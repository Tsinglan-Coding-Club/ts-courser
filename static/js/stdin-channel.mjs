/** Shared memory layout used by both the worker and the page's input form. */
export const STDIN_SAB_SIZE = 4096;
export const STDIN_HEADER_SIZE = 8;
export const STDIN_IDLE = 0;
export const STDIN_WAITING = 1;
export const STDIN_READY = 2;
export const STDIN_CANCELLED = 3;

/** One request owns its buffer; late submissions must never answer a later run. */
export function createStdinRequest(buffer, prompt, onResponse, onClose) {
    const status = new Int32Array(buffer, 0, 1);
    const length = new Int32Array(buffer, 4, 1);
    const maxBytes = buffer.byteLength - STDIN_HEADER_SIZE;
    let closed = false;

    function finish(state) {
        closed = true;
        Atomics.store(status, 0, state);
        Atomics.notify(status, 0, 1);
        onClose();
    }

    return {
        prompt,
        maxBytes,
        submit(value) {
            if (closed || Atomics.load(status, 0) !== STDIN_WAITING) {
                return { ok: false, error: 'This input request has ended.' };
            }
            const text = String(value);
            const encoded = new TextEncoder().encode(text);
            if (encoded.length > maxBytes) {
                return { ok: false, error: `Input is too long (maximum ${maxBytes} UTF-8 bytes).` };
            }
            new Uint8Array(buffer, STDIN_HEADER_SIZE, encoded.length).set(encoded);
            Atomics.store(length, 0, encoded.length);
            onResponse(text);
            finish(STDIN_READY);
            return { ok: true };
        },
        cancel() {
            if (closed) return;
            finish(STDIN_CANCELLED);
        },
    };
}
