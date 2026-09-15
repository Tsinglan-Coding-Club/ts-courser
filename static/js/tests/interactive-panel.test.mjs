import assert from 'node:assert/strict';
import test from 'node:test';

import {
    InteractivePanel,
    collectMapLegend,
    mapCellDisplay,
    nodeFingerprint,
    validateMapNode,
} from '../interactive-panel.mjs';

const scalar = (text, key = text) => ({ kind: 'scalar', text, key });
const grid = (rows) => ({ kind: 'list', items: rows.map((row) => ({ kind: 'list', items: row })) });

class MiniNode {
    constructor(documentRef, tag = '#text', text = '') {
        this.ownerDocument = documentRef;
        this.tagName = tag;
        this.parentNode = null;
        this.children = [];
        this.dataset = {};
        this.hidden = false;
        this._text = text;
        this._listeners = new Map();
        this._className = '';
        this.style = { setProperty() {} };
        this.classList = {
            add: (...names) => this._setClasses(new Set([...this._classes(), ...names])),
            remove: (...names) => this._setClasses(new Set([...this._classes()].filter((name) => !names.includes(name)))),
            contains: (name) => this._classes().has(name),
            toggle: (name, force) => {
                const next = force === undefined ? !this._classes().has(name) : force;
                if (next) this.classList.add(name);
                else this.classList.remove(name);
                return next;
            },
        };
    }

