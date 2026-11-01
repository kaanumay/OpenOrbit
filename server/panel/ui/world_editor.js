/* OpenOrbit paneli — Dünya Editörü (worlds.py, /api/dunya…; belgeler/DUNYA_EDITORU.md). panel.js'in yardımcılarını kullanır.
   Dünya: standart oyun verisinin üstüne konan değişiklik katmanı. Standart dünya salt okunur: değişiklikler taslakta durur,
   "Yeni dünya olarak kaydet" onları bir dünyaya çevirir. Kaydın varsayılan dünyası OYNA'da açılır.
   Görünümler: kitaplık (dünya kartları, pilotların dünyaları) ve editör (dünya çubuğu, bölüm menüsü, bölüm). Değişiklikler kendiliğinden
   kaydedilir (yama: dosya + JSON Pointer -> tam değer). */
'use strict';

Object.assign(ICONS, {
  map: '<polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/>',
  alien: '<path d="M12 3c-4.4 0-8 3.1-8 7.4 0 4.6 4.2 10.6 8 10.6s8-6 8-10.6C20 6.1 16.4 3 12 3z"/><path d="M7.5 11.5c1.6-.2 3 .7 3.3 2.2-1.6.3-3-.5-3.3-2.2z"/><path d="M16.5 11.5c-1.6-.2-3 .7-3.3 2.2 1.6.3 3-.5 3.3-2.2z"/>',
  target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  box: '<path d="M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4a2 2 0 0 0 1-1.7z"/><polyline points="3.3 7 12 12 20.7 7"/><line x1="12" y1="22" x2="12" y2="12"/>',
  ring: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5" stroke-dasharray="3 2"/>',
  lock: '<rect x="4" y="11" width="16" height="11" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
  move: '<polyline points="5 9 2 12 5 15"/><polyline points="9 5 12 2 15 5"/><polyline points="15 19 12 22 9 19"/><polyline points="19 9 22 12 19 15"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/>',
  crosshair: '<circle cx="12" cy="12" r="9"/><line x1="12" y1="1" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="23"/><line x1="1" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="23" y2="12"/>',
  minus: '<line x1="5" y1="12" x2="19" y2="12"/>',
  nest: '<polygon points="12 2 20.7 7 20.7 17 12 22 3.3 17 3.3 7 12 2"/><circle cx="12" cy="12" r="3"/>',
  maximize: '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>',
  gift: '<polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/><line x1="12" y1="22" x2="12" y2="7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/>',
});

const DE = { liste: null, did: null, section: 'genel', ozet: null, timer: {}, durum: 'hazir', esyalar: null, uzayli: null, sec: {} };
// bölüm: kimlik, ad, simge, açıklama, hazır mı (yakında olanlar menüde sönük)
const WE_SECTIONS = [
  ['genel', N('Genel Bakış'), 'globe', N('Dünyanın kartı, değişiklik özeti ve bu dünyada oynayan pilotlar.'), true],
  ['haritalar', N('Haritalar'), 'map', N('Uzaylıların doğma listesi ve bölgeleri, bonus kutuları, portallar, güvenli bölgeler ve inler.'), true],
  ['uzaylilar', N('Uzaylılar'), 'alien', N('Can, kalkan, hasar, hız, saldırganlık ve ödüller; var olan bir uzaylıdan yenisini türet.'), true],
  ['gorevler', N('Görevler'), 'target', N('Hedefler, ödüller, seviye ve önkoşullar; birkaç tıkla yeni görev.'), true],
  ['magaza', N('Mağaza'), 'cart', N('Ürünlerin fiyatı ve para birimi; ürünü satıştan kaldır.'), true],
  ['muzayede', N('Açık Artırma'), 'gavel', N('Saatlik, günlük ve haftalık lotlar: eşya, adet, anında alım fiyatı.'), true],
  ['kutular', N('Kutular ve Ganimet'), 'gift', N('Bonus kutularının ve booty kutularının içeriği.'), true],
  ['kapilar', N('Galaksi Kapıları'), 'ring', N('Dalgalar, uzaylılar ve kapı ödülleri.'), true],
  ['etkinlikler', N('Etkinlikler'), 'calendar', N('Bu dünyada hangi etkinlik ne zaman açık; harita etkinliklerinin uzaylıları.'), true],
  ['ekonomi', N('Ödüller ve Ekonomi'), 'star', N('Seviye eşikleri, rütbe puanı formülü ve rütbe eşikleri.'), true],
];
const weIcon = (id, cls = 'we-icon') => art('ed_' + id, cls);         // bölüm ikonu (images/ed_<bölüm>.webp, OP-009)
const WE_COVER_IMAGES = new Set(['standart', 'nebula', 'crimson', 'ice', 'mining', 'crystal', 'toxic', 'void']);   // gorsel/dunya_<kapak>.webp (OP-010)
// replaceChildren null/false'u metin olarak eklerdi ("null"): koşullu çocuklar süzülür
const fill = (el, ...k) => el.replaceChildren(...k.flat(Infinity).filter(x => x != null && x !== false));
const jp = (...p) => p.map(x => '/' + String(x).replace(/~/g, '~0').replace(/\//g, '~1')).join('');   // JSON Pointer (game_data.py)
const weIsStandard = () => DE.did === 'standart';

function weCover(cover, cls = '') {
  const el = h('div', { class: 'we-cover k-' + (cover || 'nebula') + ' ' + cls });
  if (WE_COVER_IMAGES.has(cover)) el.style.backgroundImage = 'url(images/dunya_' + cover + '.webp)';
  else el.append(h('i', { class: 'gz' }), h('i', { class: 'hl' }));      // gezegen ve halka (kodla)
  return el;
}

// ------------------------------------------------------------------ giriş noktası
async function renderWorld() {
  await loadGameImages();
  const r = await act(() => api('/api/dunyalar')); if (!r || S.page !== 'dunya') return;
  DE.liste = r;
  if (DE.did && !r.liste.some(w => w.id === DE.did)) DE.did = null;
  if (!DE.did) return weLibrary();
  weEditor();
}
function weOpen(did, section) { DE.did = did; DE.section = section || 'genel'; DE.uzayli = null; DE.sec = {}; renderWorld(); }

// ================================================================== KİTAPLIK
function weLibrary() {
  const r = DE.liste, special = r.liste.filter(w => !w.standart);
  const card = w => {
    const pilots = w.users || [];
    return h('div', { class: 'we-card' + (w.standart ? ' standard' : ''), onclick: e => { if (!e.target.closest('button')) weOpen(w.id); } },
      weCover(w.cover, 'buyuk'),
      h('div', { class: 'we-card-body' },
        h('div', { class: 'row between', style: { gap: '8px' } }, h('div', { class: 'we-card-name' }, w.standart ? icon('lock') : null, w.ad),
          w.standart ? badge(T('Salt okunur'), 'info') : badge(w.changes ? T('{0} değişiklik', w.changes) : T('Değişiklik yok'), w.changes ? 'orange' : '')),
        h('div', { class: 'we-card-desc muted small' }, w.aciklama || T('Açıklama yok.')),
        h('div', { class: 'we-card-pilot' }, pilots.length ? [icon('users'), h('span', null, pilots.slice(0, 3).map(p => p.pilot || p.ad).join(', ')
          + (pilots.length > 3 ? ' +' + (pilots.length - 3) : ''))] : h('span', { class: 'dim' }, T('Varsayılan dünyası bu olan pilot yok'))),
        h('div', { class: 'row', style: { gap: '6px', marginTop: 'auto' } },
          btn(w.standart ? T('İncele') : T('Düzenle'), () => weOpen(w.id), 'sm primary', w.standart ? 'search' : 'edit'),
          btn(T('Pilota ata'), ev => weAssignMenu(ev.currentTarget, w), 'sm', 'users'),
          h('span', { class: 'spacer' }),
          btn('', ev => weWorldMenu(ev.currentTarget, w), 'sm ghost icon', 'more', { title: T('Diğer') }))));
  };
  const new_ = h('button', { class: 'we-card yeni', type: 'button', onclick: () => weNewWorld() },
    h('div', { class: 'we-new-icon' }, icon('plus')), h('b', null, T('Yeni dünya')), h('span', { class: 'muted small' }, T('Standart dünyadan başla ya da bir dünyayı kopyala.')));
  const pilotRow = k => {
    const sel = h('select', { class: 'input', onchange: e => act(() => api('/api/kayitlar/dunya', { id: k.id, dunya: e.target.value }),
      T('{0}: varsayılan dünya değişti.', k.pilot || k.ad)).then(x => { if (x) { DE.liste = x; weLibrary(); poll(); } }) },
      r.liste.map(w => h('option', { value: w.id, selected: w.id === k.dunya }, w.ad)));
    return h('tr', null, h('td', null, h('b', null, k.pilot || '?'), ' ', badge(k.firma || '?', firmaCls(k.firma)), k.aktif ? ' ' : null,
      k.aktif ? badge(T('Etkin kayıt'), 'ok') : null), h('td', { class: 'muted' }, k.ad), h('td', null, lvl(k.seviye)), h('td', null, sel));
  };
  fill($('#content'), h('div', { class: 'stack' },
    h('div', { class: 'we-intro card' },
      h('div', null, h('h2', null, icon('globe'), T('Dünyalar')),
        h('p', { class: 'desc', style: { maxWidth: '640px', marginBottom: '0' } }, T('Bir dünya, oyunun haritalarını, uzaylılarını, görevlerini, mağazasını ve açık artırmasını kendine göre değiştirdiğin bir evrendir. Her pilot kendi varsayılan dünyasına girer; OYNA o dünyayı açar. Standart dünya korunur: değişikliklerini saklamak için yeni bir dünya oluşturursun.'))),
      h('div', { class: 'row wrap', style: { gap: '8px' } }, btn(T('Yeni dünya'), () => weNewWorld(), 'primary', 'plus'),
        btn(T('İçe aktar'), () => weImport(), '', 'upload')),
      art('dron_editor', 'we-intro-art')),
    h('div', { class: 'we-grid' }, r.liste.map(card), new_),
    !special.length ? h('div', { class: 'card we-empty' }, art('bos_dunya', 'we-empty-art'), h('div', null, T('Henüz kendi dünyan yok. Standart dünyayı açıp dilediğini değiştir, sonra "Yeni dünya olarak kaydet" de; ya da "Yeni dünya" ile boş bir kopyadan başla.'))) : null,
    r.kayitlar.length ? h('div', { class: 'card' }, h('h2', null, icon('users'), T('Pilotların dünyaları')),
      h('p', { class: 'desc' }, T('Her kayıt OYNA\'ya basınca kendi varsayılan dünyasına girer. Arkadaşlarınla oynarken host\'un dünyası herkese uygulanır.')),
      h('table', { class: 'table' }, h('thead', null, h('tr', null, [T('Pilot'), T('Kayıt'), T('Seviye'), T('Varsayılan dünya')].map(x => h('th', null, x)))),
        h('tbody', null, r.kayitlar.map(pilotRow)))) : null));
}

function weAssignMenu(anchor, w) {
  const ks = DE.liste.kayitlar;
  if (!ks.length) return toast(T('Önce bir kayıt oluştur.'), 'info');
  popMenu(anchor, ks.map(k => ({ label: (k.pilot || k.ad) + (k.dunya === w.id ? '  ✓' : ''), ic: k.dunya === w.id ? 'check' : 'users',
    fn: () => act(() => api('/api/kayitlar/dunya', { id: k.id, dunya: w.id }), T('{0} artık "{1}" dünyasına girer.', k.pilot || k.ad, w.ad))
      .then(x => { if (x) { DE.liste = x; poll(); S.page === 'dunya' && (DE.did ? weEditor() : weLibrary()); } }) })));
}

function weWorldMenu(anchor, w) {
  const items = [
    { label: w.standart ? T('İncele') : T('Düzenle'), iconEl: 'edit', fn: () => weOpen(w.id) },
    { label: T('Kopyala'), ic: 'copy', fn: async () => {
      const name = await promptBox(T('Dünyayı kopyala'), T('Yeni dünyanın adı'), w.standart ? T('Yeni dünya') : T('{0} (kopya)', w.ad)); if (name == null) return;
      const x = await act(() => api('/api/dunya/copy', { id: w.id, name }), T('Kopyalandı.')); if (x) { DE.liste = x; weLibrary(); } } },
    { label: T('Paylaş / dışa aktar'), ic: 'download', fn: () => weExport(w) },
  ];
  if (!w.standart) items.push({ label: T('Yeniden adlandır'), ic: 'edit', fn: () => weRename(w) }, '-',
    { label: T('Sil'), ic: 'trash', danger: true, fn: async () => {
      if (!await confirmBox(T('"{0}" silinsin mi?', w.ad), T('Dünya silinir; varsayılan dünyası bu olan pilotlar standart dünyaya döner. Silinen dünya save/dunyalar/_silinenler klasöründe saklanır.'), { ok: T('Sil'), danger: true })) return;
      const x = await act(() => api('/api/dunya/sil', { id: w.id }), T('Dünya silindi.')); if (x) { DE.liste = x; if (DE.did === w.id) DE.did = null; renderWorld(); } } });
  popMenu(anchor, items);
}

async function weRename(w) {
  const name = await promptBox(T('Yeniden adlandır'), T('Dünyanın adı'), w.ad); if (name == null) return;
  const x = await act(() => api('/api/dunya/update', { id: w.id, name }), T('Kaydedildi.')); if (x) { DE.liste = x; renderWorld(); }
}

// yeni dünya: ad, açıklama, kapak, başlangıç (standart ya da bir dünya); taslaktan=true ise standart dünyanın taslağı
function weNewWorld({ from_draft = false } = {}) {
  const w = { ad: '', aciklama: '', cover: 'nebula', kaynak: 'standart', kayit: null };
  const active = DE.liste.kayitlar.find(k => k.aktif);
  const name = h('input', { class: 'input', placeholder: T('Örn. Zor Uzay, Avcı Cenneti'), maxlength: 40, oninput: e => { w.ad = e.target.value; } });
  const is_open = h('textarea', { class: 'input', rows: 2, maxlength: 240, placeholder: T('Bu dünyada ne farklı? (isteğe bağlı)'), oninput: e => { w.aciklama = e.target.value; } });
  const covers = h('div', { class: 'we-covers' });
  const renderCover = () => fill(covers, ...DE.liste.covers.filter(k => k !== 'standart').map(k =>
    h('button', { type: 'button', class: 'we-cover-pick' + (w.cover === k ? ' on' : ''), onclick: () => { w.cover = k; renderCover(); } }, weCover(k))));
  renderCover();
  const source = from_draft ? null : h('select', { class: 'input', onchange: e => { w.kaynak = e.target.value; } },
    DE.liste.liste.map(x => h('option', { value: x.id }, x.standart ? T('Standart dünya (boş başla)') : T('Kopyala: {0}', x.ad))));
  const assign = active ? h('label', { class: 'row', style: { gap: '8px', cursor: 'pointer' } }, h('label', { class: 'switch' },
    h('input', { type: 'checkbox', checked: true, onchange: e => { w.kayit = e.target.checked ? active.id : null; } }), h('span')),
    h('span', null, T('{0} bu dünyaya girsin (varsayılan dünyası olsun)', active.pilot || active.ad))) : null;
  if (active) w.kayit = active.id;
  const m = modal({ title: from_draft ? T('Yeni dünya olarak kaydet') : T('Yeni dünya'), wide: true,
    sub: from_draft ? T('Standart dünyada yaptığın {0} değişiklik bu dünyaya taşınır; standart dünya olduğu gibi kalır.', DE.ozet?.changes || 0) : null,
    body: h('div', { class: 'stack', style: { gap: '14px' } }, from_draft ? art('dron_kayit', 'we-save-art') : null, field(T('Ad'), name), field(T('Açıklama'), is_open),
      field(T('Kapak'), covers), source ? field(T('Başlangıç'), source) : null, assign),
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Oluştur'), async () => {
      const x = await act(() => api('/api/dunya/create', Object.assign({}, w, { from_draft })), T('Dünya oluşturuldu: {0}', w.ad.trim()));
      if (!x) return;
      m.close(); DE.liste = x; poll(); weOpen(x.yeni, from_draft ? DE.section : 'genel');
    }, 'primary', 'check')] });
}

// ================================================================== EDİTÖR
async function weEditor() {
  const summary = await act(() => api('/api/dunya?dunya=' + encodeURIComponent(DE.did))); if (!summary || S.page !== 'dunya') return;
  DE.ozet = summary;
  const root = h('div', { class: 'stack', id: 'de-kok' });
  fill($('#content'), root);
  root.append(weBar(), h('div', { id: 'we-warning' }), h('div', { class: 'we-layout' }, deMenu(), h('div', { class: 'we-field', id: 'we-field' })));
  weWarning();
  weRenderSection();
}

function weBar() {
  const w = DE.ozet;
  return h('div', { class: 'card we-bar' },
    btn('', () => { DE.did = null; renderWorld(); }, 'ghost icon', 'arrowL', { title: T('Dünyalar') }),
    weCover(w.cover, 'kucuk'),
    h('div', { class: 'we-bar-name' }, h('div', { class: 'row', style: { gap: '8px' } }, h('b', null, w.ad),
      w.standart ? badge([icon('lock'), T('Standart · salt okunur')], 'info') : badge(T('Özel dünya'), 'orange')),
      h('div', { class: 'muted small ellipsis' }, w.aciklama || (w.standart ? '' : T('Açıklama yok.')))),
    h('span', { class: 'spacer' }),
    h('span', { class: 'we-save-status', id: 'we-save-status' }),
    btn(T('Dünya değiştir'), ev => popMenu(ev.currentTarget, DE.liste.liste.map(x => ({ label: x.ad + (x.id === DE.did ? '  ✓' : ''),
      ic: x.standart ? 'lock' : 'globe', fn: () => weOpen(x.id, DE.section) }))), 'sm', 'refresh'),
    btn('', ev => weWorldMenu(ev.currentTarget, DE.liste.liste.find(x => x.id === DE.did) || w), 'sm ghost icon', 'more', { title: T('Diğer') }));
}

function weSaveStatus(d) {
  DE.durum = d;
  const el = $('#we-save-status'); if (!el) return;
  el.className = 'we-save-status ' + d;
  fill(el, ...(d === 'kaydediliyor' ? [h('span', { class: 'spin' }), T('Kaydediliyor…')] : d === 'kaydedildi'
    ? [icon('check'), weIsStandard() ? T('Taslağa yazıldı') : T('Kaydedildi')] : []));
}

