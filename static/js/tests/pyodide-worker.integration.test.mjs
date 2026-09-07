import assert from 'node:assert/strict';
import test from 'node:test';
import { Worker } from 'node:worker_threads';
import { createStdinRequest } from '../stdin-channel.mjs';

test('browser worker supports imported displays, input cancellation, stop/restart and silent isolated judging', { timeout: 30000 }, async t => {
    const worker = new Worker(new URL('./helpers/pyodide-worker-host.mjs', import.meta.url));
    t.after(() => worker.terminate());
    const messages = [];
    const waiters = new Set();
    let id = 0;
    let stdin;
    let interrupt;
    worker.on('message', message => {
        messages.push(message);
        if (message.type === 'stdin-init') stdin = message.sab;
        if (message.type === 'interrupt-init') interrupt = new Uint8Array(message.sab);
        for (const waiter of [...waiters]) {
            if (waiter.predicate(message)) {
                waiters.delete(waiter);
                clearTimeout(waiter.timer);
                waiter.resolve(message);
            }
        }
    });
    const waitFor = predicate => new Promise((resolve, reject) => {
        const waiter = { predicate, resolve };
        waiter.timer = setTimeout(() => {
            waiters.delete(waiter);
            reject(new Error(`Worker response timed out; messages: ${JSON.stringify(messages.slice(-4))}`));
        }, 8000);
        waiters.add(waiter);
    });
    const start = (type, args = {}) => {
        if (interrupt && (type === 'run' || type === 'judge')) interrupt[0] = 0;
        const runId = ++id;
        const done = waitFor(message => message.id === runId);
        worker.postMessage({ id: runId, type, ...args });
        return { runId, done };
    };
    const reply = value => {
        const request = createStdinRequest(stdin, '', () => {}, () => {});
        if (value === null) request.cancel();
        else assert.equal(request.submit(value).ok, true);
    };
    const ping = await start('ping').done;
    assert.equal(ping.stdinEnabled, true);
    assert.ok(interrupt);

    await t.test('normal import, final snapshot and native errors', async () => {
        const execution = start('run', { python: `
from courser import display, display_map, define_symbol
define_symbol('wall', '🧱')
display_map([['wall', 0]])
display(1)
display(2)
print('only stdout')
` });
        const response = await execution.done;
        assert.equal(response.error, undefined);
        assert.equal(response.stdout, 'only stdout\n');
        const events = messages.filter(message => message.runId === execution.runId && message.type === 'interactive').flatMap(message => message.events);
        assert.equal(events.at(-1).value.text, '2');
        assert.equal(events[0].symbols[0].text, '🧱');
        const missingImport = await start('run', { python: 'display(1)' }).done;
        assert.equal(missingImport.errorKind, 'python');
        assert.match(missingImport.error, /NameError/);
        assert.doesNotMatch(missingImport.error, /courser-runner/);
        const syntax = await start('run', { python: 'if True print(1)' }).done;
        assert.equal(syntax.errorKind, 'python');
        assert.match(syntax.error, /SyntaxError/);
        assert.doesNotMatch(syntax.error, /courser-runner/);
        const asyncCode = await start('run', { python: 'import asyncio\nawait asyncio.sleep(0)\nprint("await works")' }).done;
        assert.equal(asyncCode.stdout, 'await works\n');
    });

    await t.test('pending displays arrive before input and two inputs preserve Unicode/empty strings', async () => {
        const firstInput = waitFor(message => message.type === 'stdin-request');
        const execution = start('run', { python: `
from courser import display
display(1)
display(2)
a = input('First? ')
b = input('Second? ')
print(repr(a), repr(b))
` });
        await firstInput;
        const events = messages.filter(message => message.runId === execution.runId && message.type === 'interactive').flatMap(message => message.events);
        assert.equal(events.at(-1).value.text, '2');
        const secondInput = waitFor(message => message.type === 'stdin-request');
        reply('你好 🐱');
        await secondInput;
        reply('');
        assert.equal((await execution.done).stdout, "'你好 🐱' ''\n");
    });

    await t.test('cancel raises EOFError, Stop raises KeyboardInterrupt, and next run starts fresh', async () => {
        let input = waitFor(message => message.type === 'stdin-request');
        let execution = start('run', { python: 'input("Cancel me")' });
        await input;
        reply(null);
        const cancelled = await execution.done;
        assert.equal(cancelled.errorKind, 'python');
        assert.match(cancelled.error, /EOFError: Input cancelled/);
        assert.match(cancelled.error, /File "main\.py", line 1/);
        assert.doesNotMatch(cancelled.error, /_custom_input|courser-runner/);

        input = waitFor(message => message.type === 'stdin-request');
        execution = start('run', { python: 'input("Stop me")' });
        await input;
        interrupt[0] = 2;
        reply(null);
        assert.equal((await execution.done).interrupted, true);

        input = waitFor(message => message.type === 'stdin-request');
        execution = start('run', { python: 'from courser import display_map; display_map([["wall"]]); print(input())' });
        await input;
        reply('restarted');
        assert.equal((await execution.done).stdout, 'restarted\n');
        const map = messages.find(message => message.runId === execution.runId && message.type === 'interactive').events[0];
        assert.deepEqual(map.symbols, []);
    });

    await t.test('judging uses fresh modules/globals per case, emits no maps, and restores input after errors', async () => {
        const execution = start('judge', {
            python: `
from courser import display_map, define_symbol
counter = globals().get('counter', 0) + 1
display_map([[counter]])
define_symbol(1, 'custom')
print(counter, input())
`,
            testCases: [{ input: 'one', expected: '1 one' }, { input: 'two', expected: '1 two' }],
        });
        assert.deepEqual((await execution.done).results.map(result => result.passed), [true, true]);
        assert.equal(messages.some(message => message.runId === execution.runId), false);
        const failure = await start('judge', {
            python: 'input(); raise ValueError("student error")', testCases: [{ input: 'x', expected: '' }],
        }).done;
        assert.match(failure.results[0].error, /ValueError: student error/);
        const input = waitFor(message => message.type === 'stdin-request');
        const next = start('run', { python: 'print(input("After judging?"))' });
        await input;
        reply('yes');
        assert.equal((await next.done).stdout, 'yes\n');
    });

    await t.test('tight display loops remain interruptible and final state belongs to the correct run', async () => {
        const frame = waitFor(message => message.type === 'interactive');
        const execution = start('run', { python: 'from courser import display\ni = 0\nwhile True:\n    display(i)\n    i += 1' });
        await frame;
        interrupt[0] = 2;
        assert.equal((await execution.done).interrupted, true);
        const next = await start('run', { python: 'print("done")' }).done;
        assert.equal(next.stdout, 'done\n');
    });

    await t.test('Stop received before worker execution begins is not cleared by startup', async () => {
        const runId = ++id;
        const done = waitFor(message => message.id === runId);
        interrupt[0] = 2;
        worker.postMessage({ id: runId, type: 'run', python: 'print("must not execute")' });
        const response = await done;
        assert.equal(response.interrupted, true);
        assert.equal(response.stdout, '');
    });
});
