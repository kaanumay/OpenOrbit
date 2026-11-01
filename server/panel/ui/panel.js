/* OpenOrbit local server panel — the UI (panel.py's /api/... endpoints). No external library.
   Language: texts are written in English (the source language), T() gives the selected language's version (<code>.json, Turkish included: tr.json; if absent the text
   itself; shared with the Python side, lang.py).
   On first start the setup wizard: language, game folder, first pilot, game settings (panel.json 'dil', 'kurulum_tamam'). If the game is not
   found on the computer the game folder step starts downloading it (client_download.py; also from the Client page). When the panel installs a new version from GitHub
   and restarts (updater.py) the token changes: the page refreshes itself. */
'use strict';
const TOKEN = document.querySelector('meta[name="panel-token"]').content;
const $ = (s, r = document) => r.querySelector(s);

// ------------------------------------------------------------------ dil
// languages: /api/diller (lang.py LANGUAGES); text not in the dictionary stays in English (the source)
const I18N = { lang: 'tr', dict: {}, list: [{ code: 'tr', name: 'Türkçe', local: 'tr-TR', coverage: 100 }, { code: 'en', name: 'English', local: 'en-US', coverage: 100 }] };
function T(s, ...a) {
  let r = I18N.dict[s] ?? s;
  if (a.length) r = r.replace(/\{(\d+)\}/g, (m, i) => a[+i] == null ? '' : String(a[+i]));
  return r;
}
const langOf = k => I18N.list.find(x => x.code === k);
const LOC = () => langOf(I18N.lang)?.local || 'tr-TR';
const loadDict = async k => { try { return await (await fetch(k + '.json', { cache: 'no-store' })).json(); } catch (e) { return {}; } };
async function setLang(lang) {
  I18N.lang = langOf(lang) ? lang : 'tr';
  I18N.dict = I18N.lang === 'en' ? {} : await loadDict(I18N.lang);
  document.documentElement.lang = LOC();
}
// the first of the browser's languages that the panel has (pt-BR -> pt); otherwise English
const guessLang = () => (navigator.languages || [navigator.language || '']).map(x => x.toLowerCase().split('-')[0]).find(langOf) || 'en';
function applyStatic() {
  const sub = $('#brand-sub'); if (sub) sub.textContent = T('Local Server Panel');
  // support link at the very bottom of the sidebar (Buy Me a Coffee; opens in the default browser: /api/bagis)
  const coffee = $('#coffee');
  if (!coffee) return;
  const open_ = () => act(() => api('/api/donate', {}));
  const button = h('button', { class: 'coffee', type: 'button', title: 'buymeacoffee.com/kaanumay', onclick: open_ }, art('drone_coffee', 'coffee-drone'),
    h('span', null, h('b', null, T('Buy me a coffee')), h('small', null, T("Support OpenOrbit"))));
  coffee.replaceChildren(button);
  // below it the latest supporters scroll by to the left (Recent supporters on the page; if offline the list comes back empty, the strip never appears)
  api('/api/supporters').then(d => {
    if (!d.names || !d.names.length || !button.isConnected) return;   // if applyStatic rebuilt it when the language changed, the old one should not be added
    const group = () => h('span', { class: 'coffee-group' }, d.names.map(a => h('span', null, a)));
    const duration = Math.max(12, d.names.join('').length * 0.45 + d.names.length * 2);   // so the speed stays constant as the number of names grows
    coffee.append(h('button', { class: 'coffee-strip', type: 'button', title: T('Recent supporters'), 'aria-label': T('Recent supporters') + ': ' + d.names.join(', '), onclick: open_ },
      h('span', { class: 'coffee-marquee', style: { animationDuration: duration + 's' } }, group(), group())));
  }).catch(() => {});
}

// ------------------------------------------------------------------ icons (24x24, line)
const ICONS = {
  play: '<polygon points="7 4 20 12 7 20 7 4" fill="currentColor" stroke="none"/>',
  save: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  sliders: '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
  calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
  server: '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>',
  info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  hangar: '<path d="M3 21V9l9-6 9 6v12"/><path d="M7 21v-7h10v7"/><line x1="7" y1="17" x2="17" y2="17"/>',
  lab: '<path d="M9 3h6"/><path d="M10 3v6L4 19a1.5 1.5 0 0 0 1.3 2h13.4a1.5 1.5 0 0 0 1.3-2L14 9V3"/><line x1="7" y1="15" x2="17" y2="15"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
  gavel: '<path d="M14 13l-7.5 7.5a2.1 2.1 0 0 1-3-3L11 10"/><path d="M16 16l6-6"/><path d="M8 8l6-6"/><path d="M9 7l8 8"/><path d="M21 11l-8-8"/>',
  cart: '<circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.7 13.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L23 6H6"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  folder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  refresh: '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.5 9a9 9 0 0 1 14.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0 0 20.5 15"/>',
  power: '<path d="M18.4 6.6a9 9 0 1 1-12.8 0"/><line x1="12" y1="2" x2="12" y2="12"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  undo: '<polyline points="1 4 1 10 7 10"/><path d="M3.5 15a9 9 0 1 0 2.1-9.4L1 10"/>',
  star: '<polygon points="12 2 15.1 8.3 22 9.3 17 14.1 18.2 21 12 17.8 5.8 21 7 14.1 2 9.3 8.9 8.3 12 2"/>',
  note: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="13" y2="17"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
  search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  ship: '<path d="M12 2 4 20l8-4 8 4z"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  globe: '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  wand: '<path d="M15 4V2"/><path d="M15 16v-2"/><path d="M8 9h2"/><path d="M20 9h2"/><path d="M17.8 11.8 19 13"/><path d="M15 9h.01"/><path d="M17.8 6.2 19 5"/><path d="m3 21 9-9"/><path d="M12.2 6.2 11 5"/>',
  arrowL: '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
  arrowR: '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>',
  chevR: '<polyline points="9 18 15 12 9 6"/>',
  agenda: '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="7" y1="14" x2="13" y2="14"/><line x1="10" y1="18" x2="17" y2="18"/>',
};
const SVGNS = 'http://www.w3.org/2000/svg';
function icon(name) {
  const s = document.createElementNS(SVGNS, 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor');
  s.setAttribute('stroke-width', '2'); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round');
  s.innerHTML = ICONS[name] || ''; return s;
}

// ------------------------------------------------------------------ DOM helpers
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  if (props) for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') for (const [p, x] of Object.entries(v)) p.startsWith('--') ? el.style.setProperty(p, x) : el.style[p] = x;   // variables like --c only with setProperty
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked' || k === 'disabled' || k === 'selected') el[k] = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const btn = (label, onclick, cls = '', iconEl = null, props = {}) =>
  h('button', Object.assign({ class: 'btn ' + cls, onclick, type: 'button' }, props), iconEl ? icon(iconEl) : null, label ? h('span', null, label) : null);
const badge = (text, cls = '') => h('span', { class: 'badge ' + cls }, text);
const dot = cls => h('span', { class: 'dot ' + (cls || '') });
const art = (name, cls = 'art') => h('img', { class: cls, src: 'images/' + name + '.webp', sub: '' });   // ui/images/ (Orders.md)
const N = s => s;     // marker for text to be translated: it stays in a variable, shown with T() (test_panel_lang.py collects it)
const field = (label, ...ctl) => h('div', { class: 'field' }, h('label', null, label), ...ctl);

// ------------------------------------------------------------------ formats
const fmtN = n => (Number(n) || 0).toLocaleString(LOC());
function fmtDur(s) {
  s = Math.max(0, s | 0);
  const d = Math.floor(s / 86400), hh = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  if (d) return T('{0}d {1}h', d, hh);
  if (hh) return T('{0}h {1}m', hh, m);
  if (m) return T('{0} min', m);
  return T('{0} s', s);
}
function parseDate(str) { if (!str) return null; const d = new Date(str.replace(' ', 'T')); return isNaN(d) ? null : d; }
function fmtWhen(str) {
  const d = parseDate(str); if (!d) return '—';
  const now = new Date(), diff = (now - d) / 1000;
  const t = d.toLocaleTimeString(LOC(), { hour: '2-digit', minute: '2-digit' });
  const day = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (diff < 60) return T('just now');
  if (diff < 3600) return T('{0} min ago', Math.floor(diff / 60));
  if (d >= day) return T('today {0}', t);
  if (d >= new Date(day - 86400000)) return T('yesterday {0}', t);
  if (diff < 7 * 86400) return T('{0} days ago', Math.floor(diff / 86400));
  return d.toLocaleDateString(LOC(), { day: 'numeric', month: 'short', year: 'numeric' });
}
const fmtBytes = b => b == null ? '—' : b < 1024 ? b + ' B' : b < 1048576 ? (b / 1024).toFixed(1) + ' KB'
  : b < 1073741824 ? (b / 1048576).toFixed(1) + ' MB' : (b / 1073741824).toFixed(2) + ' GB';
const firmaCls = f => ({ MMO: 'mmo', EIC: 'eic', VRU: 'vru' }[f] || '');
const lvl = v => T('Lv') + ' ' + (v ?? '?');

// ------------------------------------------------------------------ API
async function api(path, body) {
  const opt = { headers: { 'X-Panel-Token': TOKEN } };
  if (body !== undefined) {
    opt.method = 'POST'; opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body);
  }
  let r;
  try { r = await fetch(path, opt); } catch (e) { throw new Error(T("Can't reach the panel: it may have closed.")); }
  const d = await r.json().catch(() => ({}));
  if (r.status === 403 && d.error && d.error !== 'host' && !api.reloading) { api.reloading = true; location.reload(); }   // the panel restarted
  if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
  return d;
}
async function act(fn, okMsg) {
  try {
    const r = await fn();
    if (okMsg) toast(typeof okMsg === 'function' ? okMsg(r) : okMsg, 'ok');
    return r;
  } catch (e) { toast(e.message, 'err'); return undefined; }
}

// ------------------------------------------------------------------ notification, window, menu
function toast(text, kind = 'info', ms = 4200) {
  const t = h('div', { class: 'toast ' + kind }, icon(kind === 'ok' ? 'check' : kind === 'err' ? 'alert' : 'info'), h('div', null, text));
  $('#toasts').append(t);
  setTimeout(() => { t.style.transition = '.3s'; t.style.opacity = '0'; setTimeout(() => t.remove(), 320); }, kind === 'err' ? ms + 3000 : ms);
}
function modal({ title, sub, body, foot, wide, onclose }) {
  const root = $('#modal-root');
  const box = h('div', { class: 'modal' + (wide ? ' wide' : '') }, h('h3', null, title), sub ? h('div', { class: 'muted small' }, sub) : null,
    h('div', { class: 'body' }, body), foot ? h('div', { class: 'foot' }, foot) : null);
  const back = h('div', { class: 'modal-back', onmousedown: e => { if (e.target === back) close(); } }, box);
  function close() { back.remove(); document.removeEventListener('keydown', esc); if (onclose) onclose(); }
  function esc(e) { if (e.key === 'Escape' && root.lastChild === back) close(); }
  document.addEventListener('keydown', esc);
  root.append(back);
  setTimeout(() => { const f = box.querySelector('input:not([type=checkbox]):not([type=range]), textarea'); if (f) f.focus(); }, 30);
  return { close, box };
}
function confirmBox(title, text, { ok = T('OK'), danger = false, detail = null } = {}) {
  return new Promise(res => {
    let done = false;
    const m = modal({
      title, body: [h('div', null, text), detail], onclose: () => { if (!done) res(false); },
      foot: [btn(T('Cancel'), () => m.close(), 'ghost'), btn(ok, () => { done = true; m.close(); res(true); }, danger ? 'danger' : 'primary')],
    });
  });
}
function promptBox(title, label, value = '', { ok = T('Save'), multiline = false, placeholder = '' } = {}) {
  return new Promise(res => {
    let done = false;
    const inp = multiline ? h('textarea', { class: 'input', placeholder }, value) : h('input', { class: 'input', value, placeholder });
    const submit = () => { done = true; m.close(); res(inp.value); };
    if (!multiline) inp.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
    const m = modal({
      title, body: field(label, inp), onclose: () => { if (!done) res(null); },
      foot: [btn(T('Cancel'), () => m.close(), 'ghost'), btn(ok, submit, 'primary')],
    });
  });
}
function popMenu(anchor, items) {
  document.querySelectorAll('.menu').forEach(m => m.remove());
  const m = h('div', { class: 'menu' }, items.map(it => it === '-' ? h('hr') :
    h('button', { class: it.danger ? 'danger' : '', onclick: () => { m.remove(); it.fn(); }, disabled: it.disabled }, icon(it.ic || 'more'), it.label)));
  document.body.append(m);
  const r = anchor.getBoundingClientRect();
  const w = m.offsetWidth, hgt = m.offsetHeight;
  m.style.left = Math.min(window.innerWidth - w - 8, r.right - w) + 'px';
  m.style.top = (r.bottom + hgt + 8 > window.innerHeight ? r.top - hgt - 6 : r.bottom + 6) + 'px';
  setTimeout(() => document.addEventListener('mousedown', function off(e) {
    if (!m.contains(e.target)) { m.remove(); document.removeEventListener('mousedown', off); }
  }), 0);
}

// ------------------------------------------------------------------ pages and frame
const PAGES = [
  { id: 'play', name: N('Play'), ic: 'play', sub: N('See your save, check your settings and start the game.') },
  { id: 'friend', name: N('Play with Friends'), ic: 'users', sub: N("Host a server or join your friend's server. Everyone plays with their own save.") },
  { id: 'saves', name: N('Saves'), ic: 'save', sub: N('Save slots, backups, copying, import and export.') },
  { id: 'settings', name: N('Game Settings'), ic: 'sliders', sub: N('Multipliers and rules. Saved automatically; most apply instantly while the game is running.') },
  { id: 'world', name: N('World Editor'), ic: 'globe', sub: N('Change the maps, aliens, quests, shop and auction; create your own worlds.') },
  { id: 'bots', name: N('Bots'), ic: 'bot', beta: true, sub: N('Bots that develop, talk and found clans like real players: create a pack and assign it to a world.') },
  { id: 'events', name: N('Events'), ic: 'calendar', sub: N('Each event by calendar, or switched on / off by hand.') },
  { id: 'calendar', name: N('Event Calendar'), ic: 'agenda', sub: N('Events and their sessions in hourly, daily, weekly and monthly views (local time).') },
  { id: 'client', name: N('Client'), ic: 'monitor', sub: N('Game folder, version check and display options.') },
  { id: 'server', name: N('Server'), ic: 'server', sub: N('Server processes, ports, behavior and logs.') },
  { id: 'panel', name: N('Panel'), ic: 'info', sub: N('Language, setup wizard, updates, desktop shortcut, folders and about the panel.') },
  // in-game menus: in a separate section of the sidebar, only while the game is open (panel_channel.py); the icon is the game's own image (sprite)
  // the order is the same as the tabs above the pages (GAME_PAGES)
  { id: 'shop', name: N('Shop'), ic: 'cart', sprite: 'shop_normal', game: true, sub: N('The in-game shop: what you buy arrives in the game right away.') },
  { id: 'hangar', name: N('Hangar'), ic: 'hangar', sprite: 'hangar_normal', game: true, sub: N('Your ships and their equipment: click an item to equip or unequip it; it changes in the game right away.') },
  { id: 'skylab', name: N('Skylab'), ic: 'lab', sprite: 'skylab_normal', game: true, sub: N('Modules, production, storage and transport to your ship; the same as the Skylab in the game.') },
  { id: 'auction', name: N('Auction'), ic: 'gavel', sprite: 'auction_normal', game: true, sub: N('Bid, bid on everything, set auto-bids and alarms; they work in the game even with the panel closed.') },
];
const S = { state: null, page: null, sig: {}, timers: [] };

function buildNav() {
  const nav = $('#nav');
  const navBtn = p => h('button', { 'data-page': p.id, class: p.id === S.page ? 'active' : null, onclick: () => go(p.id) },
    p.game && GI.index?.sprite[p.sprite] ? sprite(p.sprite, 18) : icon(p.ic),
    h('span', null, T(p.name)), p.beta ? h('span', { class: 'beta-label' }, 'Beta') : null,
    h('span', { class: 'badge', id: 'nav-badge-' + p.id, style: { display: 'none' } }));
  nav.replaceChildren(...PAGES.filter(p => !p.game).map(navBtn),
    h('div', { class: 'nav-game', id: 'nav-game', style: { display: 'none' } }, h('div', { class: 'nav-title' }, T('In-game')),
      PAGES.filter(p => p.game).map(navBtn)));
}
function go(id, push = true) {
  if (!PAGES.find(p => p.id === id)) id = 'play';
  S.timers.forEach(clearInterval); S.timers = [];
  S.page = id; S.sig = {}; document.body.dataset.page = id;      // the page title's scene (panel.css .topbar)
  if (push && location.hash !== '#' + id) history.replaceState(null, '', '#' + id);
  document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('active', b.dataset.page === id));
  const p = PAGES.find(x => x.id === id);
  $('#page-title').replaceChildren(T(p.name), ...(p.beta ? [h('span', { class: 'beta-label' }, 'Beta')] : [])); $('#page-sub').textContent = T(p.sub);
  $('#content').replaceChildren(h('div', { class: 'empty' }, h('div', { class: 'spin', style: { margin: '30px auto' } })));
  RENDER[id]();
}
window.addEventListener('hashchange', () => go(location.hash.slice(1), false));

function srvState(d) {
  const s = d?.processes; if (!s) return { web: 'off', game: 'off', client: 'off' };
  return { web: s.servers.web.state, game: s.servers.game.state, client: s.client.state };
}
const stCls = v => v === 'on' ? 'ok' : v === 'crashed' ? 'err' : '';
const stText = v => ({ on: T('On'), off: T('Off'), crashed: T('Crashed') }[v] || v);

function renderChrome() {
  const d = S.state, st = srvState(d);
  const side = $('#side-status');
  side.replaceChildren(
    ...[[T('Web server'), st.web], [T('Game server'), st.game], [T('Client'), st.client]].map(([n, v]) =>
      h('div', { class: 'row' }, h('span', null, n), h('span', { class: 'row', style: { gap: '6px' } }, dot(stCls(v)), stText(v)))),
    h('div', { class: 'give' }, S.offline ? T('No connection to the panel') : 'Panel ' + (d?.panel?.version || '')));
  const tr = $('#top-right');
  const kids = [];
  if (S.offline) kids.push(h('span', { class: 'pill' }, dot('err'), T('Panel closed')));
  else if (d) {
    if (d.active) kids.push(h('span', { class: 'pill' }, icon('save'), T('Save:') + ' ', h('b', null, d.active.name)));
    const running = st.client === 'on', srv = st.game === 'on';
    kids.push(h('span', { class: 'pill' }, dot(d.play.running ? 'busy' : running ? 'ok' : srv ? 'warn' : ''),
      d.play.running ? T('Starting…') : running ? T('Game running') : srv ? T('Server running') : T('Off')));
    const extras = d.multi?.clients?.length;
    if (extras) kids.push(h('span', { class: 'pill', style: { cursor: 'pointer' }, onclick: () => go('play') }, icon('monitor'), T('{0} extra clients', extras)));
    const friends = d.friend || {};
    if (friends.host || FRD_ACTIVE(friends.guest)) kids.push(h('span', { class: 'pill', style: { cursor: 'pointer' }, onclick: () => go('friend') }, icon('users'),
      friends.host ? T('Friend server running') : T("On a friend's server:") + ' ', friends.host ? null : h('b', null, friends.address)));
  }
  tr.replaceChildren(...kids);
  const navGame = $('#nav-game'), gameOpen = st.game === 'on' && st.client === 'on';
  if (navGame) navGame.style.display = gameOpen ? '' : 'none';
  // when the game closes the user on an in-game page returns to the Play page (the page's data comes from the game server)
  if (d && !gameOpen && PAGES.find(p => p.id === S.page)?.game) {
    if (S.game_was_open) toast(T('The game closed: back to the Play page.'), 'info');
    go('play');
  }
  S.game_was_open = gameOpen;
  const setBadge = (id, text, cls) => {
    const b = $('#nav-badge-' + id); if (!b) return;
    b.style.display = text ? '' : 'none'; b.textContent = text || ''; b.className = 'badge ' + (cls || '');
  };
  if (d) {
    setBadge('saves', d.save_count ? String(d.save_count) : '', '');
    setBadge('events', d.events.length ? String(d.events.length) : '', 'orange');
    const errs = d.warnings.filter(u => u.type === 'error').length;
    setBadge('server', st.game === 'crashed' || st.web === 'crashed' ? '!' : '', 'err');
    setBadge('play', errs ? '!' : '', 'err');
    setBadge('settings', d.settings_summary.length ? String(d.settings_summary.length) : '', 'info');
  }
}

async function poll() {
  try { S.state = await api('/api/status'); S.offline = false; } catch (e) { S.offline = true; }
  if (S.state?.panel?.updated && S.state.panel.uptime_sec < 60 && !S.updToast) { S.updToast = true; toast(T('The panel was updated and restarted.'), 'ok'); }
  renderChrome();
  if (S.page === 'play') { renderPlayBody(); liveTick(); }
  if (S.page === 'server') renderServerCards();
  if (S.page === 'friend' && FRD.data) friendsTick();
  poll.n = (poll.n || 0) + 1;
  if (poll.n % 3 === 0) auctionEventTick();      // auction notifications (~5 s)
  setTimeout(poll, S.state?.play?.running ? 500 : 1500);
}
window.addEventListener('pagehide', () => navigator.sendBeacon && navigator.sendBeacon('/api/closed', '{}'));

// ================================================================== PLAY
function renderPlay() { S.sig = {}; $('#content').replaceChildren(h('div', { class: 'stack', id: 'play' })); renderPlayBody(); }

function renderPlayBody() {
  const d = S.state, root = $('#play');
  if (!root) return;
  if (!d) return;
  const sig = JSON.stringify([d.active, d.processes.servers.web.state, d.processes.servers.game.state, d.processes.client.state,
    d.processes.client.last, d.play, d.warnings, d.settings_summary, d.events, multiSig(d.multi), S.multiBusy, Math.floor(Date.now() / 30000)]);
  if (S.sig.play === sig) return;
  S.sig.play = sig;
  const st = srvState(d), a = d.active, o = d.play;
  const running = st.client === 'on', srv = st.game === 'on';
  const blocking = d.warnings.filter(u => u.type === 'error');
  const clientMissing = blocking.some(u => u.page === 'client');

  // ---- hero card
  let left;
  if (!a) {
    left = h('div', null, h('div', { class: 'slot-name' }, T('No save')), h('div', { class: 'pilot' }, T('Welcome, pilot')),
      h('div', { class: 'muted' }, T('To play, create a save first: choose your pilot name and company.')),
      h('div', { class: 'row', style: { marginTop: '16px' } }, btn(T('Create a new save'), () => newSaveModal(), 'primary', 'plus')));
  } else {
    left = h('div', null,
      h('div', { class: 'row', style: { gap: '8px' } }, h('span', { class: 'slot-name' }, a.name),
        btn(T('Switch'), ev => switchSaveMenu(ev.currentTarget), 'ghost sm', 'refresh')),
      h('div', { class: 'pilot' }, firmaCls(a.company) ? art('company_' + firmaCls(a.company), 'crest-sm') : null, a.pilot, badge(a.company, firmaCls(a.company)), a.clan ? badge('[' + a.clan + ']', 'info') : null),
      h('div', { class: 'meta' },
        [[T('Level'), a.level], [T('Ship'), a.ship], [T('Map'), a.map], [T('Play time'), fmtDur(a.play_sec)],
          [T('Last played'), fmtWhen(a.last_played || a.last_save)]].map(([k, v]) => h('span', null, k + ' ', h('b', null, v)))),
      a.world_info ? playWorldChip(a) : null,                    // the save's default world (world_editor.js)
      h('div', { class: 'stats' },
        [[T('Credits'), a.credits, 'cr'], [T('Uridium'), a.uridium, 'ur'], [T('Honor'), a.honor, 'hn'], [T('Experience'), a.ep, 'ep']].map(([k, v, c]) =>
          h('div', { class: 'stat' }, h('div', { class: 'k' }, k), h('div', { class: 'v ' + c }, fmtN(v))))));
  }
  let main, sub = [];
  if (o.running) {
    const prep = o.steps.length && o.steps[o.steps.length - 1].progress;      // BepInEx's first-start preparation (client_patch.warm_up)
    main = h('button', { class: 'play-btn busy' + (prep ? ' prep' : ''), disabled: true, style: prep ? { '--p': prep.percent + '%' } : null },
      prep ? null : h('span', { class: 'spin', style: { borderTopColor: '#021120' } }), prep ? T('PREPARING') : T('STARTING'));
  } else if (running) {
    main = h('button', { class: 'play-btn running', disabled: true }, icon('check'), T('GAME RUNNING'));
    sub.push(btn(T('Close the game'), async () => {
      if (await confirmBox(T('Close the game?'), T('The client will be closed. Your save is kept on the server; quitting with the in-game logout button is safer.'),
        { ok: T('Close'), danger: true })) act(() => api('/api/client/close', {}));
    }, 'danger sm', 'power'));
  } else {
    main = h('button', { class: 'play-btn', disabled: !a || clientMissing, onclick: () => act(() => api('/api/play', {})) }, icon('play'), T('PLAY'));
    if (srv) sub.push(btn(T('Stop the server'), () => act(() => api('/api/server/stop', {}), T('Servers stopped.')), 'ghost sm', 'stop'));
    else sub.push(btn(T('Start the server only'), () => act(() => api('/api/play', { server_only: true })), 'ghost sm', 'server', { disabled: !a }));
  }
  const playCol = h('div', { class: 'play-col' }, main, h('div', { class: 'play-sub' }, sub),
    a ? h('div', { class: 'small muted' }, running ? (S.panelCfg?.when_client_closes === 'on' || d.multi?.clients?.length ? T('Have a good flight! The servers stay on when you close the game.')
      : T('Have a good flight! The servers stop when you close the game.')) : srv ? T('Server running: PLAY opens the client.') : T('The servers and the client start together.')) : null);
  const hero = h('div', { class: 'hero' }, left, playCol);

  // ---- launch steps
  let steps = null;
  const recent = o.finished && (Date.now() / 1000 - o.finished < 45);
  if (o.steps.length && (o.running || o.error || recent)) {
    steps = h('div', { class: 'card' }, h('h2', null, icon('zap'), o.server_only ? T('Server launch') : T('Game launch')),
      stepList(o.steps));
  }
  const last = d.processes.client.last;
  const early = last && last.early && !running ? h('div', { class: 'alert warning' }, icon('alert'),
    h('div', null, T('The client closed {0} s after starting ({1}). The servers were left running. Check the client log.', last.duration_sec, last.time)),
    btn(T('Log'), () => { go('server'); setTimeout(() => showLog(d.panel.platform === 'win32' ? 'client.log' : 'wine.log'), 100); }, 'sm')) : null;

  // ---- warnings
  const warns = d.warnings.map(u => h('div', { class: 'alert ' + (u.type === 'error' ? 'error' : 'warning') }, icon('alert'),
    h('div', { style: u.progress != null ? { flex: '1' } : null }, u.text,
      u.progress != null ? h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: u.progress + '%' } }))) : null,
      u.download && u.download.total ? h('div', { class: 'small dl-info' }, dlInfo(u.download)) : null),
    u.action ? btn(u.action.running ? u.action.running_text || T('Installing…') : u.action.text, () => act(() => api(u.action.api, {})), 'primary sm', null, { disabled: !!u.action.running }) : null,
    u.page ? btn(T('Go'), () => go(u.page), 'sm') : null));

  // ---- summary cards
  const setCard = h('div', { class: 'card' }, h('h2', null, icon('sliders'), T('Active settings')),
    h('p', { class: 'desc' }, d.settings_summary.length ? T('Different from the defaults:') : T('All settings are at their defaults.')),
    h('div', { class: 'chips' }, d.settings_summary.map(x => h('span', { class: 'chip' }, x.name, h('b', null, x.value)))),
    h('div', { class: 'row', style: { marginTop: '14px' } }, btn(T('Edit settings'), () => go('settings'), 'sm', 'sliders')));
  const evCard = h('div', { class: 'card' }, h('h2', null, icon('calendar'), T('Active events')),
    h('p', { class: 'desc' }, d.events.length ? T('Yearly events active when you enter the game:') : T('No yearly event is on right now.')),
    h('div', { class: 'chips' }, d.events.map(n => h('span', { class: 'chip' }, '🎉 ', n))),
    h('div', { class: 'row wrap', style: { marginTop: '14px' } }, btn(T('Manage events'), () => go('events'), 'sm', 'calendar'),
      btn(T('Calendar'), () => go('calendar'), 'ghost sm', 'agenda')));
  const srvCard = h('div', { class: 'card' }, h('h2', null, icon('server'), T('Server')),
    h('div', { class: 'check-list' }, [[T('Web login (8090, 80)'), st.web, d.processes.servers.web.duration_sec],
      [T('Game server (8081)'), st.game, d.processes.servers.game.duration_sec], [T('Client'), st.client, d.processes.client.duration_sec]].map(([n, v, t]) =>
      h('div', null, dot(stCls(v)), h('span', null, n), h('span', { class: 'muted small', style: { marginLeft: 'auto' } },
        stText(v) + (v === 'on' && t != null ? ' · ' + fmtDur(t) : ''))))),
    h('div', { class: 'row' }, btn(T('Server and logs'), () => go('server'), 'sm', 'server')));

  root.replaceChildren(...[...warns, hero, steps, early, multiCard(d), srv || S.live?.exists ? liveCard() : null,
    h('div', { class: 'grid g3' }, setCard, evCard, srvCard)].filter(Boolean));
}

