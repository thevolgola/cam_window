import os
import queue
import threading
import time

import cv2

# CRITICAL: Disable OpenCV threading globally to prevent segfaults with FFmpeg on Linux
cv2.setNumThreads(0)
# Force RTSP to use TCP transport (interleaved) for better stability
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

class CameraModule(threading.Thread):
    def __init__(self, source=0, frame_queue=None, width=1280, height=720):
        super().__init__(daemon=True)
        self.source = source
        self.frame_queue = frame_queue
        self.width = width
        self.height = height
        
        self.cap = None
        self.running = threading.Event()
        self.running.set()
        
        # Performance monitoring
        self.last_frame_time = time.time()
        self.is_connected = False
        self.connection_start_time = time.time()  # Track when connection attempt started
        self.status_text = "Initializing..."
        self.waiting_for_manual_refresh = False
        self._has_connected_once = False
        self._auto_reconnect_used = False
        self._connect_in_progress = False
        self._refresh_requested = threading.Event()
        self._state_lock = threading.Lock()
        self._last_refresh_request_at = 0.0
        
        # Connection timeout: 15 seconds for RTSP streams
        self.CONNECTION_TIMEOUT = 15.0
        self.RETRY_DELAY = 3.0
        self.REFRESH_DEBOUNCE_SECONDS = 0.75

    def _set_status(self, text: str, waiting_for_manual_refresh: bool | None = None) -> None:
        """Update user-facing camera status safely across threads."""
        with self._state_lock:
            self.status_text = text
            if waiting_for_manual_refresh is not None:
                self.waiting_for_manual_refresh = waiting_for_manual_refresh

    def get_status_text(self) -> str:
        """Return the latest user-facing status string."""
        with self._state_lock:
            return self.status_text

    def is_waiting_for_refresh(self) -> bool:
        """Return whether the camera is idle and waiting for manual refresh."""
        with self._state_lock:
            return self.waiting_for_manual_refresh

    def is_connecting(self) -> bool:
        """Return whether a connection attempt is in progress."""
        with self._state_lock:
            return self._connect_in_progress

    def request_refresh(self) -> tuple[bool, str]:
        """Queue one manual refresh attempt and coalesce rapid repeated clicks."""
        now = time.time()
        with self._state_lock:
            if not self.running.is_set():
                return False, "Camera thread is stopped."
            if self.is_connected:
                return False, "Camera is already connected."
            if self._connect_in_progress:
                return False, "Connection attempt already in progress."
            if now - self._last_refresh_request_at < self.REFRESH_DEBOUNCE_SECONDS:
                return False, "Refresh request ignored to prevent spam."
            self._last_refresh_request_at = now
            self.waiting_for_manual_refresh = False
            self.status_text = "Refresh requested..."

        self._refresh_requested.set()
        return True, "Refresh requested."

    def _release_capture(self) -> None:
        """Release the current capture safely."""
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception as e:
                print(f"[Camera] Error releasing capture: {e}")
            finally:
                self.cap = None

    def _mark_waiting_for_refresh(self, message: str) -> None:
        """Transition into the manual-refresh-required state."""
        self.is_connected = False
        self._release_capture()
        self._set_status(message, waiting_for_manual_refresh=True)

    def _safe_create_capture(self, source, timeout=10.0):
        """
        Safely create VideoCapture with timeout to prevent segfaults.
        Returns (cap, success) tuple.
        """
        cap = None
        success = False
        
        def create_capture():
            nonlocal cap, success
            try:
                # Use FFMPEG backend explicitly for RTSP sources
                backend = cv2.CAP_FFMPEG if isinstance(source, str) and "rtsp" in source.lower() else cv2.CAP_ANY
                cap = cv2.VideoCapture(source, backend)
                
                # Configure RTSP-specific settings
                if isinstance(source, str) and ("rtsp" in source.lower() or "rtsps" in source.lower()):
                    # RTSP-specific optimizations
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize buffer
                    cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)   # Disable autofocus
                
                # Set resolution
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                
                # Test the connection with a dummy isOpened call
                success = cap.isOpened()
                
            except Exception as e:
                print(f"[Camera] Error creating capture: {e}")
                if cap is not None:
                    try:
                        cap.release()
                    except:
                        pass
                cap = None
                success = False
        
        # Run in a thread with timeout
        thread = threading.Thread(target=create_capture, daemon=True)
        thread.start()
        thread.join(timeout=timeout)
        
        # If thread is still alive, capture creation is hanging
        if thread.is_alive():
            print(f"[Camera] Connection timeout after {timeout}s")
            if cap is not None:
                try:
                    cap.release()
                except:
                    pass
            return None, False
        
        return cap, success

    def _connect(self, reason: str = "manual") -> bool:
        """Attempts to connect to the camera source with timeout."""
        self._release_capture()
        
        # Reset connection timer
        self.connection_start_time = time.time()
        phase_map = {
            "initial": "Connecting...",
            "manual": "Refreshing connection...",
            "reconnect": "Reconnecting once...",
        }
        self._set_status(phase_map.get(reason, "Connecting..."), waiting_for_manual_refresh=False)
        print(f"[Camera] Connecting to camera source: {self.source}...")
        
        # Check if we should still be running
        if not self.running.is_set():
            print("[Camera] Stop signal received, aborting connection")
            return False
        
        with self._state_lock:
            self._connect_in_progress = True

        try:
            # Use timeout-protected capture creation
            self.cap, is_opened = self._safe_create_capture(
                self.source, 
                timeout=self.CONNECTION_TIMEOUT
            )
            
            if is_opened and self.cap is not None:
                self.is_connected = True
                self._has_connected_once = True
                self._auto_reconnect_used = False
                self._refresh_requested.clear()
                self._set_status("Connected", waiting_for_manual_refresh=False)
                print("[Camera] ✅ Connection Successful")
                return True
            else:
                print("[Camera] ❌ Connection Failed or timed out")
                self._mark_waiting_for_refresh("Connection failed. Click Refresh to retry.")
                return False
                    
        except Exception as e:
            print(f"[Camera] Exception during connect: {e}")
            self._mark_waiting_for_refresh("Connection error. Click Refresh to retry.")
            return False
        finally:
            with self._state_lock:
                self._connect_in_progress = False

    def run(self):
        """Main thread loop for continuous frame capture."""
        print("[Camera] Starting camera thread...")
        
        try:
            self._connect(reason="initial")
            
            while self.running.is_set():
                if not self.is_connected:
                    if self._refresh_requested.wait(timeout=0.1):
                        self._refresh_requested.clear()
                        if self.running.is_set():
                            self._connect(reason="manual")
                    continue

                # Safety check: ensure cap is still valid
                if self.cap is None:
                    self.is_connected = False
                    self._mark_waiting_for_refresh("Camera disconnected. Click Refresh to retry.")
                    continue

                try:
                    ret, frame = self.cap.read()
                    
                    if not ret or frame is None:
                        print("[Camera] Lost camera frame.")
                        self.is_connected = False
                        self._release_capture()

                        if self._has_connected_once and not self._auto_reconnect_used:
                            self._auto_reconnect_used = True
                            print("[Camera] Attempting single automatic reconnect...")
                            if self._connect(reason="reconnect"):
                                continue

                        self._mark_waiting_for_refresh("Connection lost. Click Refresh to retry.")
                        continue

                    # --- REAL-TIME PRIORITY LOGIC ---
                    # If detector is slow, clear queue to send newest frame only
                    if self.frame_queue.full():
                        try:
                            self.frame_queue.get_nowait()  # Drop old frame
                        except queue.Empty:
                            pass

                    try:
                        self.frame_queue.put(frame, timeout=0.01)
                    except queue.Full:
                        pass

                    self.last_frame_time = time.time()
                    
                except Exception as e:
                    print(f"[Camera] Error reading frame: {e}")
                    self.is_connected = False
                    self._release_capture()

                    if self._has_connected_once and not self._auto_reconnect_used:
                        self._auto_reconnect_used = True
                        print("[Camera] Read error. Attempting single automatic reconnect...")
                        if self._connect(reason="reconnect"):
                            continue

                    self._mark_waiting_for_refresh("Camera error. Click Refresh to retry.")
                    
        except Exception as e:
            print(f"[Camera] Fatal error in run loop: {e}")
        finally:
            print("[Camera] Cleaning up camera thread...")
            self.stop()

    def stop(self):
        """Safely stop camera and release resources."""
        print("[Camera] Stopping camera thread...")
        self.running.clear()
        self._refresh_requested.set()
        
        self._release_capture()
        self.is_connected = False
        self._set_status("Stopped", waiting_for_manual_refresh=False)
        print("[Camera] Camera thread stopped")
