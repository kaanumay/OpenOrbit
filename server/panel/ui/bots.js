/* OpenOrbit paneli — Botlar (bots.py, /api/bot…; belgeler/BOTLAR.md). panel.js'in yardımcılarını kullanır.
   Bot paketi: kadrosu oluşturulurken bir kez üretilen botlar (ad, firma, kişilik) ve ayarları. Paket bir dünyaya atanır; oyuncu o
   dünyada oyuna girince botlar devreye girer. Kipler: Basit (haritalarda dolaşan, harita değiştirmeyen), Normal (gerçek oyuncu gibi
   gelişen, karar veren, sosyal), Gelişmiş (Normal + yerel dil modeli: sohbet ve kararlar).
   Görünümler: kitaplık (paket kartları), sihirbaz (ad ve dünya -> kip -> ayarlar), editör (sekmeler). Değişiklikler kendiliğinden
   kaydedilir. */
'use strict';

Object.assign(ICONS, {
  bot: '<rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 8V4"/><circle cx="12" cy="3" r="1"/><circle cx="9" cy="13" r="1.3"/><circle cx="15" cy="13" r="1.3"/><path d="M9 17h6"/>',
  brain: '<path d="M9 4a3 3 0 0 0-3 3v.5A3 3 0 0 0 4 10.5 3 3 0 0 0 5 13a3 3 0 0 0 1 5 3 3 0 0 0 6 1V5a2 2 0 0 0-3-1z"/><path d="M15 4a3 3 0 0 1 3 3v.5a3 3 0 0 1 2 3 3 3 0 0 1-1 2.5 3 3 0 0 1-1 5 3 3 0 0 1-6 1"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  yukari: '<path d="M12 19V5"/><path d="M6 11l6-6 6 6"/>',
  asagi: '<path d="M12 5v14"/><path d="M6 13l6 6 6-6"/>',
  list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><circle cx="3.5" cy="6" r="1"/><circle cx="3.5" cy="12" r="1"/><circle cx="3.5" cy="18" r="1"/>',
});

const BT = { liste: null, pid: null, d: null, sekme: 'genel', timer: null, bekleyen: {} };
const BT_MODES = {
  basit: { ad: N('Basit'), ic: 'bot', ozet: N('Haritalarda NPC gibi dolaşan, harita değiştirmeyen botlar. Uzaylı keser; düşmansa seni görünce gücüne göre saldırır ya da kaçar.') },
  normal: { ad: N('Normal'), ic: 'users', ozet: N('Gerçek oyuncu gibi: üssünde başlar, görev yapar, kasar, gemi ve lazer alır, PvP yapar, klan kurar, arkadaş edinir, sohbet eder. Her botun kişiliği ve kararları kendine.') },
  gelismis: { ad: N('Gelişmiş'), ic: 'brain', ozet: N('Normal kipin üstüne dil modeli (dahili Qwen3 4B, OpenAI, Claude, Gemini ya da kendi yerel LLM\'in): botlar seninle ve birbirleriyle gerçekten konuşur, ricalarını düşünüp karar verir, yardım çağrılarına gelir.') },
};
const BT_ARCHETYPE = { kasici: N('PvE kasıcı'), avci: N('PvP avcısı'), sosyal: N('Sosyal'), tuccar: N('Tüccar'), gorevci: N('Görevci'), rahat: N('Rahat'), lider: N('Lider') };
const BT_TARGET = { kasilma: N('Uzaylı kasıyor'), gorev: N('Görev yapıyor'), pvp: N('PvP avında'), alisveris: N('Alışverişte'), dinlenme: N('Dinleniyor'),
  kesif: N('Keşifte'), grup: N('Grupta'), yardim: N('Yardıma gidiyor'), basit: N('Uzaylı kasıyor'), satis: N('Kargo satıyor'),
  mod: N('Modda'), kapi: N('Galaksi kapısında'), duello: N('Düelloda') };
const BT_PERMS = {
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
const BT_CLASS_NAME = s => s === '4-X' ? '4-1…4-4' : s;
const btFill = (el, ...k) => el.replaceChildren(...k.flat(Infinity).filter(x => x != null && x !== false));
const btCompany = ['MMO', 'EIC', 'VRU'];
function btArt(name, backup, cls = 'bt-art') {         // görsel gelmediyse (Orders.md) var olan bir görsel
  const im = art(name, cls);
  im.onerror = () => { im.onerror = null; im.src = 'images/' + backup + '.webp'; };
  return im;
}
const btWorldName = id => (BT.liste?.dunyalar || []).find(w => w.id === id)?.ad || T('Atanmamış');

// ------------------------------------------------------------------ giriş noktası
async function renderBots() {
  const r = await act(() => api('/api/botlar')); if (!r || S.page !== 'botlar') return;
  BT.liste = r;
  if (BT.pid && !r.liste.some(p => p.id === BT.pid)) BT.pid = null;
  if (!BT.pid) return btLibrary();
  btEditor();
}
function btOpen(pid, tab) { BT.pid = pid; BT.sekme = tab || 'genel'; renderBots(); }

function btCompanyBar(f) {
  const top = f.reduce((a, b) => a + b, 0) || 1;
  return h('div', { class: 'bt-companies', title: btCompany.map((x, i) => x + ' ' + f[i]).join(' · ') },
    f.map((n, i) => h('i', { class: btCompany[i].toLowerCase(), style: { width: (100 * n / top) + '%' } })));
}

// ================================================================== KİTAPLIK
function btLibrary() {
  const r = BT.liste;
  const card = p => h('div', { class: 'bt-card', onclick: e => { if (!e.target.closest('button')) btOpen(p.id); } },
    h('div', { class: 'bt-card-top k-' + p.kip }, btArt('bot_kip_' + p.kip, 'dron_editor', 'bt-card-art'),
      h('div', null, h('b', null, p.ad), h('div', { class: 'small muted' }, T(BT_MODES[p.kip].ad) + ' · ' + T('{0} bot', p.adet)))),
    h('div', { class: 'bt-card-body' },
      h('div', { class: 'row wrap', style: { gap: '6px' } }, p.dunya ? badge([icon('globe'), btWorldName(p.dunya)], 'info') : badge(T('Dünyaya atanmadı'), 'warn'),
        p.kip !== 'basit' ? badge(p.gelisim === 'jumpstart' ? 'Jumpstart' : 'Progressive', '') : null),
      btCompanyBar(p.firmalar),
      h('div', { class: 'small muted' }, p.level_avg != null ? T('Ortalama seviye {0} · en yüksek {1}', p.level_avg, p.level_max)
        : T('Henüz oynanmadı: botlar ilk girişte başlar.')),
      p.aciklama ? h('div', { class: 'small ellipsis' }, p.aciklama) : null),
    h('div', { class: 'bt-card-bottom' }, btn(T('Aç'), () => btOpen(p.id), 'sm primary', 'edit'),
      btn('', ev => btPackMenu(ev.currentTarget, p), 'sm ghost icon', 'more', { title: T('Diğer') })));
  btFill($('#content'), h('div', { class: 'stack' },
    h('div', { class: 'card bt-intro' }, btArt('bot_giris', 'dron_hosgeldin', 'bt-intro-art'),
      h('div', null, h('h2', null, icon('bot'), T('Botlar')),
        h('p', { class: 'desc' }, T('Bot paketi oluştur, bir dünyaya ata: o dünyada oynarken botlar gerçek oyuncular gibi haritalarda olur. Kadro bir kez üretilir; her girişte aynı botlarla karşılaşırsın, onlar da sen yokken bile ilerler.')),
        h('div', { class: 'row wrap' }, btn(T('Yeni bot paketi'), () => btWizard(), 'primary', 'plus')))),
    h('div', { class: 'bt-grid' }, r.liste.map(card), h('button', { class: 'bt-card yeni', onclick: () => btWizard() }, icon('plus'), h('span', null, T('Yeni bot paketi'))))));
}

function btPackMenu(anchor, p) {
  popMenu(anchor, [
    { label: T('Aç'), ic: 'edit', fn: () => btOpen(p.id) },
    { label: T('Dünyaya ata'), ic: 'globe', fn: () => btAssignMenu(anchor, p) },
    { label: T('Yeniden adlandır'), ic: 'edit', fn: async () => {
      const name = await promptBox(T('Yeniden adlandır'), T('Paketin adı'), p.ad); if (name == null) return;
      if (await act(() => api('/api/bot/update', { id: p.id, name }), T('Kaydedildi.'))) renderBots(); } },
    '-',
    { label: T('Sil'), ic: 'trash', danger: true, fn: async () => {
      if (!await confirmBox(T('"{0}" silinsin mi?', p.ad), T('Paket ve botların ilerlemesi silinir (save/botlar/_silinenler klasöründe saklanır).'), { ok: T('Sil'), danger: true })) return;
      const x = await act(() => api('/api/bot/sil', { id: p.id }), T('Bot paketi silindi.')); if (x) { BT.liste = x; if (BT.pid === p.id) BT.pid = null; renderBots(); } } },
  ]);
}

function btAssignMenu(anchor, p) {
  const items = BT.liste.dunyalar.map(w => ({ label: w.ad + (p.dunya === w.id ? '  ✓' : ''), ic: p.dunya === w.id ? 'check' : 'globe',
    fn: () => btAssign(p, w.id) }));
  items.push('-', { label: T('Atamayı kaldır'), ic: 'x', fn: () => btAssign(p, null), disabled: !p.dunya });
  popMenu(anchor, items);
}
async function btAssign(p, did) {
  const old = did && BT.liste.liste.find(x => x.dunya === did && x.id !== p.id);
  if (old && !await confirmBox(T('Dünyanın paketi değişsin mi?'), T('"{0}" dünyasında şu an "{1}" paketi var; o paket boşa çıkar.', btWorldName(did), old.ad))) return;
  const x = await act(() => api('/api/bot/assign', { id: p.id, dunya: did }), did ? T('"{0}" artık "{1}" dünyasında.', p.ad, btWorldName(did)) : T('Atama kaldırıldı.'));
  if (x) { BT.liste = x; renderBots(); }
}

// ================================================================== SİHİRBAZ
function btWizard() {
  const r = BT.liste;
  const w = { ad: '', aciklama: '', dunya: (r.dunyalar.find(d => !r.liste.some(p => p.dunya === d.id)) || r.dunyalar[0] || {}).id || null, kip: 'normal',
    gelisim: 'progressive', adet: 80, dil: 'karisik', ad_dili: 'karisik', ad_kaynagi: 'uretim', firma_dagilimi: [1, 1, 1], ozel: '', ayarlar: { jumpstart_saat: 60, basit_guc: 1, basit_dost: 0.5,
      basit_haritalar: { 'X-1': 2, 'X-2': 2, 'X-3': 2, 'X-4': 2, '4-X': 3, 'X-5': 1, 'X-6': 1, 'X-7': 1, 'X-8': 1, '4-5': 2 } } };
  let step = 0;
  const body = h('div', { class: 'stack', style: { gap: '14px' } });
  const footer = h('div', { class: 'row', style: { gap: '8px', justifyContent: 'flex-end', width: '100%' } });
  const m = modal({ title: T('Yeni bot paketi'), wide: true, body: body, foot: footer });
  const steps = [T('Ad ve dünya'), T('Kip'), T('Ayarlar')];
  function render() {
    const parent = h('div', { class: 'bt-steps' }, steps.map((a, i) => h('span', { class: i === step ? 'on' : i < step ? 'tamam' : '' }, h('b', null, i + 1), a)));
    btFill(body, parent, [btStep1, btStep2, btStep3][step](w, render));
    btFill(footer, btn(T('Vazgeç'), () => m.close(), 'ghost'), h('span', { class: 'spacer' }),
      step ? btn(T('Geri'), () => { step--; render(); }, 'ghost', 'arrowL') : null,
      step < 2 ? btn(T('İleri'), () => {
        if (step === 0 && !w.ad.trim()) return toast(T('Bot paketine bir ad ver.'), 'err');
        step++; render();
      }, 'primary') : btn(T('Oluştur'), async () => {
        const x = await act(() => api('/api/bot/create', w), T('Bot paketi oluşturuldu: {0}', w.ad.trim()));
        if (!x) return;
        m.close(); BT.liste = x; btOpen(x.yeni, w.kip === 'gelismis' ? 'gelismis' : 'kadro');
      }, 'primary', 'check'));
  }
  render();
}

function btStep1(w) {
  const r = BT.liste;
  const name = h('input', { class: 'input', value: w.ad, placeholder: T('Örn. Kalabalık Sunucu, Avcılar'), maxlength: 40, oninput: e => { w.ad = e.target.value; } });
  const is_open = h('textarea', { class: 'input', rows: 2, maxlength: 240, placeholder: T('Bu paket nasıl bir sunucu? (isteğe bağlı)'), oninput: e => { w.aciklama = e.target.value; } }, w.aciklama);
  const world = h('select', { class: 'input', onchange: e => { w.dunya = e.target.value || null; } },
    r.dunyalar.map(d => {
      const p = r.liste.find(x => x.dunya === d.id);
      return h('option', { value: d.id, selected: w.dunya === d.id }, d.ad + (p ? ' — ' + T('şu an: {0}', p.ad) : ''));
    }), h('option', { value: '', selected: !w.dunya }, T('Şimdilik atama')));
  return h('div', { class: 'stack', style: { gap: '14px' } }, field(T('Ad'), name), field(T('Açıklama'), is_open),
    field(T('Çalışacağı dünya'), world, h('div', { class: 'small muted' }, T('Oyuncu bu dünyada oyuna girince paket devreye girer. Bir dünyada tek paket olur.'))));
}

function btStep2(w, render) {
  const card = k => h('button', { type: 'button', class: 'bt-mode' + (w.kip === k ? ' on' : ''), onclick: () => { w.kip = k; render(); } },
    btArt('bot_kip_' + k, 'dron_editor', 'bt-mode-art'), h('b', null, icon(BT_MODES[k].ic), T(BT_MODES[k].ad)), h('div', { class: 'small' }, T(BT_MODES[k].ozet)));
  return h('div', { class: 'stack', style: { gap: '12px' } }, h('div', { class: 'bt-modes' }, ['basit', 'normal', 'gelismis'].map(card)),
    w.kip === 'gelismis' ? btLlmWarning(true) : null);
}

function btLlmWarning(wizard = false) {
  return h('div', { class: 'alert uyari' }, icon('alert'), h('div', null,
    h('b', null, T('Gelişmiş kip bilgisayarını çok zorlayabilir.')),
    h('div', null, T('Botların sohbeti ve kararları bilgisayarında çalışan Qwen3 4B (Q4_K_M) dil modeliyle verilir: yaklaşık 2,5 GB indirme, 4 GB boş bellek ve güçlü bir işlemci ya da ekran kartı ister. Zayıf bilgisayarlarda oyun yavaşlayabilir.')),
    h('div', { style: { marginTop: '6px' } }, T('Bilgisayarın kaldırmıyorsa Gelişmiş sekmesinden OpenAI, Claude, Gemini, DeepSeek gibi bir sağlayıcıyı API anahtarınla ya da kendi yerel LLM sunucunu (Ollama, LM Studio) seçebilirsin; o zaman botlar kendi dillerinde de konuşur.')),
    h('div', { style: { marginTop: '6px' } }, T('Bilgisayarın kaldırmıyorsa Normal kip de çok gelişmiş bir bot deneyimi verir: botlar yine kişiliklerine göre karar verir, gelişir, klan kurar ve kalıplarla sohbet eder.')),
    wizard ? h('div', { class: 'small muted', style: { marginTop: '6px' } }, T('Modeli paket oluşturulduktan sonra Gelişmiş sekmesinden kurup test edeceksin.')) : null));
}

function btNumber(value, onchange, { min = 0, max = 999, step = 1, cls = 'num' } = {}) {
  return h('input', { class: 'input ' + cls, type: 'number', value: value, min, max, step, onchange: e => {
    let v = Number(e.target.value); if (!isFinite(v)) v = min; v = Math.max(min, Math.min(max, v)); e.target.value = v; onchange(v); } });
}
function btSlider(value, onchange, { min, max, step, fmt = v => v }) {
  const tag = h('span', { class: 'bt-value' }, fmt(value));
  // dolgu (panel.css: --p) değerle birlikte: parıltı tutamağı izler
  const paint = el => el.style.setProperty('--p', (100 * (Number(el.value) - min) / ((max - min) || 1)) + '%');
  const r = h('input', { type: 'range', min, max, step, value: value, class: 'bt-range',
    oninput: e => { tag.textContent = fmt(Number(e.target.value)); paint(e.target); }, onchange: e => onchange(Number(e.target.value)) });
  paint(r);
  return h('div', { class: 'row', style: { gap: '10px' } }, r, tag);
}
function btSeg(options, value, onchange) {
  // seçim hemen görünür (yeniden çizim beklemez: Kadro'da yalnız Uygula'dan sonra görünüyordu)
  const el = h('div', { class: 'seg' }, options.map(([v, name]) => h('button', { type: 'button', class: v === value ? 'on' : '', onclick: e => {
    el.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === e.currentTarget)); onchange(v);
  } }, name)));
  return el;
}
// adların ve sohbetin dili (bot/languages/<kod>.json); dil adları kendi dillerinde
const BT_LANGS = [['tr', 'Türkçe'], ['en', 'English'], ['de', 'Deutsch'], ['es', 'Español'], ['fr', 'Français'], ['pl', 'Polski'],
  ['pt', 'Português'], ['ru', 'Русский']];
