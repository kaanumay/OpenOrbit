/* OpenOrbit paneli — Kayıtlar ve karakter editörü (kayitlar.py, kayit_editoru.py; /api/kayitlar…, /api/editor…). panel.js'in
   yardımcılarını ve oyunun görsellerini (ogYukle, sprite, esyaSprite, esyaAdi: BepInEx dökümü) kullanır.
   Kitaplık: etkin kaydın sahnesi (gemi, firma portresi, seviye ilerlemesi, cüzdan), öbür kayıtların kartları, silinenler.
   Editör: kaydın taslağında (duzenleme.json) çalışır. Her işlem oyunun kurallarıyla (hangar, ödül yolu) taslağa uygulanır ve görünüm
   yenilenir; Kaydet güvenlik yedeği alıp kayda yazar, Vazgeç taslağı atar. Kayıt oyundaysa salt okunur. */
'use strict';

Object.assign(IC, {
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

const KF = { 1: 'MMO', 2: 'EIC', 3: 'VRU' };
const kfKucuk = f => (typeof f === 'number' ? KF[f] : f || '').toLowerCase();
const fmtKisa = n => { try { return new Intl.NumberFormat(LOC(), { notation: 'compact', maximumFractionDigits: 1 }).format(n || 0); } catch (e) { return fmtN(n); } };
const keBos = (boy, ic) => h('span', { class: 'sprite bos', style: { width: boy + 'px', height: boy + 'px' } }, icon(ic));
const spr = (ad, boy, ic = 'box') => OG.dizin?.sprite[ad] ? sprite(ad, boy) : keBos(boy, ic);
// gemi: tepeden büyük görünüm (_top), yoksa mağaza ikonu; tasarımın kendi görünümü önce (ship_sentinel_design_sentinel-carbonite)
function gemiSprite(lid, firma) {
  const k = lid.replace(/^ship_/, ''), son = k.split('_').pop(), taban = k.split('_')[0];
  for (const c of [son, son + '-' + firma, taban, taban + '-' + firma]) for (const b of ['_top', '_100x100']) if (OG.dizin?.sprite[c + b]) return c + b;
  return esyaSprite(lid, firma);
}
const gemiGorsel = (lid, boy, firma) => {
  const sp = lid && OG.dizin && gemiSprite(lid, firma), el = sp ? sprite(sp, boy) : keBos(boy, 'ship');
  if (lid) el.dataset.loot = lid;              // eşya ipucu: değerler, yuvalar, bonus (panel.js esyaIpucu)
  return el;
};
// dron: seviyesinin görünümü (iris-4: 5. seviye), yoksa daha düşüğü
function dronSprite(lid, sv) {
  const b = lid.replace(/^drone_/, '');
  for (let n = Math.min(5, (sv || 1) - 1); n >= 0; n--) for (const s of ['_100x100', '_top']) if (OG.dizin?.sprite[b + '-' + n + s]) return b + '-' + n + s;
  return esyaSprite(lid);
}
const dronGorsel = (lid, sv, boy) => {
  const sp = OG.dizin && dronSprite(lid, sv), el = sp ? sprite(sp, boy) : keBos(boy, 'drone');
  el.dataset.loot = lid;
  return el;
};
const petGorsel = (sv, boy) => spr(OG.dizin?.sprite['pet10-' + (sv || 0) + '_top'] ? 'pet10-' + (sv || 0) + '_top' : 'pet10_100x100', boy, 'paw');
const esyaIkon = (lid, boy, firma) => oyunIkon(lid, boy, firma || kfKucuk(KE.v?.pilot.firma), 'box');
// firmanın oyundaki karakter portresi (CommonUI eic_char), yoksa panelin arması
const portre = (f, cls = 'ke-portre', boy = 112) => OG.dizin?.sprite[kfKucuk(f) + '_char'] ? h('span', { class: cls }, sprite(kfKucuk(f) + '_char', boy))
  : h('span', { class: cls + ' arma' }, art('firma_' + (kfKucuk(f) || 'eic'), 'crest'));
function epBar(ep, taban, sonraki, cls = '') {
  const p = sonraki ? Math.max(0, Math.min(1, (ep - taban) / Math.max(1, sonraki - taban))) : 1;
  return h('div', { class: 'ke-ep ' + cls, title: sonraki ? T('{0} / {1} EP', fmtN(ep), fmtN(sonraki)) : T('En yüksek seviye') }, h('span', { style: { width: (p * 100).toFixed(1) + '%' } }));
}

// ================================================================== KİTAPLIK
const KL = { cop: false };

async function renderKayitlar() {
  if (KE.slot) return renderEditor();
  await ogYukle();
  const r = await act(() => api('/api/kayitlar')); if (!r || S.page !== 'kayitlar' || KE.slot) return;
  const aktif = r.liste.find(k => k.aktif), digerleri = r.liste.filter(k => !k.aktif);
  const tools = h('div', { class: 'row wrap' },
    btn(T('Yeni kayıt'), () => newSaveModal(), 'primary', 'plus'),
    btn(T('İçe aktar…'), () => act(() => api('/api/kayitlar/iceri', {}), x => x.iptal ? T('İptal edildi.') : T('Kayıt içe aktarıldı.')).then(() => renderKayitlar()), '', 'upload'),
    h('span', { class: 'spacer' }),
    r.liste.length ? h('span', { class: 'small muted' }, T('{0} kayıt', r.liste.length)) : null,
    btn(T('Kayıt klasörü'), () => act(() => api('/api/klasor_ac', { ne: 'kayitlar' })), 'ghost', 'folder'));
  $('#content').replaceChildren(h('div', { class: 'stack ke-kitap' }, tools,
    aktif ? kayitSahnesi(aktif) : h('div', { class: 'card empty' }, art('bos_kayit'), h('h3', null, T('Henüz kayıt yok')),
      h('div', null, T('Yeni bir kayıt oluştur ya da bir yedeği içe aktar.'))),
    digerleri.length ? h('div', { class: 'section-title' }, T('Öbür kayıtlar ({0})', digerleri.length)) : null,
    digerleri.length ? h('div', { class: 'ke-kartlar' }, digerleri.map(kayitKarti)) : null,
    silinenler(r.silinenler)));
}

// kayıt kartlarının ortak "Diğer" menüsü (ek istemci, ad, not, kopya, dışa aktarma, klasör, silme)
function kayitMenusu(k, ev) {
  const c = S.durum?.coklu, extra = c && c.ayar && c.kayit_sayisi > 1 && (c.kayitlar || []).find(x => x.id === k.id);
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
  ].filter(Boolean));
}
const durumRozetleri = k => [k.kullanimda ? badge(T('OYUNDA'), 'ok') : null, k.taslak ? badge(T('KAYDEDİLMEMİŞ DEĞİŞİKLİK'), 'warn') : null,
  k.bozuk ? badge(T('BOZUK'), 'err') : null];

// etkin kayıt: geniş sahne (gemi, firma portresi, seviye, cüzdan, eylemler)
function kayitSahnesi(k) {
  const f = kfKucuk(k.firma);
  const para = (ad, n, etiket) => h('div', { class: 'ke-para-k' }, art('kaynak_' + ad, 'ke-para-ic'), h('div', null, h('span', null, etiket), h('b', null, fmtN(n))));
  const meta = (ic, etiket, deger) => h('div', { class: 'ke-meta' }, icon(ic), h('span', null, etiket), h('b', null, deger));
  return h('div', { class: 'card ke-sahne f-' + f },
    h('div', { class: 'ke-sahne-gemi' }, gemiGorsel(k.gemi_gorunum, 250, f),
      h('div', { class: 'ke-sahne-gemi-ad' }, k.gemi_gorunum ? esyaAdi(k.gemi_gorunum) : k.gemi)),
    h('div', { class: 'ke-sahne-govde' },
      h('div', { class: 'row wrap', style: { gap: '8px' } }, badge(T('ETKİN KAYIT'), 'info'), ...durumRozetleri(k)),
      h('div', { class: 'ke-sahne-bas' }, portre(k.firma),
        h('div', { style: { minWidth: 0 } }, h('h2', { class: 'ke-sahne-ad' }, k.ad),
          h('div', { class: 'ke-pilot' }, h('b', null, k.pilot), k.klan ? h('span', { class: 'ke-klan' }, '[' + k.klan + ']') : null,
            badge(k.firma || '?', firmaCls(k.firma)), k.premium ? badge('Premium', 'orange') : null))),
      h('div', { class: 'ke-sv' }, h('div', { class: 'ke-sv-n' }, h('small', null, T('Seviye')), h('b', null, k.seviye ?? '?')),
        h('div', { class: 'grow' }, h('div', { class: 'row between small muted' }, h('span', null, T('Deneyim')),
          h('span', { class: 'mono' }, k.seviye_sonraki ? fmtKisa(k.ep) + ' / ' + fmtKisa(k.seviye_sonraki) + ' EP' : fmtKisa(k.ep) + ' EP')),
          epBar(k.ep, k.seviye_taban, k.seviye_sonraki))),
      h('div', { class: 'ke-paralar' }, para('kredi', k.kredi, T('Kredi')), para('uridyum', k.uridyum, T('Uridyum')), para('onur', k.onur, T('Onur'))),
      h('div', { class: 'ke-metalar' }, meta('map', T('Harita'), k.harita), meta('ship', T('Gemi'), T('{0} gemi', k.gemi_sayisi)),
        meta('drone', T('Dronlar'), k.dron_sayisi), meta('paw', 'P.E.T.', k.pet || '—'), meta('clock', T('Oynama'), fmtDur(k.oynama_sn)),
        meta('calendar', T('Son oynama'), fmtWhen(k.son_oynama || k.son_kayit))),
      k.not_ ? h('div', { class: 'note' }, k.not_) : null,
      h('div', { class: 'row wrap ke-eylem' },
        btn(T('Oyna'), () => { go('oyna'); act(() => api('/api/oyna', {})); }, 'orange', 'play', { disabled: k.kullanimda }),
        btn(T('Karakter editörü'), () => keAc(k), 'primary', 'edit'),
        btn(T('Yedekler ({0})', k.yedek_sayisi), () => backupsModal(k.id), '', 'clock'),
        h('span', { class: 'spacer' }),
        btn('', ev => kayitMenusu(k, ev), 'ghost icon', 'more', { title: T('Diğer') }))));
}

function kayitKarti(k) {
  const f = kfKucuk(k.firma);
  return h('div', { class: 'card ke-kart-k f-' + f },
    h('div', { class: 'ke-kart-ust' },
      h('div', { class: 'ke-kart-gemi' }, gemiGorsel(k.gemi_gorunum, 96, f)),
      h('div', { class: 'grow', style: { minWidth: 0 } },
        h('div', { class: 'row', style: { gap: '6px', minWidth: 0 } }, h('span', { class: 'ke-kart-ad', title: k.ad }, k.ad)),
        h('div', { class: 'ke-pilot small' }, h('b', null, k.pilot), k.klan ? h('span', { class: 'ke-klan' }, '[' + k.klan + ']') : null, badge(k.firma || '?', firmaCls(k.firma))),
        h('div', { class: 'row', style: { gap: '8px', marginTop: '6px' } }, h('span', { class: 'ke-sv-mini' }, T('Sv {0}', k.seviye ?? '?')),
          h('div', { class: 'grow' }, epBar(k.ep, k.seviye_taban, k.seviye_sonraki, 'ince')))),
      btn('', ev => kayitMenusu(k, ev), 'ghost icon sm', 'more', { title: T('Diğer') })),
    h('div', { class: 'row wrap', style: { gap: '6px' } }, ...durumRozetleri(k)),
    h('div', { class: 'ke-kart-paralar' },
      h('span', null, art('kaynak_kredi', 'ke-para-ic sm'), fmtKisa(k.kredi)), h('span', null, art('kaynak_uridyum', 'ke-para-ic sm'), fmtKisa(k.uridyum)),
      h('span', null, icon('ship'), k.gemi_gorunum ? esyaAdi(k.gemi_gorunum) : k.gemi), h('span', null, icon('clock'), fmtWhen(k.son_oynama || k.son_kayit))),
    k.not_ ? h('div', { class: 'note' }, k.not_) : null,
    h('div', { class: 'row wrap', style: { gap: '6px', marginTop: 'auto' } },
      btn(T('Etkin yap'), () => act(() => api('/api/kayitlar/aktif', { id: k.id }), T('Etkin kayıt: {0}', k.ad)).then(() => { renderKayitlar(); poll(); }), 'primary sm', 'check'),
      btn(T('Editör'), () => keAc(k), 'sm', 'edit'),
      btn(T('Yedekler'), () => backupsModal(k.id), 'sm ghost', 'clock')));
}

