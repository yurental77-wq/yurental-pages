const fs = require('fs');
const path = require('path');

const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, 'data/data_rows.json'), 'utf8'));
const PROGRESS_PATH = 'progress.json';

// province|slug → DATA index 빠른 조회
const slugIndex = new Map();
for (let i = 0; i < DATA.length; i++) {
  slugIndex.set(`${DATA[i].province}|${DATA[i].slug}`, i);
}

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
  const file = await ghApi(`/contents/${PROGRESS_PATH}?ref=${branch}`);
  const json = Buffer.from(file.content, 'base64').toString('utf8');
  return { state: JSON.parse(json), sha: file.sha };
}

async function writeProgress(state, sha) {
  const branch = process.env.GITHUB_BRANCH || 'main';
  const content = Buffer.from(JSON.stringify(state)).toString('base64');
  await ghApi(`/contents/${PROGRESS_PATH}`, {
    method: 'PUT',
    body: JSON.stringify({
      message: '[skip ci] 지역 리셋 적용',
      content,
      sha,
      branch,
    }),
  });
}

exports.handler = async function (event) {
  if (event.httpMethod !== 'POST') return { statusCode: 405, body: 'Method Not Allowed' };

  const adminPassword = event.headers['x-admin-password'];
  if (!process.env.ADMIN_PASSWORD || adminPassword !== process.env.ADMIN_PASSWORD) {
    return { statusCode: 401, body: JSON.stringify({ error: '관리자 비밀번호가 올바르지 않습니다.' }) };
  }

  if (!process.env.GITHUB_TOKEN || !process.env.GITHUB_REPO) {
    return { statusCode: 500, body: JSON.stringify({ error: 'GITHUB_TOKEN 또는 GITHUB_REPO 환경변수가 설정되지 않았습니다.' }) };
  }

  let provinces = [];
  try {
    const body = event.body ? JSON.parse(event.body) : {};
    provinces = Array.isArray(body.provinces) ? body.provinces : [];
  } catch (e) {}

  if (!provinces.length) {
    return { statusCode: 400, body: JSON.stringify({ error: '리셋할 지역을 선택해주세요.' }) };
  }

  try {
    const { state, sha } = await readProgress();
    const provinceSet = new Set(provinces);

    const toReset = state.published.filter(it => provinceSet.has(it.province));
    const remaining = state.published.filter(it => !provinceSet.has(it.province));

    // published 항목 → DATA 인덱스 변환
    const newQueueIndices = [];
    for (const it of toReset) {
      const idx = slugIndex.get(`${it.province}|${it.slug}`);
      if (idx !== undefined) newQueueIndices.push(idx);
    }

    const newState = {
      ...state,
      published: remaining,
      resetQueue: [...(state.resetQueue || []), ...newQueueIndices],
    };

    await writeProgress(newState, sha);

    return {
      statusCode: 200,
      body: JSON.stringify({
        reset: toReset.length,
        provinces: [...provinceSet],
        resetQueueTotal: newState.resetQueue.length,
      }),
    };
  } catch (err) {
    return { statusCode: 500, body: JSON.stringify({ error: err.message }) };
  }
};
