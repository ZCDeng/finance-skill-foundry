import {copyFileSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {afterEach, describe, expect, it} from 'vitest';

const require = createRequire(import.meta.url);
const {checkPackagedFont} = require('../scripts/check-packaged-font.cjs');
const source = fileURLToPath(new URL('../src/assets/fonts/noto-sans-sc/NotoSansSC-variable.woff2', import.meta.url));
const reportSource = fileURLToPath(new URL('../src/assets/fonts/noto-sans-sc/NotoSansSC-report.ttf', import.meta.url));
const dirs: string[] = [];
function fixture() {
  const base = mkdtempSync(join(tmpdir(), 'foundry-packed-font-'));
  dirs.push(base);
  const app = join(base, 'FA Foundry.app');
  const folder = join(app, 'Contents/Resources/dsh/assets/fonts');
  mkdirSync(folder, {recursive:true});
  const reportFolder = join(app, 'Contents/Resources/fonts');
  mkdirSync(reportFolder, {recursive:true});
  return {app, font:join(folder, 'NotoSansSC-variable.woff2'), reportFont:join(reportFolder, 'NotoSansSC-report.ttf')};
}
afterEach(() => { for (const dir of dirs.splice(0)) rmSync(dir, {recursive:true, force:true}); });

describe('final packaged native font', () => {
  it('checks copied final resources against the approved font hash and length', () => {
    const {app, font, reportFont} = fixture();
    copyFileSync(source, font);
    copyFileSync(reportSource, reportFont);
    expect(checkPackagedFont(app)).toMatchObject({status:'passed', bytes:8490924, sha256:'97a715fad95d3cacf4838b1ffedb123d2f1bf0f6bbd726c73e147dcaf317869f'});
  });
  it('refuses a modified Word embedding font', () => {
    const {app, font, reportFont} = fixture();
    copyFileSync(source, font);
    writeFileSync(reportFont, 'invalid');
    expect(() => checkPackagedFont(app)).toThrow('embeddable font');
  });
  it('refuses a missing final font even when the source and staging font exist', () => {
    expect(() => checkPackagedFont(fixture().app)).toThrow('Packaged native font missing');
  });
  it('refuses truncated resources and external symlinks', () => {
    const {app, font} = fixture();
    writeFileSync(font, 'wOF2');
    expect(() => checkPackagedFont(app)).toThrow('differs from the approved offline font');
    rmSync(font);
    symlinkSync(source, font);
    expect(() => checkPackagedFont(app)).toThrow('regular bundled file');
  });
});
