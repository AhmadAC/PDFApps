
# app/i18n.py

"""PDFApps – Internationalization (i18n) module."""
# app/i18n.py
import contextlib
import json
import locale
import logging
import os
import shutil
import sys
import threading
from typing import Callable

_log = logging.getLogger(__name__)

_TRANSLATIONS: dict = {}
_LANG: str = "en"

_CONFIG_LOCK = threading.RLock()

_LEGACY_CONFIG = os.path.join(os.path.expanduser("~"), ".pdfapps_config.json")
_LEGACY_SIGNATURE = os.path.join(os.path.expanduser("~"), ".pdfapps_signature.png")


def _resolve_config_paths() -> tuple[str, str]:
    """Return (config_path, signature_path)."""
    if os.path.isfile(_LEGACY_CONFIG):
        return _LEGACY_CONFIG, _LEGACY_SIGNATURE
    if sys.platform in ("win32", "darwin"):
        return _LEGACY_CONFIG, _LEGACY_SIGNATURE
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    d = os.path.join(xdg, "pdfapps")
    return os.path.join(d, "config.json"), os.path.join(d, "signature.png")


_CONFIG_PATH, _SIGNATURE_PATH = _resolve_config_paths()


_SIG_I18N = {
    "en": {
        "viewer.add_signature": "Add Signature",
        "edit.signature.saved_tab": "My Signatures",
        "edit.signature.new_tab": "Create / Import",
        "edit.signature.no_saved": "No saved signatures yet. Create or import one!",
        "edit.signature.delete_confirm": "Delete this saved signature?",
        "edit.signature.filter": "Signatures (*.png *.svg *.jpg *.jpeg *.webp)",
        "edit.signature.name_prompt": "Signature name (optional):",
        "edit.signature.place_hint": "Left-click on page to place signature. Right-click to cancel.",
        "edit.signature.resize_hint": "Drag handles to resize. Click outside or press Enter to apply.",
        "viewer.sig_placed": "✔ Signature added (Ctrl+Z to undo, Ctrl+S to save)",
    },
    "pt": {
        "viewer.add_signature": "Adicionar Assinatura",
        "edit.signature.saved_tab": "Minhas Assinaturas",
        "edit.signature.new_tab": "Criar / Importar",
        "edit.signature.no_saved": "Ainda não tem assinaturas guardadas. Crie ou importe uma!",
        "edit.signature.delete_confirm": "Eliminar esta assinatura guardada?",
        "edit.signature.filter": "Assinaturas (*.png *.svg *.jpg *.jpeg *.webp)",
        "edit.signature.name_prompt": "Nome da assinatura (opcional):",
        "edit.signature.place_hint": "Clique com o botão esquerdo para posicionar. Botão direito para cancelar.",
        "edit.signature.resize_hint": "Arraste os cantos para redimensionar. Clique fora ou prima Enter para aplicar.",
        "viewer.sig_placed": "✔ Assinatura adicionada (Ctrl+Z para anular, Ctrl+S para guardar)",
    },
    "es": {
        "viewer.add_signature": "Añadir Firma",
        "edit.signature.saved_tab": "Mis Firmas",
        "edit.signature.new_tab": "Crear / Importar",
        "edit.signature.no_saved": "Aún no hay firmas guardadas. ¡Cree o importe una!",
        "edit.signature.delete_confirm": "¿Eliminar esta firma guardada?",
        "edit.signature.filter": "Firmas (*.png *.svg *.jpg *.jpeg *.webp)",
        "edit.signature.name_prompt": "Nombre de la firma (opcional):",
        "edit.signature.place_hint": "Clic izquierdo para colocar. Clic derecho para cancelar.",
        "edit.signature.resize_hint": "Arrastre para redimensionar. Clic fuera o Enter para aplicar.",
        "viewer.sig_placed": "✔ Firma añadida (Ctrl+Z para deshacer, Ctrl+S para guardar)",
    },
    "fr": {
        "viewer.add_signature": "Ajouter une signature",
        "edit.signature.saved_tab": "Mes signatures",
        "edit.signature.new_tab": "Créer / Importer",
        "edit.signature.no_saved": "Aucune signature enregistrée. Créez ou importez-en une !",
        "edit.signature.delete_confirm": "Supprimer cette signature ?",
        "edit.signature.filter": "Signatures (*.png *.svg *.jpg *.jpeg *.webp)",
        "edit.signature.name_prompt": "Nom de la signature (facultatif) :",
        "edit.signature.place_hint": "Clic gauche pour placer. Clic droit pour annuler.",
        "edit.signature.resize_hint": "Glissez les poignées pour redimensionner. Cliquez dehors ou Entrée pour appliquer.",
        "viewer.sig_placed": "✔ Signature ajoutée (Ctrl+Z pour annuler, Ctrl+S pour enregistrer)",
    },
    "de": {
        "viewer.add_signature": "Signatur hinzufügen",
        "edit.signature.saved_tab": "Meine Signaturen",
        "edit.signature.new_tab": "Erstellen / Importieren",
        "edit.signature.no_saved": "Noch keine Signaturen gespeichert. Erstellen oder importieren Sie eine!",
        "edit.signature.delete_confirm": "Diese gespeicherte Signatur löschen?",
        "edit.signature.filter": "Signaturen (*.png *.svg *.jpg *.jpeg *.webp)",
        "edit.signature.name_prompt": "Signaturname (optional):",
        "edit.signature.place_hint": "Linksklick zum Platzieren. Rechtsklick zum Abbrechen.",
        "edit.signature.resize_hint": "Griffe ziehen zum Skalieren. Außerhalb klicken oder Enter zum Anwenden.",
        "viewer.sig_placed": "✔ Signatur hinzugefügt (Strg+Z zum Rückgängigmachen, Strg+S zum Speichern)",
    },
    "zh": {
        "viewer.add_signature": "添加签名",
        "edit.signature.saved_tab": "我的签名",
        "edit.signature.new_tab": "创建 / 导入",
        "edit.signature.no_saved": "尚无保存的签名。请创建或导入一个！",
        "edit.signature.delete_confirm": "确定删除此保存的签名吗？",
        "edit.signature.filter": "签名 (*.png *.svg *.jpg *.jpeg *.webp)",
        "edit.signature.name_prompt": "签名名称（可选）：",
        "edit.signature.place_hint": "左键点击页面放置签名，右键取消。",
        "edit.signature.resize_hint": "拖动手柄调整大小，点击空白处或回车确认。",
        "viewer.sig_placed": "✔ 已添加签名（Ctrl+Z 撤销，Ctrl+S 保存）",
    },
    "it": {
        "viewer.add_signature": "Aggiungi firma",
        "edit.signature.saved_tab": "Le mie firme",
        "edit.signature.new_tab": "Crea / Importa",
        "edit.signature.no_saved": "Nessuna firma salvata. Creane o importane una!",
        "edit.signature.delete_confirm": "Eliminare questa firma salvata?",
        "edit.signature.filter": "Firme (*.png *.svg *.jpg *.jpeg *.webp)",
        "edit.signature.name_prompt": "Nome della firma (facoltativo):",
        "edit.signature.place_hint": "Clic sinistro per posizionare. Clic destro per annullare.",
        "edit.signature.resize_hint": "Trascina per ridimensionare. Clic fuori o Invio per applicare.",
        "viewer.sig_placed": "✔ Firma aggiunta (Ctrl+Z per annullare, Ctrl+S per salvare)",
    },
    "nl": {
        "viewer.add_signature": "Handtekening toevoegen",
        "edit.signature.saved_tab": "Mijn handtekeningen",
        "edit.signature.new_tab": "Maken / Importeren",
        "edit.signature.no_saved": "Nog geen opgeslagen handtekeningen. Maak of importeer er een!",
        "edit.signature.delete_confirm": "Deze opgeslagen handtekening verwijderen?",
        "edit.signature.filter": "Handtekeningen (*.png *.svg *.jpg *.jpeg *.webp)",
        "edit.signature.name_prompt": "Naam van handtekening (optioneel):",
        "edit.signature.place_hint": "Linksklik om te plaatsen. Rechtsklik om te annuleren.",
        "edit.signature.resize_hint": "Versleep handgrepen om te vergroten/verkleinen. Klik buiten of druk op Enter.",
        "viewer.sig_placed": "✔ Handtekening toegevoegd (Ctrl+Z om ongedaan te maken, Ctrl+S om op te slaan)",
    },
}


