/** Install the website's Python module and deliver bounded display snapshots. */
export function createCourserRuntime(pyodide, source, send, now = () => performance.now()) {
    // Use Python's actual installation directory rather than assuming a version.
    const sitePackages = pyodide.runPython('__import__("sysconfig").get_path("purelib")');
    pyodide.FS.writeFile(`${sitePackages}/courser.py`, source, { encoding: 'utf8' });

    let module = null;
    let runId = null;
    let enabled = false;
    let lastFlush = -Infinity;
    const pending = new Map();

    function flush() {
        if (pending.size && enabled && runId !== null) {
            send({ type: 'interactive', runId, events: [...pending.values()] });
        }
        pending.clear();
        lastFlush = now();
    }

    function receive(serialized) {
        if (!enabled || runId === null) return;
        const event = JSON.parse(serialized);
        const key = event.type === 'map' ? 'map' : `display:${JSON.stringify(event.label)}`;
        pending.set(key, event);
        // Python can keep this worker busy without yielding to JS timers. Check
        // the clock on calls, retaining only the latest snapshot in each slot.
        if (now() - lastFlush >= 16) flush();
    }

    function end() {
        flush();
        enabled = false;
        runId = null;
        if (module) {
            module.destroy();
            module = null;
        }
    }

    function begin(id, displayEnabled = true) {
        end();
        const sys = pyodide.pyimport('sys');
        const modules = sys.modules;
        try {
            // Fresh student globals alone do not clear imported module state.
            if (modules.has('courser')) modules.delete('courser');
        } finally {
            modules.destroy();
            sys.destroy();
        }
        module = pyodide.pyimport('courser');
        runId = id;
        enabled = displayEnabled;
        lastFlush = -Infinity;
        module._configure(receive, enabled);
    }

    return { begin, flush, end };
}
