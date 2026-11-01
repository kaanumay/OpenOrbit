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

const DE = { liste: null, did: null, section: 'genel', summary: null, timer: {}, durum: 'hazir', esyalar: null, alien: null, sec: {} };
// bölüm: kimlik, ad, simge, açıklama, hazır mı (yakında olanlar menüde sönük)
const WE_SECTIONS = [
  ['genel', N('Overview'), 'globe', N("The world's card, a summary of changes and the pilots playing in this world."), true],
  ['haritalar', N('Maps'), 'map', N('Alien spawn list and zones, bonus boxes, portals, safe zones and lairs.'), true],
  ['alien_spawns', N('Aliens'), 'alien', N('Hit points, shield, damage, speed, aggression and rewards; derive a new one from an existing alien.'), true],
  ['quests', N('Quests'), 'target', N('Objectives, rewards, level and prerequisites; a new quest in a few clicks.'), true],
  ['shop', N('Shop'), 'cart', N('Price and currency of products; remove a product from sale.'), true],
  ['auction', N('Auction'), 'gavel', N('Hourly, daily and weekly lots: item, quantity, buy-now price.'), true],
  ['boxes', N('Boxes and Loot'), 'gift', N('Contents of bonus boxes and booty boxes.'), true],
  ['kapilar', N('Galaxy Gates'), 'ring', N('Waves, aliens and gate rewards.'), true],
  ['events', N('Events'), 'calendar', N('Which event is on when in this world; the aliens of map events.'), true],
  ['economy', N('Rewards and Economy'), 'star', N('Level thresholds, rank point formula and rank thresholds.'), true],
];
const weIcon = (id, cls = 'we-icon') => art('ed_' + id, cls);         // bölüm ikonu (images/ed_<bölüm>.webp, OP-009)
const WE_COVER_IMAGES = new Set(['standard', 'nebula', 'crimson', 'ice', 'mining', 'crystal', 'toxic', 'void']);   // gorsel/dunya_<kapak>.webp (OP-010)
// replaceChildren null/false'u metin olarak eklerdi ("null"): koşullu çocuklar süzülür
const fill = (el, ...k) => el.replaceChildren(...k.flat(Infinity).filter(x => x != null && x !== false));
const jp = (...p) => p.map(x => '/' + String(x).replace(/~/g, '~0').replace(/\//g, '~1')).join('');   // JSON Pointer (game_data.py)
const weIsStandard = () => DE.did === 'standard';

function weCover(cover, cls = '') {
  const el = h('div', { class: 'we-cover k-' + (cover || 'nebula') + ' ' + cls });
  if (WE_COVER_IMAGES.has(cover)) el.style.backgroundImage = 'url(images/world_' + cover + '.webp)';
  else el.append(h('i', { class: 'gz' }), h('i', { class: 'hl' }));      // gezegen ve halka (kodla)
  return el;
}

// ------------------------------------------------------------------ giriş noktası
async function renderWorld() {
  await loadGameImages();
  const r = await act(() => api('/api/dunyalar')); if (!r || S.page !== 'world') return;
  DE.liste = r;
  if (DE.did && !r.liste.some(w => w.id === DE.did)) DE.did = null;
  if (!DE.did) return weLibrary();
  weEditor();
}
function weOpen(did, section) { DE.did = did; DE.section = section || 'genel'; DE.alien = null; DE.sec = {}; renderWorld(); }

// ================================================================== KİTAPLIK
function weLibrary() {
  const r = DE.liste, special = r.liste.filter(w => !w.standard);
  const card = w => {
    const pilots = w.users || [];
    return h('div', { class: 'we-card' + (w.standard ? ' standard' : ''), onclick: e => { if (!e.target.closest('button')) weOpen(w.id); } },
      weCover(w.cover, 'buyuk'),
      h('div', { class: 'we-card-body' },
        h('div', { class: 'row between', style: { gap: '8px' } }, h('div', { class: 'we-card-name' }, w.standard ? icon('lock') : null, w.ad),
          w.standard ? badge(T('Read-only'), 'info') : badge(w.changes ? T('{0} changes', w.changes) : T('No changes'), w.changes ? 'orange' : '')),
        h('div', { class: 'we-card-desc muted small' }, w.aciklama || T('No description.')),
        h('div', { class: 'we-card-pilot' }, pilots.length ? [icon('users'), h('span', null, pilots.slice(0, 3).map(p => p.pilot || p.ad).join(', ')
          + (pilots.length > 3 ? ' +' + (pilots.length - 3) : ''))] : h('span', { class: 'dim' }, T('No pilot has this as their default world'))),
        h('div', { class: 'row', style: { gap: '6px', marginTop: 'auto' } },
          btn(w.standard ? T('View') : T('Edit'), () => weOpen(w.id), 'sm primary', w.standard ? 'search' : 'edit'),
          btn(T('Assign to pilot'), ev => weAssignMenu(ev.currentTarget, w), 'sm', 'users'),
          h('span', { class: 'spacer' }),
          btn('', ev => weWorldMenu(ev.currentTarget, w), 'sm ghost icon', 'more', { title: T('More') }))));
  };
  const new_ = h('button', { class: 'we-card yeni', type: 'button', onclick: () => weNewWorld() },
    h('div', { class: 'we-new-icon' }, icon('plus')), h('b', null, T('New world')), h('span', { class: 'muted small' }, T('Start from the standard world or copy a world.')));
  const pilotRow = k => {
    const sel = h('select', { class: 'input', onchange: e => act(() => api('/api/kayitlar/dunya', { id: k.id, world: e.target.value }),
      T('{0}: default world changed.', k.pilot || k.ad)).then(x => { if (x) { DE.liste = x; weLibrary(); poll(); } }) },
      r.liste.map(w => h('option', { value: w.id, selected: w.id === k.world }, w.ad)));
    return h('tr', null, h('td', null, h('b', null, k.pilot || '?'), ' ', badge(k.firma || '?', firmaCls(k.firma)), k.active ? ' ' : null,
      k.active ? badge(T('Active save'), 'ok') : null), h('td', { class: 'muted' }, k.ad), h('td', null, lvl(k.seviye)), h('td', null, sel));
  };
  fill($('#content'), h('div', { class: 'stack' },
    h('div', { class: 'we-intro card' },
      h('div', null, h('h2', null, icon('globe'), T('Worlds')),
        h('p', { class: 'desc', style: { maxWidth: '640px', marginBottom: '0' } }, T("A world is a universe where you change the game's maps, aliens, quests, shop and auction to your liking. Each pilot enters their own default world; PLAY opens that world. The standard world is protected: to keep your changes, create a new world."))),
      h('div', { class: 'row wrap', style: { gap: '8px' } }, btn(T('New world'), () => weNewWorld(), 'primary', 'plus'),
        btn(T('Import'), () => weImport(), '', 'upload')),
      art('drone_editor', 'we-intro-art')),
    h('div', { class: 'we-grid' }, r.liste.map(card), new_),
    !special.length ? h('div', { class: 'card we-empty' }, art('empty_world', 'we-empty-art'), h('div', null, T('You don\'t have a world of your own yet. Open the standard world and change whatever you like, then choose "Save as new world"; or start from a blank copy with "New world".'))) : null,
    r.saves.length ? h('div', { class: 'card' }, h('h2', null, icon('users'), T("Pilots' worlds")),
      h('p', { class: 'desc' }, T("Each save enters its own default world when you press PLAY. When you play with friends, the host's world applies to everyone.")),
      h('table', { class: 'table' }, h('thead', null, h('tr', null, [T('Pilot'), T('Save file'), T('Level'), T('Default world')].map(x => h('th', null, x)))),
        h('tbody', null, r.saves.map(pilotRow)))) : null));
}

function weAssignMenu(anchor, w) {
  const ks = DE.liste.saves;
  if (!ks.length) return toast(T('Create a save first.'), 'info');
  popMenu(anchor, ks.map(k => ({ label: (k.pilot || k.ad) + (k.world === w.id ? '  ✓' : ''), ic: k.world === w.id ? 'check' : 'users',
    fn: () => act(() => api('/api/kayitlar/dunya', { id: k.id, world: w.id }), T('{0} now enters the world "{1}".', k.pilot || k.ad, w.ad))
      .then(x => { if (x) { DE.liste = x; poll(); S.page === 'world' && (DE.did ? weEditor() : weLibrary()); } }) })));
}

function weWorldMenu(anchor, w) {
  const items = [
    { label: w.standard ? T('View') : T('Edit'), iconEl: 'edit', fn: () => weOpen(w.id) },
    { label: T('Copy'), ic: 'copy', fn: async () => {
      const name = await promptBox(T('Copy world'), T('Name of the new world'), w.standard ? T('New world') : T('{0} (copy)', w.ad)); if (name == null) return;
      const x = await act(() => api('/api/dunya/copy', { id: w.id, name }), T('Copied.')); if (x) { DE.liste = x; weLibrary(); } } },
    { label: T('Share / export'), ic: 'download', fn: () => weExport(w) },
  ];
  if (!w.standard) items.push({ label: T('Rename'), ic: 'edit', fn: () => weRename(w) }, '-',
    { label: T('Delete'), ic: 'trash', danger: true, fn: async () => {
      if (!await confirmBox(T('Delete "{0}"?', w.ad), T('The world is deleted; pilots whose default world is this one go back to the standard world. A deleted world is kept in the save/dunyalar/_silinenler folder.'), { ok: T('Delete'), danger: true })) return;
      const x = await act(() => api('/api/dunya/sil', { id: w.id }), T('World deleted.')); if (x) { DE.liste = x; if (DE.did === w.id) DE.did = null; renderWorld(); } } });
  popMenu(anchor, items);
}

async function weRename(w) {
  const name = await promptBox(T('Rename'), T('World name'), w.ad); if (name == null) return;
  const x = await act(() => api('/api/dunya/update', { id: w.id, name }), T('Saved.')); if (x) { DE.liste = x; renderWorld(); }
}

// yeni dünya: ad, açıklama, kapak, başlangıç (standart ya da bir dünya); taslaktan=true ise standart dünyanın taslağı
function weNewWorld({ from_draft = false } = {}) {
  const w = { ad: '', aciklama: '', cover: 'nebula', kaynak: 'standard', record: null };
  const active = DE.liste.saves.find(k => k.active);
  const name = h('input', { class: 'input', placeholder: T("e.g. Hard Space, Hunter's Paradise"), maxlength: 40, oninput: e => { w.ad = e.target.value; } });
  const is_open = h('textarea', { class: 'input', rows: 2, maxlength: 240, placeholder: T("What's different in this world? (optional)"), oninput: e => { w.aciklama = e.target.value; } });
  const covers = h('div', { class: 'we-covers' });
  const renderCover = () => fill(covers, ...DE.liste.covers.filter(k => k !== 'standard').map(k =>
    h('button', { type: 'button', class: 'we-cover-pick' + (w.cover === k ? ' on' : ''), onclick: () => { w.cover = k; renderCover(); } }, weCover(k))));
  renderCover();
  const source = from_draft ? null : h('select', { class: 'input', onchange: e => { w.kaynak = e.target.value; } },
    DE.liste.liste.map(x => h('option', { value: x.id }, x.standard ? T('Standard world (start empty)') : T('Copy: {0}', x.ad))));
  const assign = active ? h('label', { class: 'row', style: { gap: '8px', cursor: 'pointer' } }, h('label', { class: 'switch' },
    h('input', { type: 'checkbox', checked: true, onchange: e => { w.record = e.target.checked ? active.id : null; } }), h('span')),
    h('span', null, T('{0} enters this world (make it their default world)', active.pilot || active.ad))) : null;
  if (active) w.record = active.id;
  const m = modal({ title: from_draft ? T('Save as new world') : T('New world'), wide: true,
    sub: from_draft ? T('The {0} changes you made in the standard world are moved to this world; the standard world stays as it was.', DE.summary?.changes || 0) : null,
    body: h('div', { class: 'stack', style: { gap: '14px' } }, from_draft ? art('drone_record', 'we-save-art') : null, field(T('Name'), name), field(T('Description'), is_open),
      field(T('Cover'), covers), source ? field(T('Start from'), source) : null, assign),
    foot: [btn(T('Cancel'), () => m.close(), 'ghost'), btn(T('Create'), async () => {
      const x = await act(() => api('/api/dunya/create', Object.assign({}, w, { from_draft })), T('World created: {0}', w.ad.trim()));
      if (!x) return;
      m.close(); DE.liste = x; poll(); weOpen(x.yeni, from_draft ? DE.section : 'genel');
    }, 'primary', 'check')] });
}

// ================================================================== EDİTÖR
async function weEditor() {
  const summary = await act(() => api('/api/dunya?world=' + encodeURIComponent(DE.did))); if (!summary || S.page !== 'world') return;
  DE.summary = summary;
  const root = h('div', { class: 'stack', id: 'we-root' });
  fill($('#content'), root);
  root.append(weBar(), h('div', { id: 'we-warning' }), h('div', { class: 'we-layout' }, deMenu(), h('div', { class: 'we-field', id: 'we-field' })));
  weWarning();
  weRenderSection();
}

function weBar() {
  const w = DE.summary;
  return h('div', { class: 'card we-bar' },
    btn('', () => { DE.did = null; renderWorld(); }, 'ghost icon', 'arrowL', { title: T('Worlds') }),
    weCover(w.cover, 'lowercase'),
    h('div', { class: 'we-bar-name' }, h('div', { class: 'row', style: { gap: '8px' } }, h('b', null, w.ad),
      w.standard ? badge([icon('lock'), T('Standard · read-only')], 'info') : badge(T('Custom world'), 'orange')),
      h('div', { class: 'muted small ellipsis' }, w.aciklama || (w.standard ? '' : T('No description.')))),
    h('span', { class: 'spacer' }),
    h('span', { class: 'we-save-status', id: 'we-save-status' }),
    btn(T('Switch world'), ev => popMenu(ev.currentTarget, DE.liste.liste.map(x => ({ label: x.ad + (x.id === DE.did ? '  ✓' : ''),
      ic: x.standard ? 'lock' : 'globe', fn: () => weOpen(x.id, DE.section) }))), 'sm', 'refresh'),
    btn('', ev => weWorldMenu(ev.currentTarget, DE.liste.liste.find(x => x.id === DE.did) || w), 'sm ghost icon', 'more', { title: T('More') }));
}

function weSaveStatus(d) {
  DE.durum = d;
  const el = $('#we-save-status'); if (!el) return;
  el.className = 'we-save-status ' + d;
  fill(el, ...(d === 'kaydediliyor' ? [h('span', { class: 'spin' }), T('Saving…')] : d === 'kaydedildi'
    ? [icon('check'), weIsStandard() ? T('Written to draft') : T('Saved')] : []));
}

function weWarning() {
  const el = $('#we-warning'); if (!el) return;
  const w = DE.summary, out = [];
  if (w.standard) out.push(h('div', { class: 'we-draft' + (w.changes ? ' dolu' : '') }, art('drone_lock', 'we-draft-art'),
    h('div', null, h('b', null, w.changes ? T('{0} unsaved changes', w.changes) : T("The standard world can't be edited")),
      h('div', { class: 'small' }, w.changes ? T('The standard world is protected. To keep these changes, save them to a new world.')
        : T('You can change anything you like: changes are kept in a draft, and you save them as a new world to bring them into the game.'))),
    w.changes ? btn(T('Discard draft'), async () => {
      if (await confirmBox(T('Discard the draft?'), T('The {0} changes you made in the standard world are deleted.', w.changes), { ok: T('Discard'), danger: true }))
        act(() => api('/api/dunya/discard_draft', {}), T('Draft discarded.')).then(x => x && weEditor());
    }, 'sm ghost', 'trash') : null,
    btn(T('Save as new world'), () => weNewWorld({ from_draft: true }), 'sm orange', 'save', { disabled: !w.changes })));
  if (w.server_in_this_world && !w.restart_needed) out.push(h('div', { class: 'alert info' }, icon('zap'),
    h('div', null, T('The server is running with this world: shop and auction changes take effect in game immediately. For changes in other sections, the server must restart.'))));
  if (w.server_in_this_world && w.restart_needed) out.push(h('div', { class: 'alert warning' }, icon('alert'),
    h('div', null, T('Some changes take effect when the server restarts (when the game is closed, PLAY restarts it automatically). Shop and auction changes are already live in game.')),
    btn(T('Restart the server'), async () => {
      if (await confirmBox(T('Restart the server?'), T("If you're in the game, your connection drops; the client reconnects. Your save is kept."), { ok: T('Restart') }))
        act(() => api('/api/dunya/server_restart', {}), T('The server was restarted.')).then(x => x && weEditor());
    }, 'sm', 'refresh')));
  fill(el, ...out);
  el.style.display = out.length ? '' : 'none';
}

function deMenu() {
  return h('nav', { class: 'de-menu', id: 'de-menu' }, WE_SECTIONS.map(([id, name, iconEl, , ready]) => {
    const n = DE.summary.sections[id] || 0;
    return h('button', { type: 'button', class: (DE.section === id ? 'on ' : '') + (ready ? '' : 'soon'), 'data-b': id, disabled: !ready,
      title: ready ? null : T('Coming soon'), onclick: () => { DE.section = id; DE.sec = {}; weMenuCount(); weRenderSection(); } },
      weIcon(id), h('span', null, T(name)), ready ? (n ? h('span', { class: 'we-count' }, n) : null) : h('span', { class: 'we-soon' }, T('Coming soon')));
  }));
}
function weMenuCount() {
  document.querySelectorAll('#de-menu button').forEach(b => {
    b.classList.toggle('on', b.dataset.b === DE.section);
    const n = DE.summary.sections[b.dataset.b] || 0, s = b.querySelector('.we-count');
    if (b.disabled) return;
    if (n && s) s.textContent = n; else if (n) b.append(h('span', { class: 'we-count' }, n)); else if (s) s.remove();
  });
}

function weRenderSection() {
  const b = WE_SECTIONS.find(x => x[0] === DE.section) || WE_SECTIONS[0];
  const area = $('#we-field'); if (!area) return;
  area.parentNode.classList.toggle('dar', b[0] === 'haritalar');          // harita tuvaline yer: menü simge şeridi
  fill(area, h('div', { class: 'empty' }, h('div', { class: 'spin', style: { margin: '30px auto' } })));
  ({ genel: weGeneral, haritalar: weMaps, alien_spawns: weAliens, quests: weQuests, shop: weShop, auction: weAuction, boxes: weBoxes, kapilar: weGates, events: weEvents, economy: weEconomy }[b[0]])(area, b);
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
      const r = await act(() => api('/api/dunya/yama', { world: DE.did, file, route, value }));
      if (r) { DE.summary = Object.assign(DE.summary, r); weMenuCount(); weWarning(); weSaveStatus('kaydedildi'); if (after) after(r); }
      else weSaveStatus('hazir');
      res(r);
    }, ms);
  });
}
async function weRevert(file, route, section) {
  const r = await act(() => api('/api/dunya/geri_al', { world: DE.did, file, route, section }), T('Reset to standard.'));
  if (r) { DE.summary = Object.assign(DE.summary, r); weMenuCount(); weWarning(); }
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
  : h('button', { type: 'button', class: 'we-standard', title: T('Reset to the standard value'), onclick: back }, icon('undo'), T('Standard: {0}', fmt(std)));

// ================================================================== ORTAK SEÇİCİLER
const ITEM_CATEGORY = [['hepsi', N('All')], ['ammunition', N('Ammunition')], ['equipment', N('Equipment')], ['ship', N('Ships')],
  ['drone', N('Drones')], ['resource', N('Resources')], ['booster', N('Boosters')], ['currency', N('Currency')], ['other', N('More')]];
const itemCategory = l => { const p = l.split('_')[0]; return ITEM_CATEGORY.some(k => k[0] === p) ? p : 'other'; };

async function pickItem(title = T('Select item')) {
  if (!DE.esyalar) { const r = await act(() => api('/api/dunya/esyalar')); if (!r) return null; DE.esyalar = r.esyalar; }
  return new Promise(res => {
    let multiplier = 'hepsi', q = '', limit = 120, done = false;
    const grid = h('div', { class: 'we-picker-grid' });
    const render = () => {
      const s = q.trim().toLowerCase();
      const list = DE.esyalar.filter(l => (multiplier === 'hepsi' || itemCategory(l) === multiplier) && (!s || l.includes(s) || itemName(l).toLowerCase().includes(s)));
      fill(grid, ...list.slice(0, limit).map(l => h('button', { type: 'button', class: 'we-picker-item', title: l,
        onclick: () => { done = true; m.close(); res(l); } }, gameIcon(l, 44, null, 'box'), h('span', null, itemName(l)))),
        list.length > limit ? h('button', { type: 'button', class: 'btn sm we-more', onclick: () => { limit += 240; render(); } }, T('{0} more items', fmtN(list.length - limit))) : null,
        !list.length ? h('div', { class: 'empty small muted' }, T('No matching items.')) : null);
    };
    const seg = h('div', { class: 'seg' }, ITEM_CATEGORY.map(([k, name]) => h('button', { class: k === multiplier ? 'on info' : '', onclick: e => {
      multiplier = k; seg.querySelectorAll('button').forEach(b => b.classList.remove('on', 'info')); e.currentTarget.classList.add('on', 'info'); render(); } }, T(name))));
    const search = h('input', { class: 'input', placeholder: T('Search by name or ID…'), oninput: e => { q = e.target.value; limit = 120; render(); } });
    const m = modal({ title: title, wide: true, onclose: () => { if (!done) res(null); }, body: h('div', { class: 'stack', style: { gap: '10px' } },
      search, seg, !GI.index ? h('div', { class: 'small muted' }, T('The game images are prepared once the game has been started with BepInEx.')) : null, grid) });
    render();
  });
}

async function alienList() {
  if (!DE.alien) { const r = await act(() => api('/api/dunya/section?bolum=alien_spawns&world=' + encodeURIComponent(DE.did))); if (!r) return null; DE.alien = r.alien_spawns; }
  return DE.alien;
}
const npcIcon = (u, size) => u && u.icon && GI.index?.sprite[u.icon] ? sprite(u.icon, size) : h('span', { class: 'sprite vacant we-npc-empty', style: { width: size + 'px', height: size + 'px' } }, icon('alien'));
const npcName = u => (u?.ad || '').replace(/^[-=\[\]:.{}\s]+|[-=\[\]:.{}\s]+$/g, '') || u?.tip || '?';

async function pickAlien(title = T('Select alien'), { with_id = false, numeric = false } = {}) {
  const entries = await alienList(); if (!entries) return null;
  return new Promise(res => {
    let q = '', filter_by = 'harita', done = false;
    const grid = h('div', { class: 'we-picker-grid npc' });
    const render = () => {
      const s = q.trim().toLowerCase();
      const l = entries.filter(u => (!with_id || u.npc_kimlik != null) && (!numeric || /^\d+$/.test(u.tip)) && (filter_by === 'hepsi' || (filter_by === 'harita' ? u.nerede.length || u.yeni : u.etkinlik))
        && (!s || npcName(u).toLowerCase().includes(s)));
      fill(grid, ...l.map(u => h('button', { type: 'button', class: 'we-picker-item', onclick: () => { done = true; m.close(); res(u); } },
        npcIcon(u, 44), h('span', null, npcName(u)), h('small', { class: 'muted' }, T('HP {0}', fmtN(u.hp))))),
        !l.length ? h('div', { class: 'empty small muted' }, T('No matching aliens.')) : null);
    };
    const seg = h('div', { class: 'seg' }, [['harita', N('Spawning on maps')], ['etkinlik', N('Event')], ['hepsi', N('All')]].map(([k, name]) =>
      h('button', { class: k === filter_by ? 'on info' : '', onclick: e => { filter_by = k; seg.querySelectorAll('button').forEach(b => b.classList.remove('on', 'info')); e.currentTarget.classList.add('on', 'info'); render(); } }, T(name))));
    const m = modal({ title: title, wide: true, onclose: () => { if (!done) res(null); }, body: h('div', { class: 'stack', style: { gap: '10px' } },
      h('input', { class: 'input', placeholder: T('Search aliens…'), oninput: e => { q = e.target.value; render(); } }), seg, grid) });
    render();
  });
}

let WE_MAPS = null;
async function pickMap(title, selected = [], { multi = true } = {}) {
  if (!WE_MAPS) { const r = await act(() => api('/api/dunya/section?bolum=haritalar&world=' + encodeURIComponent(DE.did))); if (!r) return null; WE_MAPS = r.haritalar; }
  return new Promise(res => {
    const sec = new Set(selected.map(String)); let done = false;
    const group = h('div', { class: 'we-map-chips' });
    const render = () => fill(group, ...WE_MAPS.map(x => h('button', { type: 'button', class: 'we-map-chip f-' + x.firma + (sec.has(x.ad) ? ' on' : ''),
      onclick: () => { if (!multi) { done = true; m.close(); return res([x.ad]); } sec.has(x.ad) ? sec.delete(x.ad) : sec.add(x.ad); render(); } }, x.ad)));
    const m = modal({ title: title, wide: true, onclose: () => { if (!done) res(null); }, body: h('div', { class: 'stack', style: { gap: '10px' } },
      multi ? h('div', { class: 'small muted' }, T('If none is selected, it applies on every map.')) : null, group),
      foot: multi ? [btn(T('Clear'), () => { sec.clear(); render(); }, 'ghost'), btn(T('OK'), () => { done = true; m.close(); res([...sec]); }, 'primary')] : null });
    render();
  });
}

// ================================================================== GENEL BAKIŞ
function weGeneral(area, b) {
  const w = DE.summary;
  const covers = h('div', { class: 'we-covers' });
  const renderCover = () => fill(covers, ...DE.liste.covers.filter(k => k !== 'standard').map(k =>
    h('button', { type: 'button', class: 'we-cover-pick' + (w.cover === k ? ' on' : ''), disabled: w.standard, onclick: () =>
      act(() => api('/api/dunya/update', { id: w.id, cover: k })).then(x => { if (x) { DE.liste = x; w.cover = k; renderCover(); $('#de-kok .we-bar .we-cover').replaceWith(weCover(k, 'lowercase')); } }) }, weCover(k))));
  renderCover();
  const saveMeta = (fieldName, v) => act(() => api('/api/dunya/update', { id: w.id, [fieldName]: v })).then(x => { if (x) { DE.liste = x; w[fieldName] = v; weSaveStatus('kaydedildi'); } });
  const card = h('div', { class: 'card we-overview-card' }, weCover(w.cover, 'buyuk'),
    h('div', { class: 'stack', style: { gap: '12px' } },
      w.standard ? h('div', null, h('h3', { class: 'de-h3' }, icon('lock'), w.ad), h('p', { class: 'muted' }, w.aciklama))
        : [field(T('Name'), h('input', { class: 'input', value: w.ad, maxlength: 40, onchange: e => saveMeta('ad', e.target.value).then(() => weEditor()) })),
          field(T('Description'), h('textarea', { class: 'input', rows: 2, maxlength: 240, onchange: e => saveMeta('aciklama', e.target.value) }, w.aciklama || '')),
          field(T('Cover'), covers)],
      h('div', { class: 'row wrap small muted', style: { gap: '14px' } }, w.created ? h('span', null, T('Created {0}', fmtWhen(w.created))) : null,
        w.update ? h('span', null, T('Last changed {0}', fmtWhen(w.update))) : null)));
  const sections = h('div', { class: 'card' }, h('h2', null, icon('layers'), T('Changes')),
    h('p', { class: 'desc' }, w.changes ? T('What differs from standard in this world. You can reset a section to standard with one click.') : T('This world is still identical to the standard world. Start editing from the sections on the left.')),
    h('div', { class: 'we-summary-grid' }, WE_SECTIONS.filter(x => x[0] !== 'genel').map(x => {
      const n = w.sections[x[0]] || 0;
      return h('div', { class: 'we-summary-box' + (n ? ' dolu' : '') + (x[4] ? '' : ' soon') },
        h('div', { class: 'row', style: { gap: '8px' } }, weIcon(x[0], 'we-icon orta'), h('b', null, T(x[1]))),
        h('div', { class: 'we-summary-count' }, x[4] ? (n ? T('{0} changes', n) : T('Standard')) : T('Coming soon')),
        h('div', { class: 'row', style: { gap: '6px' } }, x[4] ? btn(T('Open'), () => { DE.section = x[0]; weMenuCount(); weRenderSection(); }, 'sm', 'chevR') : null,
          n ? btn('', async () => {
            if (await confirmBox(T('Reset {0} to standard?', T(x[1])), T('{0} changes in this section will be deleted.', n), { ok: T('Reset to standard'), danger: true }))
              weRevert(null, null, x[0]).then(r => r && weRenderSection());
          }, 'sm ghost icon', 'undo', { title: T('Reset to standard') }) : null));
    })));
  const users = (DE.liste.liste.find(x => x.id === w.id) || {}).users || [];
  const pilots = h('div', { class: 'card' }, h('h2', null, icon('users'), T('Playing in this world')),
    h('p', { class: 'desc' }, users.length ? T('These pilots enter this world when they press PLAY.') : T('No pilot has made this world their default yet.')),
    h('div', { class: 'chips' }, users.map(p => h('span', { class: 'chip' }, icon('users'), p.pilot || p.ad))),
    h('div', { class: 'row', style: { marginTop: '12px' } }, btn(T('Assign to pilot'), ev => weAssignMenu(ev.currentTarget, w), 'sm', 'users')));
  fill(area, h('div', { class: 'stack' }, card, sections, pilots,
    h('div', { class: 'alert info' }, icon('info'), h('div', null, T("Client limits: new maps or new items can't be added (both are in the game's own files). New aliens are copies of an existing model with new values; their names show in the game.")))));
}

// ================================================================== UZAYLILAR
const ORE_NAME = { 0: 'resource_ore_prometium', 1: 'resource_ore_endurium', 2: 'resource_ore_terbium', 3: 'resource_ore_xenomit', 4: 'resource_ore_prometid',
  5: 'resource_ore_duranium', 6: 'resource_ore_promerium', 7: 'resource_ore_seprom', 8: 'resource_ore_palladium', 28: 'resource_ore_osmium' };
const REWARD_FIELD = [['ep', N('Experience'), 'source_experience'], ['onur', N('Honor'), 'source_onur'], ['kredi', N('Credits'), 'source_kredi'], ['uridyum', N('Uridium'), 'source_uridyum']];

async function weAliens(area, b) {
  DE.alien = null;
  const entries = await alienList(); if (!entries || DE.section !== 'alien_spawns') return;
  const f = DE.sec.aliens || (DE.sec.aliens = { q: '', filter_by: 'harita', selected: null });
  const grid = h('div', { class: 'we-npc-list' }), detail = h('div', { class: 'we-detail' });
  const maxHp = Math.max(...entries.map(u => u.hp)), scale = v => Math.max(3, Math.log10(1 + v) / Math.log10(1 + maxHp) * 100);   // can/kalkan çubuğu (logaritmik)
  const render = () => {
    const s = f.q.trim().toLowerCase();
    const l = entries.filter(u => (f.filter_by === 'hepsi' || (f.filter_by === 'harita' ? u.nerede.length || u.yeni : f.filter_by === 'etkinlik' ? u.etkinlik
      : f.filter_by === 'changed' ? u.changed : u.yeni)) && (!s || npcName(u).toLowerCase().includes(s)));
    fill(grid, ...l.map(u => h('button', { type: 'button', class: 'de-npc' + (f.selected === u.tip ? ' on' : '') + (u.changed ? ' degisti' : ''),
      onclick: () => { f.selected = u.tip; render(); } }, npcIcon(u, 40),
      h('div', { class: 'we-npc-name' }, h('b', null, npcName(u)), h('div', { class: 'we-bars' },
        h('i', { class: 'hp', style: { width: scale(u.hp) + '%' } }), h('i', { class: 'sh', style: { width: scale(u.kalkan) + '%' } }))),
      u.yeni ? badge(T('New'), 'orange') : u.aggressive ? h('span', { class: 'we-aggressive', title: T('Hostile') }, icon('zap')) : null)),
      !l.length ? h('div', { class: 'empty small muted' }, T('No matching aliens.')) : null);
    const u = entries.find(x => x.tip === f.selected) || l[0];
    if (u && !f.selected) { f.selected = u.tip; grid.querySelector('.de-npc')?.classList.add('on'); }
    fill(detail, u ? alienDetail(u, entries, render) : h('div', { class: 'empty muted' }, T('Pick an alien from the left.')));
  };
  const seg = h('div', { class: 'seg' }, [['harita', N('On maps')], ['etkinlik', N('Event')], ['changed', N('Modified')], ['yeni', N('New')], ['hepsi', N('All')]].map(([k, name]) =>
    h('button', { class: f.filter_by === k ? 'on info' : '', onclick: () => { f.filter_by = k; weRenderSection(); } }, T(name))));
  fill(area, h('div', { class: 'card' }, weTitle(b, h('input', { class: 'input', style: { width: '200px' }, placeholder: T('Search aliens…'), value: f.q, oninput: e => { f.q = e.target.value; render(); } }), seg),
    h('div', { class: 'we-two-col' }, grid, detail)));
  render();
}

function alienDetail(u, entries, refresh) {
  const t = JSON.parse(JSON.stringify(u.full)), std = u.standard;
  const route = jp('types', u.tip);
  const save = () => {
    Object.assign(u, { ad: t.ad, hp: t.hp, kalkan: t.kalkan, hasar: t.hasar, hiz: t.hiz, aggressive: t.aggressive, reward: t.reward, kargo: t.kargo, full: t, changed: true });
    wePatch('npc.json', route, t);
  };
  const back = async () => { if (await weRevert('npc.json', route)) { DE.alien = null; weRenderSection(); } };
  const row = (name, fieldName, opts) => h('div', { class: 'we-field-row' + (std && std[fieldName] !== t[fieldName] ? ' degisti' : '') },
    h('label', null, name), weNumber(t[fieldName], v => { t[fieldName] = v; save(); refreshRows(); }, opts),
    std ? weStd(std[fieldName], t[fieldName], () => { t[fieldName] = std[fieldName]; save(); refreshRows(); }) : null);
  const box = h('div', { class: 'stack', style: { gap: '8px' } });
  const refreshRows = () => fill(box, 
    row(T('Hit points'), 'hp', { max: 50000000, step: 100, width: 110 }), row(T('Shield'), 'kalkan', { max: 50000000, step: 100, width: 110 }),
    row(T('Damage'), 'hasar', { max: 1000000, step: 10 }), row(T('Speed'), 'hiz', { max: 2000, step: 5 }),
    h('div', { class: 'we-field-row' + (std && std.aggressive !== t.aggressive ? ' degisti' : '') }, h('label', null, T('Hostile')),
      h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: t.aggressive, onchange: e => { t.aggressive = e.target.checked; save(); refreshRows(); } }), h('span')),
      h('span', { class: 'small muted' }, t.aggressive ? T('Attacks you on sight.') : T('Fights back only when attacked.'))),
    h('div', { class: 'we-subtitle' }, T('Kill reward')),
    h('div', { class: 'we-reward-grid' }, REWARD_FIELD.map(([k, name, g]) => h('div', { class: 'we-reward' + (std && (std.reward || {})[k] !== t.reward[k] ? ' degisti' : '') },
      art(g, 'we-reward-icon'), h('div', null, h('div', { class: 'small muted' }, T(name)), weNumber(t.reward[k] || 0, v => { t.reward[k] = v; save(); }, { max: 1e9, step: k === 'uridyum' ? 1 : 10, width: 86 }))))),
    h('div', { class: 'we-subtitle' }, T('Cargo box (ore)')),
    h('div', { class: 'we-cargo' }, Object.entries(ORE_NAME).filter(([i]) => t.kargo[i] || +i < 8).map(([i, loot]) =>
      h('div', { class: 'we-cargo-item' + (t.kargo[i] ? ' var' : '') }, gameIcon(loot, 26, null, 'box'), h('span', { class: 'small' }, itemName(loot)),
        weNumber(t.kargo[i] || 0, v => { if (v) t.kargo[i] = v; else delete t.kargo[i]; save(); }, { max: 100000, step: 1, width: 64 })))));
  refreshRows();
  const nameInp = h('input', { class: 'input we-name-input', value: t.ad, maxlength: 60, onchange: e => { t.ad = e.target.value; save(); } });
  const deriveAlien = async () => {
    const name = await promptBox(T('Derive new alien'), T("The new alien's name shown in the game"), '-=[ ' + npcName(u) + ' X ]=-'); if (name == null) return;
    const n = Math.max(0, ...entries.filter(x => x.tip.startsWith('custom_')).map(x => +x.tip.slice('custom_'.length) || 0)) + 1;
    const new_ = Object.assign(JSON.parse(JSON.stringify(t)), { name, model: t.model || u.tip, npc_kimlik: null, _kaynak: 'Dünya Editörü: ' + u.tip });
    delete new_.npc_kimlik; delete new_.etkinlik; delete new_.haritalar;
    const r = await wePatch('npc.json', jp('types', 'custom_' + n), new_, { ms: 0 });
    if (r) { toast(T("New alien created. You can add it to a map's spawn list from the Maps section."), 'ok'); DE.alien = null; DE.sec.aliens.selected = 'custom_' + n; DE.sec.aliens.filter_by = 'yeni'; weRenderSection(); }
  };
  return h('div', { class: 'stack', style: { gap: '14px' } },
    h('div', { class: 'we-detail-head' }, npcIcon(u, 64), h('div', { style: { flex: 1, minWidth: 0 } }, nameInp,
      h('div', { class: 'small muted' }, u.yeni ? T('New alien · model: {0}', u.model) : T('Type {0}', u.tip), std && std.ad !== t.ad ? [' · ', weStd(std.ad, t.ad, () => { t.ad = std.ad; nameInp.value = std.ad; save(); }, x => x)] : null))),
    box,
    h('div', { class: 'we-subtitle' }, T('Where it spawns')),
    u.nerede.length ? h('div', { class: 'chips' }, u.nerede.map(m => h('button', { type: 'button', class: 'chip link', onclick: () => {
      const hm = (WE_MAPS || []).find(x => x.ad === m); DE.section = 'haritalar'; DE.sec = { hr: { selected: hm ? hm.id : null } }; weMenuCount(); weRenderSection(); } }, icon('map'), m)))
      : h('div', { class: 'small muted' }, T("Not in any map's spawn list.")),
    h('div', { class: 'row wrap', style: { gap: '8px', marginTop: '6px' } },
      btn(T('Derive a new alien from this'), deriveAlien, 'sm', 'copy'),
      u.changed && !u.yeni ? btn(T('Reset to standard'), back, 'sm ghost', 'undo') : null,
      u.yeni ? btn(T('Delete'), async () => {
        if (await confirmBox(T('Delete the alien?'), T('Its rows in the spawn lists are removed too.'), { ok: T('Delete'), danger: true })) {
          const r = await wePatch('npc.json', route, { $delete: true }, { ms: 0 }); if (r) { DE.alien = null; DE.sec.aliens.selected = null; weRenderSection(); } }
      }, 'sm danger', 'trash') : null));
}

