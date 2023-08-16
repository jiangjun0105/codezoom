"""Log settings which have to run before any other code."""
from __future__ import annotations

from pathlib import Path

import loguru
from dotenv import load_dotenv

# TODO: Make this configurable.
LOG_FILE_PATH = Path(__file__).parent.parent / ".logs"

# Remove default sink which print to stdout and stderr
loguru.logger.remove()

# Let it print to a file and clean up logs older than 3 days
# FIXME: The retention is not working
logger = loguru.logger.add(str(LOG_FILE_PATH / "{time}.log"), retention="3 days")

load_dotenv()