function btPickLang(value, onchange, mixedName, locked) {
  return h('select', { class: 'input bt-lang', disabled: !!locked, onchange: e => onchange(e.target.value) },
    [['karisik', mixedName]].concat(BT_LANGS).map(([v, name]) => h('option', { value: v, selected: v === value }, name)));
}
// adların kaynağı (panel/botlar.AD_KAYNAKLARI): üretici gerçek sunucuların üslubuyla ya da dostats.info'daki gerçek oyuncular
const BT_NAME_SOURCE_DESCRIPTION = N("Üretilen adlar gerçek sunuculardaki gibi süslüdür (-»Λd«-, ツ, ᵀᴹ). DOStats seçilirse adlar ve klan etiketleri dostats.info'daki gerçek oyunculardan alınır (internet gerekir; yeni eklenen botlara ve baştan üretime).");
function btNameSource(value, onchange) {
  return h('select', { class: 'input', onchange: e => onchange(e.target.value) },
    [['uretim', T('Üretilen')], ['dostats', T('DOStats (gerçek oyuncular)')]].map(([v, name]) => h('option', { value: v, selected: v === value }, name)));
}
// dahili dil modeli yalnız İngilizce; başka bir sağlayıcı seçiliyse Gelişmiş kipte de dil serbest (bot/llm_provider.py)
const btLangLocked = mode => mode === 'gelismis' && !BT.liste?.llm_multilingual;
function btChatLang(mode, value, onchange) {
  return btLangLocked(mode) ? btPickLang('en', () => {}, T('Her bot adının dilinde'), true) : btPickLang(value, onchange, T('Her bot adının dilinde'));
}
function btDistribution(f, onchange) {
  return h('div', { class: 'row bt-distribution', style: { gap: '8px' } }, btCompany.map((x, i) => h('label', { class: 'row', style: { gap: '4px' } },
    badge(x, x.toLowerCase()), btNumber(f[i], v => { f[i] = v; onchange(f); }, { min: 0, max: 100 }))));
}

function btStep3(w, render) {
  if (w.kip === 'basit') return btSimpleSettings(w.ayarlar, () => render(), true);
  return h('div', { class: 'stack', style: { gap: '14px' } },
    field(T('Toplam bot'), btSlider(w.adet, v => { w.adet = v; }, { min: 5, max: 3000, step: 5 }),
      h('div', { class: 'small muted' }, T('Aynı anda hepsi çevrimiçi olmaz: her botun kendi oyun saatleri var. Yüzlerce bot sorun değil; haritanda gemi olarak görünenler sınırlı.'))),
    field(T('Firma dağılımı (oran)'), btDistribution(w.firma_dagilimi, f => { w.firma_dagilimi = f; })),
    field(T('Gelişim'), btSeg([['progressive', 'Progressive'], ['jumpstart', 'Jumpstart']], w.gelisim, v => { w.gelisim = v; render(); }),
      h('div', { class: 'small muted' }, w.gelisim === 'progressive'
        ? T('Herkes oyunun başında olduğu gibi 1. seviyede, Phoenix ile kendi üssünde başlar ve gerçek oyuncu gibi gelişir.')
        : T('Kadro gerçekçi bir dağılımla başlar: çok acemi, çok orta seviye, az güçlü oyuncu. Donanımları, paraları ve seviyeleri tutarlı.'))),
    w.gelisim === 'jumpstart' ? field(T('Ortalama oyun süresi (saat)'), btSlider(w.ayarlar.jumpstart_saat, v => { w.ayarlar.jumpstart_saat = v; }, { min: 5, max: 500, step: 5 })) : null,
    field(T('Adların dili'), btPickLang(w.ad_dili, v => { w.ad_dili = v; }, T('Karışık')),
      h('div', { class: 'small muted' }, T('Botların kullanıcı adları bu dilin oyuncularına benzer.'))),
    field(T('Ad kaynağı'), btNameSource(w.ad_kaynagi, v => { w.ad_kaynagi = v; }),
      h('div', { class: 'small muted' }, T(BT_NAME_SOURCE_DESCRIPTION))),
    field(T('Sohbet dili'), btChatLang(w.kip, w.dil, v => { w.dil = v; }),
      h('div', { class: 'small muted' }, btLangLocked(w.kip) ? T('Gelişmiş kipte botlar yalnız İngilizce konuşur (dil modeli öteki dillerde zayıf).')
        : T('Botların sohbette kullandığı dil. "Her bot adının dilinde" seçilirse adı Almanca olan Almanca konuşur.'))),
    field(T('Kendi botların (isteğe bağlı)'), btCustomField(w.ozel, v => { w.ozel = v; })));
}

// kullanıcının kendi botları (panel/botlar.ozel_cozumle): satır başına "ad, firma, davranış, dil"; ad dışındakiler isteğe bağlı
function btCustomField(value, onchange) {
  return h('div', { class: 'stack', style: { gap: '6px' } },
    h('textarea', { class: 'input bt-custom', rows: 5, spellcheck: false, placeholder: 'Kaan\nStarHunter, VRU\nOldMiner, MMO, kasici, tr\nRedBaron, EIC, avci', oninput: e => onchange(e.target.value) }, value || ''),
    h('div', { class: 'small muted' }, T('Satır başına bir bot: ad, sonra isteğe bağlı firma (MMO, EIC, VRU), davranış ({0}) ve sohbet dili ({1}). Verilmeyenler ve kalan botlar her zamanki gibi üretilir.',
      Object.keys(BT_ARCHETYPE).join(', '), BT_LANGS.map(d => d[0]).join(', '))));
}

function btSimpleSettings(a, render, wizard = false, save = null) {
  const top = () => Object.entries(a.basit_haritalar).reduce((s, [k, v]) => s + v * (k === '4-X' ? 4 : ['4-5'].includes(k) ? 1 : 3), 0);
  const total = h('b', null, top());
  const parent = h('div', { class: 'bt-classes' }, (BT.liste?.classes || Object.keys(a.basit_haritalar)).map(s => h('label', { class: 'bt-class' },
    h('span', null, BT_CLASS_NAME(s)), btNumber(a.basit_haritalar[s] ?? 0, v => { a.basit_haritalar[s] = v; total.textContent = top(); save && save(); }, { min: 0, max: 20 }))));
  return h('div', { class: 'stack', style: { gap: '14px' } },
    field(T('Harita başına bot'), parent, h('div', { class: 'small muted' }, T('Firma haritalarında her firmanın haritasına ayrı ayrı (X-3 = 1-3, 2-3, 3-3), ortak haritalara (4-1…4-5) bir kez. Toplam: '), total)),
    field(T('Güç oranı'), btSlider(a.basit_guc, v => { a.basit_guc = v; save && save(); }, { min: 0.3, max: 3, step: 0.1, fmt: v => '×' + v.toFixed(1) }),
      h('div', { class: 'small muted' }, T('Haritanın tipik oyuncusunun donanımına göre: 1 aynı, 2 iki kat güçlü, 0,5 zayıf.'))),
    field(T('Dost bot payı'), btSlider(a.basit_dost, v => { a.basit_dost = v; save && save(); }, { min: 0, max: 1, step: 0.05, fmt: v => '%' + Math.round(v * 100) }),
      h('div', { class: 'small muted' }, T('Firma haritasındaki botların ne kadarı haritanın firmasından (geri kalanı düşman).'))));
}

// ================================================================== EDİTÖR
const BT_TABS = [
  ['genel', N('Genel'), 'sliders'], ['kadro', N('Kadro'), 'users'], ['davranis', N('Davranış'), 'target'], ['erisim', N('Erişimler'), 'shield'],
  ['sohbet', N('Sohbet'), 'chat'], ['klanlar', N('Klanlar'), 'star'], ['basit', N('Basit kip'), 'bot'], ['gelismis', N('Gelişmiş kip'), 'brain'],
];

async function btEditor() {
  const [d] = await Promise.all([act(() => api('/api/bot?id=' + encodeURIComponent(BT.pid))), loadGameImages()]);   // oyunun görselleri: gemi, rütbe
  if (!d || S.page !== 'botlar') return;
  BT.d = d;
  const tabs = BT_TABS.filter(([k]) => (k !== 'basit' || d.kip === 'basit') && (k !== 'gelismis' || d.kip === 'gelismis')
    && (d.kip !== 'basit' || !['davranis', 'sohbet'].includes(k)));
  if (!tabs.some(([k]) => k === BT.sekme)) BT.sekme = 'genel';
  btFill($('#content'), h('div', { class: 'stack' },
    h('div', { class: 'card bt-bar' }, btn('', () => { BT.pid = null; renderBots(); }, 'ghost icon', 'arrowL', { title: T('Bot paketleri') }),
      btArt('bot_kip_' + d.kip, 'dron_editor', 'bt-bar-art'),
      h('div', { class: 'bt-bar-name' }, h('div', { class: 'row', style: { gap: '8px' } }, h('b', null, d.ad), badge(T(BT_MODES[d.kip].ad), 'orange'),
        d.dunya ? badge([icon('globe'), btWorldName(d.dunya)], 'info') : badge(T('Dünyaya atanmadı'), 'warn')),
        h('div', { class: 'muted small ellipsis' }, T('{0} bot', d.adet) + (d.level_avg != null ? ' · ' + T('ortalama seviye {0}', d.level_avg) : ''))),
      h('span', { class: 'spacer' }), h('span', { class: 'we-save-status', id: 'bt-kayit' }),
      btn(T('Dünyaya ata'), ev => btAssignMenu(ev.currentTarget, d), 'sm', 'globe'),
      btn('', ev => btPackMenu(ev.currentTarget, d), 'sm ghost icon', 'more', { title: T('Diğer') })),
    d.server_in_pack ? h('div', { class: 'alert ' + (d.restart_needed ? 'uyari' : 'bilgi') }, icon(d.restart_needed ? 'alert' : 'info'),
      h('div', null, d.restart_needed ? T('Paket oyun açıldıktan sonra değişti: değişiklikler sunucu yeniden başlayınca geçerli olur.')
        : T('Bu paket şu an oyunda çalışıyor. Kadro listesi sunucunun dakikalık kaydından.')),
      d.restart_needed ? btn(T('Sunucuyu yeniden başlat'), () => act(() => api('/api/bot/server_restart', {}), T('Sunucu yeniden başlatılıyor.')).then(() => setTimeout(btEditor, 1500)), 'sm orange', 'refresh') : null) : null,
    h('div', { class: 'seg bt-tabs' }, tabs.map(([k, name, iconEl]) => h('button', { type: 'button', class: BT.sekme === k ? 'on' : '',
      onclick: () => { BT.sekme = k; btEditor(); } }, icon(iconEl), T(name)))),
    h('div', { id: 'bt-alan' }, ({ genel: btGeneral, kadro: btRoster, davranis: btBehavior, erisim: btAccess, sohbet: btChat, klanlar: btClans, basit: btSimple, gelismis: btAdvanced })[BT.sekme](d))));
}

