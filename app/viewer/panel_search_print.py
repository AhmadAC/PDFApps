# app/viewer/panel_search_print.py
"""PDFApps – High-speed custom print dialog, accounting integration, and in-document search."""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
from typing import TYPE_CHECKING

import fitz
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
import qtawesome as qta

from app.constants import ACCENT, BG_CARD, BG_INNER, BORDER, TEXT_PRI, TEXT_SEC, _LQ
from app.i18n import t
from app.utils import parse_pages, show_error

if TYPE_CHECKING:
    from app.viewer.canvas_1 import _SelectCanvas
    _Base = QWidget
else:
    _Base = object

_log = logging.getLogger(__name__)


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _get_os_badge() -> str:
    if _is_linux():
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            return line.split("=", 1)[1].strip().strip('"')
                        if line.startswith("NAME="):
                            return line.split("=", 1)[1].strip().strip('"')
        except Exception:
            pass
        return "Linux CUPS"
    elif sys.platform == "win32":
        return "Windows Spooler"
    elif sys.platform == "darwin":
        return "macOS"
    return sys.platform


def _find_printer_accounting_script() -> str | None:
    """Locate the standalone PrinterAccounting.py script if present."""
    base_dirs = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "ComputerScripts"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ComputerScripts"),
        os.path.join(os.getcwd(), "ComputerScripts"),
        os.path.join(os.getcwd(), "..", "ComputerScripts"),
        os.path.join(os.path.expanduser("~"), "ComputerScripts"),
        "/var/mnt/shared-drive/2027/ComputerScripts",
    ]
    for d in base_dirs:
        p = os.path.join(d, "PrinterAccounting.py")
        if os.path.isfile(p):
            return os.path.abspath(p)
    return None


def _find_accounting_history_file() -> str | None:
    script_path = _find_printer_accounting_script()
    if script_path:
        h = os.path.join(os.path.dirname(script_path), "history.json")
        if os.path.isfile(h):
            return h
    home_history = os.path.expanduser("~/.fuji_printer_history.json")
    if os.path.isfile(home_history):
        return home_history
    return None


