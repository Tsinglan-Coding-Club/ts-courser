import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';
import { studentQuiz } from './helpers/student-quiz.mjs';

const require = createRequire(import.meta.url);
const {
    canSplitCbaLineGroup,
    initQuizEditor,
    codePointLength,
    normalizeCbaConfig,
    parseQuiz,
    serializeQuiz,
    setCbaIndentationMode,
    splitQuizBlocks,
    splitCbaLineGroup,
    tokenizeCodeBody,
} = require('../quiz-editor.js');

test('CBA markdown round-trips code from its fence without putting code in the prompt', () => {
    const code = '  print("hi")  \n\treturn value\n';
    const original = [{
        type: 'cba',
        question: 'Complete this small program',
        code,
        cba: normalizeCbaConfig(code, null, 'python'),
    }];

    const parsed = parseQuiz(serializeQuiz(original));
    assert.equal(parsed.length, 1);
    assert.equal(parsed[0].type, 'cba');
    assert.equal(parsed[0].question, 'Complete this small program');
    assert.equal(parsed[0].code, code);
    assert.doesNotMatch(parsed[0].question, /print|return/);
});

test('CBA config preserves valid manually merged cuts and hints', () => {
    const code = 'return value';
    const config = {
        v: 1,
        language: 'python',
        indentation: 'sortable',
        lines: [{ cuts: [6, 12], hints: [true, false] }],
    };
    const normalized = normalizeCbaConfig(code, config);
    assert.deepEqual(normalized, {
        ...config,
        lines: [{ ...config.lines[0], indentMerged: false, indentHint: false }],
    });
});

test('legacy v1 indentation config gains non-breaking per-line indent defaults', () => {
    const code = '    return value';
    const visible = normalizeCbaConfig(code, {
        v: 1, language: 'python', indentation: 'visible',
        lines: [{ cuts: [6, 12], hints: [false, true] }],
    });
    const sortable = normalizeCbaConfig(code, {
        v: 1, language: 'python', indentation: 'sortable',
        lines: [{ cuts: [6, 12], hints: [false, true] }],
    });
    assert.deepEqual(visible.lines[0], { cuts: [6, 12], hints: [false, true], indentMerged: false, indentHint: true });
    assert.deepEqual(sortable.lines[0], { cuts: [6, 12], hints: [false, true], indentMerged: false, indentHint: false });
});

test('serialized indent merge retains a single merged hint state', () => {
    const code = '    return value';
    const question = {
        type: 'cba', question: 'Assemble', code,
        cba: {
            v: 1, language: 'python', indentation: 'sortable',
            lines: [{ cuts: [6, 12], hints: [true, false], indentMerged: true, indentHint: true }],
        },
    };
    const parsed = parseQuiz(serializeQuiz([question]))[0];
    assert.equal(parsed.cba.lines[0].indentMerged, true);
    assert.equal(parsed.cba.lines[0].indentHint || parsed.cba.lines[0].hints[0], true);
});

test('invalid optional indentation fields rebuild the whole CBA config', () => {
    const code = '    return value';
    const config = normalizeCbaConfig(code, {
        v: 1, language: 'python', indentation: 'sortable',
        lines: [{ cuts: [6, 12], hints: [false, false], indentMerged: 'true' }],
    });
    assert.equal(config.lines[0].indentMerged, false);
    assert.equal(config.lines[0].indentHint, true);
    assert.equal(config.indentation, 'visible');
    assert.deepEqual(config.lines[0].cuts, [6, 12]);
});

test('Split restores atomic token boundaries and reverses an indent merge', () => {
    const line = '    return value';
    const config = {
        cuts: [12], hints: [true], indentMerged: true, indentHint: true,
    };
    assert.equal(canSplitCbaLineGroup(line, config, 0), true);
    assert.equal(splitCbaLineGroup(line, config, 0), true);
    assert.deepEqual(config, {
        cuts: [6, 12], hints: [true, true], indentMerged: false, indentHint: true,
    });
});

test('Split only affects the selected grouped body range', () => {
    const line = 'return value + next';
    const config = {
        cuts: [12, 14, 19], hints: [false, true, false], indentMerged: false, indentHint: false,
    };
    assert.equal(canSplitCbaLineGroup(line, config, 0), true);
    splitCbaLineGroup(line, config, 0);
    assert.deepEqual(config.cuts, [6, 12, 14, 19]);
    assert.deepEqual(config.hints, [false, false, true, false]);
});

test('switching Fixed hint to Student arranges unlocks a merged indent when body is not a hint', () => {
    const cba = normalizeCbaConfig('    return value', {
        v: 1, language: 'python', indentation: 'visible',
        lines: [{ cuts: [6, 12], hints: [false, false], indentMerged: true, indentHint: true }],
    });
    // Indent merge is structural only; it must never turn c0 into a hint.
    assert.equal(cba.lines[0].hints[0], false);
    setCbaIndentationMode(cba, 'sortable');
    assert.equal(cba.indentation, 'sortable');
    assert.equal(cba.lines[0].indentHint, false);
    assert.equal(cba.lines[0].hints[0], false);
    assert.equal(cba.lines[0].indentHint || cba.lines[0].hints[0], false);
});

