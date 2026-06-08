/**
 * Quiz Editor — Markdown-based quiz question editor with visual preview.
 *
 * ## Quiz Markdown Format
 *
 * Questions are separated by `## ` (h2) at line start. Question text can span
 * multiple lines (everything before the first `>` choice line).
 *
 * ### MCQ (Multiple Choice Question)
 * ```
 * ## What is 2+2?
 * Here is some **explanation** with `code`.
 * >+ 4
 * > 3
 * > 5
 * ```
 * - `## ` starts a new question (h2 delimiter)
 * - `>+` marks the correct answer
 * - `>` marks wrong answers
 * - Question text: all lines between `## ` and first `>` line
 *
 * ### FRQ (Free Response Question)
 * ```
 * ## Explain Newton's First Law.
 * Use **markdown** in your response.
 * >
 * ```
 * - Exactly one `>` with no content = FRQ
 *
 * ## API
 *
 * - parseQuiz(markdown)  → [{id, type, question, choices: [{id, text, isCorrect}]}]
 * - serializeQuiz(data)  → markdown string
 * - initQuizEditor(config) → attaches editor to DOM elements
 */

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

/**
 * Parse quiz markdown into structured question objects.
 * @param {string} markdown - Raw markdown string
 * @returns {Array} Array of question objects
 */
