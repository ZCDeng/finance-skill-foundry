#!/usr/bin/env node
'use strict';

const assert = require('assert');
const { execFileSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const repo = path.resolve(__dirname, '..');
const output = path.resolve(process.env.UI_EVIDENCE_DIR || path.join(repo, 'build/manager-ux-section7-pages'));
const bundle = path.resolve(process.env.UI_APP_BUNDLE || path.join(repo, 'build/manager-ux-section7-candidate/mac-arm64/FA Foundry.app'));
const playwrightModule = process.env.PLAYWRIGHT_MODULE || 'playwright';
const fixtures = path.join(repo, 'fixtures/period-smoke');
const title = '第七节页面验收 · locked-window';
const period = '2026-08';
const sessionId = 'section7-pages-session';
const sha64 = /^[0-9a-f]{64}$/;
const PREVIEW_BAR_HEIGHT = 44;
const GEOMETRY_TOLERANCE = 1;

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(value, null, 2));
}

function hashFile(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function failEarly(message, extra = {}) {
  const evidence = {
    status: 'not_run',
    reason: message,
    bundle,
    output,
    playwrightModule,
    ...extra,
  };
  writeJson(path.join(output, 'verification.json'), evidence);
  throw new Error(message);
}

function requireFile(file, label) {
  if (!fs.existsSync(file)) failEarly(`${label} missing`, { missing: file });
  return file;
}

function safeName(value) {
  return String(value).replace(/[^a-z0-9._-]+/gi, '-').replace(/^-|-$/g, '').toLowerCase();
}

function runCli(bin, varRoot, args, options = {}) {
  const full = ['--var', varRoot, ...(options.globalArgs || []), ...args];
  const stdout = execFileSync(bin, full, {
    cwd: repo,
    env: {
      ...process.env,
      FOUNDRY_VAR: varRoot,
      LITELLM_LOCAL_MODEL_COST_MAP: 'True',
    },
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: options.timeout || 60000,
  });
  return stdout.trim();
}

function seedStore(bin, qa) {
  const varRoot = path.join(qa, 'var');
  fs.mkdirSync(varRoot, { recursive: true });
  const task = runCli(bin, varRoot, ['task-new', '--title', title, '--period', period]);
  const taskArgs = ['--task', task];
  const windowId = runCli(bin, varRoot, ['create'], { globalArgs: taskArgs });
  runCli(bin, varRoot, [
    'import',
    '--coa', path.join(fixtures, 'coa.xlsx'),
    '--units', path.join(fixtures, 'units.xlsx'),
    '--map', path.join(fixtures, 'map.xlsx'),
    '--named', path.join(fixtures, 'named.json'),
    '--drop-dir', fixtures,
  ], { globalArgs: taskArgs, timeout: 120000 });
  runCli(bin, varRoot, ['lock'], { globalArgs: taskArgs });
  runCli(bin, varRoot, ['record-questions', '--questions', path.join(fixtures, 'questions.json')], { globalArgs: taskArgs });
  runCli(bin, varRoot, [
    'record-session',
    '--role', 'period',
    '--window', windowId,
    '--verbatim', '第七节页面专项验收 synthetic locked-window fixture',
  ], { globalArgs: [...taskArgs, '--session', sessionId] });
  runCli(bin, varRoot, ['emit-brief', '--receipt'], { globalArgs: [...taskArgs, '--session', sessionId], timeout: 120000 });
  const exportRow = JSON.parse(runCli(bin, varRoot, ['export', '--format', 'xlsx'], { globalArgs: [...taskArgs, '--session', sessionId], timeout: 120000 }));
  const deliverables = JSON.parse(runCli(bin, varRoot, ['deliverables'], { globalArgs: taskArgs }));
  const taskShow = JSON.parse(runCli(bin, varRoot, ['task-show'], { globalArgs: taskArgs }));
  assert.match(exportRow.sha256, sha64, 'export row carries exact sha256');
  assert.equal(exportRow.ext, '.xlsx', 'seeded export is an archived workbook');
  assert.equal(exportRow.window_id, windowId, 'export is tied to the seeded window');
  return { varRoot, task, windowId, exportRow, deliverables, taskShow };
}

async function main() {
  fs.mkdirSync(output, { recursive: true });
  const verification = path.join(output, 'verification.json');
  if (fs.existsSync(verification)) fs.unlinkSync(verification);

  const executable = requireFile(path.join(bundle, 'Contents/MacOS/FA Foundry'), 'candidate executable');
  const bin = requireFile(path.join(bundle, 'Contents/Resources/foundry/foundry'), 'packaged foundry CLI');
  const appAsar = requireFile(path.join(bundle, 'Contents/Resources/app.asar'), 'packaged app.asar');
  requireFile(path.join(fixtures, 'coa.xlsx'), 'synthetic fixture coa');
  requireFile(path.join(fixtures, 'named.json'), 'synthetic fixture named descriptor');
  const { _electron } = require(playwrightModule);

  const qa = fs.mkdtempSync(path.join(os.tmpdir(), 'finance-ui-section7-pages-'));
  const seed = seedStore(bin, qa);
  const evidence = {
    status: 'running',
    bundle,
    executable,
    output,
    qa,
    fixture: fixtures,
    app: { executableSha256: hashFile(executable), foundrySha256: hashFile(bin), appAsarSha256: hashFile(appAsar) },
    seed: {
      task: seed.task,
      windowId: seed.windowId,
      sessionId,
      exportRow: seed.exportRow,
      deliverableCount: seed.deliverables.length,
    },
    checks: [],
    measures: [],
    assumptions: [
      'seed uses packaged foundry CLI create/import/lock/emit-brief/export only',
      'query-locked/model-provider calls are intentionally not used',
      'exact sha256/window/session identifiers may appear only inside expanded TechnicalInfo blocks',
      'visible preview native view must align exactly to the 44px PreviewBar bottom at every captured viewport',
    ],
  };
  const pass = (name, details = {}) => evidence.checks.push({ name, ok: true, ...details });

  const app = await _electron.launch({
    executablePath: executable,
    args: [`--user-data-dir=${path.join(qa, 'profile')}`],
    env: {
      ...process.env,
      FOUNDRY_VAR: seed.varRoot,
      FOUNDRY_BIN: undefined,
      FOUNDRY_DSH_INSTALL: undefined,
      FOUNDRY_FORMULATOR_BIN: undefined,
      LITELLM_LOCAL_MODEL_COST_MAP: 'True',
    },
    timeout: 45000,
  });

  async function nativePreview() {
    return await app.evaluate(async ({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows()[0];
      if (!win) return null;
      const children = win.contentView.children
        .filter((child) => child.webContents && /^http:\/\/127\.0\.0\.1/.test(child.webContents.getURL()))
        .map((child) => ({
          url: child.webContents.getURL(),
          visible: typeof child.getVisible === 'function' ? child.getVisible() : true,
          bounds: typeof child.getBounds === 'function' ? child.getBounds() : null,
          child,
        }));
      const visible = children.find((entry) => entry.visible && entry.bounds && entry.bounds.width > 0 && entry.bounds.height > 0);
      if (!visible) return { visible: false, candidates: children.map(({ url, visible, bounds }) => ({ url, visible, bounds })) };
      return {
        visible: true,
        url: visible.url,
        bounds: visible.bounds,
        png: (await visible.child.webContents.capturePage()).toPNG().toString('base64'),
        candidates: children.map(({ url, visible, bounds }) => ({ url, visible, bounds })),
      };
    });
  }

  async function capture(page, name, width, height, dark = false) {
    await app.evaluate(({ BrowserWindow, nativeTheme }, value) => {
      nativeTheme.themeSource = value.dark ? 'dark' : 'light';
      BrowserWindow.getAllWindows()[0].setContentSize(value.width, value.height);
    }, { width, height, dark });
    for (const target of app.context().pages()) await target.emulateMedia({ colorScheme: null });
    await page.waitForTimeout(500);
    await page.evaluate(() => document.fonts.ready);
    const image = await app.evaluate(async ({ BrowserWindow }) => (await BrowserWindow.getAllWindows()[0].capturePage()).toPNG().toString('base64'));
    fs.writeFileSync(path.join(output, `${safeName(name)}.png`), Buffer.from(image, 'base64'));
    const native = await nativePreview();
    if (native?.visible && native.png) fs.writeFileSync(path.join(output, `${safeName(name)}-native.png`), Buffer.from(native.png, 'base64'));
    try {
      const mediaSource = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getMediaSourceId());
      const id = mediaSource.split(':')[1];
      execFileSync('/usr/sbin/screencapture', ['-x', '-o', '-l', id, path.join(output, `${safeName(name)}-window.png`)], { stdio: 'pipe', timeout: 5000 });
    } catch (error) {
      evidence.checks.push({ name: `${name}:native-window-screencapture`, ok: false, optional: true, message: String(error.message || error).slice(0, 240) });
    }
    const measurement = await page.evaluate(() => {
      const box = (selector) => {
        const node = document.querySelector(selector);
        const rect = node?.getBoundingClientRect();
        return rect && node.checkVisibility() ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height, bottom: rect.bottom, right: rect.right } : null;
      };
      return {
        viewport: [innerWidth, innerHeight],
        colorScheme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light',
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
        bodyOverflow: document.body.scrollWidth > innerWidth,
        boxes: {
          head: box('.fnd-head'),
          taskbar: box('.fnd-taskbar'),
          column: box('.fnd-column'),
          deliverableStamp: box('.fnd-doc__stamp'),
          technical: box('.analysis-technical'),
          technicalList: box('.analysis-technical-list'),
          taskDetail: box('.fnd-time'),
        },
        shellEmbedded: document.querySelector('.fnd-shell')?.getAttribute('data-embedded') || '',
        screen: document.querySelector('.fnd-shell')?.getAttribute('data-screen') || '',
      };
    });
    assert.equal(measurement.horizontalOverflow, false, `${name} document has no horizontal overflow`);
    assert.equal(measurement.bodyOverflow, false, `${name} body has no horizontal overflow`);
    if (native?.visible) {
      assert.ok(measurement.boxes.head && measurement.boxes.taskbar, `${name} visible preview has app header and PreviewBar`);
      const taskbarHeightDelta = Math.abs(measurement.boxes.taskbar.height - PREVIEW_BAR_HEIGHT);
      const nativeDelta = Math.abs(native.bounds.y - measurement.boxes.taskbar.bottom);
      assert.ok(taskbarHeightDelta <= GEOMETRY_TOLERANCE, `${name} PreviewBar height is 44px ± ${GEOMETRY_TOLERANCE}px`);
      assert.ok(nativeDelta <= GEOMETRY_TOLERANCE, `${name} native preview y equals PreviewBar bottom`);
      pass(`${name}:preview-native-flush-with-44px-bar`, {
        taskbar: measurement.boxes.taskbar,
        nativeBounds: native.bounds,
        taskbarHeightDelta,
        nativeDelta,
      });
    }
    evidence.measures.push({ name, width, height, dark, native: native && { visible: native.visible, url: native.url, bounds: native.bounds, candidates: native.candidates }, ...measurement });
    writeJson(verification, evidence);
    return { measurement, native };
  }

  async function visibleText(page, selector = 'body') {
    return await page.locator(selector).innerText({ timeout: 5000 });
  }

  async function assertIdentifierOnlyInTechnical(page, identifier, label) {
    const leaks = await page.evaluate((id) => {
      const rows = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let node = walker.nextNode();
      while (node) {
        const text = node.nodeValue || '';
        if (text.includes(id)) {
          const parent = node.parentElement;
          const rect = parent?.getBoundingClientRect();
          const visible = Boolean(parent && rect && rect.width > 0 && rect.height > 0 && getComputedStyle(parent).visibility !== 'hidden' && getComputedStyle(parent).display !== 'none');
          if (visible) rows.push({ text, tag: parent.tagName, classes: parent.className, technical: Boolean(parent.closest('.analysis-technical')) });
        }
        node = walker.nextNode();
      }
      return rows;
    }, identifier);
    const outside = leaks.filter((row) => !row.technical);
    assert.deepEqual(outside, [], `${label} appears only inside TechnicalInfo`);
    assert.ok(leaks.length > 0, `${label} is visible after TechnicalInfo opens`);
    pass(`${label}:exact-id-only-in-technical`, { visibleTextNodes: leaks.length });
  }

  async function assertTechnicalClosed(page, scope, label) {
    const details = page.locator(scope).locator('.analysis-technical').first();
    await details.waitFor({ timeout: 10000 });
    assert.equal(await details.evaluate((node) => node.hasAttribute('open')), false, `${label} TechnicalInfo defaults collapsed`);
    pass(`${label}:technical-default-collapsed`);
    return details;
  }

  async function openPreviewAndCheck(page, openButton, label) {
    const before = await page.locator('.fnd-column').boundingBox();
    await openButton.click();
    await page.getByText('表格预览').waitFor({ timeout: 45000 });
    await page.getByRole('button', { name: '关闭预览' }).waitFor({ timeout: 10000 });
    await page.waitForFunction(async () => {
      const status = await window.foundry.previewStatus();
      return status.ok && status.value.running;
    }, undefined, { timeout: 45000 });
    await page.waitForTimeout(800);

    const barDetails = await assertTechnicalClosed(page, '.fnd-taskbar', `${label}:previewbar`);
    assert.equal((await visibleText(page, '.fnd-taskbar')).includes(seed.exportRow.sha256), false, `${label} previewbar hides exact sha while collapsed`);
    pass(`${label}:previewbar-collapsed-hides-exact-sha`);

    const preview1280 = await capture(page, `${label}-preview-light-1280`, 1280, 800, false);
    const native = preview1280.native;
    assert.ok(native?.visible, `${label} preview native view is visible`);
    const boxes = preview1280.measurement.boxes;
    assert.ok(boxes.head && boxes.taskbar, `${label} has app header and preview bar`);
    assert.ok(Math.abs(boxes.taskbar.height - PREVIEW_BAR_HEIGHT) <= GEOMETRY_TOLERANCE, `${label} PreviewBar height is 44px ± ${GEOMETRY_TOLERANCE}px`);
    assert.ok(Math.abs(native.bounds.y - boxes.taskbar.bottom) <= GEOMETRY_TOLERANCE, `${label} native view y equals PreviewBar bottom`);
    assert.ok(native.bounds.height > 160 && native.bounds.width > 600, `${label} native preview has useful bounds`);
    pass(`${label}:native-flush-with-44px-previewbar`, { nativeBounds: native.bounds, head: boxes.head, taskbar: boxes.taskbar });

    await barDetails.locator('summary').click();
    await page.waitForTimeout(250);
    await assertIdentifierOnlyInTechnical(page, seed.exportRow.sha256, `${label}:preview-sha`);
    const overlay = await page.locator('.fnd-taskbar .analysis-technical-list').boundingBox();
    const expandedNative = await nativePreview();
    const stripAfterOpen = await page.locator('.fnd-taskbar').boundingBox();
    const overlayHit = await page.evaluate(() => {
      const node = document.querySelector('.fnd-taskbar .analysis-technical-list');
      const rect = node?.getBoundingClientRect();
      if (!node || !rect) return null;
      const hit = document.elementFromPoint(rect.left + Math.min(24, rect.width / 2), rect.top + Math.min(18, rect.height / 2));
      return { hitInsidePanel: Boolean(hit?.closest('.analysis-technical-list')), hitTag: hit?.tagName ?? '', hitClass: hit?.className ?? '' };
    });
    const retainedPreview = expandedNative?.candidates?.find((item) => item.url === native.url) ?? null;
    assert.ok(overlay, `${label} preview technical popover is measurable`);
    assert.ok(stripAfterOpen, `${label} preview strip is measurable after TechnicalInfo opens`);
    assert.ok(retainedPreview, `${label} native preview view is retained after TechnicalInfo opens`);
    assert.equal(retainedPreview.visible, false, `${label} native preview view is hidden while TechnicalInfo is open`);
    assert.equal(Boolean(expandedNative?.visible), false, `${label} no visible native preview covers the TechnicalInfo panel`);
    assert.ok(overlay.y >= stripAfterOpen.y + stripAfterOpen.height - 1, `${label} preview technical popover starts below the PreviewBar`);
    assert.equal(overlayHit?.hitInsidePanel, true, `${label} preview technical popover receives DOM hit testing`);
    pass(`${label}:preview-technical-not-obscured`, { overlay, retainedPreview, strip: stripAfterOpen, overlayHit });

    await barDetails.locator('summary').click();
    let restoredNative = null;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      await page.waitForTimeout(250);
      const candidate = await nativePreview();
      if (candidate?.visible && JSON.stringify(candidate.bounds) === JSON.stringify(native.bounds)) {
        restoredNative = candidate;
        break;
      }
    }
    assert.ok(restoredNative?.visible && restoredNative.bounds, `${label} native preview view is visible after TechnicalInfo closes`);
    assert.deepEqual(restoredNative.bounds, native.bounds, `${label} native preview bounds restore after TechnicalInfo closes`);
    pass(`${label}:preview-native-restored-after-technical-collapse`, { nativeBounds: restoredNative.bounds });

    await capture(page, `${label}-preview-dark-1280`, 1280, 800, true);
    await capture(page, `${label}-preview-light-1080`, 1080, 760, false);
    await capture(page, `${label}-preview-dark-1080`, 1080, 760, true);

    await page.getByRole('button', { name: '关闭预览' }).click();
    await page.waitForFunction(async () => {
      const status = await window.foundry.previewStatus();
      return status.ok && !status.value.running;
    }, undefined, { timeout: 15000 });
    await page.waitForTimeout(500);
    const afterNative = await nativePreview();
    assert.equal(Boolean(afterNative?.visible), false, `${label} native preview hidden after close`);
    await expectAbsent(page, '.fnd-taskbar', `${label} PreviewBar gone after close`);
    const after = await page.evaluate(() => {
      const column = document.querySelector('.fnd-column')?.getBoundingClientRect();
      const shell = document.querySelector('.fnd-shell');
      const visibleButtons = Array.from(document.querySelectorAll('button')).filter((button) => {
        const rect = button.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && rect.bottom >= 0 && rect.top <= innerHeight;
      }).map((button) => button.textContent?.trim() || button.getAttribute('aria-label') || '').filter(Boolean).slice(0, 12);
      return {
        column: column ? { x: column.x, y: column.y, width: column.width, height: column.height, bottom: column.bottom } : null,
        embedded: shell?.getAttribute('data-embedded') || '',
        screen: shell?.getAttribute('data-screen') || '',
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
        visibleButtons,
      };
    });
    assert.ok(before && after.column, `${label} column bounds measurable around preview close`);
    assert.equal(after.embedded, 'no', `${label} shell leaves embedded preview mode after close`);
    assert.equal(after.horizontalOverflow, false, `${label} main page has no horizontal overflow after preview close`);
    assert.ok(after.visibleButtons.length > 0, `${label} main page controls are visible after preview close`);
    pass(`${label}:preview-close-restores-boundary`, { before, after });
  }

  async function expectAbsent(page, selector, label) {
    const count = await page.locator(selector).count();
    assert.equal(count, 0, label);
    pass(label);
  }

  try {
    const page = await app.firstWindow();
    await page.waitForLoadState('domcontentloaded');
    await page.locator('.workspace-header').waitFor({ timeout: 45000 });
    await page.waitForFunction(() => document.fonts.check('500 14px "Noto Sans SC"'), undefined, { timeout: 30000 });
    pass('packaged-electron-started');

    await page.getByRole('button', { name: '成果库' }).click();
    await page.getByRole('button', { name: `打开 ${title} 的导出件 第 ${seed.exportRow.seq} 版` }).click();
    await page.getByText('这一版是 Excel 工作簿').waitFor({ timeout: 15000 });
    assert.ok((await visibleText(page)).includes(title), 'deliverable page shows seeded task title');
    assert.equal((await visibleText(page)).includes(seed.exportRow.sha256), false, 'deliverable open hides exact sha before TechnicalInfo expands');
    const deliverableTech = await assertTechnicalClosed(page, '.fnd-column', 'deliverable-open');
    await capture(page, 'deliverables-open-light-1280', 1280, 800, false);
    await deliverableTech.locator('summary').click();
    await assertIdentifierOnlyInTechnical(page, seed.exportRow.sha256, 'deliverable-open-sha');
    await assertIdentifierOnlyInTechnical(page, sessionId, 'deliverable-open-session-id');
    pass('deliverables-open-uses-real-archived-workbook', { sha256: seed.exportRow.sha256, seq: seed.exportRow.seq });

    await openPreviewAndCheck(page, page.getByRole('button', { name: /在这里预览/ }), 'deliverables');

    await page.getByRole('button', { name: '工作区' }).click();
    await page.locator('.workspace-header').waitFor({ timeout: 10000 });
    const taskMenu = page.getByRole('button', { name: '任务工具' });
    await taskMenu.click();
    await page.getByRole('menuitem', { name: '任务记录与旧版流程' }).click();
    await page.getByRole('heading', { name: title }).waitFor({ timeout: 15000 });
    await page.getByText('窗口链').waitFor({ timeout: 10000 });
    await page.getByText('交付物版本').waitFor({ timeout: 10000 });
    await capture(page, 'task-detail-light-1280', 1280, 800, false);
    const taskText = await visibleText(page);
    assert.equal(taskText.includes(seed.windowId), false, 'task detail hides exact window id before TechnicalInfo expands');
    assert.equal(taskText.includes(seed.exportRow.sha256), false, 'task detail hides exact sha before TechnicalInfo expands');
    pass('task-detail-hides-identifiers-while-folded');

    const taskTechnicals = page.locator('.analysis-technical');
    const technicalCount = await taskTechnicals.count();
    assert.ok(technicalCount >= 3, 'task detail exposes multiple TechnicalInfo blocks');
    for (let i = 0; i < technicalCount; i += 1) {
      assert.equal(await taskTechnicals.nth(i).evaluate((node) => node.hasAttribute('open')), false, `task TechnicalInfo ${i} defaults folded`);
    }
    pass('task-detail-all-technical-info-default-collapsed', { count: technicalCount });
    await taskTechnicals.nth(0).locator('summary').click();
    await assertIdentifierOnlyInTechnical(page, seed.windowId, 'task-detail-window-id');
    await taskTechnicals.nth(technicalCount - 1).locator('summary').click();
    await assertIdentifierOnlyInTechnical(page, sessionId, 'task-detail-session-id');
    await assertIdentifierOnlyInTechnical(page, seed.exportRow.sha256, 'task-detail-version-sha');
    await page.getByRole('button', { name: `预览第 ${seed.exportRow.seq} 版交付物` }).waitFor({ timeout: 10000 });

    await openPreviewAndCheck(page, page.getByRole('button', { name: `预览第 ${seed.exportRow.seq} 版交付物` }), 'task-detail');

    evidence.status = 'passed';
    writeJson(verification, evidence);
    await app.close();
    console.log(`Section 7 page verification passed. Evidence: ${output}`);
  } catch (error) {
    evidence.status = 'failed';
    evidence.error = error && error.stack ? error.stack : String(error);
    writeJson(verification, evidence);
    try { await app.close(); } catch {}
    throw error;
  }
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
