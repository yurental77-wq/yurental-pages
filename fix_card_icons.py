import os, re

ROOT = 'C:/Users/pc/Downloads/3333'

THUMB_COLOR_POOL = ['#dce8ff', '#ffe8d6', '#e3f6e0', '#fde8ee', '#e6e0fb', '#fff3c4', '#dff7f4', '#ffe0e0']

PRINTER_ICON_SVG = '''<svg viewBox="0 0 64 64" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="8" width="36" height="14" rx="2" fill="#fff" stroke="#1a4fa0" stroke-width="2"/>
  <rect x="6" y="20" width="44" height="22" rx="3" fill="#1a4fa0"/>
  <rect x="14" y="34" width="28" height="20" rx="2" fill="#fff" stroke="#1a4fa0" stroke-width="2"/>
  <circle cx="42" cy="27" r="2.2" fill="#7fffb0"/>
  <rect x="12" y="25" width="12" height="3" rx="1.5" fill="#fff"/>
</svg>'''

def pick_color(jimyeong, sangho):
    s = jimyeong + sangho
    h = sum(ord(c) for c in s)
    return THUMB_COLOR_POOL[h % len(THUMB_COLOR_POOL)]

# 카드 블록 전체를 찾는 정규식: card-thumb(이미지 포함) ~ card-name(상호 - 지명) 까지
CARD_RE = re.compile(
    r'(<div class="card-thumb"[^>]*>.*?</div>)\s*'
    r'(<div class="card-body">\s*<div class="card-name">([^<]+) - ([^<]+)</div>)',
    re.DOTALL
)

def replace_card(m):
    body_start = m.group(2)
    sangho = m.group(3).strip()
    jimyeong = m.group(4).strip()
    color = pick_color(jimyeong, sangho)
    new_thumb = f'<div class="card-thumb" style="background:{color}; padding:18px;">{PRINTER_ICON_SVG}</div>'
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
        if '<div class="card-thumb">' not in content and 'class="card-thumb"' not in content:
            continue
        new_content, n = CARD_RE.subn(replace_card, content)
        if n > 0:
            with open(fp, 'w', encoding='utf-8') as f:
                f.write(new_content)
            count_files += 1
            count_cards += n

print('수정된 파일 수:', count_files)
print('교체된 카드 수:', count_cards)
