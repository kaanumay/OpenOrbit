/* OpenOrbit yerel sunucu paneli — arayüz (panel.py'nin /api/... uçları). Dış kitaplık yok.
   Dil: metinler Türkçe yazılır, T() seçili dildeki hâlini verir (<kod>.json, yoksa en.json; Python tarafıyla ortak, dil.py).
   İlk açılışta kurulum sihirbazı: dil, oyun klasörü, ilk pilot, oyun ayarları (panel.json 'dil', 'kurulum_tamam'). Oyun
   bilgisayarda bulunamazsa oyun klasörü adımı onu indirmeye başlar (indirme.py; İstemci sayfasından da). Panel GitHub'daki yeni
   sürümü kurup yeniden başlayınca (guncelleme.py) belirteç değişir: sayfa kendini yeniler. */
'use strict';
const TOKEN = document.querySelector('meta[name="panel-token"]').content;
const $ = (s, r = document) => r.querySelector(s);

// ------------------------------------------------------------------ dil
// diller: /api/diller (dil.py DILLER); sözlükte olmayan metin İngilizceye, o da yoksa Türkçeye düşer
const I18N = { lang: 'tr', dict: {}, en: {}, list: [{ kod: 'tr', ad: 'Türkçe', yerel: 'tr-TR', kapsam: 100 }, { kod: 'en', ad: 'English', yerel: 'en-US', kapsam: 100 }] };
function T(s, ...a) {
  let r = I18N.dict[s] ?? I18N.en[s] ?? s;
  if (a.length) r = r.replace(/\{(\d+)\}/g, (m, i) => a[+i] == null ? '' : String(a[+i]));
  return r;
}
const langOf = k => I18N.list.find(x => x.kod === k);
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
  const kahve = $('#kahve');
  if (!kahve) return;
  const ac = () => act(() => api('/api/bagis', {}));
  const dugme = h('button', { class: 'kahve', type: 'button', title: 'buymeacoffee.com/kaanumay', onclick: ac }, art('dron_kahve', 'kahve-dron'),
    h('span', null, h('b', null, T('Bana bir kahve ısmarla')), h('small', null, T("OpenOrbit'i destekle"))));
  kahve.replaceChildren(dugme);
  // altında son destekçiler sola kayarak geçer (sayfadaki Recent supporters; çevrimdışıysa liste boş gelir, şerit hiç çıkmaz)
  api('/api/destekciler').then(d => {
    if (!d.adlar || !d.adlar.length || !dugme.isConnected) return;   // dil değişince applyStatic yeniden kurduysa eskisi eklenmesin
    const grup = () => h('span', { class: 'kahve-grup' }, d.adlar.map(a => h('span', null, a)));
    const sure = Math.max(12, d.adlar.join('').length * 0.45 + d.adlar.length * 2);   // ad sayısı arttıkça hız sabit kalsın
    kahve.append(h('button', { class: 'kahve-serit', type: 'button', title: T('Son destekçiler'), 'aria-label': T('Son destekçiler') + ': ' + d.adlar.join(', '), onclick: ac },
      h('span', { class: 'kahve-kayan', style: { animationDuration: sure + 's' } }, grup(), grup())));
  }).catch(() => {});
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
const art = (name, cls = 'art') => h('img', { class: cls, src: 'gorsel/' + name + '.webp', alt: '' });   // arayuz/gorsel/ (Orders.md)
const N = s => s;     // çevrilecek metin işareti: değişkende durur, T() ile gösterilir (test_panel_dil.py toplar)
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
  // oyun içi menüler: kenar çubuğunun ayrı bölümünde, yalnız oyun açıkken (panel_kanali.py); simge oyunun kendi görseli (sprite)
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
    p.oyun && OG.dizin?.sprite[p.sprite] ? sprite(p.sprite, 18) : icon(p.ic),
    h('span', null, T(p.ad)), p.beta ? h('span', { class: 'beta-etiket' }, 'Beta') : null,
    h('span', { class: 'badge', id: 'nav-badge-' + p.id, style: { display: 'none' } }));
  nav.replaceChildren(...PAGES.filter(p => !p.oyun).map(navBtn),
    h('div', { class: 'nav-oyun', id: 'nav-oyun', style: { display: 'none' } }, h('div', { class: 'nav-baslik' }, T('Oyun içi')),
      PAGES.filter(p => p.oyun).map(navBtn)));
}
function go(id, push = true) {
  if (!PAGES.find(p => p.id === id)) id = 'oyna';
  S.timers.forEach(clearInterval); S.timers = [];
  S.page = id; S.sig = {}; document.body.dataset.page = id;      // sayfa başlığının sahnesi (panel.css .topbar)
  if (push && location.hash !== '#' + id) history.replaceState(null, '', '#' + id);
  document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('active', b.dataset.page === id));
  const p = PAGES.find(x => x.id === id);
  $('#page-title').replaceChildren(T(p.ad), ...(p.beta ? [h('span', { class: 'beta-etiket' }, 'Beta')] : [])); $('#page-sub').textContent = T(p.sub);
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
  const navOyun = $('#nav-oyun'), oyunAcik = st.oyun === 'acik' && st.istemci === 'acik';
  if (navOyun) navOyun.style.display = oyunAcik ? '' : 'none';
  // oyun kapanınca oyun içi sayfadaki kullanıcı Oyna sayfasına döner (sayfanın verisi oyun sunucusundan)
  if (d && !oyunAcik && PAGES.find(p => p.id === S.page)?.oyun) {
    if (S.oyunAcikti) toast(T('Oyun kapandı: Oyna sayfasına dönüldü.'), 'info');
    go('oyna');
  }
  S.oyunAcikti = oyunAcik;
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
  if (S.page === 'sunucu') renderServerCards();
  if (S.page === 'arkadas' && ARK.veri) arkTick();
  poll.n = (poll.n || 0) + 1;
  if (poll.n % 3 === 0) muzayedeOlayTick();      // açık artırma bildirimleri (~5 sn)
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
      h('div', { class: 'pilot' }, firmaCls(a.firma) ? art('firma_' + firmaCls(a.firma), 'crest-sm') : null, a.pilot, badge(a.firma, firmaCls(a.firma)), a.klan ? badge('[' + a.klan + ']', 'info') : null),
      h('div', { class: 'meta' },
        [[T('Seviye'), a.seviye], [T('Gemi'), a.gemi], [T('Harita'), a.harita], [T('Oynama'), fmtDur(a.oynama_sn)],
          [T('Son oynama'), fmtWhen(a.son_oynama || a.son_kayit)]].map(([k, v]) => h('span', null, k + ' ', h('b', null, v)))),
      a.dunya_bilgi ? oynaDunyaCipi(a) : null,                    // kaydın varsayılan dünyası (dunya.js)
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
      stepList(o.adimlar));
  }
  const last = d.surecler.istemci.son;
  const early = last && last.erken && !running ? h('div', { class: 'alert uyari' }, icon('alert'),
    h('div', null, T('İstemci açıldıktan {0} sn sonra kapandı ({1}). Sunucular açık bırakıldı. İstemci günlüğüne bakın.', last.sure_sn, last.zaman)),
    btn(T('Günlük'), () => { go('sunucu'); setTimeout(() => showLog(d.panel.platform === 'win32' ? 'client.log' : 'wine.log'), 100); }, 'sm')) : null;

  // ---- uyarılar
  const warns = d.uyarilar.map(u => h('div', { class: 'alert ' + (u.tur === 'hata' ? 'hata' : 'uyari') }, icon('alert'),
    h('div', { style: u.ilerleme != null ? { flex: '1' } : null }, u.metin,
      u.ilerleme != null ? h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: u.ilerleme + '%' } }))) : null,
      u.indirme && u.indirme.toplam ? h('div', { class: 'small dl-info' }, dlInfo(u.indirme)) : null),
    u.eylem ? btn(u.eylem.calisiyor ? u.eylem.calisiyor_metin || T('Kuruluyor…') : u.eylem.metin, () => act(() => api(u.eylem.api, {})), 'primary sm', null, { disabled: !!u.eylem.calisiyor }) : null,
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
    h('div', { class: 'grid g2', style: { marginTop: '12px' } },
      h('div', { class: 'stack', style: { gap: '10px' } }, meter(T('Can'), g.can, g.can_azami, 'hp'), meter(T('Kalkan'), g.kalkan, g.kalkan_azami, 'sh'), meter(T('Kargo'), g.kargo, g.kargo_azami, 'cg')),
      h('div', { class: 'kv one' }, facts.map(([a, b]) => h('div', null, h('span', { class: 'muted' }, a), h('b', { title: b }, b))))),
    h('div', { class: 'live-alt' }, h('div', { class: 'stats', style: { marginTop: 0 } },
      [[T('Seviye'), p.seviye, 'lv'], [T('Kredi'), p.kredi, 'cr'], [T('Uridyum'), p.uridyum, 'ur'], [T('Onur'), p.onur, 'hn']].map(([a, v, c]) =>
        h('div', { class: 'stat' }, h('div', { class: 'k' }, a), h('div', { class: 'v ' + c }, fmtN(v))))),
      d.etkinlik_adlari && d.etkinlik_adlari.length ? h('div', { class: 'chips', style: { marginTop: '10px' } }, d.etkinlik_adlari.map(n => h('span', { class: 'chip' }, n))) : null));
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
const stepList = list => h('div', { class: 'steps' }, list.map(s => [h('div', { class: 'step ' + s.durum },
  h('span', { class: 'ic' }, s.durum === 'calisiyor' ? h('span', { class: 'spin' }) : icon(s.durum === 'hata' ? 'x' : 'check')),
  h('span', null, s.metin), h('span', { class: 'dim small', style: { marginLeft: 'auto' } }, s.zaman)),
  s.ilerleme && s.durum === 'calisiyor' ? prepBox(s.ilerleme) : null]));

// BepInEx'in ilk açılış hazırlığı (istemci_yama.isit/ilerleme): oyun penceresi henüz görünmez, oyuncu oyunun açılmadığını sanmasın
const PREP_ASAMA = [N('İstemci başlatılıyor'), N('Köprü derlemeleri üretiliyor'), N('Dosyalar yazılıyor')];
function prepBox(p) {
  return h('div', { class: 'prep' },
    h('div', { class: 'prep-head' }, icon('zap'), h('span', null, T('Düzeltmeler ilk açılışa hazırlanıyor')), h('b', null, '%' + p.yuzde)),
    h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: p.yuzde + '%' } }))),
    h('div', { class: 'prep-stages' }, PREP_ASAMA.map((a, i) => {
      const st = i < p.asama ? 'tamam' : i === p.asama ? 'calisiyor' : 'bekliyor';
      return h('div', { class: 'prep-stage ' + st }, h('span', { class: 'ic' }, st === 'tamam' ? icon('check') : st === 'calisiyor'
        ? h('span', { class: 'spin' }) : h('span', { class: 'dot-sm' })), h('span', null, T(a)));
    })),
    h('div', { class: 'small muted' }, T('Yalnız ilk açılışta bir kez yapılır; bu sırada oyun penceresi görünmez. Bitince oyun kendiliğinden açılır, bir şeye basman gerekmez.'),
      ' ', h('span', { class: 'dim' }, T('Geçen süre: {0}', fmtDur(p.gecen_sn)))));
}

