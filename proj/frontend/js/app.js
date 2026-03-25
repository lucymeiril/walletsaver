/**
 * 지갑 지키미 — 메인 앱 (app.js)
 * 
 * 역할: UI 인터랙션, 라우팅, 컴포넌트 렌더링.
 * data.js만 교체하면 전체 데이터가 바뀜 (결합도 제로).
 * 추후 API 연결 시 fetch()로 교체하면 끝.
 */

;(function () {
  'use strict';

  // ===== DOM 캐싱 =====
  const $ = s => document.querySelector(s);
  const $$ = s => document.querySelectorAll(s);

  // ===== 1. TAB NAVIGATION =====
  const pages = $$('.page');
  const navLinks = $$('[data-tab]');

  function switchTab(tab) {
    console.log(`[탭] → ${tab}`);
    pages.forEach(p => p.classList.remove('active'));
    navLinks.forEach(l => {
      l.classList.toggle('active', l.dataset.tab === tab);
    });
    const el = $(`#page-${tab}`);
    if (el) el.classList.add('active');
    // 모바일 메뉴 닫기
    $('#mobile-menu')?.classList.remove('open');
    // 스크롤 맨 위
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  navLinks.forEach(l => {
    l.addEventListener('click', e => {
      e.preventDefault();
      switchTab(l.dataset.tab);
    });
  });

  // ===== 2. MOBILE MENU =====
  $('#btn-mobile')?.addEventListener('click', () => {
    $('#mobile-menu').classList.toggle('open');
  });
  $('.mobile-menu__overlay')?.addEventListener('click', () => {
    $('#mobile-menu').classList.remove('open');
  });

  // ===== 3. HEADER SCROLL =====
  let lastScroll = 0;
  window.addEventListener('scroll', () => {
    const hdr = $('#hdr');
    if (window.scrollY > 20) hdr.classList.add('scrolled');
    else hdr.classList.remove('scrolled');
    lastScroll = window.scrollY;
  }, { passive: true });

  // ===== 4. SEARCH AUTOCOMPLETE =====
  const searchInput = $('#search-input');
  const searchAC = $('#search-ac');
  const searchClear = $('#search-clear');
  let acIndex = -1;

  searchInput?.addEventListener('input', () => {
    const q = searchInput.value.trim();
    searchClear.classList.toggle('hidden', !q);
    if (q.length === 0) { searchAC.classList.add('hidden'); return; }

    const matches = PRODUCTS.filter(p => p.name.includes(q) || p.cat.includes(q));
    if (matches.length === 0) { searchAC.classList.add('hidden'); return; }

    acIndex = -1;
    searchAC.innerHTML = matches.map((p, i) => `
      <div class="ac-item" data-id="${p.id}" data-idx="${i}">
        <span class="ac-item__icon">${p.icon}</span>
        <div class="ac-item__info">
          <div class="ac-item__name">${highlightMatch(p.name, q)}</div>
          <div class="ac-item__cat">${p.cat}</div>
        </div>
        <span class="ac-item__price">${fmt(p.cur)}원</span>
      </div>
    `).join('');
    searchAC.classList.remove('hidden');

    searchAC.querySelectorAll('.ac-item').forEach(item => {
      item.addEventListener('click', () => selectProduct(parseInt(item.dataset.id)));
    });
  });

  searchInput?.addEventListener('keydown', e => {
    const items = searchAC.querySelectorAll('.ac-item');
    if (!items.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); acIndex = Math.min(acIndex + 1, items.length - 1); updateACFocus(items); }
    if (e.key === 'ArrowUp') { e.preventDefault(); acIndex = Math.max(acIndex - 1, 0); updateACFocus(items); }
    if (e.key === 'Enter' && acIndex >= 0) { e.preventDefault(); items[acIndex].click(); }
    if (e.key === 'Escape') { searchAC.classList.add('hidden'); }
  });

  function updateACFocus(items) {
    items.forEach((it, i) => it.classList.toggle('focused', i === acIndex));
  }

  searchClear?.addEventListener('click', () => {
    searchInput.value = '';
    searchAC.classList.add('hidden');
    searchClear.classList.add('hidden');
    searchInput.focus();
  });

  document.addEventListener('click', e => {
    if (!e.target.closest('#search')) searchAC?.classList.add('hidden');
  });

  function highlightMatch(text, q) {
    const idx = text.indexOf(q);
    if (idx < 0) return text;
    return text.slice(0, idx) + `<mark style="color:var(--accent);background:none">${q}</mark>` + text.slice(idx + q.length);
  }

  // Quick tags
  $$('.tag[data-q]').forEach(tag => {
    tag.addEventListener('click', () => {
      const p = PRODUCTS.find(pr => pr.name === tag.dataset.q);
      if (p) selectProduct(p.id);
    });
  });

  // ===== 5. PRODUCT DETAIL (물가비교) =====
  let currentProduct = null;

  function selectProduct(id) {
    const p = PRODUCTS.find(pr => pr.id === id);
    if (!p) return;
    currentProduct = p;
    console.log(`[상품선택] ${p.name} (${p.unit})`);

    // 입력 업데이트
    searchInput.value = p.name;
    searchAC.classList.add('hidden');

    // 탭 전환
    switchTab('price');

    // 아이템 정보
    $('#pd-icon').textContent = p.icon;
    $('#pd-name').textContent = `${p.name} ${p.unit}`;
    $('#pd-cat').textContent = p.cat;

    // 가격 박스
    $('#pv-cur').textContent = fmt(p.cur) + '원';
    $('#pv-avg').textContent = fmt(p.avg) + '원';
    $('#pv-low').textContent = fmt(p.low) + '원';
    $('#pv-high').textContent = fmt(p.high) + '원';

    // 구매 타이밍 뱃지
    renderTimingBadge(p);

    // 가격 등급 바 마커
    renderTierBar(p);

    // 차트
    renderChart(p, 30);

    // 마트별 가격
    renderMartList(p);

    // 관련 핫딜
    renderRelatedDeals(p);
  }

  function renderTimingBadge(p) {
    const badge = $('#timing-badge');
    const ratio = p.cur / p.avg;
    const diff = p.cur - p.avg;
    const diffStr = diff >= 0 ? `+${fmt(diff)}원` : `${fmt(diff)}원`;

    let cls, icon, title, desc;
    if (ratio <= 0.7) {
      cls = 'ultra'; icon = '🔥'; title = '역대급 기회!';
      desc = `현재 ${fmt(p.cur)}원은 평균보다 ${Math.round((1 - ratio) * 100)}% 저렴합니다. 지금 바로 구매하세요!`;
    } else if (ratio <= 0.85) {
      cls = 'great'; icon = '💙'; title = '좋은 가격이에요!';
      desc = `현재 ${fmt(p.cur)}원은 평균(${fmt(p.avg)}원)보다 ${Math.round((1 - ratio) * 100)}% 저렴합니다.`;
    } else if (ratio <= 1.05) {
      cls = 'good'; icon = '✅'; title = '지금 사도 괜찮아요!';
      desc = `현재 ${fmt(p.cur)}원은 평균(${fmt(p.avg)}원) 수준입니다. (${diffStr})`;
    } else {
      cls = 'wait'; icon = '⏳'; title = '조금 기다려보세요';
      desc = `현재 ${fmt(p.cur)}원은 평균보다 ${Math.round((ratio - 1) * 100)}% 비쌉니다. 할인을 기다려보세요.`;
    }

    badge.className = `timing__badge ${cls}`;
    badge.querySelector('.timing__icon').textContent = icon;
    $('#timing-title').textContent = title;
    $('#timing-desc').textContent = desc;
  }

  function renderTierBar(p) {
    const range = p.high - p.low;
    const pos = ((p.cur - p.low) / range) * 100;
    const clamped = Math.max(3, Math.min(97, pos));
    // 반전: 낮을수록 좋음 → 왼쪽(역대급), 높을수록 → 오른쪽(비쌈)
    $('#tier-marker').style.left = `${clamped}%`;
  }

  // ===== 6. CHART (Canvas) =====
  function renderChart(p, days) {
    const canvas = $('#chart-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width - 40;
    canvas.height = 220;
    const W = canvas.width, H = canvas.height;
    const PAD = { top: 20, right: 16, bottom: 30, left: 50 };

    const history = genPriceHistory(p, days);
    const prices = history.map(h => h.price);
    const minP = Math.min(...prices) * 0.95;
    const maxP = Math.max(...prices) * 1.05;

    ctx.clearRect(0, 0, W, H);

    // grid lines
    ctx.strokeStyle = 'rgba(148,163,184,.08)';
    ctx.lineWidth = 1;
    for (let i = 0; i < 5; i++) {
      const y = PAD.top + (H - PAD.top - PAD.bottom) * (i / 4);
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(W - PAD.right, y); ctx.stroke();
      const price = Math.round(maxP - (maxP - minP) * (i / 4));
      ctx.fillStyle = '#64748b'; ctx.font = '11px Inter'; ctx.textAlign = 'right';
      ctx.fillText(fmt(price), PAD.left - 8, y + 4);
    }

    // average line
    const avgY = PAD.top + (H - PAD.top - PAD.bottom) * ((maxP - p.avg) / (maxP - minP));
    ctx.strokeStyle = 'rgba(56,189,248,.35)';
    ctx.setLineDash([6, 4]);
    ctx.beginPath(); ctx.moveTo(PAD.left, avgY); ctx.lineTo(W - PAD.right, avgY); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#38bdf8'; ctx.font = '10px Inter'; ctx.textAlign = 'left';
    ctx.fillText(`평균 ${fmt(p.avg)}`, W - PAD.right + 4, avgY + 3);

    // line + gradient
    const drawW = W - PAD.left - PAD.right;
    const drawH = H - PAD.top - PAD.bottom;
    const step = drawW / (prices.length - 1);

    const gradient = ctx.createLinearGradient(0, PAD.top, 0, H - PAD.bottom);
    gradient.addColorStop(0, 'rgba(56,189,248,.18)');
    gradient.addColorStop(1, 'rgba(56,189,248,0)');

    // fill area
    ctx.beginPath();
    prices.forEach((pr, i) => {
      const x = PAD.left + i * step;
      const y = PAD.top + drawH * ((maxP - pr) / (maxP - minP));
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.lineTo(PAD.left + (prices.length - 1) * step, H - PAD.bottom);
    ctx.lineTo(PAD.left, H - PAD.bottom);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    // line
    ctx.beginPath();
    prices.forEach((pr, i) => {
      const x = PAD.left + i * step;
      const y = PAD.top + drawH * ((maxP - pr) / (maxP - minP));
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 2;
    ctx.stroke();

    // current price dot
    const lastX = PAD.left + (prices.length - 1) * step;
    const lastY = PAD.top + drawH * ((maxP - prices[prices.length - 1]) / (maxP - minP));
    ctx.beginPath();
    ctx.arc(lastX, lastY, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#38bdf8';
    ctx.fill();
    ctx.beginPath();
    ctx.arc(lastX, lastY, 8, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(56,189,248,.3)';
    ctx.lineWidth = 2;
    ctx.stroke();

    // x axis labels
    ctx.fillStyle = '#64748b'; ctx.font = '10px Inter'; ctx.textAlign = 'center';
    const labelInterval = Math.max(1, Math.floor(prices.length / 6));
    history.forEach((h, i) => {
      if (i % labelInterval === 0 || i === prices.length - 1) {
        const x = PAD.left + i * step;
        const d = h.date;
        ctx.fillText(`${d.getMonth() + 1}/${d.getDate()}`, x, H - 8);
      }
    });
  }

  // Chart range buttons
  $$('.chart-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.chart-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      if (currentProduct) renderChart(currentProduct, parseInt(btn.dataset.range));
    });
  });

  // ===== 7. MART LIST (사이드바) =====
  function renderMartList(p) {
    const el = $('#pd-marts');
    if (!el) return;
    const marts = [
      { name: '이마트', dot: '#FFD700', key: 'emart' },
      { name: '홈플러스', dot: '#FF6B35', key: 'homeplus' },
      { name: '롯데마트', dot: '#E4002B', key: 'lotte' },
      { name: '코스트코', dot: '#E31837', key: 'costco' },
    ];
    el.innerHTML = marts.map(m => {
      const price = p.stores[m.key];
      const diff = price - p.avg;
      const vs = diff <= 0
        ? `<span class="ml-item__vs cheap">${fmt(diff)}원</span>`
        : `<span class="ml-item__vs expensive">+${fmt(diff)}원</span>`;
      return `<div class="ml-item">
        <div class="ml-item__left">
          <span class="ml-item__dot" style="background:${m.dot}"></span>
          <span class="ml-item__name">${m.name}</span>
        </div>
        <div><span class="ml-item__price">${fmt(price)}원</span>${vs}</div>
      </div>`;
    }).join('');
  }

  // ===== 8. RELATED DEALS =====
  function renderRelatedDeals(p) {
    const el = $('#pd-deals');
    if (!el) return;
    const related = HOTDEALS.filter(d => d.title.includes(p.name) || (d.cat === 'food' && p.cat.includes('채소') || p.cat.includes('축산')));
    const shown = related.length > 0 ? related.slice(0, 4) : HOTDEALS.filter(d => d.cat === 'food').slice(0, 3);
    el.innerHTML = shown.map(d => {
      const badge = d.price && p ? getBadge(d.price, p.avg) : '';
      return `<div class="rd-item">
        <div class="rd-item__title">${d.title}</div>
        <div class="rd-item__meta"><span>${d.source}</span><span>${d.time}</span>${badge}</div>
      </div>`;
    }).join('');
  }

  // ===== 9. HOME — PRICE GRID =====
  function renderPriceGrid() {
    const el = $('#price-grid');
    if (!el) return;
    el.innerHTML = PRODUCTS.slice(0, 8).map(p => {
      const diff = p.cur - p.avg;
      const pct = ((diff / p.avg) * 100).toFixed(1);
      let cls = 'same', arrow = '→';
      if (diff < -p.avg * 0.03) { cls = 'down'; arrow = `▼${Math.abs(pct)}%`; }
      else if (diff > p.avg * 0.03) { cls = 'up'; arrow = `▲${pct}%`; }
      return `<div class="pg-card" data-id="${p.id}">
        <div class="pg-card__top">
          <span class="pg-card__icon">${p.icon}</span>
          <span class="pg-card__change ${cls}">${arrow}</span>
        </div>
        <div class="pg-card__name">${p.name} (${p.unit})</div>
        <div class="pg-card__price">${fmt(p.cur)}원</div>
      </div>`;
    }).join('');

    el.querySelectorAll('.pg-card').forEach(card => {
      card.addEventListener('click', () => selectProduct(parseInt(card.dataset.id)));
    });
  }

  // ===== 10. HOME — HOTDEAL PREVIEW =====
  function renderHomeDealPreview() {
    const el = $('#home-deals');
    if (!el) return;
    el.innerHTML = HOTDEALS.slice(0, 4).map(d => renderDealCard(d)).join('');
  }

  function renderDealCard(d) {
    const badge = d.price ? getBadgeHTML(d) : '<span class="dc__badge none"></span>';
    const priceStr = d.price ? `${fmt(d.price)}원` : '';
    return `<div class="dc">
      <div class="dc__head">
        <span class="dc__source">${d.source}</span>
        <span class="dc__time">${d.time}</span>
      </div>
      <div class="dc__title">${d.title}</div>
      <div class="dc__bottom">
        <span class="dc__price">${priceStr}</span>
        ${badge}
      </div>
    </div>`;
  }

  function getBadgeHTML(d) {
    if (!d.price || !d.origPrice) return '<span class="dc__badge none"></span>';
    const ratio = d.price / d.origPrice;
    if (ratio <= 0.5) return `<span class="dc__badge ultra">${Math.round((1 - ratio) * 100)}% 할인</span>`;
    if (ratio <= 0.75) return `<span class="dc__badge great">${Math.round((1 - ratio) * 100)}% 할인</span>`;
    if (ratio <= 0.9) return `<span class="dc__badge ok">${Math.round((1 - ratio) * 100)}% 할인</span>`;
    return '<span class="dc__badge none"></span>';
  }

  function getBadge(price, avg) {
    if (!price || !avg) return '';
    const ratio = price / avg;
    if (ratio <= 0.7) return `<span class="dc__badge ultra">평균 대비 -${Math.round((1 - ratio) * 100)}%</span>`;
    if (ratio <= 0.85) return `<span class="dc__badge great">평균 대비 -${Math.round((1 - ratio) * 100)}%</span>`;
    return '';
  }

  // ===== 11. HOME — MART PREVIEW =====
  function renderHomeMartPreview() {
    const el = $('#home-mart');
    if (!el) return;
    // 각 마트에서 1개씩 대표 상품
    const previews = Object.entries(MART_DATA).map(([key, m]) => {
      const best = m.items.reduce((a, b) => (b.disc > a.disc ? b : a));
      return `<div class="mg-card" style="border-left:3px solid ${m.color}">
        <div class="mg-card__name">${best.name}</div>
        <div class="mg-card__prices">
          <span class="mg-card__sale">${fmt(best.sale)}원</span>
          <span class="mg-card__orig">${fmt(best.orig)}원</span>
          <span class="mg-card__disc">-${best.disc}%</span>
        </div>
        <span class="mg-card__event">${m.name} · ${best.event}</span>
      </div>`;
    });
    el.innerHTML = previews.join('');
  }

  // ===== 12. HOTDEAL TAB =====
  function renderHotdealGrid(filter = 'all') {
    const el = $('#hotdeal-grid');
    if (!el) return;
    let items = HOTDEALS;
    if (filter !== 'all') items = HOTDEALS.filter(d => d.cat === filter);
    el.innerHTML = items.map(d => renderDealCard(d)).join('');
    if (!items.length) el.innerHTML = '<p style="grid-column:1/-1;text-align:center;color:var(--text3);padding:40px">해당 카테고리 핫딜이 없습니다.</p>';
  }

  $$('.fbtn[data-f]').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.fbtn[data-f]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderHotdealGrid(btn.dataset.f);
    });
  });

  // ===== 13. MART TAB =====
  function renderMartGrid(martKey = 'emart') {
    const m = MART_DATA[martKey];
    if (!m) return;
    $('#mart-period').textContent = `행사 기간: ${m.period}`;
    $('#mart-count').textContent = `총 ${m.items.length}개 상품`;

    $('#mart-grid').innerHTML = m.items.map(item => {
      // DB 평균가 대비 (매칭 시도)
      const matched = PRODUCTS.find(p => item.name.includes(p.name));
      let vsHTML = '';
      if (matched) {
        const diff = item.sale - matched.avg;
        if (diff < 0) vsHTML = `<div class="mg-card__vs">DB 평균 대비 <em class="cheap">${fmt(diff)}원 저렴</em></div>`;
        else vsHTML = `<div class="mg-card__vs">DB 평균 대비 <em class="expensive">+${fmt(diff)}원</em></div>`;
      }
      return `<div class="mg-card">
        <div class="mg-card__name">${item.name}</div>
        <div class="mg-card__prices">
          <span class="mg-card__sale">${fmt(item.sale)}원</span>
          <span class="mg-card__orig">${fmt(item.orig)}원</span>
          <span class="mg-card__disc">-${item.disc}%</span>
        </div>
        ${vsHTML}
        <span class="mg-card__event">${item.event}</span>
      </div>`;
    }).join('');
  }

  $$('.mart-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      $$('.mart-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      renderMartGrid(tab.dataset.mart);
    });
  });

  // ===== 14. LOCAL PRICING (주유소 + 식당) =====
  // 14-1. 메인 탭 전환
  $$('.lmt-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.lmt-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const tab = btn.dataset.localtab;
      
      $$('.local-view').forEach(v => v.classList.add('hidden'));
      $(`#view-${tab}`).classList.remove('hidden');
    });
  });

  // 14-2. 주유소 렌더링
  function renderGasStations(fuel = 'gasoline') {
    const el = $('#gas-stations');
    if (!el) return;
    const sorted = [...GAS_STATIONS].sort((a, b) => (a[fuel] || 9999) - (b[fuel] || 9999));
    const avgPrice = Math.round(sorted.reduce((s, g) => s + (g[fuel] || 0), 0) / sorted.filter(g => g[fuel]).length);
    $('#gas-avg strong').textContent = `${fmt(avgPrice)}원/L`;

    el.innerHTML = sorted.map((g, i) => {
      const price = g[fuel];
      if (!price) return '';
      return `<div class="gs-item">
        <span class="gs-item__rank">${i + 1}</span>
        <div style="flex:1">
          <div class="gs-item__name">${g.name}</div>
          <div class="gs-item__addr">${g.addr}</div>
        </div>
        <span class="gs-item__price">${fmt(price)}원</span>
      </div>`;
    }).join('');
  }

  $$('.gas-type').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.gas-type').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderGasStations(btn.dataset.fuel);
    });
  });

  // 14-3. 동네 식당 렌더링
  function renderRestaurants(category = 'all') {
    const el = $('#restaurant-list');
    if (!el) return;
    
    let items = RESTAURANTS;
    if (category !== 'all') {
      items = items.filter(r => r.cat === category);
    }
    
    // 평균 대비 저렴한 순으로 정렬
    items.sort((a, b) => {
      const diffA = a.price - (LOCAL_AVGS[a.menu] || a.price);
      const diffB = b.price - (LOCAL_AVGS[b.menu] || b.price);
      return diffA - diffB;
    });

    el.innerHTML = items.map(r => {
      const avg = LOCAL_AVGS[r.menu];
      let badgeHTML = '';
      if (avg) {
        const diff = r.price - avg;
        if (diff < 0) {
          badgeHTML = `<div class="rest-item__badge cheap">평균대비 -${fmt(Math.abs(diff))}원</div>`;
        } else if (diff > 0) {
          badgeHTML = `<div class="rest-item__badge expensive">평균대비 +${fmt(diff)}원</div>`;
        } else {
          badgeHTML = `<div class="rest-item__badge avg">평균 수준</div>`;
        }
      }
      
      return `<div class="rest-item" data-idx="${r.name}">
        <div class="rest-item__main">
          <div class="rest-item__name">
            <span class="rest-item__cat">${r.cat}</span>${r.name}
          </div>
          <div class="rest-item__menu">
            <b>${r.menu}</b> ${fmt(r.price)}원
          </div>
        </div>
        ${badgeHTML}
      </div>`;
    }).join('');
  }

  $$('.rest-type').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.rest-type').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderRestaurants(btn.dataset.cat);
    });
  });

  // 14-4. 식당 아이템 클릭 이벤트 (모달 연결)
  $('#restaurant-list')?.addEventListener('click', e => {
    const item = e.target.closest('.rest-item');
    if (!item) return;
    const rName = item.dataset.idx;
    const r = RESTAURANTS.find(x => x.name === rName);
    if (r) openRestaurantModal(r);
  });

  function openRestaurantModal(r) {
    $('#rm-name').textContent = r.name;
    $('#rm-cat').textContent = r.cat;
    $('#rm-addr').textContent = r.addr;
    $('#rm-rating-val').textContent = r.rating;

    // 더미 메뉴 생성 로직
    const mockMenus = [ { menu: r.menu, price: r.price } ];
    if (r.cat === '중식') mockMenus.push({menu: "짬뽕", price: r.price + 1000}, {menu: "탕수육", price: 15000});
    else if (r.cat === '카페') mockMenus.push({menu: "카페라떼", price: r.price + 500}, {menu: "조각케이크", price: 5500});
    else if (r.cat === '한식') mockMenus.push({menu: "공기밥", price: 1000}, {menu: "계란말이", price: 6000});

    const menusHTML = mockMenus.map(m => {
      const avg = LOCAL_AVGS[m.menu];
      let badge = '';
      if (avg) {
        const diff = m.price - avg;
        if (diff < 0) badge = `<span class="rm-menu-badge cheap">평균대비 -${fmt(Math.abs(diff))}원 ↓</span>`;
        else if (diff > 0) badge = `<span class="rm-menu-badge expensive">+${fmt(diff)}원 ↑</span>`;
      }
      return `
        <div class="rm-menu-item">
          <div class="rm-menu-item__left">${m.menu}</div>
          <div style="display:flex; align-items:center;">
            <span class="rm-menu-item__price">${fmt(m.price)}원</span>
            ${badge}
          </div>
        </div>
      `;
    }).join('');
    
    $('#rm-menus').innerHTML = menusHTML;
    openModal('modal-restaurant');
  }

  $('#rest-close')?.addEventListener('click', () => closeModal('modal-restaurant'));
  $('#rm-btn-close')?.addEventListener('click', () => closeModal('modal-restaurant'));
  $('#modal-restaurant .modal__overlay')?.addEventListener('click', () => closeModal('modal-restaurant'));

  // ===== 15. COMMUNITY =====
  function renderCommunity(filter = 'all') {
    const el = $('#post-list');
    if (!el) return;
    let posts = COMMUNITY_POSTS;
    if (filter !== 'all') posts = posts.filter(p => p.cat === filter);

    el.innerHTML = posts.map(p => {
      let priceBadge = '';
      if (p.priceVsAvg !== null) {
        const cls = p.priceVsAvg < -20 ? 'cheap' : 'avg';
        priceBadge = `<span class="pl-item__price-badge ${cls}">평균 대비 ${p.priceVsAvg}%</span>`;
      }
      return `<div class="pl-item">
        <span class="pl-item__cat">${p.cat}</span>
        <div class="pl-item__body">
          <div class="pl-item__title">${p.title}</div>
          <div class="pl-item__meta">
            <span>${p.author}</span>
            <span>${p.time}</span>
            <span>조회 ${p.views}</span>
            <span>댓글 ${p.comments}</span>
          </div>
        </div>
        ${priceBadge}
      </div>`;
    }).join('');
  }

  $$('.ctab').forEach(tab => {
    tab.addEventListener('click', () => {
      $$('.ctab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const map = { 'all': 'all', 'mart': '마트', 'online': '온라인', 'food': '외식', 'etc': '기타' };
      renderCommunity(map[tab.dataset.ct] || 'all');
    });
  });

  // ===== 16. MODALS =====
  // Login modal
  function openModal(id) {
    const modal = $(`#${id}`);
    if (modal) { modal.classList.add('open'); document.body.style.overflow = 'hidden'; }
  }
  function closeModal(id) {
    const modal = $(`#${id}`);
    if (modal) { modal.classList.remove('open'); document.body.style.overflow = ''; }
  }

  $('#btn-login')?.addEventListener('click', () => openModal('modal-login'));
  $('#btn-login-m')?.addEventListener('click', () => { $('#mobile-menu').classList.remove('open'); openModal('modal-login'); });
  $('#modal-close')?.addEventListener('click', () => closeModal('modal-login'));
  $('#modal-login .modal__overlay')?.addEventListener('click', () => closeModal('modal-login'));

  // Modal tabs
  $$('.modal__tab').forEach(tab => {
    tab.addEventListener('click', () => {
      $$('.modal__tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      if (tab.dataset.mt === 'login') {
        $('#form-login').classList.remove('hidden');
        $('#form-signup').classList.add('hidden');
      } else {
        $('#form-login').classList.add('hidden');
        $('#form-signup').classList.remove('hidden');
      }
    });
  });

  // Write modal
  $('#btn-write')?.addEventListener('click', () => openModal('modal-write'));
  $('#write-close')?.addEventListener('click', () => closeModal('modal-write'));
  $('#modal-write .modal__overlay')?.addEventListener('click', () => closeModal('modal-write'));

  // --- Write Autocomplete Logic ---
  const wsInput = $('#write-search-input');
  const wsAc = $('#write-ac');
  const wsSelected = $('#write-selected');
  const wsSearch = $('#write-search');
  const wsAvgPrice = $('#ws-avg-price');
  const wsUnit = $('#ws-unit');
  const wsStorage = $('#write-storage');
  let wsIndex = -1;

  wsInput?.addEventListener('input', () => {
    const q = wsInput.value.trim();
    if (q.length === 0) { wsAc.classList.add('hidden'); return; }

    const matches = WRITE_AUTOCOMPLETE_DB.filter(p => p.name.includes(q) || p.cat.includes(q));
    
    let html = matches.map((p, i) => `
      <div class="wac-item" data-id="${p.id}" data-idx="${i}">
        <div class="wac-item__name">${highlightMatch(p.name, q)}</div>
        <div class="wac-item__cat">${p.cat} / ${p.storage} / 기준: ${fmt(p.avg)}원(${p.unit})</div>
      </div>
    `).join('');

    // 항상 직접 입력 옵션을 하단에 추가 (Validation Bypass)
    html += `
      <div class="wac-item wac-item--manual" data-id="manual">
        <div class="wac-item__name" style="color:var(--accent)">➕ '${q}' 직접 입력하기 (평균가 검증 우회)</div>
      </div>
    `;

    wsAc.innerHTML = html;
    wsAc.classList.remove('hidden');

    wsAc.querySelectorAll('.wac-item').forEach(item => {
      item.addEventListener('click', () => selectWriteItem(item.dataset.id));
    });
  });

  wsInput?.addEventListener('keydown', e => {
    const items = wsAc.querySelectorAll('.wac-item');
    if (!items.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); wsIndex = Math.min(wsIndex + 1, items.length - 1); updateWacFocus(items); }
    if (e.key === 'ArrowUp') { e.preventDefault(); wsIndex = Math.max(wsIndex - 1, 0); updateWacFocus(items); }
    if (e.key === 'Enter' && wsIndex >= 0) { e.preventDefault(); items[wsIndex].click(); }
    if (e.key === 'Escape') { wsAc.classList.add('hidden'); }
  });

  function updateWacFocus(items) {
    items.forEach((it, i) => it.classList.toggle('focused', i === wsIndex));
  }

  function selectWriteItem(id) {
    if (id === 'manual') {
      const q = wsInput.value.trim();
      wsAc.classList.add('hidden');
      wsSearch.classList.add('hidden');
      wsSelected.classList.remove('hidden');
      
      $('#ws-cat').textContent = "직접 입력 (검증 우회)";
      $('#ws-name').textContent = q;
      wsAvgPrice.value = ''; // No average price, validation will skip
      wsUnit.value = '';
      wsStorage.value = '';
      return;
    }

    const p = WRITE_AUTOCOMPLETE_DB.find(pr => pr.id === parseInt(id));
    if (!p) return;
    
    wsAc.classList.add('hidden');
    wsSearch.classList.add('hidden');
    wsSelected.classList.remove('hidden');
    
    $('#ws-cat').textContent = p.cat;
    $('#ws-name').textContent = p.name;
    wsAvgPrice.value = p.avg;
    wsUnit.value = p.unit;
    
    if (p.storage && p.storage !== '해당없음') {
      wsStorage.value = p.storage;
    }
  }

  $('#ws-clear')?.addEventListener('click', () => {
    wsSearch.classList.remove('hidden');
    wsSelected.classList.add('hidden');
    wsInput.value = '';
    wsInput.focus();
    wsAvgPrice.value = '';
    wsUnit.value = '';
    $('#write-warning')?.classList.add('hidden');
  });

  // Form submissions (demo toast)
  $('#form-login')?.addEventListener('submit', e => {
    e.preventDefault();
    closeModal('modal-login');
    showToast('로그인 되었습니다! (데모)', 'success');
  });
  $('#form-signup')?.addEventListener('submit', e => {
    e.preventDefault();
    closeModal('modal-login');
    showToast('회원가입이 완료되었습니다! (데모)', 'success');
  });
  
  // Validation on Write Submit
  $('#write-form')?.addEventListener('submit', e => {
    e.preventDefault();
    const warningEl = $('#write-warning');
    warningEl.classList.add('hidden');

    if (wsSelected.classList.contains('hidden')) {
      warningEl.textContent = 'DB 품목 매칭을 완료해주세요. (자동완성에서 항목 선택)';
      warningEl.classList.remove('hidden');
      return;
    }

    const price = parseInt($('#write-price').value, 10);
    const avgStr = wsAvgPrice.value;
    const unit = wsUnit.value;
    
    if (avgStr) {
      const avg = parseInt(avgStr, 10);
      if (price < avg * 0.2) {
        warningEl.textContent = `[등록 차단] 입력하신 가격(${fmt(price)}원)이 평균가(${fmt(avg)}원/${unit}) 대비 비정상적으로 저렴하여 허위/오류 우려로 등록이 제한됩니다.`;
        warningEl.classList.remove('hidden');
        return;
      }
      if (price > avg * 1.2) {
        warningEl.textContent = `[등록 차단] 입력하신 가격(${fmt(price)}원)이 평균가(${fmt(avg)}원/${unit}) 대비 비싸서 바이럴/광고 우려로 핫딜 등록이 제한됩니다.`;
        warningEl.classList.remove('hidden');
        return;
      }
    }

    closeModal('modal-write');
    showToast('핫딜이 성공적으로 검증 및 공유되었습니다!', 'info');
    
    $('#write-form').reset();
    $('#ws-clear').click();
  });

  // ESC to close
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      document.querySelectorAll('.modal.active').forEach(m => {
        m.classList.remove('active');
      });
    }
  });

  // --- 21. DETAIL MODALS DELEGATION ---
  document.addEventListener('click', e => {
    // 1. Hotdeal Delegation
    const dc = e.target.closest('.dc');
    if (dc) {
      const title = dc.querySelector('.dc__title')?.textContent;
      const d = HOTDEALS.find(x => x.title === title);
      openHotdealModal(d);
      return;
    }
    
    // 2. Mart Delegation
    const mg = e.target.closest('.mg-card');
    if (mg) {
      const name = mg.querySelector('.mg-card__name')?.textContent;
      let martItem = null;
      let martName = '';
      for (const [k, v] of Object.entries(MART_DATA)) {
        const found = v.items.find(x => x.name === name);
        if (found) { martItem = found; martName = v.name; break; }
      }
      openMartModal(martItem, martName);
      return;
    }
    
    // 3. Community Post Delegation
    const pl = e.target.closest('.pl-item');
    if (pl) {
      if (pl.classList.contains('ft-item')) {
        const title = pl.querySelector('.pl-item__title')?.textContent;
        const post = COMMUNITY_FREETALK.find(x => x.title === title) || {};
        openPostModal({ ...post, priceVsAvg: null, isFree: true });
      } else {
        const title = pl.querySelector('.pl-item__title')?.textContent;
        const post = COMMUNITY_POSTS.find(x => x.title === title) || {};
        openPostModal(post);
      }
      return;
    }
    
    // 4. Gas Station Delegation
    const gs = e.target.closest('.gs-item');
    if (gs) {
      const name = gs.querySelector('.gs-item__name')?.textContent;
      const st = GAS_STATIONS.find(x => x.name === name);
      openGasModal(st);
      return;
    }
  });

  function openHotdealModal(d) {
    if (!d) return;
    $('#hd-source').textContent = d.source;
    $('#hd-time').textContent = d.time;
    $('#hd-title').textContent = d.title;
    
    if (d.price) {
      $('#hd-price').textContent = fmt(d.price);
      $('#hd-orig').textContent = fmt(d.origPrice);
      $('#hd-badge-wrap').innerHTML = getBadgeHTML(d).replace(/dc__badge/g, 'mod-tag outline');
    } else {
      $('#hd-price').textContent = '-';
      $('#hd-orig').textContent = '-';
      $('#hd-badge-wrap').innerHTML = '';
    }
    $('#hd-views').textContent = d.views;
    $('#hd-comments').textContent = d.comments;
    
    openModal('modal-hotdeal');
  }

  function openMartModal(m, mName) {
    if (!m) return;
    $('#md-mart').textContent = mName;
    $('#md-event').textContent = m.event;
    $('#md-name').textContent = m.name;
    $('#md-sale').textContent = fmt(m.sale);
    $('#md-orig').textContent = fmt(m.orig);
    $('#md-disc').textContent = `-${m.disc}%`;
    
    // Set dummy flyer image
    $('#md-flyer-img').src = `https://placehold.co/600x400/1e293b/38bdf8?text=Flyer+Image:+${encodeURIComponent(m.name)}`;
    
    const matched = PRODUCTS.find(p => m.name.includes(p.name));
    const vsBox = $('#md-vs-box');
    if (matched) {
      const diff = m.sale - matched.avg;
      if (diff < 0) {
        vsBox.innerHTML = `DB 평균 시세(${fmt(matched.avg)}원) 대비 <strong>${fmt(Math.abs(diff))}원</strong> 저렴합니다!`;
        vsBox.style.color = "var(--green)";
        vsBox.style.borderColor = "rgba(52,211,153,.3)";
        vsBox.style.background = "rgba(52,211,153,.1)";
      } else {
        vsBox.innerHTML = `DB 평균 시세(${fmt(matched.avg)}원) 대비 비쌉니다. (오프라인 한정 여부/매장 재고 확인 요망)`;
        vsBox.style.color = "var(--yellow)";
        vsBox.style.borderColor = "rgba(251,191,36,.3)";
        vsBox.style.background = "rgba(251,191,36,.1)";
      }
      vsBox.classList.remove('hidden');
    } else {
      vsBox.classList.add('hidden');
    }
    
    openModal('modal-mart-detail');
  }

  function openPostModal(p) {
    if (!p) return;
    $('#po-cat').textContent = p.cat;
    $('#po-title').textContent = p.title;
    $('#po-author').textContent = p.author;
    $('#po-time').textContent = p.time;
    $('#po-comments-cnt').textContent = p.comments;
    
    // FreeTalk fallback body
    if (p.isFree) {
        $('#po-body-text').textContent = "자유게시판의 내용입니다. 동네 소식이나 팁 등을 자유롭게 공유하는 곳입니다.";
        $('#po-body-img').classList.add('hidden');
    } else {
        $('#po-body-text').textContent = "회원님들! 오늘 우연히 들렀다가 발견했는데 가격 오류인가 싶을 정도로 쌉니다! 필요하신 분들 품절되기 전에 빨리 달리세요!!";
        $('#po-body-img').classList.remove('hidden');
    }
    
    const ver = $('#po-verify');
    if (p.priceVsAvg !== null) {
      if (p.priceVsAvg < 0) {
        ver.className = 'po-verify cheap';
        ver.innerHTML = `✅ <strong>가격 검증 통과됨</strong><br>동네 및 온라인 DB 평균가 대비 <strong>${Math.abs(p.priceVsAvg)}% 저렴</strong>한 것으로 확인된 핫딜입니다.`;
      } else {
        ver.className = 'po-verify';
        ver.innerHTML = `⚠️ <strong>시세 확인 필요</strong><br>평균가 대비 유의미하게 저렴하지 않거나 관련 데이터가 부족합니다. 구매 전 시세 확인을 권장합니다.`;
      }
      ver.classList.remove('hidden');
    } else {
      ver.classList.add('hidden');
    }
    
    openModal('modal-post');
  }

  function openGasModal(g) {
    if (!g) return;
    $('#gd-brand').textContent = g.brand;
    $('#gd-name').textContent = g.name;
    $('#gd-addr').textContent = g.addr;
    $('#gd-gas').textContent = g.gasoline ? fmt(g.gasoline) + "원" : "-";
    $('#gd-die').textContent = g.diesel ? fmt(g.diesel) + "원" : "-";
    $('#gd-lpg').textContent = g.lpg ? fmt(g.lpg) + "원" : "-";
    openModal('modal-gas-detail');
  }

  // Modals Close Events
  $$('#hotdeal-close, #modal-hotdeal .modal__overlay').forEach(el => el?.addEventListener('click', () => closeModal('modal-hotdeal')));
  $('#hd-btn-go')?.addEventListener('click', () => { showToast('해당 쇼핑몰/원문 링크로 이동합니다.', 'info'); closeModal('modal-hotdeal'); });

  $$('#mart-close, #modal-mart-detail .modal__overlay').forEach(el => el?.addEventListener('click', () => closeModal('modal-mart-detail')));
  $('#md-btn-cart')?.addEventListener('click', () => { showToast('장바구니에 담겼습니다!', 'success'); closeModal('modal-mart-detail'); });

  $$('#post-close, #modal-post .modal__overlay').forEach(el => el?.addEventListener('click', () => closeModal('modal-post')));
  
  // Post Comment Submit
  $('#po-comment-btn')?.addEventListener('click', () => {
    const ipt = $('#po-comment-text');
    const txt = ipt.value.trim();
    if (!txt) return;
    const clist = $('#po-comments-list');
    const div = document.createElement('div');
    div.className = 'po-comment';
    div.innerHTML = `<strong>(나)</strong> ${txt}`;
    clist.prepend(div);
    ipt.value = '';
    
    // update count
    const cntEl = $('#po-comments-cnt');
    cntEl.textContent = parseInt(cntEl.textContent, 10) + 1;
    showToast('댓글이 등록되었습니다.', 'success');
  });
  
  $('#po-comment-text')?.addEventListener('keyup', (e) => {
    if (e.key === 'Enter') $('#po-comment-btn').click();
  });

  $$('#gas-close, #modal-gas-detail .modal__overlay').forEach(el => el?.addEventListener('click', () => closeModal('modal-gas-detail')));
  $('#gd-btn-map')?.addEventListener('click', () => { showToast('기본 지도 앱 길찾기를 실행합니다.', 'info'); closeModal('modal-gas-detail'); });

  // ===== 17. TOAST =====
  function showToast(msg, type = 'info') {
    const container = $('#toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 3000);
  }

  // ===== 18. UTILITY =====
  function fmt(n) {
    if (n == null) return '';
    return n.toLocaleString('ko-KR');
  }

  // ===== 19. INTERSECTION OBSERVER (scroll animations) =====
  const observer = new IntersectionObserver(entries => {
    entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('visible'); observer.unobserve(e.target); } });
  }, { threshold: 0.1 });
  document.querySelectorAll('.animate-on-view').forEach(el => observer.observe(el));

  // ===== 20. INIT =====
  function init() {
    console.log('[지갑지키미] 초기화 시작');
    renderPriceGrid();
    renderHomeDealPreview();
    renderHomeMartPreview();
    renderHotdealGrid();
    renderMartGrid('emart');
    renderGasStations('gasoline');
    typeof renderRestaurants === 'function' && renderRestaurants('all');
    renderCommunity('all');
    console.log('[지갑지키미] 초기화 완료');
  }

  init();
})();
