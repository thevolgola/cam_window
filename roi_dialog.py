"""
roi_dialog.py
─────────────────────────────────────────────────────────────────────────────
ROI Setup Dialog for CamAI Ford project.

Modes
-----
Auto   – run one YOLO inference on the snapshot frame, propose the resulting
         bounding boxes as ROI candidates.  User reviews and confirms.
Manual – user clicks a slot-ID button then rubber-band draws a rectangle
         directly on the canvas.  Multiple slots can be drawn in sequence.

Usage (from mainwindow.py)
--------------------------
    snapshot = <latest numpy BGR frame>
    dlg = ROIDialog(snapshot, detector=self.detect, current_rois=self.detect.slot_rois, parent=self)
    if dlg.exec() == ROIDialog.Accepted:
        self.detect.slot_rois = dlg.get_rois()
"""

import os
import json
import copy
import threading

import cv2
import numpy as np
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTabWidget, QWidget, QScrollArea, QSizePolicy,
    QSpinBox, QMessageBox, QButtonGroup
)
from PySide6.QtCore import Qt, QRect, QPoint, QSize, Slot, Signal, QMetaObject
from PySide6.QtGui import QImage, QPixmap, QFont, QPainter, QPen, QColor, QCursor

# ── Configuration Constants ───────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = "config_detector.json"

# ── Style ─────────────────────────────────────────────────────────────────────
STYLE = """
QDialog {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
QTabWidget::pane {
    border: 1px solid #45475a;
    border-radius: 6px;
    background: #1e1e2e;
}
QTabBar::tab {
    background: #313244;
    color: #cdd6f4;
    padding: 7px 22px;
    border-radius: 4px;
    font-weight: bold;
    font-size: 13px;
    margin-right: 3px;
}
QTabBar::tab:selected {
    background: #89b4fa;
    color: #11111b;
}
QLabel {
    color: #cdd6f4;
    font-size: 13px;
}
QPushButton {
    border-radius: 6px;
    padding: 7px 16px;
    font-size: 13px;
    font-weight: bold;
}
QPushButton#btn_detect {
    background-color: #89b4fa;
    color: #11111b;
}
QPushButton#btn_detect:hover { background-color: #a0c4fc; }
QPushButton#btn_confirm_auto {
    background-color: #a6e3a1;
    color: #11111b;
}
QPushButton#btn_confirm_auto:hover { background-color: #b5f0b0; }
QPushButton#btn_clear_slot {
    background-color: #f38ba8;
    color: #11111b;
}
QPushButton#btn_clear_slot:hover { background-color: #f5a8bd; }
QPushButton#btn_clear_all {
    background-color: #f38ba8;
    color: #11111b;
}
QPushButton#btn_clear_all:hover { background-color: #f5a8bd; }
QPushButton#btn_save {
    background-color: #a6e3a1;
    color: #11111b;
    padding: 9px 24px;
    font-size: 14px;
}
QPushButton#btn_save:hover { background-color: #b5f0b0; }
QPushButton#btn_cancel {
    background-color: #45475a;
    color: #cdd6f4;
    padding: 9px 24px;
    font-size: 14px;
}
QPushButton#btn_cancel:hover { background-color: #585b70; }
QPushButton[slot_btn="true"] {
    background-color: #313244;
    color: #cdd6f4;
    border: 2px solid #45475a;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
    font-weight: bold;
    min-width: 42px;
}
QPushButton[slot_btn="true"]:checked {
    background-color: #cba6f7;
    color: #11111b;
    border: 2px solid #cba6f7;
}
QPushButton#btn_add_slot {
    background-color: #fab387;
    color: #11111b;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
    font-weight: bold;
}
QFrame#divider { color: #45475a; }
QScrollArea { border: none; background: transparent; }
"""

# ── Colour constants (Match Rule #14) ──────────────────────────────────────────
COL_CONFIRMED   = QColor("#a6e3a1")   # green
COL_PROPOSED    = QColor("#74c7ec")   # blue (sky blue)
COL_DRAWING     = QColor("#f9e2af")   # yellow (peach/yellow)


