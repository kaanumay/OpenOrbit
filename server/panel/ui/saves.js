/* OpenOrbit panel — Saves and the character editor (saves.py, save_editor.py; /api/kayitlar..., /api/editor...). Uses panel.js's
   helpers and the game's images (ogYukle, sprite, esyaSprite, esyaAdi: the BepInEx dump).
   Library: the active save's scene (ship, company portrait, level progress, wallet), cards of the other saves, deleted ones.
   Editor: works on the save's draft (duzenleme.json). Every action is applied to the draft with the game's rules (hangar, reward path) and the view is
   refreshed; Save takes a safety backup and writes to the save, Discard throws the draft away. Read-only if the save is in game. */
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
// ship: large top-down view (_top), otherwise the shop icon; the design's own look first (ship_sentinel_design_sentinel-carbonite)
function shipSprite(lid, firma) {
  const k = lid.replace(/^ship_/, ''), last = k.split('_').pop(), base = k.split('_')[0];
  for (const c of [last, last + '-' + firma, base, base + '-' + firma]) for (const b of ['_top', '_100x100']) if (GI.index?.sprite[c + b]) return c + b;
  return itemSprite(lid, firma);
}
const shipImage = (lid, size, firma) => {
  const sp = lid && GI.index && shipSprite(lid, firma), el = sp ? sprite(sp, size) : seEmpty(size, 'ship');
  if (lid) el.dataset.loot = lid;              // item tooltip: values, slots, bonus (panel.js itemHint)
  return el;
};
// drone: the look of its level (iris-4: level 5), otherwise a lower one
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
const itemIcon = (lid, size, firma) => gameIcon(lid, size, firma || companyLower(SE.v?.pilot.company), 'box');
// the company's character portrait in the game (CommonUI eic_char), otherwise the panel's crest
const portrait = (f, cls = 'se-portrait', size = 112) => GI.index?.sprite[companyLower(f) + '_char'] ? h('span', { class: cls }, sprite(companyLower(f) + '_char', size))
  : h('span', { class: cls + ' emblem' }, art('firma_' + (companyLower(f) || 'eic'), 'crest'));
function epBar(ep, base, next_, cls = '') {
  const p = next_ ? Math.max(0, Math.min(1, (ep - base) / Math.max(1, next_ - base))) : 1;
  return h('div', { class: 'se-ep ' + cls, title: next_ ? T('{0} / {1} EP', fmtN(ep), fmtN(next_)) : T('Highest level') }, h('span', { style: { width: (p * 100).toFixed(1) + '%' } }));
}

// ================================================================== LIBRARY
const KL = { trash: false };

async function renderSaves() {
  if (SE.slot) return renderEditor();
  await loadGameImages();
  const r = await act(() => api('/api/saves')); if (!r || S.page !== 'saves' || SE.slot) return;
  const active = r.entries.find(k => k.active), others = r.entries.filter(k => !k.active);
  const tools = h('div', { class: 'row wrap' },
    btn(T('New save'), () => newSaveModal(), 'primary', 'plus'),
    btn(T('Import…'), () => act(() => api('/api/saves/import', {}), x => x.cancelled ? T('Cancelled.') : T('Save imported.')).then(() => renderSaves()), '', 'upload'),
    h('span', { class: 'spacer' }),
    r.entries.length ? h('span', { class: 'small muted' }, T('{0} saves', r.entries.length)) : null,
    btn(T('Saves folder'), () => act(() => api('/api/open_folder', { ne: 'saves' })), 'ghost', 'folder'));
  $('#content').replaceChildren(h('div', { class: 'stack ke-kitap' }, tools,
    active ? saveScene(active) : h('div', { class: 'card empty' }, art('empty_save'), h('h3', null, T('No saves yet')),
      h('div', null, T('Create a new save or import a backup.'))),
    others.length ? h('div', { class: 'section-title' }, T('Other saves ({0})', others.length)) : null,
    others.length ? h('div', { class: 'se-cards' }, others.map(saveCard)) : null,
    trash(r.trash)));
}

// the shared "More" menu of the save cards (extra client, name, note, copy, export, folder, delete)
function saveMenu(k, ev) {
  const c = S.state?.multi, extra = c && c.setting && c.save_count > 1 && (c.saves || []).find(x => x.id === k.id);
  const extraWhy = extra ? (extra.extra || k.id === c.main ? T('Save in use') : extraBlock(S.state, extra)) : null;
  popMenu(ev.currentTarget, [
    extra ? { label: extraWhy ? T('Open in extra client ({0})', extraWhy) : T('Open in extra client'), iconEl: 'play', disabled: !!extraWhy,
      fn: () => openExtra(k.id, k.pilot).then(() => S.page === 'saves' && renderSaves()) } : null,
    extra ? '-' : null,
    { label: T('Rename'), ic: 'edit', fn: async () => { const v = await promptBox(T('Rename save'), T('Save name'), k.name); if (v != null) act(() => api('/api/saves/rename', { id: k.id, name: v }), T('Name changed.')).then(renderSaves); } },
    { label: T('Add / edit note'), ic: 'note', fn: async () => { const v = await promptBox(T('Save note'), T('Note'), k.not_, { multiline: true }); if (v != null) act(() => api('/api/saves/note', { id: k.id, not: v })).then(renderSaves); } },
    { label: T('Copy'), ic: 'copy', fn: async () => { const v = await promptBox(T('Copy save'), T('Name of the new save'), T('{0} (copy)', k.name)); if (v != null) act(() => api('/api/saves/copy', { id: k.id, name: v }), T('Copied.')).then(renderSaves); } },
    { label: T('Export (.zip)…'), ic: 'download', fn: () => act(() => api('/api/saves/export', { id: k.id, with_backups: true }), x => x.cancelled ? T('Cancelled.') : T('Exported: {0}', x.route)) },
    { label: T('Open folder'), ic: 'folder', fn: () => act(() => api('/api/open_folder', { ne: 'record', id: k.id })) },
    '-',
    { label: T('Delete'), ic: 'trash', danger: true, disabled: k.in_use, fn: async () => {
      if (await confirmBox(T('Delete the save?'), T('"{0}" ({1}) goes to the trash; you can restore it at the bottom of the Saves page.', k.name, k.pilot), { ok: T('Delete'), danger: true }))
        act(() => api('/api/saves/delete', { id: k.id }), T('Moved to the trash.')).then(renderSaves);
    } },
  ].filter(Boolean));
}
const statusBadges = k => [k.in_use ? badge(T('IN GAME'), 'ok') : null, k.draft ? badge(T('UNSAVED CHANGES'), 'warn') : null,
  k.corrupt ? badge(T('CORRUPT'), 'err') : null];

// active save: wide scene (ship, company portrait, level, wallet, actions)
function saveScene(k) {
  const f = companyLower(k.company);
  const currency = (name, n, tag) => h('div', { class: 'se-currency-card' }, art('source_' + name, 'se-currency-icon'), h('div', null, h('span', null, tag), h('b', null, fmtN(n))));
  const meta = (iconEl, tag, value) => h('div', { class: 'se-meta' }, icon(iconEl), h('span', null, tag), h('b', null, value));
  return h('div', { class: 'card se-scene f-' + f },
    h('div', { class: 'se-scene-ship' }, shipImage(k.ship_appearance, 250, f),
      h('div', { class: 'se-scene-ship-name' }, k.ship_appearance ? itemName(k.ship_appearance) : k.ship)),
    h('div', { class: 'se-scene-body' },
      h('div', { class: 'row wrap', style: { gap: '8px' } }, badge(T('ACTIVE SAVE'), 'info'), ...statusBadges(k)),
      h('div', { class: 'se-scene-head' }, portrait(k.company),
        h('div', { style: { minWidth: 0 } }, h('h2', { class: 'se-scene-name' }, k.name),
          h('div', { class: 'se-pilot' }, h('b', null, k.pilot), k.clan ? h('span', { class: 'se-clan' }, '[' + k.clan + ']') : null,
            badge(k.company || '?', firmaCls(k.company)), k.premium ? badge('Premium', 'orange') : null))),
      h('div', { class: 'se-lv' }, h('div', { class: 'se-lv-num' }, h('small', null, T('Level')), h('b', null, k.level ?? '?')),
        h('div', { class: 'grow' }, h('div', { class: 'row between small muted' }, h('span', null, T('Experience')),
          h('span', { class: 'mono' }, k.next_level ? fmtShort(k.ep) + ' / ' + fmtShort(k.next_level) + ' EP' : fmtShort(k.ep) + ' EP')),
          epBar(k.ep, k.level_base, k.next_level))),
      h('div', { class: 'se-currencies' }, currency('credits', k.credits, T('Credits')), currency('uridium', k.uridium, T('Uridium')), currency('honor', k.honor, T('Honor'))),
      h('div', { class: 'se-metas' }, meta('map', T('Map'), k.map), meta('ship', T('Ship'), T('{0} ships', k.ship_count)),
        meta('drone', T('Drones'), k.drone_count), meta('paw', 'P.E.T.', k.pet || '—'), meta('clock', T('Play time'), fmtDur(k.play_sec)),
        meta('calendar', T('Last played'), fmtWhen(k.last_played || k.last_save))),
      k.not_ ? h('div', { class: 'note' }, k.not_) : null,
      h('div', { class: 'row wrap se-action' },
        btn(T('Play'), () => { go('play'); act(() => api('/api/play', {})); }, 'orange', 'play', { disabled: k.in_use }),
        btn(T('Character editor'), () => seOpen(k), 'primary', 'edit'),
        btn(T('Backups ({0})', k.backup_count), () => backupsModal(k.id), '', 'clock'),
        h('span', { class: 'spacer' }),
        btn('', ev => saveMenu(k, ev), 'ghost icon', 'more', { title: T('More') }))));
}

