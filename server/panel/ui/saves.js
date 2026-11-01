/* OpenOrbit paneli — Kayıtlar ve karakter editörü (saves.py, save_editor.py; /api/kayitlar…, /api/editor…). panel.js'in
   yardımcılarını ve oyunun görsellerini (ogYukle, sprite, esyaSprite, esyaAdi: BepInEx dökümü) kullanır.
   Kitaplık: etkin kaydın sahnesi (gemi, firma portresi, seviye ilerlemesi, cüzdan), öbür kayıtların kartları, silinenler.
   Editör: kaydın taslağında (duzenleme.json) çalışır. Her işlem oyunun kurallarıyla (hangar, ödül yolu) taslağa uygulanır ve görünüm
   yenilenir; Kaydet güvenlik yedeği alıp kayda yazar, Vazgeç taslağı atar. Kayıt oyundaysa salt okunur. */
'use strict';

Object.assign(ICONS, {
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  drone: '<circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/><circle cx="12" cy="12" r="8" stroke-dasharray="2 3"/>',
  paw: '<circle cx="5.5" cy="10" r="2"/><circle cx="9" cy="5.5" r="2"/><circle cx="15" cy="5.5" r="2"/><circle cx="18.5" cy="10" r="2"/><path d="M12 12c-3 0-6 3.5-6 6a3 3 0 0 0 3 3c1.2 0 2-.6 3-.6s1.8.6 3 .6a3 3 0 0 0 3-3c0-2.5-3-6-6-6z"/>',
  ammo: '<path d="M9 2h6v4l1 2v14H8V8l1-2z"/><line x1="8" y1="12" x2="16" y2="12"/>',
  gem: '<polygon points="6 3 18 3 22 9 12 22 2 9 6 3"/><polyline points="2 9 22 9"/><polyline points="12 22 8 9 12 3 16 9 12 22"/>',
  wrench: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
  heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8z"/>',
  gauge: '<path d="M12 14l4-4"/><path d="M3.3 19a10 10 0 1 1 17.4 0"/>',
  cpu: '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v4M15 1v4M9 19v4M15 19v4M1 9h4M1 15h4M19 9h4M19 15h4"/>',
});

const COMPANY_TAG = { 1: 'MMO', 2: 'EIC', 3: 'VRU' };
const companyLower = f => (typeof f === 'number' ? COMPANY_TAG[f] : f || '').toLowerCase();
const fmtShort = n => { try { return new Intl.NumberFormat(LOC(), { notation: 'compact', maximumFractionDigits: 1 }).format(n || 0); } catch (e) { return fmtN(n); } };
const seEmpty = (size, iconEl) => h('span', { class: 'sprite vacant', style: { width: size + 'px', height: size + 'px' } }, icon(iconEl));
const spr = (name, size, iconEl = 'box') => GI.index?.sprite[name] ? sprite(name, size) : seEmpty(size, iconEl);
// gemi: tepeden büyük görünüm (_top), yoksa mağaza ikonu; tasarımın kendi görünümü önce (ship_sentinel_design_sentinel-carbonite)
function shipSprite(lid, firma) {
  const k = lid.replace(/^ship_/, ''), last = k.split('_').pop(), base = k.split('_')[0];
  for (const c of [last, last + '-' + firma, base, base + '-' + firma]) for (const b of ['_top', '_100x100']) if (GI.index?.sprite[c + b]) return c + b;
  return itemSprite(lid, firma);
}
const shipImage = (lid, size, firma) => {
  const sp = lid && GI.index && shipSprite(lid, firma), el = sp ? sprite(sp, size) : seEmpty(size, 'ship');
  if (lid) el.dataset.loot = lid;              // eşya ipucu: değerler, yuvalar, bonus (panel.js esyaIpucu)
  return el;
};
// dron: seviyesinin görünümü (iris-4: 5. seviye), yoksa daha düşüğü
function droneSprite(lid, lv) {
  const b = lid.replace(/^drone_/, '');
  for (let n = Math.min(5, (lv || 1) - 1); n >= 0; n--) for (const s of ['_100x100', '_top']) if (GI.index?.sprite[b + '-' + n + s]) return b + '-' + n + s;
  return itemSprite(lid);
}
const droneImage = (lid, lv, size) => {
  const sp = GI.index && droneSprite(lid, lv), el = sp ? sprite(sp, size) : seEmpty(size, 'drone');
  el.dataset.loot = lid;
  return el;
};
const petImage = (lv, size) => spr(GI.index?.sprite['pet10-' + (lv || 0) + '_top'] ? 'pet10-' + (lv || 0) + '_top' : 'pet10_100x100', size, 'paw');
const itemIcon = (lid, size, firma) => gameIcon(lid, size, firma || companyLower(SE.v?.pilot.firma), 'box');
// firmanın oyundaki karakter portresi (CommonUI eic_char), yoksa panelin arması
const portrait = (f, cls = 'se-portrait', size = 112) => GI.index?.sprite[companyLower(f) + '_char'] ? h('span', { class: cls }, sprite(companyLower(f) + '_char', size))
  : h('span', { class: cls + ' emblem' }, art('firma_' + (companyLower(f) || 'eic'), 'crest'));
function epBar(ep, base, next_, cls = '') {
  const p = next_ ? Math.max(0, Math.min(1, (ep - base) / Math.max(1, next_ - base))) : 1;
  return h('div', { class: 'se-ep ' + cls, title: next_ ? T('{0} / {1} EP', fmtN(ep), fmtN(next_)) : T('En yüksek seviye') }, h('span', { style: { width: (p * 100).toFixed(1) + '%' } }));
}

// ================================================================== KİTAPLIK
const KL = { trash: false };

async function renderSaves() {
  if (SE.slot) return renderEditor();
  await loadGameImages();
  const r = await act(() => api('/api/kayitlar')); if (!r || S.page !== 'saves' || SE.slot) return;
  const active = r.liste.find(k => k.active), others = r.liste.filter(k => !k.active);
  const tools = h('div', { class: 'row wrap' },
    btn(T('Yeni kayıt'), () => newSaveModal(), 'primary', 'plus'),
    btn(T('İçe aktar…'), () => act(() => api('/api/kayitlar/import', {}), x => x.cancelled ? T('İptal edildi.') : T('Kayıt içe aktarıldı.')).then(() => renderSaves()), '', 'upload'),
    h('span', { class: 'spacer' }),
    r.liste.length ? h('span', { class: 'small muted' }, T('{0} kayıt', r.liste.length)) : null,
    btn(T('Kayıt klasörü'), () => act(() => api('/api/open_folder', { ne: 'saves' })), 'ghost', 'folder'));
  $('#content').replaceChildren(h('div', { class: 'stack ke-kitap' }, tools,
    active ? saveScene(active) : h('div', { class: 'card empty' }, art('empty_save'), h('h3', null, T('Henüz kayıt yok')),
      h('div', null, T('Yeni bir kayıt oluştur ya da bir yedeği içe aktar.'))),
    others.length ? h('div', { class: 'section-title' }, T('Öbür kayıtlar ({0})', others.length)) : null,
    others.length ? h('div', { class: 'se-cards' }, others.map(saveCard)) : null,
    trash(r.trash)));
}

// kayıt kartlarının ortak "Diğer" menüsü (ek istemci, ad, not, kopya, dışa aktarma, klasör, silme)
function saveMenu(k, ev) {
  const c = S.durum?.multi, extra = c && c.ayar && c.save_count > 1 && (c.saves || []).find(x => x.id === k.id);
  const extraWhy = extra ? (extra.ek || k.id === c.main ? T('Kayıt kullanımda') : extraBlock(S.durum, extra)) : null;
  popMenu(ev.currentTarget, [
    extra ? { label: extraWhy ? T('Ek istemcide aç ({0})', extraWhy) : T('Ek istemcide aç'), iconEl: 'play', disabled: !!extraWhy,
      fn: () => openExtra(k.id, k.pilot).then(() => S.page === 'saves' && renderSaves()) } : null,
    extra ? '-' : null,
    { label: T('Yeniden adlandır'), ic: 'edit', fn: async () => { const v = await promptBox(T('Kaydı yeniden adlandır'), T('Kayıt adı'), k.ad); if (v != null) act(() => api('/api/kayitlar/rename', { id: k.id, ad: v }), T('Ad değişti.')).then(renderSaves); } },
    { label: T('Not ekle / düzenle'), ic: 'note', fn: async () => { const v = await promptBox(T('Kayıt notu'), T('Not'), k.not_, { multiline: true }); if (v != null) act(() => api('/api/kayitlar/note', { id: k.id, not: v })).then(renderSaves); } },
    { label: T('Kopyala'), ic: 'copy', fn: async () => { const v = await promptBox(T('Kaydı kopyala'), T('Yeni kaydın adı'), T('{0} (kopya)', k.ad)); if (v != null) act(() => api('/api/kayitlar/copy', { id: k.id, ad: v }), T('Kopyalandı.')).then(renderSaves); } },
    { label: T('Dışa aktar (.zip)…'), ic: 'download', fn: () => act(() => api('/api/kayitlar/disari', { id: k.id, with_backups: true }), x => x.cancelled ? T('İptal edildi.') : T('Dışa aktarıldı: {0}', x.route)) },
    { label: T('Klasörü aç'), ic: 'folder', fn: () => act(() => api('/api/open_folder', { ne: 'record', id: k.id })) },
    '-',
    { label: T('Sil'), ic: 'trash', danger: true, disabled: k.in_use, fn: async () => {
      if (await confirmBox(T('Kayıt silinsin mi?'), T('"{0}" ({1}) çöp kutusuna taşınır; Kayıtlar sayfasının altından geri alabilirsin.', k.ad, k.pilot), { ok: T('Sil'), danger: true }))
        act(() => api('/api/kayitlar/sil', { id: k.id }), T('Çöp kutusuna taşındı.')).then(renderSaves);
    } },
  ].filter(Boolean));
}
const statusBadges = k => [k.in_use ? badge(T('OYUNDA'), 'ok') : null, k.draft ? badge(T('KAYDEDİLMEMİŞ DEĞİŞİKLİK'), 'warn') : null,
  k.corrupt ? badge(T('BOZUK'), 'err') : null];

