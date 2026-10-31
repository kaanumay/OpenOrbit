/* OpenOrbit paneli — Botlar (botlar.py, /api/bot…; belgeler/BOTLAR.md). panel.js'in yardımcılarını kullanır.
   Bot paketi: kadrosu oluşturulurken bir kez üretilen botlar (ad, firma, kişilik) ve ayarları. Paket bir dünyaya atanır; oyuncu o
   dünyada oyuna girince botlar devreye girer. Kipler: Basit (haritalarda dolaşan, harita değiştirmeyen), Normal (gerçek oyuncu gibi
   gelişen, karar veren, sosyal), Gelişmiş (Normal + yerel dil modeli: sohbet ve kararlar).
   Görünümler: kitaplık (paket kartları), sihirbaz (ad ve dünya -> kip -> ayarlar), editör (sekmeler). Değişiklikler kendiliğinden
   kaydedilir. */
'use strict';

Object.assign(IC, {
  bot: '<rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 8V4"/><circle cx="12" cy="3" r="1"/><circle cx="9" cy="13" r="1.3"/><circle cx="15" cy="13" r="1.3"/><path d="M9 17h6"/>',
  brain: '<path d="M9 4a3 3 0 0 0-3 3v.5A3 3 0 0 0 4 10.5 3 3 0 0 0 5 13a3 3 0 0 0 1 5 3 3 0 0 0 6 1V5a2 2 0 0 0-3-1z"/><path d="M15 4a3 3 0 0 1 3 3v.5a3 3 0 0 1 2 3 3 3 0 0 1-1 2.5 3 3 0 0 1-1 5 3 3 0 0 1-6 1"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  yukari: '<path d="M12 19V5"/><path d="M6 11l6-6 6 6"/>',
  asagi: '<path d="M12 5v14"/><path d="M6 13l6 6 6-6"/>',
  list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><circle cx="3.5" cy="6" r="1"/><circle cx="3.5" cy="12" r="1"/><circle cx="3.5" cy="18" r="1"/>',
});

const BT = { liste: null, pid: null, d: null, sekme: 'genel', zam: null, bekleyen: {} };
const BT_KIPLER = {
  basit: { ad: N('Basit'), ic: 'bot', ozet: N('Haritalarda NPC gibi dolaşan, harita değiştirmeyen botlar. Uzaylı keser; düşmansa seni görünce gücüne göre saldırır ya da kaçar.') },
  normal: { ad: N('Normal'), ic: 'users', ozet: N('Gerçek oyuncu gibi: üssünde başlar, görev yapar, kasar, gemi ve lazer alır, PvP yapar, klan kurar, arkadaş edinir, sohbet eder. Her botun kişiliği ve kararları kendine.') },
  gelismis: { ad: N('Gelişmiş'), ic: 'brain', ozet: N('Normal kipin üstüne dil modeli (dahili Qwen3 4B, OpenAI, Claude, Gemini ya da kendi yerel LLM\'in): botlar seninle ve birbirleriyle gerçekten konuşur, ricalarını düşünüp karar verir, yardım çağrılarına gelir.') },
};
const BT_ARKETIP = { kasici: N('PvE kasıcı'), avci: N('PvP avcısı'), sosyal: N('Sosyal'), tuccar: N('Tüccar'), gorevci: N('Görevci'), rahat: N('Rahat'), lider: N('Lider') };
const BT_HEDEF = { kasilma: N('Uzaylı kasıyor'), gorev: N('Görev yapıyor'), pvp: N('PvP avında'), alisveris: N('Alışverişte'), dinlenme: N('Dinleniyor'),
  kesif: N('Keşifte'), grup: N('Grupta'), yardim: N('Yardıma gidiyor'), basit: N('Uzaylı kasıyor'), satis: N('Kargo satıyor'),
  mod: N('Modda'), kapi: N('Galaksi kapısında'), duello: N('Düelloda') };
const BT_IZIN = {
  magaza: [N('Mağaza'), N('Kredi ve uridyumla gemi, lazer, jeneratör ve dron alırlar.')],
  gorev: [N('Görevler'), N('Görev zincirini yaparlar.')],
  pvp: [N('PvP'), N('Botlar birbirleriyle savaşır.')],
  oyuncuya_saldir: [N('Sana saldırma'), N('Düşman firmadaki botlar seni görünce saldırabilir.')],
  sohbet: [N('Sohbet'), N('Global, firma, klan ve grup sohbetine yazar, fısıltına yanıt verirler.')],
  klan: [N('Klana katılma'), N('Kişiliklerine uyan klanlara başvururlar (seninkine de).')],
  klan_kur: [N('Klan kurma'), N('Lider ruhlu, zengin botlar klan kurar ve başvuruları değerlendirir.')],
  arkadas: [N('Arkadaşlık'), N('Arkadaşlık isteğini değerlendirir, birlikte oynadıkları kişilere istek gönderirler.')],
  grup: [N('Grup'), N('Grup davetini kabul edebilir, grupta liderin peşinden giderler.')],
  muzayede: [N('Açık artırma'), N('Açık artırmada teklif verip seninle yarışırlar.')],
  yardim: [N('Yardım çağrıları'), N('Sohbetteki yardım çağrısına (ör. "2-4 yardım") bazı botlar gelir.')],
  kargo: [N('Kargo ve cevher satışı'), N('Uzaylıların kargo kutularını toplarlar; kargo dolunca kendi istasyonlarına (X-1, X-8) dönüp cevheri satarlar.')],
  roket: [N('Roketler'), N("Roket alır ve savaşta atarlar (R-310'dan PLT-3030'a, paralarına göre).")],
  ozel_cephane: [N('Özel cephane'), N("Dayanıklı uzaylılara x2/x3 (MCB-25/50), PvP'de RSB-75 kullanır, uridyumla alırlar. Kapalıysa yalnız LCB-10.")],
  ekstra: [N("CPU'lar ve ekstralar"), N("Onarım robotu, roket CPU'su, kargo CPU'su, HM-7, atlama ve gizlenme CPU'ları, Insta-Shield ve Smart Bomb alıp kullanırlar.")],
  mayin: [N('Mayınlar'), N('Saldırgan botlar mayın alır; senden kaçarken arkalarına mayın bırakırlar.')],
  lab: [N('Arıtma ve laboratuvar'), N('Kargodaki cevheri arıtıp lazerlerine, roketlerine ve kalkanlarına yüklerler (Prometid, Duranium, Promerium, Seprom).')],
  skylab: [N('Skylab'), N('Skylab kurup yükseltirler; ürettiği cevheri gemiye taşıyıp satar ya da laboratuvarda kullanırlar.')],
  teknoloji: [N('Teknoloji eşyaları'), N("Assembly'de teknoloji eşyası üretip (Backup Shields, Battle Repair Bot, Chain Impulse, Energy Leech, Precision Targeter) savaşta kullanırlar.")],
  ganimet: [N('Ganimet kutuları'), N('Haritadaki anahtarlı kutuları anahtarla açarlar; yeşil kutuya değerse uridyumla anahtar alırlar.')],
  assembly: [N('Assembly'), N("Uzaylılardan topladıkları kaynaklarla Assembly'de anahtar, eşya ve cephane üretirler.")],
  kapi: [N('Galaksi Kapıları'), N('Kapı enerjisiyle (ya da uridyumla) üreticide parça toplar, kapıyı kurar ve gücü yetince koşarlar.')],
  etkinlik: [N("Etkinlikler ve pass'ler"), N('Etkinliklere katılırlar (etkinlik uzaylıları, kutuları ve parası), Battle Pass ve Season Pass ilerletip ödül alırlar.')],
  klan_diplomasi: [N('Klan diplomasisi'), N('Bot klan liderleri ittifak, saldırmazlık, savaş ve barış ister ya da gelen isteklere (senin klanınınkiler dahil) yanıt verir. Müttefike saldırmazlar, savaştaki klanın üyesini önceliklerler.')],
  klan_ksi: [N('Klan istasyonları'), N('Bot klanları kasalarıyla Klan Savaş İstasyonu kurar, yükseltir ve savunur; boş asteroitler için seninle ve birbirleriyle yarışırlar. Açıkken sahte rakip klanlar olmaz.')],
  klan_emir: [N('Klan emirleri'), N('Klanındaki botlara klan sohbetinden iş verirsin: "everyone farm", "3 of you go to 4-4", "defend our base", "come help me", "get lf-3", "use goliath", "full shield", "stop". Sadakatlerine göre uyarlar.')],
  kapi_dolgu: [N('Kapı doldurma'), N('Sohbette "need fillers for hades" yazınca seviyesi yeten botlar "inv me" der. Grubundaki botlar Galaksi Kapısına, Hades\'e, LoW\'a ya da QZ\'ye seninle girer ve dalgaları birlikte temizlersiniz.')],
  modlar: [N('Etkinlik ve PvE modları'), N('Etkinlik kapıları, Voyagers, Trinity, Astral, Black Light, Echoes, LoW, Vortex, Mimesis, World Boss, Apotheosis, Labirent; Dispatch ve Galaxy Trek. Gücü yettiği moda girer, ulaştığı yere göre ödül alırlar.')],
  kutu_calma: [N('Kargo çalma'), N('Kaba botlar ara sıra başkasının (seninkini de) kargo kutusunu toplar; aynı firmadansa onur kaybeder.')],
};
const BT_SINIF_AD = s => s === '4-X' ? '4-1…4-4' : s;
const btDoldur = (el, ...k) => el.replaceChildren(...k.flat(Infinity).filter(x => x != null && x !== false));
const btFirma = ['MMO', 'EIC', 'VRU'];
function btArt(name, yedek, cls = 'bt-art') {         // görsel gelmediyse (Orders.md) var olan bir görsel
  const im = art(name, cls);
  im.onerror = () => { im.onerror = null; im.src = 'gorsel/' + yedek + '.webp'; };
  return im;
}
const btDunyaAd = id => (BT.liste?.dunyalar || []).find(w => w.id === id)?.ad || T('Atanmamış');

// ------------------------------------------------------------------ giriş noktası
async function renderBotlar() {
  const r = await act(() => api('/api/botlar')); if (!r || S.page !== 'botlar') return;
  BT.liste = r;
  if (BT.pid && !r.liste.some(p => p.id === BT.pid)) BT.pid = null;
  if (!BT.pid) return btKitaplik();
  btEditor();
}
function btAc(pid, sekme) { BT.pid = pid; BT.sekme = sekme || 'genel'; renderBotlar(); }

function btFirmaCubugu(f) {
  const top = f.reduce((a, b) => a + b, 0) || 1;
  return h('div', { class: 'bt-firmalar', title: btFirma.map((x, i) => x + ' ' + f[i]).join(' · ') },
    f.map((n, i) => h('i', { class: btFirma[i].toLowerCase(), style: { width: (100 * n / top) + '%' } })));
}

// ================================================================== KİTAPLIK
function btKitaplik() {
  const r = BT.liste;
  const kart = p => h('div', { class: 'bt-kart', onclick: e => { if (!e.target.closest('button')) btAc(p.id); } },
    h('div', { class: 'bt-kart-ust k-' + p.kip }, btArt('bot_kip_' + p.kip, 'dron_editor', 'bt-kart-art'),
      h('div', null, h('b', null, p.ad), h('div', { class: 'small muted' }, T(BT_KIPLER[p.kip].ad) + ' · ' + T('{0} bot', p.adet)))),
    h('div', { class: 'bt-kart-govde' },
      h('div', { class: 'row wrap', style: { gap: '6px' } }, p.dunya ? badge([icon('globe'), btDunyaAd(p.dunya)], 'info') : badge(T('Dünyaya atanmadı'), 'warn'),
        p.kip !== 'basit' ? badge(p.gelisim === 'jumpstart' ? 'Jumpstart' : 'Progressive', '') : null),
      btFirmaCubugu(p.firmalar),
      h('div', { class: 'small muted' }, p.seviye_ort != null ? T('Ortalama seviye {0} · en yüksek {1}', p.seviye_ort, p.seviye_enb)
        : T('Henüz oynanmadı: botlar ilk girişte başlar.')),
      p.aciklama ? h('div', { class: 'small ellipsis' }, p.aciklama) : null),
    h('div', { class: 'bt-kart-alt' }, btn(T('Aç'), () => btAc(p.id), 'sm primary', 'edit'),
      btn('', ev => btPaketMenu(ev.currentTarget, p), 'sm ghost icon', 'more', { title: T('Diğer') })));
  btDoldur($('#content'), h('div', { class: 'stack' },
    h('div', { class: 'card bt-giris' }, btArt('bot_giris', 'dron_hosgeldin', 'bt-giris-art'),
      h('div', null, h('h2', null, icon('bot'), T('Botlar')),
        h('p', { class: 'desc' }, T('Bot paketi oluştur, bir dünyaya ata: o dünyada oynarken botlar gerçek oyuncular gibi haritalarda olur. Kadro bir kez üretilir; her girişte aynı botlarla karşılaşırsın, onlar da sen yokken bile ilerler.')),
        h('div', { class: 'row wrap' }, btn(T('Yeni bot paketi'), () => btSihirbaz(), 'primary', 'plus')))),
    h('div', { class: 'bt-izgara' }, r.liste.map(kart), h('button', { class: 'bt-kart yeni', onclick: () => btSihirbaz() }, icon('plus'), h('span', null, T('Yeni bot paketi'))))));
}

function btPaketMenu(anchor, p) {
  popMenu(anchor, [
    { label: T('Aç'), ic: 'edit', fn: () => btAc(p.id) },
    { label: T('Dünyaya ata'), ic: 'globe', fn: () => btAtaMenu(anchor, p) },
    { label: T('Yeniden adlandır'), ic: 'edit', fn: async () => {
      const ad = await promptBox(T('Yeniden adlandır'), T('Paketin adı'), p.ad); if (ad == null) return;
      if (await act(() => api('/api/bot/guncelle', { id: p.id, ad }), T('Kaydedildi.'))) renderBotlar(); } },
    '-',
    { label: T('Sil'), ic: 'trash', danger: true, fn: async () => {
      if (!await confirmBox(T('"{0}" silinsin mi?', p.ad), T('Paket ve botların ilerlemesi silinir (save/botlar/_silinenler klasöründe saklanır).'), { ok: T('Sil'), danger: true })) return;
      const x = await act(() => api('/api/bot/sil', { id: p.id }), T('Bot paketi silindi.')); if (x) { BT.liste = x; if (BT.pid === p.id) BT.pid = null; renderBotlar(); } } },
  ]);
}

function btAtaMenu(anchor, p) {
  const items = BT.liste.dunyalar.map(w => ({ label: w.ad + (p.dunya === w.id ? '  ✓' : ''), ic: p.dunya === w.id ? 'check' : 'globe',
    fn: () => btAta(p, w.id) }));
  items.push('-', { label: T('Atamayı kaldır'), ic: 'x', fn: () => btAta(p, null), disabled: !p.dunya });
  popMenu(anchor, items);
}
async function btAta(p, did) {
  const eski = did && BT.liste.liste.find(x => x.dunya === did && x.id !== p.id);
  if (eski && !await confirmBox(T('Dünyanın paketi değişsin mi?'), T('"{0}" dünyasında şu an "{1}" paketi var; o paket boşa çıkar.', btDunyaAd(did), eski.ad))) return;
  const x = await act(() => api('/api/bot/ata', { id: p.id, dunya: did }), did ? T('"{0}" artık "{1}" dünyasında.', p.ad, btDunyaAd(did)) : T('Atama kaldırıldı.'));
  if (x) { BT.liste = x; renderBotlar(); }
}

