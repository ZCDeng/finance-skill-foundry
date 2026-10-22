"""The assistant can actually declare the same contract the execution layer enforces."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_period_contract_and_authorized_repair_tools_are_published():
    node = shutil.which('node')
    if not node:
        pytest.skip('node unavailable')
    script = "import {definitions} from './dsh-plugin/analysis.js'; console.log(JSON.stringify(definitions()))"
    result = subprocess.run([node, '--input-type=module', '-e', script], cwd=ROOT, capture_output=True, text=True, check=True)
    definitions = {item['name']: item for item in json.loads(result.stdout)}
    for name in ['analysis-save', 'analysis-script', 'analysis-script-start']:
        properties = definitions[name]['parameters']['properties']['spec']['properties']
        assert properties['period_binding']['properties']['mode']['enum'] == ['current']
    assert 'dashboard_repair_read' in definitions
    assert 'dashboard_repair_propose' in definitions
    assert definitions['dashboard_repair_propose']['parameters']['properties']['spec']['required'] == ['run_id', 'spec']
