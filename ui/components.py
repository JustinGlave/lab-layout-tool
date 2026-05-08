"""Phoenix Controls component helpers — shared across the ATS app suite.

Use these instead of raw Qt widgets so every tool reads as one product.

Buttons:
    PrimaryButton   — red, main/destructive actions (Save, Generate, Submit)
    SecondaryButton — blue, supporting actions (Export, Save Draft, Refresh)
    TertiaryButton  — outline, low-emphasis (Cancel, Help, Dismiss)

Typography:
    PageTitle    — 14pt bold (objectName "ProjectTitle")
    PageSubtitle — 10pt muted (objectName "ProjectSubtitle")
    SectionTitle — 12pt semibold (objectName "SectionTitle")
    HintLabel    — 9pt muted (objectName "hint")

Containers:
    Panel        — dark rounded card; pass an optional title to show a SectionTitle inside
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


# ── Scroll-wheel guards ───────────────────────────────────────────────────────
# Default Qt behavior changes a combo/spin's value when the mouse wheel is
# rolled over it, even if the widget isn't focused. In a long scrollable form
# that's a usability landmine — users scrolling the page accidentally shift
# values. These subclasses ignore wheel events unless the widget has focus.


class NoScrollComboBox(QComboBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # StrongFocus = accept focus on click and tab, NOT on wheel scroll.
        # Without this, the first wheel scroll grants focus and subsequent
        # scrolls change the value even though wheelEvent ignored the first.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoScrollSpinBox(QSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoScrollDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoScrollDateEdit(QDateEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class PrimaryButton(QPushButton):
    """Red primary-action button."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setMinimumHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class SecondaryButton(QPushButton):
    """Blue secondary-action button."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("secondaryButton")
        self.setMinimumHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class TertiaryButton(QPushButton):
    """Outline tertiary button (low-emphasis / cancel / dismiss)."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("tertiaryButton")
        self.setMinimumHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class PageTitle(QLabel):
    """14pt bold page title (objectName 'ProjectTitle')."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("ProjectTitle")


class PageSubtitle(QLabel):
    """10pt muted subtitle (objectName 'ProjectSubtitle')."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("ProjectSubtitle")


class SectionTitle(QLabel):
    """12pt semibold section header (objectName 'SectionTitle')."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("SectionTitle")


class HintLabel(QLabel):
    """9pt muted helper text (objectName 'hint')."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("hint")


