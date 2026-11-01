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
const seEmpty = (size, iconEl) => h('span', { class: 'sprite bos', style: { width: size + 'px', height: size + 'px' } }, icon(iconEl));
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
const portrait = (f, cls = 'ke-portre', size = 112) => GI.index?.sprite[companyLower(f) + '_char'] ? h('span', { class: cls }, sprite(companyLower(f) + '_char', size))
  : h('span', { class: cls + ' arma' }, art('firma_' + (companyLower(f) || 'eic'), 'crest'));
function epBar(ep, base, next_, cls = '') {
  const p = next_ ? Math.max(0, Math.min(1, (ep - base) / Math.max(1, next_ - base))) : 1;
  return h('div', { class: 'ke-ep ' + cls, title: next_ ? T('{0} / {1} EP', fmtN(ep), fmtN(next_)) : T('En yüksek seviye') }, h('span', { style: { width: (p * 100).toFixed(1) + '%' } }));
}

// ================================================================== KİTAPLIK
const KL = { cop: false };

async function renderSaves() {
  if (SE.slot) return renderEditor();
  await loadGameImages();
  const r = await act(() => api('/api/kayitlar')); if (!r || S.page !== 'kayitlar' || SE.slot) return;
  const active = r.liste.find(k => k.aktif), others = r.liste.filter(k => !k.aktif);
  const tools = h('div', { class: 'row wrap' },
    btn(T('Yeni kayıt'), () => newSaveModal(), 'primary', 'plus'),
    btn(T('İçe aktar…'), () => act(() => api('/api/kayitlar/iceri', {}), x => x.iptal ? T('İptal edildi.') : T('Kayıt içe aktarıldı.')).then(() => renderSaves()), '', 'upload'),
    h('span', { class: 'spacer' }),
    r.liste.length ? h('span', { class: 'small muted' }, T('{0} kayıt', r.liste.length)) : null,
    btn(T('Kayıt klasörü'), () => act(() => api('/api/klasor_ac', { ne: 'kayitlar' })), 'ghost', 'folder'));
  $('#content').replaceChildren(h('div', { class: 'stack ke-kitap' }, tools,
    active ? saveScene(active) : h('div', { class: 'card empty' }, art('bos_kayit'), h('h3', null, T('Henüz kayıt yok')),
      h('div', null, T('Yeni bir kayıt oluştur ya da bir yedeği içe aktar.'))),
    others.length ? h('div', { class: 'section-title' }, T('Öbür kayıtlar ({0})', others.length)) : null,
    others.length ? h('div', { class: 'ke-kartlar' }, others.map(saveCard)) : null,
    trash(r.silinenler)));
}

// kayıt kartlarının ortak "Diğer" menüsü (ek istemci, ad, not, kopya, dışa aktarma, klasör, silme)
function saveMenu(k, ev) {
  const c = S.durum?.coklu, extra = c && c.ayar && c.kayit_sayisi > 1 && (c.kayitlar || []).find(x => x.id === k.id);
  const extraWhy = extra ? (extra.ek || k.id === c.ana ? T('Kayıt kullanımda') : extraBlock(S.durum, extra)) : null;
  popMenu(ev.currentTarget, [
    extra ? { label: extraWhy ? T('Ek istemcide aç ({0})', extraWhy) : T('Ek istemcide aç'), iconEl: 'play', disabled: !!extraWhy,
      fn: () => openExtra(k.id, k.pilot).then(() => S.page === 'kayitlar' && renderSaves()) } : null,
    extra ? '-' : null,
    { label: T('Yeniden adlandır'), ic: 'edit', fn: async () => { const v = await promptBox(T('Kaydı yeniden adlandır'), T('Kayıt adı'), k.ad); if (v != null) act(() => api('/api/kayitlar/adlandir', { id: k.id, ad: v }), T('Ad değişti.')).then(renderSaves); } },
    { label: T('Not ekle / düzenle'), ic: 'note', fn: async () => { const v = await promptBox(T('Kayıt notu'), T('Not'), k.not_, { multiline: true }); if (v != null) act(() => api('/api/kayitlar/not', { id: k.id, not: v })).then(renderSaves); } },
    { label: T('Kopyala'), ic: 'copy', fn: async () => { const v = await promptBox(T('Kaydı kopyala'), T('Yeni kaydın adı'), T('{0} (kopya)', k.ad)); if (v != null) act(() => api('/api/kayitlar/kopyala', { id: k.id, ad: v }), T('Kopyalandı.')).then(renderSaves); } },
    { label: T('Dışa aktar (.zip)…'), ic: 'download', fn: () => act(() => api('/api/kayitlar/disari', { id: k.id, yedeklerle: true }), x => x.iptal ? T('İptal edildi.') : T('Dışa aktarıldı: {0}', x.yol)) },
    { label: T('Klasörü aç'), ic: 'folder', fn: () => act(() => api('/api/klasor_ac', { ne: 'kayit', id: k.id })) },
    '-',
    { label: T('Sil'), ic: 'trash', danger: true, disabled: k.kullanimda, fn: async () => {
      if (await confirmBox(T('Kayıt silinsin mi?'), T('"{0}" ({1}) çöp kutusuna taşınır; Kayıtlar sayfasının altından geri alabilirsin.', k.ad, k.pilot), { ok: T('Sil'), danger: true }))
        act(() => api('/api/kayitlar/sil', { id: k.id }), T('Çöp kutusuna taşındı.')).then(renderSaves);
    } },
  ].filter(Boolean));
}
const statusBadges = k => [k.kullanimda ? badge(T('OYUNDA'), 'ok') : null, k.taslak ? badge(T('KAYDEDİLMEMİŞ DEĞİŞİKLİK'), 'warn') : null,
  k.bozuk ? badge(T('BOZUK'), 'err') : null];

// etkin kayıt: geniş sahne (gemi, firma portresi, seviye, cüzdan, eylemler)
function saveScene(k) {
  const f = companyLower(k.firma);
  const currency = (name, n, tag) => h('div', { class: 'ke-para-k' }, art('kaynak_' + name, 'ke-para-ic'), h('div', null, h('span', null, tag), h('b', null, fmtN(n))));
  const meta = (iconEl, tag, value) => h('div', { class: 'ke-meta' }, icon(iconEl), h('span', null, tag), h('b', null, value));
  return h('div', { class: 'card ke-sahne f-' + f },
    h('div', { class: 'ke-sahne-gemi' }, shipImage(k.gemi_gorunum, 250, f),
      h('div', { class: 'ke-sahne-gemi-ad' }, k.gemi_gorunum ? itemName(k.gemi_gorunum) : k.gemi)),
    h('div', { class: 'ke-sahne-govde' },
      h('div', { class: 'row wrap', style: { gap: '8px' } }, badge(T('ETKİN KAYIT'), 'info'), ...statusBadges(k)),
      h('div', { class: 'ke-sahne-bas' }, portrait(k.firma),
        h('div', { style: { minWidth: 0 } }, h('h2', { class: 'ke-sahne-ad' }, k.ad),
          h('div', { class: 'ke-pilot' }, h('b', null, k.pilot), k.klan ? h('span', { class: 'ke-klan' }, '[' + k.klan + ']') : null,
            badge(k.firma || '?', firmaCls(k.firma)), k.premium ? badge('Premium', 'orange') : null))),
      h('div', { class: 'ke-sv' }, h('div', { class: 'ke-sv-n' }, h('small', null, T('Seviye')), h('b', null, k.seviye ?? '?')),
        h('div', { class: 'grow' }, h('div', { class: 'row between small muted' }, h('span', null, T('Deneyim')),
          h('span', { class: 'mono' }, k.seviye_sonraki ? fmtShort(k.ep) + ' / ' + fmtShort(k.seviye_sonraki) + ' EP' : fmtShort(k.ep) + ' EP')),
          epBar(k.ep, k.seviye_taban, k.seviye_sonraki))),
      h('div', { class: 'ke-paralar' }, currency('kredi', k.kredi, T('Kredi')), currency('uridyum', k.uridyum, T('Uridyum')), currency('onur', k.onur, T('Onur'))),
      h('div', { class: 'ke-metalar' }, meta('map', T('Harita'), k.harita), meta('ship', T('Gemi'), T('{0} gemi', k.gemi_sayisi)),
        meta('drone', T('Dronlar'), k.dron_sayisi), meta('paw', 'P.E.T.', k.pet || '—'), meta('clock', T('Oynama'), fmtDur(k.oynama_sn)),
        meta('calendar', T('Son oynama'), fmtWhen(k.son_oynama || k.last_save))),
      k.not_ ? h('div', { class: 'note' }, k.not_) : null,
      h('div', { class: 'row wrap ke-eylem' },
        btn(T('Oyna'), () => { go('oyna'); act(() => api('/api/oyna', {})); }, 'orange', 'play', { disabled: k.kullanimda }),
        btn(T('Karakter editörü'), () => seOpen(k), 'primary', 'edit'),
        btn(T('Yedekler ({0})', k.yedek_sayisi), () => backupsModal(k.id), '', 'clock'),
        h('span', { class: 'spacer' }),
        btn('', ev => saveMenu(k, ev), 'ghost icon', 'more', { title: T('Diğer') }))));
}

function saveCard(k) {
  const f = companyLower(k.firma);
  return h('div', { class: 'card ke-kart-k f-' + f },
    h('div', { class: 'ke-kart-ust' },
      h('div', { class: 'ke-kart-gemi' }, shipImage(k.gemi_gorunum, 96, f)),
      h('div', { class: 'grow', style: { minWidth: 0 } },
        h('div', { class: 'row', style: { gap: '6px', minWidth: 0 } }, h('span', { class: 'ke-kart-ad', title: k.ad }, k.ad)),
        h('div', { class: 'ke-pilot small' }, h('b', null, k.pilot), k.klan ? h('span', { class: 'ke-klan' }, '[' + k.klan + ']') : null, badge(k.firma || '?', firmaCls(k.firma))),
        h('div', { class: 'row', style: { gap: '8px', marginTop: '6px' } }, h('span', { class: 'ke-sv-mini' }, T('Sv {0}', k.seviye ?? '?')),
          h('div', { class: 'grow' }, epBar(k.ep, k.seviye_taban, k.seviye_sonraki, 'ince')))),
      btn('', ev => saveMenu(k, ev), 'ghost icon sm', 'more', { title: T('Diğer') })),
    h('div', { class: 'row wrap', style: { gap: '6px' } }, ...statusBadges(k)),
    h('div', { class: 'ke-kart-paralar' },
      h('span', null, art('kaynak_kredi', 'ke-para-ic sm'), fmtShort(k.kredi)), h('span', null, art('kaynak_uridyum', 'ke-para-ic sm'), fmtShort(k.uridyum)),
      h('span', null, icon('ship'), k.gemi_gorunum ? itemName(k.gemi_gorunum) : k.gemi), h('span', null, icon('clock'), fmtWhen(k.son_oynama || k.last_save))),
    k.not_ ? h('div', { class: 'note' }, k.not_) : null,
    h('div', { class: 'row wrap', style: { gap: '6px', marginTop: 'auto' } },
      btn(T('Etkin yap'), () => act(() => api('/api/kayitlar/aktif', { id: k.id }), T('Etkin kayıt: {0}', k.ad)).then(() => { renderSaves(); poll(); }), 'primary sm', 'check'),
      btn(T('Editör'), () => seOpen(k), 'sm', 'edit'),
      btn(T('Yedekler'), () => backupsModal(k.id), 'sm ghost', 'clock')));
}