function weWarning() {
  const el = $('#we-warning'); if (!el) return;
  const w = DE.ozet, out = [];
  if (w.standart) out.push(h('div', { class: 'we-draft' + (w.changes ? ' dolu' : '') }, art('dron_kilit', 'we-draft-art'),
    h('div', null, h('b', null, w.changes ? T('{0} değişiklik kaydedilmedi', w.changes) : T('Standart dünya düzenlenemez')),
      h('div', { class: 'small' }, w.changes ? T('Standart dünya korunur. Bu değişiklikleri saklamak için onları yeni bir dünyaya kaydet.')
        : T('Dilediğini değiştirebilirsin: değişiklikler bir taslakta tutulur, oyuna geçmesi için yeni bir dünya olarak kaydedersin.'))),
    w.changes ? btn(T('Taslağı at'), async () => {
      if (await confirmBox(T('Taslak atılsın mı?'), T('Standart dünyada yaptığın {0} değişiklik silinir.', w.changes), { ok: T('At'), danger: true }))
        act(() => api('/api/dunya/discard_draft', {}), T('Taslak atıldı.')).then(x => x && weEditor());
    }, 'sm ghost', 'trash') : null,
    btn(T('Yeni dünya olarak kaydet'), () => weNewWorld({ from_draft: true }), 'sm orange', 'save', { disabled: !w.changes })));
  if (w.server_in_this_world && !w.restart_needed) out.push(h('div', { class: 'alert bilgi' }, icon('zap'),
    h('div', null, T('Sunucu bu dünyayla açık: mağaza ve açık artırma değişiklikleri oyunda hemen geçerli. Öteki bölümlerdeki değişiklikler için sunucu yeniden başlamalı.'))));
  if (w.server_in_this_world && w.restart_needed) out.push(h('div', { class: 'alert uyari' }, icon('alert'),
    h('div', null, T('Bazı değişiklikler sunucu yeniden başlayınca geçerli olur (oyun kapalıyken OYNA kendiliğinden yeniden başlatır). Mağaza ve açık artırma değişiklikleri zaten oyunda.')),
    btn(T('Sunucuyu yeniden başlat'), async () => {
      if (await confirmBox(T('Sunucu yeniden başlatılsın mı?'), T('Oyundaysan bağlantın kopar; istemci yeniden bağlanır. Kaydın korunur.'), { ok: T('Yeniden başlat') }))
        act(() => api('/api/dunya/server_restart', {}), T('Sunucu yeniden başlatıldı.')).then(x => x && weEditor());
    }, 'sm', 'refresh')));
  fill(el, ...out);
  el.style.display = out.length ? '' : 'none';
}

function deMenu() {
  return h('nav', { class: 'de-menu', id: 'de-menu' }, WE_SECTIONS.map(([id, name, iconEl, , ready]) => {
    const n = DE.ozet.sections[id] || 0;
    return h('button', { type: 'button', class: (DE.section === id ? 'on ' : '') + (ready ? '' : 'soon'), 'data-b': id, disabled: !ready,
      title: ready ? null : T('Yakında'), onclick: () => { DE.section = id; DE.sec = {}; weMenuCount(); weRenderSection(); } },
      weIcon(id), h('span', null, T(name)), ready ? (n ? h('span', { class: 'we-count' }, n) : null) : h('span', { class: 'we-soon' }, T('Yakında')));
  }));
}
function weMenuCount() {
  document.querySelectorAll('#de-menu button').forEach(b => {
    b.classList.toggle('on', b.dataset.b === DE.section);
    const n = DE.ozet.sections[b.dataset.b] || 0, s = b.querySelector('.we-count');
    if (b.disabled) return;
    if (n && s) s.textContent = n; else if (n) b.append(h('span', { class: 'we-count' }, n)); else if (s) s.remove();
  });
}

function weRenderSection() {
  const b = WE_SECTIONS.find(x => x[0] === DE.section) || WE_SECTIONS[0];
  const area = $('#we-field'); if (!area) return;
  area.parentNode.classList.toggle('dar', b[0] === 'haritalar');          // harita tuvaline yer: menü simge şeridi
  fill(area, h('div', { class: 'empty' }, h('div', { class: 'spin', style: { margin: '30px auto' } })));
  ({ genel: weGeneral, haritalar: weMaps, uzaylilar: weAliens, gorevler: weQuests, magaza: weShop, muzayede: weAuction, kutular: weBoxes, kapilar: weGates, etkinlikler: weEvents, ekonomi: weEconomy }[b[0]])(area, b);
}
const weTitle = (b, ...extras) => h('div', { class: 'row between wrap we-section-head' }, h('div', null, h('h2', null, weIcon(b[0], 'we-icon buyuk'), T(b[1])),
  h('div', { class: 'muted small' }, T(b[3]))), h('div', { class: 'row wrap', style: { gap: '8px' } }, ...extras));

// değişiklik: yama (dosya + yol -> tam değer); standartta taslağa. Gecikmeli (aynı anahtar için son değer gider).
function wePatch(file, route, value, { ms = 450, after } = {}) {
  const k = file + route;
  clearTimeout(DE.timer[k]); weSaveStatus('kaydediliyor');
  return new Promise(res => {
    DE.timer[k] = setTimeout(async () => {
      delete DE.timer[k];
      const r = await act(() => api('/api/dunya/yama', { dunya: DE.did, file, route, value }));
      if (r) { DE.ozet = Object.assign(DE.ozet, r); weMenuCount(); weWarning(); weSaveStatus('kaydedildi'); if (after) after(r); }
      else weSaveStatus('hazir');
      res(r);
    }, ms);
  });
}
async function weRevert(file, route, section) {
  const r = await act(() => api('/api/dunya/geri_al', { dunya: DE.did, file, route, section }), T('Standarda döndürüldü.'));
  if (r) { DE.ozet = Object.assign(DE.ozet, r); weMenuCount(); weWarning(); }
  return r;
}

// sayı alanı: −/+ düğmeleri, elle yazım; değişince cb(değer)
function weNumber(v, cb, { min = 0, max = 1e9, step = 1, width = 92 } = {}) {
  const inp = h('input', { class: 'input num', type: 'number', min, max, step: step, value: v, style: { width: width + 'px' } });
  const set = x => { x = Math.max(min, Math.min(max, Math.round(+x || 0))); inp.value = x; cb(x); };
  inp.addEventListener('change', () => set(inp.value));
  return h('div', { class: 'we-number' }, h('button', { type: 'button', onclick: () => set(+inp.value - step), tabindex: -1 }, icon('minus')), inp,
    h('button', { type: 'button', onclick: () => set(+inp.value + step), tabindex: -1 }, icon('plus')));
}
// "standart: X" ipucu ve tek tıkla geri alma
const weStd = (std, now, back, fmt = fmtN) => std == null || JSON.stringify(std) === JSON.stringify(now) ? null
  : h('button', { type: 'button', class: 'we-standard', title: T('Standart değere döndür'), onclick: back }, icon('undo'), T('Standart: {0}', fmt(std)));

// ================================================================== ORTAK SEÇİCİLER
const ITEM_CATEGORY = [['hepsi', N('Hepsi')], ['ammunition', N('Cephane')], ['equipment', N('Ekipman')], ['ship', N('Gemiler')],
  ['drone', N('Dronlar')], ['resource', N('Kaynaklar')], ['booster', N('Boosterlar')], ['currency', N('Para')], ['diger', N('Diğer')]];
const itemCategory = l => { const p = l.split('_')[0]; return ITEM_CATEGORY.some(k => k[0] === p) ? p : 'diger'; };

async function pickItem(title = T('Eşya seç')) {
  if (!DE.esyalar) { const r = await act(() => api('/api/dunya/esyalar')); if (!r) return null; DE.esyalar = r.esyalar; }
  return new Promise(res => {
    let multiplier = 'hepsi', q = '', limit = 120, done = false;
    const grid = h('div', { class: 'we-picker-grid' });
    const render = () => {
      const s = q.trim().toLowerCase();
      const list = DE.esyalar.filter(l => (multiplier === 'hepsi' || itemCategory(l) === multiplier) && (!s || l.includes(s) || itemName(l).toLowerCase().includes(s)));
      fill(grid, ...list.slice(0, limit).map(l => h('button', { type: 'button', class: 'we-picker-item', title: l,
        onclick: () => { done = true; m.close(); res(l); } }, gameIcon(l, 44, null, 'box'), h('span', null, itemName(l)))),
        list.length > limit ? h('button', { type: 'button', class: 'btn sm we-more', onclick: () => { limit += 240; render(); } }, T('{0} eşya daha', fmtN(list.length - limit))) : null,
        !list.length ? h('div', { class: 'empty small muted' }, T('Eşleşen eşya yok.')) : null);
    };
    const seg = h('div', { class: 'seg' }, ITEM_CATEGORY.map(([k, name]) => h('button', { class: k === multiplier ? 'on info' : '', onclick: e => {
      multiplier = k; seg.querySelectorAll('button').forEach(b => b.classList.remove('on', 'info')); e.currentTarget.classList.add('on', 'info'); render(); } }, T(name))));
    const search = h('input', { class: 'input', placeholder: T('Ad ya da kimlikle ara…'), oninput: e => { q = e.target.value; limit = 120; render(); } });
    const m = modal({ title: title, wide: true, onclose: () => { if (!done) res(null); }, body: h('div', { class: 'stack', style: { gap: '10px' } },
      search, seg, !GI.index ? h('div', { class: 'small muted' }, T('Oyunun görselleri, oyun bir kez BepInEx ile açılınca hazırlanır.')) : null, grid) });
    render();
  });
}

async function alienList() {
  if (!DE.uzayli) { const r = await act(() => api('/api/dunya/section?bolum=uzaylilar&dunya=' + encodeURIComponent(DE.did))); if (!r) return null; DE.uzayli = r.uzaylilar; }
  return DE.uzayli;
}
const npcIcon = (u, size) => u && u.ikon && GI.index?.sprite[u.ikon] ? sprite(u.ikon, size) : h('span', { class: 'sprite bos we-npc-empty', style: { width: size + 'px', height: size + 'px' } }, icon('alien'));
const npcName = u => (u?.ad || '').replace(/^[-=\[\]:.{}\s]+|[-=\[\]:.{}\s]+$/g, '') || u?.tip || '?';

async function pickAlien(title = T('Uzaylı seç'), { with_id = false, numeric = false } = {}) {
  const entries = await alienList(); if (!entries) return null;
  return new Promise(res => {
    let q = '', filter_by = 'harita', done = false;
    const grid = h('div', { class: 'we-picker-grid npc' });
    const render = () => {
      const s = q.trim().toLowerCase();
      const l = entries.filter(u => (!with_id || u.npc_kimlik != null) && (!numeric || /^\d+$/.test(u.tip)) && (filter_by === 'hepsi' || (filter_by === 'harita' ? u.nerede.length || u.yeni : u.etkinlik))
        && (!s || npcName(u).toLowerCase().includes(s)));
      fill(grid, ...l.map(u => h('button', { type: 'button', class: 'we-picker-item', onclick: () => { done = true; m.close(); res(u); } },
        npcIcon(u, 44), h('span', null, npcName(u)), h('small', { class: 'muted' }, T('Can {0}', fmtN(u.hp))))),
        !l.length ? h('div', { class: 'empty small muted' }, T('Eşleşen uzaylı yok.')) : null);
    };
    const seg = h('div', { class: 'seg' }, [['harita', N('Haritalarda doğanlar')], ['etkinlik', N('Etkinlik')], ['hepsi', N('Hepsi')]].map(([k, name]) =>
      h('button', { class: k === filter_by ? 'on info' : '', onclick: e => { filter_by = k; seg.querySelectorAll('button').forEach(b => b.classList.remove('on', 'info')); e.currentTarget.classList.add('on', 'info'); render(); } }, T(name))));
    const m = modal({ title: title, wide: true, onclose: () => { if (!done) res(null); }, body: h('div', { class: 'stack', style: { gap: '10px' } },
      h('input', { class: 'input', placeholder: T('Uzaylı ara…'), oninput: e => { q = e.target.value; render(); } }), seg, grid) });
    render();
  });
}

let WE_MAPS = null;
async function pickMap(title, selected = [], { multi = true } = {}) {
  if (!WE_MAPS) { const r = await act(() => api('/api/dunya/section?bolum=haritalar&dunya=' + encodeURIComponent(DE.did))); if (!r) return null; WE_MAPS = r.haritalar; }
  return new Promise(res => {
    const sec = new Set(selected.map(String)); let done = false;
    const group = h('div', { class: 'we-map-chips' });
    const render = () => fill(group, ...WE_MAPS.map(x => h('button', { type: 'button', class: 'we-map-chip f-' + x.firma + (sec.has(x.ad) ? ' on' : ''),
      onclick: () => { if (!multi) { done = true; m.close(); return res([x.ad]); } sec.has(x.ad) ? sec.delete(x.ad) : sec.add(x.ad); render(); } }, x.ad)));
    const m = modal({ title: title, wide: true, onclose: () => { if (!done) res(null); }, body: h('div', { class: 'stack', style: { gap: '10px' } },
      multi ? h('div', { class: 'small muted' }, T('Hiçbiri seçilmezse her haritada geçerli.')) : null, group),
      foot: multi ? [btn(T('Temizle'), () => { sec.clear(); render(); }, 'ghost'), btn(T('Tamam'), () => { done = true; m.close(); res([...sec]); }, 'primary')] : null });
    render();
  });
}

// ================================================================== GENEL BAKIŞ
function weGeneral(area, b) {
  const w = DE.ozet;
  const covers = h('div', { class: 'we-covers' });
  const renderCover = () => fill(covers, ...DE.liste.covers.filter(k => k !== 'standart').map(k =>
    h('button', { type: 'button', class: 'we-cover-pick' + (w.cover === k ? ' on' : ''), disabled: w.standart, onclick: () =>
      act(() => api('/api/dunya/update', { id: w.id, cover: k })).then(x => { if (x) { DE.liste = x; w.cover = k; renderCover(); $('#de-kok .we-bar .we-cover').replaceWith(weCover(k, 'kucuk')); } }) }, weCover(k))));
  renderCover();
  const saveMeta = (fieldName, v) => act(() => api('/api/dunya/update', { id: w.id, [fieldName]: v })).then(x => { if (x) { DE.liste = x; w[fieldName] = v; weSaveStatus('kaydedildi'); } });
  const card = h('div', { class: 'card we-overview-card' }, weCover(w.cover, 'buyuk'),
    h('div', { class: 'stack', style: { gap: '12px' } },
      w.standart ? h('div', null, h('h3', { class: 'de-h3' }, icon('lock'), w.ad), h('p', { class: 'muted' }, w.aciklama))
        : [field(T('Ad'), h('input', { class: 'input', value: w.ad, maxlength: 40, onchange: e => saveMeta('ad', e.target.value).then(() => weEditor()) })),
          field(T('Açıklama'), h('textarea', { class: 'input', rows: 2, maxlength: 240, onchange: e => saveMeta('aciklama', e.target.value) }, w.aciklama || '')),
          field(T('Kapak'), covers)],
      h('div', { class: 'row wrap small muted', style: { gap: '14px' } }, w.created ? h('span', null, T('Oluşturuldu {0}', fmtWhen(w.created))) : null,
        w.guncelleme ? h('span', null, T('Son değişiklik {0}', fmtWhen(w.guncelleme))) : null)));
  const sections = h('div', { class: 'card' }, h('h2', null, icon('layers'), T('Değişiklikler')),
    h('p', { class: 'desc' }, w.changes ? T('Bu dünyada standarttan farklı olanlar. Bir bölümü tek tıkla standarda döndürebilirsin.') : T('Bu dünya henüz standart dünyayla aynı. Soldaki bölümlerden düzenlemeye başla.')),
    h('div', { class: 'we-summary-grid' }, WE_SECTIONS.filter(x => x[0] !== 'genel').map(x => {
      const n = w.sections[x[0]] || 0;
      return h('div', { class: 'we-summary-box' + (n ? ' dolu' : '') + (x[4] ? '' : ' soon') },
        h('div', { class: 'row', style: { gap: '8px' } }, weIcon(x[0], 'we-icon orta'), h('b', null, T(x[1]))),
        h('div', { class: 'we-summary-count' }, x[4] ? (n ? T('{0} değişiklik', n) : T('Standart')) : T('Yakında')),
        h('div', { class: 'row', style: { gap: '6px' } }, x[4] ? btn(T('Aç'), () => { DE.section = x[0]; weMenuCount(); weRenderSection(); }, 'sm', 'chevR') : null,
          n ? btn('', async () => {
            if (await confirmBox(T('{0} standarda dönsün mü?', T(x[1])), T('Bu bölümdeki {0} değişiklik silinir.', n), { ok: T('Standarda döndür'), danger: true }))
              weRevert(null, null, x[0]).then(r => r && weRenderSection());
          }, 'sm ghost icon', 'undo', { title: T('Standarda döndür') }) : null));
    })));
  const users = (DE.liste.liste.find(x => x.id === w.id) || {}).users || [];
  const pilots = h('div', { class: 'card' }, h('h2', null, icon('users'), T('Bu dünyada oynayanlar')),
    h('p', { class: 'desc' }, users.length ? T('Bu pilotlar OYNA\'ya basınca bu dünyaya girer.') : T('Henüz bu dünyayı varsayılan yapan pilot yok.')),
    h('div', { class: 'chips' }, users.map(p => h('span', { class: 'chip' }, icon('users'), p.pilot || p.ad))),
    h('div', { class: 'row', style: { marginTop: '12px' } }, btn(T('Pilota ata'), ev => weAssignMenu(ev.currentTarget, w), 'sm', 'users')));
  fill(area, h('div', { class: 'stack' }, card, sections, pilots,
    h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('İstemcinin sınırları: yeni harita ya da yeni eşya eklenemez (ikisi de oyunun kendi dosyalarında). Yeni uzaylılar var olan bir modelin yeni değerlerle kopyasıdır; adları oyunda görünür.')))));
}

// ================================================================== UZAYLILAR
const ORE_NAME = { 0: 'resource_ore_prometium', 1: 'resource_ore_endurium', 2: 'resource_ore_terbium', 3: 'resource_ore_xenomit', 4: 'resource_ore_prometid',
  5: 'resource_ore_duranium', 6: 'resource_ore_promerium', 7: 'resource_ore_seprom', 8: 'resource_ore_palladium', 28: 'resource_ore_osmium' };
const REWARD_FIELD = [['ep', N('Deneyim'), 'kaynak_deneyim'], ['onur', N('Onur'), 'kaynak_onur'], ['kredi', N('Kredi'), 'kaynak_kredi'], ['uridyum', N('Uridyum'), 'kaynak_uridyum']];