def _load_translations():
    global _TRANSLATIONS
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "app", "translations.json")
    if not os.path.isfile(path):
        path = os.path.join(os.path.dirname(__file__), "translations.json")
    with open(path, "r", encoding="utf-8") as f:
        _TRANSLATIONS = json.load(f)

    for lang_code, dict_vals in _SIG_I18N.items():
        if lang_code in _TRANSLATIONS:
            _TRANSLATIONS[lang_code].update(dict_vals)
        elif "en" in _TRANSLATIONS:
            _TRANSLATIONS.setdefault(lang_code, {}).update(dict_vals)


def _detect_system_language() -> str:
    loc = ""
    try:
        if sys.platform == "win32":
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            _WIN_LANG = {
                0x0816: "pt", 0x0416: "pt",
                0x0C0A: "es", 0x040A: "es", 0x080A: "es",
                0x040C: "fr", 0x080C: "fr", 0x0C0C: "fr",
                0x0407: "de", 0x0807: "de", 0x0C07: "de",
                0x0804: "zh", 0x0404: "zh", 0x1004: "zh",
                0x0410: "it", 0x0810: "it",
                0x0413: "nl", 0x0813: "nl",
            }
            primary = lang_id & 0x03FF
            _WIN_PRIMARY = {
                0x16: "pt", 0x0A: "es", 0x0C: "fr", 0x07: "de",
                0x04: "zh", 0x10: "it", 0x13: "nl",
            }
            lang = _WIN_LANG.get(lang_id) or _WIN_PRIMARY.get(primary)
            if lang:
                return lang
        try:
            loc = locale.getlocale()[0] or ""
        except Exception:
            loc = ""
    except Exception:
        pass
    for code in ("pt", "es", "fr", "de", "zh", "it", "nl"):
        if loc.startswith(code):
            return code
    return "en"