    get className() { return this._className; }
    set className(value) { this._className = String(value); }
    get textContent() { return this.children.length ? this.children.map((child) => child.textContent).join('') : this._text; }
    set textContent(value) { this.replaceChildren(this.ownerDocument.createTextNode(String(value))); }
    _classes() { return new Set(this._className.split(/\s+/).filter(Boolean)); }
    _setClasses(names) { this._className = [...names].join(' '); }
    append(...nodes) {
        for (const node of nodes) {
            node.parentNode = this;
            this.children.push(node);
        }
    }
    replaceChildren(...nodes) {
        this.children.forEach((child) => { child.parentNode = null; });
        this.children = [];
        this._text = '';
        this.append(...nodes);
    }
    remove() {
        if (!this.parentNode) return;
        this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
        this.parentNode = null;
    }
    setAttribute() {}
    addEventListener(type, listener) {
        if (!this._listeners.has(type)) this._listeners.set(type, []);
        this._listeners.get(type).push(listener);
    }
    dispatch(type) { (this._listeners.get(type) || []).forEach((listener) => listener({ target: this })); }
    focus() {
        this.ownerDocument.activeElement = this;
        this.dispatch('focus');
    }
    contains(node) {
        return node === this || this.children.some((child) => child.contains && child.contains(node));
    }
    closest(selector) {
        let node = this;
        while (node) {
            if (node._matches && node._matches(selector)) return node;
            node = node.parentNode;
        }
        return null;
    }
    _matches(selector) {
        if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
        const attributes = [...selector.matchAll(/\[data-([a-z-]+)="([^"]*)"\]/g)];
        return attributes.length > 0 && attributes.every((match) => this.dataset[match[1].replace(/-([a-z])/g, (_, char) => char.toUpperCase())] === match[2]);
    }
    querySelectorAll(selector) {
        const result = [];
        const visit = (node) => {
            node.children.forEach((child) => {
                if (child._matches && child._matches(selector)) result.push(child);
                if (child.children) visit(child);
            });
        };
        visit(this);
        return result;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

class MiniDocument {
    constructor() { this.activeElement = null; }
    createElement(tag) { return new MiniNode(this, tag); }
    createTextNode(text) { return new MiniNode(this, '#text', text); }
}

function createPanel() {
    const documentRef = new MiniDocument();
    return { documentRef, panel: new InteractivePanel(documentRef.createElement('div')) };
}

test('fingerprints nested nodes without modifying their runtime snapshots', () => {
    const node = { kind: 'list', items: [scalar('<unsafe>', 'str:<unsafe>')] };
    const before = structuredClone(node);
    assert.equal(nodeFingerprint(node), 'list:[scalar:str:<unsafe>:<unsafe>]');
    assert.deepEqual(node, before);
});

test('accepts non-empty rectangular scalar grids within renderer limits', () => {
    const result = validateMapNode(grid([[scalar('0'), scalar('1')], [scalar('2'), scalar('3')]]));
    assert.equal(result.valid, true);
    assert.equal(result.rows, 2);
    assert.equal(result.cols, 2);
});

test('rejects ragged, empty, and nested map values', () => {
    assert.equal(validateMapNode(grid([[scalar('0')], [scalar('1'), scalar('2')]])).valid, false);
    assert.equal(validateMapNode({ kind: 'list', items: [] }).valid, false);
    assert.equal(validateMapNode(grid([[{ kind: 'list', items: [] }]])).valid, false);
});

test('uses only declared matching symbols and keeps unknown values as their repr text', () => {
    const symbols = [{ key: 'int:1', text: '🌲' }];
    assert.equal(mapCellDisplay(scalar('1', 'int:1'), symbols), '🌲');
    assert.equal(mapCellDisplay(scalar("'?'", 'str:?'), symbols), "'?'");
});

test('legend includes declared symbols used by a map exactly once', () => {
    const map = validateMapNode(grid([
        [scalar('1', 'int:1'), scalar('1', 'int:1')],
        [scalar('2', 'int:2'), scalar('?', 'str:?')],
    ]));
    assert.deepEqual(collectMapLegend(map, [
        { key: 'int:1', text: '🌲' },
        { key: 'int:2', text: '🪨' },
        { key: 'missing', text: 'x' },
        { key: 'int:1', text: 'duplicate' },
    ]), [
        { key: 'int:1', text: '🌲', value: '1' },
        { key: 'int:2', text: '🪨', value: '2' },
    ]);
});

test('reset removes rendered cards and map DOM before a new run', () => {
    const { panel } = createPanel();
    panel.applyEvents([
        { type: 'display', label: 'score', value: scalar('1') },
        { type: 'map', value: grid([[scalar('x')]]), symbols: [] },
    ]);
    assert.equal(panel.cards.children.length, 1);
    assert.equal(panel.mapArea.children.length, 2);

    panel.reset();
    assert.equal(panel.cards.children.length, 0);
    assert.equal(panel.mapArea.children.length, 0);
    assert.equal(panel._lastGrid, null);

    panel.applyEvents([{ type: 'display', label: 'next', value: scalar('2') }]);
    assert.equal(panel.cards.children.length, 1);
    assert.equal(panel.cards.children[0].dataset.slot, 'label:next');
});

test('same-size map updates retain the focused cell, while data view shows raw text and coordinates', () => {
    const { documentRef, panel } = createPanel();
    const first = grid([[scalar('1', 'int:1'), scalar('2', 'int:2')]]);
    panel.applyEvents([{ type: 'map', value: first, symbols: [{ key: 'int:1', text: '🌲' }] }]);
    const focused = panel._cellAt(0, 1);
    focused.focus();

    const next = grid([[scalar('1', 'int:1'), scalar('3', 'int:3')]]);
    panel.applyEvents([{ type: 'map', value: next, symbols: [{ key: 'int:1', text: '🌲' }] }]);
    assert.equal(panel._cellAt(0, 1), focused);
    assert.equal(documentRef.activeElement, focused);
    assert.equal(focused.textContent, '3');

    panel._setView('data');
    assert.equal(panel._cellAt(0, 0).textContent, '1');
    assert.equal(panel._columnAxis.children[0].textContent, '0');
    assert.equal(panel._rowAxis.children[0].textContent, '0');
    assert.equal(panel._cellAt(0, 1), focused);
    assert.equal(panel.status.textContent, '[0][1] = 3');
});
