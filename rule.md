# 📋 Project Rules & Guidelines

**IMPORTANT:** Read this file before making ANY changes to the project. These rules ensure consistency, prevent bugs, and maintain code quality.

Last Updated: March 12, 2026

---

## 🎯 Pre-Change Checklist

Before you start implementing ANY feature or fix, complete this checklist:

- [ ] Read relevant sections of this `rule.md`
- [ ] Check `todo.md` to understand task priority and status
- [ ] Read `CODE_ANALYSIS.md` for function descriptions
- [ ] Understand the threading architecture (see Architecture section)
- [ ] Check if similar functionality already exists
- [ ] Look at related test cases or similar implementations
- [ ] Understand the data flow (frame_queue, result_queue)
- [ ] Plan changes before writing code

---

## 🏗️ Architecture & Threading Rules

### Rule #1: Respect the Threading Model
**You MUST understand this before touching any code:**

```
Main Thread (UI)
├── CameraModule (Daemon Thread)
│   └── Reads from camera source
│   └── Puts frames in frame_queue
├── YOLODetector (Daemon Thread)
│   ├── Gets frames from frame_queue
│   ├── Runs YOLO detection
│   └── Puts results in result_queue
├── WebSocketModule (Daemon Thread)
│   └── Broadcasts results to clients
└── UI Timer (33ms interval)
    └── Updates display from result_queue

```
**CRITICAL:** Never do blocking operations on the UI thread!


Module list

CamAI_Ford
│
├── mainwindow.py                 # The Launcher
├── modules/
│   ├── camera.py    # RTSP/Webcam stream logic
│   ├── detect.py    # AI logic (Standard Inference)
│   ├── roi_dialog.py       # THE HYBRID EDITOR (Auto + Manual)
│   ├── web_socket.py       # Data broadcasting & Logging
│   ├── settings_dialog.py   # Settings & ROI File handling
│   └── unit_manager.py     # System "Boss" (Handles multiple cams)
│
├── config/
│   ├── settings.json       # App & Camera configs
│   └── rois/               # Generated ROI JSONs for each cam
│
├── models/                 # Your trained .pt files
├── logs/                   # Auto-rotating JSON logs
└── assets/                 # Icons and Dark Mode CSS (.qss)


### Rule #2: Queue Communication Protocol
- **frame_queue:** Gets frame, puts processed results
- **result_queue:** Gets detection results (dict with 'frame' and 'slots')
- **ALWAYS use timeout:** `queue.get(timeout=0.01)` to prevent deadlock
- **NEVER block indefinitely** on queue operations
- **Check if empty first:** `while not self.result_queue.empty():`

### Rule #3: Thread Safety
- Only access `self.detect` from UI when it's safe (after it's created)
- Use `QMetaObject.invokeMethod()` to update UI from other threads
- Don't modify shared state without synchronization
- Use `threading.Event()` for thread control (as done in CameraModule)

---

## 📝 Code Style Rules

### Rule #4: Follow the Existing Code Style
- Use the current naming convention: `_method_names_with_underscores`
- Use the current docstring format: `"""Description."""`
- Maintain consistent indentation (4 spaces)
- Group related methods together with section comments:
  ```python
  # ── Section Name ────────────────────────────
  def method1(self):
      pass
  
  def method2(self):
      pass
  ```

### Rule #5: Import Organization
**Correct order:**
1. Standard library imports
2. Third-party imports
3. Local imports

```python
import os
import json
import queue
import threading

from PySide6.QtWidgets import QMainWindow
from PySide6.QtCore import QTimer

from camera import CameraModule
from detect import YOLODetector
```

### Rule #6: Type Hints
- Use type hints for function parameters and returns
- Examples:
  ```python
  def _get_camera_url(self, index: int = 0) -> str:
  def _select_camera(self, idx: int) -> None:
  def _convert_source(self, url: str) -> int | str:
  ```

---

## 🧪 Testing Rules

### Rule #7: Test Before Committing
Every change must be tested:
- [ ] Run the application without errors
- [ ] Test the specific feature/fix you implemented
- [ ] Test related features to ensure you didn't break them
- [ ] Check the console for warnings/errors
- [ ] Verify settings.json is valid JSON after changes