function saveCard(k) {
  const f = companyLower(k.company);
  return h('div', { class: 'card se-card-save f-' + f },
    h('div', { class: 'se-card-top' },
      h('div', { class: 'se-card-ship' }, shipImage(k.ship_appearance, 96, f)),
      h('div', { class: 'grow', style: { minWidth: 0 } },
        h('div', { class: 'row', style: { gap: '6px', minWidth: 0 } }, h('span', { class: 'se-card-name', title: k.name }, k.name)),
        h('div', { class: 'se-pilot small' }, h('b', null, k.pilot), k.clan ? h('span', { class: 'se-clan' }, '[' + k.clan + ']') : null, badge(k.company || '?', firmaCls(k.company))),
        h('div', { class: 'row', style: { gap: '8px', marginTop: '6px' } }, h('span', { class: 'se-lv-mini' }, T('Lv {0}', k.level ?? '?')),
          h('div', { class: 'grow' }, epBar(k.ep, k.level_base, k.next_level, 'ince')))),
      btn('', ev => saveMenu(k, ev), 'ghost icon sm', 'more', { title: T('More') })),
    h('div', { class: 'row wrap', style: { gap: '6px' } }, ...statusBadges(k)),
    h('div', { class: 'se-card-currencies' },
      h('span', null, art('source_credits', 'se-currency-icon sm'), fmtShort(k.credits)), h('span', null, art('source_uridium', 'se-currency-icon sm'), fmtShort(k.uridium)),
      h('span', null, icon('ship'), k.ship_appearance ? itemName(k.ship_appearance) : k.ship), h('span', null, icon('clock'), fmtWhen(k.last_played || k.last_save))),
    k.not_ ? h('div', { class: 'note' }, k.not_) : null,
    h('div', { class: 'row wrap', style: { gap: '6px', marginTop: 'auto' } },
      btn(T('Make active'), () => act(() => api('/api/saves/active', { id: k.id }), T('Active save: {0}', k.name)).then(() => { renderSaves(); poll(); }), 'primary sm', 'check'),
      btn(T('Editor'), () => seOpen(k), 'sm', 'edit'),
      btn(T('Backups'), () => backupsModal(k.id), 'sm ghost', 'clock')));
}

function trash(entries) {
  if (!entries.length) return null;
  const d = h('details', { class: 'card se-trash', open: KL.trash, ontoggle: e => { KL.trash = e.target.open; } },
    h('summary', null, icon('trash'), T('Deleted ({0})', entries.length), h('span', { class: 'small muted' }, T('Deleted saves wait here; you can restore them or delete them permanently.'))),
    h('table', { class: 'table' }, h('thead', null, h('tr', null, h('th', null, T('Save file')), h('th', null, T('Pilot')), h('th', null, T('Deleted')), h('th'))),
      h('tbody', null, entries.map(x => h('tr', null, h('td', null, x.name), h('td', null, `${x.pilot} · ${lvl(x.level)}`), h('td', { class: 'muted' }, fmtWhen(x.deletion)),
        h('td', { class: 'num' }, h('div', { class: 'actions', style: { justifyContent: 'flex-end' } },
          btn(T('Restore'), () => act(() => api('/api/saves/undo', { file: x.file }), T('Save restored.')).then(renderSaves), 'sm', 'undo'),
          btn(T('Delete permanently'), async () => {
            if (await confirmBox(T('Delete permanently?'), T('The save "{0}" and its backups are deleted from disk. This cannot be undone.', x.name), { ok: T('Delete permanently'), danger: true }))
              act(() => api('/api/saves/empty_trash', { file: x.file }), T('Deleted permanently.')).then(renderSaves);
          }, 'danger sm', 'trash'))))))),
    entries.length > 1 ? h('div', { class: 'row', style: { marginTop: '12px', justifyContent: 'flex-end' } },
      btn(T('Empty the trash'), async () => {
        if (await confirmBox(T('Empty the trash?'), T('{0} saves will be deleted permanently.', entries.length), { ok: T('Empty'), danger: true }))
          act(() => api('/api/saves/empty_trash', {}), T('Trash emptied.')).then(renderSaves);
      }, 'danger sm', 'trash')) : null);
  return d;
}

// ================================================================== CHARACTER EDITOR
const SE = { slot: null, name: '', v: null, tab: 'pilot', ship: null, config: null, busy: false, catalog: null, search: '', ammoFilled: false, invKind: 'all', resourceSearch: '' };
const SE_TABS = [
  ['pilot', N('Pilot'), 'user', 'pilotSheet_normal'], ['hangar', N('Hangar'), 'hangar', 'hangar_normal'], ['drones', N('Drones'), 'drone', null],
  ['pet', 'P.E.T.', 'paw', 'pet_normal'], ['inventory', N('Inventory'), 'box', 'assembly_normal'], ['ammunition', N('Ammunition'), 'ammo', null],
  ['sources', N('Resources'), 'gem', 'refinement_normal'], ['boosters', N('Boosters'), 'zap', 'booster_normal'], ['maintenance', N('Maintenance'), 'wrench', 'settings_normal'],
  ['stats', N('Statistics'), 'star', null],
];
const SE_CATEGORY = { all: N('All'), ship: N('Ships'), design: N('Ship designs'), laser: N('Lasers'), rocket_launcher: N('Rocket launchers'), generator: N('Generators'),
  extras: N('Extras and CPUs'), module: N('Modules and cores'), heavy: N('Heavy weapons'), drone: N('Drones and formations'), pet: 'P.E.T.', ammunition: N('Ammunition'),
  booster: N('Boosters'), source: N('Resources'), package: N('Packages'), other: N('More') };
const SE_CATEGORY_ICON = { all: 'layers', ship: 'ship', design: 'wand', laser: 'zap', rocket_launcher: 'target', generator: 'shield', extras: 'cpu', module: 'layers', heavy: 'crosshair',
  drone: 'drone', pet: 'paw', ammunition: 'ammo', booster: 'zap', source: 'gem', package: 'gift', other: 'box' };
const SE_AMMO = [['laser', N('Laser ammo')], ['rocket', N('Rockets')], ['rocket_launcher', N('Rocket launcher ammo')], ['mine', N('Mines')], ['special', N('Special ammo')], ['other', N('More')]];
const SE_RESET = [['hints', N('Show tips again (closed and already shown ones, event notices)')],
  ['ui', N('Reset menu bars and window positions')], ['game_settings', N("Reset the game's Settings window (graphics, sound, gameplay)")],
  ['active_quests', N('Drop accepted missions (finished ones stay)')], ['history', N('Clear the logbook and account history')]];
const SE_FIELD = { name: N('Pilot name'), company: N('Company'), level: N('Level'), ep: N('Experience (EP)'), credits: N('Credits'), uridium: N('Uridium'), honor: N('Honor'),
  premium: 'Premium', active_ship: N('Active ship'), map: N('Map'), hp: N('Ship hit points') };

function seOpen(k) {
  Object.assign(SE, { slot: k.id, name: k.name, v: null, tab: 'pilot', ship: null, config: null });
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
    if (v.discarded) toast(T('The save changed after it was opened in the editor (the game was played or a backup restored): the old draft was discarded.'), 'info', 7000);
  }
  seRender();
}

// no game images (the game is not installed or was never opened with BepInEx): the editor can only show items clearly with the game's icons and
// names; the library (save cards) works without images too
function seLock() {
  if (S.page !== 'saves' || !SE.slot) return;
  $('#content').replaceChildren(h('div', { class: 'stack ke-editor' },
    h('div', { class: 'card se-bar' }, btn(T('Saves'), seClose, 'ghost', 'arrowL'),
      h('div', { class: 'se-bar-name' }, h('b', null, SE.name || SE.slot), h('div', { class: 'small muted' }, T('Character editor')))),
    h('div', { class: 'card empty se-lock' }, art('drone_lock'), h('h3', null, T("The game's images aren't ready yet")),
      h('p', null, T("The character editor shows items with the game's own icons, names and descriptions. Install the game and open it once with PLAY: the images are prepared on the first launch, then the editor opens.")),
      h('div', { class: 'row', style: { justifyContent: 'center', gap: '8px' } }, btn(T('Client page'), () => go('client'), 'primary', 'monitor'),
        btn(T('Try again'), () => renderEditor(), '', 'refresh')))));
}

// apply the actions to the draft (save_editor.OPS); on success the new view is drawn -> was it successful
async function seApply(...ops) {
  if (!SE.v || SE.v.read_only || SE.busy) return false;
  SE.busy = true; document.body.classList.add('se-busy');
  const v = await act(() => api('/api/editor/apply', { id: SE.slot, ops }));
  SE.busy = false; document.body.classList.remove('se-busy');
  if (v && SE.slot) { SE.v = v; seRender(); return true; }
  return false;
}

// Search box: the editor (all tabs and item tiles) is rebuilt when typing pauses, not on every key; the cursor stays in place
function seSearch(e, assign) {
  assign(e.target.value); clearTimeout(SE.searchTimer);
  SE.searchTimer = setTimeout(() => {
    if (!e.target.isConnected) return;          // meanwhile the page or tab changed
    const pos = e.target.selectionStart; seRender();
    const new_ = $('.se-main .game-search'); if (new_) { new_.focus(); new_.setSelectionRange(pos, pos); }
  }, 150);
}
function seRender() {
  if (S.page !== 'saves' || !SE.slot || !SE.v) return;
  const v = SE.v, c = $('#content'), sc = c.scrollTop;
  const tab = SE_TABS.find(s => s[0] === SE.tab) || SE_TABS[0];
  c.replaceChildren(h('div', { class: 'stack ke-editor' }, seBar(v),
    v.read_only ? h('div', { class: 'alert warning' }, icon('lock'), h('div', null, h('b', null, T('The save is in the game right now: view only.')), ' ',
      T('Close the game and the server to make changes. While the game is running, use the in-game Hangar and Shop pages for equipment and purchases.'))) : null,
    h('div', { class: 'se-layout' },
      h('aside', { class: 'se-side' }, seIdentity(v), seMenu(v)),
      h('div', { class: 'se-main' }, h('div', { class: 'se-main-head' }, seTabIcon(tab, 30), h('div', null, h('h2', null, T(tab[1])), h('div', { class: 'small muted' }, seTabDescription(tab[0])))),
        SE_RENDER[tab[0]](v)))));
  c.scrollTop = sc;
}

// tab icon: the panel's image (images/ke_<tab>.webp, Orders.md OP-013: delivered ones go to SE_IMAGE), otherwise the game's menu sprite, otherwise a line icon
const SE_IMAGE = new Set(['pilot', 'hangar', 'drones', 'pet', 'inventory', 'ammunition', 'sources', 'boosters', 'maintenance']);
const seTabIcon = (s, size) => SE_IMAGE.has(s[0]) ? h('span', { class: 'se-tab-icon image' }, art('ke_' + s[0], 'se-tab-art'))
  : s[3] && GI.index?.sprite[s[3]] ? h('span', { class: 'se-tab-icon game' }, sprite(s[3], size)) : h('span', { class: 'se-tab-icon' }, icon(s[2]));
