import sys
import socket
import threading
import sqlite3
import json
import random
import os
import io
from pathlib import Path
from nacl.secret import SecretBox

# ✅ Explicit PySide6 imports
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QPushButton, QLineEdit,
                               QComboBox, QScrollArea, QDialog, QCheckBox)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QPixmap
import qrcode

# 🎨 THEME
DARK_THEME = """
QMainWindow { background-color: #121212; }
QLabel { color: #e0e0e0; font-family: 'Segoe UI', 'Ubuntu', 'Roboto', sans-serif; }
QLineEdit {
    background-color: #1e1e1e; border: 1px solid #333; border-radius: 10px;
    padding: 10px 12px; color: #fff; font-size: 14px;
}
QPushButton {
    background-color: #0d8a4a; border-radius: 10px; padding: 8px 14px;
    color: white; font-weight: 600; font-size: 13px;
}
QPushButton:hover { background-color: #0f9c55; }
QCheckBox { color: #bbb; spacing: 6px; }
QScrollArea { border: none; background-color: #121212; }
QWidget#chatContainer { background-color: #121212; }
"""

# 📦 CORE SETUP (Absolute paths)
PROJECT_DIR = Path(__file__).parent.resolve()
PROFILE_PATH = PROJECT_DIR / "user_profile.json"
DB_PATH = PROJECT_DIR / "chat_data.db"
KEY_PATH = PROJECT_DIR / "chat_key.bin"

PORT = 5555
box = None
db = None


def initialize_app():
    """Loads encryption key and database."""
    global box, db
    if not KEY_PATH.exists():
        KEY_PATH.write_bytes(os.urandom(32))
    box = SecretBox(KEY_PATH.read_bytes())

    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.execute("""CREATE TABLE IF NOT EXISTS messages
                  (
                      id
                      INTEGER
                      PRIMARY
                      KEY
                      AUTOINCREMENT,
                      sender
                      TEXT,
                      placeholder
                      TEXT,
                      ciphertext
                      TEXT,
                      nonce
                      TEXT
                  )""")
    db.commit()


# 🤖 AI PLACEHOLDER (Safe fallback)
try:
    from placeholder_ai import generate_placeholder
except ImportError:
    def generate_placeholder(msg, use_ai=False, name="friend"):
        return random.choice(["✨ You're amazing!", "🌟 Great vibes!", "💫 Hope you're well!"])


def prepare_outgoing(text, use_ai=False, sender_name="You"):
    nonce = os.urandom(SecretBox.NONCE_SIZE)
    ct = box.encrypt(text.encode(), nonce).ciphertext
    placeholder = generate_placeholder(text, use_ai=use_ai)

    db.execute("INSERT INTO messages (sender, placeholder, ciphertext, nonce) VALUES (?, ?, ?, ?)",
               (sender_name, placeholder, ct.hex(), nonce.hex()))
    db.commit()
    return f"{sender_name}|{placeholder}|{nonce.hex()}|{ct.hex()}"


# 🌐 NETWORK HANDLER
class NetworkHandler(QObject):
    msg_received = Signal(str)
    status_update = Signal(str)
    conn = None

    def start(self, mode, ip="127.0.0.1"):
        def run():
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if mode == "host":
                    self.sock.bind(("0.0.0.0", PORT))
                    self.sock.listen(1)
                    self.status_update.emit("🟢 Waiting for connection...")
                    self.conn, _ = self.sock.accept()
                    self.sock.close()
                else:
                    self.status_update.emit("🔵 Connecting...")
                    self.sock.connect((ip, PORT))
                    self.conn = self.sock

                self.status_update.emit("✅ Connected!")
                file = self.conn.makefile('r', encoding='utf-8')
                for line in file:
                    msg = line.strip()
                    if msg:
                        self.msg_received.emit(msg)
            except Exception as e:
                self.status_update.emit(f"❌ {e}")
            finally:
                self.conn = None
                self.status_update.emit("🔴 Disconnected")

        threading.Thread(target=run, daemon=True).start()

    def send_line(self, text):
        if self.conn:
            try:
                self.conn.sendall((text + "\n").encode())
            except Exception as e:
                self.status_update.emit(f"❌ Send failed: {e}")


# 💬 MESSAGE BUBBLE WIDGET
class MessageBubble(QWidget):
    def __init__(self, text, is_sent=False, decrypt_data=None, parent=None):
        super().__init__(parent)
        self.is_decrypted = False
        self.decrypt_data = decrypt_data

        # Split "📤 Name: " or "📩 Name: " prefix from content
        if ": " in text:
            self.prefix, self.original_content = text.split(": ", 1)
            self.prefix += ": "
        else:
            self.prefix, self.original_content = "", text

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(400)

        # ✅ FIXED: Complete condition with colon
        if decrypt_data:
            self.decrypt_btn = QPushButton("Decrypt")
            self.decrypt_btn.setFixedWidth(85)
            self.decrypt_btn.clicked.connect(self._toggle_view)

        base_style = "background-color: #2a2a2a; color: #e0e0e0; padding: 10px 14px; border-radius: 14px; max-width: 320px;"

        if is_sent:
            layout.addStretch()
            layout.addWidget(self.label)
            if decrypt_data:
                layout.addWidget(self.decrypt_btn)
            self.label.setStyleSheet(base_style.replace("#2a2a2a", "#0d8a4a"))
        else:
            layout.addWidget(self.label)
            if decrypt_data:
                layout.addWidget(self.decrypt_btn)
            layout.addStretch()
            self.label.setStyleSheet(base_style)

    def _toggle_view(self):
        if not self.decrypt_data: return
        if self.is_decrypted:
            self.label.setText(self.prefix + self.original_content)
            self.decrypt_btn.setText("Decrypt")
            self.is_decrypted = False
        else:
            nonce, ct = self.decrypt_data
            try:
                plain = box.decrypt(bytes.fromhex(ct), bytes.fromhex(nonce)).decode()
                self.label.setText(self.prefix + "🔓 " + plain)
                self.decrypt_btn.setText("Encrypt")
                self.is_decrypted = True
            except Exception:
                self.label.setText(self.prefix + "❌ Failed")
                self.decrypt_btn.setEnabled(False)


