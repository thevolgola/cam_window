# CamAI Ford Project - Code Analysis & TODO List

## Overview
This document provides a comprehensive analysis of the Python modules in the `cam_window/` directory, including all functions, classes, potential improvements, bugs, and areas needing implementation.

---

## 1. FUNCTION & CLASS INVENTORY

### 1.1 mainwindow.py

#### **Class: MainWindow(QMainWindow)**
Container class for the entire UI application using PySide6.

**Methods:**
- `__init__(parent=None)` - Initialize main window with all modules and threads
- `setup_ui()` - Creates the main UI layout (video feed + sidebar)
- `_section_label(text)` - Helper to create styled section headers
- `_divider()` - Helper to create separator lines
- `_build_camera_grid()` - Build 2x2 grid of camera buttons
- `_toggle_camera_list()` - Switch between single camera and grid view
- `_show_camera_list()` - Display camera grid
- `_hide_camera_list()` - Return to single camera view
- `_select_camera(idx)` - Select a camera and optionally restart feed
- `_refresh_url_label()` - Update camera URL display
- `_refresh_cam_status_label()` - Update camera name/model info
- `_toggle_detection()` - Enable/disable AI detection with validation
- `open_settings()` - Open settings dialog and handle changes
- `_get_camera_url(index)` - Retrieve camera URL by index
- `_convert_source(url)` - Convert URL string to int (webcam) or string (RTSP)
- `_restart_camera(new_url)` - Stop old camera thread and start new one
- `open_roi_dialog()` - Open ROI setup dialog
- `load_config()` - Load saved ROI configuration from JSON
- `save_rois(silent)` - Save slot ROI coordinates to JSON file
- `reset_rois()` - Clear all calibration data with confirmation
- `update_ui()` - Timer-based UI refresh (~30 FPS) with frame and status updates
- `closeEvent(event)` - Cleanup on application exit

---

### 1.2 camera.py

#### **Class: CameraModule(threading.Thread)**
Handles camera frame capture in a daemon thread.

**Methods:**
- `__init__(source, frame_queue, width, height)` - Initialize camera with source and frame queue
- `_connect()` - Connect to camera source (RTSP URL or local index)
- `run()` - Main thread loop for continuous frame capture
- `stop()` - Stop the camera thread and release resources

---

### 1.3 detect.py

#### **Class: YOLODetector(threading.Thread)**
Runs YOLO inference in a daemon thread for parking slot detection.

**Methods:**
- `__init__(frame_queue, result_queue, model_path, detect_interval)` - Initialize detector with model
- `run()` - Main thread loop: pull frame → YOLO inference → slot state analysis
- `get_states()` - Thread-safe getter for current slot states

---

### 1.4 settings_dialog.py

#### **Helper Functions:**
- `load_settings()` - Load settings from JSON file with fallback to defaults
- `save_settings(data)` - Persist settings dict to disk

#### **Class: CameraRow(QWidget)**
A single camera entry in the settings dialog.

**Methods:**
- `__init__(cam_data, parent)` - Initialize row with camera data
- `_build_ui()` - Create form fields (Name, URL, Model, Test button)
- `_test_url()` - Test camera connection in background thread
- `_show_test_result(ok)` - Slot to display connection test result
- `_browse_model()` - Open file dialog to select .pt model file
- `_on_remove()` - Trigger removal confirmation
- `get_data()` - Return current form values as dict

#### **Class: SettingsDialog(QDialog)**
Modal dialog for managing camera sources and WebSocket settings.

**Methods:**
- `__init__(parent)` - Initialize settings dialog
- `_build_ui()` - Create camera section + WebSocket config section
- `_populate_cameras()` - Load existing cameras from settings
- `_add_camera(cam_data)` - Add a new camera row (with optional pre-filled data)
- `remove_camera_row(row)` - Remove a camera row with validation
- `_save_and_accept()` - Validate all cameras and save settings
- `get_settings()` - Return the saved settings dict

---

### 1.5 web_socket.py

