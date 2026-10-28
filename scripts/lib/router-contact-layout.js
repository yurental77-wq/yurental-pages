'use strict';
const assert = require('assert/strict');

function moveRouterContact(html) {
  const contacts = [...html.matchAll(/<h2 class="section-title">[^<]*라우터렌탈 상담<\/h2>\s*<section class="router-contact">[\s\S]*?<\/section>/g)];
  const intros = [...html.matchAll(/<div class="intro-box intro-box--with-thumbnail">[\s\S]*?<img class="intro-thumbnail"[^>]*>\s*<\/div>/g)];
  assert.equal(contacts.length, 1, '라우터 상담 제목/박스가 정확히 한 곳이어야 합니다.');
  assert.equal(intros.length, 1, '라우터 제품 소개가 정확히 한 곳이어야 합니다.');
  const prices = [...html.matchAll(/<section class="price-section" id="router-pricing">[\s\S]*?<\/section>/g)];
  assert.equal(prices.length, 1, '라우터 요금표가 정확히 한 곳이어야 합니다.');
  const contact = contacts[0], intro = intros[0];
  const pricing = prices[0];
  // 소개 바로 아래에 요금표, 그 다음에 상담 제목과 박스를 배치한다.
  const afterIntro = intro.index + intro[0].length;
  const afterPricing = pricing.index + pricing[0].length;
  if (pricing.index >= afterIntro && !html.slice(afterIntro, pricing.index).trim()
    && contact.index >= afterPricing && !html.slice(afterPricing, contact.index).trim()) return html;
  return html.replace(contact[0], '').replace(pricing[0], '')
    .replace(intro[0], () => intro[0] + '\n\n  ' + pricing[0] + '\n\n  ' + contact[0]);
}

module.exports = { moveRouterContact };
