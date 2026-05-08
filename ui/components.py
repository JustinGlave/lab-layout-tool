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
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QTableWidget,
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


class BackgroundWatermarkWidget(QWidget):
    """Container widget that paints a centered, low-opacity logo behind its
    children. Use as the parent for a layout to show a subtle watermark behind
    the form (matches Phoenix-Checkout-Tool's _BgWidget pattern).

    Mouse events pass through the widget itself; only its layout's children
    interact with input. Pixmap loaded once at construction; if the file is
    missing, the widget renders as a plain background with no watermark.
    """

    def __init__(self, image_path: str = '', opacity: float = 0.12,
                 width_ratio: float = 0.45, parent=None):
        super().__init__(parent)
        self._opacity = float(opacity)
        self._width_ratio = float(width_ratio)
        self._pixmap = QPixmap()
        if image_path and os.path.isfile(image_path):
            loaded = QPixmap(image_path)
            if not loaded.isNull():
                self._pixmap = loaded

    def paintEvent(self, event):
        # Clear background per QSS first by calling super (so the parent's
        # styled fill applies), then overlay the watermark.
        super().paintEvent(event)
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

