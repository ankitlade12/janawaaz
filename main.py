"""Render Workflows service entrypoint.

Local dev:   render workflows dev -- python main.py
On Render:   start command `python main.py` on a Workflow service.
"""

import logging

from janawaaz.workflows import app

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

if __name__ == "__main__":
    app.start()
