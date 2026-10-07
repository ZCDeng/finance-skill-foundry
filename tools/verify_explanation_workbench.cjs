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
  nativeBoundsCaptures: [],
  sourceReceipt: null,
  requirementsFlow: null,
  controlChecks: [],
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

function screenshotSlug(value) {
  return String(value).normalize('NFKD').replace(/[^\p{Letter}\p{Number}]+/gu, '-').replace(/^-|-$/g, '').slice(0, 80) || 'capture';
}


async function setNativeWindowState({width, height, theme = 'light', zoom = 1}) {
  await page.emulateMedia({colorScheme: theme === 'dark' ? 'dark' : 'light'}).catch(() => undefined);
  await app.evaluate(({BrowserWindow, nativeTheme}, value) => {
    nativeTheme.themeSource = value.theme;
    const candidates = BrowserWindow.getAllWindows()
      .filter((window) => !window.isDestroyed())
      .map((window) => ({window, bounds: window.getContentBounds(), visible: window.isVisible(), url: window.webContents.getURL()}))
      .sort((a, b) => Number(b.visible) - Number(a.visible) || (b.bounds.width * b.bounds.height) - (a.bounds.width * a.bounds.height));
    const selected = candidates.find((candidate) => candidate.visible && candidate.bounds.width >= 800) || candidates[0];
    if (!selected) throw new Error('No BrowserWindow available for native QA');
    selected.window.setContentSize(value.width, value.height);
    selected.window.webContents.setZoomFactor(value.zoom);
  }, {width, height, theme, zoom});
  await until(
    () => page.evaluate(() => ({width: innerWidth, height: innerHeight})).catch(() => null),
    (viewport) => Boolean(viewport?.width && viewport?.height),
    'renderer viewport available after native resize',
    5000,
  );
  await delay(350);
}

async function dismissDshSetupIfVisible() {
  for (const name of [/Configure later/i, /Skip/i, /稍后/, /以后再说/, /跳过/]) {
    const button = page.getByRole('button', {name}).first();
    if (await button.isVisible().catch(() => false)) {
      await button.click().catch(() => undefined);
      await delay(300);
      return name.toString();
    }
  }
  return null;
}

