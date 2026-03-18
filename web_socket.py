import asyncio
import websockets
import json
import threading
import os
from datetime import datetime

class WebSocketModule(threading.Thread):
    def __init__(self, host="0.0.0.0", port=8765,
                 log_file=None,
                 max_log_size_mb=10):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        # Set default log file path relative to this file
        if log_file is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            log_file = os.path.join(os.path.dirname(base_dir), "log", "detection_log.json")
        self.log_file = log_file
        self.max_log_size = max_log_size_mb * 1024 * 1024  # Convert MB to bytes
        self.loop = None
        self.clients = set()

        # Ensure directory exists
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)

    def _manage_log_size(self):
        """Strictly controls the log file size to prevent disk overflow."""
        try:
            if os.path.exists(self.log_file):
                if os.path.getsize(self.log_file) > self.max_log_size:
                    backup_file = self.log_file + ".old"
                    # Remove the previous backup to make room
                    if os.path.exists(backup_file):
                        os.remove(backup_file)
                    # ROTATE: Current becomes the backup
                    os.rename(self.log_file, backup_file)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] LOG ROTATION: Moved to .old")
        except Exception as e:
            print(f"Log Rotation Error: {e}")

    async def handler(self, websocket):
        self.clients.add(websocket)
        print(f"Robot Server connected. Active clients: {len(self.clients)}")
        try:
            await websocket.wait_closed()
        finally:
            if websocket in self.clients:
                self.clients.remove(websocket)
            print(f"Robot Server disconnected. Active clients: {len(self.clients)}")

    def send_data_to_all(self, slot_states):
        """
        Receives data from YOLODetector and broadcasts to the robot server.
        Transforms raw labels into robot-ready 'states'.
        """
        if not self.loop:
            return

        object_list = []
        for slot_id, label in slot_states.items():
            current_label = str(label).strip().lower()

            # Mapping logic for Robot decision making
            if current_label == "empty":
                state = "empty"      # Action: Robot can place a car
            elif current_label == "unknown" or current_label == "fail":
                state = "unknown"    # Action: Robot must stop (Obstacle/Error)
            else:
                state = "occupied"   # Action: Robot can take the car

            obj = {
                "id": int(slot_id),
                "state": state,
                "label": label  # Keeps raw label (Car Full / Car Empty) for logging
            }
            object_list.append(obj)

        # Package payload with ISO timestamp
        payload = {
            "timestamp": datetime.now().isoformat(),
            "total_slots": len(object_list),
            "objects": object_list
        }
        message = json.dumps(payload)

        # Log management and persistent writing
        self._manage_log_size()
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(message + "\n")
        except Exception as e:
            print(f"Logging error: {e}")

        # Broadcast to all connected servers/robots
        if self.clients:
            for client in list(self.clients):
                try:
                    # Thread-safe scheduling for the asyncio loop
                    asyncio.run_coroutine_threadsafe(client.send(message), self.loop)
                except Exception as e:
                    print(f"Error broadcasting to robot: {e}")

    async def main(self):
        async with websockets.serve(self.handler, self.host, self.port):
            await asyncio.Future()  # Keep server running

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.main())

    def stop(self):
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)