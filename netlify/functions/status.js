const fs = require('fs');
const path = require('path');
const { getStore } = require('@netlify/blobs');

const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, 'data/data_rows.json'), 'utf8'));

exports.handler = async function (event) {
  const adminPassword = event.headers['x-admin-password'];
  if (!process.env.ADMIN_PASSWORD || adminPassword !== process.env.ADMIN_PASSWORD) {
    return { statusCode: 401, body: JSON.stringify({ error: '관리자 비밀번호가 올바르지 않습니다.' }) };
  }

  try {
    const store = getStore('progress');
    const state = await store.get('state', { type: 'json' });

    if (!state) {
      const byProvince = {};
      for (const row of DATA) {
        byProvince[row.province] = (byProvince[row.province] || 0) + 1;
      }
      return {
        statusCode: 200,
        body: JSON.stringify({
          started: false,
          totalRows: DATA.length,
          totalPublished: 0,
          remaining: DATA.length,
          percentage: 0,
          byProvinceTotal: byProvince,
          byProvincePublished: {},
        }),
      };
    }

    const byProvinceTotal = {};
    for (const row of DATA) {
      byProvinceTotal[row.province] = (byProvinceTotal[row.province] || 0) + 1;
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
      }),
    };
  } catch (err) {
    return { statusCode: 500, body: JSON.stringify({ error: err.message }) };
  }
};
