# app\styles.py 
"""PDFApps – stylesheet strings (dark + light themes)."""

from app.constants import (
    ACCENT, ACCENT_H, ACCENT_P,
    BG_BASE, BG_SIDE, BG_CARD, BG_INPUT, BG_INNER,
    BORDER, TEXT_PRI, TEXT_SEC,
    _LA, _LAH, _LAP, _LB, _LS, _LC, _LI, _LN, _LO, _LP, _LQ,
)

STYLE = f"""
/* ── Globals ─────────────────────────────────────────────────────────── */
QMainWindow {{ background: {BG_BASE}; }}
#central_widget {{ background: {BG_BASE}; }}
QWidget     {{ background: transparent; color: {TEXT_PRI};
              font-family: "Segoe UI Variable Text", "Segoe UI", Arial, sans-serif; font-size: 11pt; }}
QDialog     {{ background: {BG_CARD}; color: {TEXT_PRI}; }}
QMenu       {{ background: #262626; color: {TEXT_PRI}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 4px; margin: 2px 4px; background: transparent; }}
QMenu::item:selected {{ background: {ACCENT}; color: #FFFFFF; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
QMessageBox {{ background: {BG_CARD}; color: {TEXT_PRI}; }}
QToolTip    {{ background: #262626; color: {TEXT_PRI}; border: 1px solid {BORDER}; border-radius: 4px; padding: 4px 6px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ── Sidebar ─────────────────────────────────────────────────────────── */
#sidebar    {{ background: {BG_SIDE}; border-right: 1px solid {BORDER}; }}
#sidebar QScrollBar:vertical, #sidebar QScrollBar:horizontal {{
    width: 0px; height: 0px; max-width: 0px; max-height: 0px;
    background: transparent; border: none;
}}
#brand_area {{ background: {BG_SIDE}; padding: 0; }}

#app_title {{ font-size: 14pt; font-weight: 700; color: #FFFFFF;
             background: transparent; padding: 0; }}
#app_sub   {{ font-size: 9.5pt; color: {TEXT_SEC};
             background: transparent; padding: 0; }}

#nav_sep   {{ background: {BORDER}; max-height: 1px; margin: 4px 12px 8px 12px; }}
#nav_group_sep {{ background: {BORDER}; max-height: 1px; margin: 0 8px 0 4px; }}

#nav_search {{ background: #1E1E1E; border: 1px solid {BORDER}; border-radius: 6px;
              color: {TEXT_PRI}; padding: 6px 10px; margin: 4px 12px 4px 12px; font-size: 10pt; }}
#nav_search:focus {{ border: 1px solid {ACCENT}; }}

#nav_list  {{ background: transparent; border: none; outline: none;
             color: #CCCCCC; font-size: 11pt; }}
#nav_list QScrollBar:vertical, #nav_list QScrollBar:horizontal {{
    width: 0px; height: 0px; max-width: 0px; max-height: 0px;
    background: transparent; border: none;
}}
#nav_list::item          {{ padding: 9px 12px; margin: 2px 8px; border-radius: 6px; }}
#nav_list::item:hover    {{ background: #333333; color: #FFFFFF; }}
#nav_list::item:selected {{ background: #264F78; border: 1px solid {ACCENT};
                           color: #FFFFFF; font-weight: 600; }}

#sidebar_footer {{ background: transparent; color: #888888;
                  font-size: 9pt; padding: 10px 16px; }}

#workspace_bar {{ background: {BG_SIDE}; border-bottom: 1px solid {BORDER}; }}
#workspace_title {{ font-size: 11pt; font-weight: 700; color: #FFFFFF; background: transparent; }}
#workspace_hint  {{ font-size: 9pt; color: {TEXT_SEC}; background: transparent; }}
#workspace_badge {{
    background: #264F78; border: 1px solid {ACCENT}; color: #FFFFFF;
    border-radius: 10px; padding: 4px 10px; font-size: 9pt; font-weight: 600;
}}
#quick_btn {{
    background: #333333; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 6px 14px; min-height: 30px; font-size: 10pt; font-weight: 600; color: #FFFFFF;
}}
#quick_btn:hover   {{ background: #3C3F41; border-color: {ACCENT}; }}
#quick_btn:pressed {{ background: {ACCENT}; }}
#workspace_shell {{ background: {BG_BASE}; }}

/* ── Tool header ─────────────────────────────────────────────────────── */
#tool_header  {{ background: {BG_CARD}; border-bottom: 1px solid {BORDER};
                min-height: 68px; padding: 0 24px; }}
#th_icon      {{ background: #333333; border: 1px solid {BORDER}; border-radius: 8px; padding: 0; }}
#th_title     {{ font-size: 14pt; font-weight: 700; background: transparent;
                color: #FFFFFF; }}
#th_desc      {{ font-size: 10.5pt; background: transparent; color: {TEXT_SEC}; }}

/* ── Scroll inner ────────────────────────────────────────────────────── */
#scroll_inner {{ background: {BG_INNER}; }}

/* ── Action bar ──────────────────────────────────────────────────────── */
#action_bar   {{ background: {BG_CARD}; border-top: 1px solid {BORDER}; }}

/* ── Primary button ──────────────────────────────────────────────────── */
#btn_primary {{
    background: {ACCENT}; color: #FFFFFF; border: 1px solid #005A9E;
    border-radius: 6px; font-size: 11pt; font-weight: 700;
    padding: 10px 24px; min-height: 40px;
}}
#btn_primary:hover   {{ background: {ACCENT_H}; }}
#btn_primary:pressed {{ background: {ACCENT_P}; }}
#btn_primary:disabled {{ background: #3A3D40; border-color: #4A4D50; color: #777777; }}

/* ── Secondary buttons ───────────────────────────────────────────────── */
QPushButton {{
    background: #3C3F41; border: 1px solid #555555;
    border-radius: 6px; padding: 6px 14px; color: {TEXT_PRI}; font-size: 10.5pt;
}}
QPushButton:hover   {{ background: #4F5254; border-color: {ACCENT}; color: #FFFFFF; }}
QPushButton:pressed {{ background: {ACCENT}; color: #FFFFFF; }}

#btn_danger {{
    background: #4A1D1D; color: #FCA5A5; font-size: 10.5pt;
    border: 1px solid #7F1D1D; border-radius: 6px; padding: 6px 14px;
}}
#btn_danger:hover {{ background: #5C2323; color: #FFFFFF; border-color: #B91C1C; }}

/* ── Section labels ──────────────────────────────────────────────────── */
#section_lbl {{
    font-size: 9pt; font-weight: 700; color: {TEXT_SEC};
    background: transparent; padding: 12px 0 4px 0;
    letter-spacing: 1px;
}}

/* ── Cards (GroupBox) ────────────────────────────────────────────────── */
QGroupBox {{
    background: {BG_CARD}; border: 1px solid {BORDER};
    border-radius: 8px; margin-top: 20px;
    padding: 16px 14px 12px 14px;
    font-size: 10pt; font-weight: 600; color: #CCCCCC;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 2px 8px; left: 14px; top: -1px;
    background: {BG_CARD}; color: {TEXT_PRI};
}}
QGroupBox QWidget  {{ background: transparent; }}
QGroupBox QLabel   {{ background: transparent; }}
QGroupBox QLineEdit, QGroupBox QSpinBox,
QGroupBox QComboBox {{ background: {BG_INPUT}; }}

/* ── Inputs ──────────────────────────────────────────────────────────── */
QLineEdit, QSpinBox, QComboBox {{
    background: {BG_INPUT}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 6px 10px; color: {TEXT_PRI};
    font-size: 10.5pt; min-height: 22px;
}}
QLineEdit:focus, QSpinBox:focus {{
    border: 1px solid {ACCENT}; background: #262626;
}}
QPushButton:focus, QComboBox:focus {{
    border: 2px solid {ACCENT};
}}
QLineEdit[readOnly="true"] {{ background: #242424; color: {TEXT_SEC}; }}

QComboBox::drop-down       {{ border: none; width: 26px; }}
QComboBox::down-arrow      {{ width: 11px; }}
QComboBox QAbstractItemView {{
    background: #2B2B2B; border: 1px solid {BORDER};
    border-radius: 6px; color: {TEXT_PRI}; font-size: 10.5pt;
    selection-background-color: {ACCENT}; selection-color: white;
}}

QTextEdit {{
    background: #1E1E1E; border: 1px solid {BORDER};
    border-radius: 6px; padding: 10px; color: {TEXT_PRI}; font-size: 10.5pt;
}}

/* ── Drop zone ───────────────────────────────────────────────────────── */
#drop_zone {{
    background: {BG_CARD}; border: 1px dashed {BORDER};
    border-radius: 8px; min-height: 60px;
}}
#drop_zone[drag_active="true"] {{
    background: #1E293B; border: 1px dashed {ACCENT};
}}
#drop_icon {{ background: transparent; border: none; padding: 0; min-width: 0; }}
#drop_zone_lbl {{ font-size: 10.5pt; color: {TEXT_SEC}; background: transparent; }}
#drop_zone_lbl[has_file="true"] {{ color: #FFFFFF; font-weight: 600; }}
#drop_clear {{
    background: transparent; border: none; color: {TEXT_SEC};
    font-size: 13pt; padding: 0 4px; min-width: 0;
}}
#drop_clear:hover {{ color: #EF4444; border: none; }}

/* ── Lists & Tables ──────────────────────────────────────────────────── */
QListWidget, QTableWidget {{
    background: #1E1E1E; border: 1px solid {BORDER};
    border-radius: 6px; outline: none; font-size: 10.5pt;
    alternate-background-color: #242424; color: {TEXT_PRI};
}}
QListWidget::item          {{ padding: 8px 12px; margin: 0; border-radius: 4px; }}
QListWidget::item:selected {{ background: {ACCENT}; color: #FFFFFF; }}
QListWidget::item:hover:!selected {{ background: #2E2E2E; }}
QTableWidget::item:selected {{ background: {ACCENT}; color: #FFFFFF; }}
QHeaderView::section {{
    background: #2B2B2B; border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 10px; font-weight: 700;
    color: {TEXT_SEC}; font-size: 9.5pt;
}}
QTableWidget {{ gridline-color: {BORDER}; }}

/* ── Scrollbars ──────────────────────────────────────────────────────── */
QScrollBar:vertical   {{ width: 8px; background: transparent; margin: 0; border: none; }}
QScrollBar:horizontal {{ height: 8px; background: transparent; margin: 0; border: none; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: #555555; border-radius: 4px; min-height: 20px;
}}
QScrollBar::handle:vertical:hover,
QScrollBar::handle:horizontal:hover {{ background: #6A6D70; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* -- Mode buttons (checkable) -----------------------------------------------*/
QPushButton:checkable {{ background: #333333; border: 1px solid #444444;
    border-radius: 6px; padding: 6px 8px; text-align: left; font-size: 10pt; color: #CCCCCC; }}
QPushButton:checkable:hover   {{ background: #3C3F41; border-color: {ACCENT}; color: #FFFFFF; }}
QPushButton:checkable:checked {{ background: #264F78; border: 1px solid {ACCENT}; color: #FFFFFF; font-weight: 600; }}
QPushButton:checkable:pressed {{ background: {ACCENT}; color: #FFFFFF; }}

/* ── Info label ──────────────────────────────────────────────────────── */
#info_lbl {{ color: {TEXT_SEC}; font-size: 9.5pt; background: transparent;
            padding: 2px 4px; }}

/* ── Status bar ──────────────────────────────────────────────────────── */
QStatusBar {{ background: {BG_SIDE}; border-top: 1px solid {BORDER};
             color: {TEXT_SEC}; font-size: 9.5pt; padding: 4px 14px; }}

/* ── TOC tree (PDF bookmarks panel) ──────────────────────────────────── */
#toc_tree {{ background: {BG_SIDE}; border: none; border-right: 1px solid {BORDER};
            color: {TEXT_PRI}; font-size: 10pt; outline: 0; padding: 4px; }}
#toc_tree::item {{ padding: 4px 6px; border: none; }}
#toc_tree::item:hover {{ background: #333333; }}
#toc_tree::item:selected {{ background: {ACCENT}; color: white; }}

/* ── PDF Viewer panel ────────────────────────────────────────────────── */
#viewer_panel  {{ background: {BG_INNER}; border-left: 1px solid {BORDER}; }}
#viewer_header {{ background: {BG_CARD}; border-bottom: 1px solid {BORDER}; }}
#viewer_title  {{ font-size: 10.5pt; font-weight: 600; color: #FFFFFF;
                 background: transparent; }}
#viewer_page_lbl {{ font-size: 10pt; color: {TEXT_SEC}; background: transparent;
                   min-width: 54px; }}
#viewer_nav_btn  {{ background: #333333; border: 1px solid #555555;
                   border-radius: 6px; color: {TEXT_PRI};
                   min-width: 30px; min-height: 30px; padding: 0; }}
#viewer_nav_btn:hover   {{ background: #4F5254; border-color: {ACCENT}; color: #FFFFFF; }}
#viewer_nav_btn:pressed {{ background: {ACCENT}; color: #FFFFFF; }}
#viewer_nav_btn:disabled {{ background: #242424; border-color: #333333; color: #555555; }}
#page_input {{ background: #1E1E1E; border: 1px solid {BORDER}; border-radius: 4px;
               color: {TEXT_PRI}; font-size: 10pt; padding: 2px; }}
#viewer_placeholder {{ font-size: 12pt; color: {TEXT_SEC}; background: {BG_INNER}; }}
#viewer_sel_status  {{ font-size: 9pt; color: {TEXT_SEC}; background: {BG_CARD};
                       border-top: 1px solid {BORDER}; padding: 4px 8px; }}
QPdfView {{ background: {BG_INNER}; border: none; }}
QSplitter::handle {{ background: {BORDER}; width: 1px; }}

#theme_btn {{
    background: #333333; border: 1px solid #555555; border-radius: 14px;
    font-size: 12pt; padding: 0; min-width: 28px; max-width: 28px; color: {TEXT_PRI};
}}
#theme_btn:hover {{ background: #4F5254; border-color: {ACCENT}; }}

#viewer_tabs {{
    background: {BG_CARD}; border: none; border-bottom: 1px solid {BORDER};
}}
#viewer_tabs::tab {{
    background: {BG_CARD}; color: {TEXT_SEC}; border: none;
    padding: 6px 14px; margin-right: 1px; border-bottom: 2px solid transparent;
}}
#viewer_tabs::tab:selected {{
    color: #FFFFFF; background: #1E1E1E; border-bottom: 2px solid {ACCENT};
}}
#viewer_tabs::tab:hover:!selected {{ color: #FFFFFF; background: #333333; }}

#new_tab_btn {{
    background: {BG_CARD}; border: none; border-bottom: 1px solid {BORDER};
    color: {TEXT_SEC}; font-size: 14pt; font-weight: bold; padding: 0;
}}
#new_tab_btn:hover {{ color: #FFFFFF; background: #333333; }}
"""

