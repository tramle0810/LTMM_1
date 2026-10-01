"""
E-Wallet - giao diện mobile (PySide6)

Font cần có (đặt cạnh file này hoặc trong thư mục fonts/):
    Isometra-Regular.ttf   -> chữ "E-WALLET"
    Roboto-Regular.ttf     -> chữ thường
    Roboto-Medium.ttf      -> tiêu đề, nút, nhãn nhấn mạnh
"""
import os
import sys
import secrets
import hashlib
from datetime import datetime
import database 

from database import get_connection, init_db, show_database
from crypto_utils import generate_key_pair, hash_transaction, sign_data, verify_signature


from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter,
    QPalette, QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout,
    QWidget,
)
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

# Đường dẫn đến wallet.db nằm cùng thư mục với mobile_app.py
database.DATABASE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "wallet.db"
)


def get_user_by_account(account_number):
    """Lấy thông tin người dùng theo số tài khoản."""
    conn = database.get_connection()
    try:
        return conn.execute(
            """
            SELECT id, username, password, account_number, balance
            FROM users
            WHERE account_number = ?
            """,
            (account_number,)
        ).fetchone()
    finally:
        conn.close()

def get_transactions_for_account(account_number):
    conn = database.get_connection()

    try:
        rows = conn.execute(
            """
            SELECT
                t.id,
                sender.account_number AS sender_account,
                receiver.account_number AS receiver_account,
                t.amount,
                t.timestamp AS created_at,
                t.transaction_hash AS tx_hash,
                t.signature
            FROM transactions AS t
            JOIN users AS sender ON sender.id = t.sender_id
            JOIN users AS receiver ON receiver.id = t.receiver_id
            WHERE sender.account_number = ?
               OR receiver.account_number = ?
            ORDER BY t.id DESC
            """,
            (account_number, account_number)
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()


def format_money(value):
    return f"{float(value or 0):,.0f} VNĐ"
# =====================================================================
# 1. THEME – bảng màu navy (lấy từ ảnh palette)
# =====================================================================
class C:
    INK = "#1B263B"        # Deep Navy  – chữ chính, nút
    NAVY = "#0D1B2A"       # Navy       – nhấn đậm
    STEEL = "#3D5A80"      # Steel Blue – accent, icon
    AIRY = "#98B4C7"       # Airy Blue
    PALE = "#D8E6F2"       # Pale Blue
    ICE = "#EAF2F8"        # Ice Blue
    BEIGE = "#F2EFE7"
    WHITE = "#FFFFFF"
    MUTED = "#5F7C97"      # chữ phụ
    LINE = "#E6ECF3"       # viền input / đường kẻ
    PLACEHOLDER = "#9AA8B7"
    IN = "#2F7F73"         # tiền vào
    OUT = "#C0524A"        # tiền ra


# =====================================================================
# 2. FONT
# =====================================================================
class Fonts:
    isometra = "Arial Black"      # fallback nếu thiếu Isometra
    regular = "Segoe UI"
    medium = "Segoe UI"
    medium_weight = 600


def load_fonts():
    """Nạp font từ ./fonts hoặc cùng thư mục với file này.
    Gọi SAU khi đã tạo QApplication."""
    here = os.path.dirname(os.path.abspath(__file__))
    folders = [os.path.join(here, "fonts"), here]

    def register(filename):
        for folder in folders:
            path = os.path.join(folder, filename)
            if os.path.isfile(path):
                font_id = QFontDatabase.addApplicationFont(path)
                if font_id != -1:
                    families = QFontDatabase.applicationFontFamilies(font_id)
                    if families:
                        return families[0]
        print(f"[font] Không tìm thấy {filename} - dùng font dự phòng")
        return None

    iso = register("Isometra-Regular.ttf")
    reg = register("RobotoSlab-Regular.ttf")
    med = register("RobotoSlab-Medium.ttf")

    if iso:
        Fonts.isometra = iso
    if reg:
        Fonts.regular = reg
    if med:
        Fonts.medium = med
        # Nếu Medium và Regular cùng family "Roboto" -> chọn Medium bằng weight 500
        Fonts.medium_weight = 500 if med == Fonts.regular else 400
    else:
        Fonts.medium = Fonts.regular
        Fonts.medium_weight = 600


# =====================================================================
# 3. ICON (SVG vẽ bằng code, không cần file ảnh)
# =====================================================================
_ICON_BODY = {
    "eye": '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    "eye_off": ('<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94'
                'M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19'
                'm-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>'),
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/>',
    "arrow_left": '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
    "log_out": ('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>'
                '<polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>'),
    "deposit": ('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
                '<polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>'),
    "send": '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "arrow_up_right": '<line x1="7" y1="17" x2="17" y2="7"/><polyline points="7 7 17 7 17 17"/>',
    "arrow_down_left": '<line x1="17" y1="7" x2="7" y2="17"/><polyline points="17 17 7 17 7 7"/>',
}


