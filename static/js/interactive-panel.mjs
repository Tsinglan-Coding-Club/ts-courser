/**
 * A small, dependency-free renderer for values emitted by the courser Python
 * library.  The runtime owns conversion from Python values to the serialisable
 * node shape used here; this module only renders those snapshots.
 */

const MAX_CELLS = 2500;
const MAX_DIMENSION = 100;

/** Return a stable description without changing the runtime's node object. */
export function nodeFingerprint(node) {
    if (!node || typeof node !== 'object') return 'invalid';
    if (node.kind === 'scalar') {
        return `scalar:${String(node.key)}:${String(node.text)}`;
    }
    if (node.kind === 'list' && Array.isArray(node.items)) {
        return `list:[${node.items.map(nodeFingerprint).join(',')}]`;
    }
    return 'invalid';
}

/**
 * Validate the shape accepted by display_map.  A valid grid is non-empty,
 * rectangular, two-dimensional, and small enough to remain useful in a panel.
 */
export function validateMapNode(node) {
    if (!node || node.kind !== 'list' || !Array.isArray(node.items) || node.items.length === 0) {
        return { valid: false, rows: 0, cols: 0, cells: [] };
    }
    const rows = node.items;
    if (rows.length > MAX_DIMENSION || !rows.every((row) => row && row.kind === 'list' && Array.isArray(row.items))) {
        return { valid: false, rows: 0, cols: 0, cells: [] };
    }
    const cols = rows[0].items.length;
    if (cols === 0 || cols > MAX_DIMENSION || rows.some((row) => row.items.length !== cols)) {
        return { valid: false, rows: 0, cols: 0, cells: [] };
    }
    if (rows.length * cols > MAX_CELLS || rows.some((row) => row.items.some((cell) => !cell || cell.kind !== 'scalar'))) {
        return { valid: false, rows: 0, cols: 0, cells: [] };
    }
    return { valid: true, rows: rows.length, cols, cells: rows.map((row) => row.items) };
}

/** Get the glyph to paint in a map cell. Unknown values deliberately stay raw. */
export function mapCellDisplay(node, symbols) {
    const symbol = (symbols || []).find((entry) => entry && String(entry.key) === String(node && node.key));
    return symbol ? String(symbol.text) : String(node && node.text);
}

/** Build the legend only from declared symbols that are actually present. */
export function collectMapLegend(grid, symbols) {
    if (!grid || !grid.valid) return [];
    const used = new Map();
    for (const row of grid.cells) {
        for (const cell of row) {
            const key = String(cell.key);
            if (!used.has(key)) used.set(key, String(cell.text));
        }
    }
    const seen = new Set();
    return (Array.isArray(symbols) ? symbols : []).flatMap((symbol) => {
        if (!symbol || seen.has(String(symbol.key)) || !used.has(String(symbol.key))) return [];
        seen.add(String(symbol.key));
        return [{ key: String(symbol.key), text: String(symbol.text), value: used.get(String(symbol.key)) }];
    });
}

function createElement(documentRef, tag, className, text) {
    const element = documentRef.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
}

function slotKey(label) {
    return label === null || label === undefined ? '__default__' : `label:${String(label)}`;
}

function snapshotFingerprint(snapshot) {
    if (!snapshot) return '';
    const symbols = snapshot.symbols
        .map((symbol) => `${String(symbol.key)}:${String(symbol.text)}`)
        .join('|');
    return `${nodeFingerprint(snapshot.value)}|${symbols}`;
}

export class InteractivePanel {
    constructor(root) {
        if (!root || !root.ownerDocument) throw new Error('InteractivePanel requires a DOM element');
        this.root = root;
        this.document = root.ownerDocument;
        this.displaySlots = new Map();
        this.mapSnapshot = null;
        this.view = 'map';
        this.showIndexes = false;
        this.selectedCell = null;
        this._cardElements = new Map();
        this._hasRendered = false;
        this._mapFingerprint = '';
        this._mapElementRendered = false;
        this._destroyed = false;
        this._resizeObserver = null;
        this._build();
    }

