'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const vm = require('vm');
const { createRedirects, districtPath, leafPath } = require('../netlify/functions/lib/emd-url-paths');
const ROOT = path.resolve(__dirname, '..');
const { handler } = require('../netlify/functions/emd-redirect');
const rows = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/emd_regions.json'), 'utf8')).regions;
const routes = require('../netlify/functions/data/emd_url_redirects.json').routes;
assert.deepEqual(routes, createRedirects(rows));
const encode = value => value.split('/').map(encodeURIComponent).join('/');
const fileFor = value => path.join(ROOT, ...value.split('/').filter(Boolean), 'index.html');
const rules = fs.readFileSync(path.join(ROOT, '_redirects'), 'utf8').split(/\r?\n/)
  .filter(line => line.includes('/.netlify/functions/emd-redirect?')).map(line => {
    const [from, to, status] = line.trim().split(/\s+/);
    assert.equal(status, '200'); // 기존 정적 파일은 가로채지 않는다.
    const keys = [];
    const pattern = from.split('/').map(segment => {
      if (segment === '*') { keys.push('splat'); return '(.*)'; }
      if (segment.startsWith(':')) { keys.push(segment.slice(1)); return '([^/]+)'; }
      return segment;
    }).join('/');
    return { match: new RegExp('^' + pattern + '/?$'), keys, to };
  });
assert.equal(rules.length, 6);
async function throughRules(urlPath) {
  for (const rule of rules) {
    const match = urlPath.match(rule.match);
    if (!match) continue;
    const values = Object.fromEntries(rule.keys.map((key, index) => [key, match[index + 1]]));
    const rewrite = rule.to.replace(/:(\w+)/g, (_, key) => encodeURIComponent(values[key] || ''));
    const params = Object.fromEntries(new URL(rewrite, 'https://hanarentalbj.kr').searchParams);
    return handler({ queryStringParameters: params });
  }
  throw new Error('리다이렉트 라우팅 규칙 없음: ' + urlPath);
}
(async () => {
  let requests = 0;
  for (const [from, to] of Object.entries(routes)) {
    assert.ok(fs.existsSync(fileFor(to)), '새 페이지 없음: ' + to);
    const html = fs.readFileSync(fileFor(to), 'utf8');
    if (html.includes('var BRANDS')) {
      assert.ok(html.includes(`'<a href="' + brand.link + '"`), '배너 링크 템플릿 손상: ' + to);
      assert.ok(html.includes(`'<img src="' + pick(brand.imgs) + '"`), '배너 이미지 템플릿 손상: ' + to);
    }
    assert.ok(!fs.existsSync(fileFor(from)), '기존 주소가 정적 파일로 남음: ' + from);
    assert.ok(!Object.hasOwn(routes, to), '리다이렉트 체인: ' + to);
    for (const variant of [from, from.slice(0, -1), from + 'index.html', encode(from), encode(from.slice(0, -1)), encode(from + 'index.html')]) {
      const response = await throughRules(variant);
      assert.equal(response.statusCode, 301, variant);
      assert.equal(response.headers.Location, encode(to), variant); requests++;
    }
  }
  const sample = Object.keys(routes)[0];
  const query = await handler({ queryStringParameters: { from: sample, utm_source: 'test' } });
  assert.ok(query.headers.Location.endsWith('?utm_source=test'));
  assert.equal((await handler({ queryStringParameters: { from: '//evil.example/' } })).statusCode, 404);
  assert.equal((await handler({ queryStringParameters: { from: sample, tail: 'bad.html' } })).statusCode, 404);
  assert.equal((await handler({ queryStringParameters: { from: '%' } })).statusCode, 400);
  for (const product of ['복합기렌탈', '라우터렌탈']) {
    const targets = new Set();
    for (const row of rows) {
      const url = leafPath(row, product);
      assert.ok(!targets.has(url)); targets.add(url);
      assert.ok(!url.includes(row.code));
      const html = fs.readFileSync(fileFor(url), 'utf8');
      assert.ok(html.includes(`'<a href="' + brand.link + '"`), '배너 링크 템플릿 손상: ' + url);
      assert.ok(html.includes(`'<img src="' + pick(brand.imgs) + '"`), '배너 이미지 템플릿 손상: ' + url);
      const canonical = html.match(/<link rel="canonical" href="([^"]+)"/)[1];
      assert.equal(canonical, 'https://hanarentalbj.kr' + encode(url));
      const schemas = [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].map(match => JSON.parse(match[1]));
      const crumbs = schemas.find(item => item['@type'] === 'BreadcrumbList').itemListElement;
      assert.equal(crumbs.length, 3);
      assert.equal(crumbs[1].item, 'https://hanarentalbj.kr' + encode(districtPath(row, product)));
      assert.equal(crumbs[2].item, canonical);
    }
  }
  const sampleRow = rows.find(row => row.code === '2617053000');
  for (const product of ['복합기렌탈', '라우터렌탈']) {
    const html = fs.readFileSync(fileFor(leafPath(sampleRow, product)), 'utf8');
    const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].find(match => match[1].includes('var BRANDS'))[1];
    const elements = { 'banner-top': {}, 'banner-bottom': {} };
    vm.runInNewContext(script, { document: { getElementById: id => elements[id],
      body: { classList: { contains: () => product === '라우터렌탈' } } } });
    for (const element of Object.values(elements)) {
      assert.match(element.innerHTML, /href="https:\/\/(?:hanarental\.shop|yurental\.com)\/"/);
      assert.match(element.innerHTML, /src="https:\/\/gi\.esmplus\.com\//);
    }
  }
  console.log(JSON.stringify({ result: 'PASS', leafPages: rows.length * 2, redirects: Object.keys(routes).length,
    redirectHttpCases: requests, status: 301, redirectChains: 0, openRedirects: 0 }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
