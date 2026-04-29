const state = {
  stiri: [],
  meciuri: [],
  bilete: [],
  meta: {}
};

const $ = (selector) => document.querySelector(selector);
const newsGrid = $('#newsGrid');
const matchesGrid = $('#matchesGrid');
const modal = $('#ticketModal');
const ticketBody = $('#ticketBody');
const ticketOdd = $('#ticketOdd');

const LUNI_RO = [
  'ianuarie', 'februarie', 'martie', 'aprilie', 'mai', 'iunie',
  'iulie', 'august', 'septembrie', 'octombrie', 'noiembrie', 'decembrie'
];

function formatDate(value) {
  if (!value) return 'Necunoscut';
  try {
    return new Intl.DateTimeFormat('ro-RO', {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function formatDayHeader(isoDate) {
  // isoDate poate fi "2026-04-29T10:00:00+00:00" sau "2026-04-29"
  if (!isoDate) return 'Data necunoscuta';
  try {
    const d = new Date(isoDate);
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);

    const sameDay = (a, b) =>
      a.getFullYear() === b.getFullYear() &&
      a.getMonth() === b.getMonth() &&
      a.getDate() === b.getDate();

    let prefix = '';
    if (sameDay(d, today)) prefix = 'Astazi · ';
    else if (sameDay(d, yesterday)) prefix = 'Ieri · ';

    return `${prefix}${d.getDate()} ${LUNI_RO[d.getMonth()]} ${d.getFullYear()}`;
  } catch {
    return isoDate;
  }
}

function dayKey(isoDate) {
  // Cheie YYYY-MM-DD pentru grupare
  if (!isoDate) return '0000-00-00';
  try {
    return new Date(isoDate).toISOString().split('T')[0];
  } catch {
    return String(isoDate).split('T')[0];
  }
}

async function loadJson(path, fallback) {
  try {
    const response = await fetch(`${path}?v=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Nu pot incarca ${path}`);
    return await response.json();
  } catch (error) {
    console.warn(error.message);
    return fallback;
  }
}

async function init() {
  const [newsData, matchesData] = await Promise.all([
    loadJson('stiri.json', { updated_at: null, stiri: [] }),
    loadJson('meciuri.json', { updated_at: null, meciuri: [], bilete_sugerate: [] })
  ]);

  state.stiri = Array.isArray(newsData.stiri) ? newsData.stiri : [];
  state.meciuri = Array.isArray(matchesData.meciuri) ? matchesData.meciuri : [];
  state.bilete = Array.isArray(matchesData.bilete_sugerate) ? matchesData.bilete_sugerate : [];
  state.meta = {
    newsUpdated: newsData.updated_at,
    matchesUpdated: matchesData.updated_at
  };

  renderNews();
  renderMatches();
  renderStats();
}

function renderStats() {
  $('#newsCount').textContent = state.stiri.length;
  $('#matchesCount').textContent = state.meciuri.length;

  const avg = state.meciuri.length
    ? Math.round(state.meciuri.reduce((sum, item) => sum + Number(item.scor_incredere || 0), 0) / state.meciuri.length)
    : 0;

  $('#avgConfidence').textContent = `${avg}%`;
  $('#lastUpdate').textContent = formatDate(state.meta.matchesUpdated || state.meta.newsUpdated);
}

function renderNews() {
  if (!state.stiri.length) {
    newsGrid.innerHTML = emptyCard('Pregatim selectia zilei. Stirile sportive apar aici de doua ori pe zi.');
    return;
  }

  // Grupare pe zile (cheia: YYYY-MM-DD din data_publicare; fallback la updated_at)
  const groups = {};
  state.stiri.forEach(item => {
    const dateField = item.data_publicare || state.meta.newsUpdated || new Date().toISOString();
    const key = dayKey(dateField);
    if (!groups[key]) groups[key] = { iso: dateField, items: [] };
    groups[key].items.push(item);
  });

  // Sortare zile descrescator (cele mai recente sus)
  const sortedKeys = Object.keys(groups).sort().reverse();

  let html = '';
  let animIndex = 0;

  sortedKeys.forEach(key => {
    const grp = groups[key];
    html += `
      <div class="news-day-header">
        <h3>${escapeHtml(formatDayHeader(grp.iso))}</h3>
        <span class="pill pill-green">${grp.items.length} ${grp.items.length === 1 ? 'stire' : 'stiri'}</span>
      </div>
      <div class="news-day-group">
        ${grp.items.map(item => {
          const card = `
            <article class="news-card" style="animation-delay:${animIndex * 60}ms">
              <span class="pill pill-green">${escapeHtml(item.categorie || 'Fotbal')}</span>
              <h3>${escapeHtml(item.titlu || 'Stire fara titlu')}</h3>
              <p>${escapeHtml(item.rezumat || '')}</p>
              <div class="news-meta">
                ${(item.surse || []).slice(0, 3).map(source => `<span class="pill">${escapeHtml(source)}</span>`).join('')}
                ${item.data_afisaj ? `<span class="pill pill-time">${escapeHtml(item.data_afisaj)}</span>` : ''}
              </div>
            </article>
          `;
          animIndex++;
          return card;
        }).join('')}
      </div>
    `;
  });

  newsGrid.innerHTML = html;
}

function renderMatches() {
  if (!state.meciuri.length) {
    matchesGrid.innerHTML = emptyCard('NEXAS AI nu a gasit evenimente care sa treaca de filtrul nostru strict de incredere. Calitatea primeaza.');
    return;
  }

  matchesGrid.innerHTML = state.meciuri.map((match) => `
    <article class="match-card">
      <div class="match-top">
        <div>
          <h3>${escapeHtml(match.home || '')} vs ${escapeHtml(match.away || '')}</h3>
          <div class="league">${escapeHtml(match.liga || '')} · ${escapeHtml(match.ora || '')}${match.data ? ' · ' + escapeHtml(match.data) : ''}</div>
        </div>
        <div class="odd-box"><small>cota</small>${Number(match.cota || 0).toFixed(2)}</div>
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

function emptyCard(message) {
  return `<article class="news-card"><h3>Date indisponibile</h3><p>${escapeHtml(message)}</p></article>`;
}

function generateTicket() {
  // 1) Daca avem bilete pre-calculate de scriptul Python, folosim biletul "Bilet sigur"
  if (state.bilete && state.bilete.length > 0) {
    showTicketSelector();
    return;
  }

  // 2) Fallback: folosim primele 5 meciuri sortate dupa incredere (NU random!)
  const pool = [...state.meciuri].filter(match => Number(match.cota) > 1);
  if (pool.length < 3) {
    ticketBody.innerHTML = '<p class="modal-note">Ai nevoie de minimum 3 meciuri pentru a genera biletul.</p>';
    ticketOdd.textContent = '0.00';
    openModal();
    return;
  }

  const sorted = pool.sort((a, b) => Number(b.scor_incredere || 0) - Number(a.scor_incredere || 0));
  const selected = sorted.slice(0, Math.min(5, sorted.length));
  renderTicket('Bilet automat', selected);
}

function showTicketSelector() {
  // Afiseaza cele 3 bilete sugerate ca tab-uri
  const buttons = state.bilete.map((bilet, idx) => `
    <button class="ticket-tab ${idx === 0 ? 'active' : ''}" data-bilet-idx="${idx}">
      ${escapeHtml(bilet.nume)}<br>
      <small>cota ${Number(bilet.cota_totala || 0).toFixed(2)} · ${Number(bilet.incredere_medie || 0).toFixed(0)}%</small>
    </button>
  `).join('');

  ticketBody.innerHTML = `
    <div class="ticket-tabs">${buttons}</div>
    <div id="ticketContent"></div>
  `;

  // Event listeners pentru tab-uri
  document.querySelectorAll('.ticket-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.ticket-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const idx = parseInt(btn.dataset.beletIdx || btn.dataset.biletIdx, 10);
      showBiletContent(idx);
    });
  });

  // Default: primul bilet
  showBiletContent(0);
  openModal();
}

function showBiletContent(idx) {
  const bilet = state.bilete[idx];
  if (!bilet) return;

  const meciuriBilet = bilet.fixture_ids
    .map(fid => state.meciuri.find(m => m.fixture_id === fid))
    .filter(Boolean);

  const content = $('#ticketContent');
  if (!content) return;

  content.innerHTML = meciuriBilet.map(match => `
    <div class="ticket-item">
      <div>
        <b>${escapeHtml(match.home)} vs ${escapeHtml(match.away)}</b><br>
        <small>${escapeHtml(match.tip_pariu || '')} · ${escapeHtml(match.pronostic || '')} · ${Number(match.scor_incredere || 0)}%</small>
      </div>
      <strong>${Number(match.cota || 0).toFixed(2)}</strong>
    </div>
  `).join('');

  ticketOdd.textContent = Number(bilet.cota_totala || 0).toFixed(2);
}

function renderTicket(label, selected) {
  const totalOdd = selected.reduce((total, match) => total * Number(match.cota || 1), 1);

  ticketBody.innerHTML = `
    <p class="modal-note"><strong>${escapeHtml(label)}</strong></p>
    ${selected.map(match => `
      <div class="ticket-item">
        <div>
          <b>${escapeHtml(match.home)} vs ${escapeHtml(match.away)}</b><br>
          <small>${escapeHtml(match.tip_pariu || '')} · ${escapeHtml(match.pronostic || '')} · ${Number(match.scor_incredere || 0)}%</small>
        </div>
        <strong>${Number(match.cota || 0).toFixed(2)}</strong>
      </div>
    `).join('')}
  `;

  ticketOdd.textContent = totalOdd.toFixed(2);
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

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

['#makeTicketTop', '#makeTicketHero', '#makeTicketMain'].forEach(selector => {
  const button = $(selector);
  if (button) button.addEventListener('click', generateTicket);
});

document.querySelectorAll('[data-close-modal]').forEach(el => el.addEventListener('click', closeModal));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeModal();
});

init();