#### **Class: WebSocketModule(threading.Thread)**
Manages WebSocket server communication with robot/client systems.

**Methods:**
- `__init__(host, port, log_file, max_log_size_mb)` - Initialize WebSocket server
- `_manage_log_size()` - Rotate log file when size limit exceeded
- `handler(websocket)` - Async handler for WebSocket client connections
- `send_data_to_all(slot_states)` - Broadcast parking slot states to all clients
- `main()` - Async server loop (runs in asyncio)
- `run()` - Thread entry point for asyncio event loop
- `stop()` - Gracefully shut down the server

---

### 1.6 roi_dialog.py

#### **Class: ROICanvas(QLabel)**
Custom widget for interactive ROI drawing on camera frames.

**Methods:**
- `__init__(frame, parent)` - Initialize canvas with camera snapshot
- `set_frame(frame)` - Update the displayed frame
- `set_draw_enabled(enabled)` - Enable/disable drawing mode
- `_scaled_rect()` - Calculate display rect accounting for aspect ratio
- `_label_to_frame(pt)` - Convert viewport pixel to original frame pixel
- `_frame_to_label(x, y)` - Convert original frame pixel to viewport pixel
- `_render()` - Convert numpy frame to QPixmap
- `paintEvent(event)` - Custom paint to overlay ROIs and drawing
- `resizeEvent(event)` - Handle window resize
- `mousePressEvent(event)` - Start rectangle drawing
- `mouseMoveEvent(event)` - Update rubber-band rect while dragging
- `mouseReleaseEvent(event)` - Finalize drawn rectangle

#### **Class: ROIDialog(QDialog)**
Modal dialog for setting parking slot ROIs using auto or manual modes.

**Methods:**
- `__init__(snapshot, detector, current_rois, parent)` - Initialize ROI dialog
- `_build_ui()` - Create canvas + tabs (Auto/Manual) + buttons
- `_build_auto_tab()` - Create auto-detection tab UI
- `_build_manual_tab()` - Create manual drawing tab UI
- `_on_tab_change(index)` - Enable/disable drawing when switching tabs
- `_run_auto_detect()` - Spawn thread to run YOLO inference on snapshot
- `_show_auto_results(proposed)` - Display auto-detected ROI candidates (blue)
- `_show_auto_error(msg)` - Handle auto-detect errors
- `_confirm_auto_rois()` - Accept proposed ROIs as confirmed (green)
- `_add_slot_btn(slot_id, set_active)` - Add slot selector button to manual tab
- `_select_slot(slot_id)` - Switch active slot for manual drawing
- `_clear_active_slot()` - Remove ROI for current slot
- `_clear_all_rois()` - Clear all ROIs with confirmation
- `_on_manual_rect_drawn(slot_id, roi)` - Callback when user finishes drawing
- `_on_save()` - Validate ROIs and accept dialog
- `get_rois()` - Return confirmed ROIs dict
- `_set_status(msg)` - Update status label

---

## 2. FUNCTIONAL DESCRIPTIONS

### CameraModule
**Purpose:** Continuously capture frames from RTSP streams or local cameras.
- Implements auto-reconnect logic (retries every 2 seconds on failure)
- Drops old frames from queue if detector is slow (real-time priority)
- Configurable resolution (default 1280x720)

### YOLODetector
**Purpose:** Run YOLO inference on incoming frames to detect parking slot states.
- Supports 4 classes: "Empty", "Car Empty", "Car Full", "Unknown"
- Has calibration mode (auto-assign ROIs on first detection) and monitoring mode
- Throttled detection interval (default 0.25s = 4 FPS detection, higher frame capture rate)
- Thread-safe state access via lock

### MainWindow
**Purpose:** Unified UI for monitoring and controlling the system.
- Displays live video feed with detection overlays (scales to 640x480)
- Sidebar with system status (AI engine, WebSocket clients, parking slots)
- Multi-camera support with grid view and single-camera switching
- ROI setup dialog for calibration
- Settings dialog for camera/WebSocket configuration
- Auto-saves ROI configuration to JSON

