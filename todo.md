# 🎯 Project TODO List

Last Updated: March 13, 2026

---

## 🔴 CRITICAL ISSUES - Fix Immediately

### Camera & Stream Management
- [x] **Fix camera switching** - Sidebar not updating, streams not changing when selecting different camera
- [x] **Implement detection enable/disable** - Toggle button now controls YOLODetector
- [x] **Fix frame resolution mismatch** - ROI coordinates now align with original frame via raw_frame passing
- [x] **Encapsulate ROI logic in ROIDialog** - Save/Reset methods moved from MainWindow to dedicated dialog
- [x] **Cleanup Sidebar UI** - Removed redundant Save/Reset buttons; merged into ROI workflow
- [x] **Fix detection button text display** - Button now shows correct ON/OFF states with proper styling
- [x] **Add connection status display** - Shows "INITIALIZING...", timeout, and connection failed messages
- [ ] **Handle missing model file gracefully** - Should show warning, not crash silently

### Settings & Configuration
- [x] **Validate camera index after deletion** - App crashes if deleted camera was currently selected
- [x] **Test connection shows false failures** - Removed test button; now using main window connection status
- [ ] **Rebuild UI on settings change** - Camera grid not updating after adding/removing cameras

---

## 🟡 HIGH PRIORITY - Core Functionality

### Documentation & Project Management
- [x] **Create comprehensive TODO list** - Organized task management with priority levels and status tracking
- [x] **Create development rules document** - 22 essential rules, checklists, and guidelines for consistent development
- [x] **Create code analysis documentation** - Complete function inventory, architecture overview, and bug analysis

### Multi-Camera Support
- [ ] **Implement actual camera switching** - Select camera → stream updates + sidebar updates
- [ ] **Per-camera detection control** - Each camera should have separate on/off toggle
- [ ] **Per-camera model loading** - Load different YOLO model for each camera
- [ ] **Per-camera ROI settings** - Store separate ROI for each camera
- [ ] **Per-camera performance stats** - Track FPS, latency per camera

### Detection System
- [ ] **Connect detection toggle to YOLODetector** - Make button actually enable/disable processing
- [ ] **Implement friendly error messages** - Print user-facing errors instead of technical exceptions
- [ ] **Add detection status indicator** - Show if detection is running/paused/failed
- [ ] **Handle model loading errors** - Graceful fallback if model file is missing

### User Interface
- [ ] **Improve camera grid styling** - Current buttons are hard to read with multi-line text
- [ ] **Add loading indicator** - Show spinner when connecting to camera
- [ ] **Add connection status** - Display "Connected", "Connecting...", "Failed" for each camera
- [ ] **Improve error dialogs** - Show specific error messages, not generic warnings

---

## 🟢 MEDIUM PRIORITY - Features & Improvements

### Logging & Debugging
- [ ] **Implement proper logging system** - Replace print() with logger
- [ ] **Add debug mode flag** - Control verbosity via settings
- [ ] **Log detection results** - Track what was detected and when
- [ ] **Log connection attempts** - Show retry counts and timing

### Performance & Optimization
- [ ] **Implement frame rate limiting** - Prevent UI thread overload
- [ ] **Add frame drop detection** - Warn when camera can't keep up
- [ ] **Optimize frame resizing** - Cache scaled pixmaps
- [ ] **Profile performance** - Identify bottlenecks

### WebSocket / Communication
- [ ] **Add reconnection logic** - Retry failed WebSocket connections
- [ ] **Implement heartbeat** - Keep-alive signal for clients
- [ ] **Add message queuing** - Buffer detections if client temporarily unavailable
- [ ] **Support multiple WebSocket clients** - Already partially done, needs testing

### Settings & Configuration
- [ ] **Add default settings validation** - Check all required fields exist
- [ ] **Implement settings backup** - Auto-backup before changes
- [ ] **Add reset to defaults option** - One-click reset in settings dialog
- [ ] **Support multiple config files** - Switch between saved profiles

---

## 🔵 LOWER PRIORITY - Nice-to-Have Features

### Analytics & Monitoring
- [ ] **Add real-time statistics dashboard** - FPS, detection count, latency
- [ ] **Implement session history** - Track detections over time
- [ ] **Add database logging** - Store detection results in SQLite/MySQL
- [ ] **Generate usage reports** - Daily/weekly summaries

### Advanced Detection
- [ ] **Support multiple models** - Toggle between different YOLO versions
- [ ] **Implement model comparison** - Run multiple models side-by-side
- [ ] **Add object tracking** - Track detected objects across frames
- [ ] **Implement confidence filtering** - Filter out low-confidence detections

### Video & Recording
- [ ] **Implement video recording** - Record detected events
- [ ] **Add clip export** - Save detected object clips
- [ ] **Implement pause/resume** - Control video playback
- [ ] **Add playback scrubbing** - Seek through recorded video

### User Experience
- [ ] **Add keyboard shortcuts** - Quick access to common functions
- [ ] **Implement drag-and-drop** - Drag model files to load
- [ ] **Add tooltips** - Hover help on buttons/settings
- [ ] **Support dark/light themes** - Theme switching

### System & Deployment
- [ ] **Package as executable** - PyInstaller bundle for distribution
- [ ] **Add auto-update check** - Notify of new versions
- [ ] **Implement config versioning** - Handle upgrades gracefully
- [ ] **Add crash recovery** - Auto-save state before crashes

---

## 📊 Feature Status Legend

| Status | Meaning |
|--------|---------|
| ✅ Done | Fully implemented and tested |
| ⚠️ Partial | Partially implemented, needs completion |
| ❌ Broken | Implemented but not working correctly |
| 🔲 Not Started | Planned but not begun |

---

## 🔧 Implementation Notes

### Dependencies Added Recently
- QFileDialog - for model file selection
- QScrollArea, QGridLayout - for camera grid view
- time module - for webcam initialization delay

### Known Limitations
1. Only supports linear camera list (no grouping)
2. Detection model must be same YOLO format
3. No built-in conflict resolution for port 8765
4. Camera URLs stored in plaintext (security risk)

### Architecture Overview
```
MainWindow (UI Thread)
├── CameraModule (Thread) → frame_queue
├── YOLODetector (Thread) ← frame_queue, result_queue →
├── WebSocketModule (Thread)
├── SettingsDialog (Modal)
└── ROIDialog (Modal)
```

---

## 📝 How to Use This TODO List

1. Pick a section based on priority (CRITICAL → HIGH → MEDIUM)
2. Read `rule.md` before starting any change
3. Check off items as you complete them
4. Update timestamps in files when modified
5. Document changes in CHANGELOG.md
6. Test thoroughly before marking as complete

---

## 🐛 Related Documents

- **CODE_ANALYSIS.md** - Detailed function-by-function breakdown
- **rule.md** - Rules and guidelines (READ BEFORE MAKING CHANGES)
- **CHANGELOG.md** - Git-style change history for this session
