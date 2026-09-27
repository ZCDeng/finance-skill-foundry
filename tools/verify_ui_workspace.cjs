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
  const root = path.resolve(__dirname, '..');
  const qa = fs.mkdtempSync('/tmp/finance-ui-workspace-');
  const output = path.resolve(process.env.UI_EVIDENCE_DIR || path.join(root, 'build/ui-workspace-review'));
  fs.mkdirSync(output, { recursive: true });
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
  const dataset = cli('dataset-add', ['--path', file, '--name', '八月经营数据', '--meta', JSON.stringify({ period: '2026-08', unit: '万元', currency: 'CNY' })], task.id);
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
  // UI_CHECKS picks the phases: first-screen (R12) and workspace (the flow below it); both by default.
  const phases = (process.env.UI_CHECKS || 'first-screen,workspace').split(',').map(phase => phase.trim());
  try {
    const page = await app.firstWindow(); await page.waitForLoadState('domcontentloaded');
    await page.locator('.workspace-header').waitFor();
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
        boxes: Object.fromEntries(['.fnd-head', '.workspace-header', '.workspace-native', '.workspace-results', '.analysis-result', '.analysis-table', '.analysis-draft-reading'].map(selector => {
          const node = document.querySelector(selector), rect = node?.getBoundingClientRect();
          return [selector, rect && node.checkVisibility() ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null];
        })) }));
      measures.push({ name, nativeBounds: native?.bounds, ...measurement }); assert.equal(measurement.horizontalOverflow, false, name + ' horizontal overflow');
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
    // R12 first screen: each seeded result, opened at 1280 × 800, shows its answer without scrolling, above the
    // finance settings, and its visible text holds no ids, scenario codes or raw column names.
    const measureFirstScreen = (forbidden) => page.evaluate((forbidden) => {
      const pane = document.querySelector('#analysis-panel-results'), scroller = document.querySelector('.workspace-results');
      const box = node => { if (!node) return null; const rect = node.getBoundingClientRect(); return { x: rect.x, y: rect.y, width: rect.width, height: rect.height }; };
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
        conclusion: box(pane.querySelector('.analysis-result .analysis-headline')), card: box(pane.querySelector('.analysis-result .analysis-kpi-card')), settings: box(pane.querySelector('[aria-label="财务分析设置"]')),
        cardNotes: [...pane.querySelectorAll('.analysis-kpi-card')].map(card => ({ notes: card.querySelector('.analysis-kpi-notes')?.textContent ?? '', inferred: card.textContent.includes('推断') })), hits };
    }, forbidden);
    if (phases.includes('first-screen')) for (const [kind, seeded] of Object.entries(firstScreen)) {
      await app.evaluate(({ BrowserWindow, nativeTheme }) => { nativeTheme.themeSource = 'light'; BrowserWindow.getAllWindows()[0].setContentSize(1280, 800); });
      await openTask(seeded.title);
      const resultsTab = page.getByRole('tab', { name: /分析结果/ });
      if (await resultsTab.getAttribute('aria-selected') !== 'true') await resultsTab.click();
      // The run heading carries the run id as its title: wait for this task's run, not the previous task's cards.
      await page.locator(`.analysis-result [title="${seeded.run}"]`).waitFor({ timeout: 30000 });
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
        if (kind === 'legacy') assert.ok(seen.cardNotes.every(card => card.notes.includes('推断')), name + ' every card says 推断');
        if (kind === 'declared') assert.ok(seen.cardNotes.every(card => !card.inferred), name + ' no card says 推断');
      }
      checks.push(`first screen at 1280 × 800, light and dark: ${seeded.title} shows its ${kind === 'finance' ? 'conclusion bar' : 'key figures'} unscrolled, above any settings, with no technical names${kind === 'legacy' ? ', cards marked 推断' : kind === 'declared' ? ', no card marked 推断' : ''}`);
    }
    if (!phases.includes('workspace')) {
      const evidence = { status: 'passed', qa, output, synthetic: true, providerCalls: 0, phases, notRun: ['workspace flow: UI_CHECKS leaves it out'], checks, measures, firstScreen: firstScreenMeasures,
        appAsarSha256: createHash('sha256').update(fs.readFileSync(bundle + '/Contents/Resources/app.asar')).digest('hex') };
      fs.writeFileSync(output + '/verification.json', JSON.stringify(evidence, null, 2)); console.log(JSON.stringify(evidence)); return;
    }
    await openTask('华东八月经营分析');
    await page.getByRole('table', { name: '业务结果' }).waitFor({ timeout: 30000 });
    await capture('results-1440', 1440, 900);
    await capture('results-1280', 1280, 800);
    assert.ok(measures.at(-1).boxes['.analysis-table'].y < 450, 'result table in first viewport');
    checks.push('first viewport contains result table at 1280 × 800');
    await page.getByRole('tab', { name: /资料/ }).click();
    assert.equal(await page.locator('.analysis-source-refresh').getAttribute('open'), null, 'ERP refresh starts collapsed');
    await capture('materials-collapsed-1280', 1280, 800);
    await page.getByText('更新 ERP 来源', { exact: true }).click();
    const ledger = page.getByLabel('账簿', { exact: true });
    await ledger.focus();
    await ledger.hover();
    await capture('materials-focus-light-1280', 1280, 800);
    await capture('materials-focus-dark-1280', 1280, 800, true);
    const focus = await ledger.evaluate(node => {const css=getComputedStyle(node);return {outline:css.outlineWidth,offset:css.outlineOffset,border:css.borderColor,color:css.outlineColor};});
    assert.equal(focus.outline, '2px'); assert.equal(focus.offset, '-1px'); assert.equal(focus.border, 'rgba(255, 255, 255, 0.14)'); assert.equal(focus.color, 'rgb(226, 193, 128)');
    checks.push('ERP refresh starts collapsed; real ledger hover+focus has one inset edge in both themes');
    await page.getByText('更新 ERP 来源', { exact: true }).click();
    await page.getByRole('tab', { name: /分析结果/ }).click();
    await page.getByText('口径与计算定义', { exact: true }).click();
    await page.getByLabel('总部费用分摊（万元）', { exact: true }).fill('30.00');
    await page.getByRole('button', { name: '保存新版并重跑', exact: true }).click();
    await page.getByRole('cell', { name: '240.00', exact: true }).waitFor({ timeout: 20000 });
    await page.locator('.workspace-results').evaluate(node => { node.scrollTop = 0; });
    checks.push('named decimal parameter saves a new version and changes actual result 250 → 240');
    await page.getByRole('button', { name: '查看本次计算依据' }).click();
    await capture('evidence-1280', 1280, 800);
    await page.keyboard.press('Escape');
    assert.equal(await page.getByRole('button', { name: '查看本次计算依据' }).evaluate(node => node === document.activeElement), true);
    await page.getByRole('button', { name: '查看本次计算依据' }).click();
    await page.getByRole('button', { name: '查看 八月经营数据', exact: true }).click();
    await page.getByRole('heading', { name: '八月经营数据', exact: true }).waitFor();
    checks.push('run alias opens the exact source snapshot in the material view');
    await page.getByRole('tab', { name: /分析结果/ }).click();
    const closeEvidence = page.getByRole('button', { name: '关闭计算依据' });
    if (await closeEvidence.isVisible()) await closeEvidence.click();
    await page.getByRole('button', { name: '比较版本', exact: true }).click();
    const comparison = page.getByLabel('对照运行');
    await comparison.selectOption({ index: 1 });
    await page.getByRole('table', { name: '对照版本数据' }).waitFor();
    await page.getByRole('table', { name: '对照版本数据' }).scrollIntoViewIfNeeded();
    await capture('comparison-1440', 1440, 900);
    checks.push('saved runs compare and evidence closes with Escape returning focus');
    await page.getByRole('tab', { name: /文稿/ }).click();
    await page.locator('.analysis-draft-reading').scrollIntoViewIfNeeded();
    await capture('draft-1440', 1440, 900);
    await capture('draft-dark-1280', 1280, 800, true);
    await page.getByRole('button', { name: '编辑文稿', exact: true }).click();
    const body = '经理补充：继续核对实际费用归属；本文所附计算仍保留原来的分摊口径，后续采用新版测算时再更新引用。';
    await page.locator('.analysis-draft-fields textarea').first().fill(body);
    await app.evaluate(({ shell }) => { globalThis.__uiOpened = []; shell.openPath = async file => { globalThis.__uiOpened.push(file); return ''; }; });
    await page.getByText('导出', { exact: true }).click();
    await page.getByRole('menuitem', { name: /导出工作簿/ }).click();
    await page.getByRole('status').filter({ hasText: '已导出工作簿' }).waitFor({ timeout: 15000 });
    const exported = await app.evaluate(() => globalThis.__uiOpened);
    assert.equal(exported.length, 1); assert.ok(fs.readFileSync(exported[0]).subarray(0, 2).equals(Buffer.from('PK')));
    const state = cli('analysis-state', [], task.id);
    assert.equal(state.drafts.at(-1).body, body); assert.equal(state.analyses.length, 2); assert.equal(state.runs.length, 2);
    checks.push('export saves dirty draft and writes a valid workbook for that exact version');
    await page.getByRole('tab', { name: /分析结果/ }).click();
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
    await page.getByRole('heading', { name: '华东经营分析 · 财务复核' }).waitFor();
    assert.equal(cli('task-list').find(row => row.id === task.id).title, '华东经营分析 · 财务复核');
    checks.push('task rename persists without changing task identity');
    await page.getByRole('button', { name: '展开任务列表' }).click();
    await page.getByRole('button', { name: '新建任务', exact: true }).click();
    await capture('new-task-1280', 1280, 800);
    assert.equal(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].contentView.children
      .filter(child => child.webContents).some(child => child.getVisible())), false, 'native layer is hidden on new task');
    const evidence = { status: 'passed', qa, output, task: task.id, synthetic: true, providerCalls: 0, phases, checks, measures, firstScreen: firstScreenMeasures,
      exportedDraft: state.drafts.at(-1), exportedRuns: state.drafts.at(-1).run_ids.map(id => state.runs.find(row => row.id === id)),
      exported: exported[0], appAsarSha256: createHash('sha256').update(fs.readFileSync(bundle + '/Contents/Resources/app.asar')).digest('hex') };
    fs.writeFileSync(output + '/verification.json', JSON.stringify(evidence, null, 2)); console.log(JSON.stringify(evidence));
  } catch (error) {
    console.error('DOM:', await (await app.firstWindow()).locator('body').innerText());
    console.error(JSON.stringify({ qa, output, checks, measures, firstScreen: firstScreenMeasures, error: String(error) })); throw error;
  } finally { await app.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
