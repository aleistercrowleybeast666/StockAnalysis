from __future__ import annotations

from stock_analysis.common.paths import Resources_GetPath

LIGHT_THEME_COLORS = {
    "button": "#3B82F6",
    "button_hover": "#2563EB",
    "button_pressed": "#1D4ED8",
    "button_text": "#FFFFFF",
    "button_disabled": "#9CA3AF",
    "button_disabled_text": "#F9FAFB",
    "focus": "#3B82F6",
    "main_title": "#3B82F6",
    "section_title": "#3B82F6",
    "accent_text": "#3B82F6",
}

_CHECKBOX_CHECK_ICON = Resources_GetPath("icons/checkbox_checked.svg").as_posix()

LIGHT_THEME_QSS = f"""
QMainWindow, QWidget {{
    background-color: #F8FAFC;
    color: #1F2937;
}}
QPushButton {{
    background-color: {LIGHT_THEME_COLORS["button"]};
    color: {LIGHT_THEME_COLORS["button_text"]};
    border: 1px solid {LIGHT_THEME_COLORS["button"]};
    border-radius: 5px;
    min-height: 30px;
    padding: 3px 14px;
}}
QPushButton:hover {{
    background-color: {LIGHT_THEME_COLORS["button_hover"]};
    border-color: {LIGHT_THEME_COLORS["button_hover"]};
}}
QPushButton:pressed {{
    background-color: {LIGHT_THEME_COLORS["button_pressed"]};
    border-color: {LIGHT_THEME_COLORS["button_pressed"]};
}}
QPushButton:focus {{
    border: 2px solid {LIGHT_THEME_COLORS["focus"]};
}}
QPushButton:disabled {{
    background-color: {LIGHT_THEME_COLORS["button_disabled"]};
    border-color: {LIGHT_THEME_COLORS["button_disabled"]};
    color: {LIGHT_THEME_COLORS["button_disabled_text"]};
}}
QLabel#main_title {{
    color: {LIGHT_THEME_COLORS["main_title"]};
    font-size: 22px;
    font-weight: 600;
    padding: 4px 0;
}}
QLabel#main_subtitle, QLabel#scope_note, QLabel#user_note {{
    color: #64748B;
    padding-bottom: 6px;
}}
QLabel#stage_label, QLabel#status_label {{
    color: {LIGHT_THEME_COLORS["section_title"]};
    font-weight: 600;
}}
QGroupBox {{
    border: 1px solid {LIGHT_THEME_COLORS["button"]};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 8px;
    background-color: #FFFFFF;
}}
QGroupBox::title {{
    color: {LIGHT_THEME_COLORS["section_title"]};
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    font-weight: 600;
}}
QCheckBox {{
    spacing: 7px;
}}
QRadioButton {{
    spacing: 7px;
}}
QCheckBox::indicator, QGroupBox::indicator {{
    width: 17px;
    height: 17px;
    border: 2px solid #64748B;
    border-radius: 3px;
    background-color: #FFFFFF;
}}
QCheckBox::indicator:unchecked, QGroupBox::indicator:unchecked {{
    image: none;
}}
QCheckBox::indicator:hover, QGroupBox::indicator:hover {{
    border-color: {LIGHT_THEME_COLORS["button"]};
}}
QCheckBox::indicator:checked, QGroupBox::indicator:checked {{
    border-color: {LIGHT_THEME_COLORS["button"]};
    background-color: {LIGHT_THEME_COLORS["button"]};
    image: url("{_CHECKBOX_CHECK_ICON}");
}}
QCheckBox::indicator:disabled, QGroupBox::indicator:disabled {{
    border-color: #9CA3AF;
    background-color: #E5E7EB;
}}
QCheckBox::indicator:checked:disabled, QGroupBox::indicator:checked:disabled {{
    border-color: #9CA3AF;
    background-color: #9CA3AF;
}}
QRadioButton::indicator {{
    width: 17px;
    height: 17px;
    border: 2px solid #64748B;
    border-radius: 10px;
    background-color: #FFFFFF;
}}
QRadioButton::indicator:unchecked {{
    image: none;
}}
QRadioButton::indicator:hover {{
    border-color: {LIGHT_THEME_COLORS["button"]};
}}
QRadioButton::indicator:checked {{
    border: 5px solid {LIGHT_THEME_COLORS["button"]};
    background-color: #FFFFFF;
}}
QRadioButton::indicator:disabled {{
    border-color: #9CA3AF;
    background-color: #E5E7EB;
}}
QToolButton {{
    color: {LIGHT_THEME_COLORS["accent_text"]};
    background-color: #FFFFFF;
    border: 1px solid #93C5FD;
    border-radius: 4px;
    min-height: 26px;
    padding: 2px 10px;
}}
QToolButton:hover, QToolButton:checked {{
    background-color: #EFF6FF;
    border-color: {LIGHT_THEME_COLORS["button"]};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {{
    background-color: #FFFFFF;
    border: 1px solid #94A3B8;
    border-radius: 4px;
    padding: 3px 5px;
    selection-background-color: {LIGHT_THEME_COLORS["button"]};
    selection-color: #FFFFFF;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QTextEdit:focus {{
    border: 1px solid {LIGHT_THEME_COLORS["focus"]};
}}
QProgressBar {{
    border: 1px solid {LIGHT_THEME_COLORS["button"]};
    border-radius: 5px;
    background-color: #E5E7EB;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {LIGHT_THEME_COLORS["button"]};
    border-radius: 4px;
}}
QSplitter::handle {{
    background-color: #CBD5E1;
}}
"""
