/**
 * pyodide-api.js — Worker Communication Layer
 *
 * Manages the Web Worker lifecycle and provides a request/response
 * messaging pattern for communicating with the Pyodide worker.
 *
 * Reference: Pyodide docs — "Using Pyodide in a web worker"
 */

let _worker = null;
let _pendingRequests = new Map();
let _lastId = 1;

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
        _worker = new Worker('/static/js/pyodide-worker.js', { type: 'module' });
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
        const data = event.data;

        // --- stdin request (SharedArrayBuffer-based) ---
        if (data.type === 'stdin-init') {
            _stdinSab = data.sab;
            return;
        }

        if (data.type === 'stdin-request') {
            _handleStdinRequest(data);
            return;
        }

        // --- interrupt buffer init ---
        if (data.type === 'interrupt-init') {
            _interruptSab = data.sab;
            return;
        }

        // --- Real-time stdout/stderr streaming ---
        if (data.type === 'stdout' || data.type === 'stderr') {
            if (_onStreamOutput) {
                _onStreamOutput(data.type, data.text);
            }
            return;
        }

        // --- request/response matching ---
        if (data.id !== undefined && _pendingRequests.has(data.id)) {
            const { resolve, reject } = _pendingRequests.get(data.id);
            _pendingRequests.delete(data.id);

            if (data.error) {
                reject(new Error(data.error));
            } else {
                resolve(data);
            }
        }
    });
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

function _handleStdinRequest(data) {
    if (!_stdinSab) {
        console.error('[pyodide-api] stdin-request received but no SAB initialized');
        return;
    }

    // Prompt comes directly from the message (no SAB read needed).
    const prompt = data.prompt || '';

    // 1) Show browser prompt dialog (empty string = Python default)
    const response = window.prompt(prompt) || '';

    // 2) Echo prompt (white) + user input (green) on one console line
    if (_onStreamOutput) {
        _onStreamOutput('stdout', prompt);        // white, no \n
        _onStreamOutput('input', response + '\n'); // green, ends line
    }

    // Write response back to SAB for synchronous return to worker
    const status = new Int32Array(_stdinSab, 0, 1);
    const dataLen = new Int32Array(_stdinSab, 4, 1);
    const encoder = new TextEncoder();
    const encoded = encoder.encode(response);
    new Uint8Array(_stdinSab, 8, encoded.length).set(encoded);
    Atomics.store(dataLen, 0, encoded.length);
    Atomics.store(status, 0, 2); // status = "has-response"

    // Wake the worker
    Atomics.notify(status, 0, 1);
}

// ---- Interrupt & Termination ----

/**
 * Send an interrupt signal (SIGINT) to the running Python code.
 * Writes 2 into the interrupt SharedArrayBuffer, triggering KeyboardInterrupt.
 */
export function writeInterrupt() {
    if (!_interruptSab) return;
    new Uint8Array(_interruptSab)[0] = 2;
}

/**
 * Hard-terminate the Pyodide worker. Use as last resort when
 * KeyboardInterrupt doesn't stop execution (e.g., swallowed by except:).
 * The next call to getWorker() will create a fresh worker.
 */
export function terminateWorker() {
    if (_worker) {
        _worker.terminate();
        _worker = null;
        _pendingRequests.clear();
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

    _pendingRequests.set(id, { resolve, reject });
    worker.postMessage({ id, ...msg });
    return promise;
}

/**
 * Run Python code in the worker.
 * @param {string} script - Python code to execute
 * @param {object} context - JS object to inject as Python globals
 * @param {string[]} apis - List of API names to enable
 * @returns {Promise<{result: any, stdout: string, stderr: string, error: string|null}>}
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
 * Ping the worker to check readiness.
 */
export async function ping() {
    const worker = getWorker();
    return requestResponse(worker, { type: 'ping' });
}
