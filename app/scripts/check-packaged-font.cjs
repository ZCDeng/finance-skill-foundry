#!/usr/bin/env node
// Validate the final .app resource tree, after electron-builder copied filters.
// Also usable as electron-builder's afterPack hook; no runtime is started.
const {createHash} = require('node:crypto');
const {lstatSync, readFileSync} = require('node:fs');
const {join, resolve} = require('node:path');
const manifest = require('../src/assets/fonts/noto-sans-sc/manifest.json');
const reportFont = require('../src/assets/fonts/noto-sans-sc/report-font.json');
const figureFont = require('../src/assets/fonts/ibm-plex-mono/manifest.json');

function checkBundled(path, bytes, sha256, label) {
  let stat;
  try { stat = lstatSync(path); }
  catch (error) { throw new Error(`Packaged ${label} missing: ${path}`, {cause:error}); }
  const digest = createHash('sha256').update(readFileSync(path)).digest('hex');
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size !== bytes || digest !== sha256) {
    throw new Error(`Packaged ${label} differs from the publisher's file: ${path}`);
  }
}

function checkPackagedFont(appPath) {
  const fontPath = join(resolve(appPath), 'Contents/Resources/dsh/assets/fonts', manifest.output.file);
  let stat;
  try { stat = lstatSync(fontPath); }
  catch (error) { throw new Error(`Packaged native font missing: ${fontPath}`, {cause:error}); }
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`Packaged native font must be a regular bundled file: ${fontPath}`);
  const sha256 = createHash('sha256').update(readFileSync(fontPath)).digest('hex');
  if (stat.size !== manifest.output.bytes || sha256 !== manifest.output.sha256) {
    throw new Error(`Packaged native font differs from the approved offline font: ${fontPath} (${stat.size} bytes; SHA256 ${sha256})`);
  }
  const reportFontPath = join(resolve(appPath), 'Contents/Resources/fonts', reportFont.file);
  const reportStat = lstatSync(reportFontPath);
  const reportSha256 = createHash('sha256').update(readFileSync(reportFontPath)).digest('hex');
  if (!reportStat.isFile() || reportStat.isSymbolicLink() || reportStat.size !== reportFont.bytes || reportSha256 !== reportFont.sha256) {
    throw new Error(`Packaged report font differs from the approved embeddable font: ${reportFontPath}`);
  }
  // IBM Plex Mono for report exports: the three WOFF2 faces HTML and PDF embed, and the TrueType face Word embeds.
  const figureFolder = join(resolve(appPath), 'Contents/Resources/fonts/ibm-plex-mono');
  for (const face of [...figureFont.faces, figureFont.word]) checkBundled(join(figureFolder, face.file), face.bytes, face.sha256, 'figure font');
  checkBundled(join(figureFolder, figureFont.license.file), readFileSync(join(__dirname, '../src/assets/fonts/ibm-plex-mono', figureFont.license.file)).length, figureFont.license.sha256, 'figure font license');
  return {status:'passed', appPath:resolve(appPath), fontPath, bytes:stat.size, sha256, reportFontPath, reportFontSha256: reportSha256, figureFonts: figureFont.faces.length + 1};
}

async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin') return;
  const result = checkPackagedFont(join(context.appOutDir, context.packager.appInfo.productFilename + '.app'));
  console.log(JSON.stringify({check:'packaged_native_font', ...result}));
}
module.exports = afterPack;
module.exports.checkPackagedFont = checkPackagedFont;

if (require.main === module) {
  try {
    if (process.argv.length !== 3) throw new Error('Usage: node app/scripts/check-packaged-font.cjs /absolute/path/FA\u00a0Foundry.app');
    console.log(JSON.stringify(checkPackagedFont(process.argv[2])));
  } catch (error) {
    console.error(JSON.stringify({status:'failed', error:error.message}));
    process.exitCode = 1;
  }
}
