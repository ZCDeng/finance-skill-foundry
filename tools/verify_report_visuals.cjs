#!/usr/bin/env node
// Real Electron acceptance for reportVisual. Uses only synthetic task data/profile.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { execFileSync, execFile } = require('node:child_process');
const { createHash } = require('node:crypto');
const { inflateRawSync } = require('node:zlib');
const { createRequire } = require('node:module');

const repo = path.resolve(__dirname, '..');
const appRoot = path.join(repo, 'app');
const requireFromHere = createRequire(__filename);

if (process.env.REPORT_VISUAL_EXPORT_HELPER === '1') {
  runElectronHelper().catch((error) => {
    console.error(error && error.stack ? error.stack : String(error));
    try { require('electron').app.exit(1); } catch {}
    process.exit(1);
  });
} else {
  main().catch((error) => {
    console.error(error && error.stack ? error.stack : String(error));
    process.exit(1);
  });
}

async function main() {
  const bundle = path.resolve(process.env.UI_APP_BUNDLE || '/Applications/FA Foundry.app');
  const evidenceDir = path.resolve(process.env.UI_EVIDENCE_DIR || path.join(repo, 'build/report-visuals/current'));
  const checksRequested = new Set(String(process.env.UI_REPORT_VISUAL_CHECKS || 'render,fixture,ui,exports').split(',').map((x) => x.trim()).filter(Boolean));
  const qa = fs.mkdtempSync('/tmp/finance-report-visuals-');
  const varRoot = path.join(qa, 'var');
  const profile = path.join(qa, 'profile');
  const outDir = path.join(evidenceDir, 'outputs');
  fs.rmSync(evidenceDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });

  const bundleInfo = bundlePaths(bundle);
  const moduleInfo = resolveReportModules(bundleInfo, evidenceDir);
  const checks = [];
  const failures = [];
  const notes = [];
  const check = (name, ok, detail = {}) => {
    const row = { name, ok: Boolean(ok), ...detail };
    checks.push(row);
    if (!ok) failures.push(row);
  };

  requireFile(moduleInfo.converters, 'compiled converters.js');
  requireFile(moduleInfo.format, 'compiled format.js');
  requireFile(moduleInfo.visuals, 'compiled visuals.js');
  requireFile(moduleInfo.visualRaster, 'compiled visual-raster.js');
  requireFile(moduleInfo.visualEvidence, 'compiled visual-evidence.js');
  check('compiled-report-visual-modules-present', true, moduleInfo);

  if (checksRequested.has('render')) {
    const standaloneJob = path.join(qa, 'standalone-render-job.json');
    fs.writeFileSync(standaloneJob, JSON.stringify({
      mode: 'standalone-render',
      modules: moduleInfo,
      output: path.join(evidenceDir, 'standalone-render'),
      fonts: fontPaths(bundleInfo),
      helperUserData: path.join(qa, 'helper-profile'),
    }, null, 2));
    const result = JSON.parse(runElectronHelperJob(standaloneJob));
    check('standalone-render-screenshots-produced', result.screenshots.length === 4 && result.figureScreenshots.length >= 3, { screenshots: result.screenshots, figureScreenshots: result.figureScreenshots });
    check('standalone-docx-rasterizes-visuals', result.docx.media.length >= 3 && result.docx.hasPngMedia && result.docx.pngDimensionsOk && result.docx.identityReceiptOk && !result.docx.identityLeakOutsideReceipt, result.docx);
    check('standalone-pdf-raster-pages-visible', result.pdf.pages >= 1 && result.pdf.missing.length === 0 && result.pdf.raster?.pages?.length >= 1 && result.pdf.raster.pages.every((page) => page.hasContent && !page.touchesEdge), result.pdf);
    check('standalone-direct-docx-rejects-visual-node', result.directDocxRejected === true, { message: result.directDocxRejectMessage });
    check('standalone-render-text-preserved', missing(result.text, ['长中文标题用于窄屏截断检查', '流程图 · 审批链路', '123456789.987654', '缺失']).length === 0, { textSha256: sha256(Buffer.from(result.text, 'utf8')) });
  }

  let manifest;
  if (checksRequested.has('fixture') || checksRequested.has('ui') || checksRequested.has('exports')) {
    const foundry = foundryCommand(bundleInfo);
    assertCommand(foundry.bin, 'Foundry CLI binary');
    const seeded = JSON.parse(execFileSync('python3', [path.join(repo, 'tools/report_visual_fixture.py'), '--foundry-bin', foundry.bin, '--foundry-prefix', JSON.stringify(foundry.prefix), '--var-root', varRoot, '--out-dir', evidenceDir], { encoding: 'utf8', cwd: repo }));
    manifest = JSON.parse(fs.readFileSync(seeded.manifest, 'utf8'));
    check('fixture-seeded-real-task-draft', /^[0-9a-f]{32}$/.test(manifest.task_id) && /^[0-9a-f]{32}$/.test(manifest.draft_id), { taskId: manifest.task_id, draftId: manifest.draft_id });
    const bar = manifest.saved_visuals.find((row) => row.kind === 'bar');
    const line = manifest.saved_visuals.find((row) => row.kind === 'line');
    check('fixture-server-overwrites-forged-proof', bar && bar.source_label !== '伪造来源必须被覆盖' && JSON.stringify(bar.series).includes('华东') && !JSON.stringify(bar.series).includes('999999'), { sourceLabel: bar?.source_label });
    check('fixture-line-preserves-missing-value', line && line.series.rows.some((row) => row['现金流'] === null), { rows: line?.series?.rows });
  }

  if (checksRequested.has('exports')) {
    const exportResult = await verifyExports({ bundleInfo, moduleInfo, varRoot, outDir, manifest });
    for (const row of exportResult.checks) check(row.name, row.ok, row.detail);
  }

  if (checksRequested.has('ui')) {
    const uiResult = await verifyRealUi({ bundleInfo, evidenceDir, varRoot, profile, manifest });
    for (const row of uiResult.checks) check(row.name, row.ok, row.detail);
  }

  const evidence = {
    status: failures.length ? 'failed' : 'passed',
    synthetic: true,
    providerCalls: 0,
    bundle,
    appAsarSha256: fs.existsSync(bundleInfo.appAsar) ? hashFile(bundleInfo.appAsar) : null,
    moduleInfo,
    checksRequested: [...checksRequested],
    qa,
    varRoot,
    profile,
    evidenceDir,
    manifest: manifest ? { task_id: manifest.task_id, draft_id: manifest.draft_id, task_title: manifest.task_title, draft_title: manifest.draft_title } : null,
    checks,
    failures,
    notes,
    assumptions: [
      'Fixture is seeded through packaged Foundry CLI into an isolated FOUNDRY_VAR.',
      'Numeric reportVisual nodes are saved unresolved and materialized by the server from chart_id; fake proof fields are checked as overwritten.',
      'DOCX export first materializes reportVisual nodes to PNG through visual-raster before calling converter exportDocx.',
      'No model/provider request is made by this script.',
    ],
  };
  fs.writeFileSync(path.join(evidenceDir, 'verification.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify({ status: evidence.status, checks: checks.length, failed: failures.length, evidenceDir, verification: path.join(evidenceDir, 'verification.json') }, null, 2));
  if (failures.length) process.exitCode = 1;
}

async function verifyExports({ bundleInfo, moduleInfo, varRoot, outDir, manifest }) {
  const checks = [];
  const check = (name, ok, detail = {}) => checks.push({ name, ok: Boolean(ok), detail });
  const foundry = foundryCommand(bundleInfo);
  const cli = (command, args) => JSON.parse(execFileSync(foundry.bin, [...foundry.prefix, '--var', varRoot, '--task', manifest.task_id, command, ...args], { encoding: 'utf8', cwd: repo }));
  const md = cli('analysis-export', ['--draft', manifest.draft_id, '--format', 'md']);
  const xlsx = cli('analysis-export', ['--draft', manifest.draft_id, '--format', 'xlsx']);
  const mdPath = path.join(outDir, 'report.md');
  const xlsxPath = path.join(outDir, 'report.xlsx');
  fs.copyFileSync(md.path, mdPath);
  fs.copyFileSync(xlsx.path, xlsxPath);
  const mdText = fs.readFileSync(mdPath, 'utf8');
  check('markdown-fallback-includes-data-and-flow', missing(mdText, ['单位：万元', '| 项目 | 本期 | 预算 |', '解释流程（作者分析，不是计算证据）', '缺失']).length === 0, { path: mdPath, sha256: hashFile(mdPath) });

  const helperJob = path.join(path.dirname(outDir), 'export-helper-job.json');
  fs.writeFileSync(helperJob, JSON.stringify({
    mode: 'export-draft',
    modules: moduleInfo,
    output: outDir,
    fonts: fontPaths(bundleInfo),
    helperUserData: path.join(path.dirname(outDir), 'helper-profile'),
    draft: manifest.draft,
  }, null, 2));
  const helper = JSON.parse(runElectronHelperJob(helperJob));
  check('html-export-contains-controlled-svg', helper.html.svgCount >= 3 && helper.html.missing.length === 0 && helper.html.forbidden.length === 0, helper.html);
  check('export-figure-screenshots-produced', Array.isArray(helper.figureScreenshots) && helper.figureScreenshots.length >= 3 && helper.figureScreenshots.every((shot) => shot.metrics?.svgCount >= 1 && shot.metrics?.overflow === false), { figureScreenshots: helper.figureScreenshots });
  check('pdf-export-renders-report-visual-text', helper.pdf.pages >= 1 && helper.pdf.missing.length === 0, helper.pdf);
  check('pdf-export-raster-pages-visible', helper.pdf.raster?.pages?.length >= 1 && helper.pdf.raster.pages.every((page) => page.hasContent && !page.touchesEdge), helper.pdf.raster);
  check('docx-export-uses-rasterized-png', helper.docx.hasPngMedia && helper.docx.media.length >= 3 && helper.docx.missingVisualNodeRejection === true && helper.docx.pngDimensionsOk && helper.docx.identityReceiptOk && !helper.docx.identityLeakOutsideReceipt, helper.docx);
  const xlsxInspection = inspectXlsx(xlsxPath);
  check('xlsx-export-native-charts-and-exact-data', xlsxInspection.chartCount >= 2 && xlsxInspection.missing.length === 0, xlsxInspection);
  return { checks };
}

async function verifyRealUi({ bundleInfo, evidenceDir, varRoot, profile, manifest }) {
  const checks = [];
  const check = (name, ok, detail = {}) => checks.push({ name, ok: Boolean(ok), detail });
  const playwrightModule = process.env.PLAYWRIGHT_MODULE || 'playwright';
  const { _electron } = requireFromHere(playwrightModule);
  const executable = requireFile(bundleInfo.executable, 'Electron executable');
  let app;
  try {
    app = await _electron.launch({
      executablePath: executable,
      args: [`--user-data-dir=${profile}`],
      env: { ...process.env, FOUNDRY_VAR: varRoot, FOUNDRY_BIN: undefined, FOUNDRY_DSH_INSTALL: undefined, FOUNDRY_FORMULATOR_BIN: undefined },
      timeout: 60000,
    });
    const page = await app.firstWindow();
    await page.waitForLoadState('domcontentloaded');
    await page.locator('.workspace-header').waitFor({ timeout: 45000 });
    await page.waitForFunction(async () => {
      const result = await window.foundry?.harnessStatus?.();
      return result?.ok && result.value?.wiring?.state === 'ready';
    }, undefined, { timeout: 60000 });
    await ensureSidebar(page);
    await page.locator('.workspace-task').filter({ hasText: manifest.task_title }).first().click();
    await page.locator('.workspace-title').filter({ hasText: manifest.task_title }).waitFor({ timeout: 30000 });
    await revealReport(page, manifest);
    await page.locator('.report-reading, .report-prosemirror, .analysis-draft').first().waitFor({ timeout: 30000 });
    const reading = await collectVisualDom(page);
    check('ui-reading-shows-three-report-visuals', reading.svgCount >= 3 && reading.missing.length === 0, reading);

    const variantResults = await captureVariants(app, page, evidenceDir, 'report-visual-reading');
    const themeChanged = variantResults.some((row) => row.colorScheme === 'dark' && row.themeLooksDark)
      && variantResults.some((row) => row.colorScheme === 'light' && row.themeLooksLight);
    check('ui-theme-variants-no-overflow', variantResults.every((row) => row.overflow === false && row.themeMatches) && themeChanged, { variants: variantResults, themeChanged });

    const flowTakeaway = `流程图已通过桌面验收编辑路径更新 ${Date.now()}`;
    await editFlowVisualStrict(page, flowTakeaway);
    await insertReportVisualFromComposer(page, { kind: 'bar', title: '桌面验收插入条形图', sourceValue: `chart:${manifest.bar.chart_id}`, sourceNeedle: '区域预算差异', categoryNeedle: '项目', valueNeedles: ['本期'], unit: '万元' });
    await insertReportVisualFromComposer(page, { kind: 'line', title: '桌面验收插入折线图', sourceValue: `chart:${manifest.line.chart_id}`, sourceNeedle: '月度现金流', categoryNeedle: '月份', valueNeedles: ['现金流'], unit: '万元' });
    const edited = await collectVisualDom(page);
    check('ui-composer-inserts-bar-line-and-edits-flow-before-save', edited.visualEditButtons >= 5 && edited.text.includes(flowTakeaway) && edited.text.includes('桌面验收插入条形图') && edited.text.includes('桌面验收插入折线图'), edited);
    await saveDraftStrict(page);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('.workspace-header').waitFor({ timeout: 45000 });
    await ensureSidebar(page);
    await page.locator('.workspace-task').filter({ hasText: manifest.task_title }).first().click();
    await revealReport(page, manifest);
    const after = await collectVisualDom(page);
    check('ui-save-reopen-keeps-edited-and-inserted-report-visuals', after.svgCount >= 5 && after.visualFigures >= 5 && after.text.includes(flowTakeaway) && after.text.includes('桌面验收插入条形图') && after.text.includes('桌面验收插入折线图'), after);
  } catch (error) {
    if (app) await captureFailure(app, evidenceDir, 'ui-failure').catch(() => {});
    check('ui-report-visual-flow', false, { message: error && error.stack ? error.stack : String(error) });
  } finally {
    if (app) await app.close().catch(() => {});
  }
  return { checks };
}

async function ensureSidebar(page) {
  const open = await page.evaluate(() => document.querySelector('.workspace')?.getAttribute('data-sidebar') === 'open').catch(() => false);
  if (open) return;
  const toggle = page.locator('.workspace-header button[title="任务列表"], .workspace-header button[aria-label="展开任务列表"]').first();
  if (await toggle.isVisible({ timeout: 5000 }).catch(() => false)) await toggle.click();
  await page.waitForFunction(() => document.querySelector('.workspace')?.getAttribute('data-sidebar') === 'open', undefined, { timeout: 30000 }).catch(() => {});
}

async function revealReport(page, manifest) {
  // 文稿 sits under the 汇报 step.
  const reportStep = page.getByRole('tab', { name: /汇报/ }).first();
  if (await reportStep.isVisible({ timeout: 5000 }).catch(() => false)) await reportStep.click();
  const documentTab = page.getByRole('tab', { name: /文稿/ }).first();
  if (await documentTab.isVisible({ timeout: 5000 }).catch(() => false)) await documentTab.click();
  else {
    const button = page.getByRole('button', { name: /文稿|成果专注|工作区/ }).first();
    if (await button.isVisible({ timeout: 5000 }).catch(() => false)) await button.click();
  }
  await page.waitForFunction((title) => {
    const text = document.body.innerText || '';
    return text.includes(title) || Boolean(document.querySelector('.report-reading, .report-prosemirror, .analysis-draft, [aria-label="文稿阅读"], [aria-label="可视化文稿编辑器"]'));
  }, manifest.draft_title, { timeout: 30000 });
  const read = page.getByRole('tab', { name: /^阅读$/ }).first();
  if (await read.isVisible({ timeout: 5000 }).catch(() => false)) await read.click();
}

async function collectVisualDom(page) {
  return await page.evaluate((needles) => {
    const text = document.body.innerText || '';
    return {
      text,
      svgCount: document.querySelectorAll('.report-visual svg, .report-visual-node svg').length,
      visualFigures: document.querySelectorAll('.report-visual, .report-visual-node').length,
      visualEditButtons: [...document.querySelectorAll('button')].filter((button) => (button.getAttribute('aria-label') || button.textContent || '').includes('编辑图表')).length,
      missing: needles.filter((needle) => !text.includes(needle)),
      overflow: document.documentElement.scrollWidth > window.innerWidth + 2,
    };
  }, ['区域预算差异', '月度现金流趋势', '预算复核流程']);
}

async function editFlowVisualStrict(page, takeawayText) {
  await openEditorTab(page);
  const button = page.getByRole('button', { name: /编辑图表：.*(预算复核流程|审批链路|流程)|编辑图表：预算复核流程/ }).last();
  await button.waitFor({ timeout: 15000 });
  await button.click();
  await page.getByRole('heading', { name: '编辑图表' }).waitFor({ timeout: 10000 });
  await page.getByLabel('图表结论').fill(takeawayText);
  await page.getByRole('button', { name: '更新图表' }).click();
  await page.waitForFunction((needle) => (document.body.innerText || '').includes(needle), takeawayText, { timeout: 15000 });
  await moveEditorCursorToEnd(page);
}

async function insertReportVisualFromComposer(page, spec) {
  await openEditorTab(page);
  await moveEditorCursorToEnd(page);
  await page.getByRole('button', { name: '插入图表' }).click();
  await page.getByRole('heading', { name: '插入图表' }).waitFor({ timeout: 10000 });
  await page.getByLabel('图表类型').selectOption(spec.kind);
  await page.getByLabel('图表标题').fill(spec.title);
  await selectOptionValueOrText(page.getByLabel('图表数据'), spec.sourceValue, spec.sourceNeedle);
  await page.getByLabel('类别列').waitFor({ timeout: 15000 });
  await selectOptionContaining(page.getByLabel('类别列'), spec.categoryNeedle);
  await chooseValueColumns(page, spec.valueNeedles);
  await page.getByLabel('图表单位').fill(spec.unit);
  await page.getByLabel('图表预览').locator('svg').waitFor({ timeout: 15000 });
  await page.getByRole('button', { name: '插入文稿' }).click();
  await page.getByRole('button', { name: `编辑图表：${spec.title}` }).waitFor({ timeout: 15000 });
}



async function moveEditorCursorToEnd(page) {
  await page.evaluate(() => {
    const editor = document.querySelector('.ProseMirror');
    if (!editor) throw new Error('ProseMirror editor not found');
    editor.focus();
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    selection?.removeAllRanges();
    selection?.addRange(range);
  });
}

async function chooseValueColumns(page, preferredNeedles) {
  const labels = await page.locator('.report-visual-composer__series label').evaluateAll((rows) => rows.map((label) => ({ text: label.textContent || '', disabled: Boolean(label.querySelector('input')?.disabled) })));
  const chosen = [];
  for (const needle of preferredNeedles) {
    const exact = labels.find((row) => !row.disabled && row.text.includes(needle));
    if (exact) chosen.push(exact.text.trim());
  }
  if (!chosen.length) {
    const fallback = labels.find((row) => !row.disabled && row.text.trim());
    if (fallback) chosen.push(fallback.text.trim());
  }
  if (!chosen.length) throw new Error(`no enabled value columns available: ${JSON.stringify(labels)}`);
  for (const label of chosen.slice(0, 1)) {
    await page.getByLabel(new RegExp(`数值列\\s+${escapeRegExp(label)}`)).check();
  }
}

async function selectOptionValueOrText(locator, value, needle) {
  await locator.waitFor({ timeout: 15000 });
  const selected = await locator.evaluate(async (select, input) => {
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      const options = [...select.options];
      const exact = input.value ? options.find((row) => row.value === input.value) : null;
      const textual = input.needle ? options.find((row) => row.value && row.textContent?.includes(input.needle)) : null;
      const option = exact || textual;
      if (option) return option.value;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error(`no selectable option for ${input.value || input.needle}; options=${[...select.options].map((row) => `${row.value}:${row.textContent}`).join('|')}`);
  }, { value, needle });
  await locator.selectOption(selected);
}

async function selectOptionContaining(locator, needle) {
  await selectOptionValueOrText(locator, undefined, needle);
}

async function openEditorTab(page) {
  const editTab = page.getByRole('tab', { name: /^编辑$/ }).first();
  await editTab.waitFor({ timeout: 10000 });
  await editTab.click();
  await page.getByLabel('可视化文稿编辑器').waitFor({ timeout: 15000 });
}

async function saveDraftStrict(page) {
  const save = page.getByRole('button', { name: '保存文稿新版' }).first();
  await save.waitFor({ timeout: 15000 });
  await save.click();
  await page.waitForFunction(() => !(document.body.innerText || '').includes('正在'), undefined, { timeout: 30000 });
}

async function captureVariants(app, page, evidenceDir, prefix) {
  const results = [];
  const variants = [
    { requestedName: 'light-1280', requestedWidth: 1280, height: 820, colorScheme: 'light' },
    { requestedName: 'dark-1280', requestedWidth: 1280, height: 820, colorScheme: 'dark' },
    { requestedName: 'light-narrow-request900', requestedWidth: 900, height: 760, colorScheme: 'light' },
    { requestedName: 'dark-narrow-request900', requestedWidth: 900, height: 760, colorScheme: 'dark' },
  ];
  for (const variant of variants) {
    await page.emulateMedia({ colorScheme: variant.colorScheme });
    await app.evaluate(({ BrowserWindow, nativeTheme }, v) => {
      nativeTheme.themeSource = v.colorScheme;
      BrowserWindow.getAllWindows()[0].setContentSize(v.requestedWidth, v.height);
    }, variant);
    await page.waitForFunction((scheme) => {
      const value = getComputedStyle(document.documentElement).getPropertyValue('--fnd-bg').trim();
      const luminance = cssColorLuminance(value);
      if (!Number.isFinite(luminance)) return false;
      return scheme === 'dark' ? luminance < 0.2 : luminance > 0.8;
      function cssColorLuminance(input) {
        const raw = String(input || '').trim();
        let rgb = null;
        const hex = raw.match(/^#([0-9a-f]{3}|[0-9a-f]{6})([0-9a-f]{2})?$/i);
        if (hex) {
          const body = hex[1].length === 3 ? hex[1].split('').map((ch) => ch + ch).join('') : hex[1];
          rgb = [parseInt(body.slice(0, 2), 16), parseInt(body.slice(2, 4), 16), parseInt(body.slice(4, 6), 16)];
        } else {
          const match = raw.match(/rgba?\(([^)]+)\)/i);
          if (match) rgb = match[1].split(',').slice(0, 3).map((part) => Number(part.trim()));
        }
        if (!rgb || rgb.some((v) => !Number.isFinite(v))) return NaN;
        const channel = (v) => {
          const srgb = v / 255;
          return srgb <= 0.03928 ? srgb / 12.92 : Math.pow((srgb + 0.055) / 1.055, 2.4);
        };
        return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
      }
    }, variant.colorScheme, { timeout: 10000 });
    await page.waitForTimeout(250);
    await page.evaluate(() => document.querySelector('.report-visual, .report-visual-node')?.scrollIntoView({ block: 'center' }));
    const metrics = await page.evaluate(() => {
      const root = getComputedStyle(document.documentElement);
      const body = getComputedStyle(document.body);
      const visual = document.querySelector('.report-visual, .report-visual-node');
      const visualStyle = visual ? getComputedStyle(visual) : null;
      const fndBg = root.getPropertyValue('--fnd-bg').trim();
      const bodyBg = body.backgroundColor;
      const visualBg = visualStyle?.backgroundColor || '';
      const fndBgLuminance = cssColorLuminance(fndBg);
      const bodyBgLuminance = cssColorLuminance(bodyBg);
      const visualBgLuminance = cssColorLuminance(visualBg);
      return {
        actualWidth: innerWidth,
        actualHeight: innerHeight,
        scrollWidth: document.documentElement.scrollWidth,
        overflow: document.documentElement.scrollWidth > innerWidth + 2,
        fndBg,
        bodyBg,
        visualBg,
        fndBgLuminance,
        bodyBgLuminance,
        visualBgLuminance,
        themeLooksDark: fndBgLuminance < 0.2,
        themeLooksLight: fndBgLuminance > 0.8,
      };
      function cssColorLuminance(input) {
        const raw = String(input || '').trim();
        if (!raw || raw === 'transparent') return NaN;
        let rgb = null;
        const hex = raw.match(/^#([0-9a-f]{3}|[0-9a-f]{6})([0-9a-f]{2})?$/i);
        if (hex) {
          const body = hex[1].length === 3 ? hex[1].split('').map((ch) => ch + ch).join('') : hex[1];
          rgb = [parseInt(body.slice(0, 2), 16), parseInt(body.slice(2, 4), 16), parseInt(body.slice(4, 6), 16)];
        } else {
          const match = raw.match(/rgba?\(([^)]+)\)/i);
          if (match) rgb = match[1].split(',').slice(0, 3).map((part) => Number(part.trim()));
        }
        if (!rgb || rgb.some((v) => !Number.isFinite(v))) return NaN;
        const channel = (v) => {
          const srgb = v / 255;
          return srgb <= 0.03928 ? srgb / 12.92 : Math.pow((srgb + 0.055) / 1.055, 2.4);
        };
        return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
      }
    });
    const actualName = `${prefix}-${variant.colorScheme}-${metrics.actualWidth}`;
    await captureFailure(app, evidenceDir, actualName);
    results.push({
      requestedName: variant.requestedName,
      requestedWidth: variant.requestedWidth,
      requestedHeight: variant.height,
      colorScheme: variant.colorScheme,
      screenshot: `${actualName}.png`,
      themeMatches: variant.colorScheme === 'dark' ? metrics.themeLooksDark : metrics.themeLooksLight,
      ...metrics,
    });
  }
  await page.emulateMedia({ colorScheme: 'light' });
  return results;
}

function escapeRegExp(value) { return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

async function captureFailure(app, dir, name) {
  const png = await app.evaluate(async ({ BrowserWindow }) => (await BrowserWindow.getAllWindows()[0].capturePage()).toPNG().toString('base64'));
  fs.writeFileSync(path.join(dir, `${name}.png`), Buffer.from(png, 'base64'));
}

function runElectronHelperJob(jobPath) {
  const electronBin = path.join(appRoot, 'node_modules/.bin/electron');
  requireFile(electronBin, 'local Electron binary');
  return execFileSync(electronBin, [__filename, '--job', jobPath], {
    cwd: repo,
    env: { ...process.env, REPORT_VISUAL_EXPORT_HELPER: '1' },
    encoding: 'utf8',
    maxBuffer: 128 * 1024 * 1024,
  });
}


function visualNodesOf(document) {
  const nodes = [];
  const visit = (rows) => {
    for (const node of rows || []) {
      if (node && node.type === 'reportVisual') nodes.push(node);
      if (node && Array.isArray(node.content)) visit(node.content);
    }
  };
  visit(document?.content || []);
  return nodes;
}

function documentWithOneVisual(document, visualNode, index) {
  return {
    schema_version: 1,
    template_version: 'annual-v1',
    metadata: document.metadata || {},
    content: [
      { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: `reportVisual figure ${index + 1}` }] },
      visualNode,
    ],
  };
}

