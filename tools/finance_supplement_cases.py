"""Frozen supplemental cases and public-only trusted synthetic preconditions.

Loading private oracles is a controller operation. The seeding API accepts only
the explicit public projection and never creates answer artifacts.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ROOT / 'tests/fixtures/finance_supplements/three_statement_v1'
FROZEN_MANIFEST_SHA256 = 'd96b541d07c1e9af4c6e1a1538de65c51290325363ae1d6c9879f430d5cf6905'
ORIGINAL_DRIVER_SHA256 = '7868708a037dce6fabd89a0b41915ded1dc31913e55bf216960e48f1e4a8c7bf'
EMPTY_COLLECTIONS = ('runs', 'requirements', 'drafts', 'completions')
PROFILE_FIELDS = ('purpose', 'effective_period.start', 'effective_period.end', 'functional_currency',
                  'presentation_currency', 'presentation_unit', 'entity_scope')
PUBLIC_FIELDS = {'id', 'question', 'datasets', 'attachments', 'runnable'}
REQUEST_FIELDS = {'schema_version', 'suite_id', 'case_id', 'context', 'synthetic_scenario_declarations',
                  'task', 'required_metrics', 'required_model_checks', 'public_files', 'reporting_profile'}
DATASET_NAMES = ('template_inputs', 'model_boundary', 'transaction_allocation')


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def tree_hashes(path):
    root = Path(path)
    return {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(root.rglob('*')) if p.is_file()}


def history_hashes(path):
    root = Path(path)
    return {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(root.rglob('*'))
            if p.is_file() and p.name not in {'.lock', 'completion.lock'}
            and p.relative_to(root).as_posix() != 'analysis/sequence.json'}


def unchanged_history(before, after):
    return [name for name, expected in before.items() if after.get(name) != expected]


def original_driver():
    path = ROOT / 'tools/verify_finance_mutation_pipeline.py'
    if file_hash(path) != ORIGINAL_DRIVER_SHA256:
        raise ValueError('original mutation driver hash changed')
    spec = importlib.util.spec_from_file_location('_supplement_original_cli', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def new_cli(foundry, directory, *, var=None, task=None):
    module = original_driver()
    class RecordingCLI(module.CLI):
        def call(self, command, *parts, **kwargs):
            if any((self.directory / 'calls').glob(f'{self.sequence + 1:03d}-*.json')):
                raise FileExistsError('refusing to overwrite raw CLI call')
            return super().call(command, *parts, **kwargs)
    cli = RecordingCLI(foundry, Path(directory))
    if var is not None:
        cli.var = Path(var)
    cli.task = task
    return cli


def request_from_public(publiccase):
    if set(publiccase) != PUBLIC_FIELDS:
        raise ValueError('seed accepts only the explicit public case projection')
    attachments = publiccase.get('attachments') or []
    if len(attachments) != 1 or attachments[0].get('name') != 'scenario_request' or attachments[0].get('format') != 'md':
        raise ValueError('one explicit public scenario request attachment is required')
    request = json.loads(attachments[0]['text'])
    if set(request) != REQUEST_FIELDS or request.get('case_id') != publiccase.get('id'):
        raise ValueError('public request identity or allowlisted fields invalid')
    if request['reporting_profile'].get('purpose') != 'forecast' or not request['synthetic_scenario_declarations']:
        raise ValueError('explicit synthetic forecast profile and declarations required')
    return request


def case_public(case):
    public = deepcopy(case['public'])
    request_from_public(public)
    return public


def public_selection(case):
    """Controller-only selection; only its public member may enter a runtime."""
    return {'public': case_public(case), 'oracle': deepcopy(case['oracle']),
            'fixture_sha256': case['fixture_sha256'], 'oracle_sha256': case['oracle_sha256']}


def precondition_specs(publiccase, dataset_ids):
    request = request_from_public(publiccase)
    source = {d['name']: d for d in publiccase['datasets']}
    if set(source) != set(DATASET_NAMES) or not set(source) <= set(dataset_ids):
        raise ValueError('three explicit public source datasets are required')
    context = request['context']
    scope = {key: context[key] for key in ('organization', 'ledger', 'scenario', 'currency', 'unit')}
    bindings = {}
    for alias, selector_key in (('template_inputs', 'input_name'), ('model_boundary', 'boundary_name')):
        for row in source[alias]['rows']:
            name = row[selector_key] if alias == 'template_inputs' else 'boundary.' + row[selector_key]
            if name in bindings:
                raise ValueError('duplicate public source input name')
            bindings[name] = {'alias': alias, 'column': 'amount', 'selector': {selector_key: row[selector_key]},
                'aggregation': 'single', 'period': row['period'],
                'scope': {key: row[key] for key in ('organization', 'ledger', 'scenario')},
                'currency': row['currency'], 'unit': row['unit']}
    if len(source['template_inputs']['rows']) != 16 or len(source['model_boundary']['rows']) != 8 or len(bindings) != 24:
        raise ValueError('exact 16 input and eight boundary source rows required')
    return {'context': {'bindings': {alias: dataset_ids[alias] for alias in DATASET_NAMES},
                        'scopes': {alias: scope for alias in DATASET_NAMES},
                        'reporting_profile': deepcopy(request['reporting_profile'])},
            'scenario_inputs': {'template_id': context['template_id'], 'period': context['period'],
                                'scope': scope, 'source_bindings': bindings},
            'profile_fields': list(PROFILE_FIELDS),
            'boundary_names': sorted(key for key in bindings if key.startswith('boundary.'))}


def load_suite(root):
    root = Path(root).resolve()
    manifest_path = root / 'manifest.json'
    manifest_hash = file_hash(manifest_path)
    if manifest_hash != FROZEN_MANIFEST_SHA256 or (root / 'freeze.sha256').read_text().strip() != manifest_hash + '  manifest.json':
        raise ValueError('frozen supplement manifest hash mismatch')
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('status') != 'frozen':
        raise ValueError('supplement suite is not frozen')
    for relative, expected in manifest['artifact_hashes'].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or file_hash(path) != expected:
            raise ValueError('frozen artifact hash mismatch: ' + relative)
    contract = json.loads((root / manifest['contract_path']).read_text())
    if contract['numeric_tolerance'] != '0' or contract['original_release']['credit'] != 0:
        raise ValueError('supplement exact/isolated acceptance contract changed')
    cases = []
    for entry in manifest['cases']:
        case_id = entry['case_id']
        prefix = 'public/' + case_id + '/'
        expected_public = {prefix + name for name in ('request.json', 'template_inputs.json', 'model_boundary.json', 'transaction_allocation.json')}
        if set(entry['public_files']) != expected_public or entry['oracle_path'] != 'private/oracles/' + case_id + '.json':
            raise ValueError('case public/private path isolation invalid')
        request = json.loads((root / prefix / 'request.json').read_text())
        datasets = [json.loads((root / prefix / (alias + '.json')).read_text()) for alias in DATASET_NAMES[:2]]
        allocation_text = (root / prefix / 'transaction_allocation.json').read_text()
        allocation = json.loads(allocation_text)
        datasets.append({'dataset_alias': 'transaction_allocation',
                         'metadata': {key: allocation['scope'][key] for key in ('organization', 'ledger', 'scenario', 'currency', 'unit')},
                         'rows': [{'record_type': 'transaction_allocation', 'public_record_json': allocation_text}]})
        public = {'id': case_id, 'question': request['task'] + '\n公开合成范围：\n' + '\n'.join(request['synthetic_scenario_declarations'])
                  + '\n先读取 financial-statements 技能及其 FOUNDRY.md、forecast-models.md、model-checks.md 配套资源。',
                  'datasets': [{'name': d['dataset_alias'], 'metadata': d['metadata'], 'rows': d['rows']} for d in datasets],
                  'attachments': [{'name': 'scenario_request', 'format': 'md',
                                   'text': (root / prefix / 'request.json').read_text(),
                                   'metadata': {key: request['context'][key] for key in ('organization', 'ledger', 'scenario', 'currency', 'unit')}}],
                  'runnable': True}
        request_from_public(public)
        derived = precondition_specs(public, dict.fromkeys(DATASET_NAMES, 'controller-only-placeholder'))
        if derived['scenario_inputs']['source_bindings'] != {**entry['source_bindings'], **entry['boundary_bindings']}:
            raise ValueError('frozen bindings differ from public row identities')
        if request['required_metrics'] != contract['required_metrics'] or request['required_model_checks'] != contract['required_model_checks']:
            raise ValueError('public output obligations differ from frozen contract')
        oracle = json.loads((root / entry['oracle_path']).read_text())
        if set(oracle['expected_values']) != set(contract['required_metrics']) or any(
                not Decimal(value).is_finite() for value in oracle['expected_values'].values()):
            raise ValueError('private oracle must contain exactly 13 finite values')
        cases.append({'case_id': case_id, 'family_id': entry['family_id'], 'public': public, 'oracle': oracle,
                      'fixture_sha256': digest({name: manifest['artifact_hashes'][name] for name in entry['public_files']}),
                      'oracle_sha256': manifest['artifact_hashes'][entry['oracle_path']], 'manifest_entry': entry})
    if [case['case_id'] for case in cases] != contract['case_ids'] or len(cases) != 3:
        raise ValueError('frozen case identity set mismatch')
    return {'root': str(root), 'manifest': manifest, 'contract': contract, 'cases': cases, 'manifest_sha256': manifest_hash}


def empty_counts(state):
    if any(name not in state or not isinstance(state[name], list) for name in EMPTY_COLLECTIONS):
        raise ValueError('missing initial answer-artifact collections')
    counts = {name: len(state[name]) for name in EMPTY_COLLECTIONS}
    if any(counts.values()):
        raise ValueError('preexisting answer artifacts cannot enter a supplemental seed')
    return counts


def apply_preconditions(cli, publiccase, dataset_ids, *, mutation=None):
    """Actual CLI setup; mutation controls are used only by the negative engineering driver."""
    specs = precondition_specs(publiccase, dataset_ids)
    action = (mutation or {}).get('action')
    if action == 'replace_numeric_source_bindings_with_direct_values':
        inputs = next(d['rows'] for d in publiccase['datasets'] if d['name'] == 'template_inputs')
        specs['scenario_inputs']['values'] = {r['input_name']: r['amount'] for r in inputs}
        specs['scenario_inputs']['source_bindings'] = {k: v for k, v in specs['scenario_inputs']['source_bindings'].items() if k.startswith('boundary.')}
    context = cli.call('finance-context-save', spec=specs['context'])
    scenario = cli.call('finance-scenario-save', spec={'context_id': context['id'], 'kind': 'driver_model',
        'label': 'Independent synthetic single-entity management forecast', 'inputs': specs['scenario_inputs']})
    profile = None
    if action != 'omit_profile_confirmation':
        profile = cli.call('finance-profile-confirm', actor='manager', spec={'context_id': context['id'], 'confirmed_fields': specs['profile_fields']})
    names = specs['boundary_names']
    if action == 'omit_confirmed_boundary':
        names = [name for name in names if name != mutation['boundary']]
    boundary = cli.call('finance-profile-confirm', actor='manager', required=False,
        spec={'context_id': context['id'], 'scenario_id': scenario['id'], 'confirmed_model_boundaries': names})
    if mutation is None and boundary['returncode'] != 0:
        raise ValueError('trusted synthetic boundary setup failed: ' + boundary['stderr'])
    status = cli.call('finance-profile-status', spec={'context_id': context['id'], 'scenario_id': scenario['id']}, required=False)
    return {'context': context, 'scenario': scenario, 'profile_confirmation': profile,
            'boundary_confirmation': boundary, 'profile_status': status, 'specs': specs}


def prepare_preconditions(foundry, var, task, output, publiccase, dataset_ids):
    """Prepare only public synthetic context/profile/scenario; retain a zero-answer snapshot."""
    output, var = Path(output).resolve(), Path(var).resolve()
    output.mkdir(parents=True, exist_ok=False)
    request_from_public(publiccase)
    cli = new_cli(foundry, output, var=var, task=task)
    before = cli.state()
    initial = empty_counts(before)
    task_root = var / 'tasks' / task
    old = history_hashes(task_root)
    for dataset in publiccase['datasets']:
        actual = cli.call('dataset-read', '--dataset', dataset_ids[dataset['name']])
        if digest(actual.get('rows')) != digest(dataset['rows']):
            raise ValueError('registered public source does not match selected case')
    setup = apply_preconditions(cli, publiccase, dataset_ids)
    status = setup['profile_status']
    if status['returncode'] != 0 or status['value'].get('professional_status') != 'supported':
        raise ValueError('trusted synthetic profile/boundary status is not supported')
    after = cli.state()
    final_counts = empty_counts(after)
    if unchanged_history(old, history_hashes(task_root)):
        raise ValueError('precondition setup rewrote prior source/task bytes')
    write_new(output / 'public-input.json', publiccase)
    write_new(output / 'before-state.json', before)
    write_new(output / 'initial-state.json', after)
    shutil.copytree(task_root, output / 'initial-task-snapshot')
    snapshot = tree_hashes(output / 'initial-task-snapshot')
    proof = {'status': 'ready', 'context_id': setup['context']['id'], 'scenario_id': setup['scenario']['id'],
             'task_id': task, 'initial_empty_counts': final_counts, 'before_empty_counts': initial,
             'initial_snapshot_sha256': digest(snapshot), 'initial_snapshot_files': snapshot,
             'initial_snapshot_path': 'initial-task-snapshot', 'public_sha256': digest(publiccase),
             'setup': setup, 'provider_calls': 0,
             'authorization': 'Synthetic scoped engineering setup only; no real professional signoff',
             'created_answer_artifacts': False}
    write_new(output / 'runtime-precondition.json', proof)
    return {**proof, 'files': tree_hashes(output)}
