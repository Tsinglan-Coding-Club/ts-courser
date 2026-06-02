/**
 * console.js — Custom Terminal-Style Console Panel
 *
 * A lightweight, zero-dependency console UI component for displaying
 * Python stdout/stderr output. Supports basic ANSI escape codes.
 *
 * Usage:
 *   const console = new ConsolePanel(document.getElementById('console'));
 *   console.writeln('Hello, World!', 'stdout');
 *   console.writeln('Error occurred', 'stderr');
 *   console.clear();
 */

class ConsolePanel {
    /**
     * @param {HTMLElement|string} container - DOM element or CSS selector
     */
    constructor(container) {
        this._container = typeof container === 'string'
            ? document.querySelector(container)
            : container;

        if (!this._container) {
            throw new Error('ConsolePanel: container not found');
        }

        this._maxLines = 2000;
        this._lineCount = 0;
        this._isDestroyed = false;

        this._buildDOM();
        this._bindEvents();
    }

    // ---- DOM Construction ----

    _buildDOM() {
        this._container.classList.add('console-panel');
        this._container.innerHTML = `
            <div class="console-header">
                <span class="console-title">
                    <i class="bi bi-terminal"></i> Console
                </span>
                <div class="console-actions">
                    <button class="console-btn" data-action="copy" title="Copy output">
                        <i class="bi bi-copy"></i>
                    </button>
                    <button class="console-btn" data-action="clear" title="Clear console">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </div>
            <div class="console-output" id="${this._uid('output')}"></div>
        `;

        this._outputEl = this._container.querySelector('.console-output');
    }

    _uid(suffix) {
        return `console-${suffix}-${Math.random().toString(36).slice(2, 8)}`;
    }

    _bindEvents() {
        this._container.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-action]');
            if (!btn) return;

