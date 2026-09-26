
# app/tools/crop.py

"""PDFApps – TabCortar: crop PDF pages tool."""
import contextlib
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QHBoxLayout, QGridLayout, QLineEdit,
    QComboBox, QSpinBox, QPushButton, QLabel, QFileDialog, QMessageBox,
    QVBoxLayout,
)
from PySide6.QtGui import QShortcut, QKeySequence
import qtawesome as qta
import fitz

from app import i18n
from app.base import BasePage
from app.pdf_io import atomic_pdf_write
from app.i18n import t, get_language
from app.utils import section, info_lbl, parse_pages, show_error
from app.constants import ACCENT, DESKTOP, TEXT_PRI, TEXT_SEC, _LQ
from app.widgets import DropFileEdit


_CROP_I18N = {
    "en": {
        "nav.crop": "Crop",
        "tool.crop.name": "Crop pages",
        "tool.crop.desc": "Crop one or multiple pages using margin controls or Foxit-style visual selection.",
        "tool.crop.btn": "Save",
        "tool.crop.source": "Source file",
        "tool.crop.output": "Output file",
        "tool.crop.options": "Page range and target",
        "tool.crop.margins": "Crop margins (pt)",
        "tool.crop.top": "Top:",
        "tool.crop.bottom": "Bottom:",
        "tool.crop.left": "Left:",
        "tool.crop.right": "Right:",
        "tool.crop.pages_label": "Apply to:",
        "tool.crop.pages_all": "All pages",
        "tool.crop.pages_current": "Current page",
        "tool.crop.pages_custom": "Custom range",
        "tool.crop.subset_label": "Subset:",
        "tool.crop.subset_all": "All pages in range",
        "tool.crop.subset_odd": "Odd pages only",
        "tool.crop.subset_even": "Even pages only",
        "tool.crop.reset": "↺ Reset",
        "tool.crop.trim_5": "Trim 5%",
        "tool.crop.trim_10": "Trim 10%",
        "tool.crop.trim_half_in": "Trim 0.5 in",
        "tool.crop.draw_btn": "✂  Drag Crop Box on Page",
        "tool.crop.apply_preview": "✂  Crop / Preview (Enter)",
        "tool.crop.drag_hint": "💡 Drag a box on the page or enter margins. Press Enter or click Crop to preview. Use Ctrl+Z to undo.",
        "tool.crop.done": "Cropped PDF saved at:\n{path}",
        "tool.crop.status.done": "✔ Cropped → {name}",
        "tool.crop.status.preview_applied": "✔ Crop preview applied (Ctrl+Z to undo)",
        "tool.crop.status.undone": "↩ Crop undone (Ctrl+Y to redo)",
        "tool.crop.status.redone": "↪ Crop redone",
        "tool.crop.invalid_margins": "The crop margins exceed the page dimensions.",
        "tool.crop.no_pages": "No pages selected to crop.",
    },
    "pt": {
        "nav.crop": "Recortar",
        "tool.crop.name": "Recortar páginas",
        "tool.crop.desc": "Recorta uma ou várias páginas usando margens ou seleção visual estilo Foxit.",
        "tool.crop.btn": "Guardar",
        "tool.crop.source": "Ficheiro de origem",
        "tool.crop.output": "Ficheiro de saída",
        "tool.crop.options": "Intervalo e páginas alvo",
        "tool.crop.margins": "Margens de recorte (pt)",
        "tool.crop.top": "Superior:",
        "tool.crop.bottom": "Inferior:",
        "tool.crop.left": "Esquerda:",
        "tool.crop.right": "Direita:",
        "tool.crop.pages_label": "Aplicar a:",
        "tool.crop.pages_all": "Todas as páginas",
        "tool.crop.pages_current": "Página atual",
        "tool.crop.pages_custom": "Intervalo personalizado",
        "tool.crop.subset_label": "Subconjunto:",
        "tool.crop.subset_all": "Todas as páginas no intervalo",
        "tool.crop.subset_odd": "Apenas páginas ímpares",
        "tool.crop.subset_even": "Apenas páginas pares",
        "tool.crop.reset": "↺ Repor",
        "tool.crop.trim_5": "Cortar 5%",
        "tool.crop.trim_10": "Cortar 10%",
        "tool.crop.trim_half_in": "Cortar 0.5 in",
        "tool.crop.draw_btn": "✂  Desenhar Caixa de Recorte",
        "tool.crop.apply_preview": "✂  Recortar / Pré-visualizar (Enter)",
        "tool.crop.drag_hint": "💡 Arrasta uma caixa na página ou insere margens. Prime Enter ou clica em Recortar para ver o resultado. Usa Ctrl+Z para anular.",
        "tool.crop.done": "PDF recortado guardado em:\n{path}",
        "tool.crop.status.done": "✔ Recortado → {name}",
        "tool.crop.status.preview_applied": "✔ Pré-visualização de recorte aplicada (Ctrl+Z para anular)",
        "tool.crop.status.undone": "↩ Recorte anulado (Ctrl+Y para refazer)",
        "tool.crop.status.redone": "↪ Recorte refeito",
        "tool.crop.invalid_margins": "As margens de recorte excedem as dimensões da página.",
        "tool.crop.no_pages": "Nenhuma página selecionada para recortar.",
    },
    "es": {
        "nav.crop": "Recortar",
        "tool.crop.name": "Recortar páginas",
        "tool.crop.desc": "Recorta una o varias páginas usando márgenes o selección visual estilo Foxit.",
        "tool.crop.btn": "Guardar",
        "tool.crop.source": "Archivo de origen",
        "tool.crop.output": "Archivo de salida",
        "tool.crop.options": "Rango y páginas objetivo",
        "tool.crop.margins": "Márgenes de recorte (pt)",
        "tool.crop.top": "Superior:",
        "tool.crop.bottom": "Inferior:",
        "tool.crop.left": "Izquierda:",
        "tool.crop.right": "Derecha:",
        "tool.crop.pages_label": "Aplicar a:",
        "tool.crop.pages_all": "Todas las páginas",
        "tool.crop.pages_current": "Página actual",
        "tool.crop.pages_custom": "Rango personalizado",
        "tool.crop.subset_label": "Subconjunto:",
        "tool.crop.subset_all": "Todas las páginas en el rango",
        "tool.crop.subset_odd": "Solo páginas impares",
        "tool.crop.subset_even": "Solo páginas pares",
        "tool.crop.reset": "↺ Restablecer",
        "tool.crop.trim_5": "Cortar 5%",
        "tool.crop.trim_10": "Cortar 10%",
        "tool.crop.trim_half_in": "Cortar 0.5 in",
        "tool.crop.draw_btn": "✂  Dibujar Cuadro de Recorte",
        "tool.crop.apply_preview": "✂  Recortar / Vista previa (Enter)",
        "tool.crop.drag_hint": "💡 Arrastra un cuadro en la página o introduce márgenes. Pulsa Enter o haz clic en Recortar para previsualizar. Usa Ctrl+Z para deshacer.",
        "tool.crop.done": "PDF recortado guardado en:\n{path}",
        "tool.crop.status.done": "✔ Recortado → {name}",
        "tool.crop.status.preview_applied": "✔ Vista previa de recorte aplicada (Ctrl+Z para deshacer)",
        "tool.crop.status.undone": "↩ Recorte deshecho (Ctrl+Y para rehacer)",
        "tool.crop.status.redone": "↪ Recorte rehecho",
        "tool.crop.invalid_margins": "Los márgenes de recorte exceden las dimensiones de la página.",
        "tool.crop.no_pages": "No se han seleccionado páginas para recortar.",
    },
    "fr": {
        "nav.crop": "Recadrer",
        "tool.crop.name": "Recadrer les pages",
        "tool.crop.desc": "Recadrez une ou plusieurs pages à l'aide des marges ou de la sélection visuelle.",
        "tool.crop.btn": "Enregistrer",
        "tool.crop.source": "Fichier source",
        "tool.crop.output": "Fichier de sortie",
        "tool.crop.options": "Plage et pages cibles",
        "tool.crop.margins": "Marges de recadrage (pt)",
        "tool.crop.top": "Haut :",
        "tool.crop.bottom": "Bas :",
        "tool.crop.left": "Gauche :",
        "tool.crop.right": "Droite :",
        "tool.crop.pages_label": "Appliquer à :",
        "tool.crop.pages_all": "Toutes les pages",
        "tool.crop.pages_current": "Page actuelle",
        "tool.crop.pages_custom": "Plage personnalisée",
        "tool.crop.subset_label": "Sous-ensemble :",
        "tool.crop.subset_all": "Toutes les pages de la plage",
        "tool.crop.subset_odd": "Pages impaires uniquement",
        "tool.crop.subset_even": "Pages paires uniquement",
        "tool.crop.reset": "↺ Réinitialiser",
        "tool.crop.trim_5": "Rogner 5%",
        "tool.crop.trim_10": "Rogner 10%",
        "tool.crop.trim_half_in": "Rogner 0.5 in",
        "tool.crop.draw_btn": "✂  Dessiner la Zone de Recadrage",
        "tool.crop.apply_preview": "✂  Recadrer / Aperçu (Entrée)",
        "tool.crop.drag_hint": "💡 Glissez un cadre sur la page ou saisissez des marges. Appuyez sur Entrée ou cliquez sur Recadrer pour prévisualiser. Utilisez Ctrl+Z pour annuler.",
        "tool.crop.done": "PDF recadré enregistré sous :\n{path}",
        "tool.crop.status.done": "✔ Recadré → {name}",
        "tool.crop.status.preview_applied": "✔ Aperçu du recadrage appliqué (Ctrl+Z pour annuler)",
        "tool.crop.status.undone": "↩ Recadrage annulé (Ctrl+Y pour rétablir)",
        "tool.crop.status.redone": "↪ Recadrage rétabli",
        "tool.crop.invalid_margins": "Les marges de recadrage dépassent les dimensions de la page.",
        "tool.crop.no_pages": "Aucune page sélectionnée pour le recadrage.",
    },
    "de": {
        "nav.crop": "Zuschneiden",
        "tool.crop.name": "Seiten zuschneiden",
        "tool.crop.desc": "Seiten mit Randsteuerungen oder visueller Auswahl zuschneiden.",
        "tool.crop.btn": "Speichern",
        "tool.crop.source": "Quelldatei",
        "tool.crop.output": "Ausgabedatei",
        "tool.crop.options": "Seitenbereich und Ziel",
        "tool.crop.margins": "Zuschneideränder (pt)",
        "tool.crop.top": "Oben:",
        "tool.crop.bottom": "Unten:",
        "tool.crop.left": "Links:",
        "tool.crop.right": "Rechts:",
        "tool.crop.pages_label": "Anwenden auf:",
        "tool.crop.pages_all": "Alle Seiten",
        "tool.crop.pages_current": "Aktuelle Seite",
        "tool.crop.pages_custom": "Benutzerdefinierter Bereich",
        "tool.crop.subset_label": "Teilmenge:",
        "tool.crop.subset_all": "Alle Seiten im Bereich",
        "tool.crop.subset_odd": "Nur ungerade Seiten",
        "tool.crop.subset_even": "Nur gerade Seiten",
        "tool.crop.reset": "↺ Zurücksetzen",
        "tool.crop.trim_5": "5% beschneiden",
        "tool.crop.trim_10": "10% beschneiden",
        "tool.crop.trim_half_in": "0.5 in beschneiden",
        "tool.crop.draw_btn": "✂  Zuschnittbereich auf Seite ziehen",
        "tool.crop.apply_preview": "✂  Zuschneiden / Vorschau (Eingabe)",
        "tool.crop.drag_hint": "💡 Rahmen auf der Seite ziehen oder Ränder eingeben. Eingabe drücken oder Zuschneiden klicken für Vorschau. Strg+Z zum Rückgängigmachen.",
        "tool.crop.done": "Zugeschnittenes PDF gespeichert unter:\n{path}",
        "tool.crop.status.done": "✔ Zugeschnitten → {name}",
        "tool.crop.status.preview_applied": "✔ Zuschnitt-Vorschau angewendet (Strg+Z zum Rückgängigmachen)",
        "tool.crop.status.undone": "↩ Zuschnitt rückgängig gemacht (Strg+Y zum Wiederholen)",
        "tool.crop.status.redone": "↪ Zuschnitt wiederholt",
        "tool.crop.invalid_margins": "Die Schnittränder überschreiten die Seitenabmessungen.",
        "tool.crop.no_pages": "Keine Seiten zum Zuschneiden ausgewählt.",
    },
    "zh": {
        "nav.crop": "裁剪",
        "tool.crop.name": "裁剪页面",
        "tool.crop.desc": "使用边距控制或可视化选择裁剪单页或多页。",
        "tool.crop.btn": "保存",
        "tool.crop.source": "源文件",
        "tool.crop.output": "输出文件",
        "tool.crop.options": "页面范围与目标",
        "tool.crop.margins": "裁剪边距 (pt)",
        "tool.crop.top": "顶部：",
        "tool.crop.bottom": "底部：",
        "tool.crop.left": "左侧：",
        "tool.crop.right": "右侧：",
        "tool.crop.pages_label": "应用于：",
        "tool.crop.pages_all": "所有页面",
        "tool.crop.pages_current": "当前页面",
        "tool.crop.pages_custom": "自定义范围",
        "tool.crop.subset_label": "子集：",
        "tool.crop.subset_all": "范围内所有页面",
        "tool.crop.subset_odd": "仅奇数页",
        "tool.crop.subset_even": "仅偶数页",
        "tool.crop.reset": "↺ 重置",
        "tool.crop.trim_5": "裁剪 5%",
        "tool.crop.trim_10": "裁剪 10%",
        "tool.crop.trim_half_in": "裁剪 0.5 英寸",
        "tool.crop.draw_btn": "✂  在页面上拖动裁剪框",
        "tool.crop.apply_preview": "✂  裁剪 / 预览 (Enter)",
        "tool.crop.drag_hint": "💡 在页面上拖动选框或输入边距。按 Enter 或点击裁剪以预览效果。使用 Ctrl+Z 撤销。",
        "tool.crop.done": "已裁剪的 PDF 保存至：\n{path}",
        "tool.crop.status.done": "✔ 已裁剪 → {name}",
        "tool.crop.status.preview_applied": "✔ 已应用裁剪预览（按 Ctrl+Z 撤销）",
        "tool.crop.status.undone": "↩ 已撤销裁剪（按 Ctrl+Y 重做）",
        "tool.crop.status.redone": "↪ 已重做裁剪",
        "tool.crop.invalid_margins": "裁剪边距超过了页面尺寸。",
        "tool.crop.no_pages": "未选择要裁剪的页面。",
    },
    "it": {
        "nav.crop": "Ritaglia",
        "tool.crop.name": "Ritaglia pagine",
        "tool.crop.desc": "Ritaglia una o più pagine utilizzando i margini o la selezione visiva.",
        "tool.crop.btn": "Salva",
        "tool.crop.source": "File sorgente",
        "tool.crop.output": "File di output",
        "tool.crop.options": "Intervallo e pagine di destinazione",
        "tool.crop.margins": "Margini di ritaglio (pt)",
        "tool.crop.top": "Superiore:",
        "tool.crop.bottom": "Inferiore:",
        "tool.crop.left": "Sinistra:",
        "tool.crop.right": "Destra:",
        "tool.crop.pages_label": "Applica a:",
        "tool.crop.pages_all": "Tutte le pagine",
        "tool.crop.pages_current": "Pagina corrente",
        "tool.crop.pages_custom": "Intervallo personalizzato",
        "tool.crop.subset_label": "Sottoinsieme:",
        "tool.crop.subset_all": "Tutte le pagine nell'intervallo",
        "tool.crop.subset_odd": "Solo pagine dispari",
        "tool.crop.subset_even": "Solo pagine pari",
        "tool.crop.reset": "↺ Ripristina",
        "tool.crop.trim_5": "Taglia 5%",
        "tool.crop.trim_10": "Taglia 10%",
        "tool.crop.trim_half_in": "Taglia 0.5 in",
        "tool.crop.draw_btn": "✂  Disegna Riquadro sulla Pagina",
        "tool.crop.apply_preview": "✂  Ritaglia / Anteprima (Invio)",
        "tool.crop.drag_hint": "💡 Trascina un riquadro sulla pagina o inserisci i margini. Premi Invio o clicca Ritaglia per l'anteprima. Usa Ctrl+Z per annullare.",
        "tool.crop.done": "PDF ritagliato salvato in:\n{path}",
        "tool.crop.status.done": "✔ Ritagliato → {name}",
        "tool.crop.status.preview_applied": "✔ Anteprima ritaglio applicata (Ctrl+Z per annullare)",
        "tool.crop.status.undone": "↩ Ritaglio annullato (Ctrl+Y per ripristinare)",
        "tool.crop.status.redone": "↪ Ritaglio ripristinato",
        "tool.crop.invalid_margins": "I margini di ritaglio superano le dimensioni della pagina.",
        "tool.crop.no_pages": "Nessuna pagina selezionata da ritagliare.",
    },
    "nl": {
        "nav.crop": "Bijsnijden",
        "tool.crop.name": "Pagina's bijsnijden",
        "tool.crop.desc": "Snijd een of meerdere pagina's bij met margeregelaars of visuele selectie.",
        "tool.crop.btn": "Opslaan",
        "tool.crop.source": "Bronbestand",
        "tool.crop.output": "Uitvoerbestand",
        "tool.crop.options": "Paginabereik en doel",
        "tool.crop.margins": "Bijsnijdmarges (pt)",
        "tool.crop.top": "Boven:",
        "tool.crop.bottom": "Onder:",
        "tool.crop.left": "Links:",
        "tool.crop.right": "Rechts:",
        "tool.crop.pages_label": "Toepassen op:",
        "tool.crop.pages_all": "Alle pagina's",
        "tool.crop.pages_current": "Huidige pagina",
        "tool.crop.pages_custom": "Aangepast bereik",
        "tool.crop.subset_label": "Deelverzameling:",
        "tool.crop.subset_all": "Alle pagina's in bereik",
        "tool.crop.subset_odd": "Alleen oneven pagina's",
        "tool.crop.subset_even": "Alleen even pagina's",
        "tool.crop.reset": "↺ Herstellen",
        "tool.crop.trim_5": "5% bijsnijden",
        "tool.crop.trim_10": "10% bijsnijden",
        "tool.crop.trim_half_in": "0.5 in bijsnijden",
        "tool.crop.draw_btn": "✂  Bijsnijdkader op Pagina Slepen",
        "tool.crop.apply_preview": "✂  Bijsnijden / Voorbeeld (Enter)",
        "tool.crop.drag_hint": "💡 Sleep een kader op de pagina of voer marges in. Druk op Enter of klik op Bijsnijden voor voorbeeld. Gebruik Ctrl+Z om te herstellen.",
        "tool.crop.done": "Bijgesneden PDF opgeslagen op:\n{path}",
        "tool.crop.status.done": "✔ Bijgesneden → {name}",
        "tool.crop.status.preview_applied": "✔ Bijsnijdvoorbeeld toegepast (Ctrl+Z om ongedaan te maken)",
        "tool.crop.status.undone": "↩ Bijsnijden ongedaan gemaakt (Ctrl+Y om opnieuw uit te voeren)",
        "tool.crop.status.redone": "↪ Bijsnijden opnieuw uitgevoerd",
        "tool.crop.invalid_margins": "De bijsnijdmarges overschrijden de pagina-afmetingen.",
        "tool.crop.no_pages": "Geen pagina's geselecteerd om bij te snijden.",
    },
}

