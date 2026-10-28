'use strict';
const { createHash } = require('crypto');

function koreaDate(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) throw new Error('유효하지 않은 수정일: ' + value);
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(date);
}

// Git의 체크아웃 개행 변환만으로 수정일이 바뀌지 않도록 LF로 비교한다.
function contentHash(content) {
  const bytes = Buffer.from(content.replace(/\r\n/g, '\n'), 'utf8');
  return createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex');
}

function pagePath(url) {
  const pathname = new URL(url).pathname;
  const parts = pathname.split('/').filter(Boolean).map(decodeURIComponent);
  if (parts.some(part => /[/\\\0]/.test(part) || part === '.' || part === '..')) {
    throw new Error('안전하지 않은 사이트맵 경로: ' + url);
  }
  if (pathname.endsWith('/') || !parts.length || !parts[parts.length - 1].endsWith('.html')) parts.push('index.html');
  return parts.join('/');
}

function readLastmods(xml) {
  const dates = new Map();
  for (const match of xml.matchAll(/<url>([\s\S]*?)<\/url>/g)) {
    const loc = match[1].match(/<loc>([^<]+)<\/loc>/);
    const date = match[1].match(/<lastmod>(\d{4}-\d{2}-\d{2})<\/lastmod>/);
    if (loc && date) dates.set(pagePath(loc[1].replace(/&amp;/g, '&')), date[1]);
  }
  return dates;
}

function withLastmod(xml, resolveDate) {
  return xml.replace(/<url>([\s\S]*?)<\/url>/g, (block, body) => {
    const loc = body.match(/<loc>([^<]+)<\/loc>/);
    if (!loc) throw new Error('사이트맵 URL에 loc가 없습니다.');
    const date = resolveDate(loc[1].replace(/&amp;/g, '&'));
    if (!date) return block; // 이력이 없는 미수정 페이지의 날짜는 추측하지 않는다.
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new Error('잘못된 lastmod: ' + date);
    const clean = body.replace(/<lastmod>[^<]*<\/lastmod>/g, '');
    return '<url>' + clean.replace(/<\/loc>/, `</loc><lastmod>${date}</lastmod>`) + '</url>';
  });
}

function createRemoteResolver(previousXml, treeEntries, generatedFiles, modifiedAt) {
  const dates = readLastmods(previousXml);
  const hashes = new Map(treeEntries.filter(entry => entry.type === 'blob').map(entry => [entry.path, entry.sha]));
  const generated = new Map(generatedFiles.map(file => [file.path, file.content]));
  const today = koreaDate(modifiedAt);
  return url => {
    const file = pagePath(url);
    if (generated.has(file) && hashes.get(file) !== contentHash(generated.get(file))) return today;
    return dates.get(file);
  };
}

module.exports = { koreaDate, contentHash, pagePath, readLastmods, withLastmod, createRemoteResolver };
