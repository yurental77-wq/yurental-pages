'use strict';
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { koreaDate, contentHash, pagePath, withLastmod } = require('../../netlify/functions/lib/sitemap-lastmod');
const { areaSlug } = require('../../netlify/functions/lib/emd-url-paths');
const SITEMAPS = ['sitemap.xml', 'sitemap-emd.xml', 'sitemap-router.xml'];

function createResolver(root) {
  const git = args => execFileSync('git', ['-c', 'core.quotepath=false', ...args], {
    cwd: root, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024,
  });
  const rows = JSON.parse(fs.readFileSync(path.join(root, 'data/emd_regions.json'), 'utf8')).regions;
  const paths = ['pages', 'emd', 'router', 'index.html', ...new Set(rows.map(areaSlug))];
  const hashes = new Map();
  for (const line of git(['ls-tree', '-r', '--format=%(objectname) %(path)', 'HEAD', '--', ...paths]).split('\n')) {
    if (/^[a-f0-9]{40} /.test(line)) hashes.set(line.slice(41).trimEnd(), line.slice(0, 40));
  }
  const dates = new Map();
  let date;
  for (const line of git(['log', '--format=@@DATE:%cI', '--name-only', '--no-renames', '--', ...paths]).split(/\r?\n/)) {
    if (line.startsWith('@@DATE:')) date = koreaDate(line.slice(7));
    else if (line.endsWith('.html') && date && !dates.has(line)) dates.set(line, date);
  }
  return url => {
    const relative = pagePath(url), file = path.join(root, ...relative.split('/'));
    const content = fs.readFileSync(file, 'utf8'); // 존재하지 않는 페이지는 오류로 알린다.
    if (hashes.get(relative) === contentHash(content) && dates.has(relative)) return dates.get(relative);
    // 미커밋 변경/새 파일은 실제 로컬 저장 시각을 사용한다. 재빌드한 동일 내용은 위에서 걸러진다.
    return koreaDate(fs.statSync(file).mtime);
  };
}

function updateLocalSitemaps(root, { write = true, names = SITEMAPS } = {}) {
  const resolve = createResolver(root);
  return names.filter(name => fs.existsSync(path.join(root, name))).map(name => {
    const file = path.join(root, name), original = fs.readFileSync(file, 'utf8');
    const next = withLastmod(original, resolve);
    const entries = [...next.matchAll(/<url>([\s\S]*?)<\/url>/g)];
    const lastmods = entries.map(entry => entry[1].match(/<lastmod>([^<]+)<\/lastmod>/)?.[1]);
    if (lastmods.some(value => !value)) throw new Error('수정일 누락: ' + name);
    if (write && next !== original) fs.writeFileSync(file, next, 'utf8');
    return { file: name, urls: entries.length, updated: next !== original, dates: [...new Set(lastmods)].sort() };
  });
}

module.exports = { updateLocalSitemaps, createResolver };
