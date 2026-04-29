import os

# Run Qt in headless mode for test execution.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    """Create a single QApplication instance for tests that require Qt widgets."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
