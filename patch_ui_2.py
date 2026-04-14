import re

with open('mainwindow.py', 'r') as f:
    code = f.read()

# Replace the camera switching and UI update logic
old_logic = """    # ── Camera Switching ───────────────────────────────────────────────

    def _build_camera_grid(self):
        # Clear existing
        while self.camera_grid_layout.count():
            item = self.camera_grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        cameras = self._app_settings.get("cameras", [])
        
        if not cameras:
            lbl = QLabel("No cameras configured. Open Settings to add.")
            lbl.setStyleSheet("color: #a6adc8;")
            self.camera_grid_layout.addWidget(lbl, 0, 0)
            return

        cols = 2
        for i, cam in enumerate(cameras):
            btn = QPushButton(f"{cam.get('name', 'Cam ' + str(i+1))}\\n{cam.get('url', '')}")
            btn.setMinimumHeight(100)
            
            if i == self._current_camera_idx:
                btn.setStyleSheet(\"\"\"
                    background-color: #a6e3a1; color: #11111b; font-weight: bold;
                    border-radius: 6px; padding: 10px; text-align: left;
                \"\"\")
            else:
                btn.setStyleSheet(\"\"\"
                    background-color: #313244; color: #cdd6f4;
                    border-radius: 6px; padding: 10px; text-align: left;
                \"\"\")
                btn.clicked.connect(lambda checked, idx=i: self._select_camera(idx))

            row = i // cols
            col = i % cols
            self.camera_grid_layout.addWidget(btn, row, col)

    def _toggle_camera_list(self):
        self._showing_camera_list = not self._showing_camera_list
        if self._showing_camera_list:
            self.video_label.hide()
            self._build_camera_grid()
            self.camera_grid_container.show()
            self.btn_cameras.setText("🔙 BACK TO CAMERA VIEW")
            self.btn_cameras.setStyleSheet(
                "background-color: #f38ba8; color: #11111b; font-weight: bold; padding: 10px;"
            )
        else:
            self.camera_grid_container.hide()
            self.video_label.show()
            self.btn_cameras.setText("📹 VIEW ALL CAMERAS")
            self.btn_cameras.setStyleSheet(
                "background-color: #fab387; color: #11111b; font-weight: bold; padding: 10px;"
            )
            self._refresh_cam_status_label()

    def _select_camera(self, idx):
        print(f"[MainWindow] Switching to camera index {idx}")
        self._previous_camera_idx = self._current_camera_idx
        self._current_camera_idx = idx
        
        # Determine URL and Model
        new_url = self._get_camera_url(idx)
        new_model = self._resolve_model_path(self._get_camera_model(idx))
        
        # Restart camera thread
        self._restart_camera(new_url)
        
        # Update YOLO model dynamically
        self.detect.change_model(new_model)
        
        self._refresh_url_label()
        self._refresh_cam_status_label()
        
        if self._showing_camera_list:
            self._toggle_camera_list() # Hide grid and return to single view

    def _refresh_url_label(self):
        url = self._get_camera_url(self._current_camera_idx)
        # Obfuscate if it's a long RTSP string for cleaner UI
        if url.startswith("rtsp://") and len(url) > 30:
             # Basic obfuscation for display
             parts = url.split('@')
             if len(parts) > 1:
                 safe_url = f"rtsp://***@{parts[-1]}"
             else:
                 safe_url = url[:25] + "..."
             self.cam_url_label.setText(f"URL: {safe_url}")
        else:
             self.cam_url_label.setText(f"URL: {url}")

    def _refresh_cam_status_label(self):
        cam_name = "Camera"
        model_name = "No Model"
        
        cameras = self._app_settings.get("cameras", [])
        if cameras and self._current_camera_idx < len(cameras):
            cam = cameras[self._current_camera_idx]
            cam_name = cam.get("name", f"Cam {self._current_camera_idx+1}")
            model_path = self._get_camera_model(self._current_camera_idx)
            if model_path:
                model_name = os.path.basename(model_path)
            else:
                model_name = "No AI Model (Raw Feed)"
                
        self.cam_status_label.setText(f"Active Camera: {cam_name}\\nModel: {model_name}")

    # ── Action Handlers ────────────────────────────────────────────────────────

    def _toggle_detection(self):
        self._detection_enabled = self.btn_detect.isChecked()
        self.detect.enabled = self._detection_enabled
        if self._detection_enabled:
            self.btn_detect.setText("▶ DETECTION: ON")
            self.btn_detect.setStyleSheet(
                "background-color: #a6e3a1; color: #11111b; font-weight: bold; padding: 10px;"
            )
        else:
            self.btn_detect.setText("⏸ DETECTION: OFF")
            self.btn_detect.setStyleSheet(
                "background-color: #f38ba8; color: #11111b; font-weight: bold; padding: 10px;"
            )"""

