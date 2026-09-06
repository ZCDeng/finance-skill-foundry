#!/usr/bin/env node
/**
 * Installed native explanation-workbench QA.
 *
 * Usage, after a packaged app exists:
 *   PLAYWRIGHT_MODULE=/absolute/path/to/playwright \
 *   QA_APP=/Applications/Finance\ Skill\ Foundry.app/Contents/MacOS/Finance\ Skill\ Foundry \
 *   node tools/verify_explanation_workbench.cjs
 *
 * This script seeds synthetic finance evidence through the packaged foundry CLI,
 * then verifies the installed Electron UI and IPC path. It does not send chat
 * prompts, does not call a model provider, and does not replace the backend with
 * a mock. Synthetic rows are fixtures for UI/explanation-quality acceptance.
 */
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {execFileSync} = require('node:child_process');
const {_electron} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const qa = fs.mkdtempSync('/tmp/finance-explanation-workbench-');
const varRoot = path.join(qa, 'var');
const fixturesDir = path.join(qa, 'fixtures');
const screenshotsDir = path.join(qa, 'screenshots');
fs.mkdirSync(fixturesDir, {recursive: true});
fs.mkdirSync(screenshotsDir, {recursive: true});

const executablePath = process.env.QA_APP;
if (!executablePath) throw new Error('QA_APP must identify the packaged Electron executable');
const resources = path.resolve(path.dirname(executablePath), '../Resources');
const appAsarPath = path.join(resources, 'app.asar');
const appAsarSha256 = fs.existsSync(appAsarPath) ? sha256File(appAsarPath) : null;
const bin = process.env.QA_FOUNDRY || path.join(resources, 'foundry/foundry');
if (!fs.existsSync(bin)) throw new Error('Packaged foundry binary missing: ' + bin);

const report = {
  status: 'running',
  qa,
  executablePath,
  resources,
  appAsarSha256,
  foundryCommand: bin,
  checks: [],
  fixtures: [],
  screenshots: [],
  modelRequestTripwire: {blockedUrls: [], ipcSubmissions: []},
  notTested: [
    'Real model/provider answer quality; this script deliberately sends no chat prompt.',
    'Human managerial correctness beyond deterministic fixture arithmetic.',
  ],
};

let app;
let page;

