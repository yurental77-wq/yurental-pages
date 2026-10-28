// node scripts/update_router_thumbnail.js [--write]
// 라우터 소개 사진만 투명 WebP로 바꾼다. OG/구조화데이터/기타 사진은 보존.
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const ROOT = path.resolve(__dirname, '..');
const PRODUCT = require('../data/router_product.json');
const write = process.argv.includes('--write');
const asset = path.join(ROOT, PRODUCT.introImage);
assert.ok(fs.existsSync(asset), '배경 제거 이미지가 없습니다.');
const operations = [];
let pages = 0;
for (const relative of fs.readdirSync(path.join(ROOT, 'router'), { recursive: true }).filter(file => file.endsWith('index.html'))) {
  const file = path.join(ROOT, 'router', relative);
  const html = fs.readFileSync(file, 'utf8');
  if (!html.includes('<body class="router-page">')) continue;
  const matches = [...html.matchAll(/<img class="intro-thumbnail"[^>]+>/g)];
  assert.equal(matches.length, 1, file);
  const src = path.relative(path.dirname(file), asset).split(path.sep).join('/');
  const before = matches[0][0];
  assert.ok(before.includes(`src="${PRODUCT.image}"`) || before.includes(`src="${src}"`), `알 수 없는 원본: ${file}`);
  const after = before.replace(/src="[^"]+"/, `src="${src}"`);
  const updated = html.replace(before, () => after).replaceAll('router.css?v=20261028b', 'router.css?v=20261028c');
  assert.equal(updated.replace(after, () => before).replaceAll('router.css?v=20261028c', 'router.css?v=20261028b'), html.replaceAll('router.css?v=20261028c', 'router.css?v=20261028b'), file);
  if (write) { if (updated !== html) operations.push({ file, updated }); }
  else assert.equal(updated === html, true, `썸네일 미반영: ${file}`);
  pages++;
}
assert.equal(pages, 4048);
for (const { file, updated } of operations) fs.writeFileSync(file, Buffer.from(updated, 'utf8'));
console.log(JSON.stringify({ pages, updated: operations.length, otherContentPreserved: true }));
