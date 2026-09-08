import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function picker() {
    const teacher = (value, textContent, disabled = false) => ({value, textContent, disabled});
    const search = {value: '', addEventListener(event, listener) { this[event] = listener; }};
    const select = {
        value: '',
        options: [teacher('', 'Select a teacher', true), teacher('wang', '王老师 (wang)'), teacher('alice', 'Alice (alice)'), teacher('pending', 'Pending — Awaiting approval', true)],
        addEventListener(event, listener) { this[event] = listener; },
        replaceChildren(...options) { this.options = options; },
    };
    const status = {};
    const elements = {teacherSearch: search, teacherSelect: select, teacherSearchStatus: status};
    vm.runInNewContext(readFileSync(new URL('../teacher-picker.js', import.meta.url), 'utf8'), {
        document: {getElementById: id => elements[id]},
    });
    return {search, select, status};
}

test('teacher picker searches names and usernames and restores all options when cleared', () => {
    const {search, select, status} = picker();
    for (const query of ['王', ' WANG ']) {
        search.value = query;
        search.input();
        assert.deepEqual(select.options.map(option => option.value), ['', 'wang']);
        assert.equal(select.value, '');
    }
    search.value = 'missing';
    search.input();
    assert.equal(status.textContent, 'No teachers found.');
    search.value = '';
    search.input();
    assert.equal(select.options.length, 4);
    assert.equal(select.options[3].disabled, true);
});

test('filtering never substitutes a different teacher for the selected account', () => {
    const {search, select} = picker();
    select.value = 'wang';
    select.change();
    search.value = 'alice';
    search.input();
    assert.equal(select.value, '');
    search.value = '';
    search.input();
    assert.equal(select.value, 'wang');
});