class _FastPrintWorker(QThread):
    """Background worker thread for asynchronous high-speed printing."""

    progress = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, job_type: str, target: str, payload_or_pdf: bytes | str, job_kwargs: dict, parent=None):
        super().__init__(parent)
        self.job_type = job_type  # "socket", "cups", "qprinter"
        self.target = target
        self.payload_or_pdf = payload_or_pdf
        self.kwargs = job_kwargs
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            if self.job_type == "socket":
                self._run_socket()
            elif self.job_type == "cups":
                self._run_cups()
            elif self.job_type == "qprinter":
                self._run_qprinter()
        except Exception as exc:
            self.finished.emit(False, str(exc))

    def _run_socket(self):
        ip = self.target
        port = int(self.kwargs.get("port", 9100))
        if isinstance(self.payload_or_pdf, str):
            if os.path.isfile(self.payload_or_pdf):
                with open(self.payload_or_pdf, "rb") as f:
                    data: bytes = f.read()
            else:
                data = self.payload_or_pdf.encode("latin-1")
        else:
            data = self.payload_or_pdf

        total = len(data)
        self.progress.emit(10, f"Connecting to {ip}:{port}...")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)
            s.settimeout(12)
            s.connect((ip, port))

            chunk_size = 65536
            sent = 0
            self.progress.emit(25, f"Streaming {total / 1024:.1f} KB to printer...")

            while sent < total:
                if self._is_cancelled:
                    raise RuntimeError("Print job cancelled by user.")
                chunk = data[sent:sent + chunk_size]
                s.sendall(chunk)
                sent += len(chunk)
                pct = 25 + int((sent / total) * 70)
                self.progress.emit(pct, f"Sending: {sent // 1024} / {total // 1024} KB ({pct}%)...")

            self.progress.emit(100, "Print job accepted by printer.")
        self.finished.emit(True, f"Sent successfully to {ip}:{port}!")

    def _run_cups(self):
        queue = self.target
        pdf_path = self.payload_or_pdf
        copies = self.kwargs.get("copies", 1)
        duplex = self.kwargs.get("duplex", "1-Sided")
        paper = self.kwargs.get("paper", "A4")
        color = self.kwargs.get("color", "Color")
        user = self.kwargs.get("user", "")

        is_color = (color == "Color")

        self.progress.emit(30, f"Spooling to CUPS queue '{queue}'...")
        cmd = ["lp", "-d", queue, "-n", str(copies)]

        if "Long Edge" in duplex:
            cmd.extend(["-o", "sides=two-sided-long-edge"])
        elif "Short Edge" in duplex:
            cmd.extend(["-o", "sides=two-sided-short-edge"])
        else:
            cmd.extend(["-o", "sides=one-sided"])

        if paper:
            cmd.extend(["-o", f"media={paper}"])

        if is_color:
            cmd.extend(["-o", "ColorModel=Color", "-o", "print-color-mode=color"])
        else:
            cmd.extend([
                "-o", "ColorModel=Gray",
                "-o", "ColorModel=Grayscale",
                "-o", "CNColorMode=mono",
                "-o", "print-color-mode=monochrome",
            ])

        if user:
            cmd.extend(["-o", f"job-originating-user-name={user}"])

        cmd.append(str(pdf_path))
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip() or f"CUPS returned code {res.returncode}")

        self.progress.emit(100, "Dispatched to CUPS spooler.")
        self.finished.emit(True, f"Sent to CUPS printer '{queue}'!\n{res.stdout.strip()}")

    def _run_qprinter(self):
        printer_name = self.target
        pdf_path = self.payload_or_pdf
        page_indices = self.kwargs.get("page_indices", [])
        copies = self.kwargs.get("copies", 1)
        color = self.kwargs.get("color", "Color")
        is_color = (color == "Color")

        self.progress.emit(15, f"Initializing {printer_name}...")
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPrinterName(printer_name)
        printer.setDocName(os.path.basename(str(pdf_path)))

        if is_color:
            printer.setColorMode(QPrinter.ColorMode.Color)
        else:
            printer.setColorMode(QPrinter.ColorMode.GrayScale)

        if printer.supportsMultipleCopies():
            printer.setCopyCount(copies)
            job_copies = 1
        else:
            job_copies = copies

        painter = QPainter()
        if not painter.begin(printer):
            raise RuntimeError(f"Could not open printer '{printer_name}' for writing.")

        try:
            doc = fitz.open(str(pdf_path))
            total_pages = doc.page_count
            pages_to_render = [p for p in page_indices if 0 <= p < total_pages] if page_indices else list(range(total_pages))
            total_steps = len(pages_to_render) * job_copies
            step_count = 0

            target_dpi = min(200, max(120, printer.resolution() // 2))
            zoom = target_dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            cs = fitz.csRGB if is_color else fitz.csGRAY
            fmt = QImage.Format.Format_RGB888 if is_color else QImage.Format.Format_Grayscale8

            first_page = True
            for _ in range(job_copies):
                for p_idx in pages_to_render:
                    if self._is_cancelled:
                        raise RuntimeError("Print job cancelled.")

                    step_count += 1
                    pct = int((step_count / max(1, total_steps)) * 95)
                    self.progress.emit(pct, f"Printing page {p_idx + 1} ({step_count}/{total_steps})...")

                    if not first_page:
                        printer.newPage()
                    first_page = False

                    page = doc[p_idx]
                    pix = page.get_pixmap(matrix=mat, colorspace=cs, alpha=False)
                    img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
                    pix = None

                    target_rect = QRectF(painter.viewport())
                    source_rect = QRectF(0, 0, img.width(), img.height())
                    scale = min(target_rect.width() / source_rect.width(), target_rect.height() / source_rect.height())
                    w = source_rect.width() * scale
                    h = source_rect.height() * scale
                    x = target_rect.x() + (target_rect.width() - w) / 2
                    y = target_rect.y() + (target_rect.height() - h) / 2
                    painter.drawImage(QRectF(x, y, w, h), img, source_rect)
            doc.close()
        finally:
            painter.end()

        self.progress.emit(100, "Sent to Windows Print Spooler.")
        self.finished.emit(True, f"Successfully spooled to '{printer_name}'.")


class _PdfPrintDialog(QDialog):
    """Modern, high-performance custom print dialog with live preview and Fuji Xerox accounting."""

    def __init__(self, doc_path: str, password: str = "", initial_pages: list[int] | None = None, parent=None):
        super().__init__(parent)
        self.doc_path = doc_path
        self.password = password
        self.initial_pages = initial_pages
        self.total_pages = 0
        self.current_preview_page = 0
        self.temp_slice_path = None
        self.worker = None

        self.setObjectName("print_dialog")
        self.setWindowTitle(f"Print — {os.path.basename(doc_path)}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
        self.setMinimumSize(960, 620)
        self.setModal(True)

        self._load_accounting_history()
        self._init_doc_metrics()
        self._build_ui()
        self._apply_dialog_stylesheet()
        self._populate_printers()

        QTimer.singleShot(0, self.showMaximized)

    def _init_doc_metrics(self):
        try:
            doc = fitz.open(self.doc_path)
            if self.password and doc.needs_pass:
                doc.authenticate(self.password)
            self.total_pages = doc.page_count
            doc.close()
        except Exception:
            self.total_pages = 1

    def _load_accounting_history(self):
        self.acct_user = "ali"
        self.acct_pin = "1688"
        self.acct_id = ""
        self.saved_ip = "172.31.2.14"
        self.saved_printer = ""
        self.saved_duplex = "2-Sided (Flip on Long Edge)"
        self.saved_paper = "A4"
        self.saved_color = "Color"

        h_file = _find_accounting_history_file()
        if h_file and os.path.isfile(h_file):
            try:
                with open(h_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.acct_user = data.get("user_id", self.acct_user)
                    self.acct_pin = data.get("passcode", self.acct_pin)
                    self.acct_id = data.get("account_id", self.acct_id)
                    self.saved_ip = data.get("printer_ip", self.saved_ip)
                    self.saved_printer = data.get("printer_queue", self.saved_printer)
                    self.saved_duplex = data.get("duplex", self.saved_duplex)
                    self.saved_paper = data.get("paper_size", self.saved_paper)
                    self.saved_color = data.get("color_mode", self.saved_color)
            except Exception:
                pass

    def _save_accounting_history(self):
        h_file = _find_accounting_history_file()
        if not h_file:
            script_path = _find_printer_accounting_script()
            if script_path:
                h_file = os.path.join(os.path.dirname(script_path), "history.json")
            else:
                h_file = os.path.expanduser("~/.fuji_printer_history.json")

        data = {
            "user_id": self.edit_acct_user.text().strip(),
            "passcode": self.edit_acct_pin.text().strip(),
            "account_id": self.edit_acct_id.text().strip(),
            "printer_ip": self.edit_ip.text().strip(),
            "printer_queue": self.cmb_printer.currentText(),
            "duplex": self.cmb_duplex.currentText(),
            "paper_size": self.cmb_paper.currentText(),
            "color_mode": self.cmb_color.currentText(),
            "copies": self.spin_copies.value(),
        }
        try:
            with open(h_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception:
            pass

    def _apply_dialog_stylesheet(self):
        self.setStyleSheet("""
            QDialog#print_dialog {
                background-color: #1E1F22;
                color: #F0F0F0;
            }
            QDialog#print_dialog QScrollArea {
                background: transparent;
                border: none;
            }
            QDialog#print_dialog QGroupBox {
                background-color: #26282D;
                border: 1px solid #3E4249;
                border-radius: 6px;
                margin-top: 14px;
                padding: 14px 14px 12px 14px;
                font-weight: 600;
                color: #A0A0A0;
            }
            QDialog#print_dialog QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 4px;
                background-color: #26282D;
                color: #CCCCCC;
            }
            QDialog#print_dialog QLineEdit,
            QDialog#print_dialog QComboBox,
            QDialog#print_dialog QSpinBox {
                background-color: #1E1F22;
                border: 1px solid #3E4249;
                border-radius: 4px;
                padding: 4px 8px;
                color: #F0F0F0;
                min-height: 26px;
            }
            QDialog#print_dialog QLineEdit:focus,
            QDialog#print_dialog QComboBox:focus,
            QDialog#print_dialog QSpinBox:focus {
                border: 1px solid #0078D4;
            }
            QDialog#print_dialog QPushButton {
                background-color: #383A40;
                border: 1px solid #4E5157;
                border-radius: 4px;
                padding: 4px 12px;
                color: #F0F0F0;
                min-height: 26px;
                font-size: 10pt;
            }
            QDialog#print_dialog QPushButton#nav_page_btn {
                min-height: 22px;
                max-height: 26px;
                padding: 2px 4px;
                font-size: 9pt;
            }
            QDialog#print_dialog QPushButton:hover {
                background-color: #43464D;
                border-color: #0078D4;
            }
            QDialog#print_dialog QPushButton#btn_primary {
                background-color: #0078D4;
                border: 1px solid #106EBE;
                color: #FFFFFF;
                font-weight: bold;
                font-size: 10.5pt;
            }
            QDialog#print_dialog QPushButton#btn_primary:hover {
                background-color: #106EBE;
            }
            QDialog#print_dialog QRadioButton,
            QDialog#print_dialog QCheckBox {
                color: #F0F0F0;
                spacing: 8px;
                background: transparent;
            }
            QDialog#print_dialog QLabel {
                background: transparent;
                color: #F0F0F0;
            }
            QDialog#print_dialog QScrollBar:vertical {
                width: 8px;
                background: transparent;
                margin: 0;
            }
            QDialog#print_dialog QScrollBar::handle:vertical {
                background: #4E5157;
                border-radius: 4px;
                min-height: 20px;
            }
            QDialog#print_dialog QScrollBar::handle:vertical:hover {
                background: #636770;
            }
            QDialog#print_dialog QScrollBar::add-line:vertical,
            QDialog#print_dialog QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

    def _build_ui(self):
        main_lay = QHBoxLayout(self)
        main_lay.setContentsMargins(14, 12, 14, 12)
        main_lay.setSpacing(14)

        # ── LEFT PANEL: Live Interactive Preview ──────────────────────
        left_box = QWidget()
        v_left = QVBoxLayout(left_box)
        v_left.setContentsMargins(0, 0, 0, 0)
        v_left.setSpacing(6)

        top_hdr = QHBoxLayout()
        lbl_doc = QLabel(f"<b>{os.path.basename(self.doc_path)}</b>")
        lbl_doc.setStyleSheet(f"font-size: 11pt; color: {TEXT_PRI};")
        top_hdr.addWidget(lbl_doc)
        top_hdr.addStretch()

        badge_txt = _get_os_badge()
        os_badge = QLabel(badge_txt)
        os_badge.setStyleSheet(f"background: #24283B; color: {ACCENT}; border: 1px solid {BORDER}; border-radius: 4px; padding: 3px 8px; font-weight: bold; font-size: 8.5pt;")
        top_hdr.addWidget(os_badge)
        v_left.addLayout(top_hdr)

        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_scroll.setStyleSheet("background: #121316; border: 1px solid #333842; border-radius: 8px;")

        self.lbl_preview_img = QLabel("Loading preview...")
        self.lbl_preview_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview_img.setStyleSheet("background: transparent;")
        self.preview_scroll.setWidget(self.lbl_preview_img)
        v_left.addWidget(self.preview_scroll, 1)

        # Navigation Bar: First, Prev, Page indicator, Next, Last
        nav_h = QHBoxLayout()
        nav_h.setContentsMargins(0, 2, 0, 2)
        nav_h.setSpacing(6)

        self.btn_first_page = QPushButton("<<")
        self.btn_first_page.setObjectName("nav_page_btn")
        self.btn_first_page.setFixedWidth(36)
        self.btn_first_page.setFixedHeight(26)
        self.btn_first_page.setToolTip("First Page (Page 1)")
        self.btn_first_page.clicked.connect(self._first_preview_page)
        nav_h.addWidget(self.btn_first_page)

        self.btn_prev_page = QPushButton("< Prev")
        self.btn_prev_page.setObjectName("nav_page_btn")
        self.btn_prev_page.setFixedWidth(56)
        self.btn_prev_page.setFixedHeight(26)
        self.btn_prev_page.setToolTip("Previous Page")
        self.btn_prev_page.clicked.connect(self._prev_preview_page)
        nav_h.addWidget(self.btn_prev_page)

        self.lbl_page_count = QLabel(f"Page 1 of {self.total_pages}")
        self.lbl_page_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_page_count.setStyleSheet(f"color: {ACCENT}; font-weight: bold; font-size: 9.5pt;")
        nav_h.addWidget(self.lbl_page_count, 1)

        self.btn_next_page = QPushButton("Next >")
        self.btn_next_page.setObjectName("nav_page_btn")
        self.btn_next_page.setFixedWidth(56)
        self.btn_next_page.setFixedHeight(26)
        self.btn_next_page.setToolTip("Next Page")
        self.btn_next_page.clicked.connect(self._next_preview_page)
        nav_h.addWidget(self.btn_next_page)

        self.btn_last_page = QPushButton(">>")
        self.btn_last_page.setObjectName("nav_page_btn")
        self.btn_last_page.setFixedWidth(36)
        self.btn_last_page.setFixedHeight(26)
        self.btn_last_page.setToolTip(f"Last Page (Page {self.total_pages})")
        self.btn_last_page.clicked.connect(self._last_preview_page)
        nav_h.addWidget(self.btn_last_page)

        v_left.addLayout(nav_h)
        main_lay.addWidget(left_box, 6)

        # ── RIGHT PANEL: Settings, Accounting & Print Actions ─────────
        right_container = QWidget()
        right_container.setMinimumWidth(440)
        right_container_layout = QVBoxLayout(right_container)
        right_container_layout.setContentsMargins(0, 0, 0, 0)
        right_container_layout.setSpacing(8)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        right_box = QWidget()
        right_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        v_right = QVBoxLayout(right_box)
        v_right.setContentsMargins(0, 0, 10, 0)
        v_right.setSpacing(12)

        # 1. Destination Group
        grp_dest = QGroupBox("Printer Destination")
        f_dest = QFormLayout(grp_dest)
        f_dest.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        f_dest.setVerticalSpacing(10)
        f_dest.setHorizontalSpacing(12)
        f_dest.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)

        self.cmb_printer = QComboBox()
        self.cmb_printer.setMinimumHeight(30)
        self.cmb_printer.currentIndexChanged.connect(self._on_printer_changed)
        f_dest.addRow("Printer:", self.cmb_printer)

        ip_row = QHBoxLayout()
        ip_row.setContentsMargins(0, 0, 0, 0)
        ip_row.setSpacing(8)
        self.edit_ip = QLineEdit(self.saved_ip)
        self.edit_ip.setMinimumHeight(30)
        self.edit_ip.setPlaceholderText("e.g. 172.31.2.14")
        ip_row.addWidget(self.edit_ip, 1)

        self.btn_test_ip = QPushButton("Test Port 9100")
        self.btn_test_ip.setMinimumHeight(30)
        self.btn_test_ip.setToolTip("Verify high-speed port connectivity")
        self.btn_test_ip.clicked.connect(self._test_printer_ip)
        ip_row.addWidget(self.btn_test_ip)

        self.row_ip_widget = QWidget()
        self.row_ip_widget.setLayout(ip_row)
        f_dest.addRow("Network IP:", self.row_ip_widget)

        v_right.addWidget(grp_dest)

        # 2. Accounting Credentials (Fuji Xerox ApeosPort / XSA)
        grp_acct = QGroupBox("Printer Accounting (Fuji Xerox ApeosPort / Auditron)")
        f_acct = QFormLayout(grp_acct)
        f_acct.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        f_acct.setVerticalSpacing(10)
        f_acct.setHorizontalSpacing(12)
        f_acct.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)

        self.edit_acct_user = QLineEdit(self.acct_user)
        self.edit_acct_user.setMinimumHeight(30)
        f_acct.addRow("User ID:", self.edit_acct_user)

        pin_row = QHBoxLayout()
        pin_row.setContentsMargins(0, 0, 0, 0)
        pin_row.setSpacing(8)
        self.edit_acct_pin = QLineEdit(self.acct_pin)
        self.edit_acct_pin.setMinimumHeight(30)
        self.edit_acct_pin.setEchoMode(QLineEdit.EchoMode.Password)
        pin_row.addWidget(self.edit_acct_pin, 1)

        self.btn_toggle_pin = QPushButton("Show")
        self.btn_toggle_pin.setFixedWidth(64)
        self.btn_toggle_pin.setMinimumHeight(30)
        self.btn_toggle_pin.setCheckable(True)
        self.btn_toggle_pin.toggled.connect(
            lambda checked: (
                self.edit_acct_pin.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password),
                self.btn_toggle_pin.setText("Hide" if checked else "Show")
            )
        )
        pin_row.addWidget(self.btn_toggle_pin)

        pin_widget = QWidget()
        pin_widget.setLayout(pin_row)
        f_acct.addRow("Passcode / PIN:", pin_widget)

        self.edit_acct_id = QLineEdit(self.acct_id)
        self.edit_acct_id.setMinimumHeight(30)
        self.edit_acct_id.setPlaceholderText("Optional Account ID")
        f_acct.addRow("Account ID:", self.edit_acct_id)

        script_path = _find_printer_accounting_script()
        if script_path:
            btn_launch_acct = QPushButton("Open Fuji Xerox Manager (Standalone)...")
            btn_launch_acct.setMinimumHeight(30)
            btn_launch_acct.clicked.connect(self._launch_standalone_accounting)
            f_acct.addRow("", btn_launch_acct)

        v_right.addWidget(grp_acct)

        # 3. Page Range Group
        grp_range = QGroupBox("Page Range")
        v_range = QVBoxLayout(grp_range)
        v_range.setSpacing(10)

        self.rad_all = QRadioButton(f"All Pages (1 - {self.total_pages})")
        self.rad_all.setMinimumHeight(24)
        self.rad_current = QRadioButton(f"Current Page (Page {self.current_preview_page + 1})")
        self.rad_current.setMinimumHeight(24)
        self.rad_custom = QRadioButton("Custom Range:")
        self.rad_custom.setMinimumHeight(24)

        self.bg_range = QButtonGroup(self)
        self.bg_range.addButton(self.rad_all, 0)
        self.bg_range.addButton(self.rad_current, 1)
        self.bg_range.addButton(self.rad_custom, 2)
        self.rad_all.setChecked(True)

        if self.initial_pages and len(self.initial_pages) > 0 and len(self.initial_pages) != self.total_pages:
            self.rad_custom.setChecked(True)

        v_range.addWidget(self.rad_all)
        v_range.addWidget(self.rad_current)

        custom_h = QHBoxLayout()
        custom_h.setContentsMargins(0, 0, 0, 0)
        custom_h.setSpacing(8)
        custom_h.addWidget(self.rad_custom)
        self.edit_range = QLineEdit()
        self.edit_range.setMinimumHeight(30)
        self.edit_range.setPlaceholderText("e.g. 1-3, 5, 8")
        if self.initial_pages:
            self.edit_range.setText(", ".join(str(p + 1) for p in self.initial_pages))
        custom_h.addWidget(self.edit_range, 1)
        v_range.addLayout(custom_h)

        quick_row = QHBoxLayout()
        quick_row.setContentsMargins(0, 0, 0, 0)
        quick_row.setSpacing(8)
        btn_odd = QPushButton("Odd Pages")
        btn_odd.setMinimumHeight(28)
        btn_odd.clicked.connect(self._set_range_odd)
        btn_even = QPushButton("Even Pages")
        btn_even.setMinimumHeight(28)
        btn_even.clicked.connect(self._set_range_even)
        quick_row.addWidget(btn_odd)
        quick_row.addWidget(btn_even)
        quick_row.addStretch()
        v_range.addLayout(quick_row)

        self.bg_range.idClicked.connect(lambda _: self._update_preview())
        self.edit_range.textChanged.connect(lambda _: self._update_preview() if self.rad_custom.isChecked() else None)

        v_right.addWidget(grp_range)

        # 4. Layout & Finishing
        grp_opts = QGroupBox("Layout && Finishing")
        f_opts = QFormLayout(grp_opts)
        f_opts.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        f_opts.setVerticalSpacing(10)
        f_opts.setHorizontalSpacing(12)
        f_opts.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)

        copies_h = QHBoxLayout()
        copies_h.setContentsMargins(0, 0, 0, 0)
        copies_h.setSpacing(10)
        self.spin_copies = QSpinBox()
        self.spin_copies.setMinimumHeight(30)
        self.spin_copies.setRange(1, 999)
        self.spin_copies.setValue(1)
        copies_h.addWidget(self.spin_copies)

        self.chk_collate = QCheckBox("Collate")
        self.chk_collate.setMinimumHeight(30)
        self.chk_collate.setChecked(True)
        copies_h.addWidget(self.chk_collate)
        copies_h.addStretch()

        copies_w = QWidget()
        copies_w.setLayout(copies_h)
        f_opts.addRow("Copies:", copies_w)

        self.cmb_duplex = QComboBox()
        self.cmb_duplex.setMinimumHeight(30)
        self.cmb_duplex.addItems(["1-Sided (Simplex)", "2-Sided (Flip on Long Edge)", "2-Sided (Flip on Short Edge)"])
        idx_dup = self.cmb_duplex.findText(self.saved_duplex)
        if idx_dup >= 0:
            self.cmb_duplex.setCurrentIndex(idx_dup)
        f_opts.addRow("Duplex:", self.cmb_duplex)

        self.cmb_paper = QComboBox()
        self.cmb_paper.setMinimumHeight(30)
        self.cmb_paper.addItems(["A4", "A3", "Letter", "Legal", "A5"])
        idx_paper = self.cmb_paper.findText(self.saved_paper)
        if idx_paper >= 0:
            self.cmb_paper.setCurrentIndex(idx_paper)
        f_opts.addRow("Paper Size:", self.cmb_paper)

        self.cmb_color = QComboBox()
        self.cmb_color.setMinimumHeight(30)
        self.cmb_color.addItems(["Color", "Black & White (Grayscale)"])
        idx_col = self.cmb_color.findText(self.saved_color)
        if idx_col >= 0:
            self.cmb_color.setCurrentIndex(idx_col)
        self.cmb_color.currentIndexChanged.connect(lambda _: self._update_preview())
        f_opts.addRow("Color Mode:", self.cmb_color)

        self.cmb_orient = QComboBox()
        self.cmb_orient.setMinimumHeight(30)
        self.cmb_orient.addItems(["Auto (Match PDF)", "Portrait", "Landscape"])
        self.cmb_orient.currentIndexChanged.connect(lambda _: self._update_preview())
        f_opts.addRow("Orientation:", self.cmb_orient)

        v_right.addWidget(grp_opts)
        v_right.addStretch()

        right_scroll.setWidget(right_box)
        right_container_layout.addWidget(right_scroll, 1)

        # 5. Fixed Bottom Action Row
        bottom_box = QWidget()
        bottom_layout = QVBoxLayout(bottom_box)
        bottom_layout.setContentsMargins(0, 2, 8, 2)
        bottom_layout.setSpacing(6)

        self.prog_bar = QProgressBar()
        self.prog_bar.setFixedHeight(12)
        self.prog_bar.setVisible(False)
        bottom_layout.addWidget(self.prog_bar)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {ACCENT}; font-size: 9pt;")
        bottom_layout.addWidget(self.lbl_status)

        act_h = QHBoxLayout()
        act_h.setContentsMargins(0, 0, 0, 0)
        act_h.setSpacing(10)
        act_h.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setMinimumHeight(34)
        self.btn_cancel.setFixedWidth(100)
        self.btn_cancel.clicked.connect(self.reject)
        act_h.addWidget(self.btn_cancel)

        self.btn_print = QPushButton("Print")
        self.btn_print.setObjectName("btn_primary")
        self.btn_print.setMinimumHeight(34)
        self.btn_print.clicked.connect(self._start_print_job)
        act_h.addWidget(self.btn_print)

        bottom_layout.addLayout(act_h)
        right_container_layout.addWidget(bottom_box)

        main_lay.addWidget(right_container, 5)

    def _populate_printers(self):
        self.cmb_printer.clear()
        self.cmb_printer.addItem("Direct Network Printer (Raw Port 9100 — JetDirect)", "socket")

        printers = QPrinterInfo.availablePrinters()
        for p in printers:
            p_name = p.printerName()
            self.cmb_printer.addItem(p_name, ("cups" if _is_linux() else "qprinter", p_name))

        if _is_linux():
            try:
                res = subprocess.run(["lpstat", "-e"], capture_output=True, text=True)
                for q in res.stdout.splitlines():
                    q = q.strip()
                    if q and not any(q in self.cmb_printer.itemText(i) for i in range(self.cmb_printer.count())):
                        self.cmb_printer.addItem(f"{q} (CUPS)", ("cups", q))
            except Exception:
                pass

        if self.saved_printer:
            idx = self.cmb_printer.findText(self.saved_printer)
            if idx >= 0:
                self.cmb_printer.setCurrentIndex(idx)

    def _on_printer_changed(self, idx: int):
        data = self.cmb_printer.itemData(idx)
        is_direct_socket = (data == "socket")
        self.row_ip_widget.setVisible(is_direct_socket)
        if is_direct_socket:
            self.btn_print.setText("Print")
        else:
            self.btn_print.setText("Send Print Job")

    def _test_printer_ip(self):
        ip = self.edit_ip.text().strip()
        if not ip:
            QMessageBox.warning(self, "Invalid IP", "Please specify a target printer IP.")
            return
        try:
            with socket.create_connection((ip, 9100), timeout=1.5):
                QMessageBox.information(self, "Online", f"Printer at {ip}:9100 is ONLINE and ready for Port 9100 printing.")
        except Exception as e:
            QMessageBox.critical(self, "Offline / Refused", f"Cannot connect to {ip}:9100:\n{e}")

    def _launch_standalone_accounting(self):
        script_path = _find_printer_accounting_script()
        if not script_path:
            QMessageBox.warning(self, "Not Found", "PrinterAccounting.py not found in ComputerScripts directory.")
            return
        self._save_accounting_history()
        subprocess.Popen([sys.executable, script_path, self.doc_path])

    def _set_range_odd(self):
        self.rad_custom.setChecked(True)
        odds = [str(p) for p in range(1, self.total_pages + 1, 2)]
        self.edit_range.setText(", ".join(odds))

    def _set_range_even(self):
        self.rad_custom.setChecked(True)
        evens = [str(p) for p in range(2, self.total_pages + 1, 2)]
        self.edit_range.setText(", ".join(evens))

    def _first_preview_page(self):
        if self.current_preview_page > 0:
            self.current_preview_page = 0
            self._update_preview()

    def _prev_preview_page(self):
        if self.current_preview_page > 0:
            self.current_preview_page -= 1
            self._update_preview()

    def _next_preview_page(self):
        if self.current_preview_page < self.total_pages - 1:
            self.current_preview_page += 1
            self._update_preview()

    def _last_preview_page(self):
        if self.current_preview_page < self.total_pages - 1:
            self.current_preview_page = self.total_pages - 1
            self._update_preview()

    def showEvent(self, event):
        super().showEvent(event)
        self.showMaximized()
        QTimer.singleShot(50, self._update_preview)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(50, self._update_preview)

    def _update_preview(self):
        self.rad_current.setText(f"Current Page (Page {self.current_preview_page + 1})")
        self.lbl_page_count.setText(f"Page {self.current_preview_page + 1} of {self.total_pages}")
        self.btn_first_page.setEnabled(self.current_preview_page > 0)
        self.btn_prev_page.setEnabled(self.current_preview_page > 0)
        self.btn_next_page.setEnabled(self.current_preview_page < self.total_pages - 1)
        self.btn_last_page.setEnabled(self.current_preview_page < self.total_pages - 1)

        try:
            doc = fitz.open(self.doc_path)
            if self.password and doc.needs_pass:
                doc.authenticate(self.password)

            if 0 <= self.current_preview_page < doc.page_count:
                page = doc[self.current_preview_page]
                vp = self.preview_scroll.viewport()
                avail_w = max(100, vp.width() - 32)
                avail_h = max(100, vp.height() - 32)

                pw = page.rect.width
                ph = page.rect.height
                orient = self.cmb_orient.currentText()
                if ("Landscape" in orient and pw < ph) or ("Portrait" in orient and pw > ph):
                    pw, ph = ph, pw

                zoom = min(avail_w / max(1.0, pw), avail_h / max(1.0, ph))
                zoom = max(0.05, zoom * 0.95)

                mat = fitz.Matrix(zoom, zoom)
                if "Landscape" in orient and page.rect.width < page.rect.height:
                    mat = mat.prerotate(90)
                elif "Portrait" in orient and page.rect.width > page.rect.height:
                    mat = mat.prerotate(90)

                pix = page.get_pixmap(matrix=mat, alpha=False)
                if "Black & White" in self.cmb_color.currentText() and pix.n != 1:
                    pix = fitz.Pixmap(fitz.csGRAY, pix)
                elif pix.n != 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                fmt = QImage.Format.Format_Grayscale8 if pix.n == 1 else QImage.Format.Format_RGB888
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
                doc.close()
                self.lbl_preview_img.setPixmap(QPixmap.fromImage(img))
                return
            doc.close()
        except Exception:
            pass
        self.lbl_preview_img.setText(f"Preview unavailable for Page {self.current_preview_page + 1}")

    def _resolve_target_pages(self) -> list[int]:
        if self.rad_all.isChecked():
            return list(range(self.total_pages))
        elif self.rad_current.isChecked():
            return [self.current_preview_page]
        else:
            txt = self.edit_range.text().strip()
            if not txt:
                raise ValueError("Custom page range is empty.")
            return parse_pages(txt, self.total_pages)

    def _start_print_job(self):
        try:
            pages = self._resolve_target_pages()
        except Exception as e:
            QMessageBox.warning(self, "Invalid Range", str(e))
            return

        if not pages:
            QMessageBox.warning(self, "Invalid Range", "No pages selected to print.")
            return

        self._save_accounting_history()

        p_idx = self.cmb_printer.currentIndex()
        p_data = self.cmb_printer.itemData(p_idx)

        copies = self.spin_copies.value()
        duplex = self.cmb_duplex.currentText()
        paper = self.cmb_paper.currentText()
        color = self.cmb_color.currentText()
        is_color = (color == "Color")
        is_grayscale = not is_color

        user = self.edit_acct_user.text().strip() or "none"
        pin = self.edit_acct_pin.text().strip()
        acct = self.edit_acct_id.text().strip()

        target_file = self.doc_path
        self.temp_slice_path = None

        # Prepare print document: convert to 100% DeviceGray or slice if custom pages / black & white selected
        need_temp = (is_grayscale or len(pages) != self.total_pages or pages != list(range(self.total_pages)))
        if need_temp:
            try:
                doc = fitz.open(self.doc_path)
                if self.password and doc.needs_pass:
                    doc.authenticate(self.password)
                sliced_doc = fitz.open()

                for p in pages:
                    if 0 <= p < doc.page_count:
                        if is_grayscale:
                            # Render page at 300 DPI in pure DeviceGray colorspace to guarantee zero color clicks
                            page = doc[p]
                            pix = page.get_pixmap(dpi=300, colorspace=fitz.csGRAY, alpha=False)
                            new_page = sliced_doc.new_page(width=page.rect.width, height=page.rect.height)
                            new_page.insert_image(page.rect, stream=pix.tobytes("jpeg"))
                        else:
                            sliced_doc.insert_pdf(doc, from_page=p, to_page=p)

                doc.close()

                fd, tmp_out = tempfile.mkstemp(prefix="pdfapps_print_", suffix=".pdf")
                os.close(fd)
                sliced_doc.save(tmp_out, garbage=4, deflate=True)
                sliced_doc.close()
                self.temp_slice_path = tmp_out
                target_file = tmp_out
            except Exception as ex:
                QMessageBox.critical(self, "Page Processing Error", f"Failed to prepare pages for printing:\n{ex}")
                return

        # Mode 1: Direct Socket Port 9100 (Instant Foxit Speed)
        if p_data == "socket":
            ip = self.edit_ip.text().strip()
            if not ip:
                QMessageBox.warning(self, "Missing IP", "Printer IP is required for Port 9100.")
                return

            try:
                with open(target_file, "rb") as f:
                    pdf_bytes = f.read()

                pjl = [
                    "\x1b%-12345X@PJL",
                    f'@PJL SET JOBATTR = "@JOAU={user}"',
                    f'@PJL SET JOBATTR = "@JOAP={pin}"',
                ]
                if acct:
                    pjl.append(f'@PJL SET JOBATTR = "@DAID={acct}"')
                pjl.append(f'@PJL SET JOBNAME = "{os.path.basename(self.doc_path)}"')
                pjl.append(f"@PJL SET COPIES = {copies}")
                pjl.append(f"@PJL SET PAPER = {paper}")

                if is_color:
                    pjl.append("@PJL SET COLORMODE = COLOR")
                    pjl.append("@PJL SET RENDERMODE = COLOR")
                else:
                    pjl.append("@PJL SET COLORMODE = MONO")
                    pjl.append("@PJL SET RENDERMODE = GRAYSCALE")
                    pjl.append("@PJL SET DATAMODE = GRAYSCALE")
                    pjl.append("@PJL SET COLOR = OFF")
                    pjl.append("@PJL SET PROCESSCOLOR = OFF")

                if "Long Edge" in duplex:
                    pjl.append("@PJL SET DUPLEX = ON\r\n@PJL SET BINDING = LONGEDGE")
                elif "Short Edge" in duplex:
                    pjl.append("@PJL SET DUPLEX = ON\r\n@PJL SET BINDING = SHORTEDGE")
                else:
                    pjl.append("@PJL SET DUPLEX = OFF")

                pjl.append("@PJL ENTER LANGUAGE = PDF\r\n")
                payload = "\r\n".join(pjl).encode("latin-1") + pdf_bytes + b"\r\n\x1b%-12345X"

                self._dispatch_worker("socket", ip, payload, {"port": 9100})
            except Exception as e:
                self._cleanup_temp_slice()
                QMessageBox.critical(self, "Setup Error", str(e))
                return

        # Mode 2: CUPS on Linux
        elif isinstance(p_data, tuple) and p_data[0] == "cups":
            queue_name = p_data[1]
            self._dispatch_worker(
                "cups",
                queue_name,
                target_file,
                {
                    "copies": copies,
                    "duplex": duplex,
                    "paper": paper,
                    "color": color,
                    "user": user,
                },
            )

        # Mode 3: Native Windows Spooler / QPrinter fallback
        else:
            printer_name = p_data[1] if isinstance(p_data, tuple) else self.cmb_printer.currentText()
            self._dispatch_worker(
                "qprinter",
                printer_name,
                target_file,
                {
                    "copies": copies,
                    "color": color,
                    "page_indices": pages if not self.temp_slice_path else None,
                },
            )

    def _dispatch_worker(self, job_type: str, target: str, payload_or_pdf, kwargs):
        self.btn_print.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.prog_bar.setValue(0)
        self.prog_bar.setVisible(True)

        self.worker = _FastPrintWorker(job_type, target, payload_or_pdf, kwargs, parent=self)

        def on_prog(pct, msg):
            self.prog_bar.setValue(pct)
            self.lbl_status.setText(msg)

        def on_done(success, msg):
            self.btn_print.setEnabled(True)
            self.btn_cancel.setEnabled(True)
            self.prog_bar.setVisible(False)
            self._cleanup_temp_slice()

            if success:
                QMessageBox.information(self, "Print Succeeded", msg)
                self.accept()
            else:
                QMessageBox.critical(self, "Print Error", msg)

        self.worker.progress.connect(on_prog)
        self.worker.finished.connect(on_done)
        self.worker.start()

    def _cleanup_temp_slice(self):
        if self.temp_slice_path and os.path.exists(self.temp_slice_path):
            with contextlib.suppress(Exception):
                os.unlink(self.temp_slice_path)
            self.temp_slice_path = None

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(1000)
        self._cleanup_temp_slice()
        super().closeEvent(event)


class PanelSearchPrintMixin(_Base):
    """Mixin for in-document text search bar and high-speed custom print dialog."""

    if TYPE_CHECKING:
        _current_path: str
        _pdf_password: str
        _fitz_doc: fitz.Document | None
        _search_bar: QWidget
        _search_input: QLineEdit
        _search_lbl: QLabel
        _search_results: list[tuple[int, list]]
        _search_current: int
        _search_debounce: QTimer
        _pending_search_query: str
        _canvas: _SelectCanvas
        _canvas_scroll: QScrollArea

    def _toggle_search(self):
        if self._search_bar.isVisible():
            self._close_search()
        else:
            self._search_bar.setVisible(True)
            self._search_input.setFocus()
            self._search_input.selectAll()

    def _close_search(self):
        self._search_bar.setVisible(False)
        self._search_results.clear()
        self._search_current = -1
        self._search_lbl.setText("")
        self._canvas.set_search_highlights([])
        self._canvas.update()

    def _on_search_text_changed(self, text: str):
        query = text.strip()
        if not query:
            self._search_debounce.stop()
            self._pending_search_query = ""
            self._search_results.clear()
            self._search_current = -1
            self._search_lbl.setText("")
            self._canvas.set_search_highlights([])
            self._canvas.update()
            return
        self._pending_search_query = query
        self._search_debounce.start()

    def _run_pending_search(self):
        query = self._pending_search_query
        if query:
            self._do_search(query)

    def _do_search(self, query: str):
        doc = self._fitz_doc
        if doc is None or getattr(doc, "is_closed", False):
            return
        results = []
        try:
            for page_idx in range(doc.page_count):
                page = doc[page_idx]
                rects = page.search_for(query)
                if rects:
                    results.append((page_idx, rects))
        except (RuntimeError, ValueError):
            return
        self._search_results = results
        total = sum(len(rects) for _, rects in results)
        if total == 0:
            self._search_lbl.setText("0 / 0")
            self._search_current = -1
            self._canvas.set_search_highlights([])
            self._canvas.update()
            return
        self._search_current = 0
        self._update_search_highlight()

    def _search_next(self):
        if not self._search_results:
            text = self._search_input.text().strip()
            if text:
                self._do_search(text)
            return
        total = sum(len(rects) for _, rects in results) if (results := self._search_results) else 0
        if total == 0:
            return
        self._search_current = (self._search_current + 1) % total
        self._update_search_highlight()

    def _search_prev(self):
        if not self._search_results:
            return
        total = sum(len(rects) for _, rects in self._search_results)
        if total == 0:
            return
        self._search_current = (self._search_current - 1) % total
        self._update_search_highlight()

    def _update_search_highlight(self):
        total = sum(len(rects) for _, rects in self._search_results)
        self._search_lbl.setText(f"{self._search_current + 1} / {total}")
        all_highlights = []
        flat_idx = 0
        current_page = 0
        for page_idx, rects in self._search_results:
            for rect in rects:
                all_highlights.append((page_idx, rect))
                if flat_idx == self._search_current:
                    current_page = page_idx
                flat_idx += 1
        self._canvas.set_search_highlights(all_highlights, self._search_current)
        if current_page < len(self._canvas._entries):
            entry = self._canvas._entries[current_page]
            _, cur_rect = all_highlights[self._search_current]
            z = self._canvas._zoom
            y_target = entry.y_off + int(cur_rect.y0 * z) - 100
            sb = self._canvas_scroll.verticalScrollBar()
            if sb:
                sb.setValue(max(0, y_target))
        self._canvas.update()

    def _reset_search_state(self):
        self._search_debounce.stop()
        self._pending_search_query = ""
        self._close_search()

    def _cancel_print_job(self):
        pass

    def _print_pdf(self, page_indices: list[int] | None = None):
        """Invoke the high-speed custom PDFApps Print Dialog."""
        doc = self._fitz_doc
        if doc is None or getattr(doc, "is_closed", False):
            return
        if not self._current_path or not os.path.isfile(self._current_path):
            return

        dlg = _PdfPrintDialog(
            doc_path=self._current_path,
            password=getattr(self, "_pdf_password", ""),
            initial_pages=page_indices,
            parent=self,
        )
        dlg.exec()