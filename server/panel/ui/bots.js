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
  up: '<path d="M12 19V5"/><path d="M6 11l6-6 6 6"/>',
  down: '<path d="M12 5v14"/><path d="M6 13l6 6 6-6"/>',
  list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><circle cx="3.5" cy="6" r="1"/><circle cx="3.5" cy="12" r="1"/><circle cx="3.5" cy="18" r="1"/>',
});

const BT = { liste: null, pid: null, d: null, tab: 'genel', timer: null, pending: {} };
const BT_MODES = {
  simple: { ad: N('Simple'), ic: 'bot', summary: N('Bots that wander the maps like NPCs without changing maps. They kill aliens; enemy bots attack or flee depending on strength when they see you.') },
  normal: { ad: N('Normal'), ic: 'users', summary: N('Like a real player: starts at the base, does quests, grinds, buys ships and lasers, does PvP, founds a clan, makes friends, chats. Each bot has its own personality and decisions.') },
  advanced: { ad: N('Advanced'), ic: 'brain', summary: N('Normal mode plus a language model (built-in Qwen3 4B, OpenAI, Claude, Gemini or your own local LLM): bots really talk with you and with each other, think over your requests and decide, and answer calls for help.') },
};
const BT_ARCHETYPE = { grinder: N('PvE grinder'), hunter: N('PvP hunter'), sosyal: N('Social'), trader: N('Trader'), quester: N('Quester'), casual: N('Relaxed'), lider: N('Leader') };
const BT_TARGET = { grinding: N('Farming aliens'), gorev: N('Doing quests'), pvp: N('Hunting PvP'), shopping: N('Shopping'), resting: N('Resting'),
  exploring: N('Exploring'), grup: N('In a group'), yardim: N('Going to help'), simple: N('Farming aliens'), selling: N('Selling cargo'),
  mod: N('In a mode'), kapi: N('In a galaxy gate'), duello: N('Dueling') };
const BT_PERMS = {
  shop: [N('Shop'), N('They buy ships, lasers, generators and drones with credits and uridium.')],
  gorev: [N('Quests'), N('They complete the quest chain.')],
  pvp: [N('PvP'), N('Bots fight each other.')],
  attack_player: [N("Don't attack you"), N('Bots of the enemy company may attack when they see you.')],
  sohbet: [N('Chat'), N('They write in global, company, clan and group chat, and reply to whispers.')],
  klan: [N('Joining clans'), N('They apply to clans that match their personalities (yours too).')],
  clan_found: [N('Founding clans'), N('Bots with a leader spirit and plenty of money found clans and evaluate applications.')],
  arkadas: [N('Friendship'), N('They consider friend requests and send requests to people they have played with.')],
  grup: [N('Group'), N('They can accept group invites and follow the leader in the group.')],
  auction: [N('Auction'), N('They bid in auctions and compete with you.')],
  yardim: [N('Calls for help'), N('Some bots come to a call for help in chat (e.g. "2-4 help").')],
  kargo: [N('Cargo and ore selling'), N("They collect aliens' cargo boxes; when the cargo is full they return to their own station (X-1, X-8) and sell the ore.")],
  roket: [N('Rockets'), N("They buy rockets and fire them in combat (from R-310 to PLT-3030, depending on their money).")],
  custom_ammunition: [N('Special ammo'), N("They use x2/x3 (MCB-25/50) on tough aliens and RSB-75 in PvP, bought with uridium. If off, LCB-10 only.")],
  ekstra: [N("CPUs and extras"), N("They buy and use repair bots, the rocket CPU, cargo CPU, HM-7, jump and cloaking CPUs, Insta-Shield and Smart Bomb.")],
  mayin: [N('Mines'), N('Aggressive bots buy mines and drop them behind them when fleeing from you.')],
  lab: [N('Refining and lab'), N('They refine ore from their cargo and load it into their lasers, rockets and shields (Prometid, Duranium, Promerium, Seprom).')],
  skylab: [N('Skylab'), N('They build and upgrade a Skylab; they transport its ore to their ship and sell it or use it in the lab.')],
  technology: [N('Tech items'), N("They build tech items in the Assembly (Backup Shields, Battle Repair Bot, Chain Impulse, Energy Leech, Precision Targeter) and use them in combat.")],
  booty: [N('Booty boxes'), N('They open the key-locked boxes on the map with keys; for green boxes they buy a key with uridium if it is worth it.')],
  assembly: [N('Assembly'), N("They use the resources collected from aliens to build keys, items and ammo in the Assembly.")],
  kapi: [N('Galaxy Gates'), N('They collect parts at the generator with gate energy (or uridium), build the gate and run it once they are strong enough.')],
  etkinlik: [N("Events and passes"), N('They take part in events (event aliens, boxes and currency) and progress the Battle Pass and Season Pass to collect rewards.')],
  clan_diplomacy: [N('Clan diplomacy'), N("Bot clan leaders propose alliances, non-aggression pacts, wars and peace, and answer incoming requests (including your clan's). They don't attack allies and prioritise members of clans they are at war with.")],
  clan_cbs: [N('Clan battle stations'), N('Bot clans build, upgrade and defend Clan Battle Stations with their treasury; they race you and each other for the free asteroids. While on, there are no fake rival clans.')],
  clan_order: [N('Clan orders'), N('You give the bots in your clan orders in clan chat: "everyone farm", "3 of you go to 4-4", "defend our base", "come help me", "get lf-3", "use goliath", "full shield", "stop". They obey according to their loyalty.')],
  gate_filler: [N('Gate fillers'), N('When you write "need fillers for hades" in chat, bots with a high enough level say "inv me". Bots in your group enter the Galaxy Gate, Hades, LoW or QZ with you and you clear the waves together.')],
  modes: [N('Event and PvE modes'), N('Event gates, Voyagers, Trinity, Astral, Black Light, Echoes, LoW, Vortex, Mimesis, World Boss, Apotheosis, Labyrinth; Dispatch and Galaxy Trek. They enter the modes they can handle and are rewarded for how far they get.')],
  box_stealing: [N('Cargo stealing'), N("Rude bots now and then collect someone else's cargo box (yours too); if it belongs to their own company they lose honor.")],
};
const BT_CLASS_NAME = s => s === '4-X' ? '4-1…4-4' : s;
const btFill = (el, ...k) => el.replaceChildren(...k.flat(Infinity).filter(x => x != null && x !== false));
const btCompany = ['MMO', 'EIC', 'VRU'];
function btArt(name, backup, cls = 'bt-art') {         // görsel gelmediyse (Orders.md) var olan bir görsel
  const im = art(name, cls);
  im.onerror = () => { im.onerror = null; im.src = 'images/' + backup + '.webp'; };
  return im;
}
const btWorldName = id => (BT.liste?.worlds || []).find(w => w.id === id)?.ad || T('Unassigned');

// ------------------------------------------------------------------ giriş noktası
async function renderBots() {
  const r = await act(() => api('/api/botlar')); if (!r || S.page !== 'bots') return;
  BT.liste = r;
  if (BT.pid && !r.liste.some(p => p.id === BT.pid)) BT.pid = null;
  if (!BT.pid) return btLibrary();
  btEditor();
}
function btOpen(pid, tab) { BT.pid = pid; BT.tab = tab || 'genel'; renderBots(); }

function btCompanyBar(f) {
  const top = f.reduce((a, b) => a + b, 0) || 1;
  return h('div', { class: 'bt-companies', title: btCompany.map((x, i) => x + ' ' + f[i]).join(' · ') },
    f.map((n, i) => h('i', { class: btCompany[i].toLowerCase(), style: { width: (100 * n / top) + '%' } })));
}

// ================================================================== KİTAPLIK
function btLibrary() {
  const r = BT.liste;
  const card = p => h('div', { class: 'bt-card', onclick: e => { if (!e.target.closest('button')) btOpen(p.id); } },
    h('div', { class: 'bt-card-top k-' + p.mode }, btArt('bot_kip_' + p.mode, 'drone_editor', 'bt-card-art'),
      h('div', null, h('b', null, p.ad), h('div', { class: 'small muted' }, T(BT_MODES[p.mode].ad) + ' · ' + T('{0} bots', p.adet)))),
    h('div', { class: 'bt-card-body' },
      h('div', { class: 'row wrap', style: { gap: '6px' } }, p.world ? badge([icon('globe'), btWorldName(p.world)], 'info') : badge(T('Not assigned to a world'), 'warn'),
        p.mode !== 'simple' ? badge(p.progression === 'jumpstart' ? 'Jumpstart' : 'Progressive', '') : null),
      btCompanyBar(p.companies),
      h('div', { class: 'small muted' }, p.level_avg != null ? T('Average level {0} · highest {1}', p.level_avg, p.level_max)
        : T('Not played yet: bots start on first login.')),
      p.aciklama ? h('div', { class: 'small ellipsis' }, p.aciklama) : null),
    h('div', { class: 'bt-card-bottom' }, btn(T('Open'), () => btOpen(p.id), 'sm primary', 'edit'),
      btn('', ev => btPackMenu(ev.currentTarget, p), 'sm ghost icon', 'more', { title: T('More') })));
  btFill($('#content'), h('div', { class: 'stack' },
    h('div', { class: 'card bt-intro' }, btArt('bot_login', 'drone_welcome', 'bt-intro-art'),
      h('div', null, h('h2', null, icon('bot'), T('Bots')),
        h('p', { class: 'desc' }, T("Create a bot pack and assign it to a world: while you play in that world, the bots are on the maps like real players. The roster is generated once; you meet the same bots every time you log in, and they keep progressing even when you're away.")),
        h('div', { class: 'row wrap' }, btn(T('New bot pack'), () => btWizard(), 'primary', 'plus')))),
    h('div', { class: 'bt-grid' }, r.liste.map(card), h('button', { class: 'bt-card yeni', onclick: () => btWizard() }, icon('plus'), h('span', null, T('New bot pack'))))));
}

function btPackMenu(anchor, p) {
  popMenu(anchor, [
    { label: T('Open'), ic: 'edit', fn: () => btOpen(p.id) },
    { label: T('Assign to world'), ic: 'globe', fn: () => btAssignMenu(anchor, p) },
    { label: T('Rename'), ic: 'edit', fn: async () => {
      const name = await promptBox(T('Rename'), T('Pack name'), p.ad); if (name == null) return;
      if (await act(() => api('/api/bot/update', { id: p.id, name }), T('Saved.'))) renderBots(); } },
    '-',
    { label: T('Delete'), ic: 'trash', danger: true, fn: async () => {
      if (!await confirmBox(T('Delete "{0}"?', p.ad), T("The pack and the bots' progress are deleted (kept in the save/botlar/_silinenler folder)."), { ok: T('Delete'), danger: true })) return;
      const x = await act(() => api('/api/bot/sil', { id: p.id }), T('Bot pack deleted.')); if (x) { BT.liste = x; if (BT.pid === p.id) BT.pid = null; renderBots(); } } },
  ]);
}

function btAssignMenu(anchor, p) {
  const items = BT.liste.worlds.map(w => ({ label: w.ad + (p.world === w.id ? '  ✓' : ''), ic: p.world === w.id ? 'check' : 'globe',
    fn: () => btAssign(p, w.id) }));
  items.push('-', { label: T('Remove assignment'), ic: 'x', fn: () => btAssign(p, null), disabled: !p.world });
  popMenu(anchor, items);
}
async function btAssign(p, did) {
  const old = did && BT.liste.liste.find(x => x.world === did && x.id !== p.id);
  if (old && !await confirmBox(T("Change the world's pack?"), T('The world "{0}" currently has the pack "{1}"; that pack will be left unassigned.', btWorldName(did), old.ad))) return;
  const x = await act(() => api('/api/bot/assign', { id: p.id, world: did }), did ? T('"{0}" is now in the world "{1}".', p.ad, btWorldName(did)) : T('Assignment removed.'));
  if (x) { BT.liste = x; renderBots(); }
}

// ================================================================== SİHİRBAZ
function btWizard() {
  const r = BT.liste;
  const w = { ad: '', aciklama: '', world: (r.worlds.find(d => !r.liste.some(p => p.world === d.id)) || r.worlds[0] || {}).id || null, mode: 'normal',
    progression: 'progressive', adet: 80, dil: 'mixed', name_lang: 'mixed', name_source: 'uretim', company_distribution: [1, 1, 1], ozel: '', settings: { jumpstart_hours: 60, simple_power: 1, simple_friendly: 0.5,
      simple_maps: { 'X-1': 2, 'X-2': 2, 'X-3': 2, 'X-4': 2, '4-X': 3, 'X-5': 1, 'X-6': 1, 'X-7': 1, 'X-8': 1, '4-5': 2 } } };
  let step = 0;
  const body = h('div', { class: 'stack', style: { gap: '14px' } });
  const footer = h('div', { class: 'row', style: { gap: '8px', justifyContent: 'flex-end', width: '100%' } });
  const m = modal({ title: T('New bot pack'), wide: true, body: body, foot: footer });
  const steps = [T('Name and world'), T('Mode'), T('Settings')];
  function render() {
    const parent = h('div', { class: 'bt-steps' }, steps.map((a, i) => h('span', { class: i === step ? 'on' : i < step ? 'tamam' : '' }, h('b', null, i + 1), a)));
    btFill(body, parent, [btStep1, btStep2, btStep3][step](w, render));
    btFill(footer, btn(T('Cancel'), () => m.close(), 'ghost'), h('span', { class: 'spacer' }),
      step ? btn(T('Back'), () => { step--; render(); }, 'ghost', 'arrowL') : null,
      step < 2 ? btn(T('Next'), () => {
        if (step === 0 && !w.ad.trim()) return toast(T('Give the bot pack a name.'), 'err');
        step++; render();
      }, 'primary') : btn(T('Create'), async () => {
        const x = await act(() => api('/api/bot/create', w), T('Bot pack created: {0}', w.ad.trim()));
        if (!x) return;
        m.close(); BT.liste = x; btOpen(x.yeni, w.mode === 'advanced' ? 'advanced' : 'roster');
      }, 'primary', 'check'));
  }
  render();
}

