import sys
import queue
import os
import time
import cv2
import json
import numpy as np
from PySide6.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout,
                               QHBoxLayout, QWidget, QPushButton, QFrame,
                               QMessageBox, QScrollArea, QGridLayout, QStackedWidget, QSizePolicy)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap, QFont, QPainter, QColor

from unit_manager import UnitManager
from web_socket import WebSocketModule
from settings_dialog import SettingsDialog, load_settings
from roi_dialog import ROIDialog

# Portability
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


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
                padding: 8px 14px;
                font-size: 13px;
                font-weight: bold;
                color: #11111b;
            }
        """)

        # ── State Properties ────────────────────────────────────────────────────────
        self.grid_mode = False          # True = View all cameras
        self.active_camera_id = None    # Currently focused camera ID
        self._focused_raw_frame: np.ndarray | None = None
        self.grid_video_labels = {}     # Dictionary mapping cam_id -> QLabel
        
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
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(12)

        # ── LEFT: Main Display Area ────────────────────────────────────────────
        self.video_container_widget = QWidget()
        self.video_container_layout = QVBoxLayout(self.video_container_widget)
        self.video_container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Title bar above video
        self.cam_title = QLabel("Initializing...")
        self.cam_title.setStyleSheet("""
            font-size: 16px; font-weight: bold; color: #cdd6f4;
            background-color: #313244; padding: 8px; border-radius: 4px;
        """)
        self.cam_title.setAlignment(Qt.AlignCenter)
        self.video_container_layout.addWidget(self.cam_title)

        # Stack to hold Single View vs Grid View
        self.video_stack = QStackedWidget()
        
        # Single View Label
        self.single_video_label = QLabel("Waiting for camera...")
        self.single_video_label.setAlignment(Qt.AlignCenter)
        self.single_video_label.setStyleSheet("background-color: #11111b; color: #a6adc8; border-radius: 4px;")
        self.single_video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.single_video_label.setMinimumSize(640, 480)
        
        # Grid View Area
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setStyleSheet("QScrollArea { border: none; background-color: #11111b; }")
        
        self.grid_container = QWidget()
        self.grid_container.setStyleSheet("background-color: #11111b;")
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(10)
        
        self.grid_scroll.setWidget(self.grid_container)
        
        self.video_stack.addWidget(self.single_video_label) # Index 0
        self.video_stack.addWidget(self.grid_scroll)        # Index 1

        self.video_container_layout.addWidget(self.video_stack)
        self.main_layout.addWidget(self.video_container_widget, stretch=4)

        # ── RIGHT: Sidebar ─────────────────────────────────────────────────────
        self.sidebar = QVBoxLayout()
        self.sidebar.setContentsMargins(4, 0, 4, 0)
        self.sidebar.setSpacing(6)

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
        self.slots_widget = QWidget()
        self.slots_widget.setLayout(self.slots_layout)
        
        self.slots_scroll = QScrollArea()
        self.slots_scroll.setWidget(self.slots_widget)
        self.slots_scroll.setWidgetResizable(True)
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

        # View Switcher button
        self.btn_cameras = QPushButton("📹 VIEW ALL CAMERAS")
        self.btn_cameras.clicked.connect(self._toggle_camera_list)
        self.btn_cameras.setStyleSheet(
            "background-color: #fab387; color: #11111b; font-weight: bold; padding: 10px;"
        )
        self.sidebar.addWidget(self.btn_cameras)

        # Detection toggle button
        self.btn_detect = QPushButton("🔴 AI DETECTION IS OFF")
        self.btn_detect.clicked.connect(self._toggle_detection)
        self.btn_detect.setStyleSheet(
            "background-color: #f38ba8; color: #11111b; font-weight: bold; padding: 10px;"
        )
        self.sidebar.addWidget(self.btn_detect)

        self.sidebar.addWidget(self._divider())

        # Action Buttons
        self.sidebar.addWidget(self._section_label("ACTIONS"))

        self.btn_settings = QPushButton("⚙  SETTINGS")
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_settings.setStyleSheet(
            "background-color: #cba6f7; color: #11111b; font-weight: bold; padding: 10px;"
        )

        self.btn_roi = QPushButton("📐  SET ROI")
        self.btn_roi.clicked.connect(self.open_roi_dialog)
        self.btn_roi.setStyleSheet(
            "background-color: #89dceb; color: #11111b; font-weight: bold; padding: 10px;"
        )

        self.sidebar.addWidget(self.btn_settings)
        self.sidebar.addWidget(self.btn_roi)

        self.main_layout.addLayout(self.sidebar, stretch=1)

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Arial", 10, QFont.Bold))
        lbl.setStyleSheet("color: #89b4fa; margin-top: 8px;")
        return lbl

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #45475a; margin: 4px 0;")
        return line

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

        cols = 2
        for i, cam in enumerate(cameras):
            cam_id = str(cam.get("id"))
            name = cam.get("name", f"Camera {cam_id}")
            
            cam_container = QFrame()
            cam_container.setStyleSheet("""
                QFrame { background-color: #1e1e2e; border: 2px solid #313244; border-radius: 4px; }
                QFrame:hover { border: 2px solid #89b4fa; }
            """)
            clayout = QVBoxLayout(cam_container)
            clayout.setContentsMargins(5, 5, 5, 5)
            
            title_lbl = QLabel(name)
            title_lbl.setStyleSheet("color: #cdd6f4; font-weight: bold; border: none;")
            title_lbl.setAlignment(Qt.AlignCenter)
            clayout.addWidget(title_lbl)
            
            video_lbl = QLabel("Connecting...")
            video_lbl.setAlignment(Qt.AlignCenter)
            video_lbl.setStyleSheet("background-color: #11111b; border: none;")
            video_lbl.setMinimumSize(320, 240)
            clayout.addWidget(video_lbl)
            
            self.grid_video_labels[cam_id] = video_lbl
            
            btn = QPushButton("Focus")
            btn.setStyleSheet("""
                background-color: #89b4fa; color: #11111b; font-weight: bold;
                padding: 4px; border-radius: 2px;
            """)
            btn.clicked.connect(lambda checked, cid=cam_id: self._select_camera(str(cid)))
            clayout.addWidget(btn)

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
        else:
            self.video_stack.setCurrentIndex(0)
            self.btn_cameras.setText("📹 VIEW ALL CAMERAS")
            self.btn_cameras.setStyleSheet("background-color: #89b4fa; color: #11111b; font-weight: bold; font-size: 14px; padding: 10px;")
            
            self.btn_detect.setEnabled(True)
            self.btn_roi.setEnabled(True)
            self._refresh_cam_status_label()

    def _select_camera(self, cam_id: str):
        """Set the active camera for the single view mode."""
        self.active_camera_id = cam_id
        if self.grid_mode:
            self._toggle_camera_list()
        self._refresh_cam_status_label()
        
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

    # ── Settings ───────────────────────────────────────────────────────────────

    def open_settings(self):
        """Open settings dialog and sync changes with the UnitManager."""
        dialog = SettingsDialog(self)
        if dialog.exec() == SettingsDialog.Accepted:
            self._app_settings = dialog.get_settings()
            
            ws_cfg = self._app_settings.get("websocket", {})
            self.ws_server.stop()
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

    def _resolve_model_path(self, path: str) -> str:
        if not path: return ""
        if os.path.isabs(path): return path
        return os.path.join(BASE_DIR, path)

    # ── ROI Dialog ─────────────────────────────────────────────────────────────

    def open_roi_dialog(self):
        """Open ROI configuration only for the actively focused camera."""
        if not self.active_camera_id:
            QMessageBox.warning(self, "Select Camera", "Please add and select a camera first.")
            return
            
        unit = self.unit_manager.get_unit(self.active_camera_id)
        if not unit:
            return
            
        if self._focused_raw_frame is None:
            QMessageBox.warning(self, "No Frame", "Wait for the camera to connect before opening ROI setup.")
            return

        with unit.detect.lock:
            current_rois = unit.detect.slot_rois.copy()

        dialog = ROIDialog(self._focused_raw_frame, unit.detect, current_rois, self)
        if dialog.exec() == ROIDialog.Accepted:
            new_rois = dialog.get_rois()
            with unit.detect.lock:
                unit.detect.slot_rois = new_rois
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
                QMessageBox.information(self, "Saved", "All Region of Interests have been saved.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save ROI settings: {e}")

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
                    config = {active: legacy_rois}
                elif any(isinstance(v, list) for v in config.values()): 
                    # Another legacy raw dict
                    active = self.active_camera_id if self.active_camera_id else "1"
                    config = {active: config}
                
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
                placeholder = self._create_placeholder_pixmap("Connecting or Offline...", 640, 480)
                if self.grid_mode and cam_id in self.grid_video_labels:
                    grid_lbl = self.grid_video_labels[cam_id]
                    scaled = placeholder.scaled(grid_lbl.width(), grid_lbl.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    grid_lbl.setPixmap(scaled)
                    
                if not self.grid_mode and cam_id == self.active_camera_id:
                    self.single_video_label.setPixmap(placeholder)

        # Process new frames and states
        for cam_id, res in results.items():
            frame_rgb = res["frame"]
            raw_frame = res["raw_frame"]
            
            h, w, ch = frame_rgb.shape
            bytes_per_line = ch * w
            img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
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
            lo.setContentsMargins(5, 5, 5, 5)
            
            lbl_id = QLabel(f"Slot {slot_id}")
            lbl_id.setStyleSheet("color: #cdd6f4; font-weight: bold; font-size: 14px;")
            
            lbl_state = QLabel(state.upper())
            if state == "empty":
                lbl_state.setStyleSheet("color: #a6e3a1; font-weight: bold; font-size: 14px;")
            elif state == "occupied":
                lbl_state.setStyleSheet("color: #f38ba8; font-weight: bold; font-size: 14px;")
            else:
                lbl_state.setStyleSheet("color: #bac2de; font-weight: bold; font-size: 14px;")
                
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
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())