// ---- multiple clients (multi_client.py, /api/coklu): after PLAY, extra clients to the same server with the other saves
const multiSig = c => c && JSON.stringify(Object.assign({}, c, { clients: (c.clients || []).map(x => Object.assign({}, x, { duration_sec: null })) }));
async function openExtra(id, pilot) {
  S.multiBusy = id; S.sig.play = null; renderPlayBody();
  const r = await act(() => api('/api/multi/open', { record: id }), T('Opening extra client: {0}', pilot));
  S.multiBusy = null; S.sig.play = null;
  try { S.state = await api('/api/status'); } catch (e) { /* at the next poll */ }
  renderChrome(); renderPlayBody();
  return r;
}
function extraBlock(d, k) {
  const c = d.multi, open = c.clients || [];
  const pilots = [(c.saves || []).find(x => x.id === c.main)?.pilot, ...open.map(x => x.pilot)].filter(Boolean).map(p => p.toLowerCase());
  return srvState(d).game !== 'on' ? T('PLAY first') : d.play.running ? T('Starting') : k.corrupt ? T('Save corrupt')
    : k.friend ? T("On a friend's server") : open.length >= c.max_count ? T('Limit reached ({0})', c.max_count)
    : pilots.includes((k.pilot || '').toLowerCase()) ? T('Same pilot name already open') : S.multiBusy ? T('Opening…') : null;
}
function multiCard(d) {
  const c = d.multi; if (!c) return null;
  const open = c.clients || [], st = srvState(d), srv = st.game === 'on';
  if (!open.length && (!c.setting || c.save_count < 2)) return null;      // off or no other save: no card (setting on the Client page)
  const now = Date.now() / 1000;
  const others = (c.saves || []).filter(k => !k.extra && k.id !== c.main);
  const desc = !srv ? T('After PLAY you can open extra clients with your other saves on the same server: each in its own window, with its own pilot. They see each other in game and can group up and fly together.')
    : !c.server ? (st.client === 'on' ? T('The server started in single-player mode: for an extra client, close the game and press PLAY again.')
      : T('The server is in single-player mode: it restarts in multi-session mode when the first extra client opens.'))
    : T("Extra clients connect to this server; the window title is the pilot's name. Each client uses about 600 MB of memory.");
  const logBtn = id => btn('', () => { go('server'); setTimeout(() => showLog('client_' + id + '.log'), 100); }, 'ghost sm icon', 'note', { title: T('Log') });
  const openRows = open.map(x => h('tr', null, h('td', null, h('b', null, x.pilot),
      [(c.saves || []).find(k => k.id === x.record)?.name || x.record].filter(a => a !== x.pilot).map(a => h('div', { class: 'small muted' }, a))),
    h('td', null, x.level ?? '—'), h('td', null, x.map || '—'),
    h('td', null, x.state === 'opening' ? badge(T('Opening'), 'info') : x.state === 'closing' ? badge(T('Closing'), 'orange')
      : x.connected ? badge(T('In game'), 'ok') : badge(T('Connecting'), 'info')),
    h('td', { class: 'muted small' }, (x.pid ? 'PID ' + x.pid + ' · ' : '') + fmtDur(x.duration_sec)),
    h('td', { class: 'num' }, h('div', { class: 'actions', style: { justifyContent: 'flex-end' } }, logBtn(x.record),
      btn(T('Close'), async () => {
        if (await confirmBox(T('Close {0}?', x.pilot), T("The extra client's window closes; the save's latest state is written."), { ok: T('Close'), danger: true }))
          act(() => api('/api/multi/close', { record: x.record }), T('Closing {0}.', x.pilot));
      }, 'ghost sm', 'power', { disabled: x.state !== 'on' })))));
  const otherRows = others.map(k => {
    const why = extraBlock(d, k), busy = S.multiBusy === k.id;
    return h('div', { class: 'row multi-row' }, h('span', { style: { minWidth: 0, flex: 1 } }, h('b', null, k.pilot || '?'), ' ',
      badge(k.company || '?', firmaCls(k.company)), h('span', { class: 'small muted' }, ' ' + lvl(k.level) + ' · ' + k.name)),
      why && !busy ? h('span', { class: 'small dim' }, why) : null,
      btn(busy ? T('Opening…') : T('Open in extra client'), () => openExtra(k.id, k.pilot), 'primary sm', busy ? null : 'play', { disabled: !!why || busy }));
  });
  const early = Object.entries(c.last || {}).filter(([id, s]) => s.early && now - s.end_time < 120 && !open.some(x => x.record === id)).map(([id, s]) =>
    h('div', { class: 'alert warning' }, icon('alert'), h('div', null, T('The extra client of the save {0} closed {1} s after opening ({2}). Check the client log.',
      (c.saves || []).find(k => k.id === id)?.name || id, s.duration_sec, s.time)), logBtn(id)));
  return h('div', { class: 'card', id: 'multi-card' },
    h('div', { class: 'row between wrap' }, h('h2', null, icon('monitor'), T('Multi-client')),
      h('div', { class: 'row wrap', style: { gap: '6px' } }, badge(T('{0} / {1} extra clients', open.length, c.max_count), open.length ? 'ok' : ''),
        open.length > 1 ? btn(T('Turn all off'), async () => {
          if (await confirmBox(T('Close all extra clients?'), T("{0} windows close; the saves' latest state is written. The main client stays open.", open.length), { ok: T('Turn all off'), danger: true }))
            act(() => api('/api/multi/close_all', {}), T('Closing the extra clients.'));
        }, 'ghost sm', 'power') : null,
        btn('', () => go('client'), 'ghost sm icon', 'sliders', { title: T('Multi-client settings') }))),
    h('p', { class: 'desc' }, desc),
    early,
    open.length ? h('table', { class: 'table', style: { marginBottom: others.length ? '12px' : 0 } },
      h('thead', null, h('tr', null, [T('Pilot'), T('Level'), T('Map'), T('Status'), T('Duration'), ''].map(x => h('th', null, x)))),
      h('tbody', null, openRows)) : null,
    others.length ? h('div', { class: 'stack', style: { gap: '6px' } }, otherRows)
      : !c.setting ? null : h('div', { class: 'small muted' }, T('No other save to open.')));
}

// ---- live status (the game server's live_status.json; live_status.py, /api/canli)
async function liveTick() {
  if (S.page !== 'play' || S.liveBusy) return;
  S.liveBusy = true;
  try { S.live = await api('/api/live'); } catch (e) { S.live = null; } finally { S.liveBusy = false; }
  const c = $('#live-card'), want = srvState(S.state).game === 'on' || !!S.live?.exists;
  if (c && want) c.replaceWith(liveCard());
  else if (!!c !== want) { S.sig.play = null; renderPlayBody(); }     // let the card appear / disappear
}
function meter(label, v, max, cls) {
  const pct = max ? Math.max(0, Math.min(100, v * 100 / max)) : 0;
  return h('div', { class: 'meter ' + (cls || '') }, h('div', { class: 'row between small' }, h('span', { class: 'muted' }, label), h('b', null, fmtN(v) + ' / ' + fmtN(max))),
    h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } })));
}
function liveCard() {
  const r = S.live;
  const head = h('h2', null, icon('zap'), T('Live status'));
  if (!r || !r.exists) return h('div', { class: 'card', id: 'live-card' }, head, h('p', { class: 'desc' }, T("Waiting for the game server's status…")));
  const d = r.state, w = d.world || {}, g = d.ship, p = d.pilot, k = d.position;
  const flags = [d.connected ? badge(T('Client connected'), 'ok') : badge(T('Client not connected'), ''), r.age > 10 ? badge(T('Status {0} s old', Math.round(r.age)), 'warn') : null,
    w.dead ? badge(T('Ship destroyed'), 'err') : null, w.in_combat ? badge(T('In combat'), 'orange') : null, w.safe ? badge(T('In a safe zone'), 'info') : null];
  const facts = [[T('Map'), `${k.map} (${fmtN(k.x)}, ${fmtN(k.y)})`], [T('Ship'), (g.name || '').replace('ship_', '')], [T('Aliens'), w.alien != null ? fmtN(w.alien) : '—'],
    [T('Boxes / ore'), w.box != null ? fmtN(w.box) + ' / ' + fmtN(w.ore) : '—'], [T('Target'), w.target || '—'], [T('Play time'), fmtDur(d.play_sec)]];
  if (w.gate) facts.push([T('Gate'), `${w.gate.name || ''}${w.gate.wave ? ' · ' + w.gate.wave : ''}${w.gate.stage ? ' · ' + w.gate.stage : ''}`]);
  if (w.loop) facts.push([T('Loop'), T('{0} ms avg. · max {1} ms', w.loop.avg_ms, w.loop.max_ms) + (w.loop.slow ? ' · ' + T('{0} slow ticks', fmtN(w.loop.slow)) : '')]);
  return h('div', { class: 'card', id: 'live-card' }, h('div', { class: 'row between wrap' }, head, h('div', { class: 'row wrap', style: { gap: '6px' } }, flags)),
    h('div', { class: 'grid g2', style: { marginTop: '12px' } },
      h('div', { class: 'stack', style: { gap: '10px' } }, meter(T('Hit points'), g.hp, g.max_hp, 'hp'), meter(T('Shield'), g.shield, g.shield_max, 'sh'), meter(T('Cargo'), g.cargo, g.cargo_max, 'cg')),
      h('div', { class: 'kv one' }, facts.map(([a, b]) => h('div', null, h('span', { class: 'muted' }, a), h('b', { title: b }, b))))),
    h('div', { class: 'live-sub' }, h('div', { class: 'stats', style: { marginTop: 0 } },
      [[T('Level'), p.level, 'lv'], [T('Credits'), p.credits, 'cr'], [T('Uridium'), p.uridium, 'ur'], [T('Honor'), p.honor, 'hn']].map(([a, v, c]) =>
        h('div', { class: 'stat' }, h('div', { class: 'k' }, a), h('div', { class: 'v ' + c }, fmtN(v))))),
      d.event_names && d.event_names.length ? h('div', { class: 'chips', style: { marginTop: '10px' } }, d.event_names.map(n => h('span', { class: 'chip' }, n))) : null));
}

async function switchSaveMenu(anchor) {
  const r = await act(() => api('/api/saves')); if (!r) return;
  popMenu(anchor, [...r.entries.map(k => ({
    label: `${k.name} — ${k.pilot} (${lvl(k.level)})${k.active ? '  ✓' : ''}`, ic: k.active ? 'check' : 'save',
    fn: () => act(() => api('/api/saves/active', { id: k.id }), T('Active save: {0}', k.name)).then(() => poll()),
  })), '-', { label: T('New save…'), ic: 'plus', fn: () => newSaveModal() }, { label: T('Manage saves'), ic: 'save', fn: () => go('saves') }]);
}

// ================================================================== PLAY WITH YOUR FRIENDS (friends.py, /api/arkadas)
const IP_KIND = { local: [N('Home network'), 'ok'], radmin: [N('Radmin VPN'), 'info'], tailscale: [N('Tailscale'), 'info'], general: [N('Public'), 'orange'],
  connection: [N('Link-local'), ''] };
const FRD_STATUS = { connecting: [N('Connecting'), 'info'], in_game: [N('In game'), 'ok'], leaving: [N('Leaving'), 'orange'], finished: [N('Left'), ''],
  error: [N('Error'), 'err'] };
const FRD_ACTIVE = s => ['connecting', 'in_game', 'leaving'].includes(s);
const FRD = { tab: null, address: null, password: '', record: null, info: null, data: null };
const copyText = t => navigator.clipboard.writeText(t).then(() => toast(T('Copied: {0}', t), 'ok'), () => toast(t, 'info'));
const clock = sec => sec ? new Date(sec * 1000).toLocaleTimeString(LOC(), { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';

async function renderFriends() {
  const v = await act(() => api('/api/friend'));
  if (!v || S.page !== 'friend') return;
  FRD.data = v;
  drawFriends();
}
function drawFriends() {
  const v = FRD.data, d = S.state;
  if (!FRD.tab) FRD.tab = v.guest.state !== 'none' ? 'join' : 'host';
  if (FRD.address == null) FRD.address = v.guest.last_address || '';
  const tabs = h('div', { class: 'seg' }, [['host', T('Host a server')], ['join', T('Join a friend')]].map(([k, t]) =>
    h('button', { class: FRD.tab === k ? 'on info' : '', onclick: () => { FRD.tab = k; drawFriends(); } }, t)));
  $('#content').replaceChildren(h('div', { class: 'stack', id: 'friend' }, h('div', { class: 'row' }, tabs),
    ...(FRD.tab === 'host' ? hostView(v) : joinView(v))));
  S.sig.friendsMode = friendsMode(v, d); S.sig.friendsDyn = friendsDyn(v);
}
const friendsMode = (v, d) => JSON.stringify([FRD.tab, v.host.on, v.guest.state, d?.play, srvState(d), v.saves.map(k => k.id), d?.active?.id]);
const friendsDyn = v => JSON.stringify([v.host.guests, v.guest.steps, v.guest.last_sync, v.guest.connection, v.guest.not, v.host.public_ip]);
async function friendsTick() {
  if (S.friendsBusy) return;
  S.friendsBusy = true;
  let v;
  try { v = await api('/api/friend'); } catch (e) { return; } finally { S.friendsBusy = false; }
  if (S.page !== 'friend') return;
  FRD.data = v;
  if (friendsMode(v, S.state) !== S.sig.friendsMode) return drawFriends();
  if (friendsDyn(v) === S.sig.friendsDyn) return;
  S.sig.friendsDyn = friendsDyn(v);
  const g = $('#friend-guests'); if (g) g.replaceWith(guestsCard(v.host));
  const j = $('#friend-join-status'); if (j) j.replaceWith(joinStatus(v));
}

function launchSteps(o) {
  const recent = o.finished && (Date.now() / 1000 - o.finished < 45);
  if (!o.steps.length || !(o.running || o.error || recent)) return null;
  return stepList(o.steps);
}
const stepList = list => h('div', { class: 'steps' }, list.map(s => [h('div', { class: 'step ' + s.state },
  h('span', { class: 'ic' }, s.state === 'running' ? h('span', { class: 'spin' }) : icon(s.state === 'error' ? 'x' : 'check')),
  h('span', null, s.text), h('span', { class: 'dim small', style: { marginLeft: 'auto' } }, s.time)),
  s.progress && s.state === 'running' ? prepBox(s.progress) : null]));

// BepInEx's first-start preparation (client_patch.warm_up/progress): the game window is not visible yet, so the player does not think the game failed to open
const PREP_STAGE = [N('Starting the client'), N('Generating bridge assemblies'), N('Writing files')];
function prepBox(p) {
  return h('div', { class: 'prep' },
    h('div', { class: 'prep-head' }, icon('zap'), h('span', null, T('Preparing the fixes for the first launch')), h('b', null, '%' + p.percent)),
    h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: p.percent + '%' } }))),
    h('div', { class: 'prep-stages' }, PREP_STAGE.map((a, i) => {
      const st = i < p.stage ? 'done' : i === p.stage ? 'running' : 'waiting';
      return h('div', { class: 'prep-stage ' + st }, h('span', { class: 'ic' }, st === 'done' ? icon('check') : st === 'running'
        ? h('span', { class: 'spin' }) : h('span', { class: 'dot-sm' })), h('span', null, T(a)));
    })),
    h('div', { class: 'small muted' }, T("This happens only once, on the first launch; the game window stays hidden meanwhile. When it's done the game opens by itself, you don't need to press anything."),
      ' ', h('span', { class: 'dim' }, T('Elapsed: {0}', fmtDur(p.elapsed_sec)))));
}

// ---- Host
function hostView(v) {
  const dmg = v.host, d = S.state, st = srvState(d), busy = d?.play?.running, running = st.client === 'on';
  const single = st.game === 'on' && !dmg.on, guest = FRD_ACTIVE(v.guest.state);
  const left = h('div', null, h('div', { class: 'slot-name' }, T('Friend server')),
    h('div', { class: 'pilot' }, dmg.on ? T('Your server is running') : T('Server off'),
      dmg.on ? badge(T('{0} / {1} guests', dmg.guests.length, dmg.max_count), 'ok') : null, dmg.password ? badge(T('Password protected'), 'info') : null),
    h('div', { class: 'muted' }, dmg.on ? T('Your friends join with one of the addresses below. You play with your own save.')
      : T('When you host, you play with your own save; your friends join with theirs.')),
    d?.active ? h('div', { class: 'meta' }, h('span', null, T('Save:') + ' ', h('b', null, d.active.name)), h('span', null, T('Pilot') + ' ', h('b', null, d.active.pilot))) : null,
    v.world ? hostWorldChip(v) : null);                                // the server's world (world_editor.js)
  let main; const sub = [];
  if (busy) main = h('button', { class: 'play-btn busy', disabled: true }, h('span', { class: 'spin', style: { borderTopColor: '#021120' } }), T('STARTING'));
  else if (dmg.on && running) main = h('button', { class: 'play-btn running', disabled: true }, icon('check'), T('GAME RUNNING'));
  else main = h('button', { class: 'play-btn', disabled: !d?.active || guest || (running && !dmg.on), onclick: () => act(() => api('/api/friend/host', {})) },
    icon(dmg.on ? 'play' : 'users'), dmg.on ? T('PLAY') : T('HOST'));
  if (dmg.on) sub.push(btn(T('Stop server'), async () => {
    if (dmg.guests.length && !await confirmBox(T('Stop the server?'), T('Connected guests are dropped from the game; their saves stay on their own computers in their latest state.'),
      { ok: T('Close'), danger: true })) return;
    act(() => api('/api/server/stop', {}), T('Servers stopped.'));
  }, 'danger sm', 'stop', { disabled: running || busy }));
  else sub.push(btn(T('Start the server only'), () => act(() => api('/api/friend/host', { server_only: true })), 'ghost sm', 'server',
    { disabled: !d?.active || guest || busy }));
  const hint = guest ? T("You are on a friend's server right now: leave it first.") : single ? T('Your single-player server is running: Host restarts it as a friend server.')
    : dmg.on ? (S.panelCfg?.when_client_closes === 'on' ? T('The server stays on when you close the game.') : T('The server also stops when you close the game (Server > Behavior).')) : null;
  const hero = h('div', { class: 'hero' }, left, h('div', { class: 'play-col' }, main, h('div', { class: 'play-sub' }, sub), hint ? h('div', { class: 'small muted' }, hint) : null));
  const steps = d?.play ? launchSteps(d.play) : null;

  // settings
  const pw = h('input', { class: 'input', value: dmg.password, placeholder: T('No password'), maxlength: 64 });
  const max = h('select', { class: 'input', style: { width: '110px' } }, Array.from({ length: 16 }, (_, i) => i + 1).map(n => h('option', { value: n, selected: n === dmg.max_count }, n)));
  const save = () => act(() => api('/api/friend/settings', { password: pw.value, max_count: +max.value }), T('Saved.'))
    .then(r => { if (r) { FRD.data = r; } });
  pw.addEventListener('change', save); max.addEventListener('change', save);
  const world = v.world ? h('select', { class: 'input', onchange: e => act(() => api('/api/friend/settings', { world: e.target.value }), T('Saved.'))
    .then(r => { if (r) { FRD.data = r; drawFriends(); } }) },
    h('option', { value: '', selected: !v.world.choice }, T("Your save's world ({0})", v.world.save_world.name)),
    v.world.entries.map(w => h('option', { value: w.id, selected: v.world.choice === w.id }, w.name))) : null;
  const setCard = h('div', { class: 'card' }, h('h2', null, icon('sliders'), T('Server settings')),
    h('div', { class: 'grid g2' }, field(T('Join password'), pw), field(T('Maximum guests'), max)),
    world ? h('div', { style: { marginTop: '12px' } }, field(T("Server's world"), world),
      h('p', { class: 'small muted', style: { margin: '6px 0 0' } }, T('Guests play in this world too (maps, aliens, quests, shop). You prepare worlds in the World Editor.'))) : null,
    h('p', { class: 'desc', style: { marginTop: '10px' } }, dmg.on ? T('Changes take effect when the server restarts.')
      : T('A password stops anyone who knows your address from joining. Guests enter it under Join a friend.')));

  // addresses
  const ipRow = (ip, kind) => h('div', { class: 'row between' }, h('b', { class: 'mono' }, ip), h('span', { class: 'row', style: { gap: '6px' } },
    badge(T((IP_KIND[kind] || IP_KIND.general)[0]), (IP_KIND[kind] || IP_KIND.general)[1]), btn('', () => copyText(ip), 'ghost sm', 'copy', { title: T('Copy') })));
  const addrCard = h('div', { class: 'card' }, h('h2', null, icon('globe'), T('Address to give your friends')),
    h('div', { class: 'stack', style: { gap: '8px' } }, dmg.ips.map(x => ipRow(x.ip, x.type)),
      dmg.public_ip ? ipRow(dmg.public_ip, 'general') : h('div', { class: 'row' }, btn(T('Find my public IP'), async () => {
        const r = await act(() => api('/api/friend/public_ip', {})); if (r) { FRD.data.host.public_ip = r.ip; drawFriends(); }
      }, 'sm', 'search'), h('span', { class: 'small dim' }, T('Asks api.ipify.org.')))),
    h('p', { class: 'desc', style: { marginTop: '12px' } }, T('If you are in the same home (same router), give your home network address. For friends over the internet, give your public IP (with port forwarding) or your virtual network address (Radmin VPN, ZeroTier, Tailscale).')));

  // ports
  const portCard = h('div', { class: 'card' }, h('h2', null, icon('shield'), T('Ports to open')),
    h('table', { class: 'table' }, h('thead', null, h('tr', null, h('th', null, T('Protocol')), h('th', null, T('Port')), h('th', null, T('Used for')))),
      h('tbody', null, [['TCP', dmg.game_port, T('Game and account upload')], ['TCP', dmg.chat_port, T('Chat')]].map(([a, b, c]) =>
        h('tr', null, h('td', null, h('b', null, a)), h('td', { class: 'mono' }, b), h('td', null, c))))),
    h('p', { class: 'desc', style: { marginTop: '10px' } }, T('No UDP port is needed. The web login (80, 8090) stays on this computer only; do not open those.')),
    h('div', { class: 'stack', style: { gap: '8px', marginTop: '6px' } },
      S.state?.panel?.platform && S.state.panel.platform !== 'win32'
        ? h('div', { class: 'note' }, h('b', null, '1. '), T("Firewall: if macOS asks, allow incoming connections for Python. On Linux, if a firewall (e.g. ufw) is on:"),
          h('div', { class: 'cmd', style: { marginTop: '6px' } }, `sudo ufw allow ${dmg.game_port},${dmg.chat_port}/tcp`))
        : h('div', { class: 'note' }, h('b', null, '1. '), T('Windows Firewall: when the server first starts, allow access in the window shown for Python (Private networks). If no window appeared, in a command prompt opened as administrator:'),
          h('div', { class: 'cmd', style: { marginTop: '6px' } }, `netsh advfirewall firewall add rule name="DarkOrbit" dir=in action=allow protocol=TCP localport=${dmg.game_port},${dmg.chat_port}`)),
      h('div', { class: 'note' }, h('b', null, '2. '), T('On the same home network nothing else is needed.')),
      h('div', { class: 'note' }, h('b', null, '3. '), T("Over the internet: in your router's settings, forward TCP ports {0} and {1} to this computer's home network address (port forwarding / Virtual server / NAT).", dmg.game_port, dmg.chat_port)),
      h('div', { class: 'note' }, h('b', null, '4. '), T("If your internet provider uses CGNAT (the router's WAN address differs from your public IP), forwarding will not work: set up a virtual network such as Radmin VPN, ZeroTier or Tailscale and give the address on that network."))));

  // shared world
  const share = h('div', { class: 'card' }, h('h2', null, icon('info'), T('Shared universe')),
    h('div', { class: 'check-list' }, [N('Company, battle and Blacklight maps (1-1 … 5-4, BL) are shared: aliens, boxes and ores are shared and you see each other.'),
      N("Gate, mode and event maps are each player's own copy."), N("Chat is shared; mail, clan and auction are each player's own."),
      N('Your game settings (multipliers, events) also apply to your guests.'),
      N("Guests' saves are not written to this computer and do not appear on the Saves page: their progress is saved on their own computers."),
      N('Players cannot attack each other (no PvP).')].map(t => h('div', null, icon('check'), h('span', null, T(t))))));
  return [hero, steps ? h('div', { class: 'card' }, h('h2', null, icon('zap'), T('Server launch')), steps) : null, guestsCard(dmg),
    h('div', { class: 'grid g2' }, addrCard, setCard), h('div', { class: 'grid g2' }, portCard, share)].filter(Boolean);
}
function guestsCard(dmg) {
  if (!dmg.on) return h('div', { id: 'friend-guests' });
  const now = Date.now() / 1000;
  return h('div', { class: 'card', id: 'friend-guests' }, h('h2', null, icon('users'), T('Guests')),
    dmg.guests.length ? h('table', { class: 'table' },
      h('thead', null, h('tr', null, [T('Pilot'), T('Level'), T('Map'), T('Address'), T('Status'), T('Duration'), ''].map(x => h('th', null, x)))),
      h('tbody', null, dmg.guests.map(g => h('tr', null, h('td', null, h('b', null, g.name)), h('td', null, g.level), h('td', null, g.map || '—'),
        h('td', { class: 'mono' }, g.ip), h('td', null, g.connected ? badge(T('In game'), 'ok') : badge(T('Not connected'), '')), h('td', null, fmtDur(now - g.entry)),
        h('td', { class: 'num' }, btn(T('Kick'), async () => {
          if (await confirmBox(T('Kick {0}?', g.name), T('Their connection is closed. Their save stays on their own computer in its latest state.'), { ok: T('Kick'), danger: true }))
            act(() => api('/api/friend/kick', { session: g.session }), T('{0} removed.', g.name));
        }, 'ghost sm', 'x')))))) :
      h('p', { class: 'desc' }, T('No guests yet. Your friends connect by entering your address under Play with Friends > Join a friend.')));
}

// ---- Join
function joinView(v) {
  const m = v.guest;
  if (FRD_ACTIVE(m.state)) return [joinStatus(v), joinInfo()];
  const d = S.state, st = srvState(d);
  const address = h('input', { class: 'input', value: FRD.address, placeholder: '192.168.1.20', oninput: e => { FRD.address = e.target.value; } });
  const pw = h('input', { class: 'input', type: 'password', value: FRD.password, placeholder: T('Leave empty if there is no password'), oninput: e => { FRD.password = e.target.value; } });
  const slot = h('select', { class: 'input', onchange: e => { FRD.record = e.target.value; } },
    v.saves.map(k => h('option', { value: k.id, selected: k.id === (FRD.record || v.active) }, `${k.name} — ${k.pilot} (${lvl(k.level)})`)));
  const info = h('div', { id: 'friend-info' }, FRD.info ? serverInfo(FRD.info, v) : null);
  const test = btn(T('Test connection'), async ev => {
    const b = ev.currentTarget; b.disabled = true;
    const r = await act(() => api('/api/friend/test', { address: address.value }));
    b.disabled = false; FRD.info = r || null;
    info.replaceChildren(r ? serverInfo(r, v) : '');
  }, 'sm', 'search');
  const blocked = st.game === 'on' ? T('Your own server is running: stop it first to join.') : st.client === 'on' ? T('The game is open: close it first.')
    : !v.saves.length ? T('First create a save on the Saves page.') : null;
  const join = h('button', { class: 'play-btn', disabled: !!blocked, onclick: () =>
    act(() => api('/api/friend/join', { address: address.value, password: pw.value, record: slot.value })).then(r => { if (r) renderFriends(); }) }, icon('play'), T('JOIN'));
  const left = h('div', { class: 'stack', style: { gap: '12px' } }, h('div', { class: 'slot-name' }, T("Join your friend's server")),
    field(T("Your friend's address (IP or domain name)"), h('div', { class: 'row' }, address, test)), h('div', { class: 'grid g2' }, field(T('Password'), pw), field(T('Save to use'), slot)), info);
  const hero = h('div', { class: 'hero' }, left, h('div', { class: 'play-col' }, join,
    h('div', { class: 'small muted' }, blocked || T("Your save is backed up, sent to your friend's server and the game opens."))));
  const last = ['finished', 'error'].includes(m.state) ? h('div', { class: 'card' }, h('h2', null, icon(m.state === 'error' ? 'alert' : 'check'),
    m.state === 'error' ? T('Join failed') : T('Last session')), stepList(m.steps),
    m.not ? h('div', { class: 'alert warning', style: { marginTop: '10px' } }, icon('alert'), h('div', null, m.not)) : null,
    m.last_sync ? h('p', { class: 'desc', style: { marginTop: '10px' } }, T('Last save sync: {0}', clock(m.last_sync))) : null) : null;
  return [hero, last, joinInfo()].filter(Boolean);
}
function serverInfo(r, v) {
  const sameClient = !r.client || r.client === v.client_version;
  return h('div', { class: 'stack', style: { gap: '10px' } },
    h('div', { class: 'kv' }, [[T('Server'), r.address], [T('Host pilot'), r.pilot || '—'], [T('Players'), (r.players || []).join(', ') || '—'],
      [T('Guests'), `${r.guest} / ${r.max_count}`], [T('Password'), r.password ? T('Required') : T('None')], [T('Game version'), r.client || '—']].map(([a, b]) =>
      h('div', null, h('span', null, a), h('b', null, b)))),
    h('div', { class: 'wz-summary' }, checkRow(r.compatible, r.compatible ? T('Panel versions match') : T('Panel versions differ: both of you should update the panel')),
      checkRow(sameClient, sameClient ? T('Same game version') : T('Different game version (yours {0})', v.client_version)),
      checkRow(r.place, r.place ? T('Server has room') : T('Server full'))));
}
function joinStatus(v) {
  const m = v.guest, [t, c] = FRD_STATUS[m.state] || [m.state, ''];
  const slot = v.saves.find(k => k.id === m.record);
  return h('div', { class: 'card', id: 'friend-join-status' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('users'), T("Your friend's server")), badge(T(t), c)),
    h('div', { class: 'kv', style: { margin: '12px 0' } }, [[T('Address'), m.address], [T('Host pilot'), m.server?.pilot || '—'],
      [T('Save file'), slot ? `${slot.name} — ${slot.pilot}` : m.record], [T('Last sync'), clock(m.last_sync)],
      [T('Connection'), m.connection ? T('Good') : T('Lost, retrying…')]].map(([a, b]) => h('div', null, h('span', null, a), h('b', null, b)))),
    stepList(m.steps),
    m.not ? h('div', { class: 'alert warning', style: { marginTop: '10px' } }, icon('alert'), h('div', null, m.not)) : null,
    h('div', { class: 'row', style: { marginTop: '14px' } }, btn(T('Leave'), async () => {
      if (await confirmBox(T("Leave your friend's server?"), T('The game closes and the latest state of your save is written to this computer.'), { ok: T('Leave'), danger: true }))
        act(() => api('/api/friend/leave', {})).then(() => friendsTick());
    }, 'danger', 'power', { disabled: m.state === 'leaving' }), h('span', { class: 'small muted' }, T('Closing the game also leaves.'))));
}
const joinInfo = () => h('div', { class: 'card' }, h('h2', null, icon('info'), T('Where is my save?')),
  h('div', { class: 'check-list' }, [N('Your save is backed up before joining (Saves > Backups).'),
    N('While you play, your progress is written to your save on this computer every few seconds; its final state is saved when you leave.'),
    N("Your save is not written to your friend's computer and does not appear on their Saves page."),
    N("Your friend's game settings (multipliers, events) apply on their server."),
    N("Your friend's server: TCP ports 8081 (game) and 7771 (chat) must be open on their side.")].map(t => h('div', null, icon('check'), h('span', null, T(t))))));