const seTabDescription = id => T({ pilot: N('Name, company, level, experience, honor and wallet.'), hangar: N('Ships, two configs, designs and slots: click to equip or unequip.'),
  drones: N('Drones, their levels, upgrades and equipment.'), pet: N('P.E.T.: level, fuel, open slots and equipment.'),
  inventory: N('Unequipped items: equip them, change their level or delete them.'), ammunition: N('Laser ammo, rockets, mines and special ammo.'),
  sources: N('Ores in the cargo and collectible resources.'), boosters: N('Timed bonuses and their remaining time.'),
  maintenance: N('Repair, home station, key bindings and state resets.'),
  stats: N('Rank point breakdown, destroyed aliens and players, deaths, gate times.') }[id]);

function seBar(v) {
  const f = v.diff || { number: 0 }, ro = v.read_only;
  return h('div', { class: 'card se-bar' },
    btn(T('Saves'), seClose, 'ghost', 'arrowL'),
    h('div', { class: 'se-bar-name' }, h('b', null, SE.name || SE.slot), h('div', { class: 'small muted' }, T('Character editor'))),
    h('span', { class: 'spacer' }),
    ro ? badge(T('Read-only'), 'warn')
      : f.number ? h('button', { class: 'se-change exists', type: 'button', onclick: seChanges, title: T('View changes') }, h('span', { class: 'se-pulse' }), T('{0} unsaved changes', f.number), icon('chevR'))
        : h('span', { class: 'se-change' }, icon('check'), T('Same as the save')),
    ro ? null : btn(T('Cancel'), seCancel, 'ghost', 'undo', { disabled: !f.number }),
    ro ? null : btn(T('Save'), seSave, 'primary', 'save', { disabled: !f.number }));
}

function seIdentity(v) {
  const p = v.pilot, d = v.state, g = v.ships.find(x => x.active) || v.ships[0], f = companyLower(p.company);
  const sell = (name, n, tag) => h('div', { class: 'se-wallet-row' }, art('source_' + name, 'se-currency-icon'), h('span', null, tag), h('b', null, fmtN(n)));
  const value = (sp, iconEl, n, m) => h('div', { class: 'se-value', title: m != null ? fmtN(n) + ' / ' + fmtN(m) : fmtN(n) }, spr(sp, 20, iconEl), h('b', null, fmtShort(n)));
  return h('div', { class: 'card se-identity f-' + f },
    h('div', { class: 'se-identity-scene' }, h('div', { class: 'se-ring' }), shipImage(g.appearance, 170, f)),
    h('div', { class: 'se-identity-head' }, portrait(p.company, 'se-portrait lowercase', 84),
      h('div', { style: { minWidth: 0 } }, h('div', { class: 'se-identity-name' }, p.name), h('div', { class: 'se-pilot small' }, p.clan ? h('span', { class: 'se-clan' }, '[' + p.clan + ']') : null,
        badge(COMPANY_TAG[p.company] || '?', firmaCls(COMPANY_TAG[p.company])), p.premium ? badge('Premium', 'orange') : null))),
    h('div', { class: 'se-lv sm' }, h('div', { class: 'se-lv-num' }, h('small', null, T('Lv')), h('b', null, p.level)),
      h('div', { class: 'grow' }, h('div', { class: 'row between small muted' }, h('span', null, itemName(g.lootId)), h('span', { class: 'mono' }, fmtShort(p.ep) + ' EP')),
        epBar(p.ep, p.level_base, p.next_level))),
    h('div', { class: 'se-wallet' }, sell('credits', p.credits, T('Credits')), sell('uridium', p.uridium, T('Uridium')), sell('honor', p.honor, T('Honor'))),
    h('div', { class: 'se-values' }, value('hitpoints_100x100', 'heart', d.hp, d.max_hp), value('shield_100x100', 'shield', d.shield, d.shield_max),
      value('speed_100x100', 'gauge', g.value.speed), value('damage_laser_100x100', 'zap', g.value.damage)));
}

function seMenu(v) {
  const n = { hangar: v.ships.length, drones: v.drones.length, inventory: v.inventory.filter(e => !seIsEquipped(e)).length, boosters: v.boosters.length,
    sources: v.sources.length + v.ores.filter(c => c[2]).length, ammunition: v.ammunition.filter(c => c[1]).length };
  return h('nav', { class: 'card se-menu' }, SE_TABS.map(s => h('button', { class: s[0] === SE.tab ? 'on' : '', type: 'button',
    onclick: () => { if (SE.tab !== s[0]) { SE.tab = s[0]; $('#content').scrollTop = 0; seRender(); } } },
  seTabIcon(s, 20), h('span', null, T(s[1])), n[s[0]] ? h('span', { class: 'se-count' }, fmtN(n[s[0]])) : s[0] === 'pet' && !v.pet ? h('span', { class: 'se-count none' }, '—') : null)));
}

// ---- shared parts
const seCard = (title, iconEl, ...body) => h('div', { class: 'card se-card' }, title ? h('h2', null, icon(iconEl), title) : null, ...body);
function numberBox(value, update, { min = 0, max = null, cls = '' } = {}) {
  return h('input', { class: 'input num ' + cls, type: 'number', min, max, step: 1, value: value, disabled: SE.v.read_only,
    onchange: e => { const n = Math.round(+e.target.value); if (!Number.isFinite(n)) { e.target.value = value; return; }
      const x = Math.max(min, max != null ? Math.min(max, n) : n); if (x !== value) update(x); else e.target.value = value; },
    onkeydown: e => { if (e.key === 'Enter') e.target.blur(); } });
}
// slider: the track fills up to the handle (panel.css input[type=range] --p; min and max must be given before value)
function slider(props, cls = '') {
  const el = h('input', Object.assign({ type: 'range', class: 'se-range ' + cls }, props));
  const filler = () => el.style.setProperty('--p', (el.value - el.min) / Math.max(1e-9, el.max - el.min) * 100 + '%');
  el.addEventListener('input', filler);
  filler();
  return el;
}
// small plus/minus box: [−] n / max [+]
function stepBox(n, maximum, update, { min = 0 } = {}) {
  const ro = SE.v.read_only;
  return h('div', { class: 'se-stepper' }, h('button', { type: 'button', disabled: ro || n <= min, onclick: () => update(n - 1) }, icon('minus')),
    h('span', null, h('b', null, n), maximum != null ? ' / ' + maximum : ''), h('button', { type: 'button', disabled: ro || (maximum != null && n >= maximum), onclick: () => update(n + 1) }, icon('plus')));
}
function seShip(v) {
  let g = v.ships.find(x => x.id === SE.ship);
  if (!g) { g = v.ships.find(x => x.active) || v.ships[0]; SE.ship = g.id; }
  if (!g.configs[SE.config]) SE.config = g.active_config;
  return g;
}
// ship and config selection (Drones and P.E.T. equipment also live in the ship's config)
function shipPicker(v, g) {
  return h('div', { class: 'row wrap se-picker' }, h('span', { class: 'lbl' }, T('Ship')),
    h('select', { class: 'input', onchange: e => { SE.ship = e.target.value; SE.config = null; seRender(); } },
      v.ships.map(x => h('option', { value: x.id, selected: x.id === g.id }, itemName(x.lootId) + (x.active ? ' · ' + T('active') : '')))),
    h('div', { class: 'seg' }, Object.keys(g.configs).map(c => h('button', { class: c === SE.config ? 'on info' : '', onclick: () => { SE.config = c; seRender(); } },
      T('Config {0}', c), c === g.active_config ? ' •' : ''))));
}
const moveOp = (id, direction, tgt) => ({ operation: 'carry', direction, target: tgt.target, ship: SE.ship, config: +SE.config, drone: tgt.drone || 0, set: tgt.set || '', item: id });
const equipTarget = tgt => ({ target: tgt.target, ship: SE.ship, config: +SE.config, drone: tgt.drone || 0, set: tgt.set || '' });
const lvlBadge = e => [e.upgrade ? h('span', { class: 'se-badge-lv' }, '+' + e.upgrade) : null, e.level ? h('span', { class: 'se-badge-lv left' }, T('Lv {0}', e.level)) : null];

// button with an item icon: the tooltip reads the example's info (upgrade, random attributes, CPU allowance) from the button's _item
function seItemButton(props, e, ...kids) {
  const b = h('button', props, ...kids);
  b._item = SE.v.rights[e.lootId] ? Object.assign({}, e, { right: SE.v.rights[e.lootId] }) : e;
  return b;
}
const seIsEditable = e => !!(e.maximum || e.level || e.rng || SE.v.rights[e.lootId]);
function seCell(e, tgt) {
  return seItemButton({ class: 'se-cell full', type: 'button', onclick: ev => !SE.v.read_only && seItemMenu(ev.currentTarget, e, tgt) }, e,
    itemIcon(e.lootId, 44), ...lvlBadge(e));
}
const seEmptyCell = (tgt, iconEl = 'plus', title = T('Empty slot: equip')) => h('button', { class: 'se-cell vacant', type: 'button', title: title, disabled: SE.v.read_only,
  onclick: () => sePickEquip(tgt) }, icon(iconEl));
function seSlotBox(name, c, tgt, extra) {
  return h('div', { class: 'se-slot' + (c.items.length >= c.capacity && c.capacity ? ' filled' : '') },
    h('div', { class: 'se-slot-head' }, h('b', null, name), h('span', { class: 'row', style: { gap: '6px' } }, extra, h('span', { class: 'mono' }, c.items.length + ' / ' + c.capacity))),
    h('div', { class: 'se-cells' }, c.items.map(e => seCell(e, tgt)), Array.from({ length: Math.max(0, c.capacity - c.items.length) }, () => seEmptyCell(tgt))));
}
function seItemMenu(anchor, e, tgt) {
  popMenu(anchor, [
    { label: T('Unequip (to inventory)'), ic: 'download', fn: () => seApply(moveOp(e.id, 'kick', tgt)) },
    seIsEditable(e) ? { label: T('Edit…'), ic: 'edit', fn: () => seEdit(e) } : null,
    '-',
    { label: T('Unequip and delete'), ic: 'trash', danger: true, fn: () => seApply(moveOp(e.id, 'kick', tgt), { operation: 'delete', items: [e.id] }) },
  ].filter(Boolean));
}

