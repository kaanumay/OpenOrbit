/* OpenOrbit yerel sunucu paneli — arayüz (panel.py'nin /api/... uçları). Dış kitaplık yok.
   Dil: metinler Türkçe yazılır, T() seçili dildeki hâlini verir (İngilizcesi en.json; Python tarafıyla ortak, dil.py).
   İlk açılışta kurulum sihirbazı: dil, oyun klasörü, ilk pilot, oyun ayarları (panel.json 'dil', 'kurulum_tamam'). Oyun
   bilgisayarda bulunamazsa oyun klasörü adımı onu indirmeye başlar (indirme.py; İstemci sayfasından da). Panel GitHub'daki yeni
   sürümü kurup yeniden başlayınca (guncelleme.py) belirteç değişir: sayfa kendini yeniler. */
'use strict';
const TOKEN = document.querySelector('meta[name="panel-token"]').content;
const $ = (s, r = document) => r.querySelector(s);

// ------------------------------------------------------------------ dil
const I18N = { lang: 'tr', en: null };
function T(s, ...a) {
  let r = I18N.lang === 'en' && I18N.en && I18N.en[s] != null ? I18N.en[s] : s;
  if (a.length) r = r.replace(/\{(\d+)\}/g, (m, i) => a[+i] == null ? '' : String(a[+i]));
  return r;
}
const LOC = () => I18N.lang === 'en' ? 'en-US' : 'tr-TR';
async function setLang(lang) {
  I18N.lang = lang === 'en' ? 'en' : 'tr';
  if (I18N.lang === 'en' && !I18N.en) {
    try { I18N.en = await (await fetch('en.json', { cache: 'no-store' })).json(); } catch (e) { I18N.en = {}; }
  }
  document.documentElement.lang = I18N.lang;
}
function applyStatic() {
  const sub = $('#brand-sub'); if (sub) sub.textContent = T('Yerel Sunucu Paneli');
}

// ------------------------------------------------------------------ simgeler (24x24, çizgi)
const IC = {
  play: '<polygon points="7 4 20 12 7 20 7 4" fill="currentColor" stroke="none"/>',
  save: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  sliders: '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
  calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
  server: '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>',
  info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
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
  s.innerHTML = IC[name] || ''; return s;
}

// ------------------------------------------------------------------ DOM yardımcıları
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  if (props) for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') for (const [p, x] of Object.entries(v)) p.startsWith('--') ? el.style.setProperty(p, x) : el.style[p] = x;   // --c gibi değişkenler yalnız setProperty ile
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
const btn = (label, onclick, cls = '', ic = null, props = {}) =>
  h('button', Object.assign({ class: 'btn ' + cls, onclick, type: 'button' }, props), ic ? icon(ic) : null, label ? h('span', null, label) : null);
const badge = (text, cls = '') => h('span', { class: 'badge ' + cls }, text);
const dot = cls => h('span', { class: 'dot ' + (cls || '') });
const N = s => s;      // çevrilecek metin işareti: değişkende durur, T() ile gösterilir (test_panel_dil.py toplar)
const field = (label, ...ctl) => h('div', { class: 'field' }, h('label', null, label), ...ctl);

// ------------------------------------------------------------------ biçimler
const fmtN = n => (Number(n) || 0).toLocaleString(LOC());
function fmtDur(s) {
  s = Math.max(0, s | 0);
  const d = Math.floor(s / 86400), hh = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  if (d) return T('{0} g {1} sa', d, hh);
  if (hh) return T('{0} sa {1} dk', hh, m);
  if (m) return T('{0} dk', m);
  return T('{0} sn', s);
}
function parseDate(str) { if (!str) return null; const d = new Date(str.replace(' ', 'T')); return isNaN(d) ? null : d; }
function fmtWhen(str) {
  const d = parseDate(str); if (!d) return '—';
  const now = new Date(), diff = (now - d) / 1000;
  const t = d.toLocaleTimeString(LOC(), { hour: '2-digit', minute: '2-digit' });
  const day = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (diff < 60) return T('az önce');
  if (diff < 3600) return T('{0} dk önce', Math.floor(diff / 60));
  if (d >= day) return T('bugün {0}', t);
  if (d >= new Date(day - 86400000)) return T('dün {0}', t);
  if (diff < 7 * 86400) return T('{0} gün önce', Math.floor(diff / 86400));
  return d.toLocaleDateString(LOC(), { day: 'numeric', month: 'short', year: 'numeric' });
}
const fmtBytes = b => b == null ? '—' : b < 1024 ? b + ' B' : b < 1048576 ? (b / 1024).toFixed(1) + ' KB'
  : b < 1073741824 ? (b / 1048576).toFixed(1) + ' MB' : (b / 1073741824).toFixed(2) + ' GB';
const firmaCls = f => ({ MMO: 'mmo', EIC: 'eic', VRU: 'vru' }[f] || '');
const lvl = v => T('Sv') + ' ' + (v ?? '?');

// ------------------------------------------------------------------ API
async function api(path, body) {
  const opt = { headers: { 'X-Panel-Belirteci': TOKEN } };
  if (body !== undefined) {
    opt.method = 'POST'; opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body);
  }
  let r;
  try { r = await fetch(path, opt); } catch (e) { throw new Error(T('Panele ulaşılamıyor: panel kapanmış olabilir.')); }
  const d = await r.json().catch(() => ({}));
  if (r.status === 403 && d.hata && d.hata !== 'host' && !api.reloading) { api.reloading = true; location.reload(); }   // panel yeniden başladı
  if (!r.ok) throw new Error(d.hata || ('HTTP ' + r.status));
  return d;
}
async function act(fn, okMsg) {
  try {
    const r = await fn();
    if (okMsg) toast(typeof okMsg === 'function' ? okMsg(r) : okMsg, 'ok');
    return r;
  } catch (e) { toast(e.message, 'err'); return undefined; }
}

// ------------------------------------------------------------------ bildirim, pencere, menü
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
function confirmBox(title, text, { ok = T('Tamam'), danger = false, detail = null } = {}) {
  return new Promise(res => {
    let done = false;
    const m = modal({
      title, body: [h('div', null, text), detail], onclose: () => { if (!done) res(false); },
      foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(ok, () => { done = true; m.close(); res(true); }, danger ? 'danger' : 'primary')],
    });
  });
}
function promptBox(title, label, value = '', { ok = T('Kaydet'), multiline = false, placeholder = '' } = {}) {
  return new Promise(res => {
    let done = false;
    const inp = multiline ? h('textarea', { class: 'input', placeholder }, value) : h('input', { class: 'input', value, placeholder });
    const submit = () => { done = true; m.close(); res(inp.value); };
    if (!multiline) inp.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
    const m = modal({
      title, body: field(label, inp), onclose: () => { if (!done) res(null); },
      foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(ok, submit, 'primary')],
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

// ------------------------------------------------------------------ sayfalar ve çerçeve
const PAGES = [
  { id: 'oyna', ad: N('Oyna'), ic: 'play', sub: N('Kaydını gör, ayarlarını kontrol et ve oyunu başlat.') },
  { id: 'oyuncular', ad: N('Oyuncu Yönetimi'), ic: 'shield', sub: N('Bağlı oyuncuların envanteri: eşya ver, herkese ver, eşya çıkar. Çıkarmalar denetim günlüğüne yazılır.') },
  { id: 'arkadas', ad: N('Arkadaşlarınla Oyna'), ic: 'users', sub: N('Sunucu kur (Host) ya da arkadaşının sunucusuna katıl (Join). Herkes kendi kaydıyla oynar.') },
  { id: 'kayitlar', ad: N('Kayıtlar'), ic: 'save', sub: N('Kayıt yuvaları, yedekler, kopyalama, içe ve dışa aktarma.') },
  { id: 'ayarlar', ad: N('Oyun Ayarları'), ic: 'sliders', sub: N('Çarpanlar ve kurallar. Kendiliğinden kaydedilir; çoğu oyun açıkken anında uygulanır.') },
  { id: 'etkinlikler', ad: N('Etkinlikler'), ic: 'calendar', sub: N('Her etkinlik takvime göre ya da elle açık / kapalı.') },
  { id: 'takvim', ad: N('Etkinlik Takvimi'), ic: 'agenda', sub: N('Etkinlikler ve seansları saatlik, günlük, haftalık ve aylık görünümde (yerel saat).') },
  { id: 'istemci', ad: N('İstemci'), ic: 'monitor', sub: N('Oyun klasörü, sürüm denetimi ve görüntü seçenekleri.') },
  { id: 'sunucu', ad: N('Sunucu'), ic: 'server', sub: N('Sunucu süreçleri, portlar, davranış ve günlükler.') },
  { id: 'panel', ad: N('Panel'), ic: 'info', sub: N('Dil, kurulum sihirbazı, güncellemeler, masaüstü kısayolu, klasörler ve panel hakkında.') },
];
const S = { durum: null, page: null, sig: {}, timers: [] };

function buildNav() {
  const nav = $('#nav');
  nav.replaceChildren(...PAGES.map(p => h('button', { 'data-page': p.id, onclick: () => go(p.id) }, icon(p.ic), h('span', null, T(p.ad)),
    h('span', { class: 'badge', id: 'nav-badge-' + p.id, style: { display: 'none' } }))));
}
function go(id, push = true) {
  if (!PAGES.find(p => p.id === id)) id = 'oyna';
  S.timers.forEach(clearInterval); S.timers = [];
  S.page = id; S.sig = {};
  if (push && location.hash !== '#' + id) history.replaceState(null, '', '#' + id);
  document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('active', b.dataset.page === id));
  const p = PAGES.find(x => x.id === id);
  $('#page-title').textContent = T(p.ad); $('#page-sub').textContent = T(p.sub);
  $('#content').replaceChildren(h('div', { class: 'empty' }, h('div', { class: 'spin', style: { margin: '30px auto' } })));
  RENDER[id]();
}
window.addEventListener('hashchange', () => go(location.hash.slice(1), false));

function srvState(d) {
  const s = d?.surecler; if (!s) return { web: 'kapali', oyun: 'kapali', istemci: 'kapali' };
  return { web: s.sunucular.web.durum, oyun: s.sunucular.oyun.durum, istemci: s.istemci.durum };
}
const stCls = v => v === 'acik' ? 'ok' : v === 'coktu' ? 'err' : '';
const stText = v => ({ acik: T('Açık'), kapali: T('Kapalı'), coktu: T('Çöktü') }[v] || v);

function renderChrome() {
  const d = S.durum, st = srvState(d);
  const side = $('#side-status');
  side.replaceChildren(
    ...[[T('Web sunucusu'), st.web], [T('Oyun sunucusu'), st.oyun], [T('İstemci'), st.istemci]].map(([n, v]) =>
      h('div', { class: 'row' }, h('span', null, n), h('span', { class: 'row', style: { gap: '6px' } }, dot(stCls(v)), stText(v)))),
    h('div', { class: 'ver' }, S.offline ? T('Panel bağlantısı yok') : 'Panel ' + (d?.panel?.surum || '')));
  const tr = $('#top-right');
  const kids = [];
  if (S.offline) kids.push(h('span', { class: 'pill' }, dot('err'), T('Panel kapandı')));
  else if (d) {
    if (d.aktif) kids.push(h('span', { class: 'pill' }, icon('save'), T('Kayıt:') + ' ', h('b', null, d.aktif.ad)));
    const running = st.istemci === 'acik', srv = st.oyun === 'acik';
    kids.push(h('span', { class: 'pill' }, dot(d.oyna.calisiyor ? 'busy' : running ? 'ok' : srv ? 'warn' : ''),
      d.oyna.calisiyor ? T('Başlatılıyor…') : running ? T('Oyun açık') : srv ? T('Sunucu açık') : T('Kapalı')));
    const extras = d.coklu?.istemciler?.length;
    if (extras) kids.push(h('span', { class: 'pill', style: { cursor: 'pointer' }, onclick: () => go('oyna') }, icon('monitor'), T('{0} ek istemci', extras)));
    const ark = d.arkadas || {};
    if (ark.host || ARK_AKTIF(ark.misafir)) kids.push(h('span', { class: 'pill', style: { cursor: 'pointer' }, onclick: () => go('arkadas') }, icon('users'),
      ark.host ? T('Arkadaş sunucusu açık') : T('Arkadaşın sunucusunda:') + ' ', ark.host ? null : h('b', null, ark.adres)));
  }
  tr.replaceChildren(...kids);
  const setBadge = (id, text, cls) => {
    const b = $('#nav-badge-' + id); if (!b) return;
    b.style.display = text ? '' : 'none'; b.textContent = text || ''; b.className = 'badge ' + (cls || '');
  };
  if (d) {
    setBadge('kayitlar', d.kayit_sayisi ? String(d.kayit_sayisi) : '', '');
    setBadge('etkinlikler', d.etkinlikler.length ? String(d.etkinlikler.length) : '', 'orange');
    const errs = d.uyarilar.filter(u => u.tur === 'hata').length;
    setBadge('sunucu', st.oyun === 'coktu' || st.web === 'coktu' ? '!' : '', 'err');
    setBadge('oyna', errs ? '!' : '', 'err');
    setBadge('ayarlar', d.ayar_ozet.length ? String(d.ayar_ozet.length) : '', 'info');
  }
}

async function poll() {
  try { S.durum = await api('/api/durum'); S.offline = false; } catch (e) { S.offline = true; }
  if (S.durum?.panel?.guncellendi && S.durum.panel.acik_sn < 60 && !S.updToast) { S.updToast = true; toast(T('Panel güncellendi ve yeniden başladı.'), 'ok'); }
  renderChrome();
  if (S.page === 'oyna') { renderOynaBody(); liveTick(); }
  if (S.page === 'sunucu') { renderServerCards(); testTick(); }
  if (S.page === 'arkadas' && ARK.veri) arkTick();
  setTimeout(poll, S.durum?.oyna?.calisiyor ? 500 : 1500);
}
window.addEventListener('pagehide', () => navigator.sendBeacon && navigator.sendBeacon('/api/kapandi', '{}'));

// ================================================================== OYNA
function renderOyna() { S.sig = {}; $('#content').replaceChildren(h('div', { class: 'stack', id: 'oyna' })); renderOynaBody(); }

function renderOynaBody() {
  const d = S.durum, root = $('#oyna');
  if (!root) return;
  if (!d) return;
  const sig = JSON.stringify([d.aktif, d.surecler.sunucular.web.durum, d.surecler.sunucular.oyun.durum, d.surecler.istemci.durum,
    d.surecler.istemci.son, d.oyna, d.uyarilar, d.ayar_ozet, d.etkinlikler, multiSig(d.coklu), S.cokluBusy, Math.floor(Date.now() / 30000)]);
  if (S.sig.oyna === sig) return;
  S.sig.oyna = sig;
  const st = srvState(d), a = d.aktif, o = d.oyna;
  const running = st.istemci === 'acik', srv = st.oyun === 'acik';
  const blocking = d.uyarilar.filter(u => u.tur === 'hata');
  const clientMissing = blocking.some(u => u.sayfa === 'istemci');

  // ---- kahraman kartı
  let left;
  if (!a) {
    left = h('div', null, h('div', { class: 'slot-name' }, T('Kayıt yok')), h('div', { class: 'pilot' }, T('Hoş geldin, pilot')),
      h('div', { class: 'muted' }, T('Oynamak için önce bir kayıt oluştur: pilot adını ve firmanı seç.')),
      h('div', { class: 'row', style: { marginTop: '16px' } }, btn(T('Yeni kayıt oluştur'), () => newSaveModal(), 'primary', 'plus')));
  } else {
    left = h('div', null,
      h('div', { class: 'row', style: { gap: '8px' } }, h('span', { class: 'slot-name' }, a.ad),
        btn(T('Değiştir'), ev => switchSaveMenu(ev.currentTarget), 'ghost sm', 'refresh')),
      h('div', { class: 'pilot' }, a.pilot, badge(a.firma, firmaCls(a.firma)), a.klan ? badge('[' + a.klan + ']', 'info') : null),
      h('div', { class: 'meta' },
        [[T('Seviye'), a.seviye], [T('Gemi'), a.gemi], [T('Harita'), a.harita], [T('Oynama'), fmtDur(a.oynama_sn)],
          [T('Son oynama'), fmtWhen(a.son_oynama || a.son_kayit)]].map(([k, v]) => h('span', null, k + ' ', h('b', null, v)))),
      h('div', { class: 'stats' },
        [[T('Kredi'), a.kredi, 'cr'], [T('Uridyum'), a.uridyum, 'ur'], [T('Onur'), a.onur, 'hn'], [T('Deneyim'), a.ep, 'ep']].map(([k, v, c]) =>
          h('div', { class: 'stat' }, h('div', { class: 'k' }, k), h('div', { class: 'v ' + c }, fmtN(v))))));
  }
  let main, sub = [];
  if (o.calisiyor) {
    main = h('button', { class: 'play-btn busy', disabled: true }, h('span', { class: 'spin', style: { borderTopColor: '#021120' } }), T('BAŞLATILIYOR'));
  } else if (running) {
    main = h('button', { class: 'play-btn running', disabled: true }, icon('check'), T('OYUN AÇIK'));
    sub.push(btn(T('Oyunu kapat'), async () => {
      if (await confirmBox(T('Oyun kapatılsın mı?'), T('İstemci kapatılır. Kaydın sunucuda tutuluyor; oyundan çıkış düğmesiyle çıkmak daha güvenlidir.'),
        { ok: T('Kapat'), danger: true })) act(() => api('/api/istemci/kapat', {}));
    }, 'danger sm', 'power'));
  } else {
    main = h('button', { class: 'play-btn', disabled: !a || clientMissing, onclick: () => act(() => api('/api/oyna', {})) }, icon('play'), T('OYNA'));
    if (srv) sub.push(btn(T('Sunucuyu durdur'), () => act(() => api('/api/sunucu/durdur', {}), T('Sunucular durduruldu.')), 'ghost sm', 'stop'));
    else sub.push(btn(T('Yalnız sunucuyu başlat'), () => act(() => api('/api/oyna', { sadece_sunucu: true })), 'ghost sm', 'server', { disabled: !a }));
  }
  const playCol = h('div', { class: 'play-col' }, main, h('div', { class: 'play-sub' }, sub),
    a ? h('div', { class: 'small muted' }, running ? (S.panelCfg?.istemci_kapaninca === 'acik' || d.coklu?.istemciler?.length ? T('İyi uçuşlar! Oyunu kapatınca sunucular açık kalır.')
      : T('İyi uçuşlar! Oyunu kapatınca sunucular kapanır.')) : srv ? T('Sunucu açık: OYNA istemciyi açar.') : T('Sunucular ve istemci birlikte açılır.')) : null);
  const hero = h('div', { class: 'hero' }, left, playCol);

  // ---- başlatma adımları
  let steps = null;
  const recent = o.bitti && (Date.now() / 1000 - o.bitti < 45);
  if (o.adimlar.length && (o.calisiyor || o.hata || recent)) {
    steps = h('div', { class: 'card' }, h('h2', null, icon('zap'), o.sadece_sunucu ? T('Sunucu başlatma') : T('Oyun başlatma')),
      h('div', { class: 'steps' }, o.adimlar.map(s => h('div', { class: 'step ' + s.durum },
        h('span', { class: 'ic' }, s.durum === 'calisiyor' ? h('span', { class: 'spin' }) : icon(s.durum === 'hata' ? 'x' : 'check')),
        h('span', null, s.metin), h('span', { class: 'dim small', style: { marginLeft: 'auto' } }, s.zaman)))));
  }
  const last = d.surecler.istemci.son;
  const early = last && last.erken && !running ? h('div', { class: 'alert uyari' }, icon('alert'),
    h('div', null, T('İstemci açıldıktan {0} sn sonra kapandı ({1}). Sunucular açık bırakıldı. İstemci günlüğüne bakın.', last.sure_sn, last.zaman)),
    btn(T('Günlük'), () => { go('sunucu'); setTimeout(() => showLog(d.panel.platform === 'win32' ? 'client.log' : 'wine.log'), 100); }, 'sm')) : null;

  // ---- uyarılar
  const warns = d.uyarilar.map(u => h('div', { class: 'alert ' + (u.tur === 'hata' ? 'hata' : 'uyari') }, icon('alert'), h('div', null, u.metin),
    u.eylem ? btn(u.eylem.calisiyor ? T('Kuruluyor…') : u.eylem.metin, () => act(() => api(u.eylem.api, {})), 'primary sm', null, { disabled: !!u.eylem.calisiyor }) : null,
    u.sayfa ? btn(T('Git'), () => go(u.sayfa), 'sm') : null));

  // ---- özet kartları
  const setCard = h('div', { class: 'card' }, h('h2', null, icon('sliders'), T('Etkin ayarlar')),
    h('p', { class: 'desc' }, d.ayar_ozet.length ? T('Varsayılandan farklı olanlar:') : T('Bütün ayarlar varsayılan.')),
    h('div', { class: 'chips' }, d.ayar_ozet.map(x => h('span', { class: 'chip' }, x.ad, h('b', null, x.deger)))),
    h('div', { class: 'row', style: { marginTop: '14px' } }, btn(T('Ayarları düzenle'), () => go('ayarlar'), 'sm', 'sliders')));
  const evCard = h('div', { class: 'card' }, h('h2', null, icon('calendar'), T('Açık etkinlikler')),
    h('p', { class: 'desc' }, d.etkinlikler.length ? T('Oyuna girdiğinde etkin olan yıllık etkinlikler:') : T('Şu an açık yıllık etkinlik yok.')),
    h('div', { class: 'chips' }, d.etkinlikler.map(n => h('span', { class: 'chip' }, '🎉 ', n))),
    h('div', { class: 'row wrap', style: { marginTop: '14px' } }, btn(T('Etkinlikleri yönet'), () => go('etkinlikler'), 'sm', 'calendar'),
      btn(T('Takvim'), () => go('takvim'), 'ghost sm', 'agenda')));
  const srvCard = h('div', { class: 'card' }, h('h2', null, icon('server'), T('Sunucu')),
    h('div', { class: 'check-list' }, [[T('Web girişi (8090, 80)'), st.web, d.surecler.sunucular.web.sure_sn],
      [T('Oyun sunucusu (8081)'), st.oyun, d.surecler.sunucular.oyun.sure_sn], [T('İstemci'), st.istemci, d.surecler.istemci.sure_sn]].map(([n, v, t]) =>
      h('div', null, dot(stCls(v)), h('span', null, n), h('span', { class: 'muted small', style: { marginLeft: 'auto' } },
        stText(v) + (v === 'acik' && t != null ? ' · ' + fmtDur(t) : ''))))),
    h('div', { class: 'row' }, btn(T('Sunucu ve günlükler'), () => go('sunucu'), 'sm', 'server')));

  root.replaceChildren(...[...warns, hero, steps, early, multiCard(d), srv || S.live?.var ? liveCard() : null,
    h('div', { class: 'grid g3' }, setCard, evCard, srvCard)].filter(Boolean));
}

// ---- çoklu istemci (coklu.py, /api/coklu): OYNA'dan sonra öteki kayıtlarla aynı sunucuya ek istemciler
const multiSig = c => c && JSON.stringify(Object.assign({}, c, { istemciler: (c.istemciler || []).map(x => Object.assign({}, x, { sure_sn: null })) }));
async function openExtra(id, pilot) {
  S.cokluBusy = id; S.sig.oyna = null; renderOynaBody();
  const r = await act(() => api('/api/coklu/ac', { kayit: id }), T('Ek istemci açılıyor: {0}', pilot));
  S.cokluBusy = null; S.sig.oyna = null;
  try { S.durum = await api('/api/durum'); } catch (e) { /* bir sonraki yoklamada */ }
  renderChrome(); renderOynaBody();
  return r;
}
function extraBlock(d, k) {
  const c = d.coklu, open = c.istemciler || [];
  const pilots = [(c.kayitlar || []).find(x => x.id === c.ana)?.pilot, ...open.map(x => x.pilot)].filter(Boolean).map(p => p.toLowerCase());
  return srvState(d).oyun !== 'acik' ? T('Önce OYNA') : d.oyna.calisiyor ? T('Başlatma sürüyor') : k.bozuk ? T('Kayıt bozuk')
    : k.arkadas ? T('Arkadaşının sunucusunda') : open.length >= c.en_cok ? T('Sınır dolu ({0})', c.en_cok)
    : pilots.includes((k.pilot || '').toLowerCase()) ? T('Aynı pilot adı açık') : S.cokluBusy ? T('Açılıyor…') : null;
}
function multiCard(d) {
  const c = d.coklu; if (!c) return null;
  const open = c.istemciler || [], st = srvState(d), srv = st.oyun === 'acik';
  if (!open.length && (!c.ayar || c.kayit_sayisi < 2)) return null;      // kapalı ya da başka kayıt yok: kart yok (İstemci sayfasında ayar)
  const now = Date.now() / 1000;
  const others = (c.kayitlar || []).filter(k => !k.ek && k.id !== c.ana);
  const desc = !srv ? T('OYNA\'dan sonra öteki kayıtlarınla aynı sunucuya ek istemciler açabilirsin: her biri ayrı pencerede, kendi pilotuyla. Birbirinizi oyunda görür, grup kurup birlikte uçarsınız.')
    : !c.sunucu ? (st.istemci === 'acik' ? T('Sunucu tek oyunculu açıldı: ek istemci için oyunu kapatıp yeniden OYNA\'ya bas.')
      : T('Sunucu tek oyunculu açık: ilk ek istemci açılırken sunucu çok oturumlu yeniden başlar.'))
    : T('Ek istemciler bu sunucuya bağlanır; pencere başlığı pilotun adıdır. Her istemci yaklaşık 600 MB bellek kullanır.');
  const logBtn = id => btn('', () => { go('sunucu'); setTimeout(() => showLog('client_' + id + '.log'), 100); }, 'ghost sm icon', 'note', { title: T('Günlük') });
  const openRows = open.map(x => h('tr', null, h('td', null, h('b', null, x.pilot),
      [(c.kayitlar || []).find(k => k.id === x.kayit)?.ad || x.kayit].filter(a => a !== x.pilot).map(a => h('div', { class: 'small muted' }, a))),
    h('td', null, x.seviye ?? '—'), h('td', null, x.harita || '—'),
    h('td', null, x.durum === 'aciliyor' ? badge(T('Açılıyor'), 'info') : x.durum === 'kapaniyor' ? badge(T('Kapanıyor'), 'orange')
      : x.bagli ? badge(T('Oyunda'), 'ok') : badge(T('Bağlanıyor'), 'info')),
    h('td', { class: 'muted small' }, (x.pid ? 'PID ' + x.pid + ' · ' : '') + fmtDur(x.sure_sn)),
    h('td', { class: 'num' }, h('div', { class: 'actions', style: { justifyContent: 'flex-end' } }, logBtn(x.kayit),
      btn(T('Kapat'), async () => {
        if (await confirmBox(T('{0} kapatılsın mı?', x.pilot), T('Ek istemcinin penceresi kapanır; kaydın son hâli yazılır.'), { ok: T('Kapat'), danger: true }))
          act(() => api('/api/coklu/kapat', { kayit: x.kayit }), T('{0} kapatılıyor.', x.pilot));
      }, 'ghost sm', 'power', { disabled: x.durum !== 'acik' })))));
  const otherRows = others.map(k => {
    const why = extraBlock(d, k), busy = S.cokluBusy === k.id;
    return h('div', { class: 'row multi-row' }, h('span', { style: { minWidth: 0, flex: 1 } }, h('b', null, k.pilot || '?'), ' ',
      badge(k.firma || '?', firmaCls(k.firma)), h('span', { class: 'small muted' }, ' ' + lvl(k.seviye) + ' · ' + k.ad)),
      why && !busy ? h('span', { class: 'small dim' }, why) : null,
      btn(busy ? T('Açılıyor…') : T('Ek istemcide aç'), () => openExtra(k.id, k.pilot), 'primary sm', busy ? null : 'play', { disabled: !!why || busy }));
  });
  const early = Object.entries(c.son || {}).filter(([id, s]) => s.erken && now - s.bitis < 120 && !open.some(x => x.kayit === id)).map(([id, s]) =>
    h('div', { class: 'alert uyari' }, icon('alert'), h('div', null, T('{0} kaydının ek istemcisi açıldıktan {1} sn sonra kapandı ({2}). İstemci günlüğüne bakın.',
      (c.kayitlar || []).find(k => k.id === id)?.ad || id, s.sure_sn, s.zaman)), logBtn(id)));
  return h('div', { class: 'card', id: 'coklu-card' },
    h('div', { class: 'row between wrap' }, h('h2', null, icon('monitor'), T('Çoklu istemci')),
      h('div', { class: 'row wrap', style: { gap: '6px' } }, badge(T('{0} / {1} ek istemci', open.length, c.en_cok), open.length ? 'ok' : ''),
        open.length > 1 ? btn(T('Hepsini kapat'), async () => {
          if (await confirmBox(T('Ek istemcilerin hepsi kapatılsın mı?'), T('{0} pencere kapanır; kayıtların son hâli yazılır. Ana istemci açık kalır.', open.length), { ok: T('Hepsini kapat'), danger: true }))
            act(() => api('/api/coklu/hepsini_kapat', {}), T('Ek istemciler kapatılıyor.'));
        }, 'ghost sm', 'power') : null,
        btn('', () => go('istemci'), 'ghost sm icon', 'sliders', { title: T('Çoklu istemci ayarları') }))),
    h('p', { class: 'desc' }, desc),
    early,
    open.length ? h('table', { class: 'table', style: { marginBottom: others.length ? '12px' : 0 } },
      h('thead', null, h('tr', null, [T('Pilot'), T('Seviye'), T('Harita'), T('Durum'), T('Süre'), ''].map(x => h('th', null, x)))),
      h('tbody', null, openRows)) : null,
    others.length ? h('div', { class: 'stack', style: { gap: '6px' } }, otherRows)
      : !c.ayar ? null : h('div', { class: 'small muted' }, T('Açılabilecek başka kayıt yok.')));
}

// ---- canlı durum (oyun sunucusunun durum.json'u; canli_durum.py, /api/canli)
async function liveTick() {
  if (S.page !== 'oyna' || S.liveBusy) return;
  S.liveBusy = true;
  try { S.live = await api('/api/canli'); } catch (e) { S.live = null; } finally { S.liveBusy = false; }
  const c = $('#canli-card'), want = srvState(S.durum).oyun === 'acik' || !!S.live?.var;
  if (c && want) c.replaceWith(liveCard());
  else if (!!c !== want) { S.sig.oyna = null; renderOynaBody(); }     // kart çıksın / kalksın
}
function meter(label, v, max, cls) {
  const pct = max ? Math.max(0, Math.min(100, v * 100 / max)) : 0;
  return h('div', { class: 'meter ' + (cls || '') }, h('div', { class: 'row between small' }, h('span', { class: 'muted' }, label), h('b', null, fmtN(v) + ' / ' + fmtN(max))),
    h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } })));
}
function lootPicker(placeholder) {
  const input = h('input', { class: 'input', placeholder, autocomplete: 'off' });
  const results = h('div', { class: 'loot-results', hidden: true });
  const wrap = h('div', { class: 'loot-picker' }, input, results);
  let items = [];
  const close = () => { results.hidden = true; results.replaceChildren(); };
  const terms = value => String(value).toLocaleLowerCase().replace(/[_-]+/g, ' ').split(/\s+/).filter(Boolean);
  const draw = () => {
    const query = terms(input.value);
    if (!query.length || input.value.trim().length < 2) return close();
    const rows = items.filter(([id, name]) => {
      const haystack = (id + ' ' + name).toLocaleLowerCase();
      return query.every(term => haystack.includes(term));
    }).slice(0, 12);
    results.replaceChildren(...rows.map(([id, name]) => h('button', { type: 'button', onclick: () => {
      input.value = id; close(); input.focus();
    } }, h('b', { class: 'mono' }, id), name ? h('span', null, name) : null)));
    results.hidden = !rows.length;
  };
  input.addEventListener('input', draw);
  input.addEventListener('focus', draw);
  input.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  api('/api/esya_listesi').then(r => { items = r.esyalar || []; draw(); }).catch(() => {});
  return { input, el: wrap };
}
// ---- Oyuncu Yönetimi (yonetim.py, /api/oyuncular): Aternos tarzı oyuncu listesi; eşya verme ve çıkarma yalnız burada (Canlı durumda yok)
const OY = { veri: null, sec: null, env: null, sekme: 'envanter', ara: '', tur: '', denetim: null, gorunum: 'izgara', yok: new Set() };
const OY_TUR = { ekipman: N('Ekipman'), cephane: N('Cephane'), cevher: N('Cevher'), kaynak: N('Kaynak'), gemi: N('Gemi'), dron: N('Dron') };
const OY_ISLEM = { ver: [N('Verildi'), 'ok'], herkese_ver: [N('Herkese verildi'), 'info'], cikar: [N('Çıkarıldı'), 'err'] };