async function captureHtmlToPng({ BrowserWindow, nativeTheme }, html, file, { width = 1200, height = 1400, dark = false } = {}) {
  nativeTheme.themeSource = dark ? 'dark' : 'light';
  const win = new BrowserWindow({ show: false, width, height, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  await win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
  await win.webContents.executeJavaScript('document.fonts.ready.then(()=>true)');
  const metrics = await win.webContents.executeJavaScript(`(() => {
    const target = document.querySelector('.report-visual') || document.body;
    target.scrollIntoView({block:'start'});
    const rect = target.getBoundingClientRect();
    return {svgCount: document.querySelectorAll('.report-visual svg').length, overflow: document.documentElement.scrollWidth > innerWidth + 2, text: document.body.innerText, rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}};
  })()`);
  const png = (await win.capturePage()).toPNG();
  fs.writeFileSync(file, png);
  win.destroy();
  return { file, bytes: png.length, metrics };
}

async function runElectronHelper() {
  const { app, BrowserWindow, nativeTheme } = require('electron');
  const jobPath = process.argv[process.argv.indexOf('--job') + 1];
  const job = JSON.parse(fs.readFileSync(jobPath, 'utf8'));
  if (job.helperUserData) app.setPath('userData', path.resolve(job.helperUserData));
  app.on('window-all-closed', () => {});
  await app.whenReady();
  const output = path.resolve(job.output);
  fs.mkdirSync(output, { recursive: true });
  const converters = require(job.modules.converters);
  const host = require(job.modules.host);
  const raster = require(job.modules.visualRaster);
  const visualEvidence = require(job.modules.visualEvidence);
  const document = job.mode === 'standalone-render' ? standaloneDocument() : job.draft.document;
  const title = job.mode === 'standalone-render' ? 'reportVisual standalone render' : job.draft.title;
  const visualTitles = visualNodesOf(document).map((node) => node.attrs?.visual?.title).filter(Boolean);
  const pdfNeedles = visualTitles.map(stableTitleNeedle);
  const expected = [...visualTitles, '123456789.987654', '缺失'];

  const html = converters.renderReportHtml(document, title, { print: false });
  fs.writeFileSync(path.join(output, 'report.html'), html);
  const text = stripTags(html);
  const screenshots = [];
  for (const variant of [
    { name: 'light-1280', width: 1280, height: 820, dark: false },
    { name: 'dark-1280', width: 1280, height: 820, dark: true },
    { name: 'light-900', width: 900, height: 760, dark: false },
    { name: 'dark-900', width: 900, height: 760, dark: true },
  ]) {
    screenshots.push({ ...(await captureHtmlToPng({ BrowserWindow, nativeTheme }, html, path.join(output, `render-${variant.name}.png`), variant)), ...variant });
  }
  const figureScreenshots = [];
  for (const [index, node] of visualNodesOf(document).entries()) {
    const visual = node.attrs?.visual || {};
    const kind = visual.kind || `visual-${index + 1}`;
    const single = converters.renderReportHtml(documentWithOneVisual(document, node, index), String(visual.title || `图表 ${index + 1}`), { print: false });
    figureScreenshots.push({ kind, title: visual.title || '', ...(await captureHtmlToPng({ BrowserWindow, nativeTheme }, single, path.join(output, `figure-${index + 1}-${kind}.png`), { width: 1200, height: 1500, dark: false })) });
  }
  const htmlInfo = { path: path.join(output, 'report.html'), svgCount: countMatches(html, '<svg'), missing: missing(text, expected), forbidden: missing('', []) };
  let directDocxRejected = false;
  let directDocxRejectMessage = '';
  try { await converters.exportDocx(document, title, readOptional(job.fonts?.docx)); }
  catch (error) { directDocxRejected = true; directDocxRejectMessage = String(error.message || error); }
  const rasterFont = dataUrl('font/woff2', readOptional(job.fonts?.raster || job.fonts?.pdf));
  const visualSources = visualEvidence.reportVisualEvidence(document);
  const identityTokens = collectVisualIdentityTokens(document);
  const docxReady = await raster.materializeReportVisualsForDocx(document, rasterFont, new AbortController().signal);
  const docxBuffer = Buffer.from(await converters.exportDocx(docxReady, title, readOptional(job.fonts?.docx), { visualSources }));
  const docxPath = path.join(output, 'report.docx');
  fs.writeFileSync(docxPath, docxBuffer);
  const docx = inspectDocx(docxPath, { visualSources, identityTokens });
  docx.missingVisualNodeRejection = directDocxRejected;
  const printHtml = converters.renderReportHtml(document, title, { print: true, fontDataUrl: dataUrl('font/woff2', readOptional(job.fonts?.pdf)) });
  const pdfBuffer = Buffer.from(await host.printReportPdf(printHtml, new AbortController().signal));
  const pdfPath = path.join(output, 'report.pdf');
  fs.writeFileSync(pdfPath, pdfBuffer);
  const pdfText = await pdfTextContent(pdfPath);
  const pdfRaster = await rasterizePdfPages(pdfPath, path.join(output, 'pdf-pages'));
  const result = { text, screenshots, figureScreenshots, html: htmlInfo, docx, directDocxRejected, directDocxRejectMessage, pdf: { path: pdfPath, bytes: pdfBuffer.length, pages: pdfText.pages, missing: missing(pdfText.text, pdfNeedles), raster: pdfRaster } };
  process.stdout.write(JSON.stringify(result));
  app.exit(0);
}


function stableTitleNeedle(title) {
  const value = String(title || '').split('·').pop().replace(/[（(].*$/, '').trim();
  return value || String(title || '').trim();
}

function standaloneDocument() {
  const cols = [{ name: '项目' }, { name: '本期' }, { name: '预算' }, { name: '差异' }];
  const rows = [
    { '项目': '长中文标题用于窄屏截断检查 · 华东区域', '本期': '120.123456', '预算': '100', '差异': '20.123456' },
    { '项目': '华南', '本期': '0', '预算': '88.5000', '差异': '-88.5000' },
    { '项目': '华北', '本期': '-45.6700', '预算': '20', '差异': '-65.6700' },
    { '项目': '西部', '本期': null, '预算': '30.0001', '差异': null },
    { '项目': '总部共享', '本期': '123456789.987654', '预算': '123456700.123456', '差异': '89.864198' },
  ];
  const visualBase = { version: 1, run_id: 'b'.repeat(32), snapshot_hash: 'c'.repeat(64), source_label: 'standalone frozen chart', series: { columns: cols, rows } };
  return { schema_version: 1, template_version: 'annual-v1', metadata: { company: '华宸物业', period: '2026-H1', currency: 'CNY', unit: '万元' }, content: [
    { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'reportVisual standalone' }] },
    { type: 'reportVisual', attrs: { visual: { ...visualBase, kind: 'bar', title: '长中文标题用于窄屏截断检查 · 区域预算差异', takeaway: '负数、零值、缺失、高精度都必须保留。', chart_id: 'a'.repeat(32), category: '项目', value_columns: ['本期', '预算'], unit: '万元' } } },
    { type: 'reportVisual', attrs: { visual: { ...visualBase, kind: 'line', title: '月度趋势 · 缺失点不断言为零', takeaway: '缺失点应为空。', chart_id: 'd'.repeat(32), category: '项目', value_columns: ['本期', '预算'], unit: '万元' } } },
    { type: 'reportVisual', attrs: { visual: { version: 1, kind: 'flow', title: '流程图 · 审批链路', takeaway: '流程图为作者分析。', source_label: '作者分析', steps: [{ label: '读取资料', detail: '登记快照', connector: '形成结果' }, { label: '复核图表', detail: '核对精确数据', connector: '导出' }, { label: '归档', detail: '保存报告', connector: '' }] } } },
  ] };
}

async function pdfTextContent(file) {
  const pdfjs = await import(path.join(appRoot, 'node_modules/pdfjs-dist/legacy/build/pdf.mjs'));
  const data = fs.readFileSync(file);
  const loadingTask = pdfjs.getDocument({ data: new Uint8Array(data), disableWorker: true, useSystemFonts: true, isEvalSupported: false });
  const pdf = await loadingTask.promise;
  try {
    let text = '';
    const pages = [];
    for (let pageNo = 1; pageNo <= pdf.numPages; pageNo++) {
      const page = await pdf.getPage(pageNo);
      const content = await page.getTextContent({ includeMarkedContent: false });
      const pageText = content.items.map((item) => item.str || '').join('');
      text += pageText;
      pages.push({ page: pageNo, text: pageText });
    }
    return { pages: pdf.numPages, text, pageText: pages };
  } finally {
    if (typeof pdf.destroy === 'function') await pdf.destroy();
    else if (typeof loadingTask.destroy === 'function') await loadingTask.destroy();
  }
}

async function rasterizePdfPages(file, outputDir) {
  const pdfjs = await import(path.join(appRoot, 'node_modules/pdfjs-dist/legacy/build/pdf.mjs'));
  const { createCanvas } = require(require.resolve('@napi-rs/canvas', { paths: [appRoot] }));
  fs.rmSync(outputDir, { recursive: true, force: true });
  fs.mkdirSync(outputDir, { recursive: true });
  const data = fs.readFileSync(file);
  const loadingTask = pdfjs.getDocument({ data: new Uint8Array(data), disableWorker: true, useSystemFonts: true, isEvalSupported: false });
  const pdf = await loadingTask.promise;
  const pages = [];
  try {
    for (let pageNo = 1; pageNo <= pdf.numPages; pageNo++) {
      const page = await pdf.getPage(pageNo);
      const viewport = page.getViewport({ scale: 1.5 });
      const canvas = createCanvas(Math.ceil(viewport.width), Math.ceil(viewport.height));
      const context = canvas.getContext('2d');
      context.fillStyle = '#ffffff';
      context.fillRect(0, 0, canvas.width, canvas.height);
      await page.render({ canvasContext: context, viewport }).promise;
      const png = canvas.toBuffer('image/png');
      const out = path.join(outputDir, `page-${String(pageNo).padStart(2, '0')}.png`);
      fs.writeFileSync(out, png);
      const bounds = rasterContentBounds(context.getImageData(0, 0, canvas.width, canvas.height).data, canvas.width, canvas.height);
      pages.push({
        page: pageNo,
        file: out,
        width: canvas.width,
        height: canvas.height,
        bytes: png.length,
        bounds,
        hasContent: Boolean(bounds),
        touchesEdge: bounds ? bounds.left < 4 || bounds.top < 4 || bounds.right > canvas.width - 5 || bounds.bottom > canvas.height - 5 : true,
      });
    }
    return { outputDir, pages };
  } finally {
    if (typeof pdf.destroy === 'function') await pdf.destroy();
    else if (typeof loadingTask.destroy === 'function') await loadingTask.destroy();
  }
}

function rasterContentBounds(data, width, height) {
  let left = width; let top = height; let right = -1; let bottom = -1;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const at = (y * width + x) * 4;
      const alpha = data[at + 3];
      if (alpha === 0) continue;
      const r = data[at]; const g = data[at + 1]; const b = data[at + 2];
      if (Math.abs(255 - r) + Math.abs(255 - g) + Math.abs(255 - b) <= 18) continue;
      if (x < left) left = x;
      if (x > right) right = x;
      if (y < top) top = y;
      if (y > bottom) bottom = y;
    }
  }
  if (right < 0) return null;
  return { left, top, right, bottom, width: right - left + 1, height: bottom - top + 1 };
}

