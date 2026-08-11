"""The container's start command must actually resolve.

``scripts/startup.sh`` ends with ``exec python -m habit_tracker``, and the image
is built with ``uv sync --no-install-project``, so the ``habit-tracker`` console
script never lands in the venv -- ``-m`` is the only way in. A missing
``__main__`` module makes the container exit immediately with
``No module named habit_tracker.__main__``, which no other test in this suite
would notice because every one of them imports the package directly.
"""

import importlib.util
import runpy
from unittest.mock import patch


def test_module_entry_point_resolves():
    """python -m habit_tracker must find a __main__ module."""
    assert importlib.util.find_spec("habit_tracker.__main__") is not None


def test_module_entry_point_invokes_main():
    """Running the module as __main__ calls the presentation entry point."""
    with patch("habit_tracker.presentation.main.main") as mock_main:
        runpy.run_module("habit_tracker", run_name="__main__")
    mock_main.assert_called_once_with()
