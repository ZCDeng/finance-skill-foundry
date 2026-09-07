"""Check the real exported workbook against the UI workflow's saved records."""
import json
import sys
from decimal import Decimal
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
        sheet = workbook[f'Result {index}']
        assert tuple(cell.value for cell in sheet[1]) == tuple(columns)
        assert sheet.max_row == len(result['rows']) + 1
        for row_number, row in enumerate(result['rows'], 2):
            for column_number, column in enumerate(result['columns'], 1):
                expected = row.get(column['name'])
                cell = sheet.cell(row_number, column_number)
                numeric = str(column.get('type', '')).upper().startswith(
                    ('DECIMAL', 'NUMERIC', 'INTEGER', 'BIGINT', 'SMALLINT', 'HUGEINT', 'DOUBLE', 'FLOAT'))
                location = f'{sheet.title}!{cell.coordinate}'
                if expected is None:
                    assert cell.value is None, location
                elif numeric and cell.data_type == 'n':
                    assert Decimal(str(cell.value)) == Decimal(str(expected)), location
                else:
                    assert cell.value == str(expected), location
                    if numeric:
                        assert cell.comment and '精度' in cell.comment.text, location
        stored = dict(workbook[f'Evidence {index}'].values)
        assert stored['id'] == run['id']
    return {'status': 'passed', 'workbook': evidence['exported'], 'draftId': draft['id'],
            'runIds': draft['run_ids'], 'checks': ['exact saved title and body', 'exact saved version',
                                               'every result cell and evidence run ID']}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1])), ensure_ascii=False, indent=2))
