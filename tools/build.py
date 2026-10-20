#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build a pinned, hash-verified multi-KMI arm64 KernelSU module ZIP.

The pin lives in upstream.lock.json (tag, commit, per-asset SHA-256), refreshed
by tools/sync.py. Nothing here is downloaded without being checked against it.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "upstream.lock.json").read_text())
VERSION = re.search(r"^version=(.+)$", (ROOT / "module/module.prop").read_text(), re.M).group(1)
SLUG = LOCK["repository"].removeprefix("https://github.com/")
URL = f"{LOCK['repository']}/releases/download/{LOCK['tag']}/"


def fetch(url, path):
    headers = {"User-Agent": "susfs-lkm-module-builder"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
        path.write_bytes(response.read())


def download(url, path, digest):
    # A leftover file from an earlier pin is stale cache, not a corrupt download: refetch once.
    for _ in range(2):
        if not path.exists():
            fetch(url, path)
        if hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            return
        path.unlink()
    raise RuntimeError(f"SHA-256 mismatch: {path.name}")


def main():
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    sdk = Path(os.environ.get("ANDROID_HOME", str(Path.home() / "Android/Sdk")))
    ndk_env = os.environ.get("ANDROID_NDK_HOME")
    ndk = Path(ndk_env) if ndk_env else sorted((sdk / "ndk").iterdir(),
              key=lambda p: tuple(int(n) for n in p.name.split(".")))[-1]
    clang = ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android28-clang"
    probe = build / "susfs_probe"
    subprocess.run([str(clang), "-O2", "-Wall", "-Wextra", "-Werror", "-fPIE", "-pie",
                    str(ROOT / "tools/susfs_probe.c"), "-o", str(probe)], check=True)

    for name, digest in LOCK["assets"].items():
        download(URL + name, build / name, digest)
    source = build / "upstream-source.tar.gz"
    download(f"https://api.github.com/repos/{SLUG}/tarball/{LOCK['commit']}", source, LOCK["source_sha256"])

    provenance = {"repository": LOCK["repository"], "tag": LOCK["tag"], "commit": LOCK["commit"],
                  "assets_sha256": LOCK["assets"], "architecture": LOCK["architecture"],
                  "wrapper_version": VERSION, "supported_kmis": LOCK["supported_kmis"],
                  "source_sha256": LOCK["source_sha256"]}

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    output = dist / f"susfs-lkm-module-{VERSION}-arm64-multi-kmi.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / "module").rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT / "module"))
        archive.writestr("kmis", "".join(k + "\n" for k in LOCK["supported_kmis"]))
        archive.write(probe, "bin/susfs_probe")
        archive.write(build / "susfs_insmod", "bin/susfs_insmod")
        for name in LOCK["assets"]:
            if name.endswith(".ko"):
                archive.write(build / name, "lib/" + name)
        archive.write(source, "source/upstream-source.tar.gz")
        archive.write(ROOT / "tools/susfs_probe.c", "source/susfs_probe.c")
        archive.write(ROOT / "LICENSE", "LICENSE")
        archive.writestr("provenance.json", json.dumps(provenance, indent=2) + "\n")
    print(output)
    print("sha256:", hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