def svg_pixmap(name, color, size=24, stroke=2.0):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round">{_ICON_BODY[name]}</svg>'
    )
    ratio = 2  # nét sắc trên màn hình retina
    pm = QPixmap(size * ratio, size * ratio)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
    painter.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def svg_icon(name, color, size=24, stroke=2.0):
    return QIcon(svg_pixmap(name, color, size, stroke))


# =====================================================================
# 4. STYLE SHEET
# =====================================================================
_QSS = """
/* ---------- Chữ ---------- */
QLabel { background: transparent; color: @INK@; font-family: "@REG@"; font-size: 15px; }
QLabel#AppTitle  { font-family: "@ISO@"; font-size: 34px; color: @INK@; }
QLabel#WordMark  { font-family: "@ISO@"; font-size: 22px; color: @INK@; }
QLabel#H1 { font-family: "@MED@"; font-weight: @MEDW@; font-size: 34px; }
QLabel#H2 { font-family: "@MED@"; font-weight: @MEDW@; font-size: 22px; }
QLabel#H3 { font-family: "@MED@"; font-weight: @MEDW@; font-size: 17px; }
QLabel#Subtitle { font-family: "@MED@"; font-weight: @MEDW@; font-size: 15px; color: @MUTED@; }
QLabel#FieldLabel { font-size: 15px; color: @INK@; }
QLabel#Muted { color: @MUTED@; font-size: 15px; }
QLabel#Tiny  { color: @MUTED@; font-size: 12px; }

QLabel#CardCaption { font-family: "@MED@"; font-weight: @MEDW@; font-size: 12px; color: @AIRY@; }
QLabel#CardMeta    { font-size: 14px; color: @PALE@; }
QLabel#Balance     { font-family: "@MED@"; font-weight: @MEDW@; font-size: 32px; color: white; }

QLabel#RowTitle  { font-family: "@MED@"; font-weight: @MEDW@; font-size: 15px; }
QLabel#RowSub    { font-size: 12px; color: @MUTED@; }
QLabel#AmountIn  { font-family: "@MED@"; font-weight: @MEDW@; font-size: 15px; color: @IN@; }
QLabel#AmountOut { font-family: "@MED@"; font-weight: @MEDW@; font-size: 15px; color: @OUT@; }
QLabel#Badge     { background: @PALE@; border-radius: 22px; }
QLabel#Banner {
    background: @ICE@; color: @STEEL@; border-radius: 16px; padding: 12px 14px;
    font-family: "@MED@"; font-weight: @MEDW@; font-size: 13px;
}

/* ---------- Khung ---------- */
QFrame#Card  { background: rgba(255,255,255,245); border-radius: 36px; }
QFrame#Panel { background: rgba(255,255,255,245); border-radius: 26px; }
QFrame#BalanceCard {
    border-radius: 28px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @INK@, stop:1 @STEEL@);
}
QFrame#Line { background: @LINE@; border: none; }

/* ---------- Ô nhập ---------- */
QLineEdit {
    background: #F8FAFC; border: 2px solid @LINE@; border-radius: 26px;
    padding: 0 16px 0 20px; min-height: 48px;
    font-family: "@REG@"; font-size: 16px; color: @INK@;
    selection-background-color: @PALE@; selection-color: @INK@;
}
QLineEdit:focus { border: 2px solid @STEEL@; background: white; }

/* ---------- Nút ---------- */
QPushButton#Primary {
    color: white; border: none; border-radius: 28px; min-height: 56px;
    font-family: "@MED@"; font-weight: @MEDW@; font-size: 17px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @INK@, stop:1 @STEEL@);
}
QPushButton#Primary:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #24344F, stop:1 #4A6E9A);
}
QPushButton#Primary:pressed { background: @NAVY@; }

QPushButton#Link {
    background: transparent; border: none; color: @INK@;
    font-family: "@REG@"; font-size: 17px; min-height: 34px;
}
QPushButton#Link:hover { color: @STEEL@; }

QPushButton#TextLink {
    background: transparent; border: none; color: @STEEL@;
    font-family: "@MED@"; font-weight: @MEDW@; font-size: 13px;
}
QPushButton#TextLink:hover { color: @INK@; }

QPushButton#IconBtn { background: transparent; border: none; }
QPushButton#BackBtn {
    background: rgba(255,255,255,190); border: none; border-radius: 22px;
}
QPushButton#BackBtn:hover { background: white; }

QPushButton#Chip {
    background: #F1F5F9; border: 2px solid @LINE@; border-radius: 20px; min-height: 36px;
    font-family: "@MED@"; font-weight: @MEDW@; font-size: 13px; color: @INK@;
}
QPushButton#Chip:hover { background: @PALE@; }

QToolButton#Tile {
    background: rgba(255,255,255,245); border: none; border-radius: 22px;
    color: @INK@; font-family: "@MED@"; font-weight: @MEDW@; font-size: 13px;
    padding-top: 10px;
}
QToolButton#Tile:hover { background: @ICE@; }

/* ---------- Scroll (trong suốt, ẩn thanh cuộn) ---------- */
QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { width: 0px; background: transparent; }

/* ---------- Hộp thoại ---------- */
QMessageBox { background: white; }
QMessageBox QLabel { color: @INK@; font-size: 14px; }
QMessageBox QPushButton {
    background: @STEEL@; color: white; border: none; border-radius: 14px;
    min-width: 84px; padding: 8px 16px;
    font-family: "@MED@"; font-weight: @MEDW@; font-size: 13px;
}
QMessageBox QPushButton:hover { background: @INK@; }
"""


