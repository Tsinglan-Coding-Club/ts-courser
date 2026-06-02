/**
 * pyodide-worker.js — Web Worker for Pyodide Python Execution
 *
 * This worker:
 *   1. Loads Pyodide (CPython compiled to WebAssembly)
 *   2. Receives execution requests from the main thread
 *   3. Runs Python code with injected globals + custom API functions
 *   4. Captures stdout/stderr and returns results
 *
 * Reference: Pyodide docs — "Using Pyodide in a web worker"
 */

import { loadPyodide } from '/static/pyodide/pyodide.mjs?v=3';
import { createApiWrapper, initStdin, stdinWithPrompt, getDiagnostics } from '/static/js/worker-apis.js';

// ---------------------------------------------------------------------------
// Diagnostic: environment check (runs immediately)
// ---------------------------------------------------------------------------

console.log('[pyodide-worker] Worker started. Diagnostics:', JSON.stringify(getDiagnostics()));

// ---------------------------------------------------------------------------
// Pyodide Initialization (preload — starts immediately)
// ---------------------------------------------------------------------------

let _stdoutBuffer = '';
let _stderrBuffer = '';
let _stdinEnabled = false;
let _interruptBuf = null;
// Named stdout/stderr writers for batched output.
// Per Pyodide docs: batched is called when \n is written (line will END
// with \n) OR when stdout is flushed (line will NOT end with \n).
// This naturally supports both print("x") and print("x", end="").
const _stdoutWrite = (text) => {
    _stdoutBuffer += text;
    // Diagnostic: send to main thread (bypasses worker console isolation)
    self.postMessage({ type: '_dbg_stdout', text: text });
    console.warn('[DBG:1:worker] stdout batched len=' + text.length + ' text=' + JSON.stringify(text));
    self.postMessage({ type: 'stdout', text });
};
const _stderrWrite = (text) => {
    _stderrBuffer += text;
    self.postMessage({ type: '_dbg_stderr', text: text });
    console.warn('[DBG:1:worker] stderr batched len=' + text.length + ' text=' + JSON.stringify(text));
    self.postMessage({ type: 'stderr', text });
};

let pyodideReady = (async () => {
    console.log('[pyodide-worker] Loading Pyodide...');
    const pyodide = await loadPyodide({
        indexURL: '/static/pyodide/',
        env: { PYTHONUNBUFFERED: '1' },
    });
    console.log('[pyodide-worker] Pyodide loaded. Version:', pyodide.version);

    // Set up stdin: override Python's input() to pass prompt explicitly,
    // because Pyodide's stdin callback doesn't receive the prompt argument.
    const stdinOk = initStdin();
    if (stdinOk) {
        pyodide.globals.set('_stdin_with_prompt', stdinWithPrompt);
        await pyodide.runPythonAsync(`
import builtins

def _custom_input(prompt=""):
    return _stdin_with_prompt(str(prompt))

builtins.input = _custom_input
`);
        _stdinEnabled = true;
        console.log('[pyodide-worker] stdin (input()) enabled with prompt support.');
    } else {
        _stdinEnabled = false;
        console.warn('[pyodide-worker] stdin disabled. Python input() will raise an error.');
    }

    // Use Pyodide's write handler — receives raw Uint8Array bytes from
    // Emscripten C layer, including \n (ASCII 10). No buffering: every
    // Python write() triggers this immediately, even print("x", end="").
    pyodide.setStdout({
        write: (buffer) => {
            const text = new TextDecoder().decode(buffer);
            _stdoutBuffer += text;
            console.warn('[DBG:1:worker] stdout write len=' + buffer.length + ' text=' + JSON.stringify(text));
            self.postMessage({ type: 'stdout', text });
            return buffer.length;
        },
        isatty: false,
    });
    pyodide.setStderr({
        write: (buffer) => {
            const text = new TextDecoder().decode(buffer);
            _stderrBuffer += text;
            console.warn('[DBG:1:worker] stderr write len=' + buffer.length + ' text=' + JSON.stringify(text));
            self.postMessage({ type: 'stderr', text });
            return buffer.length;
        },
        isatty: false,
    });
    console.log('[pyodide-worker] Write stdout/stderr enabled via setStdout({write}).');

    // Set up interrupt buffer for KeyboardInterrupt (Stop button)
    // Uses 1-byte SharedArrayBuffer — write 2 to trigger SIGINT
    try {
        _interruptBuf = new Uint8Array(new SharedArrayBuffer(1));
        pyodide.setInterruptBuffer(_interruptBuf);
        self.postMessage({ type: 'interrupt-init', sab: _interruptBuf.buffer });
        console.log('[pyodide-worker] Interrupt buffer initialized.');
    } catch (e) {
        console.warn('[pyodide-worker] Interrupt buffer unavailable:', e.message);
    }

    // Expose for worker-apis.js (checkInterrupt during stdin wait)
    self._pyodide = pyodide;

    return pyodide;
})();

// ---------------------------------------------------------------------------
// Message Handler
// ---------------------------------------------------------------------------