// ================================================================== SİHİRBAZ
function btSihirbaz() {
  const r = BT.liste;
  const w = { ad: '', aciklama: '', dunya: (r.dunyalar.find(d => !r.liste.some(p => p.dunya === d.id)) || r.dunyalar[0] || {}).id || null, kip: 'normal',
    gelisim: 'progressive', adet: 80, dil: 'karisik', ad_dili: 'karisik', ad_kaynagi: 'uretim', firma_dagilimi: [1, 1, 1], ozel: '', ayarlar: { jumpstart_saat: 60, basit_guc: 1, basit_dost: 0.5,
      basit_haritalar: { 'X-1': 2, 'X-2': 2, 'X-3': 2, 'X-4': 2, '4-X': 3, 'X-5': 1, 'X-6': 1, 'X-7': 1, 'X-8': 1, '4-5': 2 } } };
  let adim = 0;
  const govde = h('div', { class: 'stack', style: { gap: '14px' } });
  const ayak = h('div', { class: 'row', style: { gap: '8px', justifyContent: 'flex-end', width: '100%' } });
  const m = modal({ title: T('Yeni bot paketi'), wide: true, body: govde, foot: ayak });
  const adimlar = [T('Ad ve dünya'), T('Kip'), T('Ayarlar')];
  function ciz() {
    const ust = h('div', { class: 'bt-adimlar' }, adimlar.map((a, i) => h('span', { class: i === adim ? 'on' : i < adim ? 'tamam' : '' }, h('b', null, i + 1), a)));
    btDoldur(govde, ust, [btAdim1, btAdim2, btAdim3][adim](w, ciz));
    btDoldur(ayak, btn(T('Vazgeç'), () => m.close(), 'ghost'), h('span', { class: 'spacer' }),
      adim ? btn(T('Geri'), () => { adim--; ciz(); }, 'ghost', 'arrowL') : null,
      adim < 2 ? btn(T('İleri'), () => {
        if (adim === 0 && !w.ad.trim()) return toast(T('Bot paketine bir ad ver.'), 'err');
        adim++; ciz();
      }, 'primary') : btn(T('Oluştur'), async () => {
        const x = await act(() => api('/api/bot/olustur', w), T('Bot paketi oluşturuldu: {0}', w.ad.trim()));
        if (!x) return;
        m.close(); BT.liste = x; btAc(x.yeni, w.kip === 'gelismis' ? 'gelismis' : 'kadro');
      }, 'primary', 'check'));
  }
  ciz();
}

function btAdim1(w) {
  const r = BT.liste;
  const ad = h('input', { class: 'input', value: w.ad, placeholder: T('Örn. Kalabalık Sunucu, Avcılar'), maxlength: 40, oninput: e => { w.ad = e.target.value; } });
  const acik = h('textarea', { class: 'input', rows: 2, maxlength: 240, placeholder: T('Bu paket nasıl bir sunucu? (isteğe bağlı)'), oninput: e => { w.aciklama = e.target.value; } }, w.aciklama);
  const dunya = h('select', { class: 'input', onchange: e => { w.dunya = e.target.value || null; } },
    r.dunyalar.map(d => {
      const p = r.liste.find(x => x.dunya === d.id);
      return h('option', { value: d.id, selected: w.dunya === d.id }, d.ad + (p ? ' — ' + T('şu an: {0}', p.ad) : ''));
    }), h('option', { value: '', selected: !w.dunya }, T('Şimdilik atama')));
  return h('div', { class: 'stack', style: { gap: '14px' } }, field(T('Ad'), ad), field(T('Açıklama'), acik),
    field(T('Çalışacağı dünya'), dunya, h('div', { class: 'small muted' }, T('Oyuncu bu dünyada oyuna girince paket devreye girer. Bir dünyada tek paket olur.'))));
}

function btAdim2(w, ciz) {
  const kart = k => h('button', { type: 'button', class: 'bt-kip' + (w.kip === k ? ' on' : ''), onclick: () => { w.kip = k; ciz(); } },
    btArt('bot_kip_' + k, 'dron_editor', 'bt-kip-art'), h('b', null, icon(BT_KIPLER[k].ic), T(BT_KIPLER[k].ad)), h('div', { class: 'small' }, T(BT_KIPLER[k].ozet)));
  return h('div', { class: 'stack', style: { gap: '12px' } }, h('div', { class: 'bt-kipler' }, ['basit', 'normal', 'gelismis'].map(kart)),
    w.kip === 'gelismis' ? btLlmUyari(true) : null);
}

function btLlmUyari(sihirbaz = false) {
  return h('div', { class: 'alert uyari' }, icon('alert'), h('div', null,
    h('b', null, T('Gelişmiş kip bilgisayarını çok zorlayabilir.')),
    h('div', null, T('Botların sohbeti ve kararları bilgisayarında çalışan Qwen3 4B (Q4_K_M) dil modeliyle verilir: yaklaşık 2,5 GB indirme, 4 GB boş bellek ve güçlü bir işlemci ya da ekran kartı ister. Zayıf bilgisayarlarda oyun yavaşlayabilir.')),
    h('div', { style: { marginTop: '6px' } }, T('Bilgisayarın kaldırmıyorsa Gelişmiş sekmesinden OpenAI, Claude, Gemini, DeepSeek gibi bir sağlayıcıyı API anahtarınla ya da kendi yerel LLM sunucunu (Ollama, LM Studio) seçebilirsin; o zaman botlar kendi dillerinde de konuşur.')),
    h('div', { style: { marginTop: '6px' } }, T('Bilgisayarın kaldırmıyorsa Normal kip de çok gelişmiş bir bot deneyimi verir: botlar yine kişiliklerine göre karar verir, gelişir, klan kurar ve kalıplarla sohbet eder.')),
    sihirbaz ? h('div', { class: 'small muted', style: { marginTop: '6px' } }, T('Modeli paket oluşturulduktan sonra Gelişmiş sekmesinden kurup test edeceksin.')) : null));
}

function btSayi(deger, onchange, { min = 0, max = 999, step = 1, cls = 'num' } = {}) {
  return h('input', { class: 'input ' + cls, type: 'number', value: deger, min, max, step, onchange: e => {
    let v = Number(e.target.value); if (!isFinite(v)) v = min; v = Math.max(min, Math.min(max, v)); e.target.value = v; onchange(v); } });
}
function btKaydirac(deger, onchange, { min, max, step, fmt = v => v }) {
  const etiket = h('span', { class: 'bt-deger' }, fmt(deger));
  // dolgu (panel.css: --p) değerle birlikte: parıltı tutamağı izler
  const boya = el => el.style.setProperty('--p', (100 * (Number(el.value) - min) / ((max - min) || 1)) + '%');
  const r = h('input', { type: 'range', min, max, step, value: deger, class: 'bt-range',
    oninput: e => { etiket.textContent = fmt(Number(e.target.value)); boya(e.target); }, onchange: e => onchange(Number(e.target.value)) });
  boya(r);
  return h('div', { class: 'row', style: { gap: '10px' } }, r, etiket);
}
function btSeg(secenekler, deger, onchange) {
  // seçim hemen görünür (yeniden çizim beklemez: Kadro'da yalnız Uygula'dan sonra görünüyordu)
  const el = h('div', { class: 'seg' }, secenekler.map(([v, ad]) => h('button', { type: 'button', class: v === deger ? 'on' : '', onclick: e => {
    el.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === e.currentTarget)); onchange(v);
  } }, ad)));
  return el;
}
// adların ve sohbetin dili (bot/diller/<kod>.json); dil adları kendi dillerinde
const BT_DILLER = [['tr', 'Türkçe'], ['en', 'English'], ['de', 'Deutsch'], ['es', 'Español'], ['fr', 'Français'], ['pl', 'Polski'],
  ['pt', 'Português'], ['ru', 'Русский']];
function btDilSec(deger, onchange, karisikAd, kilitli) {
  return h('select', { class: 'input bt-dil', disabled: !!kilitli, onchange: e => onchange(e.target.value) },
    [['karisik', karisikAd]].concat(BT_DILLER).map(([v, ad]) => h('option', { value: v, selected: v === deger }, ad)));
}
// adların kaynağı (panel/botlar.AD_KAYNAKLARI): üretici gerçek sunucuların üslubuyla ya da dostats.info'daki gerçek oyuncular
const BT_AD_KAYNAGI_ACIKLAMA = N("Üretilen adlar gerçek sunuculardaki gibi süslüdür (-»Λd«-, ツ, ᵀᴹ). DOStats seçilirse adlar ve klan etiketleri dostats.info'daki gerçek oyunculardan alınır (internet gerekir; yeni eklenen botlara ve baştan üretime).");
function btAdKaynagi(deger, onchange) {
  return h('select', { class: 'input', onchange: e => onchange(e.target.value) },
    [['uretim', T('Üretilen')], ['dostats', T('DOStats (gerçek oyuncular)')]].map(([v, ad]) => h('option', { value: v, selected: v === deger }, ad)));
}
// dahili dil modeli yalnız İngilizce; başka bir sağlayıcı seçiliyse Gelişmiş kipte de dil serbest (bot/llm_saglayici.py)
const btDilKilitli = kip => kip === 'gelismis' && !BT.liste?.llm_cok_dilli;
function btSohbetDili(kip, deger, onchange) {
  return btDilKilitli(kip) ? btDilSec('en', () => {}, T('Her bot adının dilinde'), true) : btDilSec(deger, onchange, T('Her bot adının dilinde'));
}
function btDagilim(f, onchange) {
  return h('div', { class: 'row bt-dagilim', style: { gap: '8px' } }, btFirma.map((x, i) => h('label', { class: 'row', style: { gap: '4px' } },
    badge(x, x.toLowerCase()), btSayi(f[i], v => { f[i] = v; onchange(f); }, { min: 0, max: 100 }))));
}

function btAdim3(w, ciz) {
  if (w.kip === 'basit') return btBasitAyar(w.ayarlar, () => ciz(), true);
  return h('div', { class: 'stack', style: { gap: '14px' } },
    field(T('Toplam bot'), btKaydirac(w.adet, v => { w.adet = v; }, { min: 5, max: 3000, step: 5 }),
      h('div', { class: 'small muted' }, T('Aynı anda hepsi çevrimiçi olmaz: her botun kendi oyun saatleri var. Yüzlerce bot sorun değil; haritanda gemi olarak görünenler sınırlı.'))),
    field(T('Firma dağılımı (oran)'), btDagilim(w.firma_dagilimi, f => { w.firma_dagilimi = f; })),
    field(T('Gelişim'), btSeg([['progressive', 'Progressive'], ['jumpstart', 'Jumpstart']], w.gelisim, v => { w.gelisim = v; ciz(); }),
      h('div', { class: 'small muted' }, w.gelisim === 'progressive'
        ? T('Herkes oyunun başında olduğu gibi 1. seviyede, Phoenix ile kendi üssünde başlar ve gerçek oyuncu gibi gelişir.')
        : T('Kadro gerçekçi bir dağılımla başlar: çok acemi, çok orta seviye, az güçlü oyuncu. Donanımları, paraları ve seviyeleri tutarlı.'))),
    w.gelisim === 'jumpstart' ? field(T('Ortalama oyun süresi (saat)'), btKaydirac(w.ayarlar.jumpstart_saat, v => { w.ayarlar.jumpstart_saat = v; }, { min: 5, max: 500, step: 5 })) : null,
    field(T('Adların dili'), btDilSec(w.ad_dili, v => { w.ad_dili = v; }, T('Karışık')),
      h('div', { class: 'small muted' }, T('Botların kullanıcı adları bu dilin oyuncularına benzer.'))),
    field(T('Ad kaynağı'), btAdKaynagi(w.ad_kaynagi, v => { w.ad_kaynagi = v; }),
      h('div', { class: 'small muted' }, T(BT_AD_KAYNAGI_ACIKLAMA))),
    field(T('Sohbet dili'), btSohbetDili(w.kip, w.dil, v => { w.dil = v; }),
      h('div', { class: 'small muted' }, btDilKilitli(w.kip) ? T('Gelişmiş kipte botlar yalnız İngilizce konuşur (dil modeli öteki dillerde zayıf).')
        : T('Botların sohbette kullandığı dil. "Her bot adının dilinde" seçilirse adı Almanca olan Almanca konuşur.'))),
    field(T('Kendi botların (isteğe bağlı)'), btOzelAlan(w.ozel, v => { w.ozel = v; })));
}

// kullanıcının kendi botları (panel/botlar.ozel_cozumle): satır başına "ad, firma, davranış, dil"; ad dışındakiler isteğe bağlı
function btOzelAlan(deger, onchange) {
  return h('div', { class: 'stack', style: { gap: '6px' } },
    h('textarea', { class: 'input bt-ozel', rows: 5, spellcheck: false, placeholder: 'Kaan\nStarHunter, VRU\nOldMiner, MMO, kasici, tr\nRedBaron, EIC, avci', oninput: e => onchange(e.target.value) }, deger || ''),
    h('div', { class: 'small muted' }, T('Satır başına bir bot: ad, sonra isteğe bağlı firma (MMO, EIC, VRU), davranış ({0}) ve sohbet dili ({1}). Verilmeyenler ve kalan botlar her zamanki gibi üretilir.',
      Object.keys(BT_ARKETIP).join(', '), BT_DILLER.map(d => d[0]).join(', '))));
}

function btBasitAyar(a, ciz, sihirbaz = false, kaydet = null) {
  const top = () => Object.entries(a.basit_haritalar).reduce((s, [k, v]) => s + v * (k === '4-X' ? 4 : ['4-5'].includes(k) ? 1 : 3), 0);
  const toplam = h('b', null, top());
  const ust = h('div', { class: 'bt-siniflar' }, (BT.liste?.siniflar || Object.keys(a.basit_haritalar)).map(s => h('label', { class: 'bt-sinif' },
    h('span', null, BT_SINIF_AD(s)), btSayi(a.basit_haritalar[s] ?? 0, v => { a.basit_haritalar[s] = v; toplam.textContent = top(); kaydet && kaydet(); }, { min: 0, max: 20 }))));
  return h('div', { class: 'stack', style: { gap: '14px' } },
    field(T('Harita başına bot'), ust, h('div', { class: 'small muted' }, T('Firma haritalarında her firmanın haritasına ayrı ayrı (X-3 = 1-3, 2-3, 3-3), ortak haritalara (4-1…4-5) bir kez. Toplam: '), toplam)),
    field(T('Güç oranı'), btKaydirac(a.basit_guc, v => { a.basit_guc = v; kaydet && kaydet(); }, { min: 0.3, max: 3, step: 0.1, fmt: v => '×' + v.toFixed(1) }),
      h('div', { class: 'small muted' }, T('Haritanın tipik oyuncusunun donanımına göre: 1 aynı, 2 iki kat güçlü, 0,5 zayıf.'))),
    field(T('Dost bot payı'), btKaydirac(a.basit_dost, v => { a.basit_dost = v; kaydet && kaydet(); }, { min: 0, max: 1, step: 0.05, fmt: v => '%' + Math.round(v * 100) }),
      h('div', { class: 'small muted' }, T('Firma haritasındaki botların ne kadarı haritanın firmasından (geri kalanı düşman).'))));
}

