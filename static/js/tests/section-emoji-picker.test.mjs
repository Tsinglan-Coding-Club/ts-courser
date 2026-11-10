import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const icons = [
    {name: 'devicon:python:original', url: '/static/vendor/devicon/python/python-original.svg', category: 'Devicon', filter: 'devicon', shortcodes: ['python']},
    {name: 'heroicons:24-outline:academic-cap', url: '/static/vendor/heroicons/24/outline/academic-cap.svg', category: 'Heroicons · Outline', filter: 'everyday', shortcodes: ['academic-cap']},
];

function element(properties = {}) {
    return {
        ...properties,
        children: [],
        set textContent(value) { this.text = value; this.children = []; },
        get textContent() { return this.text; },
        listeners: {},
        setAttribute(name, value) { this[name] = value; },
        appendChild(child) { this.children.push(child); },
        addEventListener(name, listener) { this.listeners[name] = listener; },
        dispatchEvent(event) { return this.listeners[event.type]?.(event); },
        focus() { this.focused = true; },
    };
}

function setup({fetchCatalog = async () => ({ok: true, json: async () => icons})} = {}) {
    const requests = {catalog: 0, module: 0};
    const createField = value => {
        const input = element({value, dataset: {}});
        const details = element({open: false});
        const preview = element();
        const clear = element();
        const host = element({dataset: {source: '/emoji.json'}});
        const status = element();
        const filterButtons = ['all', 'devicon', 'everyday'].map(iconFilter => element({dataset: {iconFilter}}));
        const filters = element({hidden: true, querySelectorAll: () => filterButtons});
        const summary = element();
        const modal = element();
        const selectors = {
            'input[name="emoji"]': input,
            '[data-emoji-details]': details,
            '[data-emoji-preview]': preview,
            '[data-emoji-clear]': clear,
            '[data-icon-filters]': filters,
            '[data-emoji-picker-host]': host,
            '[data-emoji-picker-status]': status,
            summary,
        };
        const field = {
            querySelector: selector => selectors[selector],
            closest: () => modal,
        };
        return {
            field, input, details, preview, clear, summary, modal, status, filters, filterButtons,
            get picker() { return host.children[0]; },
            async open() {
                details.open = true;
                await details.dispatchEvent({type: 'toggle'});
            },
        };
    };
    const fields = [createField(''), createField('🐍')];
    vm.runInNewContext(readFileSync(new URL('../section-emoji-picker.js', import.meta.url), 'utf8'), {
        document: {
            querySelectorAll: () => fields.map(item => item.field),
            currentScript: {dataset: {pickerModule: '/picker.js', iconOptions: '/icon-options/'}},
            createElement: tagName => {
                const tabs = element({
                    activeTab: {dataset: {groupId: '-1'}},
                    querySelector(selector) { return selector === '[aria-selected="true"]' ? this.activeTab : null; },
                });
                const panel = element({
                    querySelectorAll: () => [],
                    before(node) { this.previousElementSibling = node; },
                });
                const selectors = {'[role="tablist"]': tabs, '.tabpanel': panel};
                return element({
                    tagName, dataset: {},
                    shadowRoot: element({querySelector: selector => selectors[selector] ?? null}),
                });
            },
            head: {appendChild(script) { requests.module++; script.dispatchEvent({type: 'load'}); }},
        },
        fetch: (...args) => { requests.catalog++; return fetchCatalog(...args); },
        Event,
        IntersectionObserver: class {},
        MutationObserver: class {
            constructor(callback) { this.callback = callback; }
            observe(target) { target.notifyMutation = this.callback; }
        },
    });
    return {fields, requests};
}

test('picker selection saves full Unicode and keeps the other section form independent', async () => {
    const {fields: [add, edit]} = setup();
    await add.open();
    add.picker.dispatchEvent({type: 'emoji-click', detail: {unicode: '👩🏽‍💻'}});
    assert.equal(add.input.value, '👩🏽‍💻');
    assert.equal(add.preview.textContent, '👩🏽‍💻');
    assert.equal(add.clear.disabled, false);
    assert.equal(add.details.open, false);
    assert.equal(add.summary.focused, true);
    assert.equal(edit.input.value, '🐍');
    assert.equal(edit.preview.textContent, '🐍');
});

