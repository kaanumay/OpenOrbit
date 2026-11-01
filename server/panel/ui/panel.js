/* OpenOrbit yerel sunucu paneli — arayüz (panel.py'nin /api/... uçları). Dış kitaplık yok.
   Dil: metinler Türkçe yazılır, T() seçili dildeki hâlini verir (<kod>.json, yoksa en.json; Python tarafıyla ortak, lang.py).
   İlk açılışta kurulum sihirbazı: dil, oyun klasörü, ilk pilot, oyun ayarları (panel.json 'dil', 'kurulum_tamam'). Oyun
   bilgisayarda bulunamazsa oyun klasörü adımı onu indirmeye başlar (client_download.py; İstemci sayfasından da). Panel GitHub'daki yeni
   sürümü kurup yeniden başlayınca (updater.py) belirteç değişir: sayfa kendini yeniler. */
'use strict';
const TOKEN = document.querySelector('meta[name="panel-token"]').content;
const $ = (s, r = document) => r.querySelector(s);

// ------------------------------------------------------------------ dil
// diller: /api/diller (lang.py DILLER); sözlükte olmayan metin İngilizceye, o da yoksa Türkçeye düşer
const I18N = { lang: 'tr', dict: {}, en: {}, list: [{ code: 'tr', ad: 'Türkçe', yerel: 'tr-TR', coverage: 100 }, { code: 'en', ad: 'English', yerel: 'en-US', coverage: 100 }] };
function T(s, ...a) {
  let r = I18N.dict[s] ?? I18N.en[s] ?? s;
  if (a.length) r = r.replace(/\{(\d+)\}/g, (m, i) => a[+i] == null ? '' : String(a[+i]));
  return r;
}
const langOf = k => I18N.list.find(x => x.code === k);
const LOC = () => langOf(I18N.lang)?.yerel || 'tr-TR';
const loadDict = async k => { try { return await (await fetch(k + '.json', { cache: 'no-store' })).json(); } catch (e) { return {}; } };
async function setLang(lang) {
  I18N.lang = langOf(lang) ? lang : 'tr';
  I18N.en = I18N.lang === 'tr' ? {} : await loadDict('en');
  I18N.dict = ['tr', 'en'].includes(I18N.lang) ? {} : await loadDict(I18N.lang);
  document.documentElement.lang = LOC();
}
// tarayıcının dillerinden panelde olan ilki (pt-BR -> pt); yoksa İngilizce
const guessLang = () => (navigator.languages || [navigator.language || '']).map(x => x.toLowerCase().split('-')[0]).find(langOf) || 'en';
function applyStatic() {
  const sub = $('#brand-sub'); if (sub) sub.textContent = T('Yerel Sunucu Paneli');
  // kenar çubuğunun en altında destek bağlantısı (Buy Me a Coffee; varsayılan tarayıcıda açılır: /api/bagis)
  const coffee = $('#kahve');
  if (!coffee) return;
  const open_ = () => act(() => api('/api/donate', {}));
  const button = h('button', { class: 'kahve', type: 'button', title: 'buymeacoffee.com/kaanumay', onclick: open_ }, art('dron_kahve', 'coffee-drone'),
    h('span', null, h('b', null, T('Bana bir kahve ısmarla')), h('small', null, T("OpenOrbit'i destekle"))));
  coffee.replaceChildren(button);
  // altında son destekçiler sola kayarak geçer (sayfadaki Recent supporters; çevrimdışıysa liste boş gelir, şerit hiç çıkmaz)
  api('/api/supporters').then(d => {
    if (!d.adlar || !d.adlar.length || !button.isConnected) return;   // dil değişince applyStatic yeniden kurduysa eskisi eklenmesin
    const group = () => h('span', { class: 'coffee-group' }, d.adlar.map(a => h('span', null, a)));
    const duration = Math.max(12, d.adlar.join('').length * 0.45 + d.adlar.length * 2);   // ad sayısı arttıkça hız sabit kalsın
    coffee.append(h('button', { class: 'coffee-strip', type: 'button', title: T('Son destekçiler'), 'aria-label': T('Son destekçiler') + ': ' + d.adlar.join(', '), onclick: open_ },
      h('span', { class: 'coffee-marquee', style: { animationDuration: duration + 's' } }, group(), group())));
  }).catch(() => {});
}

// ------------------------------------------------------------------ simgeler (24x24, çizgi)
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
const btn = (label, onclick, cls = '', iconEl = null, props = {}) =>
  h('button', Object.assign({ class: 'btn ' + cls, onclick, type: 'button' }, props), iconEl ? icon(iconEl) : null, label ? h('span', null, label) : null);
const badge = (text, cls = '') => h('span', { class: 'badge ' + cls }, text);
const dot = cls => h('span', { class: 'dot ' + (cls || '') });
const art = (name, cls = 'art') => h('img', { class: cls, src: 'images/' + name + '.webp', sub: '' });   // arayuz/images/ (Orders.md)
const N = s => s;     // çevrilecek metin işareti: değişkende durur, T() ile gösterilir (test_panel_lang.py toplar)
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
  { id: 'arkadas', ad: N('Arkadaşlarınla Oyna'), ic: 'users', sub: N('Sunucu kur (Host) ya da arkadaşının sunucusuna katıl (Join). Herkes kendi kaydıyla oynar.') },
  { id: 'kayitlar', ad: N('Kayıtlar'), ic: 'save', sub: N('Kayıt yuvaları, yedekler, kopyalama, içe ve dışa aktarma.') },
  { id: 'ayarlar', ad: N('Oyun Ayarları'), ic: 'sliders', sub: N('Çarpanlar ve kurallar. Kendiliğinden kaydedilir; çoğu oyun açıkken anında uygulanır.') },
  { id: 'dunya', ad: N('Dünya Editörü'), ic: 'globe', sub: N('Haritaları, uzaylıları, görevleri, mağazayı ve açık artırmayı değiştir; kendi dünyalarını oluştur.') },
  { id: 'botlar', ad: N('Botlar'), ic: 'bot', beta: true, sub: N('Gerçek oyuncu gibi gelişen, konuşan ve klan kuran botlar: paket oluştur, bir dünyaya ata.') },
  { id: 'etkinlikler', ad: N('Etkinlikler'), ic: 'calendar', sub: N('Her etkinlik takvime göre ya da elle açık / kapalı.') },
  { id: 'takvim', ad: N('Etkinlik Takvimi'), ic: 'agenda', sub: N('Etkinlikler ve seansları saatlik, günlük, haftalık ve aylık görünümde (yerel saat).') },
  { id: 'istemci', ad: N('İstemci'), ic: 'monitor', sub: N('Oyun klasörü, sürüm denetimi ve görüntü seçenekleri.') },
  { id: 'sunucu', ad: N('Sunucu'), ic: 'server', sub: N('Sunucu süreçleri, portlar, davranış ve günlükler.') },
  { id: 'panel', ad: N('Panel'), ic: 'info', sub: N('Dil, kurulum sihirbazı, güncellemeler, masaüstü kısayolu, klasörler ve panel hakkında.') },
  // oyun içi menüler: kenar çubuğunun ayrı bölümünde, yalnız oyun açıkken (panel_channel.py); simge oyunun kendi görseli (sprite)
  // sıra sayfaların üstündeki sekmelerle aynı (OYUN_SAYFALARI)
  { id: 'magaza', ad: N('Mağaza'), ic: 'cart', sprite: 'shop_normal', oyun: true, sub: N('Oyundaki mağaza: aldığın eşya oyuna anında gelir.') },
  { id: 'hangar', ad: N('Hangar'), ic: 'hangar', sprite: 'hangar_normal', oyun: true, sub: N('Gemilerin ve donanımları: tıkladığın eşya takılır ya da çıkarılır, oyunda da anında değişir.') },
  { id: 'skylab', ad: N('Skylab'), ic: 'lab', sprite: 'skylab_normal', oyun: true, sub: N('Modüller, üretim, depo ve gemiye taşıma; oyundaki Skylab ile aynı.') },
  { id: 'muzayede', ad: N('Açık Artırma'), ic: 'gavel', sprite: 'auction_normal', oyun: true, sub: N('Teklif ver, hepsine katıl, otomatik teklif ve alarm kur; panel kapalıyken de oyunda işler.') },
];
const S = { durum: null, page: null, sig: {}, timers: [] };

function buildNav() {
  const nav = $('#nav');
  const navBtn = p => h('button', { 'data-page': p.id, class: p.id === S.page ? 'active' : null, onclick: () => go(p.id) },
    p.oyun && GI.index?.sprite[p.sprite] ? sprite(p.sprite, 18) : icon(p.ic),
    h('span', null, T(p.ad)), p.beta ? h('span', { class: 'beta-label' }, 'Beta') : null,
    h('span', { class: 'badge', id: 'nav-badge-' + p.id, style: { display: 'none' } }));
  nav.replaceChildren(...PAGES.filter(p => !p.oyun).map(navBtn),
    h('div', { class: 'nav-game', id: 'nav-game', style: { display: 'none' } }, h('div', { class: 'nav-title' }, T('Oyun içi')),
      PAGES.filter(p => p.oyun).map(navBtn)));
}
function go(id, push = true) {
  if (!PAGES.find(p => p.id === id)) id = 'oyna';
  S.timers.forEach(clearInterval); S.timers = [];
  S.page = id; S.sig = {}; document.body.dataset.page = id;      // sayfa başlığının sahnesi (panel.css .topbar)
  if (push && location.hash !== '#' + id) history.replaceState(null, '', '#' + id);
  document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('active', b.dataset.page === id));
  const p = PAGES.find(x => x.id === id);
  $('#page-title').replaceChildren(T(p.ad), ...(p.beta ? [h('span', { class: 'beta-label' }, 'Beta')] : [])); $('#page-sub').textContent = T(p.sub);
  $('#content').replaceChildren(h('div', { class: 'empty' }, h('div', { class: 'spin', style: { margin: '30px auto' } })));
  RENDER[id]();
}
window.addEventListener('hashchange', () => go(location.hash.slice(1), false));

function srvState(d) {
  const s = d?.processes; if (!s) return { web: 'kapali', oyun: 'kapali', istemci: 'kapali' };
  return { web: s.servers.web.durum, oyun: s.servers.oyun.durum, istemci: s.istemci.durum };
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
    const extras = d.coklu?.clients?.length;
    if (extras) kids.push(h('span', { class: 'pill', style: { cursor: 'pointer' }, onclick: () => go('oyna') }, icon('monitor'), T('{0} ek istemci', extras)));
    const friends = d.arkadas || {};
    if (friends.host || FRD_ACTIVE(friends.misafir)) kids.push(h('span', { class: 'pill', style: { cursor: 'pointer' }, onclick: () => go('arkadas') }, icon('users'),
      friends.host ? T('Arkadaş sunucusu açık') : T('Arkadaşın sunucusunda:') + ' ', friends.host ? null : h('b', null, friends.adres)));
  }
  tr.replaceChildren(...kids);
  const navGame = $('#nav-game'), gameOpen = st.oyun === 'acik' && st.istemci === 'acik';
  if (navGame) navGame.style.display = gameOpen ? '' : 'none';
  // oyun kapanınca oyun içi sayfadaki kullanıcı Oyna sayfasına döner (sayfanın verisi oyun sunucusundan)
  if (d && !gameOpen && PAGES.find(p => p.id === S.page)?.oyun) {
    if (S.game_was_open) toast(T('Oyun kapandı: Oyna sayfasına dönüldü.'), 'info');
    go('oyna');
  }
  S.game_was_open = gameOpen;
  const setBadge = (id, text, cls) => {
    const b = $('#nav-badge-' + id); if (!b) return;
    b.style.display = text ? '' : 'none'; b.textContent = text || ''; b.className = 'badge ' + (cls || '');
  };
  if (d) {
    setBadge('kayitlar', d.save_count ? String(d.save_count) : '', '');
    setBadge('etkinlikler', d.etkinlikler.length ? String(d.etkinlikler.length) : '', 'orange');
    const errs = d.warnings.filter(u => u.tur === 'hata').length;
    setBadge('sunucu', st.oyun === 'coktu' || st.web === 'coktu' ? '!' : '', 'err');
    setBadge('oyna', errs ? '!' : '', 'err');
    setBadge('ayarlar', d.settings_summary.length ? String(d.settings_summary.length) : '', 'info');
  }
}

async function poll() {
  try { S.durum = await api('/api/durum'); S.offline = false; } catch (e) { S.offline = true; }
  if (S.durum?.panel?.updated && S.durum.panel.uptime_sec < 60 && !S.updToast) { S.updToast = true; toast(T('Panel güncellendi ve yeniden başladı.'), 'ok'); }
  renderChrome();
  if (S.page === 'oyna') { renderPlayBody(); liveTick(); }
  if (S.page === 'sunucu') renderServerCards();
  if (S.page === 'arkadas' && FRD.veri) friendsTick();
  poll.n = (poll.n || 0) + 1;
  if (poll.n % 3 === 0) auctionEventTick();      // açık artırma bildirimleri (~5 sn)
  setTimeout(poll, S.durum?.oyna?.calisiyor ? 500 : 1500);
}
window.addEventListener('pagehide', () => navigator.sendBeacon && navigator.sendBeacon('/api/kapandi', '{}'));

// ================================================================== OYNA
function renderPlay() { S.sig = {}; $('#content').replaceChildren(h('div', { class: 'stack', id: 'oyna' })); renderPlayBody(); }

function renderPlayBody() {
  const d = S.durum, root = $('#oyna');
  if (!root) return;
  if (!d) return;
  const sig = JSON.stringify([d.aktif, d.processes.servers.web.durum, d.processes.servers.oyun.durum, d.processes.istemci.durum,
    d.processes.istemci.son, d.oyna, d.warnings, d.settings_summary, d.etkinlikler, multiSig(d.coklu), S.multiBusy, Math.floor(Date.now() / 30000)]);
  if (S.sig.oyna === sig) return;
  S.sig.oyna = sig;
  const st = srvState(d), a = d.aktif, o = d.oyna;
  const running = st.istemci === 'acik', srv = st.oyun === 'acik';
  const blocking = d.warnings.filter(u => u.tur === 'hata');
  const clientMissing = blocking.some(u => u.page === 'istemci');

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
      h('div', { class: 'pilot' }, firmaCls(a.firma) ? art('firma_' + firmaCls(a.firma), 'crest-sm') : null, a.pilot, badge(a.firma, firmaCls(a.firma)), a.klan ? badge('[' + a.klan + ']', 'info') : null),
      h('div', { class: 'meta' },
        [[T('Seviye'), a.seviye], [T('Gemi'), a.gemi], [T('Harita'), a.harita], [T('Oynama'), fmtDur(a.play_sec)],
          [T('Son oynama'), fmtWhen(a.last_played || a.last_save)]].map(([k, v]) => h('span', null, k + ' ', h('b', null, v)))),
      a.world_info ? playWorldChip(a) : null,                    // kaydın varsayılan dünyası (world_editor.js)
      h('div', { class: 'stats' },
        [[T('Kredi'), a.kredi, 'cr'], [T('Uridyum'), a.uridyum, 'ur'], [T('Onur'), a.onur, 'hn'], [T('Deneyim'), a.ep, 'ep']].map(([k, v, c]) =>
          h('div', { class: 'stat' }, h('div', { class: 'k' }, k), h('div', { class: 'v ' + c }, fmtN(v))))));
  }
  let main, sub = [];
  if (o.calisiyor) {
    const prep = o.adimlar.length && o.adimlar[o.adimlar.length - 1].ilerleme;      // BepInEx'in ilk açılış hazırlığı (istemci_yama.isit)
    main = h('button', { class: 'play-btn busy' + (prep ? ' prep' : ''), disabled: true, style: prep ? { '--p': prep.yuzde + '%' } : null },
      prep ? null : h('span', { class: 'spin', style: { borderTopColor: '#021120' } }), prep ? T('HAZIRLANIYOR') : T('BAŞLATILIYOR'));
  } else if (running) {
    main = h('button', { class: 'play-btn running', disabled: true }, icon('check'), T('OYUN AÇIK'));
    sub.push(btn(T('Oyunu kapat'), async () => {
      if (await confirmBox(T('Oyun kapatılsın mı?'), T('İstemci kapatılır. Kaydın sunucuda tutuluyor; oyundan çıkış düğmesiyle çıkmak daha güvenlidir.'),
        { ok: T('Kapat'), danger: true })) act(() => api('/api/istemci/kapat', {}));
    }, 'danger sm', 'power'));
  } else {
    main = h('button', { class: 'play-btn', disabled: !a || clientMissing, onclick: () => act(() => api('/api/oyna', {})) }, icon('play'), T('OYNA'));
    if (srv) sub.push(btn(T('Sunucuyu durdur'), () => act(() => api('/api/sunucu/durdur', {}), T('Sunucular durduruldu.')), 'ghost sm', 'stop'));
    else sub.push(btn(T('Yalnız sunucuyu başlat'), () => act(() => api('/api/oyna', { server_only: true })), 'ghost sm', 'server', { disabled: !a }));
  }
  const playCol = h('div', { class: 'play-col' }, main, h('div', { class: 'play-sub' }, sub),
    a ? h('div', { class: 'small muted' }, running ? (S.panelCfg?.istemci_kapaninca === 'acik' || d.coklu?.clients?.length ? T('İyi uçuşlar! Oyunu kapatınca sunucular açık kalır.')
      : T('İyi uçuşlar! Oyunu kapatınca sunucular kapanır.')) : srv ? T('Sunucu açık: OYNA istemciyi açar.') : T('Sunucular ve istemci birlikte açılır.')) : null);
  const hero = h('div', { class: 'hero' }, left, playCol);

  // ---- başlatma adımları
  let steps = null;
  const recent = o.bitti && (Date.now() / 1000 - o.bitti < 45);
  if (o.adimlar.length && (o.calisiyor || o.hata || recent)) {
    steps = h('div', { class: 'card' }, h('h2', null, icon('zap'), o.server_only ? T('Sunucu başlatma') : T('Oyun başlatma')),
      stepList(o.adimlar));
  }
  const last = d.processes.istemci.son;
  const early = last && last.early && !running ? h('div', { class: 'alert uyari' }, icon('alert'),
    h('div', null, T('İstemci açıldıktan {0} sn sonra kapandı ({1}). Sunucular açık bırakıldı. İstemci günlüğüne bakın.', last.sure_sn, last.time)),
    btn(T('Günlük'), () => { go('sunucu'); setTimeout(() => showLog(d.panel.platform === 'win32' ? 'client.log' : 'wine.log'), 100); }, 'sm')) : null;

  // ---- uyarılar
  const warns = d.warnings.map(u => h('div', { class: 'alert ' + (u.tur === 'hata' ? 'hata' : 'uyari') }, icon('alert'),
    h('div', { style: u.ilerleme != null ? { flex: '1' } : null }, u.metin,
      u.ilerleme != null ? h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: u.ilerleme + '%' } }))) : null,
      u.download && u.download.toplam ? h('div', { class: 'small dl-info' }, dlInfo(u.download)) : null),
    u.eylem ? btn(u.eylem.calisiyor ? u.eylem.running_text || T('Kuruluyor…') : u.eylem.metin, () => act(() => api(u.eylem.api, {})), 'primary sm', null, { disabled: !!u.eylem.calisiyor }) : null,
    u.page ? btn(T('Git'), () => go(u.page), 'sm') : null));

  // ---- özet kartları
  const setCard = h('div', { class: 'card' }, h('h2', null, icon('sliders'), T('Etkin ayarlar')),
    h('p', { class: 'desc' }, d.settings_summary.length ? T('Varsayılandan farklı olanlar:') : T('Bütün ayarlar varsayılan.')),
    h('div', { class: 'chips' }, d.settings_summary.map(x => h('span', { class: 'chip' }, x.ad, h('b', null, x.deger)))),
    h('div', { class: 'row', style: { marginTop: '14px' } }, btn(T('Ayarları düzenle'), () => go('ayarlar'), 'sm', 'sliders')));
  const evCard = h('div', { class: 'card' }, h('h2', null, icon('calendar'), T('Açık etkinlikler')),
    h('p', { class: 'desc' }, d.etkinlikler.length ? T('Oyuna girdiğinde etkin olan yıllık etkinlikler:') : T('Şu an açık yıllık etkinlik yok.')),
    h('div', { class: 'chips' }, d.etkinlikler.map(n => h('span', { class: 'chip' }, '🎉 ', n))),
    h('div', { class: 'row wrap', style: { marginTop: '14px' } }, btn(T('Etkinlikleri yönet'), () => go('etkinlikler'), 'sm', 'calendar'),
      btn(T('Takvim'), () => go('takvim'), 'ghost sm', 'agenda')));
  const srvCard = h('div', { class: 'card' }, h('h2', null, icon('server'), T('Sunucu')),
    h('div', { class: 'check-list' }, [[T('Web girişi (8090, 80)'), st.web, d.processes.servers.web.sure_sn],
      [T('Oyun sunucusu (8081)'), st.oyun, d.processes.servers.oyun.sure_sn], [T('İstemci'), st.istemci, d.processes.istemci.sure_sn]].map(([n, v, t]) =>
      h('div', null, dot(stCls(v)), h('span', null, n), h('span', { class: 'muted small', style: { marginLeft: 'auto' } },
        stText(v) + (v === 'acik' && t != null ? ' · ' + fmtDur(t) : ''))))),
    h('div', { class: 'row' }, btn(T('Sunucu ve günlükler'), () => go('sunucu'), 'sm', 'server')));

  root.replaceChildren(...[...warns, hero, steps, early, multiCard(d), srv || S.live?.var ? liveCard() : null,
    h('div', { class: 'grid g3' }, setCard, evCard, srvCard)].filter(Boolean));
}

// ---- çoklu istemci (multi_client.py, /api/coklu): OYNA'dan sonra öteki kayıtlarla aynı sunucuya ek istemciler
const multiSig = c => c && JSON.stringify(Object.assign({}, c, { clients: (c.clients || []).map(x => Object.assign({}, x, { sure_sn: null })) }));
async function openExtra(id, pilot) {
  S.multiBusy = id; S.sig.oyna = null; renderPlayBody();
  const r = await act(() => api('/api/coklu/ac', { kayit: id }), T('Ek istemci açılıyor: {0}', pilot));
  S.multiBusy = null; S.sig.oyna = null;
  try { S.durum = await api('/api/durum'); } catch (e) { /* bir sonraki yoklamada */ }
  renderChrome(); renderPlayBody();
  return r;
}
function extraBlock(d, k) {
  const c = d.coklu, open = c.clients || [];
  const pilots = [(c.kayitlar || []).find(x => x.id === c.ana)?.pilot, ...open.map(x => x.pilot)].filter(Boolean).map(p => p.toLowerCase());
  return srvState(d).oyun !== 'acik' ? T('Önce OYNA') : d.oyna.calisiyor ? T('Başlatma sürüyor') : k.bozuk ? T('Kayıt bozuk')
    : k.arkadas ? T('Arkadaşının sunucusunda') : open.length >= c.en_cok ? T('Sınır dolu ({0})', c.en_cok)
    : pilots.includes((k.pilot || '').toLowerCase()) ? T('Aynı pilot adı açık') : S.multiBusy ? T('Açılıyor…') : null;
}
function multiCard(d) {
  const c = d.coklu; if (!c) return null;
  const open = c.clients || [], st = srvState(d), srv = st.oyun === 'acik';
  if (!open.length && (!c.ayar || c.save_count < 2)) return null;      // kapalı ya da başka kayıt yok: kart yok (İstemci sayfasında ayar)
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
    const why = extraBlock(d, k), busy = S.multiBusy === k.id;
    return h('div', { class: 'row multi-row' }, h('span', { style: { minWidth: 0, flex: 1 } }, h('b', null, k.pilot || '?'), ' ',
      badge(k.firma || '?', firmaCls(k.firma)), h('span', { class: 'small muted' }, ' ' + lvl(k.seviye) + ' · ' + k.ad)),
      why && !busy ? h('span', { class: 'small dim' }, why) : null,
      btn(busy ? T('Açılıyor…') : T('Ek istemcide aç'), () => openExtra(k.id, k.pilot), 'primary sm', busy ? null : 'play', { disabled: !!why || busy }));
  });
  const early = Object.entries(c.son || {}).filter(([id, s]) => s.early && now - s.bitis < 120 && !open.some(x => x.kayit === id)).map(([id, s]) =>
    h('div', { class: 'alert uyari' }, icon('alert'), h('div', null, T('{0} kaydının ek istemcisi açıldıktan {1} sn sonra kapandı ({2}). İstemci günlüğüne bakın.',
      (c.kayitlar || []).find(k => k.id === id)?.ad || id, s.sure_sn, s.time)), logBtn(id)));
  return h('div', { class: 'card', id: 'coklu-card' },
    h('div', { class: 'row between wrap' }, h('h2', null, icon('monitor'), T('Çoklu istemci')),
      h('div', { class: 'row wrap', style: { gap: '6px' } }, badge(T('{0} / {1} ek istemci', open.length, c.en_cok), open.length ? 'ok' : ''),
        open.length > 1 ? btn(T('Hepsini kapat'), async () => {
          if (await confirmBox(T('Ek istemcilerin hepsi kapatılsın mı?'), T('{0} pencere kapanır; kayıtların son hâli yazılır. Ana istemci açık kalır.', open.length), { ok: T('Hepsini kapat'), danger: true }))
            act(() => api('/api/coklu/close_all', {}), T('Ek istemciler kapatılıyor.'));
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

// ---- canlı durum (oyun sunucusunun durum.json'u; live_status.py, /api/canli)
async function liveTick() {
  if (S.page !== 'oyna' || S.liveBusy) return;
  S.liveBusy = true;
  try { S.live = await api('/api/canli'); } catch (e) { S.live = null; } finally { S.liveBusy = false; }
  const c = $('#canli-card'), want = srvState(S.durum).oyun === 'acik' || !!S.live?.var;
  if (c && want) c.replaceWith(liveCard());
  else if (!!c !== want) { S.sig.oyna = null; renderPlayBody(); }     // kart çıksın / kalksın
}
function meter(label, v, max, cls) {
  const pct = max ? Math.max(0, Math.min(100, v * 100 / max)) : 0;
  return h('div', { class: 'meter ' + (cls || '') }, h('div', { class: 'row between small' }, h('span', { class: 'muted' }, label), h('b', null, fmtN(v) + ' / ' + fmtN(max))),
    h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } })));
}
function liveCard() {
  const r = S.live;
  const head = h('h2', null, icon('zap'), T('Canlı durum'));
  if (!r || !r.var) return h('div', { class: 'card', id: 'canli-card' }, head, h('p', { class: 'desc' }, T('Oyun sunucusunun durum bilgisi bekleniyor…')));
  const d = r.durum, w = d.dunya || {}, g = d.gemi, p = d.pilot, k = d.position;
  const flags = [d.bagli ? badge(T('İstemci bağlı'), 'ok') : badge(T('İstemci bağlı değil'), ''), r.age > 10 ? badge(T('Durum {0} sn eski', Math.round(r.age)), 'warn') : null,
    w.dead ? badge(T('Gemi yok edildi'), 'err') : null, w.in_combat ? badge(T('Savaşta'), 'orange') : null, w.guvenli ? badge(T('Güvenli bölgede'), 'info') : null];
  const facts = [[T('Harita'), `${k.harita} (${fmtN(k.x)}, ${fmtN(k.y)})`], [T('Gemi'), (g.ad || '').replace('ship_', '')], [T('Uzaylı'), w.uzayli != null ? fmtN(w.uzayli) : '—'],
    [T('Kutu / cevher'), w.kutu != null ? fmtN(w.kutu) + ' / ' + fmtN(w.cevher) : '—'], [T('Hedef'), w.hedef || '—'], [T('Oynama'), fmtDur(d.play_sec)]];
  if (w.kapi) facts.push([T('Kapı'), `${w.kapi.ad || ''}${w.kapi.dalga ? ' · ' + w.kapi.dalga : ''}${w.kapi.stage ? ' · ' + w.kapi.stage : ''}`]);
  if (w.loop) facts.push([T('Döngü'), T('{0} ms ort. · en çok {1} ms', w.loop.avg_ms, w.loop.max_ms) + (w.loop.yavas ? ' · ' + T('{0} yavaş adım', fmtN(w.loop.yavas)) : '')]);
  return h('div', { class: 'card', id: 'canli-card' }, h('div', { class: 'row between wrap' }, head, h('div', { class: 'row wrap', style: { gap: '6px' } }, flags)),
    h('div', { class: 'grid g2', style: { marginTop: '12px' } },
      h('div', { class: 'stack', style: { gap: '10px' } }, meter(T('Can'), g.can, g.max_hp, 'hp'), meter(T('Kalkan'), g.kalkan, g.shield_max, 'sh'), meter(T('Kargo'), g.kargo, g.cargo_max, 'cg')),
      h('div', { class: 'kv one' }, facts.map(([a, b]) => h('div', null, h('span', { class: 'muted' }, a), h('b', { title: b }, b))))),
    h('div', { class: 'live-sub' }, h('div', { class: 'stats', style: { marginTop: 0 } },
      [[T('Seviye'), p.seviye, 'lv'], [T('Kredi'), p.kredi, 'cr'], [T('Uridyum'), p.uridyum, 'ur'], [T('Onur'), p.onur, 'hn']].map(([a, v, c]) =>
        h('div', { class: 'stat' }, h('div', { class: 'k' }, a), h('div', { class: 'v ' + c }, fmtN(v))))),
      d.event_names && d.event_names.length ? h('div', { class: 'chips', style: { marginTop: '10px' } }, d.event_names.map(n => h('span', { class: 'chip' }, n))) : null));
}

async function switchSaveMenu(anchor) {
  const r = await act(() => api('/api/kayitlar')); if (!r) return;
  popMenu(anchor, [...r.liste.map(k => ({
    label: `${k.ad} — ${k.pilot} (${lvl(k.seviye)})${k.aktif ? '  ✓' : ''}`, ic: k.aktif ? 'check' : 'save',
    fn: () => act(() => api('/api/kayitlar/aktif', { id: k.id }), T('Etkin kayıt: {0}', k.ad)).then(() => poll()),
  })), '-', { label: T('Yeni kayıt…'), ic: 'plus', fn: () => newSaveModal() }, { label: T('Kayıtları yönet'), ic: 'save', fn: () => go('kayitlar') }]);
}

// ================================================================== ARKADAŞLARINLA OYNA (friends.py, /api/arkadas)
const IP_KIND = { yerel: [N('Ev ağı'), 'ok'], radmin: [N('Radmin VPN'), 'info'], tailscale: [N('Tailscale'), 'info'], genel: [N('Genel'), 'orange'],
  baglanti: [N('Yalnız bu ağ'), ''] };
const FRD_STATUS = { baglaniyor: [N('Bağlanıyor'), 'info'], oyunda: [N('Oyunda'), 'ok'], ayriliyor: [N('Ayrılıyor'), 'orange'], bitti: [N('Ayrıldın'), ''],
  hata: [N('Hata'), 'err'] };
const FRD_ACTIVE = s => ['baglaniyor', 'oyunda', 'ayriliyor'].includes(s);
const FRD = { sekme: null, adres: null, sifre: '', kayit: null, bilgi: null, veri: null };
const copyText = t => navigator.clipboard.writeText(t).then(() => toast(T('Kopyalandı: {0}', t), 'ok'), () => toast(t, 'info'));
const clock = sec => sec ? new Date(sec * 1000).toLocaleTimeString(LOC(), { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';

async function renderFriends() {
  const v = await act(() => api('/api/arkadas'));
  if (!v || S.page !== 'arkadas') return;
  FRD.veri = v;
  drawFriends();
}
function drawFriends() {
  const v = FRD.veri, d = S.durum;
  if (!FRD.sekme) FRD.sekme = v.misafir.durum !== 'yok' ? 'join' : 'host';
  if (FRD.adres == null) FRD.adres = v.misafir.last_address || '';
  const tabs = h('div', { class: 'seg' }, [['host', T('Sunucu kur (Host)')], ['join', T('Arkadaşına katıl (Join)')]].map(([k, t]) =>
    h('button', { class: FRD.sekme === k ? 'on info' : '', onclick: () => { FRD.sekme = k; drawFriends(); } }, t)));
  $('#content').replaceChildren(h('div', { class: 'stack', id: 'arkadas' }, h('div', { class: 'row' }, tabs),
    ...(FRD.sekme === 'host' ? hostView(v) : joinView(v))));
  S.sig.friendsMode = friendsMode(v, d); S.sig.friendsDyn = friendsDyn(v);
}
const friendsMode = (v, d) => JSON.stringify([FRD.sekme, v.host.acik, v.misafir.durum, d?.oyna, srvState(d), v.kayitlar.map(k => k.id), d?.aktif?.id]);
const friendsDyn = v => JSON.stringify([v.host.guests, v.misafir.adimlar, v.misafir.last_sync, v.misafir.baglanti, v.misafir.not, v.host.public_ip]);
async function friendsTick() {
  if (S.friendsBusy) return;
  S.friendsBusy = true;
  let v;
  try { v = await api('/api/arkadas'); } catch (e) { return; } finally { S.friendsBusy = false; }
  if (S.page !== 'arkadas') return;
  FRD.veri = v;
  if (friendsMode(v, S.durum) !== S.sig.friendsMode) return drawFriends();
  if (friendsDyn(v) === S.sig.friendsDyn) return;
  S.sig.friendsDyn = friendsDyn(v);
  const g = $('#ark-misafirler'); if (g) g.replaceWith(guestsCard(v.host));
  const j = $('#ark-join-durum'); if (j) j.replaceWith(joinStatus(v));
}

function launchSteps(o) {
  const recent = o.bitti && (Date.now() / 1000 - o.bitti < 45);
  if (!o.adimlar.length || !(o.calisiyor || o.hata || recent)) return null;
  return stepList(o.adimlar);
}
const stepList = list => h('div', { class: 'steps' }, list.map(s => [h('div', { class: 'step ' + s.durum },
  h('span', { class: 'ic' }, s.durum === 'calisiyor' ? h('span', { class: 'spin' }) : icon(s.durum === 'hata' ? 'x' : 'check')),
  h('span', null, s.metin), h('span', { class: 'dim small', style: { marginLeft: 'auto' } }, s.time)),
  s.ilerleme && s.durum === 'calisiyor' ? prepBox(s.ilerleme) : null]));

// BepInEx'in ilk açılış hazırlığı (istemci_yama.isit/ilerleme): oyun penceresi henüz görünmez, oyuncu oyunun açılmadığını sanmasın
const PREP_STAGE = [N('İstemci başlatılıyor'), N('Köprü derlemeleri üretiliyor'), N('Dosyalar yazılıyor')];
function prepBox(p) {
  return h('div', { class: 'prep' },
    h('div', { class: 'prep-head' }, icon('zap'), h('span', null, T('Düzeltmeler ilk açılışa hazırlanıyor')), h('b', null, '%' + p.yuzde)),
    h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: p.yuzde + '%' } }))),
    h('div', { class: 'prep-stages' }, PREP_STAGE.map((a, i) => {
      const st = i < p.stage ? 'tamam' : i === p.stage ? 'calisiyor' : 'bekliyor';
      return h('div', { class: 'prep-stage ' + st }, h('span', { class: 'ic' }, st === 'tamam' ? icon('check') : st === 'calisiyor'
        ? h('span', { class: 'spin' }) : h('span', { class: 'dot-sm' })), h('span', null, T(a)));
    })),
    h('div', { class: 'small muted' }, T('Yalnız ilk açılışta bir kez yapılır; bu sırada oyun penceresi görünmez. Bitince oyun kendiliğinden açılır, bir şeye basman gerekmez.'),
      ' ', h('span', { class: 'dim' }, T('Geçen süre: {0}', fmtDur(p.elapsed_sec)))));
}