// ---- item editing: upgrade level (Assembly), the level of the P.E.T. gear/protocol, the CPU's allowance and random attributes
// (unstable module: attributes fraction, ships, re-roll allowance; particle weapon: attributes percent, allowance, the cannon's star; QFC: linked
// ship, level, attributes percent). The game's range is written as a hint; the value is free. All in a single action list to the draft.
function seEdit(e) {
  const v = SE.v, pool = v.pools[e.lootId], r = e.rng || {}, right = v.rights[e.lootId], fraction = pool?.unit === 'fraction';
  const st = { upgrade: e.upgrade || 0, level: e.level, cpu: right ? right[0] : null, attribute: (r.attribute || []).map(([a, x]) => [a, fraction ? x * 100 : x]),
    ships: [...(r.ships || [])], ship: r.ship || v.ships.find(g => g.active)?.lootId, qlevel: r.level || 1, right: r.right ?? pool?.right, star: r.star || 0 };
  const sections = [], sortedShips = () => [...v.all_ships].sort((a, b) => itemName(a).localeCompare(itemName(b)));
  const title = (t, extra) => h('div', { class: 'row between' }, h('div', { class: 'lbl' }, t), extra ? h('span', { class: 'small dim' }, extra) : null);
  if (e.maximum) {
    const out = h('b', { class: 'se-lv-value' }, '+' + st.upgrade);
    sections.push(h('div', { class: 'se-edit' }, title(T('Upgrade level')), h('div', { class: 'se-lv-pick' }, out,
      h('div', { class: 'grow' }, slider({ min: 0, max: e.maximum, value: st.upgrade, oninput: x => { st.upgrade = +x.target.value; out.textContent = '+' + st.upgrade; } }),
        h('div', { class: 'row between small dim' }, h('span', null, '0'), h('span', null, '+' + e.maximum))))));
  }
  if (e.level) {
    const seg = h('div', { class: 'seg' });
    const render = () => seg.replaceChildren(...[1, 2, 3, 4].map(n => h('button', { class: n === st.level ? 'on info' : '', onclick: () => { st.level = n; render(); } }, T('Lv {0}', n))));
    render();
    sections.push(h('div', { class: 'se-edit' }, title(T('P.E.T. level')), seg));
  }
  if (right) sections.push(h('div', { class: 'se-edit' }, title(T('Charges left'), T('One refill gives {0} charges; charges are shared by every copy of this item.', fmtN(right[1]))),
    h('input', { class: 'input num', type: 'number', min: 0, value: st.cpu, oninput: x => { st.cpu = Math.max(0, Math.round(+x.target.value) || 0); } })));
  if (pool) {
    const lines = h('div', { class: 'se-attr' });
    const renderAttributes = () => lines.replaceChildren(...[...st.attribute.map((n, i) => h('div', { class: 'se-attr-row' },
      h('select', { class: 'input', onchange: x => { n[0] = x.target.value; renderAttributes(); } }, pool.attribute.map(a => h('option', { value: a, selected: a === n[0],
        disabled: a !== n[0] && st.attribute.some(m => m[0] === a) }, attributeName(a)))),
      h('label', { class: 'se-percent' }, h('input', { class: 'input num', type: 'number', min: 0, step: 0.1, value: Math.round(n[1] * 100) / 100,
        oninput: x => { n[1] = Math.max(0, +x.target.value || 0); } }), '%'),
      btn('', () => { st.attribute.splice(i, 1); renderAttributes(); }, 'ghost sm icon', 'x', { title: T('Remove') }))),
    st.attribute.length < pool.max_attributes ? btn(T('Add attribute'), () => {
      const a = pool.attribute.find(x => !st.attribute.some(m => m[0] === x)); if (a) { st.attribute.push([a, pool.interval[0]]); renderAttributes(); }
    }, 'sm ghost', 'plus') : null].filter(Boolean));
    renderAttributes();
    sections.push(h('div', { class: 'se-edit' }, title(T('Attributes'), T('In the game {0}–{1}%, up to {2} attributes', fmtN(pool.interval[0]), fmtN(pool.interval[1]), pool.max_attributes)),
      !e.rng?.attribute ? h('div', { class: 'small muted' }, T("The attributes haven't been rolled yet: Apply rolls them as the game does, then writes your values.")) : null, lines));
    if (pool.preference) {
      const chips = h('div', { class: 'se-ship-chips' });
      const add = h('select', { class: 'input', onchange: x => { if (x.target.value && !st.ships.includes(x.target.value)) st.ships.push(x.target.value); renderShip(); } });
      const renderShip = () => {
        chips.replaceChildren(...st.ships.map((g, i) => h('span', { class: 'chip' }, gameIcon(g, 22, companyLower(v.pilot.company), 'ship'), itemName(g),
          h('button', { class: 'btn ghost sm icon', type: 'button', onclick: () => { st.ships.splice(i, 1); renderShip(); } }, icon('x')))));
        add.replaceChildren(h('option', { value: '' }, T('Add ship…')), ...sortedShips().filter(g => !st.ships.includes(g))
          .map(g => h('option', { value: g }, (pool.preference.includes(g) ? '★ ' : '') + itemName(g))));
      };
      renderShip();
      sections.push(h('div', { class: 'se-edit' }, title(T('Ships it works on'), T('★ rolled more often in the game')), chips, add));
    }
    if (pool.max_level) {
      sections.push(h('div', { class: 'grid g2' },
        field(T('Bound ship'), h('select', { class: 'input', onchange: x => { st.ship = x.target.value; } },
          sortedShips().map(g => h('option', { value: g, selected: g === st.ship }, itemName(g))))),
        field(T('Level'), h('input', { class: 'input num', type: 'number', min: 1, max: pool.max_level, value: st.qlevel,
          oninput: x => { st.qlevel = Math.max(1, Math.min(pool.max_level, Math.round(+x.target.value) || 1)); } }))));
    }
    if (pool.right) {
      const k = h('span');
      const c = () => k.replaceChildren(stepBox(st.right, pool.right, n => { st.right = n; c(); }));
      c();
      sections.push(h('div', { class: 'se-edit line' }, h('div', { class: 'lbl' }, T('Rerolls left')), k));
    }
    if (pool.star) {
      const stars = h('div', { class: 'se-stars' });
      const c = () => stars.replaceChildren(...Array.from({ length: pool.star + 1 }, (_, n) => h('button', { type: 'button', class: n && n <= st.star ? 'on' : '',
        title: n ? '★'.repeat(n) : T('No stars'), onclick: () => { st.star = n; c(); } }, icon(n ? 'star' : 'x'))));
      c();
      sections.push(h('div', { class: 'se-edit line' }, h('div', { class: 'lbl' }, T('Stars')), stars));
    }
  }
  const m = modal({ title: T('Edit item'), sub: itemName(e.lootId), wide: !!pool,
    body: [h('div', { class: 'se-edit-head' }, itemIcon(e.lootId, 56), h('div', { class: 'small muted' }, T('Changes go to the draft; pressing Save writes them to the save.'))), ...sections],
    foot: [btn(T('Cancel'), () => m.close(), 'ghost'), btn(T('Apply'), async () => {
      const ops = [];
      if (e.maximum && st.upgrade !== (e.upgrade || 0)) ops.push({ operation: 'item_level', item: e.id, upgrade: st.upgrade });
      if (e.level && st.level !== e.level) ops.push({ operation: 'item_level', item: e.id, level: st.level });
      if (right && st.cpu !== right[0]) ops.push({ operation: 'cpu_charges', lootId: e.lootId, right: st.cpu });
      if (pool) {
        if (!st.attribute.length && e.rng?.attribute) return toast(T('At least one attribute is needed.'), 'err');
        const o = { operation: 'rng', item: e.id };
        if (st.attribute.length) o.attribute = st.attribute.map(([a, x]) => [a, fraction ? x / 100 : x]);
        if (pool.preference) { if (!st.ships.length) return toast(T('Pick at least one ship.'), 'err'); o.ships = st.ships; }
        if (pool.max_level) { o.ship = st.ship; o.level = st.qlevel; }
        if (pool.right) o.right = st.right;
        if (pool.star) o.star = st.star;
        ops.push(o);
      }
      if (!ops.length) return m.close();
      if (await seApply(...ops)) { m.close(); toast(T('Item updated (in the draft).'), 'ok'); }
    }, 'primary', 'check')] });
}

// groups the inventory: those with the same lootId and level in one box (count); those with random attributes (module, cannon, QFC) one by one
// item equipped somewhere (its ship and configs); the game lets another config of the same ship use it too
const seIsEquipped = e => !!(e.configs && e.configs.length);
const seIsUsable = e => !seIsEquipped(e) || (e.ship === SE.ship && !e.configs.includes(String(SE.config)));
function groupItems(entries) {
  const gr = {};
  for (const e of entries) { const k = [e.lootId, e.upgrade || 0, e.level || 0, e.rng ? e.id : ''].join('|'); (gr[k] = gr[k] || []).push(e); }
  return Object.values(gr).sort((a, b) => itemName(a[0].lootId).localeCompare(itemName(b[0].lootId)));
}
// put in an empty slot: those in the inventory that fit, or give from the catalog and put in
function sePickEquip(tgt) {
  const v = SE.v;
  const eligible = v.inventory.filter(e => seIsUsable(e) && (tgt.target === 'ship' ? e.targets.includes('ship') && e.slot === tgt.slot
    : tgt.target === 'drone' ? e.targets.includes('drone') && (tgt.slot === 'design') === (e.slot === 'design')
      : e.targets.includes('pet') && (tgt.slot === 'heat' ? e.heat : e.pet_slot === tgt.slot)))
    .sort((a, b) => seIsEquipped(b) - seIsEquipped(a));          // items of the other config first: free copies stay free
  const title = tgt.target === 'drone' ? (tgt.slot === 'design' ? T('Drone design') : T('Drone equipment')) : slotName(tgt.slot);
  const m = modal({ title: T('{0}: equip an item', title), wide: true, body: [
    eligible.length ? h('div', { class: 'se-selection' }, groupItems(eligible).map(gr => seItemButton({ class: 'se-selection-item', type: 'button',
      onclick: () => { m.close(); seApply(moveOp(gr[0].id, 'equip', tgt)); } }, gr[0], itemIcon(gr[0].lootId, 56), ...lvlBadge(gr[0]),
      h('span', { class: 'name' }, itemName(gr[0].lootId)), gr.length > 1 ? h('span', { class: 'se-qty' }, '×' + gr.length) : null)))
      : h('div', { class: 'empty' }, icon('box'), h('div', null, T('No item in the inventory fits here.'))),
    h('div', { class: 'se-selection-bottom' }, h('span', { class: 'small muted' }, T("If it isn't in the inventory, you can add it from the catalog and equip it here directly.")),
      btn(T('Add from catalog and equip'), () => { m.close(); seCatalog({ equip: tgt, title }); }, 'primary sm', 'plus'))],
  foot: [btn(T('Close'), () => m.close(), 'ghost')] });
}

