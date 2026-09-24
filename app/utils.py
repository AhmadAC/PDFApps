# app\utils.py

"""PDFApps – utility functions and reusable UI factory helpers."""

# app/utils.py
import contextlib
import logging
import logging.handlers
import os
import subprocess
import sys
import traceback

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPalette, QColor, QPainter
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QFileDialog, QApplication,
)
import qtawesome as qta

from app.i18n import t
from app.constants import (
    ACCENT, DESKTOP,
    BG_BASE, BG_CARD, BG_INPUT,
    TEXT_PRI,
    SUCCESS_DARK, SUCCESS_LIGHT,
    _LA, _LB, _LC, _LI, _LN, _LO, _LP,
)


def resource_path(rel):
    """Returns the correct path both in dev and in PyInstaller exe."""
    base = getattr(sys, '_MEIPASS',
                   os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


def reveal_file(path: str) -> None:
    """Open the OS file manager and highlight the given file when possible.
    Falls back to opening the parent folder on Linux."""
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])
    except OSError:
        pass


def open_folder(path: str) -> None:
    """Open the folder containing the given file (or the folder itself)."""
    try:
        folder = os.path.dirname(path) if os.path.isfile(path) else path
        if sys.platform == "win32":
            subprocess.Popen(["explorer", os.path.normpath(folder)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except OSError:
        pass


def format_size_localized(value: float, decimals: int = 1) -> str:
    """Format a numeric value using the system locale's decimal separator.

    DE/FR/IT/ES typically use comma; EN/PT use period. Falls back to a plain
    ``f"{value:.{decimals}f}"`` (period) if QLocale is unavailable, e.g. in
    headless test environments where the Qt plugin failed to load.
    """
    try:
        from PySide6.QtCore import QLocale
        return QLocale.system().toString(float(value), 'f', decimals)
    except Exception:
        return f"{value:.{decimals}f}"


def _make_palette(dark: bool) -> QPalette:
    p = QPalette()
    if dark:
        p.setColor(QPalette.ColorRole.Window,          QColor(BG_BASE))
        p.setColor(QPalette.ColorRole.WindowText,      QColor(TEXT_PRI))
        p.setColor(QPalette.ColorRole.Base,            QColor(BG_INPUT))
        p.setColor(QPalette.ColorRole.AlternateBase,   QColor(BG_CARD))
        p.setColor(QPalette.ColorRole.Text,            QColor(TEXT_PRI))
        p.setColor(QPalette.ColorRole.Button,          QColor("#1E2235"))
        p.setColor(QPalette.ColorRole.ButtonText,      QColor(TEXT_PRI))
        p.setColor(QPalette.ColorRole.Highlight,       QColor(ACCENT))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    else:
        p.setColor(QPalette.ColorRole.Window,          QColor(_LB))
        p.setColor(QPalette.ColorRole.WindowText,      QColor(_LP))
        p.setColor(QPalette.ColorRole.Base,            QColor(_LI))
        p.setColor(QPalette.ColorRole.AlternateBase,   QColor(_LN))
        p.setColor(QPalette.ColorRole.Text,            QColor(_LP))
        p.setColor(QPalette.ColorRole.Button,          QColor(_LC))
        p.setColor(QPalette.ColorRole.ButtonText,      QColor(_LP))
        p.setColor(QPalette.ColorRole.Highlight,       QColor(_LA))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    return p


def _paint_bg(widget: QWidget) -> None:
    """Makes QWidget subclasses honour 'background:' in the stylesheet."""
    from PySide6.QtWidgets import QStyleOption, QStyle
    opt = QStyleOption()
    opt.initFrom(widget)
    p = QPainter(widget)
    widget.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, p, widget)


def parse_pages(text: str, total: int) -> list:
    _MAX_PAGES = 100_000
    pages: list = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a = a.strip(); b = b.strip()
            if not a and not b:
                raise ValueError(
                    t("tool.err.bad_page_input", text=part))
            try:
                a_int = int(a) if a else 1
                b_int = int(b) if b else total
            except ValueError as exc:
                raise ValueError(
                    t("tool.err.bad_page_input", text=part)) from exc
        else:
            try:
                a_int = b_int = int(part)
            except ValueError as exc:
                raise ValueError(
                    t("tool.err.bad_page_input", text=part)) from exc
        if "-" in part:
            if b_int - a_int + 1 > _MAX_PAGES:
                raise ValueError(
                    f"Range too large: {a_int}-{b_int} (max {_MAX_PAGES})")
            pages.extend(range(a_int - 1, b_int))
        else:
            pages.append(a_int - 1)
        if len(pages) > _MAX_PAGES:
            raise ValueError(f"Too many pages selected (max {_MAX_PAGES})")
    invalid = [p for p in pages if p < 0 or p >= total]
    if invalid:
        bad = sorted({(p + 1) if p >= 0 else 0 for p in invalid})
        raise ValueError(
            f"Pages out of range: {bad}  (valid: 1-{total})")
    return sorted(set(pages))


_IMAGE_PIXEL_LIMIT = 100_000_000


def check_image_size(path: str) -> tuple[bool, int, int]:
    """Return ``(ok, width, height)`` for the image at ``path``."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            w, h = img.size
    except Exception:
        return True, 0, 0
    return (w * h) <= _IMAGE_PIXEL_LIMIT, w, h


def pick_pdfs(parent: QWidget) -> list:
    paths, _ = QFileDialog.getOpenFileNames(
        parent, t("btn.select_pdfs"), DESKTOP, t("file_filter.pdf"))
    return paths


def pick_folder(parent: QWidget) -> str:
    return QFileDialog.getExistingDirectory(parent, t("btn.select_folder"))


_SECONDARY_PWD_ATTRS = ("_pwd_map", "_written_pwd")


def wipe_pdf_password(obj) -> None:
    """Best-effort wipe of the cached PDF password attribute on ``obj``."""
    obj._pdf_password = ""
    for name in _SECONDARY_PWD_ATTRS:
        cache = getattr(obj, name, None)
        if isinstance(cache, dict):
            cache.clear()


def prompt_pdf_password(path: str, parent=None) -> tuple[bool, str]:
    """Open the PDF and, if encrypted, prompt the user for a password."""
    try:
        import fitz
        doc = fitz.open(path)
    except Exception:
        return True, ""
    try:
        if not doc.needs_pass:
            return True, ""
        from app.editor.dialogs import _PdfPasswordDialog
        from app.pdf_password import authenticate_fitz
        from PySide6.QtWidgets import QDialog
        wrong = False
        while True:
            dlg = _PdfPasswordDialog(os.path.basename(path), wrong=wrong, parent=parent)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return False, ""
            winner = authenticate_fitz(doc, dlg.password())
            if winner is not None:
                return True, winner
            wrong = True
    finally:
        doc.close()


# ── UI factory helpers ────────────────────────────────────────────────────────

def ToolHeader(icon_name: str, title: str, desc: str) -> QWidget:
    """Fixed header at the top of each tool."""
    w = QWidget(); w.setObjectName("tool_header")
    h = QHBoxLayout(w); h.setContentsMargins(24, 14, 24, 14); h.setSpacing(12)
    ico = QPushButton()
    ico.setIcon(qta.icon(icon_name, color=ACCENT))
    ico.setIconSize(QSize(22, 22))
    ico.setFixedSize(36, 36)
    ico.setObjectName("th_icon")
    ico.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    col = QVBoxLayout(); col.setSpacing(3)
    t_lbl = QLabel(title); t_lbl.setObjectName("th_title")
    t_lbl.setWordWrap(True)
    d = QLabel(desc);  d.setObjectName("th_desc")
    d.setWordWrap(True)
    col.addWidget(t_lbl); col.addWidget(d)
    h.addWidget(ico, 0); h.addLayout(col, 1)
    w.setMinimumWidth(0)
    return w


def _action_progress_stylesheet(dark: bool) -> str:
    """Theme-aware stylesheet for the ActionBar's thin progress strip."""
    if dark:
        return (
            f"QProgressBar {{ background: {BG_INPUT}; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}"
        )
    return (
        f"QProgressBar {{ background: {_LO}; border-radius: 3px; }}"
        f"QProgressBar::chunk {{ background: {_LA}; border-radius: 3px; }}"
    )


def ActionBar(btn_text: str, slot) -> tuple:
    """Bottom bar with primary action button and optional progress bar."""
    from PySide6.QtWidgets import QProgressBar
    bar = QWidget(); bar.setObjectName("action_bar")
    v = QVBoxLayout(bar); v.setContentsMargins(20, 8, 20, 8); v.setSpacing(6)
    progress = QProgressBar(); progress.setVisible(False)
    progress.setFixedHeight(6); progress.setTextVisible(False)
    progress.setObjectName("action_progress")
    progress.setStyleSheet(_action_progress_stylesheet(is_dark()))
    v.addWidget(progress)
    h = QHBoxLayout(); h.setContentsMargins(0, 0, 0, 0)
    h.addStretch()
    btn = QPushButton(btn_text); btn.setObjectName("btn_primary")
    btn.setMinimumWidth(200); btn.setFixedHeight(42)
    btn.clicked.connect(slot)
    h.addWidget(btn)
    v.addLayout(h)
    bar.progress = progress

    def _update_theme(dark: bool) -> None:
        try:
            progress.setStyleSheet(_action_progress_stylesheet(dark))
        except RuntimeError:
            pass
    bar.update_theme = _update_theme
    return bar, btn


def section(text: str) -> QLabel:
    lbl = QLabel(text.upper()); lbl.setObjectName("section_lbl")
    return lbl


def info_lbl() -> QLabel:
    lbl = QLabel(""); lbl.setObjectName("info_lbl")
    return lbl


def primary_btn(text: str) -> QPushButton:
    b = QPushButton(text); b.setObjectName("btn_primary")
    b.setFixedHeight(38); return b


def danger_btn(text: str) -> QPushButton:
    b = QPushButton(text); b.setObjectName("btn_danger"); return b


def scrolled(widget: QWidget) -> QScrollArea:
    sa = QScrollArea(); sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame); sa.setWidget(widget)
    return sa