async function weAliens(area, b) {
  DE.uzayli = null;
  const entries = await alienList(); if (!entries || DE.section !== 'uzaylilar') return;
  const f = DE.sec.aliens || (DE.sec.aliens = { q: '', filter_by: 'harita', secili: null });
  const grid = h('div', { class: 'we-npc-list' }), detail = h('div', { class: 'we-detail' });
  const maxHp = Math.max(...entries.map(u => u.hp)), scale = v => Math.max(3, Math.log10(1 + v) / Math.log10(1 + maxHp) * 100);   // can/kalkan çubuğu (logaritmik)
  const render = () => {
    const s = f.q.trim().toLowerCase();
    const l = entries.filter(u => (f.filter_by === 'hepsi' || (f.filter_by === 'harita' ? u.nerede.length || u.yeni : f.filter_by === 'etkinlik' ? u.etkinlik
      : f.filter_by === 'degisti' ? u.degisti : u.yeni)) && (!s || npcName(u).toLowerCase().includes(s)));
    fill(grid, ...l.map(u => h('button', { type: 'button', class: 'de-npc' + (f.secili === u.tip ? ' on' : '') + (u.degisti ? ' degisti' : ''),
      onclick: () => { f.secili = u.tip; render(); } }, npcIcon(u, 40),
      h('div', { class: 'we-npc-name' }, h('b', null, npcName(u)), h('div', { class: 'we-bars' },
        h('i', { class: 'hp', style: { width: scale(u.hp) + '%' } }), h('i', { class: 'sh', style: { width: scale(u.kalkan) + '%' } }))),
      u.yeni ? badge(T('Yeni'), 'orange') : u.saldirgan ? h('span', { class: 'we-aggressive', title: T('Saldırgan') }, icon('zap')) : null)),
      !l.length ? h('div', { class: 'empty small muted' }, T('Eşleşen uzaylı yok.')) : null);
    const u = entries.find(x => x.tip === f.secili) || l[0];
    if (u && !f.secili) { f.secili = u.tip; grid.querySelector('.de-npc')?.classList.add('on'); }
    fill(detail, u ? alienDetail(u, entries, render) : h('div', { class: 'empty muted' }, T('Soldan bir uzaylı seç.')));
  };
  const seg = h('div', { class: 'seg' }, [['harita', N('Haritalarda')], ['etkinlik', N('Etkinlik')], ['degisti', N('Değiştirilenler')], ['yeni', N('Yeni')], ['hepsi', N('Hepsi')]].map(([k, name]) =>
    h('button', { class: f.filter_by === k ? 'on info' : '', onclick: () => { f.filter_by = k; weRenderSection(); } }, T(name))));
  fill(area, h('div', { class: 'card' }, weTitle(b, h('input', { class: 'input', style: { width: '200px' }, placeholder: T('Uzaylı ara…'), value: f.q, oninput: e => { f.q = e.target.value; render(); } }), seg),
    h('div', { class: 'we-two-col' }, grid, detail)));
  render();
}

function alienDetail(u, entries, refresh) {
  const t = JSON.parse(JSON.stringify(u.tam)), std = u.standart;
  const route = jp('tipler', u.tip);
  const save = () => {
    Object.assign(u, { ad: t.ad, hp: t.hp, kalkan: t.kalkan, hasar: t.hasar, hiz: t.hiz, saldirgan: t.saldirgan, odul: t.odul, kargo: t.kargo, tam: t, degisti: true });
    wePatch('npc.json', route, t);
  };
  const back = async () => { if (await weRevert('npc.json', route)) { DE.uzayli = null; weRenderSection(); } };
  const row = (name, fieldName, opts) => h('div', { class: 'we-field-row' + (std && std[fieldName] !== t[fieldName] ? ' degisti' : '') },
    h('label', null, name), weNumber(t[fieldName], v => { t[fieldName] = v; save(); refreshRows(); }, opts),
    std ? weStd(std[fieldName], t[fieldName], () => { t[fieldName] = std[fieldName]; save(); refreshRows(); }) : null);
  const box = h('div', { class: 'stack', style: { gap: '8px' } });
  const refreshRows = () => fill(box, 
    row(T('Can'), 'hp', { max: 50000000, adim: 100, width: 110 }), row(T('Kalkan'), 'kalkan', { max: 50000000, adim: 100, width: 110 }),
    row(T('Hasar'), 'hasar', { max: 1000000, adim: 10 }), row(T('Hız'), 'hiz', { max: 2000, adim: 5 }),
    h('div', { class: 'we-field-row' + (std && std.saldirgan !== t.saldirgan ? ' degisti' : '') }, h('label', null, T('Saldırgan')),
      h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: t.saldirgan, onchange: e => { t.saldirgan = e.target.checked; save(); refreshRows(); } }), h('span')),
      h('span', { class: 'small muted' }, t.saldirgan ? T('Seni görünce saldırır.') : T('Yalnız saldırınca karşılık verir.'))),
    h('div', { class: 'we-subtitle' }, T('Öldürme ödülü')),
    h('div', { class: 'we-reward-grid' }, REWARD_FIELD.map(([k, name, g]) => h('div', { class: 'we-reward' + (std && (std.odul || {})[k] !== t.odul[k] ? ' degisti' : '') },
      art(g, 'we-reward-icon'), h('div', null, h('div', { class: 'small muted' }, T(name)), weNumber(t.odul[k] || 0, v => { t.odul[k] = v; save(); }, { max: 1e9, adim: k === 'uridyum' ? 1 : 10, width: 86 }))))),
    h('div', { class: 'we-subtitle' }, T('Kargo kutusu (cevher)')),
    h('div', { class: 'we-cargo' }, Object.entries(ORE_NAME).filter(([i]) => t.kargo[i] || +i < 8).map(([i, loot]) =>
      h('div', { class: 'we-cargo-item' + (t.kargo[i] ? ' var' : '') }, gameIcon(loot, 26, null, 'box'), h('span', { class: 'small' }, itemName(loot)),
        weNumber(t.kargo[i] || 0, v => { if (v) t.kargo[i] = v; else delete t.kargo[i]; save(); }, { max: 100000, adim: 1, width: 64 })))));
  refreshRows();
  const nameInp = h('input', { class: 'input we-name-input', value: t.ad, maxlength: 60, onchange: e => { t.ad = e.target.value; save(); } });
  const deriveAlien = async () => {
    const name = await promptBox(T('Yeni uzaylı türet'), T('Yeni uzaylının oyunda görünen adı'), '-=[ ' + npcName(u) + ' X ]=-'); if (name == null) return;
    const n = Math.max(0, ...entries.filter(x => x.tip.startsWith('ozel_')).map(x => +x.tip.slice(5) || 0)) + 1;
    const new_ = Object.assign(JSON.parse(JSON.stringify(t)), { name, model: t.model || u.tip, npc_kimlik: null, _kaynak: 'Dünya Editörü: ' + u.tip });
    delete new_.npc_kimlik; delete new_.etkinlik; delete new_.haritalar;
    const r = await wePatch('npc.json', jp('tipler', 'ozel_' + n), new_, { ms: 0 });
    if (r) { toast(T('Yeni uzaylı oluşturuldu. Haritalar bölümünden bir haritanın doğma listesine ekleyebilirsin.'), 'ok'); DE.uzayli = null; DE.sec.aliens.secili = 'ozel_' + n; DE.sec.aliens.filter_by = 'yeni'; weRenderSection(); }
  };
  return h('div', { class: 'stack', style: { gap: '14px' } },
    h('div', { class: 'we-detail-head' }, npcIcon(u, 64), h('div', { style: { flex: 1, minWidth: 0 } }, nameInp,
      h('div', { class: 'small muted' }, u.yeni ? T('Yeni uzaylı · model: {0}', u.model) : T('Tür {0}', u.tip), std && std.ad !== t.ad ? [' · ', weStd(std.ad, t.ad, () => { t.ad = std.ad; nameInp.value = std.ad; save(); }, x => x)] : null))),
    box,
    h('div', { class: 'we-subtitle' }, T('Nerede doğar')),
    u.nerede.length ? h('div', { class: 'chips' }, u.nerede.map(m => h('button', { type: 'button', class: 'chip link', onclick: () => {
      const hm = (WE_MAPS || []).find(x => x.ad === m); DE.section = 'haritalar'; DE.sec = { hr: { secili: hm ? hm.id : null } }; weMenuCount(); weRenderSection(); } }, icon('map'), m)))
      : h('div', { class: 'small muted' }, T('Hiçbir haritanın doğma listesinde değil.')),
    h('div', { class: 'row wrap', style: { gap: '8px', marginTop: '6px' } },
      btn(T('Bundan yeni uzaylı türet'), deriveAlien, 'sm', 'copy'),
      u.degisti && !u.yeni ? btn(T('Standarda döndür'), back, 'sm ghost', 'undo') : null,
      u.yeni ? btn(T('Sil'), async () => {
        if (await confirmBox(T('Uzaylı silinsin mi?'), T('Doğma listelerindeki satırları da kalkar.'), { ok: T('Sil'), danger: true })) {
          const r = await wePatch('npc.json', route, { $delete: true }, { ms: 0 }); if (r) { DE.uzayli = null; DE.sec.aliens.secili = null; weRenderSection(); } }
      }, 'sm danger', 'trash') : null));
}

// ================================================================== HARİTALAR
const MAP_TOOL = [['sec', N('Seç ve taşı'), 'move'], ['bolge', N('Doğma bölgesi'), 'target'], ['in', N('İn (sabit doğma noktası)'), 'nest'], ['guvenli', N('Güvenli bölge'), 'shield']];
const MAP_LAYER = [['izgara', N('Izgara')], ['engel', N('Engeller')], ['guvenli', N('Güvenli bölgeler')], ['portal', N('Portallar')], ['bolge', N('Doğma bölgeleri')], ['in', N('İnler')]];
const MAP_COMPANY = { mmo: N('MMO'), eic: N('EIC'), vru: N('VRU'), savas: N('Savaş'), korsan: N('Korsan'), bl: N('Black Light'), diger: N('Diğer') };