// ================================================================== EDİTÖR
const BT_SEKMELER = [
  ['genel', N('Genel'), 'sliders'], ['kadro', N('Kadro'), 'users'], ['davranis', N('Davranış'), 'target'], ['erisim', N('Erişimler'), 'shield'],
  ['sohbet', N('Sohbet'), 'chat'], ['klanlar', N('Klanlar'), 'star'], ['basit', N('Basit kip'), 'bot'], ['gelismis', N('Gelişmiş kip'), 'brain'],
];

async function btEditor() {
  const [d] = await Promise.all([act(() => api('/api/bot?id=' + encodeURIComponent(BT.pid))), ogYukle()]);   // oyunun görselleri: gemi, rütbe
  if (!d || S.page !== 'botlar') return;
  BT.d = d;
  const sekmeler = BT_SEKMELER.filter(([k]) => (k !== 'basit' || d.kip === 'basit') && (k !== 'gelismis' || d.kip === 'gelismis')
    && (d.kip !== 'basit' || !['davranis', 'sohbet'].includes(k)));
  if (!sekmeler.some(([k]) => k === BT.sekme)) BT.sekme = 'genel';
  btDoldur($('#content'), h('div', { class: 'stack' },
    h('div', { class: 'card bt-cubuk' }, btn('', () => { BT.pid = null; renderBotlar(); }, 'ghost icon', 'arrowL', { title: T('Bot paketleri') }),
      btArt('bot_kip_' + d.kip, 'dron_editor', 'bt-cubuk-art'),
      h('div', { class: 'bt-cubuk-ad' }, h('div', { class: 'row', style: { gap: '8px' } }, h('b', null, d.ad), badge(T(BT_KIPLER[d.kip].ad), 'orange'),
        d.dunya ? badge([icon('globe'), btDunyaAd(d.dunya)], 'info') : badge(T('Dünyaya atanmadı'), 'warn')),
        h('div', { class: 'muted small ellipsis' }, T('{0} bot', d.adet) + (d.seviye_ort != null ? ' · ' + T('ortalama seviye {0}', d.seviye_ort) : ''))),
      h('span', { class: 'spacer' }), h('span', { class: 'de-kayit', id: 'bt-kayit' }),
      btn(T('Dünyaya ata'), ev => btAtaMenu(ev.currentTarget, d), 'sm', 'globe'),
      btn('', ev => btPaketMenu(ev.currentTarget, d), 'sm ghost icon', 'more', { title: T('Diğer') })),
    d.sunucu_bu_pakette ? h('div', { class: 'alert ' + (d.yeniden_gerekli ? 'uyari' : 'bilgi') }, icon(d.yeniden_gerekli ? 'alert' : 'info'),
      h('div', null, d.yeniden_gerekli ? T('Paket oyun açıldıktan sonra değişti: değişiklikler sunucu yeniden başlayınca geçerli olur.')
        : T('Bu paket şu an oyunda çalışıyor. Kadro listesi sunucunun dakikalık kaydından.')),
      d.yeniden_gerekli ? btn(T('Sunucuyu yeniden başlat'), () => act(() => api('/api/bot/sunucu_yeniden', {}), T('Sunucu yeniden başlatılıyor.')).then(() => setTimeout(btEditor, 1500)), 'sm orange', 'refresh') : null) : null,
    h('div', { class: 'seg bt-sekmeler' }, sekmeler.map(([k, ad, ic]) => h('button', { type: 'button', class: BT.sekme === k ? 'on' : '',
      onclick: () => { BT.sekme = k; btEditor(); } }, icon(ic), T(ad)))),
    h('div', { id: 'bt-alan' }, ({ genel: btGenel, kadro: btKadro, davranis: btDavranis, erisim: btErisim, sohbet: btSohbet, klanlar: btKlanlar, basit: btBasit, gelismis: btGelismis })[BT.sekme](d))));
}

function btKayit(durum) {
  const el = $('#bt-kayit'); if (!el) return;
  el.className = 'de-kayit ' + durum;
  btDoldur(el, ...(durum === 'kaydediliyor' ? [h('span', { class: 'spin' }), T('Kaydediliyor…')] : durum === 'kaydedildi' ? [icon('check'), T('Kaydedildi')] : []));
}
// değişiklik: 450 ms bekleyip tek istekte (ayarlar birleştirilir)
function btYama(alanlar) {
  for (const [k, v] of Object.entries(alanlar)) {
    if (k === 'ayarlar') BT.bekleyen.ayarlar = Object.assign(BT.bekleyen.ayarlar || {}, v);
    else BT.bekleyen[k] = v;
  }
  btKayit('kaydediliyor');
  clearTimeout(BT.zam);
  BT.zam = setTimeout(async () => {
    const govde = Object.assign({ id: BT.pid }, BT.bekleyen); BT.bekleyen = {};
    const x = await act(() => api('/api/bot/guncelle', govde));
    if (!x) return btKayit('');
    const kip = BT.d.kip;
    BT.d = x; btKayit('kaydedildi');
    if (govde.kip && govde.kip !== kip || govde.ad) btEditor();
  }, 450);
}
const btA = (k, v) => btYama({ ayarlar: { [k]: v } });

function btSatir(ad, aciklama, ctl) {
  return h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, ad), aciklama ? h('div', { class: 'help' }, aciklama) : null), h('div', { class: 'ctl' }, ctl));
}
function btAnahtar(deger, onchange) {
  return h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: !!deger, onchange: e => onchange(e.target.checked) }), h('span'));
}

// ------------------------------------------------------------------ Genel
function btGenel(d) {
  const a = d.ayarlar;
  const ad = h('input', { class: 'input', value: d.ad, maxlength: 40, onchange: e => btYama({ ad: e.target.value }) });
  const acik = h('input', { class: 'input', value: d.aciklama || '', maxlength: 240, placeholder: T('Açıklama yok.'), onchange: e => btYama({ aciklama: e.target.value }) });
  const kipSec = async v => {
    if (v === d.kip) return;
    if (v === 'gelismis' && !await confirmBox(T('Gelişmiş kipe geçilsin mi?'), btLlmUyari(), { ok: T('Gelişmiş kipe geç') })) return;
    if ((v === 'basit') !== (d.kip === 'basit') && !await confirmBox(T('Kip değişsin mi?'),
      T('Basit kipte kadro haritalara dağıtılır ve sayısı harita ayarlarından gelir; Normal ve Gelişmiş kipte botlar kendi başına gelişir. İlerleme korunur.'))) return;
    btYama({ kip: v });
  };
  const fg = a.firma_guc || [1, 1, 1];
  return h('div', { class: 'stack' },
    h('div', { class: 'card' }, h('h2', null, icon('edit'), T('Paket')),
      btSatir(T('Ad'), null, ad), btSatir(T('Açıklama'), null, acik),
      btSatir(T('Kip'), T(BT_KIPLER[d.kip].ozet), btSeg(['basit', 'normal', 'gelismis'].map(k => [k, T(BT_KIPLER[k].ad)]), d.kip, kipSec)),
      d.kip !== 'basit' ? btSatir(T('Gelişim'), d.gelisim === 'jumpstart' ? T('Kadro gerçekçi bir dağılımla başlar (ilk açılışta).') : T('Herkes 1. seviyede, kendi üssünde başlar.'),
        btSeg([['progressive', 'Progressive'], ['jumpstart', 'Jumpstart']], d.gelisim, v => btYama({ gelisim: v }))) : null,
      d.kip !== 'basit' && d.gelisim === 'jumpstart' ? btSatir(T('Ortalama oyun süresi (saat)'), T('Jumpstart dağılımının ortası: birkaç bot bunun katlarıyla, çoğu altında başlar.'),
        btSayi(a.jumpstart_saat, v => btA('jumpstart_saat', v), { min: 1, max: 2000 })) : null),
    d.kip !== 'basit' ? h('div', { class: 'card' }, h('h2', null, icon('clock'), T('Zaman ve gelişim')),
      btSatir(T('İlerleme hızı'), T('Kazançların çarpanı: 1 gerçek oyuncu temposu.'), btKaydirac(a.hiz, v => btA('hiz', v), { min: 0.1, max: 10, step: 0.1, fmt: v => '×' + v.toFixed(1) })),
      btSatir(T('Çevrimiçi olma eğilimi'), T('Botların oyun saatlerine göre çevrimiçi olma isteği; yüksekse aynı anda daha çok bot.'),
        btKaydirac(a.cevrimici_oran, v => btA('cevrimici_oran', v), { min: 0.05, max: 2, step: 0.05, fmt: v => '%' + Math.round(v * 100) })),
      btSatir(T('Aynı anda en çok çevrimiçi'), T('0: sınırsız.'), btSayi(a.en_cok_cevrimici, v => btA('en_cok_cevrimici', v), { min: 0, max: 3000 })),
      btSatir(T('Sen yokken ilerleme (saat)'), T('Oyuna dönünce geçen sürenin en çok bu kadarı benzetilir. 0: botlar yalnız sen oynarken ilerler.'),
        btSayi(a.telafi_saat, v => btA('telafi_saat', v), { min: 0, max: 48 })),
      d.gelisim !== 'jumpstart' ? btSatir(T('Yeni pilot kaydı (saniye)'), T('Progressive: her firmaya ortalama bu kadar saniyede bir yeni pilot kayıt olup oyuna başlar (yeni açılmış bir sunucu gibi; hepsi aynı anda doğmaz). 0: hepsi baştan kayıtlı.'),
        btSayi(a.kayit_sn ?? 15, v => btA('kayit_sn', v), { min: 0, max: 300 })) : null,
      btSatir(T('Firmaların gücü'), T('Firmanın botlarının gelişim çarpanı (1 eşit).'), h('div', { class: 'row', style: { gap: '8px' } }, btFirma.map((x, i) =>
        h('label', { class: 'row', style: { gap: '4px' } }, badge(x, x.toLowerCase()), btSayi(fg[i], v => { fg[i] = v; btA('firma_guc', fg); }, { min: 0.2, max: 5, step: 0.1 })))))) : null,
    btOyunAyariKart(d),
    h('div', { class: 'card' }, h('h2', null, icon('trash'), T('İlerleme')),
      btSatir(T('İlerlemeyi sıfırla'), T('Botların seviyesi, parası, donanımı, klanları ve ilişkileri silinir; adlar ve kişilikler kalır.'),
        btn(T('Sıfırla'), async () => {
          if (!await confirmBox(T('İlerleme sıfırlansın mı?'), T('Botlar baştan başlar (Jumpstart\'ta yeniden dağıtılır).'), { ok: T('Sıfırla'), danger: true })) return;
          const x = await act(() => api('/api/bot/sifirla', { id: d.id }), T('İlerleme sıfırlandı.')); if (x) { BT.d = x; btEditor(); }
        }, 'sm danger', 'trash'))));
}

// ------------------------------------------------------------------ Kadro
function btKadro(d) {
  const ark = {};
  d.kadro.forEach(b => { ark[b.arketip] = (ark[b.arketip] || 0) + 1; });
  const f = d.firma_dagilimi.slice();
  let adet = d.adet, dil = d.dil || 'karisik', adDili = d.ad_dili || dil, adKaynagi = d.ad_kaynagi || 'uretim', ozel = '';
  const kontrol = d.kip === 'basit' ? h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Basit kipte bot sayısı Basit kip sekmesindeki harita sayılarından gelir.')))
    : h('div', { class: 'stack', style: { gap: '10px' } },
      btSatir(T('Bot sayısı'), T('Artırınca yeni botlar eklenir, azaltınca sondakiler çıkar; var olanlar değişmez.'), btSayi(adet, v => { adet = v; }, { min: 1, max: 3000 })),
      btSatir(T('Firma dağılımı (oran)'), T('Yeni eklenen botlara ve baştan üretime uygulanır.'), btDagilim(f, x => { f.splice(0, 3, ...x); })),
      btSatir(T('Adların dili'), T('Yeni eklenen botlara ve baştan üretime uygulanır; var olan botların adı değişmez.'),
        btDilSec(adDili, v => { adDili = v; }, T('Karışık'))),
      btSatir(T('Ad kaynağı'), T(BT_AD_KAYNAGI_ACIKLAMA), btAdKaynagi(adKaynagi, v => { adKaynagi = v; })),
      btSatir(T('Sohbet dili'), btDilKilitli(d.kip) ? T('Gelişmiş kipte botlar yalnız İngilizce konuşur (dil modeli öteki dillerde zayıf).')
        : T('Uygula ile bütün botlar bu dilde konuşur.'), btSohbetDili(d.kip, dil, v => { dil = v; })),
      field(T('Kendi botların'), btOzelAlan('', v => { ozel = v; }), h('div', { class: 'small muted' }, T('Uygula: kadroda olmayan adlar yeni bot olarak eklenir. Baştan üret: kadronun başında olurlar.'))),
      h('div', { class: 'row wrap', style: { justifyContent: 'flex-end' } },
        btn(T('Uygula'), async () => { const x = await act(() => api('/api/bot/kadro', { id: d.id, adet, firma_dagilimi: f, dil, ad_dili: adDili, ad_kaynagi: adKaynagi, ozel }), T('Kadro güncellendi.')); if (x) { BT.d = x; btEditor(); } }, 'sm primary', 'check'),
        btn(T('Baştan üret'), async () => {
          if (!await confirmBox(T('Kadro baştan üretilsin mi?'), T('Bütün botlar yeni adlar ve kişiliklerle yeniden üretilir, ilerlemeleri silinir.'), { ok: T('Baştan üret'), danger: true })) return;
          const x = await act(() => api('/api/bot/kadro', { id: d.id, adet, firma_dagilimi: f, dil, ad_dili: adDili, ad_kaynagi: adKaynagi, ozel, yeniden: true }), T('Kadro yeniden üretildi.')); if (x) { BT.d = x; btEditor(); }
        }, 'sm danger', 'refresh')));
  return h('div', { class: 'stack' },
    h('div', { class: 'card' }, h('h2', null, icon('users'), T('Kadro')),
      h('p', { class: 'desc' }, T('Kişilikler kadro üretilirken bir kez belirlendi: her botun arketipi, özellikleri (saldırganlık, sabır, sosyallik …), oyun saatleri ve yazım üslubu kendine.')),
      h('div', { class: 'row wrap', style: { gap: '6px', marginBottom: '12px' } }, Object.entries(ark).sort((a, b) => b[1] - a[1]).map(([k, n]) => badge(T(BT_ARKETIP[k] || k) + ' ' + n, ''))),
      kontrol),
    h('div', { class: 'card' }, h('h2', null, icon('list'), T('Botlar')),
      h('p', { class: 'desc' }, d.durum_var ? T('Seviye, gemi, harita ve iş sunucunun son kaydından (oyun açıkken dakikada bir). Satıra tıklayınca botun editörü açılır.') : T('Botlar henüz oynamadı: bu dünyada oyuna girince başlarlar.')),
      btKadroTablosu(d.kadro)));
}