// ---- Host
function hostView(v) {
  const dmg = v.host, d = S.durum, st = srvState(d), busy = d?.oyna?.calisiyor, running = st.istemci === 'acik';
  const single = st.oyun === 'acik' && !dmg.acik, guest = FRD_ACTIVE(v.misafir.durum);
  const left = h('div', null, h('div', { class: 'slot-name' }, T('Arkadaş sunucusu')),
    h('div', { class: 'pilot' }, dmg.acik ? T('Sunucun açık') : T('Sunucu kapalı'),
      dmg.acik ? badge(T('{0} / {1} misafir', dmg.guests.length, dmg.en_cok), 'ok') : null, dmg.sifre ? badge(T('Şifreli'), 'info') : null),
    h('div', { class: 'muted' }, dmg.acik ? T('Arkadaşların aşağıdaki adreslerden biriyle katılır. Sen kendi kaydınla oynarsın.')
      : T('Sunucu kurunca kendi kaydınla oyuna girersin; arkadaşların kendi kayıtlarıyla katılır.')),
    d?.aktif ? h('div', { class: 'meta' }, h('span', null, T('Kayıt:') + ' ', h('b', null, d.aktif.ad)), h('span', null, T('Pilot') + ' ', h('b', null, d.aktif.pilot))) : null,
    v.dunya ? hostWorldChip(v) : null);                                // sunucunun dünyası (world_editor.js)
  let main; const sub = [];
  if (busy) main = h('button', { class: 'play-btn busy', disabled: true }, h('span', { class: 'spin', style: { borderTopColor: '#021120' } }), T('BAŞLATILIYOR'));
  else if (dmg.acik && running) main = h('button', { class: 'play-btn running', disabled: true }, icon('check'), T('OYUN AÇIK'));
  else main = h('button', { class: 'play-btn', disabled: !d?.aktif || guest || (running && !dmg.acik), onclick: () => act(() => api('/api/arkadas/host', {})) },
    icon(dmg.acik ? 'play' : 'users'), dmg.acik ? T('OYNA') : T('SUNUCU KUR'));
  if (dmg.acik) sub.push(btn(T('Sunucuyu kapat'), async () => {
    if (dmg.guests.length && !await confirmBox(T('Sunucu kapatılsın mı?'), T('Bağlı misafirler oyundan düşer; kayıtları kendi bilgisayarlarında son hâliyle kalır.'),
      { ok: T('Kapat'), danger: true })) return;
    act(() => api('/api/sunucu/durdur', {}), T('Sunucular durduruldu.'));
  }, 'danger sm', 'stop', { disabled: running || busy }));
  else sub.push(btn(T('Yalnız sunucuyu başlat'), () => act(() => api('/api/arkadas/host', { server_only: true })), 'ghost sm', 'server',
    { disabled: !d?.aktif || guest || busy }));
  const hint = guest ? T('Şu an arkadaşının sunucusundasın: önce oradan ayrıl.') : single ? T('Tek oyunculu sunucun açık: Sunucu kur onu arkadaş sunucusu olarak yeniden başlatır.')
    : dmg.acik ? (S.panelCfg?.istemci_kapaninca === 'acik' ? T('Oyunu kapatınca sunucu açık kalır.') : T('Oyunu kapatınca sunucu da kapanır (Sunucu > Davranış).')) : null;
  const hero = h('div', { class: 'hero' }, left, h('div', { class: 'play-col' }, main, h('div', { class: 'play-sub' }, sub), hint ? h('div', { class: 'small muted' }, hint) : null));
  const steps = d?.oyna ? launchSteps(d.oyna) : null;

  // ayarlar
  const pw = h('input', { class: 'input', value: dmg.sifre, placeholder: T('Şifresiz'), maxlength: 64 });
  const max = h('select', { class: 'input', style: { width: '110px' } }, Array.from({ length: 16 }, (_, i) => i + 1).map(n => h('option', { value: n, selected: n === dmg.en_cok }, n)));
  const save = () => act(() => api('/api/arkadas/ayarlar', { sifre: pw.value, en_cok: +max.value }), T('Kaydedildi.'))
    .then(r => { if (r) { FRD.veri = r; } });
  pw.addEventListener('change', save); max.addEventListener('change', save);
  const world = v.dunya ? h('select', { class: 'input', onchange: e => act(() => api('/api/arkadas/ayarlar', { dunya: e.target.value }), T('Kaydedildi.'))
    .then(r => { if (r) { FRD.veri = r; drawFriends(); } }) },
    h('option', { value: '', selected: !v.dunya.secim }, T('Kaydının dünyası ({0})', v.dunya.save_world.ad)),
    v.dunya.liste.map(w => h('option', { value: w.id, selected: v.dunya.secim === w.id }, w.ad))) : null;
  const setCard = h('div', { class: 'card' }, h('h2', null, icon('sliders'), T('Sunucu ayarları')),
    h('div', { class: 'grid g2' }, field(T('Katılma şifresi'), pw), field(T('En çok misafir'), max)),
    world ? h('div', { style: { marginTop: '12px' } }, field(T('Sunucunun dünyası'), world),
      h('p', { class: 'small muted', style: { margin: '6px 0 0' } }, T('Misafirler de bu dünyada oynar (haritalar, uzaylılar, görevler, mağaza). Dünyaları Dünya Editörü\'nde hazırlarsın.'))) : null,
    h('p', { class: 'desc', style: { marginTop: '10px' } }, dmg.acik ? T('Değişiklikler sunucu yeniden başlayınca geçerli olur.')
      : T('Şifre, adresini bilen herkesin katılmasını engeller. Misafirler bu şifreyi Arkadaşına katıl bölümünde yazar.')));

  // adresler
  const ipRow = (ip, kind) => h('div', { class: 'row between' }, h('b', { class: 'mono' }, ip), h('span', { class: 'row', style: { gap: '6px' } },
    badge(T((IP_KIND[kind] || IP_KIND.genel)[0]), (IP_KIND[kind] || IP_KIND.genel)[1]), btn('', () => copyText(ip), 'ghost sm', 'copy', { title: T('Kopyala') })));
  const addrCard = h('div', { class: 'card' }, h('h2', null, icon('globe'), T('Arkadaşlarına vereceğin adres')),
    h('div', { class: 'stack', style: { gap: '8px' } }, dmg.ips.map(x => ipRow(x.ip, x.tur)),
      dmg.public_ip ? ipRow(dmg.public_ip, 'genel') : h('div', { class: 'row' }, btn(T('Genel IP\'mi bul'), async () => {
        const r = await act(() => api('/api/arkadas/public_ip', {})); if (r) { FRD.veri.host.public_ip = r.ip; drawFriends(); }
      }, 'sm', 'search'), h('span', { class: 'small dim' }, T('api.ipify.org\'a sorulur.')))),
    h('p', { class: 'desc', style: { marginTop: '12px' } }, T('Aynı evdeyseniz (aynı modem) ev ağı adresini ver. İnternet üzerinden bağlanacaklara genel IP\'ni (port yönlendirmesiyle) ya da sanal ağ (Radmin VPN, ZeroTier, Tailscale) adresini ver.')));

  // portlar
  const portCard = h('div', { class: 'card' }, h('h2', null, icon('shield'), T('Açılması gereken portlar')),
    h('table', { class: 'table' }, h('thead', null, h('tr', null, h('th', null, T('Protokol')), h('th', null, T('Port')), h('th', null, T('Ne için')))),
      h('tbody', null, [['TCP', dmg.game_port, T('Oyun ve hesap gönderimi')], ['TCP', dmg.chat_port, T('Sohbet')]].map(([a, b, c]) =>
        h('tr', null, h('td', null, h('b', null, a)), h('td', { class: 'mono' }, b), h('td', null, c))))),
    h('p', { class: 'desc', style: { marginTop: '10px' } }, T('UDP portu gerekmez. Web girişi (80, 8090) yalnız bu bilgisayarda kalır; onları açma.')),
    h('div', { class: 'stack', style: { gap: '8px', marginTop: '6px' } },
      S.durum?.panel?.platform && S.durum.panel.platform !== 'win32'
        ? h('div', { class: 'note' }, h('b', null, '1. '), T("Güvenlik duvarı: macOS sorarsa Python'a gelen bağlantı izni ver. Linux'ta güvenlik duvarı (ör. ufw) açıksa:"),
          h('div', { class: 'cmd', style: { marginTop: '6px' } }, `sudo ufw allow ${dmg.game_port},${dmg.chat_port}/tcp`))
        : h('div', { class: 'note' }, h('b', null, '1. '), T('Windows Güvenlik Duvarı: sunucu ilk açıldığında Python için çıkan pencerede erişime izin ver (Özel ağlar). Pencere çıkmadıysa yönetici olarak açılmış bir komut isteminde:'),
          h('div', { class: 'cmd', style: { marginTop: '6px' } }, `netsh advfirewall firewall add rule name="DarkOrbit" dir=in action=allow protocol=TCP localport=${dmg.game_port},${dmg.chat_port}`)),
      h('div', { class: 'note' }, h('b', null, '2. '), T('Aynı ev ağında başka bir şey gerekmez.')),
      h('div', { class: 'note' }, h('b', null, '3. '), T('İnternet üzerinden: modeminin arayüzünde TCP {0} ve {1} portlarını bu bilgisayarın ev ağı adresine yönlendir (port yönlendirme / Sanal sunucu / NAT).', dmg.game_port, dmg.chat_port)),
      h('div', { class: 'note' }, h('b', null, '4. '), T('İnternet sağlayıcın CGNAT kullanıyorsa (modemdeki WAN adresi genel IP\'nden farklıysa) yönlendirme işe yaramaz: Radmin VPN, ZeroTier ya da Tailscale gibi bir sanal ağ kurun ve o ağdaki adresi verin.'))));

  // ortak evren
  const share = h('div', { class: 'card' }, h('h2', null, icon('info'), T('Ortak evren')),
    h('div', { class: 'check-list' }, [N('Firma, savaş ve Blacklight haritaları (1-1 … 5-4, BL) ortak: uzaylılar, kutular ve cevherler paylaşılır, birbirinizi görürsünüz.'),
      N('Kapı, mod ve etkinlik haritaları herkesin kendi kopyası.'), N('Sohbet ortak; posta, klan ve müzayede her oyuncunun kendisinin.'),
      N('Oyun ayarların (çarpanlar, etkinlikler) misafirlerine de uygulanır.'),
      N('Misafirlerin kaydı bu bilgisayara yazılmaz, Kayıtlar sayfasında görünmez: ilerlemeleri kendi bilgisayarlarına kaydedilir.'),
      N('Oyuncular birbirine saldıramaz (PvP yok).')].map(t => h('div', null, icon('check'), h('span', null, T(t))))));
  return [hero, steps ? h('div', { class: 'card' }, h('h2', null, icon('zap'), T('Sunucu başlatma')), steps) : null, guestsCard(dmg),
    h('div', { class: 'grid g2' }, addrCard, setCard), h('div', { class: 'grid g2' }, portCard, share)].filter(Boolean);
}
function guestsCard(dmg) {
  if (!dmg.acik) return h('div', { id: 'ark-misafirler' });
  const now = Date.now() / 1000;
  return h('div', { class: 'card', id: 'ark-misafirler' }, h('h2', null, icon('users'), T('Misafirler')),
    dmg.guests.length ? h('table', { class: 'table' },
      h('thead', null, h('tr', null, [T('Pilot'), T('Seviye'), T('Harita'), T('Adres'), T('Durum'), T('Süre'), ''].map(x => h('th', null, x)))),
      h('tbody', null, dmg.guests.map(g => h('tr', null, h('td', null, h('b', null, g.ad)), h('td', null, g.seviye), h('td', null, g.harita || '—'),
        h('td', { class: 'mono' }, g.ip), h('td', null, g.bagli ? badge(T('Oyunda'), 'ok') : badge(T('Bağlı değil'), '')), h('td', null, fmtDur(now - g.giris)),
        h('td', { class: 'num' }, btn(T('Çıkar'), async () => {
          if (await confirmBox(T('{0} çıkarılsın mı?', g.ad), T('Bağlantısı kapanır. Kaydı kendi bilgisayarında son hâliyle kalır.'), { ok: T('Çıkar'), danger: true }))
            act(() => api('/api/arkadas/kick', { oturum: g.oturum }), T('{0} çıkarıldı.', g.ad));
        }, 'ghost sm', 'x')))))) :
      h('p', { class: 'desc' }, T('Henüz misafir yok. Arkadaşların Arkadaşlarınla Oyna > Arkadaşına katıl bölümünde adresini yazıp bağlanır.')));
}

// ---- Join
function joinView(v) {
  const m = v.misafir;
  if (FRD_ACTIVE(m.durum)) return [joinStatus(v), joinInfo()];
  const d = S.durum, st = srvState(d);
  const address = h('input', { class: 'input', value: FRD.adres, placeholder: '192.168.1.20', oninput: e => { FRD.adres = e.target.value; } });
  const pw = h('input', { class: 'input', type: 'password', value: FRD.sifre, placeholder: T('Şifre yoksa boş bırak'), oninput: e => { FRD.sifre = e.target.value; } });
  const slot = h('select', { class: 'input', onchange: e => { FRD.kayit = e.target.value; } },
    v.kayitlar.map(k => h('option', { value: k.id, selected: k.id === (FRD.kayit || v.aktif) }, `${k.ad} — ${k.pilot} (${lvl(k.seviye)})`)));
  const info = h('div', { id: 'ark-bilgi' }, FRD.bilgi ? serverInfo(FRD.bilgi, v) : null);
  const test = btn(T('Bağlantıyı dene'), async ev => {
    const b = ev.currentTarget; b.disabled = true;
    const r = await act(() => api('/api/arkadas/test', { adres: address.value }));
    b.disabled = false; FRD.bilgi = r || null;
    info.replaceChildren(r ? serverInfo(r, v) : '');
  }, 'sm', 'search');
  const blocked = st.oyun === 'acik' ? T('Kendi sunucun açık: katılmak için önce onu durdur.') : st.istemci === 'acik' ? T('Oyun açık: önce kapat.')
    : !v.kayitlar.length ? T('Önce Kayıtlar sayfasından bir kayıt oluştur.') : null;
  const join = h('button', { class: 'play-btn', disabled: !!blocked, onclick: () =>
    act(() => api('/api/arkadas/join', { adres: address.value, sifre: pw.value, kayit: slot.value })).then(r => { if (r) renderFriends(); }) }, icon('play'), T('KATIL'));
  const left = h('div', { class: 'stack', style: { gap: '12px' } }, h('div', { class: 'slot-name' }, T('Arkadaşının sunucusuna katıl')),
    field(T('Arkadaşının adresi (IP ya da alan adı)'), h('div', { class: 'row' }, address, test)), h('div', { class: 'grid g2' }, field(T('Şifre'), pw), field(T('Kullanılacak kayıt'), slot)), info);
  const hero = h('div', { class: 'hero' }, left, h('div', { class: 'play-col' }, join,
    h('div', { class: 'small muted' }, blocked || T('Kaydın yedeklenir, arkadaşının sunucusuna gönderilir ve oyun açılır.'))));
  const last = ['bitti', 'hata'].includes(m.durum) ? h('div', { class: 'card' }, h('h2', null, icon(m.durum === 'hata' ? 'alert' : 'check'),
    m.durum === 'hata' ? T('Katılma başarısız') : T('Son oturum')), stepList(m.adimlar),
    m.not ? h('div', { class: 'alert uyari', style: { marginTop: '10px' } }, icon('alert'), h('div', null, m.not)) : null,
    m.last_sync ? h('p', { class: 'desc', style: { marginTop: '10px' } }, T('Kaydın son eşitlemesi: {0}', clock(m.last_sync))) : null) : null;
  return [hero, last, joinInfo()].filter(Boolean);
}
function serverInfo(r, v) {
  const sameClient = !r.istemci || r.istemci === v.client_version;
  return h('div', { class: 'stack', style: { gap: '10px' } },
    h('div', { class: 'kv' }, [[T('Sunucu'), r.adres], [T('Sunucunun pilotu'), r.pilot || '—'], [T('Oyuncular'), (r.players || []).join(', ') || '—'],
      [T('Misafir'), `${r.misafir} / ${r.en_cok}`], [T('Şifre'), r.sifre ? T('Gerekli') : T('Yok')], [T('Oyun sürümü'), r.istemci || '—']].map(([a, b]) =>
      h('div', null, h('span', null, a), h('b', null, b)))),
    h('div', { class: 'wz-summary' }, checkRow(r.compatible, r.compatible ? T('Panel sürümleri uyumlu') : T('Panel sürümleri farklı: ikiniz de paneli güncelleyin')),
      checkRow(sameClient, sameClient ? T('Oyun sürümü aynı') : T('Oyun sürümü farklı (seninki {0})', v.client_version)),
      checkRow(r.yer, r.yer ? T('Sunucuda yer var') : T('Sunucu dolu'))));
}
function joinStatus(v) {
  const m = v.misafir, [t, c] = FRD_STATUS[m.durum] || [m.durum, ''];
  const slot = v.kayitlar.find(k => k.id === m.kayit);
  return h('div', { class: 'card', id: 'ark-join-durum' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('users'), T('Arkadaşının sunucusu')), badge(T(t), c)),
    h('div', { class: 'kv', style: { margin: '12px 0' } }, [[T('Adres'), m.adres], [T('Sunucunun pilotu'), m.sunucu?.pilot || '—'],
      [T('Kayıt'), slot ? `${slot.ad} — ${slot.pilot}` : m.kayit], [T('Son eşitleme'), clock(m.last_sync)],
      [T('Bağlantı'), m.baglanti ? T('İyi') : T('Kesik, yeniden deneniyor…')]].map(([a, b]) => h('div', null, h('span', null, a), h('b', null, b)))),
    stepList(m.adimlar),
    m.not ? h('div', { class: 'alert uyari', style: { marginTop: '10px' } }, icon('alert'), h('div', null, m.not)) : null,
    h('div', { class: 'row', style: { marginTop: '14px' } }, btn(T('Ayrıl'), async () => {
      if (await confirmBox(T('Arkadaşının sunucusundan ayrılınsın mı?'), T('Oyun kapanır, kaydının son hâli bu bilgisayara yazılır.'), { ok: T('Ayrıl'), danger: true }))
        act(() => api('/api/arkadas/leave', {})).then(() => friendsTick());
    }, 'danger', 'power', { disabled: m.durum === 'ayriliyor' }), h('span', { class: 'small muted' }, T('Oyunu kapatınca da ayrılırsın.'))));
}
const joinInfo = () => h('div', { class: 'card' }, h('h2', null, icon('info'), T('Kaydın nerede?')),
  h('div', { class: 'check-list' }, [N('Katılmadan önce kaydın yedeklenir (Kayıtlar > Yedekler).'),
    N('Oyun sürerken ilerlemen birkaç saniyede bir bu bilgisayardaki kaydına yazılır; ayrılınca son hâli kaydedilir.'),
    N('Arkadaşının bilgisayarına kaydın yazılmaz, onun Kayıtlar sayfasında görünmez.'),
    N('Arkadaşının oyun ayarları (çarpanlar, etkinlikler) onun sunucusunda geçerlidir.'),
    N('Arkadaşının sunucusu: TCP 8081 (oyun) ve 7771 (sohbet) portları ona açık olmalı.')].map(t => h('div', null, icon('check'), h('span', null, T(t))))));

// ================================================================== KAYITLAR
// Kayıtlar sayfası ve karakter editörü: saves.js. Burada yeni pilot formu ve yedekler penceresi (kurulum sihirbazı da kullanır).

// ---- yeni pilot formu (Yeni kayıt penceresi ve kurulum sihirbazı)
const FIRMS = [[1, 'MMO', 'Mars Mining Operations', 'var(--mmo)', '1-1'], [2, 'EIC', 'Earth Industries Corp.', 'var(--eic)', '2-1'],
  [3, 'VRU', 'Venus Resources Unlimited', 'var(--vru)', '3-1']];
function pilotForm({ start = true } = {}) {
  const st = { firma: 2 };
  const name = h('input', { class: 'input', placeholder: T('ör. Ana kayıt, Hızlı deneme…') });
  const pilot = h('input', { class: 'input', placeholder: T('3-20 karakter'), maxlength: 20 });
  // başlangıç değerleri (isteğe bağlı; boş: şablondaki): kredi, uridyum, seviye (EP'si seviyenin eşiği), onur, cephane
  const num = (min, max) => h('input', { class: 'input', type: 'number', min, max, step: 1, placeholder: T('şablondaki') });
  const credits = num(0), uri = num(0), level = num(1, 50), honor = num(0), laser = num(0), rocket = num(0);
  const progressive = h('input', { type: 'checkbox' }), campaign = h('input', { type: 'checkbox' });
  const cards = FIRMS.map(([id, k, n, c, m]) => {
    const el = h('div', { class: 'radio-card' + (id === st.firma ? ' on' : ''), style: { '--c': c }, onclick: () => {
      st.firma = id; el.parentNode.querySelectorAll('.radio-card').forEach(x => x.classList.remove('on')); el.classList.add('on');
    } }, art('firma_' + k.toLowerCase(), 'crest'), h('b', null, k), h('span', null, n), h('span', null, T('Başlangıç: {0}', m)));
    return el;
  });
  const el = [field(T('Pilot adı (oyunda görünür)'), pilot), field(T('Firma'), h('div', { class: 'radio-cards' }, cards)),
    field(T('Kayıt adı (isteğe bağlı)'), name),
    start ? h('div', { class: 'grid g2' }, field(T('Başlangıç kredisi (isteğe bağlı)'), credits), field(T('Başlangıç uridyumu (isteğe bağlı)'), uri),
      field(T('Başlangıç seviyesi (1-50, isteğe bağlı)'), level), field(T('Başlangıç onuru (isteğe bağlı)'), honor),
      field(T('LCB-10 lazer cephanesi (isteğe bağlı)'), laser), field(T('R-310 roketi (isteğe bağlı)'), rocket)) : null,
    h('label', { class: 'row small', title: T('Season Pass ilk sezondan (Mobius) başlar; her sezon bitince bir sonraki açılır, en yeniye dek. Sonradan eklenen sezonlar da sırası gelince açılır. Kapalıysa hep en yeni sezon.') },
      h('span', { class: 'switch' }, progressive, h('span')), T('Sezonları ilk sezondan sırayla aç')),
    h('label', { class: 'row small', title: T('Yeni sunucu açılışındaki "Level 1", "Level 5" … "Level 25" görevleri: seviyene ulaştıkça yüksek ödüller (gemiler, ekipman, uridyum, Premium). Kaydın açılışından itibaren 30 gün görev listesinde durur. Kapalıysa bu görevler hiç görünmez.') },
      h('span', { class: 'switch' }, campaign, h('span')), T('Başlangıç kampanyası'))];
  const v = x => start ? x.value : '';
  return { el, pilot, values: () => ({ ad: name.value.trim() || pilot.value.trim(), pilot: pilot.value.trim(), firma: st.firma,
    kredi: v(credits), uridyum: v(uri), seviye: v(level), onur: v(honor), lazer: v(laser), roket: v(rocket), ilerlemeli: progressive.checked, kampanya: campaign.checked }) };
}

