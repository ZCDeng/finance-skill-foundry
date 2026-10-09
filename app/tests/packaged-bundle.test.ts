import {mkdirSync, mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {tmpdir} from 'node:os';
import {createRequire} from 'node:module';
import {afterEach, describe, expect, it} from 'vitest';

const require = createRequire(import.meta.url);
const {checkPackagedBundle, machoArchs} = require('../scripts/check-packaged-bundle.cjs');
const asar = require('@electron/asar');

const ARM64 = 0x0100000c;
const X86_64 = 0x01000007;

/** A thin 64-bit Mach-O header for one CPU, which is all the check reads. */
function thin(cpu: number): Buffer {
  const head = Buffer.alloc(32);
  head.writeUInt32LE(0xfeedfacf, 0);
  head.writeUInt32LE(cpu, 4);
  return head;
}

function fat(cpus: number[]): Buffer {
  const head = Buffer.alloc(8 + cpus.length * 20);
  head.writeUInt32BE(0xcafebabe, 0);
  head.writeUInt32BE(cpus.length, 4);
  cpus.forEach((cpu, i) => head.writeUInt32BE(cpu, 8 + i * 20));
  return head;
}

const RESOURCE_FILES = [
  'foundry/foundry',
  'foundry/_internal/foundry/resources/method/FOUNDRY.md',
  'formulator/data_formulator',
  'formulator/_internal/data_formulator/dist/index.html',
  'formulator/_internal/foundry/__init__.pyc',
  'dsh/PIN',
  'dsh/node_modules/@deepseek-ai/dsh/lib/bin.js',
  'dsh/node_modules/finance-skill-foundry-dsh/package.json',
  'dsh/node_modules/dsh-univer-office/artifacts/gateway.cjs',
  'dsh/node_modules/dsh-univer-office/artifacts/unit-content-worker.mjs',
  'dsh/node_modules/dsh-univer-office/artifacts/viewer/index.html',
  'dsh-plugin/package.json',
  'fonts/OFL.txt',
  'fonts/asap-sharp/OFL.txt',
  'dsh/assets/fonts/OFL.txt',
  ...['demo_pack', 'fixtures', 'dsh-plugin', 'formulator-plugin', 'templates', 'data_templates']
    .map((name) => `foundry/_internal/foundry/resources/${name}/.keep`),
];

const ASAR_FILES: Record<string, string> = {
  'dist-electron/main.js': '',
  'dist-vite/index.html': '',
  'node_modules/pdfjs-dist/legacy/build/pdf.mjs': '',
  'node_modules/mammoth/package.json': '{}',
  'node_modules/docx/package.json': '{}',
  'node_modules/linkedom/package.json': '{}',
  'node_modules/@modelcontextprotocol/sdk/package.json': '{}',
  ...Object.fromEntries(
    ['NotoSansSC-variable', 'asap-000', 'asap-001', 'asap-002', 'IBMPlexMono-Regular', 'IBMPlexMono-SemiBold', 'IBMPlexMono-Bold']
      .map((face) => [`dist-vite/assets/${face}-Hx1.woff2`, 'wOF2']),
  ),
};

const dirs: string[] = [];
afterEach(() => { for (const dir of dirs.splice(0)) rmSync(dir, {recursive: true, force: true}); });

function put(path: string, content: string | Buffer) {
  mkdirSync(dirname(path), {recursive: true});
  writeFileSync(path, content);
}

async function fixture(options: {asarFiles?: Record<string, string>} = {}) {
  const base = mkdtempSync(join(tmpdir(), 'foundry-packed-bundle-'));
  dirs.push(base);
  const app = join(base, 'FA Foundry.app');
  const resources = join(app, 'Contents/Resources');
  for (const file of RESOURCE_FILES) put(join(resources, file), '');
  put(join(resources, 'foundry/foundry'), thin(ARM64));
  put(join(resources, 'formulator/data_formulator'), thin(ARM64));
  put(join(app, 'Contents/MacOS/FA Foundry'), thin(ARM64));
  const source = join(base, 'asar-source');
  for (const [file, content] of Object.entries(options.asarFiles ?? ASAR_FILES)) put(join(source, file), content);
  await asar.createPackage(source, join(resources, 'app.asar'));
  return {app, resources};
}

describe('packaged bundle completeness', () => {
  it('passes a bundle that carries everything', async () => {
    const {app} = await fixture();
    expect(checkPackagedBundle(app)).toMatchObject({status: 'passed', machO: 3});
  });

  it('names a missing service binary and a missing resources directory', async () => {
    const {app, resources} = await fixture();
    rmSync(join(resources, 'formulator/data_formulator'));
    rmSync(join(resources, 'foundry/_internal/foundry/resources/demo_pack'), {recursive: true});
    expect(() => checkPackagedBundle(app)).toThrow('missing: foundry/_internal/foundry/resources/demo_pack/');
    expect(() => checkPackagedBundle(app)).toThrow('missing: formulator/data_formulator');
  });

  it('refuses an Intel-only Mach-O file and accepts a universal one', async () => {
    const {app, resources} = await fixture();
    put(join(resources, 'dsh/node_modules/x/universal.node'), fat([X86_64, ARM64]));
    expect(checkPackagedBundle(app).status).toBe('passed');
    put(join(resources, 'dsh/node_modules/node-pty/prebuilds/darwin-x64/pty.node'), thin(X86_64));
    expect(() => checkPackagedBundle(app)).toThrow('not arm64: Contents/Resources/dsh/node_modules/node-pty/prebuilds/darwin-x64/pty.node (x86_64)');
  });

  it('does not mistake a Java class file for a universal binary', () => {
    const base = mkdtempSync(join(tmpdir(), 'foundry-packed-bundle-'));
    dirs.push(base);
    const path = join(base, 'A.class');
    const head = Buffer.alloc(8);
    head.writeUInt32BE(0xcafebabe, 0);
    head.writeUInt32BE(0x00000034, 4);
    writeFileSync(path, head);
    expect(machoArchs(path)).toBeNull();
  });

  it('names a main-process dependency missing from the archive', async () => {
    const {'node_modules/pdfjs-dist/legacy/build/pdf.mjs': _, ...rest} = ASAR_FILES;
    const {app} = await fixture({asarFiles: rest});
    expect(() => checkPackagedBundle(app)).toThrow('missing in app.asar: node_modules/pdfjs-dist/legacy/build/pdf.mjs');
  });

  it('refuses a renderer face Vite never emitted', async () => {
    const {'dist-vite/assets/asap-001-Hx1.woff2': _, ...rest} = ASAR_FILES;
    const {app} = await fixture({asarFiles: rest});
    expect(() => checkPackagedBundle(app)).toThrow('renderer font not in app.asar: asap-001.woff2');
  });
});
