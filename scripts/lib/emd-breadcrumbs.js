'use strict';

const PROVINCE_LABELS = {
  '서울특별시': '서울', '부산광역시': '부산', '대구광역시': '대구',
  '인천광역시': '인천', '대전광역시': '대전', '울산광역시': '울산',
  '광주광역시': '광주', '경기도': '경기', '강원특별자치도': '강원',
  '세종특별자치시': '세종',
  '전북특별자치도': '전북', '전남광주통합특별시': '전남광주',
  '충청북도': '충북', '충청남도': '충남', '경상북도': '경북',
  '경상남도': '경남', '전라남도': '전남', '제주특별자치도': '제주',
};

// URL/목록 계층은 그대로 두고 읍면동 상세의 표시 경로만 간소화한다.
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
