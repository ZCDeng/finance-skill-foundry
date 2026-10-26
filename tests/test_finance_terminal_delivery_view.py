"""The actual registered client component exposes durable final tool text."""
import json
from pathlib import Path
import subprocess


def test_verified_terminal_text_is_visible_outside_closed_tool_details():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ['node', str(root / 'tests/finance_terminal_delivery_view.mjs')],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report == {'passed': True, 'checks': 17, 'provider_calls': 0}
    assert (root / 'dsh-plugin/client.js').read_bytes() == (
        root / 'foundry/resources/dsh-plugin/client.js').read_bytes()