function newSaveModal() {
  const f = pilotForm();
  const active = h('input', { type: 'checkbox', checked: true });
  const m = modal({
    title: T('Yeni kayıt'), sub: T('Yeni bir pilotla sıfırdan başlar. Eski kayıtların etkilenmez.'),
    body: [...f.el, h('label', { class: 'row small' }, h('span', { class: 'switch' }, active, h('span')), T('Etkin kayıt yap'))],
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Oluştur'), async ev => {
      const b = ev.currentTarget; b.disabled = true;
      const r = await act(() => api('/api/kayitlar/yeni', Object.assign(f.values(), { set_active: active.checked })), T('Kayıt oluşturuldu.'));
      b.disabled = false;
      if (r) { m.close(); if (S.page === 'kayitlar') renderSaves(); poll(); }
    }, 'primary', 'plus')],
  });
}

async function backupsModal(id) {
  let m;
  async function load() {
    const r = await act(() => api('/api/backups?id=' + encodeURIComponent(id))); if (!r) return;
    const k = r.kayit, cfg = r.ayarlar;
    const note = h('input', { class: 'input', placeholder: T('Not (isteğe bağlı): ör. Kapı öncesi') });
    const take = btn(T('Şimdi yedek al'), () => act(() => api('/api/backups/al', { id, not: note.value }), T('Yedek alındı.')).then(load), 'primary', 'save');
    const tog = h('input', { type: 'checkbox', checked: cfg.backup_on_launch, onchange: e => act(() => api('/api/panel_settings', { values: { backup_on_launch: e.target.checked } }), T('Kaydedildi.')) });
    const keep = h('input', { class: 'input num', type: 'number', min: 1, max: 200, value: cfg.backup_count,
      onchange: e => act(() => api('/api/panel_settings', { values: { backup_count: +e.target.value } }), T('Kaydedildi.')) });
    const iv = h('input', { class: 'input num', type: 'number', min: 0, max: 600, value: cfg.backup_interval_min,
      onchange: e => act(() => api('/api/panel_settings', { values: { backup_interval_min: +e.target.value } }), T('Kaydedildi.')) });
    const rows = r.liste.map(b => h('tr', null,
      h('td', null, h('div', null, fmtWhen(b.time)), h('div', { class: 'dim small' }, b.time)),
      h('td', null, badge(b.kind_name, b.tur === 'manual' ? 'info' : b.tur === 'before' ? 'orange' : '')),
      h('td', null, `${b.pilot} · ${lvl(b.seviye)}`), h('td', { class: 'num' }, fmtN(b.kredi)), h('td', { class: 'num' }, fmtN(b.uridyum)),
      h('td', { class: 'small muted' }, b.not_ || ''),
      h('td', { class: 'num' }, h('div', { class: 'actions', style: { justifyContent: 'flex-end', flexWrap: 'nowrap' } },
        btn(T('Geri yükle'), async () => {
          if (await confirmBox(T('Yedek geri yüklensin mi?'), T('"{0}" kaydı {1} anına döner. Şimdiki durum önce "Geri yükleme öncesi" yedeği olarak saklanır.', k.ad, b.time), { ok: T('Geri yükle') }))
            act(() => api('/api/backups/restore', { id, dosya: b.dosya }), T('Geri yüklendi.')).then(load);
        }, 'sm', 'undo', { disabled: k.in_use, title: k.in_use ? T('Oyun açıkken geri yüklenemez') : '' }),
        btn('', ev => popMenu(ev.currentTarget, [
          { label: T('Yeni kayıt olarak aç'), ic: 'plus', fn: async () => { const v = await promptBox(T('Yedekten yeni kayıt'), T('Yeni kaydın adı'), `${k.ad} (${b.time.slice(0, 10)})`); if (v != null) act(() => api('/api/backups/new_save', { id, dosya: b.dosya, ad: v }), T('Yeni kayıt oluşturuldu.')).then(() => S.page === 'kayitlar' && renderSaves()); } },
          { label: T('Not'), ic: 'note', fn: async () => { const v = await promptBox(T('Yedek notu'), T('Not'), b.not_); if (v != null) act(() => api('/api/backups/note', { id, dosya: b.dosya, not: v })).then(load); } },
          '-',
          { label: T('Sil'), ic: 'trash', danger: true, fn: async () => { if (await confirmBox(T('Yedek silinsin mi?'), T('{0} yedeği diskten silinir.', b.time), { ok: T('Sil'), danger: true })) act(() => api('/api/backups/sil', { id, dosya: b.dosya }), T('Yedek silindi.')).then(load); } },
        ]), 'ghost sm icon', 'more')))));
    const body = [
      k.in_use ? h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Kayıt oyunda: yedek alabilirsin, geri yükleme için oyunu ve sunucuyu kapat.'))) : null,
      h('div', { class: 'row' }, note, take, btn(T('Klasör'), () => act(() => api('/api/open_folder', { ne: 'yedek', id })), 'ghost', 'folder')),
      h('div', { class: 'row wrap small muted', style: { gap: '18px' } },
        h('label', { class: 'row' }, h('span', { class: 'switch' }, tog, h('span')), T("Oyna'da otomatik yedek al")),
        h('label', { class: 'row' }, T('Saklanacak otomatik yedek'), keep),
        h('label', { class: 'row' }, T('Oyun sırasında her'), iv, T('dakikada (0: kapalı)'))),
      rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, [[N('Zaman'), ''], [N('Tür'), ''], [N('Pilot'), ''], [N('Kredi'), 'num'], [N('Uridyum'), 'num'], [N('Not'), ''], ['', '']].map(([x, c]) => h('th', { class: c }, x ? T(x) : '')))),
        h('tbody', null, rows))) : h('div', { class: 'empty' }, art('bos_kayit'), h('div', null, T('Bu kaydın yedeği yok.'))),
      h('div', { class: 'small dim' }, T('Elle alınan yedekler kendiliğinden silinmez. Otomatik yedeklerin en yeni {0} tanesi kalır.', cfg.backup_count))];
    if (m) { m.box.querySelector('.body').replaceChildren(...body.filter(Boolean)); }
    else m = modal({ title: T('Yedekler — {0}', k.ad), sub: `${k.pilot} · ${k.firma} · ${T('Seviye')} ${k.seviye}`, wide: true, body, foot: [btn(T('Kapat'), () => m.close(), '')],
      onclose: () => { if (S.page === 'kayitlar') renderSaves(); } });
  }
  load();
}

// ================================================================== OYUN AYARLARI
const MULTIPLIER_VALUES = [0, 0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4, 5, 6, 7.5, 10, 12.5, 15, 20, 25, 30, 40, 50];
const APPLY_WHEN = { 'anında': ['an', N('Anında')], 'harita': ['harita', N('Harita değişince')], 'giriş': ['giris', N('Yeniden girişte')], 'başlatma': ['baslatma', N('Sunucu yeniden başlayınca')] };
let saveTimer = null, pending = {};
function queueSave(key, value) {
  pending[key] = value;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const body = pending; pending = {};
    const r = await act(() => api('/api/ayarlar', { values: body }));
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
    const k = row.dataset.key, v = r.values[k] ?? r.default[k];
    row.classList.toggle('changed', v !== r.default[k]);
  });
  document.querySelectorAll('.set-group').forEach(card => {         // grup başlığında değişen ayar sayısı
    const n = card.querySelectorAll('.set-row.changed').length;
    card.querySelector('.grp-count').textContent = n ? ' · ' + T('{0} değişiklik', n) : '';
  });
  document.querySelectorAll('.set-sub').forEach(sub => {            // "Ayrıntılı ayarla" düğmesinde değişen alt ayar sayısı
    const n = sub.querySelectorAll('.set-row.changed').length;
    document.querySelector(`.set-row[data-key="${sub.dataset.parent}"] .set-toggle .n`).textContent = n ? T('{0} özel', n) : '';
    paintEff(sub.dataset.parent);
  });
  if (S.settingsFilter && document.querySelector('.set-tools')) S.settingsFilter(true);
}

async function renderSettings() {
  const r = await act(() => api('/api/ayarlar')); if (!r || S.page !== 'ayarlar') return;
  S.ayar = r;
  const val = k => r.values[k] ?? r.default[k];
  const presets = Object.entries(r.hazir).map(([key, p]) => h('button', { class: 'preset', onclick: async () => {
    if (await confirmBox(T('"{0}" uygulansın mı?', p.ad), T('Bütün oyun ayarları bu hazır ayarın değerlerine döner (etkinlik seçimlerin değişmez).'), { ok: T('Uygula') }))
      act(() => api('/api/ayarlar/hazir', { ad: key }), T('"{0}" uygulandı.', p.ad)).then(renderSettings);
  } }, h('b', null, p.ad), h('span', null, p.aciklama)));
  const user = Object.entries(r.sablonlar || {}).map(([key, p]) => h('div', { class: 'preset', onclick: async e => {
    if (e.target.closest('.x')) return;
    if (await confirmBox(T('"{0}" uygulansın mı?', p.ad), T('Bütün oyun ayarları bu şablonun değerlerine döner.'), { ok: T('Uygula') }))
      act(() => api('/api/ayarlar/hazir', { ad: key }), T('"{0}" uygulandı.', p.ad)).then(renderSettings);
  } }, h('b', null, '★ ', p.ad), h('span', null, T('{0} değişiklik', Object.keys(p.values).length)),
    btn('', async () => { if (await confirmBox(T('Şablon silinsin mi?'), T('"{0}" şablonu silinir.', p.ad), { ok: T('Sil'), danger: true })) act(() => api('/api/ayarlar/delete_template', { ad: key })).then(renderSettings); }, 'ghost sm icon x', 'x', { title: T('Sil') })));
  const copySel = h('select', { class: 'input', style: { maxWidth: '240px' } }, (r.kayitlar || []).map(k => h('option', { value: k.id }, k.ad)));
  const saveCard = r.kayit ? h('div', { class: 'card' }, h('h2', null, icon('save'), T('Bu kaydın ayarları: {0}', r.save_name)),
    h('p', { class: 'desc' }, T('Oyun ayarları ve etkinlik seçimleri her kayda özgüdür; etkin kayıt değişince ayarlar da değişir.')),
    (r.kayitlar || []).length ? h('div', { class: 'row' }, copySel,
      btn(T('Bu kayıttan kopyala'), async () => {
        const src = r.kayitlar.find(k => k.id === copySel.value);
        if (src && await confirmBox(T('Ayarlar kopyalansın mı?'), T('"{0}" kaydının bütün oyun ayarları ve etkinlik seçimleri bu kayda kopyalanır.', src.ad), { ok: T('Kopyala') }))
          act(() => api('/api/ayarlar/copy', { kaynak: src.id }), T('Ayarlar kopyalandı.')).then(renderSettings);
      }, 'sm', 'copy')) : null) : null;
  const presetCard = h('div', { class: 'card' }, h('h2', null, icon('star'), T('Hazır ayarlar')),
    h('p', { class: 'desc' }, T('Bir ayar kümesini tek tıkla uygula ya da şimdiki ayarlarını şablon olarak sakla.')),
    h('div', { class: 'preset-bar' }, presets, user),
    h('div', { class: 'row', style: { marginTop: '12px' } },
      btn(T('Şimdiki ayarları şablon olarak kaydet'), async () => { const v = await promptBox(T('Şablon olarak kaydet'), T('Şablon adı'), ''); if (v) act(() => api('/api/ayarlar/save_template', { ad: v }), T('Şablon kaydedildi.')).then(renderSettings); }, 'sm', 'save'),
      h('span', { class: 'spacer' }),
      btn(T('Hepsini varsayılana döndür'), async () => { if (await confirmBox(T('Varsayılana dönülsün mü?'), T('Bütün oyun ayarları varsayılana döner (etkinlik seçimlerin değişmez).'), { ok: T('Döndür') })) act(() => api('/api/ayarlar/sifirla', {}), T('Varsayılana dönüldü.')).then(renderSettings); }, 'ghost sm', 'undo')));
  const info = h('div', { class: 'alert bilgi' }, icon('info'), h('div', null,
    h('span', { id: 'saved-note' }, T('Değişiklikler kendiliğinden kaydedilir.')), ' ' + T('Etiketler ne zaman geçerli olduğunu gösterir:') + ' ',
    ...Object.values(APPLY_WHEN).map(([c, t]) => [h('span', { class: 'tag ' + c }, T(t)), ' ']),
    r.server_running ? h('div', { style: { marginTop: '4px' } }, T('Sunucu açık: "Anında" ayarlar oyunda hemen değişir.')) : null));
  S.settingsOpen = S.settingsOpen || {};
  const groups = r.gruplar.map(g => {
    const items = r.sema.filter(s => s.grup === g.anahtar && !s.parent);
    if (!items.length) return null;
    return h('div', { class: 'card set-group', 'data-grup': g.anahtar }, h('h2', null, g.ad, h('span', { class: 'muted small grp-count' })),
      items.map(s => {
        const row = settingRow(s, val(s.anahtar), r.default[s.anahtar]), kids = r.sema.filter(c => c.parent === s.anahtar);
        return kids.length ? [row, subPanel(row, kids, val, r.default)] : row;
      }));
  }).filter(Boolean);
  // arama, yalnız değişenler, grup kısayolları (seçimler sayfa yenilenince de kalır)
  const q = h('input', { class: 'input', type: 'search', placeholder: T('Ayar ara (ad ya da açıklama)…'), value: S.settingsSearch || '' });
  const only = h('input', { type: 'checkbox', checked: !!S.settingsChanged });
  const none = h('div', { class: 'card muted', hidden: true }, T('Aramaya uyan ayar yok.'));
  // keep: kayıttan sonra (markChanged) yalnız gösterir, görünen satırı gizlemez (varsayılana dönen satır düzenlerken kaybolmasın).
  // Alt ayar üstünün adıyla da aranır; uyan alt ayarın üstü görünür ve bölümü açılır.
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
      h('label', { class: 'row', style: { gap: '8px' } }, h('span', { class: 'switch' }, only, h('span')), T('Yalnız değişenler'))),
    h('div', { style: { marginTop: '10px' } }, jump));
  $('#content').replaceChildren(h('div', { class: 'stack' }, saveCard, presetCard, info, tools, none, ...groups));
  apply();
  markChanged();
}

function settingRow(s, v, def) {
  const [tc, tagText] = APPLY_WHEN[s.uygulama] || ['', s.uygulama];
  // alt ayar (s.ust): uygulama etiketi üstünde; yerine etkin çarpan (paintEff). data-v: gösterilen değer (sürgü bırakılmadan da)
  const row = h('div', { class: 'set-row' + (s.parent ? ' sub' : ''), 'data-key': s.anahtar, 'data-v': v });
  // bağlı ayar (s.kosul): yalnız o açma kapama ayarı açıkken, onun altında görünür
  if (s.condition) { row.dataset.condition = s.condition; row.classList.toggle('condition-off', !(S.ayar.values[s.condition] ?? S.ayar.default[s.condition])); }
  const head = h('div', null, h('div', { class: 'name' }, s.ad, s.parent ? h('span', { class: 'eff' }) : h('span', { class: 'tag ' + tc }, T(tagText))),
    h('div', { class: 'help' }, s.aciklama));
  let ctl;
  // sürgü önerilen aralıkta (min..max); sayı kutusuna elle sinir'e dek her değer yazılır (settings.py), aralığın dışı "elle" işaretli
  const top = s.sinir ?? s.max;
  const over = h('span', { class: 'tag elle', title: T('Önerilen aralığın ({0} – {1}) dışında; elle yazılabilen en büyük değer {2}.', fmtMult(s.min ?? 0), fmtMult(s.max ?? 0), fmtMult(top)) }, T('Elle'));
  const markOver = x => { over.hidden = !(x > s.max); };
  if (s.tur === 'carpan') {
    const vals = MULTIPLIER_VALUES.filter(x => x >= s.min && x <= s.max);
    if (!vals.includes(s.max)) vals.push(s.max);
    const near = x => vals.reduce((best_i, y, i) => Math.abs(y - x) < Math.abs(vals[best_i] - x) ? i : best_i, 0);
    const lab = h('span', { class: 'mult' }, '×' + fmtMult(v));
    const range = h('input', { type: 'range', min: 0, max: vals.length - 1, step: 1, value: near(v) });
    const num = h('input', { class: 'input num', type: 'number', min: s.min, max: top, step: 'any', value: v, title: T('En çok {0}', fmtMult(top)) });
    const paint = () => range.style.setProperty('--p', (range.value / (vals.length - 1) * 100) + '%');
    const show = x => { num.value = x; lab.textContent = '×' + fmtMult(x); markOver(x); row.dataset.v = x; paintEff(s.parent || s.anahtar); };
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
    ctl = h('div', { class: 'ctl' }, over, num, s.unit ? h('span', { class: 'mult' }, s.unit) : null, reset);
  } else if (s.tur === 'bool') {
    const cb = h('input', { type: 'checkbox', checked: v, onchange: e => {
      queueSave(s.anahtar, e.target.checked);
      document.querySelectorAll(`.set-row[data-condition="${s.anahtar}"]`).forEach(c => c.classList.toggle('condition-off', !e.target.checked));
    } });
    ctl = h('div', { class: 'ctl' }, h('label', { class: 'switch' }, cb, h('span')));
  } else if (s.tur === 'seviye') {
    // seçeneklerin açıklaması ve rengi şemadan (settings.py: secenek_aciklama, renkler; panel dilinde gelir)
    const say = i => (s.option_description || [])[i] || '';
    const desc = h('div', { class: 'level-desc' }, say(v));
    const seg = h('div', { class: 'seg' }, s.options.map((name, i) => h('button', { class: (i === v ? 'on ' : '') + ((s.colors || [])[i] || ''), onclick: e => {
      seg.querySelectorAll('button').forEach(b => b.classList.remove('on')); e.currentTarget.classList.add('on'); desc.textContent = say(i); queueSave(s.anahtar, i);
    } }, name)));
    ctl = h('div', { class: 'ctl', style: { flexDirection: 'column', alignItems: 'flex-end' } }, seg);
    head.append(desc);
  }
  row.append(head, ctl);
  return row;
}
// alt ayarlar (settings.py ALTLAR): üstün satırında "Ayrıntılı ayarla" düğmesi, altında açılan bölüm (açıklığı S.ayarAcik'te kalır)
function subPanel(row, kids, val, defs) {
  const key = row.dataset.key;
  const sub = h('div', { class: 'set-sub', 'data-parent': key },
    h('p', { class: 'sub-note' }, T('Her satırın çarpanı yukarıdaki genel çarpanla çarpılır: genel ×2 ve satır ×3 ise ×6.')),
    kids.map(c => settingRow(c, val(c.anahtar), defs[c.anahtar])));
  row.firstChild.append(h('button', { class: 'set-toggle', type: 'button', onclick: () => { S.settingsOpen[key] = sub.hidden; setOpen(row, sub, sub.hidden); } },
    icon('chevR'), T('Ayrıntılı ayarla'), h('span', { class: 'cnt' }, kids.length), h('span', { class: 'n' })));
  setOpen(row, sub, !!S.settingsOpen[key]);
  return sub;
}
function setOpen(row, sub, open) {
  sub.hidden = !open;
  const b = row.querySelector('.set-toggle'); b.classList.toggle('open', open); b.setAttribute('aria-expanded', String(open));
}
function paintEff(parent) {          // alt ayarların etkin çarpanı (genel x alt): genel x1 değilse "toplam ×6"
  const p = document.querySelector(`.set-row[data-key="${parent}"]`), sub = document.querySelector(`.set-sub[data-parent="${parent}"]`);
  if (!p || !sub) return;
  sub.querySelectorAll('.set-row').forEach(c => { c.querySelector('.eff').textContent = +p.dataset.v === 1 ? '' : T('toplam ×{0}', fmtMult(p.dataset.v * c.dataset.v)); });
}
const fmtMult = x => (Math.round(x * 100) / 100).toLocaleString(LOC());