async function captureNativeBounds(name, options) {
  await setNativeWindowState(options);
  const dismissedSetup = await dismissDshSetupIfVisible();
  const renderer = await screenshot(name);
  const native = await app.evaluate(async ({BrowserWindow}) => {
    const windows = BrowserWindow.getAllWindows()
      .filter((window) => !window.isDestroyed())
      .map((window, index) => ({
        index,
        title: window.getTitle(),
        visible: window.isVisible(),
        focused: window.isFocused(),
        content: window.getContentBounds(),
        url: window.webContents.getURL(),
        window,
      }))
      .sort((a, b) => Number(b.visible) - Number(a.visible) || (b.content.width * b.content.height) - (a.content.width * a.content.height));
    const selected = windows.find((candidate) => candidate.visible && candidate.content.width >= 800) || windows[0];
    if (!selected) throw new Error('No BrowserWindow available for native QA');
    const window = selected.window;
    const content = window.getContentBounds();
    const children = window.contentView.children
      .filter((child) => child.webContents)
      .map((child, index) => ({
        index,
        visible: child.getVisible(),
        bounds: child.getBounds(),
        url: child.webContents.getURL(),
      }));
    const visibleChild = window.contentView.children.find((child) => child.webContents && child.getVisible() && child.getBounds().width > 0 && child.getBounds().height > 0);
    return {
      selectedWindow: {index: selected.index, title: selected.title, visible: selected.visible, focused: selected.focused, content: selected.content, url: selected.url},
      windows: windows.map(({window: _window, ...item}) => item),
      content,
      children,
      shellPng: (await window.webContents.capturePage()).toPNG().toString('base64'),
      dshChildPng: visibleChild ? (await visibleChild.webContents.capturePage()).toPNG().toString('base64') : null,
    };
  });
  const shellFile = path.join(screenshotsDir, `${name}-shell-native.png`);
  fs.writeFileSync(shellFile, Buffer.from(native.shellPng, 'base64'));
  report.screenshots.push(shellFile);
  const dshFile = path.join(screenshotsDir, `${name}-dsh-child-native.png`);
  if (native.dshChildPng) {
    fs.writeFileSync(dshFile, Buffer.from(native.dshChildPng, 'base64'));
    report.screenshots.push(dshFile);
  }
  const nativeForReport = {...native, shellPng: `[saved:${shellFile}]`, dshChildPng: native.dshChildPng ? `[saved:${dshFile}]` : null};
  const measurement = await page.evaluate(() => {
    const bodyStyle = getComputedStyle(document.body);
    const rootStyle = getComputedStyle(document.documentElement);
    return {
      viewport: {width: innerWidth, height: innerHeight},
      visualViewport: window.visualViewport ? {width: window.visualViewport.width, height: window.visualViewport.height, scale: window.visualViewport.scale} : null,
      devicePixelRatio,
      prefersDark: matchMedia('(prefers-color-scheme: dark)').matches,
      horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      bodyFont: bodyStyle.fontFamily,
      background: bodyStyle.backgroundColor,
      tokenBackground: rootStyle.getPropertyValue('--fnd-bg').trim(),
    };
  });
  const expectedCssWidth = Math.round(native.content.width / options.zoom);
  const expectedCssHeight = Math.round(native.content.height / options.zoom);
  const capture = {name, options, renderer, shellFile, dshFile: native.dshChildPng ? dshFile : null, dismissedSetup, native: nativeForReport, measurement, expectedCssWidth, expectedCssHeight};
  report.nativeBoundsCaptures.push(capture);
  const inBounds = native.children.every((child) => {
    const b = child.bounds || {};
    return Number.isFinite(b.x) && Number.isFinite(b.y) && Number.isFinite(b.width) && Number.isFinite(b.height)
      && b.x >= 0 && b.y >= 0 && b.x + b.width <= native.content.width + 1 && b.y + b.height <= native.content.height + 1;
  });
  const viewportMatchesNative = Math.abs(measurement.viewport.width - expectedCssWidth) <= 3 && Math.abs(measurement.viewport.height - expectedCssHeight) <= 3;
  const themeMatches = options.theme === 'dark'
    ? measurement.prefersDark && measurement.tokenBackground !== '#ffffff' && measurement.background !== 'rgb(255, 255, 255)'
    : !measurement.prefersDark;
  check(`native_bounds_${name}`, 'installed native shell bounds/theme are captured separately from any DSH child WebContentsView', {
    childCount: native.children.length,
    visibleCount: native.children.filter((child) => child.visible).length,
    shellFile,
    dshFile: native.dshChildPng ? dshFile : null,
    dismissedSetup,
    expectedCssWidth,
    expectedCssHeight,
    measurement,
    selectedWindow: native.selectedWindow,
  }, native.children.length > 0 && inBounds && viewportMatchesNative && themeMatches && !measurement.horizontalOverflow);
  return capture;
}

async function chooseSearchableOption(root, label, query, expectedText = query) {
  await root.getByLabel(label, {exact: true}).click();
  const search = page.getByLabel(`${label}搜索`, {exact: true});
  await search.waitFor({state: 'visible', timeout: 10000});
  await search.fill(query);
  await search.press('Enter');
  await until(
    () => root.getByLabel(label, {exact: true}).textContent().catch(() => ''),
    (text) => text.includes(expectedText),
    `${label} selected ${expectedText}`,
    10000,
  );
}

async function ensureDetailsOpen(locator) {
  await locator.waitFor({state: 'visible', timeout: 20000});
  const open = await locator.evaluate((node) => node.open);
  if (!open) await locator.locator('summary').first().click();
  await until(() => locator.evaluate((node) => node.open), Boolean, 'details opened', 10000);
}