// Kadro tablosu: ada göre arama, firma ve kişilik süzgeci, sıralama (oyuncu isteği 2026-10-30). Sıralanan değer hep tabloda görünür:
// kendi sütunu yoksa (EP, onur, kredi …) Seviye'nin yanında vurgulu bir sütun açılır. # süzülmüş ve sıralanmış listedeki yerdir.
const BT_SIRA = [['ad', N('Pilot')], ['seviye', N('Seviye')], ['rutbe', N('Rütbe')], ['gemi', N('Gemi')], ['harita', N('Harita')], ['hedef', N('Ne yapıyor')],
  ['npc', N('Uzaylı')], ['oyuncu', N('Oyuncu')], ['olum', N('Ölüm')]];
const BT_SIRA_EK = [['ep', N('Deneyim (EP)')], ['onur', N('Onur')], ['kredi', N('Kredi')], ['uridyum', N('Uridyum')], ['kapi', N('Biten galaksi kapısı')],
  ['firma', N('Firma')], ['arketip', N('Kişilik')]];
const BT_SIRA_DEGER = { npc: b => b.istat.npc || 0, oyuncu: b => b.istat.oyuncu || 0, olum: b => b.istat.olum || 0, kapi: b => b.istat.kapi_tamam || 0,
  harita: b => b.harita_ad || '', gemi: b => btGemiAd(b.gemi) };
const BT_SIRA_METIN = ['ad', 'gemi', 'harita', 'hedef', 'arketip', 'firma'];
const BT_SIRA_SAYI = new Set(['seviye', 'rutbe', 'npc', 'oyuncu', 'olum', 'ep', 'onur', 'kredi', 'uridyum', 'kapi']);
const BT_KAYNAK = { ep: 'deneyim', onur: 'onur', kredi: 'kredi', uridyum: 'uridyum' };
const btGemiAd = l => String(l || '').replace('ship_', '').replace(/^\w/, c => c.toUpperCase());
const btRutbe = (r, boy) => OG.dizin?.sprite['rank' + r] ? h('span', { class: 'bt-rutbe', title: T('Rütbe {0}', r) }, sprite('rank' + r, boy)) : h('span', null, r);
function btKadroTablosu(kadro) {
  const s = BT.kadroSuz = BT.kadroSuz || { ara: '', firma: 0, arketip: '', ozel: false, sira: 'no', ters: false };
  const tablo = h('table', { class: 'table bt-kadro' }), sayac = h('span', { class: 'bt-sayac' });
  const deger = (b, k) => BT_SIRA_DEGER[k] ? BT_SIRA_DEGER[k](b) : k === 'no' ? b.no : b[k] ?? '';
  const isik = () => BT_SIRA_EK.find(([k]) => k === s.sira && BT_SIRA_SAYI.has(k));       // sıralanan değerin kendi sütunu yok
  const sirala = k => { if (s.sira === k) s.ters = !s.ters; else { s.sira = k; s.ters = !BT_SIRA_METIN.includes(k); } ciz(); };
  const hucre = (b, k) => {
    const f = btFirma[b.firma - 1], n = deger(b, k);
    if (k === 'ad') return h('div', { class: 'bt-pilot' },
      h('div', { class: 'bt-pilot-ad' }, h('a', { href: '#', class: 'bt-ad', onclick: e => e.preventDefault() }, b.ad),
        b.ozel ? h('span', { class: 'badge info bt-ozel-rozet', title: T('Kendi eklediğin bot') }, T('Özel')) : null),
      h('div', { class: 'bt-pilot-alt' }, h('span', { class: 'bt-firma-et' }, f), T(BT_ARKETIP[b.arketip] || b.arketip),
        h('span', { class: 'dim' }, btOzellikOzeti(b.ozellik))));
    if (k === 'seviye') return h('b', { class: 'bt-sv' }, n);
    if (k === 'rutbe') return btRutbe(n || 1, 22);
    if (k === 'gemi') return h('div', { class: 'bt-gemi' }, gemiGorsel(b.gemi, 30, f.toLowerCase()), h('span', null, n));
    if (k === 'harita') return n || h('span', { class: 'dim' }, '—');
    if (k === 'hedef') return [b.hedef ? h('span', { class: 'bt-is' }, T(BT_HEDEF[b.hedef] || b.hedef)) : h('span', { class: 'dim' }, '—'), btAjanIzi(b)];
    if (BT_KAYNAK[k]) return h('span', { class: 'bt-kaynak' }, art('kaynak_' + BT_KAYNAK[k], 'bt-kaynak-ic'), fmtN(n));
    return n ? fmtN(n) : h('span', { class: 'dim' }, '0');
  };
  const ciz = () => {
    const ara = s.ara.trim().toLocaleLowerCase(LOC());
    const liste = kadro.filter(b => (!ara || b.ad.toLocaleLowerCase(LOC()).includes(ara)) && (!s.firma || b.firma === s.firma)
      && (!s.arketip || b.arketip === s.arketip) && (!s.ozel || b.ozel));
    const yon = s.ters ? -1 : 1, metin = BT_SIRA_METIN.includes(s.sira);
    liste.sort((a, b) => { const x = deger(a, s.sira), y = deger(b, s.sira);
      return yon * (metin ? String(x).localeCompare(String(y), LOC(), { numeric: true }) : (Number(x) || 0) - (Number(y) || 0)) || a.no - b.no; });
    const sutun = BT_SIRA.slice();
    if (isik()) sutun.splice(2, 0, isik());
    const sinif = k => [BT_SIRA_SAYI.has(k) ? 'num' : '', k === s.sira ? 'on' : '', isik()?.[0] === k ? 'isik' : '', 'k-' + k].join(' ');
    tablo.replaceChildren(
      h('thead', null, h('tr', null, h('th', { class: 'num bt-sira-no' }, '#'), sutun.map(([k, ad]) => h('th', { class: 'bt-sirali ' + sinif(k), title: T('Sıralamak için tıkla'),
        onclick: () => sirala(k) }, T(ad), icon(k === s.sira && s.ters ? 'asagi' : 'yukari'))))),
      h('tbody', null, liste.length ? liste.map((b, i) => h('tr', { class: 'f-' + btFirma[b.firma - 1].toLowerCase(), onclick: () => btBotDetay(b.no) },
        h('td', { class: 'num bt-sira-no' }, i + 1), sutun.map(([k]) => h('td', { class: sinif(k) }, hucre(b, k)))))
        : h('tr', null, h('td', { colspan: sutun.length + 1, class: 'bt-bos' }, T('Süzgece uyan bot yok.')))));
    sayac.textContent = T('{0} / {1} bot', liste.length, kadro.length);
    firmaSec.querySelectorAll('button').forEach((x, i) => x.classList.toggle('on', i === s.firma));
    siraSec.value = s.sira;
    yonBtn.replaceChildren(icon(s.ters ? 'asagi' : 'yukari'));
    yonBtn.title = s.ters ? T('Azalan: tıkla, artan olsun') : T('Artan: tıkla, azalan olsun');
  };
  const secim = (deg, secenekler, on) => h('select', { class: 'input', onchange: e => { on(e.target.value); ciz(); } },
    secenekler.map(([v, ad]) => h('option', { value: v, selected: String(v) === String(deg) }, ad)));
  const firmaSec = h('div', { class: 'seg bt-firma-sec' }, [T('Hepsi'), ...btFirma].map((ad, i) =>
    h('button', { type: 'button', class: i ? 'f-' + ad.toLowerCase() : '', onclick: () => { s.firma = i; ciz(); } }, ad)));
  const siraSec = secim(s.sira, [['no', T('Kadro sırası')]].concat(BT_SIRA.concat(BT_SIRA_EK).map(([k, ad]) => [k, T(ad)])), v => {
    s.sira = v; s.ters = !BT_SIRA_METIN.includes(v) && v !== 'no'; });
  const yonBtn = btn('', () => { s.ters = !s.ters; ciz(); }, 'ghost icon');
  const arac = h('div', { class: 'bt-suzgec' },
    h('label', { class: 'bt-ara' }, icon('search'), h('input', { class: 'input', type: 'search', placeholder: T('Ada göre ara'), value: s.ara,
      oninput: e => { s.ara = e.target.value; ciz(); } })),
    firmaSec,
    secim(s.arketip, [['', T('Bütün kişilikler')]].concat(Object.entries(BT_ARKETIP).map(([k, ad]) => [k, T(ad)])), v => { s.arketip = v; }),
    h('div', { class: 'bt-sirala' }, h('span', { class: 'small muted' }, T('Sırala')), siraSec, yonBtn),
    h('label', { class: 'row small bt-ozel-sec' }, btAnahtar(s.ozel, v => { s.ozel = v; ciz(); }), T('Yalnız kendi botların')),
    h('span', { class: 'spacer' }), sayac);
  ciz();
  return h('div', null, arac, h('div', { class: 'bt-tablo' }, tablo));
}

const BT_OZELLIK = { saldirganlik: N('saldırgan'), rekabet: N('rekabetçi'), sosyallik: N('sosyal'), sabir: N('sabırlı'), risk: N('riskçi'), sadakat: N('sadık'),
  yardimseverlik: N('yardımsever'), konuskanlik: N('konuşkan'), tutumluluk: N('tutumlu'), hirs: N('hırslı') };
function btOzellikOzeti(o) {
  const en = Object.entries(o || {}).sort((a, b) => b[1] - a[1]).slice(0, 2);
  return en.map(([k]) => T(BT_OZELLIK[k] || k)).join(', ');
}

// ------------------------------------------------------------------ Davranış, Erişimler, Sohbet
function btDavranis(d) {
  const a = d.ayarlar;
  return h('div', { class: 'card' }, h('h2', null, icon('target'), T('Davranış')),
    btSatir(T('PvP için en düşük seviye'), T('Bu seviyenin altındaki botlar PvP avına çıkmaz.'), btSayi(a.pvp_seviye, v => btA('pvp_seviye', v), { min: 1, max: 32 })),
    btSatir(T('Başka firmanın haritaları'), T('Botlar düşman firmaların haritalarına girebilir.'), btAnahtar(a.yabanci_harita, v => btA('yabanci_harita', v))),
    btSatir(T('Haritanda gemi olarak en çok'), T('Bulunduğun haritadaki botlardan en çok bu kadarı gemi olarak görünür; ötekiler arka planda oynar (performans).'),
      btSayi(a.somut_en_cok, v => btA('somut_en_cok', v), { min: 1, max: 150 })),
    btSatir(T('Kaç bota bir bot klanı'), T('Botların kurabileceği klan sayısı kadroya göre.'), btSayi(a.klan_basina, v => btA('klan_basina', v), { min: 3, max: 100 })),
    btSatir(T('Yardım çağrısına en çok'), T('Sohbetteki bir yardım çağrısına gelen en çok bot.'), btSayi(a.yardim_en_cok, v => btA('yardim_en_cok', v), { min: 0, max: 20 })),
    h('h3', null, T('Yoğun saat (prime time)')),
    btSatir(T('Başlangıç ve bitiş saati'), T('Akşamın yoğun saatleri (bilgisayarının saatiyle): daha çok bot çevrimiçi olur ve PvP canlanır. Başlangıç bitişe eşitse yoğun saat yok.'),
      h('div', { class: 'row', style: { gap: '6px' } }, btSayi(a.prime_baslangic, v => btA('prime_baslangic', v), { min: 0, max: 23 }), h('span', null, '–'),
        btSayi(a.prime_bitis, v => btA('prime_bitis', v), { min: 0, max: 23 }))),
    btSatir(T('Yoğun saatte PvP isteği'), T('PvP avına çıkma isteğinin çarpanı (1: fark yok).'),
      btKaydirac(a.prime_pvp, v => btA('prime_pvp', v), { min: 1, max: 5, step: 0.5, fmt: v => 'x' + v })),
    btSatir(T('Büyük savaşlar'), T('Yoğun saatte üç firmanın PvP botları her saat değişen bir cephe haritasında (4-4, 4-5, 4-1/2/3) toplanır. Haritanda gemi olarak görünen sayıyı artırırsan savaş büyür.'),
      btAnahtar(a.buyuk_savas, v => btA('buyuk_savas', v))));
}

function btErisim(d) {
  const iz = Object.assign({}, d.ayarlar.izinler);
  const izinler = (BT.liste?.izinler || Object.keys(BT_IZIN)).filter(k => d.kip !== 'basit' || ['pvp', 'oyuncuya_saldir'].includes(k));
  return h('div', { class: 'card' }, h('h2', null, icon('shield'), T('Erişimler')),
    h('p', { class: 'desc' }, T('Botların oyunun hangi bölümlerini kullanacağı. Kapatılan bölümü hiçbir bot kullanmaz.')),
    izinler.map(k => btSatir(T(BT_IZIN[k][0]), T(BT_IZIN[k][1]), btAnahtar(iz[k] !== false, v => { iz[k] = v; btA('izinler', { [k]: v }); }))));
}

function btSohbet(d) {
  const a = d.ayarlar;
  return h('div', null, h('div', { class: 'card' }, h('h2', null, icon('chat'), T('Sohbet')),
    btSatir(T('Laf atma'), T('Botların sataşma düzeyi: Kapalı (hep kibar), Hafif, Sert (öldürünce globalde laf atar, sataşmaya sert karşılık), Çok sert (düşman firmaya ve sana sık sık laf atar). Küfür ve gerçek tehdit hiçbirinde yok.'),
      btSeg([[0, T('Kapalı')], [1, T('Hafif')], [2, T('Sert')], [3, T('Çok sert')]], a.kaba_sohbet, v => btA('kaba_sohbet', v))),
    btSatir(T('Sohbet'), T(BT_IZIN.sohbet[1]), btAnahtar(a.izinler.sohbet !== false, v => btA('izinler', { sohbet: v }))),
    btSatir(T('Kanal yoğunluğu'), T('Global ve firma sohbetinde dakikada en çok bot satırı (sohbet sele dönmesin).'),
      btKaydirac(a.sohbet_dk, v => btA('sohbet_dk', v), { min: 0, max: 30, step: 1, fmt: v => T('{0}/dk', v) })),
    h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, d.kip === 'gelismis'
      ? T('Gelişmiş kipte botlar dil modeliyle konuşur; model yetişemezse kalıp cümlelere döner.')
      : T('Normal kipte botlar duruma ve kişiliklerine göre kalıp cümlelerle konuşur: selamlaşır, seviye atlayınca yazar, yardım çağrılarına ve fısıltına yanıt verir.')))),
    btModerasyon(d));
}

