#!/usr/bin/env node
// Manual desktop regressions that need a real packaged Electron app and synthetic data only.
// Current coverage: StructureProposalCard header contrast and task lifecycle UI persistence.
const { _electron } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const assert = require('node:assert/strict');
const { writeWorkbook } = require('./fixtures/write_manual_regression_budget_xlsx.cjs');

function hashFile(file) { return createHash('sha256').update(fs.readFileSync(file)).digest('hex'); }
function requireFile(file, label) { if (!fs.existsSync(file)) throw new Error(`${label} missing: ${file}`); return file; }
function safeRm(file) { fs.rmSync(file, { force: true }); }
function parseColor(value) {
  const text = String(value || '').trim();
  const rgb = text.match(/^rgba?\(([^)]+)\)$/i);
  if (rgb) {
    const parts = rgb[1].split(',').map((part) => part.trim());
    return { r: Number(parts[0]), g: Number(parts[1]), b: Number(parts[2]), a: parts[3] === undefined ? 1 : Number(parts[3]) };
  }
  const hex = text.match(/^#([0-9a-f]{6})$/i);
  if (hex) return { r: parseInt(hex[1].slice(0, 2), 16), g: parseInt(hex[1].slice(2, 4), 16), b: parseInt(hex[1].slice(4, 6), 16), a: 1 };
  return null;
}
function channel(value) { const next = value / 255; return next <= 0.03928 ? next / 12.92 : ((next + 0.055) / 1.055) ** 2.4; }
function luminance(color) { return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b); }
function compositeOver(fg, bg) {
  const alpha = fg.a === undefined ? 1 : fg.a;
  return {
    r: fg.r * alpha + bg.r * (1 - alpha),
    g: fg.g * alpha + bg.g * (1 - alpha),
    b: fg.b * alpha + bg.b * (1 - alpha),
    a: 1,
  };
}
function contrast(fg, bg) {
  const high = Math.max(luminance(fg), luminance(bg));
  const low = Math.min(luminance(fg), luminance(bg));
  return (high + 0.05) / (low + 0.05);
}
function round(value) { return Math.round(value * 1000) / 1000; }

