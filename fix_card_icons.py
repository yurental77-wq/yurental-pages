import os, re

ROOT = 'C:/Users/pc/Downloads/3333'

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

def pick_img(jimyeong, sangho):
    s = jimyeong + sangho
    h = sum(ord(c) for c in s)
    return PRINTER_IMG_POOL[h % len(PRINTER_IMG_POOL)]

# card-thumb 블록(SVG 아이콘 버전이든 img 버전이든) ~ card-name(상호 - 지명) 까지 매칭
CARD_RE = re.compile(
    r'(<div class="card-thumb"[^>]*>.*?</div>)\s*'
    r'(<div class="card-body">\s*<div class="card-name">([^<]+) - ([^<]+)</div>)',
    re.DOTALL
)

def replace_card(m):
    body_start = m.group(2)
    sangho = m.group(3).strip()
    jimyeong = m.group(4).strip()
    img_url = pick_img(jimyeong, sangho)
    new_thumb = f'<div class="card-thumb"><img src="{img_url}" alt="{sangho}" /></div>'
    return new_thumb + '\n    ' + body_start

count_files = 0
count_cards = 0

for root, dirs, files in os.walk(f'{ROOT}/pages'):
    for fn in files:
        if fn != 'index.html':
            continue
        fp = os.path.join(root, fn)
        with open(fp, 'r', encoding='utf-8') as f:
            content = f.read()
        if 'class="card-thumb"' not in content:
            continue
        new_content, n = CARD_RE.subn(replace_card, content)
        if n > 0:
            with open(fp, 'w', encoding='utf-8') as f:
                f.write(new_content)
            count_files += 1
            count_cards += n

print('수정된 파일 수:', count_files)
print('교체된 카드 수:', count_cards)
