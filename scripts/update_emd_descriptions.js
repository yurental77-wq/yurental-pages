// node scripts/update_emd_descriptions.js [--write]
// 읍면동 복합기의 meta/OG/WebPage 설명만 지역별 저장 소개문과 동기화.
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { ROOT } = require('../build');
const { validateSource, leafPath } = require('../build-emd');
const { getMetaDescription, escapeHtml } = require('../netlify/functions/lib/copier-header-intros');
const rows = validateSource(JSON.parse(fs.readFileSync(path.join(ROOT, 'data/emd_regions.json'), 'utf8')));
const write = process.argv.includes('--write');
const operations = [], descriptions = new Set(), lengths = [];
const metaRegex = /(<meta (?:name="description"|property="og:description") content=")[^"]*("[^>]*>)/g;
const schemaRegex = /<script type="application\/ld\+json">([\s\S]*?)<\/script>/g;
function stripDescriptions(html) {
  return html.replace(metaRegex, '').replace(schemaRegex, (block, body) => {
    const schema = JSON.parse(body);
    if (schema['@type'] !== 'WebPage') return block;
    delete schema.description;
    return JSON.stringify(schema);
  });
}
for (const row of rows) {
  const key = leafPath(row), file = path.join(ROOT, ...key.split('/').filter(Boolean), 'index.html');
  const html = fs.readFileSync(file, 'utf8');
  const description = getMetaDescription(key, 'MISSING');
  assert.notEqual(description, 'MISSING', key);
  assert.ok(description.startsWith(row.full_name + ' '), key);
  assert.ok(description.length >= 140 && description.length <= 205, key);
  assert.ok(!descriptions.has(description), `중복 description: ${key}`);
  descriptions.add(description); lengths.push(description.length);
  let metaCount = 0, schemaCount = 0;
  let next = html.replace(metaRegex, (_, prefix, suffix) => {
    metaCount++; return prefix + escapeHtml(description) + suffix;
  });
  next = next.replace(schemaRegex, (block, body) => {
    const schema = JSON.parse(body);
    if (schema['@type'] !== 'WebPage') return block;
    schemaCount++;
    schema.description = description;
    return block.replace(body, () => body.replace(body.trim(), () => JSON.stringify(schema).replace(/</g, '\\u003c')));
  });
  assert.equal(metaCount, 2, file);
  assert.equal(schemaCount, 1, file);
  assert.equal(stripDescriptions(next), stripDescriptions(html), `설명 외 변경: ${file}`);
  if (write) { if (next !== html) operations.push({ file, next }); }
  else assert.equal(next === html, true, `메타 설명 미반영: ${file}`);
}
assert.equal(getMetaDescription('/pages/경기도/의정부-복합기렌탈/', 'city-unchanged'), 'city-unchanged');
assert.equal(getMetaDescription('/router/익산/', 'router-unchanged'), 'router-unchanged');
for (const { file, next } of operations) fs.writeFileSync(file, Buffer.from(next, 'utf8'));
console.log(JSON.stringify({ pages: rows.length, updated: operations.length, uniqueDescriptions: descriptions.size,
  minChars: Math.min(...lengths), maxChars: Math.max(...lengths), titlesAndBodyPreserved: true }, null, 2));