// etkin kayıt: geniş sahne (gemi, firma portresi, seviye, cüzdan, eylemler)
function saveScene(k) {
  const f = companyLower(k.firma);
  const currency = (name, n, tag) => h('div', { class: 'se-currency-card' }, art('source_' + name, 'se-currency-icon'), h('div', null, h('span', null, tag), h('b', null, fmtN(n))));
  const meta = (iconEl, tag, value) => h('div', { class: 'se-meta' }, icon(iconEl), h('span', null, tag), h('b', null, value));
  return h('div', { class: 'card se-scene f-' + f },
    h('div', { class: 'se-scene-ship' }, shipImage(k.ship_appearance, 250, f),
      h('div', { class: 'se-scene-ship-name' }, k.ship_appearance ? itemName(k.ship_appearance) : k.gemi)),
    h('div', { class: 'se-scene-body' },
      h('div', { class: 'row wrap', style: { gap: '8px' } }, badge(T('ETKİN KAYIT'), 'info'), ...statusBadges(k)),
      h('div', { class: 'se-scene-head' }, portrait(k.firma),
        h('div', { style: { minWidth: 0 } }, h('h2', { class: 'se-scene-name' }, k.ad),
          h('div', { class: 'se-pilot' }, h('b', null, k.pilot), k.klan ? h('span', { class: 'se-clan' }, '[' + k.klan + ']') : null,
            badge(k.firma || '?', firmaCls(k.firma)), k.premium ? badge('Premium', 'orange') : null))),
      h('div', { class: 'se-lv' }, h('div', { class: 'se-lv-num' }, h('small', null, T('Seviye')), h('b', null, k.seviye ?? '?')),
        h('div', { class: 'grow' }, h('div', { class: 'row between small muted' }, h('span', null, T('Deneyim')),
          h('span', { class: 'mono' }, k.next_level ? fmtShort(k.ep) + ' / ' + fmtShort(k.next_level) + ' EP' : fmtShort(k.ep) + ' EP')),
          epBar(k.ep, k.level_base, k.next_level))),
      h('div', { class: 'se-currencies' }, currency('kredi', k.kredi, T('Kredi')), currency('uridyum', k.uridyum, T('Uridyum')), currency('onur', k.onur, T('Onur'))),
      h('div', { class: 'se-metas' }, meta('map', T('Harita'), k.harita), meta('ship', T('Gemi'), T('{0} gemi', k.ship_count)),
        meta('drone', T('Dronlar'), k.drone_count), meta('paw', 'P.E.T.', k.pet || '—'), meta('clock', T('Oynama'), fmtDur(k.play_sec)),
        meta('calendar', T('Son oynama'), fmtWhen(k.last_played || k.last_save))),
      k.not_ ? h('div', { class: 'note' }, k.not_) : null,
      h('div', { class: 'row wrap se-action' },
        btn(T('Oyna'), () => { go('play'); act(() => api('/api/oyna', {})); }, 'orange', 'play', { disabled: k.in_use }),
        btn(T('Karakter editörü'), () => seOpen(k), 'primary', 'edit'),
        btn(T('Yedekler ({0})', k.backup_count), () => backupsModal(k.id), '', 'clock'),
        h('span', { class: 'spacer' }),
        btn('', ev => saveMenu(k, ev), 'ghost icon', 'more', { title: T('Diğer') }))));
}

function saveCard(k) {
  const f = companyLower(k.firma);
  return h('div', { class: 'card se-card-save f-' + f },
    h('div', { class: 'se-card-top' },
      h('div', { class: 'se-card-ship' }, shipImage(k.ship_appearance, 96, f)),
      h('div', { class: 'grow', style: { minWidth: 0 } },
        h('div', { class: 'row', style: { gap: '6px', minWidth: 0 } }, h('span', { class: 'se-card-name', title: k.ad }, k.ad)),
        h('div', { class: 'se-pilot small' }, h('b', null, k.pilot), k.klan ? h('span', { class: 'se-clan' }, '[' + k.klan + ']') : null, badge(k.firma || '?', firmaCls(k.firma))),
        h('div', { class: 'row', style: { gap: '8px', marginTop: '6px' } }, h('span', { class: 'se-lv-mini' }, T('Sv {0}', k.seviye ?? '?')),
          h('div', { class: 'grow' }, epBar(k.ep, k.level_base, k.next_level, 'ince')))),
      btn('', ev => saveMenu(k, ev), 'ghost icon sm', 'more', { title: T('Diğer') })),
    h('div', { class: 'row wrap', style: { gap: '6px' } }, ...statusBadges(k)),
    h('div', { class: 'se-card-currencies' },
      h('span', null, art('source_kredi', 'se-currency-icon sm'), fmtShort(k.kredi)), h('span', null, art('source_uridyum', 'se-currency-icon sm'), fmtShort(k.uridyum)),
      h('span', null, icon('ship'), k.ship_appearance ? itemName(k.ship_appearance) : k.gemi), h('span', null, icon('clock'), fmtWhen(k.last_played || k.last_save))),
    k.not_ ? h('div', { class: 'note' }, k.not_) : null,
    h('div', { class: 'row wrap', style: { gap: '6px', marginTop: 'auto' } },
      btn(T('Etkin yap'), () => act(() => api('/api/kayitlar/aktif', { id: k.id }), T('Etkin kayıt: {0}', k.ad)).then(() => { renderSaves(); poll(); }), 'primary sm', 'check'),
      btn(T('Editör'), () => seOpen(k), 'sm', 'edit'),
      btn(T('Yedekler'), () => backupsModal(k.id), 'sm ghost', 'clock')));
}

function trash(entries) {
  if (!entries.length) return null;
  const d = h('details', { class: 'card se-trash', open: KL.trash, ontoggle: e => { KL.trash = e.target.open; } },
    h('summary', null, icon('trash'), T('Silinenler ({0})', entries.length), h('span', { class: 'small muted' }, T('Silinen kayıtlar burada bekler; geri alabilir ya da kalıcı olarak silebilirsin.'))),
    h('table', { class: 'table' }, h('thead', null, h('tr', null, h('th', null, T('Kayıt')), h('th', null, T('Pilot')), h('th', null, T('Silinme')), h('th'))),
      h('tbody', null, entries.map(x => h('tr', null, h('td', null, x.ad), h('td', null, `${x.pilot} · ${lvl(x.seviye)}`), h('td', { class: 'muted' }, fmtWhen(x.deletion)),
        h('td', { class: 'num' }, h('div', { class: 'actions', style: { justifyContent: 'flex-end' } },
          btn(T('Geri al'), () => act(() => api('/api/kayitlar/geri_al', { dosya: x.dosya }), T('Kayıt geri alındı.')).then(renderSaves), 'sm', 'undo'),
          btn(T('Kalıcı sil'), async () => {
            if (await confirmBox(T('Kalıcı olarak silinsin mi?'), T('"{0}" kaydı ve yedekleri diskten silinir. Bu geri alınamaz.', x.ad), { ok: T('Kalıcı sil'), danger: true }))
              act(() => api('/api/kayitlar/empty_trash', { dosya: x.dosya }), T('Kalıcı olarak silindi.')).then(renderSaves);
          }, 'danger sm', 'trash'))))))),
    entries.length > 1 ? h('div', { class: 'row', style: { marginTop: '12px', justifyContent: 'flex-end' } },
      btn(T('Çöp kutusunu boşalt'), async () => {
        if (await confirmBox(T('Çöp kutusu boşaltılsın mı?'), T('{0} kayıt kalıcı olarak silinir.', entries.length), { ok: T('Boşalt'), danger: true }))
          act(() => api('/api/kayitlar/empty_trash', {}), T('Çöp kutusu boşaltıldı.')).then(renderSaves);
      }, 'danger sm', 'trash')) : null);
  return d;
}

// ================================================================== KARAKTER EDİTÖRÜ
const SE = { slot: null, ad: '', v: null, tab: 'pilot', gemi: null, config: null, busy: false, catalog: null, search: '', ammoFilled: false, invKind: 'hepsi', resourceSearch: '' };
const SE_TABS = [
  ['pilot', N('Pilot'), 'user', 'pilotSheet_normal'], ['hangar', N('Hangar'), 'hangar', 'hangar_normal'], ['drones', N('Dronlar'), 'drone', null],
  ['pet', 'P.E.T.', 'paw', 'pet_normal'], ['inventory', N('Envanter'), 'box', 'assembly_normal'], ['ammunition', N('Cephane'), 'ammo', null],
  ['sources', N('Kaynaklar'), 'gem', 'refinement_normal'], ['boosters', N('Boosterlar'), 'zap', 'booster_normal'], ['maintenance', N('Bakım'), 'wrench', 'settings_normal'],
  ['stats', N('İstatistik'), 'star', null],
];
const SE_CATEGORY = { hepsi: N('Hepsi'), gemi: N('Gemiler'), tasarim: N('Gemi tasarımları'), lazer: N('Lazerler'), rocket_launcher: N('Roketatarlar'), generator: N('Jeneratörler'),
  ekstra: N('Ekstralar ve CPU'), modul: N('Modüller ve çekirdekler'), heavy: N('Ağır silahlar'), drone: N('Dronlar ve formasyonlar'), pet: 'P.E.T.', ammunition: N('Cephane'),
  booster: N('Boosterlar'), kaynak: N('Kaynaklar'), paket: N('Paketler'), other: N('Diğer') };
const SE_CATEGORY_ICON = { hepsi: 'layers', gemi: 'ship', tasarim: 'wand', lazer: 'zap', rocket_launcher: 'target', generator: 'shield', ekstra: 'cpu', modul: 'layers', heavy: 'crosshair',
  drone: 'drone', pet: 'paw', ammunition: 'ammo', booster: 'zap', kaynak: 'gem', paket: 'gift', other: 'box' };
const SE_AMMO = [['lazer', N('Lazer cephanesi')], ['roket', N('Roketler')], ['rocket_launcher', N('Roketatar cephanesi')], ['mayin', N('Mayınlar')], ['ozel', N('Özel cephane')], ['other', N('Diğer')]];
const SE_RESET = [['hints', N('İpuçlarını yeniden göster (kapattıkların ve gösterilenler, etkinlik bildirimleri)')],
  ['ui', N('Menü çubuklarının ve pencerelerin yerini varsayılana döndür')], ['game_settings', N('Oyunun Ayarlar penceresini (grafik, ses, oynanış) varsayılana döndür')],
  ['active_quests', N('Alınmış görevleri bırak (bitirilenler kalır)')], ['history', N('Seyir defterini ve hesap geçmişini boşalt')]];
const SE_FIELD = { ad: N('Pilot adı'), firma: N('Firma'), seviye: N('Seviye'), ep: N('Deneyim (EP)'), kredi: N('Kredi'), uridyum: N('Uridyum'), onur: N('Onur'),
  premium: 'Premium', active_ship: N('Etkin gemi'), harita: N('Harita'), can: N('Gemi canı') };

function seOpen(k) {
  Object.assign(SE, { slot: k.id, ad: k.ad, v: null, tab: 'pilot', gemi: null, config: null });
  $('#content').scrollTop = 0;
  renderEditor();
}
function seClose() { SE.slot = null; SE.v = null; renderSaves(); }

async function renderEditor() {
  await loadGameImages();
  if (!GI.index) return seLock();
  if (!SE.v) {
    const v = await act(() => api('/api/editor?id=' + encodeURIComponent(SE.slot)));
    if (!v) { SE.slot = null; return renderSaves(); }
    if (S.page !== 'saves' || !SE.slot) return;
    SE.v = v;
    if (v.discarded) toast(T('Kayıt editörde açıldıktan sonra değişmiş (oyun oynandı ya da yedek geri yüklendi): eski taslak atıldı.'), 'info', 7000);
  }
  seRender();
}

// oyunun görselleri yok (oyun kurulmadı ya da BepInEx ile hiç açılmadı): editör eşyaları ancak oyunun simgeleri ve adlarıyla
// anlaşılır gösterebilir; kitaplık (kayıt kartları) görselsiz de çalışır
function seLock() {
  if (S.page !== 'saves' || !SE.slot) return;
  $('#content').replaceChildren(h('div', { class: 'stack ke-editor' },
    h('div', { class: 'card se-bar' }, btn(T('Kayıtlar'), seClose, 'ghost', 'arrowL'),
      h('div', { class: 'se-bar-name' }, h('b', null, SE.ad || SE.slot), h('div', { class: 'small muted' }, T('Karakter editörü')))),
    h('div', { class: 'card empty se-lock' }, art('drone_lock'), h('h3', null, T('Oyunun görselleri henüz hazır değil')),
      h('p', null, T('Karakter editörü eşyaları oyunun kendi simgeleri, adları ve açıklamalarıyla gösterir. Oyunu kur ve bir kez OYNA ile aç: görseller ilk açılışta hazırlanır, sonra editör açılır.')),
      h('div', { class: 'row', style: { justifyContent: 'center', gap: '8px' } }, btn(T('İstemci sayfası'), () => go('client'), 'primary', 'monitor'),
        btn(T('Yeniden dene'), () => renderEditor(), '', 'refresh')))));
}