function silinenler(liste) {
  if (!liste.length) return null;
  const d = h('details', { class: 'card ke-cop', open: KL.cop, ontoggle: e => { KL.cop = e.target.open; } },
    h('summary', null, icon('trash'), T('Silinenler ({0})', liste.length), h('span', { class: 'small muted' }, T('Silinen kayıtlar burada bekler; geri alabilir ya da kalıcı olarak silebilirsin.'))),
    h('table', { class: 'table' }, h('thead', null, h('tr', null, h('th', null, T('Kayıt')), h('th', null, T('Pilot')), h('th', null, T('Silinme')), h('th'))),
      h('tbody', null, liste.map(x => h('tr', null, h('td', null, x.ad), h('td', null, `${x.pilot} · ${lvl(x.seviye)}`), h('td', { class: 'muted' }, fmtWhen(x.silinme)),
        h('td', { class: 'num' }, h('div', { class: 'actions', style: { justifyContent: 'flex-end' } },
          btn(T('Geri al'), () => act(() => api('/api/kayitlar/geri_al', { dosya: x.dosya }), T('Kayıt geri alındı.')).then(renderKayitlar), 'sm', 'undo'),
          btn(T('Kalıcı sil'), async () => {
            if (await confirmBox(T('Kalıcı olarak silinsin mi?'), T('"{0}" kaydı ve yedekleri diskten silinir. Bu geri alınamaz.', x.ad), { ok: T('Kalıcı sil'), danger: true }))
              act(() => api('/api/kayitlar/cop_bosalt', { dosya: x.dosya }), T('Kalıcı olarak silindi.')).then(renderKayitlar);
          }, 'danger sm', 'trash'))))))),
    liste.length > 1 ? h('div', { class: 'row', style: { marginTop: '12px', justifyContent: 'flex-end' } },
      btn(T('Çöp kutusunu boşalt'), async () => {
        if (await confirmBox(T('Çöp kutusu boşaltılsın mı?'), T('{0} kayıt kalıcı olarak silinir.', liste.length), { ok: T('Boşalt'), danger: true }))
          act(() => api('/api/kayitlar/cop_bosalt', {}), T('Çöp kutusu boşaltıldı.')).then(renderKayitlar);
      }, 'danger sm', 'trash')) : null);
  return d;
}

// ================================================================== KARAKTER EDİTÖRÜ
const KE = { slot: null, ad: '', v: null, sekme: 'pilot', gemi: null, konfig: null, mesgul: false, katalog: null, ara: '', cepDolu: false, envTur: 'hepsi', kaynakAra: '' };
const KE_SEKMELER = [
  ['pilot', N('Pilot'), 'user', 'pilotSheet_normal'], ['hangar', N('Hangar'), 'hangar', 'hangar_normal'], ['dronlar', N('Dronlar'), 'drone', null],
  ['pet', 'P.E.T.', 'paw', 'pet_normal'], ['envanter', N('Envanter'), 'box', 'assembly_normal'], ['cephane', N('Cephane'), 'ammo', null],
  ['kaynaklar', N('Kaynaklar'), 'gem', 'refinement_normal'], ['boosterlar', N('Boosterlar'), 'zap', 'booster_normal'], ['bakim', N('Bakım'), 'wrench', 'settings_normal'],
  ['istatistik', N('İstatistik'), 'star', null],
];
const KE_KAT = { hepsi: N('Hepsi'), gemi: N('Gemiler'), tasarim: N('Gemi tasarımları'), lazer: N('Lazerler'), roketatar: N('Roketatarlar'), jenerator: N('Jeneratörler'),
  ekstra: N('Ekstralar ve CPU'), modul: N('Modüller ve çekirdekler'), agir: N('Ağır silahlar'), dron: N('Dronlar ve formasyonlar'), pet: 'P.E.T.', cephane: N('Cephane'),
  booster: N('Boosterlar'), kaynak: N('Kaynaklar'), paket: N('Paketler'), diger: N('Diğer') };
const KE_KAT_IC = { hepsi: 'layers', gemi: 'ship', tasarim: 'wand', lazer: 'zap', roketatar: 'target', jenerator: 'shield', ekstra: 'cpu', modul: 'layers', agir: 'crosshair',
  dron: 'drone', pet: 'paw', cephane: 'ammo', booster: 'zap', kaynak: 'gem', paket: 'gift', diger: 'box' };
const KE_CEP = [['lazer', N('Lazer cephanesi')], ['roket', N('Roketler')], ['roketatar', N('Roketatar cephanesi')], ['mayin', N('Mayınlar')], ['ozel', N('Özel cephane')], ['diger', N('Diğer')]];
const KE_SIFIRLA = [['ipuclari', N('İpuçlarını yeniden göster (kapattıkların ve gösterilenler, etkinlik bildirimleri)')],
  ['arayuz', N('Menü çubuklarının ve pencerelerin yerini varsayılana döndür')], ['oyun_ayarlari', N('Oyunun Ayarlar penceresini (grafik, ses, oynanış) varsayılana döndür')],
  ['aktif_gorevler', N('Alınmış görevleri bırak (bitirilenler kalır)')], ['gecmis', N('Seyir defterini ve hesap geçmişini boşalt')]];
const KE_ALAN = { ad: N('Pilot adı'), firma: N('Firma'), seviye: N('Seviye'), ep: N('Deneyim (EP)'), kredi: N('Kredi'), uridyum: N('Uridyum'), onur: N('Onur'),
  premium: 'Premium', aktif_gemi: N('Etkin gemi'), harita: N('Harita'), can: N('Gemi canı') };

function keAc(k) {
  Object.assign(KE, { slot: k.id, ad: k.ad, v: null, sekme: 'pilot', gemi: null, konfig: null });
  $('#content').scrollTop = 0;
  renderEditor();
}
function keKapat() { KE.slot = null; KE.v = null; renderKayitlar(); }

async function renderEditor() {
  await ogYukle();
  if (!OG.dizin) return keKilit();
  if (!KE.v) {
    const v = await act(() => api('/api/editor?id=' + encodeURIComponent(KE.slot)));
    if (!v) { KE.slot = null; return renderKayitlar(); }
    if (S.page !== 'kayitlar' || !KE.slot) return;
    KE.v = v;
    if (v.atildi) toast(T('Kayıt editörde açıldıktan sonra değişmiş (oyun oynandı ya da yedek geri yüklendi): eski taslak atıldı.'), 'info', 7000);
  }
  keCiz();
}

// oyunun görselleri yok (oyun kurulmadı ya da BepInEx ile hiç açılmadı): editör eşyaları ancak oyunun simgeleri ve adlarıyla
// anlaşılır gösterebilir; kitaplık (kayıt kartları) görselsiz de çalışır
function keKilit() {
  if (S.page !== 'kayitlar' || !KE.slot) return;
  $('#content').replaceChildren(h('div', { class: 'stack ke-editor' },
    h('div', { class: 'card ke-cubuk' }, btn(T('Kayıtlar'), keKapat, 'ghost', 'arrowL'),
      h('div', { class: 'ke-cubuk-ad' }, h('b', null, KE.ad || KE.slot), h('div', { class: 'small muted' }, T('Karakter editörü')))),
    h('div', { class: 'card empty ke-kilit' }, art('dron_kilit'), h('h3', null, T('Oyunun görselleri henüz hazır değil')),
      h('p', null, T('Karakter editörü eşyaları oyunun kendi simgeleri, adları ve açıklamalarıyla gösterir. Oyunu kur ve bir kez OYNA ile aç: görseller ilk açılışta hazırlanır, sonra editör açılır.')),
      h('div', { class: 'row', style: { justifyContent: 'center', gap: '8px' } }, btn(T('İstemci sayfası'), () => go('istemci'), 'primary', 'monitor'),
        btn(T('Yeniden dene'), () => renderEditor(), '', 'refresh')))));
}

// işlemleri taslağa uygula (kayit_editoru.ISLEMLER); başarıda yeni görünüm çizilir -> başarılı mı
async function keUygula(...islemler) {
  if (!KE.v || KE.v.salt_okunur || KE.mesgul) return false;
  KE.mesgul = true; document.body.classList.add('ke-mesgul');
  const v = await act(() => api('/api/editor/uygula', { id: KE.slot, islemler }));
  KE.mesgul = false; document.body.classList.remove('ke-mesgul');
  if (v && KE.slot) { KE.v = v; keCiz(); return true; }
  return false;
}

// Arama kutusu: editör (bütün sekme ve eşya döşemeleri) her tuşta değil yazma durunca yeniden kurulur; imleç yerinde kalır
function keAra(e, ata) {
  ata(e.target.value); clearTimeout(KE.araT);
  KE.araT = setTimeout(() => {
    if (!e.target.isConnected) return;          // bu arada sayfa ya da sekme değişti
    const pos = e.target.selectionStart; keCiz();
    const yeni = $('.ke-ana .oy-ara'); if (yeni) { yeni.focus(); yeni.setSelectionRange(pos, pos); }
  }, 150);
}
function keCiz() {
  if (S.page !== 'kayitlar' || !KE.slot || !KE.v) return;
  const v = KE.v, c = $('#content'), sc = c.scrollTop;
  const sekme = KE_SEKMELER.find(s => s[0] === KE.sekme) || KE_SEKMELER[0];
  c.replaceChildren(h('div', { class: 'stack ke-editor' }, keCubuk(v),
    v.salt_okunur ? h('div', { class: 'alert uyari' }, icon('lock'), h('div', null, h('b', null, T('Kayıt şu an oyunda: yalnız görüntüleniyor.')), ' ',
      T('Değiştirmek için oyunu ve sunucuyu kapat. Oyun açıkken donanım ve alışveriş için oyun içi Hangar ve Mağaza sayfaları var.'))) : null,
    h('div', { class: 'ke-duzen' },
      h('aside', { class: 'ke-yan' }, keKimlik(v), keMenu(v)),
      h('div', { class: 'ke-ana' }, h('div', { class: 'ke-ana-bas' }, keSekmeIkon(sekme, 30), h('div', null, h('h2', null, T(sekme[1])), h('div', { class: 'small muted' }, keSekmeAciklama(sekme[0])))),
        KE_CIZ[sekme[0]](v)))));
  c.scrollTop = sc;
}

// sekme ikonu: panelin görseli (gorsel/ke_<sekme>.webp, Orders.md OP-013: teslim edilenler KE_GORSEL'e), yoksa oyunun menü sprite'ı, o da yoksa çizgi ikon
const KE_GORSEL = new Set(['pilot', 'hangar', 'dronlar', 'pet', 'envanter', 'cephane', 'kaynaklar', 'boosterlar', 'bakim']);
const keSekmeIkon = (s, boy) => KE_GORSEL.has(s[0]) ? h('span', { class: 'ke-sk-ic gorsel' }, art('ke_' + s[0], 'ke-sk-art'))
  : s[3] && OG.dizin?.sprite[s[3]] ? h('span', { class: 'ke-sk-ic oyun' }, sprite(s[3], boy)) : h('span', { class: 'ke-sk-ic' }, icon(s[2]));