            const action = btn.dataset.action;
            if (action === 'copy') this._copy();
            if (action === 'clear') this.clear();
        });
    }

    // ---- Output Methods ----

    /**
     * Append text to the console.
     *
     * Pyodide's stdout is line-buffered: each callback delivers one complete
     * line of output (the trailing \n is consumed as a flush delimiter and
     * never passed to the handler). writeln() manually appends \n for system
     * messages. Both cases are handled uniformly: split by \n, render each
     * non-trailing segment as a <div> line.
     *
     * @param {string} text - The text to write
     * @param {'stdout'|'stderr'|'system'} type - Output type for styling
     */
    write(text, type = 'stdout') {
        if (this._isDestroyed) return;
        if (text === undefined || text === null) return;

        const str = String(text);
        const lines = str.split('\n');

        // A trailing empty segment means the input ended with \n
        // (e.g. from writeln). Don't render it — it's just a terminator.
        // But a single empty segment (write("")) should render as a blank line.
        const hasTrailingNL = lines.length > 1 && lines[lines.length - 1] === '';
        const end = hasTrailingNL ? lines.length - 1 : lines.length;

        for (let i = 0; i < end; i++) {
            this._appendLine(lines[i], type);
        }
    }

    /**
     * Append text followed by a newline.
     * @param {string} text
     * @param {'stdout'|'stderr'|'system'} type
     */
    writeln(text, type) {
        this.write(String(text !== undefined ? text : '') + '\n', type);
    }

    /**
     * Clear all output.
     */
    clear() {
        if (this._isDestroyed) return;
        this._outputEl.innerHTML = '';
        this._lineCount = 0;
    }

    /**
     * Destroy the console panel, removing all DOM elements and listeners.
     */
    destroy() {
        this._isDestroyed = true;
        if (this._container) {
            this._container.innerHTML = '';
            this._container.classList.remove('console-panel');
        }
    }

    // ---- Internal ----

    _appendLine(text, type) {
        const lineEl = document.createElement('div');
        lineEl.className = `console-line console-${type}`;

        // Treat 'input' same as special type for styling
        // (console.css has .console-input for the REPL; we reuse it)

        // Basic ANSI escape code parsing
        if (text.indexOf('\x1b[') !== -1) {
            lineEl.innerHTML = this._parseAnsi(text);
        } else {
            lineEl.textContent = text;
        }

        this._outputEl.appendChild(lineEl);
        this._lineCount++;

        // Trim old lines if over limit (handles both steady-state and burst writes)
        while (this._lineCount > this._maxLines) {
            const firstChild = this._outputEl.firstChild;
            if (firstChild) firstChild.remove();
            this._lineCount--;
        }

        // Auto-scroll to bottom
        this._scrollToBottom();
    }

    _scrollToBottom() {
        if (this._outputEl) {
            this._outputEl.scrollTop = this._outputEl.scrollHeight;
        }
    }

    /**
     * Parse basic ANSI escape sequences into HTML spans.
     * Supports: colors (30-37, 90-97), reset (0), bold (1)
     */
    _parseAnsi(text) {
        // Map ANSI codes to CSS classes
        const colorMap = {
            '30': 'ansi-black',   '31': 'ansi-red',     '32': 'ansi-green',
            '33': 'ansi-yellow',  '34': 'ansi-blue',    '35': 'ansi-magenta',
            '36': 'ansi-cyan',    '37': 'ansi-white',
            '90': 'ansi-bright-black',  '91': 'ansi-bright-red',
            '92': 'ansi-bright-green',  '93': 'ansi-bright-yellow',
            '94': 'ansi-bright-blue',   '95': 'ansi-bright-magenta',
            '96': 'ansi-bright-cyan',   '97': 'ansi-bright-white',
        };

        // Replace ANSI sequences with spans
        let html = '';
        let currentClasses = [];
        let i = 0;

        while (i < text.length) {
            if (text[i] === '\x1b' && text[i + 1] === '[') {
                // Find the end of the escape sequence
                const end = text.indexOf('m', i + 2);
                if (end === -1) {
                    html += _escapeHtml(text[i]);
                    i++;
                    continue;
                }

                const code = text.substring(i + 2, end);
                i = end + 1;

                // Parse codes
                const codes = code.split(';');
                for (const c of codes) {
                    if (c === '0') {
                        // Reset
                        if (currentClasses.length > 0) {
                            html += '</span>';
                            currentClasses = [];
                        }
                    } else if (c === '1') {
                        currentClasses.push('ansi-bold');
                    } else if (colorMap[c]) {
                        currentClasses.push(colorMap[c]);
                    }
                }

                if (currentClasses.length > 0) {
                    html += `<span class="${currentClasses.join(' ')}">`;
                }
            } else {
                html += _escapeHtml(text[i]);
                i++;
            }
        }

        // Close any open spans
        if (currentClasses.length > 0) {
            html += '</span>';
        }

        return html;
    }

    // ---- Actions ----

    _copy() {
        const text = this._outputEl
            ? Array.from(this._outputEl.children).map(el => el.textContent).join('\n')
            : '';

        navigator.clipboard.writeText(text).then(() => {
            this._flashAction('copy');
        }).catch(() => {
            // Fallback: select and copy
            const range = document.createRange();
            range.selectNodeContents(this._outputEl);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            document.execCommand('copy');
            sel.removeAllRanges();
        });
    }

    _flashAction(action) {
        const btn = this._container.querySelector(`[data-action="${action}"]`);
        if (!btn) return;
        const icon = btn.querySelector('i');
        if (!icon) return;

        const origClass = icon.className;
        icon.className = 'bi bi-check';
        setTimeout(() => {
            icon.className = origClass;
        }, 1000);
    }
}

/**
 * Escape HTML special characters.
 */
function _escapeHtml(str) {
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
    return str.replace(/[&<>"']/g, c => map[c]);
}

// Export globally (non-module script)
window.ConsolePanel = ConsolePanel;