// bot klanları (bot/klan_yonetim.py, bot/klan_us.py): logo (Orders.md OP-017; yoksa etiket), lider, kasa, bütçe, istasyon, diplomasi
const BT_DIPLO = { 1: N('ittifak'), 2: N('saldırmazlık'), 3: N('savaş') };
function btKlanLogo(k) {
  if (!k.logo) return h('div', { class: 'bt-klan-logo bos' }, String(k.etiket || '?').slice(0, 4));
  const im = h('img', { class: 'bt-klan-logo', src: 'gorsel/klan_logo/' + k.logo + '.webp', alt: '' });
  im.onerror = () => im.replaceWith(btKlanLogo({ etiket: k.etiket }));
  return im;
}
function btKlanlar(d) {
  const ks = d.klanlar || [];
  const kart = k => h('div', { class: 'bt-klan' }, btKlanLogo(k),
    h('div', { class: 'bt-klan-govde' },
      h('div', { class: 'bt-klan-ad' }, h('b', null, '[' + k.etiket + '] ' + k.ad), badge(T('{0} üye', k.uye), '')),
      h('div', { class: 'small muted' }, [T('Lider: {0}', k.lider), T('Kasa: {0} kredi', fmtN(k.kasa)), T('Vergi: %{0}', k.vergi)].join(' · ')),
      k.butce ? h('div', { class: 'small muted' }, T('Bütçe: istasyon %{0}, ödeme %{1}, savaş %{2}', ...['ksi', 'odeme', 'savas'].map(a => Math.round(100 * (k.butce[a] || 0))))) : null,
      k.rutbeler.length ? h('div', { class: 'small muted' }, T('Rütbeler: {0}', k.rutbeler.join(', '))) : null,
      h('div', { class: 'small' }, k.istasyonlar.length ? T('İstasyon: {0}', k.istasyonlar.join(', ')) : k.yaris ? T('İstasyon yarışında: {0}', k.yaris) : T('İstasyonu yok')),
      k.diplomasi.length ? h('div', { class: 'small muted' }, k.diplomasi.map(x => T(BT_DIPLO[x.tur] || '?') + ': ' + x.ad).join(' · ')) : null,
      k.haberler.length ? h('div', { class: 'small muted bt-klan-haber' }, '“' + k.haberler[0] + '”') : null));
  return h('div', { class: 'stack' }, h('div', { class: 'card' }, h('h2', null, icon('star'), T('Klanlar')),
    h('p', { class: 'desc' }, T('Botların kurduğu ve üye olduğu klanlar (sunucunun son kaydından). Liderler rütbeleri, açıklamayı, duyuruları, vergiyi, kasanın bütçesini ve Klan Savaş İstasyonlarını kendileri yönetir.')),
    ks.length ? h('div', { class: 'bt-klanlar' }, ks.map(kart))
      : h('div', { class: 'small muted' }, T('Henüz bot klanı yok: lider ruhlu botlar seviye ve para biriktirince kurar.'))));
}

// sohbet moderatörleri (bot/moderasyon.py): kuralı çiğneyen önce uyarılır, sonra susturulur, sonra yasaklanır
function btModerasyon(d) {
  const a = d.ayarlar;
  return h('div', { class: 'card' }, h('h2', null, icon('shield'), T('Sohbet moderatörleri')),
    h('p', { class: 'desc' }, T('Sakin, sabırlı birkaç bot sohbet moderatörü olur (adları moderatör renginde). Kuralı çiğneyen (sen ya da botlar) önce uyarılır, yine çiğnerse susturulur, çok susturulan sohbetten yasaklanır. Yalnız global ve firma sohbeti; kararı çevrimiçi bir moderatör verir.')),
    btSatir(T('Moderatörler'), T('Açıkken moderatör botlar kuralları uygular.'), btAnahtar(a.moderator, v => btA('moderator', v))),
    btSatir(T('Moderatör sayısı'), T('Kadrodan seçilen moderatör bot sayısı.'), btSayi(a.mod_sayisi, v => btA('mod_sayisi', v), { min: 1, max: 10 })),
    btSatir(T('BÜYÜK HARF yasak'), T('Çoğu büyük harfle yazılmış mesaj.'), btAnahtar(a.kural_buyuk, v => btA('kural_buyuk', v))),
    btSatir(T('Spam yasak'), T('Aynı mesajı üç kez ya da 10 saniyede beş mesaj.'), btAnahtar(a.kural_sel, v => btA('kural_sel', v))),
    btSatir(T('Hakaret yasak'), T('Hakaret ve zararlı sözler.'), btAnahtar(a.kural_hakaret, v => btA('kural_hakaret', v))),
    btSatir(T('Reklam yasak'), T('Bağlantılar ve reklam.'), btAnahtar(a.kural_reklam, v => btA('kural_reklam', v))),
    btSatir(T('Susturma süresi (dk)'), null, btSayi(a.sustur_dk, v => btA('sustur_dk', v), { min: 1, max: 1440 })),
    btSatir(T('Kaç susturmada yasak'), null, btSayi(a.yasak_esik, v => btA('yasak_esik', v), { min: 1, max: 10 })),
    btSatir(T('Yasak süresi (saat)'), null, btSayi(a.yasak_saat, v => btA('yasak_saat', v), { min: 1, max: 720 })));
}

function btBasit(d) {
  const a = JSON.parse(JSON.stringify(d.ayarlar));
  const kaydet = () => btYama({ ayarlar: { basit_haritalar: a.basit_haritalar, basit_guc: a.basit_guc, basit_dost: a.basit_dost } });
  return h('div', { class: 'card' }, h('h2', null, icon('bot'), T('Basit kip')),
    h('p', { class: 'desc' }, T('Botlar haritalara seviyelerine göre dağıtılır ve orada kalır: uzaylı keser, düşmansa seni görünce gücüne göre saldırır ya da kaçar, ölünce aynı haritada doğar.')),
    btBasitAyar(a, null, false, kaydet));
}

// botun son düşüncesi (modelin kendi notu, İngilizce); tıklayınca editörün Düşünceler ya da Hafıza bölümü (bot/ani.py, bot/ajan.py)
function btAjanIzi(b) {
  const son = (b.ajan || []).filter(x => x.dusunce).slice(-1)[0];
  if (!son && !b.hafiza) return null;
  return h('a', { href: '#', class: 'small muted bt-ajan', title: T('Ayrıntılar için tıkla'),
    onclick: e => { e.preventDefault(); e.stopPropagation(); btBotDetay(b.no, son ? 'dusunce' : 'hafiza'); } }, icon('brain'), son ? son.dusunce : T('Aklındakiler'));
}
const BT_AMAC = { soz: N('söz'), intikam: N('intikam'), tesekkur: N('teşekkür'), rekabet: N('rekabet'), merak: N('merak') };
const BT_RUH = { ofke: N('Öfke'), moral: N('Moral'), sikilma: N('Sıkılma'), yorgunluk: N('Yorgunluk'), ozguven: N('Özgüven') };
const BT_EKIP = [['lazer', N('Lazerler'), 'lazer'], ['kalkan', N('Kalkan jeneratörleri'), 'jen'], ['hiz', N('Hız jeneratörleri'), 'jen'], ['dron', N('Dronlar')], ['ekstra', N('Ekstralar'), 'ekstra']];
const BT_ISTAT = { npc: N('Öldürülen uzaylı'), oyuncu: N('Öldürülen oyuncu'), olum: N('Ölüm'), kutu: N('Bonus kutusu'), kargo_kutusu: N('Kargo kutusu'),
  kutu_caldi: N('Başkasının kargo kutusu'), alim: N('Alışveriş'), gorev: N('Biten görev'), sure_sn: N('Oyun süresi'),
  harcama_kredi: N('Harcanan kredi'), harcama_uridyum: N('Harcanan uridyum'), cevher_kredi: N('Cevher satışından kredi'), ikmal: N('Cephane ikmali'),
  kutu_acti: N('Açılan ganimet kutusu'), anahtar_alim: N('Alınan anahtar'), aritma: N('Arıtma'), lab_yukleme: N('Laboratuvar yüklemesi'),
  skylab_yukseltme: N('Skylab yükseltmesi'), skylab_tasima: N('Skylab taşıması'), teknoloji: N('Teknoloji üretimi'), assembly: N('Assembly üretimi'),
  mod_kosu: N('Mod koşusu'), kapi_tamam: N('Biten galaksi kapısı'), kapi_kayip: N('Kaybedilen galaksi kapısı'), kapi_cekilis: N('Kapı çekilişi'),
  etkinlik_npc: N('Etkinlik uzaylısı'), etkinlik_kutusu: N('Etkinlik kutusu'), etkinlik_dusme: N('Etkinlik ganimeti'), pass_gorev: N('Battle Pass görevi'),
  battle_pass: N('Battle Pass'), sezon_seviye: N('Season Pass seviyesi'), dispatch: N('Dispatch'), galaxy_trek: N('Galaxy Trek'), mayin: N('Mayın'),
  smart_bomb: N('Smart Bomb'), emp: N('EMP'), salvo: N('Roket salvosu'), gizlendi: N('Gizlenme'), atlama_cpu: N("Atlama CPU'su") };
const BT_ISTAT_ONDE = ['npc', 'oyuncu', 'olum', 'gorev', 'kapi_tamam', 'sure_sn'];          // İstatistik bölümünün büyük kutuları
const BT_UYARI = { sohbet: N('sohbet'), pvp: N('PvP'), kutu: N('kargo kutusu') };
const keSureBt = sn => sn ? (sn >= 3600 ? Math.floor(sn / 3600) + ':' : '') + String(Math.floor(sn / 60) % 60).padStart(sn >= 3600 ? 2 : 1, '0') + ':' + String(Math.round(sn) % 60).padStart(2, '0') : '—';
const btKisa = l => String(l || '').split('_').pop().toUpperCase();
const btBuyuk = m => m ? m.charAt(0).toLocaleUpperCase(LOC()) + m.slice(1) : m;
const BT_OLAY = { oldurdu_beni: N('beni vurdu'), oldurdum: N('ben vurdum'), yardim_etti: N('yardım etti'), yardim_ettim: N('yardım ettim'),
  sohbet: N('sohbet'), hakaret: N('hakaret'), ovgu: N('övgü'), grup: N('grup'), klan: N('klan'), arkadas: N('arkadaşlık'), reddetti: N('reddetti'),
  birlikte_avlandik: N('birlikte avlandık'), meydan: N('meydan okudu'), dedikodu_iyi: N('iyi dedikodu'), dedikodu_kotu: N('kötü dedikodu'),
  uyarildim: N('yönetici uyardı') };
const BT_ALISKANLIK = { gunduzcu: N('Gündüz oynar'), aksamci: N('Akşam oynar'), gece_kusu: N('Gece kuşu'), tutkun: N('Tutkun') };

// kişilik radarı: on özellik bir çokgen (0 merkez, 1 dış halka); ayarla(o) şekli kaydırıcıyla birlikte günceller
function btRadar(o) {
  const NS = 'http://www.w3.org/2000/svg', K = Object.keys(BT_OZELLIK), R = 92, M = 130;
  const el = (ad, a) => { const e = document.createElementNS(NS, ad); for (const k in a) e.setAttribute(k, a[k]); return e; };
  const nokta = (i, r) => { const a = -Math.PI / 2 + i * 2 * Math.PI / K.length; return [M + Math.cos(a) * r, M + Math.sin(a) * r]; };
  const svg = el('svg', { viewBox: '0 0 260 260', class: 'bt-radar', role: 'img', 'aria-label': T('Kişilik') });
  for (const r of [.25, .5, .75, 1]) svg.append(el('polygon', { class: 'izgara', points: K.map((_, i) => nokta(i, R * r).join(',')).join(' ') }));
  K.forEach((k, i) => {
    const [x, y] = nokta(i, R), [tx, ty] = nokta(i, R + 16);
    svg.append(el('line', { class: 'izgara', x1: M, y1: M, x2: x, y2: y }));
    const t = el('text', { x: tx, y: ty + 4, 'text-anchor': Math.abs(tx - M) < 8 ? 'middle' : tx > M ? 'start' : 'end' });
    t.textContent = btBuyuk(T(BT_OZELLIK[k])); svg.append(t);
  });
  const sekil = el('polygon', { class: 'sekil' }), noktalar = K.map(() => el('circle', { r: 3 }));
  svg.append(sekil, ...noktalar);
  const ayarla = d => {
    const p = K.map((k, i) => nokta(i, R * Math.max(.03, d[k] ?? .5)));
    sekil.setAttribute('points', p.map(x => x.join(',')).join(' '));
    noktalar.forEach((c, i) => { c.setAttribute('cx', p[i][0]); c.setAttribute('cy', p[i][1]); });
  };
  ayarla(o);
  return { svg, ayarla };
}

// ------------------------------------------------------------------ bot editörü: kimlik kartı ve bölüm menüsü solda, bölüm sağda
// (bot/duzenle.py; /api/bot/detay). Değişiklikler birikir, Kaydet tek istekte yazar. Oyun bu paketle açıkken canlı bot okunur ve
// düzenleme hemen oyunda geçerli olur.
const BT_D_SEKMELER = [['profil', N('Profil'), 'user', N('Ad, seviye, cüzdan, harita ve şu anki işi.')],
  ['kisilik', N('Kişilik'), 'brain', N('Kararlarını belirleyen özellikleri ve şu anki ruh hâli.')],
  ['hangar', N('Hangar'), 'ship', N('Gemi, donanım, cephane ve kargo. En iyi eşyalar yuvalara takılır, fazlası depoda kalır.')],
  ['hafiza', N('Hafıza'), 'note', N('Kişiler hakkında düşündükleri, anıları, hedefleri ve hatırlatıcıları.')],
  ['dusunce', N('Düşünceler'), 'chat', N('Dil modelinin son kararları ve kullandığı araçlar.')],
  ['istat', N('İstatistik'), 'gauge', N('Sayaçlar, kapı süreleri, uyarılar, arkadaşlar ve Skylab.')]];
const BT_D_GORSEL = { profil: 'ke_pilot', hangar: 'ke_hangar', kisilik: 'bt_kisilik', hafiza: 'bt_hafiza', dusunce: 'bt_dusunce', istat: 'bt_istat' };   // Orders.md OP-013, OP-019
const btDIkon = s => BT_D_GORSEL[s[0]] ? h('span', { class: 'ke-sk-ic gorsel' }, art(BT_D_GORSEL[s[0]], 'ke-sk-art')) : h('span', { class: 'ke-sk-ic' }, icon(s[2]));

