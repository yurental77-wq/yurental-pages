// 최초 소개문 생성·저장된 소개문 반영. 기본은 검증만, --write는 상단 소개문만 갱신.
// 실행: node scripts/update_header_intros.js [--write]
'use strict';

const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const crypto = require('crypto');
const { ROOT, DATA, renderPage } = require('../build');
const { validateSource, leafPath } = require('../build-emd');
const { escapeHtml } = require('../netlify/functions/lib/copier-header-intros');
const DATA_FILE = path.join(ROOT, 'netlify/functions/data/copier_header_intros.json');
const saved = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
const emds = validateSource(JSON.parse(fs.readFileSync(path.join(ROOT, 'data/emd_regions.json'), 'utf8')));
const targets = [
  ...DATA.map(item => ({ key: `/pages/${item.province}/${item.slug}/`, region: item.region })),
  ...emds.map(row => ({ key: leafPath(row), region: row.full_name })),
];
const write = process.argv.includes('--write');
assert.equal(new Set(targets.map(item => item.key)).size, targets.length);

// 업종은 해당 지역의 사실이 아니라 상담자가 고려할 수 있는 사용 상황으로 표현한다.
const openings = [
  '{region} 복합기·프린터·복사기 렌탈 문의를 준비하고 계신가요?',
  '{region} 복합기·프린터·복사기 렌탈 문의, 주된 사용 목적은 무엇인가요?',
  '{region} 복합기·프린터·복사기 렌탈 문의, 어떤 업무에 필요한가요?',
  '{region} 복합기·프린터·복사기 렌탈 문의, 꼭 필요한 기능은 무엇인가요?',
  '{region} 복합기·프린터·복사기 렌탈 문의에 필요한 사용 조건을 정하셨나요?',
  '{region} 복합기·프린터·복사기 렌탈 문의, 사용 기간은 정하셨나요?',
  '{region} 복합기·프린터·복사기 렌탈 문의, 하루 출력량은 어느 정도인가요?',
  '{region} 복합기·프린터·복사기 렌탈 문의에 앞서 문서 용도를 정하셨나요?',
  '{region} 복합기·프린터·복사기 렌탈 문의, 어떤 문서를 주로 출력하시나요?',
  '{region} 복합기·프린터·복사기 렌탈 문의, 자주 쓰는 기능은 무엇인가요?',
];
const environments = [
  '칼라·흑백 출력량과 A3·A4 문서 비중, 계약서 스캔 빈도가 기종 선택의 기준입니다.',
  '제안서를 만든다면 칼라·흑백 비율과 A3·A4 문서 크기, 스캔 해상도가 중요합니다.',
  '수업 자료를 준비할 때는 칼라·흑백 출력량, A3·A4 용지와 연속 스캔을 함께 고려합니다.',
  '여러 직원이 쓴다면 칼라·흑백 인쇄량과 A3·A4 문서, 스캔 파일의 공유 방식을 정리합니다.',
  '칼라·흑백 보고서가 몰리는 날의 출력량, A3·A4 문서 크기와 스캔 속도도 고려 대상입니다.',
  '칼라·흑백 안내문을 자주 뽑는다면 A3·A4 사용 비율과 양면 인쇄, 스캔 기능이 중요합니다.',
  '계약 문서를 보관할 때는 칼라·흑백 인쇄량 외에 A3·A4 원고와 양면 스캔이 기준입니다.',
  '칼라·흑백 회의 자료의 월 출력량, A3·A4 사용 여부와 스캔 저장 위치를 정리합니다.',
  '임시 사무실이라면 칼라·흑백 출력량과 A3·A4 문서, 스캔 연결 환경을 먼저 파악합니다.',
  '작업 지시서를 쓴다면 칼라·흑백 구분, A3·A4 출력량과 원고 스캔 빈도를 고려합니다.',
  '칼라·흑백 홍보물의 출력 빈도와 A3·A4 크기, 이미지 스캔 품질도 선택 기준이 됩니다.',
  '칼라·흑백 인쇄가 적더라도 A3·A4 문서와 자주 쓰는 스캔 기능은 따로 정리하는 편이 좋습니다.',
  '칼라·흑백 문서가 섞인 업무라면 A3·A4 급지 방식과 여러 장의 스캔 흐름이 중요합니다.',
  '칼라·흑백 정산 자료를 다룬다면 A3·A4 출력 매수와 증빙 문서의 스캔 빈도를 살핍니다.',
  '칼라·흑백 자료를 부서별로 나눈다면 A3·A4 출력량과 스캔 파일 관리 방식을 고려합니다.',
  '칼라·흑백 발표 자료의 색상 용도, A3·A4 문서 비중과 스캔 필요 여부를 정리합니다.',
  '칼라·흑백 신청서를 처리할 때는 A3·A4 문서 크기와 스캔 원고의 장수가 기준이 됩니다.',
  '칼라·흑백 인쇄를 여러 대로 나눈다면 A3·A4 출력량과 스캔 담당 장비를 정해 두면 좋습니다.',
  '칼라·흑백 문서의 보관 업무가 많다면 A3·A4 출력량과 검색 가능한 스캔 파일이 필요한지 살핍니다.',
  '칼라·흑백 도표를 자주 쓴다면 A3·A4 확대 인쇄와 스캔 기능, 월 출력량을 함께 고려합니다.',
  '칼라·흑백 인쇄가 특정 시기에 몰린다면 A3·A4 문서량과 스캔 대기 시간을 고려합니다.',
  '칼라·흑백 일일 업무 문서의 A3·A4 사용량과 스캔 자료를 옮길 컴퓨터 수를 정리합니다.',
  '칼라·흑백 출력물을 외부에 전달한다면 A3·A4 문서 품질과 스캔 해상도를 함께 살핍니다.',
  '칼라·흑백 인쇄와 스캔을 번갈아 쓴다면 A3·A4 원고 크기와 작업 순서도 고려 대상입니다.',
];
const consultations = [
  '임대·대여 상품과 월 요금은 기본 매수와 초과 단가를 나누어 상담하세요.',
  '임대·대여 상품과 요금 상담에는 예상 매수와 이용 기간을 함께 전달해 주세요.',
  '임대·대여 상품의 요금은 소모품 포함 범위와 약정 조건을 함께 상담할 수 있습니다.',
  '임대·대여 상품과 요금 상담 시 설치 조건과 유지관리 범위도 질문해 보세요.',
  '임대·대여 상품별 월 요금은 기본 매수와 부가세 포함 여부를 함께 상담하면 좋습니다.',
  '임대·대여 상품과 요금은 필요한 기능과 계약 기간을 정리해 상담하는 편이 좋습니다.',
  '임대·대여 상품 상담에서 월 요금 외에 초과 출력 비용도 물어보세요.',
  '임대·대여 상품과 요금은 토너 제공 조건과 방문 비용을 구분해 상담하세요.',
  '임대·대여 상품과 요금 상담은 설치 주소와 희망 이용 기간을 기준으로 진행합니다.',
  '임대·대여 상품을 상담할 때는 월 요금에 어떤 관리 항목이 포함되는지도 중요합니다.',
];
const endings = [
  '플로터는 필요한 용지 폭과 함께 별도로 문의해 주세요.',
  '도면용 플로터는 출력 규격을 정해 별도로 문의해 주세요.',
  '플로터 이용 조건은 대형 출력물의 크기를 알려 별도로 문의해 주세요.',
  '플로터가 필요하다면 도면·포스터 용도를 구분해 별도로 문의해 주세요.',
  '플로터 상품과 요금은 예상 사용량을 기준으로 별도로 문의해 주세요.',
  '플로터는 사무용 장비와 구분하여 별도로 문의해 주세요.',
  '플로터의 기종과 이용 가능 조건은 별도로 문의해 주세요.',
  '플로터 견적은 원하는 출력 폭과 기간을 알려 별도로 문의해 주세요.',
];
const pools = [openings, environments, consultations, endings];
const combinations = pools.reduce((total, pool) => total * pool.length, 1);
function compose(index, region) {
  return pools.map(pool => {
    const sentence = pool[index % pool.length];
    index = Math.floor(index / pool.length);
    return sentence.replace('{region}', region);
  }).join(' ');
}
function validate(entry, region, key) {
  assert.equal(entry.region, region, `지역명 불일치: ${key}`);
  const text = entry.text;
  assert.equal(typeof text, 'string', key);
  assert.ok(text.startsWith(region + ' '), `시작 지역명: ${key}`);
  for (const word of ['칼라', '흑백', '복합기', '프린터', '복사기', '플로터', '임대', '렌탈', '대여', 'A3', 'A4']) {
    assert.ok(text.includes(word), `필수 단어 ${word}: ${key}`);
  }
  // 종로1.2.3.4가동 등 지명 속 마침표는 문장 경계가 아니다.
  const sentences = text.slice(region.length).match(/[^.!?]+[.!?]/g) || [];
  assert.equal(sentences.length, 4, `문장 수: ${key}`);
  assert.ok(sentences[0].includes('렌탈 문의'), key);
  assert.match(sentences[3], /플로터.*별도로 문의/, key);
  assert.ok(text.length >= 140 && text.length <= 205, `길이 ${text.length}: ${key}`);
  assert.ok(!/[<>\r\n]/.test(text), `한 줄 일반 텍스트만 허용: ${key}`);
}