### Rule #8: Testing for New Features
When adding a new feature:
- [ ] Test with all camera types (RTSP, webcam "0", file path)
- [ ] Test with missing files/invalid URLs (error handling)
- [ ] Test UI buttons interact correctly
- [ ] Check that settings persist after restart
- [ ] Verify no memory leaks (check if threads stop properly)

---

## 📚 Settings & Configuration Rules

### Rule #9: Settings Structure
**NEVER manually edit settings.json!** Always use the SettingsDialog.

Current structure:
```json
{
    "cameras": [
        {
            "id": 1,
            "name": "Camera Name",
            "url": "rtsp://... or 0 for webcam",
            "model": "path/to/model.pt or empty string",
            "enabled": true
        }
    ],
    "websocket": {
        "host": "0.0.0.0",
        "port": 8765
    }
}
```

### Rule #10: Camera URL Handling
- **String "0"** = Webcam (must convert to int 0 for cv2.VideoCapture)
- **RTSP URL** = IP camera (pass as string)
- **File path** = Video file (pass as string)
- **ALWAYS use `_convert_source()`** before passing to CameraModule
- **NEVER assume URL type** - always validate

### Rule #11: Settings Validation
When loading settings:
- [ ] Check "cameras" key exists (fallback to DEFAULT_SETTINGS)
- [ ] Check "websocket" key exists (fallback to DEFAULT_SETTINGS)
- [ ] Validate all camera URLs are non-empty
- [ ] Validate port number is 1024-65535
- [ ] Handle missing model gracefully (empty string is OK)

---

## 🎨 UI & UX Rules

### Rule #12: UI Thread Safety
- **Never call OpenCV/blocking operations on UI thread**
- Use threading for slow operations (test connection, camera init)
- Use `QMetaObject.invokeMethod()` to update UI from threads
- Example:
  ```python
  def _do_slow_task():
      result = expensive_operation()
      QMetaObject.invokeMethod(self, "_show_result", 
                              Qt.QueuedConnection, Q_ARG(bool, result))
  
  threading.Thread(target=_do_slow_task, daemon=True).start()
  ```

### Rule #13: Message Boxes
- Use `QMessageBox` for important messages
- Types:
  - `.information()` - Success/informational
  - `.warning()` - User error/invalid input
  - `.critical()` - Application error
  - `.question()` - Yes/No confirmation
- Example: `QMessageBox.warning(self, "Title", "Message")`
- Style: Message need to be clear,fit in the box. The context and background should be contrast.

### Rule #14: Button Styling
All buttons use consistent styling. Examples:
```python
# Green (confirm/add)
"background-color: #a6e3a1; color: #11111b;"

# Red (delete/stop)  
"background-color: #f38ba8; color: #11111b;"

# Blue (info/switch)
"background-color: #74c7ec; color: #11111b;"

# Orange (test/show)
"background-color: #fab387; color: #11111b;"

# Purple (settings)
"background-color: #cba6f7; color: #11111b;"
```
- Restrict of using icon.
---

## 🐛 Debugging Rules

### Rule #15: Use Print Statements for Debugging
Format: `[ModuleName] Message`
```python
print(f"[MainWindow] Camera switched to index {idx}")
print(f"[CameraModule] Connected to {self.source}")
print(f"[YOLODetector] Detection in {elapsed_ms}ms")
```

### Rule #16: Error Handling
- **Never let exceptions silently fail**
- Always catch and log errors
- Provide user-friendly error messages
- Example:
  ```python
  try:
      result = operation()
  except Exception as e:
      print(f"[MainWindow] Error: {e}")
      QMessageBox.critical(self, "Error", "Operation failed")
  ```

---

## 📌 Known Bugs & Limitations

### Rule #17: Aware of These Issues
Before implementing features, know these are broken:
- ❌ Camera switching doesn't actually change stream
- ❌ Sidebar camera status doesn't update
- ❌ Webcam test connection shows false failures
- ❌ Removed cameras still appear in grid
- ❌ Detection toggle button doesn't control YOLODetector
- ❌ ROI uses wrong frame resolution