// ================================================================== HARİTALAR
const MAP_TOOL = [['sec', N('Select and move'), 'move'], ['region', N('Spawn zone'), 'target'], ['in', N('Lair (fixed spawn point)'), 'nest'], ['safe', N('Safe zone'), 'shield']];
const MAP_LAYER = [['gridline', N('Grid')], ['block', N('Obstacles')], ['safe', N('Safe zones')], ['portal', N('Portals')], ['region', N('Spawn zones')], ['in', N('Lairs')]];
const MAP_COMPANY = { mmo: N('MMO'), eic: N('EIC'), vru: N('VRU'), savas: N('Battle'), pirate: N('Pirate'), bl: N('Black Light'), other: N('More') };

async function weMaps(area, b) {
  const r = await act(() => api('/api/dunya/section?bolum=haritalar&world=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'haritalar') return;
  WE_MAPS = r.haritalar;
  await alienList();
  const f = DE.sec.hr || (DE.sec.hr = {});
  f.tool = f.tool || 'sec'; f.layer = f.layer || { gridline: true, block: true, safe: true, portal: true, region: true, in: true };
  if (!f.selected || !r.haritalar.some(x => x.id === f.selected)) f.selected = r.haritalar[0]?.id;
  const groups = {};
  r.haritalar.forEach(x => (groups[x.firma] = groups[x.firma] || []).push(x));
  const entries = h('div', { class: 'we-map-list' }, Object.entries(groups).map(([fi, xs]) => h('div', { class: 'we-map-group' },
    h('div', { class: 'we-map-group-name f-' + fi }, T(MAP_COMPANY[fi] || fi)),
    h('div', { class: 'we-map-group-chips' }, xs.map(x => h('button', { type: 'button', class: 'we-map-chip f-' + x.firma + (x.id === f.selected ? ' on' : '') + (x.changed ? ' degisti' : ''),
      title: T('{0} aliens', fmtN(x.alien)), onclick: () => { f.selected = x.id; f.object = null; weRenderSection(); } }, x.ad))))));
  const canvas = h('div', { class: 'we-canvas-card' }), panel = h('div', { class: 'we-map-panel' });
  fill(area, h('div', { class: 'card we-map-card' }, weTitle(b), entries, h('div', { class: 'we-map' }, canvas, panel)));
  const hm = await act(() => api('/api/dunya/harita?world=' + encodeURIComponent(DE.did) + '&id=' + f.selected)); if (!hm || DE.section !== 'haritalar') return;
  mapEditor(hm, canvas, panel, f);
}

function mapEditor(hm, canvas, panel, f) {
  const [W, H] = hm.size, layout = JSON.parse(JSON.stringify(hm.layout || {}));
  layout.safe = layout.safe || []; layout.lairs = layout.lairs || {}; layout.portals = layout.portals || {};
  const npc = hm.npc.map(g => Object.assign({}, g));
  const aliens = tip => (DE.alien || []).find(u => u.tip === tip);
  const saveNpc = () => { wePatch('npc.json', jp('haritalar', hm.id, 'npc'), npc.map(g => g.region ? { tip: g.tip, adet: g.adet, region: g.region } : { tip: g.tip, adet: g.adet })); markSelected(); };
  const saveLayout = () => { const d = JSON.parse(JSON.stringify(layout)); if (!d.safe.length) delete d.safe; if (!Object.keys(d.lairs).length) delete d.lairs;
    if (!Object.keys(d.portals).length) delete d.portals; wePatch('map_layout.json', jp('haritalar', hm.id), d); markSelected(); };
  const markSelected = () => { const c = document.querySelector('.we-map-chip.on'); if (c) c.classList.add('changed'); };

  // ---- tuval (SVG, oyun birimleri)
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('class', 'de-svg');
  svg.style.setProperty('--s', W / 21000);      // etiketlerin boyu harita ölçeğiyle
  const el = (tag, at, ...kids) => { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(at || {})) e.setAttribute(k, v); kids.forEach(k => k && e.append(k)); return e; };
  const S1 = W / 21000;            // ölçek: 2x haritada işaretler de büyür
  // tepeden işaret (images/harita_<ad>.webp, OP-011): merkez (x, y), boy oyun birimi
  const beacon = (name, x, y, size) => el('image', { href: 'images/map_' + name + '.webp', x: x - size * S1 / 2, y: y - size * S1 / 2, width: size * S1, height: size * S1, class: 'beacon' });
  const point = e => { const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; const q = p.matrixTransform(svg.getScreenCTM().inverse()); return [Math.round(Math.max(0, Math.min(W, q.x))), Math.round(Math.max(0, Math.min(H, q.y)))]; };
  let drag = null;
  const dragStart = (e, obj, update, finished) => { e.stopPropagation(); e.preventDefault(); f.object = obj; drag = { update, finished, moved: false }; svg.setPointerCapture(e.pointerId); renderMapPanel(); render(); };
  svg.addEventListener('pointermove', e => { if (!drag) return; drag.moved = true; drag.update(point(e)); render(); });
  svg.addEventListener('pointerup', () => { if (drag) { const s = drag; drag = null; if (s.moved) s.finished(); renderMapPanel(); } });
  svg.addEventListener('pointerdown', async e => {
    if (e.target !== svg && !e.target.classList.contains('we-ground')) return;
    const [x, y] = point(e);
    if (f.tool === 'safe') { layout.safe.push([x, y, 1500 * S1 | 0]); f.object = { tur: 'safe', i: layout.safe.length - 1 }; saveLayout(); }
    else if (f.tool === 'region' || f.tool === 'in') {
      const candidates = f.tool === 'region' ? npc.filter(g => !g.region) : npc;
      if (!candidates.length) return toast(f.tool === 'region' ? T('Every type has a zone. Add an alien to the list first.') : T('Add an alien to the list first.'), 'info');
      const sec = candidates.length === 1 ? candidates[0] : await new Promise(res => popMenuAt(e.clientX, e.clientY, candidates.map(g => ({ label: npcName(aliens(g.tip)) + ' ×' + g.adet, ic: 'alien', fn: () => res(g) }))));
      if (!sec) return;
      if (f.tool === 'region') { sec.region = [x, y, 2500 * S1 | 0]; f.object = { tur: 'region', tip: sec.tip }; saveNpc(); }
      else { (layout.lairs[sec.tip] = layout.lairs[sec.tip] || []).push([x, y]); f.object = { tur: 'in', tip: sec.tip, i: layout.lairs[sec.tip].length - 1 }; saveLayout(); }
    } else { f.object = null; }
    renderMapPanel(); render();
  });
  const render = () => {
    fill(svg);
    svg.append(el('rect', { x: 0, y: 0, width: W, height: H, class: 'we-ground' }));
    if (f.layer.gridline) for (let x = 1000; x < W; x += 1000) svg.append(el('line', { x1: x, y1: 0, x2: x, y2: H, class: x % 5000 ? 'iz' : 'iz thick' }));
    if (f.layer.gridline) for (let y = 1000; y < H; y += 1000) svg.append(el('line', { x1: 0, y1: y, x2: W, y2: y, class: y % 5000 ? 'iz' : 'iz thick' }));
    if (f.layer.block) hm.obstacles.forEach(([x0, y0, x1, y1]) => svg.append(el('rect', { x: x0, y: y0, width: x1 - x0, height: y1 - y0, class: 'block' })));
    if (hm.istasyon) { const [sx, sy] = hm.istasyon; svg.append(el('circle', { cx: sx, cy: sy, r: 1800 * S1, class: 'station-area' }), beacon('istasyon', sx, sy, 1100),
      el('text', { x: sx, y: sy + 860 * S1, class: 'etiket' }, document.createTextNode(T('Station')))); }
    if (hm.structure) svg.append(beacon('quest_giver', hm.structure[0], hm.structure[1], 700));
    if (f.layer.safe) layout.safe.forEach((z, i) => { const on = f.object?.tur === 'safe' && f.object.i === i;
      const c = el('circle', { cx: z[0], cy: z[1], r: z[2], class: 'safe' + (on ? ' on' : '') });
      c.addEventListener('pointerdown', e => f.tool === 'sec' && dragStart(e, { tur: 'safe', i }, ([x, y]) => { z[0] = x; z[1] = y; }, saveLayout));
      svg.append(c, beacon('safe', z[0], z[1], 520)); if (on) svg.append(handle(z, () => saveLayout())); });
    if (f.layer.region) npc.filter(g => g.region).forEach(g => { const z = g.region, on = f.object?.tur === 'region' && f.object.tip === g.tip;
      const gr = el('g', { class: 'region' + (on ? ' on' : '') + (aliens(g.tip)?.aggressive ? ' saldirgan' : '') });
      gr.append(el('circle', { cx: z[0], cy: z[1], r: z[2] }), el('text', { x: z[0], y: z[1], class: 'etiket ortada' }, document.createTextNode(npcName(aliens(g.tip)) + ' ×' + g.adet)));
      gr.addEventListener('pointerdown', e => f.tool === 'sec' && dragStart(e, { tur: 'region', tip: g.tip }, ([x, y]) => { z[0] = x; z[1] = y; }, saveNpc));
      svg.append(gr); if (on) svg.append(handle(z, () => saveNpc())); });
    if (f.layer.in) Object.entries(layout.lairs).forEach(([tip, pts]) => pts.forEach((p, i) => { const on = f.object?.tur === 'in' && f.object.tip === tip && f.object.i === i;
      const pg = el('g', { class: 'in' + (on ? ' on' : '') }, el('circle', { cx: p[0], cy: p[1], r: 420 * S1, class: 'in-halo' }), beacon('in', p[0], p[1], 720));
      pg.addEventListener('pointerdown', e => f.tool === 'sec' && dragStart(e, { tur: 'in', tip, i }, ([x, y]) => { p[0] = x; p[1] = y; }, saveLayout));
      svg.append(pg, el('text', { x: p[0], y: p[1] + 620 * S1, class: 'etiket lowercase' }, document.createTextNode(npcName(aliens(tip))))); }));
    if (f.layer.portal) hm.portals.forEach(g => { const on = f.object?.tur === 'portal' && f.object.key === g.key, r = 330 * S1;
      const gr = el('g', { class: 'portal' + (on ? ' on' : '') + (layout.portals[g.key] ? ' tasindi' : '') });
      gr.append(el('circle', { cx: g.x, cy: g.y, r: r * 1.9, class: 'portal-area' }), el('circle', { cx: g.x, cy: g.y, r: r * 1.25, class: 'portal-halo' }), beacon('portal', g.x, g.y, 900),
        el('text', { x: g.x, y: g.y - r * 2.3, class: 'etiket' }, document.createTextNode('→ ' + g.hedef)));
      gr.addEventListener('pointerdown', e => f.tool === 'sec' && dragStart(e, { tur: 'portal', key: g.key }, ([x, y]) => { g.x = x; g.y = y; layout.portals[g.key] = [x, y]; }, saveLayout));
      svg.append(gr); });
  };
  // yarıçap tutamacı (seçili daire): sağ kenarından sürükle
  const handle = (z, finished) => { const t = el('circle', { cx: z[0] + z[2], cy: z[1], r: 160 * S1, class: 'handle' });
    t.addEventListener('pointerdown', e => dragStart(e, f.object, ([x, y]) => { z[2] = Math.max(200, Math.round(Math.hypot(x - z[0], y - z[1]))); }, finished)); return t; };

  const tools = h('div', { class: 'we-tools' }, h('div', { class: 'seg' }, MAP_TOOL.map(([k, name, iconEl]) => h('button', { class: f.tool === k ? 'on info' : '', title: T(name),
    onclick: e => { f.tool = k; e.currentTarget.parentNode.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === e.currentTarget)); e.currentTarget.parentNode.querySelectorAll('button').forEach(x => x.classList.toggle('info', x === e.currentTarget)); svg.dataset.tool = k; hint(); } },
      k === 'in' || k === 'safe' ? art('map_' + k, 'we-tool-icon') : icon(iconEl)))),
    h('span', { class: 'we-tool-tip small muted', id: 'we-tool-tip' }), h('span', { class: 'spacer' }),
    btn('', ev => popMenu(ev.currentTarget, MAP_LAYER.map(([k, name]) => ({ label: T(name) + (f.layer[k] ? '  ✓' : ''), ic: f.layer[k] ? 'check' : 'layers', fn: () => { f.layer[k] = !f.layer[k]; render(); } }))), 'sm ghost icon', 'layers', { title: T('Layers') }));
  const hint = () => { const e = $('#we-tool-tip'); if (e) e.textContent = { sec: T("Drag objects; change the selected circle's radius with the dot on its edge."),
    region: T('Click the map: the alien type you chose spawns inside this circle.'), in: T("Click the map: the type's fixed spawn point (aliens appear here)."),
    safe: T('Click the map: safe zone (aliens neither attack nor spawn).') }[f.tool]; };
  svg.dataset.tool = f.tool;
  fill(canvas, tools, h('div', { class: 'we-svg-wrap' }, svg), h('div', { class: 'we-canvas-bottom small muted' },
    h('span', null, hm.ad + ' · ' + fmtN(W) + ' × ' + fmtN(H)), h('span', { class: 'spacer' }),
    h('span', { class: 'we-legend' }, art('map_portal'), T('Portal'), art('map_safe'), T('Safe'), h('i', { class: 'l-zone' }), T('Spawn zone'), art('map_in'), T('Lair'), h('i', { class: 'l-obstacle' }), T('Obstacle'))));
  hint(); render();

  // ---- sağ panel: seçili nesne ya da doğma listesi
  const renderMapPanel = () => {
    const n = f.object, out = [];
    if (n) {
      const back = btn(T('Deselect'), () => { f.object = null; renderMapPanel(); render(); }, 'sm ghost', 'arrowL');
      if (n.tur === 'portal') {
        const g = hm.portals.find(x => x.key === n.key);
        out.push(h('div', { class: 'we-subtitle' }, T('Portal → {0}', g.hedef)), position(g, v => { g.x = v[0]; g.y = v[1]; layout.portals[g.key] = v; saveLayout(); render(); }),
          layout.portals[g.key] ? btn(T('Return to the standard position'), () => { delete layout.portals[g.key]; saveLayout(); toast(T('The portal is at its standard position (visible after you refresh the page).'), 'info'); }, 'sm ghost', 'undo') : null);
      } else if (n.tur === 'safe') {
        const z = layout.safe[n.i];
        out.push(h('div', { class: 'we-subtitle' }, T('Safe zone')), position(z, v => { z[0] = v[0]; z[1] = v[1]; saveLayout(); render(); }),
          h('div', { class: 'we-field-row' }, h('label', null, T('Radius')), weNumber(z[2], v => { z[2] = v; saveLayout(); render(); }, { min: 100, max: 6000, step: 100 })),
          btn(T('Delete the zone'), () => { layout.safe.splice(n.i, 1); f.object = null; saveLayout(); renderMapPanel(); render(); }, 'sm danger', 'trash'));
      } else if (n.tur === 'region') {
        const g = npc.find(x => x.tip === n.tip);
        out.push(h('div', { class: 'we-subtitle' }, T('Spawn zone')), h('div', { class: 'row', style: { gap: '8px' } }, npcIcon(aliens(g.tip), 32), h('b', null, npcName(aliens(g.tip)) + ' ×' + g.adet)),
          position(g.region, v => { g.region[0] = v[0]; g.region[1] = v[1]; saveNpc(); render(); }),
          h('div', { class: 'we-field-row' }, h('label', null, T('Radius')), weNumber(g.region[2], v => { g.region[2] = v; saveNpc(); render(); }, { min: 200, max: 15000, step: 100 })),
          h('p', { class: 'small muted' }, T('Aliens spawn and respawn inside this circle; then they roam the map.')),
          btn(T('Remove the zone (scatter over the map)'), () => { delete g.region; f.object = null; saveNpc(); renderMapPanel(); render(); }, 'sm danger', 'trash'));
      } else if (n.tur === 'in') {
        const p = layout.lairs[n.tip][n.i];
        out.push(h('div', { class: 'we-subtitle' }, T('Lair: {0}', npcName(aliens(n.tip)))), position(p, v => { p[0] = v[0]; p[1] = v[1]; saveLayout(); render(); }),
          h('p', { class: 'small muted' }, T('Aliens of this type spawn only in their lairs (in a free one if there are several).')),
          btn(T('Delete the lair'), () => { layout.lairs[n.tip].splice(n.i, 1); if (!layout.lairs[n.tip].length) delete layout.lairs[n.tip]; f.object = null; saveLayout(); renderMapPanel(); render(); }, 'sm danger', 'trash'));
      }
      fill(panel, h('div', { class: 'stack', style: { gap: '10px' } }, back, ...out));
      return;
    }
    const total = npc.reduce((a, g) => a + g.adet, 0);
    const row = g => { const u = aliens(g.tip);
      return h('div', { class: 'we-spawn' }, npcIcon(u, 34), h('div', { class: 'we-spawn-name' }, h('b', { title: npcName(u) }, npcName(u)),
        h('div', { class: 'small muted' }, u?.aggressive ? T('Hostile') : T('Peaceful'), g.region ? ' · ' + T('in zone') : '', layout.lairs[g.tip] ? ' · ' + T('{0} lairs', layout.lairs[g.tip].length) : ''),
        weNumber(g.adet, v => { g.adet = v; saveNpc(); totalEl.textContent = T('{0} aliens', fmtN(npc.reduce((a, x) => a + x.adet, 0))); render(); }, { max: 300, width: 52 })),
        h('div', { class: 'we-spawn-action' },
          btn('', () => { if (g.region) { f.object = { tur: 'region', tip: g.tip }; } else { g.region = [W / 2 | 0, H / 2 | 0, 2500 * S1 | 0]; f.object = { tur: 'region', tip: g.tip }; saveNpc(); } renderMapPanel(); render(); },
            'sm ghost icon' + (g.region ? ' on' : ''), 'target', { title: g.region ? T('Select the zone') : T('Add spawn zone') }),
          btn('', () => { npc.splice(npc.indexOf(g), 1); saveNpc(); renderMapPanel(); render(); }, 'sm ghost icon', 'x', { title: T('Remove from list') })));
    };
    const totalEl = h('span', { class: 'badge info' }, T('{0} aliens', fmtN(total)));
    const std = hm.standard;
    fill(panel, h('div', { class: 'stack', style: { gap: '10px' } },
      h('div', { class: 'row between' }, h('div', { class: 'we-subtitle', style: { margin: 0 } }, T('Spawning aliens')), totalEl),
      npc.length ? h('div', { class: 'stack', style: { gap: '6px' } }, npc.map(row)) : h('div', { class: 'small muted' }, T('No aliens spawn on this map.')),
      btn(T('Add alien'), async () => { const u = await pickAlien(T('Add an alien to the map')); if (!u) return;
        const v = npc.find(g => g.tip === u.tip); if (v) v.adet += 5; else npc.push({ tip: u.tip, adet: 10 }); saveNpc(); renderMapPanel(); render(); }, 'sm primary', 'plus'),
      h('div', { class: 'we-subtitle' }, T('Bonus boxes')),
      h('div', { class: 'we-field-row' }, art('source_kredi', 'we-reward-icon'), weNumber(hm.bonus_boxes, v => { hm.bonus_boxes = v; wePatch('npc.json', jp('haritalar', hm.id, 'bonus_boxes'), v); markSelected(); }, { max: 300, width: 60 }),
        weStd(std.bonus_boxes, hm.bonus_boxes, () => { hm.bonus_boxes = std.bonus_boxes; wePatch('npc.json', jp('haritalar', hm.id, 'bonus_boxes'), std.bonus_boxes); renderMapPanel(); })),
      h('p', { class: 'small muted' }, T('Quantities are multiplied by the alien count and box abundance multipliers in Game Settings.')),
      oreBlock(hm, markSelected),
      (hm.changed.npc || hm.changed.layout || hm.changed.bonus_boxes || hm.cevher.ozel) ? btn(T('Reset the map to standard'), async () => {
        if (!await confirmBox(T('Reset {0} to standard?', hm.ad), T('The spawn list, zones, lairs, safe zones, portal locations and ores return to standard.'), { ok: T('Reset to standard'), danger: true })) return;
        for (const [d, y] of [['npc.json', jp('haritalar', hm.id, 'npc')], ['npc.json', jp('haritalar', hm.id, 'bonus_boxes')], ['map_layout.json', jp('haritalar', hm.id)], ['items.json', hm.cevher.route]]) await weRevert(d, y);
        weRenderSection(); }, 'sm ghost', 'undo') : null));
  };
  const position = (v, cb) => h('div', { class: 'we-field-row' }, h('label', null, T('Position')), weNumber(v[0], x => cb([x, v[1]]), { max: W, step: 100, width: 76 }),
    weNumber(v[1], y => cb([v[0], y]), { max: H, step: 100, width: 76 }));
  renderMapPanel();
}
function popMenuAt(x, y, items) {
  const a = h('span', { style: { position: 'fixed', left: x + 'px', top: y + 'px', width: '1px', height: '1px' } }); document.body.append(a);
  popMenu(a, items); setTimeout(() => a.remove(), 0);
}

