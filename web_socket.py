import json
import os
import threading
import asyncio
from datetime import datetime

import websockets

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
        self.server = None
        self.stop_event = None
        self._stopping = threading.Event()

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

    def send_data_to_all(self, camera_results):
        """
        Receives detection results from all camera units and broadcasts
        a payload containing camera_id, slot_id, and derived state.
        """
        if not self.loop or self._stopping.is_set():
            return

        object_list = []
        for camera_id, result in camera_results.items():
            slots = result.get("slots", {}) if isinstance(result, dict) else {}
            for slot_id, label in slots.items():
                state = label

                formatted_slot_id = int(slot_id) if isinstance(slot_id, str) and slot_id.isdigit() else slot_id
                formatted_camera_id = int(camera_id) if isinstance(camera_id, str) and camera_id.isdigit() else camera_id

                obj = {
                    "camera_id": formatted_camera_id,
                    "slot_id": formatted_slot_id,
                    "state": state,
                }
                object_list.append(obj)

        # Package payload with ISO timestamp
        payload = {
            "timestamp": datetime.now().isoformat(),
            "total_slots": len(object_list),
            "slots": object_list,
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
        self.stop_event = asyncio.Event()
        async with websockets.serve(self.handler, self.host, self.port) as server:
            self.server = server
            await self.stop_event.wait()

        if self.clients:
            await asyncio.gather(
                *(client.close() for client in list(self.clients)),
                return_exceptions=True,
            )

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.main())
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
        except Exception as e:
            print(f"[WebSocketModule] Server stopped with error: {e}")
        finally:
            self.server = None
            self.stop_event = None
            self.loop.close()
            self.loop = None

    def stop(self):
        self._stopping.set()
        if self.loop and not self.loop.is_closed() and self.stop_event:
            self.loop.call_soon_threadsafe(self.stop_event.set)