function trash(entries) {
  if (!entries.length) return null;
  const d = h('details', { class: 'card ke-cop', open: KL.cop, ontoggle: e => { KL.cop = e.target.open; } },
    h('summary', null, icon('trash'), T('Silinenler ({0})', entries.length), h('span', { class: 'small muted' }, T('Silinen kayıtlar burada bekler; geri alabilir ya da kalıcı olarak silebilirsin.'))),
    h('table', { class: 'table' }, h('thead', null, h('tr', null, h('th', null, T('Kayıt')), h('th', null, T('Pilot')), h('th', null, T('Silinme')), h('th'))),
      h('tbody', null, entries.map(x => h('tr', null, h('td', null, x.ad), h('td', null, `${x.pilot} · ${lvl(x.seviye)}`), h('td', { class: 'muted' }, fmtWhen(x.silinme)),
        h('td', { class: 'num' }, h('div', { class: 'actions', style: { justifyContent: 'flex-end' } },
          btn(T('Geri al'), () => act(() => api('/api/kayitlar/geri_al', { dosya: x.dosya }), T('Kayıt geri alındı.')).then(renderSaves), 'sm', 'undo'),
          btn(T('Kalıcı sil'), async () => {
            if (await confirmBox(T('Kalıcı olarak silinsin mi?'), T('"{0}" kaydı ve yedekleri diskten silinir. Bu geri alınamaz.', x.ad), { ok: T('Kalıcı sil'), danger: true }))
              act(() => api('/api/kayitlar/cop_bosalt', { dosya: x.dosya }), T('Kalıcı olarak silindi.')).then(renderSaves);
          }, 'danger sm', 'trash'))))))),
    entries.length > 1 ? h('div', { class: 'row', style: { marginTop: '12px', justifyContent: 'flex-end' } },
      btn(T('Çöp kutusunu boşalt'), async () => {
        if (await confirmBox(T('Çöp kutusu boşaltılsın mı?'), T('{0} kayıt kalıcı olarak silinir.', entries.length), { ok: T('Boşalt'), danger: true }))
          act(() => api('/api/kayitlar/cop_bosalt', {}), T('Çöp kutusu boşaltıldı.')).then(renderSaves);
      }, 'danger sm', 'trash')) : null);
  return d;
}

// ================================================================== KARAKTER EDİTÖRÜ
const SE = { slot: null, ad: '', v: null, sekme: 'pilot', gemi: null, konfig: null, busy: false, katalog: null, ara: '', ammoFilled: false, invKind: 'hepsi', resourceSearch: '' };
const SE_TABS = [
  ['pilot', N('Pilot'), 'user', 'pilotSheet_normal'], ['hangar', N('Hangar'), 'hangar', 'hangar_normal'], ['dronlar', N('Dronlar'), 'drone', null],
  ['pet', 'P.E.T.', 'paw', 'pet_normal'], ['envanter', N('Envanter'), 'box', 'assembly_normal'], ['cephane', N('Cephane'), 'ammo', null],
  ['kaynaklar', N('Kaynaklar'), 'gem', 'refinement_normal'], ['boosterlar', N('Boosterlar'), 'zap', 'booster_normal'], ['bakim', N('Bakım'), 'wrench', 'settings_normal'],
  ['istatistik', N('İstatistik'), 'star', null],
];
const SE_CATEGORY = { hepsi: N('Hepsi'), gemi: N('Gemiler'), tasarim: N('Gemi tasarımları'), lazer: N('Lazerler'), roketatar: N('Roketatarlar'), jenerator: N('Jeneratörler'),
  ekstra: N('Ekstralar ve CPU'), modul: N('Modüller ve çekirdekler'), agir: N('Ağır silahlar'), dron: N('Dronlar ve formasyonlar'), pet: 'P.E.T.', cephane: N('Cephane'),
  booster: N('Boosterlar'), kaynak: N('Kaynaklar'), paket: N('Paketler'), diger: N('Diğer') };
const SE_CATEGORY_ICON = { hepsi: 'layers', gemi: 'ship', tasarim: 'wand', lazer: 'zap', roketatar: 'target', jenerator: 'shield', ekstra: 'cpu', modul: 'layers', agir: 'crosshair',
  dron: 'drone', pet: 'paw', cephane: 'ammo', booster: 'zap', kaynak: 'gem', paket: 'gift', diger: 'box' };
const SE_AMMO = [['lazer', N('Lazer cephanesi')], ['roket', N('Roketler')], ['roketatar', N('Roketatar cephanesi')], ['mayin', N('Mayınlar')], ['ozel', N('Özel cephane')], ['diger', N('Diğer')]];
const SE_RESET = [['ipuclari', N('İpuçlarını yeniden göster (kapattıkların ve gösterilenler, etkinlik bildirimleri)')],
  ['arayuz', N('Menü çubuklarının ve pencerelerin yerini varsayılana döndür')], ['oyun_ayarlari', N('Oyunun Ayarlar penceresini (grafik, ses, oynanış) varsayılana döndür')],
  ['aktif_gorevler', N('Alınmış görevleri bırak (bitirilenler kalır)')], ['gecmis', N('Seyir defterini ve hesap geçmişini boşalt')]];
const SE_FIELD = { ad: N('Pilot adı'), firma: N('Firma'), seviye: N('Seviye'), ep: N('Deneyim (EP)'), kredi: N('Kredi'), uridyum: N('Uridyum'), onur: N('Onur'),
  premium: 'Premium', aktif_gemi: N('Etkin gemi'), harita: N('Harita'), can: N('Gemi canı') };

function seOpen(k) {
  Object.assign(SE, { slot: k.id, ad: k.ad, v: null, sekme: 'pilot', gemi: null, konfig: null });
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
    if (S.page !== 'kayitlar' || !SE.slot) return;
    SE.v = v;
    if (v.atildi) toast(T('Kayıt editörde açıldıktan sonra değişmiş (oyun oynandı ya da yedek geri yüklendi): eski taslak atıldı.'), 'info', 7000);
  }
  seRender();
}

// oyunun görselleri yok (oyun kurulmadı ya da BepInEx ile hiç açılmadı): editör eşyaları ancak oyunun simgeleri ve adlarıyla
// anlaşılır gösterebilir; kitaplık (kayıt kartları) görselsiz de çalışır
function seLock() {
  if (S.page !== 'kayitlar' || !SE.slot) return;
  $('#content').replaceChildren(h('div', { class: 'stack ke-editor' },
    h('div', { class: 'card ke-cubuk' }, btn(T('Kayıtlar'), seClose, 'ghost', 'arrowL'),
      h('div', { class: 'ke-cubuk-ad' }, h('b', null, SE.ad || SE.slot), h('div', { class: 'small muted' }, T('Karakter editörü')))),
    h('div', { class: 'card empty ke-kilit' }, art('dron_kilit'), h('h3', null, T('Oyunun görselleri henüz hazır değil')),
      h('p', null, T('Karakter editörü eşyaları oyunun kendi simgeleri, adları ve açıklamalarıyla gösterir. Oyunu kur ve bir kez OYNA ile aç: görseller ilk açılışta hazırlanır, sonra editör açılır.')),
      h('div', { class: 'row', style: { justifyContent: 'center', gap: '8px' } }, btn(T('İstemci sayfası'), () => go('istemci'), 'primary', 'monitor'),
        btn(T('Yeniden dene'), () => renderEditor(), '', 'refresh')))));
}

// işlemleri taslağa uygula (kayit_editoru.ISLEMLER); başarıda yeni görünüm çizilir -> başarılı mı
async function seApply(...ops) {
  if (!SE.v || SE.v.salt_okunur || SE.busy) return false;
  SE.busy = true; document.body.classList.add('ke-mesgul');
  const v = await act(() => api('/api/editor/uygula', { id: SE.slot, ops }));
  SE.busy = false; document.body.classList.remove('ke-mesgul');
  if (v && SE.slot) { SE.v = v; seRender(); return true; }
  return false;
}

// Arama kutusu: editör (bütün sekme ve eşya döşemeleri) her tuşta değil yazma durunca yeniden kurulur; imleç yerinde kalır
function seSearch(e, assign) {
  assign(e.target.value); clearTimeout(SE.searchTimer);
  SE.searchTimer = setTimeout(() => {
    if (!e.target.isConnected) return;          // bu arada sayfa ya da sekme değişti
    const pos = e.target.selectionStart; seRender();
    const new_ = $('.ke-ana .oy-ara'); if (new_) { new_.focus(); new_.setSelectionRange(pos, pos); }
  }, 150);
}
function seRender() {
  if (S.page !== 'kayitlar' || !SE.slot || !SE.v) return;
  const v = SE.v, c = $('#content'), sc = c.scrollTop;
  const tab = SE_TABS.find(s => s[0] === SE.sekme) || SE_TABS[0];
  c.replaceChildren(h('div', { class: 'stack ke-editor' }, seBar(v),
    v.salt_okunur ? h('div', { class: 'alert uyari' }, icon('lock'), h('div', null, h('b', null, T('Kayıt şu an oyunda: yalnız görüntüleniyor.')), ' ',
      T('Değiştirmek için oyunu ve sunucuyu kapat. Oyun açıkken donanım ve alışveriş için oyun içi Hangar ve Mağaza sayfaları var.'))) : null,
    h('div', { class: 'ke-duzen' },
      h('aside', { class: 'ke-yan' }, seIdentity(v), seMenu(v)),
      h('div', { class: 'ke-ana' }, h('div', { class: 'ke-ana-bas' }, seTabIcon(tab, 30), h('div', null, h('h2', null, T(tab[1])), h('div', { class: 'small muted' }, seTabDescription(tab[0])))),
        SE_RENDER[tab[0]](v)))));
  c.scrollTop = sc;
}

// sekme ikonu: panelin görseli (images/ke_<sekme>.webp, Orders.md OP-013: teslim edilenler KE_GORSEL'e), yoksa oyunun menü sprite'ı, o da yoksa çizgi ikon
const SE_IMAGE = new Set(['pilot', 'hangar', 'dronlar', 'pet', 'envanter', 'cephane', 'kaynaklar', 'boosterlar', 'bakim']);
const seTabIcon = (s, size) => SE_IMAGE.has(s[0]) ? h('span', { class: 'ke-sk-ic gorsel' }, art('ke_' + s[0], 'ke-sk-art'))
  : s[3] && GI.index?.sprite[s[3]] ? h('span', { class: 'ke-sk-ic oyun' }, sprite(s[3], size)) : h('span', { class: 'ke-sk-ic' }, icon(s[2]));
const seTabDescription = id => T({ pilot: N('Ad, firma, seviye, deneyim, onur ve cüzdan.'), hangar: N('Gemiler, iki config, tasarımlar ve yuvalar: tıkla, tak ya da çıkar.'),
  dronlar: N('Dronlar, seviyeleri, yükseltmeleri ve donanımları.'), pet: N('P.E.T.: seviye, yakıt, açık yuvalar ve donanım.'),
  envanter: N('Takılı olmayan eşyalar: tak, seviyesini değiştir ya da sil.'), cephane: N('Lazer cephanesi, roketler, mayınlar ve özel cephane.'),
  kaynaklar: N('Kargodaki cevherler ve toplanabilir kaynaklar.'), boosterlar: N('Süreli bonuslar ve kalan süreleri.'),
  bakim: N('Onarım, ana istasyon, tuş atamaları ve durum sıfırlama.'),
  istatistik: N('Rütbe puanının parçaları, öldürülen uzaylılar ve oyuncular, ölümler, kapı süreleri.') }[id]);

