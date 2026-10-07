import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="certgen-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["CERT_STORAGE_DIR"] = str(_tmp / "certs")
os.environ["MAX_RECIPIENTS_PER_JOB"] = "50"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    # TestClient runs background tasks before returning, so jobs are finished when the POST returns.
    with TestClient(app) as c:
        yield c


def recipient(i: int = 1, **overrides):
    data = {"name": f"Person {i}", "email": f"person{i}@example.com", "course": "Python 101"}
    data.update(overrides)
    return data