function btStep1(w) {
  const r = BT.liste;
  const name = h('input', { class: 'input', value: w.ad, placeholder: T('e.g. Crowded Server, Hunters'), maxlength: 40, oninput: e => { w.ad = e.target.value; } });
  const is_open = h('textarea', { class: 'input', rows: 2, maxlength: 240, placeholder: T('What kind of server is this pack? (optional)'), oninput: e => { w.aciklama = e.target.value; } }, w.aciklama);
  const world = h('select', { class: 'input', onchange: e => { w.world = e.target.value || null; } },
    r.worlds.map(d => {
      const p = r.liste.find(x => x.world === d.id);
      return h('option', { value: d.id, selected: w.world === d.id }, d.ad + (p ? ' — ' + T('Currently: {0}', p.ad) : ''));
    }), h('option', { value: '', selected: !w.world }, T('No assignment for now')));
  return h('div', { class: 'stack', style: { gap: '14px' } }, field(T('Name'), name), field(T('Description'), is_open),
    field(T('World to run in'), world, h('div', { class: 'small muted' }, T('When a player enters the game in this world, the pack kicks in. A world can have only one pack.'))));
}

function btStep2(w, render) {
  const card = k => h('button', { type: 'button', class: 'bt-mode' + (w.mode === k ? ' on' : ''), onclick: () => { w.mode = k; render(); } },
    btArt('bot_kip_' + k, 'drone_editor', 'bt-mode-art'), h('b', null, icon(BT_MODES[k].ic), T(BT_MODES[k].ad)), h('div', { class: 'small' }, T(BT_MODES[k].summary)));
  return h('div', { class: 'stack', style: { gap: '12px' } }, h('div', { class: 'bt-modes' }, ['simple', 'normal', 'advanced'].map(card)),
    w.mode === 'advanced' ? btLlmWarning(true) : null);
}

function btLlmWarning(wizard = false) {
  return h('div', { class: 'alert warning' }, icon('alert'), h('div', null,
    h('b', null, T('Advanced mode can put a heavy load on your computer.')),
    h('div', null, T("The bots' chat and decisions come from the Qwen3 4B (Q4_K_M) language model running on your computer: about 2.5 GB download, 4 GB of free memory and a powerful CPU or graphics card required. The game may slow down on weak computers.")),
    h('div', { style: { marginTop: '6px' } }, T("If your computer can't handle it, pick a provider like OpenAI, Claude, Gemini or DeepSeek with your API key, or your own local LLM server (Ollama, LM Studio), on the Advanced tab; bots can then also speak their own languages.")),
    h('div', { style: { marginTop: '6px' } }, T("If your computer can't handle it, Normal mode still gives a very advanced bot experience: bots still decide by personality, progress, found clans and chat using templates.")),
    wizard ? h('div', { class: 'small muted', style: { marginTop: '6px' } }, T("You'll install and test the model from the Advanced tab after the pack is created.")) : null));
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
    [['mixed', mixedName]].concat(BT_LANGS).map(([v, name]) => h('option', { value: v, selected: v === value }, name)));
}
// adların kaynağı (panel/botlar.AD_KAYNAKLARI): üretici gerçek sunucuların üslubuyla ya da dostats.info'daki gerçek oyuncular
const BT_NAME_SOURCE_DESCRIPTION = N("Generated names are decorated like on real servers (-»Λd«-, ツ, ᵀᴹ). With DOStats, names and clan tags are taken from real players on dostats.info (needs internet; applies to newly added bots and regeneration).");
function btNameSource(value, onchange) {
  return h('select', { class: 'input', onchange: e => onchange(e.target.value) },
    [['uretim', T('Generated')], ['dostats', T('DOStats (real players)')]].map(([v, name]) => h('option', { value: v, selected: v === value }, name)));
}
// dahili dil modeli yalnız İngilizce; başka bir sağlayıcı seçiliyse Gelişmiş kipte de dil serbest (bot/llm_provider.py)
const btLangLocked = mode => mode === 'advanced' && !BT.liste?.llm_multilingual;
function btChatLang(mode, value, onchange) {
  return btLangLocked(mode) ? btPickLang('en', () => {}, T("Each bot in its name's language"), true) : btPickLang(value, onchange, T("Each bot in its name's language"));
}
function btDistribution(f, onchange) {
  return h('div', { class: 'row bt-distribution', style: { gap: '8px' } }, btCompany.map((x, i) => h('label', { class: 'row', style: { gap: '4px' } },
    badge(x, x.toLowerCase()), btNumber(f[i], v => { f[i] = v; onchange(f); }, { min: 0, max: 100 }))));
}

function btStep3(w, render) {
  if (w.mode === 'simple') return btSimpleSettings(w.settings, () => render(), true);
  return h('div', { class: 'stack', style: { gap: '14px' } },
    field(T('Total bots'), btSlider(w.adet, v => { w.adet = v; }, { min: 5, max: 3000, step: 5 }),
      h('div', { class: 'small muted' }, T('Not all are online at once: each bot has its own play hours. Hundreds of bots are no problem; the number shown as ships on your map is limited.'))),
    field(T('Company distribution (ratio)'), btDistribution(w.company_distribution, f => { w.company_distribution = f; })),
    field(T('Progress'), btSeg([['progressive', 'Progressive'], ['jumpstart', 'Jumpstart']], w.progression, v => { w.progression = v; render(); }),
      h('div', { class: 'small muted' }, w.progression === 'progressive'
        ? T('Everyone starts at level 1 as at the beginning of the game, with the Phoenix at their own base, and develops like a real player.')
        : T('The roster starts with a realistic distribution: many beginners, many mid-level, few strong players. Equipment, money and levels are consistent.'))),
    w.progression === 'jumpstart' ? field(T('Average play time (hours)'), btSlider(w.settings.jumpstart_hours, v => { w.settings.jumpstart_hours = v; }, { min: 5, max: 500, step: 5 })) : null,
    field(T('Name language'), btPickLang(w.name_lang, v => { w.name_lang = v; }, T('Mixed')),
      h('div', { class: 'small muted' }, T("The bots' usernames look like those of players of this language."))),
    field(T('Name source'), btNameSource(w.name_source, v => { w.name_source = v; }),
      h('div', { class: 'small muted' }, T(BT_NAME_SOURCE_DESCRIPTION))),
    field(T('Chat language'), btChatLang(w.mode, w.dil, v => { w.dil = v; }),
      h('div', { class: 'small muted' }, btLangLocked(w.mode) ? T('In Advanced mode bots speak English only (the language model is weak in other languages).')
        : T('The language bots use in chat. With "Each bot in its name\'s language", a bot with a German name speaks German.'))),
    field(T('Your own bots (optional)'), btCustomField(w.ozel, v => { w.ozel = v; })));
}

// kullanıcının kendi botları (panel/botlar.ozel_cozumle): satır başına "ad, firma, davranış, dil"; ad dışındakiler isteğe bağlı
function btCustomField(value, onchange) {
  return h('div', { class: 'stack', style: { gap: '6px' } },
    h('textarea', { class: 'input bt-custom', rows: 5, spellcheck: false, placeholder: 'Kaan\nStarHunter, VRU\nOldMiner, MMO, kasici, tr\nRedBaron, EIC, avci', oninput: e => onchange(e.target.value) }, value || ''),
    h('div', { class: 'small muted' }, T('One bot per line: name, then optionally company (MMO, EIC, VRU), behaviour ({0}) and chat language ({1}). Anything left out, and all other bots, are generated as usual.',
      Object.keys(BT_ARCHETYPE).join(', '), BT_LANGS.map(d => d[0]).join(', '))));
}

function btSimpleSettings(a, render, wizard = false, save = null) {
  const top = () => Object.entries(a.simple_maps).reduce((s, [k, v]) => s + v * (k === '4-X' ? 4 : ['4-5'].includes(k) ? 1 : 3), 0);
  const total = h('b', null, top());
  const parent = h('div', { class: 'bt-classes' }, (BT.liste?.classes || Object.keys(a.simple_maps)).map(s => h('label', { class: 'bt-class' },
    h('span', null, BT_CLASS_NAME(s)), btNumber(a.simple_maps[s] ?? 0, v => { a.simple_maps[s] = v; total.textContent = top(); save && save(); }, { min: 0, max: 20 }))));
  return h('div', { class: 'stack', style: { gap: '14px' } },
    field(T('Bots per map'), parent, h('div', { class: 'small muted' }, T("On company maps, once for each company's map (X-3 = 1-3, 2-3, 3-3), and once for shared maps (4-1–4-5). Total:"), total)),
    field(T('Strength ratio'), btSlider(a.simple_power, v => { a.simple_power = v; save && save(); }, { min: 0.3, max: 3, step: 0.1, fmt: v => '×' + v.toFixed(1) }),
      h('div', { class: 'small muted' }, T("Based on the equipment of the map's typical player: 1 is the same, 2 is twice as strong, 0.5 is weaker."))),
    field(T('Friendly bot share'), btSlider(a.simple_friendly, v => { a.simple_friendly = v; save && save(); }, { min: 0, max: 1, step: 0.05, fmt: v => '%' + Math.round(v * 100) }),
      h('div', { class: 'small muted' }, T("How many of the bots on a company map are from that map's company (the rest are enemies)."))));
}

// ================================================================== EDİTÖR
const BT_TABS = [
  ['genel', N('Public'), 'sliders'], ['roster', N('Roster'), 'users'], ['behavior', N('Behavior'), 'target'], ['access', N('Permissions'), 'shield'],
  ['sohbet', N('Chat'), 'chat'], ['clans', N('Clans'), 'star'], ['simple', N('Simple mode'), 'bot'], ['advanced', N('Advanced mode'), 'brain'],
];

async function btEditor() {
  const [d] = await Promise.all([act(() => api('/api/bot?id=' + encodeURIComponent(BT.pid))), loadGameImages()]);   // oyunun görselleri: gemi, rütbe
  if (!d || S.page !== 'bots') return;
  BT.d = d;
  const tabs = BT_TABS.filter(([k]) => (k !== 'simple' || d.mode === 'simple') && (k !== 'advanced' || d.mode === 'advanced')
    && (d.mode !== 'simple' || !['behavior', 'sohbet'].includes(k)));
  if (!tabs.some(([k]) => k === BT.tab)) BT.tab = 'genel';
  btFill($('#content'), h('div', { class: 'stack' },
    h('div', { class: 'card bt-bar' }, btn('', () => { BT.pid = null; renderBots(); }, 'ghost icon', 'arrowL', { title: T('Bot packs') }),
      btArt('bot_kip_' + d.mode, 'drone_editor', 'bt-bar-art'),
      h('div', { class: 'bt-bar-name' }, h('div', { class: 'row', style: { gap: '8px' } }, h('b', null, d.ad), badge(T(BT_MODES[d.mode].ad), 'orange'),
        d.world ? badge([icon('globe'), btWorldName(d.world)], 'info') : badge(T('Not assigned to a world'), 'warn')),
        h('div', { class: 'muted small ellipsis' }, T('{0} bots', d.adet) + (d.level_avg != null ? ' · ' + T('average level {0}', d.level_avg) : ''))),
      h('span', { class: 'spacer' }), h('span', { class: 'we-save-status', id: 'bt-save' }),
      btn(T('Assign to world'), ev => btAssignMenu(ev.currentTarget, d), 'sm', 'globe'),
      btn('', ev => btPackMenu(ev.currentTarget, d), 'sm ghost icon', 'more', { title: T('More') })),
    d.server_in_pack ? h('div', { class: 'alert ' + (d.restart_needed ? 'warning' : 'info') }, icon(d.restart_needed ? 'alert' : 'info'),
      h('div', null, d.restart_needed ? T('The pack changed after the game opened: changes take effect when the server restarts.')
        : T("This pack is currently running in the game. The roster list comes from the server's per-minute save.")),
      d.restart_needed ? btn(T('Restart the server'), () => act(() => api('/api/bot/server_restart', {}), T('Server is restarting.')).then(() => setTimeout(btEditor, 1500)), 'sm orange', 'refresh') : null) : null,
    h('div', { class: 'seg bt-tabs' }, tabs.map(([k, name, iconEl]) => h('button', { type: 'button', class: BT.tab === k ? 'on' : '',
      onclick: () => { BT.tab = k; btEditor(); } }, icon(iconEl), T(name)))),
    h('div', { id: 'bt-area' }, ({ genel: btGeneral, roster: btRoster, behavior: btBehavior, access: btAccess, sohbet: btChat, clans: btClans, simple: btSimple, advanced: btAdvanced })[BT.tab](d))));
}