// ================================================================== ETKİNLİKLER
async function renderEvents(list) {
  const r = list || await act(() => api('/api/etkinlikler')); if (!r || S.page !== 'etkinlikler') return;
  const set = (key, v) => act(() => api('/api/etkinlikler', { changes: { [key]: v } })).then(x => x && renderEvents(x));
  const bulk = (to, kind) => act(() => api('/api/etkinlikler', { hepsi: to, kind }), T('Güncellendi.')).then(x => x && renderEvents(x));
  const row = e => {
    const state = e.durum || 'takvim';
    const status = e.etkin ? badge(e.durum === 'acik' && !e.in_calendar ? T('Açık (elle)') : T('Açık'), 'ok')
      : e.suppressed_by ? badge(T('Kapalı (çakışma: {0})', e.suppressed_by), 'err')
      : badge(e.durum === 'kapali' && e.in_calendar ? T('Kapalı (elle)') : T('Kapalı'), e.durum === 'kapali' ? 'err' : '');
    const cal = e.in_calendar ? (e.time_left_sec != null ? T('takvimde açık · {0} kaldı', fmtDur(e.time_left_sec)) : T('takvimde açık'))
      : (e.next_day != null ? T('takvimde {0} gün sonra', e.next_day) : T('takvimde şu an kapalı'));
    return h('div', { class: 'ev-row' },
      h('div', null, h('div', { class: 'name' }, e.ad, status), h('div', { class: 'help muted small' }, e.aciklama),
        h('div', { class: 'when' }, '📅 ', e.time, ' · ', cal),
        e.conflicting && e.conflicting.length ? h('div', { class: 'help muted small' }, T('Birlikte açık olamaz: {0}', e.conflicting.join(', '))) : null),
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

// ================================================================== ETKİNLİK TAKVİMİ (event_schedule.py, /api/takvim)
// Görünümler: saatlik (seçili günün 24 saati, satırlar ve seanslar), günlük (o günün ayrıntılı listesi), haftalık (pazartesiden 7 gün),
// aylık (6 haftalık ızgara). Çubuk: takvime göre dolu, elle açık çizgili, elle kapalı soluk. Zamanlar yerel saat.
const CAL = { gorunum: 'haftalik', gun: null, filter_by: { yillik: true, haftalik: true, seans: true }, ara: '', veri: null, coverage: null };
const CAL_VIEW = [['saatlik', N('Saatlik')], ['gunluk', N('Günlük')], ['haftalik', N('Haftalık')], ['aylik', N('Aylık')]];
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
const KIND_NAME = { yillik: N('Yıllık'), haftalik: N('Haftalık') };

function calRange() {
  const g = dayStart(CAL.gun || new Date());
  if (CAL.gorunum === 'haftalik') { const a = addDays(g, -((g.getDay() + 6) % 7)); return [a, addDays(a, 7)]; }
  if (CAL.gorunum === 'aylik') { const f = new Date(g.getFullYear(), g.getMonth(), 1); const a = addDays(f, -((f.getDay() + 6) % 7)); return [a, addDays(a, 42)]; }
  return [g, addDays(g, 1)];
}
function calGo(appearance, day) { if (appearance) CAL.gorunum = appearance; if (day) CAL.gun = day; renderCalendar(); }
function calShift(n) {
  const g = dayStart(CAL.gun || new Date());
  calGo(null, CAL.gorunum === 'aylik' ? new Date(g.getFullYear(), g.getMonth() + n, 1) : addDays(g, CAL.gorunum === 'haftalik' ? 7 * n : n));
}
function enterCalendar() {
  CAL.gun = CAL.gun || new Date();
  renderCalendar();
  S.timers.push(setInterval(() => { if (document.visibilityState === 'visible' && !document.querySelector('.modal')) renderCalendar(); }, 60000));
}
async function renderCalendar() {
  const [a, b] = calRange();
  let r;
  try { r = await api(`/api/takvim?bas=${a.getTime() / 1000}&bit=${b.getTime() / 1000}`); } catch (e) { toast(e.message, 'err'); return; }
  if (S.page !== 'takvim') return;
  CAL.veri = r; CAL.coverage = [a.getTime() / 1000, b.getTime() / 1000];
  drawCalendar();
}

// görünümde gösterilecek satırlar: süzgeçler; aralıkta açık olan, seansı olan ya da elle açılmış etkinlikler
function calRows() {
  const q = CAL.ara.trim().toLocaleLowerCase(LOC());
  return CAL.veri.etkinlikler.filter(e => CAL.filter_by[e.tur] && (!q || e.ad.toLocaleLowerCase(LOC()).includes(q)))
    .map(e => Object.assign({}, e, { color: calColor(e.anahtar), sessions: CAL.filter_by.seans ? e.sessions.filter(s => s.ranges.length) : [] }))
    .filter(e => e.active_ranges.length || e.ranges.length || e.sessions.length);
}
function drawCalendar() {
  const r = CAL.veri, [A, B] = CAL.coverage, g = CAL.gorunum;
  const title = g === 'aylik' ? dfmt((A + B) / 2, { month: 'long', year: 'numeric' })
    : g === 'haftalik' ? dfmt(A, { day: 'numeric', month: 'short' }) + ' – ' + dfmt(B - 1, { day: 'numeric', month: 'short', year: 'numeric' })
      : dfmt(A, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  const chip = (k, t) => h('button', { class: 'cal-filter' + (CAL.filter_by[k] ? ' on' : ''), onclick: () => { CAL.filter_by[k] = !CAL.filter_by[k]; drawCalendar(); } }, T(t));
  const search = h('input', { class: 'input', style: { width: '170px' }, placeholder: T('Etkinlik ara…'), value: CAL.ara,
    oninput: e => { CAL.ara = e.target.value; clearTimeout(CAL.searchTimer); CAL.searchTimer = setTimeout(() => { drawCalendar(); const s = $('#tk-ara'); if (s) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); } }, 250); } });
  search.id = 'tk-ara';
  const bar = h('div', { class: 'card cal-toolbar' },
    h('div', { class: 'row between wrap' },
      h('div', { class: 'seg' }, CAL_VIEW.map(([k, t]) => h('button', { class: g === k ? 'on info' : '', onclick: () => calGo(k) }, T(t)))),
      h('div', { class: 'row' }, btn('', () => calShift(-1), 'ghost sm icon', 'arrowL', { title: T('Önceki') }),
        btn(T('Bugün'), () => calGo(null, new Date()), 'sm'), btn('', () => calShift(1), 'ghost sm icon', 'arrowR', { title: T('Sonraki') }),
        h('b', { class: 'cal-title' }, title)),
      h('div', { class: 'row wrap' }, chip('yillik', N('Yıllık')), chip('haftalik', N('Haftalık')), chip('seans', N('Seanslar')), search)),
    h('div', { class: 'cal-legend small muted' }, h('span', null, h('i', { class: 'cal-sw' }), T('takvime göre')),
      h('span', null, h('i', { class: 'cal-sw forced' }), T('elle açık')), h('span', null, h('i', { class: 'cal-sw off' }), T('elle kapalı')),
      h('span', null, h('i', { class: 'cal-sw sub' }), T('seans / doğuş saati')),
      r.always_open ? h('span', { class: 'badge info' }, T('Oyun ayarı: seanslar hep açık')) : null));
  const rows = calRows();
  const view = g === 'aylik' ? calMonth(rows) : g === 'gunluk' ? calDay(rows) : calGantt(rows);
  $('#content').replaceChildren(h('div', { class: 'stack' }, bar, calSummary(r), view));
}

// ---- özet: şu an açık olanlar ve sıradakiler (görünümden bağımsız)
function calSummary(r) {
  const now = Date.now() / 1000;
  const on = r.etkinlikler.filter(e => e.etkin);
  const next = r.etkinlikler.filter(e => e.durum !== 'kapali' && e.next && e.next[0] > now + 1).sort((x, y) => x.next[0] - y.next[0]).slice(0, 8);
  const dotc = k => h('i', { class: 'cal-dot', style: { background: calColor(k) } });
  return h('div', { class: 'grid g2' },
    h('div', { class: 'card' }, h('h2', null, icon('zap'), T('Şu an açık ({0})', on.length)),
      on.length ? h('div', { class: 'chips' }, on.map(e => h('button', { class: 'chip cal-chip', onclick: () => calDetail(e.anahtar) }, dotc(e.anahtar), e.ad,
        e.durum === 'acik' && !e.in_calendar ? h('span', { class: 'dim' }, T('elle')) : e.time_left_sec != null ? h('span', { class: 'dim' }, fmtDur(e.time_left_sec)) : null)))
        : h('p', { class: 'desc' }, T('Şu an açık etkinlik yok.'))),
    h('div', { class: 'card' }, h('h2', null, icon('clock'), T('Sıradakiler')),
      next.length ? h('div', { class: 'cal-next' }, next.map(e => h('div', { class: 'row', onclick: () => calDetail(e.anahtar) }, dotc(e.anahtar),
        h('div', { class: 'grow' }, h('div', { class: 'ellipsis', style: { maxWidth: 'none' }, title: e.ad }, e.ad),
          h('div', { class: 'small muted' }, calSpan(e.next[0], e.next[1]))),     // tarih adın altında: dar kartta rozet taşmasın
        badge(T('{0} sonra', fmtDur(e.next[0] - now)), 'info'))))
        : h('p', { class: 'desc' }, T('Yakında başlayacak etkinlik yok.'))));
}

// ---- saatlik ve haftalık: zaman çizelgesi (satır başına etkinlik, altında seansları)
function calGantt(rows) {
  const [A, B] = CAL.coverage, now = Date.now() / 1000, week = CAL.gorunum === 'haftalik';
  const pct = t => Math.max(0, Math.min(100, (t - A) * 100 / (B - A)));
  const cols = week ? 7 : 24;
  const bar = (s, e, cls, color, title) => h('div', { class: 'cal-b ' + cls, style: { left: pct(s) + '%', width: Math.max(0.25, pct(e) - pct(s)) + '%', '--c': color }, title });
  const nowLine = () => now >= A && now < B ? h('div', { class: 'cal-now', style: { left: pct(now) + '%' } }) : null;
  const ticks = Array.from({ length: cols }, (_, i) => {
    if (!week) return h('div', { class: 'cal-tick' }, String(i).padStart(2, '0'));
    const d = addDays(new Date(A * 1000), i), today = dayStart(new Date()).getTime() === d.getTime();
    return h('div', { class: 'cal-tick click' + (today ? ' today' : ''), title: T('Günlük görünüm'), onclick: () => calGo('gunluk', d) },
      d.toLocaleDateString(LOC(), { weekday: 'short', day: 'numeric' }));
  });
  const evRow = e => {
    const st = e.durum, bars = st === 'acik' ? [bar(A, B, 'forced', e.color, e.ad + ' · ' + T('elle açık'))]
      : e.ranges.map(([s, x]) => bar(s, x, st === 'kapali' ? 'off' : '', e.color, e.ad + ' · ' + calSpan(s, x) + (st === 'kapali' ? ' · ' + T('elle kapalı') : '')));
    return [h('div', { class: 'cal-row' }, h('div', { class: 'cal-name', onclick: () => calDetail(e.anahtar), title: e.aciklama || e.ad },
      h('i', { class: 'cal-dot', style: { background: e.color } }), h('span', { class: 'ellipsis', style: { maxWidth: 'none' } }, e.ad),
      st ? badge(st === 'acik' ? T('elle açık') : T('elle kapalı'), st === 'acik' ? 'ok' : 'err') : null),
      h('div', { class: 'cal-track', style: { '--cols': cols } }, bars, nowLine())),
    ...e.sessions.map(s => h('div', { class: 'cal-row sub' }, h('div', { class: 'cal-name', title: s.haritalar.join(', ') }, '↳ ', h('span', { class: 'ellipsis', style: { maxWidth: 'none' } },
      s.ad + (s.haritalar.length ? ' · ' + s.haritalar.join(', ') : ''))),
      h('div', { class: 'cal-track', style: { '--cols': cols } }, s.ranges.map(([a, b, f]) => bar(a, b, 'sub' + (f === 1 ? ' cift' : ''), e.color,
        s.ad + ' · ' + calSpan(a, b) + (f === 1 ? ' · ' + T('çift ödül') : f > 1 ? ' · ' + T('giriş {0}\'e kadar', hhmm(f)) : ''))), nowLine())))];
  };
  return h('div', { class: 'card cal-gantt-card' }, rows.length ? h('div', { class: 'cal-gantt' },
    h('div', { class: 'cal-row head' }, h('div', { class: 'cal-name muted small' }, T('{0} etkinlik', rows.length)), h('div', { class: 'cal-track ticks', style: { '--cols': cols } }, ticks)),
    rows.map(evRow)) : h('div', { class: 'empty' }, art('bos_etkinlik'), h('div', null, T('Bu aralıkta gösterilecek etkinlik yok.'))));
}

// ---- günlük: seçili günün ayrıntılı listesi (bütün gün sürenler, saatli aralıklar ve seanslar sırayla)
function calDay(rows) {
  const [A, B] = CAL.coverage, now = Date.now() / 1000;
  const allDay = [], timed = [];
  for (const e of rows) {
    const iv = e.durum === 'acik' ? [[A, B]] : e.durum === 'kapali' ? [] : e.ranges;
    if (iv.some(([s, x]) => s <= A && x >= B)) allDay.push(e);
    else iv.forEach(([s, x]) => timed.push({ e, s, x, ad: e.ad }));
    e.sessions.forEach(sec => sec.ranges.forEach(([s, x, f]) => timed.push({ e, s, x, f, ad: e.ad, sub: sec.ad + (sec.haritalar.length ? ' · ' + sec.haritalar.join(', ') : '') })));
  }
  timed.sort((p, q) => p.s - q.s || p.x - q.x);
  const status = (s, x) => now >= x ? badge(T('Bitti'), '') : now >= s ? badge(T('Sürüyor · {0} kaldı', fmtDur(x - now)), 'ok') : badge(T('{0} sonra', fmtDur(s - now)), 'info');
  const dotc = e => h('i', { class: 'cal-dot', style: { background: e.color } });
  const end = new Date(B * 1000);
  return h('div', { class: 'grid g2 tk-day' },
    h('div', { class: 'card' }, h('h2', null, icon('calendar'), T('Bütün gün ({0})', allDay.length)),
      allDay.length ? h('div', { class: 'stack', style: { gap: '10px' } }, allDay.map(e => h('div', { class: 'cal-item', onclick: () => calDetail(e.anahtar) },
        h('div', { class: 'row' }, dotc(e), h('b', null, e.ad), badge(T(KIND_NAME[e.tur]), ''), e.durum ? badge(e.durum === 'acik' ? T('elle açık') : T('elle kapalı'), e.durum === 'acik' ? 'ok' : 'err') : null),
        e.aciklama ? h('div', { class: 'small muted' }, e.aciklama) : null, h('div', { class: 'small dim' }, '📅 ', e.time))))
        : h('p', { class: 'desc' }, T('Bu gün bütün gün süren etkinlik yok.'))),
    h('div', { class: 'card' }, h('h2', null, icon('clock'), T('Saatli ({0})', timed.length)),
      timed.length ? h('div', { class: 'cal-agenda' }, timed.map(t => h('div', { class: 'cal-item row' + (now >= t.x ? ' past' : ''), onclick: () => calDetail(t.e.anahtar) },
        h('span', { class: 'mono cal-time' }, hhmm(t.s) + '–' + (t.x >= B && !end.getHours() ? '24:00' : hhmm(t.x))), dotc(t.e),
        h('div', { style: { flex: 1, minWidth: 0 } }, h('div', null, t.ad), t.sub ? h('div', { class: 'small muted' }, t.sub,
          t.f === 1 ? ' · ' + T('çift ödül') : t.f > 1 ? ' · ' + T('giriş {0}\'e kadar', hhmm(t.f)) : '') : null),
        status(t.s, t.x))))
        : h('p', { class: 'desc' }, T('Bu gün saatli etkinlik ya da seans yok.'))));
}

// ---- aylık: 6 haftalık ızgara; gün hücresinde o gün açık etkinlikler (tıklayınca günlük görünüm)
function calMonth(rows) {
  const [A] = CAL.coverage, month = new Date(((CAL.coverage[0] + CAL.coverage[1]) / 2) * 1000).getMonth(), today = dayStart(new Date()).getTime();
  const heads = Array.from({ length: 7 }, (_, i) => h('div', { class: 'cal-mhead' }, addDays(new Date(A * 1000), i).toLocaleDateString(LOC(), { weekday: 'short' })));
  const cells = Array.from({ length: 42 }, (_, i) => {
    const d = addDays(new Date(A * 1000), i), s = d.getTime() / 1000, x = addDays(d, 1).getTime() / 1000;
    const items = [];
    for (const e of rows) {
      const iv = e.durum === 'acik' ? [[s, x]] : e.durum === 'kapali' ? [] : e.ranges.filter(([p, q]) => p < x && q > s);
      if (iv.length) items.push({ e, saat: iv[0][0] > s ? hhmm(iv[0][0]) : null, full: iv.some(([p, q]) => p <= s && q >= x) });
      else if (e.sessions.some(sec => sec.ranges.some(([p, q]) => p < x && q > s))) items.push({ e, saat: null, tam: false, seans: true });
    }
    items.sort((p, q) => (p.e.tur !== 'yillik') - (q.e.tur !== 'yillik') || (!p.tam) - (!q.tam));
    const max = 4;
    return h('div', { class: 'cal-cell' + (d.getMonth() !== month ? ' other' : '') + (d.getTime() === today ? ' today' : ''), onclick: () => calGo('gunluk', d) },
      h('div', { class: 'cal-dnum' }, d.getDate()),
      items.slice(0, max).map(it => h('div', { class: 'cal-mchip' + (it.e.durum === 'acik' ? ' forced' : ''), style: { '--c': it.e.color }, title: it.e.ad },
        it.saat ? h('span', { class: 'dim' }, it.saat + ' ') : null, it.e.ad)),
      items.length > max ? h('div', { class: 'small muted' }, T('+{0} daha', items.length - max)) : null);
  });
  return h('div', { class: 'card' }, h('div', { class: 'cal-month' }, heads, cells));
}

// ---- etkinliğin ayrıntısı: açıklama, takvim, bu görünümdeki aralıklar, seanslar; elle açık / kapalı seçimi
function calDetail(key) {
  const e = CAL.veri.etkinlikler.find(x => x.anahtar === key); if (!e) return;
  const now = Date.now() / 1000, st = e.durum || 'takvim';
  const set = v => act(() => api('/api/etkinlikler', { changes: { [key]: v } }), T('Güncellendi.')).then(x => { if (x) { m.close(); renderCalendar(); } });
  const iv = e.durum === 'acik' ? [] : e.ranges;
  const cur = e.next && e.next[0] <= now + 1 ? T('Takvimde açık · {0} kaldı', fmtDur(e.next[1] - now))
    : e.next ? T('Takvimde sonraki: {0} ({1} sonra)', calSpan(e.next[0], e.next[1]), fmtDur(e.next[0] - now)) : T('Takvimde yakında dönemi yok.');
  const m = modal({
    title: e.ad, sub: T(KIND_NAME[e.tur]) + ' · ' + (e.etkin ? T('şu an açık') : T('şu an kapalı')), wide: true,
    body: h('div', { class: 'stack', style: { gap: '12px' } },
      e.aciklama ? h('div', null, e.aciklama) : null,
      h('div', { class: 'kv one cal-kv' }, [[T('Takvim'), e.time], [T('Durum'), cur]].map(([a, b]) => h('div', null, h('span', { class: 'muted' }, a), h('b', null, b)))),
      h('div', null, h('div', { class: 'lbl' }, T('Bu görünümde')), iv.length ? h('div', { class: 'chips', style: { marginTop: '6px' } }, iv.slice(0, 24).map(([s, x]) => h('span', { class: 'chip' }, calSpan(s, x))),
        iv.length > 24 ? h('span', { class: 'small muted' }, T('+{0} daha', iv.length - 24)) : null)
        : h('div', { class: 'small muted' }, e.durum === 'acik' ? T('Elle açık: her zaman geçerli.') : T('Bu görünümde takvimde yok.'))),
      e.sessions.length ? h('div', null, h('div', { class: 'lbl' }, T('Seanslar ve doğuş saatleri')), h('div', { class: 'stack', style: { gap: '6px', marginTop: '6px' } },
        e.sessions.map(s => h('div', { class: 'small' }, h('b', null, s.ad), s.haritalar.length ? ' · ' + s.haritalar.join(', ') : '',
          h('div', { class: 'muted' }, s.ranges.length ? [...new Set(s.ranges.map(([a, b]) => hhmm(a) + '–' + hhmm(b)))].slice(0, 12).join(', ') : T('Bu görünümde yok')))))) : null,
      h('div', null, h('div', { class: 'lbl' }, T('Oyunda')), h('div', { class: 'seg', style: { marginTop: '6px' } },
        [['takvim', T('Takvime göre'), 'info'], ['acik', T('Açık'), 'ok'], ['kapali', T('Kapalı'), 'err']].map(([k, t, c]) =>
          h('button', { class: (st === k ? 'on ' : '') + c, onclick: () => set(k === 'takvim' ? null : k) }, t))))),
    foot: [btn(T('Etkinlikler sayfası'), () => { m.close(); go('etkinlikler'); }, 'ghost', 'calendar'), btn(T('Kapat'), () => m.close(), 'primary')],
  });
}

// ================================================================== İSTEMCİ
const versionText = (c, supported) => !c.surum ? T('Sürüm bilinmiyor')
  : c.compatible ? T('Sürüm {0} (sunucuyla uyumlu)', c.surum) : T('Sürüm {0} — sunucu {1} için yazıldı', c.surum, supported);
const checkRow = (ok, text, warn) => h('div', { class: ok ? 'ok' : warn ? 'wr' : 'no' }, icon(ok ? 'check' : warn ? 'alert' : 'x'), text);
const WINDOW_MODES = [['pencere', N('Pencere')], ['kenarliksiz', N('Kenarlıksız tam ekran')], ['tam_ekran', N('Tam ekran')]];
function resolutionList(r) {
  const res = r.resolutions.map(([w, hh]) => `${w}x${hh}`);
  const scr = r.ekran ? `${r.ekran[0]}x${r.ekran[1]}` : null;
  if (scr && !res.includes(scr)) res.push(scr);
  return { res, scr };
}

// ---- oyunu indirme (client_download.py, /api/istemci/indirme): sihirbazın oyun klasörü adımı ve İstemci sayfası
const DL_ACTIVE = st => st.calisiyor || st.partial || ['hata', 'durdu', 'bitti'].includes(st.durum);
const dlPct = st => st.toplam ? Math.floor(100 * st.alinan / st.toplam) : 0;
function dlBox(st, refresh, { haveClient = false } = {}) {      // haveClient: geçerli istemci var, yarım dosyalar yalnız silinir
  const pct = dlPct(st), run = st.calisiyor;
  const call = (path, msg) => act(() => api(path, {}), msg).then(x => { if (x) refresh(x); });
  const discard = async () => {
    if (await confirmBox(T('Yarım indirme silinsin mi?'), T('İndirilen dosyalar (proje klasöründeki istemci_indiriliyor) silinir; sonra baştan iner.'), { ok: T('Sil'), danger: true }))
      call('/api/istemci/download_delete', T('Yarım indirme silindi.'));
  };
  const head = { hazirlaniyor: T('İndirme hazırlanıyor…'), indiriliyor: T('Oyun indiriliyor: %{0}', pct), verifying: T('Dosyalar doğrulanıyor…'),
    bitti: T('Oyun indirildi ve kuruldu.'), hata: T('İndirme durdu.'), durdu: T('İndirme durduruldu (%{0}).', pct) }[st.durum]
    || (st.partial ? T('Önceki indirme yarım kaldı.') : T('Oyunu indir'));
  const info = st.durum === 'indiriliyor' ? dlInfo(st)
    : st.durum === 'bitti' ? st.hedef
    : st.durum === 'hata' ? st.hata
    : haveClient && st.partial ? T('Seçili istemci kullanılıyor; yarım kalan dosyaları silebilirsin.')
    : st.durum === 'durdu' || st.partial ? T('Sürdürünce yalnız eksik dosyalar iner.')
    : st.durum === 'bos' ? T('DarkOrbit {0} istemcisi oyunun resmî indirme sunucusundan alınıp proje klasörüne kurulur: yaklaşık 3,5 GB indirme, diskte 4,3 GB. İstemci dosyaları değiştirilmez.', (/(\d+\.\d+\.\d+)\.zip/.exec(st.url || '') || [])[1] || '')
    : '';
  const btns = run ? [btn(T('Durdur'), () => call('/api/istemci/download_stop', T('İndirme durduruluyor…')), 'ghost sm', 'stop')]
    : st.durum === 'bitti' ? []
    : [haveClient ? null : btn(st.durum === 'hata' ? T('Yeniden dene') : st.durum === 'durdu' || st.partial ? T('Sürdür') : T('İndir ve kur'), () => call('/api/istemci/indir'), 'primary sm', 'download'),
      st.partial ? btn(T('Yarım indirmeyi sil'), discard, 'ghost sm', 'trash') : null];
  return h('div', { class: 'dl-box ' + (st.durum === 'hata' ? 'err' : st.durum === 'bitti' ? 'ok' : '') },
    h('b', null, head),
    run || st.durum === 'durdu' ? h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } }))) : null,
    info ? h('div', { class: 'small muted dl-info', title: st.dosya || '' }, info) : null,
    btns.some(Boolean) ? h('div', { class: 'row wrap' }, btns) : null);
}
// indirmenin satırı: inen / toplam, hız, kalan süre, dosya
function dlInfo(st) {
  return [`${fmtBytes(st.alinan)} / ${fmtBytes(st.toplam)}`, st.hiz ? `${fmtBytes(st.hiz)}/${T('sn')}` : null,
    st.time_left_sec != null && st.hiz ? T('kalan {0}', fmtDur(st.time_left_sec)) : null, T('dosya {0}/{1}', st.done_files, st.file_count)].filter(Boolean).join(' · ');
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

// ---- macOS: panelin kurduğu Wine + DXMT ve Rosetta 2 (wine_engine.py, /api/motor): Wine / Proton kartı ve sihirbazın oyun klasörü adımı
function engineBox(m, refresh, { engine = true } = {}) {
  const call = (path, msg) => act(() => api(path, {}), msg).then(x => { if (x) refresh(x); });
  const pct = m.toplam ? Math.floor(100 * m.alinan / m.toplam) : 0, run = m.calisiyor, ros = m.rosetta;
  const rosetta = !ros.gerekli ? null : ros.var ? h('div', { class: 'check-list', style: { margin: 0 } }, checkRow(true, T('Rosetta 2 kurulu')))
    : h('div', { class: 'alert hata' }, icon('alert'), h('div', null, T("Rosetta 2 kurulu değil: oyunu açan Wine Apple Silicon'da onunla çalışır. Kurmak için macOS yönetici şifreni sorar."),
      ros.hata ? h('div', { class: 'small' }, ros.hata) : null),
      btn(ros.durum === 'kuruluyor' ? T('Kuruluyor…') : T("Rosetta'yı kur"), () => call('/api/rosetta/kur'), 'primary sm', 'download', { disabled: ros.durum === 'kuruluyor' }));
  const old = m.macos_old ? h('div', { class: 'alert uyari' }, icon('alert'), h('div', null, T('DXMT macOS 14 Sonoma ya da daha yenisini ister (bu Mac: {0}); oyun açılmayabilir.', m.macos))) : null;
  if (!engine) return h('div', { class: 'stack', style: { gap: '10px' } }, rosetta, old);
  const head = run ? (m.durum === 'kuruluyor' ? T('Wine kuruluyor…') : T('Wine ve DXMT indiriliyor: %{0}', pct))
    : m.durum === 'kurulu' ? T('Oyunu açacak Wine hazır: {0}', m.ad) : m.durum === 'hata' ? T('Wine kurulamadı.')
    : m.durum === 'durdu' ? T('Wine indirmesi durduruldu.') : T('Oyunu açacak Wine henüz kurulmadı.');
  const info = run ? [`${fmtBytes(m.alinan)} / ${fmtBytes(m.toplam)}`, m.hiz ? `${fmtBytes(m.hiz)}/${T('sn')}` : null,
      m.time_left_sec != null && m.hiz ? T('kalan {0}', fmtDur(m.time_left_sec)) : null].filter(Boolean).join(' · ')
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
function engineWatch(wrap, m, opts) {
  let sig = JSON.stringify(m);
  const draw = x => { sig = JSON.stringify(x); wrap.replaceChildren(engineBox(x, draw, opts)); };
  draw(m);
  const id = setInterval(async () => {
    if (!wrap.isConnected) { clearInterval(id); return; }
    let x; try { x = await api('/api/motor'); } catch (e) { return; }
    if (JSON.stringify(x) !== sig) draw(x);
  }, 1000);
  return id;
}

// ---- istemcinin düzeltmelerini yükleyen BepInEx (client_patch.py, /api/yama): İstemci sayfası ve sihirbazın oyun klasörü adımı
function patchBox(y, refresh) {
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
function patchWatch(wrap, y) {
  let sig = JSON.stringify(y);
  const draw = x => { sig = JSON.stringify(x); wrap.replaceChildren(patchBox(x, draw)); };
  draw(y);
  const id = setInterval(async () => {
    if (!wrap.isConnected) { clearInterval(id); return; }
    let x; try { x = await api('/api/yama'); } catch (e) { return; }
    if (JSON.stringify(x) !== sig) draw(x);
  }, 1000);
  return id;
}

// ---- Linux ve macOS: istemciyi açan Wine ya da Proton (client_runner.py; /api/istemci 'calistirici', Windows'ta null)
function runnerCard(c, cfg, saveCfg) {
  const mac = c.platform === 'darwin';
  const kinds = [['otomatik', T('Otomatik')], ['motor', T("Panelin Wine'ı")], ['wine', 'Wine'], ['proton', 'Proton'], ['ozel', T('Özel komut')]]
    .filter(([k]) => mac ? k !== 'proton' : k !== 'motor');
  const seg = h('div', { class: 'seg' }, kinds.map(([k, t]) =>
    h('button', { class: cfg.runner === k ? 'on info' : '', onclick: () => saveCfg({ runner: k, runner_path: '' }) }, t)));
  const used = c.tur === 'proton' ? `${c.ad}${c.umu ? ' (umu-run)' : ''}` : c.tur === 'ozel' ? c.yol : c.ad;
  const mWrap = mac ? h('div', { class: 'dl-wrap' }) : null;
  if (mWrap && c.motor) S.timers.push(engineWatch(mWrap, c.motor, { motor: c.tur === 'motor' }));
  const pathIn = h('input', { class: 'input mono', value: cfg.runner_path, placeholder: cfg.runner === 'ozel' ? T('ör. umu-run') : T('Boş: kendiliğinden bulunur'),
    onchange: e => saveCfg({ runner_path: e.target.value.trim() }) });
  const prefixIn = h('input', { class: 'input mono', value: cfg.wine_prefix, placeholder: c.default_prefix[c.tur] || T('Boş: Wine\'ın öntanımlısı'),
    onchange: e => saveCfg({ wine_prefix: e.target.value.trim() }) });
  const found = [...c.protons.map(p => ['proton', p.yol, p.ad]), ...c.wines.map(w => ['wine', w, 'Wine'])];
  return h('div', { class: 'card' }, h('h2', null, icon('zap'), 'Wine / Proton'),
    h('p', { class: 'desc' }, T("Oyun bir Windows programı; Linux ve macOS'ta Wine ya da Proton ile açılır. Otomatik: Linux'ta Steam'in Proton'u (umu-run kuruluysa onunla), yoksa Wine; macOS'ta panelin kendi kurduğu Wine ve DXMT (macOS'ta düz Wine oyunun Direct3D 11 grafiklerini çizemez). İstemci kendi öneğinde çalışır; önek ilk açılışta kurulur (yarım dakika kadar sürebilir).")),
    c.hata && !(mac && c.motor && !c.motor.rosetta.var) ? h('div', { class: 'alert hata' }, icon('alert'), h('div', null, c.hata))
      : h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Kullanılan: {0}', used))),
    mWrap ? h('div', { style: { marginTop: '12px' } }, mWrap) : null,
    h('div', { class: 'stack', style: { gap: '14px', marginTop: '12px' } },
      field(T('Çalıştırıcı'), seg),
      c.tur === 'motor' ? null : field(cfg.runner === 'ozel' ? T('Komut (istemcinin önüne eklenir)') : T('Yol (wine programı ya da Proton klasörü)'), pathIn),
      field(T('Önek klasörü (WINEPREFIX)'), prefixIn)),
    found.length ? [h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('Bulunanlar')),
      h('div', { class: 'stack', style: { gap: '8px', marginTop: '8px' } }, found.map(([k, route, name]) => h('div', { class: 'row' },
        badge(name, 'info'), h('span', { class: 'mono', style: { flex: 1, minWidth: 0, wordBreak: 'break-all' } }, route),
        c.tur === k && c.yol === route ? badge(T('kullanılıyor'), 'ok') : btn(T('Kullan'), () => saveCfg({ runner: k, runner_path: route }), 'sm'))))] : null,
    h('div', { class: 'small muted', style: { marginTop: '12px' } }, T('Oyun açılmazsa Sunucu sayfasındaki wine.log günlüğüne bakın.')));
}

async function renderClient(data) {
  const r = data || await act(() => api('/api/istemci')); if (!r || S.page !== 'istemci') return;
  const c = r.kontrol, cfg = r.ayarlar;
  const dlWrap = !c.valid || DL_ACTIVE(r.download) ? h('div', { class: 'dl-wrap' }) : null;
  const yWrap = c.valid && r.yama.gerekli ? h('div', { class: 'dl-wrap' }) : null;
  const saveCfg = (vals, msg = T('Kaydedildi.')) => act(() => api('/api/panel_settings', { values: vals }), msg).then(x => x && renderClient(x));
  const folderCard = h('div', { class: 'card' }, h('h2', null, icon('folder'), T('İstemci klasörü')),
    h('p', { class: 'desc' }, T('Orijinal DarkOrbit Unity istemcisinin klasörü (içinde DarkOrbit.exe ve DarkOrbit_Data olan). Güncelleme gelirse ya da klasörü taşırsan buradan seç.')),
    h('div', { class: 'path' }, c.yol || T('Seçilmedi')),
    h('div', { class: 'small muted', style: { marginTop: '6px' } }, r.secili ? T('Elle seçildi.') : T('Kendiliğinden bulundu (bilinen klasörlerdeki en uygun sürüm).')),
    h('div', { class: 'check-list' },
      checkRow(c.exe, 'DarkOrbit.exe'), checkRow(c.veri, T('DarkOrbit_Data klasörü')),
      c.valid ? checkRow(c.compatible, versionText(c, r.desteklenen), !c.compatible) : null),
    c.issues.length && !c.valid && !r.download.calisiyor ? h('div', { class: 'alert hata' }, icon('alert'), h('div', null, c.issues.join(' '))) : null,
    h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('Oyunu indir')),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Hızlı indirme')),
      h('div', { class: 'help' }, T('Açıkken oyun aynı anda 3 bağlantıyla iner; kapalıyken tek bağlantıyla (daha yavaş). Bir sonraki indirmede geçerli olur.'))),
      h('div', { class: 'ctl' }, h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: cfg.fast_download, onchange: e => saveCfg({ fast_download: e.target.checked }) }), h('span')))),
    dlWrap,
    yWrap ? [h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('İstemci düzeltmeleri (BepInEx)')), yWrap] : null,
    h('div', { id: 'proto-box' }),
    h('div', { class: 'row wrap', style: { marginTop: '12px' } },
      btn(T('Klasör seç…'), () => act(() => api('/api/istemci/select', {}), x => x.iptal ? T('İptal edildi.') : T('İstemci klasörü kaydedildi.')).then(x => x && renderClient(x)), 'primary', 'folder'),
      btn(T('Kendiliğinden bul'), () => act(() => api('/api/istemci/otomatik', {}), T('Kendiliğinden bulma açık.')).then(x => x && renderClient(x)), '', 'search'),
      btn(T('Klasörü aç'), () => act(() => api('/api/open_folder', { ne: 'istemci' })), 'ghost', 'folder')),
    r.candidates.length > 1 || (r.candidates.length === 1 && r.candidates[0].yol !== c.yol) ? [h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('Bulunan istemciler')),
      h('div', { class: 'stack', style: { gap: '8px', marginTop: '8px' } }, r.candidates.map(a => h('div', { class: 'row' },
        badge(a.surum || '?', a.compatible ? 'ok' : 'warn'), h('span', { class: 'mono', style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, title: a.yol }, a.yol),
        a.yol === c.yol ? badge(T('kullanılıyor'), 'info') : btn(T('Kullan'), () => act(() => api('/api/istemci/use', { yol: a.yol }), T('Kaydedildi.')).then(x => x && renderClient(x)), 'sm'))))] : null);

  const { res, scr } = resolutionList(r);
  const cur = `${cfg.width}x${cfg.height}`;
  const custom = !res.includes(cur);
  const sel = h('select', { class: 'input', style: { width: '220px' }, onchange: e => {
    if (e.target.value === 'ozel') { cw.style.display = ''; return; }
    const [w, hh] = e.target.value.split('x').map(Number); saveCfg({ width: w, height: hh });
  } }, res.map(x => h('option', { value: x, selected: x === cur }, x + (x === scr ? '  (' + T('ekran') + ')' : ''))), h('option', { value: 'ozel', selected: custom }, T('Özel…')));
  const wIn = h('input', { class: 'input num', type: 'number', value: cfg.width }), hIn = h('input', { class: 'input num', type: 'number', value: cfg.height });
  const cw = h('div', { class: 'row', style: { display: custom ? '' : 'none' } }, wIn, '×', hIn, btn(T('Uygula'), () => saveCfg({ width: +wIn.value, height: +hIn.value }), 'sm'));
  const mode = h('div', { class: 'seg' }, WINDOW_MODES.map(([k, t]) =>
    h('button', { class: cfg.window_mode === k ? 'on info' : '', onclick: () => saveCfg({ window_mode: k }) }, T(t))));
  const mon = h('select', { class: 'input', style: { width: '220px' }, onchange: e => saveCfg({ monitor: +e.target.value }) },
    [0, 1, 2, 3, 4].map(i => h('option', { value: i, selected: cfg.monitor === i }, i ? T('Ekran {0}', i) : T('Varsayılan'))));
  const extra = h('input', { class: 'input mono', value: cfg.extra_args, placeholder: T('ör. -force-d3d11'), onchange: e => saveCfg({ extra_args: e.target.value }) });
  const dispCard = h('div', { class: 'card' }, h('h2', null, icon('monitor'), T('Görüntü')),
    h('p', { class: 'desc' }, T('İstemciye başlatma argümanı olarak verilir; oyunun kendi grafik ayarları (2D/3D, kalite) oyun içinden.')),
    h('div', { class: 'stack', style: { gap: '14px' } },
      field(T('Pencere kipi'), mode),
      field(T('Çözünürlük'), h('div', { class: 'row wrap' }, sel, cw)),
      field(T('Ekran'), mon),
      field(T('Ek Unity argümanları (gelişmiş)'), extra),
      field(T('Başlatma komutu'), h('div', { class: 'cmd' }, r.command.join(' ')))));
  const warn = h('div', { class: 'alert uyari' }, icon('alert'), h('div', null,
    T("Klasördeki DarkorbitLauncher.exe'yi çalıştırma: istemciyi resmî sunucudan güncelleyip yerel sunucuyla uyumu bozabilir. Panel istemcinin kendi dosyalarını değiştirmez; yerel giriş adresiyle başlatır, yanına kurduğu BepInEx'le küçük düzeltmeleri yükler.")));
  const multiCfg = h('div', { class: 'card compact' }, h('h2', null, icon('users'), T('Çoklu istemci')),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Öteki kayıtlarla ek istemciler')),
      h('div', { class: 'help' }, T("Açıksa ve en az iki kaydın varsa OYNA sunucuyu çok oturumlu açar; Oyna sayfasından öteki kayıtlarınla aynı sunucuya ek istemciler açarsın. Ek istemciler pencere kipinde açılır; görüntü ayarları ortaktır."))),
      h('div', { class: 'ctl' }, h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: cfg.multi_client, onchange: e => saveCfg({ multi_client: e.target.checked }) }), h('span')))),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('En çok ek istemci')),
      h('div', { class: 'help' }, T('Her istemci yaklaşık 600 MB bellek ve bir miktar ekran kartı kullanır.'))),
      h('div', { class: 'ctl' }, h('select', { class: 'input', style: { width: '90px' }, onchange: e => saveCfg({ multi_client_max: +e.target.value }) },
        [1, 2, 3, 4, 5, 6, 7, 8].map(n => h('option', { value: n, selected: cfg.multi_client_max === n }, String(n)))))));
  $('#content').replaceChildren(h('div', { class: 'stack' }, h('div', { class: 'grid g2' }, folderCard, dispCard),
    r.runner ? runnerCard(r.runner, cfg, saveCfg) : null, multiCfg, warn));
  S.sig = S.sig || {}; S.proto = null; S.protoClient = c;
  if (dlWrap) S.timers.push(dlWatch(dlWrap, r.download, () => { toast(T('Oyun indirildi ve kuruldu.'), 'ok'); renderClient(); }, { haveClient: c.valid }));
  if (yWrap) S.timers.push(patchWatch(yWrap, r.yama));
  protoTick(true);
  S.timers.push(setInterval(() => protoTick(), 1000));
}