STYLE_LIGHT = f"""
QMainWindow {{ background: #CBD5E1; }}
#central_widget {{ background: #CBD5E1; }}
QWidget     {{ background: transparent; color: {_LP};
              font-family: "Segoe UI Variable Text", "Segoe UI", Arial, sans-serif; font-size: 11pt; }}
QDialog     {{ background: {_LC}; color: {_LP}; }}
QMenu       {{ background: {_LC}; color: {_LP}; border: 1px solid {_LO}; border-radius: 6px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 4px; margin: 2px 4px; background: transparent; }}
QMenu::item:selected {{ background: {_LA}; color: #FFFFFF; }}
QMenu::separator {{ height: 1px; background: {_LO}; margin: 4px 6px; }}
QMessageBox {{ background: {_LC}; color: {_LP}; }}
QToolTip    {{ background: {_LC}; color: {_LP}; border: 1px solid {_LO}; border-radius: 4px; padding: 4px 6px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

#sidebar    {{ background: {_LS}; border-right: 1px solid {_LO}; }}
#sidebar QScrollBar:vertical, #sidebar QScrollBar:horizontal {{
    width: 0px; height: 0px; max-width: 0px; max-height: 0px;
    background: transparent; border: none;
}}
#brand_area {{ background: {_LS}; padding: 0; }}
#app_title  {{ font-size: 14pt; font-weight: 700; color: {_LP};
              background: transparent; padding: 0; }}
#app_sub    {{ font-size: 9.5pt; color: {_LQ};
              background: transparent; padding: 0; }}
#nav_sep    {{ background: {_LO}; max-height: 1px; margin: 4px 12px 8px 12px; }}
#nav_group_sep {{ background: {_LO}; max-height: 1px; margin: 0 8px 0 4px; }}
#nav_search {{ background: #FFFFFF; border: 1px solid {_LO}; border-radius: 6px;
              color: {_LP}; padding: 6px 10px; margin: 4px 12px 4px 12px; font-size: 10pt; }}
#nav_search:focus {{ border: 1px solid {_LA}; }}
#nav_list   {{ background: transparent; border: none; outline: none;
              color: {_LQ}; font-size: 11pt; }}
#nav_list QScrollBar:vertical, #nav_list QScrollBar:horizontal {{
    width: 0px; height: 0px; max-width: 0px; max-height: 0px;
    background: transparent; border: none;
}}
#nav_list::item          {{ padding: 9px 12px; margin: 2px 8px; border-radius: 6px; }}
#nav_list::item:hover    {{ background: #E0E7FF; color: {_LP}; }}
#nav_list::item:selected {{ background: #D6E8FA; border: 1px solid #70A7DB;
                           color: {_LA}; font-weight: 700; }}
#sidebar_footer {{ background: transparent; color: {_LQ};
                  font-size: 9pt; padding: 10px 16px; }}

#workspace_bar {{ background: #E8EEF1; border-bottom: 1px solid #CBD5E1; }}
#workspace_title {{ font-size: 11pt; font-weight: 700; color: #1E293B; background: transparent; }}
#workspace_hint  {{ font-size: 9pt; color: #64748B; background: transparent; }}
#workspace_badge {{
    background: #D6E8FA; border: 1px solid #70A7DB; color: {_LA};
    border-radius: 10px; padding: 4px 10px; font-size: 9pt; font-weight: 600;
}}
#quick_btn {{
    background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 6px;
    padding: 6px 14px; min-height: 30px; font-size: 10pt; font-weight: 600; color: {_LP};
}}
#quick_btn:hover   {{ background: #E2E8F0; border-color: #94A3B8; }}
#quick_btn:pressed {{ background: #CBD5E1; }}
#workspace_shell {{ background: #CBD5E1; }}

#tool_header  {{ background: {_LC}; border-bottom: 1px solid {_LO};
                min-height: 68px; padding: 0 24px; }}
#th_icon      {{ background: #EEF4FB; border: 1px solid {_LO}; border-radius: 8px; padding: 0; }}
#th_title     {{ font-size: 14pt; font-weight: 700; background: transparent; color: {_LP}; }}
#th_desc      {{ font-size: 10.5pt; background: transparent; color: {_LQ}; }}

#scroll_inner {{ background: {_LN}; }}
#action_bar   {{ background: {_LC}; border-top: 1px solid {_LO}; }}

#btn_primary {{
    background: {_LA}; color: #FFFFFF; border: none;
    border-radius: 6px; font-size: 11pt; font-weight: 700;
    padding: 10px 24px; min-height: 40px;
}}
#btn_primary:hover   {{ background: {_LAH}; }}
#btn_primary:pressed {{ background: {_LAP}; }}
#btn_primary:disabled {{ background: #CBD5E1; color: #94A3B8; }}

QPushButton {{
    background: {_LC}; border: 1px solid {_LO};
    border-radius: 6px; padding: 6px 14px; color: {_LP}; font-size: 10.5pt;
}}
QPushButton:hover   {{ background: #E0E7FF; border-color: {_LA}; color: {_LP}; }}
QPushButton:pressed {{ background: #C7D8F2; }}

#btn_danger {{
    background: #FEF2F2; color: #DC2626; font-size: 10.5pt;
    border: 1px solid #FECACA; border-radius: 6px; padding: 6px 14px;
}}
#btn_danger:hover {{ background: #FEE2E2; color: #B91C1C; border-color: #FCA5A5; }}

#section_lbl {{
    font-size: 9pt; font-weight: 700; color: {_LQ};
    background: transparent; padding: 12px 0 4px 0; letter-spacing: 1px;
}}

QGroupBox {{
    background: {_LC}; border: 1px solid {_LO};
    border-radius: 8px; margin-top: 20px; padding: 16px 14px 12px 14px;
    font-size: 10pt; font-weight: 600; color: {_LQ};
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 2px 8px; left: 14px; top: -1px;
    background: {_LC}; color: {_LP};
}}
QGroupBox QWidget  {{ background: transparent; }}
QGroupBox QLabel   {{ background: transparent; }}
QGroupBox QLineEdit, QGroupBox QSpinBox,
QGroupBox QComboBox {{ background: {_LI}; }}

QLineEdit, QSpinBox, QComboBox {{
    background: {_LI}; border: 1px solid {_LO};
    border-radius: 6px; padding: 6px 10px; color: {_LP};
    font-size: 10.5pt; min-height: 22px;
}}
QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {_LA}; background: #FFFFFF; }}
QPushButton:focus, QComboBox:focus {{ border: 2px solid {_LA}; }}
QLineEdit[readOnly="true"] {{ background: #EEEEEE; color: {_LQ}; }}

QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ width: 11px; }}
QComboBox QAbstractItemView {{
    background: {_LC}; border: 1px solid {_LO};
    border-radius: 6px; color: {_LP}; font-size: 10.5pt;
    selection-background-color: {_LA}; selection-color: white;
}}

QTextEdit {{
    background: {_LC}; border: 1px solid {_LO};
    border-radius: 6px; padding: 10px; color: {_LP}; font-size: 10.5pt;
}}

#drop_zone {{
    background: {_LC}; border: 1px dashed {_LO};
    border-radius: 8px; min-height: 60px;
}}
#drop_zone[drag_active="true"] {{ background: #EBF2FF; border: 1px dashed {_LA}; }}
#drop_icon {{ background: transparent; border: none; padding: 0; min-width: 0; }}
#drop_zone_lbl {{ font-size: 10.5pt; color: {_LQ}; background: transparent; }}
#drop_zone_lbl[has_file="true"] {{ color: {_LP}; font-weight: 600; }}
#drop_clear {{
    background: transparent; border: none; color: {_LQ};
    font-size: 13pt; padding: 0 4px; min-width: 0;
}}
#drop_clear:hover {{ color: #DC2626; border: none; }}

QListWidget, QTableWidget {{
    background: {_LC}; border: 1px solid {_LO};
    border-radius: 6px; outline: none; font-size: 10.5pt;
    alternate-background-color: {_LN}; color: {_LP};
}}
QListWidget::item          {{ padding: 8px 12px; margin: 0; border-radius: 4px; }}
QListWidget::item:selected {{ background: {_LA}; color: #FFFFFF; }}
QListWidget::item:hover    {{ background: #DDE6F0; }}
QTableWidget::item:selected {{ background: {_LA}; color: #FFFFFF; }}
QHeaderView::section {{
    background: {_LC}; border: none; border-bottom: 1px solid {_LO};
    padding: 6px 10px; font-weight: 700; color: {_LQ}; font-size: 9.5pt;
}}
QTableWidget {{ gridline-color: {_LO}; }}

QScrollBar:vertical   {{ width: 8px; background: transparent; margin: 0; border: none; }}
QScrollBar:horizontal {{ height: 8px; background: transparent; margin: 0; border: none; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {_LO}; border-radius: 4px; min-height: 20px;
}}
QScrollBar::handle:vertical:hover,
QScrollBar::handle:horizontal:hover {{ background: #94A3B8; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

#info_lbl {{ color: {_LQ}; font-size: 9.5pt; background: transparent; padding: 2px 4px; }}

QStatusBar {{ background: {_LS}; border-top: 1px solid {_LO};
             color: {_LQ}; font-size: 9.5pt; padding: 4px 14px; }}

#toc_tree {{ background: {_LS}; border: none; border-right: 1px solid {_LO};
            color: {_LP}; font-size: 10pt; outline: 0; padding: 4px; }}
#toc_tree::item {{ padding: 4px 6px; border: none; }}
#toc_tree::item:hover {{ background: #E0E7FF; }}
#toc_tree::item:selected {{ background: {_LA}; color: white; }}

#viewer_panel  {{ background: {_LN}; border-left: 1px solid {_LO}; }}
#viewer_header {{ background: {_LC}; border-bottom: 1px solid {_LO}; }}
#viewer_title  {{ font-size: 10.5pt; font-weight: 600; color: {_LP}; background: transparent; }}
#viewer_page_lbl {{ font-size: 10pt; color: {_LQ}; background: transparent; min-width: 54px; }}

#viewer_nav_btn  {{ background: #FFFFFF; border: 1px solid #CBD5E1;
                   border-radius: 6px; color: {_LP};
                   min-width: 30px; min-height: 30px; padding: 0; }}
#viewer_nav_btn:hover   {{ background: #E2E8F0; border-color: {_LA}; color: {_LP}; }}
#viewer_nav_btn:pressed {{ background: #CBD5E1; }}
#viewer_nav_btn:disabled {{ background: {_LN}; border-color: {_LO}; color: {_LO}; }}
#page_input {{ background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 4px;
               color: {_LP}; font-size: 10pt; padding: 2px; }}

#viewer_placeholder {{ font-size: 12pt; color: {_LQ}; background: {_LN}; }}
#viewer_sel_status  {{ font-size: 9pt; color: {_LQ}; background: {_LC};
                       border-top: 1px solid {_LO}; padding: 4px 8px; }}
QPdfView {{ background: {_LN}; border: none; }}
QSplitter::handle {{ background: {_LO}; width: 1px; }}

#theme_btn {{
    background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 14px; font-size: 12pt;
    padding: 0; min-width: 28px; max-width: 28px; color: {_LP};
}}
#theme_btn:hover {{ background: #E2E8F0; border-color: {_LA}; }}

#viewer_tabs {{
    background: {_LC}; border: none; border-bottom: 1px solid {_LO};
}}
#viewer_tabs::tab {{
    background: {_LC}; color: {_LQ}; border: none;
    padding: 6px 14px; margin-right: 1px; border-bottom: 2px solid transparent;
}}
#viewer_tabs::tab:selected {{
    color: {_LP}; background: #FFFFFF; border-bottom: 2px solid {_LA};
}}
#viewer_tabs::tab:hover:!selected {{ color: {_LP}; background: #E0E7FF; }}

#new_tab_btn {{
    background: {_LC}; border: none; border-bottom: 1px solid {_LO};
    color: {_LQ}; font-size: 14pt; font-weight: bold; padding: 0;
}}
#new_tab_btn:hover {{ color: {_LP}; background: #E0E7FF; }}
"""