async function renderOyuncular() {
  $('#content').replaceChildren(h('div', { class: 'stack', id: 'oyuncular' }));
  await oyLoad(true);
  S.timers.push(setInterval(() => { if (document.visibilityState === 'visible' && !document.querySelector('.modal')) oyLoad(false); }, 3000));
}
async function oyLoad(force) {
  let v;
  try { v = await api('/api/oyuncular'); } catch (e) { if (force) toast(e.message, 'err'); return; }
  if (S.page !== 'oyuncular') return;
  const online = v.oyuncular.filter(p => p.cevrimici);
  if (OY.sec && !online.some(p => p.id === OY.sec)) { OY.sec = null; OY.env = null; }
  if (!OY.sec && online.length) OY.sec = online[0].id;
  OY.env = null;
  if (OY.sec) { try { OY.env = await api('/api/oyuncular/envanter?oyuncu=' + encodeURIComponent(OY.sec)); } catch (e) { OY.env = null; } }
  if (OY.sekme === 'denetim' && v.sunucu_acik) { try { OY.denetim = (await api('/api/oyuncular/denetim')).kayitlar; } catch (e) { /* kanal yanıt vermedi */ } }
  if (S.page !== 'oyuncular') return;
  OY.veri = v;
  const sig = JSON.stringify([v, OY.env, OY.denetim, OY.sec, OY.sekme]);
  if (!force && S.sig.oy === sig) return;
  S.sig.oy = sig; oyDraw();
}
function oySelect(id) { OY.sec = id; OY.env = null; OY.ara = ''; OY.tur = ''; oyLoad(true); }
function oyDraw() {
  const focus = document.activeElement && document.activeElement.id === 'oy-ara' ? document.activeElement.selectionStart : null;
  const root = $('#oyuncular'); if (!root) return;
  root.replaceChildren(h('div', { class: 'pm' }, oyList(), oyDetail()));
  const inp = $('#oy-ara');
  if (focus != null && inp) { inp.focus(); inp.setSelectionRange(focus, focus); }
}
function oyList() {
  const v = OY.veri, online = v.oyuncular.filter(p => p.cevrimici), offline = v.oyuncular.length - online.length;
  const row = p => h('div', { class: 'pm-row' + (p.cevrimici ? ' can' : '') + (p.id && p.id === OY.sec ? ' on' : ''), onclick: p.cevrimici ? () => oySelect(p.id) : null },
    dot(p.cevrimici ? 'ok' : ''), h('div', { class: 'grow' }, h('b', null, p.ad || '?'), ' ',
      p.seviye ? h('span', { class: 'small muted' }, lvl(p.seviye)) : null, p.firma ? [' ', badge(p.firma, firmaCls(p.firma))] : null),
    p.cevrimici ? badge(T('Çevrimiçi'), 'ok') : [badge(T('Çevrimdışı'), ''), btn('', ev => { ev.stopPropagation(); go('kayitlar'); }, 'sm ghost', 'save', { title: T('Kayıt düzenleyici') })]);
  return h('div', { class: 'card' },
    h('div', { class: 'row between wrap' }, h('h2', null, icon('users'), T('Oyuncular')),
      btn(T('Herkese eşya ver'), () => oyGiveModal(null), 'sm', 'plus', { disabled: !online.length })),
    !v.sunucu_acik ? h('p', { class: 'desc' }, T('Oyun sunucusu kapalı: canlı işlemler için önce OYNA ile sunucuyu başlatın.')) : null,
    v.hata ? h('div', { class: 'alert hata' }, icon('alert'), h('div', null, v.hata)) : null,
    v.oyuncular.length ? h('div', { class: 'stack', style: { gap: '6px', marginTop: '10px' } }, v.oyuncular.map(row))
      : h('p', { class: 'desc' }, T('Henüz oyuncu ya da kayıt yok.')),
    offline ? h('p', { class: 'small muted', style: { marginTop: '10px' } }, T('Çevrimdışı kayıtlar canlı düzenlenemez: sunucu durmuşken Kayıtlar sayfasındaki kayıt düzenleyiciyi kullanın.')) : null);
}
function oyDetail() {
  const env = OY.env;
  if (!env) return h('div', { class: 'card' }, h('div', { class: 'empty' }, T('Bağlı oyuncu yok.')));
  const tabs = h('div', { class: 'seg' }, [['envanter', T('Envanter')], ['denetim', T('Denetim günlüğü')]].map(([k, t]) =>
    h('button', { class: OY.sekme === k ? 'on info' : '', onclick: () => { OY.sekme = k; S.sig.oy = null; oyLoad(true); } }, t)));
  const m = env.para;
  const stats = h('div', { class: 'stats', style: { marginTop: '12px' } },
    [[T('Seviye'), m.seviye, ''], [T('Kredi'), m.kredi, 'cr'], [T('Uridyum'), m.uridyum, 'ur'], [T('Onur'), m.onur, 'hn']].map(([a, val, c]) =>
      h('div', { class: 'stat' }, h('div', { class: 'k' }, a), h('div', { class: 'v ' + c }, fmtN(val)))));
  return h('div', { class: 'card' },
    h('div', { class: 'row between wrap' }, h('h2', null, icon('ship'), env.oyuncu, ' ', badge(T('Çevrimiçi'), 'ok')),
      btn(T('Eşya ver'), () => oyGiveModal({ id: env.id, ad: env.oyuncu }), 'sm', 'plus')),
    stats, h('div', { class: 'row', style: { marginTop: '14px' } }, tabs),
    OY.sekme === 'envanter' ? oyInventory() : oyAudit());
}
function oyInventory() {
  const ara = h('input', { class: 'input', id: 'oy-ara', placeholder: T('Eşya ara…'), value: OY.ara, autocomplete: 'off',
    oninput: ev => { OY.ara = ev.currentTarget.value; $('#oy-table').replaceChildren(oyTable()); } });
  const tur = h('select', { class: 'input', style: { width: 'auto' }, onchange: ev => { OY.tur = ev.currentTarget.value; $('#oy-table').replaceChildren(oyTable()); } },
    h('option', { value: '' }, T('Tüm türler')), Object.entries(OY_TUR).map(([k, n]) => h('option', { value: k, selected: OY.tur === k }, T(n))));
  return h('div', null, h('div', { class: 'pm-tools' }, ara, tur,
    h('div', { class: 'seg' }, [['izgara', T('Izgara')], ['liste', T('Liste')]].map(([k, t]) =>
      h('button', { class: OY.gorunum === k ? 'on info' : '', onclick: () => { OY.gorunum = k; S.sig.oy = null; oyLoad(true); } }, t)))),
    h('div', { id: 'oy-table' }, oyTable()),
    h('p', { class: 'small muted', style: { marginTop: '10px' } }, T('Takılı ekipman çıkarılamaz: oyuncu önce hangardan çıkarmalı. Çıkarılanlar denetim günlüğüne yazılır, sohbette duyurulmaz.')));
}
function oyTable() {
  const env = OY.env, q = OY.ara.trim().toLocaleLowerCase();
  const rows = env.esyalar.filter(r => (!OY.tur || r.tur === OY.tur) && (!q || r.esya.toLocaleLowerCase().includes(q)))
    .sort((a, b) => a.tur === b.tur ? (a.esya < b.esya ? -1 : 1) : (a.tur < b.tur ? -1 : 1));
  if (!rows.length) return h('p', { class: 'desc' }, env.esyalar.length ? T('Filtreye uyan eşya yok.') : T('Envanter boş.'));
  if (OY.gorunum === 'izgara') return oyGrid(rows);
  return h('div', { class: 'pm-scroll' }, h('table', { class: 'table' },
    h('thead', null, h('tr', null, [T('Eşya'), T('Tür'), T('Adet'), T('Takılı'), ''].map(x => h('th', null, x)))),
    h('tbody', null, rows.map(r => h('tr', null,
      h('td', null, h('span', { class: 'mono' }, r.esya)), h('td', null, badge(T(OY_TUR[r.tur] || r.tur), '')), h('td', null, fmtN(r.adet)),
      h('td', null, r.takili ? fmtN(r.takili) : '—'),
      h('td', { style: { textAlign: 'right' } }, r.silinebilir > 0
        ? btn(T('Çıkar'), () => oyRemove(r), 'sm danger', 'trash')
        : btn(T('Çıkar'), null, 'sm', 'trash', { disabled: true, title: T('Takılı ekipman çıkarılamaz.') })))))));
}
// Izgara: Aternos gibi kutular; simge ikonlar/<lootId>.png (tools/ikon_cikar.py istemciden çıkarır), yoksa türe göre renkli harf kutusu
function oyGrid(rows) {
  const short = id => (id.split('_').pop() || id).slice(0, 7).toUpperCase();
  return h('div', { class: 'pm-scroll' }, h('div', { class: 'pm-grid' }, rows.map(r => {
    const can = r.silinebilir > 0;
    const tile = h('div', { class: 'pm-slot ' + r.tur + (can ? ' can' : ''), title: r.esya + ' · ' + T(OY_TUR[r.tur] || r.tur) + (can ? '' : ' · ' + T('Takılı ekipman çıkarılamaz.')),
      onclick: can ? () => oyRemove(r) : null }, h('span', { class: 'pm-fb' }, short(r.esya)));
    if (!OY.yok.has(r.esya)) {
      const img = h('img', { src: 'ikonlar/' + encodeURIComponent(r.esya) + '.png', alt: '' });
      img.addEventListener('error', () => { OY.yok.add(r.esya); img.remove(); });
      tile.prepend(img);
    }
    if (r.adet > 1) tile.append(h('span', { class: 'pm-n' }, fmtN(r.adet)));
    if (r.takili) tile.append(h('span', { class: 'pm-eq' }, icon('check')));
    return tile;
  })));
}
function oyAudit() {
  const rows = OY.denetim || [];
  if (!rows.length) return h('p', { class: 'desc', style: { marginTop: '12px' } }, T('Henüz kayıt yok.'));
  return h('div', { class: 'pm-scroll', style: { marginTop: '12px' } }, h('table', { class: 'table' },
    h('thead', null, h('tr', null, [T('Zaman'), T('İşlem'), T('Oyuncu'), T('Eşya'), T('Adet')].map(x => h('th', null, x)))),
    h('tbody', null, rows.map(r => { const [ad, cls] = OY_ISLEM[r.islem] || [r.islem, '']; return h('tr', null,
      h('td', null, r.zaman), h('td', null, badge(T(ad), cls)), h('td', null, r.oyuncu || (r.oyuncular || []).join(', ')),
      h('td', null, h('span', { class: 'mono' }, r.esya)), h('td', null, fmtN(r.adet))); }))));
}
function oyGiveModal(player) {         // player: { id, ad } ya da null (bağlı herkes)
  const online = OY.veri.oyuncular.filter(p => p.cevrimici);
  const picker = lootPicker(T('lootId — ör. ammunition_laser_lcb-10'));
  const amount = h('input', { class: 'input', type: 'number', min: 1, value: 1, style: { width: '120px' } });
  const m = modal({ title: player ? T('Eşya ver: {0}', player.ad) : T('Herkese eşya ver'), wide: true,
    sub: player ? T('Başarılı veriliş herkesin sohbetine duyurulur.')
      : T('Bağlı {0} oyuncunun hepsine verilir. Başarılı veriliş herkesin sohbetine duyurulur.', online.length),
    body: [field(T('Eşya'), picker.el), field(T('Adet'), amount)],
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Ver ve duyur'), async ev => {
      const loot = picker.input.value.trim();
      if (!loot) return toast(T('Bir eşya seçin.'), 'err');
      const b = ev.currentTarget; b.disabled = true;
      const body = { esya: loot, adet: amount.value };
      const r = await act(() => player ? api('/api/oyuncular/ver', Object.assign(body, { oyuncu: player.id })) : api('/api/oyuncular/herkese_ver', body),
        x => player ? T('{0} oyuncusuna {1} x{2} verildi ve duyuruldu.', x.oyuncu, x.esya, fmtN(x.adet))
          : T('{0} oyuncuya {1} x{2} verildi ve duyuruldu.', x.oyuncular.length, x.esya, fmtN(x.adet)));
      b.disabled = false; if (r) { m.close(); oyLoad(true); }
    }, 'primary', 'plus')],
  });
}
function oyRemove(row) {                // çıkarma ayrı ve iki adımlı: adet seç, sonra oyuncu + eşya + adedi adıyla onayla
  const who = { id: OY.env.id, ad: OY.env.oyuncu }, max = row.silinebilir;
  const amount = h('input', { class: 'input', type: 'number', min: 1, max, value: 1, style: { width: '120px' } });
  const m = modal({ title: T('Eşya çıkar'), sub: T('{0} oyuncusundan alınır; geri verilmez. Sohbette duyurulmaz, denetim günlüğüne yazılır.', who.ad),
    body: [h('div', { class: 'mono' }, row.esya), field(T('Çıkarılacak adet'), amount, h('div', { class: 'small muted' }, T('En çok {0} adet', fmtN(max))))],
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Devam'), async () => {
      const n = Math.floor(Number(amount.value));
      if (!(n >= 1 && n <= max)) return toast(T('Adet 1 ile {0} arasında olmalı.', fmtN(max)), 'err');
      m.close();
      const ok = await confirmBox(T('Eşyayı çıkar?'), T('{0} oyuncusundan {1} x{2} çıkarılacak. Bu işlem geri alınamaz.', who.ad, row.esya, fmtN(n)),
        { ok: T('Çıkar'), danger: true });
      if (!ok) return;
      const r = await act(() => api('/api/oyuncular/cikar', { oyuncu: who.id, esya: row.esya, adet: n }),
        x => T('{0} oyuncusundan {1} x{2} çıkarıldı.', x.oyuncu, x.esya, fmtN(x.adet)));
      if (r) oyLoad(true);
    }, 'danger', 'trash')],
  });
}
function liveCard() {
  const r = S.live;
  const head = h('h2', null, icon('zap'), T('Canlı durum'));
  if (!r || !r.var) return h('div', { class: 'card', id: 'canli-card' }, head, h('p', { class: 'desc' }, T('Oyun sunucusunun durum bilgisi bekleniyor…')));
  const d = r.durum, w = d.dunya || {}, g = d.gemi, p = d.pilot, k = d.konum;
  const flags = [d.bagli ? badge(T('İstemci bağlı'), 'ok') : badge(T('İstemci bağlı değil'), ''), r.yas > 10 ? badge(T('Durum {0} sn eski', Math.round(r.yas)), 'warn') : null,
    w.olu ? badge(T('Gemi yok edildi'), 'err') : null, w.savasta ? badge(T('Savaşta'), 'orange') : null, w.guvenli ? badge(T('Güvenli bölgede'), 'info') : null];
  const facts = [[T('Harita'), `${k.harita} (${fmtN(k.x)}, ${fmtN(k.y)})`], [T('Gemi'), (g.ad || '').replace('ship_', '')], [T('Uzaylı'), w.uzayli != null ? fmtN(w.uzayli) : '—'],
    [T('Kutu / cevher'), w.kutu != null ? fmtN(w.kutu) + ' / ' + fmtN(w.cevher) : '—'], [T('Hedef'), w.hedef || '—'], [T('Oynama'), fmtDur(d.oynama_sn)]];
  if (w.kapi) facts.push([T('Kapı'), `${w.kapi.ad || ''}${w.kapi.dalga ? ' · ' + w.kapi.dalga : ''}${w.kapi.evre ? ' · ' + w.kapi.evre : ''}`]);
  if (w.dongu) facts.push([T('Döngü'), T('{0} ms ort. · en çok {1} ms', w.dongu.ort_ms, w.dongu.en_cok_ms) + (w.dongu.yavas ? ' · ' + T('{0} yavaş adım', fmtN(w.dongu.yavas)) : '')]);
  return h('div', { class: 'card', id: 'canli-card' }, h('div', { class: 'row between wrap' }, head, h('div', { class: 'row wrap', style: { gap: '6px' } }, flags)),
    h('div', { class: 'grid g3', style: { marginTop: '12px' } },
      h('div', { class: 'stack', style: { gap: '10px' } }, meter(T('Can'), g.can, g.can_azami, 'hp'), meter(T('Kalkan'), g.kalkan, g.kalkan_azami, 'sh'), meter(T('Kargo'), g.kargo, g.kargo_azami, 'cg')),
      h('div', { class: 'kv one' }, facts.map(([a, b]) => h('div', null, h('span', { class: 'muted' }, a), h('b', null, b)))),
      h('div', null, h('div', { class: 'stats', style: { marginTop: 0, gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' } },
        [[T('Seviye'), p.seviye, ''], [T('Kredi'), p.kredi, 'cr'], [T('Uridyum'), p.uridyum, 'ur'], [T('Onur'), p.onur, 'hn']].map(([a, v, c]) =>
          h('div', { class: 'stat' }, h('div', { class: 'k' }, a), h('div', { class: 'v ' + c }, fmtN(v))))),
        d.etkinlik_adlari && d.etkinlik_adlari.length ? h('div', { class: 'chips', style: { marginTop: '10px' } }, d.etkinlik_adlari.map(n => h('span', { class: 'chip' }, n))) : null)));
}

async function switchSaveMenu(anchor) {
  const r = await act(() => api('/api/kayitlar')); if (!r) return;
  popMenu(anchor, [...r.liste.map(k => ({
    label: `${k.ad} — ${k.pilot} (${lvl(k.seviye)})${k.aktif ? '  ✓' : ''}`, ic: k.aktif ? 'check' : 'save',
    fn: () => act(() => api('/api/kayitlar/aktif', { id: k.id }), T('Etkin kayıt: {0}', k.ad)).then(() => poll()),
  })), '-', { label: T('Yeni kayıt…'), ic: 'plus', fn: () => newSaveModal() }, { label: T('Kayıtları yönet'), ic: 'save', fn: () => go('kayitlar') }]);
}

// ================================================================== ARKADAŞLARINLA OYNA (arkadas.py, /api/arkadas)
const IP_TUR = { yerel: [N('Ev ağı'), 'ok'], radmin: [N('Radmin VPN'), 'info'], tailscale: [N('Tailscale'), 'info'], genel: [N('Genel'), 'orange'],
  baglanti: [N('Yalnız bu ağ'), ''] };
const ARK_DURUM = { baglaniyor: [N('Bağlanıyor'), 'info'], oyunda: [N('Oyunda'), 'ok'], ayriliyor: [N('Ayrılıyor'), 'orange'], bitti: [N('Ayrıldın'), ''],
  hata: [N('Hata'), 'err'] };
const ARK_AKTIF = s => ['baglaniyor', 'oyunda', 'ayriliyor'].includes(s);
const ARK = { sekme: null, adres: null, sifre: '', kayit: null, bilgi: null, veri: null };
const copyText = t => navigator.clipboard.writeText(t).then(() => toast(T('Kopyalandı: {0}', t), 'ok'), () => toast(t, 'info'));
const clock = sec => sec ? new Date(sec * 1000).toLocaleTimeString(LOC(), { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';

async function renderArkadas() {
  const v = await act(() => api('/api/arkadas'));
  if (!v || S.page !== 'arkadas') return;
  ARK.veri = v;
  drawArkadas();
}
function drawArkadas() {
  const v = ARK.veri, d = S.durum;
  if (!ARK.sekme) ARK.sekme = v.misafir.durum !== 'yok' ? 'join' : 'host';
  if (ARK.adres == null) ARK.adres = v.misafir.son_adres || '';
  const tabs = h('div', { class: 'seg' }, [['host', T('Sunucu kur (Host)')], ['join', T('Arkadaşına katıl (Join)')]].map(([k, t]) =>
    h('button', { class: ARK.sekme === k ? 'on info' : '', onclick: () => { ARK.sekme = k; drawArkadas(); } }, t)));
  $('#content').replaceChildren(h('div', { class: 'stack', id: 'arkadas' }, h('div', { class: 'row' }, tabs),
    ...(ARK.sekme === 'host' ? hostView(v) : joinView(v))));
  S.sig.arkMode = arkMode(v, d); S.sig.arkDyn = arkDyn(v);
}
const arkMode = (v, d) => JSON.stringify([ARK.sekme, v.host.acik, v.misafir.durum, d?.oyna, srvState(d), v.kayitlar.map(k => k.id), d?.aktif?.id]);
const arkDyn = v => JSON.stringify([v.host.misafirler, v.misafir.adimlar, v.misafir.son_esitleme, v.misafir.baglanti, v.misafir.not, v.host.genel_ip]);
async function arkTick() {
  if (S.arkBusy) return;
  S.arkBusy = true;
  let v;
  try { v = await api('/api/arkadas'); } catch (e) { return; } finally { S.arkBusy = false; }
  if (S.page !== 'arkadas') return;
  ARK.veri = v;
  if (arkMode(v, S.durum) !== S.sig.arkMode) return drawArkadas();
  if (arkDyn(v) === S.sig.arkDyn) return;
  S.sig.arkDyn = arkDyn(v);
  const g = $('#ark-misafirler'); if (g) g.replaceWith(guestsCard(v.host));
  const j = $('#ark-join-durum'); if (j) j.replaceWith(joinStatus(v));
}

function launchSteps(o) {
  const recent = o.bitti && (Date.now() / 1000 - o.bitti < 45);
  if (!o.adimlar.length || !(o.calisiyor || o.hata || recent)) return null;
  return stepList(o.adimlar);
}
const stepList = list => h('div', { class: 'steps' }, list.map(s => h('div', { class: 'step ' + s.durum },
  h('span', { class: 'ic' }, s.durum === 'calisiyor' ? h('span', { class: 'spin' }) : icon(s.durum === 'hata' ? 'x' : 'check')),
  h('span', null, s.metin), h('span', { class: 'dim small', style: { marginLeft: 'auto' } }, s.zaman))));

// ---- Host
function hostView(v) {
  const hs = v.host, d = S.durum, st = srvState(d), busy = d?.oyna?.calisiyor, running = st.istemci === 'acik';
  const single = st.oyun === 'acik' && !hs.acik, guest = ARK_AKTIF(v.misafir.durum);
  const left = h('div', null, h('div', { class: 'slot-name' }, T('Arkadaş sunucusu')),
    h('div', { class: 'pilot' }, hs.acik ? T('Sunucun açık') : T('Sunucu kapalı'),
      hs.acik ? badge(T('{0} / {1} misafir', hs.misafirler.length, hs.en_cok), 'ok') : null, hs.sifre ? badge(T('Şifreli'), 'info') : null),
    h('div', { class: 'muted' }, hs.acik ? T('Arkadaşların aşağıdaki adreslerden biriyle katılır. Sen kendi kaydınla oynarsın.')
      : T('Sunucu kurunca kendi kaydınla oyuna girersin; arkadaşların kendi kayıtlarıyla katılır.')),
    d?.aktif ? h('div', { class: 'meta' }, h('span', null, T('Kayıt:') + ' ', h('b', null, d.aktif.ad)), h('span', null, T('Pilot') + ' ', h('b', null, d.aktif.pilot))) : null);
  let main; const sub = [];
  if (busy) main = h('button', { class: 'play-btn busy', disabled: true }, h('span', { class: 'spin', style: { borderTopColor: '#021120' } }), T('BAŞLATILIYOR'));
  else if (hs.acik && running) main = h('button', { class: 'play-btn running', disabled: true }, icon('check'), T('OYUN AÇIK'));
  else main = h('button', { class: 'play-btn', disabled: !d?.aktif || guest || (running && !hs.acik), onclick: () => act(() => api('/api/arkadas/host', {})) },
    icon(hs.acik ? 'play' : 'users'), hs.acik ? T('OYNA') : T('SUNUCU KUR'));
  if (hs.acik) sub.push(btn(T('Sunucuyu kapat'), async () => {
    if (hs.misafirler.length && !await confirmBox(T('Sunucu kapatılsın mı?'), T('Bağlı misafirler oyundan düşer; kayıtları kendi bilgisayarlarında son hâliyle kalır.'),
      { ok: T('Kapat'), danger: true })) return;
    act(() => api('/api/sunucu/durdur', {}), T('Sunucular durduruldu.'));
  }, 'danger sm', 'stop', { disabled: running || busy }));
  else sub.push(btn(T('Yalnız sunucuyu başlat'), () => act(() => api('/api/arkadas/host', { sadece_sunucu: true })), 'ghost sm', 'server',
    { disabled: !d?.aktif || guest || busy }));
  const hint = guest ? T('Şu an arkadaşının sunucusundasın: önce oradan ayrıl.') : single ? T('Tek oyunculu sunucun açık: Sunucu kur onu arkadaş sunucusu olarak yeniden başlatır.')
    : hs.acik ? (S.panelCfg?.istemci_kapaninca === 'acik' ? T('Oyunu kapatınca sunucu açık kalır.') : T('Oyunu kapatınca sunucu da kapanır (Sunucu > Davranış).')) : null;
  const hero = h('div', { class: 'hero' }, left, h('div', { class: 'play-col' }, main, h('div', { class: 'play-sub' }, sub), hint ? h('div', { class: 'small muted' }, hint) : null));
  const steps = d?.oyna ? launchSteps(d.oyna) : null;

  // ayarlar
  const pw = h('input', { class: 'input', value: hs.sifre, placeholder: T('Şifresiz'), maxlength: 64 });
  const max = h('select', { class: 'input', style: { width: '110px' } }, Array.from({ length: 16 }, (_, i) => i + 1).map(n => h('option', { value: n, selected: n === hs.en_cok }, n)));
  const save = () => act(() => api('/api/arkadas/ayarlar', { sifre: pw.value, en_cok: +max.value }), T('Kaydedildi.'))
    .then(r => { if (r) { ARK.veri = r; } });
  pw.addEventListener('change', save); max.addEventListener('change', save);
  const setCard = h('div', { class: 'card' }, h('h2', null, icon('sliders'), T('Sunucu ayarları')),
    h('div', { class: 'grid g2' }, field(T('Katılma şifresi'), pw), field(T('En çok misafir'), max)),
    h('p', { class: 'desc', style: { marginTop: '10px' } }, hs.acik ? T('Değişiklikler sunucu yeniden başlayınca geçerli olur.')
      : T('Şifre, adresini bilen herkesin katılmasını engeller. Misafirler bu şifreyi Arkadaşına katıl bölümünde yazar.')));

  // adresler
  const ipRow = (ip, tur) => h('div', { class: 'row between' }, h('b', { class: 'mono' }, ip), h('span', { class: 'row', style: { gap: '6px' } },
    badge(T((IP_TUR[tur] || IP_TUR.genel)[0]), (IP_TUR[tur] || IP_TUR.genel)[1]), btn('', () => copyText(ip), 'ghost sm', 'copy', { title: T('Kopyala') })));
  const addrCard = h('div', { class: 'card' }, h('h2', null, icon('globe'), T('Arkadaşlarına vereceğin adres')),
    h('div', { class: 'stack', style: { gap: '8px' } }, hs.ipler.map(x => ipRow(x.ip, x.tur)),
      hs.genel_ip ? ipRow(hs.genel_ip, 'genel') : h('div', { class: 'row' }, btn(T('Genel IP\'mi bul'), async () => {
        const r = await act(() => api('/api/arkadas/genel_ip', {})); if (r) { ARK.veri.host.genel_ip = r.ip; drawArkadas(); }
      }, 'sm', 'search'), h('span', { class: 'small dim' }, T('api.ipify.org\'a sorulur.')))),
    h('p', { class: 'desc', style: { marginTop: '12px' } }, T('Aynı evdeyseniz (aynı modem) ev ağı adresini ver. İnternet üzerinden bağlanacaklara genel IP\'ni (port yönlendirmesiyle) ya da sanal ağ (Radmin VPN, ZeroTier, Tailscale) adresini ver.')));

  // portlar
  const portCard = h('div', { class: 'card' }, h('h2', null, icon('shield'), T('Açılması gereken portlar')),
    h('table', { class: 'table' }, h('thead', null, h('tr', null, h('th', null, T('Protokol')), h('th', null, T('Port')), h('th', null, T('Ne için')))),
      h('tbody', null, [['TCP', hs.oyun_portu, T('Oyun ve hesap gönderimi')], ['TCP', hs.sohbet_portu, T('Sohbet')]].map(([a, b, c]) =>
        h('tr', null, h('td', null, h('b', null, a)), h('td', { class: 'mono' }, b), h('td', null, c))))),
    h('p', { class: 'desc', style: { marginTop: '10px' } }, T('UDP portu gerekmez. Web girişi (80, 8090) yalnız bu bilgisayarda kalır; onları açma.')),
    h('div', { class: 'stack', style: { gap: '8px', marginTop: '6px' } },
      S.durum?.panel?.platform && S.durum.panel.platform !== 'win32'
        ? h('div', { class: 'note' }, h('b', null, '1. '), T("Güvenlik duvarı: macOS sorarsa Python'a gelen bağlantı izni ver. Linux'ta güvenlik duvarı (ör. ufw) açıksa:"),
          h('div', { class: 'cmd', style: { marginTop: '6px' } }, `sudo ufw allow ${hs.oyun_portu},${hs.sohbet_portu}/tcp`))
        : h('div', { class: 'note' }, h('b', null, '1. '), T('Windows Güvenlik Duvarı: sunucu ilk açıldığında Python için çıkan pencerede erişime izin ver (Özel ağlar). Pencere çıkmadıysa yönetici olarak açılmış bir komut isteminde:'),
          h('div', { class: 'cmd', style: { marginTop: '6px' } }, `netsh advfirewall firewall add rule name="DarkOrbit" dir=in action=allow protocol=TCP localport=${hs.oyun_portu},${hs.sohbet_portu}`)),
      h('div', { class: 'note' }, h('b', null, '2. '), T('Aynı ev ağında başka bir şey gerekmez.')),
      h('div', { class: 'note' }, h('b', null, '3. '), T('İnternet üzerinden: modeminin arayüzünde TCP {0} ve {1} portlarını bu bilgisayarın ev ağı adresine yönlendir (port yönlendirme / Sanal sunucu / NAT).', hs.oyun_portu, hs.sohbet_portu)),
      h('div', { class: 'note' }, h('b', null, '4. '), T('İnternet sağlayıcın CGNAT kullanıyorsa (modemdeki WAN adresi genel IP\'nden farklıysa) yönlendirme işe yaramaz: Radmin VPN, ZeroTier ya da Tailscale gibi bir sanal ağ kurun ve o ağdaki adresi verin.'))));

  // ortak evren
  const share = h('div', { class: 'card' }, h('h2', null, icon('info'), T('Ortak evren')),
    h('div', { class: 'check-list' }, [N('Firma, savaş ve Blacklight haritaları (1-1 … 5-4, BL) ortak: uzaylılar, kutular ve cevherler paylaşılır, birbirinizi görürsünüz.'),
      N('Kapı, mod ve etkinlik haritaları herkesin kendi kopyası.'), N('Sohbet ortak; posta, klan ve müzayede her oyuncunun kendisinin.'),
      N('Oyun ayarların (çarpanlar, etkinlikler) misafirlerine de uygulanır.'),
      N('Misafirlerin kaydı bu bilgisayara yazılmaz, Kayıtlar sayfasında görünmez: ilerlemeleri kendi bilgisayarlarına kaydedilir.'),
      N('Oyuncular birbirine saldıramaz (PvP yok).')].map(t => h('div', null, icon('check'), h('span', null, T(t))))));
  return [hero, steps ? h('div', { class: 'card' }, h('h2', null, icon('zap'), T('Sunucu başlatma')), steps) : null, guestsCard(hs),
    h('div', { class: 'grid g2' }, addrCard, setCard), h('div', { class: 'grid g2' }, portCard, share)].filter(Boolean);
}
function guestsCard(hs) {
  if (!hs.acik) return h('div', { id: 'ark-misafirler' });
  const now = Date.now() / 1000;
  return h('div', { class: 'card', id: 'ark-misafirler' }, h('h2', null, icon('users'), T('Misafirler')),
    hs.misafirler.length ? h('table', { class: 'table' },
      h('thead', null, h('tr', null, [T('Pilot'), T('Seviye'), T('Harita'), T('Adres'), T('Durum'), T('Süre'), ''].map(x => h('th', null, x)))),
      h('tbody', null, hs.misafirler.map(g => h('tr', null, h('td', null, h('b', null, g.ad)), h('td', null, g.seviye), h('td', null, g.harita || '—'),
        h('td', { class: 'mono' }, g.ip), h('td', null, g.bagli ? badge(T('Oyunda'), 'ok') : badge(T('Bağlı değil'), '')), h('td', null, fmtDur(now - g.giris)),
        h('td', { class: 'num' }, btn(T('Çıkar'), async () => {
          if (await confirmBox(T('{0} çıkarılsın mı?', g.ad), T('Bağlantısı kapanır. Kaydı kendi bilgisayarında son hâliyle kalır.'), { ok: T('Çıkar'), danger: true }))
            act(() => api('/api/arkadas/at', { oturum: g.oturum }), T('{0} çıkarıldı.', g.ad));
        }, 'ghost sm', 'x')))))) :
      h('p', { class: 'desc' }, T('Henüz misafir yok. Arkadaşların Arkadaşlarınla Oyna > Arkadaşına katıl bölümünde adresini yazıp bağlanır.')));
}

// ---- Join
function joinView(v) {
  const m = v.misafir;
  if (ARK_AKTIF(m.durum)) return [joinStatus(v), joinInfo()];
  const d = S.durum, st = srvState(d);
  const adres = h('input', { class: 'input', value: ARK.adres, placeholder: '192.168.1.20', oninput: e => { ARK.adres = e.target.value; } });
  const pw = h('input', { class: 'input', type: 'password', value: ARK.sifre, placeholder: T('Şifre yoksa boş bırak'), oninput: e => { ARK.sifre = e.target.value; } });
  const slot = h('select', { class: 'input', onchange: e => { ARK.kayit = e.target.value; } },
    v.kayitlar.map(k => h('option', { value: k.id, selected: k.id === (ARK.kayit || v.aktif) }, `${k.ad} — ${k.pilot} (${lvl(k.seviye)})`)));
  const info = h('div', { id: 'ark-bilgi' }, ARK.bilgi ? serverInfo(ARK.bilgi, v) : null);
  const test = btn(T('Bağlantıyı dene'), async ev => {
    const b = ev.currentTarget; b.disabled = true;
    const r = await act(() => api('/api/arkadas/dene', { adres: adres.value }));
    b.disabled = false; ARK.bilgi = r || null;
    info.replaceChildren(r ? serverInfo(r, v) : '');
  }, 'sm', 'search');
  const blocked = st.oyun === 'acik' ? T('Kendi sunucun açık: katılmak için önce onu durdur.') : st.istemci === 'acik' ? T('Oyun açık: önce kapat.')
    : !v.kayitlar.length ? T('Önce Kayıtlar sayfasından bir kayıt oluştur.') : null;
  const join = h('button', { class: 'play-btn', disabled: !!blocked, onclick: () =>
    act(() => api('/api/arkadas/katil', { adres: adres.value, sifre: pw.value, kayit: slot.value })).then(r => { if (r) renderArkadas(); }) }, icon('play'), T('KATIL'));
  const left = h('div', { class: 'stack', style: { gap: '12px' } }, h('div', { class: 'slot-name' }, T('Arkadaşının sunucusuna katıl')),
    field(T('Arkadaşının adresi (IP ya da alan adı)'), h('div', { class: 'row' }, adres, test)), h('div', { class: 'grid g2' }, field(T('Şifre'), pw), field(T('Kullanılacak kayıt'), slot)), info);
  const hero = h('div', { class: 'hero' }, left, h('div', { class: 'play-col' }, join,
    h('div', { class: 'small muted' }, blocked || T('Kaydın yedeklenir, arkadaşının sunucusuna gönderilir ve oyun açılır.'))));
  const last = ['bitti', 'hata'].includes(m.durum) ? h('div', { class: 'card' }, h('h2', null, icon(m.durum === 'hata' ? 'alert' : 'check'),
    m.durum === 'hata' ? T('Katılma başarısız') : T('Son oturum')), stepList(m.adimlar),
    m.not ? h('div', { class: 'alert uyari', style: { marginTop: '10px' } }, icon('alert'), h('div', null, m.not)) : null,
    m.son_esitleme ? h('p', { class: 'desc', style: { marginTop: '10px' } }, T('Kaydın son eşitlemesi: {0}', clock(m.son_esitleme))) : null) : null;
  return [hero, last, joinInfo()].filter(Boolean);
}
function serverInfo(r, v) {
  const sameClient = !r.istemci || r.istemci === v.istemci_surumu;
  return h('div', { class: 'stack', style: { gap: '10px' } },
    h('div', { class: 'kv' }, [[T('Sunucu'), r.adres], [T('Sunucunun pilotu'), r.pilot || '—'], [T('Oyuncular'), (r.oyuncular || []).join(', ') || '—'],
      [T('Misafir'), `${r.misafir} / ${r.en_cok}`], [T('Şifre'), r.sifre ? T('Gerekli') : T('Yok')], [T('Oyun sürümü'), r.istemci || '—']].map(([a, b]) =>
      h('div', null, h('span', null, a), h('b', null, b)))),
    h('div', { class: 'wz-summary' }, checkRow(r.uyumlu, r.uyumlu ? T('Panel sürümleri uyumlu') : T('Panel sürümleri farklı: ikiniz de paneli güncelleyin')),
      checkRow(sameClient, sameClient ? T('Oyun sürümü aynı') : T('Oyun sürümü farklı (seninki {0})', v.istemci_surumu)),
      checkRow(r.yer, r.yer ? T('Sunucuda yer var') : T('Sunucu dolu'))));
}
function joinStatus(v) {
  const m = v.misafir, [t, c] = ARK_DURUM[m.durum] || [m.durum, ''];
  const slot = v.kayitlar.find(k => k.id === m.kayit);
  return h('div', { class: 'card', id: 'ark-join-durum' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('users'), T('Arkadaşının sunucusu')), badge(T(t), c)),
    h('div', { class: 'kv', style: { margin: '12px 0' } }, [[T('Adres'), m.adres], [T('Sunucunun pilotu'), m.sunucu?.pilot || '—'],
      [T('Kayıt'), slot ? `${slot.ad} — ${slot.pilot}` : m.kayit], [T('Son eşitleme'), clock(m.son_esitleme)],
      [T('Bağlantı'), m.baglanti ? T('İyi') : T('Kesik, yeniden deneniyor…')]].map(([a, b]) => h('div', null, h('span', null, a), h('b', null, b)))),
    stepList(m.adimlar),
    m.not ? h('div', { class: 'alert uyari', style: { marginTop: '10px' } }, icon('alert'), h('div', null, m.not)) : null,
    h('div', { class: 'row', style: { marginTop: '14px' } }, btn(T('Ayrıl'), async () => {
      if (await confirmBox(T('Arkadaşının sunucusundan ayrılınsın mı?'), T('Oyun kapanır, kaydının son hâli bu bilgisayara yazılır.'), { ok: T('Ayrıl'), danger: true }))
        act(() => api('/api/arkadas/ayril', {})).then(() => arkTick());
    }, 'danger', 'power', { disabled: m.durum === 'ayriliyor' }), h('span', { class: 'small muted' }, T('Oyunu kapatınca da ayrılırsın.'))));
}
const joinInfo = () => h('div', { class: 'card' }, h('h2', null, icon('info'), T('Kaydın nerede?')),
  h('div', { class: 'check-list' }, [N('Katılmadan önce kaydın yedeklenir (Kayıtlar > Yedekler).'),
    N('Oyun sürerken ilerlemen birkaç saniyede bir bu bilgisayardaki kaydına yazılır; ayrılınca son hâli kaydedilir.'),
    N('Arkadaşının bilgisayarına kaydın yazılmaz, onun Kayıtlar sayfasında görünmez.'),
    N('Arkadaşının oyun ayarları (çarpanlar, etkinlikler) onun sunucusunda geçerlidir.'),
    N('Arkadaşının sunucusu: TCP 8081 (oyun) ve 7771 (sohbet) portları ona açık olmalı.')].map(t => h('div', null, icon('check'), h('span', null, T(t))))));

// ================================================================== KAYITLAR
async function renderKayitlar() {
  const r = await act(() => api('/api/kayitlar')); if (!r || S.page !== 'kayitlar') return;
  const tools = h('div', { class: 'row wrap' },
    btn(T('Yeni kayıt'), () => newSaveModal(), 'primary', 'plus'),
    btn(T('İçe aktar…'), () => act(() => api('/api/kayitlar/iceri', {}), x => x.iptal ? T('İptal edildi.') : T('Kayıt içe aktarıldı.')).then(() => renderKayitlar()), '', 'upload'),
    h('span', { class: 'spacer' }),
    btn(T('Kayıt klasörü'), () => act(() => api('/api/klasor_ac', { ne: 'kayitlar' })), 'ghost', 'folder'));
  const cards = r.liste.map(k => saveCard(k));
  const trash = r.silinenler.length ? [h('div', { class: 'section-title' }, T('Silinenler ({0})', r.silinenler.length)),
    h('div', { class: 'card' }, h('p', { class: 'desc' }, T('Silinen kayıtlar burada bekler; geri alabilir ya da kalıcı olarak silebilirsin.')),
      h('table', { class: 'table' }, h('thead', null, h('tr', null, h('th', null, T('Kayıt')), h('th', null, T('Pilot')), h('th', null, T('Silinme')), h('th'))),
        h('tbody', null, r.silinenler.map(x => h('tr', null, h('td', null, x.ad), h('td', null, `${x.pilot} · ${lvl(x.seviye)}`),
          h('td', { class: 'muted' }, fmtWhen(x.silinme)),
          h('td', { class: 'num' }, h('div', { class: 'actions', style: { justifyContent: 'flex-end' } },
            btn(T('Geri al'), () => act(() => api('/api/kayitlar/geri_al', { dosya: x.dosya }), T('Kayıt geri alındı.')).then(renderKayitlar), 'sm', 'undo'),
            btn(T('Kalıcı sil'), async () => {
              if (await confirmBox(T('Kalıcı olarak silinsin mi?'), T('"{0}" kaydı ve yedekleri diskten silinir. Bu geri alınamaz.', x.ad), { ok: T('Kalıcı sil'), danger: true }))
                act(() => api('/api/kayitlar/cop_bosalt', { dosya: x.dosya }), T('Kalıcı olarak silindi.')).then(renderKayitlar);
            }, 'danger sm', 'trash'))))))),
      r.silinenler.length > 1 ? h('div', { class: 'row', style: { marginTop: '12px', justifyContent: 'flex-end' } },
        btn(T('Çöp kutusunu boşalt'), async () => {
          if (await confirmBox(T('Çöp kutusu boşaltılsın mı?'), T('{0} kayıt kalıcı olarak silinir.', r.silinenler.length), { ok: T('Boşalt'), danger: true }))
            act(() => api('/api/kayitlar/cop_bosalt', {}), T('Çöp kutusu boşaltıldı.')).then(renderKayitlar);
        }, 'danger sm', 'trash')) : null)] : [];
  $('#content').replaceChildren(h('div', { class: 'stack' }, tools,
    cards.length ? h('div', { class: 'grid gauto' }, cards) :
      h('div', { class: 'card empty' }, icon('save'), h('h3', null, T('Henüz kayıt yok')), h('div', null, T('Yeni bir kayıt oluştur ya da bir yedeği içe aktar.'))),
    ...trash));
}

function saveCard(k) {
  const more = ev => { const c = S.durum?.coklu, extra = c && c.ayar && c.kayit_sayisi > 1 && (c.kayitlar || []).find(x => x.id === k.id);
    const extraWhy = extra ? (extra.ek || k.id === c.ana ? T('Kayıt kullanımda') : extraBlock(S.durum, extra)) : null;
    popMenu(ev.currentTarget, [
    extra ? { label: extraWhy ? T('Ek istemcide aç ({0})', extraWhy) : T('Ek istemcide aç'), ic: 'play', disabled: !!extraWhy,
      fn: () => openExtra(k.id, k.pilot).then(() => S.page === 'kayitlar' && renderKayitlar()) } : null,
    extra ? '-' : null,
    { label: T('Yeniden adlandır'), ic: 'edit', fn: async () => { const v = await promptBox(T('Kaydı yeniden adlandır'), T('Kayıt adı'), k.ad); if (v != null) act(() => api('/api/kayitlar/adlandir', { id: k.id, ad: v }), T('Ad değişti.')).then(renderKayitlar); } },
    { label: T('Not ekle / düzenle'), ic: 'note', fn: async () => { const v = await promptBox(T('Kayıt notu'), T('Not'), k.not_, { multiline: true }); if (v != null) act(() => api('/api/kayitlar/not', { id: k.id, not: v })).then(renderKayitlar); } },
    { label: T('Kopyala'), ic: 'copy', fn: async () => { const v = await promptBox(T('Kaydı kopyala'), T('Yeni kaydın adı'), T('{0} (kopya)', k.ad)); if (v != null) act(() => api('/api/kayitlar/kopyala', { id: k.id, ad: v }), T('Kopyalandı.')).then(renderKayitlar); } },
    { label: T('Dışa aktar (.zip)…'), ic: 'download', fn: () => act(() => api('/api/kayitlar/disari', { id: k.id, yedeklerle: true }), x => x.iptal ? T('İptal edildi.') : T('Dışa aktarıldı: {0}', x.yol)) },
    { label: T('Klasörü aç'), ic: 'folder', fn: () => act(() => api('/api/klasor_ac', { ne: 'kayit', id: k.id })) },
    '-',
    { label: T('Sil'), ic: 'trash', danger: true, disabled: k.kullanimda, fn: async () => {
      if (await confirmBox(T('Kayıt silinsin mi?'), T('"{0}" ({1}) çöp kutusuna taşınır; Kayıtlar sayfasının altından geri alabilirsin.', k.ad, k.pilot), { ok: T('Sil'), danger: true }))
        act(() => api('/api/kayitlar/sil', { id: k.id }), T('Çöp kutusuna taşındı.')).then(renderKayitlar);
    } },
  ].filter(Boolean)); };
  return h('div', { class: 'card save-card' + (k.aktif ? ' active' : '') },
    h('div', { class: 'head' }, h('div', { style: { minWidth: 0, flex: 1 } },
      h('div', { class: 'row', style: { gap: '8px' } }, h('span', { class: 'title' }, k.ad), k.aktif ? badge(T('ETKİN'), 'info') : null,
        k.kullanimda ? badge(T('OYUNDA'), 'ok') : null, k.bozuk ? badge(T('BOZUK'), 'err') : null),
      h('div', { class: 'sub' }, k.pilot, ' · ', badge(k.firma || '?', firmaCls(k.firma)), ' · ' + T('Seviye') + ' ', k.seviye ?? '?')),
      btn('', more, 'ghost icon', 'more', { title: T('Diğer') })),
    h('div', { class: 'kv' },
      h('div', null, T('Kredi'), h('b', null, fmtN(k.kredi))), h('div', null, T('Uridyum'), h('b', null, fmtN(k.uridyum))),
      h('div', null, T('Gemi'), h('b', null, k.gemi)), h('div', null, T('Harita'), h('b', null, k.harita)),
      h('div', null, T('Oynama'), h('b', null, fmtDur(k.oynama_sn))), h('div', null, T('Son oynama'), h('b', null, fmtWhen(k.son_oynama || k.son_kayit))),
      h('div', null, T('Yedek'), h('b', null, k.yedek_sayisi)), h('div', null, T('Boyut'), h('b', null, fmtBytes(k.boyut)))),
    k.not_ ? h('div', { class: 'note' }, k.not_) : null,
    h('div', { class: 'actions' },
      k.aktif ? btn(T('Oyna'), () => { go('oyna'); act(() => api('/api/oyna', {})); }, 'orange sm', 'play')
        : btn(T('Etkin yap'), () => act(() => api('/api/kayitlar/aktif', { id: k.id }), T('Etkin kayıt: {0}', k.ad)).then(renderKayitlar), 'primary sm', 'check'),
      btn(T('Yedekler'), () => backupsModal(k.id), 'sm', 'clock'),
      btn(T('Düzenle'), () => editModal(k.id), 'sm', 'edit', { disabled: k.kullanimda, title: k.kullanimda ? T('Oyun açıkken düzenlenemez') : '' })));
}

// ---- yeni pilot formu (Yeni kayıt penceresi ve kurulum sihirbazı)
const FIRMS = [[1, 'MMO', 'Mars Mining Operations', 'var(--mmo)', '1-1'], [2, 'EIC', 'Earth Industries Corp.', 'var(--eic)', '2-1'],
  [3, 'VRU', 'Venus Resources Unlimited', 'var(--vru)', '3-1']];
function pilotForm({ start = true } = {}) {
  const st = { firma: 2 };
  const ad = h('input', { class: 'input', placeholder: T('ör. Ana kayıt, Hızlı deneme…') });
  const pilot = h('input', { class: 'input', placeholder: T('3-20 karakter'), maxlength: 20 });
  // başlangıç değerleri (isteğe bağlı; boş: şablondaki): kredi, uridyum, seviye (EP'si seviyenin eşiği), onur, cephane
  const num = (min, max) => h('input', { class: 'input', type: 'number', min, max, step: 1, placeholder: T('şablondaki') });
  const kredi = num(0), uri = num(0), seviye = num(1, 50), onur = num(0), lazer = num(0), roket = num(0);
  const ilerlemeli = h('input', { type: 'checkbox' });
  const cards = FIRMS.map(([id, k, n, c, m]) => {
    const el = h('div', { class: 'radio-card' + (id === st.firma ? ' on' : ''), style: { '--c': c }, onclick: () => {
      st.firma = id; el.parentNode.querySelectorAll('.radio-card').forEach(x => x.classList.remove('on')); el.classList.add('on');
    } }, h('b', null, k), h('span', null, n), h('span', null, T('Başlangıç: {0}', m)));
    return el;
  });
  const el = [field(T('Pilot adı (oyunda görünür)'), pilot), field(T('Firma'), h('div', { class: 'radio-cards' }, cards)),
    field(T('Kayıt adı (isteğe bağlı)'), ad),
    start ? h('div', { class: 'grid g2' }, field(T('Başlangıç kredisi (isteğe bağlı)'), kredi), field(T('Başlangıç uridyumu (isteğe bağlı)'), uri),
      field(T('Başlangıç seviyesi (1-50, isteğe bağlı)'), seviye), field(T('Başlangıç onuru (isteğe bağlı)'), onur),
      field(T('LCB-10 lazer cephanesi (isteğe bağlı)'), lazer), field(T('R-310 roketi (isteğe bağlı)'), roket)) : null,
    h('label', { class: 'row small', title: T('Season Pass ilk sezondan (Mobius) başlar; her sezon bitince bir sonraki açılır, en yeniye dek. Sonradan eklenen sezonlar da sırası gelince açılır. Kapalıysa hep en yeni sezon.') },
      h('span', { class: 'switch' }, ilerlemeli, h('span')), T('Sezonları ilk sezondan sırayla aç'))];
  const v = x => start ? x.value : '';
  return { el, pilot, values: () => ({ ad: ad.value.trim() || pilot.value.trim(), pilot: pilot.value.trim(), firma: st.firma,
    kredi: v(kredi), uridyum: v(uri), seviye: v(seviye), onur: v(onur), lazer: v(lazer), roket: v(roket), ilerlemeli: ilerlemeli.checked }) };
}

function newSaveModal() {
  const f = pilotForm();
  const aktif = h('input', { type: 'checkbox', checked: true });
  const m = modal({
    title: T('Yeni kayıt'), sub: T('Yeni bir pilotla sıfırdan başlar. Eski kayıtların etkilenmez.'),
    body: [...f.el, h('label', { class: 'row small' }, h('span', { class: 'switch' }, aktif, h('span')), T('Etkin kayıt yap'))],
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Oluştur'), async ev => {
      const b = ev.currentTarget; b.disabled = true;
      const r = await act(() => api('/api/kayitlar/yeni', Object.assign(f.values(), { aktif_yap: aktif.checked })), T('Kayıt oluşturuldu.'));
      b.disabled = false;
      if (r) { m.close(); if (S.page === 'kayitlar') renderKayitlar(); poll(); }
    }, 'primary', 'plus')],
  });
}

