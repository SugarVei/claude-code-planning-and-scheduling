"""
UI样式模块（复制自论文配套算法仓库 ui/styles.py，保持桌面界面视觉一致；来源见 vendor_nsga/README.md）
UI Styles Module

定义PyQt5界面的科学风格样式表，采用现代化设计语言。
"""

# 主题颜色 - 科研风格配色方案
COLORS = {
    # 主色调 - 专业蓝色系
    'primary': '#1565C0',           # 主色调 - 深蓝
    'primary_light': '#1E88E5',     # 浅蓝
    'primary_dark': '#0D47A1',      # 深蓝
    'primary_bg': '#E3F2FD',        # 主色背景
    
    # 辅助色
    'secondary': '#00897B',         # 青绿色
    'secondary_light': '#26A69A',   # 浅青绿
    'accent': '#FF6F00',            # 橙色强调
    'accent_light': '#FFA726',      # 浅橙
    
    # 背景色
    'background': '#F5F7FA',        # 页面背景
    'surface': '#FFFFFF',           # 卡片表面
    'surface_alt': '#FAFBFC',       # 替代表面
    
    # 状态色
    'error': '#D32F2F',             # 错误红
    'error_bg': '#FFEBEE',          # 错误背景
    'success': '#388E3C',           # 成功绿
    'success_bg': '#E8F5E9',        # 成功背景
    'warning': '#F57C00',           # 警告橙
    'warning_bg': '#FFF3E0',        # 警告背景
    'info': '#0288D1',              # 信息蓝
    'info_bg': '#E1F5FE',           # 信息背景
    
    # 文字色
    'text_primary': '#1A1A2E',      # 主文字
    'text_secondary': '#5C6370',    # 次要文字
    'text_disabled': '#9E9E9E',     # 禁用文字
    'text_inverse': '#FFFFFF',      # 反色文字
    
    # 边框和分割线
    'border': '#E1E4E8',            # 边框
    'border_light': '#EAECEF',      # 浅边框
    'divider': '#DFE1E6',           # 分割线
    
    # 交互状态
    'hover': '#E8F0FE',             # 悬停
    'active': '#D2E3FC',            # 激活
    'focus': '#1565C0',             # 焦点
    
    # 阴影色
    'shadow': 'rgba(0, 0, 0, 0.08)',
    'shadow_dark': 'rgba(0, 0, 0, 0.12)',
}

