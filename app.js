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

// Carusel: timer activ pentru ziua "Astazi"
let activeCarousel = null;
const CAROUSEL_INTERVAL = 5000; // 5 secunde
const CAROUSEL_MIN_NEWS = 4;    // sub 4 stiri intr-o zi -> fara carusel

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

function isToday(isoDate) {
  if (!isoDate) return false;
  try {
    const d = new Date(isoDate);
    const today = new Date();
    return d.getFullYear() === today.getFullYear() &&
           d.getMonth() === today.getMonth() &&
           d.getDate() === today.getDate();
  } catch {
    return false;
  }
}

function dayKey(isoDate) {
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

// ============================================================
// RENDER STIRI - cu carusel pe zile
// ============================================================

function renderNews() {
  // Cleanup carusele vechi
  stopActiveCarousel();

  if (!state.stiri.length) {
    newsGrid.innerHTML = emptyCard('Pregatim selectia zilei. Stirile sportive apar aici de doua ori pe zi.');
    return;
  }

  // Grupare pe zile
  const groups = {};
  state.stiri.forEach(item => {
    const dateField = item.data_publicare || state.meta.newsUpdated || new Date().toISOString();
    const key = dayKey(dateField);
    if (!groups[key]) groups[key] = { iso: dateField, items: [] };
    groups[key].items.push(item);
  });

  const sortedKeys = Object.keys(groups).sort().reverse();

  let html = '';
  sortedKeys.forEach((key, dayIdx) => {
    const grp = groups[key];
    const isCurrentDay = isToday(grp.iso);
    const useCarousel = grp.items.length >= CAROUSEL_MIN_NEWS;
    const carouselId = `carousel-${key}`;

    html += `
      <div class="news-day-header">
        <h3>${escapeHtml(formatDayHeader(grp.iso))}</h3>
        <span class="pill pill-green">${grp.items.length} ${grp.items.length === 1 ? 'stire' : 'stiri'}</span>
      </div>
    `;

    if (useCarousel) {
      html += renderCarousel(carouselId, grp.items, isCurrentDay);
    } else {
      // Sub prag: grila simpla cu fade-in cascada
      html += `<div class="news-day-group">${grp.items.map((item, i) =>
        renderNewsCard(item, i)
      ).join('')}</div>`;
    }
  });

  newsGrid.innerHTML = html;

  // Activeaza caruselele
  document.querySelectorAll('.news-carousel').forEach(carousel => {
    initCarousel(carousel);
  });
}

function renderCarousel(carouselId, items, isAutoplay) {
  const cards = items.map((item, i) => renderNewsCard(item, i, true)).join('');
  return `
    <div class="news-carousel" id="${carouselId}" data-autoplay="${isAutoplay ? '1' : '0'}">
      <button class="carousel-arrow carousel-arrow-left" aria-label="Anterior">‹</button>

      <div class="carousel-viewport">
        <div class="carousel-track">${cards}</div>
      </div>

      <button class="carousel-arrow carousel-arrow-right" aria-label="Urmator">›</button>

      <div class="carousel-indicators"></div>

      ${isAutoplay ? '<div class="carousel-progress"><div class="carousel-progress-bar"></div></div>' : ''}
    </div>
  `;
}

function renderNewsCard(item, index, inCarousel = false) {
  const cls = inCarousel ? 'news-card carousel-card' : 'news-card';
  const delay = inCarousel ? 0 : index * 60;

  return `
    <article class="${cls}" style="animation-delay:${delay}ms">
      <span class="pill pill-green">${escapeHtml(item.categorie || 'Fotbal')}</span>

      <h3>${escapeHtml(item.titlu || 'Stire fara titlu')}</h3>

      <p class="news-summary">${escapeHtml(item.rezumat || '')}</p>

      <button class="read-more-btn" type="button">
        Citeste mai mult
      </button>

      <div class="news-meta">
        ${(item.surse || []).slice(0, 3).map(source => `<span class="pill">${escapeHtml(source)}</span>`).join('')}
        ${item.data_afisaj ? `<span class="pill pill-time">${escapeHtml(item.data_afisaj)}</span>` : ''}
      </div>
    </article>
  `;
}

// ============================================================
// LOGICA CARUSEL
// ============================================================

function getCardsPerView() {
  const w = window.innerWidth;
  if (w < 640) return 1;
  if (w < 1024) return 2;
  return 3;
}

function initCarousel(carousel) {
  const track = carousel.querySelector('.carousel-track');
  const cards = track.querySelectorAll('.carousel-card');
  const indicatorsBox = carousel.querySelector('.carousel-indicators');
  const arrowLeft = carousel.querySelector('.carousel-arrow-left');
  const arrowRight = carousel.querySelector('.carousel-arrow-right');
  const progressBar = carousel.querySelector('.carousel-progress-bar');
  const isAutoplay = carousel.dataset.autoplay === '1';

  let cardsPerView = getCardsPerView();
  let totalPages = Math.max(1, Math.ceil(cards.length / cardsPerView));
  let currentPage = 0;
  let autoTimer = null;
  let progressTimer = null;
  let isPaused = false;
  let touchStartX = 0;

  // Construire indicatori
  function buildIndicators() {
    indicatorsBox.innerHTML = '';
    for (let i = 0; i < totalPages; i++) {
      const dot = document.createElement('button');
      dot.className = 'carousel-dot';
      if (i === currentPage) dot.classList.add('active');
      dot.setAttribute('aria-label', `Pagina ${i + 1}`);
      dot.addEventListener('click', () => goToPage(i, true));
      indicatorsBox.appendChild(dot);
    }
  }

  function updateIndicators() {
    indicatorsBox.querySelectorAll('.carousel-dot').forEach((dot, i) => {
      dot.classList.toggle('active', i === currentPage);
    });
  }

  function goToPage(page, userInteraction = false) {
    currentPage = ((page % totalPages) + totalPages) % totalPages;
    const cardWidth = cards[0] ? cards[0].getBoundingClientRect().width : 0;
    const gap = 16;
    const offset = currentPage * cardsPerView * (cardWidth + gap);
    track.style.transform = `translateX(-${offset}px)`;
    updateIndicators();

    if (userInteraction && isAutoplay) {
      restartAutoplay();
    }
  }

  function next() { goToPage(currentPage + 1); }
  function prev() { goToPage(currentPage - 1); }

  function startAutoplay() {
    if (!isAutoplay || isPaused) return;
    stopAutoplay();
    if (progressBar) {
      progressBar.style.transition = 'none';
      progressBar.style.width = '0%';
      // Force reflow
      void progressBar.offsetWidth;
      progressBar.style.transition = `width ${CAROUSEL_INTERVAL}ms linear`;
      progressBar.style.width = '100%';
    }
    autoTimer = setTimeout(() => {
      next();
      startAutoplay();
    }, CAROUSEL_INTERVAL);
  }

  function stopAutoplay() {
    if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    if (progressBar) {
      progressBar.style.transition = 'none';
      progressBar.style.width = '0%';
    }
  }

  function restartAutoplay() {
    stopAutoplay();
    if (!isPaused) startAutoplay();
  }

  // Recalculare la resize
  function handleResize() {
    const newCardsPerView = getCardsPerView();
    if (newCardsPerView !== cardsPerView) {
      cardsPerView = newCardsPerView;
      totalPages = Math.max(1, Math.ceil(cards.length / cardsPerView));
      currentPage = Math.min(currentPage, totalPages - 1);
      buildIndicators();
      goToPage(currentPage);
    } else {
      goToPage(currentPage);
    }
  }

  // Event listeners
  arrowLeft.addEventListener('click', () => { prev(); restartAutoplay(); });
  arrowRight.addEventListener('click', () => { next(); restartAutoplay(); });

  carousel.addEventListener('mouseenter', () => {
    isPaused = true;
    stopAutoplay();
  });
  carousel.addEventListener('mouseleave', () => {
    isPaused = false;
    if (isAutoplay) startAutoplay();
  });

  // Swipe pe mobile
  carousel.addEventListener('touchstart', (e) => {
    touchStartX = e.touches[0].clientX;
    isPaused = true;
    stopAutoplay();
  }, { passive: true });

  carousel.addEventListener('touchend', (e) => {
    const touchEndX = e.changedTouches[0].clientX;
    const diff = touchStartX - touchEndX;
    if (Math.abs(diff) > 50) {
      if (diff > 0) next();
      else prev();
    }
    setTimeout(() => {
      isPaused = false;
      if (isAutoplay) startAutoplay();
    }, 1500);
  }, { passive: true });

  window.addEventListener('resize', handleResize);

  // Stocheaza referinte pentru cleanup
  carousel._cleanup = () => {
    stopAutoplay();
    window.removeEventListener('resize', handleResize);
  };

  // Init
  buildIndicators();
  goToPage(0);
  if (isAutoplay) {
    activeCarousel = carousel;
    startAutoplay();
  }
}

function stopActiveCarousel() {
  document.querySelectorAll('.news-carousel').forEach(c => {
    if (c._cleanup) c._cleanup();
  });
  activeCarousel = null;
}

// ============================================================
// RENDER MECIURI
// ============================================================

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

// ============================================================
// MODAL BILETE
// ============================================================

function generateTicket() {
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

  const sorted = pool.sort((a, b) => Number(b.scor_incredere || 0) - Number(a.scor_incredere || 0));
  const selected = sorted.slice(0, Math.min(5, sorted.length));
  renderTicket('Bilet automat', selected);
}

function showTicketSelector() {
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

  document.querySelectorAll('.ticket-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.ticket-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const idx = parseInt(btn.dataset.biletIdx, 10);
      showBiletContent(idx);
    });
  });

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
document.addEventListener('click', function (event) {
  const button = event.target.closest('.read-more-btn');
  if (!button) return;

  const card = button.closest('.news-card');
  if (!card) return;

  card.classList.toggle('is-expanded');

  button.textContent = card.classList.contains('is-expanded')
    ? 'Arata mai putin'
    : 'Citeste mai mult';
});
