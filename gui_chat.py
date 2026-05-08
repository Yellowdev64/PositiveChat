import sys
import socket
import threading
import sqlite3
import json
import random
import os
import io
import re
import shutil
import base64
from pathlib import Path
from nacl.public import PrivateKey, PublicKey, Box

from PySide6.QtWidgets import (QApplication, QMainWindow, QStackedWidget,
                               QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QLineEdit, QListWidget, QListWidgetItem,
                               QScrollArea, QDialog, QCheckBox, QMessageBox, QFileDialog)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QPixmap
import qrcode
from PIL import Image as PILImage

# 🎨 THEME
DARK_THEME = """
QMainWindow, QWidget { background-color: #121212; color: #e0e0e0; }
QLabel { font-family: 'Segoe UI', 'Ubuntu', 'Roboto', sans-serif; }
QLineEdit { background-color: #1e1e1e; border: 1px solid #333; border-radius: 8px; padding: 8px; color: #fff; }
QPushButton { background-color: #0d8a4a; border-radius: 8px; padding: 8px 14px; color: white; font-weight: 600; }
QPushButton:hover { background-color: #0f9c55; }
QPushButton:disabled { background-color: #333; color: #666; }
QListWidget { background-color: #181818; border: 1px solid #2a2a2a; border-radius: 8px; padding: 4px; }
QScrollArea { border: none; background-color: #121212; }
QWidget#chatContainer { background-color: #121212; }
"""

# 📦 CORE SETUP
PROJECT_DIR = Path(__file__).parent.resolve()
PROFILE_PATH = PROJECT_DIR / "user_profile.json"
DB_PATH = PROJECT_DIR / "chat_data.db"
KEY_PATH = PROJECT_DIR / "chat_key.bin"
AVATAR_DIR = PROJECT_DIR / "avatars"
DOWNLOADS_DIR = PROJECT_DIR / "downloads"
PORT = 5555
box = None
db = None
my_private_key = None
my_public_key = None
session_box = None  # ✅ Set safely in Main Thread

AVATAR_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR.mkdir(exist_ok=True)