# ─────────────────────────────────────────────────────────────────────────────
# ROICanvas
# ─────────────────────────────────────────────────────────────────────────────
class ROICanvas(QLabel):
    """
    A QLabel that:
    • shows a scaled camera frame
    • overlays confirmed ROIs (green), proposed auto-ROIs (blue),
      and the in-progress rubber-band rect (yellow)
    • emits a rect (in original frame coords) when the user finishes drawing
    """

    def __init__(self, frame: np.ndarray, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(640, 400)
        self.setStyleSheet(
            "background-color: #11111b; border: 2px solid #45475a; border-radius: 8px;"
        )
        self.setCursor(QCursor(Qt.CrossCursor))

        # Original resolution frame
        self._frame: np.ndarray = frame
        self._h, self._w = frame.shape[:2]

        # State dicts  {slot_id: [x1,y1,x2,y2]}  in ORIGINAL frame coords
        self.confirmed_rois: dict[int, list] = {}
        self.proposed_rois:  dict[int, list] = {}  # auto mode candidates

        # Manual drawing state
        self._drawing = False
        self._draw_start: QPoint | None = None
        self._draw_end:   QPoint | None = None
        self._draw_enabled = False   # only True in Manual tab

        # Callback: called with (slot_id, [x1,y1,x2,y2]) on rect finish
        self.on_rect_drawn = None
        self.active_slot_id: int = 1

        # Caching
        self._base_pixmap: QPixmap | None = None
        self._cached_scaled_pixmap: QPixmap | None = None
        self._last_scaled_size: QSize | None = None

        self._render()

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_frame(self, frame: np.ndarray):
        self._frame = frame
        self._h, self._w = frame.shape[:2]
        self._render()

    def set_draw_enabled(self, enabled: bool):
        self._draw_enabled = enabled
        self.setCursor(QCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor))

    # ── Coordinate Mapping ─────────────────────────────────────────────────────

    def _scaled_rect(self) -> QRect:
        """Returns the QRect of the actual image inside the label (letterboxed)."""
        lw, lh = self.width(), self.height()
        img_aspect = self._w / self._h
        lbl_aspect = lw / lh if lh else 1

        if img_aspect > lbl_aspect:
            dw = lw
            dh = int(lw / img_aspect)
        else:
            dh = lh
            dw = int(lh * img_aspect)

        ox = (lw - dw) // 2
        oy = (lh - dh) // 2
        return QRect(ox, oy, dw, dh)

    def _label_to_frame(self, pt: QPoint) -> tuple[int, int]:
        """Convert label pixel → original frame pixel."""
        sr = self._scaled_rect()
        fx = int((pt.x() - sr.x()) / sr.width()  * self._w)
        fy = int((pt.y() - sr.y()) / sr.height() * self._h)
        fx = max(0, min(self._w - 1, fx))
        fy = max(0, min(self._h - 1, fy))
        return fx, fy

    def _frame_to_label(self, x: float, y: float) -> QPoint:
        """Convert original frame pixel → label pixel."""
        sr = self._scaled_rect()
        lx = int(x / self._w * sr.width()  + sr.x())
        ly = int(y / self._h * sr.height() + sr.y())
        return QPoint(lx, ly)

    # ── Rendering ──────────────────────────────────────────────────────────────

    def _render(self):
        """Convert numpy frame to QPixmap and store (paint happens in paintEvent)."""
        rgb = cv2.cvtColor(self._frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        self._base_pixmap = QPixmap.fromImage(qimg)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)

        # First let QLabel draw the pixmap (scaled)
        sr = self._scaled_rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw base frame
        if self._base_pixmap:
            if self._cached_scaled_pixmap is None or self._last_scaled_size != sr.size():
                self._cached_scaled_pixmap = self._base_pixmap.scaled(
                    sr.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self._last_scaled_size = sr.size()
            
            painter.drawPixmap(sr.topLeft(), self._cached_scaled_pixmap)

        # Helper for drawing a labelled box
        def draw_box(coords, color: QColor, slot_id: int, label_prefix: str):
            x1, y1, x2, y2 = coords
            p1 = self._frame_to_label(x1, y1)
            p2 = self._frame_to_label(x2, y2)
            rect = QRect(p1, p2).normalized()

            pen = QPen(color, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)

            # Label background
            tag = f"{label_prefix}{slot_id}"
            fm   = painter.fontMetrics()
            tw   = fm.horizontalAdvance(tag) + 8
            th   = fm.height() + 4
            bg   = QRect(rect.x(), rect.y() - th, tw, th)
            painter.fillRect(bg, color)
            painter.setPen(QColor("#11111b"))
            painter.drawText(bg, Qt.AlignCenter, tag)

        # Draw proposed (blue)
        for sid, coords in self.proposed_rois.items():
            draw_box(coords, COL_PROPOSED, sid, "Auto ")

        # Draw confirmed (green)
        for sid, coords in self.confirmed_rois.items():
            draw_box(coords, COL_CONFIRMED, sid, "Slot ")

        # Draw rubber-band in-progress rect (yellow)
        if self._drawing and self._draw_start and self._draw_end:
            pen = QPen(COL_DRAWING, 2, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRect(self._draw_start, self._draw_end).normalized())

        painter.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

    # ── Mouse Events ───────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if not self._draw_enabled or event.button() != Qt.LeftButton:
            return
        self._drawing = True
        self._draw_start = event.position().toPoint()
        self._draw_end   = self._draw_start
        self.update()

    def mouseMoveEvent(self, event):
        if self._drawing:
            self._draw_end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if not self._drawing or event.button() != Qt.LeftButton:
            return
        self._drawing = False
        self._draw_end = event.position().toPoint()

        # Convert both corners to frame coords
        fx1, fy1 = self._label_to_frame(self._draw_start)
        fx2, fy2 = self._label_to_frame(self._draw_end)

        # Ensure x1 < x2, y1 < y2
        x1, x2 = min(fx1, fx2), max(fx1, fx2)
        y1, y2 = min(fy1, fy2), max(fy1, fy2)

        # Ignore tiny accidental clicks
        if (x2 - x1) < 10 or (y2 - y1) < 10:
            self._draw_start = self._draw_end = None
            self.update()
            return

        roi = [x1, y1, x2, y2]
        self.confirmed_rois[self.active_slot_id] = roi

        if callable(self.on_rect_drawn):
            self.on_rect_drawn(self.active_slot_id, roi)

        self._draw_start = self._draw_end = None
        self.update()


# ─────────────────────────────────────────────────────────────────────────────
# ROIDialog
# ─────────────────────────────────────────────────────────────────────────────
class ROIDialog(QDialog):
    """
    Modal dialog for setting up slot ROIs.

    Parameters
    ----------
    snapshot   : latest BGR numpy frame from the camera
    detector   : YOLODetector instance (used for Auto mode inference)
    current_rois : existing {slot_id: [x1,y1,x2,y2]} dict (deep-copied)
    parent     : QWidget parent
    """

    # Signals for thread-safe UI updates from the auto-detect background thread
    _sig_auto_results = Signal(object)   # proposed: dict[int, list]
    _sig_auto_error   = Signal(str)      # error message

    def __init__(self, snapshot: np.ndarray, detector=None,
                 current_rois: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📐  ROI Setup")
        self.setMinimumSize(800, 620)
        self.setStyleSheet(STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._snapshot  = snapshot
        self._detector  = detector
        self._rois: dict[int, list] = copy.deepcopy(current_rois or {})

        # Manual mode slot buttons (dynamic)
        self._slot_btns: list[QPushButton] = []
        self._slot_btn_group = QButtonGroup(self)
        self._slot_btn_group.setExclusive(True)

        # Connect signals
        self._sig_auto_results.connect(self._show_auto_results)
        self._sig_auto_error.connect(self._show_auto_error)

        self._build_ui()
        # Load existing ROIs into canvas
        self._canvas.confirmed_rois = copy.deepcopy(self._rois)
        self._canvas.update()

    @staticmethod
    def load_rois() -> dict[int, list]:
        """Utility to load ROIs from disk without opening the dialog."""
        file_path = os.path.join(BASE_DIR, CONFIG_FILE)
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    return {int(k): v for k, v in data.items()}
            except Exception as e:
                print(f"[ROIDialog] Load Error: {e}")
        return {}

    # ── UI Construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # Title
        title = QLabel("ROI Setup")
        title.setFont(QFont("Arial", 15, QFont.Bold))
        title.setStyleSheet("color: #cba6f7;")
        root.addWidget(title)

        intro = QLabel(
            "Configure parking slot detection areas. Use <b>Auto Mode</b> to find slots using AI, "
            "or <b>Manual Mode</b> to precisely draw them yourself."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #a6adc8; font-size: 13px; margin-bottom: 4px;")
        root.addWidget(intro)

        div = QFrame(); div.setObjectName("divider"); div.setFrameShape(QFrame.HLine)
        root.addWidget(div)

        # ── Canvas ──────────────────────────────────────────────────────────────
        self._canvas = ROICanvas(self._snapshot, parent=self)
        self._canvas.on_rect_drawn = self._on_manual_rect_drawn
        root.addWidget(self._canvas, stretch=1)

        # ── Legend ──────────────────────────────────────────────────────────────
        legend = QHBoxLayout()
        legend.setSpacing(16)
        for txt, col in [("● Confirmed", "#a6e3a1"),
                          ("● Proposed",  "#89b4fa"),
                          ("● Drawing",   "#f9e2af")]:
            lbl = QLabel(txt)
            lbl.setStyleSheet(f"color: {col}; font-size: 12px;")
            legend.addWidget(lbl)
        legend.addStretch()
        root.addLayout(legend)

        div2 = QFrame(); div2.setObjectName("divider"); div2.setFrameShape(QFrame.HLine)
        root.addWidget(div2)

        # ── Tabs: Auto / Manual ─────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_change)
        root.addWidget(self._tabs)

        self._tabs.addTab(self._build_auto_tab(),   "🤖  Auto Mode")
        self._tabs.addTab(self._build_manual_tab(), "✏️  Manual Mode")

        # ── Bottom Buttons ──────────────────────────────────────────────────────
        div3 = QFrame(); div3.setObjectName("divider"); div3.setFrameShape(QFrame.HLine)
        root.addWidget(div3)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #585b70; font-size: 12px;")
        btn_row.addWidget(self._status_lbl, stretch=1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("btn_cancel")
        btn_cancel.setFixedHeight(38)
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("💾  Save & Close")
        btn_save.setObjectName("btn_save")
        btn_save.setFixedHeight(38)
        btn_save.clicked.connect(self._on_save)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

    # ── Auto Tab ───────────────────────────────────────────────────────────────

    def _build_auto_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        info = QLabel(
            "Click <b>Detect ROIs</b> to run YOLO on the snapshot and propose "
            "bounding boxes as ROI candidates (shown in blue).<br>"
            "Then click <b>Confirm</b> to accept them."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #a6adc8; font-size: 12px;")
        lay.addWidget(info)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._btn_detect = QPushButton("🤖  Detect ROIs")
        self._btn_detect.setObjectName("btn_detect")
        self._btn_detect.setFixedHeight(34)
        self._btn_detect.clicked.connect(self._run_auto_detect)

        self._btn_confirm_auto = QPushButton("✅  Confirm Proposals")
        self._btn_confirm_auto.setObjectName("btn_confirm_auto")
        self._btn_confirm_auto.setFixedHeight(34)
        self._btn_confirm_auto.setEnabled(False)
        self._btn_confirm_auto.clicked.connect(self._confirm_auto_rois)

        btn_row.addWidget(self._btn_detect)
        btn_row.addWidget(self._btn_confirm_auto)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._auto_info_lbl = QLabel("No proposals yet.")
        self._auto_info_lbl.setStyleSheet("color: #585b70; font-size: 12px;")
        lay.addWidget(self._auto_info_lbl)

        lay.addStretch()
        return w

    # ── Manual Tab ─────────────────────────────────────────────────────────────

    def _build_manual_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        info = QLabel(
            "Select a slot ID, then <b>drag a rectangle</b> on the camera frame above."
            "<br>The drawn rectangle becomes that slot's ROI (overwrites any previous)."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #a6adc8; font-size: 12px;")
        lay.addWidget(info)

        slot_row = QHBoxLayout()
        slot_row.setSpacing(6)

        slot_lbl = QLabel("Active Slot:")
        slot_lbl.setStyleSheet("font-weight: bold;")
        slot_row.addWidget(slot_lbl)

        self._slot_btn_container = QHBoxLayout()
        self._slot_btn_container.setSpacing(6)
        slot_row.addLayout(self._slot_btn_container)

        btn_add_slot = QPushButton("＋ Add Slot")
        btn_add_slot.setObjectName("btn_add_slot")
        btn_add_slot.setFixedHeight(32)
        btn_add_slot.clicked.connect(lambda: self._add_slot_btn())
        slot_row.addWidget(btn_add_slot)

        slot_row.addStretch()
        lay.addLayout(slot_row)

        clear_row = QHBoxLayout()
        clear_row.setSpacing(8)

        self._btn_clear_slot = QPushButton("🗑  Clear Active Slot")
        self._btn_clear_slot.setObjectName("btn_clear_slot")
        self._btn_clear_slot.setFixedHeight(32)
        self._btn_clear_slot.clicked.connect(self._clear_active_slot)

        self._btn_clear_all = QPushButton("⚠  Clear All")
        self._btn_clear_all.setObjectName("btn_clear_all")
        self._btn_clear_all.setFixedHeight(32)
        self._btn_clear_all.clicked.connect(self._clear_all_rois)

        clear_row.addWidget(self._btn_clear_slot)
        clear_row.addWidget(self._btn_clear_all)
        clear_row.addStretch()
        lay.addLayout(clear_row)

        lay.addStretch()

        # Populate initial slot buttons from existing ROIs
        existing_ids = sorted(self._rois.keys()) if self._rois else [1]
        for sid in existing_ids:
            self._add_slot_btn(slot_id=sid, set_active=False)

        if self._slot_btns:
            self._slot_btns[0].setChecked(True)
            self._canvas.active_slot_id = int(self._slot_btns[0].text())

        return w

    # ── Tab Switch ──────────────────────────────────────────────────────────────

    def _on_tab_change(self, index: int):
        is_manual = (index == 1)
        self._canvas.set_draw_enabled(is_manual)
        
        # When switching to manual, clear the "blue" auto boxes to avoid confusion
        if is_manual:
            if self._canvas.proposed_rois:
                self._canvas.proposed_rois.clear()
                self._auto_info_lbl.setText("Proposals cleared. Manual mode active.")
                self._btn_confirm_auto.setEnabled(False)
                self._canvas.update()

    # ── Auto Mode Logic ────────────────────────────────────────────────────────

    def _run_auto_detect(self):
        if self._detector is None:
            QMessageBox.warning(self, "Auto Detect",
                                "No detector passed to the dialog.")
            return

        # Check if AI model is loaded and ready
        model_ready = getattr(self._detector, 'model_loaded', False)
        if not model_ready or self._detector.model is None:
            QMessageBox.critical(
                self, "Auto Detect Error",
                "AI Model is not loaded. Auto Mode requires a valid YOLO model.\n\n"
                "Please ensure 'best.pt' exists in the project folder and the detector initialized correctly."
            )
            return

        self._btn_detect.setText("⏳  Detecting…")
        self._btn_detect.setEnabled(False)
        self._canvas.proposed_rois.clear()

        import threading

        def _detect():
            try:
                results = self._detector.model(
                    self._snapshot, imgsz=640, conf=0.3, verbose=False
                )
                boxes = []
                for r in results:
                    for box in r.boxes:
                        coords = [int(v) for v in box.xyxy[0].tolist()]
                        boxes.append(coords)

                # Sort left-to-right by x-centre → assign slot IDs 1, 2, 3…
                boxes.sort(key=lambda b: (b[0] + b[2]) / 2)
                proposed = {i + 1: b for i, b in enumerate(boxes)}
                self._sig_auto_results.emit(proposed)
            except Exception as e:
                self._sig_auto_error.emit(str(e))

        threading.Thread(target=_detect, daemon=True).start()

    @Slot(object)
    def _show_auto_results(self, proposed: dict):
        self._btn_detect.setText("🤖  Detect ROIs")
        self._btn_detect.setEnabled(True)

        if not proposed:
            self._auto_info_lbl.setText("⚠  No objects detected in the snapshot.")
            self._btn_confirm_auto.setEnabled(False)
            return

        self._canvas.proposed_rois = proposed
        self._canvas.update()
        
        # Build slot assignment report
        report = f"✅ <b>{len(proposed)} object(s) proposed:</b><br>"
        for sid, box in proposed.items():
            cx = (box[0] + box[2]) // 2
            cy = (box[1] + box[3]) // 2
            report += f" • Slot {sid}: Center({cx}, {cy})<br>"
            
        self._auto_info_lbl.setText(report)
        self._btn_confirm_auto.setEnabled(True)

    @Slot(str)
    def _show_auto_error(self, msg: str):
        self._btn_detect.setText("🤖  Detect ROIs")
        self._btn_detect.setEnabled(True)
        self._auto_info_lbl.setText(f"❌  Error: {msg}")
        QMessageBox.critical(self, "Detection Error", msg)

    @Slot()
    def _confirm_auto_rois(self):
        if not self._canvas.proposed_rois:
            return
        self._canvas.confirmed_rois.update(self._canvas.proposed_rois)
        self._canvas.proposed_rois.clear()
        self._canvas.update()
        count = len(self._canvas.confirmed_rois)
        self._auto_info_lbl.setText(
            f"✅  Confirmed. {count} slot(s) now active."
        )
        self._btn_confirm_auto.setEnabled(False)
        self._set_status(f"{count} ROI(s) confirmed from Auto Mode.")

    # ── Manual Mode Logic ──────────────────────────────────────────────────────

    def _add_slot_btn(self, slot_id: int | None = None, set_active: bool = True):
        """Add a slot-ID toggle button to the manual tab."""
        # Fix: If slot_id is a boolean (from signal), treat as None to trigger calc
        if slot_id is None or isinstance(slot_id, bool):
            # Safely calculate next ID
            ids = []
            for b in self._slot_btns:
                try:
                    text = b.text()
                    if text.isdigit():
                        ids.append(int(text))
                except (ValueError, AttributeError):
                    continue
            slot_id = max(ids, default=0) + 1

        # Prevent duplicates or empty IDs in the UI
        current_id_str = str(slot_id)
        for b in self._slot_btns:
            try:
                if b.text() == current_id_str:
                    if set_active:
                        b.setChecked(True)
                        self._select_slot(int(current_id_str) if current_id_str.isdigit() else 0)
                    return
            except (ValueError, AttributeError):
                continue

        btn = QPushButton(str(slot_id))
        btn.setProperty("slot_btn", "true")
        btn.setCheckable(True)
        btn.setFixedSize(42, 32)
        btn.clicked.connect(lambda checked, sid=slot_id: self._select_slot(sid))
        self._slot_btn_group.addButton(btn)
        self._slot_btns.append(btn)
        self._slot_btn_container.addWidget(btn)

        if set_active:
            btn.setChecked(True)
            self._select_slot(slot_id)

    def _select_slot(self, slot_id: int):
        self._canvas.active_slot_id = slot_id

    def _clear_active_slot(self):
        sid = self._canvas.active_slot_id
        # Remove from ROI dict if exists
        try:
            self._canvas.confirmed_rois.pop(int(sid), None)
        except (ValueError, TypeError):
            pass
        
        # Find and remove the button matching current selection (string comparison is safer)
        btn_to_remove = None
        sid_str = str(sid)
        for btn in self._slot_btns:
            try:
                if btn.text() == sid_str:
                    btn_to_remove = btn
                    break
            except Exception:
                continue
        
        if btn_to_remove:
            self._slot_btns.remove(btn_to_remove)
            self._slot_btn_group.removeButton(btn_to_remove)
            if self._slot_btn_container:
                self._slot_btn_container.removeWidget(btn_to_remove)
            btn_to_remove.deleteLater()

        # Selection fallback logic
        if self._slot_btns:
            next_btn = self._slot_btns[0]
            next_btn.setChecked(True)
            text = next_btn.text()
            self._select_slot(int(text) if text.isdigit() else text)
        else:
            # System reset to Slot 1 if empty
            self._canvas.active_slot_id = 1
            self._add_slot_btn(slot_id=1, set_active=True)

        self._canvas.update()
        self._set_status(f"Item '{sid}' removed from queue.")

    def _clear_all_rois(self):
        confirm = QMessageBox.question(
            self, "Clear All ROIs",
            "Remove all slot ROIs and reset buttons?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self._canvas.confirmed_rois.clear()
            self._canvas.proposed_rois.clear()
            
            # Remove all existing buttons
            for btn in self._slot_btns:
                self._slot_btn_group.removeButton(btn)
                self._slot_btn_container.removeWidget(btn)
                btn.deleteLater()
            self._slot_btns.clear()

            # Reset back to just Slot 1
            self._add_slot_btn(slot_id=1, set_active=True)
            
            self._canvas.update()
            self._set_status("All ROIs cleared.")

    # ── Manual rect drawn callback ─────────────────────────────────────────────

    def _on_manual_rect_drawn(self, slot_id: int, roi: list):
        self._set_status(
            f"Slot {slot_id} ROI drawn: "
            f"({roi[0]}, {roi[1]}) → ({roi[2]}, {roi[3]})"
        )

    # ── Save ───────────────────────────────────────────────────────────────────

    def _on_save(self):
        rois = self._canvas.confirmed_rois
        if not rois:
            confirm = QMessageBox.question(
                self, "No ROIs",
                "No ROIs are defined. This will clear existing calibration. Continue?",
                QMessageBox.Yes | QMessageBox.No
            )
            if confirm == QMessageBox.No:
                return

        self._rois = copy.deepcopy(rois)
        self.accept()

    def get_rois(self) -> dict[int, list]:
        """Returns the confirmed ROIs after the dialog is accepted."""
        return self._rois

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_status(self, msg: str):
        self._status_lbl.setText(msg)