// ---- yeni istemciye protokol uyarlaması (tools/il2cpp/protocol_update.py; protocol_builds.py, /api/protokol)
async function protoTick(force) {
  const box = $('#proto-box'); if (!box) return;
  if (!force && !(S.proto && S.proto.calisiyor)) return;
  let r; try { r = await api('/api/protokol'); } catch (e) { return; }
  const sig = JSON.stringify(r);
  if (!force && S.sig.proto === sig) return;
  S.sig.proto = sig; S.proto = r;
  const c = S.protoClient || {}, o = r.ozet || {}, run = r.calisiyor;
  const need = c.valid && !c.compatible;
  if (!need && !run && !r.ozet && !r.hata) { box.replaceChildren(); return; }
  const kv = [[N('Eklenen'), o.eklenen], [N('Silinen'), o.silinen], [N('Kimliği değişen'), o.kimlik], [N('Alanları değişen'), o.alanlar],
    [N('Kodlaması değişen'), o.yazma], [N('Okuması değişen'), o.okuma], [N('Belirsiz alan'), o.ambiguous]].filter(([, v]) => v != null);
  const width = () => act(() => api('/api/protokol/uret', {}), T('Protokol aracı başladı.')).then(() => protoTick(true));
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
        need && !run ? btn(T('Yeni istemciyi uyarla'), width, 'primary sm', 'refresh') : null,
        !run && r.is === 'uret' && !r.hata && o.surum && o.surum !== r.etkin ? btn(T('{0} protokolünü uygula', o.surum), use, 'sm', 'check') : null,
        !run && r.is === 'uygula' && !r.hata ? h('span', { class: 'small' }, T('Uygulandı; oyun sunucusu yeniden başlatılınca yeni protokolle çalışır.')) : null))));
}

// ================================================================== SUNUCU
let logState = { ad: 'gs.log', row: 400, filter_by: '', oto: true };
async function renderServer() {
  const cfg = await act(() => api('/api/panel_settings')); if (!cfg || S.page !== 'sunucu') return;
  S.panelCfg = cfg;
  const saveCfg = vals => act(() => api('/api/panel_settings', { values: vals }), T('Kaydedildi.')).then(() => renderServer());
  const seg = (key, opts) => h('div', { class: 'seg' }, opts.map(([k, t]) => h('button', { class: cfg[key] === k ? 'on info' : '', onclick: () => saveCfg({ [key]: k }) }, t)));
  const behav = h('div', { class: 'card compact' }, h('h2', null, icon('sliders'), T('Davranış')),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('İstemci kapanınca')), h('div', { class: 'help' }, T('Oyundan çıkınca panelin açtığı sunucular ne olsun?'))),
      h('div', { class: 'ctl' }, seg('istemci_kapaninca', [['kapat', T('Sunucuları kapat')], ['acik', T('Açık bırak')]]))),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Panel penceresi kapanınca')), h('div', { class: 'help' }, T('Oyun sürüyorsa beklenir, sonra panel ve sunucular kapanır; ya da her şey hemen kapanır.'))),
      h('div', { class: 'ctl' }, seg('pencere_kapaninca', [['bekle', T('Oyun bitince kapat')], ['kapat', T('Hemen kapat')]]))),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Günlükleri döndür')), h('div', { class: 'help' }, T("5 MB'ı geçen günlükler başlatmada .1, .2, .3 olarak saklanır."))),
      h('div', { class: 'ctl' }, h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: cfg.rotate_logs, onchange: e => saveCfg({ rotate_logs: e.target.checked }) }), h('span')))));
  const ports = h('div', { class: 'card' }, h('h2', null, icon('link'), T('Portlar')),
    h('p', { class: 'desc' }, T('Sunucu başlamıyorsa portları başka bir süreç (önceki oturumdan kalan sunucu ya da başka program) tutuyor olabilir.')),
    h('div', { id: 'port-list' }), h('div', { class: 'row' }, btn(T('Portları denetle'), () => checkPorts(), 'sm', 'search')));
  const logs = h('div', { class: 'card' },
    h('div', { class: 'row between wrap' }, h('h2', null, icon('note'), T('Günlükler')),
      h('div', { class: 'row wrap' },
        h('input', { class: 'input', style: { width: '180px' }, placeholder: T('Süz…'), value: logState.filter_by, oninput: e => { logState.filter_by = e.target.value; loadLog(); } }),
        h('select', { class: 'input', style: { width: '110px' }, onchange: e => { logState.row = +e.target.value; loadLog(); } },
          [200, 400, 1000, 3000].map(n => h('option', { value: n, selected: logState.row === n }, T('{0} satır', n)))),
        h('label', { class: 'row small muted' }, h('span', { class: 'switch' }, h('input', { type: 'checkbox', checked: logState.oto, onchange: e => { logState.oto = e.target.checked; } }), h('span')), T('Canlı')),
        btn('', () => loadLog(), 'ghost sm icon', 'refresh', { title: T('Yenile') }),
        btn(T('Klasör'), () => act(() => api('/api/open_folder', { ne: 'gunlukler' })), 'ghost sm', 'folder'),
        btn(T('Temizle'), async () => { if (await confirmBox(T('Günlük temizlensin mi?'), T('{0} boşaltılır.', logState.ad), { ok: T('Temizle'), danger: true })) act(() => api('/api/gunluk/temizle', { ad: logState.ad }), T('Temizlendi.')).then(loadLog); }, 'ghost sm', 'trash'))),
    h('div', { class: 'log-tabs', id: 'log-tabs', style: { margin: '10px 0' } }), h('div', { class: 'log-view', id: 'log-view' }));
  $('#content').replaceChildren(h('div', { class: 'stack' }, h('div', { class: 'grid g3', id: 'srv-cards' }), h('div', { class: 'grid g2' }, behav, ports), logs));
  S.sig = {};
  renderServerCards();
  loadLog();
  S.timers.push(setInterval(() => { if (logState.oto && document.visibilityState === 'visible') loadLog(true); }, 2000));
}

function renderServerCards() {
  const box = $('#srv-cards'), d = S.durum; if (!box || !d) return;
  // imza ekrandaki süre metniyle (fmtDur): saniyelik sure_sn her yoklamada kartları yeniden kurup fare altındaki düğmenin tıklamasını yutuyordu
  const s = d.processes, duration = x => x && Object.assign({}, x, { sure_sn: x.sure_sn == null ? null : fmtDur(x.sure_sn) });
  const sig = JSON.stringify([Object.assign({}, s, { servers: { web: duration(s.servers.web), oyun: duration(s.servers.oyun) }, istemci: duration(s.istemci) }), d.oyna.calisiyor]);
  if (S.sig.srv === sig) return; S.sig.srv = sig;
  const busy = d.oyna.calisiyor, cl = s.istemci.durum === 'acik';
  const card = (title, iconEl, st, ports, extra, actions) => h('div', { class: 'card status-card' },
    h('div', { class: 'big' }, icon(iconEl), title), h('div', { class: 'row', style: { marginTop: '8px' } }, dot(stCls(st.durum)), h('b', null, stText(st.durum)),
      st.pid ? h('span', { class: 'muted small' }, `PID ${st.pid} · ${fmtDur(st.sure_sn)}`) : null, st.exit_code != null && st.durum === 'coktu' ? badge(T('çıkış {0}', st.exit_code), 'err') : null),
    ports ? h('div', { class: 'ports' }, Object.entries(ports).map(([p, on]) => badge(on ? T('{0} dinliyor', p) : T('{0} kapalı', p), on ? 'ok' : ''))) : h('div', { style: { height: '12px' } }),
    extra, h('div', { class: 'actions' }, actions));
  const w = s.servers.web, o = s.servers.oyun, srvOn = w.durum === 'acik' || o.durum === 'acik';
  box.replaceChildren(
    card(T('Web sunucusu'), 'link', w, w.ports, h('div', { class: 'small muted' }, T('İstemcinin web girişi, harita listesi, dil seçimi.')), [btn(T('Günlük'), () => showLog('http.log'), 'sm'), btn(T('Konsol'), () => showLog('web_konsol.log'), 'ghost sm')]),
    card(T('Oyun sunucusu'), 'server', o, o.ports, h('div', { class: 'small muted' }, s.kayit ? T('Kayıt: {0}', s.kayit) + (s.control_channel ? ' · ' + T('kontrol kanalı açık (8099)') : '') : T('Oyun dünyası, kayıt, sohbet (7771).')),
      [srvOn ? btn(T('Durdur'), () => act(() => api('/api/sunucu/durdur', {}), T('Durduruldu.')), 'danger sm', 'stop', { disabled: cl || busy, title: cl ? T('Önce oyunu kapatın') : '' })
        : btn(T('Başlat'), () => act(() => api('/api/oyna', { server_only: true })), 'primary sm', 'play', { disabled: busy }),
      // yalnız simge: dört düğme kart genişliğine sığsın, "Konsol" tek başına alta düşmesin
      btn(null, () => act(() => api('/api/sunucu/restart', {}), T('Yeniden başlatıldı.')), 'sm icon', 'refresh', { disabled: busy || !srvOn, title: T('Yeniden başlat') + ' — ' + T('Oyun açıksa istemci yeniden bağlanmalı') }),
      btn(T('Günlük'), () => showLog('gs.log'), 'ghost sm'), btn(T('Konsol'), () => showLog('oyun_konsol.log'), 'ghost sm')]),
    card(T('İstemci'), 'monitor', s.istemci, null, h('div', { class: 'small muted' }, s.istemci.son ? T('Son kapanış {0} · {1} açık kaldı', s.istemci.son.time, fmtDur(s.istemci.son.sure_sn)) : T('Orijinal Unity istemcisi.')),
      [cl ? btn(T('Kapat'), async () => { if (await confirmBox(T('İstemci kapatılsın mı?'), T('Oyun penceresi kapatılır.'), { ok: T('Kapat'), danger: true })) act(() => api('/api/istemci/kapat', {})); }, 'danger sm', 'power')
        : btn(T('Oyna'), () => { go('oyna'); act(() => api('/api/oyna', {})); }, 'orange sm', 'play', { disabled: busy }),
      btn(T('Günlük'), () => showLog('client.log'), 'ghost sm')]));
}

async function checkPorts() {
  const box = $('#port-list'); if (!box) return;
  box.replaceChildren(h('div', { class: 'row muted small' }, h('span', { class: 'spin' }), T('Denetleniyor…')));
  const r = await act(() => api('/api/portlar')); if (!r) { box.replaceChildren(); return; }
  box.replaceChildren(r.length ? h('div', { class: 'stack', style: { gap: '8px', marginBottom: '12px' } }, r.map(p => h('div', { class: 'alert ' + (p.ours ? 'uyari' : 'hata') }, icon('alert'),
    h('div', null, h('b', null, `${p.port} (${p.ad})`), ` — ${p.process} (PID ${p.pid ?? '?'})`, h('div', { class: 'mono dim', style: { marginTop: '3px' } }, p.command || ''),
      p.ours ? h('div', { class: 'small' }, T('Bu projenin önceki oturumdan kalan sunucusu.')) : h('div', { class: 'small' }, T('Başka bir program: panel kapatmaz; kendiniz kapatın.'))),
    p.ours ? btn(T('Kapat'), () => act(() => api('/api/portlar/kapat', { pid: p.pid }), T('Süreç kapatıldı.')).then(() => checkPorts()), 'sm', 'x') : null)))
    : h('div', { class: 'row small', style: { marginBottom: '12px', color: 'var(--ok)' } }, icon('check'), T('Panel dışında portları tutan süreç yok.')));
}

function showLog(name) { logState.ad = name; loadLog(); const v = $('#log-view'); if (v) v.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
async function loadLog(quiet) {
  const view = $('#log-view'); if (!view) return;
  let r;
  try { r = await api('/api/gunluk?ad=' + encodeURIComponent(logState.ad) + '&satir=' + logState.row); } catch (e) { if (!quiet) toast(e.message, 'err'); return; }
  const tabs = $('#log-tabs');
  if (tabs) tabs.replaceChildren(...r.liste.map(g => h('button', { class: 'btn sm ' + (g.ad === logState.ad ? 'primary' : 'ghost'), onclick: () => { logState.ad = g.ad; loadLog(); } },
    g.ad, g.boyut != null ? h('span', { class: 'dim', style: { fontWeight: 400 } }, fmtBytes(g.boyut)) : null)));
  const atBottom = view.scrollHeight - view.scrollTop - view.clientHeight < 40;
  const f = logState.filter_by.toLowerCase();
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
// ---- güncellemeler (updater.py, /api/guncelleme): GitHub'daki son sürüm, otomatik kurulum
const UPD_TEXT = { guncel: N('Panel güncel.'), var: N('Yeni sürüm var.'), indiriliyor: N('Yeni sürüm indiriliyor…'), kuruluyor: N('Yeni sürüm kuruluyor…'),
  kuruldu: N('Yeni sürüm kuruldu: oyun ve sunucular kapalıysa panel şimdi yeniden başlar.'), bilinmiyor: N('Henüz denetlenmedi.'),
  yerel_degisiklik: N("GitHub'da yeni sürüm var, ama bu kopyada yerel değişiklikler var: güncellemeyi git ile al."),
  yerelde_ileri: N("Bu kopyada GitHub'a gönderilmemiş commit'ler var: kurulacak bir şey yok.") };
const fmtVersion = v => v && v.surum ? v.surum.slice(0, 7) + (v.tarih ? ' · ' + new Date(v.tarih).toLocaleString(LOC(), { dateStyle: 'medium', timeStyle: 'short' }) : '') : T('bilinmiyor');
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
    const save = k => act(() => api('/api/panel_settings', { values: { guncelleme: k } }), T('Kaydedildi.')).then(x => x && load());
    const toggle = on => {                               // kapalıyken yeni sürüm yalnız haber verilir (bildir)
      save(on ? 'otomatik' : 'bildir');
      if (!on) { const m = modal({ title: T('Otomatik güncelleme kapatıldı'), body: T('Gün içinde çok sık güncelleme çıkabiliyor; sık sık kontrol etmeniz önerilir.'),
        foot: [btn(T('Tamam'), () => m.close(), 'primary')] }); }
    };
    body.replaceChildren(h('div', null,                  // h() boşları atlar (replaceChildren null'ı metin yapar)
      h('div', { class: 'kv', style: { maxWidth: '620px' } },
        h('div', null, T('Kurulu sürüm'), h('b', null, fmtVersion(r.kurulu))),
        h('div', null, 'GitHub', h('b', null, r.son ? fmtVersion(r.son) : '—')),
        h('div', null, T('Kurulum biçimi'), h('b', null, r.kurulu.bicim === 'git' ? T('Git klonu (git ile ileri sarılır)') : T('İndirilmiş ZIP'))),
        h('div', null, T('Son denetim'), h('b', null, r.last_check ? fmtWhen(new Date(r.last_check * 1000).toISOString()) : '—'))),
      r.son && r.son.message && r.durum === 'var' ? h('div', { class: 'small muted', style: { marginTop: '6px' } }, T('Son değişiklik: {0}', r.son.message)) : null,
      h('div', { class: 'alert ' + cls, style: { marginTop: '12px' } }, icon(cls === 'bilgi' ? 'info' : 'alert'),
        h('div', null, text, r.durum === 'indiriliyor' ? ' ' + (pct != null ? pct + '% · ' : '') + fmtBytes(r.alinan) : '',
          r.durum === 'var' && !r.idle ? h('div', { class: 'small' }, T('Oyun, sunucular ya da başka bir iş açık: kapanınca kurulabilir.')) : null)),
      r.durum === 'indiriliyor' && pct != null ? h('div', { class: 'meter', style: { marginTop: '8px' } }, h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } }))) : null,
      h('div', { class: 'stack', style: { gap: '12px', marginTop: '14px' } },
        h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Otomatik güncelleme')),
          h('div', { class: 'help' }, T('Açıkken yeni sürüm oyun ve sunucular kapanınca kendiliğinden kurulur; kapalıyken yalnız haber verilir.'))),
          h('div', { class: 'ctl' }, h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: r.ayar === 'otomatik', onchange: e => toggle(e.target.checked) }), h('span')))),
        h('div', { class: 'row wrap' },
          btn(T('Şimdi denetle'), () => act(() => api('/api/guncelleme/check', {})).then(x => x && draw(x)), '', 'refresh', { disabled: run }),
          r.durum === 'var' ? btn(T('Güncellemeyi kur'), () => act(() => api('/api/guncelleme/kur', {})).then(x => x && draw(x)), 'primary', 'download', { disabled: !r.idle }) : null,
          h('span', { class: 'small muted mono' }, r.storage)))));
  };
  const load = () => api('/api/guncelleme').then(draw).catch(() => {});
  load();
  S.timers.push(setInterval(() => { if (card.isConnected) load(); }, 2000));
  return card;
}

// ---- Discord Rich Presence (discord_rp.py, /api/discord_rp): Discord profilinde oyunun anlık hâli; oyuncu neyin görüneceğini seçer
const RP_FIELDS = [['rp_pilot', N('Pilot adı'), N('Oyundaki adın (varsayılan kapalı).')], ['rp_klan', N('Klan etiketi'), N('Adın önünde [ETİKET].')],
  ['rp_gemi', N('Gemi'), N('Etkin geminin adı.')], ['rp_seviye', N('Seviye'), N('Pilotun seviyesi.')],
  ['rp_harita', N('Harita'), N('Harita adı ve bölgenin görseli.')], ['rp_durum', N('Ne yaptığın'), N('Savaştaki hedef, kapı dalgası, güvenli bölge.')],
  ['rp_firma', N('Firma'), N('Firmanın amblemi (küçük görsel).')], ['rp_sure', N('Oturum süresi'), N('Oyuna girdiğinden beri geçen süre.')],
  ['rp_grup', N('Grup'), N('Arkadaşlarınla Oyna: sunucundaki oyuncu sayısı.')], ['rp_butonlar', N('Düğmeler'), N("Discord sunucusu ve GitHub bağlantısı (başkaları görür).")],
  ['rp_panelde', N('Oyun kapalıyken'), N('Yalnız panel açıkken de "Panelde" görünür.')]];
