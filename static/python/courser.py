"""Small display helpers supplied by the TS-Courser interactive area.

This module is installed by the website's Pyodide runner.  It deliberately has
no browser or Pyodide imports so that the same validation can run in CPython.
"""

import json
import math


__all__ = ["display", "display_map", "define_symbol"]


_MAX_SCALAR_CELLS = 2500
_MAX_LIST_NESTING = 2
_MAX_MAP_ROWS = 100
_MAX_MAP_COLUMNS = 100
_MAX_DISPLAY_SLOTS = 20
_MAX_SYMBOL_MAPPINGS = 100
_MAX_SCALAR_STRING_LENGTH = 500
_MAX_LABEL_LENGTH = 60
_MAX_SYMBOL_LENGTH = 32

_emit = None
_enabled = True
_display_slots = set()
_symbols = {}


def _configure(emit, enabled=True):
    """Configure the website bridge and reset all per-run state.

    This is intentionally private.  The browser calls it before each student
    run; student programs should use only the names in ``__all__``.
    """
    global _emit, _enabled, _display_slots, _symbols

    if emit is not None and not callable(emit):
        raise TypeError("emit must be callable or None")
    if not isinstance(enabled, bool):
        raise TypeError("enabled must be a bool")

    _emit = emit
    _enabled = enabled
    _display_slots = set()
    _symbols = {}


def _scalar_parts(value, location):
    """Return the rendered text and a type-preserving stable key for a scalar."""
    value_type = type(value)
    if value_type is bool:
        type_name = "bool"
    elif value_type is int:
        type_name = "int"
    elif value_type is float:
        if not math.isfinite(value):
            raise ValueError("{} must be a finite float".format(location))
        type_name = "float"
    elif value_type is str:
        if len(value) > _MAX_SCALAR_STRING_LENGTH:
            raise ValueError(
                "{} string is too long (maximum {} characters)".format(
                    location, _MAX_SCALAR_STRING_LENGTH
                )
            )
        type_name = "str"
    elif value is None:
        type_name = "none"
    else:
        raise TypeError(
            "{} must be an int, finite float, str, bool, None, or list".format(
                location
            )
        )

    text = repr(value)
    return text, "{}:{}".format(type_name, text)


def _scalar_node(value, location, counter):
    text, key = _scalar_parts(value, location)
    counter[0] += 1
    if counter[0] > _MAX_SCALAR_CELLS:
        raise ValueError(
            "{} contains more than {} scalar cells".format(
                location, _MAX_SCALAR_CELLS
            )
        )
    return {"kind": "scalar", "text": text, "key": key}


def _snapshot(value, location="value"):
    """Copy a scalar/list value into a JSON-safe node without changing it."""
    counter = [0]
    active_lists = set()

    def visit(item, item_location, depth):
        if isinstance(item, list):
            if len(item) > _MAX_SCALAR_CELLS:
                raise ValueError(
                    "{} has more than {} entries".format(
                        item_location, _MAX_SCALAR_CELLS
                    )
                )
            item_id = id(item)
            if item_id in active_lists:
                raise TypeError("{} contains a circular list".format(item_location))
            if depth >= _MAX_LIST_NESTING:
                raise ValueError(
                    "{} is nested more than {} list levels".format(
                        item_location, _MAX_LIST_NESTING
                    )
                )

            active_lists.add(item_id)
            try:
                items = [
                    visit(child, "{}[{}]".format(item_location, index), depth + 1)
                    for index, child in enumerate(item)
                ]
            finally:
                active_lists.remove(item_id)
            return {"kind": "list", "items": items}

        return _scalar_node(item, item_location, counter)

    return visit(value, location, 0)


def _emit_event(event):
    if _enabled and _emit is not None:
        _emit(json.dumps(event, separators=(",", ":")))


def _validated_label(label):
    if label is None:
        return None
    if type(label) is not str:
        raise TypeError("label must be a str or None")
    if len(label) > _MAX_LABEL_LENGTH:
        raise ValueError(
            "label is too long (maximum {} characters)".format(_MAX_LABEL_LENGTH)
        )
    return label


def display(value, label=None):
    """Send a scalar or up-to-two-level list snapshot to a named display slot."""
    label = _validated_label(label)
    node = _snapshot(value, "display value")

    if label not in _display_slots:
        if len(_display_slots) >= _MAX_DISPLAY_SLOTS:
            raise ValueError(
                "at most {} independent display labels are allowed".format(
                    _MAX_DISPLAY_SLOTS
                )
            )
        _display_slots.add(label)

    _emit_event({"type": "display", "label": label, "value": node})
    return None


def define_symbol(value, symbol):
    """Map one scalar value to text in maps emitted after this call."""
    _, key = _scalar_parts(value, "symbol value")
    if type(symbol) is not str:
        raise TypeError("symbol must be a str")
    if not symbol:
        raise ValueError("symbol must not be empty")
    if len(symbol) > _MAX_SYMBOL_LENGTH:
        raise ValueError(
            "symbol is too long (maximum {} characters)".format(_MAX_SYMBOL_LENGTH)
        )

    if key not in _symbols and len(_symbols) >= _MAX_SYMBOL_MAPPINGS:
        raise ValueError(
            "at most {} symbol mappings are allowed".format(_MAX_SYMBOL_MAPPINGS)
        )
    _symbols[key] = symbol
    return None


def _map_snapshot(grid):
    if not isinstance(grid, list):
        raise TypeError("map grid must be a nonempty 2D list")
    if not grid:
        raise ValueError("map grid must contain at least one row")
    if len(grid) > _MAX_MAP_ROWS:
        raise ValueError("map grid has more than {} rows".format(_MAX_MAP_ROWS))

    expected_columns = None
    counter = [0]
    rows = []
    for row_index, row in enumerate(grid):
        location = "map grid[{}]".format(row_index)
        if not isinstance(row, list):
            raise TypeError("{} must be a list".format(location))
        if not row:
            raise ValueError("{} must not be empty".format(location))
        if len(row) > _MAX_MAP_COLUMNS:
            raise ValueError(
                "{} has more than {} columns".format(location, _MAX_MAP_COLUMNS)
            )
        if expected_columns is None:
            expected_columns = len(row)
        elif len(row) != expected_columns:
            raise ValueError("map grid must be rectangular")

        rows.append(
            {
                "kind": "list",
                "items": [
                    _scalar_node(
                        cell,
                        "{}[{}]".format(location, column_index),
                        counter,
                    )
                    for column_index, cell in enumerate(row)
                ],
            }
        )

    return {"kind": "list", "items": rows}


def display_map(grid):
    """Send a rectangular 2D-list snapshot with the current symbol mapping."""
    node = _map_snapshot(grid)
    symbols = [
        {"key": key, "text": text} for key, text in _symbols.items()
    ]
    _emit_event({"type": "map", "value": node, "symbols": symbols})
    return None
