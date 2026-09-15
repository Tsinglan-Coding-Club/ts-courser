/**
 * Quiz Editor — Markdown-based quiz question editor with visual preview.
 *
 * ## Quiz Markdown Format
 *
 * Questions are separated by `## ` (h2) at line start. Question text can span
 * multiple lines (everything before the first `>` choice line).
 *
 * ### MCQ (Multiple Choice Question — single correct)
 * ```
 * ## What is 2+2?
 * Here is some **explanation** with `code`.
 * >+ 4
 * > 3
 * > 5
 * ```
 * - `## ` starts a new question (h2 delimiter)
 * - `>+` marks the single correct answer
 * - `>` marks wrong answers
 * - Question text: all lines between `## ` and first `>` line
 *
 * ### MRQ (Multi-Response Question — multiple correct)
 * ```
 * ## Which are prime numbers?
 * >* 2
 * >* 3
 * > 4
 * >* 5
 * ```
 * - `>*` marks correct answers (multiple allowed)
 *
 * ### FRQ (Free Response Question)
 * ```
 * ## Explain Newton's First Law.
 * Use **markdown** in your response.
 * >
 * ```
 * - Exactly one `>` with no content = FRQ
 *
 * ### SRT (Sorting Question)
 * ```
 * ## Sort by size, smallest first
 * >1 Seed
 * >3 Watermelon
 * >2 Apple
 * >4 Pumpkin
 * ```
 * - `>N text` — N = correct sort position (1-based), text = option label
 * - The order in the markdown is the initial display order for the quiz taker
 *
 * ## API
 *
 * - parseQuiz(markdown)  → [{id, type, question, choices: [{id, text, isCorrect, sortPosition}]}]
 * - serializeQuiz(data)  → markdown string
 * - initQuizEditor(config) → attaches editor to DOM elements
 */

// ============================================================================
// 0. Type Configuration — extend this to add new question types
// ============================================================================

const QUESTION_TYPES = {
    mcq: { label: 'MCQ', badgeClass: 'quiz-type-mcq', hasChoices: true, isSorting: false },
    mrq: { label: 'MRQ', badgeClass: 'quiz-type-mrq', hasChoices: true, isSorting: false },
    frq: { label: 'FRQ', badgeClass: 'quiz-type-frq', hasChoices: false, isSorting: false },
    srt: { label: 'SRT', badgeClass: 'quiz-type-srt', hasChoices: true, isSorting: true },
    cba: { label: 'CBA', badgeClass: 'quiz-type-cba', hasChoices: false, isSorting: false, isCodeBlocks: true },
};

const ALL_TYPES = Object.keys(QUESTION_TYPES);

// ============================================================================
// 1. Parser & Serializer (pure functions, no DOM dependency)
// ============================================================================

let _questionIdCounter = 0;
let _choiceIdCounter = 0;

function resetIdCounters() {
    _questionIdCounter = 0;
    _choiceIdCounter = 0;
}

function nextQuestionId() {
    return 'q-' + (++_questionIdCounter);
}

function nextChoiceId() {
    return 'c-' + (++_choiceIdCounter);
}

// ---------------------------------------------------------------------------
// Code-block assembly (CBA) helpers.  The serialized config intentionally only
// stores structure.  Source code is always read from, and written to, the CBA
// code fence rather than a JSON string.
// ---------------------------------------------------------------------------

const CBA_CONFIG_VERSION = 1;
const CBA_OPERATORS = [
    '>>=', '<<=', '**=', '//=', '...', '===', '!==', '=>', '==', '!=', '<=',
    '>=', '<<', '>>', '**', '//', '+=', '-=', '*=', '/=', '%=', '&=', '|=',
    '^=', '->', ':=', '&&', '||', '??', '?.', '++', '--', '(', ')', '[', ']',
    '{', '}', ',', ':', ';', '.', '+', '-', '*', '/', '%', '<', '>', '=', '!',
    '&', '|', '^', '~', '?', '@', '\\'
];

function codePointLength(value) {
    return Array.from(value || '').length;
}

/**
 * Tokenise one non-indentation line body.  Token end values are Unicode code
 * point offsets, so emoji/non-BMP identifiers never produce UTF-16 cuts.
 */
