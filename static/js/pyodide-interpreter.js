/**
 * pyodide-interpreter.js — High-Level Interpreter API
 *
 * The single entry point for consumers (templates, UI code).
 * Wraps the Web Worker communication layer with a clean async API.
 *
 * Usage:
 *   await PyodideInterpreter.init();
 *   const { result, error, stdout, stderr } = await PyodideInterpreter.runCode(code);
 *   PyodideInterpreter.registerAPI('draw_circle');
 */

import { asyncRun, ping, resetNamespace as workerReset, onStreamOutput, writeInterrupt, terminateWorker } from '/static/js/pyodide-api.js';

const PyodideInterpreter = {
    // ---- State ----
    _ready: false,
    _initPromise: null,
    _version: null,
    _registeredApis: [],
    _streamWired: false,
    _running: false,

    // ---- Callbacks ----
    /** @type {function(type: string, text: string): void} */
    onOutput: null,

    /** @type {function(): void} */
    onReady: null,

    /** @type {function(error: Error): void} */
    onError: null,

    // ---- Public API ----

    /**
     * Initialize the interpreter (load Pyodide in the Web Worker).
     * Safe to call multiple times — subsequent calls return the cached promise.
     * @returns {Promise<void>}
     */
    async init() {
        if (this._ready) return;
        if (this._initPromise) return this._initPromise;

        // Wire up real-time stdout/stderr streaming (once)
        if (!this._streamWired) {
            onStreamOutput((type, text) => {
                if (this.onOutput) {
                    this.onOutput(type, text);
                }
            });
            this._streamWired = true;
        }

        this._initPromise = this._doInit();
        return this._initPromise;
    },

    async _doInit() {
        try {
            const pong = await ping();
            this._version = pong.pyodideVersion || 'unknown';
            this._ready = true;

            if (this.onReady) this.onReady();
        } catch (error) {
            this._initPromise = null;
            if (this.onError) this.onError(error);
            throw error;
        }
    },

    /**
     * Execute Python code and return the result.
     * stdout/stderr are streamed in real-time via onOutput callback.
     * The returned {stdout, stderr} contains the full accumulated output.
     * @param {string} code - Python source code
     * @returns {Promise<{result: any, stdout: string, stderr: string, error: string|null}>}
     */
    async runCode(code) {
        if (!this._ready) {
            throw new Error('Interpreter not initialized. Call PyodideInterpreter.init() first.');
        }

        this._running = true;
        try {
            return await asyncRun(code, {}, this._registeredApis);
        } finally {
            this._running = false;
        }
    },

    /**
     * Stop the currently running Python code by sending an interrupt signal.
     */
    stop() {
        writeInterrupt();
    },

    /**
     * Hard-terminate the worker (last resort if interrupt doesn't work).
     * Reinitializes the interpreter, requiring init() to be called again.
     */
    async hardStop() {
        terminateWorker();
        this._ready = false;
        this._initPromise = null;
        this._running = false;
        // Reinitialize immediately so the user doesn't have to wait
        try {
            await this.init();
        } catch (error) {
            // Re-initialization failed. onError has already been called
            // by _doInit(). The interpreter remains in not-ready state.
            // Callers can safely use hardStop() without try/catch.
        }
    },

    /**
     * Reset the Python namespace, clearing all user-defined variables.
     * The Pyodide runtime stays warm — no reload needed.
     * @returns {Promise<void>}
     */
    async resetNamespace() {
        if (!this._ready) return;
        await workerReset();
        if (this.onOutput) {
            this.onOutput('system', 'Namespace cleared.\n');
        }
    },

    /**
     * ★ Register a custom API function to be available in Python.
     * The API handler must be registered in worker-apis.js first.
     *
     * @param {string} name - The API name (must match worker-apis.js registry key)
     */
    registerAPI(name) {
        if (!this._registeredApis.includes(name)) {
            this._registeredApis.push(name);
        }
    },

    /**
     * Unregister a custom API.
     * @param {string} name
     */
    unregisterAPI(name) {
        const idx = this._registeredApis.indexOf(name);
        if (idx !== -1) this._registeredApis.splice(idx, 1);
    },

    // ---- Getters ----

    /** @returns {boolean} */
    get isReady() {
        return this._ready;
    },

    /** @returns {boolean} */
    get isRunning() {
        return this._running;
    },

    /** @returns {string} */
    get version() {
        return this._version || 'loading...';
    },

    /** @returns {string[]} */
    get registeredApis() {
        return [...this._registeredApis];
    },
};

export default PyodideInterpreter;
