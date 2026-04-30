const state = {
  stiri: [],
  meciuri: [],
  alteMeciuri: [],
  bilete: [],
  meta: {},
  stiriVisible: 6
};

const $ = (selector) => document.querySelector(selector);
const newsGrid        = $('#newsGrid');
const matchesGrid     = $('#matchesGrid');
const otherMatchesGrid = $('#otherMatchesGrid');
const modal           = $('#ticketModal');
const ticketBody      = $('#ticketBody');
const ticketOdd       = $('#ticketOdd');

async function loadJson(path, fallback) {
  try {
    const resp = await fetch(`${path}?v=${Date.now()}`, { cache: 'no-store' });
    if (!resp.ok) throw new Error(`Nu pot incarca ${path}`);
    return await resp.json();
  } catch (e) {
    console.warn(e.message);
    return fallback;
  }
}

async function init() {
  const [newsData, matchesData, otherData] = await Promise.all([
    loadJson('stiri.json',        { stiri: [] }),
    loadJson('meciuri.json',      { meciuri: [], bilete_sugerate: [] }),
    loadJson('alte_meciuri.json', { meciuri: [] })
  ]);

  state.stiri       = Array.isArray(newsData.stiri)               ? newsData.stiri               : [];
  state.meciuri     = Array.isArray(matchesData.meciuri)          ? matchesData.meciuri          : [];
  state.bilete      = Array.isArray(matchesData.bilete_sugerate)  ? matchesData.bilete_sugerate  : [];
  state.alteMeciuri = Array.isArray(otherData.meciuri)            ? otherData.meciuri            : [];

  renderNews();
  renderMatches();
  renderOtherMatches();
}

// ── Stiri cu Load More ────────────────────────────────────────────────────────

function renderNews() {
  if (!newsGrid) return;
  if (!state.stiri.length) {
    newsGrid.innerHTML = emptyCard('Nu exista stiri disponibile momentan.');
    removeLoadMoreBtn();
    return;
  }

  const visible = state.stiri.slice(0, state.stiriVisible);
  newsGrid.innerHTML = visible.map((item) => `
    <article class="news-card">
      <span class="pill pill-green">${escapeHtml(item.categorie || 'Fotbal')}</span>
      <h3>${escapeHtml(item.titlu || 'Stire fara titlu')}</h3>
      <p class="news-summary">${escapeHtml(item.rezumat || '')}</p>
      <button class="read-more-btn" type="button">Citeste mai mult</button>
      <div class="news-meta">
        ${(item.surse || []).slice(0, 3).map(s => `<span class="pill">${escapeHtml(s)}</span>`).join('')}
        ${item.data_afisaj ? `<span class="pill pill-time">${escapeHtml(item.data_afisaj)}</span>` : ''}
      </div>
    </article>
  `).join('');

  renderLoadMoreBtn();
}

function renderLoadMoreBtn() {
  removeLoadMoreBtn();
  if (state.stiriVisible >= state.stiri.length) return;

  const remaining = state.stiri.length - state.stiriVisible;
  const wrap = document.createElement('div');
  wrap.id = 'loadMoreWrap';
  wrap.style.cssText = 'grid-column:1/-1;display:flex;justify-content:center;margin-top:8px;';
  wrap.innerHTML = `
    <button id="loadMoreBtn" class="btn btn-ghost" style="gap:8px;">
      Încarcă mai multe
      <span style="background:rgba(57,255,156,.18);color:var(--green);border-radius:999px;padding:2px 10px;font-size:12px;">+${remaining}</span>
    </button>`;
  newsGrid.appendChild(wrap);
  document.getElementById('loadMoreBtn').addEventListener('click', () => {
    state.stiriVisible += 6;
    renderNews();
  });
}

function removeLoadMoreBtn() {
  const el = document.getElementById('loadMoreWrap');
  if (el) el.remove();
}

// ── Meciuri principale ────────────────────────────────────────────────────────

