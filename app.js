const state = {
  stiri: [],
  meciuri: [],
  alteMeciuri: [],
  alteMeciuriUpdatedAt: null,
  bilete: [],
  stiriVisible: 6,
  meciuriVisible: 10
};

const $ = (selector) => document.querySelector(selector);
const newsGrid    = $('#newsGrid');
const matchesGrid = $('#matchesGrid');
const modal       = $('#ticketModal');
const ticketBody  = $('#ticketBody');
const ticketOdd   = $('#ticketOdd');
const ticketEyebrow = $('#ticketEyebrow');

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
    removeBtn('loadMoreNewsWrap');
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
  addLoadMoreBtn(newsGrid, 'loadMoreNewsWrap',
    state.stiri.length - state.stiriVisible,
    () => { state.stiriVisible += 6; renderNews(); }
  );
}

// ── Meciuri din alte_meciuri cu Load More ─────────────────────────────────────

function renderMatches() {
  if (!matchesGrid) return;
  if (!state.alteMeciuri.length) {
    matchesGrid.innerHTML = emptyCard('Nu exista meciuri disponibile momentan.');
    removeBtn('loadMoreMatchesWrap');
    return;
  }

  const visible = state.alteMeciuri.slice(0, state.meciuriVisible);

  matchesGrid.innerHTML = visible.map((match) => {
    const c1 = match.cota_1 != null ? Number(match.cota_1).toFixed(2) : '-';
    const cx = match.cota_x != null ? Number(match.cota_x).toFixed(2) : '-';
    const c2 = match.cota_2 != null ? Number(match.cota_2).toFixed(2) : '-';
    const p  = match.pronostic || null;

    return `
      <article class="match-card">
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
        ${p ? `
        <div class="match-pick" style="margin-top:10px;">
          <span class="pill pill-green">${escapeHtml(p)}</span>
          <small style="color:var(--muted);margin-left:8px;">${escapeHtml(match.motiv || '')}</small>
        </div>` : ''}
      </article>`;
  }).join('');

  addLoadMoreBtn(matchesGrid, 'loadMoreMatchesWrap',
    state.alteMeciuri.length - state.meciuriVisible,
    () => { state.meciuriVisible += 10; renderMatches(); }
  );
}

// ── Load More helper ──────────────────────────────────────────────────────────

function addLoadMoreBtn(grid, id, remaining, onClick) {
  removeBtn(id);
  if (remaining <= 0) return;
  const wrap = document.createElement('div');
  wrap.id = id;
  wrap.style.cssText = 'grid-column:1/-1;display:flex;justify-content:center;margin-top:8px;';
  wrap.innerHTML = `
    <button class="btn btn-ghost" style="gap:8px;">
      Încarcă mai multe
      <span style="background:rgba(57,255,156,.18);color:var(--green);border-radius:999px;padding:2px 10px;font-size:12px;">+${remaining}</span>
    </button>`;
  wrap.querySelector('button').addEventListener('click', onClick);
  grid.appendChild(wrap);
}

function removeBtn(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

// ── Highlight celula pronostic ────────────────────────────────────────────────

function cellStyle(cell, pronostic) {
  const active = (
    (cell === '1' && (pronostic === '1' || pronostic === '1X')) ||
    (cell === 'X' && (pronostic === 'X' || pronostic === '1X' || pronostic === 'X2')) ||
    (cell === '2' && (pronostic === '2' || pronostic === 'X2'))
  );
  return active
    ? 'background:rgba(57,255,156,.22);border-color:rgba(57,255,156,.5);'
    : '';
}

// ── Cota efectiva per pronostic ───────────────────────────────────────────────

function cotaEfectiva(match) {
  const p  = match.pronostic;
  const c1 = Number(match.cota_1) || 0;
  const cx = Number(match.cota_x) || 0;
  const c2 = Number(match.cota_2) || 0;

  if (!p) return null;
  if (p === '1') return c1 || null;
  if (p === '2') return c2 || null;
  if (p === 'X') return cx || null;
  // Double chance: 1/(1/cA + 1/cB)
  if (p === '1X' && c1 && cx) return 1 / (1 / c1 + 1 / cx);
  if (p === 'X2' && cx && c2) return 1 / (1 / cx + 1 / c2);
  return null;
}

function formatDataMeci(match) {
  const parts = [];
  if (match.data) parts.push(match.data);
  if (match.ora)  parts.push(match.ora);
  if (match.liga) parts.push(match.liga);
  return parts.join(' · ');
}

// ── BILET AI — greedy, fix pe zi ─────────────────────────────────────────────

const STORAGE_KEY = 'nexas_bilet_ai_v2';

function getBiletAiSalvat() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (e) { return null; }
}

function salvaBiletAi(bilet, updatedAt) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ bilet, updatedAt }));
  } catch (e) {}
}