def build_stylesheet():
    tokens = {
        "INK": C.INK, "NAVY": C.NAVY, "STEEL": C.STEEL, "AIRY": C.AIRY,
        "PALE": C.PALE, "ICE": C.ICE, "MUTED": C.MUTED, "LINE": C.LINE,
        "IN": C.IN, "OUT": C.OUT,
        "REG": Fonts.regular, "MED": Fonts.medium, "ISO": Fonts.isometra,
        "MEDW": str(Fonts.medium_weight),
    }
    qss = _QSS
    for key, value in tokens.items():
        qss = qss.replace(f"@{key}@", value)
    return qss


# =====================================================================
# 5. WIDGET DÙNG CHUNG
# =====================================================================
class GradientBackground(QWidget):
    """Nền gradient xanh navy + các vòng tròn mờ trang trí."""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        grad = QLinearGradient(0, 0, w * 0.35, h)
        grad.setColorAt(0.00, QColor(C.ICE))
        grad.setColorAt(0.45, QColor("#8FA9BE"))
        grad.setColorAt(1.00, QColor("#3F5F86"))
        p.fillRect(self.rect(), grad)

        p.setPen(Qt.NoPen)
        # (tâm x, tâm y, bán kính, độ mờ)
        circles = [
            (0.88 * w, 0.02 * h, 0.40 * w, 55),   # góc trên phải
            (-0.04 * w, 0.28 * h, 0.17 * w, 35),  # mép trái
            (0.04 * w, 0.79 * h + 0.52 * w, 0.52 * w, 28),  # góc dưới trái
        ]
        for cx, cy, r, alpha in circles:
            p.setBrush(QColor(255, 255, 255, alpha))
            p.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))


def add_shadow(widget, blur=40, dy=12, color=QColor(13, 27, 42, 70)):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(color)
    widget.setGraphicsEffect(effect)


def make_label(text, name=None, align=None, wrap=False):
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    if align is not None:
        label.setAlignment(align)
    label.setWordWrap(wrap)
    return label


def make_input(placeholder, password=False):
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    if password:
        edit.setEchoMode(QLineEdit.Password)
        action = edit.addAction(svg_icon("eye_off", C.STEEL, 22), QLineEdit.TrailingPosition)

        def toggle():
            hidden = edit.echoMode() == QLineEdit.Password
            edit.setEchoMode(QLineEdit.Normal if hidden else QLineEdit.Password)
            action.setIcon(svg_icon("eye" if hidden else "eye_off", C.STEEL, 22))

        action.triggered.connect(toggle)
    return edit


