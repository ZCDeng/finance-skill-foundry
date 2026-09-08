#!/usr/bin/env node
import { createHash, randomUUID } from 'node:crypto';
import { execFile } from 'node:child_process';
import { createRequire } from 'node:module';
import { access, cp, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { constants as fsConstants } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { inflateRawSync } from 'node:zlib';

const require = createRequire(import.meta.url);
const repoRoot = path.resolve(new URL('..', import.meta.url).pathname);
const appRoot = path.join(repoRoot, 'app');
const taskId = '79e2e9484e354a00849cf1c20a796b6e';
const draftId = 'b38e7dcf2f0a4beaa13e8bf98e13737e';
const defaultLiveVar = path.join(os.homedir(), 'Library/Application Support/FA Foundry/var');
const defaultSourceDir = '/Users/zcdeng/Desktop/物业集团月结财务套表';
const defaultWorkRoot = path.join(repoRoot, 'build/report-workflow-final-20260908');
const expectedText = ['华宸物业', '月结核对', 'BUD→LE', '五区对比'];
const expectedAmounts = [
  '3,256,440,000',
  '129,753,049',
  '174,319,387',
  '527,999.9999',
  '7,201.91',
  '1,234.5600',
  '-98.7600',
  '120,120.0120',
  '912,345.6789',
];
const requiredMarkers = [
  'BODYFONT-MARKER-001',
  'LT-ROW-001',
  'LT-ROW-060',
  'LT-ROW-120',
  'WD-MERGE-001',
  'WD-COL-12',
  'NOTE-SEMANTIC-001',
  'IMG-ALT-001',
  'SRC-LINK-001',
  'PDF-END-MARKER-001',
];
const pngDataUrl = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lOjG0wAAAABJRU5ErkJggg==';

let electronApp;

main().catch((error) => {
  const message = error instanceof Error ? error.stack || error.message : String(error);
  console.error(message);
  if (electronApp?.exit) electronApp.exit(1);
  process.exit(1);
});

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (!process.versions.electron) {
    await runElectron(options);
    return;
  }
  electronApp = (await import('electron')).app;
  electronApp.on('window-all-closed', () => {});
  await electronApp.whenReady();
  const result = await runAcceptance(options);
  await writeStdout(JSON.stringify(result, null, 2) + '\n');
  electronApp.exit(result.failures.length ? 1 : 0);
}

async function runElectron(options) {
  const electronBin = path.join(appRoot, 'node_modules/.bin/electron');
  const electronEntrypoint = path.join(repoRoot, 'tools/verify_report_workflow_electron.cjs');
  await access(electronBin, fsConstants.X_OK);
  await new Promise((resolve) => {
    execFile(electronBin, [electronEntrypoint, ...process.argv.slice(2)], {
      cwd: repoRoot,
      env: { ...process.env, ELECTRON_ENABLE_LOGGING: '0' },
      maxBuffer: 64 * 1024 * 1024,
    }, (error, stdout, stderr) => {
      if (stdout) process.stdout.write(stdout);
      if (stderr) process.stderr.write(stderr);
      if (error) process.exitCode = typeof error.code === 'number' ? error.code : 1;
      resolve(undefined);
    });
  });
}