test('actual Add button handlers survive form CRLF and editor/student reload', () => {
    // Minimal DOM host: exercise production button listeners and serialization,
    // not a hand-written approximation of the Add button Markdown.
    class Element {
        constructor() {
            this.value = '';
            this.children = [];
            this.dataset = {};
            this.style = { setProperty() {} };
            this.events = {};
        }
        set innerHTML(value) { this.html = value; this.children = []; }
        get innerHTML() { return this.html || ''; }
        appendChild(child) { this.children.push(child); return child; }
        append(...children) { this.children.push(...children); }
        addEventListener(name, callback) { this.events[name] = callback; }
        setAttribute() {}
        querySelector() { return null; }
        querySelectorAll() { return []; }
        click() { this.events.click(); }
    }
    const elements = Object.fromEntries(
        ['source', 'preview', 'mcq', 'mrq', 'srt', 'frq', 'cba'].map(id => [id, new Element()])
    );
    const previousDocument = globalThis.document;
    const previousRAF = globalThis.requestAnimationFrame;
    globalThis.document = {
        getElementById: id => elements[id],
        createElement: () => new Element(),
        addEventListener() {},
    };
    globalThis.requestAnimationFrame = () => 0;
    try {
        const editor = initQuizEditor({
            sourceId: 'source', previewId: 'preview',
            addMcqBtnId: 'mcq', addMrqBtnId: 'mrq', addSrtBtnId: 'srt',
            addFrqBtnId: 'frq', addCbaBtnId: 'cba',
        });
        const types = ['cba', 'mcq', 'mrq', 'srt', 'frq'];
        for (const type of types) elements[type].click();
        assert.deepEqual(editor.getQuestions().map(q => q.type), types);
        const browserPostedMarkdown = elements.source.value.replace(/\n/g, '\r\n');
        for (const markdown of [browserPostedMarkdown, browserPostedMarkdown.replace(/\r\n/g, '\r')]) {
            editor.setMarkdown(markdown);
            assert.deepEqual(editor.getQuestions().map(q => q.type), types);
            assert.deepEqual(Array.from(studentQuiz.parseQuiz(markdown), q => q.type), types);
            assert.deepEqual(parseQuiz(serializeQuiz(editor.getQuestions())).map(q => q.type), types);
        }
    } finally {
        globalThis.document = previousDocument;
        globalThis.requestAnimationFrame = previousRAF;
    }
});

test('CBA cuts use Unicode code points, not JavaScript UTF-16 offsets', () => {
    const body = 'emoji😀 + 1';
    const tokens = tokenizeCodeBody(body);
    assert.equal(codePointLength(body), 10);
    assert.equal(tokens.find(token => token.text === '😀').end, 6);
    const config = normalizeCbaConfig(body, null);
    assert.equal(config.lines[0].cuts.at(-1), 10);
    assert.notEqual(config.lines[0].cuts.at(-1), body.length);
});

test('H2-looking lines inside code fences never split quiz blocks', () => {
    const markdown = `## Build it
\`\`\`quiz-cba python
# ## this stays in the program
print('done')
\`\`\`
\`\`\`quiz-cba-config
{}
\`\`\`

## A separate question
>+ yes`;
    const blocks = splitQuizBlocks(markdown);
    assert.equal(blocks.length, 2);
    assert.match(blocks[0], /# ## this stays/);
    assert.equal(parseQuiz(markdown).length, 2);
});

test('the persisted episode 75 CBA fences are recognized before FRQ fallback', () => {
    const markdown = `## Complete the greeting function
Arrange the tokens into valid Python.
\`\`\`quiz-cba python
def greet(name):
    if name:
        return f"Hello, {name}!"
    return "Hello!"
\`\`\`
\`\`\`quiz-cba-config
{"v":1,"language":"python","indentation":"visible","lines":[{"cuts":[3,9,10,14,15,16],"hints":[true,false,false,false,false,false]},{"cuts":[2,7,8],"hints":[false,false,false]},{"cuts":[6,24],"hints":[true,false]},{"cuts":[6,15],"hints":[false,false]}]}
\`\`\`

## Build a loop
\`\`\`quiz-cba python
for item in items:
    print(item)
\`\`\`
\`\`\`quiz-cba-config
{"v":1,"language":"python","indentation":"sortable","lines":[{"cuts":[3,8,11,17,18],"hints":[false,false,true,false,false]},{"cuts":[5,6,10,11],"hints":[false,false,false,false]}]}
\`\`\``;
    const questions = parseQuiz(markdown);
    assert.deepEqual(questions.map(question => question.type), ['cba', 'cba']);
    assert.equal(questions[0].code, 'def greet(name):\n    if name:\n        return f"Hello, {name}!"\n    return "Hello!"');
    assert.equal(questions[1].cba.indentation, 'sortable');
});
