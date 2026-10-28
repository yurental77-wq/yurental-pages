/** 도시 및 행정읍면동 라우터 페이지 생성. 실행: node build-router.js */
'use strict';
const fs = require('fs');
const path = require('path');
const { emdBreadcrumbs, routerDistrictBreadcrumbs } = require('./scripts/lib/emd-breadcrumbs');
const { moveRouterContact } = require('./scripts/lib/router-contact-layout');
const { ROOT, SITE_URL, DATA, renderPage, encodeUrl, stripHtml, seededRandom } = require('./build');
const { validateSource, findCity, leafPath, districtPath } = require('./build-emd');
const PRODUCT = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/router_product.json'), 'utf8'));
const HUB_TEMPLATE = fs.readFileSync(path.join(ROOT,'netlify/functions/templates/province_hub_template.html'),'utf8');
const ROUTER_ROOT = path.join(ROOT, 'router');
const phoneHref = 'tel:' + PRODUCT.phone.replace(/-/g, '');
const mobileHref = 'tel:' + PRODUCT.mobile.replace(/-/g, '');
const money = price => price.toLocaleString('ko-KR');
const esc = text => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// 장식용 선 아이콘: 내용과 접근성 이름은 기존 제목에서 제공한다.
function routerIcon(index) {
  const shapes = [
    '<path d="M4 21V8l8-5 8 5v13M3 21h18M9 21v-5h6v5M8 9h1m6 0h1M8 12h1m6 0h1"/>',
    '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4m-4-10 3-3m2 6 3-3"/>',
    '<path d="M3 10h18l-2-6H5l-2 6Zm1 0v10h16V10M9 20v-6h6v6M3 10c0 3 4 3 4 0 0 3 5 3 5 0 0 3 5 3 5 0 0 3 4 3 4 0"/>',
    '<rect x="3" y="5" width="13" height="10" rx="2"/><path d="m16 8 5-2v8l-5-2M7 15v5m-3 0h10"/>',
    '<path d="m3 11 9-8 9 8M5 9v12h14V9M9 21v-7h6v7M8 8c2-2 6-2 8 0m-6 2c1-1 3-1 4 0"/>',
    '<rect x="3" y="12" width="18" height="8" rx="2"/><path d="M7 16h.01M11 16h.01M6 7a9 9 0 0 1 12 0M9 10a5 5 0 0 1 6 0"/>',
    '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M8 3v4m8-4v4M4 11h16m-11 4h6m-6 3h3"/>',
  ];
  return `<span class="router-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" focusable="false">${shapes[index]}</svg></span>`;
}

const FAQ = [
  ['익산에서 라우터렌탈을 상담하려면 무엇을 알려줘야 하나요?', '도로명 주소, 설치할 건물의 층수와 실내·실외 위치, 이용 시작일과 기간, 월 예상 데이터량을 준비해 주세요. PC·태블릿·CCTV 등 연결할 기기의 종류와 수량을 알려주면 통신 환경과 연결 방법을 함께 확인할 수 있습니다.'],
  ['CNR-5G500의 기간별 렌탈료는 얼마인가요?', `3일 ${money(PRODUCT.plans[0].price)}원, 15일 ${money(PRODUCT.plans[1].price)}원, 월 ${money(PRODUCT.plans[2].price)}원이며 부가세는 별도입니다. 데이터 요금, 설치·회수와 연장 비용 등 계약에 포함되는 범위는 견적 상담에서 확인해 주세요.`],
  ['익산 어느 주소에서나 5G가 같은 속도로 연결되나요?', '그렇지는 않습니다. 서비스 범위, 건물 구조, 설치 층수, 통신 음영, 망 혼잡과 요금제에 따라 연결 방식과 속도가 달라집니다. 설치 주소와 사용할 위치를 먼저 알려 5G·LTE 이용 가능 여부를 확인하세요.'],
  ['유선 인터넷 공사 없이 사용할 수 있나요?', 'CNR-5G500은 5G·LTE 이동통신망을 이용하는 설치형 라우터입니다. 통신 개통 조건과 수신 상태를 확인한 뒤 전원 및 기기를 연결해 이용하도록 안내받을 수 있습니다. 현장에 따라 추가 장비나 설정이 필요한지는 상담 시 확인하세요.'],
  ['PC는 유선으로, 노트북은 와이파이로 함께 연결할 수 있나요?', '기가비트 LAN 2포트와 2.4GHz·5GHz Wi-Fi 5·Wi-Fi 6를 지원합니다. 연결 장비 수와 네트워크 구성에 따라 허브 등 별도 장비가 필요한지, 사용량과 통신 조건이 적절한지 확인해 주세요.'],
  ['AI 교육, CCTV나 키오스크 용도로도 상담할 수 있나요?', '교육·실습용 태블릿과 노트북, 현장 CCTV, 키오스크 등 연결 장비에 맞춘 구성을 상담할 수 있습니다. 영상 전송이나 클라우드 작업은 데이터 사용량이 커질 수 있으므로 예상 사용량과 장비의 네트워크 요구사항을 함께 알려주세요.'],
  ['VPN과 원격 관리 기능은 바로 사용할 수 있나요?', '제품은 Secuway·Axgate SSL VPN agent와 NMS 원격 관리를 지원합니다. 다만 실제 적용은 기업망 정책, 관리 계정, 장비 구성과 계약 조건을 확인해야 합니다. 원하는 기능을 상담 단계에서 구체적으로 전달해 주세요.'],
  ['단기 렌탈을 연장하거나 반납할 때 무엇을 확인하나요?', '연장 가능 여부와 추가 요금, 장비 회수 방법과 일정, 반납 지연·분실·파손 시 비용을 계약 전에 확인하세요. 이용 종료 후에는 계정 및 접속 정보 처리 방법도 안내받는 것이 좋습니다.'],
];

