import os
import json
import time
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFormLayout, QGroupBox, QScrollArea, QWidget,
    QMessageBox, QFrame, QSpinBox, QFileDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon

# ── Constants ────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

DEFAULT_SETTINGS = {
    "cameras": [
        {
            "id": 1,
            "name": "Camera 1",
            "url": "rtsp://admin:rtc%402025@192.168.5.110:554/Streaming/Channels/101",
            "model": "",
            "enabled": True
        }
    ],
    "websocket": {
        "host": "0.0.0.0",
        "port": 8765
    }
}

# ── Style Sheet ───────────────────────────────────────────────────────────────
DIALOG_STYLE = """
QDialog {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
QLabel {
    color: #cdd6f4;
    font-size: 13px;
}
QGroupBox {
    color: #89b4fa;
    border: 1px solid #45475a;
    border-radius: 8px;
    margin-top: 12px;
    padding: 10px;
    font-size: 13px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px 0 6px;
    color: #89b4fa;
}
QLineEdit {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    color: #cdd6f4;
    padding: 6px 10px;
    font-size: 13px;
    selection-background-color: #89b4fa;
}
QLineEdit:focus {
    border: 1px solid #89b4fa;
}
QLineEdit:disabled {
    background-color: #11111b;
    color: #585b70;
}
QSpinBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    color: #cdd6f4;
    padding: 4px 8px;
    font-size: 13px;
}
QSpinBox:focus {
    border: 1px solid #89b4fa;
}
QPushButton {
    border-radius: 6px;
    padding: 7px 16px;
    font-size: 13px;
    font-weight: bold;
    color: #11111b;
}
QPushButton#btn_add {
    background-color: #a6e3a1;
}
QPushButton#btn_add:hover {
    background-color: #b5f0b0;
}
QPushButton#btn_remove {
    background-color: #f38ba8;
    color: #11111b;
}
QPushButton#btn_remove:hover {
    background-color: #f5a8bd;
}
QPushButton#btn_save {
    background-color: #89b4fa;
}
QPushButton#btn_save:hover {
    background-color: #a0c4fc;
}
QPushButton#btn_cancel {
    background-color: #45475a;
    color: #cdd6f4;
}
QPushButton#btn_cancel:hover {
    background-color: #585b70;
}
QPushButton#btn_browse {
    background-color: #74c7ec;
    color: #11111b;
}
QPushButton#btn_browse:hover {
    background-color: #89dceb;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollBar:vertical {
    background: #1e1e2e;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #89b4fa;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


def load_settings():
    """Load settings from file, creating defaults if missing."""
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Merge with defaults to handle missing keys
        if "cameras" not in data:
            data["cameras"] = DEFAULT_SETTINGS["cameras"]
        if "websocket" not in data:
            data["websocket"] = DEFAULT_SETTINGS["websocket"]
        return data
    except Exception as e:
        print(f"[Settings] Load error: {e}. Using defaults.")
        return DEFAULT_SETTINGS.copy()


def save_settings(data: dict):
    """Persist settings to disk."""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"[Settings] Saved to {SETTINGS_FILE}")
        return True
    except Exception as e:
        print(f"[Settings] Save error: {e}")
        return False


# ── Camera Row Widget ─────────────────────────────────────────────────────────
class CameraRow(QWidget):
    """A single camera entry row inside the settings dialog."""

    def __init__(self, cam_data: dict, parent=None):
        super().__init__(parent)
        self.cam_data = cam_data
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── Group Box ─────────────────────────────────────────────────────────
        self.group = QGroupBox()
        self.group.setTitle(f"📷  {self.cam_data.get('name', 'Camera')}")
        group_layout = QFormLayout(self.group)
        group_layout.setSpacing(8)
        group_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # Camera Name
        self.edit_name = QLineEdit(self.cam_data.get("name", ""))
        self.edit_name.setPlaceholderText("e.g. Entrance Cam")
        self.edit_name.textChanged.connect(
            lambda t: self.group.setTitle(f"📷  {t}" if t else "📷  Camera")
        )
        group_layout.addRow("Name:", self.edit_name)

        # URL
        self.edit_url = QLineEdit(self.cam_data.get("url", ""))
        self.edit_url.setPlaceholderText(
            "rtsp://user:pass@192.168.x.x:554/... or 0 for webcam"
        )
        self.edit_url.setMinimumWidth(380)
        group_layout.addRow("URL / Source:", self.edit_url)

        # AI Model
        model_layout = QHBoxLayout()
        self.edit_model = QLineEdit(self.cam_data.get("model", ""))
        self.edit_model.setPlaceholderText("e.g. best.pt or /path/to/model.pt (optional)")
        self.edit_model.setMinimumWidth(380)
        model_layout.addWidget(self.edit_model)
        
        self.btn_browse = QPushButton("📂 Browse")
        self.btn_browse.setObjectName("btn_browse")
        self.btn_browse.setFixedHeight(30)
        self.btn_browse.setFixedWidth(90)
        self.btn_browse.clicked.connect(self._browse_model)
        model_layout.addWidget(self.btn_browse)
        
        group_layout.addRow("AI Model (.pt):", model_layout)

        # Remove button
        self.btn_remove = QPushButton("🗑 Remove")
        self.btn_remove.setObjectName("btn_remove")
        self.btn_remove.setFixedHeight(30)
        # Caller wires this up via remove_requested signal
        self.btn_remove.clicked.connect(self._on_remove)
        group_layout.addRow("", self.btn_remove)

        layout.addWidget(self.group)



    def _browse_model(self):
        """Browse for a .pt model file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select AI Model (.pt file)",
            "",
            "PyTorch Models (*.pt);;All Files (*)"
        )
        if file_path:
            self.edit_model.setText(file_path)

    def _on_remove(self):
        # Let the parent dialog handle the removal
        dialog = self.parent()
        while dialog and not isinstance(dialog, SettingsDialog):
            dialog = dialog.parent()
        if dialog:
            dialog.remove_camera_row(self)

    def get_data(self) -> dict:
        """Return the current values as a dict."""
        return {
            "id": self.cam_data.get("id", 1),
            "name": self.edit_name.text().strip() or "Camera",
            "url": self.edit_url.text().strip(),
            "model": self.edit_model.text().strip(),
            "enabled": True
        }