function inspectXlsx(file) {
  const entries = listZipEntries(fs.readFileSync(file));
  const chartCount = entries.filter((entry) => /^xl\/charts\/chart\d+\.xml$/.test(entry.name)).length;
  const text = entries
    .filter((entry) => /^xl\/(?:worksheets\/sheet\d+|sharedStrings)\.xml$/.test(entry.name))
    .map((entry) => entry.data.toString('utf8'))
    .join('\n')
    .replace(/<[^>]+>/g, ' ');
  const need = ['区域预算差异', '月度现金流趋势', '预算复核流程', '120.123456', '-45.6700', '123456789.987654'];
  return {
    path: file,
    chartCount,
    sheetCount: entries.filter((entry) => /^xl\/worksheets\/sheet\d+\.xml$/.test(entry.name)).length,
    missing: need.filter((item) => !text.includes(item)),
  };
}

function inspectDocx(file, options = {}) {
  const entries = listZipEntries(fs.readFileSync(file));
  const documentXml = entries.find((entry) => entry.name === 'word/document.xml')?.data.toString('utf8') || '';
  const allXml = entries.filter((entry) => entry.name.endsWith('.xml')).map((entry) => entry.data.toString('utf8')).join('\n');
  const extents = [...documentXml.matchAll(/<wp:extent cx="(\d+)" cy="(\d+)"/g)].map((match) => ({ cx: Number(match[1]), cy: Number(match[2]), ratio: Number(match[1]) / Math.max(1, Number(match[2])) }));
  const media = entries.filter((entry) => /^word\/media\/.+/.test(entry.name)).map((entry, index) => {
    const png = entry.data.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]));
    const size = png ? pngSize(entry.data) : null;
    const extent = extents[index] || null;
    const imageRatio = size ? size.width / Math.max(1, size.height) : null;
    const extentRatio = extent?.ratio ?? null;
    return {
      name: entry.name,
      bytes: entry.uncompressedSize,
      png,
      size,
      extent,
      ratioDelta: imageRatio != null && extentRatio != null ? Math.abs(imageRatio - extentRatio) : null,
      ratioOk: imageRatio != null && extentRatio != null ? Math.abs(imageRatio - extentRatio) <= 0.04 : false,
    };
  });
  const visualSources = options.visualSources || [];
  const identityTokens = options.identityTokens || [];
  const receiptParagraphs = documentXml.split(/<w:p[ >]/).filter((part) => part.includes('图表依据'));
  const leakedTokens = identityTokens.filter((token) => token && documentXml.includes(token) && !receiptParagraphs.some((paragraph) => paragraph.includes(token)));
  return {
    path: file,
    bytes: fs.statSync(file).size,
    media,
    hasPngMedia: media.some((row) => row.png),
    pngDimensionsOk: media.filter((row) => row.png).length >= 3 && media.filter((row) => row.png).every((row) => row.size?.width >= 500 && row.size?.height >= 250 && row.ratioOk),
    visualSources,
    visualSourceCount: visualSources.length,
    receiptParagraphCount: receiptParagraphs.length,
    identityReceiptOk: visualSources.length > 0 && visualSources.every((source) => documentXml.includes(xmlEscapedNeedle(source))) && receiptParagraphs.length >= visualSources.length,
    identityLeakOutsideReceipt: leakedTokens.length > 0,
    leakedTokens,
    textXmlSha256: sha256(Buffer.from(allXml, 'utf8')),
  };
}