async function runAcceptance(options) {
  const startedAt = new Date().toISOString();
  const bundle = options.bundle ? bundlePaths(options.bundle) : undefined;
  const workRoot = path.resolve(options.workRoot ?? defaultWorkRoot);
  const liveVar = path.resolve(options.liveVar ?? defaultLiveVar);
  const sourceDir = path.resolve(options.sourceDir ?? defaultSourceDir);
  const isolatedVar = path.join(workRoot, 'var');
  const outDir = path.join(workRoot, 'outputs');
  const failures = [];
  const notes = [];
  const evidence = {
    startedAt,
    repoRoot,
    workRoot,
    liveVar,
    sourceDir,
    taskId,
    draftId,
    bundle: bundle ? { app: bundle.app, reportsRoot: bundle.reportsRoot, foundryBin: bundle.foundryBin, pdfFont: bundle.pdfFontPath, docxFont: bundle.docxFontPath } : null,
  };

  const reportsRoot = bundle?.reportsRoot ?? path.join(appRoot, 'dist-electron/reports');
  await assertCompiledModules(reportsRoot);
  if (bundle) await assertBundleAssets(bundle);
  const converters = require(path.join(reportsRoot, 'converters.js'));
  const host = require(path.join(reportsRoot, 'host.js'));

  await rm(workRoot, { recursive: true, force: true });
  await mkdir(outDir, { recursive: true });

  const sourceHashesBefore = await hashDirectory(sourceDir, (file) => file.endsWith('.xlsx'));
  evidence.sourceHashesBefore = sourceHashesBefore;
  await cloneTask(liveVar, isolatedVar);
  const draft = await readJson(path.join(isolatedVar, 'tasks', taskId, 'analysis/drafts', `${draftId}.json`));
  evidence.liveDraft = { title: draft.title, bodySha256: sha256(Buffer.from(draft.body ?? '', 'utf8')), contentHash: draft.content_hash };

  const xlsxPath = pickPropertyWorkbook(sourceHashesBefore);
  const foundry = foundryRunner(bundle);
  const addedSource = await foundryJson(foundry, isolatedVar, 'report-source-add', ['--path', xlsxPath]);
  evidence.reportSource = addedSource.source;

  const document = converters.documentFromMarkdown(draft.body);
  document.metadata = { company: '华宸物业', period: '2026-08', currency: 'CNY', unit: '元/万元' };
  document.sources = [addedSource.source];
  document.content.unshift({
    type: 'heading',
    attrs: { level: 1 },
    content: [{ type: 'text', text: draft.title }],
  });
  document.content.push(...stressNodes(addedSource.source.id));
  const projected = converters.documentToMarkdown(document);
  for (const text of [...expectedText, ...expectedAmounts, ...requiredMarkers, '长表跨页压力测试', '宽表分段压力测试', '合并单元格']) {
    record(failures, projected.includes(text), 'projection_contains', { text });
  }

  const specPath = path.join(workRoot, 'rich-draft-spec.json');
  await writeFile(specPath, JSON.stringify({
    parent_id: draftId,
    title: `${draft.title} - 五格式验收副本`,
    document,
    limitations: ['验收脚本在隔离副本中生成，不改变真实任务。'],
  }, null, 2));
  const richDraft = await foundryJson(foundry, isolatedVar, 'analysis-draft', ['--spec-file', specPath]);
  evidence.richDraft = { id: richDraft.id, contentHash: richDraft.content_hash, parentId: richDraft.parent_id };
  record(failures, richDraft.parent_id === draftId, 'rich_draft_parent_preserved', { parent: richDraft.parent_id });
  record(failures, typeof richDraft.document === 'object', 'rich_draft_has_document', {});
  record(failures, (richDraft.body ?? '').includes('宽表分段压力测试'), 'rich_draft_body_projected_from_document', {});

  const exported = {};
  exported.md = await backendExport(foundry, isolatedVar, richDraft.id, 'md', outDir);
  exported.xlsx = await backendExport(foundry, isolatedVar, richDraft.id, 'xlsx', outDir);
  exported.html = await converterExportRegister(foundry, isolatedVar, richDraft, 'html', outDir, async () => Buffer.from(converters.renderReportHtml(richDraft.document, richDraft.title, { print: false }), 'utf8'));
  const docxFontData = await optionalDocxFontData(notes, bundle);
  const pdfFontData = await optionalPdfFontData(notes, bundle);
  exported.docx = await converterExportRegister(foundry, isolatedVar, richDraft, 'docx', outDir, async () => Buffer.from(await converters.exportDocx(richDraft.document, richDraft.title, docxFontData?.data)));
  const printHtml = converters.renderReportHtml(richDraft.document, richDraft.title, { print: true, fontDataUrl: pdfFontData ? fontDataUrl(pdfFontData) : undefined });
  exported.pdf = await converterExportRegister(foundry, isolatedVar, richDraft, 'pdf', outDir, async () => Buffer.from(await host.printReportPdf(printHtml, new AbortController().signal)));
  evidence.exports = exported;

  const roundTrips = {};
  for (const format of ['md', 'html', 'docx', 'pdf']) {
    const file = exported[format].copiedPath;
    const data = await readFile(file);
    const source = { id: deterministicSourceId(format), name: path.basename(file), sha256: sha256(data), format };
    const imported = await converters.importReport(data, format, source);
    const markdown = imported.document ? converters.documentToMarkdown(imported.document) : '';
    roundTrips[format] = {
      warnings: imported.warnings,
      needsReview: imported.needsReview,
      markdownSha256: sha256(Buffer.from(markdown, 'utf8')),
      textChecks: checkText(markdown),
      structure: summarizeDocument(imported.document),
    };
    recordMissing(failures, roundTrips[format].textChecks.missingText, `${format}_roundtrip_chinese_text`);
    recordMissing(failures, roundTrips[format].textChecks.missingAmounts, `${format}_roundtrip_amounts`);
    recordMissing(failures, roundTrips[format].textChecks.missingMarkers, `${format}_roundtrip_markers`);
    if (format === 'html') {
      record(failures, markdown.includes('NOTE-SEMANTIC-001'), 'html_roundtrip_note_semantic_text', {});
      record(failures, roundTrips.html.structure.notes >= 1, 'html_roundtrip_note_node_preserved', roundTrips.html.structure);
      record(failures, roundTrips.html.structure.tables >= 1, 'html_roundtrip_table_preserved', roundTrips.html.structure);
    }
    if (format === 'docx') {
      record(failures, markdown.includes('NOTE-SEMANTIC-001'), 'docx_roundtrip_note_semantic_text', {});
      record(failures, roundTrips.docx.structure.notes >= 1, 'docx_roundtrip_note_node_preserved', roundTrips.docx.structure);
      record(failures, roundTrips.docx.structure.tables >= 1, 'docx_roundtrip_table_preserved', roundTrips.docx.structure);
    }
  }

  const xlsxImported = await importExportedXlsx(foundry, isolatedVar, exported.xlsx.copiedPath);
  roundTrips.xlsx = xlsxImported.summary;
  record(failures, xlsxImported.text.includes('华宸物业'), 'xlsx_roundtrip_chinese_text', xlsxImported.summary);
  recordMissing(failures, missingInText(xlsxImported.text, expectedAmounts), 'xlsx_roundtrip_amounts');
  recordMissing(failures, missingInText(xlsxImported.text, requiredMarkers), 'xlsx_roundtrip_markers');

  const docxEvidence = await inspectDocx(exported.docx.copiedPath, docxFontData);
  evidence.docx = docxEvidence;
  record(failures, docxEvidence.embeddedFonts.length >= 1, 'docx_embeds_report_font_payload', docxEvidence);
  record(failures, !docxFontData || docxEvidence.expectedFontPayloadEmbedded, 'docx_embedded_font_payload_matches_report_font', docxEvidence);

  const pdfEvidence = await inspectPdf(exported.pdf.copiedPath);
  evidence.pdf = pdfEvidence;
  record(failures, pdfEvidence.pages >= 1, 'pdf_page_count', pdfEvidence);
  record(failures, pdfEvidence.textItems > 0, 'pdf_selectable_text_items', pdfEvidence);
  record(failures, pdfEvidence.fonts.bodyMarkerPt >= 10.5, 'pdf_body_font_at_least_11pt', pdfEvidence.fonts);
  record(failures, pdfEvidence.fonts.noteMarkerPt >= 8.5, 'pdf_note_font_at_least_9pt', pdfEvidence.fonts);
  record(failures, pdfEvidence.bounds.minXPt >= 48 && pdfEvidence.bounds.minXPt <= 80, 'pdf_left_margin_near_20mm', pdfEvidence.bounds);
  record(failures, pdfEvidence.bounds.maxXPt <= pdfEvidence.bounds.pageWidthPt - 48, 'pdf_right_margin_respected', pdfEvidence.bounds);
  record(failures, pdfEvidence.markers.hasEndMarker, 'pdf_end_marker_not_clipped', pdfEvidence.markers);
  record(failures, pdfEvidence.markers.orphanHeadingCount === 0, 'pdf_heading_not_orphaned_at_page_end', pdfEvidence.markers);

  evidence.negativeCases = await runNegativeCases({ converters, host, foundry, isolatedVar, workRoot });
  for (const item of evidence.negativeCases) record(failures, item.ok, `negative_${item.name}`, item);

  evidence.sourceHashesAfter = await hashDirectory(sourceDir, (file) => file.endsWith('.xlsx'));
  record(failures, JSON.stringify(evidence.sourceHashesBefore) === JSON.stringify(evidence.sourceHashesAfter), 'original_source_hashes_unchanged', {});
  const reportPath = path.join(workRoot, 'acceptance-report.json');
  const result = { ok: failures.length === 0, failures, notes, evidence, roundTrips };
  await writeFile(reportPath, JSON.stringify(result, null, 2));
  result.reportPath = reportPath;
  return result;
}

