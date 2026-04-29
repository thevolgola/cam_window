import sys
import queue
import os
import time
import cv2
import json
import numpy as np
from PySide6.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout,
                               QHBoxLayout, QWidget, QPushButton, QFrame,
                               QMessageBox, QScrollArea, QGridLayout, QStackedWidget, QSizePolicy,
                               QStyle)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap, QFont, QPainter, QColor

from unit_manager import UnitManager
from web_socket import WebSocketModule
from settings_dialog import SettingsDialog, load_settings
from roi_dialog import ROIDialog

# Portability
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MESSAGE_BOX_STYLE = """
QMessageBox {
    background-color: #1e1e2e;
}
QMessageBox QLabel {
    color: #f5f7ff;
    font-size: 13px;
}
QMessageBox QPushButton {
    background-color: #89b4fa;
    color: #11111b;
    border: 1px solid #74c7ec;
    border-radius: 6px;
    padding: 4px 10px;
    min-width: 64px;
    min-height: 28px;
    margin: 10px 6px 12px 6px;
    font-size: 11px;
    font-weight: bold;
}
QMessageBox QPushButton:hover {
    background-color: #a0c4fc;
}
"""


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Robot Parking Control - Monitor")
        self.setMinimumSize(1100, 700)
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e2e; }
            QWidget     { background-color: #1e1e2e; color: #cdd6f4; }
            QLabel      { color: #cdd6f4; }
            QPushButton {
                border-radius: 6px;
                min-height: 28px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: bold;
                color: #11111b;
            }
        """)

        # ── State Properties ────────────────────────────────────────────────────────
        self.grid_mode = False          # True = View all cameras
        self.active_camera_id = None    # Currently focused camera ID
        self._focused_raw_frame: np.ndarray | None = None
        self._latest_raw_frames: dict[str, np.ndarray] = {}
        self.grid_video_labels = {}     # Dictionary mapping cam_id -> QLabel
        self.sidebar_expanded = True
        
        # Load global settings
        self._app_settings = load_settings()
        cameras_config = self._app_settings.get("cameras", [])
        
        if cameras_config:
            self.active_camera_id = str(cameras_config[0]["id"])

        # ── Initialize Multi-Camera Infrastructure ────────────────────────────────
        self.unit_manager = UnitManager()
        
        ws_cfg = self._app_settings.get("websocket", {})
        self.ws_server = WebSocketModule(
            host=ws_cfg.get("host", "0.0.0.0"), 
            port=ws_cfg.get("port", 8765)
        )
        self.ws_server.start()
        
        # Sync units with config
        self.unit_manager.sync_cameras(cameras_config)

        # ── Build UI ───────────────────────────────────────────────────────────────
        self.setup_ui()
        
        # ── Load ROIs ──────────────────────────────────────────────────────────────
        self.load_rois()

        # ── Start UI Refresh Timer (≈30 FPS) ───────────────────────────────────────
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(33)

    # ── UI Construction ────────────────────────────────────────────────────────

    def setup_ui(self):
        """Creates a modern layout with a sidebar and stacked video container."""
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(4, 4, 4, 4)
        self.main_layout.setSpacing(4)

        # ── LEFT: Main Display Area ────────────────────────────────────────────
        self.video_container_widget = QWidget()
        self.video_container_layout = QVBoxLayout(self.video_container_widget)
        self.video_container_layout.setContentsMargins(0, 0, 0, 0)
        self.video_container_layout.setSpacing(6)
        
        # Title bar above video
        self.cam_title = QLabel("Initializing...")
        self.cam_title.setStyleSheet("""
            font-size: 13px; font-weight: bold; color: #cdd6f4;
            background-color: #313244; padding: 3px 6px; border-radius: 3px;
        """)
        self.cam_title.setAlignment(Qt.AlignCenter)
        self.video_container_layout.addWidget(self.cam_title)

        # Stack to hold Single View vs Grid View
        self.video_stack = QStackedWidget()
        
        # Single View Label
        self.single_video_label = QLabel("Waiting for camera...")
        self.single_video_label.setAlignment(Qt.AlignCenter)
        self.single_video_label.setStyleSheet(
            "background-color: #11111b; color: #a6adc8; border: 1px solid #313244; border-radius: 3px;"
        )
        self.single_video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.single_video_label.setMinimumSize(640, 480)
        
        # Grid View Area
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setStyleSheet("QScrollArea { border: none; background-color: #11111b; }")
        
        self.grid_container = QWidget()
        self.grid_container.setStyleSheet("background-color: #11111b;")
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(1, 1, 1, 1)
        self.grid_layout.setSpacing(3)
        
        self.grid_scroll.setWidget(self.grid_container)
        
        self.video_stack.addWidget(self.single_video_label) # Index 0
        self.video_stack.addWidget(self.grid_scroll)        # Index 1

        self.video_container_layout.addWidget(self.video_stack)
        self.main_layout.addWidget(self.video_container_widget, stretch=4)

        # ── RIGHT: Sidebar ─────────────────────────────────────────────────────
        self.sidebar_widget = QFrame()
        self.sidebar_widget.setObjectName("sidebarWidget")
        self.sidebar_widget.setStyleSheet("""
            QFrame#sidebarWidget {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 5px;
            }
        """)
        self.sidebar_widget.setMinimumWidth(236)
        self.sidebar_widget.setMaximumWidth(288)

        self.sidebar = QVBoxLayout(self.sidebar_widget)
        self.sidebar.setContentsMargins(6, 6, 6, 6)
        self.sidebar.setSpacing(5)

        sidebar_header = QHBoxLayout()
        sidebar_header.setContentsMargins(0, 0, 0, 0)

        self.sidebar_title = QLabel("CONTROL PANEL")
        self.sidebar_title.setFont(QFont("Arial", 10, QFont.Bold))
        self.sidebar_title.setStyleSheet("color: #89b4fa;")
        sidebar_header.addWidget(self.sidebar_title)

        sidebar_header.addStretch()

        self.btn_toggle_sidebar = QPushButton()
        self.btn_toggle_sidebar.clicked.connect(self._toggle_sidebar)
        self.btn_toggle_sidebar.setMinimumSize(70, 36)
        self.btn_toggle_sidebar.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                font-size: 12px;
                padding: 0;
            }
        """)
        self._update_sidebar_toggle_button()
        sidebar_header.addWidget(self.btn_toggle_sidebar)
        self.sidebar.addLayout(sidebar_header)

        # System Status
        self.sidebar.addWidget(self._section_label("SYSTEM STATUS"))

        import torch
        device_name = 'CUDA' if torch.cuda.is_available() else 'CPU'
        self.hw_label = QLabel(f"AI ENGINE: {device_name}")
        self.hw_label.setStyleSheet("font-size: 12px;")
        self.sidebar.addWidget(self.hw_label)

        self.conn_label = QLabel("WEBSOCKET: 0 CLIENTS")
        self.conn_label.setStyleSheet("font-size: 12px;")
        self.sidebar.addWidget(self.conn_label)

        self.cam_url_label = QLabel()
        self.cam_url_label.setWordWrap(True)
        self.cam_url_label.setStyleSheet("font-size: 11px; color: #585b70;")
        self._refresh_url_label()
        self.sidebar.addWidget(self.cam_url_label)

        self.sidebar.addWidget(self._divider())

        # Parking Slots Area
        self.sidebar.addWidget(self._section_label("PARKING SLOTS"))
        self.slots_layout = QVBoxLayout()
        self.slots_layout.setAlignment(Qt.AlignTop)
        self.slots_layout.setSpacing(4)
        self.slots_widget = QWidget()
        self.slots_widget.setLayout(self.slots_layout)
        
        self.slots_scroll = QScrollArea()
        self.slots_scroll.setWidget(self.slots_widget)
        self.slots_scroll.setWidgetResizable(True)
        self.slots_scroll.setMinimumHeight(180)
        self.slots_scroll.setStyleSheet("QScrollArea { border: none; background-color: #1e1e2e; }")
        
        self.sidebar.addWidget(self.slots_scroll)
        self.sidebar.addStretch()

        self.sidebar.addWidget(self._divider())

        # Detection Control
        self.sidebar.addWidget(self._section_label("SELECTED CAMERA"))

        # Camera status info
        self.cam_status_label = QLabel()
        self.cam_status_label.setWordWrap(True)
        self.cam_status_label.setStyleSheet("font-size: 11px; color: #cdd6f4;")
        self._refresh_cam_status_label()
        self.sidebar.addWidget(self.cam_status_label)

        self.camera_nav_widget = QWidget()
        camera_nav_layout = QHBoxLayout(self.camera_nav_widget)
        camera_nav_layout.setContentsMargins(0, 0, 0, 0)
        camera_nav_layout.setSpacing(6)

        self.btn_prev_camera = QPushButton("◀ PREVIOUS")
        self.btn_prev_camera.clicked.connect(lambda: self._select_relative_camera(-1))
        self.btn_prev_camera.setStyleSheet(
            "background-color: #74c7ec; color: #11111b; font-weight: bold; padding: 6px 9px;"
        )
        self.btn_prev_camera.setMinimumHeight(28)
        camera_nav_layout.addWidget(self.btn_prev_camera)

        self.btn_next_camera = QPushButton("NEXT ▶")
        self.btn_next_camera.clicked.connect(lambda: self._select_relative_camera(1))
        self.btn_next_camera.setStyleSheet(
            "background-color: #74c7ec; color: #11111b; font-weight: bold; padding: 6px 9px;"
        )
        self.btn_next_camera.setMinimumHeight(28)
        camera_nav_layout.addWidget(self.btn_next_camera)
        self.sidebar.addWidget(self.camera_nav_widget)

        # View Switcher button
        self.btn_cameras = QPushButton("📹 VIEW ALL CAMERAS")
        self.btn_cameras.clicked.connect(self._toggle_camera_list)
        self.btn_cameras.setStyleSheet(
            "background-color: #fab387; color: #11111b; font-weight: bold; padding: 6px 10px;"
        )
        self.btn_cameras.setMinimumHeight(28)
        self.sidebar.addWidget(self.btn_cameras)

        # Detection toggle button
        self.btn_detect = QPushButton("🔴 AI DETECTION IS OFF")
        self.btn_detect.clicked.connect(self._toggle_detection)
        self.btn_detect.setStyleSheet(
            "background-color: #f38ba8; color: #11111b; font-weight: bold; padding: 6px 10px;"
        )
        self.btn_detect.setMinimumHeight(28)
        self.sidebar.addWidget(self.btn_detect)

        self.btn_refresh_camera = QPushButton("🔄 REFRESH CAMERA")
        self.btn_refresh_camera.clicked.connect(self._refresh_camera_connection)
        self.btn_refresh_camera.setStyleSheet(
            "background-color: #f9e2af; color: #11111b; font-weight: bold; padding: 6px 10px;"
        )
        self.btn_refresh_camera.setMinimumHeight(28)
        self.sidebar.addWidget(self.btn_refresh_camera)

        self.sidebar.addWidget(self._divider())

        # Action Buttons
        self.sidebar.addWidget(self._section_label("ACTIONS"))

        self.btn_settings = QPushButton("⚙  SETTINGS")
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_settings.setStyleSheet(
            "background-color: #cba6f7; color: #11111b; font-weight: bold; padding: 6px 10px;"
        )
        self.btn_settings.setMinimumHeight(28)

        self.btn_roi = QPushButton("📐  SET ROI")
        self.btn_roi.clicked.connect(self.open_roi_dialog)
        self.btn_roi.setStyleSheet(
            "background-color: #89dceb; color: #11111b; font-weight: bold; padding: 6px 10px;"
        )
        self.btn_roi.setMinimumHeight(28)

        self.sidebar.addWidget(self.btn_settings)
        self.sidebar.addWidget(self.btn_roi)

        self.main_layout.addWidget(self.sidebar_widget, stretch=0)
        self._update_camera_nav_buttons()

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Arial", 9, QFont.Bold))
        lbl.setStyleSheet("color: #89b4fa; margin-top: 4px;")
        return lbl

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #45475a; margin: 2px 0;")
        return line

    def _update_sidebar_toggle_button(self):
        icon_type = QStyle.SP_ArrowLeft if self.sidebar_expanded else QStyle.SP_ArrowRight
        tooltip = "Collapse sidebar" if self.sidebar_expanded else "Expand sidebar"
        self.btn_toggle_sidebar.setIcon(self.style().standardIcon(icon_type))
        self.btn_toggle_sidebar.setText("")
        self.btn_toggle_sidebar.setToolTip(tooltip)

    def _show_message(
        self,
        icon: QMessageBox.Icon,
        title: str,
        text: str,
        buttons: QMessageBox.StandardButton = QMessageBox.Ok,
        default_button: QMessageBox.StandardButton | None = None,
        informative_text: str | None = None,
    ) -> QMessageBox.StandardButton:
        """Show a simple native message box with optional explanatory text."""
        main_text = text
        detail_text = informative_text
        if detail_text is None and "\n\n" in text:
            main_text, detail_text = text.split("\n\n", 1)

        msg_box = QMessageBox(self)
        msg_box.setIcon(icon)
        msg_box.setWindowTitle(title)
        msg_box.setText(main_text)
        if detail_text:
            msg_box.setInformativeText(detail_text)
        msg_box.setStandardButtons(buttons)
        if default_button is not None:
            msg_box.setDefaultButton(default_button)
        msg_box.setStyleSheet(MESSAGE_BOX_STYLE)
        if msg_box.layout() is not None:
            msg_box.layout().setContentsMargins(16, 14, 16, 22)
            msg_box.layout().setSpacing(12)
        text_label = msg_box.findChild(QLabel, "qt_msgbox_label")
        if text_label is not None:
            text_label.setWordWrap(True)
            text_label.setMinimumWidth(360)
            text_label.setMaximumWidth(440)
            text_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            text_label.setContentsMargins(6, 0, 0, 0)
        info_label = msg_box.findChild(QLabel, "qt_msgbox_informativelabel")
        if info_label is not None:
            info_label.setWordWrap(True)
            info_label.setMinimumWidth(360)
            info_label.setMaximumWidth(440)
            info_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            info_label.setContentsMargins(6, 2, 0, 0)
        icon_label = msg_box.findChild(QLabel, "qt_msgboxex_icon_label")
        if icon_label is not None:
            icon_label.setFixedWidth(46)
            icon_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        msg_box.adjustSize()
        size_hint = msg_box.sizeHint()
        msg_box.resize(max(size_hint.width(), 580), max(size_hint.height(), 220))
        return QMessageBox.StandardButton(msg_box.exec())

    def _toggle_sidebar(self):
        self.sidebar_expanded = not self.sidebar_expanded

        widgets_to_toggle = [
            self.sidebar_title,
            self.hw_label,
            self.conn_label,
            self.cam_url_label,
            self.slots_scroll,
            self.cam_status_label,
            self.camera_nav_widget,
            self.btn_cameras,
            self.btn_detect,
            self.btn_refresh_camera,
            self.btn_settings,
            self.btn_roi,
        ]

        section_labels = self.sidebar_widget.findChildren(QLabel)
        dividers = self.sidebar_widget.findChildren(QFrame)

        if self.sidebar_expanded:
            self.sidebar_widget.setMinimumWidth(236)
            self.sidebar_widget.setMaximumWidth(288)
            self.sidebar.setContentsMargins(6, 6, 6, 6)
            self.sidebar.setSpacing(5)
            self.btn_toggle_sidebar.setMinimumSize(28, 28)
            for widget in widgets_to_toggle:
                widget.show()
            for lbl in section_labels:
                if lbl not in (self.sidebar_title, self.cam_title):
                    lbl.show()
            for divider in dividers:
                divider.show()
            self.sidebar_title.show()
        else:
            self.sidebar_widget.setMinimumWidth(44)
            self.sidebar_widget.setMaximumWidth(44)
            self.sidebar.setContentsMargins(4, 4, 4, 4)
            self.sidebar.setSpacing(2)
            self.btn_toggle_sidebar.setMinimumSize(28, 28)
            for widget in widgets_to_toggle:
                widget.hide()
            for lbl in section_labels:
                if lbl is not self.cam_title:
                    lbl.hide()
            for divider in dividers:
                divider.hide()
            self.sidebar_title.hide()

        self._update_sidebar_toggle_button()

    def _get_camera_ids_in_order(self) -> list[str]:
        """Return configured camera IDs in display order."""
        return [str(cam.get("id")) for cam in self._app_settings.get("cameras", []) if "id" in cam]

    def _select_relative_camera(self, step: int) -> None:
        """Move focus to the next or previous configured camera."""
        camera_ids = self._get_camera_ids_in_order()
        if not camera_ids:
            return

        if self.active_camera_id not in camera_ids:
            self._select_camera(camera_ids[0])
            return

        current_index = camera_ids.index(self.active_camera_id)
        target_index = (current_index + step) % len(camera_ids)
        self._select_camera(camera_ids[target_index])

    def _update_camera_nav_buttons(self) -> None:
        """Enable navigation only when single-camera mode has multiple cameras."""
        enabled = len(self._get_camera_ids_in_order()) > 1 and not self.grid_mode
        self.btn_prev_camera.setEnabled(enabled)
        self.btn_next_camera.setEnabled(enabled)

    def _build_camera_grid(self):
        """Build the grid view showing live feeds of all cameras."""
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
                
        self.grid_video_labels.clear()

        cameras = self._app_settings.get("cameras", [])
        if not cameras:
            lbl = QLabel("No cameras configured.")
            lbl.setStyleSheet("color: #a6adc8; font-size: 16px;")
            self.grid_layout.addWidget(lbl, 0, 0)
            return

        available_width = max(self.grid_scroll.viewport().width(), self.grid_scroll.width(), 1)
        cols = max(2, min(4, available_width // 260))
        for i, cam in enumerate(cameras):
            cam_id = str(cam.get("id"))
            name = cam.get("name", f"Camera {cam_id}")
            
            cam_container = QFrame()
            cam_container.setStyleSheet("""
                QFrame { background-color: #1e1e2e; border: 1px solid #313244; border-radius: 3px; }
                QFrame:hover { border: 1px solid #89b4fa; }
            """)
            clayout = QVBoxLayout(cam_container)
            clayout.setContentsMargins(2, 2, 2, 2)
            clayout.setSpacing(2)

            header = QWidget()
            header.setStyleSheet("background-color: transparent; border: none;")
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_layout.setSpacing(4)

            title_lbl = QLabel(f"CAM {cam_id}")
            title_lbl.setStyleSheet("""
                color: #cdd6f4; font-weight: bold; border: none; font-size: 10px;
                background-color: #313244; padding: 2px 6px; border-radius: 8px;
            """)
            title_lbl.setToolTip(name)
            header_layout.addWidget(title_lbl)

            if name and name != f"Camera {cam_id}":
                name_lbl = QLabel(name)
                name_lbl.setStyleSheet("color: #bac2de; border: none; font-size: 10px;")
                name_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                header_layout.addWidget(name_lbl, 1)
            else:
                header_layout.addStretch()

            video_lbl = QLabel("Connecting...")
            video_lbl.setAlignment(Qt.AlignCenter)
            video_lbl.setStyleSheet("background-color: #11111b; border: none;")
            video_lbl.setMinimumSize(220, 165)

            self.grid_video_labels[cam_id] = video_lbl

            btn = QPushButton("OPEN CAMERA")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(28)
            btn.setMinimumWidth(84)
            btn.setStyleSheet("""
                background-color: #89b4fa; color: #11111b; font-weight: bold;
                padding: 3px 8px; border-radius: 8px; font-size: 10px;
            """)
            btn.clicked.connect(lambda checked, cid=cam_id: self._select_camera(str(cid)))
            header_layout.addWidget(btn)

            clayout.addWidget(header)
            clayout.addWidget(video_lbl, 1)

            row = i // cols
            col = i % cols
            self.grid_layout.addWidget(cam_container, row, col)

    def _toggle_camera_list(self):
        """Toggle between single view and grid view."""
        self.grid_mode = not self.grid_mode
        if self.grid_mode:
            self._build_camera_grid()
            self.video_stack.setCurrentIndex(1)
            self.cam_title.setText("All Cameras Overview")
            self.btn_cameras.setText("🔙 SINGLE CAMERA VIEW")
            self.btn_cameras.setStyleSheet("background-color: #f38ba8; color: #11111b; font-weight: bold; font-size: 14px; padding: 10px;")
            
            self.btn_detect.setEnabled(False)
            self.btn_roi.setEnabled(False)
            self.btn_refresh_camera.setEnabled(False)
        else:
            self.video_stack.setCurrentIndex(0)
            self.btn_cameras.setText("📹 VIEW ALL CAMERAS")
            self.btn_cameras.setStyleSheet("background-color: #89b4fa; color: #11111b; font-weight: bold; font-size: 14px; padding: 10px;")
            
            self.btn_detect.setEnabled(True)
            self.btn_roi.setEnabled(True)
            self._refresh_cam_status_label()
            self._refresh_camera_button_state()

        self._update_camera_nav_buttons()

    def _select_camera(self, cam_id: str):
        """Set the active camera for the single view mode."""
        self.active_camera_id = cam_id
        self._focused_raw_frame = self._latest_raw_frames.get(cam_id)
        if self.grid_mode:
            self._toggle_camera_list()
        self._refresh_cam_status_label()
        self._update_camera_nav_buttons()
        self._refresh_camera_button_state()
        
        unit = self.unit_manager.get_unit(cam_id)
        if unit:
            enabled = getattr(unit.detect, 'enabled', False)
            if enabled:
                self.btn_detect.setText("🟢 AI DETECTION IS ON")
                self.btn_detect.setStyleSheet("background-color: #a6e3a1; color: #11111b; font-weight: bold; font-size: 14px; padding: 10px;")
            else:
                self.btn_detect.setText("🔴 AI DETECTION IS OFF")
                self.btn_detect.setStyleSheet("background-color: #f38ba8; color: #11111b; font-weight: bold; font-size: 14px; padding: 10px;")

    def _refresh_url_label(self):
        count = len(self.unit_manager.units)
        self.cam_url_label.setText(f"Active Streams: {count}")

    def _refresh_cam_status_label(self):
        """Update the sidebar title with currently focused camera info."""
        if not self.active_camera_id:
            self.cam_title.setText("No Camera Selected")
            self.cam_status_label.setText("None")
            return
            
        cameras = self._app_settings.get("cameras", [])
        cam = None
        for c in cameras:
            if str(c.get("id")) == self.active_camera_id:
                cam = c
                break
                
        if cam:
            name = cam.get("name", "Unknown Camera")
            model = cam.get("model", "")
            model_name = os.path.basename(model) if model else "No Model (Raw Feed)"
            
            self.cam_title.setText(f"📹 {name}")
            self.cam_status_label.setText(f"Camera: {name}\nModel: {model_name}")

    def _refresh_camera_button_state(self) -> None:
        """Update the refresh button according to the active camera connection state."""
        if self.grid_mode or not self.active_camera_id:
            self.btn_refresh_camera.setEnabled(False)
            self.btn_refresh_camera.setText("🔄 REFRESH CAMERA")
            return

        unit = self.unit_manager.get_unit(self.active_camera_id)
        if not unit:
            self.btn_refresh_camera.setEnabled(False)
            self.btn_refresh_camera.setText("🔄 REFRESH CAMERA")
            return

        camera = unit.camera
        if camera.is_connecting():
            self.btn_refresh_camera.setEnabled(False)
            self.btn_refresh_camera.setText("⏳ CONNECTING...")
        elif camera.is_connected:
            self.btn_refresh_camera.setEnabled(False)
            self.btn_refresh_camera.setText("✅ CONNECTED")
        elif camera.is_waiting_for_refresh():
            self.btn_refresh_camera.setEnabled(True)
            self.btn_refresh_camera.setText("🔄 REFRESH CAMERA")
        else:
            self.btn_refresh_camera.setEnabled(False)
            self.btn_refresh_camera.setText("⏳ WAITING...")
            
    # ── Action Handlers ────────────────────────────────────────────────

    def _toggle_detection(self):
        """Toggle AI detection only for the actively focused camera."""
        if not self.active_camera_id:
            return
            
        unit = self.unit_manager.get_unit(self.active_camera_id)
        if not unit:
            return
            
        new_state = not getattr(unit.detect, 'enabled', False)
        unit.set_detection_enabled(new_state)
        
        if new_state:
            self.btn_detect.setText("🟢 AI DETECTION IS ON")
            self.btn_detect.setStyleSheet("background-color: #a6e3a1; color: #11111b; font-weight: bold; font-size: 14px; padding: 10px;")
        else:
            self.btn_detect.setText("🔴 AI DETECTION IS OFF")
            self.btn_detect.setStyleSheet("background-color: #f38ba8; color: #11111b; font-weight: bold; font-size: 14px; padding: 10px;")

    def _refresh_camera_connection(self) -> None:
        """Request a manual reconnect for the actively focused camera."""
        if not self.active_camera_id:
            return

        unit = self.unit_manager.get_unit(self.active_camera_id)
        if not unit:
            return

        requested, message = unit.request_camera_refresh()
        if not requested and "spam" not in message.lower():
            self._show_message(QMessageBox.Icon.Information, "Refresh Camera", message)

        self._refresh_camera_button_state()

    # ── Settings ───────────────────────────────────────────────────────────────

    def open_settings(self):
        """Open settings dialog and sync changes with the UnitManager."""
        dialog = SettingsDialog(self)
        if dialog.exec() == SettingsDialog.Accepted:
            self._app_settings = dialog.get_settings()
            
            ws_cfg = self._app_settings.get("websocket", {})
            self.ws_server.stop()
            if self.ws_server.is_alive():
                self.ws_server.join(timeout=2.0)
            self.ws_server = WebSocketModule(
                host=ws_cfg.get("host", "0.0.0.0"),
                port=ws_cfg.get("port", 8765)
            )
            self.ws_server.start()

            cameras_config = self._app_settings.get("cameras", [])
            self.unit_manager.sync_cameras(cameras_config)
            
            if self.grid_mode:
                self._build_camera_grid()
                
            active_ids = self.unit_manager.get_all_active_ids()
            if self.active_camera_id not in active_ids and active_ids:
                self._select_camera(active_ids[0])
            else:
                self._refresh_cam_status_label()
                self._update_camera_nav_buttons()
                self._refresh_camera_button_state()

    def _resolve_model_path(self, path: str) -> str:
        if not path: return ""
        if os.path.isabs(path): return path
        return os.path.join(BASE_DIR, path)

    # ── ROI Dialog ─────────────────────────────────────────────────────────────

    def open_roi_dialog(self):
        """Open ROI configuration only for the actively focused camera."""
        if not self.active_camera_id:
            self._show_message(
                QMessageBox.Icon.Warning,
                "Select Camera",
                "Please select a camera.",
            )
            return
            
        unit = self.unit_manager.get_unit(self.active_camera_id)
        if not unit:
            return
            
        snapshot = self._latest_raw_frames.get(self.active_camera_id)
        if snapshot is None:
            self._show_message(
                QMessageBox.Icon.Warning,
                "No Frame",
                "Wait for the camera to connect.",
            )
            return

        with unit.detect.lock:
            current_rois = ROIDialog.normalize_rois(unit.detect.slot_rois)

        dialog = ROIDialog(snapshot.copy(), unit.detect, current_rois, self)
        if dialog.exec() == ROIDialog.Accepted:
            new_rois = dialog.get_rois()
            with unit.detect.lock:
                unit.detect.slot_rois = ROIDialog.normalize_rois(new_rois)
            self.save_rois(silent=True)

    def save_rois(self, silent=False):
        """Save the ROIs extracted from all active detectors."""
        config = {}
        for cam_id in self.unit_manager.get_all_active_ids():
            unit = self.unit_manager.get_unit(cam_id)
            if unit:
                with unit.detect.lock:
                    config[cam_id] = unit.detect.slot_rois.copy()
            
        try:
            file_path = os.path.join(BASE_DIR, "config_detector.json")
            with open(file_path, 'w') as f:
                json.dump(config, f, indent=4)
            if not silent:
                self._show_message(
                    QMessageBox.Icon.Information,
                    "Saved",
                    "All Region of Interests have been saved.",
                )
        except Exception as e:
            self._show_message(
                QMessageBox.Icon.Critical,
                "Error",
                f"Failed to save ROI settings: {e}",
            )

    def load_rois(self):
        """Load ROIs from config and push strictly to UnitManager."""
        try:
            file_path = os.path.join(BASE_DIR, "config_detector.json")
            with open(file_path, "r") as f:
                config = json.load(f)
                
                # Check for legacy single-camera formats
                if "parking_slots" in config:
                    legacy_rois = config["parking_slots"]
                    active = self.active_camera_id if self.active_camera_id else "1"
                    config = {str(active): ROIDialog.normalize_rois(legacy_rois)}
                elif any(isinstance(v, list) for v in config.values()): 
                    # Another legacy raw dict
                    active = self.active_camera_id if self.active_camera_id else "1"
                    config = {str(active): ROIDialog.normalize_rois(config)}
                else:
                    config = {
                        str(cam_id): ROIDialog.normalize_rois(cam_rois)
                        for cam_id, cam_rois in config.items()
                    }
                
                self.unit_manager.apply_rois(config)
        except:
            pass

    # ── UI Update Loop ─────────────────────────────────────────────────────────

    def update_ui(self):
        """Timer callback loop that updates all camera views and broadcasts to WebSocket."""
        clients_count = len(self.ws_server.clients)
        self.conn_label.setText(f"WEBSOCKET: {clients_count} CLIENTS")
        
        results = self.unit_manager.get_all_results()
        
        # Connection status for offline units
        for cam_id, unit in self.unit_manager.units.items():
            if not unit.camera.is_connected:
                status_text = unit.camera.get_status_text() or "Connecting or Offline..."
                placeholder = self._create_placeholder_pixmap(status_text, 640, 480)
                if self.grid_mode and cam_id in self.grid_video_labels:
                    grid_lbl = self.grid_video_labels[cam_id]
                    scaled = placeholder.scaled(grid_lbl.width(), grid_lbl.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    grid_lbl.setPixmap(scaled)
                    
                if not self.grid_mode and cam_id == self.active_camera_id:
                    self.single_video_label.setPixmap(placeholder)

        # Process new frames and states
        for cam_id, res in results.items():
            frame_bgr = res["frame"]
            raw_frame = res["raw_frame"]
            self._latest_raw_frames[str(cam_id)] = raw_frame.copy()
            
            h, w, ch = frame_bgr.shape
            bytes_per_line = ch * w
            img = QImage(frame_bgr.data, w, h, bytes_per_line, QImage.Format_BGR888)
            pixmap = QPixmap.fromImage(img)
            
            if self.grid_mode and cam_id in self.grid_video_labels:
                lbl = self.grid_video_labels[cam_id]
                scaled_pixmap = pixmap.scaled(lbl.width(), lbl.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                lbl.setPixmap(scaled_pixmap)
                
            if not self.grid_mode and cam_id == self.active_camera_id:
                self._focused_raw_frame = raw_frame
                scaled_pixmap = pixmap.scaled(self.single_video_label.width(), self.single_video_label.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.single_video_label.setPixmap(scaled_pixmap)
                self._update_sidebar_slots(res["slots"])

        self._refresh_camera_button_state()
        
        merged_states = self.unit_manager.get_all_slot_states()
        self.ws_server.send_data_to_all(merged_states)
        
    def _create_placeholder_pixmap(self, text, w, h) -> QPixmap:
        pixmap = QPixmap(w, h)
        pixmap.fill(QColor("#11111b"))
        painter = QPainter(pixmap)
        painter.setPen(QColor("#a6adc8"))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
        painter.end()
        return pixmap

    def _update_sidebar_slots(self, slots_data: dict):
        while self.slots_layout.count():
            item = self.slots_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
                
        if not slots_data:
            lbl = QLabel("No detection data or ROIs defined.")
            lbl.setStyleSheet("color: #a6adc8; padding-top: 10px;")
            self.slots_layout.addWidget(lbl)
            return

        for slot_id, state in slots_data.items():
            row = QWidget()
            lo = QHBoxLayout(row)
            lo.setContentsMargins(4, 3, 4, 3)

            lbl_id = QLabel(f"Slot {slot_id}")
            lbl_id.setStyleSheet("color: #cdd6f4; font-weight: bold; font-size: 13px;")

            lbl_state = QLabel(state.upper())
            if state == "empty":
                lbl_state.setStyleSheet("color: #a6e3a1; font-weight: bold; font-size: 13px;")
            elif state == "occupied":
                lbl_state.setStyleSheet("color: #f38ba8; font-weight: bold; font-size: 13px;")
            else:
                lbl_state.setStyleSheet("color: #bac2de; font-weight: bold; font-size: 13px;")
                
            lo.addWidget(lbl_id)
            lo.addStretch()
            lo.addWidget(lbl_state)
            self.slots_layout.addWidget(row)

    # ── Shutdown ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        print("[MainWindow] Shutting down...")
        self.timer.stop()
        self.unit_manager.stop_all()
        self.ws_server.stop()
        if self.ws_server.is_alive():
            self.ws_server.join(timeout=2.0)
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
