import csv, io, base64, os, re, random, openpyxl
from urllib.parse import quote

ROOT = 'C:/Users/pc/Downloads/3333'

# 배너는 page_template.html / province_hub_template.html 내 JS가 런타임에 랜덤 렌더링함 (하나렌탈/노란우산렌탈 4종)

# 이 사이트(지역별 페이지 모음) 자체의 도메인 — 도메인 정해지면 이 값만 바꾸면 됨
SITE_URL = 'https://hana-yurental.netlify.app'

# 2. 업체 시트 데이터 로드
with open(f'{ROOT}/sheet.csv', 'rb') as f:
    sheet_rows = list(csv.reader(io.StringIO(f.read().decode('utf-8'))))[1:]

dealers = []
for row in sheet_rows:
    jimyeong = row[0].strip()
    sangho = row[2].strip()
    if jimyeong and sangho:
        dealers.append({'jimyeong': jimyeong, 'sangho': sangho})

# 3. 엑셀 카테고리 로드
EXCEL_PATH = 'C:/Users/pc/Downloads/상품등록/전국_카테고리목록_렌탈 임대 대여.xlsx'
wb = openpyxl.load_workbook(EXCEL_PATH, read_only=True)
excel_rows = []
for sheetname in wb.sheetnames:
    if not sheetname:
        continue
    ws = wb[sheetname]
    for r in ws.iter_rows(values_only=True):
        if r[0] == 'No' or r[0] is None:
            continue
        excel_rows.append({'sheet': sheetname, 'region': r[1], 'product': r[2], 'category': r[3]})

print('엑셀 행 수:', len(excel_rows))
print('업체 수:', len(dealers))

# 4. 지역명 매칭 함수
def find_dealers(region, sheet_province, limit=5):
    matches = []
    for d in dealers:
        if region in d['jimyeong'] or d['jimyeong'] in region:
            matches.append(d)
    if not matches:
        # 광역 단위(도/시) 이름으로 재시도
        for d in dealers:
            if sheet_province[:2] in d['jimyeong']:
                matches.append(d)
    # 중복 제거
    seen = set()
    uniq = []
    for m in matches:
        key = (m['jimyeong'], m['sangho'])
        if key not in seen:
            seen.add(key)
            uniq.append(m)
    return uniq[:limit]

# 상호별 상담 문의 링크 매핑
CONSULT_URL_MAP = [
    ('노란우산렌탈', 'https://yurental.com/'),
]
DEFAULT_CONSULT_URL = 'http://hanarental.net/'

PHONE_MAP = {
    'http://hanarental.net/': '1600-3165',
    'https://yurental.com/': '1833-4839',
}

def get_consult_url(sangho):
    for keyword, url in CONSULT_URL_MAP:
        if keyword in sangho:
            return url
    return DEFAULT_CONSULT_URL

# 실제 업체 사진 풀 (업체별로 다르게 배정)
PRINTER_IMG_POOL = [
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
]

def assign_imgs_for_page(seed_str, count):
    rng = random.Random(sum(ord(c) for c in seed_str))
    pool = PRINTER_IMG_POOL[:]
    rng.shuffle(pool)
    return [pool[i % len(pool)] for i in range(count)]

# 임의 좌표/주소 생성용 기본값 (지역명 기반 안내 문구만 사용, 정밀주소는 추정값 표기)
def make_card(d, region, img_url):
    consult_url = get_consult_url(d['sangho'])
    phone = PHONE_MAP.get(consult_url, '1600-3165')
    return f'''  <div class="card">
    <div class="card-thumb"><img src="{img_url}" alt="{d['sangho']}" /></div>
    <div class="card-body">
      <div class="card-name">{d['sangho']} - {d['jimyeong']}</div>
      <span class="card-badge">복합기렌탈</span>
      <div class="card-info"><span>📍 서비스 지역</span> {d['jimyeong']} 인근</div>
      <div class="card-info"><span>📞 상담</span> 무료 견적 상담 가능</div>
      <div class="card-links">
        <a class="map-btn naver" href="https://map.naver.com/v5/search/{d['jimyeong']} 복합기렌탈" target="_blank" rel="noopener">네이버 지도</a>
        <a class="map-btn google" href="https://www.google.com/maps/search/복합기렌탈+{d['jimyeong']}" target="_blank" rel="noopener">구글 지도</a>
        <a class="map-btn consult" href="{consult_url}" target="_blank" rel="noopener">홈페이지</a>
        <a class="map-btn phone" href="tel:{phone}">전화문의</a>
      </div>
    </div>
  </div>'''

def slugify(region, product):
    s = f'{region}-{product}'
    s = re.sub(r'\s+', '-', s)
    return s

