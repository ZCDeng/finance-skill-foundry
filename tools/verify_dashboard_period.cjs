#!/usr/bin/env node
/**
 * Packaged Electron acceptance for dashboard period bindings and carry recovery.
 *
 * After freezing and packaging the current checkout:
 *   QA_APP='/path/to/FA Foundry.app/Contents/MacOS/FA Foundry' \
 *   PLAYWRIGHT_MODULE='/existing/node_modules/playwright' \
 *   QA_OUT=build/verification/dashboard-period \
 *   node tools/verify_dashboard_period.cjs
 * For the explicitly requested installed-app acceptance, also set
 *   QA_ALLOW_INSTALLED=1 QA_APP='/Applications/FA Foundry.app/Contents/MacOS/FA Foundry'
 *
 * All writes are synthetic and confined to one fresh temporary HOME, profile,
 * harness home and FOUNDRY_VAR. The installed app needs an explicit opt-in;
 * this never sends a chat prompt or needs model credentials.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {createHash} = require('node:crypto');
const {execFileSync} = require('node:child_process');
const {pathToFileURL} = require('node:url');

const root = path.resolve(__dirname, '..');
const scratch = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'finance-dashboard-period-')));
const dirs = Object.fromEntries(['var', 'profile', 'home', 'harness', 'fixtures', 'screenshots', 'tmp'].map((name) => {
  const dir = path.join(scratch, name);
  fs.mkdirSync(dir, {recursive: true});
  return [name, dir];
}));
const out = process.env.QA_OUT ? path.resolve(process.env.QA_OUT) : null;
const executablePath = process.env.QA_APP ? path.resolve(process.env.QA_APP) : null;
const allowInstalled = process.env.QA_ALLOW_INSTALLED === '1';
const report = {
  status: 'running', scratch, out, executablePath, allowInstalled, bundle: null, checks: [], screenshots: [],
  fixtures: [], uiCalls: [], externalRequests: [], modelPromptRequests: [], sourceHistory: {},
  notTested: ['Real task data, provider responses, signing and notarization.',
    ...(!allowInstalled ? ['Installed /Applications application.'] : [])],
};
let app;
let page;
let foundry;

const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
const readHash = (file) => hash(fs.readFileSync(file));
const writeJson = (file, value) => fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
const canonical = (value) => Array.isArray(value) ? value.map(canonical)
  : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])])) : value;
const same = (left, right) => JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const env = {
  HOME: dirs.home, PATH: '/usr/bin:/bin', TMPDIR: dirs.tmp + '/',
  FOUNDRY_VAR: dirs.var, DSH_HOME: dirs.harness,
  LANG: 'en_US.UTF-8', LC_ALL: 'en_US.UTF-8',
};

function check(name, observed, valid) {
  report.checks.push({name, status: valid ? 'passed' : 'failed', observed});
  if (!valid) throw new Error(`${name}: ${JSON.stringify(observed)}`);
}

async function until(read, accept, label, timeout = 30000) {
  let value;
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    value = await read();
    if (accept(value)) return value;
    await delay(100);
  }
  throw new Error(`${label}: ${JSON.stringify(value)}`);
}

function cli(command, args = [], task, raw = false, actor = 'manager') {
  const text = execFileSync(foundry, [
    '--var', dirs.var, ...(task ? ['--task', task] : []), '--actor', actor, command, ...args,
  ], {encoding: 'utf8', env, timeout: 120000, maxBuffer: 32 * 1024 * 1024}).trim();
  return raw ? text : JSON.parse(text);
}

const spec = (command, value, task) => cli(command, ['--spec', JSON.stringify(value)], task);
const assistantSpec = (command, value, task) => cli(command, ['--spec', JSON.stringify(value)], task, false, 'assistant');
const task = (title, period) => ({id: cli('task-new', ['--title', title, '--period', period], undefined, true), title, period});
const analysisState = (taskId) => cli('analysis-state', [], taskId);
const dashboard = (taskId) => spec('dashboard-read', {}, taskId).dashboard;

function fixtureFile(name, period) {
  const file = path.join(dirs.fixtures, `${name}-${period}.json`);
  const rows = Array.from({length: 9}, (_, index) => ({
    metric: `metric_${index + 1}`, period, amount: String(Number(period.slice(-2)) * 100 + index + 1),
    currency: 'CNY', unit: '万元',
  }));
  writeJson(file, rows);
  report.fixtures.push({file, period, rows: rows.length, synthetic: true, sha256: readHash(file)});
  return file;
}

function addDataset(taskInfo, name = 'QA月度经营数据') {
  return cli('dataset-add', ['--path', fixtureFile(taskInfo.id, taskInfo.period), '--name', name], taskInfo.id);
}

function figureCards(run, count = 9) {
  return Array.from({length: count}, (_, index) => ({
    kind: 'figure', title: `期间验收指标 ${index + 1}`, state: 'accepted', accepted_by: 'QA 八月经理', run_id: run.id,
    select: {match: {metric: `metric_${index + 1}`, period: run.result.rows[0].period}, column: 'value'},
  }));
}

// Kept in one place so the fixture explicitly exercises the public contract.
function boundDefinition(datasetId) {
  return {
    question: '期间绑定验收：九个经营指标随本期重算', bindings: {actual: datasetId},
    sql: 'SELECT metric, $period AS period, CAST(amount AS DECIMAL(38,2)) AS value, currency, unit FROM actual WHERE period = $period ORDER BY metric',
    parameters: {period: '2026-08'}, scope: {period: '2026-08'},
    period_binding: {mode: 'current', parameters: ['period']},
  };
}

function seedPair(name, definition, count = 9) {
  const august = task(`QA 八月 · ${name}`, '2026-08');
  const september = task(`QA 九月 · ${name}`, '2026-09');
  const source = addDataset(august);
  addDataset(september);
  const saved = spec('analysis-save', definition(source.id), august.id);
  const run = cli('analysis-run', ['--analysis', saved.id], august.id);
  check(`${name}_august_run_succeeded`, {id: run.id, execution_status: run.execution_status}, run.execution_status === 'succeeded');
  const board = spec('dashboard-save', {parent_id: null, cards: figureCards(run, count)}, august.id);
  const before = analysisState(august.id);
  const sourceFiles = taskFiles(august.id);
  return {name, august, september, saved, run, board, before, sourceFiles};
}

function allFiles(dir, base = dir) {
  return fs.readdirSync(dir, {withFileTypes: true}).flatMap((entry) => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? allFiles(file, base) : entry.isFile() ? [path.relative(base, file)] : [];
  });
}

function taskFiles(taskId) {
  const dir = path.join(dirs.var, 'tasks', taskId);
  return Object.fromEntries(allFiles(dir).sort().map((file) => [file, readHash(path.join(dir, file))]));
}

function unchangedSource(pair) {
  const current = taskFiles(pair.august.id);
  report.sourceHistory[pair.august.id] = {
    title: pair.august.title, boardId: pair.board.id, runId: pair.run.id,
    before: pair.sourceFiles, after: current,
  };
  return {
    sameBoard: same(dashboard(pair.august.id), pair.board),
    sameState: same(analysisState(pair.august.id), pair.before),
    sameTaskFileBytes: same(current, pair.sourceFiles),
    sourceFileCount: Object.keys(pair.sourceFiles).length,
    changedFiles: [...new Set([...Object.keys(current), ...Object.keys(pair.sourceFiles)])]
      .filter((file) => current[file] !== pair.sourceFiles[file]),
  };
}

async function verifyCandidate() {
  if (!executablePath || !fs.existsSync(executablePath)) throw new Error('QA_APP must name an existing candidate Electron executable.');
  const realExecutable = fs.realpathSync(executablePath);
  if (realExecutable.includes('/Library/Application Support/')) {
    throw new Error('QA_APP must remain outside user data locations, including installed-app acceptance.');
  }
  if (realExecutable.startsWith('/Applications/')) {
    if (!allowInstalled || realExecutable !== '/Applications/FA Foundry.app/Contents/MacOS/FA Foundry') {
      throw new Error('Installed acceptance requires QA_ALLOW_INSTALLED=1 and /Applications/FA Foundry.app.');
    }
  }
  const resources = path.resolve(path.dirname(realExecutable), '../Resources');
  const archive = path.join(resources, 'app.asar');
  foundry = path.join(resources, 'foundry/foundry');
  const {foundrySourceHash, stampedHash} = await import(pathToFileURL(path.join(root, 'app/scripts/source-hash.mjs')).href);
  const current = foundrySourceHash(root, path.join(root, 'app/scripts/build-foundry.mjs'));
  const stamped = stampedHash(path.join(resources, 'foundry/BUILT'));
  check('candidate_frozen_cli_matches_current_source', {current, stamped, foundry}, current === stamped && fs.existsSync(foundry));
  const formulatorCurrent = foundrySourceHash(root, path.join(root, 'app/scripts/build-formulator.mjs'));
  const formulatorStamped = stampedHash(path.join(resources, 'formulator/BUILT'));
  check('candidate_formulator_embeds_current_foundry_source', {current: formulatorCurrent, stamped: formulatorStamped},
    formulatorCurrent === formulatorStamped);
  const asar = require(path.join(root, 'app/node_modules/@electron/asar'));
  const compared = [];
  for (const name of ['dist-electron', 'dist-vite']) {
    const dir = path.join(root, 'app', name);
    if (!fs.existsSync(dir)) throw new Error(`Build first: ${dir} missing.`);
    for (const file of allFiles(dir)) {
      if (name === 'dist-electron' && file.endsWith('.js.map')) continue;
      const from = path.join(name, file).split(path.sep).join('/');
      const source = readHash(path.join(dir, file));
      const packaged = hash(asar.extractFile(archive, from));
      if (source !== packaged) throw new Error(`Candidate differs from current build: ${from}`);
      compared.push(from);
    }
  }
  report.bundle = {resources, foundry, appAsarSha256: readHash(archive), sourceHash: current, comparedBuildFiles: compared.length};
  check('candidate_electron_and_renderer_match_current_build', {comparedFiles: compared.length}, compared.length > 2);
}

async function ipc(method, args = []) {
  report.uiCalls.push({method, command: method === 'financeCall' ? args[1] : undefined});
  const answer = await page.evaluate(({method, args}) => window.foundry[method](...args), {method, args});
  if (answer && answer.ok === false) throw new Error(`${method}: ${answer.message}`);
  return answer?.ok === true ? answer.value : answer;
}

async function screenshot(name) {
  const file = path.join(dirs.screenshots, `${name}.png`);
  await page.screenshot({path: file, fullPage: true});
  report.screenshots.push(file);
}

async function openBoard(taskInfo) {
  const workspace = page.getByRole('button', {name: '工作区', exact: true});
  if (await workspace.isVisible().catch(() => false)) await workspace.click();
  const expand = page.getByRole('button', {name: '展开任务列表', exact: true});
  if (await expand.isVisible().catch(() => false)) await expand.click();
  const direct = page.locator(`.workspace-task[title="${taskInfo.title}"]`).first();
  await direct.waitFor({state: 'visible', timeout: 30000});
  await direct.click();
  await ipc('harnessOpen', ['analysis', taskInfo.id]);
  const tabs = page.locator('.analysis-tabbar:visible').last();
  await tabs.getByRole('tab', {name: /汇报/}).click();
  const boardTab = page.getByRole('tab', {name: /^看板/}).last();
  if (await boardTab.isVisible().catch(() => false)) await boardTab.click();
  await page.locator('.dashboard').waitFor({state: 'visible', timeout: 30000});
}

async function verifyNineCards(pair) {
  await openBoard(pair.september);
  const offer = page.locator('.dashboard__templates li').filter({hasText: pair.august.title});
  await offer.waitFor({state: 'visible', timeout: 30000});
  await offer.getByRole('button', {name: /带过来并重算/}).click();
  await verifyCarriedNine(pair, 'bound');
}

async function verifyCarriedNine(pair, prefix) {
  await until(() => ipc('financeCall', [pair.september.id, 'dashboard-read', {}]), (read) => read.dashboard?.cards?.length === 9, 'nine cards carried');
  const cards = page.locator('.dashboard-card');
  await until(() => cards.count(), (count) => count === 9, 'nine rendered cards');
  const target = await ipc('analysisState', [pair.september.id]);
  const read = await ipc('financeCall', [pair.september.id, 'dashboard-read', {}]);
  check(`${prefix}_nine_cards_wait_for_fresh_manager_acceptance`, read.dashboard.cards.map(({state, accepted}) => ({state, accepted})),
    read.dashboard.cards.every((card) => card.state === 'pinned' && !card.accepted));
  const runs = new Map(target.runs.map((run) => [run.id, run]));
  const actual = read.dashboard.cards.map((card, index) => {
    const run = runs.get(card.run_id);
    const row = run?.result?.rows?.find((item) => item.metric === `metric_${index + 1}`);
    return {run: run?.id, period: row?.period, value: row?.value, expected: 901 + index};
  });
  check(`${prefix}_nine_cards_use_september_period_and_values`, actual,
    actual.every((item) => item.period === '2026-09' && Number(item.value) === item.expected));
  const periodRun = runs.get(read.dashboard.cards[0].run_id);
  check(`${prefix}_shared_run_has_frozen_september_parameter_binding`, {
    runIds: [...new Set(read.dashboard.cards.map((card) => card.run_id))],
    parameters: periodRun?.parameters, resolvedPeriod: periodRun?.resolved_period,
    selectionPeriods: read.dashboard.cards.map((card) => card.select.match.period),
  }, new Set(read.dashboard.cards.map((card) => card.run_id)).size === 1
    && periodRun.parameters?.period === '2026-09' && periodRun.resolved_period?.period === '2026-09'
    && read.dashboard.cards.every((card) => card.select.match.period === '2026-09'));
  const cardText = await cards.allTextContents();
  check(`${prefix}_nine_cards_render_september`, cardText, cardText.every((text) => /2026.*9/.test(text) && text.includes('待认可')));
  await screenshot(`${prefix}-nine-september-cards-waiting`);
  await cards.last().scrollIntoViewIfNeeded();
  await screenshot(`${prefix}-nine-september-cards-waiting-bottom`);
  for (let index = 0; index < 9; index += 1) {
    await cards.nth(index).getByRole('button', {name: '认可', exact: true}).click();
    await until(() => ipc('financeCall', [pair.september.id, 'dashboard-read', {}]),
      (value) => value.dashboard.cards[index].state === 'accepted', `manager accepted card ${index + 1}`);
  }
  const accepted = (await ipc('financeCall', [pair.september.id, 'dashboard-read', {}])).dashboard;
  check(`${prefix}_nine_cards_can_each_be_accepted_by_manager`, accepted.cards.map(({run_id, state, accepted}) => ({run_id, state, accepted})),
    accepted.cards.every((card) => card.state === 'accepted' && card.accepted?.run_id === card.run_id && card.accepted?.by === 'QA 九月经理'));
  const sourceEvidence = unchangedSource(pair);
  check(`${prefix}_august_board_runs_and_acceptance_remain_unchanged`, sourceEvidence,
    sourceEvidence.sameBoard && sourceEvidence.sameState && sourceEvidence.sameTaskFileBytes);
  await screenshot(`${prefix}-nine-september-cards-accepted`);
  await cards.first().scrollIntoViewIfNeeded();
  await screenshot(`${prefix}-nine-september-cards-accepted-top`);
}

async function verifyMissingScope(pair) {
  await openBoard(pair.september);
  const offers = await ipc('financeCall', [pair.september.id, 'dashboard-carry', {}]);
  const offer = offers.offers.find((row) => row.task_id === pair.august.id);
  check('missing_scope_literal_not_ready_to_carry', offer, Boolean(offer) && offer.ready === 0);
  const row = page.locator('.dashboard__templates li').filter({hasText: pair.august.title});
  await row.waitFor({state: 'visible', timeout: 30000});
  const text = await row.innerText();
  check('missing_scope_literal_explains_upgrade_in_ui', text, /升级|修复/.test(text));
  check('missing_scope_does_not_create_wrong_period_result', analysisState(pair.september.id).runs.length,
    analysisState(pair.september.id).runs.length === 0 && !dashboard(pair.september.id));
  await row.scrollIntoViewIfNeeded();
  await screenshot('03-missing-scope-needs-upgrade');
}

async function verifyRecovery(pair) {
  const row = page.locator('.dashboard__templates li').filter({hasText: pair.august.title});
  await row.getByRole('button', {name: '让助手修复计算', exact: true}).click();
  const pending = await until(() => ipc('financeCall', [pair.september.id, 'dashboard-read', {}]),
    (value) => value.carry_attempt?.failed?.length === 9, 'UI repair action persists nine failed cards');
  check('all_blocked_ui_action_authorizes_scoped_repair', pending.carry_attempt,
    pending.carry_attempt.from_task_id === pair.august.id && pending.carry_attempt.failed.every((item) => item.run_id === pair.run.id));
  // This deterministic CLI call stands in for the assistant tool. No model or
  // browser mock participates: actor=assistant must pass the real store gate.
  const original = assistantSpec('dashboard-repair-read', {run_id: pair.run.id}, pair.september.id);
  const originalText = JSON.stringify(original);
  check('assistant_can_read_only_attempt_authorized_legacy_run', original,
    originalText.includes(pair.run.id) && originalText.includes('2026-08'));
  const replacement = boundDefinition(pair.saved.bindings.actual);
  const proposed = assistantSpec('dashboard-repair-propose', {
    run_id: pair.run.id,
    spec: {sql: replacement.sql, parameters: replacement.parameters, period_binding: replacement.period_binding},
  }, pair.september.id);
  report.repairProposal = proposed;
  check('repair_proposal_records_verified_august_replay', {
    sourceRunId: proposed.source_run_id, targetPeriod: proposed.resolved_period, baseline: proposed.baseline,
  }, proposed.source_run_id === pair.run.id && proposed.resolved_period === '2026-09'
    && proposed.baseline?.verified === true
    && proposed.baseline.source_result_hash === proposed.baseline.replayed_result_hash);
  const sourceEvidence = unchangedSource(pair);
  check('repair_proposal_preserves_august_source_history', sourceEvidence,
    sourceEvidence.sameBoard && sourceEvidence.sameState && sourceEvidence.sameTaskFileBytes);
  const beforeManager = await ipc('financeCall', [pair.september.id, 'dashboard-read', {}]);
  check('repair_proposal_waits_for_manager_to_continue', beforeManager,
    !beforeManager.dashboard?.cards?.length && beforeManager.carry_attempt?.failed?.length === 9);
  await openBoard(pair.september);
  const resume = page.getByRole('button', {name: /继续带入剩余卡/});
  await resume.waitFor({state: 'visible', timeout: 30000});
  await resume.scrollIntoViewIfNeeded();
  await screenshot('recovery-ready-to-continue');
  await resume.click();
  await verifyCarriedNine(pair, 'recovered');
  const finished = await ipc('financeCall', [pair.september.id, 'dashboard-read', {}]);
  check('repair_attempt_clears_failures_after_manager_resumes', finished.carry_attempt,
    !finished.carry_attempt?.failed?.length);
}

async function main() {
  await verifyCandidate();
  const bound = seedPair('参数绑定九卡', boundDefinition);
  const missingScope = seedPair('缺少范围旧月', (id) => ({
    question: '缺scope旧月固定值验收', bindings: {actual: id},
    sql: "SELECT metric, '2026-08' AS period, CAST(amount AS DECIMAL(38,2)) AS value, currency, unit FROM actual ORDER BY metric",
  }));
  const {_electron} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
  app = await _electron.launch({executablePath, args: [`--user-data-dir=${dirs.profile}`], env, timeout: 60000});
  report.packaged = await app.evaluate(({app}) => ({packaged: app.isPackaged, appPath: app.getAppPath(), userData: app.getPath('userData')}));
  check('real_packaged_electron_uses_isolated_profile', report.packaged,
    report.packaged.packaged && report.packaged.userData === dirs.profile);
  await app.context().route(/^https?:\/\//, (route) => {
    const url = new URL(route.request().url());
    if (/\/api\/session\.(prompt|send)/.test(url.pathname)) {
      report.modelPromptRequests.push(route.request().url());
      return route.abort('blockedbyclient');
    }
    if (['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) return route.continue();
    report.externalRequests.push(route.request().url());
    return route.abort('blockedbyclient');
  });
  page = await app.firstWindow();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForFunction(() => window.foundry?.financeCall && window.foundry?.analysisState, undefined, {timeout: 60000});
  const info = await ipc('appInfo');
  check('real_electron_ipc_uses_isolated_foundry_store', info, info.data_folder === dirs.var);
  await ipc('firstLookDone');
  await ipc('preferencesSet', [{people: [{id: 'qa_manager', name: 'QA 九月经理', role: 'manager', signature: 'QA 九月经理'}], current_person: 'qa_manager'}]);
  await page.reload();
  await until(() => ipc('harnessStatus'), (status) => status?.wiring?.state === 'ready', 'candidate harness ready', 60000);
  await verifyNineCards(bound);
  await verifyMissingScope(missingScope);
  await verifyRecovery(missingScope);
  check('no_external_provider_request_was_used', report.externalRequests, report.externalRequests.length === 0);
  check('no_chat_model_prompt_was_submitted', report.modelPromptRequests, report.modelPromptRequests.length === 0);
  report.status = 'passed';
}

main().catch(async (error) => {
  report.status = 'failed';
  report.error = {message: error.message, stack: error.stack};
  if (page) await screenshot('failure').catch(() => undefined);
  process.exitCode = 1;
}).finally(async () => {
  if (app) await app.close().catch(() => undefined);
  const file = path.join(scratch, 'dashboard-period-receipt.json');
  writeJson(file, report);
  if (out) {
    fs.mkdirSync(out, {recursive: true});
    writeJson(path.join(out, 'dashboard-period-receipt.json'), report);
    fs.cpSync(dirs.screenshots, path.join(out, 'screenshots'), {recursive: true});
    fs.cpSync(dirs.fixtures, path.join(out, 'fixtures'), {recursive: true});
  }
  console.log(JSON.stringify({status: report.status, receipt: file, out, checks: report.checks, error: report.error}, null, 2));
});
