#!/usr/bin/env node
/**
 * Candidate native structured-aggregate workbench QA.
 *
 * Usage, after a packaged app exists:
 *   QA_OUT=build/verification/r4-integration/structured-aggregate-candidate-ui \
 *   PLAYWRIGHT_MODULE=/absolute/path/to/playwright-core \
 *   QA_APP=/absolute/path/to/FA\ Foundry.app/Contents/MacOS/FA\ Foundry \
 *   node tools/verify_structured_aggregate_workbench.cjs
 *
 * The script seeds one synthetic structured_aggregate run through the packaged
 * foundry CLI, launches the candidate Electron app with an isolated profile,
 * and verifies the real renderer/IPC path. It deliberately sends no chat prompt
 * and blocks model-style prompt submission surfaces.
 */
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {execFileSync} = require('node:child_process');

const qa = fs.mkdtempSync('/tmp/finance-structured-aggregate-workbench-');
const varRoot = path.join(qa, 'var');
const fixturesDir = path.join(qa, 'fixtures');
const screenshotsDir = path.join(qa, 'screenshots');
fs.mkdirSync(fixturesDir, {recursive: true});
fs.mkdirSync(screenshotsDir, {recursive: true});

const executablePath = process.env.QA_APP;
const qaOut = process.env.QA_OUT ? path.resolve(process.env.QA_OUT) : null;