with open(f'{ROOT}/page_template.html', 'r', encoding='utf-8') as f:
    TEMPLATE = f.read()

with open(f'{ROOT}/province_hub_template.html', 'r', encoding='utf-8') as f:
    HUB_TEMPLATE = f.read()

# 질문형 제목/부제 템플릿 풀 (행마다 순환 적용 → 중복 콘텐츠 방지)
TITLE_TEMPLATES = [
    '{category} 상담 전 확인 사항은 무엇인가요?',
    '{category} 후회 없이 고르려면 어디부터 봐야 하나요?',
    '{category} 견적 비교, 어디서 한눈에 볼 수 있나요?',
    '{category} 잘하는 곳은 어떻게 찾나요?',
    '{category} 가격 비교 전 꼭 봐야 할 곳은 어디인가요?',
    '{region}에서 {product} 알아본다면 어디부터 확인해야 하나요?',
    '{category} 상담 전 미리 확인하면 좋은 곳이 있을까요?',
]

SUBTITLE_TEMPLATES = [
    '{region} 인근 {product} 관련 업체들의 위치와 지도를 한 번에 비교해 볼 수 있습니다.',
    '{region} 지역 {product} 업체의 위치와 연락처를 확인해 보세요.',
    '{region} 인근에서 {product} 가능한 곳을 지도로 빠르게 찾아보세요.',
    '{region} 인근 {product} 업체 정보를 모아 한 번에 비교할 수 있습니다.',
    '{region}에서 {product}이 필요하다면, 아래 업체 목록을 참고하세요.',
]

