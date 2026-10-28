// 읽기 전용: 전국 도시·행정읍면동 라우터 페이지, 링크, SEO 및 사이트맵 검사.
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { ROOT, SITE_URL, DATA } = require('../build');
const { validateSource } = require('../build-emd');
const rows = validateSource(JSON.parse(fs.readFileSync(path.join(ROOT,'data/emd_regions.json'),'utf8')));
const { listRouterFiles } = require('./lib/router-files');
const files = listRouterFiles(ROOT);
const { isRootRouterLeafPath } = require('../netlify/functions/lib/emd-url-paths');
assert.equal(files.filter(file => isRootRouterLeafPath('/' + path.relative(ROOT, path.dirname(file)).split(path.sep).join('/') + '/')).length, rows.length);
const expectedDistricts = new Set(rows.map(row=>row.province+'|'+row.district)).size;
const expectedProvinces = new Set(rows.map(row=>row.province)).size + new Set(DATA.map(city=>city.province)).size;
assert.equal(files.length,DATA.length+rows.length+expectedDistricts+expectedProvinces+2);
const canonicalSet = new Set(), titles = new Set(), descriptions = new Set();
let details = 0, localLinks = 0, emd = 0;
const expectedCodes = new Set(rows.map(row=>row.code));
for (const file of files) {
  const html = fs.readFileSync(file,'utf8');
  assert(!/\{\{[A-Z_]+\}\}/.test(html),file);
  const canonical = html.match(/<link rel="canonical" href="([^"]+)"/)[1];
  const urlPath = '/' + path.relative(ROOT,path.dirname(file)).split(path.sep).join('/')+'/';
  assert.equal(decodeURI(canonical),SITE_URL+urlPath,file);
  assert(!canonicalSet.has(canonical),'중복 canonical: '+file); canonicalSet.add(canonical);
  const title = html.match(/<title>([^<]+)<\/title>/)[1];
  assert(!titles.has(title),'중복 title: '+file); titles.add(title);
  const description = html.match(/<meta name="description" content="([^"]+)"/)[1];
  assert(!descriptions.has(description),'중복 description: '+file); descriptions.add(description);
  assert.equal((html.match(/<h1[ >]/g)||[]).length,1,file);
  const schemas = [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].map(match=>JSON.parse(match[1]));
  const breadcrumb = schemas.find(schema=>schema['@type']==='BreadcrumbList');
  assert.equal(breadcrumb.itemListElement.at(-1).item,canonical,file);
  if (html.includes('class="router-page"')) {
    details++;
    assert.equal((html.match(/class="router-plan"/g)||[]).length,3,file);
    const product = schemas.find(schema=>schema['@type']==='Product');
    assert.deepEqual(product.offers.map(offer=>offer.price),[80000,100000,130000],file);
    assert(product.offers.every(offer=>offer.url===canonical && offer.priceSpecification.valueAddedTaxIncluded===false),file);
    const faq = schemas.find(schema=>schema['@type']==='FAQPage');
    assert.equal(faq.mainEntity.length,(html.match(/class="faq-q"/g)||[]).length,file);
    for (const question of faq.mainEntity) { assert(html.includes(question.name),file); assert(html.includes(question.acceptedAnswer.text),file); }
    assert(html.includes('href="tel:16604625"') && html.includes('href="tel:01071386470"'),file);
    assert(html.includes("link: 'https://hanarental.shop/'") && html.includes("link: 'https://yurental.com/'"),file);
    assert(!html.includes('月') && !html.includes('월 인쇄량'),file);
    const web = schemas.find(schema=>schema['@type']==='WebPage');
    if (web.about.identifier) { emd++; assert(expectedCodes.delete(web.about.identifier),'중복/알 수 없는 행정코드: '+file); }
    if (!web.about.name.includes('익산')) assert(!html.includes('익산'), '익산 문구 잔존: '+file);
  }
  const markup = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'');
  for (const match of markup.matchAll(/(?:href|src)="([^"]+)"/g)) {
    const target = match[1];
    if (/^(?:[a-z]+:|\/\/)/i.test(target)) continue;
    const [pathname,fragment] = target.split('#');
    if (pathname) {
      const clean = decodeURIComponent(pathname.split('?')[0]);
      const local = clean.startsWith('/') ? path.resolve(ROOT,'.'+clean) : path.resolve(path.dirname(file),clean);
      assert(local.startsWith(ROOT+path.sep),'작업 폴더 외부 링크: '+file);
      assert(fs.existsSync(local),'잘못된 파일 링크 '+target+' in '+file); localLinks++;
    } else if (fragment) assert(html.includes('id="'+fragment+'"'),'잘못된 앵커: '+file);
  }
}
assert.equal(emd,3565); assert.equal(expectedCodes.size,0);
assert.equal(details,227+3565+expectedDistricts);
const sitemap = fs.readFileSync(path.join(ROOT,'sitemap-router.xml'),'utf8');
const locations = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map(match=>match[1]);
assert.equal(locations.length,files.length);
assert.equal(new Set(locations).size,locations.length);
for (const location of locations) assert(canonicalSet.has(location),'알 수 없는 사이트맵 URL: '+location);
assert(fs.readFileSync(path.join(ROOT,'robots.txt'),'utf8').includes('Sitemap: '+SITE_URL+'/sitemap-router.xml'));
console.log(JSON.stringify({pages:files.length,detailPages:details,emdPages:emd,localLinks,sitemapUrls:locations.length,uniqueTitles:titles.size,uniqueDescriptions:descriptions.size},null,2));