// ================================================================== GÖREVLER
const QU_KIND = { 6: ['alien', N('Kill'), 'npc'], 27: ['alien', N('Kill (total)'), 'npc'], 67: ['box', N('Collect'), 'esya'], 34: ['map', N('Go to map'), 'harita'],
  52: ['cart', N('Sell ore'), 'cevher'], 55: ['gift', N('Collect bonus boxes'), null], 51: ['box', N('Collect cargo boxes'), null], 28: ['users', N('Defeat a player'), null],
  2: ['clock', N('Time limit'), 'sure'], 63: ['clock', N('Real-time duration'), 'sure'], 3: ['clock', N('Stay on the map'), 'sure'], 62: ['flag', N('Return to the quest giver'), null],
  53: ['star', N('Reach a level'), null], 35: ['x', N('Die'), null], 42: ['link', N('Use a portal'), null], 80: ['ring', N('Complete a Galaxy Gate'), null],
  13: ['zap', N('Travel distance'), null], 7: ['zap', N('Deal damage'), null], 9: ['shield', N('Take damage'), null] };
const QU_FILTER = [['hepsi', N('All')], ['main', N('Main quests')], ['tekrar', N('Daily and weekly')], ['etkinlik', N('Event')], ['changed', N('Modified')], ['yeni', N('New')], ['off', N('Off')]];
const ORE_OLD = { 1: 'resource_ore_prometium', 2: 'resource_ore_endurium', 3: 'resource_ore_terbium', 4: 'resource_ore_xenomit', 11: 'resource_ore_prometid',
  12: 'resource_ore_duranium', 13: 'resource_ore_promerium', 14: 'resource_ore_seprom', 15: 'resource_ore_palladium', 42: 'resource_ore_osmium' };

