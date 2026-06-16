import csv, io, json, re, openpyxl

ROOT = 'C:/Users/pc/Downloads/3333'

with open(f'{ROOT}/sheet.csv', 'rb') as f:
    sheet_rows = list(csv.reader(io.StringIO(f.read().decode('utf-8'))))[1:]

dealers = []
for row in sheet_rows:
    jimyeong = row[0].strip()
    sangho = row[2].strip()
    if jimyeong and sangho:
        dealers.append({'jimyeong': jimyeong, 'sangho': sangho})

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

def find_dealers(region, sheet_province, limit=5):
    matches = []
    for d in dealers:
        if region in d['jimyeong'] or d['jimyeong'] in region:
            matches.append(d)
    if not matches:
        for d in dealers:
            if sheet_province[:2] in d['jimyeong']:
                matches.append(d)
    seen = set()
    uniq = []
    for m in matches:
        key = (m['jimyeong'], m['sangho'])
        if key not in seen:
            seen.add(key)
            uniq.append(m)
    return uniq[:limit] if uniq else dealers[:5]

def slugify(region, product):
    s = f'{region}-{product}'
    return re.sub(r'\s+', '-', s)

dataset = []
for row in excel_rows:
    region = row['region']
    product = row['product']
    province = row['sheet']
    category = row['category']
    matched = find_dealers(region, province)
    dataset.append({
        'province': province,
        'region': region,
        'product': product,
        'category': category,
        'slug': slugify(region, product),
        'dealers': matched,
    })

with open(f'{ROOT}/data_rows.json', 'w', encoding='utf-8') as f:
    json.dump(dataset, f, ensure_ascii=False)

print('총 행수:', len(dataset))