async function editModal(id) {
  const v = await act(() => api('/api/kayit_profili?id=' + encodeURIComponent(id))); if (!v) return;
  const f = {};
  const num = (key, label) => { f[key] = h('input', { class: 'input', type: 'number', value: v[key] }); return field(label, f[key]); };
  f.pilot = h('input', { class: 'input', value: v.pilot, maxlength: 20 });
  const onar = h('input', { type: 'checkbox' }), us = h('input', { type: 'checkbox' }), tus = h('input', { type: 'checkbox' });
  // ---- eşya / gemi ver (oyunun ödül yolu; profil_araci.py ver) ve durum sıfırlama
  const give = [], giveList = h('div', { class: 'chips' });
  const lootInp = h('input', { class: 'input', placeholder: T('lootId — ör. ship_goliath, equipment_weapon_laser_lf-4'), list: 'loot-ids' });
  const lootN = h('input', { class: 'input', type: 'number', min: 1, value: 1, style: { width: '90px' } });
  const lootDl = h('datalist', { id: 'loot-ids' });
  api('/api/esya_listesi').then(r => lootDl.replaceChildren(...r.esyalar.map(([k, t]) => h('option', { value: k }, t)))).catch(() => {});
  const drawGive = () => giveList.replaceChildren(...give.map((g, i) => h('span', { class: 'chip' }, g[0], h('b', null, '×' + fmtN(g[1])),
    h('button', { class: 'btn ghost sm icon', type: 'button', onclick: () => { give.splice(i, 1); drawGive(); } }, icon('x')))));
  const addGive = () => { const l = lootInp.value.trim(); if (!l) return; give.push([l, Math.max(1, +lootN.value || 1)]); lootInp.value = ''; lootN.value = 1; drawGive(); lootInp.focus(); };
  lootInp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addGive(); } });
  const RESETS = [['ipuclari', T('İpuçlarını yeniden göster (kapattıkların ve gösterilenler, etkinlik bildirimleri)')],
    ['arayuz', T('Menü çubuklarının ve pencerelerin yerini varsayılana döndür')], ['oyun_ayarlari', T('Oyunun Ayarlar penceresini (grafik, ses, oynanış) varsayılana döndür')],
    ['aktif_gorevler', T('Alınmış görevleri bırak (bitirilenler kalır)')], ['gecmis', T('Seyir defterini ve hesap geçmişini boşalt')]];
  const resetBox = Object.fromEntries(RESETS.map(([k]) => [k, h('input', { type: 'checkbox' })]));
  const m = modal({
    title: T('Kaydı düzenle'), wide: true, sub: T('{0} · {1} · Seviye {2}. Değiştirmeden önce kendiliğinden güvenlik yedeği alınır.', v.pilot, v.firma, v.seviye),
    body: [v.kullanimda ? h('div', { class: 'alert hata' }, icon('alert'), h('div', null, T('Bu kayıt şu an oyunda. Düzenlemek için oyunu ve sunucuyu kapatın.'))) : null,
      field(T('Pilot adı'), f.pilot),
      h('div', { class: 'grid g2' }, num('kredi', T('Kredi')), num('uridyum', T('Uridyum')), num('onur', T('Onur')), num('ep', T('Deneyim (EP) — seviye buna göre'))),
      h('div', { class: 'stack', style: { gap: '10px' } },
        h('label', { class: 'row small' }, h('span', { class: 'switch' }, onar, h('span')), T('Gemiyi onar (can {0} / {1}, kalkan dolar)', fmtN(v.can), fmtN(v.can_azami))),
        h('label', { class: 'row small' }, h('span', { class: 'switch' }, us, h('span')), T('Gemiyi firmanın ana istasyonuna taşı (bir haritada takılı kaldıysan)')),
        h('label', { class: 'row small' }, h('span', { class: 'switch' }, tus, h('span')), T('Tuş atamalarını varsayılana döndür (oyundaki Ayarlar > Reset sunucuya ulaşmıyor)'))),
      field(T('Eşya, gemi, dron, cephane ver (görev ödülü gibi: ekipman boş yuvaya takılır)'),
        h('div', { class: 'row' }, lootInp, lootN, btn(T('Ekle'), addGive, 'sm', 'plus')), lootDl, giveList),
      field(T('Durum sıfırlama'),
        h('div', { class: 'stack', style: { gap: '8px' } }, RESETS.map(([k, t]) => h('label', { class: 'row small' }, h('span', { class: 'switch' }, resetBox[k], h('span')), t))))],
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Kaydet'), async () => {
      if (lootInp.value.trim()) addGive();
      const deg = { pilot: f.pilot.value, kredi: f.kredi.value, uridyum: f.uridyum.value, onur: f.onur.value, ep: f.ep.value, onar: onar.checked, ana_us: us.checked, tuslar: tus.checked,
        ver: give, sifirla: RESETS.map(([k]) => k).filter(k => resetBox[k].checked) };
      const r = await act(() => api('/api/kayitlar/duzenle', { id, degerler: deg }), x => x.degisen.length ? T('Değişti: {0}', x.degisen.join(', ')) : T('Değişiklik yok.'));
      if (r) { m.close(); if (S.page === 'kayitlar') renderKayitlar(); }
    }, 'primary', 'check', { disabled: v.kullanimda })],
  });
}