function btSaveStatus(state) {
  const el = $('#bt-kayit'); if (!el) return;
  el.className = 'we-save-status ' + state;
  btFill(el, ...(state === 'kaydediliyor' ? [h('span', { class: 'spin' }), T('Kaydediliyor…')] : state === 'kaydedildi' ? [icon('check'), T('Kaydedildi')] : []));
}
// değişiklik: 450 ms bekleyip tek istekte (ayarlar birleştirilir)
function btPatch(fields) {
  for (const [k, v] of Object.entries(fields)) {
    if (k === 'ayarlar') BT.bekleyen.ayarlar = Object.assign(BT.bekleyen.ayarlar || {}, v);
    else BT.bekleyen[k] = v;
  }
  btSaveStatus('kaydediliyor');
  clearTimeout(BT.timer);
  BT.timer = setTimeout(async () => {
    const body = Object.assign({ id: BT.pid }, BT.bekleyen); BT.bekleyen = {};
    const x = await act(() => api('/api/bot/update', body));
    if (!x) return btSaveStatus('');
    const mode = BT.d.kip;
    BT.d = x; btSaveStatus('kaydedildi');
    if (body.kip && body.kip !== mode || body.ad) btEditor();
  }, 450);
}
const btSetting = (k, v) => btPatch({ ayarlar: { [k]: v } });

function btRow(name, description, ctl) {
  return h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, name), description ? h('div', { class: 'help' }, description) : null), h('div', { class: 'ctl' }, ctl));
}
function btKey(value, onchange) {
  return h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: !!value, onchange: e => onchange(e.target.checked) }), h('span'));
}

// ------------------------------------------------------------------ Genel
function btGeneral(d) {
  const a = d.ayarlar;
  const name = h('input', { class: 'input', value: d.ad, maxlength: 40, onchange: e => btPatch({ ad: e.target.value }) });
  const is_open = h('input', { class: 'input', value: d.aciklama || '', maxlength: 240, placeholder: T('Açıklama yok.'), onchange: e => btPatch({ aciklama: e.target.value }) });
  const pickMode = async v => {
    if (v === d.kip) return;
    if (v === 'gelismis' && !await confirmBox(T('Gelişmiş kipe geçilsin mi?'), btLlmWarning(), { ok: T('Gelişmiş kipe geç') })) return;
    if ((v === 'basit') !== (d.kip === 'basit') && !await confirmBox(T('Kip değişsin mi?'),
      T('Basit kipte kadro haritalara dağıtılır ve sayısı harita ayarlarından gelir; Normal ve Gelişmiş kipte botlar kendi başına gelişir. İlerleme korunur.'))) return;
    btPatch({ kip: v });
  };
  const fg = a.firma_guc || [1, 1, 1];
  return h('div', { class: 'stack' },
    h('div', { class: 'card' }, h('h2', null, icon('edit'), T('Paket')),
      btRow(T('Ad'), null, name), btRow(T('Açıklama'), null, is_open),
      btRow(T('Kip'), T(BT_MODES[d.kip].ozet), btSeg(['basit', 'normal', 'gelismis'].map(k => [k, T(BT_MODES[k].ad)]), d.kip, pickMode)),
      d.kip !== 'basit' ? btRow(T('Gelişim'), d.gelisim === 'jumpstart' ? T('Kadro gerçekçi bir dağılımla başlar (ilk açılışta).') : T('Herkes 1. seviyede, kendi üssünde başlar.'),
        btSeg([['progressive', 'Progressive'], ['jumpstart', 'Jumpstart']], d.gelisim, v => btPatch({ gelisim: v }))) : null,
      d.kip !== 'basit' && d.gelisim === 'jumpstart' ? btRow(T('Ortalama oyun süresi (saat)'), T('Jumpstart dağılımının ortası: birkaç bot bunun katlarıyla, çoğu altında başlar.'),
        btNumber(a.jumpstart_saat, v => btSetting('jumpstart_saat', v), { min: 1, max: 2000 })) : null),
    d.kip !== 'basit' ? h('div', { class: 'card' }, h('h2', null, icon('clock'), T('Zaman ve gelişim')),
      btRow(T('İlerleme hızı'), T('Kazançların çarpanı: 1 gerçek oyuncu temposu.'), btSlider(a.hiz, v => btSetting('hiz', v), { min: 0.1, max: 10, step: 0.1, fmt: v => '×' + v.toFixed(1) })),
      btRow(T('Çevrimiçi olma eğilimi'), T('Botların oyun saatlerine göre çevrimiçi olma isteği; yüksekse aynı anda daha çok bot.'),
        btSlider(a.cevrimici_oran, v => btSetting('cevrimici_oran', v), { min: 0.05, max: 2, step: 0.05, fmt: v => '%' + Math.round(v * 100) })),
      btRow(T('Aynı anda en çok çevrimiçi'), T('0: sınırsız.'), btNumber(a.en_cok_cevrimici, v => btSetting('en_cok_cevrimici', v), { min: 0, max: 3000 })),
      btRow(T('Sen yokken ilerleme (saat)'), T('Oyuna dönünce geçen sürenin en çok bu kadarı benzetilir. 0: botlar yalnız sen oynarken ilerler.'),
        btNumber(a.telafi_saat, v => btSetting('telafi_saat', v), { min: 0, max: 48 })),
      d.gelisim !== 'jumpstart' ? btRow(T('Yeni pilot kaydı (saniye)'), T('Progressive: her firmaya ortalama bu kadar saniyede bir yeni pilot kayıt olup oyuna başlar (yeni açılmış bir sunucu gibi; hepsi aynı anda doğmaz). 0: hepsi baştan kayıtlı.'),
        btNumber(a.kayit_sn ?? 15, v => btSetting('kayit_sn', v), { min: 0, max: 300 })) : null,
      btRow(T('Firmaların gücü'), T('Firmanın botlarının gelişim çarpanı (1 eşit).'), h('div', { class: 'row', style: { gap: '8px' } }, btCompany.map((x, i) =>
        h('label', { class: 'row', style: { gap: '4px' } }, badge(x, x.toLowerCase()), btNumber(fg[i], v => { fg[i] = v; btSetting('firma_guc', fg); }, { min: 0.2, max: 5, step: 0.1 })))))) : null,
    btGameSettingCard(d),
    h('div', { class: 'card' }, h('h2', null, icon('trash'), T('İlerleme')),
      btRow(T('İlerlemeyi sıfırla'), T('Botların seviyesi, parası, donanımı, klanları ve ilişkileri silinir; adlar ve kişilikler kalır.'),
        btn(T('Sıfırla'), async () => {
          if (!await confirmBox(T('İlerleme sıfırlansın mı?'), T('Botlar baştan başlar (Jumpstart\'ta yeniden dağıtılır).'), { ok: T('Sıfırla'), danger: true })) return;
          const x = await act(() => api('/api/bot/sifirla', { id: d.id }), T('İlerleme sıfırlandı.')); if (x) { BT.d = x; btEditor(); }
        }, 'sm danger', 'trash'))));
}

// ------------------------------------------------------------------ Kadro
function btRoster(d) {
  const byArchetype = {};
  d.kadro.forEach(b => { byArchetype[b.arketip] = (byArchetype[b.arketip] || 0) + 1; });
  const f = d.firma_dagilimi.slice();
  let count = d.adet, lang = d.dil || 'karisik', nameLang = d.ad_dili || lang, nameSource = d.ad_kaynagi || 'uretim', special = '';
  const control = d.kip === 'basit' ? h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Basit kipte bot sayısı Basit kip sekmesindeki harita sayılarından gelir.')))
    : h('div', { class: 'stack', style: { gap: '10px' } },
      btRow(T('Bot sayısı'), T('Artırınca yeni botlar eklenir, azaltınca sondakiler çıkar; var olanlar değişmez.'), btNumber(count, v => { count = v; }, { min: 1, max: 3000 })),
      btRow(T('Firma dağılımı (oran)'), T('Yeni eklenen botlara ve baştan üretime uygulanır.'), btDistribution(f, x => { f.splice(0, 3, ...x); })),
      btRow(T('Adların dili'), T('Yeni eklenen botlara ve baştan üretime uygulanır; var olan botların adı değişmez.'),
        btPickLang(nameLang, v => { nameLang = v; }, T('Karışık'))),
      btRow(T('Ad kaynağı'), T(BT_NAME_SOURCE_DESCRIPTION), btNameSource(nameSource, v => { nameSource = v; })),
      btRow(T('Sohbet dili'), btLangLocked(d.kip) ? T('Gelişmiş kipte botlar yalnız İngilizce konuşur (dil modeli öteki dillerde zayıf).')
        : T('Uygula ile bütün botlar bu dilde konuşur.'), btChatLang(d.kip, lang, v => { lang = v; })),
      field(T('Kendi botların'), btCustomField('', v => { special = v; }), h('div', { class: 'small muted' }, T('Uygula: kadroda olmayan adlar yeni bot olarak eklenir. Baştan üret: kadronun başında olurlar.'))),
      h('div', { class: 'row wrap', style: { justifyContent: 'flex-end' } },
        btn(T('Uygula'), async () => { const x = await act(() => api('/api/bot/kadro', { id: d.id, count, firma_dagilimi: f, lang, ad_dili: nameLang, ad_kaynagi: nameSource, special }), T('Kadro güncellendi.')); if (x) { BT.d = x; btEditor(); } }, 'sm primary', 'check'),
        btn(T('Baştan üret'), async () => {
          if (!await confirmBox(T('Kadro baştan üretilsin mi?'), T('Bütün botlar yeni adlar ve kişiliklerle yeniden üretilir, ilerlemeleri silinir.'), { ok: T('Baştan üret'), danger: true })) return;
          const x = await act(() => api('/api/bot/kadro', { id: d.id, count, firma_dagilimi: f, lang, ad_dili: nameLang, ad_kaynagi: nameSource, special, yeniden: true }), T('Kadro yeniden üretildi.')); if (x) { BT.d = x; btEditor(); }
        }, 'sm danger', 'refresh')));
  return h('div', { class: 'stack' },
    h('div', { class: 'card' }, h('h2', null, icon('users'), T('Kadro')),
      h('p', { class: 'desc' }, T('Kişilikler kadro üretilirken bir kez belirlendi: her botun arketipi, özellikleri (saldırganlık, sabır, sosyallik …), oyun saatleri ve yazım üslubu kendine.')),
      h('div', { class: 'row wrap', style: { gap: '6px', marginBottom: '12px' } }, Object.entries(byArchetype).sort((a, b) => b[1] - a[1]).map(([k, n]) => badge(T(BT_ARCHETYPE[k] || k) + ' ' + n, ''))),
      control),
    h('div', { class: 'card' }, h('h2', null, icon('list'), T('Botlar')),
      h('p', { class: 'desc' }, d.has_state ? T('Seviye, gemi, harita ve iş sunucunun son kaydından (oyun açıkken dakikada bir). Satıra tıklayınca botun editörü açılır.') : T('Botlar henüz oynamadı: bu dünyada oyuna girince başlarlar.')),
      btRosterTable(d.kadro)));
}

// Kadro tablosu: ada göre arama, firma ve kişilik süzgeci, sıralama (oyuncu isteği 2026-10-30). Sıralanan değer hep tabloda görünür:
// kendi sütunu yoksa (EP, onur, kredi …) Seviye'nin yanında vurgulu bir sütun açılır. # süzülmüş ve sıralanmış listedeki yerdir.
const BT_SORT = [['ad', N('Pilot')], ['seviye', N('Seviye')], ['rutbe', N('Rütbe')], ['gemi', N('Gemi')], ['harita', N('Harita')], ['hedef', N('Ne yapıyor')],
  ['npc', N('Uzaylı')], ['oyuncu', N('Oyuncu')], ['olum', N('Ölüm')]];
const BT_SORT_EXTRA = [['ep', N('Deneyim (EP)')], ['onur', N('Onur')], ['kredi', N('Kredi')], ['uridyum', N('Uridyum')], ['kapi', N('Biten galaksi kapısı')],
  ['firma', N('Firma')], ['arketip', N('Kişilik')]];
const BT_SORT_VALUE = { npc: b => b.istat.npc || 0, oyuncu: b => b.istat.oyuncu || 0, olum: b => b.istat.olum || 0, kapi: b => b.istat.kapi_tamam || 0,
  harita: b => b.harita_ad || '', gemi: b => btShipName(b.gemi) };
