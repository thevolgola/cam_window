import os
import threading

import numpy as np
import pytest

import mainwindow


class FakeCamera:
    def __init__(self):
        self.is_connected = False

    def is_connecting(self):
        return False

    def is_waiting_for_refresh(self):
        return True

    def get_status_text(self):
        return "Offline"


class FakeDetect:
    def __init__(self):
        self.enabled = False
        self.slot_rois = {}
        self.slot_states = {"1": "empty"}
        self.lock = threading.Lock()


class FakeUnit:
    def __init__(self, cam_id: str):
        self.cam_id = cam_id
        self.detect = FakeDetect()
        self.camera = FakeCamera()

    def set_detection_enabled(self, enabled: bool):
        self.detect.enabled = enabled

    def request_camera_refresh(self):
        return True, "Refresh requested"


class FakeUnitManager:
    def __init__(self):
        self.units = {"1": FakeUnit("1"), "2": FakeUnit("2")}
        self.synced_cameras = None

    def sync_cameras(self, camera_configs):
        self.synced_cameras = camera_configs
        self.units = {str(cam["id"]): FakeUnit(str(cam["id"])) for cam in camera_configs}

    def get_unit(self, cam_id):
        return self.units.get(str(cam_id))

    def get_all_active_ids(self):
        return list(self.units.keys())

    def get_all_results(self):
        frame = np.zeros((32, 32, 3), dtype=np.uint8)
        return {"1": {"frame": frame, "raw_frame": frame.copy(), "slots": {"A": "empty"}}}

    def get_all_slot_states(self):
        return {"A": "empty"}

    def apply_rois(self, rois_config):
        self.rois_applied = rois_config


class FakeWebSocket:
    def __init__(self, host, port):
        self.clients = []
        self.sent = None

    def start(self):
        pass

    def stop(self):
        pass

    def is_alive(self):
        return False

    def send_data_to_all(self, data):
        self.sent = data


@pytest.fixture
def fake_mainwindow(monkeypatch, app):
    """Create a MainWindow instance with mocked dependencies for logic testing."""
    monkeypatch.setattr(mainwindow, "UnitManager", FakeUnitManager)
    monkeypatch.setattr(mainwindow, "WebSocketModule", FakeWebSocket)
    monkeypatch.setattr(mainwindow, "load_settings", lambda: {
        "cameras": [
            {"id": 1, "name": "Camera 1", "url": "rtsp://example/1", "model": "best.pt"},
            {"id": 2, "name": "Camera 2", "url": "rtsp://example/2", "model": ""},
        ],
        "websocket": {"host": "0.0.0.0", "port": 8765},
    })
    monkeypatch.setattr(mainwindow.MainWindow, "load_rois", lambda self: None)
    window = mainwindow.MainWindow()
    return window


def test_toggle_sidebar_hides_and_shows_widgets(fake_mainwindow):
    assert fake_mainwindow.sidebar_expanded is True

    fake_mainwindow._toggle_sidebar()
    assert fake_mainwindow.sidebar_expanded is False
    assert fake_mainwindow.btn_toggle_sidebar.toolTip() == "Expand sidebar"

    fake_mainwindow._toggle_sidebar()
    assert fake_mainwindow.sidebar_expanded is True
    assert fake_mainwindow.btn_toggle_sidebar.toolTip() == "Collapse sidebar"


def test_select_relative_camera_wraps_to_first_camera(fake_mainwindow):
    fake_mainwindow._app_settings["cameras"] = [
        {"id": 1, "name": "Camera 1", "url": "rtsp://example/1", "model": "best.pt"},
        {"id": 2, "name": "Camera 2", "url": "rtsp://example/2", "model": ""},
    ]
    fake_mainwindow.active_camera_id = "2"

    fake_mainwindow._select_relative_camera(1)

    assert fake_mainwindow.active_camera_id == "1"


def test_toggle_camera_list_switches_view_mode(fake_mainwindow):
    assert fake_mainwindow.grid_mode is False

    fake_mainwindow._toggle_camera_list()
    assert fake_mainwindow.grid_mode is True
    assert fake_mainwindow.video_stack.currentIndex() == 1

    fake_mainwindow._toggle_camera_list()
    assert fake_mainwindow.grid_mode is False
    assert fake_mainwindow.video_stack.currentIndex() == 0


def test_resolve_model_path_returns_absolute_for_absolute_paths(fake_mainwindow):
    path = os.path.abspath("weights/best.pt")
    assert fake_mainwindow._resolve_model_path(path) == path


def test_resolve_model_path_resolves_relative_paths(fake_mainwindow):
    relative = "weights/best.pt"
    resolved = fake_mainwindow._resolve_model_path(relative)
    expected = os.path.normpath(os.path.join("weights", "best.pt"))
    assert os.path.normpath(resolved).endswith(expected)


def test_update_ui_broadcasts_slot_states(fake_mainwindow):
    fake_mainwindow.grid_mode = False
    fake_mainwindow._app_settings["cameras"] = [
        {"id": 1, "name": "Camera 1", "url": "rtsp://example/1", "model": "best.pt"},
    ]
    fake_mainwindow.active_camera_id = "1"
    fake_mainwindow.unit_manager.units = {"1": FakeUnit("1")}

    fake_mainwindow.update_ui()

    assert fake_mainwindow.ws_server.sent == {"A": "empty"}
    assert fake_mainwindow.conn_label.text().startswith("WEBSOCKET:")


def test_refresh_url_label_shows_active_stream_count(fake_mainwindow):
    fake_mainwindow.unit_manager.units = {"1": FakeUnit("1"), "2": FakeUnit("2")}
    fake_mainwindow._refresh_url_label()
    assert "Active Streams: 2" in fake_mainwindow.cam_url_label.text()
