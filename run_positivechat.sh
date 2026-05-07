#!/bin/bash
# run_positivechat.sh - One-click launcher for PositiveChat

# Get the directory where this script lives
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Create a virtual environment if it doesn't exist
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    echo "📦 Setting up Python environment..."
    python3 -m venv "$SCRIPT_DIR/venv"
    "$SCRIPT_DIR/venv/bin/pip" install --quiet pynacl pyside6 "qrcode[pil]"
fi

# Activate and run
source "$SCRIPT_DIR/venv/bin/activate"
python3 "$SCRIPT_DIR/gui_chat.py"