    _build() {
        this.root.classList.add('interactive-panel');
        this.root.replaceChildren();

        this.toolbar = createElement(this.document, 'div', 'interactive-toolbar');
        this.mapButton = this._makeButton('Map', 'interactive-toggle is-selected', () => this._setView('map'));
        this.dataButton = this._makeButton('Data', 'interactive-toggle', () => this._setView('data'));
        this.indexLabel = createElement(this.document, 'label', 'interactive-index-toggle');
        this.indexCheckbox = this.document.createElement('input');
        this.indexCheckbox.type = 'checkbox';
        this.indexCheckbox.addEventListener('change', () => {
            this.showIndexes = this.indexCheckbox.checked;
            this._renderMap();
        });
        this.indexLabel.append(this.indexCheckbox, this.document.createTextNode(' Indexes'));
        this.toolbar.append(this.mapButton, this.dataButton, this.indexLabel);

        this.content = createElement(this.document, 'div', 'interactive-content');
        this.cards = createElement(this.document, 'div', 'interactive-display-cards');
        this.mapArea = createElement(this.document, 'div', 'interactive-map-area');
        this.empty = createElement(this.document, 'div', 'interactive-empty');
        const importLine = createElement(this.document, 'code', 'interactive-empty-import', 'from courser import display, display_map, define_symbol');
        const hint = createElement(this.document, 'p', 'interactive-empty-hint', 'Use the courser website library to show values and maps while your program runs.');
        this.empty.append(importLine, hint);
        this.status = createElement(this.document, 'div', 'interactive-selection-status');
        this.status.setAttribute('aria-live', 'polite');
        this.status.setAttribute('aria-atomic', 'true');
        this.content.append(this.cards, this.mapArea, this.empty, this.status);
        this.root.append(this.toolbar, this.content);

        if (typeof ResizeObserver !== 'undefined') {
            this._resizeObserver = new ResizeObserver(() => this._layoutMap());
            this._resizeObserver.observe(this.mapArea);
        }
        this._render();
    }

    _makeButton(label, className, action) {
        const button = createElement(this.document, 'button', className, label);
        button.type = 'button';
        button.setAttribute('aria-pressed', 'false');
        button.addEventListener('click', action);
        return button;
    }

    /** Merge new snapshot events. Named display slots persist independently. */
    applyEvents(events) {
        if (this._destroyed || !Array.isArray(events)) return;
        let mapChanged = false;
        for (const event of events) {
            if (!event || typeof event !== 'object') continue;
            if (event.type === 'display' && event.value) {
                const label = event.label === null || event.label === undefined ? null : String(event.label);
                this.displaySlots.set(slotKey(label), { label, value: event.value });
            } else if (event.type === 'map' && event.value) {
                const symbols = Array.isArray(event.symbols)
                    ? event.symbols.filter((symbol) => symbol && Object.hasOwn(symbol, 'key') && Object.hasOwn(symbol, 'text'))
                    : [];
                const snapshot = { value: event.value, symbols };
                const fingerprint = snapshotFingerprint(snapshot);
                mapChanged = mapChanged || fingerprint !== this._mapFingerprint;
                this.mapSnapshot = snapshot;
                this._mapFingerprint = fingerprint;
            }
        }
        this._render(mapChanged);
    }

    reset() {
        if (this._destroyed) return;
        this.displaySlots.clear();
        this.mapSnapshot = null;
        this.view = 'map';
        this.showIndexes = false;
        this.selectedCell = null;
        this._cardElements.clear();
        this.cards.replaceChildren();
        this.mapArea.replaceChildren();
        this._lastGrid = null;
        this._gridElement = null;
        this._gridFrame = null;
        this._mapStage = null;
        this._legendElement = null;
        this._hasRendered = false;
        this._mapFingerprint = '';
        this._mapElementRendered = false;
        this.status.textContent = '';
        this._render(false);
    }

    destroy() {
        if (this._destroyed) return;
        this._destroyed = true;
        if (this._resizeObserver) this._resizeObserver.disconnect();
        this.root.replaceChildren();
        this.root.classList.remove('interactive-panel');
        this.root.classList.remove('has-map');
    }

    _setView(view) {
        if (!this.mapSnapshot || this.view === view) return;
        this.view = view;
        this._render(true);
    }

