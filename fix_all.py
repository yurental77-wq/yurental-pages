import os, re, random

ROOT = 'C:/Users/pc/Downloads/3333'
SITE_URL = 'https://hanarentalbj.kr'

# 1. pages/index.html 재생성 — 실제 존재하는 province 폴더 전체 반영
with open(ROOT + '/province_hub_template.html', 'r', encoding='utf-8') as f:
    hub_tmpl = f.read()

provinces = sorted([
    name for name in os.listdir(ROOT + '/pages')
    if os.path.isdir(os.path.join(ROOT, 'pages', name))
])
print('발견된 province:', provinces)

links = '\n'.join('    <a href="{}/index.html">{} 복합기렌탈 지역 목록</a>'.format(p, p) for p in provinces)
top_hub = hub_tmpl.replace('{{PROVINCE}}', '전국').replace('{{CANONICAL}}', SITE_URL + '/pages/').replace('{{LINKS}}', links)
with open(ROOT + '/pages/index.html', 'w', encoding='utf-8') as f:
    f.write(top_hub)
print('pages/index.html 재생성 완료')

# 2. 기존 발행 페이지들 — 한 페이지 내 사진 중복 없이 재배정
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

CARD_RE = re.compile(
    r'(<div class="card-thumb"[^>]*>.*?</div>)\s*'
    r'(<div class="card-body">\s*<div class="card-name">([^<]+) - ([^<]+)</div>)',
    re.DOTALL
)

count_files = 0
count_cards = 0

for root, dirs, files in os.walk(ROOT + '/pages'):
    for fn in files:
        if fn != 'index.html':
            continue
        fp = os.path.join(root, fn)
        with open(fp, 'r', encoding='utf-8') as f:
            content = f.read()
        if 'class="card-thumb"' not in content:
            continue

        matches = list(CARD_RE.finditer(content))
        if not matches:
            continue

        # 페이지별 시드로 풀 셔플 → 순서대로 배정 (한 페이지 내 중복 없음)
        seed_str = fp.replace('\\', '/').split('pages/')[-1]
        rng = random.Random(sum(ord(c) for c in seed_str))
        shuffled = PRINTER_IMG_POOL[:]
        rng.shuffle(shuffled)

        # 역순으로 치환해야 인덱스가 밀리지 않음
        result = content
        for i, m in enumerate(reversed(matches)):
            img_url = shuffled[i % len(shuffled)]
            sangho = m.group(3).strip()
            new_thumb = '<div class="card-thumb"><img src="{}" alt="{}" /></div>'.format(img_url, sangho)
            replacement = new_thumb + '\n    ' + m.group(2)
            result = result[:m.start()] + replacement + result[m.end():]

        with open(fp, 'w', encoding='utf-8') as f:
            f.write(result)
        count_files += 1
        count_cards += len(matches)

print('수정된 파일: {}개, 교체된 카드: {}개'.format(count_files, count_cards))