async function weMaps(area, b) {
  const r = await act(() => api('/api/dunya/section?bolum=haritalar&dunya=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'haritalar') return;
  WE_MAPS = r.haritalar;
  await alienList();
  const f = DE.sec.hr || (DE.sec.hr = {});
  f.arac = f.arac || 'sec'; f.layer = f.layer || { izgara: true, engel: true, guvenli: true, portal: true, bolge: true, in: true };
  if (!f.secili || !r.haritalar.some(x => x.id === f.secili)) f.secili = r.haritalar[0]?.id;
  const groups = {};
  r.haritalar.forEach(x => (groups[x.firma] = groups[x.firma] || []).push(x));
  const entries = h('div', { class: 'we-map-list' }, Object.entries(groups).map(([fi, xs]) => h('div', { class: 'we-map-group' },
    h('div', { class: 'we-map-group-name f-' + fi }, T(MAP_COMPANY[fi] || fi)),
    h('div', { class: 'we-map-group-chips' }, xs.map(x => h('button', { type: 'button', class: 'we-map-chip f-' + x.firma + (x.id === f.secili ? ' on' : '') + (x.degisti ? ' degisti' : ''),
      title: T('{0} uzaylı', fmtN(x.uzayli)), onclick: () => { f.secili = x.id; f.nesne = null; weRenderSection(); } }, x.ad))))));
  const canvas = h('div', { class: 'we-canvas-card' }), panel = h('div', { class: 'we-map-panel' });
  fill(area, h('div', { class: 'card we-map-card' }, weTitle(b), entries, h('div', { class: 'we-map' }, canvas, panel)));
  const hm = await act(() => api('/api/dunya/harita?dunya=' + encodeURIComponent(DE.did) + '&id=' + f.secili)); if (!hm || DE.section !== 'haritalar') return;
  mapEditor(hm, canvas, panel, f);
}

function mapEditor(hm, canvas, panel, f) {
  const [W, H] = hm.boyut, layout = JSON.parse(JSON.stringify(hm.duzen || {}));
  layout.guvenli = layout.guvenli || []; layout.lairs = layout.lairs || {}; layout.portals = layout.portals || {};
  const npc = hm.npc.map(g => Object.assign({}, g));
  const aliens = tip => (DE.uzayli || []).find(u => u.tip === tip);
  const saveNpc = () => { wePatch('npc.json', jp('haritalar', hm.id, 'npc'), npc.map(g => g.bolge ? { tip: g.tip, adet: g.adet, bolge: g.bolge } : { tip: g.tip, adet: g.adet })); markSelected(); };
  const saveLayout = () => { const d = JSON.parse(JSON.stringify(layout)); if (!d.guvenli.length) delete d.guvenli; if (!Object.keys(d.lairs).length) delete d.lairs;
    if (!Object.keys(d.portals).length) delete d.portals; wePatch('map_layout.json', jp('haritalar', hm.id), d); markSelected(); };
  const markSelected = () => { const c = document.querySelector('.we-map-chip.on'); if (c) c.classList.add('degisti'); };

  // ---- tuval (SVG, oyun birimleri)
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('class', 'de-svg');
  svg.style.setProperty('--s', W / 21000);      // etiketlerin boyu harita ölçeğiyle
  const el = (tag, at, ...kids) => { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(at || {})) e.setAttribute(k, v); kids.forEach(k => k && e.append(k)); return e; };
  const S1 = W / 21000;            // ölçek: 2x haritada işaretler de büyür
  // tepeden işaret (images/harita_<ad>.webp, OP-011): merkez (x, y), boy oyun birimi
  const beacon = (name, x, y, size) => el('image', { href: 'images/harita_' + name + '.webp', x: x - size * S1 / 2, y: y - size * S1 / 2, width: size * S1, height: size * S1, class: 'isaret' });
  const point = e => { const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; const q = p.matrixTransform(svg.getScreenCTM().inverse()); return [Math.round(Math.max(0, Math.min(W, q.x))), Math.round(Math.max(0, Math.min(H, q.y)))]; };
  let drag = null;
  const dragStart = (e, obj, update, finished) => { e.stopPropagation(); e.preventDefault(); f.nesne = obj; drag = { update, finished, moved: false }; svg.setPointerCapture(e.pointerId); renderMapPanel(); render(); };
  svg.addEventListener('pointermove', e => { if (!drag) return; drag.moved = true; drag.update(point(e)); render(); });
  svg.addEventListener('pointerup', () => { if (drag) { const s = drag; drag = null; if (s.moved) s.bitti(); renderMapPanel(); } });
  svg.addEventListener('pointerdown', async e => {
    if (e.target !== svg && !e.target.classList.contains('we-ground')) return;
    const [x, y] = point(e);
    if (f.arac === 'guvenli') { layout.guvenli.push([x, y, 1500 * S1 | 0]); f.nesne = { tur: 'guvenli', i: layout.guvenli.length - 1 }; saveLayout(); }
    else if (f.arac === 'bolge' || f.arac === 'in') {
      const candidates = f.arac === 'bolge' ? npc.filter(g => !g.bolge) : npc;
      if (!candidates.length) return toast(f.arac === 'bolge' ? T('Bütün türlerin bölgesi var. Önce listeye uzaylı ekle.') : T('Önce listeye uzaylı ekle.'), 'info');
      const sec = candidates.length === 1 ? candidates[0] : await new Promise(res => popMenuAt(e.clientX, e.clientY, candidates.map(g => ({ label: npcName(aliens(g.tip)) + ' ×' + g.adet, ic: 'alien', fn: () => res(g) }))));
      if (!sec) return;
      if (f.arac === 'bolge') { sec.bolge = [x, y, 2500 * S1 | 0]; f.nesne = { tur: 'bolge', tip: sec.tip }; saveNpc(); }
      else { (layout.lairs[sec.tip] = layout.lairs[sec.tip] || []).push([x, y]); f.nesne = { tur: 'in', tip: sec.tip, i: layout.lairs[sec.tip].length - 1 }; saveLayout(); }
    } else { f.nesne = null; }
    renderMapPanel(); render();
  });
  const render = () => {
    fill(svg);
    svg.append(el('rect', { x: 0, y: 0, width: W, height: H, class: 'we-ground' }));
    if (f.layer.izgara) for (let x = 1000; x < W; x += 1000) svg.append(el('line', { x1: x, y1: 0, x2: x, y2: H, class: x % 5000 ? 'iz' : 'iz thick' }));
    if (f.layer.izgara) for (let y = 1000; y < H; y += 1000) svg.append(el('line', { x1: 0, y1: y, x2: W, y2: y, class: y % 5000 ? 'iz' : 'iz thick' }));
    if (f.layer.engel) hm.obstacles.forEach(([x0, y0, x1, y1]) => svg.append(el('rect', { x: x0, y: y0, width: x1 - x0, height: y1 - y0, class: 'engel' })));
    if (hm.istasyon) { const [sx, sy] = hm.istasyon; svg.append(el('circle', { cx: sx, cy: sy, r: 1800 * S1, class: 'station-area' }), beacon('istasyon', sx, sy, 1100),
      el('text', { x: sx, y: sy + 860 * S1, class: 'etiket' }, document.createTextNode(T('İstasyon')))); }
    if (hm.yapi) svg.append(beacon('gorev_verici', hm.yapi[0], hm.yapi[1], 700));
    if (f.layer.guvenli) layout.guvenli.forEach((z, i) => { const on = f.nesne?.tur === 'guvenli' && f.nesne.i === i;
      const c = el('circle', { cx: z[0], cy: z[1], r: z[2], class: 'guvenli' + (on ? ' on' : '') });
      c.addEventListener('pointerdown', e => f.arac === 'sec' && dragStart(e, { tur: 'guvenli', i }, ([x, y]) => { z[0] = x; z[1] = y; }, saveLayout));
      svg.append(c, beacon('guvenli', z[0], z[1], 520)); if (on) svg.append(handle(z, () => saveLayout())); });
    if (f.layer.bolge) npc.filter(g => g.bolge).forEach(g => { const z = g.bolge, on = f.nesne?.tur === 'bolge' && f.nesne.tip === g.tip;
      const gr = el('g', { class: 'bolge' + (on ? ' on' : '') + (aliens(g.tip)?.saldirgan ? ' saldirgan' : '') });
      gr.append(el('circle', { cx: z[0], cy: z[1], r: z[2] }), el('text', { x: z[0], y: z[1], class: 'etiket ortada' }, document.createTextNode(npcName(aliens(g.tip)) + ' ×' + g.adet)));
      gr.addEventListener('pointerdown', e => f.arac === 'sec' && dragStart(e, { tur: 'bolge', tip: g.tip }, ([x, y]) => { z[0] = x; z[1] = y; }, saveNpc));
      svg.append(gr); if (on) svg.append(handle(z, () => saveNpc())); });
    if (f.layer.in) Object.entries(layout.lairs).forEach(([tip, pts]) => pts.forEach((p, i) => { const on = f.nesne?.tur === 'in' && f.nesne.tip === tip && f.nesne.i === i;
      const pg = el('g', { class: 'in' + (on ? ' on' : '') }, el('circle', { cx: p[0], cy: p[1], r: 420 * S1, class: 'in-halo' }), beacon('in', p[0], p[1], 720));
      pg.addEventListener('pointerdown', e => f.arac === 'sec' && dragStart(e, { tur: 'in', tip, i }, ([x, y]) => { p[0] = x; p[1] = y; }, saveLayout));
      svg.append(pg, el('text', { x: p[0], y: p[1] + 620 * S1, class: 'etiket kucuk' }, document.createTextNode(npcName(aliens(tip))))); }));
    if (f.layer.portal) hm.portals.forEach(g => { const on = f.nesne?.tur === 'portal' && f.nesne.key === g.key, r = 330 * S1;
      const gr = el('g', { class: 'portal' + (on ? ' on' : '') + (layout.portals[g.key] ? ' tasindi' : '') });
      gr.append(el('circle', { cx: g.x, cy: g.y, r: r * 1.9, class: 'portal-area' }), el('circle', { cx: g.x, cy: g.y, r: r * 1.25, class: 'portal-halo' }), beacon('portal', g.x, g.y, 900),
        el('text', { x: g.x, y: g.y - r * 2.3, class: 'etiket' }, document.createTextNode('→ ' + g.hedef)));
      gr.addEventListener('pointerdown', e => f.arac === 'sec' && dragStart(e, { tur: 'portal', key: g.key }, ([x, y]) => { g.x = x; g.y = y; layout.portals[g.key] = [x, y]; }, saveLayout));
      svg.append(gr); });
  };
  // yarıçap tutamacı (seçili daire): sağ kenarından sürükle
  const handle = (z, finished) => { const t = el('circle', { cx: z[0] + z[2], cy: z[1], r: 160 * S1, class: 'tutamac' });
    t.addEventListener('pointerdown', e => dragStart(e, f.nesne, ([x, y]) => { z[2] = Math.max(200, Math.round(Math.hypot(x - z[0], y - z[1]))); }, finished)); return t; };

  const tools = h('div', { class: 'we-tools' }, h('div', { class: 'seg' }, MAP_TOOL.map(([k, name, iconEl]) => h('button', { class: f.arac === k ? 'on info' : '', title: T(name),
    onclick: e => { f.arac = k; e.currentTarget.parentNode.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === e.currentTarget)); e.currentTarget.parentNode.querySelectorAll('button').forEach(x => x.classList.toggle('info', x === e.currentTarget)); svg.dataset.arac = k; hint(); } },
      k === 'in' || k === 'guvenli' ? art('harita_' + k, 'we-tool-icon') : icon(iconEl)))),
    h('span', { class: 'we-tool-tip small muted', id: 'we-tool-tip' }), h('span', { class: 'spacer' }),
    btn('', ev => popMenu(ev.currentTarget, MAP_LAYER.map(([k, name]) => ({ label: T(name) + (f.layer[k] ? '  ✓' : ''), ic: f.layer[k] ? 'check' : 'layers', fn: () => { f.layer[k] = !f.layer[k]; render(); } }))), 'sm ghost icon', 'layers', { title: T('Katmanlar') }));
  const hint = () => { const e = $('#we-tool-tip'); if (e) e.textContent = { sec: T('Nesneleri sürükle; seçili dairenin yarıçapını kenarındaki noktadan değiştir.'),
    bolge: T('Haritaya tıkla: seçtiğin uzaylı türü bu dairenin içinde doğar.'), in: T('Haritaya tıkla: türün sabit doğma noktası (uzaylılar burada belirir).'),
    guvenli: T('Haritaya tıkla: güvenli bölge (uzaylılar saldırmaz, doğmaz).') }[f.arac]; };
  svg.dataset.arac = f.arac;
  fill(canvas, tools, h('div', { class: 'we-svg-wrap' }, svg), h('div', { class: 'we-canvas-bottom small muted' },
    h('span', null, hm.ad + ' · ' + fmtN(W) + ' × ' + fmtN(H)), h('span', { class: 'spacer' }),
    h('span', { class: 'we-legend' }, art('harita_portal'), T('Portal'), art('harita_guvenli'), T('Güvenli'), h('i', { class: 'l-zone' }), T('Doğma bölgesi'), art('harita_in'), T('İn'), h('i', { class: 'l-obstacle' }), T('Engel'))));
  hint(); render();

  // ---- sağ panel: seçili nesne ya da doğma listesi
  const renderMapPanel = () => {
    const n = f.nesne, out = [];
    if (n) {
      const back = btn(T('Seçimi bırak'), () => { f.nesne = null; renderMapPanel(); render(); }, 'sm ghost', 'arrowL');
      if (n.tur === 'portal') {
        const g = hm.portals.find(x => x.key === n.key);
        out.push(h('div', { class: 'we-subtitle' }, T('Portal → {0}', g.hedef)), position(g, v => { g.x = v[0]; g.y = v[1]; layout.portals[g.key] = v; saveLayout(); render(); }),
          layout.portals[g.key] ? btn(T('Standart yerine döndür'), () => { delete layout.portals[g.key]; saveLayout(); toast(T('Portal standart yerinde (sayfayı yenileyince görünür).'), 'info'); }, 'sm ghost', 'undo') : null);
      } else if (n.tur === 'guvenli') {
        const z = layout.guvenli[n.i];
        out.push(h('div', { class: 'we-subtitle' }, T('Güvenli bölge')), position(z, v => { z[0] = v[0]; z[1] = v[1]; saveLayout(); render(); }),
          h('div', { class: 'we-field-row' }, h('label', null, T('Yarıçap')), weNumber(z[2], v => { z[2] = v; saveLayout(); render(); }, { min: 100, max: 6000, adim: 100 })),
          btn(T('Bölgeyi sil'), () => { layout.guvenli.splice(n.i, 1); f.nesne = null; saveLayout(); renderMapPanel(); render(); }, 'sm danger', 'trash'));
      } else if (n.tur === 'bolge') {
        const g = npc.find(x => x.tip === n.tip);
        out.push(h('div', { class: 'we-subtitle' }, T('Doğma bölgesi')), h('div', { class: 'row', style: { gap: '8px' } }, npcIcon(aliens(g.tip), 32), h('b', null, npcName(aliens(g.tip)) + ' ×' + g.adet)),
          position(g.bolge, v => { g.bolge[0] = v[0]; g.bolge[1] = v[1]; saveNpc(); render(); }),
          h('div', { class: 'we-field-row' }, h('label', null, T('Yarıçap')), weNumber(g.bolge[2], v => { g.bolge[2] = v; saveNpc(); render(); }, { min: 200, max: 15000, adim: 100 })),
          h('p', { class: 'small muted' }, T('Uzaylılar bu dairenin içinde doğar ve yeniden doğar; sonra haritada dolaşırlar.')),
          btn(T('Bölgeyi kaldır (haritaya dağılsın)'), () => { delete g.bolge; f.nesne = null; saveNpc(); renderMapPanel(); render(); }, 'sm danger', 'trash'));
      } else if (n.tur === 'in') {
        const p = layout.lairs[n.tip][n.i];
        out.push(h('div', { class: 'we-subtitle' }, T('İn: {0}', npcName(aliens(n.tip)))), position(p, v => { p[0] = v[0]; p[1] = v[1]; saveLayout(); render(); }),
          h('p', { class: 'small muted' }, T('Bu türün uzaylıları yalnız inlerinde doğar (birden çok in varsa boş olanda).')),
          btn(T('İni sil'), () => { layout.lairs[n.tip].splice(n.i, 1); if (!layout.lairs[n.tip].length) delete layout.lairs[n.tip]; f.nesne = null; saveLayout(); renderMapPanel(); render(); }, 'sm danger', 'trash'));
      }
      fill(panel, h('div', { class: 'stack', style: { gap: '10px' } }, back, ...out));
      return;
    }
    const total = npc.reduce((a, g) => a + g.adet, 0);
    const row = g => { const u = aliens(g.tip);
      return h('div', { class: 'we-spawn' }, npcIcon(u, 34), h('div', { class: 'we-spawn-name' }, h('b', { title: npcName(u) }, npcName(u)),
        h('div', { class: 'small muted' }, u?.saldirgan ? T('Saldırgan') : T('Barışçıl'), g.bolge ? ' · ' + T('bölgede') : '', layout.lairs[g.tip] ? ' · ' + T('{0} in', layout.lairs[g.tip].length) : ''),
        weNumber(g.adet, v => { g.adet = v; saveNpc(); totalEl.textContent = T('{0} uzaylı', fmtN(npc.reduce((a, x) => a + x.adet, 0))); render(); }, { max: 300, width: 52 })),
        h('div', { class: 'we-spawn-action' },
          btn('', () => { if (g.bolge) { f.nesne = { tur: 'bolge', tip: g.tip }; } else { g.bolge = [W / 2 | 0, H / 2 | 0, 2500 * S1 | 0]; f.nesne = { tur: 'bolge', tip: g.tip }; saveNpc(); } renderMapPanel(); render(); },
            'sm ghost icon' + (g.bolge ? ' on' : ''), 'target', { title: g.bolge ? T('Bölgeyi seç') : T('Doğma bölgesi ekle') }),
          btn('', () => { npc.splice(npc.indexOf(g), 1); saveNpc(); renderMapPanel(); render(); }, 'sm ghost icon', 'x', { title: T('Listeden çıkar') })));
    };
    const totalEl = h('span', { class: 'badge info' }, T('{0} uzaylı', fmtN(total)));
    const std = hm.standart;
    fill(panel, h('div', { class: 'stack', style: { gap: '10px' } },
      h('div', { class: 'row between' }, h('div', { class: 'we-subtitle', style: { margin: 0 } }, T('Doğan uzaylılar')), totalEl),
      npc.length ? h('div', { class: 'stack', style: { gap: '6px' } }, npc.map(row)) : h('div', { class: 'small muted' }, T('Bu haritada uzaylı doğmuyor.')),
      btn(T('Uzaylı ekle'), async () => { const u = await pickAlien(T('Haritaya uzaylı ekle')); if (!u) return;
        const v = npc.find(g => g.tip === u.tip); if (v) v.adet += 5; else npc.push({ tip: u.tip, adet: 10 }); saveNpc(); renderMapPanel(); render(); }, 'sm primary', 'plus'),
      h('div', { class: 'we-subtitle' }, T('Bonus kutuları')),
      h('div', { class: 'we-field-row' }, art('kaynak_kredi', 'we-reward-icon'), weNumber(hm.bonus_kutu, v => { hm.bonus_kutu = v; wePatch('npc.json', jp('haritalar', hm.id, 'bonus_kutu'), v); markSelected(); }, { max: 300, width: 60 }),
        weStd(std.bonus_kutu, hm.bonus_kutu, () => { hm.bonus_kutu = std.bonus_kutu; wePatch('npc.json', jp('haritalar', hm.id, 'bonus_kutu'), std.bonus_kutu); renderMapPanel(); })),
      h('p', { class: 'small muted' }, T('Adetler Oyun Ayarları\'ndaki uzaylı sayısı ve kutu bolluğu çarpanlarıyla çarpılır.')),
      oreBlock(hm, markSelected),
      (hm.degisti.npc || hm.degisti.duzen || hm.degisti.bonus_kutu || hm.cevher.ozel) ? btn(T('Haritayı standarda döndür'), async () => {
        if (!await confirmBox(T('{0} standarda dönsün mü?', hm.ad), T('Doğma listesi, bölgeler, inler, güvenli bölgeler, portal yerleri ve cevherler standart hâline döner.'), { ok: T('Standarda döndür'), danger: true })) return;
        for (const [d, y] of [['npc.json', jp('haritalar', hm.id, 'npc')], ['npc.json', jp('haritalar', hm.id, 'bonus_kutu')], ['map_layout.json', jp('haritalar', hm.id)], ['items.json', hm.cevher.yol]]) await weRevert(d, y);
        weRenderSection(); }, 'sm ghost', 'undo') : null));
  };
  const position = (v, cb) => h('div', { class: 'we-field-row' }, h('label', null, T('Konum')), weNumber(v[0], x => cb([x, v[1]]), { max: W, adim: 100, width: 76 }),
    weNumber(v[1], y => cb([v[0], y]), { max: H, adim: 100, width: 76 }));
  renderMapPanel();
}
function popMenuAt(x, y, items) {
  const a = h('span', { style: { position: 'fixed', left: x + 'px', top: y + 'px', width: '1px', height: '1px' } }); document.body.append(a);
  popMenu(a, items); setTimeout(() => a.remove(), 0);
}

// ================================================================== GÖREVLER
const QU_KIND = { 6: ['alien', N('Öldür'), 'npc'], 27: ['alien', N('Öldür (toplam)'), 'npc'], 67: ['box', N('Topla'), 'esya'], 34: ['map', N('Haritaya git'), 'harita'],
  52: ['cart', N('Cevher sat'), 'cevher'], 55: ['gift', N('Bonus kutusu topla'), null], 51: ['box', N('Kargo kutusu topla'), null], 28: ['users', N('Oyuncu yen'), null],
  2: ['clock', N('Süre sınırı'), 'sure'], 63: ['clock', N('Gerçek zamanlı süre'), 'sure'], 3: ['clock', N('Haritada kal'), 'sure'], 62: ['flag', N('Görev vericiye dön'), null],
  53: ['star', N('Seviyeye ulaş'), null], 35: ['x', N('Öl'), null], 42: ['link', N('Portaldan geç'), null], 80: ['ring', N('Galaksi Kapısı bitir'), null],
  13: ['zap', N('Yol al'), null], 7: ['zap', N('Hasar ver'), null], 9: ['shield', N('Hasar al'), null] };
const QU_FILTER = [['hepsi', N('Hepsi')], ['ana', N('Ana görevler')], ['tekrar', N('Günlük ve haftalık')], ['etkinlik', N('Etkinlik')], ['degisti', N('Değiştirilenler')], ['yeni', N('Yeni')], ['kapali', N('Kapalı')]];
const ORE_OLD = { 1: 'resource_ore_prometium', 2: 'resource_ore_endurium', 3: 'resource_ore_terbium', 4: 'resource_ore_xenomit', 11: 'resource_ore_prometid',
  12: 'resource_ore_duranium', 13: 'resource_ore_promerium', 14: 'resource_ore_seprom', 15: 'resource_ore_palladium', 42: 'resource_ore_osmium' };

// görev eşleşmesindeki harita: "@1-1" -> 1-1; "@own X-3" -> kendi X-3 (firmaya göre çözülür)
function mapLabel(x) {
  x = String(x).replace(/^@/, '');
  const m = x.match(/^(own|enemy|any) (.+)$/);
  return m ? T({ own: N('Kendi {0}'), enemy: N('Düşman {0}'), any: N('Herhangi {0}') }[m[1]], m[2]) : x;
}
// koşulun hedefi (ne): uzaylı, eşya, cevher, harita adları
function conditionTarget(c) {
  const t = QU_KIND[c.tur], es = c.matches || [];
  if (!t) return '';
  if (t[2] === 'npc') return es.map(k => npcName((DE.uzayli || []).find(u => String(u.npc_kimlik) === String(k))) || k).join(', ') || T('uzaylı');
  if (t[2] === 'esya') return es.map(itemName).join(', ');
  if (t[2] === 'cevher') return es.map(k => ORE_OLD[k] ? itemName(ORE_OLD[k]) : k).join(', ');
  if (t[2] === 'harita') return es.map(mapLabel).join(', ');
  return '';
}
function conditionText(c) {
  const t = QU_KIND[c.tur];
  if (!t) return T('Özel koşul (tür {0})', c.tur);
  if (t[2] === 'harita') return conditionTarget(c);
  const target = t[2] === 'sure' ? fmtDur(c.hedef / 1000) : fmtN(c.hedef), ne = conditionTarget(c);
  return ne ? T('{0} {1}', target, ne) : target;
}

