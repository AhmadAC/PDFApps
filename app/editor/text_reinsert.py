# app/editor/text_reinsert.py

"""PDFApps – pure typographic-fidelity helpers for text-edit reinsertion with custom font support."""

import html
import logging

_log = logging.getLogger(__name__)

_EMBED_FAMILY = "PDFAppsEmbeddedFont"
_MIN_LEGIBLE_SCALE = 0.6
_FONT_STYLE_SUFFIXES = (
    "regular", "book", "roman", "medium", "semibold", "demibold",
    "bold", "italic", "oblique", "light", "black", "heavy", "condensed",
    "mt", "ps",
)


def _font_core(name):
    """Reduce a font name to a comparable lowercase alphanumeric core."""
    s = "".join(c for c in (name or "").split("+")[-1].lower() if c.isalnum())
    changed = True
    while changed:
        changed = False
        for suf in _FONT_STYLE_SUFFIXES:
            if s.endswith(suf) and len(s) - len(suf) >= 3:
                s = s[:-len(suf)]
                changed = True
    return s


def _font_matches(core, basefont, name):
    if not core:
        return False
    for cand in (_font_core(basefont), _font_core(name)):
        if cand and (core == cand or core in cand or cand in core):
            return True
    return False


def _text_edit_size(edit):
    """Original or user-modified span font size (points)."""
    size = float(edit.get("font_size") or 0) or float(edit.get("size") or 0)
    return size if size >= 1.0 else 4.0


def _text_edit_color_hex(edit):
    c = edit.get("color", 0)
    if isinstance(c, bool):
        c = 0
    if isinstance(c, int):
        return "#%06x" % (c & 0xFFFFFF)
    if isinstance(c, float):
        return "#%06x" % (int(c) & 0xFFFFFF)
    if isinstance(c, (list, tuple)) and len(c) >= 3:
        try:
            r, g, b = c[0], c[1], c[2]
            return "#%02x%02x%02x" % (
                max(0, min(255, int(r * 255))),
                max(0, min(255, int(g * 255))),
                max(0, min(255, int(b * 255))))
        except Exception:
            pass
    return "#000000"


def _text_edit_color_rgb(edit):
    c = edit.get("color", 0)
    if isinstance(c, bool):
        c = 0
    if isinstance(c, int):
        return (((c >> 16) & 0xFF) / 255.0, ((c >> 8) & 0xFF) / 255.0, (c & 0xFF) / 255.0)
    if isinstance(c, (list, tuple)) and len(c) >= 3:
        try:
            return (float(c[0]), float(c[1]), float(c[2]))
        except Exception:
            pass
    return (0.0, 0.0, 0.0)


def _text_edit_style(edit):
    """Return (serif, mono, bold, italic) from flags and font name."""
    flags = int(edit.get("flags", 0) or 0)
    fname = (edit.get("font", "") or "").lower()
    serif = bool(flags & 4) or any(
        k in fname for k in ("times", "serif", "roman", "georgia", "garamond", "minion"))
    mono = bool(flags & 8) or any(
        k in fname for k in ("mono", "courier", "consol"))
    bold = bool(flags & 16) or any(
        k in fname for k in ("bold", "black", "heavy", "semibold"))
    italic = bool(flags & 2) or any(
        k in fname for k in ("italic", "oblique"))
    return serif, mono, bold, italic


def _base14_fontname(edit):
    """Best-matching base-14 font code for defensive insert_text fallback."""
    serif, mono, bold, italic = _text_edit_style(edit)
    if mono:
        tbl = {(0, 0): "cour", (1, 0): "cobo", (0, 1): "coit", (1, 1): "cobi"}
    elif serif:
        tbl = {(0, 0): "tiro", (1, 0): "tibo", (0, 1): "tiit", (1, 1): "tibi"}
    else:
        tbl = {(0, 0): "helv", (1, 0): "hebo", (0, 1): "heit", (1, 1): "hebi"}
    return tbl[(int(bold), int(italic))]


def _generic_font_style(edit):
    """CSS (family, weight, style) for the generic-family htmlbox fallback."""
    serif, mono, bold, italic = _text_edit_style(edit)
    font_spec = edit.get("font", "")
    standard_families = ("Times New Roman", "Georgia", "Courier New", "Segoe UI",
                         "Calibri", "Verdana", "Arial", "Helvetica", "Trebuchet MS")
    if font_spec and any(sf.lower() in font_spec.lower() for sf in standard_families):
        family = f"'{font_spec}', sans-serif"
    else:
        family = "monospace" if mono else ("serif" if serif else "sans-serif")
    return family, ("bold" if bold else "normal"), ("italic" if italic else "normal")