function seBar(v) {
  const f = v.fark || { sayi: 0 }, ro = v.salt_okunur;
  return h('div', { class: 'card ke-cubuk' },
    btn(T('Kayıtlar'), seClose, 'ghost', 'arrowL'),
    h('div', { class: 'ke-cubuk-ad' }, h('b', null, SE.ad || SE.slot), h('div', { class: 'small muted' }, T('Karakter editörü'))),
    h('span', { class: 'spacer' }),
    ro ? badge(T('Salt okunur'), 'warn')
      : f.sayi ? h('button', { class: 'ke-degisim var', type: 'button', onclick: seChanges, title: T('Değişiklikleri gör') }, h('span', { class: 'ke-nabiz' }), T('{0} değişiklik kaydedilmedi', f.sayi), icon('chevR'))
        : h('span', { class: 'ke-degisim' }, icon('check'), T('Kayıtla aynı')),
    ro ? null : btn(T('Vazgeç'), seCancel, 'ghost', 'undo', { disabled: !f.sayi }),
    ro ? null : btn(T('Kaydet'), seSave, 'primary', 'save', { disabled: !f.sayi }));
}

function seIdentity(v) {
  const p = v.pilot, d = v.durum, g = v.gemiler.find(x => x.aktif) || v.gemiler[0], f = companyLower(p.firma);
  const sell = (name, n, tag) => h('div', { class: 'ke-cz' }, art('kaynak_' + name, 'ke-para-ic'), h('span', null, tag), h('b', null, fmtN(n)));
  const value = (sp, iconEl, n, m) => h('div', { class: 'ke-dg', title: m != null ? fmtN(n) + ' / ' + fmtN(m) : fmtN(n) }, spr(sp, 20, iconEl), h('b', null, fmtShort(n)));
  return h('div', { class: 'card ke-kimlik f-' + f },
    h('div', { class: 'ke-kimlik-sahne' }, h('div', { class: 'ke-halka' }), shipImage(g.gorunum, 170, f)),
    h('div', { class: 'ke-kimlik-bas' }, portrait(p.firma, 'ke-portre kucuk', 84),
      h('div', { style: { minWidth: 0 } }, h('div', { class: 'ke-kimlik-ad' }, p.ad), h('div', { class: 'ke-pilot small' }, p.klan ? h('span', { class: 'ke-klan' }, '[' + p.klan + ']') : null,
        badge(COMPANY_TAG[p.firma] || '?', firmaCls(COMPANY_TAG[p.firma])), p.premium ? badge('Premium', 'orange') : null))),
    h('div', { class: 'ke-sv sm' }, h('div', { class: 'ke-sv-n' }, h('small', null, T('Sv')), h('b', null, p.seviye)),
      h('div', { class: 'grow' }, h('div', { class: 'row between small muted' }, h('span', null, itemName(g.lootId)), h('span', { class: 'mono' }, fmtShort(p.ep) + ' EP')),
        epBar(p.ep, p.seviye_taban, p.seviye_sonraki))),
    h('div', { class: 'ke-cuzdan' }, sell('kredi', p.kredi, T('Kredi')), sell('uridyum', p.uridyum, T('Uridyum')), sell('onur', p.onur, T('Onur'))),
    h('div', { class: 'ke-degerler' }, value('hitpoints_100x100', 'heart', d.can, d.can_azami), value('shield_100x100', 'shield', d.kalkan, d.kalkan_azami),
      value('speed_100x100', 'gauge', g.deger.hiz), value('damage_laser_100x100', 'zap', g.deger.hasar)));
}

function seMenu(v) {
  const n = { hangar: v.gemiler.length, dronlar: v.dronlar.length, envanter: v.envanter.filter(e => !seIsEquipped(e)).length, boosterlar: v.boosterlar.length,
    kaynaklar: v.kaynaklar.length + v.cevherler.filter(c => c[2]).length, cephane: v.cephane.filter(c => c[1]).length };
  return h('nav', { class: 'card ke-menu' }, SE_TABS.map(s => h('button', { class: s[0] === SE.sekme ? 'on' : '', type: 'button',
    onclick: () => { if (SE.sekme !== s[0]) { SE.sekme = s[0]; $('#content').scrollTop = 0; seRender(); } } },
  seTabIcon(s, 20), h('span', null, T(s[1])), n[s[0]] ? h('span', { class: 'ke-say' }, fmtN(n[s[0]])) : s[0] === 'pet' && !v.pet ? h('span', { class: 'ke-say yok' }, '—') : null)));
}

// ---- ortak parçalar
const seCard = (title, iconEl, ...body) => h('div', { class: 'card ke-k' }, title ? h('h2', null, icon(iconEl), title) : null, ...body);
function numberBox(value, update, { min = 0, max = null, cls = '' } = {}) {
  return h('input', { class: 'input num ' + cls, type: 'number', min, max, step: 1, value: value, disabled: SE.v.salt_okunur,
    onchange: e => { const n = Math.round(+e.target.value); if (!Number.isFinite(n)) { e.target.value = value; return; }
      const x = Math.max(min, max != null ? Math.min(max, n) : n); if (x !== value) update(x); else e.target.value = value; },
    onkeydown: e => { if (e.key === 'Enter') e.target.blur(); } });
}
// kaydırıcı: iz tutamağa kadar dolar (panel.css input[type=range] --p; min ve max value'dan önce verilmeli)
function slider(props, cls = '') {
  const el = h('input', Object.assign({ type: 'range', class: 'ke-aralik ' + cls }, props));
  const filler = () => el.style.setProperty('--p', (el.value - el.min) / Math.max(1e-9, el.max - el.min) * 100 + '%');
  el.addEventListener('input', filler);
  filler();
  return el;
}
// küçük artı/eksi kutusu: [−] n / azami [+]
function stepBox(n, maximum, update, { min = 0 } = {}) {
  const ro = SE.v.salt_okunur;
  return h('div', { class: 'ke-adim' }, h('button', { type: 'button', disabled: ro || n <= min, onclick: () => update(n - 1) }, icon('minus')),
    h('span', null, h('b', null, n), maximum != null ? ' / ' + maximum : ''), h('button', { type: 'button', disabled: ro || (maximum != null && n >= maximum), onclick: () => update(n + 1) }, icon('plus')));
}
function seShip(v) {
  let g = v.gemiler.find(x => x.id === SE.gemi);
  if (!g) { g = v.gemiler.find(x => x.aktif) || v.gemiler[0]; SE.gemi = g.id; }
  if (!g.konfigler[SE.konfig]) SE.konfig = g.aktif_konfig;
  return g;
}
// gemi ve config seçimi (Dronlar ve P.E.T. donanımı da geminin config'inde durur)
function shipPicker(v, g) {
  return h('div', { class: 'row wrap ke-secici' }, h('span', { class: 'lbl' }, T('Gemi')),
    h('select', { class: 'input', onchange: e => { SE.gemi = e.target.value; SE.konfig = null; seRender(); } },
      v.gemiler.map(x => h('option', { value: x.id, selected: x.id === g.id }, itemName(x.lootId) + (x.aktif ? ' · ' + T('etkin') : '')))),
    h('div', { class: 'seg' }, Object.keys(g.konfigler).map(c => h('button', { class: c === SE.konfig ? 'on info' : '', onclick: () => { SE.konfig = c; seRender(); } },
      T('Config {0}', c), c === g.aktif_konfig ? ' •' : ''))));
}
const moveOp = (id, direction, tgt) => ({ islem: 'tasi', direction, hedef: tgt.hedef, gemi: SE.gemi, konfig: +SE.konfig, dron: tgt.dron || 0, kume: tgt.kume || '', esya: id });
const equipTarget = tgt => ({ hedef: tgt.hedef, gemi: SE.gemi, konfig: +SE.konfig, dron: tgt.dron || 0, kume: tgt.kume || '' });
const lvlBadge = e => [e.yukseltme ? h('span', { class: 'ke-rozet-sv' }, '+' + e.yukseltme) : null, e.seviye ? h('span', { class: 'ke-rozet-sv sol' }, T('Sv {0}', e.seviye)) : null];

// eşya simgeli düğme: ipucu örneğin bilgisini (yükseltme, rastgele nitelikler, CPU hakkı) düğmenin _esya'sından okur
function seItemButton(props, e, ...kids) {
  const b = h('button', props, ...kids);
  b._item = SE.v.haklar[e.lootId] ? Object.assign({}, e, { hak: SE.v.haklar[e.lootId] }) : e;
  return b;
}
const seIsEditable = e => !!(e.azami || e.seviye || e.rng || SE.v.haklar[e.lootId]);
function seCell(e, tgt) {
  return seItemButton({ class: 'ke-hucre dolu', type: 'button', onclick: ev => !SE.v.salt_okunur && seItemMenu(ev.currentTarget, e, tgt) }, e,
    itemIcon(e.lootId, 44), ...lvlBadge(e));
}
const seEmptyCell = (tgt, iconEl = 'plus', title = T('Boş yuva: tak')) => h('button', { class: 'ke-hucre bos', type: 'button', title: title, disabled: SE.v.salt_okunur,
  onclick: () => sePickEquip(tgt) }, icon(iconEl));
function seSlotBox(name, c, tgt, extra) {
  return h('div', { class: 'ke-yuva' + (c.esyalar.length >= c.kapasite && c.kapasite ? ' dolu' : '') },
    h('div', { class: 'ke-yuva-bas' }, h('b', null, name), h('span', { class: 'row', style: { gap: '6px' } }, extra, h('span', { class: 'mono' }, c.esyalar.length + ' / ' + c.kapasite))),
    h('div', { class: 'ke-hucreler' }, c.esyalar.map(e => seCell(e, tgt)), Array.from({ length: Math.max(0, c.kapasite - c.esyalar.length) }, () => seEmptyCell(tgt))));
}
function seItemMenu(anchor, e, tgt) {
  popMenu(anchor, [
    { label: T('Çıkar (envantere)'), ic: 'download', fn: () => seApply(moveOp(e.id, 'cikar', tgt)) },
    seIsEditable(e) ? { label: T('Düzenle…'), ic: 'edit', fn: () => seEdit(e) } : null,
    '-',
    { label: T('Çıkar ve sil'), ic: 'trash', danger: true, fn: () => seApply(moveOp(e.id, 'cikar', tgt), { islem: 'sil', esyalar: [e.id] }) },
  ].filter(Boolean));
}

