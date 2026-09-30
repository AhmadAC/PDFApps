# app/editor/apply_edits.py 
"""PDFApps – pure edit-application dispatcher for the PDF editor with media deletion/modification support."""

import os
import logging
from dataclasses import dataclass, field

from app.editor.text_reinsert import _reinsert_edited_text

_log = logging.getLogger(__name__)


@dataclass
class ApplyResult:
    """Outcome of apply_pending_edits."""

    text_fit_warnings: list = field(default_factory=list)
    embedded_font: bool = False


def apply_pending_edits(doc, pending, *, warn_fn=None) -> ApplyResult:
    """Apply pending edits to open doc, supporting transparent SVG/PNG signatures and clean media manipulation."""
    import fitz

    result = ApplyResult()

    def _collect_warning(edit):
        result.text_fit_warnings.append(edit)
        if warn_fn is not None:
            warn_fn(edit)

    embedded_font = False
    for e in pending:
        etype = e.get("type")
        pg = doc[e["page"]]

        # Handle existing document items that were moved, resized, or deleted
        if e.get("_existing"):
            if e.get("_deleted"):
                if e.get("_existing_annot"):
                    for annot in list(pg.annots() or []):
                        if getattr(annot, "xref", None) == e["_existing_annot"]:
                            pg.delete_annot(annot)
                            break
                elif e.get("_orig_rect"):
                    pg.add_redact_annot(fitz.Rect(e["_orig_rect"]), fill=False)
                    pg.apply_redactions()
                continue
            elif etype in ("image", "signature") and e.get("_orig_rect"):
                # Cleanly redact old position before inserting at new position
                pg.add_redact_annot(fitz.Rect(e["_orig_rect"]), fill=False)
                pg.apply_redactions()

        if etype == "redact":
            pg.add_redact_annot(e["rect"], fill=e["fill"])
            pg.apply_redactions()

        elif etype == "text":
            fname = (e.get("font", "") or "").lower()
            if "times" in fname or "serif" in fname or "roman" in fname:
                fontname = "tiro"
            elif "mono" in fname or "courier" in fname or "consol" in fname:
                fontname = "cour"
            else:
                fontname = "helv"
            c = e.get("color", (0, 0, 0))
            if isinstance(c, (list, tuple)) and len(c) >= 3:
                color = tuple(float(x) for x in c[:3])
            else:
                color = (0.0, 0.0, 0.0)
            pg.insert_text(e["point"], e["text"], fontsize=e.get("size", 12),
                           color=color, fontname=fontname)

        elif etype in ("image", "signature"):
            if e.get("_deleted"):
                continue
            path = e.get("path", "")
            if not path or not os.path.isfile(path):
                continue
            if path.lower().endswith((".svg", ".svgz")):
                try:
                    sdoc = fitz.open(path)
                    spix = sdoc[0].get_pixmap(dpi=300, alpha=True)
                    pg.insert_image(e["rect"], stream=spix.tobytes("png"))
                    sdoc.close()
                except Exception:
                    try:
                        from PySide6.QtSvg import QSvgRenderer
                        from PySide6.QtGui import QImage, QPainter
                        from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
                        renderer = QSvgRenderer(path)
                        if renderer.isValid():
                            ds = renderer.defaultSize()
                            w = 1200
                            h = max(10, int(w * (ds.height() / ds.width()))) if ds.width() > 0 else 400
                            qimg = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
                            qimg.fill(Qt.GlobalColor.transparent)
                            qp = QPainter(qimg)
                            renderer.render(qp)
                            qp.end()
                            ba = QByteArray()
                            buf = QBuffer(ba)
                            buf.open(QIODevice.OpenModeFlag.WriteOnly)
                            qimg.save(buf, b"PNG")
                            pg.insert_image(e["rect"], stream=ba.data())
                        else:
                            pg.insert_image(e["rect"], filename=path)
                    except Exception:
                        pg.insert_image(e["rect"], filename=path)
            else:
                pg.insert_image(e["rect"], filename=path)

        elif etype == "highlight":
            a = pg.add_highlight_annot(e["rect"])
            a.set_colors(stroke=e["color"])
            a.update()

        elif etype == "note":
            pg.add_text_annot(e["point"], e["text"])

        elif etype == "draw":
            stroke = [(float(x), float(y))
                      for x, y in e.get("points", [])]
            if len(stroke) >= 2:
                annot = pg.add_ink_annot([stroke])
                annot.set_colors(stroke=e.get("color", (1, 0, 0)))
                annot.set_border(width=max(1, int(e.get("width", 2))))
                annot.update()

        elif etype == "delete_annot":
            target_type = e.get("annot_type")
            target_bbox = e.get("bbox")
            if target_bbox is not None:
                target_rect = fitz.Rect(target_bbox)
                for annot in list(pg.annots() or []):
                    if (annot.type[0] == target_type
                            and abs(annot.rect.x0 - target_rect.x0) < 1
                            and abs(annot.rect.y0 - target_rect.y0) < 1):
                        pg.delete_annot(annot)
                        break

        elif etype == "text_edit":
            if _reinsert_edited_text(fitz, doc, pg, e,
                                     warn_fn=_collect_warning):
                embedded_font = True

    result.embedded_font = embedded_font
    if embedded_font:
        try:
            doc.subset_fonts()
        except Exception:
            _log.exception("subset_fonts after text edit failed")
    return result