// görev eşleşmesindeki harita: "@1-1" -> 1-1; "@own X-3" -> kendi X-3 (firmaya göre çözülür)
function mapLabel(x) {
  x = String(x).replace(/^@/, '');
  const m = x.match(/^(own|enemy|any) (.+)$/);
  return m ? T({ own: N('Own {0}'), enemy: N('Enemy {0}'), any: N('Any {0}') }[m[1]], m[2]) : x;
}
// koşulun hedefi (ne): uzaylı, eşya, cevher, harita adları
function conditionTarget(c) {
  const t = QU_KIND[c.tur], es = c.matches || [];
  if (!t) return '';
  if (t[2] === 'npc') return es.map(k => npcName((DE.alien || []).find(u => String(u.npc_kimlik) === String(k))) || k).join(', ') || T('alien');
  if (t[2] === 'esya') return es.map(itemName).join(', ');
  if (t[2] === 'cevher') return es.map(k => ORE_OLD[k] ? itemName(ORE_OLD[k]) : k).join(', ');
  if (t[2] === 'harita') return es.map(mapLabel).join(', ');
  return '';
}
function conditionText(c) {
  const t = QU_KIND[c.tur];
  if (!t) return T('Custom condition (type {0})', c.tur);
  if (t[2] === 'harita') return conditionTarget(c);
  const target = t[2] === 'sure' ? fmtDur(c.hedef / 1000) : fmtN(c.hedef), ne = conditionTarget(c);
  return ne ? T('{0} {1}', target, ne) : target;
}

