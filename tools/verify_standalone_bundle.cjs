#!/usr/bin/env node
// Does a packed FA Foundry run on a Mac that has nothing but macOS?
//
//   node tools/verify_standalone_bundle.cjs "/Applications/FA Foundry.app"
//
// The release checks before this one (`verify_native_workspace.cjs`, the E2E run)
// launch the app with the developer's own environment, so a bundle that leans on
// a Homebrew Python, a system Node or a cached DuckDB extension passes them. This
// one gives every step an empty HOME and `PATH=/usr/bin:/bin`, and watches what
// the app starts and what it connects to.
//
// Steps: the static bundle check; the frozen CLI's own probe; a GBK 收费明细 through
// to a collection rate; PDF and DOCX through the report converters inside app.asar;
// the frozen Formulator serving the locked-catalog connector; a cold start of the
// app itself, sampling its processes and sockets. No DeepSeek key is configured or
// needed: the only remote host the app should ever reach is the model API, and only
// once one is.
'use strict';

const {execFileSync, spawn} = require('node:child_process');
const {existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join, resolve} = require('node:path');
const {checkPackagedBundle} = require('../app/scripts/check-packaged-bundle.cjs');
const {checkPackagedFont} = require('../app/scripts/check-packaged-font.cjs');

const KIT = resolve(__dirname, '..');
const app = resolve(process.argv[2] ?? '/Applications/FA Foundry.app');
const resources = join(app, 'Contents/Resources');
const executable = join(app, 'Contents/MacOS', require(join(KIT, 'app/package.json')).productName);
const foundry = join(resources, 'foundry/foundry');
const formulator = join(resources, 'formulator/data_formulator');
const scratch = mkdtempSync(join(tmpdir(), 'fa-standalone-'));
const home = join(scratch, 'home');
mkdirSync(home);
/** Nothing from this shell: no node, no python, no brew, no virtualenv. */
const BARE = {HOME: home, PATH: '/usr/bin:/bin', TMPDIR: join(scratch, 'tmp') + '/'};
mkdirSync(BARE.TMPDIR);

const results = [];
async function step(name, body) {
  const started = Date.now();
  try {
    const detail = await body();
    results.push({step: name, ok: true, detail, ms: Date.now() - started});
    console.log(`✓ ${name}${detail ? `: ${detail}` : ''}`);
  } catch (error) {
    results.push({step: name, ok: false, error: error.message, ms: Date.now() - started});
    console.log(`✗ ${name}: ${error.message}`);
  }
}

const cli = (vars, args) =>
  execFileSync(foundry, ['--var', vars, ...args], {encoding: 'utf8', env: BARE, stdio: ['ignore', 'pipe', 'pipe']}).trim();

const LOOPBACK = /^(127\.0\.0\.1|\[::1\]|localhost):/;

/**
 * Every socket `pids` hold that reaches past this machine: a connection to another
 * host, or a server listening on anything but loopback.
 */
function remoteSockets(pids) {
  if (pids.length === 0) return [];
  let out = '';
  try {
    out = execFileSync('/usr/sbin/lsof', ['-nP', '-a', '-i', '-p', pids.join(',')], {encoding: 'utf8'});
  } catch (error) {
    out = String(error.stdout ?? ''); // lsof exits 1 when nothing matched
  }
  const found = [];
  for (const line of out.split('\n').slice(1).filter(Boolean)) {
    const fields = line.trim().split(/\s+/);
    const connection = fields.find((field) => field.includes('->'));
    if (connection && !LOOPBACK.test(connection.split('->')[1])) found.push(connection);
    if (!connection && line.includes('(LISTEN)')) {
      const address = fields[fields.indexOf('(LISTEN)') - 1];
      if (!LOOPBACK.test(address)) found.push(`listening on ${address}`);
    }
  }
  return found;
}

/** The pid and every descendant, with each one's command line, from one `ps` snapshot. */
function tree(root) {
  const rows = execFileSync('/bin/ps', ['-axo', 'pid=,ppid=,command='], {encoding: 'utf8', maxBuffer: 16 << 20}).split('\n')
    .map((line) => line.trim().match(/^(\d+)\s+(\d+)\s+(.*)$/)).filter(Boolean)
    .map(([, pid, ppid, command]) => ({pid: Number(pid), ppid: Number(ppid), command}));
  const found = new Map([[root, rows.find((row) => row.pid === root)?.command ?? '']]);
  for (let grew = true; grew;) {
    grew = false;
    for (const row of rows) if (found.has(row.ppid) && !found.has(row.pid)) { found.set(row.pid, row.command); grew = true; }
  }
  return found;
}

/**
 * A process run from neither this bundle nor macOS is something the bundle leaned on:
 * a system node, a Homebrew python, a `foundry` on PATH.
 */
