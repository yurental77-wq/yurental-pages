/**
 * 행정읍면동 3,565곳 추가 빌드. 기존 도시 페이지/사이트맵/RSS는 보존한다.
 * 사용법: node build-emd.js (node build.js 전체 빌드에서도 호출됨)
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { ROOT, SITE_URL, DATA, renderPage, seededRandom, stripHtml, encodeUrl } = require('./build');
const HUB_TEMPLATE = fs.readFileSync(path.join(ROOT, 'netlify/functions/templates/province_hub_template.html'), 'utf8');
const EMD_ROOT = path.join(ROOT, 'emd');
const SOURCE = path.join(ROOT, 'data/emd_regions.json');
const START = '<!-- EMD-LINKS:START -->';
const END = '<!-- EMD-LINKS:END -->';

function esc(value) {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// 변하지 않은 HTML은 다시 열어 덮어쓰지 않는다. 반복 빌드의 불필요한 IO도 줄인다.
function writeIfChanged(file, content) {
  if (fs.existsSync(file) && fs.readFileSync(file, 'utf8') === content) return;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content, 'utf8');
}

function validateSource(source) {
  const rows = source.regions;
  if (!Array.isArray(rows) || rows.length !== 3565 || source.metadata.count !== rows.length) {
    throw new Error('읍면동 자료는 3,565개여야 합니다.');
  }
  const codes = new Set(), names = new Set();
  for (const row of rows) {
    if (!/^\d{10}$/.test(row.code) || !row.province || !row.name || !row.full_name || !['읍', '면', '동'].includes(row.type)) {
      throw new Error(`필수 지역 정보 오류: ${row.code}`);
    }
    for (const value of [row.province, row.district, row.name]) {
      if (typeof value !== 'string' || /[<>"/\\\x00-\x1f]/.test(value) || value === '.' || value === '..') {
        throw new Error(`안전하지 않은 지역 경로: ${row.code}`);
      }
    }
    if (codes.has(row.code) || names.has(row.full_name)) throw new Error(`중복 지역: ${row.full_name}`);
    if (row.full_name !== [row.province, row.district, row.name].filter(Boolean).join(' ')) throw new Error(`전체 지역명 오류: ${row.code}`);
    codes.add(row.code); names.add(row.full_name);
  }
  return rows;
}

function districtSlug(row) { return (row.district || '세종시').replace(/\s+/g, '-'); }
function districtPath(row) { return `/emd/${row.province}/${districtSlug(row)}/`; }
function leafPath(row) { return `${districtPath(row)}${row.name}-${row.code}-복합기렌탈/`; }
function canonical(urlPath) { return encodeUrl(SITE_URL + urlPath); }
function relative(from, to) {
  const result = path.posix.relative(from, to);
  return result ? result + '/' : './';
}
// '양구'처럼 지명 자체가 '구'로 끝나는 경우를 훼손하지 않는다.
function normalizeName(name) { return name.split(' ').map(token => token.replace(/(시|군)$/, '')).join(' '); }

// 행정명은 새 자료 그대로, 업체는 기존 도시 데이터에서만 조회한다.
function findCity(row) {
  const provinceMap = {
    '서울특별시': '서울', '강원특별자치도': '강원도', '전북특별자치도': '전라북도',
    '경기도': '경기도', '충청북도': '충청북도', '충청남도': '충청남도',
    '경상북도': '경상북도', '경상남도': '경상남도',
  };
  let province = provinceMap[row.province];
  let candidates = [row.district, row.district.split(' ')[0]];
  const metros = { '부산광역시': '부산', '대구광역시': '대구', '인천광역시': '인천', '대전광역시': '대전', '울산광역시': '울산' };
  if (metros[row.province]) {
    province = '광역시'; candidates = [`${metros[row.province]} ${row.district}`];
  }
  if (row.province === '전남광주통합특별시') {
    province = row.district.endsWith('구') ? '광역시' : '전라남도';
    candidates = row.district.endsWith('구') ? [`광주 ${row.district}`] : [row.district];
  }
  if (row.province === '세종특별자치시') { province = '광역시'; candidates = ['세종 세종시']; }
  // 기존 도시 URL을 옮기지 않고 기존 군위 안내 정보에 연결한다.
  if (row.province === '대구광역시' && row.district === '군위군') { province = '경상북도'; candidates = ['군위']; }
  if (!province) return null;
  for (const candidate of candidates) {
    const matches = DATA.filter(city => city.province === province && normalizeName(city.region) === normalizeName(candidate));
    if (matches.length > 1) throw new Error(`도시 매칭 충돌: ${row.full_name}`);
    if (matches.length === 1) return matches[0];
  }
  return null;
}

function breadcrumbs(row) {
  const district = row.district || '세종시';
  return [
    { name: '전국 복합기렌탈 홈', url: '/' },
    { name: '전국 읍·면·동 목록', url: '/emd/' },
    { name: row.province, url: `/emd/${row.province}/` },
    { name: district, url: districtPath(row) },
    { name: `${row.name} 복합기렌탈`, url: leafPath(row) },
  ];
}

function crumbHtml(crumbs, currentPath) {
  return '<div class="crumb">' + crumbs.map((item, i) => i === crumbs.length - 1
    ? esc(item.name) : `<a href="${esc(relative(currentPath, item.url))}index.html">${esc(item.name)}</a>`).join(' &gt; ') + '</div>';
}

function jsonLd(objects) {
  return objects.map(object => `<script type="application/ld+json">\n${JSON.stringify(object).replace(/</g, '\\u003c')}\n</script>`).join('\n');
}

function breadcrumbSchema(crumbs) {
  return { '@context': 'https://schema.org', '@type': 'BreadcrumbList', itemListElement: crumbs.map((item, index) => ({
    '@type': 'ListItem', position: index + 1, name: item.name, item: canonical(item.url),
  })) };
}

function makeFAQ(row) {
  const area = esc(row.full_name);
  const district = esc(row.district || row.province);
  const pool = [
    [`${area} 복합기렌탈 견적을 요청할 때 무엇을 준비하나요?`, '설치 주소, 월 흑백·컬러 예상 출력량, A3 용지 필요 여부, 원하는 계약 기간을 정리해 주세요. 기본 제공 매수, 초과 출력 단가, 부가세와 소모품 포함 여부를 같은 조건으로 비교하면 실제 월 비용을 파악하기 쉽습니다.'],
    [`${esc(row.name)}까지 설치와 출장 AS가 가능한가요?`, `${area}의 정확한 도로명 주소와 건물 정보를 상담 업체에 알려 설치·출장 가능 여부를 먼저 확인하세요. ${district} 안내 업체가 해당 읍·면·동에 출장을 제공하는지, 별도 출장비가 있는지, 고장 접수 후 방문 일정은 어떻게 되는지 확인해야 합니다.`],
    ['복합기를 설치하기 전에 공간과 네트워크는 어떻게 확인하나요?', '기기 크기뿐 아니라 용지함을 열 공간과 점검 공간도 확보하세요. 출입문·복도 폭, 엘리베이터 유무, 설치 층수를 알려 운반 조건을 확인하고, 전원 콘센트와 유선 LAN 또는 Wi-Fi 연결 가능 여부를 점검해 주세요.'],
    ['토너와 소모품은 월 렌탈료에 모두 포함되나요?', '포함 범위는 계약마다 다릅니다. 토너·드럼·롤러 교체, 정기 점검, 출장 수리비가 월 요금에 포함되는지 견적서와 계약서에서 확인하세요. 용지 제공 여부와 사용자 과실 파손 비용도 별도로 확인하는 것이 좋습니다.'],
    ['컬러 복합기와 흑백 복합기는 어떻게 고르면 되나요?', '계약서·공문서 위주라면 흑백 모델을, 홍보물·발표자료 등 컬러 출력이 잦다면 컬러 모델을 비교하세요. A3 출력, 양면 스캔, 자동 원고 급지, 여러 PC의 네트워크 인쇄 등 실제 업무에 필요한 기능을 먼저 정하면 불필요한 비용을 줄일 수 있습니다.'],
    [`${esc(row.name)} 임시 사무실도 단기 렌탈을 상담할 수 있나요?`, '이용 시작일과 종료일, 필요한 기기 수량, 출력량을 먼저 알려 단기 계약 가능 여부를 확인하세요. 장기 계약과 요금이 다를 수 있으며 설치·회수비, 최소 이용 기간, 연장 요금도 함께 비교해야 합니다.'],
    ['5G 라우터도 함께 렌탈할 수 있나요?', '요금표에 CNR-5G500 라우터의 월 요금과 단기 요금이 안내되어 있습니다. 실제 설치 주소에서의 5G·LTE 수신 상태, 연결할 기기 수, 데이터 사용량, 요금제 및 추가 비용을 상담 시 확인하세요. 인터넷 연결 환경에 따라 속도와 이용 가능 여부가 달라집니다.'],
    ['이전하거나 계약을 해지할 때 어떤 조건을 확인하나요?', '사업장 이전 시 재설치·운반비, 서비스 가능 지역, 계약 중 기종 변경 조건을 확인하세요. 중도 해지 위약금, 만료 후 반납 절차, 저장 장치의 문서 데이터 삭제 방법도 계약 전에 문서로 확인하는 것이 안전합니다.'],
    ['페이지의 업체명이 해당 동에 있는 지사라는 뜻인가요?', '아닙니다. 이 페이지는 기존 시·군·구 안내 페이지의 업체 정보를 연결한 상담 가이드입니다. 표시된 업체의 실제 소재지와 해당 설치 주소의 서비스 가능 여부는 홈페이지 또는 전화 상담으로 확인해 주세요.'],
    [`${esc(row.name)}과 다른 지역의 같은 이름 동은 어떻게 구분하나요?`, `이 페이지는 ${area}를 기준으로 안내합니다. 견적 요청 시 읍·면·동 이름만 전달하지 말고 시·도, 시·군·구, 도로명 주소를 함께 알려주세요. 행정동과 법정동 주소가 다를 수 있으므로 실제 설치 주소를 기준으로 상담하는 것이 좋습니다.`],
  ];
  const rnd = seededRandom(row.code);
  for (let i = pool.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [pool[i], pool[j]] = [pool[j], pool[i]]; }
  const items = pool.slice(0, 5).map(([q, a]) => ({ q, a }));
  return { items, html: items.map(({q, a}) => `    <div class="faq-item">\n      <div class="faq-q">${q}</div>\n      <div class="faq-a">${a}</div>\n    </div>`).join('\n\n') };
}

function localInfo(row, siblings, city) {
  const district = esc(row.district || row.province);
  const otherNames = siblings.filter(item => item.code !== row.code).slice(0, 5).map(item => esc(item.name));
  const sourceNote = city ? `기존 ${esc(city.region)} 지역 페이지에 안내된 업체를 연결했습니다.` : '기존 도시 자료에 일치하는 업체가 없어 전국 상담 창구를 안내합니다.';
  return `  <div class="info-section">
    <h3>📌 ${esc(row.name)} 복합기 설치 상담 체크리스트</h3>
    <p>${esc(row.full_name)}에서 복합기를 렌탈하려면 설치 주소와 업무 조건을 먼저 정리하는 것이 좋습니다. ${sourceNote} 이 목록만으로 ${esc(row.name)}에 지사가 있거나 출장이 확정되었다고 볼 수는 없으므로, 정확한 도로명 주소를 알려 설치 가능 여부와 방문 일정을 확인하세요. 월 흑백·컬러 출력량, A3 사용 여부, 양면 스캔과 네트워크 인쇄 기능을 알려주면 필요한 기종을 비교하기 쉽습니다. 건물 층수, 엘리베이터 유무, 출입문 폭, 전원과 인터넷 연결 환경도 함께 전달해 주세요. 견적서에서는 기본 제공 매수와 초과 단가, 토너·부품·출장비 포함 여부, 부가세, 계약 기간과 해지 조건을 각각 확인하는 것이 중요합니다. 같은 ${district} 안에서도 주소와 운반 조건에 따라 방문 일정이나 추가 비용이 달라질 수 있습니다.${otherNames.length ? ` ${district}의 다른 행정읍면동으로는 ${otherNames.join('·')} 등이 있습니다.` : ''}</p>
    <div class="info-tip">행정읍·면·동 기준: ${esc(row.as_of_date)}. 법정동 주소와 다를 수 있으니 실제 설치 주소를 기준으로 상담하세요.</div>
  </div>`;
}

function fallbackCards(row) {
  return `  <div class="info-section">
    <h3>전국 렌탈 상담 창구</h3>
    <p>${esc(row.full_name)}에 매칭되는 기존 도시 업체 자료는 없습니다. 아래 업체에 해당 설치 주소의 서비스 가능 여부를 직접 확인해 주세요.</p>
    <div class="card-links">
      <a class="map-btn consult" href="http://hanarental.net/" target="_blank" rel="noopener">하나렌탈 홈페이지</a>
      <a class="map-btn phone" href="tel:1600-3165">하나렌탈 전화문의</a>
      <a class="map-btn consult" href="https://yurental.com/" target="_blank" rel="noopener">노란우산렌탈 홈페이지</a>
      <a class="map-btn phone" href="tel:1833-4839">노란우산렌탈 전화문의</a>
    </div>
  </div>`;
}

function relatedLinks(row, siblings, city) {
  const nearby = siblings.filter(item => item.code !== row.code);
  const start = Math.max(0, siblings.findIndex(item => item.code === row.code) - 3);
  const selected = nearby.slice(start, start + 6);
  const links = selected.map(item => `<a href="../${esc(leafPath(item).split('/').slice(-2)[0])}/index.html">${esc(item.name)} 복합기렌탈</a>`);
  if (city) links.unshift(`<a href="${esc(relative(leafPath(row), `/pages/${city.province}/${city.slug}/`))}index.html">${esc(city.region)} 도시 안내 페이지</a>`);
  links.push('<a href="../index.html">전체 읍·면·동 목록 보기</a>');
  return `  <section class="emd-related"><h2 class="section-title">${esc(row.district || row.province)} 읍·면·동별 안내</h2><div class="list">${links.join('\n')}</div></section>\n\n`;
}

function renderLeaf(row, index, siblings, city) {
  const crumbs = breadcrumbs(row);
  const url = canonical(leafPath(row));
  const faq = makeFAQ(row);
  const subtitle = `${esc(row.full_name)}의 복합기 기종·요금과 설치 상담 시 확인할 내용을 안내합니다.`;
  const metaDesc = `${row.full_name} 복합기렌탈 상담 가이드. 기종별 렌탈료, 설치 준비, 소모품·AS 확인 사항과 ${row.district || row.province} 읍면동 목록을 확인하세요.`;
  const schema = jsonLd([
    { '@context': 'https://schema.org', '@type': 'FAQPage', mainEntity: faq.items.map(({q, a}) => ({ '@type': 'Question', name: stripHtml(q), acceptedAnswer: { '@type': 'Answer', text: stripHtml(a) } })) },
    breadcrumbSchema(crumbs),
    { '@context': 'https://schema.org', '@type': 'WebPage', name: `${row.full_name} 복합기렌탈 상담 안내`, url, description: metaDesc,
      about: { '@type': 'AdministrativeArea', name: row.full_name, identifier: row.code },
      isPartOf: { '@type': 'WebPage', url: canonical(districtPath(row)), name: `${row.district || row.province} 읍·면·동 목록` } },
  ]);
  const item = { region: row.full_name, province: row.province, slug: row.code, product: '복합기렌탈', dealers: city ? city.dealers : [] };
  const rendered = renderPage(item, index, {
    canonical: url, subtitle, metaDesc: esc(metaDesc), faq, jsonLd: schema,
    serviceArea: `${esc(row.full_name)} 설치·출장 가능 여부는 상담 시 확인`,
    infoHtml: localInfo(row, siblings, city),
    ...(city ? {} : { cardsHtml: fallbackCards(row) }),
    filePath: path.join(ROOT, ...leafPath(row).split('/').filter(Boolean), 'index.html'),
  });
  let html = rendered.content.replaceAll('../../../assets/', '../../../../assets/');
  html = html.replace(/<div class="crumb">[\s\S]*?<\/div>/, crumbHtml(crumbs, leafPath(row)));
  html = html.replace(/<div class="intro-copy">[\s\S]*?<\/div>/, `<div class="intro-copy">
      <strong>${esc(row.full_name)} 복합기렌탈</strong> 상담을 위한 안내 페이지입니다.<br>
      복합기·복사기·프린터의 기종과 렌탈료를 비교하고, 소모품·설치·출장 AS 조건을 확인하세요.<br>
      ${city ? `${esc(city.region)} 도시 안내의 업체 정보를 연결하며,` : '전국 렌탈 상담 창구를 안내하며,'} 실제 설치 주소의 서비스 가능 여부는 업체 상담이 필요합니다.
    </div>`);
  html = html.replace(`${row.full_name} 복합기렌탈 업체 목록</h2>`, `${row.full_name} 복합기렌탈 상담 안내</h2>`);
  html = html.replace('  <div class="faq-wrap">', relatedLinks(row, siblings, city) + '  <div class="faq-wrap">');
  return { ...rendered, content: html };
}

function renderHub(label, urlPath, links, crumbs, description) {
  const assetPrefix = relative(urlPath, '/') || './';
  let html = HUB_TEMPLATE
    .split('{{PROVINCE}}').join(esc(label))
    .split('{{ASSET_PREFIX}}').join(assetPrefix)
    .split('{{CANONICAL}}').join(canonical(urlPath))
    .split('{{LINKS}}').join(links.join('\n'));
  html = html.replace(/<meta name="description" content="[^"]*" \/>/, `<meta name="description" content="${esc(description)}" />`);
  html = html.replace(/<div class="crumb">[\s\S]*?<\/div>/, crumbHtml(crumbs, urlPath));
  html = html.replace('</head>', `${jsonLd([breadcrumbSchema(crumbs)])}\n</head>`);
  return html;
}

function addCityLinks(filePath, links) {
  if (!fs.existsSync(filePath)) return false;
  const original = fs.readFileSync(filePath, 'utf8');
  const block = `${START}\n  <section class="emd-related">\n    <h2 class="section-title">읍·면·동별 복합기렌탈 안내</h2>\n    <div class="list">\n${links.join('\n')}\n    </div>\n  </section>\n${END}\n\n`;
  const cleaned = original.replace(/<!-- EMD-LINKS:START -->[\s\S]*?<!-- EMD-LINKS:END -->\r?\n\r?\n/, '');
  if (!cleaned.includes('  <div class="faq-wrap">')) throw new Error(`도시 페이지 연결 위치 없음: ${filePath}`);
  writeIfChanged(filePath, cleaned.replace('  <div class="faq-wrap">', block + '  <div class="faq-wrap">'));
  return true;
}

function buildEmd() {
  const source = JSON.parse(fs.readFileSync(SOURCE, 'utf8').replace(/^\uFEFF/, ''));
  const rows = validateSource(source);
  const districts = new Map(), provinces = new Map(), cityLinks = new Map();
  const outputs = new Map();
  for (const row of rows) {
    const key = districtPath(row);
    if (!districts.has(key)) districts.set(key, []);
    districts.get(key).push(row);
    if (!provinces.has(row.province)) provinces.set(row.province, new Set());
    provinces.get(row.province).add(key);
  }
  function queue(urlPath, content) {
    const file = path.resolve(ROOT, ...urlPath.split('/').filter(Boolean), 'index.html');
    if (!file.startsWith(EMD_ROOT + path.sep) || outputs.has(file)) throw new Error(`잘못된/중복 출력 경로: ${file}`);
    outputs.set(file, content);
  }
  let mapped = 0;
  const unmatched = new Map();
  rows.forEach((row, index) => {
    const city = findCity(row);
    if (city) mapped++; else unmatched.set(districtPath(row), row.full_name.replace(` ${row.name}`, ''));
    const page = renderLeaf(row, index, districts.get(districtPath(row)), city);
    queue(leafPath(row), page.content);
    if (city) {
      const file = path.join(ROOT, 'pages', city.province, city.slug, 'index.html');
      if (!cityLinks.has(file)) cityLinks.set(file, new Map());
      cityLinks.get(file).set(districtPath(row), row.district || row.province);
    }
  });
  for (const [urlPath, items] of districts) {
    const row = items[0];
    const links = items.map(item => `    <a href="${esc(leafPath(item).split('/').slice(-2)[0])}/index.html">${esc(item.name)} 복합기렌탈</a>`);
    const crumbs = breadcrumbs(row).slice(0, -1);
    queue(urlPath, renderHub(`${row.province} ${row.district || ''} 읍·면·동`.trim(), urlPath, links, crumbs, `${row.full_name.replace(` ${row.name}`, '')}의 ${items.length}개 행정읍면동 복합기렌탈 상담 안내. 기종·요금과 설치 준비 정보를 지역별로 확인하세요.`));
  }
  for (const [province, districtKeys] of provinces) {
    const urlPath = `/emd/${province}/`;
    const links = [...districtKeys].map(key => { const items = districts.get(key); return `    <a href="${esc(districtSlug(items[0]))}/index.html">${esc(items[0].district || '세종시')} (${items.length}곳)</a>`; });
    const crumbs = [{name:'전국 복합기렌탈 홈',url:'/'},{name:'전국 읍·면·동 목록',url:'/emd/'},{name:province,url:urlPath}];
    queue(urlPath, renderHub(`${province} 읍·면·동`, urlPath, links, crumbs, `${province}의 시·군·구별 읍면동 복합기렌탈 안내 목록입니다.`));
  }
  const topLinks = [...provinces].map(([province]) => `    <a href="${esc(province)}/index.html">${esc(province)} (${rows.filter(row => row.province === province).length}곳)</a>`);
  queue('/emd/', renderHub('전국 읍·면·동', '/emd/', topLinks, [{name:'전국 복합기렌탈 홈',url:'/'},{name:'전국 읍·면·동 목록',url:'/emd/'}], '전국 행정읍면동 3,565곳의 복합기렌탈 기종·요금과 설치 상담 안내를 시·도 및 시·군·구별로 확인하세요.'));

  // 모든 경로/HTML을 먼저 준비하고 검사한다. 기존 pages/를 삭제하지 않는다.
  for (const [file, html] of outputs) {
    if (/\{\{[A-Z_]+\}\}/.test(html)) throw new Error(`치환하지 않은 템플릿: ${file}`);
    writeIfChanged(file, html);
  }
  for (const [file, links] of cityLinks) {
    const cityDirectory = '/' + path.relative(ROOT, path.dirname(file)).split(path.sep).join('/') + '/';
    addCityLinks(file, [...links].map(([urlPath, name]) => `      <a href="${esc(relative(cityDirectory, urlPath))}index.html">${esc(name)} 읍·면·동 목록</a>`));
  }
  const topCityHub = path.join(ROOT, 'pages/index.html');
  if (fs.existsSync(topCityHub)) {
    const original = fs.readFileSync(topCityHub, 'utf8');
    const link = '    <a href="../emd/index.html" data-emd-list>전국 읍·면·동 복합기렌탈 목록 (3,565곳)</a>\n';
    if (!original.includes('data-emd-list')) writeIfChanged(topCityHub, original.replace('  <div class="list">\n', '  <div class="list">\n' + link));
  }
  const urls = [...outputs.keys()].map(file => canonical('/' + path.relative(ROOT, path.dirname(file)).split(path.sep).join('/') + '/'));
  const sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls.map(url => `  <url><loc>${esc(url)}</loc></url>`).join('\n') + '\n</urlset>\n';
  writeIfChanged(path.join(ROOT, 'sitemap-emd.xml'), sitemap);
  const robotsPath = path.join(ROOT, 'robots.txt');
  const robots = fs.readFileSync(robotsPath, 'utf8');
  const sitemapLine = `Sitemap: ${SITE_URL}/sitemap-emd.xml`;
  if (!robots.includes(sitemapLine)) writeIfChanged(robotsPath, robots.trimEnd() + '\n' + sitemapLine + '\n');
  const report = { sourceDate: source.metadata.as_of_date, leafPages: rows.length, provinceHubs: provinces.size, districtHubs: districts.size,
    sitemapUrls: urls.length, mappedToCity: mapped, nationwideContactOnly: rows.length - mapped, unmatchedDistricts: [...unmatched.values()] };
  console.log(JSON.stringify(report, null, 2));
  return report;
}

module.exports = { validateSource, findCity, leafPath, districtPath, buildEmd };
if (require.main === module) buildEmd();
