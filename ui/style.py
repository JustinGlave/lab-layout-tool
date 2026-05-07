"""Phoenix design system loader.

Loads phoenix_style.qss from the runtime resource path (works in dev and under
PyInstaller --onedir frozen). Falls back to an embedded QSS string so that
auto-updates that only replace the .exe (not _internal/) still get correct
styling.

Mirrors the canonical pattern from Phoenix-Checkout-Tool/checkout_tool_gui.py.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def _resource_path(filename: str) -> str:
    """Resolve a resource path that works in dev and under PyInstaller."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", ""))
    else:
        base = Path(__file__).resolve().parent.parent
    return str(base / filename)


def apply_dark_theme(app: QApplication) -> None:
    """Apply the Phoenix dark-navy theme: Fusion + dark palette + QSS."""
    app.setStyle("Fusion")

    palette = QPalette()
    for role, color in [
        (QPalette.ColorRole.Window,          QColor(10, 14, 39)),
        (QPalette.ColorRole.WindowText,      QColor(255, 255, 255)),
        (QPalette.ColorRole.Base,            QColor(20, 24, 41)),
        (QPalette.ColorRole.AlternateBase,   QColor(15, 18, 25)),
        (QPalette.ColorRole.ToolTipBase,     QColor(20, 24, 41)),
        (QPalette.ColorRole.ToolTipText,     QColor(255, 255, 255)),
        (QPalette.ColorRole.Text,            QColor(255, 255, 255)),
        (QPalette.ColorRole.Button,          QColor(20, 24, 41)),
        (QPalette.ColorRole.ButtonText,      QColor(255, 255, 255)),
        (QPalette.ColorRole.BrightText,      QColor(220, 38, 38)),
        (QPalette.ColorRole.Highlight,       QColor(59, 130, 246)),
        (QPalette.ColorRole.HighlightedText, QColor(255, 255, 255)),
        (QPalette.ColorRole.Link,            QColor(59, 130, 246)),
    ]:
        palette.setColor(role, color)
    app.setPalette(palette)

    qss_path = _resource_path("phoenix_style.qss")
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as fh:
            app.setStyleSheet(fh.read())
    else:
        app.setStyleSheet(_EMBEDDED_QSS)


