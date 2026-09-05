"""Check the real exported workbook against the UI workflow's saved records."""
import json
import sys
from pathlib import Path

from openpyxl import load_workbook


def verify(evidence_path: Path) -> dict:
    evidence = json.loads(evidence_path.read_text())
    draft = evidence['exportedDraft']
    workbook = load_workbook(evidence['exported'], data_only=False)
    report = workbook['Report']
    assert report.cell(1, 1).value == draft['title']
    assert report.cell(2, 1).value == draft['body']
    assert report.cell(3, 2).value == draft['id']
    for index, run in enumerate(evidence['exportedRuns'], 1):
        assert run['id'] == draft['run_ids'][index - 1]
        result = run['result']
        columns = [column['name'] for column in result['columns']]
        actual = list(workbook[f'Result {index}'].values)
        expected = [tuple(columns)] + [tuple(row.get(key) for key in columns) for row in result['rows']]
        assert actual == expected, f'Result {index} differs from its saved run'
        stored = dict(workbook[f'Evidence {index}'].values)
        assert stored['id'] == run['id']
    return {'status': 'passed', 'workbook': evidence['exported'], 'draftId': draft['id'],
            'runIds': draft['run_ids'], 'checks': ['exact saved title and body', 'exact saved version',
                                               'every result cell and evidence run ID']}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1])), ensure_ascii=False, indent=2))