# ── Compression helper ────────────────────────────────────────────────────────

class CancelledError(Exception):
    """Raised when the user cancels a long-running operation."""


class WrongPasswordError(Exception):
    """Raised when an encrypted PDF cannot be unlocked with the supplied password."""


_COMPRESS_LEVELS = {
    "extreme":     {"dpi": 72,  "quality": 40, "grayscale": True},
    "recommended": {"dpi": 150, "quality": 65, "grayscale": False},
    "low":         {"dpi": 300, "quality": 80, "grayscale": False},
}

_GS_CACHE: tuple[bool, str | None] = (False, None)


def _find_gs():
    """Find Ghostscript executable."""
    global _GS_CACHE
    if _GS_CACHE[0]:
        return _GS_CACHE[1]
    import shutil as _sh, platform as _pl
    names = (["gswin64c", "gswin32c", "gs"]
             if _pl.system() == "Windows" else ["gs"])
    for n in names:
        p = _sh.which(n)
        if p and os.path.isfile(p):
            _GS_CACHE = (True, os.path.abspath(p))
            return _GS_CACHE[1]
    if _pl.system() == "Windows":
        import glob
        for pattern in [r"C:\Program Files\gs\gs*\bin\gswin64c.exe",
                        r"C:\Program Files\gs\gs*\bin\gswin32c.exe",
                        r"C:\Program Files (x86)\gs\gs*\bin\gswin32c.exe"]:
            matches = sorted(glob.glob(pattern), reverse=True)
            for p in matches:
                if os.path.isfile(p):
                    _GS_CACHE = (True, os.path.abspath(p))
                    return _GS_CACHE[1]
    _GS_CACHE = (True, None)
    return None