async function weQuests(area, b) {
  await alienList();
  const r = await act(() => api('/api/dunya/section?bolum=quests&world=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'quests') return;
  const f = DE.sec.quests || (DE.sec.quests = { q: '', filter_by: 'main', selected: null, cap: 150 });
  const entries = h('div', { class: 'we-quest-list' }), detail = h('div', { class: 'we-detail' });
  const eligible = g => ({ hepsi: true, main: !g.pool && !g.etkinlik && g.kinds.includes(2), tekrar: g.pool || g.kinds.some(t => t === 3 || t === 6),
    etkinlik: g.etkinlik || g.kinds.includes(5), changed: g.changed, yeni: g.yeni, off: g.off })[f.filter_by];
  const render = () => {
    const s = f.q.trim().toLowerCase();
    const l = r.quests.filter(g => eligible(g) && (!s || g.ad.toLowerCase().includes(s) || String(g.id) === s));
    fill(entries, ...l.slice(0, f.cap).map(g => h('button', { type: 'button', class: 'we-quest' + (f.selected === g.id ? ' on' : '') + (g.changed ? ' degisti' : '') + (g.off ? ' kapali' : ''),
      onclick: () => { f.selected = g.id; render(); } }, h('span', { class: 'we-lv' }, g.seviye || '—'),
      h('div', { class: 'we-quest-name' }, h('b', null, g.ad), h('div', { class: 'small muted ellipsis' }, g.conditions.slice(0, 3).map(c => (QU_KIND[c.tur] ? T(QU_KIND[c.tur][1]) : '?') + ' ' + conditionText(c)).join(' · '))),
      h('div', { class: 'we-quest-reward' }, g.rewards.slice(0, 3).map(([l]) => gameIcon(l, 22, null, 'gift'))),
      g.yeni ? badge(T('New'), 'orange') : g.off ? badge(T('Off'), '') : null)),
      l.length > f.cap ? h('button', { type: 'button', class: 'btn sm we-more', onclick: () => { f.cap += 300; render(); } }, T('{0} more quests', fmtN(l.length - f.cap))) : null,
      !l.length ? h('div', { class: 'empty small muted' }, T('No matching quests.')) : null);
    if (!f.selected && l[0]) f.selected = l[0].id;
    if (f.selected) questDetail(f.selected, detail, g2 => { Object.assign(r.quests.find(x => x.id === g2.id) || {}, g2); render(); });
    else fill(detail, h('div', { class: 'empty muted' }, T('Pick a quest from the left.')));
  };
  const seg = h('div', { class: 'seg' }, QU_FILTER.map(([k, name]) => h('button', { class: f.filter_by === k ? 'on info' : '', onclick: () => { f.filter_by = k; f.selected = null; weRenderSection(); } }, T(name))));
  fill(area, h('div', { class: 'card' }, weTitle(b, h('input', { class: 'input', style: { width: '200px' }, placeholder: T('Search quests…'), value: f.q, oninput: e => { f.q = e.target.value; render(); } }),
    btn(T('New quest'), () => newQuest(), 'primary', 'plus')), h('div', { style: { margin: '12px 0' } }, seg), h('div', { class: 'we-two-col wide' }, entries, detail)));
  render();
}

async function questDetail(qid, box, updated) {
  if (box.dataset.q !== String(qid)) fill(box, h('div', { class: 'empty' }, h('div', { class: 'spin', style: { margin: '30px auto' } })));
  box.dataset.q = qid;
  const g = await act(() => api('/api/dunya/gorev?world=' + encodeURIComponent(DE.did) + '&id=' + qid)); if (!g || box.dataset.q !== String(qid)) return;
  const std = g.standard;
  const save = async (changes, regenerate = true) => {
    weSaveStatus('kaydediliyor');
    const x = await act(() => api('/api/dunya/gorev', { world: DE.did, id: qid, changes }));
    if (!x) return weSaveStatus('hazir');
    const summary = await api('/api/dunya?world=' + encodeURIComponent(DE.did)).catch(() => null); if (summary) { DE.summary = summary; weMenuCount(); weWarning(); }
    weSaveStatus('kaydedildi'); updated({ id: x.id, rewards: x.rewards, seviye: x.seviye, conditions: x.conditions.map(c => ({ tur: c.tur, hedef: c.hedef, matches: c.matches })), changed: x.changed, off: x.off, ad: x.ad });
    if (regenerate) questDetail(qid, box, updated);
  };
  let timer = null;
  const delay = (fn, ms = 500) => { clearTimeout(timer); weSaveStatus('kaydediliyor'); timer = setTimeout(fn, ms); };
  const condition = (c, i) => {
    const t = QU_KIND[c.tur] || ['info', N('Custom condition'), null], kind = t[2], sc = std?.conditions?.[i];
    const subMaps = (c.sub.find(a => a.tur === 77) || {}).matches || [];
    const pickTarget = async () => {
      let es = null;
      if (kind === 'npc') { const u = await pickAlien(T('Which alien?'), { with_id: true }); if (u) es = [String(u.npc_kimlik)]; }
      else if (kind === 'esya') { const l = await pickItem(T('Which item should be collected?')); if (l) es = [l]; }
      else if (kind === 'cevher') { const l = await new Promise(res => popMenu(box.querySelector('.we-condition[data-i="' + i + '"] .de-kosul-hedef'), Object.entries(ORE_OLD).map(([k, loot]) => ({ label: itemName(loot), ic: 'box', fn: () => res([k]) })))); es = l; }
      else if (kind === 'harita') { const l = await pickMap(T('Which map?'), [], { multi: false }); if (l) es = l; }
      if (es) save({ conditions: [{ id: c.id, matches: es }] });
    };
    const mapRestriction = async () => { const l = await pickMap(T('Only on these maps'), subMaps.map(x => String(x).replace(/^@/, ''))); if (l) save({ conditions: [{ id: c.id, harita: l }] }); };
    return h('div', { class: 'we-condition', 'data-i': i }, h('div', { class: 'we-condition-icon' }, icon(t[0])),
      h('div', { class: 'we-condition-body' }, h('div', { class: 'small muted' }, T(t[1])),
        h('div', { class: 'row wrap', style: { gap: '8px' } },
          kind === 'sure' ? h('span', { class: 'we-condition-text' }, fmtDur(c.hedef / 1000)) : c.tur === 34 ? null : weNumber(c.hedef, v => delay(() => save({ conditions: [{ id: c.id, hedef: v }] }, false)), { min: 0, max: 1e7, width: 70 }),
          kind && kind !== 'sure' ? h('button', { type: 'button', class: 'chip link de-kosul-hedef', onclick: pickTarget, title: T('Switch') },
            kind === 'esya' ? gameIcon(c.matches[0], 20, null, 'box') : kind === 'npc' ? npcIcon((DE.alien || []).find(u => String(u.npc_kimlik) === String(c.matches[0])), 20) : icon(t[0]),
            conditionTarget(c) || T('Select'), icon('edit')) : null,
          ['npc', 'esya', null].includes(kind) && c.tur !== 62 ? h('button', { type: 'button', class: 'chip link', onclick: mapRestriction, title: T('Map restriction') }, icon('map'),
            subMaps.length ? subMaps.map(mapLabel).join(', ') : T('On every map')) : null,
          sc && sc.hedef !== c.hedef && kind !== 'sure' ? weStd(sc.hedef, c.hedef, () => save({ conditions: [{ id: c.id, hedef: sc.hedef }] })) : null)));
  };
  const reward = ([l, n], i) => h('div', { class: 'we-reward-chip' }, gameIcon(l, 36, null, 'gift'), h('div', { class: 'we-reward-chip-name' }, h('div', { class: 'small ellipsis', title: l }, itemName(l)),
    weNumber(n, v => { g.rewards[i][1] = Math.max(1, v); delay(() => save({ rewards: g.rewards }, false)); }, { min: 1, max: 1e9, width: 84 })),
    btn('', () => { g.rewards.splice(i, 1); save({ rewards: g.rewards }); }, 'sm ghost icon', 'x', { title: T('Remove reward') }));
  const fast = [['currency_credits', 10000], ['currency_uridium', 500], ['currency_experience', 5000], ['currency_honour', 100]];
  fill(box, h('div', { class: 'stack', style: { gap: '14px' } },
    h('div', { class: 'we-detail-head' }, h('div', { class: 'we-quest-badge' }, icon('target')), h('div', { style: { flex: 1, minWidth: 0 } },
      g.yeni ? h('input', { class: 'input we-name-input', value: g.ad, maxlength: 60, onchange: e => save({ ad: e.target.value }) }) : h('div', { class: 'de-h3' }, g.ad),
      h('div', { class: 'small muted' }, T('Quest {0}', g.id), g.yeni ? ' · ' + T('Belongs to this world') : '', g.changed && !g.yeni ? ' · ' + T('modified') : ''))),
    h('div', { class: 'we-subtitle' }, T('In-game text')),
    field(T('Title'), h('input', { class: 'input', value: g.baslik, maxlength: 80, placeholder: g.yeni ? T('No title') : T("The game's own title"),
      onchange: e => save({ baslik: e.target.value }) })),
    field(T('Description'), h('textarea', { class: 'input', rows: 3, maxlength: 600, placeholder: T("The game's own description"), onchange: e => save({ aciklama: e.target.value }) }, g.aciklama)),
    h('div', { class: 'small dim' }, T("If you leave it empty, the game's own text is shown. The title and description are shown in the game by the OpenOrbit plugin (BepInEx).")),
    h('div', { class: 'we-field-row' }, h('label', null, T('Required level')), weNumber(g.seviye, v => delay(() => save({ seviye: v }, false)), { min: 0, max: 40, width: 56 }),
      std ? weStd(std.seviye, g.seviye, () => save({ seviye: std.seviye })) : null),
    h('div', { class: 'we-field-row' }, h('label', null, T('Quest is listed')), h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: !g.off, onchange: e => save({ off: !e.target.checked }) }), h('span')),
      h('span', { class: 'small muted' }, g.off ? T('Off: not shown at the quest giver (can still be finished if already in progress).') : T('On: any pilot who meets the conditions can take it.'))),
    h('div', { class: 'we-subtitle' }, T('Objectives')),
    g.conditions.length ? h('div', { class: 'stack', style: { gap: '8px' } }, g.conditions.map(condition)) : h('div', { class: 'small muted' }, T('This quest has no objectives.')),
    h('div', { class: 'we-subtitle' }, T('Rewards')),
    h('div', { class: 'we-rewards' }, g.rewards.map(reward),
      h('button', { type: 'button', class: 'we-reward-add', onclick: async () => { const l = await pickItem(T('Add reward')); if (!l) return; g.rewards.push([l, l.startsWith('currency_') ? 1000 : 1]); save({ rewards: g.rewards }); } }, icon('plus'), T('Add reward'))),
    h('div', { class: 'chips' }, fast.map(([l, n]) => h('button', { type: 'button', class: 'chip link', onclick: () => { const v = g.rewards.find(o => o[0] === l); if (v) v[1] += n; else g.rewards.push([l, n]); save({ rewards: g.rewards }); } },
      icon('plus'), fmtN(n) + ' ' + itemName(l)))),
    std && JSON.stringify(std.rewards) !== JSON.stringify(g.rewards) ? h('div', null, weStd(std.rewards, g.rewards, () => save({ rewards: std.rewards }), o => T('{0} rewards', o.length))) : null,
    h('div', { class: 'we-subtitle' }, T('Prerequisites')),
    h('div', { class: 'chips' }, g.previous.map(x => h('span', { class: 'chip' }, icon('target'), g.adlar[x] || x,
      h('button', { type: 'button', class: 'we-chip-x', onclick: () => save({ previous: g.previous.filter(y => y !== x) }) }, icon('x')))),
      h('button', { type: 'button', class: 'chip link', onclick: async () => { const q = await pickQuest(); if (q) save({ previous: [...g.previous, q.id] }); } }, icon('plus'), T('Add prerequisite'))),
    h('div', { class: 'row wrap', style: { gap: '8px', marginTop: '6px' } },
      g.changed && !g.yeni ? btn(T('Reset to standard'), async () => { if (await weRevert(_quFile(g), jp('quests', g.id))) { updated({ id: g.id, changed: false }); questDetail(qid, box, updated); } }, 'sm ghost', 'undo') : null,
      g.yeni ? btn(T('Delete quest'), async () => {
        if (!await confirmBox(T('Delete the quest?'), T('The quests you added to this world will be deleted.'), { ok: T('Delete'), danger: true })) return;
        const r = await wePatch('quest_extras.json', jp('quests', g.id), { $delete: true }, { ms: 0 }); if (r) { DE.sec.quests.selected = null; weRenderSection(); } }, 'sm danger', 'trash') : null)));
}
const _quFile = g => g.kaynak === 'main' ? 'quests.json' : 'quest_extras.json';

async function pickQuest() {
  const r = await act(() => api('/api/dunya/section?bolum=quests&world=' + encodeURIComponent(DE.did))); if (!r) return null;
  return new Promise(res => {
    let q = '', done = false;
    const l = h('div', { class: 'we-quest-list short' });
    const render = () => { const s = q.trim().toLowerCase();
      fill(l, ...r.quests.filter(g => !s || g.ad.toLowerCase().includes(s)).slice(0, 120).map(g => h('button', { type: 'button', class: 'we-quest', onclick: () => { done = true; m.close(); res(g); } },
        h('span', { class: 'we-lv' }, g.seviye || '—'), h('div', { class: 'we-quest-name' }, h('b', null, g.ad))))); };
    const m = modal({ title: T('Prerequisite quest'), onclose: () => { if (!done) res(null); }, body: h('div', { class: 'stack', style: { gap: '10px' } },
      h('input', { class: 'input', placeholder: T('Search quests…'), oninput: e => { q = e.target.value; render(); } }), l) });
    render();
  });
}

// yeni görev sihirbazı: 1 hedefler, 2 ödüller, 3 ad ve seviye
const QU_TEMPLATE = [['hunt', 'alien', N('Hunt'), N('Kill aliens')], ['collect', 'box', N('Collect'), N('Collect items or ore')], ['exploring', 'map', N('Explore'), N('Go to a map')],
  ['sell', 'cart', N('Trade'), N('Sell ore')], ['kutu', 'gift', N('Bonus box'), N('Collect bonus boxes')], ['kargo', 'box', N('Cargo'), N('Collect cargo boxes')]];
function newQuest() {
  const g = { ad: '', seviye: 1, targets: [], rewards: [['currency_credits', 10000], ['currency_experience', 2000]] };
  let step = 0;
  const body = h('div'), sub = h('div', { class: 'foot' });
  const m = modal({ title: T('New quest'), wide: true, body: body });
  m.box.append(sub);
  const targetRow = (x, i) => {
    const s = QU_TEMPLATE.find(y => y[0] === x.tur);
    const sec = async () => {
      if (x.tur === 'hunt') { const u = await pickAlien(T('Which alien?'), { with_id: true }); if (u) { x.matches = [String(u.npc_kimlik)]; x.etiket = npcName(u); x.icon = u; } }
      else if (x.tur === 'collect') { const l = await pickItem(T('Which item should be collected?')); if (l) { x.matches = [l]; x.etiket = itemName(l); x.loot = l; } }
      else if (x.tur === 'sell') { const l = await new Promise(res => popMenu(body.querySelector('[data-h="' + i + '"] .de-kosul-hedef'), Object.entries(ORE_OLD).map(([k, loot]) => ({ label: itemName(loot), ic: 'box', fn: () => res([k, loot]) })))); if (l) { x.matches = [l[0]]; x.etiket = itemName(l[1]); x.loot = l[1]; } }
      else if (x.tur === 'exploring') { const l = await pickMap(T('Which map?'), [], { multi: false }); if (l) { x.matches = l; x.etiket = l[0]; } }
      render();
    };
    const selectable = ['hunt', 'collect', 'sell', 'exploring'].includes(x.tur);
    return h('div', { class: 'we-condition', 'data-h': i }, h('div', { class: 'we-condition-icon' }, icon(s[1])), h('div', { class: 'we-condition-body' }, h('div', { class: 'small muted' }, T(s[3])),
      h('div', { class: 'row wrap', style: { gap: '8px' } }, x.tur !== 'exploring' ? weNumber(x.hedef, v => { x.hedef = Math.max(1, v); }, { min: 1, max: 1e7, width: 70 }) : null,
        selectable ? h('button', { type: 'button', class: 'chip link de-kosul-hedef' + (x.matches?.length ? '' : ' bos'), onclick: sec },
          x.loot ? gameIcon(x.loot, 20, null, 'box') : x.icon ? npcIcon(x.icon, 20) : icon(s[1]), x.etiket || T('Select'), icon('edit')) : null,
        x.tur !== 'exploring' ? h('button', { type: 'button', class: 'chip link', onclick: async () => { const l = await pickMap(T('Only on these maps'), x.harita || []); if (l) { x.harita = l; render(); } } },
          icon('map'), x.harita?.length ? x.harita.join(', ') : T('On every map')) : null)),
      btn('', () => { g.targets.splice(i, 1); render(); }, 'sm ghost icon', 'x'));
  };
  const render = () => {
    const steps = h('div', { class: 'we-steps' }, [N('Objectives'), N('Rewards'), N('Name and level')].map((a, i) => h('div', { class: 'we-step' + (i === step ? ' on' : i < step ? ' bitti' : '') }, h('b', null, i + 1), T(a))));
    let iconEl;
    if (step === 0) iconEl = [h('p', { class: 'desc' }, T('What should the pilot do? Add one or more objectives; the quest ends when all are complete.')),
      h('div', { class: 'we-templates' }, QU_TEMPLATE.map(([k, icon2, name, is_open]) => h('button', { type: 'button', class: 'we-template', onclick: () => {
        g.targets.push({ tur: k, hedef: k === 'exploring' ? 1 : k === 'hunt' ? 20 : k === 'sell' ? 100 : 10, matches: [] }); render();
        if (['hunt', 'collect', 'exploring'].includes(k)) setTimeout(() => body.querySelector('[data-h="' + (g.targets.length - 1) + '"] .de-kosul-hedef')?.click(), 50); } },
        icon(icon2), h('b', null, T(name)), h('span', { class: 'small muted' }, T(is_open))))),
      g.targets.length ? h('div', { class: 'stack', style: { gap: '8px', marginTop: '14px' } }, g.targets.map(targetRow)) : null];
    else if (step === 1) iconEl = [h('p', { class: 'desc' }, T('What does the pilot earn when the quest is done?')),
      h('div', { class: 'we-rewards' }, g.rewards.map(([l, n], i) => h('div', { class: 'we-reward-chip' }, gameIcon(l, 36, null, 'gift'), h('div', { class: 'we-reward-chip-name' }, h('div', { class: 'small ellipsis' }, itemName(l)),
        weNumber(n, v => { g.rewards[i][1] = Math.max(1, v); }, { min: 1, max: 1e9, width: 84 })), btn('', () => { g.rewards.splice(i, 1); render(); }, 'sm ghost icon', 'x'))),
        h('button', { type: 'button', class: 'we-reward-add', onclick: async () => { const l = await pickItem(T('Add reward')); if (l) { g.rewards.push([l, l.startsWith('currency_') ? 1000 : 1]); render(); } } }, icon('plus'), T('Add reward')))];
    else iconEl = [field(T('Quest name'), h('input', { class: 'input', value: g.ad, maxlength: 60, placeholder: T('e.g. Streuner Hunt'), oninput: e => { g.ad = e.target.value; } })),
      h('div', { class: 'we-field-row' }, h('label', null, T('Required level')), weNumber(g.seviye, v => { g.seviye = v; }, { min: 1, max: 40, width: 56 })),
      h('div', { class: 'small muted' }, T("The quest is listed at your company's quest giver (station); the name becomes the quest's title in the game."))];
    fill(body, h('div', { class: 'stack', style: { gap: '12px' } }, steps, ...iconEl));
    const missing = step === 0 && (!g.targets.length || g.targets.some(x => ['hunt', 'collect', 'sell', 'exploring'].includes(x.tur) && !x.matches?.length));
    fill(sub, btn(step ? T('Back') : T('Cancel'), () => { if (step) { step--; render(); } else m.close(); }, 'ghost', step ? 'arrowL' : null),
      step < 2 ? btn(T('Next'), () => { step++; render(); }, 'primary', 'arrowR', { disabled: missing, title: missing ? T('Choose what to do for each objective.') : null })
        : btn(T('Create quest'), async () => {
          const x = await act(() => api('/api/dunya/new_quest', { world: DE.did, ad: g.ad, seviye: g.seviye, targets: g.targets.map(y => ({ tur: y.tur, hedef: y.hedef, matches: y.matches, harita: y.harita })), rewards: g.rewards }), T('Quest created.'));
          if (!x) return;
          m.close(); DE.sec.quests = { q: '', filter_by: 'yeni', selected: x.id, cap: 150 };
          const summary = await api('/api/dunya?world=' + encodeURIComponent(DE.did)).catch(() => null); if (summary) { DE.summary = summary; weMenuCount(); weWarning(); }
          weRenderSection();
        }, 'primary', 'check'));
  };
  render();
}

