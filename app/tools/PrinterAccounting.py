# app/tools/PrinterAccounting.py
"""
PDFApps – High-speed PDF Print Suite & Fuji Xerox ApeosPort Accounting Manager.
Supports direct Port 9100 raw streaming (Foxit speed), CUPS spooler, in-memory preview,
and JCL/PJL accounting credential injection with auto-generated persistent JSON configuration.
"""

import sys
import re
import os
import json
import socket
import subprocess
import tempfile
from typing import Any

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QMessageBox, QGroupBox, QComboBox, 
    QCheckBox, QFileDialog, QTabWidget, QSpinBox, QSplitter,
    QScrollArea, QProgressBar
)
from PySide6.QtCore import Qt, QUrl, QPointF, QByteArray, QThread, Signal
from PySide6.QtGui import QPixmap, QIcon, QPainter, QImage

# Fast in-memory PDF rendering & slicing check (PyMuPDF)
try:
    import fitz
    HAS_FITZ = True
except Exception:
    fitz = None  # type: ignore
    HAS_FITZ = False

# Fallback pypdf check
try:
    from pypdf import PdfReader, PdfWriter
    HAS_PYPDF = True
except Exception:
    PdfReader = None  # type: ignore
    PdfWriter = None  # type: ignore
    HAS_PYPDF = False

# QtSvg check
try:
    from PySide6.QtSvg import QSvgRenderer
    HAS_SVG = True
except Exception:
    QSvgRenderer = None  # type: ignore
    HAS_SVG = False

# QtPdf check
try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    HAS_QTPDF = True
except Exception:
    QPdfDocument = None  # type: ignore
    QPdfView = None      # type: ignore
    HAS_QTPDF = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PREFERENCES_FILE = os.path.join(SCRIPT_DIR, "printer_preferences.json")
HISTORY_FILE = os.path.join(SCRIPT_DIR, "history.json")

DEFAULT_PREFERENCES = {
    "dest_mode": 0,
    "printer_queue": "",
    "printer_ip": "",
    "convert_chk": True,
    "user_id": "",
    "passcode": "",
    "account_id": "",
    "last_pdf_path": "",
    "page_scope": 0,
    "custom_range": "",
    "duplex": "2-Sided (Flip on Long Edge)",
    "paper_size": "A4",
    "color_mode": "Color",
    "copies": 1
}


def ensure_preferences_file() -> str:
    """Checks if preferences file exists; if missing, automatically creates it with defaults."""
    if os.path.isfile(PREFERENCES_FILE):
        return PREFERENCES_FILE
    if os.path.isfile(HISTORY_FILE):
        return HISTORY_FILE

    target_path = PREFERENCES_FILE
    try:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_PREFERENCES, f, indent=4)
        return target_path
    except Exception:
        fallback_path = os.path.expanduser("~/.pdfapps_printer_preferences.json")
        try:
            if not os.path.isfile(fallback_path):
                with open(fallback_path, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_PREFERENCES, f, indent=4)
            return fallback_path
        except Exception:
            return target_path


def get_os_info() -> str:
    """Detects Linux distribution (including Fedora 44) or host OS."""
    if sys.platform == "linux":
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r", encoding="utf-8") as f:
                    data = {}
                    for line in f:
                        if "=" in line:
                            k, v = line.strip().split("=", 1)
                            data[k] = v.strip('"')
                    name = data.get("NAME", "Linux")
                    ver = data.get("VERSION_ID", "")
                    if "fedora" in data.get("ID", "").lower():
                        return f"Fedora Linux {ver}".strip()
                    return f"{name} {ver}".strip()
        except Exception:
            pass
        return "Linux CUPS"
    elif sys.platform == "win32":
        return "Windows Spooler"
    elif sys.platform == "darwin":
        return "macOS"
    return str(sys.platform)


# -------------------------------------------------------------
# Embedded SVG Definitions
# -------------------------------------------------------------
SVG_GEAR = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="3"/>
  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
</svg>"""

SVG_DOCUMENT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
  <polyline points="14 2 14 8 20 8"/>
  <line x1="16" y1="13" x2="8" y2="13"/>
  <line x1="16" y1="17" x2="8" y2="17"/>
  <polyline points="10 9 9 9 8 9"/>
</svg>"""

SVG_PRINTER = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="6 9 6 2 18 2 18 9"/>
  <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>
  <rect x="6" y="14" width="12" height="8"/>
</svg>"""

SVG_FOLDER = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
</svg>"""

SVG_CHEVRON_LEFT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="15 18 9 12 15 6"/>
</svg>"""

SVG_CHEVRON_RIGHT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="9 18 15 12 9 6"/>
</svg>"""

SVG_CHECK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="20 6 9 17 4 12"/>
</svg>"""

SVG_TERMINAL = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="4 17 10 11 4 5"/>
  <line x1="12" y1="19" x2="20" y2="19"/>
</svg>"""

SVG_BOLT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
</svg>"""


def get_svg_icon(svg_xml: str, color: str = "#c0caf5", size: int = 20) -> QIcon:
    if not HAS_SVG or QSvgRenderer is None:
        return QIcon()
    formatted = svg_xml.format(color=color)
    renderer = QSvgRenderer(QByteArray(formatted.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


TOKYO_NIGHT_STYLE = """
    QWidget {
        background-color: #1a1b26;
        color: #c0caf5;
        font-family: Segoe UI, Roboto, Helvetica, sans-serif;
        font-size: 10pt;
    }
    QTabWidget::pane {
        border: 1px solid #414868;
        background-color: #1a1b26;
        border-radius: 6px;
    }
    QTabBar::tab {
        background-color: #24283b;
        color: #c0caf5;
        padding: 9px 18px;
        margin-right: 4px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        font-weight: bold;
    }
    QTabBar::tab:selected {
        background-color: #7aa2f7;
        color: #1a1b26;
    }
    QGroupBox {
        border: 1px solid #414868;
        border-radius: 8px;
        margin-top: 8px;
        padding-top: 12px;
        font-weight: bold;
        color: #7aa2f7;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px;
    }
    QLineEdit, QComboBox, QSpinBox {
        background-color: #24283b;
        border: 1px solid #414868;
        border-radius: 6px;
        padding: 5px 8px;
        color: #c0caf5;
    }
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
        border: 1px solid #7aa2f7;
    }
    QPushButton {
        background-color: #24283b;
        border: 1px solid #414868;
        border-radius: 6px;
        color: #c0caf5;
        padding: 6px 12px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #292e42;
        border-color: #7aa2f7;
    }
    QPushButton#PrimaryBtn {
        background-color: #7aa2f7;
        color: #1a1b26;
        border: none;
    }
    QPushButton#PrimaryBtn:hover {
        background-color: #89b4fa;
    }
    QPushButton#ActionBtn {
        background-color: #9ece6a;
        color: #1a1b26;
        border: none;
        padding: 10px;
        font-size: 11pt;
    }
    QPushButton#ActionBtn:hover {
        background-color: #b9f27c;
    }
    QPushButton#NavBtn {
        padding: 4px 10px;
        font-size: 9pt;
    }
    QProgressBar {
        border: 1px solid #414868;
        border-radius: 4px;
        text-align: center;
        background-color: #24283b;
        color: #c0caf5;
        font-weight: bold;
    }
    QProgressBar::chunk {
        background-color: #7aa2f7;
        border-radius: 3px;
    }