// işlemleri taslağa uygula (kayit_editoru.ISLEMLER); başarıda yeni görünüm çizilir -> başarılı mı
async function seApply(...ops) {
  if (!SE.v || SE.v.read_only || SE.busy) return false;
  SE.busy = true; document.body.classList.add('se-busy');
  const v = await act(() => api('/api/editor/uygula', { id: SE.slot, ops }));
  SE.busy = false; document.body.classList.remove('se-busy');
  if (v && SE.slot) { SE.v = v; seRender(); return true; }
  return false;
}

// Arama kutusu: editör (bütün sekme ve eşya döşemeleri) her tuşta değil yazma durunca yeniden kurulur; imleç yerinde kalır
function seSearch(e, assign) {
  assign(e.target.value); clearTimeout(SE.searchTimer);
  SE.searchTimer = setTimeout(() => {
    if (!e.target.isConnected) return;          // bu arada sayfa ya da sekme değişti
    const pos = e.target.selectionStart; seRender();
    const new_ = $('.se-main .game-search'); if (new_) { new_.focus(); new_.setSelectionRange(pos, pos); }
  }, 150);
}
function seRender() {
  if (S.page !== 'saves' || !SE.slot || !SE.v) return;
  const v = SE.v, c = $('#content'), sc = c.scrollTop;
  const tab = SE_TABS.find(s => s[0] === SE.tab) || SE_TABS[0];
  c.replaceChildren(h('div', { class: 'stack ke-editor' }, seBar(v),
    v.read_only ? h('div', { class: 'alert warning' }, icon('lock'), h('div', null, h('b', null, T('Kayıt şu an oyunda: yalnız görüntüleniyor.')), ' ',
      T('Değiştirmek için oyunu ve sunucuyu kapat. Oyun açıkken donanım ve alışveriş için oyun içi Hangar ve Mağaza sayfaları var.'))) : null,
    h('div', { class: 'se-layout' },
      h('aside', { class: 'se-side' }, seIdentity(v), seMenu(v)),
      h('div', { class: 'se-main' }, h('div', { class: 'se-main-head' }, seTabIcon(tab, 30), h('div', null, h('h2', null, T(tab[1])), h('div', { class: 'small muted' }, seTabDescription(tab[0])))),
        SE_RENDER[tab[0]](v)))));
  c.scrollTop = sc;
}

// sekme ikonu: panelin görseli (images/ke_<sekme>.webp, Orders.md OP-013: teslim edilenler KE_GORSEL'e), yoksa oyunun menü sprite'ı, o da yoksa çizgi ikon
const SE_IMAGE = new Set(['pilot', 'hangar', 'drones', 'pet', 'inventory', 'ammunition', 'sources', 'boosters', 'maintenance']);
const seTabIcon = (s, size) => SE_IMAGE.has(s[0]) ? h('span', { class: 'se-tab-icon gorsel' }, art('ke_' + s[0], 'se-tab-art'))
  : s[3] && GI.index?.sprite[s[3]] ? h('span', { class: 'se-tab-icon oyun' }, sprite(s[3], size)) : h('span', { class: 'se-tab-icon' }, icon(s[2]));
const seTabDescription = id => T({ pilot: N('Ad, firma, seviye, deneyim, onur ve cüzdan.'), hangar: N('Gemiler, iki config, tasarımlar ve yuvalar: tıkla, tak ya da çıkar.'),
  drones: N('Dronlar, seviyeleri, yükseltmeleri ve donanımları.'), pet: N('P.E.T.: seviye, yakıt, açık yuvalar ve donanım.'),
  inventory: N('Takılı olmayan eşyalar: tak, seviyesini değiştir ya da sil.'), ammunition: N('Lazer cephanesi, roketler, mayınlar ve özel cephane.'),
  sources: N('Kargodaki cevherler ve toplanabilir kaynaklar.'), boosters: N('Süreli bonuslar ve kalan süreleri.'),
  maintenance: N('Onarım, ana istasyon, tuş atamaları ve durum sıfırlama.'),
  stats: N('Rütbe puanının parçaları, öldürülen uzaylılar ve oyuncular, ölümler, kapı süreleri.') }[id]);

function seBar(v) {
  const f = v.diff || { sayi: 0 }, ro = v.read_only;
  return h('div', { class: 'card se-bar' },
    btn(T('Kayıtlar'), seClose, 'ghost', 'arrowL'),
    h('div', { class: 'se-bar-name' }, h('b', null, SE.ad || SE.slot), h('div', { class: 'small muted' }, T('Karakter editörü'))),
    h('span', { class: 'spacer' }),
    ro ? badge(T('Salt okunur'), 'warn')
      : f.sayi ? h('button', { class: 'se-change exists', type: 'button', onclick: seChanges, title: T('Değişiklikleri gör') }, h('span', { class: 'se-pulse' }), T('{0} değişiklik kaydedilmedi', f.sayi), icon('chevR'))
        : h('span', { class: 'se-change' }, icon('check'), T('Kayıtla aynı')),
    ro ? null : btn(T('Vazgeç'), seCancel, 'ghost', 'undo', { disabled: !f.sayi }),
    ro ? null : btn(T('Kaydet'), seSave, 'primary', 'save', { disabled: !f.sayi }));
}

function seIdentity(v) {
  const p = v.pilot, d = v.durum, g = v.ships.find(x => x.active) || v.ships[0], f = companyLower(p.firma);
  const sell = (name, n, tag) => h('div', { class: 'se-wallet-row' }, art('source_' + name, 'se-currency-icon'), h('span', null, tag), h('b', null, fmtN(n)));
  const value = (sp, iconEl, n, m) => h('div', { class: 'se-value', title: m != null ? fmtN(n) + ' / ' + fmtN(m) : fmtN(n) }, spr(sp, 20, iconEl), h('b', null, fmtShort(n)));
  return h('div', { class: 'card se-identity f-' + f },
    h('div', { class: 'se-identity-scene' }, h('div', { class: 'se-ring' }), shipImage(g.appearance, 170, f)),
    h('div', { class: 'se-identity-head' }, portrait(p.firma, 'se-portrait lowercase', 84),
      h('div', { style: { minWidth: 0 } }, h('div', { class: 'se-identity-name' }, p.ad), h('div', { class: 'se-pilot small' }, p.klan ? h('span', { class: 'se-clan' }, '[' + p.klan + ']') : null,
        badge(COMPANY_TAG[p.firma] || '?', firmaCls(COMPANY_TAG[p.firma])), p.premium ? badge('Premium', 'orange') : null))),
    h('div', { class: 'se-lv sm' }, h('div', { class: 'se-lv-num' }, h('small', null, T('Sv')), h('b', null, p.seviye)),
      h('div', { class: 'grow' }, h('div', { class: 'row between small muted' }, h('span', null, itemName(g.lootId)), h('span', { class: 'mono' }, fmtShort(p.ep) + ' EP')),
        epBar(p.ep, p.level_base, p.next_level))),
    h('div', { class: 'se-wallet' }, sell('kredi', p.kredi, T('Kredi')), sell('uridyum', p.uridyum, T('Uridyum')), sell('onur', p.onur, T('Onur'))),
    h('div', { class: 'se-values' }, value('hitpoints_100x100', 'heart', d.can, d.max_hp), value('shield_100x100', 'shield', d.kalkan, d.shield_max),
      value('speed_100x100', 'gauge', g.value.hiz), value('damage_laser_100x100', 'zap', g.value.hasar)));
}

function seMenu(v) {
  const n = { hangar: v.ships.length, drones: v.drones.length, inventory: v.inventory.filter(e => !seIsEquipped(e)).length, boosters: v.boosters.length,
    sources: v.sources.length + v.ores.filter(c => c[2]).length, ammunition: v.ammunition.filter(c => c[1]).length };
  return h('nav', { class: 'card se-menu' }, SE_TABS.map(s => h('button', { class: s[0] === SE.tab ? 'on' : '', type: 'button',
    onclick: () => { if (SE.tab !== s[0]) { SE.tab = s[0]; $('#content').scrollTop = 0; seRender(); } } },
  seTabIcon(s, 20), h('span', null, T(s[1])), n[s[0]] ? h('span', { class: 'se-count' }, fmtN(n[s[0]])) : s[0] === 'pet' && !v.pet ? h('span', { class: 'se-count none' }, '—') : null)));
}

// ---- ortak parçalar
const seCard = (title, iconEl, ...body) => h('div', { class: 'card se-card' }, title ? h('h2', null, icon(iconEl), title) : null, ...body);
function numberBox(value, update, { min = 0, max = null, cls = '' } = {}) {
  return h('input', { class: 'input num ' + cls, type: 'number', min, max, step: 1, value: value, disabled: SE.v.read_only,
    onchange: e => { const n = Math.round(+e.target.value); if (!Number.isFinite(n)) { e.target.value = value; return; }
      const x = Math.max(min, max != null ? Math.min(max, n) : n); if (x !== value) update(x); else e.target.value = value; },
    onkeydown: e => { if (e.key === 'Enter') e.target.blur(); } });
}
// kaydırıcı: iz tutamağa kadar dolar (panel.css input[type=range] --p; min ve max value'dan önce verilmeli)
function slider(props, cls = '') {
  const el = h('input', Object.assign({ type: 'range', class: 'se-range ' + cls }, props));
  const filler = () => el.style.setProperty('--p', (el.value - el.min) / Math.max(1e-9, el.max - el.min) * 100 + '%');
  el.addEventListener('input', filler);
  filler();
  return el;
}
// küçük artı/eksi kutusu: [−] n / azami [+]
function stepBox(n, maximum, update, { min = 0 } = {}) {
  const ro = SE.v.read_only;
  return h('div', { class: 'se-stepper' }, h('button', { type: 'button', disabled: ro || n <= min, onclick: () => update(n - 1) }, icon('minus')),
    h('span', null, h('b', null, n), maximum != null ? ' / ' + maximum : ''), h('button', { type: 'button', disabled: ro || (maximum != null && n >= maximum), onclick: () => update(n + 1) }, icon('plus')));
}
function seShip(v) {
  let g = v.ships.find(x => x.id === SE.gemi);
  if (!g) { g = v.ships.find(x => x.active) || v.ships[0]; SE.gemi = g.id; }
  if (!g.configs[SE.config]) SE.config = g.active_config;
  return g;
}
// gemi ve config seçimi (Dronlar ve P.E.T. donanımı da geminin config'inde durur)
function shipPicker(v, g) {
  return h('div', { class: 'row wrap se-picker' }, h('span', { class: 'lbl' }, T('Gemi')),
    h('select', { class: 'input', onchange: e => { SE.gemi = e.target.value; SE.config = null; seRender(); } },
      v.ships.map(x => h('option', { value: x.id, selected: x.id === g.id }, itemName(x.lootId) + (x.active ? ' · ' + T('etkin') : '')))),
    h('div', { class: 'seg' }, Object.keys(g.configs).map(c => h('button', { class: c === SE.config ? 'on info' : '', onclick: () => { SE.config = c; seRender(); } },
      T('Config {0}', c), c === g.active_config ? ' •' : ''))));
}
const moveOp = (id, direction, tgt) => ({ islem: 'carry', direction, hedef: tgt.hedef, gemi: SE.gemi, config: +SE.config, drone: tgt.drone || 0, set: tgt.set || '', esya: id });
const equipTarget = tgt => ({ hedef: tgt.hedef, gemi: SE.gemi, config: +SE.config, drone: tgt.drone || 0, set: tgt.set || '' });
const lvlBadge = e => [e.upgrade ? h('span', { class: 'se-badge-lv' }, '+' + e.upgrade) : null, e.seviye ? h('span', { class: 'se-badge-lv left' }, T('Sv {0}', e.seviye)) : null];