# FAQ 풀 20개 (페이지마다 5개씩 랜덤 추출 → 중복 콘텐츠 방지)
FAQ_POOL = [
    ('{product} 비용 상담 전 꼭 확인해야 할 것은 무엇인가요?',
     '상담 전에 아래 4가지를 먼저 확인하면 더 정확한 견적을 받을 수 있습니다.<br><br>① <strong>월 예상 인쇄량</strong> (A4 기준 매수)<br>② <strong>흑백/컬러, A4/A3 등 필요 기종</strong><br>③ <strong>희망 계약 기간</strong> (24~60개월)<br>④ <strong>설치 장소 및 사업장 형태</strong><br><br>위 정보를 미리 준비하면 {region} 인근 업체 위치·지도를 비교해 가장 빠르게 설치 가능한 곳을 선택할 수 있습니다.'),
    ('{product} 계약 기간은 얼마나 되나요?',
     '일반적으로 <strong>24~60개월(2~5년)</strong> 단위로 계약하며, 가장 많이 선택하는 기간은 <strong>36개월(3년)</strong>입니다. 단기(1~3개월) 임시 이용도 가능합니다.'),
    ('{region}에서 월 비용은 얼마나 되나요?',
     '36개월 약정 기준 대략적인 월 비용입니다.<br><br>· A4 흑백 → <strong>월 3만원대~</strong><br>· A4 컬러 → <strong>월 5~7만원대</strong><br>· A3 흑백 → <strong>월 5~10만원대</strong><br>· A3 컬러 → <strong>월 6~15만원대</strong><br><br>토너·드럼 소모품과 무상 A/S가 포함된 금액입니다.'),
    ('고장나면 {region}에서도 바로 출장이 되나요?',
     '네, 지역 담당자가 배정되어 <strong>당일~익일 무상 출장</strong>이 가능합니다. 부품 교체도 무상이며, 수리 불가 시 동급 기종으로 교체해 드립니다. (사용자 과실 파손은 별도 비용)'),
    ('{region} 인근 다른 업체와 비교해 보고 싶어요',
     '위 목록의 <strong>네이버 지도·구글 지도 버튼</strong>을 눌러 실제 위치를 확인하고, 거리·접근성을 비교한 뒤 홈페이지·전화문의 버튼으로 견적을 요청하실 수 있습니다.'),
    ('{product}이 구매보다 유리한가요?',
     '<strong>월 인쇄량 2,000매 이상</strong>이라면 렌탈·임대가 유리합니다. 초기 구매비용 없이 소모품과 A/S가 포함되어 관리 부담이 적고, 비용을 매월 처리해 절세 효과도 있습니다.'),
    ('토너(소모품)는 누가 제공하나요?',
     '대부분의 계약에는 <strong>토너·드럼 등 소모품이 무상 포함</strong>됩니다. 토너가 부족하면 연락 시 무상 발송 또는 기사가 방문해 교체해 드립니다. 단, 기본 매수를 초과하면 추가 요금이 발생할 수 있습니다.'),
    ('미사용 매수(기본 매수)는 어떻게 되나요?',
     '업체에 따라 <strong>미사용 매수를 다음 달로 이월</strong>해주는 곳이 많습니다. 이달 사용량이 적어도 손해 보지 않도록, 계약 전 이월 정책을 꼭 확인하세요.'),
    ('계약 중 중도 해지하면 위약금이 발생하나요?',
     '약정 기간 내 중도 해지 시 위약금이 발생할 수 있습니다. 다만 폐업·사업장 이전(증빙서류 필요)이나 기기 불량 등의 사유는 위약금 없이 해지가 가능한 경우가 많으니 계약서를 꼭 확인하세요.'),
    ('{region}은 전국 서비스망에 포함되나요?',
     '네, {region}을 포함한 전국 대부분 지역에서 설치와 A/S가 가능합니다. 일부 도서산간 지역은 출장비가 발생할 수 있어 상담 시 사전 확인을 권장합니다.'),
    ('기존 기기에 저장된 데이터는 안전한가요?',
     '반납 전 담당 기사가 내부 저장 장치의 데이터를 완전 삭제 처리합니다. 중요한 문서·스캔 데이터는 반납 전 별도 백업해두시기 바랍니다.'),
    ('흑백과 컬러 중 어떤 것을 선택해야 하나요?',
     '일반 문서·계약서 위주라면 <strong>흑백</strong>이 경제적이며 컬러 대비 월 비용이 30~50% 저렴합니다. 카탈로그·발표자료·사진 출력이 잦다면 <strong>컬러</strong>를 추천합니다.'),
    ('계약 중 기종을 더 좋은 모델로 바꿀 수 있나요?',
     '계약 갱신 시점에 최신 기종으로 무상 교체가 가능합니다. 계약 기간 중이라도 업무량이 늘었다면 담당자와 업그레이드 조건을 협의할 수 있습니다.'),
    ('{region}에서 {product} 견적은 무료인가요?',
     '네, 대부분의 업체가 전화·온라인 상담을 통한 견적 산출을 무료로 제공합니다. 정확한 견적을 위해 월 예상 인쇄량과 필요 기종을 미리 정리해두면 좋습니다.'),
    ('단기로도 {product}이 가능한가요?',
     '행사·임시 사무실 등 짧은 기간이 필요한 경우 1~3개월 단기 이용도 가능합니다. 다만 단기 이용은 월 비용이 일반 약정보다 다소 높게 책정되는 경우가 많습니다.'),
    ('설치까지 얼마나 걸리나요?',
     '지역과 재고 상황에 따라 다르지만, 통상 상담 후 <strong>2~5일 이내</strong> 설치가 가능합니다. {region} 인근 업체는 거리가 가까워 더 빠르게 진행될 수 있습니다.'),
    ('인터넷·네트워크 연결도 같이 설치해주나요?',
     '대부분의 업체가 유선 네트워크 연결까지 함께 지원합니다. 무선(Wi-Fi) 연결이나 별도 랜선 공사가 필요한 경우 사전에 상담 시 요청하시면 안내받을 수 있습니다.'),
    ('보증금이 있나요?',
     '업체와 계약 조건에 따라 보증금이 있을 수도, 없을 수도 있습니다. 보증금이 있는 경우 계약 종료 후 기기 반납과 정산이 완료되면 환불됩니다.'),
    ('여러 대를 한 번에 계약할 수 있나요?',
     '네, 사업장 규모에 따라 여러 대를 동시에 계약하면 대수별 할인 혜택을 받을 수 있는 경우가 많습니다. 정확한 할인율은 업체 상담을 통해 확인하세요.'),
    ('{region} 업체와 직접 통화하고 싶어요',
     '위 카드의 <strong>전화문의 버튼</strong>을 누르면 바로 전화 연결이 가능합니다. 통화 전 원하는 기종·예산·설치 일정을 미리 정리해두면 상담이 더 빠르게 진행됩니다.'),
]

def build_faq_html(region, product, seed):
    rnd = random.Random(seed)
    picked = rnd.sample(FAQ_POOL, 5)
    items = []
    for q_tmpl, a_tmpl in picked:
        q = q_tmpl.format(region=region, product=product)
        a = a_tmpl.format(region=region, product=product)
        items.append(f'    <div class="faq-item">\n      <div class="faq-q">{q}</div>\n      <div class="faq-a">{a}</div>\n    </div>')
    return '\n\n'.join(items)

# 5. 샘플 3개 선택 (다양한 시도/상품유형)
SAMPLE_COUNT = 3
samples = []
used_sheets = set()
for row in excel_rows:
    if row['product'] == '복합기렌탈' and row['sheet'] not in used_sheets:
        samples.append(row)
        used_sheets.add(row['sheet'])
    if len(samples) >= SAMPLE_COUNT:
        break

