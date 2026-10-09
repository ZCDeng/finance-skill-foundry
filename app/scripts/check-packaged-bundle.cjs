#!/usr/bin/env node
// Validate that a packed .app carries everything it runs, on a Mac that has nothing else.
//
// electron-builder's afterPack hook, after the font check, and usable by hand on an
// installed app. No runtime is started: this reads the tree. What a clean machine
// does with that tree is `tools/verify_standalone_bundle.cjs`.
//
// Every entry below is something a release went out without, or would have gone out
// without silently: the app starts, and one screen never works.
const {closeSync, lstatSync, openSync, readdirSync, readSync} = require('node:fs');
const {join, relative, resolve} = require('node:path');
const {checkPackagedFont} = require('./check-packaged-font.cjs');

/** Files and directories under Contents/Resources, and who reads them. */
const REQUIRED = [
  // The frozen CLI and the resources tree `foundry/resources.py` resolves into.
  'foundry/foundry',
  ...['demo_pack', 'fixtures', 'method', 'dsh-plugin', 'formulator-plugin', 'templates', 'data_templates']
    .map((name) => `foundry/_internal/foundry/resources/${name}/`),
  'foundry/_internal/foundry/resources/method/FOUNDRY.md',
  // Data Formulator and the frontend `app.py` serves from `__file__`.
  'formulator/data_formulator',
  'formulator/_internal/data_formulator/dist/index.html',
  'formulator/_internal/foundry/',
  // The harness, the period bundle's staged copy, and the Univer preview's three artifacts.
  'dsh/PIN',
  'dsh/node_modules/@deepseek-ai/dsh/lib/bin.js',
  'dsh/node_modules/finance-skill-foundry-dsh/package.json',
  'dsh/node_modules/dsh-univer-office/artifacts/gateway.cjs',
  'dsh/node_modules/dsh-univer-office/artifacts/unit-content-worker.mjs',
  'dsh/node_modules/dsh-univer-office/artifacts/viewer/index.html',
  // What each harness profile symlinks to.
  'dsh-plugin/package.json',
  // Font licenses beside the fonts (OFL §2): Noto Sans SC twice, Asap Sharp. IBM Plex Mono's is hash-checked by the font check.
  'fonts/OFL.txt',
  'fonts/asap-sharp/OFL.txt',
  'dsh/assets/fonts/OFL.txt',
];

/**
 * What the main process `require`s from the archive. electron-builder copies the
 * production `node_modules` in on its own; a change to `files` or to how the main
 * process is built could quietly stop that, and only report import would notice.
 */
const ASAR_REQUIRED = [
  'dist-electron/main.js',
  'dist-vite/index.html',
  'node_modules/pdfjs-dist/legacy/build/pdf.mjs',
  'node_modules/mammoth/package.json',
  'node_modules/docx/package.json',
  'node_modules/linkedom/package.json',
  'node_modules/@modelcontextprotocol/sdk/package.json',
];

/** The renderer's faces, which Vite renames with a hash: one prefix per file `fonts.css` names. */
const RENDERER_FONTS = [
  'NotoSansSC-variable',
  'asap-000',
  'asap-001',
  'asap-002',
  'IBMPlexMono-Regular',
  'IBMPlexMono-SemiBold',
  'IBMPlexMono-Bold',
];

const CPU_X86_64 = 0x01000007;
const CPU_ARM64 = 0x0100000c;
const CPU_NAMES = {[CPU_X86_64]: 'x86_64', [CPU_ARM64]: 'arm64'};

/** The architectures of a Mach-O file, or null when it is not one. */
function machoArchs(path) {
  const fd = openSync(path, 'r');
  try {
    const head = Buffer.alloc(8);
    if (readSync(fd, head, 0, 8, 0) < 8) return null;
    const magicBE = head.readUInt32BE(0);
    if (magicBE === 0xcafebabe || magicBE === 0xcafebabf) {
      // Java class files share this magic; their second word is a version, far above any arch count.
      const count = head.readUInt32BE(4);
      if (count === 0 || count > 16) return null;
      const size = magicBE === 0xcafebabe ? 20 : 32;
      const table = Buffer.alloc(count * size);
      readSync(fd, table, 0, table.length, 8);
      return Array.from({length: count}, (_, i) => table.readUInt32BE(i * size));
    }
    if (magicBE === 0xbebafeca || magicBE === 0xbfbafeca) {
      // A fat header written little-endian. Nothing produces these, but nothing forbids them.
      const count = head.readUInt32LE(4);
      if (count === 0 || count > 16) return null;
      const size = magicBE === 0xbebafeca ? 20 : 32;
      const table = Buffer.alloc(count * size);
      readSync(fd, table, 0, table.length, 8);
      return Array.from({length: count}, (_, i) => table.readUInt32LE(i * size));
    }
    const magicLE = head.readUInt32LE(0);
    if (magicLE === 0xfeedfacf || magicLE === 0xfeedface) return [head.readUInt32LE(4)];
    // Big-endian thin files (PowerPC, say): the same magic, byte-swapped, and a big-endian CPU type.
    if (magicBE === 0xfeedfacf || magicBE === 0xfeedface) return [head.readUInt32BE(4)];
    return null;
  } finally {
    closeSync(fd);
  }
}

