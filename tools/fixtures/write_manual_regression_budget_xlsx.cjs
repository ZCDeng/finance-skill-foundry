#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');

function crc32(buf) {
  let crc = 0xffffffff;
  for (const byte of buf) {
    crc ^= byte;
    for (let i = 0; i < 8; i += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function dosDateTime(date = new Date('2026-09-28T00:00:00Z')) {
  const year = Math.max(1980, date.getUTCFullYear());
  const time = (date.getUTCSeconds() >> 1) | (date.getUTCMinutes() << 5) | (date.getUTCHours() << 11);
  const day = date.getUTCDate() | ((date.getUTCMonth() + 1) << 5) | ((year - 1980) << 9);
  return { time, day };
}
function u16(value) { const b = Buffer.alloc(2); b.writeUInt16LE(value); return b; }
function u32(value) { const b = Buffer.alloc(4); b.writeUInt32LE(value >>> 0); return b; }
function zip(files) {
  const local = [];
  const central = [];
  let offset = 0;
  const { time, day } = dosDateTime();
  for (const file of files) {
    const name = Buffer.from(file.name, 'utf8');
    const data = Buffer.isBuffer(file.data) ? file.data : Buffer.from(file.data, 'utf8');
    const compressed = zlib.deflateRawSync(data, { level: 9 });
    const crc = crc32(data);
    const header = Buffer.concat([
      u32(0x04034b50), u16(20), u16(0x0800), u16(8), u16(time), u16(day), u32(crc),
      u32(compressed.length), u32(data.length), u16(name.length), u16(0), name,
    ]);
    local.push(header, compressed);
    central.push(Buffer.concat([
      u32(0x02014b50), u16(20), u16(20), u16(0x0800), u16(8), u16(time), u16(day), u32(crc),
      u32(compressed.length), u32(data.length), u16(name.length), u16(0), u16(0), u16(0), u16(0), u32(0), u32(offset), name,
    ]));
    offset += header.length + compressed.length;
  }
  const centralOffset = offset;
  const centralDir = Buffer.concat(central);
  const end = Buffer.concat([u32(0x06054b50), u16(0), u16(0), u16(files.length), u16(files.length), u32(centralDir.length), u32(centralOffset), u16(0)]);
  return Buffer.concat([...local, centralDir, end]);
}
function xml(text) { return String(text).replace(/[<>&"']/g, (ch) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' }[ch])); }
function columnName(index) {
  let out = '';
  for (let n = index; n > 0;) { const r = (n - 1) % 26; out = String.fromCharCode(65 + r) + out; n = Math.floor((n - 1) / 26); }
  return out;
}
function worksheet(rows) {
  const body = rows.map((row, r) => `<row r="${r + 1}">${row.map((value, c) => {
    if (value === null || value === undefined || value === '') return '';
    const ref = `${columnName(c + 1)}${r + 1}`;
    if (typeof value === 'number') return `<c r="${ref}"><v>${value}</v></c>`;
    return `<c r="${ref}" t="inlineStr"><is><t>${xml(value)}</t></is></c>`;
  }).join('')}</row>`).join('');
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${body}</sheetData></worksheet>`;
}
function budgetRows(sheetLabel, seed) {
  const months = Array.from({ length: 12 }, (_, i) => `${i + 1}月`);
  const rows = [
    [`${sheetLabel} 2026 年度预算`],
    ['单位：万元；币种：CNY；版本：董事会预算'],
    ['说明', '第 4 行为表头，A 列为项目，B-M 为月份，N 为备注'],
    ['项目', ...months, '备注'],
  ];
  const items = [['营业收入', 1200], ['主营成本', 740], ['销售费用', 95], ['管理费用', 130], ['研发投入', 88], ['经营利润', 147], ['资本开支', 52]];
  for (const [name, base] of items) rows.push([name, ...months.map((_, i) => base + seed + i * 3), `${sheetLabel} 自动合成`]);
  rows.push(['合计', ...months.map((_, i) => 2452 + seed * 7 + i * 11), '核对行']);
  return rows;
}
function writeWorkbook(outPath) {
  const sheets = [
    { name: '预算明细', rows: budgetRows('预算明细', 0) },
    { name: '渠道预算', rows: budgetRows('渠道预算', 10) },
    { name: '封面说明', rows: [['预算包'], ['仅说明，不参与计算'], ['编制：QA'], ['口径：合成数据']] },
  ];
  const overrides = sheets.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('');
  const workbookSheets = sheets.map((sheet, i) => `<sheet name="${xml(sheet.name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('');
  const rels = sheets.map((_, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('');
  const files = [
    { name: '[Content_Types].xml', data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>${overrides}<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>` },
    { name: '_rels/.rels', data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' },
    { name: 'xl/workbook.xml', data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>${workbookSheets}</sheets></workbook>` },
    { name: 'xl/_rels/workbook.xml.rels', data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${rels}</Relationships>` },
    { name: 'docProps/core.xml', data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>manual-regression-fixture</dc:creator></cp:coreProperties>' },
    { name: 'docProps/app.xml', data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>FA Foundry QA</Application></Properties>' },
    ...sheets.map((sheet, i) => ({ name: `xl/worksheets/sheet${i + 1}.xml`, data: worksheet(sheet.rows) })),
  ];
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, zip(files));
  return { path: outPath, sheets: sheets.map((sheet) => ({ name: sheet.name, rows: sheet.rows.length, columns: Math.max(...sheet.rows.map((row) => row.length)) })) };
}
if (require.main === module) {
  const out = process.argv[2];
  if (!out) { console.error('usage: write_manual_regression_budget_xlsx.cjs <out.xlsx>'); process.exit(2); }
  console.log(JSON.stringify(writeWorkbook(path.resolve(out)), null, 2));
}
module.exports = { writeWorkbook };