async function btBotDetay(no, sekme = 'profil') {
  const pid = BT.d.id;
  let v;
  try { [v] = await Promise.all([api('/api/bot/detay?id=' + encodeURIComponent(pid) + '&no=' + no), ogYukle()]); } catch (e) { toast(e.message, 'err'); return; }
  let deg = {};
  const kat = v.katalog;
  const kilit = !!v.salt_okunur;
  const fc = () => btFirma[v.firma - 1].toLowerCase();
  const yan = h('aside', { class: 'bt-d-yan' }), ana = h('div', { class: 'bt-d-ana' }), durum = h('div', { class: 'bt-d-durum' });
  const kaydet = btn(T('Kaydet'), async () => {
    const x = await act(() => api('/api/bot/detay', { id: pid, no, degisiklik: deg }), T('Kaydedildi.'));
    if (x) { v = x; deg = {}; ciz(); BT.d = await api('/api/bot?id=' + encodeURIComponent(pid)).catch(() => BT.d); }
  }, 'primary', 'check');
  const vazgec = btn(T('Vazgeç'), () => { deg = {}; ciz(); }, 'ghost', 'undo');
  // değişiklik sayacı (alt çubuk): kaydedilmemiş alan sayısı
  const isle = () => {
    const n = Object.keys(deg).length;
    kaydet.disabled = kilit || !n; vazgec.disabled = !n;
    btDoldur(durum, kilit ? [icon('lock'), T('Salt okunur')] : n ? [h('span', { class: 'ke-nabiz' }), T('{0} değişiklik kaydedilmedi', n)] : [icon('check'), T('Kayıtla aynı')]);
    durum.className = 'bt-d-durum' + (n && !kilit ? ' var' : '');
  };
  const degis = (a, val) => { deg[a] = val; isle(); };
  const al = (a, yedek) => deg[a] !== undefined ? deg[a] : yedek;
  const liste = (a, ek) => { deg[a] = (deg[a] || []).concat([ek]); ciz(); };
  const sozluk = (a, k, val) => { deg[a] = Object.assign({}, deg[a], { [k]: val }); isle(); };
  const kart = (baslik, ic, ...govde) => h('div', { class: 'card ke-k bt-dk' }, baslik ? h('h2', null, icon(ic), baslik) : null, ...govde);
  const bos = metin => h('div', { class: 'bt-d-bos' }, metin || T('Henüz bir şey yok.'));
  const yok = () => h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Bu bot henüz oyunda görünmedi: yalnız adı ve kişiliği düzenlenebilir.')));
  const sil = (onclick, title = T('Sil')) => btn('', onclick, 'ghost sm icon', 'trash', { title, disabled: kilit });
  const sayi = (n, on, o = {}) => { const el = btSayi(n, on, o); el.disabled = kilit; return el; };
  const yuzde = (n, on, cls = '') => kaydirici({ min: 0, max: 100, step: 1, value: Math.round(n * 100), disabled: kilit, oninput: e => on(+e.target.value / 100) }, cls);
  const simdi = Date.now() / 1000;

  // ---- sol: kimlik kartı (kayıtlı değerler) ve bölüm menüsü
  function kimlik() {
    const p = v.profil || {}, f = fc(), e = v.ekip || {};
    const sat = (ad, n, etiket) => h('div', { class: 'ke-cz' }, art('kaynak_' + ad, 'ke-para-ic'), h('span', null, etiket), h('b', null, fmtN(n)));
    const dg = (ic, n, baslik) => h('div', { class: 'ke-dg', title: baslik }, h('span', { class: 'bt-dg-ic' }, icon(ic)), h('b', null, n));
    const yuk = Object.values(v.kargo || {}).reduce((a, n) => a + n, 0);
    return h('div', { class: 'card ke-kimlik f-' + f },
      h('div', { class: 'ke-kimlik-sahne' }, h('div', { class: 'ke-halka' }), gemiGorsel(e.gemi || 'ship_phoenix', 150, f)),
      h('div', { class: 'ke-kimlik-bas' }, portre(v.firma, 'ke-portre kucuk', 84),
        h('div', { style: { minWidth: 0 } }, h('div', { class: 'ke-kimlik-ad', title: v.ad }, v.ad),
          h('div', { class: 'ke-pilot small' }, p.klan ? h('span', { class: 'ke-klan' }, '[' + p.klan + ']') : null, badge(btFirma[v.firma - 1], f),
            v.cevrimici ? badge(T('Çevrimiçi'), 'ok') : null))),
      h('div', { class: 'bt-d-etiket' }, h('div', null, h('b', null, T(BT_ARKETIP[v.arketip] || v.arketip)),
        v.aliskanlik ? T(BT_ALISKANLIK[v.aliskanlik] || v.aliskanlik) : null), h('div', { class: 'dim' }, btOzellikOzeti(v.ozellik))),
      v.var ? [
        h('div', { class: 'ke-sv sm' }, h('div', { class: 'ke-sv-n' }, h('small', null, T('Sv')), h('b', null, p.seviye)),
          h('div', { class: 'grow' }, h('div', { class: 'row between small muted' }, btRutbe((BT.d.kadro.find(b => b.no === no) || {}).rutbe || 1, 18), h('span', { class: 'mono' }, fmtKisa(p.ep) + ' EP')),
            epBar(p.ep, p.taban_ep || 0, p.sonraki_ep))),
        h('div', { class: 'ke-cuzdan' }, sat('kredi', p.kredi, T('Kredi')), sat('uridyum', p.uridyum, T('Uridyum')), sat('onur', p.onur, T('Onur'))),
        h('div', { class: 'ke-degerler' }, dg('zap', fmtKisa(v.guc.guc), T('Güç')), dg('crosshair', fmtKisa(v.guc.dps), T('Hasar/sn')),
          dg('heart', fmtKisa(v.guc.ehp), T('Etkin can')), dg('box', fmtKisa(yuk) + '/' + fmtKisa(v.kargo_kapasite), T('Kargo')))] : null);
  }
  function menu() {
    const n = { hangar: v.var ? BT_EKIP.reduce((a, [k]) => a + Object.keys(v.ekip[k] || {}).length, 0) : 0, hafiza: v.var ? v.anilar.length + v.iliskiler.length : 0,
      dusunce: (v.ajan || []).length };
    return h('nav', { class: 'card ke-menu' }, BT_D_SEKMELER.map(s => h('button', { class: s[0] === sekme ? 'on' : '', type: 'button',
      onclick: () => { if (sekme !== s[0]) { sekme = s[0]; ana.scrollTop = 0; ciz(); } } },
    btDIkon(s), h('span', null, T(s[1])), n[s[0]] ? h('span', { class: 'ke-say' }, fmtN(n[s[0]])) : null)));
  }

  // ---- Profil
  function profil() {
    const p = v.profil || {};
    let ad = v.ad;
    const adKart = kart(T('Ad'), 'edit', h('div', { class: 'bt-d-ad' },
      h('input', { class: 'input', value: v.ad, maxlength: 20, disabled: kilit, oninput: e => { ad = e.target.value.trim(); yeniden.disabled = kilit || ad === v.ad; },
        onkeydown: e => { if (e.key === 'Enter') yeniden.click(); } }),
      yeniden = btn(T('Yeniden adlandır'), async () => {
        if (ad === v.ad) return;
        const x = await act(() => api('/api/bot/ad', { id: pid, no, ad }), T('Kaydedildi.'));
        if (x) { BT.d = x; v.ad = ad; ciz(); }
      }, '', 'edit', { disabled: true })),
      h('div', { class: 'small dim' }, T('3-20 karakter: harf, rakam, _ . -  Ad hemen değişir, Kaydet beklemez.')));
    if (!v.var) return [adKart, yok()];
    const para = (key, ikon, etiket, n, o) => h('div', { class: 'ke-para' }, art('kaynak_' + ikon, 'ke-para-ic lg'),
      h('div', { class: 'grow' }, h('label', { class: 'lbl' }, etiket), sayi(al(key, n), x => degis(key, x), Object.assign({ min: 0, max: 2e12, cls: 'num wide' }, o))));
    const sv = p.sonraki_ep ? T('Seviye {0}; sonraki seviye {1} EP.', p.seviye, fmtN(p.sonraki_ep)) : T('Seviye {0}.', p.seviye);
    const is = [p.hedef ? T(BT_HEDEF[p.hedef] || p.hedef) : '—', p.niyet && p.niyet !== p.hedef ? T('Niyeti: {0}', T(BT_HEDEF[p.niyet] || p.niyet)) : null];
    return [adKart,
      kart(T('Seviye ve cüzdan'), 'star', h('div', { class: 'bt-d-paralar' },
        h('div', null, para('ep', 'deneyim', T('Deneyim (EP)'), p.ep, { max: 1e12 }), h('div', { class: 'small dim bt-d-not' }, sv)),
        para('kredi', 'kredi', T('Kredi'), p.kredi), para('uridyum', 'uridyum', T('Uridyum'), p.uridyum),
        para('onur', 'onur', T('Onur'), p.onur, { min: -2e12 }))),
      kart(T('Konum ve iş'), 'map',
        btSatir(T('Harita'), v.cevrimici ? T('Çevrimiçi botun haritası değiştirilemez: çevrimdışı olunca dene.') : T('Bot bir sonraki girişinde bu haritada başlar.'),
          h('select', { class: 'input', disabled: kilit || !!v.cevrimici, onchange: e => degis('harita', Number(e.target.value)) },
            kat.haritalar.map(m => h('option', { value: m.id, selected: m.id === al('harita', p.harita) }, m.ad)))),
        btSatir(T('Ne yapıyor'), is[1], h('span', { class: 'bt-is' }, is[0])),
        btSatir(T('Görev'), v.tamam ? T('{0} görev bitirdi.', v.tamam) : null, v.gorev && !deg.gorev_iptal
          ? h('div', { class: 'row', style: { gap: '8px' } }, h('b', null, v.gorev.ad), btn(T('Görevi bırak'), () => { degis('gorev_iptal', true); ciz(); }, 'ghost sm', 'x', { disabled: kilit }))
          : h('span', { class: 'dim' }, deg.gorev_iptal ? T('Bırakılacak') : '—')),
        btSatir(T('Klan'), null, h('span', null, p.klan ? '[' + p.klan + ']' : '—')))];
  }

  // ---- Kişilik: radar + özellik kaydırıcıları, ruh hâli
  function kisilik() {
    const oz = Object.assign({}, v.ozellik, deg.ozellik);
    const r = btRadar(oz);
    const ozSatir = ([k, ad_]) => {
      const deger = h('b', null, Math.round(oz[k] * 100));
      return h('div', { class: 'bt-oz' }, h('span', null, btBuyuk(T(ad_))), deger,
        yuzde(oz[k], x => { oz[k] = x; deger.textContent = Math.round(x * 100); r.ayarla(oz); sozluk('ozellik', k, x); }));
    };
    const ruh = Object.assign({}, v.ruh, deg.ruh);
    const ruhSatir = ([k, ad_]) => {
      const deger = h('b', null, Math.round((ruh[k] ?? 0) * 100));
      return h('div', { class: 'bt-oz ruh-' + k }, h('span', null, T(ad_)), deger,
        yuzde(ruh[k] ?? 0, x => { deger.textContent = Math.round(x * 100); sozluk('ruh', k, x); }, 'bt-ruh'));
    };
    return [kart(T('Özellikler'), 'brain', h('p', { class: 'desc' }, T('Kadro üretilirken belirlendi; değiştirince bot buna göre karar verir (saldırgan bot PvP\'ye, sosyal bot sohbete, tutumlu bot birikime yatkındır).')),
      h('div', { class: 'bt-kisilik' }, h('div', { class: 'bt-radar-kutu' }, r.svg), h('div', { class: 'bt-ozler' }, Object.entries(BT_OZELLIK).map(ozSatir)))),
    v.var ? kart(T('Ruh hâli'), 'heart', h('p', { class: 'desc' }, T('Şu anki duyguları: zamanla dengeye döner. Öfkeli bot intikam peşine düşer, yorgun bot erken çıkar.')),
      h('div', { class: 'bt-ozler iki' }, Object.entries(BT_RUH).map(ruhSatir))) : null];
  }

  // ---- Hangar: gemi, donanım kutuları, cephane, kargo
  function hangar() {
    if (!v.var) return [yok()];
    const e = v.ekip, f = fc();
    const gemi = al('gemi', e.gemi);
    const g = kat.gemiler.find(x => x.loot === gemi) || {};
    const yuva = { lazer: g.lazer, jen: g.jen, ekstra: g.ekstra };
    const esya = (l, n, ayarla, sil_, azami) => h('div', { class: 'bt-esya' }, oyunIkon(l, 44, f, 'box'),
      h('div', { class: 'bt-esya-ad', title: esyaAdi(l) }, esyaAdi(l)),
      h('div', { class: 'bt-esya-alt' }, sayi(n, ayarla, { min: 0, max: azami, cls: 'num' }), sil_ ? sil(sil_) : null));
    const ekleSec = (secenekler, on) => h('select', { class: 'input bt-ekle', disabled: kilit, onchange: ev => { if (ev.target.value) on(ev.target.value); } },
      [h('option', { value: '' }, T('Ekle…'))].concat(secenekler.map(x => h('option', { value: x.loot }, x.ad))));
    const kategori = ([k, ad_, yv]) => {
      const sahip = Object.assign({}, e[k], (deg.ekip || {})[k]);
      const yaz = yeni => { deg.ekip = Object.assign({}, deg.ekip, { [k]: yeni }); isle(); };
      const var_ = Object.entries(sahip).filter(([, n]) => n > 0);
      const takili = x => Object.values(Object.assign({}, e[x], (deg.ekip || {})[x])).reduce((a, n) => a + n, 0);
      // kalkan ve hız aynı jeneratör yuvalarını paylaşır; ekstranın sayısı kalan hakkı (JP-01 10 hak): her biri bir yuva
      const toplam = yv === 'jen' ? takili('kalkan') + takili('hiz') : k === 'ekstra' ? var_.length : takili(k);
      return h('div', { class: 'bt-kat' },
        h('div', { class: 'bt-kat-bas' }, h('b', null, T(ad_)), h('span', { class: 'ke-say' }, yv && yuva[yv] != null ? T('{0} / {1} yuva', toplam, yuva[yv]) : fmtN(toplam)),
          h('span', { class: 'spacer' }), ekleSec(kat[k].filter(x => !sahip[x.loot]), l => { yaz(Object.assign({}, sahip, { [l]: (kat[k].find(x => x.loot === l) || {}).hak || 1 })); ciz(); })),
        var_.length ? h('div', { class: 'bt-esyalar' }, var_.map(([l, n]) => esya(l, n, x => yaz(Object.assign({}, sahip, { [l]: x })),
          () => { const y = Object.assign({}, sahip); delete y[l]; yaz(y); ciz(); }, k === 'ekstra' ? 100000 : k === 'dron' ? 10 : 100))) : bos(T('Takılı bir şey yok.')));
    };
    const stok = Object.assign({}, v.stok, deg.stok);
    const yuk = Object.values(v.kargo).reduce((a, n) => a + n, 0), kap = v.kargo_kapasite || 1;
    return [
      kart(T('Gemi'), 'ship', h('div', { class: 'bt-gemi-kart' },
        h('div', { class: 'bt-gemi-sahne' }, gemiGorsel(gemi, 132, f)),
        h('div', { class: 'bt-gemi-sag' },
          field(T('Gemi'), h('select', { class: 'input', disabled: kilit, onchange: ev => { degis('gemi', ev.target.value); ciz(); } },
            kat.gemiler.map(x => h('option', { value: x.loot, selected: x.loot === gemi }, x.ad)))),
          h('div', { class: 'bt-yuvalar' }, [['zap', g.lazer, T('lazer')], ['shield', g.jen, T('jeneratör')], ['cpu', g.ekstra, T('ekstra')]].map(([ic, n, ad_]) =>
            h('span', { class: 'chip' }, icon(ic), h('b', null, n ?? '?'), ad_))),
          field(T('Kullandığı cephane'), h('select', { class: 'input', disabled: kilit, onchange: ev => degis('cephane', ev.target.value) },
            kat.cephane.filter(x => x.loot.includes('_laser_')).map(x => h('option', { value: x.loot, selected: x.loot === al('cephane', e.cephane) }, x.ad)))),
          h('div', { class: 'bt-guc' }, [[T('Güç'), v.guc.guc], [T('Hasar/sn'), fmtN(v.guc.dps)], [T('Etkin can'), fmtN(v.guc.ehp)]].map(([k, n]) =>
            h('div', null, h('span', null, k), h('b', null, n)))),
          deg.gemi || deg.ekip ? h('div', { class: 'small dim' }, T('Güç kaydedince yeniden hesaplanır.')) : null))),
      kart(T('Donanım'), 'layers', ...BT_EKIP.map(kategori)),
      kart(T('Cephane ve roketler'), 'ammo',
        h('div', { class: 'bt-kat-bas' }, h('span', { class: 'small muted' }, T('Depodaki cephane, roketler ve kaynaklar.')), h('span', { class: 'spacer' }),
          ekleSec(kat.cephane.filter(x => stok[x.loot] === undefined), l => { sozluk('stok', l, 100); ciz(); })),
        Object.keys(stok).length ? h('div', { class: 'bt-esyalar' }, Object.entries(stok).map(([l, n]) => esya(l, n, x => sozluk('stok', l, x), null, 1e9))) : bos()),
      kart(T('Kargo'), 'box',
        h('div', { class: 'bt-kargo' }, h('div', { class: 'bt-kargo-bar' }, h('span', { style: { width: Math.min(100, 100 * yuk / kap) + '%' } })),
          h('span', { class: 'small muted' }, T('{0} / {1}', fmtN(yuk), fmtN(kap)))),
        Object.keys(v.kargo).length && !deg.kargo_bosalt
          ? h('div', { class: 'row wrap', style: { gap: '6px', alignItems: 'center', marginTop: '10px' } }, Object.entries(v.kargo).map(([o, n]) => h('span', { class: 'chip' }, o, h('b', null, fmtN(n)))),
            h('span', { class: 'spacer' }), btn(T('Kargoyu boşalt'), () => { degis('kargo_bosalt', true); ciz(); }, 'ghost sm', 'trash', { disabled: kilit }))
          : bos(deg.kargo_bosalt ? T('Kaydedince boşaltılacak.') : T('Kargo boş.'))),
    ];
  }

  // ---- Hafıza
  function hafiza() {
    if (!v.var) return [yok()];
    const silinen = (a, k) => (deg[a] || []).includes(k);
    const iliski = v.iliskiler.filter(x => !silinen('iliski_sil', x.anahtar)).map(x => {
      const d = al('iliski', {})[x.anahtar] ?? x.d;
      const deger = h('b', { class: d >= 0 ? 'iyi' : 'kotu' }, (d > 0 ? '+' : '') + d.toFixed(2));
      const kay = kaydirici({ min: -100, max: 100, step: 5, value: Math.round(d * 100), disabled: kilit, oninput: e => {
        const y = +e.target.value / 100; deger.textContent = (y > 0 ? '+' : '') + y.toFixed(2); deger.className = y >= 0 ? 'iyi' : 'kotu'; sozluk('iliski', x.anahtar, y); } }, 'bt-iliski-ar');
      return h('div', { class: 'bt-iliski' }, h('div', null, h('b', null, x.ad),
        h('div', { class: 'small dim' }, Object.entries(x.n || {}).map(([t, n]) => (BT_OLAY[t] ? T(BT_OLAY[t]) : t) + ' ' + n).join(', '))),
      h('div', { class: 'bt-iliski-olcek' }, h('span', { class: 'small dim' }, T('Düşman')), kay, h('span', { class: 'small dim' }, T('Dost'))), deger,
      sil(() => liste('iliski_sil', x.anahtar)));
    });
    const izlenim = v.izlenim.filter(x => !silinen('izlenim_sil', x.anahtar)).map(x => h('div', { class: 'bt-not' }, h('b', null, x.ad),
      h('textarea', { class: 'input', rows: 2, disabled: kilit, oninput: e => sozluk('izlenim', x.anahtar, e.target.value) }, al('izlenim', {})[x.anahtar] ?? x.metin),
      sil(() => liste('izlenim_sil', x.anahtar))));
    const anilar = v.anilar.filter(a => !silinen('ani_sil', a.id)).map(a => {
      const bekliyor = a.takip && !a.takip.bitti && !silinen('takip_iptal', a.id);
      return h('div', { class: 'bt-ani' }, h('div', { class: 'bt-ani-bas' }, h('b', null, a.kim), h('span', { class: 'small dim' }, T('{0} önce', fmtDur(simdi - a.t))),
        a.n > 1 ? h('span', { class: 'ke-say' }, '×' + a.n) : null, bekliyor ? badge(T('Bekleyen: {0}', T(BT_AMAC[a.takip.amac] || a.takip.amac)), 'warn') : null,
        h('span', { class: 'spacer' }), bekliyor ? btn('', () => liste('takip_iptal', a.id), 'ghost sm icon', 'x', { title: T('Bekleyen işi iptal et'), disabled: kilit }) : null,
        sil(() => liste('ani_sil', a.id))),
      h('input', { class: 'input', value: al('ani', {})[a.id] ?? a.ozet, disabled: kilit, oninput: e => sozluk('ani', a.id, e.target.value) }));
    });
    const defter = al('defter', v.defter);
    const defterSatir = (m, i) => h('div', { class: 'bt-defter' }, h('span', { class: 'bt-defter-no' }, i + 1),
      h('input', { class: 'input', value: m, disabled: kilit, oninput: e => { const d = defter.slice(); d[i] = e.target.value; degis('defter', d); } }),
      sil(() => { degis('defter', defter.filter((_, j) => j !== i)); ciz(); }));
    return [
      kart(T('İlişkileri'), 'users', h('p', { class: 'desc' }, T('Kişilere bakışı: dostlarına yardım eder, düşmanlarına saldırır.')), iliski.length ? iliski : bos()),
      kart(T('Kişiler hakkındaki izlenimleri'), 'note', izlenim.length ? h('div', { class: 'bt-notlar' }, izlenim) : bos()),
      kart(T('Anıları'), 'clock', anilar.length ? h('div', { class: 'bt-anilar' }, anilar) : bos()),
      h('div', { class: 'grid g2' },
        kart(T('Hedef defteri'), 'target', ...(defter.length ? defter.map(defterSatir) : [bos()]),
          h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '8px' } },
            btn(T('Hedef ekle'), () => { degis('defter', defter.concat([''])); ciz(); }, 'ghost sm', 'plus', { disabled: kilit }))),
        kart(T('Hatırlatıcılar ve birikim'), 'bell',
          v.hatirlatici.length && !deg.hatirlatici_sil
            ? [h('ul', { class: 'bt-akil' }, v.hatirlatici.map(x => h('li', null, x.metin, h('span', { class: 'dim' }, ' (' + T('{0} sonra', fmtDur(x.kalan_sn)) + ')')))),
              h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '6px' } }, btn(T('Hatırlatıcıları sil'), () => { degis('hatirlatici_sil', true); ciz(); }, 'ghost sm', 'trash', { disabled: kilit }))]
            : bos(T('Hatırlatıcı yok.')),
          h('div', { class: 'bt-birikim' }, h('span', { class: 'lbl' }, T('Biriktirdiği')), v.birikim && !deg.birikim_sil
            ? h('div', { class: 'row', style: { gap: '8px' } }, oyunIkon(v.birikim, 28, fc(), 'box'), h('b', null, esyaAdi(v.birikim)), h('span', { class: 'spacer' }),
              btn(T('Biriktirmeyi bırak'), () => { degis('birikim_sil', true); ciz(); }, 'ghost sm', 'x', { disabled: kilit }))
            : h('span', { class: 'dim' }, '—')))),
    ];
  }

  // ---- Düşünceler: dil modelinin adımları (yeniden eskiye)
  function dusunce() {
    const iz = deg.ajan_sil ? [] : (v.ajan || []).slice().reverse();
    const adim = x => [h('b', null, x.arac), x.arg && Object.keys(x.arg).length ? ' ' + JSON.stringify(x.arg) : '', x.sonuc ? h('span', { class: 'dim' }, ' → ' + x.sonuc) : null];
    return [kart(T('Son düşünceleri'), 'chat', h('p', { class: 'desc' }, T('Botun kendi notları; dil modeli İngilizce tutar.')),
      iz.length ? h('ol', { class: 'bt-dusunceler' }, iz.map(x => h('li', null, x.dusunce ? h('div', null, x.dusunce) : null, h('div', { class: 'bt-adim' }, adim(x)))))
        : bos(deg.ajan_sil ? T('Kaydedince temizlenecek.') : T('Henüz düşünce yok: Gelişmiş kipte dil modeli karar verdikçe dolar.')),
      iz.length ? h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '10px' } }, btn(T('Düşünceleri temizle'), () => { degis('ajan_sil', true); ciz(); }, 'ghost sm', 'trash', { disabled: kilit })) : null)];
  }

  // ---- İstatistik
  function istat() {
    if (!v.var) return [yok()];
    const ist = v.istat || {};
    const deger = (k, n) => k === 'sure_sn' ? fmtDur(n) : fmtN(Math.round(n));
    const kalan = Object.entries(ist).filter(([k]) => !BT_ISTAT_ONDE.includes(k)).sort((a, b) => (BT_ISTAT[a[0]] ? 0 : 1) - (BT_ISTAT[b[0]] ? 0 : 1));
    return [
      h('div', { class: 'stats bt-d-stats' }, BT_ISTAT_ONDE.map(k => h('div', { class: 'stat' }, h('div', { class: 'k' }, T(BT_ISTAT[k])), h('div', { class: 'v' }, deger(k, ist[k] || 0))))),
      kart(T('Bütün sayaçlar'), 'list', kalan.length ? h('div', { class: 'kv bt-kv' }, kalan.map(([k, n]) => h('div', null, BT_ISTAT[k] ? T(BT_ISTAT[k]) : k, h('b', null, deger(k, n))))) : bos()),
      h('div', { class: 'grid g2' },
        kart(T('Kapı süreleri'), 'clock', Object.keys(v.kapi_sureleri || {}).length ? h('div', { class: 'kv one' },
          Object.entries(v.kapi_sureleri).map(([g, x]) => h('div', null, g.charAt(0).toUpperCase() + g.slice(1), h('b', null, T('en iyi {0}', keSureBt(x.en_iyi)) + ' · ' + T('{0} kez', fmtN(x.sayi))))))
          : bos()),
        kart(T('Arkadaşları'), 'users', (v.profil.arkadaslar || []).length ? h('div', { class: 'row wrap', style: { gap: '6px' } }, v.profil.arkadaslar.map(a => h('span', { class: 'chip' }, a))) : bos()),
        kart(T('Yönetici uyarısı'), 'alert', Object.keys(v.uyari || {}).length ? h('div', { class: 'row wrap', style: { gap: '6px' } },
          Object.entries(v.uyari).map(([k, t]) => badge(T(BT_UYARI[k] || k) + ' · ' + T('{0} kaldı', fmtDur(Math.max(0, t - Date.now() / 1000))), 'warn'))) : bos(T('Uyarı yok.'))),
        kart(T('Skylab'), 'layers', Object.keys(v.skylab || {}).length ? h('div', { class: 'row wrap', style: { gap: '6px' } }, Object.entries(v.skylab).map(([m, n]) => h('span', { class: 'chip' }, m, h('b', null, n)))) : bos())),
    ];
  }

  let yeniden;
  function ciz() {
    const s = BT_D_SEKMELER.find(x => x[0] === sekme) || BT_D_SEKMELER[0], sc = ana.scrollTop;
    btDoldur(yan, kimlik(), menu());
    btDoldur(ana, h('div', { class: 'ke-ana-bas' }, btDIkon(s), h('div', null, h('h2', null, T(s[1])), h('div', { class: 'small muted' }, T(s[3])))),
      kilit ? h('div', { class: 'alert uyari' }, icon('alert'), h('div', null, T('Oyun bu paketle açık ama sunucuya ulaşılamadı: son kayıt gösteriliyor, düzenlenemez.')))
        : v.canli ? h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Oyun açık: değişiklikler kaydedince hemen oyunda geçerli olur.'))) : null,
      ({ profil, kisilik, hangar, hafiza, dusunce, istat })[s[0]]());
    ana.scrollTop = sc;
    isle();
  }
  ciz();
  const m = modal({ title: T('Bot editörü'), sub: T('{0} paketi · {1}. bot', BT.d.ad, no), body: h('div', { class: 'bt-d' }, yan, ana), onclose: () => btEditor(),
    foot: [durum, h('span', { class: 'spacer' }), btn(T('Kapat'), async () => {
      if (Object.keys(deg).length && !await confirmBox(T('Değişiklikler kaydedilmedi'), T('Kapatınca kaydedilmemiş değişiklikler atılır.'), { ok: T('Kaydetmeden kapat'), danger: true })) return;
      m.close();
    }, 'ghost'), vazgec, kaydet] });
  m.box.classList.add('bt-d-modal');
}

