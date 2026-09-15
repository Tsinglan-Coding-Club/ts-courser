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
import { createApiWrapper, initStdin, stdinWithPrompt, getDiagnostics, setStdinExecution } from '/static/js/worker-apis.js?v=2';
import { createCourserRuntime } from './courser-runtime.mjs?v=1';
import { createPythonExecutor, ExecutionInterrupted } from './python-execution.mjs?v=1';
import {
    isUserPythonError,
    normalizeExecutionError,
} from '/static/js/python-error.mjs?v=2';

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
let _courserRuntime = null;
let _executePython = null;

function normalizeRunError(error) {
    if (error instanceof ExecutionInterrupted) {
        return { error: 'Execution interrupted', errorKind: 'interrupted', interrupted: true };
    }
    return normalizeExecutionError(error);
}
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
    const [pyodide, courserSource] = await Promise.all([
        loadPyodide({
            indexURL: '/static/pyodide/',
            env: { PYTHONUNBUFFERED: '1' },
        }),
        fetch('/static/python/courser.py?v=1').then(response => {
            if (!response.ok) throw new Error('Could not load the courser Python library.');
            return response.text();
        }),
    ]);
    _courserRuntime = createCourserRuntime(pyodide, courserSource, message => self.postMessage(message));
    _executePython = createPythonExecutor(pyodide);
    console.log('[pyodide-worker] Pyodide loaded. Version:', pyodide.version);

    // Set up stdin: override Python's input() to pass prompt explicitly,
    // because Pyodide's stdin callback doesn't receive the prompt argument.
    const stdinOk = initStdin(() => _courserRuntime.flush());
    if (stdinOk) {
        pyodide.globals.set('_stdin_with_prompt', stdinWithPrompt);
        await pyodide.runPythonAsync(`
import builtins

def _make_input(read):
    def _custom_input(prompt=""):
        response = read(str(prompt))
        if not response[0]:
            raise EOFError("Input cancelled")
        return response[1]
    return _custom_input

builtins.input = _make_input(_stdin_with_prompt)
`, { filename: '<courser-runner>' });
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
    const { id, type, python, context, apis, testCases } = event.data;

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

            case 'judge':
                await _runJudge(pyodide, id, python, testCases, apis);
                break;

            default:
                console.error('[pyodide-worker] Unknown message type:', type);
                self.postMessage({
                    id,
                    error: 'Python environment error.',
                    errorKind: 'internal',
                });
        }
    } catch (error) {
        // Catch initialization failures (e.g., Pyodide load failed)
        console.error('[pyodide-worker] Worker initialization failed:', error);
        self.postMessage({
            id,
            error: 'Python environment error.',
            errorKind: 'internal',
            diagnostics: getDiagnostics(),
        });
    }
};

// ---------------------------------------------------------------------------
// Python Execution
// ---------------------------------------------------------------------------

async function _runPython(pyodide, id, python, context, apis) {
    _stdoutBuffer = '';
    _stderrBuffer = '';
    let globals;
    let response;
    try {
        // The site's courser.py is already installed. This loader handles
        // other known imports such as numpy; it does not fetch custom modules.
        try {
            await pyodide.loadPackagesFromImports(python);
        } catch (error) {
            if (!isUserPythonError(error) || !['SyntaxError', 'IndentationError', 'TabError'].includes(error.type)) throw error;
        }
        globals = _buildGlobals(pyodide, context || {}, apis || []);
        _courserRuntime.begin(id);
        setStdinExecution(id);
        const result = await _executePython(python, globals);
        try {
            response = { id, result: _convertResult(result) };
        } finally {
            result?.destroy?.();
        }
    } catch (error) {
        const normalized = normalizeRunError(error);
        if (normalized.errorKind === 'internal') console.error('[pyodide-worker] Execution failed:', error);
        response = { id, ...normalized };
    } finally {
        // Deliver the final coalesced snapshot before the completion message.
        _courserRuntime.end();
        setStdinExecution(null);
        globals?.destroy();
    }
    self.postMessage({ ...response, stdout: _stdoutBuffer, stderr: _stderrBuffer });
}

// ---------------------------------------------------------------------------
// Automated test checking — batched test case execution
// ---------------------------------------------------------------------------

/**
 * Run submitted code against multiple test cases.
 * Each test case gets isolated stdin/stdout. Execution stops early on interrupt.
 *
 * @param {object} pyodide
 * @param {number} id - Request ID
 * @param {string} python - Python code to judge
 * @param {Array<{input: string, expected: string}>} testCases
 * @param {string[]} apis - Registered API names
 */
async function _runJudge(pyodide, id, python, testCases, apis) {
    const results = [];
    let interrupted = false;
    for (const testCase of testCases || []) {
        if (interrupted) {
            results.push({
                passed: false, input: testCase.input || '', expected: testCase.expected || '',
                actual: '', error: 'Skipped (interrupted)', interrupted: true,
            });
            continue;
        }
        _stdoutBuffer = '';
        _stderrBuffer = '';
        let globals;
        let inputGlobals;
        try {
            globals = _buildGlobals(pyodide, {}, apis || []);
            _courserRuntime.begin(id, false);
            // Keep this helper out of student globals and restore it even if
            // Python execution fails or is stopped during the test case.
            inputGlobals = pyodide.toPy({ lines: (testCase.input || '').split('\n') });
            pyodide.runPython(`
import builtins
original_input = builtins.input
line_iterator = iter(lines)
def judge_input(prompt=""):
    return next(line_iterator, "")
builtins.input = judge_input
`, { globals: inputGlobals });
            const result = await _executePython(python, globals);
            result?.destroy?.();
            const actual = _stdoutBuffer.trim();
            const expected = (testCase.expected || '').trim();
            results.push({ passed: actual === expected, input: testCase.input || '', expected: testCase.expected || '', actual });
        } catch (error) {
            const normalized = normalizeRunError(error);
            if (normalized.errorKind === 'internal') {
                console.error('[pyodide-worker] Test execution failed:', error);
                self.postMessage({ id, ...normalized, results });
                return;
            }
            if (normalized.interrupted) interrupted = true;
            results.push({
                passed: false, input: testCase.input || '', expected: testCase.expected || '',
                actual: _stdoutBuffer.trim(), error: normalized.interrupted ? 'Interrupted' : normalized.error,
                errorKind: normalized.errorKind, interrupted: normalized.interrupted || undefined,
            });
        } finally {
            if (inputGlobals) {
                // Reset the signal only after recording the interrupted result,
                // otherwise restoring input would itself be interrupted.
                if (_interruptBuf && interrupted) _interruptBuf[0] = 0;
                try {
                    pyodide.runPython('builtins.input = original_input', { globals: inputGlobals });
                } finally {
                    inputGlobals.destroy();
                }
            }
            _courserRuntime.end();
            globals?.destroy();
        }
    }
    self.postMessage({ id, results });
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
    const globals = pyodide.toPy(context);
    globals.set('__name__', '__main__');

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
    _courserRuntime.end();
    const result = pyodide.runPython(`
(lambda namespace: [namespace.pop(name, None) for name in list(namespace)
                    if not name.startswith('__') and not name.startswith('_pyodide')])(globals())
`);
    result.destroy();
}