const keSekmeAciklama = id => T({ pilot: N('Ad, firma, seviye, deneyim, onur ve cüzdan.'), hangar: N('Gemiler, iki config, tasarımlar ve yuvalar: tıkla, tak ya da çıkar.'),
  dronlar: N('Dronlar, seviyeleri, yükseltmeleri ve donanımları.'), pet: N('P.E.T.: seviye, yakıt, açık yuvalar ve donanım.'),
  envanter: N('Takılı olmayan eşyalar: tak, seviyesini değiştir ya da sil.'), cephane: N('Lazer cephanesi, roketler, mayınlar ve özel cephane.'),
  kaynaklar: N('Kargodaki cevherler ve toplanabilir kaynaklar.'), boosterlar: N('Süreli bonuslar ve kalan süreleri.'),
  bakim: N('Onarım, ana istasyon, tuş atamaları ve durum sıfırlama.'),
  istatistik: N('Rütbe puanının parçaları, öldürülen uzaylılar ve oyuncular, ölümler, kapı süreleri.') }[id]);

function keCubuk(v) {
  const f = v.fark || { sayi: 0 }, ro = v.salt_okunur;
  return h('div', { class: 'card ke-cubuk' },
    btn(T('Kayıtlar'), keKapat, 'ghost', 'arrowL'),
    h('div', { class: 'ke-cubuk-ad' }, h('b', null, KE.ad || KE.slot), h('div', { class: 'small muted' }, T('Karakter editörü'))),
    h('span', { class: 'spacer' }),
    ro ? badge(T('Salt okunur'), 'warn')
      : f.sayi ? h('button', { class: 'ke-degisim var', type: 'button', onclick: keDegisiklikler, title: T('Değişiklikleri gör') }, h('span', { class: 'ke-nabiz' }), T('{0} değişiklik kaydedilmedi', f.sayi), icon('chevR'))
        : h('span', { class: 'ke-degisim' }, icon('check'), T('Kayıtla aynı')),
    ro ? null : btn(T('Vazgeç'), keVazgec, 'ghost', 'undo', { disabled: !f.sayi }),
    ro ? null : btn(T('Kaydet'), keKaydet, 'primary', 'save', { disabled: !f.sayi }));
}

function keKimlik(v) {
  const p = v.pilot, d = v.durum, g = v.gemiler.find(x => x.aktif) || v.gemiler[0], f = kfKucuk(p.firma);
  const sat = (ad, n, etiket) => h('div', { class: 'ke-cz' }, art('kaynak_' + ad, 'ke-para-ic'), h('span', null, etiket), h('b', null, fmtN(n)));
  const deger = (sp, ic, n, m) => h('div', { class: 'ke-dg', title: m != null ? fmtN(n) + ' / ' + fmtN(m) : fmtN(n) }, spr(sp, 20, ic), h('b', null, fmtKisa(n)));
  return h('div', { class: 'card ke-kimlik f-' + f },
    h('div', { class: 'ke-kimlik-sahne' }, h('div', { class: 'ke-halka' }), gemiGorsel(g.gorunum, 170, f)),
    h('div', { class: 'ke-kimlik-bas' }, portre(p.firma, 'ke-portre kucuk', 84),
      h('div', { style: { minWidth: 0 } }, h('div', { class: 'ke-kimlik-ad' }, p.ad), h('div', { class: 'ke-pilot small' }, p.klan ? h('span', { class: 'ke-klan' }, '[' + p.klan + ']') : null,
        badge(KF[p.firma] || '?', firmaCls(KF[p.firma])), p.premium ? badge('Premium', 'orange') : null))),
    h('div', { class: 'ke-sv sm' }, h('div', { class: 'ke-sv-n' }, h('small', null, T('Sv')), h('b', null, p.seviye)),
      h('div', { class: 'grow' }, h('div', { class: 'row between small muted' }, h('span', null, esyaAdi(g.lootId)), h('span', { class: 'mono' }, fmtKisa(p.ep) + ' EP')),
        epBar(p.ep, p.seviye_taban, p.seviye_sonraki))),
    h('div', { class: 'ke-cuzdan' }, sat('kredi', p.kredi, T('Kredi')), sat('uridyum', p.uridyum, T('Uridyum')), sat('onur', p.onur, T('Onur'))),
    h('div', { class: 'ke-degerler' }, deger('hitpoints_100x100', 'heart', d.can, d.can_azami), deger('shield_100x100', 'shield', d.kalkan, d.kalkan_azami),
      deger('speed_100x100', 'gauge', g.deger.hiz), deger('damage_laser_100x100', 'zap', g.deger.hasar)));
}

function keMenu(v) {
  const n = { hangar: v.gemiler.length, dronlar: v.dronlar.length, envanter: v.envanter.filter(e => !keTakili(e)).length, boosterlar: v.boosterlar.length,
    kaynaklar: v.kaynaklar.length + v.cevherler.filter(c => c[2]).length, cephane: v.cephane.filter(c => c[1]).length };
  return h('nav', { class: 'card ke-menu' }, KE_SEKMELER.map(s => h('button', { class: s[0] === KE.sekme ? 'on' : '', type: 'button',
    onclick: () => { if (KE.sekme !== s[0]) { KE.sekme = s[0]; $('#content').scrollTop = 0; keCiz(); } } },
  keSekmeIkon(s, 20), h('span', null, T(s[1])), n[s[0]] ? h('span', { class: 'ke-say' }, fmtN(n[s[0]])) : s[0] === 'pet' && !v.pet ? h('span', { class: 'ke-say yok' }, '—') : null)));
}

// ---- ortak parçalar
const keKart = (baslik, ic, ...govde) => h('div', { class: 'card ke-k' }, baslik ? h('h2', null, icon(ic), baslik) : null, ...govde);
function sayiKutu(deger, ayarla, { min = 0, max = null, cls = '' } = {}) {
  return h('input', { class: 'input num ' + cls, type: 'number', min, max, step: 1, value: deger, disabled: KE.v.salt_okunur,
    onchange: e => { const n = Math.round(+e.target.value); if (!Number.isFinite(n)) { e.target.value = deger; return; }
      const x = Math.max(min, max != null ? Math.min(max, n) : n); if (x !== deger) ayarla(x); else e.target.value = deger; },
    onkeydown: e => { if (e.key === 'Enter') e.target.blur(); } });
}
// kaydırıcı: iz tutamağa kadar dolar (panel.css input[type=range] --p; min ve max value'dan önce verilmeli)
function kaydirici(props, cls = '') {
  const el = h('input', Object.assign({ type: 'range', class: 'ke-aralik ' + cls }, props));
  const dolgu = () => el.style.setProperty('--p', (el.value - el.min) / Math.max(1e-9, el.max - el.min) * 100 + '%');
  el.addEventListener('input', dolgu);
  dolgu();
  return el;
}
// küçük artı/eksi kutusu: [−] n / azami [+]
function adimKutu(n, azami, ayarla, { min = 0 } = {}) {
  const ro = KE.v.salt_okunur;
  return h('div', { class: 'ke-adim' }, h('button', { type: 'button', disabled: ro || n <= min, onclick: () => ayarla(n - 1) }, icon('minus')),
    h('span', null, h('b', null, n), azami != null ? ' / ' + azami : ''), h('button', { type: 'button', disabled: ro || (azami != null && n >= azami), onclick: () => ayarla(n + 1) }, icon('plus')));
}
function keGemi(v) {
  let g = v.gemiler.find(x => x.id === KE.gemi);
  if (!g) { g = v.gemiler.find(x => x.aktif) || v.gemiler[0]; KE.gemi = g.id; }
  if (!g.konfigler[KE.konfig]) KE.konfig = g.aktif_konfig;
  return g;
}
// gemi ve config seçimi (Dronlar ve P.E.T. donanımı da geminin config'inde durur)
function gemiSecici(v, g) {
  return h('div', { class: 'row wrap ke-secici' }, h('span', { class: 'lbl' }, T('Gemi')),
    h('select', { class: 'input', onchange: e => { KE.gemi = e.target.value; KE.konfig = null; keCiz(); } },
      v.gemiler.map(x => h('option', { value: x.id, selected: x.id === g.id }, esyaAdi(x.lootId) + (x.aktif ? ' · ' + T('etkin') : '')))),
    h('div', { class: 'seg' }, Object.keys(g.konfigler).map(c => h('button', { class: c === KE.konfig ? 'on info' : '', onclick: () => { KE.konfig = c; keCiz(); } },
      T('Config {0}', c), c === g.aktif_konfig ? ' •' : ''))));
}
const tasiOp = (id, yon, hd) => ({ islem: 'tasi', yon, hedef: hd.hedef, gemi: KE.gemi, konfig: +KE.konfig, dron: hd.dron || 0, kume: hd.kume || '', esya: id });
const takHedefi = hd => ({ hedef: hd.hedef, gemi: KE.gemi, konfig: +KE.konfig, dron: hd.dron || 0, kume: hd.kume || '' });
const svRozet = e => [e.yukseltme ? h('span', { class: 'ke-rozet-sv' }, '+' + e.yukseltme) : null, e.seviye ? h('span', { class: 'ke-rozet-sv sol' }, T('Sv {0}', e.seviye)) : null];

// eşya simgeli düğme: ipucu örneğin bilgisini (yükseltme, rastgele nitelikler, CPU hakkı) düğmenin _esya'sından okur
function keEsyaDugme(props, e, ...kids) {
  const b = h('button', props, ...kids);
  b._esya = KE.v.haklar[e.lootId] ? Object.assign({}, e, { hak: KE.v.haklar[e.lootId] }) : e;
  return b;
}
const keDuzenlenir = e => !!(e.azami || e.seviye || e.rng || KE.v.haklar[e.lootId]);
function keHucre(e, hd) {
  return keEsyaDugme({ class: 'ke-hucre dolu', type: 'button', onclick: ev => !KE.v.salt_okunur && keEsyaMenu(ev.currentTarget, e, hd) }, e,
    esyaIkon(e.lootId, 44), ...svRozet(e));
}
const keBosHucre = (hd, ic = 'plus', baslik = T('Boş yuva: tak')) => h('button', { class: 'ke-hucre bos', type: 'button', title: baslik, disabled: KE.v.salt_okunur,
  onclick: () => keTakSec(hd) }, icon(ic));
function keYuvaKutusu(ad, c, hd, ek) {
  return h('div', { class: 'ke-yuva' + (c.esyalar.length >= c.kapasite && c.kapasite ? ' dolu' : '') },
    h('div', { class: 'ke-yuva-bas' }, h('b', null, ad), h('span', { class: 'row', style: { gap: '6px' } }, ek, h('span', { class: 'mono' }, c.esyalar.length + ' / ' + c.kapasite))),
    h('div', { class: 'ke-hucreler' }, c.esyalar.map(e => keHucre(e, hd)), Array.from({ length: Math.max(0, c.kapasite - c.esyalar.length) }, () => keBosHucre(hd))));
}
function keEsyaMenu(anchor, e, hd) {
  popMenu(anchor, [
    { label: T('Çıkar (envantere)'), ic: 'download', fn: () => keUygula(tasiOp(e.id, 'cikar', hd)) },
    keDuzenlenir(e) ? { label: T('Düzenle…'), ic: 'edit', fn: () => keDuzenle(e) } : null,
    '-',
    { label: T('Çıkar ve sil'), ic: 'trash', danger: true, fn: () => keUygula(tasiOp(e.id, 'cikar', hd), { islem: 'sil', esyalar: [e.id] }) },
  ].filter(Boolean));
}