async function backupsModal(id) {
  let m;
  async function load() {
    const r = await act(() => api('/api/yedekler?id=' + encodeURIComponent(id))); if (!r) return;
    const k = r.kayit, cfg = r.ayarlar;
    const note = h('input', { class: 'input', placeholder: T('Not (isteğe bağlı): ör. Kapı öncesi') });
    const take = btn(T('Şimdi yedek al'), () => act(() => api('/api/yedekler/al', { id, not: note.value }), T('Yedek alındı.')).then(load), 'primary', 'save');
    const tog = h('input', { type: 'checkbox', checked: cfg.yedek_acilista, onchange: e => act(() => api('/api/panel_ayarlari', { degerler: { yedek_acilista: e.target.checked } }), T('Kaydedildi.')) });
    const keep = h('input', { class: 'input num', type: 'number', min: 1, max: 200, value: cfg.yedek_sayisi,
      onchange: e => act(() => api('/api/panel_ayarlari', { degerler: { yedek_sayisi: +e.target.value } }), T('Kaydedildi.')) });
    const iv = h('input', { class: 'input num', type: 'number', min: 0, max: 600, value: cfg.yedek_aralik_dk,
      onchange: e => act(() => api('/api/panel_ayarlari', { degerler: { yedek_aralik_dk: +e.target.value } }), T('Kaydedildi.')) });
    const rows = r.liste.map(b => h('tr', null,
      h('td', null, h('div', null, fmtWhen(b.zaman)), h('div', { class: 'dim small' }, b.zaman)),
      h('td', null, badge(b.tur_ad, b.tur === 'elle' ? 'info' : b.tur === 'once' ? 'orange' : '')),
      h('td', null, `${b.pilot} · ${lvl(b.seviye)}`), h('td', { class: 'num' }, fmtN(b.kredi)), h('td', { class: 'num' }, fmtN(b.uridyum)),
      h('td', { class: 'small muted' }, b.not_ || ''),
      h('td', { class: 'num' }, h('div', { class: 'actions', style: { justifyContent: 'flex-end', flexWrap: 'nowrap' } },
        btn(T('Geri yükle'), async () => {
          if (await confirmBox(T('Yedek geri yüklensin mi?'), T('"{0}" kaydı {1} anına döner. Şimdiki durum önce "Geri yükleme öncesi" yedeği olarak saklanır.', k.ad, b.zaman), { ok: T('Geri yükle') }))
            act(() => api('/api/yedekler/geri_yukle', { id, dosya: b.dosya }), T('Geri yüklendi.')).then(load);
        }, 'sm', 'undo', { disabled: k.kullanimda, title: k.kullanimda ? T('Oyun açıkken geri yüklenemez') : '' }),
        btn('', ev => popMenu(ev.currentTarget, [
          { label: T('Yeni kayıt olarak aç'), ic: 'plus', fn: async () => { const v = await promptBox(T('Yedekten yeni kayıt'), T('Yeni kaydın adı'), `${k.ad} (${b.zaman.slice(0, 10)})`); if (v != null) act(() => api('/api/yedekler/yeni_kayit', { id, dosya: b.dosya, ad: v }), T('Yeni kayıt oluşturuldu.')).then(() => S.page === 'kayitlar' && renderKayitlar()); } },
          { label: T('Not'), ic: 'note', fn: async () => { const v = await promptBox(T('Yedek notu'), T('Not'), b.not_); if (v != null) act(() => api('/api/yedekler/not', { id, dosya: b.dosya, not: v })).then(load); } },
          '-',
          { label: T('Sil'), ic: 'trash', danger: true, fn: async () => { if (await confirmBox(T('Yedek silinsin mi?'), T('{0} yedeği diskten silinir.', b.zaman), { ok: T('Sil'), danger: true })) act(() => api('/api/yedekler/sil', { id, dosya: b.dosya }), T('Yedek silindi.')).then(load); } },
        ]), 'ghost sm icon', 'more')))));
    const body = [
      k.kullanimda ? h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Kayıt oyunda: yedek alabilirsin, geri yükleme için oyunu ve sunucuyu kapat.'))) : null,
      h('div', { class: 'row' }, note, take, btn(T('Klasör'), () => act(() => api('/api/klasor_ac', { ne: 'yedek', id })), 'ghost', 'folder')),
      h('div', { class: 'row wrap small muted', style: { gap: '18px' } },
        h('label', { class: 'row' }, h('span', { class: 'switch' }, tog, h('span')), T("Oyna'da otomatik yedek al")),
        h('label', { class: 'row' }, T('Saklanacak otomatik yedek'), keep),
        h('label', { class: 'row' }, T('Oyun sırasında her'), iv, T('dakikada (0: kapalı)'))),
      rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, [[N('Zaman'), ''], [N('Tür'), ''], [N('Pilot'), ''], [N('Kredi'), 'num'], [N('Uridyum'), 'num'], [N('Not'), ''], ['', '']].map(([x, c]) => h('th', { class: c }, x ? T(x) : '')))),
        h('tbody', null, rows))) : h('div', { class: 'empty' }, icon('clock'), h('div', null, T('Bu kaydın yedeği yok.'))),
      h('div', { class: 'small dim' }, T('Elle alınan yedekler kendiliğinden silinmez. Otomatik yedeklerin en yeni {0} tanesi kalır.', cfg.yedek_sayisi))];
    if (m) { m.box.querySelector('.body').replaceChildren(...body.filter(Boolean)); }
    else m = modal({ title: T('Yedekler — {0}', k.ad), sub: `${k.pilot} · ${k.firma} · ${T('Seviye')} ${k.seviye}`, wide: true, body, foot: [btn(T('Kapat'), () => m.close(), '')],
      onclose: () => { if (S.page === 'kayitlar') renderKayitlar(); } });
  }
  load();
}

// ================================================================== OYUN AYARLARI
const CARPAN_DEGERLERI = [0, 0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4, 5, 6, 7.5, 10, 12.5, 15, 20, 25, 30, 40, 50];
const UYGULAMA = { 'anında': ['an', N('Anında')], 'harita': ['harita', N('Harita değişince')], 'giriş': ['giris', N('Yeniden girişte')], 'başlatma': ['baslatma', N('Sunucu yeniden başlayınca')] };
let saveTimer = null, pending = {};
function queueSave(key, value) {
  pending[key] = value;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const body = pending; pending = {};
    const r = await act(() => api('/api/ayarlar', { degerler: body }));
    if (r) { S.ayar = r; markChanged(); flashSaved(); }
  }, 350);
}
function flashSaved() {
  const el = $('#saved-note'); if (!el) return;
  el.textContent = T('Kaydedildi ✓'); el.style.color = 'var(--ok)';
  clearTimeout(el._t); el._t = setTimeout(() => { el.textContent = T('Değişiklikler kendiliğinden kaydedilir.'); el.style.color = ''; }, 1600);
}
function markChanged() {
  const r = S.ayar; if (!r) return;
  document.querySelectorAll('.set-row[data-key]').forEach(row => {
    const k = row.dataset.key, v = r.degerler[k] ?? r.varsayilan[k];
    row.classList.toggle('changed', v !== r.varsayilan[k]);
  });
  document.querySelectorAll('.set-group').forEach(card => {         // grup başlığında değişen ayar sayısı
    const n = card.querySelectorAll('.set-row.changed').length;
    card.querySelector('.grp-count').textContent = n ? ' · ' + T('{0} değişiklik', n) : '';
  });
  document.querySelectorAll('.set-sub').forEach(sub => {            // "Ayrıntılı ayarla" düğmesinde değişen alt ayar sayısı
    const n = sub.querySelectorAll('.set-row.changed').length;
    document.querySelector(`.set-row[data-key="${sub.dataset.ust}"] .set-toggle .n`).textContent = n ? T('{0} özel', n) : '';
    paintEff(sub.dataset.ust);
  });
  if (S.ayarFiltre && document.querySelector('.set-tools')) S.ayarFiltre(true);
}

async function renderAyarlar() {
  const r = await act(() => api('/api/ayarlar')); if (!r || S.page !== 'ayarlar') return;
  S.ayar = r;
  const val = k => r.degerler[k] ?? r.varsayilan[k];
  const presets = Object.entries(r.hazir).map(([key, p]) => h('button', { class: 'preset', onclick: async () => {
    if (await confirmBox(T('"{0}" uygulansın mı?', p.ad), T('Bütün oyun ayarları bu hazır ayarın değerlerine döner (etkinlik seçimlerin değişmez).'), { ok: T('Uygula') }))
      act(() => api('/api/ayarlar/hazir', { ad: key }), T('"{0}" uygulandı.', p.ad)).then(renderAyarlar);
  } }, h('b', null, p.ad), h('span', null, p.aciklama)));
  const user = Object.entries(r.sablonlar || {}).map(([key, p]) => h('div', { class: 'preset', onclick: async e => {
    if (e.target.closest('.x')) return;
    if (await confirmBox(T('"{0}" uygulansın mı?', p.ad), T('Bütün oyun ayarları bu şablonun değerlerine döner.'), { ok: T('Uygula') }))
      act(() => api('/api/ayarlar/hazir', { ad: key }), T('"{0}" uygulandı.', p.ad)).then(renderAyarlar);
  } }, h('b', null, '★ ', p.ad), h('span', null, T('{0} değişiklik', Object.keys(p.degerler).length)),
    btn('', async () => { if (await confirmBox(T('Şablon silinsin mi?'), T('"{0}" şablonu silinir.', p.ad), { ok: T('Sil'), danger: true })) act(() => api('/api/ayarlar/sablon_sil', { ad: key })).then(renderAyarlar); }, 'ghost sm icon x', 'x', { title: T('Sil') })));
  const copySel = h('select', { class: 'input', style: { maxWidth: '240px' } }, (r.kayitlar || []).map(k => h('option', { value: k.id }, k.ad)));
  const saveCard = r.kayit ? h('div', { class: 'card' }, h('h2', null, icon('save'), T('Bu kaydın ayarları: {0}', r.kayit_adi)),
    h('p', { class: 'desc' }, T('Oyun ayarları ve etkinlik seçimleri her kayda özgüdür; etkin kayıt değişince ayarlar da değişir.')),
    (r.kayitlar || []).length ? h('div', { class: 'row' }, copySel,
      btn(T('Bu kayıttan kopyala'), async () => {
        const src = r.kayitlar.find(k => k.id === copySel.value);
        if (src && await confirmBox(T('Ayarlar kopyalansın mı?'), T('"{0}" kaydının bütün oyun ayarları ve etkinlik seçimleri bu kayda kopyalanır.', src.ad), { ok: T('Kopyala') }))
          act(() => api('/api/ayarlar/kopyala', { kaynak: src.id }), T('Ayarlar kopyalandı.')).then(renderAyarlar);
      }, 'sm', 'copy')) : null) : null;
  const presetCard = h('div', { class: 'card' }, h('h2', null, icon('star'), T('Hazır ayarlar')),
    h('p', { class: 'desc' }, T('Bir ayar kümesini tek tıkla uygula ya da şimdiki ayarlarını şablon olarak sakla.')),
    h('div', { class: 'preset-bar' }, presets, user),
    h('div', { class: 'row', style: { marginTop: '12px' } },
      btn(T('Şimdiki ayarları şablon olarak kaydet'), async () => { const v = await promptBox(T('Şablon olarak kaydet'), T('Şablon adı'), ''); if (v) act(() => api('/api/ayarlar/sablon_kaydet', { ad: v }), T('Şablon kaydedildi.')).then(renderAyarlar); }, 'sm', 'save'),
      h('span', { class: 'spacer' }),
      btn(T('Hepsini varsayılana döndür'), async () => { if (await confirmBox(T('Varsayılana dönülsün mü?'), T('Bütün oyun ayarları varsayılana döner (etkinlik seçimlerin değişmez).'), { ok: T('Döndür') })) act(() => api('/api/ayarlar/sifirla', {}), T('Varsayılana dönüldü.')).then(renderAyarlar); }, 'ghost sm', 'undo')));
  const info = h('div', { class: 'alert bilgi' }, icon('info'), h('div', null,
    h('span', { id: 'saved-note' }, T('Değişiklikler kendiliğinden kaydedilir.')), ' ' + T('Etiketler ne zaman geçerli olduğunu gösterir:') + ' ',
    ...Object.values(UYGULAMA).map(([c, t]) => [h('span', { class: 'tag ' + c }, T(t)), ' ']),
    r.sunucu_acik ? h('div', { style: { marginTop: '4px' } }, T('Sunucu açık: "Anında" ayarlar oyunda hemen değişir.')) : null));
  S.ayarAcik = S.ayarAcik || {};
  const groups = r.gruplar.map(g => {
    const items = r.sema.filter(s => s.grup === g.anahtar && !s.ust);
    if (!items.length) return null;
    return h('div', { class: 'card set-group', 'data-grup': g.anahtar }, h('h2', null, g.ad, h('span', { class: 'muted small grp-count' })),
      items.map(s => {
        const row = settingRow(s, val(s.anahtar), r.varsayilan[s.anahtar]), kids = r.sema.filter(c => c.ust === s.anahtar);
        return kids.length ? [row, subPanel(row, kids, val, r.varsayilan)] : row;
      }));
  }).filter(Boolean);
  // arama, yalnız değişenler, grup kısayolları (seçimler sayfa yenilenince de kalır)
  const q = h('input', { class: 'input', type: 'search', placeholder: T('Ayar ara (ad ya da açıklama)…'), value: S.ayarAra || '' });
  const only = h('input', { type: 'checkbox', checked: !!S.ayarDegisen });
  const none = h('div', { class: 'card muted', hidden: true }, T('Aramaya uyan ayar yok.'));
  // keep: kayıttan sonra (markChanged) yalnız gösterir, görünen satırı gizlemez (varsayılana dönen satır düzenlerken kaybolmasın).
  // Alt ayar üstünün adıyla da aranır; uyan alt ayarın üstü görünür ve bölümü açılır.
  const apply = (keep = false) => {
    S.ayarAra = q.value; S.ayarDegisen = only.checked;
    const words = q.value.toLocaleLowerCase(LOC()).split(/\s+/).filter(Boolean), filt = words.length > 0 || only.checked;
    const hit = (row, extra = '') => { const text = (extra + ' ' + row.textContent).toLocaleLowerCase(LOC());
      return words.every(w => text.includes(w)) && (!only.checked || row.classList.contains('changed')); };
    let shown = 0;
    groups.forEach(card => {
      let n = 0;
      card.querySelectorAll('.set-row[data-key]:not(.sub)').forEach(row => {
        const sub = card.querySelector(`.set-sub[data-ust="${row.dataset.key}"]`);
        let kid = false;
        if (sub) sub.querySelectorAll('.set-row').forEach(c => {
          const ok = !filt || (keep && !c.hidden) || hit(c, row.querySelector('.name').textContent);
          c.hidden = !ok; kid = kid || (filt && ok);
        });
        const ok = (keep && !row.hidden) || hit(row) || kid;
        row.hidden = !ok; n += ok;
        if (sub) setOpen(row, sub, ok && (!!S.ayarAcik[row.dataset.key] || kid));
      });
      card.hidden = !n; shown += n;
    });
    none.hidden = !!shown;
  };
  S.ayarFiltre = apply;
  q.addEventListener('input', () => apply()); only.addEventListener('change', () => apply());
  const jump = h('div', { class: 'chips' }, groups.map(card => h('button', { class: 'chip link', type: 'button',
    onclick: () => { if (card.hidden) { q.value = ''; only.checked = false; apply(); } card.scrollIntoView({ behavior: 'smooth', block: 'start' }); } },
    card.querySelector('h2').firstChild.textContent)));
  const tools = h('div', { class: 'card compact set-tools' },
    h('div', { class: 'row wrap' }, h('span', { class: 'search-box' }, icon('search'), q),
      h('label', { class: 'row', style: { gap: '8px' } }, h('span', { class: 'switch' }, only, h('span')), T('Yalnız değişenler'))),
    h('div', { style: { marginTop: '10px' } }, jump));
  $('#content').replaceChildren(h('div', { class: 'stack' }, saveCard, presetCard, info, tools, none, ...groups));
  apply();
  markChanged();
}