const BT_SORT_TEXT = ['ad', 'gemi', 'harita', 'hedef', 'arketip', 'firma'];
const BT_SORT_NUMBER = new Set(['seviye', 'rutbe', 'npc', 'oyuncu', 'olum', 'ep', 'onur', 'kredi', 'uridyum', 'kapi']);
const BT_CURRENCY = { ep: 'deneyim', onur: 'onur', kredi: 'kredi', uridyum: 'uridyum' };
const btShipName = l => String(l || '').replace('ship_', '').replace(/^\w/, c => c.toUpperCase());
const btRank = (r, size) => GI.index?.sprite['rank' + r] ? h('span', { class: 'bt-rank', title: T('Rütbe {0}', r) }, sprite('rank' + r, size)) : h('span', null, r);
function btRosterTable(roster) {
  const s = BT.rosterFilter = BT.rosterFilter || { ara: '', firma: 0, arketip: '', ozel: false, sira: 'no', ters: false };
  const table = h('table', { class: 'table bt-roster' }), counter = h('span', { class: 'bt-counter' });
  const value = (b, k) => BT_SORT_VALUE[k] ? BT_SORT_VALUE[k](b) : k === 'no' ? b.no : b[k] ?? '';
  const highlight = () => BT_SORT_EXTRA.find(([k]) => k === s.sira && BT_SORT_NUMBER.has(k));       // sıralanan değerin kendi sütunu yok
  const sortBy = k => { if (s.sira === k) s.ters = !s.ters; else { s.sira = k; s.ters = !BT_SORT_TEXT.includes(k); } render(); };
  const cell = (b, k) => {
    const f = btCompany[b.firma - 1], n = value(b, k);
    if (k === 'ad') return h('div', { class: 'bt-pilot' },
      h('div', { class: 'bt-pilot-name' }, h('a', { href: '#', class: 'bt-name', onclick: e => e.preventDefault() }, b.ad),
        b.ozel ? h('span', { class: 'badge info bt-custom-badge', title: T('Kendi eklediğin bot') }, T('Özel')) : null),
      h('div', { class: 'bt-pilot-sub' }, h('span', { class: 'bt-company-label' }, f), T(BT_ARCHETYPE[b.arketip] || b.arketip),
        h('span', { class: 'dim' }, btTraitSummary(b.ozellik))));
    if (k === 'seviye') return h('b', { class: 'bt-lv' }, n);
    if (k === 'rutbe') return btRank(n || 1, 22);
    if (k === 'gemi') return h('div', { class: 'bt-ship' }, shipImage(b.gemi, 30, f.toLowerCase()), h('span', null, n));
    if (k === 'harita') return n || h('span', { class: 'dim' }, '—');
    if (k === 'hedef') return [b.hedef ? h('span', { class: 'bt-activity' }, T(BT_TARGET[b.hedef] || b.hedef)) : h('span', { class: 'dim' }, '—'), btAgentTrace(b)];
    if (BT_CURRENCY[k]) return h('span', { class: 'bt-resource' }, art('kaynak_' + BT_CURRENCY[k], 'bt-resource-icon'), fmtN(n));
    return n ? fmtN(n) : h('span', { class: 'dim' }, '0');
  };
  const render = () => {
    const search = s.ara.trim().toLocaleLowerCase(LOC());
    const entries = roster.filter(b => (!search || b.ad.toLocaleLowerCase(LOC()).includes(search)) && (!s.firma || b.firma === s.firma)
      && (!s.arketip || b.arketip === s.arketip) && (!s.ozel || b.ozel));
    const direction = s.ters ? -1 : 1, text = BT_SORT_TEXT.includes(s.sira);
    entries.sort((a, b) => { const x = value(a, s.sira), y = value(b, s.sira);
      return direction * (text ? String(x).localeCompare(String(y), LOC(), { numeric: true }) : (Number(x) || 0) - (Number(y) || 0)) || a.no - b.no; });
    const column = BT_SORT.slice();
    if (highlight()) column.splice(2, 0, highlight());
    const klass = k => [BT_SORT_NUMBER.has(k) ? 'num' : '', k === s.sira ? 'on' : '', highlight()?.[0] === k ? 'isik' : '', 'k-' + k].join(' ');
    table.replaceChildren(
      h('thead', null, h('tr', null, h('th', { class: 'num bt-row-no' }, '#'), column.map(([k, name]) => h('th', { class: 'bt-sorted ' + klass(k), title: T('Sıralamak için tıkla'),
        onclick: () => sortBy(k) }, T(name), icon(k === s.sira && s.ters ? 'asagi' : 'yukari'))))),
      h('tbody', null, entries.length ? entries.map((b, i) => h('tr', { class: 'f-' + btCompany[b.firma - 1].toLowerCase(), onclick: () => btBotDetail(b.no) },
        h('td', { class: 'num bt-row-no' }, i + 1), column.map(([k]) => h('td', { class: klass(k) }, cell(b, k)))))
        : h('tr', null, h('td', { colspan: column.length + 1, class: 'bt-empty' }, T('Süzgece uyan bot yok.')))));
    counter.textContent = T('{0} / {1} bot', entries.length, roster.length);
    firmaSec.querySelectorAll('button').forEach((x, i) => x.classList.toggle('on', i === s.firma));
    sortSelect.value = s.sira;
    directionBtn.replaceChildren(icon(s.ters ? 'asagi' : 'yukari'));
    directionBtn.title = s.ters ? T('Azalan: tıkla, artan olsun') : T('Artan: tıkla, azalan olsun');
  };
  const choice = (value, options, on) => h('select', { class: 'input', onchange: e => { on(e.target.value); render(); } },
    options.map(([v, name]) => h('option', { value: v, selected: String(v) === String(value) }, name)));
  const firmaSec = h('div', { class: 'seg bt-company-pick' }, [T('Hepsi'), ...btCompany].map((name, i) =>
    h('button', { type: 'button', class: i ? 'f-' + name.toLowerCase() : '', onclick: () => { s.firma = i; render(); } }, name)));
  const sortSelect = choice(s.sira, [['no', T('Kadro sırası')]].concat(BT_SORT.concat(BT_SORT_EXTRA).map(([k, name]) => [k, T(name)])), v => {
    s.sira = v; s.ters = !BT_SORT_TEXT.includes(v) && v !== 'no'; });
  const directionBtn = btn('', () => { s.ters = !s.ters; render(); }, 'ghost icon');
  const tool = h('div', { class: 'bt-filter' },
    h('label', { class: 'bt-search' }, icon('search'), h('input', { class: 'input', type: 'search', placeholder: T('Ada göre ara'), value: s.ara,
      oninput: e => { s.ara = e.target.value; render(); } })),
    firmaSec,
    choice(s.arketip, [['', T('Bütün kişilikler')]].concat(Object.entries(BT_ARCHETYPE).map(([k, name]) => [k, T(name)])), v => { s.arketip = v; }),
    h('div', { class: 'bt-sort' }, h('span', { class: 'small muted' }, T('Sırala')), sortSelect, directionBtn),
    h('label', { class: 'row small bt-custom-toggle' }, btKey(s.ozel, v => { s.ozel = v; render(); }), T('Yalnız kendi botların')),
    h('span', { class: 'spacer' }), counter);
  render();
  return h('div', null, tool, h('div', { class: 'bt-table' }, table));
}

const BT_TRAIT = { saldirganlik: N('saldırgan'), rekabet: N('rekabetçi'), sosyallik: N('sosyal'), sabir: N('sabırlı'), risk: N('riskçi'), sadakat: N('sadık'),
  yardimseverlik: N('yardımsever'), konuskanlik: N('konuşkan'), tutumluluk: N('tutumlu'), hirs: N('hırslı') };
function btTraitSummary(o) {
  const en = Object.entries(o || {}).sort((a, b) => b[1] - a[1]).slice(0, 2);
  return en.map(([k]) => T(BT_TRAIT[k] || k)).join(', ');
}

// ------------------------------------------------------------------ Davranış, Erişimler, Sohbet
function btBehavior(d) {
  const a = d.ayarlar;
  return h('div', { class: 'card' }, h('h2', null, icon('target'), T('Davranış')),
    btRow(T('PvP için en düşük seviye'), T('Bu seviyenin altındaki botlar PvP avına çıkmaz.'), btNumber(a.pvp_seviye, v => btSetting('pvp_seviye', v), { min: 1, max: 32 })),
    btRow(T('Başka firmanın haritaları'), T('Botlar düşman firmaların haritalarına girebilir.'), btKey(a.yabanci_harita, v => btSetting('yabanci_harita', v))),
    btRow(T('Haritanda gemi olarak en çok'), T('Bulunduğun haritadaki botlardan en çok bu kadarı gemi olarak görünür; ötekiler arka planda oynar (performans).'),
      btNumber(a.somut_en_cok, v => btSetting('somut_en_cok', v), { min: 1, max: 150 })),
    btRow(T('Kaç bota bir bot klanı'), T('Botların kurabileceği klan sayısı kadroya göre.'), btNumber(a.klan_basina, v => btSetting('klan_basina', v), { min: 3, max: 100 })),
    btRow(T('Yardım çağrısına en çok'), T('Sohbetteki bir yardım çağrısına gelen en çok bot.'), btNumber(a.yardim_en_cok, v => btSetting('yardim_en_cok', v), { min: 0, max: 20 })),
    h('h3', null, T('Yoğun saat (prime time)')),
    btRow(T('Başlangıç ve bitiş saati'), T('Akşamın yoğun saatleri (bilgisayarının saatiyle): daha çok bot çevrimiçi olur ve PvP canlanır. Başlangıç bitişe eşitse yoğun saat yok.'),
      h('div', { class: 'row', style: { gap: '6px' } }, btNumber(a.prime_baslangic, v => btSetting('prime_baslangic', v), { min: 0, max: 23 }), h('span', null, '–'),
        btNumber(a.prime_bitis, v => btSetting('prime_bitis', v), { min: 0, max: 23 }))),
    btRow(T('Yoğun saatte PvP isteği'), T('PvP avına çıkma isteğinin çarpanı (1: fark yok).'),
      btSlider(a.prime_pvp, v => btSetting('prime_pvp', v), { min: 1, max: 5, step: 0.5, fmt: v => 'x' + v })),
    btRow(T('Büyük savaşlar'), T('Yoğun saatte üç firmanın PvP botları her saat değişen bir cephe haritasında (4-4, 4-5, 4-1/2/3) toplanır. Haritanda gemi olarak görünen sayıyı artırırsan savaş büyür.'),
      btKey(a.buyuk_savas, v => btSetting('buyuk_savas', v))));
}

function btAccess(d) {
  const trace = Object.assign({}, d.ayarlar.izinler);
  const permissions = (BT.liste?.izinler || Object.keys(BT_PERMS)).filter(k => d.kip !== 'basit' || ['pvp', 'oyuncuya_saldir'].includes(k));
  return h('div', { class: 'card' }, h('h2', null, icon('shield'), T('Erişimler')),
    h('p', { class: 'desc' }, T('Botların oyunun hangi bölümlerini kullanacağı. Kapatılan bölümü hiçbir bot kullanmaz.')),
    permissions.map(k => btRow(T(BT_PERMS[k][0]), T(BT_PERMS[k][1]), btKey(trace[k] !== false, v => { trace[k] = v; btSetting('izinler', { [k]: v }); }))));
}

function btChat(d) {
  const a = d.ayarlar;
  return h('div', null, h('div', { class: 'card' }, h('h2', null, icon('chat'), T('Sohbet')),
    btRow(T('Laf atma'), T('Botların sataşma düzeyi: Kapalı (hep kibar), Hafif, Sert (öldürünce globalde laf atar, sataşmaya sert karşılık), Çok sert (düşman firmaya ve sana sık sık laf atar). Küfür ve gerçek tehdit hiçbirinde yok.'),
      btSeg([[0, T('Kapalı')], [1, T('Hafif')], [2, T('Sert')], [3, T('Çok sert')]], a.kaba_sohbet, v => btSetting('kaba_sohbet', v))),
    btRow(T('Sohbet'), T(BT_PERMS.sohbet[1]), btKey(a.izinler.sohbet !== false, v => btSetting('izinler', { sohbet: v }))),
    btRow(T('Kanal yoğunluğu'), T('Global ve firma sohbetinde dakikada en çok bot satırı (sohbet sele dönmesin).'),
      btSlider(a.sohbet_dk, v => btSetting('sohbet_dk', v), { min: 0, max: 30, step: 1, fmt: v => T('{0}/dk', v) })),
    h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, d.kip === 'gelismis'
      ? T('Gelişmiş kipte botlar dil modeliyle konuşur; model yetişemezse kalıp cümlelere döner.')
      : T('Normal kipte botlar duruma ve kişiliklerine göre kalıp cümlelerle konuşur: selamlaşır, seviye atlayınca yazar, yardım çağrılarına ve fısıltına yanıt verir.')))),
    btModeration(d));
}

// bot klanları (bot/clan_management.py, bot/clan_stations.py): logo (Orders.md OP-017; yoksa etiket), lider, kasa, bütçe, istasyon, diplomasi
const BT_DIPLOMACY = { 1: N('ittifak'), 2: N('saldırmazlık'), 3: N('savaş') };
function btClanLogo(k) {
  if (!k.logo) return h('div', { class: 'bt-clan-logo bos' }, String(k.etiket || '?').slice(0, 4));
  const im = h('img', { class: 'bt-clan-logo', src: 'images/klan_logo/' + k.logo + '.webp', alt: '' });
  im.onerror = () => im.replaceWith(btClanLogo({ etiket: k.etiket }));
  return im;
}
function btClans(d) {
  const clans = d.klanlar || [];
  const card = k => h('div', { class: 'bt-clan' }, btClanLogo(k),
    h('div', { class: 'bt-clan-body' },
      h('div', { class: 'bt-clan-name' }, h('b', null, '[' + k.etiket + '] ' + k.ad), badge(T('{0} üye', k.uye), '')),
      h('div', { class: 'small muted' }, [T('Lider: {0}', k.lider), T('Kasa: {0} kredi', fmtN(k.kasa)), T('Vergi: %{0}', k.vergi)].join(' · ')),
      k.butce ? h('div', { class: 'small muted' }, T('Bütçe: istasyon %{0}, ödeme %{1}, savaş %{2}', ...['ksi', 'odeme', 'savas'].map(a => Math.round(100 * (k.butce[a] || 0))))) : null,
      k.rutbeler.length ? h('div', { class: 'small muted' }, T('Rütbeler: {0}', k.rutbeler.join(', '))) : null,
      h('div', { class: 'small' }, k.istasyonlar.length ? T('İstasyon: {0}', k.istasyonlar.join(', ')) : k.yaris ? T('İstasyon yarışında: {0}', k.yaris) : T('İstasyonu yok')),
      k.diplomasi.length ? h('div', { class: 'small muted' }, k.diplomasi.map(x => T(BT_DIPLOMACY[x.tur] || '?') + ': ' + x.ad).join(' · ')) : null,
      k.haberler.length ? h('div', { class: 'small muted bt-clan-news' }, '“' + k.haberler[0] + '”') : null));
  return h('div', { class: 'stack' }, h('div', { class: 'card' }, h('h2', null, icon('star'), T('Klanlar')),
    h('p', { class: 'desc' }, T('Botların kurduğu ve üye olduğu klanlar (sunucunun son kaydından). Liderler rütbeleri, açıklamayı, duyuruları, vergiyi, kasanın bütçesini ve Klan Savaş İstasyonlarını kendileri yönetir.')),
    clans.length ? h('div', { class: 'bt-clans' }, clans.map(card))
      : h('div', { class: 'small muted' }, T('Henüz bot klanı yok: lider ruhlu botlar seviye ve para biriktirince kurar.'))));
}

