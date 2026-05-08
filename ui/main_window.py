"""Lab Layout Tool — main window.

Multi-room project editor:
- Project-level metadata at the top (job name, job number, technician, date,
  product line, room count)
- Sidebar tree on the left showing Project → Rooms → Valve tags for navigation
- Room tabs on the right; each tab has the 4 category panels + a tag input
  per valve

Follows the ATS / Phoenix Controls unified design system.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, QSettings, Qt, QThread, Signal
from PySide6.QtGui import QAction, QCursor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import updater
from updater import UpdateInfo, check_for_update, download_and_apply

from cad import blocks
from cad.blocks import (
    CATEGORIES,
    BlockVariant,
    ProductLine,
    list_variants,
    resolve_block_path,
)

from .components import (
    BackgroundWatermarkWidget,
    HintLabel,
    JobBrowserDialog,
    NoScrollComboBox,
    NoScrollDateEdit,
    NoScrollSpinBox,
    PageSubtitle,
    PageTitle,
    Panel,
    PreferencesDialog,
    PrimaryButton,
    SecondaryButton,
    SectionTitle,
    TertiaryButton,
    UpdateBanner,
    WelcomeDialog,
    button_row,
)
from .pbc import PBCSection
from .style import _resource_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = PROJECT_ROOT / "jobs"

APP_NAME = "Lab Layout Tool"
ORG_NAME = "ATS Inc"

CATEGORY_LABELS = {
    "SAV": "Supply Air Valves",
    "GEX": "General Exhaust Valves",
    "FEV": "Fume Hood Exhaust Valves",
    "AUX": "All Other Exhausts",
}


# ── Category section: count spinner + per-row variant + tag inputs ────────────


class CategorySection(Panel):
    """A panel for one valve category. Each row: variant dropdown + tag text box."""

    changed = Signal()  # emitted when count, variant, or tag changes

    def __init__(self, category: str, title: str, parent=None):
        super().__init__(title=title, parent=parent)
        self.category = category
        self._variants: list[BlockVariant] = []
        self._combos: list[NoScrollComboBox] = []
        self._tags: list[QLineEdit] = []
        # Up/down reorder buttons live alongside each row's combo + tag.
        # Tracking them lets _refresh_reorder_buttons disable the first row's
        # ↑ and the last row's ↓ so users can't move past either edge.
        self._up_btns: list[TertiaryButton] = []
        self._down_btns: list[TertiaryButton] = []

        body: QVBoxLayout = self.layout()  # provided by Panel

        count_row = QHBoxLayout()
        count_row.setSpacing(8)
        count_label = QLabel("Count:")
        count_label.setObjectName("ProjectSubtitle")
        count_row.addWidget(count_label)
        self.count_spin = NoScrollSpinBox()
        self.count_spin.setRange(0, 32)
        self.count_spin.setMinimumHeight(32)
        self.count_spin.setFixedWidth(80)
        self.count_spin.valueChanged.connect(self._on_count_changed)
        count_row.addWidget(self.count_spin)
        count_row.addStretch(1)
        body.addLayout(count_row)

        # Header row showing what each column means (only visible when there are rows)
        self._header_widget = QWidget()
        header_layout = QHBoxLayout(self._header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        idx_h = QLabel("")
        idx_h.setFixedWidth(32)
        header_layout.addWidget(idx_h)
        var_h = HintLabel("Variant")
        header_layout.addWidget(var_h, 1)
        tag_h = HintLabel("Tag")
        tag_h.setFixedWidth(140)
        header_layout.addWidget(tag_h)
        # Spacers for the reorder column so the header columns line up with
        # the body rows (each row has up + down buttons at 32px each).
        reorder_h = HintLabel("Order")
        reorder_h.setFixedWidth(32 + 8 + 32)   # ↑ + spacing + ↓
        reorder_h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(reorder_h)
        body.addWidget(self._header_widget)
        self._header_widget.hide()

        self.rows_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(6)
        body.addWidget(self.rows_widget)

        self._empty_hint = HintLabel(
            "No DWG blocks found for this category. "
            "Drop files into blocks/<product>/<category>/."
        )
        body.addWidget(self._empty_hint)
        self._empty_hint.hide()

    def set_variants(self, variants: list[BlockVariant]):
        self._variants = variants
        for combo in self._combos:
            self._populate(combo)
        self._refresh_hint_visibility()

    def _populate(self, combo: NoScrollComboBox):
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        if not self._variants:
            combo.addItem("(no DWG blocks found)", None)
            combo.setEnabled(False)
        else:
            combo.setEnabled(True)
            for v in self._variants:
                combo.addItem(v.label, v)
            if current is not None:
                idx = combo.findData(current)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _on_count_changed(self, n: int):
        while len(self._combos) < n:
            i = len(self._combos) + 1
            row = QHBoxLayout()
            row.setSpacing(8)
            idx_label = QLabel(f"#{i}")
            idx_label.setObjectName("ProjectSubtitle")
            idx_label.setFixedWidth(32)
            row.addWidget(idx_label)
            combo = NoScrollComboBox()
            combo.setMinimumHeight(32)
            self._populate(combo)
            combo.currentIndexChanged.connect(self.changed.emit)
            row.addWidget(combo, 1)
            tag_edit = QLineEdit()
            tag_edit.setPlaceholderText("e.g. PSV-1")
            tag_edit.setMinimumHeight(32)
            tag_edit.setFixedWidth(140)
            tag_edit.textChanged.connect(self.changed.emit)
            row.addWidget(tag_edit)
            # Reorder buttons. Lambdas capture the row index; rows never get
            # inserted/removed from the layout (we swap CONTENTS, not widgets),
            # so the captured int stays valid for the row's lifetime.
            row_idx = i - 1
            up_btn = TertiaryButton("↑")
            up_btn.setFixedWidth(32)
            up_btn.setMinimumHeight(32)
            up_btn.setToolTip("Move this valve up — affects MSTP chain order")
            up_btn.clicked.connect(
                lambda _checked=False, idx=row_idx: self._move_row(idx, -1)
            )
            row.addWidget(up_btn)
            down_btn = TertiaryButton("↓")
            down_btn.setFixedWidth(32)
            down_btn.setMinimumHeight(32)
            down_btn.setToolTip("Move this valve down — affects MSTP chain order")
            down_btn.clicked.connect(
                lambda _checked=False, idx=row_idx: self._move_row(idx, +1)
            )
            row.addWidget(down_btn)
            self.rows_layout.addLayout(row)
            self._combos.append(combo)
            self._tags.append(tag_edit)
            self._up_btns.append(up_btn)
            self._down_btns.append(down_btn)
        while len(self._combos) > n:
            self._combos.pop()
            self._tags.pop()
            self._up_btns.pop()
            self._down_btns.pop()
            row_item = self.rows_layout.takeAt(self.rows_layout.count() - 1)
            _delete_layout(row_item)
        self._header_widget.setVisible(n > 0)
        self._refresh_hint_visibility()
        self._refresh_reorder_buttons()
        self.changed.emit()

    def _refresh_reorder_buttons(self):
        """Disable ↑ on the first row and ↓ on the last row."""
        n = len(self._up_btns)
        for i, btn in enumerate(self._up_btns):
            btn.setEnabled(i > 0)
        for i, btn in enumerate(self._down_btns):
            btn.setEnabled(i < n - 1)

    def _move_row(self, idx: int, delta: int):
        """Swap row `idx`'s contents with its neighbor at `idx + delta`.

        Swaps VALUES (combo selection + tag text) rather than the widgets
        themselves — simpler and avoids re-wiring the captured-index lambdas
        on the up/down buttons. Reorder affects flatten_job's chain order,
        which determines MSTP wiring sequence.
        """
        target = idx + delta
        if not (0 <= idx < len(self._combos)) or not (0 <= target < len(self._combos)):
            return
        a_data = self._combos[idx].currentData()
        b_data = self._combos[target].currentData()
        a_tag = self._tags[idx].text()
        b_tag = self._tags[target].text()

        # Block change signals during the swap so we emit `changed` once at
        # the end instead of four times mid-flight.
        for w in (self._combos[idx], self._combos[target],
                  self._tags[idx], self._tags[target]):
            w.blockSignals(True)
        try:
            i_for_b = self._combos[idx].findData(b_data)
            t_for_a = self._combos[target].findData(a_data)
            if i_for_b >= 0:
                self._combos[idx].setCurrentIndex(i_for_b)
            if t_for_a >= 0:
                self._combos[target].setCurrentIndex(t_for_a)
            self._tags[idx].setText(b_tag)
            self._tags[target].setText(a_tag)
        finally:
            for w in (self._combos[idx], self._combos[target],
                      self._tags[idx], self._tags[target]):
                w.blockSignals(False)
        self.changed.emit()

    def _refresh_hint_visibility(self):
        empty = not self._variants and self.count_spin.value() > 0
        self._empty_hint.setVisible(empty)

    def selections(self) -> list[tuple[BlockVariant, str]]:
        """Return [(variant, tag), ...] for each populated row."""
        out: list[tuple[BlockVariant, str]] = []
        for combo, tag_edit in zip(self._combos, self._tags):
            data = combo.currentData()
            if isinstance(data, BlockVariant):
                out.append((data, tag_edit.text().strip()))
        return out

    def set_selections(self, entries: list[dict]):
        """Apply saved entries from a project JSON: list of dicts with variant_id/label/tag."""
        self.count_spin.setValue(len(entries))
        for (combo, tag_edit), entry in zip(zip(self._combos, self._tags), entries):
            label = entry.get("label", "")
            idx = combo.findText(label)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            tag_edit.setText(entry.get("tag", ""))


def _delete_layout(item):
    layout = item.layout() if hasattr(item, "layout") else None
    if layout is None:
        w = item.widget() if hasattr(item, "widget") else None
        if w is not None:
            w.deleteLater()
        return
    while layout.count():
        child = layout.takeAt(0)
        w = child.widget() if hasattr(child, "widget") else None
        if w is not None:
            w.deleteLater()
        else:
            _delete_layout(child)


# ── Room editor: room name + 4 category sections ──────────────────────────────


class RoomEditor(QWidget):
    """One room's editor — name field plus the four category panels."""

    changed = Signal()  # any change inside this room
    name_changed = Signal()  # only when the room name changes

    def __init__(self, default_name: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # Room name
        name_panel = Panel(title="Room")
        name_form = QFormLayout()
        name_form.setHorizontalSpacing(12)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. LAB 101")
        self.name_edit.setMinimumHeight(32)
        self.name_edit.setText(default_name)
        self.name_edit.textChanged.connect(self.name_changed.emit)
        self.name_edit.textChanged.connect(self.changed.emit)
        name_form.addRow("Room name", self.name_edit)
        name_panel.layout().addLayout(name_form)
        layout.addWidget(name_panel)

        # 4 category sections
        self.sections: dict[str, CategorySection] = {}
        for cat in CATEGORIES:
            sec = CategorySection(cat, CATEGORY_LABELS[cat])
            sec.changed.connect(self.changed.emit)
            sec.changed.connect(self._on_valve_changed)
            self.sections[cat] = sec
            layout.addWidget(sec)

        # PBC section — knows how to query this room's valves to build its
        # linked-valves table.
        self.pbc_section = PBCSection(self)
        self.pbc_section.changed.connect(self.changed.emit)
        layout.addWidget(self.pbc_section)

        layout.addStretch(1)

    def _on_valve_changed(self):
        """Re-sync the PBC linked-valves tables when a room's valve list
        changes (count or tag edited)."""
        self.pbc_section.refresh_all()

    def room_name(self) -> str:
        return self.name_edit.text().strip()

    def set_variants(self, pl: ProductLine):
        for cat, sec in self.sections.items():
            sec.set_variants(list_variants(pl, cat))

    def collect(self) -> dict:
        room: dict = {"name": self.room_name(), "SAV": [], "GEX": [], "FEV": [], "AUX": []}
        for cat, sec in self.sections.items():
            for variant, tag in sec.selections():
                room[cat].append({
                    "variant_id": variant.variant_id,
                    "label": variant.label,
                    "dwg_path": str(variant.dwg_path),
                    "tag": tag,
                })
        room["pbcs"] = self.pbc_section.collect()
        return room

    def apply(self, room: dict):
        self.name_edit.setText(room.get("name", ""))
        for cat, sec in self.sections.items():
            sec.set_selections(room.get(cat, []))
        # PBCs after valves so the linked-valves tables can populate from the
        # room's current valve list.
        self.pbc_section.apply(room.get("pbcs", []))


# ── Background update checker ─────────────────────────────────────────────────


class _UpdateChecker(QThread):
    found = Signal(object)

    def run(self) -> None:
        info = check_for_update()
        if info:
            self.found.emit(info)


# ── Generation worker ─────────────────────────────────────────────────────────


class _GenerationWorker(QThread):
    """Runs app.py:generate(project) on a background thread so the GUI stays
    responsive during the multi-second BricsCAD COM round-trips. Emits
    finished_ok(out_path) on success or failed(exc) on any exception."""

    finished_ok = Signal(object)  # Path
    failed = Signal(object)       # Exception

    def __init__(self, on_generate, project, parent=None):
        super().__init__(parent)
        self._on_generate = on_generate
        self._project = project

    def run(self) -> None:
        try:
            # COM is apartment-threaded — every thread that touches it must
            # initialise its own apartment. Without this, the BricsCAD
            # Dispatch call inside _on_generate raises CoInitialize-not-called.
            import pythoncom  # type: ignore
            pythoncom.CoInitialize()
            try:
                out_path = self._on_generate(self._project)
                self.finished_ok.emit(out_path)
            finally:
                try:
                    pythoncom.CoUninitialize()
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(exc)


def _humanize_error(exc: Exception) -> str:
    """Render a generation exception into a sentence the user can act on.

    pywintypes.com_error has the actual BricsCAD complaint buried in
    excepinfo[2] (the `description` field of the EXCEPINFO struct). The
    raw string repr is just the HRESULT, which is useless to a user.
    """
    try:
        import pywintypes  # type: ignore
        if isinstance(exc, pywintypes.com_error):
            parts: list[str] = []
            info = getattr(exc, "excepinfo", None)
            if info and len(info) >= 3 and info[2]:
                parts.append(str(info[2]).strip().rstrip("."))
            strerr = getattr(exc, "strerror", None)
            if strerr:
                parts.append(str(strerr).strip().rstrip("."))
            if not parts:
                hr = getattr(exc, "hresult", 0) & 0xFFFFFFFF
                parts.append(f"COM error 0x{hr:08X}")
            return "BricsCAD reported an error:\n\n" + "\n".join(parts)
    except Exception:  # noqa: BLE001
        pass
    return f"{type(exc).__name__}: {exc}"


# ── Main window ───────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    APP_NAME = APP_NAME

    def __init__(self, on_generate, version: str = "0.0.0"):
        super().__init__()
        self._on_generate = on_generate
        self._version = version
        self._update_info: UpdateInfo | None = None
        self._update_banner: UpdateBanner | None = None
        self._suppress_tree_refresh = False

        self.setWindowTitle(f"{self.APP_NAME} — v{version}")
        self.resize(1280, 880)

        icon_path = _resource_path("LLT_Normal.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._build_menu()
        self._build_ui()
        self._restore_settings()
        # Start with one room
        self._sync_rooms_to_count()
        self._refresh_tree()
        self._check_for_updates()
        # First-run guidance — defer to next event loop tick so the main
        # window has finished its initial paint before the modal pops.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._show_welcome_if_first_run)

    # ── Menu bar ──────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("File")
        new_job = QAction("New Project", self)
        new_job.setShortcut("Ctrl+N")
        new_job.triggered.connect(self._on_new_job)
        file_menu.addAction(new_job)

        open_job = QAction("Open Project…", self)
        open_job.setShortcut("Ctrl+O")
        open_job.triggered.connect(self._on_open_job)
        file_menu.addAction(open_job)

        save_job = QAction("Save Project", self)
        save_job.setShortcut("Ctrl+S")
        save_job.triggered.connect(self._save_job)
        file_menu.addAction(save_job)

        file_menu.addSeparator()
        gen_act = QAction("Generate Drawing", self)
        gen_act.setShortcut("Ctrl+G")
        gen_act.triggered.connect(self._generate)
        file_menu.addAction(gen_act)
        self._gen_act = gen_act

        file_menu.addSeparator()
        prefs_act = QAction("Preferences…", self)
        prefs_act.triggered.connect(self._on_preferences)
        file_menu.addAction(prefs_act)

        file_menu.addSeparator()
        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        # (No Edit menu yet — Undo/Redo/Cut/Copy/Paste aren't wired and
        # showing them as permanently-disabled looks broken. Add the menu
        # back when there's something it can actually do.)

        view_menu = mb.addMenu("View")
        refresh_act = QAction("Refresh Block Library", self)
        refresh_act.setShortcut("F5")
        refresh_act.triggered.connect(self._reload_variants)
        view_menu.addAction(refresh_act)

        tools_menu = mb.addMenu("Tools")
        open_blocks = QAction("Open Block Library Folder", self)
        open_blocks.triggered.connect(self._open_blocks_folder)
        tools_menu.addAction(open_blocks)

        open_templates = QAction("Open Templates Folder", self)
        open_templates.triggered.connect(self._open_templates_folder)
        tools_menu.addAction(open_templates)

        tools_menu.addSeparator()
        test_menu = tools_menu.addMenu("Test")
        quick_act = QAction("Quick Test", self)
        quick_act.setStatusTip("Load jobs/Quick_Test_Building.json and generate.")
        quick_act.triggered.connect(self._run_test_quick)
        test_menu.addAction(quick_act)
        full_act = QAction("Full Test", self)
        full_act.setStatusTip("Load jobs/thorough-test.json and generate.")
        full_act.triggered.connect(self._run_test_full)
        test_menu.addAction(full_act)

        help_menu = mb.addMenu("Help")
        welcome_act = QAction("Show Welcome", self)
        welcome_act.triggered.connect(lambda: self._show_welcome(force=True))
        help_menu.addAction(welcome_act)
        check_updates_act = QAction("Check for Updates", self)
        check_updates_act.triggered.connect(self._check_for_updates_now)
        help_menu.addAction(check_updates_act)
        help_menu.addSeparator()
        about_act = QAction("About", self)
        about_act.triggered.connect(self._on_about)
        help_menu.addAction(about_act)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Central widget paints the orange-themed app icon as a faint
        # watermark behind the form (matches Phoenix-Checkout-Tool's
        # _BgWidget pattern). Mouse events pass through to its layout's
        # children — the watermark is non-interactive.
        central = BackgroundWatermarkWidget(
            image_path=_resource_path("LLT_Transparent.png"),
            opacity=0.18,        # visible reinforcement without fighting the form
            width_ratio=0.55,    # fits a centered logo at ~55% of window width
        )
        central.setObjectName("mainContent")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        # Page header
        header = QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(PageTitle("Lab Layout Tool"))
        header.addWidget(
            PageSubtitle(
                "Multi-room project editor. Add rooms, list valves per room, generate drawings."
            )
        )
        root.addLayout(header)

        # Splitter: tree on the left, editor on the right
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── LEFT: project tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Project")
        self.tree.setMinimumWidth(220)
        self.tree.itemActivated.connect(self._on_tree_item_activated)
        self.tree.itemClicked.connect(self._on_tree_item_activated)
        splitter.addWidget(self.tree)

        # ── RIGHT: scrollable editor
        editor_scroll = QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(editor_scroll.Shape.NoFrame)
        editor_inner = QWidget()
        editor_layout = QVBoxLayout(editor_inner)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(16)

        # Project metadata panel
        meta_panel = Panel(title="Project")
        meta_form = QFormLayout()
        meta_form.setHorizontalSpacing(12)
        meta_form.setVerticalSpacing(8)
        meta_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.job_name = QLineEdit()
        self.job_name.setPlaceholderText("Project / Job name (top line)")
        self.job_name.setMinimumHeight(32)
        self.job_name.textChanged.connect(self._refresh_tree)
        meta_form.addRow("Job name (top)", self.job_name)

        self.job_name_bottom = QLineEdit()
        self.job_name_bottom.setPlaceholderText("Job name bottom line (e.g. building / address)")
        self.job_name_bottom.setMinimumHeight(32)
        meta_form.addRow("Job name (bottom)", self.job_name_bottom)

        self.job_number = QLineEdit()
        self.job_number.setPlaceholderText("e.g. 2026-001")
        self.job_number.setMinimumHeight(32)
        self.job_number.textChanged.connect(self._refresh_tree)
        meta_form.addRow("Job number", self.job_number)

        self.title_top = QLineEdit()
        self.title_top.setPlaceholderText("Optional title top line")
        self.title_top.setMinimumHeight(32)
        meta_form.addRow("Title (top)", self.title_top)

        self.title_bottom = QLineEdit()
        self.title_bottom.setPlaceholderText("Optional title bottom line")
        self.title_bottom.setMinimumHeight(32)
        meta_form.addRow("Title (bottom)", self.title_bottom)

        self.office = QLineEdit()
        self.office.setPlaceholderText("Office / company name")
        self.office.setMinimumHeight(32)
        self.office.setText(self._prefs_get_default_office())
        meta_form.addRow("Office", self.office)

        self.revision = QLineEdit()
        self.revision.setPlaceholderText("Revision label (e.g. Record Drawing Set)")
        self.revision.setMinimumHeight(32)
        self.revision.setText(self._prefs_get_default_revision())
        meta_form.addRow("Revision", self.revision)

        self.technician = QLineEdit()
        self.technician.setPlaceholderText("Technician initials or name")
        self.technician.setMinimumHeight(32)
        self.technician.setText(self._prefs_get_default_technician())
        meta_form.addRow("Technician", self.technician)

        # QDateEdit with calendar popup — better than free-text MM/DD/YYYY
        # which let users type "next Tuesday" and have it land in the title
        # block. Wheel-disabled per the form's no-scroll-by-default rule.
        self.date = NoScrollDateEdit()
        self.date.setDisplayFormat("MM/dd/yyyy")
        self.date.setCalendarPopup(True)
        self.date.setDate(QDate.currentDate())
        self.date.setMinimumHeight(32)
        meta_form.addRow("Date", self.date)

        self.product_combo = NoScrollComboBox()
        self.product_combo.setMinimumHeight(32)
        for pl in blocks.product_lines():
            self.product_combo.addItem(pl.display_name, pl)
        # Apply the user's default product line preference (File → Preferences…)
        # by selecting the matching item before connecting the change signal.
        pref_pid = self._prefs_get_default_product_line_id()
        if pref_pid:
            for i in range(self.product_combo.count()):
                pl = self.product_combo.itemData(i)
                if pl and getattr(pl, "id", None) == pref_pid:
                    self.product_combo.setCurrentIndex(i)
                    break
        self.product_combo.currentIndexChanged.connect(self._reload_variants)
        meta_form.addRow("Product line", self.product_combo)

        room_count_row = QHBoxLayout()
        self.room_count = NoScrollSpinBox()
        self.room_count.setRange(1, 20)
        self.room_count.setValue(1)
        self.room_count.setMinimumHeight(32)
        self.room_count.setFixedWidth(80)
        self.room_count.valueChanged.connect(self._sync_rooms_to_count)
        room_count_row.addWidget(self.room_count)
        room_count_row.addStretch(1)
        meta_form.addRow("Number of rooms", room_count_row)

        meta_panel.layout().addLayout(meta_form)
        editor_layout.addWidget(meta_panel)

        # Room tabs
        self.room_tabs = QTabWidget()
        self.room_tabs.setTabsClosable(False)
        # Long room names get clipped with an ellipsis instead of pushing the
        # tab bar past the panel width and forcing horizontal scroll arrows.
        self.room_tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.room_tabs.currentChanged.connect(self._refresh_tree)
        editor_layout.addWidget(self.room_tabs, 1)

        editor_scroll.setWidget(editor_inner)
        splitter.addWidget(editor_scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 1020])

        root.addWidget(splitter, 1)

        # Action buttons
        self.save_btn = SecondaryButton("Save Project")
        self.save_btn.clicked.connect(self._save_job)
        self.gen_btn = PrimaryButton("Generate Drawing")
        self.gen_btn.setDefault(True)
        self.gen_btn.clicked.connect(self._generate)
        cancel_btn = TertiaryButton("New")
        cancel_btn.clicked.connect(self._on_new_job)
        root.addLayout(button_row(cancel_btn, self.save_btn, self.gen_btn))

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    # ── Rooms management ─────────────────────────────────────────────────────

    def _rooms(self) -> list[RoomEditor]:
        return [self.room_tabs.widget(i) for i in range(self.room_tabs.count())]

    def _sync_rooms_to_count(self):
        target = self.room_count.value()
        current = self.room_tabs.count()

        # Removing rooms that contain user data (valves or PBCs) is
        # destructive and not undoable. Confirm first; revert the spinbox
        # silently if the user backs out.
        if target < current:
            doomed_with_data: list[str] = []
            for i in range(target, current):
                room = self.room_tabs.widget(i)
                if isinstance(room, RoomEditor) and self._room_has_data(room):
                    label = self.room_tabs.tabText(i) or f"Room {i + 1}"
                    doomed_with_data.append(label)
            if doomed_with_data:
                n = len(doomed_with_data)
                names = ", ".join(doomed_with_data[:5])
                if n > 5:
                    names += f", and {n - 5} more"
                resp = QMessageBox.question(
                    self,
                    "Discard rooms?",
                    f"Reducing the room count will permanently discard "
                    f"{n} room{'s' if n != 1 else ''} that contain valves "
                    f"or PBCs:\n\n{names}\n\nContinue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if resp != QMessageBox.StandardButton.Yes:
                    # Revert without re-firing valueChanged (would loop the prompt)
                    self.room_count.blockSignals(True)
                    self.room_count.setValue(current)
                    self.room_count.blockSignals(False)
                    return

        # Add rooms if needed
        while self.room_tabs.count() < target:
            idx = self.room_tabs.count()
            default = f"LAB {idx + 1:03d}"
            room = RoomEditor(default_name=default)
            # Hook `changed` (any field) to a sender-based slot that refreshes
            # the tab label badge (valve count) AND the sidebar tree. Hooking
            # the bare `_refresh_tree` would lose the per-room badge update.
            # Use sender-based slots (not lambdas capturing `room`) so a queued
            # signal during deleteLater can't fire on a half-destroyed widget.
            room.changed.connect(self._on_room_changed)
            room.name_changed.connect(self._on_room_name_changed)
            self.room_tabs.addTab(room, default)
            self._apply_current_product_to_room(room)
        # Remove rooms if needed
        while self.room_tabs.count() > target:
            i = self.room_tabs.count() - 1
            w = self.room_tabs.widget(i)
            self.room_tabs.removeTab(i)
            if w is not None:
                w.deleteLater()
        self._refresh_tree()

    def _room_has_data(self, room: RoomEditor) -> bool:
        """True if the room has any user-entered valves or PBCs.

        Used by _sync_rooms_to_count to decide whether to confirm a
        destructive room removal. The room name alone (auto-generated
        default like 'LAB 001') doesn't count.
        """
        try:
            data = room.collect()
        except Exception:  # noqa: BLE001
            return True  # err on the side of confirming
        if data.get("pbcs"):
            return True
        for cat in CATEGORIES:
            if data.get(cat):
                return True
        return False

    def _on_room_changed(self):
        """Slot for RoomEditor.changed (anything inside the room form).
        Refreshes both the tab label (valve count badge) and the sidebar
        tree. Uses sender() so a queued signal during deleteLater can't
        fire on a half-destroyed widget."""
        room = self.sender()
        if isinstance(room, RoomEditor):
            self._update_tab_label(room)

    def _on_room_name_changed(self):
        """Slot for RoomEditor.name_changed. Resolves sender at emit time so
        we don't hold a Python reference to a possibly-destroyed widget."""
        room = self.sender()
        if isinstance(room, RoomEditor):
            self._update_tab_label(room)

    def _update_tab_label(self, room: RoomEditor):
        idx = self.room_tabs.indexOf(room)
        if idx >= 0:
            base = room.room_name() or f"Room {idx + 1}"
            # Append a valve count badge so it's obvious at a glance which
            # rooms are populated. Use room.collect() so the count includes
            # PBCs (which show as "+N" if any). Wrap in try/except — collect()
            # touches a lot of widgets and shouldn't be allowed to break the
            # tab text update.
            badge = ""
            try:
                data = room.collect()
                v = sum(len(data.get(c, []) or []) for c in CATEGORIES)
                p = len(data.get("pbcs", []) or [])
                if v == 0 and p == 0:
                    badge = " (empty)"
                elif p > 0:
                    badge = f" ({v} valves, {p} PBC{'s' if p != 1 else ''})"
                else:
                    badge = f" ({v} valve{'s' if v != 1 else ''})"
            except Exception:  # noqa: BLE001
                pass
            self.room_tabs.setTabText(idx, base + badge)
        self._refresh_tree()

    def _apply_current_product_to_room(self, room: RoomEditor):
        pl = self._current_product()
        if pl is not None:
            room.set_variants(pl)

    def _current_product(self) -> ProductLine | None:
        return self.product_combo.currentData()

    def _reload_variants(self):
        pl = self._current_product()
        if pl is None:
            return
        for room in self._rooms():
            room.set_variants(pl)
        self.statusBar().showMessage(
            f"Block library refreshed for {pl.display_name}", 4000
        )

    # ── Tree sidebar ─────────────────────────────────────────────────────────

    def _refresh_tree(self):
        if self._suppress_tree_refresh:
            return
        self.tree.blockSignals(True)
        self.tree.clear()
        job_name = self.job_name.text().strip() or "(unnamed project)"
        job_num = self.job_number.text().strip()
        root_label = f"{job_name}" + (f"  —  {job_num}" if job_num else "")
        root_item = QTreeWidgetItem([root_label])
        root_item.setData(0, Qt.ItemDataRole.UserRole, ("project", None))
        self.tree.addTopLevelItem(root_item)

        for r_idx, room in enumerate(self._rooms()):
            r_label = room.room_name() or f"Room {r_idx + 1}"
            r_item = QTreeWidgetItem([r_label])
            r_item.setData(0, Qt.ItemDataRole.UserRole, ("room", r_idx))
            root_item.addChild(r_item)
            for cat in CATEGORIES:
                sec = room.sections[cat]
                for i, (variant, tag) in enumerate(sec.selections()):
                    label = tag if tag else f"{cat}-{i + 1} (no tag)"
                    leaf = QTreeWidgetItem([f"{label}  —  {variant.label}"])
                    leaf.setData(0, Qt.ItemDataRole.UserRole, ("valve", r_idx))
                    r_item.addChild(leaf)
            r_item.setExpanded(True)
        root_item.setExpanded(True)
        self.tree.blockSignals(False)

    def _on_tree_item_activated(self, item: QTreeWidgetItem, _column: int = 0):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, ref = data
        if kind in ("room", "valve") and isinstance(ref, int):
            self.room_tabs.setCurrentIndex(ref)

    # ── Project IO ───────────────────────────────────────────────────────────

    def _collect_project(self) -> dict:
        pl = self._current_product()
        proj = {
            "schema_version": 2,
            "job_name": self.job_name.text().strip(),
            "job_name_bottom": self.job_name_bottom.text().strip(),
            "job_number": self.job_number.text().strip(),
            "title_top": self.title_top.text().strip(),
            "title_bottom": self.title_bottom.text().strip(),
            "office": self.office.text().strip(),
            "revision": self.revision.text().strip(),
            "technician": self.technician.text().strip(),
            "date": self.date.text().strip(),
            "product_line": pl.id if pl else None,
            "product_line_display": pl.display_name if pl else None,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "rooms": [room.collect() for room in self._rooms()],
        }
        return proj

    def _save_job(self):
        proj = self._collect_project()
        JOBS_DIR.mkdir(exist_ok=True)
        filename = (proj["job_name"] or "untitled").replace(" ", "_")
        path = JOBS_DIR / f"{filename}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(proj, f, indent=2)
        self.statusBar().showMessage(f"Saved {path.name}", 5000)

    def _on_new_job(self):
        self._suppress_tree_refresh = True
        try:
            self.job_name.clear()
            self.job_name_bottom.clear()
            self.job_number.clear()
            self.title_top.clear()
            self.title_bottom.clear()
            # Pull defaults from per-user preferences (File → Preferences…)
            self.office.setText(self._prefs_get_default_office())
            self.revision.setText(self._prefs_get_default_revision())
            self.technician.setText(self._prefs_get_default_technician())
            self.date.setDate(QDate.currentDate())
            # Default product line if the user has set one
            pid = self._prefs_get_default_product_line_id()
            if pid:
                for i in range(self.product_combo.count()):
                    pl = self.product_combo.itemData(i)
                    if pl and getattr(pl, "id", None) == pid:
                        self.product_combo.setCurrentIndex(i)
                        break
            self.room_count.setValue(1)
            for room in self._rooms():
                room.name_edit.clear()
                for sec in room.sections.values():
                    sec.count_spin.setValue(0)
        finally:
            self._suppress_tree_refresh = False
        self._refresh_tree()
        self.statusBar().showMessage("New project", 3000)

    def _on_open_job(self):
        # Browse jobs/*.json with a Phoenix-styled list (file, job name, room
        # count, modified date) instead of a bare OS file picker. Has a
        # 'Browse for other file...' fallback to the system dialog for
        # projects living elsewhere on disk.
        dlg = JobBrowserDialog(jobs_dir=JOBS_DIR, parent=self)
        if dlg.exec() != JobBrowserDialog.DialogCode.Accepted:
            return
        if dlg.selected_path is None:
            return
        self._load_project_from_path(dlg.selected_path)

    def _resolve_block_paths(self, data: dict) -> None:
        """Fill in missing or stale dwg_path values from variant_id.

        Test fixtures and hand-edited project files may omit dwg_path
        entirely (or have absolute paths from another machine) — both
        cases get rebuilt from the project's product_line + each entry's
        category + variant_id. User-saved projects with valid existing
        paths pass through unchanged.
        """
        pid = data.get("product_line")
        if not pid:
            return
        try:
            pls = blocks.product_lines()
        except Exception:  # noqa: BLE001
            return
        pl = next((p for p in pls if p.id == pid), None)
        if pl is None:
            return
        for room in data.get("rooms", []) or []:
            for cat in CATEGORIES:
                for entry in room.get(cat, []) or []:
                    vid = entry.get("variant_id")
                    if not vid:
                        continue
                    existing = entry.get("dwg_path")
                    needs_fix = (not existing) or (not Path(existing).is_file())
                    if needs_fix:
                        entry["dwg_path"] = str(resolve_block_path(pl, cat, vid))

    def _load_project_from_path(self, path: Path) -> bool:
        if not path.exists():
            QMessageBox.warning(
                self, "Project Missing", f"Could not find {path.name} at {path}"
            )
            return False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Upgrade pre-v2 projects (single-room shape) into the current schema.
        # All version-aware logic lives in cad/migrate.py so the loader stays
        # version-agnostic.
        from cad.migrate import migrate_project
        data = migrate_project(data)

        # Fill in missing or broken dwg_path values from variant_id. Lets
        # project JSONs (especially test fixtures) ship without absolute
        # Windows paths embedded; user-saved projects with valid existing
        # paths pass through unchanged.
        self._resolve_block_paths(data)

        self._suppress_tree_refresh = True
        try:
            self.job_name.setText(data.get("job_name", ""))
            self.job_name_bottom.setText(data.get("job_name_bottom", ""))
            self.job_number.setText(data.get("job_number", ""))
            self.title_top.setText(data.get("title_top", ""))
            self.title_bottom.setText(data.get("title_bottom", ""))
            self.office.setText(data.get("office", "") or self._prefs_get_default_office())
            self.revision.setText(data.get("revision", "") or self._prefs_get_default_revision())
            self.technician.setText(data.get("technician", ""))
            saved_date = data.get("date", "") or ""
            qd = QDate.fromString(saved_date, "MM/dd/yyyy") if saved_date else QDate()
            self.date.setDate(qd if qd.isValid() else QDate.currentDate())
            pid = data.get("product_line")
            for i in range(self.product_combo.count()):
                pl = self.product_combo.itemData(i)
                if pl and pl.id == pid:
                    self.product_combo.setCurrentIndex(i)
                    break
            self._reload_variants()
            rooms = data.get("rooms", [])
            self.room_count.setValue(max(1, len(rooms)))
            for i, room_data in enumerate(rooms):
                if i < self.room_tabs.count():
                    room_widget = self.room_tabs.widget(i)
                    room_widget.apply(room_data)
                    self._update_tab_label(room_widget)
        finally:
            self._suppress_tree_refresh = False
        self._refresh_tree()
        self.statusBar().showMessage(f"Loaded {path.name}", 5000)
        return True

    def _run_test_quick(self):
        if self._load_project_from_path(JOBS_DIR / "Quick_Test_Building.json"):
            self._generate()

    def _run_test_full(self):
        if self._load_project_from_path(JOBS_DIR / "thorough-test.json"):
            self._generate()

    def _validate_project(self, proj: dict) -> tuple[list[str], list[str]]:
        """Pre-flight checks. Returns (errors, warnings).

        Errors are blockers (no DWG can be produced). Warnings are
        suspicious but not fatal — the user is asked to confirm.
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not (proj.get("job_name") or "").strip():
            warnings.append("Job name is empty.")
        if not proj.get("product_line"):
            errors.append("No product line selected.")

        rooms = proj.get("rooms") or []
        if not rooms:
            errors.append("Project has no rooms.")
            return errors, warnings

        any_valves = False
        any_pbcs = False
        for r_idx, room in enumerate(rooms):
            label = (room.get("name") or f"Room {r_idx + 1}").strip()
            valve_count = sum(
                len(room.get(cat, []) or [])
                for cat in CATEGORIES
            )
            pbcs = room.get("pbcs") or []
            if valve_count > 0:
                any_valves = True
            if pbcs:
                any_pbcs = True

            # Untagged valves
            for cat in CATEGORIES:
                for v_idx, entry in enumerate(room.get(cat, []) or []):
                    if not (entry.get("tag") or "").strip():
                        warnings.append(
                            f"{label}: {cat} #{v_idx + 1} ({entry.get('variant_id', '?')}) has no tag."
                        )

            # PBC field completeness
            valve_tags_in_room: set[str] = set()
            for cat in CATEGORIES:
                for entry in room.get(cat, []) or []:
                    t = (entry.get("tag") or "").strip()
                    if t:
                        valve_tags_in_room.add(t)
            for p_idx, pbc in enumerate(pbcs):
                ptag = (pbc.get("tag") or "").strip() or f"PBC #{p_idx + 1}"
                if not (pbc.get("tag") or "").strip():
                    warnings.append(f"{label}: PBC #{p_idx + 1} has no tag.")
                if not (pbc.get("mac") or "").strip():
                    warnings.append(f"{label}: {ptag} has no MAC.")
                # Broken links
                for link in pbc.get("links") or []:
                    lt = (link.get("valve_tag") or "").strip()
                    if lt and lt not in valve_tags_in_room:
                        warnings.append(
                            f"{label}: {ptag} links to {lt!r} but no valve "
                            f"in the room has that tag."
                        )

        if not any_valves and not any_pbcs:
            errors.append("Project has no valves and no PBCs in any room.")
        return errors, warnings

    def _generate(self):
        # Reject re-entry while a worker is already running. The gen button
        # and menu action are also disabled below, but defense in depth.
        if getattr(self, "_gen_worker", None) is not None:
            return

        proj = self._collect_project()

        # Pre-flight validation. Errors block; warnings prompt to continue.
        errors, warnings = self._validate_project(proj)
        if errors:
            QMessageBox.critical(
                self, "Cannot generate",
                "The project can't be generated:\n\n• " + "\n• ".join(errors),
            )
            return
        if warnings:
            preview = warnings[:8]
            tail = (
                f"\n\n…and {len(warnings) - len(preview)} more."
                if len(warnings) > len(preview) else ""
            )
            resp = QMessageBox.warning(
                self, "Continue with these issues?",
                "The project has some unfilled fields:\n\n• "
                + "\n• ".join(preview)
                + tail
                + "\n\nGenerate the drawing anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return

        # Move generation to a worker thread so the GUI stays responsive
        # during the multi-second BricsCAD COM burst. A non-cancellable
        # progress dialog blocks meaningful interaction with the form
        # (preventing mid-flight edits to `proj`) while keeping the window
        # repaintable and movable.
        self.statusBar().showMessage("Generating drawing in BricsCAD…")
        self.gen_btn.setEnabled(False)
        self._gen_act.setEnabled(False)

        self._gen_dialog = QProgressDialog(
            "Generating drawing in BricsCAD…\n"
            "This usually takes 10–30 seconds; large projects can take longer.",
            None,            # no cancel button — COM calls can't be interrupted cleanly
            0, 0,            # busy indicator (indeterminate progress)
            self,
        )
        self._gen_dialog.setWindowTitle("Generating…")
        self._gen_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._gen_dialog.setMinimumDuration(0)
        self._gen_dialog.setAutoClose(False)
        self._gen_dialog.setAutoReset(False)

        self._gen_worker = _GenerationWorker(self._on_generate, proj, parent=self)
        self._gen_worker.finished_ok.connect(self._on_generation_finished_ok)
        self._gen_worker.failed.connect(self._on_generation_failed)
        # Always run cleanup whether success or failure
        self._gen_worker.finished.connect(self._on_generation_done)
        self._gen_worker.start()
        self._gen_dialog.show()

    def _on_generation_finished_ok(self, out_path):
        self.statusBar().showMessage(f"Drawing saved to {out_path}", 8000)
        # Surface the result with an action affordance — the file path is
        # often needed (to email, attach to a ticket, etc.) and the user
        # otherwise has to remember/copy it from the status bar.
        out_path = Path(out_path)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Drawing generated")
        box.setText(f"Saved to:\n{out_path}")
        open_btn = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.setDefaultButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            try:
                os.startfile(str(out_path.parent))  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

    def _on_generation_failed(self, exc):
        self.statusBar().showMessage("Generation failed", 5000)
        msg = _humanize_error(exc)
        log_path = PROJECT_ROOT / "jobs" / "last_generation.log"
        if log_path.is_file():
            msg += f"\n\nGeneration log: {log_path}"
        QMessageBox.critical(self, "Generation failed", msg)

    def _on_generation_done(self):
        """Always-runs cleanup, paired with QThread.finished."""
        if getattr(self, "_gen_dialog", None) is not None:
            try:
                self._gen_dialog.close()
            except Exception:  # noqa: BLE001
                pass
            self._gen_dialog = None
        self.gen_btn.setEnabled(True)
        self._gen_act.setEnabled(True)
        worker = getattr(self, "_gen_worker", None)
        if worker is not None:
            try:
                worker.deleteLater()
            except Exception:  # noqa: BLE001
                pass
        self._gen_worker = None

    # ── Tools menu ────────────────────────────────────────────────────────────

    def _open_blocks_folder(self):
        os.startfile(str(PROJECT_ROOT / "blocks"))  # type: ignore[attr-defined]

    def _open_templates_folder(self):
        os.startfile(str(PROJECT_ROOT / "templates"))  # type: ignore[attr-defined]

    def _on_about(self):
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            (
                f"<b>{APP_NAME}</b><br>"
                f"Version {self._version}<br><br>"
                f"Multi-room project editor for as-built lab valve drawings.<br>"
                f"© ATS Inc."
            ),
        )

    # ── Auto-updater ──────────────────────────────────────────────────────────

    def _check_for_updates(self) -> None:
        self._update_checker = _UpdateChecker()
        self._update_checker.found.connect(self._on_update_found)
        self._update_checker.start()

    def _check_for_updates_now(self) -> None:
        self.statusBar().showMessage("Checking for updates…", 2000)
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            info = check_for_update()
        finally:
            QApplication.restoreOverrideCursor()

        if info:
            self._on_update_found(info)
            QMessageBox.information(
                self,
                "Update Available",
                f"Version {info.latest_version} is available.\n\n"
                f"Use the update banner to install it.",
            )
        else:
            QMessageBox.information(
                self,
                "No Update Available",
                f"You're running v{self._version}. No newer release was found.",
            )
            self.statusBar().showMessage("No update available", 4000)

    def _on_update_found(self, info: UpdateInfo) -> None:
        self._update_info = info
        if self._update_banner and self._update_banner.isVisible():
            return
        banner = UpdateBanner(
            current_version=info.current_version,
            latest_version=info.latest_version,
            release_notes=info.release_notes,
            parent=self,
        )
        banner.install_clicked.connect(lambda: self._do_install(info))
        self._update_banner = banner
        self.statusBar().addPermanentWidget(banner, 1)
        banner.show()
        self.statusBar().showMessage(f"Update available: v{info.latest_version}", 0)

    def _do_install(self, info: UpdateInfo) -> None:
        progress = QProgressDialog("Downloading update…", "Cancel", 0, 100, self)
        progress.setWindowTitle("Installing Update")
        progress.setModal(True)
        progress.setValue(0)
        progress.show()

        def on_progress(done: int, total: int) -> None:
            if total > 0:
                progress.setValue(int(done / total * 100))
            QApplication.processEvents()

        try:
            download_and_apply(info, progress_callback=on_progress)
        except RuntimeError as exc:
            progress.close()
            QMessageBox.critical(
                self,
                "Update Failed",
                f"{exc}\n\n"
                f"You can install manually from:\n"
                f"https://github.com/{updater.GITHUB_OWNER}/{updater.GITHUB_REPO}/releases/latest",
            )

    # ── Preferences ───────────────────────────────────────────────────────────

    def _prefs_get(self, key: str, default: str = "") -> str:
        s = QSettings(ORG_NAME, APP_NAME)
        v = s.value(f"prefs/{key}", default)
        return str(v) if v is not None else default

    def _prefs_get_default_office(self) -> str:
        return self._prefs_get("office", "ATS Automation Inc.")

    def _prefs_get_default_revision(self) -> str:
        return self._prefs_get("revision", "Record Drawing Set")

    def _prefs_get_default_technician(self) -> str:
        return self._prefs_get("technician", "")

    def _prefs_get_default_product_line_id(self) -> "str | None":
        v = self._prefs_get("product_line", "")
        return v or None

    def _on_preferences(self):
        """Open the preferences dialog and persist any changes to QSettings."""
        try:
            pls = blocks.product_lines()
        except Exception:  # noqa: BLE001
            pls = []
        dlg = PreferencesDialog(
            parent=self,
            office=self._prefs_get_default_office(),
            revision=self._prefs_get_default_revision(),
            technician=self._prefs_get_default_technician(),
            product_lines=pls,
            default_product_line_id=self._prefs_get_default_product_line_id(),
        )
        if dlg.exec() != PreferencesDialog.DialogCode.Accepted:
            # Even on Cancel, honor an explicit "reset welcome" click
            if dlg.reset_welcome:
                QSettings(ORG_NAME, APP_NAME).setValue("welcome_dismissed", False)
            return
        s = QSettings(ORG_NAME, APP_NAME)
        s.setValue("prefs/office", dlg.office)
        s.setValue("prefs/revision", dlg.revision)
        s.setValue("prefs/technician", dlg.technician)
        s.setValue("prefs/product_line", dlg.default_product_line_id or "")
        if dlg.reset_welcome:
            s.setValue("welcome_dismissed", False)
        self.statusBar().showMessage("Preferences saved", 4000)

    # ── Welcome dialog ────────────────────────────────────────────────────────

    def _show_welcome_if_first_run(self) -> None:
        """Called from __init__ via a 0-ms QTimer. Pops the welcome dialog
        unless the user has previously checked 'Don't show again'."""
        s = QSettings(ORG_NAME, APP_NAME)
        if s.value("welcome_dismissed", False, type=bool):
            return
        self._show_welcome(force=False)

    def _show_welcome(self, force: bool = False) -> None:
        """Show the welcome dialog. `force=True` from the Help menu always
        shows it even if previously dismissed; `force=False` from the
        first-run check respects the user's prior choice."""
        s = QSettings(ORG_NAME, APP_NAME)
        prev = s.value("welcome_dismissed", False, type=bool)
        dlg = WelcomeDialog(parent=self, dont_show_default=prev)
        dlg.exec()
        # Only persist a "checked" state — explicit-show from the menu
        # shouldn't unset a prior preference if the user leaves it unchecked.
        if dlg.dont_show_again():
            s.setValue("welcome_dismissed", True)
        elif force:
            # User opened from menu, unchecked the box → re-enable on next launch
            s.setValue("welcome_dismissed", False)

    # ── QSettings ─────────────────────────────────────────────────────────────

    def _restore_settings(self):
        s = QSettings(ORG_NAME, APP_NAME)
        geom = s.value("geometry")
        if geom is not None:
            self.restoreGeometry(geom)
        state = s.value("windowState")
        if state is not None:
            self.restoreState(state)

    def closeEvent(self, event):
        s = QSettings(ORG_NAME, APP_NAME)
        s.setValue("geometry", self.saveGeometry())
        s.setValue("windowState", self.saveState())
        if hasattr(self, "_update_checker"):
            self._update_checker.wait(2000)
        super().closeEvent(event)