// ================================================================== SAVES
// Saves page and character editor: saves.js. Here the new pilot form and the backups window (the setup wizard uses them too).

// ---- new pilot form (New save window and the setup wizard)
const FIRMS = [[1, 'MMO', 'Mars Mining Operations', 'var(--mmo)', '1-1'], [2, 'EIC', 'Earth Industries Corp.', 'var(--eic)', '2-1'],
  [3, 'VRU', 'Venus Resources Unlimited', 'var(--vru)', '3-1']];
function pilotForm({ start = true } = {}) {
  const st = { company: 2 };
  const name = h('input', { class: 'input', placeholder: T('e.g. Main save, Quick test…') });
  const pilot = h('input', { class: 'input', placeholder: T('3-20 characters'), maxlength: 20 });
  // starting values (optional; empty: the template's): credits, uridium, level (its EP is the level's threshold), honor, ammo
  const num = (min, max) => h('input', { class: 'input', type: 'number', min, max, step: 1, placeholder: T('template value') });
  const credits = num(0), uri = num(0), level = num(1, 50), honor = num(0), laser = num(0), rocket = num(0);
  const progressive = h('input', { type: 'checkbox' }), campaign = h('input', { type: 'checkbox' });
  const cards = FIRMS.map(([id, k, n, c, m]) => {
    const el = h('div', { class: 'radio-card' + (id === st.company ? ' on' : ''), style: { '--c': c }, onclick: () => {
      st.company = id; el.parentNode.querySelectorAll('.radio-card').forEach(x => x.classList.remove('on')); el.classList.add('on');
    } }, art('company_' + k.toLowerCase(), 'crest'), h('b', null, k), h('span', null, n), h('span', null, T('Start: {0}', m)));
    return el;
  });
  const el = [field(T('Pilot name (shown in the game)'), pilot), field(T('Company'), h('div', { class: 'radio-cards' }, cards)),
    field(T('Save name (optional)'), name),
    start ? h('div', { class: 'grid g2' }, field(T('Starting credits (optional)'), credits), field(T('Starting uridium (optional)'), uri),
      field(T('Starting level (1-50, optional)'), level), field(T('Starting honor (optional)'), honor),
      field(T('LCB-10 laser ammo (optional)'), laser), field(T('R-310 rockets (optional)'), rocket)) : null,
    h('label', { class: 'row small', title: T('The Season Pass starts from the first season (Mobius); when a season ends the next one opens, up to the newest. Seasons added later also open in turn. When off, it is always the newest season.') },
      h('span', { class: 'switch' }, progressive, h('span')), T('Unlock seasons in order from the first')),
    h('label', { class: 'row small', title: T('The new-server "Level 1", "Level 5" … "Level 25" quests: big rewards (ships, equipment, uridium, Premium) as you reach each level. They stay in the quest list for 30 days from when the save is created. When off, these quests never appear.') },
      h('span', { class: 'switch' }, campaign, h('span')), T('Starter campaign'))];
  const v = x => start ? x.value : '';
  return { el, pilot, values: () => ({ name: name.value.trim() || pilot.value.trim(), pilot: pilot.value.trim(), company: st.company,
    credits: v(credits), uridium: v(uri), level: v(level), honor: v(honor), laser: v(laser), rocket: v(rocket), progressive: progressive.checked, campaign: campaign.checked }) };
}

function newSaveModal() {
  const f = pilotForm();
  const active = h('input', { type: 'checkbox', checked: true });
  const m = modal({
    title: T('New save'), sub: T('Starts from scratch with a new pilot. Your other saves are not affected.'),
    body: [...f.el, h('label', { class: 'row small' }, h('span', { class: 'switch' }, active, h('span')), T('Make it the active save'))],
    foot: [btn(T('Cancel'), () => m.close(), 'ghost'), btn(T('Create'), async ev => {
      const b = ev.currentTarget; b.disabled = true;
      const r = await act(() => api('/api/saves/new', Object.assign(f.values(), { set_active: active.checked })), T('Save created.'));
      b.disabled = false;
      if (r) { m.close(); if (S.page === 'saves') renderSaves(); poll(); }
    }, 'primary', 'plus')],
  });
}

async function backupsModal(id) {
  let m;
  async function load() {
    const r = await act(() => api('/api/backups?id=' + encodeURIComponent(id))); if (!r) return;
    const k = r.record, cfg = r.settings;
    const note = h('input', { class: 'input', placeholder: T('Note (optional): e.g. Before the gate') });
    const take = btn(T('Back up now'), () => act(() => api('/api/backups/buy', { id, note: note.value }), T('Backup taken.')).then(load), 'primary', 'save');
    const tog = h('input', { type: 'checkbox', checked: cfg.backup_on_launch, onchange: e => act(() => api('/api/panel_settings', { values: { backup_on_launch: e.target.checked } }), T('Saved.')) });
    const keep = h('input', { class: 'input num', type: 'number', min: 1, max: 200, value: cfg.backup_count,
      onchange: e => act(() => api('/api/panel_settings', { values: { backup_count: +e.target.value } }), T('Saved.')) });
    const iv = h('input', { class: 'input num', type: 'number', min: 0, max: 600, value: cfg.backup_interval_min,
      onchange: e => act(() => api('/api/panel_settings', { values: { backup_interval_min: +e.target.value } }), T('Saved.')) });
    const rows = r.entries.map(b => h('tr', null,
      h('td', null, h('div', null, fmtWhen(b.time)), h('div', { class: 'dim small' }, b.time)),
      h('td', null, badge(b.kind_name, b.type === 'manual' ? 'info' : b.type === 'before' ? 'orange' : '')),
      h('td', null, `${b.pilot} · ${lvl(b.level)}`), h('td', { class: 'num' }, fmtN(b.credits)), h('td', { class: 'num' }, fmtN(b.uridium)),
      h('td', { class: 'small muted' }, b.not_ || ''),
      h('td', { class: 'num' }, h('div', { class: 'actions', style: { justifyContent: 'flex-end', flexWrap: 'nowrap' } },
        btn(T('Restore'), async () => {
          if (await confirmBox(T('Restore the backup?'), T('The save "{0}" goes back to {1}. The current state is kept first as a "Before restore" backup.', k.name, b.time), { ok: T('Restore') }))
            act(() => api('/api/backups/restore', { id, file: b.file }), T('Restored.')).then(load);
        }, 'sm', 'undo', { disabled: k.in_use, title: k.in_use ? T("Can't restore while the game is running") : '' }),
        btn('', ev => popMenu(ev.currentTarget, [
          { label: T('Open as a new save'), ic: 'plus', fn: async () => { const v = await promptBox(T('New save from backup'), T('Name of the new save'), `${k.name} (${b.time.slice(0, 10)})`); if (v != null) act(() => api('/api/backups/new_save', { id, file: b.file, name: v }), T('New save created.')).then(() => S.page === 'saves' && renderSaves()); } },
          { label: T('Note'), ic: 'note', fn: async () => { const v = await promptBox(T('Backup note'), T('Note'), b.not_); if (v != null) act(() => api('/api/backups/note', { id, file: b.file, note: v })).then(load); } },
          '-',
          { label: T('Delete'), ic: 'trash', danger: true, fn: async () => { if (await confirmBox(T('Delete the backup?'), T('The {0} backup will be deleted from disk.', b.time), { ok: T('Delete'), danger: true })) act(() => api('/api/backups/delete', { id, file: b.file }), T('Backup deleted.')).then(load); } },
        ]), 'ghost sm icon', 'more')))));
    const body = [
      k.in_use ? h('div', { class: 'alert info' }, icon('info'), h('div', null, T('The save is in the game: you can take backups; close the game and the server to restore.'))) : null,
      h('div', { class: 'row' }, note, take, btn(T('Folder'), () => act(() => api('/api/open_folder', { what: 'backup', id })), 'ghost', 'folder')),
      h('div', { class: 'row wrap small muted', style: { gap: '18px' } },
        h('label', { class: 'row' }, h('span', { class: 'switch' }, tog, h('span')), T("Back up automatically on Play")),
        h('label', { class: 'row' }, T('Automatic backups to keep'), keep),
        h('label', { class: 'row' }, T('During the game every'), iv, T('minutes (0: off)'))),
      rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, [[N('Time'), ''], [N('Type'), ''], [N('Pilot'), ''], [N('Credits'), 'num'], [N('Uridium'), 'num'], [N('Note'), ''], ['', '']].map(([x, c]) => h('th', { class: c }, x ? T(x) : '')))),
        h('tbody', null, rows))) : h('div', { class: 'empty' }, art('empty_save'), h('div', null, T('This save has no backups.'))),
      h('div', { class: 'small dim' }, T('Manual backups are never deleted automatically. The newest {0} automatic backups are kept.', cfg.backup_count))];
    if (m) { m.box.querySelector('.body').replaceChildren(...body.filter(Boolean)); }
    else m = modal({ title: T('Backups — {0}', k.name), sub: `${k.pilot} · ${k.company} · ${T('Level')} ${k.level}`, wide: true, body, foot: [btn(T('Close'), () => m.close(), '')],
      onclose: () => { if (S.page === 'saves') renderSaves(); } });
  }
  load();
}

// ================================================================== GAME SETTINGS
const MULTIPLIER_VALUES = [0, 0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4, 5, 6, 7.5, 10, 12.5, 15, 20, 25, 30, 40, 50];
const APPLY_WHEN = { 'instant': ['instant', N('Instant')], 'map': ['map', N('On map change')], 'login': ['entry', N('On next login')], 'restart': ['restart', N('On server restart')] };
let saveTimer = null, pending = {};
function queueSave(key, value) {
  pending[key] = value;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const body = pending; pending = {};
    const r = await act(() => api('/api/settings', { values: body }));
    if (r) { S.setting = r; markChanged(); flashSaved(); }
  }, 350);
}
function flashSaved() {
  const el = $('#saved-note'); if (!el) return;
  el.textContent = T('Saved ✓'); el.style.color = 'var(--ok)';
  clearTimeout(el._t); el._t = setTimeout(() => { el.textContent = T('Changes are saved automatically.'); el.style.color = ''; }, 1600);
}
function markChanged() {
  const r = S.setting; if (!r) return;
  document.querySelectorAll('.set-row[data-key]').forEach(row => {
    const k = row.dataset.key, v = r.values[k] ?? r.default[k];
    row.classList.toggle('changed', v !== r.default[k]);
  });
  document.querySelectorAll('.set-group').forEach(card => {         // number of settings changed in the group heading
    const n = card.querySelectorAll('.set-row.changed').length;
    card.querySelector('.grp-count').textContent = n ? ' · ' + T('{0} changes', n) : '';
  });
  document.querySelectorAll('.set-sub').forEach(sub => {            // number of sub-settings changed on the "Fine-tune" button
    const n = sub.querySelectorAll('.set-row.changed').length;
    document.querySelector(`.set-row[data-key="${sub.dataset.parent}"] .set-toggle .n`).textContent = n ? T('{0} custom', n) : '';
    paintEff(sub.dataset.parent);
  });
  if (S.settingsFilter && document.querySelector('.set-tools')) S.settingsFilter(true);
}

async function renderSettings() {
  const r = await act(() => api('/api/settings')); if (!r || S.page !== 'settings') return;
  S.setting = r;
  const val = k => r.values[k] ?? r.default[k];
  const presets = Object.entries(r.ready).map(([key, p]) => h('button', { class: 'preset', onclick: async () => {
    if (await confirmBox(T('Apply "{0}"?', p.name), T("All game settings switch to this preset's values (your event choices don't change)."), { ok: T('Apply') }))
      act(() => api('/api/settings/presets', { name: key }), T('"{0}" applied.', p.name)).then(renderSettings);
  } }, h('b', null, p.name), h('span', null, p.description)));
  const user = Object.entries(r.templates || {}).map(([key, p]) => h('div', { class: 'preset', onclick: async e => {
    if (e.target.closest('.x')) return;
    if (await confirmBox(T('Apply "{0}"?', p.name), T("All game settings switch to this template's values."), { ok: T('Apply') }))
      act(() => api('/api/settings/presets', { name: key }), T('"{0}" applied.', p.name)).then(renderSettings);
  } }, h('b', null, '★ ', p.name), h('span', null, T('{0} changes', Object.keys(p.values).length)),
    btn('', async () => { if (await confirmBox(T('Delete the template?'), T('The template "{0}" will be deleted.', p.name), { ok: T('Delete'), danger: true })) act(() => api('/api/settings/delete_template', { name: key })).then(renderSettings); }, 'ghost sm icon x', 'x', { title: T('Delete') })));
  const copySel = h('select', { class: 'input', style: { maxWidth: '240px' } }, (r.saves || []).map(k => h('option', { value: k.id }, k.name)));
  const saveCard = r.record ? h('div', { class: 'card' }, h('h2', null, icon('save'), T("This save's settings: {0}", r.save_name)),
    h('p', { class: 'desc' }, T('Game settings and event choices belong to each save; when the active save changes, the settings change too.')),
    (r.saves || []).length ? h('div', { class: 'row' }, copySel,
      btn(T('Copy from this save'), async () => {
        const src = r.saves.find(k => k.id === copySel.value);
        if (src && await confirmBox(T('Copy the settings?'), T('All game settings and event choices of the save "{0}" are copied to this save.', src.name), { ok: T('Copy') }))
          act(() => api('/api/settings/copy', { source: src.id }), T('Settings copied.')).then(renderSettings);
      }, 'sm', 'copy')) : null) : null;
  const presetCard = h('div', { class: 'card' }, h('h2', null, icon('star'), T('Presets')),
    h('p', { class: 'desc' }, T('Apply a set of settings with one click, or keep your current settings as a template.')),
    h('div', { class: 'preset-bar' }, presets, user),
    h('div', { class: 'row', style: { marginTop: '12px' } },
      btn(T('Save the current settings as a template'), async () => { const v = await promptBox(T('Save as template'), T('Template name'), ''); if (v) act(() => api('/api/settings/save_template', { name: v }), T('Template saved.')).then(renderSettings); }, 'sm', 'save'),
      h('span', { class: 'spacer' }),
      btn(T('Reset all to defaults'), async () => { if (await confirmBox(T('Reset to defaults?'), T("All game settings go back to their defaults (your event choices don't change)."), { ok: T('Revert') })) act(() => api('/api/settings/reset', {}), T('Back to defaults.')).then(renderSettings); }, 'ghost sm', 'undo')));
  const info = h('div', { class: 'alert info' }, icon('info'), h('div', null,
    h('span', { id: 'saved-note' }, T('Changes are saved automatically.')), ' ' + T('Tags show when a setting takes effect:') + ' ',
    ...Object.values(APPLY_WHEN).map(([c, t]) => [h('span', { class: 'tag ' + c }, T(t)), ' ']),
    r.server_running ? h('div', { style: { marginTop: '4px' } }, T('The server is running: "Instant" settings change in the game right away.')) : null));
  S.settingsOpen = S.settingsOpen || {};
  const groups = r.groups.map(g => {
    const items = r.schema.filter(s => s.group === g.key && !s.parent);
    if (!items.length) return null;
    return h('div', { class: 'card set-group', 'data-group': g.key }, h('h2', null, g.name, h('span', { class: 'muted small grp-count' })),
      items.map(s => {
        const row = settingRow(s, val(s.key), r.default[s.key]), kids = r.schema.filter(c => c.parent === s.key);
        return kids.length ? [row, subPanel(row, kids, val, r.default)] : row;
      }));
  }).filter(Boolean);
  // search, changed only, group shortcuts (the selections stay when the page refreshes too)
  const q = h('input', { class: 'input', type: 'search', placeholder: T('Search settings (name or description)…'), value: S.settingsSearch || '' });
  const only = h('input', { type: 'checkbox', checked: !!S.settingsChanged });
  const none = h('div', { class: 'card muted', hidden: true }, T('No setting matches the search.'));
  // keep: after a save (markChanged) it only shows, does not hide the visible row (so a row that returned to the default does not vanish while editing).
  // A sub-setting is also searched by its parent's name; the parent of a matching sub-setting becomes visible and its section opens.
  const apply = (keep = false) => {
    S.settingsSearch = q.value; S.settingsChanged = only.checked;
    const words = q.value.toLocaleLowerCase(LOC()).split(/\s+/).filter(Boolean), filt = words.length > 0 || only.checked;
    const hit = (row, extra = '') => { const text = (extra + ' ' + row.textContent).toLocaleLowerCase(LOC());
      return words.every(w => text.includes(w)) && (!only.checked || row.classList.contains('changed')); };
    let shown = 0;
    groups.forEach(card => {
      let n = 0;
      card.querySelectorAll('.set-row[data-key]:not(.sub)').forEach(row => {
        const sub = card.querySelector(`.set-sub[data-parent="${row.dataset.key}"]`);
        let kid = false;
        if (sub) sub.querySelectorAll('.set-row').forEach(c => {
          const ok = !filt || (keep && !c.hidden) || hit(c, row.querySelector('.name').textContent);
          c.hidden = !ok; kid = kid || (filt && ok);
        });
        const ok = (keep && !row.hidden) || hit(row) || kid;
        row.hidden = !ok; n += ok;
        if (sub) setOpen(row, sub, ok && (!!S.settingsOpen[row.dataset.key] || kid));
      });
      card.hidden = !n; shown += n;
    });
    none.hidden = !!shown;
  };
  S.settingsFilter = apply;
  q.addEventListener('input', () => apply()); only.addEventListener('change', () => apply());
  const jump = h('div', { class: 'chips' }, groups.map(card => h('button', { class: 'chip link', type: 'button',
    onclick: () => { if (card.hidden) { q.value = ''; only.checked = false; apply(); } card.scrollIntoView({ behavior: 'smooth', block: 'start' }); } },
    card.querySelector('h2').firstChild.textContent)));
  const tools = h('div', { class: 'card compact set-tools' },
    h('div', { class: 'row wrap' }, h('span', { class: 'search-box' }, icon('search'), q),
      h('label', { class: 'row', style: { gap: '8px' } }, h('span', { class: 'switch' }, only, h('span')), T('Changed only'))),
    h('div', { style: { marginTop: '10px' } }, jump));
  $('#content').replaceChildren(h('div', { class: 'stack' }, saveCard, presetCard, info, tools, none, ...groups));
  apply();
  markChanged();
}

function settingRow(s, v, def) {
  const [tc, tagText] = APPLY_WHEN[s.apply_mode] || ['', s.apply_mode];
  // sub-setting (s.ust): on the parent, the apply label; in its place the effective multiplier (paintEff). data-v: the displayed value (even without releasing the slider)
  const row = h('div', { class: 'set-row' + (s.parent ? ' sub' : ''), 'data-key': s.key, 'data-v': v });
  // linked setting (s.condition): shown below it only while that on/off setting is on
  if (s.condition) { row.dataset.condition = s.condition; row.classList.toggle('condition-off', !(S.setting.values[s.condition] ?? S.setting.default[s.condition])); }
  const head = h('div', null, h('div', { class: 'name' }, s.name, s.parent ? h('span', { class: 'eff' }) : h('span', { class: 'tag ' + tc }, T(tagText))),
    h('div', { class: 'help' }, s.description));
  let ctl;
  // the slider is in the recommended range (min..max); any value up to limit can be typed by hand into the number box (settings.py), outside the range it is marked "manual"
  const top = s.cap ?? s.max;
  const over = h('span', { class: 'tag manual', title: T('Outside the recommended range ({0} – {1}); the largest value you can type is {2}.', fmtMult(s.min ?? 0), fmtMult(s.max ?? 0), fmtMult(top)) }, T('Manual'));
  const markOver = x => { over.hidden = !(x > s.max); };
  if (s.type === 'multiplier') {
    const vals = MULTIPLIER_VALUES.filter(x => x >= s.min && x <= s.max);
    if (!vals.includes(s.max)) vals.push(s.max);
    const near = x => vals.reduce((best_i, y, i) => Math.abs(y - x) < Math.abs(vals[best_i] - x) ? i : best_i, 0);
    const lab = h('span', { class: 'mult' }, '×' + fmtMult(v));
    const range = h('input', { type: 'range', min: 0, max: vals.length - 1, step: 1, value: near(v) });
    const num = h('input', { class: 'input num', type: 'number', min: s.min, max: top, step: 'any', value: v, title: T('At most {0}', fmtMult(top)) });
    const paint = () => range.style.setProperty('--p', (range.value / (vals.length - 1) * 100) + '%');
    const show = x => { num.value = x; lab.textContent = '×' + fmtMult(x); markOver(x); row.dataset.v = x; paintEff(s.parent || s.key); };
    range.addEventListener('input', () => { show(vals[+range.value]); paint(); });
    range.addEventListener('change', () => queueSave(s.key, vals[+range.value]));
    num.addEventListener('change', () => {
      const x = Math.min(top, Math.max(s.min, parseFloat(String(num.value).replace(',', '.')) || 0));
      show(x); range.value = near(x); paint(); queueSave(s.key, x);
    });
    const reset = btn('', () => { show(def); range.value = near(def); paint(); queueSave(s.key, def); }, 'ghost sm icon', 'undo', { title: T('Default (×{0})', fmtMult(def)) });
    paint(); markOver(v);
    ctl = h('div', { class: 'ctl' }, h('div', { style: { flex: 1, minWidth: '140px' } }, range), over, lab, num, reset);
  } else if (s.type === 'number') {
    const num = h('input', { class: 'input num', type: 'number', min: s.min, max: top, step: 1, value: v, title: T('At most {0}', fmtMult(top)) });
    const fix = x => Math.min(top, Math.max(s.min, Math.round(parseFloat(String(x).replace(',', '.')) || 0)));
    num.addEventListener('change', () => { const x = fix(num.value); num.value = x; markOver(x); queueSave(s.key, x); });
    const reset = btn('', () => { num.value = def; markOver(def); queueSave(s.key, def); }, 'ghost sm icon', 'undo', { title: T('Default ({0})', def) });
    markOver(v);
    ctl = h('div', { class: 'ctl' }, over, num, s.unit ? h('span', { class: 'mult' }, s.unit) : null, reset);
  } else if (s.type === 'bool') {
    const cb = h('input', { type: 'checkbox', checked: v, onchange: e => {
      queueSave(s.key, e.target.checked);
      document.querySelectorAll(`.set-row[data-condition="${s.key}"]`).forEach(c => c.classList.toggle('condition-off', !e.target.checked));
    } });
    ctl = h('div', { class: 'ctl' }, h('label', { class: 'switch' }, cb, h('span')));
  } else if (s.type === 'level') {
    // the options' description and color from the schema (settings.py: option_description, colors; arrive in the panel's language)
    const say = i => (s.option_description || [])[i] || '';
    const desc = h('div', { class: 'level-desc' }, say(v));
    const seg = h('div', { class: 'seg' }, s.options.map((name, i) => h('button', { class: (i === v ? 'on ' : '') + ((s.colors || [])[i] || ''), onclick: e => {
      seg.querySelectorAll('button').forEach(b => b.classList.remove('on')); e.currentTarget.classList.add('on'); desc.textContent = say(i); queueSave(s.key, i);
    } }, name)));
    ctl = h('div', { class: 'ctl', style: { flexDirection: 'column', alignItems: 'flex-end' } }, seg);
    head.append(desc);
  }
  row.append(head, ctl);
  return row;
}
// sub-settings (settings.py SUBS): a "Fine-tune" button on the parent's row, a section that opens below it (its open state stays in S.settingsOpen)
function subPanel(row, kids, val, defs) {
  const key = row.dataset.key;
  const sub = h('div', { class: 'set-sub', 'data-parent': key },
    h('p', { class: 'sub-note' }, T('Each row is multiplied by the overall multiplier above: overall ×2 and row ×3 give ×6.')),
    kids.map(c => settingRow(c, val(c.key), defs[c.key])));
  row.firstChild.append(h('button', { class: 'set-toggle', type: 'button', onclick: () => { S.settingsOpen[key] = sub.hidden; setOpen(row, sub, sub.hidden); } },
    icon('chevR'), T('Fine-tune'), h('span', { class: 'cnt' }, kids.length), h('span', { class: 'n' })));
  setOpen(row, sub, !!S.settingsOpen[key]);
  return sub;
}
function setOpen(row, sub, open) {
  sub.hidden = !open;
  const b = row.querySelector('.set-toggle'); b.classList.toggle('open', open); b.setAttribute('aria-expanded', String(open));
}
function paintEff(parent) {          // the effective multiplier of the sub-settings (general x sub): if general is not x1, "total ×6"
  const p = document.querySelector(`.set-row[data-key="${parent}"]`), sub = document.querySelector(`.set-sub[data-parent="${parent}"]`);
  if (!p || !sub) return;
  sub.querySelectorAll('.set-row').forEach(c => { c.querySelector('.eff').textContent = +p.dataset.v === 1 ? '' : T('total ×{0}', fmtMult(p.dataset.v * c.dataset.v)); });
}
const fmtMult = x => (Math.round(x * 100) / 100).toLocaleString(LOC());

// ================================================================== EVENTS
async function renderEvents(list) {
  const r = list || await act(() => api('/api/events')); if (!r || S.page !== 'events') return;
  const set = (key, v) => act(() => api('/api/events', { changes: { [key]: v } })).then(x => x && renderEvents(x));
  const bulk = (to, kind) => act(() => api('/api/events', { all: to, kind }), T('Updated.')).then(x => x && renderEvents(x));
  const row = e => {
    const state = e.state || 'calendar';
    const status = e.enabled ? badge(e.state === 'on' && !e.in_calendar ? T('On (manual)') : T('On'), 'ok')
      : e.suppressed_by ? badge(T('Off (conflict: {0})', e.suppressed_by), 'err')
      : badge(e.state === 'off' && e.in_calendar ? T('Off (manual)') : T('Off'), e.state === 'off' ? 'err' : '');
    const cal = e.in_calendar ? (e.time_left_sec != null ? T('on by calendar · {0} left', fmtDur(e.time_left_sec)) : T('on by calendar'))
      : (e.next_day != null ? T('by calendar in {0} days', e.next_day) : T('off by calendar now'));
    return h('div', { class: 'ev-row' },
      h('div', null, h('div', { class: 'name' }, e.name, status), h('div', { class: 'help muted small' }, e.description),
        h('div', { class: 'when' }, '📅 ', e.time, ' · ', cal),
        e.conflicting && e.conflicting.length ? h('div', { class: 'help muted small' }, T('Cannot run together with: {0}', e.conflicting.join(', '))) : null),
      h('div', { class: 'seg' }, [['calendar', T('By calendar'), 'info'], ['on', T('On'), 'ok'], ['off', T('Off'), 'err']].map(([k, t, c]) =>
        h('button', { class: (state === k ? 'on ' : '') + c, onclick: () => set(e.key, k === 'calendar' ? null : k) }, t))));
  };
  const yearly = r.filter(e => e.type === 'yearly'), weekly = r.filter(e => e.type === 'weekly');
  $('#content').replaceChildren(h('div', { class: 'stack' },
    h('div', { class: 'alert info' }, icon('info'), h('div', null, T("Event aliens, boxes and discounts on the map change while the game is running; the client's event icons and windows update when you re-enter the game (changing maps or logging out and in is enough).")),
      btn(T('Show on calendar'), () => go('calendar'), 'sm', 'agenda'), btn(T('Turn all events off'), () => bulk('off'), 'sm', 'power')),
    h('div', { class: 'card' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('calendar'), T('Yearly events')),
      h('div', { class: 'row wrap' }, btn(T('All by calendar'), () => bulk('calendar', 'yearly'), 'sm'), btn(T('Turn all on'), () => bulk('on', 'yearly'), 'sm'), btn(T('Turn all off'), () => bulk('off', 'yearly'), 'sm'))),
      h('p', { class: 'desc' }, T('They open by the real date; you can turn any event on or off at any time. Several events can run at once; of events that conflict (Battle Pass, map decoration, cargo box) only one: the one you turned on, otherwise the one that started first.')),
      yearly.map(row)),
    h('div', { class: 'card' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('clock'), T('Weekly events')),
      h('div', { class: 'row wrap' }, btn(T('All by calendar'), () => bulk('calendar', 'weekly'), 'sm'), btn(T('Turn all on'), () => bulk('on', 'weekly'), 'sm'), btn(T('Turn all off'), () => bulk('off', 'weekly'), 'sm'))),
      h('p', { class: 'desc' }, T('They run on certain days and hours of the week (local time). Choose "On" to keep them always active.')),
      weekly.map(row))));
}

// ================================================================== EVENT CALENDAR (event_schedule.py, /api/takvim)
// Views: hourly (the 24 hours of the selected day, rows and sessions), daily (the day's detailed list), weekly (7 days from Monday),
// monthly (6-week grid). Bar: filled per the calendar, outlined if manually open, faded if manually closed. Times are local time.
const CAL = { appearance: 'weekly', day: null, filter_by: { yearly: true, weekly: true, session: true }, search: '', data: null, coverage: null };
const CAL_VIEW = [['hourly', N('Hourly')], ['daily', N('Daily')], ['weekly', N('Weekly')], ['monthly', N('Monthly')]];
const CAL_COLOR = ['#38c4ff', '#ff8a3d', '#3ddc97', '#ff6b81', '#a29bfe', '#ffc857', '#1dd1a1', '#f368e0', '#54a0ff', '#ff7f50', '#00d2d3', '#c8d6e5'];
const calColor = k => { let x = 7; for (const c of k) x = (x * 31 + c.charCodeAt(0)) >>> 0; return CAL_COLOR[x % CAL_COLOR.length]; };
const dayStart = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const hhmm = ts => new Date(ts * 1000).toLocaleTimeString(LOC(), { hour: '2-digit', minute: '2-digit' });
const dfmt = (ts, o) => new Date(ts * 1000).toLocaleDateString(LOC(), o);
const calSpan = (s, e) => {                      // "24 Eki 19:00 – 23:00" ya da "14 Eki 00:00 – 1 Kas 24:00"
  const same = dayStart(new Date(s * 1000)).getTime() === dayStart(new Date((e - 1) * 1000)).getTime();
  const end = new Date(e * 1000), endTxt = end.getHours() || end.getMinutes() ? hhmm(e) : '24:00';
  return dfmt(s, { day: 'numeric', month: 'short' }) + ' ' + hhmm(s) + ' – ' + (same ? endTxt : dfmt(e - 1, { day: 'numeric', month: 'short' }) + ' ' + endTxt);
};
const KIND_NAME = { yearly: N('Yearly'), weekly: N('Weekly') };

