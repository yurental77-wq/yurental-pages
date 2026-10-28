// node scripts/update_router_header_intros.js [--write]
// 저장한 지역별 소개문은 보존하고, 상단 header p만 반영한다.
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const crypto = require('crypto');
const { listRouterFiles } = require('./lib/router-files');
const { escapeHtml } = require('../netlify/functions/lib/copier-header-intros');
const ROOT = path.resolve(__dirname, '..');
const DATA_FILE = path.join(ROOT, 'netlify/functions/data/router_header_intros.json');
const saved = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
const write = process.argv.includes('--write');
const pools = [
  [
    '라우터렌탈 문의를 준비하고 계신가요?',
    '라우터렌탈 문의, 어떤 공간에서 사용하시나요?',
    '라우터렌탈 문의에 앞서 이용 기간을 정하셨나요?',
    '라우터렌탈 문의, 연결할 장비는 몇 대인가요?',
    '라우터렌탈 문의 시 필요한 데이터량을 알고 계신가요?',
    '라우터렌탈 문의, 유선 회선을 기다리기 어려우신가요?',
    '라우터렌탈 문의를 위해 사용 목적을 정리하셨나요?',
    '라우터렌탈 문의, 실내와 실외 중 어디에서 쓰시나요?',
  ],
  [
    '건설현장·임시사무실·AI교육의 무선인터넷과 무선와이파이는 연결 기기 수부터 검토합니다.',
    '건설현장·임시사무실·AI교육에 필요한 무선인터넷과 무선와이파이는 사용 위치가 중요합니다.',
    '건설현장·임시사무실·AI교육용 무선인터넷과 무선와이파이는 PC·태블릿 수를 기준으로 살핍니다.',
    '건설현장·임시사무실·AI교육에서 쓸 무선인터넷과 무선와이파이는 영상 사용량도 고려합니다.',
    '건설현장·임시사무실·AI교육의 무선인터넷과 무선와이파이는 동시 접속 상황에 맞춰 검토합니다.',
    '건설현장·임시사무실·AI교육용 무선인터넷과 무선와이파이는 실내 배치와 전원도 중요합니다.',
    '건설현장·임시사무실·AI교육의 무선인터넷과 무선와이파이는 유선 연결 필요 여부도 살핍니다.',
    '건설현장·임시사무실·AI교육에 쓸 무선인터넷과 무선와이파이는 파일 전송량을 함께 고려합니다.',
    '건설현장·임시사무실·AI교육용 무선인터넷과 무선와이파이는 클라우드 작업 빈도도 중요합니다.',
    '건설현장·임시사무실·AI교육의 무선인터넷과 무선와이파이는 이동 여부와 설치 층수도 살핍니다.',
    '건설현장·임시사무실·AI교육에서 무선인터넷과 무선와이파이를 쓴다면 장비별 연결 방식을 정리합니다.',
    '건설현장·임시사무실·AI교육의 무선인터넷과 무선와이파이는 사용 시간대와 수신 환경을 고려합니다.',
  ],
  [
    '단기 무선공유기 상품·요금은 기간과 데이터량을 알려 상담하세요.',
    '단기 무선공유기 요금 상담에는 시작일과 종료일을 함께 전달해 주세요.',
    '단기 무선공유기 상품은 데이터와 개통 비용을 구분해 상담할 수 있습니다.',
    '단기 무선공유기 요금은 설치·회수 비용까지 나누어 상담하면 좋습니다.',
    '단기 무선공유기 상품 상담 시 연장 조건과 요금도 물어보세요.',
    '단기 무선공유기 요금은 희망 기간과 연결 장비를 정해 상담하세요.',
    '단기 무선공유기 상품·요금 상담에 예상 동시 접속 수를 알려 주세요.',
    '단기 무선공유기 요금은 데이터 제공 범위와 함께 상담하는 편이 좋습니다.',
    '단기 무선공유기 상품·요금 상담 시 장비 수령 방법도 질문해 보세요.',
    '단기 무선공유기 상품은 사용 기간과 필요한 설정을 정리해 상담하세요.',
    '단기 무선공유기 요금 상담에서는 반납 일정과 추가 비용도 중요합니다.',
    '단기 무선공유기 상품·요금은 월 이용 조건과 나누어 상담할 수 있습니다.',
  ],
  [
    '설치 주소와 업무 환경에 맞춘 무선인터넷 렌탈 서비스를 제공합니다.',
    '사용 장소와 연결 장비에 맞춘 라우터렌탈 서비스를 이용하실 수 있습니다.',
    '현장 환경과 이용 목적을 반영한 무선공유기 렌탈 서비스를 제공합니다.',
    '건설현장부터 교육 공간까지 사용 환경에 맞춘 라우터렌탈 서비스를 제공합니다.',
    '사업장 구조와 필요한 연결 구성을 고려한 라우터렌탈 서비스를 제공합니다.',
    '사용 공간과 이용 기간에 맞는 무선인터넷 렌탈 서비스를 이용하실 수 있습니다.',
    '설치 주소와 실내·실외 위치에 맞춰 라우터렌탈 서비스를 제공합니다.',
    '데이터 사용 목적과 현장 조건을 반영한 무선인터넷 렌탈 서비스를 제공합니다.',
  ],
];
const total = pools.reduce((count, pool) => count * pool.length, 1);
function compose(index, region) {
  return region + ' ' + pools.map(pool => {
    const text = pool[index % pool.length];
    index = Math.floor(index / pool.length);
    return text;
  }).join(' ');
}
function validate(entry, region, key) {
  assert.equal(entry.region, region, key);
  assert.ok(entry.text.startsWith(region + ' '), key);
  assert.ok(entry.text.length >= 140 && entry.text.length <= 205, `분량 ${entry.text.length}: ${key}`);
  for (const word of ['건설현장', '임시사무실', 'AI교육', '단기', '라우터렌탈', '무선인터넷', '무선와이파이', '무선공유기']) {
    assert.ok(entry.text.includes(word), `키워드 ${word}: ${key}`);
  }
  assert.equal((entry.text.slice(region.length).match(/[^.!?]+[.!?]/g) || []).length, 4, key);
  assert.ok(!/[<>\r\n]/.test(entry.text), key);
}
const targets = [];
for (const absolute of listRouterFiles(ROOT)) {
  const html = fs.readFileSync(absolute, 'utf8');
  if (!html.includes('<body class="router-page">')) continue;
  const heading = html.match(/<h1>([^<]+)<\/h1>/)[1];
  const region = heading.replace(/ 5G 라우터렌탈 · CNR-5G500 무선공유기 임대$/, '');
  assert.notEqual(region, heading, absolute);
  const key = '/' + path.relative(ROOT, absolute).split(path.sep).join('/').replace(/index\.html$/, '');
  targets.push({ key, region, file: absolute, html });
}
assert.equal(targets.length, 4048);
const unique = new Set();
for (const { key, region } of targets) {
  if (!saved.entries[key]) continue;
  validate(saved.entries[key], region, key);
  const normalized = saved.entries[key].text.slice(region.length);
  assert.ok(!unique.has(normalized), `지역명만 다른 소개문: ${key}`);
  unique.add(normalized);
}
let added = 0;
const operations = [];
for (const { key, region, file, html } of targets) {
  if (!saved.entries[key]) {
    assert.ok(write, `소개문 없음: ${key}`);
    const seed = crypto.createHash('sha256').update(key).digest().readUInt32LE(0);
    let text;
    for (let i = 0; i < total; i++) {
      const candidate = compose((seed + i) % total, region);
      if (candidate.length < 140 || candidate.length > 205 || unique.has(candidate.slice(region.length))) continue;
      text = candidate; break;
    }
    assert.ok(text, `문구 조합 부족: ${key}`);
    saved.entries[key] = { region, text };
    unique.add(text.slice(region.length)); added++;
  }
  validate(saved.entries[key], region, key);
  const headers = [...html.matchAll(/<header class="site-header">[\s\S]*?<\/header>/g)];
  assert.equal(headers.length, 1, file);
  const header = headers[0][0];
  assert.equal((header.match(/<p\b[^>]*>[\s\S]*?<\/p>/g) || []).length, 1, file);
  const next = header.replace(/<p\b[^>]*>[\s\S]*?<\/p>/, `<p class="regional-intro">${escapeHtml(saved.entries[key].text)}</p>`);
  const updated = html.replace(header, () => next);
  assert.equal(updated.replace(next, () => header), html, `소개문 외 변경: ${key}`);
  if (write) { if (html !== updated) operations.push({ file, updated }); }
  else assert.equal(updated, html, `HTML 미반영: ${key}`);
}
if (write) {
  if (added) fs.writeFileSync(DATA_FILE, Buffer.from(JSON.stringify(saved, null, 2) + '\n', 'utf8'));
  for (const { file, updated } of operations) fs.writeFileSync(file, Buffer.from(updated, 'utf8'));
}
const lengths = targets.map(item => saved.entries[item.key].text.length);
console.log(JSON.stringify({ pages: targets.length, added, updated: operations.length, normalizedUnique: unique.size,
  minChars: Math.min(...lengths), maxChars: Math.max(...lengths),
  example: saved.entries['/router/emd/부산광역시/동구/'], otherContentPreserved: true }, null, 2));
