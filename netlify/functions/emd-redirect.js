'use strict';
const { routes } = require('./data/emd_url_redirects.json');

exports.handler = async event => {
  const params = event.queryStringParameters || {};
  // Netlify의 200 rewrite는 원래 요청 URL을 event.path/rawUrl에 전달한다.
  // rewrite 목적지에 붙인 쿼리 값을 원래 요청의 경로로 간주하지 않는다.
  const isOriginalPath = value => /^\/(?:router\/)?emd\//.test(value || '');
  let rawPath = '';
  if (event.rawUrl) {
    try { rawPath = new URL(event.rawUrl).pathname; }
    catch { return { statusCode: 400, body: 'Bad Request' }; }
  }
  const requestPath = [event.path, rawPath].find(isOriginalPath) || '';
  const originalRequest = isOriginalPath(requestPath);
  const tail = originalRequest ? '' : (params.tail || '');
  if (tail && tail !== 'index.html') return { statusCode: 404, body: 'Not Found' };
  let from;
  try { from = decodeURIComponent(originalRequest ? requestPath : (params.from || '')).replace(/index\.html$/, '').replace(/\/?$/, '/'); }
  catch { return { statusCode: 400, body: 'Bad Request' }; }
  if (!Object.hasOwn(routes, from)) return { statusCode: 404, body: 'Not Found' };
  const target = routes[from];
  // 이동 대상은 검증된 사이트 내부 경로로만 제한한다.
  if (!target.startsWith('/emd/') && !target.startsWith('/router/emd/')) {
    return { statusCode: 500, body: 'Invalid redirect target' };
  }
  const query = new URLSearchParams();
  for (const [key, values] of Object.entries(event.multiValueQueryStringParameters || params)) {
    if (key === 'from' || key === 'tail') continue;
    for (const value of Array.isArray(values) ? values : [values]) query.append(key, value);
  }
  const location = target.split('/').map(encodeURIComponent).join('/') + (query.size ? '?' + query : '');
  return { statusCode: 301, headers: { Location: location, 'Cache-Control': 'public, max-age=3600' }, body: '' };
};
