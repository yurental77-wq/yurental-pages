/**
 * 구글 시트의 '지역동의어'/'핫지역' 열을 읽어 region_synonyms.json 생성
 * 사용법: node scripts/update_synonyms.js
 * (시트가 '링크 있는 사람 보기 가능'으로 공개돼 있어야 함)
 */
'use strict';
const fs = require('fs');
const path = require('path');

const SHEET_ID = '1rGentuqu4Jhzxv-b-Zu92AejlBXWdoYb6Qp3DO1XhOM';
const GID = '1646398695';
const CSV_URL = `https://docs.google.com/spreadsheets/d/${SHEET_ID}/gviz/tq?tqx=out:csv&gid=${GID}`;
const OUT = path.resolve(__dirname, '../netlify/functions/data/region_synonyms.json');

function parseCSV(text) {
  const rows = []; let row = [], field = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else q = false; }
      else field += c;
    } else {
      if (c === '"') q = true;
      else if (c === ',') { row.push(field); field = ''; }
      else if (c === '\n' || c === '\r') {
        if (c === '\r' && text[i + 1] === '\n') i++;
        if (field !== '' || row.length) { row.push(field); rows.push(row); row = []; field = ''; }
      } else field += c;
    }
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row); }
  return rows;
}

// "키:값1|값2, 키2:값" -> {키:[값...]}
function parseKV(s) {
  const map = {};
  if (!s) return map;
  s.split(',').forEach(part => {
    const seg = part.trim(); if (!seg) return;
    const ci = seg.indexOf(':'); if (ci < 0) return;
    const key = seg.slice(0, ci).trim();
    const vals = seg.slice(ci + 1).split('|').map(v => v.trim()).filter(Boolean);
    if (key) map[key] = (map[key] || []).concat(vals);
  });
  return map;
}

(async () => {
  const res = await fetch(CSV_URL);
  if (!res.ok) throw new Error(`시트 다운로드 실패(${res.status}). 시트를 '링크 있는 사람 보기'로 공개했는지 확인하세요.`);
  const raw = await res.text();
  const rows = parseCSV(raw);
  const header = rows[0];
  const iSyn = header.indexOf('지역동의어'), iHot = header.indexOf('핫지역'), iUse = header.indexOf('사용');

  const result = {};
  for (let r = 1; r < rows.length; r++) {
    const row = rows[r];
    if (iUse >= 0 && (row[iUse] || '').trim().toUpperCase() === 'N') continue;
    const syn = parseKV(row[iSyn] || '');
    const hot = parseKV(row[iHot] || '');
    new Set([...Object.keys(syn), ...Object.keys(hot)]).forEach(k => {
      if (!result[k]) result[k] = { syn: [], hot: [] };
      if (syn[k]) result[k].syn = [...new Set([...result[k].syn, ...syn[k]])];
      if (hot[k]) result[k].hot = [...new Set([...result[k].hot, ...hot[k]])];
    });
  }
  fs.writeFileSync(OUT, JSON.stringify(result, null, 2), 'utf8');
  console.log(`✅ region_synonyms.json 갱신 완료 — ${Object.keys(result).length}개 지역`);
})();
