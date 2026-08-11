"""Module entry point so ``python -m habit_tracker`` works.

The container runs the bot this way (``scripts/startup.sh``) rather than via the
``habit-tracker`` console script, because the image is built with
``uv sync --no-install-project`` -- the dependencies are installed but the
project itself is not, so no console script lands in the venv. ``PYTHONPATH``
points at ``/app/src`` instead, which makes the package importable but leaves
``-m`` needing this file.
"""

from habit_tracker.presentation.main import main

if __name__ == "__main__":
    main()