def _win_short_path(path: str) -> str:
    """On Windows, try to map ``path`` to its 8.3 short form."""
    if sys.platform != "win32" or not path:
        return path
    if not os.path.exists(path):
        return path
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(512)
        n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 512)
        if n and buf.value:
            return buf.value
    except Exception:
        pass
    return path


def _is_valid_pdf(path: str) -> bool:
    """Return True if ``path`` is a readable, non-empty PDF with pages."""
    try:
        if not path or not os.path.isfile(path) or os.path.getsize(path) <= 0:
            return False
    except OSError:
        return False
    try:
        import fitz
        doc = fitz.open(path)
        try:
            if doc.needs_pass:
                return False
            return doc.page_count > 0
        finally:
            doc.close()
    except Exception:
        pass
    try:
        from pypdf import PdfReader
        r = PdfReader(path)
        if r.is_encrypted:
            return False
        return len(r.pages) > 0
    except Exception:
        return False


def _compress_pdf(src: str, dst: str, level: str = "recommended",
                  progress_fn=None, password: str | None = None) -> tuple:
    import tempfile, shutil, subprocess, time

    cfg     = _COMPRESS_LEVELS.get(level, _COMPRESS_LEVELS["recommended"])
    dpi     = cfg["dpi"]
    quality = cfg["quality"]
    gray    = cfg["grayscale"]
    before  = os.path.getsize(src)
    temps: list = []

    encrypted = False
    authed = False
    try:
        import fitz
        from app.pdf_password import authenticate_fitz
        probe = fitz.open(src)
        try:
            encrypted = probe.needs_pass
            if encrypted and password:
                winner = authenticate_fitz(probe, password)
                authed = winner is not None
                if winner is not None:
                    password = winner
        finally:
            probe.close()
    except Exception:
        try:
            from app.pdf_password import decrypt_pypdf
            from pypdf import PdfReader
            pr = PdfReader(src)
            encrypted = pr.is_encrypted
            if encrypted and password:
                winner = decrypt_pypdf(pr, password)
                authed = winner is not None
                if winner is not None:
                    password = winner
        except Exception:
            encrypted = False
    if encrypted and not authed:
        raise WrongPasswordError(t("tool.err.wrong_password"))
    if not encrypted:
        password = None

    def _prog(stage, cur=0, tot=0):
        if progress_fn and progress_fn(stage, cur, tot) is False:
            for _p in temps:
                try: os.unlink(_p)
                except Exception: pass
            raise CancelledError()

    # ── Pass A : Ghostscript ─────────────────────────────────────────────
    _prog("passA")
    gs = _find_gs()
    p = None
    if gs:
        try:
            presets = {
                "extreme":     "/screen",
                "recommended": "/ebook",
                "low":         "/printer",
            }
            fd, p = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
            cmd = [
                gs, "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                f"-dPDFSETTINGS={presets[level]}",
                "-dNOPAUSE", "-dQUIET", "-dBATCH",
                "-dDownsampleColorImages=true",
                "-dDownsampleGrayImages=true",
                "-dDownsampleMonoImages=true",
                f"-dColorImageResolution={dpi}",
                f"-dGrayImageResolution={dpi}",
                f"-dMonoImageResolution={max(dpi, 150)}",
                "-dColorImageDownsampleThreshold=1.0",
                "-dGrayImageDownsampleThreshold=1.0",
                "-dColorImageDownsampleType=/Bicubic",
                "-dGrayImageDownsampleType=/Bicubic",
            ]
            if gray:
                cmd += ["-sColorConversionStrategy=Gray",
                        "-dProcessColorModel=/DeviceGray",
                        "-dOverrideICC"]
            if password:
                cmd += [f"-sPDFPassword={password}"]
            _src_for_gs = _win_short_path(src)
            _out_for_gs = _win_short_path(p)
            cmd += [f"-sOutputFile={_out_for_gs}", _src_for_gs]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            deadline = time.monotonic() + 120
            cancelled = False
            try:
                while True:
                    if proc.poll() is not None:
                        break
                    if progress_fn and progress_fn("passA", 0, 0) is False:
                        cancelled = True
                        break
                    if time.monotonic() > deadline:
                        break
                    time.sleep(0.2)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try: proc.wait(timeout=2)
                        except subprocess.TimeoutExpired: pass
            if cancelled:
                try: os.unlink(p)
                except Exception: pass
                raise CancelledError()
            if proc.returncode == 0 and _is_valid_pdf(p):
                temps.append(p)
            else:
                try: os.unlink(p)
                except Exception: pass
        except CancelledError:
            raise
        except Exception:
            if p:
                try: os.unlink(p)
                except Exception: pass

    # ── Pass B : PyMuPDF ─────────────────────────────────────────────────
    _prog("passB_setup")
    doc = None
    p = None
    try:
        import fitz
        doc = fitz.open(src)
        if doc.needs_pass:
            if not (password and doc.authenticate(password)):
                raise WrongPasswordError(t("tool.err.wrong_password"))

        try:
            doc.scrub(metadata=True, xml_metadata=True,
                      thumbnails=True, attached_files=True)
        except Exception:
            pass

        _prog("passB_setup")

        try:
            doc.subset_fonts()
        except Exception:
            pass

        _prog("passB_images", 0, 1)
        try:
            doc.rewrite_images(
                dpi_threshold=dpi + 10,
                dpi_target=dpi,
                quality=quality,
                lossy=True,
                lossless=True,
                bitonal=True,
                color=True,
                gray=True,
                set_to_gray=gray,
            )
        except Exception:
            pass
        _prog("passB_images", 1, 1)

        _prog("passB_save")
        fd, p = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
        save_kw = dict(garbage=4, deflate=True, deflate_fonts=True, clean=True)
        try:
            doc.save(p, **save_kw, use_objstms=True)
        except TypeError:
            doc.save(p, **save_kw)
        if _is_valid_pdf(p):
            temps.append(p)
            p = None
    except CancelledError:
        raise
    except WrongPasswordError:
        raise
    except Exception:
        pass
    finally:
        if doc is not None:
            try: doc.close()
            except Exception: pass
        if p:
            try: os.unlink(p)
            except Exception: pass

    # ── Pass C : pikepdf ─────────────────────────────────────────────────
    _prog("passC")
    pdf = None
    p = None
    try:
        import pikepdf
        best_so_far = min(temps, key=lambda f: os.path.getsize(f)) if temps else src
        open_kw = {"password": password} if (best_so_far == src and password) else {}
        pdf = pikepdf.open(best_so_far, **open_kw)
        fd, p = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
        _prog("passC")
        pdf.save(p,
                 object_stream_mode=pikepdf.ObjectStreamMode.generate,
                 compress_streams=True,
                 recompress_flate=True,
                 linearize=True)
        if _is_valid_pdf(p):
            temps.append(p)
            p = None
    except CancelledError:
        if pdf is not None:
            try: pdf.close()
            except Exception: pass
            pdf = None
        for _p in temps:
            try: os.unlink(_p)
            except Exception: pass
        raise
    except Exception:
        pass
    finally:
        if pdf is not None:
            with contextlib.suppress(Exception):
                pdf.close()
        if p:
            with contextlib.suppress(Exception):
                os.unlink(p)

    if not temps:
        raise RuntimeError(t("tool.compress.deps_missing"))

    best      = min(temps, key=lambda p: os.path.getsize(p))
    best_size = os.path.getsize(best)

    for _p in temps:
        if _p != best:
            try: os.unlink(_p)
            except Exception: pass

    if best_size >= before:
        with contextlib.suppress(Exception):
            os.unlink(best)
        raise ValueError(t("tool.compress.no_gain_detail",
                           before=f"{before/1024:.0f}",
                           after=f"{best_size/1024:.0f}"))

    dst_dir = os.path.dirname(dst) or "."
    try:
        os.replace(best, dst)
    except OSError:
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=dst_dir)
        os.close(fd)
        try:
            shutil.copyfile(best, tmp)
            os.replace(tmp, dst)
        except Exception:
            with contextlib.suppress(Exception):
                os.unlink(tmp)
            raise
        with contextlib.suppress(Exception):
            os.unlink(best)
    return before, best_size


