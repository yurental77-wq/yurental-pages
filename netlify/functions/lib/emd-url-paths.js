'use strict';
const PROVINCE_LABELS = {
  '서울특별시': '서울', '부산광역시': '부산', '대구광역시': '대구',
  '인천광역시': '인천', '대전광역시': '대전', '울산광역시': '울산',
  '광주광역시': '광주', '경기도': '경기', '강원특별자치도': '강원',
  '세종특별자치시': '세종', '전북특별자치도': '전북',
  '전남광주통합특별시': '전남광주', '충청북도': '충북', '충청남도': '충남',
  '경상북도': '경북', '경상남도': '경남', '전라남도': '전남', '제주특별자치도': '제주',
};
const prefix = product => product === '라우터렌탈' ? '/router/emd/' : '/emd/';
const districtSlug = row => (row.district || '세종시').replace(/\s+/g, '-');
function districtPath(row, product = '복합기렌탈') {
  const area = `${PROVINCE_LABELS[row.province] || row.province}-${districtSlug(row)}`;
  return `${prefix(product)}${area}/`;
}
function leafPath(row, product = '복합기렌탈') {
  return `${districtPath(row, product)}${row.name}-${product}/`;
}
function legacyDistrictPath(row, product = '복합기렌탈') {
  return `${prefix(product)}${row.province}/${districtSlug(row)}/`;
}
function legacyLeafPath(row, product = '복합기렌탈') {
  return `${legacyDistrictPath(row, product)}${row.name}-${row.code}-${product}/`;
}
function createRedirects(rows) {
  const routes = {}, targets = new Map();
  for (const row of rows) for (const product of ['복합기렌탈', '라우터렌탈']) {
    for (const [oldPath, newPath] of [
      [legacyDistrictPath(row, product), districtPath(row, product)],
      [legacyLeafPath(row, product), leafPath(row, product)],
    ]) {
      if (targets.has(newPath) && targets.get(newPath) !== oldPath) throw new Error('새 URL 중복: ' + newPath);
      routes[oldPath] = newPath; targets.set(newPath, oldPath);
    }
  }
  return routes;
}
// 새 정적 파일은 우선 제공한다. 이전 주소만 함수가 실제 HTTP 301로 응답한다.
function redirectRules() {
  const lines = ['# EMD-URL-REDIRECTS:START'];
  for (const base of ['/emd', '/router/emd']) {
    lines.push(`${base}/:province/:district/:leaf/*  /.netlify/functions/emd-redirect?from=${base}/:province/:district/:leaf/&tail=:splat  200`);
    lines.push(`${base}/:province/:district/:leaf  /.netlify/functions/emd-redirect?from=${base}/:province/:district/:leaf  200`);
    lines.push(`${base}/:province/:district  /.netlify/functions/emd-redirect?from=${base}/:province/:district  200`);
  }
  lines.push('# EMD-URL-REDIRECTS:END');
  return lines.join('\n') + '\n';
}
module.exports = { PROVINCE_LABELS, districtSlug, districtPath, leafPath, legacyDistrictPath, legacyLeafPath, createRedirects, redirectRules };