function faqContent(region, seed) {
  const items = FAQ.map(([q, a]) => ({ q:q.replaceAll('익산',region), a }));
  if (region !== '익산') {
    const random = seededRandom(seed);
    for (let i=items.length-1;i>0;i--) { const j=Math.floor(random()*(i+1)); [items[i],items[j]]=[items[j],items[i]]; }
  }
  return { items, html: items.map(({q, a}) => `    <div class="faq-item">\n      <div class="faq-q">${esc(q)}</div>\n      <div class="faq-a">${esc(a)}</div>\n    </div>`).join('\n\n') };
}

function structuredData(faq, context) {
  const { title, description, urlPath, crumbs, fullName, code } = context;
  const canonical = encodeUrl(SITE_URL + urlPath);
  const objects = [
    { '@context':'https://schema.org', '@type':'WebPage', name:title, url:canonical, description, about:{'@type':'AdministrativeArea',name:fullName,...(code ? {identifier:code} : {})} },
    breadcrumbSchema(crumbs),
    { '@context':'https://schema.org', '@type':'Product', name:PRODUCT.model+' 5G·LTE 라우터', model:PRODUCT.model,
      brand:{'@type':'Brand',name:PRODUCT.brand}, image:PRODUCT.image, description:'Wi-Fi 6와 기가비트 LAN 2포트를 지원하는 설치형 5G·LTE 라우터.',
      offers:PRODUCT.plans.map(plan=>({'@type':'Offer',name:plan.label+' (부가세 별도)',url:canonical,price:plan.price,priceCurrency:'KRW',businessFunction:'http://purl.org/goodrelations/v1#LeaseOut',
        priceSpecification:{'@type':'UnitPriceSpecification',price:plan.price,priceCurrency:'KRW',unitText:plan.period,valueAddedTaxIncluded:false}})),
    },
    { '@context':'https://schema.org', '@type':'FAQPage', mainEntity:faq.items.map(({q,a})=>({'@type':'Question',name:stripHtml(q),acceptedAnswer:{'@type':'Answer',text:stripHtml(a)}})) },
  ];
  return objects.map(object=>'<script type="application/ld+json">\n'+JSON.stringify(object).replace(/</g,'\\u003c')+'\n</script>').join('\n');
}