function settingRow(s, v, def) {
  const [tc, tt] = UYGULAMA[s.uygulama] || ['', s.uygulama];
  // alt ayar (s.ust): uygulama etiketi üstünde; yerine etkin çarpan (paintEff). data-v: gösterilen değer (sürgü bırakılmadan da)
  const row = h('div', { class: 'set-row' + (s.ust ? ' sub' : ''), 'data-key': s.anahtar, 'data-v': v });
  const head = h('div', null, h('div', { class: 'name' }, s.ad, s.ust ? h('span', { class: 'eff' }) : h('span', { class: 'tag ' + tc }, T(tt))),
    h('div', { class: 'help' }, s.aciklama));
  let ctl;
  // sürgü önerilen aralıkta (min..max); sayı kutusuna elle sinir'e dek her değer yazılır (ayar.py), aralığın dışı "elle" işaretli
  const top = s.sinir ?? s.max;
  const over = h('span', { class: 'tag elle', title: T('Önerilen aralığın ({0} – {1}) dışında; elle yazılabilen en büyük değer {2}.', fmtMult(s.min ?? 0), fmtMult(s.max ?? 0), fmtMult(top)) }, T('Elle'));
  const markOver = x => { over.hidden = !(x > s.max); };
  if (s.tur === 'carpan') {
    const vals = CARPAN_DEGERLERI.filter(x => x >= s.min && x <= s.max);
    if (!vals.includes(s.max)) vals.push(s.max);
    const near = x => vals.reduce((bi, y, i) => Math.abs(y - x) < Math.abs(vals[bi] - x) ? i : bi, 0);
    const lab = h('span', { class: 'mult' }, '×' + fmtMult(v));
    const range = h('input', { type: 'range', min: 0, max: vals.length - 1, step: 1, value: near(v) });
    const num = h('input', { class: 'input num', type: 'number', min: s.min, max: top, step: 'any', value: v, title: T('En çok {0}', fmtMult(top)) });
    const paint = () => range.style.setProperty('--p', (range.value / (vals.length - 1) * 100) + '%');
    const show = x => { num.value = x; lab.textContent = '×' + fmtMult(x); markOver(x); row.dataset.v = x; paintEff(s.ust || s.anahtar); };
    range.addEventListener('input', () => { show(vals[+range.value]); paint(); });
    range.addEventListener('change', () => queueSave(s.anahtar, vals[+range.value]));
    num.addEventListener('change', () => {
      const x = Math.min(top, Math.max(s.min, parseFloat(String(num.value).replace(',', '.')) || 0));
      show(x); range.value = near(x); paint(); queueSave(s.anahtar, x);
    });
    const reset = btn('', () => { show(def); range.value = near(def); paint(); queueSave(s.anahtar, def); }, 'ghost sm icon', 'undo', { title: T('Varsayılan (×{0})', fmtMult(def)) });
    paint(); markOver(v);
    ctl = h('div', { class: 'ctl' }, h('div', { style: { flex: 1, minWidth: '140px' } }, range), over, lab, num, reset);
  } else if (s.tur === 'sayi') {
    const num = h('input', { class: 'input num', type: 'number', min: s.min, max: top, step: 1, value: v, title: T('En çok {0}', fmtMult(top)) });
    const fix = x => Math.min(top, Math.max(s.min, Math.round(parseFloat(String(x).replace(',', '.')) || 0)));
    num.addEventListener('change', () => { const x = fix(num.value); num.value = x; markOver(x); queueSave(s.anahtar, x); });
    const reset = btn('', () => { num.value = def; markOver(def); queueSave(s.anahtar, def); }, 'ghost sm icon', 'undo', { title: T('Varsayılan ({0})', def) });
    markOver(v);
    ctl = h('div', { class: 'ctl' }, over, num, s.birim ? h('span', { class: 'mult' }, s.birim) : null, reset);
  } else if (s.tur === 'bool') {
    const cb = h('input', { type: 'checkbox', checked: v, onchange: e => queueSave(s.anahtar, e.target.checked) });
    ctl = h('div', { class: 'ctl' }, h('label', { class: 'switch' }, cb, h('span')));
  } else if (s.tur === 'seviye') {
    // seçeneklerin açıklaması ve rengi şemadan (ayar.py: secenek_aciklama, renkler; panel dilinde gelir)
    const say = i => (s.secenek_aciklama || [])[i] || '';
    const desc = h('div', { class: 'level-desc' }, say(v));
    const seg = h('div', { class: 'seg' }, s.secenekler.map((name, i) => h('button', { class: (i === v ? 'on ' : '') + ((s.renkler || [])[i] || ''), onclick: e => {
      seg.querySelectorAll('button').forEach(b => b.classList.remove('on')); e.currentTarget.classList.add('on'); desc.textContent = say(i); queueSave(s.anahtar, i);
    } }, name)));
    ctl = h('div', { class: 'ctl', style: { flexDirection: 'column', alignItems: 'flex-end' } }, seg);
    head.append(desc);
  }
  row.append(head, ctl);
  return row;
}
// alt ayarlar (ayar.py ALTLAR): üstün satırında "Ayrıntılı ayarla" düğmesi, altında açılan bölüm (açıklığı S.ayarAcik'te kalır)
function subPanel(row, kids, val, defs) {
  const key = row.dataset.key;
  const sub = h('div', { class: 'set-sub', 'data-ust': key },
    h('p', { class: 'sub-note' }, T('Her satırın çarpanı yukarıdaki genel çarpanla çarpılır: genel ×2 ve satır ×3 ise ×6.')),
    kids.map(c => settingRow(c, val(c.anahtar), defs[c.anahtar])));
  row.firstChild.append(h('button', { class: 'set-toggle', type: 'button', onclick: () => { S.ayarAcik[key] = sub.hidden; setOpen(row, sub, sub.hidden); } },
    icon('chevR'), T('Ayrıntılı ayarla'), h('span', { class: 'cnt' }, kids.length), h('span', { class: 'n' })));
  setOpen(row, sub, !!S.ayarAcik[key]);
  return sub;
}
function setOpen(row, sub, open) {
  sub.hidden = !open;
  const b = row.querySelector('.set-toggle'); b.classList.toggle('open', open); b.setAttribute('aria-expanded', String(open));
}
function paintEff(ust) {          // alt ayarların etkin çarpanı (genel x alt): genel x1 değilse "toplam ×6"
  const p = document.querySelector(`.set-row[data-key="${ust}"]`), sub = document.querySelector(`.set-sub[data-ust="${ust}"]`);
  if (!p || !sub) return;
  sub.querySelectorAll('.set-row').forEach(c => { c.querySelector('.eff').textContent = +p.dataset.v === 1 ? '' : T('toplam ×{0}', fmtMult(p.dataset.v * c.dataset.v)); });
}
const fmtMult = x => (Math.round(x * 100) / 100).toLocaleString(LOC());

// ================================================================== ETKİNLİKLER
async function renderEtkinlikler(list) {
  const r = list || await act(() => api('/api/etkinlikler')); if (!r || S.page !== 'etkinlikler') return;
  const set = (key, v) => act(() => api('/api/etkinlikler', { degisiklik: { [key]: v } })).then(x => x && renderEtkinlikler(x));
  const bulk = (to, tur) => act(() => api('/api/etkinlikler', { hepsi: to, tur }), T('Güncellendi.')).then(x => x && renderEtkinlikler(x));
  const row = e => {
    const state = e.durum || 'takvim';
    const status = e.etkin ? badge(e.durum === 'acik' && !e.takvimde ? T('Açık (elle)') : T('Açık'), 'ok')
      : e.bastiran ? badge(T('Kapalı (çakışma: {0})', e.bastiran), 'err')
      : badge(e.durum === 'kapali' && e.takvimde ? T('Kapalı (elle)') : T('Kapalı'), e.durum === 'kapali' ? 'err' : '');
    const cal = e.takvimde ? (e.kalan_sn != null ? T('takvimde açık · {0} kaldı', fmtDur(e.kalan_sn)) : T('takvimde açık'))
      : (e.sonraki_gun != null ? T('takvimde {0} gün sonra', e.sonraki_gun) : T('takvimde şu an kapalı'));
    return h('div', { class: 'ev-row' },
      h('div', null, h('div', { class: 'name' }, e.ad, status), h('div', { class: 'help muted small' }, e.aciklama),
        h('div', { class: 'when' }, '📅 ', e.zaman, ' · ', cal),
        e.cakisan && e.cakisan.length ? h('div', { class: 'help muted small' }, T('Birlikte açık olamaz: {0}', e.cakisan.join(', '))) : null),
      h('div', { class: 'seg' }, [['takvim', T('Takvime göre'), 'info'], ['acik', T('Açık'), 'ok'], ['kapali', T('Kapalı'), 'err']].map(([k, t, c]) =>
        h('button', { class: (state === k ? 'on ' : '') + c, onclick: () => set(e.anahtar, k === 'takvim' ? null : k) }, t))));
  };
  const yearly = r.filter(e => e.tur === 'yillik'), weekly = r.filter(e => e.tur === 'haftalik');
  $('#content').replaceChildren(h('div', { class: 'stack' },
    h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Haritadaki etkinlik uzaylıları, kutular ve indirimler oyun açıkken de değişir; istemcideki etkinlik simgeleri ve pencereleri oyuna yeniden girince güncellenir (harita değiştirmek ya da çıkıp girmek yeter).')),
      btn(T('Takvimde gör'), () => go('takvim'), 'sm', 'agenda'), btn(T('Tüm etkinlikleri kapat'), () => bulk('kapali'), 'sm', 'power')),
    h('div', { class: 'card' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('calendar'), T('Yıllık etkinlikler')),
      h('div', { class: 'row wrap' }, btn(T('Hepsi takvime göre'), () => bulk('takvim', 'yillik'), 'sm'), btn(T('Hepsini aç'), () => bulk('acik', 'yillik'), 'sm'), btn(T('Hepsini kapat'), () => bulk('kapali', 'yillik'), 'sm'))),
      h('p', { class: 'desc' }, T('Gerçek tarihe göre açılırlar; istediğin etkinliği istediğin zaman açabilir ya da kapatabilirsin. Birden çok etkinlik aynı anda açık olabilir; birbiriyle çakışanlardan (Battle Pass, harita süsü, kargo kutusu) yalnız biri: elle açtığın, yoksa önce başlayan.')),
      yearly.map(row)),
    h('div', { class: 'card' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('clock'), T('Haftalık etkinlikler')),
      h('div', { class: 'row wrap' }, btn(T('Hepsi takvime göre'), () => bulk('takvim', 'haftalik'), 'sm'), btn(T('Hepsini aç'), () => bulk('acik', 'haftalik'), 'sm'), btn(T('Hepsini kapat'), () => bulk('kapali', 'haftalik'), 'sm'))),
      h('p', { class: 'desc' }, T('Haftanın belli gün ve saatlerinde (yerel saat) açılırlar. "Açık" seçilirse her zaman geçerli olur.')),
      weekly.map(row))));
}

// ================================================================== ETKİNLİK TAKVİMİ (takvim_cizelge.py, /api/takvim)
// Görünümler: saatlik (seçili günün 24 saati, satırlar ve seanslar), günlük (o günün ayrıntılı listesi), haftalık (pazartesiden 7 gün),
// aylık (6 haftalık ızgara). Çubuk: takvime göre dolu, elle açık çizgili, elle kapalı soluk. Zamanlar yerel saat.
const TKV = { gorunum: 'haftalik', gun: null, filtre: { yillik: true, haftalik: true, seans: true }, ara: '', veri: null, kapsam: null };
const TKV_GORUNUM = [['saatlik', N('Saatlik')], ['gunluk', N('Günlük')], ['haftalik', N('Haftalık')], ['aylik', N('Aylık')]];
const TKV_RENK = ['#38c4ff', '#ff8a3d', '#3ddc97', '#ff6b81', '#a29bfe', '#ffc857', '#1dd1a1', '#f368e0', '#54a0ff', '#ff7f50', '#00d2d3', '#c8d6e5'];
const tkvColor = k => { let x = 7; for (const c of k) x = (x * 31 + c.charCodeAt(0)) >>> 0; return TKV_RENK[x % TKV_RENK.length]; };
const dayStart = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const hhmm = ts => new Date(ts * 1000).toLocaleTimeString(LOC(), { hour: '2-digit', minute: '2-digit' });
const dfmt = (ts, o) => new Date(ts * 1000).toLocaleDateString(LOC(), o);
const tkvSpan = (s, e) => {                      // "24 Eki 19:00 – 23:00" ya da "14 Eki 00:00 – 1 Kas 24:00"
  const same = dayStart(new Date(s * 1000)).getTime() === dayStart(new Date((e - 1) * 1000)).getTime();
  const end = new Date(e * 1000), endTxt = end.getHours() || end.getMinutes() ? hhmm(e) : '24:00';
  return dfmt(s, { day: 'numeric', month: 'short' }) + ' ' + hhmm(s) + ' – ' + (same ? endTxt : dfmt(e - 1, { day: 'numeric', month: 'short' }) + ' ' + endTxt);
};
const TUR_AD = { yillik: N('Yıllık'), haftalik: N('Haftalık') };

function tkvRange() {
  const g = dayStart(TKV.gun || new Date());
  if (TKV.gorunum === 'haftalik') { const a = addDays(g, -((g.getDay() + 6) % 7)); return [a, addDays(a, 7)]; }
  if (TKV.gorunum === 'aylik') { const f = new Date(g.getFullYear(), g.getMonth(), 1); const a = addDays(f, -((f.getDay() + 6) % 7)); return [a, addDays(a, 42)]; }
  return [g, addDays(g, 1)];
}
function tkvGo(gorunum, gun) { if (gorunum) TKV.gorunum = gorunum; if (gun) TKV.gun = gun; renderTakvim(); }
function tkvShift(n) {
  const g = dayStart(TKV.gun || new Date());
  tkvGo(null, TKV.gorunum === 'aylik' ? new Date(g.getFullYear(), g.getMonth() + n, 1) : addDays(g, TKV.gorunum === 'haftalik' ? 7 * n : n));
}
function enterTakvim() {
  TKV.gun = TKV.gun || new Date();
  renderTakvim();
  S.timers.push(setInterval(() => { if (document.visibilityState === 'visible' && !document.querySelector('.modal')) renderTakvim(); }, 60000));
}
async function renderTakvim() {
  const [a, b] = tkvRange();
  let r;
  try { r = await api(`/api/takvim?bas=${a.getTime() / 1000}&bit=${b.getTime() / 1000}`); } catch (e) { toast(e.message, 'err'); return; }
  if (S.page !== 'takvim') return;
  TKV.veri = r; TKV.kapsam = [a.getTime() / 1000, b.getTime() / 1000];
  drawTakvim();
}

// görünümde gösterilecek satırlar: süzgeçler; aralıkta açık olan, seansı olan ya da elle açılmış etkinlikler
function tkvRows() {
  const q = TKV.ara.trim().toLocaleLowerCase(LOC());
  return TKV.veri.etkinlikler.filter(e => TKV.filtre[e.tur] && (!q || e.ad.toLocaleLowerCase(LOC()).includes(q)))
    .map(e => Object.assign({}, e, { renk: tkvColor(e.anahtar), seanslar: TKV.filtre.seans ? e.seanslar.filter(s => s.araliklar.length) : [] }))
    .filter(e => e.etkin_araliklar.length || e.araliklar.length || e.seanslar.length);
}
function drawTakvim() {
  const r = TKV.veri, [A, B] = TKV.kapsam, g = TKV.gorunum;
  const title = g === 'aylik' ? dfmt((A + B) / 2, { month: 'long', year: 'numeric' })
    : g === 'haftalik' ? dfmt(A, { day: 'numeric', month: 'short' }) + ' – ' + dfmt(B - 1, { day: 'numeric', month: 'short', year: 'numeric' })
      : dfmt(A, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  const chip = (k, t) => h('button', { class: 'tk-filter' + (TKV.filtre[k] ? ' on' : ''), onclick: () => { TKV.filtre[k] = !TKV.filtre[k]; drawTakvim(); } }, T(t));
  const search = h('input', { class: 'input', style: { width: '170px' }, placeholder: T('Etkinlik ara…'), value: TKV.ara,
    oninput: e => { TKV.ara = e.target.value; clearTimeout(TKV.araT); TKV.araT = setTimeout(() => { drawTakvim(); const s = $('#tk-ara'); if (s) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); } }, 250); } });
  search.id = 'tk-ara';
  const bar = h('div', { class: 'card tk-toolbar' },
    h('div', { class: 'row between wrap' },
      h('div', { class: 'seg' }, TKV_GORUNUM.map(([k, t]) => h('button', { class: g === k ? 'on info' : '', onclick: () => tkvGo(k) }, T(t)))),
      h('div', { class: 'row' }, btn('', () => tkvShift(-1), 'ghost sm icon', 'arrowL', { title: T('Önceki') }),
        btn(T('Bugün'), () => tkvGo(null, new Date()), 'sm'), btn('', () => tkvShift(1), 'ghost sm icon', 'arrowR', { title: T('Sonraki') }),
        h('b', { class: 'tk-title' }, title)),
      h('div', { class: 'row wrap' }, chip('yillik', N('Yıllık')), chip('haftalik', N('Haftalık')), chip('seans', N('Seanslar')), search)),
    h('div', { class: 'tk-legend small muted' }, h('span', null, h('i', { class: 'tk-sw' }), T('takvime göre')),
      h('span', null, h('i', { class: 'tk-sw forced' }), T('elle açık')), h('span', null, h('i', { class: 'tk-sw off' }), T('elle kapalı')),
      h('span', null, h('i', { class: 'tk-sw sub' }), T('seans / doğuş saati')),
      r.hep_acik ? h('span', { class: 'badge info' }, T('Oyun ayarı: seanslar hep açık')) : null));
  const rows = tkvRows();
  const view = g === 'aylik' ? tkvMonth(rows) : g === 'gunluk' ? tkvDay(rows) : tkvGantt(rows);
  $('#content').replaceChildren(h('div', { class: 'stack' }, bar, tkvSummary(r), view));
}

// ---- özet: şu an açık olanlar ve sıradakiler (görünümden bağımsız)
function tkvSummary(r) {
  const now = Date.now() / 1000;
  const on = r.etkinlikler.filter(e => e.etkin);
  const next = r.etkinlikler.filter(e => e.durum !== 'kapali' && e.sonraki && e.sonraki[0] > now + 1).sort((x, y) => x.sonraki[0] - y.sonraki[0]).slice(0, 8);
  const dotc = k => h('i', { class: 'tk-dot', style: { background: tkvColor(k) } });
  return h('div', { class: 'grid g2' },
    h('div', { class: 'card' }, h('h2', null, icon('zap'), T('Şu an açık ({0})', on.length)),
      on.length ? h('div', { class: 'chips' }, on.map(e => h('button', { class: 'chip tk-chip', onclick: () => tkvDetail(e.anahtar) }, dotc(e.anahtar), e.ad,
        e.durum === 'acik' && !e.takvimde ? h('span', { class: 'dim' }, T('elle')) : e.kalan_sn != null ? h('span', { class: 'dim' }, fmtDur(e.kalan_sn)) : null)))
        : h('p', { class: 'desc' }, T('Şu an açık etkinlik yok.'))),
    h('div', { class: 'card' }, h('h2', null, icon('clock'), T('Sıradakiler')),
      next.length ? h('div', { class: 'tk-next' }, next.map(e => h('div', { class: 'row', onclick: () => tkvDetail(e.anahtar) }, dotc(e.anahtar),
        h('span', { class: 'ellipsis', style: { maxWidth: 'none', flex: 1 } }, e.ad), h('span', { class: 'small muted' }, tkvSpan(e.sonraki[0], e.sonraki[1])),
        badge(T('{0} sonra', fmtDur(e.sonraki[0] - now)), 'info'))))
        : h('p', { class: 'desc' }, T('Yakında başlayacak etkinlik yok.'))));
}

// ---- saatlik ve haftalık: zaman çizelgesi (satır başına etkinlik, altında seansları)
function tkvGantt(rows) {
  const [A, B] = TKV.kapsam, now = Date.now() / 1000, week = TKV.gorunum === 'haftalik';
  const pct = t => Math.max(0, Math.min(100, (t - A) * 100 / (B - A)));
  const cols = week ? 7 : 24;
  const bar = (s, e, cls, color, title) => h('div', { class: 'tk-b ' + cls, style: { left: pct(s) + '%', width: Math.max(0.25, pct(e) - pct(s)) + '%', '--c': color }, title });
  const nowLine = () => now >= A && now < B ? h('div', { class: 'tk-now', style: { left: pct(now) + '%' } }) : null;
  const ticks = Array.from({ length: cols }, (_, i) => {
    if (!week) return h('div', { class: 'tk-tick' }, String(i).padStart(2, '0'));
    const d = addDays(new Date(A * 1000), i), today = dayStart(new Date()).getTime() === d.getTime();
    return h('div', { class: 'tk-tick click' + (today ? ' today' : ''), title: T('Günlük görünüm'), onclick: () => tkvGo('gunluk', d) },
      d.toLocaleDateString(LOC(), { weekday: 'short', day: 'numeric' }));
  });
  const evRow = e => {
    const st = e.durum, bars = st === 'acik' ? [bar(A, B, 'forced', e.renk, e.ad + ' · ' + T('elle açık'))]
      : e.araliklar.map(([s, x]) => bar(s, x, st === 'kapali' ? 'off' : '', e.renk, e.ad + ' · ' + tkvSpan(s, x) + (st === 'kapali' ? ' · ' + T('elle kapalı') : '')));
    return [h('div', { class: 'tk-row' }, h('div', { class: 'tk-name', onclick: () => tkvDetail(e.anahtar), title: e.aciklama || e.ad },
      h('i', { class: 'tk-dot', style: { background: e.renk } }), h('span', { class: 'ellipsis', style: { maxWidth: 'none' } }, e.ad),
      st ? badge(st === 'acik' ? T('elle açık') : T('elle kapalı'), st === 'acik' ? 'ok' : 'err') : null),
      h('div', { class: 'tk-track', style: { '--cols': cols } }, bars, nowLine())),
    ...e.seanslar.map(s => h('div', { class: 'tk-row sub' }, h('div', { class: 'tk-name', title: s.haritalar.join(', ') }, '↳ ', h('span', { class: 'ellipsis', style: { maxWidth: 'none' } },
      s.ad + (s.haritalar.length ? ' · ' + s.haritalar.join(', ') : ''))),
      h('div', { class: 'tk-track', style: { '--cols': cols } }, s.araliklar.map(([a, b, f]) => bar(a, b, 'sub' + (f === 1 ? ' cift' : ''), e.renk,
        s.ad + ' · ' + tkvSpan(a, b) + (f === 1 ? ' · ' + T('çift ödül') : f > 1 ? ' · ' + T('giriş {0}\'e kadar', hhmm(f)) : ''))), nowLine())))];
  };
  return h('div', { class: 'card tk-gantt-card' }, rows.length ? h('div', { class: 'tk-gantt' },
    h('div', { class: 'tk-row head' }, h('div', { class: 'tk-name muted small' }, T('{0} etkinlik', rows.length)), h('div', { class: 'tk-track ticks', style: { '--cols': cols } }, ticks)),
    rows.map(evRow)) : h('p', { class: 'desc' }, T('Bu aralıkta gösterilecek etkinlik yok.')));
}

// ---- günlük: seçili günün ayrıntılı listesi (bütün gün sürenler, saatli aralıklar ve seanslar sırayla)
function tkvDay(rows) {
  const [A, B] = TKV.kapsam, now = Date.now() / 1000;
  const allDay = [], timed = [];
  for (const e of rows) {
    const iv = e.durum === 'acik' ? [[A, B]] : e.durum === 'kapali' ? [] : e.araliklar;
    if (iv.some(([s, x]) => s <= A && x >= B)) allDay.push(e);
    else iv.forEach(([s, x]) => timed.push({ e, s, x, ad: e.ad }));
    e.seanslar.forEach(sn => sn.araliklar.forEach(([s, x, f]) => timed.push({ e, s, x, f, ad: e.ad, alt: sn.ad + (sn.haritalar.length ? ' · ' + sn.haritalar.join(', ') : '') })));
  }
  timed.sort((p, q) => p.s - q.s || p.x - q.x);
  const status = (s, x) => now >= x ? badge(T('Bitti'), '') : now >= s ? badge(T('Sürüyor · {0} kaldı', fmtDur(x - now)), 'ok') : badge(T('{0} sonra', fmtDur(s - now)), 'info');
  const dotc = e => h('i', { class: 'tk-dot', style: { background: e.renk } });
  const end = new Date(B * 1000);
  return h('div', { class: 'grid g2 tk-day' },
    h('div', { class: 'card' }, h('h2', null, icon('calendar'), T('Bütün gün ({0})', allDay.length)),
      allDay.length ? h('div', { class: 'stack', style: { gap: '10px' } }, allDay.map(e => h('div', { class: 'tk-item', onclick: () => tkvDetail(e.anahtar) },
        h('div', { class: 'row' }, dotc(e), h('b', null, e.ad), badge(T(TUR_AD[e.tur]), ''), e.durum ? badge(e.durum === 'acik' ? T('elle açık') : T('elle kapalı'), e.durum === 'acik' ? 'ok' : 'err') : null),
        e.aciklama ? h('div', { class: 'small muted' }, e.aciklama) : null, h('div', { class: 'small dim' }, '📅 ', e.zaman))))
        : h('p', { class: 'desc' }, T('Bu gün bütün gün süren etkinlik yok.'))),
    h('div', { class: 'card' }, h('h2', null, icon('clock'), T('Saatli ({0})', timed.length)),
      timed.length ? h('div', { class: 'tk-agenda' }, timed.map(t => h('div', { class: 'tk-item row' + (now >= t.x ? ' past' : ''), onclick: () => tkvDetail(t.e.anahtar) },
        h('span', { class: 'mono tk-time' }, hhmm(t.s) + '–' + (t.x >= B && !end.getHours() ? '24:00' : hhmm(t.x))), dotc(t.e),
        h('div', { style: { flex: 1, minWidth: 0 } }, h('div', null, t.ad), t.alt ? h('div', { class: 'small muted' }, t.alt,
          t.f === 1 ? ' · ' + T('çift ödül') : t.f > 1 ? ' · ' + T('giriş {0}\'e kadar', hhmm(t.f)) : '') : null),
        status(t.s, t.x))))
        : h('p', { class: 'desc' }, T('Bu gün saatli etkinlik ya da seans yok.'))));
}