// ---- eşya düzenleme: yükseltme seviyesi (Assembly), P.E.T. dişlisinin/protokolünün seviyesi, CPU'nun hakkı ve rastgele nitelikler
// (kararsız modül: nitelikler kesir, gemiler, yeniden çekme hakkı; parçacık silahı: nitelikler yüzde, hak, topun yıldızı; QFC: bağlı
// gemi, seviye, nitelikler yüzde). Oyunun aralığı ipucu olarak yazılır; değer serbest. Hepsi tek işlem listesiyle taslağa.
function seEdit(e) {
  const v = SE.v, pool = v.havuzlar[e.lootId], r = e.rng || {}, right = v.haklar[e.lootId], fraction = pool?.birim === 'kesir';
  const st = { yukseltme: e.yukseltme || 0, seviye: e.seviye, cpu: right ? right[0] : null, attribute: (r.nitelik || []).map(([a, x]) => [a, fraction ? x * 100 : x]),
    gemiler: [...(r.gemiler || [])], gemi: r.gemi || v.gemiler.find(g => g.aktif)?.lootId, qlevel: r.seviye || 1, hak: r.hak ?? pool?.hak, yildiz: r.yildiz || 0 };
  const sections = [], sortedShips = () => [...v.tum_gemiler].sort((a, b) => itemName(a).localeCompare(itemName(b)));
  const title = (t, extra) => h('div', { class: 'row between' }, h('div', { class: 'lbl' }, t), extra ? h('span', { class: 'small dim' }, extra) : null);
  if (e.azami) {
    const out = h('b', { class: 'ke-sv-deger' }, '+' + st.yukseltme);
    sections.push(h('div', { class: 'ke-dz' }, title(T('Yükseltme seviyesi')), h('div', { class: 'ke-sv-sec' }, out,
      h('div', { class: 'grow' }, slider({ min: 0, max: e.azami, value: st.yukseltme, oninput: x => { st.yukseltme = +x.target.value; out.textContent = '+' + st.yukseltme; } }),
        h('div', { class: 'row between small dim' }, h('span', null, '0'), h('span', null, '+' + e.azami))))));
  }
  if (e.seviye) {
    const seg = h('div', { class: 'seg' });
    const render = () => seg.replaceChildren(...[1, 2, 3, 4].map(n => h('button', { class: n === st.seviye ? 'on info' : '', onclick: () => { st.seviye = n; render(); } }, T('Sv {0}', n))));
    render();
    sections.push(h('div', { class: 'ke-dz' }, title(T('P.E.T. seviyesi')), seg));
  }
  if (right) sections.push(h('div', { class: 'ke-dz' }, title(T('Kalan hak'), T('Bir dolum {0} hak; hak bu eşya türünün bütün örnekleri için ortak.', fmtN(right[1]))),
    h('input', { class: 'input num', type: 'number', min: 0, value: st.cpu, oninput: x => { st.cpu = Math.max(0, Math.round(+x.target.value) || 0); } })));
  if (pool) {
    const lines = h('div', { class: 'ke-nit' });
    const renderAttributes = () => lines.replaceChildren(...[...st.nitelik.map((n, i) => h('div', { class: 'ke-nit-satir' },
      h('select', { class: 'input', onchange: x => { n[0] = x.target.value; renderAttributes(); } }, pool.nitelik.map(a => h('option', { value: a, selected: a === n[0],
        disabled: a !== n[0] && st.nitelik.some(m => m[0] === a) }, attributeName(a)))),
      h('label', { class: 'ke-yuzde' }, h('input', { class: 'input num', type: 'number', min: 0, step: 0.1, value: Math.round(n[1] * 100) / 100,
        oninput: x => { n[1] = Math.max(0, +x.target.value || 0); } }), '%'),
      btn('', () => { st.nitelik.splice(i, 1); renderAttributes(); }, 'ghost sm icon', 'x', { title: T('Kaldır') }))),
    st.nitelik.length < pool.azami_nitelik ? btn(T('Nitelik ekle'), () => {
      const a = pool.nitelik.find(x => !st.nitelik.some(m => m[0] === x)); if (a) { st.nitelik.push([a, pool.aralik[0]]); renderAttributes(); }
    }, 'sm ghost', 'plus') : null].filter(Boolean));
    renderAttributes();
    sections.push(h('div', { class: 'ke-dz' }, title(T('Nitelikler'), T('Oyunda {0}–{1}%, en çok {2} nitelik', fmtN(pool.aralik[0]), fmtN(pool.aralik[1]), pool.azami_nitelik)),
      !e.rng?.nitelik ? h('div', { class: 'small muted' }, T('Nitelikler henüz çekilmedi: Uygula oyundaki gibi çeker, sonra senin değerlerin yazılır.')) : null, lines));
    if (pool.tercih) {
      const chips = h('div', { class: 'ke-gemi-chips' });
      const add = h('select', { class: 'input', onchange: x => { if (x.target.value && !st.gemiler.includes(x.target.value)) st.gemiler.push(x.target.value); renderShip(); } });
      const renderShip = () => {
        chips.replaceChildren(...st.gemiler.map((g, i) => h('span', { class: 'chip' }, gameIcon(g, 22, companyLower(v.pilot.firma), 'ship'), itemName(g),
          h('button', { class: 'btn ghost sm icon', type: 'button', onclick: () => { st.gemiler.splice(i, 1); renderShip(); } }, icon('x')))));
        add.replaceChildren(h('option', { value: '' }, T('Gemi ekle…')), ...sortedShips().filter(g => !st.gemiler.includes(g))
          .map(g => h('option', { value: g }, (pool.tercih.includes(g) ? '★ ' : '') + itemName(g))));
      };
      renderShip();
      sections.push(h('div', { class: 'ke-dz' }, title(T('Geçtiği gemiler'), T('★ oyunda daha sık çıkanlar')), chips, add));
    }
    if (pool.azami_seviye) {
      sections.push(h('div', { class: 'grid g2' },
        field(T('Bağlı gemi'), h('select', { class: 'input', onchange: x => { st.gemi = x.target.value; } },
          sortedShips().map(g => h('option', { value: g, selected: g === st.gemi }, itemName(g))))),
        field(T('Seviye'), h('input', { class: 'input num', type: 'number', min: 1, max: pool.azami_seviye, value: st.qlevel,
          oninput: x => { st.qlevel = Math.max(1, Math.min(pool.azami_seviye, Math.round(+x.target.value) || 1)); } }))));
    }
    if (pool.hak) {
      const k = h('span');
      const c = () => k.replaceChildren(stepBox(st.hak, pool.hak, n => { st.hak = n; c(); }));
      c();
      sections.push(h('div', { class: 'ke-dz satir' }, h('div', { class: 'lbl' }, T('Yeniden çekme hakkı')), k));
    }
    if (pool.yildiz) {
      const stars = h('div', { class: 'ke-yildizlar' });
      const c = () => stars.replaceChildren(...Array.from({ length: pool.yildiz + 1 }, (_, n) => h('button', { type: 'button', class: n && n <= st.yildiz ? 'on' : '',
        title: n ? '★'.repeat(n) : T('Yıldızsız'), onclick: () => { st.yildiz = n; c(); } }, icon(n ? 'star' : 'x'))));
      c();
      sections.push(h('div', { class: 'ke-dz satir' }, h('div', { class: 'lbl' }, T('Yıldız')), stars));
    }
  }
  const m = modal({ title: T('Eşyayı düzenle'), sub: itemName(e.lootId), wide: !!pool,
    body: [h('div', { class: 'ke-dz-bas' }, itemIcon(e.lootId, 56), h('div', { class: 'small muted' }, T('Değişiklikler taslağa yazılır; Kaydet\'e basınca kayda geçer.'))), ...sections],
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Uygula'), async () => {
      const ops = [];
      if (e.azami && st.yukseltme !== (e.yukseltme || 0)) ops.push({ islem: 'esya_seviye', esya: e.id, yukseltme: st.yukseltme });
      if (e.seviye && st.seviye !== e.seviye) ops.push({ islem: 'esya_seviye', esya: e.id, seviye: st.seviye });
      if (right && st.cpu !== right[0]) ops.push({ islem: 'cpu_hak', lootId: e.lootId, hak: st.cpu });
      if (pool) {
        if (!st.nitelik.length && e.rng?.nitelik) return toast(T('En az bir nitelik gerekli.'), 'err');
        const o = { islem: 'rng', esya: e.id };
        if (st.nitelik.length) o.nitelik = st.nitelik.map(([a, x]) => [a, fraction ? x / 100 : x]);
        if (pool.tercih) { if (!st.gemiler.length) return toast(T('En az bir gemi seç.'), 'err'); o.gemiler = st.gemiler; }
        if (pool.azami_seviye) { o.gemi = st.gemi; o.seviye = st.qlevel; }
        if (pool.hak) o.hak = st.hak;
        if (pool.yildiz) o.yildiz = st.yildiz;
        ops.push(o);
      }
      if (!ops.length) return m.close();
      if (await seApply(...ops)) { m.close(); toast(T('Eşya güncellendi (taslakta).'), 'ok'); }
    }, 'primary', 'check')] });
}

// envanteri gruplar: aynı lootId ve seviyedekiler tek kutuda (adet); rastgele nitelikliler (modül, top, QFC) tek tek
// item equipped somewhere (its ship and configs); the game lets another config of the same ship use it too
const seIsEquipped = e => !!(e.konfigler && e.konfigler.length);
const seIsUsable = e => !seIsEquipped(e) || (e.gemi === SE.gemi && !e.konfigler.includes(String(SE.konfig)));
function groupItems(entries) {
  const gr = {};
  for (const e of entries) { const k = [e.lootId, e.yukseltme || 0, e.seviye || 0, e.rng ? e.id : ''].join('|'); (gr[k] = gr[k] || []).push(e); }
  return Object.values(gr).sort((a, b) => itemName(a[0].lootId).localeCompare(itemName(b[0].lootId)));
}
// boş yuvaya tak: envanterde uyanlar ya da katalogdan ver ve tak
function sePickEquip(tgt) {
  const v = SE.v;
  const eligible = v.envanter.filter(e => seIsUsable(e) && (tgt.hedef === 'ship' ? e.hedefler.includes('ship') && e.yuva === tgt.yuva
    : tgt.hedef === 'drone' ? e.hedefler.includes('drone') && (tgt.yuva === 'tasarim') === (e.yuva === 'tasarim')
      : e.hedefler.includes('pet') && (tgt.yuva === 'heat' ? e.heat : e.pet_yuva === tgt.yuva)))
    .sort((a, b) => seIsEquipped(b) - seIsEquipped(a));          // items of the other config first: free copies stay free
  const title = tgt.hedef === 'drone' ? (tgt.yuva === 'tasarim' ? T('Dron tasarımı') : T('Dron donanımı')) : slotName(tgt.yuva);
  const m = modal({ title: T('{0}: eşya tak', title), wide: true, body: [
    eligible.length ? h('div', { class: 'ke-secim' }, groupItems(eligible).map(gr => seItemButton({ class: 'ke-secim-esya', type: 'button',
      onclick: () => { m.close(); seApply(moveOp(gr[0].id, 'tak', tgt)); } }, gr[0], itemIcon(gr[0].lootId, 56), ...lvlBadge(gr[0]),
      h('span', { class: 'ad' }, itemName(gr[0].lootId)), gr.length > 1 ? h('span', { class: 'ke-adet' }, '×' + gr.length) : null)))
      : h('div', { class: 'empty' }, icon('box'), h('div', null, T('Envanterde buraya takılabilecek eşya yok.'))),
    h('div', { class: 'ke-secim-alt' }, h('span', { class: 'small muted' }, T('Envanterde yoksa katalogdan ekleyip doğrudan buraya takabilirsin.')),
      btn(T('Katalogdan ekle ve tak'), () => { m.close(); seCatalog({ tak: tgt, title }); }, 'primary sm', 'plus'))],
  foot: [btn(T('Kapat'), () => m.close(), 'ghost')] });
}

