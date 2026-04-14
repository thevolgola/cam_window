import re

with open('mainwindow.py', 'r') as f:
    text = f.read()

# Replace save_rois
old_save = """    def save_rois(self, rois: dict):
        \"\"\"Persists ROI configuration to config_detector.json.\"\"\"
        try:
            # Convert keys to string for JSON
            data_to_save = {str(k): v for k, v in rois.items()}
            file_path = os.path.join(BASE_DIR, "config_detector.json")
            with open(file_path, 'w') as f:
                json.dump(data_to_save, f, indent=4)
            print(f"[MainWindow] Configuration saved to config_detector.json")
        except Exception as e:
            print(f"[MainWindow] Save Error: {e}")
            QMessageBox.critical(self, "Save Error", f"Could not save ROIs: {e}")"""

new_save = """    def save_rois(self, silent=False):
        \"\"\"Save the ROIs extracted from all active detectors.\"\"\"
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
            print(f"[MainWindow] Configuration saved to config_detector.json")
            if not silent:
                QMessageBox.information(self, "Saved", "All Region of Interests have been saved.")
        except Exception as e:
            print(f"[MainWindow] Save Error: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save ROI settings: {e}")

    def load_rois(self):
        \"\"\"Load ROIs from config and push strictly to UnitManager.\"\"\"
        try:
            file_path = os.path.join(BASE_DIR, "config_detector.json")
            with open(file_path, "r") as f:
                config = json.load(f)
                
                # Check if it's legacy single-camera format or multi-camera
                if "parking_slots" in config:
                    print("[MainWindow] Migrating legacy config format to multi-camera...")
                    legacy_rois = config["parking_slots"]
                    active = self.active_camera_id if self.active_camera_id else "1"
                    config = {active: legacy_rois}
                    # Save the migrated config immediately
                    with open(file_path, "w") as f2:
                        json.dump(config, f2, indent=4)
                elif any(isinstance(v, list) for v in config.values()): 
                    # Another possible legacy format where root is slot IDs
                    print("[MainWindow] Migrating raw dict config format to multi-camera...")
                    active = self.active_camera_id if self.active_camera_id else "1"
                    config = {active: config}
                
                self.unit_manager.apply_rois(config)
        except (FileNotFoundError, json.JSONDecodeError):
            print("[MainWindow] No valid ROI config found.")"""

text = text.replace(old_save, new_save)

# Replace update_ui entirely
old_update = """    def update_ui(self):
        \"\"\"Updates frame and sidebar information.\"\"\"
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
            pass"""

new_update = """    def update_ui(self):
        \"\"\"Timer callback loop that updates all camera views and broadcasts to WebSocket.\"\"\"
        # 1. Update system status
        clients_count = len(self.ws_server.clients)
        self.conn_label.setText(f"WEBSOCKET: {clients_count} CLIENTS")
        
        # 2. Get results from all camera units
        results = self.unit_manager.get_all_results()
        
        # Update connection statuses if a unit didn't produce a new frame
        for cam_id, unit in self.unit_manager.units.items():
            if not unit.camera.is_connected:
                # Need to show a disconnected placeholder
                placeholder = self._create_placeholder_pixmap("Connecting or Offline...", 640, 480)
                
                # Update Grid
                if self.grid_mode and cam_id in self.grid_video_labels:
                    grid_lbl = self.grid_video_labels[cam_id]
                    scaled = placeholder.scaled(grid_lbl.width(), grid_lbl.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    grid_lbl.setPixmap(scaled)
                    
                # Update Single View (if focused)
                if not self.grid_mode and cam_id == self.active_camera_id:
                    self.single_video_label.setPixmap(placeholder)
                    self.single_video_label.setText("")

        # 3. Process new frames and states
        for cam_id, res in results.items():
            frame_rgb = res["frame"]
            raw_frame = res["raw_frame"]
            
            # Convert OpenCV frame to Qt Pixmap
            h, w, ch = frame_rgb.shape
            bytes_per_line = ch * w
            img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(img)
            
            # --- Render into Grid View ---
            if self.grid_mode and cam_id in self.grid_video_labels:
                lbl = self.grid_video_labels[cam_id]
                scaled_pixmap = pixmap.scaled(lbl.width(), lbl.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                lbl.setPixmap(scaled_pixmap)
                
            # --- Render into Single View ---
            if not self.grid_mode and cam_id == self.active_camera_id:
                self._focused_raw_frame = raw_frame
                scaled_pixmap = pixmap.scaled(self.single_video_label.width(), self.single_video_label.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.single_video_label.setPixmap(scaled_pixmap)
                
                # Update the side panel slots using THIS camera's detection results
                self._update_sidebar_slots(res["slots"])
        
        # 4. Global Broadcast via WebSocket
        merged_states = self.unit_manager.get_all_slot_states()
        self.ws_server.send_data_to_all(merged_states)
        
    def _create_placeholder_pixmap(self, text, w, h) -> QPixmap:
        \"\"\"Draws a simple placeholder frame if the stream drops.\"\"\"
        from PySide6.QtGui import QPainter, QColor
        pixmap = QPixmap(w, h)
        pixmap.fill(QColor("#11111b"))
        painter = QPainter(pixmap)
        painter.setPen(QColor("#a6adc8"))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
        painter.end()
        return pixmap

    def _update_sidebar_slots(self, slots_data: dict):
        \"\"\"Updates the sidebar parking layout purely visually.\"\"\"
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
            self.slots_layout.addWidget(row)"""

text = text.replace(old_update, new_update)

# Replace shutdown
old_shutdown = """    def closeEvent(self, event):
        \"\"\"Application exit logic.\"\"\"
        print("[MainWindow] Exiting system.")
        self.timer.stop()
        self.camera.stop()
        self.detect.stop()
        self.ws_server.stop()
        
        # Wait up to 2 seconds for threads
        self.camera.join(timeout=2.0)
        self.detect.join(timeout=2.0)
        
        self.ws_server.join(timeout=2.0)
        event.accept()"""

new_shutdown = """    def closeEvent(self, event):
        \"\"\"Cleanup handler when app closes.\"\"\"
        print("[MainWindow] Shutting down...")
        self.timer.stop()
        self.unit_manager.stop_all()
        self.ws_server.stop()
        event.accept()"""

text = text.replace(old_shutdown, new_shutdown)

with open('mainwindow.py', 'w') as f:
    f.write(text)
print("Finished patching update_ui, save_rois, load_rois, closeEvent.")