function collectVisualIdentityTokens(document) {
  return visualNodesOf(document)
    .map((node) => node.attrs?.visual || {})
    .flatMap((visual) => [visual.chart_id, visual.run_id, visual.snapshot_hash])
    .filter((value) => typeof value === 'string' && value.length >= 16);
}

function xmlEscapedNeedle(value) {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function pngSize(buffer) {
  if (!buffer.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) return null;
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

function listZipEntries(buffer) {
  const entries = [];
  let offset = 0;
  while (offset <= buffer.length - 30) {
    const signature = buffer.readUInt32LE(offset);
    if (signature !== 0x04034b50) break;
    const method = buffer.readUInt16LE(offset + 8);
    const compressedSize = buffer.readUInt32LE(offset + 18);
    const uncompressedSize = buffer.readUInt32LE(offset + 22);
    const nameLength = buffer.readUInt16LE(offset + 26);
    const extraLength = buffer.readUInt16LE(offset + 28);
    const name = buffer.subarray(offset + 30, offset + 30 + nameLength).toString('utf8');
    const dataStart = offset + 30 + nameLength + extraLength;
    const dataEnd = dataStart + compressedSize;
    if (dataEnd > buffer.length) break;
    let data;
    if (method === 0) data = buffer.subarray(dataStart, dataEnd);
    else if (method === 8) data = inflateRawSync(buffer.subarray(dataStart, dataEnd));
    if (data) entries.push({ name, data, compressedSize, uncompressedSize });
    offset = dataEnd;
  }
  return entries;
}

function bundlePaths(bundlePath) {
  const resources = path.join(bundlePath, 'Contents/Resources');
  return {
    app: bundlePath,
    resources,
    executable: path.join(bundlePath, 'Contents/MacOS/FA Foundry'),
    appAsar: path.join(resources, 'app.asar'),
    foundryBin: path.join(resources, 'foundry/foundry'),
    reportsRoot: path.join(resources, 'app.asar/dist-electron/reports'),
    pdfFontPath: path.join(resources, 'dsh/assets/fonts/NotoSansSC-variable.woff2'),
    docxFontPath: path.join(resources, 'fonts/NotoSansSC-report.ttf'),
  };
}

function resolveReportModules(bundleInfo, evidenceDir) {
  const explicit = process.env.UI_REPORT_MODULES_DIR;
  if (explicit) return reportModulePaths(path.resolve(explicit), { source: 'explicit-dev-dir', explicit: true });
  requireFile(bundleInfo.appAsar, 'bundle app.asar');
  const extractRoot = path.join(evidenceDir, 'extracted-app-asar');
  fs.rmSync(extractRoot, { recursive: true, force: true });
  fs.mkdirSync(extractRoot, { recursive: true });
  const asar = require(require.resolve('@electron/asar', { paths: [appRoot] }));
  asar.extractAll(bundleInfo.appAsar, extractRoot);
  const reportsRoot = path.join(extractRoot, 'dist-electron/reports');
  const paths = reportModulePaths(reportsRoot, { source: 'bundle-asar-extract', appAsar: bundleInfo.appAsar, appAsarSha256: hashFile(bundleInfo.appAsar), extractRoot });
  for (const file of ['format', 'converters', 'host', 'visuals', 'visualRaster', 'visualEvidence']) requireFile(paths[file], `extracted ${file}`);
  return paths;
}

function reportModulePaths(reportsRoot, meta = {}) {
  return {
    ...meta,
    reportsRoot,
    format: path.join(reportsRoot, 'format.js'),
    converters: path.join(reportsRoot, 'converters.js'),
    host: path.join(reportsRoot, 'host.js'),
    visuals: path.join(reportsRoot, 'visuals.js'),
    visualRaster: path.join(reportsRoot, 'visual-raster.js'),
    visualEvidence: path.join(reportsRoot, 'visual-evidence.js'),
  };
}

function assertCommand(bin, label) {
  if (bin.includes('/') || bin.startsWith('.')) return requireFile(bin, label);
  execFileSync('/bin/sh', ['-lc', 'command -v ' + shellQuote(bin)], { stdio: 'ignore' });
  return bin;
}

function shellQuote(value) { return "'" + String(value).replace(/'/g, "'\\''") + "'"; }

function foundryCommand(bundleInfo) {
  if (process.env.FOUNDRY_BIN) return { bin: process.env.FOUNDRY_BIN, prefix: JSON.parse(process.env.FOUNDRY_PREFIX || '[]') };
  return { bin: bundleInfo.foundryBin, prefix: [] };
}

function fontPaths(bundleInfo) {
  return {
    pdf: fs.existsSync(bundleInfo.pdfFontPath) ? bundleInfo.pdfFontPath : path.join(appRoot, 'src/assets/fonts/noto-sans-sc/NotoSansSC-variable.woff2'),
    raster: fs.existsSync(bundleInfo.pdfFontPath) ? bundleInfo.pdfFontPath : path.join(appRoot, 'src/assets/fonts/noto-sans-sc/NotoSansSC-variable.woff2'),
    docx: fs.existsSync(bundleInfo.docxFontPath) ? bundleInfo.docxFontPath : path.join(appRoot, 'src/assets/fonts/noto-sans-sc/NotoSansSC-report.ttf'),
  };
}

function dataUrl(mime, data) { return `data:${mime};base64,${data.toString('base64')}`; }
function readOptional(file) { return file && fs.existsSync(file) ? fs.readFileSync(file) : undefined; }
function stripTags(html) { return String(html).replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' '); }
function countMatches(text, needle) { return String(text).split(needle).length - 1; }
function missing(text, values) { const hay = searchable(text); return values.filter((value) => !hay.includes(searchable(value))); }
function searchable(text) { return String(text || '').normalize('NFKC').replace(/\s+/g, ''); }
function sha256(data) { return createHash('sha256').update(data).digest('hex'); }
function hashFile(file) { return sha256(fs.readFileSync(file)); }
function requireFile(file, label) { if (!fs.existsSync(file)) throw new Error(`${label} missing: ${file}`); return file; }
