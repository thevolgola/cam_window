import queue
import cv2
import asyncio
import websockets
import json
import threading

from camera import CameraReader
from detect import YOLODetector

# WebSocket client chạy trong thread riêng
class WSClient(threading.Thread):
    def __init__(self, detector, uri="ws://localhost:8765"):
        super().__init__(daemon=True)
        self.detector = detector
        self.uri = uri
        self.running = True

    async def send_loop(self):
        async with websockets.connect(self.uri) as websocket:
            while self.running:
                # Lấy trạng thái slot từ detector
                states = self.detector.get_states()
                data = {"slots": states}
                await websocket.send(json.dumps(data))

                # Nhận phản hồi từ server
                try:
                    reply = await websocket.recv()
                    print("Server reply:", reply)
                except Exception as e:
                    print("WebSocket error:", e)

                await asyncio.sleep(1)  # gửi mỗi giây

    def run(self):
        asyncio.run(self.send_loop())

    def stop(self):
        self.running = False


def main():
    frame_queue = queue.Queue(maxsize=10)
    result_queue = queue.Queue(maxsize=10)

    # Camera và Detector
    cam = CameraReader("rtsp://admin:rtc%402025@192.168.5.110:554/Streaming/Channels/101", frame_queue)  
    base_dir = os.path.dirname(os.path.abspath(__file__))
    weights_path = os.path.join(base_dir, "best.pt")
    det = YOLODetector(frame_queue, result_queue, weights_path)

    cam.start()
    det.start()

    # WebSocket client
    ws_client = WSClient(det)
    ws_client.start()

    while True:
        if not result_queue.empty():
            result = result_queue.get()
            annotated_frame = result["frame"]
            slots = result["slots"]

            # Hiển thị video
            cv2.imshow("YOLO Detector + WS Client", annotated_frame)

            # In trạng thái ra console
            print(f"1 {slots[1]}, 2 {slots[2]}")

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Cleanup
    ws_client.stop()
    cam.stop()
    det.join()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()