// eşya simgeli düğme: ipucu örneğin bilgisini (yükseltme, rastgele nitelikler, CPU hakkı) düğmenin _esya'sından okur
function seItemButton(props, e, ...kids) {
  const b = h('button', props, ...kids);
  b._item = SE.v.haklar[e.lootId] ? Object.assign({}, e, { right: SE.v.haklar[e.lootId] }) : e;
  return b;
}
const seIsEditable = e => !!(e.azami || e.seviye || e.rng || SE.v.haklar[e.lootId]);
function seCell(e, tgt) {
  return seItemButton({ class: 'se-cell full', type: 'button', onclick: ev => !SE.v.read_only && seItemMenu(ev.currentTarget, e, tgt) }, e,
    itemIcon(e.lootId, 44), ...lvlBadge(e));
}
const seEmptyCell = (tgt, iconEl = 'plus', title = T('Boş yuva: tak')) => h('button', { class: 'se-cell vacant', type: 'button', title: title, disabled: SE.v.read_only,
  onclick: () => sePickEquip(tgt) }, icon(iconEl));
function seSlotBox(name, c, tgt, extra) {
  return h('div', { class: 'se-slot' + (c.esyalar.length >= c.capacity && c.capacity ? ' dolu' : '') },
    h('div', { class: 'se-slot-head' }, h('b', null, name), h('span', { class: 'row', style: { gap: '6px' } }, extra, h('span', { class: 'mono' }, c.esyalar.length + ' / ' + c.capacity))),
    h('div', { class: 'se-cells' }, c.esyalar.map(e => seCell(e, tgt)), Array.from({ length: Math.max(0, c.capacity - c.esyalar.length) }, () => seEmptyCell(tgt))));
}
function seItemMenu(anchor, e, tgt) {
  popMenu(anchor, [
    { label: T('Çıkar (envantere)'), ic: 'download', fn: () => seApply(moveOp(e.id, 'kick', tgt)) },
    seIsEditable(e) ? { label: T('Düzenle…'), ic: 'edit', fn: () => seEdit(e) } : null,
    '-',
    { label: T('Çıkar ve sil'), ic: 'trash', danger: true, fn: () => seApply(moveOp(e.id, 'kick', tgt), { islem: 'delete', esyalar: [e.id] }) },
  ].filter(Boolean));
}

// ---- eşya düzenleme: yükseltme seviyesi (Assembly), P.E.T. dişlisinin/protokolünün seviyesi, CPU'nun hakkı ve rastgele nitelikler
// (kararsız modül: nitelikler kesir, gemiler, yeniden çekme hakkı; parçacık silahı: nitelikler yüzde, hak, topun yıldızı; QFC: bağlı
// gemi, seviye, nitelikler yüzde). Oyunun aralığı ipucu olarak yazılır; değer serbest. Hepsi tek işlem listesiyle taslağa.
function seEdit(e) {
  const v = SE.v, pool = v.pools[e.lootId], r = e.rng || {}, right = v.haklar[e.lootId], fraction = pool?.unit === 'fraction';
  const st = { upgrade: e.upgrade || 0, seviye: e.seviye, cpu: right ? right[0] : null, attribute: (r.nitelik || []).map(([a, x]) => [a, fraction ? x * 100 : x]),
    ships: [...(r.ships || [])], gemi: r.gemi || v.ships.find(g => g.active)?.lootId, qlevel: r.seviye || 1, right: r.right ?? pool?.right, star: r.star || 0 };
  const sections = [], sortedShips = () => [...v.all_ships].sort((a, b) => itemName(a).localeCompare(itemName(b)));
  const title = (t, extra) => h('div', { class: 'row between' }, h('div', { class: 'lbl' }, t), extra ? h('span', { class: 'small dim' }, extra) : null);
  if (e.azami) {
    const out = h('b', { class: 'se-lv-value' }, '+' + st.upgrade);
    sections.push(h('div', { class: 'se-edit' }, title(T('Yükseltme seviyesi')), h('div', { class: 'se-lv-pick' }, out,
      h('div', { class: 'grow' }, slider({ min: 0, max: e.azami, value: st.upgrade, oninput: x => { st.upgrade = +x.target.value; out.textContent = '+' + st.upgrade; } }),
        h('div', { class: 'row between small dim' }, h('span', null, '0'), h('span', null, '+' + e.azami))))));
  }
  if (e.seviye) {
    const seg = h('div', { class: 'seg' });
    const render = () => seg.replaceChildren(...[1, 2, 3, 4].map(n => h('button', { class: n === st.seviye ? 'on info' : '', onclick: () => { st.seviye = n; render(); } }, T('Sv {0}', n))));
    render();
    sections.push(h('div', { class: 'se-edit' }, title(T('P.E.T. seviyesi')), seg));
  }
  if (right) sections.push(h('div', { class: 'se-edit' }, title(T('Kalan hak'), T('Bir dolum {0} hak; hak bu eşya türünün bütün örnekleri için ortak.', fmtN(right[1]))),
    h('input', { class: 'input num', type: 'number', min: 0, value: st.cpu, oninput: x => { st.cpu = Math.max(0, Math.round(+x.target.value) || 0); } })));
  if (pool) {
    const lines = h('div', { class: 'se-attr' });
    const renderAttributes = () => lines.replaceChildren(...[...st.nitelik.map((n, i) => h('div', { class: 'se-attr-row' },
      h('select', { class: 'input', onchange: x => { n[0] = x.target.value; renderAttributes(); } }, pool.nitelik.map(a => h('option', { value: a, selected: a === n[0],
        disabled: a !== n[0] && st.nitelik.some(m => m[0] === a) }, attributeName(a)))),
      h('label', { class: 'se-percent' }, h('input', { class: 'input num', type: 'number', min: 0, step: 0.1, value: Math.round(n[1] * 100) / 100,
        oninput: x => { n[1] = Math.max(0, +x.target.value || 0); } }), '%'),
      btn('', () => { st.nitelik.splice(i, 1); renderAttributes(); }, 'ghost sm icon', 'x', { title: T('Kaldır') }))),
    st.nitelik.length < pool.max_attributes ? btn(T('Nitelik ekle'), () => {
      const a = pool.nitelik.find(x => !st.nitelik.some(m => m[0] === x)); if (a) { st.nitelik.push([a, pool.interval[0]]); renderAttributes(); }
    }, 'sm ghost', 'plus') : null].filter(Boolean));
    renderAttributes();
    sections.push(h('div', { class: 'se-edit' }, title(T('Nitelikler'), T('Oyunda {0}–{1}%, en çok {2} nitelik', fmtN(pool.interval[0]), fmtN(pool.interval[1]), pool.max_attributes)),
      !e.rng?.nitelik ? h('div', { class: 'small muted' }, T('Nitelikler henüz çekilmedi: Uygula oyundaki gibi çeker, sonra senin değerlerin yazılır.')) : null, lines));
    if (pool.preference) {
      const chips = h('div', { class: 'se-ship-chips' });
      const add = h('select', { class: 'input', onchange: x => { if (x.target.value && !st.ships.includes(x.target.value)) st.ships.push(x.target.value); renderShip(); } });
      const renderShip = () => {
        chips.replaceChildren(...st.ships.map((g, i) => h('span', { class: 'chip' }, gameIcon(g, 22, companyLower(v.pilot.firma), 'ship'), itemName(g),
          h('button', { class: 'btn ghost sm icon', type: 'button', onclick: () => { st.ships.splice(i, 1); renderShip(); } }, icon('x')))));
        add.replaceChildren(h('option', { value: '' }, T('Gemi ekle…')), ...sortedShips().filter(g => !st.ships.includes(g))
          .map(g => h('option', { value: g }, (pool.preference.includes(g) ? '★ ' : '') + itemName(g))));
      };
      renderShip();
      sections.push(h('div', { class: 'se-edit' }, title(T('Geçtiği gemiler'), T('★ oyunda daha sık çıkanlar')), chips, add));
    }
    if (pool.max_level) {
      sections.push(h('div', { class: 'grid g2' },
        field(T('Bağlı gemi'), h('select', { class: 'input', onchange: x => { st.gemi = x.target.value; } },
          sortedShips().map(g => h('option', { value: g, selected: g === st.gemi }, itemName(g))))),
        field(T('Seviye'), h('input', { class: 'input num', type: 'number', min: 1, max: pool.max_level, value: st.qlevel,
          oninput: x => { st.qlevel = Math.max(1, Math.min(pool.max_level, Math.round(+x.target.value) || 1)); } }))));
    }
    if (pool.right) {
      const k = h('span');
      const c = () => k.replaceChildren(stepBox(st.right, pool.right, n => { st.right = n; c(); }));
      c();
      sections.push(h('div', { class: 'se-edit satir' }, h('div', { class: 'lbl' }, T('Yeniden çekme hakkı')), k));
    }
    if (pool.star) {
      const stars = h('div', { class: 'se-stars' });
      const c = () => stars.replaceChildren(...Array.from({ length: pool.star + 1 }, (_, n) => h('button', { type: 'button', class: n && n <= st.star ? 'on' : '',
        title: n ? '★'.repeat(n) : T('Yıldızsız'), onclick: () => { st.star = n; c(); } }, icon(n ? 'star' : 'x'))));
      c();
      sections.push(h('div', { class: 'se-edit satir' }, h('div', { class: 'lbl' }, T('Yıldız')), stars));
    }
  }
  const m = modal({ title: T('Eşyayı düzenle'), sub: itemName(e.lootId), wide: !!pool,
    body: [h('div', { class: 'se-edit-head' }, itemIcon(e.lootId, 56), h('div', { class: 'small muted' }, T('Değişiklikler taslağa yazılır; Kaydet\'e basınca kayda geçer.'))), ...sections],
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Uygula'), async () => {
      const ops = [];
      if (e.azami && st.upgrade !== (e.upgrade || 0)) ops.push({ islem: 'item_level', esya: e.id, upgrade: st.upgrade });
      if (e.seviye && st.seviye !== e.seviye) ops.push({ islem: 'item_level', esya: e.id, seviye: st.seviye });
      if (right && st.cpu !== right[0]) ops.push({ islem: 'cpu_charges', lootId: e.lootId, right: st.cpu });
      if (pool) {
        if (!st.nitelik.length && e.rng?.nitelik) return toast(T('En az bir nitelik gerekli.'), 'err');
        const o = { islem: 'rng', esya: e.id };
        if (st.nitelik.length) o.nitelik = st.nitelik.map(([a, x]) => [a, fraction ? x / 100 : x]);
        if (pool.preference) { if (!st.ships.length) return toast(T('En az bir gemi seç.'), 'err'); o.ships = st.ships; }
        if (pool.max_level) { o.gemi = st.gemi; o.seviye = st.qlevel; }
        if (pool.right) o.right = st.right;
        if (pool.star) o.star = st.star;
        ops.push(o);
      }
      if (!ops.length) return m.close();
      if (await seApply(...ops)) { m.close(); toast(T('Eşya güncellendi (taslakta).'), 'ok'); }
    }, 'primary', 'check')] });
}