async function comboboxDebug(label, phase) {
  return page.evaluate(({label, phase}) => {
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
    };
    const rectOf = (el) => {
      const rect = el.getBoundingClientRect();
      return {x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height)};
    };
    const search = Array.from(document.querySelectorAll('input')).find((el) => el.getAttribute('aria-label') === `${label}搜索`);
    const activeElement = document.activeElement;
    const activeId = search?.getAttribute('aria-activedescendant') || '';
    const activeOption = activeId ? document.getElementById(activeId) : null;
    const options = Array.from(document.querySelectorAll('[role="option"]')).filter(visible).map((el, index) => ({
      index,
      id: el.id,
      text: (el.textContent || '').replace(/\s+/g, ' ').trim(),
      ariaSelected: el.getAttribute('aria-selected'),
      dataActive: el.getAttribute('data-active'),
      dataDisabled: el.getAttribute('data-disabled'),
      rect: rectOf(el),
    }));
    return {
      phase,
      search: search ? {
        value: search.value,
        ariaLabel: search.getAttribute('aria-label'),
        ariaActiveDescendant: activeId,
        ariaControls: search.getAttribute('aria-controls'),
        rect: rectOf(search),
      } : null,
      activeOption: activeOption ? {
        id: activeOption.id,
        text: (activeOption.textContent || '').replace(/\s+/g, ' ').trim(),
        dataActive: activeOption.getAttribute('data-active'),
        ariaSelected: activeOption.getAttribute('aria-selected'),
        rect: rectOf(activeOption),
      } : null,
      activeElement: activeElement ? {
        tag: activeElement.tagName,
        ariaLabel: activeElement.getAttribute('aria-label'),
        role: activeElement.getAttribute('role'),
        id: activeElement.id,
        text: (activeElement.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120),
      } : null,
      options,
    };
  }, {label, phase});
}