// ---- Host
function hostView(v) {
  const hs = v.host, d = S.durum, st = srvState(d), busy = d?.oyna?.calisiyor, running = st.istemci === 'acik';
  const single = st.oyun === 'acik' && !hs.acik, guest = ARK_AKTIF(v.misafir.durum);
  const left = h('div', null, h('div', { class: 'slot-name' }, T('Arkadaş sunucusu')),
    h('div', { class: 'pilot' }, hs.acik ? T('Sunucun açık') : T('Sunucu kapalı'),
      hs.acik ? badge(T('{0} / {1} misafir', hs.misafirler.length, hs.en_cok), 'ok') : null, hs.sifre ? badge(T('Şifreli'), 'info') : null),
    h('div', { class: 'muted' }, hs.acik ? T('Arkadaşların aşağıdaki adreslerden biriyle katılır. Sen kendi kaydınla oynarsın.')
      : T('Sunucu kurunca kendi kaydınla oyuna girersin; arkadaşların kendi kayıtlarıyla katılır.')),
    d?.aktif ? h('div', { class: 'meta' }, h('span', null, T('Kayıt:') + ' ', h('b', null, d.aktif.ad)), h('span', null, T('Pilot') + ' ', h('b', null, d.aktif.pilot))) : null,
    v.dunya ? hostDunyaCipi(v) : null);                                // sunucunun dünyası (dunya.js)
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
  const dunya = v.dunya ? h('select', { class: 'input', onchange: e => act(() => api('/api/arkadas/ayarlar', { dunya: e.target.value }), T('Kaydedildi.'))
    .then(r => { if (r) { ARK.veri = r; drawArkadas(); } }) },
    h('option', { value: '', selected: !v.dunya.secim }, T('Kaydının dünyası ({0})', v.dunya.kaydin.ad)),
    v.dunya.liste.map(w => h('option', { value: w.id, selected: v.dunya.secim === w.id }, w.ad))) : null;
  const setCard = h('div', { class: 'card' }, h('h2', null, icon('sliders'), T('Sunucu ayarları')),
    h('div', { class: 'grid g2' }, field(T('Katılma şifresi'), pw), field(T('En çok misafir'), max)),
    dunya ? h('div', { style: { marginTop: '12px' } }, field(T('Sunucunun dünyası'), dunya),
      h('p', { class: 'small muted', style: { margin: '6px 0 0' } }, T('Misafirler de bu dünyada oynar (haritalar, uzaylılar, görevler, mağaza). Dünyaları Dünya Editörü\'nde hazırlarsın.'))) : null,
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
// Kayıtlar sayfası ve karakter editörü: kayit.js. Burada yeni pilot formu ve yedekler penceresi (kurulum sihirbazı da kullanır).

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
  const ilerlemeli = h('input', { type: 'checkbox' }), kampanya = h('input', { type: 'checkbox' });
  const cards = FIRMS.map(([id, k, n, c, m]) => {
    const el = h('div', { class: 'radio-card' + (id === st.firma ? ' on' : ''), style: { '--c': c }, onclick: () => {
      st.firma = id; el.parentNode.querySelectorAll('.radio-card').forEach(x => x.classList.remove('on')); el.classList.add('on');
    } }, art('firma_' + k.toLowerCase(), 'crest'), h('b', null, k), h('span', null, n), h('span', null, T('Başlangıç: {0}', m)));
    return el;
  });
  const el = [field(T('Pilot adı (oyunda görünür)'), pilot), field(T('Firma'), h('div', { class: 'radio-cards' }, cards)),
    field(T('Kayıt adı (isteğe bağlı)'), ad),
    start ? h('div', { class: 'grid g2' }, field(T('Başlangıç kredisi (isteğe bağlı)'), kredi), field(T('Başlangıç uridyumu (isteğe bağlı)'), uri),
      field(T('Başlangıç seviyesi (1-50, isteğe bağlı)'), seviye), field(T('Başlangıç onuru (isteğe bağlı)'), onur),
      field(T('LCB-10 lazer cephanesi (isteğe bağlı)'), lazer), field(T('R-310 roketi (isteğe bağlı)'), roket)) : null,
    h('label', { class: 'row small', title: T('Season Pass ilk sezondan (Mobius) başlar; her sezon bitince bir sonraki açılır, en yeniye dek. Sonradan eklenen sezonlar da sırası gelince açılır. Kapalıysa hep en yeni sezon.') },
      h('span', { class: 'switch' }, ilerlemeli, h('span')), T('Sezonları ilk sezondan sırayla aç')),
    h('label', { class: 'row small', title: T('Yeni sunucu açılışındaki "Level 1", "Level 5" … "Level 25" görevleri: seviyene ulaştıkça yüksek ödüller (gemiler, ekipman, uridyum, Premium). Kaydın açılışından itibaren 30 gün görev listesinde durur. Kapalıysa bu görevler hiç görünmez.') },
      h('span', { class: 'switch' }, kampanya, h('span')), T('Başlangıç kampanyası'))];
  const v = x => start ? x.value : '';
  return { el, pilot, values: () => ({ ad: ad.value.trim() || pilot.value.trim(), pilot: pilot.value.trim(), firma: st.firma,
    kredi: v(kredi), uridyum: v(uri), seviye: v(seviye), onur: v(onur), lazer: v(lazer), roket: v(roket), ilerlemeli: ilerlemeli.checked, kampanya: kampanya.checked }) };
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
        h('tbody', null, rows))) : h('div', { class: 'empty' }, art('bos_kayit'), h('div', null, T('Bu kaydın yedeği yok.'))),
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
  // bağlı ayar (s.kosul): yalnız o açma kapama ayarı açıkken, onun altında görünür
  if (s.kosul) { row.dataset.kosul = s.kosul; row.classList.toggle('kosul-kapali', !(S.ayar.degerler[s.kosul] ?? S.ayar.varsayilan[s.kosul])); }
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
    const cb = h('input', { type: 'checkbox', checked: v, onchange: e => {
      queueSave(s.anahtar, e.target.checked);
      document.querySelectorAll(`.set-row[data-kosul="${s.anahtar}"]`).forEach(c => c.classList.toggle('kosul-kapali', !e.target.checked));
    } });
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
        h('div', { class: 'grow' }, h('div', { class: 'ellipsis', style: { maxWidth: 'none' }, title: e.ad }, e.ad),
          h('div', { class: 'small muted' }, tkvSpan(e.sonraki[0], e.sonraki[1]))),     // tarih adın altında: dar kartta rozet taşmasın
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
    rows.map(evRow)) : h('div', { class: 'empty' }, art('bos_etkinlik'), h('div', null, T('Bu aralıkta gösterilecek etkinlik yok.'))));
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
  const info = st.durum === 'indiriliyor' ? dlInfo(st)
    : st.durum === 'bitti' ? st.hedef
    : st.durum === 'hata' ? st.hata
    : haveClient && st.yarim ? T('Seçili istemci kullanılıyor; yarım kalan dosyaları silebilirsin.')
    : st.durum === 'durdu' || st.yarim ? T('Sürdürünce yalnız eksik dosyalar iner.')
    : st.durum === 'bos' ? T('DarkOrbit {0} istemcisi oyunun resmî indirme sunucusundan alınıp proje klasörüne kurulur: yaklaşık 3,5 GB indirme, diskte 4,3 GB. İstemci dosyaları değiştirilmez.', (/(\d+\.\d+\.\d+)\.zip/.exec(st.url || '') || [])[1] || '')
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
// indirmenin satırı: inen / toplam, hız, kalan süre, dosya
function dlInfo(st) {
  return [`${fmtBytes(st.alinan)} / ${fmtBytes(st.toplam)}`, st.hiz ? `${fmtBytes(st.hiz)}/${T('sn')}` : null,
    st.kalan_sn != null && st.hiz ? T('kalan {0}', fmtDur(st.kalan_sn)) : null, T('dosya {0}/{1}', st.biten_dosya, st.dosya_sayisi)].filter(Boolean).join(' · ');
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

// ---- istemcinin düzeltmelerini yükleyen BepInEx (istemci_yama.py, /api/yama): İstemci sayfası ve sihirbazın oyun klasörü adımı
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
    h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('Oyunu indir')),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Hızlı indirme')),
      h('div', { class: 'help' }, T('Açıkken oyun aynı anda 3 bağlantıyla iner; kapalıyken tek bağlantıyla (daha yavaş). Bir sonraki indirmede geçerli olur.'))),
      h('div', { class: 'ctl' }, h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: cfg.hizli_indirme, onchange: e => saveCfg({ hizli_indirme: e.target.checked }) }), h('span')))),
    dlWrap,
    yWrap ? [h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('İstemci düzeltmeleri (BepInEx)')), yWrap] : null,
    h('div', { id: 'proto-box' }),
    h('div', { class: 'row wrap', style: { marginTop: '12px' } },
      btn(T('Klasör seç…'), () => act(() => api('/api/istemci/sec', {}), x => x.iptal ? T('İptal edildi.') : T('İstemci klasörü kaydedildi.')).then(x => x && renderIstemci(x)), 'primary', 'folder'),
      btn(T('Kendiliğinden bul'), () => act(() => api('/api/istemci/otomatik', {}), T('Kendiliğinden bulma açık.')).then(x => x && renderIstemci(x)), '', 'search'),
      btn(T('Klasörü aç'), () => act(() => api('/api/klasor_ac', { ne: 'istemci' })), 'ghost', 'folder')),
    r.adaylar.length > 1 || (r.adaylar.length === 1 && r.adaylar[0].yol !== c.yol) ? [h('hr', { class: 'sep' }), h('div', { class: 'lbl' }, T('Bulunan istemciler')),
      h('div', { class: 'stack', style: { gap: '8px', marginTop: '8px' } }, r.adaylar.map(a => h('div', { class: 'row' },
        badge(a.surum || '?', a.uyumlu ? 'ok' : 'warn'), h('span', { class: 'mono', style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, title: a.yol }, a.yol),
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
  const mon = h('select', { class: 'input', style: { width: '220px' }, onchange: e => saveCfg({ monitor: +e.target.value }) },
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
    T("Klasördeki DarkorbitLauncher.exe'yi çalıştırma: istemciyi resmî sunucudan güncelleyip yerel sunucuyla uyumu bozabilir. Panel istemcinin kendi dosyalarını değiştirmez; yerel giriş adresiyle başlatır, yanına kurduğu BepInEx'le küçük düzeltmeleri yükler.")));
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
  $('#content').replaceChildren(h('div', { class: 'stack' }, h('div', { class: 'grid g3', id: 'srv-cards' }), h('div', { class: 'grid g2' }, behav, ports), logs));
  S.sig = {};
  renderServerCards();
  loadLog();
  S.timers.push(setInterval(() => { if (logState.oto && document.visibilityState === 'visible') loadLog(true); }, 2000));
}

function renderServerCards() {
  const box = $('#srv-cards'), d = S.durum; if (!box || !d) return;
  // imza ekrandaki süre metniyle (fmtDur): saniyelik sure_sn her yoklamada kartları yeniden kurup fare altındaki düğmenin tıklamasını yutuyordu
  const s = d.surecler, sure = x => x && Object.assign({}, x, { sure_sn: x.sure_sn == null ? null : fmtDur(x.sure_sn) });
  const sig = JSON.stringify([Object.assign({}, s, { sunucular: { web: sure(s.sunucular.web), oyun: sure(s.sunucular.oyun) }, istemci: sure(s.istemci) }), d.oyna.calisiyor]);
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
      // yalnız simge: dört düğme kart genişliğine sığsın, "Konsol" tek başına alta düşmesin
      btn(null, () => act(() => api('/api/sunucu/yeniden', {}), T('Yeniden başlatıldı.')), 'sm icon', 'refresh', { disabled: busy || !srvOn, title: T('Yeniden başlat') + ' — ' + T('Oyun açıksa istemci yeniden bağlanmalı') }),
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
// ---- güncellemeler (guncelleme.py, /api/guncelleme): GitHub'daki son sürüm, otomatik kurulum
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
    const toggle = on => {                               // kapalıyken yeni sürüm yalnız haber verilir (bildir)
      save(on ? 'otomatik' : 'bildir');
      if (!on) { const m = modal({ title: T('Otomatik güncelleme kapatıldı'), body: T('Gün içinde çok sık güncelleme çıkabiliyor; sık sık kontrol etmeniz önerilir.'),
        foot: [btn(T('Tamam'), () => m.close(), 'primary')] }); }
    };
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
        h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Otomatik güncelleme')),
          h('div', { class: 'help' }, T('Açıkken yeni sürüm oyun ve sunucular kapanınca kendiliğinden kurulur; kapalıyken yalnız haber verilir.'))),
          h('div', { class: 'ctl' }, h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: r.ayar === 'otomatik', onchange: e => toggle(e.target.checked) }), h('span')))),
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

// ---- Discord Rich Presence (discord_rp.py, /api/discord_rp): Discord profilinde oyunun anlık hâli; oyuncu neyin görüneceğini seçer
const RP_ALANLAR = [['rp_pilot', N('Pilot adı'), N('Oyundaki adın (varsayılan kapalı).')], ['rp_klan', N('Klan etiketi'), N('Adın önünde [ETİKET].')],
  ['rp_gemi', N('Gemi'), N('Etkin geminin adı.')], ['rp_seviye', N('Seviye'), N('Pilotun seviyesi.')],
  ['rp_harita', N('Harita'), N('Harita adı ve bölgenin görseli.')], ['rp_durum', N('Ne yaptığın'), N('Savaştaki hedef, kapı dalgası, güvenli bölge.')],
  ['rp_firma', N('Firma'), N('Firmanın amblemi (küçük görsel).')], ['rp_sure', N('Oturum süresi'), N('Oyuna girdiğinden beri geçen süre.')],
  ['rp_grup', N('Grup'), N('Arkadaşlarınla Oyna: sunucundaki oyuncu sayısı.')], ['rp_butonlar', N('Düğmeler'), N("Discord sunucusu ve GitHub bağlantısı (başkaları görür).")],
  ['rp_panelde', N('Oyun kapalıyken'), N('Yalnız panel açıkken de "Panelde" görünür.')]];
