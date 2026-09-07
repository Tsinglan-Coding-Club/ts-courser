/**
 * reference-renderer.js — Custom Reference Sheet Renderer
 *
 * Renders reference sheet markdown into a formatted reference sheet
 * with Python syntax highlighting and indentation emphasis.
 *
 * Exposed globally as:
 *   window.renderReferenceSheet(markdown) → HTML string
 */

(function() {

// ---- Python syntax highlighter ----

const PY_KEYWORDS = /\b(if|elif|else|for|while|def|return|import|from|class|try|except|finally|with|as|in|not|and|or|True|False|None|break|continue|pass|yield|lambda|global|nonlocal|assert|del|raise)\b/g;
const PY_BUILTINS = /\b(print|input|range|len|int|float|str|list|dict|set|tuple|bool|type|abs|min|max|sum|sorted|enumerate|zip|map|filter|open|isinstance|hasattr|getattr|setattr)\b(?=\s*\()/g;
const PY_NUMBER = /\b(\d+\.?\d*)\b/g;

function escapeHTML(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/**
 * Highlight a single line of Python code after HTML-escaping.
 * Applies keyword, builtin, string, comment, and number coloring.
 * @param {string} line - raw text line
 * @returns {string} HTML for the line
 */
function highlightLine(line) {
    // Compute indent level from leading spaces
    var stripped = line.replace(/^ +/, '');
    var leading = line.length - stripped.length;
    var level = Math.floor(leading / 4);
    var html = escapeHTML(line);
    var indentClass = 'ref-indent-' + Math.min(level, 3);

    // Use sentinel markers to prevent later regexes from matching
    // inside already-inserted HTML attributes.
    var M = {
        comment:    ['\x01C\x01', '\x01/C\x01'],
        string:     ['\x01S\x01', '\x01/S\x01'],
        keyword:    ['\x01K\x01', '\x01/K\x01'],
        builtin:    ['\x01B\x01', '\x01/B\x01'],
        number:     ['\x01N\x01', '\x01/N\x01'],
    };

    // 1. Comments (# …) — only when preceded by whitespace or line start
    //    (avoid matching # inside HTML entities like &#x27;)
    html = html.replace(/(^|\s)(#.*)$/, '$1' + M.comment[0] + '$2' + M.comment[1]);

    // 2. Strings (double and single quotes, already HTML-escaped)
    html = html.replace(/(&quot;(?:[^&]|&(?!quot;))*&quot;)/g, M.string[0] + '$1' + M.string[1]);
    html = html.replace(/(&#x27;(?:[^&]|&(?!#x27;))*&#x27;)/g, M.string[0] + '$1' + M.string[1]);

    // 3. Keywords (before placeholders to avoid corrupting spans)
    html = html.replace(PY_KEYWORDS, M.keyword[0] + '$1' + M.keyword[1]);

    // 4. Builtins
    html = html.replace(PY_BUILTINS, M.builtin[0] + '$1' + M.builtin[1]);

    // 5. Numbers
    html = html.replace(PY_NUMBER, M.number[0] + '$1' + M.number[1]);

    // Convert markers to actual <span> tags
    html = html.replace(/\x01C\x01(.*?)\x01\/C\x01/g, '<span class="py-comment">$1</span>');
    html = html.replace(/\x01S\x01(.*?)\x01\/S\x01/g, '<span class="py-string">$1</span>');
    html = html.replace(/\x01K\x01(.*?)\x01\/K\x01/g, '<span class="py-keyword">$1</span>');
    html = html.replace(/\x01B\x01(.*?)\x01\/B\x01/g, '<span class="py-builtin">$1</span>');
    html = html.replace(/\x01N\x01(.*?)\x01\/N\x01/g, '<span class="py-number">$1</span>');

    return '<span class="' + indentClass + '">' + html + '</span>';
}

function highlightPython(code) {
    var lines = code.split('\n');
    return lines.map(function(line) {
        return highlightLine(line);
    }).join('\n');
}

// ---- Markdown structure parser ----

/**
 * Parse reference markdown into sections.
 * Each section: { heading, codeBlocks: [string], annotations: [string] }
 */
function parseReferenceMD(md) {
    if (!md || !md.trim() || md === 'None') return [];

    var sections = [];
    var blocks = md.split(/^## /m);

    for (var i = 0; i < blocks.length; i++) {
        var block = blocks[i].trim();
        if (!block) continue;

        var lines = block.split('\n');
        var heading = lines[0].trim();
        var codeBlocks = [];
        var annotations = [];
        var inCode = false;
        var codeBuf = [];

        for (var j = 1; j < lines.length; j++) {
            var line = lines[j];

            if (/^```/.test(line)) {
                if (inCode) {
                    codeBlocks.push(codeBuf.join('\n'));
                    codeBuf = [];
                    inCode = false;
                } else {
                    inCode = true;
                }
                continue;
            }

            if (inCode) {
                codeBuf.push(line);
            } else if (/^- /.test(line)) {
                annotations.push(line.replace(/^- /, '').trim());
            }
        }

        // Unclosed code block
        if (inCode && codeBuf.length > 0) {
            codeBlocks.push(codeBuf.join('\n'));
        }

        sections.push({
            heading: heading,
            codeBlocks: codeBlocks,
            annotations: annotations,
        });
    }

    return sections;
}

// ---- Renderer ----

/**
 * Render reference sheet markdown to HTML.
 * @param {string} md - Raw markdown string
 * @returns {string} HTML for the reference sheet
 */
function renderReferenceSheet(md) {
    var sections = parseReferenceMD(md);
    if (sections.length === 0) return '';

    var html = '<div class="ref-sheet">';
    for (var i = 0; i < sections.length; i++) {
        var sec = sections[i];
        html += '<div class="ref-section">';
        html += '<h3 class="ref-heading">' + escapeHTML(sec.heading) + '</h3>';

        // Code blocks
        for (var k = 0; k < sec.codeBlocks.length; k++) {
            html += '<pre class="ref-code-block"><code>';
            html += highlightPython(sec.codeBlocks[k]);
            html += '</code></pre>';
        }

        // Annotations
        for (var a = 0; a < sec.annotations.length; a++) {
            var ann = sec.annotations[a];
            // Inline code within annotations
            ann = escapeHTML(ann).replace(/`([^`]+)`/g, '<code>$1</code>');
            html += '<div class="ref-annotation">' + ann + '</div>';
        }

        html += '</div>';
    }
    html += '</div>';
    return html;
}

// Expose globally
window.renderReferenceSheet = renderReferenceSheet;

})();