async function pickMultiSelectOptionBySearch(root, label, query, expectedOption) {
  const button = root.getByRole('button', {name: label, exact: true}).first();
  const search = page.getByLabel(`${label}搜索`, {exact: true});
  if (await search.isVisible().catch(() => false)) {
    await search.press('Escape').catch(() => undefined);
    await search.waitFor({state: 'hidden', timeout: 5000}).catch(() => undefined);
  }
  await button.click();
  await search.waitFor({state: 'visible', timeout: 10000});
  await search.fill(query);
  const expected = page.getByRole('option', {name: new RegExp(expectedOption)});
  await expected.waitFor({state: 'visible', timeout: 10000});
  const visibleOptionsDebug = await comboboxDebug(label, `${expectedOption}:options-visible`);
  const popoverScreenshot = await screenshot(`popover-${screenshotSlug(label)}-${screenshotSlug(query)}`);
  const visibleOptions = visibleOptionsDebug.options.map((option) => option.text).filter(Boolean);
  const expectedIndex = visibleOptions.findIndex((text) => text.includes(expectedOption));
  check(`${label}_${expectedOption}_search_options`, 'installed renderer MultiSelect search exposes the requested option before keyboard selection', visibleOptions, expectedIndex >= 0);
  for (let i = 0; i < expectedIndex; i += 1) {
    await search.press('ArrowDown');
  }
  const beforeEnter = await comboboxDebug(label, `${expectedOption}:before-enter`);
  report.controlChecks.push({label, query, expectedOption, expectedIndex, popoverScreenshot, visibleOptionsDebug, beforeEnter});
  await search.press('Enter');
  const afterEnter = await comboboxDebug(label, `${expectedOption}:after-enter`);
  report.controlChecks.push({label, query, expectedOption, expectedIndex, afterEnter, buttonText: await button.textContent().catch(() => '')});
  await until(
    () => button.textContent().catch(() => ''),
    (text) => text.includes(expectedOption),
    `${label} selected ${expectedOption}`,
    10000,
  );
  await search.press('Escape').catch(() => undefined);
  await search.waitFor({state: 'hidden', timeout: 5000}).catch(() => undefined);
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
  const observed = await until(
    async () => {
      const tabbar = page.locator('.analysis-tabbar:visible').last();
      const tab = tabbar.getByRole('tab', {name: /文稿/});
      await tab.waitFor({state: 'visible', timeout: 5000});
      const before = await tab.evaluate((el) => ({
        selected: el.getAttribute('aria-selected'),
        id: el.id,
        text: el.textContent || '',
        rect: (() => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height}; })(),
      })).catch(() => null);
      await tab.scrollIntoViewIfNeeded().catch(() => undefined);
      await tab.click().catch(() => undefined);
      await delay(500);
      let afterTab = page.locator('.analysis-tabbar:visible').last().getByRole('tab', {name: /文稿/});
      let selected = await afterTab.getAttribute('aria-selected').catch(() => null);
      const attempts = [{method: 'pointer-click', selected, activePanelId: await page.locator('[role=tabpanel].analysis-content:visible').last().getAttribute('id').catch(() => null)}];
      if (selected !== 'true') {
        await afterTab.focus().catch(() => undefined);
        await page.keyboard.press('Enter').catch(() => undefined);
        await delay(500);
        afterTab = page.locator('.analysis-tabbar:visible').last().getByRole('tab', {name: /文稿/});
        selected = await afterTab.getAttribute('aria-selected').catch(() => null);
        attempts.push({method: 'keyboard-enter', selected, activePanelId: await page.locator('[role=tabpanel].analysis-content:visible').last().getAttribute('id').catch(() => null)});
      }
      if (selected !== 'true') {
        await afterTab.focus().catch(() => undefined);
        await page.keyboard.press(' ').catch(() => undefined);
        await delay(500);
        afterTab = page.locator('.analysis-tabbar:visible').last().getByRole('tab', {name: /文稿/});
        selected = await afterTab.getAttribute('aria-selected').catch(() => null);
        attempts.push({method: 'keyboard-space', selected, activePanelId: await page.locator('[role=tabpanel].analysis-content:visible').last().getAttribute('id').catch(() => null)});
      }
      const panel = page.locator('#analysis-panel-drafts:visible').last();
      return {
        before,
        attempts,
        selected,
        activePanelId: await page.locator('[role=tabpanel].analysis-content:visible').last().getAttribute('id').catch(() => null),
        visibleDraftPanels: await page.locator('#analysis-panel-drafts:visible').count().catch(() => 0),
        hasArticle: await panel.getByRole('article', {name: '文稿阅读'}).count().catch(() => 0),
        hasQuality: await panel.getByRole('region', {name: '文稿质量检查'}).count().catch(() => 0),
        text: await panel.evaluate((el) => el.textContent || '').catch(() => ''),
        visibleBody: await page.locator('body').innerText().catch(() => ''),
      };
    },
    (value) => value.selected === 'true' && value.visibleDraftPanels > 0 && value.hasArticle > 0 && value.hasQuality > 0,
    'draft tab visible',
    30000,
  );
  report.controlChecks.push({draftTabOpen: {
    selected: observed.selected,
    activePanelId: observed.activePanelId,
    visibleDraftPanels: observed.visibleDraftPanels,
    hasArticle: observed.hasArticle,
    hasQuality: observed.hasQuality,
    textPreview: observed.text.slice(0, 400),
  }});
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
  const invoiceRows = [
    {id: 'AR-001', ledger: 'L1', organization: 'O1', currency: 'CNY', unit: '万元', due_date: '2026-08-15', amount: '80', invoice_status: '争议', customer: '华东客户甲'},
    {id: 'AR-002', ledger: 'L1', organization: 'O1', currency: 'CNY', unit: '万元', due_date: '2026-08-31', amount: '40', invoice_status: '逾期', customer: '华东客户乙'},
    {id: 'AR-003', ledger: 'L1', organization: 'O1', currency: 'CNY', unit: '万元', due_date: '2026-09-25', amount: '30', invoice_status: '正常', customer: '华东客户丙'},
  ];
  const activityRows = [
    {id: 'RCPT-001', invoice_id: 'AR-001', ledger: 'L1', organization: 'O1', currency: 'CNY', unit: '万元', effective_date: '2026-09-20', amount: '20', kind: 'payment'},
  ];
  const actualPath = writeJson(path.join(fixturesDir, 'actual.json'), actualRows);
  const budgetPath = writeJson(path.join(fixturesDir, 'budget.json'), budgetRows);
  const invoicesPath = writeJson(path.join(fixturesDir, 'aging-invoices.json'), invoiceRows);
  const activityPath = writeJson(path.join(fixturesDir, 'aging-activity.json'), activityRows);
  report.fixtures.push({name: 'actual', path: actualPath, rows: actualRows.length, synthetic: true});
  report.fixtures.push({name: 'budget', path: budgetPath, rows: budgetRows.length, synthetic: true});
  report.fixtures.push({name: 'invoices', path: invoicesPath, rows: invoiceRows.length, synthetic: true});
  report.fixtures.push({name: 'activity', path: activityPath, rows: activityRows.length, synthetic: true});

  const actual = cli('dataset-add', ['--path', actualPath, '--name', 'QA 实际发生'], taskId);
  const budget = cli('dataset-add', ['--path', budgetPath, '--name', 'QA 预算'], taskId);
  const invoices = cli('dataset-add', ['--path', invoicesPath, '--name', 'QA 应收发票'], taskId);
  const activity = cli('dataset-add', ['--path', activityPath, '--name', 'QA 核销活动'], taskId);
  const context = cliSpec('finance-context-save', {
    name: 'QA 解释质量口径',
    bindings: {actual: actual.id, budget: budget.id, invoices: invoices.id, activity: activity.id},
    scopes: {
      actual: {ledger: 'L1', organization: 'O1', period: '2026-09', currency: 'CNY', unit: '万元', scenario: 'actual'},
      budget: {ledger: 'L1', organization: 'O1', period: '2026-09', currency: 'CNY', unit: '万元', scenario: 'budget'},
      invoices: {ledger: 'L1', organization: 'O1', currency: 'CNY', unit: '万元'},
      activity: {ledger: 'L1', organization: 'O1', currency: 'CNY', unit: '万元'},
    },
  }, taskId);
  const requirements = cliSpec('analysis-requirements-save', {
    context_id: context.id,
    question: '解释本期利润差异并下钻利润，同时核对来源。',
    scope: {ledger: 'L1', organization: 'O1', period: '2026-09', currency: 'CNY', unit: '万元'},
    bindings: {actual: actual.id, budget: budget.id},
    items: [
      {id: 'profit', metric: 'profit', label: '利润', dimensions: {metric: 'profit'}, requires_drilldown: true},
      {id: 'revenue', metric: 'revenue', label: '收入', dimensions: {metric: 'revenue'}, requires_drilldown: false},
    ],
  }, taskId);
  report.requirementsFlow = {initialId: requirements.id, question: requirements.question, savedBeforeRun: true};
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

  check('seed_prepare_evidence_groups_available', 'packaged CLI prepare-explanation emitted evidence groups for automatic source receipt', {
    evidenceGroups: prepared.evidence_groups?.length,
    automaticTables: prepared.automatic_supporting_tables?.length ?? 0,
  }, Array.isArray(prepared.evidence_groups) && prepared.evidence_groups.length > 0);

  const draft = cliSpec('save-explanation-draft', {
    title: 'QA 利润说明',
    body: `利润超预算 {{fact:${profitFact.id}}}，请在文稿页验证可下钻来源。`,
    run_ids: [run.id],
    fact_ids: [profitFact.id],
    requirements_id: requirements.id,
    review_status: 'unreviewed',
    publication_status: 'draft',
  }, taskId);
  const validation = cliSpec('validate-explanation', {draft_id: draft.id}, taskId);
  report.sourceReceipt = {
    draftId: draft.id,
    requirementsId: draft.requirements_id,
    claimCount: draft.claims?.length ?? 0,
    factCount: draft.fact_ids?.length ?? 0,
    appendixBytes: draft.evidence_appendix?.length ?? 0,
    completion: draft.completion,
  };
  check('seed_draft_quality_passed', 'packaged CLI save-explanation-draft and validate-explanation', {
    draftId: draft.id,
    status: validation.status,
    body: draft.body,
    sourceReceipt: report.sourceReceipt,
  }, validation.status === 'pass' && draft.body.includes('5 万元') && draft.body.includes('## 计算依据')
    && draft.requirements_id === requirements.id && (draft.claims?.length ?? 0) > 0 && draft.completion?.status === 'complete');

  const revisedRequirements = cliSpec('analysis-requirements-save', {
    parent_id: requirements.id,
    context_id: context.id,
    question: '经理改为同时解释利润差异与应收争议状态。',
    scope: {ledger: 'L1', organization: 'O1', period: '2026-09', currency: 'CNY', unit: '万元'},
    bindings: {actual: actual.id, budget: budget.id, invoices: invoices.id},
    change_reason: '经理新增应收争议状态复核，收入项仍保留用于利润解释闭合。',
    items: [
      {id: 'profit', metric: 'profit', label: '利润', dimensions: {metric: 'profit'}, requires_drilldown: true},
      {id: 'revenue', metric: 'revenue', label: '收入', dimensions: {metric: 'revenue'}, requires_drilldown: false},
      {id: 'open_ar', metric: 'open_amount', label: '争议应收余额', dimensions: {status: 'disputed'}, requires_drilldown: true},
    ],
  }, taskId);
  report.requirementsFlow.revisedId = revisedRequirements.id;
  report.requirementsFlow.draftRequirementsId = draft.requirements_id;
  report.requirementsFlow.oldDraftShouldBeStale = revisedRequirements.id !== draft.requirements_id;

  return {taskTitle, taskId, actual, budget, invoices, activity, context, requirements, revisedRequirements, run, prepared, profitFact, draft};
}


