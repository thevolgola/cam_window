import threading
import time
from ultralytics import YOLO
import cv2
import queue
import torch

class YOLODetector(threading.Thread):
    def __init__(self, frame_queue, result_queue, model_path="best.pt", detect_interval=0.25):
        super().__init__(daemon=True)
        self.frame_queue = frame_queue
        self.result_queue = result_queue
        
        # --- PORTABILITY & HARDWARE ---
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.model = None
        self.model_loaded = False
        
        if model_path:
            try:
                self.model = YOLO(model_path)
                self.model.to(self.device)
                self.model_loaded = True
                print(f"AI Engine: Running on {self.device.upper()} with model {model_path}")
            except Exception as e:
                print(f"AI Engine Error: Could not load model {model_path}: {e}")
        else:
            print("AI Engine: No model path provided.")

        self.slot_rois: dict[int, list] = {}
        self.slot_states: dict[int, str] = {}
        self.lock = threading.Lock()

        # Your 4 Trained Classes Color Mapping
        self.STATE_COLORS = {
            "Empty": (0, 255, 0),        # Green (Layout clear)
            "Car Empty": (0, 255, 255),  # Yellow (Car present, no goods)
            "Car Full": (0, 0, 255),     # Red (Car present + goods)
            "Unknown": (128, 128, 128)   # Grey (Obstacle or Error)
        }

        self.detect_interval = detect_interval
        self.last_detect_time = 0.0
        self.running = threading.Event()
        self.running.set()
        self.enabled = False  # NEW: Detection toggle
        self.ws_module = None

    def run(self):
        while self.running.is_set():
            try:
                # 1. Pull Frame
                raw_frame = self.frame_queue.get(timeout=2)
                
                h_raw, w_raw = raw_frame.shape[:2]
                midpoint = w_raw // 2 

                # Setup Display Scaling (640x480 for UI)
                display_frame = cv2.resize(raw_frame, (640, 480))
                scale_x, scale_y = 640 / w_raw, 480 / h_raw

                # Only run AI if enabled and model is loaded
                if self.enabled and self.model_loaded and self.model is not None:
                    now = time.time()
                    if now - self.last_detect_time >= self.detect_interval:
                        self.last_detect_time = now

                        # --- GLOBAL INFERENCE (Looks at whole layout) ---
                        results = self.model(raw_frame, imgsz=640, conf=0.3, verbose=False)
                        
                        found_detections = []
                        for r in results:
                            for box in r.boxes:
                                coords = box.xyxy[0].tolist() # [x1, y1, x2, y2]
                                label = self.model.names[int(box.cls)]
                                conf = float(box.conf)
                                
                                # Center Point of Object
                                cx = (coords[0] + coords[2]) / 2
                                cy = (coords[1] + coords[3]) / 2
                                
                                found_detections.append({
                                    'coords': coords,
                                    'center': (cx, cy),
                                    'label': label,
                                    'conf': conf
                                })

                        with self.lock:
                            if not self.slot_rois:
                                # --- CALIBRATION MODE ---
                                # Detects your layout or cars to set the ROIs
                                for det in found_detections:
                                    s_id = 1 if det['center'][0] < midpoint else 2
                                    self.slot_rois[s_id] = [int(x) for x in det['coords']]
                                    self.slot_states[s_id] = det['label']
                            else:
                                # --- MONITORING MODE (Logic for 4 Classes) ---
                                new_states = {sid: "Unknown" for sid in self.slot_rois.keys()}

                                for slot_id, (sx1, sy1, sx2, sy2) in self.slot_rois.items():
                                    # Get all items inside this slot area
                                    in_slot = [d for d in found_detections if sx1 <= d['center'][0] <= sx2 and sy1 <= d['center'][1] <= sy2]

                                    if in_slot:
                                        # Sort by highest confidence
                                        in_slot.sort(key=lambda x: x['conf'], reverse=True)
                                        
                                        # PRIORITY: If AI sees 'Car' and 'Empty' layout together, Car takes priority
                                        car_hit = next((d for d in in_slot if "Car" in d['label']), None)
                                        
                                        final_label = car_hit['label'] if car_hit else in_slot[0]['label']

                                        # Explicit Comparison for your 4 Classes
                                        if final_label == "Car Full":
                                            new_states[slot_id] = "Car Full"
                                        elif final_label == "Car Empty":
                                            new_states[slot_id] = "Car Empty"
                                        elif final_label == "Empty":
                                            new_states[slot_id] = "Empty"
                                        elif final_label == "Unknown":
                                            new_states[slot_id] = "Unknown"
                                        else:
                                            new_states[slot_id] = "Unknown"
                                    else:
                                        # Nothing detected in this box (AI is blind here)
                                        new_states[slot_id] = "Unknown"

                                self.slot_states = new_states

                # --- DRAWING & OUTPUT ---
                current_states = self.get_states()
                if self.slot_rois:
                    for slot_id, coords in self.slot_rois.items():
                        state = current_states.get(slot_id, "Unknown")
                        color = self.STATE_COLORS.get(state, (128, 128, 128))

                        # Scaling ROI back to display size
                        dx1, dy1 = int(coords[0] * scale_x), int(coords[1] * scale_y)
                        dx2, dy2 = int(coords[2] * scale_x), int(coords[3] * scale_y)

                        cv2.rectangle(display_frame, (dx1, dy1), (dx2, dy2), color, 2)
                        cv2.putText(display_frame, f"Slot {slot_id}: {state}", (dx1, dy1 - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                # Send to Robot
                if self.ws_module:
                    self.ws_module.send_data_to_all(current_states)

                # Send to UI
                if not self.result_queue.full():
                    self.result_queue.put({
                        "frame": display_frame, 
                        "raw_frame": raw_frame,
                        "slots": current_states
                    })

            except queue.Empty:
                continue
            except Exception as e:
                print(f"DETECTOR ERROR: {e}")

    def get_states(self):
        with self.lock:
            return self.slot_states.copy()

    def change_model(self, model_path: str):
        """Update the YOLO model on the fly."""
        with self.lock:
            if not model_path:
                self.model = None
                self.model_loaded = False
                print("[Detector] Model cleared.")
                return

            try:
                self.model = YOLO(model_path)
                self.model.to(self.device)
                self.model_loaded = True
                print(f"[Detector] Model switched to: {model_path}")
            except Exception as e:
                print(f"[Detector] Error switching model: {e}")
                self.model = None
                self.model_loaded = False

    def stop(self):
        self.running.clear()