def _build_embed_archive(fitz, doc, page, edit, new_txt):
    """Return (archive, ref) embedding the span's original font, or (None, None)."""
    if edit.get("_font_changed"):
        return None, None
    core = _font_core(edit.get("font", ""))
    if not core:
        return None, None
    try:
        fonts = page.get_fonts(full=False)
    except Exception:
        return None, None
    xref = None
    for f in fonts:
        fxref, basefont, name = f[0], f[3], f[4]
        if "+" in (basefont or ""):
            continue
        if fxref and int(fxref) > 0 and _font_matches(core, basefont, name):
            xref = int(fxref)
            break
    if not xref:
        return None, None
    try:
        _n, ext_, _t, content = doc.extract_font(xref)
    except Exception:
        return None, None
    if not content or len(content) < 256:
        return None, None
    try:
        probe = fitz.Font(fontbuffer=content)
        for ch in new_txt:
            if ch.isspace():
                continue
            if not probe.has_glyph(ord(ch)):
                return None, None
    except Exception:
        return None, None
    ref = "pdfapps_embed." + ((ext_ or "ttf").lstrip(".") or "ttf")
    try:
        arch = fitz.Archive()
        arch.add(content, ref)
    except Exception:
        return None, None
    return arch, ref


def _text_edit_redaction_rect(fitz, edit, size):
    """Vertically tight redaction rectangle for removing original span."""
    bbox = fitz.Rect(edit["bbox"])
    origin = edit.get("origin") or (bbox.x0, bbox.y1)
    asc = float(edit.get("ascender") or 0)
    desc = float(edit.get("descender") or 0)
    span = asc - desc
    if size > 0 and asc > 0 and desc < 0 and span > 1e-3:
        y1 = float(origin[1]) - size * desc / span
        y0 = y1 - size
        if (y1 - y0) >= size * 0.5 and y0 >= bbox.y0 - 0.5 and y1 <= bbox.y1 + 0.5:
            return fitz.Rect(bbox.x0, y0, bbox.x1, y1)
    return bbox


def _text_edit_layout_rect(fitz, page, edit, size):
    """Layout rectangle for insert_htmlbox."""
    bbox = fitz.Rect(edit["bbox"])
    origin = edit.get("origin") or (bbox.x0, bbox.y1)
    asc = float(edit.get("ascender") or 0) or 0.9
    x0 = float(origin[0])
    top = float(origin[1]) - asc * size
    right = page.rect.x1 - 2.0
    if right <= x0 + size:
        right = min(page.rect.x1, x0 + size * 8)
    bottom = max(top + 3.0 * size, page.rect.y1 - 2.0)
    return fitz.Rect(x0, top, right, bottom)


def _warn_if_downscaled(htmlbox_result, edit, warn_fn):
    """Inspect insert_htmlbox's (spare_height, scale) output."""
    try:
        spare_height, scale = htmlbox_result
        scale = float(scale)
    except Exception:
        return
    if scale < _MIN_LEGIBLE_SCALE or (spare_height is not None and spare_height < 0):
        _log.warning(
            "edited text did not fit its box at the original size "
            "(scale=%.2f); it was reduced to fit. old=%r",
            scale, (edit.get("old_text") or "")[:40])
        if warn_fn is not None:
            try:
                warn_fn(edit)
            except Exception:
                _log.exception("text-fit warn_fn raised")


def _reinsert_edited_text(fitz, doc, page, edit, warn_fn=None):
    """Redact original span and reinsert replacement text with custom typography support."""
    bbox = fitz.Rect(edit["bbox"])
    new_txt = (edit.get("new_text") or "").strip()
    size = _text_edit_size(edit)

    arch = ref = None
    if new_txt:
        arch, ref = _build_embed_archive(fitz, doc, page, edit, new_txt)

    redact_rect = _text_edit_redaction_rect(fitz, edit, size)
    try:
        page.add_redact_annot(redact_rect, fill=False, cross_out=False)
        page.apply_redactions(images=0, graphics=0, text=0)
    except Exception:
        page.add_redact_annot(redact_rect, fill=(1, 1, 1))
        page.apply_redactions()

    if not new_txt:
        return False

    color_hex = _text_edit_color_hex(edit)
    rect = _text_edit_layout_rect(fitz, page, edit, size)
    body = "<div>%s</div>" % html.escape(new_txt)

    try:
        if arch is not None:
            css = ("@font-face {{ font-family: {fam}; src: url({ref}); }}\n"
                   "* {{ margin:0; padding:0; white-space:pre-wrap;"
                   " font-family:{fam}; font-size:{sz}pt; color:{col}; }}"
                   ).format(fam=_EMBED_FAMILY, ref=ref, sz=size, col=color_hex)
            _warn_if_downscaled(
                page.insert_htmlbox(rect, body, css=css, archive=arch),
                edit, warn_fn)
            return True
        family, weight, style = _generic_font_style(edit)
        css = ("* {{ margin:0; padding:0; white-space:pre-wrap;"
               " font-family:{fam}; font-size:{sz}pt; color:{col};"
               " font-weight:{w}; font-style:{s}; }}"
               ).format(fam=family, sz=size, col=color_hex, w=weight, s=style)
        _warn_if_downscaled(page.insert_htmlbox(rect, body, css=css), edit, warn_fn)
        return False
    except Exception:
        _log.exception("htmlbox reinsertion failed; using base-14 insert_text")
        try:
            origin = edit.get("origin") or (bbox.x0, bbox.y1)
            page.insert_text(fitz.Point(float(origin[0]), float(origin[1])),
                             new_txt, fontsize=size,
                             fontname=_base14_fontname(edit),
                             color=_text_edit_color_rgb(edit))
        except Exception:
            _log.exception("base-14 insert_text fallback also failed")
        return False