function calRange() {
  const g = dayStart(CAL.day || new Date());
  if (CAL.appearance === 'weekly') { const a = addDays(g, -((g.getDay() + 6) % 7)); return [a, addDays(a, 7)]; }
  if (CAL.appearance === 'monthly') { const f = new Date(g.getFullYear(), g.getMonth(), 1); const a = addDays(f, -((f.getDay() + 6) % 7)); return [a, addDays(a, 42)]; }
  return [g, addDays(g, 1)];
}
function calGo(appearance, day) { if (appearance) CAL.appearance = appearance; if (day) CAL.day = day; renderCalendar(); }
function calShift(n) {
  const g = dayStart(CAL.day || new Date());
  calGo(null, CAL.appearance === 'monthly' ? new Date(g.getFullYear(), g.getMonth() + n, 1) : addDays(g, CAL.appearance === 'weekly' ? 7 * n : n));
}
function enterCalendar() {
  CAL.day = CAL.day || new Date();
  renderCalendar();
  S.timers.push(setInterval(() => { if (document.visibilityState === 'visible' && !document.querySelector('.modal')) renderCalendar(); }, 60000));
}
async function renderCalendar() {
  const [a, b] = calRange();
  let r;
  try { r = await api(`/api/calendar?start=${a.getTime() / 1000}&bit=${b.getTime() / 1000}`); } catch (e) { toast(e.message, 'err'); return; }
  if (S.page !== 'calendar') return;
  CAL.data = r; CAL.coverage = [a.getTime() / 1000, b.getTime() / 1000];
  drawCalendar();
}

// rows to show in the view: filters; events that are open in the range, have a session or were opened manually
function calRows() {
  const q = CAL.search.trim().toLocaleLowerCase(LOC());
  return CAL.data.events.filter(e => CAL.filter_by[e.type] && (!q || e.name.toLocaleLowerCase(LOC()).includes(q)))
    .map(e => Object.assign({}, e, { color: calColor(e.key), sessions: CAL.filter_by.session ? e.sessions.filter(s => s.ranges.length) : [] }))
    .filter(e => e.active_ranges.length || e.ranges.length || e.sessions.length);
}
function drawCalendar() {
  const r = CAL.data, [A, B] = CAL.coverage, g = CAL.appearance;
  const title = g === 'monthly' ? dfmt((A + B) / 2, { month: 'long', year: 'numeric' })
    : g === 'weekly' ? dfmt(A, { day: 'numeric', month: 'short' }) + ' – ' + dfmt(B - 1, { day: 'numeric', month: 'short', year: 'numeric' })
      : dfmt(A, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  const chip = (k, t) => h('button', { class: 'cal-filter' + (CAL.filter_by[k] ? ' on' : ''), onclick: () => { CAL.filter_by[k] = !CAL.filter_by[k]; drawCalendar(); } }, T(t));
  const search = h('input', { class: 'input', style: { width: '170px' }, placeholder: T('Search events…'), value: CAL.search,
    oninput: e => { CAL.search = e.target.value; clearTimeout(CAL.searchTimer); CAL.searchTimer = setTimeout(() => { drawCalendar(); const s = $('#cal-search'); if (s) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); } }, 250); } });
  search.id = 'cal-search';
  const bar = h('div', { class: 'card cal-toolbar' },
    h('div', { class: 'row between wrap' },
      h('div', { class: 'seg' }, CAL_VIEW.map(([k, t]) => h('button', { class: g === k ? 'on info' : '', onclick: () => calGo(k) }, T(t)))),
      h('div', { class: 'row' }, btn('', () => calShift(-1), 'ghost sm icon', 'arrowL', { title: T('Previous') }),
        btn(T('Today'), () => calGo(null, new Date()), 'sm'), btn('', () => calShift(1), 'ghost sm icon', 'arrowR', { title: T('Forward') }),
        h('b', { class: 'cal-title' }, title)),
      h('div', { class: 'row wrap' }, chip('yearly', N('Yearly')), chip('weekly', N('Weekly')), chip('session', N('Sessions')), search)),
    h('div', { class: 'cal-legend small muted' }, h('span', null, h('i', { class: 'cal-sw' }), T('by calendar')),
      h('span', null, h('i', { class: 'cal-sw forced' }), T('forced on')), h('span', null, h('i', { class: 'cal-sw off' }), T('forced off')),
      h('span', null, h('i', { class: 'cal-sw sub' }), T('session / spawn hours')),
      r.always_open ? h('span', { class: 'badge info' }, T('Game setting: sessions always open')) : null));
  const rows = calRows();
  const view = g === 'monthly' ? calMonth(rows) : g === 'daily' ? calDay(rows) : calGantt(rows);
  $('#content').replaceChildren(h('div', { class: 'stack' }, bar, calSummary(r), view));
}

// ---- summary: those open now and the upcoming ones (independent of the view)
function calSummary(r) {
  const now = Date.now() / 1000;
  const on = r.events.filter(e => e.enabled);
  const next = r.events.filter(e => e.state !== 'off' && e.next && e.next[0] > now + 1).sort((x, y) => x.next[0] - y.next[0]).slice(0, 8);
  const dotc = k => h('i', { class: 'cal-dot', style: { background: calColor(k) } });
  return h('div', { class: 'grid g2' },
    h('div', { class: 'card' }, h('h2', null, icon('zap'), T('Active now ({0})', on.length)),
      on.length ? h('div', { class: 'chips' }, on.map(e => h('button', { class: 'chip cal-chip', onclick: () => calDetail(e.key) }, dotc(e.key), e.name,
        e.state === 'on' && !e.in_calendar ? h('span', { class: 'dim' }, T('forced')) : e.time_left_sec != null ? h('span', { class: 'dim' }, fmtDur(e.time_left_sec)) : null)))
        : h('p', { class: 'desc' }, T('No event is active right now.'))),
    h('div', { class: 'card' }, h('h2', null, icon('clock'), T('Coming up')),
      next.length ? h('div', { class: 'cal-next' }, next.map(e => h('div', { class: 'row', onclick: () => calDetail(e.key) }, dotc(e.key),
        h('div', { class: 'grow' }, h('div', { class: 'ellipsis', style: { maxWidth: 'none' }, title: e.name }, e.name),
          h('div', { class: 'small muted' }, calSpan(e.next[0], e.next[1]))),     // the date is under the name: so the badge does not overflow in a narrow card
        badge(T('in {0}', fmtDur(e.next[0] - now)), 'info'))))
        : h('p', { class: 'desc' }, T('No event starts soon.'))));
}

// ---- hourly and weekly: timeline (an event per row, its sessions below)
function calGantt(rows) {
  const [A, B] = CAL.coverage, now = Date.now() / 1000, week = CAL.appearance === 'weekly';
  const pct = t => Math.max(0, Math.min(100, (t - A) * 100 / (B - A)));
  const cols = week ? 7 : 24;
  const bar = (s, e, cls, color, title) => h('div', { class: 'cal-b ' + cls, style: { left: pct(s) + '%', width: Math.max(0.25, pct(e) - pct(s)) + '%', '--c': color }, title });
  const nowLine = () => now >= A && now < B ? h('div', { class: 'cal-now', style: { left: pct(now) + '%' } }) : null;
  const ticks = Array.from({ length: cols }, (_, i) => {
    if (!week) return h('div', { class: 'cal-tick' }, String(i).padStart(2, '0'));
    const d = addDays(new Date(A * 1000), i), today = dayStart(new Date()).getTime() === d.getTime();
    return h('div', { class: 'cal-tick click' + (today ? ' today' : ''), title: T('Daily view'), onclick: () => calGo('daily', d) },
      d.toLocaleDateString(LOC(), { weekday: 'short', day: 'numeric' }));
  });
  const evRow = e => {
    const st = e.state, bars = st === 'on' ? [bar(A, B, 'forced', e.color, e.name + ' · ' + T('forced on'))]
      : e.ranges.map(([s, x]) => bar(s, x, st === 'off' ? 'off' : '', e.color, e.name + ' · ' + calSpan(s, x) + (st === 'off' ? ' · ' + T('forced off') : '')));
    return [h('div', { class: 'cal-row' }, h('div', { class: 'cal-name', onclick: () => calDetail(e.key), title: e.description || e.name },
      h('i', { class: 'cal-dot', style: { background: e.color } }), h('span', { class: 'ellipsis', style: { maxWidth: 'none' } }, e.name),
      st ? badge(st === 'on' ? T('forced on') : T('forced off'), st === 'on' ? 'ok' : 'err') : null),
      h('div', { class: 'cal-track', style: { '--cols': cols } }, bars, nowLine())),
    ...e.sessions.map(s => h('div', { class: 'cal-row sub' }, h('div', { class: 'cal-name', title: s.maps.join(', ') }, '↳ ', h('span', { class: 'ellipsis', style: { maxWidth: 'none' } },
      s.name + (s.maps.length ? ' · ' + s.maps.join(', ') : ''))),
      h('div', { class: 'cal-track', style: { '--cols': cols } }, s.ranges.map(([a, b, f]) => bar(a, b, 'sub' + (f === 1 ? ' double' : ''), e.color,
        s.name + ' · ' + calSpan(a, b) + (f === 1 ? ' · ' + T('double rewards') : f > 1 ? ' · ' + T('entry until {0}', hhmm(f)) : ''))), nowLine())))];
  };
  return h('div', { class: 'card cal-gantt-card' }, rows.length ? h('div', { class: 'cal-gantt' },
    h('div', { class: 'cal-row head' }, h('div', { class: 'cal-name muted small' }, T('{0} events', rows.length)), h('div', { class: 'cal-track ticks', style: { '--cols': cols } }, ticks)),
    rows.map(evRow)) : h('div', { class: 'empty' }, art('empty_event'), h('div', null, T('No events to show in this range.'))));
}

// ---- daily: the selected day's detailed list (all-day ones, timed intervals and sessions in order)
function calDay(rows) {
  const [A, B] = CAL.coverage, now = Date.now() / 1000;
  const allDay = [], timed = [];
  for (const e of rows) {
    const iv = e.state === 'on' ? [[A, B]] : e.state === 'off' ? [] : e.ranges;
    if (iv.some(([s, x]) => s <= A && x >= B)) allDay.push(e);
    else iv.forEach(([s, x]) => timed.push({ e, s, x, name: e.name }));
    e.sessions.forEach(sec => sec.ranges.forEach(([s, x, f]) => timed.push({ e, s, x, f, name: e.name, sub: sec.name + (sec.maps.length ? ' · ' + sec.maps.join(', ') : '') })));
  }
  timed.sort((p, q) => p.s - q.s || p.x - q.x);
  const status = (s, x) => now >= x ? badge(T('Over'), '') : now >= s ? badge(T('Running · {0} left', fmtDur(x - now)), 'ok') : badge(T('in {0}', fmtDur(s - now)), 'info');
  const dotc = e => h('i', { class: 'cal-dot', style: { background: e.color } });
  const end = new Date(B * 1000);
  return h('div', { class: 'grid g2 tk-day' },
    h('div', { class: 'card' }, h('h2', null, icon('calendar'), T('All day ({0})', allDay.length)),
      allDay.length ? h('div', { class: 'stack', style: { gap: '10px' } }, allDay.map(e => h('div', { class: 'cal-item', onclick: () => calDetail(e.key) },
        h('div', { class: 'row' }, dotc(e), h('b', null, e.name), badge(T(KIND_NAME[e.type]), ''), e.state ? badge(e.state === 'on' ? T('forced on') : T('forced off'), e.state === 'on' ? 'ok' : 'err') : null),
        e.description ? h('div', { class: 'small muted' }, e.description) : null, h('div', { class: 'small dim' }, '📅 ', e.time))))
        : h('p', { class: 'desc' }, T('No all-day events on this day.'))),
    h('div', { class: 'card' }, h('h2', null, icon('clock'), T('Timed ({0})', timed.length)),
      timed.length ? h('div', { class: 'cal-agenda' }, timed.map(t => h('div', { class: 'cal-item row' + (now >= t.x ? ' past' : ''), onclick: () => calDetail(t.e.key) },
        h('span', { class: 'mono cal-time' }, hhmm(t.s) + '–' + (t.x >= B && !end.getHours() ? '24:00' : hhmm(t.x))), dotc(t.e),
        h('div', { style: { flex: 1, minWidth: 0 } }, h('div', null, t.name), t.sub ? h('div', { class: 'small muted' }, t.sub,
          t.f === 1 ? ' · ' + T('double rewards') : t.f > 1 ? ' · ' + T('entry until {0}', hhmm(t.f)) : '') : null),
        status(t.s, t.x))))
        : h('p', { class: 'desc' }, T('No timed events or sessions on this day.'))));
}

// ---- monthly: 6-week grid; in a day cell the events open that day (clicking opens the daily view)
function calMonth(rows) {
  const [A] = CAL.coverage, month = new Date(((CAL.coverage[0] + CAL.coverage[1]) / 2) * 1000).getMonth(), today = dayStart(new Date()).getTime();
  const heads = Array.from({ length: 7 }, (_, i) => h('div', { class: 'cal-mhead' }, addDays(new Date(A * 1000), i).toLocaleDateString(LOC(), { weekday: 'short' })));
  const cells = Array.from({ length: 42 }, (_, i) => {
    const d = addDays(new Date(A * 1000), i), s = d.getTime() / 1000, x = addDays(d, 1).getTime() / 1000;
    const items = [];
    for (const e of rows) {
      const iv = e.state === 'on' ? [[s, x]] : e.state === 'off' ? [] : e.ranges.filter(([p, q]) => p < x && q > s);
      if (iv.length) items.push({ e, hour: iv[0][0] > s ? hhmm(iv[0][0]) : null, full: iv.some(([p, q]) => p <= s && q >= x) });
      else if (e.sessions.some(sec => sec.ranges.some(([p, q]) => p < x && q > s))) items.push({ e, hour: null, full: false, session: true });
    }
    items.sort((p, q) => (p.e.type !== 'yearly') - (q.e.type !== 'yearly') || (!p.full) - (!q.full));
    const max = 4;
    return h('div', { class: 'cal-cell' + (d.getMonth() !== month ? ' other' : '') + (d.getTime() === today ? ' today' : ''), onclick: () => calGo('daily', d) },
      h('div', { class: 'cal-dnum' }, d.getDate()),
      items.slice(0, max).map(it => h('div', { class: 'cal-mchip' + (it.e.state === 'on' ? ' forced' : ''), style: { '--c': it.e.color }, title: it.e.name },
        it.hour ? h('span', { class: 'dim' }, it.hour + ' ') : null, it.e.name)),
      items.length > max ? h('div', { class: 'small muted' }, T('+{0} more', items.length - max)) : null);
  });
  return h('div', { class: 'card' }, h('div', { class: 'cal-month' }, heads, cells));
}

// ---- the event's details: description, calendar, intervals in this view, sessions; manual open / closed choice
function calDetail(key) {
  const e = CAL.data.events.find(x => x.key === key); if (!e) return;
  const now = Date.now() / 1000, st = e.state || 'calendar';
  const set = v => act(() => api('/api/events', { changes: { [key]: v } }), T('Updated.')).then(x => { if (x) { m.close(); renderCalendar(); } });
  const iv = e.state === 'on' ? [] : e.ranges;
  const cur = e.next && e.next[0] <= now + 1 ? T('On the calendar now · {0} left', fmtDur(e.next[1] - now))
    : e.next ? T('Next on the calendar: {0} (in {1})', calSpan(e.next[0], e.next[1]), fmtDur(e.next[0] - now)) : T('No upcoming period on the calendar.');
  const m = modal({
    title: e.name, sub: T(KIND_NAME[e.type]) + ' · ' + (e.enabled ? T('active now') : T('inactive now')), wide: true,
    body: h('div', { class: 'stack', style: { gap: '12px' } },
      e.description ? h('div', null, e.description) : null,
      h('div', { class: 'kv one cal-kv' }, [[T('Calendar'), e.time], [T('Status'), cur]].map(([a, b]) => h('div', null, h('span', { class: 'muted' }, a), h('b', null, b)))),
      h('div', null, h('div', { class: 'lbl' }, T('In this view')), iv.length ? h('div', { class: 'chips', style: { marginTop: '6px' } }, iv.slice(0, 24).map(([s, x]) => h('span', { class: 'chip' }, calSpan(s, x))),
        iv.length > 24 ? h('span', { class: 'small muted' }, T('+{0} more', iv.length - 24)) : null)
        : h('div', { class: 'small muted' }, e.state === 'on' ? T('Forced on: always in effect.') : T('Not on the calendar in this view.'))),
      e.sessions.length ? h('div', null, h('div', { class: 'lbl' }, T('Sessions and spawn hours')), h('div', { class: 'stack', style: { gap: '6px', marginTop: '6px' } },
        e.sessions.map(s => h('div', { class: 'small' }, h('b', null, s.name), s.maps.length ? ' · ' + s.maps.join(', ') : '',
          h('div', { class: 'muted' }, s.ranges.length ? [...new Set(s.ranges.map(([a, b]) => hhmm(a) + '–' + hhmm(b)))].slice(0, 12).join(', ') : T('Not in this view')))))) : null,
      h('div', null, h('div', { class: 'lbl' }, T('In game')), h('div', { class: 'seg', style: { marginTop: '6px' } },
        [['calendar', T('By calendar'), 'info'], ['on', T('On'), 'ok'], ['off', T('Off'), 'err']].map(([k, t, c]) =>
          h('button', { class: (st === k ? 'on ' : '') + c, onclick: () => set(k === 'calendar' ? null : k) }, t))))),
    foot: [btn(T('Events page'), () => { m.close(); go('events'); }, 'ghost', 'calendar'), btn(T('Close'), () => m.close(), 'primary')],
  });
}

// ================================================================== CLIENT
const versionText = (c, supported) => !c.version ? T('Unknown version')
  : c.compatible ? T('Version {0} (compatible with the server)', c.version) : T('Version {0} — the server was written for {1}', c.version, supported);
const checkRow = (ok, text, warn) => h('div', { class: ok ? 'ok' : warn ? 'wr' : 'no' }, icon(ok ? 'check' : warn ? 'alert' : 'x'), text);
const WINDOW_MODES = [['windowed', N('Window')], ['borderless', N('Borderless fullscreen')], ['fullscreen', N('Fullscreen')]];
function resolutionList(r) {
  const res = r.resolutions.map(([w, hh]) => `${w}x${hh}`);
  const scr = r.screen ? `${r.screen[0]}x${r.screen[1]}` : null;
  if (scr && !res.includes(scr)) res.push(scr);
  return { res, scr };
}

// ---- downloading the game (client_download.py, /api/istemci/indirme): the wizard's game folder step and the Client page
const DL_ACTIVE = st => st.running || st.partial || ['error', 'stopped', 'finished'].includes(st.state);
const dlPct = st => st.total ? Math.floor(100 * st.claimed / st.total) : 0;
function dlBox(st, refresh, { haveClient = false } = {}) {      // haveClient: there is a valid client, partial files are only deleted
  const pct = dlPct(st), run = st.running;
  const call = (path, msg) => act(() => api(path, {}), msg).then(x => { if (x) refresh(x); });
  const discard = async () => {
    if (await confirmBox(T('Delete the unfinished download?'), T('The downloaded files (istemci_indiriliyor in the project folder) are deleted; the next download starts from the beginning.'), { ok: T('Delete'), danger: true }))
      call('/api/client/download_delete', T('The unfinished download was deleted.'));
  };
  const head = { preparing: T('Preparing the download…'), downloading: T('Downloading the game: {0}%', pct), verifying: T('Checking the files…'),
    finished: T('The game was downloaded and installed.'), error: T('The download stopped.'), stopped: T('Download paused ({0}%).', pct) }[st.state]
    || (st.partial ? T('The previous download was not finished.') : T('Download the game'));
  const info = st.state === 'downloading' ? dlInfo(st)
    : st.state === 'finished' ? st.target
    : st.state === 'error' ? st.error
    : haveClient && st.partial ? T('The selected client is in use; you can delete the unfinished files.')
    : st.state === 'stopped' || st.partial ? T('When you resume, only the missing files are downloaded.')
    : st.state === 'vacant' ? T("The DarkOrbit {0} client is downloaded from the game's official download server and installed into the project folder: about 3.5 GB to download, 4.3 GB on disk. The client files are not modified.", (/(\d+\.\d+\.\d+)\.zip/.exec(st.url || '') || [])[1] || '')
    : '';
  const btns = run ? [btn(T('Stop'), () => call('/api/client/download_stop', T('Stopping the download…')), 'ghost sm', 'stop')]
    : st.state === 'finished' ? []
    : [haveClient ? null : btn(st.state === 'error' ? T('Try again') : st.state === 'stopped' || st.partial ? T('Resume') : T('Download and install'), () => call('/api/client/download'), 'primary sm', 'download'),
      st.partial ? btn(T('Delete unfinished download'), discard, 'ghost sm', 'trash') : null];
  return h('div', { class: 'dl-box ' + (st.state === 'error' ? 'err' : st.state === 'finished' ? 'ok' : '') },
    h('b', null, head),
    run || st.state === 'stopped' ? h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } }))) : null,
    info ? h('div', { class: 'small muted dl-info', title: st.file || '' }, info) : null,
    btns.some(Boolean) ? h('div', { class: 'row wrap' }, btns) : null);
}
// the download's row: downloaded / total, speed, time left, file
function dlInfo(st) {
  return [`${fmtBytes(st.claimed)} / ${fmtBytes(st.total)}`, st.speed ? `${fmtBytes(st.speed)}/${T('s')}` : null,
    st.time_left_sec != null && st.speed ? T('{0} remaining', fmtDur(st.time_left_sec)) : null, T('file {0}/{1}', st.done_files, st.file_count)].filter(Boolean).join(' · ');
}
// refreshes the box every second; when the job finishes (finished) onDone. -> setInterval id
function dlWatch(wrap, st, onDone, opts) {
  let sig = JSON.stringify(st);
  const draw = s => wrap.replaceChildren(dlBox(s, x => { draw(x); sig = JSON.stringify(x); }, opts));
  draw(st);
  const id = setInterval(async () => {
    if (!wrap.isConnected) { clearInterval(id); return; }
    let s; try { s = await api('/api/client/download_status'); } catch (e) { return; }
    const was = JSON.parse(sig);
    const n = JSON.stringify(s);
    if (n === sig) return;
    sig = n; draw(s);
    if (s.state === 'finished' && was.state !== 'finished' && onDone) onDone(s);
  }, 1000);
  return id;
}

// ---- macOS: the Wine + DXMT and Rosetta 2 the panel installs (wine_engine.py, /api/motor): the Wine / Proton card and the wizard's game folder step
function engineBox(m, refresh, { engine = true } = {}) {
  const call = (path, msg) => act(() => api(path, {}), msg).then(x => { if (x) refresh(x); });
  const pct = m.total ? Math.floor(100 * m.claimed / m.total) : 0, run = m.running, ros = m.rosetta;
  const rosetta = !ros.required ? null : ros.exists ? h('div', { class: 'check-list', style: { margin: 0 } }, checkRow(true, T('Rosetta 2 is installed')))
    : h('div', { class: 'alert error' }, icon('alert'), h('div', null, T("Rosetta 2 is not installed: on Apple Silicon the Wine that opens the game runs with it. Installing it asks for your macOS administrator password."),
      ros.error ? h('div', { class: 'small' }, ros.error) : null),
      btn(ros.state === 'installing' ? T('Installing…') : T("Install Rosetta"), () => call('/api/rosetta/install'), 'primary sm', 'download', { disabled: ros.state === 'installing' }));
  const old = m.macos_old ? h('div', { class: 'alert warning' }, icon('alert'), h('div', null, T('DXMT needs macOS 14 Sonoma or newer (this Mac: {0}); the game may not open.', m.macos))) : null;
  if (!engine) return h('div', { class: 'stack', style: { gap: '10px' } }, rosetta, old);
  const head = run ? (m.state === 'installing' ? T('Installing Wine…') : T('Downloading Wine and DXMT: {0}%', pct))
    : m.state === 'built' ? T('The Wine that opens the game is ready: {0}', m.name) : m.state === 'error' ? T('Wine could not be installed.')
    : m.state === 'stopped' ? T('The Wine download was stopped.') : T("The Wine that opens the game isn't installed yet.");
  const info = run ? [`${fmtBytes(m.claimed)} / ${fmtBytes(m.total)}`, m.speed ? `${fmtBytes(m.speed)}/${T('s')}` : null,
      m.time_left_sec != null && m.speed ? T('{0} remaining', fmtDur(m.time_left_sec)) : null].filter(Boolean).join(' · ')
    : m.state === 'error' ? m.error : m.state === 'built' ? m.folder
    : T("{0} is downloaded and installed (about {1}); it is also downloaded by itself on the first PLAY.", m.name, fmtBytes(m.size));
  const btns = run ? [btn(T('Stop'), () => call('/api/engine/stop', T('Stopping the download…')), 'ghost sm', 'stop')]
    : m.state === 'built' ? [] : [btn(m.state === 'error' || m.state === 'stopped' ? T('Try again') : T('Download and install'), () => call('/api/engine/install'), 'primary sm', 'download')];
  return h('div', { class: 'stack', style: { gap: '10px' } },
    h('div', { class: 'dl-box ' + (m.state === 'error' ? 'err' : m.state === 'built' ? 'ok' : '') }, h('b', null, head),
      run ? h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } }))) : null,
      info ? h('div', { class: 'small muted dl-info' }, info) : null,
      btns.length ? h('div', { class: 'row wrap' }, btns) : null),
    rosetta, old);
}
// refreshes the box every second (stops by itself when leaving the page) -> setInterval id
function engineWatch(wrap, m, opts) {
  let sig = JSON.stringify(m);
  const draw = x => { sig = JSON.stringify(x); wrap.replaceChildren(engineBox(x, draw, opts)); };
  draw(m);
  const id = setInterval(async () => {
    if (!wrap.isConnected) { clearInterval(id); return; }
    let x; try { x = await api('/api/engine'); } catch (e) { return; }
    if (JSON.stringify(x) !== sig) draw(x);
  }, 1000);
  return id;
}

// ---- BepInEx, which loads the client's fixes (client_patch.py, /api/yama): the Client page and the wizard's game folder step
function patchBox(y, refresh) {
  const call = path => act(() => api(path, {})).then(x => { if (x) refresh(x); });
  const pct = y.total ? Math.floor(100 * y.claimed / y.total) : 0, run = y.running;
  const head = run ? (y.state === 'installing' ? T('Installing BepInEx…') : T('Downloading BepInEx: {0}%', pct))
    : y.state === 'built' ? T('Client fixes ready: {0}', y.name) : y.state === 'error' ? T('BepInEx could not be installed.')
    : y.state === 'stopped' ? T('The BepInEx download was stopped.') : T("BepInEx isn't installed yet.");
  const info = run ? `${fmtBytes(y.claimed)} / ${fmtBytes(y.total)}` : y.state === 'error' ? y.error
    : y.state === 'built' ? T("Fixes the auction countdown, the rank window and shop totals. On the game's first start BepInEx takes about half a minute to get ready.")
    : T("The plugin that fixes small client bugs is loaded with BepInEx: {0} is installed into the game folder (about {1}); it is also installed by itself on the first PLAY.", y.name, fmtBytes(y.total));
  const btns = run ? [btn(T('Stop'), () => call('/api/patch/stop'), 'ghost sm', 'stop')]
    : y.state === 'built' ? [] : [btn(y.state === 'error' || y.state === 'stopped' ? T('Try again') : T('Download and install'), () => call('/api/patch/install'), 'primary sm', 'download')];
  return h('div', { class: 'dl-box ' + (y.state === 'error' ? 'err' : y.state === 'built' ? 'ok' : '') }, h('b', null, head),
    run ? h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } }))) : null,
    info ? h('div', { class: 'small muted dl-info' }, info) : null,
    btns.length ? h('div', { class: 'row wrap' }, btns) : null);
}
// refreshes the box every second (stops by itself when leaving the page) -> setInterval id
function patchWatch(wrap, y) {
  let sig = JSON.stringify(y);
  const draw = x => { sig = JSON.stringify(x); wrap.replaceChildren(patchBox(x, draw)); };
  draw(y);
  const id = setInterval(async () => {
    if (!wrap.isConnected) { clearInterval(id); return; }
    let x; try { x = await api('/api/patch'); } catch (e) { return; }
    if (JSON.stringify(x) !== sig) draw(x);
  }, 1000);
  return id;
}

// ---- Linux and macOS: the Wine or Proton that starts the client (client_runner.py; /api/istemci 'runner', null on Windows)
function runnerCard(c, cfg, saveCfg) {
  const mac = c.platform === 'darwin';
  const kinds = [['auto', T('Automatic')], ['engine', T("Panel's Wine")], ['wine', 'Wine'], ['proton', 'Proton'], ['special', T('Custom command')]]
    .filter(([k]) => mac ? k !== 'proton' : k !== 'engine');
  const seg = h('div', { class: 'seg' }, kinds.map(([k, t]) =>
    h('button', { class: cfg.runner === k ? 'on info' : '', onclick: () => saveCfg({ runner: k, runner_path: '' }) }, t)));
  const used = c.type === 'proton' ? `${c.name}${c.umu ? ' (umu-run)' : ''}` : c.type === 'special' ? c.route : c.name;
  const mWrap = mac ? h('div', { class: 'dl-wrap' }) : null;
  if (mWrap && c.engine) S.timers.push(engineWatch(mWrap, c.engine, { engine: c.type === 'engine' }));
  const pathIn = h('input', { class: 'input mono', value: cfg.runner_path, placeholder: cfg.runner === 'special' ? T('e.g. umu-run') : T('Empty: found automatically'),
    onchange: e => saveCfg({ runner_path: e.target.value.trim() }) });
  const prefixIn = h('input', { class: 'input mono', value: cfg.wine_prefix, placeholder: c.default_prefix[c.type] || T("Empty: Wine's default"),
    onchange: e => saveCfg({ wine_prefix: e.target.value.trim() }) });
  const found = [...c.protons.map(p => ['proton', p.route, p.name]), ...c.wines.map(w => ['wine', w, 'Wine'])];
  return h('div', { class: 'card' }, h('h2', null, icon('zap'), 'Wine / Proton'),
    h('p', { class: 'desc' }, T("The game is a Windows program; on Linux and macOS it opens with Wine or Proton. Automatic: Steam's Proton on Linux (through umu-run if it is installed), otherwise Wine; on macOS the Wine and DXMT that the panel installs itself (plain Wine can't draw the game's Direct3D 11 graphics on macOS). The client runs in its own prefix, which is set up the first time it opens (this can take about half a minute).")),
    c.error && !(mac && c.engine && !c.engine.rosetta.exists) ? h('div', { class: 'alert error' }, icon('alert'), h('div', null, c.error))
      : h('div', { class: 'alert info' }, icon('info'), h('div', null, T('In use: {0}', used))),
    mWrap ? h('div', { style: { marginTop: '12px' } }, mWrap) : null,
    h('div', { class: 'stack', style: { gap: '14px', marginTop: '12px' } },
      field(T('Runner'), seg),
      c.type === 'engine' ? null : field(cfg.runner === 'special' ? T('Command (put in front of the client)') : T('Path (wine program or Proton folder)'), pathIn),
      field(T('Prefix folder (WINEPREFIX)'), prefixIn)),
    found.length ? [h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('Found')),
      h('div', { class: 'stack', style: { gap: '8px', marginTop: '8px' } }, found.map(([k, route, name]) => h('div', { class: 'row' },
        badge(name, 'info'), h('span', { class: 'mono', style: { flex: 1, minWidth: 0, wordBreak: 'break-all' } }, route),
        c.type === k && c.route === route ? badge(T('in use'), 'ok') : btn(T('Use'), () => saveCfg({ runner: k, runner_path: route }), 'sm'))))] : null,
    h('div', { class: 'small muted', style: { marginTop: '12px' } }, T("If the game doesn't open, look at the wine.log log on the Server page.")));
}