function btSaveStatus(state) {
  const el = $('#bt-kayit'); if (!el) return;
  el.className = 'we-save-status ' + state;
  btFill(el, ...(state === 'kaydediliyor' ? [h('span', { class: 'spin' }), T('Saving…')] : state === 'kaydedildi' ? [icon('check'), T('Saved')] : []));
}
// değişiklik: 450 ms bekleyip tek istekte (ayarlar birleştirilir)
function btPatch(fields) {
  for (const [k, v] of Object.entries(fields)) {
    if (k === 'settings') BT.pending.settings = Object.assign(BT.pending.settings || {}, v);
    else BT.pending[k] = v;
  }
  btSaveStatus('kaydediliyor');
  clearTimeout(BT.timer);
  BT.timer = setTimeout(async () => {
    const body = Object.assign({ id: BT.pid }, BT.pending); BT.pending = {};
    const x = await act(() => api('/api/bot/update', body));
    if (!x) return btSaveStatus('');
    const mode = BT.d.mode;
    BT.d = x; btSaveStatus('kaydedildi');
    if (body.mode && body.mode !== mode || body.ad) btEditor();
  }, 450);
}
const btSetting = (k, v) => btPatch({ settings: { [k]: v } });

function btRow(name, description, ctl) {
  return h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, name), description ? h('div', { class: 'help' }, description) : null), h('div', { class: 'ctl' }, ctl));
}
function btKey(value, onchange) {
  return h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: !!value, onchange: e => onchange(e.target.checked) }), h('span'));
}

// ------------------------------------------------------------------ Genel
function btGeneral(d) {
  const a = d.settings;
  const name = h('input', { class: 'input', value: d.ad, maxlength: 40, onchange: e => btPatch({ ad: e.target.value }) });
  const is_open = h('input', { class: 'input', value: d.aciklama || '', maxlength: 240, placeholder: T('No description.'), onchange: e => btPatch({ aciklama: e.target.value }) });
  const pickMode = async v => {
    if (v === d.mode) return;
    if (v === 'advanced' && !await confirmBox(T('Switch to Advanced mode?'), btLlmWarning(), { ok: T('Switch to Advanced mode') })) return;
    if ((v === 'simple') !== (d.mode === 'simple') && !await confirmBox(T('Change the mode?'),
      T('In Simple mode the roster is spread across maps and the count comes from the map settings; in Normal and Advanced mode bots develop on their own. Progress is kept.'))) return;
    btPatch({ mode: v });
  };
  const fg = a.company_power || [1, 1, 1];
  return h('div', { class: 'stack' },
    h('div', { class: 'card' }, h('h2', null, icon('edit'), T('Pack')),
      btRow(T('Name'), null, name), btRow(T('Description'), null, is_open),
      btRow(T('Mode'), T(BT_MODES[d.mode].summary), btSeg(['simple', 'normal', 'advanced'].map(k => [k, T(BT_MODES[k].ad)]), d.mode, pickMode)),
      d.mode !== 'simple' ? btRow(T('Progress'), d.progression === 'jumpstart' ? T('The roster starts with a realistic distribution (on first launch).') : T('Everyone starts at level 1 at their own base.'),
        btSeg([['progressive', 'Progressive'], ['jumpstart', 'Jumpstart']], d.progression, v => btPatch({ progression: v }))) : null,
      d.mode !== 'simple' && d.progression === 'jumpstart' ? btRow(T('Average play time (hours)'), T('The middle of the Jumpstart distribution: a few bots start at multiples of it, most start below.'),
        btNumber(a.jumpstart_hours, v => btSetting('jumpstart_hours', v), { min: 1, max: 2000 })) : null),
    d.mode !== 'simple' ? h('div', { class: 'card' }, h('h2', null, icon('clock'), T('Time and progress')),
      btRow(T('Progression speed'), T('Multiplier of gains: 1 is the pace of a real player.'), btSlider(a.hiz, v => btSetting('hiz', v), { min: 0.1, max: 10, step: 0.1, fmt: v => '×' + v.toFixed(1) })),
      btRow(T('Tendency to be online'), T("Bots' desire to be online according to their play hours; the higher it is, the more bots at once."),
        btSlider(a.online_ratio, v => btSetting('online_ratio', v), { min: 0.05, max: 2, step: 0.05, fmt: v => '%' + Math.round(v * 100) })),
      btRow(T('Most online at the same time'), T('0: unlimited.'), btNumber(a.max_online, v => btSetting('max_online', v), { min: 0, max: 3000 })),
      btRow(T("Progress while you're away (hours)"), T('On return to the game, at most this much of the elapsed time is simulated. 0: bots progress only while you play.'),
        btNumber(a.catchup_hours, v => btSetting('catchup_hours', v), { min: 0, max: 48 })),
      d.progression !== 'jumpstart' ? btRow(T('New pilot sign-up (seconds)'), T('Progressive: on average one new pilot per company signs up and starts playing every this many seconds (like a freshly opened server; they do not all spawn at once). 0: everyone is signed up from the start.'),
        btNumber(a.signup_sec ?? 15, v => btSetting('signup_sec', v), { min: 0, max: 300 })) : null,
      btRow(T('Company strength'), T("Development multiplier of the company's bots (1 = equal)."), h('div', { class: 'row', style: { gap: '8px' } }, btCompany.map((x, i) =>
        h('label', { class: 'row', style: { gap: '4px' } }, badge(x, x.toLowerCase()), btNumber(fg[i], v => { fg[i] = v; btSetting('company_power', fg); }, { min: 0.2, max: 5, step: 0.1 })))))) : null,
    btGameSettingCard(d),
    h('div', { class: 'card' }, h('h2', null, icon('trash'), T('Progression')),
      btRow(T('Reset progress'), T("The bots' level, money, equipment, clans and relationships are deleted; names and personalities stay."),
        btn(T('Reset'), async () => {
          if (!await confirmBox(T('Reset progress?'), T('Bots start from scratch (redistributed in Jumpstart).'), { ok: T('Reset'), danger: true })) return;
          const x = await act(() => api('/api/bot/sifirla', { id: d.id }), T('Progress reset.')); if (x) { BT.d = x; btEditor(); }
        }, 'sm danger', 'trash'))));
}

// ------------------------------------------------------------------ Kadro
function btRoster(d) {
  const byArchetype = {};
  d.roster.forEach(b => { byArchetype[b.archetype] = (byArchetype[b.archetype] || 0) + 1; });
  const f = d.company_distribution.slice();
  let count = d.adet, lang = d.dil || 'mixed', nameLang = d.name_lang || lang, nameSource = d.name_source || 'uretim', special = '';
  const control = d.mode === 'simple' ? h('div', { class: 'alert info' }, icon('info'), h('div', null, T('In Simple mode, the bot count comes from the map counts in the Simple mode tab.')))
    : h('div', { class: 'stack', style: { gap: '10px' } },
      btRow(T('Bot count'), T("Increasing adds new bots, decreasing removes the last ones; existing bots don't change."), btNumber(count, v => { count = v; }, { min: 1, max: 3000 })),
      btRow(T('Company distribution (ratio)'), T('Applies to newly added bots and to regeneration.'), btDistribution(f, x => { f.splice(0, 3, ...x); })),
      btRow(T('Name language'), T('Applies to newly added bots and to regeneration; existing bots keep their names.'),
        btPickLang(nameLang, v => { nameLang = v; }, T('Mixed'))),
      btRow(T('Name source'), T(BT_NAME_SOURCE_DESCRIPTION), btNameSource(nameSource, v => { nameSource = v; })),
      btRow(T('Chat language'), btLangLocked(d.mode) ? T('In Advanced mode bots speak English only (the language model is weak in other languages).')
        : T('After Apply, all bots speak this language.'), btChatLang(d.mode, lang, v => { lang = v; })),
      field(T('Your own bots'), btCustomField('', v => { special = v; }), h('div', { class: 'small muted' }, T('Apply: names not in the roster are added as new bots. Regenerate: they come first in the roster.'))),
      h('div', { class: 'row wrap', style: { justifyContent: 'flex-end' } },
        btn(T('Apply'), async () => { const x = await act(() => api('/api/bot/kadro', { id: d.id, count, company_distribution: f, lang, name_lang: nameLang, name_source: nameSource, special }), T('Roster updated.')); if (x) { BT.d = x; btEditor(); } }, 'sm primary', 'check'),
        btn(T('Regenerate'), async () => {
          if (!await confirmBox(T('Regenerate the roster?'), T('All bots are regenerated with new names and personalities, and their progress is deleted.'), { ok: T('Regenerate'), danger: true })) return;
          const x = await act(() => api('/api/bot/kadro', { id: d.id, count, company_distribution: f, lang, name_lang: nameLang, name_source: nameSource, special, regenerate: true }), T('Roster regenerated.')); if (x) { BT.d = x; btEditor(); }
        }, 'sm danger', 'refresh')));
  return h('div', { class: 'stack' },
    h('div', { class: 'card' }, h('h2', null, icon('users'), T('Roster')),
      h('p', { class: 'desc' }, T('Personalities were set once when the roster was generated: each bot has its own archetype, traits (aggression, patience, sociability …), play hours and writing style.')),
      h('div', { class: 'row wrap', style: { gap: '6px', marginBottom: '12px' } }, Object.entries(byArchetype).sort((a, b) => b[1] - a[1]).map(([k, n]) => badge(T(BT_ARCHETYPE[k] || k) + ' ' + n, ''))),
      control),
    h('div', { class: 'card' }, h('h2', null, icon('list'), T('Bots')),
      h('p', { class: 'desc' }, d.has_state ? T("Level, ship, map and activity come from the server's last save (once a minute while the game is open). Click a row to open the bot's editor.") : T("The bots haven't played yet: they start when you enter the game in this world.")),
      btRosterTable(d.roster)));
}

// Kadro tablosu: ada göre arama, firma ve kişilik süzgeci, sıralama (oyuncu isteği 2026-10-30). Sıralanan değer hep tabloda görünür:
// kendi sütunu yoksa (EP, onur, kredi …) Seviye'nin yanında vurgulu bir sütun açılır. # süzülmüş ve sıralanmış listedeki yerdir.
const BT_SORT = [['ad', N('Pilot')], ['seviye', N('Level')], ['rutbe', N('Rank')], ['gemi', N('Ship')], ['harita', N('Map')], ['hedef', N("What it's doing")],
  ['npc', N('Aliens')], ['player', N('Players')], ['olum', N('Deaths')]];
const BT_SORT_EXTRA = [['ep', N('Experience (EP)')], ['onur', N('Honor')], ['kredi', N('Credits')], ['uridyum', N('Uridium')], ['kapi', N('Galaxy gates finished')],
  ['firma', N('Company')], ['archetype', N('Personality')]];
const BT_SORT_VALUE = { npc: b => b.stats.npc || 0, player: b => b.stats.player || 0, olum: b => b.stats.olum || 0, kapi: b => b.stats.gate_done || 0,
  harita: b => b.map_name || '', gemi: b => btShipName(b.gemi) };