async function verifyWorkbenchControlsAndScenario(seed) {
  await page.getByRole('tab', {name: /分析结果/}).click();
  const setup = page.locator('details.analysis-finance-setup').first();
  await ensureDetailsOpen(setup);
  await chooseSearchableOption(setup, '预算资料（可选）', '预算', 'QA 预算');
  const organization = setup.getByLabel('组织', {exact: true}).first();
  await organization.fill('华东运营中心');
  await setup.getByLabel('期间', {exact: true}).first().fill('2026-09');
  await setup.getByRole('button', {name: '对比期间打开年月选择', exact: true}).click();
  const periodDialog = page.getByRole('dialog', {name: '对比期间年月选择'});
  await periodDialog.waitFor({state: 'visible', timeout: 10000});
  await screenshot('popover-period-comparison');
  await periodDialog.press('ArrowLeft');
  await periodDialog.press('Enter');
  const compareValue = await setup.getByLabel('对比期间', {exact: true}).inputValue();
  check('period_picker_keyboard_comparison_period', 'installed renderer AccountingPeriodInput supports keyboard month selection for comparison scope', compareValue, /^\d{4}-\d{2}$/.test(compareValue));

  const scenario = setup.locator('details.analysis-scenario-panel').first();
  await ensureDetailsOpen(scenario);
  await chooseSearchableOption(scenario, '应收/发票资料', 'invoices', 'invoices');
  await chooseSearchableOption(scenario, '核销活动（可选）', 'activity', 'activity');
  const agingDate = scenario.getByLabel('账龄日期', {exact: true});
  await agingDate.fill('2026-09-30');
  await agingDate.press('Enter');
  const committedAgingDate = await agingDate.inputValue();
  await agingDate.press('ArrowDown');
  const dateDialog = page.getByRole('dialog', {name: '账龄日期日期选择'});
  await dateDialog.waitFor({state: 'visible', timeout: 10000});
  await screenshot('popover-date-aging-date');
  await dateDialog.press('Escape');
  check('date_picker_keyboard_aging_date', 'installed renderer DateInput accepts typed aging date and opens/closes picker from keyboard', committedAgingDate, committedAgingDate === '2026-09-30');

  await pickMultiSelectOptionBySearch(scenario, '应收状态筛选', '争议', '争议应收');
  await pickMultiSelectOptionBySearch(scenario, '应收状态筛选', '逾期', '逾期应收');
  const statusLabel = await scenario.getByRole('button', {name: '应收状态筛选', exact: true}).textContent();
  check('status_search_multiselect_keyboard', 'installed renderer searchable multi-select accepts Chinese status search and keyboard options', statusLabel, statusLabel.includes('争议应收') && statusLabel.includes('逾期应收'));

  await scenario.getByRole('button', {name: /运行基准情景/}).click();
  let agingRun;
  const isAgingScenarioRun = (run) => {
    const result = run?.result || {};
    const columnNames = (result.columns || []).map((column) => typeof column === 'string' ? column : column?.name);
    return run?.engine === 'finance'
      && run?.execution_status === 'succeeded'
      && result.domain === 'foundry.finance.scenario_result.v1'
      && columnNames.includes('result_key')
      && columnNames.includes('as_of')
      && columnNames.includes('bucket')
      && columnNames.includes('open_amount')
      && Array.isArray(result.detail_rows)
      && Array.isArray(result.excluded_detail_rows)
      && Boolean(result.evidence?.status_filter);
  };
  await until(
    () => {
      const state = cli('analysis-state', [], seed.taskId);
      agingRun = [...(state.runs || [])].reverse().find((run) => isAgingScenarioRun(run) || (run.engine === 'finance' && run.error));
      const result = agingRun?.result || {};
      const columnNames = (result.columns || []).map((column) => typeof column === 'string' ? column : column?.name);
      return {
        runId: agingRun?.id,
        domain: result.domain,
        columns: columnNames,
        executionStatus: agingRun?.execution_status,
        detailCount: result.detail_rows?.length,
        excludedCount: result.excluded_detail_rows?.length,
        statusFilter: result.evidence?.status_filter,
        error: agingRun?.error,
        ready: isAgingScenarioRun(agingRun),
      };
    },
    (observed) => observed.ready === true,
    'aging scenario run persisted',
    30000,
  );
  check('ui_aging_status_filter_result_sections', 'real UI saved and ran native aging status_filter, then packaged CLI reread drilldown-ready sections', {
    runId: agingRun?.id,
    rowCount: agingRun?.result?.rows?.length,
    detailCount: agingRun?.result?.detail_rows?.length,
    excludedCount: agingRun?.result?.excluded_detail_rows?.length,
    statusFilter: agingRun?.result?.evidence?.status_filter,
  }, Boolean(agingRun?.id) && (agingRun.result.detail_rows?.length ?? 0) >= 2 && (agingRun.result.excluded_detail_rows?.length ?? 0) >= 1
    && agingRun.result.evidence?.status_filter?.include?.includes('disputed') && agingRun.result.evidence.status_filter.include.includes('overdue'));
  report.controlChecks.push({
    comparePeriod: compareValue,
    agingDate: await agingDate.inputValue(),
    statusLabel,
    agingRunId: agingRun?.id,
  });
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
  await selectTask(seed.taskTitle);
  const opened = await invokeBridge('harnessOpen', ['analysis', seed.taskId]);
  check('open_seeded_task_without_prompt_submission', 'installed app main/CLI/native IPC', opened, opened.ok && Boolean(opened.value?.sessionId));
  await captureNativeBounds('native-light-1500', {width: 1500, height: 920, theme: 'light', zoom: 1});
  await captureNativeBounds('native-dark-1280', {width: 1280, height: 820, theme: 'dark', zoom: 1});
  await captureNativeBounds('native-narrow-1080', {width: 1080, height: 760, theme: 'light', zoom: 1});
  await captureNativeBounds('native-zoom-125', {width: 1280, height: 820, theme: 'light', zoom: 1.25});
  await setNativeWindowState({width: 1500, height: 920, theme: 'light', zoom: 1});
  await verifyWorkbenchControlsAndScenario(seed);
  await openDraftsTab();
  const draftPanel = page.locator('#analysis-panel-drafts:visible').last();
  await draftPanel.getByRole('article', {name: '文稿阅读'}).waitFor({state: 'visible', timeout: 30000});
  await draftPanel.getByRole('heading', {name: 'QA 利润说明'}).waitFor({state: 'visible', timeout: 30000});

  const quality = draftPanel.getByRole('region', {name: '文稿质量检查'});
  await quality.waitFor({state: 'attached', timeout: 30000});
  await until(
    () => quality.evaluate((el) => el.textContent || ''),
    (text) => text.includes('已引用') && text.includes('数字与口径') && text.includes('问题覆盖') && text.includes('来源追溯'),
    'quality facts loaded',
    30000,
  );
  const qualityText = await quality.textContent();
  const checkStatuses = await quality.getByLabel('分项核对状态').evaluate((node) => Array.from(node.querySelectorAll('div')).map((row) => row.textContent || ''));
  const referencedFactsFromHeader = Number((qualityText.match(/已引用\s*(\d+)\s*条事实/) || [])[1]);
  const availableFactsFromHeader = Number((qualityText.match(/可引用事实\s*·\s*(\d+)\s*条/) || [])[1]);
  const referencedFactsFromDetails = Number((qualityText.match(/"referenced_fact_count":\s*(\d+)/) || [])[1]);
  const availableFactsFromDetails = Number((qualityText.match(/"available_fact_count":\s*(\d+)/) || [])[1]);
  const expectedReferencedFacts = report.sourceReceipt?.factCount ?? 0;
  const qualityCounts = {referencedFactsFromHeader, availableFactsFromHeader, referencedFactsFromDetails, availableFactsFromDetails, expectedReferencedFacts};
  check('quality_panel_shows_stale_coverage_and_provenance_statuses', 'real renderer exposes number pass, coverage/provenance gaps, stale requirements, and fact counts consistent with source receipt', {qualityText, checkStatuses, qualityCounts},
    qualityText.includes('需要复核')
    && expectedReferencedFacts > 0
    && referencedFactsFromHeader === expectedReferencedFacts
    && referencedFactsFromDetails === expectedReferencedFacts
    && availableFactsFromHeader >= referencedFactsFromHeader
    && availableFactsFromDetails >= referencedFactsFromDetails
    && checkStatuses.some((text) => text.includes('数字与口径') && text.includes('已核对'))
    && checkStatuses.some((text) => text.includes('问题覆盖') && text.includes('仍有缺口'))
    && checkStatuses.some((text) => text.includes('来源追溯') && text.includes('仍有缺口'))
    && qualityText.includes('本次分析范围已更新')
    && qualityText.includes('尚未提供“争议应收余额”的计算依据')
    && qualityText.includes('尚未完成“争议应收余额”的指定来源核查'));
  const staleText = await draftPanel.getByRole('region', {name: '本次分析要求'}).textContent();
  check('old_draft_stale_after_requirements_revision', 'requirements changed after this draft, so the opened old draft must be marked stale', {
    staleText,
    draftRequirementsId: seed.draft.requirements_id,
    revisedRequirementsId: seed.revisedRequirements.id,
  }, staleText.includes('范围已变') && staleText.includes(seed.draft.requirements_id.slice(0, 12)) && staleText.includes(seed.revisedRequirements.id.slice(0, 12)));

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
  const saveButtons = await page.getByRole('button', {name: /保存文稿新版|归档此版/}).evaluateAll((buttons) => buttons.map((button) => ({text: button.textContent, disabled: button.disabled})));
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
    datasetIds: {actual: seed.actual.id, budget: seed.budget.id, invoices: seed.invoices.id, activity: seed.activity.id},
    contextId: seed.context.id,
    requirementsId: seed.requirements.id,
    revisedRequirementsId: seed.revisedRequirements.id,
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
