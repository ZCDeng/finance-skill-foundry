"""app/scripts/notarize-app.sh leaves nothing behind: the ~544 MB upload zip and its work directory are removed
after notarization, whether Apple accepts the app or not. The Apple tools are stubbed; nothing is uploaded."""
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'app' / 'scripts' / 'notarize-app.sh'


def _stub(bin_dir, name, body):
    path = bin_dir / name
    path.write_text('#!/bin/sh\n' + body, encoding='utf-8')
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(tmp_path, status):
    bin_dir, work_root, app = tmp_path / 'bin', tmp_path / 'tmp', tmp_path / 'FA Foundry.app'
    bin_dir.mkdir()
    work_root.mkdir()
    app.mkdir()
    _stub(bin_dir, 'codesign', 'exit 0\n')
    _stub(bin_dir, 'spctl', 'exit 0\n')
    # ditto -c -k --keepParent APP ZIP: write the zip where the script asks, and say where.
    _stub(bin_dir, 'ditto', f'for last; do :; done\nprintf zip > "$last"\nprintf %s "$last" > "{tmp_path}/zip-path"\n')
    _stub(bin_dir, 'xcrun', f'''case "$1 $2" in
  "notarytool submit") printf '{{"status":"{status}","id":"abc","message":"done"}}\\n' ;;
  "notarytool log") echo "log" ;;
esac
exit 0
''')
    env = {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'TMPDIR': str(work_root),
           'NOTARY_PROFILE': 'stub'}
    result = subprocess.run(['sh', str(SCRIPT), str(app)], env=env, capture_output=True, text=True)
    return result, work_root


@pytest.mark.parametrize('status, code', [('Accepted', 0), ('Invalid', 1)])
def test_the_upload_zip_and_work_directory_are_removed_after_notarization(tmp_path, status, code):
    result, work_root = _run(tmp_path, status)

    assert result.returncode == code, result.stderr
    assert f'"status":"{status}"' in result.stdout
    # The upload zip was made under TMPDIR, and nothing of it is left there.
    assert Path((tmp_path / 'zip-path').read_text()).parent.parent == work_root
    assert list(work_root.iterdir()) == []