async function renderClient(data) {
  const r = data || await act(() => api('/api/client')); if (!r || S.page !== 'client') return;
  const c = r.control, cfg = r.settings;
  const dlWrap = !c.valid || DL_ACTIVE(r.download) ? h('div', { class: 'dl-wrap' }) : null;
  const yWrap = c.valid && r.patch.required ? h('div', { class: 'dl-wrap' }) : null;
  const saveCfg = (vals, msg = T('Saved.')) => act(() => api('/api/panel_settings', { values: vals }), msg).then(x => x && renderClient(x));
  const folderCard = h('div', { class: 'card' }, h('h2', null, icon('folder'), T('Client folder')),
    h('p', { class: 'desc' }, T('Folder of the original DarkOrbit Unity client (the one with DarkOrbit.exe and DarkOrbit_Data). Choose it here after an update or if you move the folder.')),
    h('div', { class: 'path' }, c.route || T('Not selected')),
    h('div', { class: 'small muted', style: { marginTop: '6px' } }, r.selected ? T('Chosen manually.') : T('Found automatically (the best version in the usual folders).')),
    h('div', { class: 'check-list' },
      checkRow(c.exe, 'DarkOrbit.exe'), checkRow(c.data, T('DarkOrbit_Data folder')),
      c.valid ? checkRow(c.compatible, versionText(c, r.supported), !c.compatible) : null),
    c.issues.length && !c.valid && !r.download.running ? h('div', { class: 'alert error' }, icon('alert'), h('div', null, c.issues.join(' '))) : null,
    h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('Download the game')),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Fast download')),
      h('div', { class: 'help' }, T('When on, the game downloads over 3 connections at once; when off, over a single connection (slower). Applies to the next download.'))),
      h('div', { class: 'ctl' }, h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: cfg.fast_download, onchange: e => saveCfg({ fast_download: e.target.checked }) }), h('span')))),
    dlWrap,
    yWrap ? [h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('Client fixes (BepInEx)')), yWrap] : null,
    h('div', { id: 'proto-box' }),
    h('div', { class: 'row wrap', style: { marginTop: '12px' } },
      btn(T('Choose folder…'), () => act(() => api('/api/client/select', {}), x => x.cancelled ? T('Cancelled.') : T('Client folder saved.')).then(x => x && renderClient(x)), 'primary', 'folder'),
      btn(T('Find automatically'), () => act(() => api('/api/client/auto', {}), T('Automatic search is on.')).then(x => x && renderClient(x)), '', 'search'),
      btn(T('Open folder'), () => act(() => api('/api/open_folder', { what: 'client' })), 'ghost', 'folder')),
    r.candidates.length > 1 || (r.candidates.length === 1 && r.candidates[0].route !== c.route) ? [h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('Clients found')),
      h('div', { class: 'stack', style: { gap: '8px', marginTop: '8px' } }, r.candidates.map(a => h('div', { class: 'row' },
        badge(a.version || '?', a.compatible ? 'ok' : 'warn'), h('span', { class: 'mono', style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, title: a.route }, a.route),
        a.route === c.route ? badge(T('in use'), 'info') : btn(T('Use'), () => act(() => api('/api/client/use', { route: a.route }), T('Saved.')).then(x => x && renderClient(x)), 'sm'))))] : null);

  const { res, scr } = resolutionList(r);
  const cur = `${cfg.width}x${cfg.height}`;
  const custom = !res.includes(cur);
  const sel = h('select', { class: 'input', style: { width: '220px' }, onchange: e => {
    if (e.target.value === 'special') { cw.style.display = ''; return; }
    const [w, hh] = e.target.value.split('x').map(Number); saveCfg({ width: w, height: hh });
  } }, res.map(x => h('option', { value: x, selected: x === cur }, x + (x === scr ? '  (' + T('screen') + ')' : ''))), h('option', { value: 'special', selected: custom }, T('Custom…')));
  const wIn = h('input', { class: 'input num', type: 'number', value: cfg.width }), hIn = h('input', { class: 'input num', type: 'number', value: cfg.height });
  const cw = h('div', { class: 'row', style: { display: custom ? '' : 'none' } }, wIn, '×', hIn, btn(T('Apply'), () => saveCfg({ width: +wIn.value, height: +hIn.value }), 'sm'));
  const mode = h('div', { class: 'seg' }, WINDOW_MODES.map(([k, t]) =>
    h('button', { class: cfg.window_mode === k ? 'on info' : '', onclick: () => saveCfg({ window_mode: k }) }, T(t))));
  const mon = h('select', { class: 'input', style: { width: '220px' }, onchange: e => saveCfg({ monitor: +e.target.value }) },
    [0, 1, 2, 3, 4].map(i => h('option', { value: i, selected: cfg.monitor === i }, i ? T('Display {0}', i) : T('Default'))));
  const extra = h('input', { class: 'input mono', value: cfg.extra_args, placeholder: T('e.g. -force-d3d11'), onchange: e => saveCfg({ extra_args: e.target.value }) });
  const dispCard = h('div', { class: 'card' }, h('h2', null, icon('monitor'), T('Display')),
    h('p', { class: 'desc' }, T("Passed to the client as launch arguments; the game's own graphics settings (2D/3D, quality) are in the game.")),
    h('div', { class: 'stack', style: { gap: '14px' } },
      field(T('Window mode'), mode),
      field(T('Resolution'), h('div', { class: 'row wrap' }, sel, cw)),
      field(T('Monitor'), mon),
      field(T('Extra Unity arguments (advanced)'), extra),
      field(T('Launch command'), h('div', { class: 'cmd' }, r.command.join(' ')))));
  const warn = h('div', { class: 'alert warning' }, icon('alert'), h('div', null,
    T("Don't run DarkorbitLauncher.exe from that folder: it may update the client from the official server and break compatibility with the local server. The panel never changes the client's own files; it starts it with the local login address and loads small fixes with the BepInEx it installs next to it.")));
  const multiCfg = h('div', { class: 'card compact' }, h('h2', null, icon('users'), T('Multi-client')),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Extra clients with your other saves')),
      h('div', { class: 'help' }, T("When on and you have at least two saves, PLAY starts the server in multi-session mode; from the Play page you open extra clients with your other saves on the same server. Extra clients open windowed and share the display settings."))),
      h('div', { class: 'ctl' }, h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: cfg.multi_client, onchange: e => saveCfg({ multi_client: e.target.checked }) }), h('span')))),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Most extra clients')),
      h('div', { class: 'help' }, T('Each client uses about 600 MB of memory and some graphics card.'))),
      h('div', { class: 'ctl' }, h('select', { class: 'input', style: { width: '90px' }, onchange: e => saveCfg({ multi_client_max: +e.target.value }) },
        [1, 2, 3, 4, 5, 6, 7, 8].map(n => h('option', { value: n, selected: cfg.multi_client_max === n }, String(n)))))));
  $('#content').replaceChildren(h('div', { class: 'stack' }, h('div', { class: 'grid g2' }, folderCard, dispCard),
    r.runner ? runnerCard(r.runner, cfg, saveCfg) : null, multiCfg, warn));
  S.sig = S.sig || {}; S.proto = null; S.protoClient = c;
  if (dlWrap) S.timers.push(dlWatch(dlWrap, r.download, () => { toast(T('The game was downloaded and installed.'), 'ok'); renderClient(); }, { haveClient: c.valid }));
  if (yWrap) S.timers.push(patchWatch(yWrap, r.patch));
  protoTick(true);
  S.timers.push(setInterval(() => protoTick(), 1000));
}

// ---- protocol adaptation to a new client (tools/il2cpp/protocol_update.py; protocol_builds.py, /api/protokol)
async function protoTick(force) {
  const box = $('#proto-box'); if (!box) return;
  if (!force && !(S.proto && S.proto.running)) return;
  let r; try { r = await api('/api/protocol'); } catch (e) { return; }
  const sig = JSON.stringify(r);
  if (!force && S.sig.proto === sig) return;
  S.sig.proto = sig; S.proto = r;
  const c = S.protoClient || {}, o = r.summary || {}, run = r.running;
  const need = c.valid && !c.compatible;
  if (!need && !run && !r.summary && !r.error) { box.replaceChildren(); return; }
  const kv = [[N('Added'), o.added], [N('Removed'), o.deleted], [N('IDs changed'), o.uid], [N('Fields changed'), o.fields],
    [N('Encoding changed'), o.write], [N('Decoding changed'), o.read_at], [N('Unclear fields'), o.ambiguous]].filter(([, v]) => v != null);
  const width = () => act(() => api('/api/protocol/generate', {}), T('Protocol tool started.')).then(() => protoTick(true));
  const use = () => act(() => api('/api/protocol/apply', { version: o.version }), T('Applying…')).then(() => protoTick(true));
  box.replaceChildren(h('div', { class: 'alert ' + (r.error ? 'error' : need ? 'warning' : 'info'), style: { marginTop: '12px' } }, icon(r.error ? 'alert' : 'info'),
    h('div', { class: 'stack', style: { gap: '6px', flex: 1, minWidth: 0 } },
      h('div', null, need ? T("The server's active protocol is for {0}. Adapt the new client: it builds the protocol from this client's code and reports the differences (the active files are left alone).", r.enabled)
        : T('Active protocol: {0}.', r.enabled)),
      run ? h('div', { class: 'row' }, h('span', { class: 'spin' }), h('span', { class: 'small' }, (r.lines || []).slice(-1)[0] || T('Running…'))) : null,
      r.error ? h('div', { class: 'small' }, r.error) : null,
      kv.length ? h('div', { class: 'small' }, `${o.version || ''}: ` + kv.map(([k, v]) => `${T(k)} ${v}`).join(' · ')) : null,
      o.report ? h('div', { class: 'small mono', style: { overflow: 'hidden', textOverflow: 'ellipsis' } }, o.report) : null,
      h('div', { class: 'row wrap' },
        need && !run ? btn(T('Adapt the new client'), width, 'primary sm', 'refresh') : null,
        !run && r.is === 'produce' && !r.error && o.version && o.version !== r.enabled ? btn(T('Apply the {0} protocol', o.version), use, 'sm', 'check') : null,
        !run && r.is === 'apply' && !r.error ? h('span', { class: 'small' }, T('Applied; the game server uses the new protocol after a restart.')) : null))));
}

// ================================================================== SERVER
let logState = { name: 'gs.log', row: 400, filter_by: '', auto: true };
async function renderServer() {
  const cfg = await act(() => api('/api/panel_settings')); if (!cfg || S.page !== 'server') return;
  S.panelCfg = cfg;
  const saveCfg = vals => act(() => api('/api/panel_settings', { values: vals }), T('Saved.')).then(() => renderServer());
  const seg = (key, opts) => h('div', { class: 'seg' }, opts.map(([k, t]) => h('button', { class: cfg[key] === k ? 'on info' : '', onclick: () => saveCfg({ [key]: k }) }, t)));
  const behav = h('div', { class: 'card compact' }, h('h2', null, icon('sliders'), T('Behavior')),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('When the client closes')), h('div', { class: 'help' }, T('What should happen to the servers the panel started when you quit the game?'))),
      h('div', { class: 'ctl' }, seg('when_client_closes', [['close', T('Stop the servers')], ['on', T('Keep running')]]))),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('When the panel window closes')), h('div', { class: 'help' }, T('If a game is running it waits, then the panel and servers close; or everything closes right away.'))),
      h('div', { class: 'ctl' }, seg('when_window_closes', [['wait', T('Close when the game ends')], ['close', T('Close right away')]]))),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Rotate logs')), h('div', { class: 'help' }, T("Logs over 5 MB are kept as .1, .2, .3 at startup."))),
      h('div', { class: 'ctl' }, h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: cfg.rotate_logs, onchange: e => saveCfg({ rotate_logs: e.target.checked }) }), h('span')))));
  const ports = h('div', { class: 'card' }, h('h2', null, icon('link'), T('Ports')),
    h('p', { class: 'desc' }, T("If the server won't start, another process (a server left over from a previous session or another program) may be holding the ports.")),
    h('div', { id: 'port-list' }), h('div', { class: 'row' }, btn(T('Check ports'), () => checkPorts(), 'sm', 'search')));
  const logs = h('div', { class: 'card' },
    h('div', { class: 'row between wrap' }, h('h2', null, icon('note'), T('Logs')),
      h('div', { class: 'row wrap' },
        h('input', { class: 'input', style: { width: '180px' }, placeholder: T('Filter…'), value: logState.filter_by, oninput: e => { logState.filter_by = e.target.value; loadLog(); } }),
        h('select', { class: 'input', style: { width: '110px' }, onchange: e => { logState.row = +e.target.value; loadLog(); } },
          [200, 400, 1000, 3000].map(n => h('option', { value: n, selected: logState.row === n }, T('{0} lines', n)))),
        h('label', { class: 'row small muted' }, h('span', { class: 'switch' }, h('input', { type: 'checkbox', checked: logState.auto, onchange: e => { logState.auto = e.target.checked; } }), h('span')), T('Live')),
        btn('', () => loadLog(), 'ghost sm icon', 'refresh', { title: T('Refresh') }),
        btn(T('Folder'), () => act(() => api('/api/open_folder', { what: 'logs' })), 'ghost sm', 'folder'),
        btn(T('Clear'), async () => { if (await confirmBox(T('Clear the log?'), T('{0} will be emptied.', logState.name), { ok: T('Clear'), danger: true })) act(() => api('/api/log/clear', { name: logState.name }), T('Cleared.')).then(loadLog); }, 'ghost sm', 'trash'))),
    h('div', { class: 'log-tabs', id: 'log-tabs', style: { margin: '10px 0' } }), h('div', { class: 'log-view', id: 'log-view' }));
  $('#content').replaceChildren(h('div', { class: 'stack' }, h('div', { class: 'grid g3', id: 'srv-cards' }), h('div', { class: 'grid g2' }, behav, ports), logs));
  S.sig = {};
  renderServerCards();
  loadLog();
  S.timers.push(setInterval(() => { if (logState.auto && document.visibilityState === 'visible') loadLog(true); }, 2000));
}

function renderServerCards() {
  const box = $('#srv-cards'), d = S.state; if (!box || !d) return;
  // the signature uses the time text shown on screen (fmtDur): the per-second sure_sn rebuilt the cards on every poll and swallowed the click on the button under the mouse
  const s = d.processes, duration = x => x && Object.assign({}, x, { duration_sec: x.duration_sec == null ? null : fmtDur(x.duration_sec) });
  const sig = JSON.stringify([Object.assign({}, s, { servers: { web: duration(s.servers.web), game: duration(s.servers.game) }, client: duration(s.client) }), d.play.running]);
  if (S.sig.srv === sig) return; S.sig.srv = sig;
  const busy = d.play.running, cl = s.client.state === 'on';
  const card = (title, iconEl, st, ports, extra, actions) => h('div', { class: 'card status-card' },
    h('div', { class: 'big' }, icon(iconEl), title), h('div', { class: 'row', style: { marginTop: '8px' } }, dot(stCls(st.state)), h('b', null, stText(st.state)),
      st.pid ? h('span', { class: 'muted small' }, `PID ${st.pid} · ${fmtDur(st.duration_sec)}`) : null, st.exit_code != null && st.state === 'crashed' ? badge(T('exit {0}', st.exit_code), 'err') : null),
    ports ? h('div', { class: 'ports' }, Object.entries(ports).map(([p, on]) => badge(on ? T('{0} listening', p) : T('{0} closed', p), on ? 'ok' : ''))) : h('div', { style: { height: '12px' } }),
    extra, h('div', { class: 'actions' }, actions));
  const w = s.servers.web, o = s.servers.game, srvOn = w.state === 'on' || o.state === 'on';
  box.replaceChildren(
    card(T('Web server'), 'link', w, w.ports, h('div', { class: 'small muted' }, T("The client's web login, map list and language selection.")), [btn(T('Log'), () => showLog('http.log'), 'sm'), btn(T('Console'), () => showLog('web_console.log'), 'ghost sm')]),
    card(T('Game server'), 'server', o, o.ports, h('div', { class: 'small muted' }, s.record ? T('Save: {0}', s.record) + (s.control_channel ? ' · ' + T('control channel open (8099)') : '') : T('Game world, saving, chat (7771).')),
      [srvOn ? btn(T('Stop'), () => act(() => api('/api/server/stop', {}), T('Stopped.')), 'danger sm', 'stop', { disabled: cl || busy, title: cl ? T('Close the game first') : '' })
        : btn(T('Start'), () => act(() => api('/api/play', { server_only: true })), 'primary sm', 'play', { disabled: busy }),
      // icon only: so the four buttons fit the card width and "Console" does not drop to the bottom on its own
      btn(null, () => act(() => api('/api/server/restart', {}), T('Restarted.')), 'sm icon', 'refresh', { disabled: busy || !srvOn, title: T('Restart') + ' — ' + T('If the game is running, the client must reconnect') }),
      btn(T('Log'), () => showLog('gs.log'), 'ghost sm'), btn(T('Console'), () => showLog('game_console.log'), 'ghost sm')]),
    card(T('Client'), 'monitor', s.client, null, h('div', { class: 'small muted' }, s.client.last ? T('Last closed {0} · ran for {1}', s.client.last.time, fmtDur(s.client.last.duration_sec)) : T('The original Unity client.')),
      [cl ? btn(T('Close'), async () => { if (await confirmBox(T('Close the client?'), T('The game window will be closed.'), { ok: T('Close'), danger: true })) act(() => api('/api/client/close', {})); }, 'danger sm', 'power')
        : btn(T('Play'), () => { go('play'); act(() => api('/api/play', {})); }, 'orange sm', 'play', { disabled: busy }),
      btn(T('Log'), () => showLog('client.log'), 'ghost sm')]));
}

async function checkPorts() {
  const box = $('#port-list'); if (!box) return;
  box.replaceChildren(h('div', { class: 'row muted small' }, h('span', { class: 'spin' }), T('Checking…')));
  const r = await act(() => api('/api/ports')); if (!r) { box.replaceChildren(); return; }
  box.replaceChildren(r.length ? h('div', { class: 'stack', style: { gap: '8px', marginBottom: '12px' } }, r.map(p => h('div', { class: 'alert ' + (p.ours ? 'warning' : 'error') }, icon('alert'),
    h('div', null, h('b', null, `${p.port} (${p.name})`), ` — ${p.process} (PID ${p.pid ?? '?'})`, h('div', { class: 'mono dim', style: { marginTop: '3px' } }, p.command || ''),
      p.ours ? h('div', { class: 'small' }, T('A server of this project left over from a previous session.')) : h('div', { class: 'small' }, T("Another program: the panel won't close it; close it yourself."))),
    p.ours ? btn(T('Close'), () => act(() => api('/api/ports/close', { pid: p.pid }), T('Process closed.')).then(() => checkPorts()), 'sm', 'x') : null)))
    : h('div', { class: 'row small', style: { marginBottom: '12px', color: 'var(--ok)' } }, icon('check'), T('No process outside the panel is holding the ports.')));
}

function showLog(name) { logState.name = name; loadLog(); const v = $('#log-view'); if (v) v.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
async function loadLog(quiet) {
  const view = $('#log-view'); if (!view) return;
  let r;
  try { r = await api('/api/log?name=' + encodeURIComponent(logState.name) + '&satir=' + logState.row); } catch (e) { if (!quiet) toast(e.message, 'err'); return; }
  const tabs = $('#log-tabs');
  if (tabs) tabs.replaceChildren(...r.entries.map(g => h('button', { class: 'btn sm ' + (g.name === logState.name ? 'primary' : 'ghost'), onclick: () => { logState.name = g.name; loadLog(); } },
    g.name, g.size != null ? h('span', { class: 'dim', style: { fontWeight: 400 } }, fmtBytes(g.size)) : null)));
  const atBottom = view.scrollHeight - view.scrollTop - view.clientHeight < 40;
  const f = logState.filter_by.toLowerCase();
  const lines = r.lines.filter(l => !f || l.toLowerCase().includes(f));
  const sig = logState.name + '|' + f + '|' + lines.length + '|' + (lines[lines.length - 1] || '');
  if (quiet && view.dataset.sig === sig) return;
  view.dataset.sig = sig;
  view.replaceChildren(...(r.exists ? lines.map(l => {
    const low = l.toLowerCase();
    const cls = /error|hata|traceback|exception|çöktü|failed/.test(low) ? 'e' : /uyar|warn|yanıtsız|unanswered/.test(low) ? 'w' : /^\d\d:\d\d:\d\d -> /.test(l) ? 'i' : '';
    return h('div', { class: cls }, l);
  }) : [h('div', { class: 't' }, T("This log doesn't exist yet."))]));
  if (atBottom || !quiet) view.scrollTop = view.scrollHeight;
}

// ================================================================== PANEL
// ---- updates (updater.py, /api/guncelleme): the latest version on GitHub, automatic installation
const UPD_TEXT = { up_to_date: N('The panel is up to date.'), var: N('A new version is available.'), downloading: N('Downloading the new version…'), installing: N('Installing the new version…'),
  installed: N('New version installed: if the game and servers are closed, the panel restarts now.'), unknown: N('Not checked yet.'),
  local_changes: N("There is a new version on GitHub, but this copy has local changes: get the update with git."),
  local_ahead: N("This copy has commits that are not on GitHub yet: nothing to install.") };
const fmtVersion = v => v && v.version ? v.version.slice(0, 7) + (v.date ? ' · ' + new Date(v.date).toLocaleString(LOC(), { dateStyle: 'medium', timeStyle: 'short' }) : '') : T('unknown');
function updCard() {
  const card = h('div', { class: 'card' }, h('h2', null, icon('refresh'), T('Updates')),
    h('p', { class: 'desc' }, T("The panel checks the latest version on GitHub and installs it if it is newer. Your saves, settings and game client are not changed; the old versions of changed files are backed up.")),
    h('div', { class: 'upd-body' }));
  let sig = '';
  const draw = r => {
    const s = JSON.stringify(r); if (s === sig) return; sig = s;
    const body = card.querySelector('.upd-body'); if (!body) return;
    const run = r.running || ['downloading', 'installing'].includes(r.state);
    const cls = r.state === 'error' ? 'error' : ['exists', 'installed', 'local_changes'].includes(r.state) ? 'warning' : 'info';
    const text = r.state === 'error' ? r.error : r.running && r.state !== 'downloading' && r.state !== 'installing' ? T('Checking…') : T(UPD_TEXT[r.state] || r.state);
    const pct = r.total ? Math.floor(100 * r.claimed / r.total) : null;
    const save = k => act(() => api('/api/panel_settings', { values: { update: k } }), T('Saved.')).then(x => x && load());
    const toggle = on => {                               // when off, a new version is only announced (notify)
      save(on ? 'auto' : 'notify');
      if (!on) { const m = modal({ title: T('Automatic updates turned off'), body: T('Updates can come out very often during the day; checking frequently is recommended.'),
        foot: [btn(T('OK'), () => m.close(), 'primary')] }); }
    };
    body.replaceChildren(h('div', null,                  // h() skips empty values (replaceChildren turns null into text)
      h('div', { class: 'kv', style: { maxWidth: '620px' } },
        h('div', null, T('Installed version'), h('b', null, fmtVersion(r.built))),
        h('div', null, 'GitHub', h('b', null, r.last ? fmtVersion(r.last) : '—')),
        h('div', null, T('Installation type'), h('b', null, r.built.style === 'git' ? T('Git clone (fast-forwarded with git)') : T('Downloaded ZIP'))),
        h('div', null, T('Last check'), h('b', null, r.last_check ? fmtWhen(new Date(r.last_check * 1000).toISOString()) : '—'))),
      r.last && r.last.message && r.state === 'exists' ? h('div', { class: 'small muted', style: { marginTop: '6px' } }, T('Latest change: {0}', r.last.message)) : null,
      h('div', { class: 'alert ' + cls, style: { marginTop: '12px' } }, icon(cls === 'info' ? 'info' : 'alert'),
        h('div', null, text, r.state === 'downloading' ? ' ' + (pct != null ? pct + '% · ' : '') + fmtBytes(r.claimed) : '',
          r.state === 'exists' && !r.idle ? h('div', { class: 'small' }, T('The game, the servers or another task is running: it can be installed once they are closed.')) : null)),
      r.state === 'downloading' && pct != null ? h('div', { class: 'meter', style: { marginTop: '8px' } }, h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } }))) : null,
      h('div', { class: 'stack', style: { gap: '12px', marginTop: '14px' } },
        h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Automatic updates')),
          h('div', { class: 'help' }, T('When on, a new version installs by itself once the game and servers are closed; when off, you are only notified.'))),
          h('div', { class: 'ctl' }, h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: r.setting === 'auto', onchange: e => toggle(e.target.checked) }), h('span')))),
        h('div', { class: 'row wrap' },
          btn(T('Check now'), () => act(() => api('/api/update/check', {})).then(x => x && draw(x)), '', 'refresh', { disabled: run }),
          r.state === 'exists' ? btn(T('Install update'), () => act(() => api('/api/update/install', {})).then(x => x && draw(x)), 'primary', 'download', { disabled: !r.idle }) : null,
          h('span', { class: 'small muted mono' }, r.storage)))));
  };
  const load = () => api('/api/update').then(draw).catch(() => {});
  load();
  S.timers.push(setInterval(() => { if (card.isConnected) load(); }, 2000));
  return card;
}

// ---- Discord Rich Presence (discord_rp.py, /api/discord_rp): the game's live state on the Discord profile; the player chooses what is shown
const RP_FIELDS = [['rp_pilot', N('Pilot name'), N('Your in-game name (off by default).')], ['rp_clan', N('Clan tag'), N('Shown before your name as [TAG].')],
  ['rp_ship', N('Ship'), N('Name of the active ship.')], ['rp_level', N('Level'), N("The pilot's level.")],
  ['rp_map', N('Map'), N('Map name and the region image.')], ['rp_state', N('What you are doing'), N('Combat target, gate wave, safe zone.')],
  ['rp_company', N('Company'), N('Company emblem (small image).')], ['rp_duration', N('Session time'), N('Time since you entered the game.')],
  ['rp_group', N('Group'), N('Play with Friends: number of players on your server.')], ['rp_buttons', N('Buttons'), N("Discord server and GitHub links (visible to others).")],
  ['rp_in_panel', N('While the game is closed'), N('Shows "In the panel" while only the panel is open.')]];
const RP_STATUS = { connected: [N("Connected to Discord"), 'ok'], discord_not_running: [N('Discord is not running'), 'warn'], error: [N('Error'), 'err'], off: [N('Off'), ''] };
function rpCard() {
  const head = h('span', { class: 'rp-status' });
  const body = h('div', { class: 'rp-body' });
  const card = h('div', { class: 'card' }, h('h2', null, icon('users'), 'Discord Rich Presence', head),
    h('p', { class: 'desc' }, T('Your Discord profile shows that you are playing OpenOrbit and what you are doing in the game. The Discord desktop app must be running; choose below what is shown.')), body);
  let sig = '', start = null;
  const local = k => 'images/discord/' + k + '.webp';     // the name of the presence on Discord (OP-018)
  const duration = () => { const s = Math.max(0, Math.floor(Date.now() / 1000 - start)), p = n => String(n).padStart(2, '0');
    return T('{0} elapsed', (s >= 3600 ? p(Math.floor(s / 3600)) + ':' : '') + p(Math.floor(s % 3600 / 60)) + ':' + p(s % 60)); };
  const save = vals => act(() => api('/api/panel_settings', { values: vals })).then(x => x && load());
  const draw = r => {
    const s = JSON.stringify(r); if (s === sig) return; sig = s;
    const a = r.settings, e = r.event, on = a.discord_rp, [dt, dc] = RP_STATUS[r.state] || RP_STATUS.off;
    head.replaceChildren(badge(T(dt), dc));
    const sw = (k, dis) => h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: a[k], disabled: dis, onchange: ev => save({ [k]: ev.target.checked }) }), h('span'));
    start = e && e.timestamps ? e.timestamps.start : null;
    const g = e && e.assets || {};
    const preview = h('div', { class: 'rp-card' + (on && e ? '' : ' empty') }, h('div', { class: 'rp-top' }, T('Playing')),
      on && e ? h('div', { class: 'rp-inner' },
        h('div', { class: 'rp-image' }, g.large_image ? h('img', { class: 'rp-large', src: local(g.large_image), sub: '', title: g.large_text || '' }) : null,
          g.small_image ? h('img', { class: 'rp-small', src: local(g.small_image), sub: '', title: g.small_text || '' }) : null),
        h('div', { class: 'rp-text' }, h('b', null, 'OpenOrbit'), h('div', null, e.details),
          h('div', null, e.state, e.party ? ` (${T('{0} of {1}', e.party.size[0], e.party.size[1])})` : ''),
          start ? h('div', { class: 'rp-time' }, duration()) : null)) : h('div', { class: 'small muted' }, on ? T('Nothing is shown on your profile right now.') : T('Rich Presence is off.')),
      on && e && e.buttons ? h('div', { class: 'rp-buttons' }, e.buttons.map(b => h('span', null, b.label))) : null);
    body.replaceChildren(h('div', { class: 'grid g2', style: { alignItems: 'start' } },
      h('div', { class: 'stack rp-setting', style: { gap: '4px' } },
        h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Rich Presence')),
          h('div', { class: 'help' }, r.state === 'discord_not_running' ? T('Connects automatically when Discord opens.') : r.state === 'error' ? r.error : T('Turning it off removes it from your profile at once.'))),
          h('div', { class: 'ctl' }, sw('discord_rp'))),
        h('div', { class: 'rp-fields' + (on ? '' : ' off') }, RP_FIELDS.map(([k, name, assist]) => h('div', { class: 'set-row sub' },
          h('div', null, h('div', { class: 'name' }, T(name)), h('div', { class: 'help' }, T(assist))), h('div', { class: 'ctl' }, sw(k, !on)))))),
      h('div', { class: 'stack', style: { gap: '8px' } }, h('div', { class: 'small muted' }, T('Your profile will look like this:')), preview)));
  };
  const load = () => api('/api/discord_rp').then(draw).catch(() => {});
  load();
  S.timers.push(setInterval(() => { if (card.isConnected) load(); }, 3000));
  S.timers.push(setInterval(() => { const x = card.querySelector('.rp-time'); if (x && start) x.textContent = duration(); }, 1000));
  return card;
}

