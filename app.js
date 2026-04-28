const state = {
  stiri: [],
  meciuri: [],
  meta: {}
};

const $ = (selector) => document.querySelector(selector);
const newsGrid = $('#newsGrid');
const matchesGrid = $('#matchesGrid');
const modal = $('#ticketModal');
const ticketBody = $('#ticketBody');
const ticketOdd = $('#ticketOdd');

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
    loadJson('meciuri.json', { updated_at: null, meciuri: [] })
  ]);

  state.stiri = Array.isArray(newsData.stiri) ? newsData.stiri : [];
  state.meciuri = Array.isArray(matchesData.meciuri) ? matchesData.meciuri : [];
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
    newsGrid.innerHTML = emptyCard('Nu exista stiri in stiri.json. Ruleaza workflow-ul de stiri.');
    return;
  }

  newsGrid.innerHTML = state.stiri.map((item, index) => `
    <article class="news-card" style="animation-delay:${index * 80}ms">
      <span class="pill pill-green">${escapeHtml(item.categorie || 'Sport')}</span>
      <h3>${escapeHtml(item.titlu || 'Stire fara titlu')}</h3>
      <p>${escapeHtml(item.rezumat || '')}</p>
      <div class="news-meta">
        ${(item.surse || []).slice(0, 3).map(source => `<span class="pill">${escapeHtml(source)}</span>`).join('')}
      </div>
    </article>
  `).join('');
}

function renderMatches() {
  if (!state.meciuri.length) {
    matchesGrid.innerHTML = emptyCard('Nu exista meciuri in meciuri.json. Ruleaza workflow-ul de meciuri.');
    return;
  }

  matchesGrid.innerHTML = state.meciuri.map((match) => `
    <article class="match-card">
      <div class="match-top">
        <div>
          <h3>${escapeHtml(match.home || '')} vs ${escapeHtml(match.away || '')}</h3>
          <div class="league">${escapeHtml(match.liga || '')} · ${escapeHtml(match.ora || '')}</div>
        </div>
        <div class="odd-box"><small>cota</small>${Number(match.cota || 0).toFixed(2)}</div>
      </div>
      <div class="match-pick">Pronostic: ${escapeHtml(match.pronostic || '')}</div>
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
  const pool = [...state.meciuri].filter(match => Number(match.cota) > 1);
  if (pool.length < 5) {
    ticketBody.innerHTML = '<p class="modal-note">Ai nevoie de minimum 5 meciuri in meciuri.json pentru a genera biletul.</p>';
    ticketOdd.textContent = '0.00';
    openModal();
    return;
  }

  const selected = shuffle(pool).slice(0, 5);
  const totalOdd = selected.reduce((total, match) => total * Number(match.cota || 1), 1);

  ticketBody.innerHTML = selected.map(match => `
    <div class="ticket-item">
      <div>
        <b>${escapeHtml(match.home)} vs ${escapeHtml(match.away)}</b><br>
        <small>${escapeHtml(match.pronostic)} · ${Number(match.scor_incredere || 0)}%</small>
      </div>
      <strong>${Number(match.cota || 0).toFixed(2)}</strong>
    </div>
  `).join('');

  ticketOdd.textContent = totalOdd.toFixed(2);
  openModal();
}

function shuffle(items) {
  return items
    .map(value => ({ value, sort: Math.random() }))
    .sort((a, b) => a.sort - b.sort)
    .map(({ value }) => value);
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
