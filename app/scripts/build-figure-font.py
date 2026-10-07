#!/usr/bin/env python3
"""Rebuild or verify FA Foundry's pinned, offline IBM Plex Mono figure faces.

Uses already installed fontTools + Brotli; never installs dependencies.
--check reads only bundled files and makes no network requests.

The faces are format conversions only: no glyph subsetting, renaming or outline
changes, so the Reserved Font Name "Plex" stays with the unmodified font. CSS
unicode-range decides which characters the app draws with them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.request import urlopen

from fontTools import __version__ as fonttools_version
from fontTools.ttLib import TTFont
from fontTools.ttLib.woff2 import WOFF2FlavorData

COMMIT = "5e8a3ba899557829a76cfdac30fa512bda91d7ca"
BASE = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl/ibmplexmono/"
FACES = {
    400: ("IBMPlexMono-Regular.ttf", "6a3412f058c7d8dfd9170c41e85ade48e5156ecb89356110ca57a0a27734af46"),
    600: ("IBMPlexMono-SemiBold.ttf", "d3c38e55c78f5b0f28009fddba4834ec503278936a5986032424c9bd2d23aa46"),
    700: ("IBMPlexMono-Bold.ttf", "ac27abd6450a64dd94467580a02fe6235156d5b92f2926ebbc8e7489df64e0be"),
}
EXTRA = {
    "OFL.txt": "7e6b2818edbd8f6a01ae80641cc8f16a51080d08fb4e532be3a0b6f74adb07da",
    "METADATA.pb": "006b605a8a45174a3f8ad9456006233ff8f13cf3cae7fe7602904334dc323c7c",
}
# Every character a figure is written with: digits, grouping, sign, accounting parentheses, percent and the space
# that holds a positive figure's closing-parenthesis column.
FIGURE_CHARACTERS = "0123456789,.-+()%\u2212 "
DEST = Path(__file__).resolve().parents[1] / "src/assets/fonts/ibm-plex-mono"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def woff2_name(ttf: str) -> str:
    return ttf.removesuffix(".ttf") + ".woff2"


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
    for filename, expected in EXTRA.items():
        if digest((DEST / filename).read_bytes()) != expected:
            raise ValueError(f"bundled file hash mismatch: {filename}")
    for row in manifest["faces"]:
        path = DEST / row["file"]
        if digest(path.read_bytes()) != row["sha256"]:
            raise ValueError(f"bundled face hash mismatch: {row['file']}")
        if inspect_font(path) != row["measured"]:
            raise ValueError(f"face metadata or figure widths differ from manifest: {row['file']}")
    print(json.dumps({"verified": [row["file"] for row in manifest["faces"]]}))


def build(source_dir: Path) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    sources = {name: expected for name, expected in FACES.values()} | EXTRA
    for filename, expected in sources.items():
        path = source_dir / filename
        if not path.exists():
            path.write_bytes(urlopen(BASE + filename, timeout=60).read())
        if digest(path.read_bytes()) != expected:
            raise ValueError(f"official source hash mismatch: {filename}")
    DEST.mkdir(parents=True, exist_ok=True)
    faces = []
    for weight, (filename, expected) in FACES.items():
        source = source_dir / filename
        output = DEST / woff2_name(filename)
        with TTFont(source, recalcTimestamp=False) as font:
            font.flavor = "woff2"
            # Raw tables keep the face readable by the Node font tests' Brotli decoder.
            font.flavorData = WOFF2FlavorData(transformedTables=set())
            font.save(output)
        measured = inspect_font(output)
        if measured != inspect_font(source) or measured["weight_class"] != weight:
            raise ValueError(f"WOFF2 conversion changed measured font content: {filename}")
        data = output.read_bytes()
        faces.append({
            "weight": weight, "file": output.name, "sha256": digest(data), "bytes": len(data),
            "source": {"path": f"ofl/ibmplexmono/{filename}", "url": BASE + filename, "sha256": expected, "bytes": source.stat().st_size},
            "measured": measured,
        })
    for name in EXTRA:
        (DEST / name).write_bytes((source_dir / name).read_bytes())
    manifest = {
        "source": {"repository": "https://github.com/google/fonts", "commit": COMMIT, "directory": "ofl/ibmplexmono"},
        "license": {"name": "SIL Open Font License 1.1", "reserved_font_name": "Plex", "url": BASE + "OFL.txt", "sha256": EXTRA["OFL.txt"]},
        "build": {"fonttools": fonttools_version, "subset": False, "woff2_transformed_tables": [], "recalc_timestamp": False},
        "figure_characters": FIGURE_CHARACTERS,
        "faces": faces,
    }
    (DEST / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    check()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--source-dir", type=Path)
    args = parser.parse_args()
    if args.check:
        check()
    elif args.source_dir:
        build(args.source_dir)
    else:
        with tempfile.TemporaryDirectory(prefix="foundry-plex-build-") as directory:
            build(Path(directory))


if __name__ == "__main__":
    main()
