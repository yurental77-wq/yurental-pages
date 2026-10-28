'use strict';

const { PROVINCE_LABELS } = require('../../netlify/functions/lib/emd-url-paths');

// 표시 경로와 검색엔진 계층을 동일한 3단계로 유지한다.
function emdBreadcrumbs(row, districtUrl, leafUrl, product) {
  const district = row.province === '세종특별자치시'
    ? (row.district || '세종시')
    : `${PROVINCE_LABELS[row.province] || row.province} ${row.district}`.trim();
  return [
    { name: '홈', url: '/' },
    { name: district, url: districtUrl },
    { name: `${row.name} ${product}`, url: leafUrl },
  ];
}

function routerDistrictBreadcrumbs(row, districtUrl) {
  return [
    { name: '홈', url: '/' },
    { name: `${PROVINCE_LABELS[row.province] || row.province} 라우터렌탈`, url: `/router/emd/${row.province}/` },
    { name: row.district || '세종시', url: districtUrl },
  ];
}

module.exports = { emdBreadcrumbs, routerDistrictBreadcrumbs };