// sohbet moderatörleri (bot/moderation.py): kuralı çiğneyen önce uyarılır, sonra susturulur, sonra yasaklanır
function btModeration(d) {
  const a = d.ayarlar;
  return h('div', { class: 'card' }, h('h2', null, icon('shield'), T('Sohbet moderatörleri')),
    h('p', { class: 'desc' }, T('Sakin, sabırlı birkaç bot sohbet moderatörü olur (adları moderatör renginde). Kuralı çiğneyen (sen ya da botlar) önce uyarılır, yine çiğnerse susturulur, çok susturulan sohbetten yasaklanır. Yalnız global ve firma sohbeti; kararı çevrimiçi bir moderatör verir.')),
    btRow(T('Moderatörler'), T('Açıkken moderatör botlar kuralları uygular.'), btKey(a.moderator, v => btSetting('moderator', v))),
    btRow(T('Moderatör sayısı'), T('Kadrodan seçilen moderatör bot sayısı.'), btNumber(a.mod_sayisi, v => btSetting('mod_sayisi', v), { min: 1, max: 10 })),
    btRow(T('BÜYÜK HARF yasak'), T('Çoğu büyük harfle yazılmış mesaj.'), btKey(a.kural_buyuk, v => btSetting('kural_buyuk', v))),
    btRow(T('Spam yasak'), T('Aynı mesajı üç kez ya da 10 saniyede beş mesaj.'), btKey(a.kural_sel, v => btSetting('kural_sel', v))),
    btRow(T('Hakaret yasak'), T('Hakaret ve zararlı sözler.'), btKey(a.kural_hakaret, v => btSetting('kural_hakaret', v))),
    btRow(T('Reklam yasak'), T('Bağlantılar ve reklam.'), btKey(a.kural_reklam, v => btSetting('kural_reklam', v))),
    btRow(T('Susturma süresi (dk)'), null, btNumber(a.sustur_dk, v => btSetting('sustur_dk', v), { min: 1, max: 1440 })),
    btRow(T('Kaç susturmada yasak'), null, btNumber(a.yasak_esik, v => btSetting('yasak_esik', v), { min: 1, max: 10 })),
    btRow(T('Yasak süresi (saat)'), null, btNumber(a.yasak_saat, v => btSetting('yasak_saat', v), { min: 1, max: 720 })));
}

function btSimple(d) {
  const a = JSON.parse(JSON.stringify(d.ayarlar));
  const save = () => btPatch({ ayarlar: { basit_haritalar: a.basit_haritalar, basit_guc: a.basit_guc, basit_dost: a.basit_dost } });
  return h('div', { class: 'card' }, h('h2', null, icon('bot'), T('Basit kip')),
    h('p', { class: 'desc' }, T('Botlar haritalara seviyelerine göre dağıtılır ve orada kalır: uzaylı keser, düşmansa seni görünce gücüne göre saldırır ya da kaçar, ölünce aynı haritada doğar.')),
    btSimpleSettings(a, null, false, save));
}

// botun son düşüncesi (modelin kendi notu, İngilizce); tıklayınca editörün Düşünceler ya da Hafıza bölümü (bot/memories.py, bot/agent.py)
function btAgentTrace(b) {
  const last = (b.ajan || []).filter(x => x.dusunce).slice(-1)[0];
  if (!last && !b.hafiza) return null;
  return h('a', { href: '#', class: 'small muted bt-agent', title: T('Ayrıntılar için tıkla'),
    onclick: e => { e.preventDefault(); e.stopPropagation(); btBotDetail(b.no, last ? 'dusunce' : 'hafiza'); } }, icon('brain'), last ? last.dusunce : T('Aklındakiler'));
}
const BT_PURPOSE = { soz: N('söz'), intikam: N('intikam'), tesekkur: N('teşekkür'), rekabet: N('rekabet'), merak: N('merak') };
const BT_MOOD = { ofke: N('Öfke'), moral: N('Moral'), sikilma: N('Sıkılma'), yorgunluk: N('Yorgunluk'), ozguven: N('Özgüven') };
const BT_GEAR = [['lazer', N('Lazerler'), 'lazer'], ['kalkan', N('Kalkan jeneratörleri'), 'jen'], ['hiz', N('Hız jeneratörleri'), 'jen'], ['dron', N('Dronlar')], ['ekstra', N('Ekstralar'), 'ekstra']];
const BT_STATS = { npc: N('Öldürülen uzaylı'), oyuncu: N('Öldürülen oyuncu'), olum: N('Ölüm'), kutu: N('Bonus kutusu'), kargo_kutusu: N('Kargo kutusu'),
  kutu_caldi: N('Başkasının kargo kutusu'), alim: N('Alışveriş'), gorev: N('Biten görev'), sure_sn: N('Oyun süresi'),
  harcama_kredi: N('Harcanan kredi'), harcama_uridyum: N('Harcanan uridyum'), cevher_kredi: N('Cevher satışından kredi'), ikmal: N('Cephane ikmali'),
  kutu_acti: N('Açılan ganimet kutusu'), anahtar_alim: N('Alınan anahtar'), aritma: N('Arıtma'), lab_yukleme: N('Laboratuvar yüklemesi'),
  skylab_yukseltme: N('Skylab yükseltmesi'), skylab_tasima: N('Skylab taşıması'), teknoloji: N('Teknoloji üretimi'), assembly: N('Assembly üretimi'),
  mod_kosu: N('Mod koşusu'), kapi_tamam: N('Biten galaksi kapısı'), kapi_kayip: N('Kaybedilen galaksi kapısı'), kapi_cekilis: N('Kapı çekilişi'),
  etkinlik_npc: N('Etkinlik uzaylısı'), etkinlik_kutusu: N('Etkinlik kutusu'), etkinlik_dusme: N('Etkinlik ganimeti'), pass_gorev: N('Battle Pass görevi'),
  battle_pass: N('Battle Pass'), sezon_seviye: N('Season Pass seviyesi'), dispatch: N('Dispatch'), galaxy_trek: N('Galaxy Trek'), mayin: N('Mayın'),
  smart_bomb: N('Smart Bomb'), emp: N('EMP'), salvo: N('Roket salvosu'), gizlendi: N('Gizlenme'), atlama_cpu: N("Atlama CPU'su") };
const BT_STATS_FEATURED = ['npc', 'oyuncu', 'olum', 'gorev', 'kapi_tamam', 'sure_sn'];          // İstatistik bölümünün büyük kutuları
const BT_WARNING = { sohbet: N('sohbet'), pvp: N('PvP'), kutu: N('kargo kutusu') };
const seDurationBt = sec => sec ? (sec >= 3600 ? Math.floor(sec / 3600) + ':' : '') + String(Math.floor(sec / 60) % 60).padStart(sec >= 3600 ? 2 : 1, '0') + ':' + String(Math.round(sec) % 60).padStart(2, '0') : '—';
const btShort = l => String(l || '').split('_').pop().toUpperCase();
const btCapitalize = m => m ? m.charAt(0).toLocaleUpperCase(LOC()) + m.slice(1) : m;
const BT_EVENT = { oldurdu_beni: N('beni vurdu'), oldurdum: N('ben vurdum'), yardim_etti: N('yardım etti'), yardim_ettim: N('yardım ettim'),
  sohbet: N('sohbet'), hakaret: N('hakaret'), ovgu: N('övgü'), grup: N('grup'), klan: N('klan'), arkadas: N('arkadaşlık'), reddetti: N('reddetti'),
  birlikte_avlandik: N('birlikte avlandık'), meydan: N('meydan okudu'), dedikodu_iyi: N('iyi dedikodu'), dedikodu_kotu: N('kötü dedikodu'),
  uyarildim: N('yönetici uyardı') };
const BT_HABIT = { gunduzcu: N('Gündüz oynar'), aksamci: N('Akşam oynar'), gece_kusu: N('Gece kuşu'), tutkun: N('Tutkun') };

// kişilik radarı: on özellik bir çokgen (0 merkez, 1 dış halka); ayarla(o) şekli kaydırıcıyla birlikte günceller
function btRadar(o) {
  const NS = 'http://www.w3.org/2000/svg', K = Object.keys(BT_TRAIT), R = 92, M = 130;
  const el = (name, a) => { const e = document.createElementNS(NS, name); for (const k in a) e.setAttribute(k, a[k]); return e; };
  const point = (i, r) => { const a = -Math.PI / 2 + i * 2 * Math.PI / K.length; return [M + Math.cos(a) * r, M + Math.sin(a) * r]; };
  const svg = el('svg', { viewBox: '0 0 260 260', class: 'bt-radar', role: 'img', 'aria-label': T('Kişilik') });
  for (const r of [.25, .5, .75, 1]) svg.append(el('polygon', { class: 'izgara', points: K.map((_, i) => point(i, R * r).join(',')).join(' ') }));
  K.forEach((k, i) => {
    const [x, y] = point(i, R), [tx, ty] = point(i, R + 16);
    svg.append(el('line', { class: 'izgara', x1: M, y1: M, x2: x, y2: y }));
    const t = el('text', { x: tx, y: ty + 4, 'text-anchor': Math.abs(tx - M) < 8 ? 'middle' : tx > M ? 'start' : 'end' });
    t.textContent = btCapitalize(T(BT_TRAIT[k])); svg.append(t);
  });
  const shape = el('polygon', { class: 'sekil' }), waypoints = K.map(() => el('circle', { r: 3 }));
  svg.append(shape, ...waypoints);
  const update = d => {
    const p = K.map((k, i) => point(i, R * Math.max(.03, d[k] ?? .5)));
    shape.setAttribute('points', p.map(x => x.join(',')).join(' '));
    waypoints.forEach((c, i) => { c.setAttribute('cx', p[i][0]); c.setAttribute('cy', p[i][1]); });
  };
  update(o);
  return { svg, update };
}

// ------------------------------------------------------------------ bot editörü: kimlik kartı ve bölüm menüsü solda, bölüm sağda
// (bot/edit.py; /api/bot/detay). Değişiklikler birikir, Kaydet tek istekte yazar. Oyun bu paketle açıkken canlı bot okunur ve
// düzenleme hemen oyunda geçerli olur.
const BT_D_TABS = [['profil', N('Profil'), 'user', N('Ad, seviye, cüzdan, harita ve şu anki işi.')],
  ['kisilik', N('Kişilik'), 'brain', N('Kararlarını belirleyen özellikleri ve şu anki ruh hâli.')],
  ['hangar', N('Hangar'), 'ship', N('Gemi, donanım, cephane ve kargo. En iyi eşyalar yuvalara takılır, fazlası depoda kalır.')],
  ['hafiza', N('Hafıza'), 'note', N('Kişiler hakkında düşündükleri, anıları, hedefleri ve hatırlatıcıları.')],
  ['dusunce', N('Düşünceler'), 'chat', N('Dil modelinin son kararları ve kullandığı araçlar.')],
  ['istat', N('İstatistik'), 'gauge', N('Sayaçlar, kapı süreleri, uyarılar, arkadaşlar ve Skylab.')]];
const BT_D_IMAGE = { profil: 'ke_pilot', hangar: 'ke_hangar', kisilik: 'bt_kisilik', hafiza: 'bt_hafiza', dusunce: 'bt_dusunce', istat: 'bt_istat' };   // Orders.md OP-013, OP-019
const btDetailIcon = s => BT_D_IMAGE[s[0]] ? h('span', { class: 'se-tab-icon gorsel' }, art(BT_D_IMAGE[s[0]], 'se-tab-art')) : h('span', { class: 'se-tab-icon' }, icon(s[2]));