const normalized = new Set();
for (const { key, region } of targets) {
  if (!saved.entries[key]) continue;
  validate(saved.entries[key], region, key);
  const body = saved.entries[key].text.slice(region.length);
  assert.ok(!normalized.has(body), `지역명만 다른 소개문: ${key}`);
  normalized.add(body);
}
let added = 0;
for (const { key, region } of targets) {
  if (saved.entries[key]) continue; // 수동으로 수정한 소개문은 보존한다.
  assert.ok(write, `저장된 소개문 없음: ${key}. --write로 처음 생성하세요.`);
  const seed = crypto.createHash('sha256').update(key).digest().readUInt32LE(0);
  let text;
  for (let attempt = 0; attempt < combinations; attempt++) {
    const candidate = compose((seed + attempt) % combinations, region);
    if (candidate.length < 140 || candidate.length > 205 || normalized.has(candidate.slice(region.length))) continue;
    text = candidate; break;
  }
  assert.ok(text, `소개문 조합 부족: ${key}`);
  saved.entries[key] = { region, text };
  validate(saved.entries[key], region, key);
  normalized.add(text.slice(region.length));
  added++;
}

// 모든 대상과 저장된 문구를 검증한 뒤, 전체 재빌드 없이 header의 p 한 곳만 바꾼다.
const operations = [];
for (const { key } of targets) {
  const file = path.join(ROOT, ...key.split('/').filter(Boolean), 'index.html');
  const html = fs.readFileSync(file, 'utf8');
  const headers = [...html.matchAll(/<header class="site-header">[\s\S]*?<\/header>/g)];
  assert.equal(headers.length, 1, `헤더 수: ${key}`);
  const header = headers[0][0];
  assert.equal((header.match(/<p\b[^>]*>[\s\S]*?<\/p>/g) || []).length, 1, key);
  const newHeader = header.replace(/<p\b[^>]*>[\s\S]*?<\/p>/, `<p class="regional-intro">${escapeHtml(saved.entries[key].text)}</p>`);
  const updated = html.replace(header, () => newHeader);
  assert.equal(updated.replace(newHeader, () => header), html, `소개문 외 변경: ${key}`);
  if (write) {
    if (updated !== html) operations.push({ file, updated });
  } else {
    assert.equal(updated, html, `저장된 소개문이 HTML에 미반영됨: ${key}`);
  }
}
if (write) {
  if (added) fs.writeFileSync(DATA_FILE, JSON.stringify(saved, null, 2) + '\n', 'utf8');
  for (const { file, updated } of operations) fs.writeFileSync(file, updated, 'utf8');
} else {
  // 다음 도시·읍면동 빌드에서도 동일하게 적용되는지 확인한다 (파일 쓰기 없음).
  const city = DATA.find(item => item.region === '의정부');
  const cityKey = `/pages/${city.province}/${city.slug}/`;
  assert.ok(renderPage(city, 0).content.includes(escapeHtml(saved.entries[cityKey].text)));
  const row = emds.find(item => item.name === '연기면');
  assert.ok(renderPage({ ...city, region: row.full_name }, 0, { canonical: 'https://hanarentalbj.kr' + leafPath(row) }).content.includes(escapeHtml(saved.entries[leafPath(row)].text)));
}
const lengths = targets.map(({ key }) => saved.entries[key].text.length);
console.log(JSON.stringify({ pages: targets.length, city: DATA.length, emd: emds.length,
  added, updated: operations.length, normalizedUnique: normalized.size,
  minChars: Math.min(...lengths), maxChars: Math.max(...lengths),
  examples: targets.filter(item => item.region === '의정부' || item.region.endsWith(' 연기면')).map(({ key }) => saved.entries[key]),
}, null, 2));
