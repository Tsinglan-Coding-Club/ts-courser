/**
 * worker-apis.js — Custom API Registry (runs inside Web Worker)
 *
 * ★ EXTENSION POINT ★
 * To add a new API function callable from Python:
 *   1. Add a handler to the `registry` Map below
 *   2. On the main thread, listen for 'api-call' messages
 *
 * The handler can either:
 *   - Run entirely in the worker (pure computation) → return value directly
 *   - Post a message to the main thread (DOM access) → fire-and-forget
 */

// ============================================================================
// API Registry — add custom API handlers here
// ============================================================================

import {
    STDIN_SAB_SIZE, STDIN_HEADER_SIZE, STDIN_IDLE, STDIN_WAITING, STDIN_READY,
} from './stdin-channel.mjs?v=1';

const registry = new Map();

// Example API: sends a message to the main thread (verifies the pipeline works)
registry.set('print_message', (msg) => {
    self.postMessage({
        type: 'api-call',
        api: 'print_message',
        args: [String(msg)],
    });
    return null;
});

// ============================================================================
// Python Wrapper Factory
// ============================================================================

/**
 * Create a Python-callable wrapper for a registered API handler.
 * Pyodide automatically converts JS functions in Python globals dicts
 * to Python callables, so we just return the raw wrapped function.
 *
 * @param {object} pyodide - The Pyodide runtime instance
 * @param {string} name - The API name (must exist in registry)
 * @returns {Function|null} A JS function (Pyodide auto-wraps for Python), or null
 */
export function createApiWrapper(pyodide, name) {
    const handler = registry.get(name);
    if (!handler) return null;

    const wrapped = (...args) => {
        // Convert PyProxy args to plain JS values
        const jsArgs = args.map((a) => {
            try {
                if (a !== null && a !== undefined && typeof a.toJs === 'function') {
                    return a.toJs();
                }
            } catch (_) { /* fall through */ }
            return a;
        });
        return handler(...jsArgs);
    };

    // Pyodide auto-converts JS functions in globals to Python callables.
    // No manual create_proxy needed.
    return wrapped;
}

/**
 * Get the list of all registered API names.
 * @returns {string[]}
 */
export function getRegisteredApiNames() {
    return Array.from(registry.keys());
}

// ============================================================================
// SharedArrayBuffer stdin — supports Python's input() via Atomics.wait
// ============================================================================

let _stdinSab = null;
let _stdinStatus = null;
let _stdinDataLen = null;
let _stdinAvailable = false; // true if SharedArrayBuffer+Atomics are usable
let _beforeInput = () => {};
let _executionId = null;

export function setStdinExecution(id) {
    _executionId = id;
}

// ---- Diagnostic helpers ----

function _diagnose() {
    const info = {
        crossOriginIsolated: (typeof crossOriginIsolated !== 'undefined') ? crossOriginIsolated : 'undefined',
        SharedArrayBuffer: typeof SharedArrayBuffer,
        Atomics: typeof Atomics,
        AtomicsWait: typeof (Atomics && Atomics.wait),
    };
    return info;
}

// ---- Public API ----

export function isStdinAvailable() {
    return _stdinAvailable;
}

export function getDiagnostics() {
    return _diagnose();
}

/**
 * Initialize the SharedArrayBuffer for stdin.
 * Gracefully degrades if cross-origin isolation is not available.
 */
export function initStdin(beforeInput = () => {}) {
    _beforeInput = beforeInput;
    const diag = _diagnose();
    console.log('[worker-apis] Cross-origin isolation diagnostics:', JSON.stringify(diag));

    if (!diag.crossOriginIsolated) {
        console.warn(
            '[worker-apis] NOT cross-origin isolated. ' +
            'SharedArrayBuffer is unavailable — Python input() will be disabled. ' +
            'Ensure COOP/COEP headers are set on ALL responses (including static files).'
        );
        _stdinAvailable = false;
        return false;
    }

    try {
        _stdinSab = new SharedArrayBuffer(STDIN_SAB_SIZE);
        _stdinStatus = new Int32Array(_stdinSab, 0, 1);
        _stdinDataLen = new Int32Array(_stdinSab, 4, 1);
        _stdinAvailable = true;

        // Send the SAB reference to the main thread
        self.postMessage({ type: 'stdin-init', sab: _stdinSab });
        console.log('[worker-apis] SharedArrayBuffer stdin initialized successfully.');
        return true;
    } catch (err) {
        console.error('[worker-apis] Failed to create SharedArrayBuffer:', err.message);
        _stdinAvailable = false;
        return false;
    }
}

/**
 * Stdin with explicit prompt — called from Python's overridden input().
 * Receives the actual prompt string and passes it to the main thread.
 * Blocks synchronously via Atomics.wait until the main thread provides input.
 *
 * @param {string} prompt - The prompt string from Python's input("...")
 * @returns {[boolean, string]} Whether input was supplied, and its text
 */
export function stdinWithPrompt(prompt) {
    if (!_stdinAvailable || !_stdinSab) {
        throw new Error('Python input() is not available.');
    }

    // Signal main thread with the real prompt
    _beforeInput();
    Atomics.store(_stdinStatus, 0, STDIN_WAITING);

    // Send prompt via postMessage (no SAB encoding needed — main thread reads data.prompt)
    self.postMessage({ type: 'stdin-request', runId: _executionId, prompt: String(prompt || '') });

    // Block until main thread responds (interruptible: 200ms chunks)
    try {
        while (Atomics.load(_stdinStatus, 0) === STDIN_WAITING) {
            self._pyodide?.checkInterrupt();
            Atomics.wait(_stdinStatus, 0, STDIN_WAITING, 200);
        }
        self._pyodide?.checkInterrupt();
        if (Atomics.load(_stdinStatus, 0) !== STDIN_READY) return [false, ''];

        const respLen = Atomics.load(_stdinDataLen, 0);
        const respCopy = new Uint8Array(respLen);
        respCopy.set(new Uint8Array(_stdinSab, STDIN_HEADER_SIZE, respLen));
        return [true, new TextDecoder().decode(respCopy)];
    } finally {
        Atomics.store(_stdinStatus, 0, STDIN_IDLE);
    }
}
