import csv, io, base64

# 배너는 template.html 내 JS가 런타임에 랜덤 렌더링함 (하나렌탈/노란우산렌탈 4종)

cards_data = [
    {'j':'안산','s':'하나렌탈 경기중부지사','k':'복합기렌탈','jb':'경기도 안산시 단원구 원초로 24-1','dr':'경기도 안산시 단원구 광덕대로 52','c':'37.3219, 126.8308','img':'https://images.unsplash.com/photo-1612198188060-c7c2a3b66eae?w=220&q=70','nq':'안산 복합기렌탈','gq':'복합기렌탈+안산'},
    {'j':'태안군','s':'노란우산렌탈','k':'프린터임대','jb':'충청남도 태안군 태안읍 상옥리 210-5','dr':'충청남도 태안군 태안읍 동백로 45','c':'36.7454, 126.2981','img':'https://images.unsplash.com/photo-1497366754035-f200968a6e72?w=220&q=70','nq':'태안 복합기렌탈','gq':'복합기렌탈+태안'},
    {'j':'안산 단원구','s':'하나렌탈 경기중부지사','k':'복사기렌탈','jb':'경기도 안산시 단원구 신길동 752-3','dr':'경기도 안산시 단원구 화랑로 130','c':'37.3102, 126.8195','img':'https://images.unsplash.com/photo-1564069114551-7a949d6f5481?w=220&q=70','nq':'안산 단원구 복합기렌탈','gq':'복합기렌탈+안산+단원구'},
    {'j':'화성 동탄','s':'노란우산렌탈 화성동탄지사','k':'컬러복합기렌탈','jb':'경기도 화성시 동탄면 방교리 880-2','dr':'경기도 화성시 동탄대로 680','c':'37.2015, 127.0744','img':'https://images.unsplash.com/photo-1497366216548-37526070297c?w=220&q=70','nq':'화성 동탄 복합기렌탈','gq':'복합기렌탈+화성+동탄'},
    {'j':'창원','s':'하나렌탈 창원지사','k':'문서세단기렌탈','jb':'경상남도 창원시 성산구 중앙대로 85-1','dr':'경상남도 창원시 성산구 중앙대로 85','c':'35.2280, 128.6811','img':'https://images.unsplash.com/photo-1486325212027-8081e485255e?w=220&q=70','nq':'창원 복합기렌탈','gq':'복합기렌탈+창원'},
    {'j':'해남','s':'노란우산렌탈','k':'복합기렌탈','jb':'전라남도 해남군 해남읍 해리 305-2','dr':'전라남도 해남군 해남읍 해남로 28','c':'34.5734, 126.5990','img':'https://images.unsplash.com/photo-1542744173-8e7e53415bb0?w=220&q=70','nq':'해남 복합기렌탈','gq':'복합기렌탈+해남'},
    {'j':'전주 완산구','s':'하나렌탈','k':'복합기렌탈','jb':'전라북도 전주시 완산구 효자동 1가 210-4','dr':'전라북도 전주시 완산구 백제대로 555','c':'35.8214, 127.1089','img':'https://images.unsplash.com/photo-1581091226033-d5c48150dbaa?w=220&q=70','nq':'전주 완산구 복합기렌탈','gq':'복합기렌탈+전주+완산구'},
    {'j':'천안 서북구','s':'노란우산렌탈 세종지사','k':'복합기렌탈','jb':'충청남도 천안시 서북구 불당동 744-1','dr':'충청남도 천안시 서북구 불당대로 138','c':'36.8415, 127.1349','img':'https://images.unsplash.com/photo-1519389950473-47ba0277781c?w=220&q=70','nq':'천안 서북구 복합기렌탈','gq':'복합기렌탈+천안+서북구'},
    {'j':'양양','s':'명성시스템','k':'복합기렌탈','jb':'강원도 양양군 양양읍 군행리 112-3','dr':'강원도 양양군 양양읍 양양로 100','c':'38.0753, 128.6194','img':'https://images.unsplash.com/photo-1497366412874-3415097a27e7?w=220&q=70','nq':'양양 복합기렌탈','gq':'복합기렌탈+양양'},
    {'j':'영암','s':'노란우산렌탈','k':'복합기렌탈','jb':'전라남도 영암군 영암읍 역리 58-1','dr':'전라남도 영암군 영암읍 영암로 200','c':'34.7997, 126.6966','img':'https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?w=220&q=70','nq':'영암 복합기렌탈','gq':'복합기렌탈+영암'},
]

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

def card(d):
    consult_url = get_consult_url(d['s'])
    phone = PHONE_MAP.get(consult_url, '1600-3165')
    return (
        '  <div class="card">\n'
        '    <div class="card-thumb"><img src="' + d['img'] + '" alt="' + d['s'] + ' ' + d['j'] + '" /></div>\n'
        '    <div class="card-body">\n'
        '      <div class="card-name">' + d['s'] + ' - ' + d['j'] + '</div>\n'
        '      <span class="card-badge">' + d['k'] + '</span>\n'
        '      <div class="card-info"><span>📌 지번</span> ' + d['jb'] + '</div>\n'
        '      <div class="card-info"><span>🏠 도로명</span> ' + d['dr'] + '</div>\n'
        '      <div class="card-info"><span>🌐 좌표</span> ' + d['c'] + '</div>\n'
        '      <div class="card-links">\n'
        '        <a class="map-btn naver" href="https://map.naver.com/v5/search/' + d['nq'] + '" target="_blank" rel="noopener">네이버 지도</a>\n'
        '        <a class="map-btn google" href="https://www.google.com/maps/search/' + d['gq'] + '" target="_blank" rel="noopener">구글 지도</a>\n'
        '        <a class="map-btn consult" href="' + consult_url + '" target="_blank" rel="noopener">홈페이지</a>\n'
        '        <a class="map-btn phone" href="tel:' + phone + '">전화문의</a>\n'
        '      </div>\n'
        '    </div>\n'
        '  </div>'
    )

all_cards = '\n\n'.join(card(d) for d in cards_data)

with open('C:/Users/pc/Downloads/3333/template.html', 'r', encoding='utf-8') as f:
    tmpl = f.read()

html = tmpl.replace('{{CARDS}}', all_cards)

with open('C:/Users/pc/Downloads/3333/index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print('done, size:', len(html))