async function renderPanel() {
  const r = await act(() => api('/api/about')); if (!r || S.page !== 'panel') return;
  const pathRow = (label, p, ne) => h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, label), h('div', { class: 'help mono' }, p)),
    h('div', { class: 'ctl' }, ne ? btn(T('Open'), () => act(() => api('/api/open_folder', { what: ne })), 'sm', 'folder') : null));
  const langSeg = h('div', { class: 'seg diller' }, I18N.list.map(({ code: k, name: t }) => h('button', { class: I18N.lang === k ? 'on info' : '', onclick: async () => {
    if (k === I18N.lang) return;
    const x = await act(() => api('/api/panel_settings', { values: { lang: k } })); if (x) location.reload();
  } }, t)));
  $('#content').replaceChildren(h('div', { class: 'stack' },
    h('div', { class: 'grid g2' },
      h('div', { class: 'card' }, h('h2', null, icon('globe'), 'Dil · Language'),
        h('p', { class: 'desc' }, T("The panel's language. The page reloads when it changes; the game's own language is chosen on its login screen.")), langSeg),
      h('div', { class: 'card' }, h('h2', null, icon('wand'), T('Setup wizard')),
        h('p', { class: 'desc' }, T('Open the language, game folder, first pilot and game settings steps again.')),
        btn(T('Open the wizard'), () => openWizard(0), 'primary', 'wand'))),
    h('div', { class: 'card' }, h('h2', null, icon('users'), 'Discord'),
      h('p', { class: 'desc' }, T('Community server: announcements, help, bug reports and suggestions, with Turkish and English channels.')),
      h('div', { class: 'row wrap' },
        btn(T("Join Discord"), () => act(() => api('/api/discord', {}), T('The invite link opened in your browser.')), 'primary', 'users'),
        h('span', { class: 'small muted mono' }, r.discord))),
    rpCard(),
    updCard(),
    h('div', { class: 'grid g2' },
      h('div', { class: 'card' }, h('h2', null, icon('star'), T('Desktop shortcut')),
        h('p', { class: 'desc' }, T('Puts an OpenOrbit shortcut (with the DarkOrbit icon) on the desktop; double-click it to open this panel (without a console window).')),
        r.old_shortcut ? h('div', { class: 'alert info', style: { marginBottom: '12px' } }, icon('info'),
          h('div', null, T('The old desktop shortcut (DarkOrbit) points to the removed launcher. Create shortcut puts the new one there and removes the old one.'))) : null,
        btn(T('Create shortcut'), async () => {
          if (await act(() => api('/api/shortcut', {}), x => T('Shortcut created: {0}', x.route))) renderPanel();
        }, 'primary', 'plus')),
      h('div', { class: 'card' }, h('h2', null, icon('power'), T('Close the panel')),
        h('p', { class: 'desc' }, T('The panel and the servers it started close. If the game is running, close it first.')),
        btn(T('Close the panel'), async () => {
          if (await confirmBox(T('Close the panel?'), T('The panel and the servers it started will close.'), { ok: T('Close'), danger: true }))
            act(() => api('/api/close', {})).then(x => { if (x) { setTimeout(() => window.close(), 400); document.body.replaceChildren(h('div', { class: 'empty', style: { paddingTop: '26vh' } }, art('no_connection'), h('h3', null, T('Panel closed')), h('div', null, T('You can close this window.')))); } });
        }, 'danger', 'power'))),
    h('div', { class: 'card' }, h('h2', null, icon('folder'), T('Folders')),
      pathRow(T('Project'), r.root, 'project'), pathRow(T('Save slots'), r.saves, 'saves'), pathRow(T('Logs'), r.logs, 'logs'),
      pathRow(T('Game settings file'), r.settings), pathRow(T('Panel settings file'), r.panel)),
    h('div', { class: 'card' }, h('h2', null, icon('info'), T('About')),
      h('div', { class: 'kv', style: { maxWidth: '520px' } }, h('div', null, T('Panel version'), h('b', null, r.version)), h('div', null, 'Python', h('b', null, r.python)),
        h('div', null, T('Panel address'), h('b', null, '127.0.0.1:' + r.port)), h('div', { style: { gridColumn: '1 / -1' } }, T('Internet'), h('b', null, T("for updates, downloading the game and the game's images")))),
      h('p', { class: 'desc', style: { marginTop: '14px' } }, T("OpenOrbit: a single-player, offline local server. The client, graphics and texts belong to Bigpoint GmbH; for personal use only.")))));
}

// ================================================================== SETUP WIZARD
// On first start (if panel.json has no 'dil' or 'kurulum_tamam') and from the Panel page. The steps use the existing APIs;
// 'kurulum_tamam' is written at the end.
const WZ_STEPS = [['lang', N('Language')], ['welcome', N('Welcome')], ['folder', N('Game folder')], ['pilot', N('Pilot')], ['settings', N('Game settings')], ['finished', N('Ready')]];
const WZ = { step: 0, draw: 0 };

function openWizard(step = 0) {
  closeWizard();
  Object.assign(WZ, { step, newPilot: false, created: null, preset: undefined, presetStart: undefined, display: null,
    shortcut: !S.panelCfg?.setup_done, dlAuto: false });
  document.body.append(h('div', { class: 'wizard', id: 'wizard', role: 'dialog', 'aria-modal': 'true' }));
  drawWizard();
}
function closeWizard() { clearInterval(WZ.timer); const w = $('#wizard'); if (w) w.remove(); }
const wzGo = n => { WZ.step = Math.max(0, Math.min(WZ_STEPS.length - 1, n)); drawWizard(); };

async function drawWizard() {
  const root = $('#wizard'); if (!root) return;
  const token = ++WZ.draw;
  const [id] = WZ_STEPS[WZ.step];
  clearInterval(WZ.timer);
  root.classList.add('busy');                      // buttons are locked while loading (so a double click does not skip a step)
  root.querySelectorAll('.wz-foot button, .wz-body button').forEach(b => { b.disabled = true; });
  let p;
  try { p = await WZ_PAGES[id](); } catch (e) { p = { title: T('Something went wrong'), content: h('div', { class: 'alert error' }, icon('alert'), h('div', null, e.message)) }; }
  if (token !== WZ.draw || !$('#wizard')) return;
  root.classList.remove('busy');
  const done = !!S.panelCfg?.setup_done;
  const steps = h('div', { class: 'wz-steps' }, WZ_STEPS.map(([sid, name], i) => h('span', { class: 'wz-step' + (i === WZ.step ? ' on' : i < WZ.step ? ' done' : '') },
    h('i', null, i < WZ.step ? '✓' : String(i + 1)), h('span', null, i === 0 ? 'Dil · Language' : T(name)))));
  const next = p.next === null ? null : p.next || {};
  const nextBtn = next ? btn(next.label || T('Next'), async ev => {
    const b = ev.currentTarget; b.disabled = true;
    let ok = true;
    try { if (next.fn) ok = await next.fn(); } finally { b.disabled = false; }
    if (ok) wzGo(WZ.step + 1);
  }, 'primary', next.icon || 'arrowR', { disabled: next.disabled }) : null;
  const foot = h('div', { class: 'wz-foot' },
    WZ.step > 0 || done ? btn(done ? T('Close the wizard') : T('Skip setup'), () => skipWizard(), 'ghost sm') : null,
    h('span', { class: 'spacer' }),
    p.skip ? btn(T('Skip this step'), () => wzGo(WZ.step + 1), 'ghost') : null,
    WZ.step > 0 ? btn(T('Back'), () => wzGo(WZ.step - 1), '', 'arrowL') : null,
    p.extra || null, nextBtn);
  root.replaceChildren(h('div', { class: 'wz-box' },
    h('div', { class: 'wz-head' }, h('img', { src: 'images/emblem.webp', sub: '' }),
      h('div', null, h('div', { class: 'wz-brand' }, 'OPENORBIT'), h('div', { class: 'wz-kicker' }, WZ.step === 0 ? 'Kurulum · Setup' : T('Setup'))), steps),
    h('div', { class: 'wz-body' }, h('div', { class: 'wz-main' }, h('h2', null, p.title), p.sub ? h('div', { class: 'wz-sub' }, p.sub) : null, p.content),
      art('drone_' + id, 'wz-art')),
    foot));
  if (p.after) p.after();
  const f = root.querySelector('.wz-body input:not([type=checkbox])'); if (f) f.focus();
}

async function skipWizard() {
  const r = await act(() => api('/api/panel_settings', { values: { setup_done: true } })); if (!r) return;
  S.panelCfg = r.settings; closeWizard();
}
async function finishWizard(play) {
  const r = await act(() => api('/api/panel_settings', { values: { setup_done: true } })); if (!r) return false;
  S.panelCfg = r.settings;
  if (WZ.shortcut) await act(() => api('/api/shortcut', {}), x => T('Shortcut created: {0}', x.route));
  closeWizard(); go('play');
  if (play) act(() => api('/api/play', {}));
  else toast(T('Setup complete. Have a good flight!'), 'ok');
  return false;
}
async function chooseLang(code) {
  const r = await act(() => api('/api/panel_settings', { values: { lang: code } })); if (!r) return;
  S.panelCfg = r.settings;
  await setLang(code);
  applyStatic(); buildNav(); go(S.page || 'play', false); renderChrome();
  wzGo(1);
}
function currentPreset(r) {
  const v = (vals, k) => vals[k] ?? r.default[k];
  return Object.keys(r.ready).find(key => r.schema.every(s => v(r.values, s.key) === v(r.ready[key].values, s.key))) || null;
}
const pick = (el, cls = 'on') => { el.parentNode.querySelectorAll(':scope > *').forEach(x => x.classList.remove(cls)); el.classList.add(cls); };

const WZ_PAGES = {
  // ---- 1. language (each language by its own name; the browser's language stands out)
  lang: async () => {
    const cur = S.panelCfg?.lang, hint = cur || guessLang();
    const card = ({ code, name, coverage }) => h('button', { class: 'wz-lang' + (cur === code ? ' on' : hint === code ? ' hint' : ''), type: 'button', onclick: () => chooseLang(code) },
      h('span', { class: 'code' }, code.toUpperCase()), h('b', null, name), coverage < 100 ? h('span', null, coverage + '%') : null);
    return { title: 'Dil seçin · Choose your language', sub: 'Panel bu dilde açılır; sonra Panel sayfasından değişir. · You can change it later on the Panel page.',
      content: h('div', { class: 'wz-langs' }, I18N.list.map(card)),
      next: cur ? { label: T('Next') } : null };
  },
  // ---- 2. welcome
  welcome: async () => ({
    title: T("Welcome to OpenOrbit"),
    sub: T('Single-player, offline DarkOrbit: the original game client connects to a local server on your computer.'),
    content: h('div', { class: 'stack' },
      h('div', { class: 'wz-list' }, [['folder', T('Choose the game folder'), T('The folder where the original DarkOrbit client is installed; if it is not on your computer, the panel downloads it.')],
        ['ship', T('Create your first pilot'), T('Pilot name and company: MMO, EIC or VRU.')],
        ['sliders', T('Choose game settings'), T("A difficulty preset and the game window's display.")]].map(([iconEl, a, b], i) =>
        h('div', { class: 'wz-item' }, h('span', { class: 'wz-num' }, String(i + 1)), icon(iconEl), h('div', null, h('b', null, a), h('div', { class: 'muted small' }, b))))),
      h('div', { class: 'alert info' }, icon('info'), h('div', null, T("The game never connects to the official servers and the client's files are never changed; internet is only used to download the game's images the first time they are shown. You can change everything later in the panel.")))),
    next: { label: T('Begin') },
  }),
  // ---- 3. game folder
  folder: async () => {
    const r = await api('/api/client');
    const c = r.control;
    let dl = r.download;
    const none = !c.valid && !r.candidates.length;
    if (none && dl.state === 'vacant' && !WZ.dlAuto) {     // game not found: start downloading by itself (resume if it was left half done)
      WZ.dlAuto = true;
      dl = await act(() => api('/api/client/download', {})) || dl;
    }
    if (c.valid && c.compatible && dl.running) {      // while a download is in progress a compatible client was found or selected: the download stops
      dl = await act(() => api('/api/client/download_stop', {}), T('Download stopped: the client that was found is used.')) || dl;
    }
    const dlWrap = (!c.valid && (none || DL_ACTIVE(dl))) || (c.valid && (dl.running || dl.partial)) ? h('div', { class: 'dl-wrap' }) : null;
    const bg = !c.valid && dl.running;
    let m = r.runner?.type === 'engine' ? r.runner.engine : null;   // macOS: the Wine that will open the game is downloaded by itself too
    if (m && m.state === 'none' && !WZ.engineAuto) { WZ.engineAuto = true; m = await act(() => api('/api/engine/install', {})) || m; }
    const mWrap = m ? h('div', { class: 'dl-wrap' }) : null;
    let y = c.valid && r.patch.required ? r.patch : null;  // BepInEx for the client's fixes is installed by itself too
    if (y && y.state === 'none' && !WZ.patchAuto) { WZ.patchAuto = true; y = await act(() => api('/api/patch/install', {})) || y; }
    const yWrap = y ? h('div', { class: 'dl-wrap' }) : null;
    const chosen = x => { if (x) drawWizard(); };
    const use = p => act(() => api('/api/client/use', { route: p })).then(chosen);
    const browse = () => act(() => api('/api/client/select', {}), x => x.cancelled ? T('Cancelled.') : T('Game folder selected.')).then(chosen);
    const rows = r.candidates.map(a => h('button', { class: 'wz-opt' + (a.route === c.route ? ' on' : ''), type: 'button', onclick: () => use(a.route) },
      h('span', { class: 'wz-radio' }), h('span', { class: 'mono' }, a.route), badge(a.version || '?', a.compatible ? 'ok' : 'warn')));
    return {
      title: T('DarkOrbit game folder'),
      sub: T("Folder of the original DarkOrbit client: it must contain DarkOrbit.exe and DarkOrbit_Data. The panel doesn't change the client's own files; it installs BepInEx next to them for small fixes."),
      content: [
        rows.length ? field(T('Folders found'), h('div', { class: 'wz-opts' }, rows))
          : c.valid ? null : h('div', { class: 'alert info' }, icon('info'), h('div', null, T('DarkOrbit was not found on your computer, so the game is being downloaded and installed into the project folder. If you already have the game installed, choose its folder.'))),
        dlWrap,
        mWrap ? field(T('The Wine that opens the game (macOS)'), mWrap) : null,
        yWrap ? field(T('Client fixes (BepInEx)'), yWrap) : null,
        bg ? h('div', { class: 'small muted' }, T('The download continues in the background: you can create your pilot in the meantime.')) : null,
        dlWrap ? null : field(T('Selected folder'), h('div', { class: 'path' }, c.route || T('Not selected'))),
        c.route ? h('div', { class: 'check-list', style: { margin: 0 } }, checkRow(c.exe, 'DarkOrbit.exe'), checkRow(c.data, T('DarkOrbit_Data folder')),
          c.valid ? checkRow(c.compatible, versionText(c, r.supported), !c.compatible) : null) : null,
        c.valid && !c.compatible ? h('div', { class: 'alert warning' }, icon('alert'), h('div', null, T("This client is a different version than the server's protocol. The game may still start; if something breaks, adapt the new client on the Client page."))) : null,
        h('div', { class: 'row wrap' }, btn(T('Choose folder…'), browse, rows.length || dlWrap ? '' : 'primary', 'folder'), btn(T('Search again'), () => drawWizard(), 'ghost', 'search'))],
      next: { disabled: !c.valid && !bg }, skip: !c.valid && !bg,
      after: () => {
        if (dlWrap) WZ.timer = dlWatch(dlWrap, dl, () => drawWizard(), { haveClient: c.valid });
        if (mWrap) engineWatch(mWrap, m);              // when the wizard is redrawn the box goes away, the refresh stops by itself
        if (yWrap) patchWatch(yWrap, y);
      },
    };
  },
  // ---- 4. ilk pilot
  pilot: async () => {
    const r = await api('/api/saves');
    if (r.entries.length && !WZ.newPilot) {
      const a = r.entries.find(k => k.active) || r.entries[0];
      return {
        title: WZ.created ? T('Your pilot is ready') : T('Pilot'),
        sub: WZ.created ? T('The save was created and made active.') : T('You already have {0} save(s): continue with the active one or create a new pilot.', r.entries.length),
        content: [h('div', { class: 'card save-card active' },
          h('div', { class: 'head' }, h('div', { style: { minWidth: 0, flex: 1 } },
            h('div', { class: 'row', style: { gap: '8px' } }, h('span', { class: 'title' }, a.pilot), badge(a.company || '?', firmaCls(a.company)), badge(T('ACTIVE'), 'info')),
            h('div', { class: 'sub' }, `${a.name} · ${T('Level')} ${a.level ?? '?'} · ${a.ship} · ${a.map}`)))),
          r.entries.length > 1 ? h('div', { class: 'small muted' }, T('You can switch the active save later on the Saves page.')) : null,
          h('div', { class: 'row' }, btn(T('Create a new pilot'), () => { WZ.newPilot = true; drawWizard(); }, 'ghost', 'plus'))],
        next: {},
      };
    }
    const f = pilotForm({ start: false });
    return {
      title: T('Create your first pilot'), sub: T("You start from scratch with a new pilot. Your company sets your starting map; it can't be changed later."),
      content: [...f.el, r.entries.length ? h('div', { class: 'row' }, btn(T('Cancel'), () => { WZ.newPilot = false; drawWizard(); }, 'ghost', 'undo')) : null],
      next: { label: T('Create pilot'), icon: 'plus', fn: async () => {
        const x = await act(() => api('/api/saves/new', Object.assign(f.values(), { set_active: true })), T('Pilot created.'));
        if (!x) return false;
        WZ.created = x.id; WZ.newPilot = false; poll();
        return true;
      } },
    };
  },
  // ---- 5. game settings: preset and game window
  settings: async () => {
    const [r, c] = await Promise.all([api('/api/settings'), api('/api/client')]);
    if (WZ.presetStart === undefined) { WZ.presetStart = currentPreset(r); WZ.preset = WZ.presetStart; }
    const cfg = c.settings;
    if (!WZ.display) WZ.display = { window_mode: cfg.window_mode, width: cfg.width, height: cfg.height };
    const presets = h('div', { class: 'preset-bar' }, Object.entries(r.ready).map(([key, p]) => h('button', { class: 'preset' + (WZ.preset === key ? ' on' : ''), type: 'button',
      onclick: e => { WZ.preset = key; pick(e.currentTarget); } }, h('b', null, p.name), h('span', null, p.description))));
    const mode = h('div', { class: 'seg' }, WINDOW_MODES.map(([k, t]) => h('button', { class: WZ.display.window_mode === k ? 'on info' : '', type: 'button',
      onclick: e => { WZ.display.window_mode = k; e.currentTarget.parentNode.querySelectorAll('button').forEach(b => b.className = ''); e.currentTarget.className = 'on info'; } }, T(t))));
    const { res, scr } = resolutionList(c);
    const cur = `${WZ.display.width}x${WZ.display.height}`;
    if (!res.includes(cur)) res.push(cur);
    const sel = h('select', { class: 'input', onchange: e => { const [w, hh] = e.target.value.split('x').map(Number); WZ.display.width = w; WZ.display.height = hh; } },
      res.map(x => h('option', { value: x, selected: x === cur }, x + (x === scr ? '  (' + T('screen') + ')' : ''))));
    return {
      title: T('Game settings'), sub: T('Pick a preset and set up the game window. All settings (damage, reward multipliers, events …) are on the Game Settings page later.'),
      content: [field(T('Difficulty and rewards'), presets),
        WZ.presetStart === null ? h('div', { class: 'small muted' }, T('Your current settings differ from the presets; they stay as they are unless you pick one.')) : null,
        h('hr', { class: 'sep', style: { margin: '2px 0' } }),
        h('div', { class: 'grid g2' }, field(T('Window mode'), mode), field(T('Resolution'), sel))],
      next: { fn: async () => {
        if (WZ.preset && WZ.preset !== WZ.presetStart) {
          if (!await act(() => api('/api/settings/presets', { name: WZ.preset }))) return false;
          WZ.presetStart = WZ.preset;
        }
        return !!await act(() => api('/api/panel_settings', { values: WZ.display }));
      } },
    };
  },
  // ---- 6. summary
  finished: async () => {
    const [d, c, a] = await Promise.all([api('/api/status'), api('/api/client'), api('/api/settings')]);
    const k = c.control, cfg = c.settings, pre = currentPreset(a);
    const canPlay = !!d.active && k.valid;
    const dlRun = !k.valid && c.download.running;
    const mode = (WINDOW_MODES.find(([x]) => x === cfg.window_mode) || [, cfg.window_mode])[1];
    const rows = [[true, T('Language'), langOf(I18N.lang).name],
      [k.valid, T('Game folder'), k.valid ? k.route + (k.version ? ' · ' + k.version : '') : dlRun ? T('Downloading: {0}% (you can follow it on the Client page)', dlPct(c.download)) : T('Not selected: choose it on the Client page.')],
      [!!d.active, T('Pilot'), d.active ? `${d.active.pilot} · ${d.active.company}` : T('Not created: create one on the Saves page.')],
      [true, T('Game settings'), pre ? a.ready[pre].name : T('Custom')],
      [true, T('Game window'), `${T(mode)} · ${cfg.width}×${cfg.height}`]];
    const sc = h('input', { type: 'checkbox', checked: WZ.shortcut, onchange: e => { WZ.shortcut = e.target.checked; } });
    return {
      title: canPlay ? T('All set') : T('Almost there'),
      sub: canPlay ? T("Press PLAY to start the servers and open the game.") : dlRun ? T('Once the game has downloaded, you can start it from the Play page.') : T('You can complete the missing steps later in the panel.'),
      content: [h('div', { class: 'wz-summary' }, rows.map(([ok, t, v]) => h('div', { class: ok ? 'ok' : 'wr' }, icon(ok ? 'check' : 'alert'), h('span', null, t), h('b', { title: v }, v)))),
        h('label', { class: 'row small' }, h('span', { class: 'switch' }, sc, h('span')), T('Put an OpenOrbit shortcut on the desktop'))],
      extra: canPlay ? btn(T('Just finish'), () => finishWizard(false), '') : null,
      next: { label: canPlay ? T('Finish and play') : T('Finish'), icon: canPlay ? 'play' : 'check', fn: () => finishWizard(canPlay) },
    };
  },
};

// ================================================================== IN GAME: COMMON
// Shop, Hangar and Skylab from the game server (panel_channel.py: the same path as the client's requests; the windows in the game are updated too).
// Images and item names are the dump of the client's BepInEx plugin (/game_images/: atlas pages, dizin.json, adlar_<lang>.json).
// The same bar above the three pages: switching between pages, wallet and safe zone (equipment changes only there: panel_channel.in_station).
const GI = { index: null, names: {}, lang: null };
async function loadGameImages() {
  const j = async n => { const r = await fetch('/game_images/' + n); if (!r.ok) throw new Error(r.status); return r.json(); };
  if (!GI.index) { try { GI.index = await j('dizin.json'); buildNav(); renderChrome(); } catch (e) { /* no dump: icons, raw names */ } }
  if (GI.index && GI.lang !== I18N.lang) { try { GI.names = await j('adlar_' + I18N.lang + '.json'); GI.lang = I18N.lang; } catch (e) { GI.names = {}; } }
}
// a sprite of the game: cropped from the atlas page, fitted proportionally into the box (width x height) (dizin: page, x, y, w, h, full w, full h, ox, oy)
function sprite(name, size) {
  const e = GI.index?.sprite[name], box = h('span', { class: 'sprite', style: { width: size + 'px', height: size + 'px' } });
  if (!e) return box;
  const [page, x, y, w, hh, W, H, ox, oy] = e, [pw, ph] = GI.index.pages[page], k = size / Math.max(W, H);
  box.append(h('span', { style: { width: W * k + 'px', height: H * k + 'px', position: 'relative' } }, h('span', { style: {
    position: 'absolute', left: ox * k + 'px', top: oy * k + 'px', width: w * k + 'px', height: hh * k + 'px',
    background: 'url("/game_images/' + page + '.png") ' + (-x * k) + 'px ' + (-y * k) + 'px / ' + pw * k + 'px ' + ph * k + 'px no-repeat' } })));
  return box;
}
// lootId -> sprite name: the last part of the id (lf-4_100x100); ships by company (aegis-eic), drones by level (flax-1)
function itemSprite(lid, firma) {
  const k = lid.includes('_') ? lid.slice(lid.indexOf('_') + 1) : lid, last = k.split('_').pop();
  for (const c of [last, k.replace(/_/g, '-'), k, last + '-' + firma, last + '-1'])
    for (const b of ['_100x100', '_63x63', '_top', '_30x30', '']) if (GI.index?.sprite[c + b]) return c + b;
  return null;
}
const itemName = lid => GI.names[lid] || lid.slice(lid.indexOf('_') + 1).replace(/[_-]/g, ' ').toUpperCase();
const gameIcon = (lid, size, firma, iconEl = 'hangar') => {
  const sp = lid && itemSprite(lid, firma), el = sp ? sprite(sp, size) : h('span', { class: 'sprite vacant', style: { width: size + 'px', height: size + 'px' } }, icon(iconEl));
  if (lid) el.dataset.loot = lid;                // item tooltip (itemHint)
  return el;
};

// ---- item tooltip: on hovering over the icon the game's texts (the plugin's dump metinler_<lang>.json: name, type, tooltip description,
// description, note, source; attribute names; English if missing in the language) and the server's values (/api/esya_bilgi: damage, shield, bonuses,
// ships, upgrade, sale). Instance-specific info (upgrade level, random attributes, allowance) is in the _item of the icon's parent.
const IP = { text: null, en: null, lang: null, info: null, el: null, time: 0, box: null, loading: null };
const HINT_LABEL = { damage: N('Damage'), pvp_damage: N('Damage to players'), shield: N('Shield'), absorb: N('Damage absorption'), speed: N('Speed'), hp: N('Hit points'), cargo: N('Cargo'),
  laser_multiplier: N('Laser damage'), hit: N('Hit chance'), full_repair: N('Full repair'), hp_per_minute: N('Repair per minute'), right: N('Charges per refill'), extra_slot: N('Extra slots added'),
  cooldown: N('Cooldown'), cargo_multiplier: N('Cargo'), drone_shield: N('Drone shield'), drone_laser: N('Drone laser damage'), duration: N('Duration'), min_value: N('Minimum bonus'),
  value_range: N('Value range'), reroll: N('Rerolls left'), base_damage: N('Base damage'), element: N('Element'), extra_attribute: N('Extra attributes'),
  defense: N('Defense'), shot: N('Shots'), quality: N('Quality'), max_level: N('Highest level'), range: N('Range'), duration_sec: N('Duration (s)'),
  level_bonus: N('By level'), booster_shield_regeneration: N('Shield regen'), booster_repair: N('Repairs'), booster_collect_resources: N('Resource collection'),
  booster_collect_resources_newbie: N('Resource collection'), booster_ability_cooldown_time: N('Ability cooldown') };
const IP_ELEMENT = { thermal: N('Thermal'), corrosive: N('Corrosive'), electro: N('Electro') };
const HINT_UPGRADE = { LASER_DAMAGE_UPGRADE: N('damage'), ROCKETLAUNCHER_DAMAGE_UPGRADE: N('damage'), GENERATOR_SHIELD_UPGRADE: N('shield'), DRONE_SHIELD_UPGRADE: N('drone shield'),
  DRONE_DAMAGE_UPGRADE: N('drone damage'), CANNON_DAMAGE_UPGRADE: N('damage'), CANNON_DEF_UPGRADE: N('defense'), DRIVE_DAMAGE_UPGRADE: N('damage'), DRIVE_DEF_UPGRADE: N('defense') };
const HINT_SLOT = { lasers: N('Laser'), generators: N('Generator'), extras: N('Extra'), heavy_guns: N('Rocket launcher'), ship_upgrades: N('Module'), QuantumFluidCore: 'QFC',
  cannons: N('Cannon'), cannon_shields: N('Refractor'), drives: N('Drive'), lenses: N('Lens'), default: N('Equipment slot') };
