import assert from 'node:assert/strict';
import test from 'node:test';
import { studentQuiz } from './helpers/student-quiz.mjs';

test('identical name tokens are interchangeable but IDs still cannot be reused', () => {
    const q = studentQuiz.parseQuiz('## Names\r\n```quiz-cba python\r\nname + name\r\n```')[0];
    assert.equal(q.type, 'cba');
    assert.equal(studentQuiz.isCBACorrect(q, [['l0c2', 'l0c1', 'l0c0']]), true);
    assert.equal(studentQuiz.isCBACorrect(q, [['l0c0', 'l0c1', 'l0c0']]), false);
    assert.equal(studentQuiz.isCBACorrect(q, [['unknown', 'l0c1', 'l0c2']]), false);
    assert.equal(studentQuiz.isCBACorrect(q, [['l0c1', 'l0c0', 'l0c2']]), false);
});

test('same names on different rows and same indentation tokens can exchange IDs', () => {
    const code = 'name = name\n    name = name';
    const q = studentQuiz.parseQuiz('## Names\n```quiz-cba python\n' + code + '\n```')[0];
    assert.equal(studentQuiz.isCBACorrect(q, [['l1c2', 'l1c1', 'l1c0'], ['l0c2', 'l0c1', 'l0c0']]), true);
    const token = (text, kind = 'token', leadingIndent = '') => ({ text, kind, leadingIndent });
    assert.equal(studentQuiz.cbaTokensEquivalent(token('name'), token(' name ')), true);
    assert.equal(studentQuiz.cbaTokensEquivalent(token('"a b"'), token('"a  b"')), false);
    assert.equal(studentQuiz.cbaTokensEquivalent(token('    name', 'token', '    '), token('name')), false);
    assert.equal(studentQuiz.cbaTokensEquivalent(token('    ', 'indent'), token('        ', 'indent')), false);
    assert.equal(studentQuiz.cbaTokensEquivalent(token('    ', 'indent'), token('    ', 'indent')), true);
});

import { cbaPlacement } from './helpers/student-quiz.mjs';

test('CBA drops preserve target slots, holes, and unrelated tokens across moves', () => {
    const q = studentQuiz.parseQuiz('## Assemble\n```quiz-cba python\na + b\nc + d\n```')[0];
    const lines = [[], []];
    cbaPlacement.placeCBAToken(q, lines, 'l0c2', 0, 2);
    assert.deepEqual(lines, [[null, null, 'l0c2'], []]);
    assert.equal(cbaPlacement.isCBAComplete(q, lines), false);
    cbaPlacement.placeCBAToken(q, lines, 'l0c0', 0, 0);
    cbaPlacement.placeCBAToken(q, lines, 'l0c0', 1, 2);
    assert.deepEqual(lines, [[null, null, 'l0c2'], [null, null, 'l0c0']]);
    cbaPlacement.placeCBAToken(q, lines, 'l0c2', 0, 1);
    assert.deepEqual(lines[0], [null, 'l0c2', null]);
    cbaPlacement.removeCBAToken(lines, 'l0c2');
    cbaPlacement.placeCBAInFirstEmptySlot(q, lines, 'l0c1');
    assert.deepEqual(lines, [['l0c1', null, null], [null, null, 'l0c0']]);
    assert.deepEqual(JSON.parse(JSON.stringify(lines)), lines);
});

test('CBA replacement returns the previous token to the bank without shifting slots', () => {
    const q = studentQuiz.parseQuiz('## Assemble\n```quiz-cba python\na + b\n```')[0];
    const lines = [['l0c0', 'l0c1', 'l0c2']];
    assert.equal(cbaPlacement.isCBAComplete(q, lines), true);
    cbaPlacement.placeCBAToken(q, lines, 'l0c2', 0, 0);
    assert.deepEqual(lines, [['l0c2', 'l0c1', null]]);
    assert.equal(cbaPlacement.isCBAComplete(q, lines), false);
    assert.equal(studentQuiz.isCBACorrect(q, lines), false);
    for (const [id, row, slot] of [['unknown', 0, 0], ['l0c1', 0, 3], ['l0c1', -1, 0]]) {
        cbaPlacement.placeCBAToken(q, lines, id, row, slot);
        assert.deepEqual(lines, [['l0c2', 'l0c1', null]]);
    }
    cbaPlacement.placeCBAInFirstEmptySlot(q, lines, 'l0c0');
    assert.equal(cbaPlacement.isCBAComplete(q, lines), true);
});