const BT_SORT_TEXT = ['ad', 'gemi', 'harita', 'hedef', 'archetype', 'firma'];
const BT_SORT_NUMBER = new Set(['seviye', 'rutbe', 'npc', 'player', 'olum', 'ep', 'onur', 'kredi', 'uridyum', 'kapi']);
const BT_CURRENCY = { ep: 'experience', onur: 'onur', kredi: 'kredi', uridyum: 'uridyum' };
const btShipName = l => String(l || '').replace('ship_', '').replace(/^\w/, c => c.toUpperCase());
const btRank = (r, size) => GI.index?.sprite['rank' + r] ? h('span', { class: 'bt-rank', title: T('Rank {0}', r) }, sprite('rank' + r, size)) : h('span', null, r);
function btRosterTable(roster) {
  const s = BT.rosterFilter = BT.rosterFilter || { search: '', firma: 0, archetype: '', ozel: false, order: 'no', reverse: false };
  const table = h('table', { class: 'table bt-roster' }), counter = h('span', { class: 'bt-counter' });
  const value = (b, k) => BT_SORT_VALUE[k] ? BT_SORT_VALUE[k](b) : k === 'no' ? b.no : b[k] ?? '';
  const highlight = () => BT_SORT_EXTRA.find(([k]) => k === s.order && BT_SORT_NUMBER.has(k));       // sıralanan değerin kendi sütunu yok
  const sortBy = k => { if (s.order === k) s.reverse = !s.reverse; else { s.order = k; s.reverse = !BT_SORT_TEXT.includes(k); } render(); };
  const cell = (b, k) => {
    const f = btCompany[b.firma - 1], n = value(b, k);
    if (k === 'ad') return h('div', { class: 'bt-pilot' },
      h('div', { class: 'bt-pilot-name' }, h('a', { href: '#', class: 'bt-name', onclick: e => e.preventDefault() }, b.ad),
        b.ozel ? h('span', { class: 'badge info bt-custom-badge', title: T('A bot you added') }, T('Custom')) : null),
      h('div', { class: 'bt-pilot-sub' }, h('span', { class: 'bt-company-label' }, f), T(BT_ARCHETYPE[b.archetype] || b.archetype),
        h('span', { class: 'dim' }, btTraitSummary(b.traits))));
    if (k === 'seviye') return h('b', { class: 'bt-lv' }, n);
    if (k === 'rutbe') return btRank(n || 1, 22);
    if (k === 'gemi') return h('div', { class: 'bt-ship' }, shipImage(b.gemi, 30, f.toLowerCase()), h('span', null, n));
    if (k === 'harita') return n || h('span', { class: 'dim' }, '—');
    if (k === 'hedef') return [b.hedef ? h('span', { class: 'bt-activity' }, T(BT_TARGET[b.hedef] || b.hedef)) : h('span', { class: 'dim' }, '—'), btAgentTrace(b)];
    if (BT_CURRENCY[k]) return h('span', { class: 'bt-resource' }, art('source_' + BT_CURRENCY[k], 'bt-resource-icon'), fmtN(n));
    return n ? fmtN(n) : h('span', { class: 'dim' }, '0');
  };
  const render = () => {
    const search = s.search.trim().toLocaleLowerCase(LOC());
    const entries = roster.filter(b => (!search || b.ad.toLocaleLowerCase(LOC()).includes(search)) && (!s.firma || b.firma === s.firma)
      && (!s.archetype || b.archetype === s.archetype) && (!s.ozel || b.ozel));
    const direction = s.reverse ? -1 : 1, text = BT_SORT_TEXT.includes(s.order);
    entries.sort((a, b) => { const x = value(a, s.order), y = value(b, s.order);
      return direction * (text ? String(x).localeCompare(String(y), LOC(), { numeric: true }) : (Number(x) || 0) - (Number(y) || 0)) || a.no - b.no; });
    const column = BT_SORT.slice();
    if (highlight()) column.splice(2, 0, highlight());
    const klass = k => [BT_SORT_NUMBER.has(k) ? 'num' : '', k === s.order ? 'on' : '', highlight()?.[0] === k ? 'highlight' : '', 'k-' + k].join(' ');
    table.replaceChildren(
      h('thead', null, h('tr', null, h('th', { class: 'num bt-row-no' }, '#'), column.map(([k, name]) => h('th', { class: 'bt-sorted ' + klass(k), title: T('Click to sort'),
        onclick: () => sortBy(k) }, T(name), icon(k === s.order && s.reverse ? 'down' : 'up'))))),
      h('tbody', null, entries.length ? entries.map((b, i) => h('tr', { class: 'f-' + btCompany[b.firma - 1].toLowerCase(), onclick: () => btBotDetail(b.no) },
        h('td', { class: 'num bt-row-no' }, i + 1), column.map(([k]) => h('td', { class: klass(k) }, cell(b, k)))))
        : h('tr', null, h('td', { colspan: column.length + 1, class: 'bt-empty' }, T('No bots match the filter.')))));
    counter.textContent = T('{0} / {1} bots', entries.length, roster.length);
    firmaSec.querySelectorAll('button').forEach((x, i) => x.classList.toggle('on', i === s.firma));
    sortSelect.value = s.order;
    directionBtn.replaceChildren(icon(s.reverse ? 'down' : 'up'));
    directionBtn.title = s.reverse ? T('Descending: click for ascending') : T('Ascending: click for descending');
  };
  const choice = (value, options, on) => h('select', { class: 'input', onchange: e => { on(e.target.value); render(); } },
    options.map(([v, name]) => h('option', { value: v, selected: String(v) === String(value) }, name)));
  const firmaSec = h('div', { class: 'seg bt-company-pick' }, [T('All'), ...btCompany].map((name, i) =>
    h('button', { type: 'button', class: i ? 'f-' + name.toLowerCase() : '', onclick: () => { s.firma = i; render(); } }, name)));
  const sortSelect = choice(s.order, [['no', T('Roster order')]].concat(BT_SORT.concat(BT_SORT_EXTRA).map(([k, name]) => [k, T(name)])), v => {
    s.order = v; s.reverse = !BT_SORT_TEXT.includes(v) && v !== 'no'; });
  const directionBtn = btn('', () => { s.reverse = !s.reverse; render(); }, 'ghost icon');
  const tool = h('div', { class: 'bt-filter' },
    h('label', { class: 'bt-search' }, icon('search'), h('input', { class: 'input', type: 'search', placeholder: T('Search by name'), value: s.search,
      oninput: e => { s.search = e.target.value; render(); } })),
    firmaSec,
    choice(s.archetype, [['', T('All personalities')]].concat(Object.entries(BT_ARCHETYPE).map(([k, name]) => [k, T(name)])), v => { s.archetype = v; }),
    h('div', { class: 'bt-sort' }, h('span', { class: 'small muted' }, T('Sort')), sortSelect, directionBtn),
    h('label', { class: 'row small bt-custom-toggle' }, btKey(s.ozel, v => { s.ozel = v; render(); }), T('Only your own bots')),
    h('span', { class: 'spacer' }), counter);
  render();
  return h('div', null, tool, h('div', { class: 'bt-table' }, table));
}

const BT_TRAIT = { aggression: N('aggressive'), rekabet: N('competitive'), sociability: N('social'), patience: N('patient'), risk: N('risk-taking'), loyalty: N('loyal'),
  helpfulness: N('helpful'), talkativeness: N('talkative'), frugality: N('thrifty'), ambition: N('ambitious') };
function btTraitSummary(o) {
  const en = Object.entries(o || {}).sort((a, b) => b[1] - a[1]).slice(0, 2);
  return en.map(([k]) => T(BT_TRAIT[k] || k)).join(', ');
}

// ------------------------------------------------------------------ Davranış, Erişimler, Sohbet
function btBehavior(d) {
  const a = d.settings;
  return h('div', { class: 'card' }, h('h2', null, icon('target'), T('Behavior')),
    btRow(T('Minimum level for PvP'), T("Bots below this level don't go PvP hunting."), btNumber(a.pvp_level, v => btSetting('pvp_level', v), { min: 1, max: 32 })),
    btRow(T("Other companies' maps"), T("Bots can enter enemy companies' maps."), btKey(a.foreign_map, v => btSetting('foreign_map', v))),
    btRow(T('Most shown as ships on your map'), T('At most this many of the bots on your map appear as ships; the others play in the background (performance).'),
      btNumber(a.max_concrete, v => btSetting('max_concrete', v), { min: 1, max: 150 })),
    btRow(T('One bot clan for every how many bots'), T('Number of clans the bots can found, relative to the roster.'), btNumber(a.bots_per_clan, v => btSetting('bots_per_clan', v), { min: 3, max: 100 })),
    btRow(T('Most to answer a call for help'), T('Maximum number of bots that answer a call for help in chat.'), btNumber(a.help_max, v => btSetting('help_max', v), { min: 0, max: 20 })),
    h('h3', null, T('Prime time')),
    btRow(T('Start and end hour'), T("The busy evening hours (your computer's clock): more bots are online and PvP heats up. If start equals end there is no prime time."),
      h('div', { class: 'row', style: { gap: '6px' } }, btNumber(a.prime_start, v => btSetting('prime_start', v), { min: 0, max: 23 }), h('span', null, '–'),
        btNumber(a.prime_end, v => btSetting('prime_end', v), { min: 0, max: 23 }))),
    btRow(T('PvP drive in prime time'), T('Multiplier of the wish to go PvP hunting (1: no change).'),
      btSlider(a.prime_pvp, v => btSetting('prime_pvp', v), { min: 1, max: 5, step: 0.5, fmt: v => 'x' + v })),
    btRow(T('Big battles'), T('In prime time the PvP bots of all three companies gather on a front map that changes every hour (4-4, 4-5, 4-1/2/3). Raise the number of ships shown on your map for bigger fights.'),
      btKey(a.big_battle, v => btSetting('big_battle', v))));
}

function btAccess(d) {
  const trace = Object.assign({}, d.settings.permissions);
  const permissions = (BT.liste?.permissions || Object.keys(BT_PERMS)).filter(k => d.mode !== 'simple' || ['pvp', 'attack_player'].includes(k));
  return h('div', { class: 'card' }, h('h2', null, icon('shield'), T('Permissions')),
    h('p', { class: 'desc' }, T('Which parts of the game the bots will use. No bot uses a disabled part.')),
    permissions.map(k => btRow(T(BT_PERMS[k][0]), T(BT_PERMS[k][1]), btKey(trace[k] !== false, v => { trace[k] = v; btSetting('permissions', { [k]: v }); }))));
}

function btChat(d) {
  const a = d.settings;
  return h('div', null, h('div', { class: 'card' }, h('h2', null, icon('chat'), T('Chat')),
    btRow(T('Trash talk'), T('How much bots provoke: Off (always polite), Light, Harsh (taunts in global after a kill, answers insults hard), Very harsh (often taunts enemy companies and you). Never swearing or real threats.'),
      btSeg([[0, T('Off')], [1, T('Light')], [2, T('Harsh')], [3, T('Very harsh')]], a.rude_chat, v => btSetting('rude_chat', v))),
    btRow(T('Chat'), T(BT_PERMS.sohbet[1]), btKey(a.permissions.sohbet !== false, v => btSetting('permissions', { sohbet: v }))),
    btRow(T('Channel density'), T("Maximum bot lines per minute in global and company chat (so chat doesn't get flooded)."),
      btSlider(a.chat_min, v => btSetting('chat_min', v), { min: 0, max: 30, step: 1, fmt: v => T('{0}/min', v) })),
    h('div', { class: 'alert info' }, icon('info'), h('div', null, d.mode === 'advanced'
      ? T("In Advanced mode, bots talk using the language model; if the model can't keep up, they fall back to template sentences.")
      : T('In Normal mode, bots talk with template sentences based on the situation and their personality: they greet, write when they level up, and reply to calls for help and whispers.')))),
    btModeration(d));
}

// bot klanları (bot/clan_management.py, bot/clan_stations.py): logo (Orders.md OP-017; yoksa etiket), lider, kasa, bütçe, istasyon, diplomasi
const BT_DIPLOMACY = { 1: N('alliance'), 2: N('non-aggression'), 3: N('war') };
function btClanLogo(k) {
  if (!k.logo) return h('div', { class: 'bt-clan-logo vacant' }, String(k.etiket || '?').slice(0, 4));
  const im = h('img', { class: 'bt-clan-logo', src: 'images/klan_logo/' + k.logo + '.webp', sub: '' });
  im.onerror = () => im.replaceWith(btClanLogo({ etiket: k.etiket }));
  return im;
}
function btClans(d) {
  const clans = d.clans || [];
  const card = k => h('div', { class: 'bt-clan' }, btClanLogo(k),
    h('div', { class: 'bt-clan-body' },
      h('div', { class: 'bt-clan-name' }, h('b', null, '[' + k.etiket + '] ' + k.ad), badge(T('{0} members', k.member), '')),
      h('div', { class: 'small muted' }, [T('Leader: {0}', k.lider), T('Treasury: {0} credits', fmtN(k.treasury)), T('Tax: {0}%', k.tax)].join(' · ')),
      k.budget ? h('div', { class: 'small muted' }, T('Budget: station {0}%, payouts {1}%, war {2}%', ...['ksi', 'odeme', 'savas'].map(a => Math.round(100 * (k.budget[a] || 0))))) : null,
      k.ranks.length ? h('div', { class: 'small muted' }, T('Ranks: {0}', k.ranks.join(', '))) : null,
      h('div', { class: 'small' }, k.stations.length ? T('Station: {0}', k.stations.join(', ')) : k.race ? T('Racing for a station: {0}', k.race) : T('No station')),
      k.diplomacy.length ? h('div', { class: 'small muted' }, k.diplomacy.map(x => T(BT_DIPLOMACY[x.tur] || '?') + ': ' + x.ad).join(' · ')) : null,
      k.clan_news.length ? h('div', { class: 'small muted bt-clan-news' }, '“' + k.clan_news[0] + '”') : null));
  return h('div', { class: 'stack' }, h('div', { class: 'card' }, h('h2', null, icon('star'), T('Clans')),
    h('p', { class: 'desc' }, T("Clans founded or joined by the bots (from the server's last save). Leaders manage ranks, description, news, tax, the treasury budget and Clan Battle Stations themselves.")),
    clans.length ? h('div', { class: 'bt-clans' }, clans.map(card))
      : h('div', { class: 'small muted' }, T('No bot clans yet: leader-minded bots found one once they have the level and the money.'))));
}

