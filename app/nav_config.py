"""PDFApps – Sidebar navigation groups and tool definitions."""
from app.i18n import t

from app.tools.split import TabDividir
from app.tools.merge import TabJuntar
from app.tools.rotate import TabRotar
from app.tools.crop import TabCortar
from app.tools.extract import TabExtrair
from app.tools.reorder import TabReordenar
from app.tools.compress import TabComprimir
from app.tools.encrypt import TabEncriptar
from app.tools.watermark import TabMarcaDagua
from app.tools.ocr import TabOCR
from app.tools.convert import TabConverter
from app.editor.tab import TabEditar
from app.tools.info import TabInfo
from app.tools.import_pdf import TabImport
from app.tools.page_numbers import TabPageNumbers
from app.tools.nup import TabNUp

_NAV_GROUPS = [
    ("nav.group.organize", [
        ("nav.split",         "fa5s.cut",                TabDividir),
        ("nav.merge",         "fa5s.object-group",       TabJuntar),
        ("nav.reorder",       "fa5s.sort",               TabReordenar),
        ("nav.extract",       "fa5s.file-export",        TabExtrair),
    ]),
    ("nav.group.transform", [
        ("nav.crop",          "fa5s.crop-alt",           TabCortar),
        ("nav.rotate",        "fa5s.sync-alt",           TabRotar),
        ("nav.compress",      "fa5s.compress-arrows-alt",TabComprimir),
        ("nav.page_numbers",  "fa5s.list-ol",            TabPageNumbers),
        ("nav.nup",           "fa5s.th",                 TabNUp),
    ]),
    ("nav.group.security", [
        ("nav.encrypt",       "fa5s.lock",               TabEncriptar),
        ("nav.watermark",     "fa5s.stamp",              TabMarcaDagua),
    ]),
    ("nav.group.convert", [
        ("nav.ocr",           "fa5s.eye",                TabOCR),
        ("nav.convert",       "fa5s.exchange-alt",       TabConverter),
        ("nav.import",        "fa5s.file-import",        TabImport),
    ]),
    ("nav.group.annotate", [
        ("nav.edit",          "fa5s.edit",               TabEditar),
    ]),
    ("nav.group.inspect", [
        ("nav.info",          "fa5s.info-circle",        TabInfo),
    ]),
]

_NAV_KEYS = [(key, icon, cls) for _, tools in _NAV_GROUPS for key, icon, cls in tools]


def _build_nav_items():
    return [(t(key), icon, cls) for key, icon, cls in _NAV_KEYS]


NAV_ITEMS = _build_nav_items()