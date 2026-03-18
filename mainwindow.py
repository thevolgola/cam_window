import sys
import queue
import os
import time
import cv2
import json
import numpy as np
from PySide6.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout,
                               QHBoxLayout, QWidget, QPushButton, QFrame,
                               QMessageBox, QScrollArea, QGridLayout)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap, QFont

from camera import CameraModule
from detect import YOLODetector
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

        # ── Data Queues ────────────────────────────────────────────────────────
        self.frame_queue = queue.Queue(maxsize=1)
        self.result_queue = queue.Queue(maxsize=1)

        # ── Load Settings ──────────────────────────────────────────────────────
        self._app_settings = load_settings()

        # First camera URL
        rtsp_url = self._get_camera_url(0)
        camera_source = self._convert_source(rtsp_url) if rtsp_url else 0

        # Get model for first camera from settings
        model_path = self._resolve_model_path(self._get_camera_model(0))
        if not model_path:
            print("[MainWindow] WARNING: No AI model set for the initial camera.")
        elif not os.path.exists(model_path):
            print(f"[MainWindow] CRITICAL: Model file not found at {model_path}!")

        # ── Module Init ────────────────────────────────────────────────────────
        ws_cfg = self._app_settings.get("websocket", {})
        self.ws_server = WebSocketModule(
            host=ws_cfg.get("host", "0.0.0.0"),
            port=int(ws_cfg.get("port", 8765))
        )
        self.camera = CameraModule(source=camera_source, frame_queue=self.frame_queue)
        self.detect = YOLODetector(self.frame_queue, self.result_queue,
                                   model_path=model_path)
        self.detect.ws_module = self.ws_server

        # Latest frame snapshot (used by ROI dialog)
        self._latest_frame: np.ndarray | None = None

        # ── Detection Control ──────────────────────────────────────────────────
        self._detection_enabled = False  # Start detection OFF by default
        self._current_camera_idx = 0    # Track which camera is currently displayed
        self._showing_camera_list = False  # Track if showing camera list
        self._previous_camera_idx = 0  # Track last viewed single camera
        self._connection_timeout = 10.0  # Timeout in seconds for camera connection

        self.setup_ui()
        self.detect.slot_rois = ROIDialog.load_rois()

        # ── Start Threads ──────────────────────────────────────────────────────
        self.ws_server.start()
        self.camera.start()
        self.detect.start()

        # ── UI Refresh Timer (≈30 FPS) ─────────────────────────────────────────
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(33)

    # ── UI Construction ────────────────────────────────────────────────────────

    def setup_ui(self):
        """Creates a modern layout with a sidebar."""
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(12)

        # ── LEFT: Video Feed ───────────────────────────────────────────────────
        self.video_container = QVBoxLayout()
        self.video_label = QLabel("INITIALIZING STREAM...")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet(
            "background-color: #11111b; border: 2px solid #45475a; "
            "border-radius: 10px; font-size: 14px; color: #585b70;"
        )
        self.video_container.addWidget(self.video_label)

        # Camera Grid (hidden by default)
        self.camera_grid_container = QWidget()
        self.camera_grid_layout = QGridLayout(self.camera_grid_container)
        self.camera_grid_layout.setSpacing(12)
        self.camera_grid_layout.setContentsMargins(12, 12, 12, 12)
        self.camera_grid_layout.setColumnStretch(0, 1)
        self.camera_grid_layout.setColumnStretch(1, 1)
        self.camera_grid_container.setStyleSheet("background-color: #11111b;")
        self._build_camera_grid()
        self.video_container.addWidget(self.camera_grid_container)

        self.camera_grid_container.hide()  # Hidden initially

        self.main_layout.addLayout(self.video_container, stretch=4)

        # ── RIGHT: Sidebar ─────────────────────────────────────────────────────
        self.sidebar = QVBoxLayout()
        self.sidebar.setContentsMargins(4, 0, 4, 0)
        self.sidebar.setSpacing(6)

        # System Status
        self.sidebar.addWidget(self._section_label("SYSTEM STATUS"))

        self.hw_label = QLabel(f"AI ENGINE: {self.detect.device.upper()}")
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

        # Parking Slots
        self.sidebar.addWidget(self._section_label("PARKING SLOTS"))
        self.slot_status_label = QLabel("Waiting for data...")
        self.slot_status_label.setWordWrap(True)
        self.slot_status_label.setFont(QFont("Consolas", 10))
        self.sidebar.addWidget(self.slot_status_label)

        self.sidebar.addStretch()

        self.sidebar.addWidget(self._divider())

        # Detection Control
        self.sidebar.addWidget(self._section_label("DETECTION"))

        # Camera selector info
        self.cam_status_label = QLabel()
        self.cam_status_label.setWordWrap(True)
        self.cam_status_label.setStyleSheet("font-size: 11px; color: #cdd6f4;")
        self._refresh_cam_status_label()
        self.sidebar.addWidget(self.cam_status_label)

        # Camera list button
        self.btn_cameras = QPushButton("📹 VIEW ALL CAMERAS")
        self.btn_cameras.clicked.connect(self._toggle_camera_list)
        self.btn_cameras.setStyleSheet(
            "background-color: #fab387; color: #11111b; font-weight: bold; padding: 10px;"
        )
        self.sidebar.addWidget(self.btn_cameras)

        # Detection toggle button
        self.btn_detect = QPushButton("⏸ DETECTION: OFF")
        self.btn_detect.setCheckable(True)
        self.btn_detect.setChecked(self._detection_enabled)
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
        """Build camera grid with all available cameras (up to 4)."""
        # Clear existing layout
        while self.camera_grid_layout.count():
            child = self.camera_grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        cameras = self._app_settings.get("cameras", [])
        col = 0
        row = 0
        max_cameras = 4

        for idx, cam in enumerate(cameras[:max_cameras]):
            cam_btn = QPushButton()
            cam_name = cam.get("name", f"Camera {idx + 1}")
            cam_url = cam.get("url", "N/A")
            model = cam.get("model", "No Model")

            # Create button with camera info
            cam_btn.setText(f"📷 {cam_name}\n{cam_url[:40]}...\n🤖 {model}")
            cam_btn.setMinimumHeight(120)
            cam_btn.clicked.connect(lambda checked, i=idx: self._select_camera(i))

            # Style the button
            is_current = idx == self._current_camera_idx and not self._showing_camera_list
            if is_current:
                cam_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #a6e3a1;
                        color: #11111b;
                        border: 3px solid #89b4fa;
                        border-radius: 10px;
                        font-weight: bold;
                        padding: 10px;
                        font-size: 12px;
                    }
                    QPushButton:hover { background-color: #b5f0b0; }
                """)
            else:
                cam_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #313244;
                        color: #cdd6f4;
                        border: 2px solid #45475a;
                        border-radius: 10px;
                        padding: 10px;
                        font-size: 12px;
                    }
                    QPushButton:hover { 
                        background-color: #45475a;
                        border: 2px solid #89b4fa;
                    }
                """)

            self.camera_grid_layout.addWidget(cam_btn, row, col)

            col += 1
            if col >= 2:
                col = 0
                row += 1

    def _toggle_camera_list(self):
        """Toggle between single camera view and all cameras grid."""
        if self._showing_camera_list:
            # Returning from camera list - restore previous camera
            self._current_camera_idx = self._previous_camera_idx
            self._hide_camera_list()
        else:
            # Show all cameras
            self._show_camera_list()

    def _show_camera_list(self):
        """Show the camera grid view."""
        self._previous_camera_idx = self._current_camera_idx
        self._showing_camera_list = True
        self.video_label.hide()
        self.camera_grid_container.show()
        self._build_camera_grid()
        self.btn_cameras.setText("◀ BACK TO CAMERA")
        self.btn_cameras.setStyleSheet(
            "background-color: #74c7ec; color: #11111b; font-weight: bold; padding: 10px;"
        )

    def _hide_camera_list(self):
        """Hide the camera grid view and return to single camera."""
        self._showing_camera_list = False
        self.camera_grid_container.hide()
        self.video_label.show()
        self.btn_cameras.setText("📹 VIEW ALL CAMERAS")
        self.btn_cameras.setStyleSheet(
            "background-color: #fab387; color: #11111b; font-weight: bold; padding: 10px;"
        )
        # Note: Don't reset _current_camera_idx here - it may have been updated by _select_camera()
        self._refresh_cam_status_label()

    def _select_camera(self, idx: int):
        """Select a specific camera and close the camera list."""
        cameras = self._app_settings.get("cameras", [])
        if idx >= len(cameras):
            return

        # Get the new camera URL
        new_url = cameras[idx].get("url", "")
        old_url = self._get_camera_url(self._current_camera_idx)

        # Update the current camera index
        self._current_camera_idx = idx
        self._refresh_cam_status_label()

        # Update model for this specific camera
        new_model = self._resolve_model_path(self._get_camera_model(idx))
        self.detect.change_model(new_model)

        # If the URL is different, restart the camera
        if new_url and new_url != old_url:
            self._restart_camera(new_url)

        # Auto-switch back to single camera view (call _hide_camera_list directly, not _toggle_camera_list
        # to avoid resetting the camera index)
        self._hide_camera_list()

    def _refresh_url_label(self):
        url = self._get_camera_url(0)
        # Mask password in display
        display = url if len(url) < 60 else url[:57] + "…"
        self.cam_url_label.setText(f"📡 {display}")

    def _refresh_cam_status_label(self):
        """Update the camera status label with current camera info and model."""
        cameras = self._app_settings.get("cameras", [])
        if cameras and self._current_camera_idx < len(cameras):
            cam = cameras[self._current_camera_idx]
            name = cam.get("name", "Camera")
            model = cam.get("model", "")
            model_display = f"🤖 Model: {model}" if model else "🤖 Model: Not Set"
            self.cam_status_label.setText(f"📷 {name}\n{model_display}")
        else:
            self.cam_status_label.setText("No camera configured")

    def _toggle_detection(self):
        """Toggle detection on/off. Warn if no model is set."""
        # Get current camera configuration
        cameras = self._app_settings.get("cameras", [])
        if not cameras or self._current_camera_idx >= len(cameras):
            QMessageBox.warning(self, "Detection", "No camera configured.")
            self.btn_detect.setChecked(False)
            return

        current_camera = cameras[self._current_camera_idx]
        model = current_camera.get("model", "").strip()

        # If trying to enable detection without a model
        if self.btn_detect.isChecked() and not model:
            QMessageBox.warning(
                self, "Detection Warning",
                f"Cannot enable detection for camera '{current_camera.get('name', 'Camera')}'.\n\n"
                "No AI model has been set. Please configure a model in Settings first."
            )
            self.btn_detect.setChecked(False)
            return

        # Update detection state
        self._detection_enabled = self.btn_detect.isChecked()
        
        # Update button appearance
        if self._detection_enabled:
            # Enable detection in self.detect module
            self.btn_detect.setText("▶ DETECTION: ON")
            self.btn_detect.setStyleSheet(
                "background-color: #a6e3a1; color: #11111b; font-weight: bold; padding: 10px;"
            )
            self.detect.enabled = True
            print("[MainWindow] Detection enabled")
        else:
            self.btn_detect.setText("⏸ DETECTION: OFF")
            self.btn_detect.setStyleSheet(
                "background-color: #f38ba8; color: #11111b; font-weight: bold; padding: 10px;"
            )
            # Disable detection in self.detect module
            self.detect.enabled = False
            print("[MainWindow] Detection disabled")

    # ── Settings ───────────────────────────────────────────────────────────────

    def open_settings(self):
        """Open the settings dialog. Restart camera if URL changed."""
        dlg = SettingsDialog(parent=self)
        if dlg.exec() == SettingsDialog.Accepted:
            new_settings = dlg.get_settings()
            old_url = self._get_camera_url(self._current_camera_idx)
            self._app_settings = new_settings
            new_url = self._get_camera_url(self._current_camera_idx)

            # Check if current camera still exists
            cameras = self._app_settings.get("cameras", [])
            if self._current_camera_idx >= len(cameras):
                # Current camera was deleted, switch to camera 0
                self._current_camera_idx = 0
                new_url = self._get_camera_url(0)

            self._refresh_url_label()
            self._refresh_cam_status_label()

            # Rebuild camera grid if visible
            if self._showing_camera_list:
                self._build_camera_grid()

            # Restart camera if URL changed
            if old_url and old_url != new_url:
                self._restart_camera(new_url)
                QMessageBox.information(
                    self, "Settings Applied",
                    f"Camera updated.\nReconnecting to: {new_url[:50]}..."
                )
            else:
                # Still check if the model changed even if URL didn't
                new_model = self._resolve_model_path(self._get_camera_model(self._current_camera_idx))
                self.detect.change_model(new_model)
                QMessageBox.information(
                    self, "Settings Saved",
                    "Settings updated."
                )

    def _get_camera_url(self, index: int = 0) -> str:
        """Return the URL of camera at the given index, or empty string."""
        cameras = self._app_settings.get("cameras", [])
        if cameras and index < len(cameras):
            return cameras[index].get("url", "")
        return ""

    def _get_camera_model(self, index: int = 0) -> str:
        """Return the model path of camera at the given index."""
        cameras = self._app_settings.get("cameras", [])
        if cameras and index < len(cameras):
            return cameras[index].get("model", "")
        return ""

    def _resolve_model_path(self, path: str) -> str:
        """Helper to resolve relative paths to BASE_DIR."""
        if not path:
            return ""
        if os.path.isabs(path):
            return path
        return os.path.join(BASE_DIR, path)

    def _convert_source(self, url: str):
        """Convert URL to proper camera source (int if digit, string otherwise)."""
        if url.isdigit():
            return int(url)
        return url

    def _restart_camera(self, new_url: str):
        """Stop the current camera thread and start a new one with new_url."""
        print(f"[MainWindow] Restarting camera → {new_url}")
        self.camera.stop()
        
        # Wait for the camera thread to fully stop before starting a new one
        # This prevents FFmpeg assertion failures when rapidly switching cameras
        if self.camera.is_alive():
            self.camera.join(timeout=2.0)  # Wait up to 2 seconds for clean shutdown
        
        # Clear stale frames
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break

        # Convert source (int if digit, string otherwise)
        camera_source = self._convert_source(new_url)
        self.camera = CameraModule(source=camera_source, frame_queue=self.frame_queue)
        self.camera.start()
        # Connection status will be shown in update_ui() via the connection_start_time

    # ── ROI Dialog ─────────────────────────────────────────────────────────────

    def open_roi_dialog(self):
        """Open the ROI setup dialog with the latest frame snapshot."""
        if self._latest_frame is None:
            QMessageBox.information(
                self, "ROI Setup",
                "No camera frame available yet. Please wait for the stream to start."
            )
            return

        dlg = ROIDialog(
            snapshot=self._latest_frame,
            detector=self.detect,
            current_rois=self.detect.slot_rois,
            parent=self
        )
        if dlg.exec() == ROIDialog.Accepted:
            new_rois = dlg.get_rois()
            self.detect.slot_rois = new_rois
            self.save_rois(new_rois)
            QMessageBox.information(
                self, "ROI Updated",
                f"✅  {len(new_rois)} slot ROI(s) applied successfully."
            )

    def save_rois(self, rois: dict):
        """Persists ROI configuration to config_detector.json."""
        try:
            # Convert keys to string for JSON
            data_to_save = {str(k): v for k, v in rois.items()}
            file_path = os.path.join(BASE_DIR, "config_detector.json")
            with open(file_path, 'w') as f:
                json.dump(data_to_save, f, indent=4)
            print(f"[MainWindow] Configuration saved to config_detector.json")
        except Exception as e:
            print(f"[MainWindow] Save Error: {e}")
            QMessageBox.critical(self, "Save Error", f"Could not save ROIs: {e}")

    # ── UI Update Loop ─────────────────────────────────────────────────────────

    def update_ui(self):
        """Updates frame and sidebar information."""
        # 1. Connection Counter
        client_count = len(self.ws_server.clients)
        self.conn_label.setText(f"WEBSOCKET: {client_count} CLIENTS")

        # 2. Check Camera Connection Status
        if not self.camera.is_connected:
            # Camera is not connected - show status message
            elapsed = time.time() - self.camera.connection_start_time
            if elapsed >= self._connection_timeout:
                # Timeout reached - show connection failed
                self.video_label.setText("Connection Failed - Check camera URL")
            else:
                # Still trying to connect
                self.video_label.setText("Initializing System - Please wait...")
            self.slot_status_label.setText("Waiting for camera connection...")
            return  # Don't try to process frames if camera isn't connected

        # 3. Video + States (only if camera is connected)
        try:
            if not self.result_queue.empty():
                data = self.result_queue.get_nowait()
                frame = data.get('frame')
                states = data.get('slots', {})

                if frame is not None:
                    # Keep a snapshot for the ROI dialog 
                    # Use raw_frame if available (original resolution), otherwise fallback to frame
                    self._latest_frame = data.get('raw_frame', frame).copy()

                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_frame.shape
                    qimg = QImage(rgb_frame.data, w, h, ch * w,
                                  QImage.Format_RGB888).copy()
                    self.video_label.setPixmap(
                        QPixmap.fromImage(qimg).scaled(
                            self.video_label.size(),
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation
                        )
                    )

                # Update sidebar slot status
                status_text = ""
                for s_id, label in states.items():
                    color = "#a6e3a1" if label == "Empty" else "#f38ba8"
                    status_text += (
                        f"SLOT {s_id}: "
                        f"<span style='color:{color};'>{label.upper()}</span><br>"
                    )
                self.slot_status_label.setText(status_text or "No detections.")

        except Exception as e:
            print(f"[MainWindow] Error in update_ui: {e}")
            pass

    # ── Shutdown ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self.camera.stop()
        self.detect.stop()
        self.ws_server.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())