// sohbet moderatörleri (bot/moderation.py): kuralı çiğneyen önce uyarılır, sonra susturulur, sonra yasaklanır
function btModeration(d) {
  const a = d.settings;
  return h('div', { class: 'card' }, h('h2', null, icon('shield'), T('Chat moderators')),
    h('p', { class: 'desc' }, T('A few calm, patient bots become chat moderators (names in the moderator colour). Whoever breaks a rule (you or bots) is warned first, muted if they do it again, and banned from chat after too many mutes. Only global and company chat; an online moderator decides.')),
    btRow(T('Moderators'), T('When on, moderator bots enforce the rules.'), btKey(a.moderator, v => btSetting('moderator', v))),
    btRow(T('Number of moderators'), T('How many bots of the roster are moderators.'), btNumber(a.mod_count, v => btSetting('mod_count', v), { min: 1, max: 10 })),
    btRow(T('No CAPS'), T('Messages written mostly in capitals.'), btKey(a.rule_caps, v => btSetting('rule_caps', v))),
    btRow(T('No spam'), T('The same message three times, or five messages in 10 seconds.'), btKey(a.rule_flood, v => btSetting('rule_flood', v))),
    btRow(T('No insults'), T('Insults and harmful words.'), btKey(a.rule_insult, v => btSetting('rule_insult', v))),
    btRow(T('No ads'), T('Links and advertising.'), btKey(a.rule_ads, v => btSetting('rule_ads', v))),
    btRow(T('Mute length (min)'), null, btNumber(a.mute_min, v => btSetting('mute_min', v), { min: 1, max: 1440 })),
    btRow(T('Mutes before a ban'), null, btNumber(a.ban_threshold, v => btSetting('ban_threshold', v), { min: 1, max: 10 })),
    btRow(T('Ban length (hours)'), null, btNumber(a.ban_hours, v => btSetting('ban_hours', v), { min: 1, max: 720 })));
}

function btSimple(d) {
  const a = JSON.parse(JSON.stringify(d.settings));
  const save = () => btPatch({ settings: { simple_maps: a.simple_maps, simple_power: a.simple_power, simple_friendly: a.simple_friendly } });
  return h('div', { class: 'card' }, h('h2', null, icon('bot'), T('Simple mode')),
    h('p', { class: 'desc' }, T('Bots are distributed to maps by level and stay there: they kill aliens, and enemy bots attack or flee depending on strength when they see you; when they die, they respawn on the same map.')),
    btSimpleSettings(a, null, false, save));
}

// botun son düşüncesi (modelin kendi notu, İngilizce); tıklayınca editörün Düşünceler ya da Hafıza bölümü (bot/memories.py, bot/agent.py)
function btAgentTrace(b) {
  const last = (b.agent || []).filter(x => x.thought).slice(-1)[0];
  if (!last && !b.memory) return null;
  return h('a', { href: '#', class: 'small muted bt-agent', title: T('Click for details'),
    onclick: e => { e.preventDefault(); e.stopPropagation(); btBotDetail(b.no, last ? 'thought' : 'memory'); } }, icon('brain'), last ? last.thought : T('On their mind'));
}
const BT_PURPOSE = { soz: N('promise'), intikam: N('revenge'), tesekkur: N('thanks'), rekabet: N('rivalry'), merak: N('a question') };
const BT_MOOD = { anger: N('Anger'), morale: N('Morale'), boredom: N('Boredom'), fatigue: N('Tiredness'), confidence: N('Confidence') };
const BT_GEAR = [['lazer', N('Lasers'), 'lazer'], ['kalkan', N('Shield generators'), 'gen'], ['hiz', N('Speed generators'), 'gen'], ['drone', N('Drones')], ['ekstra', N('Extras'), 'ekstra']];
const BT_STATS = { npc: N('Aliens killed'), player: N('Players killed'), olum: N('Deaths'), kutu: N('Bonus box'), cargo_box: N('Cargo boxes'),
  box_stolen: N("Others' cargo boxes"), purchase: N('Purchases'), gorev: N('Quests finished'), sure_sn: N('Time played'),
  spend_kredi: N('Credits spent'), spend_uridyum: N('Uridium spent'), ore_credits: N('Credits from ore sales'), resupply: N('Ammo restocks'),
  box_opened: N('Booty boxes opened'), key_pickup: N('Keys bought'), refining: N('Refining'), lab_load: N('Lab upgrades loaded'),
  skylab_upgrade: N('Skylab upgrades'), skylab_transport: N('Skylab transports'), technology: N('Tech items built'), assembly: N('Assembly crafting'),
  mode_run: N('Mode runs'), gate_done: N('Galaxy gates finished'), gate_lost: N('Galaxy gates lost'), gate_draw: N('Gate spins'),
  event_npc: N('Event alien'), event_box: N('Event box'), event_drop: N('Event loot'), pass_quest: N('Battle Pass tasks'),
  battle_pass: N('Battle Pass'), season_level: N('Season Pass levels'), dispatch: N('Dispatch'), galaxy_trek: N('Galaxy Trek'), mayin: N('Mines'),
  smart_bomb: N('Smart Bomb'), emp: N('EMP'), salvo: N('Rocket salvos'), hidden: N('Cloaking'), jump_cpu: N("Jump CPU") };
const BT_STATS_FEATURED = ['npc', 'player', 'olum', 'gorev', 'gate_done', 'sure_sn'];          // İstatistik bölümünün büyük kutuları
const BT_WARNING = { sohbet: N('chat'), pvp: N('PvP'), kutu: N('cargo box') };
const seDurationBt = sec => sec ? (sec >= 3600 ? Math.floor(sec / 3600) + ':' : '') + String(Math.floor(sec / 60) % 60).padStart(sec >= 3600 ? 2 : 1, '0') + ':' + String(Math.round(sec) % 60).padStart(2, '0') : '—';
const btShort = l => String(l || '').split('_').pop().toUpperCase();
const btCapitalize = m => m ? m.charAt(0).toLocaleUpperCase(LOC()) + m.slice(1) : m;
const BT_EVENT = { killed_me: N('shot me down'), oldurdum: N('I shot him down'), helped_me: N('helped me'), i_helped: N('I helped'),
  sohbet: N('chat'), hakaret: N('insult'), praise: N('praise'), grup: N('group'), klan: N('clan'), arkadas: N('friendship'), reddetti: N('turned me down'),
  hunted_together: N('farmed together'), meydan: N('challenged me'), gossip_good: N('good gossip'), gossip_bad: N('bad gossip'),
  warned: N('warned by the admin') };
const BT_HABIT = { daytime: N('Daytime player'), evening: N('Evening player'), night_owl: N('Night owl'), devoted: N('Devoted') };

