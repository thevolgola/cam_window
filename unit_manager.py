import queue
from typing import Dict, List, Optional

from camera import CameraModule
from detect import YOLODetector

class CameraUnit:
    """Encapsulates a single camera stream and its dedicated AI detector."""
    
    def __init__(self, cam_id: str, url: str, model_path: str = ""):
        self.cam_id = str(cam_id)
        self.url = url
        self.model_path = model_path
        
        # Dedicated queues for this unit
        self.frame_queue = queue.Queue(maxsize=1)
        self.result_queue = queue.Queue(maxsize=1)
        
        # Instantiate modules
        self.camera = CameraModule(source=self.url, frame_queue=self.frame_queue)
        
        # Detector needs special initialization depending on if model is provided
        self.detect = YOLODetector(
            frame_queue=self.frame_queue,
            result_queue=self.result_queue,
            model_path=self.model_path
        )
        
        # Inject the cam_id into the detector so results are identifiable
        self.detect.cam_id = self.cam_id

    def set_detection_enabled(self, enabled: bool):
        """Enable or disable AI detection for this specific camera."""
        if hasattr(self.detect, 'enabled'):
            self.detect.enabled = enabled

    def set_model(self, model_path: str):
        """Change the AI model for this camera."""
        self.model_path = model_path
        self.detect.change_model(model_path)

    def request_camera_refresh(self) -> tuple[bool, str]:
        """Request one debounced manual camera reconnect attempt."""
        return self.camera.request_refresh()

    def set_rois(self, rois: dict):
        """Set the Region of Interest bounding boxes for this camera."""
        with self.detect.lock:
            self.detect.slot_rois = rois

    def get_latest_result(self) -> Optional[dict]:
        """Poll the result queue. Returns None if empty."""
        try:
            return self.result_queue.get_nowait()
        except queue.Empty:
            return None

    def start(self):
        """Start both the camera and detection threads."""
        self.camera.start()
        self.detect.start()

    def stop(self):
        """Stop threads and clean up."""
        self.camera.stop()
        self.detect.stop()
        
        # Wait for threads to exit locally to prevent hangs
        self.camera.join(timeout=2.0)
        self.detect.join(timeout=2.0)
        
        # Flush queues
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break
                
        while not self.result_queue.empty():
            try:
                self.result_queue.get_nowait()
            except queue.Empty:
                break


class UnitManager:
    """Orchestrates multiple CameraUnits."""
    
    def __init__(self):
        # Map of cam_id (string) to CameraUnit instances
        self.units: Dict[str, CameraUnit] = {}

    def sync_cameras(self, camera_configs: List[dict]):
        """
        Synchronize the running units with the provided configuration list.
        Starts new cameras, stops removed ones, and updates models for existing.
        `camera_configs` format: [{'id': 1, 'url': '...', 'model': '...'}, ...]
        """
        active_ids = []
        
        for cam_data in camera_configs:
            cam_id = str(cam_data.get('id', ''))
            url = cam_data.get('url', '')
            model = cam_data.get('model', '')
            
            if not cam_id or not url:
                continue
                
            active_ids.append(cam_id)
            
            if cam_id in self.units:
                # Update existing unit if model changed
                unit = self.units[cam_id]
                if unit.url != url:
                    # If URL changed, we must recreate the unit
                    print(f"[UnitManager] URL changed for camera {cam_id}, recreating.")
                    self.remove_unit(cam_id)
                    self.add_unit(cam_id, url, model)
                elif unit.model_path != model:
                    print(f"[UnitManager] Updating model for camera {cam_id}")
                    unit.set_model(model)
            else:
                # Create new unit
                print(f"[UnitManager] Starting new camera unit {cam_id}")
                self.add_unit(cam_id, url, model)
                
        # Remove units that are no longer in the config
        current_ids = list(self.units.keys())
        for cid in current_ids:
            if cid not in active_ids:
                print(f"[UnitManager] Stopping removed camera unit {cid}")
                self.remove_unit(cid)

    def add_unit(self, cam_id: str, url: str, model_path: str = ""):
        """Create and start a new camera unit."""
        if cam_id in self.units:
            return
            
        unit = CameraUnit(cam_id, url, model_path)
        self.units[cam_id] = unit
        unit.start()

    def remove_unit(self, cam_id: str):
        """Stop and remove a camera unit."""
        if cam_id in self.units:
            self.units[cam_id].stop()
            del self.units[cam_id]

    def get_unit(self, cam_id: str) -> Optional[CameraUnit]:
        """Retrieve a specific unit."""
        return self.units.get(str(cam_id))
        
    def get_all_active_ids(self) -> List[str]:
        """Return a list of all currently active camera IDs."""
        return list(self.units.keys())

    def apply_rois(self, rois_config: dict):
        """
        Apply ROIs to all units.
        `rois_config` format: {"cam_id": {"slot_id": [x,y,w,h], ...}}
        """
        for cam_id, unit in self.units.items():
            cam_rois = rois_config.get(cam_id, {})
            unit.set_rois(cam_rois)

    def get_all_results(self) -> Dict[str, dict]:
        """
        Poll all units for new frames and detection results.
        Returns a dictionary mapping cam_id to result dicts.
        """
        results = {}
        for cam_id, unit in self.units.items():
            res = unit.get_latest_result()
            if res:
                results[cam_id] = res
        return results
        
    def get_all_slot_states(self) -> dict:
        """
        Aggregates slot states from all active units.
        Useful for broadcasting to WebSocket.
        """
        all_states = {}
        for cam_id, unit in self.units.items():
            with unit.detect.lock:
                # Merge dictionaries
                all_states.update(unit.detect.slot_states.copy())
        return all_states

    def stop_all(self):
        """Stop all running units."""
        for cam_id, unit in self.units.items():
            unit.stop()
        self.units.clear()
