// node scripts/update_price_router_thumbnail.js [--write]
// 메인·도시·읍면동 복합기 요금표의 라우터 사진만 투명 이미지로 교체.
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const ROOT = path.resolve(__dirname, '..');
const write = process.argv.includes('--write');
const asset = path.join(ROOT, 'assets/cnr-5g500-cutout.webp');
assert.ok(fs.existsSync(asset));
const files = [path.join(ROOT, 'index.html')];
for (const dir of ['pages', 'emd']) {
  files.push(...fs.readdirSync(path.join(ROOT, dir), { recursive: true }).filter(file => file.endsWith('index.html')).map(file => path.join(ROOT, dir, file)));
}
const rowPattern = /<tr class="pt-router">[\s\S]*?<\/tr>/g;
const operations = [];
let checked = 0;
for (const file of files) {
  const html = fs.readFileSync(file, 'utf8');
  const rows = [...html.matchAll(rowPattern)];
  if (!rows.length) continue;
  assert.equal(rows.length, 1, file);
  const row = rows[0][0];
  const src = path.relative(path.dirname(file), asset).split(path.sep).join('/');
  assert.equal((row.match(/<img\b/g) || []).length, 1, file);
  const nextRow = row.replace(/(<img src=")[^"]+("[^>]*>)/, (_, before, after) => before + src + after);
  const next = html.replace(row, () => nextRow).replace(/site\.css\?v=20261028[bd](?![a-z\d])/g, 'site.css?v=20261028e');
  const normalizeStyle = text => text.replace(/site\.css\?v=20261028[bde](?![a-z\d])/g, 'site.css?v=STYLE');
  assert.equal(normalizeStyle(next.replace(nextRow, () => row)), normalizeStyle(html), `사진 외 변경: ${file}`);
  if (write) { if (next !== html) operations.push({ file, next }); }
  else assert.equal(next === html, true, `사진 미반영: ${file}`);
  checked++;
}
assert.equal(checked, 3793);
for (const { file, next } of operations) fs.writeFileSync(file, Buffer.from(next, 'utf8'));
console.log(JSON.stringify({ checked, updated: operations.length, pricesAndCopyPreserved: true }));
