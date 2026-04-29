const state = {
  stiri: [],
  meciuri: [],
  alteMeciuri: [],
  bilete: [],
  meta: {}
};

const $ = (selector) => document.querySelector(selector);
const newsGrid = $('#newsGrid');
const matchesGrid = $('#matchesGrid');
const otherMatchesGrid = $('#otherMatchesGrid');
const modal = $('#ticketModal');
const ticketBody = $('#ticketBody');
const ticketOdd = $('#ticketOdd');

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
  const [newsData, matchesData, otherData] = await Promise.all([
    loadJson('stiri.json', { stiri: [] }),
    loadJson('meciuri.json', { meciuri: [], bilete_sugerate: [] }),
    loadJson('alte_meciuri.json', { meciuri: [] })
  ]);

  state.stiri = Array.isArray(newsData.stiri) ? newsData.stiri : [];
  state.meciuri = Array.isArray(matchesData.meciuri) ? matchesData.meciuri : [];
  state.bilete = Array.isArray(matchesData.bilete_sugerate) ? matchesData.bilete_sugerate : [];
  state.alteMeciuri = Array.isArray(otherData.meciuri) ? otherData.meciuri : [];

  renderNews();
  renderMatches();
  renderOtherMatches();
}

function renderNews() {
  if (!newsGrid) return;

  if (!state.stiri.length) {
    newsGrid.innerHTML = emptyCard('Nu exista stiri disponibile momentan.');
    return;
  }

  newsGrid.innerHTML = state.stiri.map((item) => `
    <article class="news-card">
      <span class="pill pill-green">${escapeHtml(item.categorie || 'Fotbal')}</span>
      <h3>${escapeHtml(item.titlu || 'Stire fara titlu')}</h3>
      <p class="news-summary">${escapeHtml(item.rezumat || '')}</p>
      <button class="read-more-btn" type="button">Citeste mai mult</button>
      <div class="news-meta">
        ${(item.surse || []).slice(0, 3).map(source => `<span class="pill">${escapeHtml(source)}</span>`).join('')}
        ${item.data_afisaj ? `<span class="pill pill-time">${escapeHtml(item.data_afisaj)}</span>` : ''}
      </div>
    </article>
  `).join('');
}

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

function renderOtherMatches() {
  if (!otherMatchesGrid) return;

  if (!state.alteMeciuri.length) {
    otherMatchesGrid.innerHTML = emptyCard('Nu exista alte meciuri disponibile momentan.');
    return;
  }

  otherMatchesGrid.innerHTML = state.alteMeciuri.map((match) => {
    const cota1 = match.cota_1 ?? match.odds_1 ?? match['1'] ?? '-';
    const cotax = match.cota_x ?? match.odds_x ?? match.X ?? '-';
    const cota2 = match.cota_2 ?? match.odds_2 ?? match['2'] ?? '-';

    return `
      <article class="match-card other-match-card">
        <div class="match-top">
          <div>
            <h3>${escapeHtml(match.home || '')} vs ${escapeHtml(match.away || '')}</h3>
            <div class="league">
              ${escapeHtml(match.liga || '')}
              ${match.data ? ' · ' + escapeHtml(match.data) : ''}
              ${match.ora ? ' · ' + escapeHtml(match.ora) : ''}
            </div>
          </div>
        </div>

        <div class="match-stats">
          <div><span>${escapeHtml(cota1)}</span><small>1</small></div>
          <div><span>${escapeHtml(cotax)}</span><small>X</small></div>
          <div><span>${escapeHtml(cota2)}</span><small>2</small></div>
        </div>
      </article>
    `;
  }).join('');
}

function generateTicket() {
  if (!modal || !ticketBody || !ticketOdd) return;

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

function showTicketSelector() {
  const buttons = state.bilete.map((bilet, index) => `
    <button class="ticket-tab ${index === 0 ? 'active' : ''}" data-bilet-idx="${index}">
      ${escapeHtml(bilet.nume || 'Bilet')}<br>
      <small>cota ${Number(bilet.cota_totala || 0).toFixed(2)} · ${Number(bilet.incredere_medie || 0).toFixed(0)}%</small>
    </button>
  `).join('');

  ticketBody.innerHTML = `
    <div class="ticket-tabs">${buttons}</div>
    <div id="ticketContent"></div>
  `;

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

  const meciuriBilet = (bilet.fixture_ids || [])
    .map(id => state.meciuri.find(m => m.fixture_id === id))
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

['#makeTicketTop', '#makeTicketHero', '#makeTicketMain'].forEach(selector => {
  const button = $(selector);
  if (button) button.addEventListener('click', generateTicket);
});

document.querySelectorAll('[data-close-modal]').forEach(el => {
  el.addEventListener('click', closeModal);
});

document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeModal();
});

document.addEventListener('click', event => {
  const button = event.target.closest('.read-more-btn');
  if (!button) return;

  const card = button.closest('.news-card');
  if (!card) return;

  card.classList.toggle('is-expanded');
  button.textContent = card.classList.contains('is-expanded')
    ? 'Arata mai putin'
    : 'Citeste mai mult';
});

init();
