#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Host tests for the build tool's asset cache handling."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tools.build as build  # noqa: E402  (import needs ROOT on sys.path)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.remote = self.dir / "remote.bin"
        self.local = self.dir / "build" / "asset.bin"
        self.local.parent.mkdir()

    def serve(self, data):
        self.remote.write_bytes(data)
        return self.remote.as_uri()

    def test_missing_file_is_fetched_and_verified(self):
        url = self.serve(b"fresh")
        build.download(url, self.local, sha256(b"fresh"))
        self.assertEqual(self.local.read_bytes(), b"fresh")

    def test_verified_file_is_not_refetched(self):
        self.local.write_bytes(b"good")
        # The URL serves nothing: passing proves the verified cache was used as-is.
        build.download("file:///dev/null", self.local, sha256(b"good"))

    def test_stale_file_from_an_earlier_pin_is_replaced(self):
        self.local.write_bytes(b"stale")  # left behind by a previous pin
        url = self.serve(b"fresh")
        build.download(url, self.local, sha256(b"fresh"))
        self.assertEqual(self.local.read_bytes(), b"fresh")

    def test_mismatching_download_still_fails(self):
        url = self.serve(b"wrong")
        with self.assertRaises(RuntimeError):
            build.download(url, self.local, sha256(b"expected"))
        self.assertFalse(self.local.exists())


if __name__ == "__main__":
    unittest.main()