// kişilik radarı: on özellik bir çokgen (0 merkez, 1 dış halka); ayarla(o) şekli kaydırıcıyla birlikte günceller
function btRadar(o) {
  const NS = 'http://www.w3.org/2000/svg', K = Object.keys(BT_TRAIT), R = 92, M = 130;
  const el = (name, a) => { const e = document.createElementNS(NS, name); for (const k in a) e.setAttribute(k, a[k]); return e; };
  const point = (i, r) => { const a = -Math.PI / 2 + i * 2 * Math.PI / K.length; return [M + Math.cos(a) * r, M + Math.sin(a) * r]; };
  const svg = el('svg', { viewBox: '0 0 260 260', class: 'bt-radar', role: 'img', 'aria-label': T('Personality') });
  for (const r of [.25, .5, .75, 1]) svg.append(el('polygon', { class: 'gridline', points: K.map((_, i) => point(i, R * r).join(',')).join(' ') }));
  K.forEach((k, i) => {
    const [x, y] = point(i, R), [tx, ty] = point(i, R + 16);
    svg.append(el('line', { class: 'gridline', x1: M, y1: M, x2: x, y2: y }));
    const t = el('text', { x: tx, y: ty + 4, 'text-anchor': Math.abs(tx - M) < 8 ? 'middle' : tx > M ? 'start' : 'end' });
    t.textContent = btCapitalize(T(BT_TRAIT[k])); svg.append(t);
  });
  const shape = el('polygon', { class: 'shape' }), waypoints = K.map(() => el('circle', { r: 3 }));
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
const BT_D_TABS = [['profil', N('Profile'), 'user', N('Name, level, wallet, map and current activity.')],
  ['personality', N('Personality'), 'brain', N('The traits behind its decisions and its current mood.')],
  ['hangar', N('Hangar'), 'ship', N('Ship, equipment, ammo and cargo. The best items go into the slots, the rest stays in storage.')],
  ['memory', N('Memory'), 'note', N('What it thinks of people, its memories, goals and reminders.')],
  ['thought', N('Thoughts'), 'chat', N("The language model's latest decisions and the tools it used.")],
  ['stats', N('Statistics'), 'gauge', N('Counters, gate times, warnings, friends and Skylab.')]];
const BT_D_IMAGE = { profil: 'ke_pilot', hangar: 'ke_hangar', personality: 'bt_personality', memory: 'bt_memory', thought: 'bt_thought', stats: 'bt_stats' };   // Orders.md OP-013, OP-019
const btDetailIcon = s => BT_D_IMAGE[s[0]] ? h('span', { class: 'se-tab-icon gorsel' }, art(BT_D_IMAGE[s[0]], 'se-tab-art')) : h('span', { class: 'se-tab-icon' }, icon(s[2]));

async function btBotDetail(no, tab = 'profil') {
  const pid = BT.d.id;
  let v;
  try { [v] = await Promise.all([api('/api/bot/detay?id=' + encodeURIComponent(pid) + '&no=' + no), loadGameImages()]); } catch (e) { toast(e.message, 'err'); return; }
  let value = {};
  const multiplier = v.catalog;
  const lock = !!v.read_only;
  const fc = () => btCompany[v.firma - 1].toLowerCase();
  const side = h('aside', { class: 'bt-detail-side' }), main = h('div', { class: 'bt-detail-main' }), state = h('div', { class: 'bt-detail-status' });
  const save = btn(T('Save'), async () => {
    const x = await act(() => api('/api/bot/detay', { id: pid, no, changes: value }), T('Saved.'));
    if (x) { v = x; value = {}; render(); BT.d = await api('/api/bot?id=' + encodeURIComponent(pid)).catch(() => BT.d); }
  }, 'primary', 'check');
  const cancel = btn(T('Cancel'), () => { value = {}; render(); }, 'ghost', 'undo');
  // değişiklik sayacı (alt çubuk): kaydedilmemiş alan sayısı
  const handle = () => {
    const n = Object.keys(value).length;
    save.disabled = lock || !n; cancel.disabled = !n;
    btFill(state, lock ? [icon('lock'), T('Read-only')] : n ? [h('span', { class: 'se-pulse' }), T('{0} unsaved changes', n)] : [icon('check'), T('Same as the save')]);
    state.className = 'bt-detail-status' + (n && !lock ? ' var' : '');
  };
  const change = (a, val) => { value[a] = val; handle(); };
  const get_value = (a, backup) => value[a] !== undefined ? value[a] : backup;
  const entries = (a, extra) => { value[a] = (value[a] || []).concat([extra]); render(); };
  const mapping = (a, k, val) => { value[a] = Object.assign({}, value[a], { [k]: val }); handle(); };
  const card = (title, iconEl, ...body) => h('div', { class: 'card se-card bt-detail-card' }, title ? h('h2', null, icon(iconEl), title) : null, ...body);
  const empty = text => h('div', { class: 'bt-detail-empty' }, text || T('Nothing yet.'));
  const missing = () => h('div', { class: 'alert info' }, icon('info'), h('div', null, T("This bot hasn't appeared in the game yet: only its name and personality can be edited.")));
  const remove = (onclick, title = T('Delete')) => btn('', onclick, 'ghost sm icon', 'trash', { title, disabled: lock });
  const count = (n, on, o = {}) => { const el = btNumber(n, on, o); el.disabled = lock; return el; };
  const percent = (n, on, cls = '') => slider({ min: 0, max: 100, step: 1, value: Math.round(n * 100), disabled: lock, oninput: e => on(+e.target.value / 100) }, cls);
  const now = Date.now() / 1000;

  // ---- sol: kimlik kartı (kayıtlı değerler) ve bölüm menüsü
  function uid() {
    const p = v.profil || {}, f = fc(), e = v.gear || {};
    const sell = (name, n, tag) => h('div', { class: 'se-wallet-row' }, art('source_' + name, 'se-currency-icon'), h('span', null, tag), h('b', null, fmtN(n)));
    const stats = (iconEl, n, title) => h('div', { class: 'se-value', title: title }, h('span', { class: 'bt-value-icon' }, icon(iconEl)), h('b', null, n));
    const cargo = Object.values(v.kargo || {}).reduce((a, n) => a + n, 0);
    return h('div', { class: 'card se-identity f-' + f },
      h('div', { class: 'se-identity-scene' }, h('div', { class: 'se-ring' }), shipImage(e.gemi || 'ship_phoenix', 150, f)),
      h('div', { class: 'se-identity-head' }, portrait(v.firma, 'se-portrait lowercase', 84),
        h('div', { style: { minWidth: 0 } }, h('div', { class: 'se-identity-name', title: v.ad }, v.ad),
          h('div', { class: 'se-pilot small' }, p.klan ? h('span', { class: 'se-clan' }, '[' + p.klan + ']') : null, badge(btCompany[v.firma - 1], f),
            v.online ? badge(T('Online'), 'ok') : null))),
      h('div', { class: 'bt-detail-label' }, h('div', null, h('b', null, T(BT_ARCHETYPE[v.archetype] || v.archetype)),
        v.habit ? T(BT_HABIT[v.habit] || v.habit) : null), h('div', { class: 'dim' }, btTraitSummary(v.traits))),
      v.var ? [
        h('div', { class: 'se-lv sm' }, h('div', { class: 'se-lv-num' }, h('small', null, T('Lv')), h('b', null, p.seviye)),
          h('div', { class: 'grow' }, h('div', { class: 'row between small muted' }, btRank((BT.d.roster.find(b => b.no === no) || {}).rutbe || 1, 18), h('span', { class: 'mono' }, fmtShort(p.ep) + ' EP')),
            epBar(p.ep, p.base_ep || 0, p.next_ep))),
        h('div', { class: 'se-wallet' }, sell('kredi', p.kredi, T('Credits')), sell('uridyum', p.uridyum, T('Uridium')), sell('onur', p.onur, T('Honor'))),
        h('div', { class: 'se-values' }, stats('zap', fmtShort(v.power.power), T('Power')), stats('crosshair', fmtShort(v.power.dps), T('Damage/s')),
          stats('heart', fmtShort(v.power.ehp), T('Effective HP')), stats('box', fmtShort(cargo) + '/' + fmtShort(v.cargo_capacity), T('Cargo')))] : null);
  }
  function menu() {
    const n = { hangar: v.var ? BT_GEAR.reduce((a, [k]) => a + Object.keys(v.gear[k] || {}).length, 0) : 0, memory: v.var ? v.memories.length + v.relations.length : 0,
      thought: (v.agent || []).length };
    return h('nav', { class: 'card se-menu' }, BT_D_TABS.map(s => h('button', { class: s[0] === tab ? 'on' : '', type: 'button',
      onclick: () => { if (tab !== s[0]) { tab = s[0]; main.scrollTop = 0; render(); } } },
    btDetailIcon(s), h('span', null, T(s[1])), n[s[0]] ? h('span', { class: 'se-count' }, fmtN(n[s[0]])) : null)));
  }

  // ---- Profil
  function profile() {
    const p = v.profil || {};
    let name = v.ad;
    const nameCard = card(T('Name'), 'edit', h('div', { class: 'bt-detail-name' },
      h('input', { class: 'input', value: v.ad, maxlength: 20, disabled: lock, oninput: e => { name = e.target.value.trim(); regenerate.disabled = lock || name === v.ad; },
        onkeydown: e => { if (e.key === 'Enter') regenerate.click(); } }),
      regenerate = btn(T('Rename'), async () => {
        if (name === v.ad) return;
        const x = await act(() => api('/api/bot/ad', { id: pid, no, name }), T('Saved.'));
        if (x) { BT.d = x; v.ad = name; render(); }
      }, '', 'edit', { disabled: true })),
      h('div', { class: 'small dim' }, T('3-20 characters: letters, digits, _ . -  The name changes right away, without Save.')));
    if (!v.var) return [nameCard, missing()];
    const currency = (key, icon, tag, n, o) => h('div', { class: 'se-currency' }, art('source_' + icon, 'se-currency-icon lg'),
      h('div', { class: 'grow' }, h('label', { class: 'lbl' }, tag), count(get_value(key, n), x => change(key, x), Object.assign({ min: 0, max: 2e12, cls: 'num wide' }, o))));
    const lv = p.next_ep ? T('Level {0}; next level at {1} EP.', p.seviye, fmtN(p.next_ep)) : T('Level {0}.', p.seviye);
    const job = [p.hedef ? T(BT_TARGET[p.hedef] || p.hedef) : '—', p.intent && p.intent !== p.hedef ? T('Intends: {0}', T(BT_TARGET[p.intent] || p.intent)) : null];
    return [nameCard,
      card(T('Level and wallet'), 'star', h('div', { class: 'bt-detail-currencies' },
        h('div', null, currency('ep', 'experience', T('Experience (EP)'), p.ep, { max: 1e12 }), h('div', { class: 'small dim bt-detail-note' }, lv)),
        currency('kredi', 'kredi', T('Credits'), p.kredi), currency('uridyum', 'uridyum', T('Uridium'), p.uridyum),
        currency('onur', 'onur', T('Honor'), p.onur, { min: -2e12 }))),
      card(T('Location and activity'), 'map',
        btRow(T('Map'), v.online ? T("An online bot's map can't be changed: try once it is offline.") : T('The bot starts on this map the next time it logs in.'),
          h('select', { class: 'input', disabled: lock || !!v.online, onchange: e => change('harita', Number(e.target.value)) },
            multiplier.haritalar.map(m => h('option', { value: m.id, selected: m.id === get_value('harita', p.harita) }, m.ad)))),
        btRow(T("What it's doing"), job[1], h('span', { class: 'bt-activity' }, job[0])),
        btRow(T('Quest'), v.tamam ? T('Finished {0} quests.', v.tamam) : null, v.gorev && !value.cancel_quest
          ? h('div', { class: 'row', style: { gap: '8px' } }, h('b', null, v.gorev.ad), btn(T('Drop the quest'), () => { change('cancel_quest', true); render(); }, 'ghost sm', 'x', { disabled: lock }))
          : h('span', { class: 'dim' }, value.cancel_quest ? T('Will be dropped') : '—')),
        btRow(T('Clan'), null, h('span', null, p.klan ? '[' + p.klan + ']' : '—')))];
  }

  // ---- Kişilik: radar + özellik kaydırıcıları, ruh hâli
  function personality() {
    const traits = Object.assign({}, v.traits, value.traits);
    const r = btRadar(traits);
    const traitRow = ([k, name_]) => {
      const value = h('b', null, Math.round(traits[k] * 100));
      return h('div', { class: 'bt-trait' }, h('span', null, btCapitalize(T(name_))), value,
        percent(traits[k], x => { traits[k] = x; value.textContent = Math.round(x * 100); r.update(traits); mapping('traits', k, x); }));
    };
    const mood = Object.assign({}, v.mood, value.mood);
    const moodRow = ([k, name_]) => {
      const value = h('b', null, Math.round((mood[k] ?? 0) * 100));
      return h('div', { class: 'bt-trait ruh-' + k }, h('span', null, T(name_)), value,
        percent(mood[k] ?? 0, x => { value.textContent = Math.round(x * 100); mapping('mood', k, x); }, 'bt-mood'));
    };
    return [card(T('Traits'), 'brain', h('p', { class: 'desc' }, T('Set when the roster was generated; change it and the bot decides accordingly (aggressive bots lean to PvP, social ones to chat, thrifty ones to saving).')),
      h('div', { class: 'bt-personality' }, h('div', { class: 'bt-radar-box' }, r.svg), h('div', { class: 'bt-traits' }, Object.entries(BT_TRAIT).map(traitRow)))),
    v.var ? card(T('Mood'), 'heart', h('p', { class: 'desc' }, T('Its current feelings: they settle back over time. An angry bot seeks revenge, a tired one logs off early.')),
      h('div', { class: 'bt-traits iki' }, Object.entries(BT_MOOD).map(moodRow))) : null];
  }

  // ---- Hangar: gemi, donanım kutuları, cephane, kargo
  function hangar() {
    if (!v.var) return [missing()];
    const e = v.gear, f = fc();
    const ship = get_value('gemi', e.gemi);
    const g = multiplier.ships.find(x => x.loot === ship) || {};
    const slot = { lazer: g.lazer, gen: g.gen, ekstra: g.ekstra };
    const item = (l, n, update, remove_, maximum) => h('div', { class: 'bt-item' }, gameIcon(l, 44, f, 'box'),
      h('div', { class: 'bt-item-name', title: itemName(l) }, itemName(l)),
      h('div', { class: 'bt-item-bottom' }, count(n, update, { min: 0, max: maximum, cls: 'num' }), remove_ ? remove(remove_) : null));
    const addSelect = (options, on) => h('select', { class: 'input bt-add', disabled: lock, onchange: ev => { if (ev.target.value) on(ev.target.value); } },
      [h('option', { value: '' }, T('Add…'))].concat(options.map(x => h('option', { value: x.loot }, x.ad))));
    const category = ([k, name_, slot_info]) => {
      const owner = Object.assign({}, e[k], (value.gear || {})[k]);
      const write = new_ => { value.gear = Object.assign({}, value.gear, { [k]: new_ }); handle(); };
      const var_ = Object.entries(owner).filter(([, n]) => n > 0);
      const equipped = x => Object.values(Object.assign({}, e[x], (value.gear || {})[x])).reduce((a, n) => a + n, 0);
      // kalkan ve hız aynı jeneratör yuvalarını paylaşır; ekstranın sayısı kalan hakkı (JP-01 10 hak): her biri bir yuva
      const total = slot_info === 'gen' ? equipped('kalkan') + equipped('hiz') : k === 'ekstra' ? var_.length : equipped(k);
      return h('div', { class: 'bt-cat' },
        h('div', { class: 'bt-cat-head' }, h('b', null, T(name_)), h('span', { class: 'se-count' }, slot_info && slot[slot_info] != null ? T('{0} / {1} slots', total, slot[slot_info]) : fmtN(total)),
          h('span', { class: 'spacer' }), addSelect(multiplier[k].filter(x => !owner[x.loot]), l => { write(Object.assign({}, owner, { [l]: (multiplier[k].find(x => x.loot === l) || {}).right || 1 })); render(); })),
        var_.length ? h('div', { class: 'bt-items' }, var_.map(([l, n]) => item(l, n, x => write(Object.assign({}, owner, { [l]: x })),
          () => { const y = Object.assign({}, owner); delete y[l]; write(y); render(); }, k === 'ekstra' ? 100000 : k === 'drone' ? 10 : 100))) : empty(T('Nothing equipped.')));
    };
    const stock = Object.assign({}, v.stock, value.stock);
    const cargo = Object.values(v.kargo).reduce((a, n) => a + n, 0), capacity = v.cargo_capacity || 1;
    return [
      card(T('Ship'), 'ship', h('div', { class: 'bt-ship-card' },
        h('div', { class: 'bt-ship-scene' }, shipImage(ship, 132, f)),
        h('div', { class: 'bt-ship-right' },
          field(T('Ship'), h('select', { class: 'input', disabled: lock, onchange: ev => { change('gemi', ev.target.value); render(); } },
            multiplier.ships.map(x => h('option', { value: x.loot, selected: x.loot === ship }, x.ad)))),
          h('div', { class: 'bt-slots' }, [['zap', g.lazer, T('laser')], ['shield', g.gen, T('generator')], ['cpu', g.ekstra, T('extra')]].map(([iconEl, n, name_]) =>
            h('span', { class: 'chip' }, icon(iconEl), h('b', null, n ?? '?'), name_))),
          field(T('Ammo in use'), h('select', { class: 'input', disabled: lock, onchange: ev => change('ammunition', ev.target.value) },
            multiplier.ammunition.filter(x => x.loot.includes('_laser_')).map(x => h('option', { value: x.loot, selected: x.loot === get_value('ammunition', e.ammunition) }, x.ad)))),
          h('div', { class: 'bt-power' }, [[T('Power'), v.power.power], [T('Damage/s'), fmtN(v.power.dps)], [T('Effective HP'), fmtN(v.power.ehp)]].map(([k, n]) =>
            h('div', null, h('span', null, k), h('b', null, n)))),
          value.gemi || value.gear ? h('div', { class: 'small dim' }, T('Power is recalculated on save.')) : null))),
      card(T('Equipment'), 'layers', ...BT_GEAR.map(category)),
      card(T('Ammo and rockets'), 'ammo',
        h('div', { class: 'bt-cat-head' }, h('span', { class: 'small muted' }, T('Ammo, rockets and resources in storage.')), h('span', { class: 'spacer' }),
          addSelect(multiplier.ammunition.filter(x => stock[x.loot] === undefined), l => { mapping('stock', l, 100); render(); })),
        Object.keys(stock).length ? h('div', { class: 'bt-items' }, Object.entries(stock).map(([l, n]) => item(l, n, x => mapping('stock', l, x), null, 1e9))) : empty()),
      card(T('Cargo'), 'box',
        h('div', { class: 'bt-cargo' }, h('div', { class: 'bt-cargo-bar' }, h('span', { style: { width: Math.min(100, 100 * cargo / capacity) + '%' } })),
          h('span', { class: 'small muted' }, T('{0} of {1}', fmtN(cargo), fmtN(capacity)))),
        Object.keys(v.kargo).length && !value.empty_cargo
          ? h('div', { class: 'row wrap', style: { gap: '6px', alignItems: 'center', marginTop: '10px' } }, Object.entries(v.kargo).map(([o, n]) => h('span', { class: 'chip' }, o, h('b', null, fmtN(n)))),
            h('span', { class: 'spacer' }), btn(T('Empty the cargo'), () => { change('empty_cargo', true); render(); }, 'ghost sm', 'trash', { disabled: lock }))
          : empty(value.empty_cargo ? T('Will be emptied on save.') : T('Cargo is empty.'))),
    ];
  }

  // ---- Hafıza
  function memory() {
    if (!v.var) return [missing()];
    const deleted = (a, k) => (value[a] || []).includes(k);
    const relation = v.relations.filter(x => !deleted('delete_relation', x.anahtar)).map(x => {
      const d = get_value('relation', {})[x.anahtar] ?? x.d;
      const value = h('b', { class: d >= 0 ? 'good' : 'bad' }, (d > 0 ? '+' : '') + d.toFixed(2));
      const saves = slider({ min: -100, max: 100, step: 5, value: Math.round(d * 100), disabled: lock, oninput: e => {
        const y = +e.target.value / 100; value.textContent = (y > 0 ? '+' : '') + y.toFixed(2); value.className = y >= 0 ? 'good' : 'bad'; mapping('relation', x.anahtar, y); } }, 'bt-relation-range');
      return h('div', { class: 'bt-relation' }, h('div', null, h('b', null, x.ad),
        h('div', { class: 'small dim' }, Object.entries(x.n || {}).map(([t, n]) => (BT_EVENT[t] ? T(BT_EVENT[t]) : t) + ' ' + n).join(', '))),
      h('div', { class: 'bt-relation-scale' }, h('span', { class: 'small dim' }, T('Enemy')), saves, h('span', { class: 'small dim' }, T('Friend'))), value,
      remove(() => entries('delete_relation', x.anahtar)));
    });
    const impression = v.impression.filter(x => !deleted('delete_impression', x.anahtar)).map(x => h('div', { class: 'bt-note' }, h('b', null, x.ad),
      h('textarea', { class: 'input', rows: 2, disabled: lock, oninput: e => mapping('impression', x.anahtar, e.target.value) }, get_value('impression', {})[x.anahtar] ?? x.metin),
      remove(() => entries('delete_impression', x.anahtar))));
    const memories = v.memories.filter(a => !deleted('delete_memory', a.id)).map(a => {
      const waiting = a.takip && !a.takip.finished && !deleted('cancel_followup', a.id);
      return h('div', { class: 'bt-memory' }, h('div', { class: 'bt-memory-head' }, h('b', null, a.kim), h('span', { class: 'small dim' }, T('{0} ago', fmtDur(now - a.t))),
        a.n > 1 ? h('span', { class: 'se-count' }, '×' + a.n) : null, waiting ? badge(T('Pending: {0}', T(BT_PURPOSE[a.takip.amac] || a.takip.amac)), 'warn') : null,
        h('span', { class: 'spacer' }), waiting ? btn('', () => entries('cancel_followup', a.id), 'ghost sm icon', 'x', { title: T('Cancel the pending plan'), disabled: lock }) : null,
        remove(() => entries('delete_memory', a.id))),
      h('input', { class: 'input', value: get_value('memory_log', {})[a.id] ?? a.summary, disabled: lock, oninput: e => mapping('memory_log', a.id, e.target.value) }));
    });
    const ledger = get_value('ledger', v.ledger);
    const notebookRow = (m, i) => h('div', { class: 'bt-ledger' }, h('span', { class: 'bt-ledger-no' }, i + 1),
      h('input', { class: 'input', value: m, disabled: lock, oninput: e => { const d = ledger.slice(); d[i] = e.target.value; change('ledger', d); } }),
      remove(() => { change('ledger', ledger.filter((_, j) => j !== i)); render(); }));
    return [
      card(T('Relationships'), 'users', h('p', { class: 'desc' }, T('How it sees people: it helps friends and attacks enemies.')), relation.length ? relation : empty()),
      card(T('Impressions of people'), 'note', impression.length ? h('div', { class: 'bt-notes' }, impression) : empty()),
      card(T('Memories'), 'clock', memories.length ? h('div', { class: 'bt-memories' }, memories) : empty()),
      h('div', { class: 'grid g2' },
        card(T('Goal list'), 'target', ...(ledger.length ? ledger.map(notebookRow) : [empty()]),
          h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '8px' } },
            btn(T('Add goal'), () => { change('ledger', ledger.concat([''])); render(); }, 'ghost sm', 'plus', { disabled: lock }))),
        card(T('Reminders and savings'), 'bell',
          v.reminder.length && !value.clear_reminder
            ? [h('ul', { class: 'bt-mind' }, v.reminder.map(x => h('li', null, x.metin, h('span', { class: 'dim' }, ' (' + T('in {0}', fmtDur(x.time_left_sec)) + ')')))),
              h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '6px' } }, btn(T('Delete reminders'), () => { change('clear_reminder', true); render(); }, 'ghost sm', 'trash', { disabled: lock }))]
            : empty(T('No reminders.')),
          h('div', { class: 'bt-savings' }, h('span', { class: 'lbl' }, T('Saving up for')), v.savings && !value.clear_savings
            ? h('div', { class: 'row', style: { gap: '8px' } }, gameIcon(v.savings, 28, fc(), 'box'), h('b', null, itemName(v.savings)), h('span', { class: 'spacer' }),
              btn(T('Stop saving'), () => { change('clear_savings', true); render(); }, 'ghost sm', 'x', { disabled: lock }))
            : h('span', { class: 'dim' }, '—')))),
    ];
  }

  // ---- Düşünceler: dil modelinin adımları (yeniden eskiye)
  function thought() {
    const trace = value.clear_agent ? [] : (v.agent || []).slice().reverse();
    const step = x => [h('b', null, x.tool), x.arg && Object.keys(x.arg).length ? ' ' + JSON.stringify(x.arg) : '', x.result ? h('span', { class: 'dim' }, ' → ' + x.result) : null];
    return [card(T('Latest thoughts'), 'chat', h('p', { class: 'desc' }, T("The bot's own notes; the language model keeps them in English.")),
      trace.length ? h('ol', { class: 'bt-thoughts' }, trace.map(x => h('li', null, x.thought ? h('div', null, x.thought) : null, h('div', { class: 'bt-step' }, step(x)))))
        : empty(value.clear_agent ? T('Will be cleared on save.') : T('No thoughts yet: fills up as the language model makes decisions in Advanced mode.')),
      trace.length ? h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '10px' } }, btn(T('Clear thoughts'), () => { change('clear_agent', true); render(); }, 'ghost sm', 'trash', { disabled: lock })) : null)];
  }

  // ---- İstatistik
  function stats() {
    if (!v.var) return [missing()];
    const ist = v.stats || {};
    const value = (k, n) => k === 'sure_sn' ? fmtDur(n) : fmtN(Math.round(n));
    const remaining = Object.entries(ist).filter(([k]) => !BT_STATS_FEATURED.includes(k)).sort((a, b) => (BT_STATS[a[0]] ? 0 : 1) - (BT_STATS[b[0]] ? 0 : 1));
    return [
      h('div', { class: 'stats bt-detail-stats' }, BT_STATS_FEATURED.map(k => h('div', { class: 'stat' }, h('div', { class: 'k' }, T(BT_STATS[k])), h('div', { class: 'v' }, value(k, ist[k] || 0))))),
      card(T('All counters'), 'list', remaining.length ? h('div', { class: 'kv bt-kv' }, remaining.map(([k, n]) => h('div', null, BT_STATS[k] ? T(BT_STATS[k]) : k, h('b', null, value(k, n))))) : empty()),
      h('div', { class: 'grid g2' },
        card(T('Gate times'), 'clock', Object.keys(v.gate_times || {}).length ? h('div', { class: 'kv one' },
          Object.entries(v.gate_times).map(([g, x]) => h('div', null, g.charAt(0).toUpperCase() + g.slice(1), h('b', null, T('best {0}', seDurationBt(x.best)) + ' · ' + T('{0} times', fmtN(x.sayi))))))
          : empty()),
        card(T('Friends'), 'users', (v.profil.friends || []).length ? h('div', { class: 'row wrap', style: { gap: '6px' } }, v.profil.friends.map(a => h('span', { class: 'chip' }, a))) : empty()),
        card(T('Admin warning'), 'alert', Object.keys(v.warning || {}).length ? h('div', { class: 'row wrap', style: { gap: '6px' } },
          Object.entries(v.warning).map(([k, t]) => badge(T(BT_WARNING[k] || k) + ' · ' + T('{0} left', fmtDur(Math.max(0, t - Date.now() / 1000))), 'warn'))) : empty(T('No warnings.'))),
        card(T('Skylab'), 'layers', Object.keys(v.skylab || {}).length ? h('div', { class: 'row wrap', style: { gap: '6px' } }, Object.entries(v.skylab).map(([m, n]) => h('span', { class: 'chip' }, m, h('b', null, n)))) : empty())),
    ];
  }

  let regenerate;
  function render() {
    const s = BT_D_TABS.find(x => x[0] === tab) || BT_D_TABS[0], sc = main.scrollTop;
    btFill(side, uid(), menu());
    btFill(main, h('div', { class: 'se-main-head' }, btDetailIcon(s), h('div', null, h('h2', null, T(s[1])), h('div', { class: 'small muted' }, T(s[3])))),
      lock ? h('div', { class: 'alert warning' }, icon('alert'), h('div', null, T('The game is running with this pack but its server did not answer: showing the last save, editing is off.')))
        : v.live ? h('div', { class: 'alert info' }, icon('info'), h('div', null, T('The game is running: changes take effect in game as soon as you save.'))) : null,
      ({ profile, personality, hangar, memory, thought, stats })[s[0]]());
    main.scrollTop = sc;
    handle();
  }
  render();
  const m = modal({ title: T('Bot editor'), sub: T('{0} pack · bot #{1}', BT.d.ad, no), body: h('div', { class: 'bt-detail' }, side, main), onclose: () => btEditor(),
    foot: [state, h('span', { class: 'spacer' }), btn(T('Close'), async () => {
      if (Object.keys(value).length && !await confirmBox(T('Changes not saved'), T('Closing discards the unsaved changes.'), { ok: T('Close without saving'), danger: true })) return;
      m.close();
    }, 'ghost'), cancel, save] });
  m.box.classList.add('bt-detail-modal');
}

