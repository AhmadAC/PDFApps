"""PDFApps – WorkspaceBar: top toolbar for workspace actions and navigation."""
from PySide6.QtCore import Qt, QSize, QByteArray, QRectF
from PySide6.QtGui import QIcon, QPainter, QPixmap, QColor, QPen, QFont, QLinearGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QLineEdit
)
import qtawesome as qta

from app.constants import TEXT_PRI, ACCENT, _LP
from app.i18n import t
from app.utils import _paint_bg


def get_reset_zoom_icon(size: int = 18, color: str | None = None) -> QIcon:
    """Return an icon containing the modern vibrant SVG with 100% in the middle."""
    svg_xml = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="100%" height="100%">
  <defs>
    <!-- Modern vibrant gradient (easily customizable) -->
    <linearGradient id="resetGradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#06B6D4" />
      <stop offset="100%" stop-color="#10B981" />
    </linearGradient>
  </defs>

  <!-- Background Track Ring (Muted) -->
  <circle
    cx="100"
    cy="100"
    r="64"
    fill="none"
    stroke="url(#resetGradient)"
    stroke-width="7"
    stroke-opacity="0.15"
  />

  <!-- Active Counter-Clockwise Reset Arc (~310°) -->
  <path
    d="M 51 59 A 64 64 0 1 0 94 36"
    fill="none"
    stroke="url(#resetGradient)"
    stroke-width="7"
    stroke-linecap="round"
  />

  <!-- Sleek Arrowhead at Arc Termination -->
  <polygon
    points="72,36 93,23 93,49"
    fill="url(#resetGradient)"
    stroke="url(#resetGradient)"
    stroke-width="2"
    stroke-linejoin="round"
  />

  <!-- Centered "100%" Text -->
  <text
    x="100"
    y="101"
    text-anchor="middle"
    dominant-baseline="central"
    fill="url(#resetGradient)"
    font-family="system-ui, -apple-system, 'Segoe UI', Roboto, Inter, sans-serif"
    font-size="34"
    font-weight="700"
    letter-spacing="-1px"
  >100%</text>
