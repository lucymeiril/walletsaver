"""Web-api process configuration.

Only process-level settings used by the current web runtime live here. Storage
paths are owned by the dedicated web-api storage services through their
``WALLETSAVIOR_*`` environment variables, and OAuth loads its own credentials.
The current web runtime does not own crawler settings or a PostgreSQL database.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8000"))
