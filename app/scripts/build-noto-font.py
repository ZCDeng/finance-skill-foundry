#!/usr/bin/env python3
"""Rebuild or verify FA Foundry's pinned, offline Noto Sans SC WOFF2.

Uses already installed fontTools + Brotli; never installs dependencies.
--check reads only bundled files and makes no network requests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.parse import quote
from urllib.request import urlopen

from fontTools import __version__ as fonttools_version
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.woff2 import WOFF2FlavorData

COMMIT = "5e35378e6bda803962ee6fd257e444a7d459660d"
BASE = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl/notosanssc/"
SOURCES = {
    "NotoSansSC[wght].ttf": "a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da",
    "OFL.txt": "1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9",
    "METADATA.pb": "c6c4bdb785793b2de1da177caeeffcd0c90d7680bdab2de8f88ab45007bc59bc",
}
DEST = Path(__file__).resolve().parents[1] / "src/assets/fonts/noto-sans-sc"
OUTPUT = "NotoSansSC-variable.woff2"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_font(path: Path) -> dict:
    with TTFont(path, recalcTimestamp=False) as font:
        cmap = font.getBestCmap()
        weights = {}
        for weight in (400, 500, 600, 700):
            glyphs = font.getGlyphSet(location={"wght": weight})
            pen = RecordingPen()
            glyphs[cmap[ord("财")]].draw(pen)
            advances = [glyphs[cmap[ord(digit)]].width for digit in "0123456789"]
            if len(set(advances)) != 1:
                raise ValueError(f"digits are not equal-width at {weight}")
            weights[str(weight)] = {
                "digit_advances": advances,
                "outline_sha256": digest(repr(pen.value).encode()),
            }
        if len({row["outline_sha256"] for row in weights.values()}) != 4:
            raise ValueError("UI weights do not produce distinct Chinese glyph outlines")
        return {
            "family": font["name"].getDebugName(16),
            "axes": [
                {"tag": axis.axisTag, "min": axis.minValue, "default": axis.defaultValue, "max": axis.maxValue}
                for axis in font["fvar"].axes
            ],
            "coverage": {"codepoints": len(cmap), "glyphs": font["maxp"].numGlyphs},
            "numerals": {
                "mode": "equal-default-advances",
                "has_tnum_feature": any(row.FeatureTag == "tnum" for row in font["GSUB"].table.FeatureList.FeatureRecord),
            },
            "weights": weights,
        }


def check() -> None:
    manifest = json.loads((DEST / "manifest.json").read_text())
    for filename, expected in [(OUTPUT, manifest["output"]["sha256"]), ("OFL.txt", SOURCES["OFL.txt"]), ("METADATA.pb", SOURCES["METADATA.pb"])]:
        if digest((DEST / filename).read_bytes()) != expected:
            raise ValueError(f"bundled file hash mismatch: {filename}")
    measured = inspect_font(DEST / OUTPUT)
    if any(manifest[key] != value for key, value in measured.items()):
        raise ValueError("font metadata, outlines or digit advances differ from manifest")
    print(json.dumps({"verified": str(DEST / OUTPUT), "bytes": (DEST / OUTPUT).stat().st_size, **measured}, ensure_ascii=False))


def build(source_dir: Path) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    for filename, expected in SOURCES.items():
        path = source_dir / filename
        if not path.exists():
            path.write_bytes(urlopen(BASE + quote(filename), timeout=60).read())
        if digest(path.read_bytes()) != expected:
            raise ValueError(f"official source hash mismatch: {filename}")
    source = source_dir / "NotoSansSC[wght].ttf"
    DEST.mkdir(parents=True, exist_ok=True)
    with TTFont(source, recalcTimestamp=False) as font:
        font.flavor = "woff2"
        # No glyph subsetting, weight instancing or outline changes. Retaining
        # raw tables permits binary coverage tests with Node's Brotli decoder.
        font.flavorData = WOFF2FlavorData(transformedTables=set())
        font.save(DEST / OUTPUT)
    for name in ("OFL.txt", "METADATA.pb"):
        (DEST / name).write_bytes((source_dir / name).read_bytes())
    measured = inspect_font(DEST / OUTPUT)
    if measured != inspect_font(source):
        raise ValueError("WOFF2 conversion changed measured font content")
    data = (DEST / OUTPUT).read_bytes()
    manifest = {
        "source": {
            "repository": "https://github.com/google/fonts",
            "commit": COMMIT,
            "path": "ofl/notosanssc/NotoSansSC[wght].ttf",
            "url": BASE + quote(source.name),
            "sha256": SOURCES[source.name],
            "bytes": source.stat().st_size,
        },
        "license": {"name": "SIL Open Font License 1.1", "url": BASE + "OFL.txt", "sha256": SOURCES["OFL.txt"]},
        "output": {"file": OUTPUT, "sha256": digest(data), "bytes": len(data)},
        "build": {"fonttools": fonttools_version, "subset": False, "woff2_transformed_tables": [], "recalc_timestamp": False},
        **measured,
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
        with tempfile.TemporaryDirectory(prefix="foundry-noto-build-") as directory:
            build(Path(directory))


if __name__ == "__main__":
    main()
