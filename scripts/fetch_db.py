"""Download the built database at deploy time.

college_compass.db is about 100 MB and not in git. The built file is published
as a gzip release asset; Render's build command runs this script after the
dependency install:

    pip install -r requirements.txt && python scripts/fetch_db.py

DB_SHA256 pins the decompressed database, not the .gz, so any gzip level or
tool produces a valid asset. A bad download, a wrong file or a failed request
raises, which fails the build instead of shipping a service that cannot boot.
See README "Build the database" for how to publish a new asset.
"""

import gzip
import hashlib
import shutil
import urllib.request
from pathlib import Path

DB_URL = "https://github.com/TheMEGALODON55681/college-compass/releases/download/db-v1/college_compass.db.gz"
DB_SHA256 = "ec51de5e11010c5ee7ad465a7ee3e2b3943be4150c460736776dd48944c0b16e"
TARGET = Path(__file__).resolve().parent.parent / "college_compass.db"
CHUNK = 1 << 20


def _sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_db(url=DB_URL, sha256=DB_SHA256, target=TARGET):
    target = Path(target)
    if target.exists():
        if _sha256_of(target) == sha256:
            print(f"[fetch_db] {target.name} already present and verified")
            return
        raise RuntimeError(
            f"{target} exists but is different from the pinned database. "
            "Delete it to download the pinned copy, or update DB_SHA256 if the new one is intended."
        )

    unpacked = target.with_name(target.name + ".part")
    try:
        print(f"[fetch_db] downloading {url}")
        with urllib.request.urlopen(url, timeout=60) as response, gzip.GzipFile(fileobj=response) as src, open(unpacked, "wb") as out:
            shutil.copyfileobj(src, out, CHUNK)
        got = _sha256_of(unpacked)
        if got != sha256:
            raise RuntimeError(f"checksum mismatch for {url}: expected {sha256}, got {got}")
        unpacked.replace(target)
        print(f"[fetch_db] wrote {target} ({target.stat().st_size / 1048576:.1f} MB), checksum verified")
    finally:
        unpacked.unlink(missing_ok=True)


if __name__ == "__main__":
    fetch_db()
