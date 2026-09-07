import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { STDIN_WAITING, STDIN_CANCELLED } from '../stdin-channel.mjs';

test('page transport closes inputs once, honors early Stop and ignores stale worker events', async t => {
    class WorkerStub {
        constructor() { this.listeners = {}; this.sent = []; }
        addEventListener(type, callback) { this.listeners[type] = callback; }
        postMessage(message) { this.sent.push(message); }
        emit(message) { this.listeners.message({ data: message }); }
        terminate() {}
    }
    const originalWorker = globalThis.Worker;
    globalThis.Worker = WorkerStub;
    t.after(() => { globalThis.Worker = originalWorker; });
    const source = readFileSync(new URL('../pyodide-api.js', import.meta.url), 'utf8')
        .replace('/static/js/python-error.mjs?v=2', new URL('../python-error.mjs', import.meta.url).href)
        .replace('./stdin-channel.mjs?v=1', new URL('../stdin-channel.mjs', import.meta.url).href);
    const api = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
    const worker = api.getWorker();
    const stdin = new SharedArrayBuffer(4096);
    const interrupt = new SharedArrayBuffer(1);
    const status = new Int32Array(stdin, 0, 1);
    worker.emit({ type: 'stdin-init', sab: stdin });
    worker.emit({ type: 'interrupt-init', sab: interrupt });
    const requests = [];
    const frames = [];
    let closed = 0;
    api.onInputRequest(request => requests.push(request), () => closed++);
    api.onInteractive(events => frames.push(events));

    let execution = api.asyncRun('input()');
    let runId = worker.sent.at(-1).id;
    api.writeInterrupt();
    Atomics.store(status, 0, STDIN_WAITING);
    worker.emit({ type: 'stdin-request', runId, prompt: 'Too late' });
    assert.equal(requests.length, 0, 'do not reopen input after Stop');
    assert.equal(Atomics.load(status, 0), STDIN_CANCELLED);
    worker.emit({ id: runId, error: 'Execution interrupted', errorKind: 'interrupted', interrupted: true });
    assert.equal((await execution).interrupted, true);

    execution = api.asyncRun('input()');
    runId = worker.sent.at(-1).id;
    assert.equal(new Uint8Array(interrupt)[0], 0, 'clear old interrupt before new dispatch');
    Atomics.store(status, 0, STDIN_WAITING);
    worker.emit({ type: 'stdin-request', runId, prompt: 'Ready' });
    assert.equal(requests.length, 1);
    const beforeStop = closed;
    api.writeInterrupt();
    assert.equal(closed, beforeStop + 1);
    assert.equal(requests[0].submit('late').ok, false);

    api.terminateWorker();
    assert.equal((await execution).interrupted, true);
    const nextWorker = api.getWorker();
    const next = api.asyncRun('print(1)');
    const nextId = nextWorker.sent.at(-1).id;
    worker.emit({ type: 'interactive', runId: nextId, events: ['stale'] });
    assert.deepEqual(frames, []);
    nextWorker.emit({ id: nextId, stdout: '1\n' });
    assert.equal((await next).stdout, '1\n');
    api.terminateWorker();
});