const HINT_PLACE = { SHIP: N('Ship'), PET: 'P.E.T.', DRONE: N('Drone') };
async function loadHints() {
  const j = async n => { const r = await fetch('/game_images/' + n); if (!r.ok) throw new Error(r.status); return r.json(); };
  if (GI.index && IP.lang !== I18N.lang) {
    IP.lang = I18N.lang;
    try { IP.text = await j('metinler_' + I18N.lang + '.json'); } catch (e) { IP.text = null; }
    if (!IP.en && I18N.lang !== 'en') { try { IP.en = await j('metinler_en.json'); } catch (e) { /* old dump: names only */ } }
  }
  if (!IP.info) { try { IP.info = (await api('/api/item_info')).items; } catch (e) { IP.info = {}; } }
}
const hintText = lid => IP.text?.e[lid] || IP.en?.e[lid] || null;
const attributeName = a => IP.text?.n[a] || IP.en?.n[a] || a.replace(/_/g, ' ');
const hintPercent = v => (v > 0 ? '+' : '') + (Math.round(v * 1000) / 10).toLocaleString(LOC()) + '%';
function hintValue(v, b) {
  if (typeof v === 'string') return b === 'e' ? T(IP_ELEMENT[v] || v) : v;
  return { p: () => (Math.round(v * 1000) / 10).toLocaleString(LOC()) + '%', x: () => '×' + fmtN(v), sec: () => fmtDur(v), sa: () => fmtDur(v * 3600) }[b]?.() ?? fmtN(v);
}
// placeholders in the description (%HOURS%, %BOOSTERVALUE% ...; "+%%BOOSTERVALUE%" = "+%" and the value) with their value, or "..." if absent; <br> is a line break,
// other tags are dropped
const hintPlaceholder = (s, ph) => s.replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '')
  .replace(/%([A-Za-z_]+)%/g, (m, k) => { const v = ph && (ph[k] ?? ph[k.toUpperCase()]); return v != null && v !== '' ? String(v) : '…'; });

function itemHint(lid, es, firma) {
  const txt = hintText(lid), b = IP.info?.[lid] || {}, ph = b.ph;
  const row = (k, v, cls = '') => h('div', { class: 'tip-row ' + cls }, h('span', null, k), h('b', null, v));
  const body = [];
  // the tooltip description is a short effect line; if it is the same as the start of the description (formations) only the description
  if (txt?.[2] && !(txt[3] && txt[3].slice(0, 30) === txt[2].slice(0, 30))) body.push(h('div', { class: 'tip-effect' }, hintPlaceholder(txt[2], ph)));
  if (txt?.[3]) body.push(h('div', { class: 'tip-description' }, hintPlaceholder(txt[3], ph)));
  const values = (b.stats || []).map(([k, v, f]) => row(T(HINT_LABEL[k] || k), hintValue(v, f)));
  for (const [a, v] of b.m || []) values.push(row(attributeName(a), hintPercent(v), 'bonus'));
  if (values.length) body.push(h('div', { class: 'tip-block' }, values));
  if (b.slot_info) body.push(h('div', { class: 'tip-slots' }, Object.entries(b.slot_info).map(([k, n]) => h('span', null, T(HINT_SLOT[k] || k), h('b', null, n)))));
  for (const [y, low, t] of b.up || []) {
    const curUpgrade = es?.upgrade || 0;
    body.push(h('div', { class: 'tip-block' }, h('div', { class: 'tip-title' }, T('Upgrades')),
      row(T('Per level'), hintPercent(y) + ' ' + T(HINT_UPGRADE[t] || t)), row(T('Highest level'), '+' + low),
      curUpgrade ? row(T('Current level'), '+' + curUpgrade + ' · ' + hintPercent(y * curUpgrade), 'bonus') : null));
  }
  const r = es?.rng;
  if (r?.attribute?.length) {
    const fraction = r.type === 'module';
    body.push(h('div', { class: 'tip-block rng' }, h('div', { class: 'tip-title' }, T("This item's attributes")),
      r.attribute.map(([a, v]) => row(attributeName(a), hintPercent(fraction ? v : v / 100), 'bonus')),
      r.level ? row(T('Level'), r.level) : null, r.star ? row(T('Stars'), '★'.repeat(r.star)) : null,
      r.right != null ? row(T('Rerolls left'), r.right) : null));
  }
  const ships = r?.ships || (r?.ship ? [r.ship] : null) || b.gm;
  if (ships?.length) body.push(h('div', { class: 'tip-block' }, h('div', { class: 'tip-title' }, r?.ships || r?.ship ? T('Ships it works on') : b.stats?.some(d => d[0] === 'min_value') ? T('Ships it rolls more often') : T('Ships it works on')),
    h('div', { class: 'tip-ships' }, ships.map(g => h('span', null, gameIcon(g, 22, firma, 'ship'), itemName(g))))));
  if (es?.right != null) body.push(row(T('Charges left'), fmtN(es.right[0]) + ' / ' + fmtN(es.right[1])));
  if (txt?.[4]) body.push(h('div', { class: 'ip-not' }, icon('info'), hintPlaceholder(txt[4], ph)));
  const sub = [b.tk ? T('Fits: {0}', b.tk.map(x => T(HINT_PLACE[x] || x)).join(', ')) : null, b.sell ? T('Sells for {0}', fmtN(b.sell) + ' C.') : null].filter(Boolean);
  if (txt?.[5]) body.push(h('div', { class: 'tip-resource' }, hintPlaceholder(txt[5], ph)));
  return h('div', { class: 'tooltip' },
    h('div', { class: 'tip-head' }, gameIcon(lid, 52, firma, 'box'), h('div', { style: { minWidth: 0 } },
      h('b', null, itemName(lid) + (es?.upgrade ? ' +' + es.upgrade : '')), txt?.[1] ? h('div', { class: 'tip-kind' }, txt[1]) : null,
      es?.level ? h('div', { class: 'tip-kind' }, T('Lv {0}', es.level)) : null)),
    body.length ? body : h('div', { class: 'tip-description dim' }, lid),
    sub.length ? h('div', { class: 'tip-bottom' }, sub.join(' · ')) : null);
}
function closeHint() { clearTimeout(IP.time); IP.el = null; IP.box?.remove(); IP.box = null; }
document.addEventListener('mouseover', e => {
  const el = e.target.closest?.('[data-loot]');
  if (el === IP.el) return;
  closeHint();
  if (!el || el.closest('.tooltip')) return;
  IP.el = el;
  for (let n = el; n && n !== document.body; n = n.parentElement) if (n.title) { n.dataset.title = n.title; n.removeAttribute('title'); }   // instead of the browser's name balloon
  IP.time = setTimeout(async () => {
    await (IP.loading ||= loadHints().finally(() => { IP.loading = null; }));
    if (IP.el !== el || !el.isConnected) return;
    let es = null;
    for (let n = el; n && !es; n = n.parentElement) es = n._item || null;
    const k = itemHint(el.dataset.loot, es, el.dataset.company);
    document.body.append(k);
    IP.box = k;
    const r = el.getBoundingClientRect(), w = k.offsetWidth, hh = k.offsetHeight;
    k.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.right + 10 + w > window.innerWidth ? r.left - w - 10 : r.right + 10)) + 'px';
    k.style.top = Math.max(8, Math.min(window.innerHeight - hh - 8, r.top)) + 'px';
  }, 260);
});
document.addEventListener('mousedown', closeHint, true);
document.addEventListener('scroll', closeHint, true);
const formatMoney = (cur, n) => fmtN(n) + (cur === 'credits' || cur === 'credits' ? ' C.' : ' U.');
// the server's error and info keys (BaseKey names, panel_channel's own keys); raw text (with spaces) as it is
const GAME_TEXT = { not_enough_credits: N('You do not have enough credits.'), not_enough_uridium: N('You do not have enough uridium.'), shop_item_not_found: N('This item is not on sale right now.'),
  drone_have_max: N('You already have the maximum number of drones.'), info_text_switch_hangar_station_only: N('You can only change ships while at a station.'),
  error_can_not_equip_to_slot: N('This item cannot go in this slot.'), config_change_failed_time: N('Wait a moment before changing the config.'),
  items_hangarSlot_max_favs: N('You can have at most 10 favourite ships.'), error_pet_name_length: N('The P.E.T. name must be 1-24 characters.'),
  error_pet_name_char: N('The P.E.T. name may only contain letters and digits.'), drone_slotCPUinUse: N('The slot CPU is in use: empty your extra slots first.'),
  pet_gear_requirement: N("The P.E.T.'s level is too low for this item."), special_generic_hint: N('The config already has this extra.') };
const gameText = k => GAME_TEXT[k] ? T(GAME_TEXT[k]) : k && k.includes(' ') ? k : T('Could not do that ({0}).', k || '?');
const GAME_PAGES = [['shop', N('Shop'), 'shop_normal', 'cart'], ['hangar', N('Hangar'), 'hangar_normal', 'hangar'], ['skylab', N('Skylab'), 'skylab_normal', 'lab'],
  ['auction', N('Auction'), 'auction_normal', 'gavel']];

// the common top bar of the three pages; extras: page-specific buttons (search, refresh)
function gameHeader(v, page, ...extras) {
  const currency = (name, n) => h('span', { class: 'pill shop-currency' }, art('source_' + name, 'shop-resource'), h('b', null, fmtN(n)));
  return h('div', { class: 'card game-top' },
    h('div', { class: 'game-tabs' }, GAME_PAGES.map(([id, name, sp, iconEl]) => h('button', { class: 'game-tab' + (id === page ? ' on' : ''), type: 'button',
      onclick: () => id !== page && go(id) }, GI.index?.sprite[sp] ? sprite(sp, 22) : icon(iconEl), h('span', null, T(name))))),
    h('div', { class: 'row wrap', style: { gap: '8px', justifyContent: 'flex-end' } }, currency('credits', v.credits), currency('uridium', v.uridium),
      h('span', { class: 'pill ' + (v.in_station ? 'game-safe' : 'game-space'), title: v.in_station ? T('Equipment can be changed.') : T('Equipment can only be changed in a safe zone.') },
        dot(v.in_station ? 'ok' : 'warn'), v.in_station ? T('In a safe zone') : T('In space')), ...extras));
}
function gameError(e, page) {
  $('#content').replaceChildren(h('div', { class: 'card' }, h('div', { class: 'empty' }, h('p', null, e.message), btn(T('Refresh'), () => go(page), '', 'refresh'))));
}

// ================================================================== IN GAME: SHOP
const SHP_CATEGORY = { ship: N('Ships'), shipdesign: N('Ship designs'), laser: N('Lasers'), ammunition: N('Ammunition'), generator: N('Generators'),
  extras: N('Extras'), booster: N('Boosters'), drone: N('Drones'), petgear: N('P.E.T. gear'), protocol: N('Protocols'), customization: N('Customization') };
const SHP = { data: null, multiplier: null, search: '', level: {} };

async function renderShop() {
  await loadGameImages();
  try { SHP.data = await api('/api/game/shop'); } catch (e) { return gameError(e, 'shop'); }
  if (!SHP.data.categories.includes(SHP.multiplier)) SHP.multiplier = SHP.data.categories[0];
  const grid = h('div', { class: 'shop-grid' });
  const entries = () => {
    const q = SHP.search.trim().toLowerCase(), its = (SHP.data.items[SHP.multiplier] || []).filter(it => !q || itemName(it.lootId).toLowerCase().includes(q));
    grid.replaceChildren(...its.map(shopCard));
    if (!its.length) grid.append(h('div', { class: 'empty' }, T('No products.')));
  };
  const search = h('input', { class: 'input game-search', placeholder: T('Search…'), value: SHP.search, oninput: e => { SHP.search = e.target.value; entries(); } });
  $('#content').replaceChildren(h('div', { class: 'stack' },
    gameHeader(SHP.data, 'shop', search, btn(null, () => renderShop(), 'icon', 'refresh', { title: T('Refresh') })),
    h('div', { class: 'card' },
      !SHP.data.visual ? h('p', { class: 'desc' }, T('The game images are prepared once the game has been started with BepInEx.')) : null,
      h('div', { class: 'seg', style: { flexWrap: 'wrap' } }, SHP.data.categories.map(c =>
        h('button', { class: c === SHP.multiplier ? 'on info' : '', onclick: () => { SHP.multiplier = c; renderShop(); } }, SHP_CATEGORY[c] ? T(SHP_CATEGORY[c]) : c)))),
    grid));
  entries();
}

function shopCard(it) {
  // tiered product (P.E.T. gear, protocol): the price is per level, maxAmount is the highest level the P.E.T. allows (magaza.shop_list)
  const leveled = (it.price || []).length > 1, unaffordable = it.maxAmount === -1;
  const lv = Math.min(SHP.level[it.lootId] || 1, leveled ? Math.max(1, it.maxAmount) : 1);
  const many = !leveled && (!!it.amountsSelectable || it.maxAmount > 1);
  const count = many ? h('input', { class: 'input num', type: 'number', min: 1, max: it.maxAmount > 0 ? it.maxAmount : null, value: 1 }) : null;
  // the server's cost text is in English format ("190,000 U."): the price is written in the panel's number format
  const price = it.price?.length ? fmtN(it.price[lv - 1]) + (it.currency === 'real' ? ' U.' : ' C.') : it.cost;
  return h('div', { class: 'shop-card' + (unaffordable ? ' unavailable' : '') },
    gameIcon(it.lootId, 84, SHP.data.company, 'cart'),
    h('div', { class: 'shop-name', title: it.lootId }, itemName(it.lootId)),
    leveled ? h('div', { class: 'seg shop-lv' }, it.price.map((p, i) => h('button', { class: i + 1 === lv ? 'on info' : '', disabled: i + 1 > Math.max(1, it.maxAmount),
      onclick: () => { SHP.level[it.lootId] = i + 1; renderShop(); } }, T('Lv {0}', i + 1)))) : null,
    h('div', { class: 'shop-price ' + (it.currency === 'real' ? 'uri' : 'cred') }, price),
    h('div', { class: 'row', style: { gap: '6px', justifyContent: 'center' } }, count,
      btn(T('Buy'), e => shopBuy(it, count ? Math.max(1, +count.value | 0) : 1, lv, e.currentTarget), 'sm primary', null, { disabled: unaffordable })),
    it.canBeSubscribedTo ? btn(it.isSubscriptionRunning ? T('End subscription') : T('Subscribe'), e => shopSubscribe(it, e.currentTarget), 'sm ghost') : null);
}

async function shopBuy(it, n, lv, b) {
  b.disabled = true;
  const r = await act(() => api('/api/game/buy', { lootId: it.lootId, category: it.category, amount: n, level: lv }));
  b.disabled = false;
  if (!r) return;
  if (!r.done) return toast(GAME_TEXT[r.error] ? T(GAME_TEXT[r.error]) : T('Could not buy ({0}).', r.error || '?'), 'err');
  toast(T('Bought: {0}', (n > 1 ? fmtN(n) + ' × ' : '') + itemName(it.lootId)), 'ok');
  renderShop();                       // wallet and list (a purchased unique item drops off the list, counts by money)
}

async function shopSubscribe(it, b) {
  b.disabled = true;
  const r = await act(() => api('/api/game/shop/subscribe', { lootId: it.lootId, category: it.category }));
  if (r && !r.done) toast(gameText(r.error), 'err');
  renderShop();
}

// ================================================================== IN GAME: HANGAR
// Ships, two configs; ship, drone and P.E.T. slots, CPUs (panel_channel.py /hangar). Clicking an item in the inventory fits it into the selected
// section (ship, selected drone, P.E.T. or HEAT slot) in the selected config, clicking one in a slot removes it (HangarShipMoveItemsRequest).
// In sell mode those selected from the inventory are sold together. Outside the safe zone equipment does not change (buttons off, the server rejects it too).
const HG_SLOT = { laser: N('Lasers'), rocket: N('Rocket launcher'), generators: N('Generators'), extra: N('Extras'), upgrades: N('Ship modules'),
  QuantumFluidCore: 'Quantum Fluid Core', cannon: N('Particle cannons'), cannonShield: N('Breakers'), drive: 'Singularity Drive', lens: N('Lenses'),
  lasers: N('Lasers'), gears: N('Gears'), protocols: N('Protocols'), visual: N('Look'), heat: 'HEAT', design: N('Drone designs'), other: N('More') };
const slotName = y => HG_SLOT[y] ? T(HG_SLOT[y]) : y;
const HG = { ship: null, config: null, section: 'ship', drone: null, slot: {}, mode: 'equip', set: '', selected: {} };

async function renderHangar() {
  await loadGameImages();
  let v;
  try { v = await api('/api/game/hangar?ship=' + encodeURIComponent(HG.ship || '')); } catch (e) { return gameError(e, 'hangar'); }
  HG.ship = v.ship;
  if (!v.configs[HG.config]) HG.config = v.active_config;
  if (HG.section === 'pet' && !v.pet) HG.section = 'ship';
  const drones = v.drones[HG.config] || [], lock = !v.in_station, iconName = (lid, size) => gameIcon(lid, size, v.company);
  if (!drones.find(d => d.id === HG.drone)) HG.drone = drones[0]?.id ?? null;
  const ship = v.ships.find(g => g.id === v.ship);
  const lvlBadge = e => e.level ? h('span', { class: 'hg-lv' }, '+' + e.level) : null;
  const kick = (e, target, drone) => h('button', { class: 'hg-item', type: 'button', disabled: lock, title: itemName(e.lootId) + ' — ' + T('click to unequip'),
    onclick: ev => hangarMove({ item: e.id, direction: 'kick', target, drone }, ev.currentTarget) }, iconName(e.lootId, 44));
  const empty = n => Array.from({ length: Math.max(0, n) }, () => h('span', { class: 'hg-item vacant' }));
  const slotBox = (name, c, target, extra) => h('div', { class: 'hg-slot' }, h('div', { class: 'row between' }, h('b', null, slotName(name)),
    h('span', { class: 'row', style: { gap: '6px' } }, extra, h('span', { class: 'mono' }, c.items.length + ' / ' + c.capacity))),
    h('div', { class: 'hg-grid' }, c.items.map(e => kick(e, target)), empty(c.capacity - c.items.length)));
  // ships: active first; star is favorite (ships that can be teleported to in the game)
  const ships = h('div', { class: 'hg-ships' }, [...v.ships].sort((a, b) => b.active - a.active || b.favorite - a.favorite).map(g => h('div', { class: 'hg-ship' + (g.id === v.ship ? ' on' : ''),
    title: itemName(g.lootId), onclick: () => { HG.ship = g.id; renderHangar(); } },
    h('button', { class: 'hg-star' + (g.favorite ? ' on' : ''), type: 'button', title: g.favorite ? T('Remove from favourites') : T('Make favourite'),
      onclick: ev => { ev.stopPropagation(); hangarAction({ operation: 'favorite', ship: g.id, favorite: !g.favorite }); } }, icon('star')),
    iconName(g.design || g.lootId, 54), h('span', null, itemName(g.lootId)), g.active ? badge(T('Active'), 'ok') : null)));
  const appearance = v.designs.length > 1 ? h('div', { class: 'row wrap', style: { gap: '6px' } }, h('span', { class: 'lbl' }, T('Look')),
    v.designs.map(t => h('button', { class: 'hg-item' + (t === v.appearance ? ' on' : ''), type: 'button', title: itemName(t), disabled: lock && t !== v.appearance,
      onclick: ev => t !== v.appearance && hangarDesign(t, ev.currentTarget) }, iconName(t, 44)))) : null;
  const tools = h('div', { class: 'row wrap hg-tools' },
    ship.active ? null : btn(T('Make active ship'), e => hangarSetActive(v.ship, e.currentTarget), 'sm primary', null, { disabled: lock }),
    ship.active && HG.config !== v.active_config ? btn(T('Use this config'), () => hangarAction({ operation: 'config', config: HG.config }, T('Config changed.')), 'sm primary') : null,
    btn(T('Save'), () => hangarAction({ operation: 'save', ship: v.ship }, T('Both configs saved.')), 'sm', 'save', { title: T('Stores the equipment of both configs for this ship.') }),
    ship.registered ? btn(T('Load'), () => hangarAction({ operation: 'load', ship: v.ship }, T('Saved equipment loaded.')), 'sm', 'download', { disabled: lock }) : null,
    btn(T('Transfer…'), () => hangarTransfer(v), 'sm', 'copy', { disabled: lock, title: T("Moves this ship's equipment to another ship.") }),
    btn(T('Clear'), async () => await confirmBox(T('Empty config {0}?', HG.config), T('Items on the ship, drones and P.E.T. go back to the inventory.'),
      { ok: T('Clear'), danger: true }) && hangarAction({ operation: 'clean_up', ship: v.ship, config: HG.config }), 'sm', 'trash', { disabled: lock }));
  // selected section
  let section;
  if (HG.section === 'ship') section = h('div', { class: 'hg-slots' }, v.slots.map(y => slotBox(y, v.configs[HG.config][y], 'ship')));
  else if (HG.section === 'drone') section = drones.length ? h('div', { class: 'hg-drones' }, drones.map(d => h('div', { class: 'hg-drone' + (d.id === HG.drone ? ' on' : ''),
    onclick: () => { if (HG.drone !== d.id) { HG.drone = d.id; renderHangar(); } } },
    iconName(d.lootId, 40), h('div', { class: 'grow' }, h('b', null, itemName(d.lootId)), d.id === HG.drone ? h('div', { class: 'lbl' }, T('drone that gets the inventory items')) : null),
    h('div', { class: 'hg-grid' }, d.items.map(e => kick(e, 'drone', d.id)), empty(d.capacity - d.items.length),
      [d.design, d.appearance].map(e => e ? kick(e, 'drone', d.id) : null)),
    btn(T('Sell'), async ev => { ev.stopPropagation(); if (await confirmBox(T('Sell {0}?', itemName(d.lootId)), T('Its items go back to the inventory.'), { ok: T('Sell'), danger: true }))
      hangarAction({ operation: 'drone_sell', drone: d.id }, T('Drone sold.')); }, 'sm ghost', null, { disabled: lock })))) : h('div', { class: 'empty' }, T('No drones.'));
  else if (HG.section === 'pet') {
    const pb = v.pet_info, pc = v.pet[HG.config];
    const openSlot = y => pc[y].price > 0 ? btn('+1 (' + formatMoney('uridium', pc[y].price) + ')', async () => await confirmBox(T('Unlock a {0} slot?', slotName(y)),
      T('{0} uridium will be spent.', fmtN(pc[y].price)), { ok: T('Open') }) && hangarAction({ operation: 'pet_slot', slot: y }, T('Slot unlocked.')), 'sm ghost') : null;
    section = h('div', { class: 'stack' },
      h('div', { class: 'row wrap', style: { gap: '10px' } }, h('b', null, pb.name || 'P.E.T.'), badge(T('Lv {0}', pb.level), 'info'),
        btn(T('Rename ({0})', formatMoney('uridium', pb.rename_price)), async () => { const name = await promptBox(T("P.E.T.'s name"), T('1-24 letters or digits'), pb.name || '');
          if (name != null && name !== pb.name) hangarAction({ operation: 'pet_name', name }, T("The P.E.T.'s name changed.")); }, 'sm ghost'),
        pc.heat.capacity ? h('div', { class: 'seg' }, [['', T('Normal slots')], ['heat', 'HEAT']].map(([k, t]) => h('button', { class: HG.set === k ? 'on info' : '',
          onclick: () => { HG.set = k; renderHangar(); } }, t))) : null),
      !pb.heat_unlocked && pc.heat.capacity ? h('p', { class: 'desc', style: { margin: 0 } }, T("HEAT slots take effect once the P.E.T.'s HEAT level is high enough.")) : null,
      h('div', { class: 'hg-slots' }, v.pet_slots.filter(y => y !== 'heat' || pc.heat.capacity || pc.heat.price).map(y => slotBox(y, pc[y], 'pet', openSlot(y)))));
  } else section = v.cpus.length ? h('div', { class: 'hg-cpus' }, v.cpus.map(c => h('div', { class: 'hg-cpu' }, iconName(c.lootId, 40),
    h('div', { class: 'grow' }, h('b', null, itemName(c.lootId)), c.type === 'ammunition' ? h('div', { class: 'lbl' }, T('buys {1} when below {0}', fmtN(c.threshold), fmtN(c.count))) : null),
    c.type === 'ackapa' ? btn(c.on ? T('On') : T('Off'), () => hangarAction({ operation: 'cpu', lootId: c.lootId }), 'sm ' + (c.on ? 'primary' : 'ghost'))
      : h('select', { class: 'input', onchange: e => hangarAction({ operation: 'cpu_ammo', item: c.id, ammunition: e.target.value }, T('Auto-buy ammo chosen.')) },
        h('option', { value: '', disabled: true, selected: !c.selected }, T('Choose ammo')),
        c.options.map(o => h('option', { value: o, selected: o === c.selected }, itemName(o)))))))
    : h('div', { class: 'empty' }, T('The active config has no CPU with settings.'));
  const sections = [['ship', T('Ship')], ['drone', T('Drones')]].concat(v.pet ? [['pet', 'P.E.T.']] : [], ship.active ? [['cpu', 'CPU']] : []);
  if (!sections.find(([k]) => k === HG.section)) HG.section = 'ship';
  $('#content').replaceChildren(h('div', { class: 'stack' },
    gameHeader(v, 'hangar', btn(null, () => renderHangar(), 'icon', 'refresh', { title: T('Refresh') })),
    h('div', { class: 'card' }, ships),
    h('div', { class: 'card hg-ship-card' },
      lock ? h('div', { class: 'hg-warning' }, icon('alert'), v.portal_hangar ? T("Equipment can only be changed at a station or in a portal's safe zone (a little after combat).")
        : T('Equipment can only be changed at a station (a little after combat).')) : null,
      h('div', { class: 'row between wrap', style: { gap: '10px' } },
        h('div', { class: 'row', style: { gap: '12px' } }, iconName(ship.design || ship.lootId, 64), h('div', null, h('h2', { style: { margin: 0 } }, itemName(ship.lootId)),
          ship.active ? h('span', { class: 'lbl' }, T('Active ship')) : null)),
        h('div', { class: 'seg' }, Object.keys(v.configs).map(c => h('button', { class: c === HG.config ? 'on info' : '', onclick: () => { HG.config = c; renderHangar(); } },
          T('Config {0}', c), ship.active && c === v.active_config ? ' •' : '')))),
      tools, appearance,
      h('div', { class: 'seg' }, sections.map(([k, t]) => h('button', { class: k === HG.section ? 'on info' : '', onclick: () => { HG.section = k; renderHangar(); } }, t))),
      section),
    hangarInventory(v, lock, iconName, lvlBadge)));
}

// inventory card: in fit mode those that can be fitted into the selected section, in sell mode those that can be sold (identical items in one box, with their count)
function hangarInventory(v, lock, iconName, lvlBadge) {
  const sell = HG.mode === 'sell' && HG.section !== 'cpu';
  // items equipped in another config of this ship can be equipped here too (as in game); they are never sold
  const elsewhere = e => e.configs && e.configs.length > 0;
  const eligible = v.inventory.filter(e => sell ? e.selling && !elsewhere(e)
    : HG.section !== 'cpu' && e.targets.includes(HG.section) && !(e.configs || []).includes(String(HG.config)));
  const kinds = [...new Set(eligible.map(e => e.slot))], key = sell ? 'sell' : HG.section;
  if (!kinds.includes(HG.slot[key])) HG.slot[key] = kinds[0];
  const group = {};
  for (const e of eligible.filter(e => e.slot === HG.slot[key])) (group[e.lootId] = group[e.lootId] || []).push(e);
  for (const es of Object.values(group)) es.sort((a, b) => elsewhere(b) - elsewhere(a));      // items of the other config first: free copies stay free
  for (const id of Object.keys(HG.selected)) if (!v.inventory.find(e => String(e.id) === id && e.selling && !elsewhere(e))) delete HG.selected[id];
  const selected = v.inventory.filter(e => HG.selected[e.id]), total = {};
  for (const e of selected) total[e.selling[0]] = (total[e.selling[0]] || 0) + e.selling[1];
  const boxes = Object.entries(group).sort((a, b) => itemName(a[0]).localeCompare(itemName(b[0]))).map(([lid, es]) => {
    const n = es.filter(e => HG.selected[e.id]).length;
    const b = h('button', { class: 'hg-item' + (n ? ' on' : ''), type: 'button', disabled: !sell && lock,
      title: itemName(lid) + (sell ? ' — ' + T('sale value {0}', formatMoney(es[0].selling[0], es[0].selling[1])) + ' · ' + T('click to select, right-click to deselect') : ' — ' + T('click to equip')),
      onclick: ev => { if (!sell) return hangarMove({ item: es[0].id, direction: 'equip', target: HG.section, drone: HG.drone, set: HG.section === 'pet' ? HG.set : '' }, ev.currentTarget);
        const e = es.find(x => !HG.selected[x.id]); if (e) { HG.selected[e.id] = true; renderHangar(); } },
      oncontextmenu: ev => { if (!sell) return; ev.preventDefault(); const e = es.find(x => HG.selected[x.id]); if (e) { delete HG.selected[e.id]; renderHangar(); } } },
      iconName(lid, 44), lvlBadge(es[0]), es.length > 1 ? h('span', { class: 'hg-count' }, (n ? n + '/' : '') + fmtN(es.length)) : n ? h('span', { class: 'hg-count' }, '✓') : null);
    b._item = es[0].level ? { upgrade: es[0].level } : null;        // item tooltip: upgrade level
    return b;
  });
  return h('div', { class: 'card' },
    h('div', { class: 'row between wrap', style: { gap: '10px' } },
      h('div', { class: 'row', style: { gap: '10px' } }, h('h2', { style: { margin: 0 } }, T('Inventory')),
        HG.section !== 'cpu' ? h('div', { class: 'seg' }, [['equip', T('Equip')], ['sell', T('Sell')]].map(([k, t]) => h('button', { class: HG.mode === k ? 'on info' : '',
          onclick: () => { HG.mode = k; renderHangar(); } }, t))) : null),
      h('div', { class: 'seg', style: { flexWrap: 'wrap' } }, kinds.map(y => h('button', { class: y === HG.slot[key] ? 'on info' : '', onclick: () => { HG.slot[key] = y; renderHangar(); } }, slotName(y))))),
    h('div', { class: 'hg-grid', style: { marginTop: '12px' } }, boxes.length ? boxes : h('div', { class: 'empty' }, sell ? T('No items to sell.') : T('No items to equip.'))),
    sell && selected.length ? h('div', { class: 'hg-sell' }, h('span', null, T('{0} items selected', selected.length), ' · ', h('b', null, Object.entries(total).map(([c, n]) => formatMoney(c, n)).join(' + '))),
      h('div', { class: 'row', style: { gap: '6px' } }, btn(T('Clear selection'), () => { HG.selected = {}; renderHangar(); }, 'sm ghost'),
        btn(T('Sell selected'), async () => await confirmBox(T('Sell {0} items?', selected.length), T('You get {0} for them. This cannot be undone.',
          Object.entries(total).map(([c, n]) => formatMoney(c, n)).join(' + ')), { ok: T('Sell'), danger: true })
          && hangarAction({ operation: 'sell', items: selected.map(e => e.id) }, T('Sold.'), () => { HG.selected = {}; }), 'sm primary'))) : null);
}

