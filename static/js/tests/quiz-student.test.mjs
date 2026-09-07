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
