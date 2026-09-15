import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { loadPyodide } from 'pyodide';

import { formatPythonError } from '../python-error.mjs';

const pyodideIndex = fileURLToPath(
    new URL('../../../node_modules/pyodide/', import.meta.url)
);

const pyodidePromise = loadPyodide({ indexURL: pyodideIndex });

async function runAndFormat(code) {
    const pyodide = await pyodidePromise;
    try {
        await pyodide.runPythonAsync(code, { filename: 'main.py' });
        assert.fail('Expected Python code to raise');
    } catch (error) {
        return formatPythonError(error.message);
    }
}

test('formats a real Pyodide NameError without runtime frames', async () => {
    const result = await runAndFormat('print(missing)');

    assert.match(result, /^Traceback \(most recent call last\):/);
    assert.match(result, /File "main\.py", line 1/);
    assert.match(result, /NameError: name 'missing' is not defined$/);
    assert.doesNotMatch(result, /pyodide|wasm|eval_code_async/i);
});

test('formats a real Pyodide SyntaxError like Python', async () => {
    const result = await runAndFormat('if True print(1)');

    assert.match(result, /^  File "main\.py", line 1/);
    assert.match(result, /\^+/);
    assert.match(result, /SyntaxError: invalid syntax$/);
    assert.doesNotMatch(result, /Traceback|pyodide|wasm/i);
});

test('formats a real Pyodide IndentationError like Python', async () => {
    const result = await runAndFormat('if True:\nprint(1)');

    assert.match(result, /^  File "main\.py", line 2/);
    assert.match(result, /IndentationError:/);
    assert.doesNotMatch(result, /Traceback|pyodide|wasm/i);
});

test('keeps all student frames from a real nested traceback', async () => {
    const result = await runAndFormat(`def divide():
    return 1 / 0

divide()`);

    assert.match(result, /line 4, in <module>/);
    assert.match(result, /line 2, in divide/);
    assert.match(result, /ZeroDivisionError: division by zero$/);
    assert.doesNotMatch(result, /pyodide|wasm|eval_code_async/i);
});

test('cleans a real Pyodide ExceptionGroup traceback', async () => {
    const result = await runAndFormat(
        'raise ExceptionGroup("many", [ValueError("bad"), TypeError("wrong")])'
    );

    assert.match(result, /File "main\.py", line 1/);
    assert.match(result, /ExceptionGroup: many \(2 sub-exceptions\)/);
    assert.match(result, /ValueError: bad/);
    assert.match(result, /TypeError: wrong/);
    assert.doesNotMatch(result, /pyodide|wasm|eval_code_async|CodeRunner/i);
});