function usageContent(region, areaNote) {
  const cases = [
    ['건설현장·컨테이너', '공사 기간 동안 사용할 임시 사무실의 PC와 업무 장비를 연결할 때, 설치 위치와 전원 환경부터 확인하세요.'],
    ['AI 교육·실습 공간', '수업에 사용하는 노트북·태블릿 수와 클라우드 작업량을 알려 교육 일정에 맞는 네트워크 조건을 상담하세요.'],
    ['팝업매장·행사장', '며칠 또는 수주간 운영하는 공간이라면 단기 요금과 이용 기간, 장비 수령·회수 일정을 함께 비교하세요.'],
    ['CCTV·키오스크', '영상 전송량, 장비의 유선 연결 방식과 외부 접속 설정을 알려 네트워크 구성이 가능한지 확인하세요.'],
    ['외곽 사업장·농장', '고정 회선 설치가 어려운 곳에서는 실제 사용할 위치의 이동통신 신호와 실내·실외 운용 조건이 중요합니다.'],
    ['업무용 백업 회선', '기존 회선의 보조 연결로 사용하려면 유·무선 전환 방식, 사내망 정책과 필요한 설정을 사전에 상담하세요.'],
  ];
  return `  <section class="info-section" aria-labelledby="router-use-title">
    <h2 class="section-title" id="router-use-title" style="margin-top:0">${esc(region)}에서 이런 환경이라면 라우터렌탈을 확인하세요</h2>
    <div class="router-features">${cases.map(([title,text],index)=>`<article class="router-feature">${routerIcon(index)}<h3>${title}</h3><p>${text}</p></article>`).join('\n')}</div>
    <div class="info-tip">${esc(areaNote)} 지역명만으로 설치 가능 여부나 통신속도를 확정할 수는 없습니다.</div>
  </section>`;
}

function priceContent() {
  return `  <section class="price-section" id="router-pricing">
    <h2 class="price-section__title">CNR-5G500 라우터 렌탈 요금</h2>
    <p class="price-section__sub">필요한 이용 기간을 정한 뒤, 데이터와 설치 조건을 함께 확인하세요</p>
    <div class="router-plans">${PRODUCT.plans.map(plan=>`<article class="router-plan">${routerIcon(6)}<h3>${esc(plan.label)}</h3><div class="router-plan-price">${money(plan.price)}<span>원</span></div><small>부가세 별도</small><p>${esc(plan.use)}</p><a class="map-btn phone" href="${phoneHref}">${esc(plan.period)} 이용 상담</a></article>`).join('\n')}</div>
    <p class="price-note">※ 안내 금액은 부가세 별도입니다. 데이터 요금, 개통·설치·회수·연장 비용 및 제공 범위는 이용 조건에 따라 상담 시 확인해 주세요.</p>
  </section>
  <section class="info-section" id="router-specs">
    <h2 class="section-title" style="margin-top:0">CNR-5G500 주요 사양</h2>
    <div class="router-spec-wrap"><table class="router-spec-table"><caption style="text-align:left;padding:16px 22px">${esc(PRODUCT.brand)} ${esc(PRODUCT.model)} 제품 사양</caption><tbody>${PRODUCT.specs.map(([label,value])=>`<tr><th scope="row">${esc(label)}</th><td>${esc(value)}</td></tr>`).join('\n')}</tbody></table></div>
    <p class="router-small">LAN의 기가비트 규격이 실제 인터넷 속도를 보장하는 것은 아닙니다. 통신망과 현장 조건에 따라 속도가 달라지며, VPN·원격 관리 설정은 별도 확인이 필요합니다.</p>
  </section>
  <section class="info-section">
    <h2 class="section-title" style="margin-top:0">견적 상담 전 준비할 5가지</h2>
    <ol class="router-checklist"><li>정확한 설치 주소와 실내·실외 위치, 건물 층수</li><li>이용 시작일·종료일과 연장 가능성</li><li>월 예상 데이터 사용량과 영상·클라우드 사용 여부</li><li>PC·CCTV·키오스크·태블릿 등 연결 장비의 종류와 수량</li><li>유선 LAN·와이파이·VPN 등 필요한 네트워크 구성</li></ol>
  </section>`;
}