const RP_DURUM = { bagli: [N("Discord'a bağlı"), 'ok'], discord_yok: [N('Discord açık değil'), 'warn'], hata: [N('Hata'), 'err'], kapali: [N('Kapalı'), ''] };
function rpCard() {
  const head = h('span', { class: 'rp-durum' });
  const body = h('div', { class: 'rp-govde' });
  const card = h('div', { class: 'card' }, h('h2', null, icon('users'), 'Discord Rich Presence', head),
    h('p', { class: 'desc' }, T('Discord profilinde OpenOrbit oynadığın ve oyunda ne yaptığın görünür. Discord masaüstü uygulaması açık olmalı; neyin görüneceğini aşağıdan seç.')), body);
  let sig = '', bas = null;
  const yerel = k => 'gorsel/discord/' + k + '.webp';     // Discord'daki varlığın adı (OP-018)
  const sure = () => { const s = Math.max(0, Math.floor(Date.now() / 1000 - bas)), p = n => String(n).padStart(2, '0');
    return T('{0} geçti', (s >= 3600 ? p(Math.floor(s / 3600)) + ':' : '') + p(Math.floor(s % 3600 / 60)) + ':' + p(s % 60)); };
  const save = vals => act(() => api('/api/panel_ayarlari', { degerler: vals })).then(x => x && load());
  const draw = r => {
    const s = JSON.stringify(r); if (s === sig) return; sig = s;
    const a = r.ayarlar, e = r.etkinlik, on = a.discord_rp, [dt, dc] = RP_DURUM[r.durum] || RP_DURUM.kapali;
    head.replaceChildren(badge(T(dt), dc));
    const sw = (k, dis) => h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: a[k], disabled: dis, onchange: ev => save({ [k]: ev.target.checked }) }), h('span'));
    bas = e && e.timestamps ? e.timestamps.start : null;
    const g = e && e.assets || {};
    const onizleme = h('div', { class: 'rp-kart' + (on && e ? '' : ' bos') }, h('div', { class: 'rp-ust' }, T('Oynuyor')),
      on && e ? h('div', { class: 'rp-ic' },
        h('div', { class: 'rp-gorsel' }, g.large_image ? h('img', { class: 'rp-buyuk', src: yerel(g.large_image), alt: '', title: g.large_text || '' }) : null,
          g.small_image ? h('img', { class: 'rp-kucuk', src: yerel(g.small_image), alt: '', title: g.small_text || '' }) : null),
        h('div', { class: 'rp-metin' }, h('b', null, 'OpenOrbit'), h('div', null, e.details),
          h('div', null, e.state, e.party ? ` (${T('{0} / {1}', e.party.size[0], e.party.size[1])})` : ''),
          bas ? h('div', { class: 'rp-sure' }, sure()) : null)) : h('div', { class: 'small muted' }, on ? T('Şu an profilinde bir şey görünmüyor.') : T('Rich Presence kapalı.')),
      on && e && e.buttons ? h('div', { class: 'rp-dugmeler' }, e.buttons.map(b => h('span', null, b.label))) : null);
    body.replaceChildren(h('div', { class: 'grid g2', style: { alignItems: 'start' } },
      h('div', { class: 'stack rp-ayar', style: { gap: '4px' } },
        h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Rich Presence')),
          h('div', { class: 'help' }, r.durum === 'discord_yok' ? T('Discord açılınca kendiliğinden bağlanır.') : r.durum === 'hata' ? r.hata : T('Kapatınca profilinden hemen kalkar.'))),
          h('div', { class: 'ctl' }, sw('discord_rp'))),
        h('div', { class: 'rp-alanlar' + (on ? '' : ' kapali') }, RP_ALANLAR.map(([k, ad, yardim]) => h('div', { class: 'set-row sub' },
          h('div', null, h('div', { class: 'name' }, T(ad)), h('div', { class: 'help' }, T(yardim))), h('div', { class: 'ctl' }, sw(k, !on)))))),
      h('div', { class: 'stack', style: { gap: '8px' } }, h('div', { class: 'small muted' }, T('Profilinde böyle görünür:')), onizleme)));
  };
  const load = () => api('/api/discord_rp').then(draw).catch(() => {});
  load();
  S.timers.push(setInterval(() => { if (card.isConnected) load(); }, 3000));
  S.timers.push(setInterval(() => { const x = card.querySelector('.rp-sure'); if (x && bas) x.textContent = sure(); }, 1000));
  return card;
}

