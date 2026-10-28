// node scripts/update_router_contact.js [--write]
// 기존 내용을 보존하고 제품 소개 → 요금표 → 상담 제목/박스 순서로 배치한다.
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { moveRouterContact } = require('./lib/router-contact-layout');
const ROOT = path.resolve(__dirname, '..');
const write = process.argv.includes('--write');
const files = [];
function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(file);
    else if (entry.name === 'index.html') files.push(file);
  }
}
walk(path.join(ROOT, 'router'));
const operations = [];
let details = 0, lists = 0;
const contactPattern = /<h2 class="section-title">[^<]*라우터렌탈 상담<\/h2>\s*<section class="router-contact">[\s\S]*?<\/section>/;
const pricingPattern = /<section class="price-section" id="router-pricing">[\s\S]*?<\/section>/;
const ignoreMovedBlock = html => html.replace(contactPattern, '').replace(pricingPattern, '').replace(/>\s+</g, '><');
for (const file of files) {
  const html = fs.readFileSync(file, 'utf8');
  if (!html.includes('class="router-contact"')) {
    assert.ok(!html.includes('<body class="router-page">'), `상담 박스 누락: ${file}`);
    lists++;
    continue;
  }
  const updated = moveRouterContact(html);
  assert.equal(ignoreMovedBlock(updated), ignoreMovedBlock(html), `다른 내용 변경: ${file}`);
  assert.equal(updated.match(contactPattern)[0], html.match(contactPattern)[0], `상담 내용 변경: ${file}`);
  assert.equal(updated.match(pricingPattern)[0], html.match(pricingPattern)[0], `요금표 내용 변경: ${file}`);
  assert.equal(moveRouterContact(updated), updated, `반복 적용 오류: ${file}`);
  assert.ok(updated.indexOf('id="router-pricing"') < updated.indexOf('class="router-contact"'), file);
  assert.equal((updated.match(/class="router-contact"/g) || []).length, 1, file);
  if (write) {
    if (updated !== html) operations.push({ file, updated });
  } else assert.equal(updated, html, `상담 위치 미반영: ${file}`);
  details++;
}
assert.equal(details, 4048);
assert.equal(lists, 28);
// 기존 라우터 빌드와 같이 Buffer 경로를 사용한다 (Windows의 UTF-8 직접 쓰기 오류 방지).
for (const { file, updated } of operations) fs.writeFileSync(file, Buffer.from(updated, 'utf8'));
console.log(JSON.stringify({ details, listsUnchanged: lists, updated: operations.length, otherContentPreserved: true }, null, 2));
