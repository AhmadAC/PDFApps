"""PDFApps – Sidebar navigation groups and tool definitions."""
import importlib
from app.i18n import t


class LazyTool:
    """Lazily loads and instantiates tool classes upon first request."""
    __slots__ = ("module_name", "class_name", "_cls")

    def __init__(self, module_name: str, class_name: str):
        self.module_name = module_name
        self.class_name = class_name
        self._cls = None

    def get_class(self):
        if self._cls is None:
            mod = importlib.import_module(self.module_name)
            self._cls = getattr(mod, self.class_name)
        return self._cls

    def __call__(self, *args, **kwargs):
        return self.get_class()(*args, **kwargs)

    def __repr__(self):
        return f"<LazyTool {self.module_name}.{self.class_name}>"


_NAV_GROUPS = [
    ("nav.group.organize", [
        ("nav.split",         "fa5s.cut",                 LazyTool("app.tools.split", "TabDividir")),
        ("nav.merge",         "fa5s.object-group",        LazyTool("app.tools.merge", "TabJuntar")),
        ("nav.reorder",       "fa5s.sort",                LazyTool("app.tools.reorder", "TabReordenar")),
        ("nav.extract",       "fa5s.file-export",         LazyTool("app.tools.extract", "TabExtrair")),
    ]),
    ("nav.group.transform", [
        ("nav.crop",          "fa5s.crop-alt",            LazyTool("app.tools.crop", "TabCortar")),
        ("nav.rotate",        "fa5s.sync-alt",            LazyTool("app.tools.rotate", "TabRotar")),
        ("nav.compress",      "fa5s.compress-arrows-alt", LazyTool("app.tools.compress", "TabComprimir")),
        ("nav.page_numbers",  "fa5s.list-ol",             LazyTool("app.tools.page_numbers", "TabPageNumbers")),
        ("nav.nup",           "fa5s.th",                  LazyTool("app.tools.nup", "TabNUp")),
    ]),
    ("nav.group.security", [
        ("nav.encrypt",       "fa5s.lock",                LazyTool("app.tools.encrypt", "TabEncriptar")),
        ("nav.watermark",     "fa5s.stamp",               LazyTool("app.tools.watermark", "TabMarcaDagua")),
    ]),
    ("nav.group.convert", [
        ("nav.ocr",           "fa5s.eye",                 LazyTool("app.tools.ocr", "TabOCR")),
        ("nav.convert",       "fa5s.exchange-alt",        LazyTool("app.tools.convert", "TabConverter")),
        ("nav.import",        "fa5s.file-import",         LazyTool("app.tools.import_pdf", "TabImport")),
    ]),
    ("nav.group.annotate", [
        ("nav.edit",          "fa5s.edit",                LazyTool("app.editor.tab", "TabEditar")),
    ]),
    ("nav.group.inspect", [
        ("nav.info",          "fa5s.info-circle",         LazyTool("app.tools.info", "TabInfo")),
    ]),
]

_NAV_KEYS = [(key, icon, cls) for _, tools in _NAV_GROUPS for key, icon, cls in tools]


def _build_nav_items():
    return [(t(key), icon, cls) for key, icon, cls in _NAV_KEYS]


NAV_ITEMS = _build_nav_items()