async function renderPanel() {
  const r = await act(() => api('/api/hakkinda')); if (!r || S.page !== 'panel') return;
  const pathRow = (label, p, ne) => h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, label), h('div', { class: 'help mono' }, p)),
    h('div', { class: 'ctl' }, ne ? btn(T('Aç'), () => act(() => api('/api/klasor_ac', { ne })), 'sm', 'folder') : null));
  const langSeg = h('div', { class: 'seg diller' }, I18N.list.map(({ kod: k, ad: t }) => h('button', { class: I18N.lang === k ? 'on info' : '', onclick: async () => {
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
    rpCard(),
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
    h('div', { class: 'wz-head' }, h('img', { src: 'gorsel/amblem.webp', alt: '' }),
      h('div', null, h('div', { class: 'wz-brand' }, 'OPENORBIT'), h('div', { class: 'wz-kicker' }, WZ.step === 0 ? 'Kurulum · Setup' : T('Kurulum'))), steps),
    h('div', { class: 'wz-body' }, h('div', { class: 'wz-main' }, h('h2', null, p.title), p.sub ? h('div', { class: 'wz-sub' }, p.sub) : null, p.content),
      art('dron_' + id, 'wz-art')),
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
  // ---- 1. dil (her dil kendi adıyla; tarayıcının dili öne çıkar)
  dil: async () => {
    const cur = S.panelCfg?.dil, hint = cur || guessLang();
    const card = ({ kod, ad, kapsam }) => h('button', { class: 'wz-lang' + (cur === kod ? ' on' : hint === kod ? ' hint' : ''), type: 'button', onclick: () => chooseLang(kod) },
      h('span', { class: 'code' }, kod.toUpperCase()), h('b', null, ad), kapsam < 100 ? h('span', null, kapsam + '%') : null);
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
    let y = c.gecerli && r.yama.gerekli ? r.yama : null;  // istemcinin düzeltmeleri için BepInEx de kendiliğinden kurulur
    if (y && y.durum === 'yok' && !WZ.yamaAuto) { WZ.yamaAuto = true; y = await act(() => api('/api/yama/kur', {})) || y; }
    const yWrap = y ? h('div', { class: 'dl-wrap' }) : null;
    const chosen = x => { if (x) drawWizard(); };
    const use = p => act(() => api('/api/istemci/kullan', { yol: p })).then(chosen);
    const browse = () => act(() => api('/api/istemci/sec', {}), x => x.iptal ? T('İptal edildi.') : T('Oyun klasörü seçildi.')).then(chosen);
    const rows = r.adaylar.map(a => h('button', { class: 'wz-opt' + (a.yol === c.yol ? ' on' : ''), type: 'button', onclick: () => use(a.yol) },
      h('span', { class: 'wz-radio' }), h('span', { class: 'mono' }, a.yol), badge(a.surum || '?', a.uyumlu ? 'ok' : 'warn')));
    return {
      title: T('DarkOrbit oyun klasörü'),
      sub: T("Orijinal DarkOrbit istemcisinin klasörü: içinde DarkOrbit.exe ve DarkOrbit_Data olmalı. Panel istemcinin kendi dosyalarını değiştirmez; yanına küçük düzeltmeler için BepInEx kurar."),
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
    const rows = [[true, T('Dil'), langOf(I18N.lang).ad],
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

// ================================================================== OYUN İÇİ: ORTAK
// Mağaza, Hangar ve Skylab oyun sunucusundan (panel_kanali.py: istemcinin istekleriyle aynı yol; oyundaki pencereler de güncellenir).
// Görseller ve eşya adları istemcinin BepInEx eklentisinin dökümü (/oyun_gorsel/: atlas sayfaları, dizin.json, adlar_<dil>.json).
// Üç sayfanın üstünde aynı çubuk: sayfalar arasında geçiş, cüzdan ve güvenli bölge (donanım yalnız orada değişir: panel_kanali.istasyonda).
const OG = { dizin: null, adlar: {}, dil: null };
async function ogYukle() {
  const j = async n => { const r = await fetch('/oyun_gorsel/' + n); if (!r.ok) throw new Error(r.status); return r.json(); };
  if (!OG.dizin) { try { OG.dizin = await j('dizin.json'); buildNav(); renderChrome(); } catch (e) { /* döküm yok: simgeler, ham adlar */ } }
  if (OG.dizin && OG.dil !== I18N.lang) { try { OG.adlar = await j('adlar_' + I18N.lang + '.json'); OG.dil = I18N.lang; } catch (e) { OG.adlar = {}; } }
}
// oyunun bir sprite'ı: atlas sayfasından kırpılır, kutuya (boy x boy) orantılı sığdırılır (dizin: sayfa, x, y, g, y, tam g, tam y, ox, oy)
function sprite(ad, boy) {
  const e = OG.dizin?.sprite[ad], kutu = h('span', { class: 'sprite', style: { width: boy + 'px', height: boy + 'px' } });
  if (!e) return kutu;
  const [sayfa, x, y, w, hh, W, H, ox, oy] = e, [pw, ph] = OG.dizin.sayfalar[sayfa], k = boy / Math.max(W, H);
  kutu.append(h('span', { style: { width: W * k + 'px', height: H * k + 'px', position: 'relative' } }, h('span', { style: {
    position: 'absolute', left: ox * k + 'px', top: oy * k + 'px', width: w * k + 'px', height: hh * k + 'px',
    background: 'url("/oyun_gorsel/' + sayfa + '.png") ' + (-x * k) + 'px ' + (-y * k) + 'px / ' + pw * k + 'px ' + ph * k + 'px no-repeat' } })));
  return kutu;
}
// lootId -> sprite adı: kimliğin son parçası (lf-4_100x100); gemiler şirkete göre (aegis-eic), dronlar seviyeyle (flax-1)
function esyaSprite(lid, firma) {
  const k = lid.includes('_') ? lid.slice(lid.indexOf('_') + 1) : lid, son = k.split('_').pop();
  for (const c of [son, k.replace(/_/g, '-'), k, son + '-' + firma, son + '-1'])
    for (const b of ['_100x100', '_63x63', '_top', '_30x30', '']) if (OG.dizin?.sprite[c + b]) return c + b;
  return null;
}
const esyaAdi = lid => OG.adlar[lid] || lid.slice(lid.indexOf('_') + 1).replace(/[_-]/g, ' ').toUpperCase();
const oyunIkon = (lid, boy, firma, ic = 'hangar') => {
  const sp = lid && esyaSprite(lid, firma), el = sp ? sprite(sp, boy) : h('span', { class: 'sprite bos', style: { width: boy + 'px', height: boy + 'px' } }, icon(ic));
  if (lid) el.dataset.loot = lid;                // eşya ipucu (esyaIpucu)
  return el;
};

// ---- eşya ipucu: simgenin üstünde durunca oyunun metinleri (eklentinin dökümü metinler_<dil>.json: ad, tür, ipucu açıklaması,
// açıklama, not, kaynak; nitelik adları; dilde yoksa İngilizce) ve sunucunun değerleri (/api/esya_bilgi: hasar, kalkan, bonuslar,
// gemiler, yükseltme, satış). Örneğe özgü bilgi (yükseltme seviyesi, rastgele nitelikler, hak) simgenin bir üst öğesinin _esya'sında.
const IP = { metin: null, en: null, dil: null, bilgi: null, el: null, zaman: 0, kutu: null, yukleniyor: null };
const IP_ETIKET = { hasar: N('Hasar'), pvp_hasar: N('Oyunculara hasar'), kalkan: N('Kalkan'), emme: N('Hasar emme'), hiz: N('Hız'), can: N('Can'), kargo: N('Kargo'),
  lazer_carpan: N('Lazer hasarı'), isabet: N('İsabet'), tam_onarim: N('Tam onarım'), dakikada_can: N('Dakikada onarım'), hak: N('Dolum başına hak'), ek_yuva: N('Ek ekstra yuvası'),
  bekleme: N('Bekleme'), kargo_carpan: N('Kargo'), dron_kalkan: N('Dron kalkanı'), dron_lazer: N('Dron lazer hasarı'), sure: N('Süre'), en_az: N('En az bonus'),
  deger_araligi: N('Değer aralığı'), yeniden_cekme: N('Yeniden çekme hakkı'), taban_hasar: N('Temel hasar'), element: N('Element'), ek_nitelik: N('Ek nitelik'),
  savunma: N('Savunma'), atis: N('Atış'), kalite: N('Kalite'), azami_seviye: N('En yüksek seviye'), menzil: N('Menzil'), sure_sn: N('Süre (sn)'),
  seviye_bonus: N('Seviyelere göre'), booster_shield_regeneration: N('Kalkan yenilenmesi'), booster_repair: N('Onarım'), booster_collect_resources: N('Kaynak toplama'),
  booster_collect_resources_newbie: N('Kaynak toplama'), booster_ability_cooldown_time: N('Yetenek beklemesi') };
const IP_ELEMENT = { thermal: N('Termal'), corrosive: N('Korozif'), electro: N('Elektro') };
const IP_YUKSELTME = { LASER_DAMAGE_UPGRADE: N('hasar'), ROCKETLAUNCHER_DAMAGE_UPGRADE: N('hasar'), GENERATOR_SHIELD_UPGRADE: N('kalkan'), DRONE_SHIELD_UPGRADE: N('dron kalkanı'),
  DRONE_DAMAGE_UPGRADE: N('dron hasarı'), CANNON_DAMAGE_UPGRADE: N('hasar'), CANNON_DEF_UPGRADE: N('savunma'), DRIVE_DAMAGE_UPGRADE: N('hasar'), DRIVE_DEF_UPGRADE: N('savunma') };
const IP_YUVA = { lasers: N('Lazer'), generators: N('Jeneratör'), extras: N('Ekstra'), heavy_guns: N('Roketatar'), ship_upgrades: N('Modül'), QuantumFluidCore: 'QFC',
  cannons: N('Top'), cannon_shields: N('Kırıcı'), drives: N('Sürücü'), lenses: N('Mercek'), default: N('Donanım yuvası') };
const IP_YER = { SHIP: N('Gemi'), PET: 'P.E.T.', DRONE: N('Dron') };
async function ipucuYukle() {
  const j = async n => { const r = await fetch('/oyun_gorsel/' + n); if (!r.ok) throw new Error(r.status); return r.json(); };
  if (OG.dizin && IP.dil !== I18N.lang) {
    IP.dil = I18N.lang;
    try { IP.metin = await j('metinler_' + I18N.lang + '.json'); } catch (e) { IP.metin = null; }
    if (!IP.en && I18N.lang !== 'en') { try { IP.en = await j('metinler_en.json'); } catch (e) { /* eski döküm: yalnız adlar */ } }
  }
  if (!IP.bilgi) { try { IP.bilgi = (await api('/api/esya_bilgi')).esyalar; } catch (e) { IP.bilgi = {}; } }
}
const ipMetin = lid => IP.metin?.e[lid] || IP.en?.e[lid] || null;
const nitelikAdi = a => IP.metin?.n[a] || IP.en?.n[a] || a.replace(/_/g, ' ');
const ipYuzde = v => (v > 0 ? '+' : '') + (Math.round(v * 1000) / 10).toLocaleString(LOC()) + '%';
function ipDeger(v, b) {
  if (typeof v === 'string') return b === 'e' ? T(IP_ELEMENT[v] || v) : v;
  return { p: () => (Math.round(v * 1000) / 10).toLocaleString(LOC()) + '%', x: () => '×' + fmtN(v), sn: () => fmtDur(v), sa: () => fmtDur(v * 3600) }[b]?.() ?? fmtN(v);
}
// açıklamadaki yer tutucular (%HOURS%, %BOOSTERVALUE% …; "+%%BOOSTERVALUE%" = "+%" ve değer) değeriyle, yoksa "…"; <br> satır sonu,
// öbür etiketler atılır
const ipYerTutucu = (s, ph) => s.replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '')
  .replace(/%([A-Za-z_]+)%/g, (m, k) => { const v = ph && (ph[k] ?? ph[k.toUpperCase()]); return v != null && v !== '' ? String(v) : '…'; });

function esyaIpucu(lid, es, firma) {
  const mt = ipMetin(lid), b = IP.bilgi?.[lid] || {}, ph = b.ph;
  const satir = (k, v, cls = '') => h('div', { class: 'ip-satir ' + cls }, h('span', null, k), h('b', null, v));
  const govde = [];
  // ipucu açıklaması kısa etki satırı; açıklamanın başıyla aynıysa (formasyonlar) yalnız açıklama
  if (mt?.[2] && !(mt[3] && mt[3].slice(0, 30) === mt[2].slice(0, 30))) govde.push(h('div', { class: 'ip-etki' }, ipYerTutucu(mt[2], ph)));
  if (mt?.[3]) govde.push(h('div', { class: 'ip-aciklama' }, ipYerTutucu(mt[3], ph)));
  const degerler = (b.dg || []).map(([k, v, f]) => satir(T(IP_ETIKET[k] || k), ipDeger(v, f)));
  for (const [a, v] of b.m || []) degerler.push(satir(nitelikAdi(a), ipYuzde(v), 'bonus'));
  if (degerler.length) govde.push(h('div', { class: 'ip-blok' }, degerler));
  if (b.yv) govde.push(h('div', { class: 'ip-yuvalar' }, Object.entries(b.yv).map(([k, n]) => h('span', null, T(IP_YUVA[k] || k), h('b', null, n)))));
  for (const [y, az, t] of b.up || []) {
    const su = es?.yukseltme || 0;
    govde.push(h('div', { class: 'ip-blok' }, h('div', { class: 'ip-baslik' }, T('Yükseltme')),
      satir(T('Seviye başına'), ipYuzde(y) + ' ' + T(IP_YUKSELTME[t] || t)), satir(T('En yüksek seviye'), '+' + az),
      su ? satir(T('Şimdiki seviye'), '+' + su + ' · ' + ipYuzde(y * su), 'bonus') : null));
  }
  const r = es?.rng;
  if (r?.nitelik?.length) {
    const kesir = r.tur === 'modul';
    govde.push(h('div', { class: 'ip-blok rng' }, h('div', { class: 'ip-baslik' }, T('Bu eşyanın nitelikleri')),
      r.nitelik.map(([a, v]) => satir(nitelikAdi(a), ipYuzde(kesir ? v : v / 100), 'bonus')),
      r.seviye ? satir(T('Seviye'), r.seviye) : null, r.yildiz ? satir(T('Yıldız'), '★'.repeat(r.yildiz)) : null,
      r.hak != null ? satir(T('Yeniden çekme hakkı'), r.hak) : null));
  }
  const gemiler = r?.gemiler || (r?.gemi ? [r.gemi] : null) || b.gm;
  if (gemiler?.length) govde.push(h('div', { class: 'ip-blok' }, h('div', { class: 'ip-baslik' }, r?.gemiler || r?.gemi ? T('Geçtiği gemiler') : b.dg?.some(d => d[0] === 'en_az') ? T('Daha sık çıktığı gemiler') : T('Geçtiği gemiler')),
    h('div', { class: 'ip-gemiler' }, gemiler.map(g => h('span', null, oyunIkon(g, 22, firma, 'ship'), esyaAdi(g))))));
  if (es?.hak != null) govde.push(satir(T('Kalan hak'), fmtN(es.hak[0]) + ' / ' + fmtN(es.hak[1])));
  if (mt?.[4]) govde.push(h('div', { class: 'ip-not' }, icon('info'), ipYerTutucu(mt[4], ph)));
  const alt = [b.tk ? T('Takılır: {0}', b.tk.map(x => T(IP_YER[x] || x)).join(', ')) : null, b.sat ? T('Satış: {0}', fmtN(b.sat) + ' C.') : null].filter(Boolean);
  if (mt?.[5]) govde.push(h('div', { class: 'ip-kaynak' }, ipYerTutucu(mt[5], ph)));
  return h('div', { class: 'ipucu' },
    h('div', { class: 'ip-bas' }, oyunIkon(lid, 52, firma, 'box'), h('div', { style: { minWidth: 0 } },
      h('b', null, esyaAdi(lid) + (es?.yukseltme ? ' +' + es.yukseltme : '')), mt?.[1] ? h('div', { class: 'ip-tur' }, mt[1]) : null,
      es?.seviye ? h('div', { class: 'ip-tur' }, T('Sv {0}', es.seviye)) : null)),
    govde.length ? govde : h('div', { class: 'ip-aciklama dim' }, lid),
    alt.length ? h('div', { class: 'ip-alt' }, alt.join(' · ')) : null);
}
function ipucuKapat() { clearTimeout(IP.zaman); IP.el = null; IP.kutu?.remove(); IP.kutu = null; }
document.addEventListener('mouseover', e => {
  const el = e.target.closest?.('[data-loot]');
  if (el === IP.el) return;
  ipucuKapat();
  if (!el || el.closest('.ipucu')) return;
  IP.el = el;
  for (let n = el; n && n !== document.body; n = n.parentElement) if (n.title) { n.dataset.baslik = n.title; n.removeAttribute('title'); }   // tarayıcının ad balonu yerine
  IP.zaman = setTimeout(async () => {
    await (IP.yukleniyor ||= ipucuYukle().finally(() => { IP.yukleniyor = null; }));
    if (IP.el !== el || !el.isConnected) return;
    let es = null;
    for (let n = el; n && !es; n = n.parentElement) es = n._esya || null;
    const k = esyaIpucu(el.dataset.loot, es, el.dataset.firma);
    document.body.append(k);
    IP.kutu = k;
    const r = el.getBoundingClientRect(), w = k.offsetWidth, hh = k.offsetHeight;
    k.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.right + 10 + w > window.innerWidth ? r.left - w - 10 : r.right + 10)) + 'px';
    k.style.top = Math.max(8, Math.min(window.innerHeight - hh - 8, r.top)) + 'px';
  }, 260);
});
document.addEventListener('mousedown', ipucuKapat, true);
document.addEventListener('scroll', ipucuKapat, true);
const paraYaz = (cur, n) => fmtN(n) + (cur === 'credits' || cur === 'kredi' ? ' C.' : ' U.');
// sunucunun hata ve bilgi anahtarları (BaseKey adları, panel_kanali'nin kendi anahtarları); ham metin (boşluklu) olduğu gibi
const OY_METIN = { not_enough_credits: N('Yeterli kredin yok.'), not_enough_uridium: N('Yeterli uridyumun yok.'), shop_item_not_found: N('Bu ürün şu an satılmıyor.'),
  drone_have_max: N('Dron sayısı en çokta.'), info_text_switch_hangar_station_only: N('Gemi yalnız istasyondayken değiştirilebilir.'),
  error_can_not_equip_to_slot: N('Bu eşya bu yuvaya takılamaz.'), config_change_failed_time: N('Config değiştirmek için biraz bekle.'),
  items_hangarSlot_max_favs: N('En çok 10 favori gemi olabilir.'), error_pet_name_length: N('P.E.T. adı 1-24 karakter olmalı.'),
  error_pet_name_char: N('P.E.T. adında yalnız harf ve rakam olabilir.'), drone_slotCPUinUse: N('Yuva CPU\'su kullanımda: önce ekstra yuvalarını boşalt.'),
  pet_gear_requirement: N('P.E.T.\'in seviyesi bu eşya için yetmiyor.'), special_generic_hint: N('Bu ekstradan config\'te zaten var.') };
const oyunMetni = k => OY_METIN[k] ? T(OY_METIN[k]) : k && k.includes(' ') ? k : T('İşlem yapılamadı ({0}).', k || '?');
const OYUN_SAYFALARI = [['magaza', N('Mağaza'), 'shop_normal', 'cart'], ['hangar', N('Hangar'), 'hangar_normal', 'hangar'], ['skylab', N('Skylab'), 'skylab_normal', 'lab'],
  ['muzayede', N('Açık Artırma'), 'auction_normal', 'gavel']];

// üç sayfanın ortak üst çubuğu; ekler: sayfaya özgü düğmeler (arama, yenile)
function oyunUstu(v, sayfa, ...ekler) {
  const para = (ad, n) => h('span', { class: 'pill mg-para' }, art('kaynak_' + ad, 'mg-kaynak'), h('b', null, fmtN(n)));
  return h('div', { class: 'card oy-ust' },
    h('div', { class: 'oy-sekmeler' }, OYUN_SAYFALARI.map(([id, ad, sp, ic]) => h('button', { class: 'oy-sekme' + (id === sayfa ? ' on' : ''), type: 'button',
      onclick: () => id !== sayfa && go(id) }, OG.dizin?.sprite[sp] ? sprite(sp, 22) : icon(ic), h('span', null, T(ad))))),
    h('div', { class: 'row wrap', style: { gap: '8px', justifyContent: 'flex-end' } }, para('kredi', v.kredi), para('uridyum', v.uridyum),
      h('span', { class: 'pill ' + (v.istasyonda ? 'oy-guvenli' : 'oy-uzay'), title: v.istasyonda ? T('Donanım değiştirilebilir.') : T('Donanım yalnız güvenli bölgede değiştirilebilir.') },
        dot(v.istasyonda ? 'ok' : 'warn'), v.istasyonda ? T('Güvenli bölgede') : T('Uzayda')), ...ekler));
}
function oyunHatasi(e, sayfa) {
  $('#content').replaceChildren(h('div', { class: 'card' }, h('div', { class: 'empty' }, h('p', null, e.message), btn(T('Yenile'), () => go(sayfa), '', 'refresh'))));
}

// ================================================================== OYUN İÇİ: MAĞAZA
const MG_KATEGORI = { ship: N('Gemiler'), shipdesign: N('Gemi tasarımları'), laser: N('Lazerler'), ammunition: N('Cephane'), generator: N('Jeneratörler'),
  extras: N('Ekstralar'), booster: N('Boosterlar'), drone: N('Dronlar'), petgear: N('P.E.T. donanımı'), protocol: N('Protokoller'), customization: N('Kişiselleştirme') };
const MG = { veri: null, kat: null, ara: '', seviye: {} };

async function renderMagaza() {
  await ogYukle();
  try { MG.veri = await api('/api/oyun/magaza'); } catch (e) { return oyunHatasi(e, 'magaza'); }
  if (!MG.veri.kategoriler.includes(MG.kat)) MG.kat = MG.veri.kategoriler[0];
  const izgara = h('div', { class: 'mg-izgara' });
  const liste = () => {
    const q = MG.ara.trim().toLowerCase(), its = (MG.veri.esyalar[MG.kat] || []).filter(it => !q || esyaAdi(it.lootId).toLowerCase().includes(q));
    izgara.replaceChildren(...its.map(magazaKart));
    if (!its.length) izgara.append(h('div', { class: 'empty' }, T('Ürün yok.')));
  };
  const ara = h('input', { class: 'input oy-ara', placeholder: T('Ara…'), value: MG.ara, oninput: e => { MG.ara = e.target.value; liste(); } });
  $('#content').replaceChildren(h('div', { class: 'stack' },
    oyunUstu(MG.veri, 'magaza', ara, btn(null, () => renderMagaza(), 'icon', 'refresh', { title: T('Yenile') })),
    h('div', { class: 'card' },
      !MG.veri.gorsel ? h('p', { class: 'desc' }, T('Oyunun görselleri, oyun bir kez BepInEx ile açılınca hazırlanır.')) : null,
      h('div', { class: 'seg', style: { flexWrap: 'wrap' } }, MG.veri.kategoriler.map(c =>
        h('button', { class: c === MG.kat ? 'on info' : '', onclick: () => { MG.kat = c; renderMagaza(); } }, MG_KATEGORI[c] ? T(MG_KATEGORI[c]) : c)))),
    izgara));
  liste();
}

function magazaKart(it) {
  // seviyeli ürün (P.E.T. dişlisi, protokol): fiyat seviye başına, maxAmount P.E.T.'in izin verdiği en yüksek seviye (magaza.shop_list)
  const seviyeli = (it.price || []).length > 1, yetmez = it.maxAmount === -1;
  const sv = Math.min(MG.seviye[it.lootId] || 1, seviyeli ? Math.max(1, it.maxAmount) : 1);
  const cok = !seviyeli && (!!it.amountsSelectable || it.maxAmount > 1);
  const adet = cok ? h('input', { class: 'input num', type: 'number', min: 1, max: it.maxAmount > 0 ? it.maxAmount : null, value: 1 }) : null;
  // sunucunun cost metni İngilizce biçimli ("190,000 U."): fiyat panelin sayı biçimiyle yazılır
  const fiyat = it.price?.length ? fmtN(it.price[sv - 1]) + (it.currency === 'real' ? ' U.' : ' C.') : it.cost;
  return h('div', { class: 'mg-kart' + (yetmez ? ' yetmez' : '') },
    oyunIkon(it.lootId, 84, MG.veri.firma, 'cart'),
    h('div', { class: 'mg-ad', title: it.lootId }, esyaAdi(it.lootId)),
    seviyeli ? h('div', { class: 'seg mg-sv' }, it.price.map((p, i) => h('button', { class: i + 1 === sv ? 'on info' : '', disabled: i + 1 > Math.max(1, it.maxAmount),
      onclick: () => { MG.seviye[it.lootId] = i + 1; renderMagaza(); } }, T('Sv {0}', i + 1)))) : null,
    h('div', { class: 'mg-fiyat ' + (it.currency === 'real' ? 'uri' : 'kre') }, fiyat),
    h('div', { class: 'row', style: { gap: '6px', justifyContent: 'center' } }, adet,
      btn(T('Satın al'), e => magazaAl(it, adet ? Math.max(1, +adet.value | 0) : 1, sv, e.currentTarget), 'sm primary', null, { disabled: yetmez })),
    it.canBeSubscribedTo ? btn(it.isSubscriptionRunning ? T('Aboneliği bitir') : T('Abone ol'), e => magazaAbone(it, e.currentTarget), 'sm ghost') : null);
}

async function magazaAl(it, n, sv, b) {
  b.disabled = true;
  const r = await act(() => api('/api/oyun/al', { lootId: it.lootId, category: it.category, amount: n, level: sv }));
  b.disabled = false;
  if (!r) return;
  if (!r.tamam) return toast(OY_METIN[r.hata] ? T(OY_METIN[r.hata]) : T('Satın alınamadı ({0}).', r.hata || '?'), 'err');
  toast(T('Satın alındı: {0}', (n > 1 ? fmtN(n) + ' × ' : '') + esyaAdi(it.lootId)), 'ok');
  renderMagaza();                       // cüzdan ve liste (alınan tekil eşya listeden düşer, adetler paraya göre)
}

async function magazaAbone(it, b) {
  b.disabled = true;
  const r = await act(() => api('/api/oyun/magaza/abone', { lootId: it.lootId, category: it.category }));
  if (r && !r.tamam) toast(oyunMetni(r.hata), 'err');
  renderMagaza();
}

// ================================================================== OYUN İÇİ: HANGAR
// Gemiler, iki config; gemi, dron ve P.E.T. yuvaları, CPU'lar (panel_kanali.py /hangar). Envanterdeki eşyaya tıklayınca seçili config'te
// seçili bölüme (gemi, seçili dron, P.E.T. ya da HEAT yuvası) takılır, yuvadakine tıklayınca çıkarılır (HangarShipMoveItemsRequest).
// Satış kipinde envanterden seçilenler birlikte satılır. Güvenli bölge dışında donanım değişmez (düğmeler kapalı, sunucu da reddeder).
const HG_YUVA = { laser: N('Lazerler'), rocket: N('Roketatar'), generators: N('Jeneratörler'), extra: N('Ekstralar'), upgrades: N('Gemi modülleri'),
  QuantumFluidCore: 'Quantum Fluid Core', cannon: N('Parçacık topları'), cannonShield: N('Kırıcılar'), drive: 'Singularity Drive', lens: N('Mercekler'),
  lasers: N('Lazerler'), gears: N('Dişliler'), protocols: N('Protokoller'), visual: N('Görünüm'), heat: 'HEAT', tasarim: N('Dron tasarımları'), diger: N('Diğer') };
const yuvaAdi = y => HG_YUVA[y] ? T(HG_YUVA[y]) : y;
const HG = { gemi: null, konfig: null, bolum: 'ship', dron: null, yuva: {}, kip: 'tak', kume: '', secili: {} };

async function renderHangar() {
  await ogYukle();
  let v;
  try { v = await api('/api/oyun/hangar?gemi=' + encodeURIComponent(HG.gemi || '')); } catch (e) { return oyunHatasi(e, 'hangar'); }
  HG.gemi = v.gemi;
  if (!v.konfigler[HG.konfig]) HG.konfig = v.aktif_konfig;
  if (HG.bolum === 'pet' && !v.pet) HG.bolum = 'ship';
  const dronlar = v.dronlar[HG.konfig] || [], kilit = !v.istasyonda, ikon = (lid, boy) => oyunIkon(lid, boy, v.firma);
  if (!dronlar.find(d => d.id === HG.dron)) HG.dron = dronlar[0]?.id ?? null;
  const gemi = v.gemiler.find(g => g.id === v.gemi);
  const svRozet = e => e.seviye ? h('span', { class: 'hg-sv' }, '+' + e.seviye) : null;
  const cikar = (e, hedef, dron) => h('button', { class: 'hg-esya', type: 'button', disabled: kilit, title: esyaAdi(e.lootId) + ' — ' + T('çıkarmak için tıkla'),
    onclick: ev => hangarTasi({ esya: e.id, yon: 'cikar', hedef, dron }, ev.currentTarget) }, ikon(e.lootId, 44));
  const bos = n => Array.from({ length: Math.max(0, n) }, () => h('span', { class: 'hg-esya bos' }));
  const yuvaKutusu = (ad, c, hedef, ek) => h('div', { class: 'hg-yuva' }, h('div', { class: 'row between' }, h('b', null, yuvaAdi(ad)),
    h('span', { class: 'row', style: { gap: '6px' } }, ek, h('span', { class: 'mono' }, c.esyalar.length + ' / ' + c.kapasite))),
    h('div', { class: 'hg-izgara' }, c.esyalar.map(e => cikar(e, hedef)), bos(c.kapasite - c.esyalar.length)));
  // gemiler: etkin önce; yıldız favori (oyunda ışınlanabilen gemiler)
  const gemiler = h('div', { class: 'hg-gemiler' }, [...v.gemiler].sort((a, b) => b.aktif - a.aktif || b.favori - a.favori).map(g => h('div', { class: 'hg-gemi' + (g.id === v.gemi ? ' on' : ''),
    title: esyaAdi(g.lootId), onclick: () => { HG.gemi = g.id; renderHangar(); } },
    h('button', { class: 'hg-yildiz' + (g.favori ? ' on' : ''), type: 'button', title: g.favori ? T('Favoriden çıkar') : T('Favori yap'),
      onclick: ev => { ev.stopPropagation(); hangarIslem({ islem: 'favori', gemi: g.id, favori: !g.favori }); } }, icon('star')),
    ikon(g.tasarim || g.lootId, 54), h('span', null, esyaAdi(g.lootId)), g.aktif ? badge(T('Etkin'), 'ok') : null)));
  const gorunum = v.tasarimlar.length > 1 ? h('div', { class: 'row wrap', style: { gap: '6px' } }, h('span', { class: 'lbl' }, T('Görünüm')),
    v.tasarimlar.map(t => h('button', { class: 'hg-esya' + (t === v.gorunum ? ' on' : ''), type: 'button', title: esyaAdi(t), disabled: kilit && t !== v.gorunum,
      onclick: ev => t !== v.gorunum && hangarTasarim(t, ev.currentTarget) }, ikon(t, 44)))) : null;
  const araclar = h('div', { class: 'row wrap hg-arac' },
    gemi.aktif ? null : btn(T('Etkin gemi yap'), e => hangarEtkin(v.gemi, e.currentTarget), 'sm primary', null, { disabled: kilit }),
    gemi.aktif && HG.konfig !== v.aktif_konfig ? btn(T('Bu config\'i kullan'), () => hangarIslem({ islem: 'konfig', konfig: HG.konfig }, T('Config değişti.')), 'sm primary') : null,
    btn(T('Kaydet'), () => hangarIslem({ islem: 'kaydet', gemi: v.gemi }, T('İki config kaydedildi.')), 'sm', 'save', { title: T('İki config\'in donanımını bu gemi için saklar.') }),
    gemi.kayitli ? btn(T('Yükle'), () => hangarIslem({ islem: 'yukle', gemi: v.gemi }, T('Kayıtlı donanım takıldı.')), 'sm', 'download', { disabled: kilit }) : null,
    btn(T('Aktar…'), () => hangarAktar(v), 'sm', 'copy', { disabled: kilit, title: T('Bu geminin donanımını başka bir gemiye taşır.') }),
    btn(T('Temizle'), async () => await confirmBox(T('Config {0} boşaltılsın mı?', HG.konfig), T('Gemideki, dronlardaki ve P.E.T.\'teki eşyalar envantere iner.'),
      { ok: T('Temizle'), danger: true }) && hangarIslem({ islem: 'temizle', gemi: v.gemi, konfig: HG.konfig }), 'sm', 'trash', { disabled: kilit }));
  // seçili bölüm
  let bolum;
  if (HG.bolum === 'ship') bolum = h('div', { class: 'hg-yuvalar' }, v.yuvalar.map(y => yuvaKutusu(y, v.konfigler[HG.konfig][y], 'ship')));
  else if (HG.bolum === 'drone') bolum = dronlar.length ? h('div', { class: 'hg-dronlar' }, dronlar.map(d => h('div', { class: 'hg-dron' + (d.id === HG.dron ? ' on' : ''),
    onclick: () => { if (HG.dron !== d.id) { HG.dron = d.id; renderHangar(); } } },
    ikon(d.lootId, 40), h('div', { class: 'grow' }, h('b', null, esyaAdi(d.lootId)), d.id === HG.dron ? h('div', { class: 'lbl' }, T('envanterden takılacak dron')) : null),
    h('div', { class: 'hg-izgara' }, d.esyalar.map(e => cikar(e, 'drone', d.id)), bos(d.kapasite - d.esyalar.length),
      [d.tasarim, d.gorunum].map(e => e ? cikar(e, 'drone', d.id) : null)),
    btn(T('Sat'), async ev => { ev.stopPropagation(); if (await confirmBox(T('{0} satılsın mı?', esyaAdi(d.lootId)), T('Üstündeki eşyalar envantere iner.'), { ok: T('Sat'), danger: true }))
      hangarIslem({ islem: 'dron_sat', dron: d.id }, T('Dron satıldı.')); }, 'sm ghost', null, { disabled: kilit })))) : h('div', { class: 'empty' }, T('Dron yok.'));
  else if (HG.bolum === 'pet') {
    const pb = v.pet_bilgi, pc = v.pet[HG.konfig];
    const yuvaAc = y => pc[y].fiyat > 0 ? btn('+1 (' + paraYaz('uridium', pc[y].fiyat) + ')', async () => await confirmBox(T('{0} yuvası açılsın mı?', yuvaAdi(y)),
      T('{0} uridyum harcanır.', fmtN(pc[y].fiyat)), { ok: T('Aç') }) && hangarIslem({ islem: 'pet_yuva', yuva: y }, T('Yuva açıldı.')), 'sm ghost') : null;
    bolum = h('div', { class: 'stack' },
      h('div', { class: 'row wrap', style: { gap: '10px' } }, h('b', null, pb.ad || 'P.E.T.'), badge(T('Sv {0}', pb.seviye), 'info'),
        btn(T('Adını değiştir ({0})', paraYaz('uridium', pb.ad_fiyati)), async () => { const ad = await promptBox(T('P.E.T.\'in adı'), T('1-24 harf ya da rakam'), pb.ad || '');
          if (ad != null && ad !== pb.ad) hangarIslem({ islem: 'pet_ad', ad }, T('P.E.T.\'in adı değişti.')); }, 'sm ghost'),
        pc.heat.kapasite ? h('div', { class: 'seg' }, [['', T('Normal yuvalar')], ['heat', 'HEAT']].map(([k, t]) => h('button', { class: HG.kume === k ? 'on info' : '',
          onclick: () => { HG.kume = k; renderHangar(); } }, t))) : null),
      !pb.heat_acik && pc.heat.kapasite ? h('p', { class: 'desc', style: { margin: 0 } }, T('HEAT yuvaları P.E.T.\'in HEAT seviyesi yükselince etkinleşir.')) : null,
      h('div', { class: 'hg-yuvalar' }, v.pet_yuvalari.filter(y => y !== 'heat' || pc.heat.kapasite || pc.heat.fiyat).map(y => yuvaKutusu(y, pc[y], 'pet', yuvaAc(y)))));
  } else bolum = v.cpular.length ? h('div', { class: 'hg-cpular' }, v.cpular.map(c => h('div', { class: 'hg-cpu' }, ikon(c.lootId, 40),
    h('div', { class: 'grow' }, h('b', null, esyaAdi(c.lootId)), c.tur === 'cephane' ? h('div', { class: 'lbl' }, T('{0} altına inince {1} alır', fmtN(c.esik), fmtN(c.adet))) : null),
    c.tur === 'ackapa' ? btn(c.acik ? T('Açık') : T('Kapalı'), () => hangarIslem({ islem: 'cpu', lootId: c.lootId }), 'sm ' + (c.acik ? 'primary' : 'ghost'))
      : h('select', { class: 'input', onchange: e => hangarIslem({ islem: 'cpu_cephane', esya: c.id, cephane: e.target.value }, T('Otomatik alım cephanesi seçildi.')) },
        h('option', { value: '', disabled: true, selected: !c.secili }, T('Cephane seç')),
        c.secenekler.map(o => h('option', { value: o, selected: o === c.secili }, esyaAdi(o)))))))
    : h('div', { class: 'empty' }, T('Etkin config\'te ayarı olan CPU yok.'));
  const bolumler = [['ship', T('Gemi')], ['drone', T('Dronlar')]].concat(v.pet ? [['pet', 'P.E.T.']] : [], gemi.aktif ? [['cpu', 'CPU']] : []);
  if (!bolumler.find(([k]) => k === HG.bolum)) HG.bolum = 'ship';
  $('#content').replaceChildren(h('div', { class: 'stack' },
    oyunUstu(v, 'hangar', btn(null, () => renderHangar(), 'icon', 'refresh', { title: T('Yenile') })),
    h('div', { class: 'card' }, gemiler),
    h('div', { class: 'card hg-gemi-kart' },
      kilit ? h('div', { class: 'hg-uyari' }, icon('alert'), v.portal_hangar ? T('Donanım yalnız istasyonda ya da portalın güvenli bölgesinde (savaştan biraz sonra) değiştirilebilir.')
        : T('Donanım yalnız istasyonda (savaştan biraz sonra) değiştirilebilir.')) : null,
      h('div', { class: 'row between wrap', style: { gap: '10px' } },
        h('div', { class: 'row', style: { gap: '12px' } }, ikon(gemi.tasarim || gemi.lootId, 64), h('div', null, h('h2', { style: { margin: 0 } }, esyaAdi(gemi.lootId)),
          gemi.aktif ? h('span', { class: 'lbl' }, T('Etkin gemi')) : null)),
        h('div', { class: 'seg' }, Object.keys(v.konfigler).map(c => h('button', { class: c === HG.konfig ? 'on info' : '', onclick: () => { HG.konfig = c; renderHangar(); } },
          T('Config {0}', c), gemi.aktif && c === v.aktif_konfig ? ' •' : '')))),
      araclar, gorunum,
      h('div', { class: 'seg' }, bolumler.map(([k, t]) => h('button', { class: k === HG.bolum ? 'on info' : '', onclick: () => { HG.bolum = k; renderHangar(); } }, t))),
      bolum),
    hangarEnvanter(v, kilit, ikon, svRozet)));
}

// envanter kartı: takma kipinde seçili bölüme takılabilenler, satış kipinde satılabilenler (aynı eşyalar tek kutuda, sayısıyla)
function hangarEnvanter(v, kilit, ikon, svRozet) {
  const sat = HG.kip === 'sat' && HG.bolum !== 'cpu';
  // items equipped in another config of this ship can be equipped here too (as in game); they are never sold
  const baska = e => e.konfigler && e.konfigler.length > 0;
  const uygun = v.envanter.filter(e => sat ? e.satis && !baska(e)
    : HG.bolum !== 'cpu' && e.hedefler.includes(HG.bolum) && !(e.konfigler || []).includes(String(HG.konfig)));
  const turler = [...new Set(uygun.map(e => e.yuva))], anahtar = sat ? 'sat' : HG.bolum;
  if (!turler.includes(HG.yuva[anahtar])) HG.yuva[anahtar] = turler[0];
  const grup = {};
  for (const e of uygun.filter(e => e.yuva === HG.yuva[anahtar])) (grup[e.lootId] = grup[e.lootId] || []).push(e);
  for (const es of Object.values(grup)) es.sort((a, b) => baska(b) - baska(a));      // items of the other config first: free copies stay free
  for (const id of Object.keys(HG.secili)) if (!v.envanter.find(e => String(e.id) === id && e.satis && !baska(e))) delete HG.secili[id];
  const secilen = v.envanter.filter(e => HG.secili[e.id]), toplam = {};
  for (const e of secilen) toplam[e.satis[0]] = (toplam[e.satis[0]] || 0) + e.satis[1];
  const kutular = Object.entries(grup).sort((a, b) => esyaAdi(a[0]).localeCompare(esyaAdi(b[0]))).map(([lid, es]) => {
    const n = es.filter(e => HG.secili[e.id]).length;
    const b = h('button', { class: 'hg-esya' + (n ? ' on' : ''), type: 'button', disabled: !sat && kilit,
      title: esyaAdi(lid) + (sat ? ' — ' + T('satış değeri {0}', paraYaz(es[0].satis[0], es[0].satis[1])) + ' · ' + T('seçmek için tıkla, sağ tıkla bırak') : ' — ' + T('takmak için tıkla')),
      onclick: ev => { if (!sat) return hangarTasi({ esya: es[0].id, yon: 'tak', hedef: HG.bolum, dron: HG.dron, kume: HG.bolum === 'pet' ? HG.kume : '' }, ev.currentTarget);
        const e = es.find(x => !HG.secili[x.id]); if (e) { HG.secili[e.id] = true; renderHangar(); } },
      oncontextmenu: ev => { if (!sat) return; ev.preventDefault(); const e = es.find(x => HG.secili[x.id]); if (e) { delete HG.secili[e.id]; renderHangar(); } } },
      ikon(lid, 44), svRozet(es[0]), es.length > 1 ? h('span', { class: 'hg-adet' }, (n ? n + '/' : '') + fmtN(es.length)) : n ? h('span', { class: 'hg-adet' }, '✓') : null);
    b._esya = es[0].seviye ? { yukseltme: es[0].seviye } : null;        // eşya ipucu: yükseltme seviyesi
    return b;
  });
  return h('div', { class: 'card' },
    h('div', { class: 'row between wrap', style: { gap: '10px' } },
      h('div', { class: 'row', style: { gap: '10px' } }, h('h2', { style: { margin: 0 } }, T('Envanter')),
        HG.bolum !== 'cpu' ? h('div', { class: 'seg' }, [['tak', T('Tak')], ['sat', T('Sat')]].map(([k, t]) => h('button', { class: HG.kip === k ? 'on info' : '',
          onclick: () => { HG.kip = k; renderHangar(); } }, t))) : null),
      h('div', { class: 'seg', style: { flexWrap: 'wrap' } }, turler.map(y => h('button', { class: y === HG.yuva[anahtar] ? 'on info' : '', onclick: () => { HG.yuva[anahtar] = y; renderHangar(); } }, yuvaAdi(y))))),
    h('div', { class: 'hg-izgara', style: { marginTop: '12px' } }, kutular.length ? kutular : h('div', { class: 'empty' }, sat ? T('Satılabilecek eşya yok.') : T('Takılabilecek eşya yok.'))),
    sat && secilen.length ? h('div', { class: 'hg-satis' }, h('span', null, T('{0} eşya seçili', secilen.length), ' · ', h('b', null, Object.entries(toplam).map(([c, n]) => paraYaz(c, n)).join(' + '))),
      h('div', { class: 'row', style: { gap: '6px' } }, btn(T('Seçimi temizle'), () => { HG.secili = {}; renderHangar(); }, 'sm ghost'),
        btn(T('Seçilenleri sat'), async () => await confirmBox(T('{0} eşya satılsın mı?', secilen.length), T('Karşılığında {0} alırsın. Bu geri alınamaz.',
          Object.entries(toplam).map(([c, n]) => paraYaz(c, n)).join(' + ')), { ok: T('Sat'), danger: true })
          && hangarIslem({ islem: 'sat', esyalar: secilen.map(e => e.id) }, T('Satıldı.'), () => { HG.secili = {}; }), 'sm primary'))) : null);
}

async function hangarTasi(istek, b) {
  b.disabled = true;
  const r = await act(() => api('/api/oyun/hangar/tasi', Object.assign({ gemi: HG.gemi, konfig: HG.konfig }, istek)));
  if (r && !r.tamam) toast(r.hata === 'istasyon' ? T('Donanım yalnız güvenli bölgede değiştirilebilir.') : oyunMetni(r.hata), 'err');
  renderHangar();
}

// hangarın öteki işlemleri (panel_kanali.ISLEMLER): başarıda bilgi metni, sonra yenile
async function hangarIslem(istek, okMetin, sonra) {
  const r = await act(() => api('/api/oyun/hangar/islem', Object.assign({ gemi: HG.gemi }, istek)));
  if (r && !r.tamam) toast(r.hata === 'istasyon' ? T('Donanım yalnız güvenli bölgede değiştirilebilir.') : oyunMetni(r.hata), 'err');
  else if (r) { if (okMetin) toast(okMetin, 'ok'); if (sonra) sonra(); }
  renderHangar();
}

// Transfer System: bu geminin donanımı başka bir gemiye (hedefin yuvaları yetmeli)
function hangarAktar(v) {
  let hedef = null;
  const liste = h('div', { class: 'hg-gemiler', style: { flexWrap: 'wrap' } }, v.gemiler.filter(g => g.id !== v.gemi).map(g => h('div', { class: 'hg-gemi', onclick: ev => {
    hedef = g.id; liste.querySelectorAll('.hg-gemi').forEach(x => x.classList.toggle('on', x === ev.currentTarget)); } },
    oyunIkon(g.tasarim || g.lootId, 54, v.firma), h('span', null, esyaAdi(g.lootId)))));
  const m = modal({ title: T('Donanımı aktar'), sub: T('{0} gemisinin iki config\'i, dronları ve P.E.T. donanımı seçtiğin gemiye taşınır.', esyaAdi(v.gemiler.find(g => g.id === v.gemi).lootId)),
    body: [liste], wide: true, foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Aktar'), () => { if (!hedef) return toast(T('Bir gemi seç.'), 'err');
      m.close(); hangarIslem({ islem: 'aktar', gemi: v.gemi, hedef_gemi: hedef }, T('Donanım aktarıldı.')); }, 'primary')] });
}

async function hangarEtkin(gemi, b) {
  b.disabled = true;
  const r = await act(() => api('/api/oyun/hangar/etkin', { gemi }));
  if (r && !r.tamam) toast(oyunMetni(r.hata), 'err');
  else if (r) toast(T('Etkin gemi değişti.'), 'ok');
  renderHangar();
}

async function hangarTasarim(lootId, b) {
  b.disabled = true;
  const r = await act(() => api('/api/oyun/hangar/tasarim', { gemi: HG.gemi, lootId }));
  if (r && !r.tamam) toast(r.hata === 'istasyon' ? T('Donanım yalnız güvenli bölgede değiştirilebilir.') : oyunMetni(r.hata), 'err');
  renderHangar();
}

// ================================================================== OYUN İÇİ: SKYLAB
// Modüller, depo, enerji, robotlar ve taşıma (panel_kanali.py /skylab): işlemler istemcinin SkylabActionRequest ve
// SkylabPurchaseRobotRequest'i (kurallar, bedeller ve süreler oyundakiyle aynı). Modül görseli yok: üretilen cevherin görseli.
const SK_CEVHER = { PROMETIUM_COLLECTOR: 'prometium', ENDURIUM_COLLECTOR: 'endurium', TERBIUM_COLLECTOR: 'terbium', PROMETID_REFINERY: 'prometid',
  DURANIUM_REFINERY: 'duranium', PROMERIUM_REFINERY: 'promerium', SEPROM_REFINERY: 'seprom', XENO_MODULE: 'xenomit' };
const SK_MODUL = { BASE_MODULE: N('Ana modül'), SOLAR_MODULE: N('Güneş modülü'), STORAGE_MODULE: N('Depo modülü'), TRANSPORT_MODULE: N('Taşıma modülü'),
  XENO_MODULE: N('Xeno modülü') };
const cevherAdi = ad => esyaAdi('resource_ore_' + ad.toLowerCase());
const skModulAdi = k => SK_MODUL[k] ? T(SK_MODUL[k]) : k.endsWith('_COLLECTOR') ? T('{0} toplayıcısı', cevherAdi(SK_CEVHER[k]))
  : T('{0} rafinerisi', cevherAdi(SK_CEVHER[k]));
const SK_METIN = {
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
const skMetni = k => SK_METIN[k] ? T(SK_METIN[k]) : oyunMetni(k);
const SK = { gonder: {} };

async function renderSkylab() {
  await ogYukle();
  let v;
  try { v = await api('/api/oyun/skylab'); } catch (e) { return oyunHatasi(e, 'skylab'); }
  const cevherIkon = (ad, boy) => OG.dizin?.sprite[ad + '_100x100'] ? sprite(ad + '_100x100', boy) : h('span', { class: 'sprite bos', style: { width: boy + 'px', height: boy + 'px' } }, icon('lab'));
  const depo = v.depo.map(o => h('div', { class: 'sk-cevher' }, cevherIkon(o.ad.toLowerCase(), 44),
    h('div', { class: 'grow' }, h('div', { class: 'row between' }, h('b', null, cevherAdi(o.ad)), h('span', { class: 'mono' }, fmtN(o.miktar) + ' / ' + fmtN(o.kapasite))),
      h('div', { class: 'sk-bar' }, h('span', { style: { width: Math.min(100, 100 * o.miktar / Math.max(1, o.kapasite)) + '%' } })))));
  const moduller = v.moduller.map(m => {
    const kur = m.seviye === 0, durum = m.kalan != null ? badge(T('Yükseltiliyor: {0}', fmtDur(m.kalan)), 'info')
      : kur ? badge(T('Kurulmadı')) : m.durum === 'ACTIVE' ? badge(T('Çalışıyor'), 'ok') : badge(T('Kapalı'), 'warn');
    const c = m.maliyet, dugmeler = [];
    if (m.kalan != null) {
      dugmeler.push(btn(T('Bitir ({0} U.)', fmtN(m.bitirme)), () => skylabIslem(m.id, 'instantFinishUpgrade'), 'sm primary'),
        btn(T('İptal'), async () => await confirmBox(T('Yükseltme iptal edilsin mi?'), T('Harcananlar geri gelmez.'), { ok: T('İptal et'), danger: true })
          && skylabIslem(m.id, 'abortUpgrade'), 'sm'));
    } else if (c) {
      dugmeler.push(btn(kur ? T('Kur') : T('Yükselt'), () => skylabIslem(m.id, 'upgrade'), 'sm primary'));
      if (c.uridyum) dugmeler.push(btn(T('Anında ({0} U.)', fmtN(c.uridyum)), () => skylabIslem(m.id, 'instantUpgrade'), 'sm'));
    }
    if (m.acilir && !kur && m.kalan == null) dugmeler.push(btn(m.durum === 'ACTIVE' ? T('Kapat') : T('Aç'),
      () => skylabIslem(m.id, m.durum === 'ACTIVE' ? 'setInactive' : 'setActive'), 'sm ghost'));
    return h('div', { class: 'sk-modul' + (m.durum === 'ACTIVE' ? ' on' : '') },
      h('div', { class: 'row', style: { gap: '10px' } }, SK_CEVHER[m.id] ? cevherIkon(SK_CEVHER[m.id], 48) : h('span', { class: 'sprite bos', style: { width: '48px', height: '48px' } }, icon('lab')),
        h('div', { class: 'grow' }, h('b', null, skModulAdi(m.id)), h('div', { class: 'mono' }, T('Sv {0} / {1}', m.seviye, m.azami)))),
      h('div', { class: 'row wrap', style: { gap: '6px' } }, durum,
        m.uretim ? badge(T('{0} / sa', fmtN(m.uretim)), '') : null, m.enerji ? badge(T('{0} enerji', fmtN(m.enerji)), 'orange') : null,
        m.verim ? badge(T('verim %{0}', m.verim), '') : null),
      c && m.kalan == null ? h('div', { class: 'sk-bedel' }, T('{0} C., her birinden {1} Prometium / Endurium / Terbium, {2}', fmtN(c.kredi), fmtN(c.kaynak), fmtDur(c.sure_sn))) : null,
      h('div', { class: 'row wrap', style: { gap: '6px' } }, dugmeler),
      m.robot && !kur ? h('div', { class: 'sk-robot' }, h('span', { class: 'lbl' }, T('Robotlar: {0} / {1}', m.robot.etkin, m.robot.azami) + (m.robot.depoda ? ' · ' + T('depoda {0}', m.robot.depoda) : '')),
        h('div', { class: 'row', style: { gap: '6px' } }, ['1', '2'].map(t => btn('+' + (t === '1' ? '1%' : '4%') + ' · ' + paraYaz(m.robot.fiyat[t][0], m.robot.fiyat[t][1]),
          () => skylabRobot(m.id, t), 'sm ghost', null, { title: T('48 saat çalışan robot') })))) : null);
  });
  const t = v.tasima, gonder = v.depo.map(o => h('label', { class: 'sk-gonder' }, cevherIkon(o.ad.toLowerCase(), 28),
    h('input', { class: 'input num', type: 'number', min: 0, max: o.miktar, value: SK.gonder[o.id] || 0, oninput: e => { SK.gonder[o.id] = +e.target.value | 0; } })));
  const tasima = t ? h('div', { class: 'stack' }, h('p', { class: 'desc', style: { margin: 0 } }, T('Taşıma sürüyor: {0} kaldı.', fmtDur(t.kalan))),
    h('div', null, btn(T('Hemen bitir ({0} U.)', fmtN(v.hizli_fiyat)), () => skylabIslem('TRANSPORT_MODULE', 'startTransport', 'instantFinish'), 'sm primary')))
    : h('div', { class: 'stack' }, h('div', { class: 'row wrap', style: { gap: '10px' } }, gonder),
      h('div', { class: 'row wrap', style: { gap: '8px' } }, btn(T('Gönder'), () => skylabIslem('TRANSPORT_MODULE', 'startTransport', ''), 'sm primary'),
        btn(T('Hızlı gönder ({0} U.)', fmtN(v.hizli_fiyat)), () => skylabIslem('TRANSPORT_MODULE', 'startTransport', 'fast'), 'sm')));
  $('#content').replaceChildren(h('div', { class: 'stack' },
    oyunUstu(v, 'skylab', h('span', { class: 'pill' + (v.enerji.kullanilan > v.enerji.gunes ? ' err' : '') }, T('Enerji'), ' ', h('b', null, fmtN(v.enerji.kullanilan) + ' / ' + fmtN(v.enerji.gunes))),
      btn(null, () => renderSkylab(), 'icon', 'refresh', { title: T('Yenile') })),
    h('div', { class: 'card' }, h('h2', null, T('Depo')), h('div', { class: 'sk-depo' }, depo)),
    h('div', { class: 'sk-moduller' }, moduller),
    h('div', { class: 'card' }, h('h2', null, T('Gemiye taşıma')), tasima)));
}

async function skylabIslem(modul, islem, mod) {
  const miktarlar = islem === 'startTransport' && mod !== 'instantFinish' ? SK.gonder : {};
  const r = await act(() => api('/api/oyun/skylab/islem', { modul, islem, mod: mod || '', miktarlar }));
  if (r) {
    if (r.hatalar.length) toast(skMetni(r.hatalar[0]), 'err');
    else if (r.basarilar.length) toast(skMetni(r.basarilar[r.basarilar.length - 1]), 'ok');
    if (r.tamam && islem === 'startTransport') SK.gonder = {};
  }
  renderSkylab();
}

async function skylabRobot(modul, tip) {
  const r = await act(() => api('/api/oyun/skylab/robot', { modul, tip }));
  if (r && !r.tamam) toast(skMetni(r.hatalar[0]), 'err');
  else if (r) toast(T('Robot alındı.'), 'ok');
  renderSkylab();
}

// ================================================================== OYUN İÇİ: AÇIK ARTIRMA
// Lotlar, teklifler ve anında alım istemcinin Auction* istekleriyle (panel_kanali.py /muzayede). Otomatik teklif ve alarm kuralları
// oyun sunucusunda (muzayede.oto): panel kapalıyken de işler, alarm oyunda ekran mesajı olur. Olaylar (geçildin, kazandın, otomatik
// teklif…) panelin her sayfasında bildirim olarak çıkar (muzayedeOlayTick; masaüstü bildirimi izin verilirse).
const MZ_TUR = { hour: N('Saatlik'), day: N('Günlük'), week: N('Haftalık') };
const MZ_GRUP = { ship: N('Gemiler'), shipdesign: N('Gemi tasarımları'), extra: N('Ekstralar'), module: N('Modüller'), booster: N('Boosterlar'),
  battery: N('Lazer cephanesi'), rocket: N('Roketler'), generator: N('Jeneratörler'), weapon: N('Silahlar'), special: N('Özel') };
const MZ_DURUM = [['hepsi', N('Hepsi')], ['teklif', N('Teklif verdiklerim')], ['onde', N('Öndeyim')], ['degil', N('Önde değilim')], ['oto', N('Otomatik')], ['alarm', N('Alarmlı')]];
Object.assign(OY_METIN, { auction_bid_minBid_not_reached: N('Teklif, en yüksek tekliften en az 10.000 kredi fazla olmalı.'), auction_bid_credits_to_little: N('Yeterli kredin yok.'),
  auction_buy_instant_invalid: N('Bu lot anında alınamaz.'), items_shop_error_ship_contains_ship: N('Bu gemi zaten sende.'), auction_error_generic: N('Açık artırma işlemi yapılamadı.') });
const MZ = { tur: 'hepsi', grup: 'hepsi', durum: 'hepsi', ara: '', bitis: {}, son: null };
const mzKey = l => l.tur + '|' + l.loot;
function mzOlayMetni(o) {
  const ad = esyaAdi(o.loot);
  return { gecildi: () => T('Teklifin geçildi: {0}', ad), bitiyor: () => T('{0} için {1} dk kaldı.', ad, o.dk), kazanildi: () => T('Kazandın: {0} ({1})', ad, paraYaz('credits', o.fiyat)),
    kaybedildi: () => T('Kaybettin: {0}', ad), oto_teklif: () => T('Otomatik teklif: {0}, {1}', ad, paraYaz('credits', o.fiyat)),
    oto_sinir: () => T('Otomatik teklif sınırına ulaşıldı: {0} ({1} gerekiyor)', ad, paraYaz('credits', o.gereken)) }[o.tip]?.() || o.tip;
}
const mzOlayTuru = t => ({ kazanildi: 'ok', oto_teklif: 'info', gecildi: 'err', oto_sinir: 'err', kaybedildi: 'err', bitiyor: 'info' }[t] || 'info');

async function renderMuzayede() {
  await ogYukle();
  let v;
  try { v = await api('/api/oyun/muzayede'); } catch (e) { return oyunHatasi(e, 'muzayede'); }
  const simdi = Date.now() / 1000;
  for (const [k, n] of Object.entries(v.kalan)) MZ.bitis[k] = simdi + n;
  if (v.olaylar.length) MZ.son = Math.max(MZ.son || 0, v.olaylar[0].no);
  const gruplar = [...new Set(v.lotlar.map(l => l.grup))];
  const sec = l => (MZ.tur === 'hepsi' || l.tur === MZ.tur) && (MZ.grup === 'hepsi' || l.grup === MZ.grup)
    && (!MZ.ara || esyaAdi(l.loot).toLowerCase().includes(MZ.ara.toLowerCase()))
    && ({ hepsi: true, teklif: l.benim > 0, onde: l.onde, degil: !l.onde, oto: !!l.oto, alarm: !!l.alarm })[MZ.durum];
  const gorunen = v.lotlar.filter(sec).sort((a, b) => (b.onde - a.onde) || (!!b.oto - !!a.oto) || ['hour', 'day', 'week'].indexOf(a.tur) - ['hour', 'day', 'week'].indexOf(b.tur)
    || esyaAdi(a.loot).localeCompare(esyaAdi(b.loot)));
  const katilinacak = gorunen.filter(l => !l.onde), toplam = katilinacak.reduce((t, l) => t + l.sonraki, 0);
  const sayac = k => h('span', { class: 'pill mz-sayac', 'data-tur': k }, h('span', { class: 'lbl' }, T(MZ_TUR[k])), h('b', null, fmtDur(MZ.bitis[k] - simdi)));
  const ara = h('input', { class: 'input oy-ara', placeholder: T('Ara…'), value: MZ.ara, oninput: e => { MZ.ara = e.target.value; clearTimeout(MZ.araT); MZ.araT = setTimeout(renderMuzayede, 250); } });
  const seg = (liste, deger, ata) => h('div', { class: 'seg', style: { flexWrap: 'wrap' } }, liste.map(([k, t]) => h('button', { class: k === deger ? 'on info' : '', onclick: () => { ata(k); renderMuzayede(); } }, t)));
  $('#content').replaceChildren(h('div', { class: 'stack' },
    oyunUstu(v, 'muzayede', ara, btn(null, () => renderMuzayede(), 'icon', 'refresh', { title: T('Yenile') })),
    h('div', { class: 'card mz-ust' },
      h('div', { class: 'row between wrap', style: { gap: '10px' } },
        h('div', { class: 'row wrap', style: { gap: '8px' } }, ['hour', 'day', 'week'].map(sayac)),
        h('div', { class: 'row wrap', style: { gap: '6px' } },
          btn(T('Hepsine katıl ({0} lot)', katilinacak.length), async () => katilinacak.length && await confirmBox(T('{0} lota teklif verilsin mi?', katilinacak.length),
            T('Her lota en düşük geçerli teklif verilir (toplam {0}). Teklifi geçilen lotun kredisi hemen geri gelir.', paraYaz('credits', toplam)), { ok: T('Katıl') })
            && muzayedeHepsi(katilinacak), 'sm primary', 'gavel', { disabled: !katilinacak.length }),
          btn(T('Görünenlere otomatik teklif…'), () => muzayedeTopluOto(gorunen, v), 'sm', null, { disabled: !gorunen.length }),
          gorunen.some(l => l.oto) ? btn(T('Otomatikleri kapat'), () => muzayedeTopluKapat(gorunen.filter(l => l.oto)), 'sm ghost') : null)),
      h('div', { class: 'row wrap', style: { gap: '8px', marginTop: '12px' } },
        seg([['hepsi', T('Hepsi')]].concat(['hour', 'day', 'week'].map(k => [k, T(MZ_TUR[k])])), MZ.tur, k => { MZ.tur = k; }),
        seg(MZ_DURUM.map(([k, t]) => [k, T(t)]), MZ.durum, k => { MZ.durum = k; })),
      h('div', { style: { marginTop: '8px' } }, seg([['hepsi', T('Bütün gruplar')]].concat(gruplar.map(g => [g, MZ_GRUP[g] ? T(MZ_GRUP[g]) : g])), MZ.grup, k => { MZ.grup = k; })),
      !v.rakip ? h('p', { class: 'desc', style: { margin: '10px 0 0' } }, T('Sanal rakipler kapalı: teklif veren tek kişi sensin. Oyun Ayarları > Müzayede\'den açılabilir.')) : null),
    h('div', { class: 'mz-izgara' }, gorunen.length ? gorunen.map(l => muzayedeKart(l, v)) : h('div', { class: 'empty' }, T('Lot yok.'))),
    h('div', { class: 'mz-alt' },
      h('div', { class: 'card' }, h('h2', null, icon('bell'), T('Olaylar')), v.olaylar.length ? h('div', { class: 'mz-liste' }, v.olaylar.map(o => h('div', { class: 'mz-olay ' + mzOlayTuru(o.tip) },
        dot(mzOlayTuru(o.tip) === 'ok' ? 'ok' : mzOlayTuru(o.tip) === 'err' ? 'warn' : ''), h('span', { class: 'grow' }, mzOlayMetni(o)),
        h('span', { class: 'mono muted' }, new Date(o.zaman * 1000).toLocaleTimeString(LOC(), { hour: '2-digit', minute: '2-digit' })))))
        : h('div', { class: 'empty' }, T('Henüz olay yok.'))),
      h('div', { class: 'card' }, h('h2', null, icon('clock'), T('Geçmiş')), v.gecmis.length ? h('div', { class: 'mz-liste' }, v.gecmis.map(g => h('div', { class: 'mz-olay' },
        oyunIkon(g.loot, 26, v.firma, 'gavel'), h('span', { class: 'grow' }, esyaAdi(g.loot), h('span', { class: 'muted' }, ' · ' + T(MZ_TUR[g.tur] || g.tur))),
        h('span', { class: g.kim === v.kimlik ? 'mz-ben' : 'muted' }, g.ad || '—'), h('span', { class: 'mono' }, paraYaz('credits', g.teklif)))))
        : h('div', { class: 'empty' }, T('Geçmiş yok.'))))));
  S.timers.push(setInterval(() => {            // dönem sayaçları; dönem bitince liste yenilenir (kazanılan eşya, yeni dönem)
    const t = Date.now() / 1000;
    document.querySelectorAll('.mz-sayac').forEach(el => { el.querySelector('b').textContent = fmtDur(MZ.bitis[el.dataset.tur] - t); });
    if (Object.values(MZ.bitis).some(b => b - t < -2) && !MZ.yenileniyor) { MZ.yenileniyor = true; setTimeout(() => { MZ.yenileniyor = false; if (S.page === 'muzayede') renderMuzayede(); }, 3000); }
  }, 1000));
}

function muzayedeKart(l, v) {
  const inp = h('input', { class: 'input num', type: 'number', min: l.sonraki, step: v.artis, value: l.sonraki });
  const durum = l.onde ? badge(T('Öndesin'), 'ok') : l.en_yuksek ? badge(T('En yüksek: {0}', l.en_yuksek_ad || '—'), 'warn') : badge(T('Teklif yok'));
  return h('div', { class: 'mz-kart' + (l.onde ? ' onde' : '') },
    h('div', { class: 'row', style: { gap: '10px', alignItems: 'flex-start' } }, oyunIkon(l.loot, 64, v.firma, 'gavel'),
      h('div', { class: 'grow' }, h('div', { class: 'mg-ad', style: { minHeight: 0 } }, esyaAdi(l.loot)),
        h('div', { class: 'row wrap', style: { gap: '4px', marginTop: '4px' } }, badge(T(MZ_TUR[l.tur])), l.adet > 1 ? badge('× ' + fmtN(l.adet)) : null,
          l.oto ? badge(T('Oto ≤ {0}', fmtN(l.oto.azami)), 'info') : null)),
      // alarm düğmesi başlıkta (alt satırda yer kalmayınca tek başına alta düşüyordu); kuruluysa turuncu
      btn(null, () => muzayedeAlarmPencere(l), 'sm icon ' + (l.alarm ? 'orange' : 'ghost'), 'bell', { title: l.alarm ? T('Alarm kurulu') : T('Alarm') })),
    h('div', { class: 'mz-satir' }, h('span', { class: 'muted' }, T('En yüksek')), h('b', null, l.en_yuksek ? paraYaz('credits', l.en_yuksek) : '—')),
    h('div', { class: 'mz-satir' }, h('span', { class: 'muted' }, T('Senin teklifin')), h('b', { class: l.onde ? 'mz-ben' : '' }, l.benim ? paraYaz('credits', l.benim) : '—')),
    h('div', { class: 'row', style: { gap: '6px' } }, durum),
    h('div', { class: 'row', style: { gap: '6px' } }, inp, btn(T('Teklif ver'), e => muzayedeTeklif(l, +inp.value | 0, e.currentTarget), 'sm primary'),
      btn('+' + fmtN(v.artis), () => { inp.value = (+inp.value | 0) + v.artis; }, 'sm ghost', null, { title: T('Teklifi artır') })),
    h('div', { class: 'row wrap', style: { gap: '6px' } },
      l.anlik ? btn(T('Anında al ({0})', paraYaz('uridium', l.fiyat)), async e => await confirmBox(T('{0} anında alınsın mı?', esyaAdi(l.loot)), T('{0} uridyum harcanır.', fmtN(l.fiyat)), { ok: T('Al') })
        && muzayedeAnlik(l), 'sm ghost') : null,
      btn(l.oto ? T('Otomatik: açık') : T('Otomatik teklif'), () => muzayedeOtoPencere(l, v), 'sm ' + (l.oto ? 'primary' : 'ghost'))));
}

async function muzayedeTeklif(l, fiyat, b) {
  b.disabled = true;
  const r = await act(() => api('/api/oyun/muzayede/teklif', { tur: l.tur, loot: l.loot, fiyat }));
  if (r && !r.tamam) toast(oyunMetni(r.hata), 'err');
  else if (r) toast(T('Teklif verildi: {0}, {1}', esyaAdi(l.loot), paraYaz('credits', fiyat)), 'ok');
  renderMuzayede();
}

async function muzayedeHepsi(lotlar) {
  const r = await act(() => api('/api/oyun/muzayede/hepsi', { lotlar: lotlar.map(l => [l.tur, l.loot]) }));
  if (r) {
    if (r.verilen) toast(T('{0} lota teklif verildi: toplam {1}', r.verilen, paraYaz('credits', r.tutar)), 'ok');
    for (const [k, n] of Object.entries(r.hatalar)) toast(oyunMetni(k) + ' (' + n + ')', 'err');
  }
  renderMuzayede();
}

async function muzayedeAnlik(l) {
  const r = await act(() => api('/api/oyun/muzayede/anlik', { tur: l.tur, loot: l.loot }));
  if (r && !r.tamam) toast(oyunMetni(r.hata), 'err');
  else if (r) toast(T('Satın alındı: {0}', esyaAdi(l.loot)), 'ok');
  renderMuzayede();
}

// otomatik teklif: azami tutara kadar, geçildikçe en düşük geçerli teklifi verir (oyun sunucusunda; panel kapalıyken de)
function muzayedeOtoPencere(l, v) {
  const inp = h('input', { class: 'input', type: 'number', min: v.en_az, step: v.artis, value: l.oto?.azami || Math.max(l.sonraki * 2, v.en_az * 5) });
  const m = modal({ title: T('Otomatik teklif: {0}', esyaAdi(l.loot)), sub: T('Geçildikçe en düşük geçerli teklif verilir; en çok bu tutara kadar. Panel kapalıyken de oyunda işler.'),
    body: [field(T('En çok (kredi)'), inp)], foot: [l.oto ? btn(T('Kapat'), () => { m.close(); muzayedeKural('oto', l, { azami: 0 }, T('Otomatik teklif kapandı.')); }, 'ghost') : null,
      btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Kaydet'), () => { m.close(); muzayedeKural('oto', l, { azami: +inp.value | 0 }, T('Otomatik teklif açık.')); }, 'primary')] });
}

function muzayedeAlarmPencere(l) {
  const a = l.alarm || {};
  const gec = h('input', { type: 'checkbox', checked: a.gecilince ?? true });
  const dk = h('select', { class: 'input' }, [[0, T('Kapalı')], [5, T('{0} dk', 5)], [15, T('{0} dk', 15)], [30, T('{0} dk', 30)], [60, T('{0} sa', 1)], [180, T('{0} sa', 3)]]
    .map(([n, t]) => h('option', { value: n, selected: (a.dk || 0) === n }, t)));
  const m = modal({ title: T('Alarm: {0}', esyaAdi(l.loot)), sub: T('Alarm oyunda ekran mesajı, panelde bildirim olur.'),
    body: [h('label', { class: 'row', style: { gap: '8px' } }, gec, T('Teklifim geçilince uyar')), field(T('Dönem bitmeden önce uyar'), dk)],
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Kaydet'), () => { m.close(); mzBildirimIzni();
      muzayedeKural('alarm', l, { gecilince: gec.checked, dk: +dk.value }, gec.checked || +dk.value ? T('Alarm kuruldu.') : T('Alarm kaldırıldı.')); }, 'primary')] });
}

async function muzayedeKural(tur, l, alanlar, okMetin) {
  const r = await act(() => api('/api/oyun/muzayede/' + tur, Object.assign({ tur: l.tur, loot: l.loot }, alanlar)));
  if (r) toast(okMetin, 'ok');
  renderMuzayede();
}

function muzayedeTopluOto(lotlar, v) {
  const inp = h('input', { class: 'input', type: 'number', min: v.en_az, step: v.artis, value: v.en_az * 10 });
  const m = modal({ title: T('{0} lota otomatik teklif', lotlar.length), sub: T('Her lot için aynı en çok tutar. Kredin yettiği sürece geçildikçe teklif verilir.'),
    body: [field(T('Lot başına en çok (kredi)'), inp)], foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Kaydet'), async () => {
      m.close(); for (const l of lotlar) await api('/api/oyun/muzayede/oto', { tur: l.tur, loot: l.loot, azami: +inp.value | 0 }).catch(() => null);
      toast(T('{0} lota otomatik teklif açıldı.', lotlar.length), 'ok'); renderMuzayede(); }, 'primary')] });
}