### SettingsDialog
**Purpose:** Manage camera sources and server configuration without code changes.
- Add/remove cameras dynamically
- Test camera connectivity
- Configure WebSocket host/port
- Browse for AI model files (.pt)
- Validates camera URLs and model paths

### WebSocketModule
**Purpose:** Broadcast parking slot detection results to external robot/client systems.
- Accepts multiple concurrent WebSocket connections
- Transforms detection labels to robot-ready states: "empty", "occupied", "unknown"
- Logs all detections with ISO timestamps to JSON file
- Auto-rotates log when size exceeds limit (prevents disk overflow)

### ROIDialog
**Purpose:** Interactive tool for defining parking slot regions-of-interest.
- **Auto Mode:** Run YOLO to auto-detect and propose ROIs
- **Manual Mode:** User draws rectangles for precise slot definition
- Visual feedback: blue (proposed), green (confirmed), yellow (drawing)
- Persists ROIs to JSON config file via MainWindow

---

## 3. POTENTIAL IMPROVEMENTS & MISSING FEATURES

### 3.1 Critical Issues

#### **Detection Enable/Disable Not Wired Up**
- `mainwindow.py` lines 320-332: `_toggle_detection()` method has TODO comments
- Detection state is set in UI but **not actually applied to the detector**
- Impact: User can click "toggles" detection but it doesn't actually stop inference
- **Fix Needed:** Add `self.detect.detection_enabled` flag and check it in detector's `run()` loop

#### **Latest Frame Used for ROI is Display Frame, Not Original**
- `mainwindow.py` line 674: `self._latest_frame = frame.copy()` stores 640x480 display frame
- ROI dialog draws on this scaled frame, not the original camera resolution frame
- Impact: ROI coordinates will be slightly off
- **Fix Needed:** Pass original frame from detector to MainWindow

#### **No Error Handling for Model File Missing**
- `mainwindow.py` lines 64-65: Just prints a warning, continues with missing model
- Impact: Application starts but crashes silently when detector tries to load model
- **Fix Needed:** Show blocking error dialog and exit gracefully

#### **WebSocket Send Failures Not Logged Properly**
- `web_socket.py` line 126: Generic exception catch, doesn't track client disconnections
- Impact: Hard to debug network issues
- **Fix Needed:** Add client state tracking and better error logging

### 3.2 Performance & Resource Issues

#### **Frame Queue Always Full, Constantly Dropping Frames**
- `camera.py` line 54: Drops frames if queue is full
- With 30 FPS capture and 4 FPS detection, queue will frequently overflow
- Impact: Jerky video feed, inconsistent data logging
- **Improvement:** Consider using a circular buffer instead of queue

#### **No FPS Metrics**
- Camera and detector run but no way to monitor actual frame rate
- Impact: Can't detect performance degradation
- **Improvement:** Add FPS counter to camera and detector

#### **Model Loading Not Optimized**
- Model loaded once but never moved to GPU properly (line 137 in detect.py seems incomplete)
- Impact: First inference slow, potential memory issues
- **Improvement:** Verify `model.to(device)` is working; add warmup inference

#### **No Thread Management for Settings Dialog**
- WebSocket and detector threads keep running while user edits settings
- Changing camera URL requires stopping/starting camera thread
- Impact: Potential race conditions
- **Improvement:** Implement proper state management and thread synchronization

### 3.3 Feature Gaps

#### **No Detection History/Statistics**
- Only current state is shown, no historical data
- Impact: Can't analyze occupancy patterns
- **Improvement:** Store state transitions with timestamps; add statistics view

#### **No Alert/Notification System**
- No way to notify when slot state changes
- Impact: Passive monitoring only
- **Improvement:** Add buzzer/email/SMS notifications for state changes

#### **Limited Multi-Camera Support**
- Can view different cameras but detection runs on only one
- Impact: Can't monitor multiple parking areas simultaneously
- **Improvement:** Support detector threads per camera

