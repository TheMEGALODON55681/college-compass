"""Runnable checks for scripts/fetch_db.py, the build-time download of the
release database. Served from a throwaway local HTTP server, never the real
release.

The four outcomes that matter at deploy time: a good download lands as a
verified file, a checksum mismatch fails loud and leaves no database behind
(so a bad deploy cannot boot on a half-written or wrong file), a failed
download fails loud, and a database that is already in place is left alone
unless it differs from the pinned one - then the script refuses rather than
overwrite someone's locally rebuilt copy.
"""

import gzip
import hashlib
import sys
import threading
import urllib.error
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.fetch_db import fetch_db

PAYLOAD = b"SQLite format 3\x00" + bytes(range(256)) * 400


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def served(tmp_path):
    """A folder holding college_compass.db.gz, served over HTTP on a free port."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "college_compass.db.gz").write_bytes(gzip.compress(PAYLOAD))
    (site / "not-gzip.gz").write_bytes(b"<html>an error page served with status 200</html>")
    server = HTTPServer(("127.0.0.1", 0), partial(_Quiet, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/college_compass.db.gz"
    server.shutdown()


GOOD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def test_download_decompresses_and_verifies(served, tmp_path):
    target = tmp_path / "college_compass.db"
    fetch_db(served, GOOD_SHA, target)
    assert target.read_bytes() == PAYLOAD
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["college_compass.db"]


def test_checksum_mismatch_fails_loud_and_leaves_nothing(served, tmp_path):
    target = tmp_path / "college_compass.db"
    with pytest.raises(RuntimeError, match="checksum"):
        fetch_db(served, "0" * 64, target)
    assert not target.exists()
    assert [p.name for p in tmp_path.iterdir() if p.is_file()] == []


def test_failed_download_fails_loud(served, tmp_path):
    target = tmp_path / "college_compass.db"
    with pytest.raises(urllib.error.HTTPError):
        fetch_db(served.replace("college_compass.db.gz", "missing.gz"), GOOD_SHA, target)
    assert not target.exists()


def test_non_gzip_response_fails_loud_and_leaves_nothing(served, tmp_path):
    target = tmp_path / "college_compass.db"
    with pytest.raises(gzip.BadGzipFile):
        fetch_db(served.replace("college_compass.db.gz", "not-gzip.gz"), GOOD_SHA, target)
    assert [p.name for p in tmp_path.iterdir() if p.is_file()] == []


def test_matching_database_is_left_alone_without_a_download(tmp_path):
    target = tmp_path / "college_compass.db"
    target.write_bytes(PAYLOAD)
    fetch_db("http://127.0.0.1:1/never-contacted.gz", GOOD_SHA, target)
    assert target.read_bytes() == PAYLOAD


def test_different_existing_database_is_not_overwritten(served, tmp_path):
    target = tmp_path / "college_compass.db"
    target.write_bytes(b"a locally rebuilt database")
    with pytest.raises(RuntimeError, match="different"):
        fetch_db(served, GOOD_SHA, target)
    assert target.read_bytes() == b"a locally rebuilt database"
