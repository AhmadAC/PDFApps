# app/editor/tab_constants.py
"""PDFApps – tab_constants: mode constants, colors, and limits for TabEditar."""

_MODE_REDACT = 0
_MODE_TEXT = 1
_MODE_IMAGE = 2
_MODE_HIGHLIGHT = 3
_MODE_NOTE = 4
_MODE_FORMS = 5
_MODE_SIGNATURE = 6
_MODE_DRAW = 7
_MODE_SELECT = 8

_MAX_REDO = 100
_MAX_PENDING = 500

_HI_COLORS_KEYS = ["color.yellow", "color.green", "color.pink", "color.light_blue"]
_HI_COLORS_VALS = [(1, 1, 0), (0, 1, 0), (1, 0.4, 0.7), (0.5, 0.8, 1)]

_RED_FILLS_KEYS = ["color.black", "color.white", "color.grey"]
_RED_FILLS_VALS = [(0, 0, 0), (1, 1, 1), (0.5, 0.5, 0.5)]

_MODE_KEYS = [
    ("edit.mode.redact",    "fa5s.eraser"),
    ("edit.mode.text",      "fa5s.font"),
    ("edit.mode.image",     "fa5s.image"),
    ("edit.mode.highlight", "fa5s.highlighter"),
    ("edit.mode.note",      "fa5s.sticky-note"),
    ("edit.mode.forms",     "fa5s.clipboard-list"),
    ("edit.mode.signature", "fa5s.signature"),
    ("edit.mode.draw",      "fa5s.pencil-alt"),
    ("edit.mode.select",    "fa5s.mouse-pointer"),
]

_DRAW_COLORS_KEYS = ["color.red", "color.black", "color.blue", "color.green", "color.yellow"]
_DRAW_COLORS_VALS = [(1, 0, 0), (0, 0, 0), (0.1, 0.4, 1), (0, 0.7, 0.2), (1, 0.85, 0)]