self.onmessage = async (event) => {
    const { id, type, python, context, apis } = event.data;

    try {
        const pyodide = await pyodideReady;

        switch (type) {
            case 'ping':
                self.postMessage({
                    id,
                    result: 'pong',
                    pyodideVersion: pyodide.version,
                    stdinEnabled: _stdinEnabled,
                    diagnostics: getDiagnostics(),
                });
                break;

            case 'reset':
                await _resetNamespace(pyodide);
                self.postMessage({ id, result: 'ok' });
                break;

            case 'run':
                await _runPython(pyodide, id, python, context, apis);
                break;

            default:
                self.postMessage({ id, error: `Unknown message type: ${type}` });
        }
    } catch (error) {
        // Catch initialization failures (e.g., Pyodide load failed)
        self.postMessage({
            id,
            error: `Worker initialization failed: ${error.message || String(error)}`,
            diagnostics: getDiagnostics(),
        });
    }
};

// ---------------------------------------------------------------------------
// Python Execution
// ---------------------------------------------------------------------------

async function _runPython(pyodide, id, python, context, apis) {
    // Reset per-run buffers
    _stdoutBuffer = '';
    _stderrBuffer = '';

    // Load any packages imported by the script
    try {
        await pyodide.loadPackagesFromImports(python);
    } catch (e) {
        _stderrBuffer += `[Package load warning] ${e.message || e}\n`;
    }

    // Build the globals dict: context data + custom API functions
    let globals;
    try {
        globals = _buildGlobals(pyodide, context || {}, apis || []);
    } catch (e) {
        self.postMessage({
            id,
            error: `Failed to build execution context: ${e.message}`,
            stdout: _stdoutBuffer,
            stderr: _stderrBuffer,
        });
        return;
    }

    // Execute
    try {
        // Clear any stale interrupt signal before running
        if (_interruptBuf) _interruptBuf[0] = 0;

        const result = await pyodide.runPythonAsync(python, { globals });
        self.postMessage({
            id,
            result: _convertResult(result),
            stdout: _stdoutBuffer,
            stderr: _stderrBuffer,
        });
    } catch (error) {
        const message = error.message || String(error);
        const interrupted = message.includes('KeyboardInterrupt');
        self.postMessage({
            id,
            error: interrupted ? 'Execution interrupted' : message,
            stdout: _stdoutBuffer,
            stderr: _stderrBuffer,
            interrupted: interrupted || undefined,
        });
    }
}

// ---------------------------------------------------------------------------
// Globals Builder
// ---------------------------------------------------------------------------

/**
 * Build a Python globals dict from:
 *   - `context`: plain JS object → Python dict
 *   - `apis`: list of API names → Python-callable wrapped handlers
 */
function _buildGlobals(pyodide, context, apis) {
    const PyDict = pyodide.globals.get('dict');

    // Convert JS context object to Python dict
    const entries = Object.entries(context).map(([k, v]) => [k, _jsToPython(pyodide, v)]);
    const globals = PyDict(entries);

    // Inject custom API functions
    for (const apiName of apis) {
        const wrapper = createApiWrapper(pyodide, apiName);
        if (wrapper) {
            globals.set(apiName, wrapper);
        } else {
            _stderrBuffer += `[API warning] Unknown API "${apiName}" — not registered in worker-apis.js\n`;
        }
    }

    return globals;
}

/**
 * Recursively convert a JS value to a Python-compatible value via Pyodide FFI.
 */
function _jsToPython(pyodide, value) {
    if (value === null || value === undefined) return null;
    if (Array.isArray(value)) {
        return pyodide.globals.get('list')(value.map(v => _jsToPython(pyodide, v)));
    }
    if (typeof value === 'object') {
        const PyDict = pyodide.globals.get('dict');
        const entries = Object.entries(value).map(([k, v]) => [k, _jsToPython(pyodide, v)]);
        return PyDict(entries);
    }
    // Primitives: numbers, strings, booleans pass through directly
    return value;
}

/**
 * Convert Python result to a JSON-safe JS value for postMessage.
 */
function _convertResult(result) {
    if (result === undefined || result === null) return null;
    try {
        if (typeof result.toJs === 'function') {
            const js = result.toJs();
            // Convert Python dict to plain object recursively
            return _pyDictToObject(js);
        }
    } catch (_) { /* fall through */ }
    return String(result);
}

function _pyDictToObject(value) {
    if (value === null || value === undefined) return null;
    if (Array.isArray(value)) return value.map(_pyDictToObject);
    if (typeof value === 'object' && value.constructor === Map) {
        const obj = {};
        for (const [k, v] of value) {
            obj[k] = _pyDictToObject(v);
        }
        return obj;
    }
    return value;
}

// ---------------------------------------------------------------------------
// Namespace Reset
// ---------------------------------------------------------------------------

/**
 * Clear user-defined globals while preserving builtins.
 * Runs in the same Pyodide instance to keep the runtime warm.
 */
async function _resetNamespace(pyodide) {
    // Gather names to delete (all non-builtin, non-dunder globals)
    await pyodide.runPythonAsync(`
import builtins as _b
_keep = set(dir(_b)) | {'__builtins__', '__name__', '__doc__', '__package__'}
for _k in list(globals().keys()):
    if _k not in _keep and not _k.startswith('_pyodide'):
        del globals()[_k]
`);
}