def make_primary(text, slot):
    btn = QPushButton(text)
    btn.setObjectName("Primary")
    btn.setCursor(Qt.PointingHandCursor)
    btn.clicked.connect(slot)
    add_shadow(btn, blur=28, dy=10, color=QColor(27, 38, 59, 90))
    return btn


def make_link(text, slot):
    btn = QPushButton(text)
    btn.setObjectName("Link")
    btn.setCursor(Qt.PointingHandCursor)
    btn.clicked.connect(slot)
    return btn


def make_line(height=2):
    line = QFrame()
    line.setObjectName("Line")
    line.setFixedHeight(height)
    return line


def make_divider(text):
    """Đường kẻ - chữ - đường kẻ, ví dụ: ───── Hoặc ─────"""
    row = QHBoxLayout()
    row.setSpacing(14)
    row.addWidget(make_line(), 1)
    row.addWidget(make_label(text, "Tiny"))
    row.addWidget(make_line(), 1)
    return row


def make_card(radius_name="Card"):
    frame = QFrame()
    frame.setObjectName(radius_name)
    add_shadow(frame)
    return frame


def make_round_button(icon_name, slot, color=C.INK):
    btn = QPushButton()
    btn.setObjectName("BackBtn")
    btn.setIcon(svg_icon(icon_name, color, 22))
    btn.setIconSize(QSize(22, 22))
    btn.setFixedSize(44, 44)
    btn.setCursor(Qt.PointingHandCursor)
    btn.clicked.connect(slot)
    return btn


def scrollable(content):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(content)
    return area


def parse_amount(text):
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


class TransactionRow(QWidget):
    ICONS = {
        "deposit": ("arrow_down_left", True),
        "receive": ("arrow_down_left", True),
        "transfer": ("arrow_up_right", False),
    }

    def __init__(self, kind, title, subtitle, amount, status=None):
        super().__init__()
        icon_name, incoming = self.ICONS[kind]

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 10, 0, 10)
        row.setSpacing(14)

        badge = QLabel()
        badge.setObjectName("Badge")
        badge.setFixedSize(44, 44)
        badge.setAlignment(Qt.AlignCenter)
        badge.setPixmap(svg_pixmap(icon_name, C.STEEL, 22))
        row.addWidget(badge)

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(make_label(title, "RowTitle"))
        text.addWidget(make_label(subtitle, "RowSub"))
        row.addLayout(text, 1)

        right = QVBoxLayout()
        right.setSpacing(2)
        right.addWidget(make_label(amount, "AmountIn" if incoming else "AmountOut", Qt.AlignRight))
        if status:
            right.addWidget(make_label(status, "RowSub", Qt.AlignRight))
        row.addLayout(right)


def add_rows(layout, rows, with_status=False):
    for i, (kind, title, sub, amount, status) in enumerate(rows):
        if i:
            layout.addWidget(make_line(1))
        layout.addWidget(TransactionRow(kind, title, sub, amount, status if with_status else None))


# Giao dịch được tải trực tiếp từ wallet.db sau khi đăng nhập.


# =====================================================================
# 6. MÀN HÌNH CHÍNH
# =====================================================================
LOGIN, REGISTER, DASHBOARD, DEPOSIT, TRANSFER, HISTORY = range(6)


class EWalletMobileApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("E-Wallet")
        self.resize(390, 800)
        self.setMinimumSize(360, 700)

        self.is_balance_hidden = False
        self.raw_balance_str = "0 VNĐ"
        self.current_stk_counter = 10000001
        self.current_user = None
        self.recent_layout = None
        self.history_layout = None

        background = GradientBackground()
        self.setCentralWidget(background)
        outer = QVBoxLayout(background)
        outer.setContentsMargins(0, 0, 0, 0)

        self.stacked = QStackedWidget()
        outer.addWidget(self.stacked)

        # Thứ tự add phải khớp LOGIN, REGISTER, DASHBOARD, ...
        self.stacked.addWidget(self.build_login_screen())
        self.stacked.addWidget(self.build_register_screen())
        self.stacked.addWidget(self.build_dashboard_screen())
        self.stacked.addWidget(self.build_deposit_screen())
        self.stacked.addWidget(self.build_transfer_screen())
        self.stacked.addWidget(self.build_history_screen())

        self.setStyleSheet(build_stylesheet())
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(C.PLACEHOLDER))
        self.setPalette(palette)

        self.go(LOGIN)

    def go(self, index):
            self.stacked.setCurrentIndex(index)

    # ------------------------------------------------------------ auth
    def auth_page(self, build_card_content):
            """Khung chung cho Login/Register: tiêu đề E-WALLET + card trắng + icon khiên."""
            content = QWidget()
            root = QVBoxLayout(content)
            root.setContentsMargins(24, 40, 24, 24)
            root.setSpacing(0)

            root.addWidget(make_label("E-WALLET", "AppTitle", Qt.AlignCenter))
            root.addSpacing(30)

            card = make_card("Card")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(30, 32, 30, 28)
            layout.setSpacing(0)
            build_card_content(layout)
            root.addWidget(card)

            shield = QLabel()
            shield.setPixmap(svg_pixmap("shield", C.STEEL, 30, 1.8))
            shield.setAlignment(Qt.AlignCenter)
            root.addSpacing(24)
            root.addWidget(shield)
            root.addStretch()
            return scrollable(content)

    def build_login_screen(self):
        def card_content(layout):
            layout.addWidget(make_label("Xin chào", "H1"))
            layout.addSpacing(2)
            layout.addWidget(make_label("Đăng nhập để quản lý ví của bạn", "Subtitle"))
            layout.addSpacing(22)

            layout.addWidget(make_label("Số tài khoản", "FieldLabel"))
            layout.addSpacing(8)
            self.login_stk = make_input("Nhập số tài khoản")
            layout.addWidget(self.login_stk)
            layout.addSpacing(16)

            layout.addWidget(make_label("Mật khẩu", "FieldLabel"))
            layout.addSpacing(8)
            self.login_pass = make_input("Nhập mật khẩu", password=True)
            layout.addWidget(self.login_pass)
            layout.addSpacing(26)

            layout.addWidget(make_primary("ĐĂNG NHẬP", self.handle_login))
            layout.addSpacing(22)
            layout.addLayout(make_divider("Hoặc"))
            layout.addSpacing(14)
            layout.addWidget(make_label("Bạn chưa có tài khoản?", "Muted", Qt.AlignCenter))
            layout.addWidget(make_link("Đăng ký tài khoản", lambda: self.go(REGISTER)))

            return self.auth_page(card_content)

    def build_register_screen(self):
        def card_content(layout):
            layout.addWidget(make_label("Đăng ký", "H1"))
            layout.addSpacing(2)
            layout.addWidget(make_label("Tạo tài khoản mới để trải nghiệm ví", "Subtitle"))
            layout.addSpacing(20)

            layout.addWidget(make_label("Họ và tên", "FieldLabel"))
            layout.addSpacing(8)
            self.reg_fullname = make_input("Nhập họ và tên đầy đủ")
            layout.addWidget(self.reg_fullname)
            layout.addSpacing(14)

            layout.addWidget(make_label("Mật khẩu", "FieldLabel"))
            layout.addSpacing(8)
            self.reg_pass = make_input("Nhập mật khẩu", password=True)
            layout.addWidget(self.reg_pass)
            layout.addSpacing(14)

            layout.addWidget(make_label("Nhập lại mật khẩu", "FieldLabel"))
            layout.addSpacing(8)
            self.reg_confirm_pass = make_input("Xác nhận lại mật khẩu", password=True)
            layout.addWidget(self.reg_confirm_pass)
            layout.addSpacing(24)

            layout.addWidget(make_primary("ĐĂNG KÝ TÀI KHOẢN", self.handle_register))
            layout.addSpacing(18)
            layout.addLayout(make_divider("Hoặc"))
            layout.addSpacing(10)
            layout.addWidget(make_label("Đã có tài khoản?", "Muted", Qt.AlignCenter))
            layout.addWidget(make_link("Quay lại đăng nhập", lambda: self.go(LOGIN)))

        return self.auth_page(card_content)

    def refresh_account_data(self):
        if not self.current_user:
            return

        user = get_user_by_account(
            self.current_user["account_number"]
        )

        if not user:
            return

        self.current_user = dict(user)

        # Cập nhật thông tin tài khoản trên giao diện
        self.dash_user_name.setText(user["username"])
        self.dash_stk.setText(
            f"STK: {user['account_number']}"
        )

        self.raw_balance_str = format_money(user["balance"])

        if not self.is_balance_hidden:
            self.lbl_balance.setText(self.raw_balance_str)

        # Lấy giao dịch thật từ SQLite
        transactions = get_transactions_for_account(
            user["account_number"]
        )

        # Hai giao dịch gần nhất ở màn hình chính
        self.populate_transaction_layout(
            self.recent_layout,
            transactions[:2],
            with_status=False
        )

        # Toàn bộ lịch sử giao dịch
        self.populate_transaction_layout(
            self.history_layout,
            transactions,
            with_status=True
        )
    def populate_transaction_layout(self, layout, rows, with_status=False):
            # Xóa danh sách cũ
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        if not rows:
            layout.addWidget(
                make_label(
                    "Chưa có giao dịch trong tài khoản này.",
                    "Muted",
                    wrap=True
                )
            )
            return

        current_account = (
            self.current_user.get("account_number")
            if self.current_user else None
        )

        display_rows = []

        for tx in rows:
            sender = str(tx["sender_account"])
            receiver = str(tx["receiver_account"])
            amount = float(tx["amount"] or 0)
            timestamp = str(tx["created_at"] or "")

            if sender == str(current_account):
                kind = "transfer"
                title = "Chuyển tiền"
                subtitle = f"Đến STK: {receiver}"
                amount_text = f"-{format_money(amount)}"
            else:
                kind = "receive"
                title = "Nhận tiền"
                subtitle = f"Từ STK: {sender}"
                amount_text = f"+{format_money(amount)}"

            if timestamp:
                subtitle += f" · {timestamp}"

            status = "Hoàn tất" if with_status else None

            display_rows.append(
                (kind, title, subtitle, amount_text, status)
            )

        add_rows(layout, display_rows, with_status=with_status)
    
    def handle_login(self):
        account_number = self.login_stk.text().strip()
        password = self.login_pass.text()
        if not account_number or not password:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập số tài khoản và mật khẩu.")
            return
        try:
            user = get_user_by_account(account_number)
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi database", f"Không đọc được wallet.db:\n{exc}")
            return
        password = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if not user or password != user["password"]:
            QMessageBox.warning(self, "Đăng nhập thất bại", "Số tài khoản hoặc mật khẩu không đúng.")
            return
        self.current_user = dict(user)
        self.refresh_account_data()
        self.login_pass.clear()
        self.go(DASHBOARD)

    def handle_register(self):
        fullname = self.reg_fullname.text().strip()
        pwd1 = self.reg_pass.text()
        pwd2 = self.reg_confirm_pass.text()

        if not fullname or not pwd1 or not pwd2:
            QMessageBox.warning(
                self, "Thiếu thông tin",
                "Vui lòng điền đầy đủ thông tin."
            )
            return

        if pwd1 != pwd2:
            QMessageBox.warning(
                self, "Lỗi",
                "Mật khẩu xác nhận không trùng khớp."
            )
            return

        if len(pwd1) < 6:
            QMessageBox.warning(
                self, "Mật khẩu quá ngắn",
                "Mật khẩu cần ít nhất 6 ký tự."
            )
            return

        conn = None

        try:
            conn = database.get_connection()

            # Kiểm tra tên đăng nhập đã tồn tại chưa
            existing = conn.execute(
                "SELECT id FROM users WHERE username = ?",
                (fullname,)
            ).fetchone()

            if existing:
                QMessageBox.warning(
                    self, "Tên tài khoản đã tồn tại",
                    "Vui lòng sử dụng tên khác."
                )
                return

            # Tạo cặp khóa RSA
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048
            )

            private_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode("utf-8")

            public_pem = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")

            # Giữ cách băm mật khẩu SHA-256 tương thích handle_login
            password_hash = hashlib.sha256(
                pwd1.encode("utf-8")
            ).hexdigest()

            # Tạo số tài khoản tiếp theo
            stk = database.generate_account_number(
                conn.cursor()
            )

            # Bảng users có đúng 6 cột cần ghi
            conn.execute(
                """
                INSERT INTO users (
                    username,
                    password,
                    account_number,
                    balance,
                    private_key,
                    public_key
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    fullname,
                    password_hash,
                    stk,
                    0.0,
                    private_pem,
                    public_pem,
                )
            )

            conn.commit()

        except Exception as exc:
            if conn:
                conn.rollback()

            QMessageBox.critical(
                self, "Lỗi đăng ký",
                f"Không thể tạo tài khoản:\n{exc}"
            )
            return

        finally:
            if conn:
                conn.close()

        QMessageBox.information(
            self,
            "Đăng ký thành công",
            f"Chủ tài khoản: {fullname}\n"
            f"Số tài khoản: {stk}\n\n"
            "Hãy lưu lại số tài khoản để đăng nhập."
        )

        self.login_stk.setText(stk)

        for edit in (
            self.reg_fullname,
            self.reg_pass,
            self.reg_confirm_pass
        ):
            edit.clear()

        self.go(LOGIN)
    
    def handle_logout(self):
        self.current_user = None
        self.login_pass.clear()
        self.go(LOGIN)

    # ------------------------------------------------------- dashboard
    def build_dashboard_screen(self):
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 28, 24, 24)
        root.setSpacing(0)

        top = QHBoxLayout()
        top.addWidget(make_label("E-WALLET", "WordMark"))
        top.addStretch()
        top.addWidget(make_round_button("log_out", self.handle_logout))
        root.addLayout(top)

        root.addSpacing(20)
        root.addWidget(make_label("Xin chào,", "Muted"))
        self.dash_user_name = make_label("Khách hàng", "H2")
        root.addWidget(self.dash_user_name)

        root.addSpacing(18)
        root.addWidget(self.build_balance_card())

        root.addSpacing(18)
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        tiles.addWidget(self.make_tile("deposit", "Nạp tiền", lambda: self.go(DEPOSIT)))
        tiles.addWidget(self.make_tile("send", "Chuyển tiền", lambda: self.go(TRANSFER)))
        tiles.addWidget(self.make_tile("clock", "Lịch sử", lambda: self.go(HISTORY)))
        root.addLayout(tiles)

        root.addSpacing(18)
        panel = make_card("Panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(22, 18, 22, 10)
        pl.setSpacing(0)
        head = QHBoxLayout()
        head.addWidget(make_label("Giao dịch gần đây", "H3"))
        head.addStretch()
        see_all = QPushButton("Xem tất cả")
        see_all.setObjectName("TextLink")
        see_all.setCursor(Qt.PointingHandCursor)
        see_all.clicked.connect(lambda: self.go(HISTORY))
        head.addWidget(see_all)
        pl.addLayout(head)
        pl.addSpacing(4)
        self.recent_layout = pl
        add_rows(self.recent_layout, [])
        root.addWidget(panel)

        root.addStretch()
        return scrollable(content)

    def build_balance_card(self):
        card = QFrame()
        card.setObjectName("BalanceCard")
        add_shadow(card, blur=36, dy=14, color=QColor(13, 27, 42, 90))
        v = QVBoxLayout(card)
        v.setContentsMargins(24, 20, 20, 22)
        v.setSpacing(0)

        top = QHBoxLayout()
        top.addWidget(make_label("SỐ DƯ KHẢ DỤNG", "CardCaption"))
        top.addStretch()
        self.btn_eye = QPushButton()
        self.btn_eye.setObjectName("IconBtn")
        self.btn_eye.setIcon(svg_icon("eye", C.PALE, 22))
        self.btn_eye.setIconSize(QSize(22, 22))
        self.btn_eye.setFixedSize(34, 34)
        self.btn_eye.setCursor(Qt.PointingHandCursor)
        self.btn_eye.clicked.connect(self.toggle_balance)
        top.addWidget(self.btn_eye)
        v.addLayout(top)

        self.lbl_balance = make_label(self.raw_balance_str, "Balance")
        v.addWidget(self.lbl_balance)
        v.addSpacing(14)

        self.dash_stk = make_label("STK: 10000001", "CardMeta")
        v.addWidget(self.dash_stk)
        v.addSpacing(10)

        secure = QHBoxLayout()
        secure.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(svg_pixmap("shield", C.AIRY, 16, 2))
        secure.addWidget(icon)
        secure.addWidget(make_label("Bảo vệ bởi SHA-256 & chữ ký RSA", "CardCaption"))
        secure.addStretch()
        v.addLayout(secure)
        return card

    def make_tile(self, icon_name, text, slot):
        btn = QToolButton()
        btn.setObjectName("Tile")
        btn.setIcon(svg_icon(icon_name, C.STEEL, 26))
        btn.setIconSize(QSize(26, 26))
        btn.setText(text)
        btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(88)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.clicked.connect(slot)
        return btn

    def toggle_balance(self):
        self.is_balance_hidden = not self.is_balance_hidden
        if self.is_balance_hidden:
            self.lbl_balance.setText("••••••••")
            self.btn_eye.setIcon(svg_icon("eye_off", C.PALE, 22))
        else:
            self.lbl_balance.setText(self.raw_balance_str)
            self.btn_eye.setIcon(svg_icon("eye", C.PALE, 22))

    # --------------------------------------------------- trang con
    def sub_page(self, title, build_panel_content):
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 28, 24, 24)
        root.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(make_round_button("arrow_left", lambda: self.go(DASHBOARD)))
        head.addWidget(make_label(title, "H2"))
        head.addStretch()
        root.addLayout(head)
        root.addSpacing(24)

        panel = make_card("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(0)
        build_panel_content(layout)
        root.addWidget(panel)
        root.addStretch()
        return scrollable(content)

    def build_deposit_screen(self):
        def content(layout):
            layout.addWidget(make_label("Số tiền muốn nạp (VNĐ)", "FieldLabel"))
            layout.addSpacing(8)
            self.dep_input = make_input("Nhập số tiền")
            self.dep_input.setText("500,000")
            layout.addWidget(self.dep_input)
            layout.addSpacing(14)

            grid = QGridLayout()
            grid.setSpacing(10)
            for i, amt in enumerate(["100,000", "200,000", "500,000", "1,000,000"]):
                chip = QPushButton(amt)
                chip.setObjectName("Chip")
                chip.setCursor(Qt.PointingHandCursor)
                chip.clicked.connect(lambda _=False, a=amt: self.dep_input.setText(a))
                grid.addWidget(chip, i // 2, i % 2)
            layout.addLayout(grid)
            layout.addSpacing(26)
            layout.addWidget(make_primary("XÁC NHẬN NẠP TIỀN", self.handle_deposit))

        return self.sub_page("Nạp tiền vào ví", content)

    def handle_deposit(self):
        amount = parse_amount(self.dep_input.text())
        if amount <= 0:
            QMessageBox.warning(self, "Số tiền không hợp lệ", "Vui lòng nhập số tiền lớn hơn 0.")
            return
        QMessageBox.information(
            self, "Chưa tích hợp nạp tiền",
            "Chức năng nạp tiền chưa được kết nối với database; số dư không thay đổi."
        )

    def build_transfer_screen(self):
        def content(layout):
            layout.addWidget(make_label(
                "Giao dịch được băm SHA-256 và ký bằng RSA private key.", "Banner", wrap=True))
            layout.addSpacing(18)

            layout.addWidget(make_label("Số tài khoản người nhận", "FieldLabel"))
            layout.addSpacing(8)
            self.trans_stk = make_input("Nhập số tài khoản nhận")
            layout.addWidget(self.trans_stk)
            layout.addSpacing(14)

            layout.addWidget(make_label("Số tiền chuyển (VNĐ)", "FieldLabel"))
            layout.addSpacing(8)
            self.trans_amt = make_input("Nhập số tiền")
            layout.addWidget(self.trans_amt)
            layout.addSpacing(26)

            layout.addWidget(make_primary("KÝ & CHUYỂN TIỀN", self.handle_transfer))

        return self.sub_page("Chuyển tiền", content)

    def handle_transfer(self):
        stk = self.trans_stk.text().strip()
        amount = parse_amount(self.trans_amt.text())
        if not stk or amount <= 0:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập đầy đủ STK và số tiền hợp lệ.")
            return
        QMessageBox.information(
            self, "Chưa tích hợp chuyển tiền",
            "Chức năng chuyển tiền chưa được kết nối với database; số dư và lịch sử không thay đổi."
        )

    def build_history_screen(self):
        def content(layout):
            layout.setContentsMargins(24, 14, 24, 14)
            self.history_layout = layout
            add_rows(layout, [])

        return self.sub_page("Lịch sử giao dịch", content)


# =====================================================================
# 7. CHẠY APP
# =====================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    load_fonts()                       # phải gọi sau khi có QApplication
    app.setFont(QFont(Fonts.regular, 11))
    window = EWalletMobileApp()
    window.show()
    sys.exit(app.exec())
