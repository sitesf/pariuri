const state = {
  stiri: [],
  alteMeciuri: [],
  alteMeciuriUpdatedAt: null,
  stiriVisible: 6,
  meciuriVisible: 10,
  activeDay: 'toate',
  selectedMatches: new Map(), // key -> match object
};

const $ = (sel) => document.querySelector(sel);
const newsGrid    = $('#newsGrid');
const matchesGrid = $('#matchesGrid');
const dayFilters  = $('#dayFilters');
const modal       = $('#ticketModal');
const ticketBody  = $('#ticketBody');
const ticketOdd   = $('#ticketOdd');
const ticketEyebrow = $('#ticketEyebrow');
const ticketTitle   = $('#ticketTitle');
const customBar     = $('#customBar');
const customCount   = $('#customCount');
const customOdd     = $('#customOdd');

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
  const [newsData, otherData] = await Promise.all([
    loadJson('stiri.json',        { stiri: [] }),
    loadJson('alte_meciuri.json', { meciuri: [], updated_at: null }),
  ]);

  state.stiri                = Array.isArray(newsData.stiri)    ? newsData.stiri    : [];
  state.alteMeciuri          = Array.isArray(otherData.meciuri) ? otherData.meciuri : [];
  state.alteMeciuriUpdatedAt = otherData.updated_at || null;

  renderNews();
  renderDayFilters();
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
      <span class="pill pill-green">${esc(item.categorie || 'Fotbal')}</span>
      <h3>${esc(item.titlu || 'Stire fara titlu')}</h3>
      <p class="news-summary">${esc(item.rezumat || '')}</p>
      <button class="read-more-btn" type="button">Citeste mai mult</button>
      <div class="news-meta">
        ${(item.surse || []).slice(0,3).map(s=>`<span class="pill">${esc(s)}</span>`).join('')}
        ${item.data_afisaj ? `<span class="pill pill-time">${esc(item.data_afisaj)}</span>` : ''}
      </div>
    </article>`).join('');
  addLoadMoreBtn(newsGrid, 'loadMoreNewsWrap',
    state.stiri.length - state.stiriVisible,
    () => { state.stiriVisible += 6; renderNews(); }
  );
}

// ── Day filter tabs ───────────────────────────────────────────────────────────

function renderDayFilters() {
  if (!dayFilters) return;
  const dates = [...new Set(state.alteMeciuri.map(m => m.data).filter(Boolean))].sort();
  if (!dates.length) { dayFilters.innerHTML = ''; return; }

  const tabs = [
    { key: 'toate', label: 'Toate' },
    ...dates.map(d => ({ key: d, label: formatDayLabel(d) }))
  ];

  dayFilters.innerHTML = tabs.map(t => `
    <button class="day-tab ${t.key === state.activeDay ? 'active' : ''}" data-day="${t.key}">
      ${t.label}
    </button>`).join('');

  dayFilters.querySelectorAll('.day-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      state.activeDay = btn.dataset.day;
      state.meciuriVisible = 10;
      dayFilters.querySelectorAll('.day-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderMatches();
    });
  });
}

function formatDayLabel(dateStr) {
  try {
    const d = new Date(dateStr + 'T12:00:00');
    const today = new Date(); today.setHours(12,0,0,0);
    const tomorrow = new Date(today); tomorrow.setDate(tomorrow.getDate()+1);
    if (d.toDateString() === today.toDateString())    return 'Azi';
    if (d.toDateString() === tomorrow.toDateString()) return 'Mâine';
    return d.toLocaleDateString('ro-RO', { weekday:'short', day:'numeric', month:'short' });
  } catch(e) { return dateStr; }
}

// ── Meciuri cu filtre + selectie + Load More ──────────────────────────────────

function filteredMatches() {
  if (state.activeDay === 'toate') return state.alteMeciuri;
  return state.alteMeciuri.filter(m => m.data === state.activeDay);
}

function matchKey(match) {
  return `${match.home}_${match.away}_${match.data}`;
}

function renderMatches() {
  if (!matchesGrid) return;
  const list = filteredMatches();

  if (!list.length) {
    matchesGrid.innerHTML = emptyCard('Nu exista meciuri pentru ziua selectata.');
    removeBtn('loadMoreMatchesWrap');
    return;
  }

  const visible = list.slice(0, state.meciuriVisible);

  matchesGrid.innerHTML = visible.map((match) => {
    const key = matchKey(match);
    const sel = state.selectedMatches.has(key);
    const c1  = match.cota_1     != null ? Number(match.cota_1).toFixed(2)     : '-';
    const cx  = match.cota_x     != null ? Number(match.cota_x).toFixed(2)     : '-';
    const c2  = match.cota_2     != null ? Number(match.cota_2).toFixed(2)     : '-';
    const p   = match.pronostic  || null;

    return `
      <article class="match-card${sel ? ' is-selected' : ''}" data-key="${esc(key)}">
        <div class="match-top">
          <div>
            <h3>${esc(match.home||'')} vs ${esc(match.away||'')}</h3>
            <div class="league">
              ${esc(match.liga||'')}
              ${match.data ? ' · '+esc(match.data) : ''}
              ${match.ora  ? ' · '+esc(match.ora)  : ''}
            </div>
          </div>
          ${sel ? `<div style="color:var(--green);font-size:20px;font-weight:900;">✓</div>` : ''}
        </div>
        <div class="match-stats">
          <div style="${cellStyle('1',p)}"><span>${esc(c1)}</span><small>1</small></div>
          <div style="${cellStyle('X',p)}"><span>${esc(cx)}</span><small>X</small></div>
          <div style="${cellStyle('2',p)}"><span>${esc(c2)}</span><small>2</small></div>
        </div>
        ${match.cota_gg ? `
        <div class="match-stats" style="margin-top:8px;">
          <div style="${match.pronostic==='GG'?'background:rgba(57,255,156,.22);border-color:rgba(57,255,156,.5);':''}">
            <span>${Number(match.cota_gg).toFixed(2)}</span><small>GG</small>
          </div>
          <div style="${match.pronostic==='Sub 2.5'?'background:rgba(57,255,156,.22);border-color:rgba(57,255,156,.5);':''}">
            <span>${match.cota_under25 ? Number(match.cota_under25).toFixed(2) : '-'}</span><small>Sub 2.5</small>
          </div>
          <div style="${match.pronostic==='Peste 2.5'?'background:rgba(57,255,156,.22);border-color:rgba(57,255,156,.5);':''}">
            <span>${match.cota_over25 ? Number(match.cota_over25).toFixed(2) : '-'}</span><small>Peste 2.5</small>
          </div>
        </div>` : ''}
        ${p ? `
        <div class="match-pick" style="margin-top:10px;">
          <span class="pill pill-green">${esc(p)}</span>
          <small style="color:var(--muted);margin-left:8px;">${esc(match.motiv||'')}</small>
        </div>` : ''}
      </article>`;
  }).join('');

  // Click pe card → toggle selectie
  matchesGrid.querySelectorAll('.match-card').forEach(card => {
    card.addEventListener('click', () => {
      const key = card.dataset.key;
      const match = state.alteMeciuri.find(m => matchKey(m) === key);
      if (!match) return;
      if (state.selectedMatches.has(key)) {
        state.selectedMatches.delete(key);
      } else {
        state.selectedMatches.set(key, match);
      }
      updateCustomBar();
      renderMatches();
    });
  });

  addLoadMoreBtn(matchesGrid, 'loadMoreMatchesWrap',
    list.length - state.meciuriVisible,
    () => { state.meciuriVisible += 10; renderMatches(); }
  );
}

// ── Custom bar (bilet personalizat) ──────────────────────────────────────────

function updateCustomBar() {
  if (!customBar) return;
  const count = state.selectedMatches.size;
  if (count === 0) {
    customBar.classList.remove('visible');
    return;
  }
  customBar.classList.add('visible');
  if (customCount) customCount.textContent = count;

  const total = [...state.selectedMatches.values()]
    .reduce((acc, m) => acc * (Number(m.cota_pronostic) || 1), 1);
  if (customOdd) customOdd.textContent = total.toFixed(2);
}

function deschideCustomBilet() {
  if (!state.selectedMatches.size) return;
  const selected = [...state.selectedMatches.values()];
  const total = selected.reduce((acc, m) => acc * (Number(m.cota_pronostic) || 1), 1);

  setModalHeader('Bilet Personalizat', 'Biletul tau');
  ticketBody.innerHTML = `
    <p class="modal-note" style="margin-bottom:16px;">
      ${selected.length} meciuri selectate de tine
    </p>
    ${selected.map(m => ticketRow(m, Number(m.cota_pronostic) || null)).join('')}`;
  ticketOdd.textContent = total.toFixed(2);
  openModal();
}

// ── Highlight celula ──────────────────────────────────────────────────────────

function cellStyle(cell, p) {
  const active =
    (cell==='1' && (p==='1'||p==='1X')) ||
    (cell==='X' && (p==='X'||p==='1X'||p==='X2')) ||
    (cell==='2' && (p==='2'||p==='X2'));
  return active ? 'background:rgba(57,255,156,.22);border-color:rgba(57,255,156,.5);' : '';
}

// ── Cota efectiva ─────────────────────────────────────────────────────────────

function cotaEf(match) {
  return Number(match.cota_pronostic) || null;
}

function formatInfo(match) {
  return [match.data, match.ora, match.liga].filter(Boolean).join(' · ');
}

function ticketRow(match, cota) {
  return `
    <div class="ticket-item">
      <div>
        <b>${esc(match.home)} vs ${esc(match.away)}</b><br>
        <small style="color:var(--muted);">${esc(formatInfo(match))}</small><br>
        <small>
          <span style="color:var(--green);font-weight:700;">${esc(match.pronostic||'')}</span>
          ${match.motiv ? ' · '+esc(match.motiv) : ''}
        </small>
      </div>
      <strong>${cota ? cota.toFixed(2) : '-'}</strong>
    </div>`;
}

// ── Storage helpers ───────────────────────────────────────────────────────────

function getSaved(key) {
  try { return JSON.parse(localStorage.getItem(key)); } catch(e) { return null; }
}
function setSaved(key, val) {
  try { localStorage.setItem(key, JSON.stringify(val)); } catch(e) {}
}

function getOrGenerate(storageKey, generatorFn) {
  const saved = getSaved(storageKey);
  if (saved && saved.updatedAt === state.alteMeciuriUpdatedAt && saved.bilet) {
    return saved.bilet;
  }
  const bilet = generatorFn();
  if (bilet) setSaved(storageKey, { bilet, updatedAt: state.alteMeciuriUpdatedAt });
  return bilet;
}

// ── BILET AI — selectie aleatorie ponderata, cote pana la 2.00 ───────────────

function genBiletAi() {
  const pool = state.alteMeciuri.filter(m => {
    const c = cotaEf(m);
    return m.pronostic && c && c > 1.05 && c <= 2.00;
  });
  if (pool.length < 5) return null;

  // Ponderam aleator dupa probabilitate
  const MAX_TRIES = 400;
  let best = null, bestDist = Infinity;

  for (let i = 0; i < MAX_TRIES; i++) {
    // Selectie aleatorie ponderata dupa probabilitate
    const shuffled = weightedShuffle(pool);
    const count    = 5 + Math.floor(Math.random() * 4); // 5-8
    const selected = shuffled.slice(0, Math.min(count, shuffled.length));
    const total    = selected.reduce((acc, m) => acc * (cotaEf(m)||1), 1);

    if (total >= 10 && total <= 25) return { selected, total };
    const dist = total < 10 ? 10 - total : total - 25;
    if (dist < bestDist) { bestDist = dist; best = { selected, total }; }
  }
  return best;
}

function weightedShuffle(pool) {
  // Meciuri cu probabilitate mai mare au sansa mai mare sa fie alese
  const weighted = pool.map(m => ({
    m,
    w: (m.probabilitate || 0.5) + Math.random() * 0.3
  }));
  weighted.sort((a,b) => b.w - a.w);
  // Micsora ordinea cu putina aleatorietate
  for (let i = weighted.length-1; i > 0; i--) {
    if (Math.random() < 0.3) {
      const j = Math.floor(Math.random() * (i+1));
      [weighted[i], weighted[j]] = [weighted[j], weighted[i]];
    }
  }
  return weighted.map(x => x.m);
}

function deschideBiletAi() {
  if (!modal) return;
  const bilet = getOrGenerate('nexas_bilet_ai_v4', genBiletAi);
  if (!bilet) {
    setModalHeader('Bilet AI', 'Biletul tau');
    ticketBody.innerHTML = '<p class="modal-note">Nu sunt suficiente meciuri. Reîncearcă după actualizarea agentului (miercuri).</p>';
    ticketOdd.textContent = '0.00';
    openModal(); return;
  }
  setModalHeader('Bilet AI al zilei', 'Biletul tau');
  ticketBody.innerHTML = `
    <p class="modal-note" style="margin-bottom:16px;">
      ${bilet.selected.length} meciuri · cele mai sigure pronosticuri
    </p>
    ${bilet.selected.map(m => ticketRow(m, cotaEf(m))).join('')}`;
  ticketOdd.textContent = Number(bilet.total).toFixed(2);
  openModal();
}

// ── BILET RISC — cote 1.50-2.00, cota totala ~100 ───────────────────────────

function genBiletRisc() {
  const pool = state.alteMeciuri.filter(m => {
    const c = cotaEf(m);
    return m.pronostic && c && c >= 1.50 && c <= 2.00;
  });
  if (pool.length < 3) return null;

  // Sortat dupa probabilitate descrescator — cele mai sigure primele
  const sorted = [...pool].sort((a,b) => (b.probabilitate||0) - (a.probabilitate||0));

  // Greedy: adauga meciuri pana cota totala ajunge la ~100
  const selected = [];
  let total = 1;
  const TARGET = 100;

  for (const match of sorted) {
    const c = cotaEf(match);
    if (!c) continue;
    selected.push(match);
    total *= c;
    if (total >= TARGET) break;
    if (selected.length >= 20) break;
  }

  if (!selected.length) return null;
  return { selected, total };
}

function deschideBiletRisc() {
  if (!modal) return;
  const bilet = getOrGenerate('nexas_bilet_risc_v3', genBiletRisc);
  if (!bilet) {
    setModalHeader('Bilet Risc', 'Biletul tau');
    ticketBody.innerHTML = '<p class="modal-note">Nu sunt suficiente meciuri cu cote 1.50-2.00. Reincerca dupa actualizarea agentului.</p>';
    ticketOdd.textContent = '0.00';
    openModal(); return;
  }
  setModalHeader('Bilet Risc', 'Biletul tau');
  ticketBody.innerHTML = `
    <p class="modal-note" style="margin-bottom:16px;">
      ${bilet.selected.length} meciuri · cote 1.50-2.00 · cota tinta ~100
    </p>
    ${bilet.selected.map(m => ticketRow(m, cotaEf(m))).join('')}`;
  ticketOdd.textContent = Number(bilet.total).toFixed(2);
  openModal();
}

// ── COTA 2 — 1-3 meciuri, cumulat ~2.00 ─────────────────────────────────────

function genCota2() {
  // Pool: pronosticuri foarte sigure (cota < 1.50)
  const pool = state.alteMeciuri.filter(m => {
    const c = cotaEf(m);
    return (m.pronostic === '1' || m.pronostic === '2') && c && c < 1.50;
  });

  if (!pool.length) return null;

  // Sortat dupa probabilitate
  const sorted = [...pool].sort((a,b) => (b.probabilitate||0) - (a.probabilitate||0));

  // Gasim combinatia de 1-3 meciuri cu total cat mai aproape de 2.00
  let best = null, bestDist = Infinity;

  for (let i = 0; i < Math.min(sorted.length, 10); i++) {
    // 1 meci
    const c1 = cotaEf(sorted[i]);
    if (c1) {
      const d1 = Math.abs(c1 - 2.0);
      if (d1 < bestDist) { bestDist=d1; best={ selected:[sorted[i]], total:c1 }; }
    }
    // 2 meciuri
    for (let j = i+1; j < Math.min(sorted.length, 10); j++) {
      const c2 = cotaEf(sorted[j]);
      if (c1 && c2) {
        const t2 = c1*c2;
        const d2 = Math.abs(t2 - 2.0);
        if (d2 < bestDist) { bestDist=d2; best={ selected:[sorted[i],sorted[j]], total:t2 }; }
      }
      // 3 meciuri
      for (let k = j+1; k < Math.min(sorted.length, 10); k++) {
        const c3 = cotaEf(sorted[k]);
        if (c1 && c2 && c3) {
          const t3 = c1*c2*c3;
          const d3 = Math.abs(t3 - 2.0);
          if (d3 < bestDist) { bestDist=d3; best={ selected:[sorted[i],sorted[j],sorted[k]], total:t3 }; }
        }
      }
    }
  }
  return best;
}

function deschideCota2() {
  if (!modal) return;
  const bilet = getOrGenerate('nexas_cota2_v2', genCota2);
  if (!bilet) {
    setModalHeader('Cota 2', 'Biletul tau');
    ticketBody.innerHTML = '<p class="modal-note">Nu sunt suficiente meciuri foarte sigure. Reîncearcă după actualizarea agentului.</p>';
    ticketOdd.textContent = '0.00';
    openModal(); return;
  }
  setModalHeader('Cota 2', 'Biletul tau');
  ticketBody.innerHTML = `
    <p class="modal-note" style="margin-bottom:16px;">
      ${bilet.selected.length} ${bilet.selected.length===1?'meci':'meciuri'} · cele mai sigure · cotă totală ~2.00
    </p>
    ${bilet.selected.map(m => ticketRow(m, cotaEf(m))).join('')}`;
  ticketOdd.textContent = Number(bilet.total).toFixed(2);
  openModal();
}

// ── GENEREAZA BILET — aleatoriu din alteMeciuri, cota 10-20 ──────────────────

function generateTicket() {
  if (!modal) return;
  setModalHeader('Bilet generat aleatoriu', 'Biletul tau');

  const pool = state.alteMeciuri.filter(m => {
    const c = cotaEf(m);
    return m.pronostic && c && c > 1.05 && c < 5.0;
  });

  if (pool.length < 5) {
    ticketBody.innerHTML = '<p class="modal-note">Nu sunt suficiente meciuri cu pronostic. Reîncearcă după actualizarea agentului.</p>';
    ticketOdd.textContent = '0.00';
    openModal(); return;
  }

  const MAX_TRIES = 300;
  let best = null, bestDist = Infinity;

  for (let i = 0; i < MAX_TRIES; i++) {
    const count    = 5 + Math.floor(Math.random() * 4);
    const shuffled = [...pool].sort(() => Math.random() - 0.5);
    const selected = shuffled.slice(0, Math.min(count, shuffled.length));
    const total    = selected.reduce((acc, m) => acc * (cotaEf(m)||1), 1);

    if (total >= 10 && total <= 20) { best = { selected, total }; break; }
    const dist = total < 10 ? 10 - total : total - 20;
    if (dist < bestDist) { bestDist = dist; best = { selected, total }; }
  }

  if (!best) {
    ticketBody.innerHTML = '<p class="modal-note">Nu am putut genera un bilet în intervalul dorit.</p>';
    ticketOdd.textContent = '0.00';
    openModal(); return;
  }

  ticketBody.innerHTML = `
    <p class="modal-note" style="margin-bottom:16px;">
      ${best.selected.length} meciuri · cota țintă 10–20
    </p>
    ${best.selected.map(m => ticketRow(m, cotaEf(m))).join('')}`;
  ticketOdd.textContent = Number(best.total).toFixed(2);
  openModal();
}

// ── Modal ─────────────────────────────────────────────────────────────────────

function setModalHeader(eyebrow, title) {
  if (ticketEyebrow) ticketEyebrow.textContent = eyebrow;
  if (ticketTitle)   ticketTitle.textContent   = title;
}

function openModal() {
  modal.classList.add('is-open');
  modal.setAttribute('aria-hidden', 'false');
}

function closeModal() {
  modal.classList.remove('is-open');
  modal.setAttribute('aria-hidden', 'true');
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

// ── Utils ─────────────────────────────────────────────────────────────────────

function emptyCard(msg) {
  return `<article class="news-card"><h3>Date indisponibile</h3><p>${esc(msg)}</p></article>`;
}

function esc(v) {
  return String(v ?? '')
    .replaceAll('&','&amp;').replaceAll('<','&lt;')
    .replaceAll('>','&gt;').replaceAll('"','&quot;')
    .replaceAll("'",'&#039;');
}

// ── Events ────────────────────────────────────────────────────────────────────

['#makeTicketTop','#makeTicketHero','#makeTicketMain'].forEach(sel => {
  const btn = $(sel); if (btn) btn.addEventListener('click', generateTicket);
});

const biletAiBtn   = $('#biletAiBtn');   if (biletAiBtn)   biletAiBtn.addEventListener('click',   deschideBiletAi);
const biletRiscBtn = $('#biletRiscBtn'); if (biletRiscBtn) biletRiscBtn.addEventListener('click', deschideBiletRisc);
const cota2Btn     = $('#cota2Btn');     if (cota2Btn)     cota2Btn.addEventListener('click',     deschideCota2);

const customTicketBtn   = $('#customTicketBtn');   if (customTicketBtn)   customTicketBtn.addEventListener('click', deschideCustomBilet);
const clearSelectionBtn = $('#clearSelectionBtn'); if (clearSelectionBtn) clearSelectionBtn.addEventListener('click', () => {
  state.selectedMatches.clear();
  updateCustomBar();
  renderMatches();
});

document.querySelectorAll('[data-close-modal]').forEach(el => el.addEventListener('click', closeModal));
document.addEventListener('keydown', e => { if (e.key==='Escape') closeModal(); });

document.addEventListener('click', e => {
  const btn = e.target.closest('.read-more-btn');
  if (!btn) return;
  const card = btn.closest('.news-card');
  if (!card) return;
  card.classList.toggle('is-expanded');
  btn.textContent = card.classList.contains('is-expanded') ? 'Arata mai putin' : 'Citeste mai mult';
});

init();