# ── Settings Dialog ───────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    """
    Modal settings dialog.
    Opens from the main window, lets user edit camera URLs, then
    emits the new settings via the `accepted` signal path.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙  Camera Settings")
        self.setMinimumSize(600, 480)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._settings = load_settings()
        self._camera_rows: list[CameraRow] = []
        self._build_ui()
        self._populate_cameras()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # Title
        title = QLabel("System Settings")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet("color: #89b4fa; margin-bottom: 4px;")
        root.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #45475a;")
        root.addWidget(sep)

        # ── Cameras Section ───────────────────────────────────────────────────
        cam_header_row = QHBoxLayout()
        cam_lbl = QLabel("📹  Camera Sources")
        cam_lbl.setFont(QFont("Arial", 12, QFont.Bold))
        cam_lbl.setStyleSheet("color: #cba6f7;")
        cam_header_row.addWidget(cam_lbl)
        cam_header_row.addStretch()

        self.btn_add = QPushButton("➕ Add Camera")
        self.btn_add.setObjectName("btn_add")
        self.btn_add.setFixedHeight(32)
        self.btn_add.clicked.connect(self._add_camera)
        cam_header_row.addWidget(self.btn_add)
        root.addLayout(cam_header_row)

        # Scroll area for camera rows
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(260)
        self.cam_container = QWidget()
        self.cam_layout = QVBoxLayout(self.cam_container)
        self.cam_layout.setContentsMargins(0, 0, 8, 0)
        self.cam_layout.setSpacing(6)
        self.cam_layout.addStretch()
        self.scroll.setWidget(self.cam_container)
        root.addWidget(self.scroll, stretch=1)

        # ── WebSocket Section ─────────────────────────────────────────────────
        ws_group = QGroupBox("🔌  WebSocket Server")
        ws_layout = QFormLayout(ws_group)
        ws_layout.setSpacing(8)
        ws_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        ws_cfg = self._settings.get("websocket", DEFAULT_SETTINGS["websocket"])
        self.edit_ws_host = QLineEdit(ws_cfg.get("host", "0.0.0.0"))
        self.edit_ws_host.setPlaceholderText("0.0.0.0 (all interfaces)")
        ws_layout.addRow("Host:", self.edit_ws_host)

        self.spin_ws_port = QSpinBox()
        self.spin_ws_port.setRange(1024, 65535)
        self.spin_ws_port.setValue(int(ws_cfg.get("port", 8765)))
        ws_layout.addRow("Port:", self.spin_ws_port)

        root.addWidget(ws_group)

        # ── Bottom Buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.setFixedHeight(36)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton("💾  Save & Apply")
        self.btn_save.setObjectName("btn_save")
        self.btn_save.setFixedHeight(36)
        self.btn_save.clicked.connect(self._save_and_accept)

        btn_row.addStretch()
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_save)
        root.addLayout(btn_row)

    def _populate_cameras(self):
        for cam in self._settings.get("cameras", []):
            self._add_camera(cam)

    def _add_camera(self, cam_data=None):
        """Add a new camera row. cam_data is pre-filled if editing existing."""
        if cam_data is None or not isinstance(cam_data, dict):
            # Generate next ID
            existing_ids = [r.cam_data.get("id", 0) for r in self._camera_rows]
            next_id = max(existing_ids, default=0) + 1
            cam_data = {
                "id": next_id,
                "name": f"Camera {next_id}",
                "url": "",
                "model": "",
                "enabled": True
            }

        row = CameraRow(cam_data, parent=self.cam_container)
        self._camera_rows.append(row)
        # Insert before the trailing stretch
        idx = self.cam_layout.count() - 1
        self.cam_layout.insertWidget(idx, row)

    def remove_camera_row(self, row: CameraRow):
        if len(self._camera_rows) <= 1:
            QMessageBox.warning(self, "Remove Camera",
                                "You must keep at least one camera configured.")
            return
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Remove Camera")
        msg_box.setText(f"Remove '{row.get_data().get('name', 'Camera')}'?")
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.resize(450, 200)  # Make the dialog bigger
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #0f0f0f;
                color: white;
                font-family: Arial;
                font-size: 16px;
                font-weight: normal;
            }
            QMessageBox QLabel {
                color: white;
                font-family: Arial;
                font-size: 16px;
                font-weight: normal;
            }
            QMessageBox QPushButton {
                background-color: #45475a;
                color: white;
                border: 2px solid #585b70;
                border-radius: 8px;
                padding: 12px 24px;
                font-family: Arial;
                font-size: 16px;
                font-weight: bold;
                min-width: 120px;
                min-height: 40px;
            }
            QMessageBox QPushButton:hover {
                background-color: #585b70;
                border: 2px solid #89b4fa;
            }
            QMessageBox QPushButton:pressed {
                background-color: #313244;
            }
            QMessageBox QPushButton[text="Confirm"] {
                background-color: #a6e3a1;
                color: #11111b;
                border: 2px solid #89b4fa;
            }
            QMessageBox QPushButton[text="Confirm"]:hover {
                background-color: #b5f0b0;
                border: 2px solid #74c7ec;
            }
        """)
        cancel_button = msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        confirm_button = msg_box.addButton("Confirm", QMessageBox.ButtonRole.AcceptRole)
        msg_box.setDefaultButton(cancel_button)
        confirm = msg_box.exec()
        if msg_box.clickedButton() == confirm_button:
            self._camera_rows.remove(row)
            self.cam_layout.removeWidget(row)
            row.deleteLater()

    def _save_and_accept(self):
        # Validate – every camera must have a URL
        for row in self._camera_rows:
            d = row.get_data()
            if not d["url"]:
                QMessageBox.warning(
                    self, "Validation Error",
                    f"Camera '{d['name']}' has an empty URL. Please fill it in."
                )
                return
            
            # Model is optional, but if provided, check if file exists (only for absolute paths)
            model_path = d["model"]
            if model_path and os.path.isabs(model_path) and not os.path.exists(model_path):
                QMessageBox.warning(
                    self, "Validation Warning",
                    f"Model file not found for camera '{d['name']}':\n{model_path}\n\n"
                    "You can still save, but detection won't work without a valid model."
                )
                # Don't return - let user save if they want

        # Build new settings
        new_settings = {
            "cameras": [r.get_data() for r in self._camera_rows],
            "websocket": {
                "host": self.edit_ws_host.text().strip() or "0.0.0.0",
                "port": self.spin_ws_port.value()
            }
        }

        if save_settings(new_settings):
            self._settings = new_settings
            self.accept()   # caller reads get_settings()
        else:
            QMessageBox.critical(self, "Error", "Failed to save settings file.")

    def get_settings(self) -> dict:
        """Returns the last saved/accepted settings."""
        return self._settings
