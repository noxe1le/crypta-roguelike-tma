/* Крипта — клиент Mini App. Без фреймворков: состояние приходит с сервера,
   здесь только отрисовка и анимации. */

const $ = (id) => document.getElementById(id);

const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
if (tg) {
  tg.ready();
  tg.expand();
  try {
    tg.setHeaderColor('#0a0910');
    tg.setBackgroundColor('#0a0910');
  } catch (e) { /* старые клиенты */ }
}

const DEV_ID = new URLSearchParams(location.search).get('dev');

function headers() {
  const h = { 'Content-Type': 'application/json' };
  if (tg && tg.initData) h['X-Init-Data'] = tg.initData;
  else if (DEV_ID) h['X-Dev-Id'] = DEV_ID;
  return h;
}

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { ...headers(), ...(opts.headers || {}) } });
  if (!res.ok) {
    let detail = 'Что-то пошло не так';
    try { detail = (await res.json()).detail || detail; } catch (e) { /* не JSON */ }
    throw new Error(detail);
  }
  return res.json();
}

/* ------------------------------------------------------------------ */
/* отрисовка                                                          */
/* ------------------------------------------------------------------ */
let S = null;
let busy = false;
let lastPhase = null;

const PHASE_CLASS = {
  combat: 'combat',
  shrine: 'shrine',
};

const INTENT_ICON = {
  attack: '⚡',
  heavy: '⚠️',
  poison: '☠️',
  guard: '🛡',
  drain: '🩸',
  charge: '💥',
  enrage: '🔥',
};

function render(data) {
  S = data;
  window.S = data;  // удобно для отладки в консоли
  const st = data.state;
  const v = data.view || {};

  $('floorNum').textContent = st.floor;
  $('floorName').textContent = data.floor_name || '';

  const pct = Math.max(0, Math.min(100, (st.hp / st.max_hp) * 100));
  $('hpFill').style.width = pct + '%';
  $('hpNum').textContent = `${st.hp}/${st.max_hp}`;
  document.querySelector('.hp-bar').classList.toggle('low', pct <= 30);

  $('atk').textContent = st.atk;
  $('def').textContent = st.def;
  $('gold').textContent = st.gold;
  $('kills').textContent = st.kills;

  renderMap(st);

  const card = $('card');
  card.className = 'card' + (PHASE_CLASS[st.phase] ? ' ' + PHASE_CLASS[st.phase] : '');

  const roomNo = Math.min(st.node + 1, 4);
  $('roomTag').textContent = st.phase === 'stairs'
    ? 'этаж ' + st.floor + ' · лестница'
    : 'этаж ' + st.floor + ' · комната ' + roomNo + '/4';
  $('emoji').textContent = v.emoji || '🕯';
  $('title').textContent = (v.title || 'Крипта') + (v.phase ? ' · ' + v.phase : '');
  $('text').textContent = v.text || '';

  const intentEl = $('intent');
  if (v.intent && v.intent.text && st.phase === 'combat') {
    intentEl.classList.remove('hidden');
    intentEl.dataset.kind = v.intent.kind || 'attack';
    intentEl.textContent = INTENT_ICON[v.intent.kind] + ' ' + v.intent.text;
  } else {
    intentEl.classList.add('hidden');
    intentEl.textContent = '';
  }
  $('status').textContent = v.status || '';

  const mhp = $('mhp');
  if (v.monster) {
    mhp.classList.remove('hidden');
    const mp = Math.max(0, Math.min(100, (v.monster.hp / v.monster.max_hp) * 100));
    $('mhpFill').style.width = mp + '%';
    $('mhpNum').textContent = `${v.monster.hp} / ${v.monster.max_hp}`;
  } else {
    mhp.classList.add('hidden');
  }

  $('weapon').textContent = `⚔️ ${st.weapon.name}`;
  $('armor').textContent = `🛡 ${st.armor.name}`;
  $('potions').textContent = `🧪 ×${st.potions}`;

  renderActions(data.actions || []);

  if (st.phase === 'dead' || st.phase === 'won') {
    if (lastPhase !== st.phase) {
      setTimeout(() => showOverlay(data), 550);
    }
  } else {
    hideOverlay();
  }
  lastPhase = st.phase;
}

function renderMap(st) {
  const total = 4;
  let html = '';
  for (let i = 0; i < total; i++) {
    let cls = 'node';
    let inner = String(i + 1);
    if (st.phase === 'stairs' || i < st.node) { cls += ' done'; inner = '✓'; }
    else if (i === st.node) { cls += ' now'; inner = '●'; }
    html += `<div class="${cls}">${inner}</div>`;
    if (i < total - 1) html += `<div class="link ${i < st.node ? 'done' : ''}"></div>`;
  }
  $('map').innerHTML = html;
}

const BTN_CLASS = {
  fight: 'fight',
  flee: 'danger',
  next: 'primary',
  down: 'primary',
  door: '',
  potion: '',
  shrine: '',
  guard: 'guard',
};

function renderActions(actions) {
  const box = $('actions');
  box.innerHTML = '';
  actions.forEach((a) => {
    const b = document.createElement('button');
    b.className = 'btn ' + (BTN_CLASS[a.kind] || '');
    b.innerHTML = `<span class="ico">${a.emoji || ''}</span><span class="lbl"></span>`;
    b.querySelector('.lbl').textContent = a.label;
    b.addEventListener('click', () => act(a.id));
    box.appendChild(b);
  });
}

