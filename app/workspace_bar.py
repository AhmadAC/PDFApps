"""PDFApps – WorkspaceBar: top toolbar for workspace actions and navigation."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QLineEdit
)
import qtawesome as qta

from app.constants import TEXT_PRI, ACCENT, _LQ, TEXT_SEC
from app.i18n import t


class WorkspaceBar(QWidget):
    """Top bar containing sidebar toggle, breadcrumb, viewer tools, zoom and page navigation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workspace_bar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)

        def _a11y(btn, tip):
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)

        self._sidebar_toggle_btn = QPushButton()
        self._ico_bars = qta.icon("fa5s.bars", color=TEXT_PRI)
        self._ico_times = qta.icon("fa5s.times", color=TEXT_PRI)
        self._sidebar_toggle_btn.setIcon(self._ico_bars)
        self._sidebar_toggle_btn.setObjectName("viewer_nav_btn")
        self._sidebar_toggle_btn.setFixedSize(28, 28)
        _a11y(self._sidebar_toggle_btn, t("sidebar.collapse_expand"))
        layout.addWidget(self._sidebar_toggle_btn)

        self._breadcrumb = QLabel(t("workspace.title"))
        self._breadcrumb.setObjectName("workspace_title")
        layout.addWidget(self._breadcrumb, 1)

        self._open_pdf_btn = QPushButton()
        self._open_pdf_btn.setIcon(qta.icon("fa5s.folder-open", color=TEXT_PRI))
        self._open_pdf_btn.setObjectName("viewer_nav_btn")
        self._open_pdf_btn.setFixedSize(28, 28)
        _a11y(self._open_pdf_btn, t("btn.open_pdf"))
        layout.addWidget(self._open_pdf_btn)

        self._toc_top_btn = QPushButton()
        self._toc_top_btn.setIcon(qta.icon("fa5s.bookmark", color=TEXT_PRI))
        self._toc_top_btn.setObjectName("viewer_nav_btn")
        self._toc_top_btn.setFixedSize(28, 28)
        _a11y(self._toc_top_btn, t("viewer.toc"))
        self._toc_top_btn.setVisible(False)
        layout.addWidget(self._toc_top_btn)

        self._night_top_btn = QPushButton()
        self._night_top_btn.setIcon(qta.icon("fa5s.moon", color=TEXT_PRI))
        self._night_top_btn.setObjectName("viewer_nav_btn")
        self._night_top_btn.setFixedSize(28, 28)
        _a11y(self._night_top_btn, t("viewer.night_mode"))
        self._night_top_btn.setCheckable(True)
        layout.addWidget(self._night_top_btn)

        self._print_top_btn = QPushButton()
        self._print_top_btn.setIcon(qta.icon("fa5s.print", color=TEXT_PRI))
        self._print_top_btn.setObjectName("viewer_nav_btn")
        self._print_top_btn.setFixedSize(28, 28)
        _a11y(self._print_top_btn, t("viewer.print"))
        layout.addWidget(self._print_top_btn)

        self._present_btn = QPushButton()
        self._present_btn.setIcon(qta.icon("fa5s.tv", color=TEXT_PRI))
        self._present_btn.setObjectName("viewer_nav_btn")
        self._present_btn.setFixedSize(28, 28)
        _a11y(self._present_btn, t("viewer.presentation") + " (F5)")
        layout.addWidget(self._present_btn)

        self._search_top_btn = QPushButton()
        self._search_top_btn.setIcon(qta.icon("fa5s.search", color=TEXT_PRI))
        self._search_top_btn.setObjectName("viewer_nav_btn")
        self._search_top_btn.setFixedSize(28, 28)
        _a11y(self._search_top_btn, t("search.placeholder") + " (Ctrl+F)")
        layout.addWidget(self._search_top_btn)

        # Zoom widget
        self._zoom_widget = QWidget()
        zw_h = QHBoxLayout(self._zoom_widget)
        zw_h.setContentsMargins(0, 0, 0, 0)
        zw_h.setSpacing(4)

        self._zm_btn = QPushButton()
        self._zm_btn.setIcon(qta.icon("fa5s.search-minus", color=TEXT_PRI))
        self._zm_btn.setFixedSize(28, 28)
        self._zm_btn.setObjectName("viewer_nav_btn")
        _a11y(self._zm_btn, t("zoom.out"))

        self._lbl_zoom = QLabel("100%")
        self._lbl_zoom.setMinimumWidth(42)
        self._lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._zp_btn = QPushButton()
        self._zp_btn.setIcon(qta.icon("fa5s.search-plus", color=TEXT_PRI))
        self._zp_btn.setFixedSize(28, 28)
        self._zp_btn.setObjectName("viewer_nav_btn")
        _a11y(self._zp_btn, t("zoom.in"))

        self._z0_btn = QPushButton(t("zoom.reset"))
        self._z0_btn.setObjectName("viewer_nav_btn")
        self._z0_btn.setFixedHeight(28)
        _a11y(self._z0_btn, t("zoom.reset_tip"))

        zw_h.addWidget(self._zm_btn)
        zw_h.addWidget(self._lbl_zoom)
        zw_h.addWidget(self._zp_btn)
        zw_h.addWidget(self._z0_btn)
        self._zoom_widget.setVisible(False)
        layout.addWidget(self._zoom_widget)

        # Page navigation widget
        self._page_nav_widget = QWidget()
        pn_h = QHBoxLayout(self._page_nav_widget)
        pn_h.setContentsMargins(0, 0, 0, 0)
        pn_h.setSpacing(4)

        self._prev_pg_btn = QPushButton()
        self._prev_pg_btn.setIcon(qta.icon("fa5s.chevron-left", color=TEXT_PRI))
        self._prev_pg_btn.setFixedSize(28, 28)
        self._prev_pg_btn.setObjectName("viewer_nav_btn")
        _a11y(self._prev_pg_btn, t("nav.prev_page"))

        self._page_input = QLineEdit("1")
        self._page_input.setFixedWidth(40)
        self._page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_input.setObjectName("page_input")

        self._page_total_lbl = QLabel(t("nav.page_total"))
        self._page_total_lbl.setMinimumWidth(30)

        self._next_pg_btn = QPushButton()
        self._next_pg_btn.setIcon(qta.icon("fa5s.chevron-right", color=TEXT_PRI))
        self._next_pg_btn.setFixedSize(28, 28)
        self._next_pg_btn.setObjectName("viewer_nav_btn")
        _a11y(self._next_pg_btn, t("nav.next_page"))

        pn_h.addWidget(self._prev_pg_btn)
        pn_h.addWidget(self._page_input)
        pn_h.addWidget(self._page_total_lbl)
        pn_h.addWidget(self._next_pg_btn)
        self._page_nav_widget.setVisible(False)
        layout.addWidget(self._page_nav_widget)

        # Undo/redo top buttons
        self._undo_top_btn = QPushButton()
        self._undo_top_btn.setIcon(qta.icon("fa5s.undo", color=TEXT_PRI))
        self._undo_top_btn.setObjectName("viewer_nav_btn")
        self._undo_top_btn.setFixedSize(28, 28)
        _a11y(self._undo_top_btn, "Undo (Ctrl+Z)")
        self._undo_top_btn.setVisible(False)
        layout.addWidget(self._undo_top_btn)

        self._redo_top_btn = QPushButton()
        self._redo_top_btn.setIcon(qta.icon("fa5s.redo", color=TEXT_PRI))
        self._redo_top_btn.setObjectName("viewer_nav_btn")
        self._redo_top_btn.setFixedSize(28, 28)
        _a11y(self._redo_top_btn, "Redo (Ctrl+Y)")
        self._redo_top_btn.setVisible(False)
        layout.addWidget(self._redo_top_btn)

        self._help_btn = QPushButton("?")
        self._help_btn.setObjectName("theme_btn")
        _a11y(self._help_btn, t("help.tip"))
        self._help_btn.setFixedSize(28, 28)
        layout.addWidget(self._help_btn)

        _lang_labels = {"en": "EN", "pt": "PT", "es": "ES", "fr": "FR", "de": "DE", "zh": "ZH", "it": "IT", "nl": "NL"}
        from app.i18n import get_language
        self._lang_btn = QPushButton(_lang_labels.get(get_language(), "EN"))
        self._lang_btn.setObjectName("theme_btn")
        _a11y(self._lang_btn, t("lang.selector"))
        self._lang_btn.setFixedSize(28, 28)
        layout.addWidget(self._lang_btn)

        self._theme_btn = QPushButton("☀")
        self._theme_btn.setObjectName("theme_btn")
        _a11y(self._theme_btn, t("theme.toggle"))
        self._theme_btn.setFixedSize(28, 28)
        layout.addWidget(self._theme_btn)

        self._update_btn = QPushButton()
        self._update_btn.setIcon(qta.icon("fa5s.arrow-circle-up", color=ACCENT))
        self._update_btn.setObjectName("viewer_nav_btn")
        self._update_btn.setFixedSize(28, 28)
        _a11y(self._update_btn, t("update.check"))
        self._update_btn.setVisible(False)
        self._update_btn.setStyleSheet(
            f"QPushButton {{ border: 1.5px solid {ACCENT}; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: rgba(20,184,166,0.15); }}"
        )
        layout.addWidget(self._update_btn)

    def update_theme(self, dark: bool, sidebar_collapsed: bool = False):
        bar_color = TEXT_PRI if dark else _LQ
        self._ico_bars = qta.icon("fa5s.bars", color=bar_color)
        self._ico_times = qta.icon("fa5s.times", color=bar_color)
        self._sidebar_toggle_btn.setIcon(self._ico_bars if sidebar_collapsed else self._ico_times)
        self._open_pdf_btn.setIcon(qta.icon("fa5s.folder-open", color=bar_color))
        self._toc_top_btn.setIcon(qta.icon("fa5s.bookmark", color=bar_color))
        self._night_top_btn.setIcon(qta.icon("fa5s.moon", color=bar_color))
        self._print_top_btn.setIcon(qta.icon("fa5s.print", color=bar_color))
        self._present_btn.setIcon(qta.icon("fa5s.tv", color=bar_color))
        self._search_top_btn.setIcon(qta.icon("fa5s.search", color=bar_color))
        self._undo_top_btn.setIcon(qta.icon("fa5s.undo", color=bar_color))
        self._redo_top_btn.setIcon(qta.icon("fa5s.redo", color=bar_color))
        self._zm_btn.setIcon(qta.icon("fa5s.search-minus", color=bar_color))
        self._zp_btn.setIcon(qta.icon("fa5s.search-plus", color=bar_color))
        self._prev_pg_btn.setIcon(qta.icon("fa5s.chevron-left", color=bar_color))
        self._next_pg_btn.setIcon(qta.icon("fa5s.chevron-right", color=bar_color))
        self._theme_btn.setText("☀" if dark else "🌙")