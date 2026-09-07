export class ExecutionInterrupted extends Error {}

/** Catch KeyboardInterrupt inside Python before it escapes the asyncio task. */
export function createPythonExecutor(pyodide) {
    const helperGlobals = pyodide.toPy({});
    pyodide.runPython(`
from pyodide.code import eval_code_async

async def execute(source, namespace):
    try:
        result = await eval_code_async(source, globals=namespace, filename="main.py")
        return False, result
    except KeyboardInterrupt:
        return True, None
`, { globals: helperGlobals, filename: '<courser-runner>' });
    const execute = helperGlobals.get('execute');
    helperGlobals.destroy();

    return async (source, globals) => {
        const outcome = await execute(source, globals);
        try {
            if (outcome.get(0)) throw new ExecutionInterrupted('Execution interrupted');
            return outcome.get(1);
        } finally {
            outcome.destroy();
        }
    };
}
