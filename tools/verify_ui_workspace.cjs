// Packaged Electron, isolated synthetic finance data, no model requests.
// UI_APP_BUNDLE names another packaged .app (default app/release); the first-screen check (R12) is described in
// docs/verification/2026-09-27-first-screen-check.md and seeds through tools/fixtures/seed_first_screen_runs.py.
const { _electron } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const assert = require('node:assert/strict');
(async () => {
  // UI_CHECKS picks the phases: first-screen (R12) and workspace (the flow below it); both by default. A run that
  // leaves one out records status 'partial' and names it in skippedPhases; only a run of both can record 'passed'.
  const root = path.resolve(__dirname, '..');
  const output = path.resolve(process.env.UI_EVIDENCE_DIR || path.join(root, 'build/ui-workspace-review'));
  fs.mkdirSync(output, { recursive: true });
  // No earlier verdict survives this run: until this run writes its own, there is no verification.json at all.
  fs.rmSync(path.join(output, 'verification.json'), { force: true });
  const allPhases = ['first-screen', 'workspace'];
  const phases = (process.env.UI_CHECKS || allPhases.join(',')).split(',').map(phase => phase.trim()).filter(Boolean);
  const unknownPhases = phases.filter(phase => !allPhases.includes(phase));
  if (unknownPhases.length || !phases.length) throw new Error(`UI_CHECKS must name ${allPhases.join(' and/or ')}; got ${JSON.stringify(process.env.UI_CHECKS)}`);
  const skippedPhases = allPhases.filter(phase => !phases.includes(phase));
  const qa = fs.mkdtempSync('/tmp/finance-ui-workspace-');
  const bundle = path.resolve(process.env.UI_APP_BUNDLE || path.join(root, 'app/release/mac-arm64/FA Foundry.app'));
  const bin = path.join(bundle, 'Contents/Resources/foundry/foundry');
  const cli = (command, args = [], task) => { const raw = execFileSync(bin, ['--var', qa + '/var', ...(task ? ['--task', task] : []), command, ...args], { encoding: 'utf8' }).trim(); return command === 'task-new' ? { id: raw } : JSON.parse(raw); };
  // First-screen fixtures, seeded before the tasks below so the workspace still opens on the same task.
  const firstScreen = JSON.parse(execFileSync(path.join(root, '.venv/bin/python'), [path.join(__dirname, 'fixtures/seed_first_screen_runs.py'),
    '--bin', bin, '--var', qa + '/var', '--work', qa + '/fixtures'], { encoding: 'utf8' }));
  // The raw names each seeded result carries: its column names, its row fields and the identifier-like values in them.
  const rawNames = ({ task: id, run: runId }) => {
    const run = cli('analysis-state', [], id).runs.find(row => row.id === runId);
    const names = new Set(run.result.columns.map(column => column.name));
    for (const row of run.result.rows) for (const [key, value] of Object.entries(row)) { names.add(key); if (typeof value === 'string') names.add(value); }
    return [...names].filter(name => /^[A-Za-z][A-Za-z0-9_]*$/.test(name) && /[a-z]/.test(name));
  };
  const prior = cli('task-new', ['--title', '集团回款跟进', '--period', '2026-08']);
  const task = cli('task-new', ['--title', '华东八月经营分析', '--period', '2026-08']);
  const file = qa + '/华东经营数据.csv';
  fs.writeFileSync(file, '区域,收入,成本,费用\n华东,1280.00,820.00,190.00\n华南,960.00,650.00,160.00\n华北,830.00,590.00,155.00\n');
  const dataset = cli('dataset-add', ['--path', file, '--name', '八月经营数据', '--meta', JSON.stringify({
    period: '2026-08', organization: '华东', unit: '万元', currency: 'CNY', scenario: 'actual', ledger: '经营总账',
    scope_hints: { period: '2026-08', organization: '华东', unit: '万元', currency: 'CNY', scenario: 'actual', ledger: '经营总账', granularity: '区域' },
  })], task.id);
  const spec = { question: '总部费用分摊后的区域经营利润', bindings: { actual: dataset.id },
    sql: 'SELECT 区域, 收入, 成本, 费用, 收入-成本-费用-CAST($overhead AS DECIMAL(38,2)) AS 经营利润 FROM actual',
    parameters: { overhead: '20.00' }, parameter_metadata: [{ key: 'overhead', label: '总部费用分摊', type: 'decimal', unit: '万元', role: 'business', constraints: { min: '0', max: '100' } }],
    assumptions: [{ name: '分摊口径', value: '各区域采用相同费用分摊额' }], metrics: [{ name: '经营利润', expression: '收入－成本－费用－总部费用分摊' }] };
  const first = cli('analysis-save', ['--spec', JSON.stringify(spec)], task.id);
  const run = cli('analysis-run', ['--analysis', first.id], task.id);
  cli('analysis-draft', ['--spec', JSON.stringify({ title: '八月经营分析备忘', body: '## 经营表现\n华东经营利润为 **250 万元**，高于华南和华北。\n\n## 口径与判断\n本次各区域分摊总部费用 20 万元。费用分摊只是本次测算口径，尚需结合总部实际费用归属判断。\n\n- 继续核对区域费用明细。\n- 将预算与实际数据按同一口径比较。', run_ids: [run.id] })], task.id);
  const app = await _electron.launch({ executablePath: path.join(bundle, 'Contents/MacOS/FA Foundry'), args: ['--user-data-dir=' + qa + '/profile'],
    env: { ...process.env, FOUNDRY_VAR: qa + '/var', FOUNDRY_BIN: undefined, FOUNDRY_DSH_INSTALL: undefined, FOUNDRY_FORMULATOR_BIN: undefined }, timeout: 45000 });
  const checks = []; const measures = []; const firstScreenMeasures = [];
  // Every run rewrites verification.json, so a failed or partial run never leaves an earlier 'passed' in place.
  const writeEvidence = (fields) => {
    const evidence = { status: skippedPhases.length ? 'partial' : 'passed', skippedPhases, qa, output, synthetic: true, providerCalls: 0, phases,
      notRun: skippedPhases.map(phase => `${phase}: UI_CHECKS leaves it out`), ...fields, checks, measures, firstScreen: firstScreenMeasures,
      appAsarSha256: createHash('sha256').update(fs.readFileSync(bundle + '/Contents/Resources/app.asar')).digest('hex') };
    fs.writeFileSync(output + '/verification.json', JSON.stringify(evidence, null, 2)); return evidence;
  };
  try {
    const page = await app.firstWindow(); await page.waitForLoadState('domcontentloaded');
    // Since 0.11.0 the app opens on 总览; the workspace lives on the 工作区 tab.
    const openWorkspace = async () => {
      const tab = page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '工作区', exact: true });
      await tab.waitFor();
      if (await tab.getAttribute('aria-current') !== 'page') await tab.click();
      await page.locator('.workspace-header').waitFor();
    };
    await openWorkspace();
    const expand = page.getByRole('button', { name: '展开任务列表' });
    if (await expand.isVisible()) await expand.click();
    await page.locator('.workspace-task').filter({ hasText: '华东八月经营分析' }).click();
    console.log('Selected finance fixture');
    await page.getByRole('table', { name: '业务结果' }).waitFor({ timeout: 30000 });
    await page.waitForFunction(() => document.fonts.check('500 14px "Noto Sans SC"'));
    const capture = async (name, width, height, dark = false) => {
      console.log('Capture', name);
      await app.evaluate(({ BrowserWindow, nativeTheme }, value) => { nativeTheme.themeSource = value.dark ? 'dark' : 'light'; BrowserWindow.getAllWindows()[0].setContentSize(value.width, value.height); }, { width, height, dark });
      for (const target of app.context().pages()) await target.emulateMedia({ colorScheme: null });
      if (!name.startsWith('onboarding')) await app.evaluate(async ({ BrowserWindow }) => {
        const view = BrowserWindow.getAllWindows()[0].contentView.children.find(child => child.webContents && /^http:\/\/127\.0\.0\.1/.test(child.webContents.getURL()));
        if (view?.getVisible()) await view.webContents.executeJavaScript(`Array.from(document.querySelectorAll('button')).find(button => ['Configure later', '稍后配置', '稍后设置'].includes(button.textContent.trim()))?.click()`);
      });
      await page.waitForTimeout(400); await page.evaluate(() => document.fonts.ready);
      const image = await app.evaluate(async ({ BrowserWindow }) => (await BrowserWindow.getAllWindows()[0].capturePage()).toPNG().toString('base64'));
      fs.writeFileSync(output + '/' + name + '.png', Buffer.from(image, 'base64'));
      const native = await app.evaluate(async ({ webContents, BrowserWindow }) => {
        const view = BrowserWindow.getAllWindows()[0].contentView.children.find(child => child.webContents && /^http:\/\/127\.0\.0\.1/.test(child.webContents.getURL()));
        if (!view || !view.getVisible() || view.getBounds().width < 1) return null;
        return { bounds: view.getBounds(), png: (await view.webContents.capturePage()).toPNG().toString('base64') };
      });
      if (native) fs.writeFileSync(output + '/' + name + '-native.png', Buffer.from(native.png, 'base64'));
      try {
        const mediaSource = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getMediaSourceId());
        const id = mediaSource.split(':')[1];
        execFileSync('/usr/sbin/screencapture', ['-x', '-o', '-l', id, output + '/' + name + '-window.png'], { stdio: 'pipe', timeout: 5000 });
      } catch (error) { console.log('Full native-layer window capture unavailable:', error.message.slice(0,150)); }
      const measurement = await page.evaluate(() => ({ viewport: [innerWidth, innerHeight], font: getComputedStyle(document.body).fontFamily,
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth, background: getComputedStyle(document.body).backgroundColor,
        boxes: Object.fromEntries(['.fnd-head', '.workspace-header', '.workspace-native', '.workspace-results', '.analysis-result', '.analysis-table', '.report-reading'].map(selector => {
          const node = document.querySelector(selector), rect = node?.getBoundingClientRect();
          return [selector, rect && node.checkVisibility() ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null];
        })) }));
      // A fold's chevron hangs 24px to the left of its words; inside a bordered card or a table cell it must stay
      // inside (.fnd-fold-inset). Each visible chevron is held to the first framed box around its fold.
      measurement.foldsAcrossEdge = await page.evaluate(() => [...document.querySelectorAll('.fnd-disclosure-summary__icon')].filter(icon => icon.checkVisibility()).flatMap(icon => {
        const summary = icon.closest('summary'), mark = icon.getBoundingClientRect();
        for (let node = summary.parentElement; node && node !== document.body; node = node.parentElement) {
          const style = getComputedStyle(node), edge = parseFloat(style.borderLeftWidth) || 0;
          if (!node.matches('td, th') && !(edge > 0 && style.borderLeftStyle !== 'none')) continue;
          return mark.left < node.getBoundingClientRect().left + edge ? [summary.textContent.trim().slice(0, 40)] : [];
        }
        return [];
      }));
      measures.push({ name, nativeBounds: native?.bounds, ...measurement }); assert.equal(measurement.horizontalOverflow, false, name + ' horizontal overflow');
      assert.deepEqual(measurement.foldsAcrossEdge, [], name + ' fold chevrons stay inside their card or cell');
    };
    await page.waitForFunction(async () => { const result = await window.foundry.harnessStatus(); return result.ok && result.value.wiring.state === 'ready'; }, undefined, { timeout: 45000 });
    await page.waitForFunction(() => !document.querySelector('.workspace-connection'));
    await page.waitForTimeout(300);
    await capture('onboarding-1280', 1280, 800);
    await app.evaluate(async ({ webContents }) => {
      const native = webContents.getAllWebContents().find(target => /^http:\/\/127\.0\.0\.1/.test(target.getURL()));
      if (native) await native.executeJavaScript(`Array.from(document.querySelectorAll('button')).find(button => ['Configure later', '稍后配置', '稍后设置'].includes(button.textContent.trim()))?.click()`);
    });
    await page.waitForTimeout(300);
    const openTask = async (title) => {
      const expandTasks = page.getByRole('button', { name: '展开任务列表' });
      if (await expandTasks.isVisible()) await expandTasks.click();
      await page.locator('.workspace-task').filter({ hasText: title }).click();
    };
    // Folds animate open: click the summary, then wait until the fold's first content is on screen before reading it.
    const openFold = async (details) => {
      await details.locator(':scope > summary').click();
      await details.locator(':scope > :not(summary)').first().waitFor({ state: 'visible' });
    };
    const fieldValue = async (label, rootLocator = page) => {
      const control = rootLocator.getByLabel(label, { exact: true });
      // A disclosure such as 更多范围 animates open; read the control once it is on screen, not mid-expansion.
      await control.waitFor({ state: 'visible' });
      const tag = await control.evaluate(node => node.tagName.toLowerCase());
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return control.inputValue();
      return control.locator('span').first().innerText();
    };
    const scopeDisplay = (label, value) => ({ 单位: { 万元: '万元 · 管理报表常用' }, 币种: { 人民币: '人民币 · CNY' }, 情景: { 实际: '实际 · 账面发生数' } })[label]?.[value] ?? value;
    const assertScopeFields = async (prefix, expected) => {
      for (const [label, value] of Object.entries(expected)) assert.equal(await fieldValue(`${prefix}${label}`), scopeDisplay(label, value), `${prefix}${label} shows ${value}`);
    };
    /** 范围与计算 reads the task's scope as one line; it is changed on 范围. */
    const assertScopeLine = async (rootLocator, parts) => {
      const line = (await rootLocator.getByRole('group', { name: '计算用的范围' }).innerText()).replace(/\s+/g, ' ');
      for (const part of parts) assert.ok(line.includes(part), `the scope line reads ${part}: ${line}`);
    };
    const chooseOption = async (label, option, rootLocator = page) => {
      await rootLocator.getByLabel(label, { exact: true }).click();
      const escaped = option.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      await page.getByRole('option', { name: new RegExp(`^${escaped}(\\s|$)`) }).click();
    };
    const reloadWorkspace = async () => {
      await page.reload();
      await page.waitForLoadState('domcontentloaded');
      await openWorkspace();
      await page.waitForFunction(async () => { const result = await window.foundry.harnessStatus(); return result.ok && result.value.wiring.state === 'ready'; }, undefined, { timeout: 45000 });
      await page.waitForFunction(() => !document.querySelector('.workspace-connection'));
    };
    // R12 first screen: each seeded result, opened at 1280 × 800, shows its answer without scrolling, above the
    // finance settings, and its visible text holds no ids, scenario codes or raw column names.
    const measureFirstScreen = (forbidden) => page.evaluate((forbidden) => {
      const pane = document.querySelector('#analysis-panel-results'), scroller = document.querySelector('.workspace-results');
      const box = node => { if (!node?.checkVisibility()) return null; const rect = node.getBoundingClientRect(); return { x: rect.x, y: rect.y, width: rect.width, height: rect.height }; };
      // Text a reader sees: rendered, outside closed <details> (their summary stays), not a closed select's other options.
      const folded = text => { for (let child = text, node = text.parentElement; node; child = node, node = node.parentElement) {
        if (node.tagName === 'DETAILS' && !node.open && child.nodeName !== 'SUMMARY') return true; if (node === pane) return false; } return false; };
      const walker = document.createTreeWalker(pane, NodeFilter.SHOW_TEXT), seen = [];
      for (let text = walker.nextNode(); text; text = walker.nextNode()) {
        const element = text.parentElement;
        if (!text.data.trim() || element.closest('option, script, style') || folded(text) || !element.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
        seen.push({ text: text.data, where: element.className || element.tagName });
      }
      for (const select of pane.querySelectorAll('select')) if (select.checkVisibility() && !folded(select)) seen.push({ text: select.selectedOptions[0]?.text ?? '', where: 'select' });
      const patterns = [['12-character hex id', /(?<![0-9A-Za-z])[0-9A-Fa-f]{12,}(?![0-9A-Za-z])/g], ['snake_case code', /(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?![A-Za-z0-9_])/g],
        ...forbidden.map(name => ['raw column or value', new RegExp(`(?<![A-Za-z0-9_])${name}(?![A-Za-z0-9_])`, 'g')])];
      const hits = seen.flatMap(({ text, where }) => patterns.flatMap(([kind, pattern]) => [...text.matchAll(pattern)].map(match => ({ kind, match: match[0], text: text.trim().slice(0, 80), where }))));
      const frame = scroller.getBoundingClientRect();
      return { viewport: [innerWidth, innerHeight], visibleTop: Math.max(0, frame.top), visibleBottom: Math.min(innerHeight, frame.bottom), scrollTop: scroller.scrollTop, pageScrollTop: document.scrollingElement.scrollTop,
        conclusion: box(pane.querySelector('.analysis-result .analysis-headline')), card: box(pane.querySelector('.analysis-result .analysis-kpi-card')), settings: box(pane.querySelector('.analysis-finance-setup-body')),
        cardNotes: [...pane.querySelectorAll('.analysis-kpi-card')].map(card => ({ notes: card.querySelector('.analysis-kpi-notes')?.textContent ?? '', inferred: card.textContent.includes('推断') })), hits };
    }, forbidden);
    // 设置 › 显示技术信息 is off by default: ids, digests and raw results stay off the page. The checks of exact ids
    // below turn it on once, from the 设置 page that ⌘, opens, and leave it on.
    let technicalShown = false;
    const showTechnical = async () => {
      if (technicalShown) return;
      await page.keyboard.press(process.platform === 'darwin' ? 'Meta+Comma' : 'Control+Comma');
      const toggle = page.getByRole('switch', { name: '显示技术信息' });
      await toggle.waitFor();
      assert.equal(await page.getByRole('button', { name: '设置', exact: true }).getAttribute('aria-current'), 'page', '⌘, opens 设置 and marks its gear');
      assert.equal(await toggle.getAttribute('aria-checked'), 'false', '显示技术信息 starts off');
      await capture('app-settings-light-1280', 1280, 800); await capture('app-settings-dark-1280', 1280, 800, true);
      await toggle.click();
      await page.waitForFunction(() => document.querySelector('[role="switch"][aria-checked="true"]') !== null);
      technicalShown = true;
      await openWorkspace();
      checks.push('⌘, opens 设置 with 显示技术信息 off; turning it on there brings the technical folds back');
    };
    if (phases.includes('first-screen')) for (const [kind, seeded] of Object.entries(firstScreen)) {
      await app.evaluate(({ BrowserWindow, nativeTheme }) => { nativeTheme.themeSource = 'light'; BrowserWindow.getAllWindows()[0].setContentSize(1280, 800); });
      await openTask(seeded.title);
      const resultsTab = page.getByRole('tab', { name: /财务分析/ });
      if (await resultsTab.getAttribute('aria-selected') !== 'true') await resultsTab.click();
      // The result carries its run id as data-run: wait for this task's run, not the previous task's cards.
      await page.locator(`.analysis-result[data-run="${seeded.run}"]`).waitFor({ timeout: 30000 });
      await page.locator(kind === 'finance' ? '.analysis-result .analysis-headline' : '.analysis-result .analysis-kpi-card').first().waitFor({ timeout: 30000 });
      const forbidden = rawNames(seeded);
      for (const dark of [false, true]) {
        const name = `first-screen-${kind}-${dark ? 'dark' : 'light'}-1280`;
        await capture(name, 1280, 800, dark);
        const seen = await measureFirstScreen(forbidden); firstScreenMeasures.push({ name, kind, task: seeded.task, run: seeded.run, forbidden, ...seen });
        assert.deepEqual(seen.viewport, [1280, 800], name + ' viewport');
        assert.equal(seen.scrollTop + seen.pageScrollTop, 0, name + ' opens without scrolling');
        // The answer the manager reads first: the conclusion bar (finance), the first sentence and card (declared), the first card (legacy).
        const targets = { finance: { conclusion: seen.conclusion }, declared: { conclusion: seen.conclusion, card: seen.card }, legacy: { card: seen.card } }[kind];
        for (const [part, target] of Object.entries(targets)) {
          assert.ok(target, `${name} shows its ${part}`);
          assert.ok(target.y >= seen.visibleTop && target.y < seen.visibleBottom, `${name} ${part} top ${target.y} is inside the first screen (${seen.visibleTop}–${seen.visibleBottom})`);
          if (seen.settings) assert.ok(target.y < seen.settings.y, `${name} ${part} top ${target.y} stands above the finance settings at ${seen.settings.y}`);
        }
        assert.deepEqual(seen.hits, [], name + ' visible text holds no ids, scenario codes or raw column names');
        if (kind !== 'finance') assert.ok(seen.cardNotes.length > 0, name + ' shows key-figure cards');
        // Since 5f65c82 the 推断 note sits in the card meta without its own .analysis-kpi-notes span.
        if (kind === 'legacy') assert.ok(seen.cardNotes.every(card => card.inferred), name + ' every card says 推断');
        if (kind === 'declared') assert.ok(seen.cardNotes.every(card => !card.inferred), name + ' no card says 推断');
      }
      checks.push(`first screen at 1280 × 800, light and dark: ${seeded.title} shows its ${kind === 'finance' ? 'conclusion bar' : 'key figures'} unscrolled, above any settings, with no technical names${kind === 'legacy' ? ', cards marked 推断' : kind === 'declared' ? ', no card marked 推断' : ''}`);
      if (kind === 'finance') {
        assert.equal(await page.locator('.analysis-finance-variance > details.analysis-technical').count(), 0, 'raw technical information stays off the page until 设置 turns it on');
        await showTechnical();
        await page.locator(`.analysis-result[data-run="${seeded.run}"]`).waitFor({ timeout: 30000 });
        const raw = page.locator('.analysis-finance-variance > details.analysis-technical');
        assert.equal(await raw.count(), 1, 'variance has one raw technical information block');
        assert.equal(await raw.getAttribute('open'), null, 'raw information starts closed');
        assert.equal(await raw.getByRole('table', { name: '原始计算结果' }).isVisible(), false, 'raw table is hidden');
        await raw.locator('summary').click();
        assert.equal(await raw.locator('details').count(), 0, 'raw results and diagnostics have no nested disclosure');
        await raw.getByRole('table', { name: '原始计算结果' }).waitFor();
        const savedRun = cli('analysis-state', [], seeded.task).runs.find(row => row.id === seeded.run);
        const exactActual = savedRun.result.rows[0].actual;
        assert.equal(typeof exactActual, 'string', 'finance amount remains a Decimal string');
        // Since 76b3552 result figures are written in accounting form (grouped thousands); the digits stay unrounded.
        assert.ok((await raw.innerText()).replace(/,/g, '').includes(exactActual), 'raw table retains the exact saved decimal');
        await capture('variance-technical-1280', 1280, 800);
        await raw.locator('summary').click();
        checks.push('variance raw results and diagnostics share one default-closed TechnicalInfo; expansion keeps exact Decimal values');
        await page.getByRole('button', { name: '调整范围', exact: true }).click();
        const financeSettings = page.getByRole('region', { name: /^(范围与计算|计算定义与参数)$/ });
        await financeSettings.waitFor();
        assert.equal(await page.getByRole('region', { name: /^(范围与计算|计算定义与参数)$/ }).count(), 1, 'one 范围与计算 fold');
        await assertScopeLine(financeSettings, ['期间 2026 年 8 月', '组织 华东公司', '单位 万元']);
        await financeSettings.getByRole('region', { name: '计算定义', exact: true }).waitFor();
        await capture('finance-settings-light-1280', 1280, 800);
        await capture('finance-settings-dark-1080', 1080, 800, true);
        assert.equal(await financeSettings.getByLabel('组织', { exact: true }).count(), 0, 'the scope is changed on 范围 only');
        await page.keyboard.press('Escape');
        assert.equal(await financeSettings.isVisible(), false, 'Escape closes settings');
        assert.equal(await page.getByRole('button', { name: '调整范围', exact: true }).evaluate(node => node === document.activeElement), true, 'Escape returns focus to 调整范围');
        await page.locator('details.analysis-finance-setup > summary').first().click();
        await financeSettings.waitFor();
        await assertScopeLine(financeSettings, ['期间 2026 年 8 月', '组织 华东公司']);
        await page.keyboard.press('Escape');
        checks.push('调整范围 opens one drawer that reads the selected calculation scope beside its definition; the scope has no fields there; Escape restores trigger focus');
      }
    }
    if (!phases.includes('workspace')) { console.log(JSON.stringify(writeEvidence({}))); return; }
    await showTechnical();
    await openTask('华东八月经营分析');
    await page.getByRole('table', { name: '业务结果' }).waitFor({ timeout: 30000 });
    await page.getByRole('tab', { name: /范围/ }).click();
    await page.getByRole('region', { name: '分析范围' }).waitFor();
    await page.getByRole('region', { name: '分析范围' }).scrollIntoViewIfNeeded();
    await capture('scope-candidates-1280', 1280, 800);
    for (const [label, value] of Object.entries({ 期间: '2026-08', 组织: '华东', 单位: '万元', 币种: 'CNY', 情景: 'actual' })) {
      const adopt = page.getByRole('button', { name: `采用资料里的${label} ${value}`, exact: true });
      if (label === '情景') assert.equal(await adopt.innerText(), '实际', 'scenario suggestion shows its business label');
      await adopt.click();
    }
    await chooseOption('分析范围单位', '万元');
    await chooseOption('分析范围币种', '人民币');
    await chooseOption('分析范围情景', '实际');
    await assertScopeFields('分析范围', { 期间: '2026-08', 组织: '华东', 单位: '万元', 币种: '人民币', 情景: '实际' });
    await page.getByRole('region', { name: '分析范围' }).getByText('更多范围').click();
    await page.getByRole('button', { name: '采用资料里的账簿 经营总账', exact: true }).click();
    await page.getByRole('button', { name: '采用资料里的粒度 区域', exact: true }).click();
    await assertScopeFields('分析范围', { 账簿: '经营总账', 粒度: '区域' });
    await page.getByRole('button', { name: '保存范围', exact: true }).click();
    await page.getByRole('status').filter({ hasText: '已保存分析范围，旧版本仍保留。' }).waitFor({ timeout: 20000 });
    const savedRequirements = cli('analysis-requirements-list', ['--spec', '{}'], task.id).current;
    assert.deepEqual(savedRequirements.scope, { period: '2026-08', organization: '华东', unit: '万元', currency: 'CNY', scenario: 'actual', ledger: '经营总账', granularity: '区域' });
    await capture('scope-confirmed-1280', 1280, 800);
    await page.getByRole('tab', { name: /财务分析/ }).click();
    await page.locator('details.analysis-finance-setup > summary').first().click();
    const settings = page.getByRole('region', { name: /^(范围与计算|计算定义与参数)$/ });
    await settings.waitFor();
    await assertScopeLine(settings, ['期间 2026 年 8 月', '组织 华东', '单位 万元', '币种 人民币', '情景 实际', '账簿 经营总账']);
    await reloadWorkspace();
    await openTask('华东八月经营分析');
    await page.getByRole('tab', { name: /范围/ }).click();
    await page.getByRole('region', { name: '分析范围' }).waitFor();
    await assertScopeFields('分析范围', { 期间: '2026-08', 组织: '华东', 单位: '万元', 币种: '人民币', 情景: '实际' });
    await page.getByRole('region', { name: '分析范围' }).getByText('更多范围').click();
    await assertScopeFields('分析范围', { 账簿: '经营总账', 粒度: '区域' });
    await page.getByRole('tab', { name: /财务分析/ }).click();
    await page.getByRole('table', { name: '业务结果' }).waitFor({ timeout: 30000 });
    checks.push('真实合成资料 metadata/scope_hints 一键采用为分析范围；保存写入 requirements，财务分析「自己动手算」读出同一范围，重载后持久化');
    // 本月三句话 (#166) opens at the top of the task; once folded, the results own the first screen again.
    const brief = page.locator('details.analysis-brief');
    assert.equal(await brief.getAttribute('open'), '', '本月三句话 opens expanded at the top of the task');
    await brief.locator(':scope > summary').click();
    await brief.locator(':scope > :not(summary)').first().waitFor({ state: 'hidden' });
    // The fold animates shut; measure once only its summary is left.
    await page.waitForFunction(() => {
      const node = document.querySelector('details.analysis-brief'), summary = node?.querySelector(':scope > summary');
      return node && summary && node.getBoundingClientRect().height - summary.getBoundingClientRect().height < 40;
    }, null, { timeout: 10000 });
    await capture('results-1440', 1440, 900);
    await capture('results-1280', 1280, 800);
    // The whole 业务结果 table sits inside the visible part of the results pane, unscrolled.
    const resultTable = await page.getByRole('table', { name: '业务结果' }).evaluate(node => {
      const frame = document.querySelector('.workspace-results'), rect = node.getBoundingClientRect(), pane = frame.getBoundingClientRect();
      return { top: rect.top, bottom: rect.bottom, visibleTop: Math.max(0, pane.top), visibleBottom: Math.min(innerHeight, pane.bottom), scrollTop: frame.scrollTop };
    });
    measures.push({ name: 'results-1280 业务结果 table', resultTable });
    assert.equal(resultTable.scrollTop, 0, 'results pane opens unscrolled');
    assert.ok(resultTable.top >= resultTable.visibleTop && resultTable.bottom <= resultTable.visibleBottom,
      `业务结果 table ${resultTable.top}–${resultTable.bottom} inside the first screen (${resultTable.visibleTop}–${resultTable.visibleBottom})`);
    checks.push('first viewport contains the whole 业务结果 table at 1280 × 800');
    await page.getByRole('tab', { name: /资料/ }).click();
    assert.equal(await page.locator('.analysis-source-refresh').getAttribute('open'), null, 'ERP refresh starts collapsed');
    await capture('materials-collapsed-1280', 1280, 800);
    await page.getByText('更新 ERP 来源', { exact: true }).click();
    const ledger = page.getByLabel('账簿', { exact: true });
    await ledger.evaluate(node => node.scrollIntoView({ block: 'center' }));
    // 账簿 is a combobox button: a scripted focus() on a button is not :focus-visible, keyboard focus is.
    await ledger.evaluate(node => node.focus({ focusVisible: true }));
    await ledger.hover();
    // DESIGN.md 按钮与字段: a focused field keeps its neutral --fnd-line border (no hover paint) under a 1px --fnd-focus
    // outline offset -1px, so hover + focus paints one edge. Token values from the DESIGN.md front matter / tokens.css.
    const fieldFocus = { light: { border: 'rgba(32, 41, 76, 0.12)', color: 'rgb(138, 103, 41)' }, dark: { border: 'rgba(255, 255, 255, 0.12)', color: 'rgb(191, 163, 108)' } };
    for (const theme of ['light', 'dark']) {
      await capture(`materials-focus-${theme}-1280`, 1280, 800, theme === 'dark');
      // capture dismisses the native pane's setup prompt, which takes focus into that view: give it back to the field.
      await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.focus());
      await ledger.evaluate(node => node.focus({ focusVisible: true }));
      await ledger.hover();
      // Measure after the border-color transition (--fnd-transition) has settled.
      await ledger.evaluate(node => Promise.all(node.getAnimations().filter(animation => animation.effect?.getTiming().iterations !== Infinity).map(animation => animation.finished)));
      const focus = await ledger.evaluate(node => { const css = getComputedStyle(node);
        return { focusVisible: node.matches(':focus-visible'), hovered: node.matches(':hover'), outline: css.outlineWidth, style: css.outlineStyle, offset: css.outlineOffset, border: css.borderColor, color: css.outlineColor }; });
      measures.push({ name: `materials-focus-${theme}-1280 ledger`, focus });
      assert.deepEqual(focus, { focusVisible: true, hovered: true, outline: '1px', style: 'solid', offset: '-1px', ...fieldFocus[theme] }, `${theme} ledger hover + focus`);
    }
    checks.push('ERP refresh starts collapsed; hovered and focused ledger field keeps its neutral border under one 1px inset --fnd-focus outline, light and dark');
    await page.getByText('更新 ERP 来源', { exact: true }).click();
    await page.getByRole('tab', { name: /财务分析/ }).click();
    await page.locator('details.analysis-finance-setup > summary').first().click();
    await settings.waitFor();
    await settings.getByLabel('总部费用分摊（万元）', { exact: true }).fill('30.00');
    await capture('calculation-settings-1280', 1280, 800);
    await page.keyboard.press('Escape');
    await page.locator('details.analysis-finance-setup > summary').first().click();
    assert.equal(await settings.getByLabel('总部费用分摊（万元）', { exact: true }).inputValue(), '30.00', 'parameter edits survive closing the drawer');
    await page.getByRole('button', { name: '保存新版并重跑', exact: true }).click();
    // Since #152 a figure cell holds a 查看来源 button, so the cell is named by that button; match its text instead.
    await page.getByRole('table', { name: '业务结果' }).getByRole('cell').filter({ hasText: /^240\.00$/ }).waitFor({ timeout: 20000 });
    await settings.waitFor({ state: 'hidden' });
    assert.equal(await settings.isVisible(), false, 'successful SQL calculation closes settings and shows its result');
    const rerunState = cli('analysis-state', [], task.id);
    const latestRun = rerunState.runs.at(-1);
    assert.ok(latestRun?.id && latestRun?.output_hash, 'rerun state includes exact run id and output hash for technical verification');
    const history = page.locator('details.analysis-history');
    const historySummary = await history.locator('summary').first().innerText();
    assert.equal(rerunState.runs.length, 2, 'the task keeps both saved calculations');
    assert.equal(historySummary, '计算历史 · 结果 1', 'history is scoped to the selected analysis version');
    assert.equal(historySummary.includes('活动'), false, 'history summary uses manager-facing labels');
    if (await history.getAttribute('open') === null) await history.locator('summary').first().click();
    assert.equal(await history.locator('.analysis-history-row').filter({ hasText: '中间步骤' }).count(), 0, 'business calculation history does not list middle steps as results');
    assert.equal(await history.locator('.analysis-history-steps').count(), 0, 'no synthetic middle steps were mocked into the fixture');
    await page.locator('.workspace-results').evaluate(node => { node.scrollTop = 0; });
    checks.push('named decimal parameter saves a new version and changes actual result 250 → 240');
    await page.getByRole('button', { name: '查看本次计算依据' }).click();
    await capture('evidence-1280', 1280, 800);
    const evidence = page.getByRole('dialog', { name: '本次计算依据' });
    const technical = evidence.locator('details.analysis-technical');
    assert.ok(await technical.count() >= 2, 'evidence exposes source and run technical info blocks');
    assert.equal(await technical.evaluateAll(nodes => nodes.every(node => !node.hasAttribute('open'))), true, 'technical info is collapsed by default');
    const foldedEvidenceText = await evidence.innerText();
    assert.equal(foldedEvidenceText.includes(dataset.id), false, 'folded evidence hides exact dataset id');
    assert.equal(foldedEvidenceText.includes(latestRun.id), false, 'folded evidence hides exact run id');
    for (let index = 0, count = await technical.count(); index < count; index += 1) await technical.nth(index).locator('summary').click();
    // The folds animate open; read the dialog once the last one's contents are on screen.
    await page.waitForFunction(id => document.querySelector('[role="dialog"]')?.innerText.includes(id), latestRun.id, { timeout: 5000 }).catch(() => undefined);
    const expandedEvidenceText = await evidence.innerText();
    assert.ok(expandedEvidenceText.includes(dataset.id), 'expanded technical info shows the exact dataset id');
    assert.ok(expandedEvidenceText.includes(latestRun.id), 'expanded technical info shows the exact run id');
    assert.ok(expandedEvidenceText.includes(latestRun.output_hash), 'expanded technical info shows the exact output hash');
    await capture('technical-expanded-1280', 1280, 800);
    checks.push('计算历史 uses 结果/未完成 wording; 技术信息 is default-collapsed, then reveals exact dataset/run/hash identifiers on demand');
    await page.keyboard.press('Escape');
    assert.equal(await page.getByRole('button', { name: '查看本次计算依据' }).evaluate(node => node === document.activeElement), true);
    await page.getByRole('button', { name: '查看本次计算依据' }).click();
    await page.getByRole('button', { name: '查看 八月经营数据', exact: true }).click();
    // The snapshot opens in the 依据资料 preview on the results tab, naming the dataset version the run bound.
    const preview = page.getByRole('region', { name: '依据资料预览' });
    await preview.getByRole('heading', { name: '八月经营数据', exact: true }).waitFor();
    assert.ok((await preview.locator('.analysis-technical').textContent()).includes(dataset.id), 'preview names the bound snapshot');
    checks.push('run alias opens the exact source snapshot in the 依据资料 preview');
    await page.getByRole('tab', { name: /财务分析/ }).click();
    const closeEvidence = page.getByRole('button', { name: '关闭计算依据' });
    if (await closeEvidence.isVisible()) await closeEvidence.click();
    await page.getByRole('button', { name: '比较版本', exact: true }).click();
    const comparison = page.getByLabel('对照结果');
    await comparison.selectOption({ index: 1 });
    await page.getByRole('table', { name: '对照版本数据' }).waitFor();
    await page.getByRole('table', { name: '对照版本数据' }).scrollIntoViewIfNeeded();
    await capture('comparison-1440', 1440, 900);
    checks.push('saved runs compare and evidence closes with Escape returning focus');
    await page.getByText('保存这次分析方法', { exact: true }).click();
    await page.getByLabel('方法名称', { exact: true }).fill('区域利润分摊方法');
    await page.getByRole('button', { name: '保存为方法', exact: true }).click();
    await page.getByRole('status').filter({ hasText: '已保存方法，可在方法库中复用。' }).waitFor();
    const expandForMethods = page.getByRole('button', { name: '展开任务列表' });
    if (await expandForMethods.isVisible()) await expandForMethods.click();
    await page.locator('.workspace-library').filter({ hasText: '方法库' }).click();
    const savedMethod = page.locator('.analysis-method').filter({ hasText: '区域利润分摊方法' });
    await savedMethod.waitFor();
    const methodAdvanced = savedMethod.locator('details');
    assert.equal(await methodAdvanced.getAttribute('open'), null, 'method definitions are initially hidden');
    assert.equal(await methodAdvanced.locator('pre').isVisible(), false);
    assert.equal(await savedMethod.getByLabel('总部费用分摊（万元）', { exact: true }).inputValue(), '', 'saved business values are not silently reused');
    await capture('method-library-1280', 1280, 800);
    await methodAdvanced.locator('summary').click();
    await methodAdvanced.locator('pre').waitFor({ state: 'visible' });
    assert.ok((await methodAdvanced.innerText()).includes('SELECT'), 'the saved SQL stays accessible');
    await capture('method-library-advanced-dark-1080', 1080, 800, true);
    await page.getByRole('tab', { name: /财务分析/ }).click();
    checks.push('method library separates business parameters from the collapsed calculation definition and does not reuse saved amounts');
    // 文稿 (DraftEditor + ReportEditor): a saved draft opens in 阅读 mode inside the 文稿工作区, its toolbar saying
    // 文稿 · 草稿 · 未阅, the Markdown rendered as a document at the 16px/28px reading size with 18px after each paragraph.
    await page.getByRole('tab', { name: /汇报/ }).click();
    await page.getByRole('tab', { name: /文稿/ }).click();
    const reading = page.getByRole('article', { name: '文稿阅读' });
    await reading.waitFor();
    const modes = page.getByRole('tablist', { name: '文稿模式' });
    assert.equal(await modes.getByRole('tab', { name: '阅读', exact: true }).getAttribute('aria-selected'), 'true', 'a saved draft opens in 阅读');
    const toolbar = page.getByRole('group', { name: '文稿工具栏' });
    assert.equal(await toolbar.getByRole('heading', { level: 3 }).innerText(), '文稿');
    assert.match(await toolbar.locator('.report-status').innerText(), /^草稿 · 未阅 · 检查：/, 'toolbar states the draft revision');
    await reading.getByRole('heading', { name: '八月经营分析备忘', exact: true }).waitFor();
    for (const section of ['经营表现', '口径与判断']) await reading.getByRole('heading', { name: section, exact: true }).waitFor();
    assert.equal(await reading.locator('strong').filter({ hasText: '250 万元' }).count(), 1, 'Markdown emphasis rendered, not shown as **');
    assert.deepEqual(await reading.getByRole('listitem').allInnerTexts(), ['继续核对区域费用明细。', '将预算与实际数据按同一口径比较。']);
    assert.equal((await reading.innerText()).includes('**'), false, 'no raw Markdown markers in the reading view');
    const readingType = await reading.evaluate(node => { const css = getComputedStyle(node), paragraph = getComputedStyle(node.querySelector('p'));
      // --fnd-font-prose leads with FND Figures (digits and % only, DESIGN.md 决定 4B); the words are set in the face after it.
      const families = css.fontFamily.split(',').map(family => family.trim().replaceAll('"', ''));
      return { figures: families[0], font: families[1], size: css.fontSize, leading: css.lineHeight, after: paragraph.marginBottom }; });
    measures.push({ name: 'draft reading type', readingType });
    assert.deepEqual(readingType, { figures: 'FND Figures', font: 'Noto Sans SC', size: '16px', leading: '28px', after: '18px' }, 'reading typography per DESIGN.md');
    await reading.scrollIntoViewIfNeeded();
    await capture('draft-1440', 1440, 900);
    await capture('draft-dark-1280', 1280, 800, true);
    checks.push('saved draft opens in 阅读 with its revision state, rendered Markdown and 16px/28px reading type');
    const references = page.locator('details').filter({ has: page.locator('summary').filter({ hasText: /^引用的计算与依据 · 1 次计算$/ }) }).last();
    await openFold(references);
    assert.ok((await references.innerText()).includes('引用计算 1'), 'draft references use readable ordinals');
    assert.equal((await references.innerText()).includes(run.id), false, 'the saved run id is hidden');
    const referenceTechnical = references.locator('details.analysis-technical');
    await openFold(referenceTechnical);
    assert.ok((await referenceTechnical.innerText()).includes(run.id), 'technical information shows the exact draft reference');
    await capture('draft-references-1280', 1280, 800);
    await references.locator(':scope > summary').click();
    checks.push('draft references use ordinals with exact cited run ids under TechnicalInfo');
    // 编辑: the manager rewrites the body through the Markdown source field; the visual editor follows it and the
    // draft is marked changed (未阅, not rechecked) with the note that export saves it first.
    await modes.getByRole('tab', { name: '编辑', exact: true }).click();
    assert.equal(await page.getByRole('textbox', { name: '文稿标题', exact: true }).inputValue(), '八月经营分析备忘');
    const source = page.getByRole('textbox', { name: '文稿正文', exact: true });
    assert.ok((await source.inputValue()).startsWith('## 经营表现'), 'Markdown source holds the saved body');
    const body = '经理补充：继续核对实际费用归属；本文所附计算仍保留原来的分摊口径，后续采用新版测算时再更新引用。';
    await source.fill(body);
    await page.getByLabel('可视化文稿编辑器', { exact: true }).filter({ hasText: body }).waitFor();
    assert.match(await toolbar.locator('.report-status').innerText(), /^草稿 · 未阅 · 检查：改稿后未重检$/, 'an edited body reads as not rechecked');
    await page.getByRole('button', { name: '保存文稿新版', exact: true }).waitFor();
    await page.getByText('交给助手或导出时，会先保存当前内容为新版本。', { exact: true }).waitFor();
    await toolbar.evaluate(node => node.scrollIntoView({ block: 'start' }));
    await capture('draft-edit-1280', 1280, 800);
    // Export asks main for a save path; answer it inside the isolated QA folder instead of showing the dialog.
    const exportPath = qa + '/exports/八月经营分析备忘-management.xlsx';
    fs.mkdirSync(path.dirname(exportPath), { recursive: true });
    await app.evaluate(({ dialog }, file) => { globalThis.__uiSaveDialogs = []; dialog.showSaveDialog = async (...args) => { globalThis.__uiSaveDialogs.push(args.at(-1)); return { canceled: false, filePath: file }; }; }, exportPath);
    await toolbar.getByRole('button', { name: '导出', exact: true }).click();
    await page.getByRole('menuitem', { name: /导出工作簿/ }).click();
    await page.getByRole('status').filter({ hasText: `已导出工作簿：${exportPath}` }).waitFor({ timeout: 30000 });
    const dialogs = await app.evaluate(() => globalThis.__uiSaveDialogs);
    assert.equal(dialogs.length, 1); assert.equal(dialogs[0].title, '导出财务文稿');
    const exported = [exportPath]; assert.ok(fs.readFileSync(exportPath).subarray(0, 2).equals(Buffer.from('PK')), 'exported workbook is a zip');
    const state = cli('analysis-state', [], task.id);
    assert.equal(state.drafts.length, 2, 'export saved the edited body as a new draft version');
    assert.equal(state.drafts.at(-1).body, body); assert.equal(state.drafts.at(-1).parent_id, state.drafts[0].id);
    assert.deepEqual(state.drafts.at(-1).run_ids, [run.id], 'editing the body keeps the cited run');
    assert.equal(state.analyses.length, 2); assert.equal(state.runs.length, 2);
    checks.push('编辑 via Markdown source marks the draft changed; export saves it as a new version citing the same run and writes a valid workbook');
    await page.getByRole('tab', { name: /财务分析/ }).click();
    await capture('results-narrow-1080', 1080, 760);
    assert.equal(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].contentView.children
      .filter(child => child.webContents).some(child => child.getVisible())), false, 'native layer is hidden in result focus');
    await page.getByRole('button', { name: '展开任务列表' }).click();
    await capture('tasks-overlay-1080', 1080, 760);
    assert.equal(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].contentView.children
      .filter(child => child.webContents).some(child => child.getVisible())), false, 'native layer is hidden behind task overlay');
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: /修改任务名称/ }).click();
    await page.getByLabel('任务名称', { exact: true }).fill('华东经营分析 · 财务复核');
    await page.getByRole('button', { name: '保存任务名称' }).click();
    await page.getByRole('heading', { name: '华东经营分析 · 财务复核' }).first().waitFor();
    assert.equal(cli('task-list').find(row => row.id === task.id).title, '华东经营分析 · 财务复核');
    checks.push('task rename persists without changing task identity');
    await page.getByRole('button', { name: '展开任务列表' }).click();
    await page.getByRole('button', { name: '新建任务', exact: true }).click();
    await capture('new-task-1280', 1280, 800);
    assert.equal(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].contentView.children
      .filter(child => child.webContents).some(child => child.getVisible())), false, 'native layer is hidden on new task');
    console.log(JSON.stringify(writeEvidence({ task: task.id, exportedDraft: state.drafts.at(-1),
      exportedRuns: state.drafts.at(-1).run_ids.map(id => state.runs.find(row => row.id === id)), exported: exported[0] })));
  } catch (error) {
    writeEvidence({ status: 'failed', error: String(error) });
    try { console.error('DOM:', await (await app.firstWindow()).locator('body').innerText()); }
    catch (dump) { console.error('DOM unavailable:', String(dump)); }
    console.error(JSON.stringify({ qa, output, checks, measures, firstScreen: firstScreenMeasures, error: String(error) })); throw error;
  } finally { await app.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