Do NOT assume these work! Test your code against these issues.

### Rule #18: Threading Gotchas
- Don't access `self.camera` from multiple places simultaneously
- Always call `camera.stop()` before creating new camera
- Clear queue after stopping: `while not queue.empty(): queue.get()`
- Daemon threads continue in background (may cause issues on exit)

---

## 📝 Documentation Rules

### Rule #19: Document Your Changes
For every change, update these files:
1. **CHANGELOG.md** - Add section with timestamp
2. **Code comments** - Explain complex logic
3. **Function docstrings** - Describe what function does
4. **Update todo.md** - Mark related items as done

### Rule #20: Code Comments
- Add `# ──` Section Headers for major sections
- Add inline comments for complex logic
- Keep comments up-to-date with code changes
- Bad: `x = x + 1  # increment x`
- Good: `# Convert string URL to int for webcam source`

---

## 🚀 Git & Version Control Rules

### Rule #21: Commit Guidelines
- Write clear commit messages
- Reference todo.md items: "Fixes #3 in todo.md"
- One feature per commit
- Test before committing
- Update CHANGELOG.md before committing

### Rule #22: Never Force Push
- Always pull before push
- Resolve conflicts carefully
- Test after resolving conflicts
- Communicate with team if stuck

---

## 🔐 Security Rules

### Rule #23: Password & URL Security
- **NEVER log camera URLs** (they contain passwords)
- Mask URLs in UI: `url[:40] + "…"`
- **NEVER commit real credentials** to git
- Use environment variables for sensitive data

### Rule #24: Input Validation
- Validate all user inputs (URLs, ports, filenames)
- Reject invalid file paths
- Validate port range: 1024-65535
- Don't trust settings.json - validate on load

---

## ⚡ Performance Rules

### Rule #25: Optimize Key Paths
- Don't create new objects in UI loop
- Avoid deep copies of frames (use `.copy()` only when needed)
- Cache frame pixmaps if reused
- Don't process every frame (drop old frames in queue)

### Rule #26: Resource Cleanup
- Always stop threads before exit
- Release camera objects: `cap.release()`
- Close file handles in finally blocks
- Test app shutdown (check for hanging processes)

---

## 🎓 Learning Resources

### Understanding the Code
1. Read relevant section in `CODE_ANALYSIS.md`
2. Trace through the code flow with print statements
3. Look at similar existing implementations
4. Test in small steps (test one function at a time)

### Debugging Tips
1. Add print statements with `[ModuleName]` prefix
2. Use Python debugger: `import pdb; pdb.set_trace()`
3. Check settings.json is valid: `python -m json.tool settings.json`
4. Check thread count: `threading.enumerate()`

---

## ✅ Change Checklist

Use this before submitting any code:

```
Pre-Implementation:
- [ ] Read relevant parts of rule.md
- [ ] Checked todo.md for priority
- [ ] Understood architecture/threading
- [ ] Found similar existing code to reference

During Implementation:
- [ ] Followed code style rules
- [ ] Added comments/docstrings
- [ ] Used proper error handling
- [ ] Thread-safe code (if multi-threaded)
- [ ] Type hints added

Testing:
- [ ] App runs without errors
- [ ] Feature works as intended
- [ ] No memory leaks (check with `top`)
- [ ] Tested error cases (missing files, invalid URLs)
- [ ] Tested on all camera types

Before Committing:
- [ ] Updated CHANGELOG.md
- [ ] Updated todo.md
- [ ] Code reviewed (self)
- [ ] No hardcoded values/paths
- [ ] No credentials in code
- [ ] All tests passed
```

---

## 📞 Questions?

If you're unsure about a rule or how to implement something:
1. Check `CODE_ANALYSIS.md` for function descriptions
2. Look at existing similar code
3. Read the docstrings
4. Check the related diagram in `rule.md`
5. Test in small steps and add print statements

**Remember:** It's better to ask/think twice and code once, than to code wrong the first time!
