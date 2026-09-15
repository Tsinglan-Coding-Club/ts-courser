import assert from 'node:assert/strict';
import test from 'node:test';
import {
    createStdinRequest, STDIN_SAB_SIZE, STDIN_HEADER_SIZE,
    STDIN_WAITING, STDIN_READY, STDIN_CANCELLED,
} from '../stdin-channel.mjs';

function setup() {
    const buffer = new SharedArrayBuffer(STDIN_SAB_SIZE);
    const status = new Int32Array(buffer, 0, 1);
    Atomics.store(status, 0, STDIN_WAITING);
    const responses = [];
    let closed = 0;
    const request = createStdinRequest(buffer, 'Your answer?', value => responses.push(value), () => closed++);
    return { buffer, status, responses, request, get closed() { return closed; } };
}

test('input preserves Unicode and an intentionally empty response', () => {
    for (const value of ['你好 🐱', '']) {
        const state = setup();
        assert.deepEqual(state.request.submit(value), { ok: true });
        assert.equal(Atomics.load(state.status, 0), STDIN_READY);
        const size = Atomics.load(new Int32Array(state.buffer, 4, 1), 0);
        assert.equal(new TextDecoder().decode(new Uint8Array(state.buffer, STDIN_HEADER_SIZE, size)), value);
        assert.deepEqual(state.responses, [value]);
        assert.equal(state.closed, 1);
    }
});

test('oversized UTF-8 input stays editable and does not overrun shared memory', () => {
    const state = setup();
    const result = state.request.submit('🐱'.repeat(1100));
    assert.equal(result.ok, false);
    assert.match(result.error, /too long/);
    assert.equal(Atomics.load(state.status, 0), STDIN_WAITING);
    assert.equal(state.closed, 0);
    assert.equal(state.request.submit('shorter').ok, true);
});

test('cancel and duplicate submission cannot answer a later request on the same buffer', () => {
    const state = setup();
    state.request.cancel();
    assert.equal(Atomics.load(state.status, 0), STDIN_CANCELLED);
    Atomics.store(state.status, 0, STDIN_WAITING);
    assert.equal(state.request.submit('stale answer').ok, false);
    state.request.cancel();
    assert.equal(Atomics.load(state.status, 0), STDIN_WAITING);
    assert.equal(state.closed, 1);
    assert.deepEqual(state.responses, []);
});