function parseArgs(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (item === '--work-root') options.workRoot = argv[++index];
    else if (item === '--bundle') options.bundle = argv[++index];
    else if (item === '--live-var') options.liveVar = argv[++index];
    else if (item === '--source-dir') options.sourceDir = argv[++index];
    else throw new Error(`Unknown option: ${item}`);
  }
  return options;
}

function bundlePaths(bundlePath) {
  const appPath = path.resolve(bundlePath);
  const resources = path.join(appPath, 'Contents/Resources');
  return {
    app: appPath,
    resources,
    reportsRoot: path.join(resources, 'app.asar/dist-electron/reports'),
    foundryBin: path.join(resources, 'foundry/foundry'),
    pdfFontPath: path.join(resources, 'dsh/assets/fonts/NotoSansSC-variable.woff2'),
    docxFontPath: path.join(resources, 'fonts/NotoSansSC-report.ttf'),
  };
}

function foundryRunner(bundle) {
  if (process.env.FOUNDRY_BIN) return { bin: process.env.FOUNDRY_BIN, prefix: [] };
  if (bundle) return { bin: bundle.foundryBin, prefix: [] };
  return { bin: 'uv', prefix: ['run', 'python', '-m', 'foundry.cli'] };
}

async function assertCompiledModules(reportsRoot) {
  for (const filename of ['format.js', 'converters.js', 'host.js']) {
    const compiled = path.join(reportsRoot, filename);
    try { await access(compiled, fsConstants.R_OK); } catch {
      throw new Error(`Missing compiled Electron report module ${compiled}. Run "cd app && npm run build" before this acceptance script.`);
    }
  }
}