(async () => {
  const repo = path.resolve(__dirname, '..');
  const bundle = path.resolve(process.env.UI_APP_BUNDLE || '/Applications/FA Foundry.app');
  const output = path.resolve(process.env.UI_EVIDENCE_DIR || path.join(repo, 'build/manual-regressions/current'));
  const baselineMode = process.env.UI_EXPECT_FAILURE === '1' || process.env.UI_BASELINE === '1' || path.basename(output) === 'baseline';
  const threshold = Number(process.env.UI_CONTRAST_THRESHOLD || '4.5');
  const requestedChecks = new Set(String(process.env.UI_MANUAL_CHECKS || 'structure,lifecycle').split(',').map((item) => item.trim()).filter(Boolean));
  const qa = fs.mkdtempSync('/tmp/finance-ui-manual-regressions-');
  const varRoot = path.join(qa, 'var');
  const fixtureDir = path.join(qa, 'fixtures');
  const fixture = path.join(fixtureDir, 'structure-proposal-budget.xlsx');
  const lifecycleSource = path.join(fixtureDir, 'lifecycle-source.csv');
  const executable = requireFile(path.join(bundle, 'Contents/MacOS/FA Foundry'), 'Electron executable');
  const bin = requireFile(path.join(bundle, 'Contents/Resources/foundry/foundry'), 'packaged foundry CLI');
  const appAsar = requireFile(path.join(bundle, 'Contents/Resources/app.asar'), 'app.asar');
  const verification = path.join(output, 'verification.json');
  fs.mkdirSync(output, { recursive: true });
  safeRm(verification);

  const checks = [];
  const measures = [];
  const failures = [];
  let app;
  let page;
  const pass = (name, detail = {}) => checks.push({ name, ok: true, ...detail });
  const fail = (name, message, detail = {}) => { failures.push({ name, message, ...detail }); checks.push({ name, ok: false, message, ...detail }); };
  const cli = (command, args = [], task) => {
    const raw = execFileSync(bin, ['--var', varRoot, ...(task ? ['--task', task] : []), command, ...args], { encoding: 'utf8' }).trim();
    if (command === 'task-new') return { id: raw };
    return JSON.parse(raw);
  };


  const launchDesktop = async () => {
    const launched = await _electron.launch({
      executablePath: executable,
      args: [`--user-data-dir=${path.join(qa, 'profile')}`],
      env: { ...process.env, FOUNDRY_VAR: varRoot, FOUNDRY_BIN: undefined, FOUNDRY_DSH_INSTALL: undefined, FOUNDRY_FORMULATOR_BIN: undefined },
      timeout: 60000,
    });
    const first = await launched.firstWindow();
    await first.waitForLoadState('domcontentloaded');
    await first.locator('.workspace-header').waitFor({ timeout: 45000 });
    await first.waitForFunction(async () => {
      const result = await window.foundry.harnessStatus();
      return result.ok && result.value.wiring.state === 'ready';
    }, undefined, { timeout: 60000 });
    return { app: launched, page: first };
  };

  const visibleText = async (needle) => {
    const text = await page.evaluate(() => document.body.innerText || '');
    return text.includes(needle);
  };
  const ensureSidebar = async () => {
    const open = await page.evaluate(() => document.querySelector('.workspace')?.getAttribute('data-sidebar') === 'open').catch(() => false);
    if (open) return;
    const toggle = page.locator('.workspace-header button[title="任务列表"], .workspace-header button[aria-label="展开任务列表"]').first();
    await toggle.waitFor({ state: 'visible', timeout: 30000 });
    await toggle.click();
    await page.waitForFunction(() => document.querySelector('.workspace')?.getAttribute('data-sidebar') === 'open', undefined, { timeout: 30000 });
  };
  const openLifecycleView = async (label) => {
    await ensureSidebar();
    const button = page.locator('.workspace-lifecycle button').filter({ hasText: label }).first();
    await button.waitFor({ timeout: 30000 });
    await button.click();
    await expectPressed(button, `${label} lifecycle filter is selected`);
  };
  const expectPressed = async (locator, label) => {
    await page.waitForFunction((text) => {
      const buttons = [...document.querySelectorAll('.workspace-lifecycle button')];
      return buttons.some((button) => button.textContent?.includes(text) && button.getAttribute('aria-pressed') === 'true');
    }, label.split(' ')[0], { timeout: 30000 }).catch(async () => {
      const pressed = await locator.getAttribute('aria-pressed').catch(() => null);
      assert.equal(pressed, 'true', label);
    });
  };
  const pickTaskByTitle = async (title) => {
    await ensureSidebar();
    const item = page.locator('.workspace-task').filter({ hasText: title }).first();
    await item.waitFor({ timeout: 30000 });
    await item.click();
    await page.locator('.workspace-title').filter({ hasText: title }).waitFor({ timeout: 30000 });
  };
  const expectTaskInSidebar = async (title, expected, checkName) => {
    const locator = page.locator('.workspace-task').filter({ hasText: title });
    if (expected) {
      await locator.first().waitFor({ state: 'visible', timeout: 30000 });
      pass(checkName, { title, expected });
      return;
    }
    await page.waitForFunction((needle) => {
      return ![...document.querySelectorAll('.workspace-task')].some((node) => node.textContent?.includes(needle));
    }, title, { timeout: 30000 });
    pass(checkName, { title, expected });
  };
  const chooseTaskTool = async (label) => {
    await page.getByRole('button', { name: '任务工具' }).click();
    const item = page.getByRole('menuitem', { name: new RegExp(label) }).first();
    await item.waitFor({ timeout: 30000 });
    await item.click();
  };
  const waitTaskStatus = async (taskId, status) => {
    await page.waitForFunction(async ({ id, expected }) => {
      const result = await window.foundry.tasks(expected);
      if (!result.ok) return false;
      return result.value.some((task) => task.id === id && (task.lifecycle_status || 'active') === expected);
    }, { id: taskId, expected: status }, { timeout: 30000 });
  };
  const captureWindow = async (name) => {
    await page.evaluate(() => document.fonts.ready);
    const image = await app.evaluate(async ({ BrowserWindow }) => (await BrowserWindow.getAllWindows()[0].capturePage()).toPNG().toString('base64'));
    fs.writeFileSync(path.join(output, `${name}.png`), Buffer.from(image, 'base64'));
  };
  const galleryVisibleRows = async () => page.evaluate(() => {
    const screen = document.querySelector('.fnd-shell[data-screen="deliverables"]');
    if (!screen) return [];
    return [...screen.querySelectorAll('tbody tr, .fnd-table__open')]
      .filter((row) => {
        const rect = row.getBoundingClientRect();
        const style = getComputedStyle(row);
        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
      })
      .map((row) => row.textContent?.replace(/\s+/g, ' ').trim() ?? '')
      .filter(Boolean);
  });
  const openGallery = async () => {
    await page.getByRole('button', { name: '成果库' }).click();
    await page.locator('.fnd-shell[data-screen="deliverables"]').waitFor({ timeout: 30000 });
  };
  const assertGalleryContains = async (title, expected, checkName) => {
    await openGallery();
    if (expected) {
      await page.waitForFunction((needle) => {
        const screen = document.querySelector('.fnd-shell[data-screen="deliverables"]');
        return Boolean(screen && (screen.innerText || '').includes(needle));
      }, title, { timeout: 30000 });
    } else {
      await page.waitForFunction(async (needle) => {
        const result = await window.foundry.gallery();
        if (!result.ok) return false;
        return !result.value.some((entry) => entry.task?.title === needle);
      }, title, { timeout: 30000 });
      await page.waitForFunction((needle) => {
        const screen = document.querySelector('.fnd-shell[data-screen="deliverables"]');
        if (!screen) return false;
        const rows = [...screen.querySelectorAll('tbody tr, .fnd-table__open')].filter((row) => {
          const rect = row.getBoundingClientRect();
          const style = getComputedStyle(row);
          return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
        });
        return rows.every((row) => !(row.textContent || '').includes(needle));
      }, title, { timeout: 30000 });
    }
    const rows = await galleryVisibleRows();
    const contains = rows.some((row) => row.includes(title));
    if (contains === expected) pass(checkName, { title, expected, rows: rows.slice(0, 8) });
    else {
      await captureWindow(`${checkName}-failure`).catch(() => {});
      fail(checkName, `gallery ${expected ? 'does not show' : 'still shows'} visible row for ${title}`, { title, expected, contains, rows: rows.slice(0, 8) });
    }
  };
  const assertSourceHashStable = (taskId, datasetId, expectedHash) => {
    const state = cli('analysis-state', [], taskId);
    const source = state.sources?.find((item) => item.id === datasetId) ?? state.datasets?.find?.((item) => item.id === datasetId);
    assert.ok(source, 'lifecycle source remains readable from analysis-state');
    const actual = source.source_hash || source.sha256 || source.hash;
    assert.equal(actual, expectedHash, 'lifecycle source hash remains unchanged');
    pass('lifecycle-source-hash-stable', { task: taskId, dataset: datasetId, sourceHash: actual });
  };
  const verifyTaskLifecycle = async (seed) => {
    await page.getByRole('button', { name: '工作区' }).click();
    await openLifecycleView('进行中');
    await pickTaskByTitle(seed.primaryTitle);
    await chooseTaskTool('归档任务');
    await waitTaskStatus(seed.primary.id, 'archived');
    await openLifecycleView('已归档');
    await expectTaskInSidebar(seed.primaryTitle, true, 'lifecycle-archive-visible-in-sidebar');
    await assertGalleryContains(seed.primaryTitle, true, 'lifecycle-archived-visible-in-gallery');
    await page.getByRole('button', { name: '工作区' }).click();
    await openLifecycleView('已归档');
    await pickTaskByTitle(seed.primaryTitle);
    await chooseTaskTool('恢复任务');
    await waitTaskStatus(seed.primary.id, 'active');
    await openLifecycleView('进行中');
    await expectTaskInSidebar(seed.primaryTitle, true, 'lifecycle-restore-from-archive-visible-in-active');
    await pickTaskByTitle(seed.primaryTitle);
    await chooseTaskTool('移入回收站');
    await waitTaskStatus(seed.primary.id, 'trashed');
    await openLifecycleView('回收站');
    await expectTaskInSidebar(seed.primaryTitle, true, 'lifecycle-trash-visible-in-recycle');
    await assertGalleryContains(seed.primaryTitle, false, 'lifecycle-trashed-hidden-from-gallery');
    await captureWindow('lifecycle-trashed-before-restart');
    await app.close();
    app = null;
    ({ app, page } = await launchDesktop());
    await page.getByRole('button', { name: '工作区' }).click();
    await openLifecycleView('回收站');
    await expectTaskInSidebar(seed.primaryTitle, true, 'lifecycle-trash-persists-after-restart');
    await pickTaskByTitle(seed.primaryTitle);
    await chooseTaskTool('恢复任务');
    await waitTaskStatus(seed.primary.id, 'active');
    await openLifecycleView('进行中');
    await expectTaskInSidebar(seed.primaryTitle, true, 'lifecycle-restore-from-trash-visible-in-active');
    assertSourceHashStable(seed.primary.id, seed.dataset.id, seed.sourceHash);
    const activeTasks = cli('task-list', ['--lifecycle', 'active']);
    assert.ok(activeTasks.some((task) => task.id === seed.other.id), 'control task remains active during lifecycle operations');
    pass('lifecycle-control-task-still-active', { task: seed.other.id });
  };

  const writeEvidence = (status) => {
    const body = {
      status,
      baselineMode,
      threshold,
      bundle,
      executable,
      qa,
      output,
      synthetic: true,
      providerCalls: 0,
      app: { appAsarSha256: hashFile(appAsar), executableSha256: hashFile(executable), foundrySha256: hashFile(bin) },
      fixture,
      requestedChecks: [...requestedChecks],
      checks,
      measures,
      failures,
      assumptions: [
        'Synthetic XLSX is generated locally and registered as a workbook snapshot with packaged foundry CLI dataset-add.',
        'No model/provider/query-locked calls are used.',
        'Contrast is measured from rendered table header computed foreground composited over effective background colors.',
        'Baseline runs may record failed checks while exiting successfully so the old build can be preserved as evidence.',
      ],
    };
    fs.writeFileSync(verification, JSON.stringify(body, null, 2));
    return body;
  };

  try {
    const generated = writeWorkbook(fixture);
    fs.writeFileSync(lifecycleSource, [
      '科目,2026-07,2026-08,2026-09,备注',
      '收入,100,120,140,持久化验收源文件',
      '成本,40,44,48,保持hash不变',
    ].join('\n') + '\n');
    const task = cli('task-new', ['--title', '结构确认样式回归', '--period', '2026-09']);
    const dataset = cli('dataset-add', [
      '--path', fixture,
      '--name', '多工作表预算',
      '--meta', JSON.stringify({ mode: 'workbook', period: '2026', unit: '万元', currency: 'CNY', scenario: 'budget' }),
    ], task.id);
    const lifecycleSeed = {
      primaryTitle: '生命周期验收主任务',
      otherTitle: '生命周期验收对照任务',
      primary: cli('task-new', ['--title', '生命周期验收主任务', '--period', '2026-09']),
      other: cli('task-new', ['--title', '生命周期验收对照任务', '--period', '2026-09']),
      dataset: null,
      draft: null,
      sourceHash: hashFile(lifecycleSource),
    };
    lifecycleSeed.dataset = cli('dataset-add', [
      '--path', lifecycleSource,
      '--name', '生命周期源文件',
      '--meta', JSON.stringify({ period: '2026-09', unit: '万元', currency: 'CNY', scenario: 'lifecycle' }),
    ], lifecycleSeed.primary.id);
    lifecycleSeed.draft = cli('analysis-draft', ['--spec', JSON.stringify({
      title: '生命周期成果',
      body: '## 生命周期成果\n\n这是一份合成成果，用于验证归档任务仍出现在成果库，回收站任务从成果库隐藏。',
      run_ids: [],
      claims: [],
      limitations: [],
    })], lifecycleSeed.primary.id);
    assert.equal(lifecycleSeed.dataset.source_hash, lifecycleSeed.sourceHash, 'lifecycle source hash is recorded by dataset-add');
    pass('packaged-cli-seeded-lifecycle-tasks', { primary: lifecycleSeed.primary.id, other: lifecycleSeed.other.id, dataset: lifecycleSeed.dataset.id, draft: lifecycleSeed.draft.id, sourceHash: lifecycleSeed.sourceHash });
    const listed = cli('structure-proposal-list', ['--spec', '{}'], task.id);
    assert.equal(dataset.kind, 'workbook', 'fixture is registered as a workbook snapshot');
    assert.equal(dataset.structure_proposal?.structure_state, 'pending_confirmation', 'dataset-add records pending structure proposal');
    assert.ok(listed.proposals?.length >= 1, 'structure proposal list returns the pending workbook');
    const proposal = listed.proposals.find((item) => item.dataset_id === dataset.id);
    assert.ok(proposal, 'proposal belongs to the synthetic dataset');
    assert.equal(proposal.structure_state, 'pending_confirmation', 'proposal is pending manager confirmation');
    const mainSheet = proposal.sheets.find((sheet) => sheet.sheet === '预算明细');
    assert.ok(mainSheet, 'proposal includes the synthetic budget sheet');
    assert.equal(mainSheet.header_row, 4, 'proposal reads row 4 as the header row');
    assert.equal(mainSheet.start_column, 'A', 'proposal starts at column A');
    assert.equal(mainSheet.end_column, 'N', 'proposal ends at column N');
    pass('packaged-cli-seeded-pending-structure-card', { task: task.id, dataset: dataset.id, proposal: proposal.id, generated });

    ({ app, page } = await launchDesktop());
    const expand = page.getByRole('button', { name: '展开任务列表' });
    if (await expand.isVisible()) await expand.click();
    await page.locator('.workspace-task').filter({ hasText: '结构确认样式回归' }).click();
    await page.locator('.workspace-title').filter({ hasText: '结构确认样式回归' }).waitFor({ timeout: 30000 });
    const datasetsTab = page.getByRole('tab', { name: /资料/ });
    if (await datasetsTab.isVisible()) await datasetsTab.click();
    const resultsFocus = page.getByRole('button', { name: '成果专注' });
    if (await resultsFocus.isVisible()) await resultsFocus.click();
    await page.getByRole('tabpanel').filter({ hasText: '多工作表预算' }).waitFor({ timeout: 45000 });
    // The file's row on the 资料 page opens its structure card in place (aria-expanded button, not a details).
    const confirm = page.getByRole('button', { name: /^去确认表结构：.*多工作表预算/ }).first();
    await confirm.waitFor({ timeout: 30000 });
    if ((await confirm.getAttribute('aria-expanded')) !== 'true') await confirm.click();
    await page.locator('.analysis-structure-card').filter({ hasText: '多工作表预算' }).first().waitFor({ timeout: 30000 });
    await page.locator('.analysis-structure-preview tr.is-header td').first().waitFor({ timeout: 30000 });
    await page.evaluate(() => document.fonts.ready);
    pass('desktop-shows-structure-proposal-card');

    async function captureAndMeasure(name, width, height, dark) {
      await app.evaluate(({ BrowserWindow, nativeTheme }, value) => {
        nativeTheme.themeSource = value.dark ? 'dark' : 'light';
        BrowserWindow.getAllWindows()[0].setContentSize(value.width, value.height);
      }, { width, height, dark });
      for (const target of app.context().pages()) await target.emulateMedia({ colorScheme: null });
      await page.waitForTimeout(500);
      await page.evaluate(() => {
        const header = document.querySelector('.analysis-structure-preview tr.is-header');
        header?.scrollIntoView({ block: 'center', inline: 'nearest' });
      });
      await page.waitForTimeout(200);
      const image = await app.evaluate(async ({ BrowserWindow }) => (await BrowserWindow.getAllWindows()[0].capturePage()).toPNG().toString('base64'));
      fs.writeFileSync(path.join(output, `${name}.png`), Buffer.from(image, 'base64'));
      try {
        const mediaSource = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getMediaSourceId());
        const id = mediaSource.split(':')[1];
        execFileSync('/usr/sbin/screencapture', ['-x', '-o', '-l', id, path.join(output, `${name}-window.png`)], { stdio: 'pipe', timeout: 5000 });
      } catch (error) {
        // BrowserWindow capture still records this all-DOM regression; native window capture is best-effort.
      }
      const sample = await page.evaluate(() => {
        function readableBackground(node) {
          for (let current = node; current; current = current.parentElement) {
            const color = getComputedStyle(current).backgroundColor;
            if (color && !/^rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*0\s*\)$/i.test(color) && color !== 'transparent') return color;
          }
          return getComputedStyle(document.body).backgroundColor;
        }
        const card = document.querySelector('.analysis-structure-card');
        const preview = card?.querySelector('.analysis-structure-preview');
        const headerCells = [...(preview?.querySelectorAll('tr.is-header th, tr.is-header td') ?? [])];
        const cells = headerCells.map((cell) => {
          const style = getComputedStyle(cell);
          const rect = cell.getBoundingClientRect();
          return {
            text: cell.textContent?.trim() ?? '',
            color: style.color,
            backgroundColor: readableBackground(cell),
            directBackgroundColor: style.backgroundColor,
            rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
          };
        });
        const box = (selector) => {
          const node = document.querySelector(selector);
          const rect = node?.getBoundingClientRect();
          return rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null;
        };
        return {
          viewport: [innerWidth, innerHeight],
          horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
          headerCellCount: cells.length,
          cells,
          boxes: {
            card: box('.analysis-structure-card'),
            preview: box('.analysis-structure-preview'),
            header: box('.analysis-structure-preview tr.is-header'),
          },
        };
      });
      assert.equal(sample.horizontalOverflow, false, `${name} has no horizontal overflow`);
      assert.ok(sample.headerCellCount >= 3, `${name} captures the visible header row cells`);
      assert.ok(sample.cells.some((cell) => cell.text === '项目') && sample.cells.some((cell) => cell.text === '1月'), `${name} captures the project and month header cells`);
      const cells = sample.cells.map((cell) => {
        const fg = parseColor(cell.color);
        const bg = parseColor(cell.backgroundColor);
        const effectiveFg = fg && bg ? compositeOver(fg, bg) : fg;
        const ratio = effectiveFg && bg ? round(contrast(effectiveFg, bg)) : 0;
        return { ...cell, parsedColor: fg, effectiveColor: effectiveFg, parsedBackgroundColor: bg, contrast: ratio };
      });
      const minContrast = Math.min(...cells.map((cell) => cell.contrast));
      const failed = cells.filter((cell) => cell.contrast < threshold);
      const measure = { name, dark, threshold, minContrast, failedCount: failed.length, cells, boxes: sample.boxes };
      measures.push(measure);
      if (failed.length) fail(`${name}:structure-header-contrast`, `minimum contrast ${minContrast} is below ${threshold}`, { failed: failed.slice(0, 6) });
      else pass(`${name}:structure-header-contrast`, { minContrast });
      return measure;
    }


    async function captureOptionalReadinessContrast(name, width, height, dark) {
      await app.evaluate(({ BrowserWindow, nativeTheme }, value) => {
        nativeTheme.themeSource = value.dark ? 'dark' : 'light';
        BrowserWindow.getAllWindows()[0].setContentSize(value.width, value.height);
      }, { width, height, dark });
      for (const target of app.context().pages()) await target.emulateMedia({ colorScheme: null });
      await page.waitForTimeout(500);
      const sample = await page.evaluate(() => {
        function readableBackground(node) {
          for (let current = node; current; current = current.parentElement) {
            const color = getComputedStyle(current).backgroundColor;
            if (color && !/^rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*0\s*\)$/i.test(color) && color !== 'transparent') return color;
          }
          return getComputedStyle(document.body).backgroundColor;
        }
        const row = document.querySelector('.analysis-readiness-table thead tr');
        if (!row) return { present: false, cells: [] };
        row.scrollIntoView({ block: 'center', inline: 'nearest' });
        const cells = [...row.querySelectorAll('th, td')].map((cell) => {
          const style = getComputedStyle(cell);
          const rect = cell.getBoundingClientRect();
          return {
            text: cell.textContent?.trim() ?? '',
            color: style.color,
            backgroundColor: readableBackground(cell),
            directBackgroundColor: style.backgroundColor,
            rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
          };
        });
        return { present: true, cells };
      });
      if (!sample.present || sample.cells.length === 0) {
        pass(`${name}:readiness-header-contrast-skipped`, { reason: 'no visible readiness table header' });
        return null;
      }
      await page.waitForTimeout(200);
      const image = await app.evaluate(async ({ BrowserWindow }) => (await BrowserWindow.getAllWindows()[0].capturePage()).toPNG().toString('base64'));
      fs.writeFileSync(path.join(output, `${name}.png`), Buffer.from(image, 'base64'));
      const cells = sample.cells.map((cell) => {
        const fg = parseColor(cell.color);
        const bg = parseColor(cell.backgroundColor);
        const effectiveFg = fg && bg ? compositeOver(fg, bg) : fg;
        const ratio = effectiveFg && bg ? round(contrast(effectiveFg, bg)) : 0;
        return { ...cell, parsedColor: fg, effectiveColor: effectiveFg, parsedBackgroundColor: bg, contrast: ratio };
      });
      const minContrast = Math.min(...cells.map((cell) => cell.contrast));
      const failed = cells.filter((cell) => cell.contrast < threshold);
      const measure = { name, dark, threshold, minContrast, failedCount: failed.length, cells, target: 'readiness-table-header' };
      measures.push(measure);
      if (failed.length) fail(`${name}:readiness-header-contrast`, `minimum contrast ${minContrast} is below ${threshold}`, { failed: failed.slice(0, 6) });
      else pass(`${name}:readiness-header-contrast`, { minContrast });
      return measure;
    }

    await captureAndMeasure('structure-proposal-light-1280', 1280, 800, false);
    await captureAndMeasure('structure-proposal-dark-1280', 1280, 800, true);
    await captureAndMeasure('structure-proposal-light-1080', 1080, 760, false);
    await captureAndMeasure('structure-proposal-dark-1080', 1080, 760, true);
    await captureOptionalReadinessContrast('readiness-header-light-1280', 1280, 800, false);
    await captureOptionalReadinessContrast('readiness-header-dark-1280', 1280, 800, true);
    if (requestedChecks.has('lifecycle')) await verifyTaskLifecycle(lifecycleSeed);

    const status = failures.length ? 'failed' : 'passed';
    const evidence = writeEvidence(status);
    console.log(JSON.stringify({ status, baselineMode, checks: checks.length, failed: failures.length, output, verification, appAsarSha256: evidence.app.appAsarSha256 }, null, 2));
    if (failures.length && !baselineMode) process.exitCode = 1;
  } catch (error) {
    if (app && page) await captureWindow('manual-regression-failure').catch(() => {});
    fail('manual-regression-script', error.stack || error.message || String(error));
    const evidence = writeEvidence('error');
    console.error(JSON.stringify({ status: 'error', baselineMode, output, verification, appAsarSha256: evidence.app.appAsarSha256, error: String(error.message || error) }, null, 2));
    if (!baselineMode) process.exitCode = 1;
  } finally {
    if (app) await app.close().catch(() => {});
  }
})();