const report = {
  status: 'running',
  qa,
  qaOut,
  executablePath: executablePath || null,
  resources: null,
  appAsarSha256: null,
  foundryCommand: null,
  task: null,
  seededRun: null,
  checks: [],
  fixtures: [],
  screenshots: [],
  modelRequestTripwire: {blockedUrls: [], ipcSubmissions: []},
  notTested: [
    'Real model/provider answer quality; this script deliberately sends no chat prompt.',
    'Production /Applications replacement or installed-app state; QA_APP is launched directly as a candidate bundle.',
    'Human managerial correctness beyond deterministic fixture arithmetic and source-trace rendering.',
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

function cli(command, args = [], task, raw = false) {
  const output = execFileSync(report.foundryCommand, [
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

async function screenshot(name) {
  const file = path.join(screenshotsDir, `${name}.png`);
  await page.screenshot({path: file, fullPage: true});
  report.screenshots.push(file);
  return file;
}

function cssEscape(value) {
  return String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
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

async function invokeBridge(method, args = []) {
  return page.evaluate(async ({method, args}) => window.foundry[method](...args), {method, args});
}

async function ensureDetailsOpenBySummary(summaryText) {
  const details = page.locator('details').filter({hasText: summaryText}).first();
  await details.waitFor({state: 'visible', timeout: 15000});
  const wasOpen = await details.evaluate((node) => node.open);
  if (!wasOpen) await details.locator('summary').first().click();
  await until(() => details.evaluate((node) => node.open), Boolean, `${summaryText} details opened`, 10000);
  return details;
}

async function openResultsTab() {
  const tabbar = page.locator('.analysis-tabbar:visible').last();
  const tab = tabbar.getByRole('tab', {name: /结果/});
  await tab.waitFor({state: 'visible', timeout: 30000});
  await tab.click();
  await until(
    () => tab.getAttribute('aria-selected').catch(() => null),
    (selected) => selected === 'true',
    'results tab selected',
    10000,
  );
}

async function blockPromptSubmissionSurfaces() {
  await page.evaluate(() => {
    window.__qaBlockedUrls = [];
    window.__qaHarnessSubmissions = [];
    window.__qaFinanceCalls = [];
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const input = args[0];
      const url = typeof input === 'string' ? input : input?.url || '';
      if (/\/api\/session\.(prompt|send)/.test(url)) {
        window.__qaBlockedUrls.push(url);
        throw new Error(`QA blocked model prompt request: ${url}`);
      }
      return originalFetch(...args);
    };
    const installBridgeGuard = () => {
      if (!window.foundry || window.__qaBridgeGuardInstalled) return Boolean(window.__qaBridgeGuardInstalled);
      window.__qaBridgeGuardInstalled = true;
      if (typeof window.foundry.harnessOpen === 'function') {
        const originalHarnessOpen = window.foundry.harnessOpen.bind(window.foundry);
        window.foundry.harnessOpen = async (...args) => {
          window.__qaHarnessSubmissions.push(args);
          if (args[2]?.submit) throw new Error('QA blocked harnessOpen submit=true');
          return originalHarnessOpen(...args);
        };
      }
      if (typeof window.foundry.financeCall === 'function') {
        const originalFinanceCall = window.foundry.financeCall.bind(window.foundry);
        window.foundry.financeCall = async (...args) => {
          window.__qaFinanceCalls.push(args);
          return originalFinanceCall(...args);
        };
      }
      return true;
    };
    installBridgeGuard();
    const timer = setInterval(() => {
      if (installBridgeGuard()) clearInterval(timer);
    }, 50);
  });
}

function seedFixture() {
  const taskTitle = `验收：结构化汇总工作台 ${new Date().toISOString()}`;
  const taskId = cli('task-new', ['--title', taskTitle, '--period', '2026-09'], undefined, true);
  const rows = [
    {period: '2026-09', region: '华东', department: '直营', currency: 'CNY', unit: '万元', account: '收入', amount: '120', customer: '客户甲', doc_id: 'AR-001', line_id: '1', source_status: 'posted', source_note: '已入账销售发票'},
    {period: '2026-09', region: '华东', department: '直营', currency: 'CNY', unit: '万元', account: '收入', amount: '80', customer: '客户乙', doc_id: 'AR-002', line_id: '1', source_status: 'posted', source_note: '已入账销售发票'},
    {period: '2026-09', region: '华东', department: '直营', currency: 'CNY', unit: '万元', account: '收入', amount: null, customer: '客户缺失', doc_id: 'AR-003', line_id: '1', source_status: 'posted', source_note: '来源金额待补'},
    {period: '2026-09', region: '海外', department: '直营', currency: 'USD', unit: '万美元', account: '收入', amount: '15', customer: '客户海外', doc_id: 'AR-004', line_id: '1', source_status: 'posted', source_note: '外币销售发票'},
    {period: '2026-09', region: '华南', department: '经销', currency: 'CNY', unit: '万元', account: '收入', amount: '50', customer: '客户剔除', doc_id: 'AR-005', line_id: '1', source_status: 'duplicate_pull', source_note: '重复拉取应剔除'},
  ];
  const fixturePath = writeJson(path.join(fixturesDir, 'structured-aggregate-source.json'), rows);
  report.fixtures.push({name: 'structured-source', path: fixturePath, rows: rows.length, synthetic: true});

  const dataset = cli('dataset-add', ['--path', fixturePath, '--name', 'QA 结构化单快照'], taskId);
  const definition = cliSpec('analysis-save', {
    question: '结构化聚合验收：收入按地区和币种分组',
    engine: 'structured_aggregate',
    bindings: {actual: dataset.id},
    aggregate_plan: {
      dataset_alias: 'actual',
      filters: [{field: 'period', op: 'eq', value: '2026-09', reason: '候选包验收期间'}],
      exclusions: [{field: 'source_status', op: 'eq', value: 'duplicate_pull', reason: '剔除重复拉取来源'}],
      group_by: ['period', 'region', 'currency', 'unit'],
      measures: [
        {name: 'revenue', field: 'amount', aggregation: 'sum'},
        {name: 'first_amount', field: 'amount', aggregation: 'min'},
        {name: 'customer_count', field: 'customer', aggregation: 'count_distinct'},
      ],
      dedupe: {policy: 'keep_first_identical_else_error', keys: ['doc_id', 'line_id']},
      result_key_columns: ['period', 'region', 'currency', 'unit'],
      scope: {period: '2026-09'},
    },
  }, taskId);
  const run = cli('analysis-run', ['--analysis', definition.id], taskId);
  report.task = {id: taskId, title: taskTitle};
  report.seededRun = {id: run.id, definitionId: definition.id, datasetId: dataset.id, status: run.execution_status};

  const result = run.result || {};
  const diagnostics = Array.isArray(result.diagnostics) ? result.diagnostics : [];
  const rowsOut = Array.isArray(result.rows) ? result.rows : [];
  check('cli_structured_run_succeeded', 'packaged CLI creates a structured_aggregate run without mocks', {
    runId: run.id,
    engine: run.engine,
    status: run.execution_status,
    rowCount: rowsOut.length,
  }, run.engine === 'structured_aggregate' && run.execution_status === 'succeeded' && rowsOut.length >= 2);
  check('cli_multicurrency_grouping_present', 'result rows preserve separate CNY and USD groups', {
    groups: rowsOut.map((row) => ({period: row.period, region: row.region, currency: row.currency, revenue: row.revenue})),
  }, rowsOut.some((row) => row.region === '华东' && row.currency === 'CNY') && rowsOut.some((row) => row.region === '海外' && row.currency === 'USD'));
  check('cli_detail_and_exclusion_present', 'structured result contains included and excluded source maps for UI drilldown', {
    detailRows: result.detail_rows?.length || 0,
    excludedRows: result.excluded_detail_rows?.length || 0,
  }, Array.isArray(result.detail_rows) && result.detail_rows.length > 0 && Array.isArray(result.excluded_detail_rows) && result.excluded_detail_rows.length > 0);
  check('cli_missing_amount_diagnostic_present', 'missing measure values emit real backend aggregation diagnostics', diagnostics, diagnostics.some((item) => item?.code === 'aggregate_missing_measure_values' && item.aggregation === 'sum'));
  check('cli_provenance_verified', 'structured aggregate result carries executor source-map provenance', result.provenance || null, result.provenance?.mode === 'executor_verified_source_map' && result.provenance?.status === 'verified');
  return {taskId, taskTitle, runId: run.id};
}

async function launchCandidate() {
  const playwrightModule = process.env.PLAYWRIGHT_MODULE || 'playwright';
  const {_electron} = require(playwrightModule);
  app = await _electron.launch({
    executablePath,
    args: [`--user-data-dir=${path.join(qa, 'profile')}`],
    env: sanitizedEnv(),
    timeout: 60000,
  });
  page = await app.firstWindow();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForFunction(() => window.foundry?.harnessOpen && window.foundry?.financeCall, {timeout: 60000});
  await blockPromptSubmissionSurfaces();
}

async function verifyUi(taskTitle) {
  await until(
    () => invokeBridge('harnessStatus').catch((error) => ({error: String(error)})),
    (status) => status?.ok && status.value?.wiring?.state === 'ready',
    'harness status ready',
    60000,
  );
  await selectTask(taskTitle);
  await invokeBridge('harnessOpen', ['analysis', report.task.id]);
  await openResultsTab();
  await page.getByText('结构化汇总结果').waitFor({state: 'visible', timeout: 30000});
  await screenshot('structured-results');

  const mainText = await page.locator('body').innerText();
  check('ui_manager_table_visible', 'real candidate renderer shows structured aggregate table and multicurrency groups', {
    hasCaption: mainText.includes('结构化汇总结果'),
    hasEast: mainText.includes('华东'),
    hasOverseas: mainText.includes('海外'),
    hasCny: mainText.includes('CNY'),
    hasUsd: mainText.includes('USD'),
  }, mainText.includes('结构化汇总结果') && mainText.includes('华东') && mainText.includes('海外') && mainText.includes('CNY') && mainText.includes('USD'));
  check('ui_provenance_wording_bounded', 'source traceability is visible but explicitly not a business-judgment approval', {
    sourceTraceable: mainText.includes('来源可追溯'),
    businessJudgmentBoundary: mainText.includes('不代表业务判断'),
  }, mainText.includes('来源可追溯') && mainText.includes('不代表业务判断'));
  check('ui_missing_amount_diagnostic_readable', 'aggregate_missing_measure_values is presented as Chinese manager-readable diagnostic', {
    includesMissing: mainText.includes('来源金额缺失'),
    includesIncompleteOrExcluded: mainText.includes('汇总未完成') || mainText.includes('缺失来源'),
  }, mainText.includes('来源金额缺失') && (mainText.includes('汇总未完成') || mainText.includes('缺失来源')));

  const rawDetails = page.locator('details').filter({hasText: '原始结果字段'}).first();
  await rawDetails.waitFor({state: 'visible', timeout: 15000});
  const rawInitiallyOpen = await rawDetails.evaluate((node) => node.open);
  const rawTechnicalVisibleBeforeOpen = await page.locator('body').innerText().then((text) => ['result_key', 'source_rows', 'excluded_source_rows', 'provenance_status'].some((key) => text.includes(key)));
  check('ui_raw_technical_fields_collapsed', 'technical columns are not part of the daily manager view before raw fields are expanded', {
    rawInitiallyOpen,
    rawTechnicalVisibleBeforeOpen,
  }, rawInitiallyOpen === false && rawTechnicalVisibleBeforeOpen === false);

  await ensureDetailsOpenBySummary('原始结果字段');
  await until(
    () => page.locator('body').innerText(),
    (text) => text.includes('result_key') || text.includes('source_rows') || text.includes('provenance_status'),
    'raw technical fields visible after expansion',
    10000,
  );
  await screenshot('structured-raw-expanded');

  await ensureDetailsOpenBySummary('剔除明细');
  await until(
    () => page.locator('body').innerText(),
    (text) => text.includes('剔除重复拉取来源'),
    'excluded detail rows visible',
    10000,
  );

  const sourceSelect = page.getByLabel('结果行来源').first();
  await sourceSelect.waitFor({state: 'visible', timeout: 15000});
  await sourceSelect.selectOption('excluded_detail_rows:0');
  await page.getByRole('button', {name: '查看来源行'}).click();
  const sourceDetail = page.locator('.analysis-drilldown-result details').first();
  await sourceDetail.waitFor({state: 'visible'});
  await sourceDetail.locator('summary').click();
  await until(
    () => page.locator('body').innerText(),
    (text) => text.includes('客户剔除') && text.includes('AR-005'),
    'excluded source drilldown opens real source record',
    20000,
  );
  await screenshot('structured-excluded-drilldown');
  const state = cli('analysis-state', [], report.task.id);
  const checks = state.evidence_checks || [];
  check('ui_excluded_drilldown_persisted_verified_source', 'real UI click persists excluded section and original source row identity', checks,
    checks.some((item) => item.location?.run_id === report.seededRun.id && item.location?.section === 'excluded_detail_rows'
      && item.status === 'verified' && item.sources?.some((source) => source.dataset_id === report.seededRun.datasetId && source.row_index === 5)));


  const tripwire = await page.evaluate(() => ({blockedUrls: window.__qaBlockedUrls || [], harnessSubmissions: window.__qaHarnessSubmissions || []}));
  report.modelRequestTripwire.blockedUrls = tripwire.blockedUrls;
  report.modelRequestTripwire.ipcSubmissions = tripwire.harnessSubmissions;
  check('qa_no_model_prompt_surface_used', 'QA opens workbench and drilldown only; it does not submit chat/model prompts', tripwire, tripwire.blockedUrls.length === 0 && !tripwire.harnessSubmissions.some((args) => args?.[2]?.submit));
}

function copyDirSync(src, dest) {
  fs.mkdirSync(dest, {recursive: true});
  for (const entry of fs.readdirSync(src, {withFileTypes: true})) {
    const from = path.join(src, entry.name);
    const to = path.join(dest, entry.name);
    if (entry.isDirectory()) copyDirSync(from, to);
    else if (entry.isFile()) fs.copyFileSync(from, to);
  }
}

function persistReport() {
  const receipt = path.join(qa, 'structured-aggregate-workbench-receipt.json');
  writeJson(receipt, report);
  if (qaOut) {
    fs.mkdirSync(qaOut, {recursive: true});
    writeJson(path.join(qaOut, 'structured-aggregate-workbench-receipt.json'), report);
    writeJson(path.join(qaOut, 'summary.json'), {
      status: report.status,
      qa,
      executablePath: report.executablePath,
      appAsarSha256: report.appAsarSha256,
      checks: report.checks.map(({name, status}) => ({name, status})),
      screenshots: report.screenshots,
      notTested: report.notTested,
    });
    for (const folder of ['fixtures', 'screenshots', 'var']) copyDirSync(path.join(qa, folder), path.join(qaOut, 'runtime-artifacts', folder));
  }
  return receipt;
}

async function main() {
  if (!executablePath) throw new Error('QA_APP must identify the packaged Electron executable');
  report.resources = path.resolve(path.dirname(executablePath), '../Resources');
  const appAsarPath = path.join(report.resources, 'app.asar');
  report.appAsarSha256 = fs.existsSync(appAsarPath) ? sha256File(appAsarPath) : null;
  report.foundryCommand = process.env.QA_FOUNDRY || path.join(report.resources, 'foundry/foundry');
  if (!fs.existsSync(report.foundryCommand)) throw new Error('Packaged foundry binary missing: ' + report.foundryCommand);

  const seeded = seedFixture();
  await launchCandidate();
  await verifyUi(seeded.taskTitle);
  report.status = 'passed';
}

main().catch(async (error) => {
  report.status = 'failed';
  report.error = {message: error.message, stack: error.stack};
  if (page) await screenshot('failure').catch(() => undefined);
  process.exitCode = 1;
}).finally(async () => {
  if (app) await app.close().catch(() => undefined);
  const receipt = persistReport();
  console.log(JSON.stringify({status: report.status, receipt, qa, qaOut, checks: report.checks}, null, 2));
});
