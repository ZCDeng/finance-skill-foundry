#!/usr/bin/env node
// Synthetic, isolated packaged-app acceptance. No model request or human sign-off.
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const { _electron } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const executable = process.env.QA_APP;
if (!executable) throw new Error('QA_APP must identify the candidate executable');
const resources = path.resolve(path.dirname(executable), '../Resources');
const bin = path.join(resources, 'foundry/foundry');
const qa = fs.mkdtempSync('/tmp/finance-professional-app-');
const varRoot = path.join(qa, 'var');
const repo = path.resolve(__dirname, '..');
const sha = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const report = {status: 'running', qa, executable, appAsarSha256: sha(path.join(resources, 'app.asar')),
  foundrySha256: sha(bin), checks: [], screenshots: [], synthetic: true, providerCalls: 0,
  humanProfessionalReview: 'not_performed'};
const env = {...process.env, FOUNDRY_VAR: varRoot};
for (const key of ['FOUNDRY_BIN', 'FOUNDRY_DSH_INSTALL', 'FOUNDRY_FORMULATOR_BIN',
  'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'DEEPSEEK_API_KEY']) delete env[key];
let task, app, page;
function cli(command, args = [], raw = false) {
  const text = execFileSync(bin, ['--var', varRoot, ...(task ? ['--task', task] : []), command, ...args],
    {encoding: 'utf8', env}).trim();
  return raw ? text : JSON.parse(text);
}
const spec = (command, value) => cli(command, ['--spec', JSON.stringify(value)]);
function check(name, observed, valid) {
  report.checks.push({name, observed, status: valid ? 'passed' : 'failed'});
  if (!valid) throw new Error(name + ': ' + JSON.stringify(observed));
}
async function screenshot(name) {
  const file = path.join(qa, name + '.png');
  await page.screenshot({path: file, fullPage: true}); report.screenshots.push(file);
}
async function bridge(command, value) {
  const reply = await page.evaluate(async ({task, command, value}) =>
    window.foundry.financeCall(task, command, value), {task, command, value});
  if (!reply.ok) throw new Error(JSON.stringify(reply));
  return reply.value;
}
async function main() {
  const title = '验收：三表来源与口径 ' + new Date().toISOString();
  task = cli('task-new', ['--title', title, '--period', '2026-09'], true);
  report.task = task;
  const bindings = {}, sourceBindings = {};
  const fixture = path.join(repo, 'tests/fixtures/finance_evals/professional_runtime_v1/public/E18--base--closed-template');
  for (const [alias, key] of [['template_inputs', 'input_name'], ['model_boundary', 'boundary_name']]) {
    const input = path.join(fixture, alias + '.json');
    const rows = JSON.parse(fs.readFileSync(input, 'utf8')).rows;
    const file = path.join(qa, alias + '.json'); fs.writeFileSync(file, JSON.stringify(rows));
    bindings[alias] = cli('dataset-add', ['--path', file, '--name', alias]).id;
    for (const row of rows) {
      const name = alias === 'model_boundary' ? 'boundary.' + row[key] : row[key];
      sourceBindings[name] = {alias, column: 'amount', selector: {[key]: row[key]}, aggregation: 'single',
        period: row.period, scope: {organization: row.organization}, currency: row.currency, unit: row.unit};
    }
  }
  const profile = {schema_version: 1, basis: 'management', basis_version: 'management-v1', purpose: 'forecast',
    fiscal_year_start: '2026-01-01', early_adoption: false, effective_period: {start: '2026-09', end: '2026-09'},
    functional_currency: 'CNY', presentation_currency: 'CNY', presentation_unit: '元',
    entity_scope: 'Synthetic Fixture Co', policies: {}};
  const context = spec('finance-context-save', {bindings, reporting_profile: profile});
  const scenario = spec('finance-scenario-save', {context_id: context.id, kind: 'driver_model', label: 'E18 管理预测',
    inputs: {template_id: 'linked_three_statement_management_v1', period: '2026-09',
      scope: {organization: 'Synthetic Fixture Co', currency: 'CNY', unit: '元'}, source_bindings: sourceBindings}});
  const unconfirmed = spec('finance-scenario-run', {scenario_id: scenario.id});
  const before = spec('prepare-explanation', {run_ids: [unconfirmed.id]});
  const beforeCash = before.facts.find(f => f.column === 'value' && f.value === '90');
  check('unconfirmed_template_is_not_professional_amount_evidence', beforeCash?.evidence_eligibility,
    beforeCash?.evidence_eligibility?.counts_as_amount_evidence === false);
  app = await _electron.launch({executablePath: executable, args: ['--user-data-dir=' + path.join(qa, 'profile')], env, timeout: 60000});
  page = await app.firstWindow(); await page.waitForLoadState('domcontentloaded');
  await page.waitForFunction(() => window.foundry?.financeCall);
  const packed = await app.evaluate(({app}) => ({packaged: app.isPackaged, path: app.getAppPath()}));
  check('actual_packaged_app', packed, packed.packaged === true);
  await page.getByRole('button', {name: '工作区', exact: true}).click();
  const expand = page.getByRole('button', {name: '展开任务列表', exact: true});
  if (await expand.isVisible().catch(() => false)) await expand.click();
  await page.locator('.workspace-task').filter({hasText: title}).first().click();
  await page.getByRole('tab', {name: /财务分析/}).click();
  const setup = page.locator('details.analysis-finance-setup').first();
  if (!await setup.evaluate(el => el.open)) await setup.locator(':scope > summary').click();
  const details = setup.locator('details').filter({has: page.getByText('专业口径确认', {exact: true})}).first();
  if (!await details.evaluate(el => el.open)) await details.locator(':scope > summary').click();
  await screenshot('01-profile-before-confirmation');
  await page.getByRole('button', {name: '确认所列专业口径', exact: true}).click();
  await page.getByText(/已确认当前专业口径/).waitFor({timeout: 30000});
  const confirmed = spec('finance-profile-status', {context_id: context.id});
  check('renderer_click_trusted_ipc_confirmation', confirmed.professional_status, confirmed.professional_status === 'supported');
  const boundaryPending = spec('finance-profile-status', {context_id: context.id, scenario_id: scenario.id});
  check('profile_confirmation_does_not_approve_model_assumptions', boundaryPending.professional_status,
    boundaryPending.professional_status === 'awaiting_model_boundary_confirmation');
  await page.getByLabel('管理预测模型', {exact: true}).selectOption(scenario.id);
  await page.getByRole('button', {name: '预览八项模型边界', exact: true}).click();
  await page.getByRole('button', {name: '确认本模型八项边界均为零', exact: true}).waitFor({timeout: 30000});
  await page.getByRole('button', {name: '确认本模型八项边界均为零', exact: true}).scrollIntoViewIfNeeded();
  await screenshot('02-boundary-source-preview');
  await page.getByRole('button', {name: '确认本模型八项边界均为零', exact: true}).click();
  await page.getByText('已确认当前预测模型的八项零值边界。', {exact: true}).waitFor({timeout: 30000});
  const authorized = spec('finance-profile-status', {context_id: context.id, scenario_id: scenario.id});
  check('separate_model_boundary_confirmation', authorized.professional_status, authorized.professional_status === 'supported');
  await screenshot('02-profile-confirmed');
  const requirement = spec('analysis-requirements-save', {context_id: context.id, question: '期末现金及管理三表',
    items: [{id: 'cash', metric: 'closing_cash', dimensions: {template_id: 'linked_three_statement_management_v1', scenario_id: scenario.id}}]});
  const run = await bridge('finance-scenario-run', {scenario_id: scenario.id});
  const expected = {net_income: '50', cash_flow_operating: '50', cash_flow_investing: '-40', cash_flow_financing: '-20',
    closing_cash: '90', closing_receivables: '70', closing_ppe: '230', closing_payables: '60', closing_debt: '80',
    closing_equity: '250', total_assets: '390', total_liabilities_equity: '390', available_cash: '90'};
  for (const [metric, value] of Object.entries(expected)) {
    const row = run.result.rows.find(r => r.metric_key === metric);
    check('template_' + metric, row?.value, row?.value === value);
  }
  const prepared = await bridge('prepare-explanation', {run_ids: [run.id]});
  const facts = prepared.facts.filter(f => f.column === 'value' && run.result.rows[f.row]?.metric_key in expected);
  check('source_backed_template_facts', facts.map(f => f.evidence_eligibility), facts.length === 13 && facts.every(f => f.evidence_eligibility?.counts_as_amount_evidence));
  const claims = facts.map(f => ({basis: 'calculation', run_id: run.id, row: f.row, column: f.column, value: f.value, fact_id: f.id}));
  const draft = await bridge('save-explanation-draft', {requirements_id: requirement.id, run_ids: [run.id], claims,
    body: facts.map(f => `${run.result.rows[f.row].metric_key}: {{fact:${f.id}}}`).join('\n')});
  check('packaged_source_to_current_draft_complete', draft.completion, draft.completion?.status === 'complete');
  report.runId = run.id; report.draftId = draft.id;
  const next = spec('finance-context-save', {parent_id: context.id, bindings, scopes: {template_inputs: {period: '2026-10'}}});
  const nextStatus = spec('finance-profile-status', {context_id: next.id});
  check('changed_month_requires_new_confirmation', nextStatus.professional_status, nextStatus.professional_status === 'awaiting_profile_confirmation');
  const confirmationId = confirmed.rule_basis.confirmation_id;
  await bridge('finance-profile-revoke', {id: confirmationId, reason: '验收撤销：旧证据应失效'});
  const stale = await bridge('prepare-explanation', {run_ids: [run.id]});
  check('revocation_invalidates_old_amount_evidence', stale.facts.filter(f => f.column === 'value').map(f => f.evidence_eligibility),
    stale.facts.filter(f => f.column === 'value').every(f => f.evidence_eligibility?.counts_as_amount_evidence === false));
  const currentState = cli('analysis-state');
  const currentReceipt = currentState.completions.find(item => item.id === draft.completion.id);
  const currentDraft = currentState.drafts.find(item => item.id === draft.id);
  check('revocation_invalidates_current_completion', currentReceipt, currentReceipt?.status === 'awaiting_manager');
  check('revocation_marks_current_draft_for_review', currentDraft?.quality, currentDraft?.quality?.status === 'needs_attention');
  report.status = 'passed';
}
main().catch(async error => {report.status = 'failed'; report.error = String(error.stack || error);
  if (page) await screenshot('failure').catch(() => {}); process.exitCode = 1;
}).finally(async () => {if (app) await app.close(); fs.writeFileSync(path.join(qa, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({status: report.status, qa, checks: report.checks.length, error: report.error}));});