// envanteri gruplar: aynı lootId ve seviyedekiler tek kutuda (adet); rastgele nitelikliler (modül, top, QFC) tek tek
// item equipped somewhere (its ship and configs); the game lets another config of the same ship use it too
const seIsEquipped = e => !!(e.configs && e.configs.length);
const seIsUsable = e => !seIsEquipped(e) || (e.gemi === SE.gemi && !e.configs.includes(String(SE.config)));
function groupItems(entries) {
  const gr = {};
  for (const e of entries) { const k = [e.lootId, e.upgrade || 0, e.seviye || 0, e.rng ? e.id : ''].join('|'); (gr[k] = gr[k] || []).push(e); }
  return Object.values(gr).sort((a, b) => itemName(a[0].lootId).localeCompare(itemName(b[0].lootId)));
}
// boş yuvaya tak: envanterde uyanlar ya da katalogdan ver ve tak
function sePickEquip(tgt) {
  const v = SE.v;
  const eligible = v.inventory.filter(e => seIsUsable(e) && (tgt.hedef === 'ship' ? e.targets.includes('ship') && e.yuva === tgt.yuva
    : tgt.hedef === 'drone' ? e.targets.includes('drone') && (tgt.yuva === 'tasarim') === (e.yuva === 'tasarim')
      : e.targets.includes('pet') && (tgt.yuva === 'heat' ? e.heat : e.pet_yuva === tgt.yuva)))
    .sort((a, b) => seIsEquipped(b) - seIsEquipped(a));          // items of the other config first: free copies stay free
  const title = tgt.hedef === 'drone' ? (tgt.yuva === 'tasarim' ? T('Dron tasarımı') : T('Dron donanımı')) : slotName(tgt.yuva);
  const m = modal({ title: T('{0}: eşya tak', title), wide: true, body: [
    eligible.length ? h('div', { class: 'se-selection' }, groupItems(eligible).map(gr => seItemButton({ class: 'se-selection-item', type: 'button',
      onclick: () => { m.close(); seApply(moveOp(gr[0].id, 'equip', tgt)); } }, gr[0], itemIcon(gr[0].lootId, 56), ...lvlBadge(gr[0]),
      h('span', { class: 'ad' }, itemName(gr[0].lootId)), gr.length > 1 ? h('span', { class: 'se-qty' }, '×' + gr.length) : null)))
      : h('div', { class: 'empty' }, icon('box'), h('div', null, T('Envanterde buraya takılabilecek eşya yok.'))),
    h('div', { class: 'se-selection-bottom' }, h('span', { class: 'small muted' }, T('Envanterde yoksa katalogdan ekleyip doğrudan buraya takabilirsin.')),
      btn(T('Katalogdan ekle ve tak'), () => { m.close(); seCatalog({ equip: tgt, title }); }, 'primary sm', 'plus'))],
  foot: [btn(T('Kapat'), () => m.close(), 'ghost')] });
}

// ---- katalog: eklenebilecek her şey, kategoriler, arama, adet (oyunun ödül yolu)
async function seCatalog(o = {}) {
  if (!SE.catalog) { const r = await act(() => api('/api/editor/katalog')); if (!r) return; SE.catalog = r; }
  let entries = SE.catalog.esyalar;
  if (o.equip) entries = entries.filter(([, , gy, py, dr]) => o.equip.hedef === 'ship' ? gy === o.equip.yuva
    : o.equip.hedef === 'pet' ? (o.equip.yuva === 'heat' ? py === 'lasers' || py === 'generators' : py === o.equip.yuva) : dr && (o.equip.yuva === 'tasarim') === (gy === null && !py));
  if (o.on) entries = entries.filter(([l]) => l.startsWith(o.on));
  const tally = {}; for (const [, k] of entries) tally[k] = (tally[k] || 0) + 1;
  const categories = ['hepsi', ...SE.catalog.categories.filter(k => tally[k])];
  const st = { multiplier: o.multiplier && tally[o.multiplier] ? o.multiplier : categories.length === 2 ? categories[1] : 'hepsi', search: '', sec: null };
  const grid = h('div', { class: 'se-cat-grid' }), left = h('div', { class: 'se-cat-list' }), sub = h('div', { class: 'se-cat-bottom' });
  const search = h('input', { class: 'input', placeholder: T('Ara: ad ya da lootId…'), oninput: e => { st.search = e.target.value.trim().toLowerCase(); render(); } });
  const render = () => {
    left.replaceChildren(...categories.map(k => h('button', { class: k === st.multiplier ? 'on' : '', type: 'button', onclick: () => { st.multiplier = k; render(); } },
      icon(SE_CATEGORY_ICON[k] || 'box'), h('span', null, T(SE_CATEGORY[k] || k)), h('small', null, fmtN(k === 'hepsi' ? entries.length : tally[k])))));
    const its = entries.filter(([l, k]) => (st.multiplier === 'hepsi' || k === st.multiplier) && (!st.search || l.includes(st.search) || itemName(l).toLowerCase().includes(st.search)));
    const visible = its.slice(0, 300);
    // seçim yalnız sınıfı değiştirir (ızgara yeniden çizilirse kaydırma başa dönerdi)
    const sec = (l, el) => { st.sec = l; grid.querySelectorAll('.se-cat-item.on').forEach(x => x.classList.remove('on')); el.classList.add('on'); renderSub(); };
    grid.replaceChildren(...[...visible.map(([l]) => h('button', { class: 'se-cat-item' + (st.sec === l ? ' on' : ''), type: 'button', title: l,
      onclick: e => sec(l, e.currentTarget), ondblclick: e => { sec(l, e.currentTarget); add(); } }, itemIcon(l, 52), h('span', null, itemName(l)))),
    its.length > visible.length ? h('div', { class: 'se-cat-more small muted' }, T('{0} eşyadan ilk {1} tanesi gösteriliyor: aramayı daralt.', fmtN(its.length), visible.length)) : null,
    !its.length ? h('div', { class: 'empty' }, T('Eşya yok.')) : null].filter(Boolean));
    grid.scrollTop = 0;
    renderSub();
  };
  const count = h('input', { class: 'input num', type: 'number', min: 1, value: 1 });
  const single = l => l.startsWith('ship_') || l.startsWith('drone_formation_');
  const renderSub = () => {
    if (!st.sec) return sub.replaceChildren(h('span', { class: 'small muted' }, o.equip ? T('Bir eşya seç: verilir ve doğrudan yuvaya takılır.') : T('Bir eşya seç (çift tıklama hemen ekler).')));
    sub.replaceChildren(...[itemIcon(st.sec, 48), h('div', { class: 'grow', style: { minWidth: 0 } }, h('b', null, itemName(st.sec)), h('div', { class: 'mono small dim' }, st.sec)),
      single(st.sec) ? null : h('label', { class: 'row small' }, T('Adet'), count), btn(o.equip ? T('Ver ve tak') : T('Ekle'), add, 'primary', 'plus')].filter(Boolean));
  };
  async function add() {
    if (!st.sec) return;
    const n = single(st.sec) ? 1 : Math.max(1, Math.round(+count.value) || 1), lid = st.sec;
    const ok = await seApply({ islem: 'give', esyalar: [[lid, n]], equip: o.equip ? equipTarget(o.equip) : undefined });
    if (ok) { toast(T('Eklendi: {0}', (n > 1 ? fmtN(n) + ' × ' : '') + itemName(lid)), 'ok'); if (o.equip) m.close(); }
  }
  const m = modal({ title: o.baslik ? T('Katalog: {0}', o.baslik) : T('Eşya ekle'), wide: true,
    sub: T('Eşyalar oyunun ödül yoluyla verilir: gemi hangara, ekipman envantere, cephane ve kaynaklar sayaçlara.'),
    body: [h('div', { class: 'se-catalog' }, left, h('div', { class: 'se-cat-right' }, search, grid)), sub], foot: [btn(T('Kapat'), () => m.close(), 'ghost')] });
  m.box.classList.add('se-catalog-modal');
  render();
}

// ================================================================== SEKMELER
function sePilot(v) {
  const p = v.pilot, ro = v.read_only;
  const op = x => seApply(Object.assign({ islem: 'pilot' }, x));
  const name = h('input', { class: 'input', value: p.ad, maxlength: 20, disabled: ro, onchange: e => e.target.value.trim() !== p.ad && op({ ad: e.target.value }) });
  const companies = h('div', { class: 'radio-cards' }, FIRMS.map(([id, k, n, c, m]) => h('div', { class: 'radio-card' + (id === p.firma ? ' on' : ''), style: { '--c': c },
    onclick: async () => { if (ro || id === p.firma) return;
      if (await confirmBox(T('Firma değişsin mi?'), T('{0} artık {1} pilotu olur; gemi {2} ana istasyonuna taşınır.', p.ad, k, m), { ok: T('Değiştir') })) op({ firma: id }); } },
  art('firma_' + k.toLowerCase(), 'crest'), h('b', null, k), h('span', null, n))));
  const prem = h('input', { type: 'checkbox', checked: p.premium, disabled: ro, onchange: e => op({ premium: e.target.checked }) });
  const lvlLabel = h('b', null, p.seviye);
  const lv = h('div', { class: 'se-lv-edit' },
    h('div', { class: 'se-lv-large' }, h('button', { class: 'btn icon', type: 'button', disabled: ro || p.seviye <= 1, onclick: () => op({ seviye: p.seviye - 1 }) }, icon('minus')),
      h('div', null, h('small', null, T('Seviye')), lvlLabel),
      h('button', { class: 'btn icon', type: 'button', disabled: ro || p.seviye >= p.max_level, onclick: () => op({ seviye: p.seviye + 1 }) }, icon('plus'))),
    h('div', { class: 'grow' }, slider({ min: 1, max: p.max_level, value: p.seviye, disabled: ro,
      oninput: e => { lvlLabel.textContent = e.target.value; }, onchange: e => +e.target.value !== p.seviye && op({ seviye: +e.target.value }) }),
    h('div', { class: 'row between small dim' }, h('span', null, '1'), h('span', null, p.max_level))));
  const currency = (key, tag, n, fast) => h('div', { class: 'se-currency' }, art('source_' + key, 'se-currency-icon lg'),
    h('div', { class: 'grow' }, h('label', { class: 'lbl' }, tag), numberBox(n, x => op({ [key]: x }), { max: 1e12, cls: 'wide' })),
    h('div', { class: 'se-quick' }, fast.map(x => h('button', { class: 'chip', type: 'button', disabled: ro, onclick: () => op({ [key]: Math.min(1e12, n + x) }) }, '+' + fmtShort(x)))));
  return h('div', { class: 'stack' },
    h('div', { class: 'grid g2' },
      seCard(T('Kimlik'), 'user', field(T('Pilot adı (oyunda görünür)'), name),
        h('label', { class: 'row small', style: { marginTop: '12px' } }, h('span', { class: 'switch' }, prem, h('span')), T('Premium üyelik'))),
      seCard(T('Seviye ve onur'), 'star', lv,
        h('div', { class: 'grid g2', style: { marginTop: '12px' } },
          field(T('Deneyim (EP)'), numberBox(p.ep, x => op({ ep: x }), { max: 2 ** 53, cls: 'wide' })),
          field(T('Onur'), numberBox(p.onur, x => op({ onur: x }), { min: -1e12, max: 1e12, cls: 'wide' }))),
        h('div', { class: 'small dim', style: { marginTop: '8px' } }, p.next_level ? T('Sonraki seviye {0} EP\'de.', fmtN(p.next_level)) : T('En yüksek seviye')))),
    seCard(T('Firma'), 'globe', h('p', { class: 'desc' }, T('Firma değişince gemi yeni firmanın ana istasyonuna taşınır.')), companies),
    seCard(T('Cüzdan'), 'star', h('div', { class: 'grid g2' }, currency('kredi', T('Kredi'), p.kredi, [1e6, 1e7, 1e8]), currency('uridyum', T('Uridyum'), p.uridyum, [1e4, 1e5, 1e6]))),
    seCard(T('Hesap'), 'info', h('div', { class: 'kv' },
      h('div', null, T('Klan'), h('b', null, p.klan ? '[' + p.klan + ']' : '—')), h('div', null, T('Rütbe'), h('b', null, p.rutbe ?? '—')),
      h('div', null, T('Oynama'), h('b', null, fmtDur(p.play_sec))), h('div', null, T('Oluşturma'), h('b', null, fmtWhen(p.created))),
      h('div', null, T('Uridyum bankası'), h('b', null, fmtN(p.bank))), h('div', null, T('Görevler'), h('b', null, T('{0} alınmış · {1} bitmiş', v.quests.active, v.quests.tamam))))));
}