# 主样式表
MAIN_STYLESHEET = f"""
/* ==================== 全局样式 ==================== */
QMainWindow {{
    background-color: {COLORS['background']};
}}

QWidget {{
    font-family: 'Microsoft YaHei UI', 'Segoe UI', 'PingFang SC', sans-serif;
    font-size: 10pt;
    color: {COLORS['text_primary']};
}}

/* ==================== 分组框 ==================== */
QGroupBox {{
    font-weight: 600;
    font-size: 10pt;
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    margin-top: 16px;
    padding: 16px 12px 12px 12px;
    background-color: {COLORS['surface']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 12px;
    margin-left: 8px;
    color: {COLORS['primary']};
    background-color: {COLORS['surface']};
    border-radius: 4px;
}}

/* ==================== 标签 ==================== */
QLabel {{
    color: {COLORS['text_primary']};
    padding: 2px 0;
}}

QLabel[heading="true"] {{
    font-size: 12pt;
    font-weight: 600;
    color: {COLORS['primary_dark']};
}}

QLabel[subheading="true"] {{
    font-size: 9pt;
    color: {COLORS['text_secondary']};
}}

/* ==================== 输入框 ==================== */
QLineEdit, QSpinBox, QDoubleSpinBox {{
    padding: 8px 12px;
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    background-color: {COLORS['surface']};
    min-height: 28px;
    selection-background-color: {COLORS['primary_bg']};
}}

QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {COLORS['primary_light']};
}}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {COLORS['primary']};
    border-width: 2px;
    padding: 7px 11px;
}}

QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background-color: {COLORS['surface_alt']};
    color: {COLORS['text_disabled']};
}}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 22px;
    border: none;
    background-color: transparent;
}}

QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {COLORS['hover']};
}}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {COLORS['text_secondary']};
    width: 0;
    height: 0;
}}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {COLORS['text_secondary']};
    width: 0;
    height: 0;
}}

/* ==================== 下拉框 ==================== */
QComboBox {{
    padding: 8px 12px;
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    background-color: {COLORS['surface']};
    min-height: 28px;
}}

QComboBox:hover {{
    border-color: {COLORS['primary_light']};
}}

QComboBox:focus {{
    border-color: {COLORS['primary']};
    border-width: 2px;
}}

QComboBox::drop-down {{
    border: none;
    width: 28px;
    padding-right: 4px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {COLORS['text_secondary']};
    margin-right: 8px;
}}

QComboBox QAbstractItemView {{
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    background-color: {COLORS['surface']};
    selection-background-color: {COLORS['hover']};
    selection-color: {COLORS['text_primary']};
    padding: 4px;
}}

QComboBox QAbstractItemView::item {{
    padding: 8px 12px;
    min-height: 28px;
}}

QComboBox QAbstractItemView::item:hover {{
    background-color: {COLORS['hover']};
}}

/* ==================== 按钮 ==================== */
QPushButton {{
    padding: 10px 24px;
    border: none;
    border-radius: 6px;
    background-color: {COLORS['primary']};
    color: {COLORS['text_inverse']};
    font-weight: 600;
    min-height: 36px;
}}

QPushButton:hover {{
    background-color: {COLORS['primary_light']};
}}

QPushButton:pressed {{
    background-color: {COLORS['primary_dark']};
}}

QPushButton:disabled {{
    background-color: {COLORS['border']};
    color: {COLORS['text_disabled']};
}}

/* 次要按钮 */
QPushButton[secondary="true"] {{
    background-color: {COLORS['surface']};
    color: {COLORS['primary']};
    border: 2px solid {COLORS['primary']};
    padding: 8px 22px;
}}

QPushButton[secondary="true"]:hover {{
    background-color: {COLORS['primary_bg']};
}}

QPushButton[secondary="true"]:pressed {{
    background-color: {COLORS['active']};
}}

/* 成功按钮 */
QPushButton[success="true"] {{
    background-color: {COLORS['success']};
}}

QPushButton[success="true"]:hover {{
    background-color: #43A047;
}}

/* 警告按钮 */
QPushButton[warning="true"] {{
    background-color: {COLORS['warning']};
}}

/* 危险按钮 */
QPushButton[danger="true"] {{
    background-color: {COLORS['error']};
}}

/* 文字按钮 */
QPushButton[text="true"] {{
    background-color: transparent;
    color: {COLORS['primary']};
    border: none;
}}

QPushButton[text="true"]:hover {{
    background-color: {COLORS['hover']};
}}

/* ==================== 单选按钮 ==================== */
QRadioButton {{
    spacing: 10px;
    padding: 4px 0;
}}

QRadioButton::indicator {{
    width: 20px;
    height: 20px;
    border-radius: 10px;
    border: 2px solid {COLORS['border']};
    background-color: {COLORS['surface']};
}}

QRadioButton::indicator:hover {{
    border-color: {COLORS['primary_light']};
}}

QRadioButton::indicator:checked {{
    border-color: {COLORS['primary']};
    background-color: {COLORS['primary']};
}}

QRadioButton::indicator:checked::after {{
    width: 8px;
    height: 8px;
    border-radius: 4px;
    background-color: white;
}}

/* ==================== 复选框 ==================== */
QCheckBox {{
    spacing: 10px;
    padding: 4px 0;
}}

QCheckBox::indicator {{
    width: 20px;
    height: 20px;
    border-radius: 4px;
    border: 2px solid {COLORS['border']};
    background-color: {COLORS['surface']};
}}

QCheckBox::indicator:hover {{
    border-color: {COLORS['primary_light']};
}}

QCheckBox::indicator:checked {{
    border-color: {COLORS['primary']};
    background-color: {COLORS['primary']};
}}

/* ==================== 进度条 ==================== */
QProgressBar {{
    border: none;
    border-radius: 6px;
    background-color: {COLORS['primary_bg']};
    text-align: center;
    min-height: 24px;
    font-weight: 500;
}}

QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 {COLORS['primary']}, 
                                stop:1 {COLORS['secondary']});
    border-radius: 6px;
}}

/* ==================== 选项卡 ==================== */
QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    background-color: {COLORS['surface']};
    padding: 8px;
}}

QTabBar::tab {{
    padding: 10px 20px;
    margin-right: 4px;
    border: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    background-color: {COLORS['surface_alt']};
    color: {COLORS['text_secondary']};
    font-weight: 500;
}}

QTabBar::tab:selected {{
    background-color: {COLORS['surface']};
    color: {COLORS['primary']};
    border-bottom: 3px solid {COLORS['primary']};
}}

QTabBar::tab:hover:!selected {{
    background-color: {COLORS['hover']};
    color: {COLORS['text_primary']};
}}

/* ==================== 文本框 ==================== */
QTextEdit, QPlainTextEdit {{
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    background-color: {COLORS['surface']};
    padding: 12px;
    selection-background-color: {COLORS['primary_bg']};
}}

QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {COLORS['primary']};
}}

/* ==================== 滚动条 ==================== */
QScrollBar:vertical {{
    border: none;
    background-color: transparent;
    width: 12px;
    margin: 4px 2px;
}}

QScrollBar::handle:vertical {{
    background-color: {COLORS['border']};
    border-radius: 5px;
    min-height: 40px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLORS['text_secondary']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}

QScrollBar:horizontal {{
    border: none;
    background-color: transparent;
    height: 12px;
    margin: 2px 4px;
}}

QScrollBar::handle:horizontal {{
    background-color: {COLORS['border']};
    border-radius: 5px;
    min-width: 40px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {COLORS['text_secondary']};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ==================== 表格 ==================== */
QTableWidget, QTableView {{
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    gridline-color: {COLORS['border_light']};
    background-color: {COLORS['surface']};
    alternate-background-color: {COLORS['surface_alt']};
    selection-background-color: {COLORS['primary_bg']};
    selection-color: {COLORS['text_primary']};
}}

QTableWidget::item, QTableView::item {{
    padding: 8px 12px;
    border-bottom: 1px solid {COLORS['border_light']};
}}

QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {COLORS['primary_bg']};
    color: {COLORS['text_primary']};
}}

QHeaderView::section {{
    background-color: {COLORS['surface_alt']};
    padding: 10px 12px;
    border: none;
    border-right: 1px solid {COLORS['border_light']};
    border-bottom: 2px solid {COLORS['border']};
    font-weight: 600;
    color: {COLORS['text_primary']};
}}

QHeaderView::section:hover {{
    background-color: {COLORS['hover']};
}}

/* ==================== 状态栏 ==================== */
QStatusBar {{
    background-color: {COLORS['surface']};
    border-top: 1px solid {COLORS['border']};
    padding: 4px 8px;
    color: {COLORS['text_secondary']};
}}

QStatusBar::item {{
    border: none;
}}

/* ==================== 工具提示 ==================== */
QToolTip {{
    background-color: {COLORS['text_primary']};
    color: {COLORS['text_inverse']};
    border: none;
    padding: 8px 12px;
    border-radius: 6px;
    font-size: 9pt;
}}

/* ==================== 滑块 ==================== */
QSlider::groove:horizontal {{
    border: none;
    height: 6px;
    background-color: {COLORS['border']};
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    background-color: {COLORS['primary']};
    border: none;
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}}

QSlider::handle:horizontal:hover {{
    background-color: {COLORS['primary_light']};
    width: 20px;
    height: 20px;
    margin: -7px 0;
    border-radius: 10px;
}}

QSlider::sub-page:horizontal {{
    background-color: {COLORS['primary']};
    border-radius: 3px;
}}

/* ==================== 分割器 ==================== */
QSplitter::handle {{
    background-color: {COLORS['border']};
}}

QSplitter::handle:horizontal {{
    width: 2px;
}}

QSplitter::handle:vertical {{
    height: 2px;
}}

QSplitter::handle:hover {{
    background-color: {COLORS['primary']};
}}

/* ==================== 菜单 ==================== */
QMenuBar {{
    background-color: {COLORS['surface']};
    border-bottom: 1px solid {COLORS['border']};
    padding: 4px 0;
}}

QMenuBar::item {{
    padding: 8px 16px;
    background-color: transparent;
    border-radius: 4px;
    margin: 0 2px;
}}

QMenuBar::item:selected {{
    background-color: {COLORS['hover']};
}}

QMenu {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 8px 0;
}}

QMenu::item {{
    padding: 10px 24px;
}}

QMenu::item:selected {{
    background-color: {COLORS['hover']};
}}

QMenu::separator {{
    height: 1px;
    background-color: {COLORS['border']};
    margin: 4px 12px;
}}

/* ==================== 框架 ==================== */
QFrame[frameShape="4"] {{
    color: {COLORS['border']};
}}

QFrame[frameShape="5"] {{
    color: {COLORS['border']};
}}
"""