async function muzayedeTopluKapat(lotlar) {
  for (const l of lotlar) await api('/api/oyun/muzayede/oto', { tur: l.tur, loot: l.loot, azami: 0 }).catch(() => null);
  toast(T('Otomatik teklifler kapandı.'), 'ok');
  renderMuzayede();
}

function mzBildirimIzni() {
  try { if (window.Notification && Notification.permission === 'default') Notification.requestPermission(); } catch (e) { /* desteklenmiyor */ }
}

// yeni açık artırma olayları: her sayfada bildirim (ilk yoklama yalnız başlangıcı belirler); masaüstü bildirimi izin varsa
async function muzayedeOlayTick() {
  if (srvState(S.durum).oyun !== 'acik' || muzayedeOlayTick.busy) return;
  muzayedeOlayTick.busy = true;
  try {
    const r = await api('/api/oyun/muzayede/olaylar?son=' + (MZ.son || 0));
    const yeni = r.olaylar.filter(o => o.no > (MZ.son || 0)).reverse();
    if (MZ.son !== null) for (const o of yeni) {
      toast(T('Açık artırma') + ': ' + mzOlayMetni(o), mzOlayTuru(o.tip), 7000);
      try { if (window.Notification && Notification.permission === 'granted' && document.visibilityState !== 'visible') new Notification('OpenOrbit', { body: mzOlayMetni(o) }); } catch (e) { /* yok */ }
    }
    if (yeni.length || MZ.son === null) MZ.son = Math.max(MZ.son || 0, ...r.olaylar.map(o => o.no), 0);
    if (yeni.length && S.page === 'muzayede') renderMuzayede();
  } catch (e) { /* oyuna girilmedi */ } finally { muzayedeOlayTick.busy = false; }
}

