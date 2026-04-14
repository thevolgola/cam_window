import re

with open('mainwindow.py', 'r') as f:
    text = f.read()

# Replace update_ui
start_idx = text.find('    def update_ui(self):')
end_idx = text.find('    def _create_placeholder_pixmap', start_idx)

# If _create_placeholder_pixmap is not found, try to find the next function
if end_idx == -1:
    end_idx = text.find('    def _update_sidebar_slots', start_idx)

new_update_ui = """    def update_ui(self):
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

"""

if start_idx != -1 and end_idx != -1:
    text = text[:start_idx] + new_update_ui + text[end_idx:]
    with open('mainwindow.py', 'w') as f:
        f.write(text)
    print("Replaced update_ui")
else:
    print(f"Could not find bounds for update_ui: {start_idx}, {end_idx}")

