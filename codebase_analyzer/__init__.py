"""Log settings which have to run before any other code."""
from __future__ import annotations

from pathlib import Path

import loguru

# TODO: Make this configurable.
LOG_FILE_PATH = Path("~/ichigen-coder/.logs/").expanduser()

# Remove default sink which print to stdout and stderr
loguru.logger.remove()

# Let it print to a file and rotate every week
# TODO: see if need retention policy
logger = loguru.logger.add(str(LOG_FILE_PATH / "{time}.log"), rotation="1 week")