def _load_config_language() -> str:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            return cfg.get("language", "")
    except Exception:
        return ""


def _atomic_write_config(cfg: dict):
    """Write config atomically: write to temp file, then rename."""
    import tempfile
    dir_name = os.path.dirname(_CONFIG_PATH)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        os.replace(tmp, _CONFIG_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _update_config(mutator: Callable[[dict], None]) -> None:
    with _CONFIG_LOCK:
        cfg: dict = {}
        corrupt = False
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except FileNotFoundError:
            cfg = {}
        except Exception:
            cfg = {}
            corrupt = True
        if not isinstance(cfg, dict):
            cfg = {}
            corrupt = True
        if corrupt:
            try:
                if os.path.isfile(_CONFIG_PATH) and os.path.getsize(_CONFIG_PATH) > 0:
                    from datetime import datetime
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_path = _CONFIG_PATH + f".corrupt-{ts}.bak"
                    with contextlib.suppress(Exception):
                        shutil.copy2(_CONFIG_PATH, backup_path)
                        _log.warning("config.json appeared corrupt; saved backup to %s", backup_path)
            except OSError:
                pass
        mutator(cfg)
        _atomic_write_config(cfg)


def _save_config_language(lang: str):
    _update_config(lambda cfg: cfg.__setitem__("language", lang))


def init():
    """Initialize i18n: load translations and set language."""
    global _LANG
    _load_translations()
    saved = _load_config_language()
    if saved and saved in _TRANSLATIONS:
        _LANG = saved
    else:
        _LANG = _detect_system_language()


def set_language(lang: str):
    global _LANG
    _LANG = lang
    _save_config_language(lang)


def get_language() -> str:
    return _LANG


def available_languages() -> list[str]:
    return list(_TRANSLATIONS.keys())


def t(key: str, **kwargs) -> str:
    """Get translated string by key. Supports format kwargs."""
    val = _TRANSLATIONS.get(_LANG, {}).get(key)
    if val is None:
        val = _TRANSLATIONS.get("en", {}).get(key, key)
    if kwargs:
        try:
            return val.format(**kwargs)
        except Exception:
            return val
    return val


_RECENT_FILES_MIN = 1
_RECENT_FILES_MAX = 50
_DEFAULT_MAX_RECENT = 10
_MAX_RECENT = _DEFAULT_MAX_RECENT


def _get_max_recent() -> int:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return _DEFAULT_MAX_RECENT
    val = cfg.get("max_recent_files", _DEFAULT_MAX_RECENT)
    try:
        n = int(val)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_RECENT
    return max(_RECENT_FILES_MIN, min(_RECENT_FILES_MAX, n))


def get_recent_files() -> list[str]:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            recents = cfg.get("recent_files", [])
    except Exception:
        return []
    valid = [p for p in recents
             if isinstance(p, str) and os.path.lexists(p) and not os.path.isdir(p)]
    if len(valid) != len([p for p in recents if isinstance(p, str)]):
        try:
            _update_config(lambda c: c.__setitem__("recent_files", valid))
        except Exception:
            pass
    return valid


def add_recent_file(path: str):
    if not path or not isinstance(path, str):
        return
    path = os.path.abspath(os.path.normpath(path))
    if os.path.isdir(path):
        return

    def _mutate(cfg: dict) -> None:
        recents = cfg.get("recent_files", [])
        if not isinstance(recents, list):
            recents = []
        recents = [p for p in recents if isinstance(p, str)]
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        cfg["recent_files"] = recents[:_get_max_recent()]

    _update_config(_mutate)


# ── Multiple Signatures Management ───────────────────────────────────────────

def get_signatures_dir() -> str:
    """Directory where saved signatures (PNG/SVG) are stored."""
    if sys.platform in ("win32", "darwin"):
        d = os.path.join(os.path.expanduser("~"), ".pdfapps_signatures")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
        d = os.path.join(xdg, "pdfapps", "signatures")
    os.makedirs(d, exist_ok=True)
    return d


def get_saved_signatures() -> list[dict]:
    """Return all saved signatures as a list of dicts: [{'id': ..., 'name': ..., 'path': ..., 'type': ...}]."""
    sig_dir = get_signatures_dir()
    if os.path.isfile(_SIGNATURE_PATH):
        legacy_dest = os.path.join(sig_dir, "default_signature.png")
        if not os.path.exists(legacy_dest):
            with contextlib.suppress(Exception):
                shutil.copy2(_SIGNATURE_PATH, legacy_dest)

    signatures = []
    valid_exts = {".png", ".svg", ".webp", ".jpg", ".jpeg"}
    try:
        filenames = sorted(os.listdir(sig_dir))
    except OSError:
        filenames = []

    for fn in filenames:
        ext = os.path.splitext(fn)[1].lower()
        if ext in valid_exts:
            fp = os.path.join(sig_dir, fn)
            if os.path.isfile(fp):
                name_clean = os.path.splitext(fn)[0].replace("_", " ").title()
                try:
                    mtime = os.path.getmtime(fp)
                except OSError:
                    mtime = 0
                signatures.append({
                    "id": fn,
                    "name": name_clean,
                    "path": fp,
                    "type": ext.lstrip(".").upper(),
                    "mtime": mtime,
                })
    signatures.sort(key=lambda s: s.get("mtime", 0), reverse=True)
    return signatures


def save_new_signature(src_path: str, display_name: str = "") -> str:
    """Save an image or SVG file into the persistent signatures repository."""
    sig_dir = get_signatures_dir()
    ext = os.path.splitext(src_path)[1].lower()
    if not ext:
        ext = ".png"
    import time
    ts = int(time.time() * 1000)
    clean_name = "".join(c for c in (display_name or "signature") if c.isalnum() or c in ("-", "_")).strip()
    if not clean_name:
        clean_name = "signature"
    dest = os.path.join(sig_dir, f"{clean_name}_{ts}{ext}")
    shutil.copy2(src_path, dest)
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    with contextlib.suppress(Exception):
        shutil.copy2(src_path, _SIGNATURE_PATH)
    return dest


def delete_saved_signature(path: str) -> bool:
    """Delete a saved signature file from the persistent signatures repository."""
    try:
        if os.path.isfile(path):
            os.remove(path)
            return True
    except OSError:
        pass
    return False


def get_saved_signature() -> str | None:
    """Return path to the most recent saved signature image, or None."""
    sigs = get_saved_signatures()
    if sigs:
        return sigs[0]["path"]
    if os.path.isfile(_SIGNATURE_PATH):
        return _SIGNATURE_PATH
    return None


def save_signature(img_path: str):
    """Backwards-compatibility wrapper for saving signature."""
    save_new_signature(img_path)


def clear_saved_signature():
    """Remove legacy saved signature."""
    try:
        os.remove(_SIGNATURE_PATH)
    except OSError:
        pass


init()