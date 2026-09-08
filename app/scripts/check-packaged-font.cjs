#!/usr/bin/env node
// Validate the final .app resource tree, after electron-builder copied filters.
// Also usable as electron-builder's afterPack hook; no runtime is started.
const {createHash} = require('node:crypto');
const {lstatSync, readFileSync} = require('node:fs');
const {join, resolve} = require('node:path');
const manifest = require('../src/assets/fonts/noto-sans-sc/manifest.json');
const reportFont = require('../src/assets/fonts/noto-sans-sc/report-font.json');

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
  return {status:'passed', appPath:resolve(appPath), fontPath, bytes:stat.size, sha256, reportFontPath, reportFontSha256: reportSha256};
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