#### **No Video Recording**
- Live feed not recorded for later review
- Impact: Can't investigate why system missed a detection
- **Improvement:** Add optional video recording with configurable retention

#### **Manual ROI Drawing UI Issues**
- Slot buttons in manual mode don't show ROI count
- No visual feedback if rectangle is too small
- Impact: User confusion
- **Improvement:** Display ROI validation and feedback

#### **Settings Not Persisted Across App Restart for Detection State**
- Detection toggle state resets on app restart
- Impact: Need to re-enable detection every time
- **Improvement:** Save detection state to settings

### 3.4 Code Quality & Maintainability

#### **No Input Validation for RTSP URLs**
- Settings dialog accepts any URL without format checking
- Impact: Garbage URLs cause cryptic errors later
- **Improvement:** Use regex or urllib to validate URL format

#### **Hardcoded Color Values**
- State colors defined in multiple places (detect.py, roi_dialog.py)
- Impact: Changing color scheme requires editing multiple files
- **Improvement:** Move to centralized config

#### **No Logging Framework**
- All debug output via print() statements
- Impact: Hard to track issues in production
- **Improvement:** Implement proper logging with levels (DEBUG, INFO, ERROR)

#### **Settings JSON Not Versioned**
- If config schema changes, old files break silently
- Impact: Hard to migrate settings from old versions
- **Improvement:** Add version field to settings JSON

#### **Minimal Comments on Complex Logic**
- Detector's state priority logic (lines 104-122 in detect.py) lacks explanation
- Impact: Hard to modify detection rules
- **Improvement:** Add detailed comments explaining detection logic

#### **ROI Persistence Not Atomic**
- Settings saved to disk without transaction safety
- Impact: Corruption if save fails mid-operation
- **Improvement:** Use atomic write (write to temp file, then rename)

### 3.5 User Experience Issues

#### **No Feedback During Long Operations**
- Camera reconnection blocks UI briefly
- Auto-detect in ROI dialog shows loading state but cursor not updated
- Impact: Looks frozen
- **Improvement:** Use progress indicators

#### **Settings Validation Warnings Don't Block Save**
- Model file warnings allow save to proceed
- Impact: User thinks settings are valid but detection fails
- **Improvement:** Use Approved/Reject pattern, not just warnings

#### **No "About" or Help Text**
- New users don't know what each button does
- Impact: Steep learning curve
- **Improvement:** Add tooltips and help dialogs

---

## 4. AREAS NEEDING IMPLEMENTATION

### 4.1 Immediate Fixes (Priority: HIGH)

| Issue | File | Lines | Severity |
|-------|------|-------|----------|
| Implement detection enable/disable logic | detect.py | ~30-40 | 🔴 Critical |
| Use original resolution frame for ROI setup | detect.py, mainwindow.py | ~670-674 | 🔴 Critical |
| Add model file validation on startup | mainwindow.py | 64-65 | 🔴 Critical |
| Add thread-safe detection state flag | detect.py | __init__ | 🟠 High |
| Improve WebSocket error handling | web_socket.py | 115-130 | 🟠 High |

### 4.2 Medium Priority Features

| Feature | File | Effort | Impact |
|---------|------|--------|--------|
| FPS monitoring dashboard | mainwindow.py | 2-3 hours | Medium |
| Detection history log viewer | new file | 3-4 hours | Medium |
| Better multi-camera detection support | detect.py, mainwindow.py | 4-5 hours | High |
| Video recording module | new file | 3-4 hours | Medium |
| Settings validation with regex | settings_dialog.py | 1-2 hours | Low |
| Centralized theme/color constants | new file | 1 hour | Low |

### 4.3 Low Priority Improvements

| Improvement | Effort | Note |
|------------|--------|------|
| Add logging framework | 2 hours | Nice for production |
| Implement settings versioning | 1-2 hours | Future-proofing |
| Add tooltips and help dialogs | 2-3 hours | UX enhancement |
| Atomic file writes | 1 hour | Data safety |
| ROI validation feedback | 1-2 hours | UX improvement |