function parseQuiz(markdown) {
    resetIdCounters();
    if (!markdown || !markdown.trim()) return [];

    const questions = [];
    // Split by ## at line start (h2 only, not ###)
    const blocks = markdown.split(/^## (?![#])/m);

    for (let i = 0; i < blocks.length; i++) {
        const block = blocks[i];
        if (!block) continue;

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

        for (let j = 0; j < choiceLines.length; j++) {
            const line = choiceLines[j];

            // Check patterns in order: empty >, correct with text, correct empty, wrong
            const emptyMatch = line.match(/^>\s*$/);
            const correctMatch = line.match(/^>\+ (.+)$/);
            const correctEmpty = line.match(/^>\+ \s*$/);
            const wrongMatch = line.match(/^> (?!\+)(.+)$/);

            if (correctMatch) {
                choices.push({
                    id: nextChoiceId(),
                    text: correctMatch[1].trim(),
                    isCorrect: true
                });
                hasCorrectMarker = true;
            } else if (correctEmpty) {
                choices.push({
                    id: nextChoiceId(),
                    text: '',
                    isCorrect: true
                });
                hasCorrectMarker = true;
            } else if (wrongMatch) {
                choices.push({
                    id: nextChoiceId(),
                    text: wrongMatch[1].trim(),
                    isCorrect: false
                });
            } else if (emptyMatch) {
                // Empty > line — will be treated as FRQ indicator below
                choices.push({
                    id: nextChoiceId(),
                    text: '',
                    isCorrect: false
                });
            }
        }

        // Determine type:
        // - No choice lines at all → FRQ
        // - Single empty choice line → FRQ
        // - Multiple choices with content → MCQ
        const isFRQ = choices.length === 0 ||
                      (choices.length === 1 && choices[0].text === '');

        // Auto-mark first choice as correct for MCQ if none marked and choices exist
        if (!isFRQ && !hasCorrectMarker && choices.length > 0) {
            choices[0].isCorrect = true;
        }

        // Sanitize: skip questions where the text is literally "None" (Django null artifact)
        if (questionText === 'None') continue;

        questions.push({
            id: nextQuestionId(),
            type: isFRQ ? 'frq' : 'mcq',
            question: questionText,
            choices: isFRQ ? [] : choices
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

        if (q.type === 'frq') {
            lines.push('> ');
        } else if (q.type === 'mcq') {
            const choices = q.choices || [];
            if (choices.length === 0) {
                // MCQ with no choices — add two empty defaults
                lines.push('>+ ');
                lines.push('> ');
            } else {
                for (const c of choices) {
                    if (c.isCorrect) {
                        lines.push('>+ ' + c.text.trim());
                    } else {
                        lines.push('> ' + c.text.trim());
                    }
                }
            }
        }

        return lines.join('\n');
    });

    return blocks.join('\n\n') + '\n';
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
    const addFrqBtn = config.addFrqBtnId ? document.getElementById(config.addFrqBtnId) : null;

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

        const typeBadge = document.createElement('span');
        typeBadge.className = 'quiz-type-badge ' + (q.type === 'mcq' ? 'quiz-type-mcq' : 'quiz-type-frq');
        typeBadge.textContent = q.type === 'mcq' ? 'MCQ' : 'FRQ';

        const qNumber = document.createElement('span');
        qNumber.className = 'quiz-question-number';
        qNumber.textContent = 'Q' + (qIndex + 1);

        const headerActions = document.createElement('div');
        headerActions.className = 'quiz-header-actions';

        // Toggle MCQ ↔ FRQ
        const toggleBtn = document.createElement('button');
        toggleBtn.type = 'button';
        toggleBtn.className = 'btn btn-sm btn-outline-secondary';
        toggleBtn.title = q.type === 'mcq' ? 'Convert to FRQ' : 'Convert to MCQ';
        toggleBtn.innerHTML = q.type === 'mcq'
            ? '<i class="bi bi-arrow-left-right"></i> FRQ'
            : '<i class="bi bi-arrow-left-right"></i> MCQ';
        toggleBtn.addEventListener('click', () => toggleQuestionType(qIndex));

        // Delete question
        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'btn btn-sm btn-outline-danger';
        deleteBtn.title = 'Delete question';
        deleteBtn.innerHTML = '<i class="bi bi-trash"></i>';
        deleteBtn.addEventListener('click', () => deleteQuestion(qIndex));

        headerActions.appendChild(toggleBtn);
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

        if (q.type === 'mcq') {
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
            // FRQ placeholder
            const frqPlaceholder = document.createElement('div');
            frqPlaceholder.className = 'quiz-frq-placeholder';
            frqPlaceholder.innerHTML = '<i class="bi bi-pencil-square"></i> Free response — student will type answer here';
            choicesArea.appendChild(frqPlaceholder);
        }

        body.appendChild(choicesArea);
        card.appendChild(body);

        return card;
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

        // Correct answer radio
        const radio = document.createElement('input');
        radio.type = 'radio';
        radio.className = 'quiz-choice-radio';
        radio.name = 'correct-' + currentQuestions[qIndex].id;
        radio.checked = choice.isCorrect;
        radio.title = 'Mark as correct answer';
        radio.addEventListener('change', () => {
            // Unset all, set this one
            currentQuestions[qIndex].choices.forEach((c, i) => {
                c.isCorrect = (i === cIndex);
            });
            syncPreviewToSource();
            // Refresh radio states in DOM
            refreshChoiceRadios(qIndex);
        });

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

        // Delete choice button (min 1 choice for MCQ)
        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'btn btn-sm btn-outline-danger quiz-choice-delete';
        deleteBtn.innerHTML = '<i class="bi bi-x"></i>';
        deleteBtn.title = 'Remove choice';
        deleteBtn.addEventListener('click', () => deleteChoice(qIndex, cIndex));

        row.appendChild(dragHandle);
        row.appendChild(radio);
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

    // ---- Refresh radio button states after correct answer change ----
    function refreshChoiceRadios(qIndex) {
        const card = previewEl.querySelector(`[data-question-index="${qIndex}"]`);
        if (!card) return;
        const radios = card.querySelectorAll('.quiz-choice-radio');
        const choices = currentQuestions[qIndex].choices || [];
        radios.forEach((radio, i) => {
            radio.checked = choices[i] && choices[i].isCorrect;
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
        // Scroll to bottom
        previewEl.scrollTop = previewEl.scrollHeight;
        // Focus the new question input
        const lastCard = previewEl.querySelector('.quiz-question-card:last-child .quiz-question-input');
        if (lastCard) lastCard.focus();
    }

    // ---- Add a new FRQ question ----
    function addFRQ() {
        const newQ = {
            id: nextQuestionId(),
            type: 'frq',
            question: '',
            choices: []
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

    // ---- Toggle question type (MCQ ↔ FRQ) ----
    function toggleQuestionType(qIndex) {
        const q = currentQuestions[qIndex];
        if (q.type === 'mcq') {
            q.type = 'frq';
            q.choices = [];
        } else {
            q.type = 'mcq';
            q.choices = [
                { id: nextChoiceId(), text: '', isCorrect: true },
                { id: nextChoiceId(), text: '', isCorrect: false }
            ];
        }
        syncPreviewToSource();
        syncSourceToPreview();
    }

    // ---- Add a choice to an MCQ question ----
    function addChoice(qIndex) {
        const q = currentQuestions[qIndex];
        if (q.type !== 'mcq') return;
        q.choices.push({ id: nextChoiceId(), text: '', isCorrect: false });
        syncPreviewToSource();
        syncSourceToPreview();
    }

    // ---- Delete a choice from an MCQ question ----
    function deleteChoice(qIndex, cIndex) {
        const q = currentQuestions[qIndex];
        if (q.type !== 'mcq') return;
        if (q.choices.length <= 1) return; // minimum 1 choice
        const wasCorrect = q.choices[cIndex].isCorrect;
        q.choices.splice(cIndex, 1);
        // If the deleted choice was the correct one, mark first as correct
        if (wasCorrect && q.choices.length > 0) {
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
    if (addMcqBtn) {
        addMcqBtn.addEventListener('click', addMCQ);
    }
    if (addFrqBtn) {
        addFrqBtn.addEventListener('click', addFRQ);
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
        addFRQ,
        refresh: syncSourceToPreview,
        getQuestions: () => currentQuestions,
        setMarkdown: (md) => {
            sourceEl.value = md;
            syncSourceToPreview();
        }
    };
}

// Expose to global scope (non-module script)
window.QuizEditor = {
    parseQuiz,
    serializeQuiz,
    initQuizEditor
};