print('샘플 수:', len(samples))
for s in samples:
    print(s)

os.makedirs(f'{ROOT}/pages', exist_ok=True)

sitemap_urls = []
province_links = {}  # province -> [(slug, region, product, category)]

for idx, row in enumerate(samples):
    region = row['region']
    product = row['product']
    province = row['sheet']
    category = row['category']  # 엑셀 카테고리명 값 (예: "서울 종로구복합기렌탈 임대/대여")

    title_tmpl = TITLE_TEMPLATES[idx % len(TITLE_TEMPLATES)]
    subtitle_tmpl = SUBTITLE_TEMPLATES[idx % len(SUBTITLE_TEMPLATES)]

    title = title_tmpl.format(category=category, region=region, product=product)
    subtitle = subtitle_tmpl.format(category=category, region=region, product=product)
    meta_title = f'{title} | 하나렌탈'
    meta_desc = f'{category} 비용 상담 전 꼭 확인하세요. {subtitle}'
    keywords = f'{category},{product},{region}{product},복합기렌탈,복합기임대,하나렌탈'

    matched = find_dealers(region, province)
    if not matched:
        matched = dealers[:5]

    imgs = assign_imgs_for_page(f'{region}-{product}', len(matched))
    cards_html = '\n\n'.join(make_card(d, region, imgs[i]) for i, d in enumerate(matched))
    faq_html = build_faq_html(region, product, seed=f'{region}-{product}-{idx}')

    slug = slugify(region, product)
    canonical = f'{SITE_URL}/pages/{province}/{slug}/'

    page_html = (TEMPLATE
        .replace('{{TITLE}}', title)
        .replace('{{SUBTITLE}}', subtitle)
        .replace('{{META_TITLE}}', meta_title)
        .replace('{{META_DESC}}', meta_desc)
        .replace('{{KEYWORDS}}', keywords)
        .replace('{{CANONICAL}}', canonical)
        .replace('{{REGION}}', region)
        .replace('{{PRODUCT}}', product)
        .replace('{{PROVINCE}}', province)
        .replace('{{CARDS}}', cards_html)
        .replace('{{FAQ}}', faq_html)
    )

    page_dir = f'{ROOT}/pages/{province}/{slug}'
    os.makedirs(page_dir, exist_ok=True)
    with open(f'{page_dir}/index.html', 'w', encoding='utf-8') as f:
        f.write(page_html)

    sitemap_urls.append(f'{SITE_URL}/pages/{quote(province)}/{quote(slug)}/')
    province_links.setdefault(province, []).append({'slug': slug, 'region': region, 'product': product, 'category': category})

# 6. 시/도 허브 페이지 생성 (province별 목록)
top_links = []
for province, items in province_links.items():
    link_rows = '\n'.join(
        f'    <a href="{it["slug"]}/index.html">{it["category"]}</a>' for it in items
    )
    hub_html = (HUB_TEMPLATE
        .replace('{{PROVINCE}}', province)
        .replace('{{CANONICAL}}', f'{SITE_URL}/pages/{province}/')
        .replace('{{LINKS}}', link_rows)
    )
    hub_dir = f'{ROOT}/pages/{province}'
    os.makedirs(hub_dir, exist_ok=True)
    with open(f'{hub_dir}/index.html', 'w', encoding='utf-8') as f:
        f.write(hub_html)
    sitemap_urls.append(f'{SITE_URL}/pages/{quote(province)}/')
    top_links.append(province)

# 7. pages/index.html (시/도 전체 허브)
province_list_html = '\n'.join(f'    <a href="{p}/index.html">{p} 복합기렌탈 지역 목록</a>' for p in top_links)
pages_index_html = (HUB_TEMPLATE
    .replace('{{PROVINCE}}', '전국')
    .replace('{{CANONICAL}}', f'{SITE_URL}/pages/')
    .replace('{{LINKS}}', province_list_html)
)
with open(f'{ROOT}/pages/index.html', 'w', encoding='utf-8') as f:
    f.write(pages_index_html)
sitemap_urls.append(f'{SITE_URL}/pages/')

# sitemap 샘플 생성
sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
for u in sitemap_urls:
    sitemap += f'  <url><loc>{u}</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>\n'
sitemap += '</urlset>\n'
with open(f'{ROOT}/sitemap_sample.xml', 'w', encoding='utf-8') as f:
    f.write(sitemap)

print('완료. 생성된 페이지:', len(samples))
for u in sitemap_urls:
    print(u)
