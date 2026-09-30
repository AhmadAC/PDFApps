# app/editor/tab_history.py
"""PDFApps – tab_history: history, undo/redo, and pending edits management."""

import contextlib
import os
import tempfile
import fitz

from app.i18n import t
from app.editor.tab_constants import _MAX_PENDING, _MAX_REDO, _MODE_FORMS


class TabHistoryManager:
    """Manages pending visual edits, annotation imports, and undo/redo stacks."""

    def __init__(self, tab):
        self.tab = tab
        self.pending = tab._pending
        self.redo_stack = tab._redo_stack

    def add(self, edit: dict, *, _from_redo: bool = False) -> None:
        if not _from_redo:
            self.redo_stack.clear()
        self.pending.append(edit)
        if len(self.pending) > _MAX_PENDING:
            to_drop = self.pending[:-_MAX_PENDING]
            self.pending[:] = self.pending[-_MAX_PENDING:]
            tmp_root = os.path.normcase(tempfile.gettempdir())
            for old in to_drop:
                with contextlib.suppress(Exception):
                    p = old.get("path")
                    if p and os.path.isfile(p) and os.path.normcase(p).startswith(tmp_root):
                        os.unlink(p)
            for _ in range(len(to_drop)):
                self.tab._pending_list.takeItem(0)

        suffix = t("edit.label.page_suffix", n=edit["page"] + 1)
        labels = {
            "redact":    lambda e: t("edit.label.redact") + suffix,
            "text":      lambda e: t("edit.label.text", txt=e["text"][:18]) + suffix,
            "image":     lambda e: t("edit.label.image", name=os.path.basename(e.get("path", ""))) + suffix,
            "highlight": lambda e: t("edit.label.highlight") + suffix,
            "note":      lambda e: t("edit.label.note") + suffix,
            "text_edit": lambda e: (
                (t("edit.label.edit", old=e.get("old_text", "")[:12], new=e.get("new_text", "")[:12]) + suffix)
                if e.get("new_text") else (f"🗑 Text {suffix}")
            ),
            "signature":    lambda e: t("edit.mode.signature") + suffix,
            "draw":         lambda e: t("edit.mode.draw") + suffix,
            "delete_annot": lambda e: t("edit.label.note_delete") + suffix,
        }
        builder = labels.get(edit["type"], lambda e: e["type"] + suffix)
        lbl = builder(edit)
        self.tab._pending_list.addItem(lbl)
        self.tab._status(t("edit.status.added", label=lbl, count=len(self.pending)))
        self.tab._canvas.set_overlays(self.pending)

    def undo(self) -> None:
        if getattr(self.tab, "_mode_idx", -1) == _MODE_FORMS:
            self.tab._status(t("editor.forms.undo_unavailable"))
            return
        if not self.pending:
            return
        edit = self.pending.pop()
        self.redo_stack.append(edit)
        if len(self.redo_stack) > _MAX_REDO:
            self.redo_stack.pop(0)
        self.tab._pending_list.takeItem(self.tab._pending_list.count() - 1)
        if edit.get("_deleted"):
            edit["_deleted"] = False
        if edit.get("type") == "delete_annot":
            original = edit.get("_original_note")
            if isinstance(original, dict):
                self.pending.append(original)
                page = original.get("page", 0)
                self.tab._pending_list.addItem(t("edit.status.note_label", n=(page or 0) + 1))
        self.tab._canvas.set_overlays(self.pending)
        self.tab._status(t("edit.status.undo", n=len(self.pending)))

    def redo(self) -> None:
        if not self.redo_stack:
            return
        edit = self.redo_stack.pop()
        self.add(edit, _from_redo=True)

    def clear(self) -> None:
        self.pending.clear()
        self.tab._pending_list.clear()
        self.redo_stack.clear()
        self.tab._canvas.set_overlays([])

    def handle_note_deleted(self, overlay: dict) -> None:
        text = overlay.get("text", "").strip()
        page = overlay.get("page")
        for i, p in enumerate(self.pending):
            if p.get("type") == "note" and p.get("text", "").strip() == text and p.get("page") == page:
                removed = self.pending.pop(i)
                self.tab._pending_list.takeItem(i)
                self.redo_stack.append(removed)
                if len(self.redo_stack) > _MAX_REDO:
                    self.redo_stack.pop(0)
                if removed.get("_existing"):
                    edit = {
                        "type": "delete_annot",
                        "page": removed.get("page"),
                        "annot_type": removed.get("_annot_type"),
                        "bbox": removed.get("_annot_bbox"),
                        "_existing": True,
                        "_original_note": removed,
                    }
                    self.pending.append(edit)
                    suffix = t("edit.label.page_suffix", n=((removed.get("page") or 0) + 1))
                    self.tab._pending_list.addItem(t("edit.label.note_delete") + suffix)
                self.tab._canvas.set_overlays(self.pending)
                return
        if overlay.get("_existing"):
            edit = {
                "type": "delete_annot",
                "page": page,
                "annot_type": overlay.get("_annot_type"),
                "bbox": overlay.get("_annot_bbox"),
                "_existing": True,
            }
            self.pending.append(edit)
            suffix = t("edit.label.page_suffix", n=(page or 0) + 1)
            self.tab._pending_list.addItem(t("edit.label.note_delete") + suffix)
            self.tab._canvas.set_overlays(self.pending)

    def handle_overlay_deleted(self, idx: int, edit: dict) -> None:
        if edit in self.pending:
            self.pending.remove(edit)
            self.redo_stack.append(edit)
            for r in range(self.tab._pending_list.count()):
                item = self.tab._pending_list.item(r)
                if item and edit.get("type") in item.text():
                    self.tab._pending_list.takeItem(r)
                    break
        elif edit.get("_existing"):
            if edit not in self.pending:
                self.pending.append(edit)
            suffix = t("edit.label.page_suffix", n=edit["page"] + 1)
            self.tab._pending_list.addItem(f"🗑 {edit['type'].title()} {suffix}")
        self.tab._status("✔ " + t("tool.deleted", default="Object deleted (Ctrl+Z to undo)"))

    def load_existing_annotations(self) -> None:
        try:
            doc = self.tab._canvas._doc
            if not doc:
                self.tab._status(t("edit.status.no_doc"))
                return
            count = 0
            total_annots = 0
            for page_idx in range(doc.page_count):
                page = doc[page_idx]
                for annot in page.annots() or []:
                    total_annots += 1
                    if annot.type[0] == fitz.PDF_ANNOT_TEXT:
                        r = annot.rect
                        txt = annot.info.get("content", "")
                        if txt:
                            self.pending.append({
                                "type": "note",
                                "page": page_idx,
                                "point": fitz.Point(r.x0, r.y0 + r.height),
                                "text": txt,
                                "_existing": True,
                                "_annot_type": annot.type[0],
                                "_annot_bbox": [r.x0, r.y0, r.x1, r.y1],
                            })
                            count += 1
            self.tab._status(t("edit.status.note_loaded", count=count, total=total_annots))
            self.tab._canvas.set_overlays(self.pending)
        except Exception as ex:
            self.tab._status(t("edit.status.annot_error", ex=ex))