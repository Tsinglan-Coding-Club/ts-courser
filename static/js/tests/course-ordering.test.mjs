import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

// Exercise the actual template handlers with a minimal DOM and controlled saves.
const template = readFileSync(new URL('../../../templates/teacher/course_edit.html', import.meta.url), 'utf8');
const script = template.slice(template.indexOf('let reorderSaving = false;'), template.indexOf("initializeOrdering([document.getElementById"));

class Element {
    constructor(className = '', dataset = {}) {
        Object.assign(this, {className, dataset, children: [], parentElement: null, listeners: {}, textContent: ''});
        this.classList = {
            add: name => { this.className += ` ${name}`; },
            remove: name => { this.className = this.className.split(' ').filter(value => value !== name).join(' '); }
        };
    }
    matches(selector) { return selector.startsWith('.') && this.className.split(' ').includes(selector.slice(1)); }
    closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector); }
    querySelector(selector) {
        for (const child of this.children) {
            if (child.matches(selector)) return child;
            const found = child.querySelector(selector);
            if (found) return found;
        }
        return null;
    }
    remove() {
        if (this.parentElement) this.parentElement.children.splice(this.parentElement.children.indexOf(this), 1);
        this.parentElement = null;
    }
    insertBefore(node, reference) {
        node.remove();
        const index = reference ? this.children.indexOf(reference) : this.children.length;
        assert.ok(index >= 0);
        this.children.splice(index, 0, node);
        node.parentElement = this;
    }
    appendChild(node) { this.insertBefore(node, null); }
    get nextSibling() { return this.parentElement.children[this.parentElement.children.indexOf(this) + 1] || null; }
    addEventListener(type, listener) { this.listeners[type] = listener; }
    async fire(type, target = this) {
        const event = {target, stopPropagation() {}, preventDefault() {}, dataTransfer: {setData() {}}};
        await this.listeners[type](event);
    }
}

function setup(success = true) {
    const status = new Element();
    const containers = [1, 2].map(sectionId => {
        const card = new Element('section-card');
        card.appendChild(new Element('episode-count'));
        const list = new Element('episodes-container', {sectionId});
        card.appendChild(list);
        return list;
    });
    const first = new Element('episode-list-item', {episodeId: 10});
    const second = new Element('episode-list-item', {episodeId: 11});
    containers[0].appendChild(first);
    containers[0].appendChild(second);
    containers[1].appendChild(new Element('empty-episodes'));
    const requests = [];
    const context = vm.createContext({
        document: {getElementById: () => status, createElement: () => new Element()},
        csrftoken: 'token',
        fetch: async (url, options) => {
            requests.push(JSON.parse(options.body));
            return {ok: success, json: async () => ({success, error: 'Save failed'})};
        }
    });
    vm.runInContext(script, context);
    context.initializeOrdering(containers, '.episode-list-item', '/reorder', 'episode_orders', 'episodeId');
    return {containers, first, second, requests, status};
}
const ids = list => list.children.filter(row => row.matches('.episode-list-item')).map(row => row.dataset.episodeId);

test('move into empty section, move again from new parent, and update counts', async () => {
    const {containers: [source, destination], first, second, requests} = setup();
    await first.fire('dragstart');
    await destination.fire('drop', destination.children[0]);
    await first.fire('dragend');
    assert.deepEqual(ids(source), [11]);
    assert.deepEqual(ids(destination), [10]);
    assert.equal(destination.querySelector('.empty-episodes'), null);
    assert.deepEqual(requests[0].episode_sections, [
        {section_id: 1, episode_ids: [11]}, {section_id: 2, episode_ids: [10]}
    ]);
    await first.fire('dragstart');
    await source.fire('drop', second);
    await first.fire('dragend');
    assert.deepEqual(ids(source), [10, 11]);
    assert.deepEqual(ids(destination), []);
    assert.ok(destination.querySelector('.empty-episodes'));
    assert.equal(source.parentElement.querySelector('.episode-count').textContent, '2 episodes');
});

test('failed move restores both lists and their empty states', async () => {
    const {containers: [source, destination], first, status} = setup(false);
    await first.fire('dragstart');
    await destination.fire('drop');
    await first.fire('dragend');
    assert.deepEqual(ids(source), [10, 11]);
    assert.deepEqual(ids(destination), []);
    assert.ok(destination.querySelector('.empty-episodes'));
    assert.match(status.textContent, /Order was not saved/);
});

test('reordering within a section sends a single complete section', async () => {
    const {containers: [source], first, second, requests} = setup();
    await first.fire('dragstart');
    await source.fire('drop', second);
    assert.deepEqual(ids(source), [11, 10]);
    assert.deepEqual(requests[0].episode_sections, [{section_id: 1, episode_ids: [11, 10]}]);
});