// ---- aylık: 6 haftalık ızgara; gün hücresinde o gün açık etkinlikler (tıklayınca günlük görünüm)
function tkvMonth(rows) {
  const [A] = TKV.kapsam, month = new Date(((TKV.kapsam[0] + TKV.kapsam[1]) / 2) * 1000).getMonth(), today = dayStart(new Date()).getTime();
  const heads = Array.from({ length: 7 }, (_, i) => h('div', { class: 'tk-mhead' }, addDays(new Date(A * 1000), i).toLocaleDateString(LOC(), { weekday: 'short' })));
  const cells = Array.from({ length: 42 }, (_, i) => {
    const d = addDays(new Date(A * 1000), i), s = d.getTime() / 1000, x = addDays(d, 1).getTime() / 1000;
    const items = [];
    for (const e of rows) {
      const iv = e.durum === 'acik' ? [[s, x]] : e.durum === 'kapali' ? [] : e.araliklar.filter(([p, q]) => p < x && q > s);
      if (iv.length) items.push({ e, saat: iv[0][0] > s ? hhmm(iv[0][0]) : null, tam: iv.some(([p, q]) => p <= s && q >= x) });
      else if (e.seanslar.some(sn => sn.araliklar.some(([p, q]) => p < x && q > s))) items.push({ e, saat: null, tam: false, seans: true });
    }
    items.sort((p, q) => (p.e.tur !== 'yillik') - (q.e.tur !== 'yillik') || (!p.tam) - (!q.tam));
    const max = 4;
    return h('div', { class: 'tk-cell' + (d.getMonth() !== month ? ' other' : '') + (d.getTime() === today ? ' today' : ''), onclick: () => tkvGo('gunluk', d) },
      h('div', { class: 'tk-dnum' }, d.getDate()),
      items.slice(0, max).map(it => h('div', { class: 'tk-mchip' + (it.e.durum === 'acik' ? ' forced' : ''), style: { '--c': it.e.renk }, title: it.e.ad },
        it.saat ? h('span', { class: 'dim' }, it.saat + ' ') : null, it.e.ad)),
      items.length > max ? h('div', { class: 'small muted' }, T('+{0} daha', items.length - max)) : null);
  });
  return h('div', { class: 'card' }, h('div', { class: 'tk-month' }, heads, cells));
}

// ---- etkinliğin ayrıntısı: açıklama, takvim, bu görünümdeki aralıklar, seanslar; elle açık / kapalı seçimi
function tkvDetail(key) {
  const e = TKV.veri.etkinlikler.find(x => x.anahtar === key); if (!e) return;
  const now = Date.now() / 1000, st = e.durum || 'takvim';
  const set = v => act(() => api('/api/etkinlikler', { degisiklik: { [key]: v } }), T('Güncellendi.')).then(x => { if (x) { m.close(); renderTakvim(); } });
  const iv = e.durum === 'acik' ? [] : e.araliklar;
  const cur = e.sonraki && e.sonraki[0] <= now + 1 ? T('Takvimde açık · {0} kaldı', fmtDur(e.sonraki[1] - now))
    : e.sonraki ? T('Takvimde sonraki: {0} ({1} sonra)', tkvSpan(e.sonraki[0], e.sonraki[1]), fmtDur(e.sonraki[0] - now)) : T('Takvimde yakında dönemi yok.');
  const m = modal({
    title: e.ad, sub: T(TUR_AD[e.tur]) + ' · ' + (e.etkin ? T('şu an açık') : T('şu an kapalı')), wide: true,
    body: h('div', { class: 'stack', style: { gap: '12px' } },
      e.aciklama ? h('div', null, e.aciklama) : null,
      h('div', { class: 'kv one tk-kv' }, [[T('Takvim'), e.zaman], [T('Durum'), cur]].map(([a, b]) => h('div', null, h('span', { class: 'muted' }, a), h('b', null, b)))),
      h('div', null, h('div', { class: 'lbl' }, T('Bu görünümde')), iv.length ? h('div', { class: 'chips', style: { marginTop: '6px' } }, iv.slice(0, 24).map(([s, x]) => h('span', { class: 'chip' }, tkvSpan(s, x))),
        iv.length > 24 ? h('span', { class: 'small muted' }, T('+{0} daha', iv.length - 24)) : null)
        : h('div', { class: 'small muted' }, e.durum === 'acik' ? T('Elle açık: her zaman geçerli.') : T('Bu görünümde takvimde yok.'))),
      e.seanslar.length ? h('div', null, h('div', { class: 'lbl' }, T('Seanslar ve doğuş saatleri')), h('div', { class: 'stack', style: { gap: '6px', marginTop: '6px' } },
        e.seanslar.map(s => h('div', { class: 'small' }, h('b', null, s.ad), s.haritalar.length ? ' · ' + s.haritalar.join(', ') : '',
          h('div', { class: 'muted' }, s.araliklar.length ? [...new Set(s.araliklar.map(([a, b]) => hhmm(a) + '–' + hhmm(b)))].slice(0, 12).join(', ') : T('Bu görünümde yok')))))) : null,
      h('div', null, h('div', { class: 'lbl' }, T('Oyunda')), h('div', { class: 'seg', style: { marginTop: '6px' } },
        [['takvim', T('Takvime göre'), 'info'], ['acik', T('Açık'), 'ok'], ['kapali', T('Kapalı'), 'err']].map(([k, t, c]) =>
          h('button', { class: (st === k ? 'on ' : '') + c, onclick: () => set(k === 'takvim' ? null : k) }, t))))),
    foot: [btn(T('Etkinlikler sayfası'), () => { m.close(); go('etkinlikler'); }, 'ghost', 'calendar'), btn(T('Kapat'), () => m.close(), 'primary')],
  });
}

// ================================================================== İSTEMCİ
const versionText = (c, supported) => !c.surum ? T('Sürüm bilinmiyor')
  : c.uyumlu ? T('Sürüm {0} (sunucuyla uyumlu)', c.surum) : T('Sürüm {0} — sunucu {1} için yazıldı', c.surum, supported);
const checkRow = (ok, text, warn) => h('div', { class: ok ? 'ok' : warn ? 'wr' : 'no' }, icon(ok ? 'check' : warn ? 'alert' : 'x'), text);
const WINDOW_MODES = [['pencere', N('Pencere')], ['kenarliksiz', N('Kenarlıksız tam ekran')], ['tam_ekran', N('Tam ekran')]];
function resolutionList(r) {
  const res = r.cozunurlukler.map(([w, hh]) => `${w}x${hh}`);
  const scr = r.ekran ? `${r.ekran[0]}x${r.ekran[1]}` : null;
  if (scr && !res.includes(scr)) res.push(scr);
  return { res, scr };
}

// ---- oyunu indirme (indirme.py, /api/istemci/indirme): sihirbazın oyun klasörü adımı ve İstemci sayfası
const DL_ACTIVE = st => st.calisiyor || st.yarim || ['hata', 'durdu', 'bitti'].includes(st.durum);
const dlPct = st => st.toplam ? Math.floor(100 * st.alinan / st.toplam) : 0;
function dlBox(st, refresh, { haveClient = false } = {}) {      // haveClient: geçerli istemci var, yarım dosyalar yalnız silinir
  const pct = dlPct(st), run = st.calisiyor;
  const call = (path, msg) => act(() => api(path, {}), msg).then(x => { if (x) refresh(x); });
  const discard = async () => {
    if (await confirmBox(T('Yarım indirme silinsin mi?'), T('İndirilen dosyalar (proje klasöründeki istemci_indiriliyor) silinir; sonra baştan iner.'), { ok: T('Sil'), danger: true }))
      call('/api/istemci/indir_sil', T('Yarım indirme silindi.'));
  };
  const head = { hazirlaniyor: T('İndirme hazırlanıyor…'), indiriliyor: T('Oyun indiriliyor: %{0}', pct), dogrulaniyor: T('Dosyalar doğrulanıyor…'),
    bitti: T('Oyun indirildi ve kuruldu.'), hata: T('İndirme durdu.'), durdu: T('İndirme durduruldu (%{0}).', pct) }[st.durum]
    || (st.yarim ? T('Önceki indirme yarım kaldı.') : T('Oyunu indir'));
  const info = st.durum === 'indiriliyor'
    ? [`${fmtBytes(st.alinan)} / ${fmtBytes(st.toplam)}`, st.hiz ? `${fmtBytes(st.hiz)}/${T('sn')}` : null,
      st.kalan_sn != null && st.hiz ? T('kalan {0}', fmtDur(st.kalan_sn)) : null, T('dosya {0}/{1}', st.biten_dosya, st.dosya_sayisi)].filter(Boolean).join(' · ')
    : st.durum === 'bitti' ? st.hedef
    : st.durum === 'hata' ? st.hata
    : haveClient && st.yarim ? T('Seçili istemci kullanılıyor; yarım kalan dosyaları silebilirsin.')
    : st.durum === 'durdu' || st.yarim ? T('Sürdürünce yalnız eksik dosyalar iner.')
    : st.durum === 'bos' ? T('DarkOrbit {0} istemcisi oyunun resmî indirme sunucusundan alınıp proje klasörüne kurulur: yaklaşık 3,5 GB indirme, diskte 4,3 GB. İstemci dosyaları değiştirilmez.', '1.1.115')
    : '';
  const btns = run ? [btn(T('Durdur'), () => call('/api/istemci/indir_durdur', T('İndirme durduruluyor…')), 'ghost sm', 'stop')]
    : st.durum === 'bitti' ? []
    : [haveClient ? null : btn(st.durum === 'hata' ? T('Yeniden dene') : st.durum === 'durdu' || st.yarim ? T('Sürdür') : T('İndir ve kur'), () => call('/api/istemci/indir'), 'primary sm', 'download'),
      st.yarim ? btn(T('Yarım indirmeyi sil'), discard, 'ghost sm', 'trash') : null];
  return h('div', { class: 'dl-box ' + (st.durum === 'hata' ? 'err' : st.durum === 'bitti' ? 'ok' : '') },
    h('b', null, head),
    run || st.durum === 'durdu' ? h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } }))) : null,
    info ? h('div', { class: 'small muted dl-info', title: st.dosya || '' }, info) : null,
    btns.some(Boolean) ? h('div', { class: 'row wrap' }, btns) : null);
}
// kutuyu saniyede bir yeniler; iş bitince (bitti) onDone. -> setInterval kimliği
function dlWatch(wrap, st, onDone, opts) {
  let sig = JSON.stringify(st);
  const draw = s => wrap.replaceChildren(dlBox(s, x => { draw(x); sig = JSON.stringify(x); }, opts));
  draw(st);
  const id = setInterval(async () => {
    if (!wrap.isConnected) { clearInterval(id); return; }
    let s; try { s = await api('/api/istemci/indirme'); } catch (e) { return; }
    const was = JSON.parse(sig);
    const n = JSON.stringify(s);
    if (n === sig) return;
    sig = n; draw(s);
    if (s.durum === 'bitti' && was.durum !== 'bitti' && onDone) onDone(s);
  }, 1000);
  return id;
}

// ---- macOS: panelin kurduğu Wine + DXMT ve Rosetta 2 (wine_motoru.py, /api/motor): Wine / Proton kartı ve sihirbazın oyun klasörü adımı
function motorBox(m, refresh, { motor = true } = {}) {
  const call = (path, msg) => act(() => api(path, {}), msg).then(x => { if (x) refresh(x); });
  const pct = m.toplam ? Math.floor(100 * m.alinan / m.toplam) : 0, run = m.calisiyor, ros = m.rosetta;
  const rosetta = !ros.gerekli ? null : ros.var ? h('div', { class: 'check-list', style: { margin: 0 } }, checkRow(true, T('Rosetta 2 kurulu')))
    : h('div', { class: 'alert hata' }, icon('alert'), h('div', null, T("Rosetta 2 kurulu değil: oyunu açan Wine Apple Silicon'da onunla çalışır. Kurmak için macOS yönetici şifreni sorar."),
      ros.hata ? h('div', { class: 'small' }, ros.hata) : null),
      btn(ros.durum === 'kuruluyor' ? T('Kuruluyor…') : T("Rosetta'yı kur"), () => call('/api/rosetta/kur'), 'primary sm', 'download', { disabled: ros.durum === 'kuruluyor' }));
  const old = m.macos_eski ? h('div', { class: 'alert uyari' }, icon('alert'), h('div', null, T('DXMT macOS 14 Sonoma ya da daha yenisini ister (bu Mac: {0}); oyun açılmayabilir.', m.macos))) : null;
  if (!motor) return h('div', { class: 'stack', style: { gap: '10px' } }, rosetta, old);
  const head = run ? (m.durum === 'kuruluyor' ? T('Wine kuruluyor…') : T('Wine ve DXMT indiriliyor: %{0}', pct))
    : m.durum === 'kurulu' ? T('Oyunu açacak Wine hazır: {0}', m.ad) : m.durum === 'hata' ? T('Wine kurulamadı.')
    : m.durum === 'durdu' ? T('Wine indirmesi durduruldu.') : T('Oyunu açacak Wine henüz kurulmadı.');
  const info = run ? [`${fmtBytes(m.alinan)} / ${fmtBytes(m.toplam)}`, m.hiz ? `${fmtBytes(m.hiz)}/${T('sn')}` : null,
      m.kalan_sn != null && m.hiz ? T('kalan {0}', fmtDur(m.kalan_sn)) : null].filter(Boolean).join(' · ')
    : m.durum === 'hata' ? m.hata : m.durum === 'kurulu' ? m.klasor
    : T("{0} indirilip kurulur (yaklaşık {1}); ilk OYNA'da da kendiliğinden iner.", m.ad, fmtBytes(m.boyut));
  const btns = run ? [btn(T('Durdur'), () => call('/api/motor/durdur', T('İndirme durduruluyor…')), 'ghost sm', 'stop')]
    : m.durum === 'kurulu' ? [] : [btn(m.durum === 'hata' || m.durum === 'durdu' ? T('Yeniden dene') : T('İndir ve kur'), () => call('/api/motor/kur'), 'primary sm', 'download')];
  return h('div', { class: 'stack', style: { gap: '10px' } },
    h('div', { class: 'dl-box ' + (m.durum === 'hata' ? 'err' : m.durum === 'kurulu' ? 'ok' : '') }, h('b', null, head),
      run ? h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } }))) : null,
      info ? h('div', { class: 'small muted dl-info' }, info) : null,
      btns.length ? h('div', { class: 'row wrap' }, btns) : null),
    rosetta, old);
}
// kutuyu saniyede bir yeniler (sayfadan çıkınca kendiliğinden durur) -> setInterval kimliği
function motorWatch(wrap, m, opts) {
  let sig = JSON.stringify(m);
  const draw = x => { sig = JSON.stringify(x); wrap.replaceChildren(motorBox(x, draw, opts)); };
  draw(m);
  const id = setInterval(async () => {
    if (!wrap.isConnected) { clearInterval(id); return; }
    let x; try { x = await api('/api/motor'); } catch (e) { return; }
    if (JSON.stringify(x) !== sig) draw(x);
  }, 1000);
  return id;
}

// ---- Windows: istemcinin düzeltmelerini yükleyen BepInEx (istemci_yama.py, /api/yama): İstemci sayfası ve sihirbazın oyun klasörü adımı
function yamaBox(y, refresh) {
  const call = path => act(() => api(path, {})).then(x => { if (x) refresh(x); });
  const pct = y.toplam ? Math.floor(100 * y.alinan / y.toplam) : 0, run = y.calisiyor;
  const head = run ? (y.durum === 'kuruluyor' ? T('BepInEx kuruluyor…') : T('BepInEx indiriliyor: %{0}', pct))
    : y.durum === 'kurulu' ? T('İstemci düzeltmeleri hazır: {0}', y.ad) : y.durum === 'hata' ? T('BepInEx kurulamadı.')
    : y.durum === 'durdu' ? T('BepInEx indirmesi durduruldu.') : T('BepInEx henüz kurulmadı.');
  const info = run ? `${fmtBytes(y.alinan)} / ${fmtBytes(y.toplam)}` : y.durum === 'hata' ? y.hata
    : y.durum === 'kurulu' ? T('Müzayede sayacı, rütbe penceresi ve mağaza tutarı düzeltilir. Oyunun ilk açılışında BepInEx yarım dakika kadar hazırlanır.')
    : T("İstemcinin küçük hatalarını düzelten eklenti BepInEx ile yüklenir: {0} oyun klasörüne kurulur (yaklaşık {1}); ilk OYNA'da da kendiliğinden kurulur.", y.ad, fmtBytes(y.toplam));
  const btns = run ? [btn(T('Durdur'), () => call('/api/yama/durdur'), 'ghost sm', 'stop')]
    : y.durum === 'kurulu' ? [] : [btn(y.durum === 'hata' || y.durum === 'durdu' ? T('Yeniden dene') : T('İndir ve kur'), () => call('/api/yama/kur'), 'primary sm', 'download')];
  return h('div', { class: 'dl-box ' + (y.durum === 'hata' ? 'err' : y.durum === 'kurulu' ? 'ok' : '') }, h('b', null, head),
    run ? h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } }))) : null,
    info ? h('div', { class: 'small muted dl-info' }, info) : null,
    btns.length ? h('div', { class: 'row wrap' }, btns) : null);
}
// kutuyu saniyede bir yeniler (sayfadan çıkınca kendiliğinden durur) -> setInterval kimliği
function yamaWatch(wrap, y) {
  let sig = JSON.stringify(y);
  const draw = x => { sig = JSON.stringify(x); wrap.replaceChildren(yamaBox(x, draw)); };
  draw(y);
  const id = setInterval(async () => {
    if (!wrap.isConnected) { clearInterval(id); return; }
    let x; try { x = await api('/api/yama'); } catch (e) { return; }
    if (JSON.stringify(x) !== sig) draw(x);
  }, 1000);
  return id;
}

// ---- Linux ve macOS: istemciyi açan Wine ya da Proton (calistirici.py; /api/istemci 'calistirici', Windows'ta null)
function runnerCard(c, cfg, saveCfg) {
  const mac = c.platform === 'darwin';
  const kinds = [['otomatik', T('Otomatik')], ['motor', T("Panelin Wine'ı")], ['wine', 'Wine'], ['proton', 'Proton'], ['ozel', T('Özel komut')]]
    .filter(([k]) => mac ? k !== 'proton' : k !== 'motor');
  const seg = h('div', { class: 'seg' }, kinds.map(([k, t]) =>
    h('button', { class: cfg.calistirici === k ? 'on info' : '', onclick: () => saveCfg({ calistirici: k, calistirici_yolu: '' }) }, t)));
  const used = c.tur === 'proton' ? `${c.ad}${c.umu ? ' (umu-run)' : ''}` : c.tur === 'ozel' ? c.yol : c.ad;
  const mWrap = mac ? h('div', { class: 'dl-wrap' }) : null;
  if (mWrap && c.motor) S.timers.push(motorWatch(mWrap, c.motor, { motor: c.tur === 'motor' }));
  const pathIn = h('input', { class: 'input mono', value: cfg.calistirici_yolu, placeholder: cfg.calistirici === 'ozel' ? T('ör. umu-run') : T('Boş: kendiliğinden bulunur'),
    onchange: e => saveCfg({ calistirici_yolu: e.target.value.trim() }) });
  const prefixIn = h('input', { class: 'input mono', value: cfg.wine_onek, placeholder: c.varsayilan_onek[c.tur] || T('Boş: Wine\'ın öntanımlısı'),
    onchange: e => saveCfg({ wine_onek: e.target.value.trim() }) });
  const found = [...c.protonlar.map(p => ['proton', p.yol, p.ad]), ...c.wineler.map(w => ['wine', w, 'Wine'])];
  return h('div', { class: 'card' }, h('h2', null, icon('zap'), 'Wine / Proton'),
    h('p', { class: 'desc' }, T("Oyun bir Windows programı; Linux ve macOS'ta Wine ya da Proton ile açılır. Otomatik: Linux'ta Steam'in Proton'u (umu-run kuruluysa onunla), yoksa Wine; macOS'ta panelin kendi kurduğu Wine ve DXMT (macOS'ta düz Wine oyunun Direct3D 11 grafiklerini çizemez). İstemci kendi öneğinde çalışır; önek ilk açılışta kurulur (yarım dakika kadar sürebilir).")),
    c.hata && !(mac && c.motor && !c.motor.rosetta.var) ? h('div', { class: 'alert hata' }, icon('alert'), h('div', null, c.hata))
      : h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Kullanılan: {0}', used))),
    mWrap ? h('div', { style: { marginTop: '12px' } }, mWrap) : null,
    h('div', { class: 'stack', style: { gap: '14px', marginTop: '12px' } },
      field(T('Çalıştırıcı'), seg),
      c.tur === 'motor' ? null : field(cfg.calistirici === 'ozel' ? T('Komut (istemcinin önüne eklenir)') : T('Yol (wine programı ya da Proton klasörü)'), pathIn),
      field(T('Önek klasörü (WINEPREFIX)'), prefixIn)),
    found.length ? [h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('Bulunanlar')),
      h('div', { class: 'stack', style: { gap: '8px', marginTop: '8px' } }, found.map(([k, yol, ad]) => h('div', { class: 'row' },
        badge(ad, 'info'), h('span', { class: 'mono', style: { flex: 1, minWidth: 0, wordBreak: 'break-all' } }, yol),
        c.tur === k && c.yol === yol ? badge(T('kullanılıyor'), 'ok') : btn(T('Kullan'), () => saveCfg({ calistirici: k, calistirici_yolu: yol }), 'sm'))))] : null,
    h('div', { class: 'small muted', style: { marginTop: '12px' } }, T('Oyun açılmazsa Sunucu sayfasındaki wine.log günlüğüne bakın.')));
}

