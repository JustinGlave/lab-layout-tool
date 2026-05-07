"""PBC editor widgets — added to each room tab.

Each room has a PBCSection that contains 0..N PBCEditor cards. Each PBCEditor
holds a single PBC's metadata fields (tag, device name, device #, MAC,
network #) plus a "Linked valves" table that lists the valves in the room and
lets the user check which to link and which COM trunk (1 or 2) to put them on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .components import (
    HintLabel,
    NoScrollComboBox,
    NoScrollSpinBox,
    Panel,
    PrimaryButton,
    SecondaryButton,
    SectionTitle,
    TertiaryButton,
)

if TYPE_CHECKING:
    from .main_window import RoomEditor


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


# ── Single PBC editor ─────────────────────────────────────────────────────────


class PBCEditor(QWidget):
    """One PBC: 5 text fields + a linked-valves table."""

    changed = Signal()

    def __init__(self, room: "RoomEditor", default_index: int = 0, parent=None):
        super().__init__(parent)
        self._room = room

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ── Form: PBC fields ─────────────────────────────────────────────────
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)

        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText(f"e.g. PBC-{default_index + 1}")
        self.tag_edit.setMinimumHeight(28)
        form.addRow("PBC tag", self.tag_edit)

        self.device_name = QLineEdit()
        self.device_name.setPlaceholderText("e.g. Lab PBC")
        self.device_name.setMinimumHeight(28)
        form.addRow("Device name", self.device_name)

        self.device_number = QLineEdit()
        self.device_number.setPlaceholderText("e.g. 001")
        self.device_number.setMinimumHeight(28)
        form.addRow("Device number", self.device_number)

        self.mac = QLineEdit()
        self.mac.setPlaceholderText("e.g. 00:11:22:33:44:55")
        self.mac.setMinimumHeight(28)
        form.addRow("MAC", self.mac)

        self.network_number = QLineEdit()
        self.network_number.setPlaceholderText(f"e.g. {default_index + 1}")
        self.network_number.setMinimumHeight(28)
        form.addRow("Network #", self.network_number)

        layout.addLayout(form)

        # ── Linked-valves table ──────────────────────────────────────────────
        layout.addWidget(SectionTitle("Linked valves"))
        layout.addWidget(HintLabel(
            "Check the valves this PBC controls and pick which COM trunk each lives on."
        ))

        self.valves_table = QTableWidget(0, 4)
        self.valves_table.setHorizontalHeaderLabels(["Tag", "Variant", "Link", "COM"])
        self.valves_table.verticalHeader().setVisible(False)
        self.valves_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.valves_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.valves_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.valves_table.setMinimumHeight(160)
        header = self.valves_table.horizontalHeader()
        # Fixed widths on Tag / Link / COM so the dropdown widgets in those
        # columns can't leak into adjacent cells when focused (Qt rendering
        # quirk with ResizeToContents + cellWidget combos).
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.valves_table.setColumnWidth(0, 110)   # Tag
        self.valves_table.setColumnWidth(2, 60)    # Link checkbox
        self.valves_table.setColumnWidth(3, 110)   # COM dropdown
        layout.addWidget(self.valves_table)

        # Wire all change signals up
        for w in (self.tag_edit, self.device_name, self.device_number,
                  self.mac, self.network_number):
            w.textChanged.connect(self.changed.emit)

        # Initial population
        self.refresh_valve_list()

    # ── Valve list synchronization ────────────────────────────────────────────

    def refresh_valve_list(self):
        """Re-populate the valves table from the room's current valves.

        Shows EVERY valve in the room (not just tagged ones) so the table
        reflects the room's contents as soon as you set a count. Untagged
        valves render with a placeholder and have their Link checkbox /
        COM dropdown disabled — you have to set a tag before linking.
        Existing checkbox + COM-trunk selections are preserved by tag where
        the tag still exists after the refresh.
        """
        existing = self._collect_links()

        # Hard reset before repopulating — otherwise stale cellWidget combos
        # from a prior population can stay visible at row 0 (Qt rendering
        # quirk with QTableWidget cellWidget + variable column widths).
        self.valves_table.clearContents()
        self.valves_table.setRowCount(0)

        valves: list[tuple[str, str, str]] = []  # (tag, variant_label, category)
        for cat in ("SAV", "GEX", "FEV", "AUX"):
            for variant, tag in self._room.sections[cat].selections():
                valves.append((tag.strip(), variant.label, cat))

        self.valves_table.setRowCount(len(valves))
        muted_brush = QBrush(QColor("#9ca3af"))
        for i, (tag, variant_label, _cat) in enumerate(valves):
            has_tag = bool(tag)
            display_tag = tag if has_tag else "(set tag)"

            tag_item = QTableWidgetItem(display_tag)
            tag_item.setFlags(tag_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if not has_tag:
                tag_item.setForeground(muted_brush)
            self.valves_table.setItem(i, 0, tag_item)

            v_item = QTableWidgetItem(variant_label)
            v_item.setFlags(v_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if not has_tag:
                v_item.setForeground(muted_brush)
            self.valves_table.setItem(i, 1, v_item)

            cb_container, cb = _centered_checkbox(
                checked=has_tag and tag in existing
            )
            cb.setEnabled(has_tag)
            if not has_tag:
                cb.setToolTip("Set a tag on this valve before you can link it.")
            cb.toggled.connect(self.changed.emit)
            self.valves_table.setCellWidget(i, 2, cb_container)

            combo = NoScrollComboBox()
            combo.addItems(["COM1", "COM2"])
            combo.setEnabled(has_tag)
            combo.setMinimumWidth(96)   # ensure the dropdown text + arrow fit
            if has_tag and tag in existing:
                combo.setCurrentIndex(0 if existing[tag] == 1 else 1)
            combo.currentIndexChanged.connect(self.changed.emit)
            self.valves_table.setCellWidget(i, 3, combo)

    # ── Link snapshot / collect / apply ───────────────────────────────────────

    def _collect_links(self) -> dict[str, int]:
        """Return {valve_tag: com_trunk(1|2)} for every checked row."""
        out: dict[str, int] = {}
        for row in range(self.valves_table.rowCount()):
            tag_item = self.valves_table.item(row, 0)
            if tag_item is None:
                continue
            tag = tag_item.text().strip()
            cb_container = self.valves_table.cellWidget(row, 2)
            combo = self.valves_table.cellWidget(row, 3)
            if cb_container is None or combo is None:
                continue
            cb = cb_container.findChild(QCheckBox)
            if cb is None or not cb.isChecked():
                continue
            out[tag] = 1 if combo.currentIndex() == 0 else 2
        return out

    def collect(self) -> dict:
        return {
            "tag": self.tag_edit.text().strip(),
            "device_name": self.device_name.text().strip(),
            "device_number": self.device_number.text().strip(),
            "mac": self.mac.text().strip(),
            "network_number": self.network_number.text().strip(),
            "links": [
                {"valve_tag": tag, "com_trunk": trunk}
                for tag, trunk in self._collect_links().items()
            ],
        }

    def apply(self, data: dict):
        self.tag_edit.setText(data.get("tag", ""))
        self.device_name.setText(data.get("device_name", ""))
        self.device_number.setText(data.get("device_number", ""))
        self.mac.setText(data.get("mac", ""))
        self.network_number.setText(data.get("network_number", ""))
        # Refresh first, then apply checked state from the saved links
        self.refresh_valve_list()
        # Accept int 1/2, str "1"/"2", or "COM1"/"COM2" (case-insensitive)
        # so loading a project saved by a future schema doesn't crash.
        def _trunk(raw) -> int:
            s = str(raw if raw is not None else "").strip().upper()
            return 2 if s in ("2", "COM2") else 1
        saved = {
            l.get("valve_tag", ""): _trunk(l.get("com_trunk", 1))
            for l in data.get("links", [])
        }
        for row in range(self.valves_table.rowCount()):
            tag_item = self.valves_table.item(row, 0)
            if tag_item is None:
                continue
            tag = tag_item.text().strip()
            if tag not in saved:
                continue
            cb_container = self.valves_table.cellWidget(row, 2)
            combo = self.valves_table.cellWidget(row, 3)
            if cb_container is None or combo is None:
                continue
            cb = cb_container.findChild(QCheckBox)
            if cb is not None:
                cb.setChecked(True)
            combo.setCurrentIndex(0 if saved[tag] == 1 else 1)


def _centered_checkbox(checked: bool = False) -> tuple[QWidget, QCheckBox]:
    """Container + checkbox horizontally centered for use as a table cell widget."""
    container = QWidget()
    lay = QHBoxLayout(container)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    cb = QCheckBox()
    cb.setChecked(checked)
    lay.addWidget(cb)
    return container, cb


# ── PBC wizard dialog ─────────────────────────────────────────────────────────


class PBCWizardDialog(QDialog):
    """Modal dialog wrapping a PBCEditor with Save/Cancel buttons."""

    def __init__(self, data: dict, room: "RoomEditor", idx: int, parent=None):
        super().__init__(parent)
        title_part = data.get("tag") or f"PBC #{idx + 1}"
        self.setWindowTitle(f"Edit {title_part}")
        self.setModal(True)
        self.resize(900, 720)

        self.editor = PBCEditor(room, default_index=idx)
        self.editor.apply(data)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self.editor)

        btns = QDialogButtonBox()
        save_btn = PrimaryButton("Save")
        save_btn.setDefault(True)
        cancel_btn = TertiaryButton("Cancel")
        btns.addButton(save_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        btns.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(btns)

    def collect(self) -> dict:
        return self.editor.collect()


# ── PBC section (count + list of buttons) ─────────────────────────────────────


def _empty_pbc() -> dict:
    return {
        "tag": "",
        "device_name": "",
        "device_number": "",
        "mac": "",
        "network_number": "",
        "links": [],
    }


class PBCSection(Panel):
    """Per-room panel showing a count spinner + one Edit button per PBC.
    Clicking a button opens a PBCWizardDialog with the full editor inside."""

    changed = Signal()

    def __init__(self, room: "RoomEditor", parent=None):
        super().__init__(title="PBCs", parent=parent)
        self._room = room
        self._pbcs: list[dict] = []
        # Tracked while a PBCWizardDialog is open so refresh_all() can forward
        # valve-list changes into the live wizard. Today the dialog is modal
        # so this is mostly future-proofing, but it also lets refresh_all()
        # reliably rebuild button labels even mid-edit.
        self._active_dialog: "PBCWizardDialog | None" = None

        body: QVBoxLayout = self.layout()

        count_row = QHBoxLayout()
        count_row.setSpacing(8)
        count_label = QLabel("Count:")
        count_label.setObjectName("ProjectSubtitle")
        count_row.addWidget(count_label)
        self.count_spin = NoScrollSpinBox()
        self.count_spin.setRange(0, 8)
        self.count_spin.setValue(0)
        self.count_spin.setMinimumHeight(32)
        self.count_spin.setFixedWidth(80)
        self.count_spin.valueChanged.connect(self._on_count_changed)
        count_row.addWidget(self.count_spin)
        count_row.addStretch(1)
        body.addLayout(count_row)

        self.buttons_widget = QWidget()
        self.buttons_layout = QVBoxLayout(self.buttons_widget)
        self.buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.buttons_layout.setSpacing(8)
        body.addWidget(self.buttons_widget)

        self._empty_hint = HintLabel(
            "Set the count above to add PBCs. Click an Edit button to open "
            "the PBC wizard and link valves from this room."
        )
        body.addWidget(self._empty_hint)

    # ── Count + buttons ─────────────────────────────────────────────────────

    def _on_count_changed(self, n: int):
        while len(self._pbcs) < n:
            self._pbcs.append(_empty_pbc())
        while len(self._pbcs) > n:
            self._pbcs.pop()
        self._rebuild_buttons()
        self._empty_hint.setVisible(n == 0)
        self.changed.emit()

    def _rebuild_buttons(self):
        # Clear existing buttons
        while self.buttons_layout.count():
            item = self.buttons_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()
        # Add a button per PBC, labelled with tag (or fallback "#N")
        for i, data in enumerate(self._pbcs):
            tag = data.get("tag") or ""
            n_links = len(data.get("links", []))
            label = (
                f"  Edit  PBC #{i + 1}"
                + (f" — {tag}" if tag else "")
                + f"     ({n_links} valve link{'s' if n_links != 1 else ''})"
            )
            btn = SecondaryButton(label)
            btn.setMinimumHeight(40)
            btn.clicked.connect(lambda _checked=False, idx=i: self._open_wizard(idx))
            self.buttons_layout.addWidget(btn)

    def _open_wizard(self, idx: int):
        if idx < 0 or idx >= len(self._pbcs):
            return
        dialog = PBCWizardDialog(
            self._pbcs[idx], self._room, idx, parent=self.window()
        )
        self._active_dialog = dialog
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._pbcs[idx] = dialog.collect()
                self._rebuild_buttons()
                self.changed.emit()
        finally:
            self._active_dialog = None

    # ── Sync hooks ──────────────────────────────────────────────────────────

    def refresh_all(self):
        """Re-render PBC state in response to a room valve change.

        Wired into the chain documented in CLAUDE.md:
            CategorySection.changed -> RoomEditor._on_valve_changed
            -> PBCSection.refresh_all -> PBCEditor.refresh_valve_list

        With modal dialogs the active-dialog forwarding is mostly defensive
        — the user can't edit the room behind a modal — but it makes the
        chain meaningful if dialogs ever become non-modal, and rebuilding
        the button row catches any state-derived label drift.
        """
        if self._active_dialog is not None:
            try:
                self._active_dialog.editor.refresh_valve_list()
            except Exception:  # noqa: BLE001
                pass
        self._rebuild_buttons()

    # ── IO ─────────────────────────────────────────────────────────────────

    def collect(self) -> list[dict]:
        return [dict(p) for p in self._pbcs]  # shallow copy

    def apply(self, pbcs: list[dict]):
        self._pbcs = [dict(p) for p in pbcs]
        self.count_spin.setValue(len(self._pbcs))
        self._rebuild_buttons()
        self._empty_hint.setVisible(len(self._pbcs) == 0)
