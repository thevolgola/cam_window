import threading

import unit_manager


class DummyUnit:
    def __init__(self, cam_id, url, model_path=""):
        self.cam_id = cam_id
        self.url = url
        self.model_path = model_path
        self.started = False
        self.stopped = False
        self.detect = type("D", (), {"lock": threading.Lock(), "slot_states": {}})()

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def set_rois(self, rois):
        self.rois = rois

    def get_latest_result(self):
        return None


class ResultUnit:
    def __init__(self, result):
        self._result = result

    def get_latest_result(self):
        return self._result


class SlotStateUnit:
    def __init__(self, states):
        self.detect = type("D", (), {"lock": threading.Lock(), "slot_states": states})()


def test_sync_cameras_adds_and_removes_units(monkeypatch):
    created = []

    def fake_camera_unit(cam_id, url, model_path=""):
        unit = DummyUnit(cam_id, url, model_path)
        created.append(cam_id)
        return unit

    monkeypatch.setattr(unit_manager, "CameraUnit", fake_camera_unit)

    manager = unit_manager.UnitManager()
    manager.sync_cameras([
        {"id": 1, "url": "rtsp://example/1", "model": "m1"},
        {"id": 2, "url": "rtsp://example/2", "model": "m2"},
    ])

    assert set(manager.units) == {"1", "2"}
    assert created == ["1", "2"]

    manager.sync_cameras([
        {"id": 2, "url": "rtsp://example/2", "model": "m2"},
    ])

    assert set(manager.units) == {"2"}


def test_apply_rois_sets_rois_on_each_unit(monkeypatch):
    manager = unit_manager.UnitManager()
    unit = DummyUnit("1", "rtsp://example/1")
    manager.units = {"1": unit}

    manager.apply_rois({"1": {"slot1": [1, 2, 3, 4]}})

    assert unit.rois == {"slot1": [1, 2, 3, 4]}


def test_get_all_results_filters_empty_results():
    manager = unit_manager.UnitManager()
    manager.units = {
        "1": ResultUnit(None),
        "2": ResultUnit({"frame": "x"}),
    }

    results = manager.get_all_results()
    assert results == {"2": {"frame": "x"}}


def test_get_all_slot_states_merges_multiple_units():
    manager = unit_manager.UnitManager()
    manager.units = {
        "1": SlotStateUnit({"A": "empty"}),
        "2": SlotStateUnit({"B": "occupied"}),
    }

    merged = manager.get_all_slot_states()
    assert merged == {"A": "empty", "B": "occupied"}