function renderMatches() {
  if (!matchesGrid) return;
  if (!state.meciuri.length) {
    matchesGrid.innerHTML = emptyCard('Nu exista predictii disponibile momentan.');
    return;
  }
  matchesGrid.innerHTML = state.meciuri.map((match) => `
    <article class="match-card">
      <div class="match-top">
        <div>
          <h3>${escapeHtml(match.home || '')} vs ${escapeHtml(match.away || '')}</h3>
          <div class="league">${escapeHtml(match.liga || '')} · ${escapeHtml(match.ora || '')}${match.data ? ' · ' + escapeHtml(match.data) : ''}</div>
        </div>
        <div class="odd-box">
          <small>cota</small>
          ${Number(match.cota || 0).toFixed(2)}
        </div>
      </div>
      <div class="match-pick">
        ${match.tip_pariu ? `<span class="pill pill-green">${escapeHtml(match.tip_pariu)}</span>` : ''}
        Pronostic: <strong>${escapeHtml(match.pronostic || '')}</strong>
      </div>
      <div class="match-stats">
        <div><span>${Number(match.scor_incredere || 0)}%</span><small>incredere</small></div>
        <div><span>${escapeHtml(match.forma_home || '-')}</span><small>forma gazde</small></div>
        <div><span>${escapeHtml(match.forma_away || '-')}</span><small>forma oaspeti</small></div>
      </div>
      <p class="reason">${escapeHtml(match.motiv || '')}</p>
    </article>
  `).join('');
}

// ── Alte Meciuri cu highlight pronostic ──────────────────────────────────────

function cotaPronostic(match) {
  const p = match.pronostic;
  if (!p) return null;
  if (p === '1')  return Number(match.cota_1) || null;
  if (p === '2')  return Number(match.cota_2) || null;
  if (p === 'X')  return Number(match.cota_x) || null;
  if (p === '1X') return Number(match.cota_1) || null;
  if (p === 'X2') return Number(match.cota_2) || null;
  return null;
}

function cellStyle(cell, pronostic) {
  const active = (
    (cell === '1'  && (pronostic === '1' || pronostic === '1X')) ||
    (cell === 'X'  && (pronostic === 'X' || pronostic === '1X' || pronostic === 'X2')) ||
    (cell === '2'  && (pronostic === '2' || pronostic === 'X2'))
  );
  return active
    ? 'background:rgba(57,255,156,.22);border-color:rgba(57,255,156,.5);'
    : '';
}

function renderOtherMatches() {
  if (!otherMatchesGrid) return;
  if (!state.alteMeciuri.length) {
    otherMatchesGrid.innerHTML = emptyCard('Nu exista alte meciuri disponibile momentan.');
    return;
  }

  otherMatchesGrid.innerHTML = state.alteMeciuri.map((match) => {
    const c1 = match.cota_1 != null ? Number(match.cota_1).toFixed(2) : '-';
    const cx = match.cota_x != null ? Number(match.cota_x).toFixed(2) : '-';
    const c2 = match.cota_2 != null ? Number(match.cota_2).toFixed(2) : '-';
    const p  = match.pronostic || null;

    return `
      <article class="match-card other-match-card">
        <div class="match-top">
          <div>
            <h3>${escapeHtml(match.home || '')} vs ${escapeHtml(match.away || '')}</h3>
            <div class="league">
              ${escapeHtml(match.liga || '')}
              ${match.data ? ' · ' + escapeHtml(match.data) : ''}
              ${match.ora  ? ' · ' + escapeHtml(match.ora)  : ''}
            </div>
          </div>
        </div>
        <div class="match-stats">
          <div style="${cellStyle('1', p)}">
            <span>${escapeHtml(c1)}</span><small>1</small>
          </div>
          <div style="${cellStyle('X', p)}">
            <span>${escapeHtml(cx)}</span><small>X</small>
          </div>
          <div style="${cellStyle('2', p)}">
            <span>${escapeHtml(c2)}</span><small>2</small>
          </div>
        </div>
        ${p ? `<div class="match-pick" style="margin-top:10px;">
          <span class="pill pill-green">${escapeHtml(p)}</span>
          <small style="color:var(--muted);margin-left:8px;">${escapeHtml(match.motiv || '')}</small>
        </div>` : ''}
      </article>`;
  }).join('');
}