async function weQuests(area, b) {
  await alienList();
  const r = await act(() => api('/api/dunya/section?bolum=gorevler&dunya=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'gorevler') return;
  const f = DE.sec.quests || (DE.sec.quests = { q: '', filter_by: 'ana', secili: null, sinir: 150 });
  const entries = h('div', { class: 'we-quest-list' }), detail = h('div', { class: 'we-detail' });
  const eligible = g => ({ hepsi: true, ana: !g.havuz && !g.etkinlik && g.kinds.includes(2), tekrar: g.havuz || g.kinds.some(t => t === 3 || t === 6),
    etkinlik: g.etkinlik || g.kinds.includes(5), degisti: g.degisti, yeni: g.yeni, kapali: g.kapali })[f.filter_by];
  const render = () => {
    const s = f.q.trim().toLowerCase();
    const l = r.gorevler.filter(g => eligible(g) && (!s || g.ad.toLowerCase().includes(s) || String(g.id) === s));
    fill(entries, ...l.slice(0, f.sinir).map(g => h('button', { type: 'button', class: 'we-quest' + (f.secili === g.id ? ' on' : '') + (g.degisti ? ' degisti' : '') + (g.kapali ? ' kapali' : ''),
      onclick: () => { f.secili = g.id; render(); } }, h('span', { class: 'we-lv' }, g.seviye || '—'),
      h('div', { class: 'we-quest-name' }, h('b', null, g.ad), h('div', { class: 'small muted ellipsis' }, g.conditions.slice(0, 3).map(c => (QU_KIND[c.tur] ? T(QU_KIND[c.tur][1]) : '?') + ' ' + conditionText(c)).join(' · '))),
      h('div', { class: 'we-quest-reward' }, g.oduller.slice(0, 3).map(([l]) => gameIcon(l, 22, null, 'gift'))),
      g.yeni ? badge(T('Yeni'), 'orange') : g.kapali ? badge(T('Kapalı'), '') : null)),
      l.length > f.sinir ? h('button', { type: 'button', class: 'btn sm we-more', onclick: () => { f.sinir += 300; render(); } }, T('{0} görev daha', fmtN(l.length - f.sinir))) : null,
      !l.length ? h('div', { class: 'empty small muted' }, T('Eşleşen görev yok.')) : null);
    if (!f.secili && l[0]) f.secili = l[0].id;
    if (f.secili) questDetail(f.secili, detail, g2 => { Object.assign(r.gorevler.find(x => x.id === g2.id) || {}, g2); render(); });
    else fill(detail, h('div', { class: 'empty muted' }, T('Soldan bir görev seç.')));
  };
  const seg = h('div', { class: 'seg' }, QU_FILTER.map(([k, name]) => h('button', { class: f.filter_by === k ? 'on info' : '', onclick: () => { f.filter_by = k; f.secili = null; weRenderSection(); } }, T(name))));
  fill(area, h('div', { class: 'card' }, weTitle(b, h('input', { class: 'input', style: { width: '200px' }, placeholder: T('Görev ara…'), value: f.q, oninput: e => { f.q = e.target.value; render(); } }),
    btn(T('Yeni görev'), () => newQuest(), 'primary', 'plus')), h('div', { style: { margin: '12px 0' } }, seg), h('div', { class: 'we-two-col genis' }, entries, detail)));
  render();
}

async function questDetail(qid, box, updated) {
  if (box.dataset.q !== String(qid)) fill(box, h('div', { class: 'empty' }, h('div', { class: 'spin', style: { margin: '30px auto' } })));
  box.dataset.q = qid;
  const g = await act(() => api('/api/dunya/gorev?dunya=' + encodeURIComponent(DE.did) + '&id=' + qid)); if (!g || box.dataset.q !== String(qid)) return;
  const std = g.standart;
  const save = async (changes, regenerate = true) => {
    weSaveStatus('kaydediliyor');
    const x = await act(() => api('/api/dunya/gorev', { dunya: DE.did, id: qid, changes }));
    if (!x) return weSaveStatus('hazir');
    const summary = await api('/api/dunya?dunya=' + encodeURIComponent(DE.did)).catch(() => null); if (summary) { DE.ozet = summary; weMenuCount(); weWarning(); }
    weSaveStatus('kaydedildi'); updated({ id: x.id, oduller: x.oduller, seviye: x.seviye, conditions: x.conditions.map(c => ({ tur: c.tur, hedef: c.hedef, matches: c.matches })), degisti: x.degisti, kapali: x.kapali, ad: x.ad });
    if (regenerate) questDetail(qid, box, updated);
  };
  let timer = null;
  const delay = (fn, ms = 500) => { clearTimeout(timer); weSaveStatus('kaydediliyor'); timer = setTimeout(fn, ms); };
  const condition = (c, i) => {
    const t = QU_KIND[c.tur] || ['info', N('Özel koşul'), null], kind = t[2], sc = std?.conditions?.[i];
    const subMaps = (c.sub.find(a => a.tur === 77) || {}).matches || [];
    const pickTarget = async () => {
      let es = null;
      if (kind === 'npc') { const u = await pickAlien(T('Hangi uzaylı?'), { with_id: true }); if (u) es = [String(u.npc_kimlik)]; }
      else if (kind === 'esya') { const l = await pickItem(T('Hangi eşya toplanacak?')); if (l) es = [l]; }
      else if (kind === 'cevher') { const l = await new Promise(res => popMenu(box.querySelector('.we-condition[data-i="' + i + '"] .de-kosul-hedef'), Object.entries(ORE_OLD).map(([k, loot]) => ({ label: itemName(loot), ic: 'box', fn: () => res([k]) })))); es = l; }
      else if (kind === 'harita') { const l = await pickMap(T('Hangi harita?'), [], { coklu: false }); if (l) es = l; }
      if (es) save({ conditions: [{ id: c.id, matches: es }] });
    };
    const mapRestriction = async () => { const l = await pickMap(T('Yalnız bu haritalarda'), subMaps.map(x => String(x).replace(/^@/, ''))); if (l) save({ conditions: [{ id: c.id, harita: l }] }); };
    return h('div', { class: 'we-condition', 'data-i': i }, h('div', { class: 'we-condition-icon' }, icon(t[0])),
      h('div', { class: 'we-condition-body' }, h('div', { class: 'small muted' }, T(t[1])),
        h('div', { class: 'row wrap', style: { gap: '8px' } },
          kind === 'sure' ? h('span', { class: 'we-condition-text' }, fmtDur(c.hedef / 1000)) : c.tur === 34 ? null : weNumber(c.hedef, v => delay(() => save({ conditions: [{ id: c.id, hedef: v }] }, false)), { min: 0, max: 1e7, width: 70 }),
          kind && kind !== 'sure' ? h('button', { type: 'button', class: 'chip link de-kosul-hedef', onclick: pickTarget, title: T('Değiştir') },
            kind === 'esya' ? gameIcon(c.matches[0], 20, null, 'box') : kind === 'npc' ? npcIcon((DE.uzayli || []).find(u => String(u.npc_kimlik) === String(c.matches[0])), 20) : icon(t[0]),
            conditionTarget(c) || T('Seç'), icon('edit')) : null,
          ['npc', 'esya', null].includes(kind) && c.tur !== 62 ? h('button', { type: 'button', class: 'chip link', onclick: mapRestriction, title: T('Harita kısıtı') }, icon('map'),
            subMaps.length ? subMaps.map(mapLabel).join(', ') : T('Her haritada')) : null,
          sc && sc.hedef !== c.hedef && kind !== 'sure' ? weStd(sc.hedef, c.hedef, () => save({ conditions: [{ id: c.id, hedef: sc.hedef }] })) : null)));
  };
  const reward = ([l, n], i) => h('div', { class: 'we-reward-chip' }, gameIcon(l, 36, null, 'gift'), h('div', { class: 'we-reward-chip-name' }, h('div', { class: 'small ellipsis', title: l }, itemName(l)),
    weNumber(n, v => { g.oduller[i][1] = Math.max(1, v); delay(() => save({ oduller: g.oduller }, false)); }, { min: 1, max: 1e9, width: 84 })),
    btn('', () => { g.oduller.splice(i, 1); save({ oduller: g.oduller }); }, 'sm ghost icon', 'x', { title: T('Ödülü kaldır') }));
  const fast = [['currency_credits', 10000], ['currency_uridium', 500], ['currency_experience', 5000], ['currency_honour', 100]];
  fill(box, h('div', { class: 'stack', style: { gap: '14px' } },
    h('div', { class: 'we-detail-head' }, h('div', { class: 'we-quest-badge' }, icon('target')), h('div', { style: { flex: 1, minWidth: 0 } },
      g.yeni ? h('input', { class: 'input we-name-input', value: g.ad, maxlength: 60, onchange: e => save({ ad: e.target.value }) }) : h('div', { class: 'de-h3' }, g.ad),
      h('div', { class: 'small muted' }, T('Görev {0}', g.id), g.yeni ? ' · ' + T('Bu dünyaya ait') : '', g.degisti && !g.yeni ? ' · ' + T('değiştirildi') : ''))),
    h('div', { class: 'we-subtitle' }, T('Oyundaki metin')),
    field(T('Başlık'), h('input', { class: 'input', value: g.baslik, maxlength: 80, placeholder: g.yeni ? T('Başlık yok') : T('Oyunun kendi başlığı'),
      onchange: e => save({ baslik: e.target.value }) })),
    field(T('Açıklama'), h('textarea', { class: 'input', rows: 3, maxlength: 600, placeholder: T('Oyunun kendi açıklaması'), onchange: e => save({ aciklama: e.target.value }) }, g.aciklama)),
    h('div', { class: 'small dim' }, T('Boş bırakırsan oyunun kendi metni görünür. Başlık ve açıklama oyunda OpenOrbit eklentisiyle (BepInEx) gösterilir.')),
    h('div', { class: 'we-field-row' }, h('label', null, T('Gereken seviye')), weNumber(g.seviye, v => delay(() => save({ seviye: v }, false)), { min: 0, max: 40, width: 56 }),
      std ? weStd(std.seviye, g.seviye, () => save({ seviye: std.seviye })) : null),
    h('div', { class: 'we-field-row' }, h('label', null, T('Görev listede')), h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: !g.kapali, onchange: e => save({ kapali: !e.target.checked }) }), h('span')),
      h('span', { class: 'small muted' }, g.kapali ? T('Kapalı: görev vericide görünmez (sürüyorsa bitirilebilir).') : T('Açık: koşulları tutan pilot alabilir.'))),
    h('div', { class: 'we-subtitle' }, T('Hedefler')),
    g.conditions.length ? h('div', { class: 'stack', style: { gap: '8px' } }, g.conditions.map(condition)) : h('div', { class: 'small muted' }, T('Bu görevin hedefi yok.')),
    h('div', { class: 'we-subtitle' }, T('Ödüller')),
    h('div', { class: 'we-rewards' }, g.oduller.map(reward),
      h('button', { type: 'button', class: 'we-reward-add', onclick: async () => { const l = await pickItem(T('Ödül ekle')); if (!l) return; g.oduller.push([l, l.startsWith('currency_') ? 1000 : 1]); save({ oduller: g.oduller }); } }, icon('plus'), T('Ödül ekle'))),
    h('div', { class: 'chips' }, fast.map(([l, n]) => h('button', { type: 'button', class: 'chip link', onclick: () => { const v = g.oduller.find(o => o[0] === l); if (v) v[1] += n; else g.oduller.push([l, n]); save({ oduller: g.oduller }); } },
      icon('plus'), fmtN(n) + ' ' + itemName(l)))),
    std && JSON.stringify(std.oduller) !== JSON.stringify(g.oduller) ? h('div', null, weStd(std.oduller, g.oduller, () => save({ oduller: std.oduller }), o => T('{0} ödül', o.length))) : null,
    h('div', { class: 'we-subtitle' }, T('Önkoşullar')),
    h('div', { class: 'chips' }, g.onceki.map(x => h('span', { class: 'chip' }, icon('target'), g.adlar[x] || x,
      h('button', { type: 'button', class: 'we-chip-x', onclick: () => save({ onceki: g.onceki.filter(y => y !== x) }) }, icon('x')))),
      h('button', { type: 'button', class: 'chip link', onclick: async () => { const q = await pickQuest(); if (q) save({ onceki: [...g.onceki, q.id] }); } }, icon('plus'), T('Önkoşul ekle'))),
    h('div', { class: 'row wrap', style: { gap: '8px', marginTop: '6px' } },
      g.degisti && !g.yeni ? btn(T('Standarda döndür'), async () => { if (await weRevert(_quFile(g), jp('gorevler', g.id))) { updated({ id: g.id, degisti: false }); questDetail(qid, box, updated); } }, 'sm ghost', 'undo') : null,
      g.yeni ? btn(T('Görevi sil'), async () => {
        if (!await confirmBox(T('Görev silinsin mi?'), T('Bu dünyaya eklediğin görev silinir.'), { ok: T('Sil'), danger: true })) return;
        const r = await wePatch('quest_extras.json', jp('gorevler', g.id), { $delete: true }, { ms: 0 }); if (r) { DE.sec.quests.secili = null; weRenderSection(); } }, 'sm danger', 'trash') : null)));
}
const _quFile = g => g.kaynak === 'ana' ? 'quests.json' : 'quest_extras.json';

async function pickQuest() {
  const r = await act(() => api('/api/dunya/section?bolum=gorevler&dunya=' + encodeURIComponent(DE.did))); if (!r) return null;
  return new Promise(res => {
    let q = '', done = false;
    const l = h('div', { class: 'we-quest-list kisa' });
    const render = () => { const s = q.trim().toLowerCase();
      fill(l, ...r.gorevler.filter(g => !s || g.ad.toLowerCase().includes(s)).slice(0, 120).map(g => h('button', { type: 'button', class: 'we-quest', onclick: () => { done = true; m.close(); res(g); } },
        h('span', { class: 'we-lv' }, g.seviye || '—'), h('div', { class: 'we-quest-name' }, h('b', null, g.ad))))); };
    const m = modal({ title: T('Önkoşul görev'), onclose: () => { if (!done) res(null); }, body: h('div', { class: 'stack', style: { gap: '10px' } },
      h('input', { class: 'input', placeholder: T('Görev ara…'), oninput: e => { q = e.target.value; render(); } }), l) });
    render();
  });
}

// yeni görev sihirbazı: 1 hedefler, 2 ödüller, 3 ad ve seviye
const QU_TEMPLATE = [['avla', 'alien', N('Avla'), N('Uzaylı öldür')], ['topla', 'box', N('Topla'), N('Eşya ya da cevher topla')], ['kesif', 'map', N('Keşfet'), N('Bir haritaya git')],
  ['sat', 'cart', N('Ticaret'), N('Cevher sat')], ['kutu', 'gift', N('Bonus kutusu'), N('Bonus kutusu topla')], ['kargo', 'box', N('Kargo'), N('Kargo kutusu topla')]];
function newQuest() {
  const g = { ad: '', seviye: 1, hedefler: [], oduller: [['currency_credits', 10000], ['currency_experience', 2000]] };
  let step = 0;
  const body = h('div'), sub = h('div', { class: 'foot' });
  const m = modal({ title: T('Yeni görev'), wide: true, body: body });
  m.box.append(sub);
  const targetRow = (x, i) => {
    const s = QU_TEMPLATE.find(y => y[0] === x.tur);
    const sec = async () => {
      if (x.tur === 'avla') { const u = await pickAlien(T('Hangi uzaylı?'), { with_id: true }); if (u) { x.matches = [String(u.npc_kimlik)]; x.etiket = npcName(u); x.ikon = u; } }
      else if (x.tur === 'topla') { const l = await pickItem(T('Hangi eşya toplanacak?')); if (l) { x.matches = [l]; x.etiket = itemName(l); x.loot = l; } }
      else if (x.tur === 'sat') { const l = await new Promise(res => popMenu(body.querySelector('[data-h="' + i + '"] .de-kosul-hedef'), Object.entries(ORE_OLD).map(([k, loot]) => ({ label: itemName(loot), ic: 'box', fn: () => res([k, loot]) })))); if (l) { x.matches = [l[0]]; x.etiket = itemName(l[1]); x.loot = l[1]; } }
      else if (x.tur === 'kesif') { const l = await pickMap(T('Hangi harita?'), [], { coklu: false }); if (l) { x.matches = l; x.etiket = l[0]; } }
      render();
    };
    const selectable = ['avla', 'topla', 'sat', 'kesif'].includes(x.tur);
    return h('div', { class: 'we-condition', 'data-h': i }, h('div', { class: 'we-condition-icon' }, icon(s[1])), h('div', { class: 'we-condition-body' }, h('div', { class: 'small muted' }, T(s[3])),
      h('div', { class: 'row wrap', style: { gap: '8px' } }, x.tur !== 'kesif' ? weNumber(x.hedef, v => { x.hedef = Math.max(1, v); }, { min: 1, max: 1e7, width: 70 }) : null,
        selectable ? h('button', { type: 'button', class: 'chip link de-kosul-hedef' + (x.matches?.length ? '' : ' bos'), onclick: sec },
          x.loot ? gameIcon(x.loot, 20, null, 'box') : x.ikon ? npcIcon(x.ikon, 20) : icon(s[1]), x.etiket || T('Seç'), icon('edit')) : null,
        x.tur !== 'kesif' ? h('button', { type: 'button', class: 'chip link', onclick: async () => { const l = await pickMap(T('Yalnız bu haritalarda'), x.harita || []); if (l) { x.harita = l; render(); } } },
          icon('map'), x.harita?.length ? x.harita.join(', ') : T('Her haritada')) : null)),
      btn('', () => { g.hedefler.splice(i, 1); render(); }, 'sm ghost icon', 'x'));
  };
  const render = () => {
    const steps = h('div', { class: 'we-steps' }, [N('Hedefler'), N('Ödüller'), N('Ad ve seviye')].map((a, i) => h('div', { class: 'we-step' + (i === step ? ' on' : i < step ? ' bitti' : '') }, h('b', null, i + 1), T(a))));
    let iconEl;
    if (step === 0) iconEl = [h('p', { class: 'desc' }, T('Pilot ne yapsın? Bir ya da birkaç hedef ekle; hepsi tamamlanınca görev biter.')),
      h('div', { class: 'we-templates' }, QU_TEMPLATE.map(([k, icon2, name, is_open]) => h('button', { type: 'button', class: 'we-template', onclick: () => {
        g.hedefler.push({ tur: k, hedef: k === 'kesif' ? 1 : k === 'avla' ? 20 : k === 'sat' ? 100 : 10, matches: [] }); render();
        if (['avla', 'topla', 'kesif'].includes(k)) setTimeout(() => body.querySelector('[data-h="' + (g.hedefler.length - 1) + '"] .de-kosul-hedef')?.click(), 50); } },
        icon(icon2), h('b', null, T(name)), h('span', { class: 'small muted' }, T(is_open))))),
      g.hedefler.length ? h('div', { class: 'stack', style: { gap: '8px', marginTop: '14px' } }, g.hedefler.map(targetRow)) : null];
    else if (step === 1) iconEl = [h('p', { class: 'desc' }, T('Görev bitince pilot ne kazansın?')),
      h('div', { class: 'we-rewards' }, g.oduller.map(([l, n], i) => h('div', { class: 'we-reward-chip' }, gameIcon(l, 36, null, 'gift'), h('div', { class: 'we-reward-chip-name' }, h('div', { class: 'small ellipsis' }, itemName(l)),
        weNumber(n, v => { g.oduller[i][1] = Math.max(1, v); }, { min: 1, max: 1e9, width: 84 })), btn('', () => { g.oduller.splice(i, 1); render(); }, 'sm ghost icon', 'x'))),
        h('button', { type: 'button', class: 'we-reward-add', onclick: async () => { const l = await pickItem(T('Ödül ekle')); if (l) { g.oduller.push([l, l.startsWith('currency_') ? 1000 : 1]); render(); } } }, icon('plus'), T('Ödül ekle')))];
    else iconEl = [field(T('Görevin adı'), h('input', { class: 'input', value: g.ad, maxlength: 60, placeholder: T('Örn. Streuner Avı'), oninput: e => { g.ad = e.target.value; } })),
      h('div', { class: 'we-field-row' }, h('label', null, T('Gereken seviye')), weNumber(g.seviye, v => { g.seviye = v; }, { min: 1, max: 40, width: 56 })),
      h('div', { class: 'small muted' }, T('Görev, firmanın görev vericisinde (istasyon) listelenir; ad oyunda görevin başlığı olur.'))];
    fill(body, h('div', { class: 'stack', style: { gap: '12px' } }, steps, ...iconEl));
    const missing = step === 0 && (!g.hedefler.length || g.hedefler.some(x => ['avla', 'topla', 'sat', 'kesif'].includes(x.tur) && !x.matches?.length));
    fill(sub, btn(step ? T('Geri') : T('Vazgeç'), () => { if (step) { step--; render(); } else m.close(); }, 'ghost', step ? 'arrowL' : null),
      step < 2 ? btn(T('İleri'), () => { step++; render(); }, 'primary', 'arrowR', { disabled: missing, title: missing ? T('Her hedef için ne yapılacağını seç.') : null })
        : btn(T('Görevi oluştur'), async () => {
          const x = await act(() => api('/api/dunya/new_quest', { dunya: DE.did, ad: g.ad, seviye: g.seviye, hedefler: g.hedefler.map(y => ({ tur: y.tur, hedef: y.hedef, matches: y.matches, harita: y.harita })), oduller: g.oduller }), T('Görev oluşturuldu.'));
          if (!x) return;
          m.close(); DE.sec.quests = { q: '', filter_by: 'yeni', secili: x.id, sinir: 150 };
          const summary = await api('/api/dunya?dunya=' + encodeURIComponent(DE.did)).catch(() => null); if (summary) { DE.ozet = summary; weMenuCount(); weWarning(); }
          weRenderSection();
        }, 'primary', 'check'));
  };
  render();
}

