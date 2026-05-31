"""
roi_dialog.py
─────────────────────────────────────────────────────────────────────────────
ROI Setup Dialog for CamAI Ford project.

Modes
-----
Auto   – run one YOLO inference on the snapshot frame, propose the resulting
         bounding boxes as ROI candidates. User reviews and confirms.
Manual – user can draw a new ROI, then move, resize, and rotate it directly
         on the canvas. Auto proposals can also be refined here.

Usage (from mainwindow.py)
--------------------------
    snapshot = <latest numpy BGR frame>
    dlg = ROIDialog(snapshot, detector=self.detect, current_rois=self.detect.slot_rois, parent=self)
    if dlg.exec() == ROIDialog.Accepted:
        self.detect.slot_rois = dlg.get_rois()
"""

import copy
import json
import math
import os

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal, Slot
from PySide6.QtGui import QColor, QCursor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# ── Configuration Constants ───────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config_detector.json")

# ── Style ─────────────────────────────────────────────────────────────────────
STYLE = """
QDialog {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
QTabWidget::pane {
    border: 1px solid #45475a;
    border-radius: 5px;
    background: #1e1e2e;
}
QTabBar::tab {
    background: #313244;
    color: #cdd6f4;
    min-height: 34px;
    padding: 8px 22px;
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
    min-height: 28px;
    padding: 4px 10px;
    font-size: 11px;
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
    padding: 5px 12px;
    font-size: 11px;
}
QPushButton#btn_save:hover { background-color: #b5f0b0; }
QPushButton#btn_cancel {
    background-color: #45475a;
    color: #cdd6f4;
    padding: 5px 12px;
    font-size: 11px;
}
QPushButton#btn_cancel:hover { background-color: #585b70; }
QPushButton[slot_btn="true"] {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 5px;
    min-width: 48px;
    min-height: 36px;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: bold;
}
QPushButton[slot_btn="true"]:checked {
    background-color: #cba6f7;
    color: #11111b;
    border: 1px solid #cba6f7;
}
QPushButton#btn_add_slot {
    background-color: #fab387;
    color: #11111b;
    border-radius: 5px;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: bold;
}
QFrame#divider { color: #45475a; }
"""
MESSAGE_BOX_STYLE = """
QMessageBox {
    background-color: #1e1e2e;
}
QMessageBox QLabel {
    color: #f5f7ff;
    font-size: 13px;
}
QMessageBox QPushButton {
    background-color: #89b4fa;
    color: #11111b;
    border: 1px solid #74c7ec;
    border-radius: 6px;
    padding: 4px 10px;
    min-width: 64px;
    min-height: 28px;
    margin: 10px 6px 12px 6px;
    font-size: 11px;
    font-weight: bold;
}
QMessageBox QPushButton:hover {
    background-color: #a0c4fc;
}
"""

# ── Colour constants ──────────────────────────────────────────────────────────
COL_CONFIRMED = QColor("#a6e3a1")
COL_PROPOSED = QColor("#74c7ec")
COL_DRAWING = QColor("#f9e2af")
COL_SELECTED = QColor("#f38ba8")