function btUsage(u) {
  if (!u) return h('div', { class: 'small muted' }, T('Measured once the game runs with this pack.'));
  const s = u.saat || {}, pay = s.input ? Math.round(100 * (s.cache || 0) / s.input) : 0;
  return h('div', { class: 'small', style: { textAlign: 'right' } },
    h('div', null, T('{0} requests · {1} input tokens ({2}% cached) · {3} output tokens', fmtN(s.request || 0), fmtN(s.input || 0), pay, fmtN(s.output || 0))),
    h('div', { class: 'muted' }, [u.provider, u.cap ? T('Hourly limit: {0} / {1} requests', fmtN(s.request || 0), fmtN(u.cap)) : T('No hourly limit'),
      u.duration_min < 60 ? T('in the last {0} minutes', u.duration_min) : null].filter(Boolean).join(' · ')),
    u.at_limit ? h('div', { style: { color: 'var(--warn)' } }, T('Limit reached: for now bots chat with templates and play by rules.')) : null);
}

function btAdvanced(d) {
  return typeof btLlmCard === 'function' ? btLlmCard(d) : h('div', { class: 'card' }, btLlmWarning());
}

// ------------------------------------------------------------------ Gelişmiş kip: dil modeli (llm_setup.py, /api/bot/llm)
function btLlmCard(d) {
  const box = h('div'), right = h('div');
  const a = d.settings;
  btLlmWatch(box, right);
  return h('div', { class: 'stack' },
    h('div', { class: 'card' }, h('h2', null, icon('brain'), T('Language model')),
      h('div', { class: 'bt-llm' }, btArt('bot_llm', 'drone_settings', 'bt-llm-art'), h('div', { class: 'stack', style: { gap: '10px' } }, right, box))),
    h('div', { class: 'card' }, h('h2', null, icon('sliders'), T('Advanced mode settings')),
      btRow(T('Usage in the last hour'), T('Requests and tokens the bots sent to the language model in the last hour (chat, memories and decisions). Providers bill by tokens; cached input is much cheaper.'),
        btUsage(d.llm_usage)),
      btRow(T('Bots thinking at the same time'), T("The model's parallel slots: requests are processed in batches. Higher means more bots talk at once, but the computer is strained more."),
        btNumber(a.llm_batch, v => btSetting('llm_batch', v), { min: 1, max: 16 })),
      btRow(T('Chat with model'), T('If off, bots talk with templates as in Normal mode; the model is only used for decisions.'), btKey(a.llm_chat, v => btSetting('llm_chat', v))),
      btRow(T('Review decisions (minutes)'), T('Each bot consults the model about its situation this often, in minutes (0: never). Shorter is livelier but heavier.'),
        btNumber(a.llm_decision_min, v => btSetting('llm_decision_min', v), { min: 0, max: 120 })),
      // araç döngüsü yalnız dahili model dışındaki sağlayıcılarda (bot/agent.py)
      btRow(T('Play with tools'), T('With providers other than the built-in model, a bot first looks at its status, the maps, the shop and quests like a player, then decides with tools; it keeps a goal list and sets itself reminders.'),
        btKey(a.llm_agent, v => btSetting('llm_agent', v))),
      btRow(T('Max steps per thought'), T('How many times at most the model is asked in one thought (several tools each time). Most thoughts finish in 1-2 requests; a higher value means more requests.'),
        btNumber(a.llm_agent_steps, v => btSetting('llm_agent_steps', v), { min: 1, max: 10 })),
      btRow(T('Hourly request limit'), T('At most this many requests per hour go to a provider other than the built-in model (chat, memories and decisions included; 0: no limit). At the limit bots chat with templates and play by rules; this caps spending.'),
        btNumber(a.llm_hourly, v => btSetting('llm_hourly', v), { min: 0, max: 20000 }))));
}