async function assertBundleAssets(bundle) {
  try { await access(bundle.foundryBin, fsConstants.X_OK); } catch {
    throw new Error(`Bundle Foundry binary is not executable: ${bundle.foundryBin}`);
  }
  try { await access(bundle.pdfFontPath, fsConstants.R_OK); } catch {
    throw new Error(`Bundle PDF Chinese font is not readable: ${bundle.pdfFontPath}`);
  }
  try { await access(bundle.docxFontPath, fsConstants.R_OK); } catch {
    throw new Error(`Bundle DOCX Chinese font is not readable: ${bundle.docxFontPath}`);
  }
}

async function cloneTask(liveVar, isolatedVar) {
  const source = path.join(liveVar, 'tasks', taskId);
  const target = path.join(isolatedVar, 'tasks', taskId);
  await mkdir(path.dirname(target), { recursive: true });
  await cp(source, target, { recursive: true, dereference: false, errorOnExist: false });
}

async function backendExport(foundry, isolatedVar, id, format, outDir) {
  const result = await foundryJson(foundry, isolatedVar, 'analysis-export', ['--draft', id, '--format', format]);
  const copiedPath = path.join(outDir, `report.${format}`);
  await cp(result.path, copiedPath);
  const data = await readFile(copiedPath);
  return { ...result, copiedPath, copiedSha256: sha256(data), bytes: data.length };
}

async function converterExportRegister(foundry, isolatedVar, draft, format, outDir, render) {
  const tempPath = path.join(outDir, `candidate.${format}`);
  await writeFile(tempPath, await render());
  const registered = await foundryJson(foundry, isolatedVar, 'report-export-register', ['--draft', draft.id, '--format', format, '--path', tempPath]);
  const copiedPath = path.join(outDir, `report.${format}`);
  await cp(registered.path, copiedPath);
  const data = await readFile(copiedPath);
  return { ...registered, copiedPath, copiedSha256: sha256(data), bytes: data.length };
}

async function foundryJson(foundry, varRoot, command, rest) {
  const stdout = await execFileText(foundry.bin, [
    ...foundry.prefix,
    '--var', varRoot,
    '--task', taskId,
    command,
    ...rest,
  ], { cwd: repoRoot });
  return JSON.parse(stdout);
}

function execFileText(bin, args, options) {
  return new Promise((resolve, reject) => {
    execFile(bin, args, { ...options, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) {
        error.message = `${error.message}\n${stderr || stdout}`;
        reject(error);
      } else {
        resolve(stdout);
      }
    });
  });
}

function writeStdout(text) {
  return new Promise((resolve) => process.stdout.write(text, resolve));
}

async function optionalDocxFontData(notes, bundle) {
  const candidates = [
    bundle?.docxFontPath,
    path.join(appRoot, 'src/assets/fonts/noto-sans-sc/NotoSansSC-report.ttf'),
    path.join(appRoot, 'dist-vite/assets/NotoSansSC-report.ttf'),
  ].filter(Boolean);
  const data = await firstReadableFont(candidates, 'font/ttf');
  if (data) return data;
  notes.push('离线中文 DOCX 报告字体未找到；DOCX 字体嵌入检查将只验证包内 payload 是否存在。');
  return undefined;
}

async function optionalPdfFontData(notes, bundle) {
  const candidates = [
    bundle?.pdfFontPath,
    path.join(appRoot, 'src/assets/fonts/noto-sans-sc/NotoSansSC-variable.woff2'),
    path.join(appRoot, 'dist-vite/assets/NotoSansSC-variable.woff2'),
  ].filter(Boolean);
  const data = await firstReadableFont(candidates, 'font/woff2');
  if (data) return data;
  notes.push('离线中文 PDF 运行时字体未找到；PDF 仍通过 Electron 打印，但字体完成检查可能依赖系统回退。');
  return undefined;
}