// ---- eşya düzenleme: yükseltme seviyesi (Assembly), P.E.T. dişlisinin/protokolünün seviyesi, CPU'nun hakkı ve rastgele nitelikler
// (kararsız modül: nitelikler kesir, gemiler, yeniden çekme hakkı; parçacık silahı: nitelikler yüzde, hak, topun yıldızı; QFC: bağlı
// gemi, seviye, nitelikler yüzde). Oyunun aralığı ipucu olarak yazılır; değer serbest. Hepsi tek işlem listesiyle taslağa.
function keDuzenle(e) {
  const v = KE.v, hv = v.havuzlar[e.lootId], r = e.rng || {}, hak = v.haklar[e.lootId], kesir = hv?.birim === 'kesir';
  const st = { yukseltme: e.yukseltme || 0, seviye: e.seviye, cpu: hak ? hak[0] : null, nitelik: (r.nitelik || []).map(([a, x]) => [a, kesir ? x * 100 : x]),
    gemiler: [...(r.gemiler || [])], gemi: r.gemi || v.gemiler.find(g => g.aktif)?.lootId, qseviye: r.seviye || 1, hak: r.hak ?? hv?.hak, yildiz: r.yildiz || 0 };
  const bolumler = [], gemiSirali = () => [...v.tum_gemiler].sort((a, b) => esyaAdi(a).localeCompare(esyaAdi(b)));
  const baslik = (t, ek) => h('div', { class: 'row between' }, h('div', { class: 'lbl' }, t), ek ? h('span', { class: 'small dim' }, ek) : null);
  if (e.azami) {
    const out = h('b', { class: 'ke-sv-deger' }, '+' + st.yukseltme);
    bolumler.push(h('div', { class: 'ke-dz' }, baslik(T('Yükseltme seviyesi')), h('div', { class: 'ke-sv-sec' }, out,
      h('div', { class: 'grow' }, kaydirici({ min: 0, max: e.azami, value: st.yukseltme, oninput: x => { st.yukseltme = +x.target.value; out.textContent = '+' + st.yukseltme; } }),
        h('div', { class: 'row between small dim' }, h('span', null, '0'), h('span', null, '+' + e.azami))))));
  }
  if (e.seviye) {
    const seg = h('div', { class: 'seg' });
    const ciz = () => seg.replaceChildren(...[1, 2, 3, 4].map(n => h('button', { class: n === st.seviye ? 'on info' : '', onclick: () => { st.seviye = n; ciz(); } }, T('Sv {0}', n))));
    ciz();
    bolumler.push(h('div', { class: 'ke-dz' }, baslik(T('P.E.T. seviyesi')), seg));
  }
  if (hak) bolumler.push(h('div', { class: 'ke-dz' }, baslik(T('Kalan hak'), T('Bir dolum {0} hak; hak bu eşya türünün bütün örnekleri için ortak.', fmtN(hak[1]))),
    h('input', { class: 'input num', type: 'number', min: 0, value: st.cpu, oninput: x => { st.cpu = Math.max(0, Math.round(+x.target.value) || 0); } })));
  if (hv) {
    const satirlar = h('div', { class: 'ke-nit' });
    const nitCiz = () => satirlar.replaceChildren(...[...st.nitelik.map((n, i) => h('div', { class: 'ke-nit-satir' },
      h('select', { class: 'input', onchange: x => { n[0] = x.target.value; nitCiz(); } }, hv.nitelik.map(a => h('option', { value: a, selected: a === n[0],
        disabled: a !== n[0] && st.nitelik.some(m => m[0] === a) }, nitelikAdi(a)))),
      h('label', { class: 'ke-yuzde' }, h('input', { class: 'input num', type: 'number', min: 0, step: 0.1, value: Math.round(n[1] * 100) / 100,
        oninput: x => { n[1] = Math.max(0, +x.target.value || 0); } }), '%'),
      btn('', () => { st.nitelik.splice(i, 1); nitCiz(); }, 'ghost sm icon', 'x', { title: T('Kaldır') }))),
    st.nitelik.length < hv.azami_nitelik ? btn(T('Nitelik ekle'), () => {
      const a = hv.nitelik.find(x => !st.nitelik.some(m => m[0] === x)); if (a) { st.nitelik.push([a, hv.aralik[0]]); nitCiz(); }
    }, 'sm ghost', 'plus') : null].filter(Boolean));
    nitCiz();
    bolumler.push(h('div', { class: 'ke-dz' }, baslik(T('Nitelikler'), T('Oyunda {0}–{1}%, en çok {2} nitelik', fmtN(hv.aralik[0]), fmtN(hv.aralik[1]), hv.azami_nitelik)),
      !e.rng?.nitelik ? h('div', { class: 'small muted' }, T('Nitelikler henüz çekilmedi: Uygula oyundaki gibi çeker, sonra senin değerlerin yazılır.')) : null, satirlar));
    if (hv.tercih) {
      const chips = h('div', { class: 'ke-gemi-chips' });
      const ekle = h('select', { class: 'input', onchange: x => { if (x.target.value && !st.gemiler.includes(x.target.value)) st.gemiler.push(x.target.value); gemiCiz(); } });
      const gemiCiz = () => {
        chips.replaceChildren(...st.gemiler.map((g, i) => h('span', { class: 'chip' }, oyunIkon(g, 22, kfKucuk(v.pilot.firma), 'ship'), esyaAdi(g),
          h('button', { class: 'btn ghost sm icon', type: 'button', onclick: () => { st.gemiler.splice(i, 1); gemiCiz(); } }, icon('x')))));
        ekle.replaceChildren(h('option', { value: '' }, T('Gemi ekle…')), ...gemiSirali().filter(g => !st.gemiler.includes(g))
          .map(g => h('option', { value: g }, (hv.tercih.includes(g) ? '★ ' : '') + esyaAdi(g))));
      };
      gemiCiz();
      bolumler.push(h('div', { class: 'ke-dz' }, baslik(T('Geçtiği gemiler'), T('★ oyunda daha sık çıkanlar')), chips, ekle));
    }
    if (hv.azami_seviye) {
      bolumler.push(h('div', { class: 'grid g2' },
        field(T('Bağlı gemi'), h('select', { class: 'input', onchange: x => { st.gemi = x.target.value; } },
          gemiSirali().map(g => h('option', { value: g, selected: g === st.gemi }, esyaAdi(g))))),
        field(T('Seviye'), h('input', { class: 'input num', type: 'number', min: 1, max: hv.azami_seviye, value: st.qseviye,
          oninput: x => { st.qseviye = Math.max(1, Math.min(hv.azami_seviye, Math.round(+x.target.value) || 1)); } }))));
    }
    if (hv.hak) {
      const k = h('span');
      const c = () => k.replaceChildren(adimKutu(st.hak, hv.hak, n => { st.hak = n; c(); }));
      c();
      bolumler.push(h('div', { class: 'ke-dz satir' }, h('div', { class: 'lbl' }, T('Yeniden çekme hakkı')), k));
    }
    if (hv.yildiz) {
      const yz = h('div', { class: 'ke-yildizlar' });
      const c = () => yz.replaceChildren(...Array.from({ length: hv.yildiz + 1 }, (_, n) => h('button', { type: 'button', class: n && n <= st.yildiz ? 'on' : '',
        title: n ? '★'.repeat(n) : T('Yıldızsız'), onclick: () => { st.yildiz = n; c(); } }, icon(n ? 'star' : 'x'))));
      c();
      bolumler.push(h('div', { class: 'ke-dz satir' }, h('div', { class: 'lbl' }, T('Yıldız')), yz));
    }
  }
  const m = modal({ title: T('Eşyayı düzenle'), sub: esyaAdi(e.lootId), wide: !!hv,
    body: [h('div', { class: 'ke-dz-bas' }, esyaIkon(e.lootId, 56), h('div', { class: 'small muted' }, T('Değişiklikler taslağa yazılır; Kaydet\'e basınca kayda geçer.'))), ...bolumler],
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Uygula'), async () => {
      const ops = [];
      if (e.azami && st.yukseltme !== (e.yukseltme || 0)) ops.push({ islem: 'esya_seviye', esya: e.id, yukseltme: st.yukseltme });
      if (e.seviye && st.seviye !== e.seviye) ops.push({ islem: 'esya_seviye', esya: e.id, seviye: st.seviye });
      if (hak && st.cpu !== hak[0]) ops.push({ islem: 'cpu_hak', lootId: e.lootId, hak: st.cpu });
      if (hv) {
        if (!st.nitelik.length && e.rng?.nitelik) return toast(T('En az bir nitelik gerekli.'), 'err');
        const o = { islem: 'rng', esya: e.id };
        if (st.nitelik.length) o.nitelik = st.nitelik.map(([a, x]) => [a, kesir ? x / 100 : x]);
        if (hv.tercih) { if (!st.gemiler.length) return toast(T('En az bir gemi seç.'), 'err'); o.gemiler = st.gemiler; }
        if (hv.azami_seviye) { o.gemi = st.gemi; o.seviye = st.qseviye; }
        if (hv.hak) o.hak = st.hak;
        if (hv.yildiz) o.yildiz = st.yildiz;
        ops.push(o);
      }
      if (!ops.length) return m.close();
      if (await keUygula(...ops)) { m.close(); toast(T('Eşya güncellendi (taslakta).'), 'ok'); }
    }, 'primary', 'check')] });
}

// envanteri gruplar: aynı lootId ve seviyedekiler tek kutuda (adet); rastgele nitelikliler (modül, top, QFC) tek tek
// item equipped somewhere (its ship and configs); the game lets another config of the same ship use it too
const keTakili = e => !!(e.konfigler && e.konfigler.length);
const keKullanilir = e => !keTakili(e) || (e.gemi === KE.gemi && !e.konfigler.includes(String(KE.konfig)));
function gruplaEsya(liste) {
  const gr = {};
  for (const e of liste) { const k = [e.lootId, e.yukseltme || 0, e.seviye || 0, e.rng ? e.id : ''].join('|'); (gr[k] = gr[k] || []).push(e); }
  return Object.values(gr).sort((a, b) => esyaAdi(a[0].lootId).localeCompare(esyaAdi(b[0].lootId)));
}
// boş yuvaya tak: envanterde uyanlar ya da katalogdan ver ve tak
function keTakSec(hd) {
  const v = KE.v;
  const uygun = v.envanter.filter(e => keKullanilir(e) && (hd.hedef === 'ship' ? e.hedefler.includes('ship') && e.yuva === hd.yuva
    : hd.hedef === 'drone' ? e.hedefler.includes('drone') && (hd.yuva === 'tasarim') === (e.yuva === 'tasarim')
      : e.hedefler.includes('pet') && (hd.yuva === 'heat' ? e.heat : e.pet_yuva === hd.yuva)))
    .sort((a, b) => keTakili(b) - keTakili(a));          // items of the other config first: free copies stay free
  const baslik = hd.hedef === 'drone' ? (hd.yuva === 'tasarim' ? T('Dron tasarımı') : T('Dron donanımı')) : yuvaAdi(hd.yuva);
  const m = modal({ title: T('{0}: eşya tak', baslik), wide: true, body: [
    uygun.length ? h('div', { class: 'ke-secim' }, gruplaEsya(uygun).map(gr => keEsyaDugme({ class: 'ke-secim-esya', type: 'button',
      onclick: () => { m.close(); keUygula(tasiOp(gr[0].id, 'tak', hd)); } }, gr[0], esyaIkon(gr[0].lootId, 56), ...svRozet(gr[0]),
      h('span', { class: 'ad' }, esyaAdi(gr[0].lootId)), gr.length > 1 ? h('span', { class: 'ke-adet' }, '×' + gr.length) : null)))
      : h('div', { class: 'empty' }, icon('box'), h('div', null, T('Envanterde buraya takılabilecek eşya yok.'))),
    h('div', { class: 'ke-secim-alt' }, h('span', { class: 'small muted' }, T('Envanterde yoksa katalogdan ekleyip doğrudan buraya takabilirsin.')),
      btn(T('Katalogdan ekle ve tak'), () => { m.close(); keKatalog({ tak: hd, baslik }); }, 'primary sm', 'plus'))],
  foot: [btn(T('Kapat'), () => m.close(), 'ghost')] });
}