    _render(mapChanged = false) {
        const hasMap = Boolean(this.mapSnapshot);
        const hasContent = hasMap || this.displaySlots.size > 0;
        this.empty.hidden = hasContent;
        this.toolbar.hidden = !hasMap;
        this.cards.hidden = this.displaySlots.size === 0;
        this.mapArea.hidden = !hasMap;
        this.root.classList.toggle('has-map', hasMap);
        if (!hasContent) return;

        this._renderCards();
        if (hasMap) {
            this.mapButton.classList.toggle('is-selected', this.view === 'map');
            this.dataButton.classList.toggle('is-selected', this.view === 'data');
            this.mapButton.setAttribute('aria-pressed', String(this.view === 'map'));
            this.dataButton.setAttribute('aria-pressed', String(this.view === 'data'));
            this.indexCheckbox.checked = this.showIndexes;
            if (mapChanged || !this._mapElementRendered) this._renderMap();
        }
        this._hasRendered = true;
    }

    _renderCards() {
        const currentKeys = new Set(this.displaySlots.keys());
        for (const [key, card] of this._cardElements) {
            if (!currentKeys.has(key)) {
                card.remove();
                this._cardElements.delete(key);
            }
        }
        for (const [key, slot] of this.displaySlots) {
            const fingerprint = nodeFingerprint(slot.value);
            let card = this._cardElements.get(key);
            const previous = card && card.dataset.fingerprint;
            if (!card) {
                card = createElement(this.document, 'section', 'interactive-value-card');
                card.dataset.slot = key;
                this._cardElements.set(key, card);
                this.cards.append(card);
            }
            if (previous !== fingerprint) {
                card.replaceChildren();
                const title = createElement(this.document, 'h3', 'interactive-value-label', slot.label === null ? 'Output' : slot.label);
                // General display values always expose their Python list offsets.
                // The checkbox controls the map's row and column axes.
                card.append(title, this._renderNode(slot.value, true));
                card.dataset.fingerprint = fingerprint;
                if (this._hasRendered && previous !== undefined) this._flash(card);
            }
        }
    }

    _renderNode(node, showIndexes) {
        if (!node || typeof node !== 'object') return createElement(this.document, 'span', 'interactive-scalar', 'Invalid value');
        if (node.kind === 'scalar') return createElement(this.document, 'span', 'interactive-scalar', String(node.text));
        if (node.kind !== 'list' || !Array.isArray(node.items)) return createElement(this.document, 'span', 'interactive-scalar', String(node.text || 'Invalid value'));
        if (node.items.length === 0) return createElement(this.document, 'span', 'interactive-empty-list', '[]');

        if (node.items.every((item) => item && item.kind === 'list' && Array.isArray(item.items))) {
            return this._renderMatrix(node, showIndexes);
        }

        const list = createElement(this.document, 'ol', 'interactive-list');
        node.items.forEach((item, index) => {
            const entry = createElement(this.document, 'li', 'interactive-list-item');
            if (showIndexes) entry.dataset.index = String(index);
            entry.append(this._renderNode(item, showIndexes));
            list.append(entry);
        });
        return list;
    }

    _renderMatrix(node, showIndexes) {
        const matrix = createElement(this.document, 'div', 'interactive-value-matrix');
        const columns = Math.max(...node.items.map((row) => row.items.length));
        matrix.style.setProperty('--interactive-value-columns', String(Math.max(columns, 1)));
        node.items.forEach((row, rowIndex) => {
            const rowLabel = createElement(this.document, 'span', 'interactive-value-row-label', showIndexes ? `[${rowIndex}]` : '');
            rowLabel.style.gridRow = String(rowIndex + 1);
            rowLabel.style.gridColumn = '1';
            matrix.append(rowLabel);
            row.items.forEach((item, colIndex) => {
                const cell = createElement(this.document, 'div', 'interactive-value-matrix-cell');
                if (showIndexes) cell.dataset.index = `[${rowIndex}][${colIndex}]`;
                cell.style.gridRow = String(rowIndex + 1);
                cell.style.gridColumn = String(colIndex + 2);
                cell.append(this._renderNode(item, false));
                matrix.append(cell);
            });
            if (row.items.length === 0) {
                const empty = createElement(this.document, 'span', 'interactive-empty-list', '[]');
                empty.style.gridRow = String(rowIndex + 1);
                empty.style.gridColumn = '2';
                matrix.append(empty);
            }
        });
        return matrix;
    }