/** Every Mach-O file under `root` that has no arm64 slice. Symlinks are skipped: their targets are walked. */
function nonArm64(root) {
  const out = [];
  let count = 0;
  const walk = (dir) => {
    for (const entry of readdirSync(dir, {withFileTypes: true})) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (entry.isFile()) {
        const archs = machoArchs(path);
        if (archs === null) continue;
        count += 1;
        if (!archs.includes(CPU_ARM64)) {
          out.push(`${relative(root, path)} (${archs.map((cpu) => CPU_NAMES[cpu] ?? `0x${cpu.toString(16)}`).join(', ')})`);
        }
      }
    }
  };
  walk(root);
  return {count, offenders: out};
}

function asarEntries(archive) {
  const asar = require('@electron/asar');
  return new Set(asar.listPackage(archive, {isPack: false}).map((entry) => entry.replace(/^[\\/]/, '').split('\\').join('/')));
}


function checkPackagedBundle(appPath) {
  const app = resolve(appPath);
  const resources = join(app, 'Contents/Resources');
  const problems = [];

  for (const entry of REQUIRED) {
    const wantDir = entry.endsWith('/');
    try {
      const stat = lstatSync(join(resources, entry));
      if (wantDir ? !stat.isDirectory() : !stat.isFile()) problems.push(`not a ${wantDir ? 'directory' : 'file'}: ${entry}`);
    } catch {
      problems.push(`missing: ${entry}`);
    }
  }

  const archive = join(resources, 'app.asar');
  let entries;
  try {
    entries = asarEntries(archive);
  } catch (error) {
    problems.push(`app.asar unreadable: ${error.message}`);
  }
  if (entries) {
    for (const entry of ASAR_REQUIRED) if (!entries.has(entry)) problems.push(`missing in app.asar: ${entry}`);
    const fonts = [...entries].filter((entry) => entry.startsWith('dist-vite/') && entry.endsWith('.woff2'));
    for (const face of RENDERER_FONTS) {
      if (!fonts.some((entry) => entry.split('/').pop().startsWith(`${face}-`) || entry.endsWith(`/${face}.woff2`))) {
        problems.push(`renderer font not in app.asar: ${face}.woff2`);
      }
    }
  }

  const {count, offenders} = nonArm64(app);
  if (count === 0) problems.push('no Mach-O files found: not a packed macOS app');
  for (const offender of offenders) problems.push(`not arm64: ${offender}`);

  if (problems.length) throw new Error(`Packaged bundle is incomplete:\n  ${problems.join('\n  ')}`);
  return {status: 'passed', appPath: app, required: REQUIRED.length + ASAR_REQUIRED.length, rendererFonts: RENDERER_FONTS.length, machO: count};
}

async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin') return;
  const app = join(context.appOutDir, context.packager.appInfo.productFilename + '.app');
  console.log(JSON.stringify({check: 'packaged_native_font', ...checkPackagedFont(app)}));
  console.log(JSON.stringify({check: 'packaged_bundle', ...checkPackagedBundle(app)}));
}
module.exports = afterPack;
module.exports.checkPackagedBundle = checkPackagedBundle;
module.exports.machoArchs = machoArchs;

if (require.main === module) {
  try {
    if (process.argv.length !== 3) throw new Error('Usage: node app/scripts/check-packaged-bundle.cjs /absolute/path/FA\u00a0Foundry.app');
    console.log(JSON.stringify(checkPackagedFont(process.argv[2])));
    console.log(JSON.stringify(checkPackagedBundle(process.argv[2])));
  } catch (error) {
    console.error(JSON.stringify({status: 'failed', error: error.message}));
    process.exitCode = 1;
  }
}