class Panel(QWidget):
    """Dark rounded card. Add child widgets via .layout() (a QVBoxLayout)."""

    def __init__(self, title: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(12)
        if title:
            v.addWidget(SectionTitle(title))


class PhoenixTable(QTableWidget):
    """Read-only data table with Phoenix styling defaults."""

    def __init__(self, rows: int = 0, cols: int = 0, parent=None):
        super().__init__(rows, cols, parent)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAlternatingRowColors(True)


def button_row(*buttons, align_right: bool = True) -> QHBoxLayout:
    """Convenience: horizontal layout of buttons with a leading stretch."""
    row = QHBoxLayout()
    if align_right:
        row.addStretch(1)
    for b in buttons:
        row.addWidget(b)
    if not align_right:
        row.addStretch(1)
    return row


class UpdateBanner(QFrame):
    """Slim banner shown when an update is available.

    Designed to live inside the status bar via `addPermanentWidget(banner, 1)`,
    matching the project-tracking-tool pattern. Styling lives in phoenix_style.qss
    under `#UpdateBanner`, `QLabel#UpdateMsg`, and `#InstallBtn`.
    """

    install_clicked = Signal()

    def __init__(
        self,
        current_version: str,
        latest_version: str,
        release_notes: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("UpdateBanner")
        self.setFixedHeight(44)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(8)

        msg = QLabel(
            f"Update available — v{latest_version} is ready. "
            f"You're on v{current_version}."
        )
        msg.setObjectName("UpdateMsg")
        layout.addWidget(msg, 1)

        if release_notes:
            notes_btn = TertiaryButton("Release Notes")
            notes_btn.setFixedWidth(132)
            notes_btn.clicked.connect(
                lambda: QMessageBox.information(
                    self,
                    f"What's new in v{latest_version}",
                    release_notes,
                )
            )
            layout.addWidget(notes_btn)

        install_btn = QPushButton("Install && Restart")
        install_btn.setObjectName("InstallBtn")
        install_btn.setMinimumHeight(32)
        install_btn.setFixedWidth(150)
        install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        install_btn.clicked.connect(self.install_clicked)
        layout.addWidget(install_btn)

        dismiss_btn = TertiaryButton("✕")
        dismiss_btn.setFixedWidth(40)
        dismiss_btn.setToolTip("Dismiss")
        dismiss_btn.clicked.connect(self.hide)
        layout.addWidget(dismiss_btn)


# ── Background watermark ──────────────────────────────────────────────────────


class _WatermarkOverlay(QWidget):
    """Internal overlay widget that paints the watermark. Attached as a
    sibling of the form widgets but kept raised above them so the watermark
    is visible OVER opaque Panel backgrounds, not just in the gaps between
    them. Mouse-event-transparent so clicks fall through to siblings."""

    def __init__(self, pixmap: QPixmap, opacity: float, width_ratio: float, parent):
        super().__init__(parent)
        self._pixmap = pixmap
        self._opacity = float(opacity)
        self._width_ratio = float(width_ratio)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setOpacity(self._opacity)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        target_w = max(1, int(self.width() * self._width_ratio))
        scaled = self._pixmap.scaledToWidth(
            target_w, Qt.TransformationMode.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)


class BackgroundWatermarkWidget(QWidget):
    """Container widget with a watermark overlay painted ON TOP of its layout's
    children (not behind them — Panel widgets have opaque QSS backgrounds, so
    a behind-painted watermark would only peek through the small gaps).

    The overlay is mouse-transparent and kept raised above siblings on every
    resize and show so layout-added children don't bury it.
    """

    def __init__(self, image_path: str = '', opacity: float = 0.18,
                 width_ratio: float = 0.55, parent=None):
        super().__init__(parent)
        pixmap = QPixmap()
        if image_path and os.path.isfile(image_path):
            loaded = QPixmap(image_path)
            if not loaded.isNull():
                pixmap = loaded
        self._overlay = _WatermarkOverlay(pixmap, opacity, width_ratio, self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep the overlay sized to the full parent and on top of siblings
        # added by the layout (Panels, splitter, tabs, etc.).
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()



# ── Welcome dialog (first-run guidance) ───────────────────────────────────────


class WelcomeDialog(QDialog):
    """First-run orientation modal — explains the typical workflow and exposes
    a 'Don't show again' checkbox. The host stores the checkbox state in
    QSettings; this widget is just the UI."""

    def __init__(self, parent: QWidget | None = None,
                 dont_show_default: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Welcome to Lab Layout Tool")
        self.setModal(True)
        self.resize(600, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)

        layout.addWidget(PageTitle("Welcome"))
        layout.addWidget(PageSubtitle(
            "Generate as-built valve drawings from a form. Here's the gist."
        ))

        body = QLabel(
            "<ol style='margin-left:-18px;'>"
            "<li><b>Fill in the project metadata</b> at the top — job name, "
            "job number, technician, date, product line.</li>"
            "<li><b>Set the room count</b> and name each room in its tab "
            "(e.g. <code>LAB 101</code>).</li>"
            "<li><b>Pick valves per category</b> (SAV / GEX / FEV / AUX) "
            "with a count, variant, and tag (free-form, e.g. "
            "<code>PSV-1</code>).</li>"
            "<li><b>Optionally add PBCs</b> per room — click an Edit button "
            "to open the wizard, fill in the PBC fields, and link valves "
            "to COM1 or COM2.</li>"
            "<li><b>Click Generate Drawing</b> (or Ctrl+G). BricsCAD opens "
            "and the DWG lands in <code>jobs/drawings/</code>.</li>"
            "</ol>"
            "<p>Tip: <b>Tools → Test → Quick Test</b> loads a 3-lab CSCP "
            "project and generates immediately — the fastest way to confirm "
            "BricsCAD is wired up correctly.</p>"
        )
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(body, 1)

        layout.addStretch(0)

        bottom = QHBoxLayout()
        self.dont_show_cb = QCheckBox("Don't show this on launch")
        self.dont_show_cb.setChecked(dont_show_default)
        bottom.addWidget(self.dont_show_cb)
        bottom.addStretch(1)
        ok = PrimaryButton("Got it")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        bottom.addWidget(ok)
        layout.addLayout(bottom)

    def dont_show_again(self) -> bool:
        return self.dont_show_cb.isChecked()


# ── Preferences dialog ────────────────────────────────────────────────────────


class PreferencesDialog(QDialog):
    """Simple per-user preferences — default values that pre-fill a new project
    so the user doesn't retype the same office / revision / initials each time.

    The host (MainWindow) reads/writes the values through QSettings and applies
    them to the form on New Project. This widget is just the editor; it doesn't
    own the persistence layer.

    Public properties (after exec() returns Accepted):
        office, revision, technician  — strings, possibly empty
        default_product_line_id       — str | None
        reset_welcome                 — bool, True if user clicked the reset button
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        office: str = "",
        revision: str = "",
        technician: str = "",
        product_lines: "list | None" = None,
        default_product_line_id: str | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setModal(True)
        self.resize(520, 360)
        self.reset_welcome = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        layout.addWidget(PageTitle("Preferences"))
        layout.addWidget(PageSubtitle(
            "Defaults applied when starting a new project. Per-project values "
            "still override these."
        ))

        from PySide6.QtWidgets import QFormLayout
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        from PySide6.QtWidgets import QLineEdit
        self._office_edit = QLineEdit(office)
        self._office_edit.setMinimumHeight(32)
        self._office_edit.setPlaceholderText("e.g. ATS Automation Inc.")
        form.addRow("Default office", self._office_edit)

        self._revision_edit = QLineEdit(revision)
        self._revision_edit.setMinimumHeight(32)
        self._revision_edit.setPlaceholderText("e.g. Record Drawing Set")
        form.addRow("Default revision", self._revision_edit)

        self._technician_edit = QLineEdit(technician)
        self._technician_edit.setMinimumHeight(32)
        self._technician_edit.setPlaceholderText("e.g. JMG")
        form.addRow("Default technician", self._technician_edit)

        self._product_combo = NoScrollComboBox()
        self._product_combo.setMinimumHeight(32)
        self._product_combo.addItem("(no preference — use first available)", None)
        if product_lines:
            for pl in product_lines:
                self._product_combo.addItem(pl.display_name, pl.id)
        if default_product_line_id:
            idx = self._product_combo.findData(default_product_line_id)
            if idx >= 0:
                self._product_combo.setCurrentIndex(idx)
        form.addRow("Default product line", self._product_combo)

        layout.addLayout(form)
        layout.addStretch(1)

        # First-run welcome reset
        welcome_row = QHBoxLayout()
        welcome_row.addWidget(HintLabel(
            "Want the welcome dialog back on next launch?"
        ), 1)
        reset_btn = TertiaryButton("Reset welcome dialog")
        reset_btn.clicked.connect(self._on_reset_welcome)
        welcome_row.addWidget(reset_btn)
        layout.addLayout(welcome_row)

        # Bottom buttons
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        cancel_btn = TertiaryButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)
        save_btn = PrimaryButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        bottom.addWidget(save_btn)
        layout.addLayout(bottom)

    def _on_reset_welcome(self):
        self.reset_welcome = True
        QMessageBox.information(
            self, "Welcome reset",
            "The welcome dialog will show again on the next launch.",
        )

    @property
    def office(self) -> str:
        return self._office_edit.text().strip()

    @property
    def revision(self) -> str:
        return self._revision_edit.text().strip()

    @property
    def technician(self) -> str:
        return self._technician_edit.text().strip()

    @property
    def default_product_line_id(self) -> "str | None":
        return self._product_combo.currentData()


# ── Job browser dialog ────────────────────────────────────────────────────────


class JobBrowserDialog(QDialog):
    """Project picker — lists every *.json in the jobs/ directory with quick
    metadata (job name, rooms, product line, modified date) and lets the user
    pick one. Falls back to a system file dialog for projects elsewhere on disk.

    Usage:
        dlg = JobBrowserDialog(jobs_dir=JOBS_DIR, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            path = dlg.selected_path  # pathlib.Path or None
    """

    def __init__(self, jobs_dir, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Open Project")
        self.setModal(True)
        self.resize(720, 480)

        from pathlib import Path
        self._jobs_dir = Path(jobs_dir)
        self.selected_path = None  # set on accept

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        layout.addWidget(SectionTitle(f"Projects in {self._jobs_dir.name}/"))
        layout.addWidget(HintLabel(
            "Double-click a row to open, or use the buttons below. "
            "Select 'Browse for other file…' to load a project from outside this folder."
        ))

        self._table = PhoenixTable(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["File", "Job name", "Rooms", "Modified"]
        )
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Column sizing — file/name flex, rooms/modified fixed-ish
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(2, 70)
        self._table.setColumnWidth(3, 160)
        self._table.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table, 1)

        bottom = QHBoxLayout()
        browse_btn = TertiaryButton("Browse for other file…")
        browse_btn.clicked.connect(self._on_browse)
        bottom.addWidget(browse_btn)
        bottom.addStretch(1)
        cancel_btn = TertiaryButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)
        open_btn = PrimaryButton("Open")
        open_btn.setDefault(True)
        open_btn.clicked.connect(self._on_open)
        bottom.addWidget(open_btn)
        layout.addLayout(bottom)

        self._populate()

    def _populate(self):
        import json
        from datetime import datetime
        rows = []
        for p in sorted(self._jobs_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                rows.append((p, p.name, "(unreadable)", "?", p.stat().st_mtime))
                continue
            name = (data.get("job_name") or data.get("name") or "").strip() or "(untitled)"
            rooms = data.get("rooms")
            n_rooms = str(len(rooms)) if isinstance(rooms, list) else "v1"
            rows.append((p, p.name, name, n_rooms, p.stat().st_mtime))
        # Newest first
        rows.sort(key=lambda r: r[4], reverse=True)

        self._table.setRowCount(len(rows))
        for r_idx, (p, fname, name, n_rooms, mtime) in enumerate(rows):
            file_item = QTableWidgetItem(fname)
            file_item.setData(Qt.ItemDataRole.UserRole, str(p))
            self._table.setItem(r_idx, 0, file_item)
            self._table.setItem(r_idx, 1, QTableWidgetItem(name))
            self._table.setItem(r_idx, 2, QTableWidgetItem(n_rooms))
            self._table.setItem(
                r_idx, 3,
                QTableWidgetItem(datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")),
            )
        if rows:
            self._table.selectRow(0)

    def _on_double_click(self, _item):
        self._on_open()

    def _on_open(self):
        from pathlib import Path
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 0)
        if item is None:
            return
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        self.selected_path = Path(path_str)
        self.accept()

    def _on_browse(self):
        from pathlib import Path
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", str(self._jobs_dir), "Project files (*.json)"
        )
        if path:
            self.selected_path = Path(path)
            self.accept()