// ================================================================== MAĞAZA
async function weShop(area, b) {
  const r = await act(() => api('/api/dunya/section?bolum=shop&world=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'shop') return;
  const cats = Object.keys(r.categories);
  if (!cats.length) return fill(area, h('div', { class: 'card' }, weTitle(b), h('div', { class: 'empty muted' }, T('Shop catalog not found (data/yanitlar.json).'))));
  const f = DE.sec.shop || (DE.sec.shop = { multiplier: cats[0], q: '', filter_by: 'hepsi' });
  if (!cats.includes(f.multiplier)) f.multiplier = cats[0];
  const grid = h('div', { class: 'shop-grid we-shop' });
  const priceText = (u, p) => fmtN(u) + (p === 'C' ? ' C.' : ' U.');
  const render = () => {
    const s = f.q.trim().toLowerCase();
    const l = r.categories[f.multiplier].filter(it => (f.filter_by === 'hepsi' || (f.filter_by === 'changed' ? it.world : it.world?.on_sale === false)) && (!s || itemName(it.lootId).toLowerCase().includes(s) || it.lootId.includes(s)));
    fill(grid, ...l.map(it => { const d = it.world || {}, closed = d.on_sale === false, changed = d.price != null;
      return h('button', { type: 'button', class: 'shop-card we-shop-card' + (closed ? ' kapali' : '') + (it.world ? ' degisti' : ''), onclick: () => editProduct(it, render) },
        gameIcon(it.lootId, 64, null, 'cart'), h('div', { class: 'shop-name', title: it.lootId }, itemName(it.lootId)),
        h('div', { class: 'shop-price ' + ((changed ? d.currency : it.currency) === 'C' ? 'cred' : 'uri') }, closed ? T('Not for sale') : priceText(changed ? d.price : it.price, changed ? d.currency : it.currency)),
        changed && !closed ? h('div', { class: 'small dim we-strikethrough' }, priceText(it.price, it.currency)) : null); }),
      !l.length ? h('div', { class: 'empty small muted' }, T('No products.')) : null);
  };
  const CAT = typeof SHP_CATEGORY !== 'undefined' ? SHP_CATEGORY : {};
  fill(area, h('div', { class: 'stack' }, h('div', { class: 'card' },
    weTitle(b, h('input', { class: 'input', style: { width: '180px' }, placeholder: T('Search…'), value: f.q, oninput: e => { f.q = e.target.value; render(); } }),
      btn(T('Bulk price'), () => bulkPrice(r.categories[f.multiplier], render), 'sm', 'sliders')),
    h('div', { class: 'row wrap', style: { gap: '10px', marginTop: '12px' } },
      h('div', { class: 'seg' }, cats.map(c => h('button', { class: c === f.multiplier ? 'on info' : '', onclick: () => { f.multiplier = c; weRenderSection(); } }, CAT[c] ? T(CAT[c]) : c,
        r.categories[c].some(it => it.world) ? h('span', { class: 'we-dot' }) : null))),
      h('div', { class: 'seg' }, [['hepsi', N('All')], ['changed', N('Modified')], ['off', N('Removed from sale')]].map(([k, name]) =>
        h('button', { class: f.filter_by === k ? 'on info' : '', onclick: () => { f.filter_by = k; weRenderSection(); } }, T(name))))),
    h('p', { class: 'small muted', style: { margin: '10px 0 0' } }, T('The shop price multiplier in Game Settings is applied on top of these prices. Drones and leveled P.E.T. products follow their own pricing rule.'))),
    grid));
  render();
}

function editProduct(it, refresh) {
  const d = Object.assign({}, it.world || {}), fixed = it.fixed;
  let price = d.price ?? it.price, currency = d.currency || it.currency, on_sale = d.on_sale !== false;
  const save = async () => {
    const value = {}; if (!fixed && (price !== it.price || currency !== it.currency)) { value.price = price; value.currency = currency; } if (!on_sale) value.on_sale = false;
    const empty = !Object.keys(value).length;
    const r = empty ? await weRevert('shop', jp('products', it.lootId)) : await wePatch('shop', jp('products', it.lootId), value, { ms: 0 });
    if (r) { it.world = empty ? null : value; refresh(); m.close(); }
  };
  const seg = h('div', { class: 'seg' }, [['C', N('Credits')], ['U', N('Uridium')]].map(([k, name]) => h('button', { class: currency === k ? 'on info' : '', disabled: fixed,
    onclick: e => { currency = k; seg.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === e.currentTarget)); seg.querySelectorAll('button').forEach(x => x.classList.toggle('info', x === e.currentTarget)); } }, T(name))));
  const m = modal({ title: itemName(it.lootId), sub: it.lootId, body: h('div', { class: 'stack', style: { gap: '14px' } },
    h('div', { class: 'row', style: { gap: '14px' } }, gameIcon(it.lootId, 72, null, 'cart'), h('div', { class: 'small muted' }, T('Standard price: {0}', fmtN(it.price) + (it.currency === 'C' ? ' C.' : ' U.')))),
    fixed ? h('div', { class: 'alert info' }, icon('info'), h('div', null, T("This product's price is calculated by its own rule (drone count, P.E.T. level); you can only remove it from sale."))) : null,
    h('div', { class: 'we-field-row' }, h('label', null, T('Price')), weNumber(price, v => { price = v; }, { min: 0, max: 1e10, step: currency === 'C' ? 1000 : 10, width: 130 }), seg),
    h('div', { class: 'we-field-row' }, h('label', null, T('For sale')), h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: on_sale, onchange: e => { on_sale = e.target.checked; } }), h('span')),
      h('span', { class: 'small muted' }, T("If off, it doesn't appear in the shop and can't be bought.")))),
    foot: [it.world ? btn(T('Reset to standard'), async () => { if (await weRevert('shop', jp('products', it.lootId))) { it.world = null; refresh(); m.close(); } }, 'ghost', 'undo') : null,
      h('span', { class: 'spacer' }), btn(T('Cancel'), () => m.close(), 'ghost'), btn(T('Save'), save, 'primary', 'check')] });
}

function bulkPrice(products, refresh) {
  let percent = 100;
  const m = modal({ title: T('Bulk price'), sub: T('Sets the price of products in this category to a percentage of the standard price.'), body: h('div', { class: 'stack', style: { gap: '12px' } },
    h('div', { class: 'we-field-row' }, h('label', null, T('Standard price')), weNumber(percent, v => { percent = v; }, { min: 0, max: 1000, step: 10, width: 70 }), h('span', null, '%')),
    h('div', { class: 'chips' }, [25, 50, 75, 150, 200].map(p => h('button', { type: 'button', class: 'chip link', onclick: e => { percent = p; e.currentTarget.closest('.body').querySelector('input').value = p; } }, '%' + p)))),
    foot: [btn(T('Cancel'), () => m.close(), 'ghost'), btn(T('Apply'), async () => {
      m.close(); const l = products.filter(it => !it.fixed && it.world?.on_sale !== false);
      for (const it of l) {
        const value = { price: Math.round(it.price * percent / 100), currency: it.currency };
        const r = percent === 100 ? await weRevert('shop', jp('products', it.lootId)) : await act(() => api('/api/dunya/yama', { world: DE.did, dosya: 'shop', route: jp('products', it.lootId), value }));
        if (r) { it.world = percent === 100 ? null : value; DE.summary = Object.assign(DE.summary, r); }
      }
      weMenuCount(); weWarning(); weSaveStatus('kaydedildi'); toast(T('Price of {0} products updated.', l.length), 'ok'); refresh();
    }, 'primary', 'check')] });
}

// ================================================================== AÇIK ARTIRMA
const WE_AUCTION_KIND = [['hour', N('Hourly')], ['day', N('Log')], ['week', N('Weekly')]];
async function weAuction(area, b) {
  const r = await act(() => api('/api/dunya/section?bolum=auction&world=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'auction') return;
  const lots = r.lotlar;
  const save = () => wePatch('social.json', jp('auction', 'lotlar'), lots.map(l => [l.loot, l.grup, l.tur, l.adet, l.instant, l.price]));
  const groupOf = loot => loot.startsWith('ammunition_laser') ? 'battery' : loot.startsWith('ammunition_rocket') ? 'rocket' : loot.startsWith('ship_') ? 'ship'
    : loot.startsWith('drone_') ? 'drone' : loot.startsWith('equipment_') ? 'equipment' : loot.startsWith('booster_') ? 'booster' : 'other';
  const f = DE.sec.auction || (DE.sec.auction = { tur: 'hour', q: '' });
  const columns = h('div', { class: 'stack', style: { gap: '10px' } });
  const render = () => {
    const s = f.q.trim().toLowerCase(), ls = lots.filter(l => l.tur === f.tur && (!s || itemName(l.loot).toLowerCase().includes(s)));
    const tab = h('div', { class: 'seg' }, WE_AUCTION_KIND.map(([kind, name]) => h('button', { class: f.tur === kind ? 'on info' : '', onclick: () => { f.tur = kind; render(); } },
      T(name), ' ', h('span', { class: 'we-count mavi' }, lots.filter(l => l.tur === kind).length))));
    const add = btn(T('Add lot'), async () => {
      const loot = await pickItem(T('Add lot: {0}', T(WE_AUCTION_KIND.find(x => x[0] === f.tur)[1]))); if (!loot) return;
      if (lots.some(l => l.tur === f.tur && l.loot === loot)) return toast(T('This item is already in this period.'), 'info');
      lots.push({ loot, grup: groupOf(loot), tur: f.tur, adet: 1, instant: true, price: 1000 }); save(); render(); }, 'sm primary', 'plus');
    fill(columns, h('div', { class: 'row wrap', style: { gap: '10px' } }, tab,
      h('input', { class: 'input', style: { width: '180px' }, placeholder: T('Search…'), value: f.q, oninput: e => { f.q = e.target.value; render(); setTimeout(() => columns.querySelector('input.input')?.focus(), 0); } }),
      h('span', { class: 'spacer' }), add),
      h('div', { class: 'we-lot-head small muted' }, h('span'), h('span', null, T('Item')), h('span', null, T('Quantity')), h('span', null, T('Buy now')), h('span', null, T('Price (U.)')), h('span')),
      ls.length ? h('div', { class: 'we-lots' }, ls.map(l => h('div', { class: 'we-lot' }, gameIcon(l.loot, 34, null, 'gavel'),
        h('div', { class: 'we-lot-name', title: l.loot }, itemName(l.loot)),
        weNumber(l.adet, v => { l.adet = Math.max(1, v); save(); }, { min: 1, max: 1e7, width: 76 }),
        h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: l.instant, onchange: e => { l.instant = e.target.checked; save(); render(); } }), h('span')),
        l.instant ? weNumber(l.price, v => { l.price = v; save(); }, { min: 0, max: 1e9, step: 100, width: 86 }) : h('span', { class: 'small dim' }, T('bid only')),
        btn('', () => { lots.splice(lots.indexOf(l), 1); save(); render(); }, 'sm ghost icon', 'x', { title: T('Remove lot') }))))
        : h('div', { class: 'empty small muted' }, T('No lots in this period.')));
  };
  fill(area, h('div', { class: 'card' }, weTitle(b, r.changed ? btn(T('Reset to standard'), async () => {
    if (await confirmBox(T('Reset the auction to standard?'), T("The lot list returns to the game's own {0} lots.", r.default_count), { ok: T('Reset to standard'), danger: true }))
      if (await weRevert('social.json', jp('auction', 'lotlar'))) weRenderSection(); }, 'sm ghost', 'undo') : null),
    h('p', { class: 'small muted', style: { margin: '10px 0 14px' } }, T('Bids are placed with credits; buy-now with uridium. Lots refresh every period (at minute 30 of every hour, 22:30 UTC, Sunday 22:30 UTC).')),
    columns));
  render();
}

// ---- harita paneli: cevherler (items.json cevherler.haritalar: haritanın adıyla, yoksa harita sınıfınınki)
function oreBlock(hm, markSelected) {
  const c = hm.cevher, count = Object.assign({}, c.adet), box = h('div', { class: 'stack', style: { gap: '6px' } });
  const save = () => { c.ozel = true; wePatch('items.json', c.route, count); markSelected(); render(); };
  const render = () => {
    const var_ = Object.keys(c.kinds).filter(t => count[t] > 0);
    fill(box, 
      h('div', { class: 'small muted' }, c.ozel ? T('Specific to this map.') : T('Values of class {0} (all maps in the same class). Changing them makes them specific to this map only.', c.class_name)),
      ...var_.map(t => h('div', { class: 'we-ore' }, gameIcon(c.kinds[t], 24, null, 'box'), h('span', { class: 'small ellipsis' }, itemName(c.kinds[t])),
        weNumber(count[t], v => { count[t] = v; save(); }, { max: 1000, step: 5, width: 52 }))),
      !var_.length ? h('div', { class: 'small dim' }, T('There is no ore on this map.')) : null,
      h('div', { class: 'row wrap', style: { gap: '6px' } },
        btn(T('Add ore'), ev => popMenu(ev.currentTarget, Object.keys(c.kinds).filter(t => !(count[t] > 0)).map(t => ({ label: itemName(c.kinds[t]), ic: 'plus',
          fn: () => { count[t] = 20; save(); } }))), 'sm', 'plus'),
        c.ozel ? btn(T('Reset to the class value'), async () => { if (await weRevert('items.json', c.route)) weRenderSection(); }, 'sm ghost', 'undo') : null),
      h('div', { class: 'we-field-row' }, h('label', null, T('Respawn')), weNumber(c.renew_sec[0], v => { c.renew_sec[0] = v; regeneration(); }, { min: 1, max: 3600, width: 46 }),
        h('span', { class: 'small muted' }, '–'), weNumber(c.renew_sec[1], v => { c.renew_sec[1] = v; regeneration(); }, { min: 1, max: 3600, width: 46 }), h('span', { class: 'small muted' }, T('s'))),
      h('div', { class: 'small dim' }, T('Respawn time applies on all maps.')));
  };
  const regeneration = () => wePatch('items.json', jp('ores', 'respawn_sec'), [Math.min(...c.renew_sec), Math.max(...c.renew_sec)]);
  render();
  return h('div', { class: 'stack', style: { gap: '8px' } }, h('div', { class: 'we-subtitle' }, T('Ores')), box);
}

// ================================================================== KUTULAR VE GANİMET
const MAP_CLASS_NAME = { 'X-1..X-8': N('Company maps (X-1 – X-8)'), 'X-2..X-8': N('Company maps (X-2 – X-8)'), '4-X': N('Battle maps (4-X)'),
  '5-X': N('Pirate maps (5-1 – 5-3)'), '5-4': '5-4', 'BL': 'Black Light' };
// kutunun oyundaki görseli (atlas), yoksa anahtarının simgesi
const BOX_SPRITE = { PIRATE_BOOTY: 'booty_box_green', PIRATE_BOOTY_GOLD: 'booty_box_gold', PIRATE_BOOTY_RED: 'booty_box_red', PIRATE_BOOTY_BLUE: 'booty_box_blue',
  PIRATE_BOOTY_SILVER: 'booty_box_silver', BLACK_BOOTY_BOX: 'blackBooty_100x100', MASQUE_BOOTY_BOX: 'masqueBooty_100x100' };
const boxIcon = (k, size) => GI.index?.sprite[BOX_SPRITE[k.tur]] ? sprite(BOX_SPRITE[k.tur], size) : gameIcon(k.anahtar, size, null, 'gift');

