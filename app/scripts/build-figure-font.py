#!/usr/bin/env python3
"""Fetch or verify FA Foundry's pinned, offline IBM Plex Mono figure faces.

Uses already installed fontTools + Brotli; never installs dependencies.
--check reads only bundled files and makes no network requests.

The faces are IBM's own WOFF2 files from the publisher's npm package, copied byte
for byte. Nothing is converted, subset or renamed: under the OFL a format change
is already a Modified Version, which may not carry the Reserved Font Name "Plex".
CSS unicode-range decides which characters the app draws with them.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
from urllib.request import urlopen

from fontTools.ttLib import TTFont

PACKAGE = "@ibm/plex-mono"
VERSION = "2.5.0"
TARBALL = f"https://registry.npmjs.org/{PACKAGE}/-/plex-mono-{VERSION}.tgz"
TARBALL_SHA256 = "55b5ffcfcd5e9db36ef2070b2b07a573434ca02c6f3be2b921c0b88fff29acad"
FACES = {
    400: ("IBMPlexMono-Regular.woff2", "ba204497f16b6d334cee9d1e963a831b73e3a56e1d6300a8489d18df7214b350"),
    600: ("IBMPlexMono-SemiBold.woff2", "6a825b4824c01cbb401e829e5a066a1818411bcb3538b5a5792c5ca9b82343c3"),
    700: ("IBMPlexMono-Bold.woff2", "ea576f38d05cc44cca48c45314984beb8cc1d2b886f58e1dce99f15dc344eb1d"),
}
LICENSE = ("LICENSE.txt", "OFL.txt", "7e6b2818edbd8f6a01ae80641cc8f16a51080d08fb4e532be3a0b6f74adb07da")
# Every character a figure is written with: digits, grouping, sign, accounting parentheses, percent and the space
# that holds a positive figure's closing-parenthesis column.
FIGURE_CHARACTERS = "0123456789,.-+()%\u2212 "
DEST = Path(__file__).resolve().parents[1] / "src/assets/fonts/ibm-plex-mono"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_font(path: Path) -> dict:
    with TTFont(path, recalcTimestamp=False) as font:
        cmap = font.getBestCmap()
        missing = [f"U+{ord(ch):04X}" for ch in FIGURE_CHARACTERS if ord(ch) not in cmap]
        if missing:
            raise ValueError(f"figure characters missing: {missing}")
        advances = {ch: font["hmtx"][cmap[ord(ch)]][0] for ch in FIGURE_CHARACTERS}
        if len(set(advances.values())) != 1:
            raise ValueError(f"figure characters are not one width: {advances}")
        return {
            "family": font["name"].getDebugName(1),
            "version": font["name"].getDebugName(5),
            "weight_class": font["OS/2"].usWeightClass,
            "fs_type": font["OS/2"].fsType,
            "units_per_em": font["head"].unitsPerEm,
            "figure_advance": next(iter(advances.values())),
            "codepoints": len(cmap),
        }


def check() -> None:
    manifest = json.loads((DEST / "manifest.json").read_text())
    if digest((DEST / LICENSE[1]).read_bytes()) != LICENSE[2]:
        raise ValueError("bundled license hash mismatch")
    for row in manifest["faces"]:
        path = DEST / row["file"]
        if digest(path.read_bytes()) != row["sha256"] or row["sha256"] != FACES[row["weight"]][1]:
            raise ValueError(f"bundled face is not the publisher's file: {row['file']}")
        if inspect_font(path) != row["measured"]:
            raise ValueError(f"face metadata or figure widths differ from manifest: {row['file']}")
    print(json.dumps({"verified": [row["file"] for row in manifest["faces"]]}))


def build() -> None:
    data = urlopen(TARBALL, timeout=60).read()
    if digest(data) != TARBALL_SHA256:
        raise ValueError("npm tarball hash mismatch")
    DEST.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        def member(path: str) -> bytes:
            return archive.extractfile(f"package/{path}").read()
        faces = []
        for weight, (filename, expected) in FACES.items():
            face = member(f"fonts/complete/woff2/{filename}")
            if digest(face) != expected:
                raise ValueError(f"publisher face hash mismatch: {filename}")
            (DEST / filename).write_bytes(face)
            measured = inspect_font(DEST / filename)
            if measured["weight_class"] != weight:
                raise ValueError(f"unexpected weight class: {filename}")
            faces.append({"weight": weight, "file": filename, "sha256": expected, "bytes": len(face),
                          "source": f"package/fonts/complete/woff2/{filename}", "measured": measured})
        license_text = member(LICENSE[0])
        if digest(license_text) != LICENSE[2]:
            raise ValueError("publisher license hash mismatch")
        (DEST / LICENSE[1]).write_bytes(license_text)
    manifest = {
        "source": {"package": PACKAGE, "version": VERSION, "tarball": TARBALL, "sha256": TARBALL_SHA256,
                   "repository": "https://github.com/IBM/plex"},
        "license": {"name": "SIL Open Font License 1.1", "reserved_font_name": "Plex", "file": LICENSE[1], "sha256": LICENSE[2]},
        "build": {"copied_unmodified": True, "subset": False, "converted": False},
        "figure_characters": FIGURE_CHARACTERS,
        "faces": faces,
    }
    (DEST / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    check()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check()
    else:
        build()


if __name__ == "__main__":
    main()
