// node scripts/update_router_district_breadcrumbs.js [--write]
// 시군구 라우터 상세의 화면 경로와 BreadcrumbList만 3단계로 간소화.
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { ROOT, SITE_URL, encodeUrl } = require('../build');
const { validateSource, districtPath } = require('../build-emd');
const { routerDistrictBreadcrumbs } = require('./lib/emd-breadcrumbs');
const { escapeHtml } = require('../netlify/functions/lib/copier-header-intros');
const rows = validateSource(JSON.parse(fs.readFileSync(path.join(ROOT, 'data/emd_regions.json'), 'utf8')));
const districts = new Map(rows.map(row => ['/router' + districtPath(row), row]));
const write = process.argv.includes('--write');
const operations = [];
const crumbRegex = /<div class="crumb">[\s\S]*?<\/div>/;
const schemaRegex = /<script type="application\/ld\+json">([\s\S]*?)<\/script>/g;
const strip = html => html.replace(crumbRegex, '').replace(schemaRegex, (block, body) => JSON.parse(body)['@type'] === 'BreadcrumbList' ? '' : block);
for (const [url, row] of districts) {
  const file = path.join(ROOT, ...url.split('/').filter(Boolean), 'index.html');
  const html = fs.readFileSync(file, 'utf8');
  const crumbs = routerDistrictBreadcrumbs(row, url);
  assert.equal(crumbs.length, 3);
  const markup = '<div class="crumb">' + crumbs.map((item, index) => {
    assert.ok(fs.existsSync(path.join(ROOT, ...item.url.split('/').filter(Boolean), 'index.html')), item.url);
    if (index === 2) return escapeHtml(item.name);
    const relative = path.posix.relative(url, item.url);
    return `<a href="${escapeHtml(relative ? relative + '/' : './')}index.html">${escapeHtml(item.name)}</a>`;
  }).join(' &gt; ') + '</div>';
  assert.equal((html.match(/<div class="crumb">/g) || []).length, 1, file);
  let updated = html.replace(crumbRegex, () => markup), schemas = 0;
  updated = updated.replace(schemaRegex, (block, body) => {
    const schema = JSON.parse(body);
    if (schema['@type'] !== 'BreadcrumbList') return block;
    schemas++;
    schema.itemListElement = crumbs.map((item, index) => ({ '@type': 'ListItem', position: index + 1, name: item.name, item: encodeUrl(SITE_URL + item.url) }));
    return block.replace(body, () => body.replace(body.trim(), () => JSON.stringify(schema).replace(/</g, '\\u003c')));
  });
  assert.equal(schemas, 1, file);
  assert.equal(strip(updated), strip(html), `경로 외 변경: ${file}`);
  if (write) { if (updated !== html) operations.push({ file, updated }); }
  else assert.equal(updated, html, `경로 미반영: ${file}`);
}
assert.equal(districts.size, 256);
for (const { file, updated } of operations) fs.writeFileSync(file, Buffer.from(updated, 'utf8'));
console.log(JSON.stringify({ pages: districts.size, updated: operations.length, steps: 3, otherContentPreserved: true }));