// ================================================================== MAĞAZA
async function weShop(area, b) {
  const r = await act(() => api('/api/dunya/section?bolum=magaza&dunya=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'magaza') return;
  const cats = Object.keys(r.categories);
  if (!cats.length) return fill(area, h('div', { class: 'card' }, weTitle(b), h('div', { class: 'empty muted' }, T('Mağaza kataloğu bulunamadı (data/yanitlar.json).'))));
  const f = DE.sec.shop || (DE.sec.shop = { multiplier: cats[0], q: '', filter_by: 'hepsi' });
  if (!cats.includes(f.multiplier)) f.multiplier = cats[0];
  const grid = h('div', { class: 'shop-grid we-shop' });
  const priceText = (u, p) => fmtN(u) + (p === 'C' ? ' C.' : ' U.');
  const render = () => {
    const s = f.q.trim().toLowerCase();
    const l = r.categories[f.multiplier].filter(it => (f.filter_by === 'hepsi' || (f.filter_by === 'degisti' ? it.dunya : it.dunya?.on_sale === false)) && (!s || itemName(it.lootId).toLowerCase().includes(s) || it.lootId.includes(s)));
    fill(grid, ...l.map(it => { const d = it.dunya || {}, closed = d.on_sale === false, changed = d.fiyat != null;
      return h('button', { type: 'button', class: 'shop-card we-shop-card' + (closed ? ' kapali' : '') + (it.dunya ? ' degisti' : ''), onclick: () => editProduct(it, render) },
        gameIcon(it.lootId, 64, null, 'cart'), h('div', { class: 'shop-name', title: it.lootId }, itemName(it.lootId)),
        h('div', { class: 'shop-price ' + ((changed ? d.currency : it.currency) === 'C' ? 'cred' : 'uri') }, closed ? T('Satışta değil') : priceText(changed ? d.fiyat : it.fiyat, changed ? d.currency : it.currency)),
        changed && !closed ? h('div', { class: 'small dim we-strikethrough' }, priceText(it.fiyat, it.currency)) : null); }),
      !l.length ? h('div', { class: 'empty small muted' }, T('Ürün yok.')) : null);
  };
  const CAT = typeof SHP_CATEGORY !== 'undefined' ? SHP_CATEGORY : {};
  fill(area, h('div', { class: 'stack' }, h('div', { class: 'card' },
    weTitle(b, h('input', { class: 'input', style: { width: '180px' }, placeholder: T('Ara…'), value: f.q, oninput: e => { f.q = e.target.value; render(); } }),
      btn(T('Toplu fiyat'), () => bulkPrice(r.categories[f.multiplier], render), 'sm', 'sliders')),
    h('div', { class: 'row wrap', style: { gap: '10px', marginTop: '12px' } },
      h('div', { class: 'seg' }, cats.map(c => h('button', { class: c === f.multiplier ? 'on info' : '', onclick: () => { f.multiplier = c; weRenderSection(); } }, CAT[c] ? T(CAT[c]) : c,
        r.categories[c].some(it => it.dunya) ? h('span', { class: 'we-dot' }) : null))),
      h('div', { class: 'seg' }, [['hepsi', N('Hepsi')], ['degisti', N('Değiştirilenler')], ['kapali', N('Satıştan kaldırılanlar')]].map(([k, name]) =>
        h('button', { class: f.filter_by === k ? 'on info' : '', onclick: () => { f.filter_by = k; weRenderSection(); } }, T(name))))),
    h('p', { class: 'small muted', style: { margin: '10px 0 0' } }, T('Oyun Ayarları\'ndaki mağaza fiyatı çarpanı bu fiyatların üstüne uygulanır. Dronların ve seviyeli P.E.T. ürünlerinin fiyatı kendi kuralıyla işler.'))),
    grid));
  render();
}

function editProduct(it, refresh) {
  const d = Object.assign({}, it.dunya || {}), fixed = it.sabit;
  let price = d.fiyat ?? it.fiyat, currency = d.currency || it.currency, on_sale = d.on_sale !== false;
  const save = async () => {
    const value = {}; if (!fixed && (price !== it.fiyat || currency !== it.currency)) { value.fiyat = price; value.currency = currency; } if (!on_sale) value.on_sale = false;
    const empty = !Object.keys(value).length;
    const r = empty ? await weRevert('magaza', jp('urunler', it.lootId)) : await wePatch('magaza', jp('urunler', it.lootId), value, { ms: 0 });
    if (r) { it.dunya = empty ? null : value; refresh(); m.close(); }
  };
  const seg = h('div', { class: 'seg' }, [['C', N('Kredi')], ['U', N('Uridyum')]].map(([k, name]) => h('button', { class: currency === k ? 'on info' : '', disabled: fixed,
    onclick: e => { currency = k; seg.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === e.currentTarget)); seg.querySelectorAll('button').forEach(x => x.classList.toggle('info', x === e.currentTarget)); } }, T(name))));
  const m = modal({ title: itemName(it.lootId), sub: it.lootId, body: h('div', { class: 'stack', style: { gap: '14px' } },
    h('div', { class: 'row', style: { gap: '14px' } }, gameIcon(it.lootId, 72, null, 'cart'), h('div', { class: 'small muted' }, T('Standart fiyat: {0}', fmtN(it.fiyat) + (it.currency === 'C' ? ' C.' : ' U.')))),
    fixed ? h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Bu ürünün fiyatı kendi kuralıyla hesaplanır (dron sayısı, P.E.T. seviyesi); yalnız satıştan kaldırabilirsin.'))) : null,
    h('div', { class: 'we-field-row' }, h('label', null, T('Fiyat')), weNumber(price, v => { price = v; }, { min: 0, max: 1e10, adim: currency === 'C' ? 1000 : 10, width: 130 }), seg),
    h('div', { class: 'we-field-row' }, h('label', null, T('Satışta')), h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: on_sale, onchange: e => { on_sale = e.target.checked; } }), h('span')),
      h('span', { class: 'small muted' }, T('Kapalıysa mağazada görünmez, satın alınamaz.')))),
    foot: [it.dunya ? btn(T('Standarda döndür'), async () => { if (await weRevert('magaza', jp('urunler', it.lootId))) { it.dunya = null; refresh(); m.close(); } }, 'ghost', 'undo') : null,
      h('span', { class: 'spacer' }), btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Kaydet'), save, 'primary', 'check')] });
}

function bulkPrice(products, refresh) {
  let percent = 100;
  const m = modal({ title: T('Toplu fiyat'), sub: T('Bu kategorideki ürünlerin fiyatını standart fiyatın yüzdesine çeker.'), body: h('div', { class: 'stack', style: { gap: '12px' } },
    h('div', { class: 'we-field-row' }, h('label', null, T('Standart fiyatın')), weNumber(percent, v => { percent = v; }, { min: 0, max: 1000, adim: 10, width: 70 }), h('span', null, '%')),
    h('div', { class: 'chips' }, [25, 50, 75, 150, 200].map(p => h('button', { type: 'button', class: 'chip link', onclick: e => { percent = p; e.currentTarget.closest('.body').querySelector('input').value = p; } }, '%' + p)))),
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Uygula'), async () => {
      m.close(); const l = products.filter(it => !it.sabit && it.dunya?.on_sale !== false);
      for (const it of l) {
        const value = { fiyat: Math.round(it.fiyat * percent / 100), currency: it.currency };
        const r = percent === 100 ? await weRevert('magaza', jp('urunler', it.lootId)) : await act(() => api('/api/dunya/yama', { dunya: DE.did, dosya: 'magaza', yol: jp('urunler', it.lootId), value }));
        if (r) { it.dunya = percent === 100 ? null : value; DE.ozet = Object.assign(DE.ozet, r); }
      }
      weMenuCount(); weWarning(); weSaveStatus('kaydedildi'); toast(T('{0} ürünün fiyatı güncellendi.', l.length), 'ok'); refresh();
    }, 'primary', 'check')] });
}

// ================================================================== AÇIK ARTIRMA
const WE_AUCTION_KIND = [['hour', N('Saatlik')], ['day', N('Günlük')], ['week', N('Haftalık')]];
async function weAuction(area, b) {
  const r = await act(() => api('/api/dunya/section?bolum=muzayede&dunya=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'muzayede') return;
  const lots = r.lotlar;
  const save = () => wePatch('social.json', jp('muzayede', 'lotlar'), lots.map(l => [l.loot, l.grup, l.tur, l.adet, l.anlik, l.fiyat]));
  const groupOf = loot => loot.startsWith('ammunition_laser') ? 'battery' : loot.startsWith('ammunition_rocket') ? 'rocket' : loot.startsWith('ship_') ? 'ship'
    : loot.startsWith('drone_') ? 'drone' : loot.startsWith('equipment_') ? 'equipment' : loot.startsWith('booster_') ? 'booster' : 'other';
  const f = DE.sec.auction || (DE.sec.auction = { tur: 'hour', q: '' });
  const columns = h('div', { class: 'stack', style: { gap: '10px' } });
  const render = () => {
    const s = f.q.trim().toLowerCase(), ls = lots.filter(l => l.tur === f.tur && (!s || itemName(l.loot).toLowerCase().includes(s)));
    const tab = h('div', { class: 'seg' }, WE_AUCTION_KIND.map(([kind, name]) => h('button', { class: f.tur === kind ? 'on info' : '', onclick: () => { f.tur = kind; render(); } },
      T(name), ' ', h('span', { class: 'we-count mavi' }, lots.filter(l => l.tur === kind).length))));
    const add = btn(T('Lot ekle'), async () => {
      const loot = await pickItem(T('Lot ekle: {0}', T(WE_AUCTION_KIND.find(x => x[0] === f.tur)[1]))); if (!loot) return;
      if (lots.some(l => l.tur === f.tur && l.loot === loot)) return toast(T('Bu eşya bu dönemde zaten var.'), 'info');
      lots.push({ loot, grup: groupOf(loot), tur: f.tur, adet: 1, anlik: true, fiyat: 1000 }); save(); render(); }, 'sm primary', 'plus');
    fill(columns, h('div', { class: 'row wrap', style: { gap: '10px' } }, tab,
      h('input', { class: 'input', style: { width: '180px' }, placeholder: T('Ara…'), value: f.q, oninput: e => { f.q = e.target.value; render(); setTimeout(() => columns.querySelector('input.input')?.focus(), 0); } }),
      h('span', { class: 'spacer' }), add),
      h('div', { class: 'we-lot-head small muted' }, h('span'), h('span', null, T('Eşya')), h('span', null, T('Adet')), h('span', null, T('Anında alım')), h('span', null, T('Fiyat (U.)')), h('span')),
      ls.length ? h('div', { class: 'we-lots' }, ls.map(l => h('div', { class: 'we-lot' }, gameIcon(l.loot, 34, null, 'gavel'),
        h('div', { class: 'we-lot-name', title: l.loot }, itemName(l.loot)),
        weNumber(l.adet, v => { l.adet = Math.max(1, v); save(); }, { min: 1, max: 1e7, width: 76 }),
        h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: l.anlik, onchange: e => { l.anlik = e.target.checked; save(); render(); } }), h('span')),
        l.anlik ? weNumber(l.fiyat, v => { l.fiyat = v; save(); }, { min: 0, max: 1e9, adim: 100, width: 86 }) : h('span', { class: 'small dim' }, T('yalnız teklif')),
        btn('', () => { lots.splice(lots.indexOf(l), 1); save(); render(); }, 'sm ghost icon', 'x', { title: T('Lotu kaldır') }))))
        : h('div', { class: 'empty small muted' }, T('Bu dönemde lot yok.')));
  };
  fill(area, h('div', { class: 'card' }, weTitle(b, r.degisti ? btn(T('Standarda döndür'), async () => {
    if (await confirmBox(T('Açık artırma standarda dönsün mü?'), T('Lot listesi oyunun kendi {0} lotuna döner.', r.default_count), { ok: T('Standarda döndür'), danger: true }))
      if (await weRevert('social.json', jp('muzayede', 'lotlar'))) weRenderSection(); }, 'sm ghost', 'undo') : null),
    h('p', { class: 'small muted', style: { margin: '10px 0 14px' } }, T('Teklifler kredi ile verilir; anında alım uridyumla. Lotlar her dönem (saatin 30. dakikası, 22:30 UTC, pazar 22:30 UTC) yenilenir.')),
    columns));
  render();
}

// ---- harita paneli: cevherler (items.json cevherler.haritalar: haritanın adıyla, yoksa harita sınıfınınki)
function oreBlock(hm, markSelected) {
  const c = hm.cevher, count = Object.assign({}, c.adet), box = h('div', { class: 'stack', style: { gap: '6px' } });
  const save = () => { c.ozel = true; wePatch('items.json', c.yol, count); markSelected(); render(); };
  const render = () => {
    const var_ = Object.keys(c.kinds).filter(t => count[t] > 0);
    fill(box, 
      h('div', { class: 'small muted' }, c.ozel ? T('Bu haritaya özel.') : T('{0} sınıfının değerleri (aynı sınıftaki bütün haritalar). Değiştirince yalnız bu haritaya özel olur.', c.sinif)),
      ...var_.map(t => h('div', { class: 'we-ore' }, gameIcon(c.kinds[t], 24, null, 'box'), h('span', { class: 'small ellipsis' }, itemName(c.kinds[t])),
        weNumber(count[t], v => { count[t] = v; save(); }, { max: 1000, adim: 5, width: 52 }))),
      !var_.length ? h('div', { class: 'small dim' }, T('Bu haritada cevher yok.')) : null,
      h('div', { class: 'row wrap', style: { gap: '6px' } },
        btn(T('Cevher ekle'), ev => popMenu(ev.currentTarget, Object.keys(c.kinds).filter(t => !(count[t] > 0)).map(t => ({ label: itemName(c.kinds[t]), ic: 'plus',
          fn: () => { count[t] = 20; save(); } }))), 'sm', 'plus'),
        c.ozel ? btn(T('Sınıfın değerine döndür'), async () => { if (await weRevert('items.json', c.yol)) weRenderSection(); }, 'sm ghost', 'undo') : null),
      h('div', { class: 'we-field-row' }, h('label', null, T('Yeniden doğma')), weNumber(c.yeniden_sn[0], v => { c.yeniden_sn[0] = v; regeneration(); }, { min: 1, max: 3600, width: 46 }),
        h('span', { class: 'small muted' }, '–'), weNumber(c.yeniden_sn[1], v => { c.yeniden_sn[1] = v; regeneration(); }, { min: 1, max: 3600, width: 46 }), h('span', { class: 'small muted' }, T('sn'))),
      h('div', { class: 'small dim' }, T('Yeniden doğma süresi bütün haritalarda geçerli.')));
  };
  const regeneration = () => wePatch('items.json', jp('cevherler', 'yeniden_dogma_sn'), [Math.min(...c.yeniden_sn), Math.max(...c.yeniden_sn)]);
  render();
  return h('div', { class: 'stack', style: { gap: '8px' } }, h('div', { class: 'we-subtitle' }, T('Cevherler')), box);
}

// ================================================================== KUTULAR VE GANİMET
const MAP_CLASS_NAME = { 'X-1..X-8': N('Firma haritaları (X-1 – X-8)'), 'X-2..X-8': N('Firma haritaları (X-2 – X-8)'), '4-X': N('Savaş haritaları (4-X)'),
  '5-X': N('Korsan haritaları (5-1 – 5-3)'), '5-4': '5-4', 'BL': 'Black Light' };
// kutunun oyundaki görseli (atlas), yoksa anahtarının simgesi
const BOX_SPRITE = { PIRATE_BOOTY: 'booty_box_green', PIRATE_BOOTY_GOLD: 'booty_box_gold', PIRATE_BOOTY_RED: 'booty_box_red', PIRATE_BOOTY_BLUE: 'booty_box_blue',
  PIRATE_BOOTY_SILVER: 'booty_box_silver', BLACK_BOOTY_BOX: 'blackBooty_100x100', MASQUE_BOOTY_BOX: 'masqueBooty_100x100' };
const boxIcon = (k, size) => GI.index?.sprite[BOX_SPRITE[k.tur]] ? sprite(BOX_SPRITE[k.tur], size) : gameIcon(k.anahtar, size, null, 'gift');