// ---- katalog: eklenebilecek her şey, kategoriler, arama, adet (oyunun ödül yolu)
async function seCatalog(o = {}) {
  if (!SE.katalog) { const r = await act(() => api('/api/editor/katalog')); if (!r) return; SE.katalog = r; }
  let entries = SE.katalog.esyalar;
  if (o.tak) entries = entries.filter(([, , gy, py, dr]) => o.tak.hedef === 'ship' ? gy === o.tak.yuva
    : o.tak.hedef === 'pet' ? (o.tak.yuva === 'heat' ? py === 'lasers' || py === 'generators' : py === o.tak.yuva) : dr && (o.tak.yuva === 'tasarim') === (gy === null && !py));
  if (o.on) entries = entries.filter(([l]) => l.startsWith(o.on));
  const tally = {}; for (const [, k] of entries) tally[k] = (tally[k] || 0) + 1;
  const categories = ['hepsi', ...SE.katalog.kategoriler.filter(k => tally[k])];
  const st = { kat: o.kat && tally[o.kat] ? o.kat : categories.length === 2 ? categories[1] : 'hepsi', search: '', sec: null };
  const grid = h('div', { class: 'ke-kat-izgara' }), left = h('div', { class: 'ke-kat-liste' }), sub = h('div', { class: 'ke-kat-alt' });
  const search = h('input', { class: 'input', placeholder: T('Ara: ad ya da lootId…'), oninput: e => { st.ara = e.target.value.trim().toLowerCase(); render(); } });
  const render = () => {
    left.replaceChildren(...categories.map(k => h('button', { class: k === st.kat ? 'on' : '', type: 'button', onclick: () => { st.kat = k; render(); } },
      icon(SE_CATEGORY_ICON[k] || 'box'), h('span', null, T(SE_CATEGORY[k] || k)), h('small', null, fmtN(k === 'hepsi' ? entries.length : tally[k])))));
    const its = entries.filter(([l, k]) => (st.kat === 'hepsi' || k === st.kat) && (!st.ara || l.includes(st.ara) || itemName(l).toLowerCase().includes(st.ara)));
    const visible = its.slice(0, 300);
    // seçim yalnız sınıfı değiştirir (ızgara yeniden çizilirse kaydırma başa dönerdi)
    const sec = (l, el) => { st.sec = l; grid.querySelectorAll('.ke-kat-esya.on').forEach(x => x.classList.remove('on')); el.classList.add('on'); renderSub(); };
    grid.replaceChildren(...[...visible.map(([l]) => h('button', { class: 'ke-kat-esya' + (st.sec === l ? ' on' : ''), type: 'button', title: l,
      onclick: e => sec(l, e.currentTarget), ondblclick: e => { sec(l, e.currentTarget); add(); } }, itemIcon(l, 52), h('span', null, itemName(l)))),
    its.length > visible.length ? h('div', { class: 'ke-kat-fazla small muted' }, T('{0} eşyadan ilk {1} tanesi gösteriliyor: aramayı daralt.', fmtN(its.length), visible.length)) : null,
    !its.length ? h('div', { class: 'empty' }, T('Eşya yok.')) : null].filter(Boolean));
    grid.scrollTop = 0;
    renderSub();
  };
  const count = h('input', { class: 'input num', type: 'number', min: 1, value: 1 });
  const single = l => l.startsWith('ship_') || l.startsWith('drone_formation_');
  const renderSub = () => {
    if (!st.sec) return sub.replaceChildren(h('span', { class: 'small muted' }, o.tak ? T('Bir eşya seç: verilir ve doğrudan yuvaya takılır.') : T('Bir eşya seç (çift tıklama hemen ekler).')));
    sub.replaceChildren(...[itemIcon(st.sec, 48), h('div', { class: 'grow', style: { minWidth: 0 } }, h('b', null, itemName(st.sec)), h('div', { class: 'mono small dim' }, st.sec)),
      single(st.sec) ? null : h('label', { class: 'row small' }, T('Adet'), count), btn(o.tak ? T('Ver ve tak') : T('Ekle'), add, 'primary', 'plus')].filter(Boolean));
  };
  async function add() {
    if (!st.sec) return;
    const n = single(st.sec) ? 1 : Math.max(1, Math.round(+count.value) || 1), lid = st.sec;
    const ok = await seApply({ islem: 'ver', esyalar: [[lid, n]], tak: o.tak ? equipTarget(o.tak) : undefined });
    if (ok) { toast(T('Eklendi: {0}', (n > 1 ? fmtN(n) + ' × ' : '') + itemName(lid)), 'ok'); if (o.tak) m.close(); }
  }
  const m = modal({ title: o.baslik ? T('Katalog: {0}', o.baslik) : T('Eşya ekle'), wide: true,
    sub: T('Eşyalar oyunun ödül yoluyla verilir: gemi hangara, ekipman envantere, cephane ve kaynaklar sayaçlara.'),
    body: [h('div', { class: 'ke-katalog' }, left, h('div', { class: 'ke-kat-sag' }, search, grid)), sub], foot: [btn(T('Kapat'), () => m.close(), 'ghost')] });
  m.box.classList.add('ke-katalog-modal');
  render();
}

// ================================================================== SEKMELER
function sePilot(v) {
  const p = v.pilot, ro = v.salt_okunur;
  const op = x => seApply(Object.assign({ islem: 'pilot' }, x));
  const name = h('input', { class: 'input', value: p.ad, maxlength: 20, disabled: ro, onchange: e => e.target.value.trim() !== p.ad && op({ ad: e.target.value }) });
  const companies = h('div', { class: 'radio-cards' }, FIRMS.map(([id, k, n, c, m]) => h('div', { class: 'radio-card' + (id === p.firma ? ' on' : ''), style: { '--c': c },
    onclick: async () => { if (ro || id === p.firma) return;
      if (await confirmBox(T('Firma değişsin mi?'), T('{0} artık {1} pilotu olur; gemi {2} ana istasyonuna taşınır.', p.ad, k, m), { ok: T('Değiştir') })) op({ firma: id }); } },
  art('firma_' + k.toLowerCase(), 'crest'), h('b', null, k), h('span', null, n))));
  const prem = h('input', { type: 'checkbox', checked: p.premium, disabled: ro, onchange: e => op({ premium: e.target.checked }) });
  const lvlLabel = h('b', null, p.seviye);
  const lv = h('div', { class: 'ke-sv-duzen' },
    h('div', { class: 'ke-sv-buyuk' }, h('button', { class: 'btn icon', type: 'button', disabled: ro || p.seviye <= 1, onclick: () => op({ seviye: p.seviye - 1 }) }, icon('minus')),
      h('div', null, h('small', null, T('Seviye')), lvlLabel),
      h('button', { class: 'btn icon', type: 'button', disabled: ro || p.seviye >= p.azami_seviye, onclick: () => op({ seviye: p.seviye + 1 }) }, icon('plus'))),
    h('div', { class: 'grow' }, slider({ min: 1, max: p.azami_seviye, value: p.seviye, disabled: ro,
      oninput: e => { lvlLabel.textContent = e.target.value; }, onchange: e => +e.target.value !== p.seviye && op({ seviye: +e.target.value }) }),
    h('div', { class: 'row between small dim' }, h('span', null, '1'), h('span', null, p.azami_seviye))));
  const currency = (key, tag, n, fast) => h('div', { class: 'ke-para' }, art('kaynak_' + key, 'ke-para-ic lg'),
    h('div', { class: 'grow' }, h('label', { class: 'lbl' }, tag), numberBox(n, x => op({ [key]: x }), { max: 1e12, cls: 'genis' })),
    h('div', { class: 'ke-hizli' }, fast.map(x => h('button', { class: 'chip', type: 'button', disabled: ro, onclick: () => op({ [key]: Math.min(1e12, n + x) }) }, '+' + fmtShort(x)))));
  return h('div', { class: 'stack' },
    h('div', { class: 'grid g2' },
      seCard(T('Kimlik'), 'user', field(T('Pilot adı (oyunda görünür)'), name),
        h('label', { class: 'row small', style: { marginTop: '12px' } }, h('span', { class: 'switch' }, prem, h('span')), T('Premium üyelik'))),
      seCard(T('Seviye ve onur'), 'star', lv,
        h('div', { class: 'grid g2', style: { marginTop: '12px' } },
          field(T('Deneyim (EP)'), numberBox(p.ep, x => op({ ep: x }), { max: 2 ** 53, cls: 'genis' })),
          field(T('Onur'), numberBox(p.onur, x => op({ onur: x }), { min: -1e12, max: 1e12, cls: 'genis' }))),
        h('div', { class: 'small dim', style: { marginTop: '8px' } }, p.seviye_sonraki ? T('Sonraki seviye {0} EP\'de.', fmtN(p.seviye_sonraki)) : T('En yüksek seviye')))),
    seCard(T('Firma'), 'globe', h('p', { class: 'desc' }, T('Firma değişince gemi yeni firmanın ana istasyonuna taşınır.')), companies),
    seCard(T('Cüzdan'), 'star', h('div', { class: 'grid g2' }, currency('kredi', T('Kredi'), p.kredi, [1e6, 1e7, 1e8]), currency('uridyum', T('Uridyum'), p.uridyum, [1e4, 1e5, 1e6]))),
    seCard(T('Hesap'), 'info', h('div', { class: 'kv' },
      h('div', null, T('Klan'), h('b', null, p.klan ? '[' + p.klan + ']' : '—')), h('div', null, T('Rütbe'), h('b', null, p.rutbe ?? '—')),
      h('div', null, T('Oynama'), h('b', null, fmtDur(p.oynama_sn))), h('div', null, T('Oluşturma'), h('b', null, fmtWhen(p.olusturma))),
      h('div', null, T('Uridyum bankası'), h('b', null, fmtN(p.banka))), h('div', null, T('Görevler'), h('b', null, T('{0} alınmış · {1} bitmiş', v.gorevler.aktif, v.gorevler.tamam))))));
}

