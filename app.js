const state = {
  stiri: [],
  meciuri: [],
  alteMeciuri: [],
  alteMeciuriUpdatedAt: null,
  bilete: [],
  stiriVisible: 6
};

const $ = (selector) => document.querySelector(selector);
const newsGrid         = $('#newsGrid');
const matchesGrid      = $('#matchesGrid');
const modal            = $('#ticketModal');
const ticketBody       = $('#ticketBody');
const ticketOdd        = $('#ticketOdd');
const ticketEyebrow    = $('#ticketEyebrow');

// ── JSON loader ───────────────────────────────────────────────────────────────

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
    loadJson('alte_meciuri.json', { meciuri: [], updated_at: null })
  ]);

  state.stiri                = Array.isArray(newsData.stiri)              ? newsData.stiri              : [];
  state.meciuri              = Array.isArray(matchesData.meciuri)         ? matchesData.meciuri         : [];
  state.bilete               = Array.isArray(matchesData.bilete_sugerate) ? matchesData.bilete_sugerate : [];
  state.alteMeciuri          = Array.isArray(otherData.meciuri)           ? otherData.meciuri           : [];
  state.alteMeciuriUpdatedAt = otherData.updated_at || null;

  renderNews();
  renderMatches();
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

// ── Helpers pronostic ─────────────────────────────────────────────────────────

function cotaPronostic(match) {
  const p = match.pronostic;
  if (!p) return null;
  if (p === '1' || p === '1X') return Number(match.cota_1) || null;
  if (p === '2' || p === 'X2') return Number(match.cota_2) || null;
  if (p === 'X')               return Number(match.cota_x) || null;
  return null;
}

function formatDataMeci(match) {
  const parts = [];
  if (match.data) parts.push(match.data);
  if (match.ora)  parts.push(match.ora);
  if (match.liga) parts.push(match.liga);
  return parts.join(' · ');
}

// ── BILET AI — fix pe zi ──────────────────────────────────────────────────────

const STORAGE_KEY = 'nexas_bilet_ai';

function getBiletAiSalvat() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (e) {
    return null;
  }
}

function salvaBiletAi(bilet, updatedAt) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ bilet, updatedAt }));
  } catch (e) {}
}

function genereazaBiletAiNou() {
  const pool = state.alteMeciuri.filter(m => {
    const c = cotaPronostic(m);
    return m.pronostic && c && c > 1.05 && c < 5.0;
  });

  if (pool.length < 5) return null;

  const MAX_TRIES = 300;
  let best = null;
  let bestDist = Infinity;

  for (let attempt = 0; attempt < MAX_TRIES; attempt++) {
    const count    = 5 + Math.floor(Math.random() * 4); // 5-8
    const shuffled = [...pool].sort(() => Math.random() - 0.5);
    const selected = shuffled.slice(0, Math.min(count, shuffled.length));
    const total    = selected.reduce((acc, m) => acc * (cotaPronostic(m) || 1), 1);

    if (total >= 10 && total <= 20) {
      return { selected, total };
    }
    const dist = total < 10 ? 10 - total : total - 20;
    if (dist < bestDist) {
      bestDist = dist;
      best = { selected, total };
    }
  }
  return best;
}

function deschideBiletAi() {
  if (!modal || !ticketBody || !ticketOdd) return;

  const salvat = getBiletAiSalvat();

  // Refolosim biletul salvat daca e de la aceeasi rulare a agentului
  if (salvat && salvat.updatedAt === state.alteMeciuriUpdatedAt && salvat.bilet) {
    afiseazaBiletAi(salvat.bilet.selected, salvat.bilet.total);
    return;
  }

  // Genereaza bilet nou si salveaza
  const biletNou = genereazaBiletAiNou();

  if (!biletNou) {
    if (ticketEyebrow) ticketEyebrow.textContent = 'Bilet AI';
    ticketBody.innerHTML = '<p class="modal-note">Nu sunt suficiente meciuri cu pronostic. Reîncearcă după actualizarea agentului.</p>';
    ticketOdd.textContent = '0.00';
    openModal();
    return;
  }

  salvaBiletAi(biletNou, state.alteMeciuriUpdatedAt);
  afiseazaBiletAi(biletNou.selected, biletNou.total);
}

function afiseazaBiletAi(selected, total) {
  if (ticketEyebrow) ticketEyebrow.textContent = 'Bilet AI al zilei';

  ticketBody.innerHTML = `
    <p class="modal-note" style="margin-bottom:16px;">
      Bilet fix · ${selected.length} meciuri · cota țintă 10–20
    </p>
    ${selected.map(match => {
      const cota = cotaPronostic(match);
      const info = formatDataMeci(match);
      return `
        <div class="ticket-item">
          <div>
            <b>${escapeHtml(match.home)} vs ${escapeHtml(match.away)}</b><br>
            <small style="color:var(--muted);">${escapeHtml(info)}</small><br>
            <small>
              <span style="color:var(--green);font-weight:700;">${escapeHtml(match.pronostic)}</span>
              · ${escapeHtml(match.motiv || '')}
            </small>
          </div>
          <strong>${cota ? Number(cota).toFixed(2) : '-'}</strong>
        </div>`;
    }).join('')}
  `;
  ticketOdd.textContent = Number(total).toFixed(2);
  openModal();
}

// ── GENEREAZA BILET — aleatoriu la fiecare click ──────────────────────────────

function generateTicket() {
  if (!modal || !ticketBody || !ticketOdd) return;

  if (ticketEyebrow) ticketEyebrow.textContent = 'Bilet generat aleatoriu';

  // Fallback daca exista bilete din meciuri.json
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

  // Aleatoriu de fiecare data
  const shuffled = [...pool].sort(() => Math.random() - 0.5);
  const selected = shuffled.slice(0, Math.min(5, shuffled.length));
  const total    = selected.reduce((acc, m) => acc * Number(m.cota || 1), 1);

  ticketBody.innerHTML = `
    <p class="modal-note"><strong>Bilet aleatoriu</strong></p>
    ${selected.map(match => `
      <div class="ticket-item">
        <div>
          <b>${escapeHtml(match.home)} vs ${escapeHtml(match.away)}</b><br>
          <small style="color:var(--muted);">${escapeHtml(match.liga || '')}${match.data ? ' · ' + escapeHtml(match.data) : ''}${match.ora ? ' · ' + escapeHtml(match.ora) : ''}</small><br>
          <small>${escapeHtml(match.tip_pariu || '')} · ${escapeHtml(match.pronostic || '')} · ${Number(match.scor_incredere || 0)}%</small>
        </div>
        <strong>${Number(match.cota || 0).toFixed(2)}</strong>
      </div>`).join('')}
  `;
  ticketOdd.textContent = total.toFixed(2);
  openModal();
}

// ── Ticket selector (bilete din meciuri.json) ─────────────────────────────────

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

// ── Modal ─────────────────────────────────────────────────────────────────────

function openModal() {
  modal.classList.add('is-open');
  modal.setAttribute('aria-hidden', 'false');
}

function closeModal() {
  modal.classList.remove('is-open');
  modal.setAttribute('aria-hidden', 'true');
}

// ── Utils ─────────────────────────────────────────────────────────────────────

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

// Genereaza Bilet — aleatoriu
['#makeTicketTop', '#makeTicketHero', '#makeTicketMain'].forEach(sel => {
  const btn = $(sel);
  if (btn) btn.addEventListener('click', generateTicket);
});

// Bilet AI — fix pe zi
const biletAiBtn = $('#biletAiBtn');
if (biletAiBtn) biletAiBtn.addEventListener('click', deschideBiletAi);

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
