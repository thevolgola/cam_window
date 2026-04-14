import re

with open('mainwindow.py', 'r') as f:
    code = f.read()

# Replace settings and ROI methods
old_methods = """    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self._app_settings = dialog.get_settings()
            # Reset WebSocket if port changed
            ws_cfg = self._app_settings.get("websocket", {})
            # We don't dynamically restart WS in this basic version, requires more robust thread handling
            
            # Re-init current camera if possible
            cameras = self._app_settings.get("cameras", [])
            # Fix index out of bounds if cameras were deleted
            if self._current_camera_idx >= len(cameras):
                self._current_camera_idx = max(0, len(cameras) - 1)
                
            new_url = self._get_camera_url(self._current_camera_idx)
            new_model = self._resolve_model_path(self._get_camera_model(self._current_camera_idx))
            
            self._restart_camera(new_url)
            self.detect.change_model(new_model)
            self._refresh_url_label()
            self._refresh_cam_status_label()

            if self._showing_camera_list:
                self._build_camera_grid()

    def open_roi_dialog(self):
        if self._latest_frame is None:
            QMessageBox.warning(self, "No Frame", "Please wait for camera stream before opening ROI config.")
            return

        dialog = ROIDialog(self._latest_frame, self.detect, self.detect.slot_rois.copy(), self)
        if dialog.exec() == QDialog.Accepted:
            self.detect.slot_rois = dialog.get_rois()
            # Save specifically to config_detector.json
            dialog.save_rois_to_file(self.detect.slot_rois)"""

new_methods = """    def open_settings(self):
        \"\"\"Open settings dialog and sync changes with the UnitManager.\"\"\"
        dialog = SettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self._app_settings = dialog.get_settings()
            
            # Restart WS server with new port if changed
            ws_cfg = self._app_settings.get("websocket", {})
            self.ws_server.stop()
            self.ws_server = WebSocketModule(
                host=ws_cfg.get("host", "0.0.0.0"),
                port=ws_cfg.get("port", 8765)
            )
            self.ws_server.start()

            # Sync units
            cameras_config = self._app_settings.get("cameras", [])
            self.unit_manager.sync_cameras(cameras_config)
            
            # Refresh UI
            if self.grid_mode:
                self._build_camera_grid()
                
            # Keep active camera valid
            active_ids = self.unit_manager.get_all_active_ids()
            if self.active_camera_id not in active_ids and active_ids:
                self._select_camera(active_ids[0])
            else:
                self._refresh_cam_status_label()

    def open_roi_dialog(self):
        \"\"\"Open ROI configuration only for the actively focused camera.\"\"\"
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
        if dialog.exec() == QDialog.Accepted:
            new_rois = dialog.get_rois()
            with unit.detect.lock:
                unit.detect.slot_rois = new_rois
            self.save_rois(silent=True)"""

if old_methods in code:
    code = code.replace(old_methods, new_methods)
    print("Successfully patched settings & ROI.")
else:
    print("Old settings/ROI logic not found. Trying regex.")
    
with open('mainwindow.py', 'w') as f:
    f.write(code)