function seHangar(v) {
  const g = seShip(v), ro = v.read_only, f = companyLower(v.pilot.firma), cfg = g.configs[SE.config];
  const strip = h('div', { class: 'se-ships' }, v.ships.map(x => h('button', { class: 'se-ship' + (x.id === g.id ? ' on' : ''), type: 'button', title: itemName(x.lootId),
    onclick: () => { SE.gemi = x.id; SE.config = null; seRender(); } }, shipImage(x.appearance, 62, f), h('span', { class: 'se-ship-name' }, itemName(x.lootId)),
  x.active ? h('span', { class: 'se-active' }, T('Etkin')) : null, x.favorite ? h('span', { class: 'se-star' }, icon('star')) : null)),
  ro ? null : h('button', { class: 'se-ship add', type: 'button', onclick: () => seCatalog({ multiplier: 'gemi', baslik: T('Gemiler') }) },
    h('span', { class: 'se-add-icon' }, icon('plus')), h('span', { class: 'se-ship-name' }, T('Gemi ekle'))));
  const value = (sp, iconEl, name, n) => h('div', { class: 'se-gauge' }, spr(sp, 26, iconEl), h('span', null, name), h('b', null, n == null ? '—' : fmtN(n)));
  const base = g.lootId.replace(/^ship_/, '');
  const designs = h('div', { class: 'se-designs' }, g.designs.map(t => h('button', { class: 'se-design' + (t === g.appearance ? ' on' : ''), type: 'button',
    title: itemName(t), disabled: ro, onclick: () => t !== g.appearance && seApply({ islem: 'tasarim', gemi: g.id, lootId: t }) }, shipImage(t, 46, f))),
  ro ? null : h('button', { class: 'se-design add', type: 'button', title: T('Tasarım ekle'), onclick: () => seCatalog({ multiplier: 'tasarim', on: 'ship_' + base + '_design_', baslik: T('{0} tasarımları', itemName(g.lootId)) }) }, icon('plus')));
  const tools = h('div', { class: 'row wrap', style: { gap: '6px' } },
    g.active ? null : btn(T('Etkin gemi yap'), () => seApply({ islem: 'active_ship', gemi: g.id }), 'sm primary', 'check', { disabled: ro }),
    SE.config !== g.active_config ? btn(T('Bu config\'i kullan'), () => seApply({ islem: 'config', gemi: g.id, config: +SE.config }), 'sm', 'check', { disabled: ro }) : null,
    btn(g.favorite ? T('Favoriden çıkar') : T('Favori yap'), () => seApply({ islem: 'favorite', gemi: g.id, favorite: !g.favorite }), 'sm', 'star', { disabled: ro }),
    btn(T('Aktar…'), () => seTransfer(v, g), 'sm', 'copy', { disabled: ro, title: T('Bu geminin donanımını başka bir gemiye taşır.') }),
    btn(T('Temizle'), async () => await confirmBox(T('Config {0} boşaltılsın mı?', SE.config), T('Gemideki, dronlardaki ve P.E.T.\'teki eşyalar envantere iner.'), { ok: T('Temizle'), danger: true })
      && seApply({ islem: 'clean_up', gemi: g.id, config: +SE.config }), 'sm', 'trash', { disabled: ro }),
    btn(T('Kaldır'), async () => await confirmBox(T('{0} kaldırılsın mı?', itemName(g.lootId)), T('Gemi hangardan çıkar; üstündeki donanım envantere iner. Kaydetmeden önce Vazgeç ile geri alınabilir.'),
      { ok: T('Kaldır'), danger: true }) && seApply({ islem: 'delete_ship', gemi: g.id }), 'sm danger', 'trash', { disabled: ro || g.active, title: g.active ? T('Etkin gemi kaldırılamaz: önce başka bir gemiyi etkin yap.') : '' }));
  return h('div', { class: 'stack' },
    h('div', { class: 'card se-card' }, strip),
    h('div', { class: 'card se-ship-card f-' + f },
      h('div', { class: 'se-ship-scene' }, shipImage(g.appearance, 230, f)),
      h('div', { class: 'se-ship-info' },
        h('div', { class: 'row wrap', style: { gap: '8px' } }, h('h2', { class: 'se-ship-title' }, itemName(g.lootId)),
          g.active ? badge(T('Etkin gemi'), 'ok') : null, g.favorite ? badge(T('Favori'), 'orange') : null),
        g.tasarim ? h('div', { class: 'small muted' }, T('Görünüm: {0}', itemName(g.tasarim))) : null,
        h('div', { class: 'se-gauges' }, value('hitpoints_100x100', 'heart', T('Can'), g.value.can), value('shield_100x100', 'shield', T('Kalkan'), g.value.kalkan),
          value('speed_100x100', 'gauge', T('Hız'), g.value.hiz), value('damage_laser_100x100', 'zap', T('Lazer hasarı'), g.value.hasar), value(null, 'box', T('Kargo'), g.value.kargo)),
        g.designs.length > 1 || !ro ? h('div', null, h('div', { class: 'lbl', style: { marginBottom: '6px' } }, T('Görünüm')), designs) : null,
        h('div', { class: 'seg' }, Object.keys(g.configs).map(c => h('button', { class: c === SE.config ? 'on info' : '', onclick: () => { SE.config = c; seRender(); } },
          T('Config {0}', c), c === g.active_config ? ' •' : ''))),
        tools)),
    h('div', { class: 'se-slots' }, g.slots.map(y => seSlotBox(slotName(y), cfg[y], { hedef: 'ship', yuva: y }))));
}