function seHangar(v) {
  const g = seShip(v), ro = v.salt_okunur, f = companyLower(v.pilot.firma), cfg = g.konfigler[SE.konfig];
  const strip = h('div', { class: 'ke-gemiler' }, v.gemiler.map(x => h('button', { class: 'ke-gemi' + (x.id === g.id ? ' on' : ''), type: 'button', title: itemName(x.lootId),
    onclick: () => { SE.gemi = x.id; SE.konfig = null; seRender(); } }, shipImage(x.gorunum, 62, f), h('span', { class: 'ke-gemi-ad' }, itemName(x.lootId)),
  x.aktif ? h('span', { class: 'ke-etkin' }, T('Etkin')) : null, x.favori ? h('span', { class: 'ke-yildiz' }, icon('star')) : null)),
  ro ? null : h('button', { class: 'ke-gemi ekle', type: 'button', onclick: () => seCatalog({ kat: 'gemi', baslik: T('Gemiler') }) },
    h('span', { class: 'ke-ekle-ic' }, icon('plus')), h('span', { class: 'ke-gemi-ad' }, T('Gemi ekle'))));
  const value = (sp, iconEl, name, n) => h('div', { class: 'ke-gd' }, spr(sp, 26, iconEl), h('span', null, name), h('b', null, n == null ? '—' : fmtN(n)));
  const base = g.lootId.replace(/^ship_/, '');
  const designs = h('div', { class: 'ke-tasarimlar' }, g.tasarimlar.map(t => h('button', { class: 'ke-tasarim' + (t === g.gorunum ? ' on' : ''), type: 'button',
    title: itemName(t), disabled: ro, onclick: () => t !== g.gorunum && seApply({ islem: 'tasarim', gemi: g.id, lootId: t }) }, shipImage(t, 46, f))),
  ro ? null : h('button', { class: 'ke-tasarim ekle', type: 'button', title: T('Tasarım ekle'), onclick: () => seCatalog({ kat: 'tasarim', on: 'ship_' + base + '_design_', baslik: T('{0} tasarımları', itemName(g.lootId)) }) }, icon('plus')));
  const tools = h('div', { class: 'row wrap', style: { gap: '6px' } },
    g.aktif ? null : btn(T('Etkin gemi yap'), () => seApply({ islem: 'etkin_gemi', gemi: g.id }), 'sm primary', 'check', { disabled: ro }),
    SE.konfig !== g.aktif_konfig ? btn(T('Bu config\'i kullan'), () => seApply({ islem: 'konfig', gemi: g.id, konfig: +SE.konfig }), 'sm', 'check', { disabled: ro }) : null,
    btn(g.favori ? T('Favoriden çıkar') : T('Favori yap'), () => seApply({ islem: 'favori', gemi: g.id, favori: !g.favori }), 'sm', 'star', { disabled: ro }),
    btn(T('Aktar…'), () => seTransfer(v, g), 'sm', 'copy', { disabled: ro, title: T('Bu geminin donanımını başka bir gemiye taşır.') }),
    btn(T('Temizle'), async () => await confirmBox(T('Config {0} boşaltılsın mı?', SE.konfig), T('Gemideki, dronlardaki ve P.E.T.\'teki eşyalar envantere iner.'), { ok: T('Temizle'), danger: true })
      && seApply({ islem: 'temizle', gemi: g.id, konfig: +SE.konfig }), 'sm', 'trash', { disabled: ro }),
    btn(T('Kaldır'), async () => await confirmBox(T('{0} kaldırılsın mı?', itemName(g.lootId)), T('Gemi hangardan çıkar; üstündeki donanım envantere iner. Kaydetmeden önce Vazgeç ile geri alınabilir.'),
      { ok: T('Kaldır'), danger: true }) && seApply({ islem: 'gemi_sil', gemi: g.id }), 'sm danger', 'trash', { disabled: ro || g.aktif, title: g.aktif ? T('Etkin gemi kaldırılamaz: önce başka bir gemiyi etkin yap.') : '' }));
  return h('div', { class: 'stack' },
    h('div', { class: 'card ke-k' }, strip),
    h('div', { class: 'card ke-gemi-kart f-' + f },
      h('div', { class: 'ke-gemi-sahne' }, shipImage(g.gorunum, 230, f)),
      h('div', { class: 'ke-gemi-bilgi' },
        h('div', { class: 'row wrap', style: { gap: '8px' } }, h('h2', { class: 'ke-gemi-baslik' }, itemName(g.lootId)),
          g.aktif ? badge(T('Etkin gemi'), 'ok') : null, g.favori ? badge(T('Favori'), 'orange') : null),
        g.tasarim ? h('div', { class: 'small muted' }, T('Görünüm: {0}', itemName(g.tasarim))) : null,
        h('div', { class: 'ke-gdler' }, value('hitpoints_100x100', 'heart', T('Can'), g.deger.can), value('shield_100x100', 'shield', T('Kalkan'), g.deger.kalkan),
          value('speed_100x100', 'gauge', T('Hız'), g.deger.hiz), value('damage_laser_100x100', 'zap', T('Lazer hasarı'), g.deger.hasar), value(null, 'box', T('Kargo'), g.deger.kargo)),
        g.tasarimlar.length > 1 || !ro ? h('div', null, h('div', { class: 'lbl', style: { marginBottom: '6px' } }, T('Görünüm')), designs) : null,
        h('div', { class: 'seg' }, Object.keys(g.konfigler).map(c => h('button', { class: c === SE.konfig ? 'on info' : '', onclick: () => { SE.konfig = c; seRender(); } },
          T('Config {0}', c), c === g.aktif_konfig ? ' •' : ''))),
        tools)),
    h('div', { class: 'ke-yuvalar' }, g.yuvalar.map(y => seSlotBox(slotName(y), cfg[y], { hedef: 'ship', yuva: y }))));
}