async function weBoxes(area, b) {
  const r = await act(() => api('/api/dunya/section?bolum=boxes&world=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'boxes') return;
  const f = DE.sec.box_kinds || (DE.sec.box_kinds = { selected: 'bonus' });
  const entries = h('div', { class: 'we-npc-list' }), detail = h('div', { class: 'we-detail' });
  const items = [{ id: 'bonus', ad: T('Bonus box'), sub: T('On all maps (except 4-X)'), icon: 'bonus_box', changed: r.bonus_changed },
    { id: 'bonus_4x', ad: T('Rich bonus box'), sub: T('On battle maps (4-X)'), icon: 'bonus_box_green', changed: r.bonus_4x_changed },
    ...r.boxes.map(k => ({ id: k.tur, ad: k.ad, sub: !k.spawns ? T('Does not spawn on maps') : k.calendar ? T('During the event') : T('Always'), box: k, changed: k.changed }))];
  const render = () => {
    fill(entries, ...items.map(o => h('button', { type: 'button', class: 'de-npc' + (f.selected === o.id ? ' on' : '') + (o.changed ? ' degisti' : ''),
      onclick: () => { f.selected = o.id; render(); } }, o.kutu ? boxIcon(o.kutu, 36) : (GI.index?.sprite[o.icon] ? sprite(o.icon, 36) : icon('gift')),
      h('div', { class: 'we-npc-name' }, h('b', null, o.ad), h('div', { class: 'small muted' }, o.sub)))));
    const o = items.find(x => x.id === f.selected) || items[0];
    fill(detail, o.kutu ? boxDetail(o, r) : bonusDetail(o, r));
  };
  fill(area, h('div', { class: 'card' }, weTitle(b), h('div', { class: 'we-two-col narrow-list' }, entries, detail)));
  render();
}

function bonusDetail(o, r) {
  const route = jp(o.id === 'bonus' ? 'bonus_boxes' : 'bonus_box_4x'), rows = r[o.id].map(x => x.slice());
  const box = h('div', { class: 'stack', style: { gap: '6px' } });
  const save = () => { o.changed = true; wePatch('npc.json', route, rows); };
  const render = () => fill(box, ...rows.map((x, i) => h('div', { class: 'we-box-row' }, gameIcon(x[0], 32, null, 'gift'),
    h('div', { class: 'we-box-body' }, h('span', { class: 'we-box-name', title: x[0] }, itemName(x[0])),
      h('div', { class: 'we-box-controls' }, h('span', { class: 'small muted' }, T('Quantity')), weNumber(x[1], v => { x[1] = Math.max(1, v); save(); }, { min: 1, max: 1e7, width: 70 }),
        h('span', { class: 'we-percent' }, '%' + (100 / rows.length).toFixed(1)))),
    btn('', () => { if (rows.length < 2) return toast(T('A bonus box needs at least one reward.'), 'info'); rows.splice(i, 1); save(); render(); }, 'sm ghost icon', 'x'))),
    h('button', { type: 'button', class: 'we-reward-add', onclick: async () => { const l = await pickItem(T('Add reward')); if (!l) return; rows.push([l, l.startsWith('ammunition_') ? 100 : 1]); save(); render(); } },
      icon('plus'), T('Add reward')));
  render();
  return h('div', { class: 'stack', style: { gap: '12px' } },
    h('div', { class: 'we-detail-head' }, GI.index?.sprite[o.icon] ? sprite(o.icon, 56) : icon('gift'), h('div', null, h('div', { class: 'de-h3' }, o.ad), h('div', { class: 'small muted' }, o.sub))),
    h('p', { class: 'small muted', style: { margin: 0 } }, T('When a box is collected, one of the rows drops with equal chance. The number of boxes on the map is in the Maps section.')),
    box,
    o.changed ? btn(T('Reset to standard'), async () => { if (await weRevert('npc.json', route)) weRenderSection(); }, 'sm ghost', 'undo') : null);
}

function boxDetail(o, r) {
  const k = JSON.parse(JSON.stringify(o.kutu)), route = jp('boxes', k.tur);
  const save = () => { o.changed = true; wePatch('boxes.json', route, { adet: k.adet, renew_sec: k.renew_sec, haritalar: k.haritalar, reward: k.reward }); };
  const table = h('div', { class: 'stack', style: { gap: '6px' } });
  const percent = w => { const t = k.reward.reduce((a, x) => a + (+x[2] || 0), 0); return t ? (100 * w / t).toFixed(w * 100 / t < 1 ? 2 : 1) : '0'; };
  const render = () => fill(table, ...k.reward.map((x, i) => {
    const pack = x[0] === 'paket';
    const weight = h('input', { class: 'input num we-weight', type: 'number', min: 0, step: 'any', value: x[2], title: T('Weight'),
      onchange: e => { x[2] = Math.max(0, +e.target.value || 0); save(); render(); } });
    return h('div', { class: 'we-box-row' }, pack ? h('span', { class: 'we-bundle' }, x[1].slice(0, 4).map(([l]) => gameIcon(l, 16, null, 'gift'))) : gameIcon(x[0], 32, null, 'gift'),
      h('div', { class: 'we-box-body' }, h('span', { class: 'we-box-name', title: pack ? x[1].map(([l, n]) => n + ' × ' + l).join('\n') : x[0] }, pack ? T('Bundle ({0} items)', x[1].length) : itemName(x[0])),
        h('div', { class: 'we-box-controls' },
          pack ? null : h('span', { class: 'small muted' }, T('Quantity')),
          pack ? null : Array.isArray(x[1]) ? [weNumber(x[1][0], v => { x[1][0] = Math.max(1, v); save(); }, { min: 1, max: 1e7, width: 52 }), '–',
            weNumber(x[1][1], v => { x[1][1] = Math.max(1, v); save(); }, { min: 1, max: 1e7, width: 52 })]
            : weNumber(x[1], v => { x[1] = Math.max(1, v); save(); }, { min: 1, max: 1e7, width: 70 }),
          h('span', { class: 'small muted' }, T('Weight')), weight, h('span', { class: 'we-percent' }, '%' + percent(+x[2] || 0)))),
      btn('', () => { if (k.reward.length < 2) return toast(T('A box needs at least one reward.'), 'info'); k.reward.splice(i, 1); save(); render(); }, 'sm ghost icon', 'x'));
  }), h('button', { type: 'button', class: 'we-reward-add', onclick: async () => {
    const l = await pickItem(T('Add reward')); if (!l) return; k.reward.push([l, 1, 5]); save(); render(); } }, icon('plus'), T('Add reward')));
  render();
  const classes = h('div', { class: 'chips' });
  const renderClass = () => fill(classes, ...r.classes.map(s => h('button', { type: 'button', class: 'chip link we-class' + (k.haritalar.includes(s) ? ' on' : ''),
    onclick: () => { k.haritalar = k.haritalar.includes(s) ? k.haritalar.filter(x => x !== s) : [...k.haritalar, s]; save(); renderClass(); } },
    k.haritalar.includes(s) ? icon('check') : icon('plus'), MAP_CLASS_NAME[s] ? T(MAP_CLASS_NAME[s]) : s)));
  renderClass();
  return h('div', { class: 'stack', style: { gap: '12px' } },
    h('div', { class: 'we-detail-head' }, boxIcon(k, 56), h('div', null, h('div', { class: 'de-h3' }, k.ad),
      h('div', { class: 'small muted' }, T('To open: {0}', itemName(k.anahtar)), k.calendar ? ' · ' + T('spawns only while the event is running') : ''))),
    h('div', { class: 'we-field-row' }, h('label', null, T('Quantity on map')), weNumber(k.adet, v => { k.adet = v; save(); }, { min: 0, max: 100, width: 56 }),
      h('span', { class: 'small muted' }, T('at the same time on each map'))),
    k.renew_sec ? h('div', { class: 'we-field-row' }, h('label', null, T('Respawn')),
      weNumber(k.renew_sec[0], v => { k.renew_sec[0] = v; save(); }, { min: 10, max: 86400, step: 30, width: 64 }), '–',
      weNumber(k.renew_sec[1], v => { k.renew_sec[1] = v; save(); }, { min: 10, max: 86400, step: 30, width: 64 }), h('span', { class: 'small muted' }, T('s'))) : null,
    h('div', { class: 'we-subtitle' }, T('Spawn maps')), classes,
    h('div', { class: 'we-subtitle' }, T('Reward table')),
    h('p', { class: 'small muted', style: { margin: 0 } }, T('When opened, one row is drawn by its weight: weight / total weight = chance.')),
    table,
    o.changed ? btn(T('Reset to standard'), async () => { if (await weRevert('boxes.json', route)) weRenderSection(); }, 'sm ghost', 'undo') : null);
}

// ================================================================== GALAKSİ KAPILARI
const GATE_REWARD_FIELD = [['ep', N('Experience'), 'source_experience'], ['onur', N('Honor'), 'source_onur'], ['uridyum', N('Uridium'), 'source_uridyum'],
  ['xenomit', N('Xenomit'), 'resource_ore_xenomit'], ['log_disk', N('Log disk'), 'resource_logfile'], ['voucher', N('Coupon'), '']];
const ROMAN = n => ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII', 'XIII', 'XIV', 'XV'][n] || String(n + 1);

async function weGates(area, b) {
  const r = await act(() => api('/api/dunya/section?bolum=kapilar&world=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'kapilar') return;
  const f = DE.sec.kp || (DE.sec.kp = { selected: r.kapilar[0]?.key, on: {} });
  const entries = h('div', { class: 'we-npc-list' }), detail = h('div', { class: 'we-detail' });
  const render = () => {
    fill(entries, ...r.kapilar.map(g => h('button', { type: 'button', class: 'de-npc' + (f.selected === g.key ? ' on' : '') + (g.changed ? ' degisti' : ''),
      onclick: () => { f.selected = g.key; render(); } }, art('ed_kapilar', 'we-gate-icon'),
      h('div', { class: 'we-npc-name' }, h('b', null, g.ad), h('div', { class: 'small muted' }, T('{0} waves · {1} parts', g.waves.length, g.part))))));
    const g = r.kapilar.find(x => x.key === f.selected) || r.kapilar[0];
    fill(detail, gateDetail(g, f));
  };
  fill(area, h('div', { class: 'card' }, weTitle(b), h('div', { class: 'we-two-col narrow-list' }, entries, detail)));
  render();
}

function gateDetail(g, f) {
  const route = jp('kapilar', g.key), std = g.standard;
  const save = () => {
    g.changed = true;
    return wePatch('gates.json', route, { part: g.part, can: g.can, reward: Object.assign({}, g.reward, { ammunition: g.ammunition, chance: g.chance.map(x => ({ adet: x.adet, probability: x.probability })) }),
      waves: g.waves.map(w => ({ alien_spawns: w.alien_spawns.map(a => ({ tur: a.tur, adet: a.adet, hp: a.hp, kalkan: a.kalkan, hasar: a.hasar, hiz: a.hiz })) })) });
  };
  const row = (name, k, opts) => h('div', { class: 'we-field-row' + (std && std[k] !== g[k] ? ' degisti' : '') }, h('label', null, name),
    weNumber(g[k], v => { g[k] = v; save(); }, opts), std ? weStd(std[k], g[k], () => { g[k] = std[k]; save(); weRenderSection(); }) : null);
  const ammo = h('div', { class: 'we-rewards' });
  const renderAmmo = () => fill(ammo, ...Object.entries(g.ammunition).map(([l, n]) => h('div', { class: 'we-reward-chip' }, gameIcon(l, 32, null, 'gift'),
    h('div', { class: 'we-reward-chip-name' }, h('div', { class: 'small ellipsis' }, itemName(l)), weNumber(n, v => { g.ammunition[l] = Math.max(1, v); save(); }, { min: 1, max: 1e8, step: 100, width: 80 })),
    btn('', () => { delete g.ammunition[l]; save(); renderAmmo(); }, 'sm ghost icon', 'x'))),
    h('button', { type: 'button', class: 'we-reward-add', onclick: async () => { const l = await pickItem(T('Add reward')); if (!l) return; g.ammunition[l] = (g.ammunition[l] || 0) + 1000; save(); renderAmmo(); } },
      icon('plus'), T('Add reward')));
  renderAmmo();
  const wave = (w, n) => {
    const is_open = !!f.on[g.key + n], total = w.alien_spawns.reduce((a, x) => a + x.adet, 0);
    const value = (name, v, cb, opts) => h('label', { class: 'we-wave-value' }, h('span', null, name), weNumber(v, cb, opts));
    const body = is_open ? h('div', { class: 'we-wave-body' }, w.alien_spawns.map(a => h('div', { class: 'we-wave-row' }, npcIcon(a, 30),
      h('div', { class: 'we-box-body' }, h('div', { class: 'we-npc-name' }, h('b', null, npcName(a)), a.permanent ? badge(T('Boss'), 'orange') : null,
          a.changed_kind ? badge(T('Changed'), 'orange') : null, h('span', { class: 'spacer' }),
          a.fixed ? null : btn(T('Switch'), async () => {
            const u = await pickAlien(T('Which alien should this wave have?'), { numeric: true }); if (!u) return;
            Object.assign(a, { tur: u.tip, ad: u.ad, icon: u.icon, hp: u.hp, kalkan: u.kalkan, hasar: u.hasar, hiz: u.hiz, changed_kind: true });
            await save(); weRenderSection(); }, 'sm ghost', 'refresh', { title: T('Replace the alien with a different type (quantity and position stay the same)') })),
        h('div', { class: 'we-box-controls' },
          value(T('Quantity'), a.adet, v => { a.adet = Math.max(a.en_az, v); save(); summary.textContent = T('{0} aliens', fmtN(w.alien_spawns.reduce((t, x) => t + x.adet, 0))); }, { min: a.en_az, max: 5000, width: 46 }),
          value(T('Hit points'), a.hp, v => { a.hp = v; save(); }, { max: 50000000, step: 1000, width: 80 }),
          value(T('Shield'), a.kalkan, v => { a.kalkan = v; save(); }, { max: 50000000, step: 1000, width: 80 }),
          value(T('Damage'), a.hasar, v => { a.hasar = v; save(); }, { max: 1000000, step: 50, width: 62 })))))) : null;
    const summary = h('span', { class: 'small muted' }, T('{0} aliens', fmtN(total)));
    return h('div', { class: 'we-wave' + (is_open ? ' acik' : '') }, h('button', { type: 'button', class: 'we-wave-title', onclick: () => { f.on[g.key + n] = !is_open; weRenderSection(); } },
      icon(is_open ? 'chevR' : 'chevR'), h('b', null, T('Wave {0}', ROMAN(n))), h('span', { class: 'we-wave-icons' }, w.alien_spawns.slice(0, 6).map(a => npcIcon(a, 22))), h('span', { class: 'spacer' }), summary), body);
  };
  return h('div', { class: 'stack', style: { gap: '12px' } },
    h('div', { class: 'we-detail-head' }, art('ed_kapilar', 'we-gate-icon buyuk'), h('div', null, h('div', { class: 'de-h3' }, g.ad), h('div', { class: 'small muted' }, T('{0} waves', g.waves.length)))),
    row(T('Parts required'), 'part', { min: 1, max: 10000, width: 64 }), row(T('Hit points'), 'can', { min: 1, max: 100, width: 50 }),
    h('div', { class: 'we-subtitle' }, T('Gate reward')),
    h('div', { class: 'we-reward-grid' }, GATE_REWARD_FIELD.filter(([k]) => k in g.reward).map(([k, name, looks]) => h('div', { class: 'we-reward' + (std && std.reward[k] !== g.reward[k] ? ' degisti' : '') },
      looks.startsWith('source_') ? art(looks, 'we-reward-icon') : gameIcon(looks || null, 30, null, 'gift'), h('div', null, h('div', { class: 'small muted' }, T(name)),
        weNumber(g.reward[k] || 0, v => { g.reward[k] = v; save(); }, { max: 1e10, step: k === 'ep' ? 10000 : k === 'onur' ? 1000 : 10, width: 92 }))))),
    h('div', { class: 'we-subtitle' }, T('Ammo and item reward')), ammo,
    g.chance.length ? [h('div', { class: 'we-subtitle' }, T('Lucky rewards')), h('div', { class: 'stack', style: { gap: '6px' } }, g.chance.map(x => h('div', { class: 'we-box-row' },
      x.paket ? icon('gift') : gameIcon(x.esya, 32, null, 'gift'), h('div', { class: 'we-box-body' }, h('span', { class: 'we-box-name' }, x.paket ? T('Ore bundle') : itemName(x.esya)),
        h('div', { class: 'we-box-controls' },
          typeof x.adet === 'number' && !x.paket ? [h('span', { class: 'small muted' }, T('Quantity')), weNumber(x.adet, v => { x.adet = Math.max(1, v); save(); }, { min: 1, max: 1e7, width: 60 })] : null,
          h('span', { class: 'small muted' }, T('Chance')), h('input', { class: 'input num we-weight', type: 'number', min: 0, max: 100, step: 'any', value: +(x.probability * 100).toFixed(3),
            onchange: e => { x.probability = Math.max(0, Math.min(100, +e.target.value || 0)) / 100; save(); } }), h('span', { class: 'we-percent' }, '%'))), h('span'))))] : null,
    h('div', { class: 'we-subtitle' }, T('Waves')),
    h('p', { class: 'small muted', style: { margin: 0 } }, T("When the quantity changes, the wave's subgroups are split proportionally. The wave alien multiplier from Game Settings is applied on top of this.")),
    h('div', { class: 'stack', style: { gap: '6px' } }, g.waves.map(wave)),
    g.changed ? btn(T('Reset the gate to standard'), async () => { if (await weRevert('gates.json', route)) weRenderSection(); }, 'sm ghost', 'undo') : null);
}

// ================================================================== ETKİNLİKLER
const EVENT_FILTER = [['harita', N('Map events')], ['yearly', N('Yearly')], ['weekly', N('Weekly')], ['changed', N('Modified')]];
const EVENT_STATUS = [['calendar', N('By calendar'), 'info'], ['on', N('Always on'), 'ok'], ['off', N('Off'), 'err']];
const today = (day = 0) => new Date(Date.now() + day * 86400000).toISOString().slice(0, 10);

async function weEvents(area, b) {
  await alienList();
  const r = await act(() => api('/api/dunya/section?bolum=events&world=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'events') return;
  const f = DE.sec.label || (DE.sec.label = { filter_by: 'harita', q: '', selected: null, history: false });
  const entries = h('div', { class: 'we-npc-list' }), detail = h('div', { class: 'we-detail' });
  const render = () => {
    const s = f.q.trim().toLowerCase();
    const l = r.events.filter(e => (f.filter_by === 'changed' ? e.changed : e.tur === f.filter_by) && (!s || e.ad.toLowerCase().includes(s)));
    fill(entries, ...l.map(e => h('button', { type: 'button', class: 'de-npc' + (f.selected === e.key ? ' on' : '') + (e.changed ? ' degisti' : ''),
      onclick: () => { f.selected = e.key; render(); } }, e.harita?.alien_spawns[0] ? npcIcon(e.harita.alien_spawns[0], 34) : weIcon('events', 'we-gate-icon'),
      h('div', { class: 'we-npc-name' }, h('b', null, e.ad), h('div', { class: 'small muted' },
        e.world_status === 'on' ? T('Always on in this world') : e.world_status === 'off' ? T('Off in this world') : T('By calendar')))) ),
      !l.length ? h('div', { class: 'empty small muted' }, T('No matching events.')) : null);
    const e = r.events.find(x => x.key === f.selected) || l[0];
    if (e && !f.selected) f.selected = e.key;
    fill(detail, e ? eventDetail(e, r, f) : h('div', { class: 'empty muted' }, T('Pick an event on the left.')));
  };
  const seg = h('div', { class: 'seg' }, EVENT_FILTER.map(([k, name]) => h('button', { class: f.filter_by === k ? 'on info' : '', onclick: () => { f.filter_by = k; f.selected = null; weRenderSection(); } }, T(name))));
  fill(area, h('div', { class: 'card' }, weTitle(b, h('input', { class: 'input', style: { width: '180px' }, placeholder: T('Search events…'), value: f.q, oninput: e => { f.q = e.target.value; render(); } }), seg),
    h('p', { class: 'small muted', style: { margin: '10px 0 0' } }, T("An event you turned on or off by hand on the save's Events page takes priority over the world's setting.")),
    h('div', { class: 'we-two-col narrow-list' }, entries, detail)));
  render();
}

function eventDetail(e, r, f) {
  const route = jp('events', e.key);
  const save = () => { e.changed = true; wePatch('events.json', route, { world_status: e.world_status, donemler: e.donemler || undefined,
    harita: e.harita ? { haritalar: e.harita.haritalar, alien_spawns: e.harita.alien_spawns.map(a => ({ adet: a.adet })), quota: e.harita.quota, boss: e.harita.boss } : undefined }); };
  const state = h('div', { class: 'seg' }, EVENT_STATUS.map(([k, name, c]) => h('button', { class: e.world_status === k ? 'on ' + c : '',
    onclick: () => { e.world_status = k; save(); weRenderSection(); } }, T(name))));
  const out = [h('div', { class: 'we-detail-head' }, e.harita?.alien_spawns[0] ? npcIcon(e.harita.alien_spawns[0], 56) : weIcon('events', 'we-gate-icon buyuk'),
    h('div', null, h('div', { class: 'de-h3' }, e.ad), h('div', { class: 'small muted' }, { harita: T('Map event'), yearly: T('Yearly event'), weekly: T('Weekly event') }[e.tur]))),
    h('div', { class: 'we-field-row' }, h('label', null, T('In this world')), state)];
  if (e.donemler) {
    const box = h('div', { class: 'stack', style: { gap: '6px' } });
    const renderPeriods = () => {
      const todayStr = today();
      const lines = e.donemler.map((d, i) => [d, i]).filter(([d]) => f.history || d[0].length === 5 || d[1] >= todayStr);
      fill(box, ...lines.map(([d, i]) => {
        const yearly = d[0].length === 5;
        const entry = (j) => h('input', { class: 'input we-date', type: yearly ? 'text' : 'date', value: d[j], placeholder: yearly ? T('MM-DD') : null,
          onchange: ev => { d[j] = ev.target.value; save(); } });
        return h('div', { class: 'we-period' + (!yearly && d[1] < todayStr ? ' gecmis' : '') + (!yearly && d[0] <= todayStr && todayStr <= d[1] ? ' simdi' : '') },
          entry(0), h('span', { class: 'muted' }, '–'), entry(1), yearly ? badge(T('Every year'), 'info') : null,
          !yearly && d[0] <= todayStr && todayStr <= d[1] ? badge(T('Now'), 'ok') : null, h('span', { class: 'spacer' }),
          btn('', () => { e.donemler.splice(i, 1); save(); renderPeriods(); }, 'sm ghost icon', 'x', { title: T('Delete period') }));
      }), !lines.length ? h('div', { class: 'small dim' }, T('No upcoming periods.')) : null,
      h('div', { class: 'row wrap', style: { gap: '6px' } },
        btn(T('Add period'), () => { e.donemler.push([today(), today(7)]); save(); renderPeriods(); }, 'sm', 'plus'),
        btn(T('Period that repeats every year'), () => { const d = today().slice(5); e.donemler.push([d, today(7).slice(5)]); save(); renderPeriods(); }, 'sm ghost', 'refresh'),
        h('label', { class: 'row small muted', style: { gap: '6px', cursor: 'pointer' } }, h('input', { type: 'checkbox', checked: f.history, onchange: ev => { f.history = ev.target.checked; renderPeriods(); } }),
          T('Show past periods'))));
    };
    renderPeriods();
    out.push(h('div', { class: 'we-subtitle' }, T('Periods')), h('p', { class: 'small muted', style: { margin: 0 } }, T('The event opens between these dates (end day included). "Every year" periods repeat on the same days every year.')), box);
  } else if (e.days || e.hours) {
    const WEEKDAYS = [N('Mon'), N('Tue'), N('Wed'), N('Thu'), N('Fri'), N('Sat'), N('Sun')];
    out.push(h('div', { class: 'we-subtitle' }, T('Weekly schedule')), h('div', { class: 'small muted' },
      (e.days ? e.days.map(g => T(WEEKDAYS[g])).join(', ') : T('Every day')) + (e.hours ? ' · ' + e.hours.map(([a, b2]) => String(a).padStart(2, '0') + ':00–' + String(b2).padStart(2, '0') + ':00').join(', ') : '')),
      h('div', { class: 'small dim' }, T('The weekly schedule can\'t be changed; you can pin it in this world with "Always on" or "Off".')));
  }
  if (e.harita) {
    const gameMap = e.harita;
    const classes = h('div', { class: 'chips' }, r.classes.map(m => { const var_ = gameMap.haritalar.includes(m), allowed = gameMap.selectable.includes(m);
      return h('button', { type: 'button', class: 'chip link we-class' + (var_ ? ' on' : ''), disabled: !allowed && !var_, title: allowed ? null : T('This event has no alien for this map class'),
        onclick: () => { gameMap.haritalar = var_ ? gameMap.haritalar.filter(x => x !== m) : [...gameMap.haritalar, m]; if (!var_ && gameMap.quota[m] == null) gameMap.quota[m] = Math.max(20, ...Object.values(gameMap.quota)); save(); weRenderSection(); } },
        var_ ? icon('check') : icon('plus'), m); }));
    out.push(h('div', { class: 'we-subtitle' }, T('Map event')), h('div', { class: 'small muted' }, T("Map classes where the event's aliens spawn:")), classes,
      ...gameMap.alien_spawns.map(a => h('div', { class: 'we-field-row' }, npcIcon(a, 28), h('b', { class: 'small', style: { minWidth: '120px' } }, npcName(a)),
        weNumber(a.adet, v => { a.adet = v; save(); }, { max: 200, width: 56 }), h('span', { class: 'small muted' }, T('at once on the map')))),
      Object.keys(gameMap.quota).length ? h('div', { class: 'small muted' }, T('Quota per map (the most that spawn on that map during the event):')) : null,
      Object.keys(gameMap.quota).length ? h('div', { class: 'we-quota' }, gameMap.haritalar.filter(m => m in gameMap.quota).map(m => h('label', { class: 'we-wave-value' }, h('span', null, m),
        weNumber(gameMap.quota[m], v => { gameMap.quota[m] = v; save(); }, { max: 10000, width: 56 })))) : null,
      gameMap.boss ? h('div', { class: 'we-field-row' }, h('label', null, T('Boss')), h('label', { class: 'we-wave-value' }, h('span', null, T('Quantity')),
        weNumber(gameMap.boss.adet, v => { gameMap.boss.adet = v; save(); }, { max: 50, width: 46 })),
        h('label', { class: 'we-wave-value' }, h('span', null, T('Duration (min)')), weNumber(Math.round(gameMap.boss.sure_sn / 60), v => { gameMap.boss.sure_sn = Math.max(1, v) * 60; save(); }, { min: 1, max: 1440, width: 52 }))) : null);
  }
  if (e.changed) out.push(btn(T('Reset event to standard'), async () => { if (await weRevert('events.json', route)) weRenderSection(); }, 'sm ghost', 'undo'));
  return h('div', { class: 'stack', style: { gap: '12px' } }, out);
}

// ================================================================== ÖDÜLLER VE EKONOMİ
const RANK_FORMULA = [['ep', N('Per experience point')], ['onur', N('Per honor point')], ['seviye', N('Per level')], ['npc', N('Per alien point')],
  ['gorev', N('Per completed quest')], ['player', N("Per defeated player's points")], ['gemi', N('Per ship point')], ['gun', N('Per day since the save was created')],
  ['friendly', N('Per player destroyed from your own company')], ['death_by_enemy', N('Per defeat by an enemy')], ['death_by_radiation', N('Per death in radiation')],
  ['phoenix', N('Per Phoenix destroyed')]];

async function weEconomy(area, b) {
  const r = await act(() => api('/api/dunya/section?bolum=economy&world=' + encodeURIComponent(DE.did))); if (!r || DE.section !== 'economy') return;
  const f = DE.sec.ek || (DE.sec.ek = { all: false });
  const lv = r.seviyeler.map(x => x.slice()), es = r.thresholds.slice(), fo = Object.assign({}, r.formula);
  const saveLevels = () => wePatch('levels.json', jp('seviyeler'), lv.map(x => x[1]));
  const limit = f.all ? lv.length : 26;
  const levels = h('div', { class: 'we-level-grid' }, lv.slice(1, limit).map((x, i) => h('label', { class: 'we-wave-value' + (x[1] !== r.levels_default[i + 1][1] ? ' degisti' : '') },
    h('span', { class: 'we-lv' }, x[0]), weNumber(x[1], v => { x[1] = v; saveLevels(); }, { min: 1, max: 1e15, step: 1000, width: 112 }))));
  const percent = h('div', { class: 'chips' }, [50, 75, 125, 200].map(p => h('button', { type: 'button', class: 'chip link', onclick: () => {
    lv.forEach((x, i) => { if (i) x[1] = Math.max(lv[i - 1][1] + 1, Math.round(r.levels_default[i][1] * p / 100)); }); saveLevels().then(() => weRenderSection()); } }, '%' + p)));
  const formula = h('div', { class: 'stack', style: { gap: '4px' } }, RANK_FORMULA.filter(([k]) => k in fo).map(([k, name]) => h('div', { class: 'we-field-row' + (fo[k] !== r.formula_default[k] ? ' degisti' : '') },
    h('label', { style: { width: '240px' } }, T(name)), h('input', { class: 'input num', type: 'number', step: 'any', value: fo[k], style: { width: '110px' },
      onchange: ev => { fo[k] = +ev.target.value || 0; wePatch('ranks.json', jp('formula'), fo); } }),
    weStd(r.formula_default[k], fo[k], () => { fo[k] = r.formula_default[k]; wePatch('ranks.json', jp('formula'), fo).then(() => weRenderSection()); }, x => String(x)))));
  const thresholds = h('div', { class: 'we-level-grid wide' }, es.slice(1).map((n, i) => h('label', { class: 'we-wave-value' + (n !== r.thresholds_default[i + 1] ? ' degisti' : '') },
    h('span', { class: 'ellipsis', style: { width: '150px' } }, r.ranks[i + 1] || i + 2),
    weNumber(n, v => { es[i + 1] = v; wePatch('ranks.json', jp('thresholds'), es); }, { min: 1, max: 1e9, step: 100, width: 92 }))));
  const back = (file, route, name) => btn(T('Reset to standard'), async () => { if (await weRevert(file, route)) weRenderSection(); }, 'sm ghost', 'undo', { title: name });
  fill(area, h('div', { class: 'stack' },
    h('div', { class: 'card' }, weTitle(b)),
    h('div', { class: 'card' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('star'), T('Level thresholds')), h('div', { class: 'row', style: { gap: '6px' } }, percent, back('levels.json', jp('seviyeler')))),
      h('p', { class: 'desc' }, T('Total experience (EP) required to reach each level. For faster progression, pick a percentage of the standard thresholds.')), levels,
      lv.length > limit || f.all ? btn(f.all ? T('Show less') : T('All levels ({0})', lv.length), () => { f.all = !f.all; weRenderSection(); }, 'sm ghost', 'chevR') : null),
    h('div', { class: 'card' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('shield'), T('Rank point formula')), back('ranks.json', jp('formula'))),
      h('p', { class: 'desc' }, T('Rank points are summed with these coefficients; negative coefficients lower the points.')), formula),
    h('div', { class: 'card' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('shield'), T('Rank thresholds')), back('ranks.json', jp('thresholds'))),
      h('p', { class: 'desc' }, T('Minimum rank points required for each rank (in single-player, the rank is awarded by these thresholds).')), thresholds),
    h('div', { class: 'alert info' }, icon('info'), h('div', null, T("The rewards of the daily login calendar are shown from the game's own file, so they can't be changed here (a changed reward would still look the old way in the calendar).")))));
}

// ================================================================== PAYLAŞIM (dışa / içe aktarma, paylaşım kodu)
async function weExport(w) {
  const r = await act(() => api('/api/dunya/kod', { world: w.id })); if (!r) return;
  const long = r.code.length > 1900;
  const code = h('textarea', { class: 'input mono we-code', rows: 4, readonly: true }, r.code);
  const m = modal({ title: T('Share world "{0}"', w.ad), wide: true, body: h('div', { class: 'stack', style: { gap: '12px' } },
    h('div', { class: 'we-share-summary' }, weCover(w.cover, 'lowercase'), h('div', null, h('b', null, w.ad), h('div', { class: 'small muted' },
      w.standard ? T('Draft of the standard world') : T('{0} changes', w.changes)))),
    h('div', { class: 'we-share-paths' },
      h('div', { class: 'we-share-path' }, icon('download'), h('b', null, T('As a file')), h('div', { class: 'small muted' }, T('A .json file: your friend adds it with "Import" in their World Editor.')),
        btn(T('Save to file'), () => act(() => api('/api/dunya/disari', { world: w.id })).then(x => { if (x && x.route) { toast(T('Saved: {0}', x.route), 'ok'); m.close(); } }), 'sm primary', 'download')),
      h('div', { class: 'we-share-path' }, icon('copy'), h('b', null, T('Share code')), h('div', { class: 'small muted' },
        long ? T("The code is {0} characters long: it won't fit in a Discord message, so share it as a file or send it as a text file.", fmtN(r.code.length))
          : T('The code is {0} characters long: you can paste it into chat or Discord.', fmtN(r.code.length))),
        btn(T('Copy code'), async () => { try { await navigator.clipboard.writeText(r.code); toast(T('Code copied.'), 'ok'); } catch (e) { code.select(); document.execCommand('copy'); toast(T('Code copied.'), 'ok'); } }, 'sm', 'copy'))),
    code,
    h('div', { class: 'small dim' }, T('A shared world carries only the changes; saves, pilots and progress are not shared.'))),
    foot: [btn(T('Close'), () => m.close(), 'ghost')] });
}

function weImport() {
  const code = h('textarea', { class: 'input mono we-code', rows: 4, placeholder: 'OODUNYA1:…' });
  const result = x => { if (!x || x.cancelled) return; m.close(); DE.liste = x; weImportReport(x); };
  const m = modal({ title: T('Import world'), wide: true, body: h('div', { class: 'stack', style: { gap: '12px' } },
    h('div', { class: 'we-share-paths' },
      h('div', { class: 'we-share-path' }, icon('folder'), h('b', null, T('From file')), h('div', { class: 'small muted' }, T('Choose the shared .json file.')),
        btn(T('Choose file…'), () => act(() => api('/api/dunya/import', {})).then(result), 'sm primary', 'upload')),
      h('div', { class: 'we-share-path' }, icon('copy'), h('b', null, T('From share code')), h('div', { class: 'small muted' }, T('Paste the code below.')),
        btn(T('Import from code'), () => code.value.trim() ? act(() => api('/api/dunya/import', { code: code.value })).then(result) : toast(T('Paste the code first.'), 'info'), 'sm', 'upload'))),
    code, h('div', { class: 'small dim' }, T('An imported world is added as a new world; it never overwrites any world.'))),
    foot: [btn(T('Cancel'), () => m.close(), 'ghost')] });
}

function weImportReport(x) {
  const r = x.report || {}, w = x.liste.find(d => d.id === x.yeni);
  const m = modal({ title: T('World imported'), body: h('div', { class: 'stack', style: { gap: '12px' } },
    h('div', { class: 'we-share-summary' }, art('drone_record', 'we-report-art'), h('div', null, h('b', null, w ? w.ad : x.yeni), h('div', { class: 'small muted' }, T('{0} changes', r.changes || 0)))),
    r.data_differs?.length ? h('div', { class: 'alert warning' }, icon('alert'), h('div', null, T('This world was prepared with different game data ({0}). The changes are applied, but some may not work as expected.', r.data_differs.join(', ')))) : null,
    r.skipped ? h('div', { class: 'alert warning' }, icon('alert'), h('div', null, T('Changes skipped because they could not be applied: {0}.', r.skipped),
      r.issues?.length ? h('ul', { class: 'small we-issues' }, r.issues.map(s2 => h('li', null, s2))) : null)) : null,
    !r.data_differs?.length && !r.skipped ? h('div', { class: 'alert info' }, icon('check'), h('div', null, T('All changes were applied.'))) : null),
    foot: [btn(T('Close'), () => { m.close(); renderWorld(); }, 'ghost'), btn(T('Open the world'), () => { m.close(); weOpen(x.yeni); }, 'primary', 'chevR')] });
}

// ================================================================== OYNA SAYFASI: kaydın dünyası
function playWorldChip(a) {
  const w = a.world_info;
  return h('button', { type: 'button', class: 'game-world', title: T('PLAY opens this world. Click to change.'), onclick: ev => playWorldMenu(ev.currentTarget, a) },
    weCover(w.cover, 'mini'), h('span', { class: 'game-world-name' }, h('small', null, T('World')), h('b', null, w.ad)),
    w.standard ? icon('lock') : w.changes ? badge(T('{0} changes', w.changes), 'orange') : null, icon('chevR'));
}
async function playWorldMenu(anchor, a) {
  const r = await act(() => api('/api/dunyalar')); if (!r) return;
  popMenu(anchor, [...r.liste.map(w => ({ label: w.ad + (w.id === a.world_info.id ? '  ✓' : ''), ic: w.standard ? 'lock' : 'globe',
    fn: () => act(() => api('/api/kayitlar/dunya', { id: a.id, world: w.id }), T('{0} now enters the world "{1}".', a.pilot, w.ad)).then(x => x && poll()) })),
    '-', { label: T('World Editor'), ic: 'edit', fn: () => { DE.did = a.world_info.id; DE.section = 'genel'; go('world'); } }]);
}

// ARKADAŞLARINLA OYNA > Host: sunucunun dünyası (panel ayarı arkadas_dunya; boş: kaydının dünyası)
function hostWorldChip(v) {
  const w = v.world.valid;
  return h('button', { type: 'button', class: 'game-world', title: T('The server starts with this world; guests play in it too. Click to change.'),
    onclick: ev => popMenu(ev.currentTarget, [{ label: T("Your save's world ({0})", v.world.save_world.ad) + (!v.world.choice ? '  ✓' : ''), ic: 'save', fn: () => hostPickWorld('') },
      ...v.world.liste.map(x => ({ label: x.ad + (v.world.choice === x.id ? '  ✓' : ''), ic: x.standard ? 'lock' : 'globe', fn: () => hostPickWorld(x.id) })), '-',
      { label: T('World Editor'), ic: 'edit', fn: () => { DE.did = w.id; DE.section = 'genel'; go('world'); } }]) },
    weCover(w.cover, 'mini'), h('span', { class: 'game-world-name' }, h('small', null, T("Server's world")), h('b', null, w.ad)),
    w.standard ? icon('lock') : w.changes ? badge(T('{0} changes', w.changes), 'orange') : null, icon('chevR'));
}
function hostPickWorld(id) {
  act(() => api('/api/arkadas/ayarlar', { world: id }), FRD.data?.host?.on ? T('This world opens when the server restarts.') : T('Saved.'))
    .then(r => { if (r) { FRD.data = r; drawFriends(); } });
}
