"""PDFApps – entry point."""
# pdfapps.py
import argparse
import ctypes
import logging
import os
import sys
from pathlib import Path

# Ensure the project directory is always the first lookup path in sys.path,
# preventing ModuleNotFoundError when Windows launches the script from another folder.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtGui import QIcon, QImageReader
from PySide6.QtWidgets import QApplication, QMessageBox

try:
    # Defensive import — surfaces the missing-dependency dialog before
    # the rest of app.* drags pypdf in via tools/*.py and crashes with
    # an opaque traceback. The names are intentionally unused here.
    from pypdf import PdfReader, PdfWriter  # noqa: F401
except ImportError:
    _app = QApplication(sys.argv)
    QMessageBox.critical(None, "Missing dependency",
                         "Install the pypdf library:\n\npip install pypdf")
    sys.exit(1)

try:
    import fitz  # PyMuPDF — used by viewer render, editor, most tools
    del fitz
except ImportError:
    _app = QApplication(sys.argv)
    QMessageBox.critical(None, "Missing dependency",
                         "Install PyMuPDF:\n\npip install pymupdf")
    sys.exit(1)

from app.constants import APP_VERSION
from app.window import MainWindow
from app.styles import STYLE, STYLE_LIGHT
from app.utils import _make_palette, setup_logging


def _ensure_icons():
    """Ensure icon_512.png and icon.ico are generated and in sync with pdfapps.svg."""
    ico_path = PROJECT_ROOT / "icon.ico"
    png_path = PROJECT_ROOT / "icon_512.png"
    svg_path = PROJECT_ROOT / "pdfapps.svg"

    if not svg_path.is_file():
        return

    needs_generation = False
    if not ico_path.is_file() or not png_path.is_file():
        needs_generation = True
    else:
        try:
            svg_mtime = svg_path.stat().st_mtime
            if svg_mtime > ico_path.stat().st_mtime or svg_mtime > png_path.stat().st_mtime:
                needs_generation = True
        except Exception:
            pass

    if needs_generation:
        try:
            from generate_icons import generate_all_icons
            generate_all_icons(PROJECT_ROOT)
        except Exception as exc:
            logging.getLogger(__name__).warning("Icon auto-generation skipped: %s", exc)


def _excepthook(exc_type, exc_value, exc_traceback):
    """Route uncaught exceptions through the logging framework so
    PyInstaller --windowed builds still surface crashes in the log
    file instead of silently swallowing them on closed stderr.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.getLogger(__name__).critical(
        "Uncaught exception",
        exc_info=(exc_type, exc_value, exc_traceback),
    )
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(
                None, "Unexpected error",
                f"{exc_type.__name__}: {exc_value}\n\nDetails logged.",
            )
    except Exception:
        pass


def _load_dark_pref() -> bool:
    try:
        import json
        from app.i18n import _CONFIG_PATH
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("dark_mode", True)
    except Exception:
        return True


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the PDFApps command-line."""
    parser = argparse.ArgumentParser(
        prog="pdfapps",
        description="PDFApps — fast desktop PDF editor.",
        add_help=True,
    )
    parser.add_argument(
        "files", nargs="*", metavar="PDF",
        help=("One or more PDF files to open. Each file opens in its "
              "own tab. Defaults to the welcome screen."),
    )
    parser.add_argument(
        "-v", "--version", action="version",
        version=f"PDFApps {APP_VERSION}",
    )
    return parser.parse_args(argv)


def main():
    # Fix Windows Taskbar grouping: Assign a unique AppUserModelID so Windows
    # displays PDFApps's custom icon rather than grouping it under pythonw.exe.
    if sys.platform == "win32":
        try:
            myappid = "pdfapps.desktop.editor.release"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    setup_logging()
    print("[PDFApps] Initializing application...")
    sys.excepthook = _excepthook
    args = _parse_args(sys.argv[1:])

    pdf_files = [
        os.path.abspath(f) for f in (args.files or [])
        if os.path.isfile(f) and f.lower().endswith(".pdf")
    ]
    if pdf_files:
        from app.single_instance import send_to_existing
        if send_to_existing(pdf_files):
            sys.exit(0)

    # Disable Qt's default 256 MB memory allocation limit for image readers
    QImageReader.setAllocationLimit(0)

    app = QApplication(sys.argv)

    # Synchronize icon assets from pdfapps.svg if missing or modified
    _ensure_icons()

    # Set application & taskbar icon
    ico_path = PROJECT_ROOT / "icon.ico"
    png_path = PROJECT_ROOT / "icon_512.png"
    svg_path = PROJECT_ROOT / "pdfapps.svg"
    icon_file = ico_path if ico_path.is_file() else (png_path if png_path.is_file() else (svg_path if svg_path.is_file() else None))
    if icon_file:
        app_icon = QIcon(str(icon_file))
        app.setWindowIcon(app_icon)

    app.setApplicationName(" ")
    app.setApplicationDisplayName(" ")
    app.setStyle("Fusion")
    dark = _load_dark_pref()
    app.setPalette(_make_palette(dark))
    app.setStyleSheet(STYLE if dark else STYLE_LIGHT)

    window = MainWindow()
    if icon_file:
        window.setWindowIcon(QIcon(str(icon_file)))
    window.showMaximized()

    for pdf_arg in args.files:
        abs_arg = os.path.abspath(pdf_arg)
        if os.path.isfile(abs_arg) and abs_arg.lower().endswith(".pdf"):
            window._load_and_track(abs_arg)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()