function seTransfer(v, g) {
  let target = null;
  const entries = h('div', { class: 'se-ships sar' }, v.ships.filter(x => x.id !== g.id).map(x => h('button', { class: 'se-ship', type: 'button', onclick: ev => {
    target = x.id; entries.querySelectorAll('.se-ship').forEach(b => b.classList.toggle('on', b === ev.currentTarget)); } },
  shipImage(x.appearance, 54, companyLower(v.pilot.firma)), h('span', { class: 'se-ship-name' }, itemName(x.lootId)))));
  const m = modal({ title: T('Donanımı aktar'), sub: T('{0} gemisinin iki config\'i, dronları ve P.E.T. donanımı seçtiğin gemiye taşınır.', itemName(g.lootId)), wide: true, body: [entries],
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Aktar'), () => { if (!target) return toast(T('Bir gemi seç.'), 'err'); m.close(); seApply({ islem: 'import_action', gemi: g.id, target }); }, 'primary')] });
}

function seDrones(v) {
  const g = seShip(v), ro = v.read_only, dcfg = g.drones[SE.config] || {};
  const new_ = ['drone_flax', 'drone_iris', 'drone_apis', 'drone_zeus'].map(l => h('button', { class: 'se-drone-add', type: 'button', disabled: ro,
    title: T('{0} ekle', itemName(l)), onclick: () => seApply({ islem: 'give', esyalar: [[l, 1]] }) }, droneImage(l, 1, 40), h('span', null, itemName(l)), icon('plus')));
  const card = d => {
    const c = dcfg[d.id] || { esyalar: [] }, tgt = { hedef: 'drone', drone: d.id }, tgtDesign = { hedef: 'drone', drone: d.id, yuva: 'tasarim' };
    const upgradeLabel = h('b', { class: 'se-lv-value sm' }, '+' + d.upgrade);
    return h('div', { class: 'card se-drone' },
      h('div', { class: 'se-drone-image' }, droneImage(d.lootId, d.seviye, 76)),
      h('div', { class: 'se-drone-body' },
        h('div', { class: 'row between' }, h('b', { class: 'se-drone-name' }, itemName(d.lootId)),
          btn('', async () => await confirmBox(T('{0} kaldırılsın mı?', itemName(d.lootId)), T('Dron kaldırılır; üstündeki eşyalar envantere iner.'), { ok: T('Kaldır'), danger: true })
            && seApply({ islem: 'drone_delete', drone: d.id }), 'ghost sm icon', 'trash', { disabled: ro, title: T('Kaldır') })),
        h('div', { class: 'se-drone-row' }, h('span', { class: 'lbl' }, T('Seviye')),
          h('div', { class: 'se-pips' }, v.drone_levels.map((points, i) => h('button', { class: 'se-pip' + (i < d.seviye ? ' on' : ''), type: 'button', disabled: ro,
            title: T('Seviye {0} ({1} puan)', i + 1, fmtN(points)), onclick: () => i + 1 !== d.seviye && seApply({ islem: 'drone', drone: d.id, seviye: i + 1 }) }))),
          h('span', { class: 'small dim' }, T('{0} puan', fmtN(d.puan)))),
        h('div', { class: 'se-drone-row' }, h('span', { class: 'lbl' }, T('Yükseltme')),
          slider({ min: 0, max: d.max_upgrade, value: d.upgrade, disabled: ro,
            oninput: e => { upgradeLabel.textContent = '+' + e.target.value; }, onchange: e => seApply({ islem: 'drone', drone: d.id, upgrade: +e.target.value }) }), upgradeLabel),
        h('div', { class: 'se-cells' }, c.esyalar.map(e => seCell(e, tgt)), Array.from({ length: Math.max(0, d.capacity - c.esyalar.length) }, () => seEmptyCell(tgt)),
          h('span', { class: 'se-divider' }),
          c.tasarim ? seCell(c.tasarim, tgtDesign) : seEmptyCell(tgtDesign, 'wand', T('Tasarım yuvası')),
          c.appearance ? seCell(c.appearance, tgtDesign) : seEmptyCell(tgtDesign, 'wand', T('Görünüm yuvası')))));
  };
  return h('div', { class: 'stack' },
    h('div', { class: 'card se-card' }, h('div', { class: 'row wrap between', style: { gap: '12px' } }, shipPicker(v, g),
      h('span', { class: 'pill' }, icon('drone'), T('Dronlar'), ' ', h('b', null, v.drones.filter(d => !d.tek).length + ' / ' + v.max_drones))),
    h('p', { class: 'desc', style: { margin: '10px 0 8px' } }, T('Donanım seçili geminin seçili config\'inde durur (oyundaki gibi her geminin iki config\'i).')),
    ro ? null : h('div', { class: 'se-drone-extras' }, new_)),
    v.drones.length ? h('div', { class: 'se-drones' }, v.drones.map(card)) : h('div', { class: 'card empty' }, icon('drone'), h('div', null, T('Dron yok.'))));
}

function sePet(v) {
  const p = v.pet, ro = v.read_only;
  if (!p) return h('div', { class: 'card se-pet-none' }, petImage(0, 150), h('div', null, h('h3', null, T('Bu pilotun P.E.T.\'i yok')),
    h('p', { class: 'muted' }, T('P.E.T. ver: seviye 0, başlangıç yakıtı ve yuvalarıyla gelir; sonra seviyesini ve yuvalarını buradan ayarlayabilirsin.')),
    btn(T('P.E.T. ver'), () => seApply({ islem: 'pet', give: true }), 'primary', 'plus', { disabled: ro })));
  const g = seShip(v), pc = (g.pet || {})[SE.config] || {};
  const op = x => seApply(Object.assign({ islem: 'pet' }, x));
  const lvlLabel = h('b', null, p.seviye), fuelLabel = h('b', { class: 'mono' }, fmtN(p.fuel));
  const name = h('input', { class: 'input', value: p.ad || '', maxlength: 24, disabled: ro, onchange: e => e.target.value.trim() && e.target.value.trim() !== p.ad && op({ ad: e.target.value }) });
  return h('div', { class: 'stack' },
    h('div', { class: 'card se-pet' },
      h('div', { class: 'se-pet-scene' }, h('div', { class: 'se-ring' }), petImage(p.seviye, 190)),
      h('div', { class: 'se-pet-body stack', style: { gap: '14px' } },
        h('div', { class: 'row wrap', style: { gap: '8px' } }, h('h2', { class: 'se-ship-title' }, p.ad || 'P.E.T.'), p.destroyed ? badge(T('Yıkık'), 'err') : badge(T('Hazır'), 'ok'),
          p.heat ? badge('HEAT ' + p.heat, 'orange') : null),
        field(T('Ad'), name),
        h('div', { class: 'se-lv-edit' },
          h('div', { class: 'se-lv-large' }, h('button', { class: 'btn icon', type: 'button', disabled: ro || p.seviye <= 0, onclick: () => op({ seviye: p.seviye - 1 }) }, icon('minus')),
            h('div', null, h('small', null, T('Seviye')), lvlLabel),
            h('button', { class: 'btn icon', type: 'button', disabled: ro || p.seviye >= p.max_level, onclick: () => op({ seviye: p.seviye + 1 }) }, icon('plus'))),
          h('div', { class: 'grow' }, slider({ min: 0, max: p.max_level, value: p.seviye, disabled: ro,
            oninput: e => { lvlLabel.textContent = e.target.value; }, onchange: e => +e.target.value !== p.seviye && op({ seviye: +e.target.value }) }),
          h('div', { class: 'row between small dim' }, h('span', null, '0'), h('span', null, T('{0} EP', fmtN(p.ep))), h('span', null, p.max_level)))),
        h('div', null, h('div', { class: 'row between' }, h('span', { class: 'lbl' }, T('Yakıt')), h('span', null, fuelLabel, h('span', { class: 'dim' }, ' / ' + fmtN(p.max_fuel)))),
          slider({ min: 0, max: p.max_fuel, step: 100, value: p.fuel, disabled: ro,
            oninput: e => { fuelLabel.textContent = fmtN(+e.target.value); }, onchange: e => op({ fuel: +e.target.value }) }, 'fuel')),
        p.destroyed ? btn(T('Onar'), () => op({ repair: true }), 'sm primary', 'wrench', { disabled: ro }) : null)),
    seCard(T('Açık yuvalar'), 'layers', h('p', { class: 'desc' }, T('Oyunda uridyumla açılan yuvalar; seviyenin verdiğinden azı seçilemez.')),
      h('div', { class: 'se-pet-slots' }, Object.keys(p.max_slots).filter(y => y !== 'heat').map(y => h('div', { class: 'se-pet-slot' }, h('span', null, slotName(y)),
        stepBox(p.yuva[y] || 0, p.max_slots[y], n => op({ yuva: { [y]: n } })))))),
    h('div', { class: 'card se-card' }, h('div', { class: 'row wrap between', style: { gap: '12px' } }, h('h2', { style: { margin: 0 } }, icon('box'), T('Donanım')), shipPicker(v, g)),
      h('div', { class: 'se-slots', style: { marginTop: '12px' } }, v.pet_slots.filter(y => pc[y] && (pc[y].capacity || pc[y].esyalar.length))
        .map(y => seSlotBox(slotName(y), pc[y], { hedef: 'pet', yuva: y, set: y === 'heat' ? 'heat' : '' })))));
}

function seInventory(v) {
  const g = seShip(v), ro = v.read_only;
  const empty = v.inventory.filter(e => !seIsEquipped(e));          // inventory tab: only items equipped nowhere (delete, edit)
  const kinds = [...new Set(empty.map(e => e.yuva))];
  if (SE.invKind !== 'hepsi' && !kinds.includes(SE.invKind)) SE.invKind = 'hepsi';
  const q = SE.search.toLowerCase();
  const entries = empty.filter(e => (SE.invKind === 'hepsi' || e.yuva === SE.invKind) && (!q || itemName(e.lootId).toLowerCase().includes(q) || e.lootId.includes(q)));
  const grid = h('div', { class: 'se-inv' }, groupItems(entries).map(gr => {
    const e = gr[0];
    return seItemButton({ class: 'se-inv-item', type: 'button', onclick: ev => !ro && popMenu(ev.currentTarget, [
      e.targets.includes('ship') ? { label: T('Seçili gemiye tak ({0}, config {1})', itemName(g.lootId), SE.config), ic: 'download', fn: () => seApply(moveOp(e.id, 'equip', { hedef: 'ship' })) } : null,
      seIsEditable(e) ? { label: T('Düzenle…'), ic: 'edit', fn: () => seEdit(e) } : null,
      '-',
      { label: T('Bir tanesini sil'), ic: 'trash', danger: true, fn: () => seApply({ islem: 'delete', esyalar: [e.id] }) },
      gr.length > 1 ? { label: T('Hepsini sil ({0})', gr.length), ic: 'trash', danger: true, fn: () => seApply({ islem: 'delete', esyalar: gr.map(x => x.id) }) } : null,
    ].filter(Boolean)) }, e, itemIcon(e.lootId, 54), ...lvlBadge(e), gr.length > 1 ? h('span', { class: 'se-qty' }, '×' + gr.length) : null, h('span', { class: 'ad' }, itemName(e.lootId)));
  }));
  return h('div', { class: 'stack' },
    h('div', { class: 'card se-card' }, h('div', { class: 'row wrap', style: { gap: '10px' } },
      h('input', { class: 'input game-search', placeholder: T('Ara…'), value: SE.search, oninput: e => seSearch(e, v => { SE.search = v; }) }),
      h('span', { class: 'spacer' }), ro ? null : btn(T('Eşya ekle'), () => seCatalog({}), 'primary sm', 'plus')),
    kinds.length > 1 ? h('div', { class: 'seg', style: { marginTop: '12px', flexWrap: 'wrap' } }, ['hepsi', ...kinds].map(t => h('button', { class: t === SE.invKind ? 'on info' : '',
      onclick: () => { SE.invKind = t; seRender(); } }, t === 'hepsi' ? T('Hepsi') : t === 'tasarim' ? T('Dron tasarımları') : slotName(t)))) : null),
    entries.length ? h('div', { class: 'card se-card' }, grid) : h('div', { class: 'card empty' }, icon('box'), h('div', null, empty.length ? T('Aramaya uyan eşya yok.') : T('Envanter boş: bütün eşyalar takılı.'))));
}

function seAmmo(v) {
  const ro = v.read_only, groups = {};
  for (const c of v.ammunition) if (!SE.ammoFilled || c[1]) (groups[c[2]] = groups[c[2]] || []).push(c);
  const box = ([l, n]) => h('div', { class: 'se-pocket' + (n ? '' : ' zero') }, itemIcon(l, 44), h('div', { class: 'grow', style: { minWidth: 0 } },
    h('div', { class: 'se-pocket-name', title: l }, itemName(l)), numberBox(n, x => seApply({ islem: 'ammunition', counts: { [l]: x } }), { max: 1e12, cls: 'wide' })));
  const bulkSet = async entries => { const s = await promptBox(T('Hepsine aynı adet'), T('Adet'), '100000'); if (s == null) return;
    const n = Math.max(0, Math.round(+s) || 0); seApply({ islem: 'ammunition', counts: Object.fromEntries(entries.map(c => [c[0], n])) }); };
  const full = h('input', { type: 'checkbox', checked: SE.ammoFilled, onchange: e => { SE.ammoFilled = e.target.checked; seRender(); } });
  return h('div', { class: 'stack' },
    h('div', { class: 'card se-card row wrap', style: { gap: '14px' } }, h('label', { class: 'row small' }, h('span', { class: 'switch' }, full, h('span')), T('Yalnız elde olanları göster')),
      h('span', { class: 'spacer' }), h('span', { class: 'small muted' }, T('Toplam {0} tür, {1} tanesi elde.', v.ammunition.length, v.ammunition.filter(c => c[1]).length))),
    ...SE_AMMO.filter(([k]) => groups[k]).map(([k, name]) => seCard(null, null,
      h('div', { class: 'row between', style: { marginBottom: '12px' } }, h('h2', { style: { margin: 0 } }, icon('ammo'), T(name)),
        ro ? null : btn(T('Hepsine aynı adet…'), () => bulkSet(groups[k]), 'sm ghost', 'edit')),
      h('div', { class: 'se-pockets' }, groups[k].map(box)))));
}

function seResources(v) {
  const ro = v.read_only, d = v.durum, q = SE.resourceSearch.toLowerCase();
  const ore = ([t, l, n]) => h('div', { class: 'se-pocket' + (n ? '' : ' zero') }, itemIcon(l, 44), h('div', { class: 'grow', style: { minWidth: 0 } },
    h('div', { class: 'se-pocket-name' }, itemName(l)), numberBox(n, x => seApply({ islem: 'cevher', counts: { [t]: x } }), { max: 1e9, cls: 'wide' })));
  const sources = v.sources.filter(([l]) => !q || l.includes(q) || itemName(l).toLowerCase().includes(q));
  return h('div', { class: 'stack' },
    seCard(null, null, h('div', { class: 'row between', style: { marginBottom: '12px' } }, h('h2', { style: { margin: 0 } }, icon('gem'), T('Cevherler')),
      h('span', { class: 'pill' }, icon('box'), T('Kargo'), ' ', h('b', null, fmtN(d.kargo) + ' / ' + fmtN(d.cargo_max)))),
    h('div', { class: 'se-pockets' }, v.ores.map(ore))),
    seCard(null, null, h('div', { class: 'row wrap between', style: { gap: '10px', marginBottom: '12px' } }, h('h2', { style: { margin: 0 } }, icon('gift'), T('Toplanabilirler ve öbür kaynaklar')),
      h('div', { class: 'row', style: { gap: '8px' } }, h('input', { class: 'input game-search', placeholder: T('Ara…'), value: SE.resourceSearch,
        oninput: e => seSearch(e, v => { SE.resourceSearch = v; }) }),
      ro ? null : btn(T('Kaynak ekle'), () => seCatalog({ multiplier: 'kaynak', baslik: T('Kaynaklar') }), 'primary sm', 'plus'))),
    sources.length ? h('div', { class: 'se-pockets' }, sources.map(([l, n]) => h('div', { class: 'se-pocket' }, itemIcon(l, 44), h('div', { class: 'grow', style: { minWidth: 0 } },
      h('div', { class: 'se-pocket-name', title: l }, itemName(l)), h('div', { class: 'row', style: { gap: '4px' } }, numberBox(n, x => seApply({ islem: 'kaynak', counts: { [l]: x } }), { max: 1e12, cls: 'wide' }),
        ro ? null : btn('', () => seApply({ islem: 'kaynak', counts: { [l]: 0 } }), 'ghost sm icon', 'x', { title: T('Kaldır') }))))))
      : h('div', { class: 'empty' }, T('Kaynak yok.'))));
}

function seBoosters(v) {
  const ro = v.read_only;
  const row = ([l, sec]) => {
    const hour = h('input', { class: 'input num', type: 'number', min: 0, step: 0.5, value: Math.round(sec / 360) / 10, disabled: ro,
      onchange: e => { const s = Math.max(0, Math.round((+e.target.value || 0) * 3600)); if (s !== sec) seApply({ islem: 'booster', durations: { [l]: s } }); } });
    return h('div', { class: 'se-boost' }, itemIcon(l, 48), h('div', { class: 'grow', style: { minWidth: 0 } }, h('b', null, itemName(l)), h('div', { class: 'small muted' }, T('{0} kaldı', fmtDur(sec)))),
      h('label', { class: 'row small' }, hour, T('saat')), ro ? null : btn('', () => seApply({ islem: 'booster', durations: { [l]: 0 } }), 'ghost sm icon', 'x', { title: T('Kaldır') }));
  };
  return h('div', { class: 'stack' },
    h('div', { class: 'card se-card row wrap', style: { gap: '10px' } }, h('span', { class: 'small muted grow' }, T('Editörden verilen booster, uzaylıdan düşen gibi yalnız oyun açıkken işler.')),
      ro ? null : btn(T('Booster ekle'), () => seCatalog({ multiplier: 'booster', baslik: T('Boosterlar') }), 'primary sm', 'plus')),
    v.boosters.length ? h('div', { class: 'card se-card se-boosts' }, v.boosters.map(row)) : h('div', { class: 'card empty' }, icon('zap'), h('div', null, T('Etkin booster yok.'))));
}

function seMaintenance(v) {
  const ro = v.read_only, d = v.durum;
  const row = (iconEl, title, description, ...button) => h('div', { class: 'se-maintenance' }, h('span', { class: 'se-maintenance-icon' }, icon(iconEl)),
    h('div', { class: 'grow' }, h('b', null, title), h('div', { class: 'small muted' }, description)), ...button);
  const boxes = Object.fromEntries(SE_RESET.map(([k]) => [k, h('input', { type: 'checkbox', disabled: ro })]));
  return h('div', { class: 'stack' },
    seCard(T('Gemi ve konum'), 'wrench',
      row('heart', T('Gemiyi onar'), T('Can {0} / {1}, kalkan {2} / {3}.', fmtN(d.can), fmtN(d.max_hp), fmtN(d.kalkan), fmtN(d.shield_max)),
        btn(T('Onar'), () => seApply({ islem: 'repair' }), 'sm', 'wrench', { disabled: ro || (d.can >= d.max_hp && d.kalkan >= d.shield_max) })),
      row('map', T('Ana istasyona taşı'), T('Şu an {0}; firmanın ana haritası {1}. Bir haritada takılı kaldıysan.', d.map_name, d.main_map),
        btn(T('Taşı'), () => seApply({ islem: 'home_base' }), 'sm', 'map', { disabled: ro })),
      row('sliders', T('Tuş atamaları'), T('Varsayılana döner (oyundaki Ayarlar > Reset sunucuya ulaşmıyor).'),
        btn(T('Varsayılana döndür'), async () => await confirmBox(T('Tuş atamaları varsayılana dönsün mü?'), T('Kendi atadığın tuşlar silinir.'), { ok: T('Döndür') }) && seApply({ islem: 'keybinds' }),
          'sm', 'undo', { disabled: ro }))),
    seCard(T('Durum sıfırlama'), 'refresh', h('div', { class: 'stack', style: { gap: '8px' } },
      SE_RESET.map(([k, t]) => h('label', { class: 'row small' }, h('span', { class: 'switch' }, boxes[k], h('span')), T(t)))),
    h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '12px' } }, btn(T('Seçilenleri sıfırla'), () => {
      const b = SE_RESET.map(([k]) => k).filter(k => boxes[k].checked);
      if (!b.length) return toast(T('Sıfırlanacak bölüm seç.'), 'err');
      seApply({ islem: 'reset', sections: b });
    }, 'sm', 'refresh', { disabled: ro }))),
    h('div', { class: 'small dim' }, T('Bütün değişiklikler önce taslakta durur; Kaydet\'e basınca kayda yazılır ve önceki hâli yedeklenir.')));
}

