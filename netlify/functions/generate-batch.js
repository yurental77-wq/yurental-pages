const fs = require('fs');
const path = require('path');

const DEFAULT_BATCH_SIZE = 50;
const MAX_BATCH_SIZE = 300; // GitHub API/함수 실행시간 한도를 고려한 1회 최대치
const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, 'data/data_rows.json'), 'utf8'));
const PAGE_TEMPLATE = fs.readFileSync(path.join(__dirname, 'templates/page_template.html'), 'utf8');
const HUB_TEMPLATE = fs.readFileSync(path.join(__dirname, 'templates/province_hub_template.html'), 'utf8');

// 배너는 page_template.html 내 JS가 런타임에 랜덤 렌더링함 (하나렌탈/노란우산렌탈 4종)
// 이 사이트(지역별 페이지 모음) 자체의 도메인 — 도메인 정해지면 Netlify 환경변수 SITE_URL에 등록
const SITE_URL = process.env.SITE_URL || 'https://hana-yurental.netlify.app';

const CONSULT_URL_MAP = [['노란우산렌탈', 'https://yurental.com/']];
const DEFAULT_CONSULT_URL = 'http://hanarental.net/';
const PHONE_MAP = {
  'http://hanarental.net/': '1600-3165',
  'https://yurental.com/': '1833-4839',
};

const TITLE_TEMPLATES = [
  '{category} 상담 전 확인 사항은 무엇인가요?',
  '{category} 후회 없이 고르려면 어디부터 봐야 하나요?',
  '{category} 견적 비교, 어디서 한눈에 볼 수 있나요?',
  '{category} 잘하는 곳은 어떻게 찾나요?',
  '{category} 가격 비교 전 꼭 봐야 할 곳은 어디인가요?',
  '{region}에서 {product} 알아본다면 어디부터 확인해야 하나요?',
  '{category} 상담 전 미리 확인하면 좋은 곳이 있을까요?',
];

const SUBTITLE_TEMPLATES = [
  '{region} 인근 {product} 관련 업체들의 위치와 지도를 한 번에 비교해 볼 수 있습니다.',
  '{region} 지역 {product} 업체의 위치와 연락처를 확인해 보세요.',
  '{region} 인근에서 {product} 가능한 곳을 지도로 빠르게 찾아보세요.',
  '{region} 인근 {product} 업체 정보를 모아 한 번에 비교할 수 있습니다.',
  '{region}에서 {product}이 필요하다면, 아래 업체 목록을 참고하세요.',
];