"""


class BackgroundPrintWorker(QThread):
    """Background worker thread to stream PDF payloads over raw sockets without freezing the GUI."""
    progress = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, target_ip: str, target_port: int, payload_bytes: bytes, job_name: str):
        super().__init__()
        self.target_ip = target_ip
        self.target_port = target_port
        self.payload_bytes = payload_bytes
        self.job_name = job_name
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            self.progress.emit(10, f"Connecting to {self.target_ip}:{self.target_port}...")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)
                s.settimeout(15)
                s.connect((self.target_ip, int(self.target_port)))

                total_len = len(self.payload_bytes)
                chunk_size = 65536
                sent = 0

                self.progress.emit(25, f"Streaming {total_len / 1024:.1f} KB to printer...")
                while sent < total_len:
                    if self._is_cancelled:
                        raise RuntimeError("Print job cancelled by user.")
                    chunk = self.payload_bytes[sent:sent + chunk_size]
                    s.sendall(chunk)
                    sent += len(chunk)
                    pct = 25 + int((sent / total_len) * 70)
                    self.progress.emit(pct, f"Sending data: {sent // 1024} / {total_len // 1024} KB...")

                self.progress.emit(100, "Print job accepted by printer.")
            self.finished.emit(True, f"Successfully sent '{self.job_name}' to {self.target_ip}!")
        except Exception as exc:
            self.finished.emit(False, str(exc))


class FujiAccountingManager(QWidget):
    def __init__(self, initial_pdf=None):
        super().__init__()
        self.os_title = get_os_info()
        self.setWindowTitle(f"Fast PDF Print & Accounting Suite — [{self.os_title}]")
        self.setStyleSheet(TOKYO_NIGHT_STYLE)
        
        self.total_pages = 0
        self.current_page = 1
        self.initial_pdf = initial_pdf
        self.print_thread: BackgroundPrintWorker | None = None

        self.scroll_area: QScrollArea | None = None
        self.preview_lbl: QLabel | None = None
        self.pdf_doc: Any = None
        self.pdf_view: Any = None
        self.nav: Any = None

        self.setAcceptDrops(True)
        self.init_ui()
        self.load_printer_list()
        self.load_preferences()

        if self.initial_pdf and os.path.isfile(self.initial_pdf):
            self.file_input.setText(os.path.abspath(self.initial_pdf))

        # Start maximized
        self.setWindowState(Qt.WindowState.WindowMaximized)

    def init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(8)

        # Header bar
        header_bar = QHBoxLayout()
        title_lbl = QLabel(f"<b>Print Suite & Manager</b> <span style='color: #7aa2f7;'>[{self.os_title}]</span>")
        title_lbl.setStyleSheet("font-size: 11pt; color: #c0caf5;")
        header_bar.addWidget(title_lbl)
        header_bar.addStretch()

        self.status_badge = QLabel("Engine: Ready")
        self.status_badge.setStyleSheet("background: #24283b; color: #9ece6a; padding: 3px 8px; border-radius: 4px; font-weight: bold;")
        header_bar.addWidget(self.status_badge)
        root_layout.addLayout(header_bar)

        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)

        # Tab 1: PDF Print & Preview (Document SVG)
        self.tab_preview = QWidget()
        self.init_preview_tab()
        doc_icon = get_svg_icon(SVG_DOCUMENT, "#c0caf5", 18)
        self.tabs.addTab(self.tab_preview, doc_icon, "Print & Preview")

        # Tab 2: Settings & Accounting Setup (Gear SVG)
        self.tab_setup = QWidget()
        self.init_setup_tab()
        gear_icon = get_svg_icon(SVG_GEAR, "#c0caf5", 18)
        self.tabs.addTab(self.tab_setup, gear_icon, "Printer & Accounting Setup")

    # -------------------------------------------------------------
    # Drag and Drop Support
    # -------------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".pdf"):
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and path.lower().endswith(".pdf") and os.path.isfile(path):
                self.file_input.setText(path)
                event.acceptProposedAction()
                break

    # -------------------------------------------------------------
    # TAB 1: Print & Preview
    # -------------------------------------------------------------
    def init_preview_tab(self):
        layout = QHBoxLayout(self.tab_preview)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(8)

        # 1. Document Selection
        file_group = QGroupBox("Document Selection")
        f_layout = QVBoxLayout()
        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText("Select or Drag & Drop a PDF here...")
        self.file_input.textChanged.connect(self.load_preview)
        f_layout.addWidget(self.file_input)

        browse_btn = QPushButton("Browse PDF File...")
        browse_btn.setIcon(get_svg_icon(SVG_FOLDER, "#7aa2f7", 16))
        browse_btn.clicked.connect(self.browse_pdf)
        f_layout.addWidget(browse_btn)
        file_group.setLayout(f_layout)
        left_layout.addWidget(file_group)

        # 2. Destination & Mode
        dest_group = QGroupBox("Printer Destination & Mode")
        d_layout = QVBoxLayout()
        d_layout.setSpacing(6)

        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("Target:"))
        self.dest_mode_combo = QComboBox()
        self.dest_mode_combo.addItems([
            "Direct Raw Socket 9100 (Instant Foxit Speed)",
            "CUPS Queue (Linux System Spooler)"
        ])
        self.dest_mode_combo.currentIndexChanged.connect(self.on_dest_mode_changed)
        dest_row.addWidget(self.dest_mode_combo, 1)
        d_layout.addLayout(dest_row)

        ip_row = QHBoxLayout()
        self.ip_lbl = QLabel("Printer IP:")
        ip_row.addWidget(self.ip_lbl)
        self.dest_ip_input = QLineEdit()
        self.dest_ip_input.setPlaceholderText("e.g. 192.168.1.100")
        ip_row.addWidget(self.dest_ip_input, 1)

        self.test_conn_btn = QPushButton("Test")
        self.test_conn_btn.setToolTip("Test Port 9100 connection")
        self.test_conn_btn.clicked.connect(self.test_printer_ip_connection)
        ip_row.addWidget(self.test_conn_btn)
        d_layout.addLayout(ip_row)

        self.cups_queue_combo = QComboBox()
        self.cups_queue_combo.setVisible(False)
        d_layout.addWidget(self.cups_queue_combo)

        # Dynamic Accounting Banner
        self.acct_banner_lbl = QLabel("Accounting: Not configured")
        self.acct_banner_lbl.setStyleSheet("color: #7aa2f7; font-size: 8.5pt;")
        d_layout.addWidget(self.acct_banner_lbl)

        dest_group.setLayout(d_layout)
        left_layout.addWidget(dest_group)

        # 3. Page Range Selector
        page_group = QGroupBox("Page Range")
        pg_layout = QVBoxLayout()
        pg_layout.setSpacing(5)

        self.page_scope_combo = QComboBox()
        self.page_scope_combo.addItems([
            "All Pages",
            "Current Page Only",
            "Custom Range"
        ])
        self.page_scope_combo.currentIndexChanged.connect(self.on_page_scope_changed)
        pg_layout.addWidget(self.page_scope_combo)

        self.custom_range_input = QLineEdit()
        self.custom_range_input.setPlaceholderText("e.g. 1, 3, 5-8")
        self.custom_range_input.setEnabled(False)
        pg_layout.addWidget(self.custom_range_input)

        quick_range_row = QHBoxLayout()
        btn_all = QPushButton("All")
        btn_all.setObjectName("NavBtn")
        btn_all.clicked.connect(lambda: self.page_scope_combo.setCurrentIndex(0))
        btn_odd = QPushButton("Odd")
        btn_odd.setObjectName("NavBtn")
        btn_odd.clicked.connect(self.set_range_odd)
        btn_even = QPushButton("Even")
        btn_even.setObjectName("NavBtn")
        btn_even.clicked.connect(self.set_range_even)
        quick_range_row.addWidget(btn_all)
        quick_range_row.addWidget(btn_odd)
        quick_range_row.addWidget(btn_even)
        pg_layout.addLayout(quick_range_row)

        page_group.setLayout(pg_layout)
        left_layout.addWidget(page_group)

        # 4. Print Settings Group
        settings_group = QGroupBox("Layout & Quality Settings")
        s_layout = QVBoxLayout()
        s_layout.setSpacing(5)

        s_layout.addWidget(QLabel("2-Sided / Duplex:"))
        self.duplex_combo = QComboBox()
        self.duplex_combo.addItems([
            "1-Sided (Simplex)",
            "2-Sided (Flip on Long Edge)",
            "2-Sided (Flip on Short Edge)"
        ])
        self.duplex_combo.setCurrentIndex(1)
        s_layout.addWidget(self.duplex_combo)

        s_layout.addWidget(QLabel("Paper Size:"))
        self.paper_combo = QComboBox()
        self.paper_combo.addItems(["A4", "A3", "Letter", "Legal"])
        self.paper_combo.setCurrentText("A4")
        s_layout.addWidget(self.paper_combo)

        s_layout.addWidget(QLabel("Color Mode:"))
        self.color_combo = QComboBox()
        self.color_combo.addItems([
            "Color",
            "Black & White (Monochrome)"
        ])
        s_layout.addWidget(self.color_combo)

        s_layout.addWidget(QLabel("Copies:"))
        self.copies_spin = QSpinBox()
        self.copies_spin.setRange(1, 99)
        self.copies_spin.setValue(1)
        s_layout.addWidget(self.copies_spin)

        settings_group.setLayout(s_layout)
        left_layout.addWidget(settings_group)

        left_layout.addStretch()

        # Progress bar
        self.print_progress = QProgressBar()
        self.print_progress.setVisible(False)
        self.print_progress.setFixedHeight(14)
        left_layout.addWidget(self.print_progress)

        # Send Button
        self.send_pdf_btn = QPushButton("⚡ Fast Direct Print (Port 9100)")
        self.send_pdf_btn.setObjectName("ActionBtn")
        self.send_pdf_btn.setIcon(get_svg_icon(SVG_BOLT, "#1a1b26", 18))
        self.send_pdf_btn.clicked.connect(self.execute_print_job)
        left_layout.addWidget(self.send_pdf_btn)

        splitter.addWidget(left_widget)

        # Right Column: PDF Preview Area
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        nav_bar = QHBoxLayout()
        self.doc_name_lbl = QLabel("No document loaded.")
        nav_bar.addWidget(self.doc_name_lbl)

        nav_bar.addStretch()

        self.prev_btn = QPushButton("Prev")
        self.prev_btn.setObjectName("NavBtn")
        self.prev_btn.setIcon(get_svg_icon(SVG_CHEVRON_LEFT, "#c0caf5", 14))
        self.prev_btn.clicked.connect(self.go_prev_page)
        nav_bar.addWidget(self.prev_btn)

        self.page_indicator_lbl = QLabel("Page: - / -")
        self.page_indicator_lbl.setStyleSheet("font-weight: bold; color: #7aa2f7; padding: 0 10px;")
        nav_bar.addWidget(self.page_indicator_lbl)

        self.next_btn = QPushButton("Next")
        self.next_btn.setObjectName("NavBtn")
        self.next_btn.setIcon(get_svg_icon(SVG_CHEVRON_RIGHT, "#c0caf5", 14))
        self.next_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.next_btn.clicked.connect(self.go_next_page)
        nav_bar.addWidget(self.next_btn)

        right_layout.addLayout(nav_bar)

        if HAS_QTPDF and QPdfDocument is not None and QPdfView is not None:
            self.pdf_doc = QPdfDocument(self)
            self.pdf_view = QPdfView(self)
            self.pdf_view.setDocument(self.pdf_doc)
            self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            
            self.nav = self.pdf_view.pageNavigator()
            self.nav.currentPageChanged.connect(self.on_qtpdf_page_changed)
            right_layout.addWidget(self.pdf_view)
        else:
            self.scroll_area = QScrollArea()
            self.preview_lbl = QLabel("Loading preview engine...")
            self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.scroll_area.setWidget(self.preview_lbl)
            self.scroll_area.setWidgetResizable(True)
            right_layout.addWidget(self.scroll_area)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

    # -------------------------------------------------------------
    # TAB 2: Setup & Credentials
    # -------------------------------------------------------------
    def init_setup_tab(self):
        layout = QVBoxLayout(self.tab_setup)
        layout.setSpacing(12)

        p_group = QGroupBox("Target Printer & Network Defaults")
        p_layout = QVBoxLayout()

        p_layout.addWidget(QLabel("CUPS Queue:"))
        self.printer_combo = QComboBox()
        self.printer_combo.currentIndexChanged.connect(self.on_printer_selected)
        p_layout.addWidget(self.printer_combo)

        p_layout.addWidget(QLabel("Default Printer IP Address:"))
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("e.g. 192.168.1.100")
        self.ip_input.textChanged.connect(lambda txt: self.dest_ip_input.setText(txt))
        p_layout.addWidget(self.ip_input)

        self.convert_chk = QCheckBox("Switch CUPS queue from LPD to socket://<IP>:9100 on apply")
        self.convert_chk.setChecked(True)
        p_layout.addWidget(self.convert_chk)

        p_group.setLayout(p_layout)
        layout.addWidget(p_group)

        cred_group = QGroupBox("Accounting Credentials (Auditron / XSA)")
        c_layout = QVBoxLayout()

        c_layout.addWidget(QLabel("User ID / Login Name:"))
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Your printer accounting login")
        self.user_input.textChanged.connect(self.update_acct_banner)
        c_layout.addWidget(self.user_input)

        c_layout.addWidget(QLabel("Passcode / PIN:"))
        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("Your printer accounting passcode")
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_input.textChanged.connect(self.update_acct_banner)

        p_row = QHBoxLayout()
        p_row.addWidget(self.pass_input)
        toggle_pin = QPushButton("Show / Hide")
        toggle_pin.setCheckable(True)
        toggle_pin.toggled.connect(lambda c: self.pass_input.setEchoMode(QLineEdit.EchoMode.Normal if c else QLineEdit.EchoMode.Password))
        p_row.addWidget(toggle_pin)
        c_layout.addLayout(p_row)

        c_layout.addWidget(QLabel("Account ID (Optional):"))
        self.account_input = QLineEdit()
        self.account_input.setPlaceholderText("Leave blank unless required by administrator")
        self.account_input.textChanged.connect(self.update_acct_banner)
        c_layout.addWidget(self.account_input)

        cred_group.setLayout(c_layout)
        layout.addWidget(cred_group)

        auth_group = QGroupBox("System Sudo Authorization (For Updating CUPS Config on Linux)")
        a_layout = QVBoxLayout()

        a_layout.addWidget(QLabel("Linux Sudo Password:"))
        self.sudo_input = QLineEdit()
        self.sudo_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.sudo_input.setPlaceholderText("Enter Linux sudo password to modify CUPS PPD")

        s_row = QHBoxLayout()
        s_row.addWidget(self.sudo_input)
        toggle_sudo = QPushButton("Show / Hide")
        toggle_sudo.setCheckable(True)
        toggle_sudo.toggled.connect(lambda c: self.sudo_input.setEchoMode(QLineEdit.EchoMode.Normal if c else QLineEdit.EchoMode.Password))
        s_row.addWidget(toggle_sudo)
        a_layout.addLayout(s_row)

        btn_row = QHBoxLayout()
        self.test_socket_btn = QPushButton("Test Socket PS")
        self.test_socket_btn.setIcon(get_svg_icon(SVG_TERMINAL, "#c0caf5", 16))
        self.test_socket_btn.clicked.connect(self.send_direct_socket_test)
        btn_row.addWidget(self.test_socket_btn)

        self.save_btn = QPushButton("Save & Apply CUPS Settings")
        self.save_btn.setObjectName("PrimaryBtn")
        self.save_btn.setIcon(get_svg_icon(SVG_CHECK, "#1a1b26", 16))
        self.save_btn.clicked.connect(self.apply_configuration)
        btn_row.addWidget(self.save_btn)

        a_layout.addLayout(btn_row)
        auth_group.setLayout(a_layout)
        layout.addWidget(auth_group)

        layout.addStretch()

    def update_acct_banner(self):
        u = self.user_input.text().strip()
        has_pin = bool(self.pass_input.text().strip())
        if not u and not has_pin:
            self.acct_banner_lbl.setText("Accounting: None configured")
        else:
            pin_mask = "****" if has_pin else "None"
            user_disp = u if u else "None"
            self.acct_banner_lbl.setText(f"Accounting: User [{user_disp}] | PIN [{pin_mask}]")

    def on_dest_mode_changed(self, idx: int):
        is_direct = (idx == 0)
        self.ip_lbl.setVisible(is_direct)
        self.dest_ip_input.setVisible(is_direct)
        self.test_conn_btn.setVisible(is_direct)
        self.cups_queue_combo.setVisible(not is_direct)
        if is_direct:
            self.send_pdf_btn.setText("⚡ Fast Direct Print (Port 9100)")
        else:
            self.send_pdf_btn.setText("🖨️ Print via CUPS Queue")

    def test_printer_ip_connection(self):
        ip = self.dest_ip_input.text().strip()
        if not ip:
            QMessageBox.warning(self, "Validation", "Please enter an IP address.")
            return
        try:
            with socket.create_connection((ip, 9100), timeout=1.5):
                QMessageBox.information(self, "Online", f"Printer at {ip}:9100 is ONLINE and ready!")
        except Exception as e:
            QMessageBox.critical(self, "Offline", f"Cannot connect to {ip}:9100:\n{e}")

    # -------------------------------------------------------------
    # Auto-Generated Preferences Persistence (JSON)
    # -------------------------------------------------------------
    def load_preferences(self):
        target_file = ensure_preferences_file()
        if not os.path.exists(target_file):
            self.update_acct_banner()
            return
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "duplex" in data:
                idx = self.duplex_combo.findText(data["duplex"])
                if idx >= 0: self.duplex_combo.setCurrentIndex(idx)
            if "paper_size" in data:
                idx = self.paper_combo.findText(data["paper_size"])
                if idx >= 0: self.paper_combo.setCurrentIndex(idx)
            if "color_mode" in data:
                idx = self.color_combo.findText(data["color_mode"])
                if idx >= 0: self.color_combo.setCurrentIndex(idx)
            if "copies" in data:
                self.copies_spin.setValue(int(data["copies"]))
            if "page_scope" in data:
                self.page_scope_combo.setCurrentIndex(int(data["page_scope"]))
            if "custom_range" in data:
                self.custom_range_input.setText(data["custom_range"])
            if "dest_mode" in data:
                self.dest_mode_combo.setCurrentIndex(int(data["dest_mode"]))

            if "printer_queue" in data and data["printer_queue"]:
                idx = self.printer_combo.findText(data["printer_queue"])
                if idx >= 0:
                    self.printer_combo.setCurrentIndex(idx)
                else:
                    self.printer_combo.addItem(data["printer_queue"])
                    self.printer_combo.setCurrentText(data["printer_queue"])
            if "printer_ip" in data and data["printer_ip"]:
                self.ip_input.setText(data["printer_ip"])
                self.dest_ip_input.setText(data["printer_ip"])
            if "convert_chk" in data:
                self.convert_chk.setChecked(data["convert_chk"])
            if "user_id" in data:
                self.user_input.setText(data["user_id"])
            if "passcode" in data:
                self.pass_input.setText(data["passcode"])
            if "account_id" in data:
                self.account_input.setText(data["account_id"])

            if "last_pdf_path" in data and os.path.exists(data["last_pdf_path"]):
                self.file_input.setText(data["last_pdf_path"])

            self.update_acct_banner()
        except Exception as e:
            print(f"Failed to read preferences: {e}")

    def save_preferences(self):
        data = {
            "dest_mode": self.dest_mode_combo.currentIndex(),
            "printer_queue": self.printer_combo.currentText(),
            "printer_ip": self.dest_ip_input.text().strip(),
            "convert_chk": self.convert_chk.isChecked(),
            "user_id": self.user_input.text().strip(),
            "passcode": self.pass_input.text().strip(),
            "account_id": self.account_input.text().strip(),
            "last_pdf_path": self.file_input.text().strip(),
            "page_scope": self.page_scope_combo.currentIndex(),
            "custom_range": self.custom_range_input.text().strip(),
            "duplex": self.duplex_combo.currentText(),
            "paper_size": self.paper_combo.currentText(),
            "color_mode": self.color_combo.currentText(),
            "copies": self.copies_spin.value()
        }
        for path in (PREFERENCES_FILE, HISTORY_FILE):
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
            except Exception:
                pass

    def closeEvent(self, event):
        self.save_preferences()
        super().closeEvent(event)

    # -------------------------------------------------------------
    # Page Navigation & Preview Logic
    # -------------------------------------------------------------
    def browse_pdf(self):
        current_val = self.file_input.text().strip()
        if current_val and os.path.exists(os.path.dirname(current_val)):
            start_dir = os.path.dirname(current_val) if os.path.isfile(current_val) else current_val
        elif os.path.exists("/var/mnt/shared-drive/2027"):
            start_dir = "/var/mnt/shared-drive/2027"
        else:
            start_dir = os.path.expanduser("~")

        dialog = QFileDialog(self, "Select PDF File", start_dir, "PDF Files (*.pdf);;All Files (*)")

        pinned_dirs = [
            os.path.expanduser("~"),
            "/var/mnt/shared-drive",
            "/var/mnt/shared-drive/2027",
            "/var/mnt/shared-drive/2027/MrCooperSuite/0HTMLOfflineQUiz/ahmadac.github.io/0_Quiz/0 Paper Hw",
            os.path.expanduser("~/Downloads"),
            os.path.expanduser("~/Documents"),
        ]

        sidebar_urls = [QUrl.fromLocalFile(p) for p in pinned_dirs if os.path.exists(p)]
        dialog.setSidebarUrls(sidebar_urls)

        if dialog.exec():
            files = dialog.selectedFiles()
            if files:
                self.file_input.setText(files[0])
                self.save_preferences()

    def load_preview(self, file_path: str):
        if not file_path or not os.path.isfile(file_path):
            self.doc_name_lbl.setText("No document loaded.")
            self.page_indicator_lbl.setText("Page: - / -")
            self.total_pages = 0
            self.current_page = 1
            return

        filename = os.path.basename(file_path)
        self.doc_name_lbl.setText(f"<b>{filename}</b>")

        if HAS_QTPDF and self.pdf_doc is not None:
            self.pdf_doc.load(file_path)
            self.total_pages = self.pdf_doc.pageCount()
            self.current_page = 1
            self.update_page_indicator()
        elif HAS_FITZ and fitz is not None:
            try:
                doc = fitz.open(file_path)
                self.total_pages = doc.page_count
                doc.close()
                self.current_page = 1
                self.render_fitz_page(file_path, 1)
            except Exception:
                self.render_fallback_page(file_path, 1)
        else:
            self.render_fallback_page(file_path, 1)

    def on_qtpdf_page_changed(self, page_idx: int):
        self.current_page = page_idx + 1
        self.update_page_indicator()

    def update_page_indicator(self):
        self.page_indicator_lbl.setText(f"Viewing: {self.current_page} / {self.total_pages}")
        if self.page_scope_combo.currentIndex() == 1:
            self.page_scope_combo.setItemText(1, f"Current Page Only (Page {self.current_page})")

    def go_prev_page(self):
        if self.current_page > 1:
            self.jump_to_page(self.current_page - 1)

    def go_next_page(self):
        if self.current_page < self.total_pages:
            self.jump_to_page(self.current_page + 1)

    def jump_to_page(self, page_num: int):
        self.current_page = page_num
        self.update_page_indicator()

        if HAS_QTPDF and self.nav is not None:
            self.nav.jump(page_num - 1, QPointF(0, 0), self.nav.currentZoom())
        elif HAS_FITZ:
            self.render_fitz_page(self.file_input.text().strip(), page_num)
        else:
            self.render_fallback_page(self.file_input.text().strip(), page_num)

    def render_fitz_page(self, file_path: str, page_num: int):
        """Instant in-memory rendering via PyMuPDF without spawning pdftoppm."""
        if not HAS_FITZ or fitz is None:
            return
        try:
            doc = fitz.open(file_path)
            if 1 <= page_num <= doc.page_count:
                page = doc[page_num - 1]
                target_w = max(400, (self.scroll_area.width() - 40) if self.scroll_area else 400)
                zoom = target_w / max(1.0, page.rect.width)
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
                doc.close()
                if self.preview_lbl is not None:
                    self.preview_lbl.setPixmap(QPixmap.fromImage(img))
        except Exception:
            pass

    def render_fallback_page(self, file_path: str, page_num: int):
        try:
            res = subprocess.run(["pdfinfo", file_path], capture_output=True, text=True)
            m = re.search(r"Pages:\s+([0-9]+)", res.stdout)
            if m:
                self.total_pages = int(m.group(1))
            self.current_page = page_num
            self.update_page_indicator()

            subprocess.run([
                "pdftoppm", "-png", "-r", "120", 
                "-f", str(page_num), "-l", str(page_num), 
                file_path, "/tmp/preview_pg"
            ], check=True)
            img_path = f"/tmp/preview_pg-{page_num}.png"
            if os.path.exists(img_path) and self.preview_lbl is not None:
                pix = QPixmap(img_path)
                self.preview_lbl.setPixmap(pix.scaledToWidth(720, Qt.TransformationMode.SmoothTransformation))
        except Exception:
            pass

    def on_page_scope_changed(self, idx: int):
        self.custom_range_input.setEnabled(idx == 2)
        if idx == 1:
            self.page_scope_combo.setItemText(1, f"Current Page Only (Page {self.current_page})")
        else:
            self.page_scope_combo.setItemText(1, "Current Page Only")

    def set_range_odd(self):
        self.page_scope_combo.setCurrentIndex(2)
        if self.total_pages > 0:
            odds = [str(p) for p in range(1, self.total_pages + 1, 2)]
            self.custom_range_input.setText(", ".join(odds))

    def set_range_even(self):
        self.page_scope_combo.setCurrentIndex(2)
        if self.total_pages > 0:
            evens = [str(p) for p in range(2, self.total_pages + 1, 2)]
            self.custom_range_input.setText(", ".join(evens))

    # -------------------------------------------------------------
    # High-Speed Slicing & Direct Print Execution
    # -------------------------------------------------------------
    def parse_pages(self, scope_idx: int, total_pages: int) -> list[int]:
        if scope_idx == 0:
            return list(range(1, total_pages + 1))
        elif scope_idx == 1:
            return [self.current_page]
        elif scope_idx == 2:
            raw_text = self.custom_range_input.text().strip()
            if not raw_text:
                raise ValueError("Custom page range is empty. Enter pages like '1, 3, 5-8'.")

            pages: set[int] = set()
            for part in raw_text.split(","):
                part = part.strip()
                if not part:
                    continue
                if "-" in part:
                    bounds = part.split("-")
                    if len(bounds) == 2 and bounds[0].strip().isdigit() and bounds[1].strip().isdigit():
                        start, end = int(bounds[0]), int(bounds[1])
                        for p in range(min(start, end), max(start, end) + 1):
                            if 1 <= p <= total_pages:
                                pages.add(p)
                elif part.isdigit():
                    p = int(part)
                    if 1 <= p <= total_pages:
                        pages.add(p)

            if not pages:
                raise ValueError(f"No valid pages found in '{raw_text}' for a {total_pages}-page document.")
            return sorted(list(pages))
        return list(range(1, total_pages + 1))

    def extract_pdf_pages_fast(self, input_pdf: str, page_list: list[int]) -> str:
        """Lightning-fast in-memory slicing via PyMuPDF or pypdf."""
        tmp_fd, out_path = tempfile.mkstemp(suffix=".pdf")
        os.close(tmp_fd)

        # 1. PyMuPDF (Fastest, zero process overhead)
        if HAS_FITZ and fitz is not None:
            doc = fitz.open(input_pdf)
            new_doc = fitz.open()
            for p in page_list:
                if 1 <= p <= doc.page_count:
                    new_doc.insert_pdf(doc, from_page=p-1, to_page=p-1)
            new_doc.save(out_path)
            new_doc.close()
            doc.close()
            return out_path

        # 2. pypdf
        if HAS_PYPDF and PdfReader is not None and PdfWriter is not None:
            reader = PdfReader(input_pdf)
            writer = PdfWriter()
            for p in page_list:
                if 1 <= p <= len(reader.pages):
                    writer.add_page(reader.pages[p-1])
            with open(out_path, "wb") as f:
                writer.write(f)
            return out_path

        # 3. qpdf fallback
        page_str = ",".join(str(p) for p in page_list)
        try:
            res = subprocess.run(["qpdf", "--empty", "--pages", input_pdf, page_str, "--", out_path], capture_output=True)
            if res.returncode == 0:
                return out_path
        except FileNotFoundError:
            pass

        # 4. pdfseparate / pdfunite fallback
        try:
            temp_dir = tempfile.mkdtemp()
            chunk_files = []
            for p in page_list:
                single_page = os.path.join(temp_dir, f"pg_{p}.pdf")
                subprocess.run(["pdfseparate", "-f", str(p), "-l", str(p), input_pdf, single_page], check=True)
                chunk_files.append(single_page)

            subprocess.run(["pdfunite"] + chunk_files + [out_path], check=True)
            for f in chunk_files:
                os.remove(f)
            os.rmdir(temp_dir)
            return out_path
        except Exception:
            if os.path.exists(out_path):
                os.remove(out_path)
            raise RuntimeError("Could not slice pages. Please install 'pymupdf' or 'qpdf'.")

    def execute_print_job(self):
        pdf_path = self.file_input.text().strip()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Invalid File", "Please select a valid PDF file first.")
            return

        is_direct = (self.dest_mode_combo.currentIndex() == 0)
        ip = self.dest_ip_input.text().strip()
        queue = self.cups_queue_combo.currentText().strip() or self.printer_combo.currentText().strip()

        if is_direct and not ip:
            QMessageBox.warning(self, "Missing IP", "Printer IP Address is required for Direct Port 9100.")
            return
        if not is_direct and not queue:
            QMessageBox.warning(self, "Missing Queue", "No CUPS queue selected.")
            return

        scope_idx = self.page_scope_combo.currentIndex()
        pages_to_print: list[int] = []
        try:
            pages_to_print = self.parse_pages(scope_idx, self.total_pages or 9999)
        except Exception as e:
            QMessageBox.warning(self, "Page Range Error", str(e))
            return

        if not pages_to_print:
            QMessageBox.warning(self, "Page Range Error", "No pages selected to print.")
            return

        needs_cleanup = False
        target_pdf = pdf_path
        if scope_idx != 0 or len(pages_to_print) != self.total_pages:
            try:
                target_pdf = self.extract_pdf_pages_fast(pdf_path, pages_to_print)
                needs_cleanup = True
            except Exception as e:
                QMessageBox.critical(self, "Page Slicing Error", str(e))
                return

        duplex_val = self.duplex_combo.currentText()
        paper_val = self.paper_combo.currentText()
        color_val = self.color_combo.currentText()
        copies_val = self.copies_spin.value()
        username = self.user_input.text().strip()
        passcode = self.pass_input.text().strip()
        account = self.account_input.text().strip()

        # If CUPS Mode on Linux
        if not is_direct:
            try:
                cmd = ["lp", "-d", queue, "-n", str(copies_val)]
                if "Long Edge" in duplex_val:
                    cmd.extend(["-o", "sides=two-sided-long-edge"])
                elif "Short Edge" in duplex_val:
                    cmd.extend(["-o", "sides=two-sided-short-edge"])
                else:
                    cmd.extend(["-o", "sides=one-sided"])

                cmd.extend(["-o", f"media={paper_val}"])
                cmd.extend(["-o", "ColorModel=Color" if "Color" in color_val else "ColorModel=Gray"])
                if username:
                    cmd.extend(["-o", f"job-originating-user-name={username}"])
                cmd.append(target_pdf)

                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode != 0:
                    raise RuntimeError(res.stderr.strip() or f"lp exited with code {res.returncode}")

                self.save_preferences()
                QMessageBox.information(self, "CUPS Print Sent", f"Print job sent to CUPS queue '{queue}'!\n{res.stdout.strip()}")
            except Exception as e:
                QMessageBox.critical(self, "CUPS Error", f"Failed to print via CUPS:\n{e}")
            finally:
                if needs_cleanup and os.path.exists(target_pdf):
                    os.remove(target_pdf)
            return

        # Direct Socket Port 9100 Mode (Foxit-speed)
        try:
            with open(target_pdf, "rb") as f:
                pdf_data = f.read()

            pjl = [
                "\x1b%-12345X@PJL"
            ]
            if username:
                pjl.append(f'@PJL SET JOBATTR = "@JOAU={username}"')
            if passcode:
                pjl.append(f'@PJL SET JOBATTR = "@JOAP={passcode}"')
            if account:
                pjl.append(f'@PJL SET JOBATTR = "@DAID={account}"')

            pjl.append(f'@PJL SET JOBNAME = "{os.path.basename(pdf_path)}"')
            pjl.append(f"@PJL SET COPIES = {copies_val}")
            pjl.append(f"@PJL SET PAPER = {paper_val}")

            if "Color" in color_val:
                pjl.append("@PJL SET COLORMODE = COLOR")
                pjl.append("@PJL SET RENDERMODE = COLOR")
            else:
                pjl.append("@PJL SET COLORMODE = MONO")
                pjl.append("@PJL SET RENDERMODE = GRAYSCALE")

            if "Long Edge" in duplex_val:
                pjl.append("@PJL SET DUPLEX = ON")
                pjl.append("@PJL SET BINDING = LONGEDGE")
            elif "Short Edge" in duplex_val:
                pjl.append("@PJL SET DUPLEX = ON")
                pjl.append("@PJL SET BINDING = SHORTEDGE")
            else:
                pjl.append("@PJL SET DUPLEX = OFF")

            pjl.append("@PJL ENTER LANGUAGE = PDF\r\n")

            header_str = "\r\n".join(pjl)
            payload = header_str.encode("latin-1") + pdf_data + b"\r\n\x1b%-12345X"

            self.send_pdf_btn.setEnabled(False)
            self.print_progress.setValue(0)
            self.print_progress.setVisible(True)

            self.print_thread = BackgroundPrintWorker(ip, 9100, payload, os.path.basename(pdf_path))
            
            def on_progress(pct: int, msg: str):
                self.print_progress.setValue(pct)
                self.status_badge.setText(msg)

            def on_finished(success: bool, message: str):
                self.send_pdf_btn.setEnabled(True)
                self.print_progress.setVisible(False)
                self.status_badge.setText("Engine: Ready")

                if needs_cleanup and os.path.exists(target_pdf):
                    os.remove(target_pdf)

                if success:
                    self.save_preferences()
                    page_desc = f"{len(pages_to_print)} page(s)" if pages_to_print else "All pages"
                    QMessageBox.information(
                        self, "Print Sent (Port 9100)",
                        f"Job transmitted instantly to {ip}:9100!\n\n"
                        f"• File: {os.path.basename(pdf_path)}\n"
                        f"• Pages: {page_desc}\n"
                        f"• Duplex: {duplex_val}\n"
                        f"• Paper: {paper_val}\n"
                        f"• Color: {color_val}\n"
                        f"• Copies: {copies_val}"
                    )
                else:
                    QMessageBox.critical(self, "Printing Failed", f"Could not print to {ip}:9100:\n{message}")

            self.print_thread.progress.connect(on_progress)
            self.print_thread.finished.connect(on_finished)
            self.print_thread.start()

        except Exception as e:
            self.send_pdf_btn.setEnabled(True)
            self.print_progress.setVisible(False)
            if needs_cleanup and os.path.exists(target_pdf):
                os.remove(target_pdf)
            QMessageBox.critical(self, "Print Setup Error", str(e))

    # -------------------------------------------------------------
    # CUPS / System Configuration
    # -------------------------------------------------------------
    def load_printer_list(self):
        try:
            res = subprocess.run(["lpstat", "-e"], capture_output=True, text=True)
            queues = [q.strip() for q in res.stdout.splitlines() if q.strip()]
            if not queues:
                res_p = subprocess.run(["lpstat", "-p"], capture_output=True, text=True)
                queues = re.findall(r"printer\s+([^\s]+)", res_p.stdout)

            self.printer_combo.clear()
            self.printer_combo.addItems(queues)
            self.cups_queue_combo.clear()
            self.cups_queue_combo.addItems(queues)

            if "4th" in queues:
                self.printer_combo.setCurrentText("4th")
                self.cups_queue_combo.setCurrentText("4th")
            self.on_printer_selected()
        except Exception:
            self.printer_combo.addItem("4th")
            self.cups_queue_combo.addItem("4th")

    def on_printer_selected(self):
        queue = self.printer_combo.currentText()
        if not queue:
            return
        try:
            res = subprocess.run(["lpstat", "-v", queue], capture_output=True, text=True)
            m = re.search(r":\s*[a-zA-Z0-9_+.-]+://([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", res.stdout)
            if m:
                self.ip_input.setText(m.group(1))
                self.dest_ip_input.setText(m.group(1))
        except Exception:
            pass

    def run_sudo_cmd(self, cmd_args: list[str], input_data: str | None = None) -> str:
        sudo_pwd = self.sudo_input.text()
        if not sudo_pwd:
            raise ValueError("Please enter your Linux system (sudo) password in Tab 2.")

        cmd = ["sudo", "-S"] + cmd_args
        payload = f"{sudo_pwd}\n"
        if input_data:
            payload += input_data

        proc = subprocess.run(cmd, input=payload, capture_output=True, text=True)
        if proc.returncode != 0:
            err = proc.stderr.lower()
            if "incorrect password" in err or "authentication failure" in err:
                raise PermissionError("Incorrect Linux sudo password.")
            raise RuntimeError(proc.stderr.strip() or f"Command failed with code {proc.returncode}")
        return proc.stdout

    def send_direct_socket_test(self):
        ip = self.ip_input.text().strip() or self.dest_ip_input.text().strip()
        username = self.user_input.text().strip() or "testuser"
        passcode = self.pass_input.text().strip()

        if not ip:
            QMessageBox.warning(self, "Validation", "Printer IP Address is required.")
            return

        test_str = (
            "\x1b%-12345X@PJL\r\n"
            f'@PJL SET JOBATTR = "@JOAU={username}"\r\n'
            f'@PJL SET JOBATTR = "@JOAP={passcode}"\r\n'
            "@PJL ENTER LANGUAGE = POSTSCRIPT\r\n"
            "%!PS\r\n"
            "/Helvetica findfont 20 scalefont setfont\r\n"
            "100 700 moveto\r\n"
            f"(Direct Socket Test: {username} on ApeosPort) show\r\n"
            "showpage\r\n"
            "\x1b%-12345X"
        )
        payload = test_str.encode("latin-1")

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((ip, 9100))
                s.sendall(payload)
            QMessageBox.information(self, "Sent", f"Test print sent directly to {ip}:9100.")
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", f"Failed to send direct test:\n{e}")

    def apply_configuration(self):
        queue = self.printer_combo.currentText()
        ip = self.ip_input.text().strip()
        username = self.user_input.text().strip()
        passcode = self.pass_input.text().strip()
        account = self.account_input.text().strip()

        if not queue:
            QMessageBox.warning(self, "Error", "No printer queue selected.")
            return
        if not username:
            QMessageBox.warning(self, "Validation", "User ID cannot be empty.")
            return

        if self.convert_chk.isChecked() and ip:
            try:
                new_uri = f"socket://{ip}:9100"
                self.run_sudo_cmd(["lpadmin", "-p", queue, "-v", new_uri])
                self.run_sudo_cmd(["lpadmin", "-p", queue, "-o", "pdftops-renderer-default=pdftops"])
                self.run_sudo_cmd(["lpadmin", "-d", queue])
            except Exception as e:
                QMessageBox.critical(self, "Error Updating Queue", f"Could not update printer URI:\n{e}")
                return

        try:
            ppd_path = f"/etc/cups/ppd/{queue}.ppd"
            current_ppd = self.run_sudo_cmd(["cat", ppd_path])
            base_text = current_ppd.split("*Protocols: PJL")[0].rstrip()

            daid_entry = f'@PJL SET JOBATTR = <22>@DAID={account}<22><0A>' if account else ''
            user_entry = f'@PJL SET JOBATTR = <22>@JOAU={username}<22><0A>' if username else ''
            pin_entry = f'@PJL SET JOBATTR = <22>@JOAP={passcode}<22><0A>' if passcode else ''

            new_jcl = (
                "\n\n*Protocols: PJL\n"
                f'*JCLBegin: "<1B>%-12345X@PJL<0A>{user_entry}{pin_entry}{daid_entry}"\n'
                '*JCLToPSInterpreter: "@PJL ENTER LANGUAGE = POSTSCRIPT<0A>"\n'
                '*JCLToPDFInterpreter: "@PJL ENTER LANGUAGE = PDF<0A>"\n'
                '*JCLEnd: "<1B>%-12345X"\n'
            )
            full_text = base_text + new_jcl

            self.run_sudo_cmd(["tee", ppd_path], input_data=full_text)
            self.run_sudo_cmd(["systemctl", "restart", "cups"])

            self.save_preferences()

            QMessageBox.information(
                self, 
                "Success", 
                f"Queue '{queue}' configured:\n- URI set to socket://{ip}:9100\n- Injected PS & PDF accounting headers\n- Set as default printer\n- CUPS restarted."
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))


def main():
    app = QApplication.instance()
    owns_app = False
    if not app:
        app = QApplication(sys.argv)
        owns_app = True

    initial_pdf = None
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if not arg.startswith("-") and os.path.isfile(arg):
                initial_pdf = os.path.abspath(arg)
                break

    window = FujiAccountingManager(initial_pdf=initial_pdf)
    window.showMaximized()

    if owns_app:
        sys.exit(app.exec())


if __name__ == "__main__":
    main()