function btKullanim(u) {
  if (!u) return h('div', { class: 'small muted' }, T('Oyun bu paketle açılınca ölçülür.'));
  const s = u.saat || {}, pay = s.girdi ? Math.round(100 * (s.onbellek || 0) / s.girdi) : 0;
  return h('div', { class: 'small', style: { textAlign: 'right' } },
    h('div', null, T('{0} istek · {1} girdi tokeni (%{2} önbellekten) · {3} çıktı tokeni', fmtN(s.istek || 0), fmtN(s.girdi || 0), pay, fmtN(s.cikti || 0))),
    h('div', { class: 'muted' }, [u.saglayici, u.sinir ? T('Saatlik sınır: {0} / {1} istek', fmtN(s.istek || 0), fmtN(u.sinir)) : T('Saatlik sınır yok'),
      u.sure_dk < 60 ? T('son {0} dakikada', u.sure_dk) : null].filter(Boolean).join(' · ')),
    u.sinirda ? h('div', { style: { color: 'var(--warn)' } }, T('Sınıra gelindi: botlar şimdilik kalıplarla konuşuyor ve kurallı kararla oynuyor.')) : null);
}

function btGelismis(d) {
  return typeof btLlmKart === 'function' ? btLlmKart(d) : h('div', { class: 'card' }, btLlmUyari());
}

// ------------------------------------------------------------------ Gelişmiş kip: dil modeli (llm_kurulum.py, /api/bot/llm)
function btLlmKart(d) {
  const kutu = h('div'), sag = h('div');
  const a = d.ayarlar;
  btLlmIzle(kutu, sag);
  return h('div', { class: 'stack' },
    h('div', { class: 'card' }, h('h2', null, icon('brain'), T('Dil modeli')),
      h('div', { class: 'bt-llm' }, btArt('bot_llm', 'dron_ayarlar', 'bt-llm-art'), h('div', { class: 'stack', style: { gap: '10px' } }, sag, kutu))),
    h('div', { class: 'card' }, h('h2', null, icon('sliders'), T('Gelişmiş kip ayarları')),
      btSatir(T('Son bir saatin kullanımı'), T('Botların dil modeline son bir saatte gönderdiği istekler ve tokenler (sohbet, anılar ve kararlar). Sağlayıcının faturası token sayısına göre işler; önbellekten gelen girdi çok daha ucuzdur.'),
        btKullanim(d.llm_kullanim)),
      btSatir(T('Aynı anda düşünen bot'), T('Modelin paralel yuvaları: istekler toplu işlenir. Yüksekse daha çok bot aynı anda konuşur ama bilgisayar daha çok zorlanır.'),
        btSayi(a.llm_toplu, v => btA('llm_toplu', v), { min: 1, max: 16 })),
      btSatir(T('Sohbet modelle'), T('Kapalıysa botlar Normal kipteki gibi kalıplarla konuşur; model yalnız kararlarda kullanılır.'), btAnahtar(a.llm_sohbet, v => btA('llm_sohbet', v))),
      btSatir(T('Kararları gözden geçirme (dakika)'), T('Her bot bu kadar dakikada bir durumunu modele danışır (0: hiç). Kısa süre daha canlı ama daha ağır.'),
        btSayi(a.llm_karar_dk, v => btA('llm_karar_dk', v), { min: 0, max: 120 })),
      // araç döngüsü yalnız dahili model dışındaki sağlayıcılarda (bot/ajan.py)
      btSatir(T('Araçlarla oynasın'), T('Dahili model dışındaki sağlayıcılarda bot, oyuncu gibi önce durumuna, haritalara, mağazaya ve görevlere bakar, sonra araçlarla karar verir; hedef defteri tutar, kendine hatırlatıcı kurar.'),
        btAnahtar(a.llm_ajan, v => btA('llm_ajan', v))),
      btSatir(T('Düşünme başına en çok adım'), T('Bir düşünmede modele en çok kaç kez sorulur (her seferde birkaç araç). Çoğu düşünme 1-2 istekte biter; yüksek değer daha çok istek demek.'),
        btSayi(a.llm_ajan_adim, v => btA('llm_ajan_adim', v), { min: 1, max: 10 })),
      btSatir(T('Saatlik istek sınırı'), T('Dahili model dışındaki sağlayıcıya saatte en çok bu kadar istek gider (sohbet, anılar ve kararlar dahil; 0: sınırsız). Sınıra gelince botlar kalıplarla konuşur ve kurallı kararla oynar; harcamayı sınırlar.'),
        btSayi(a.llm_saatlik, v => btA('llm_saatlik', v), { min: 0, max: 20000 }))));
}

