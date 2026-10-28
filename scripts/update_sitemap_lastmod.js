// 실행: node scripts/update_sitemap_lastmod.js --write (옵션 생략 시 검사만)
'use strict';
const path = require('path');
const { updateLocalSitemaps } = require('./lib/local-sitemap-lastmod');
console.log(JSON.stringify(updateLocalSitemaps(path.resolve(__dirname, '..'), {
  write: process.argv.includes('--write'),
}), null, 2));
