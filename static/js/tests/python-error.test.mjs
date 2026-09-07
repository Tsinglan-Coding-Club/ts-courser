import assert from 'node:assert/strict';
import test from 'node:test';

import {
    formatPythonError,
    isHandledExecutionError,
    isKeyboardInterrupt,
    isPythonError,
    isUserPythonError,
    normalizeExecutionError,
} from '../python-error.mjs';

const INTERNAL_RUNTIME_FRAME = `  File "/lib/python313.zip/_pyodide/_base.py", line 597, in eval_code_async
    await CodeRunner(
    ...<9 lines>...
    .run_async(globals, locals)
  File "/lib/python313.zip/_pyodide/_base.py", line 411, in run_async
    coroutine = eval(self.code, globals, locals)`;

test('keeps a native runtime traceback and removes Pyodide frames', () => {
    const input = `Traceback (most recent call last):
${INTERNAL_RUNTIME_FRAME}
  File "main.py", line 1, in <module>
    print(missing)
          ^^^^^^^
NameError: name 'missing' is not defined\n`;

    assert.equal(formatPythonError(input), `Traceback (most recent call last):
  File "main.py", line 1, in <module>
    print(missing)
          ^^^^^^^
NameError: name 'missing' is not defined`);
});

test('formats syntax errors like native Python file execution', () => {
    const input = `Traceback (most recent call last):
  File "/lib/python313.zip/_pyodide/_base.py", line 149, in _parse_and_compile_gen
    mod = compile(source, filename, mode, flags | ast.PyCF_ONLY_AST)
  File "main.py", line 1
    if True print(1)
            ^^^^^
SyntaxError: invalid syntax`;

    assert.equal(formatPythonError(input), `  File "main.py", line 1
    if True print(1)
            ^^^^^
SyntaxError: invalid syntax`);
});

test('preserves nested user frames', () => {
    const input = `PythonError: Traceback (most recent call last):
${INTERNAL_RUNTIME_FRAME}
  File "main.py", line 4, in <module>
    f()
  File "main.py", line 2, in f
    return 1 / 0
ZeroDivisionError: division by zero`;

    const result = formatPythonError(input);
    assert.match(result, /line 4, in <module>/);
    assert.match(result, /line 2, in f/);
    assert.match(result, /ZeroDivisionError: division by zero/);
    assert.doesNotMatch(result, /pyodide|wasm|eval_code_async/i);
});

test('preserves chained exceptions while removing internal frames', () => {
    const input = `Traceback (most recent call last):
  File "main.py", line 2, in <module>
    1 / 0
ZeroDivisionError: division by zero

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
${INTERNAL_RUNTIME_FRAME}
  File "main.py", line 4, in <module>
    raise ValueError("bad")
ValueError: bad`;

    const result = formatPythonError(input);
    assert.match(result, /ZeroDivisionError: division by zero/);
    assert.match(result, /During handling of the above exception/);
    assert.match(result, /ValueError: bad/);
    assert.doesNotMatch(result, /_pyodide|eval_code_async/);
});

test('removes internal frames from ExceptionGroup tracebacks', () => {
    const input = `  + Exception Group Traceback (most recent call last):
  |   File "/lib/python313.zip/_pyodide/_base.py", line 411, in run_async
  |     coroutine = eval(self.code, globals, locals)
  |   File "main.py", line 1, in <module>
  |     raise ExceptionGroup("many", [ValueError("bad")])
  | ExceptionGroup: many (1 sub-exception)
  +-+---------------- 1 ----------------
    | ValueError: bad
    +------------------------------------`;

    const result = formatPythonError(input);
    assert.match(result, /File "main\.py", line 1/);
    assert.match(result, /ExceptionGroup: many/);
    assert.match(result, /ValueError: bad/);
    assert.doesNotMatch(result, /_pyodide|run_async/);
});

test('renames the default Pyodide filename', () => {
    assert.equal(
        formatPythonError('  File "<exec>", line 3\nNameError: missing'),
        '  File "main.py", line 3\nNameError: missing'
    );
});

test('identifies only Pyodide PythonError objects', () => {
    assert.equal(isPythonError({ name: 'PythonError' }), true);
    assert.equal(isPythonError(new Error('network failure')), false);
    assert.equal(isPythonError(null), false);
});

test('does not classify JavaScript bridge failures as student Python errors', () => {
    assert.equal(isUserPythonError({ name: 'PythonError', type: 'NameError' }), true);
    assert.equal(isUserPythonError({ name: 'PythonError', type: 'JsException' }), false);
    assert.equal(isUserPythonError(new Error('worker failed')), false);
});

test('identifies interrupts by Python exception type, not message text', () => {
    assert.equal(isKeyboardInterrupt({ name: 'PythonError', type: 'KeyboardInterrupt' }), true);
    assert.equal(isKeyboardInterrupt({ name: 'PythonError', type: 'RuntimeError', message: 'KeyboardInterrupt' }), false);
    assert.equal(isKeyboardInterrupt(new Error('KeyboardInterrupt')), false);
});

test('normalizes student, interrupt, and infrastructure failures', () => {
    const pythonResult = normalizeExecutionError({
        name: 'PythonError',
        type: 'NameError',
        message: '  File "main.py", line 1\nNameError: missing',
    });
    assert.equal(pythonResult.errorKind, 'python');
    assert.match(pythonResult.error, /NameError: missing/);

    const interruptResult = normalizeExecutionError({
        name: 'PythonError',
        type: 'KeyboardInterrupt',
    });
    assert.deepEqual(interruptResult, {
        error: 'Execution interrupted',
        errorKind: 'interrupted',
        interrupted: true,
    });

    const bridgeResult = normalizeExecutionError({
        name: 'PythonError',
        type: 'JsException',
        message: 'pyodide.ffi.JsException: Error at wasm://internal',
    });
    assert.deepEqual(bridgeResult, {
        error: 'Python environment error.',
        errorKind: 'internal',
        interrupted: false,
    });
});

test('treats Python errors and interrupts as execution results', () => {
    assert.equal(isHandledExecutionError({ error: 'NameError', errorKind: 'python' }), true);
    assert.equal(isHandledExecutionError({ error: 'Stopped', errorKind: 'interrupted' }), true);
    assert.equal(isHandledExecutionError({ error: 'Worker failed', errorKind: 'internal' }), false);
    assert.equal(isHandledExecutionError({ result: 42 }), false);
});