// ---- katalog: eklenebilecek her şey, kategoriler, arama, adet (oyunun ödül yolu)
async function keKatalog(o = {}) {
  if (!KE.katalog) { const r = await act(() => api('/api/editor/katalog')); if (!r) return; KE.katalog = r; }
  let liste = KE.katalog.esyalar;
  if (o.tak) liste = liste.filter(([, , gy, py, dr]) => o.tak.hedef === 'ship' ? gy === o.tak.yuva
    : o.tak.hedef === 'pet' ? (o.tak.yuva === 'heat' ? py === 'lasers' || py === 'generators' : py === o.tak.yuva) : dr && (o.tak.yuva === 'tasarim') === (gy === null && !py));
  if (o.on) liste = liste.filter(([l]) => l.startsWith(o.on));
  const say = {}; for (const [, k] of liste) say[k] = (say[k] || 0) + 1;
  const katlar = ['hepsi', ...KE.katalog.kategoriler.filter(k => say[k])];
  const st = { kat: o.kat && say[o.kat] ? o.kat : katlar.length === 2 ? katlar[1] : 'hepsi', ara: '', sec: null };
  const izgara = h('div', { class: 'ke-kat-izgara' }), solda = h('div', { class: 'ke-kat-liste' }), alt = h('div', { class: 'ke-kat-alt' });
  const ara = h('input', { class: 'input', placeholder: T('Ara: ad ya da lootId…'), oninput: e => { st.ara = e.target.value.trim().toLowerCase(); ciz(); } });
  const ciz = () => {
    solda.replaceChildren(...katlar.map(k => h('button', { class: k === st.kat ? 'on' : '', type: 'button', onclick: () => { st.kat = k; ciz(); } },
      icon(KE_KAT_IC[k] || 'box'), h('span', null, T(KE_KAT[k] || k)), h('small', null, fmtN(k === 'hepsi' ? liste.length : say[k])))));
    const its = liste.filter(([l, k]) => (st.kat === 'hepsi' || k === st.kat) && (!st.ara || l.includes(st.ara) || esyaAdi(l).toLowerCase().includes(st.ara)));
    const gorunen = its.slice(0, 300);
    // seçim yalnız sınıfı değiştirir (ızgara yeniden çizilirse kaydırma başa dönerdi)
    const sec = (l, el) => { st.sec = l; izgara.querySelectorAll('.ke-kat-esya.on').forEach(x => x.classList.remove('on')); el.classList.add('on'); altCiz(); };
    izgara.replaceChildren(...[...gorunen.map(([l]) => h('button', { class: 'ke-kat-esya' + (st.sec === l ? ' on' : ''), type: 'button', title: l,
      onclick: e => sec(l, e.currentTarget), ondblclick: e => { sec(l, e.currentTarget); ekle(); } }, esyaIkon(l, 52), h('span', null, esyaAdi(l)))),
    its.length > gorunen.length ? h('div', { class: 'ke-kat-fazla small muted' }, T('{0} eşyadan ilk {1} tanesi gösteriliyor: aramayı daralt.', fmtN(its.length), gorunen.length)) : null,
    !its.length ? h('div', { class: 'empty' }, T('Eşya yok.')) : null].filter(Boolean));
    izgara.scrollTop = 0;
    altCiz();
  };
  const adet = h('input', { class: 'input num', type: 'number', min: 1, value: 1 });
  const tekil = l => l.startsWith('ship_') || l.startsWith('drone_formation_');
  const altCiz = () => {
    if (!st.sec) return alt.replaceChildren(h('span', { class: 'small muted' }, o.tak ? T('Bir eşya seç: verilir ve doğrudan yuvaya takılır.') : T('Bir eşya seç (çift tıklama hemen ekler).')));
    alt.replaceChildren(...[esyaIkon(st.sec, 48), h('div', { class: 'grow', style: { minWidth: 0 } }, h('b', null, esyaAdi(st.sec)), h('div', { class: 'mono small dim' }, st.sec)),
      tekil(st.sec) ? null : h('label', { class: 'row small' }, T('Adet'), adet), btn(o.tak ? T('Ver ve tak') : T('Ekle'), ekle, 'primary', 'plus')].filter(Boolean));
  };
  async function ekle() {
    if (!st.sec) return;
    const n = tekil(st.sec) ? 1 : Math.max(1, Math.round(+adet.value) || 1), lid = st.sec;
    const ok = await keUygula({ islem: 'ver', esyalar: [[lid, n]], tak: o.tak ? takHedefi(o.tak) : undefined });
    if (ok) { toast(T('Eklendi: {0}', (n > 1 ? fmtN(n) + ' × ' : '') + esyaAdi(lid)), 'ok'); if (o.tak) m.close(); }
  }
  const m = modal({ title: o.baslik ? T('Katalog: {0}', o.baslik) : T('Eşya ekle'), wide: true,
    sub: T('Eşyalar oyunun ödül yoluyla verilir: gemi hangara, ekipman envantere, cephane ve kaynaklar sayaçlara.'),
    body: [h('div', { class: 'ke-katalog' }, solda, h('div', { class: 'ke-kat-sag' }, ara, izgara)), alt], foot: [btn(T('Kapat'), () => m.close(), 'ghost')] });
  m.box.classList.add('ke-katalog-modal');
  ciz();
}

// ================================================================== SEKMELER
function kePilot(v) {
  const p = v.pilot, ro = v.salt_okunur;
  const op = x => keUygula(Object.assign({ islem: 'pilot' }, x));
  const ad = h('input', { class: 'input', value: p.ad, maxlength: 20, disabled: ro, onchange: e => e.target.value.trim() !== p.ad && op({ ad: e.target.value }) });
  const firmalar = h('div', { class: 'radio-cards' }, FIRMS.map(([id, k, n, c, m]) => h('div', { class: 'radio-card' + (id === p.firma ? ' on' : ''), style: { '--c': c },
    onclick: async () => { if (ro || id === p.firma) return;
      if (await confirmBox(T('Firma değişsin mi?'), T('{0} artık {1} pilotu olur; gemi {2} ana istasyonuna taşınır.', p.ad, k, m), { ok: T('Değiştir') })) op({ firma: id }); } },
  art('firma_' + k.toLowerCase(), 'crest'), h('b', null, k), h('span', null, n))));
  const prem = h('input', { type: 'checkbox', checked: p.premium, disabled: ro, onchange: e => op({ premium: e.target.checked }) });
  const svEt = h('b', null, p.seviye);
  const sv = h('div', { class: 'ke-sv-duzen' },
    h('div', { class: 'ke-sv-buyuk' }, h('button', { class: 'btn icon', type: 'button', disabled: ro || p.seviye <= 1, onclick: () => op({ seviye: p.seviye - 1 }) }, icon('minus')),
      h('div', null, h('small', null, T('Seviye')), svEt),
      h('button', { class: 'btn icon', type: 'button', disabled: ro || p.seviye >= p.azami_seviye, onclick: () => op({ seviye: p.seviye + 1 }) }, icon('plus'))),
    h('div', { class: 'grow' }, kaydirici({ min: 1, max: p.azami_seviye, value: p.seviye, disabled: ro,
      oninput: e => { svEt.textContent = e.target.value; }, onchange: e => +e.target.value !== p.seviye && op({ seviye: +e.target.value }) }),
    h('div', { class: 'row between small dim' }, h('span', null, '1'), h('span', null, p.azami_seviye))));
  const para = (key, etiket, n, hizli) => h('div', { class: 'ke-para' }, art('kaynak_' + key, 'ke-para-ic lg'),
    h('div', { class: 'grow' }, h('label', { class: 'lbl' }, etiket), sayiKutu(n, x => op({ [key]: x }), { max: 1e12, cls: 'genis' })),
    h('div', { class: 'ke-hizli' }, hizli.map(x => h('button', { class: 'chip', type: 'button', disabled: ro, onclick: () => op({ [key]: Math.min(1e12, n + x) }) }, '+' + fmtKisa(x)))));
  return h('div', { class: 'stack' },
    h('div', { class: 'grid g2' },
      keKart(T('Kimlik'), 'user', field(T('Pilot adı (oyunda görünür)'), ad),
        h('label', { class: 'row small', style: { marginTop: '12px' } }, h('span', { class: 'switch' }, prem, h('span')), T('Premium üyelik'))),
      keKart(T('Seviye ve onur'), 'star', sv,
        h('div', { class: 'grid g2', style: { marginTop: '12px' } },
          field(T('Deneyim (EP)'), sayiKutu(p.ep, x => op({ ep: x }), { max: 2 ** 53, cls: 'genis' })),
          field(T('Onur'), sayiKutu(p.onur, x => op({ onur: x }), { min: -1e12, max: 1e12, cls: 'genis' }))),
        h('div', { class: 'small dim', style: { marginTop: '8px' } }, p.seviye_sonraki ? T('Sonraki seviye {0} EP\'de.', fmtN(p.seviye_sonraki)) : T('En yüksek seviye')))),
    keKart(T('Firma'), 'globe', h('p', { class: 'desc' }, T('Firma değişince gemi yeni firmanın ana istasyonuna taşınır.')), firmalar),
    keKart(T('Cüzdan'), 'star', h('div', { class: 'grid g2' }, para('kredi', T('Kredi'), p.kredi, [1e6, 1e7, 1e8]), para('uridyum', T('Uridyum'), p.uridyum, [1e4, 1e5, 1e6]))),
    keKart(T('Hesap'), 'info', h('div', { class: 'kv' },
      h('div', null, T('Klan'), h('b', null, p.klan ? '[' + p.klan + ']' : '—')), h('div', null, T('Rütbe'), h('b', null, p.rutbe ?? '—')),
      h('div', null, T('Oynama'), h('b', null, fmtDur(p.oynama_sn))), h('div', null, T('Oluşturma'), h('b', null, fmtWhen(p.olusturma))),
      h('div', null, T('Uridyum bankası'), h('b', null, fmtN(p.banka))), h('div', null, T('Görevler'), h('b', null, T('{0} alınmış · {1} bitmiş', v.gorevler.aktif, v.gorevler.tamam))))));
}

