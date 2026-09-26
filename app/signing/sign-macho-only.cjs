// Custom mac sign hook for `npm run package:signed`.
// @electron/osx-sign signs every file that `isbinaryfile` calls binary. In this bundle that is
// ~2,000 data files (botocore .json.gz, fonts, compiled Python) next to 341 real Mach-O files out
// of ~21,500, and each extra file costs a timestamp-server round trip; the Apple TSA starts
// refusing ("The timestamp service is not available") long before the walk ends. Only Mach-O
// code needs a signature; data files are still sealed by the app bundle's CodeResources.
// Everything else is electron-builder's own options and signer (which retries).
const fs = require('node:fs');
const { sign } = require('app-builder-lib/out/codeSign/macCodeSign');

const THIN = new Set(['feedface', 'feedfacf', 'cefaedfe', 'cffaedfe']);

function isMachO(file) {
  let stat;
  try { stat = fs.statSync(file); } catch { return true; } // let osx-sign decide
  if (!stat.isFile()) return true; // bundles and frameworks stay with osx-sign
  const head = Buffer.alloc(8);
  const fd = fs.openSync(file, 'r');
  try { fs.readSync(fd, head, 0, 8, 0); } finally { fs.closeSync(fd); }
  const magic = head.subarray(0, 4).toString('hex');
  if (THIN.has(magic)) return true;
  if (magic === 'cafebabe') { // universal binary; a Java class file shares the magic
    const archs = head.readUInt32BE(4);
    return archs > 0 && archs < 20;
  }
  return false;
}

module.exports = async function signMachOOnly(opts) {
  const ignore = opts.ignore;
  return sign({ ...opts, ignore: (file) => (ignore ? ignore(file) : false) || !isMachO(file) });
};