async function btBotDetail(no, tab = 'profil') {
  const pid = BT.d.id;
  let v;
  try { [v] = await Promise.all([api('/api/bot/detay?id=' + encodeURIComponent(pid) + '&no=' + no), loadGameImages()]); } catch (e) { toast(e.message, 'err'); return; }
  let value = {};
  const multiplier = v.katalog;
  const lock = !!v.read_only;
  const fc = () => btCompany[v.firma - 1].toLowerCase();
  const side = h('aside', { class: 'bt-detail-side' }), main = h('div', { class: 'bt-detail-main' }), state = h('div', { class: 'bt-detail-status' });
  const save = btn(T('Kaydet'), async () => {
    const x = await act(() => api('/api/bot/detay', { id: pid, no, changes: value }), T('Kaydedildi.'));
    if (x) { v = x; value = {}; render(); BT.d = await api('/api/bot?id=' + encodeURIComponent(pid)).catch(() => BT.d); }
  }, 'primary', 'check');
  const cancel = btn(T('Vazgeç'), () => { value = {}; render(); }, 'ghost', 'undo');
  // değişiklik sayacı (alt çubuk): kaydedilmemiş alan sayısı
  const handle = () => {
    const n = Object.keys(value).length;
    save.disabled = lock || !n; cancel.disabled = !n;
    btFill(state, lock ? [icon('lock'), T('Salt okunur')] : n ? [h('span', { class: 'se-pulse' }), T('{0} değişiklik kaydedilmedi', n)] : [icon('check'), T('Kayıtla aynı')]);
    state.className = 'bt-detail-status' + (n && !lock ? ' var' : '');
  };
  const change = (a, val) => { value[a] = val; handle(); };
  const get_value = (a, backup) => value[a] !== undefined ? value[a] : backup;
  const entries = (a, extra) => { value[a] = (value[a] || []).concat([extra]); render(); };
  const mapping = (a, k, val) => { value[a] = Object.assign({}, value[a], { [k]: val }); handle(); };
  const card = (title, iconEl, ...body) => h('div', { class: 'card se-card bt-detail-card' }, title ? h('h2', null, icon(iconEl), title) : null, ...body);
  const empty = text => h('div', { class: 'bt-detail-empty' }, text || T('Henüz bir şey yok.'));
  const missing = () => h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Bu bot henüz oyunda görünmedi: yalnız adı ve kişiliği düzenlenebilir.')));
  const remove = (onclick, title = T('Sil')) => btn('', onclick, 'ghost sm icon', 'trash', { title, disabled: lock });
  const count = (n, on, o = {}) => { const el = btNumber(n, on, o); el.disabled = lock; return el; };
  const percent = (n, on, cls = '') => slider({ min: 0, max: 100, step: 1, value: Math.round(n * 100), disabled: lock, oninput: e => on(+e.target.value / 100) }, cls);
  const now = Date.now() / 1000;

  // ---- sol: kimlik kartı (kayıtlı değerler) ve bölüm menüsü
  function uid() {
    const p = v.profil || {}, f = fc(), e = v.ekip || {};
    const sell = (name, n, tag) => h('div', { class: 'se-wallet-row' }, art('kaynak_' + name, 'se-currency-icon'), h('span', null, tag), h('b', null, fmtN(n)));
    const stats = (iconEl, n, title) => h('div', { class: 'se-value', title: title }, h('span', { class: 'bt-value-icon' }, icon(iconEl)), h('b', null, n));
    const cargo = Object.values(v.kargo || {}).reduce((a, n) => a + n, 0);
    return h('div', { class: 'card se-identity f-' + f },
      h('div', { class: 'se-identity-scene' }, h('div', { class: 'se-ring' }), shipImage(e.gemi || 'ship_phoenix', 150, f)),
      h('div', { class: 'se-identity-head' }, portrait(v.firma, 'se-portrait kucuk', 84),
        h('div', { style: { minWidth: 0 } }, h('div', { class: 'se-identity-name', title: v.ad }, v.ad),
          h('div', { class: 'se-pilot small' }, p.klan ? h('span', { class: 'se-clan' }, '[' + p.klan + ']') : null, badge(btCompany[v.firma - 1], f),
            v.cevrimici ? badge(T('Çevrimiçi'), 'ok') : null))),
      h('div', { class: 'bt-detail-label' }, h('div', null, h('b', null, T(BT_ARCHETYPE[v.arketip] || v.arketip)),
        v.aliskanlik ? T(BT_HABIT[v.aliskanlik] || v.aliskanlik) : null), h('div', { class: 'dim' }, btTraitSummary(v.ozellik))),
      v.var ? [
        h('div', { class: 'se-lv sm' }, h('div', { class: 'se-lv-num' }, h('small', null, T('Sv')), h('b', null, p.seviye)),
          h('div', { class: 'grow' }, h('div', { class: 'row between small muted' }, btRank((BT.d.kadro.find(b => b.no === no) || {}).rutbe || 1, 18), h('span', { class: 'mono' }, fmtShort(p.ep) + ' EP')),
            epBar(p.ep, p.base_ep || 0, p.next_ep))),
        h('div', { class: 'se-wallet' }, sell('kredi', p.kredi, T('Kredi')), sell('uridyum', p.uridyum, T('Uridyum')), sell('onur', p.onur, T('Onur'))),
        h('div', { class: 'se-values' }, stats('zap', fmtShort(v.guc.guc), T('Güç')), stats('crosshair', fmtShort(v.guc.dps), T('Hasar/sn')),
          stats('heart', fmtShort(v.guc.ehp), T('Etkin can')), stats('box', fmtShort(cargo) + '/' + fmtShort(v.cargo_capacity), T('Kargo')))] : null);
  }
  function menu() {
    const n = { hangar: v.var ? BT_GEAR.reduce((a, [k]) => a + Object.keys(v.ekip[k] || {}).length, 0) : 0, memory: v.var ? v.memories.length + v.relations.length : 0,
      thought: (v.ajan || []).length };
    return h('nav', { class: 'card se-menu' }, BT_D_TABS.map(s => h('button', { class: s[0] === tab ? 'on' : '', type: 'button',
      onclick: () => { if (tab !== s[0]) { tab = s[0]; main.scrollTop = 0; render(); } } },
    btDetailIcon(s), h('span', null, T(s[1])), n[s[0]] ? h('span', { class: 'se-count' }, fmtN(n[s[0]])) : null)));
  }

  // ---- Profil
  function profile() {
    const p = v.profil || {};
    let name = v.ad;
    const nameCard = card(T('Ad'), 'edit', h('div', { class: 'bt-detail-name' },
      h('input', { class: 'input', value: v.ad, maxlength: 20, disabled: lock, oninput: e => { name = e.target.value.trim(); regenerate.disabled = lock || name === v.ad; },
        onkeydown: e => { if (e.key === 'Enter') regenerate.click(); } }),
      regenerate = btn(T('Yeniden adlandır'), async () => {
        if (name === v.ad) return;
        const x = await act(() => api('/api/bot/ad', { id: pid, no, name }), T('Kaydedildi.'));
        if (x) { BT.d = x; v.ad = name; render(); }
      }, '', 'edit', { disabled: true })),
      h('div', { class: 'small dim' }, T('3-20 karakter: harf, rakam, _ . -  Ad hemen değişir, Kaydet beklemez.')));
    if (!v.var) return [nameCard, missing()];
    const currency = (key, icon, tag, n, o) => h('div', { class: 'se-currency' }, art('kaynak_' + icon, 'se-currency-icon lg'),
      h('div', { class: 'grow' }, h('label', { class: 'lbl' }, tag), count(get_value(key, n), x => change(key, x), Object.assign({ min: 0, max: 2e12, cls: 'num wide' }, o))));
    const lv = p.next_ep ? T('Seviye {0}; sonraki seviye {1} EP.', p.seviye, fmtN(p.next_ep)) : T('Seviye {0}.', p.seviye);
    const job = [p.hedef ? T(BT_TARGET[p.hedef] || p.hedef) : '—', p.niyet && p.niyet !== p.hedef ? T('Niyeti: {0}', T(BT_TARGET[p.niyet] || p.niyet)) : null];
    return [nameCard,
      card(T('Seviye ve cüzdan'), 'star', h('div', { class: 'bt-detail-currencies' },
        h('div', null, currency('ep', 'deneyim', T('Deneyim (EP)'), p.ep, { max: 1e12 }), h('div', { class: 'small dim bt-detail-note' }, lv)),
        currency('kredi', 'kredi', T('Kredi'), p.kredi), currency('uridyum', 'uridyum', T('Uridyum'), p.uridyum),
        currency('onur', 'onur', T('Onur'), p.onur, { min: -2e12 }))),
      card(T('Konum ve iş'), 'map',
        btRow(T('Harita'), v.cevrimici ? T('Çevrimiçi botun haritası değiştirilemez: çevrimdışı olunca dene.') : T('Bot bir sonraki girişinde bu haritada başlar.'),
          h('select', { class: 'input', disabled: lock || !!v.cevrimici, onchange: e => change('harita', Number(e.target.value)) },
            multiplier.haritalar.map(m => h('option', { value: m.id, selected: m.id === get_value('harita', p.harita) }, m.ad)))),
        btRow(T('Ne yapıyor'), job[1], h('span', { class: 'bt-activity' }, job[0])),
        btRow(T('Görev'), v.tamam ? T('{0} görev bitirdi.', v.tamam) : null, v.gorev && !value.gorev_iptal
          ? h('div', { class: 'row', style: { gap: '8px' } }, h('b', null, v.gorev.ad), btn(T('Görevi bırak'), () => { change('gorev_iptal', true); render(); }, 'ghost sm', 'x', { disabled: lock }))
          : h('span', { class: 'dim' }, value.gorev_iptal ? T('Bırakılacak') : '—')),
        btRow(T('Klan'), null, h('span', null, p.klan ? '[' + p.klan + ']' : '—')))];
  }

  // ---- Kişilik: radar + özellik kaydırıcıları, ruh hâli
  function personality() {
    const traits = Object.assign({}, v.ozellik, value.ozellik);
    const r = btRadar(traits);
    const traitRow = ([k, name_]) => {
      const value = h('b', null, Math.round(traits[k] * 100));
      return h('div', { class: 'bt-trait' }, h('span', null, btCapitalize(T(name_))), value,
        percent(traits[k], x => { traits[k] = x; value.textContent = Math.round(x * 100); r.update(traits); mapping('ozellik', k, x); }));
    };
    const mood = Object.assign({}, v.ruh, value.ruh);
    const moodRow = ([k, name_]) => {
      const value = h('b', null, Math.round((mood[k] ?? 0) * 100));
      return h('div', { class: 'bt-trait ruh-' + k }, h('span', null, T(name_)), value,
        percent(mood[k] ?? 0, x => { value.textContent = Math.round(x * 100); mapping('ruh', k, x); }, 'bt-mood'));
    };
    return [card(T('Özellikler'), 'brain', h('p', { class: 'desc' }, T('Kadro üretilirken belirlendi; değiştirince bot buna göre karar verir (saldırgan bot PvP\'ye, sosyal bot sohbete, tutumlu bot birikime yatkındır).')),
      h('div', { class: 'bt-personality' }, h('div', { class: 'bt-radar-box' }, r.svg), h('div', { class: 'bt-traits' }, Object.entries(BT_TRAIT).map(traitRow)))),
    v.var ? card(T('Ruh hâli'), 'heart', h('p', { class: 'desc' }, T('Şu anki duyguları: zamanla dengeye döner. Öfkeli bot intikam peşine düşer, yorgun bot erken çıkar.')),
      h('div', { class: 'bt-traits iki' }, Object.entries(BT_MOOD).map(moodRow))) : null];
  }

  // ---- Hangar: gemi, donanım kutuları, cephane, kargo
  function hangar() {
    if (!v.var) return [missing()];
    const e = v.ekip, f = fc();
    const ship = get_value('gemi', e.gemi);
    const g = multiplier.gemiler.find(x => x.loot === ship) || {};
    const slot = { lazer: g.lazer, jen: g.jen, ekstra: g.ekstra };
    const item = (l, n, update, remove_, maximum) => h('div', { class: 'bt-item' }, gameIcon(l, 44, f, 'box'),
      h('div', { class: 'bt-item-name', title: itemName(l) }, itemName(l)),
      h('div', { class: 'bt-item-bottom' }, count(n, update, { min: 0, max: maximum, cls: 'num' }), remove_ ? remove(remove_) : null));
    const addSelect = (options, on) => h('select', { class: 'input bt-add', disabled: lock, onchange: ev => { if (ev.target.value) on(ev.target.value); } },
      [h('option', { value: '' }, T('Ekle…'))].concat(options.map(x => h('option', { value: x.loot }, x.ad))));
    const category = ([k, name_, slot_info]) => {
      const owner = Object.assign({}, e[k], (value.ekip || {})[k]);
      const write = new_ => { value.ekip = Object.assign({}, value.ekip, { [k]: new_ }); handle(); };
      const var_ = Object.entries(owner).filter(([, n]) => n > 0);
      const equipped = x => Object.values(Object.assign({}, e[x], (value.ekip || {})[x])).reduce((a, n) => a + n, 0);
      // kalkan ve hız aynı jeneratör yuvalarını paylaşır; ekstranın sayısı kalan hakkı (JP-01 10 hak): her biri bir yuva
      const total = slot_info === 'jen' ? equipped('kalkan') + equipped('hiz') : k === 'ekstra' ? var_.length : equipped(k);
      return h('div', { class: 'bt-cat' },
        h('div', { class: 'bt-cat-head' }, h('b', null, T(name_)), h('span', { class: 'se-count' }, slot_info && slot[slot_info] != null ? T('{0} / {1} yuva', total, slot[slot_info]) : fmtN(total)),
          h('span', { class: 'spacer' }), addSelect(multiplier[k].filter(x => !owner[x.loot]), l => { write(Object.assign({}, owner, { [l]: (multiplier[k].find(x => x.loot === l) || {}).hak || 1 })); render(); })),
        var_.length ? h('div', { class: 'bt-items' }, var_.map(([l, n]) => item(l, n, x => write(Object.assign({}, owner, { [l]: x })),
          () => { const y = Object.assign({}, owner); delete y[l]; write(y); render(); }, k === 'ekstra' ? 100000 : k === 'dron' ? 10 : 100))) : empty(T('Takılı bir şey yok.')));
    };
    const stock = Object.assign({}, v.stok, value.stok);
    const cargo = Object.values(v.kargo).reduce((a, n) => a + n, 0), capacity = v.cargo_capacity || 1;
    return [
      card(T('Gemi'), 'ship', h('div', { class: 'bt-ship-card' },
        h('div', { class: 'bt-ship-scene' }, shipImage(ship, 132, f)),
        h('div', { class: 'bt-ship-right' },
          field(T('Gemi'), h('select', { class: 'input', disabled: lock, onchange: ev => { change('gemi', ev.target.value); render(); } },
            multiplier.gemiler.map(x => h('option', { value: x.loot, selected: x.loot === ship }, x.ad)))),
          h('div', { class: 'bt-slots' }, [['zap', g.lazer, T('lazer')], ['shield', g.jen, T('jeneratör')], ['cpu', g.ekstra, T('ekstra')]].map(([iconEl, n, name_]) =>
            h('span', { class: 'chip' }, icon(iconEl), h('b', null, n ?? '?'), name_))),
          field(T('Kullandığı cephane'), h('select', { class: 'input', disabled: lock, onchange: ev => change('cephane', ev.target.value) },
            multiplier.cephane.filter(x => x.loot.includes('_laser_')).map(x => h('option', { value: x.loot, selected: x.loot === get_value('cephane', e.cephane) }, x.ad)))),
          h('div', { class: 'bt-power' }, [[T('Güç'), v.guc.guc], [T('Hasar/sn'), fmtN(v.guc.dps)], [T('Etkin can'), fmtN(v.guc.ehp)]].map(([k, n]) =>
            h('div', null, h('span', null, k), h('b', null, n)))),
          value.gemi || value.ekip ? h('div', { class: 'small dim' }, T('Güç kaydedince yeniden hesaplanır.')) : null))),
      card(T('Donanım'), 'layers', ...BT_GEAR.map(category)),
      card(T('Cephane ve roketler'), 'ammo',
        h('div', { class: 'bt-cat-head' }, h('span', { class: 'small muted' }, T('Depodaki cephane, roketler ve kaynaklar.')), h('span', { class: 'spacer' }),
          addSelect(multiplier.cephane.filter(x => stock[x.loot] === undefined), l => { mapping('stok', l, 100); render(); })),
        Object.keys(stock).length ? h('div', { class: 'bt-items' }, Object.entries(stock).map(([l, n]) => item(l, n, x => mapping('stok', l, x), null, 1e9))) : empty()),
      card(T('Kargo'), 'box',
        h('div', { class: 'bt-cargo' }, h('div', { class: 'bt-cargo-bar' }, h('span', { style: { width: Math.min(100, 100 * cargo / capacity) + '%' } })),
          h('span', { class: 'small muted' }, T('{0} / {1}', fmtN(cargo), fmtN(capacity)))),
        Object.keys(v.kargo).length && !value.kargo_bosalt
          ? h('div', { class: 'row wrap', style: { gap: '6px', alignItems: 'center', marginTop: '10px' } }, Object.entries(v.kargo).map(([o, n]) => h('span', { class: 'chip' }, o, h('b', null, fmtN(n)))),
            h('span', { class: 'spacer' }), btn(T('Kargoyu boşalt'), () => { change('kargo_bosalt', true); render(); }, 'ghost sm', 'trash', { disabled: lock }))
          : empty(value.kargo_bosalt ? T('Kaydedince boşaltılacak.') : T('Kargo boş.'))),
    ];
  }

  // ---- Hafıza
  function memory() {
    if (!v.var) return [missing()];
    const deleted = (a, k) => (value[a] || []).includes(k);
    const relation = v.relations.filter(x => !deleted('iliski_sil', x.anahtar)).map(x => {
      const d = get_value('iliski', {})[x.anahtar] ?? x.d;
      const value = h('b', { class: d >= 0 ? 'iyi' : 'kotu' }, (d > 0 ? '+' : '') + d.toFixed(2));
      const saves = slider({ min: -100, max: 100, step: 5, value: Math.round(d * 100), disabled: lock, oninput: e => {
        const y = +e.target.value / 100; value.textContent = (y > 0 ? '+' : '') + y.toFixed(2); value.className = y >= 0 ? 'iyi' : 'kotu'; mapping('iliski', x.anahtar, y); } }, 'bt-relation-range');
      return h('div', { class: 'bt-relation' }, h('div', null, h('b', null, x.ad),
        h('div', { class: 'small dim' }, Object.entries(x.n || {}).map(([t, n]) => (BT_EVENT[t] ? T(BT_EVENT[t]) : t) + ' ' + n).join(', '))),
      h('div', { class: 'bt-relation-scale' }, h('span', { class: 'small dim' }, T('Düşman')), saves, h('span', { class: 'small dim' }, T('Dost'))), value,
      remove(() => entries('iliski_sil', x.anahtar)));
    });
    const impression = v.izlenim.filter(x => !deleted('izlenim_sil', x.anahtar)).map(x => h('div', { class: 'bt-note' }, h('b', null, x.ad),
      h('textarea', { class: 'input', rows: 2, disabled: lock, oninput: e => mapping('izlenim', x.anahtar, e.target.value) }, get_value('izlenim', {})[x.anahtar] ?? x.metin),
      remove(() => entries('izlenim_sil', x.anahtar))));
    const memories = v.memories.filter(a => !deleted('ani_sil', a.id)).map(a => {
      const waiting = a.takip && !a.takip.bitti && !deleted('takip_iptal', a.id);
      return h('div', { class: 'bt-memory' }, h('div', { class: 'bt-memory-head' }, h('b', null, a.kim), h('span', { class: 'small dim' }, T('{0} önce', fmtDur(now - a.t))),
        a.n > 1 ? h('span', { class: 'se-count' }, '×' + a.n) : null, waiting ? badge(T('Bekleyen: {0}', T(BT_PURPOSE[a.takip.amac] || a.takip.amac)), 'warn') : null,
        h('span', { class: 'spacer' }), waiting ? btn('', () => entries('takip_iptal', a.id), 'ghost sm icon', 'x', { title: T('Bekleyen işi iptal et'), disabled: lock }) : null,
        remove(() => entries('ani_sil', a.id))),
      h('input', { class: 'input', value: get_value('ani', {})[a.id] ?? a.ozet, disabled: lock, oninput: e => mapping('ani', a.id, e.target.value) }));
    });
    const ledger = get_value('defter', v.defter);
    const notebookRow = (m, i) => h('div', { class: 'bt-ledger' }, h('span', { class: 'bt-ledger-no' }, i + 1),
      h('input', { class: 'input', value: m, disabled: lock, oninput: e => { const d = ledger.slice(); d[i] = e.target.value; change('defter', d); } }),
      remove(() => { change('defter', ledger.filter((_, j) => j !== i)); render(); }));
    return [
      card(T('İlişkileri'), 'users', h('p', { class: 'desc' }, T('Kişilere bakışı: dostlarına yardım eder, düşmanlarına saldırır.')), relation.length ? relation : empty()),
      card(T('Kişiler hakkındaki izlenimleri'), 'note', impression.length ? h('div', { class: 'bt-notes' }, impression) : empty()),
      card(T('Anıları'), 'clock', memories.length ? h('div', { class: 'bt-memories' }, memories) : empty()),
      h('div', { class: 'grid g2' },
        card(T('Hedef defteri'), 'target', ...(ledger.length ? ledger.map(notebookRow) : [empty()]),
          h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '8px' } },
            btn(T('Hedef ekle'), () => { change('defter', ledger.concat([''])); render(); }, 'ghost sm', 'plus', { disabled: lock }))),
        card(T('Hatırlatıcılar ve birikim'), 'bell',
          v.hatirlatici.length && !value.hatirlatici_sil
            ? [h('ul', { class: 'bt-mind' }, v.hatirlatici.map(x => h('li', null, x.metin, h('span', { class: 'dim' }, ' (' + T('{0} sonra', fmtDur(x.time_left_sec)) + ')')))),
              h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '6px' } }, btn(T('Hatırlatıcıları sil'), () => { change('hatirlatici_sil', true); render(); }, 'ghost sm', 'trash', { disabled: lock }))]
            : empty(T('Hatırlatıcı yok.')),
          h('div', { class: 'bt-savings' }, h('span', { class: 'lbl' }, T('Biriktirdiği')), v.birikim && !value.birikim_sil
            ? h('div', { class: 'row', style: { gap: '8px' } }, gameIcon(v.birikim, 28, fc(), 'box'), h('b', null, itemName(v.birikim)), h('span', { class: 'spacer' }),
              btn(T('Biriktirmeyi bırak'), () => { change('birikim_sil', true); render(); }, 'ghost sm', 'x', { disabled: lock }))
            : h('span', { class: 'dim' }, '—')))),
    ];
  }

  // ---- Düşünceler: dil modelinin adımları (yeniden eskiye)
  function thought() {
    const trace = value.ajan_sil ? [] : (v.ajan || []).slice().reverse();
    const step = x => [h('b', null, x.arac), x.arg && Object.keys(x.arg).length ? ' ' + JSON.stringify(x.arg) : '', x.sonuc ? h('span', { class: 'dim' }, ' → ' + x.sonuc) : null];
    return [card(T('Son düşünceleri'), 'chat', h('p', { class: 'desc' }, T('Botun kendi notları; dil modeli İngilizce tutar.')),
      trace.length ? h('ol', { class: 'bt-thoughts' }, trace.map(x => h('li', null, x.dusunce ? h('div', null, x.dusunce) : null, h('div', { class: 'bt-step' }, step(x)))))
        : empty(value.ajan_sil ? T('Kaydedince temizlenecek.') : T('Henüz düşünce yok: Gelişmiş kipte dil modeli karar verdikçe dolar.')),
      trace.length ? h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '10px' } }, btn(T('Düşünceleri temizle'), () => { change('ajan_sil', true); render(); }, 'ghost sm', 'trash', { disabled: lock })) : null)];
  }

  // ---- İstatistik
  function stats() {
    if (!v.var) return [missing()];
    const ist = v.istat || {};
    const value = (k, n) => k === 'sure_sn' ? fmtDur(n) : fmtN(Math.round(n));
    const remaining = Object.entries(ist).filter(([k]) => !BT_STATS_FEATURED.includes(k)).sort((a, b) => (BT_STATS[a[0]] ? 0 : 1) - (BT_STATS[b[0]] ? 0 : 1));
    return [
      h('div', { class: 'stats bt-detail-stats' }, BT_STATS_FEATURED.map(k => h('div', { class: 'stat' }, h('div', { class: 'k' }, T(BT_STATS[k])), h('div', { class: 'v' }, value(k, ist[k] || 0))))),
      card(T('Bütün sayaçlar'), 'list', remaining.length ? h('div', { class: 'kv bt-kv' }, remaining.map(([k, n]) => h('div', null, BT_STATS[k] ? T(BT_STATS[k]) : k, h('b', null, value(k, n))))) : empty()),
      h('div', { class: 'grid g2' },
        card(T('Kapı süreleri'), 'clock', Object.keys(v.gate_times || {}).length ? h('div', { class: 'kv one' },
          Object.entries(v.gate_times).map(([g, x]) => h('div', null, g.charAt(0).toUpperCase() + g.slice(1), h('b', null, T('en iyi {0}', seDurationBt(x.en_iyi)) + ' · ' + T('{0} kez', fmtN(x.sayi))))))
          : empty()),
        card(T('Arkadaşları'), 'users', (v.profil.arkadaslar || []).length ? h('div', { class: 'row wrap', style: { gap: '6px' } }, v.profil.arkadaslar.map(a => h('span', { class: 'chip' }, a))) : empty()),
        card(T('Yönetici uyarısı'), 'alert', Object.keys(v.uyari || {}).length ? h('div', { class: 'row wrap', style: { gap: '6px' } },
          Object.entries(v.uyari).map(([k, t]) => badge(T(BT_WARNING[k] || k) + ' · ' + T('{0} kaldı', fmtDur(Math.max(0, t - Date.now() / 1000))), 'warn'))) : empty(T('Uyarı yok.'))),
        card(T('Skylab'), 'layers', Object.keys(v.skylab || {}).length ? h('div', { class: 'row wrap', style: { gap: '6px' } }, Object.entries(v.skylab).map(([m, n]) => h('span', { class: 'chip' }, m, h('b', null, n)))) : empty())),
    ];
  }

  let regenerate;
  function render() {
    const s = BT_D_TABS.find(x => x[0] === tab) || BT_D_TABS[0], sc = main.scrollTop;
    btFill(side, uid(), menu());
    btFill(main, h('div', { class: 'se-main-head' }, btDetailIcon(s), h('div', null, h('h2', null, T(s[1])), h('div', { class: 'small muted' }, T(s[3])))),
      lock ? h('div', { class: 'alert uyari' }, icon('alert'), h('div', null, T('Oyun bu paketle açık ama sunucuya ulaşılamadı: son kayıt gösteriliyor, düzenlenemez.')))
        : v.canli ? h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Oyun açık: değişiklikler kaydedince hemen oyunda geçerli olur.'))) : null,
      ({ profile, personality, hangar, memory, thought, stats })[s[0]]());
    main.scrollTop = sc;
    handle();
  }
  render();
  const m = modal({ title: T('Bot editörü'), sub: T('{0} paketi · {1}. bot', BT.d.ad, no), body: h('div', { class: 'bt-detail' }, side, main), onclose: () => btEditor(),
    foot: [state, h('span', { class: 'spacer' }), btn(T('Kapat'), async () => {
      if (Object.keys(value).length && !await confirmBox(T('Değişiklikler kaydedilmedi'), T('Kapatınca kaydedilmemiş değişiklikler atılır.'), { ok: T('Kaydetmeden kapat'), danger: true })) return;
      m.close();
    }, 'ghost'), cancel, save] });
  m.box.classList.add('bt-detail-modal');
}