async function renderIstemci(data) {
  const r = data || await act(() => api('/api/istemci')); if (!r || S.page !== 'istemci') return;
  const c = r.kontrol, cfg = r.ayarlar;
  const dlWrap = !c.gecerli || DL_ACTIVE(r.indirme) ? h('div', { class: 'dl-wrap' }) : null;
  const yWrap = c.gecerli && r.yama.gerekli ? h('div', { class: 'dl-wrap' }) : null;
  const saveCfg = (vals, msg = T('Kaydedildi.')) => act(() => api('/api/panel_ayarlari', { degerler: vals }), msg).then(x => x && renderIstemci(x));
  const folderCard = h('div', { class: 'card' }, h('h2', null, icon('folder'), T('İstemci klasörü')),
    h('p', { class: 'desc' }, T('Orijinal DarkOrbit Unity istemcisinin klasörü (içinde DarkOrbit.exe ve DarkOrbit_Data olan). Güncelleme gelirse ya da klasörü taşırsan buradan seç.')),
    h('div', { class: 'path' }, c.yol || T('Seçilmedi')),
    h('div', { class: 'small muted', style: { marginTop: '6px' } }, r.secili ? T('Elle seçildi.') : T('Kendiliğinden bulundu (bilinen klasörlerdeki en uygun sürüm).')),
    h('div', { class: 'check-list' },
      checkRow(c.exe, 'DarkOrbit.exe'), checkRow(c.veri, T('DarkOrbit_Data klasörü')),
      c.gecerli ? checkRow(c.uyumlu, versionText(c, r.desteklenen), !c.uyumlu) : null),
    c.sorunlar.length && !c.gecerli && !r.indirme.calisiyor ? h('div', { class: 'alert hata' }, icon('alert'), h('div', null, c.sorunlar.join(' '))) : null,
    dlWrap ? [h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('Oyunu indir')), dlWrap] : null,
    yWrap ? [h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('İstemci düzeltmeleri (BepInEx)')), yWrap] : null,
    h('div', { id: 'proto-box' }),
    h('div', { class: 'row wrap', style: { marginTop: '12px' } },
      btn(T('Klasör seç…'), () => act(() => api('/api/istemci/sec', {}), x => x.iptal ? T('İptal edildi.') : T('İstemci klasörü kaydedildi.')).then(x => x && renderIstemci(x)), 'primary', 'folder'),
      btn(T('Kendiliğinden bul'), () => act(() => api('/api/istemci/otomatik', {}), T('Kendiliğinden bulma açık.')).then(x => x && renderIstemci(x)), '', 'search'),
      btn(T('Klasörü aç'), () => act(() => api('/api/klasor_ac', { ne: 'istemci' })), 'ghost', 'folder')),
    r.adaylar.length > 1 || (r.adaylar.length === 1 && r.adaylar[0].yol !== c.yol) ? [h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('Bulunan istemciler')),
      h('div', { class: 'stack', style: { gap: '8px', marginTop: '8px' } }, r.adaylar.map(a => h('div', { class: 'row' },
        badge(a.surum || '?', a.uyumlu ? 'ok' : 'warn'), h('span', { class: 'mono', style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' } }, a.yol),
        a.yol === c.yol ? badge(T('kullanılıyor'), 'info') : btn(T('Kullan'), () => act(() => api('/api/istemci/kullan', { yol: a.yol }), T('Kaydedildi.')).then(x => x && renderIstemci(x)), 'sm'))))] : null);

  const { res, scr } = resolutionList(r);
  const cur = `${cfg.genislik}x${cfg.yukseklik}`;
  const custom = !res.includes(cur);
  const sel = h('select', { class: 'input', style: { width: '220px' }, onchange: e => {
    if (e.target.value === 'ozel') { cw.style.display = ''; return; }
    const [w, hh] = e.target.value.split('x').map(Number); saveCfg({ genislik: w, yukseklik: hh });
  } }, res.map(x => h('option', { value: x, selected: x === cur }, x + (x === scr ? '  (' + T('ekran') + ')' : ''))), h('option', { value: 'ozel', selected: custom }, T('Özel…')));
  const wIn = h('input', { class: 'input num', type: 'number', value: cfg.genislik }), hIn = h('input', { class: 'input num', type: 'number', value: cfg.yukseklik });
  const cw = h('div', { class: 'row', style: { display: custom ? '' : 'none' } }, wIn, '×', hIn, btn(T('Uygula'), () => saveCfg({ genislik: +wIn.value, yukseklik: +hIn.value }), 'sm'));
  const mode = h('div', { class: 'seg' }, WINDOW_MODES.map(([k, t]) =>
    h('button', { class: cfg.pencere_modu === k ? 'on info' : '', onclick: () => saveCfg({ pencere_modu: k }) }, T(t))));
  const mon = h('select', { class: 'input', style: { width: '160px' }, onchange: e => saveCfg({ monitor: +e.target.value }) },
    [0, 1, 2, 3, 4].map(i => h('option', { value: i, selected: cfg.monitor === i }, i ? T('Ekran {0}', i) : T('Varsayılan'))));
  const extra = h('input', { class: 'input mono', value: cfg.ek_argumanlar, placeholder: T('ör. -force-d3d11'), onchange: e => saveCfg({ ek_argumanlar: e.target.value }) });
  const dispCard = h('div', { class: 'card' }, h('h2', null, icon('monitor'), T('Görüntü')),
    h('p', { class: 'desc' }, T('İstemciye başlatma argümanı olarak verilir; oyunun kendi grafik ayarları (2D/3D, kalite) oyun içinden.')),
    h('div', { class: 'stack', style: { gap: '14px' } },
      field(T('Pencere kipi'), mode),
      field(T('Çözünürlük'), h('div', { class: 'row wrap' }, sel, cw)),
      field(T('Ekran'), mon),
      field(T('Ek Unity argümanları (gelişmiş)'), extra),
      field(T('Başlatma komutu'), h('div', { class: 'cmd' }, r.komut.join(' ')))));
  const warn = h('div', { class: 'alert uyari' }, icon('alert'), h('div', null,
    T("Klasördeki DarkorbitLauncher.exe'yi çalıştırma: istemciyi resmî sunucudan güncelleyip yerel sunucuyla uyumu bozabilir. Panel istemcinin kendi dosyalarını değiştirmez; yerel giriş adresiyle başlatır, Windows'ta yanına kurduğu BepInEx'le küçük düzeltmeleri yükler.")));
  const multiCfg = h('div', { class: 'card compact' }, h('h2', null, icon('users'), T('Çoklu istemci')),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Öteki kayıtlarla ek istemciler')),
      h('div', { class: 'help' }, T("Açıksa ve en az iki kaydın varsa OYNA sunucuyu çok oturumlu açar; Oyna sayfasından öteki kayıtlarınla aynı sunucuya ek istemciler açarsın. Ek istemciler pencere kipinde açılır; görüntü ayarları ortaktır."))),
      h('div', { class: 'ctl' }, h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: cfg.coklu_istemci, onchange: e => saveCfg({ coklu_istemci: e.target.checked }) }), h('span')))),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('En çok ek istemci')),
      h('div', { class: 'help' }, T('Her istemci yaklaşık 600 MB bellek ve bir miktar ekran kartı kullanır.'))),
      h('div', { class: 'ctl' }, h('select', { class: 'input', style: { width: '90px' }, onchange: e => saveCfg({ coklu_en_cok: +e.target.value }) },
        [1, 2, 3, 4, 5, 6, 7, 8].map(n => h('option', { value: n, selected: cfg.coklu_en_cok === n }, String(n)))))));
  $('#content').replaceChildren(h('div', { class: 'stack' }, h('div', { class: 'grid g2' }, folderCard, dispCard),
    r.calistirici ? runnerCard(r.calistirici, cfg, saveCfg) : null, multiCfg, warn));
  S.sig = S.sig || {}; S.proto = null; S.protoClient = c;
  if (dlWrap) S.timers.push(dlWatch(dlWrap, r.indirme, () => { toast(T('Oyun indirildi ve kuruldu.'), 'ok'); renderIstemci(); }, { haveClient: c.gecerli }));
  if (yWrap) S.timers.push(yamaWatch(yWrap, r.yama));
  protoTick(true);
  S.timers.push(setInterval(() => protoTick(), 1000));
}

// ---- yeni istemciye protokol uyarlaması (tools/il2cpp/protokol_guncelle.py; protokol.py, /api/protokol)
async function protoTick(force) {
  const box = $('#proto-box'); if (!box) return;
  if (!force && !(S.proto && S.proto.calisiyor)) return;
  let r; try { r = await api('/api/protokol'); } catch (e) { return; }
  const sig = JSON.stringify(r);
  if (!force && S.sig.proto === sig) return;
  S.sig.proto = sig; S.proto = r;
  const c = S.protoClient || {}, o = r.ozet || {}, run = r.calisiyor;
  const need = c.gecerli && !c.uyumlu;
  if (!need && !run && !r.ozet && !r.hata) { box.replaceChildren(); return; }
  const kv = [[N('Eklenen'), o.eklenen], [N('Silinen'), o.silinen], [N('Kimliği değişen'), o.kimlik], [N('Alanları değişen'), o.alanlar],
    [N('Kodlaması değişen'), o.yazma], [N('Okuması değişen'), o.okuma], [N('Belirsiz alan'), o.belirsiz]].filter(([, v]) => v != null);
  const gen = () => act(() => api('/api/protokol/uret', {}), T('Protokol aracı başladı.')).then(() => protoTick(true));
  const use = () => act(() => api('/api/protokol/uygula', { surum: o.surum }), T('Uygulanıyor…')).then(() => protoTick(true));
  box.replaceChildren(h('div', { class: 'alert ' + (r.hata ? 'hata' : need ? 'uyari' : 'bilgi'), style: { marginTop: '12px' } }, icon(r.hata ? 'alert' : 'info'),
    h('div', { class: 'stack', style: { gap: '6px', flex: 1, minWidth: 0 } },
      h('div', null, need ? T('Sunucunun etkin protokolü {0} için. Yeni istemciyi uyarla: protokolü bu istemcinin kodundan üretir ve farkları raporlar (etkin dosyalara dokunmaz).', r.etkin)
        : T('Etkin protokol: {0}.', r.etkin)),
      run ? h('div', { class: 'row' }, h('span', { class: 'spin' }), h('span', { class: 'small' }, (r.satirlar || []).slice(-1)[0] || T('Çalışıyor…'))) : null,
      r.hata ? h('div', { class: 'small' }, r.hata) : null,
      kv.length ? h('div', { class: 'small' }, `${o.surum || ''}: ` + kv.map(([k, v]) => `${T(k)} ${v}`).join(' · ')) : null,
      o.rapor ? h('div', { class: 'small mono', style: { overflow: 'hidden', textOverflow: 'ellipsis' } }, o.rapor) : null,
      h('div', { class: 'row wrap' },
        need && !run ? btn(T('Yeni istemciyi uyarla'), gen, 'primary sm', 'refresh') : null,
        !run && r.is === 'uret' && !r.hata && o.surum && o.surum !== r.etkin ? btn(T('{0} protokolünü uygula', o.surum), use, 'sm', 'check') : null,
        !run && r.is === 'uygula' && !r.hata ? h('span', { class: 'small' }, T('Uygulandı; oyun sunucusu yeniden başlatılınca yeni protokolle çalışır.')) : null))));
}

// ================================================================== SUNUCU
let logState = { ad: 'gs.log', satir: 400, filtre: '', oto: true };
async function renderSunucu() {
  const cfg = await act(() => api('/api/panel_ayarlari')); if (!cfg || S.page !== 'sunucu') return;
  S.panelCfg = cfg;
  const saveCfg = vals => act(() => api('/api/panel_ayarlari', { degerler: vals }), T('Kaydedildi.')).then(() => renderSunucu());
  const seg = (key, opts) => h('div', { class: 'seg' }, opts.map(([k, t]) => h('button', { class: cfg[key] === k ? 'on info' : '', onclick: () => saveCfg({ [key]: k }) }, t)));
  const behav = h('div', { class: 'card compact' }, h('h2', null, icon('sliders'), T('Davranış')),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('İstemci kapanınca')), h('div', { class: 'help' }, T('Oyundan çıkınca panelin açtığı sunucular ne olsun?'))),
      h('div', { class: 'ctl' }, seg('istemci_kapaninca', [['kapat', T('Sunucuları kapat')], ['acik', T('Açık bırak')]]))),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Panel penceresi kapanınca')), h('div', { class: 'help' }, T('Oyun sürüyorsa beklenir, sonra panel ve sunucular kapanır; ya da her şey hemen kapanır.'))),
      h('div', { class: 'ctl' }, seg('pencere_kapaninca', [['bekle', T('Oyun bitince kapat')], ['kapat', T('Hemen kapat')]]))),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Günlükleri döndür')), h('div', { class: 'help' }, T("5 MB'ı geçen günlükler başlatmada .1, .2, .3 olarak saklanır."))),
      h('div', { class: 'ctl' }, h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: cfg.gunluk_dondur, onchange: e => saveCfg({ gunluk_dondur: e.target.checked }) }), h('span')))));
  const ports = h('div', { class: 'card' }, h('h2', null, icon('link'), T('Portlar')),
    h('p', { class: 'desc' }, T('Sunucu başlamıyorsa portları başka bir süreç (önceki oturumdan kalan sunucu ya da başka program) tutuyor olabilir.')),
    h('div', { id: 'port-list' }), h('div', { class: 'row' }, btn(T('Portları denetle'), () => checkPorts(), 'sm', 'search')));
  const logs = h('div', { class: 'card' },
    h('div', { class: 'row between wrap' }, h('h2', null, icon('note'), T('Günlükler')),
      h('div', { class: 'row wrap' },
        h('input', { class: 'input', style: { width: '180px' }, placeholder: T('Süz…'), value: logState.filtre, oninput: e => { logState.filtre = e.target.value; loadLog(); } }),
        h('select', { class: 'input', style: { width: '110px' }, onchange: e => { logState.satir = +e.target.value; loadLog(); } },
          [200, 400, 1000, 3000].map(n => h('option', { value: n, selected: logState.satir === n }, T('{0} satır', n)))),
        h('label', { class: 'row small muted' }, h('span', { class: 'switch' }, h('input', { type: 'checkbox', checked: logState.oto, onchange: e => { logState.oto = e.target.checked; } }), h('span')), T('Canlı')),
        btn('', () => loadLog(), 'ghost sm icon', 'refresh', { title: T('Yenile') }),
        btn(T('Klasör'), () => act(() => api('/api/klasor_ac', { ne: 'gunlukler' })), 'ghost sm', 'folder'),
        btn(T('Temizle'), async () => { if (await confirmBox(T('Günlük temizlensin mi?'), T('{0} boşaltılır.', logState.ad), { ok: T('Temizle'), danger: true })) act(() => api('/api/gunluk/temizle', { ad: logState.ad }), T('Temizlendi.')).then(loadLog); }, 'ghost sm', 'trash'))),
    h('div', { class: 'log-tabs', id: 'log-tabs', style: { margin: '10px 0' } }), h('div', { class: 'log-view', id: 'log-view' }));
  const tests = h('div', { class: 'card', id: 'test-card', style: { display: 'none' } });
  $('#content').replaceChildren(h('div', { class: 'stack' }, h('div', { class: 'grid g3', id: 'srv-cards' }), h('div', { class: 'grid g2' }, behav, ports), tests, logs));
  S.sig = {}; S.tests = null;
  renderServerCards();
  testTick(true);
  loadLog();
  S.timers.push(setInterval(() => { if (logState.oto && document.visibilityState === 'visible') loadLog(true); }, 2000));
}

// ---- testler (server/test/test_*.py; testler.py, /api/testler). Test dosyası yoksa kart görünmez.
const TEST_ST = { gecti: [N('Geçti'), 'ok'], kaldi: [N('Kaldı'), 'err'], zaman_asimi: [N('Zaman aşımı'), 'err'], calisiyor: [N('Çalışıyor'), 'info'],
  bekliyor: [N('Bekliyor'), ''], atlandi: [N('Atlandı'), 'warn'], yok: ['—', ''] };
async function testTick(force) {
  const card = $('#test-card'); if (!card) return;
  if (!force && !(S.tests && S.tests.calisiyor)) return;
  let r; try { r = await api('/api/testler'); } catch (e) { return; }
  const sig = JSON.stringify(r);
  if (!force && S.sig.tests === sig) return;
  S.sig.tests = sig; S.tests = r;
  card.style.display = r.sonuclar.length ? '' : 'none';
  const o = r.ozet, run = r.calisiyor;
  const stName = x => T((TEST_ST[x] || [x])[0]);
  const showOut = x => modal({ title: x.ad, sub: stName(x.durum) + (x.sure_sn != null ? ' · ' + T('{0} sn', x.sure_sn) : ''), wide: true,
    body: h('div', { class: 'log-view', style: { maxHeight: '60vh' } }, (x.cikti || [T('Çıktı yok.')]).map(l => h('div', { class: /Error|Traceback|assert/i.test(l) ? 'e' : '' }, l))) });
  card.replaceChildren(
    h('div', { class: 'row between wrap' }, h('h2', null, icon('check'), T('Testler')),
      h('div', { class: 'row wrap' },
        r.bitis && !run ? h('span', { class: 'small muted' }, T('{0} geçti · {1} kaldı · {2}', o.gecti, o.kaldi, fmtDur(r.bitis - r.baslangic))) : null,
        run ? btn(T('Durdur'), () => act(() => api('/api/testler/durdur', {})).then(() => testTick(true)), 'danger sm', 'stop')
          : btn(T('Hepsini çalıştır'), () => act(() => api('/api/testler/calistir', {})).then(() => testTick(true)), 'primary sm', 'play'),
        !run && o.kaldi ? btn(T('Kalanları yeniden'), () => act(() => api('/api/testler/calistir', { adlar: r.sonuclar.filter(x => x.durum === 'kaldi' || x.durum === 'zaman_asimi').map(x => x.ad) })).then(() => testTick(true)), 'sm', 'refresh') : null)),
    h('p', { class: 'desc' }, T('Sunucunun birim ve bütünleşik testleri; her dosya ayrı süreçte çalışır (oyun açıkken de çalışır, yalnız işlemciyi paylaşır). Bir satıra tıklayınca çıktısı açılır.')),
    h('div', { class: 'test-list' }, r.sonuclar.map(x => {
      const cls = (TEST_ST[x.durum] || [x.durum, ''])[1];
      return h('div', { class: 'test-row' + (x.cikti ? ' click' : ''), onclick: x.cikti ? () => showOut(x) : null, title: x.ozet || null },
        x.durum === 'calisiyor' ? h('span', { class: 'spin' }) : dot(cls), h('span', { class: 'mono' }, x.ad.replace(/^test_|[.]py$/g, '')),
        h('span', { class: 'small muted ellipsis' }, x.ozet || ''), h('span', { class: 'spacer' }),
        x.sure_sn != null ? h('span', { class: 'small dim' }, T('{0} sn', x.sure_sn)) : null, badge(stName(x.durum), cls));
    })));
}

function renderServerCards() {
  const box = $('#srv-cards'), d = S.durum; if (!box || !d) return;
  const s = d.surecler, sig = JSON.stringify([s, d.oyna.calisiyor, Math.floor(Date.now() / 10000)]);
  if (S.sig.srv === sig) return; S.sig.srv = sig;
  const busy = d.oyna.calisiyor, cl = s.istemci.durum === 'acik';
  const card = (title, ic, st, ports, extra, actions) => h('div', { class: 'card status-card' },
    h('div', { class: 'big' }, icon(ic), title), h('div', { class: 'row', style: { marginTop: '8px' } }, dot(stCls(st.durum)), h('b', null, stText(st.durum)),
      st.pid ? h('span', { class: 'muted small' }, `PID ${st.pid} · ${fmtDur(st.sure_sn)}`) : null, st.cikis_kodu != null && st.durum === 'coktu' ? badge(T('çıkış {0}', st.cikis_kodu), 'err') : null),
    ports ? h('div', { class: 'ports' }, Object.entries(ports).map(([p, on]) => badge(on ? T('{0} dinliyor', p) : T('{0} kapalı', p), on ? 'ok' : ''))) : h('div', { style: { height: '12px' } }),
    extra, h('div', { class: 'actions' }, actions));
  const w = s.sunucular.web, o = s.sunucular.oyun, srvOn = w.durum === 'acik' || o.durum === 'acik';
  box.replaceChildren(
    card(T('Web sunucusu'), 'link', w, w.portlar, h('div', { class: 'small muted' }, T('İstemcinin web girişi, harita listesi, dil seçimi.')), [btn(T('Günlük'), () => showLog('http.log'), 'sm'), btn(T('Konsol'), () => showLog('web_konsol.log'), 'ghost sm')]),
    card(T('Oyun sunucusu'), 'server', o, o.portlar, h('div', { class: 'small muted' }, s.kayit ? T('Kayıt: {0}', s.kayit) + (s.kontrol_kanali ? ' · ' + T('kontrol kanalı açık (8099)') : '') : T('Oyun dünyası, kayıt, sohbet (7771).')),
      [srvOn ? btn(T('Durdur'), () => act(() => api('/api/sunucu/durdur', {}), T('Durduruldu.')), 'danger sm', 'stop', { disabled: cl || busy, title: cl ? T('Önce oyunu kapatın') : '' })
        : btn(T('Başlat'), () => act(() => api('/api/oyna', { sadece_sunucu: true })), 'primary sm', 'play', { disabled: busy }),
      btn(T('Yeniden başlat'), () => act(() => api('/api/sunucu/yeniden', {}), T('Yeniden başlatıldı.')), 'sm', 'refresh', { disabled: busy || !srvOn, title: T('Oyun açıksa istemci yeniden bağlanmalı') }),
      btn(T('Günlük'), () => showLog('gs.log'), 'ghost sm'), btn(T('Konsol'), () => showLog('oyun_konsol.log'), 'ghost sm')]),
    card(T('İstemci'), 'monitor', s.istemci, null, h('div', { class: 'small muted' }, s.istemci.son ? T('Son kapanış {0} · {1} açık kaldı', s.istemci.son.zaman, fmtDur(s.istemci.son.sure_sn)) : T('Orijinal Unity istemcisi.')),
      [cl ? btn(T('Kapat'), async () => { if (await confirmBox(T('İstemci kapatılsın mı?'), T('Oyun penceresi kapatılır.'), { ok: T('Kapat'), danger: true })) act(() => api('/api/istemci/kapat', {})); }, 'danger sm', 'power')
        : btn(T('Oyna'), () => { go('oyna'); act(() => api('/api/oyna', {})); }, 'orange sm', 'play', { disabled: busy }),
      btn(T('Günlük'), () => showLog('client.log'), 'ghost sm')]));
}

async function checkPorts() {
  const box = $('#port-list'); if (!box) return;
  box.replaceChildren(h('div', { class: 'row muted small' }, h('span', { class: 'spin' }), T('Denetleniyor…')));
  const r = await act(() => api('/api/portlar')); if (!r) { box.replaceChildren(); return; }
  box.replaceChildren(r.length ? h('div', { class: 'stack', style: { gap: '8px', marginBottom: '12px' } }, r.map(p => h('div', { class: 'alert ' + (p.bizim ? 'uyari' : 'hata') }, icon('alert'),
    h('div', null, h('b', null, `${p.port} (${p.ad})`), ` — ${p.surec} (PID ${p.pid ?? '?'})`, h('div', { class: 'mono dim', style: { marginTop: '3px' } }, p.komut || ''),
      p.bizim ? h('div', { class: 'small' }, T('Bu projenin önceki oturumdan kalan sunucusu.')) : h('div', { class: 'small' }, T('Başka bir program: panel kapatmaz; kendiniz kapatın.'))),
    p.bizim ? btn(T('Kapat'), () => act(() => api('/api/portlar/kapat', { pid: p.pid }), T('Süreç kapatıldı.')).then(() => checkPorts()), 'sm', 'x') : null)))
    : h('div', { class: 'row small', style: { marginBottom: '12px', color: 'var(--ok)' } }, icon('check'), T('Panel dışında portları tutan süreç yok.')));
}

function showLog(name) { logState.ad = name; loadLog(); const v = $('#log-view'); if (v) v.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
async function loadLog(quiet) {
  const view = $('#log-view'); if (!view) return;
  let r;
  try { r = await api('/api/gunluk?ad=' + encodeURIComponent(logState.ad) + '&satir=' + logState.satir); } catch (e) { if (!quiet) toast(e.message, 'err'); return; }
  const tabs = $('#log-tabs');
  if (tabs) tabs.replaceChildren(...r.liste.map(g => h('button', { class: 'btn sm ' + (g.ad === logState.ad ? 'primary' : 'ghost'), onclick: () => { logState.ad = g.ad; loadLog(); } },
    g.ad, g.boyut != null ? h('span', { class: 'dim', style: { fontWeight: 400 } }, fmtBytes(g.boyut)) : null)));
  const atBottom = view.scrollHeight - view.scrollTop - view.clientHeight < 40;
  const f = logState.filtre.toLowerCase();
  const lines = r.satirlar.filter(l => !f || l.toLowerCase().includes(f));
  const sig = logState.ad + '|' + f + '|' + lines.length + '|' + (lines[lines.length - 1] || '');
  if (quiet && view.dataset.sig === sig) return;
  view.dataset.sig = sig;
  view.replaceChildren(...(r.var ? lines.map(l => {
    const low = l.toLowerCase();
    const cls = /error|hata|traceback|exception|çöktü|failed/.test(low) ? 'e' : /uyar|warn|yanıtsız/.test(low) ? 'w' : /^\d\d:\d\d:\d\d -> /.test(l) ? 'i' : '';
    return h('div', { class: cls }, l);
  }) : [h('div', { class: 't' }, T('Bu günlük henüz yok.'))]));
  if (atBottom || !quiet) view.scrollTop = view.scrollHeight;
}

// ================================================================== PANEL
const DIL_ADLARI = { tr: 'Türkçe', en: 'English' };
// ---- güncellemeler (guncelleme.py, /api/guncelleme): GitHub'daki son sürüm, otomatik kurulum
const UPD_MODES = [['otomatik', N('Otomatik kur')], ['bildir', N('Yalnız haber ver')], ['kapali', N('Kapalı')]];
const UPD_TEXT = { guncel: N('Panel güncel.'), var: N('Yeni sürüm var.'), indiriliyor: N('Yeni sürüm indiriliyor…'), kuruluyor: N('Yeni sürüm kuruluyor…'),
  kuruldu: N('Yeni sürüm kuruldu: oyun ve sunucular kapalıysa panel şimdi yeniden başlar.'), bilinmiyor: N('Henüz denetlenmedi.'),
  yerel_degisiklik: N("GitHub'da yeni sürüm var, ama bu kopyada yerel değişiklikler var: güncellemeyi git ile al."),
  yerelde_ileri: N("Bu kopyada GitHub'a gönderilmemiş commit'ler var: kurulacak bir şey yok.") };
const fmtSurum = v => v && v.surum ? v.surum.slice(0, 7) + (v.tarih ? ' · ' + new Date(v.tarih).toLocaleString(LOC(), { dateStyle: 'medium', timeStyle: 'short' }) : '') : T('bilinmiyor');
function updCard() {
  const card = h('div', { class: 'card' }, h('h2', null, icon('refresh'), T('Güncellemeler')),
    h('p', { class: 'desc' }, T("Panel GitHub'daki son sürümü denetler ve yeniyse kurar. Kayıtların, ayarların ve oyun istemcisi değişmez; değişen dosyaların eski hâli yedeklenir.")),
    h('div', { class: 'upd-body' }));
  let sig = '';
  const draw = r => {
    const s = JSON.stringify(r); if (s === sig) return; sig = s;
    const body = card.querySelector('.upd-body'); if (!body) return;
    const run = r.calisiyor || ['indiriliyor', 'kuruluyor'].includes(r.durum);
    const cls = r.durum === 'hata' ? 'hata' : ['var', 'kuruldu', 'yerel_degisiklik'].includes(r.durum) ? 'uyari' : 'bilgi';
    const text = r.durum === 'hata' ? r.hata : r.calisiyor && r.durum !== 'indiriliyor' && r.durum !== 'kuruluyor' ? T('Denetleniyor…') : T(UPD_TEXT[r.durum] || r.durum);
    const pct = r.toplam ? Math.floor(100 * r.alinan / r.toplam) : null;
    const save = k => act(() => api('/api/panel_ayarlari', { degerler: { guncelleme: k } }), T('Kaydedildi.')).then(x => x && load());
    body.replaceChildren(h('div', null,                  // h() boşları atlar (replaceChildren null'ı metin yapar)
      h('div', { class: 'kv', style: { maxWidth: '620px' } },
        h('div', null, T('Kurulu sürüm'), h('b', null, fmtSurum(r.kurulu))),
        h('div', null, 'GitHub', h('b', null, r.son ? fmtSurum(r.son) : '—')),
        h('div', null, T('Kurulum biçimi'), h('b', null, r.kurulu.bicim === 'git' ? T('Git klonu (git ile ileri sarılır)') : T('İndirilmiş ZIP'))),
        h('div', null, T('Son denetim'), h('b', null, r.denetim ? fmtWhen(new Date(r.denetim * 1000).toISOString()) : '—'))),
      r.son && r.son.mesaj && r.durum === 'var' ? h('div', { class: 'small muted', style: { marginTop: '6px' } }, T('Son değişiklik: {0}', r.son.mesaj)) : null,
      h('div', { class: 'alert ' + cls, style: { marginTop: '12px' } }, icon(cls === 'bilgi' ? 'info' : 'alert'),
        h('div', null, text, r.durum === 'indiriliyor' ? ' ' + (pct != null ? pct + '% · ' : '') + fmtBytes(r.alinan) : '',
          r.durum === 'var' && !r.bosta ? h('div', { class: 'small' }, T('Oyun, sunucular ya da başka bir iş açık: kapanınca kurulabilir.')) : null)),
      r.durum === 'indiriliyor' && pct != null ? h('div', { class: 'meter', style: { marginTop: '8px' } }, h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } }))) : null,
      h('div', { class: 'stack', style: { gap: '12px', marginTop: '14px' } },
        field(T('Yeni sürüm çıkınca'), h('div', { class: 'seg' }, UPD_MODES.map(([k, t]) => h('button', { class: r.ayar === k ? 'on info' : '', onclick: () => r.ayar !== k && save(k) }, T(t))))),
        h('div', { class: 'row wrap' },
          btn(T('Şimdi denetle'), () => act(() => api('/api/guncelleme/denetle', {})).then(x => x && draw(x)), '', 'refresh', { disabled: run }),
          r.durum === 'var' ? btn(T('Güncellemeyi kur'), () => act(() => api('/api/guncelleme/kur', {})).then(x => x && draw(x)), 'primary', 'download', { disabled: !r.bosta }) : null,
          h('span', { class: 'small muted mono' }, r.depo)))));
  };
  const load = () => api('/api/guncelleme').then(draw).catch(() => {});
  load();
  S.timers.push(setInterval(() => { if (card.isConnected) load(); }, 2000));
  return card;
}