function btLlmWatch(box, right) {
  let signature = '', selected = null;
  // sağlayıcı formu yalnız seçim değişince yeniden çizilir (yoklama yazılanı silmesin); alt kutu dahili modelde kurulum, ötekilerde test
  const render = s => {
    signature = JSON.stringify(s);
    if (BT.liste) BT.liste.llm_multilingual = s.provider.multilingual;
    if (selected !== s.provider.selected || s.new_form) { selected = s.provider.selected; btFill(right, btLlmProvider(s.provider, x => render(Object.assign(x, { new_form: true })))); }
    btFill(box, selected === 'local' ? h('div', { class: 'stack', style: { gap: '10px' } }, btLlmWarning(), btLlmBox(s, render)) : btLlmRemoteBox(s, render));
  };
  api('/api/bot/llm').then(render).catch(e => btFill(box, h('div', { class: 'alert hata' }, icon('alert'), h('div', null, e.message))));
  const id = setInterval(async () => {
    if (!box.isConnected) return clearInterval(id);
    let s; try { s = await api('/api/bot/llm'); } catch (e) { return; }
    if (JSON.stringify(s) !== signature) render(s);
  }, 1000);
}

// sağlayıcı adları (öteki sağlayıcıların adı kendi markası)
const BT_PROVIDER_NAME = { local: N('Built-in local model (Qwen3 4B)'), ozel: N('Custom (OpenAI-compatible)') };
function btLlmProvider(provider, new_) {
  const p = provider.liste.find(x => x.kimlik === provider.selected);
  const f = { address: p.address, model: p.model, anahtar: '' };
  const send = (body, msg) => act(() => api('/api/bot/llm/saglayici', body), msg).then(x => { if (x) new_(x); });
  const sec = h('select', { class: 'input', onchange: e => send({ kimlik: e.target.value }, T('Saved.')) },
    provider.liste.map(x => h('option', { value: x.kimlik, selected: x.kimlik === provider.selected }, BT_PROVIDER_NAME[x.kimlik] ? T(BT_PROVIDER_NAME[x.kimlik]) : x.ad)));
  const rows = [btRow(T('Provider'), T("The bots' chat and decisions come from this model."), sec)];
  if (provider.selected === 'local') return h('div', null, rows);
  // model: önce elle yazılır; modeller çekilince açılır liste olur (datalist dolu kutuda süzülüp açılmıyordu)
  const modelBox = h('div', null, h('input', { class: 'input', value: f.model, oninput: e => { f.model = e.target.value.trim(); } }));
  const load = async () => {
    const x = await act(() => api('/api/bot/llm/models', { kimlik: provider.selected, address: f.address, anahtar: f.anahtar }), r => T('{0} models found.', r.models.length));
    if (!x || !x.models.length) return;
    const models = x.models.includes(f.model) || !f.model ? x.models : [f.model].concat(x.models);
    if (!f.model) f.model = models[0];
    btFill(modelBox, h('select', { class: 'input', onchange: e => { f.model = e.target.value; } }, models.map(m => h('option', { value: m, selected: m === f.model }, m))));
  };
  rows.push(
    btRow(T('Address'), p.local ? T('The OpenAI-compatible address of the server running on your computer (…/v1). The server must be running.') : T('You usually do not need to change this.'),
      h('input', { class: 'input', value: f.address, placeholder: p.default_url, oninput: e => { f.address = e.target.value.trim(); } })),
    btRow(p.key_required ? T('API key') : T('API key (optional)'), T('Stored only on this computer; it never goes into bot packs.'),
      h('input', { class: 'input', type: 'password', autocomplete: 'off', oninput: e => { f.anahtar = e.target.value.trim(); },
        placeholder: p.has_key ? T('Saved ({0}); type to change', p.anahtar) : p.key_required ? T('Paste your API key') : T('Leave empty if not needed') })),
    btRow(T('Model'), T('A fast, cheap chat model is enough; reasoning models answer slowly.'),
      h('div', { class: 'row', style: { gap: '6px' } }, modelBox, btn(T('Fetch models'), load, 'ghost sm', 'download'))),
    h('div', { class: 'row', style: { gap: '8px', justifyContent: 'flex-end' } },
      p.has_key ? btn(T('Remove key'), () => send({ kimlik: provider.selected, anahtar: '-' }, T('Deleted.')), 'ghost sm', 'trash') : null,
      btn(T('Save'), () => send({ kimlik: provider.selected, address: f.address, model: f.model, anahtar: f.anahtar }, T('Saved.')), 'primary sm', 'check')),
    h('div', { class: 'alert info' }, icon('info'), h('div', null, T('With this provider bots speak their own chat language (chosen on the Roster tab). With paid providers the requests are billed to your account: the "Bots thinking at the same time" and "Review decisions" settings set how many requests are made.'))));
  return h('div', { class: 'stack', style: { gap: '4px' } }, rows);
}

function btLlmRemoteBox(s, render) {
  const t = s.test && s.test.provider === s.provider.selected ? s.test : {};
  return h('div', { class: 'bt-llm-step' }, icon(t.durum === 'ok' ? 'check' : 'play'),
    h('div', null, h('b', null, t.durum === 'ok' ? T('The provider works') : T('Test')),
      h('div', { class: 'small muted' }, t.durum === 'running' ? T('Asking the provider a short question…') : t.durum === 'hata' ? t.hata
        : t.durum === 'ok' ? T('Answer in {0} s: "{1}"', t.sure_sn, t.response ?? '') : T('After saving, the provider is asked a short question; if it answers, the bots talk through it.'))),
    t.durum === 'running' ? h('span', { class: 'spin' }) : btn(T('Test'), () => act(() => api('/api/bot/llm/test', {})).then(x => { if (x) render(x); }), 'primary sm', 'play'));
}

function btLlmBox(s, render) {
  const call = (route, msg) => act(() => api('/api/bot/llm/' + route, {}), msg).then(x => { if (x) render(x); });
  const pct = s.toplam ? Math.floor(100 * s.claimed / s.toplam) : 0;
  const t = s.test && !s.test.provider ? s.test : {};          // uzak sağlayıcının testi değil
  const low = s.memory_gb != null && s.memory_gb < s.min_memory_gb;
  const hardware = h('div', { class: 'small muted' }, T('This computer: {0} GB memory, {1} cores.', s.memory_gb ?? '?', s.cores ?? '?'),
    low ? h('b', { style: { color: 'var(--warn)', marginLeft: '6px' } }, T('Recommended at least {0} GB.', s.min_memory_gb)) : null);
  if (!s.supported) return h('div', { class: 'alert hata' }, icon('alert'), h('div', null, T("There is no ready-made language model server for this computer's processor: use Normal mode.")));
  const step1 = s.running
    ? h('div', { class: 'dl-box' }, h('b', null, s.durum === 'installing' ? T('Installing…') : T('Downloading: %{0}', pct)),
      h('div', { class: 'meter' }, h('div', { class: 'meter-bar' }, h('span', { style: { width: pct + '%' } }))),
      h('div', { class: 'small muted dl-info' }, [`${fmtBytes(s.claimed)} / ${fmtBytes(s.toplam)}`, s.hiz ? `${fmtBytes(s.hiz)}/${T('s')}` : null,
        s.time_left_sec != null && s.hiz ? T('{0} remaining', fmtDur(s.time_left_sec)) : null, s.part].filter(Boolean).join(' · ')),
      h('div', { class: 'row' }, btn(T('Stop'), () => call('stop', T('Stopping the download…')), 'ghost sm', 'stop')))
    : ['built', 'hazir'].includes(s.durum)
      ? h('div', { class: 'bt-llm-step' }, icon('check'), h('div', null, h('b', null, T('Installed')), h('div', { class: 'small muted' }, s.model + ' · llama.cpp ' + s.surum)),
        btn(T('Remove'), async () => { if (await confirmBox(T('Delete the language model?'), T('The downloaded 2.5 GB is deleted; Advanced mode works like Normal mode until it is installed again.'), { ok: T('Delete'), danger: true })) call('delete', T('Deleted.')); }, 'ghost sm', 'trash'))
      : h('div', { class: 'bt-llm-step' }, icon('download'), h('div', null, h('b', null, s.durum === 'hata' ? T('Could not be installed') : s.durum === 'stopped' ? T('Download stopped') : T('1. Install the language model')),
        h('div', { class: 'small muted' }, s.durum === 'hata' ? s.hata : T('{0} will be downloaded (resumes where it left off if interrupted).', fmtBytes(s.size))), hardware),
        btn(s.durum === 'hata' || s.durum === 'stopped' || s.partial ? T('Resume') : T('Download and install'), () => call('kur'), 'primary sm', 'download'));
  const installed = ['built', 'hazir'].includes(s.durum);
  const step2 = h('div', { class: 'bt-llm-step' }, icon(s.durum === 'hazir' ? 'check' : 'play'),
    h('div', null, h('b', null, s.durum === 'hazir' ? T('Setup complete: the model is running') : T('2. Test')),
      h('div', { class: 'small muted' }, t.durum === 'running' ? T('The model is loading and a short question is being asked (the first launch can take up to half a minute)…')
        : t.durum === 'hata' ? t.hata : t.durum === 'ok' || s.last_test ? T('Opening {0} s, reply {1} s: "{2}"', (t.startup_sec ?? s.last_test?.startup_sec), (t.sure_sn ?? s.last_test?.sure_sn), (t.response ?? s.last_test?.response ?? ''))
        : T('The model is loaded once and answers a short question; if it replies, setup is complete.'))),
    t.durum === 'running' ? h('span', { class: 'spin' }) : btn(T('Test'), () => call('test'), (installed && s.durum !== 'hazir' ? 'primary' : 'ghost') + ' sm', 'play', { disabled: !installed }));
  return h('div', { class: 'stack', style: { gap: '4px' } }, step1, step2,
    s.durum === 'hazir' ? h('div', { class: 'alert info' }, icon('info'), h('div', null, T("When the game opens, the model opens too; the bots' chat and decisions come from it. If the model can't keep up, the bots behave as in Normal mode."))) : null);
}

// ------------------------------------------------------------------ botların oyun ayarı profili (bot/game_settings.py)
function btGameSettingCard(d) {
  const game_settings = JSON.parse(JSON.stringify(d.settings.game_settings || { profil: 'standard', values: {} }));
  const info = BT.liste?.game_settings || { hazir: [], fields: [] };
  const options = [['standard', T("Standard (the game's own values)")], ['player', T('My game settings')]]
    .concat(info.hazir.map(x => [x.id, T(x.ad)]), [['ozel', T('Custom')]]);
  const save = () => btSetting('game_settings', game_settings);
  const sec = h('select', { class: 'input', onchange: e => { game_settings.profil = e.target.value; save(); btFill(special, renderCustom()); description.textContent = describe(); } },
    options.map(([v, name]) => h('option', { value: v, selected: game_settings.profil === v }, name)));
  const describe = () => {
    const preset = info.hazir.find(x => x.id === game_settings.profil);
    return preset ? T(preset.aciklama) : game_settings.profil === 'player' ? T('Bots also play with the multipliers from the Game Settings page (on an easy setting they level up fast too).')
      : game_settings.profil === 'ozel' ? T('The multipliers below apply to bots only.') : T("Bots play with the game's own rewards and aliens; your game settings don't affect them.");
  };
  const description = h('div', { class: 'help' }, describe());
  const renderCustom = () => game_settings.profil !== 'ozel' ? null : info.fields.map(a => btRow(T(a.ad), T(a.aciklama),
    btSlider(game_settings.values[a.anahtar] ?? 1, v => { game_settings.values[a.anahtar] = v; save(); }, { min: a.en_az, max: a.max_count, step: 0.05, fmt: v => '×' + v.toFixed(2) })));
  const special = h('div', null, renderCustom());
  return h('div', { class: 'card' }, h('h2', null, icon('sliders'), T('Game settings')),
    h('p', { class: 'desc' }, T("Bots' reward and difficulty multipliers are separate from your game settings: even if you pick an easy setting for yourself, bots progress with what you choose here.")),
    h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'name' }, T('Profile')), description), h('div', { class: 'ctl' }, sec)), special);
}