# Embedded fallback — keeps full styling when an auto-update only replaces the
# .exe (not _internal/). Mirrors phoenix_style.qss.
_EMBEDDED_QSS = """
QMainWindow{background-color:#0a0e27;color:#ffffff;}
QWidget{color:#ffffff;font-family:"Segoe UI",Arial,sans-serif;font-size:11pt;}
QMenuBar{background-color:#0a0e27;color:#ffffff;border-bottom:1px solid #2d3748;padding:4px 0px;spacing:16px;}
QMenuBar::item:selected{background-color:#1f2937;color:#3b82f6;}
QMenuBar::item:pressed{background-color:#1e3a8a;}
QMenu{background-color:#141829;color:#ffffff;border:1px solid #2d3748;border-radius:4px;padding:4px 0px;}
QMenu::item{padding:8px 16px;}
QMenu::item:selected{background-color:#1f2937;color:#3b82f6;}
QMenu::item:pressed{background-color:#1e3a8a;}
QMenu::separator{background-color:#2d3748;height:1px;margin:4px 0px;}
QPushButton,QToolButton{background-color:#dc2626;color:#ffffff;border:none;border-radius:6px;padding:6px 14px;font-weight:600;font-size:11pt;font-family:"Segoe UI",sans-serif;}
QPushButton:hover,QToolButton:hover{background-color:#b91c1c;}
QPushButton:pressed,QToolButton:pressed{background-color:#991b1b;}
QPushButton:focus{outline:none;border:2px solid #3b82f6;}
QPushButton:disabled,QToolButton:disabled{background-color:#4b5563;color:#6b7280;}
QPushButton#secondaryButton{background-color:#1e3a8a;}
QPushButton#secondaryButton:hover{background-color:#1e40af;}
QPushButton#tertiaryButton{background-color:transparent;border:1px solid #4b5563;color:#3b82f6;}
QPushButton#tertiaryButton:hover{background-color:#1f2937;border:1px solid #3b82f6;}
QLineEdit{background-color:#141829;color:#ffffff;border:1px solid #2d3748;border-radius:6px;padding:6px 8px;selection-background-color:#3b82f6;}
QLineEdit:focus{border:2px solid #3b82f6;}
QLineEdit:disabled{background-color:#050810;color:#6b7280;}
QTextEdit,QPlainTextEdit{background-color:#141829;color:#ffffff;border:1px solid #2d3748;border-radius:6px;padding:6px 8px;selection-background-color:#3b82f6;}
QTextEdit:focus,QPlainTextEdit:focus{border:2px solid #3b82f6;}
QTextEdit:disabled,QPlainTextEdit:disabled{background-color:#050810;color:#6b7280;}
QComboBox{background-color:#141829;color:#ffffff;border:1px solid #2d3748;border-radius:6px;padding:6px 8px;}
QComboBox:focus{border:2px solid #3b82f6;}
QComboBox:disabled{background-color:#050810;color:#6b7280;}
QComboBox::drop-down{border:none;padding-right:8px;}
QComboBox::down-arrow{image:none;}
QComboBox QAbstractItemView{background-color:#141829;color:#ffffff;selection-background-color:#3b82f6;border:1px solid #2d3748;outline:none;}
QDateEdit{background-color:#141829;color:#ffffff;border:1px solid #2d3748;border-radius:6px;padding:6px 8px;}
QDateEdit:focus{border:2px solid #3b82f6;}
QSpinBox,QDoubleSpinBox{background-color:#141829;color:#ffffff;border:1px solid #2d3748;border-radius:6px;padding:6px 8px;}
QSpinBox:focus,QDoubleSpinBox:focus{border:2px solid #3b82f6;}
QSpinBox::up-button,QDoubleSpinBox::up-button,QSpinBox::down-button,QDoubleSpinBox::down-button{background-color:#050810;border:none;width:20px;}
QSpinBox::up-button:hover,QDoubleSpinBox::up-button:hover,QSpinBox::down-button:hover,QDoubleSpinBox::down-button:hover{background-color:#1f2937;}
QCheckBox{color:#ffffff;spacing:8px;}
QCheckBox::indicator{width:18px;height:18px;border-radius:4px;border:1px solid #4b5563;background-color:#141829;}
QCheckBox::indicator:hover{border:1px solid #3b82f6;background-color:#1f2937;}
QCheckBox::indicator:checked{background-color:#10b981;border:1px solid #10b981;}
QCheckBox::indicator:focus{border:2px solid #3b82f6;}
QRadioButton{color:#ffffff;spacing:8px;}
QRadioButton::indicator{width:18px;height:18px;border-radius:9px;border:1px solid #4b5563;background-color:#141829;}
QRadioButton::indicator:hover{border:1px solid #3b82f6;}
QRadioButton::indicator:checked{background-color:#1e3a8a;border:1px solid #1e3a8a;}
QLabel{color:#ffffff;font-family:"Segoe UI",sans-serif;}
QLabel#title{font-size:20pt;font-weight:bold;}
QLabel#sectionTitle{font-size:13pt;font-weight:600;}
QLabel#subtitle{font-size:11pt;color:#d1d5db;}
QLabel#hint{font-size:9pt;color:#9ca3af;}
QTabWidget::pane{border:1px solid #2d3748;background-color:#141829;}
QTabBar::tab{background-color:#050810;color:#9ca3af;padding:6px 18px;border:1px solid #2d3748;border-bottom:none;border-radius:6px 6px 0 0;font-weight:500;}
QTabBar::tab:selected{background-color:#141829;color:#ffffff;font-weight:600;border-bottom:3px solid #dc2626;}
QTabBar::tab:hover:!selected{background-color:#1f2937;color:#d1d5db;}
QTableWidget,QTableView{background-color:transparent;alternate-background-color:rgba(10,14,39,140);gridline-color:#2d3748;border:1px solid #2d3748;border-radius:6px;color:#ffffff;}
QTableWidget::item,QTableView::item{background-color:rgba(20,24,41,140);padding:3px 6px;border:none;color:#ffffff;}
QTableWidget::item:alternate,QTableView::item:alternate{background-color:rgba(10,14,39,140);}
QTableWidget::item:selected,QTableView::item:selected{background-color:#1e40af;color:#ffffff;}
QTableWidget::item:hover,QTableView::item:hover{background-color:#1f2937;}
QHeaderView::section{background-color:rgba(5,8,16,180);color:#e5e7eb;padding:6px 8px;border:none;border-right:1px solid #2d3748;border-bottom:1px solid #2d3748;font-weight:600;}
QHeaderView::section:hover{background-color:#1f2937;}
QTreeWidget{background:transparent;border:1px solid #2d3748;border-radius:10px;padding:4px;color:#ececec;outline:none;}
QTreeWidget::item{border-radius:6px;padding:5px 8px;margin:1px 0;}
QTreeWidget::item:selected{background:#1e3a8a;color:white;}
QTreeWidget::item:hover:!selected{background:#1f2937;}
QTreeView::branch{background:transparent;}
QTreeView::branch:selected{background:#1e3a8a;}
QTreeView::branch:hover:!selected{background:#1f2937;}
QScrollBar:vertical{background-color:#0a0e27;width:8px;border:none;}
QScrollBar::handle:vertical{background-color:#4b5563;border-radius:4px;min-height:20px;}
QScrollBar::handle:vertical:hover{background-color:#6b7280;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;border:none;background:none;}
QScrollBar:horizontal{background-color:#0a0e27;height:8px;border:none;}
QScrollBar::handle:horizontal{background-color:#4b5563;border-radius:4px;min-width:20px;}
QScrollBar::handle:horizontal:hover{background-color:#6b7280;}
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;border:none;background:none;}
QProgressBar{border:1px solid #2d3748;border-radius:6px;background-color:#050810;text-align:center;color:#ffffff;}
QProgressBar::chunk{background-color:#dc2626;border-radius:4px;}
QGroupBox{color:#ffffff;border:1px solid #2d3748;border-radius:8px;margin-top:12px;padding-top:12px;font-weight:600;}
QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;padding:0px 4px;}
QDialog{background-color:#0a0e27;}
QMessageBox QLabel{color:#ffffff;}
QMessageBox QPushButton{min-width:80px;}
QSplitter::handle{background-color:#2d3748;}
QSplitter::handle:hover{background-color:#3b82f6;}
QFrame[frameShape="4"],QFrame[frameShape="5"]{border:1px solid #2d3748;background-color:transparent;}
QToolTip{background-color:#141829;color:#ffffff;border:1px solid #2d3748;padding:6px 10px;border-radius:4px;}
QStatusBar{background-color:#050810;color:#d1d5db;border-top:1px solid #2d3748;padding:2px 12px;}
QFormLayout QLabel{color:#9ca3af;}
#Panel,#StatCard{background:rgba(20,24,41,180);border:1px solid #2d3748;border-radius:14px;}
QLabel#ProjectTitle{font-size:14pt;font-weight:700;color:#ffffff;}
QLabel#ProjectSubtitle{color:#9ca3af;font-size:10pt;}
QLabel#SectionTitle{font-size:12pt;font-weight:600;color:#ffffff;}
QLabel#PassBadge{background:#10b981;color:white;border-radius:8px;font-weight:700;font-size:10pt;padding:2px 6px;}
QLabel#FailBadge{background:#ef4444;color:white;border-radius:8px;font-weight:700;font-size:10pt;padding:2px 6px;}
QLabel#ArchivedBadge{background:#92400e;color:#f59e0b;border-radius:8px;font-weight:700;font-size:10pt;padding:0px 10px;}
QLabel#StepBadge{background:#1e3a8a;color:white;border-radius:19px;font-weight:700;font-size:13pt;}
QLabel#TagPreview{color:#3b82f6;font-size:10pt;}
QWidget#RowSep{background:rgba(45,55,72,120);border:none;}
"""
