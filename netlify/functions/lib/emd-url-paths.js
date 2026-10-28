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
const areaSlug = row => `${PROVINCE_LABELS[row.province] || row.province}-${districtSlug(row)}`;
function districtPath(row, product = '복합기렌탈') {
  return `${prefix(product)}${areaSlug(row)}/`;
}
function leafPath(row, product = '복합기렌탈') {
  return `/${areaSlug(row)}/${row.name}-${product}/`;
}
function previousRouterLeafPath(row) { return `${districtPath(row, '라우터렌탈')}${row.name}-라우터렌탈/`; }
function previousCopierLeafPath(row) { return `${districtPath(row)}${row.name}-복합기렌탈/`; }
function isRootRouterLeafPath(value) {
  return /^\/[^/]+\/[^/]+-라우터렌탈\/$/.test(value) && !/^\/\.{1,2}\//.test(value);
}
function isRootCopierLeafPath(value) {
  return /^\/[^/]+\/[^/]+-복합기렌탈\/$/.test(value) && !/^\/\.{1,2}\//.test(value);
}
function legacyDistrictPath(row, product = '복합기렌탈') {
  return `${prefix(product)}${row.province}/${districtSlug(row)}/`;
}
function legacyLeafPath(row, product = '복합기렌탈') {
  return `${legacyDistrictPath(row, product)}${row.name}-${row.code}-${product}/`;
}
function createRedirects(rows) {
  const routes = {}, targets = new Map();
  const add = (oldPath, newPath, owner) => {
    if (targets.has(newPath) && targets.get(newPath) !== owner) throw new Error('새 URL 중복: ' + newPath);
    if (Object.hasOwn(routes, oldPath) && routes[oldPath] !== newPath) throw new Error('이전 URL 충돌: ' + oldPath);
    routes[oldPath] = newPath; targets.set(newPath, owner);
  };
  for (const row of rows) for (const product of ['복합기렌탈', '라우터렌탈']) {
    add(legacyDistrictPath(row, product), districtPath(row, product), legacyDistrictPath(row, product));
    add(legacyLeafPath(row, product), leafPath(row, product), `${product}:${row.code}`);
    // 배포했던 /emd/, /router/emd/ 단축 주소도 최종 주소로 직접 이동한다.
    const previous = product === '라우터렌탈' ? previousRouterLeafPath(row) : previousCopierLeafPath(row);
    add(previous, leafPath(row, product), `${product}:${row.code}`);
  }
  return routes;
}
// 새 정적 파일은 우선 제공한다. 이전 주소만 함수가 실제 HTTP 301로 응답한다.
function redirectRules() {
  const lines = ['# EMD-URL-REDIRECTS:START'];
  for (const base of ['/emd', '/router/emd']) {
    lines.push(`${base}/:province/:district/:leaf/*  /.netlify/functions/emd-redirect  200`);
    lines.push(`${base}/:province/:district/:leaf  /.netlify/functions/emd-redirect  200`);
    lines.push(`${base}/:province/:district  /.netlify/functions/emd-redirect  200`);
  }
  lines.push('# EMD-URL-REDIRECTS:END');
  return lines.join('\n') + '\n';
}
module.exports = { PROVINCE_LABELS, districtSlug, areaSlug, districtPath, leafPath, previousRouterLeafPath,
  previousCopierLeafPath, isRootRouterLeafPath, isRootCopierLeafPath,
  legacyDistrictPath, legacyLeafPath, createRedirects, redirectRules };