const RP_STATUS = { bagli: [N("Discord'a bağlı"), 'ok'], discord_yok: [N('Discord açık değil'), 'warn'], hata: [N('Hata'), 'err'], kapali: [N('Kapalı'), ''] };
function rpCard() {
  const head = h('span', { class: 'rp-status' });
  const body = h('div', { class: 'rp-govde' });
  const card = h('div', { class: 'card' }, h('h2', null, icon('users'), 'Discord Rich Presence', head),
    h('p', { class: 'desc' }, T('Discord profilinde OpenOrbit oynadığın ve oyunda ne yaptığın görünür. Discord masaüstü uygulaması açık olmalı; neyin görüneceğini aşağıdan seç.')), body);
  let sig = '', start = null;
  const local = k => 'images/discord/' + k + '.webp';     // Discord'daki varlığın adı (OP-018)
  const duration = () => { const s = Math.max(0, Math.floor(Date.now() / 1000 - start)), p = n => String(n).padStart(2, '0');
    return T('{0} geçti', (s >= 3600 ? p(Math.floor(s / 3600)) + ':' : '') + p(Math.floor(s % 3600 / 60)) + ':' + p(s % 60)); };
  const save = vals => act(() => api('/api/panel_settings', { values: vals })).then(x => x && load());
  const draw = r => {
    const s = JSON.stringify(r); if (s === sig) return; sig = s;
    const a = r.ayarlar, e = r.etkinlik, on = a.discord_rp, [dt, dc] = RP_STATUS[r.durum] || RP_STATUS.kapali;
    head.replaceChildren(badge(T(dt), dc));
    const sw = (k, dis) => h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: a[k], disabled: dis, onchange: ev => save({ [k]: ev.target.checked }) }), h('span'));
    start = e && e.timestamps ? e.timestamps.start : null;
    const g = e && e.assets || {};
    const preview = h('div', { class: 'rp-card' + (on && e ? '' : ' bos') }, h('div', { class: 'rp-top' }, T('Oynuyor')),
      on && e ? h('div', { class: 'rp-inner' },
        h('div', { class: 'rp-image' }, g.large_image ? h('img', { class: 'rp-large', src: local(g.large_image), sub: '', title: g.large_text || '' }) : null,
          g.small_image ? h('img', { class: 'rp-small', src: local(g.small_image), sub: '', title: g.small_text || '' }) : null),
        h('div', { class: 'rp-text' }, h('b', null, 'OpenOrbit'), h('div', null, e.details),
          h('div', null, e.state, e.party ? ` (${T('{0} / {1}', e.party.size[0], e.party.size[1])})` : ''),
          start ? h('div', { class: 'rp-time' }, duration()) : null)) : h('div', { class: 'small muted' }, on ? T('Şu an profilinde bir şey görünmüyor.') : T('Rich Presence kapalı.')),
      on && e && e.buttons ? h('div', { class: 'rp-buttons' }, e.buttons.map(b => h('span', null, b.label))) : null);
    body.replaceChildren(h('div', { class: 'grid g2', style: { alignItems: 'start' } },
      h('div', { class: 'stack rp-setting', style: { gap: '4px' } },
        h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Rich Presence')),
          h('div', { class: 'help' }, r.durum === 'discord_yok' ? T('Discord açılınca kendiliğinden bağlanır.') : r.durum === 'hata' ? r.hata : T('Kapatınca profilinden hemen kalkar.'))),
          h('div', { class: 'ctl' }, sw('discord_rp'))),
        h('div', { class: 'rp-fields' + (on ? '' : ' kapali') }, RP_FIELDS.map(([k, name, assist]) => h('div', { class: 'set-row sub' },
          h('div', null, h('div', { class: 'name' }, T(name)), h('div', { class: 'help' }, T(assist))), h('div', { class: 'ctl' }, sw(k, !on)))))),
      h('div', { class: 'stack', style: { gap: '8px' } }, h('div', { class: 'small muted' }, T('Profilinde böyle görünür:')), preview)));
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
    h('div', { class: 'ctl' }, ne ? btn(T('Aç'), () => act(() => api('/api/open_folder', { ne })), 'sm', 'folder') : null));
  const langSeg = h('div', { class: 'seg diller' }, I18N.list.map(({ code: k, ad: t }) => h('button', { class: I18N.lang === k ? 'on info' : '', onclick: async () => {
    if (k === I18N.lang) return;
    const x = await act(() => api('/api/panel_settings', { values: { dil: k } })); if (x) location.reload();
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
    rpCard(),
    updCard(),
    h('div', { class: 'grid g2' },
      h('div', { class: 'card' }, h('h2', null, icon('star'), T('Masaüstü kısayolu')),
        h('p', { class: 'desc' }, T('Masaüstüne OpenOrbit kısayolu koyar (DarkOrbit simgeli); çift tıklayınca bu panel açılır (konsol penceresi olmadan).')),
        r.old_shortcut ? h('div', { class: 'alert bilgi', style: { marginBottom: '12px' } }, icon('info'),
          h('div', null, T('Masaüstündeki eski kısayol (DarkOrbit) kaldırılan başlatıcıyı açıyor. Kısayol oluştur yenisini koyar, eskisini kaldırır.'))) : null,
        btn(T('Kısayol oluştur'), async () => {
          if (await act(() => api('/api/kisayol', {}), x => T('Kısayol oluşturuldu: {0}', x.yol))) renderPanel();
        }, 'primary', 'plus')),
      h('div', { class: 'card' }, h('h2', null, icon('power'), T('Paneli kapat')),
        h('p', { class: 'desc' }, T('Panel ve panelin açtığı sunucular kapanır. Oyun açıksa önce oyunu kapat.')),
        btn(T('Paneli kapat'), async () => {
          if (await confirmBox(T('Panel kapatılsın mı?'), T('Panel ve açtığı sunucular kapanır.'), { ok: T('Kapat'), danger: true }))
            act(() => api('/api/kapat', {})).then(x => { if (x) { setTimeout(() => window.close(), 400); document.body.replaceChildren(h('div', { class: 'empty', style: { paddingTop: '26vh' } }, art('baglanti_yok'), h('h3', null, T('Panel kapandı')), h('div', null, T('Bu pencereyi kapatabilirsin.')))); } });
        }, 'danger', 'power'))),
    h('div', { class: 'card' }, h('h2', null, icon('folder'), T('Klasörler')),
      pathRow(T('Proje'), r.kok, 'proje'), pathRow(T('Kayıt yuvaları'), r.kayitlar, 'kayitlar'), pathRow(T('Günlükler'), r.gunlukler, 'gunlukler'),
      pathRow(T('Oyun ayarları dosyası'), r.ayarlar), pathRow(T('Panel ayarları dosyası'), r.panel)),
    h('div', { class: 'card' }, h('h2', null, icon('info'), T('Hakkında')),
      h('div', { class: 'kv', style: { maxWidth: '520px' } }, h('div', null, T('Panel sürümü'), h('b', null, r.surum)), h('div', null, 'Python', h('b', null, r.python)),
        h('div', null, T('Panel adresi'), h('b', null, '127.0.0.1:' + r.port)), h('div', { style: { gridColumn: '1 / -1' } }, T('İnternet'), h('b', null, T('güncelleme, oyunu indirme ve oyun görselleri için')))),
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
  root.classList.add('busy');                      // yüklenirken düğmeler kilitli (çift tıklama adım atlamasın)
  root.querySelectorAll('.wz-foot button, .wz-body button').forEach(b => { b.disabled = true; });
  let p;
  try { p = await WZ_PAGES[id](); } catch (e) { p = { title: T('Bir şeyler ters gitti'), content: h('div', { class: 'alert hata' }, icon('alert'), h('div', null, e.message)) }; }
  if (token !== WZ.draw || !$('#wizard')) return;
  root.classList.remove('busy');
  const done = !!S.panelCfg?.setup_done;
  const steps = h('div', { class: 'wz-steps' }, WZ_STEPS.map(([sid, name], i) => h('span', { class: 'wz-step' + (i === WZ.step ? ' on' : i < WZ.step ? ' done' : '') },
    h('i', null, i < WZ.step ? '✓' : String(i + 1)), h('span', null, i === 0 ? 'Dil · Language' : T(name)))));
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
    h('div', { class: 'wz-head' }, h('img', { src: 'images/amblem.webp', sub: '' }),
      h('div', null, h('div', { class: 'wz-brand' }, 'OPENORBIT'), h('div', { class: 'wz-kicker' }, WZ.step === 0 ? 'Kurulum · Setup' : T('Kurulum'))), steps),
    h('div', { class: 'wz-body' }, h('div', { class: 'wz-main' }, h('h2', null, p.title), p.sub ? h('div', { class: 'wz-sub' }, p.sub) : null, p.content),
      art('dron_' + id, 'wz-art')),
    foot));
  if (p.after) p.after();
  const f = root.querySelector('.wz-body input:not([type=checkbox])'); if (f) f.focus();
}

async function skipWizard() {
  const r = await act(() => api('/api/panel_settings', { values: { setup_done: true } })); if (!r) return;
  S.panelCfg = r.ayarlar; closeWizard();
}
async function finishWizard(play) {
  const r = await act(() => api('/api/panel_settings', { values: { setup_done: true } })); if (!r) return false;
  S.panelCfg = r.ayarlar;
  if (WZ.shortcut) await act(() => api('/api/kisayol', {}), x => T('Kısayol oluşturuldu: {0}', x.yol));
  closeWizard(); go('oyna');
  if (play) act(() => api('/api/oyna', {}));
  else toast(T('Kurulum tamam. İyi uçuşlar!'), 'ok');
  return false;
}
async function chooseLang(code) {
  const r = await act(() => api('/api/panel_settings', { values: { dil: code } })); if (!r) return;
  S.panelCfg = r.ayarlar;
  await setLang(code);
  applyStatic(); buildNav(); go(S.page || 'oyna', false); renderChrome();
  wzGo(1);
}
function currentPreset(r) {
  const v = (vals, k) => vals[k] ?? r.default[k];
  return Object.keys(r.hazir).find(key => r.sema.every(s => v(r.values, s.anahtar) === v(r.hazir[key].values, s.anahtar))) || null;
}
const pick = (el, cls = 'on') => { el.parentNode.querySelectorAll(':scope > *').forEach(x => x.classList.remove(cls)); el.classList.add(cls); };

const WZ_PAGES = {
  // ---- 1. dil (her dil kendi adıyla; tarayıcının dili öne çıkar)
  dil: async () => {
    const cur = S.panelCfg?.dil, hint = cur || guessLang();
    const card = ({ code, name, coverage }) => h('button', { class: 'wz-lang' + (cur === code ? ' on' : hint === code ? ' hint' : ''), type: 'button', onclick: () => chooseLang(code) },
      h('span', { class: 'code' }, code.toUpperCase()), h('b', null, name), coverage < 100 ? h('span', null, coverage + '%') : null);
    return { title: 'Dil seçin · Choose your language', sub: 'Panel bu dilde açılır; sonra Panel sayfasından değişir. · You can change it later on the Panel page.',
      content: h('div', { class: 'wz-langs' }, I18N.list.map(card)),
      next: cur ? { label: T('İleri') } : null };
  },
  // ---- 2. hoş geldin
  hosgeldin: async () => ({
    title: T("OpenOrbit'e hoş geldin"),
    sub: T('Tek oyunculu, çevrimdışı DarkOrbit: orijinal oyun istemcisi bilgisayarındaki yerel sunucuya bağlanır.'),
    content: h('div', { class: 'stack' },
      h('div', { class: 'wz-list' }, [['folder', T('Oyun klasörünü seç'), T('Orijinal DarkOrbit istemcisinin kurulu olduğu klasör; bilgisayarında yoksa panel indirir.')],
        ['ship', T('İlk pilotunu oluştur'), T('Pilot adı ve firma: MMO, EIC ya da VRU.')],
        ['sliders', T('Oyun ayarlarını seç'), T('Hazır bir zorluk ve oyun penceresinin görüntüsü.')]].map(([iconEl, a, b], i) =>
        h('div', { class: 'wz-item' }, h('span', { class: 'wz-num' }, String(i + 1)), icon(iconEl), h('div', null, h('b', null, a), h('div', { class: 'muted small' }, b))))),
      h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Oyun resmî sunuculara bağlanmaz, istemci dosyaları değiştirilmez; internet yalnız oyunun görsellerini ilk gösterildiklerinde indirmek için kullanılır. Her şeyi sonra panelden değiştirebilirsin.')))),
    next: { label: T('Başla') },
  }),
  // ---- 3. oyun klasörü
  klasor: async () => {
    const r = await api('/api/istemci');
    const c = r.kontrol;
    let dl = r.download;
    const none = !c.valid && !r.candidates.length;
    if (none && dl.durum === 'bos' && !WZ.dlAuto) {     // oyun bulunamadı: indirmeye kendiliğinden başla (yarım kaldıysa sürdür)
      WZ.dlAuto = true;
      dl = await act(() => api('/api/istemci/indir', {})) || dl;
    }
    if (c.valid && c.compatible && dl.calisiyor) {      // indirme sürerken uyumlu istemci bulundu ya da seçildi: indirme durur
      dl = await act(() => api('/api/istemci/download_stop', {}), T('İndirme durduruldu: bulunan istemci kullanılıyor.')) || dl;
    }
    const dlWrap = (!c.valid && (none || DL_ACTIVE(dl))) || (c.valid && (dl.calisiyor || dl.partial)) ? h('div', { class: 'dl-wrap' }) : null;
    const bg = !c.valid && dl.calisiyor;
    let m = r.runner?.tur === 'motor' ? r.runner.motor : null;   // macOS: oyunu açacak Wine da kendiliğinden iner
    if (m && m.durum === 'yok' && !WZ.engineAuto) { WZ.engineAuto = true; m = await act(() => api('/api/motor/kur', {})) || m; }
    const mWrap = m ? h('div', { class: 'dl-wrap' }) : null;
    let y = c.valid && r.yama.gerekli ? r.yama : null;  // istemcinin düzeltmeleri için BepInEx de kendiliğinden kurulur
    if (y && y.durum === 'yok' && !WZ.patchAuto) { WZ.patchAuto = true; y = await act(() => api('/api/yama/kur', {})) || y; }
    const yWrap = y ? h('div', { class: 'dl-wrap' }) : null;
    const chosen = x => { if (x) drawWizard(); };
    const use = p => act(() => api('/api/istemci/use', { yol: p })).then(chosen);
    const browse = () => act(() => api('/api/istemci/select', {}), x => x.iptal ? T('İptal edildi.') : T('Oyun klasörü seçildi.')).then(chosen);
    const rows = r.candidates.map(a => h('button', { class: 'wz-opt' + (a.yol === c.yol ? ' on' : ''), type: 'button', onclick: () => use(a.yol) },
      h('span', { class: 'wz-radio' }), h('span', { class: 'mono' }, a.yol), badge(a.surum || '?', a.compatible ? 'ok' : 'warn')));
    return {
      title: T('DarkOrbit oyun klasörü'),
      sub: T("Orijinal DarkOrbit istemcisinin klasörü: içinde DarkOrbit.exe ve DarkOrbit_Data olmalı. Panel istemcinin kendi dosyalarını değiştirmez; yanına küçük düzeltmeler için BepInEx kurar."),
      content: [
        rows.length ? field(T('Bulunan klasörler'), h('div', { class: 'wz-opts' }, rows))
          : c.valid ? null : h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Bilgisayarında DarkOrbit bulunamadı, bu yüzden oyun indirilip proje klasörüne kuruluyor. Kurulu bir oyunun varsa klasörünü seç.'))),
        dlWrap,
        mWrap ? field(T('Oyunu açacak Wine (macOS)'), mWrap) : null,
        yWrap ? field(T('İstemci düzeltmeleri (BepInEx)'), yWrap) : null,
        bg ? h('div', { class: 'small muted' }, T('İndirme arka planda sürer: bu arada pilotunu oluşturabilirsin.')) : null,
        dlWrap ? null : field(T('Seçili klasör'), h('div', { class: 'path' }, c.yol || T('Seçilmedi'))),
        c.yol ? h('div', { class: 'check-list', style: { margin: 0 } }, checkRow(c.exe, 'DarkOrbit.exe'), checkRow(c.veri, T('DarkOrbit_Data klasörü')),
          c.valid ? checkRow(c.compatible, versionText(c, r.desteklenen), !c.compatible) : null) : null,
        c.valid && !c.compatible ? h('div', { class: 'alert uyari' }, icon('alert'), h('div', null, T('Bu istemci sunucunun protokolünden farklı bir sürüm. Oyun yine açılabilir; sorun olursa İstemci sayfasından yeni istemciyi uyarla.'))) : null,
        h('div', { class: 'row wrap' }, btn(T('Klasör seç…'), browse, rows.length || dlWrap ? '' : 'primary', 'folder'), btn(T('Yeniden ara'), () => drawWizard(), 'ghost', 'search'))],
      next: { disabled: !c.valid && !bg }, skip: !c.valid && !bg,
      after: () => {
        if (dlWrap) WZ.timer = dlWatch(dlWrap, dl, () => drawWizard(), { haveClient: c.valid });
        if (mWrap) engineWatch(mWrap, m);              // sihirbaz yeniden çizilince kutu kalkar, yenileme kendiliğinden durur
        if (yWrap) patchWatch(yWrap, y);
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
        const x = await act(() => api('/api/kayitlar/yeni', Object.assign(f.values(), { set_active: true })), T('Pilot oluşturuldu.'));
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
    if (!WZ.display) WZ.display = { window_mode: cfg.window_mode, width: cfg.width, height: cfg.height };
    const presets = h('div', { class: 'preset-bar' }, Object.entries(r.hazir).map(([key, p]) => h('button', { class: 'preset' + (WZ.preset === key ? ' on' : ''), type: 'button',
      onclick: e => { WZ.preset = key; pick(e.currentTarget); } }, h('b', null, p.ad), h('span', null, p.aciklama))));
    const mode = h('div', { class: 'seg' }, WINDOW_MODES.map(([k, t]) => h('button', { class: WZ.display.window_mode === k ? 'on info' : '', type: 'button',
      onclick: e => { WZ.display.window_mode = k; e.currentTarget.parentNode.querySelectorAll('button').forEach(b => b.className = ''); e.currentTarget.className = 'on info'; } }, T(t))));
    const { res, scr } = resolutionList(c);
    const cur = `${WZ.display.width}x${WZ.display.height}`;
    if (!res.includes(cur)) res.push(cur);
    const sel = h('select', { class: 'input', onchange: e => { const [w, hh] = e.target.value.split('x').map(Number); WZ.display.width = w; WZ.display.height = hh; } },
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
        return !!await act(() => api('/api/panel_settings', { values: WZ.display }));
      } },
    };
  },
  // ---- 6. özet
  bitti: async () => {
    const [d, c, a] = await Promise.all([api('/api/durum'), api('/api/istemci'), api('/api/ayarlar')]);
    const k = c.kontrol, cfg = c.ayarlar, pre = currentPreset(a);
    const canPlay = !!d.aktif && k.valid;
    const dlRun = !k.valid && c.download.calisiyor;
    const mode = (WINDOW_MODES.find(([x]) => x === cfg.window_mode) || [, cfg.window_mode])[1];
    const rows = [[true, T('Dil'), langOf(I18N.lang).ad],
      [k.valid, T('Oyun klasörü'), k.valid ? k.yol + (k.surum ? ' · ' + k.surum : '') : dlRun ? T('İndiriliyor: %{0} (İstemci sayfasında izleyebilirsin)', dlPct(c.download)) : T('Seçilmedi: İstemci sayfasından seç.')],
      [!!d.aktif, T('Pilot'), d.aktif ? `${d.aktif.pilot} · ${d.aktif.firma}` : T('Oluşturulmadı: Kayıtlar sayfasından oluştur.')],
      [true, T('Oyun ayarları'), pre ? a.hazir[pre].ad : T('Özel')],
      [true, T('Oyun penceresi'), `${T(mode)} · ${cfg.width}×${cfg.height}`]];
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

// ================================================================== OYUN İÇİ: ORTAK
// Mağaza, Hangar ve Skylab oyun sunucusundan (panel_channel.py: istemcinin istekleriyle aynı yol; oyundaki pencereler de güncellenir).
// Görseller ve eşya adları istemcinin BepInEx eklentisinin dökümü (/oyun_gorsel/: atlas sayfaları, dizin.json, adlar_<dil>.json).
// Üç sayfanın üstünde aynı çubuk: sayfalar arasında geçiş, cüzdan ve güvenli bölge (donanım yalnız orada değişir: panel_kanali.istasyonda).
const GI = { index: null, adlar: {}, dil: null };
async function loadGameImages() {
  const j = async n => { const r = await fetch('/game_images/' + n); if (!r.ok) throw new Error(r.status); return r.json(); };
  if (!GI.index) { try { GI.index = await j('dizin.json'); buildNav(); renderChrome(); } catch (e) { /* döküm yok: simgeler, ham adlar */ } }
  if (GI.index && GI.dil !== I18N.lang) { try { GI.adlar = await j('adlar_' + I18N.lang + '.json'); GI.dil = I18N.lang; } catch (e) { GI.adlar = {}; } }
}
// oyunun bir sprite'ı: atlas sayfasından kırpılır, kutuya (boy x boy) orantılı sığdırılır (dizin: sayfa, x, y, g, y, tam g, tam y, ox, oy)
function sprite(name, size) {
  const e = GI.index?.sprite[name], box = h('span', { class: 'sprite', style: { width: size + 'px', height: size + 'px' } });
  if (!e) return box;
  const [page, x, y, w, hh, W, H, ox, oy] = e, [pw, ph] = GI.index.pages[page], k = size / Math.max(W, H);
  box.append(h('span', { style: { width: W * k + 'px', height: H * k + 'px', position: 'relative' } }, h('span', { style: {
    position: 'absolute', left: ox * k + 'px', top: oy * k + 'px', width: w * k + 'px', height: hh * k + 'px',
    background: 'url("/game_images/' + page + '.png") ' + (-x * k) + 'px ' + (-y * k) + 'px / ' + pw * k + 'px ' + ph * k + 'px no-repeat' } })));
  return box;
}
// lootId -> sprite adı: kimliğin son parçası (lf-4_100x100); gemiler şirkete göre (aegis-eic), dronlar seviyeyle (flax-1)
function itemSprite(lid, firma) {
  const k = lid.includes('_') ? lid.slice(lid.indexOf('_') + 1) : lid, last = k.split('_').pop();
  for (const c of [last, k.replace(/_/g, '-'), k, last + '-' + firma, last + '-1'])
    for (const b of ['_100x100', '_63x63', '_top', '_30x30', '']) if (GI.index?.sprite[c + b]) return c + b;
  return null;
}
const itemName = lid => GI.adlar[lid] || lid.slice(lid.indexOf('_') + 1).replace(/[_-]/g, ' ').toUpperCase();
const gameIcon = (lid, size, firma, iconEl = 'hangar') => {
  const sp = lid && itemSprite(lid, firma), el = sp ? sprite(sp, size) : h('span', { class: 'sprite bos', style: { width: size + 'px', height: size + 'px' } }, icon(iconEl));
  if (lid) el.dataset.loot = lid;                // eşya ipucu (esyaIpucu)
  return el;
};

// ---- eşya ipucu: simgenin üstünde durunca oyunun metinleri (eklentinin dökümü metinler_<dil>.json: ad, tür, ipucu açıklaması,
// açıklama, not, kaynak; nitelik adları; dilde yoksa İngilizce) ve sunucunun değerleri (/api/esya_bilgi: hasar, kalkan, bonuslar,
// gemiler, yükseltme, satış). Örneğe özgü bilgi (yükseltme seviyesi, rastgele nitelikler, hak) simgenin bir üst öğesinin _esya'sında.
const IP = { metin: null, en: null, dil: null, bilgi: null, el: null, time: 0, kutu: null, loading: null };
const HINT_LABEL = { hasar: N('Hasar'), pvp_hasar: N('Oyunculara hasar'), kalkan: N('Kalkan'), emme: N('Hasar emme'), hiz: N('Hız'), can: N('Can'), kargo: N('Kargo'),
  lazer_carpan: N('Lazer hasarı'), isabet: N('İsabet'), tam_onarim: N('Tam onarım'), dakikada_can: N('Dakikada onarım'), hak: N('Dolum başına hak'), ek_yuva: N('Ek ekstra yuvası'),
  bekleme: N('Bekleme'), kargo_carpan: N('Kargo'), dron_kalkan: N('Dron kalkanı'), dron_lazer: N('Dron lazer hasarı'), sure: N('Süre'), en_az: N('En az bonus'),
  deger_araligi: N('Değer aralığı'), yeniden_cekme: N('Yeniden çekme hakkı'), taban_hasar: N('Temel hasar'), element: N('Element'), ek_nitelik: N('Ek nitelik'),
  savunma: N('Savunma'), atis: N('Atış'), kalite: N('Kalite'), azami_seviye: N('En yüksek seviye'), menzil: N('Menzil'), sure_sn: N('Süre (sn)'),
  seviye_bonus: N('Seviyelere göre'), booster_shield_regeneration: N('Kalkan yenilenmesi'), booster_repair: N('Onarım'), booster_collect_resources: N('Kaynak toplama'),
  booster_collect_resources_newbie: N('Kaynak toplama'), booster_ability_cooldown_time: N('Yetenek beklemesi') };
const IP_ELEMENT = { thermal: N('Termal'), corrosive: N('Korozif'), electro: N('Elektro') };
const HINT_UPGRADE = { LASER_DAMAGE_UPGRADE: N('hasar'), ROCKETLAUNCHER_DAMAGE_UPGRADE: N('hasar'), GENERATOR_SHIELD_UPGRADE: N('kalkan'), DRONE_SHIELD_UPGRADE: N('dron kalkanı'),
  DRONE_DAMAGE_UPGRADE: N('dron hasarı'), CANNON_DAMAGE_UPGRADE: N('hasar'), CANNON_DEF_UPGRADE: N('savunma'), DRIVE_DAMAGE_UPGRADE: N('hasar'), DRIVE_DEF_UPGRADE: N('savunma') };
const HINT_SLOT = { lasers: N('Lazer'), generators: N('Jeneratör'), extras: N('Ekstra'), heavy_guns: N('Roketatar'), ship_upgrades: N('Modül'), QuantumFluidCore: 'QFC',
  cannons: N('Top'), cannon_shields: N('Kırıcı'), drives: N('Sürücü'), lenses: N('Mercek'), default: N('Donanım yuvası') };
const HINT_PLACE = { SHIP: N('Gemi'), PET: 'P.E.T.', DRONE: N('Dron') };
async function loadHints() {
  const j = async n => { const r = await fetch('/game_images/' + n); if (!r.ok) throw new Error(r.status); return r.json(); };
  if (GI.index && IP.dil !== I18N.lang) {
    IP.dil = I18N.lang;
    try { IP.metin = await j('metinler_' + I18N.lang + '.json'); } catch (e) { IP.metin = null; }
    if (!IP.en && I18N.lang !== 'en') { try { IP.en = await j('metinler_en.json'); } catch (e) { /* eski döküm: yalnız adlar */ } }
  }
  if (!IP.bilgi) { try { IP.bilgi = (await api('/api/item_info')).esyalar; } catch (e) { IP.bilgi = {}; } }
}
const hintText = lid => IP.metin?.e[lid] || IP.en?.e[lid] || null;
const attributeName = a => IP.metin?.n[a] || IP.en?.n[a] || a.replace(/_/g, ' ');
const hintPercent = v => (v > 0 ? '+' : '') + (Math.round(v * 1000) / 10).toLocaleString(LOC()) + '%';
function hintValue(v, b) {
  if (typeof v === 'string') return b === 'e' ? T(IP_ELEMENT[v] || v) : v;
  return { p: () => (Math.round(v * 1000) / 10).toLocaleString(LOC()) + '%', x: () => '×' + fmtN(v), sn: () => fmtDur(v), sa: () => fmtDur(v * 3600) }[b]?.() ?? fmtN(v);
}
// açıklamadaki yer tutucular (%HOURS%, %BOOSTERVALUE% …; "+%%BOOSTERVALUE%" = "+%" ve değer) değeriyle, yoksa "…"; <br> satır sonu,
// öbür etiketler atılır
const hintPlaceholder = (s, ph) => s.replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '')
  .replace(/%([A-Za-z_]+)%/g, (m, k) => { const v = ph && (ph[k] ?? ph[k.toUpperCase()]); return v != null && v !== '' ? String(v) : '…'; });

function itemHint(lid, es, firma) {
  const txt = hintText(lid), b = IP.bilgi?.[lid] || {}, ph = b.ph;
  const row = (k, v, cls = '') => h('div', { class: 'tip-row ' + cls }, h('span', null, k), h('b', null, v));
  const body = [];
  // ipucu açıklaması kısa etki satırı; açıklamanın başıyla aynıysa (formasyonlar) yalnız açıklama
  if (txt?.[2] && !(txt[3] && txt[3].slice(0, 30) === txt[2].slice(0, 30))) body.push(h('div', { class: 'tip-effect' }, hintPlaceholder(txt[2], ph)));
  if (txt?.[3]) body.push(h('div', { class: 'tip-description' }, hintPlaceholder(txt[3], ph)));
  const values = (b.stats || []).map(([k, v, f]) => row(T(HINT_LABEL[k] || k), hintValue(v, f)));
  for (const [a, v] of b.m || []) values.push(row(attributeName(a), hintPercent(v), 'bonus'));
  if (values.length) body.push(h('div', { class: 'tip-block' }, values));
  if (b.slot_info) body.push(h('div', { class: 'tip-slots' }, Object.entries(b.slot_info).map(([k, n]) => h('span', null, T(HINT_SLOT[k] || k), h('b', null, n)))));
  for (const [y, low, t] of b.up || []) {
    const curUpgrade = es?.yukseltme || 0;
    body.push(h('div', { class: 'tip-block' }, h('div', { class: 'tip-title' }, T('Yükseltme')),
      row(T('Seviye başına'), hintPercent(y) + ' ' + T(HINT_UPGRADE[t] || t)), row(T('En yüksek seviye'), '+' + low),
      curUpgrade ? row(T('Şimdiki seviye'), '+' + curUpgrade + ' · ' + hintPercent(y * curUpgrade), 'bonus') : null));
  }
  const r = es?.rng;
  if (r?.nitelik?.length) {
    const fraction = r.tur === 'modul';
    body.push(h('div', { class: 'tip-block rng' }, h('div', { class: 'tip-title' }, T('Bu eşyanın nitelikleri')),
      r.nitelik.map(([a, v]) => row(attributeName(a), hintPercent(fraction ? v : v / 100), 'bonus')),
      r.seviye ? row(T('Seviye'), r.seviye) : null, r.yildiz ? row(T('Yıldız'), '★'.repeat(r.yildiz)) : null,
      r.hak != null ? row(T('Yeniden çekme hakkı'), r.hak) : null));
  }
  const ships = r?.gemiler || (r?.gemi ? [r.gemi] : null) || b.gm;
  if (ships?.length) body.push(h('div', { class: 'tip-block' }, h('div', { class: 'tip-title' }, r?.gemiler || r?.gemi ? T('Geçtiği gemiler') : b.stats?.some(d => d[0] === 'en_az') ? T('Daha sık çıktığı gemiler') : T('Geçtiği gemiler')),
    h('div', { class: 'tip-ships' }, ships.map(g => h('span', null, gameIcon(g, 22, firma, 'ship'), itemName(g))))));
  if (es?.hak != null) body.push(row(T('Kalan hak'), fmtN(es.hak[0]) + ' / ' + fmtN(es.hak[1])));
  if (txt?.[4]) body.push(h('div', { class: 'ip-not' }, icon('info'), hintPlaceholder(txt[4], ph)));
  const sub = [b.tk ? T('Takılır: {0}', b.tk.map(x => T(HINT_PLACE[x] || x)).join(', ')) : null, b.sat ? T('Satış: {0}', fmtN(b.sat) + ' C.') : null].filter(Boolean);
  if (txt?.[5]) body.push(h('div', { class: 'tip-resource' }, hintPlaceholder(txt[5], ph)));
  return h('div', { class: 'ipucu' },
    h('div', { class: 'tip-head' }, gameIcon(lid, 52, firma, 'box'), h('div', { style: { minWidth: 0 } },
      h('b', null, itemName(lid) + (es?.yukseltme ? ' +' + es.yukseltme : '')), txt?.[1] ? h('div', { class: 'tip-kind' }, txt[1]) : null,
      es?.seviye ? h('div', { class: 'tip-kind' }, T('Sv {0}', es.seviye)) : null)),
    body.length ? body : h('div', { class: 'tip-description dim' }, lid),
    sub.length ? h('div', { class: 'tip-bottom' }, sub.join(' · ')) : null);
}
function closeHint() { clearTimeout(IP.time); IP.el = null; IP.kutu?.remove(); IP.kutu = null; }
document.addEventListener('mouseover', e => {
  const el = e.target.closest?.('[data-loot]');
  if (el === IP.el) return;
  closeHint();
  if (!el || el.closest('.ipucu')) return;
  IP.el = el;
  for (let n = el; n && n !== document.body; n = n.parentElement) if (n.title) { n.dataset.baslik = n.title; n.removeAttribute('title'); }   // tarayıcının ad balonu yerine
  IP.time = setTimeout(async () => {
    await (IP.loading ||= loadHints().finally(() => { IP.loading = null; }));
    if (IP.el !== el || !el.isConnected) return;
    let es = null;
    for (let n = el; n && !es; n = n.parentElement) es = n._item || null;
    const k = itemHint(el.dataset.loot, es, el.dataset.firma);
    document.body.append(k);
    IP.kutu = k;
    const r = el.getBoundingClientRect(), w = k.offsetWidth, hh = k.offsetHeight;
    k.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.right + 10 + w > window.innerWidth ? r.left - w - 10 : r.right + 10)) + 'px';
    k.style.top = Math.max(8, Math.min(window.innerHeight - hh - 8, r.top)) + 'px';
  }, 260);
});
document.addEventListener('mousedown', closeHint, true);
document.addEventListener('scroll', closeHint, true);
const formatMoney = (cur, n) => fmtN(n) + (cur === 'credits' || cur === 'kredi' ? ' C.' : ' U.');
// sunucunun hata ve bilgi anahtarları (BaseKey adları, panel_kanali'nin kendi anahtarları); ham metin (boşluklu) olduğu gibi
const GAME_TEXT = { not_enough_credits: N('Yeterli kredin yok.'), not_enough_uridium: N('Yeterli uridyumun yok.'), shop_item_not_found: N('Bu ürün şu an satılmıyor.'),
  drone_have_max: N('Dron sayısı en çokta.'), info_text_switch_hangar_station_only: N('Gemi yalnız istasyondayken değiştirilebilir.'),
  error_can_not_equip_to_slot: N('Bu eşya bu yuvaya takılamaz.'), config_change_failed_time: N('Config değiştirmek için biraz bekle.'),
  items_hangarSlot_max_favs: N('En çok 10 favori gemi olabilir.'), error_pet_name_length: N('P.E.T. adı 1-24 karakter olmalı.'),
  error_pet_name_char: N('P.E.T. adında yalnız harf ve rakam olabilir.'), drone_slotCPUinUse: N('Yuva CPU\'su kullanımda: önce ekstra yuvalarını boşalt.'),
  pet_gear_requirement: N('P.E.T.\'in seviyesi bu eşya için yetmiyor.'), special_generic_hint: N('Bu ekstradan config\'te zaten var.') };
const gameText = k => GAME_TEXT[k] ? T(GAME_TEXT[k]) : k && k.includes(' ') ? k : T('İşlem yapılamadı ({0}).', k || '?');
const GAME_PAGES = [['magaza', N('Mağaza'), 'shop_normal', 'cart'], ['hangar', N('Hangar'), 'hangar_normal', 'hangar'], ['skylab', N('Skylab'), 'skylab_normal', 'lab'],
  ['muzayede', N('Açık Artırma'), 'auction_normal', 'gavel']];

// üç sayfanın ortak üst çubuğu; ekler: sayfaya özgü düğmeler (arama, yenile)
function gameHeader(v, page, ...extras) {
  const currency = (name, n) => h('span', { class: 'pill shop-currency' }, art('kaynak_' + name, 'shop-resource'), h('b', null, fmtN(n)));
  return h('div', { class: 'card game-top' },
    h('div', { class: 'game-tabs' }, GAME_PAGES.map(([id, name, sp, iconEl]) => h('button', { class: 'game-tab' + (id === page ? ' on' : ''), type: 'button',
      onclick: () => id !== page && go(id) }, GI.index?.sprite[sp] ? sprite(sp, 22) : icon(iconEl), h('span', null, T(name))))),
    h('div', { class: 'row wrap', style: { gap: '8px', justifyContent: 'flex-end' } }, currency('kredi', v.kredi), currency('uridyum', v.uridyum),
      h('span', { class: 'pill ' + (v.istasyonda ? 'game-safe' : 'game-space'), title: v.istasyonda ? T('Donanım değiştirilebilir.') : T('Donanım yalnız güvenli bölgede değiştirilebilir.') },
        dot(v.istasyonda ? 'ok' : 'warn'), v.istasyonda ? T('Güvenli bölgede') : T('Uzayda')), ...extras));
}
function gameError(e, page) {
  $('#content').replaceChildren(h('div', { class: 'card' }, h('div', { class: 'empty' }, h('p', null, e.message), btn(T('Yenile'), () => go(page), '', 'refresh'))));
}

// ================================================================== OYUN İÇİ: MAĞAZA
const SHP_CATEGORY = { ship: N('Gemiler'), shipdesign: N('Gemi tasarımları'), laser: N('Lazerler'), ammunition: N('Cephane'), generator: N('Jeneratörler'),
  extras: N('Ekstralar'), booster: N('Boosterlar'), drone: N('Dronlar'), petgear: N('P.E.T. donanımı'), protocol: N('Protokoller'), customization: N('Kişiselleştirme') };
const SHP = { veri: null, multiplier: null, ara: '', seviye: {} };

async function renderShop() {
  await loadGameImages();
  try { SHP.veri = await api('/api/oyun/magaza'); } catch (e) { return gameError(e, 'magaza'); }
  if (!SHP.veri.categories.includes(SHP.multiplier)) SHP.multiplier = SHP.veri.categories[0];
  const grid = h('div', { class: 'shop-grid' });
  const entries = () => {
    const q = SHP.ara.trim().toLowerCase(), its = (SHP.veri.esyalar[SHP.multiplier] || []).filter(it => !q || itemName(it.lootId).toLowerCase().includes(q));
    grid.replaceChildren(...its.map(shopCard));
    if (!its.length) grid.append(h('div', { class: 'empty' }, T('Ürün yok.')));
  };
  const search = h('input', { class: 'input game-search', placeholder: T('Ara…'), value: SHP.ara, oninput: e => { SHP.ara = e.target.value; entries(); } });
  $('#content').replaceChildren(h('div', { class: 'stack' },
    gameHeader(SHP.veri, 'magaza', search, btn(null, () => renderShop(), 'icon', 'refresh', { title: T('Yenile') })),
    h('div', { class: 'card' },
      !SHP.veri.gorsel ? h('p', { class: 'desc' }, T('Oyunun görselleri, oyun bir kez BepInEx ile açılınca hazırlanır.')) : null,
      h('div', { class: 'seg', style: { flexWrap: 'wrap' } }, SHP.veri.categories.map(c =>
        h('button', { class: c === SHP.multiplier ? 'on info' : '', onclick: () => { SHP.multiplier = c; renderShop(); } }, SHP_CATEGORY[c] ? T(SHP_CATEGORY[c]) : c)))),
    grid));
  entries();
}

function shopCard(it) {
  // seviyeli ürün (P.E.T. dişlisi, protokol): fiyat seviye başına, maxAmount P.E.T.'in izin verdiği en yüksek seviye (magaza.shop_list)
  const leveled = (it.price || []).length > 1, unaffordable = it.maxAmount === -1;
  const lv = Math.min(SHP.seviye[it.lootId] || 1, leveled ? Math.max(1, it.maxAmount) : 1);
  const many = !leveled && (!!it.amountsSelectable || it.maxAmount > 1);
  const count = many ? h('input', { class: 'input num', type: 'number', min: 1, max: it.maxAmount > 0 ? it.maxAmount : null, value: 1 }) : null;
  // sunucunun cost metni İngilizce biçimli ("190,000 U."): fiyat panelin sayı biçimiyle yazılır
  const price = it.price?.length ? fmtN(it.price[lv - 1]) + (it.currency === 'real' ? ' U.' : ' C.') : it.cost;
  return h('div', { class: 'shop-card' + (unaffordable ? ' unavailable' : '') },
    gameIcon(it.lootId, 84, SHP.veri.firma, 'cart'),
    h('div', { class: 'shop-name', title: it.lootId }, itemName(it.lootId)),
    leveled ? h('div', { class: 'seg shop-lv' }, it.price.map((p, i) => h('button', { class: i + 1 === lv ? 'on info' : '', disabled: i + 1 > Math.max(1, it.maxAmount),
      onclick: () => { SHP.seviye[it.lootId] = i + 1; renderShop(); } }, T('Sv {0}', i + 1)))) : null,
    h('div', { class: 'shop-price ' + (it.currency === 'real' ? 'uri' : 'cred') }, price),
    h('div', { class: 'row', style: { gap: '6px', justifyContent: 'center' } }, count,
      btn(T('Satın al'), e => shopBuy(it, count ? Math.max(1, +count.value | 0) : 1, lv, e.currentTarget), 'sm primary', null, { disabled: unaffordable })),
    it.canBeSubscribedTo ? btn(it.isSubscriptionRunning ? T('Aboneliği bitir') : T('Abone ol'), e => shopSubscribe(it, e.currentTarget), 'sm ghost') : null);
}

async function shopBuy(it, n, lv, b) {
  b.disabled = true;
  const r = await act(() => api('/api/oyun/al', { lootId: it.lootId, category: it.category, amount: n, level: lv }));
  b.disabled = false;
  if (!r) return;
  if (!r.tamam) return toast(GAME_TEXT[r.hata] ? T(GAME_TEXT[r.hata]) : T('Satın alınamadı ({0}).', r.hata || '?'), 'err');
  toast(T('Satın alındı: {0}', (n > 1 ? fmtN(n) + ' × ' : '') + itemName(it.lootId)), 'ok');
  renderShop();                       // cüzdan ve liste (alınan tekil eşya listeden düşer, adetler paraya göre)
}

async function shopSubscribe(it, b) {
  b.disabled = true;
  const r = await act(() => api('/api/oyun/magaza/subscribe', { lootId: it.lootId, category: it.category }));
  if (r && !r.tamam) toast(gameText(r.hata), 'err');
  renderShop();
}

// ================================================================== OYUN İÇİ: HANGAR
// Gemiler, iki config; gemi, dron ve P.E.T. yuvaları, CPU'lar (panel_channel.py /hangar). Envanterdeki eşyaya tıklayınca seçili config'te
// seçili bölüme (gemi, seçili dron, P.E.T. ya da HEAT yuvası) takılır, yuvadakine tıklayınca çıkarılır (HangarShipMoveItemsRequest).
// Satış kipinde envanterden seçilenler birlikte satılır. Güvenli bölge dışında donanım değişmez (düğmeler kapalı, sunucu da reddeder).
const HG_SLOT = { laser: N('Lazerler'), rocket: N('Roketatar'), generators: N('Jeneratörler'), extra: N('Ekstralar'), upgrades: N('Gemi modülleri'),
  QuantumFluidCore: 'Quantum Fluid Core', cannon: N('Parçacık topları'), cannonShield: N('Kırıcılar'), drive: 'Singularity Drive', lens: N('Mercekler'),
  lasers: N('Lazerler'), gears: N('Dişliler'), protocols: N('Protokoller'), visual: N('Görünüm'), heat: 'HEAT', tasarim: N('Dron tasarımları'), diger: N('Diğer') };
const slotName = y => HG_SLOT[y] ? T(HG_SLOT[y]) : y;
const HG = { gemi: null, konfig: null, section: 'ship', dron: null, yuva: {}, mode: 'tak', kume: '', secili: {} };

async function renderHangar() {
  await loadGameImages();
  let v;
  try { v = await api('/api/oyun/hangar?gemi=' + encodeURIComponent(HG.gemi || '')); } catch (e) { return gameError(e, 'hangar'); }
  HG.gemi = v.gemi;
  if (!v.konfigler[HG.konfig]) HG.konfig = v.active_config;
  if (HG.section === 'pet' && !v.pet) HG.section = 'ship';
  const drones = v.dronlar[HG.konfig] || [], lock = !v.istasyonda, iconName = (lid, size) => gameIcon(lid, size, v.firma);
  if (!drones.find(d => d.id === HG.dron)) HG.dron = drones[0]?.id ?? null;
  const ship = v.gemiler.find(g => g.id === v.gemi);
  const lvlBadge = e => e.seviye ? h('span', { class: 'hg-lv' }, '+' + e.seviye) : null;
  const kick = (e, target, drone) => h('button', { class: 'hg-item', type: 'button', disabled: lock, title: itemName(e.lootId) + ' — ' + T('çıkarmak için tıkla'),
    onclick: ev => hangarMove({ esya: e.id, yon: 'cikar', target, drone }, ev.currentTarget) }, iconName(e.lootId, 44));
  const empty = n => Array.from({ length: Math.max(0, n) }, () => h('span', { class: 'hg-item bos' }));
  const slotBox = (name, c, target, extra) => h('div', { class: 'hg-slot' }, h('div', { class: 'row between' }, h('b', null, slotName(name)),
    h('span', { class: 'row', style: { gap: '6px' } }, extra, h('span', { class: 'mono' }, c.esyalar.length + ' / ' + c.capacity))),
    h('div', { class: 'hg-grid' }, c.esyalar.map(e => kick(e, target)), empty(c.capacity - c.esyalar.length)));
  // gemiler: etkin önce; yıldız favori (oyunda ışınlanabilen gemiler)
  const ships = h('div', { class: 'hg-ships' }, [...v.gemiler].sort((a, b) => b.aktif - a.aktif || b.favori - a.favori).map(g => h('div', { class: 'hg-ship' + (g.id === v.gemi ? ' on' : ''),
    title: itemName(g.lootId), onclick: () => { HG.gemi = g.id; renderHangar(); } },
    h('button', { class: 'hg-star' + (g.favori ? ' on' : ''), type: 'button', title: g.favori ? T('Favoriden çıkar') : T('Favori yap'),
      onclick: ev => { ev.stopPropagation(); hangarAction({ islem: 'favori', gemi: g.id, favori: !g.favori }); } }, icon('star')),
    iconName(g.tasarim || g.lootId, 54), h('span', null, itemName(g.lootId)), g.aktif ? badge(T('Etkin'), 'ok') : null)));
  const appearance = v.designs.length > 1 ? h('div', { class: 'row wrap', style: { gap: '6px' } }, h('span', { class: 'lbl' }, T('Görünüm')),
    v.designs.map(t => h('button', { class: 'hg-item' + (t === v.gorunum ? ' on' : ''), type: 'button', title: itemName(t), disabled: lock && t !== v.gorunum,
      onclick: ev => t !== v.gorunum && hangarDesign(t, ev.currentTarget) }, iconName(t, 44)))) : null;
  const tools = h('div', { class: 'row wrap hg-tools' },
    ship.aktif ? null : btn(T('Etkin gemi yap'), e => hangarSetActive(v.gemi, e.currentTarget), 'sm primary', null, { disabled: lock }),
    ship.aktif && HG.konfig !== v.active_config ? btn(T('Bu config\'i kullan'), () => hangarAction({ islem: 'konfig', konfig: HG.konfig }, T('Config değişti.')), 'sm primary') : null,
    btn(T('Kaydet'), () => hangarAction({ islem: 'kaydet', gemi: v.gemi }, T('İki config kaydedildi.')), 'sm', 'save', { title: T('İki config\'in donanımını bu gemi için saklar.') }),
    ship.registered ? btn(T('Yükle'), () => hangarAction({ islem: 'yukle', gemi: v.gemi }, T('Kayıtlı donanım takıldı.')), 'sm', 'download', { disabled: lock }) : null,
    btn(T('Aktar…'), () => hangarTransfer(v), 'sm', 'copy', { disabled: lock, title: T('Bu geminin donanımını başka bir gemiye taşır.') }),
    btn(T('Temizle'), async () => await confirmBox(T('Config {0} boşaltılsın mı?', HG.konfig), T('Gemideki, dronlardaki ve P.E.T.\'teki eşyalar envantere iner.'),
      { ok: T('Temizle'), danger: true }) && hangarAction({ islem: 'temizle', gemi: v.gemi, konfig: HG.konfig }), 'sm', 'trash', { disabled: lock }));
  // seçili bölüm
  let section;
  if (HG.section === 'ship') section = h('div', { class: 'hg-slots' }, v.yuvalar.map(y => slotBox(y, v.konfigler[HG.konfig][y], 'ship')));
  else if (HG.section === 'drone') section = drones.length ? h('div', { class: 'hg-drones' }, drones.map(d => h('div', { class: 'hg-drone' + (d.id === HG.dron ? ' on' : ''),
    onclick: () => { if (HG.dron !== d.id) { HG.dron = d.id; renderHangar(); } } },
    iconName(d.lootId, 40), h('div', { class: 'grow' }, h('b', null, itemName(d.lootId)), d.id === HG.dron ? h('div', { class: 'lbl' }, T('envanterden takılacak dron')) : null),
    h('div', { class: 'hg-grid' }, d.esyalar.map(e => kick(e, 'drone', d.id)), empty(d.capacity - d.esyalar.length),
      [d.tasarim, d.gorunum].map(e => e ? kick(e, 'drone', d.id) : null)),
    btn(T('Sat'), async ev => { ev.stopPropagation(); if (await confirmBox(T('{0} satılsın mı?', itemName(d.lootId)), T('Üstündeki eşyalar envantere iner.'), { ok: T('Sat'), danger: true }))
      hangarAction({ islem: 'dron_sat', dron: d.id }, T('Dron satıldı.')); }, 'sm ghost', null, { disabled: lock })))) : h('div', { class: 'empty' }, T('Dron yok.'));
  else if (HG.section === 'pet') {
    const pb = v.pet_info, pc = v.pet[HG.konfig];
    const openSlot = y => pc[y].fiyat > 0 ? btn('+1 (' + formatMoney('uridium', pc[y].fiyat) + ')', async () => await confirmBox(T('{0} yuvası açılsın mı?', slotName(y)),
      T('{0} uridyum harcanır.', fmtN(pc[y].fiyat)), { ok: T('Aç') }) && hangarAction({ islem: 'pet_yuva', yuva: y }, T('Yuva açıldı.')), 'sm ghost') : null;
    section = h('div', { class: 'stack' },
      h('div', { class: 'row wrap', style: { gap: '10px' } }, h('b', null, pb.ad || 'P.E.T.'), badge(T('Sv {0}', pb.seviye), 'info'),
        btn(T('Adını değiştir ({0})', formatMoney('uridium', pb.rename_price)), async () => { const name = await promptBox(T('P.E.T.\'in adı'), T('1-24 harf ya da rakam'), pb.ad || '');
          if (name != null && name !== pb.ad) hangarAction({ islem: 'pet_ad', name }, T('P.E.T.\'in adı değişti.')); }, 'sm ghost'),
        pc.heat.capacity ? h('div', { class: 'seg' }, [['', T('Normal yuvalar')], ['heat', 'HEAT']].map(([k, t]) => h('button', { class: HG.kume === k ? 'on info' : '',
          onclick: () => { HG.kume = k; renderHangar(); } }, t))) : null),
      !pb.heat_unlocked && pc.heat.capacity ? h('p', { class: 'desc', style: { margin: 0 } }, T('HEAT yuvaları P.E.T.\'in HEAT seviyesi yükselince etkinleşir.')) : null,
      h('div', { class: 'hg-slots' }, v.pet_slots.filter(y => y !== 'heat' || pc.heat.capacity || pc.heat.fiyat).map(y => slotBox(y, pc[y], 'pet', openSlot(y)))));
  } else section = v.cpus.length ? h('div', { class: 'hg-cpus' }, v.cpus.map(c => h('div', { class: 'hg-cpu' }, iconName(c.lootId, 40),
    h('div', { class: 'grow' }, h('b', null, itemName(c.lootId)), c.tur === 'cephane' ? h('div', { class: 'lbl' }, T('{0} altına inince {1} alır', fmtN(c.threshold), fmtN(c.adet))) : null),
    c.tur === 'ackapa' ? btn(c.acik ? T('Açık') : T('Kapalı'), () => hangarAction({ islem: 'cpu', lootId: c.lootId }), 'sm ' + (c.acik ? 'primary' : 'ghost'))
      : h('select', { class: 'input', onchange: e => hangarAction({ islem: 'cpu_cephane', esya: c.id, cephane: e.target.value }, T('Otomatik alım cephanesi seçildi.')) },
        h('option', { value: '', disabled: true, selected: !c.secili }, T('Cephane seç')),
        c.options.map(o => h('option', { value: o, selected: o === c.secili }, itemName(o)))))))
    : h('div', { class: 'empty' }, T('Etkin config\'te ayarı olan CPU yok.'));
  const sections = [['ship', T('Gemi')], ['drone', T('Dronlar')]].concat(v.pet ? [['pet', 'P.E.T.']] : [], ship.aktif ? [['cpu', 'CPU']] : []);
  if (!sections.find(([k]) => k === HG.section)) HG.section = 'ship';
  $('#content').replaceChildren(h('div', { class: 'stack' },
    gameHeader(v, 'hangar', btn(null, () => renderHangar(), 'icon', 'refresh', { title: T('Yenile') })),
    h('div', { class: 'card' }, ships),
    h('div', { class: 'card hg-ship-card' },
      lock ? h('div', { class: 'hg-warning' }, icon('alert'), v.portal_hangar ? T('Donanım yalnız istasyonda ya da portalın güvenli bölgesinde (savaştan biraz sonra) değiştirilebilir.')
        : T('Donanım yalnız istasyonda (savaştan biraz sonra) değiştirilebilir.')) : null,
      h('div', { class: 'row between wrap', style: { gap: '10px' } },
        h('div', { class: 'row', style: { gap: '12px' } }, iconName(ship.tasarim || ship.lootId, 64), h('div', null, h('h2', { style: { margin: 0 } }, itemName(ship.lootId)),
          ship.aktif ? h('span', { class: 'lbl' }, T('Etkin gemi')) : null)),
        h('div', { class: 'seg' }, Object.keys(v.konfigler).map(c => h('button', { class: c === HG.konfig ? 'on info' : '', onclick: () => { HG.konfig = c; renderHangar(); } },
          T('Config {0}', c), ship.aktif && c === v.active_config ? ' •' : '')))),
      tools, appearance,
      h('div', { class: 'seg' }, sections.map(([k, t]) => h('button', { class: k === HG.section ? 'on info' : '', onclick: () => { HG.section = k; renderHangar(); } }, t))),
      section),
    hangarInventory(v, lock, iconName, lvlBadge)));
}

// envanter kartı: takma kipinde seçili bölüme takılabilenler, satış kipinde satılabilenler (aynı eşyalar tek kutuda, sayısıyla)
function hangarInventory(v, lock, iconName, lvlBadge) {
  const sell = HG.mode === 'sat' && HG.section !== 'cpu';
  // items equipped in another config of this ship can be equipped here too (as in game); they are never sold
  const elsewhere = e => e.konfigler && e.konfigler.length > 0;
  const eligible = v.envanter.filter(e => sell ? e.satis && !elsewhere(e)
    : HG.section !== 'cpu' && e.hedefler.includes(HG.section) && !(e.konfigler || []).includes(String(HG.konfig)));
  const kinds = [...new Set(eligible.map(e => e.yuva))], key = sell ? 'sat' : HG.section;
  if (!kinds.includes(HG.yuva[key])) HG.yuva[key] = kinds[0];
  const group = {};
  for (const e of eligible.filter(e => e.yuva === HG.yuva[key])) (group[e.lootId] = group[e.lootId] || []).push(e);
  for (const es of Object.values(group)) es.sort((a, b) => elsewhere(b) - elsewhere(a));      // items of the other config first: free copies stay free
  for (const id of Object.keys(HG.secili)) if (!v.envanter.find(e => String(e.id) === id && e.satis && !elsewhere(e))) delete HG.secili[id];
  const selected = v.envanter.filter(e => HG.secili[e.id]), total = {};
  for (const e of selected) total[e.satis[0]] = (total[e.satis[0]] || 0) + e.satis[1];
  const boxes = Object.entries(group).sort((a, b) => itemName(a[0]).localeCompare(itemName(b[0]))).map(([lid, es]) => {
    const n = es.filter(e => HG.secili[e.id]).length;
    const b = h('button', { class: 'hg-item' + (n ? ' on' : ''), type: 'button', disabled: !sell && lock,
      title: itemName(lid) + (sell ? ' — ' + T('satış değeri {0}', formatMoney(es[0].satis[0], es[0].satis[1])) + ' · ' + T('seçmek için tıkla, sağ tıkla bırak') : ' — ' + T('takmak için tıkla')),
      onclick: ev => { if (!sell) return hangarMove({ esya: es[0].id, yon: 'tak', hedef: HG.section, dron: HG.dron, kume: HG.section === 'pet' ? HG.kume : '' }, ev.currentTarget);
        const e = es.find(x => !HG.secili[x.id]); if (e) { HG.secili[e.id] = true; renderHangar(); } },
      oncontextmenu: ev => { if (!sell) return; ev.preventDefault(); const e = es.find(x => HG.secili[x.id]); if (e) { delete HG.secili[e.id]; renderHangar(); } } },
      iconName(lid, 44), lvlBadge(es[0]), es.length > 1 ? h('span', { class: 'hg-count' }, (n ? n + '/' : '') + fmtN(es.length)) : n ? h('span', { class: 'hg-count' }, '✓') : null);
    b._item = es[0].seviye ? { yukseltme: es[0].seviye } : null;        // eşya ipucu: yükseltme seviyesi
    return b;
  });
  return h('div', { class: 'card' },
    h('div', { class: 'row between wrap', style: { gap: '10px' } },
      h('div', { class: 'row', style: { gap: '10px' } }, h('h2', { style: { margin: 0 } }, T('Envanter')),
        HG.section !== 'cpu' ? h('div', { class: 'seg' }, [['tak', T('Tak')], ['sat', T('Sat')]].map(([k, t]) => h('button', { class: HG.mode === k ? 'on info' : '',
          onclick: () => { HG.mode = k; renderHangar(); } }, t))) : null),
      h('div', { class: 'seg', style: { flexWrap: 'wrap' } }, kinds.map(y => h('button', { class: y === HG.yuva[key] ? 'on info' : '', onclick: () => { HG.yuva[key] = y; renderHangar(); } }, slotName(y))))),
    h('div', { class: 'hg-grid', style: { marginTop: '12px' } }, boxes.length ? boxes : h('div', { class: 'empty' }, sell ? T('Satılabilecek eşya yok.') : T('Takılabilecek eşya yok.'))),
    sell && selected.length ? h('div', { class: 'hg-sell' }, h('span', null, T('{0} eşya seçili', selected.length), ' · ', h('b', null, Object.entries(total).map(([c, n]) => formatMoney(c, n)).join(' + '))),
      h('div', { class: 'row', style: { gap: '6px' } }, btn(T('Seçimi temizle'), () => { HG.secili = {}; renderHangar(); }, 'sm ghost'),
        btn(T('Seçilenleri sat'), async () => await confirmBox(T('{0} eşya satılsın mı?', selected.length), T('Karşılığında {0} alırsın. Bu geri alınamaz.',
          Object.entries(total).map(([c, n]) => formatMoney(c, n)).join(' + ')), { ok: T('Sat'), danger: true })
          && hangarAction({ islem: 'sat', esyalar: selected.map(e => e.id) }, T('Satıldı.'), () => { HG.secili = {}; }), 'sm primary'))) : null);
}

async function hangarMove(request, b) {
  b.disabled = true;
  const r = await act(() => api('/api/oyun/hangar/tasi', Object.assign({ gemi: HG.gemi, konfig: HG.konfig }, request)));
  if (r && !r.tamam) toast(r.hata === 'istasyon' ? T('Donanım yalnız güvenli bölgede değiştirilebilir.') : gameText(r.hata), 'err');
  renderHangar();
}

// hangarın öteki işlemleri (panel_kanali.ISLEMLER): başarıda bilgi metni, sonra yenile
async function hangarAction(request, okText, after) {
  const r = await act(() => api('/api/oyun/hangar/islem', Object.assign({ gemi: HG.gemi }, request)));
  if (r && !r.tamam) toast(r.hata === 'istasyon' ? T('Donanım yalnız güvenli bölgede değiştirilebilir.') : gameText(r.hata), 'err');
  else if (r) { if (okText) toast(okText, 'ok'); if (after) after(); }
  renderHangar();
}

// Transfer System: bu geminin donanımı başka bir gemiye (hedefin yuvaları yetmeli)
function hangarTransfer(v) {
  let target = null;
  const entries = h('div', { class: 'hg-ships', style: { flexWrap: 'wrap' } }, v.gemiler.filter(g => g.id !== v.gemi).map(g => h('div', { class: 'hg-ship', onclick: ev => {
    target = g.id; entries.querySelectorAll('.hg-ship').forEach(x => x.classList.toggle('on', x === ev.currentTarget)); } },
    gameIcon(g.tasarim || g.lootId, 54, v.firma), h('span', null, itemName(g.lootId)))));
  const m = modal({ title: T('Donanımı aktar'), sub: T('{0} gemisinin iki config\'i, dronları ve P.E.T. donanımı seçtiğin gemiye taşınır.', itemName(v.gemiler.find(g => g.id === v.gemi).lootId)),
    body: [entries], wide: true, foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Aktar'), () => { if (!target) return toast(T('Bir gemi seç.'), 'err');
      m.close(); hangarAction({ islem: 'aktar', gemi: v.gemi, hedef_gemi: target }, T('Donanım aktarıldı.')); }, 'primary')] });
}