# 运行按钮特殊样式
RUN_BUTTON_STYLE = f"""
QPushButton {{
    font-size: 13pt;
    font-weight: 700;
    padding: 14px 40px;
    min-height: 48px;
    min-width: 160px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 {COLORS['primary']}, 
                                stop:0.5 {COLORS['primary_light']},
                                stop:1 {COLORS['secondary']});
    border-radius: 8px;
    letter-spacing: 1px;
}}

QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 {COLORS['primary_light']}, 
                                stop:0.5 #2196F3,
                                stop:1 {COLORS['secondary_light']});
}}

QPushButton:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 {COLORS['primary_dark']}, 
                                stop:1 #00695C);
}}

QPushButton:disabled {{
    background: {COLORS['border']};
    color: {COLORS['text_disabled']};
}}
"""

# 停止按钮样式
STOP_BUTTON_STYLE = f"""
QPushButton {{
    font-size: 11pt;
    font-weight: 600;
    padding: 10px 24px;
    min-height: 40px;
    background-color: {COLORS['error']};
    border-radius: 6px;
}}

QPushButton:hover {{
    background-color: #E53935;
}}

QPushButton:pressed {{
    background-color: #C62828;
}}
"""

# 结果面板样式
RESULT_PANEL_STYLE = f"""
QFrame {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
    padding: 16px;
}}
"""