async function weBoxes(area, b) {
  const r = await act(() => api('/api/dunya/section?bolum=kutular&dunya=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'kutular') return;
  const f = DE.sec.box_kinds || (DE.sec.box_kinds = { secili: 'bonus' });
  const entries = h('div', { class: 'we-npc-list' }), detail = h('div', { class: 'we-detail' });
  const items = [{ id: 'bonus', ad: T('Bonus kutusu'), sub: T('Bütün haritalarda (4-X hariç)'), ikon: 'bonus_box', degisti: r.bonus_changed },
    { id: 'bonus_4x', ad: T('Zengin bonus kutusu'), sub: T('Savaş haritalarında (4-X)'), ikon: 'bonus_box_green', degisti: r.bonus_4x_changed },
    ...r.kutular.map(k => ({ id: k.tur, ad: k.ad, sub: !k.spawns ? T('Haritalarda doğmaz') : k.takvim ? T('Etkinlikte') : T('Her zaman'), box: k, changed: k.degisti }))];
  const render = () => {
    fill(entries, ...items.map(o => h('button', { type: 'button', class: 'de-npc' + (f.secili === o.id ? ' on' : '') + (o.degisti ? ' degisti' : ''),
      onclick: () => { f.secili = o.id; render(); } }, o.kutu ? boxIcon(o.kutu, 36) : (GI.index?.sprite[o.ikon] ? sprite(o.ikon, 36) : icon('gift')),
      h('div', { class: 'we-npc-name' }, h('b', null, o.ad), h('div', { class: 'small muted' }, o.sub)))));
    const o = items.find(x => x.id === f.secili) || items[0];
    fill(detail, o.kutu ? boxDetail(o, r) : bonusDetail(o, r));
  };
  fill(area, h('div', { class: 'card' }, weTitle(b), h('div', { class: 'we-two-col narrow-list' }, entries, detail)));
  render();
}

function bonusDetail(o, r) {
  const route = jp(o.id === 'bonus' ? 'bonus_kutu' : 'bonus_kutu_4x'), rows = r[o.id].map(x => x.slice());
  const box = h('div', { class: 'stack', style: { gap: '6px' } });
  const save = () => { o.degisti = true; wePatch('npc.json', route, rows); };
  const render = () => fill(box, ...rows.map((x, i) => h('div', { class: 'we-box-row' }, gameIcon(x[0], 32, null, 'gift'),
    h('div', { class: 'we-box-body' }, h('span', { class: 'we-box-name', title: x[0] }, itemName(x[0])),
      h('div', { class: 'we-box-controls' }, h('span', { class: 'small muted' }, T('Adet')), weNumber(x[1], v => { x[1] = Math.max(1, v); save(); }, { min: 1, max: 1e7, width: 70 }),
        h('span', { class: 'we-percent' }, '%' + (100 / rows.length).toFixed(1)))),
    btn('', () => { if (rows.length < 2) return toast(T('Bonus kutusunda en az bir ödül olmalı.'), 'info'); rows.splice(i, 1); save(); render(); }, 'sm ghost icon', 'x'))),
    h('button', { type: 'button', class: 'we-reward-add', onclick: async () => { const l = await pickItem(T('Ödül ekle')); if (!l) return; rows.push([l, l.startsWith('ammunition_') ? 100 : 1]); save(); render(); } },
      icon('plus'), T('Ödül ekle')));
  render();
  return h('div', { class: 'stack', style: { gap: '12px' } },
    h('div', { class: 'we-detail-head' }, GI.index?.sprite[o.ikon] ? sprite(o.ikon, 56) : icon('gift'), h('div', null, h('div', { class: 'de-h3' }, o.ad), h('div', { class: 'small muted' }, o.sub))),
    h('p', { class: 'small muted', style: { margin: 0 } }, T('Kutu toplanınca satırlardan biri eşit şansla düşer. Haritadaki kutu sayısı Haritalar bölümünde.')),
    box,
    o.degisti ? btn(T('Standarda döndür'), async () => { if (await weRevert('npc.json', route)) weRenderSection(); }, 'sm ghost', 'undo') : null);
}

function boxDetail(o, r) {
  const k = JSON.parse(JSON.stringify(o.kutu)), route = jp('kutular', k.tur);
  const save = () => { o.degisti = true; wePatch('boxes.json', route, { adet: k.adet, yeniden_sn: k.yeniden_sn, haritalar: k.haritalar, odul: k.odul }); };
  const table = h('div', { class: 'stack', style: { gap: '6px' } });
  const percent = w => { const t = k.odul.reduce((a, x) => a + (+x[2] || 0), 0); return t ? (100 * w / t).toFixed(w * 100 / t < 1 ? 2 : 1) : '0'; };
  const render = () => fill(table, ...k.odul.map((x, i) => {
    const pack = x[0] === 'paket';
    const weight = h('input', { class: 'input num we-weight', type: 'number', min: 0, step: 'any', value: x[2], title: T('Ağırlık'),
      onchange: e => { x[2] = Math.max(0, +e.target.value || 0); save(); render(); } });
    return h('div', { class: 'we-box-row' }, pack ? h('span', { class: 'we-bundle' }, x[1].slice(0, 4).map(([l]) => gameIcon(l, 16, null, 'gift'))) : gameIcon(x[0], 32, null, 'gift'),
      h('div', { class: 'we-box-body' }, h('span', { class: 'we-box-name', title: pack ? x[1].map(([l, n]) => n + ' × ' + l).join('\n') : x[0] }, pack ? T('Paket ({0} eşya)', x[1].length) : itemName(x[0])),
        h('div', { class: 'we-box-controls' },
          pack ? null : h('span', { class: 'small muted' }, T('Adet')),
          pack ? null : Array.isArray(x[1]) ? [weNumber(x[1][0], v => { x[1][0] = Math.max(1, v); save(); }, { min: 1, max: 1e7, width: 52 }), '–',
            weNumber(x[1][1], v => { x[1][1] = Math.max(1, v); save(); }, { min: 1, max: 1e7, width: 52 })]
            : weNumber(x[1], v => { x[1] = Math.max(1, v); save(); }, { min: 1, max: 1e7, width: 70 }),
          h('span', { class: 'small muted' }, T('Ağırlık')), weight, h('span', { class: 'we-percent' }, '%' + percent(+x[2] || 0)))),
      btn('', () => { if (k.odul.length < 2) return toast(T('Kutuda en az bir ödül olmalı.'), 'info'); k.odul.splice(i, 1); save(); render(); }, 'sm ghost icon', 'x'));
  }), h('button', { type: 'button', class: 'we-reward-add', onclick: async () => {
    const l = await pickItem(T('Ödül ekle')); if (!l) return; k.odul.push([l, 1, 5]); save(); render(); } }, icon('plus'), T('Ödül ekle')));
  render();
  const classes = h('div', { class: 'chips' });
  const renderClass = () => fill(classes, ...r.classes.map(s => h('button', { type: 'button', class: 'chip link we-class' + (k.haritalar.includes(s) ? ' on' : ''),
    onclick: () => { k.haritalar = k.haritalar.includes(s) ? k.haritalar.filter(x => x !== s) : [...k.haritalar, s]; save(); renderClass(); } },
    k.haritalar.includes(s) ? icon('check') : icon('plus'), MAP_CLASS_NAME[s] ? T(MAP_CLASS_NAME[s]) : s)));
  renderClass();
  return h('div', { class: 'stack', style: { gap: '12px' } },
    h('div', { class: 'we-detail-head' }, boxIcon(k, 56), h('div', null, h('div', { class: 'de-h3' }, k.ad),
      h('div', { class: 'small muted' }, T('Açmak için: {0}', itemName(k.anahtar)), k.takvim ? ' · ' + T('yalnız etkinliği sürerken doğar') : ''))),
    h('div', { class: 'we-field-row' }, h('label', null, T('Haritada adet')), weNumber(k.adet, v => { k.adet = v; save(); }, { min: 0, max: 100, width: 56 }),
      h('span', { class: 'small muted' }, T('her haritada aynı anda'))),
    k.yeniden_sn ? h('div', { class: 'we-field-row' }, h('label', null, T('Yeniden doğma')),
      weNumber(k.yeniden_sn[0], v => { k.yeniden_sn[0] = v; save(); }, { min: 10, max: 86400, adim: 30, width: 64 }), '–',
      weNumber(k.yeniden_sn[1], v => { k.yeniden_sn[1] = v; save(); }, { min: 10, max: 86400, adim: 30, width: 64 }), h('span', { class: 'small muted' }, T('sn'))) : null,
    h('div', { class: 'we-subtitle' }, T('Doğduğu haritalar')), classes,
    h('div', { class: 'we-subtitle' }, T('Ödül tablosu')),
    h('p', { class: 'small muted', style: { margin: 0 } }, T('Açılınca bir satır ağırlığına göre çekilir: ağırlık / toplam ağırlık = şans.')),
    table,
    o.degisti ? btn(T('Standarda döndür'), async () => { if (await weRevert('boxes.json', route)) weRenderSection(); }, 'sm ghost', 'undo') : null);
}

// ================================================================== GALAKSİ KAPILARI
const GATE_REWARD_FIELD = [['ep', N('Deneyim'), 'kaynak_deneyim'], ['onur', N('Onur'), 'kaynak_onur'], ['uridyum', N('Uridyum'), 'kaynak_uridyum'],
  ['xenomit', N('Xenomit'), 'resource_ore_xenomit'], ['log_disk', N('Seyir diski'), 'resource_logfile'], ['kupon', N('Kupon'), '']];
const ROMAN = n => ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII', 'XIII', 'XIV', 'XV'][n] || String(n + 1);

async function weGates(area, b) {
  const r = await act(() => api('/api/dunya/section?bolum=kapilar&dunya=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'kapilar') return;
  const f = DE.sec.kp || (DE.sec.kp = { secili: r.kapilar[0]?.key, acik: {} });
  const entries = h('div', { class: 'we-npc-list' }), detail = h('div', { class: 'we-detail' });
  const render = () => {
    fill(entries, ...r.kapilar.map(g => h('button', { type: 'button', class: 'de-npc' + (f.secili === g.key ? ' on' : '') + (g.degisti ? ' degisti' : ''),
      onclick: () => { f.secili = g.key; render(); } }, art('ed_kapilar', 'we-gate-icon'),
      h('div', { class: 'we-npc-name' }, h('b', null, g.ad), h('div', { class: 'small muted' }, T('{0} dalga · {1} parça', g.waves.length, g.parca))))));
    const g = r.kapilar.find(x => x.key === f.secili) || r.kapilar[0];
    fill(detail, gateDetail(g, f));
  };
  fill(area, h('div', { class: 'card' }, weTitle(b), h('div', { class: 'we-two-col narrow-list' }, entries, detail)));
  render();
}

function gateDetail(g, f) {
  const route = jp('kapilar', g.key), std = g.standart;
  const save = () => {
    g.degisti = true;
    return wePatch('gates.json', route, { parca: g.parca, can: g.can, odul: Object.assign({}, g.odul, { cephane: g.cephane, sans: g.sans.map(x => ({ adet: x.adet, probability: x.probability })) }),
      waves: g.waves.map(w => ({ uzaylilar: w.uzaylilar.map(a => ({ tur: a.tur, adet: a.adet, hp: a.hp, kalkan: a.kalkan, hasar: a.hasar, hiz: a.hiz })) })) });
  };
  const row = (name, k, opts) => h('div', { class: 'we-field-row' + (std && std[k] !== g[k] ? ' degisti' : '') }, h('label', null, name),
    weNumber(g[k], v => { g[k] = v; save(); }, opts), std ? weStd(std[k], g[k], () => { g[k] = std[k]; save(); weRenderSection(); }) : null);
  const ammo = h('div', { class: 'we-rewards' });
  const renderAmmo = () => fill(ammo, ...Object.entries(g.cephane).map(([l, n]) => h('div', { class: 'we-reward-chip' }, gameIcon(l, 32, null, 'gift'),
    h('div', { class: 'we-reward-chip-name' }, h('div', { class: 'small ellipsis' }, itemName(l)), weNumber(n, v => { g.cephane[l] = Math.max(1, v); save(); }, { min: 1, max: 1e8, adim: 100, width: 80 })),
    btn('', () => { delete g.cephane[l]; save(); renderAmmo(); }, 'sm ghost icon', 'x'))),
    h('button', { type: 'button', class: 'we-reward-add', onclick: async () => { const l = await pickItem(T('Ödül ekle')); if (!l) return; g.cephane[l] = (g.cephane[l] || 0) + 1000; save(); renderAmmo(); } },
      icon('plus'), T('Ödül ekle')));
  renderAmmo();
  const wave = (w, n) => {
    const is_open = !!f.acik[g.key + n], total = w.uzaylilar.reduce((a, x) => a + x.adet, 0);
    const value = (name, v, cb, opts) => h('label', { class: 'we-wave-value' }, h('span', null, name), weNumber(v, cb, opts));
    const body = is_open ? h('div', { class: 'we-wave-body' }, w.uzaylilar.map(a => h('div', { class: 'we-wave-row' }, npcIcon(a, 30),
      h('div', { class: 'we-box-body' }, h('div', { class: 'we-npc-name' }, h('b', null, npcName(a)), a.permanent ? badge(T('Patron'), 'orange') : null,
          a.changed_kind ? badge(T('Değiştirildi'), 'orange') : null, h('span', { class: 'spacer' }),
          a.sabit ? null : btn(T('Değiştir'), async () => {
            const u = await pickAlien(T('Bu dalgada hangi uzaylı olsun?'), { numeric: true }); if (!u) return;
            Object.assign(a, { tur: u.tip, ad: u.ad, ikon: u.ikon, hp: u.hp, kalkan: u.kalkan, hasar: u.hasar, hiz: u.hiz, changed_kind: true });
            await save(); weRenderSection(); }, 'sm ghost', 'refresh', { title: T('Uzaylıyı başka türle değiştir (adet ve yer aynı kalır)') })),
        h('div', { class: 'we-box-controls' },
          value(T('Adet'), a.adet, v => { a.adet = Math.max(a.en_az, v); save(); summary.textContent = T('{0} uzaylı', fmtN(w.uzaylilar.reduce((t, x) => t + x.adet, 0))); }, { min: a.en_az, max: 5000, width: 46 }),
          value(T('Can'), a.hp, v => { a.hp = v; save(); }, { max: 50000000, adim: 1000, width: 80 }),
          value(T('Kalkan'), a.kalkan, v => { a.kalkan = v; save(); }, { max: 50000000, adim: 1000, width: 80 }),
          value(T('Hasar'), a.hasar, v => { a.hasar = v; save(); }, { max: 1000000, adim: 50, width: 62 })))))) : null;
    const summary = h('span', { class: 'small muted' }, T('{0} uzaylı', fmtN(total)));
    return h('div', { class: 'we-wave' + (is_open ? ' acik' : '') }, h('button', { type: 'button', class: 'we-wave-title', onclick: () => { f.acik[g.key + n] = !is_open; weRenderSection(); } },
      icon(is_open ? 'chevR' : 'chevR'), h('b', null, T('Dalga {0}', ROMAN(n))), h('span', { class: 'we-wave-icons' }, w.uzaylilar.slice(0, 6).map(a => npcIcon(a, 22))), h('span', { class: 'spacer' }), summary), body);
  };
  return h('div', { class: 'stack', style: { gap: '12px' } },
    h('div', { class: 'we-detail-head' }, art('ed_kapilar', 'we-gate-icon buyuk'), h('div', null, h('div', { class: 'de-h3' }, g.ad), h('div', { class: 'small muted' }, T('{0} dalga', g.waves.length)))),
    row(T('Gereken parça'), 'parca', { min: 1, max: 10000, width: 64 }), row(T('Can'), 'can', { min: 1, max: 100, width: 50 }),
    h('div', { class: 'we-subtitle' }, T('Kapı ödülü')),
    h('div', { class: 'we-reward-grid' }, GATE_REWARD_FIELD.filter(([k]) => k in g.odul).map(([k, name, looks]) => h('div', { class: 'we-reward' + (std && std.odul[k] !== g.odul[k] ? ' degisti' : '') },
      looks.startsWith('kaynak_') ? art(looks, 'we-reward-icon') : gameIcon(looks || null, 30, null, 'gift'), h('div', null, h('div', { class: 'small muted' }, T(name)),
        weNumber(g.odul[k] || 0, v => { g.odul[k] = v; save(); }, { max: 1e10, adim: k === 'ep' ? 10000 : k === 'onur' ? 1000 : 10, width: 92 }))))),
    h('div', { class: 'we-subtitle' }, T('Cephane ve eşya ödülü')), ammo,
    g.sans.length ? [h('div', { class: 'we-subtitle' }, T('Şanslı ödüller')), h('div', { class: 'stack', style: { gap: '6px' } }, g.sans.map(x => h('div', { class: 'we-box-row' },
      x.paket ? icon('gift') : gameIcon(x.esya, 32, null, 'gift'), h('div', { class: 'we-box-body' }, h('span', { class: 'we-box-name' }, x.paket ? T('Cevher paketi') : itemName(x.esya)),
        h('div', { class: 'we-box-controls' },
          typeof x.adet === 'number' && !x.paket ? [h('span', { class: 'small muted' }, T('Adet')), weNumber(x.adet, v => { x.adet = Math.max(1, v); save(); }, { min: 1, max: 1e7, width: 60 })] : null,
          h('span', { class: 'small muted' }, T('Şans')), h('input', { class: 'input num we-weight', type: 'number', min: 0, max: 100, step: 'any', value: +(x.probability * 100).toFixed(3),
            onchange: e => { x.probability = Math.max(0, Math.min(100, +e.target.value || 0)) / 100; save(); } }), h('span', { class: 'we-percent' }, '%'))), h('span'))))] : null,
    h('div', { class: 'we-subtitle' }, T('Dalgalar')),
    h('p', { class: 'small muted', style: { margin: 0 } }, T('Adet değişince dalganın alt grupları orantılı bölünür. Oyun Ayarları\'ndaki dalga uzaylı çarpanı bunun üstüne uygulanır.')),
    h('div', { class: 'stack', style: { gap: '6px' } }, g.waves.map(wave)),
    g.degisti ? btn(T('Kapıyı standarda döndür'), async () => { if (await weRevert('gates.json', route)) weRenderSection(); }, 'sm ghost', 'undo') : null);
}

// ================================================================== ETKİNLİKLER
const EVENT_FILTER = [['harita', N('Harita etkinlikleri')], ['yillik', N('Yıllık')], ['haftalik', N('Haftalık')], ['degisti', N('Değiştirilenler')]];
const EVENT_STATUS = [['takvim', N('Takvime göre'), 'info'], ['acik', N('Hep açık'), 'ok'], ['kapali', N('Kapalı'), 'err']];
const today = (day = 0) => new Date(Date.now() + day * 86400000).toISOString().slice(0, 10);

async function weEvents(area, b) {
  await alienList();
  const r = await act(() => api('/api/dunya/section?bolum=etkinlikler&dunya=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'etkinlikler') return;
  const f = DE.sec.label || (DE.sec.label = { filter_by: 'harita', q: '', secili: null, gecmis: false });
  const entries = h('div', { class: 'we-npc-list' }), detail = h('div', { class: 'we-detail' });
  const render = () => {
    const s = f.q.trim().toLowerCase();
    const l = r.etkinlikler.filter(e => (f.filter_by === 'degisti' ? e.degisti : e.tur === f.filter_by) && (!s || e.ad.toLowerCase().includes(s)));
    fill(entries, ...l.map(e => h('button', { type: 'button', class: 'de-npc' + (f.secili === e.key ? ' on' : '') + (e.degisti ? ' degisti' : ''),
      onclick: () => { f.secili = e.key; render(); } }, e.harita?.uzaylilar[0] ? npcIcon(e.harita.uzaylilar[0], 34) : weIcon('etkinlikler', 'we-gate-icon'),
      h('div', { class: 'we-npc-name' }, h('b', null, e.ad), h('div', { class: 'small muted' },
        e.world_status === 'acik' ? T('Bu dünyada hep açık') : e.world_status === 'kapali' ? T('Bu dünyada kapalı') : T('Takvime göre')))) ),
      !l.length ? h('div', { class: 'empty small muted' }, T('Eşleşen etkinlik yok.')) : null);
    const e = r.etkinlikler.find(x => x.key === f.secili) || l[0];
    if (e && !f.secili) f.secili = e.key;
    fill(detail, e ? eventDetail(e, r, f) : h('div', { class: 'empty muted' }, T('Soldan bir etkinlik seç.')));
  };
  const seg = h('div', { class: 'seg' }, EVENT_FILTER.map(([k, name]) => h('button', { class: f.filter_by === k ? 'on info' : '', onclick: () => { f.filter_by = k; f.secili = null; weRenderSection(); } }, T(name))));
  fill(area, h('div', { class: 'card' }, weTitle(b, h('input', { class: 'input', style: { width: '180px' }, placeholder: T('Etkinlik ara…'), value: f.q, oninput: e => { f.q = e.target.value; render(); } }), seg),
    h('p', { class: 'small muted', style: { margin: '10px 0 0' } }, T('Kaydın Etkinlikler sayfasında elle açtığın ya da kapattığın etkinlik, dünyanın ayarından önce gelir.')),
    h('div', { class: 'we-two-col narrow-list' }, entries, detail)));
  render();
}

function eventDetail(e, r, f) {
  const route = jp('etkinlikler', e.key);
  const save = () => { e.degisti = true; wePatch('events.json', route, { world_status: e.world_status, donemler: e.donemler || undefined,
    harita: e.harita ? { haritalar: e.harita.haritalar, uzaylilar: e.harita.uzaylilar.map(a => ({ adet: a.adet })), quota: e.harita.quota, patron: e.harita.patron } : undefined }); };
  const state = h('div', { class: 'seg' }, EVENT_STATUS.map(([k, name, c]) => h('button', { class: e.world_status === k ? 'on ' + c : '',
    onclick: () => { e.world_status = k; save(); weRenderSection(); } }, T(name))));
  const out = [h('div', { class: 'we-detail-head' }, e.harita?.uzaylilar[0] ? npcIcon(e.harita.uzaylilar[0], 56) : weIcon('etkinlikler', 'we-gate-icon buyuk'),
    h('div', null, h('div', { class: 'de-h3' }, e.ad), h('div', { class: 'small muted' }, { harita: T('Harita etkinliği'), yillik: T('Yıllık etkinlik'), haftalik: T('Haftalık etkinlik') }[e.tur]))),
    h('div', { class: 'we-field-row' }, h('label', null, T('Bu dünyada')), state)];
  if (e.donemler) {
    const box = h('div', { class: 'stack', style: { gap: '6px' } });
    const renderPeriods = () => {
      const todayStr = today();
      const lines = e.donemler.map((d, i) => [d, i]).filter(([d]) => f.gecmis || d[0].length === 5 || d[1] >= todayStr);
      fill(box, ...lines.map(([d, i]) => {
        const yearly = d[0].length === 5;
        const entry = (j) => h('input', { class: 'input we-date', type: yearly ? 'text' : 'date', value: d[j], placeholder: yearly ? T('AA-GG') : null,
          onchange: ev => { d[j] = ev.target.value; save(); } });
        return h('div', { class: 'we-period' + (!yearly && d[1] < todayStr ? ' gecmis' : '') + (!yearly && d[0] <= todayStr && todayStr <= d[1] ? ' simdi' : '') },
          entry(0), h('span', { class: 'muted' }, '–'), entry(1), yearly ? badge(T('Her yıl'), 'info') : null,
          !yearly && d[0] <= todayStr && todayStr <= d[1] ? badge(T('Şu an'), 'ok') : null, h('span', { class: 'spacer' }),
          btn('', () => { e.donemler.splice(i, 1); save(); renderPeriods(); }, 'sm ghost icon', 'x', { title: T('Dönemi sil') }));
      }), !lines.length ? h('div', { class: 'small dim' }, T('Gelecekte dönem yok.')) : null,
      h('div', { class: 'row wrap', style: { gap: '6px' } },
        btn(T('Dönem ekle'), () => { e.donemler.push([today(), today(7)]); save(); renderPeriods(); }, 'sm', 'plus'),
        btn(T('Her yıl tekrarlanan dönem'), () => { const d = today().slice(5); e.donemler.push([d, today(7).slice(5)]); save(); renderPeriods(); }, 'sm ghost', 'refresh'),
        h('label', { class: 'row small muted', style: { gap: '6px', cursor: 'pointer' } }, h('input', { type: 'checkbox', checked: f.gecmis, onchange: ev => { f.gecmis = ev.target.checked; renderPeriods(); } }),
          T('Geçmiş dönemleri göster'))));
    };
    renderPeriods();
    out.push(h('div', { class: 'we-subtitle' }, T('Dönemler')), h('p', { class: 'small muted', style: { margin: 0 } }, T('Etkinlik bu tarihler arasında açılır (bitiş günü dahil). "Her yıl" dönemleri her yıl aynı günlerde tekrar eder.')), box);
  } else if (e.days || e.saatler) {
    const WEEKDAYS = [N('Pzt'), N('Sal'), N('Çar'), N('Per'), N('Cum'), N('Cmt'), N('Paz')];
    out.push(h('div', { class: 'we-subtitle' }, T('Haftalık düzen')), h('div', { class: 'small muted' },
      (e.days ? e.days.map(g => T(WEEKDAYS[g])).join(', ') : T('Her gün')) + (e.saatler ? ' · ' + e.saatler.map(([a, b2]) => String(a).padStart(2, '0') + ':00–' + String(b2).padStart(2, '0') + ':00').join(', ') : '')),
      h('div', { class: 'small dim' }, T('Haftalık düzen değiştirilemez; "Hep açık" ya da "Kapalı" ile bu dünyada sabitleyebilirsin.')));
  }
  if (e.harita) {
    const gameMap = e.harita;
    const classes = h('div', { class: 'chips' }, r.classes.map(m => { const var_ = gameMap.haritalar.includes(m), allowed = gameMap.selectable.includes(m);
      return h('button', { type: 'button', class: 'chip link we-class' + (var_ ? ' on' : ''), disabled: !allowed && !var_, title: allowed ? null : T('Bu etkinliğin bu harita sınıfı için uzaylısı yok'),
        onclick: () => { gameMap.haritalar = var_ ? gameMap.haritalar.filter(x => x !== m) : [...gameMap.haritalar, m]; if (!var_ && gameMap.quota[m] == null) gameMap.quota[m] = Math.max(20, ...Object.values(gameMap.quota)); save(); weRenderSection(); } },
        var_ ? icon('check') : icon('plus'), m); }));
    out.push(h('div', { class: 'we-subtitle' }, T('Harita etkinliği')), h('div', { class: 'small muted' }, T('Etkinliğin uzaylılarının doğduğu harita sınıfları:')), classes,
      ...gameMap.uzaylilar.map(a => h('div', { class: 'we-field-row' }, npcIcon(a, 28), h('b', { class: 'small', style: { minWidth: '120px' } }, npcName(a)),
        weNumber(a.adet, v => { a.adet = v; save(); }, { max: 200, width: 56 }), h('span', { class: 'small muted' }, T('haritada aynı anda')))),
      Object.keys(gameMap.quota).length ? h('div', { class: 'small muted' }, T('Harita başına kota (etkinlik boyunca o haritada en çok doğan):')) : null,
      Object.keys(gameMap.quota).length ? h('div', { class: 'we-quota' }, gameMap.haritalar.filter(m => m in gameMap.quota).map(m => h('label', { class: 'we-wave-value' }, h('span', null, m),
        weNumber(gameMap.quota[m], v => { gameMap.quota[m] = v; save(); }, { max: 10000, width: 56 })))) : null,
      gameMap.patron ? h('div', { class: 'we-field-row' }, h('label', null, T('Patron')), h('label', { class: 'we-wave-value' }, h('span', null, T('Adet')),
        weNumber(gameMap.patron.adet, v => { gameMap.patron.adet = v; save(); }, { max: 50, width: 46 })),
        h('label', { class: 'we-wave-value' }, h('span', null, T('Süre (dk)')), weNumber(Math.round(gameMap.patron.sure_sn / 60), v => { gameMap.patron.sure_sn = Math.max(1, v) * 60; save(); }, { min: 1, max: 1440, width: 52 }))) : null);
  }
  if (e.degisti) out.push(btn(T('Etkinliği standarda döndür'), async () => { if (await weRevert('events.json', route)) weRenderSection(); }, 'sm ghost', 'undo'));
  return h('div', { class: 'stack', style: { gap: '12px' } }, out);
}

// ================================================================== ÖDÜLLER VE EKONOMİ
const RANK_FORMULA = [['ep', N('Deneyim puanı başına')], ['onur', N('Onur puanı başına')], ['seviye', N('Seviye başına')], ['npc', N('Uzaylı puanı başına')],
  ['gorev', N('Tamamlanan görev başına')], ['oyuncu', N('Yenilen oyuncu puanı başına')], ['gemi', N('Gemi puanı başına')], ['gun', N('Kayıttan beri geçen gün başına')],
  ['dost', N('Kendi firmandan yok edilen oyuncu başına')], ['olum_dusman', N('Düşmana yenilme başına')], ['olum_radyasyon', N('Radyasyonda ölme başına')],
  ['phoenix', N('Yok edilen Phoenix başına')]];

async function weEconomy(area, b) {
  const r = await act(() => api('/api/dunya/section?bolum=ekonomi&dunya=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'ekonomi') return;
  const f = DE.sec.ek || (DE.sec.ek = { all: false });
  const lv = r.seviyeler.map(x => x.slice()), es = r.esikler.slice(), fo = Object.assign({}, r.formul);
  const saveLevels = () => wePatch('levels.json', jp('seviyeler'), lv.map(x => x[1]));
  const limit = f.all ? lv.length : 26;
  const levels = h('div', { class: 'we-level-grid' }, lv.slice(1, limit).map((x, i) => h('label', { class: 'we-wave-value' + (x[1] !== r.levels_default[i + 1][1] ? ' degisti' : '') },
    h('span', { class: 'we-lv' }, x[0]), weNumber(x[1], v => { x[1] = v; saveLevels(); }, { min: 1, max: 1e15, adim: 1000, width: 112 }))));
  const percent = h('div', { class: 'chips' }, [50, 75, 125, 200].map(p => h('button', { type: 'button', class: 'chip link', onclick: () => {
    lv.forEach((x, i) => { if (i) x[1] = Math.max(lv[i - 1][1] + 1, Math.round(r.levels_default[i][1] * p / 100)); }); saveLevels().then(() => weRenderSection()); } }, '%' + p)));
  const formula = h('div', { class: 'stack', style: { gap: '4px' } }, RANK_FORMULA.filter(([k]) => k in fo).map(([k, name]) => h('div', { class: 'we-field-row' + (fo[k] !== r.formula_default[k] ? ' degisti' : '') },
    h('label', { style: { width: '240px' } }, T(name)), h('input', { class: 'input num', type: 'number', step: 'any', value: fo[k], style: { width: '110px' },
      onchange: ev => { fo[k] = +ev.target.value || 0; wePatch('ranks.json', jp('formul'), fo); } }),
    weStd(r.formula_default[k], fo[k], () => { fo[k] = r.formula_default[k]; wePatch('ranks.json', jp('formul'), fo).then(() => weRenderSection()); }, x => String(x)))));
  const thresholds = h('div', { class: 'we-level-grid genis' }, es.slice(1).map((n, i) => h('label', { class: 'we-wave-value' + (n !== r.thresholds_default[i + 1] ? ' degisti' : '') },
    h('span', { class: 'ellipsis', style: { width: '150px' } }, r.rutbeler[i + 1] || i + 2),
    weNumber(n, v => { es[i + 1] = v; wePatch('ranks.json', jp('esikler'), es); }, { min: 1, max: 1e9, adim: 100, width: 92 }))));
  const back = (file, route, name) => btn(T('Standarda döndür'), async () => { if (await weRevert(file, route)) weRenderSection(); }, 'sm ghost', 'undo', { title: name });
  fill(area, h('div', { class: 'stack' },
    h('div', { class: 'card' }, weTitle(b)),
    h('div', { class: 'card' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('star'), T('Seviye eşikleri')), h('div', { class: 'row', style: { gap: '6px' } }, percent, back('levels.json', jp('seviyeler')))),
      h('p', { class: 'desc' }, T('Her seviyeye ulaşmak için gereken toplam deneyim (EP). Hızlı ilerleme için standart eşiklerin yüzdesini seç.')), levels,
      lv.length > limit || f.all ? btn(f.all ? T('Daha az göster') : T('Bütün seviyeler ({0})', lv.length), () => { f.all = !f.all; weRenderSection(); }, 'sm ghost', 'chevR') : null),
    h('div', { class: 'card' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('shield'), T('Rütbe puanı formülü')), back('ranks.json', jp('formul'))),
      h('p', { class: 'desc' }, T('Rütbe puanı bu katsayılarla toplanır; eksi katsayılar puan düşürür.')), formula),
    h('div', { class: 'card' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('shield'), T('Rütbe eşikleri')), back('ranks.json', jp('esikler'))),
      h('p', { class: 'desc' }, T('Her rütbe için gereken en az rütbe puanı (tek oyunculu oyunda rütbe bu eşiklere göre verilir).')), thresholds),
    h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Günlük giriş takviminin ödülleri oyunun kendi dosyasından gösterildiği için burada değiştirilmez (değişen ödül takvimde eskisi gibi görünürdü).')))));
}

// ================================================================== PAYLAŞIM (dışa / içe aktarma, paylaşım kodu)
async function weExport(w) {
  const r = await act(() => api('/api/dunya/kod', { dunya: w.id })); if (!r) return;
  const long = r.code.length > 1900;
  const code = h('textarea', { class: 'input mono we-code', rows: 4, readonly: true }, r.code);
  const m = modal({ title: T('"{0}" dünyasını paylaş', w.ad), wide: true, body: h('div', { class: 'stack', style: { gap: '12px' } },
    h('div', { class: 'we-share-summary' }, weCover(w.cover, 'kucuk'), h('div', null, h('b', null, w.ad), h('div', { class: 'small muted' },
      w.standart ? T('Standart dünyanın taslağı') : T('{0} değişiklik', w.changes)))),
    h('div', { class: 'we-share-paths' },
      h('div', { class: 'we-share-path' }, icon('download'), h('b', null, T('Dosya olarak')), h('div', { class: 'small muted' }, T('Bir .json dosyası: arkadaşın Dünya Editörü\'nde "İçe aktar" ile ekler.')),
        btn(T('Dosyaya kaydet'), () => act(() => api('/api/dunya/disari', { dunya: w.id })).then(x => { if (x && x.yol) { toast(T('Kaydedildi: {0}', x.yol), 'ok'); m.close(); } }), 'sm primary', 'download')),
      h('div', { class: 'we-share-path' }, icon('copy'), h('b', null, T('Paylaşım kodu')), h('div', { class: 'small muted' },
        long ? T('Kod {0} karakter: Discord mesajına sığmaz, dosya olarak paylaş ya da metin dosyası olarak gönder.', fmtN(r.code.length))
          : T('Kod {0} karakter: sohbete ya da Discord\'a yapıştırabilirsin.', fmtN(r.code.length))),
        btn(T('Kodu kopyala'), async () => { try { await navigator.clipboard.writeText(r.code); toast(T('Kod kopyalandı.'), 'ok'); } catch (e) { code.select(); document.execCommand('copy'); toast(T('Kod kopyalandı.'), 'ok'); } }, 'sm', 'copy'))),
    code,
    h('div', { class: 'small dim' }, T('Paylaşılan dünya yalnız değişiklikleri taşır; kayıtlar, pilotlar ve ilerleme paylaşılmaz.'))),
    foot: [btn(T('Kapat'), () => m.close(), 'ghost')] });
}

function weImport() {
  const code = h('textarea', { class: 'input mono we-code', rows: 4, placeholder: 'OODUNYA1:…' });
  const result = x => { if (!x || x.iptal) return; m.close(); DE.liste = x; weImportReport(x); };
  const m = modal({ title: T('Dünya içe aktar'), wide: true, body: h('div', { class: 'stack', style: { gap: '12px' } },
    h('div', { class: 'we-share-paths' },
      h('div', { class: 'we-share-path' }, icon('folder'), h('b', null, T('Dosyadan')), h('div', { class: 'small muted' }, T('Paylaşılan .json dosyasını seç.')),
        btn(T('Dosya seç…'), () => act(() => api('/api/dunya/import', {})).then(result), 'sm primary', 'upload')),
      h('div', { class: 'we-share-path' }, icon('copy'), h('b', null, T('Paylaşım kodundan')), h('div', { class: 'small muted' }, T('Kodu aşağıya yapıştır.')),
        btn(T('Koddan içe aktar'), () => code.value.trim() ? act(() => api('/api/dunya/import', { code: code.value })).then(result) : toast(T('Önce kodu yapıştır.'), 'info'), 'sm', 'upload'))),
    code, h('div', { class: 'small dim' }, T('İçe aktarılan dünya yeni bir dünya olarak eklenir; hiçbir dünyanın üzerine yazılmaz.'))),
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost')] });
}

function weImportReport(x) {
  const r = x.rapor || {}, w = x.liste.find(d => d.id === x.yeni);
  const m = modal({ title: T('Dünya içe aktarıldı'), body: h('div', { class: 'stack', style: { gap: '12px' } },
    h('div', { class: 'we-share-summary' }, art('dron_kayit', 'we-report-art'), h('div', null, h('b', null, w ? w.ad : x.yeni), h('div', { class: 'small muted' }, T('{0} değişiklik', r.changes || 0)))),
    r.data_differs?.length ? h('div', { class: 'alert uyari' }, icon('alert'), h('div', null, T('Bu dünya farklı bir oyun verisiyle hazırlanmış ({0}). Değişiklikler uygulanır ama bazıları beklendiği gibi olmayabilir.', r.data_differs.join(', ')))) : null,
    r.skipped ? h('div', { class: 'alert uyari' }, icon('alert'), h('div', null, T('{0} değişiklik uygulanamadığı için atlandı.', r.skipped),
      r.issues?.length ? h('ul', { class: 'small we-issues' }, r.issues.map(s2 => h('li', null, s2))) : null)) : null,
    !r.data_differs?.length && !r.skipped ? h('div', { class: 'alert bilgi' }, icon('check'), h('div', null, T('Bütün değişiklikler uygulandı.'))) : null),
    foot: [btn(T('Kapat'), () => { m.close(); renderWorld(); }, 'ghost'), btn(T('Dünyayı aç'), () => { m.close(); weOpen(x.yeni); }, 'primary', 'chevR')] });
}

// ================================================================== OYNA SAYFASI: kaydın dünyası
function playWorldChip(a) {
  const w = a.world_info;
  return h('button', { type: 'button', class: 'game-world', title: T('OYNA bu dünyayı açar. Değiştirmek için tıkla.'), onclick: ev => playWorldMenu(ev.currentTarget, a) },
    weCover(w.cover, 'mini'), h('span', { class: 'game-world-name' }, h('small', null, T('Dünya')), h('b', null, w.ad)),
    w.standart ? icon('lock') : w.changes ? badge(T('{0} değişiklik', w.changes), 'orange') : null, icon('chevR'));
}
async function playWorldMenu(anchor, a) {
  const r = await act(() => api('/api/dunyalar')); if (!r) return;
  popMenu(anchor, [...r.liste.map(w => ({ label: w.ad + (w.id === a.world_info.id ? '  ✓' : ''), ic: w.standart ? 'lock' : 'globe',
    fn: () => act(() => api('/api/kayitlar/dunya', { id: a.id, dunya: w.id }), T('{0} artık "{1}" dünyasına girer.', a.pilot, w.ad)).then(x => x && poll()) })),
    '-', { label: T('Dünya Editörü'), ic: 'edit', fn: () => { DE.did = a.world_info.id; DE.section = 'genel'; go('dunya'); } }]);
}

// ARKADAŞLARINLA OYNA > Host: sunucunun dünyası (panel ayarı arkadas_dunya; boş: kaydının dünyası)
function hostWorldChip(v) {
  const w = v.dunya.valid;
  return h('button', { type: 'button', class: 'game-world', title: T('Sunucu bu dünyayla açılır; misafirler de bu dünyada oynar. Değiştirmek için tıkla.'),
    onclick: ev => popMenu(ev.currentTarget, [{ label: T('Kaydının dünyası ({0})', v.dunya.save_world.ad) + (!v.dunya.secim ? '  ✓' : ''), ic: 'save', fn: () => hostPickWorld('') },
      ...v.dunya.liste.map(x => ({ label: x.ad + (v.dunya.secim === x.id ? '  ✓' : ''), ic: x.standart ? 'lock' : 'globe', fn: () => hostPickWorld(x.id) })), '-',
      { label: T('Dünya Editörü'), ic: 'edit', fn: () => { DE.did = w.id; DE.section = 'genel'; go('dunya'); } }]) },
    weCover(w.cover, 'mini'), h('span', { class: 'game-world-name' }, h('small', null, T('Sunucunun dünyası')), h('b', null, w.ad)),
    w.standart ? icon('lock') : w.changes ? badge(T('{0} değişiklik', w.changes), 'orange') : null, icon('chevR'));
}
function hostPickWorld(id) {
  act(() => api('/api/arkadas/ayarlar', { dunya: id }), FRD.veri?.host?.acik ? T('Sunucu yeniden başlayınca bu dünya açılır.') : T('Kaydedildi.'))
    .then(r => { if (r) { FRD.veri = r; drawFriends(); } });
}