const FAQ_POOL = [
  ['{product} 비용 상담 전 꼭 확인해야 할 것은 무엇인가요?', '상담 전에 아래 4가지를 먼저 확인하면 더 정확한 견적을 받을 수 있습니다.<br><br>① <strong>월 예상 인쇄량</strong> (A4 기준 매수)<br>② <strong>흑백/컬러, A4/A3 등 필요 기종</strong><br>③ <strong>희망 계약 기간</strong> (24~60개월)<br>④ <strong>설치 장소 및 사업장 형태</strong><br><br>위 정보를 미리 준비하면 {region} 인근 업체 위치·지도를 비교해 가장 빠르게 설치 가능한 곳을 선택할 수 있습니다.'],
  ['{product} 계약 기간은 얼마나 되나요?', '일반적으로 <strong>24~60개월(2~5년)</strong> 단위로 계약하며, 가장 많이 선택하는 기간은 <strong>36개월(3년)</strong>입니다. 단기(1~3개월) 임시 이용도 가능합니다.'],
  ['{region}에서 월 비용은 얼마나 되나요?', '36개월 약정 기준 대략적인 월 비용입니다.<br><br>· A4 흑백 → <strong>월 3만원대~</strong><br>· A4 컬러 → <strong>월 5~7만원대</strong><br>· A3 흑백 → <strong>월 5~10만원대</strong><br>· A3 컬러 → <strong>월 6~15만원대</strong><br><br>토너·드럼 소모품과 무상 A/S가 포함된 금액입니다.'],
  ['고장나면 {region}에서도 바로 출장이 되나요?', '네, 지역 담당자가 배정되어 <strong>당일~익일 무상 출장</strong>이 가능합니다. 부품 교체도 무상이며, 수리 불가 시 동급 기종으로 교체해 드립니다. (사용자 과실 파손은 별도 비용)'],
  ['{region} 인근 다른 업체와 비교해 보고 싶어요', '위 목록의 <strong>네이버 지도·구글 지도 버튼</strong>을 눌러 실제 위치를 확인하고, 거리·접근성을 비교한 뒤 홈페이지·전화문의 버튼으로 견적을 요청하실 수 있습니다.'],
  ['{product}이 구매보다 유리한가요?', '<strong>월 인쇄량 2,000매 이상</strong>이라면 렌탈·임대가 유리합니다. 초기 구매비용 없이 소모품과 A/S가 포함되어 관리 부담이 적고, 비용을 매월 처리해 절세 효과도 있습니다.'],
  ['토너(소모품)는 누가 제공하나요?', '대부분의 계약에는 <strong>토너·드럼 등 소모품이 무상 포함</strong>됩니다. 토너가 부족하면 연락 시 무상 발송 또는 기사가 방문해 교체해 드립니다. 단, 기본 매수를 초과하면 추가 요금이 발생할 수 있습니다.'],
  ['미사용 매수(기본 매수)는 어떻게 되나요?', '업체에 따라 <strong>미사용 매수를 다음 달로 이월</strong>해주는 곳이 많습니다. 이달 사용량이 적어도 손해 보지 않도록, 계약 전 이월 정책을 꼭 확인하세요.'],
  ['계약 중 중도 해지하면 위약금이 발생하나요?', '약정 기간 내 중도 해지 시 위약금이 발생할 수 있습니다. 다만 폐업·사업장 이전(증빙서류 필요)이나 기기 불량 등의 사유는 위약금 없이 해지가 가능한 경우가 많으니 계약서를 꼭 확인하세요.'],
  ['{region}은 전국 서비스망에 포함되나요?', '네, {region}을 포함한 전국 대부분 지역에서 설치와 A/S가 가능합니다. 일부 도서산간 지역은 출장비가 발생할 수 있어 상담 시 사전 확인을 권장합니다.'],
  ['기존 기기에 저장된 데이터는 안전한가요?', '반납 전 담당 기사가 내부 저장 장치의 데이터를 완전 삭제 처리합니다. 중요한 문서·스캔 데이터는 반납 전 별도 백업해두시기 바랍니다.'],
  ['흑백과 컬러 중 어떤 것을 선택해야 하나요?', '일반 문서·계약서 위주라면 <strong>흑백</strong>이 경제적이며 컬러 대비 월 비용이 30~50% 저렴합니다. 카탈로그·발표자료·사진 출력이 잦다면 <strong>컬러</strong>를 추천합니다.'],
  ['계약 중 기종을 더 좋은 모델로 바꿀 수 있나요?', '계약 갱신 시점에 최신 기종으로 무상 교체가 가능합니다. 계약 기간 중이라도 업무량이 늘었다면 담당자와 업그레이드 조건을 협의할 수 있습니다.'],
  ['{region}에서 {product} 견적은 무료인가요?', '네, 대부분의 업체가 전화·온라인 상담을 통한 견적 산출을 무료로 제공합니다. 정확한 견적을 위해 월 예상 인쇄량과 필요 기종을 미리 정리해두면 좋습니다.'],
  ['단기로도 {product}이 가능한가요?', '행사·임시 사무실 등 짧은 기간이 필요한 경우 1~3개월 단기 이용도 가능합니다. 다만 단기 이용은 월 비용이 일반 약정보다 다소 높게 책정되는 경우가 많습니다.'],
  ['설치까지 얼마나 걸리나요?', '지역과 재고 상황에 따라 다르지만, 통상 상담 후 <strong>2~5일 이내</strong> 설치가 가능합니다. {region} 인근 업체는 거리가 가까워 더 빠르게 진행될 수 있습니다.'],
  ['인터넷·네트워크 연결도 같이 설치해주나요?', '대부분의 업체가 유선 네트워크 연결까지 함께 지원합니다. 무선(Wi-Fi) 연결이나 별도 랜선 공사가 필요한 경우 사전에 상담 시 요청하시면 안내받을 수 있습니다.'],
  ['보증금이 있나요?', '업체와 계약 조건에 따라 보증금이 있을 수도, 없을 수도 있습니다. 보증금이 있는 경우 계약 종료 후 기기 반납과 정산이 완료되면 환불됩니다.'],
  ['여러 대를 한 번에 계약할 수 있나요?', '네, 사업장 규모에 따라 여러 대를 동시에 계약하면 대수별 할인 혜택을 받을 수 있는 경우가 많습니다. 정확한 할인율은 업체 상담을 통해 확인하세요.'],
  ['{region} 업체와 직접 통화하고 싶어요', '위 카드의 <strong>전화문의 버튼</strong>을 누르면 바로 전화 연결이 가능합니다. 통화 전 원하는 기종·예산·설치 일정을 미리 정리해두면 상담이 더 빠르게 진행됩니다.'],
];