    _renderMap() {
        if (!this.mapSnapshot) return;
        this._mapElementRendered = true;
        const grid = validateMapNode(this.mapSnapshot.value);
        const priorSelected = this.selectedCell;
        const hadFocus = this.mapArea.contains(this.document.activeElement);
        const focusedCell = this.document.activeElement && this.document.activeElement.closest
            ? this.document.activeElement.closest('.interactive-map-cell')
            : null;
        const focusedCoordinates = focusedCell ? {
            row: Number(focusedCell.dataset.row),
            col: Number(focusedCell.dataset.col),
        } : null;
        if (!grid.valid) {
            this.mapArea.replaceChildren();
            this._lastGrid = null;
            this._gridElement = null;
            this._gridFrame = null;
            this._mapStage = null;
            this._legendElement = null;
            this.mapArea.append(createElement(this.document, 'p', 'interactive-map-error', 'display_map requires a non-empty rectangular two-dimensional list.'));
            this.status.textContent = '';
            return;
        }

        const geometryChanged = !this._lastGrid
            || !this._gridElement
            || this._lastGrid.rows !== grid.rows
            || this._lastGrid.cols !== grid.cols;
        if (geometryChanged) this._buildMapGrid(grid);
        else this._reconcileMapCells(grid);
        this.mapArea.classList.toggle('is-data-view', this.view === 'data');
        this._renderGridAxes(grid);
        this._renderLegend(grid);
        this._lastGrid = grid;
        this._layoutMap();

        if (priorSelected && priorSelected.row < grid.rows && priorSelected.col < grid.cols) {
            this.selectedCell = priorSelected;
            this._updateSelection(grid, false);
            if (hadFocus && geometryChanged) {
                const selected = this._cellAt(priorSelected.row, priorSelected.col);
                if (selected) selected.focus();
            }
        } else if (focusedCoordinates && geometryChanged
            && focusedCoordinates.row < grid.rows && focusedCoordinates.col < grid.cols) {
            this.selectedCell = focusedCoordinates;
            this._updateSelection(grid, false);
            const focused = this._cellAt(focusedCoordinates.row, focusedCoordinates.col);
            if (focused) focused.focus();
        } else {
            this.selectedCell = null;
            this.status.textContent = '';
        }
    }

    _buildMapGrid(grid) {
        this.mapArea.replaceChildren();
        this._mapStage = createElement(this.document, 'div', 'interactive-map-stage');
        this._gridFrame = createElement(this.document, 'div', 'interactive-grid-frame');
        this._gridCorner = createElement(this.document, 'span', 'interactive-grid-corner');
        this._columnAxis = createElement(this.document, 'div', 'interactive-column-axis');
        this._rowAxis = createElement(this.document, 'div', 'interactive-row-axis');
        this._gridElement = createElement(this.document, 'div', 'interactive-grid');
        this._gridElement.style.setProperty('--interactive-cols', String(grid.cols));
        this._gridElement.style.setProperty('--interactive-rows', String(grid.rows));
        grid.cells.forEach((row, rowIndex) => row.forEach((cell, colIndex) => {
            this._gridElement.append(this._makeMapCell(cell, rowIndex, colIndex));
        }));
        this._gridFrame.append(this._gridCorner, this._columnAxis, this._rowAxis, this._gridElement);
        this._mapStage.append(this._gridFrame);
        this._legendElement = createElement(this.document, 'div', 'interactive-legend');
        this._legendElement.setAttribute('aria-label', 'Map legend');
        this.mapArea.append(this._mapStage, this._legendElement);
    }

    _reconcileMapCells(grid) {
        this._gridElement.style.setProperty('--interactive-cols', String(grid.cols));
        this._gridElement.style.setProperty('--interactive-rows', String(grid.rows));
        grid.cells.forEach((row, rowIndex) => row.forEach((cell, colIndex) => {
            const button = this._cellAt(rowIndex, colIndex);
            if (button) this._updateMapCell(button, cell, rowIndex, colIndex);
        }));
    }

    _makeMapCell(cell, row, col) {
        const button = createElement(this.document, 'button', 'interactive-map-cell');
        button.type = 'button';
        button.dataset.row = String(row);
        button.dataset.col = String(col);
        button.addEventListener('click', () => this._selectCell(row, col, true));
        button.addEventListener('focus', () => this._selectCell(row, col, false));
        this._updateMapCell(button, cell, row, col, false);
        return button;
    }