/* ------------------------------------------------------------------ */
/* действия                                                           */
/* ------------------------------------------------------------------ */
async function act(actionId) {
  if (busy) return;
  busy = true;
  setDisabled(true);
  try {
    const data = await api('/api/action', {
      method: 'POST',
      body: JSON.stringify({ action: actionId }),
    });
    render(data);
    playEvents(data.events || [], data.state);
  } catch (e) {
    toast(e.message);
  } finally {
    busy = false;
    setDisabled(false);
  }
}

function setDisabled(v) {
  document.querySelectorAll('.actions .btn').forEach((b) => { b.disabled = v; });
}

function playEvents(events, st) {
  events.forEach((e, i) => {
    setTimeout(() => {
      if (e.t === 'hit' && e.who === 'monster') {
        floatText(`−${e.dmg}`, e.crit ? 'crit' : 'dmg', 50, 26);
        const em = $('emoji');
        em.classList.add('hurt');
        setTimeout(() => em.classList.remove('hurt'), 180);
        haptic(e.crit ? 'heavy' : 'medium');
      }
      if (e.t === 'hit' && e.who === 'player') {
        floatText(e.poison ? `☠−${e.dmg}` : `−${e.dmg}`, e.poison ? 'poison' : 'dmg', 24, 80);
        const c = $('card');
        c.classList.add('shake');
        setTimeout(() => c.classList.remove('shake'), 420);
        haptic('heavy');
      }
      if (e.t === 'miss') {
        floatText('мимо', 'miss', 50, 30);
        toast('Промах');
        haptic('light');
      }
      if (e.t === 'guard') {
        floatText('🛡', 'buff', 50, 66);
        haptic('light');
      }
      if (e.t === 'charge') {
        toast('Оно копит силы — следующий удар будет страшным');
        haptic('medium');
      }
      if (e.t === 'taunt') {
        toast(e.text);
      }
      if (e.t === 'guard_monster') {
        toast('Оно прикрылось');
      }
      if (e.t === 'heal') {
        floatText(`+${e.amount}`, 'heal', 50, 68);
        haptic('light');
      }
      if (e.t === 'buff') {
        floatText(`+${e.amount} ⚔️`, 'buff', 50, 68);
        haptic('light');
      }
      if (e.t === 'kill') toast(`${e.name} — повержен`);
      if (e.t === 'loot' && e.item) toast(`Находка: ${e.item}`);
      if (e.t === 'flee') toast(`Отступил. Потеряно ${e.gold} золота`);
    }, i * 140);
  });

  if (st.phase === 'dead' || st.phase === 'won') {
    setTimeout(() => showOverlay(S), 400 + events.length * 140);
  }
}

function floatText(text, cls, xPct, yPct) {
  const el = document.createElement('div');
  el.className = 'float ' + cls;
  el.textContent = text;
  el.style.left = xPct + '%';
  el.style.top = yPct + '%';
  $('fx').appendChild(el);
  setTimeout(() => el.remove(), 950);
}

function haptic(kind) {
  if (!tg || !tg.HapticFeedback) return;
  try {
    if (kind === 'heavy') tg.HapticFeedback.impactOccurred('heavy');
    else if (kind === 'light') tg.HapticFeedback.impactOccurred('light');
    else tg.HapticFeedback.impactOccurred('medium');
  } catch (e) { /* необязательно */ }
}

/* ------------------------------------------------------------------ */
/* оверлей финала                                                     */
/* ------------------------------------------------------------------ */
function showOverlay(data) {
  const st = data.state;
  const sc = data.score || {};
  const won = st.phase === 'won';
  $('ovEmoji').textContent = won ? '🏆' : '💀';
  $('ovTitle').textContent = won ? 'Крипта пройдена' : 'Ты погиб';
  $('ovText').textContent = won
    ? 'Король мёртв, ты — нет. Такое случается редко.'
    : 'Крипта не отпускает никого. Но вход всегда открыт снова.';
  $('ovStats').innerHTML = `
    <div><b>${sc.floor ?? st.floor}</b><span>глубина</span></div>
    <div><b>${sc.kills ?? st.kills}</b><span>убито</span></div>
    <div><b>${sc.gold ?? st.gold}</b><span>золото</span></div>
    <div><b>${sc.points ?? 0}</b><span>очки</span></div>`;
  $('overlay').classList.remove('hidden');
  haptic(won ? 'heavy' : 'medium');
}

function hideOverlay() {
  $('overlay').classList.add('hidden');
}

async function newRun(daily) {
  try {
    const data = await api('/api/new', {
      method: 'POST',
      body: JSON.stringify({ daily }),
    });
    lastPhase = null;
    hideOverlay();
    render(data);
    toast(daily ? 'Забег дня — подземелье у всех одинаковое' : 'Новый забег');
  } catch (e) {
    toast(e.message);
  }
}

$('ovNew').addEventListener('click', () => newRun(false));
$('ovDaily').addEventListener('click', () => newRun(true));

/* ------------------------------------------------------------------ */
/* тост и запуск                                                      */
/* ------------------------------------------------------------------ */
let toastTimer = null;
function toast(text) {
  const el = $('toast');
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
}

async function boot() {
  try {
    const data = await api('/api/state');
    render(data);
    if (data.state.log && data.state.log.length) {
      toast(data.state.log[data.state.log.length - 1]);
    }
  } catch (e) {
    $('text').textContent = e.message;
    $('title').textContent = 'Нет доступа';
    $('actions').innerHTML = '';
  }
}

boot();
