"""PDFApps – design system constants (colours / theme)."""

import os as _os
DESKTOP = _os.path.join(_os.path.expanduser("~"), "Desktop")

APP_VERSION = "1.15.0"
GITHUB_REPO = "nelsonduarte/PDFApps"

# PyperPoint Dark Theme Palette
ACCENT   = "#0078D4"   # PyperPoint / Fluent blue
ACCENT_H = "#106EBE"   # hover blue
ACCENT_P = "#005A9E"   # pressed blue
BG_BASE  = "#1E1E1E"   # global window background
BG_SIDE  = "#252525"   # sidebar background
BG_CARD  = "#2B2B2B"   # cards / tool header / panel surfaces
BG_INPUT = "#1E1E1E"   # inputs and edit areas
BG_INNER = "#1E1E1E"   # scroll area canvas background
BORDER   = "#444444"   # subtle dark borders
TEXT_PRI = "#F0F0F0"   # primary white/light text
TEXT_SEC = "#A0A0A0"   # secondary neutral grey text

# Status colors
SUCCESS_DARK  = "#10B981"   # vibrant green for dark mode
SUCCESS_LIGHT = "#059669"   # deeper green for light mode

# ── Light theme ────────────────────────────────────────────────────────────────
_LA  = "#0078D4"
_LAH = "#106EBE"
_LAP = "#005A9E"
_LB  = "#F4F7F6"
_LS  = "#E9EFEC"
_LC  = "#FFFFFF"
_LI  = "#FFFFFF"
_LN  = "#F2F4F7"
_LO  = "#D1D5DB"
_LP  = "#1A2B28"
_LQ  = "#555555"