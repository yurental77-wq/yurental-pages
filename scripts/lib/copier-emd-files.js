'use strict';
const fs = require('fs');
const path = require('path');
const { leafPath } = require('../../netlify/functions/lib/emd-url-paths');

// 읍면동 목록은 emd/에, 상세 페이지는 사이트 루트에 있다.
function listCopierEmdFiles(root) {
  const files = fs.readdirSync(path.join(root, 'emd'), { recursive: true })
    .filter(file => file.endsWith('index.html')).map(file => path.join(root, 'emd', file));
  const rows = JSON.parse(fs.readFileSync(path.join(root, 'data/emd_regions.json'), 'utf8')).regions;
  for (const row of rows) {
    const file = path.join(root, ...leafPath(row).split('/').filter(Boolean), 'index.html');
    if (fs.existsSync(file)) files.push(file);
  }
  return [...new Set(files)];
}
module.exports = { listCopierEmdFiles };