# 📱 QR DIALOG
class QRDialog(QDialog):
    def __init__(self, connection_string: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Share Connection")
        self.setModal(True)
        self.resize(300, 350)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Scan this QR code to connect:"))

        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(connection_string)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue(), "PNG")

        qr_label = QLabel()
        qr_label.setPixmap(pixmap.scaled(250, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        qr_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(qr_label)

        conn_label = QLabel(f"Or type manually:\n{connection_string}")
        conn_label.setWordWrap(True)
        conn_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(conn_label)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


# 🖥️ MAIN APP
class ChatApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PositiveChat")
        self.resize(550, 650)
        self.setStyleSheet(DARK_THEME)

        # ✅ Load Profile
        if PROFILE_PATH.exists():
            profile = json.loads(PROFILE_PATH.read_text())
            self.my_name = profile.get("name", "You")
            self.my_alias = profile.get("alias", "")
        else:
            self.my_name = "You"
            self.my_alias = ""

        self.net = NetworkHandler()
        self.net.msg_received.connect(self.show_incoming)
        self.net.status_update.connect(self.update_status)

        self.init_ui()
        self.show_connect_dialog()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main = QVBoxLayout(central)
        main.setContentsMargins(10, 10, 10, 10)

        self.status_lbl = QLabel("Status: Disconnected")
        qr_btn = QPushButton("📱 Show QR")
        qr_btn.clicked.connect(self.show_qr_dialog)
        top_row = QHBoxLayout()
        top_row.addWidget(self.status_lbl)
        top_row.addStretch()
        top_row.addWidget(qr_btn)
        main.addLayout(top_row)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.chat_container = QWidget(objectName="chatContainer")
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(5, 5, 5, 5)
        self.chat_layout.setSpacing(8)
        self.chat_layout.addStretch()

        self.scroll_area.setWidget(self.chat_container)
        main.addWidget(self.scroll_area)

        input_row = QHBoxLayout()
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Type a message...")
        self.send_btn = QPushButton("Send")
        self.ai_toggle = QCheckBox("Use AI phrases")
        self.ai_toggle.setChecked(False)

        input_row.addWidget(self.input_box)
        input_row.addWidget(self.ai_toggle)
        input_row.addWidget(self.send_btn)
        main.addLayout(input_row)

        self.send_btn.clicked.connect(self.send_message)
        self.input_box.returnPressed.connect(self.send_message)
        self.input_box.setEnabled(False)
        self.send_btn.setEnabled(False)

    def show_connect_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Connect")
        lay = QVBoxLayout(dlg)
        mode = QComboBox()
        mode.addItems(["Host", "Client"])
        ip_box = QLineEdit("127.0.0.1")
        start_btn = QPushButton("Start")
        lay.addWidget(QLabel("Mode:"))
        lay.addWidget(mode)
        lay.addWidget(QLabel("Host IP (if Client):"))
        lay.addWidget(ip_box)
        lay.addWidget(start_btn)
        start_btn.clicked.connect(lambda: self.connect(mode.currentText().lower(), ip_box.text(), dlg))
        dlg.exec()

    def connect(self, mode, ip, dlg):
        dlg.close()
        self.net.start(mode, ip)

    def update_status(self, txt):
        self.status_lbl.setText(f"Status: {txt}")
        enabled = "Connected" in txt
        self.input_box.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)

    def send_message(self):
        txt = self.input_box.text().strip()
        if not txt: return
        try:
            use_ai = self.ai_toggle.isChecked()
            payload = prepare_outgoing(txt, use_ai=use_ai, sender_name=self.my_name)
            self.net.send_line(payload)

            parts = payload.split("|", 3)
            ph = parts[1]
            nonce, ct = parts[2], parts[3]
            self._add_bubble(f"📤 {self.my_name}: {ph}", is_sent=True, decrypt_data=(nonce, ct))
            self.input_box.clear()
        except Exception as e:
            self._add_bubble(f"❌ Send Error: {e}")

    def show_incoming(self, raw):
        try:
            sender_name, ph, nonce, ct = raw.split("|", 3)
            self._add_bubble(f"📩 {sender_name}: {ph}", is_sent=False, decrypt_data=(nonce, ct))
        except:
            self._add_bubble(f"📩 Raw: {raw}")

    def _add_bubble(self, text, is_sent=False, decrypt_data=None):
        bubble = MessageBubble(text, is_sent=is_sent, decrypt_data=decrypt_data)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        QTimer.singleShot(0, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))

    def show_qr_dialog(self):
        import random, string
        suffix = ''.join(random.choices(string.hexdigits.lower()[:16], k=4))
        alias = f"{socket.gethostname()[:10]}-{suffix}"
        ip = "127.0.0.1"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
        except:
            pass
        conn_str = f"positivechat://{ip}:{PORT}/{alias}"
        QRDialog(conn_str, self).exec()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    if not KEY_PATH.exists():
        from setup_screen import SetupScreen

        setup = SetupScreen()
        if setup.exec():
            initialize_app()
            window = ChatApp()
            window.show()
            sys.exit(app.exec())
        else:
            sys.exit(0)
    else:
        initialize_app()
        window = ChatApp()
        window.show()
        sys.exit(app.exec())