// ── Bilet din Alte Meciuri (cota totala 10-20) ───────────────────────────────

function generateTicketFromAlte() {
  // Filtrare: meciuri cu pronostic si cota valida
  const pool = state.alteMeciuri.filter(m => {
    const c = cotaPronostic(m);
    return m.pronostic && c && c > 1.05 && c < 5.0;
  });

  if (pool.length < 5) {
    ticketBody.innerHTML = '<p class="modal-note">Nu sunt suficiente meciuri cu pronostic pentru a genera biletul. Reîncearcă mâine după actualizarea agentului.</p>';
    ticketOdd.textContent = '0.00';
    openModal();
    return;
  }

  // Incercam sa gasim o selectie de 5-8 meciuri cu cota totala 10-20
  const MAX_TRIES = 200;
  let best = null;
  let bestDist = Infinity;

  for (let attempt = 0; attempt < MAX_TRIES; attempt++) {
    // Alegem aleatoriu intre 5 si 8 meciuri
    const count = 5 + Math.floor(Math.random() * 4); // 5,6,7,8
    const shuffled = [...pool].sort(() => Math.random() - 0.5);
    const selected = shuffled.slice(0, Math.min(count, shuffled.length));

    const total = selected.reduce((acc, m) => acc * (cotaPronostic(m) || 1), 1);

    if (total >= 10 && total <= 20) {
      best = { selected, total };
      break;
    }

    // Pastram cea mai apropiata de interval
    const dist = total < 10 ? 10 - total : total - 20;
    if (dist < bestDist) {
      bestDist = dist;
      best = { selected, total };
    }
  }

  if (!best) {
    ticketBody.innerHTML = '<p class="modal-note">Nu am putut genera un bilet in intervalul dorit.</p>';
    ticketOdd.textContent = '0.00';
    openModal();
    return;
  }

  const { selected, total } = best;

  ticketBody.innerHTML = `
    <p class="modal-note" style="margin-bottom:16px;">
      Bilet generat automat · ${selected.length} meciuri · cota țintă 10–20
    </p>
    ${selected.map(match => {
      const cota = cotaPronostic(match);
      return `
        <div class="ticket-item">
          <div>
            <b>${escapeHtml(match.home)} vs ${escapeHtml(match.away)}</b><br>
            <small>${escapeHtml(match.liga || '')} · <span style="color:var(--green);font-weight:700;">${escapeHtml(match.pronostic)}</span> · ${escapeHtml(match.motiv || '')}</small>
          </div>
          <strong>${cota ? Number(cota).toFixed(2) : '-'}</strong>
        </div>`;
    }).join('')}
  `;
  ticketOdd.textContent = total.toFixed(2);
  openModal();
}

function generateTicket() {
  if (!modal || !ticketBody || !ticketOdd) return;

  // Daca exista alte meciuri cu pronostic, folosim acelea pentru bilet
  const cuPronostic = state.alteMeciuri.filter(m => m.pronostic && cotaPronostic(m));
  if (cuPronostic.length >= 5) {
    generateTicketFromAlte();
    return;
  }

  // Fallback: bilet din meciurile principale
  if (state.bilete && state.bilete.length > 0) {
    showTicketSelector();
    return;
  }

  const pool = [...state.meciuri].filter(match => Number(match.cota) > 1);
  if (pool.length < 3) {
    ticketBody.innerHTML = '<p class="modal-note">Ai nevoie de minimum 3 meciuri pentru a genera biletul.</p>';
    ticketOdd.textContent = '0.00';
    openModal();
    return;
  }
  const selected = pool
    .sort((a, b) => Number(b.scor_incredere || 0) - Number(a.scor_incredere || 0))
    .slice(0, Math.min(5, pool.length));
  renderTicket('Bilet automat', selected);
}