async function hangarMove(request, b) {
  b.disabled = true;
  const r = await act(() => api('/api/game/hangar/move', Object.assign({ ship: HG.ship, config: HG.config }, request)));
  if (r && !r.done) toast(r.error === 'station' ? T('Equipment can only be changed in a safe zone.') : gameText(r.error), 'err');
  renderHangar();
}

// the hangar's other actions (panel_channel.OPS): on success an info text, then refresh
async function hangarAction(request, okText, after) {
  const r = await act(() => api('/api/game/hangar/action', Object.assign({ ship: HG.ship }, request)));
  if (r && !r.done) toast(r.error === 'station' ? T('Equipment can only be changed in a safe zone.') : gameText(r.error), 'err');
  else if (r) { if (okText) toast(okText, 'ok'); if (after) after(); }
  renderHangar();
}

// Transfer System: this ship's equipment to another ship (the target's slots must be enough)
function hangarTransfer(v) {
  let target = null;
  const entries = h('div', { class: 'hg-ships', style: { flexWrap: 'wrap' } }, v.ships.filter(g => g.id !== v.ship).map(g => h('div', { class: 'hg-ship', onclick: ev => {
    target = g.id; entries.querySelectorAll('.hg-ship').forEach(x => x.classList.toggle('on', x === ev.currentTarget)); } },
    gameIcon(g.design || g.lootId, 54, v.company), h('span', null, itemName(g.lootId)))));
  const m = modal({ title: T('Transfer equipment'), sub: T('Both configs, drones and P.E.T. equipment of {0} move to the ship you choose.', itemName(v.ships.find(g => g.id === v.ship).lootId)),
    body: [entries], wide: true, foot: [btn(T('Cancel'), () => m.close(), 'ghost'), btn(T('Transfer'), () => { if (!target) return toast(T('Choose a ship.'), 'err');
      m.close(); hangarAction({ operation: 'import_action', ship: v.ship, target_ship: target }, T('Equipment transferred.')); }, 'primary')] });
}

async function hangarSetActive(ship, b) {
  b.disabled = true;
  const r = await act(() => api('/api/game/hangar/activate', { ship }));
  if (r && !r.done) toast(gameText(r.error), 'err');
  else if (r) toast(T('Active ship changed.'), 'ok');
  renderHangar();
}

async function hangarDesign(lootId, b) {
  b.disabled = true;
  const r = await act(() => api('/api/game/hangar/design', { ship: HG.ship, lootId }));
  if (r && !r.done) toast(r.error === 'station' ? T('Equipment can only be changed in a safe zone.') : gameText(r.error), 'err');
  renderHangar();
}

// ================================================================== IN GAME: SKYLAB
// Modules, storage, energy, robots and transport (panel_channel.py /skylab): the actions are the client's SkylabActionRequest and
// SkylabPurchaseRobotRequest (rules, costs and times are the same as in the game). No module image: the image of the ore it produces.
const SK_ORE = { PROMETIUM_COLLECTOR: 'prometium', ENDURIUM_COLLECTOR: 'endurium', TERBIUM_COLLECTOR: 'terbium', PROMETID_REFINERY: 'prometid',
  DURANIUM_REFINERY: 'duranium', PROMERIUM_REFINERY: 'promerium', SEPROM_REFINERY: 'seprom', XENO_MODULE: 'xenomit' };
const SK_MODULE = { BASE_MODULE: N('Base module'), SOLAR_MODULE: N('Solar module'), STORAGE_MODULE: N('Storage module'), TRANSPORT_MODULE: N('Transport module'),
  XENO_MODULE: N('Xeno module') };
const oreName = name => itemName('resource_ore_' + name.toLowerCase());
const skModuleName = k => SK_MODULE[k] ? T(SK_MODULE[k]) : k.endsWith('_COLLECTOR') ? T('{0} collector', oreName(SK_ORE[k]))
  : T('{0} refinery', oreName(SK_ORE[k]));
const SK_TEXT = {
  skylab_message_transport_isNotActive: N('The transport module is not running.'), skylab_message_upgrade_maximumLevel: N('The module is at its highest level.'),
  skylab_message_upgrade_basemoduleLevel: N('Upgrade the base module first.'), skylab_message_upgrade_credits: N('You do not have enough credits.'),
  skylab_message_upgrade_prometium: N('Not enough Prometium in the Skylab storage.'), skylab_message_upgrade_endurium: N('Not enough Endurium in the Skylab storage.'),
  skylab_message_upgrade_terbium: N('Not enough Terbium in the Skylab storage.'), skylab_history_module_activate_notBuiltYet: N('The module has not been built yet.'),
  skylab_history_module_deactivated: N('Module switched off.'), skylab_history_module_activated: N('Module switched on.'),
  skylab_history_module_activate_lowpower: N('The solar module does not provide enough energy.'), skylab_history_module_upgrade_lowpower: N('The solar module does not provide enough energy.'),
  skylab_message_upgrade_success: N('Upgrade started.'), skylab_message_upgrade_inProgress: N('This module is already being upgraded.'),
  skylab_history_upgrade_canceled: N('Upgrade cancelled.'), skylab_message_upgrade_uridium: N('You do not have enough uridium.'),
  skylab_history_upgrade_instant: N('Module upgraded.'), skylab_history_upgrade_finished: N('Upgrade finished.'),
  skylab_message_transport_notEnoughUridium: N('You do not have enough uridium.'), skylab_message_transport_alreadyActive: N('A transport is already under way.'),
  skylab_message_transport_requestedOreAmountIsZero: N('Choose the ores to send.'), skylab_message_transport_notEnoughSpaceInShipStorage: N("There is no room in your ship's cargo."),
  skylab_message_transport_isEmpty: N('There are no ores to send in storage.'), skylab_history_transfer_ship_started: N('Transport started.'),
  skylab_history_transfer_ship_finished: N('The ores have reached your ship.') };
const skText = k => SK_TEXT[k] ? T(SK_TEXT[k]) : gameText(k);
const SK = { send: {} };

async function renderSkylab() {
  await loadGameImages();
  let v;
  try { v = await api('/api/game/skylab'); } catch (e) { return gameError(e, 'skylab'); }
  const oreIcon = (name, size) => GI.index?.sprite[name + '_100x100'] ? sprite(name + '_100x100', size) : h('span', { class: 'sprite vacant', style: { width: size + 'px', height: size + 'px' } }, icon('lab'));
  const storage = v.storage.map(o => h('div', { class: 'sk-ore' }, oreIcon(o.name.toLowerCase(), 44),
    h('div', { class: 'grow' }, h('div', { class: 'row between' }, h('b', null, oreName(o.name)), h('span', { class: 'mono' }, fmtN(o.amount) + ' / ' + fmtN(o.capacity))),
      h('div', { class: 'sk-bar' }, h('span', { style: { width: Math.min(100, 100 * o.amount / Math.max(1, o.capacity)) + '%' } })))));
  const modules = v.modules.map(m => {
    const rate = m.level === 0, state = m.remaining != null ? badge(T('Upgrading: {0}', fmtDur(m.remaining)), 'info')
      : rate ? badge(T('Not built')) : m.state === 'ACTIVE' ? badge(T('Running'), 'ok') : badge(T('Off'), 'warn');
    const c = m.cost, buttons = [];
    if (m.remaining != null) {
      buttons.push(btn(T('Finish ({0} U.)', fmtN(m.finish)), () => skylabAction(m.id, 'instantFinishUpgrade'), 'sm primary'),
        btn(T('Cancel'), async () => await confirmBox(T('Cancel the upgrade?'), T('What was spent is not refunded.'), { ok: T('Cancel it'), danger: true })
          && skylabAction(m.id, 'abortUpgrade'), 'sm'));
    } else if (c) {
      buttons.push(btn(rate ? T('Build') : T('Upgrade'), () => skylabAction(m.id, 'upgrade'), 'sm primary'));
      if (c.uridium) buttons.push(btn(T('Instant ({0} U.)', fmtN(c.uridium)), () => skylabAction(m.id, 'instantUpgrade'), 'sm'));
    }
    if (m.toggleable && !rate && m.remaining == null) buttons.push(btn(m.state === 'ACTIVE' ? T('Close') : T('Open'),
      () => skylabAction(m.id, m.state === 'ACTIVE' ? 'setInactive' : 'setActive'), 'sm ghost'));
    return h('div', { class: 'sk-module' + (m.state === 'ACTIVE' ? ' on' : '') },
      h('div', { class: 'row', style: { gap: '10px' } }, SK_ORE[m.id] ? oreIcon(SK_ORE[m.id], 48) : h('span', { class: 'sprite vacant', style: { width: '48px', height: '48px' } }, icon('lab')),
        h('div', { class: 'grow' }, h('b', null, skModuleName(m.id)), h('div', { class: 'mono' }, T('Lv {0} / {1}', m.level, m.maximum)))),
      h('div', { class: 'row wrap', style: { gap: '6px' } }, state,
        m.production ? badge(T('{0} / h', fmtN(m.production)), '') : null, m.energy ? badge(T('{0} energy', fmtN(m.energy)), 'orange') : null,
        m.efficiency ? badge(T('efficiency {0}%', m.efficiency), '') : null),
      c && m.remaining == null ? h('div', { class: 'sk-cost' }, T('{0} C., {1} each of Prometium / Endurium / Terbium, {2}', fmtN(c.credits), fmtN(c.source), fmtDur(c.duration_sec))) : null,
      h('div', { class: 'row wrap', style: { gap: '6px' } }, buttons),
      m.robot && !rate ? h('div', { class: 'sk-robot' }, h('span', { class: 'lbl' }, T('Robots: {0} / {1}', m.robot.enabled, m.robot.maximum) + (m.robot.in_storage ? ' · ' + T('{0} in storage', m.robot.in_storage) : '')),
        h('div', { class: 'row', style: { gap: '6px' } }, ['1', '2'].map(t => btn('+' + (t === '1' ? '1%' : '4%') + ' · ' + formatMoney(m.robot.price[t][0], m.robot.price[t][1]),
          () => skylabRobot(m.id, t), 'sm ghost', null, { title: T('Robot that works for 48 hours') })))) : null);
  });
  const t = v.transport, send = v.storage.map(o => h('label', { class: 'sk-send' }, oreIcon(o.name.toLowerCase(), 28),
    h('input', { class: 'input num', type: 'number', min: 0, max: o.amount, value: SK.send[o.id] || 0, oninput: e => { SK.send[o.id] = +e.target.value | 0; } })));
  const transport = t ? h('div', { class: 'stack' }, h('p', { class: 'desc', style: { margin: 0 } }, T('Transport under way: {0} left.', fmtDur(t.remaining))),
    h('div', null, btn(T('Finish now ({0} U.)', fmtN(v.instant_price)), () => skylabAction('TRANSPORT_MODULE', 'startTransport', 'instantFinish'), 'sm primary')))
    : h('div', { class: 'stack' }, h('div', { class: 'row wrap', style: { gap: '10px' } }, send),
      h('div', { class: 'row wrap', style: { gap: '8px' } }, btn(T('Send'), () => skylabAction('TRANSPORT_MODULE', 'startTransport', ''), 'sm primary'),
        btn(T('Fast send ({0} U.)', fmtN(v.instant_price)), () => skylabAction('TRANSPORT_MODULE', 'startTransport', 'fast'), 'sm')));
  $('#content').replaceChildren(h('div', { class: 'stack' },
    gameHeader(v, 'skylab', h('span', { class: 'pill' + (v.energy.used > v.energy.solar ? ' err' : '') }, T('Energy'), ' ', h('b', null, fmtN(v.energy.used) + ' / ' + fmtN(v.energy.solar))),
      btn(null, () => renderSkylab(), 'icon', 'refresh', { title: T('Refresh') })),
    h('div', { class: 'card' }, h('h2', null, T('Storage')), h('div', { class: 'sk-storage' }, storage)),
    h('div', { class: 'sk-modules' }, modules),
    h('div', { class: 'card' }, h('h2', null, T('Transport to ship')), transport)));
}

async function skylabAction(module, operation, mod) {
  const amounts = operation === 'startTransport' && mod !== 'instantFinish' ? SK.send : {};
  const r = await act(() => api('/api/game/skylab/action', { module, operation, mod: mod || '', amounts }));
  if (r) {
    if (r.errors.length) toast(skText(r.errors[0]), 'err');
    else if (r.achievements.length) toast(skText(r.achievements[r.achievements.length - 1]), 'ok');
    if (r.done && operation === 'startTransport') SK.send = {};
  }
  renderSkylab();
}

async function skylabRobot(module, tip) {
  const r = await act(() => api('/api/game/skylab/robot', { module, tip }));
  if (r && !r.done) toast(skText(r.errors[0]), 'err');
  else if (r) toast(T('Robot bought.'), 'ok');
  renderSkylab();
}

// ================================================================== IN GAME: AUCTION
// Lots, bids and instant buy with the client's Auction* requests (panel_channel.py /muzayede). Auto-bid and alarm rules are
// on the game server (muzayede.oto): they work even when the panel is closed, an alarm becomes an on-screen message in the game. Events (outbid, won, auto
// bid ...) appear as notifications on every page of the panel (auctionEventTick; a desktop notification if permission is granted).
const AUCTION_KIND = { hour: N('Hourly'), day: N('Daily'), week: N('Weekly') };
const AUCTION_GROUP = { ship: N('Ships'), shipdesign: N('Ship designs'), extra: N('Extras'), module: N('Modules'), booster: N('Boosters'),
  battery: N('Laser ammo'), rocket: N('Rockets'), generator: N('Generators'), weapon: N('Weapons'), special: N('Custom') };
const AUCTION_STATUS = [['all', N('All')], ['bid', N('My bids')], ['leading', N('Leading')], ['not_leading', N('Not leading')], ['auto', N('Automatic')], ['alarm', N('With alarm')]];
Object.assign(GAME_TEXT, { auction_bid_minBid_not_reached: N('The bid must be at least 10,000 credits above the highest bid.'), auction_bid_credits_to_little: N('You do not have enough credits.'),
  auction_buy_instant_invalid: N('This lot cannot be bought instantly.'), items_shop_error_ship_contains_ship: N('You already own this ship.'), auction_error_generic: N('The auction action failed.') });
const MZ = { type: 'all', group: 'all', state: 'all', search: '', end_time: {}, last: null };
const auctionKey = l => l.type + '|' + l.loot;
function auctionEventText(o) {
  const name = itemName(o.loot);
  return { outbid: () => T('You were outbid: {0}', name), ending: () => T('{1} min left for {0}.', name, o.min), won: () => T('Won: {0} ({1})', name, formatMoney('credits', o.price)),
    lost: () => T('Lost: {0}', name), auto_bid: () => T('Auto-bid: {0}, {1}', name, formatMoney('credits', o.price)),
    auto_limit: () => T('Auto-bid limit reached: {0} ({1} needed)', name, formatMoney('credits', o.required)) }[o.tip]?.() || o.tip;
}
const auctionEventKind = t => ({ won: 'ok', auto_bid: 'info', outbid: 'err', auto_limit: 'err', lost: 'err', ending: 'info' }[t] || 'info');

async function renderAuction() {
  await loadGameImages();
  let v;
  try { v = await api('/api/game/auction'); } catch (e) { return gameError(e, 'auction'); }
  const now = Date.now() / 1000;
  for (const [k, n] of Object.entries(v.remaining)) MZ.end_time[k] = now + n;
  if (v.events.length) MZ.last = Math.max(MZ.last || 0, v.events[0].no);
  const groups = [...new Set(v.lots.map(l => l.group))];
  const sec = l => (MZ.type === 'all' || l.type === MZ.type) && (MZ.group === 'all' || l.group === MZ.group)
    && (!MZ.search || itemName(l.loot).toLowerCase().includes(MZ.search.toLowerCase()))
    && ({ all: true, bid: l.mine > 0, leading: l.leading, not_leading: !l.leading, auto: !!l.auto, alarm: !!l.alarm })[MZ.state];
  const visible = v.lots.filter(sec).sort((a, b) => (b.leading - a.leading) || (!!b.auto - !!a.auto) || ['hour', 'day', 'week'].indexOf(a.type) - ['hour', 'day', 'week'].indexOf(b.type)
    || itemName(a.loot).localeCompare(itemName(b.loot)));
  const joinable = visible.filter(l => !l.leading), total = joinable.reduce((t, l) => t + l.next, 0);
  const counter = k => h('span', { class: 'pill auc-counter', 'data-kind': k }, h('span', { class: 'lbl' }, T(AUCTION_KIND[k])), h('b', null, fmtDur(MZ.end_time[k] - now)));
  const search = h('input', { class: 'input game-search', placeholder: T('Search…'), value: MZ.search, oninput: e => { MZ.search = e.target.value; clearTimeout(MZ.searchTimer); MZ.searchTimer = setTimeout(renderAuction, 250); } });
  const seg = (entries, value, assign) => h('div', { class: 'seg', style: { flexWrap: 'wrap' } }, entries.map(([k, t]) => h('button', { class: k === value ? 'on info' : '', onclick: () => { assign(k); renderAuction(); } }, t)));
  $('#content').replaceChildren(h('div', { class: 'stack' },
    gameHeader(v, 'auction', search, btn(null, () => renderAuction(), 'icon', 'refresh', { title: T('Refresh') })),
    h('div', { class: 'card auc-top' },
      h('div', { class: 'row between wrap', style: { gap: '10px' } },
        h('div', { class: 'row wrap', style: { gap: '8px' } }, ['hour', 'day', 'week'].map(counter)),
        h('div', { class: 'row wrap', style: { gap: '6px' } },
          btn(T('Bid on all ({0} lots)', joinable.length), async () => joinable.length && await confirmBox(T('Bid on {0} lots?', joinable.length),
            T('The lowest valid bid is placed on each lot ({0} in total). Credits for an outbid lot come back at once.', formatMoney('credits', total)), { ok: T('Place bid') })
            && auctionAll(joinable), 'sm primary', 'gavel', { disabled: !joinable.length }),
          btn(T('Auto-bid on shown lots…'), () => auctionBulkAuto(visible, v), 'sm', null, { disabled: !visible.length }),
          visible.some(l => l.auto) ? btn(T('Turn off auto-bids'), () => auctionBulkDisable(visible.filter(l => l.auto)), 'sm ghost') : null)),
      h('div', { class: 'row wrap', style: { gap: '8px', marginTop: '12px' } },
        seg([['all', T('All')]].concat(['hour', 'day', 'week'].map(k => [k, T(AUCTION_KIND[k])])), MZ.type, k => { MZ.type = k; }),
        seg(AUCTION_STATUS.map(([k, t]) => [k, T(t)]), MZ.state, k => { MZ.state = k; })),
      h('div', { style: { marginTop: '8px' } }, seg([['all', T('All groups')]].concat(groups.map(g => [g, AUCTION_GROUP[g] ? T(AUCTION_GROUP[g]) : g])), MZ.group, k => { MZ.group = k; })),
      !v.rival ? h('p', { class: 'desc', style: { margin: '10px 0 0' } }, T('Virtual rivals are off: you are the only bidder. You can turn them on in Game Settings > Auction.')) : null),
    h('div', { class: 'auc-grid' }, visible.length ? visible.map(l => auctionCard(l, v)) : h('div', { class: 'empty' }, T('No lots.'))),
    h('div', { class: 'auc-bottom' },
      h('div', { class: 'card' }, h('h2', null, icon('bell'), T('Recent events')), v.events.length ? h('div', { class: 'auc-list' }, v.events.map(o => h('div', { class: 'auc-event ' + auctionEventKind(o.tip) },
        dot(auctionEventKind(o.tip) === 'ok' ? 'ok' : auctionEventKind(o.tip) === 'err' ? 'warn' : ''), h('span', { class: 'grow' }, auctionEventText(o)),
        h('span', { class: 'mono muted' }, new Date(o.time * 1000).toLocaleTimeString(LOC(), { hour: '2-digit', minute: '2-digit' })))))
        : h('div', { class: 'empty' }, T('No events yet.'))),
      h('div', { class: 'card' }, h('h2', null, icon('clock'), T('History')), v.history.length ? h('div', { class: 'auc-list' }, v.history.map(g => h('div', { class: 'auc-event' },
        gameIcon(g.loot, 26, v.company, 'gavel'), h('span', { class: 'grow' }, itemName(g.loot), h('span', { class: 'muted' }, ' · ' + T(AUCTION_KIND[g.type] || g.type))),
        h('span', { class: g.who === v.uid ? 'auc-me' : 'muted' }, g.name || '—'), h('span', { class: 'mono' }, formatMoney('credits', g.bid)))))
        : h('div', { class: 'empty' }, T('No history.'))))));
  S.timers.push(setInterval(() => {            // period counters; when the period ends the list is refreshed (the item won, the new period)
    const t = Date.now() / 1000;
    document.querySelectorAll('.auc-counter').forEach(el => { el.querySelector('b').textContent = fmtDur(MZ.end_time[el.dataset.kind] - t); });
    if (Object.values(MZ.end_time).some(b => b - t < -2) && !MZ.refreshing) { MZ.refreshing = true; setTimeout(() => { MZ.refreshing = false; if (S.page === 'auction') renderAuction(); }, 3000); }
  }, 1000));
}

function auctionCard(l, v) {
  const inp = h('input', { class: 'input num', type: 'number', min: l.next, step: v.increase, value: l.next });
  const state = l.leading ? badge(T("You're leading"), 'ok') : l.highest ? badge(T('Highest: {0}', l.highest_name || '—'), 'warn') : badge(T('No bids'));
  return h('div', { class: 'auc-card' + (l.leading ? ' leading' : '') },
    h('div', { class: 'row', style: { gap: '10px', alignItems: 'flex-start' } }, gameIcon(l.loot, 64, v.company, 'gavel'),
      h('div', { class: 'grow' }, h('div', { class: 'shop-name', style: { minHeight: 0 } }, itemName(l.loot)),
        h('div', { class: 'row wrap', style: { gap: '4px', marginTop: '4px' } }, badge(T(AUCTION_KIND[l.type])), l.count > 1 ? badge('× ' + fmtN(l.count)) : null,
          l.auto ? badge(T('Auto ≤ {0}', fmtN(l.auto.maximum)), 'info') : null)),
      // the alarm button is in the heading (when there was no room in the lower row it dropped to the bottom on its own); orange if set
      btn(null, () => auctionAlarmWindow(l), 'sm icon ' + (l.alarm ? 'orange' : 'ghost'), 'bell', { title: l.alarm ? T('Alarm set') : T('Alarm') })),
    h('div', { class: 'auc-row' }, h('span', { class: 'muted' }, T('Highest')), h('b', null, l.highest ? formatMoney('credits', l.highest) : '—')),
    h('div', { class: 'auc-row' }, h('span', { class: 'muted' }, T('Your bid')), h('b', { class: l.leading ? 'auc-me' : '' }, l.mine ? formatMoney('credits', l.mine) : '—')),
    h('div', { class: 'row', style: { gap: '6px' } }, state),
    h('div', { class: 'row', style: { gap: '6px' } }, inp, btn(T('Bid'), e => auctionBid(l, +inp.value | 0, e.currentTarget), 'sm primary'),
      btn('+' + fmtN(v.increase), () => { inp.value = (+inp.value | 0) + v.increase; }, 'sm ghost', null, { title: T('Raise the bid') })),
    h('div', { class: 'row wrap', style: { gap: '6px' } },
      l.instant ? btn(T('Buy now ({0})', formatMoney('uridium', l.price)), async e => await confirmBox(T('Buy {0} now?', itemName(l.loot)), T('{0} uridium will be spent.', fmtN(l.price)), { ok: T('Buy') })
        && auctionInstant(l), 'sm ghost') : null,
      btn(l.auto ? T('Auto: on') : T('Auto-bid'), () => auctionAutoWindow(l, v), 'sm ' + (l.auto ? 'primary' : 'ghost'))));
}

async function auctionBid(l, price, b) {
  b.disabled = true;
  const r = await act(() => api('/api/game/auction/bid', { type: l.type, loot: l.loot, price }));
  if (r && !r.done) toast(gameText(r.error), 'err');
  else if (r) toast(T('Bid placed: {0}, {1}', itemName(l.loot), formatMoney('credits', price)), 'ok');
  renderAuction();
}

async function auctionAll(lots) {
  const r = await act(() => api('/api/game/auction/all', { lots: lots.map(l => [l.type, l.loot]) }));
  if (r) {
    if (r.given) toast(T('Bids placed on {0} lots: {1} in total', r.given, formatMoney('credits', r.amount)), 'ok');
    for (const [k, n] of Object.entries(r.errors)) toast(gameText(k) + ' (' + n + ')', 'err');
  }
  renderAuction();
}

async function auctionInstant(l) {
  const r = await act(() => api('/api/game/auction/instant', { type: l.type, loot: l.loot }));
  if (r && !r.done) toast(gameText(r.error), 'err');
  else if (r) toast(T('Bought: {0}', itemName(l.loot)), 'ok');
  renderAuction();
}

// auto-bid: up to the maximum amount, bids the lowest valid bid each time it is outbid (on the game server; even when the panel is closed)
function auctionAutoWindow(l, v) {
  const inp = h('input', { class: 'input', type: 'number', min: v.min_value, step: v.increase, value: l.auto?.maximum || Math.max(l.next * 2, v.min_value * 5) });
  const m = modal({ title: T('Auto-bid: {0}', itemName(l.loot)), sub: T('Each time you are outbid, the lowest valid bid is placed, up to this amount. It works in the game even with the panel closed.'),
    body: [field(T('At most (credits)'), inp)], foot: [l.auto ? btn(T('Close'), () => { m.close(); auctionRule('auto', l, { maximum: 0 }, T('Auto-bid off.')); }, 'ghost') : null,
      btn(T('Cancel'), () => m.close(), 'ghost'), btn(T('Save'), () => { m.close(); auctionRule('auto', l, { maximum: +inp.value | 0 }, T('Auto-bid on.')); }, 'primary')] });
}

function auctionAlarmWindow(l) {
  const a = l.alarm || {};
  const outbid = h('input', { type: 'checkbox', checked: a.when_outbid ?? true });
  const minutes = h('select', { class: 'input' }, [[0, T('Off')], [5, T('{0} min', 5)], [15, T('{0} min', 15)], [30, T('{0} min', 30)], [60, T('{0} h', 1)], [180, T('{0} h', 3)]]
    .map(([n, t]) => h('option', { value: n, selected: (a.min || 0) === n }, t)));
  const m = modal({ title: T('Alarm: {0}', itemName(l.loot)), sub: T('An alarm shows as a message in the game and a notification in the panel.'),
    body: [h('label', { class: 'row', style: { gap: '8px' } }, outbid, T('Warn me when I am outbid')), field(T('Warn before the period ends'), minutes)],
    foot: [btn(T('Cancel'), () => m.close(), 'ghost'), btn(T('Save'), () => { m.close(); auctionNotifyPermission();
      auctionRule('alarm', l, { when_outbid: outbid.checked, min: +minutes.value }, outbid.checked || +minutes.value ? T('Alarm set.') : T('Alarm removed.')); }, 'primary')] });
}

async function auctionRule(kind, l, fields, okText) {
  const r = await act(() => api('/api/game/auction/' + kind, Object.assign({ type: l.type, loot: l.loot }, fields)));
  if (r) toast(okText, 'ok');
  renderAuction();
}

function auctionBulkAuto(lots, v) {
  const inp = h('input', { class: 'input', type: 'number', min: v.min_value, step: v.increase, value: v.min_value * 10 });
  const m = modal({ title: T('Auto-bid on {0} lots', lots.length), sub: T('The same maximum for every lot. Bids are placed when you are outbid, as long as you have credits.'),
    body: [field(T('At most per lot (credits)'), inp)], foot: [btn(T('Cancel'), () => m.close(), 'ghost'), btn(T('Save'), async () => {
      m.close(); for (const l of lots) await api('/api/game/auction/auto', { type: l.type, loot: l.loot, maximum: +inp.value | 0 }).catch(() => null);
      toast(T('Auto-bid turned on for {0} lots.', lots.length), 'ok'); renderAuction(); }, 'primary')] });
}

async function auctionBulkDisable(lots) {
  for (const l of lots) await api('/api/game/auction/auto', { type: l.type, loot: l.loot, maximum: 0 }).catch(() => null);
  toast(T('Auto-bids off.'), 'ok');
  renderAuction();
}

function auctionNotifyPermission() {
  try { if (window.Notification && Notification.permission === 'default') Notification.requestPermission(); } catch (e) { /* desteklenmiyor */ }
}

// new auction events: a notification on every page (the first poll only sets the starting point); a desktop notification if permission is granted
async function auctionEventTick() {
  if (srvState(S.state).game !== 'on' || auctionEventTick.busy) return;
  auctionEventTick.busy = true;
  try {
    const r = await api('/api/game/auction/events?last=' + (MZ.last || 0));
    const new_ = r.events.filter(o => o.no > (MZ.last || 0)).reverse();
    if (MZ.last !== null) for (const o of new_) {
      toast(T('Auction') + ': ' + auctionEventText(o), auctionEventKind(o.tip), 7000);
      try { if (window.Notification && Notification.permission === 'granted' && document.visibilityState !== 'visible') new Notification('OpenOrbit', { body: auctionEventText(o) }); } catch (e) { /* none */ }
    }
    if (new_.length || MZ.last === null) MZ.last = Math.max(MZ.last || 0, ...r.events.map(o => o.no), 0);
    if (new_.length && S.page === 'auction') renderAuction();
  } catch (e) { /* not in the game */ } finally { auctionEventTick.busy = false; }
}

const RENDER = { play: renderPlay, friend: renderFriends, saves: () => renderSaves(), settings: renderSettings, events: () => renderEvents(), client: () => renderClient(),
  calendar: enterCalendar, server: renderServer, panel: renderPanel, world: () => renderWorld(), bots: () => renderBots(), shop: renderShop, hangar: renderHangar, skylab: renderSkylab, auction: renderAuction };

// ------------------------------------------------------------------ startup
async function boot() {
  let cfg = null;
  try { cfg = await api('/api/panel_settings'); } catch (e) { /* panel closed: poll reports */ }
  S.panelCfg = cfg;
  try { I18N.list = (await api('/api/languages')).languages; } catch (e) { /* old list: Turkish, English */ }
  await setLang((cfg && cfg.lang) || guessLang());
  applyStatic();
  buildNav();
  loadGameImages();                                       // the game's images: icons of the in-game menus
  go(location.hash.slice(1) || 'play', false);
  poll();
  if (cfg && (!cfg.lang || !cfg.setup_done)) openWizard(cfg.lang ? 1 : 0);
}
document.addEventListener('DOMContentLoaded', boot);      // after the later scripts (world_editor.js) have loaded
