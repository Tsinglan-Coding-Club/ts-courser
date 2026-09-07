// Run the actual browser worker in node:worker_threads, adapting only URLs and
// browser transport. Python, shared memory, imports and execution are unchanged.
import { parentPort } from 'node:worker_threads';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const jsRoot = new URL('../../', import.meta.url);
const dependencyRoot = new URL('../../../../node_modules/pyodide/', import.meta.url);
const moduleUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const source = filename => readFileSync(new URL(filename, jsRoot), 'utf8');
const workerApis = source('worker-apis.js').replace('./stdin-channel.mjs?v=1', new URL('stdin-channel.mjs', jsRoot).href);
let worker = source('pyodide-worker.js')
    .replace('/static/pyodide/pyodide.mjs?v=3', new URL('pyodide.mjs', dependencyRoot).href)
    .replace('/static/js/worker-apis.js?v=2', moduleUrl(workerApis))
    .replace('./courser-runtime.mjs?v=1', new URL('courser-runtime.mjs', jsRoot).href)
    .replace('./python-execution.mjs?v=1', new URL('python-execution.mjs', jsRoot).href)
    .replace('/static/js/python-error.mjs?v=2', new URL('python-error.mjs', jsRoot).href)
    .replace("indexURL: '/static/pyodide/'", `indexURL: ${JSON.stringify(fileURLToPath(dependencyRoot))}`);

globalThis.self = globalThis;
globalThis.crossOriginIsolated = true;
globalThis.postMessage = message => parentPort.postMessage(message);
const sourcePath = new URL('../python/courser.py', jsRoot);
globalThis.fetch = async url => {
    if (url !== '/static/python/courser.py?v=1') throw new Error(`Unexpected fetch: ${url}`);
    return new Response(readFileSync(sourcePath));
};
console.log = () => {};
console.warn = () => {};
await import(moduleUrl(worker));
parentPort.on('message', data => self.onmessage({ data }));