new_logic = """    # ── Camera Switching ───────────────────────────────────────────────

    def _build_camera_grid(self):
        \"\"\"Build the grid view showing live feeds of all cameras.\"\"\"
        # Clear existing grid
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
            
            # Container for one camera in the grid
            cam_container = QFrame()
            cam_container.setStyleSheet(\"\"\"
                QFrame { background-color: #1e1e2e; border: 2px solid #313244; border-radius: 4px; }
                QFrame:hover { border: 2px solid #89b4fa; }
            \"\"\")
            clayout = QVBoxLayout(cam_container)
            clayout.setContentsMargins(5, 5, 5, 5)
            
            # Title
            title_lbl = QLabel(name)
            title_lbl.setStyleSheet("color: #cdd6f4; font-weight: bold; border: none;")
            title_lbl.setAlignment(Qt.AlignCenter)
            clayout.addWidget(title_lbl)
            
            # The actual video label
            video_lbl = QLabel("Connecting...")
            video_lbl.setAlignment(Qt.AlignCenter)
            video_lbl.setStyleSheet("background-color: #11111b; border: none;")
            video_lbl.setMinimumSize(320, 240)
            clayout.addWidget(video_lbl)
            
            # Store ref so update_ui can push frames to it
            self.grid_video_labels[cam_id] = video_lbl
            
            # Clickable overlay button to switch to single view
            btn = QPushButton("Focus")
            btn.setStyleSheet(\"\"\"
                background-color: #89b4fa; color: #11111b; font-weight: bold;
                padding: 4px; border-radius: 2px;
            \"\"\")
            btn.clicked.connect(lambda checked, cid=cam_id: self._select_camera(str(cid)))
            clayout.addWidget(btn)

            row = i // cols
            col = i % cols
            self.grid_layout.addWidget(cam_container, row, col)

    def _toggle_camera_list(self):
        \"\"\"Toggle between single view and grid view.\"\"\"
        self.grid_mode = not self.grid_mode
        if self.grid_mode:
            self._build_camera_grid()
            self.video_stack.setCurrentIndex(1)
            self.cam_title.setText("All Cameras Overview")
            self.btn_cameras.setText("🔙 SINGLE CAMERA VIEW")
            self.btn_cameras.setStyleSheet("background-color: #f38ba8; color: #11111b; font-weight: bold; font-size: 14px; padding: 10px;")
            
            # Disable slot-specific buttons in overview
            self.btn_detect.setEnabled(False)
            self.btn_roi.setEnabled(False)
        else:
            self.video_stack.setCurrentIndex(0)
            self.btn_cameras.setText("�� VIEW ALL CAMERAS")
            self.btn_cameras.setStyleSheet("background-color: #89b4fa; color: #11111b; font-weight: bold; font-size: 14px; padding: 10px;")
            
            self.btn_detect.setEnabled(True)
            self.btn_roi.setEnabled(True)
            self._refresh_cam_status_label()

    def _select_camera(self, cam_id: str):
        \"\"\"Set the active camera for the single view mode.\"\"\"
        self.active_camera_id = cam_id
        
        # Switch out of grid mode if we were in it
        if self.grid_mode:
            self._toggle_camera_list()
            
        self._refresh_cam_status_label()
        
        # Refresh detection toggle state for this unit
        unit = self.unit_manager.get_unit(cam_id)
        if unit:
            enabled = unit.detect.enabled
            if enabled:
                self.btn_detect.setText("🟢 AI DETECTION IS ON")
                self.btn_detect.setStyleSheet("background-color: #a6e3a1; color: #11111b; font-weight: bold; font-size: 14px; padding: 10px;")
            else:
                self.btn_detect.setText("🔴 AI DETECTION IS OFF")
                self.btn_detect.setStyleSheet("background-color: #f38ba8; color: #11111b; font-weight: bold; font-size: 14px; padding: 10px;")

    def _refresh_cam_status_label(self):
        \"\"\"Update the sidebar title with currently focused camera info.\"\"\"
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
            model_name = model.split("/")[-1] if model else "No Model (Raw Feed)"
            
            self.cam_title.setText(f"📹 {name}")
            self.cam_status_label.setText(f"Camera: {name}\\nModel: {model_name}")
            
    # ── Action Handlers ────────────────────────────────────────────────

    def _toggle_detection(self):
        \"\"\"Toggle AI detection only for the actively focused camera.\"\"\"
        if not self.active_camera_id:
            return
            
        unit = self.unit_manager.get_unit(self.active_camera_id)
        if not unit:
            return
            
        new_state = not unit.detect.enabled
        unit.set_detection_enabled(new_state)
        
        if new_state:
            self.btn_detect.setText("🟢 AI DETECTION IS ON")
            self.btn_detect.setStyleSheet("background-color: #a6e3a1; color: #11111b; font-weight: bold; font-size: 14px; padding: 10px;")
        else:
            self.btn_detect.setText("🔴 AI DETECTION IS OFF")
            self.btn_detect.setStyleSheet("background-color: #f38ba8; color: #11111b; font-weight: bold; font-size: 14px; padding: 10px;")"""

if old_logic in code:
    code = code.replace(old_logic, new_logic)
    print("Successfully patched UI definitions.")
else:
    print("Old logic not found. Trying regex.")
    
with open('mainwindow.py', 'w') as f:
    f.write(code)