function btUsage(u) {
  if (!u) return h('div', { class: 'small muted' }, T('Oyun bu paketle açılınca ölçülür.'));
  const s = u.saat || {}, pay = s.girdi ? Math.round(100 * (s.onbellek || 0) / s.girdi) : 0;
  return h('div', { class: 'small', style: { textAlign: 'right' } },
    h('div', null, T('{0} istek · {1} girdi tokeni (%{2} önbellekten) · {3} çıktı tokeni', fmtN(s.istek || 0), fmtN(s.girdi || 0), pay, fmtN(s.cikti || 0))),
    h('div', { class: 'muted' }, [u.saglayici, u.sinir ? T('Saatlik sınır: {0} / {1} istek', fmtN(s.istek || 0), fmtN(u.sinir)) : T('Saatlik sınır yok'),
      u.sure_dk < 60 ? T('son {0} dakikada', u.sure_dk) : null].filter(Boolean).join(' · ')),
    u.sinirda ? h('div', { style: { color: 'var(--warn)' } }, T('Sınıra gelindi: botlar şimdilik kalıplarla konuşuyor ve kurallı kararla oynuyor.')) : null);
}

function btAdvanced(d) {
  return typeof btLlmCard === 'function' ? btLlmCard(d) : h('div', { class: 'card' }, btLlmWarning());
}

// ------------------------------------------------------------------ Gelişmiş kip: dil modeli (llm_setup.py, /api/bot/llm)
function btLlmCard(d) {
  const box = h('div'), right = h('div');
  const a = d.ayarlar;
  btLlmWatch(box, right);
  return h('div', { class: 'stack' },
    h('div', { class: 'card' }, h('h2', null, icon('brain'), T('Dil modeli')),
      h('div', { class: 'bt-llm' }, btArt('bot_llm', 'dron_ayarlar', 'bt-llm-art'), h('div', { class: 'stack', style: { gap: '10px' } }, right, box))),
    h('div', { class: 'card' }, h('h2', null, icon('sliders'), T('Gelişmiş kip ayarları')),
      btRow(T('Son bir saatin kullanımı'), T('Botların dil modeline son bir saatte gönderdiği istekler ve tokenler (sohbet, anılar ve kararlar). Sağlayıcının faturası token sayısına göre işler; önbellekten gelen girdi çok daha ucuzdur.'),
        btUsage(d.llm_usage)),
      btRow(T('Aynı anda düşünen bot'), T('Modelin paralel yuvaları: istekler toplu işlenir. Yüksekse daha çok bot aynı anda konuşur ama bilgisayar daha çok zorlanır.'),
        btNumber(a.llm_toplu, v => btSetting('llm_toplu', v), { min: 1, max: 16 })),
      btRow(T('Sohbet modelle'), T('Kapalıysa botlar Normal kipteki gibi kalıplarla konuşur; model yalnız kararlarda kullanılır.'), btKey(a.llm_sohbet, v => btSetting('llm_sohbet', v))),
      btRow(T('Kararları gözden geçirme (dakika)'), T('Her bot bu kadar dakikada bir durumunu modele danışır (0: hiç). Kısa süre daha canlı ama daha ağır.'),
        btNumber(a.llm_karar_dk, v => btSetting('llm_karar_dk', v), { min: 0, max: 120 })),
      // araç döngüsü yalnız dahili model dışındaki sağlayıcılarda (bot/agent.py)
      btRow(T('Araçlarla oynasın'), T('Dahili model dışındaki sağlayıcılarda bot, oyuncu gibi önce durumuna, haritalara, mağazaya ve görevlere bakar, sonra araçlarla karar verir; hedef defteri tutar, kendine hatırlatıcı kurar.'),
        btKey(a.llm_ajan, v => btSetting('llm_ajan', v))),
      btRow(T('Düşünme başına en çok adım'), T('Bir düşünmede modele en çok kaç kez sorulur (her seferde birkaç araç). Çoğu düşünme 1-2 istekte biter; yüksek değer daha çok istek demek.'),
        btNumber(a.llm_ajan_adim, v => btSetting('llm_ajan_adim', v), { min: 1, max: 10 })),
      btRow(T('Saatlik istek sınırı'), T('Dahili model dışındaki sağlayıcıya saatte en çok bu kadar istek gider (sohbet, anılar ve kararlar dahil; 0: sınırsız). Sınıra gelince botlar kalıplarla konuşur ve kurallı kararla oynar; harcamayı sınırlar.'),
        btNumber(a.llm_saatlik, v => btSetting('llm_saatlik', v), { min: 0, max: 20000 }))));
}