function processContent(region) {
  const steps = [
    ['사용 환경 상담',`${region} 내 설치 주소, 이용 기간, 데이터량과 연결 장비를 알려주세요.`],
    ['통신·요금 확인','설치 위치의 수신 환경과 이용 가능한 구성, 계약 조건을 확인합니다.'],
    ['장비·개통 준비','필요한 장비와 통신 개통 사항, 설치 또는 수령 일정을 협의합니다.'],
    ['연결·사용 안내','유선·와이파이 연결, 관리 방법과 이용 종료 시 반납 절차를 안내받습니다.'],
  ];
  return `  <section class="process-section"><h2 class="process-section__title">라우터 렌탈 진행 절차</h2><p class="process-section__sub">현장 조건을 먼저 확인하고 이용 일정을 정합니다</p><div class="process-steps">${steps.map(([title,text],index)=>`<div class="process-step"><div class="step-num">0${index+1}</div><div class="step-title">${esc(title)}</div><div class="step-desc">${esc(text)}</div></div>`).join('\n')}</div></section>`;
}

function renderRouter(context) {
  const { region, urlPath, crumbs, areaNote, links, province } = context;
  const title = `${region} 5G 라우터렌탈 · CNR-5G500 무선공유기 임대`;
  const description = `${region} CNR-5G500 5G·LTE 라우터렌탈 안내. 3일 8만원·15일 10만원·월 13만원(부가세 별도), Wi-Fi 6·LAN 2포트 사양과 설치 상담 체크리스트를 확인하세요.`;
  const canonical = encodeUrl(SITE_URL + urlPath);
  const prefix = relative(urlPath, '/');
  const sourceUrl = region === '익산' ? PRODUCT.regionalSourceUrl : PRODUCT.sourceUrl;
  const faq = faqContent(region, context.code || urlPath);
  const contact = `<section class="router-contact"><p>라우터 전용 상담 창구 · 평일 09:00~18:00</p><a class="router-contact-number" href="${phoneHref}">${PRODUCT.phone}</a><p>휴대폰 상담 ${PRODUCT.mobile}</p><div class="card-links"><a class="map-btn phone" href="${phoneHref}">전화 견적 상담</a><a class="map-btn consult" href="${mobileHref}">휴대폰 상담</a><a class="map-btn google" href="${sourceUrl}" target="_blank" rel="noopener">노란우산렌탈 제품 안내</a></div><p class="router-small">이 페이지는 ${esc(region)} 이용자를 위한 안내이며, ${esc(region)} 소재 지사 또는 모든 주소의 설치 가능 여부를 의미하지 않습니다.</p></section>`;
  const item = { region, province, slug:context.code || region, product:'라우터렌탈', dealers:[] };
  const page = renderPage(item, 0, {title,subtitle:'건설현장·임시 사무실·AI 교육 공간을 위한 5G·LTE 무선 인터넷 상담 안내',metaDesc:esc(description),canonical,cardsHtml:contact,faq,jsonLd:structuredData(faq, {...context,title,description}),infoHtml:usageContent(region,areaNote)});
  let html = page.content.replace('<body>', '<body class="router-page">').replaceAll('../../../assets/', prefix+'assets/');
  html = html.replace('</head>', `  <link rel="stylesheet" href="${prefix}assets/router.css?v=20261028c" />\n</head>`);
  html = html.replace(/<meta name="keywords" content="[^"]*" \/>/, `<meta name="keywords" content="${esc(region)} 라우터렌탈,${esc(region)} 5G 라우터,무선공유기 임대,에그대여,CNR-5G500,Wi-Fi 6,단기 인터넷" />`);
  html = html.replace(/(<meta (?:property="og:image"|name="twitter:image") content=")[^"]+(" \/>)/g, '$1'+PRODUCT.image+'$2');
  html = html.replace(/<div class="crumb">[\s\S]*?<\/div>/, crumbHtml(crumbs,urlPath));
  html = html.replace(/<div class="intro-copy">[\s\S]*?<\/div>/, `<div class="intro-copy"><div class="router-kicker">5G · LTE / WI-FI 6 / GIGABIT LAN</div><p class="router-lead">${esc(region)} 건설현장, 임시 사무실, AI 교육·실습<br>라우터렌탈 무선공유기임대 에그대여</p><p class="router-intro-description">유선 회선 개통을 기다리기 어렵거나 일정 기간만 인터넷이 필요한 사업장을 위한 설치형 라우터입니다.</p><p class="router-intro-description">이용 기간과 연결 장비를 정리해 현장에 맞는 렌탈 조건을 상담할 수 있습니다.</p><div class="router-intro-actions"><a class="map-btn phone" href="${phoneHref}">전화 상담 ${PRODUCT.phone}</a><a class="map-btn google" href="#router-pricing">기간별 요금 보기</a><a class="map-btn google" href="#router-specs">제품 사양 보기</a></div><p class="router-small">실제 연결 방식·속도는 통신망, 건물 구조, 설치 위치와 요금제에 따라 달라집니다.</p></div>`);
  html = html.replace(/<img class="intro-thumbnail"[^>]+>/, `<img class="intro-thumbnail" src="${PRODUCT.introImage ? prefix + PRODUCT.introImage : PRODUCT.image}" alt="CNR-5G500 ${esc(region)} 5G 라우터렌탈 안내" width="1254" height="1254" decoding="async" />`);
  html = html.replace(/<section class="price-section">[\s\S]*?<\/section>/, priceContent());
  html = html.replace(/<section class="process-section">[\s\S]*?<\/section>/, processContent(region));
  html = html.replace(/<div class="seo-q-box">[\s\S]*?<\/div>/, `<div class="seo-q-box"><h2>${esc(region)} 라우터렌탈, 설치 주소와 이용 기간부터 확인하세요</h2><p>데이터 사용량과 장비 구성을 함께 전달하면 견적 조건을 비교하기 쉽습니다. 설치 일정과 서비스 가능 여부는 상담 후 안내받으세요.</p></div>`);
  html = html.replace(`📍 ${region} 라우터렌탈 업체 목록`, `${esc(region)} 라우터렌탈 상담`);
  html = html.replace('❓ FAQ 라우터렌탈 자주 묻는 질문', `❓ FAQ ${esc(region)} 라우터렌탈 자주 묻는 질문`);
  html = html.replace('  <div class="faq-wrap">', relatedHtml(region,urlPath,links)+'  <div class="faq-wrap">');
  html = html.replace(/<p>본 페이지는 [^<]+<\/p>/, `<p>${esc(region)} CNR-5G500 라우터렌탈 이용 안내입니다. 실제 설치 및 계약 조건은 상담 시 확인해 주세요.</p>`);
  html = html.replace(/\n<\/div>\s*\n<footer/, `\n  <p class="router-source">제품 사양·요금 참고: <a href="${sourceUrl}" target="_blank" rel="noopener">노란우산렌탈 CNR-5G500 안내</a> · 확인일 ${PRODUCT.verifiedDate}</p>\n</div>\n<footer`);
  // 요금표만 제품 소개 바로 아래로 이동한다. 사양과 체크리스트 위치는 유지한다.
  const pricing = html.match(/<section class="price-section" id="router-pricing">[\s\S]*?<\/section>/)?.[0];
  const usageStart = '<section class="info-section" aria-labelledby="router-use-title">';
  if (!pricing || !html.includes(usageStart)) throw new Error('요금표 이동 위치를 찾을 수 없습니다.');
  html = html.replace(pricing, '').replace(usageStart, pricing + '\n\n  ' + usageStart);
  // 제품 소개 → 요금표 → 상담 제목/연락처 순서를 유지한다.
  html = moveRouterContact(html);
  if (/\{\{[A-Z_]+\}\}/.test(html) || html.includes('월 인쇄량')) throw new Error('라우터 페이지에 잘못된 템플릿 내용이 남았습니다.');
  return html.replace(/^[\t ]+$/gm,'');
}

function relative(from, to) {
  const value = path.posix.relative(from, to);
  return value ? value+'/' : './';
}

function breadcrumbSchema(crumbs) {
  return {'@context':'https://schema.org','@type':'BreadcrumbList',itemListElement:crumbs.map((item,index)=>({
    '@type':'ListItem',position:index+1,name:item.name,item:encodeUrl(SITE_URL+item.url),
  }))};
}

function crumbHtml(crumbs, urlPath) {
  return '<div class="crumb">'+crumbs.map((item,index)=>index===crumbs.length-1
    ? esc(item.name) : '<a href="'+esc(relative(urlPath,item.url))+'index.html">'+esc(item.name)+'</a>').join(' &gt; ')+'</div>';
}

function relatedHtml(region, urlPath, links) {
  return '<section><h2 class="section-title">'+esc(region)+' 지역별 렌탈 안내</h2><div class="list">'+links.map(item=>
    '<a href="'+esc(relative(urlPath,item.url))+'index.html">'+esc(item.name)+'</a>').join('\n')+'</div></section>\n\n';
}

function renderHub(label, urlPath, links, crumbs, description) {
  let html = HUB_TEMPLATE.replaceAll('복합기렌탈','라우터렌탈')
    .replaceAll('{{PROVINCE}}',esc(label))
    .replaceAll('{{ASSET_PREFIX}}',relative(urlPath,'/'))
    .replaceAll('{{CANONICAL}}',encodeUrl(SITE_URL+urlPath))
    .replaceAll('{{LINKS}}',links.map(item=>'<a href="'+esc(relative(urlPath,item.url))+'index.html">'+esc(item.name)+'</a>').join('\n'));
  html = html.replace(/<meta name="description" content="[^"]*" \/>/,'<meta name="description" content="'+esc(description)+'" />')
    .replace(/<div class="crumb">[\s\S]*?<\/div>/,crumbHtml(crumbs,urlPath))
    .replace('</head>','<script type="application/ld+json">'+JSON.stringify(breadcrumbSchema(crumbs)).replace(/</g,'\\u003c')+'</script>\n</head>');
  return html;
}

// 기존 복합기 페이지 본문은 보존하고, 표시한 연결 블록만 갱신한다.
function addCopierLink(file, label, fromPath, routerPath) {
  if (!fs.existsSync(file)) throw new Error('복합기 연결 페이지 없음: '+file);
  const original = fs.readFileSync(file,'utf8');
  const clean = original.replace(/<!-- ROUTER-LINK:START -->[\s\S]*?<!-- ROUTER-LINK:END -->\r?\n\r?\n/g,'');
  const marker = '  <div class="faq-wrap">';
  if (!clean.includes(marker)) throw new Error('라우터 연결 위치 없음: '+file);
  const block = '<!-- ROUTER-LINK:START -->\n  <section><h2 class="section-title">'+esc(label)+' 5G 라우터렌탈 안내</h2><div class="list"><a href="'+esc(relative(fromPath,routerPath))+'index.html">CNR-5G500 라우터 사양·단기·월 렌탈 요금 보기</a></div></section>\n<!-- ROUTER-LINK:END -->\n\n';
  writeIfChanged(file,clean.replace(marker,block+marker));
}

function buildRouter() {
  const source = JSON.parse(fs.readFileSync(path.join(ROOT,'data/emd_regions.json'),'utf8'));
  const rows = validateSource(source);
  const outputs = new Map(), districts = new Map(), provinces = new Map(), cityProvinces = new Map();
  const cityCounts = new Map();
  DATA.forEach(city=>cityCounts.set(city.region,(cityCounts.get(city.region)||0)+1));
  const cityPath = city=>'/router/'+(cityCounts.get(city.region)>1 ? city.province+'-' : '')+city.region.replace(/\s+/g,'-')+'/';
  const routerDistrict = row=>'/router'+districtPath(row);
  const routerLeaf = row=>routerDistrict(row)+row.name+'-'+row.code+'-라우터렌탈/';
  const copierCity = city=>'/pages/'+city.province+'/'+city.slug+'/';
  const mainCrumb = {name:'전국 렌탈 홈',url:'/'};
  const routerCrumb = {name:'전국 라우터렌탈',url:'/router/'};
  const emdCrumb = {name:'라우터 읍·면·동 목록',url:'/router/emd/'};
  const cityDistricts = new Map();
  for (const row of rows) {
    const key = routerDistrict(row);
    if (!districts.has(key)) districts.set(key,[]);
    districts.get(key).push(row);
    if (!provinces.has(row.province)) provinces.set(row.province,new Set());
    provinces.get(row.province).add(key);
    const city = findCity(row);
    if (city) {
      const ckey = copierCity(city);
      if (!cityDistricts.has(ckey)) cityDistricts.set(ckey,new Map());
      cityDistricts.get(ckey).set(key,{name:(row.district||'세종시')+' 라우터 읍·면·동 목록',url:key});
    }
  }
  function queue(urlPath, html) {
    const file = path.resolve(ROOT,...urlPath.split('/').filter(Boolean),'index.html');
    if (!file.startsWith(ROUTER_ROOT+path.sep) || outputs.has(urlPath)) throw new Error('중복/잘못된 라우터 경로: '+urlPath);
    if (/\{\{[A-Z_]+\}\}/.test(html)) throw new Error('미치환 라우터 템플릿: '+urlPath);
    outputs.set(urlPath,{file,html});
  }
  const connections = [];
  for (const city of DATA) {
    if (/[<>"\/\\\x00-\x1f]/.test(city.region) || city.region==='.' || city.region==='..') throw new Error('도시 경로 오류: '+city.region);
    const urlPath = cityPath(city);
    const region = cityCounts.get(city.region)>1 ? city.province+' '+city.region : city.region;
    const provincePath = '/router/regions/'+city.province+'/';
    if (!cityProvinces.has(city.province)) cityProvinces.set(city.province,[]);
    cityProvinces.get(city.province).push({name:region+' 라우터렌탈',url:urlPath});
    const districtLinks = [...(cityDistricts.get(copierCity(city))||new Map()).values()];
    const localRows = rows.filter(row=>districtLinks.some(link=>link.url===routerDistrict(row)));
    const areaNote = city.region==='익산' ? '영등동·모현동·어양동·함열읍·황등면 등 익산 내 설치 주소와 현장 정보를 알려주세요.'
      : (localRows.length ? localRows.slice(0,5).map(row=>row.name).join('·')+' 등 '+region+' 내 설치 주소와 현장 정보를 알려주세요.' : region+'의 정확한 설치 주소와 현장 정보를 알려주세요.');
    queue(urlPath,renderRouter({region,province:city.province,fullName:city.province+' '+city.region,urlPath,areaNote,
      crumbs:[mainCrumb,routerCrumb,{name:city.province+' 도시 목록',url:provincePath},{name:region+' 라우터렌탈',url:urlPath}],
      links:[{name:city.region+' 복합기렌탈 기종·요금',url:copierCity(city)},...districtLinks,{name:'전국 라우터 도시 목록',url:'/router/'}],
    }));
    connections.push({file:path.join(ROOT,...copierCity(city).split('/').filter(Boolean),'index.html'),label:region,fromPath:copierCity(city),urlPath});
  }
  for (const [urlPath,siblings] of districts) {
    const row = siblings[0], city = findCity(row), label = [row.province,row.district||'세종시'].join(' ');
    const provincePath = '/router/emd/'+row.province+'/';
    const crumbs = routerDistrictBreadcrumbs(row, urlPath);
    queue(urlPath,renderRouter({region:label,province:row.province,fullName:label,urlPath,
      areaNote:siblings.slice(0,5).map(item=>item.name).join('·')+' 등 '+label+'의 설치 주소와 현장 정보를 알려주세요.',
      crumbs,links:[...(city ? [{name:city.region+' 도시 라우터 안내',url:cityPath(city)}] : []),...siblings.map(item=>({name:item.name+' 라우터렌탈',url:routerLeaf(item)}))],
    }));
    siblings.forEach((item,index)=>{
      const leaf = routerLeaf(item);
      const links = [{name:(row.district||'세종시')+' 전체 라우터 읍·면·동 목록',url:urlPath},
        ...siblings.filter(other=>other.code!==item.code).slice(Math.max(0,index-3),Math.max(0,index-3)+6).map(other=>({name:other.name+' 라우터렌탈',url:routerLeaf(other)})),
        {name:item.name+' 복합기렌탈 안내',url:leafPath(item)}];
      if (city) links.push({name:city.region+' 도시 라우터 안내',url:cityPath(city)});
      queue(leaf,renderRouter({region:item.full_name,province:item.province,fullName:item.full_name,code:item.code,urlPath:leaf,
        areaNote:item.full_name+'의 도로명 주소, 설치 층수와 실내·실외 위치를 알려주세요. 행정읍면동 자료 기준은 '+item.as_of_date+'이며 법정동 주소와 다를 수 있습니다.',
        crumbs:emdBreadcrumbs(item,urlPath,leaf,'라우터렌탈'),links}));
      connections.push({file:path.join(ROOT,...leafPath(item).split('/').filter(Boolean),'index.html'),label:item.full_name,fromPath:leafPath(item),urlPath:leaf});
    });
  }
  for (const [province,keys] of provinces) {
    const urlPath = '/router/emd/'+province+'/';
    const links = [...keys].map(key=>{const items=districts.get(key);return {name:(items[0].district||'세종시')+' ('+items.length+'곳)',url:key};});
    queue(urlPath,renderHub(province+' 읍·면·동',urlPath,links,[mainCrumb,routerCrumb,emdCrumb,{name:province,url:urlPath}],province+' 시·군·구별 라우터렌탈 및 무선공유기 임대 안내 목록입니다.'));
  }
  for (const [province,links] of cityProvinces) {
    const urlPath = '/router/regions/'+province+'/';
    queue(urlPath,renderHub(province+' 주요 도시',urlPath,links,[mainCrumb,routerCrumb,{name:province+' 도시 목록',url:urlPath}],province+' 도시별 5G 라우터렌탈·무선공유기 임대·에그대여 상담 안내입니다.'));
  }
  queue('/router/emd/',renderHub('전국 읍·면·동','/router/emd/',[...provinces.keys()].map(province=>({name:province,url:'/router/emd/'+province+'/'})),
    [mainCrumb,routerCrumb,emdCrumb],'전국 행정읍면동 3,565곳의 CNR-5G500 라우터렌탈 요금과 설치 상담 안내 목록입니다.'));
  queue('/router/',renderHub('전국 도시 및 읍·면·동','/router/',[
    {name:'전국 읍·면·동 라우터렌탈 (3,565곳)',url:'/router/emd/'},
    ...[...cityProvinces.keys()].map(province=>({name:province+' 도시 라우터 목록',url:'/router/regions/'+province+'/'})),
  ],[mainCrumb,routerCrumb],'전국 도시 및 읍면동 라우터렌탈 안내. CNR-5G500의 3일·15일·월 요금, 사양과 설치 준비사항을 지역별로 확인하세요.'));
  // 완성된 전체 경로를 검증한 후 기록하며 기존 디렉터리를 삭제하지 않는다.
  for (const {file,html} of outputs.values()) writeIfChanged(file,html);
  for (const link of connections) addCopierLink(link.file,link.label,link.fromPath,link.urlPath);
  const homeFile = path.join(ROOT,'index.html');
  const home = fs.readFileSync(homeFile,'utf8');
  const cleanHome = home.replace(/<!-- ROUTER-LIST:START -->[\s\S]*?<!-- ROUTER-LIST:END -->\r?\n\r?\n/g,'');
  if (!cleanHome.includes('  <div class="faq-wrap">')) throw new Error('메인 라우터 목록 연결 위치 없음');
  const homeLink = '<!-- ROUTER-LIST:START -->\n  <section><h2 class="section-title">전국 라우터렌탈 지역 안내</h2><div class="list"><a href="router/index.html">도시 및 읍·면·동별 5G 라우터렌탈 요금·사양 보기</a></div></section>\n<!-- ROUTER-LIST:END -->\n\n';
  writeIfChanged(homeFile,cleanHome.replace('  <div class="faq-wrap">',homeLink+'  <div class="faq-wrap">'));
  const sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+
    [...outputs.keys()].map(url=>'<url><loc>'+esc(encodeUrl(SITE_URL+url))+'</loc></url>').join('\n')+'\n</urlset>\n';
  writeIfChanged(path.join(ROOT,'sitemap-router.xml'),sitemap);
  const robotsFile = path.join(ROOT,'robots.txt'), robots = fs.readFileSync(robotsFile,'utf8');
  const sitemapLine = 'Sitemap: '+SITE_URL+'/sitemap-router.xml';
  if (!robots.includes(sitemapLine)) writeIfChanged(robotsFile,robots.trimEnd()+'\n'+sitemapLine+'\n');
  const report = {cityPages:DATA.length,emdPages:rows.length,districtPages:districts.size,provinceLists:provinces.size+cityProvinces.size,topLists:2,totalPages:outputs.size,sitemapUrls:outputs.size};
  console.log(JSON.stringify(report,null,2));
  return report;
}

function writeIfChanged(file,content) {
  if (fs.existsSync(file) && fs.readFileSync(file,'utf8')===content) return;
  fs.mkdirSync(path.dirname(file),{recursive:true});
  fs.writeFileSync(file,Buffer.from(content,'utf8'));
}

module.exports = { buildRouter };
if (require.main === module) buildRouter();