async function firstReadableFont(candidates, mime) {
  for (const candidate of candidates) {
    try {
      const data = await readFile(candidate);
      return { path: candidate, data, sha256: sha256(data), bytes: data.length, mime };
    } catch {}
  }
  return undefined;
}

function fontDataUrl(fontData) {
  return `data:${fontData.mime};base64,${fontData.data.toString('base64')}`;
}

function stressNodes(sourceId) {
  const longHeader = ['序号', '指标', '本期金额', '累计金额', '说明'];
  const longRows = [
    longHeader.map((text) => cell('tableHeader', text, sourceId)),
    ...Array.from({ length: 120 }, (_, index) => {
      const row = index + 1;
      const marker = `LT-ROW-${String(row).padStart(3, '0')}`;
      return [
        cell('tableCell', marker, sourceId),
        cell('tableCell', `跨页收入项目 ${row}`, sourceId),
        cell('tableCell', row === 120 ? '120,120.0120' : `${row},000.000${row % 10}`, sourceId),
        cell('tableCell', row === 60 ? '912,345.6789' : `${row * 100},500.00`, sourceId),
        cell('tableCell', row === 1 ? 'BODYFONT-MARKER-001' : row === 120 ? 'PDF-END-MARKER-001' : '保留原始精度', sourceId),
      ];
    }),
  ];
  const wideHeader = ['项目', '预算', '本期', '累计', '达成率', '华东', '华南', '华北', '华中', '西部', '租户', 'WD-COL-12'];
  const wideRows = [
    wideHeader.map((text) => cell('tableHeader', text, sourceId)),
    [
      cell('tableCell', 'WD-MERGE-001 合并单元格', sourceId, { colspan: 2 }),
      cell('tableCell', '1,234.5600', sourceId),
      cell('tableCell', '-98.7600', sourceId),
      cell('tableCell', '', sourceId),
      cell('tableCell', '45.00%', sourceId),
      cell('tableCell', '7,201.91', sourceId),
      cell('tableCell', '129,753,049', sourceId),
      cell('tableCell', '174,319,387', sourceId),
      cell('tableCell', '3,256,440,000', sourceId),
      cell('tableCell', '527,999.9999', sourceId),
    ],
    ['现金流压力', '预算', '174,319,387', '3,256,440,000', '527,999.9999', '15.00亿元', '2.2125亿元', '12.7875亿元', '18.60亿元', '-84,005,613', 'SRC-LINK-001', 'WD-COL-12']
      .map((text) => cell('tableCell', text, sourceId)),
  ];
  return [
    { type: 'heading', attrs: { level: 1, source_id: sourceId }, content: [{ type: 'text', text: '验收附录：长表跨页压力测试' }] },
    { type: 'paragraph', attrs: { source_id: sourceId }, content: [{ type: 'text', text: 'BODYFONT-MARKER-001 这一段用于核验正式 PDF 正文不低于 11pt 且不被双重边距挤窄。' }] },
    { type: 'table', attrs: { source_id: sourceId, sheet: '验收', range: 'A1:E121', caption: '长表跨页压力测试', period: '2026-08', unit: '元/万元' }, content: longRows.map((content) => ({ type: 'tableRow', attrs: { source_id: sourceId }, content })) },
    { type: 'heading', attrs: { level: 1, source_id: sourceId }, content: [{ type: 'text', text: '验收附录：宽表分段压力测试' }] },
    { type: 'paragraph', attrs: { source_id: sourceId }, content: [{ type: 'text', text: '保留合并单元格、图片、来源定位、链接和附注引用，不改变原始金额文本。' }] },
    { type: 'table', attrs: { source_id: sourceId, sheet: '验收', range: 'A1:L3', caption: '宽表分段压力测试', period: '2026-08', unit: '元/万元' }, content: wideRows.map((content) => ({ type: 'tableRow', attrs: { source_id: sourceId }, content })) },
    { type: 'image', attrs: { source_id: sourceId, src: pngDataUrl, alt: 'IMG-ALT-001 验收图片', title: '本地嵌入图片' } },
    { type: 'paragraph', attrs: { source_id: sourceId }, content: [{ type: 'text', text: 'IMG-ALT-001 图片说明：本地嵌入图片应随文稿导出，文字说明不能丢失。' }] },
    { type: 'paragraph', attrs: { source_id: sourceId }, content: [{ type: 'text', text: 'SRC-LINK-001 来源链接', marks: [{ type: 'link', attrs: { href: 'https://example.com/local-evidence' } }] }, { type: 'text', text: ' [1]' }] },
    { type: 'reportNote', attrs: { id: '1', source_id: sourceId }, content: [{ type: 'paragraph', content: [{ type: 'text', text: 'NOTE-SEMANTIC-001 附注统一放在章节末，导出时不依赖页底脚注位置。' }] }] },
  ];
}

