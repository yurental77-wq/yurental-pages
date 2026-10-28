// node scripts/refresh_style_versions.js [--write]
// 새 디자인의 캐시 버전만 갱신한다. 본문/SEO/내비게이션 URL은 보존.
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { listRouterFiles } = require('./lib/router-files');
const { listCopierEmdFiles } = require('./lib/copier-emd-files');
const ROOT = path.resolve(__dirname, '..');
const write = process.argv.includes('--write');
const files = ['index.html', 'template.html', 'page_template.html', 'province_hub_template.html',
  'netlify/functions/templates/page_template.html', 'netlify/functions/templates/province_hub_template.html', 'build-router.js'];
for (const dir of ['pages', 'emd', 'router']) {
  for (const file of fs.readdirSync(path.join(ROOT, dir), { recursive: true })) {
    if (file.endsWith('index.html')) files.push(path.join(dir, file));
  }
}
let updated = 0;
for (const file of listRouterFiles(ROOT)) {
  const relative = path.relative(ROOT, file);
  if (!relative.startsWith('router' + path.sep)) files.push(relative);
}
for (const file of listCopierEmdFiles(ROOT)) {
  const relative = path.relative(ROOT, file);
  if (!files.includes(relative)) files.push(relative);
}
for (const file of files) {
  const target = path.join(ROOT, file);
  const html = fs.readFileSync(target, 'utf8');
  const next = html.replace(/site\.css\?v=(?:20261007|20261028[a-e]?)(?![a-z\d])/g, 'site.css?v=20261028f')
    .replace(/router\.css\?v=(?:20261012|20261028)(?![a-z\d])/g, 'router.css?v=20261028b');
  if (!write) assert.equal(next === html, true, `스타일 버전 미반영: ${file}`);
  else if (next !== html) { fs.writeFileSync(target, Buffer.from(next, 'utf8')); updated++; }
}
console.log(JSON.stringify({ checked: files.length, updated, contentUnchanged: true }));