def is_dark() -> bool:
    """Return the user's current dark-mode preference."""
    try:
        import json
        from app.i18n import _CONFIG_PATH
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return bool(json.load(f).get("dark_mode", True))
    except Exception:
        return True


def error_color() -> str:
    return "#F87171" if is_dark() else "#DC2626"


def success_color(dark: bool | None = None) -> str:
    if dark is None:
        dark = is_dark()
    return SUCCESS_DARK if dark else SUCCESS_LIGHT


def result_label_style(dark: bool | None = None) -> str:
    return (f"font-weight:600; font-size:11pt; color:{success_color(dark)}; "
            "background:transparent; padding:10px 4px;")


# ─────────────────────────────────────────────────────────────────────────────
# Logging + user-friendly error dialogs
# ─────────────────────────────────────────────────────────────────────────────

_logging_initialised = False


def _log_path() -> str:
    """Return the path to the rotating log file (next to the user config)."""
    from app.i18n import _CONFIG_PATH
    return os.path.join(os.path.dirname(_CONFIG_PATH), "pdfapps.log")


def setup_logging() -> None:
    """Configure a rotating file logger and a console logger (stderr/stdout).
    Idempotent — safe to call multiple times."""
    global _logging_initialised
    if _logging_initialised:
        return
    _logging_initialised = True
    try:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s"
        )
        root = logging.getLogger()
        level = logging.DEBUG if os.environ.get("PDFAPPS_DEBUG") or os.environ.get("DEBUG") else logging.INFO
        root.setLevel(level)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        root.addHandler(console_handler)

        log_path = _log_path()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root.addHandler(file_handler)
    except Exception:
        pass


