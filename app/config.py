import os
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/certificates.db")
STORAGE_DIR = Path(os.getenv("CERT_STORAGE_DIR", "./data/certificates"))
MAX_RECIPIENTS_PER_JOB = int(os.getenv("MAX_RECIPIENTS_PER_JOB", "1000"))
