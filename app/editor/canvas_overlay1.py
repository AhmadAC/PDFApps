# app/editor/canvas_overlay1.py

"""Overlay management: selection, resizing handles, hit-testing, duplication and deletion."""

from __future__ import annotations

import os
import tempfile
import fitz
from PySide6.QtCore import Qt, QRect, QPoint

from app.editor.dialogs import _SignatureDialog, load_signature_pixmap
from app.editor.canvas_render1 import _NOTE_ICON_SIZE

# Safe fallbacks for PyMuPDF annotation type constants to satisfy Pylance stubs
_PDF_ANNOT_TEXT: int = getattr(fitz, "PDF_ANNOT_TEXT", 0)
_PDF_ANNOT_STAMP: int = getattr(fitz, "PDF_ANNOT_STAMP", 13)
_PDF_ANNOT_INK: int = getattr(fitz, "PDF_ANNOT_INK", 15)


class CanvasOverlayManager:
    HANDLE_NONE = 0
    HANDLE_TL   = 1
    HANDLE_TR   = 2
    HANDLE_BL   = 3
    HANDLE_BR   = 4

    def __init__(self, canvas):
        self.canvas = canvas

    def start_add_signature_flow(self, pos: QPoint | None = None):
        """Open signature selection dialog and enter cursor-follow placement mode."""
        dlg = _SignatureDialog(self.canvas)
        if dlg.exec() == _SignatureDialog.DialogCode.Accepted:
            path = dlg.selected_signature_path()
            if path and os.path.isfile(path):
                self.begin_signature_placement(path)

    def begin_signature_placement(self, sig_path: str):
        c = self.canvas
        c._selected_overlay_idx = -1
        c._placing_signature = True
        c._placing_sig_path = sig_path
        c._placing_sig_pixmap = load_signature_pixmap(sig_path, max_size=(320, 140))
        c.setCursor(Qt.CursorShape.CrossCursor)
        c.update()

    def cancel_signature_placement(self):
        c = self.canvas
        c._placing_signature = False
        c._placing_sig_path = ""
        c._placing_sig_pixmap = None
        c._sig_cursor_pos = None
        c.setCursor(Qt.CursorShape.ArrowCursor)
        c.update()

    def delete_selected_overlay(self) -> dict | None:
        c = self.canvas
        if 0 <= c._selected_overlay_idx < len(c._overlays):
            idx = c._selected_overlay_idx
            overlay = c._overlays[idx]
            if overlay.get("_existing"):
                overlay["_deleted"] = True
                c._selected_overlay_idx = -1
            else:
                c._overlays.pop(idx)
                c._selected_overlay_idx = -1
            c._drag_handle = self.HANDLE_NONE
            c._moving_overlay = False
            c.setCursor(Qt.CursorShape.ArrowCursor)
            c.overlay_deleted.emit(idx, overlay)
            c.overlay_changed.emit()
            c.update()
            return overlay
        return None

    def duplicate_selected_overlay(self) -> None:
        c = self.canvas
        if 0 <= c._selected_overlay_idx < len(c._overlays):
            src = c._overlays[c._selected_overlay_idx]
            new_overlay = dict(src)
            new_overlay.pop("_existing", None)
            new_overlay.pop("_orig_rect", None)
            new_overlay.pop("_existing_xref", None)
            new_overlay.pop("_existing_annot", None)
            if "rect" in new_overlay:
                r = fitz.Rect(new_overlay["rect"])
                new_overlay["rect"] = fitz.Rect(r.x0 + 15, r.y0 + 15, r.x1 + 15, r.y1 + 15)
                if "point" in new_overlay:
                    pt = new_overlay["point"]
                    new_overlay["point"] = fitz.Point(pt.x + 15, pt.y + 15)
            elif "bbox" in new_overlay:
                bb = new_overlay["bbox"]
                new_overlay["bbox"] = [bb[0] + 15, bb[1] + 15, bb[2] + 15, bb[3] + 15]
            elif "point" in new_overlay:
                pt = new_overlay["point"]
                new_overlay["point"] = fitz.Point(pt.x + 15, pt.y + 15)
            c._overlays.append(new_overlay)
            c._selected_overlay_idx = len(c._overlays) - 1
            c.overlay_changed.emit()
            c.update()

    def get_overlay_handle_at(self, idx: int, pos: QPoint) -> int:
        c = self.canvas
        if idx < 0 or idx >= len(c._overlays):
            return self.HANDLE_NONE
        e = c._overlays[idx]
        if e.get("_deleted"):
            return self.HANDLE_NONE
        etype = e.get("type")
        if etype not in ("signature", "image", "text_edit", "text", "redact"):
            return self.HANDLE_NONE
        pg = e.get("page", 0)
        if pg >= len(c._page_offsets):
            return self.HANDLE_NONE
        yo = c._page_offsets[pg][0]
        z = c._zoom

        if "rect" in e:
            r = e["rect"]
        elif "bbox" in e:
            r = fitz.Rect(e.get("bbox", (0, 0, 0, 0)))
        elif etype == "text" and "point" in e:
            pt = e["point"]
            sz = float(e.get("size", 12))
            txt = e.get("text", "")
            tw = max(16.0, len(txt) * sz * 0.65)
            r = fitz.Rect(pt.x, pt.y - sz * 0.85, pt.x + tw, pt.y + sz * 0.25)
            e["rect"] = r
        else:
            return self.HANDLE_NONE

        sx0 = int(r.x0 * z)
        sy0 = yo + int(r.y0 * z)
        sx1 = int(r.x1 * z)
        sy1 = yo + int(r.y1 * z)
        hs = 12
        if QRect(sx0 - hs, sy0 - hs, hs * 2, hs * 2).contains(pos):
            return self.HANDLE_TL
        if QRect(sx1 - hs, sy0 - hs, hs * 2, hs * 2).contains(pos):
            return self.HANDLE_TR
        if QRect(sx0 - hs, sy1 - hs, hs * 2, hs * 2).contains(pos):
            return self.HANDLE_BL
        if QRect(sx1 - hs, sy1 - hs, hs * 2, hs * 2).contains(pos):
            return self.HANDLE_BR
        return self.HANDLE_NONE

    def is_pos_inside_overlay(self, idx: int, pos: QPoint) -> bool:
        c = self.canvas
        if idx < 0 or idx >= len(c._overlays):
            return False
        e = c._overlays[idx]
        if e.get("_deleted"):
            return False
        pg = e.get("page", 0)
        if pg >= len(c._page_offsets):
            return False
        yo = c._page_offsets[pg][0]
        z = c._zoom

        if "rect" in e:
            r = e["rect"]
            sx0 = int(r.x0 * z)
            sy0 = yo + int(r.y0 * z)
            sx1 = int(r.x1 * z)
            sy1 = yo + int(r.y1 * z)
            return QRect(sx0 - 4, sy0 - 4, max(12, sx1 - sx0 + 8), max(12, sy1 - sy0 + 8)).contains(pos)
        elif "bbox" in e:
            b = e["bbox"]
            sx0 = int(b[0] * z)
            sy0 = yo + int(b[1] * z)
            sx1 = int(b[2] * z)
            sy1 = yo + int(b[3] * z)
            return QRect(sx0 - 4, sy0 - 4, max(12, sx1 - sx0 + 8), max(12, sy1 - sy0 + 8)).contains(pos)
        elif e.get("type") == "text" and "point" in e:
            pt = e["point"]
            sz = float(e.get("size", 12))
            txt = e.get("text", "")
            tw = max(16.0, len(txt) * sz * 0.65)
            r = fitz.Rect(pt.x, pt.y - sz * 0.85, pt.x + tw, pt.y + sz * 0.25)
            e["rect"] = r
            sx0 = int(r.x0 * z)
            sy0 = yo + int(r.y0 * z)
            sx1 = int(r.x1 * z)
            sy1 = yo + int(r.y1 * z)
            return QRect(sx0 - 4, sy0 - 4, max(12, sx1 - sx0 + 8), max(12, sy1 - sy0 + 8)).contains(pos)
        return False

    def detect_existing_media_at(self, page_idx: int, pdf_pt: fitz.Point) -> dict | None:
        c = self.canvas
        if not c._doc or not (0 <= page_idx < c._doc.page_count):
            return None
        page = c._doc[page_idx]

        # 1. Embedded images
        try:
            for img_info in page.get_images():
                xref = img_info[0]
                if xref <= 0:
                    continue
                rects = page.get_image_rects(xref)
                for r in rects:
                    if r.contains(pdf_pt):
                        for ov in c._overlays:
                            if ov.get("_existing_xref") == xref and ov.get("page") == page_idx:
                                return ov
                        pix = fitz.Pixmap(c._doc, xref)
                        if pix.n >= 5:
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                        fd, tmp_path = tempfile.mkstemp(suffix=".png")
                        os.close(fd)
                        pix.save(tmp_path)
                        entry = {
                            "type": "signature",
                            "page": page_idx,
                            "rect": fitz.Rect(r),
                            "path": tmp_path,
                            "_existing": True,
                            "_existing_xref": xref,
                            "_orig_rect": [r.x0, r.y0, r.x1, r.y1],
                        }
                        c._overlays.append(entry)
                        return entry
        except Exception:
            pass

        # 2. Stamp / ink annotations
        try:
            for annot in page.annots() or []:
                if annot.type[0] in (_PDF_ANNOT_STAMP, _PDF_ANNOT_INK) or annot.type[1] in ("Stamp", "Ink"):
                    if annot.rect.contains(pdf_pt):
                        for ov in c._overlays:
                            if ov.get("_existing_annot") == annot.xref and ov.get("page") == page_idx:
                                return ov
                        pix = annot.get_pixmap(dpi=150, alpha=True)
                        fd, tmp_path = tempfile.mkstemp(suffix=".png")
                        os.close(fd)
                        pix.save(tmp_path)
                        entry = {
                            "type": "signature",
                            "page": page_idx,
                            "rect": fitz.Rect(annot.rect),
                            "path": tmp_path,
                            "_existing": True,
                            "_existing_annot": annot.xref,
                            "_orig_rect": [annot.rect.x0, annot.rect.y0, annot.rect.x1, annot.rect.y1],
                            "_annot_type": annot.type[0],
                        }
                        c._overlays.append(entry)
                        return entry
        except Exception:
            pass

        return None

    def note_icon_at(self, pos: QPoint) -> int:
        c = self.canvas
        z = c._zoom
        margin = 10
        for i, e in enumerate(c._overlays):
            if e.get("type") != "note" or e.get("_deleted"):
                continue
            pg = e.get("page", 0)
            if pg >= len(c._page_offsets):
                continue
            yo = c._page_offsets[pg][0]
            pt = e["point"]
            px, py = int(pt.x * z), yo + int(pt.y * z)
            hit_r = QRect(px - margin, py - _NOTE_ICON_SIZE - margin,
                          _NOTE_ICON_SIZE + margin * 2, _NOTE_ICON_SIZE + margin * 2)
            if hit_r.contains(pos):
                return i
        return -1

    def annot_note_at(self, pos: QPoint):
        c = self.canvas
        if not c._doc:
            return -1, None
        page_idx, lx, ly = c._page_and_local(pos.x(), pos.y())
        pdf_pt = c._to_pdf(page_idx, lx, ly)
        page = c._doc[page_idx]
        for annot in page.annots() or []:
            if annot.type[0] == _PDF_ANNOT_TEXT or annot.type[1] == "Text":
                expanded = annot.rect + fitz.Rect(-10, -10, 10, 10)
                if expanded.contains(pdf_pt):
                    txt = annot.info.get("content", "") or annot.get_text() or ""
                    for i, e in enumerate(c._overlays):
                        if e.get("type") == "note" and e.get("text", "").strip() == txt.strip():
                            return i, txt.strip()
                    if txt.strip():
                        pt = fitz.Point(annot.rect.x0, annot.rect.y0 + annot.rect.height)
                        c._overlays.append({
                            "type": "note", "page": page_idx,
                            "point": pt, "text": txt.strip(),
                            "_existing": True,
                            "_annot_type": annot.type[0],
                            "_annot_bbox": [annot.rect.x0, annot.rect.y0,
                                            annot.rect.x1, annot.rect.y1],
                        })
                        return len(c._overlays) - 1, txt.strip()
        return -1, None