function fmt(tmpl, vars) {
  return tmpl.replace(/\{(\w+)\}/g, (_, k) => vars[k] != null ? vars[k] : '');
}

function seededRandom(seedStr) {
  let h = 0;
  for (let i = 0; i < seedStr.length; i++) h = (Math.imul(31, h) + seedStr.charCodeAt(i)) | 0;
  return function () {
    h = (Math.imul(h, 1664525) + 1013904223) | 0;
    return ((h >>> 0) / 4294967296);
  };
}

function sampleFAQ(region, product, seedStr) {
  const rnd = seededRandom(seedStr);
  const pool = FAQ_POOL.slice();
  for (let i = pool.length - 1; i > pool.length - 6; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  const picked = pool.slice(pool.length - 5);
  return picked.map(([q, a]) => {
    const qq = fmt(q, { region, product });
    const aa = fmt(a, { region, product });
    return `    <div class="faq-item">\n      <div class="faq-q">${qq}</div>\n      <div class="faq-a">${aa}</div>\n    </div>`;
  }).join('\n\n');
}

function getConsultUrl(sangho) {
  for (const [kw, url] of CONSULT_URL_MAP) if (sangho.includes(kw)) return url;
  return DEFAULT_CONSULT_URL;
}

const PRINTER_IMG_POOL = [
  'https://gi.esmplus.com/khon21/광고배너/25_2.png',
  'https://gi.esmplus.com/khon21/광고배너/24_3.png',
  'https://gi.esmplus.com/khon21/광고배너/24_2.png',
  'https://gi.esmplus.com/khon21/광고배너/23_3.png',
  'https://gi.esmplus.com/khon21/광고배너/41_6.png',
  'https://gi.esmplus.com/khon21/광고배너/40_4.png',
  'https://gi.esmplus.com/khon21/광고배너/39_3.png',
  'https://gi.esmplus.com/khon21/광고배너/38_2.png',
  'https://gi.esmplus.com/khon21/광고배너/37_3.png',
  'https://gi.esmplus.com/khon21/광고배너/34_5.png',
  'https://gi.esmplus.com/khon21/광고배너/27_2.png',
  'https://gi.esmplus.com/khon21/광고배너/26_5.png',
];

function assignImgsForPage(seedStr, count) {
  let h = 0;
  for (let i = 0; i < seedStr.length; i++) h += seedStr.charCodeAt(i);
  const pool = PRINTER_IMG_POOL.slice();
  // seeded Fisher-Yates shuffle
  for (let i = pool.length - 1; i > 0; i--) {
    h = (Math.imul(h, 1664525) + 1013904223) >>> 0;
    const j = h % (i + 1);
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  return Array.from({ length: count }, (_, i) => pool[i % pool.length]);
}

function makeCard(d, imgUrl, productName) {
  const consultUrl = getConsultUrl(d.sangho);
  const phone = PHONE_MAP[consultUrl] || '1600-3165';
  return `  <div class="card">
    <div class="card-thumb"><img src="${imgUrl}" alt="${d.sangho}" /></div>
    <div class="card-body">
      <div class="card-name">${d.sangho} - ${d.jimyeong}</div>
      <span class="card-badge">${productName}</span>
      <div class="card-info"><span>📍 서비스 지역</span> ${d.jimyeong} 인근</div>
      <div class="card-info"><span>📞 상담</span> 무료 견적 상담 가능</div>
      <div class="card-links">
        <a class="map-btn naver" href="https://map.naver.com/v5/search/${d.jimyeong} ${productName}" target="_blank" rel="noopener">네이버 지도</a>
        <a class="map-btn google" href="https://www.google.com/maps/search/${productName}+${d.jimyeong}" target="_blank" rel="noopener">구글 지도</a>
        <a class="map-btn consult" href="${consultUrl}" target="_blank" rel="noopener">홈페이지</a>
        <a class="map-btn phone" href="tel:${phone}">전화문의</a>
      </div>
    </div>
  </div>`;
}

function renderPage(item, globalIdx, productName) {
  const { region, province, slug, dealers } = item;
  const product = productName || item.product;
  const category = `${region} ${product}`;
  const titleTmpl = TITLE_TEMPLATES[globalIdx % TITLE_TEMPLATES.length];
  const subtitleTmpl = SUBTITLE_TEMPLATES[globalIdx % SUBTITLE_TEMPLATES.length];
  const title = fmt(titleTmpl, { category, region, product });
  const subtitle = fmt(subtitleTmpl, { category, region, product });
  const metaTitle = `${title} | 하나렌탈`;
  const metaDesc = `${category} 비용 상담 전 꼭 확인하세요. ${subtitle}`;
  const keywords = `${category},${product},${region}${product},${product},렌탈,하나렌탈`;
  const canonical = `${SITE_URL}/pages/${province}/${slug}/`;
  const imgs = assignImgsForPage(`${region}-${product}`, dealers.length);
  const cardsHtml = dealers.map((d, i) => makeCard(d, imgs[i], product)).join('\n\n');
  const faqHtml = sampleFAQ(region, product, `${region}-${product}-${globalIdx}`);

  let html = PAGE_TEMPLATE;
  const reps = {
    '{{TITLE}}': title, '{{SUBTITLE}}': subtitle, '{{META_TITLE}}': metaTitle,
    '{{META_DESC}}': metaDesc, '{{KEYWORDS}}': keywords, '{{CANONICAL}}': canonical,
    '{{REGION}}': region, '{{PRODUCT}}': product, '{{PROVINCE}}': province,
    '{{CARDS}}': cardsHtml, '{{FAQ}}': faqHtml,
  };
  for (const [k, v] of Object.entries(reps)) html = html.split(k).join(v);
  return { path: `pages/${province}/${slug}/index.html`, content: html };
}

function renderProvinceHub(province, items) {
  const links = items.map(it => `    <a href="${it.slug}/index.html">${it.category}</a>`).join('\n');
  let html = HUB_TEMPLATE
    .split('{{PROVINCE}}').join(province)
    .split('{{CANONICAL}}').join(`${SITE_URL}/pages/${province}/`)
    .split('{{LINKS}}').join(links);
  return { path: `pages/${province}/index.html`, content: html };
}

function renderTopHub(provinces, productName) {
  const label = productName || '복합기렌탈';
  const links = provinces.map(p => `    <a href="${p}/index.html">${p} ${label} 지역 목록</a>`).join('\n');
  let html = HUB_TEMPLATE
    .split('{{PROVINCE}}').join('전국')
    .split('{{CANONICAL}}').join(`${SITE_URL}/pages/`)
    .split('{{LINKS}}').join(links);
  return { path: 'pages/index.html', content: html };
}

function encodeUrl(url) {
  // 프로토콜+도메인은 그대로, 경로 부분만 각 세그먼트를 인코딩
  const [base, ...pathParts] = url.split('/');
  // url이 https://domain/path/... 형태
  return url.split('/').map((seg, i) => i < 3 ? seg : encodeURIComponent(seg)).join('/');
}

function renderSitemap(publishedItems) {
  const urls = publishedItems.map(it => encodeUrl(`${SITE_URL}/pages/${it.province}/${it.slug}/`));
  const provinces = [...new Set(publishedItems.map(it => it.province))];
  for (const p of provinces) urls.push(encodeUrl(`${SITE_URL}/pages/${p}/`));
  urls.push(`${SITE_URL}/pages/`);
  const body = urls.map(u => `  <url><loc>${u}</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>`).join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</urlset>\n`;
}

// ---- GitHub API helpers ----
const PROGRESS_PATH = 'progress.json';

async function ghApi(pathPart, opts = {}) {
  const { GITHUB_TOKEN, GITHUB_REPO } = process.env;
  const res = await fetch(`https://api.github.com/repos/${GITHUB_REPO}${pathPart}`, {
    ...opts,
    headers: {
      Authorization: `Bearer ${GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) throw new Error(`GitHub API ${pathPart} failed: ${res.status} ${await res.text()}`);
  return res.json();
}

async function readProgress() {
  const branch = process.env.GITHUB_BRANCH || 'main';
  try {
    const file = await ghApi(`/contents/${PROGRESS_PATH}?ref=${branch}`);
    const json = Buffer.from(file.content, 'base64').toString('utf8');
    return JSON.parse(json);
  } catch (e) {
    if (e.message.includes('404')) return null;
    throw e;
  }
}

async function commitFiles(files, message) {
  const branch = process.env.GITHUB_BRANCH || 'main';
  const ref = await ghApi(`/git/ref/heads/${branch}`);
  const latestCommitSha = ref.object.sha;
  const latestCommit = await ghApi(`/git/commits/${latestCommitSha}`);
  const baseTreeSha = latestCommit.tree.sha;

  const blobs = await Promise.all(files.map(async f => {
    const blob = await ghApi('/git/blobs', {
      method: 'POST',
      body: JSON.stringify({ content: f.content, encoding: 'utf-8' }),
    });
    return { path: f.path, mode: '100644', type: 'blob', sha: blob.sha };
  }));

  const tree = await ghApi('/git/trees', {
    method: 'POST',
    body: JSON.stringify({ base_tree: baseTreeSha, tree: blobs }),
  });

  const commit = await ghApi('/git/commits', {
    method: 'POST',
    body: JSON.stringify({ message, tree: tree.sha, parents: [latestCommitSha] }),
  });

  await ghApi(`/git/refs/heads/${branch}`, {
    method: 'PATCH',
    body: JSON.stringify({ sha: commit.sha }),
  });
}

exports.handler = async function (event) {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: 'Method Not Allowed' };
  }

  const adminPassword = event.headers['x-admin-password'];
  if (!process.env.ADMIN_PASSWORD || adminPassword !== process.env.ADMIN_PASSWORD) {
    return { statusCode: 401, body: JSON.stringify({ error: '관리자 비밀번호가 올바르지 않습니다.' }) };
  }

  if (!process.env.GITHUB_TOKEN || !process.env.GITHUB_REPO) {
    return { statusCode: 500, body: JSON.stringify({ error: 'GITHUB_TOKEN 또는 GITHUB_REPO 환경변수가 설정되지 않았습니다.' }) };
  }

  let requestedCount = DEFAULT_BATCH_SIZE;
  let productName = '복합기렌탈';
  try {
    const body = event.body ? JSON.parse(event.body) : {};
    if (body.count) requestedCount = parseInt(body.count, 10);
    if (body.category && typeof body.category === 'string' && body.category.trim()) {
      productName = body.category.trim();
    }
  } catch (e) {
    // 잘못된 body면 기본값 사용
  }
  if (!Number.isFinite(requestedCount) || requestedCount < 1) requestedCount = DEFAULT_BATCH_SIZE;
  if (requestedCount > MAX_BATCH_SIZE) requestedCount = MAX_BATCH_SIZE;

  try {
    let state = await readProgress();

    if (!state) {
      const PRIORITY_PROVINCES = ['전라북도'];
      const shuffle = (arr) => {
        for (let i = arr.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [arr[i], arr[j]] = [arr[j], arr[i]];
        }
        return arr;
      };
      const allIdx = DATA.map((_, i) => i);
      const priorityIdx = allIdx.filter(i => PRIORITY_PROVINCES.includes(DATA[i].province));
      const restIdx = allIdx.filter(i => !PRIORITY_PROVINCES.includes(DATA[i].province));
      const order = shuffle(priorityIdx).concat(shuffle(restIdx));
      state = { order, nextIndex: 0, published: [], resetQueue: [] };
    }

    const resetQueue = state.resetQueue || [];
    const allDone = state.nextIndex >= state.order.length && resetQueue.length === 0;
    if (allDone) {
      return {
        statusCode: 200,
        body: JSON.stringify({ done: true, message: '전체 페이지가 모두 생성되었습니다.', total: state.order.length, published: state.published.length }),
      };
    }

    // resetQueue 우선 처리, 없으면 order에서 순서대로
    let batchItems;
    let newNextIndex = state.nextIndex;
    let newResetQueue;
    if (resetQueue.length > 0) {
      const toProcess = resetQueue.slice(0, requestedCount);
      batchItems = toProcess.map(i => DATA[i]);
      newResetQueue = resetQueue.slice(toProcess.length);
    } else {
      const batchIdxs = state.order.slice(state.nextIndex, state.nextIndex + requestedCount);
      batchItems = batchIdxs.map(i => DATA[i]);
      newNextIndex = state.nextIndex + batchItems.length;
      newResetQueue = [];
    }

    const filesToCommit = [];
    batchItems.forEach((item, k) => {
      const globalIdx = (resetQueue.length > 0 ? state.nextIndex : state.nextIndex) + k;
      const { path: p, content } = renderPage(item, globalIdx, productName);
      filesToCommit.push({ path: p, content });
    });

    const newPublished = state.published.concat(
      batchItems.map(it => ({ province: it.province, slug: it.slug, category: `${it.region} ${productName}` }))
    );

    const provinceGroups = {};
    for (const it of newPublished) {
      (provinceGroups[it.province] = provinceGroups[it.province] || []).push(it);
    }
    for (const [province, items] of Object.entries(provinceGroups)) {
      const { path: p, content } = renderProvinceHub(province, items);
      filesToCommit.push({ path: p, content });
    }

    // pages/ 디렉토리의 실제 province 폴더 전체를 읽어 합산 (수동 추가된 폴더 포함)
    let allProvinces = new Set(Object.keys(provinceGroups));
    try {
      const branch = process.env.GITHUB_BRANCH || 'main';
      const pagesTree = await ghApi(`/contents/pages?ref=${branch}`);
      if (Array.isArray(pagesTree)) {
        for (const entry of pagesTree) {
          if (entry.type === 'dir') allProvinces.add(entry.name);
        }
      }
    } catch (e) { /* pages/ 없으면 무시 */ }

    const topHub = renderTopHub([...allProvinces].sort(), productName);
    filesToCommit.push({ path: topHub.path, content: topHub.content });

    filesToCommit.push({ path: 'sitemap.xml', content: renderSitemap(newPublished) });

    const logEntry = {
      date: new Date().toISOString(),
      added: batchItems.length,
      total: newPublished.length,
    };
    const newState = {
      order: state.order,
      nextIndex: newNextIndex,
      resetQueue: newResetQueue,
      log: [...(state.log || []), logEntry],
      published: newPublished,
    };
    filesToCommit.push({ path: PROGRESS_PATH, content: JSON.stringify(newState) });

    await commitFiles(filesToCommit, `[skip ci] [자동생성] ${batchItems.length}개 페이지 추가 (총 ${newPublished.length}/${state.order.length})`);

    return {
      statusCode: 200,
      body: JSON.stringify({
        done: false,
        addedThisBatch: batchItems.length,
        totalPublished: newState.published.length,
        totalRows: newState.order.length,
      }),
    };
  } catch (err) {
    return { statusCode: 500, body: JSON.stringify({ error: err.message }) };
  }
};
