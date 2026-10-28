// node scripts/update_emd_breadcrumbs.js [--write]
// 전체 재빌드 없이 읍면동 상세 페이지의 경로 표시/경로 JSON-LD만 갱신한다.
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { ROOT, SITE_URL, encodeUrl } = require('../build');
const { validateSource, leafPath, districtPath } = require('../build-emd');
const { emdBreadcrumbs } = require('./lib/emd-breadcrumbs');
const { escapeHtml } = require('../netlify/functions/lib/copier-header-intros');
const rows = validateSource(JSON.parse(fs.readFileSync(path.join(ROOT, 'data/emd_regions.json'), 'utf8')));
const write = process.argv.includes('--write');
const operations = [];
let checked = 0;
const stripCrumbs = html => html.replace(/<div class="crumb">[\s\S]*?<\/div>/g, '')
  .replace(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g,
    (block, body) => JSON.parse(body)['@type'] === 'BreadcrumbList' ? '' : block);
for (const row of rows) {
  for (const product of ['복합기렌탈', '라우터렌탈']) {
    const copier = product === '복합기렌탈';
    const leaf = leafPath(row, product);
    const district = (copier ? '' : '/router') + districtPath(row);
    const crumbs = emdBreadcrumbs(row, district, leaf, product);
    assert.equal(crumbs.length, 3);
    assert.equal(crumbs[0].name, '홈');
    assert.equal(crumbs[1].url, district);
    assert.equal(crumbs[2].url, leaf);
    for (const item of crumbs) {
      assert.ok(fs.existsSync(path.join(ROOT, ...item.url.split('/').filter(Boolean), 'index.html')), item.url);
    }
    const file = path.join(ROOT, ...leaf.split('/').filter(Boolean), 'index.html');
    const html = fs.readFileSync(file, 'utf8');
    const markup = '<div class="crumb">' + crumbs.map((item, index) => {
      if (index === crumbs.length - 1) return escapeHtml(item.name);
      const rel = path.posix.relative(leaf, item.url);
      return `<a href="${escapeHtml(rel ? rel + '/' : './')}index.html">${escapeHtml(item.name)}</a>`;
    }).join(' &gt; ') + '</div>';
    assert.equal((html.match(/<div class="crumb">/g) || []).length, 1, file);
    let updated = html.replace(/<div class="crumb">[\s\S]*?<\/div>/, () => markup);
    let schemaCount = 0;
    updated = updated.replace(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g, (block, body) => {
      const schema = JSON.parse(body);
      if (schema['@type'] !== 'BreadcrumbList') return block;
      schemaCount++;
      schema.itemListElement = crumbs.map((item, index) => ({
        '@type': 'ListItem', position: index + 1, name: item.name, item: encodeUrl(SITE_URL + item.url),
      }));
      // 기존 script의 줄바꿈 스타일도 보존한다.
      return block.replace(body, () => body.replace(body.trim(), () => JSON.stringify(schema).replace(/</g, '\\u003c')));
    });
    assert.equal(schemaCount, 1, file);
    assert.equal(stripCrumbs(updated), stripCrumbs(html), `경로 외 변경: ${file}`);
    if (!write) assert.equal(updated, html, `경로 미반영: ${file}`);
    else if (html !== updated) operations.push({ file, updated });
    checked++;
  }
}
assert.equal(checked, 7130);
const busan = rows.find(row => row.code === '2617053000');
assert.deepEqual(emdBreadcrumbs(busan, districtPath(busan), leafPath(busan), '복합기렌탈').map(item => item.name), ['홈', '부산 동구', '초량제3동 복합기렌탈']);
const sejong = rows.find(row => row.province === '세종특별자치시');
assert.equal(emdBreadcrumbs(sejong, districtPath(sejong), leafPath(sejong), '복합기렌탈')[1].name, '세종시');
for (const { file, updated } of operations) fs.writeFileSync(file, updated, 'utf8');
console.log(JSON.stringify({ checked, updated: operations.length, steps: 3, otherContentPreserved: true }, null, 2));
