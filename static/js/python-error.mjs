const DEFAULT_FILENAME = 'main.py';

function parseTracebackFrame(line) {
    const match = line.match(/^([ |]*?)File "([^"]+)"/);
    if (!match) return null;
    return { prefix: match[1], path: match[2] };
}

function isInternalPyodidePath(path) {
    return path === '<courser-runner>' || path.includes('/_pyodide/') || path.includes('\\_pyodide\\');
}

/**
 * Remove Pyodide's interpreter frames while preserving Python's traceback
 * formatting, user frames, exception chaining, source lines, and carets.
 */
export function formatPythonError(message, filename = DEFAULT_FILENAME) {
    const raw = String(message || '')
        .replace(/\r\n?/g, '\n')
        .replace(/^PythonError:\s*/, '')
        .trimEnd();

    if (!raw) return 'PythonError';

    const lines = raw
        .replaceAll('File "<exec>"', `File "${filename}"`)
        .split('\n');
    const cleaned = [];
    let skippingInternalFrame = false;
    let internalFramePrefix = '';

    for (const line of lines) {
        const frame = parseTracebackFrame(line);
        if (frame) {
            skippingInternalFrame = isInternalPyodidePath(frame.path);
            internalFramePrefix = skippingInternalFrame ? frame.prefix : '';
            if (!skippingInternalFrame) cleaned.push(line);
            continue;
        }

        if (skippingInternalFrame) {
            // A frame's source excerpt is indented beyond the frame prefix.
            // This also handles the visual prefixes used by ExceptionGroup.
            if (line.startsWith(internalFramePrefix) && line.length > internalFramePrefix.length) {
                continue;
            }
            skippingInternalFrame = false;
            internalFramePrefix = '';
        }

        cleaned.push(line);
    }

    // CPython reports compile-time errors without a traceback header when a
    // source file is executed directly. Match that native presentation.
    const lastLine = [...cleaned].reverse().find(line => line.trim() !== '') || '';
    if (/^(?:SyntaxError|IndentationError|TabError):/.test(lastLine)) {
        const headerIndex = cleaned.indexOf('Traceback (most recent call last):');
        if (headerIndex !== -1) cleaned.splice(headerIndex, 1);
    }

    return cleaned.join('\n').replace(/^\n+|\n+$/g, '');
}

export function isPythonError(error) {
    return Boolean(error && error.name === 'PythonError');
}

export function isUserPythonError(error) {
    return Boolean(isPythonError(error) && error.type !== 'JsException');
}

export function isKeyboardInterrupt(error) {
    return Boolean(isUserPythonError(error) && error.type === 'KeyboardInterrupt');
}

export function normalizeExecutionError(error) {
    if (isKeyboardInterrupt(error)) {
        return {
            error: 'Execution interrupted',
            errorKind: 'interrupted',
            interrupted: true,
        };
    }

    if (isUserPythonError(error)) {
        return {
            error: formatPythonError(error.message || String(error)),
            errorKind: 'python',
            interrupted: false,
        };
    }

    return {
        error: 'Python environment error.',
        errorKind: 'internal',
        interrupted: false,
    };
}

export function isHandledExecutionError(response) {
    return Boolean(
        response
        && response.error
        && ['python', 'interrupted'].includes(response.errorKind)
    );
}
