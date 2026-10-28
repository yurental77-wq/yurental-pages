'use strict';
const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');
const {
  koreaDate, contentHash, pagePath, readLastmods, withLastmod, createRemoteResolver,
} = require('../netlify/functions/lib/sitemap-lastmod');
const { updateLocalSitemaps } = require('./lib/local-sitemap-lastmod');
const ROOT = path.resolve(__dirname, '..');

assert.equal(koreaDate('2026-10-27T16:30:00Z'), '2026-10-28');
assert.equal(contentHash('a\r\nb'), contentHash('a\nb'));
assert.equal(pagePath('https://hanarentalbj.kr/emd/%EB%B6%80%EC%82%B0/'), 'emd/부산/index.html');
assert.equal(pagePath('https://hanarentalbj.kr/pages/index.html'), 'pages/index.html');
assert.equal(pagePath('https://hanarentalbj.kr/emd/종로1.2.3.4가동/'), 'emd/종로1.2.3.4가동/index.html');
assert.throws(() => pagePath('https://hanarentalbj.kr/emd/%2e%2e%2fsecret/'));
const xml = '<urlset><url><loc>https://hanarentalbj.kr/pages/a/</loc><lastmod>2026-10-12</lastmod></url>' +
  '<url><loc>https://hanarentalbj.kr/pages/b/</loc></url></urlset>';
const resolver = createRemoteResolver(xml, [
  { type: 'blob', path: 'pages/a/index.html', sha: contentHash('unchanged') },
  { type: 'blob', path: 'pages/b/index.html', sha: contentHash('old') },
], [
  { path: 'pages/a/index.html', content: 'unchanged' },
  { path: 'pages/b/index.html', content: 'new' },
], '2026-10-28T04:00:00Z');
const result = withLastmod(xml, resolver);
assert.equal(readLastmods(result).get('pages/a/index.html'), '2026-10-12');
assert.equal(readLastmods(result).get('pages/b/index.html'), '2026-10-28');
assert.equal(withLastmod(result, resolver), result);
assert.equal((result.match(/<lastmod>/g) || []).length, 2);
assert.equal(withLastmod(xml, () => undefined), xml);

const report = updateLocalSitemaps(ROOT, { write: false });
for (const entry of report) {
  assert.equal(entry.updated, false, '사이트맵 수정일 동기화 필요: ' + entry.file);
  const text = fs.readFileSync(path.join(ROOT, entry.file), 'utf8');
  const urls = [...text.matchAll(/<url>([\s\S]*?)<\/url>/g)];
  for (const [, body] of urls) {
    assert.equal((body.match(/<lastmod>/g) || []).length, 1);
    const date = body.match(/<lastmod>([^<]+)<\/lastmod>/)[1];
    assert.match(date, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok(date <= koreaDate(new Date()), '미래 날짜: ' + date);
  }
}
console.log(JSON.stringify({ result: 'PASS', unchangedDatePreserved: true, changedDateUpdated: true,
  timezone: 'Asia/Seoul', repeatedRunStable: true, sitemaps: report }, null, 2));