function tokenizeCodeBody(body) {
    const chars = Array.from(body || '');
    const tokens = [];
    let index = 0;
    const isIdentifierStart = char => /[A-Za-z_$]/.test(char) || (char && char.codePointAt(0) > 0x7f && /\p{L}/u.test(char));
    const isIdentifierPart = char => isIdentifierStart(char) || /[0-9]/.test(char);

    while (index < chars.length) {
        const start = index;
        const char = chars[index];
        if (/\s/.test(char)) {
            index += 1;
            continue;
        }
        // Line comments are one token.  Python (#), C-family (//), and SQL
        // style (--), cover the languages currently offered by the editor.
        if (char === '#' || (char === '/' && chars[index + 1] === '/') ||
            (char === '-' && chars[index + 1] === '-')) {
            tokens.push({ text: chars.slice(index).join(''), start, end: chars.length, type: 'comment' });
            break;
        }
        // Optional string prefixes (f, r, b, u) are folded into the string.
        let quoteIndex = index;
        if (/[fFrRbBuU]/.test(chars[quoteIndex] || '') && /[fFrRbBuU]/.test(chars[quoteIndex + 1] || '') && /['\"]/.test(chars[quoteIndex + 2] || '')) quoteIndex += 2;
        else if (/[fFrRbBuU]/.test(chars[quoteIndex] || '') && /['\"]/.test(chars[quoteIndex + 1] || '')) quoteIndex += 1;
        if (/['\"]/.test(chars[quoteIndex] || '')) {
            const quote = chars[quoteIndex];
            const triple = chars[quoteIndex + 1] === quote && chars[quoteIndex + 2] === quote;
            index = quoteIndex + (triple ? 3 : 1);
            while (index < chars.length) {
                if (chars[index] === '\\') { index += 2; continue; }
                if (triple && chars[index] === quote && chars[index + 1] === quote && chars[index + 2] === quote) { index += 3; break; }
                if (!triple && chars[index] === quote) { index += 1; break; }
                index += 1;
            }
            tokens.push({ text: chars.slice(start, index).join(''), start, end: index, type: 'string' });
            continue;
        }
        if (isIdentifierStart(char)) {
            index += 1;
            while (index < chars.length && isIdentifierPart(chars[index])) index += 1;
            tokens.push({ text: chars.slice(start, index).join(''), start, end: index, type: 'identifier' });
            continue;
        }
        if (/[0-9]/.test(char) || (char === '.' && /[0-9]/.test(chars[index + 1] || ''))) {
            index += 1;
            while (index < chars.length && /[A-Za-z0-9_.]/.test(chars[index])) index += 1;
            tokens.push({ text: chars.slice(start, index).join(''), start, end: index, type: 'number' });
            continue;
        }
        const operator = CBA_OPERATORS.find(candidate => chars.slice(index, index + Array.from(candidate).length).join('') === candidate);
        index += operator ? Array.from(operator).length : 1;
        tokens.push({ text: chars.slice(start, index).join(''), start, end: index, type: operator ? 'operator' : 'punctuation' });
    }
    return tokens;
}

function splitCodeLine(line) {
    const match = /^(?:[ \t]*)/.exec(line || '');
    const indent = match ? match[0] : '';
    return { indent, body: (line || '').slice(indent.length) };
}

function defaultCbaLines(code, indentation) {
    return String(code || '').split('\n').map(line => {
        const body = splitCodeLine(line).body;
        const cuts = tokenizeCodeBody(body).map(token => token.end);
        if (body && (cuts.length === 0 || cuts[cuts.length - 1] !== codePointLength(body))) cuts.push(codePointLength(body));
        return {
            cuts,
            hints: cuts.map(() => false),
            // Added as optional v1 fields: legacy configs simply derive their
            // initial hint state from the old global indentation mode.
            indentMerged: false,
            indentHint: indentation === 'visible'
        };
    });
}

function atomicCbaCutsForRange(line, start, end) {
    const automatic = defaultCbaLines(line, 'sortable')[0].cuts;
    return automatic.filter(cut => cut > start && cut <= end);
}

function canSplitCbaLineGroup(line, lineConfig, chunkIndex) {
    if (!lineConfig || chunkIndex < 0 || chunkIndex >= lineConfig.cuts.length) return false;
    if (lineConfig.indentMerged && chunkIndex === 0) return true;
    const start = chunkIndex === 0 ? 0 : lineConfig.cuts[chunkIndex - 1];
    return atomicCbaCutsForRange(line, start, lineConfig.cuts[chunkIndex]).length > 1;
}

/** Restore a grouped code card to the tokenizer's original boundaries. */
function splitCbaLineGroup(line, lineConfig, chunkIndex) {
    if (!canSplitCbaLineGroup(line, lineConfig, chunkIndex)) return false;
    const start = chunkIndex === 0 ? 0 : lineConfig.cuts[chunkIndex - 1];
    const end = lineConfig.cuts[chunkIndex];
    const wasIndentMerged = lineConfig.indentMerged && chunkIndex === 0;
    // Body hints stay independent of the global indentation mode.  A merged
    // card is visibly fixed when indentHint is true, but must become movable
    // again as soon as the teacher switches the mode to sortable.
    const hint = Boolean(lineConfig.hints[chunkIndex]);
    const cuts = atomicCbaCutsForRange(line, start, end);
    lineConfig.cuts.splice(chunkIndex, 1, ...cuts);
    lineConfig.hints.splice(chunkIndex, 1, ...cuts.map(() => hint));
    if (wasIndentMerged) {
        lineConfig.indentMerged = false;
    }
    return true;
}

function setCbaIndentationMode(cba, indentation) {
    const mode = indentation === 'sortable' ? 'sortable' : 'visible';
    cba.indentation = mode;
    cba.lines.forEach(line => { line.indentHint = mode === 'visible'; });
}

/** Return a validated, complete CBA config or a freshly tokenised config. */
function normalizeCbaConfig(code, rawConfig, language) {
    let candidate = rawConfig;
    if (typeof candidate === 'string') {
        try { candidate = JSON.parse(candidate); } catch (_) { candidate = null; }
    }
    const fallbackIndentation = 'visible';
    const fallback = {
        v: CBA_CONFIG_VERSION,
        language: language || 'python',
        indentation: fallbackIndentation,
        lines: defaultCbaLines(code, fallbackIndentation)
    };
    if (!candidate || typeof candidate !== 'object' || candidate.v !== CBA_CONFIG_VERSION || !Array.isArray(candidate.lines) ||
        candidate.lines.length !== fallback.lines.length) return fallback;

    const normalized = {
        v: CBA_CONFIG_VERSION,
        language: typeof candidate.language === 'string' && candidate.language.trim() ? candidate.language.trim() : fallback.language,
        indentation: candidate.indentation === 'sortable' ? 'sortable' : 'visible',
        lines: []
    };
    for (let index = 0; index < fallback.lines.length; index += 1) {
        const item = candidate.lines[index];
        const max = codePointLength(splitCodeLine(String(code || '').split('\n')[index]).body);
        if (!item || typeof item !== 'object' || !Array.isArray(item.cuts) || !Array.isArray(item.hints) ||
            (item.indentMerged !== undefined && typeof item.indentMerged !== 'boolean') ||
            (item.indentHint !== undefined && typeof item.indentHint !== 'boolean')) return fallback;
        const cuts = item.cuts.map(Number);
        if (cuts.length !== item.hints.length || item.hints.some(hint => typeof hint !== 'boolean') || cuts.some((cut, i) => !Number.isInteger(cut) || cut <= 0 || cut > max || (i && cut <= cuts[i - 1])) ||
            (max > 0 && cuts[cuts.length - 1] !== max) || (max === 0 && cuts.length !== 0)) return fallback;
        normalized.lines.push({
            cuts,
            hints: item.hints.map(Boolean),
            indentMerged: item.indentMerged === true,
            indentHint: typeof item.indentHint === 'boolean'
                ? item.indentHint
                : normalized.indentation === 'visible'
        });
    }
    return normalized;
}

/** Split on H2 delimiters, but never delimit a question while inside a fence. */
function splitQuizBlocks(markdown) {
    // HTML form submission uses CRLF even when the textarea contains LF.
    // Normalize before matching line-anchored choices and code fences.
    const source = String(markdown || '').replace(/\r\n?/g, '\n');
    const lines = source.split('\n');
    const blocks = [];
    let block = null;
    let inFence = false;
    for (const line of lines) {
        if (/^```/.test(line)) inFence = !inFence;
        if (!inFence && /^## (?!#)/.test(line)) {
            if (block !== null) blocks.push(block.join('\n'));
            block = [line.slice(3)];
        } else if (block !== null) {
            block.push(line);
        }
    }
    if (block !== null) blocks.push(block.join('\n'));
    return blocks;
}

function parseCbaBlock(block) {
    const opener = /^```quiz-cba(?:\s+([^\s`]+))?\s*$/m.exec(block);
    if (!opener) return null;
    const codeStart = opener.index + opener[0].length + (block[opener.index + opener[0].length] === '\n' ? 1 : 0);
    const closeMatcher = /^```\s*$/gm;
    closeMatcher.lastIndex = codeStart;
    const closer = closeMatcher.exec(block);
    if (!closer) return null;
    const prompt = block.slice(0, opener.index).replace(/\n$/, '').trim();
    const code = block.slice(codeStart, closer.index);
    // The newline preceding a closing fence is syntax, not user code.  A
    // deliberate blank line remains represented by one newline in `code`.
    const preservedCode = code.endsWith('\n') ? code.slice(0, -1) : code;
    const configRest = block.slice(closer.index + closer[0].length).replace(/^\n/, '');
    const configOpener = /^```quiz-cba-config\s*\n?/m.exec(configRest);
    let config = null;
    if (configOpener) {
        const configStart = configOpener.index + configOpener[0].length;
        const configCloser = /^```\s*$/m.exec(configRest.slice(configStart));
        const json = configCloser ? configRest.slice(configStart, configStart + configCloser.index).replace(/\n$/, '') : configRest.slice(configStart);
        try { config = JSON.parse(json); } catch (_) { config = null; }
    }
    return { prompt, code: preservedCode, cba: normalizeCbaConfig(preservedCode, config, opener[1] || 'python') };
}

/**
 * Parse quiz markdown into structured question objects.
 * @param {string} markdown - Raw markdown string
 * @returns {Array} Array of question objects
 */
function parseQuiz(markdown) {
    resetIdCounters();
    if (!markdown || !markdown.trim()) return [];

    const questions = [];
    const blocks = splitQuizBlocks(markdown);

    for (let i = 0; i < blocks.length; i++) {
        const block = blocks[i];
        if (!block) continue;

        const cba = parseCbaBlock(block);
        if (cba) {
            if (!cba.prompt || cba.prompt === 'None') continue;
            questions.push({
                id: nextQuestionId(),
                type: 'cba',
                question: cba.prompt,
                choices: [],
                code: cba.code,
                cba: cba.cba
            });
            continue;
        }

        const lines = block.split('\n');

        // Find the first choice line (starts with >)
        let firstChoiceIdx = -1;
        for (let j = 0; j < lines.length; j++) {
            if (/^>/.test(lines[j])) {
                firstChoiceIdx = j;
                break;
            }
        }

        // Question text: everything before the first > line
        let questionText;
        let choiceLines;
        if (firstChoiceIdx === -1) {
            // No choices at all — entire block is question text (FRQ with no > marker)
            questionText = lines.join('\n').trim();
            choiceLines = [];
        } else {
            questionText = lines.slice(0, firstChoiceIdx).join('\n').trim();
            choiceLines = lines.slice(firstChoiceIdx);
        }

        if (!questionText) continue;

        const choices = [];
        let hasCorrectMarker = false;
        let hasMrqMarker = false;
        let hasSortMarker = false;

        for (let j = 0; j < choiceLines.length; j++) {
            const line = choiceLines[j];

            // Check patterns in order:
            // empty >, MCQ correct (>+), MRQ correct (>*), SRT (>N), wrong (>)
            const frqRefMatch = line.match(/^>= (.+)$/);
            const frqRefEmpty = line.match(/^>=\s*$/);
            const emptyMatch = line.match(/^>\s*$/);
            const mcqCorrectMatch = line.match(/^>\+ (.+)$/);
            const mcqCorrectEmpty = line.match(/^>\+ \s*$/);
            const mrqCorrectMatch = line.match(/^>\* (.+)$/);
            const mrqCorrectEmpty = line.match(/^>\* \s*$/);
            const sortMatch = line.match(/^>(\d+)(?:\s+(.+))?$/);
            const wrongMatch = line.match(/^> (?!\+)(?!\*)(.+)$/);

            if (mcqCorrectMatch) {
                choices.push({
                    id: nextChoiceId(),
                    text: mcqCorrectMatch[1].trim(),
                    isCorrect: true
                });
                hasCorrectMarker = true;
            } else if (mcqCorrectEmpty) {
                choices.push({
                    id: nextChoiceId(),
                    text: '',
                    isCorrect: true
                });
                hasCorrectMarker = true;
            } else if (mrqCorrectMatch) {
                choices.push({
                    id: nextChoiceId(),
                    text: mrqCorrectMatch[1].trim(),
                    isCorrect: true
                });
                hasMrqMarker = true;
                hasCorrectMarker = true;
            } else if (mrqCorrectEmpty) {
                choices.push({
                    id: nextChoiceId(),
                    text: '',
                    isCorrect: true
                });
                hasMrqMarker = true;
                hasCorrectMarker = true;
            } else if (sortMatch) {
                choices.push({
                    id: nextChoiceId(),
                    text: sortMatch[2] ? sortMatch[2].trim() : '',
                    isCorrect: false,
                    sortPosition: parseInt(sortMatch[1], 10)
                });
                hasSortMarker = true;
            } else if (wrongMatch) {
                choices.push({
                    id: nextChoiceId(),
                    text: wrongMatch[1].trim(),
                    isCorrect: false
                });
            } else if (frqRefMatch) {
                // FRQ with reference answer: >= answer text
                choices.push({
                    id: nextChoiceId(),
                    text: frqRefMatch[1].trim(),
                    isCorrect: false,
                    _isFRQRef: true
                });
            } else if (frqRefEmpty) {
                choices.push({
                    id: nextChoiceId(),
                    text: '',
                    isCorrect: false,
                    _isFRQRef: true
                });
            } else if (emptyMatch) {
                // Legacy empty > line — treated as FRQ without reference
                choices.push({
                    id: nextChoiceId(),
                    text: '',
                    isCorrect: false
                });
            }
        }

        // Determine type:
        // - No choice lines at all → FRQ
        // - Single empty choice line (`> `) → FRQ (legacy)
        // - `>= text` → FRQ with reference answer
        // - >* marker present → MRQ
        // - Otherwise → MCQ
        const isFRQ = choices.length === 0 ||
                      (choices.length === 1 && choices[0].text === '') ||
                      (choices.length === 1 && choices[0]._isFRQRef === true);

        // Auto-mark first choice as correct if none marked and choices exist
        if (!isFRQ && !hasCorrectMarker && choices.length > 0) {
            choices[0].isCorrect = true;
        }

        let qType;
        if (isFRQ) {
            qType = 'frq';
        } else if (hasSortMarker) {
            qType = 'srt';
        } else if (hasMrqMarker) {
            qType = 'mrq';
        } else {
            qType = 'mcq';
        }

        // Sanitize: skip questions where the text is literally "None" (Django null artifact)
        if (questionText === 'None') continue;

        // Extract reference answer for FRQ
        let refAnswer = '';
        if (isFRQ && choices.length === 1 && choices[0]._isFRQRef) {
            refAnswer = choices[0].text || '';
        }

        questions.push({
            id: nextQuestionId(),
            type: qType,
            question: questionText,
            choices: isFRQ ? [] : choices,
            refAnswer: refAnswer
        });
    }

    return questions;
}

/**
 * Serialize question objects back to quiz markdown.
 * @param {Array} questions - Array of question objects
 * @returns {string} Markdown string
 */
function serializeQuiz(questions) {
    if (!questions || questions.length === 0) return '';

    const blocks = questions.map(q => {
        const lines = [];
        const qText = q.question.trim() || '(Untitled Question)';
        // Question text may be multi-line — first line gets ## prefix
        const qLines = qText.split('\n');
        for (let i = 0; i < qLines.length; i++) {
            if (i === 0) {
                lines.push('## ' + qLines[i]);
            } else {
                lines.push(qLines[i]);
            }
        }

        if (q.type === 'cba') {
            const code = q.code === undefined || q.code === null ? '' : String(q.code);
            const cba = normalizeCbaConfig(code, q.cba, q.cba && q.cba.language);
            lines.push('```quiz-cba ' + cba.language);
            lines.push(code);
            lines.push('```');
            lines.push('```quiz-cba-config');
            lines.push(JSON.stringify(cba));
            lines.push('```');
        } else if (q.type === 'frq') {
            if (q.refAnswer && q.refAnswer.trim()) {
                lines.push('>= ' + q.refAnswer.trim());
            } else {
                lines.push('> ');
            }
        } else if (q.type === 'srt') {
            const choices = q.choices || [];
            for (const c of choices) {
                const pos = c.sortPosition || 0;
                if (c.text) {
                    lines.push('>' + pos + ' ' + c.text.trim());
                } else {
                    lines.push('>' + pos);
                }
            }
        } else if (q.type === 'mcq' || q.type === 'mrq') {
            const choices = q.choices || [];
            const prefix = q.type === 'mrq' ? '>*' : '>+';
            if (choices.length === 0) {
                lines.push(prefix + ' ');
                lines.push('> ');
            } else {
                for (const c of choices) {
                    if (c.isCorrect) {
                        lines.push(prefix + ' ' + c.text.trim());
                    } else {
                        lines.push('> ' + c.text.trim());
                    }
                }
            }
        }

        return lines.join('\n');
    });

    return blocks.join('\n\n');
}

// ============================================================================
// 2. Quiz Editor UI Controller
// ============================================================================

/**
 * Initialize the quiz editor, binding source textarea and preview container.
 * @param {Object} config
 * @param {string} config.sourceId      - DOM id of the markdown source textarea
 * @param {string} config.previewId     - DOM id of the preview container
 * @param {string} config.addMcqBtnId   - DOM id of "Add MCQ" button
 * @param {string} config.addFrqBtnId   - DOM id of "Add FRQ" button
 * @param {string} config.toolbarId     - DOM id of quiz toolbar (optional)
 */
function initQuizEditor(config) {
    const sourceEl = document.getElementById(config.sourceId);
    const previewEl = document.getElementById(config.previewId);
    const addMcqBtn = config.addMcqBtnId ? document.getElementById(config.addMcqBtnId) : null;
    const addFrqBtn = config.addFrqBtnId ? document.getElementById(config.addFrqBtnId) : null;    const addSrtBtn = config.addSrtBtnId ? document.getElementById(config.addSrtBtnId) : null;    const addMrqBtn = config.addMrqBtnId ? document.getElementById(config.addMrqBtnId) : null;

    if (!sourceEl || !previewEl) {
        console.warn('Quiz editor: source or preview element not found');
        return;
    }

    // ---- State ----
    let currentQuestions = [];
    let syncTimeout = null;
    let isUpdatingSource = false;  // guard to prevent recursion

    // ---- Sync: Source → Preview ----
    function syncSourceToPreview() {
        if (isUpdatingSource) return;
        const markdown = sourceEl.value;
        currentQuestions = parseQuiz(markdown);
        renderPreview(currentQuestions);
    }

    // ---- Sync: Preview → Source ----
    function syncPreviewToSource() {
        isUpdatingSource = true;
        const markdown = serializeQuiz(currentQuestions);
        sourceEl.value = markdown;
        isUpdatingSource = false;
    }

    // ---- Render preview from question data ----
    function renderPreview(questions) {
        previewEl.innerHTML = '';

        if (questions.length === 0) {
            previewEl.innerHTML = `
                <div class="quiz-empty-state">
                    <i class="bi bi-patch-question" style="font-size:2rem;opacity:0.3;"></i>
                    <p>No questions yet. Use the buttons below to add MCQ or FRQ questions.</p>
                </div>`;
            return;
        }

        questions.forEach((q, qIndex) => {
            const card = createQuestionCard(q, qIndex);
            previewEl.appendChild(card);
        });
    }

    function labelControl(labelText, control) {
        const wrapper = document.createElement('label');
        wrapper.className = 'cba-control-label';
        const label = document.createElement('span');
        label.textContent = labelText;
        wrapper.append(label, control);
        return wrapper;
    }

    // ---- Create a question card DOM element ----
    function createQuestionCard(q, qIndex) {
        const card = document.createElement('div');
        card.className = 'quiz-question-card';
        card.dataset.questionId = q.id;
        card.dataset.questionIndex = qIndex;

        // Make card draggable for reordering
        card.draggable = true;
        card.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('text/plain', JSON.stringify({ qIndex }));
            e.dataTransfer.effectAllowed = 'move';
            card.classList.add('quiz-question-dragging');
        });
        card.addEventListener('dragend', () => {
            card.classList.remove('quiz-question-dragging');
            previewEl.querySelectorAll('.quiz-question-drag-over').forEach(el => {
                el.classList.remove('quiz-question-drag-over');
            });
        });
        card.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            card.classList.add('quiz-question-drag-over');
        });
        card.addEventListener('dragleave', () => {
            card.classList.remove('quiz-question-drag-over');
        });
        card.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation(); // prevent choice-level drop from firing
            card.classList.remove('quiz-question-drag-over');
            const data = JSON.parse(e.dataTransfer.getData('text/plain'));
            if (data.qIndex !== undefined && data.cIndex === undefined) {
                moveQuestion(data.qIndex, qIndex);
            }
        });

        // Header
        const header = document.createElement('div');
        header.className = 'quiz-question-header';

        // Drag handle
        const dragHandle = document.createElement('span');
        dragHandle.className = 'quiz-question-drag-handle';
        dragHandle.innerHTML = '<i class="bi bi-grip-vertical"></i>';
        dragHandle.title = 'Drag to reorder';

        const typeCfg = QUESTION_TYPES[q.type] || QUESTION_TYPES.mcq;
        const typeBadge = document.createElement('span');
        typeBadge.className = 'quiz-type-badge ' + typeCfg.badgeClass;
        typeBadge.textContent = typeCfg.label;

        const qNumber = document.createElement('span');
        qNumber.className = 'quiz-question-number';
        qNumber.textContent = 'Q' + (qIndex + 1);

        const headerActions = document.createElement('div');
        headerActions.className = 'quiz-header-actions';

        // Type selector from QUESTION_TYPES config
        const typeGroup = document.createElement('div');
        typeGroup.className = 'btn-group btn-group-sm quiz-type-group';
        ALL_TYPES.forEach(typeKey => {
            const t = QUESTION_TYPES[typeKey];
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-sm ' + (q.type === typeKey ? 'btn-primary' : 'btn-outline-secondary');
            btn.textContent = t.label;
            btn.title = 'Switch to ' + t.label;
            btn.addEventListener('click', () => changeQuestionType(qIndex, typeKey));
            if (q.type === typeKey) btn.setAttribute('aria-pressed', 'true');
            typeGroup.appendChild(btn);
        });
        headerActions.appendChild(typeGroup);

        // Delete question
        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'btn btn-sm btn-outline-danger';
        deleteBtn.title = 'Delete question';
        deleteBtn.innerHTML = '<i class="bi bi-trash"></i>';
        deleteBtn.addEventListener('click', () => deleteQuestion(qIndex));
        headerActions.appendChild(deleteBtn);

        header.appendChild(dragHandle);
        header.appendChild(typeBadge);
        header.appendChild(qNumber);
        header.appendChild(headerActions);
        card.appendChild(header);

        // Body
        const body = document.createElement('div');
        body.className = 'quiz-question-body';

        // Question text textarea (multi-line, supports markdown)
        const questionInput = document.createElement('textarea');
        questionInput.className = 'form-control quiz-question-input';
        questionInput.rows = 3;
        questionInput.value = q.question;
        questionInput.placeholder = 'Enter question text…\nSupports **markdown**, `code`, lists, etc.';
        questionInput.addEventListener('input', () => {
            currentQuestions[qIndex].question = questionInput.value;
            // Auto-resize
            questionInput.style.height = 'auto';
            questionInput.style.height = questionInput.scrollHeight + 'px';
            syncPreviewToSource();
        });
        // Initial auto-resize
        setTimeout(() => {
            questionInput.style.height = 'auto';
            questionInput.style.height = questionInput.scrollHeight + 'px';
        }, 0);
        body.appendChild(questionInput);

        // Choices area
        const choicesArea = document.createElement('div');
        choicesArea.className = 'quiz-choices-area';

        if (typeCfg.isCodeBlocks) {
            choicesArea.appendChild(createCbaEditor(qIndex));
        } else if (typeCfg.hasChoices) {
            (q.choices || []).forEach((choice, cIndex) => {
                const choiceRow = createChoiceRow(qIndex, cIndex, choice);
                choicesArea.appendChild(choiceRow);
            });

            // Add choice button
            const addChoiceBtn = document.createElement('button');
            addChoiceBtn.type = 'button';
            addChoiceBtn.className = 'btn btn-sm btn-outline-primary quiz-add-choice-btn';
            addChoiceBtn.innerHTML = '<i class="bi bi-plus-circle"></i> Add Choice';
            addChoiceBtn.addEventListener('click', () => addChoice(qIndex));
            choicesArea.appendChild(addChoiceBtn);
        } else {
            // FRQ reference answer input
            const refGroup = document.createElement('div');
            refGroup.className = 'mb-2';
            const refLabel = document.createElement('label');
            refLabel.className = 'form-label small fw-bold';
            refLabel.textContent = 'Reference Answer';
            refGroup.appendChild(refLabel);
            const refInput = document.createElement('textarea');
            refInput.className = 'form-control form-control-sm';
            refInput.rows = 2;
            refInput.value = q.refAnswer || '';
            refInput.placeholder = 'Enter the reference answer shown to students after submission…';
            refInput.addEventListener('input', () => {
                currentQuestions[qIndex].refAnswer = refInput.value;
                syncPreviewToSource();
            });
            refGroup.appendChild(refInput);
            choicesArea.appendChild(refGroup);
        }

        body.appendChild(choicesArea);
        card.appendChild(body);

        return card;
    }

    // ---- CBA authoring surface ------------------------------------------------
    // The textarea is the code source of truth.  Token cards only edit config,
    // so no amount of grouping/hinting can accidentally rewrite teacher code.
    function createCbaEditor(qIndex) {
        const q = currentQuestions[qIndex];
        q.code = q.code === undefined || q.code === null ? '' : String(q.code);
        q.cba = normalizeCbaConfig(q.code, q.cba, q.cba && q.cba.language);
        const panel = document.createElement('section');
        panel.className = 'cba-editor';

        const toolbar = document.createElement('div');
        toolbar.className = 'cba-toolbar';
        const language = document.createElement('select');
        language.className = 'form-select form-select-sm cba-language';
        ['python', 'javascript', 'java', 'c', 'cpp', 'text'].forEach(value => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = value === 'cpp' ? 'C++' : value[0].toUpperCase() + value.slice(1);
            option.selected = q.cba.language === value;
            language.appendChild(option);
        });
        language.addEventListener('change', () => {
            currentQuestions[qIndex].cba.language = language.value;
            syncPreviewToSource();
        });
        toolbar.appendChild(labelControl('Language', language));

        const indentationControl = document.createElement('div');
        indentationControl.className = 'cba-control-label';
        indentationControl.innerHTML = '<span>Indentation</span>';
        const indentationGroup = document.createElement('div');
        indentationGroup.className = 'btn-group btn-group-sm cba-indent-mode';
        indentationGroup.setAttribute('role', 'group');
        indentationGroup.setAttribute('aria-label', 'Indentation mode');
        [['visible', 'Fixed hint'], ['sortable', 'Student arranges']].forEach(([value, label]) => {
            const button = document.createElement('button');
            const active = q.cba.indentation === value;
            button.type = 'button';
            button.className = 'btn cba-mode-btn ' + (active ? 'btn-primary is-active' : 'btn-outline-secondary');
            button.textContent = label;
            button.setAttribute('aria-pressed', String(active));
            button.addEventListener('click', () => {
                setCbaIndentationMode(currentQuestions[qIndex].cba, value);
                indentationGroup.querySelectorAll('.cba-mode-btn').forEach(candidate => {
                    const isActive = candidate === button;
                    candidate.classList.toggle('btn-primary', isActive);
                    candidate.classList.toggle('btn-outline-secondary', !isActive);
                    candidate.classList.toggle('is-active', isActive);
                    candidate.setAttribute('aria-pressed', String(isActive));
                });
                syncPreviewToSource();
                renderCards();
            });
            indentationGroup.appendChild(button);
        });
        indentationControl.appendChild(indentationGroup);
        toolbar.appendChild(indentationControl);

        const reset = document.createElement('button');
        reset.type = 'button';
        reset.className = 'btn btn-sm btn-outline-secondary cba-reset-btn';
        reset.innerHTML = '<i class="bi bi-arrow-counterclockwise"></i> Reset tokens';
        reset.title = 'Restore automatic token groups and clear hints';
        reset.addEventListener('click', () => {
            const current = currentQuestions[qIndex];
            current.cba = normalizeCbaConfig(current.code, null, current.cba.language);
            syncPreviewToSource();
            syncSourceToPreview();
        });
        toolbar.appendChild(reset);
        panel.appendChild(toolbar);

        const grid = document.createElement('div');
        grid.className = 'cba-editor-grid';
        const sourceColumn = document.createElement('div');
        sourceColumn.className = 'cba-code-column';
        const codeLabel = document.createElement('label');
        codeLabel.className = 'form-label small fw-semibold';
        codeLabel.textContent = 'Complete code';
        const code = document.createElement('textarea');
        code.className = 'form-control cba-code-input';
        code.spellcheck = false;
        code.wrap = 'off';
        code.rows = Math.max(6, q.code.split('\n').length + 1);
        code.value = q.code;
        code.placeholder = 'Write the complete program here…';
        const feedback = document.createElement('div');
        feedback.className = 'cba-code-feedback';
        code.addEventListener('input', () => {
            currentQuestions[qIndex].code = code.value;
            // A text edit invalidates offset-based groups. Rebuild immediately;
            // the short note makes this explicit rather than silently dropping
            // teacher-selected groups/hints.
            currentQuestions[qIndex].cba = normalizeCbaConfig(code.value, null, currentQuestions[qIndex].cba.language);
            feedback.textContent = 'Code changed: token groups and hints were reset.';
            syncPreviewToSource();
            clearTimeout(syncTimeout);
            syncTimeout = setTimeout(syncSourceToPreview, 120);
        });
        sourceColumn.append(codeLabel, code, feedback);

        const cardsColumn = document.createElement('div');
        cardsColumn.className = 'cba-token-column';
        const cardsLabel = document.createElement('div');
        cardsLabel.className = 'cba-token-heading';
        cardsLabel.innerHTML = '<span>Student cards</span><small>Select two adjacent cards to merge. Lock = student hint.</small>';
        const cardList = document.createElement('div');
        cardList.className = 'cba-token-lines';
        let selected = [];

        function isSelected(item) {
            return selected.some(selectedItem => selectedItem.lineIndex === item.lineIndex &&
                selectedItem.kind === item.kind && selectedItem.chunkIndex === item.chunkIndex);
        }

        function toggleSelection(item) {
            const existing = selected.findIndex(selectedItem => selectedItem.lineIndex === item.lineIndex &&
                selectedItem.kind === item.kind && selectedItem.chunkIndex === item.chunkIndex);
            if (existing >= 0) selected.splice(existing, 1);
            else if (selected.length >= 2 || (selected.length && selected[0].lineIndex !== item.lineIndex)) selected = [item];
            else selected.push(item);
            renderCards();
        }

        function createHintToggle(isHint, onToggle, disabled) {
            const toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.className = 'cba-hint-toggle' + (isHint ? ' is-hint' : '');
            toggle.disabled = Boolean(disabled);
            toggle.innerHTML = '<i class="bi bi-' + (isHint ? 'lock-fill' : 'unlock') + '"></i>';
            toggle.title = disabled ? 'Fixed by the global Fixed hint indentation mode' : (isHint ? 'Unlock: hide this hint from students' : 'Lock this card as a student hint');
            toggle.addEventListener('click', event => {
                event.stopPropagation();
                onToggle();
                syncPreviewToSource();
                renderCards();
            });
            return toggle;
        }

        function renderCards() {
            cardList.innerHTML = '';
            const current = currentQuestions[qIndex];
            current.cba = normalizeCbaConfig(current.code, current.cba, current.cba.language);
            current.code.split('\n').forEach((line, lineIndex) => {
                const { indent, body: lineBody } = splitCodeLine(line);
                const lineEl = document.createElement('div');
                lineEl.className = 'cba-token-line';
                const number = document.createElement('span');
                number.className = 'cba-line-number';
                number.textContent = String(lineIndex + 1);
                lineEl.appendChild(number);
                const lineConfig = current.cba.lines[lineIndex];
                const { cuts, hints } = lineConfig;
                const indentColumns = Array.from(indent).reduce((total, char) => total + (char === '\t' ? 4 : 1), 0);
                const createIndentVisual = () => {
                    const indentEl = document.createElement('span');
                    indentEl.className = 'cba-indent-card ' + (current.cba.indentation === 'visible' ? 'is-visible' : 'is-sortable');
                    indentEl.style.setProperty('--cba-indent-columns', indentColumns);
                    indentEl.setAttribute('aria-label', current.cba.indentation === 'visible'
                        ? 'Fixed indentation, ' + indentColumns + ' columns'
                        : 'Sortable indentation, ' + indentColumns + ' columns');
                    indentEl.textContent = '-'.repeat(Math.max(1, indentColumns)) + '|';
                    return indentEl;
                };
                if (indent && !lineConfig.indentMerged) {
                    const indentItem = { lineIndex, kind: 'indent', chunkIndex: -1 };
                    const indentChip = document.createElement('button');
                    indentChip.type = 'button';
                    indentChip.className = 'cba-indent-select' + (isSelected(indentItem) ? ' is-selected' : '');
                    indentChip.title = 'Select indentation; select the first code card to merge them';
                    indentChip.appendChild(createIndentVisual());
                    indentChip.addEventListener('click', () => toggleSelection(indentItem));
                    lineEl.appendChild(indentChip);
                }
                let start = 0;
                cuts.forEach((end, chunkIndex) => {
                    const chunk = Array.from(lineBody).slice(start, end).join('');
                    const chip = document.createElement('button');
                    chip.type = 'button';
                    const mergedIndent = Boolean(indent && lineConfig.indentMerged && chunkIndex === 0);
                    const item = { lineIndex, kind: mergedIndent ? 'merged' : 'token', chunkIndex };
                    chip.className = 'cba-token-chip' + (mergedIndent ? ' cba-indent-merged' : '') + (isSelected(item) ? ' is-selected' : '');
                    if (mergedIndent) {
                        chip.appendChild(createIndentVisual());
                        const mergedText = document.createElement('span');
                        mergedText.textContent = chunk || '∅';
                        chip.appendChild(mergedText);
                    } else {
                        chip.textContent = chunk || '∅';
                    }
                    chip.title = mergedIndent ? 'Merged indentation and first code card' : 'Select this card';
                    chip.addEventListener('click', () => toggleSelection(item));
                    const effectiveHint = mergedIndent ? Boolean(lineConfig.indentHint || hints[chunkIndex]) : hints[chunkIndex];
                    const group = document.createElement('span');
                    group.className = 'cba-chip-group';
                    const hintIsFixed = mergedIndent && lineConfig.indentHint;
                    group.append(chip, createHintToggle(effectiveHint, () => {
                        if (mergedIndent) {
                            lineConfig.hints[chunkIndex] = !lineConfig.hints[chunkIndex];
                        } else {
                            lineConfig.hints[chunkIndex] = !lineConfig.hints[chunkIndex];
                        }
                    }, hintIsFixed));
                    lineEl.appendChild(group);
                    start = end;
                });
                if (!cuts.length && !lineBody && !indent) {
                    const empty = document.createElement('span');
                    empty.className = 'cba-empty-line';
                    empty.textContent = 'blank line';
                    lineEl.appendChild(empty);
                }
                cardList.appendChild(lineEl);
            });
            const merge = document.createElement('button');
            merge.type = 'button';
            merge.className = 'btn btn-sm btn-outline-primary cba-merge-btn';
            const canMerge = selected.length === 2 && selected[0].lineIndex === selected[1].lineIndex && (() => {
                const [first, second] = selected;
                const indentAndFirstToken = (first.kind === 'indent' && second.kind === 'token' && second.chunkIndex === 0) ||
                    (second.kind === 'indent' && first.kind === 'token' && first.chunkIndex === 0);
                const isCodeCard = item => item.kind === 'token' || item.kind === 'merged';
                return indentAndFirstToken || (isCodeCard(first) && isCodeCard(second) && Math.abs(first.chunkIndex - second.chunkIndex) === 1);
            })();
            merge.disabled = !canMerge;
            merge.innerHTML = '<i class="bi bi-link-45deg"></i> Merge selected';
            merge.addEventListener('click', () => {
                if (!canMerge) return;
                const [first, second] = selected;
                const selectedLine = current.cba.lines[first.lineIndex];
                const indentAndFirstToken = (first.kind === 'indent' && second.kind === 'token' && second.chunkIndex === 0) ||
                    (second.kind === 'indent' && first.kind === 'token' && first.chunkIndex === 0);
                if (indentAndFirstToken) {
                    selectedLine.indentMerged = true;
                    selected = [];
                    syncPreviewToSource();
                    renderCards();
                    return;
                }
                // Delete the boundary after the first chip and keep the hint if
                // either component was intentionally shown as a hint.
                const leftIndex = Math.min(first.chunkIndex, second.chunkIndex);
                const mergedHint = Boolean(selectedLine.hints[leftIndex] || selectedLine.hints[leftIndex + 1]);
                selectedLine.cuts.splice(leftIndex, 1);
                selectedLine.hints.splice(leftIndex, 2, mergedHint);
                selected = [];
                syncPreviewToSource();
                renderCards();
            });
            cardList.appendChild(merge);
            const split = document.createElement('button');
            split.type = 'button';
            split.className = 'btn btn-sm btn-outline-secondary cba-split-btn';
            const splitItem = selected.length === 1 && (selected[0].kind === 'token' || selected[0].kind === 'merged') ? selected[0] : null;
            const canSplit = splitItem && canSplitCbaLineGroup(
                current.code.split('\n')[splitItem.lineIndex],
                current.cba.lines[splitItem.lineIndex],
                splitItem.chunkIndex
            );
            split.disabled = !canSplit;
            split.innerHTML = '<i class="bi bi-distribute-horizontal"></i> Split selected';
            split.addEventListener('click', () => {
                if (!canSplit) return;
                splitCbaLineGroup(
                    current.code.split('\n')[splitItem.lineIndex],
                    current.cba.lines[splitItem.lineIndex],
                    splitItem.chunkIndex
                );
                selected = [];
                syncPreviewToSource();
                renderCards();
            });
            cardList.appendChild(split);
        }
        renderCards();
        cardsColumn.append(cardsLabel, cardList);
        grid.append(sourceColumn, cardsColumn);
        panel.appendChild(grid);
        return panel;
    }

    // ---- Create a choice row DOM element ----
    function createChoiceRow(qIndex, cIndex, choice) {
        const row = document.createElement('div');
        row.className = 'quiz-choice-row';
        row.dataset.choiceIndex = cIndex;

        // Drag handle
        const dragHandle = document.createElement('span');
        dragHandle.className = 'quiz-choice-drag-handle';
        dragHandle.innerHTML = '<i class="bi bi-grip-vertical"></i>';
        dragHandle.title = 'Drag to reorder';

        // Make row draggable
        row.draggable = true;
        row.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('text/plain', JSON.stringify({ qIndex, cIndex }));
            e.dataTransfer.effectAllowed = 'move';
            row.classList.add('quiz-choice-dragging');
        });
        row.addEventListener('dragend', () => {
            row.classList.remove('quiz-choice-dragging');
            // Remove all drag-over highlights
            previewEl.querySelectorAll('.quiz-choice-drag-over').forEach(el => {
                el.classList.remove('quiz-choice-drag-over');
            });
        });
        row.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            row.classList.add('quiz-choice-drag-over');
        });
        row.addEventListener('dragleave', () => {
            row.classList.remove('quiz-choice-drag-over');
        });
        row.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation(); // prevent question-level drop
            row.classList.remove('quiz-choice-drag-over');
            const data = JSON.parse(e.dataTransfer.getData('text/plain'));
            if (data.qIndex === qIndex) {
                moveChoice(data.qIndex, data.cIndex, cIndex);
            }
        });

        // Correct answer toggle (radio for MCQ, checkbox for MRQ, none for SRT)
        const qType = currentQuestions[qIndex].type;
        const typeCfg = QUESTION_TYPES[qType] || QUESTION_TYPES.mcq;
        const toggle = document.createElement('input');
        if (qType === 'mrq') {
            toggle.type = 'checkbox';
            toggle.className = 'quiz-choice-checkbox';
            toggle.checked = choice.isCorrect;
            toggle.title = 'Toggle correct answer';
        } else if (qType === 'mcq') {
            toggle.type = 'radio';
            toggle.className = 'quiz-choice-radio';
            toggle.name = 'correct-' + currentQuestions[qIndex].id;
            toggle.checked = choice.isCorrect;
            toggle.title = 'Mark as correct answer';
        } else if (typeCfg.isSorting) {
            // Sorting: tiny position number input
            toggle.style.display = 'none';
        }
        if (qType !== 'srt') {
            toggle.addEventListener('change', () => {
                if (qType === 'mrq') {
                    currentQuestions[qIndex].choices[cIndex].isCorrect = toggle.checked;
                } else {
                    currentQuestions[qIndex].choices.forEach((c, i) => {
                        c.isCorrect = (i === cIndex);
                    });
                }
                syncPreviewToSource();
                refreshChoiceStates(qIndex);
            });
        }

        // Choice text input
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control quiz-choice-input';
        input.value = choice.text;
        input.placeholder = 'Choice text...';
        input.addEventListener('input', () => {
            currentQuestions[qIndex].choices[cIndex].text = input.value;
            syncPreviewToSource();
        });

        // Sort position input (SRT only)
        let posInput = null;
        if (typeCfg.isSorting) {
            posInput = document.createElement('input');
            posInput.type = 'number';
            posInput.className = 'form-control quiz-sort-pos-input';
            posInput.value = choice.sortPosition || (cIndex + 1);
            posInput.min = 1;
            posInput.step = 1;
            posInput.title = 'Correct order position';
            posInput.addEventListener('input', () => {
                currentQuestions[qIndex].choices[cIndex].sortPosition = parseInt(posInput.value, 10) || 0;
                syncPreviewToSource();
            });
        }

        // Delete choice button (min 1 choice for MCQ)
        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'btn btn-sm btn-outline-danger quiz-choice-delete';
        deleteBtn.innerHTML = '<i class="bi bi-x"></i>';
        deleteBtn.title = 'Remove choice';
        deleteBtn.addEventListener('click', () => deleteChoice(qIndex, cIndex));

        row.appendChild(dragHandle);
        row.appendChild(toggle);
        if (posInput) row.appendChild(posInput);
        row.appendChild(input);
        row.appendChild(deleteBtn);
        return row;
    }

    // ---- Move a choice from one index to another (drag-and-drop) ----
    function moveChoice(qIndex, fromIndex, toIndex) {
        const choices = currentQuestions[qIndex].choices;
        if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return;
        if (fromIndex >= choices.length || toIndex >= choices.length) return;
        const [moved] = choices.splice(fromIndex, 1);
        choices.splice(toIndex, 0, moved);
        syncPreviewToSource();
        syncSourceToPreview();
    }

    // ---- Refresh choice toggle states ----
    function refreshChoiceStates(qIndex) {
        const card = previewEl.querySelector(`[data-question-index="${qIndex}"]`);
        if (!card) return;
        const toggles = card.querySelectorAll('.quiz-choice-radio, .quiz-choice-checkbox');
        const choices = currentQuestions[qIndex].choices || [];
        toggles.forEach((toggle, i) => {
            toggle.checked = choices[i] && choices[i].isCorrect;
        });
    }

    // ---- Add a new MCQ question ----
    function addMCQ() {
        const newQ = {
            id: nextQuestionId(),
            type: 'mcq',
            question: '',
            choices: [
                { id: nextChoiceId(), text: '', isCorrect: true },
                { id: nextChoiceId(), text: '', isCorrect: false }
            ]
        };
        currentQuestions.push(newQ);
        syncPreviewToSource();
        syncSourceToPreview();
        previewEl.scrollTop = previewEl.scrollHeight;
        const lastCard = previewEl.querySelector('.quiz-question-card:last-child .quiz-question-input');
        if (lastCard) lastCard.focus();
    }

    // ---- Add a new MRQ question ----
    function addMRQ() {
        const newQ = {
            id: nextQuestionId(),
            type: 'mrq',
            question: '',
            choices: [
                { id: nextChoiceId(), text: '', isCorrect: true },
                { id: nextChoiceId(), text: '', isCorrect: false }
            ]
        };
        currentQuestions.push(newQ);
        syncPreviewToSource();
        syncSourceToPreview();
        previewEl.scrollTop = previewEl.scrollHeight;
        const lastCard = previewEl.querySelector('.quiz-question-card:last-child .quiz-question-input');
        if (lastCard) lastCard.focus();
    }

    // ---- Add a new SRT question ----
    function addSRT() {
        const newQ = {
            id: nextQuestionId(),
            type: 'srt',
            question: '',
            choices: [
                { id: nextChoiceId(), text: '', isCorrect: false, sortPosition: 1 },
                { id: nextChoiceId(), text: '', isCorrect: false, sortPosition: 2 }
            ]
        };
        currentQuestions.push(newQ);
        syncPreviewToSource();
        syncSourceToPreview();
        previewEl.scrollTop = previewEl.scrollHeight;
        const lastCard = previewEl.querySelector('.quiz-question-card:last-child .quiz-question-input');
        if (lastCard) lastCard.focus();
    }

    // ---- Add a new FRQ question ----
    function addFRQ() {
        const newQ = {
            id: nextQuestionId(),
            type: 'frq',
            question: '',
            choices: [],
            refAnswer: ''
        };
        currentQuestions.push(newQ);
        syncPreviewToSource();
        syncSourceToPreview();
        previewEl.scrollTop = previewEl.scrollHeight;
        const lastCard = previewEl.querySelector('.quiz-question-card:last-child .quiz-question-input');
        if (lastCard) lastCard.focus();
    }

    // ---- Add a code-block assembly question ----
    function addCBA() {
        const code = 'print("Hello, world!")';
        const newQ = {
            id: nextQuestionId(),
            type: 'cba',
            question: 'Put the program in the correct order.',
            choices: [],
            code,
            cba: normalizeCbaConfig(code, null, 'python')
        };
        currentQuestions.push(newQ);
        syncPreviewToSource();
        syncSourceToPreview();
        previewEl.scrollTop = previewEl.scrollHeight;
        const lastCard = previewEl.querySelector('.quiz-question-card:last-child .quiz-question-input');
        if (lastCard) lastCard.focus();
    }

    // ---- Delete a question ----
    function deleteQuestion(qIndex) {
        if (currentQuestions.length <= 0) return;
        currentQuestions.splice(qIndex, 1);
        syncPreviewToSource();
        syncSourceToPreview();
    }

    // ---- Move a question from one index to another (drag-and-drop) ----
    function moveQuestion(fromIndex, toIndex) {
        if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return;
        if (fromIndex >= currentQuestions.length || toIndex >= currentQuestions.length) return;
        const [moved] = currentQuestions.splice(fromIndex, 1);
        currentQuestions.splice(toIndex, 0, moved);
        syncPreviewToSource();
        syncSourceToPreview();
    }

    // ---- Change question type (MCQ / MRQ / FRQ) ----
    function changeQuestionType(qIndex, newType) {
        const q = currentQuestions[qIndex];
        if (q.type === newType) return;

        const oldType = q.type;
        const newCfg = QUESTION_TYPES[newType];
        q.type = newType;

        if (newCfg.isCodeBlocks) {
            const code = typeof q.code === 'string' ? q.code : '';
            q.choices = [];
            q.refAnswer = undefined;
            q.code = code;
            q.cba = normalizeCbaConfig(code, q.cba, q.cba && q.cba.language);
        } else if (oldType === 'cba') {
            delete q.code;
            delete q.cba;
            if (!newCfg.hasChoices) {
                q.choices = [];
                q.refAnswer = '';
            } else {
                q.choices = [
                    { id: nextChoiceId(), text: '', isCorrect: true },
                    { id: nextChoiceId(), text: '', isCorrect: false }
                ];
            }
        } else if (!newCfg.hasChoices) {
            // Switching to FRQ: clear choices, init refAnswer
            q.choices = [];
            if (q.refAnswer === undefined) q.refAnswer = '';
        } else if (oldType === 'frq') {
            // Switching from FRQ: clear refAnswer, create default choices
            q.refAnswer = undefined;
            q.choices = [
                { id: nextChoiceId(), text: '', isCorrect: true },
                { id: nextChoiceId(), text: '', isCorrect: false }
            ];
        } else if (q.type === 'srt' || oldType === 'srt') {
            // Switching to/from SRT: rebuild choices with appropriate defaults
            const count = q.choices.length > 0 ? q.choices.length : 2;
            q.choices = [];
            for (let i = 0; i < count; i++) {
                const c = { id: nextChoiceId(), text: '', isCorrect: false };
                if (newType === 'srt') c.sortPosition = i + 1;
                else if (i === 0) c.isCorrect = true;
                q.choices.push(c);
            }
        } else if (!QUESTION_TYPES[oldType] || !QUESTION_TYPES[oldType].hasChoices) {
            // Switching from FRQ to MCQ/MRQ
            q.choices = [
                { id: nextChoiceId(), text: '', isCorrect: true },
                { id: nextChoiceId(), text: '', isCorrect: false }
            ];
        } else if (newType === 'mcq' && oldType === 'mrq') {
            // MRQ → MCQ: keep only the first correct answer
            let found = false;
            q.choices.forEach(c => {
                if (c.isCorrect) {
                    if (!found) { found = true; }
                    else { c.isCorrect = false; }
                }
            });
            if (!found && q.choices.length > 0) q.choices[0].isCorrect = true;
        }
        // MCQ → MRQ: no change needed (may already have multiple correct)

        syncPreviewToSource();
        syncSourceToPreview();
    }

    // ---- Add a choice to an MCQ/MRQ/SRT question ----
    function addChoice(qIndex) {
        const q = currentQuestions[qIndex];
        const typeCfg = QUESTION_TYPES[q.type];
        if (!typeCfg || !typeCfg.hasChoices) return;
        const newChoice = { id: nextChoiceId(), text: '', isCorrect: false };
        if (typeCfg.isSorting) {
            // Auto-assign next sort position
            const maxPos = q.choices.reduce((max, c) => Math.max(max, c.sortPosition || 0), 0);
            newChoice.sortPosition = maxPos + 1;
        }
        q.choices.push(newChoice);
        syncPreviewToSource();
        syncSourceToPreview();
    }

    // ---- Delete a choice from an MCQ/MRQ question ----
    function deleteChoice(qIndex, cIndex) {
        const q = currentQuestions[qIndex];
        const typeCfg = QUESTION_TYPES[q.type];
        if (!typeCfg || !typeCfg.hasChoices) return;
        if (q.choices.length <= 1) return;
        const wasCorrect = q.choices[cIndex].isCorrect;
        q.choices.splice(cIndex, 1);
        if (!typeCfg.isSorting && wasCorrect && q.choices.length > 0) {
            q.choices[0].isCorrect = true;
        }
        syncPreviewToSource();
        syncSourceToPreview();
    }

    // ---- Event: source textarea input (debounced) ----
    sourceEl.addEventListener('input', function () {
        clearTimeout(syncTimeout);
        syncTimeout = setTimeout(() => {
            syncSourceToPreview();
        }, 300);
    });

    // ---- Add Question buttons ----
    if (addMcqBtn) addMcqBtn.addEventListener('click', addMCQ);
    if (addMrqBtn) addMrqBtn.addEventListener('click', addMRQ);
    if (addSrtBtn) addSrtBtn.addEventListener('click', addSRT);
    if (addFrqBtn) addFrqBtn.addEventListener('click', addFRQ);
    if (config.addCbaBtnId) {
        const addCbaBtn = document.getElementById(config.addCbaBtnId);
        if (addCbaBtn) addCbaBtn.addEventListener('click', addCBA);
    }

    // ---- Auto-scroll during drag (document-level for reliability) ----
    const SCROLL_ZONE = 60;   // px from edge to trigger scroll
    const SCROLL_SPEED = 12;  // px per tick

    let isDragging = false;
    let scrollSpeed = 0;
    let scrollRafId = null;

    function autoScrollLoop() {
        if (!isDragging || scrollSpeed === 0) {
            scrollRafId = null;
            return;
        }
        previewEl.scrollTop += scrollSpeed;
        scrollRafId = requestAnimationFrame(autoScrollLoop);
    }

    function updateScrollFromMouse(e) {
        const rect = previewEl.getBoundingClientRect();
        const mouseY = e.clientY;
        const distFromTop = mouseY - rect.top;
        const distFromBottom = rect.bottom - mouseY;

        if (distFromTop < SCROLL_ZONE && distFromTop > -SCROLL_ZONE) {
            // Near or above top edge
            const clampedDist = Math.max(distFromTop, 0);
            scrollSpeed = -Math.ceil((SCROLL_ZONE - clampedDist) / SCROLL_ZONE * SCROLL_SPEED);
        } else if (distFromBottom < SCROLL_ZONE && distFromBottom > -SCROLL_ZONE) {
            // Near or below bottom edge
            const clampedDist = Math.max(distFromBottom, 0);
            scrollSpeed = Math.ceil((SCROLL_ZONE - clampedDist) / SCROLL_ZONE * SCROLL_SPEED);
        } else {
            scrollSpeed = 0;
        }

        if (scrollSpeed !== 0 && !scrollRafId) {
            scrollRafId = requestAnimationFrame(autoScrollLoop);
        }
    }

    document.addEventListener('dragover', (e) => {
        if (!isDragging) return;
        updateScrollFromMouse(e);
    });

    document.addEventListener('dragstart', () => {
        isDragging = true;
    });

    document.addEventListener('dragend', () => {
        isDragging = false;
        scrollSpeed = 0;
    });

    // ---- Initial render ----
    if (sourceEl.value.trim()) {
        syncSourceToPreview();
    }

    // ---- Public API ----
    return {
        addMCQ,
        addMRQ,
        addSRT,
        addFRQ,
        addCBA,
        refresh: syncSourceToPreview,
        getQuestions: () => currentQuestions,
        setMarkdown: (md) => {
            sourceEl.value = md;
            syncSourceToPreview();
        }
    };
}

// Expose to global scope (non-module script)
const QuizEditorApi = {
    parseQuiz,
    serializeQuiz,
    initQuizEditor,
    splitQuizBlocks,
    tokenizeCodeBody,
    normalizeCbaConfig,
    codePointLength,
    canSplitCbaLineGroup,
    splitCbaLineGroup,
    setCbaIndentationMode
};

if (typeof window !== 'undefined') window.QuizEditor = QuizEditorApi;
if (typeof module !== 'undefined' && module.exports) module.exports = QuizEditorApi;