# 卡片样式
CARD_STYLE = f"""
QFrame {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
}}

QFrame:hover {{
    border-color: {COLORS['primary_light']};
}}
"""

# 统计卡片样式
STAT_CARD_STYLE = f"""
QFrame {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
    padding: 12px;
}}

QLabel[stat_value="true"] {{
    font-size: 20pt;
    font-weight: 700;
    color: {COLORS['primary']};
}}

QLabel[stat_label="true"] {{
    font-size: 9pt;
    color: {COLORS['text_secondary']};
}}
"""

# 日志面板样式
LOG_PANEL_STYLE = f"""
QPlainTextEdit {{
    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
    font-size: 9pt;
    background-color: #1E1E2E;
    color: #CDD6F4;
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 12px;
    selection-background-color: #45475A;
}}
"""

# 成功消息样式
SUCCESS_MESSAGE_STYLE = f"""
QFrame {{
    background-color: {COLORS['success_bg']};
    border: 1px solid {COLORS['success']};
    border-radius: 8px;
    padding: 12px;
}}

QLabel {{
    color: {COLORS['success']};
}}
"""

# 错误消息样式
ERROR_MESSAGE_STYLE = f"""
QFrame {{
    background-color: {COLORS['error_bg']};
    border: 1px solid {COLORS['error']};
    border-radius: 8px;
    padding: 12px;
}}

QLabel {{
    color: {COLORS['error']};
}}
"""

# 警告消息样式
WARNING_MESSAGE_STYLE = f"""
QFrame {{
    background-color: {COLORS['warning_bg']};
    border: 1px solid {COLORS['warning']};
    border-radius: 8px;
    padding: 12px;
}}

QLabel {{
    color: {COLORS['warning']};
}}
"""

# 信息消息样式
INFO_MESSAGE_STYLE = f"""
QFrame {{
    background-color: {COLORS['info_bg']};
    border: 1px solid {COLORS['info']};
    border-radius: 8px;
    padding: 12px;
}}

QLabel {{
    color: {COLORS['info']};
}}
"""