function seTransfer(v, g) {
  let target = null;
  const entries = h('div', { class: 'ke-gemiler sar' }, v.gemiler.filter(x => x.id !== g.id).map(x => h('button', { class: 'ke-gemi', type: 'button', onclick: ev => {
    target = x.id; entries.querySelectorAll('.ke-gemi').forEach(b => b.classList.toggle('on', b === ev.currentTarget)); } },
  shipImage(x.gorunum, 54, companyLower(v.pilot.firma)), h('span', { class: 'ke-gemi-ad' }, itemName(x.lootId)))));
  const m = modal({ title: T('Donanımı aktar'), sub: T('{0} gemisinin iki config\'i, dronları ve P.E.T. donanımı seçtiğin gemiye taşınır.', itemName(g.lootId)), wide: true, body: [entries],
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Aktar'), () => { if (!target) return toast(T('Bir gemi seç.'), 'err'); m.close(); seApply({ islem: 'aktar', gemi: g.id, target }); }, 'primary')] });
}

function seDrones(v) {
  const g = seShip(v), ro = v.salt_okunur, dcfg = g.dronlar[SE.konfig] || {};
  const new_ = ['drone_flax', 'drone_iris', 'drone_apis', 'drone_zeus'].map(l => h('button', { class: 'ke-dron-ekle', type: 'button', disabled: ro,
    title: T('{0} ekle', itemName(l)), onclick: () => seApply({ islem: 'ver', esyalar: [[l, 1]] }) }, droneImage(l, 1, 40), h('span', null, itemName(l)), icon('plus')));
  const card = d => {
    const c = dcfg[d.id] || { esyalar: [] }, tgt = { hedef: 'drone', dron: d.id }, tgtDesign = { hedef: 'drone', dron: d.id, yuva: 'tasarim' };
    const upgradeLabel = h('b', { class: 'ke-sv-deger sm' }, '+' + d.yukseltme);
    return h('div', { class: 'card ke-dron' },
      h('div', { class: 'ke-dron-gorsel' }, droneImage(d.lootId, d.seviye, 76)),
      h('div', { class: 'ke-dron-govde' },
        h('div', { class: 'row between' }, h('b', { class: 'ke-dron-ad' }, itemName(d.lootId)),
          btn('', async () => await confirmBox(T('{0} kaldırılsın mı?', itemName(d.lootId)), T('Dron kaldırılır; üstündeki eşyalar envantere iner.'), { ok: T('Kaldır'), danger: true })
            && seApply({ islem: 'dron_sil', dron: d.id }), 'ghost sm icon', 'trash', { disabled: ro, title: T('Kaldır') })),
        h('div', { class: 'ke-dron-satir' }, h('span', { class: 'lbl' }, T('Seviye')),
          h('div', { class: 'ke-pipler' }, v.dron_seviyeleri.map((points, i) => h('button', { class: 'ke-pip' + (i < d.seviye ? ' on' : ''), type: 'button', disabled: ro,
            title: T('Seviye {0} ({1} puan)', i + 1, fmtN(points)), onclick: () => i + 1 !== d.seviye && seApply({ islem: 'dron', dron: d.id, seviye: i + 1 }) }))),
          h('span', { class: 'small dim' }, T('{0} puan', fmtN(d.puan)))),
        h('div', { class: 'ke-dron-satir' }, h('span', { class: 'lbl' }, T('Yükseltme')),
          slider({ min: 0, max: d.yukseltme_azami, value: d.yukseltme, disabled: ro,
            oninput: e => { upgradeLabel.textContent = '+' + e.target.value; }, onchange: e => seApply({ islem: 'dron', dron: d.id, yukseltme: +e.target.value }) }), upgradeLabel),
        h('div', { class: 'ke-hucreler' }, c.esyalar.map(e => seCell(e, tgt)), Array.from({ length: Math.max(0, d.kapasite - c.esyalar.length) }, () => seEmptyCell(tgt)),
          h('span', { class: 'ke-ayrac' }),
          c.tasarim ? seCell(c.tasarim, tgtDesign) : seEmptyCell(tgtDesign, 'wand', T('Tasarım yuvası')),
          c.gorunum ? seCell(c.gorunum, tgtDesign) : seEmptyCell(tgtDesign, 'wand', T('Görünüm yuvası')))));
  };
  return h('div', { class: 'stack' },
    h('div', { class: 'card ke-k' }, h('div', { class: 'row wrap between', style: { gap: '12px' } }, shipPicker(v, g),
      h('span', { class: 'pill' }, icon('drone'), T('Dronlar'), ' ', h('b', null, v.dronlar.filter(d => !d.tek).length + ' / ' + v.dron_azami))),
    h('p', { class: 'desc', style: { margin: '10px 0 8px' } }, T('Donanım seçili geminin seçili config\'inde durur (oyundaki gibi her geminin iki config\'i).')),
    ro ? null : h('div', { class: 'ke-dron-ekler' }, new_)),
    v.dronlar.length ? h('div', { class: 'ke-dronlar' }, v.dronlar.map(card)) : h('div', { class: 'card empty' }, icon('drone'), h('div', null, T('Dron yok.'))));
}

function sePet(v) {
  const p = v.pet, ro = v.salt_okunur;
  if (!p) return h('div', { class: 'card ke-pet-yok' }, petImage(0, 150), h('div', null, h('h3', null, T('Bu pilotun P.E.T.\'i yok')),
    h('p', { class: 'muted' }, T('P.E.T. ver: seviye 0, başlangıç yakıtı ve yuvalarıyla gelir; sonra seviyesini ve yuvalarını buradan ayarlayabilirsin.')),
    btn(T('P.E.T. ver'), () => seApply({ islem: 'pet', ver: true }), 'primary', 'plus', { disabled: ro })));
  const g = seShip(v), pc = (g.pet || {})[SE.konfig] || {};
  const op = x => seApply(Object.assign({ islem: 'pet' }, x));
  const lvlLabel = h('b', null, p.seviye), fuelLabel = h('b', { class: 'mono' }, fmtN(p.yakit));
  const name = h('input', { class: 'input', value: p.ad || '', maxlength: 24, disabled: ro, onchange: e => e.target.value.trim() && e.target.value.trim() !== p.ad && op({ ad: e.target.value }) });
  return h('div', { class: 'stack' },
    h('div', { class: 'card ke-pet' },
      h('div', { class: 'ke-pet-sahne' }, h('div', { class: 'ke-halka' }), petImage(p.seviye, 190)),
      h('div', { class: 'ke-pet-govde stack', style: { gap: '14px' } },
        h('div', { class: 'row wrap', style: { gap: '8px' } }, h('h2', { class: 'ke-gemi-baslik' }, p.ad || 'P.E.T.'), p.yikik ? badge(T('Yıkık'), 'err') : badge(T('Hazır'), 'ok'),
          p.heat ? badge('HEAT ' + p.heat, 'orange') : null),
        field(T('Ad'), name),
        h('div', { class: 'ke-sv-duzen' },
          h('div', { class: 'ke-sv-buyuk' }, h('button', { class: 'btn icon', type: 'button', disabled: ro || p.seviye <= 0, onclick: () => op({ seviye: p.seviye - 1 }) }, icon('minus')),
            h('div', null, h('small', null, T('Seviye')), lvlLabel),
            h('button', { class: 'btn icon', type: 'button', disabled: ro || p.seviye >= p.azami_seviye, onclick: () => op({ seviye: p.seviye + 1 }) }, icon('plus'))),
          h('div', { class: 'grow' }, slider({ min: 0, max: p.azami_seviye, value: p.seviye, disabled: ro,
            oninput: e => { lvlLabel.textContent = e.target.value; }, onchange: e => +e.target.value !== p.seviye && op({ seviye: +e.target.value }) }),
          h('div', { class: 'row between small dim' }, h('span', null, '0'), h('span', null, T('{0} EP', fmtN(p.ep))), h('span', null, p.azami_seviye)))),
        h('div', null, h('div', { class: 'row between' }, h('span', { class: 'lbl' }, T('Yakıt')), h('span', null, fuelLabel, h('span', { class: 'dim' }, ' / ' + fmtN(p.yakit_azami)))),
          slider({ min: 0, max: p.yakit_azami, step: 100, value: p.yakit, disabled: ro,
            oninput: e => { fuelLabel.textContent = fmtN(+e.target.value); }, onchange: e => op({ yakit: +e.target.value }) }, 'yakit')),
        p.yikik ? btn(T('Onar'), () => op({ onar: true }), 'sm primary', 'wrench', { disabled: ro }) : null)),
    seCard(T('Açık yuvalar'), 'layers', h('p', { class: 'desc' }, T('Oyunda uridyumla açılan yuvalar; seviyenin verdiğinden azı seçilemez.')),
      h('div', { class: 'ke-pet-yuvalar' }, Object.keys(p.yuva_azami).filter(y => y !== 'heat').map(y => h('div', { class: 'ke-pet-yuva' }, h('span', null, slotName(y)),
        stepBox(p.yuva[y] || 0, p.yuva_azami[y], n => op({ yuva: { [y]: n } })))))),
    h('div', { class: 'card ke-k' }, h('div', { class: 'row wrap between', style: { gap: '12px' } }, h('h2', { style: { margin: 0 } }, icon('box'), T('Donanım')), shipPicker(v, g)),
      h('div', { class: 'ke-yuvalar', style: { marginTop: '12px' } }, v.pet_yuvalari.filter(y => pc[y] && (pc[y].kapasite || pc[y].esyalar.length))
        .map(y => seSlotBox(slotName(y), pc[y], { hedef: 'pet', yuva: y, kume: y === 'heat' ? 'heat' : '' })))));
}

function seInventory(v) {
  const g = seShip(v), ro = v.salt_okunur;
  const empty = v.envanter.filter(e => !seIsEquipped(e));          // inventory tab: only items equipped nowhere (delete, edit)
  const kinds = [...new Set(empty.map(e => e.yuva))];
  if (SE.invKind !== 'hepsi' && !kinds.includes(SE.invKind)) SE.invKind = 'hepsi';
  const q = SE.ara.toLowerCase();
  const entries = empty.filter(e => (SE.invKind === 'hepsi' || e.yuva === SE.invKind) && (!q || itemName(e.lootId).toLowerCase().includes(q) || e.lootId.includes(q)));
  const grid = h('div', { class: 'ke-env' }, groupItems(entries).map(gr => {
    const e = gr[0];
    return seItemButton({ class: 'ke-env-esya', type: 'button', onclick: ev => !ro && popMenu(ev.currentTarget, [
      e.hedefler.includes('ship') ? { label: T('Seçili gemiye tak ({0}, config {1})', itemName(g.lootId), SE.konfig), ic: 'download', fn: () => seApply(moveOp(e.id, 'tak', { hedef: 'ship' })) } : null,
      seIsEditable(e) ? { label: T('Düzenle…'), ic: 'edit', fn: () => seEdit(e) } : null,
      '-',
      { label: T('Bir tanesini sil'), ic: 'trash', danger: true, fn: () => seApply({ islem: 'sil', esyalar: [e.id] }) },
      gr.length > 1 ? { label: T('Hepsini sil ({0})', gr.length), ic: 'trash', danger: true, fn: () => seApply({ islem: 'sil', esyalar: gr.map(x => x.id) }) } : null,
    ].filter(Boolean)) }, e, itemIcon(e.lootId, 54), ...lvlBadge(e), gr.length > 1 ? h('span', { class: 'ke-adet' }, '×' + gr.length) : null, h('span', { class: 'ad' }, itemName(e.lootId)));
  }));
  return h('div', { class: 'stack' },
    h('div', { class: 'card ke-k' }, h('div', { class: 'row wrap', style: { gap: '10px' } },
      h('input', { class: 'input oy-ara', placeholder: T('Ara…'), value: SE.ara, oninput: e => seSearch(e, v => { SE.ara = v; }) }),
      h('span', { class: 'spacer' }), ro ? null : btn(T('Eşya ekle'), () => seCatalog({}), 'primary sm', 'plus')),
    kinds.length > 1 ? h('div', { class: 'seg', style: { marginTop: '12px', flexWrap: 'wrap' } }, ['hepsi', ...kinds].map(t => h('button', { class: t === SE.invKind ? 'on info' : '',
      onclick: () => { SE.invKind = t; seRender(); } }, t === 'hepsi' ? T('Hepsi') : t === 'tasarim' ? T('Dron tasarımları') : slotName(t)))) : null),
    entries.length ? h('div', { class: 'card ke-k' }, grid) : h('div', { class: 'card empty' }, icon('box'), h('div', null, empty.length ? T('Aramaya uyan eşya yok.') : T('Envanter boş: bütün eşyalar takılı.'))));
}

function seAmmo(v) {
  const ro = v.salt_okunur, groups = {};
  for (const c of v.cephane) if (!SE.ammoFilled || c[1]) (groups[c[2]] = groups[c[2]] || []).push(c);
  const box = ([l, n]) => h('div', { class: 'ke-cep' + (n ? '' : ' sifir') }, itemIcon(l, 44), h('div', { class: 'grow', style: { minWidth: 0 } },
    h('div', { class: 'ke-cep-ad', title: l }, itemName(l)), numberBox(n, x => seApply({ islem: 'cephane', adetler: { [l]: x } }), { max: 1e12, cls: 'genis' })));
  const bulkSet = async entries => { const s = await promptBox(T('Hepsine aynı adet'), T('Adet'), '100000'); if (s == null) return;
    const n = Math.max(0, Math.round(+s) || 0); seApply({ islem: 'cephane', adetler: Object.fromEntries(entries.map(c => [c[0], n])) }); };
  const full = h('input', { type: 'checkbox', checked: SE.ammoFilled, onchange: e => { SE.ammoFilled = e.target.checked; seRender(); } });
  return h('div', { class: 'stack' },
    h('div', { class: 'card ke-k row wrap', style: { gap: '14px' } }, h('label', { class: 'row small' }, h('span', { class: 'switch' }, full, h('span')), T('Yalnız elde olanları göster')),
      h('span', { class: 'spacer' }), h('span', { class: 'small muted' }, T('Toplam {0} tür, {1} tanesi elde.', v.cephane.length, v.cephane.filter(c => c[1]).length))),
    ...SE_AMMO.filter(([k]) => groups[k]).map(([k, name]) => seCard(null, null,
      h('div', { class: 'row between', style: { marginBottom: '12px' } }, h('h2', { style: { margin: 0 } }, icon('ammo'), T(name)),
        ro ? null : btn(T('Hepsine aynı adet…'), () => bulkSet(groups[k]), 'sm ghost', 'edit')),
      h('div', { class: 'ke-cepler' }, groups[k].map(box)))));
}

function seResources(v) {
  const ro = v.salt_okunur, d = v.durum, q = SE.resourceSearch.toLowerCase();
  const ore = ([t, l, n]) => h('div', { class: 'ke-cep' + (n ? '' : ' sifir') }, itemIcon(l, 44), h('div', { class: 'grow', style: { minWidth: 0 } },
    h('div', { class: 'ke-cep-ad' }, itemName(l)), numberBox(n, x => seApply({ islem: 'cevher', adetler: { [t]: x } }), { max: 1e9, cls: 'genis' })));
  const sources = v.kaynaklar.filter(([l]) => !q || l.includes(q) || itemName(l).toLowerCase().includes(q));
  return h('div', { class: 'stack' },
    seCard(null, null, h('div', { class: 'row between', style: { marginBottom: '12px' } }, h('h2', { style: { margin: 0 } }, icon('gem'), T('Cevherler')),
      h('span', { class: 'pill' }, icon('box'), T('Kargo'), ' ', h('b', null, fmtN(d.kargo) + ' / ' + fmtN(d.kargo_azami)))),
    h('div', { class: 'ke-cepler' }, v.cevherler.map(ore))),
    seCard(null, null, h('div', { class: 'row wrap between', style: { gap: '10px', marginBottom: '12px' } }, h('h2', { style: { margin: 0 } }, icon('gift'), T('Toplanabilirler ve öbür kaynaklar')),
      h('div', { class: 'row', style: { gap: '8px' } }, h('input', { class: 'input oy-ara', placeholder: T('Ara…'), value: SE.resourceSearch,
        oninput: e => seSearch(e, v => { SE.resourceSearch = v; }) }),
      ro ? null : btn(T('Kaynak ekle'), () => seCatalog({ kat: 'kaynak', baslik: T('Kaynaklar') }), 'primary sm', 'plus'))),
    sources.length ? h('div', { class: 'ke-cepler' }, sources.map(([l, n]) => h('div', { class: 'ke-cep' }, itemIcon(l, 44), h('div', { class: 'grow', style: { minWidth: 0 } },
      h('div', { class: 'ke-cep-ad', title: l }, itemName(l)), h('div', { class: 'row', style: { gap: '4px' } }, numberBox(n, x => seApply({ islem: 'kaynak', adetler: { [l]: x } }), { max: 1e12, cls: 'genis' }),
        ro ? null : btn('', () => seApply({ islem: 'kaynak', adetler: { [l]: 0 } }), 'ghost sm icon', 'x', { title: T('Kaldır') }))))))
      : h('div', { class: 'empty' }, T('Kaynak yok.'))));
}

function seBoosters(v) {
  const ro = v.salt_okunur;
  const row = ([l, sec]) => {
    const hour = h('input', { class: 'input num', type: 'number', min: 0, step: 0.5, value: Math.round(sec / 360) / 10, disabled: ro,
      onchange: e => { const s = Math.max(0, Math.round((+e.target.value || 0) * 3600)); if (s !== sec) seApply({ islem: 'booster', sureler: { [l]: s } }); } });
    return h('div', { class: 'ke-boost' }, itemIcon(l, 48), h('div', { class: 'grow', style: { minWidth: 0 } }, h('b', null, itemName(l)), h('div', { class: 'small muted' }, T('{0} kaldı', fmtDur(sec)))),
      h('label', { class: 'row small' }, hour, T('saat')), ro ? null : btn('', () => seApply({ islem: 'booster', sureler: { [l]: 0 } }), 'ghost sm icon', 'x', { title: T('Kaldır') }));
  };
  return h('div', { class: 'stack' },
    h('div', { class: 'card ke-k row wrap', style: { gap: '10px' } }, h('span', { class: 'small muted grow' }, T('Editörden verilen booster, uzaylıdan düşen gibi yalnız oyun açıkken işler.')),
      ro ? null : btn(T('Booster ekle'), () => seCatalog({ kat: 'booster', baslik: T('Boosterlar') }), 'primary sm', 'plus')),
    v.boosterlar.length ? h('div', { class: 'card ke-k ke-boostlar' }, v.boosterlar.map(row)) : h('div', { class: 'card empty' }, icon('zap'), h('div', null, T('Etkin booster yok.'))));
}

function seMaintenance(v) {
  const ro = v.salt_okunur, d = v.durum;
  const row = (iconEl, title, description, ...button) => h('div', { class: 'ke-bakim' }, h('span', { class: 'ke-bakim-ic' }, icon(iconEl)),
    h('div', { class: 'grow' }, h('b', null, title), h('div', { class: 'small muted' }, description)), ...button);
  const boxes = Object.fromEntries(SE_RESET.map(([k]) => [k, h('input', { type: 'checkbox', disabled: ro })]));
  return h('div', { class: 'stack' },
    seCard(T('Gemi ve konum'), 'wrench',
      row('heart', T('Gemiyi onar'), T('Can {0} / {1}, kalkan {2} / {3}.', fmtN(d.can), fmtN(d.can_azami), fmtN(d.kalkan), fmtN(d.kalkan_azami)),
        btn(T('Onar'), () => seApply({ islem: 'onar' }), 'sm', 'wrench', { disabled: ro || (d.can >= d.can_azami && d.kalkan >= d.kalkan_azami) })),
      row('map', T('Ana istasyona taşı'), T('Şu an {0}; firmanın ana haritası {1}. Bir haritada takılı kaldıysan.', d.harita_ad, d.ana_harita),
        btn(T('Taşı'), () => seApply({ islem: 'ana_us' }), 'sm', 'map', { disabled: ro })),
      row('sliders', T('Tuş atamaları'), T('Varsayılana döner (oyundaki Ayarlar > Reset sunucuya ulaşmıyor).'),
        btn(T('Varsayılana döndür'), async () => await confirmBox(T('Tuş atamaları varsayılana dönsün mü?'), T('Kendi atadığın tuşlar silinir.'), { ok: T('Döndür') }) && seApply({ islem: 'tuslar' }),
          'sm', 'undo', { disabled: ro }))),
    seCard(T('Durum sıfırlama'), 'refresh', h('div', { class: 'stack', style: { gap: '8px' } },
      SE_RESET.map(([k, t]) => h('label', { class: 'row small' }, h('span', { class: 'switch' }, boxes[k], h('span')), T(t)))),
    h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '12px' } }, btn(T('Seçilenleri sıfırla'), () => {
      const b = SE_RESET.map(([k]) => k).filter(k => boxes[k].checked);
      if (!b.length) return toast(T('Sıfırlanacak bölüm seç.'), 'err');
      seApply({ islem: 'sifirla', bolumler: b });
    }, 'sm', 'refresh', { disabled: ro }))),
    h('div', { class: 'small dim' }, T('Bütün değişiklikler önce taslakta durur; Kaydet\'e basınca kayda yazılır ve önceki hâli yedeklenir.')));
}