// ── Ticket helpers ────────────────────────────────────────────────────────────

function showTicketSelector() {
  const buttons = state.bilete.map((bilet, i) => `
    <button class="ticket-tab ${i === 0 ? 'active' : ''}" data-bilet-idx="${i}">
      ${escapeHtml(bilet.nume || 'Bilet')}<br>
      <small>cota ${Number(bilet.cota_totala || 0).toFixed(2)} · ${Number(bilet.incredere_medie || 0).toFixed(0)}%</small>
    </button>`).join('');
  ticketBody.innerHTML = `<div class="ticket-tabs">${buttons}</div><div id="ticketContent"></div>`;
  document.querySelectorAll('.ticket-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.ticket-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      showBiletContent(Number(btn.dataset.biletIdx));
    });
  });
  showBiletContent(0);
  openModal();
}

function showBiletContent(index) {
  const bilet = state.bilete[index];
  if (!bilet) return;
  const meciuri = (bilet.fixture_ids || [])
    .map(id => state.meciuri.find(m => m.fixture_id === id))
    .filter(Boolean);
  const content = $('#ticketContent');
  if (!content) return;
  content.innerHTML = meciuri.map(match => `
    <div class="ticket-item">
      <div>
        <b>${escapeHtml(match.home)} vs ${escapeHtml(match.away)}</b><br>
        <small>${escapeHtml(match.tip_pariu || '')} · ${escapeHtml(match.pronostic || '')} · ${Number(match.scor_incredere || 0)}%</small>
      </div>
      <strong>${Number(match.cota || 0).toFixed(2)}</strong>
    </div>`).join('');
  ticketOdd.textContent = Number(bilet.cota_totala || 0).toFixed(2);
}

function renderTicket(label, selected) {
  const total = selected.reduce((acc, m) => acc * Number(m.cota || 1), 1);
  ticketBody.innerHTML = `
    <p class="modal-note"><strong>${escapeHtml(label)}</strong></p>
    ${selected.map(match => `
      <div class="ticket-item">
        <div>
          <b>${escapeHtml(match.home)} vs ${escapeHtml(match.away)}</b><br>
          <small>${escapeHtml(match.tip_pariu || '')} · ${escapeHtml(match.pronostic || '')} · ${Number(match.scor_incredere || 0)}%</small>
        </div>
        <strong>${Number(match.cota || 0).toFixed(2)}</strong>
      </div>`).join('')}`;
  ticketOdd.textContent = total.toFixed(2);
  openModal();
}

function openModal() {
  modal.classList.add('is-open');
  modal.setAttribute('aria-hidden', 'false');
}

function closeModal() {
  modal.classList.remove('is-open');
  modal.setAttribute('aria-hidden', 'true');
}

function emptyCard(message) {
  return `<article class="news-card"><h3>Date indisponibile</h3><p>${escapeHtml(message)}</p></article>`;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

// ── Events ────────────────────────────────────────────────────────────────────

['#makeTicketTop', '#makeTicketHero', '#makeTicketMain'].forEach(sel => {
  const btn = $(sel);
  if (btn) btn.addEventListener('click', generateTicket);
});

document.querySelectorAll('[data-close-modal]').forEach(el => {
  el.addEventListener('click', closeModal);
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

document.addEventListener('click', e => {
  const btn = e.target.closest('.read-more-btn');
  if (!btn) return;
  const card = btn.closest('.news-card');
  if (!card) return;
  card.classList.toggle('is-expanded');
  btn.textContent = card.classList.contains('is-expanded') ? 'Arata mai putin' : 'Citeste mai mult';
});

init();