for _lang, _entries in _CROP_I18N.items():
    if _lang in i18n._TRANSLATIONS:
        i18n._TRANSLATIONS[_lang].update(_entries)


class FocusSpinBox(QSpinBox):
    """QSpinBox that ignores mouse wheel events unless it explicitly has keyboard focus."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if self.lineEdit():
            self.lineEdit().setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        has_focus = self.hasFocus() or (self.lineEdit() and self.lineEdit().hasFocus())
        if has_focus:
            super().wheelEvent(event)
        else:
            event.ignore()


class FocusComboBox(QComboBox):
    """QComboBox that ignores mouse wheel events unless it explicitly has keyboard focus."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class TabCortar(BasePage):
    """Crop PDF pages with Foxit-style margin controls, range selection, live preview and undo/redo."""

    crop_changed = Signal(object)
    crop_mode_toggled = Signal(bool)
    crops_changed = Signal(object)

    def __init__(self, status_fn):
        super().__init__("fa5s.crop-alt", t("tool.crop.name"),
                         t("tool.crop.desc"),
                         t("tool.crop.btn"), status_fn)
        self._pipeline_supported = True
        self._page_count = 0
        self._ref_width = 595.0
        self._ref_height = 842.0
        self._updating = False

        self._applied_crops: dict[int, tuple[float, float, float, float]] = {}
        self._undo_stack: list[dict[int, tuple[float, float, float, float]]] = []
        self._redo_stack: list[dict[int, tuple[float, float, float, float]]] = []

        f = self._form

        sec_src = section(t("tool.crop.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try:
            self.drop_in.btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in)
        f.addWidget(self.lbl_info)

        # ── Interactive Crop Selection Button (Foxit Style) ───────────
        self.btn_draw_crop = QPushButton(t("tool.crop.draw_btn"))
        self.btn_draw_crop.setIcon(qta.icon("fa5s.crop-alt", color=TEXT_PRI))
        self.btn_draw_crop.setCheckable(True)
        self.btn_draw_crop.setChecked(True)
        self.btn_draw_crop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_draw_crop.setStyleSheet(
            f"QPushButton:checked {{ background: #0D3D38; border: 1.5px solid {ACCENT}; color: {ACCENT}; font-weight: bold; padding: 8px; }}"
            f"QPushButton {{ padding: 8px; font-weight: 600; }}"
        )
        self.btn_draw_crop.clicked.connect(self._on_draw_btn_clicked)
        f.addWidget(self.btn_draw_crop)

        # Page range & targets
        grp_opts = QGroupBox(t("tool.crop.options"))
        form_opts = QFormLayout(grp_opts)
        form_opts.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cmb_page_mode = FocusComboBox()
        self.cmb_page_mode.addItems([
            t("tool.crop.pages_all"),
            t("tool.crop.pages_current"),
            t("tool.crop.pages_custom"),
        ])
        self.cmb_page_mode.currentIndexChanged.connect(self._on_mode_changed)
        form_opts.addRow(t("tool.crop.pages_label"), self.cmb_page_mode)

        self.spin_current_page = FocusSpinBox()
        self.spin_current_page.setRange(1, 99999)
        self.spin_current_page.setValue(1)
        self.spin_current_page.valueChanged.connect(self._on_controls_changed)
        self.spin_current_page.setVisible(False)
        form_opts.addRow("", self.spin_current_page)

        self.edit_custom_pages = QLineEdit()
        self.edit_custom_pages.setPlaceholderText("e.g.: 1,3,5-8")
        self.edit_custom_pages.textChanged.connect(self._on_controls_changed)
        self.edit_custom_pages.setVisible(False)
        form_opts.addRow("", self.edit_custom_pages)

        self.cmb_subset = FocusComboBox()
        self.cmb_subset.addItems([
            t("tool.crop.subset_all"),
            t("tool.crop.subset_odd"),
            t("tool.crop.subset_even"),
        ])
        self.cmb_subset.currentIndexChanged.connect(self._on_controls_changed)
        form_opts.addRow(t("tool.crop.subset_label"), self.cmb_subset)

        f.addWidget(grp_opts)

        # Margins & presets
        grp_margins = QGroupBox(t("tool.crop.margins"))
        v_margins = QVBoxLayout(grp_margins)
        v_margins.setSpacing(8)

        grid = QGridLayout()
        grid.setSpacing(6)

        def _make_spin():
            sb = FocusSpinBox()
            sb.setRange(0, 5000)
            sb.setValue(0)
            sb.setSuffix(" pt")
            sb.valueChanged.connect(self._on_controls_changed)
            return sb

        self.spin_top = _make_spin()
        self.spin_bottom = _make_spin()
        self.spin_left = _make_spin()
        self.spin_right = _make_spin()

        grid.addWidget(QLabel(t("tool.crop.top")), 0, 0, Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.spin_top, 0, 1)
        grid.addWidget(QLabel(t("tool.crop.bottom")), 0, 2, Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.spin_bottom, 0, 3)

        grid.addWidget(QLabel(t("tool.crop.left")), 1, 0, Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.spin_left, 1, 1)
        grid.addWidget(QLabel(t("tool.crop.right")), 1, 2, Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.spin_right, 1, 3)

        v_margins.addLayout(grid)

        self.lbl_dimensions = QLabel("")
        self.lbl_dimensions.setStyleSheet("font-weight: 600; color: #14B8A6; padding: 2px;")
        v_margins.addWidget(self.lbl_dimensions)

        # Apply preview button
        self.btn_apply_crop = QPushButton(t("tool.crop.apply_preview"))
        self.btn_apply_crop.setIcon(qta.icon("fa5s.check", color="#FFFFFF"))
        self.btn_apply_crop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_crop.setStyleSheet(
            f"QPushButton {{ background: {ACCENT}; color: white; font-weight: bold; padding: 8px 14px; border-radius: 6px; border: none; font-size: 11pt; }}"
            f"QPushButton:hover {{ background: #0D9488; }}"
            f"QPushButton:pressed {{ background: #0F766E; }}"
        )
        self.btn_apply_crop.clicked.connect(self.apply_crop_preview)
        v_margins.addWidget(self.btn_apply_crop)

        # Undo / Redo buttons
        undo_redo_row = QHBoxLayout()
        undo_redo_row.setSpacing(6)

        self.btn_undo = QPushButton("↶ " + t("btn.undo"))
        self.btn_undo.setToolTip("Ctrl+Z")
        self.btn_undo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_undo.clicked.connect(self._undo)
        self.btn_undo.setEnabled(False)

        self.btn_redo = QPushButton("↷ " + t("btn.redo"))
        self.btn_redo.setToolTip("Ctrl+Y")
        self.btn_redo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_redo.clicked.connect(self._redo)
        self.btn_redo.setEnabled(False)

        undo_redo_row.addWidget(self.btn_undo)
        undo_redo_row.addWidget(self.btn_redo)
        v_margins.addLayout(undo_redo_row)

        # Quick preset buttons (Foxit style)
        btn_presets = QHBoxLayout()
        btn_presets.setSpacing(4)

        self.btn_reset = QPushButton(t("tool.crop.reset"))
        self.btn_reset.clicked.connect(self._preset_reset)
        btn_presets.addWidget(self.btn_reset)

        self.btn_trim5 = QPushButton(t("tool.crop.trim_5"))
        self.btn_trim5.clicked.connect(lambda: self._preset_percent(0.05))
        btn_presets.addWidget(self.btn_trim5)

        self.btn_trim10 = QPushButton(t("tool.crop.trim_10"))
        self.btn_trim10.clicked.connect(lambda: self._preset_percent(0.10))
        btn_presets.addWidget(self.btn_trim10)

        self.btn_trim_in = QPushButton(t("tool.crop.trim_half_in"))
        self.btn_trim_in.clicked.connect(self._preset_half_inch)
        btn_presets.addWidget(self.btn_trim_in)

        v_margins.addLayout(btn_presets)

        lbl_hint = QLabel(t("tool.crop.drag_hint"))
        lbl_hint.setWordWrap(True)
        lbl_hint.setStyleSheet(f"color: {TEXT_SEC}; font-size: 10pt;")
        v_margins.addWidget(lbl_hint)

        f.addWidget(grp_margins)

        sec_out = section(t("tool.crop.output"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit("cropped.pdf", save=True, default_name="cropped.pdf")
        f.addWidget(self.drop_out)
        f.addStretch()

        self._compact_hidden = [sec_src, self.drop_in, self.lbl_info]
        sec_out.setVisible(False)
        self.drop_out.setVisible(False)

        # Keyboard shortcuts within the tool panel
        sc_enter1 = QShortcut(QKeySequence(Qt.Key.Key_Return), self, self.apply_crop_preview)
        sc_enter2 = QShortcut(QKeySequence(Qt.Key.Key_Enter), self, self.apply_crop_preview)
        for sc in (sc_enter1, sc_enter2):
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def _on_draw_btn_clicked(self):
        active = self.btn_draw_crop.isChecked()
        self.crop_mode_toggled.emit(active)

    def _on_mode_changed(self, idx: int):
        self.spin_current_page.setVisible(idx == 1)
        self.edit_custom_pages.setVisible(idx == 2)
        self._on_controls_changed()

    def _preset_reset(self):
        if self._applied_crops:
            self._undo_stack.append(dict(self._applied_crops))
            self._redo_stack.clear()
            self._applied_crops = {}
            self._on_crop_history_changed()
            self._status(t("tool.crop.reset"))
            return

        self._updating = True
        self.spin_top.setValue(0)
        self.spin_bottom.setValue(0)
        self.spin_left.setValue(0)
        self.spin_right.setValue(0)
        self._updating = False
        self._on_controls_changed()

    def _preset_percent(self, pct: float):
        self._updating = True
        h_trim = int(round(self._ref_height * pct))
        w_trim = int(round(self._ref_width * pct))
        self.spin_top.setValue(h_trim)
        self.spin_bottom.setValue(h_trim)
        self.spin_left.setValue(w_trim)
        self.spin_right.setValue(w_trim)
        self._updating = False
        self._on_controls_changed()

    def _preset_half_inch(self):
        self._updating = True
        pts = 36  # 0.5 in * 72 pt/in
        self.spin_top.setValue(pts)
        self.spin_bottom.setValue(pts)
        self.spin_left.setValue(pts)
        self.spin_right.setValue(pts)
        self._updating = False
        self._on_controls_changed()

    def _get_target_pages(self) -> list[int]:
        if self._page_count <= 0:
            return []
        mode = self.cmb_page_mode.currentIndex()
        if mode == 0:
            candidates = list(range(self._page_count))
        elif mode == 1:
            pg = self.spin_current_page.value() - 1
            candidates = [pg] if 0 <= pg < self._page_count else [0]
        else:
            txt = self.edit_custom_pages.text().strip()
            if not txt:
                candidates = list(range(self._page_count))
            else:
                try:
                    candidates = parse_pages(txt, self._page_count)
                except ValueError:
                    candidates = []

        subset = self.cmb_subset.currentIndex()
        if subset == 1:  # Odd pages (1, 3, 5...) -> 0, 2, 4...
            return [p for p in candidates if (p + 1) % 2 != 0]
        elif subset == 2:  # Even pages (2, 4, 6...) -> 1, 3, 5...
            return [p for p in candidates if (p + 1) % 2 == 0]
        return candidates

    def _update_dim_label(self):
        top = self.spin_top.value()
        bottom = self.spin_bottom.value()
        left = self.spin_left.value()
        right = self.spin_right.value()
        w = max(0.0, self._ref_width - left - right)
        h = max(0.0, self._ref_height - top - bottom)
        w_mm = w * 25.4 / 72.0
        h_mm = h * 25.4 / 72.0
        self.lbl_dimensions.setText(f"📐  {w:.0f} × {h:.0f} pt  ({w_mm:.0f} × {h_mm:.0f} mm)")

    def _on_controls_changed(self):
        if self._updating:
            return
        self._update_dim_label()
        self._emit_preview()

    def _emit_preview(self):
        targets = set(self._get_target_pages())
        margins = (
            self.spin_top.value(),
            self.spin_bottom.value(),
            self.spin_left.value(),
            self.spin_right.value(),
        )
        self.crop_changed.emit({
            "margins": margins,
            "targets": targets,
            "ref_page": self.spin_current_page.value() - 1,
        })

    def apply_crop_preview(self):
        """Commit the current margin controls into the applied in-memory crop state."""
        pdf_path = self.drop_in.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            win = self.window()
            viewer = getattr(win, "_viewer", None)
            if viewer and viewer.current_path():
                pdf_path = viewer.current_path()
        if not pdf_path or not os.path.isfile(pdf_path):
            return

        targets = self._get_target_pages()
        if not targets:
            return

        top_m = self.spin_top.value()
        bot_m = self.spin_bottom.value()
        left_m = self.spin_left.value()
        right_m = self.spin_right.value()

        if top_m == 0 and bot_m == 0 and left_m == 0 and right_m == 0:
            return

        doc = None
        try:
            doc = self._open_fitz(pdf_path)
            new_crops = dict(self._applied_crops)
            any_changed = False
            for idx in targets:
                if idx < 0 or idx >= doc.page_count:
                    continue
                page = doc[idx]
                if idx in self._applied_crops:
                    base_x0, base_y0, base_x1, base_y1 = self._applied_crops[idx]
                else:
                    base_x0, base_y0, base_x1, base_y1 = page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1

                new_x0 = base_x0 + left_m
                new_y0 = base_y0 + top_m
                new_x1 = base_x1 - right_m
                new_y1 = base_y1 - bot_m

                if (new_x1 - new_x0 < 10) or (new_y1 - new_y0 < 10):
                    continue

                crop_rect = fitz.Rect(new_x0, new_y0, new_x1, new_y1) & page.mediabox
                if not crop_rect.is_empty and crop_rect.width >= 10 and crop_rect.height >= 10:
                    new_crops[idx] = (crop_rect.x0, crop_rect.y0, crop_rect.x1, crop_rect.y1)
                    any_changed = True

            if not any_changed:
                QMessageBox.warning(self, t("msg.warning"), t("tool.crop.invalid_margins"))
                return

            self._undo_stack.append(dict(self._applied_crops))
            self._redo_stack.clear()
            self._applied_crops = new_crops

            self._on_crop_history_changed()
            self._status(t("tool.crop.status.preview_applied"))
        except Exception as exc:
            show_error(self, exc)
        finally:
            if doc is not None:
                with contextlib.suppress(Exception):
                    doc.close()

    def _undo(self):
        if not self._undo_stack:
            self._status("ℹ  " + t("edit.undo_tip") + ": " + t("recent.empty"))
            return
        self._redo_stack.append(dict(self._applied_crops))
        self._applied_crops = self._undo_stack.pop()
        self._on_crop_history_changed()
        self._status(t("tool.crop.status.undone"))

    def _redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(dict(self._applied_crops))
        self._applied_crops = self._redo_stack.pop()
        self._on_crop_history_changed()
        self._status(t("tool.crop.status.redone"))

    def _on_crop_history_changed(self):
        pdf_path = self.drop_in.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            win = self.window()
            viewer = getattr(win, "_viewer", None)
            if viewer and viewer.current_path():
                pdf_path = viewer.current_path()
        ref_idx = max(0, min(self.spin_current_page.value() - 1, self._page_count - 1))
        if ref_idx in self._applied_crops:
            c = self._applied_crops[ref_idx]
            self._ref_width = c[2] - c[0]
            self._ref_height = c[3] - c[1]
        elif pdf_path and os.path.isfile(pdf_path):
            try:
                doc = self._open_fitz(pdf_path)
                r = doc[ref_idx].rect
                self._ref_width = r.width
                self._ref_height = r.height
                doc.close()
            except Exception:
                pass

        self._updating = True
        self.spin_top.setValue(0)
        self.spin_bottom.setValue(0)
        self.spin_left.setValue(0)
        self.spin_right.setValue(0)
        self._updating = False

        self._update_dim_label()
        self.crop_changed.emit(None)
        self.crops_changed.emit(self._applied_crops)
        self.btn_undo.setEnabled(len(self._undo_stack) > 0)
        self.btn_redo.setEnabled(len(self._redo_stack) > 0)

    def on_canvas_crop_selected(self, page_idx: int, rect: tuple):
        """Called when the user drags a rubber-band rectangle on the viewer canvas."""
        if len(rect) >= 6:
            p_x0, p_y0, p_x1, p_y1, pw, ph = rect[:6]
            self._ref_width = pw
            self._ref_height = ph
        else:
            p_x0, p_y0, p_x1, p_y1 = rect
            doc_path = self.drop_in.path()
            if not doc_path or not os.path.isfile(doc_path):
                win = self.window()
                viewer = getattr(win, "_viewer", None)
                if viewer and viewer.current_path():
                    doc_path = viewer.current_path()
            if doc_path and os.path.isfile(doc_path):
                try:
                    doc = self._open_fitz(doc_path)
                    p_rect = doc[page_idx].rect
                    if page_idx in self._applied_crops:
                        c = self._applied_crops[page_idx]
                        self._ref_width = c[2] - c[0]
                        self._ref_height = c[3] - c[1]
                    else:
                        self._ref_width = p_rect.width
                        self._ref_height = p_rect.height
                    doc.close()
                except Exception:
                    pass

        left = max(0.0, p_x0)
        top = max(0.0, p_y0)
        right = max(0.0, self._ref_width - p_x1)
        bottom = max(0.0, self._ref_height - p_y1)

        self._updating = True
        self.spin_current_page.setValue(page_idx + 1)
        self.spin_left.setValue(int(round(left)))
        self.spin_top.setValue(int(round(top)))
        self.spin_right.setValue(int(round(right)))
        self.spin_bottom.setValue(int(round(bottom)))
        self._updating = False

        self._update_dim_label()
        self._emit_preview()

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if p:
            self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self._maybe_prompt_password(p):
            self.drop_in.blockSignals(True)
            self.drop_in.set_path("")
            self.drop_in.blockSignals(False)
            return
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_cropped" + ext)

        self._applied_crops = {}
        self._undo_stack = []
        self._redo_stack = []
        self.btn_undo.setEnabled(False)
        self.btn_redo.setEnabled(False)

        try:
            doc = self._open_fitz(p)
            self._page_count = doc.page_count
            if self._page_count > 0:
                r0 = doc[0].rect
                self._ref_width = r0.width
                self._ref_height = r0.height
                self.spin_current_page.setMaximum(self._page_count)
            doc.close()
        except Exception as e:
            self.lbl_info.setText(t("tool.split.error_info", e=e))
            return

        self._updating = True
        self.spin_top.setValue(0)
        self.spin_bottom.setValue(0)
        self.spin_left.setValue(0)
        self.spin_right.setValue(0)
        self._updating = False

        self.lbl_info.setText(t("edit.status.pages", n=self._page_count))
        self._update_dim_label()
        self._emit_preview()
        self.crops_changed.emit(self._applied_crops)

    def auto_load(self, path: str):
        if path:
            self._load_input(path)

    def update_theme(self, dark: bool) -> None:
        super().update_theme(dark)
        pri = TEXT_PRI if dark else _LQ
        self.btn_reset.setStyleSheet(f"color: {pri};")
        if hasattr(self, "btn_undo"):
            self.btn_undo.setStyleSheet(f"color: {pri};")
        if hasattr(self, "btn_redo"):
            self.btn_redo.setStyleSheet(f"color: {pri};")

    def _run(self):
        pdf_path = self.drop_in.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            win = self.window()
            viewer = getattr(win, "_viewer", None)
            if viewer and viewer.current_path():
                pdf_path = viewer.current_path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.select_valid_pdf"))
            return

        top_m = self.spin_top.value()
        bot_m = self.spin_bottom.value()
        left_m = self.spin_left.value()
        right_m = self.spin_right.value()

        crops_to_save = dict(self._applied_crops)

        if top_m > 0 or bot_m > 0 or left_m > 0 or right_m > 0:
            targets = self._get_target_pages()
            doc_probe = None
            try:
                doc_probe = self._open_fitz(pdf_path)
                for idx in targets:
                    if idx < 0 or idx >= doc_probe.page_count:
                        continue
                    page = doc_probe[idx]
                    if idx in crops_to_save:
                        base_x0, base_y0, base_x1, base_y1 = crops_to_save[idx]
                    else:
                        base_x0, base_y0, base_x1, base_y1 = page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1
                    new_x0 = base_x0 + left_m
                    new_y0 = base_y0 + top_m
                    new_x1 = base_x1 - right_m
                    new_y1 = base_y1 - bot_m
                    crop_rect = fitz.Rect(new_x0, new_y0, new_x1, new_y1) & page.mediabox
                    if not crop_rect.is_empty and crop_rect.width >= 10 and crop_rect.height >= 10:
                        crops_to_save[idx] = (crop_rect.x0, crop_rect.y0, crop_rect.x1, crop_rect.y1)
            finally:
                if doc_probe is not None:
                    doc_probe.close()

        if not crops_to_save:
            QMessageBox.warning(self, t("msg.warning"), t("tool.crop.no_pages"))
            return

        # Always open a Save As dialog so the user can choose a destination file and name
        default_name = "cropped.pdf"
        if pdf_path:
            base, ext = os.path.splitext(os.path.basename(pdf_path))
            default_name = f"{base}_cropped{ext}"
        start_dir = os.path.dirname(pdf_path) if pdf_path else ""
        out_path = self._prompt_save_as(default_name, start_dir)
        if not out_path:
            return
        self.drop_out.set_path(out_path)

        win = self.window()
        viewer = getattr(win, "_viewer", None)

        try:
            doc = self._open_fitz(pdf_path)
            try:
                for idx, crop_tuple in crops_to_save.items():
                    if 0 <= idx < doc.page_count:
                        page = doc[idx]
                        crop_rect = fitz.Rect(crop_tuple) & page.mediabox
                        if not crop_rect.is_empty and crop_rect.width >= 10 and crop_rect.height >= 10:
                            page.set_cropbox(crop_rect)

                # Release document locks in viewer if saving onto an open file
                if viewer and viewer.current_path() and os.path.abspath(viewer.current_path()) == os.path.abspath(out_path):
                    viewer._canvas.close_doc()
                    if viewer._fitz_doc:
                        with contextlib.suppress(Exception):
                            viewer._fitz_doc.close()
                        viewer._fitz_doc = None
                    viewer._thumbnails._stop_all_workers()

                atomic_pdf_write(
                    doc, out_path, sources=[pdf_path],
                    save_opts={"garbage": 4, "deflate": True},
                    close_writer=True,
                )
            finally:
                with contextlib.suppress(Exception):
                    doc.close()

            self._status(t("tool.crop.status.done", name=os.path.basename(out_path)))
            msg = t("tool.crop.done", path=out_path)

            if win and hasattr(win, "_cleanup_pipeline") and viewer:
                win._cleanup_pipeline(id(viewer))

            if viewer:
                viewer.load(out_path)

            QMessageBox.information(self, t("msg.done"), msg)
        except Exception as e:
            show_error(self, e)