function cell(type, text, sourceId, attrs = {}) {
  return {
    type,
    attrs: { source_id: sourceId, textAlign: numericLike(text) ? 'right' : 'left', ...attrs },
    content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
  };
}

function numericLike(text) {
  return /^[(（]?-?(?:¥|￥|\$)?\s*\d[\d,]*(?:\.\d+)?%?[)）]?/.test(text);
}

function checkText(markdown) {
  return {
    text: expectedText.length - missingInText(markdown, expectedText).length,
    amount: expectedAmounts.length - missingInText(markdown, expectedAmounts).length,
    marker: requiredMarkers.length - missingInText(markdown, requiredMarkers).length,
    missingText: missingInText(markdown, expectedText),
    missingAmounts: missingInText(markdown, expectedAmounts),
    missingMarkers: missingInText(markdown, requiredMarkers),
  };
}

function searchableText(text) {
  return String(text ?? '').normalize('NFKC').replace(/\s+/g, '');
}

function missingInText(text, values) {
  const compact = searchableText(text);
  return values.filter((value) => !compact.includes(searchableText(value)));
}

function recordMissing(failures, missing, check) {
  record(failures, missing.length === 0, check, { missing });
}

function summarizeDocument(document) {
  const counts = { headings: 0, paragraphs: 0, tables: 0, notes: 0, images: 0, sourceAnchors: 0 };
  walk(document?.content ?? [], (node) => {
    if (node.type === 'heading') counts.headings += 1;
    if (node.type === 'paragraph') counts.paragraphs += 1;
    if (node.type === 'table') counts.tables += 1;
    if (node.type === 'reportNote') counts.notes += 1;
    if (node.type === 'image') counts.images += 1;
    if (node.attrs?.source_id) counts.sourceAnchors += 1;
  });
  return counts;
}

function walk(nodes, visit) {
  for (const node of nodes) {
    visit(node);
    if (node.content) walk(node.content, visit);
  }
}

async function importExportedXlsx(foundry, isolatedVar, xlsxPath) {
  const added = await foundryJson(foundry, isolatedVar, 'report-source-add', ['--path', xlsxPath]);
  const imported = await foundryJson(foundry, isolatedVar, 'report-xlsx-read', ['--source', added.source.id]);
  const text = collectNodeText(imported.document?.content ?? []);
  return {
    text,
    summary: {
      source: imported.source,
      sheets: imported.sheets,
      warnings: imported.warnings,
      structure: summarizeDocument(imported.document),
      amountHits: expectedAmounts.length - missingInText(text, expectedAmounts).length,
    },
  };
}

function collectNodeText(nodes) {
  const parts = [];
  walk(nodes, (node) => { if (node.text) parts.push(node.text); });
  return parts.join('\n');
}