// ---- catalog: everything that can be added, categories, search, count (the game's reward path)
async function seCatalog(o = {}) {
  if (!SE.catalog) { const r = await act(() => api('/api/editor/catalog')); if (!r) return; SE.catalog = r; }
  let entries = SE.catalog.items;
  if (o.equip) entries = entries.filter(([, , gy, py, dr]) => o.equip.target === 'ship' ? gy === o.equip.slot
    : o.equip.target === 'pet' ? (o.equip.slot === 'heat' ? py === 'lasers' || py === 'generators' : py === o.equip.slot) : dr && (o.equip.slot === 'design') === (gy === null && !py));
  if (o.on) entries = entries.filter(([l]) => l.startsWith(o.on));
  const tally = {}; for (const [, k] of entries) tally[k] = (tally[k] || 0) + 1;
  const categories = ['all', ...SE.catalog.categories.filter(k => tally[k])];
  const st = { multiplier: o.multiplier && tally[o.multiplier] ? o.multiplier : categories.length === 2 ? categories[1] : 'all', search: '', sec: null };
  const grid = h('div', { class: 'se-cat-grid' }), left = h('div', { class: 'se-cat-list' }), sub = h('div', { class: 'se-cat-bottom' });
  const search = h('input', { class: 'input', placeholder: T('Search: name or lootId…'), oninput: e => { st.search = e.target.value.trim().toLowerCase(); render(); } });
  const render = () => {
    left.replaceChildren(...categories.map(k => h('button', { class: k === st.multiplier ? 'on' : '', type: 'button', onclick: () => { st.multiplier = k; render(); } },
      icon(SE_CATEGORY_ICON[k] || 'box'), h('span', null, T(SE_CATEGORY[k] || k)), h('small', null, fmtN(k === 'all' ? entries.length : tally[k])))));
    const its = entries.filter(([l, k]) => (st.multiplier === 'all' || k === st.multiplier) && (!st.search || l.includes(st.search) || itemName(l).toLowerCase().includes(st.search)));
    const visible = its.slice(0, 300);
    // the selection only changes the class (if the grid were redrawn the scroll would go back to the top)
    const sec = (l, el) => { st.sec = l; grid.querySelectorAll('.se-cat-item.on').forEach(x => x.classList.remove('on')); el.classList.add('on'); renderSub(); };
    grid.replaceChildren(...[...visible.map(([l]) => h('button', { class: 'se-cat-item' + (st.sec === l ? ' on' : ''), type: 'button', title: l,
      onclick: e => sec(l, e.currentTarget), ondblclick: e => { sec(l, e.currentTarget); add(); } }, itemIcon(l, 52), h('span', null, itemName(l)))),
    its.length > visible.length ? h('div', { class: 'se-cat-more small muted' }, T('Showing the first {1} of {0} items: narrow the search.', fmtN(its.length), visible.length)) : null,
    !its.length ? h('div', { class: 'empty' }, T('No items.')) : null].filter(Boolean));
    grid.scrollTop = 0;
    renderSub();
  };
  const count = h('input', { class: 'input num', type: 'number', min: 1, value: 1 });
  const single = l => l.startsWith('ship_') || l.startsWith('drone_formation_');
  const renderSub = () => {
    if (!st.sec) return sub.replaceChildren(h('span', { class: 'small muted' }, o.equip ? T('Pick an item: it is granted and equipped straight into the slot.') : T('Pick an item (double-click adds it right away).')));
    sub.replaceChildren(...[itemIcon(st.sec, 48), h('div', { class: 'grow', style: { minWidth: 0 } }, h('b', null, itemName(st.sec)), h('div', { class: 'mono small dim' }, st.sec)),
      single(st.sec) ? null : h('label', { class: 'row small' }, T('Quantity'), count), btn(o.equip ? T('Grant and equip') : T('Add'), add, 'primary', 'plus')].filter(Boolean));
  };
  async function add() {
    if (!st.sec) return;
    const n = single(st.sec) ? 1 : Math.max(1, Math.round(+count.value) || 1), lid = st.sec;
    const ok = await seApply({ operation: 'give', items: [[lid, n]], equip: o.equip ? equipTarget(o.equip) : undefined });
    if (ok) { toast(T('Added: {0}', (n > 1 ? fmtN(n) + ' × ' : '') + itemName(lid)), 'ok'); if (o.equip) m.close(); }
  }
  const m = modal({ title: o.title ? T('Catalog: {0}', o.title) : T('Add item'), wide: true,
    sub: T("Items are granted through the game's reward path: ships to the hangar, equipment to the inventory, ammo and resources to their counters."),
    body: [h('div', { class: 'se-catalog' }, left, h('div', { class: 'se-cat-right' }, search, grid)), sub], foot: [btn(T('Close'), () => m.close(), 'ghost')] });
  m.box.classList.add('se-catalog-modal');
  render();
}

// ================================================================== SEKMELER
function sePilot(v) {
  const p = v.pilot, ro = v.read_only;
  const op = x => seApply(Object.assign({ operation: 'pilot' }, x));
  const name = h('input', { class: 'input', value: p.name, maxlength: 20, disabled: ro, onchange: e => e.target.value.trim() !== p.name && op({ name: e.target.value }) });
  const companies = h('div', { class: 'radio-cards' }, FIRMS.map(([id, k, n, c, m]) => h('div', { class: 'radio-card' + (id === p.company ? ' on' : ''), style: { '--c': c },
    onclick: async () => { if (ro || id === p.company) return;
      if (await confirmBox(T('Change company?'), T('{0} becomes a {1} pilot; the ship moves to the {2} home station.', p.name, k, m), { ok: T('Switch') })) op({ company: id }); } },
  art('firma_' + k.toLowerCase(), 'crest'), h('b', null, k), h('span', null, n))));
  const prem = h('input', { type: 'checkbox', checked: p.premium, disabled: ro, onchange: e => op({ premium: e.target.checked }) });
  const lvlLabel = h('b', null, p.level);
  const lv = h('div', { class: 'se-lv-edit' },
    h('div', { class: 'se-lv-large' }, h('button', { class: 'btn icon', type: 'button', disabled: ro || p.level <= 1, onclick: () => op({ level: p.level - 1 }) }, icon('minus')),
      h('div', null, h('small', null, T('Level')), lvlLabel),
      h('button', { class: 'btn icon', type: 'button', disabled: ro || p.level >= p.max_level, onclick: () => op({ level: p.level + 1 }) }, icon('plus'))),
    h('div', { class: 'grow' }, slider({ min: 1, max: p.max_level, value: p.level, disabled: ro,
      oninput: e => { lvlLabel.textContent = e.target.value; }, onchange: e => +e.target.value !== p.level && op({ level: +e.target.value }) }),
    h('div', { class: 'row between small dim' }, h('span', null, '1'), h('span', null, p.max_level))));
  const currency = (key, tag, n, fast) => h('div', { class: 'se-currency' }, art('source_' + key, 'se-currency-icon lg'),
    h('div', { class: 'grow' }, h('label', { class: 'lbl' }, tag), numberBox(n, x => op({ [key]: x }), { max: 1e12, cls: 'wide' })),
    h('div', { class: 'se-quick' }, fast.map(x => h('button', { class: 'chip', type: 'button', disabled: ro, onclick: () => op({ [key]: Math.min(1e12, n + x) }) }, '+' + fmtShort(x)))));
  return h('div', { class: 'stack' },
    h('div', { class: 'grid g2' },
      seCard(T('Identity'), 'user', field(T('Pilot name (shown in the game)'), name),
        h('label', { class: 'row small', style: { marginTop: '12px' } }, h('span', { class: 'switch' }, prem, h('span')), T('Premium membership'))),
      seCard(T('Level and honor'), 'star', lv,
        h('div', { class: 'grid g2', style: { marginTop: '12px' } },
          field(T('Experience (EP)'), numberBox(p.ep, x => op({ ep: x }), { max: 2 ** 53, cls: 'wide' })),
          field(T('Honor'), numberBox(p.honor, x => op({ honor: x }), { min: -1e12, max: 1e12, cls: 'wide' }))),
        h('div', { class: 'small dim', style: { marginTop: '8px' } }, p.next_level ? T('Next level at {0} EP.', fmtN(p.next_level)) : T('Highest level')))),
    seCard(T('Company'), 'globe', h('p', { class: 'desc' }, T("When the company changes, the ship moves to the new company's home station.")), companies),
    seCard(T('Wallet'), 'star', h('div', { class: 'grid g2' }, currency('credits', T('Credits'), p.credits, [1e6, 1e7, 1e8]), currency('uridium', T('Uridium'), p.uridium, [1e4, 1e5, 1e6]))),
    seCard(T('Account'), 'info', h('div', { class: 'kv' },
      h('div', null, T('Clan'), h('b', null, p.clan ? '[' + p.clan + ']' : '—')), h('div', null, T('Rank'), h('b', null, p.rank ?? '—')),
      h('div', null, T('Play time'), h('b', null, fmtDur(p.play_sec))), h('div', null, T('Created'), h('b', null, fmtWhen(p.created))),
      h('div', null, T('Uridium bank'), h('b', null, fmtN(p.bank))), h('div', null, T('Quests'), h('b', null, T('{0} taken · {1} completed', v.quests.active, v.quests.done))))));
}

