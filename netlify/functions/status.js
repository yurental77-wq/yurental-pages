const fs = require('fs');
const path = require('path');

const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, 'data/data_rows.json'), 'utf8'));
const PROGRESS_PATH = 'progress.json';

async function ghApi(pathPart, opts = {}) {
  const { GITHUB_TOKEN, GITHUB_REPO } = process.env;
  const res = await fetch(`https://api.github.com/repos/${GITHUB_REPO}${pathPart}`, {
    ...opts,
    headers: {
      Authorization: `Bearer ${GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) throw new Error(`GitHub API ${pathPart} failed: ${res.status} ${await res.text()}`);
  return res.json();
}

async function readProgress() {
  const branch = process.env.GITHUB_BRANCH || 'main';
  try {
    const file = await ghApi(`/contents/${PROGRESS_PATH}?ref=${branch}`);
    const json = Buffer.from(file.content, 'base64').toString('utf8');
    return JSON.parse(json);
  } catch (e) {
    if (e.message.includes('404')) return null;
    throw e;
  }
}

exports.handler = async function (event) {
  const adminPassword = event.headers['x-admin-password'];
  if (!process.env.ADMIN_PASSWORD || adminPassword !== process.env.ADMIN_PASSWORD) {
    return { statusCode: 401, body: JSON.stringify({ error: '관리자 비밀번호가 올바르지 않습니다.' }) };
  }

  if (!process.env.GITHUB_TOKEN || !process.env.GITHUB_REPO) {
    return { statusCode: 500, body: JSON.stringify({ error: 'GITHUB_TOKEN 또는 GITHUB_REPO 환경변수가 설정되지 않았습니다.' }) };
  }

  try {
    const state = await readProgress();

    const byProvinceTotal = {};
    for (const row of DATA) {
      byProvinceTotal[row.province] = (byProvinceTotal[row.province] || 0) + 1;
    }

    if (!state) {
      return {
        statusCode: 200,
        body: JSON.stringify({
          started: false,
          totalRows: DATA.length,
          totalPublished: 0,
          remaining: DATA.length,
          percentage: 0,
          byProvinceTotal,
          byProvincePublished: {},
        }),
      };
    }

    const byProvincePublished = {};
    for (const item of state.published) {
      byProvincePublished[item.province] = (byProvincePublished[item.province] || 0) + 1;
    }

    const totalRows = state.order.length;
    const totalPublished = state.published.length;

    return {
      statusCode: 200,
      body: JSON.stringify({
        started: true,
        totalRows,
        totalPublished,
        remaining: totalRows - totalPublished,
        percentage: Math.round((totalPublished / totalRows) * 1000) / 10,
        byProvinceTotal,
        byProvincePublished,
        log: state.log || [],
      }),
    };
  } catch (err) {
    return { statusCode: 500, body: JSON.stringify({ error: err.message }) };
  }
};