async function renderPanel() {
  const r = await act(() => api('/api/hakkinda')); if (!r || S.page !== 'panel') return;
  const pathRow = (label, p, ne) => h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, label), h('div', { class: 'help mono' }, p)),
    h('div', { class: 'ctl' }, ne ? btn(T('Aç'), () => act(() => api('/api/klasor_ac', { ne })), 'sm', 'folder') : null));
  const langSeg = h('div', { class: 'seg' }, Object.entries(DIL_ADLARI).map(([k, t]) => h('button', { class: I18N.lang === k ? 'on info' : '', onclick: async () => {
    if (k === I18N.lang) return;
    const x = await act(() => api('/api/panel_ayarlari', { degerler: { dil: k } })); if (x) location.reload();
  } }, t)));
  $('#content').replaceChildren(h('div', { class: 'stack' },
    h('div', { class: 'grid g2' },
      h('div', { class: 'card' }, h('h2', null, icon('globe'), 'Dil · Language'),
        h('p', { class: 'desc' }, T('Panelin dili. Değişince sayfa yenilenir; oyunun kendi dili giriş ekranında seçilir.')), langSeg),
      h('div', { class: 'card' }, h('h2', null, icon('wand'), T('Kurulum sihirbazı')),
        h('p', { class: 'desc' }, T('Dil, oyun klasörü, ilk pilot ve oyun ayarları adımlarını yeniden aç.')),
        btn(T('Sihirbazı aç'), () => openWizard(0), 'primary', 'wand'))),
    h('div', { class: 'card' }, h('h2', null, icon('users'), 'Discord'),
      h('p', { class: 'desc' }, T('Topluluk sunucusu: duyurular, yardım, hata bildirimi ve öneriler; Türkçe ve İngilizce kanallar.')),
      h('div', { class: 'row wrap' },
        btn(T("Discord'a katıl"), () => act(() => api('/api/discord', {}), T('Davet bağlantısı tarayıcıda açıldı.')), 'primary', 'users'),
        h('span', { class: 'small muted mono' }, r.discord))),
    updCard(),
    h('div', { class: 'grid g2' },
      h('div', { class: 'card' }, h('h2', null, icon('star'), T('Masaüstü kısayolu')),
        h('p', { class: 'desc' }, T('Masaüstüne OpenOrbit kısayolu koyar (DarkOrbit simgeli); çift tıklayınca bu panel açılır (konsol penceresi olmadan).')),
        r.eski_kisayol ? h('div', { class: 'alert bilgi', style: { marginBottom: '12px' } }, icon('info'),
          h('div', null, T('Masaüstündeki eski kısayol (DarkOrbit) kaldırılan başlatıcıyı açıyor. Kısayol oluştur yenisini koyar, eskisini kaldırır.'))) : null,
        btn(T('Kısayol oluştur'), async () => {
          if (await act(() => api('/api/kisayol', {}), x => T('Kısayol oluşturuldu: {0}', x.yol))) renderPanel();
        }, 'primary', 'plus')),
      h('div', { class: 'card' }, h('h2', null, icon('power'), T('Paneli kapat')),
        h('p', { class: 'desc' }, T('Panel ve panelin açtığı sunucular kapanır. Oyun açıksa önce oyunu kapat.')),
        btn(T('Paneli kapat'), async () => {
          if (await confirmBox(T('Panel kapatılsın mı?'), T('Panel ve açtığı sunucular kapanır.'), { ok: T('Kapat'), danger: true }))
            act(() => api('/api/kapat', {})).then(x => { if (x) { setTimeout(() => window.close(), 400); document.body.replaceChildren(h('div', { class: 'empty', style: { paddingTop: '30vh' } }, h('h3', null, T('Panel kapandı')), h('div', null, T('Bu pencereyi kapatabilirsin.')))); } });
        }, 'danger', 'power'))),
    h('div', { class: 'card' }, h('h2', null, icon('folder'), T('Klasörler')),
      pathRow(T('Proje'), r.kok, 'proje'), pathRow(T('Kayıt yuvaları'), r.kayitlar, 'kayitlar'), pathRow(T('Günlükler'), r.gunlukler, 'gunlukler'),
      pathRow(T('Oyun ayarları dosyası'), r.ayarlar), pathRow(T('Panel ayarları dosyası'), r.panel)),
    h('div', { class: 'card' }, h('h2', null, icon('info'), T('Hakkında')),
      h('div', { class: 'kv', style: { maxWidth: '520px' } }, h('div', null, T('Panel sürümü'), h('b', null, r.surum)), h('div', null, 'Python', h('b', null, r.python)),
        h('div', null, T('Panel adresi'), h('b', null, '127.0.0.1:' + r.port)), h('div', null, T('İnternet'), h('b', null, T('güncelleme, oyunu indirme ve oyun görselleri için')))),
      h('p', { class: 'desc', style: { marginTop: '14px' } }, T("OpenOrbit: tek oyunculu, çevrimdışı yerel sunucu. İstemci, grafikler ve metinler Bigpoint GmbH'ye aittir; yalnız kişisel kullanım içindir.")))));
}

// ================================================================== KURULUM SİHİRBAZI
// İlk açılışta (panel.json'da 'dil' ya da 'kurulum_tamam' yoksa) ve Panel sayfasından. Adımlar mevcut API'leri kullanır;
// sonunda 'kurulum_tamam' yazılır.
const WZ_STEPS = [['dil', N('Dil')], ['hosgeldin', N('Hoş geldin')], ['klasor', N('Oyun klasörü')], ['pilot', N('Pilot')], ['ayarlar', N('Oyun ayarları')], ['bitti', N('Hazır')]];
const WZ = { step: 0, draw: 0 };

function openWizard(step = 0) {
  closeWizard();
  Object.assign(WZ, { step, newPilot: false, created: null, preset: undefined, presetStart: undefined, display: null,
    shortcut: !S.panelCfg?.kurulum_tamam, dlAuto: false });
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
  root.classList.add('busy');                      // yüklenirken düğmeler kilitli (çift tıklama adım atlamasın)
  root.querySelectorAll('.wz-foot button, .wz-body button').forEach(b => { b.disabled = true; });
  let p;
  try { p = await WZ_PAGES[id](); } catch (e) { p = { title: T('Bir şeyler ters gitti'), content: h('div', { class: 'alert hata' }, icon('alert'), h('div', null, e.message)) }; }
  if (token !== WZ.draw || !$('#wizard')) return;
  root.classList.remove('busy');
  const done = !!S.panelCfg?.kurulum_tamam;
  const steps = h('div', { class: 'wz-steps' }, WZ_STEPS.map(([sid, ad], i) => h('span', { class: 'wz-step' + (i === WZ.step ? ' on' : i < WZ.step ? ' done' : '') },
    h('i', null, i < WZ.step ? '✓' : String(i + 1)), h('span', null, i === 0 ? 'Dil · Language' : T(ad)))));
  const next = p.next === null ? null : p.next || {};
  const nextBtn = next ? btn(next.label || T('İleri'), async ev => {
    const b = ev.currentTarget; b.disabled = true;
    let ok = true;
    try { if (next.fn) ok = await next.fn(); } finally { b.disabled = false; }
    if (ok) wzGo(WZ.step + 1);
  }, 'primary', next.icon || 'arrowR', { disabled: next.disabled }) : null;
  const foot = h('div', { class: 'wz-foot' },
    WZ.step > 0 || done ? btn(done ? T('Sihirbazı kapat') : T('Kurulumu atla'), () => skipWizard(), 'ghost sm') : null,
    h('span', { class: 'spacer' }),
    p.skip ? btn(T('Bu adımı atla'), () => wzGo(WZ.step + 1), 'ghost') : null,
    WZ.step > 0 ? btn(T('Geri'), () => wzGo(WZ.step - 1), '', 'arrowL') : null,
    p.extra || null, nextBtn);
  root.replaceChildren(h('div', { class: 'wz-box' },
    h('div', { class: 'wz-head' }, h('img', { src: 'simge.svg', alt: '' }),
      h('div', null, h('div', { class: 'wz-brand' }, 'OPENORBIT'), h('div', { class: 'wz-kicker' }, WZ.step === 0 ? 'Kurulum · Setup' : T('Kurulum'))), steps),
    h('div', { class: 'wz-body' }, h('h2', null, p.title), p.sub ? h('div', { class: 'wz-sub' }, p.sub) : null, p.content),
    foot));
  if (p.after) p.after();
  const f = root.querySelector('.wz-body input:not([type=checkbox])'); if (f) f.focus();
}

async function skipWizard() {
  const r = await act(() => api('/api/panel_ayarlari', { degerler: { kurulum_tamam: true } })); if (!r) return;
  S.panelCfg = r.ayarlar; closeWizard();
}
async function finishWizard(play) {
  const r = await act(() => api('/api/panel_ayarlari', { degerler: { kurulum_tamam: true } })); if (!r) return false;
  S.panelCfg = r.ayarlar;
  if (WZ.shortcut) await act(() => api('/api/kisayol', {}), x => T('Kısayol oluşturuldu: {0}', x.yol));
  closeWizard(); go('oyna');
  if (play) act(() => api('/api/oyna', {}));
  else toast(T('Kurulum tamam. İyi uçuşlar!'), 'ok');
  return false;
}
async function chooseLang(code) {
  const r = await act(() => api('/api/panel_ayarlari', { degerler: { dil: code } })); if (!r) return;
  S.panelCfg = r.ayarlar;
  await setLang(code);
  applyStatic(); buildNav(); go(S.page || 'oyna', false); renderChrome();
  wzGo(1);
}
function currentPreset(r) {
  const v = (vals, k) => vals[k] ?? r.varsayilan[k];
  return Object.keys(r.hazir).find(key => r.sema.every(s => v(r.degerler, s.anahtar) === v(r.hazir[key].degerler, s.anahtar))) || null;
}
const pick = (el, cls = 'on') => { el.parentNode.querySelectorAll(':scope > *').forEach(x => x.classList.remove(cls)); el.classList.add(cls); };

const WZ_PAGES = {
  // ---- 1. dil (iki dilde)
  dil: async () => {
    const cur = S.panelCfg?.dil;
    const card = (code, name, sub) => h('button', { class: 'wz-lang' + (cur === code ? ' on' : ''), type: 'button', onclick: () => chooseLang(code) },
      h('span', { class: 'code' }, code.toUpperCase()), h('b', null, name), h('span', null, sub));
    return { title: 'Dil seçin · Choose your language', sub: 'Panel bu dilde açılır; sonra Panel sayfasından değişir. · You can change it later on the Panel page.',
      content: h('div', { class: 'wz-langs' }, card('tr', 'Türkçe', 'Paneli Türkçe kullan'), card('en', 'English', 'Use the panel in English')),
      next: cur ? { label: T('İleri') } : null };
  },
  // ---- 2. hoş geldin
  hosgeldin: async () => ({
    title: T("OpenOrbit'e hoş geldin"),
    sub: T('Tek oyunculu, çevrimdışı DarkOrbit: orijinal oyun istemcisi bilgisayarındaki yerel sunucuya bağlanır.'),
    content: h('div', { class: 'stack' },
      h('div', { class: 'wz-list' }, [['folder', T('Oyun klasörünü seç'), T('Orijinal DarkOrbit istemcisinin kurulu olduğu klasör; bilgisayarında yoksa panel indirir.')],
        ['ship', T('İlk pilotunu oluştur'), T('Pilot adı ve firma: MMO, EIC ya da VRU.')],
        ['sliders', T('Oyun ayarlarını seç'), T('Hazır bir zorluk ve oyun penceresinin görüntüsü.')]].map(([ic, a, b], i) =>
        h('div', { class: 'wz-item' }, h('span', { class: 'wz-num' }, String(i + 1)), icon(ic), h('div', null, h('b', null, a), h('div', { class: 'muted small' }, b))))),
      h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Oyun resmî sunuculara bağlanmaz, istemci dosyaları değiştirilmez; internet yalnız oyunun görsellerini ilk gösterildiklerinde indirmek için kullanılır. Her şeyi sonra panelden değiştirebilirsin.')))),
    next: { label: T('Başla') },
  }),
  // ---- 3. oyun klasörü
  klasor: async () => {
    const r = await api('/api/istemci');
    const c = r.kontrol;
    let dl = r.indirme;
    const none = !c.gecerli && !r.adaylar.length;
    if (none && dl.durum === 'bos' && !WZ.dlAuto) {     // oyun bulunamadı: indirmeye kendiliğinden başla (yarım kaldıysa sürdür)
      WZ.dlAuto = true;
      dl = await act(() => api('/api/istemci/indir', {})) || dl;
    }
    if (c.gecerli && c.uyumlu && dl.calisiyor) {      // indirme sürerken uyumlu istemci bulundu ya da seçildi: indirme durur
      dl = await act(() => api('/api/istemci/indir_durdur', {}), T('İndirme durduruldu: bulunan istemci kullanılıyor.')) || dl;
    }
    const dlWrap = (!c.gecerli && (none || DL_ACTIVE(dl))) || (c.gecerli && (dl.calisiyor || dl.yarim)) ? h('div', { class: 'dl-wrap' }) : null;
    const bg = !c.gecerli && dl.calisiyor;
    let m = r.calistirici?.tur === 'motor' ? r.calistirici.motor : null;   // macOS: oyunu açacak Wine da kendiliğinden iner
    if (m && m.durum === 'yok' && !WZ.motorAuto) { WZ.motorAuto = true; m = await act(() => api('/api/motor/kur', {})) || m; }
    const mWrap = m ? h('div', { class: 'dl-wrap' }) : null;
    let y = c.gecerli && r.yama.gerekli ? r.yama : null;  // Windows: istemcinin düzeltmeleri için BepInEx de kendiliğinden kurulur
    if (y && y.durum === 'yok' && !WZ.yamaAuto) { WZ.yamaAuto = true; y = await act(() => api('/api/yama/kur', {})) || y; }
    const yWrap = y ? h('div', { class: 'dl-wrap' }) : null;
    const chosen = x => { if (x) drawWizard(); };
    const use = p => act(() => api('/api/istemci/kullan', { yol: p })).then(chosen);
    const browse = () => act(() => api('/api/istemci/sec', {}), x => x.iptal ? T('İptal edildi.') : T('Oyun klasörü seçildi.')).then(chosen);
    const rows = r.adaylar.map(a => h('button', { class: 'wz-opt' + (a.yol === c.yol ? ' on' : ''), type: 'button', onclick: () => use(a.yol) },
      h('span', { class: 'wz-radio' }), h('span', { class: 'mono' }, a.yol), badge(a.surum || '?', a.uyumlu ? 'ok' : 'warn')));
    return {
      title: T('DarkOrbit oyun klasörü'),
      sub: T("Orijinal DarkOrbit istemcisinin klasörü: içinde DarkOrbit.exe ve DarkOrbit_Data olmalı. Panel istemcinin kendi dosyalarını değiştirmez; Windows'ta yanına küçük düzeltmeler için BepInEx kurar."),
      content: [
        rows.length ? field(T('Bulunan klasörler'), h('div', { class: 'wz-opts' }, rows))
          : c.gecerli ? null : h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Bilgisayarında DarkOrbit bulunamadı, bu yüzden oyun indirilip proje klasörüne kuruluyor. Kurulu bir oyunun varsa klasörünü seç.'))),
        dlWrap,
        mWrap ? field(T('Oyunu açacak Wine (macOS)'), mWrap) : null,
        yWrap ? field(T('İstemci düzeltmeleri (BepInEx)'), yWrap) : null,
        bg ? h('div', { class: 'small muted' }, T('İndirme arka planda sürer: bu arada pilotunu oluşturabilirsin.')) : null,
        dlWrap ? null : field(T('Seçili klasör'), h('div', { class: 'path' }, c.yol || T('Seçilmedi'))),
        c.yol ? h('div', { class: 'check-list', style: { margin: 0 } }, checkRow(c.exe, 'DarkOrbit.exe'), checkRow(c.veri, T('DarkOrbit_Data klasörü')),
          c.gecerli ? checkRow(c.uyumlu, versionText(c, r.desteklenen), !c.uyumlu) : null) : null,
        c.gecerli && !c.uyumlu ? h('div', { class: 'alert uyari' }, icon('alert'), h('div', null, T('Bu istemci sunucunun protokolünden farklı bir sürüm. Oyun yine açılabilir; sorun olursa İstemci sayfasından yeni istemciyi uyarla.'))) : null,
        h('div', { class: 'row wrap' }, btn(T('Klasör seç…'), browse, rows.length || dlWrap ? '' : 'primary', 'folder'), btn(T('Yeniden ara'), () => drawWizard(), 'ghost', 'search'))],
      next: { disabled: !c.gecerli && !bg }, skip: !c.gecerli && !bg,
      after: () => {
        if (dlWrap) WZ.timer = dlWatch(dlWrap, dl, () => drawWizard(), { haveClient: c.gecerli });
        if (mWrap) motorWatch(mWrap, m);              // sihirbaz yeniden çizilince kutu kalkar, yenileme kendiliğinden durur
        if (yWrap) yamaWatch(yWrap, y);
      },
    };
  },
  // ---- 4. ilk pilot
  pilot: async () => {
    const r = await api('/api/kayitlar');
    if (r.liste.length && !WZ.newPilot) {
      const a = r.liste.find(k => k.aktif) || r.liste[0];
      return {
        title: WZ.created ? T('Pilotun hazır') : T('Pilot'),
        sub: WZ.created ? T('Kayıt oluşturuldu ve etkin yapıldı.') : T('Zaten {0} kaydın var: etkin kayıtla devam edebilir ya da yeni bir pilot oluşturabilirsin.', r.liste.length),
        content: [h('div', { class: 'card save-card active' },
          h('div', { class: 'head' }, h('div', { style: { minWidth: 0, flex: 1 } },
            h('div', { class: 'row', style: { gap: '8px' } }, h('span', { class: 'title' }, a.pilot), badge(a.firma || '?', firmaCls(a.firma)), badge(T('ETKİN'), 'info')),
            h('div', { class: 'sub' }, `${a.ad} · ${T('Seviye')} ${a.seviye ?? '?'} · ${a.gemi} · ${a.harita}`)))),
          r.liste.length > 1 ? h('div', { class: 'small muted' }, T('Etkin kaydı sonra Kayıtlar sayfasından değiştirebilirsin.')) : null,
          h('div', { class: 'row' }, btn(T('Yeni pilot oluştur'), () => { WZ.newPilot = true; drawWizard(); }, 'ghost', 'plus'))],
        next: {},
      };
    }
    const f = pilotForm({ start: false });
    return {
      title: T('İlk pilotunu oluştur'), sub: T('Yeni bir pilotla sıfırdan başlarsın. Firman başlangıç haritanı belirler; sonra değişmez.'),
      content: [...f.el, r.liste.length ? h('div', { class: 'row' }, btn(T('Vazgeç'), () => { WZ.newPilot = false; drawWizard(); }, 'ghost', 'undo')) : null],
      next: { label: T('Pilotu oluştur'), icon: 'plus', fn: async () => {
        const x = await act(() => api('/api/kayitlar/yeni', Object.assign(f.values(), { aktif_yap: true })), T('Pilot oluşturuldu.'));
        if (!x) return false;
        WZ.created = x.id; WZ.newPilot = false; poll();
        return true;
      } },
    };
  },
  // ---- 5. oyun ayarları: hazır ayar ve oyun penceresi
  ayarlar: async () => {
    const [r, c] = await Promise.all([api('/api/ayarlar'), api('/api/istemci')]);
    if (WZ.presetStart === undefined) { WZ.presetStart = currentPreset(r); WZ.preset = WZ.presetStart; }
    const cfg = c.ayarlar;
    if (!WZ.display) WZ.display = { pencere_modu: cfg.pencere_modu, genislik: cfg.genislik, yukseklik: cfg.yukseklik };
    const presets = h('div', { class: 'preset-bar' }, Object.entries(r.hazir).map(([key, p]) => h('button', { class: 'preset' + (WZ.preset === key ? ' on' : ''), type: 'button',
      onclick: e => { WZ.preset = key; pick(e.currentTarget); } }, h('b', null, p.ad), h('span', null, p.aciklama))));
    const mode = h('div', { class: 'seg' }, WINDOW_MODES.map(([k, t]) => h('button', { class: WZ.display.pencere_modu === k ? 'on info' : '', type: 'button',
      onclick: e => { WZ.display.pencere_modu = k; e.currentTarget.parentNode.querySelectorAll('button').forEach(b => b.className = ''); e.currentTarget.className = 'on info'; } }, T(t))));
    const { res, scr } = resolutionList(c);
    const cur = `${WZ.display.genislik}x${WZ.display.yukseklik}`;
    if (!res.includes(cur)) res.push(cur);
    const sel = h('select', { class: 'input', onchange: e => { const [w, hh] = e.target.value.split('x').map(Number); WZ.display.genislik = w; WZ.display.yukseklik = hh; } },
      res.map(x => h('option', { value: x, selected: x === cur }, x + (x === scr ? '  (' + T('ekran') + ')' : ''))));
    return {
      title: T('Oyun ayarları'), sub: T('Bir hazır ayar seç ve oyun penceresini ayarla. Bütün ayarlar (hasar, ödül çarpanları, etkinlikler …) sonra Oyun Ayarları sayfasında.'),
      content: [field(T('Zorluk ve ödüller'), presets),
        WZ.presetStart === null ? h('div', { class: 'small muted' }, T('Şu anki ayarların hazır ayarlardan farklı; birini seçmezsen değişmez.')) : null,
        h('hr', { class: 'sep', style: { margin: '2px 0' } }),
        h('div', { class: 'grid g2' }, field(T('Pencere kipi'), mode), field(T('Çözünürlük'), sel))],
      next: { fn: async () => {
        if (WZ.preset && WZ.preset !== WZ.presetStart) {
          if (!await act(() => api('/api/ayarlar/hazir', { ad: WZ.preset }))) return false;
          WZ.presetStart = WZ.preset;
        }
        return !!await act(() => api('/api/panel_ayarlari', { degerler: WZ.display }));
      } },
    };
  },
  // ---- 6. özet
  bitti: async () => {
    const [d, c, a] = await Promise.all([api('/api/durum'), api('/api/istemci'), api('/api/ayarlar')]);
    const k = c.kontrol, cfg = c.ayarlar, pre = currentPreset(a);
    const canPlay = !!d.aktif && k.gecerli;
    const dlRun = !k.gecerli && c.indirme.calisiyor;
    const mode = (WINDOW_MODES.find(([x]) => x === cfg.pencere_modu) || [, cfg.pencere_modu])[1];
    const rows = [[true, T('Dil'), DIL_ADLARI[I18N.lang]],
      [k.gecerli, T('Oyun klasörü'), k.gecerli ? k.yol + (k.surum ? ' · ' + k.surum : '') : dlRun ? T('İndiriliyor: %{0} (İstemci sayfasında izleyebilirsin)', dlPct(c.indirme)) : T('Seçilmedi: İstemci sayfasından seç.')],
      [!!d.aktif, T('Pilot'), d.aktif ? `${d.aktif.pilot} · ${d.aktif.firma}` : T('Oluşturulmadı: Kayıtlar sayfasından oluştur.')],
      [true, T('Oyun ayarları'), pre ? a.hazir[pre].ad : T('Özel')],
      [true, T('Oyun penceresi'), `${T(mode)} · ${cfg.genislik}×${cfg.yukseklik}`]];
    const sc = h('input', { type: 'checkbox', checked: WZ.shortcut, onchange: e => { WZ.shortcut = e.target.checked; } });
    return {
      title: canPlay ? T('Her şey hazır') : T('Neredeyse hazır'),
      sub: canPlay ? T("OYNA'ya basınca sunucular başlar ve oyun açılır.") : dlRun ? T('Oyun inince Oyna sayfasından başlatabilirsin.') : T('Eksik adımları sonra panelden tamamlayabilirsin.'),
      content: [h('div', { class: 'wz-summary' }, rows.map(([ok, t, v]) => h('div', { class: ok ? 'ok' : 'wr' }, icon(ok ? 'check' : 'alert'), h('span', null, t), h('b', { title: v }, v)))),
        h('label', { class: 'row small' }, h('span', { class: 'switch' }, sc, h('span')), T('Masaüstüne OpenOrbit kısayolu koy'))],
      extra: canPlay ? btn(T('Yalnız bitir'), () => finishWizard(false), '') : null,
      next: { label: canPlay ? T('Bitir ve oyna') : T('Bitir'), icon: canPlay ? 'play' : 'check', fn: () => finishWizard(canPlay) },
    };
  },
};

const RENDER = { oyna: renderOyna, oyuncular: renderOyuncular, arkadas: renderArkadas, kayitlar: renderKayitlar, ayarlar: renderAyarlar, etkinlikler: () => renderEtkinlikler(), istemci: () => renderIstemci(),
  takvim: enterTakvim, sunucu: renderSunucu, panel: renderPanel };

// ------------------------------------------------------------------ başlangıç
async function boot() {
  let cfg = null;
  try { cfg = await api('/api/panel_ayarlari'); } catch (e) { /* panel kapalı: poll bildirir */ }
  S.panelCfg = cfg;
  const guess = (navigator.language || '').toLowerCase().startsWith('tr') ? 'tr' : 'en';
  await setLang((cfg && cfg.dil) || guess);
  applyStatic();
  buildNav();
  go(location.hash.slice(1) || 'oyna', false);
  poll();
  if (cfg && (!cfg.dil || !cfg.kurulum_tamam)) openWizard(cfg.dil ? 1 : 0);
}
boot();
