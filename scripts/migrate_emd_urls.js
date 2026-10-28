// node scripts/migrate_emd_urls.js [--write]
// 기존 HTML 내용을 재생성하지 않고 URL/상대 경로만 변경한다. 기본은 사전 검사.
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { createRedirects, redirectRules } = require('../netlify/functions/lib/emd-url-paths');
const { listRouterFiles } = require('./lib/router-files');
const { listCopierEmdFiles } = require('./lib/copier-emd-files');
const { updateLocalSitemaps } = require('./lib/local-sitemap-lastmod');
const ROOT = path.resolve(__dirname, '..');
const ORIGIN = 'https://hanarentalbj.kr';
const rows = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/emd_regions.json'), 'utf8')).regions;
const routes = createRedirects(rows);
const allowedTargets = new Set(Object.values(routes));
const write = process.argv.includes('--write');
const encode = value => value.split('/').map(encodeURIComponent).join('/');
const normalize = value => value.replace(/index\.html$/, '').replace(/\/?$/, '/');
function localFile(urlPath) {
  const file = path.resolve(ROOT, '.' + urlPath, 'index.html');
  if (!file.startsWith(ROOT + path.sep) || !allowedTargets.has(urlPath)) throw new Error('이동 범위 오류: ' + file);
  return file;
}
function mapAbsolute(value) {
  let url;
  try { url = new URL(value.replace(/&amp;/g, '&')); } catch { return value; }
  if (url.origin !== ORIGIN) return value;
  const pathname = decodeURIComponent(url.pathname), old = normalize(pathname);
  if (!routes[old]) return value;
  return ORIGIN + encode(routes[old] + (pathname.endsWith('index.html') ? 'index.html' : '')) + url.search + url.hash;
}
function rewrite(html, oldFile, newFile) {
  const base = ORIGIN + '/' + path.relative(ROOT, oldFile).split(path.sep).join('/');
  const newDirectory = '/' + path.relative(ROOT, path.dirname(newFile)).split(path.sep).join('/') + '/';
  const scripts = [];
  const markup = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, block => {
    // 이전 변환으로 들어간 배너 템플릿 앞의 상대 경로를 제거한다.
    const original = block.replace(/(<a href=")[^"]*(' \+ brand\.link \+ '")/g, '$1$2')
      .replace(/(<img src=")[^"]*(' \+ pick\(brand\.imgs\) \+ '")/g, '$1$2');
    scripts.push(original);
    return `<!-- URL-MIGRATION-SCRIPT:${scripts.length - 1} -->`;
  });
  let next = markup.replace(/\b(href|src)="([^"]+)"/g, (all, attr, value) => {
    if (/^(?:[a-z]+:|\/\/|#)/i.test(value)) return all;
    const url = new URL(value.replace(/&amp;/g, '&'), base);
    const oldPath = decodeURIComponent(url.pathname), directory = normalize(oldPath);
    const target = routes[directory];
    if (oldFile === newFile && !target) return all;
    const newPath = target ? target + (oldPath.endsWith('index.html') ? 'index.html' : '') : oldPath;
    let relative = path.posix.relative(newDirectory, newPath) || './';
    if (newPath.endsWith('/') && !relative.endsWith('/')) relative += '/';
    return `${attr}="${relative}${url.search.replace(/&/g, '&amp;')}${url.hash}"`;
  });
  next = next.replace(/<!-- URL-MIGRATION-SCRIPT:(\d+) -->/g, (_, index) => scripts[Number(index)]);
  next = next.replace(/https?:\/\/hanarentalbj\.kr[^\s"'<>]+/g, mapAbsolute);
  return next;
}
// URL/접근 경로 외의 텍스트·디자인·설명·FAQ·가격 등은 바뀌면 중단한다.
function withoutUrls(html) {
  return html.replace(/\b(href|src)="[^"]*"/g, '$1=""')
    .replace(/https?:\/\/hanarentalbj\.kr[^\s"'<>]+/g, 'SITE_URL');
}
const files = [path.join(ROOT, 'index.html')];
for (const folder of ['pages', 'emd', 'router']) {
  files.push(...fs.readdirSync(path.join(ROOT, folder), { recursive: true })
    .filter(file => file.endsWith('index.html')).map(file => path.join(ROOT, folder, file)));
}
for (const file of listRouterFiles(ROOT)) if (!files.includes(file)) files.push(file);
for (const file of listCopierEmdFiles(ROOT)) if (!files.includes(file)) files.push(file);
const operations = [], moves = [], outputPaths = new Set();
for (const file of files) {
  const oldDirectory = '/' + path.relative(ROOT, path.dirname(file)).split(path.sep).join('/') + '/';
  const target = routes[oldDirectory] ? localFile(routes[oldDirectory]) : file;
  assert.ok(!outputPaths.has(target), '이동 대상 충돌: ' + target); outputPaths.add(target);
  const original = fs.readFileSync(file, 'utf8'), next = rewrite(original, file, target);
  assert.equal(withoutUrls(next), withoutUrls(original), 'URL 외 내용 변경: ' + file);
  if (file !== target) {
    if (fs.existsSync(target)) assert.equal(fs.readFileSync(target, 'utf8'), next, '기존 파일 덮어쓰기 충돌: ' + target);
    moves.push({ from: file, to: target, content: next });
  }
  if (file !== target || original !== next) operations.push({ file: target, content: next });
}
const metadata = [];
for (const name of ['copier_header_intros.json', 'router_header_intros.json']) {
  const file = path.join(ROOT, 'netlify/functions/data', name), text = fs.readFileSync(file, 'utf8');
  const data = JSON.parse(text), entries = {};
  for (const [key, entry] of Object.entries(data.entries)) {
    const nextKey = routes[key] || key;
    assert.ok(!Object.hasOwn(entries, nextKey), '소개문 키 충돌: ' + nextKey);
    entries[nextKey] = entry;
  }
  data.entries = entries;
  metadata.push({ file, content: JSON.stringify(data, null, 2) + '\n' });
}
for (const name of ['sitemap.xml', 'sitemap-emd.xml', 'sitemap-router.xml', 'rss.xml']) {
  const file = path.join(ROOT, name), text = fs.readFileSync(file, 'utf8');
  metadata.push({ file, content: text.replace(/<loc>([^<]+)<\/loc>/g, (_, value) => '<loc>' + mapAbsolute(value) + '</loc>')
    .replace(/<(link|guid)>(https?:[^<]+)<\/\1>/g, (_, tag, value) => `<${tag}>${mapAbsolute(value)}</${tag}>`) });
}
const redirectsFile = path.join(ROOT, '_redirects');
const existingRules = fs.readFileSync(redirectsFile, 'utf8').replace(/# EMD-URL-REDIRECTS:START[\s\S]*?# EMD-URL-REDIRECTS:END\r?\n?/g, '');
metadata.push({ file: redirectsFile, content: existingRules.trimEnd() + '\n' + redirectRules() });
metadata.push({ file: path.join(ROOT, 'netlify/functions/data/emd_url_redirects.json'),
  content: JSON.stringify({ version: 1, routes }, null, 2) + '\n' });

if (write) {
  for (const op of [...operations, ...metadata]) {
    if (fs.existsSync(op.file) && fs.readFileSync(op.file, 'utf8') === op.content) continue;
    fs.mkdirSync(path.dirname(op.file), { recursive: true });
    fs.writeFileSync(op.file, op.content, 'utf8');
  }
  // 정확히 검증한 이전 index.html만 제거한다. 디렉터리를 재귀 삭제하지 않는다.
  for (const move of moves) {
    assert.ok(move.from.startsWith(ROOT + path.sep));
    assert.equal(fs.readFileSync(move.to, 'utf8'), move.content);
    fs.unlinkSync(move.from);
  }
  updateLocalSitemaps(ROOT);
}
console.log(JSON.stringify({ mode: write ? 'write' : 'check', checkedHtml: files.length,
  movedPages: moves.length, changedHtml: operations.length, redirects: Object.keys(routes).length,
  leafPagesPerProduct: rows.length, pageContentPreserved: true }, null, 2));