const SE_RENDER = { pilot: sePilot, hangar: seHangar, dronlar: seDrones, pet: sePet, envanter: seInventory, cephane: seAmmo, kaynaklar: seResources,
  boosterlar: seBoosters, bakim: seMaintenance, istatistik: seStats };

// İstatistik (salt okunur; kayit_editoru.istatistik): rütbe puanı, öldürmeler, ölümler, kapılar ve süreleri, modların en iyileri
const SE_POINTS = [['ExperiencePoints', N('Deneyim (EP)')], ['honorPoints', N('Onur')], ['yourLevel', N('Seviye')], ['npcShotPoints', N('Uzaylı puanı')],
  ['playerShotPoints', N('Oyuncu puanı')], ['missionsCompleted', N('Biten görev')], ['daysSinceRegistration', N('Kayıttan beri gün')],
  ['DestroyedByEnemies', N('Düşmana yenilme')], ['DestroyedByRadiationZone', N('Radyasyonda ölüm')], ['friendlyPlayersDestroyed', N('Dost öldürme')]];
const seDuration = sec => sec ? (sec >= 3600 ? Math.floor(sec / 3600) + ':' : '') + String(Math.floor(sec / 60) % 60).padStart(sec >= 3600 ? 2 : 1, '0') + ':' + String(sec % 60).padStart(2, '0') : '—';
function seStats(v) {
  const s = v.istatistik || {}, p = s.puan || {};
  const table = (titles, lines, empty) => lines.length ? h('div', { class: 'bt-tablo' }, h('table', { class: 'table' },
    h('thead', null, h('tr', null, titles.map(x => h('th', null, x)))), h('tbody', null, lines)))
    : h('div', { class: 'small muted' }, empty);
  return h('div', { class: 'stack' },
    seCard(T('Rütbe puanı'), 'star', h('div', { class: 'row wrap', style: { gap: '8px', marginBottom: '8px' } },
      badge(T('Rütbe puanı') + ': ' + fmtN(p.rankPoints || 0), 'info'), badge(T('Oyun süresi') + ': ' + fmtDur(s.oynama_sn || 0), '')),
      h('div', { class: 'ke-istat' }, SE_POINTS.map(([k, name]) => h('div', { class: 'row' }, h('span', { class: 'grow muted' }, T(name)), h('b', null, fmtN(p[k] || 0)))))),
    seCard(T('Kapılar'), 'globe', table([T('Kapı'), T('Tamamlama'), T('En iyi süre'), T('Son süre')],
      (s.kapilar || []).map(k => h('tr', null, h('td', null, k.ad), h('td', { class: 'num' }, fmtN(k.tamam)), h('td', { class: 'num' }, seDuration(k.en_iyi)), h('td', { class: 'num' }, seDuration(k.son)))),
      T('Henüz tamamlanan kapı yok.')),
      h('div', { class: 'small muted', style: { marginTop: '6px' } }, T('Süre kapının ilk dalgasına girişten tamamlanmaya; bu sürümden önce biten kapıların süresi yok.'))),
    seCard(T('Öldürülen uzaylılar'), 'zap', table([T('Uzaylı'), T('Sayı'), T('Puan')],
      (s.npc || []).map(([name, n, pts]) => h('tr', null, h('td', null, name), h('td', { class: 'num' }, fmtN(n)), h('td', { class: 'num' }, fmtN(pts * n)))), T('Henüz uzaylı öldürülmedi.'))),
    seCard(T('Oyuncular ve ölümler'), 'shield', h('div', { class: 'ke-istat' },
      [[T('Düşmana yenilme'), (s.olum || {}).dusman], [T('Radyasyonda ölüm'), (s.olum || {}).radyasyon], [T('Öteki ölümler'), (s.olum || {}).diger],
       [T('Dost öldürme'), s.dost], [T('Biten görev'), s.gorev], [T('Eternal Black Light en iyi dalga'), (s.modlar || {}).ebl],
       [T('Frozen Labyrinth avı'), (s.modlar || {}).labirent], [T('Mimesis en iyi sefer'), (s.modlar || {}).mimesis]]
        .map(([name, n]) => h('div', { class: 'row' }, h('span', { class: 'grow muted' }, name), h('b', null, fmtN(n || 0))))),
      table([T('Gemi'), T('Öldürülen')], (s.oyuncu || []).map(([name, n]) => h('tr', null, h('td', null, name), h('td', { class: 'num' }, fmtN(n)))), T('Henüz oyuncu öldürülmedi.'))));
}

// ---- değişiklik özeti, kaydet, vazgeç
function seChanges() {
  const f = SE.v.fark, ro = SE.v.salt_okunur;
  const value = (k, x) => x == null ? '—' : k === 'firma' ? COMPANY_TAG[x] || x : k === 'aktif_gemi' ? itemName(x) : k === 'premium' ? (x ? T('Açık') : T('Kapalı'))
    : typeof x === 'number' ? fmtN(x) : String(x);
  const section = (title, ...contents) => contents.flat().filter(Boolean).length ? h('div', { class: 'ke-fark' }, h('div', { class: 'lbl' }, title), ...contents) : null;
  const items = (o, cls) => Object.keys(o).length ? h('div', { class: 'ke-fark-esyalar' }, Object.entries(o).map(([l, n]) => h('div', { class: 'ke-fark-esya ' + cls },
    itemIcon(l, 32), h('span', null, itemName(l)), h('b', null, (cls === 'arti' ? '+' : '−') + fmtN(n))))) : null;
  const m = modal({ title: T('Kaydedilmemiş değişiklikler'), sub: T('Kaydet\'e basınca bunlar kayda yazılır; önceki hâli "Geri yükleme öncesi" yedeği olarak saklanır.'), wide: true,
    body: [
      section(T('Değerler'), f.alanlar.map(([k, a, b]) => h('div', { class: 'ke-fark-alan' }, h('span', null, T(SE_FIELD[k] || k)), h('s', null, value(k, a)), icon('arrowR'), h('b', null, value(k, b))))),
      section(T('Eklenenler'), items(f.eklenen, 'arti')),
      section(T('Kaldırılanlar'), items(f.cikan, 'eksi')),
      section(T('Adetler'), f.adetler.map(([l, a, b]) => h('div', { class: 'ke-fark-alan' }, h('span', { class: 'row', style: { gap: '8px' } }, itemIcon(l, 26), itemName(l)), h('s', null, fmtN(a)), icon('arrowR'), h('b', null, fmtN(b))))),
      section(T('Boosterlar'), f.boosterlar.length ? h('div', { class: 'small' }, f.boosterlar.map(itemName).join(', ')) : null),
      section(T('Seviyeler'), f.seviyeler.length ? h('div', { class: 'small' }, [...new Set(f.seviyeler)].map(l => l === 'pet' ? 'P.E.T.' : itemName(l)).join(', ')) : null),
      section(T('Donanım'), f.donanim ? h('div', { class: 'small' }, T('{0} eşyanın yeri değişti (takıldı, çıkarıldı ya da taşındı).', f.donanim)) : null),
      !f.sayi ? h('div', { class: 'empty' }, T('Değişiklik yok.')) : null],
    foot: [btn(T('Kapat'), () => m.close(), 'ghost'), ro ? null : btn(T('Vazgeç'), () => { m.close(); seCancel(); }, 'danger', 'undo', { disabled: !f.sayi }),
      ro ? null : btn(T('Kaydet'), () => { m.close(); seSave(); }, 'primary', 'save', { disabled: !f.sayi })] });
}

async function seSave() {
  const r = await act(() => api('/api/editor/kaydet', { id: SE.slot }), T('Kaydedildi. Önceki hâli yedeklendi.'));
  if (r && SE.slot) { SE.v = null; renderEditor(); }
}
async function seCancel() {
  const n = SE.v?.fark?.sayi || 0;
  if (!await confirmBox(T('Değişiklikler atılsın mı?'), T('Taslaktaki {0} değişiklik silinir; kayıt olduğu gibi kalır.', n), { ok: T('At'), danger: true })) return;
  const r = await act(() => api('/api/editor/vazgec', { id: SE.slot }), T('Değişiklikler atıldı.'));
  if (r && SE.slot) { SE.v = null; renderEditor(); }
}