class ROICanvas(QLabel):
    """Canvas for drawing and editing axis-aligned or rotated ROIs."""

    MIN_ROI_SIZE = 10.0
    HANDLE_RADIUS = 7
    ROTATE_HANDLE_OFFSET = 28

    def __init__(self, frame: np.ndarray, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(640, 400)
        self.setStyleSheet(
            "background-color: #11111b; border: 1px solid #45475a; border-radius: 6px;"
        )
        self.setCursor(QCursor(Qt.CrossCursor))

        self._frame: np.ndarray = frame
        self._h, self._w = frame.shape[:2]

        self.confirmed_rois: dict[int, dict] = {}
        self.proposed_rois: dict[int, dict] = {}

        self._drawing = False
        self._draw_start: QPoint | None = None
        self._draw_end: QPoint | None = None
        self._draw_enabled = False

        self.on_rect_drawn = None
        self.on_roi_selected = None
        self.on_roi_updated = None
        self.active_slot_id: int = 1
        self.selected_slot_id: int | None = None

        self._edit_mode: str | None = None
        self._edit_state: dict | None = None

        self._base_pixmap: QPixmap | None = None
        self._cached_scaled_pixmap: QPixmap | None = None
        self._last_scaled_size: QSize | None = None

        self._render()

    # ── ROI Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    @classmethod
    def normalize_roi(cls, roi: dict | list | tuple | None) -> dict | None:
        """Convert ROI data into a normalized rotated-rect dictionary."""
        if roi is None:
            return None

        try:
            if isinstance(roi, dict):
                cx = float(roi.get("cx"))
                cy = float(roi.get("cy"))
                width = max(cls.MIN_ROI_SIZE, float(roi.get("w")))
                height = max(cls.MIN_ROI_SIZE, float(roi.get("h")))
                angle = float(roi.get("angle", 0.0))
            elif isinstance(roi, (list, tuple)) and len(roi) >= 4:
                x1, y1, x2, y2 = [float(value) for value in roi[:4]]
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                width = max(cls.MIN_ROI_SIZE, abs(x2 - x1))
                height = max(cls.MIN_ROI_SIZE, abs(y2 - y1))
                angle = 0.0
            else:
                return None
        except (TypeError, ValueError):
            return None

        return {
            "cx": round(cx, 2),
            "cy": round(cy, 2),
            "w": round(width, 2),
            "h": round(height, 2),
            "angle": round(angle % 360.0, 2),
        }

    @classmethod
    def normalize_roi_map(cls, rois: dict | None) -> dict[int, dict]:
        """Normalize a ROI dictionary keyed by slot ID."""
        normalized: dict[int, dict] = {}
        for slot_id, roi in (rois or {}).items():
            try:
                sid = int(slot_id)
            except (TypeError, ValueError):
                print(f"[ROICanvas] Skipping invalid slot id {slot_id!r}")
                continue

            normalized_roi = cls.normalize_roi(roi)
            if normalized_roi is None:
                print(f"[ROICanvas] Skipping invalid ROI entry for slot {slot_id!r}")
                continue
            normalized[sid] = normalized_roi
        return normalized

    @staticmethod
    def serialize_roi(roi: dict) -> dict:
        """Round ROI values for persistence."""
        return {
            "cx": int(round(roi["cx"])),
            "cy": int(round(roi["cy"])),
            "w": int(round(roi["w"])),
            "h": int(round(roi["h"])),
            "angle": round(float(roi.get("angle", 0.0)) % 360.0, 2),
        }

    @classmethod
    def serialize_roi_map(cls, rois: dict[int, dict]) -> dict[int, dict]:
        return {int(slot_id): cls.serialize_roi(roi) for slot_id, roi in rois.items()}

    @staticmethod
    def _rotate_point(x: float, y: float, angle_deg: float) -> tuple[float, float]:
        radians = math.radians(angle_deg)
        cos_a = math.cos(radians)
        sin_a = math.sin(radians)
        return x * cos_a - y * sin_a, x * sin_a + y * cos_a

    @classmethod
    def _roi_local_corners(cls, roi: dict) -> list[tuple[float, float]]:
        half_w = roi["w"] / 2.0
        half_h = roi["h"] / 2.0
        return [
            (-half_w, -half_h),
            (half_w, -half_h),
            (half_w, half_h),
            (-half_w, half_h),
        ]

    @classmethod
    def roi_points(cls, roi: dict) -> list[tuple[float, float]]:
        """Return ROI corner points in frame coordinates."""
        points: list[tuple[float, float]] = []
        for local_x, local_y in cls._roi_local_corners(roi):
            rot_x, rot_y = cls._rotate_point(local_x, local_y, roi["angle"])
            points.append((roi["cx"] + rot_x, roi["cy"] + rot_y))
        return points

    @classmethod
    def roi_label_points(cls, roi: dict, mapper) -> list[QPoint]:
        return [mapper(x, y) for x, y in cls.roi_points(roi)]

    def _label_to_frame_float(self, pt: QPoint) -> tuple[float, float]:
        sr = self._scaled_rect()
        fx = (pt.x() - sr.x()) / sr.width() * self._w
        fy = (pt.y() - sr.y()) / sr.height() * self._h
        fx = self._clamp(fx, 0, self._w - 1)
        fy = self._clamp(fy, 0, self._h - 1)
        return fx, fy

    def _frame_to_label_float(self, x: float, y: float) -> tuple[float, float]:
        sr = self._scaled_rect()
        lx = x / self._w * sr.width() + sr.x()
        ly = y / self._h * sr.height() + sr.y()
        return lx, ly

    def _roi_handles(self, roi: dict) -> dict:
        corners = self.roi_label_points(roi, self._frame_to_label)
        top_mid_x = (corners[0].x() + corners[1].x()) / 2.0
        top_mid_y = (corners[0].y() + corners[1].y()) / 2.0
        center_x = sum(point.x() for point in corners) / len(corners)
        center_y = sum(point.y() for point in corners) / len(corners)
        vec_x = top_mid_x - center_x
        vec_y = top_mid_y - center_y
        length = math.hypot(vec_x, vec_y) or 1.0
        rotate_x = top_mid_x + vec_x / length * self.ROTATE_HANDLE_OFFSET
        rotate_y = top_mid_y + vec_y / length * self.ROTATE_HANDLE_OFFSET

        return {
            "corners": corners,
            "rotate": QPoint(int(rotate_x), int(rotate_y)),
            "top_mid": QPoint(int(top_mid_x), int(top_mid_y)),
        }

    def _distance(self, p1: QPoint, p2: QPoint) -> float:
        return math.hypot(p1.x() - p2.x(), p1.y() - p2.y())

    def _roi_contains_point(self, roi: dict, label_pos: QPoint) -> bool:
        polygon = np.array(
            [[point.x(), point.y()] for point in self.roi_label_points(roi, self._frame_to_label)],
            dtype=np.float32,
        )
        return cv2.pointPolygonTest(polygon, (label_pos.x(), label_pos.y()), False) >= 0

    def _hit_test(self, label_pos: QPoint) -> tuple[str | None, int | None, int | None]:
        for slot_id in sorted(self.confirmed_rois.keys(), reverse=True):
            roi = self.confirmed_rois[slot_id]
            handles = self._roi_handles(roi)

            if self._distance(label_pos, handles["rotate"]) <= self.HANDLE_RADIUS + 2:
                return "rotate", slot_id, None

            for index, corner in enumerate(handles["corners"]):
                if self._distance(label_pos, corner) <= self.HANDLE_RADIUS + 2:
                    return "resize", slot_id, index

            if self._roi_contains_point(roi, label_pos):
                return "move", slot_id, None

        return None, None, None

    def _clip_roi(self, roi: dict) -> dict:
        roi = copy.deepcopy(roi)
        roi["cx"] = round(self._clamp(roi["cx"], 0, self._w - 1), 2)
        roi["cy"] = round(self._clamp(roi["cy"], 0, self._h - 1), 2)
        roi["w"] = round(
            max(self.MIN_ROI_SIZE, min(roi["w"], max(1.0, float(self._w)))),
            2,
        )
        roi["h"] = round(
            max(self.MIN_ROI_SIZE, min(roi["h"], max(1.0, float(self._h)))),
            2,
        )
        roi["angle"] = round(roi.get("angle", 0.0) % 360.0, 2)
        return roi

    def _set_selected_slot(self, slot_id: int | None, emit_callback: bool = True) -> None:
        self.selected_slot_id = slot_id
        if slot_id is not None:
            self.active_slot_id = slot_id
        if emit_callback and callable(self.on_roi_selected) and slot_id is not None:
            self.on_roi_selected(slot_id)
        self.update()

    def _notify_roi_updated(self, slot_id: int) -> None:
        if callable(self.on_roi_updated):
            self.on_roi_updated(slot_id, copy.deepcopy(self.confirmed_rois[slot_id]))

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_frame(self, frame: np.ndarray) -> None:
        self._frame = frame
        self._h, self._w = frame.shape[:2]
        self._render()

    def set_draw_enabled(self, enabled: bool) -> None:
        self._draw_enabled = enabled
        self.setCursor(QCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor))

    def replace_confirmed_rois(self, rois: dict[int, dict]) -> None:
        self.confirmed_rois = self.normalize_roi_map(rois)
        if self.selected_slot_id not in self.confirmed_rois:
            fallback = self.active_slot_id if self.active_slot_id in self.confirmed_rois else None
            self._set_selected_slot(fallback, emit_callback=False)
        self.update()

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
        fx, fy = self._label_to_frame_float(pt)
        return int(round(fx)), int(round(fy))

    def _frame_to_label(self, x: float, y: float) -> QPoint:
        """Convert original frame pixel → label pixel."""
        lx, ly = self._frame_to_label_float(x, y)
        return QPoint(int(round(lx)), int(round(ly)))

    # ── Rendering ──────────────────────────────────────────────────────────────

    def _render(self) -> None:
        """Convert numpy frame to QPixmap and store (paint happens in paintEvent)."""
        rgb = cv2.cvtColor(self._frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        self._base_pixmap = QPixmap.fromImage(qimg)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        sr = self._scaled_rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self._base_pixmap:
            if self._cached_scaled_pixmap is None or self._last_scaled_size != sr.size():
                self._cached_scaled_pixmap = self._base_pixmap.scaled(
                    sr.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self._last_scaled_size = sr.size()
            painter.drawPixmap(sr.topLeft(), self._cached_scaled_pixmap)

        def draw_roi(roi: dict, color: QColor, slot_id: int, label_prefix: str, selected: bool = False) -> None:
            points = self.roi_label_points(roi, self._frame_to_label)
            polygon = np.array([[point.x(), point.y()] for point in points], dtype=np.int32)

            pen = QPen(COL_SELECTED if selected else color, 3 if selected else 2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(*points)

            min_x = int(np.min(polygon[:, 0]))
            min_y = int(np.min(polygon[:, 1]))
            tag = f"{label_prefix}{slot_id}"
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(tag) + 8
            th = fm.height() + 4
            bg = QRect(min_x, min_y - th, tw, th)
            painter.fillRect(bg, COL_SELECTED if selected else color)
            painter.setPen(QColor("#11111b"))
            painter.drawText(bg, Qt.AlignCenter, tag)

            if selected:
                handles = self._roi_handles(roi)
                painter.setPen(QPen(COL_SELECTED, 2))
                painter.drawLine(handles["top_mid"], handles["rotate"])
                painter.setBrush(COL_SELECTED)
                for corner in handles["corners"]:
                    painter.drawEllipse(corner, self.HANDLE_RADIUS, self.HANDLE_RADIUS)
                painter.setBrush(COL_DRAWING)
                painter.drawEllipse(handles["rotate"], self.HANDLE_RADIUS, self.HANDLE_RADIUS)

        for sid, roi in self.proposed_rois.items():
            draw_roi(roi, COL_PROPOSED, sid, "Auto ")

        for sid, roi in self.confirmed_rois.items():
            draw_roi(roi, COL_CONFIRMED, sid, "Slot ", selected=(sid == self.selected_slot_id))

        if self._drawing and self._draw_start and self._draw_end:
            pen = QPen(COL_DRAWING, 2, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRect(self._draw_start, self._draw_end).normalized())

        painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update()

    # ── Mouse Events ───────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if not self._draw_enabled or event.button() != Qt.LeftButton:
            return

        label_pos = event.position().toPoint()
        hit_mode, slot_id, handle_index = self._hit_test(label_pos)
        if slot_id is not None and slot_id in self.confirmed_rois:
            self._set_selected_slot(slot_id)
            roi = copy.deepcopy(self.confirmed_rois[slot_id])
            frame_x, frame_y = self._label_to_frame_float(label_pos)
            self._edit_mode = hit_mode

            if hit_mode == "move":
                self._edit_state = {
                    "offset_x": frame_x - roi["cx"],
                    "offset_y": frame_y - roi["cy"],
                }
                return

            if hit_mode == "rotate":
                self._edit_state = {
                    "start_angle": roi["angle"],
                    "start_mouse_angle": math.degrees(math.atan2(frame_y - roi["cy"], frame_x - roi["cx"])),
                    "center_x": roi["cx"],
                    "center_y": roi["cy"],
                }
                return

            if hit_mode == "resize" and handle_index is not None:
                self._edit_state = {
                    "base_roi": roi,
                    "anchor_index": (handle_index + 2) % 4,
                }
                return

        self._edit_mode = None
        self._edit_state = None
        self._drawing = True
        self._set_selected_slot(None, emit_callback=False)
        self._draw_start = label_pos
        self._draw_end = label_pos
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if not self._draw_enabled:
            return

        label_pos = event.position().toPoint()

        if self._drawing:
            self._draw_end = label_pos
            self.update()
            return

        if not self._edit_mode or self.selected_slot_id is None or self.selected_slot_id not in self.confirmed_rois:
            return

        roi = copy.deepcopy(self.confirmed_rois[self.selected_slot_id])
        frame_x, frame_y = self._label_to_frame_float(label_pos)

        if self._edit_mode == "move":
            roi["cx"] = frame_x - self._edit_state["offset_x"]
            roi["cy"] = frame_y - self._edit_state["offset_y"]
        elif self._edit_mode == "rotate":
            current_mouse_angle = math.degrees(math.atan2(
                frame_y - self._edit_state["center_y"],
                frame_x - self._edit_state["center_x"],
            ))
            delta = current_mouse_angle - self._edit_state["start_mouse_angle"]
            roi["angle"] = self._edit_state["start_angle"] + delta
        elif self._edit_mode == "resize":
            base_roi = self._edit_state["base_roi"]
            anchor_index = self._edit_state["anchor_index"]
            anchor_local = self._roi_local_corners(base_roi)[anchor_index]
            local_x, local_y = self._rotate_point(
                frame_x - base_roi["cx"],
                frame_y - base_roi["cy"],
                -base_roi["angle"],
            )
            width = max(self.MIN_ROI_SIZE, abs(local_x - anchor_local[0]))
            height = max(self.MIN_ROI_SIZE, abs(local_y - anchor_local[1]))
            center_local_x = (anchor_local[0] + local_x) / 2.0
            center_local_y = (anchor_local[1] + local_y) / 2.0
            offset_x, offset_y = self._rotate_point(center_local_x, center_local_y, base_roi["angle"])
            roi["cx"] = base_roi["cx"] + offset_x
            roi["cy"] = base_roi["cy"] + offset_y
            roi["w"] = width
            roi["h"] = height

        self.confirmed_rois[self.selected_slot_id] = self._clip_roi(roi)
        self._notify_roi_updated(self.selected_slot_id)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return

        if self._drawing:
            self._drawing = False
            self._draw_end = event.position().toPoint()

            fx1, fy1 = self._label_to_frame(self._draw_start)
            fx2, fy2 = self._label_to_frame(self._draw_end)

            x1, x2 = min(fx1, fx2), max(fx1, fx2)
            y1, y2 = min(fy1, fy2), max(fy1, fy2)

            if (x2 - x1) >= self.MIN_ROI_SIZE and (y2 - y1) >= self.MIN_ROI_SIZE:
                roi = self.normalize_roi([x1, y1, x2, y2])
                self.confirmed_rois[self.active_slot_id] = roi
                self._set_selected_slot(self.active_slot_id)
                if callable(self.on_rect_drawn):
                    self.on_rect_drawn(self.active_slot_id, copy.deepcopy(roi))
                self._notify_roi_updated(self.active_slot_id)

            self._draw_start = None
            self._draw_end = None
            self.update()
            return

        self._edit_mode = None
        self._edit_state = None
        self.update()


class ROIDialog(QDialog):
    """Modal dialog for setting up slot ROIs."""

    _sig_auto_results = Signal(object)
    _sig_auto_error = Signal(str)

    def __init__(self, snapshot: np.ndarray, detector=None, current_rois: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📐  ROI Setup")
        self.setMinimumSize(780, 600)
        self.setStyleSheet(STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._snapshot = snapshot
        self._detector = detector
        self._rois: dict[int, dict] = self.normalize_rois(current_rois)

        self._slot_btns: list[QPushButton] = []
        self._slot_btn_group = QButtonGroup(self)
        self._slot_btn_group.setExclusive(True)

        self._sig_auto_results.connect(self._show_auto_results)
        self._sig_auto_error.connect(self._show_auto_error)

        self._build_ui()
        self._canvas.replace_confirmed_rois(copy.deepcopy(self._rois))

    @staticmethod
    def normalize_rois(rois: dict | None) -> dict[int, dict]:
        """Return normalized ROIs with integer slot IDs."""
        return ROICanvas.normalize_roi_map(rois)

    @staticmethod
    def serialize_rois(rois: dict | None) -> dict[int, dict]:
        """Prepare ROI payload for persistence."""
        return ROICanvas.serialize_roi_map(ROIDialog.normalize_rois(rois))

    @staticmethod
    def load_rois() -> dict[int, dict]:
        """Utility to load ROIs from disk without opening the dialog."""
        file_path = os.path.join(BASE_DIR, CONFIG_FILE)
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as file_obj:
                    data = json.load(file_obj)
                    return ROIDialog.normalize_rois(data)
            except Exception as error:
                print(f"[ROIDialog] Load Error: {error}")
        return {}

    # ── UI Construction ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel("ROI Setup")
        title.setFont(QFont("Arial", 15, QFont.Bold))
        title.setStyleSheet("color: #cba6f7;")
        root.addWidget(title)

        intro = QLabel(
            "Configure parking slot detection areas. Use <b>Auto Mode</b> to find slots using AI, "
            "or <b>Manual Mode</b> to draw, move, resize, and rotate them."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #a6adc8; font-size: 13px; margin-bottom: 4px;")
        root.addWidget(intro)

        div = QFrame()
        div.setObjectName("divider")
        div.setFrameShape(QFrame.HLine)
        root.addWidget(div)

        self._canvas = ROICanvas(self._snapshot, parent=self)
        self._canvas.on_rect_drawn = self._on_manual_rect_drawn
        self._canvas.on_roi_selected = self._on_canvas_roi_selected
        self._canvas.on_roi_updated = self._on_canvas_roi_updated
        root.addWidget(self._canvas, stretch=1)

        legend = QHBoxLayout()
        legend.setSpacing(16)
        for text, color in [
            ("● Confirmed", "#a6e3a1"),
            ("● Proposed", "#89b4fa"),
            ("● Selected", "#f38ba8"),
            ("● Drawing", "#f9e2af"),
        ]:
            label = QLabel(text)
            label.setStyleSheet(f"color: {color}; font-size: 12px;")
            legend.addWidget(label)
        legend.addStretch()
        root.addLayout(legend)

        div2 = QFrame()
        div2.setObjectName("divider")
        div2.setFrameShape(QFrame.HLine)
        root.addWidget(div2)

        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_change)
        root.addWidget(self._tabs)

        self._tabs.addTab(self._build_auto_tab(), "🤖  Auto Mode")
        self._tabs.addTab(self._build_manual_tab(), "✏️  Manual Mode")

        div3 = QFrame()
        div3.setObjectName("divider")
        div3.setFrameShape(QFrame.HLine)
        root.addWidget(div3)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #585b70; font-size: 12px;")
        btn_row.addWidget(self._status_lbl, stretch=1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("btn_cancel")
        btn_cancel.setMinimumHeight(28)
        btn_cancel.setMinimumWidth(82)
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("💾  Save & Close")
        btn_save.setObjectName("btn_save")
        btn_save.setMinimumHeight(28)
        btn_save.setMinimumWidth(112)
        btn_save.clicked.connect(self._on_save)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

    def _show_message(
        self,
        icon: QMessageBox.Icon,
        title: str,
        text: str,
        buttons: QMessageBox.StandardButton = QMessageBox.Ok,
        default_button: QMessageBox.StandardButton | None = None,
        informative_text: str | None = None,
    ) -> QMessageBox.StandardButton:
        """Show a simple native message box with optional explanatory text."""
        main_text = text
        detail_text = informative_text
        if detail_text is None and "\n\n" in text:
            main_text, detail_text = text.split("\n\n", 1)

        msg_box = QMessageBox(self)
        msg_box.setIcon(icon)
        msg_box.setWindowTitle(title)
        msg_box.setText(main_text)
        if detail_text:
            msg_box.setInformativeText(detail_text)
        msg_box.setStandardButtons(buttons)
        if default_button is not None:
            msg_box.setDefaultButton(default_button)
        msg_box.setStyleSheet(MESSAGE_BOX_STYLE)
        if msg_box.layout() is not None:
            msg_box.layout().setContentsMargins(16, 14, 16, 22)
            msg_box.layout().setSpacing(12)
        text_label = msg_box.findChild(QLabel, "qt_msgbox_label")
        if text_label is not None:
            text_label.setWordWrap(True)
            text_label.setMinimumWidth(360)
            text_label.setMaximumWidth(440)
            text_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            text_label.setContentsMargins(6, 0, 0, 0)
        info_label = msg_box.findChild(QLabel, "qt_msgbox_informativelabel")
        if info_label is not None:
            info_label.setWordWrap(True)
            info_label.setMinimumWidth(360)
            info_label.setMaximumWidth(440)
            info_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            info_label.setContentsMargins(6, 2, 0, 0)
        icon_label = msg_box.findChild(QLabel, "qt_msgboxex_icon_label")
        if icon_label is not None:
            icon_label.setFixedWidth(46)
            icon_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        msg_box.adjustSize()
        size_hint = msg_box.sizeHint()
        msg_box.resize(max(size_hint.width(), 580), max(size_hint.height(), 220))
        return QMessageBox.StandardButton(msg_box.exec())

    def _build_auto_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)

        info = QLabel(
            "Click <b>Detect ROIs</b> to run YOLO on the snapshot and propose "
            "bounding boxes as ROI candidates (shown in blue).<br>"
            "You can confirm them directly, or switch to <b>Manual Mode</b> to fine-tune first."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(info)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._btn_detect = QPushButton("🤖  Detect ROIs")
        self._btn_detect.setObjectName("btn_detect")
        self._btn_detect.setMinimumHeight(28)
        self._btn_detect.setMinimumWidth(108)
        self._btn_detect.clicked.connect(self._run_auto_detect)

        self._btn_confirm_auto = QPushButton("✅  Confirm Proposals")
        self._btn_confirm_auto.setObjectName("btn_confirm_auto")
        self._btn_confirm_auto.setMinimumHeight(28)
        self._btn_confirm_auto.setMinimumWidth(132)
        self._btn_confirm_auto.setEnabled(False)
        self._btn_confirm_auto.clicked.connect(self._confirm_auto_rois)

        btn_row.addWidget(self._btn_detect)
        btn_row.addWidget(self._btn_confirm_auto)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._auto_info_lbl = QLabel("No proposals yet.")
        self._auto_info_lbl.setStyleSheet("color: #585b70; font-size: 12px;")
        self._auto_info_lbl.setWordWrap(True)
        layout.addWidget(self._auto_info_lbl)

        layout.addStretch()
        return widget

    def _build_manual_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)

        info = QLabel(
            "Select a slot ID, then <b>drag on empty space</b> to draw a new ROI."
            "<br><b>Click an existing ROI</b> to select it, drag inside to move it,"
            " drag a corner handle to resize it, or drag the top handle to rotate it."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(info)

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
        btn_add_slot.setMinimumHeight(28)
        btn_add_slot.setMinimumWidth(86)
        btn_add_slot.clicked.connect(lambda: self._add_slot_btn())
        slot_row.addWidget(btn_add_slot)

        slot_row.addStretch()
        layout.addLayout(slot_row)

        clear_row = QHBoxLayout()
        clear_row.setSpacing(8)

        self._btn_clear_slot = QPushButton("🗑  Clear Active Slot")
        self._btn_clear_slot.setObjectName("btn_clear_slot")
        self._btn_clear_slot.setMinimumHeight(28)
        self._btn_clear_slot.setMinimumWidth(122)
        self._btn_clear_slot.clicked.connect(self._clear_active_slot)

        self._btn_clear_all = QPushButton("⚠  Clear All")
        self._btn_clear_all.setObjectName("btn_clear_all")
        self._btn_clear_all.setMinimumHeight(28)
        self._btn_clear_all.setMinimumWidth(86)
        self._btn_clear_all.clicked.connect(self._clear_all_rois)

        clear_row.addWidget(self._btn_clear_slot)
        clear_row.addWidget(self._btn_clear_all)
        clear_row.addStretch()
        layout.addLayout(clear_row)

        layout.addStretch()

        existing_ids = sorted(self._rois.keys()) if self._rois else [1]
        for slot_id in existing_ids:
            self._add_slot_btn(slot_id=slot_id, set_active=False)

        if self._slot_btns:
            self._set_active_slot_button(int(self._slot_btns[0].text()))

        return widget

    # ── Slot Button Helpers ────────────────────────────────────────────────────

    def _set_active_slot_button(self, slot_id: int) -> None:
        for button in self._slot_btns:
            if button.text() == str(slot_id):
                button.setChecked(True)
                break
        self._select_slot(slot_id)

    def _ensure_slot_buttons(self, slot_ids: list[int]) -> None:
        for slot_id in sorted(slot_ids):
            self._add_slot_btn(slot_id=slot_id, set_active=False)

    # ── Tab Switch ─────────────────────────────────────────────────────────────

    def _on_tab_change(self, index: int) -> None:
        is_manual = index == 1
        self._canvas.set_draw_enabled(is_manual)
        if is_manual and self._canvas.proposed_rois:
            self._promote_proposals_to_manual()

    # ── Auto Mode Logic ────────────────────────────────────────────────────────

    def _run_auto_detect(self) -> None:
        if self._detector is None:
            self._show_message(
                QMessageBox.Icon.Warning,
                "Auto Detect",
                "Auto detection is unavailable.",
            )
            return

        model_ready = getattr(self._detector, "model_loaded", False)
        if not model_ready or self._detector.model is None:
            self._show_message(
                QMessageBox.Icon.Critical,
                "Auto Detect Error",
                "AI model is not loaded.",
            )
            return

        self._btn_detect.setText("⏳  Detecting…")
        self._btn_detect.setEnabled(False)
        self._canvas.proposed_rois.clear()

        def _detect() -> None:
            try:
                results = self._detector.model(self._snapshot, imgsz=640, conf=0.3, verbose=False)
                boxes = []
                for result in results:
                    for box in result.boxes:
                        coords = [int(value) for value in box.xyxy[0].tolist()]
                        normalized = ROICanvas.normalize_roi(coords)
                        if normalized is not None:
                            boxes.append(normalized)

                boxes.sort(key=lambda roi: roi["cx"])
                proposed = {index + 1: roi for index, roi in enumerate(boxes)}
                self._sig_auto_results.emit(proposed)
            except Exception as error:
                self._sig_auto_error.emit(str(error))

        import threading

        threading.Thread(target=_detect, daemon=True).start()

    @Slot(object)
    def _show_auto_results(self, proposed: dict) -> None:
        self._btn_detect.setText("🤖  Detect ROIs")
        self._btn_detect.setEnabled(True)

        if not proposed:
            self._auto_info_lbl.setText("⚠ No objects detected in the snapshot.")
            self._btn_confirm_auto.setEnabled(False)
            return

        self._canvas.proposed_rois = self.normalize_rois(proposed)
        self._canvas.update()

        report = f"✅ <b>{len(proposed)} object(s) proposed:</b><br>"
        for slot_id, roi in self._canvas.proposed_rois.items():
            report += (
                f" • Slot {slot_id}: center({int(round(roi['cx']))}, {int(round(roi['cy']))}), "
                f"size({int(round(roi['w']))}×{int(round(roi['h']))})<br>"
            )

        self._auto_info_lbl.setText(report)
        self._btn_confirm_auto.setEnabled(True)

    @Slot(str)
    def _show_auto_error(self, msg: str) -> None:
        self._btn_detect.setText("🤖  Detect ROIs")
        self._btn_detect.setEnabled(True)
        self._auto_info_lbl.setText(f"❌ Error: {msg}")
        self._show_message(QMessageBox.Icon.Critical, "Detection Error", msg)

    @Slot()
    def _confirm_auto_rois(self) -> None:
        if not self._canvas.proposed_rois:
            return
        self._promote_proposals_to_manual()
        count = len(self._canvas.confirmed_rois)
        self._auto_info_lbl.setText(f"✅ Confirmed. {count} slot(s) now active.")
        self._btn_confirm_auto.setEnabled(False)
        self._set_status(f"{count} ROI(s) confirmed from Auto Mode.")

    def _promote_proposals_to_manual(self) -> None:
        if not self._canvas.proposed_rois:
            return

        for slot_id, roi in self._canvas.proposed_rois.items():
            self._canvas.confirmed_rois[slot_id] = copy.deepcopy(roi)

        promoted_ids = sorted(self._canvas.proposed_rois.keys())
        self._canvas.proposed_rois.clear()
        self._ensure_slot_buttons(promoted_ids)

        if promoted_ids:
            self._set_active_slot_button(promoted_ids[0])
            self._canvas._set_selected_slot(promoted_ids[0], emit_callback=False)

        self._canvas.update()
        self._btn_confirm_auto.setEnabled(False)
        self._set_status("Auto proposals moved into Manual Mode for editing.")

    # ── Manual Mode Logic ──────────────────────────────────────────────────────

    def _add_slot_btn(self, slot_id: int | None = None, set_active: bool = True) -> None:
        """Add a slot-ID toggle button to the manual tab."""
        if slot_id is None or isinstance(slot_id, bool):
            slot_id = max([int(button.text()) for button in self._slot_btns], default=0) + 1

        current_id = str(slot_id)
        for button in self._slot_btns:
            if button.text() == current_id:
                if set_active:
                    self._set_active_slot_button(slot_id)
                return

        button = QPushButton(current_id)
        button.setProperty("slot_btn", "true")
        button.setCheckable(True)
        button.setMinimumSize(48, 36)
        button.clicked.connect(lambda checked, sid=slot_id: self._select_slot(sid))
        self._slot_btn_group.addButton(button)
        self._slot_btns.append(button)
        self._slot_btn_container.addWidget(button)

        if set_active:
            self._set_active_slot_button(slot_id)

    def _select_slot(self, slot_id: int) -> None:
        self._canvas.active_slot_id = slot_id
        if slot_id in self._canvas.confirmed_rois:
            self._canvas._set_selected_slot(slot_id, emit_callback=False)
        else:
            self._canvas.selected_slot_id = None
            self._canvas.update()

    def _clear_active_slot(self) -> None:
        slot_id = self._canvas.active_slot_id
        self._canvas.confirmed_rois.pop(int(slot_id), None)
        self._canvas.proposed_rois.pop(int(slot_id), None)

        button_to_remove = next((button for button in self._slot_btns if button.text() == str(slot_id)), None)
        if button_to_remove:
            self._slot_btns.remove(button_to_remove)
            self._slot_btn_group.removeButton(button_to_remove)
            self._slot_btn_container.removeWidget(button_to_remove)
            button_to_remove.deleteLater()

        if self._slot_btns:
            next_slot_id = int(self._slot_btns[0].text())
            self._set_active_slot_button(next_slot_id)
        else:
            self._add_slot_btn(slot_id=1, set_active=True)

        self._canvas.update()
        self._set_status(f"Slot {slot_id} cleared.")

    def _clear_all_rois(self) -> None:
        confirm = self._show_message(
            QMessageBox.Icon.Question,
            "Clear All ROIs",
            "Remove all slot ROIs and reset buttons?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self._canvas.confirmed_rois.clear()
        self._canvas.proposed_rois.clear()
        self._canvas.selected_slot_id = None

        for button in self._slot_btns:
            self._slot_btn_group.removeButton(button)
            self._slot_btn_container.removeWidget(button)
            button.deleteLater()
        self._slot_btns.clear()

        self._add_slot_btn(slot_id=1, set_active=True)
        self._canvas.update()
        self._set_status("All ROIs cleared.")

    def _on_manual_rect_drawn(self, slot_id: int, roi: dict) -> None:
        self._ensure_slot_buttons([slot_id])
        self._set_active_slot_button(slot_id)
        self._set_status(
            f"Slot {slot_id}: center({int(round(roi['cx']))}, {int(round(roi['cy']))}), "
            f"size({int(round(roi['w']))}×{int(round(roi['h']))}), angle {roi['angle']:.1f}°"
        )

    def _on_canvas_roi_selected(self, slot_id: int) -> None:
        self._ensure_slot_buttons([slot_id])
        self._set_active_slot_button(slot_id)

    def _on_canvas_roi_updated(self, slot_id: int, roi: dict) -> None:
        self._ensure_slot_buttons([slot_id])
        self._set_status(
            f"Slot {slot_id}: center({int(round(roi['cx']))}, {int(round(roi['cy']))}), "
            f"size({int(round(roi['w']))}×{int(round(roi['h']))}), angle {roi['angle']:.1f}°"
        )

    # ── Save ───────────────────────────────────────────────────────────────────

    def _on_save(self) -> None:
        rois = self._canvas.confirmed_rois
        if not rois:
            confirm = self._show_message(
                QMessageBox.Icon.Question,
                "No ROIs",
                "This will clear existing calibration. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirm == QMessageBox.No:
                return

        self._rois = self.serialize_rois(copy.deepcopy(rois))
        self.accept()

    def get_rois(self) -> dict[int, dict]:
        """Returns the confirmed ROIs after the dialog is accepted."""
        return self._rois

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        self._status_lbl.setText(msg)