const RENDER = { oyna: renderOyna, arkadas: renderArkadas, kayitlar: () => renderKayitlar(), ayarlar: renderAyarlar, etkinlikler: () => renderEtkinlikler(), istemci: () => renderIstemci(),
  takvim: enterTakvim, sunucu: renderSunucu, panel: renderPanel, dunya: () => renderDunya(), botlar: () => renderBotlar(), magaza: renderMagaza, hangar: renderHangar, skylab: renderSkylab, muzayede: renderMuzayede };

// ------------------------------------------------------------------ başlangıç
async function boot() {
  let cfg = null;
  try { cfg = await api('/api/panel_ayarlari'); } catch (e) { /* panel kapalı: poll bildirir */ }
  S.panelCfg = cfg;
  try { I18N.list = (await api('/api/diller')).diller; } catch (e) { /* eski liste: Türkçe, İngilizce */ }
  await setLang((cfg && cfg.dil) || guessLang());
  applyStatic();
  buildNav();
  ogYukle();                                       // oyunun görselleri: oyun içi menülerin simgeleri
  go(location.hash.slice(1) || 'oyna', false);
  poll();
  if (cfg && (!cfg.dil || !cfg.kurulum_tamam)) openWizard(cfg.dil ? 1 : 0);
}
document.addEventListener('DOMContentLoaded', boot);      // sonraki betikler (dunya.js) yüklendikten sonra