def initialize_app():
    global box, db, my_private_key, my_public_key
    if not KEY_PATH.exists():
        my_private_key = PrivateKey.generate()
        KEY_PATH.write_bytes(bytes(my_private_key))
    else:
        my_private_key = PrivateKey(KEY_PATH.read_bytes())
    my_public_key = my_private_key.public_key

    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT, placeholder TEXT,
        ciphertext TEXT, nonce TEXT
    )""")
    db.commit()


def get_profile():
    if PROFILE_PATH.exists():
        return json.loads(PROFILE_PATH.read_text())
    return None


def save_profile(name, avatar_path=None):
    alias = f"{random.choice(['calm', 'bright', 'swift', 'nova'])}-{random.randint(1000, 9999)}"
    profile = {"name": name, "alias": alias}
    old = get_profile()
    if avatar_path:
        profile["avatar"] = avatar_path
    elif old and "avatar" in old:
        profile["avatar"] = old["avatar"]
    PROFILE_PATH.write_text(json.dumps(profile))
    return profile


# 🤖 AI PLACEHOLDER
try:
    from placeholder_ai import generate_placeholder
except ImportError:
    def generate_placeholder(msg, use_ai=False, name="friend"):
        return random.choice(["✨ You're amazing!", "🌟 Great vibes!", "💫 Hope you're well!"])


def prepare_outgoing(text, use_ai=False, sender_name="You"):
    global session_box
    if session_box is None:
        raise Exception("Session not ready")

    nonce = os.urandom(24)
    # ✅ Fixed: Convert Ciphertext to bytes BEFORE hex encoding
    ct_bytes = bytes(session_box.encrypt(text.encode(), nonce))
    placeholder = generate_placeholder(text, use_ai=use_ai)

    db.execute("INSERT INTO messages (sender, placeholder, ciphertext, nonce) VALUES (?, ?, ?, ?)",
               (sender_name, placeholder, ct_bytes.hex(), nonce.hex()))
    db.commit()
    return f"{sender_name}|{placeholder}|{nonce.hex()}|{ct_bytes.hex()}"


# 🌐 NETWORK HANDLER
class NetworkHandler(QObject):
    msg_received = Signal(str)
    file_received = Signal(str, bytes)
    status_update = Signal(str)
    secure_session_ready = Signal(bytes)
    conn = None
    sock = None

    def start(self, mode, ip="127.0.0.1"):
        def run():
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if mode == "host":
                    self.sock.bind(("0.0.0.0", PORT))
                    self.sock.listen(1)
                    self.status_update.emit("🟢 Listening...")
                    self.conn, _ = self.sock.accept()
                    self.sock.close()
                else:
                    self.status_update.emit("🔵 Connecting...")
                    self.sock.connect((ip, PORT))
                    self.conn = self.sock

                self.status_update.emit("✅ Connected! Exchanging keys...")
                # Send our public key immediately
                self.conn.sendall((f"PUBKEY|{base64.b64encode(bytes(my_public_key)).decode()}\n").encode())

                buffer = b""
                while True:
                    chunk = self.conn.recv(4096)
                    if not chunk: break
                    buffer += chunk

                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        line = line.decode("utf-8", errors="ignore").strip()

                        if line.startswith("PUBKEY|"):
                            peer_b64 = line.split("|")[1]
                            peer_pub_bytes = base64.b64decode(peer_b64)
                            self.status_update.emit("🔑 Session established!")
                            self.secure_session_ready.emit(peer_pub_bytes)
                        elif line.startswith("FILE|"):
                            _, filename, size_str = line.split("|")
                            size = int(size_str)
                            while len(buffer) < size:
                                c = self.conn.recv(4096)
                                if not c: raise ConnectionError("Lost during transfer")
                                buffer += c
                            file_data = buffer[:size]
                            buffer = buffer[size:]
                            self.file_received.emit(filename, file_data)
                        elif line.startswith("MSG|"):
                            self.msg_received.emit(line[4:])
                        elif line:
                            self.msg_received.emit(line)
            except Exception as e:
                self.status_update.emit(f"❌ {e}")
            finally:
                try:
                    if self.conn: self.conn.close()
                    if self.sock: self.sock.close()
                except:
                    pass
                self.conn = None
                self.sock = None
                self.status_update.emit("🔴 Disconnected")

        threading.Thread(target=run, daemon=True).start()

    def send_line(self, text):
        if self.conn:
            try:
                self.conn.sendall((f"MSG|{text}\n").encode())
            except:
                pass

    def send_file(self, filepath):
        if not self.conn: return False
        try:
            filename = Path(filepath).name
            with open(filepath, 'rb') as f:
                data = f.read()
            header = f"FILE|{filename}|{len(data)}\n"
            self.conn.sendall(header.encode())
            self.conn.sendall(data)
            return True
        except Exception as e:
            self.status_update.emit(f"❌ File send failed: {e}")
            return False

    def disconnect(self):
        global session_box
        session_box = None
        try:
            if self.conn: self.conn.close()
            if self.sock: self.sock.close()
        except:
            pass


# 💬 MESSAGE BUBBLE (Text)
class MessageBubble(QWidget):
    def __init__(self, text, is_sent=False, decrypt_data=None):
        super().__init__()
        self.is_decrypted = False
        self.decrypt_data = decrypt_data
        if ": " in text:
            self.prefix, self.content = text.split(": ", 1)
            self.prefix += ": "
        else:
            self.prefix, self.content = "", text

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(6)

        self.lbl = QLabel(text)
        self.lbl.setWordWrap(True)
        self.lbl.setMinimumWidth(60)

        if decrypt_data:
            self.btn = QPushButton("Decrypt")
            self.btn.setFixedWidth(80)
            self.btn.clicked.connect(self._toggle)
        else:
            self.btn = None

        base = "background-color: #2a2a2a; color: #e0e0e0; padding: 10px 12px; border-radius: 14px; max-width: 280px;"
        if is_sent:
            lay.addStretch()
            lay.addWidget(self.lbl)
            if self.btn: lay.addWidget(self.btn)
            self.lbl.setStyleSheet(base.replace("#2a2a2a", "#0d8a4a"))
        else:
            lay.addWidget(self.lbl)
            if self.btn: lay.addWidget(self.btn)
            lay.addStretch()
            self.lbl.setStyleSheet(base)

    def _toggle(self):
        if not self.decrypt_data or session_box is None:
            return
        if self.is_decrypted:
            self.lbl.setText(self.prefix + self.content)
            self.btn.setText("Decrypt")
            self.is_decrypted = False
        else:
            try:
                nonce = bytes.fromhex(self.decrypt_data[0])
                ct = bytes.fromhex(self.decrypt_data[1])
                plain = session_box.decrypt(ct, nonce).decode()
                self.lbl.setText(self.prefix + "🔓 " + plain)
                self.btn.setText("Encrypt")
                self.is_decrypted = True
            except Exception as e:
                self.lbl.setText(self.prefix + "❌ Failed")
                self.btn.setEnabled(False)


# 📎 FILE BUBBLE
class FileBubble(QWidget):
    def __init__(self, filename, filesize, is_sent, save_callback=None):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(8)

        icon = QLabel("📎")
        icon.setStyleSheet("font-size: 24px; min-width: 30px;")
        lay.addWidget(icon)

        info = QVBoxLayout()
        name_lbl = QLabel(filename)
        name_lbl.setStyleSheet("font-weight: bold;")
        size_lbl = QLabel(f"{filesize / 1024:.1f} KB")
        size_lbl.setStyleSheet("color: #888; font-size: 12px;")
        info.addWidget(name_lbl)
        info.addWidget(size_lbl)
        lay.addLayout(info)

        base = "background-color: #2a2a2a; color: #e0e0e0; padding: 10px 12px; border-radius: 14px;"

        if is_sent:
            lay.addStretch()
            self.setStyleSheet(base.replace("#2a2a2a", "#0d8a4a"))
        else:
            dl_btn = QPushButton("💾 Save")
            dl_btn.setFixedWidth(70)
            dl_btn.clicked.connect(lambda: save_callback(filename, filesize))
            lay.addWidget(dl_btn)
            lay.addStretch()
            self.setStyleSheet(base)


# 📱 QR DIALOG
class QRDialog(QDialog):
    def __init__(self, link):
        super().__init__()
        self.setWindowTitle("Scan or create QR link")
        self.setModal(True)
        self.resize(340, 380)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        link_edit = QLineEdit(link)
        link_edit.setReadOnly(True)
        lay.addWidget(link_edit)

        copy_btn = QPushButton("📋 Copy Link")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(link))
        lay.addWidget(copy_btn)

        qr = qrcode.QRCode(box_size=8, border=4)
        qr.add_data(link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        pm = QPixmap()
        pm.loadFromData(buf.read(), "PNG")

        qr_lbl = QLabel()
        qr_lbl.setPixmap(pm.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        qr_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(qr_lbl)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn)


# 👤 PROFILE DIALOG
class ProfileDialog(QDialog):
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = profile.copy()
        self.setWindowTitle("Profile! By clicking here you can add change name/picture")
        self.setModal(True)
        self.resize(320, 360)
        lay = QVBoxLayout(self)
        lay.setSpacing(14)

        self.avatar_lbl = QLabel()
        self.avatar_lbl.setAlignment(Qt.AlignCenter)
        self.avatar_lbl.setFixedSize(100, 100)
        self.avatar_lbl.setStyleSheet("background-color: #2a2a2a; border-radius: 50px; color: #888;")
        self._refresh_avatar()
        lay.addWidget(self.avatar_lbl)

        self.change_btn = QPushButton("🖼️ Change Picture")
        self.change_btn.clicked.connect(self._select_avatar)
        lay.addWidget(self.change_btn)

        lay.addWidget(QLabel("Display Name:"))
        self.name_input = QLineEdit(self.profile.get("name", ""))
        self.name_input.setPlaceholderText("Enter display name")
        lay.addWidget(self.name_input)

        self.save_btn = QPushButton("💾 Save & Close")
        self.save_btn.clicked.connect(self.accept)
        lay.addWidget(self.save_btn)

    def _refresh_avatar(self):
        path = self.profile.get("avatar")
        if path and Path(path).exists():
            pm = QPixmap(str(path)).scaled(90, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.avatar_lbl.setPixmap(pm)
        else:
            self.avatar_lbl.setText("👤")

    def _select_avatar(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Profile Picture", str(AVATAR_DIR),
                                                   "Images (*.png *.jpg *.jpeg)")
        if file_path:
            dest = AVATAR_DIR / "current_avatar.png"
            shutil.copy(file_path, dest)
            self.profile["avatar"] = str(dest)
            self._refresh_avatar()

    def get_updated_profile(self):
        self.profile["name"] = self.name_input.text().strip() or self.profile.get("name", "User")
        return self.profile


# 🖥️ SCREEN 1: WELCOME
class WelcomeScreen(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(16)

        title = QLabel("Ready to dive to the world of positivity?")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        lay.addWidget(title)

        self.login_btn = QPushButton("Log In")
        self.reg_btn = QPushButton("Register")
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.login_btn)
        btn_layout.addWidget(self.reg_btn)
        lay.addLayout(btn_layout)

        self.reg_input = QLineEdit()
        self.reg_input.setPlaceholderText("Enter your display name")
        self.reg_input.hide()
        lay.addWidget(self.reg_input)

        self.save_btn = QPushButton("Save Profile")
        self.save_btn.hide()
        lay.addWidget(self.save_btn)


# 🖥️ SCREEN 2: LOBBY (Matches PDF Exactly)
class LobbyScreen(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(12)

        # Profile Button
        self.profile_btn = QPushButton("Profile! By clicking here you can add change name/picture")
        self.profile_btn.setStyleSheet("QPushButton { text-align: left; padding: 8px; }")
        lay.addWidget(self.profile_btn)

        # Avatar
        self.avatar_lbl = QLabel("👤")
        self.avatar_lbl.setFixedSize(30, 30)
        self.avatar_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.avatar_lbl)

        # Status
        self.status_lbl = QLabel("Status: Offline")
        self.status_lbl.setStyleSheet("color: #888;")
        lay.addWidget(self.status_lbl)

        # User List
        self.user_list = QListWidget()
        self.user_list.setFixedHeight(100)
        self.user_list.addItem(QListWidgetItem("No active connections"))
        lay.addWidget(self.user_list)

        # QR Button
        self.qr_btn = QPushButton("Scan or create QR link")
        lay.addWidget(self.qr_btn)

        # Create Link Button
        self.host_btn = QPushButton("Create a one time link")
        lay.addWidget(self.host_btn)

        # ✅ ALWAYS VISIBLE: Link Input
        self.join_input = QLineEdit()
        self.join_input.setPlaceholderText("Create or add one time link")
        lay.addWidget(self.join_input)

        # Join Button
        self.join_btn = QPushButton("Join")
        lay.addWidget(self.join_btn)

        # Group Chat
        self.group_btn = QPushButton("Create a group chat option")
        self.group_btn.setEnabled(False)
        lay.addWidget(self.group_btn)

    def update_avatar(self, profile):
        path = profile.get("avatar")
        if path and Path(path).exists():
            pm = QPixmap(str(path)).scaled(26, 26, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.avatar_lbl.setPixmap(pm)
        else:
            self.avatar_lbl.setText("👤")

    def show_qr_stub(self):
        ip = "127.0.0.1"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
        except:
            pass
        link = f"positivechat://{ip}:{PORT}/{random.randint(1000, 9999)}"
        QRDialog(link).exec()


# 🖥️ SCREEN 3: CHAT
class ChatScreen(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)

        # Header
        header = QHBoxLayout()
        self.back_btn = QPushButton("← Back")
        self.header_name = QLabel("Profile of the user Chat")
        self.header_name.setFont(QFont("Segoe UI", 14, QFont.Bold))
        header.addWidget(self.back_btn)
        header.addStretch()
        header.addWidget(self.header_name)
        header.addStretch()
        lay.addLayout(header)

        # Chat Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_cont = QWidget(objectName="chatContainer")
        self.chat_lay = QVBoxLayout(self.chat_cont)
        self.chat_lay.setContentsMargins(4, 4, 4, 4)
        self.chat_lay.setSpacing(8)
        self.chat_lay.addStretch()
        self.scroll.setWidget(self.chat_cont)
        lay.addWidget(self.scroll)

        # Input Row
        input_row = QHBoxLayout()
        self.attach_btn = QPushButton("📎")
        self.attach_btn.setFixedWidth(36)
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Type here or attach file send")
        self.input_box.setEnabled(False)
        self.ai_cb = QCheckBox("AI option")
        self.send_btn = QPushButton("Send")
        self.send_btn.setEnabled(False)
        input_row.addWidget(self.attach_btn)
        input_row.addWidget(self.input_box)
        input_row.addWidget(self.ai_cb)
        input_row.addWidget(self.send_btn)
        lay.addLayout(input_row)

    def add_file_bubble(self, filename, filesize, is_sent, save_callback=None):
        bubble = FileBubble(filename, filesize, is_sent, save_callback)
        self.chat_lay.insertWidget(self.chat_lay.count() - 1, bubble)
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))


# 🚀 MAIN APP
class PositiveChatApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PositiveChat")
        self.resize(520, 720)
        self.setStyleSheet(DARK_THEME)

        self.profile = None
        self.net = NetworkHandler()
        self.net.msg_received.connect(self.show_incoming)
        self.net.file_received.connect(self.handle_file_received)
        self.net.status_update.connect(self.update_status)
        self.net.secure_session_ready.connect(self._on_session_ready)

        self.stacked = QStackedWidget()
        self.welcome = WelcomeScreen()
        self.lobby = LobbyScreen()
        self.chat = ChatScreen()

        self.stacked.addWidget(self.welcome)
        self.stacked.addWidget(self.lobby)
        self.stacked.addWidget(self.chat)
        self.setCentralWidget(self.stacked)

        self.connect_signals()
        self.check_first_run()

    def connect_signals(self):
        self.welcome.login_btn.clicked.connect(self.handle_login)
        self.welcome.reg_btn.clicked.connect(self.show_register_input)
        self.welcome.save_btn.clicked.connect(self.handle_register)
        self.welcome.reg_input.returnPressed.connect(self.handle_register)

        self.lobby.profile_btn.clicked.connect(self.open_profile_dialog)
        self.lobby.host_btn.clicked.connect(self.handle_host)
        self.lobby.join_btn.clicked.connect(self.handle_join)
        self.lobby.qr_btn.clicked.connect(self.lobby.show_qr_stub)

        self.chat.back_btn.clicked.connect(self.return_to_lobby)
        self.chat.send_btn.clicked.connect(self.send_message)
        self.chat.input_box.returnPressed.connect(self.send_message)
        self.chat.attach_btn.clicked.connect(self.handle_attachment)

    def check_first_run(self):
        p = get_profile()
        if p:
            self.profile = p
            initialize_app()
            self.lobby.update_avatar(self.profile)
            self.stacked.setCurrentWidget(self.lobby)
        else:
            self.stacked.setCurrentWidget(self.welcome)

    def handle_login(self):
        p = get_profile()
        if p:
            self.profile = p
            initialize_app()
            self.lobby.update_avatar(self.profile)
            self.stacked.setCurrentWidget(self.lobby)
        else:
            QMessageBox.information(self, "No Profile", "Please register first.")

    def show_register_input(self):
        self.welcome.reg_btn.hide()
        self.welcome.login_btn.hide()
        self.welcome.reg_input.show()
        self.welcome.save_btn.show()
        self.welcome.reg_input.setFocus()

    def handle_register(self):
        name = self.welcome.reg_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter a display name.")
            return
        self.profile = save_profile(name)
        initialize_app()
        self.lobby.update_avatar(self.profile)
        self.stacked.setCurrentWidget(self.lobby)
        self.welcome.reg_input.clear()
        self.welcome.reg_input.hide()
        self.welcome.save_btn.hide()
        self.welcome.reg_btn.show()
        self.welcome.login_btn.show()

    def open_profile_dialog(self):
        dlg = ProfileDialog(self.profile, self)
        if dlg.exec():
            self.profile = dlg.get_updated_profile()
            PROFILE_PATH.write_text(json.dumps(self.profile))
            self.lobby.update_avatar(self.profile)

    def handle_attachment(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Attach File", str(PROJECT_DIR), "All Files (*)")
        if file_path:
            if self.net.send_file(file_path):
                filename = Path(file_path).name
                filesize = Path(file_path).stat().st_size
                self.chat.add_file_bubble(filename, filesize, is_sent=True)
            else:
                QMessageBox.warning(self, "Send Failed", "Not connected")

    def handle_host(self):
        self.lobby.host_btn.setText("🟢 Listening...")
        self.lobby.host_btn.setEnabled(False)
        self.net.start("host")
        ip = "127.0.0.1"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
        except:
            pass
        session = ''.join(random.choices("abcdef0123456789", k=6))
        link = f"positivechat://{ip}:{PORT}/{session}"
        QRDialog(link).exec()
        self.lobby.host_btn.setText("Create a one time link")
        self.lobby.host_btn.setEnabled(True)

    def handle_join(self):
        raw = self.lobby.join_input.text().strip()
        match = re.match(r"positivechat://([\d.]+):(\d+)/?", raw)
        if not match:
            QMessageBox.warning(self, "Invalid Link", "Paste valid link like: positivechat://192.168.1.5:5555/abc123")
            return
        ip, port = match.group(1), int(match.group(2))
        if port != PORT:
            QMessageBox.warning(self, "Port Mismatch", f"App uses port {PORT}")
            return
        self.lobby.join_input.clear()
        self.lobby.host_btn.setEnabled(False)
        self.lobby.join_btn.setEnabled(False)
        self.net.start("client", ip)

    def update_status(self, txt):
        self.lobby.status_lbl.setText(f"Status: {txt}")
        if "Disconnected" in txt or "❌" in txt:
            self.lobby.user_list.clear()
            self.lobby.user_list.addItem(QListWidgetItem("No active connections"))
            self.lobby.host_btn.setEnabled(True)
            self.lobby.join_btn.setEnabled(True)

    def _on_session_ready(self, peer_pubkey_bytes):
        global session_box
        try:
            peer_pub = PublicKey(peer_pubkey_bytes)
            session_box = Box(my_private_key, peer_pub)
            self.switch_to_chat()
        except Exception as e:
            self.lobby.status_lbl.setText(f"❌ Key exchange failed: {e}")
            self.net.disconnect()

    def switch_to_chat(self):
        self.lobby.user_list.clear()
        self.lobby.user_list.addItem(QListWidgetItem("🟢 Active Peer"))
        self.stacked.setCurrentWidget(self.chat)
        self.chat.header_name.setText(f"Profile of the user Chat: {self.profile['name']}")
        self.chat.input_box.setEnabled(True)
        self.chat.send_btn.setEnabled(True)
        self.chat.attach_btn.setEnabled(True)
        self.chat.input_box.setFocus()

    def _send_chat_text(self, txt):
        try:
            use_ai = self.chat.ai_cb.isChecked()
            payload = prepare_outgoing(txt, use_ai=use_ai, sender_name=self.profile["name"])
            self.net.send_line(payload)
            parts = payload.split("|", 3)
            ph, nonce, ct = parts[1], parts[2], parts[3]
            self.add_bubble(f"📤 {self.profile['name']}: {ph}", True, (nonce, ct))
            self.chat.input_box.clear()
        except Exception as e:
            self.add_bubble(f"❌ Error: {e}", True)

    def send_message(self):
        txt = self.chat.input_box.text().strip()
        if txt: self._send_chat_text(txt)

    def handle_file_received(self, filename, data):
        save_path = DOWNLOADS_DIR / filename
        with open(save_path, 'wb') as f: f.write(data)
        filesize = len(data)
        self.chat.add_file_bubble(filename, filesize, is_sent=False,
                                  save_callback=lambda n, s: self.save_received_file(n, data))
        self.add_bubble(f"📩 Received file: {filename}", False)

    def save_received_file(self, filename, data):
        save_path, _ = QFileDialog.getSaveFileName(self, "Save File", str(DOWNLOADS_DIR / filename), "All Files (*)")
        if save_path:
            with open(save_path, 'wb') as f: f.write(data)
            QMessageBox.information(self, "Saved", f"File saved to:\n{save_path}")

    def show_incoming(self, raw):
        try:
            sender, ph, nonce, ct = raw.split("|", 3)
            self.chat.header_name.setText(f"Profile of the user Chat: {sender}")
            self.add_bubble(f"📩 {sender}: {ph}", False, (nonce, ct))
        except:
            self.add_bubble(f"📩 Raw: {raw}", False)

    def add_bubble(self, text, is_sent, decrypt_data=None):
        bubble = MessageBubble(text, is_sent, decrypt_data)
        self.chat.chat_lay.insertWidget(self.chat.chat_lay.count() - 1, bubble)
        QTimer.singleShot(0, lambda: self.chat.scroll.verticalScrollBar().setValue(
            self.chat.scroll.verticalScrollBar().maximum()))

    def return_to_lobby(self):
        self.net.disconnect()
        self.chat.input_box.clear()
        self.chat.input_box.setEnabled(False)
        self.chat.send_btn.setEnabled(False)
        self.chat.attach_btn.setEnabled(False)
        self.stacked.setCurrentWidget(self.lobby)
        self.lobby.host_btn.setEnabled(True)
        self.lobby.join_btn.setEnabled(True)
        self.lobby.host_btn.setText("Create a one time link")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PositiveChatApp()
    win.show()
    sys.exit(app.exec())