function seHangar(v) {
  const g = seShip(v), ro = v.read_only, f = companyLower(v.pilot.company), cfg = g.configs[SE.config];
  const strip = h('div', { class: 'se-ships' }, v.ships.map(x => h('button', { class: 'se-ship' + (x.id === g.id ? ' on' : ''), type: 'button', title: itemName(x.lootId),
    onclick: () => { SE.ship = x.id; SE.config = null; seRender(); } }, shipImage(x.appearance, 62, f), h('span', { class: 'se-ship-name' }, itemName(x.lootId)),
  x.active ? h('span', { class: 'se-active' }, T('Active')) : null, x.favorite ? h('span', { class: 'se-star' }, icon('star')) : null)),
  ro ? null : h('button', { class: 'se-ship add', type: 'button', onclick: () => seCatalog({ multiplier: 'ship', title: T('Ships') }) },
    h('span', { class: 'se-add-icon' }, icon('plus')), h('span', { class: 'se-ship-name' }, T('Add ship'))));
  const value = (sp, iconEl, name, n) => h('div', { class: 'se-gauge' }, spr(sp, 26, iconEl), h('span', null, name), h('b', null, n == null ? '—' : fmtN(n)));
  const base = g.lootId.replace(/^ship_/, '');
  const designs = h('div', { class: 'se-designs' }, g.designs.map(t => h('button', { class: 'se-design' + (t === g.appearance ? ' on' : ''), type: 'button',
    title: itemName(t), disabled: ro, onclick: () => t !== g.appearance && seApply({ operation: 'design', ship: g.id, lootId: t }) }, shipImage(t, 46, f))),
  ro ? null : h('button', { class: 'se-design add', type: 'button', title: T('Add design'), onclick: () => seCatalog({ multiplier: 'design', on: 'ship_' + base + '_design_', title: T('{0} designs', itemName(g.lootId)) }) }, icon('plus')));
  const tools = h('div', { class: 'row wrap', style: { gap: '6px' } },
    g.active ? null : btn(T('Make active ship'), () => seApply({ operation: 'active_ship', ship: g.id }), 'sm primary', 'check', { disabled: ro }),
    SE.config !== g.active_config ? btn(T('Use this config'), () => seApply({ operation: 'config', ship: g.id, config: +SE.config }), 'sm', 'check', { disabled: ro }) : null,
    btn(g.favorite ? T('Remove from favourites') : T('Make favourite'), () => seApply({ operation: 'favorite', ship: g.id, favorite: !g.favorite }), 'sm', 'star', { disabled: ro }),
    btn(T('Transfer…'), () => seTransfer(v, g), 'sm', 'copy', { disabled: ro, title: T("Moves this ship's equipment to another ship.") }),
    btn(T('Clear'), async () => await confirmBox(T('Empty config {0}?', SE.config), T('Items on the ship, drones and P.E.T. go back to the inventory.'), { ok: T('Clear'), danger: true })
      && seApply({ operation: 'clean_up', ship: g.id, config: +SE.config }), 'sm', 'trash', { disabled: ro }),
    btn(T('Remove'), async () => await confirmBox(T('Remove {0}?', itemName(g.lootId)), T('The ship leaves the hangar; its equipment goes to the inventory. Until you save, Discard undoes it.'),
      { ok: T('Remove'), danger: true }) && seApply({ operation: 'delete_ship', ship: g.id }), 'sm danger', 'trash', { disabled: ro || g.active, title: g.active ? T("The active ship can't be removed: make another ship active first.") : '' }));
  return h('div', { class: 'stack' },
    h('div', { class: 'card se-card' }, strip),
    h('div', { class: 'card se-ship-card f-' + f },
      h('div', { class: 'se-ship-scene' }, shipImage(g.appearance, 230, f)),
      h('div', { class: 'se-ship-info' },
        h('div', { class: 'row wrap', style: { gap: '8px' } }, h('h2', { class: 'se-ship-title' }, itemName(g.lootId)),
          g.active ? badge(T('Active ship'), 'ok') : null, g.favorite ? badge(T('Favorite'), 'orange') : null),
        g.design ? h('div', { class: 'small muted' }, T('Look: {0}', itemName(g.design))) : null,
        h('div', { class: 'se-gauges' }, value('hitpoints_100x100', 'heart', T('Hit points'), g.value.hp), value('shield_100x100', 'shield', T('Shield'), g.value.shield),
          value('speed_100x100', 'gauge', T('Speed'), g.value.speed), value('damage_laser_100x100', 'zap', T('Laser damage'), g.value.damage), value(null, 'box', T('Cargo'), g.value.cargo)),
        g.designs.length > 1 || !ro ? h('div', null, h('div', { class: 'lbl', style: { marginBottom: '6px' } }, T('Look')), designs) : null,
        h('div', { class: 'seg' }, Object.keys(g.configs).map(c => h('button', { class: c === SE.config ? 'on info' : '', onclick: () => { SE.config = c; seRender(); } },
          T('Config {0}', c), c === g.active_config ? ' •' : ''))),
        tools)),
    h('div', { class: 'se-slots' }, g.slots.map(y => seSlotBox(slotName(y), cfg[y], { target: 'ship', slot: y }))));
}

function seTransfer(v, g) {
  let target = null;
  const entries = h('div', { class: 'se-ships sar' }, v.ships.filter(x => x.id !== g.id).map(x => h('button', { class: 'se-ship', type: 'button', onclick: ev => {
    target = x.id; entries.querySelectorAll('.se-ship').forEach(b => b.classList.toggle('on', b === ev.currentTarget)); } },
  shipImage(x.appearance, 54, companyLower(v.pilot.company)), h('span', { class: 'se-ship-name' }, itemName(x.lootId)))));
  const m = modal({ title: T('Transfer equipment'), sub: T('Both configs, drones and P.E.T. equipment of {0} move to the ship you choose.', itemName(g.lootId)), wide: true, body: [entries],
    foot: [btn(T('Cancel'), () => m.close(), 'ghost'), btn(T('Transfer'), () => { if (!target) return toast(T('Choose a ship.'), 'err'); m.close(); seApply({ operation: 'import_action', ship: g.id, target }); }, 'primary')] });
}

function seDrones(v) {
  const g = seShip(v), ro = v.read_only, dcfg = g.drones[SE.config] || {};
  const new_ = ['drone_flax', 'drone_iris', 'drone_apis', 'drone_zeus'].map(l => h('button', { class: 'se-drone-add', type: 'button', disabled: ro,
    title: T('Add {0}', itemName(l)), onclick: () => seApply({ operation: 'give', items: [[l, 1]] }) }, droneImage(l, 1, 40), h('span', null, itemName(l)), icon('plus')));
  const card = d => {
    const c = dcfg[d.id] || { items: [] }, tgt = { target: 'drone', drone: d.id }, tgtDesign = { target: 'drone', drone: d.id, slot: 'design' };
    const upgradeLabel = h('b', { class: 'se-lv-value sm' }, '+' + d.upgrade);
    return h('div', { class: 'card se-drone' },
      h('div', { class: 'se-drone-image' }, droneImage(d.lootId, d.level, 76)),
      h('div', { class: 'se-drone-body' },
        h('div', { class: 'row between' }, h('b', { class: 'se-drone-name' }, itemName(d.lootId)),
          btn('', async () => await confirmBox(T('Remove {0}?', itemName(d.lootId)), T('The drone is removed; its items go back to the inventory.'), { ok: T('Remove'), danger: true })
            && seApply({ operation: 'drone_delete', drone: d.id }), 'ghost sm icon', 'trash', { disabled: ro, title: T('Remove') })),
        h('div', { class: 'se-drone-row' }, h('span', { class: 'lbl' }, T('Level')),
          h('div', { class: 'se-pips' }, v.drone_levels.map((points, i) => h('button', { class: 'se-pip' + (i < d.level ? ' on' : ''), type: 'button', disabled: ro,
            title: T('Level {0} ({1} points)', i + 1, fmtN(points)), onclick: () => i + 1 !== d.level && seApply({ operation: 'drone', drone: d.id, level: i + 1 }) }))),
          h('span', { class: 'small dim' }, T('{0} points', fmtN(d.points)))),
        h('div', { class: 'se-drone-row' }, h('span', { class: 'lbl' }, T('Upgrades')),
          slider({ min: 0, max: d.max_upgrade, value: d.upgrade, disabled: ro,
            oninput: e => { upgradeLabel.textContent = '+' + e.target.value; }, onchange: e => seApply({ operation: 'drone', drone: d.id, upgrade: +e.target.value }) }), upgradeLabel),
        h('div', { class: 'se-cells' }, c.items.map(e => seCell(e, tgt)), Array.from({ length: Math.max(0, d.capacity - c.items.length) }, () => seEmptyCell(tgt)),
          h('span', { class: 'se-divider' }),
          c.design ? seCell(c.design, tgtDesign) : seEmptyCell(tgtDesign, 'wand', T('Design slot')),
          c.appearance ? seCell(c.appearance, tgtDesign) : seEmptyCell(tgtDesign, 'wand', T('Look slot')))));
  };
  return h('div', { class: 'stack' },
    h('div', { class: 'card se-card' }, h('div', { class: 'row wrap between', style: { gap: '12px' } }, shipPicker(v, g),
      h('span', { class: 'pill' }, icon('drone'), T('Drones'), ' ', h('b', null, v.drones.filter(d => !d.single).length + ' / ' + v.max_drones))),
    h('p', { class: 'desc', style: { margin: '10px 0 8px' } }, T("Equipment lives in the selected ship's selected config (as in the game, every ship has two configs).")),
    ro ? null : h('div', { class: 'se-drone-extras' }, new_)),
    v.drones.length ? h('div', { class: 'se-drones' }, v.drones.map(card)) : h('div', { class: 'card empty' }, icon('drone'), h('div', null, T('No drones.'))));
}