function keHangar(v) {
  const g = keGemi(v), ro = v.salt_okunur, f = kfKucuk(v.pilot.firma), cfg = g.konfigler[KE.konfig];
  const serit = h('div', { class: 'ke-gemiler' }, v.gemiler.map(x => h('button', { class: 'ke-gemi' + (x.id === g.id ? ' on' : ''), type: 'button', title: esyaAdi(x.lootId),
    onclick: () => { KE.gemi = x.id; KE.konfig = null; keCiz(); } }, gemiGorsel(x.gorunum, 62, f), h('span', { class: 'ke-gemi-ad' }, esyaAdi(x.lootId)),
  x.aktif ? h('span', { class: 'ke-etkin' }, T('Etkin')) : null, x.favori ? h('span', { class: 'ke-yildiz' }, icon('star')) : null)),
  ro ? null : h('button', { class: 'ke-gemi ekle', type: 'button', onclick: () => keKatalog({ kat: 'gemi', baslik: T('Gemiler') }) },
    h('span', { class: 'ke-ekle-ic' }, icon('plus')), h('span', { class: 'ke-gemi-ad' }, T('Gemi ekle'))));
  const deger = (sp, ic, ad, n) => h('div', { class: 'ke-gd' }, spr(sp, 26, ic), h('span', null, ad), h('b', null, n == null ? '—' : fmtN(n)));
  const taban = g.lootId.replace(/^ship_/, '');
  const tasarimlar = h('div', { class: 'ke-tasarimlar' }, g.tasarimlar.map(t => h('button', { class: 'ke-tasarim' + (t === g.gorunum ? ' on' : ''), type: 'button',
    title: esyaAdi(t), disabled: ro, onclick: () => t !== g.gorunum && keUygula({ islem: 'tasarim', gemi: g.id, lootId: t }) }, gemiGorsel(t, 46, f))),
  ro ? null : h('button', { class: 'ke-tasarim ekle', type: 'button', title: T('Tasarım ekle'), onclick: () => keKatalog({ kat: 'tasarim', on: 'ship_' + taban + '_design_', baslik: T('{0} tasarımları', esyaAdi(g.lootId)) }) }, icon('plus')));
  const araclar = h('div', { class: 'row wrap', style: { gap: '6px' } },
    g.aktif ? null : btn(T('Etkin gemi yap'), () => keUygula({ islem: 'etkin_gemi', gemi: g.id }), 'sm primary', 'check', { disabled: ro }),
    KE.konfig !== g.aktif_konfig ? btn(T('Bu config\'i kullan'), () => keUygula({ islem: 'konfig', gemi: g.id, konfig: +KE.konfig }), 'sm', 'check', { disabled: ro }) : null,
    btn(g.favori ? T('Favoriden çıkar') : T('Favori yap'), () => keUygula({ islem: 'favori', gemi: g.id, favori: !g.favori }), 'sm', 'star', { disabled: ro }),
    btn(T('Aktar…'), () => keAktar(v, g), 'sm', 'copy', { disabled: ro, title: T('Bu geminin donanımını başka bir gemiye taşır.') }),
    btn(T('Temizle'), async () => await confirmBox(T('Config {0} boşaltılsın mı?', KE.konfig), T('Gemideki, dronlardaki ve P.E.T.\'teki eşyalar envantere iner.'), { ok: T('Temizle'), danger: true })
      && keUygula({ islem: 'temizle', gemi: g.id, konfig: +KE.konfig }), 'sm', 'trash', { disabled: ro }),
    btn(T('Kaldır'), async () => await confirmBox(T('{0} kaldırılsın mı?', esyaAdi(g.lootId)), T('Gemi hangardan çıkar; üstündeki donanım envantere iner. Kaydetmeden önce Vazgeç ile geri alınabilir.'),
      { ok: T('Kaldır'), danger: true }) && keUygula({ islem: 'gemi_sil', gemi: g.id }), 'sm danger', 'trash', { disabled: ro || g.aktif, title: g.aktif ? T('Etkin gemi kaldırılamaz: önce başka bir gemiyi etkin yap.') : '' }));
  return h('div', { class: 'stack' },
    h('div', { class: 'card ke-k' }, serit),
    h('div', { class: 'card ke-gemi-kart f-' + f },
      h('div', { class: 'ke-gemi-sahne' }, gemiGorsel(g.gorunum, 230, f)),
      h('div', { class: 'ke-gemi-bilgi' },
        h('div', { class: 'row wrap', style: { gap: '8px' } }, h('h2', { class: 'ke-gemi-baslik' }, esyaAdi(g.lootId)),
          g.aktif ? badge(T('Etkin gemi'), 'ok') : null, g.favori ? badge(T('Favori'), 'orange') : null),
        g.tasarim ? h('div', { class: 'small muted' }, T('Görünüm: {0}', esyaAdi(g.tasarim))) : null,
        h('div', { class: 'ke-gdler' }, deger('hitpoints_100x100', 'heart', T('Can'), g.deger.can), deger('shield_100x100', 'shield', T('Kalkan'), g.deger.kalkan),
          deger('speed_100x100', 'gauge', T('Hız'), g.deger.hiz), deger('damage_laser_100x100', 'zap', T('Lazer hasarı'), g.deger.hasar), deger(null, 'box', T('Kargo'), g.deger.kargo)),
        g.tasarimlar.length > 1 || !ro ? h('div', null, h('div', { class: 'lbl', style: { marginBottom: '6px' } }, T('Görünüm')), tasarimlar) : null,
        h('div', { class: 'seg' }, Object.keys(g.konfigler).map(c => h('button', { class: c === KE.konfig ? 'on info' : '', onclick: () => { KE.konfig = c; keCiz(); } },
          T('Config {0}', c), c === g.aktif_konfig ? ' •' : ''))),
        araclar)),
    h('div', { class: 'ke-yuvalar' }, g.yuvalar.map(y => keYuvaKutusu(yuvaAdi(y), cfg[y], { hedef: 'ship', yuva: y }))));
}

function keAktar(v, g) {
  let hedef = null;
  const liste = h('div', { class: 'ke-gemiler sar' }, v.gemiler.filter(x => x.id !== g.id).map(x => h('button', { class: 'ke-gemi', type: 'button', onclick: ev => {
    hedef = x.id; liste.querySelectorAll('.ke-gemi').forEach(b => b.classList.toggle('on', b === ev.currentTarget)); } },
  gemiGorsel(x.gorunum, 54, kfKucuk(v.pilot.firma)), h('span', { class: 'ke-gemi-ad' }, esyaAdi(x.lootId)))));
  const m = modal({ title: T('Donanımı aktar'), sub: T('{0} gemisinin iki config\'i, dronları ve P.E.T. donanımı seçtiğin gemiye taşınır.', esyaAdi(g.lootId)), wide: true, body: [liste],
    foot: [btn(T('Vazgeç'), () => m.close(), 'ghost'), btn(T('Aktar'), () => { if (!hedef) return toast(T('Bir gemi seç.'), 'err'); m.close(); keUygula({ islem: 'aktar', gemi: g.id, hedef }); }, 'primary')] });
}

function keDronlar(v) {
  const g = keGemi(v), ro = v.salt_okunur, dcfg = g.dronlar[KE.konfig] || {};
  const yeni = ['drone_flax', 'drone_iris', 'drone_apis', 'drone_zeus'].map(l => h('button', { class: 'ke-dron-ekle', type: 'button', disabled: ro,
    title: T('{0} ekle', esyaAdi(l)), onclick: () => keUygula({ islem: 'ver', esyalar: [[l, 1]] }) }, dronGorsel(l, 1, 40), h('span', null, esyaAdi(l)), icon('plus')));
  const kart = d => {
    const c = dcfg[d.id] || { esyalar: [] }, hd = { hedef: 'drone', dron: d.id }, hdT = { hedef: 'drone', dron: d.id, yuva: 'tasarim' };
    const upEt = h('b', { class: 'ke-sv-deger sm' }, '+' + d.yukseltme);
    return h('div', { class: 'card ke-dron' },
      h('div', { class: 'ke-dron-gorsel' }, dronGorsel(d.lootId, d.seviye, 76)),
      h('div', { class: 'ke-dron-govde' },
        h('div', { class: 'row between' }, h('b', { class: 'ke-dron-ad' }, esyaAdi(d.lootId)),
          btn('', async () => await confirmBox(T('{0} kaldırılsın mı?', esyaAdi(d.lootId)), T('Dron kaldırılır; üstündeki eşyalar envantere iner.'), { ok: T('Kaldır'), danger: true })
            && keUygula({ islem: 'dron_sil', dron: d.id }), 'ghost sm icon', 'trash', { disabled: ro, title: T('Kaldır') })),
        h('div', { class: 'ke-dron-satir' }, h('span', { class: 'lbl' }, T('Seviye')),
          h('div', { class: 'ke-pipler' }, v.dron_seviyeleri.map((puan, i) => h('button', { class: 'ke-pip' + (i < d.seviye ? ' on' : ''), type: 'button', disabled: ro,
            title: T('Seviye {0} ({1} puan)', i + 1, fmtN(puan)), onclick: () => i + 1 !== d.seviye && keUygula({ islem: 'dron', dron: d.id, seviye: i + 1 }) }))),
          h('span', { class: 'small dim' }, T('{0} puan', fmtN(d.puan)))),
        h('div', { class: 'ke-dron-satir' }, h('span', { class: 'lbl' }, T('Yükseltme')),
          kaydirici({ min: 0, max: d.yukseltme_azami, value: d.yukseltme, disabled: ro,
            oninput: e => { upEt.textContent = '+' + e.target.value; }, onchange: e => keUygula({ islem: 'dron', dron: d.id, yukseltme: +e.target.value }) }), upEt),
        h('div', { class: 'ke-hucreler' }, c.esyalar.map(e => keHucre(e, hd)), Array.from({ length: Math.max(0, d.kapasite - c.esyalar.length) }, () => keBosHucre(hd)),
          h('span', { class: 'ke-ayrac' }),
          c.tasarim ? keHucre(c.tasarim, hdT) : keBosHucre(hdT, 'wand', T('Tasarım yuvası')),
          c.gorunum ? keHucre(c.gorunum, hdT) : keBosHucre(hdT, 'wand', T('Görünüm yuvası')))));
  };
  return h('div', { class: 'stack' },
    h('div', { class: 'card ke-k' }, h('div', { class: 'row wrap between', style: { gap: '12px' } }, gemiSecici(v, g),
      h('span', { class: 'pill' }, icon('drone'), T('Dronlar'), ' ', h('b', null, v.dronlar.filter(d => !d.tek).length + ' / ' + v.dron_azami))),
    h('p', { class: 'desc', style: { margin: '10px 0 8px' } }, T('Donanım seçili geminin seçili config\'inde durur (oyundaki gibi her geminin iki config\'i).')),
    ro ? null : h('div', { class: 'ke-dron-ekler' }, yeni)),
    v.dronlar.length ? h('div', { class: 'ke-dronlar' }, v.dronlar.map(kart)) : h('div', { class: 'card empty' }, icon('drone'), h('div', null, T('Dron yok.'))));
}