const SE_RENDER = { pilot: sePilot, hangar: seHangar, drones: seDrones, pet: sePet, inventory: seInventory, ammunition: seAmmo, sources: seResources,
  boosters: seBoosters, maintenance: seMaintenance, stats: seStats };

// İstatistik (salt okunur; kayit_editoru.istatistik): rütbe puanı, öldürmeler, ölümler, kapılar ve süreleri, modların en iyileri
const SE_POINTS = [['ExperiencePoints', N('Deneyim (EP)')], ['honorPoints', N('Onur')], ['yourLevel', N('Seviye')], ['npcShotPoints', N('Uzaylı puanı')],
  ['playerShotPoints', N('Oyuncu puanı')], ['missionsCompleted', N('Biten görev')], ['daysSinceRegistration', N('Kayıttan beri gün')],
  ['DestroyedByEnemies', N('Düşmana yenilme')], ['DestroyedByRadiationZone', N('Radyasyonda ölüm')], ['friendlyPlayersDestroyed', N('Dost öldürme')]];
const seDuration = sec => sec ? (sec >= 3600 ? Math.floor(sec / 3600) + ':' : '') + String(Math.floor(sec / 60) % 60).padStart(sec >= 3600 ? 2 : 1, '0') + ':' + String(sec % 60).padStart(2, '0') : '—';
function seStats(v) {
  const s = v.stats || {}, p = s.puan || {};
  const table = (titles, lines, empty) => lines.length ? h('div', { class: 'bt-table' }, h('table', { class: 'table' },
    h('thead', null, h('tr', null, titles.map(x => h('th', null, x)))), h('tbody', null, lines)))
    : h('div', { class: 'small muted' }, empty);
  return h('div', { class: 'stack' },
    seCard(T('Rütbe puanı'), 'star', h('div', { class: 'row wrap', style: { gap: '8px', marginBottom: '8px' } },
      badge(T('Rütbe puanı') + ': ' + fmtN(p.rankPoints || 0), 'info'), badge(T('Oyun süresi') + ': ' + fmtDur(s.play_sec || 0), '')),
      h('div', { class: 'se-stats' }, SE_POINTS.map(([k, name]) => h('div', { class: 'row' }, h('span', { class: 'grow muted' }, T(name)), h('b', null, fmtN(p[k] || 0)))))),
    seCard(T('Kapılar'), 'globe', table([T('Kapı'), T('Tamamlama'), T('En iyi süre'), T('Son süre')],
      (s.kapilar || []).map(k => h('tr', null, h('td', null, k.ad), h('td', { class: 'num' }, fmtN(k.tamam)), h('td', { class: 'num' }, seDuration(k.best)), h('td', { class: 'num' }, seDuration(k.last)))),
      T('Henüz tamamlanan kapı yok.')),
      h('div', { class: 'small muted', style: { marginTop: '6px' } }, T('Süre kapının ilk dalgasına girişten tamamlanmaya; bu sürümden önce biten kapıların süresi yok.'))),
    seCard(T('Öldürülen uzaylılar'), 'zap', table([T('Uzaylı'), T('Sayı'), T('Puan')],
      (s.npc || []).map(([name, n, pts]) => h('tr', null, h('td', null, name), h('td', { class: 'num' }, fmtN(n)), h('td', { class: 'num' }, fmtN(pts * n)))), T('Henüz uzaylı öldürülmedi.'))),
    seCard(T('Oyuncular ve ölümler'), 'shield', h('div', { class: 'se-stats' },
      [[T('Düşmana yenilme'), (s.olum || {}).enemy], [T('Radyasyonda ölüm'), (s.olum || {}).radiation], [T('Öteki ölümler'), (s.olum || {}).other],
       [T('Dost öldürme'), s.friendly], [T('Biten görev'), s.gorev], [T('Eternal Black Light en iyi dalga'), (s.modes || {}).ebl],
       [T('Frozen Labyrinth avı'), (s.modes || {}).labyrinth], [T('Mimesis en iyi sefer'), (s.modes || {}).mimesis]]
        .map(([name, n]) => h('div', { class: 'row' }, h('span', { class: 'grow muted' }, name), h('b', null, fmtN(n || 0))))),
      table([T('Gemi'), T('Öldürülen')], (s.player || []).map(([name, n]) => h('tr', null, h('td', null, name), h('td', { class: 'num' }, fmtN(n)))), T('Henüz oyuncu öldürülmedi.'))));
}

// ---- değişiklik özeti, kaydet, vazgeç
function seChanges() {
  const f = SE.v.diff, ro = SE.v.read_only;
  const value = (k, x) => x == null ? '—' : k === 'firma' ? COMPANY_TAG[x] || x : k === 'active_ship' ? itemName(x) : k === 'premium' ? (x ? T('Açık') : T('Kapalı'))
    : typeof x === 'number' ? fmtN(x) : String(x);
  const section = (title, ...contents) => contents.flat().filter(Boolean).length ? h('div', { class: 'se-diff' }, h('div', { class: 'lbl' }, title), ...contents) : null;
  const items = (o, cls) => Object.keys(o).length ? h('div', { class: 'se-diff-items' }, Object.entries(o).map(([l, n]) => h('div', { class: 'se-diff-item ' + cls },
    itemIcon(l, 32), h('span', null, itemName(l)), h('b', null, (cls === 'arti' ? '+' : '−') + fmtN(n))))) : null;
  const m = modal({ title: T('Kaydedilmemiş değişiklikler'), sub: T('Kaydet\'e basınca bunlar kayda yazılır; önceki hâli "Geri yükleme öncesi" yedeği olarak saklanır.'), wide: true,
    body: [
      section(T('Değerler'), f.fields.map(([k, a, b]) => h('div', { class: 'se-diff-field' }, h('span', null, T(SE_FIELD[k] || k)), h('s', null, value(k, a)), icon('arrowR'), h('b', null, value(k, b))))),
      section(T('Eklenenler'), items(f.added, 'arti')),
      section(T('Kaldırılanlar'), items(f.leaving, 'eksi')),
      section(T('Adetler'), f.counts.map(([l, a, b]) => h('div', { class: 'se-diff-field' }, h('span', { class: 'row', style: { gap: '8px' } }, itemIcon(l, 26), itemName(l)), h('s', null, fmtN(a)), icon('arrowR'), h('b', null, fmtN(b))))),
      section(T('Boosterlar'), f.boosters.length ? h('div', { class: 'small' }, f.boosters.map(itemName).join(', ')) : null),
      section(T('Seviyeler'), f.seviyeler.length ? h('div', { class: 'small' }, [...new Set(f.seviyeler)].map(l => l === 'pet' ? 'P.E.T.' : itemName(l)).join(', ')) : null),
      section(T('Donanım'), f.hardware ? h('div', { class: 'small' }, T('{0} eşyanın yeri değişti (takıldı, çıkarıldı ya da taşındı).', f.hardware)) : null),
      !f.sayi ? h('div', { class: 'empty' }, T('Değişiklik yok.')) : null],
    foot: [btn(T('Kapat'), () => m.close(), 'ghost'), ro ? null : btn(T('Vazgeç'), () => { m.close(); seCancel(); }, 'danger', 'undo', { disabled: !f.sayi }),
      ro ? null : btn(T('Kaydet'), () => { m.close(); seSave(); }, 'primary', 'save', { disabled: !f.sayi })] });
}

async function seSave() {
  const r = await act(() => api('/api/editor/kaydet', { id: SE.slot }), T('Kaydedildi. Önceki hâli yedeklendi.'));
  if (r && SE.slot) { SE.v = null; renderEditor(); }
}
async function seCancel() {
  const n = SE.v?.diff?.sayi || 0;
  if (!await confirmBox(T('Değişiklikler atılsın mı?'), T('Taslaktaki {0} değişiklik silinir; kayıt olduğu gibi kalır.', n), { ok: T('At'), danger: true })) return;
  const r = await act(() => api('/api/editor/discard', { id: SE.slot }), T('Değişiklikler atıldı.'));
  if (r && SE.slot) { SE.v = null; renderEditor(); }
}