function sePet(v) {
  const p = v.pet, ro = v.read_only;
  if (!p) return h('div', { class: 'card se-pet-none' }, petImage(0, 150), h('div', null, h('h3', null, T('This pilot has no P.E.T.')),
    h('p', { class: 'muted' }, T('Grant a P.E.T.: it comes at level 0 with starting fuel and slots; then you can set its level and slots here.')),
    btn(T('Grant P.E.T.'), () => seApply({ operation: 'pet', give: true }), 'primary', 'plus', { disabled: ro })));
  const g = seShip(v), pc = (g.pet || {})[SE.config] || {};
  const op = x => seApply(Object.assign({ operation: 'pet' }, x));
  const lvlLabel = h('b', null, p.level), fuelLabel = h('b', { class: 'mono' }, fmtN(p.fuel));
  const name = h('input', { class: 'input', value: p.name || '', maxlength: 24, disabled: ro, onchange: e => e.target.value.trim() && e.target.value.trim() !== p.name && op({ name: e.target.value }) });
  return h('div', { class: 'stack' },
    h('div', { class: 'card se-pet' },
      h('div', { class: 'se-pet-scene' }, h('div', { class: 'se-ring' }), petImage(p.level, 190)),
      h('div', { class: 'se-pet-body stack', style: { gap: '14px' } },
        h('div', { class: 'row wrap', style: { gap: '8px' } }, h('h2', { class: 'se-ship-title' }, p.name || 'P.E.T.'), p.destroyed ? badge(T('Destroyed'), 'err') : badge(T('Ready'), 'ok'),
          p.heat ? badge('HEAT ' + p.heat, 'orange') : null),
        field(T('Name'), name),
        h('div', { class: 'se-lv-edit' },
          h('div', { class: 'se-lv-large' }, h('button', { class: 'btn icon', type: 'button', disabled: ro || p.level <= 0, onclick: () => op({ level: p.level - 1 }) }, icon('minus')),
            h('div', null, h('small', null, T('Level')), lvlLabel),
            h('button', { class: 'btn icon', type: 'button', disabled: ro || p.level >= p.max_level, onclick: () => op({ level: p.level + 1 }) }, icon('plus'))),
          h('div', { class: 'grow' }, slider({ min: 0, max: p.max_level, value: p.level, disabled: ro,
            oninput: e => { lvlLabel.textContent = e.target.value; }, onchange: e => +e.target.value !== p.level && op({ level: +e.target.value }) }),
          h('div', { class: 'row between small dim' }, h('span', null, '0'), h('span', null, T('{0} EP', fmtN(p.ep))), h('span', null, p.max_level)))),
        h('div', null, h('div', { class: 'row between' }, h('span', { class: 'lbl' }, T('Fuel')), h('span', null, fuelLabel, h('span', { class: 'dim' }, ' / ' + fmtN(p.max_fuel)))),
          slider({ min: 0, max: p.max_fuel, step: 100, value: p.fuel, disabled: ro,
            oninput: e => { fuelLabel.textContent = fmtN(+e.target.value); }, onchange: e => op({ fuel: +e.target.value }) }, 'fuel')),
        p.destroyed ? btn(T('Repair'), () => op({ repair: true }), 'sm primary', 'wrench', { disabled: ro }) : null)),
    seCard(T('Open slots'), 'layers', h('p', { class: 'desc' }, T("Slots unlocked with uridium in the game; you can't go below what the level gives.")),
      h('div', { class: 'se-pet-slots' }, Object.keys(p.max_slots).filter(y => y !== 'heat').map(y => h('div', { class: 'se-pet-slot' }, h('span', null, slotName(y)),
        stepBox(p.slot[y] || 0, p.max_slots[y], n => op({ slot: { [y]: n } })))))),
    h('div', { class: 'card se-card' }, h('div', { class: 'row wrap between', style: { gap: '12px' } }, h('h2', { style: { margin: 0 } }, icon('box'), T('Equipment')), shipPicker(v, g)),
      h('div', { class: 'se-slots', style: { marginTop: '12px' } }, v.pet_slots.filter(y => pc[y] && (pc[y].capacity || pc[y].items.length))
        .map(y => seSlotBox(slotName(y), pc[y], { target: 'pet', slot: y, set: y === 'heat' ? 'heat' : '' })))));
}

function seInventory(v) {
  const g = seShip(v), ro = v.read_only;
  const empty = v.inventory.filter(e => !seIsEquipped(e));          // inventory tab: only items equipped nowhere (delete, edit)
  const kinds = [...new Set(empty.map(e => e.slot))];
  if (SE.invKind !== 'all' && !kinds.includes(SE.invKind)) SE.invKind = 'all';
  const q = SE.search.toLowerCase();
  const entries = empty.filter(e => (SE.invKind === 'all' || e.slot === SE.invKind) && (!q || itemName(e.lootId).toLowerCase().includes(q) || e.lootId.includes(q)));
  const grid = h('div', { class: 'se-inv' }, groupItems(entries).map(gr => {
    const e = gr[0];
    return seItemButton({ class: 'se-inv-item', type: 'button', onclick: ev => !ro && popMenu(ev.currentTarget, [
      e.targets.includes('ship') ? { label: T('Equip on the selected ship ({0}, config {1})', itemName(g.lootId), SE.config), ic: 'download', fn: () => seApply(moveOp(e.id, 'equip', { target: 'ship' })) } : null,
      seIsEditable(e) ? { label: T('Edit…'), ic: 'edit', fn: () => seEdit(e) } : null,
      '-',
      { label: T('Delete one'), ic: 'trash', danger: true, fn: () => seApply({ operation: 'delete', items: [e.id] }) },
      gr.length > 1 ? { label: T('Delete all ({0})', gr.length), ic: 'trash', danger: true, fn: () => seApply({ operation: 'delete', items: gr.map(x => x.id) }) } : null,
    ].filter(Boolean)) }, e, itemIcon(e.lootId, 54), ...lvlBadge(e), gr.length > 1 ? h('span', { class: 'se-qty' }, '×' + gr.length) : null, h('span', { class: 'name' }, itemName(e.lootId)));
  }));
  return h('div', { class: 'stack' },
    h('div', { class: 'card se-card' }, h('div', { class: 'row wrap', style: { gap: '10px' } },
      h('input', { class: 'input game-search', placeholder: T('Search…'), value: SE.search, oninput: e => seSearch(e, v => { SE.search = v; }) }),
      h('span', { class: 'spacer' }), ro ? null : btn(T('Add item'), () => seCatalog({}), 'primary sm', 'plus')),
    kinds.length > 1 ? h('div', { class: 'seg', style: { marginTop: '12px', flexWrap: 'wrap' } }, ['all', ...kinds].map(t => h('button', { class: t === SE.invKind ? 'on info' : '',
      onclick: () => { SE.invKind = t; seRender(); } }, t === 'all' ? T('All') : t === 'design' ? T('Drone designs') : slotName(t)))) : null),
    entries.length ? h('div', { class: 'card se-card' }, grid) : h('div', { class: 'card empty' }, icon('box'), h('div', null, empty.length ? T('No items match the search.') : T('Inventory is empty: everything is equipped.'))));
}

function seAmmo(v) {
  const ro = v.read_only, groups = {};
  for (const c of v.ammunition) if (!SE.ammoFilled || c[1]) (groups[c[2]] = groups[c[2]] || []).push(c);
  const box = ([l, n]) => h('div', { class: 'se-pocket' + (n ? '' : ' zero') }, itemIcon(l, 44), h('div', { class: 'grow', style: { minWidth: 0 } },
    h('div', { class: 'se-pocket-name', title: l }, itemName(l)), numberBox(n, x => seApply({ operation: 'ammunition', counts: { [l]: x } }), { max: 1e12, cls: 'wide' })));
  const bulkSet = async entries => { const s = await promptBox(T('Same amount for all'), T('Quantity'), '100000'); if (s == null) return;
    const n = Math.max(0, Math.round(+s) || 0); seApply({ operation: 'ammunition', counts: Object.fromEntries(entries.map(c => [c[0], n])) }); };
  const full = h('input', { type: 'checkbox', checked: SE.ammoFilled, onchange: e => { SE.ammoFilled = e.target.checked; seRender(); } });
  return h('div', { class: 'stack' },
    h('div', { class: 'card se-card row wrap', style: { gap: '14px' } }, h('label', { class: 'row small' }, h('span', { class: 'switch' }, full, h('span')), T("Show only what's in stock")),
      h('span', { class: 'spacer' }), h('span', { class: 'small muted' }, T('{0} types in total, {1} in stock.', v.ammunition.length, v.ammunition.filter(c => c[1]).length))),
    ...SE_AMMO.filter(([k]) => groups[k]).map(([k, name]) => seCard(null, null,
      h('div', { class: 'row between', style: { marginBottom: '12px' } }, h('h2', { style: { margin: 0 } }, icon('ammo'), T(name)),
        ro ? null : btn(T('Same amount for all…'), () => bulkSet(groups[k]), 'sm ghost', 'edit')),
      h('div', { class: 'se-pockets' }, groups[k].map(box)))));
}

function seResources(v) {
  const ro = v.read_only, d = v.state, q = SE.resourceSearch.toLowerCase();
  const ore = ([t, l, n]) => h('div', { class: 'se-pocket' + (n ? '' : ' zero') }, itemIcon(l, 44), h('div', { class: 'grow', style: { minWidth: 0 } },
    h('div', { class: 'se-pocket-name' }, itemName(l)), numberBox(n, x => seApply({ operation: 'ore', counts: { [t]: x } }), { max: 1e9, cls: 'wide' })));
  const sources = v.sources.filter(([l]) => !q || l.includes(q) || itemName(l).toLowerCase().includes(q));
  return h('div', { class: 'stack' },
    seCard(null, null, h('div', { class: 'row between', style: { marginBottom: '12px' } }, h('h2', { style: { margin: 0 } }, icon('gem'), T('Ores')),
      h('span', { class: 'pill' }, icon('box'), T('Cargo'), ' ', h('b', null, fmtN(d.cargo) + ' / ' + fmtN(d.cargo_max)))),
    h('div', { class: 'se-pockets' }, v.ores.map(ore))),
    seCard(null, null, h('div', { class: 'row wrap between', style: { gap: '10px', marginBottom: '12px' } }, h('h2', { style: { margin: 0 } }, icon('gift'), T('Collectibles and other resources')),
      h('div', { class: 'row', style: { gap: '8px' } }, h('input', { class: 'input game-search', placeholder: T('Search…'), value: SE.resourceSearch,
        oninput: e => seSearch(e, v => { SE.resourceSearch = v; }) }),
      ro ? null : btn(T('Add resource'), () => seCatalog({ multiplier: 'source', title: T('Resources') }), 'primary sm', 'plus'))),
    sources.length ? h('div', { class: 'se-pockets' }, sources.map(([l, n]) => h('div', { class: 'se-pocket' }, itemIcon(l, 44), h('div', { class: 'grow', style: { minWidth: 0 } },
      h('div', { class: 'se-pocket-name', title: l }, itemName(l)), h('div', { class: 'row', style: { gap: '4px' } }, numberBox(n, x => seApply({ operation: 'source', counts: { [l]: x } }), { max: 1e12, cls: 'wide' }),
        ro ? null : btn('', () => seApply({ operation: 'source', counts: { [l]: 0 } }), 'ghost sm icon', 'x', { title: T('Remove') }))))))
      : h('div', { class: 'empty' }, T('No resources.'))));
}

