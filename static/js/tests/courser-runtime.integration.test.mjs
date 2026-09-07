import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { loadPyodide } from 'pyodide';
import { createCourserRuntime } from '../courser-runtime.mjs';

test('real Pyodide imports courser, preserves snapshots, resets imports, and silences judging', async () => {
    const pyodide = await loadPyodide({ indexURL: fileURLToPath(new URL('../../../node_modules/pyodide/', import.meta.url)) });
    const source = readFileSync(new URL('../../python/courser.py', import.meta.url), 'utf8');
    const messages = [];
    const runtime = createCourserRuntime(pyodide, source, message => messages.push(message), () => 0);
    const execute = code => {
        const globals = pyodide.toPy({ __name__: '__main__' });
        try { pyodide.runPython(code, { globals }); }
        finally { globals.destroy(); }
    };

    runtime.begin(1);
    await pyodide.loadPackagesFromImports('from courser import display, display_map, define_symbol');
    execute(`
from courser import display, display_map, define_symbol
define_symbol(7, '🧱')
data = [[7, 0]]
display_map(data)
data[0][1] = 9
display(12345678901234567890, label='score')
for i in range(1000):
    display(i)
`);
    runtime.end();
    assert.equal(messages.length, 2, 'coalesce rapid updates rather than flooding the page');
    assert.equal(messages[0].events[0].value.items[0].items[1].text, '0');
    assert.equal(messages[0].events[0].symbols[0].text, '🧱');
    assert.deepEqual(messages[1].events.map(event => [event.label, event.value.text]), [
        ['score', '12345678901234567890'], [null, '999'],
    ]);
    assert.equal(pyodide.globals.has('display'), false);

    messages.length = 0;
    runtime.begin(2);
    execute('from courser import display_map; display_map([[7]])');
    runtime.end();
    assert.deepEqual(messages[0].events[0].symbols, []);
    assert.equal(messages[0].runId, 2);

    messages.length = 0;
    runtime.begin(3, false);
    execute('from courser import display, display_map; display(1); display_map([[2]])');
    assert.throws(() => execute('from courser import display_map; display_map([[1], [2, 3]])'), /rectangular/);
    runtime.end();
    assert.deepEqual(messages, []);
});