    _updateMapCell(button, cell, row, col, allowFlash = true) {
        const fingerprint = nodeFingerprint(cell);
        const priorFingerprint = button.dataset.nodeFingerprint;
        const shown = this.view === 'data' ? String(cell.text) : mapCellDisplay(cell, this.mapSnapshot.symbols);
        const presentation = `${fingerprint}|${shown}`;
        if (button.dataset.presentation !== presentation) {
            button.replaceChildren();
            button.append(this.document.createTextNode(shown));
            button.setAttribute('aria-label', `Row ${row}, column ${col}: ${String(cell.text)}`);
            button.dataset.presentation = presentation;
        }
        button.dataset.nodeFingerprint = fingerprint;
        if (allowFlash && this._hasRendered && priorFingerprint !== undefined && priorFingerprint !== fingerprint) this._flash(button);
    }

    _renderGridAxes(grid) {
        const showAxes = this.showIndexes || this.view === 'data';
        this._gridFrame.classList.toggle('shows-indexes', showAxes);
        if (!showAxes) return;
        this._columnAxis.replaceChildren();
        this._rowAxis.replaceChildren();
        this._columnAxis.style.setProperty('--interactive-cols', String(grid.cols));
        this._rowAxis.style.setProperty('--interactive-rows', String(grid.rows));
        for (let col = 0; col < grid.cols; col++) {
            this._columnAxis.append(createElement(this.document, 'span', 'interactive-axis-label', String(col)));
        }
        for (let row = 0; row < grid.rows; row++) {
            this._rowAxis.append(createElement(this.document, 'span', 'interactive-axis-label', String(row)));
        }
    }

    _renderLegend(grid) {
        const legend = collectMapLegend(grid, this.mapSnapshot.symbols);
        this._legendElement.replaceChildren();
        this._legendElement.hidden = this.view === 'data' || legend.length === 0;
        for (const item of legend) {
            const entry = createElement(this.document, 'span', 'interactive-legend-entry');
            entry.append(createElement(this.document, 'span', 'interactive-legend-glyph', item.text), createElement(this.document, 'span', 'interactive-legend-value', item.value));
            this._legendElement.append(entry);
        }
    }

    _cellAt(row, col) {
        return this._gridElement && this._gridElement.querySelector(`[data-row="${row}"][data-col="${col}"]`);
    }

    _selectCell(row, col, announce) {
        if (!this._lastGrid || row >= this._lastGrid.rows || col >= this._lastGrid.cols) return;
        this.selectedCell = { row, col };
        this._updateSelection(this._lastGrid, announce);
    }

    _updateSelection(grid, announce) {
        if (!this.selectedCell) return;
        const { row, col } = this.selectedCell;
        const cell = grid.cells[row][col];
        for (const button of this._gridElement.querySelectorAll('.interactive-map-cell')) {
            const selected = Number(button.dataset.row) === row && Number(button.dataset.col) === col;
            button.classList.toggle('is-selected', selected);
            button.setAttribute('aria-pressed', String(selected));
        }
        const glyph = mapCellDisplay(cell, this.mapSnapshot.symbols);
        this.status.setAttribute('aria-live', announce ? 'polite' : 'off');
        this.status.textContent = `[${row}][${col}] = ${String(cell.text)}${glyph !== String(cell.text) ? ` (${glyph})` : ''}`;
    }

    _layoutMap() {
        if (!this._gridElement) return;
        const grid = this._lastGrid;
        const stage = this._mapStage;
        if (!grid || !stage) return;
        const width = stage.clientWidth;
        const height = stage.clientHeight;
        if (!width || !height) return;
        const hasAxes = this.showIndexes || this.view === 'data';
        const axisWidth = hasAxes ? 33 : 1;
        const axisHeight = hasAxes ? 21 : 1;
        const availableWidth = Math.max(1, width - axisWidth);
        const availableHeight = Math.max(1, height - axisHeight);
        const cellSize = Math.max(1, Math.floor(Math.min(availableWidth / grid.cols, availableHeight / grid.rows)));
        this._gridElement.style.setProperty('--interactive-cell-size', `${cellSize}px`);
        this._gridElement.style.setProperty('--interactive-glyph-size', `${Math.max(4, Math.floor(cellSize * 0.68))}px`);
        this._gridFrame.style.setProperty('--interactive-cell-size', `${cellSize}px`);
        this._gridFrame.style.setProperty('--interactive-glyph-size', `${Math.max(4, Math.floor(cellSize * 0.68))}px`);
    }

    _flash(element) {
        element.classList.remove('is-updated');
        // Force a new animation only for actual snapshots, never by reading data.
        void element.offsetWidth;
        element.classList.add('is-updated');
    }
}
