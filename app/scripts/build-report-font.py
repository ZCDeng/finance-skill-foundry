#!/usr/bin/env python3
"""Derive an embeddable static TTF from the approved offline Noto face."""
import hashlib
import json
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

root = Path(__file__).resolve().parents[1] / 'src/assets/fonts/noto-sans-sc'
source = root / 'NotoSansSC-variable.woff2'
expected = '97a715fad95d3cacf4838b1ffedb123d2f1bf0f6bbd726c73e147dcaf317869f'
assert hashlib.sha256(source.read_bytes()).hexdigest() == expected
font = TTFont(source, recalcTimestamp=False)
font = instantiateVariableFont(font, {'wght': 400}, inplace=True)
font.flavor = None
# OFL permits editable embedding. Retain all glyphs and original naming/license.
assert font['OS/2'].fsType == 0
output = root / 'NotoSansSC-report.ttf'
font.save(output)
data = output.read_bytes()
manifest = {'source_sha256': expected, 'weight': 400, 'subset': False,
            'file': output.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
(root / 'report-font.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest))