test('opening another section reloads its preview and Clear removes the persisted field value', () => {
    const {fields: [, edit], requests} = setup();
    edit.input.value = icons[0].name;
    edit.input.dataset.iconUrl = icons[0].url;
    edit.details.open = true;
    edit.modal.dispatchEvent({type: 'show.bs.modal'});
    assert.equal(edit.preview.children[0].src, icons[0].url);
    assert.deepEqual(requests, {catalog: 0, module: 0});
    assert.equal(edit.details.open, false);
    edit.clear.dispatchEvent({type: 'click'});
    assert.equal(edit.input.value, '');
    assert.equal(edit.preview.textContent, '📁');
    assert.equal(edit.clear.disabled, true);
});

test('installed custom icons save stable names and render local image previews', async () => {
    const {fields: [add]} = setup();
    await add.open();
    assert.equal(add.picker.customEmoji.length, 2);
    for (const icon of icons) {
        add.picker.dispatchEvent({type: 'emoji-click', detail: {emoji: {name: icon.name}}});
        assert.equal(add.input.value, icon.name);
        assert.equal(add.preview.children[0].src, icon.url);
        assert.equal(add.preview.children[0].className.includes('section-icon-heroicons'), icon.name.startsWith('heroicons:'));
    }
    add.picker.dispatchEvent({type: 'emoji-click', detail: {emoji: {name: 'unknown:icon'}}});
    assert.equal(add.input.value, icons[1].name);
    add.clear.dispatchEvent({type: 'click'});
    assert.equal(add.input.value, '');
    assert.equal(add.preview.children.length, 0);
    assert.equal(add.preview.textContent, '📁');
});

test('forms load the picker and share a single catalog request only when expanded', async () => {
    const {fields: [add, edit], requests} = setup();
    assert.deepEqual(requests, {catalog: 0, module: 0});
    assert.equal(add.picker, undefined);
    await Promise.all([add.open(), edit.open()]);
    assert.deepEqual(requests, {catalog: 1, module: 1});
    assert.equal(add.picker.customEmoji, edit.picker.customEmoji);
});

test('a failed catalog request can be retried without reloading the module', async () => {
    let fail = true;
    const {fields: [add], requests} = setup({
        fetchCatalog: async () => ({ok: !fail, json: async () => icons}),
    });
    await add.open();
    assert.equal(add.picker, undefined);
    assert.match(add.status.textContent, /try again/);
    add.details.open = false;
    fail = false;
    await add.open();
    assert.equal(add.status.textContent, '');
    assert.equal(add.picker.customEmoji, icons);
    assert.deepEqual(requests, {catalog: 2, module: 1});
});

test('custom filters narrow the catalog and restore all icons without fetching again', async () => {
    const {fields: [add, edit], requests} = setup();
    assert.equal(add.filters.hidden, true);
    await Promise.all([add.open(), edit.open()]);
    assert.equal(add.filters.hidden, false);
    assert.equal(add.picker.shadowRoot.querySelector('.tabpanel').previousElementSibling, add.filters);
    const [all, devicon, everyday] = add.filterButtons;
    everyday.dispatchEvent({type: 'click'});
    assert.equal(add.picker.customEmoji.length, 1);
    assert.equal(add.picker.customEmoji[0], icons[1]);
    assert.equal(everyday['aria-pressed'], 'true');
    assert.equal(all['aria-pressed'], 'false');
    devicon.dispatchEvent({type: 'click'});
    assert.equal(add.picker.customEmoji[0], icons[0]);
    assert.equal(edit.picker.customEmoji, icons);
    all.dispatchEvent({type: 'click'});
    assert.equal(add.picker.customEmoji, icons);
    assert.equal(requests.catalog, 1);
});

test('filters appear only in Custom and searches started from Custom', async () => {
    const {fields: [add]} = setup();
    await add.open();
    const tabs = add.picker.shadowRoot.querySelector('[role="tablist"]');
    for (const [groupId, hidden] of [[null, false], ['0', true], [null, true], ['-1', false]]) {
        tabs.activeTab = groupId === null ? null : {dataset: {groupId}};
        tabs.notifyMutation();
        assert.equal(add.filters.hidden, hidden);
    }
});

test('Escape closes an open picker before dismissing the modal', () => {
    const {fields: [add]} = setup();
    add.details.open = true;
    const event = {
        type: 'keydown', key: 'Escape',
        preventDefault() { this.defaultPrevented = true; },
        stopPropagation() { this.stopped = true; },
    };
    add.details.dispatchEvent(event);
    assert.equal(add.details.open, false);
    assert.equal(event.defaultPrevented, true);
    assert.equal(event.stopped, true);
    assert.equal(add.summary.focused, true);
});
