'use strict';

// URL 경로별로 저장된 소개문. 수정 후 node scripts/update_header_intros.js --write 실행.
const { entries } = require('../data/copier_header_intros.json');
const { entries: routerEntries } = require('../data/router_header_intros.json');

function escapeHtml(value) {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function getHeaderIntro(urlPath, fallback) {
  const key = decodeURIComponent(urlPath).replace(/index\.html$/, '');
  const entry = key.startsWith('/router/') ? routerEntries[key] : entries[key];
  return entry ? escapeHtml(entry.text) : fallback;
}

function getMetaDescription(urlPath, fallback) {
  const key = decodeURIComponent(urlPath).replace(/index\.html$/, '');
  const entry = key.startsWith('/router/') ? routerEntries[key] : entries[key];
  // 읍면동 복합기는 기본적으로 지역별 소개문을 검색 설명에도 사용한다.
  // 개별 항목을 false로 설정하면 기존 설명 규칙을 유지할 수 있다.
  const enabled = entry?.useAsMetaDescription ?? key.startsWith('/emd/');
  return entry && enabled ? entry.text : fallback;
}

module.exports = { getHeaderIntro, getMetaDescription, escapeHtml };
