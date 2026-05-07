import os
import sys
import json
import random
import string
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QMessageBox)
from PySide6.QtCore import Qt

# 📁 Absolute paths (always points to script's folder)
PROJECT_DIR = Path(__file__).parent.resolve()
KEY_PATH = PROJECT_DIR / "chat_key.bin"
PROFILE_PATH = PROJECT_DIR / "user_profile.json"


class SetupScreen(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Welcome to PositiveChat")
        self.setModal(True)
        self.resize(380, 320)
        self.setStyleSheet("""
            QDialog { background-color: #121212; }
            QLabel { color: #e0e0e0; font-size: 14px; }
            QLineEdit { background-color: #1e1e1e; border: 1px solid #333; 
                        border-radius: 8px; padding: 8px; color: #fff; }
            QPushButton { background-color: #0d8a4a; color: white; 
                          border-radius: 8px; padding: 8px 16px; font-weight: 600; }
            QPushButton:hover { background-color: #0f9c55; }
        """)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        layout.addWidget(QLabel("✨ Welcome to PositiveChat"))
        layout.addWidget(QLabel("Choose a display name. Your encryption key will be created automatically."))

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., Alex, Luna, Dev")
        layout.addWidget(self.name_input)

        self.alias_lbl = QLabel("Your unique ID will appear here...")
        self.alias_lbl.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(self.alias_lbl)

        btn_layout = QHBoxLayout()
        self.create_btn = QPushButton("Create Profile")
        self.import_btn = QPushButton("Import Backup")
        btn_layout.addWidget(self.import_btn)
        btn_layout.addWidget(self.create_btn)
        layout.addLayout(btn_layout)

        self.create_btn.clicked.connect(self.create_profile)
        self.import_btn.clicked.connect(self.import_backup)

    def generate_alias(self):
        words = ["calm", "swift", "bright", "quiet", "bold", "clear", "gentle", "steady"]
        return f"{random.choice(words)}-{random.choice(words)}-{''.join(random.choices(string.hexdigits.lower()[:16], k=4))}"

    def create_profile(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter a display name.")
            return

        if not KEY_PATH.exists():
            KEY_PATH.write_bytes(os.urandom(32))

        alias = self.generate_alias()
        profile = {"name": name, "alias": alias, "created_at": str(KEY_PATH.stat().st_mtime)}
        PROFILE_PATH.write_text(json.dumps(profile, indent=2))

        self.accept()

    def import_backup(self):
        QMessageBox.information(self, "Import Backup",
                                "Feature coming soon. Copy your `chat_key.bin` to the app folder.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dlg = SetupScreen()
    if dlg.exec():
        print("✅ Profile created successfully.")
    else:
        print("❌ Setup cancelled.")