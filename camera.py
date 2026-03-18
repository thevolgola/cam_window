import cv2
import threading
import time
import queue
import sys
import os

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
        
        # Connection timeout: 15 seconds for RTSP streams
        self.CONNECTION_TIMEOUT = 15.0
        self.RETRY_DELAY = 3.0

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

    def _connect(self):
        """Attempts to connect to the camera source with timeout."""
        # Release existing capture safely
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception as e:
                print(f"[Camera] Error releasing old capture: {e}")
            self.cap = None
        
        # Reset connection timer
        self.connection_start_time = time.time()
        print(f"[Camera] Connecting to camera source: {self.source}...")
        
        # Check if we should still be running
        if not self.running.is_set():
            print("[Camera] Stop signal received, aborting connection")
            return
        
        try:
            # Use timeout-protected capture creation
            self.cap, is_opened = self._safe_create_capture(
                self.source, 
                timeout=self.CONNECTION_TIMEOUT
            )
            
            if is_opened and self.cap is not None:
                self.is_connected = True
                print("[Camera] ✅ Connection Successful")
            else:
                self.is_connected = False
                print("[Camera] ❌ Connection Failed or timed out")
                if self.cap is not None:
                    try:
                        self.cap.release()
                    except:
                        pass
                    self.cap = None
                    
        except Exception as e:
            print(f"[Camera] Exception during connect: {e}")
            self.is_connected = False
            if self.cap is not None:
                try:
                    self.cap.release()
                except:
                    pass
                self.cap = None

    def run(self):
        """Main thread loop for continuous frame capture."""
        print("[Camera] Starting camera thread...")
        
        try:
            self._connect()
            
            while self.running.is_set():
                if not self.is_connected:
                    # Not connected, wait before retrying
                    time.sleep(self.RETRY_DELAY)
                    self._connect()
                    continue

                # Safety check: ensure cap is still valid
                if self.cap is None:
                    self.is_connected = False
                    continue

                try:
                    ret, frame = self.cap.read()
                    
                    if not ret or frame is None:
                        print("[Camera] Lost camera frame. Attempting reconnect...")
                        self.is_connected = False
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
                    
        except Exception as e:
            print(f"[Camera] Fatal error in run loop: {e}")
        finally:
            print("[Camera] Cleaning up camera thread...")
            self.stop()

    def stop(self):
        """Safely stop camera and release resources."""
        print("[Camera] Stopping camera thread...")
        self.running.clear()
        
        if self.cap is not None:
            try:
                # Double-check: ensure cap is released
                if hasattr(self.cap, 'isOpened'):
                    if self.cap.isOpened():
                        self.cap.release()
            except Exception as e:
                print(f"[Camera] Error releasing capture: {e}")
            finally:
                self.cap = None
        
        self.is_connected = False
        print("[Camera] Camera thread stopped")