---

## 5. BUG SUMMARY

### Active Bugs (Confirmed by code inspection)

1. **Detection toggle doesn't actually disable detection**
   - Lines: mainwindow.py 320-332
   - Severity: HIGH
   - Impact: Users think detection is off but it keeps running

2. **ROI dialog uses scaled frame instead of original**
   - Lines: mainwindow.py 674
   - Severity: MEDIUM
   - Impact: ROI coordinates misaligned with actual detections

3. **Missing model file causes silent failure**
   - Lines: mainwindow.py 64-65
   - Severity: HIGH
   - Impact: Application starts but detector won't work

4. **WebSocket broadcast catches all exceptions generically**
   - Lines: web_socket.py 126
   - Severity: MEDIUM
   - Impact: Network issues hard to debug

### Potential Bugs (May occur under edge cases)

1. **Race condition in settings dialog**
   - Threads continue running while user edits settings
   - detector.model_path not updated if model path changes in settings

2. **Queue overflow handling incomplete**
   - camera.py catches queue.Empty but not queue.Full
   - May lose frames without notification

3. **ROI coordinates not normalized**
   - detect.py inferenceuses raw YOLO coords without bounds checking
   - Could crash if bbox extends outside frame

---

## 6. CONFIGURATION & DEPENDENCIES

### Current Configuration Files
- `settings.json` - Camera URLs, WebSocket settings
- `config_detector.json` - Saved ROI coordinates
- `detection_log.json` - WebSocket message log (auto-rotates)

### Key Dependencies
- PySide6 - UI framework
- OpenCV (cv2) - Camera and image processing
- YOLOv8 (ultralytics) - Object detection
- websockets - WebSocket server
- PyTorch - YOLO backend

### Hardcoded Paths
- `BASE_DIR` = script directory
- Model path: `{BASE_DIR}/best.pt`
- Logs: `{BASE_DIR}/../log/detection_log.json`

---

## 7. ARCHITECTURE NOTES

### Threading Model
- **MainWindow** - Main Qt thread (UI)
- **CameraModule** - Daemon thread reading frames
- **YOLODetector** - Daemon thread running inference
- **WebSocketModule** - Daemon thread running asyncio event loop

### Data Flow
```
Camera Thread → frame_queue → Detector Thread → result_queue → UI Thread (30 FPS timer)
                                    ↓
                            WebSocket broadcast to clients
```

### State Management
- `MainWindow._detection_enabled` - UI toggle (not used in detector)
- `YOLODetector.slot_states` - Current parking states (thread-safe dict)
- `YOLODetector.slot_rois` - ROI definitions (can be updated anytime)
- Settings stored in `settings.json` (not watched for changes)

---

## 8. TESTING RECOMMENDATIONS

### Unit Test Candidates
- `_convert_source()` - URL to int conversion
- `load_settings()` - JSON parsing with edge cases
- Color mapping in detector
- ROI coordinate transformations in canvas

### Integration Test Candidates
- Settings save → reload → verify applied
- Camera reconnect on URL change
- Multi-slot detection with overlapping objects
- WebSocket client connect/disconnect

### Manual Test Checklist
- [ ] Start with no settings.json (uses defaults)
- [ ] Test changing camera URL and verify reconnect
- [ ] Test detection toggle actually stops detection
- [ ] Test ROI setup with auto and manual modes
- [ ] Test WebSocket client connection
- [ ] Test log rotation at 10MB limit
- [ ] Test with invalid model path

---

## SUMMARY STATS

| Metric | Count |
|--------|-------|
| Files Analyzed | 6 |
| Total Classes | 8 |
| Total Methods | 100+ |
| Critical Issues | 4 |
| High Priority Issues | 5 |
| Medium Priority Issues | 6 |
| Feature Gaps | 4+ |
| Lines of Code | ~2500 |

---

**Report Generated:** 2026-03-12  
**Analysis Scope:** cam_window/ directory Python modules  
**Next Step:** Prioritize fixes in Section 4.1 before feature development