function seBoosters(v) {
  const ro = v.read_only;
  const row = ([l, sec]) => {
    const hour = h('input', { class: 'input num', type: 'number', min: 0, step: 0.5, value: Math.round(sec / 360) / 10, disabled: ro,
      onchange: e => { const s = Math.max(0, Math.round((+e.target.value || 0) * 3600)); if (s !== sec) seApply({ operation: 'booster', durations: { [l]: s } }); } });
    return h('div', { class: 'se-boost' }, itemIcon(l, 48), h('div', { class: 'grow', style: { minWidth: 0 } }, h('b', null, itemName(l)), h('div', { class: 'small muted' }, T('{0} left', fmtDur(sec)))),
      h('label', { class: 'row small' }, hour, T('hours')), ro ? null : btn('', () => seApply({ operation: 'booster', durations: { [l]: 0 } }), 'ghost sm icon', 'x', { title: T('Remove') }));
  };
  return h('div', { class: 'stack' },
    h('div', { class: 'card se-card row wrap', style: { gap: '10px' } }, h('span', { class: 'small muted grow' }, T('A booster granted from the editor works like one dropped by an alien: it only runs while the game is on.')),
      ro ? null : btn(T('Add booster'), () => seCatalog({ multiplier: 'booster', title: T('Boosters') }), 'primary sm', 'plus')),
    v.boosters.length ? h('div', { class: 'card se-card se-boosts' }, v.boosters.map(row)) : h('div', { class: 'card empty' }, icon('zap'), h('div', null, T('No active boosters.'))));
}

function seMaintenance(v) {
  const ro = v.read_only, d = v.state;
  const row = (iconEl, title, description, ...button) => h('div', { class: 'se-maintenance' }, h('span', { class: 'se-maintenance-icon' }, icon(iconEl)),
    h('div', { class: 'grow' }, h('b', null, title), h('div', { class: 'small muted' }, description)), ...button);
  const boxes = Object.fromEntries(SE_RESET.map(([k]) => [k, h('input', { type: 'checkbox', disabled: ro })]));
  return h('div', { class: 'stack' },
    seCard(T('Ship and location'), 'wrench',
      row('heart', T('Repair ship'), T('HP {0} / {1}, shield {2} / {3}.', fmtN(d.hp), fmtN(d.max_hp), fmtN(d.shield), fmtN(d.shield_max)),
        btn(T('Repair'), () => seApply({ operation: 'repair' }), 'sm', 'wrench', { disabled: ro || (d.hp >= d.max_hp && d.shield >= d.shield_max) })),
      row('map', T('Move to home station'), T("Now on {0}; the company's home map is {1}. Use it if you got stuck on a map.", d.map_name, d.main_map),
        btn(T('Move'), () => seApply({ operation: 'home_base' }), 'sm', 'map', { disabled: ro })),
      row('sliders', T('Key bindings'), T("Back to default (the in-game Settings > Reset doesn't reach the server)."),
        btn(T('Reset to default'), async () => await confirmBox(T('Reset key bindings to default?'), T('Your own key bindings are deleted.'), { ok: T('Revert') }) && seApply({ operation: 'keybinds' }),
          'sm', 'undo', { disabled: ro }))),
    seCard(T('Reset state'), 'refresh', h('div', { class: 'stack', style: { gap: '8px' } },
      SE_RESET.map(([k, t]) => h('label', { class: 'row small' }, h('span', { class: 'switch' }, boxes[k], h('span')), T(t)))),
    h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '12px' } }, btn(T('Reset selected'), () => {
      const b = SE_RESET.map(([k]) => k).filter(k => boxes[k].checked);
      if (!b.length) return toast(T('Pick something to reset.'), 'err');
      seApply({ operation: 'reset', sections: b });
    }, 'sm', 'refresh', { disabled: ro }))),
    h('div', { class: 'small dim' }, T('All changes stay in a draft first; pressing Save writes them to the save and backs up its previous state.')));
}

const SE_RENDER = { pilot: sePilot, hangar: seHangar, drones: seDrones, pet: sePet, inventory: seInventory, ammunition: seAmmo, sources: seResources,
  boosters: seBoosters, maintenance: seMaintenance, stats: seStats };

// Statistics (read-only; save_editor.stats): rank points, kills, deaths, gates and their times, best results of the modes
const SE_POINTS = [['ExperiencePoints', N('Experience (EP)')], ['honorPoints', N('Honor')], ['yourLevel', N('Level')], ['npcShotPoints', N('Alien points')],
  ['playerShotPoints', N('Player points')], ['missionsCompleted', N('Quests finished')], ['daysSinceRegistration', N('Days since registration')],
  ['DestroyedByEnemies', N('Destroyed by enemies')], ['DestroyedByRadiationZone', N('Radiation deaths')], ['friendlyPlayersDestroyed', N('Friendly kills')]];
const seDuration = sec => sec ? (sec >= 3600 ? Math.floor(sec / 3600) + ':' : '') + String(Math.floor(sec / 60) % 60).padStart(sec >= 3600 ? 2 : 1, '0') + ':' + String(sec % 60).padStart(2, '0') : '—';
function seStats(v) {
  const s = v.stats || {}, p = s.points || {};
  const table = (titles, lines, empty) => lines.length ? h('div', { class: 'bt-table' }, h('table', { class: 'table' },
    h('thead', null, h('tr', null, titles.map(x => h('th', null, x)))), h('tbody', null, lines)))
    : h('div', { class: 'small muted' }, empty);
  return h('div', { class: 'stack' },
    seCard(T('Rank points'), 'star', h('div', { class: 'row wrap', style: { gap: '8px', marginBottom: '8px' } },
      badge(T('Rank points') + ': ' + fmtN(p.rankPoints || 0), 'info'), badge(T('Time played') + ': ' + fmtDur(s.play_sec || 0), '')),
      h('div', { class: 'se-stats' }, SE_POINTS.map(([k, name]) => h('div', { class: 'row' }, h('span', { class: 'grow muted' }, T(name)), h('b', null, fmtN(p[k] || 0)))))),
    seCard(T('Gates'), 'globe', table([T('Gate'), T('Completions'), T('Best time'), T('Last time')],
      (s.gates || []).map(k => h('tr', null, h('td', null, k.name), h('td', { class: 'num' }, fmtN(k.done)), h('td', { class: 'num' }, seDuration(k.best)), h('td', { class: 'num' }, seDuration(k.last)))),
      T('No gates completed yet.')),
      h('div', { class: 'small muted', style: { marginTop: '6px' } }, T('Time runs from entering the first wave to completion; gates finished before this version have no time.'))),
    seCard(T('Destroyed aliens'), 'zap', table([T('Aliens'), T('Count'), T('Points')],
      (s.npc || []).map(([name, n, pts]) => h('tr', null, h('td', null, name), h('td', { class: 'num' }, fmtN(n)), h('td', { class: 'num' }, fmtN(pts * n)))), T('No aliens destroyed yet.'))),
    seCard(T('Players and deaths'), 'shield', h('div', { class: 'se-stats' },
      [[T('Destroyed by enemies'), (s.death || {}).enemy], [T('Radiation deaths'), (s.death || {}).radiation], [T('Other deaths'), (s.death || {}).other],
       [T('Friendly kills'), s.friendly], [T('Quests finished'), s.quest], [T('Eternal Black Light best wave'), (s.modes || {}).ebl],
       [T('Frozen Labyrinth hunts'), (s.modes || {}).labyrinth], [T('Mimesis best run'), (s.modes || {}).mimesis]]
        .map(([name, n]) => h('div', { class: 'row' }, h('span', { class: 'grow muted' }, name), h('b', null, fmtN(n || 0))))),
      table([T('Ship'), T('Killed')], (s.player || []).map(([name, n]) => h('tr', null, h('td', null, name), h('td', { class: 'num' }, fmtN(n)))), T('No players destroyed yet.'))));
}

// ---- summary of changes, save, discard
function seChanges() {
  const f = SE.v.diff, ro = SE.v.read_only;
  const value = (k, x) => x == null ? '—' : k === 'company' ? COMPANY_TAG[x] || x : k === 'active_ship' ? itemName(x) : k === 'premium' ? (x ? T('On') : T('Off'))
    : typeof x === 'number' ? fmtN(x) : String(x);
  const section = (title, ...contents) => contents.flat().filter(Boolean).length ? h('div', { class: 'se-diff' }, h('div', { class: 'lbl' }, title), ...contents) : null;
  const items = (o, cls) => Object.keys(o).length ? h('div', { class: 'se-diff-items' }, Object.entries(o).map(([l, n]) => h('div', { class: 'se-diff-item ' + cls },
    itemIcon(l, 32), h('span', null, itemName(l)), h('b', null, (cls === 'added' ? '+' : '−') + fmtN(n))))) : null;
  const m = modal({ title: T('Unsaved changes'), sub: T('Pressing Save writes these to the save; its previous state is kept as a "Before restore" backup.'), wide: true,
    body: [
      section(T('Values'), f.fields.map(([k, a, b]) => h('div', { class: 'se-diff-field' }, h('span', null, T(SE_FIELD[k] || k)), h('s', null, value(k, a)), icon('arrowR'), h('b', null, value(k, b))))),
      section(T('Added items'), items(f.added, 'added')),
      section(T('Removed items'), items(f.leaving, 'removed')),
      section(T('Amounts'), f.counts.map(([l, a, b]) => h('div', { class: 'se-diff-field' }, h('span', { class: 'row', style: { gap: '8px' } }, itemIcon(l, 26), itemName(l)), h('s', null, fmtN(a)), icon('arrowR'), h('b', null, fmtN(b))))),
      section(T('Boosters'), f.boosters.length ? h('div', { class: 'small' }, f.boosters.map(itemName).join(', ')) : null),
      section(T('Levels'), f.levels.length ? h('div', { class: 'small' }, [...new Set(f.levels)].map(l => l === 'pet' ? 'P.E.T.' : itemName(l)).join(', ')) : null),
      section(T('Equipment'), f.hardware ? h('div', { class: 'small' }, T('{0} items changed place (equipped, unequipped or moved).', f.hardware)) : null),
      !f.number ? h('div', { class: 'empty' }, T('No changes.')) : null],
    foot: [btn(T('Close'), () => m.close(), 'ghost'), ro ? null : btn(T('Cancel'), () => { m.close(); seCancel(); }, 'danger', 'undo', { disabled: !f.number }),
      ro ? null : btn(T('Save'), () => { m.close(); seSave(); }, 'primary', 'save', { disabled: !f.number })] });
}

async function seSave() {
  const r = await act(() => api('/api/editor/save', { id: SE.slot }), T('Saved. The previous state was backed up.'));
  if (r && SE.slot) { SE.v = null; renderEditor(); }
}
async function seCancel() {
  const n = SE.v?.diff?.number || 0;
  if (!await confirmBox(T('Discard the changes?'), T('The {0} changes in the draft are deleted; the save stays as it is.', n), { ok: T('Discard'), danger: true })) return;
  const r = await act(() => api('/api/editor/discard', { id: SE.slot }), T('Changes discarded.'));
  if (r && SE.slot) { SE.v = null; renderEditor(); }
}