</svg>"""
    try:
        renderer = QSvgRenderer(QByteArray(svg_xml.encode("utf-8")))
        if renderer.isValid():
            dpr = 2.0
            pix = QPixmap(int(size * dpr), int(size * dpr))
            pix.fill(Qt.GlobalColor.transparent)
            pix.setDevicePixelRatio(dpr)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            renderer.render(p, QRectF(0, 0, size, size))
            p.end()
            return QIcon(pix)
    except Exception:
        pass

    try:
        dpr = 2.0
        pix = QPixmap(int(size * dpr), int(size * dpr))
        pix.fill(Qt.GlobalColor.transparent)
        pix.setDevicePixelRatio(dpr)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        grad = QLinearGradient(0, 0, size, size)
        grad.setColorAt(0.0, QColor("#06B6D4"))
        grad.setColorAt(1.0, QColor("#10B981"))

        track_col = QColor("#06B6D4")
        track_col.setAlpha(40)
        p.setPen(QPen(track_col, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = size / 2.0, size / 2.0
        r = size * 0.36
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        pen_arc = QPen(grad, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen_arc)
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), int(55 * 16), int(310 * 16))

        font = QFont("Segoe UI", int(size * 0.28), QFont.Weight.Bold)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QPen(QColor("#10B981")))
        p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "100%")
        p.end()
        return QIcon(pix)
    except Exception:
        return QIcon()


class WorkspaceBar(QWidget):
    """Top bar containing sidebar toggle, breadcrumb, viewer tools, zoom and page navigation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workspace_bar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(8)

        def _a11y(btn, tip):
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)

        # ── Left Side: App Sidebar Toggle & Pages Sidebar Toggle ──────
        self._sidebar_toggle_btn = QPushButton()
        self._ico_bars = qta.icon("fa5s.bars", color=TEXT_PRI)
        self._sidebar_toggle_btn.setIcon(self._ico_bars)
        self._sidebar_toggle_btn.setObjectName("viewer_nav_btn")
        self._sidebar_toggle_btn.setFixedSize(28, 28)
        self._sidebar_toggle_btn.setIconSize(QSize(16, 16))
        _a11y(self._sidebar_toggle_btn, t("sidebar.collapse_expand"))
        layout.addWidget(self._sidebar_toggle_btn)

        # Pages / Thumbnails sidebar toggle button with thumbnail grid icon
        self._pages_toggle_btn = QPushButton()
        self._ico_pages = qta.icon("fa5s.th-large", color=TEXT_PRI)
        self._pages_toggle_btn.setIcon(self._ico_pages)
        self._pages_toggle_btn.setObjectName("viewer_nav_btn")
        self._pages_toggle_btn.setFixedSize(28, 28)
        self._pages_toggle_btn.setIconSize(QSize(16, 16))
        _a11y(self._pages_toggle_btn, t("viewer.sidebar.pages"))
        layout.addWidget(self._pages_toggle_btn)

        self._breadcrumb = QLabel(t("workspace.title"))
        self._breadcrumb.setObjectName("workspace_title")
        layout.addWidget(self._breadcrumb, 1)

        # ── Viewer Action Buttons ─────────────────────────────────────
        self._open_pdf_btn = QPushButton()
        self._open_pdf_btn.setIcon(qta.icon("fa5s.folder-open", color=TEXT_PRI))
        self._open_pdf_btn.setObjectName("viewer_nav_btn")
        self._open_pdf_btn.setFixedSize(28, 28)
        self._open_pdf_btn.setIconSize(QSize(16, 16))
        _a11y(self._open_pdf_btn, t("btn.open_pdf"))
        layout.addWidget(self._open_pdf_btn)

        self._toc_top_btn = QPushButton()
        self._toc_top_btn.setIcon(qta.icon("fa5s.bookmark", color=TEXT_PRI))
        self._toc_top_btn.setObjectName("viewer_nav_btn")
        self._toc_top_btn.setFixedSize(28, 28)
        self._toc_top_btn.setIconSize(QSize(16, 16))
        _a11y(self._toc_top_btn, t("viewer.toc"))
        self._toc_top_btn.setVisible(False)
        layout.addWidget(self._toc_top_btn)

        self._night_top_btn = QPushButton()
        self._night_top_btn.setIcon(qta.icon("fa5s.moon", color=TEXT_PRI))
        self._night_top_btn.setObjectName("viewer_nav_btn")
        self._night_top_btn.setFixedSize(28, 28)
        self._night_top_btn.setIconSize(QSize(16, 16))
        _a11y(self._night_top_btn, t("viewer.night_mode"))
        self._night_top_btn.setCheckable(True)
        layout.addWidget(self._night_top_btn)

        self._print_top_btn = QPushButton()
        self._print_top_btn.setIcon(qta.icon("fa5s.print", color=TEXT_PRI))
        self._print_top_btn.setObjectName("viewer_nav_btn")
        self._print_top_btn.setFixedSize(28, 28)
        self._print_top_btn.setIconSize(QSize(16, 16))
        _a11y(self._print_top_btn, t("viewer.print"))
        layout.addWidget(self._print_top_btn)

        self._present_btn = QPushButton()
        self._present_btn.setIcon(qta.icon("fa5s.tv", color=TEXT_PRI))
        self._present_btn.setObjectName("viewer_nav_btn")
        self._present_btn.setFixedSize(28, 28)
        self._present_btn.setIconSize(QSize(16, 16))
        _a11y(self._present_btn, t("viewer.presentation") + " (F5)")
        layout.addWidget(self._present_btn)

        self._search_top_btn = QPushButton()
        self._search_top_btn.setIcon(qta.icon("fa5s.search", color=TEXT_PRI))
        self._search_top_btn.setObjectName("viewer_nav_btn")
        self._search_top_btn.setFixedSize(28, 28)
        self._search_top_btn.setIconSize(QSize(16, 16))
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
        self._zm_btn.setIconSize(QSize(16, 16))
        self._zm_btn.setObjectName("viewer_nav_btn")
        _a11y(self._zm_btn, t("zoom.out"))

        self._lbl_zoom = QLabel("100%")
        self._lbl_zoom.setMinimumWidth(42)
        self._lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._zp_btn = QPushButton()
        self._zp_btn.setIcon(qta.icon("fa5s.search-plus", color=TEXT_PRI))
        self._zp_btn.setFixedSize(28, 28)
        self._zp_btn.setIconSize(QSize(16, 16))
        self._zp_btn.setObjectName("viewer_nav_btn")
        _a11y(self._zp_btn, t("zoom.in"))

        self._z0_btn = QPushButton()
        self._z0_btn.setObjectName("viewer_nav_btn")
        self._z0_btn.setFixedSize(28, 28)
        self._z0_btn.setIconSize(QSize(18, 18))
        self._z0_btn.setIcon(get_reset_zoom_icon(18, TEXT_PRI))
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

        self._first_pg_btn = QPushButton()
        self._first_pg_btn.setIcon(qta.icon("fa5s.angle-double-left", color=TEXT_PRI))
        self._first_pg_btn.setFixedSize(28, 28)
        self._first_pg_btn.setIconSize(QSize(16, 16))
        self._first_pg_btn.setObjectName("viewer_nav_btn")
        first_tip = t("nav.first_page") if t("nav.first_page") != "nav.first_page" else "First page"
        _a11y(self._first_pg_btn, first_tip)

        self._prev_pg_btn = QPushButton()
        self._prev_pg_btn.setIcon(qta.icon("fa5s.chevron-left", color=TEXT_PRI))
        self._prev_pg_btn.setFixedSize(28, 28)
        self._prev_pg_btn.setIconSize(QSize(16, 16))
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
        self._next_pg_btn.setIconSize(QSize(16, 16))
        self._next_pg_btn.setObjectName("viewer_nav_btn")
        _a11y(self._next_pg_btn, t("nav.next_page"))

        self._last_pg_btn = QPushButton()
        self._last_pg_btn.setIcon(qta.icon("fa5s.angle-double-right", color=TEXT_PRI))
        self._last_pg_btn.setFixedSize(28, 28)
        self._last_pg_btn.setIconSize(QSize(16, 16))
        self._last_pg_btn.setObjectName("viewer_nav_btn")
        last_tip = t("nav.last_page") if t("nav.last_page") != "nav.last_page" else "Last page"
        _a11y(self._last_pg_btn, last_tip)

        pn_h.addWidget(self._first_pg_btn)
        pn_h.addWidget(self._prev_pg_btn)
        pn_h.addWidget(self._page_input)
        pn_h.addWidget(self._page_total_lbl)
        pn_h.addWidget(self._next_pg_btn)
        pn_h.addWidget(self._last_pg_btn)
        self._page_nav_widget.setVisible(False)
        layout.addWidget(self._page_nav_widget)

        # Undo/redo top buttons
        self._undo_top_btn = QPushButton()
        self._undo_top_btn.setIcon(qta.icon("fa5s.undo", color=TEXT_PRI))
        self._undo_top_btn.setObjectName("viewer_nav_btn")
        self._undo_top_btn.setFixedSize(28, 28)
        self._undo_top_btn.setIconSize(QSize(16, 16))
        _a11y(self._undo_top_btn, "Undo (Ctrl+Z)")
        self._undo_top_btn.setVisible(False)
        layout.addWidget(self._undo_top_btn)

        self._redo_top_btn = QPushButton()
        self._redo_top_btn.setIcon(qta.icon("fa5s.redo", color=TEXT_PRI))
        self._redo_top_btn.setObjectName("viewer_nav_btn")
        self._redo_top_btn.setFixedSize(28, 28)
        self._redo_top_btn.setIconSize(QSize(16, 16))
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

        self._theme_btn = QPushButton()
        self._theme_btn.setIcon(qta.icon("fa5s.sun", color="#FBBF24"))
        self._theme_btn.setObjectName("theme_btn")
        _a11y(self._theme_btn, t("theme.toggle"))
        self._theme_btn.setFixedSize(28, 28)
        self._theme_btn.setIconSize(QSize(16, 16))
        layout.addWidget(self._theme_btn)

        self._update_btn = QPushButton()
        self._update_btn.setIcon(qta.icon("fa5s.arrow-circle-up", color=ACCENT))
        self._update_btn.setObjectName("viewer_nav_btn")
        self._update_btn.setFixedSize(28, 28)
        self._update_btn.setIconSize(QSize(16, 16))
        _a11y(self._update_btn, t("update.check"))
        self._update_btn.setVisible(False)
        self._update_btn.setStyleSheet(
            f"QPushButton {{ border: 1.5px solid {ACCENT}; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: rgba(20,184,166,0.15); }}"
        )
        layout.addWidget(self._update_btn)

        # ── Far Right: Tool Pane Toggle ──────────────────────────────
        self._right_pane_toggle_btn = QPushButton()
        self._right_pane_toggle_btn.setIcon(qta.icon("fa5s.columns", color=TEXT_PRI))
        self._right_pane_toggle_btn.setObjectName("viewer_nav_btn")
        self._right_pane_toggle_btn.setFixedSize(28, 28)
        self._right_pane_toggle_btn.setIconSize(QSize(16, 16))
        _a11y(self._right_pane_toggle_btn, t("sidebar.collapse_expand"))
        self._right_pane_toggle_btn.setVisible(False)
        layout.addWidget(self._right_pane_toggle_btn)

    def paintEvent(self, event):
        _paint_bg(self)

    def update_theme(self, dark: bool, sidebar_collapsed: bool = False):
        bar_color = TEXT_PRI if dark else _LP
        self._ico_bars = qta.icon("fa5s.bars", color=bar_color)
        self._ico_pages = qta.icon("fa5s.th-large", color=bar_color)

        self._sidebar_toggle_btn.setIcon(self._ico_bars)
        self._pages_toggle_btn.setIcon(self._ico_pages)
        self._right_pane_toggle_btn.setIcon(qta.icon("fa5s.columns", color=bar_color))
        self._open_pdf_btn.setIcon(qta.icon("fa5s.folder-open", color=bar_color))
        self._toc_top_btn.setIcon(qta.icon("fa5s.bookmark", color=bar_color))

        is_night = self._night_top_btn.isChecked()
        self._night_top_btn.setIcon(qta.icon("fa5s.sun" if is_night else "fa5s.moon", color=ACCENT if is_night else bar_color))
        self._print_top_btn.setIcon(qta.icon("fa5s.print", color=bar_color))
        self._present_btn.setIcon(qta.icon("fa5s.tv", color=bar_color))
        self._search_top_btn.setIcon(qta.icon("fa5s.search", color=bar_color))
        self._undo_top_btn.setIcon(qta.icon("fa5s.undo", color=bar_color))
        self._redo_top_btn.setIcon(qta.icon("fa5s.redo", color=bar_color))
        self._zm_btn.setIcon(qta.icon("fa5s.search-minus", color=bar_color))
        self._zp_btn.setIcon(qta.icon("fa5s.search-plus", color=bar_color))
        self._z0_btn.setIcon(get_reset_zoom_icon(18, bar_color))
        self._first_pg_btn.setIcon(qta.icon("fa5s.angle-double-left", color=bar_color))
        self._prev_pg_btn.setIcon(qta.icon("fa5s.chevron-left", color=bar_color))
        self._next_pg_btn.setIcon(qta.icon("fa5s.chevron-right", color=bar_color))
        self._last_pg_btn.setIcon(qta.icon("fa5s.angle-double-right", color=bar_color))

        self._theme_btn.setIcon(qta.icon("fa5s.sun" if dark else "fa5s.moon", color="#FBBF24" if dark else ACCENT))