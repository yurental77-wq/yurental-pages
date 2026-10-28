// 실행: node scripts/validate_emd.js (읽기 전용 전체 검증)
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { ROOT, DATA, SITE_URL } = require('../build');
const { validateSource, findCity, leafPath } = require('../build-emd');
const source = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/emd_regions.json'), 'utf8'));
const rows = validateSource(source);
assert.throws(() => validateSource({ ...source, regions: rows.slice(1) }));
assert.throws(() => validateSource({ ...source, regions: [rows[0], rows[0], ...rows.slice(2)] }));
const checks = [
  ['전북특별자치도', '군산시', '군산'],
  ['강원특별자치도', '양구군', '양구'],
  ['강원특별자치도', '고성군', '고성'],
  ['경상남도', '고성군', '고성'],
  ['서울특별시', '중구', '중구'],
  ['부산광역시', '북구', '부산 북구'],
  ['경기도', '고양시 덕양구', '고양'],
  ['전북특별자치도', '전주시 덕진구', '전주'],
  ['대구광역시', '군위군', '군위'],
  ['세종특별자치시', '', '세종 세종시'],
];
for (const [province, district, region] of checks) {
  const row = rows.find(item => item.province === province && item.district === district);
  assert.ok(row, `테스트 자료 누락: ${province} ${district}`);
  assert.equal(findCity(row)?.region, region);
}
assert.equal(findCity(rows.find(row => row.province === '제주특별자치도')), null);
const { listCopierEmdFiles } = require('./lib/copier-emd-files');
const files = listCopierEmdFiles(ROOT);
const { isRootCopierLeafPath } = require('../netlify/functions/lib/emd-url-paths');
assert.equal(files.filter(file => isRootCopierLeafPath('/' + path.relative(ROOT, path.dirname(file)).split(path.sep).join('/') + '/')).length, rows.length);
assert.equal(files.length, 3838);
const titleSet = new Set(), canonicalSet = new Set();
let checkedLinks = 0, faqPages = 0;
const rowByPath = new Map(rows.map(row => [path.join(ROOT, ...leafPath(row).split('/').filter(Boolean), 'index.html'), row]));
for (const file of files) {
  const html = fs.readFileSync(file, 'utf8');
  assert.ok(!/\{\{[A-Z_]+\}\}/.test(html), `템플릿 치환 오류: ${file}`);
  assert.equal((html.match(/<h1[\s>]/g) || []).length, 1, file);
  const title = html.match(/<title>([\s\S]*?)<\/title>/)?.[1];
  const canonical = html.match(/<link rel="canonical" href="([^"]+)"/)?.[1];
  assert.ok(title && canonical && canonical.startsWith(SITE_URL + '/'), file);
  assert.ok(!titleSet.has(title) && !canonicalSet.has(canonical), `중복 SEO: ${file}`);
  titleSet.add(title); canonicalSet.add(canonical);
  const base = SITE_URL + '/' + path.relative(ROOT, file).split(path.sep).join('/');
  assert.equal(decodeURIComponent(new URL(canonical).pathname), decodeURIComponent(new URL(base).pathname).replace(/index\.html$/, ''), `canonical 경로: ${file}`);
  const schemas = [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].map(match => JSON.parse(match[1]));
  const breadcrumb = schemas.find(schema => schema['@type'] === 'BreadcrumbList');
  assert.ok(breadcrumb, file);
  assert.equal(breadcrumb.itemListElement.at(-1).item, canonical, file);
  // 배너 JS의 문자열 템플릿은 DOM의 링크가 아니므로 제외한다.
  const markup = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
  for (const match of markup.matchAll(/(?:href|src)="([^"]+)"/g)) {
    const value = match[1].replace(/&amp;/g, '&');
    if (/^(?:https?:|tel:|mailto:|#|data:)/.test(value)) continue;
    const url = new URL(value, base);
    let target = path.join(ROOT, decodeURIComponent(url.pathname).replace(/^\//, ''));
    if (url.pathname.endsWith('/')) target = path.join(target, 'index.html');
    assert.ok(fs.existsSync(target), `잘못된 내부 경로: ${file} -> ${value}`);
    checkedLinks++;
  }
  if (rowByPath.has(file)) {
    const row = rowByPath.get(file);
    assert.ok(title.includes(row.full_name), file);
    assert.equal((html.match(/class="pt-router"/g) || []).length, 1, file);
    assert.equal((html.match(/class="faq-item"/g) || []).length, 5, file);
    const faq = schemas.find(schema => schema['@type'] === 'FAQPage');
    assert.equal(faq.mainEntity.length, 5, file);
    const questions = [...html.matchAll(/<div class="faq-q">([\s\S]*?)<\/div>/g)].map(match => match[1]);
    assert.deepEqual(faq.mainEntity.map(item => item.name), questions, file);
    const about = schemas.find(schema => schema['@type'] === 'WebPage')?.about;
    assert.equal(about.identifier, row.code, file);
    const providerImages = [...html.matchAll(/<div class="card-thumb"><img src="([^"]+)"/g)].map(match => match[1]);
    assert.equal(new Set(providerImages).size, providerImages.length, `중복 업체 사진: ${file}`);
    faqPages++;
  }
}
const sitemap = fs.readFileSync(path.join(ROOT, 'sitemap-emd.xml'), 'utf8');
const urls = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map(match => match[1]);
assert.equal(urls.length, files.length);
assert.deepEqual(new Set(urls), canonicalSet);
assert.ok(urls.every(url => /^https:\/\/hanarentalbj\.kr\//.test(url) && !/[가-힣 ]/.test(url)));
const robots = fs.readFileSync(path.join(ROOT, 'robots.txt'), 'utf8');
assert.ok(robots.includes('Sitemap: ' + SITE_URL + '/sitemap.xml'));
assert.equal(robots.split('Sitemap: ' + SITE_URL + '/sitemap-emd.xml').length - 1, 1);
assert.ok(!fs.readFileSync(path.join(ROOT, 'sitemap.xml'), 'utf8').includes('/emd/'));
assert.ok(fs.readFileSync(path.join(ROOT, 'pages/index.html'), 'utf8').includes('data-emd-list'));
for (const city of DATA) {
  const file = path.join(ROOT, 'pages', city.province, city.slug, 'index.html');
  assert.ok(fs.existsSync(file));
  const html = fs.readFileSync(file, 'utf8');
  assert.equal((html.match(/class="pt-router"/g) || []).length, 1, file);
  assert.ok((html.match(/EMD-LINKS:START/g) || []).length <= 1, file);
}
console.log(JSON.stringify({ result: 'PASS', leafPages: faqPages, hubPages: files.length - faqPages, sitemapUrls: urls.length, internalLinksChecked: checkedLinks, existingCityPages: DATA.length }, null, 2));