def show_error(parent, exc: BaseException) -> None:
    """Show a translated, friendly error dialog with collapsible technical
    details, log the full error with traceback to stderr and log file,
    and automatically copy the complete error details to the PySide6 clipboard."""
    from PySide6.QtWidgets import QMessageBox

    if isinstance(exc, WrongPasswordError):
        logging.warning("Wrong PDF password: %s", exc)
        with contextlib.suppress(Exception):
            sys.stderr.write(f"\n[PDFApps WARNING] Wrong PDF password: {exc}\n")
            sys.stderr.flush()
        
        err_msg = str(exc) or t("tool.err.wrong_password")
        
        with contextlib.suppress(Exception):
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setText(err_msg)

        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(t("msg.warning"))
        box.setText(err_msg)
        box.exec()
        return

    logging.error(
        "UI error surfaced: %s: %s",
        type(exc).__name__, exc, exc_info=exc,
    )
    
    try:
        tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        err_text = "".join(tb_lines)
    except Exception:
        err_text = f"{type(exc).__name__}: {exc}"

    with contextlib.suppress(Exception):
        sys.stderr.write(f"\n[PDFApps ERROR]\n{err_text}\n")
        sys.stderr.flush()

    with contextlib.suppress(Exception):
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(err_text)
            sys.stderr.write("Error successfully copied to clipboard.\n")
            sys.stderr.flush()

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(t("msg.error"))
    box.setText(t("msg.unexpected") + "\n\n(Error details have been copied to your clipboard)")
    box.setDetailedText(err_text)
    box.exec()