function genereazaBiletAiGreedy() {
  // Pas 1: doar pronostic "1" sau "2", probabilitate > 60% (cota < 1.67)
  let pool = state.alteMeciuri.filter(m => {
    const c = cotaEfectiva(m);
    return (m.pronostic === '1' || m.pronostic === '2') && c && c < 1.67;
  });

  // Fallback: daca pool mic, includem 1X/X2 si prag mai larg
  if (pool.length < 5) {
    pool = state.alteMeciuri.filter(m => {
      const c = cotaEfectiva(m);
      return m.pronostic && c && c > 1.05 && c < 2.20;
    });
  }

  if (pool.length < 5) return null;

  // Pas 2: sorteaza dupa probabilitate (cota mai mica = mai sigur)
  pool.sort((a, b) => (cotaEfectiva(a) || 99) - (cotaEfectiva(b) || 99));

  // Pas 3: greedy — adauga meciuri pana cota totala e in [10, 20]
  const selected = [];
  let total = 1;

  for (const match of pool) {
    const c = cotaEfectiva(match);
    if (!c) continue;
    selected.push(match);
    total *= c;
    if (total >= 10 && selected.length >= 5) break;
    if (selected.length >= 12) break; // max 12 meciuri
  }

  // Daca tot nu am ajuns la 10, returnez ce am
  if (selected.length < 5) return null;

  return { selected, total };
}

function deschideBiletAi() {
  if (!modal || !ticketBody || !ticketOdd) return;

  const salvat = getBiletAiSalvat();
  if (salvat && salvat.updatedAt === state.alteMeciuriUpdatedAt && salvat.bilet) {
    afiseazaBiletAi(salvat.bilet.selected, salvat.bilet.total);
    return;
  }

  const biletNou = genereazaBiletAiGreedy();
  if (!biletNou) {
    if (ticketEyebrow) ticketEyebrow.textContent = 'Bilet AI';
    ticketBody.innerHTML = '<p class="modal-note">Nu sunt suficiente meciuri cu pronostic clar. Reîncearcă după actualizarea agentului.</p>';
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
      Bilet fix · ${selected.length} meciuri · cele mai sigure pronosticuri
    </p>
    ${selected.map(match => {
      const cota = cotaEfectiva(match);
      return `
        <div class="ticket-item">
          <div>
            <b>${escapeHtml(match.home)} vs ${escapeHtml(match.away)}</b><br>
            <small style="color:var(--muted);">${escapeHtml(formatDataMeci(match))}</small><br>
            <small>
              <span style="color:var(--green);font-weight:700;">${escapeHtml(match.pronostic)}</span>
              · ${escapeHtml(match.motiv || '')}
            </small>
          </div>
          <strong>${cota ? cota.toFixed(2) : '-'}</strong>
        </div>`;
    }).join('')}`;
  ticketOdd.textContent = Number(total).toFixed(2);
  openModal();
}

// ── GENEREAZA BILET — aleatoriu din alte_meciuri, cota 10-20 ─────────────────

function generateTicket() {
  if (!modal || !ticketBody || !ticketOdd) return;
  if (ticketEyebrow) ticketEyebrow.textContent = 'Bilet generat aleatoriu';

  const pool = state.alteMeciuri.filter(m => {
    const c = cotaEfectiva(m);
    return m.pronostic && c && c > 1.05 && c < 5.0;
  });

  if (pool.length < 5) {
    ticketBody.innerHTML = '<p class="modal-note">Nu sunt suficiente meciuri cu pronostic. Reîncearcă după actualizarea agentului.</p>';
    ticketOdd.textContent = '0.00';
    openModal();
    return;
  }

  const MAX_TRIES = 300;
  let best = null;
  let bestDist = Infinity;

  for (let i = 0; i < MAX_TRIES; i++) {
    const count    = 5 + Math.floor(Math.random() * 4);
    const shuffled = [...pool].sort(() => Math.random() - 0.5);
    const selected = shuffled.slice(0, Math.min(count, shuffled.length));
    const total    = selected.reduce((acc, m) => acc * (cotaEfectiva(m) || 1), 1);

    if (total >= 10 && total <= 20) { best = { selected, total }; break; }
    const dist = total < 10 ? 10 - total : total - 20;
    if (dist < bestDist) { bestDist = dist; best = { selected, total }; }
  }

  if (!best) {
    ticketBody.innerHTML = '<p class="modal-note">Nu am putut genera un bilet în intervalul dorit.</p>';
    ticketOdd.textContent = '0.00';
    openModal();
    return;
  }

  const { selected, total } = best;
  ticketBody.innerHTML = `
    <p class="modal-note" style="margin-bottom:16px;">
      Bilet aleatoriu · ${selected.length} meciuri · cota țintă 10–20
    </p>
    ${selected.map(match => {
      const cota = cotaEfectiva(match);
      return `
        <div class="ticket-item">
          <div>
            <b>${escapeHtml(match.home)} vs ${escapeHtml(match.away)}</b><br>
            <small style="color:var(--muted);">${escapeHtml(formatDataMeci(match))}</small><br>
            <small>
              <span style="color:var(--green);font-weight:700;">${escapeHtml(match.pronostic)}</span>
              · ${escapeHtml(match.motiv || '')}
            </small>
          </div>
          <strong>${cota ? cota.toFixed(2) : '-'}</strong>
        </div>`;
    }).join('')}`;
  ticketOdd.textContent = Number(total).toFixed(2);
  openModal();
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

function emptyCard(msg) {
  return `<article class="news-card"><h3>Date indisponibile</h3><p>${escapeHtml(msg)}</p></article>`;
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