function btLlmWatch(box, right) {
  let signature = '', selected = null;
  // sağlayıcı formu yalnız seçim değişince yeniden çizilir (yoklama yazılanı silmesin); alt kutu dahili modelde kurulum, ötekilerde test
  const render = s => {
    signature = JSON.stringify(s);
    if (BT.liste) BT.liste.llm_multilingual = s.saglayici.multilingual;
    if (selected !== s.saglayici.secili || s.new_form) { selected = s.saglayici.secili; btFill(right, btLlmProvider(s.saglayici, x => render(Object.assign(x, { new_form: true })))); }
    btFill(box, selected === 'yerel' ? h('div', { class: 'stack', style: { gap: '10px' } }, btLlmWarning(), btLlmBox(s, render)) : btLlmRemoteBox(s, render));
  };
  api('/api/bot/llm').then(render).catch(e => btFill(box, h('div', { class: 'alert hata' }, icon('alert'), h('div', null, e.message))));
  const id = setInterval(async () => {
    if (!box.isConnected) return clearInterval(id);
    let s; try { s = await api('/api/bot/llm'); } catch (e) { return; }
    if (JSON.stringify(s) !== signature) render(s);
  }, 1000);
}

// sağlayıcı adları (öteki sağlayıcıların adı kendi markası)
const BT_PROVIDER_NAME = { yerel: N('Dahili yerel model (Qwen3 4B)'), ozel: N('Özel (OpenAI uyumlu)') };
function btLlmProvider(provider, new_) {
  const p = provider.liste.find(x => x.kimlik === provider.secili);
  const f = { adres: p.adres, model: p.model, anahtar: '' };
  const send = (body, msg) => act(() => api('/api/bot/llm/saglayici', body), msg).then(x => { if (x) new_(x); });
  const sec = h('select', { class: 'input', onchange: e => send({ kimlik: e.target.value }, T('Kaydedildi.')) },
    provider.liste.map(x => h('option', { value: x.kimlik, selected: x.kimlik === provider.secili }, BT_PROVIDER_NAME[x.kimlik] ? T(BT_PROVIDER_NAME[x.kimlik]) : x.ad)));
  const rows = [btRow(T('Sağlayıcı'), T('Botların sohbeti ve kararları bu modelle verilir.'), sec)];
  if (provider.secili === 'yerel') return h('div', null, rows);
  // model: önce elle yazılır; modeller çekilince açılır liste olur (datalist dolu kutuda süzülüp açılmıyordu)
  const modelBox = h('div', null, h('input', { class: 'input', value: f.model, oninput: e => { f.model = e.target.value.trim(); } }));
  const load = async () => {
    const x = await act(() => api('/api/bot/llm/models', { kimlik: provider.secili, adres: f.adres, anahtar: f.anahtar }), r => T('{0} model bulundu.', r.models.length));
    if (!x || !x.models.length) return;
    const models = x.models.includes(f.model) || !f.model ? x.models : [f.model].concat(x.models);
    if (!f.model) f.model = models[0];
    btFill(modelBox, h('select', { class: 'input', onchange: e => { f.model = e.target.value; } }, models.map(m => h('option', { value: m, selected: m === f.model }, m))));
  };
  rows.push(
    btRow(T('Adres'), p.yerel ? T('Bilgisayarında çalışan sunucunun OpenAI uyumlu adresi (…/v1). Sunucu açık olmalı.') : T('Çoğu zaman değiştirmen gerekmez.'),
      h('input', { class: 'input', value: f.adres, placeholder: p.default_url, oninput: e => { f.adres = e.target.value.trim(); } })),
    btRow(p.key_required ? T('API anahtarı') : T('API anahtarı (isteğe bağlı)'), T('Yalnız bu bilgisayarda saklanır; bot paketlerine girmez.'),
      h('input', { class: 'input', type: 'password', autocomplete: 'off', oninput: e => { f.anahtar = e.target.value.trim(); },
        placeholder: p.has_key ? T('Kayıtlı ({0}); değiştirmek için yaz', p.anahtar) : p.key_required ? T('API anahtarını yapıştır') : T('Gerekmiyorsa boş bırak') })),
    btRow(T('Model'), T('Hızlı ve ucuz bir sohbet modeli yeter; düşünen (reasoning) modeller yavaş yanıt verir.'),
      h('div', { class: 'row', style: { gap: '6px' } }, modelBox, btn(T('Modelleri getir'), load, 'ghost sm', 'download'))),
    h('div', { class: 'row', style: { gap: '8px', justifyContent: 'flex-end' } },
      p.has_key ? btn(T('Anahtarı sil'), () => send({ kimlik: provider.secili, anahtar: '-' }, T('Silindi.')), 'ghost sm', 'trash') : null,
      btn(T('Kaydet'), () => send({ kimlik: provider.secili, adres: f.adres, model: f.model, anahtar: f.anahtar }, T('Kaydedildi.')), 'primary sm', 'check')),
    h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Bu sağlayıcıyla botlar kendi sohbet dillerinde konuşur (Kadro sekmesinden seçilir). Ücretli sağlayıcılarda istekler senin hesabından ödenir: "Aynı anda düşünen bot" ve "Kararları gözden geçirme" ayarları istek sayısını belirler.'))));
  return h('div', { class: 'stack', style: { gap: '4px' } }, rows);
}

function btLlmRemoteBox(s, render) {
  const t = s.test && s.test.saglayici === s.saglayici.secili ? s.test : {};
  return h('div', { class: 'bt-llm-step' }, icon(t.durum === 'ok' ? 'check' : 'play'),
    h('div', null, h('b', null, t.durum === 'ok' ? T('Sağlayıcı çalışıyor') : T('Test et')),
      h('div', { class: 'small muted' }, t.durum === 'calisiyor' ? T('Sağlayıcıya kısa bir soru soruluyor…') : t.durum === 'hata' ? t.hata
        : t.durum === 'ok' ? T('Yanıt {0} sn: "{1}"', t.sure_sn, t.yanit ?? '') : T('Kaydettikten sonra sağlayıcıya kısa bir soru sorulur; yanıt gelirse botlar onunla konuşur.'))),
    t.durum === 'calisiyor' ? h('span', { class: 'spin' }) : btn(T('Test et'), () => act(() => api('/api/bot/llm/test', {})).then(x => { if (x) render(x); }), 'primary sm', 'play'));
}

function btLlmBox(s, render) {
  const call = (route, msg) => act(() => api('/api/bot/llm/' + route, {}), msg).then(x => { if (x) render(x); });
  const pct = s.toplam ? Math.floor(100 * s.alinan / s.toplam) : 0;
  const t = s.test && !s.test.saglayici ? s.test : {};          // uzak sağlayıcının testi değil
  const low = s.memory_gb != null && s.memory_gb < s.min_memory_gb;
  const hardware = h('div', { class: 'small muted' }, T('Bu bilgisayar: {0} GB bellek, {1} çekirdek.', s.memory_gb ?? '?', s.cores ?? '?'),
    low ? h('b', { style: { color: 'var(--warn)', marginLeft: '6px' } }, T('Önerilen en az {0} GB.', s.min_memory_gb)) : null);
  if (!s.supported) return h('div', { class: 'alert hata' }, icon('alert'), h('div', null, T('Bu bilgisayarın işlemcisi için hazır dil modeli sunucusu yok: Normal kipi kullan.')));
  const step1 = s.calisiyor
    ? h('div', { class: 'dl-box' }, h('b', null, s.durum === 'kuruluyor' ? T('Kuruluyor…') : T('İndiriliyor: %{0}', pct)),
      h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } }))),
      h('div', { class: 'small muted dl-info' }, [`${fmtBytes(s.alinan)} / ${fmtBytes(s.toplam)}`, s.hiz ? `${fmtBytes(s.hiz)}/${T('sn')}` : null,
        s.time_left_sec != null && s.hiz ? T('kalan {0}', fmtDur(s.time_left_sec)) : null, s.parca].filter(Boolean).join(' · ')),
      h('div', { class: 'row' }, btn(T('Durdur'), () => call('durdur', T('İndirme durduruluyor…')), 'ghost sm', 'stop')))
    : ['kurulu', 'hazir'].includes(s.durum)
      ? h('div', { class: 'bt-llm-step' }, icon('check'), h('div', null, h('b', null, T('Kuruldu')), h('div', { class: 'small muted' }, s.model + ' · llama.cpp ' + s.surum)),
        btn(T('Kaldır'), async () => { if (await confirmBox(T('Dil modeli silinsin mi?'), T('İndirilen 2,5 GB silinir; Gelişmiş kip yeniden kurulana dek Normal kip gibi çalışır.'), { ok: T('Sil'), danger: true })) call('sil', T('Silindi.')); }, 'ghost sm', 'trash'))
      : h('div', { class: 'bt-llm-step' }, icon('download'), h('div', null, h('b', null, s.durum === 'hata' ? T('Kurulamadı') : s.durum === 'durdu' ? T('İndirme durduruldu') : T('1. Dil modelini kur')),
        h('div', { class: 'small muted' }, s.durum === 'hata' ? s.hata : T('{0} indirilir (yarım kalırsa kaldığı yerden sürer).', fmtBytes(s.boyut))), hardware),
        btn(s.durum === 'hata' || s.durum === 'durdu' || s.partial ? T('Sürdür') : T('İndir ve kur'), () => call('kur'), 'primary sm', 'download'));
  const installed = ['kurulu', 'hazir'].includes(s.durum);
  const step2 = h('div', { class: 'bt-llm-step' }, icon(s.durum === 'hazir' ? 'check' : 'play'),
    h('div', null, h('b', null, s.durum === 'hazir' ? T('Kurulum tamamlandı: model çalışıyor') : T('2. Test et')),
      h('div', { class: 'small muted' }, t.durum === 'calisiyor' ? T('Model açılıyor ve kısa bir soru soruluyor (ilk açılış yarım dakikayı bulabilir)…')
        : t.durum === 'hata' ? t.hata : t.durum === 'ok' || s.last_test ? T('Açılış {0} sn, yanıt {1} sn: "{2}"', (t.acilis_sn ?? s.last_test?.acilis_sn), (t.sure_sn ?? s.last_test?.sure_sn), (t.yanit ?? s.last_test?.yanit ?? ''))
        : T('Model bir kez açılıp kısa bir soruya yanıt verir; yanıt gelirse kurulum tamamdır.'))),
    t.durum === 'calisiyor' ? h('span', { class: 'spin' }) : btn(T('Test et'), () => call('test'), (installed && s.durum !== 'hazir' ? 'primary' : 'ghost') + ' sm', 'play', { disabled: !installed }));
  return h('div', { class: 'stack', style: { gap: '4px' } }, step1, step2,
    s.durum === 'hazir' ? h('div', { class: 'alert bilgi' }, icon('info'), h('div', null, T('Oyun açılınca model de açılır; botların sohbeti ve kararları onunla verilir. Model yetişemezse botlar Normal kipteki gibi davranır.'))) : null);
}

// ------------------------------------------------------------------ botların oyun ayarı profili (bot/game_settings.py)
function btGameSettingCard(d) {
  const game_settings = JSON.parse(JSON.stringify(d.ayarlar.oyun_ayari || { profil: 'standart', degerler: {} }));
  const info = BT.liste?.oyun_ayarlari || { hazir: [], alanlar: [] };
  const options = [['standart', T('Standart (oyunun kendi değerleri)')], ['oyuncu', T('Benim oyun ayarlarım')]]
    .concat(info.hazir.map(x => [x.id, T(x.ad)]), [['ozel', T('Özel')]]);
  const save = () => btSetting('oyun_ayari', game_settings);
  const sec = h('select', { class: 'input', onchange: e => { game_settings.profil = e.target.value; save(); btFill(special, renderCustom()); description.textContent = describe(); } },
    options.map(([v, name]) => h('option', { value: v, selected: game_settings.profil === v }, name)));
  const describe = () => {
    const preset = info.hazir.find(x => x.id === game_settings.profil);
    return preset ? T(preset.aciklama) : game_settings.profil === 'oyuncu' ? T('Botlar da Oyun Ayarları sayfasındaki çarpanlarla oynar (kolay ayarda onlar da hızlı gelişir).')
      : game_settings.profil === 'ozel' ? T('Aşağıdaki çarpanlar yalnız botlara uygulanır.') : T('Botlar oyunun kendi ödülleri ve uzaylılarıyla oynar; senin oyun ayarların onları etkilemez.');
  };
  const description = h('div', { class: 'help' }, describe());
  const renderCustom = () => game_settings.profil !== 'ozel' ? null : info.alanlar.map(a => btRow(T(a.ad), T(a.aciklama),
    btSlider(game_settings.degerler[a.anahtar] ?? 1, v => { game_settings.degerler[a.anahtar] = v; save(); }, { min: a.en_az, max: a.en_cok, step: 0.05, fmt: v => '×' + v.toFixed(2) })));
  const special = h('div', null, renderCustom());
  return h('div', { class: 'card' }, h('h2', null, icon('sliders'), T('Oyun ayarları')),
    h('p', { class: 'desc' }, T('Botların ödül ve zorluk çarpanları senin oyun ayarlarından ayrı: kendine kolay ayar seçsen de botlar burada seçtiğinle gelişir.')),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Profil')), description), h('div', { class: 'ctl' }, sec)), special);
}