async function hangarSetActive(ship, b) {
  b.disabled = true;
  const r = await act(() => api('/api/oyun/hangar/etkin', { ship }));
  if (r && !r.tamam) toast(gameText(r.hata), 'err');
  else if (r) toast(T('Etkin gemi değişti.'), 'ok');
  renderHangar();
}

async function hangarDesign(lootId, b) {
  b.disabled = true;
  const r = await act(() => api('/api/oyun/hangar/tasarim', { gemi: HG.gemi, lootId }));
  if (r && !r.tamam) toast(r.hata === 'istasyon' ? T('Donanım yalnız güvenli bölgede değiştirilebilir.') : gameText(r.hata), 'err');
  renderHangar();
}

// ================================================================== OYUN İÇİ: SKYLAB
// Modüller, depo, enerji, robotlar ve taşıma (panel_channel.py /skylab): işlemler istemcinin SkylabActionRequest ve
// SkylabPurchaseRobotRequest'i (kurallar, bedeller ve süreler oyundakiyle aynı). Modül görseli yok: üretilen cevherin görseli.
const SK_ORE = { PROMETIUM_COLLECTOR: 'prometium', ENDURIUM_COLLECTOR: 'endurium', TERBIUM_COLLECTOR: 'terbium', PROMETID_REFINERY: 'prometid',
  DURANIUM_REFINERY: 'duranium', PROMERIUM_REFINERY: 'promerium', SEPROM_REFINERY: 'seprom', XENO_MODULE: 'xenomit' };
const SK_MODULE = { BASE_MODULE: N('Ana modül'), SOLAR_MODULE: N('Güneş modülü'), STORAGE_MODULE: N('Depo modülü'), TRANSPORT_MODULE: N('Taşıma modülü'),
  XENO_MODULE: N('Xeno modülü') };
const oreName = name => itemName('resource_ore_' + name.toLowerCase());
const skModuleName = k => SK_MODULE[k] ? T(SK_MODULE[k]) : k.endsWith('_COLLECTOR') ? T('{0} toplayıcısı', oreName(SK_ORE[k]))
  : T('{0} rafinerisi', oreName(SK_ORE[k]));
