'use strict';
const fs = require('fs');
const path = require('path');
const { leafPath } = require('../../netlify/functions/lib/emd-url-paths');

// 도시/목록은 router/에, 읍면동 상세는 사이트 루트에 있다.
function listRouterFiles(root) {
  const files = fs.readdirSync(path.join(root, 'router'), { recursive: true })
    .filter(file => file.endsWith('index.html')).map(file => path.join(root, 'router', file));
  const rows = JSON.parse(fs.readFileSync(path.join(root, 'data/emd_regions.json'), 'utf8')).regions;
  for (const row of rows) {
    const file = path.join(root, ...leafPath(row, '라우터렌탈').split('/').filter(Boolean), 'index.html');
    if (fs.existsSync(file)) files.push(file);
  }
  return [...new Set(files)];
}
module.exports = { listRouterFiles };