async function inspectDocx(file, expectedFontData) {
  const data = await readFile(file);
  const entries = listZipEntries(data);
  const fontTable = entries.find((entry) => entry.name === 'word/fontTable.xml')?.data.toString('utf8') ?? '';
  const fontKeys = [...fontTable.matchAll(/fontKey=\"\{?([^\"}]+)\}?\"/g)].map((match) => match[1]);
  const embeddedFonts = entries
    .filter((entry) => entry.name.startsWith('word/fonts/') && entry.uncompressedSize > 0)
    .map((entry) => {
      const deobfuscated = expectedFontData ? deobfuscateEmbeddedFont(entry.data, fontKeys) : [];
      return {
        name: entry.name,
        bytes: entry.uncompressedSize,
        sha256: sha256(entry.data),
        deobfuscatedSha256: deobfuscated.map((candidate) => candidate.sha256),
      };
    });
  return {
    bytes: data.length,
    sha256: sha256(data),
    fontKeys,
    embeddedFonts,
    expectedFont: expectedFontData ? { path: expectedFontData.path, bytes: expectedFontData.bytes, sha256: expectedFontData.sha256 } : null,
    expectedFontPayloadEmbedded: expectedFontData ? embeddedFonts.some((entry) => entry.deobfuscatedSha256.includes(expectedFontData.sha256)) : false,
  };
}

function deobfuscateEmbeddedFont(data, fontKeys) {
  const candidates = [];
  for (const key of fontKeys) {
    for (const bytes of guidKeyCandidates(key)) {
      const restored = Buffer.from(data);
      for (let index = 0; index < Math.min(32, restored.length); index += 1) {
        restored[index] = restored[index] ^ bytes[index % 16];
      }
      candidates.push({ fontKey: key, sha256: sha256(restored) });
    }
  }
  return candidates;
}

function guidKeyCandidates(fontKey) {
  const hex = fontKey.replace(/[^0-9a-f]/gi, '');
  if (hex.length !== 32) return [];
  const canonical = Buffer.from(hex, 'hex');
  const littleEndianGuid = Buffer.from([
    canonical[3], canonical[2], canonical[1], canonical[0],
    canonical[5], canonical[4],
    canonical[7], canonical[6],
    ...canonical.subarray(8),
  ]);
  return [canonical, littleEndianGuid, Buffer.from(canonical).reverse()];
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

async function inspectPdf(file) {
  const pdfjs = await import(path.join(appRoot, 'node_modules/pdfjs-dist/legacy/build/pdf.mjs'));
  const data = await readFile(file);
  const pdf = await pdfjs.getDocument({ data: new Uint8Array(data), disableWorker: true, useSystemFonts: true }).promise;
  const items = [];
  let pageWidthPt = 0;
  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber);
    const viewport = page.getViewport({ scale: 1 });
    pageWidthPt = Math.max(pageWidthPt, viewport.width);
    const text = await page.getTextContent({ includeMarkedContent: false });
    for (const item of text.items) {
      const transform = item.transform ?? [0, 0, 0, 0, 0, 0];
      const fontPt = Math.max(Math.abs(transform[0] ?? 0), Math.abs(transform[3] ?? 0), Number(item.height ?? 0));
      items.push({
        page: pageNumber,
        str: String(item.str ?? ''),
        x: Number(transform[4] ?? 0),
        y: Number(transform[5] ?? 0),
        width: Number(item.width ?? 0),
        fontPt,
      });
    }
  }
  const contentItems = items.filter((item) => item.str.trim() && !/^\d+\s*\/\s*\d+$/.test(item.str.trim()));
  const minXPt = Math.min(...contentItems.map((item) => item.x));
  const maxXPt = Math.max(...contentItems.map((item) => item.x + Math.max(0, item.width)));
  const text = contentItems.map((item) => item.str).join('');
  const byPage = new Map();
  for (const item of contentItems) {
    const row = byPage.get(item.page) ?? [];
    row.push(item);
    byPage.set(item.page, row);
  }
  let orphanHeadingCount = 0;
  for (const pageItems of byPage.values()) {
    const sorted = pageItems.slice().sort((a, b) => b.y - a.y);
    const last = sorted[sorted.length - 1];
    if (last && /验收附录：/.test(last.str)) orphanHeadingCount += 1;
  }
  return {
    pages: pdf.numPages,
    textItems: items.length,
    bytes: data.length,
    sha256: sha256(data),
    bounds: { minXPt, maxXPt, pageWidthPt },
    fonts: {
      bodyMarkerPt: markerFont(contentItems, 'BODYFONT-MARKER-001'),
      noteMarkerPt: markerFont(contentItems, 'NOTE-SEMANTIC-001'),
    },
    markers: {
      hasEndMarker: searchableText(text).includes(searchableText('PDF-END-MARKER-001')),
      orphanHeadingCount,
    },
  };
}

function markerFont(items, marker) {
  const hit = items.find((item) => item.str.includes(marker));
  return hit?.fontPt ?? 0;
}

async function runNegativeCases({ converters, host, foundry, isolatedVar, workRoot }) {
  const cases = [];
  cases.push(await captures('worker_pdf_import', async () => {
    const data = minimalPdf('WORKER-PDF-IMPORT-001 123.45');
    const result = await host.conversion('import', {
      data,
      format: 'pdf',
      source: { id: deterministicSourceId('pdf'), name: 'worker.pdf', sha256: sha256(data), format: 'pdf' },
    }, new AbortController().signal);
    if (!converters.documentToMarkdown(result.document).includes('WORKER-PDF-IMPORT-001')) throw new Error('worker PDF import lost text');
  }));
  cases.push(await captures('host_worker_cancel', async () => {
    const controller = new AbortController();
    controller.abort();
    await expectRejects(() => host.conversion('markdown', { body: '# cancelled' }, controller.signal), '取消');
  }));
  cases.push(await captures('corrupt_docx_import', async () => {
    await expectRejects(() => converters.importReport(Buffer.from('not a zip'), 'docx', { id: deterministicSourceId('docx'), name: 'bad.docx', sha256: sha256(Buffer.from('not a zip')), format: 'docx' }), 'zip');
  }));
  cases.push(await captures('oversized_source_refused', async () => {
    const large = path.join(workRoot, 'oversized.md');
    await writeFile(large, Buffer.alloc(33 * 1024 * 1024, '#'));
    await expectRejects(() => foundryJson(foundry, isolatedVar, 'report-source-add', ['--path', large]), 'exceeds');
  }));
  cases.push(await captures('missing_image_import_is_inert', async () => {
    const html = Buffer.from('<h1>缺图</h1><p>IMG-MISSING-001</p><img src="file:///tmp/missing.png"><img src="https://example.com/missing.png">');
    const result = await converters.importReport(html, 'html', { id: deterministicSourceId('html'), name: 'missing-image.html', sha256: sha256(html), format: 'html' });
    const encoded = JSON.stringify(result.document);
    if (encoded.includes('file:///tmp/missing.png') || encoded.includes('https://example.com/missing.png')) throw new Error('unsafe missing image src survived');
    if (!result.warnings.join('\n').includes('外部')) throw new Error('missing/external image warning absent');
  }));
  cases.push(await captures('xlsx_formula_missing_cache_warning', async () => {
    const workbook = path.join(workRoot, 'formula-missing-cache.xlsx');
    await createFormulaMissingWorkbook(workbook);
    const added = await foundryJson(foundry, isolatedVar, 'report-source-add', ['--path', workbook]);
    const imported = await foundryJson(foundry, isolatedVar, 'report-xlsx-read', ['--source', added.source.id]);
    if (!imported.warnings.join('\n').includes('公式没有缓存值')) throw new Error('formula cache warning absent');
  }));
  return cases;
}

async function captures(name, run) {
  try {
    await run();
    return { name, ok: true };
  } catch (error) {
    return { name, ok: false, message: error instanceof Error ? error.message : String(error) };
  }
}

async function expectRejects(run, expected) {
  try {
    await run();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (!message.includes(expected)) throw error;
    return;
  }
  throw new Error(`expected rejection containing ${expected}`);
}

async function createFormulaMissingWorkbook(file) {
  await execFileText('uv', ['run', 'python', '-c', [
    'from openpyxl import Workbook',
    'from pathlib import Path',
    'import sys',
    'wb = Workbook()',
    'ws = wb.active',
    'ws.title = "公式缺缓存"',
    'ws["A1"] = "项目"',
    'ws["B1"] = "金额"',
    'ws["A2"] = "公式没有缓存值"',
    'ws["B2"] = "=SUM(1,2)"',
    'Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)',
    'wb.save(sys.argv[1])',
  ].join('\n'), file], { cwd: repoRoot });
}

function minimalPdf(text) {
  const escaped = text.replace(/[()\\]/g, '\\$&');
  const stream = `BT /F1 18 Tf 72 760 Td (${escaped}) Tj ET`;
  const objects = [
    '1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n',
    '2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n',
    '3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n',
    '4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n',
    `5 0 obj\n<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream\nendobj\n`,
  ];
  let output = '%PDF-1.4\n';
  const offsets = [0];
  for (const object of objects) {
    offsets.push(Buffer.byteLength(output));
    output += object;
  }
  const xref = Buffer.byteLength(output);
  output += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (let index = 1; index < offsets.length; index += 1) {
    output += `${String(offsets[index]).padStart(10, '0')} 00000 n \n`;
  }
  output += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(output);
}

async function hashDirectory(dir, include) {
  const files = await listFiles(dir);
  const rows = [];
  for (const file of files.filter(include).sort()) {
    const data = await readFile(file);
    rows.push({ path: file, sha256: sha256(data), bytes: data.length });
  }
  return rows;
}

async function listFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...await listFiles(full));
    else if (entry.isFile()) files.push(full);
  }
  return files;
}

function pickPropertyWorkbook(hashes) {
  const picked = hashes.find((row) => row.path.includes('月结财务套表') && row.path.endsWith('.xlsx')) ?? hashes.find((row) => row.path.endsWith('.xlsx'));
  if (!picked) throw new Error('No property XLSX source found for report workflow verification.');
  return picked.path;
}

function deterministicSourceId(format) {
  return createHash('md5').update(`roundtrip:${format}:${randomUUID()}`).digest('hex');
}

function record(failures, passed, check, detail) {
  if (!passed) failures.push({ check, detail });
}

function sha256(data) {
  return createHash('sha256').update(data).digest('hex');
}

async function readJson(file) {
  return JSON.parse(await readFile(file, 'utf8'));
}