const SK_TEXT = {
  skylab_message_transport_isNotActive: N('Taşıma modülü çalışmıyor.'), skylab_message_upgrade_maximumLevel: N('Modül en yüksek seviyede.'),
  skylab_message_upgrade_basemoduleLevel: N('Önce ana modülü yükselt.'), skylab_message_upgrade_credits: N('Yeterli kredin yok.'),
  skylab_message_upgrade_prometium: N('Skylab deposunda yeterli Prometium yok.'), skylab_message_upgrade_endurium: N('Skylab deposunda yeterli Endurium yok.'),
  skylab_message_upgrade_terbium: N('Skylab deposunda yeterli Terbium yok.'), skylab_history_module_activate_notBuiltYet: N('Modül henüz kurulmadı.'),
  skylab_history_module_deactivated: N('Modül kapatıldı.'), skylab_history_module_activated: N('Modül açıldı.'),
  skylab_history_module_activate_lowpower: N('Güneş modülünün enerjisi yetmiyor.'), skylab_history_module_upgrade_lowpower: N('Güneş modülünün enerjisi yetmiyor.'),
  skylab_message_upgrade_success: N('Yükseltme başladı.'), skylab_message_upgrade_inProgress: N('Bu modülün yükseltmesi zaten sürüyor.'),
  skylab_history_upgrade_canceled: N('Yükseltme iptal edildi.'), skylab_message_upgrade_uridium: N('Yeterli uridyumun yok.'),
  skylab_history_upgrade_instant: N('Modül yükseltildi.'), skylab_history_upgrade_finished: N('Yükseltme bitti.'),
  skylab_message_transport_notEnoughUridium: N('Yeterli uridyumun yok.'), skylab_message_transport_alreadyActive: N('Bir taşıma zaten sürüyor.'),
  skylab_message_transport_requestedOreAmountIsZero: N('Gönderilecek cevher seç.'), skylab_message_transport_notEnoughSpaceInShipStorage: N('Geminin kargosunda yer yok.'),
  skylab_message_transport_isEmpty: N('Depoda gönderilecek cevher yok.'), skylab_history_transfer_ship_started: N('Taşıma başladı.'),
  skylab_history_transfer_ship_finished: N('Cevherler gemiye ulaştı.') };
const skText = k => SK_TEXT[k] ? T(SK_TEXT[k]) : gameText(k);
const SK = { gonder: {} };

async function renderSkylab() {
  await loadGameImages();
  let v;
  try { v = await api('/api/oyun/skylab'); } catch (e) { return gameError(e, 'skylab'); }
  const oreIcon = (name, size) => GI.index?.sprite[name + '_100x100'] ? sprite(name + '_100x100', size) : h('span', { class: 'sprite bos', style: { width: size + 'px', height: size + 'px' } }, icon('lab'));
  const storage = v.storage.map(o => h('div', { class: 'sk-ore' }, oreIcon(o.ad.toLowerCase(), 44),
    h('div', { class: 'grow' }, h('div', { class: 'row between' }, h('b', null, oreName(o.ad)), h('span', { class: 'mono' }, fmtN(o.miktar) + ' / ' + fmtN(o.capacity))),
      h('div', { class: 'sk-bar' }, h('span', { style: { width: Math.min(100, 100 * o.miktar / Math.max(1, o.capacity)) + '%' } })))));
  const modules = v.moduller.map(m => {
    const rate = m.seviye === 0, state = m.kalan != null ? badge(T('Yükseltiliyor: {0}', fmtDur(m.kalan)), 'info')
      : rate ? badge(T('Kurulmadı')) : m.durum === 'ACTIVE' ? badge(T('Çalışıyor'), 'ok') : badge(T('Kapalı'), 'warn');
    const c = m.maliyet, buttons = [];
    if (m.kalan != null) {
      buttons.push(btn(T('Bitir ({0} U.)', fmtN(m.finish)), () => skylabAction(m.id, 'instantFinishUpgrade'), 'sm primary'),
        btn(T('İptal'), async () => await confirmBox(T('Yükseltme iptal edilsin mi?'), T('Harcananlar geri gelmez.'), { ok: T('İptal et'), danger: true })
          && skylabAction(m.id, 'abortUpgrade'), 'sm'));
    } else if (c) {
      buttons.push(btn(rate ? T('Kur') : T('Yükselt'), () => skylabAction(m.id, 'upgrade'), 'sm primary'));
      if (c.uridyum) buttons.push(btn(T('Anında ({0} U.)', fmtN(c.uridyum)), () => skylabAction(m.id, 'instantUpgrade'), 'sm'));
    }
    if (m.toggleable && !rate && m.kalan == null) buttons.push(btn(m.durum === 'ACTIVE' ? T('Kapat') : T('Aç'),
      () => skylabAction(m.id, m.durum === 'ACTIVE' ? 'setInactive' : 'setActive'), 'sm ghost'));
    return h('div', { class: 'sk-module' + (m.durum === 'ACTIVE' ? ' on' : '') },
      h('div', { class: 'row', style: { gap: '10px' } }, SK_ORE[m.id] ? oreIcon(SK_ORE[m.id], 48) : h('span', { class: 'sprite bos', style: { width: '48px', height: '48px' } }, icon('lab')),
        h('div', { class: 'grow' }, h('b', null, skModuleName(m.id)), h('div', { class: 'mono' }, T('Sv {0} / {1}', m.seviye, m.azami)))),
      h('div', { class: 'row wrap', style: { gap: '6px' } }, state,
        m.uretim ? badge(T('{0} / sa', fmtN(m.uretim)), '') : null, m.enerji ? badge(T('{0} enerji', fmtN(m.enerji)), 'orange') : null,
        m.efficiency ? badge(T('verim %{0}', m.efficiency), '') : null),
      c && m.kalan == null ? h('div', { class: 'sk-cost' }, T('{0} C., her birinden {1} Prometium / Endurium / Terbium, {2}', fmtN(c.kredi), fmtN(c.kaynak), fmtDur(c.sure_sn))) : null,
      h('div', { class: 'row wrap', style: { gap: '6px' } }, buttons),
      m.robot && !rate ? h('div', { class: 'sk-robot' }, h('span', { class: 'lbl' }, T('Robotlar: {0} / {1}', m.robot.etkin, m.robot.azami) + (m.robot.in_storage ? ' · ' + T('depoda {0}', m.robot.in_storage) : '')),
        h('div', { class: 'row', style: { gap: '6px' } }, ['1', '2'].map(t => btn('+' + (t === '1' ? '1%' : '4%') + ' · ' + formatMoney(m.robot.fiyat[t][0], m.robot.fiyat[t][1]),
          () => skylabRobot(m.id, t), 'sm ghost', null, { title: T('48 saat çalışan robot') })))) : null);
  });
  const t = v.transport, send = v.storage.map(o => h('label', { class: 'sk-send' }, oreIcon(o.ad.toLowerCase(), 28),
    h('input', { class: 'input num', type: 'number', min: 0, max: o.miktar, value: SK.gonder[o.id] || 0, oninput: e => { SK.gonder[o.id] = +e.target.value | 0; } })));
  const transport = t ? h('div', { class: 'stack' }, h('p', { class: 'desc', style: { margin: 0 } }, T('Taşıma sürüyor: {0} kaldı.', fmtDur(t.kalan))),
    h('div', null, btn(T('Hemen bitir ({0} U.)', fmtN(v.instant_price)), () => skylabAction('TRANSPORT_MODULE', 'startTransport', 'instantFinish'), 'sm primary')))
    : h('div', { class: 'stack' }, h('div', { class: 'row wrap', style: { gap: '10px' } }, send),
      h('div', { class: 'row wrap', style: { gap: '8px' } }, btn(T('Gönder'), () => skylabAction('TRANSPORT_MODULE', 'startTransport', ''), 'sm primary'),
        btn(T('Hızlı gönder ({0} U.)', fmtN(v.instant_price)), () => skylabAction('TRANSPORT_MODULE', 'startTransport', 'fast'), 'sm')));
  $('#content').replaceChildren(h('div', { class: 'stack' },
    gameHeader(v, 'skylab', h('span', { class: 'pill' + (v.enerji.used > v.enerji.solar ? ' err' : '') }, T('Enerji'), ' ', h('b', null, fmtN(v.enerji.used) + ' / ' + fmtN(v.enerji.solar))),
      btn(null, () => renderSkylab(), 'icon', 'refresh', { title: T('Yenile') })),
    h('div', { class: 'card' }, h('h2', null, T('Depo')), h('div', { class: 'sk-storage' }, storage)),
    h('div', { class: 'sk-modules' }, modules),
    h('div', { class: 'card' }, h('h2', null, T('Gemiye taşıma')), transport)));
}

async function skylabAction(modul, operation, mod) {
  const amounts = operation === 'startTransport' && mod !== 'instantFinish' ? SK.gonder : {};
  const r = await act(() => api('/api/oyun/skylab/islem', { modul, operation, mod: mod || '', amounts }));
  if (r) {
    if (r.hatalar.length) toast(skText(r.hatalar[0]), 'err');
    else if (r.achievements.length) toast(skText(r.achievements[r.achievements.length - 1]), 'ok');
    if (r.tamam && operation === 'startTransport') SK.gonder = {};
  }
  renderSkylab();
}

async function skylabRobot(modul, tip) {
  const r = await act(() => api('/api/oyun/skylab/robot', { modul, tip }));
  if (r && !r.tamam) toast(skText(r.hatalar[0]), 'err');
  else if (r) toast(T('Robot alındı.'), 'ok');
  renderSkylab();
}

// ================================================================== OYUN İÇİ: AÇIK ARTIRMA
// Lotlar, teklifler ve anında alım istemcinin Auction* istekleriyle (panel_channel.py /muzayede). Otomatik teklif ve alarm kuralları
// oyun sunucusunda (muzayede.oto): panel kapalıyken de işler, alarm oyunda ekran mesajı olur. Olaylar (geçildin, kazandın, otomatik
// teklif…) panelin her sayfasında bildirim olarak çıkar (muzayedeOlayTick; masaüstü bildirimi izin verilirse).
const AUCTION_KIND = { hour: N('Saatlik'), day: N('Günlük'), week: N('Haftalık') };
const AUCTION_GROUP = { ship: N('Gemiler'), shipdesign: N('Gemi tasarımları'), extra: N('Ekstralar'), module: N('Modüller'), booster: N('Boosterlar'),
  battery: N('Lazer cephanesi'), rocket: N('Roketler'), generator: N('Jeneratörler'), weapon: N('Silahlar'), special: N('Özel') };
const AUCTION_STATUS = [['hepsi', N('Hepsi')], ['teklif', N('Teklif verdiklerim')], ['onde', N('Öndeyim')], ['degil', N('Önde değilim')], ['oto', N('Otomatik')], ['alarm', N('Alarmlı')]];
Object.assign(GAME_TEXT, { auction_bid_minBid_not_reached: N('Teklif, en yüksek tekliften en az 10.000 kredi fazla olmalı.'), auction_bid_credits_to_little: N('Yeterli kredin yok.'),
  auction_buy_instant_invalid: N('Bu lot anında alınamaz.'), items_shop_error_ship_contains_ship: N('Bu gemi zaten sende.'), auction_error_generic: N('Açık artırma işlemi yapılamadı.') });
const MZ = { tur: 'hepsi', grup: 'hepsi', durum: 'hepsi', ara: '', bitis: {}, son: null };
const auctionKey = l => l.tur + '|' + l.loot;
function auctionEventText(o) {
  const name = itemName(o.loot);
  return { gecildi: () => T('Teklifin geçildi: {0}', name), bitiyor: () => T('{0} için {1} dk kaldı.', name, o.dk), kazanildi: () => T('Kazandın: {0} ({1})', name, formatMoney('credits', o.fiyat)),
    kaybedildi: () => T('Kaybettin: {0}', name), oto_teklif: () => T('Otomatik teklif: {0}, {1}', name, formatMoney('credits', o.fiyat)),
    oto_sinir: () => T('Otomatik teklif sınırına ulaşıldı: {0} ({1} gerekiyor)', name, formatMoney('credits', o.gereken)) }[o.tip]?.() || o.tip;
}
const auctionEventKind = t => ({ kazanildi: 'ok', oto_teklif: 'info', gecildi: 'err', oto_sinir: 'err', kaybedildi: 'err', bitiyor: 'info' }[t] || 'info');

async function renderAuction() {
  await loadGameImages();
  let v;
  try { v = await api('/api/oyun/muzayede'); } catch (e) { return gameError(e, 'muzayede'); }
  const now = Date.now() / 1000;
  for (const [k, n] of Object.entries(v.kalan)) MZ.bitis[k] = now + n;
  if (v.events.length) MZ.son = Math.max(MZ.son || 0, v.events[0].no);
  const groups = [...new Set(v.lotlar.map(l => l.grup))];
  const sec = l => (MZ.tur === 'hepsi' || l.tur === MZ.tur) && (MZ.grup === 'hepsi' || l.grup === MZ.grup)
    && (!MZ.ara || itemName(l.loot).toLowerCase().includes(MZ.ara.toLowerCase()))
    && ({ hepsi: true, teklif: l.benim > 0, onde: l.onde, degil: !l.onde, oto: !!l.oto, alarm: !!l.alarm })[MZ.durum];
  const visible = v.lotlar.filter(sec).sort((a, b) => (b.onde - a.onde) || (!!b.oto - !!a.oto) || ['hour', 'day', 'week'].indexOf(a.tur) - ['hour', 'day', 'week'].indexOf(b.tur)
    || itemName(a.loot).localeCompare(itemName(b.loot)));
  const joinable = visible.filter(l => !l.onde), total = joinable.reduce((t, l) => t + l.next, 0);
  const counter = k => h('span', { class: 'pill auc-counter', 'data-tur': k }, h('span', { class: 'lbl' }, T(AUCTION_KIND[k])), h('b', null, fmtDur(MZ.bitis[k] - now)));
  const search = h('input', { class: 'input game-search', placeholder: T('Ara…'), value: MZ.ara, oninput: e => { MZ.ara = e.target.value; clearTimeout(MZ.searchTimer); MZ.searchTimer = setTimeout(renderAuction, 250); } });
  const seg = (entries, value, assign) => h('div', { class: 'seg', style: { flexWrap: 'wrap' } }, entries.map(([k, t]) => h('button', { class: k === value ? 'on info' : '', onclick: () => { assign(k); renderAuction(); } }, t)));
  $('#content').replaceChildren(h('div', { class: 'stack' },
    gameHeader(v, 'muzayede', search, btn(null, () => renderAuction(), 'icon', 'refresh', { title: T('Yenile') })),
    h('div', { class: 'card auc-top' },
      h('div', { class: 'row between wrap', style: { gap: '10px' } },
        h('div', { class: 'row wrap', style: { gap: '8px' } }, ['hour', 'day', 'week'].map(counter)),
        h('div', { class: 'row wrap', style: { gap: '6px' } },
          btn(T('Hepsine katıl ({0} lot)', joinable.length), async () => joinable.length && await confirmBox(T('{0} lota teklif verilsin mi?', joinable.length),
            T('Her lota en düşük geçerli teklif verilir (toplam {0}). Teklifi geçilen lotun kredisi hemen geri gelir.', formatMoney('credits', total)), { ok: T('Katıl') })
            && auctionAll(joinable), 'sm primary', 'gavel', { disabled: !joinable.length }),
          btn(T('Görünenlere otomatik teklif…'), () => auctionBulkAuto(visible, v), 'sm', null, { disabled: !visible.length }),
          visible.some(l => l.oto) ? btn(T('Otomatikleri kapat'), () => auctionBulkDisable(visible.filter(l => l.oto)), 'sm ghost') : null)),
      h('div', { class: 'row wrap', style: { gap: '8px', marginTop: '12px' } },
        seg([['hepsi', T('Hepsi')]].concat(['hour', 'day', 'week'].map(k => [k, T(AUCTION_KIND[k])])), MZ.tur, k => { MZ.tur = k; }),
        seg(AUCTION_STATUS.map(([k, t]) => [k, T(t)]), MZ.durum, k => { MZ.durum = k; })),
      h('div', { style: { marginTop: '8px' } }, seg([['hepsi', T('Bütün gruplar')]].concat(groups.map(g => [g, AUCTION_GROUP[g] ? T(AUCTION_GROUP[g]) : g])), MZ.grup, k => { MZ.grup = k; })),
      !v.rakip ? h('p', { class: 'desc', style: { margin: '10px 0 0' } }, T('Sanal rakipler kapalı: teklif veren tek kişi sensin. Oyun Ayarları > Müzayede\'den açılabilir.')) : null),
    h('div', { class: 'auc-grid' }, visible.length ? visible.map(l => auctionCard(l, v)) : h('div', { class: 'empty' }, T('Lot yok.'))),
    h('div', { class: 'auc-bottom' },
      h('div', { class: 'card' }, h('h2', null, icon('bell'), T('Olaylar')), v.events.length ? h('div', { class: 'auc-list' }, v.events.map(o => h('div', { class: 'auc-event ' + auctionEventKind(o.tip) },
        dot(auctionEventKind(o.tip) === 'ok' ? 'ok' : auctionEventKind(o.tip) === 'err' ? 'warn' : ''), h('span', { class: 'grow' }, auctionEventText(o)),
        h('span', { class: 'mono muted' }, new Date(o.time * 1000).toLocaleTimeString(LOC(), { hour: '2-digit', minute: '2-digit' })))))
        : h('div', { class: 'empty' }, T('Henüz olay yok.'))),
      h('div', { class: 'card' }, h('h2', null, icon('clock'), T('Geçmiş')), v.gecmis.length ? h('div', { class: 'auc-list' }, v.gecmis.map(g => h('div', { class: 'auc-event' },
        gameIcon(g.loot, 26, v.firma, 'gavel'), h('span', { class: 'grow' }, itemName(g.loot), h('span', { class: 'muted' }, ' · ' + T(AUCTION_KIND[g.tur] || g.tur))),
        h('span', { class: g.kim === v.kimlik ? 'auc-me' : 'muted' }, g.ad || '—'), h('span', { class: 'mono' }, formatMoney('credits', g.teklif)))))
        : h('div', { class: 'empty' }, T('Geçmiş yok.'))))));
  S.timers.push(setInterval(() => {            // dönem sayaçları; dönem bitince liste yenilenir (kazanılan eşya, yeni dönem)
    const t = Date.now() / 1000;
    document.querySelectorAll('.auc-counter').forEach(el => { el.querySelector('b').textContent = fmtDur(MZ.bitis[el.dataset.tur] - t); });
    if (Object.values(MZ.bitis).some(b => b - t < -2) && !MZ.refreshing) { MZ.refreshing = true; setTimeout(() => { MZ.refreshing = false; if (S.page === 'muzayede') renderAuction(); }, 3000); }
  }, 1000));
}

function auctionCard(l, v) {
  const inp = h('input', { class: 'input num', type: 'number', min: l.next, step: v.increase, value: l.next });
  const state = l.onde ? badge(T('Öndesin'), 'ok') : l.highest ? badge(T('En yüksek: {0}', l.highest_name || '—'), 'warn') : badge(T('Teklif yok'));
  return h('div', { class: 'auc-card' + (l.onde ? ' onde' : '') },
    h('div', { class: 'row', style: { gap: '10px', alignItems: 'flex-start' } }, gameIcon(l.loot, 64, v.firma, 'gavel'),
      h('div', { class: 'grow' }, h('div', { class: 'shop-name', style: { minHeight: 0 } }, itemName(l.loot)),
        h('div', { class: 'row wrap', style: { gap: '4px', marginTop: '4px' } }, badge(T(AUCTION_KIND[l.tur])), l.adet > 1 ? badge('× ' + fmtN(l.adet)) : null,
          l.oto ? badge(T('Oto ≤ {0}', fmtN(l.oto.azami)), 'info') : null)),
      // alarm düğmesi başlıkta (alt satırda yer kalmayınca tek başına alta düşüyordu); kuruluysa turuncu
      btn(null, () => auctionAlarmWindow(l), 'sm icon ' + (l.alarm ? 'orange' : 'ghost'), 'bell', { title: l.alarm ? T('Alarm kurulu') : T('Alarm') })),
    h('div', { class: 'auc-row' }, h('span', { class: 'muted' }, T('En yüksek')), h('b', null, l.highest ? formatMoney('credits', l.highest) : '—')),
    h('div', { class: 'auc-row' }, h('span', { class: 'muted' }, T('Senin teklifin')), h('b', { class: l.onde ? 'auc-me' : '' }, l.benim ? formatMoney('credits', l.benim) : '—')),
    h('div', { class: 'row', style: { gap: '6px' } }, state),
    h('div', { class: 'row', style: { gap: '6px' } }, inp, btn(T('Teklif ver'), e => auctionBid(l, +inp.value | 0, e.currentTarget), 'sm primary'),
      btn('+' + fmtN(v.increase), () => { inp.value = (+inp.value | 0) + v.increase; }, 'sm ghost', null, { title: T('Teklifi artır') })),
    h('div', { class: 'row wrap', style: { gap: '6px' } },
      l.anlik ? btn(T('Anında al ({0})', formatMoney('uridium', l.fiyat)), async e => await confirmBox(T('{0} anında alınsın mı?', itemName(l.loot)), T('{0} uridyum harcanır.', fmtN(l.fiyat)), { ok: T('Al') })
        && auctionInstant(l), 'sm ghost') : null,
      btn(l.oto ? T('Otomatik: açık') : T('Otomatik teklif'), () => auctionAutoWindow(l, v), 'sm ' + (l.oto ? 'primary' : 'ghost'))));
}

async function auctionBid(l, price, b) {
  b.disabled = true;
  const r = await act(() => api('/api/oyun/muzayede/teklif', { tur: l.tur, loot: l.loot, price }));
  if (r && !r.tamam) toast(gameText(r.hata), 'err');
  else if (r) toast(T('Teklif verildi: {0}, {1}', itemName(l.loot), formatMoney('credits', price)), 'ok');
  renderAuction();
}

async function auctionAll(lots) {
  const r = await act(() => api('/api/oyun/muzayede/hepsi', { lotlar: lots.map(l => [l.tur, l.loot]) }));
  if (r) {
    if (r.given) toast(T('{0} lota teklif verildi: toplam {1}', r.given, formatMoney('credits', r.amount)), 'ok');
    for (const [k, n] of Object.entries(r.hatalar)) toast(gameText(k) + ' (' + n + ')', 'err');
  }
  renderAuction();
}

async function auctionInstant(l) {
  const r = await act(() => api('/api/oyun/muzayede/anlik', { tur: l.tur, loot: l.loot }));
  if (r && !r.tamam) toast(gameText(r.hata), 'err');
  else if (r) toast(T('Satın alındı: {0}', itemName(l.loot)), 'ok');
  renderAuction();
}

// otomatik teklif: azami tutara kadar, geçildikçe en düşük geçerli teklifi verir (oyun sunucusunda; panel kapalıyken de)
function auctionAutoWindow(l, v) {
  const inp = h('input', { class: 'input', type: 'number', min: v.en_az, step: v.increase, value: l.oto?.azami || Math.max(l.next * 2, v.en_az * 5) });
  const m = modal({ title: T('Otomatik teklif: {0}', itemName(l.loot)), sub: T('Geçildikçe en düşük geçerli teklif verilir; en çok bu tutara kadar. Panel kapalıyken de oyunda işler.'),
    body: [field(T('En çok (kredi)'), inp)], foot: [l.oto ? btn(T('Kapat'), () => { m.close(); auctionRule('oto', l, { azami: 0 }, T('Otomatik teklif kapandı.')); }, 'ghost') : null,
      btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Kaydet'), () => { m.close(); auctionRule('oto', l, { azami: +inp.value | 0 }, T('Otomatik teklif açık.')); }, 'primary')] });
}

function auctionAlarmWindow(l) {
  const a = l.alarm || {};
  const outbid = h('input', { type: 'checkbox', checked: a.gecilince ?? true });
  const minutes = h('select', { class: 'input' }, [[0, T('Kapalı')], [5, T('{0} dk', 5)], [15, T('{0} dk', 15)], [30, T('{0} dk', 30)], [60, T('{0} sa', 1)], [180, T('{0} sa', 3)]]
    .map(([n, t]) => h('option', { value: n, selected: (a.dk || 0) === n }, t)));
  const m = modal({ title: T('Alarm: {0}', itemName(l.loot)), sub: T('Alarm oyunda ekran mesajı, panelde bildirim olur.'),
    body: [h('label', { class: 'row', style: { gap: '8px' } }, outbid, T('Teklifim geçilince uyar')), field(T('Dönem bitmeden önce uyar'), minutes)],
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Kaydet'), () => { m.close(); auctionNotifyPermission();
      auctionRule('alarm', l, { gecilince: outbid.checked, dk: +minutes.value }, outbid.checked || +minutes.value ? T('Alarm kuruldu.') : T('Alarm kaldırıldı.')); }, 'primary')] });
}

async function auctionRule(kind, l, fields, okText) {
  const r = await act(() => api('/api/oyun/muzayede/' + kind, Object.assign({ tur: l.tur, loot: l.loot }, fields)));
  if (r) toast(okText, 'ok');
  renderAuction();
}

function auctionBulkAuto(lots, v) {
  const inp = h('input', { class: 'input', type: 'number', min: v.en_az, step: v.increase, value: v.en_az * 10 });
  const m = modal({ title: T('{0} lota otomatik teklif', lots.length), sub: T('Her lot için aynı en çok tutar. Kredin yettiği sürece geçildikçe teklif verilir.'),
    body: [field(T('Lot başına en çok (kredi)'), inp)], foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Kaydet'), async () => {
      m.close(); for (const l of lots) await api('/api/oyun/muzayede/oto', { tur: l.tur, loot: l.loot, azami: +inp.value | 0 }).catch(() => null);
      toast(T('{0} lota otomatik teklif açıldı.', lots.length), 'ok'); renderAuction(); }, 'primary')] });
}

async function auctionBulkDisable(lots) {
  for (const l of lots) await api('/api/oyun/muzayede/oto', { tur: l.tur, loot: l.loot, azami: 0 }).catch(() => null);
  toast(T('Otomatik teklifler kapandı.'), 'ok');
  renderAuction();
}

function auctionNotifyPermission() {
  try { if (window.Notification && Notification.permission === 'default') Notification.requestPermission(); } catch (e) { /* desteklenmiyor */ }
}

// yeni açık artırma olayları: her sayfada bildirim (ilk yoklama yalnız başlangıcı belirler); masaüstü bildirimi izin varsa
async function auctionEventTick() {
  if (srvState(S.durum).oyun !== 'acik' || auctionEventTick.busy) return;
  auctionEventTick.busy = true;
  try {
    const r = await api('/api/oyun/muzayede/olaylar?son=' + (MZ.son || 0));
    const new_ = r.events.filter(o => o.no > (MZ.son || 0)).reverse();
    if (MZ.son !== null) for (const o of new_) {
      toast(T('Açık artırma') + ': ' + auctionEventText(o), auctionEventKind(o.tip), 7000);
      try { if (window.Notification && Notification.permission === 'granted' && document.visibilityState !== 'visible') new Notification('OpenOrbit', { body: auctionEventText(o) }); } catch (e) { /* yok */ }
    }
    if (new_.length || MZ.son === null) MZ.son = Math.max(MZ.son || 0, ...r.events.map(o => o.no), 0);
    if (new_.length && S.page === 'muzayede') renderAuction();
  } catch (e) { /* oyuna girilmedi */ } finally { auctionEventTick.busy = false; }
}

const RENDER = { oyna: renderPlay, arkadas: renderFriends, kayitlar: () => renderSaves(), ayarlar: renderSettings, etkinlikler: () => renderEvents(), istemci: () => renderClient(),
  takvim: enterCalendar, sunucu: renderServer, panel: renderPanel, dunya: () => renderWorld(), botlar: () => renderBots(), magaza: renderShop, hangar: renderHangar, skylab: renderSkylab, muzayede: renderAuction };

// ------------------------------------------------------------------ başlangıç
async function boot() {
  let cfg = null;
  try { cfg = await api('/api/panel_settings'); } catch (e) { /* panel kapalı: poll bildirir */ }
  S.panelCfg = cfg;
  try { I18N.list = (await api('/api/diller')).languages; } catch (e) { /* eski liste: Türkçe, İngilizce */ }
  await setLang((cfg && cfg.dil) || guessLang());
  applyStatic();
  buildNav();
  loadGameImages();                                       // oyunun görselleri: oyun içi menülerin simgeleri
  go(location.hash.slice(1) || 'oyna', false);
  poll();
  if (cfg && (!cfg.dil || !cfg.setup_done)) openWizard(cfg.dil ? 1 : 0);
}
document.addEventListener('DOMContentLoaded', boot);      // sonraki betikler (world_editor.js) yüklendikten sonra