function kePet(v) {
  const p = v.pet, ro = v.salt_okunur;
  if (!p) return h('div', { class: 'card ke-pet-yok' }, petGorsel(0, 150), h('div', null, h('h3', null, T('Bu pilotun P.E.T.\'i yok')),
    h('p', { class: 'muted' }, T('P.E.T. ver: seviye 0, başlangıç yakıtı ve yuvalarıyla gelir; sonra seviyesini ve yuvalarını buradan ayarlayabilirsin.')),
    btn(T('P.E.T. ver'), () => keUygula({ islem: 'pet', ver: true }), 'primary', 'plus', { disabled: ro })));
  const g = keGemi(v), pc = (g.pet || {})[KE.konfig] || {};
  const op = x => keUygula(Object.assign({ islem: 'pet' }, x));
  const svEt = h('b', null, p.seviye), yEt = h('b', { class: 'mono' }, fmtN(p.yakit));
  const ad = h('input', { class: 'input', value: p.ad || '', maxlength: 24, disabled: ro, onchange: e => e.target.value.trim() && e.target.value.trim() !== p.ad && op({ ad: e.target.value }) });
  return h('div', { class: 'stack' },
    h('div', { class: 'card ke-pet' },
      h('div', { class: 'ke-pet-sahne' }, h('div', { class: 'ke-halka' }), petGorsel(p.seviye, 190)),
      h('div', { class: 'ke-pet-govde stack', style: { gap: '14px' } },
        h('div', { class: 'row wrap', style: { gap: '8px' } }, h('h2', { class: 'ke-gemi-baslik' }, p.ad || 'P.E.T.'), p.yikik ? badge(T('Yıkık'), 'err') : badge(T('Hazır'), 'ok'),
          p.heat ? badge('HEAT ' + p.heat, 'orange') : null),
        field(T('Ad'), ad),
        h('div', { class: 'ke-sv-duzen' },
          h('div', { class: 'ke-sv-buyuk' }, h('button', { class: 'btn icon', type: 'button', disabled: ro || p.seviye <= 0, onclick: () => op({ seviye: p.seviye - 1 }) }, icon('minus')),
            h('div', null, h('small', null, T('Seviye')), svEt),
            h('button', { class: 'btn icon', type: 'button', disabled: ro || p.seviye >= p.azami_seviye, onclick: () => op({ seviye: p.seviye + 1 }) }, icon('plus'))),
          h('div', { class: 'grow' }, kaydirici({ min: 0, max: p.azami_seviye, value: p.seviye, disabled: ro,
            oninput: e => { svEt.textContent = e.target.value; }, onchange: e => +e.target.value !== p.seviye && op({ seviye: +e.target.value }) }),
          h('div', { class: 'row between small dim' }, h('span', null, '0'), h('span', null, T('{0} EP', fmtN(p.ep))), h('span', null, p.azami_seviye)))),
        h('div', null, h('div', { class: 'row between' }, h('span', { class: 'lbl' }, T('Yakıt')), h('span', null, yEt, h('span', { class: 'dim' }, ' / ' + fmtN(p.yakit_azami)))),
          kaydirici({ min: 0, max: p.yakit_azami, step: 100, value: p.yakit, disabled: ro,
            oninput: e => { yEt.textContent = fmtN(+e.target.value); }, onchange: e => op({ yakit: +e.target.value }) }, 'yakit')),
        p.yikik ? btn(T('Onar'), () => op({ onar: true }), 'sm primary', 'wrench', { disabled: ro }) : null)),
    keKart(T('Açık yuvalar'), 'layers', h('p', { class: 'desc' }, T('Oyunda uridyumla açılan yuvalar; seviyenin verdiğinden azı seçilemez.')),
      h('div', { class: 'ke-pet-yuvalar' }, Object.keys(p.yuva_azami).filter(y => y !== 'heat').map(y => h('div', { class: 'ke-pet-yuva' }, h('span', null, yuvaAdi(y)),
        adimKutu(p.yuva[y] || 0, p.yuva_azami[y], n => op({ yuva: { [y]: n } })))))),
    h('div', { class: 'card ke-k' }, h('div', { class: 'row wrap between', style: { gap: '12px' } }, h('h2', { style: { margin: 0 } }, icon('box'), T('Donanım')), gemiSecici(v, g)),
      h('div', { class: 'ke-yuvalar', style: { marginTop: '12px' } }, v.pet_yuvalari.filter(y => pc[y] && (pc[y].kapasite || pc[y].esyalar.length))
        .map(y => keYuvaKutusu(yuvaAdi(y), pc[y], { hedef: 'pet', yuva: y, kume: y === 'heat' ? 'heat' : '' })))));
}

function keEnvanter(v) {
  const g = keGemi(v), ro = v.salt_okunur;
  const bos = v.envanter.filter(e => !keTakili(e));          // inventory tab: only items equipped nowhere (delete, edit)
  const turler = [...new Set(bos.map(e => e.yuva))];
  if (KE.envTur !== 'hepsi' && !turler.includes(KE.envTur)) KE.envTur = 'hepsi';
  const q = KE.ara.toLowerCase();
  const liste = bos.filter(e => (KE.envTur === 'hepsi' || e.yuva === KE.envTur) && (!q || esyaAdi(e.lootId).toLowerCase().includes(q) || e.lootId.includes(q)));
  const izgara = h('div', { class: 'ke-env' }, gruplaEsya(liste).map(gr => {
    const e = gr[0];
    return keEsyaDugme({ class: 'ke-env-esya', type: 'button', onclick: ev => !ro && popMenu(ev.currentTarget, [
      e.hedefler.includes('ship') ? { label: T('Seçili gemiye tak ({0}, config {1})', esyaAdi(g.lootId), KE.konfig), ic: 'download', fn: () => keUygula(tasiOp(e.id, 'tak', { hedef: 'ship' })) } : null,
      keDuzenlenir(e) ? { label: T('Düzenle…'), ic: 'edit', fn: () => keDuzenle(e) } : null,
      '-',
      { label: T('Bir tanesini sil'), ic: 'trash', danger: true, fn: () => keUygula({ islem: 'sil', esyalar: [e.id] }) },
      gr.length > 1 ? { label: T('Hepsini sil ({0})', gr.length), ic: 'trash', danger: true, fn: () => keUygula({ islem: 'sil', esyalar: gr.map(x => x.id) }) } : null,
    ].filter(Boolean)) }, e, esyaIkon(e.lootId, 54), ...svRozet(e), gr.length > 1 ? h('span', { class: 'ke-adet' }, '×' + gr.length) : null, h('span', { class: 'ad' }, esyaAdi(e.lootId)));
  }));
  return h('div', { class: 'stack' },
    h('div', { class: 'card ke-k' }, h('div', { class: 'row wrap', style: { gap: '10px' } },
      h('input', { class: 'input oy-ara', placeholder: T('Ara…'), value: KE.ara, oninput: e => keAra(e, v => { KE.ara = v; }) }),
      h('span', { class: 'spacer' }), ro ? null : btn(T('Eşya ekle'), () => keKatalog({}), 'primary sm', 'plus')),
    turler.length > 1 ? h('div', { class: 'seg', style: { marginTop: '12px', flexWrap: 'wrap' } }, ['hepsi', ...turler].map(t => h('button', { class: t === KE.envTur ? 'on info' : '',
      onclick: () => { KE.envTur = t; keCiz(); } }, t === 'hepsi' ? T('Hepsi') : t === 'tasarim' ? T('Dron tasarımları') : yuvaAdi(t)))) : null),
    liste.length ? h('div', { class: 'card ke-k' }, izgara) : h('div', { class: 'card empty' }, icon('box'), h('div', null, bos.length ? T('Aramaya uyan eşya yok.') : T('Envanter boş: bütün eşyalar takılı.'))));
}

function keCephane(v) {
  const ro = v.salt_okunur, gruplar = {};
  for (const c of v.cephane) if (!KE.cepDolu || c[1]) (gruplar[c[2]] = gruplar[c[2]] || []).push(c);
  const kutu = ([l, n]) => h('div', { class: 'ke-cep' + (n ? '' : ' sifir') }, esyaIkon(l, 44), h('div', { class: 'grow', style: { minWidth: 0 } },
    h('div', { class: 'ke-cep-ad', title: l }, esyaAdi(l)), sayiKutu(n, x => keUygula({ islem: 'cephane', adetler: { [l]: x } }), { max: 1e12, cls: 'genis' })));
  const topluAyarla = async liste => { const s = await promptBox(T('Hepsine aynı adet'), T('Adet'), '100000'); if (s == null) return;
    const n = Math.max(0, Math.round(+s) || 0); keUygula({ islem: 'cephane', adetler: Object.fromEntries(liste.map(c => [c[0], n])) }); };
  const dolu = h('input', { type: 'checkbox', checked: KE.cepDolu, onchange: e => { KE.cepDolu = e.target.checked; keCiz(); } });
  return h('div', { class: 'stack' },
    h('div', { class: 'card ke-k row wrap', style: { gap: '14px' } }, h('label', { class: 'row small' }, h('span', { class: 'switch' }, dolu, h('span')), T('Yalnız elde olanları göster')),
      h('span', { class: 'spacer' }), h('span', { class: 'small muted' }, T('Toplam {0} tür, {1} tanesi elde.', v.cephane.length, v.cephane.filter(c => c[1]).length))),
    ...KE_CEP.filter(([k]) => gruplar[k]).map(([k, ad]) => keKart(null, null,
      h('div', { class: 'row between', style: { marginBottom: '12px' } }, h('h2', { style: { margin: 0 } }, icon('ammo'), T(ad)),
        ro ? null : btn(T('Hepsine aynı adet…'), () => topluAyarla(gruplar[k]), 'sm ghost', 'edit')),
      h('div', { class: 'ke-cepler' }, gruplar[k].map(kutu)))));
}

function keKaynaklar(v) {
  const ro = v.salt_okunur, d = v.durum, q = KE.kaynakAra.toLowerCase();
  const cevher = ([t, l, n]) => h('div', { class: 'ke-cep' + (n ? '' : ' sifir') }, esyaIkon(l, 44), h('div', { class: 'grow', style: { minWidth: 0 } },
    h('div', { class: 'ke-cep-ad' }, esyaAdi(l)), sayiKutu(n, x => keUygula({ islem: 'cevher', adetler: { [t]: x } }), { max: 1e9, cls: 'genis' })));
  const kaynaklar = v.kaynaklar.filter(([l]) => !q || l.includes(q) || esyaAdi(l).toLowerCase().includes(q));
  return h('div', { class: 'stack' },
    keKart(null, null, h('div', { class: 'row between', style: { marginBottom: '12px' } }, h('h2', { style: { margin: 0 } }, icon('gem'), T('Cevherler')),
      h('span', { class: 'pill' }, icon('box'), T('Kargo'), ' ', h('b', null, fmtN(d.kargo) + ' / ' + fmtN(d.kargo_azami)))),
    h('div', { class: 'ke-cepler' }, v.cevherler.map(cevher))),
    keKart(null, null, h('div', { class: 'row wrap between', style: { gap: '10px', marginBottom: '12px' } }, h('h2', { style: { margin: 0 } }, icon('gift'), T('Toplanabilirler ve öbür kaynaklar')),
      h('div', { class: 'row', style: { gap: '8px' } }, h('input', { class: 'input oy-ara', placeholder: T('Ara…'), value: KE.kaynakAra,
        oninput: e => keAra(e, v => { KE.kaynakAra = v; }) }),
      ro ? null : btn(T('Kaynak ekle'), () => keKatalog({ kat: 'kaynak', baslik: T('Kaynaklar') }), 'primary sm', 'plus'))),
    kaynaklar.length ? h('div', { class: 'ke-cepler' }, kaynaklar.map(([l, n]) => h('div', { class: 'ke-cep' }, esyaIkon(l, 44), h('div', { class: 'grow', style: { minWidth: 0 } },
      h('div', { class: 'ke-cep-ad', title: l }, esyaAdi(l)), h('div', { class: 'row', style: { gap: '4px' } }, sayiKutu(n, x => keUygula({ islem: 'kaynak', adetler: { [l]: x } }), { max: 1e12, cls: 'genis' }),
        ro ? null : btn('', () => keUygula({ islem: 'kaynak', adetler: { [l]: 0 } }), 'ghost sm icon', 'x', { title: T('Kaldır') }))))))
      : h('div', { class: 'empty' }, T('Kaynak yok.'))));
}

function keBoosterlar(v) {
  const ro = v.salt_okunur;
  const satir = ([l, sn]) => {
    const saat = h('input', { class: 'input num', type: 'number', min: 0, step: 0.5, value: Math.round(sn / 360) / 10, disabled: ro,
      onchange: e => { const s = Math.max(0, Math.round((+e.target.value || 0) * 3600)); if (s !== sn) keUygula({ islem: 'booster', sureler: { [l]: s } }); } });
    return h('div', { class: 'ke-boost' }, esyaIkon(l, 48), h('div', { class: 'grow', style: { minWidth: 0 } }, h('b', null, esyaAdi(l)), h('div', { class: 'small muted' }, T('{0} kaldı', fmtDur(sn)))),
      h('label', { class: 'row small' }, saat, T('saat')), ro ? null : btn('', () => keUygula({ islem: 'booster', sureler: { [l]: 0 } }), 'ghost sm icon', 'x', { title: T('Kaldır') }));
  };
  return h('div', { class: 'stack' },
    h('div', { class: 'card ke-k row wrap', style: { gap: '10px' } }, h('span', { class: 'small muted grow' }, T('Editörden verilen booster, uzaylıdan düşen gibi yalnız oyun açıkken işler.')),
      ro ? null : btn(T('Booster ekle'), () => keKatalog({ kat: 'booster', baslik: T('Boosterlar') }), 'primary sm', 'plus')),
    v.boosterlar.length ? h('div', { class: 'card ke-k ke-boostlar' }, v.boosterlar.map(satir)) : h('div', { class: 'card empty' }, icon('zap'), h('div', null, T('Etkin booster yok.'))));
}