function sha256File(file) {
  return createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function writeJson(file, value) {
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
  return file;
}

function check(name, basis, observed, valid) {
  report.checks.push({name, basis, status: valid ? 'passed' : 'failed', observed});
  if (!valid) throw new Error(`${name}: ${JSON.stringify(observed)}`);
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function until(read, accept, label, timeout = 20000) {
  const deadline = Date.now() + timeout;
  let value;
  while (Date.now() < deadline) {
    value = await read();
    if (accept(value)) return value;
    await delay(100);
  }
  throw new Error(`${label}: ${JSON.stringify(value)}`);
}

function cli(command, args = [], task, raw = false) {
  const output = execFileSync(bin, [
    '--var', varRoot,
    ...(task ? ['--task', task] : []),
    command,
    ...args,
  ], {
    encoding: 'utf8',
    env: sanitizedEnv(),
    stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();
  return raw ? output : JSON.parse(output);
}

function cliSpec(command, spec, task) {
  return cli(command, ['--spec', JSON.stringify(spec)], task);
}

function sanitizedEnv() {
  const env = {...process.env, FOUNDRY_VAR: varRoot};
  for (const key of [
    'FOUNDRY_BIN',
    'FOUNDRY_DSH_INSTALL',
    'FOUNDRY_FORMULATOR_BIN',
    'OPENAI_API_KEY',
    'ANTHROPIC_API_KEY',
    'DEEPSEEK_API_KEY',
    'AZURE_OPENAI_API_KEY',
  ]) delete env[key];
  return env;
}

async function screenshot(name) {
  const file = path.join(screenshotsDir, `${name}.png`);
  if (page) {
    await page.screenshot({path: file, fullPage: true});
    report.screenshots.push(file);
  }
  return file;
}

async function clickIfVisible(locator) {
  if (await locator.count().catch(() => 0)) {
    const first = locator.first();
    if (await first.isVisible().catch(() => false)) {
      await first.click();
      return true;
    }
  }
  return false;
}

async function selectTask(taskTitle) {
  await clickIfVisible(page.getByRole('button', {name: '展开任务列表', exact: true}));
  const taskButton = page.locator(`.workspace-task[title="${cssEscape(taskTitle)}"]`).first();
  await taskButton.waitFor({state: 'visible', timeout: 30000});
  await taskButton.click();
  await page.waitForFunction(
    (title) => document.querySelector(`.workspace-task[title="${CSS.escape(title)}"]`)?.getAttribute('aria-current') === 'true',
    taskTitle,
    {timeout: 15000},
  );
}

function cssEscape(value) {
  return String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
}

async function openDraftsTab() {
  await page.getByRole('tab', {name: /文稿/}).click();
  await until(
    () => page.getByRole('tabpanel').evaluate((el) => el.textContent || '').catch(() => ''),
    (text) => text.includes('文稿') || text.includes('写下判断与建议'),
    'draft tab visible',
  );
}

async function invokeBridge(method, args = []) {
  return page.evaluate(async ({method, args}) => window.foundry[method](...args), {method, args});
}

async function seedFixture() {
  const taskTitle = `验收：解释质量工作台 ${new Date().toISOString()}`;
  const taskId = cli('task-new', ['--title', taskTitle, '--period', '2026-09'], undefined, true);
  const actualRows = [
    {ledger: 'L1', organization: 'O1', period: '2026-09', currency: 'CNY', unit: '万元', scenario: 'actual', account_code: '6001', management_account: 'revenue', amount: 120, doc_id: 'INV-001', line_id: '1'},
    {ledger: 'L1', organization: 'O1', period: '2026-09', currency: 'CNY', unit: '万元', scenario: 'actual', account_code: '6401', management_account: 'cost', amount: 70, doc_id: 'BILL-002', line_id: '1'},
    {ledger: 'L1', organization: 'O1', period: '2026-09', currency: 'CNY', unit: '万元', scenario: 'actual', account_code: '6601', management_account: 'expense', amount: 20, doc_id: 'EXP-003', line_id: '1'},
  ];
  const budgetRows = [
    {ledger: 'L1', organization: 'O1', period: '2026-09', currency: 'CNY', unit: '万元', scenario: 'budget', account_code: '6001', management_account: 'revenue', amount: 100, doc_id: 'BUD-001', line_id: '1'},
    {ledger: 'L1', organization: 'O1', period: '2026-09', currency: 'CNY', unit: '万元', scenario: 'budget', account_code: '6401', management_account: 'cost', amount: 60, doc_id: 'BUD-002', line_id: '1'},
    {ledger: 'L1', organization: 'O1', period: '2026-09', currency: 'CNY', unit: '万元', scenario: 'budget', account_code: '6601', management_account: 'expense', amount: 15, doc_id: 'BUD-003', line_id: '1'},
  ];
  const actualPath = writeJson(path.join(fixturesDir, 'actual.json'), actualRows);
  const budgetPath = writeJson(path.join(fixturesDir, 'budget.json'), budgetRows);
  report.fixtures.push({name: 'actual', path: actualPath, rows: actualRows.length, synthetic: true});
  report.fixtures.push({name: 'budget', path: budgetPath, rows: budgetRows.length, synthetic: true});

  const actual = cli('dataset-add', ['--path', actualPath, '--name', 'QA 实际发生'], taskId);
  const budget = cli('dataset-add', ['--path', budgetPath, '--name', 'QA 预算'], taskId);
  const context = cliSpec('finance-context-save', {
    name: 'QA 解释质量口径',
    bindings: {actual: actual.id, budget: budget.id},
    scopes: {
      actual: {ledger: 'L1', organization: 'O1', period: '2026-09', currency: 'CNY', unit: '万元', scenario: 'actual'},
      budget: {ledger: 'L1', organization: 'O1', period: '2026-09', currency: 'CNY', unit: '万元', scenario: 'budget'},
    },
  }, taskId);
  const run = cliSpec('explain-variance', {context_id: context.id}, taskId);
  check('seed_finance_run_succeeded', 'packaged CLI persisted synthetic actual/budget/context/run', {
    taskId,
    contextId: context.id,
    runId: run.id,
    status: run.execution_status,
    rows: run.result?.rows,
  }, run.execution_status === 'succeeded' && Array.isArray(run.result?.rows) && run.result.rows.some((row) => String(row.contribution) === '5'));

  const prepared = cliSpec('prepare-explanation', {run_ids: [run.id]}, taskId);
  const profitFact = prepared.facts.find((fact) => fact.column === 'contribution' && String(fact.value) === '5') || prepared.facts[0];
  check('seed_prepare_fact_available', 'packaged CLI prepare-explanation emitted bound facts', profitFact, Boolean(profitFact?.id && profitFact?.row != null));

  const draft = cliSpec('save-explanation-draft', {
    title: 'QA 利润说明',
    body: `利润超预算 {{fact:${profitFact.id}}}，请在文稿页验证可下钻来源。`,
    run_ids: [run.id],
    fact_ids: [profitFact.id],
    review_status: 'unreviewed',
    publication_status: 'draft',
  }, taskId);
  const validation = cliSpec('validate-explanation', {draft_id: draft.id}, taskId);
  check('seed_draft_quality_passed', 'packaged CLI save-explanation-draft and validate-explanation', {
    draftId: draft.id,
    status: validation.status,
    body: draft.body,
  }, validation.status === 'pass' && draft.body.includes('5 万元'));

  return {taskTitle, taskId, actual, budget, context, run, prepared, profitFact, draft};
}

async function verifyUi(seed) {
  const env = sanitizedEnv();
  app = await _electron.launch({
    executablePath,
    args: [`--user-data-dir=${path.join(qa, 'profile')}`],
    env,
    timeout: 60000,
  });
  page = await app.firstWindow();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForFunction(() => window.foundry?.harnessOpen && window.foundry?.financeCall, {timeout: 60000});
  await page.evaluate(() => {
    window.__qaBlockedModelUrls = [];
    const originalFetch = window.fetch;
    window.fetch = function qaNoModelFetch(input, init) {
      const url = typeof input === 'string' ? input : input?.url || '';
      if (/\/api\/session\.(prompt|send)(?:[/?]|$)/.test(url)) {
        window.__qaBlockedModelUrls.push(url);
        return Promise.reject(new Error('QA forbids model/session prompt calls'));
      }
      return originalFetch.call(this, input, init);
    };
  });
  await page.evaluate(() => {
    window.__qaHarnessSubmissions = [];
    const original = window.foundry.harnessOpen;
    window.foundry.harnessOpen = (...args) => {
      window.__qaHarnessSubmissions.push(args);
      if (args[2]?.submit) throw new Error('QA forbids submitted harnessOpen prompts');
      return original(...args);
    };
  });
  await until(
    () => invokeBridge('harnessStatus'),
    (reply) => {
      if (reply.ok && reply.value?.wiring?.state === 'failed') throw new Error('packaged wiring failed: ' + JSON.stringify(reply));
      return reply.ok && reply.value?.wiring?.state === 'ready';
    },
    'packaged wiring',
    90000,
  );
  await page.setViewportSize({width: 1500, height: 920}).catch(() => undefined);
  await selectTask(seed.taskTitle);
  const opened = await invokeBridge('harnessOpen', ['analysis', seed.taskId]);
  check('open_seeded_task_without_prompt_submission', 'installed app main/CLI/native IPC', opened, opened.ok && Boolean(opened.value?.sessionId));
  await openDraftsTab();
  await page.getByRole('heading', {name: /QA 利润说明|文稿/}).first().waitFor({timeout: 30000});

  const quality = page.getByRole('region', {name: '文稿质量检查'});
  await quality.waitFor({state: 'visible', timeout: 30000});
  await until(
    () => quality.evaluate((el) => el.textContent || ''),
    (text) => text.includes('检查通过') && text.includes('已引用'),
    'quality facts loaded',
    30000,
  );
  check('quality_panel_shows_passed_fact', 'real renderer reading packaged backend quality state', await quality.textContent(), true);

  const factsDetails = quality.locator('details').filter({hasText: '可引用事实'}).first();
  await factsDetails.locator('summary').click();
  await quality.getByRole('button', {name: '下钻此事实来源'}).first().click();
  const drilldown = await until(
    () => quality.evaluate((el) => el.textContent || ''),
    (text) => text.includes('来源行可查看') && (text.includes('INV-001') || text.includes('BILL-002') || text.includes('EXP-003')),
    'fact source drilldown',
    30000,
  );
  check('fact_drilldown_displays_source_row', 'real UI invokes drilldown-fact through IPC and packaged CLI', drilldown.slice(0, 1200), true);

  await page.getByRole('button', {name: '编辑文稿'}).click();
  const body = page.getByLabel('文稿正文');
  await body.waitFor({state: 'visible', timeout: 15000});
  const currentBody = await body.inputValue();
  await body.fill(currentBody.replace(/5\s*万元/g, '999 万元'));
  await page.getByRole('button', {name: '重检当前正文'}).click();
  const badQuality = await until(
    () => quality.evaluate((el) => el.textContent || ''),
    (text) => text.includes('999') || text.includes('需要复核') || text.includes('未引用'),
    'wrong number quality issue',
    30000,
  );
  const saveButtons = await page.getByRole('button', {name: /保存文稿新版|选定并归档此版/}).evaluateAll((buttons) => buttons.map((button) => ({text: button.textContent, disabled: button.disabled})));
  check('wrong_number_recheck_flags_issue_save_available', 'real UI keeps draft save path available while quality warns', {badQuality: badQuality.slice(0, 1200), saveButtons}, saveButtons.some((button) => !button.disabled));
  await page.getByRole('button', {name: '保存文稿新版'}).click();
  await until(
    () => page.getByText('已保存为新的文稿版本。').isVisible().catch(() => false),
    Boolean,
    'wrong-number draft saved notice',
    30000,
  );

  const bgDetails = page.locator('details.analysis-background-panel').first();
  await bgDetails.locator('summary').first().click();
  await page.getByLabel('背景组织').fill('O1');
  await page.getByLabel('背景期间').fill('2026-09');
  await bgDetails.locator('input').first().fill('QA 管理判断');
  await bgDetails.locator('textarea.analysis-code').first().fill('QA 背景：销售节奏提前，利润差异需要经理复核。');
  await page.getByRole('button', {name: '保存背景'}).click();
  await until(
    () => page.getByText('已保存财务背景。').isVisible().catch(() => false),
    Boolean,
    'background saved notice',
    30000,
  );
  const screenshotPath = await screenshot('explanation-workbench');
  check('screenshot_captured', 'real installed renderer screenshot', screenshotPath, fs.existsSync(screenshotPath));

  const state = cli('analysis-state', [], seed.taskId);
  const drafts = state.drafts || [];
  const savedWrongDraft = drafts.find((draft) => draft.body?.includes('999 万元'));
  const backgrounds = cliSpec('finance-background-list', {context_id: seed.context.id}, seed.taskId);
  check('cli_persistence_after_ui_actions', 'packaged CLI rereads UI-saved draft/background from isolated FOUNDRY_VAR', {
    draftCount: drafts.length,
    savedWrongDraftId: savedWrongDraft?.id,
    savedWrongDraftQuality: savedWrongDraft?.explanation_check?.status,
    backgrounds: backgrounds.business_contexts || backgrounds.backgrounds || backgrounds.items,
  }, Boolean(savedWrongDraft?.id) && savedWrongDraft?.explanation_check?.status === 'needs_attention' && (backgrounds.business_contexts || backgrounds.backgrounds || backgrounds.items || []).some((row) => String(row.text || '').includes('销售节奏提前')));

  const trips = await page.evaluate(() => ({blockedUrls: window.__qaBlockedModelUrls || [], harnessSubmissions: window.__qaHarnessSubmissions || []}));
  report.modelRequestTripwire = trips;
  check('zero_model_requests', 'fetch and harnessOpen submit tripwires inside installed renderer', trips, trips.blockedUrls.length === 0 && trips.harnessSubmissions.every((args) => !args[2]?.submit));
}

(async () => {
  const seed = await seedFixture();
  report.seed = {
    taskId: seed.taskId,
    taskTitle: seed.taskTitle,
    datasetIds: {actual: seed.actual.id, budget: seed.budget.id},
    contextId: seed.context.id,
    runId: seed.run.id,
    draftId: seed.draft.id,
    selectedFactId: seed.profitFact.id,
  };
  await verifyUi(seed);
  report.status = 'passed';
})().catch(async (error) => {
  report.status = 'failed';
  report.error = error.stack || String(error);
  if (page) {
    try {
      report.failureText = await page.evaluate(() => document.body.innerText.slice(0, 20000));
      await screenshot('failure');
    } catch (captureError) {
      report.captureError = String(captureError);
    }
  }
  process.exitCode = 1;
}).finally(async () => {
  if (app) {
    try {
      await app.close();
    } catch (error) {
      report.status = 'failed';
      report.closeError = String(error);
      process.exitCode = 1;
    }
  }
  const output = path.join(qa, 'explanation-workbench-receipt.json');
  writeJson(output, report);
  console.log(JSON.stringify({...report, receiptPath: output}));
});
