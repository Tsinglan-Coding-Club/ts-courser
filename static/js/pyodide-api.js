/**
 * pyodide-api.js — Worker Communication Layer
 *
 * Manages the Web Worker lifecycle and provides a request/response
 * messaging pattern for communicating with the Pyodide worker.
 *
 * Reference: Pyodide docs — "Using Pyodide in a web worker"
 */

import { isHandledExecutionError } from '/static/js/python-error.mjs?v=2';
import { createStdinRequest } from './stdin-channel.mjs?v=1';

let _worker = null;
let _pendingRequests = new Map();
let _lastId = 1;
let _activeExecutionId = null;
let _stopping = false;

/** Generate a unique message ID */
function _getId() {
    return _lastId++;
}

/** Create a promise with its resolve/reject exposed */
function _deferred() {
    let resolve, reject;
    const promise = new Promise((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
}

/**
 * Get (or create) the Pyodide Worker singleton.
 * @returns {Worker}
 */
export function getWorker() {
    if (!_worker) {
        _worker = new Worker('/static/js/pyodide-worker.js?v=6', { type: 'module' });
        _setupWorkerListeners(_worker);
    }
    return _worker;
}

/**
 * Set up the global message listener for the worker.
 * Handles both request/response messages and special event types (stdin, etc.).
 */
function _setupWorkerListeners(worker) {
    worker.addEventListener('message', (event) => {
        if (_worker !== worker) return;
        const data = event.data;

        // --- Diagnostic: catch _dbg messages from worker ---
        if (data.type === '_dbg_stdout' || data.type === '_dbg_stderr') {
            console.warn('[DBG:X:api] ' + data.type + ' CALLED, text=' + JSON.stringify(data.text));
            return;
        }

        // --- stdin request (SharedArrayBuffer-based) ---
        if (data.type === 'stdin-init') {
            _stdinSab = data.sab;
            return;
        }

        if (data.type === 'stdin-request') {
            if (data.runId === _activeExecutionId) _handleStdinRequest(data);
            return;
        }

        if (data.type === 'interactive') {
            if (data.runId === _activeExecutionId && _onInteractive) {
                _onInteractive(data.events);
            }
            return;
        }

        // --- interrupt buffer init ---
        if (data.type === 'interrupt-init') {
            _interruptSab = data.sab;
            return;
        }

        // --- Real-time stdout/stderr streaming ---
        if (data.type === 'stdout' || data.type === 'stderr') {
            console.log('[DBG:2:api] recv ' + data.type + ' len=' + data.text.length + ' raw=' + JSON.stringify(data.text));
            if (_onStreamOutput) {
                _onStreamOutput(data.type, data.text);
            }
            return;
        }

        // --- request/response matching ---
        if (data.id !== undefined && _pendingRequests.has(data.id)) {
            if (data.id === _activeExecutionId) {
                _activeExecutionId = null;
                _closeInput();
            }
            const { resolve, reject } = _pendingRequests.get(data.id);
            _pendingRequests.delete(data.id);

            // Python exceptions and user interrupts are normal execution
            // results. Only communication/runtime failures reject the request.
            if (data.error && !isHandledExecutionError(data)) {
                reject(new Error(data.error));
            } else {
                resolve(data);
            }
        }
    });

    const handleWorkerFailure = (event) => {
        if (_worker !== worker) return;
        console.error('[pyodide-api] Worker failure:', event);
        for (const { reject } of _pendingRequests.values()) {
            reject(new Error('Python environment error.'));
        }
        _pendingRequests.clear();
        if (_worker === worker) {
            worker.terminate();
            _worker = null;
        }
        _stdinSab = null;
        _interruptSab = null;
        _activeExecutionId = null;
        _closeInput();
    };

    worker.addEventListener('error', handleWorkerFailure);
    worker.addEventListener('messageerror', handleWorkerFailure);
}

// ---- Real-time stream callback ----

let _onStreamOutput = null;

/**
 * Set a callback for real-time stdout/stderr streaming from the worker.
 * Called as Python produces output, before execution completes.
 * @param {function(type: string, text: string): void} callback
 */
export function onStreamOutput(callback) {
    _onStreamOutput = callback;
}

// ---- SharedArrayBuffer stdin support ----

let _stdinSab = null;
let _interruptSab = null;
let _inputRequest = null;
let _onInputRequest = null;
let _onInputClosed = null;
let _onInteractive = null;

export function onInputRequest(callback, onClosed) {
    _onInputRequest = callback;
    _onInputClosed = onClosed;
}

export function onInteractive(callback) {
    _onInteractive = callback;
}

function _closeInput() {
    if (_inputRequest) {
        _inputRequest.cancel();
        return;
    }
    if (_onInputClosed) _onInputClosed();
}

function _handleStdinRequest(data) {
    if (!_stdinSab) {
        console.error('[pyodide-api] stdin-request received but no SAB initialized');
        return;
    }

    _closeInput();
    const prompt = data.prompt || '';
    _inputRequest = createStdinRequest(_stdinSab, prompt, response => {
        if (_onStreamOutput) {
            _onStreamOutput('stdout', prompt);
            _onStreamOutput('input', response + '\n');
        }
    }, () => {
        _inputRequest = null;
        if (_onInputClosed) _onInputClosed();
    });
    if (_onInputRequest && !_stopping) _onInputRequest(_inputRequest);
    else _inputRequest.cancel();
}

// ---- Interrupt & Termination ----

/**
 * Send an interrupt signal (SIGINT) to the running Python code.
 * Writes 2 into the interrupt SharedArrayBuffer, triggering KeyboardInterrupt.
 */
export function writeInterrupt() {
    _stopping = true;
    if (_interruptSab) new Uint8Array(_interruptSab)[0] = 2;
    _closeInput();
}

/**
 * Hard-terminate the Pyodide worker. Use as last resort when
 * KeyboardInterrupt doesn't stop execution (e.g., swallowed by except:).
 * The next call to getWorker() will create a fresh worker.
 */
export function terminateWorker() {
    _activeExecutionId = null;
    _closeInput();
    if (_worker) {
        for (const { resolve } of _pendingRequests.values()) {
            resolve({
                error: 'Execution interrupted',
                errorKind: 'interrupted',
                interrupted: true,
                results: [],
            });
        }
        _pendingRequests.clear();
        _worker.terminate();
        _worker = null;
    }
    _stdinSab = null;
    _interruptSab = null;
}

/**
 * Send a message to the worker and wait for the response with matching ID.
 * @param {Worker} worker
 * @param {object} msg
 * @returns {Promise<object>}
 */
export function requestResponse(worker, msg) {
    const { promise, resolve, reject } = _deferred();
    const id = _getId();

    if (msg.type === 'run' || msg.type === 'judge') {
        if (_activeExecutionId !== null) throw new Error('Python is already running.');
        _closeInput();
        _activeExecutionId = id;
        _stopping = false;
        // Clear the previous run's signal before dispatch, so a Stop arriving
        // while the worker starts up cannot be overwritten by worker setup.
        if (_interruptSab) new Uint8Array(_interruptSab)[0] = 0;
    }

    _pendingRequests.set(id, { resolve, reject });
    try {
        worker.postMessage({ id, ...msg });
    } catch (error) {
        _pendingRequests.delete(id);
        if (_activeExecutionId === id) _activeExecutionId = null;
        console.error('[pyodide-api] Failed to send worker request:', error);
        reject(new Error('Python environment error.'));
    }
    return promise;
}

/**
 * Run Python code in the worker.
 * @param {string} script - Python code to execute
 * @param {object} context - JS object to inject as Python globals
 * @param {string[]} apis - List of API names to enable
 * @returns {Promise<{result: any, stdout: string, stderr: string, error: string|null, errorKind: string|null, interrupted: boolean}>}
 */
export async function asyncRun(script, context = {}, apis = []) {
    const worker = getWorker();
    const response = await requestResponse(worker, {
        type: 'run',
        python: script,
        context,
        apis,
    });

    return {
        result: response.result,
        stdout: response.stdout || '',
        stderr: response.stderr || '',
        error: response.error || null,
        errorKind: response.errorKind || null,
        interrupted: response.interrupted || false,
    };
}

/**
 * Send a reset-namespace command to the worker.
 */
export async function resetNamespace() {
    const worker = getWorker();
    return requestResponse(worker, { type: 'reset' });
}

/**
 * Run Python code against test cases for automated checking.
 * @param {string} script - Python code to judge
 * @param {Array<{input: string, expected: string}>} testCases
 * @param {string[]} apis - List of API names to enable
 * @returns {Promise<{results: Array, error: string|null, errorKind: string|null, interrupted: boolean}>}
 */
export async function asyncJudge(script, testCases, apis = []) {
    const worker = getWorker();
    const response = await requestResponse(worker, {
        type: 'judge',
        python: script,
        testCases,
        apis,
    });
    return {
        results: response.results || [],
        error: response.error || null,
        errorKind: response.errorKind || null,
        interrupted: response.interrupted || false,
    };
}

/**
 * Ping the worker to check readiness.
 */
export async function ping() {
    const worker = getWorker();
    return requestResponse(worker, { type: 'ping' });
}