function foreignProcesses(commands) {
  return commands.filter((command) => command && !command.startsWith(app) && !/^\/(usr|bin|sbin|System)\//.test(command));
}

/** A one-page PDF with one line of selectable Helvetica text. */
function minimalPdf(text) {
  const stream = `BT /F1 18 Tf 72 720 Td (${text}) Tj ET`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ];
  let body = '%PDF-1.4\n';
  const offsets = objects.map((object, i) => { const at = body.length; body += `${i + 1} 0 obj\n${object}\nendobj\n`; return at; });
  const xref = body.length;
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map((at) => `${String(at).padStart(10, '0')} 00000 n \n`).join('')}`;
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body, 'latin1');
}

/**
 * Run the report worker from inside app.asar on the app's own Node.
 *
 * The main process starts the same file as a worker_thread; here it is started the
 * same way from an ELECTRON_RUN_AS_NODE process, which reads the archive the same
 * way. That is the path no repo test takes: `pdfjs-dist` is an ES module the
 * CommonJS-compiled converter reaches with `require`, from inside an archive.
 */
function convert(operation, payload) {
  const driver = join(scratch, 'convert.cjs');
  writeFileSync(driver, `
    const {Worker} = require('node:worker_threads');
    const input = JSON.parse(require('node:fs').readFileSync(process.argv[2], 'utf8'));
    if (input.payload.data) input.payload.data = Buffer.from(input.payload.data, 'base64');
    const worker = new Worker(${JSON.stringify(join(resources, 'app.asar/dist-electron/reports/worker.js'))}, {workerData: input});
    worker.once('message', (m) => {
      if (m.value instanceof Uint8Array) m.value = {base64: Buffer.from(m.value).toString('base64')};
      process.stdout.write(JSON.stringify(m));
      process.exit(0);
    });
    worker.once('error', (e) => { process.stdout.write(JSON.stringify({ok: false, message: String(e && e.stack || e)})); process.exit(0); });
  `);
  const input = join(scratch, `${operation}-${Date.now()}.json`);
  writeFileSync(input, JSON.stringify({operation, payload}));
  const out = execFileSync(executable, [driver, input], {encoding: 'utf8', env: {...BARE, ELECTRON_RUN_AS_NODE: '1'}, timeout: 120_000});
  const message = JSON.parse(out);
  if (!message.ok) throw new Error(`${operation}: ${message.message}`);
  return message.value;
}

const textOf = (node) => node.text ?? (node.content ?? []).map(textOf).join('');

async function main() {
  if (process.platform !== 'darwin') throw new Error('run this on the Mac the app is for');
  if (!existsSync(executable)) throw new Error(`no app at ${app}`);
  console.log(`checking ${app} with HOME=${home} PATH=${BARE.PATH}`);

  await step('bundle carries every file it runs, all arm64', () => {
    checkPackagedFont(app);
    const result = checkPackagedBundle(app);
    return `${result.machO} Mach-O files`;
  });

  await step('frozen CLI probe', () => { cli(join(scratch, 'probe-var'), ['probe']); });

  await step('GBK 收费明细 to a collection rate', () => {
    const vars = join(scratch, 'collection-var');
    const files = join(scratch, 'collection-files');
    mkdirSync(files, {recursive: true});
    const csv = (lines) => lines.join('\r\n') + '\r\n';
    writeFileSync(join(files, '应收.csv'), execFileSync('/usr/bin/iconv', ['-f', 'UTF-8', '-t', 'GBK'], {input: csv([
      '应收单号,房产编号,收费项目,账期,应收原额,减免额,应收净额,单据状态',
      'B1,P1,住宅物业服务费,2026-01,100,0,100,正常',
      'B2,P2,住宅物业服务费,2026-02,200,0,200,正常',
    ])}));
    writeFileSync(join(files, '实收.csv'), csv([
      '收款单号,收款日期,应收单号,收款金额,收款方式,款项性质',
      'R1,2026-01-15,B1,100,微信,当期',
    ]));
    const task = cli(vars, ['task-new', '--title', 'standalone']);
    const as = ['--task', task, '--actor', 'manager'];
    const ids = {};
    for (const [kind, name] of [['receivable', '应收'], ['receipt', '实收']]) {
      const added = JSON.parse(cli(vars, [...as, 'detail-add', '--kind', kind, '--name', name, '--path', join(files, `${name}.csv`)]));
      if (kind === 'receivable' && added.files?.[0]?.encoding !== 'gb18030') throw new Error(`应收 read as ${added.files?.[0]?.encoding}`);
      ids[kind] = added.id;
      cli(vars, [...as, 'detail-confirm', '--detail', added.id]);
    }
    const rate = JSON.parse(cli(vars, [...as, 'collection-run', '--spec', JSON.stringify({...ids, as_of: '2026-08-31'})])).result.figures.collection_rate_current;
    if (rate !== '0.3333') throw new Error(`当期收缴率 ${rate}, expected 0.3333`);
    if (existsSync(join(home, '.duckdb'))) throw new Error('DuckDB downloaded an extension into HOME');
    return `当期收缴率 ${rate}`;
  });

  await step('PDF import inside app.asar', () => {
    const value = convert('import', {
      data: minimalPdf('FA Foundry standalone').toString('base64'), format: 'pdf',
      source: {id: 'pdf', name: 'standalone.pdf', sha256: '0'.repeat(64), format: 'pdf'},
    });
    const text = textOf(value.document);
    if (!text.includes('FA Foundry standalone')) throw new Error(`extracted ${JSON.stringify(text.slice(0, 80))}`);
    return 'text extracted';
  });

  await step('DOCX export and import inside app.asar', () => {
    const document = convert('markdown', {body: '# 检查\n\n独立分发检查 1,234.56\n'});
    const exported = convert('docx', {document, title: '检查', options: {}});
    const value = convert('import', {
      data: exported.base64, format: 'docx',
      source: {id: 'docx', name: 'standalone.docx', sha256: '0'.repeat(64), format: 'docx'},
    });
    const text = textOf(value.document);
    if (!text.includes('独立分发检查 1,234.56')) throw new Error(`round trip gave ${JSON.stringify(text.slice(0, 80))}`);
    return 'round trip intact';
  });

  await step('frozen Formulator serves the locked catalog', async () => {
    const out = execFileSync(process.execPath, [join(KIT, 'app/scripts/gate-formulator.mjs'), '--bin', foundry, '--formulator', formulator, '--var', join(scratch, 'gate-var')], {
      encoding: 'utf8', env: {...BARE, PATH: BARE.PATH}, timeout: 180_000,
    });
    const connectors = out.match(/connectors: (.*)/)?.[1] ?? '';
    return connectors ? `connectors: ${connectors}` : undefined;
  });

  await step('cold start: harness up, nothing foreign started, no remote sockets', async () => {
    const userData = join(scratch, 'user-data');
    const child = spawn(executable, [`--user-data-dir=${userData}`], {env: BARE, stdio: ['ignore', 'pipe', 'pipe']});
    let output = '';
    child.stdout.on('data', (chunk) => { output += chunk; });
    child.stderr.on('data', (chunk) => { output += chunk; });
    const seen = new Map();
    const remote = new Set();
    let harness = false;
    try {
      for (let i = 0; i < 20; i += 1) {
        await new Promise((r) => setTimeout(r, 3000));
        if (child.exitCode !== null) throw new Error(`the app exited with ${child.exitCode}: ${output.slice(-400)}`);
        const processes = tree(child.pid);
        for (const [pid, command] of processes) seen.set(pid, command);
        for (const socket of remoteSockets([...processes.keys()])) remote.add(socket);
        const dsh = [...processes.values()].some((command) => command.includes('@deepseek-ai/dsh/lib/bin.js'));
        if (dsh && existsSync(join(userData, 'harness', 'profiles'))) harness = true;
      }
    } finally {
      child.kill('SIGTERM');
      await new Promise((r) => setTimeout(r, 3000));
      if (child.exitCode === null) child.kill('SIGKILL');
    }
    const problems = [];
    if (!harness) problems.push('the harness never started from the bundle with a profile');
    const foreign = foreignProcesses([...seen.values()]);
    if (foreign.length) problems.push(`started outside the bundle: ${[...new Set(foreign)].map((command) => command.slice(0, 120)).join(', ')}`);
    if (remote.size) problems.push(`remote sockets: ${[...remote].join(', ')}`);
    const errors = output.split('\n').filter((line) => /ENOENT|Cannot find module|not found|ERR_/.test(line));
    if (errors.length) problems.push(`errors on stdout/stderr: ${errors.slice(0, 5).join(' | ')}`);
    const leftovers = ['.duckdb', '.npm', '.cache', '.local'].filter((name) => existsSync(join(home, name)));
    if (leftovers.length) problems.push(`wrote into HOME: ${leftovers.join(', ')}`);
    if (problems.length) throw new Error(problems.join('; '));
    return `${seen.size} processes, all from the bundle or macOS`;
  });
}

main()
  .catch((error) => results.push({step: 'setup', ok: false, error: error.message}))
  .finally(() => {
    const failed = results.filter((result) => !result.ok);
    const report = join(scratch, 'report.json');
    writeFileSync(report, JSON.stringify({app, version: readVersion(), results}, null, 2));
    console.log(`\n${results.length - failed.length}/${results.length} passed; report ${report}`);
    if (failed.length === 0) rmSync(join(scratch, 'home'), {recursive: true, force: true});
    process.exitCode = failed.length ? 1 : 0;
  });

function readVersion() {
  try {
    return execFileSync('/usr/bin/defaults', ['read', join(app, 'Contents/Info'), 'CFBundleShortVersionString'], {encoding: 'utf8'}).trim();
  } catch {
    return null;
  }
}