function keBakim(v) {
  const ro = v.salt_okunur, d = v.durum;
  const satir = (ic, baslik, aciklama, ...dugme) => h('div', { class: 'ke-bakim' }, h('span', { class: 'ke-bakim-ic' }, icon(ic)),
    h('div', { class: 'grow' }, h('b', null, baslik), h('div', { class: 'small muted' }, aciklama)), ...dugme);
  const kutular = Object.fromEntries(KE_SIFIRLA.map(([k]) => [k, h('input', { type: 'checkbox', disabled: ro })]));
  return h('div', { class: 'stack' },
    keKart(T('Gemi ve konum'), 'wrench',
      satir('heart', T('Gemiyi onar'), T('Can {0} / {1}, kalkan {2} / {3}.', fmtN(d.can), fmtN(d.can_azami), fmtN(d.kalkan), fmtN(d.kalkan_azami)),
        btn(T('Onar'), () => keUygula({ islem: 'onar' }), 'sm', 'wrench', { disabled: ro || (d.can >= d.can_azami && d.kalkan >= d.kalkan_azami) })),
      satir('map', T('Ana istasyona taşı'), T('Şu an {0}; firmanın ana haritası {1}. Bir haritada takılı kaldıysan.', d.harita_ad, d.ana_harita),
        btn(T('Taşı'), () => keUygula({ islem: 'ana_us' }), 'sm', 'map', { disabled: ro })),
      satir('sliders', T('Tuş atamaları'), T('Varsayılana döner (oyundaki Ayarlar > Reset sunucuya ulaşmıyor).'),
        btn(T('Varsayılana döndür'), async () => await confirmBox(T('Tuş atamaları varsayılana dönsün mü?'), T('Kendi atadığın tuşlar silinir.'), { ok: T('Döndür') }) && keUygula({ islem: 'tuslar' }),
          'sm', 'undo', { disabled: ro }))),
    keKart(T('Durum sıfırlama'), 'refresh', h('div', { class: 'stack', style: { gap: '8px' } },
      KE_SIFIRLA.map(([k, t]) => h('label', { class: 'row small' }, h('span', { class: 'switch' }, kutular[k], h('span')), T(t)))),
    h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '12px' } }, btn(T('Seçilenleri sıfırla'), () => {
      const b = KE_SIFIRLA.map(([k]) => k).filter(k => kutular[k].checked);
      if (!b.length) return toast(T('Sıfırlanacak bölüm seç.'), 'err');
      keUygula({ islem: 'sifirla', bolumler: b });
    }, 'sm', 'refresh', { disabled: ro }))),
    h('div', { class: 'small dim' }, T('Bütün değişiklikler önce taslakta durur; Kaydet\'e basınca kayda yazılır ve önceki hâli yedeklenir.')));
}

const KE_CIZ = { pilot: kePilot, hangar: keHangar, dronlar: keDronlar, pet: kePet, envanter: keEnvanter, cephane: keCephane, kaynaklar: keKaynaklar,
  boosterlar: keBoosterlar, bakim: keBakim, istatistik: keIstatistik };

// İstatistik (salt okunur; kayit_editoru.istatistik): rütbe puanı, öldürmeler, ölümler, kapılar ve süreleri, modların en iyileri
const KE_PUAN = [['ExperiencePoints', N('Deneyim (EP)')], ['honorPoints', N('Onur')], ['yourLevel', N('Seviye')], ['npcShotPoints', N('Uzaylı puanı')],
  ['playerShotPoints', N('Oyuncu puanı')], ['missionsCompleted', N('Biten görev')], ['daysSinceRegistration', N('Kayıttan beri gün')],
  ['DestroyedByEnemies', N('Düşmana yenilme')], ['DestroyedByRadiationZone', N('Radyasyonda ölüm')], ['friendlyPlayersDestroyed', N('Dost öldürme')]];
const keSure = sn => sn ? (sn >= 3600 ? Math.floor(sn / 3600) + ':' : '') + String(Math.floor(sn / 60) % 60).padStart(sn >= 3600 ? 2 : 1, '0') + ':' + String(sn % 60).padStart(2, '0') : '—';
function keIstatistik(v) {
  const s = v.istatistik || {}, p = s.puan || {};
  const tablo = (basliklar, satirlar, bos) => satirlar.length ? h('div', { class: 'bt-tablo' }, h('table', { class: 'table' },
    h('thead', null, h('tr', null, basliklar.map(x => h('th', null, x)))), h('tbody', null, satirlar)))
    : h('div', { class: 'small muted' }, bos);
  return h('div', { class: 'stack' },
    keKart(T('Rütbe puanı'), 'star', h('div', { class: 'row wrap', style: { gap: '8px', marginBottom: '8px' } },
      badge(T('Rütbe puanı') + ': ' + fmtN(p.rankPoints || 0), 'info'), badge(T('Oyun süresi') + ': ' + fmtDur(s.oynama_sn || 0), '')),
      h('div', { class: 'ke-istat' }, KE_PUAN.map(([k, ad]) => h('div', { class: 'row' }, h('span', { class: 'grow muted' }, T(ad)), h('b', null, fmtN(p[k] || 0)))))),
    keKart(T('Kapılar'), 'globe', tablo([T('Kapı'), T('Tamamlama'), T('En iyi süre'), T('Son süre')],
      (s.kapilar || []).map(k => h('tr', null, h('td', null, k.ad), h('td', { class: 'num' }, fmtN(k.tamam)), h('td', { class: 'num' }, keSure(k.en_iyi)), h('td', { class: 'num' }, keSure(k.son)))),
      T('Henüz tamamlanan kapı yok.')),
      h('div', { class: 'small muted', style: { marginTop: '6px' } }, T('Süre kapının ilk dalgasına girişten tamamlanmaya; bu sürümden önce biten kapıların süresi yok.'))),
    keKart(T('Öldürülen uzaylılar'), 'zap', tablo([T('Uzaylı'), T('Sayı'), T('Puan')],
      (s.npc || []).map(([ad, n, pu]) => h('tr', null, h('td', null, ad), h('td', { class: 'num' }, fmtN(n)), h('td', { class: 'num' }, fmtN(pu * n)))), T('Henüz uzaylı öldürülmedi.'))),
    keKart(T('Oyuncular ve ölümler'), 'shield', h('div', { class: 'ke-istat' },
      [[T('Düşmana yenilme'), (s.olum || {}).dusman], [T('Radyasyonda ölüm'), (s.olum || {}).radyasyon], [T('Öteki ölümler'), (s.olum || {}).diger],
       [T('Dost öldürme'), s.dost], [T('Biten görev'), s.gorev], [T('Eternal Black Light en iyi dalga'), (s.modlar || {}).ebl],
       [T('Frozen Labyrinth avı'), (s.modlar || {}).labirent], [T('Mimesis en iyi sefer'), (s.modlar || {}).mimesis]]
        .map(([ad, n]) => h('div', { class: 'row' }, h('span', { class: 'grow muted' }, ad), h('b', null, fmtN(n || 0))))),
      tablo([T('Gemi'), T('Öldürülen')], (s.oyuncu || []).map(([ad, n]) => h('tr', null, h('td', null, ad), h('td', { class: 'num' }, fmtN(n)))), T('Henüz oyuncu öldürülmedi.'))));
}

// ---- değişiklik özeti, kaydet, vazgeç
function keDegisiklikler() {
  const f = KE.v.fark, ro = KE.v.salt_okunur;
  const deger = (k, x) => x == null ? '—' : k === 'firma' ? KF[x] || x : k === 'aktif_gemi' ? esyaAdi(x) : k === 'premium' ? (x ? T('Açık') : T('Kapalı'))
    : typeof x === 'number' ? fmtN(x) : String(x);
  const bolum = (baslik, ...icerik) => icerik.flat().filter(Boolean).length ? h('div', { class: 'ke-fark' }, h('div', { class: 'lbl' }, baslik), ...icerik) : null;
  const esyalar = (o, cls) => Object.keys(o).length ? h('div', { class: 'ke-fark-esyalar' }, Object.entries(o).map(([l, n]) => h('div', { class: 'ke-fark-esya ' + cls },
    esyaIkon(l, 32), h('span', null, esyaAdi(l)), h('b', null, (cls === 'arti' ? '+' : '−') + fmtN(n))))) : null;
  const m = modal({ title: T('Kaydedilmemiş değişiklikler'), sub: T('Kaydet\'e basınca bunlar kayda yazılır; önceki hâli "Geri yükleme öncesi" yedeği olarak saklanır.'), wide: true,
    body: [
      bolum(T('Değerler'), f.alanlar.map(([k, a, b]) => h('div', { class: 'ke-fark-alan' }, h('span', null, T(KE_ALAN[k] || k)), h('s', null, deger(k, a)), icon('arrowR'), h('b', null, deger(k, b))))),
      bolum(T('Eklenenler'), esyalar(f.eklenen, 'arti')),
      bolum(T('Kaldırılanlar'), esyalar(f.cikan, 'eksi')),
      bolum(T('Adetler'), f.adetler.map(([l, a, b]) => h('div', { class: 'ke-fark-alan' }, h('span', { class: 'row', style: { gap: '8px' } }, esyaIkon(l, 26), esyaAdi(l)), h('s', null, fmtN(a)), icon('arrowR'), h('b', null, fmtN(b))))),
      bolum(T('Boosterlar'), f.boosterlar.length ? h('div', { class: 'small' }, f.boosterlar.map(esyaAdi).join(', ')) : null),
      bolum(T('Seviyeler'), f.seviyeler.length ? h('div', { class: 'small' }, [...new Set(f.seviyeler)].map(l => l === 'pet' ? 'P.E.T.' : esyaAdi(l)).join(', ')) : null),
      bolum(T('Donanım'), f.donanim ? h('div', { class: 'small' }, T('{0} eşyanın yeri değişti (takıldı, çıkarıldı ya da taşındı).', f.donanim)) : null),
      !f.sayi ? h('div', { class: 'empty' }, T('Değişiklik yok.')) : null],
    foot: [btn(T('Kapat'), () => m.close(), 'ghost'), ro ? null : btn(T('Vazgeç'), () => { m.close(); keVazgec(); }, 'danger', 'undo', { disabled: !f.sayi }),
      ro ? null : btn(T('Kaydet'), () => { m.close(); keKaydet(); }, 'primary', 'save', { disabled: !f.sayi })] });
}

async function keKaydet() {
  const r = await act(() => api('/api/editor/kaydet', { id: KE.slot }), T('Kaydedildi. Önceki hâli yedeklendi.'));
  if (r && KE.slot) { KE.v = null; renderEditor(); }
}
async function keVazgec() {
  const n = KE.v?.fark?.sayi || 0;
  if (!await confirmBox(T('Değişiklikler atılsın mı?'), T('Taslaktaki {0} değişiklik silinir; kayıt olduğu gibi kalır.', n), { ok: T('At'), danger: true })) return;
  const r = await act(() => api('/api/editor/vazgec', { id: KE.slot }), T('Değişiklikler atıldı.'));
  if (r && KE.slot) { KE.v = null; renderEditor(); }
}