function btLlmIzle(kutu, sag) {
  let imza = '', secili = null;
  // sağlayıcı formu yalnız seçim değişince yeniden çizilir (yoklama yazılanı silmesin); alt kutu dahili modelde kurulum, ötekilerde test
  const ciz = s => {
    imza = JSON.stringify(s);
    if (BT.liste) BT.liste.llm_cok_dilli = s.saglayici.cok_dilli;
    if (secili !== s.saglayici.secili || s.yeni_form) { secili = s.saglayici.secili; btDoldur(sag, btLlmSaglayici(s.saglayici, x => ciz(Object.assign(x, { yeni_form: true })))); }
    btDoldur(kutu, secili === 'yerel' ? h('div', { class: 'stack', style: { gap: '10px' } }, btLlmUyari(), btLlmKutu(s, ciz)) : btLlmUzakKutu(s, ciz));
  };
  api('/api/bot/llm').then(ciz).catch(e => btDoldur(kutu, h('div', { class: 'alert hata' }, icon('alert'), h('div', null, e.message))));
  const id = setInterval(async () => {
    if (!kutu.isConnected) return clearInterval(id);
    let s; try { s = await api('/api/bot/llm'); } catch (e) { return; }
    if (JSON.stringify(s) !== imza) ciz(s);
  }, 1000);
}

// sağlayıcı adları (öteki sağlayıcıların adı kendi markası)
const BT_SAGLAYICI_AD = { yerel: N('Dahili yerel model (Qwen3 4B)'), ozel: N('Özel (OpenAI uyumlu)') };
function btLlmSaglayici(sg, yeni) {
  const p = sg.liste.find(x => x.kimlik === sg.secili);
  const f = { adres: p.adres, model: p.model, anahtar: '' };
  const gonder = (govde, msg) => act(() => api('/api/bot/llm/saglayici', govde), msg).then(x => { if (x) yeni(x); });
  const sec = h('select', { class: 'input', onchange: e => gonder({ kimlik: e.target.value }, T('Kaydedildi.')) },
    sg.liste.map(x => h('option', { value: x.kimlik, selected: x.kimlik === sg.secili }, BT_SAGLAYICI_AD[x.kimlik] ? T(BT_SAGLAYICI_AD[x.kimlik]) : x.ad)));
  const satirlar = [btSatir(T('Sağlayıcı'), T('Botların sohbeti ve kararları bu modelle verilir.'), sec)];
  if (sg.secili === 'yerel') return h('div', null, satirlar);
  // model: önce elle yazılır; modeller çekilince açılır liste olur (datalist dolu kutuda süzülüp açılmıyordu)
  const modelKutu = h('div', null, h('input', { class: 'input', value: f.model, oninput: e => { f.model = e.target.value.trim(); } }));
  const getir = async () => {
    const x = await act(() => api('/api/bot/llm/modeller', { kimlik: sg.secili, adres: f.adres, anahtar: f.anahtar }), r => T('{0} model bulundu.', r.modeller.length));
    if (!x || !x.modeller.length) return;
    const ms = x.modeller.includes(f.model) || !f.model ? x.modeller : [f.model].concat(x.modeller);
    if (!f.model) f.model = ms[0];
    btDoldur(modelKutu, h('select', { class: 'input', onchange: e => { f.model = e.target.value; } }, ms.map(m => h('option', { value: m, selected: m === f.model }, m))));
  };
  satirlar.push(
    btSatir(T('Adres'), p.yerel ? T('Bilgisayarında çalışan sunucunun OpenAI uyumlu adresi (…/v1). Sunucu açık olmalı.') : T('Çoğu zaman değiştirmen gerekmez.'),
      h('input', { class: 'input', value: f.adres, placeholder: p.varsayilan_adres, oninput: e => { f.adres = e.target.value.trim(); } })),
    btSatir(p.anahtar_gerekir ? T('API anahtarı') : T('API anahtarı (isteğe bağlı)'), T('Yalnız bu bilgisayarda saklanır; bot paketlerine girmez.'),
      h('input', { class: 'input', type: 'password', autocomplete: 'off', oninput: e => { f.anahtar = e.target.value.trim(); },
        placeholder: p.anahtar_var ? T('Kayıtlı ({0}); değiştirmek için yaz', p.anahtar) : p.anahtar_gerekir ? T('API anahtarını yapıştır') : T('Gerekmiyorsa boş bırak') })),
    btSatir(T('Model'), T('Hızlı ve ucuz bir sohbet modeli yeter; düşünen (reasoning) modeller yavaş yanıt verir.'),
      h('div', { class: 'row', style: { gap: '6px' } }, modelKutu, btn(T('Modelleri getir'), getir, 'ghost sm', 'download'))),
    h('div', { class: 'row', style: { gap: '8px', justifyContent: 'flex-end' } },
      p.anahtar_var ? btn(T('Anahtarı sil'), () => gonder({ kimlik: sg.secili, anahtar: '-' }, T('Silindi.')), 'ghost sm', 'trash') : null,
      btn(T('Kaydet'), () => gonder({ kimlik: sg.secili, adres: f.adres, model: f.model, anahtar: f.anahtar }, T('Kaydedildi.')), 'primary sm', 'check')),
    h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Bu sağlayıcıyla botlar kendi sohbet dillerinde konuşur (Kadro sekmesinden seçilir). Ücretli sağlayıcılarda istekler senin hesabından ödenir: "Aynı anda düşünen bot" ve "Kararları gözden geçirme" ayarları istek sayısını belirler.'))));
  return h('div', { class: 'stack', style: { gap: '4px' } }, satirlar);
}

function btLlmUzakKutu(s, ciz) {
  const t = s.test && s.test.saglayici === s.saglayici.secili ? s.test : {};
  return h('div', { class: 'bt-llm-adim' }, icon(t.durum === 'ok' ? 'check' : 'play'),
    h('div', null, h('b', null, t.durum === 'ok' ? T('Sağlayıcı çalışıyor') : T('Test et')),
      h('div', { class: 'small muted' }, t.durum === 'calisiyor' ? T('Sağlayıcıya kısa bir soru soruluyor…') : t.durum === 'hata' ? t.hata
        : t.durum === 'ok' ? T('Yanıt {0} sn: "{1}"', t.sure_sn, t.yanit ?? '') : T('Kaydettikten sonra sağlayıcıya kısa bir soru sorulur; yanıt gelirse botlar onunla konuşur.'))),
    t.durum === 'calisiyor' ? h('span', { class: 'spin' }) : btn(T('Test et'), () => act(() => api('/api/bot/llm/test', {})).then(x => { if (x) ciz(x); }), 'primary sm', 'play'));
}

function btLlmKutu(s, ciz) {
  const cagir = (yol, msg) => act(() => api('/api/bot/llm/' + yol, {}), msg).then(x => { if (x) ciz(x); });
  const pct = s.toplam ? Math.floor(100 * s.alinan / s.toplam) : 0;
  const t = s.test && !s.test.saglayici ? s.test : {};          // uzak sağlayıcının testi değil
  const az = s.bellek_gb != null && s.bellek_gb < s.en_az_bellek_gb;
  const donanim = h('div', { class: 'small muted' }, T('Bu bilgisayar: {0} GB bellek, {1} çekirdek.', s.bellek_gb ?? '?', s.cekirdek ?? '?'),
    az ? h('b', { style: { color: 'var(--warn)', marginLeft: '6px' } }, T('Önerilen en az {0} GB.', s.en_az_bellek_gb)) : null);
  if (!s.destekli) return h('div', { class: 'alert hata' }, icon('alert'), h('div', null, T('Bu bilgisayarın işlemcisi için hazır dil modeli sunucusu yok: Normal kipi kullan.')));
  const adim1 = s.calisiyor
    ? h('div', { class: 'dl-box' }, h('b', null, s.durum === 'kuruluyor' ? T('Kuruluyor…') : T('İndiriliyor: %{0}', pct)),
      h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } }))),
      h('div', { class: 'small muted dl-info' }, [`${fmtBytes(s.alinan)} / ${fmtBytes(s.toplam)}`, s.hiz ? `${fmtBytes(s.hiz)}/${T('sn')}` : null,
        s.kalan_sn != null && s.hiz ? T('kalan {0}', fmtDur(s.kalan_sn)) : null, s.parca].filter(Boolean).join(' · ')),
      h('div', { class: 'row' }, btn(T('Durdur'), () => cagir('durdur', T('İndirme durduruluyor…')), 'ghost sm', 'stop')))
    : ['kurulu', 'hazir'].includes(s.durum)
      ? h('div', { class: 'bt-llm-adim' }, icon('check'), h('div', null, h('b', null, T('Kuruldu')), h('div', { class: 'small muted' }, s.model + ' · llama.cpp ' + s.surum)),
        btn(T('Kaldır'), async () => { if (await confirmBox(T('Dil modeli silinsin mi?'), T('İndirilen 2,5 GB silinir; Gelişmiş kip yeniden kurulana dek Normal kip gibi çalışır.'), { ok: T('Sil'), danger: true })) cagir('sil', T('Silindi.')); }, 'ghost sm', 'trash'))
      : h('div', { class: 'bt-llm-adim' }, icon('download'), h('div', null, h('b', null, s.durum === 'hata' ? T('Kurulamadı') : s.durum === 'durdu' ? T('İndirme durduruldu') : T('1. Dil modelini kur')),
        h('div', { class: 'small muted' }, s.durum === 'hata' ? s.hata : T('{0} indirilir (yarım kalırsa kaldığı yerden sürer).', fmtBytes(s.boyut))), donanim),
        btn(s.durum === 'hata' || s.durum === 'durdu' || s.yarim ? T('Sürdür') : T('İndir ve kur'), () => cagir('kur'), 'primary sm', 'download'));
  const kuruldu = ['kurulu', 'hazir'].includes(s.durum);
  const adim2 = h('div', { class: 'bt-llm-adim' }, icon(s.durum === 'hazir' ? 'check' : 'play'),
    h('div', null, h('b', null, s.durum === 'hazir' ? T('Kurulum tamamlandı: model çalışıyor') : T('2. Test et')),
      h('div', { class: 'small muted' }, t.durum === 'calisiyor' ? T('Model açılıyor ve kısa bir soru soruluyor (ilk açılış yarım dakikayı bulabilir)…')
        : t.durum === 'hata' ? t.hata : t.durum === 'ok' || s.son_test ? T('Açılış {0} sn, yanıt {1} sn: "{2}"', (t.acilis_sn ?? s.son_test?.acilis_sn), (t.sure_sn ?? s.son_test?.sure_sn), (t.yanit ?? s.son_test?.yanit ?? ''))
        : T('Model bir kez açılıp kısa bir soruya yanıt verir; yanıt gelirse kurulum tamamdır.'))),
    t.durum === 'calisiyor' ? h('span', { class: 'spin' }) : btn(T('Test et'), () => cagir('test'), (kuruldu && s.durum !== 'hazir' ? 'primary' : 'ghost') + ' sm', 'play', { disabled: !kuruldu }));
  return h('div', { class: 'stack', style: { gap: '4px' } }, adim1, adim2,
    s.durum === 'hazir' ? h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Oyun açılınca model de açılır; botların sohbeti ve kararları onunla verilir. Model yetişemezse botlar Normal kipteki gibi davranır.'))) : null);
}

// ------------------------------------------------------------------ botların oyun ayarı profili (bot/oyun_ayari.py)
function btOyunAyariKart(d) {
  const oa = JSON.parse(JSON.stringify(d.ayarlar.oyun_ayari || { profil: 'standart', degerler: {} }));
  const bilgi = BT.liste?.oyun_ayarlari || { hazir: [], alanlar: [] };
  const secenekler = [['standart', T('Standart (oyunun kendi değerleri)')], ['oyuncu', T('Benim oyun ayarlarım')]]
    .concat(bilgi.hazir.map(x => [x.id, T(x.ad)]), [['ozel', T('Özel')]]);
  const kaydet = () => btA('oyun_ayari', oa);
  const sec = h('select', { class: 'input', onchange: e => { oa.profil = e.target.value; kaydet(); btDoldur(ozel, ozelCiz()); aciklama.textContent = acikla(); } },
    secenekler.map(([v, ad]) => h('option', { value: v, selected: oa.profil === v }, ad)));
  const acikla = () => {
    const hz = bilgi.hazir.find(x => x.id === oa.profil);
    return hz ? T(hz.aciklama) : oa.profil === 'oyuncu' ? T('Botlar da Oyun Ayarları sayfasındaki çarpanlarla oynar (kolay ayarda onlar da hızlı gelişir).')
      : oa.profil === 'ozel' ? T('Aşağıdaki çarpanlar yalnız botlara uygulanır.') : T('Botlar oyunun kendi ödülleri ve uzaylılarıyla oynar; senin oyun ayarların onları etkilemez.');
  };
  const aciklama = h('div', { class: 'help' }, acikla());
  const ozelCiz = () => oa.profil !== 'ozel' ? null : bilgi.alanlar.map(a => btSatir(T(a.ad), T(a.aciklama),
    btKaydirac(oa.degerler[a.anahtar] ?? 1, v => { oa.degerler[a.anahtar] = v; kaydet(); }, { min: a.en_az, max: a.en_cok, step: 0.05, fmt: v => '×' + v.toFixed(2) })));
  const ozel = h('div', null, ozelCiz());
  return h('div', { class: 'card' }, h('h2', null, icon('sliders'), T('Oyun ayarları')),
    h('p', { class: 'desc' }, T('Botların ödül ve zorluk çarpanları senin oyun ayarlarından ayrı: kendine kolay ayar seçsen de botlar burada seçtiğinle gelişir.')),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Profil')), aciklama), h('div', { class: 'ctl' }, sec)), ozel);
}
