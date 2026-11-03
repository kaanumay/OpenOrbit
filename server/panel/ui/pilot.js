/* Auto Mode page (In-game section, Beta): the server flies your ship (server/pilot/). Settings go to /api/pilot (pilot_panel.py, pilot.json
   next to the save); the bot's status, with the live map, comes back from the game server every second. Loaded after panel.js: it adds its
   own entry to PAGES, RENDER and the In-game pages' tab bar (GAME_PAGES). Kept in its own files (this one and pilot.css): a local feature.
   Layout, top to bottom:
     - the In-game bar (gameHeader);
     - the command bar: the four modes as tiles, Start/Stop, one line of what the ship is doing (pilCommand);
     - the tactical map (PILM: a canvas drawn every frame from the last status, the marks eased between two statuses; zoom, pan, follow the
       ship, layers as legend chips, the work area / areas to avoid drawn on it, a click on an alien or a portal for its actions) and the
       rail beside it: ship, target, session with its curves, journal (pilRail);
     - the settings in tabs (PIL_TABS): the first one is the chosen mode's ('mode:<mode>' cards), the others are shared. Every card is an
       entry of PILC ({id, tab (or a list of tabs), order, build}).
   Settings: every field edits one setting by its path ('flee_hp', 'pet.gear') and sends only that value; the panel merges a card's value
   into its block (pilot_panel.py). A poll that started before a save does not overwrite it (PIL.seq). */
'use strict';

Object.assign(ICONS, {
  cursor: '<path d="M5 3l6.5 17 2.4-7.1L21 10.5z"/>',
  area: '<path d="M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5"/><rect x="8" y="8" width="8" height="8" rx="1"/>',
  ban: '<circle cx="12" cy="12" r="9"/><line x1="5.7" y1="5.7" x2="18.3" y2="18.3"/>',
  eraser: '<path d="M7 21h13"/><path d="M5.5 15.5 14 7l5 5-8.5 8.5H8z"/><path d="M10.5 10.5l5 5"/>',
  fit: '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
});
if (!ICONS.bot) ICONS.bot = '<rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 8V4"/><circle cx="12" cy="3" r="1"/><circle cx="9" cy="14" r="1.2" fill="currentColor"/><circle cx="15" cy="14" r="1.2" fill="currentColor"/><path d="M2 13v3M22 13v3"/>';
PAGES.push({ id: 'pilot', name: N('Auto Mode'), ic: 'bot', game: true, beta: true, sub: N('The server flies your ship: it fights aliens at the edge of your laser range, collects boxes and repairs at low HP.') });
GAME_PAGES.push(['pilot', N('Auto Mode'), '', 'bot']);
RENDER.pilot = () => renderPilot();

const PIL = { data: null, cat: {}, tab: null, seq: 0, timer: null, polling: false, aliensSig: '', alienNames: {}, els: null, journal: 0 };
const PILC = [];           // settings cards: {id, tab, order, build}
// the modes: name, icon, the game's sprite on its tile, one line under the name
const PIL_MODES = {
  hunt: { name: N('Hunt'), ic: 'search', sp: 'npc_71_icon', sub: N('Aliens and boxes on your maps') },
  gate: { name: N('Galaxy gate'), ic: 'star', sp: 'icon_gate', sub: N('Plays a gate wave by wave') },
  quest: { name: N('Quests'), ic: 'note', sp: 'homestation_questgiver', sub: N('Follows your active quests') },
  mining: { name: N('Mining'), ic: 'cart', sp: 'resource_ore_promerium', sub: N('Harvests ore and sells it') },
};
// 'mode' is the chosen mode's tab (its name and icon come from PIL_MODES)
const PIL_TABS = [['mode', '', ''], ['combat', N('Combat'), 'play'], ['support', N('Support'), 'zap'], ['safety', N('Safety'), 'shield'],
  ['settings', N('Settings'), 'sliders']];
const PIL_STATE = { off: N('Stopped'), running: N('Running'), paused: N('Paused') };
const PIL_MODE = {
  fight: N('Fighting'), box: N('Collecting a box'), roam: N('Patrolling'), gate: N('Going to the next wave'), flee: N('Going to a safe zone'),
  repair: N('Repairing'), idle: N('Waiting'), travel: N('Flying to the hunting map'), home: N('Going to the base before stopping'), sell: N('Going to sell the cargo'),
  ore: N('Harvesting ore'), hide: N('Hiding from an enemy pilot'), quest: N('Going to a quest giver'), gate_trip: N('Going to the galaxy gate'),
  quest_point: N("Flying to the quest's point"), quest_trade: N('Going to the 5-2 trader'),
};
const PIL_REASON = {
  dead: N('Your ship is destroyed.'), jumping: N('Jumping through a portal.'), manual: N('You moved the ship: resuming in {0} s.'),
  client_autopilot: N("The game's own autopilot (Omega AutoTactic) is on: switch it off (F12)."), no_repair_robot: N('No repair robot: waiting in the safe zone.'),
};
const PIL_STOP = {
  time: N('Time limit reached.'), kills: N('Number of aliens reached.'), ammo: N('Out of laser ammo.'), dead: N('Ship destroyed (no repair left).'),
  players: N('Enemy pilot nearby.'), gate_done: N('Galaxy gate completed.'), gate_not_built: N('The galaxy gate is not built.'),
  gate_lives: N('No life left for the galaxy gate.'), gate_lives_low: N("The gate's lives fell to the limit set: the gate is kept for later."), gate_no_route: N('No route to the galaxy gate.'), gate_none: N('No galaxy gate chosen.'),
  no_quest: N('No quest to play.'), quest_done: N('The chosen quest is done.'), quest_gone: N('The chosen quest is no longer accepted.'),
};
// the journal's lines: the server sends the English template and its values (server/pilot, Pilot.note); each one is listed here so the
// panel's languages carry it (test_pilot checks that every server template is here)
const PIL_NOTES = [N('Started in {0} mode.'), N('Stopped.'), N('Stopped: {0}'), N('Stopping: {0} Flying to the base first.'), N('{0} mode chosen.'),
  N('{0} mode: {1} Switching to {2}.'), N('Repaired: back to work.'), N('Low HP ({0} %): going to a safe zone.'),
  N('No safe zone on this map: flying away from the aliens.'), N('Wave cleared: going to the next wave portal.'),
  N('{0} took no damage for {1} s: left alone for a while.'), N('Could not take a box: skipped.'), N('Cargo full but no station within reach.'),
  N('Cargo sold: {0} credits.'), N('Could not buy {0} (budget or money).'), N('Bought {0} {1} for {2} credits.'), N('Bought {0} {1} for {2} uridium.'),
  N('{0}: life bought ({1} U).'), N('{0} completed: playing it again.'), N('{0}: {1}/{2} parts, the gate cannot be prepared.'), N('{0} prepared.'),
  N('Entering the {0}.'), N('Enemy pilot nearby: {0}.'), N('Leaving the map for {0}.'), N('Enemy pilot nearby but no safe zone on this map: carrying on.'),
  N('Quest: {0} ({1}).'), N('No quest to play.'), N('Quest handed in: {0}.'), N('Quest taken: {0}.'), N('No quest to take here.'), N('Ship destroyed.'),
  N('Repaired at the base ({0}/{1}).'), N('Used {0}.'), N('Shield low: switched to config {0}.'), N('P.E.T. repaired ({0} U).'), N('P.E.T. launched.'),
  N('No route to {0}: staying here.'), N('Flying to {0}.'), N('Nothing left to do here: on to {0}.'),
  N('{0}: {1}/{2} parts ({3} U spent on spins).'), N('Shield low ({0} %): SAB-50 on the shielded aliens.'), N('Shield back to {0} %: normal ammo.'),
  N("{0} is inside an immobile alien\'s zone: drawing it out."), N('{0} did not follow: out of the zone, another try.'),
  N("{0} does not leave the immobile alien\'s zone: left alone for a while."), N("{0} is inside an immobile alien\'s zone: HP too low to draw it out.")];
const PIL_QKIND = { q_kill: N('aliens to destroy'), q_visit: N('a map to visit'), q_giver: N('back to the quest giver'),
  q_point: N('a point to reach'), q_travel: N('a distance to fly'), q_stay: N('time to spend on a map'), q_boxes: N('bonus boxes to collect'),
  q_ore: N('ore to collect'), q_grind: N('any aliens to destroy'), q_gate: N('a galaxy gate'), q_pvp: N('enemy pilots'),
  q_act: N('an action (laboratory, slot bar, Skylab, Assembly)'), q_asset: N('a station object to visit'), q_egate: N('the starter gate'),
  q_die: N('losing the ship'), q_mine: N('mines to lay') };
const PIL_WHEN = [['hp', N('HP below (%)')], ['shield', N('Shield below (%)')], ['fight', N('While fighting')], ['big', N('Target HP at least')], ['always', N('As soon as ready')]];
// A mode's "then" setting: what the bot does when the mode has nothing left to do.
const PIL_THEN = [['stop', N('Stop')], ['hunt', N('Switch to Hunt')], ['quest', N('Switch to Quests')], ['mining', N('Switch to Mining')]];
const PIL_COMPANY = { 1: ['MMO', '#ff5a5a'], 2: ['EIC', '#4aa3ff'], 3: ['VRU', '#46d27f'] };

// Small per-browser memory (the open tab, the map's layers); the page works without it.
const pilMem = (k, v) => { try { if (v === undefined) return localStorage.getItem('pil-' + k); localStorage.setItem('pil-' + k, v); } catch (e) { /* no storage */ } return null; };
// an alien's name without the game's decorations (-=[ Lordakia ]=-, \\ Impulse II //)
const pilName = s => String(s || '').replace(/^[-=[\]:.{}()\\/*\s]+|[-=[\]:.{}()\\/*\s]+$/g, '') || String(s || '?');
// a value of a journal line: numbers formatted, reasons / modes / item ids translated, alien names cleaned
const pilArg = a => typeof a === 'number' ? fmtN(a) : PIL_STOP[a] ? T(PIL_STOP[a]) : PIL_MODES[a] ? T(PIL_MODES[a].name) : PIL_QKIND[a] ? T(PIL_QKIND[a])
  : /^(ammunition|ability|tech|equipment)_/.test(a) ? itemName(a) : pilName(a);
const pilModeName = k => T((PIL_MODES[k] || PIL_MODES.hunt).name);
const pilSt = () => PIL.data?.status || {};
const pilRadar = () => pilSt().radar || null;

// ------------------------------------------------------------ the page
async function renderPilot() {
  clearInterval(PIL.timer);
  pilMapStop();
  await loadGameImages();
  try { PIL.data = await api('/api/pilot'); } catch (e) { return gameError(e, 'pilot'); }
  if (!PIL.data.online) return gameError(new Error(T('Opens once you have logged in to the game.')), 'pilot');     // the other In-game pages' text
  if (PIL.data.status?.catalog) PIL.cat = PIL.data.status.catalog;
  if (!PIL.tab) { const t = pilMem('tab'); PIL.tab = PIL_TABS.some(([k]) => k === t) ? t : 'mode'; }
  const e = PIL.els = { header: h('div'), cmd: h('div', { class: 'card pil-cmd' }), rail: h('div', { class: 'pil-rail' }),
    tabs: h('div', { class: 'seg pil-tabs' }), cards: h('div', { class: 'grid pil-cards' }) };
  PIL.journal = 0;
  $('#content').replaceChildren(h('div', { class: 'stack pil-page' }, e.header, e.cmd, h('div', { class: 'pil-main' }, pilMapBuild(), e.rail), e.tabs, e.cards));
  pilTabs();
  pilCards();
  pilRefresh();
  PIL.timer = setInterval(async () => {
    if (!e.cmd.isConnected) { pilMapStop(); return clearInterval(PIL.timer); }
    if (document.visibilityState !== 'visible' || PIL.polling) return;
    PIL.polling = true;
    const seq = PIL.seq;
    try {
      const d = await api('/api/pilot');
      if (seq !== PIL.seq) return;                  // a save went out meanwhile: its answer is newer
      PIL.data = d;
    } catch (err) { return; } finally { PIL.polling = false; }
    if (!PIL.data.online) return renderPilot();
    if (PIL.data.status?.catalog) PIL.cat = PIL.data.status.catalog;
    pilRefresh();
  }, 1000);
  S.timers.push(PIL.timer);
}

function pilTabs() {
  const m = PIL_MODES[PIL.data.config.mode] || PIL_MODES.hunt;
  PIL.els.tabs.replaceChildren(...PIL_TABS.map(([k, t, ic]) => h('button', { class: k === PIL.tab ? 'on info' : '', onclick: () => {
    PIL.tab = k; pilMem('tab', k); pilTabs(); pilCards();
  } }, icon(k === 'mode' ? m.ic : ic), T(k === 'mode' ? m.name : t))));
}

// The active tab's cards (the mode tab: the chosen mode's cards, 'mode:<mode>').
function pilCards() {
  PIL.aliensSig = '';
  const tab = PIL.tab === 'mode' ? 'mode:' + PIL.data.config.mode : PIL.tab;
  PIL.els.cards.replaceChildren(...PILC.filter(c => [].concat(c.tab).includes(tab)).sort((a, b) => a.order - b.order).map(c => c.build()));
  pilRefreshAliens();
}

function pilRefresh() {
  PIL.els.header.replaceChildren(gameHeader(pilSt(), 'pilot'));
  pilCommand();
  pilRail();
  pilMapFeed(pilRadar());
  pilRefreshAliens();
}

function pilRefreshAliens() {
  const box = PIL.els?.cards.querySelector('.pil-aliens');
  if (box) aliensList(box);
  const areas = PIL.els?.cards.querySelector('.pil-areas-box');
  if (areas && areas._sig !== pilAreasSig()) pilAreasFill(areas);
}

// ------------------------------------------------------------ settings: one path per setting ('flee_hp', 'pet.gear')
const pilGet = path => path.split('.').reduce((o, k) => (o == null ? o : o[k]), PIL.data.config);
const pilSave = (values, msg = T('Saved.')) => { PIL.seq++; return act(async () => { PIL.data = await api('/api/pilot', { config: values }); }, msg); };
const pilSet = (path, v) => { const [a, b] = path.split('.'); return pilSave(b ? { [a]: { [b]: v } } : { [a]: v }); };
const pilNum = (path, min, max, step = 1, scale = 1) => h('input', { class: 'input num', type: 'number', min, max, step,
  value: scale === 1 ? pilGet(path) : Math.round(pilGet(path) * scale), 'data-pilnum': path + '|' + scale,
  onchange: e => { if (e.target.value !== '') pilSet(path, +e.target.value / scale).then(pilNumSync); } });         // an emptied field saves nothing
const pilNumSync = () => document.querySelectorAll('input[data-pilnum]').forEach(i => {      // the server may have adjusted a value (kite_max, resume_hp)
  const [path, scale] = i.dataset.pilnum.split('|'), v = pilGet(path);
  if (v != null) i.value = +scale === 1 ? v : Math.round(v * scale);
});
const pilCheck = (path, label, title) => h('label', { class: 'pil-check', title: title || null },
  h('input', { type: 'checkbox', checked: !!pilGet(path), onchange: e => pilSet(path, e.target.checked) }), h('span', null, label));
const pilSelect = (path, options, cast = String) => h('select', { class: 'input', onchange: e => pilSet(path, cast(e.target.value)) },
  options.map(([v, l]) => h('option', { value: v, selected: String(pilGet(path)) === String(v) }, l)));
const pilFields = (...f) => h('div', { class: 'grid pil-fields' }, ...f);
const pilNoGame = () => h('p', { class: 'muted small' }, T('Start the game once to fill this list.'));
const pilCard = (ic, title, desc, ...body) => h('div', { class: 'card' }, h('h2', null, icon(ic), title), desc ? h('p', { class: 'desc' }, desc) : null, ...body);
const pilThen = (block, own) => pilFields(field(T('Then'), pilSelect(block + '.then', PIL_THEN.filter(([k]) => k !== own).map(([k, l]) => [k, T(l)]))));
const pilFill = (el, ...kids) => el.replaceChildren(...kids.flat().filter(k => k != null && k !== false && k !== ''));
// a game sprite, or the panel's icon when the dump is missing
const pilSprite = (name, size, fallback) => name && GI.index?.sprite[name] ? sprite(name, size)
  : h('span', { class: 'sprite vacant', style: { width: size + 'px', height: size + 'px' } }, icon(fallback || 'alien'));

// A list of rules (abilities, ammo resupply): one row per rule, a button to add one. make() -> the new rule (null: nothing to offer yet);
// row(rule, set) -> the row's fields (set(patch) saves the rule).
function pilRuleList(path, make, row) {
  const box = h('div', { class: 'pil-rules' });
  const draw = () => {
    const rules = pilGet(path) || [];
    const save = list => pilSet(path, list).then(draw);
    const set = (i, patch) => save(rules.map((r, j) => j === i ? Object.assign({}, r, patch) : r));
    const fresh = make();
    box.replaceChildren(...rules.map((r, i) => h('div', { class: 'pil-rule' }, ...row(r, patch => set(i, patch)),
      h('button', { class: 'pil-x', title: T('Remove'), onclick: () => save(rules.filter((_, j) => j !== i)) }, '×'))),
      fresh ? btn(T('Add a rule'), () => save([...rules, fresh]), 'sm ghost', 'plus') : pilNoGame());
  };
  draw();
  return box;
}

// Checkboxes where an empty list means "all" (ore types): every change reads the setting again, so two quick clicks never undo each other.
function pilPickSet(path, items) {
  const box = h('div', { class: 'pil-checks' });
  const draw = () => {
    const sel = pilGet(path) || [], all = !sel.length;
    box.replaceChildren(...items.map(([id, label, sp]) => h('label', { class: 'pil-check' },
      h('input', { type: 'checkbox', checked: all || sel.includes(id), onchange: e => {
        const cur = pilGet(path) || [];
        const base = cur.length ? cur : items.map(([x]) => x);
        const list = e.target.checked ? [...new Set([...base, id])] : base.filter(x => x !== id);
        pilSet(path, list.length === items.length ? [] : list).then(draw);
      } }), sp || null, h('span', null, label))));
  };
  draw();
  return box;
}

// An ordered list of maps (chips) with a select to add one.
function pilMapList(path, emptyText) {
  const box = h('div');
  const draw = () => {
    const sel = pilGet(path) || [];
    const maps = PIL.cat.maps || [];
    const name = id => (maps.find(m => m.id === id) || {}).name || '#' + id;
    const add = h('select', { class: 'input', onchange: e => { if (e.target.value) pilSet(path, [...sel, +e.target.value]).then(draw); } },
      h('option', { value: '' }, maps.length ? T('Add a map…') : T('Start the game once to fill this list.')),
      maps.filter(m => !sel.includes(m.id)).map(m => h('option', { value: m.id }, m.name)));
    box.replaceChildren(
      h('div', { class: 'row wrap pil-chips' }, sel.length ? sel.map((id, i) => h('span', { class: 'pill' }, (i + 1) + '. ' + name(id),
        h('button', { class: 'pil-x', title: T('Remove'), onclick: () => pilSet(path, sel.filter(x => x !== id)).then(draw) }, '×')))
        : h('span', { class: 'muted small' }, emptyText)), add);
  };
  draw();
  return box;
}

// ------------------------------------------------------------ the command bar
// The four modes as tiles, Start/Stop, then one line: the state, what the ship is doing and why it waits. The tiles and the button are
// built once (the button again when the state changes); the line is filled every second.
function pilCommand() {
  const card = PIL.els.cmd, d = PIL.data, st = pilSt(), cfg = d.config, on = cfg.enabled;
  if (!card._pil) {
    const tiles = Object.entries(PIL_MODES).map(([k, m]) => h('button', { class: 'pil-mode-tile', type: 'button', 'data-mode': k, title: T(m.sub),
      onclick: () => k !== PIL.data.config.mode && pilSet('mode', k).then(() => { pilTabs(); pilCards(); pilCommand(); }) },
    GI.index?.sprite[m.sp] ? sprite(m.sp, 38) : icon(m.ic), h('b', null, T(m.name)), h('small', null, T(m.sub))));
    card._pil = { tiles, go: h('div', { class: 'pil-go' }), strip: h('div', { class: 'pil-strip' }), on: null };
    card.replaceChildren(h('div', { class: 'pil-modes' }, tiles), card._pil.go, card._pil.strip);
  }
  const p = card._pil;
  p.tiles.forEach(t => t.classList.toggle('on', t.dataset.mode === cfg.mode));
  if (p.on !== on) {
    p.on = on;
    const b = btn(on ? T('Stop') : T('Start'), async () => {
      b.disabled = true;
      const r = await act(() => api(on ? '/api/pilot/stop' : '/api/pilot/start', {}));
      b.disabled = false;
      if (r) { PIL.seq++; PIL.data = r; pilCommand(); }
    }, on ? 'danger' : 'primary', on ? 'stop' : 'play');
    pilFill(p.go, b, h('small', null, on ? T('The server is flying your ship.') : T('Your ship is yours: nothing runs.')));
  }
  const state = on ? st.state || 'off' : 'off';
  const cls = state === 'running' ? 'ok' : state === 'paused' ? 'warn' : '';
  const reason = st.reason && PIL_REASON[st.reason] ? T(PIL_REASON[st.reason], st.pause_left) : '';
  const stopped = !on && st.stats?.stop_reason && PIL_STOP[st.stats.stop_reason] ? T(PIL_STOP[st.stats.stop_reason]) : '';
  const t = st.target;
  const doing = on && state === 'running' && st.mode ? (st.mode === 'fight' && t ? T('Fighting {0}', pilName(t.name)) : T(PIL_MODE[st.mode] || st.mode)) : '';
  // after a mode's end the running mode can differ from the chosen one ('then')
  const other = on && st.run_mode && st.run_mode !== cfg.mode && PIL_MODES[st.run_mode] ? T('Running: {0} (after {1})', pilModeName(st.run_mode), pilModeName(cfg.mode)) : '';
  const away = on && st.hunt_map && st.hunt_map !== st.map ? T('Heading for {0}', st.hunt_map) : '';
  pilFill(p.strip, h('span', { class: 'pil-state' }, dot(cls), T(PIL_STATE[state] || state)),
    doing && h('span', { class: 'pil-doing' }, doing), away && h('span', null, away), other && h('span', { class: 'pill warn' }, other),
    (reason || stopped) && h('span', { class: 'pil-note' }, reason || stopped), st.quest && h('span', null, T('Quest: {0}', st.quest.name)),
    h('span', { class: 'spacer' }),
    on && st.stats?.started ? h('span', null, T('Running for {0}', fmtDur(Date.now() / 1000 - st.stats.started))) : null);
}

// ------------------------------------------------------------ the rail: ship, target, session, journal
function pilRail() {
  const rail = PIL.els.rail, st = pilSt(), r = pilRadar();
  if (!rail._pil) {
    const q = { ship: h('div', { class: 'card' }), target: h('div', { class: 'card' }), session: h('div', { class: 'card' }), journal: h('div', { class: 'card' }) };
    rail._pil = Object.assign(q, { shipSig: '', sessionSig: '' });
    rail.replaceChildren(q.ship, q.target, q.session, q.journal);
  }
  const q = rail._pil;
  pilRailShip(q, r);
  pilRailTarget(q.target, st, r);
  const s = st.stats || {};
  const sig = JSON.stringify([s.kills, s.credits, s.uridium, s.ep, s.honor, s.boxes, s.deaths, s.revives, s.spent_credits, s.spent_uridium,
    (s.curve || []).length, s.started, Math.floor(Date.now() / 60000)]);
  if (sig !== q.sessionSig && !q.session.matches(':hover')) { q.sessionSig = sig; pilRailSession(q.session, s); }
  pilRailJournal(q.journal, s.journal || []);
}

const pilGauge = (label, cur, max, color, text) => {
  const pct = max ? Math.max(0, Math.min(100, 100 * cur / max)) : 0;
  return h('div', { class: 'pil-gauge' }, h('span', null, label), h('div', { class: 'pil-track' }, h('i', { style: { width: pct + '%', '--c': color } })),
    h('b', null, text ?? Math.round(pct) + ' %'));
};

function pilRailShip(q, r) {
  const hero = r?.hero;
  const sig = hero ? hero.ship + '|' + r.name + '|' + hero.peace : '';
  if (sig !== q.shipSig) {
    q.shipSig = sig;
    q.gauges = h('div', { class: 'pil-gauges' });
    pilFill(q.ship, h('h3', null, icon('ship'), T('Your ship')),
      hero ? h('div', { class: 'pil-ship' }, gameIcon(hero.ship, 56, PIL_COMPANY[hero.company]?.[0]?.toLowerCase(), 'ship'),
        h('div', { style: { minWidth: 0 } }, h('div', { class: 'pil-ship-name' }, itemName(hero.ship)),
          h('div', { class: 'pil-ship-sub' }, r.name, ' · ', hero.peace ? T('In a safe zone') : T('In space'))))
        : h('p', { class: 'muted small' }, T('Waiting for the game…')), q.gauges);
  }
  if (!hero) return;
  const cargoUsed = Math.max(0, hero.cargo_max - hero.cargo);
  pilFill(q.gauges, pilGauge(T('HP'), hero.hp, hero.hp_max, 'var(--ok)'), pilGauge(T('Shield'), hero.sh, hero.sh_max, 'var(--accent)'),
    hero.cargo_max ? pilGauge(T('Cargo'), cargoUsed, hero.cargo_max, 'var(--amber)', fmtN(cargoUsed) + ' / ' + fmtN(hero.cargo_max)) : null);
}

// The target (icon, HP and shield, distance against the laser range with the kiting band), or what the ship is doing.
function pilRailTarget(card, st, r) {
  const t = st.target, cfg = PIL.data.config;
  if (!t) {
    const on = cfg.enabled && st.state === 'running';
    const what = on && st.mode ? T(PIL_MODE[st.mode] || st.mode) : cfg.enabled ? T(PIL_STATE[st.state] || 'Paused') : T('Auto Mode is off.');
    const sig = 'idle|' + what;
    if (card._sig === sig) return;
    card._sig = sig;
    return pilFill(card, h('h3', null, icon('target'), T('Target')), h('div', { class: 'pil-idle' }, icon(on ? 'crosshair' : 'bot'),
      h('div', null, h('div', null, what), h('small', { class: 'dim' }, T('No alien targeted.')))));
  }
  const type = r?.types?.[t.tip] || {};
  const sig = 'fight|' + t.id;
  if (card._sig !== sig) {
    card._sig = sig;
    card._live = h('div');
    pilFill(card, h('h3', null, icon('target'), T('Target')),
      h('div', { class: 'pil-target' }, pilSprite(type.icon, 48), h('div', { style: { minWidth: 0 } }, h('div', { class: 'pil-target-name' }, pilName(t.name)),
        h('small', { class: 'dim' }, type.aggressive ? T('Attacks you on sight') : T('Attacks only when hit')))), card._live);
  }
  const R = Math.max(1, t.range), span = R * 1.5, at = v => Math.max(0, Math.min(100, 100 * v / span));
  pilFill(card._live, h('div', { class: 'pil-gauges' }, pilGauge(T('HP'), t.hp, t.hp_max, 'var(--err)'),
    t.shield_max ? pilGauge(T('Shield'), t.shield, t.shield_max, 'var(--accent)') : null),
  h('div', { class: 'pil-range', title: T('Distance to the target against your laser range; the green band is where the ship keeps it.') },
    h('div', { class: 'rail' }), h('div', { class: 'band', style: { left: at(cfg.kite_min * R) + '%', width: (at(cfg.kite_max * R) - at(cfg.kite_min * R)) + '%' } }),
    h('div', { class: 'edge', style: { left: at(R) + '%' } }), h('div', { class: 'mark', style: { left: at(t.dist) + '%' } })),
  h('div', { class: 'pil-range-legend' }, h('span', null, T('Distance {0}', fmtN(t.dist))), h('span', null, T('Laser range {0}', fmtN(R)))));
}

// A sparkline of one total over the session (single series: the tile's title names it), with a crosshair readout on hover.
function pilSpark(curve, idx, color) {
  const W = 140, H = 30, pts = (curve || []).map(p => [p[0], p[idx]]);
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('preserveAspectRatio', 'none'); svg.setAttribute('class', 'pil-spark');
  if (pts.length < 2) return svg;
  const t1 = pts[pts.length - 1][0] || 1, lo = Math.min(...pts.map(p => p[1])), hi = Math.max(...pts.map(p => p[1])) || 1;
  const X = t => (t / t1) * W, Y = v => H - 3 - ((v - lo) / Math.max(1, hi - lo)) * (H - 6);
  const line = pts.map((p, i) => (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join(' ');
  const el = (n, a) => { const e = document.createElementNS(SVGNS, n); for (const k in a) e.setAttribute(k, a[k]); return e; };
  svg.append(el('path', { d: line + ` L${W} ${H} L0 ${H} Z`, fill: color, 'fill-opacity': '.12', stroke: 'none' }),
    el('path', { d: line, fill: 'none', stroke: color, 'stroke-width': '2', 'vector-effect': 'non-scaling-stroke', 'stroke-linejoin': 'round' }));
  const cross = el('line', { y1: 0, y2: H, stroke: 'rgba(230,240,251,.35)', 'stroke-width': 1, 'vector-effect': 'non-scaling-stroke', visibility: 'hidden' });
  svg.append(cross);
  svg._pts = pts; svg._X = X; svg._cross = cross;
  return svg;
}

function pilRailSession(card, s) {
  const curve = s.curve || [], keys = s.curve_keys || [];
  const hours = s.started ? (Date.now() / 1000 - s.started) / 3600 : 0;
  const rate = k => hours >= 5 / 60 ? T('{0} per hour', fmtN(Math.round((s[k] || 0) / hours))) : T('rate after 5 min');
  const tile = (label, k, color) => {
    const spark = pilSpark(curve, keys.indexOf(k) + 1, color), tip = h('span', { class: 'pil-spark-tip' });
    const box = h('div', { class: 'pil-tile' }, h('span', null, label), h('b', null, fmtN(s[k] || 0)), h('small', null, rate(k)), spark, tip);
    box.addEventListener('mousemove', e => {
      if (!spark._pts) return;
      const rc = spark.getBoundingClientRect(), x = (e.clientX - rc.left) / rc.width * 140;
      const p = spark._pts.reduce((a, b) => Math.abs(spark._X(b[0]) - x) < Math.abs(spark._X(a[0]) - x) ? b : a);
      spark._cross.setAttribute('x1', spark._X(p[0])); spark._cross.setAttribute('x2', spark._X(p[0])); spark._cross.setAttribute('visibility', 'visible');
      tip.textContent = fmtDur(p[0]) + ': ' + fmtN(p[1]);
    });
    box.addEventListener('mouseleave', () => { if (spark._cross) spark._cross.setAttribute('visibility', 'hidden'); tip.textContent = ''; });
    return box;
  };
  const fact = (k, v) => h('div', null, k, h('b', null, v));
  pilFill(card, h('h3', null, icon('clock'), T('Session')),
    s.started ? [h('div', { class: 'pil-tiles' }, tile(T('Aliens'), 'kills', '#ffb94d'), tile(T('Credits'), 'credits', '#40dfff'),
      tile(T('Uridium'), 'uridium', '#9b71f4'), tile(T('Experience'), 'ep', '#3ee59b')),
    h('div', { class: 'pil-facts' }, fact(T('Boxes'), fmtN(s.boxes || 0)), fact(T('Honor'), fmtN(s.honor || 0)),
      fact(T('Deaths / repairs'), fmtN(s.deaths || 0) + ' / ' + fmtN(s.revives || 0)), fact(T('Portals'), fmtN(s.jumps || 0)),
      fact(T('Spent'), fmtN(s.spent_credits || 0) + ' C · ' + fmtN(s.spent_uridium || 0) + ' U')),
    s.stop_reason && PIL_STOP[s.stop_reason] ? h('p', { class: 'muted small', style: { margin: '8px 0 0' } }, T('Last stop: {0}', T(PIL_STOP[s.stop_reason]))) : null]
      : h('p', { class: 'muted small' }, T('Press Start: the totals and their curves appear here.')));
}

const pilSig = e => JSON.stringify(e || []);       // a journal entry's identity: a new note at the cap can share the second
function pilRailJournal(card, journal) {
  if (card._n === journal.length && card._last === pilSig(journal[journal.length - 1])) return;
  const fresh = card._n == null ? 0 : Math.max(0, journal.length - card._n);
  card._n = journal.length;
  card._last = pilSig(journal[journal.length - 1]);
  const fmt = t => new Date(t * 1000).toLocaleTimeString(LOC(), { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  const line = e => typeof e[1] === 'string' && Array.isArray(e[2]) ? T(e[1], ...e[2].map(pilArg)) : String(e[1] ?? '');     // [time, template, values]
  pilFill(card, h('h3', null, icon('note'), T('Journal')),
    journal.length ? h('ul', { class: 'pil-journal' }, journal.slice(-40).reverse().map((e, i) => h('li', { class: i < fresh ? 'new' : '' },
      h('time', null, fmt(e[0])), h('span', null, line(e))))) : h('p', { class: 'muted small' }, T('Nothing yet.')));
}

// ------------------------------------------------------------ the tactical map
// A canvas drawn every frame (requestAnimationFrame while the page is open and visible). The status arrives once a second: each mark moves
// on with its velocity and is eased toward that point, so the ships glide instead of jumping. World units -> screen: (x - view.x) * view.s.
const PIL_LAYERS = [['aliens', N('Aliens'), '#ff5d6c', ''], ['pilots', N('Pilots'), '#e6f0fb', ''], ['boxes', N('Boxes'), '#ffb94d', ''],
  ['ore', N('Ore'), '#c38bff', ''], ['trail', N('Trail'), '#40dfff', 'ring'], ['safe', N('Safe zones'), '#3ee59b', 'ring'],
  ['areas', N('Areas'), '#40dfff', 'sq'], ['range', N('Laser range'), '#b9c7da', 'ring']];
const PIL_TOOLS = [['look', N('Look'), 'cursor'], ['work', N('Work area'), 'area'], ['avoid', N('Area to avoid'), 'ban'], ['erase', N('Remove an area'), 'eraser']];
const PIL_TOOL_HINT = { work: N('Drag a rectangle: the ship hunts, collects and patrols only inside it (one work area per map).'),
  avoid: N('Drag a rectangle: the ship never flies into it nor takes anything inside it.'), erase: N('Click an area to remove it.') };
const PILM = { el: null, cv: null, ctx: null, W: 0, H: 0, dpr: 1, view: { s: 0, x: 0, y: 0 }, fitS: 0, follow: true, tool: 'look', layers: {},
  r: null, at: 0, last: 0, disp: new Map(), head: -Math.PI / 2, hover: null, drag: null, pop: null, raf: 0, imgs: {}, mapId: null, hits: [] };

function pilMapStop() {
  cancelAnimationFrame(PILM.raf);
  PILM.raf = 0;
  PILM.ro?.disconnect();
}

function pilMapBuild() {
  let saved = {};
  try { saved = JSON.parse(pilMem('layers') || '{}'); } catch (e) { /* default */ }
  PILM.layers = Object.fromEntries(PIL_LAYERS.map(([k]) => [k, saved[k] !== false]));
  PILM.tool = 'look'; PILM.pop = null; PILM.hover = null; PILM.drag = null; PILM.mapId = null; PILM.r = null; PILM.disp.clear();
  const cv = PILM.cv = h('canvas');
  PILM.ctx = cv.getContext('2d');
  const view = PILM.el = h('div', { class: 'pil-view', 'data-tool': 'look' }, cv);
  PILM.routeEl = h('div', { class: 'pil-route' });
  PILM.hintEl = h('div', { class: 'pil-toolhint', style: { display: 'none' } });
  PILM.coordEl = h('div', { class: 'pil-coords' });
  PILM.tipEl = h('div', { class: 'pil-tip', style: { display: 'none' } });
  view.append(PILM.routeEl, PILM.hintEl, PILM.coordEl, PILM.tipEl);
  PILM.nameEl = h('div', { class: 'pil-mapname' });
  PILM.toolSeg = h('div', { class: 'seg' }, PIL_TOOLS.map(([k, name, ic]) => h('button', { type: 'button', title: T(name), 'data-tool': k,
    class: k === 'look' ? 'on info' : '', onclick: () => pilTool(k) }, icon(ic), h('span', null, T(name)))));
  PILM.followBtn = btn(T('Follow the ship'), () => { PILM.follow = !PILM.follow; pilMapButtons(); }, 'sm ghost', 'crosshair');
  const bar = h('div', { class: 'pil-bar' }, PILM.nameEl, PILM.toolSeg, h('span', { class: 'spacer' }), PILM.followBtn,
    btn('', () => { pilFit(); PILM.follow = true; pilMapButtons(); }, 'sm ghost icon', 'fit', { title: T('Whole map') }));
  PILM.legend = h('div', { class: 'pil-legend' });
  pilLegend();
  pilMapButtons();
  pilMapEvents();
  PILM.ro = new ResizeObserver(() => pilResize());
  PILM.ro.observe(view);
  PILM.last = performance.now();
  const frame = t => {
    if (!view.isConnected) return pilMapStop();
    PILM.raf = requestAnimationFrame(frame);
    if (document.visibilityState !== 'visible') return;
    pilDraw(t);
  };
  PILM.raf = requestAnimationFrame(frame);
  return h('div', { class: 'card pil-scope' }, bar, view, PILM.legend);
}

function pilLegend() {
  pilFill(PILM.legend, PIL_LAYERS.map(([k, name, c, shape]) => h('button', { type: 'button', class: 'pil-chip' + (PILM.layers[k] ? '' : ' off'),
    title: T('Show or hide'), onclick: () => { PILM.layers[k] = !PILM.layers[k]; pilMem('layers', JSON.stringify(PILM.layers)); pilLegend(); } },
  h('span', { class: 'pil-sw ' + shape, style: { '--c': c } }), T(name))),
  h('span', { class: 'spacer' }), h('span', { class: 'muted' }, T('Wheel: zoom · drag: move · double-click: whole map')));
}

function pilMapButtons() {
  PILM.followBtn.classList.toggle('on', PILM.follow);
  PILM.followBtn.classList.toggle('info', PILM.follow);
  PILM.toolSeg.querySelectorAll('button').forEach(b => { const on = b.dataset.tool === PILM.tool; b.classList.toggle('on', on); b.classList.toggle('info', on); });
  PILM.el.dataset.tool = PILM.tool;
  const hint = PIL_TOOL_HINT[PILM.tool];
  PILM.hintEl.style.display = hint ? '' : 'none';
  PILM.hintEl.textContent = hint ? T(hint) : '';
}

function pilTool(k) {
  PILM.tool = k;
  pilPopClose();
  pilMapButtons();
}

function pilResize() {
  const rc = PILM.el.getBoundingClientRect();
  if (!rc.width || !rc.height) return;
  const first = !PILM.W;
  PILM.W = rc.width; PILM.H = rc.height; PILM.dpr = window.devicePixelRatio || 1;
  PILM.cv.width = Math.round(rc.width * PILM.dpr); PILM.cv.height = Math.round(rc.height * PILM.dpr);
  const r = PILM.r;
  if (!r) return;
  const old = PILM.fitS;
  PILM.fitS = Math.min(PILM.W / r.w, PILM.H / r.h);
  if (first || !old || PILM.view.s <= old * 1.001) pilFit(); else pilClamp();
}

function pilFit() {
  const r = PILM.r;
  if (!r || !PILM.W) return;
  PILM.fitS = Math.min(PILM.W / r.w, PILM.H / r.h);
  PILM.view.s = PILM.fitS;
  pilClamp();
}

// the map stays in view: centered on an axis it fits, otherwise its edges no farther in than a fifth of the view
function pilClamp() {
  const r = PILM.r, v = PILM.view;
  if (!r) return;
  for (const [k, size, span] of [['x', r.w, PILM.W / v.s], ['y', r.h, PILM.H / v.s]]) {
    if (span >= size) v[k] = (size - span) / 2;
    else v[k] = Math.max(-span * 0.2, Math.min(size - span * 0.8, v[k]));
  }
}

const pilWorld = (px, py) => [PILM.view.x + px / PILM.view.s, PILM.view.y + py / PILM.view.s];

// A new status: the marks keep their eased position; another map starts over (fit, empty trail).
function pilMapFeed(r) {
  if (!PILM.el) return;
  PILM.r = r;
  PILM.at = performance.now();
  if (!r) { PILM.nameEl.replaceChildren(h('b', null, '—')); return; }
  if (r.map !== PILM.mapId) {
    PILM.mapId = r.map;
    PILM.disp.clear();
    pilPopClose();
    pilResize();
    pilFit();
    PILM.nameEl.replaceChildren(h('b', null, r.name), h('span', null, fmtN(r.w) + ' × ' + fmtN(r.h)));
  }
  const route = (r.intent || {}).route || [];
  pilFill(PILM.routeEl, route.length > 1 ? route.map((m, i) => [i ? icon('chevR') : null, h('span', { class: i === 0 ? 'here' : i === route.length - 1 ? 'goal' : '' }, m)]) : null);
  if (PILM.pop) PILM.pop.refresh?.();
}

// an atlas page of the game's images (drawn straight from the page with drawImage)
function pilPage(page) {
  let img = PILM.imgs[page];
  if (!img) { img = PILM.imgs[page] = new Image(); img.src = '/game_images/' + page + '.png'; }
  return img.complete && img.naturalWidth ? img : null;
}
function pilImage(src) {
  let img = PILM.imgs[src];
  if (!img) { img = PILM.imgs[src] = new Image(); img.src = src; }
  return img.complete && img.naturalWidth ? img : null;
}
// draws sprite `name` centered at (x, y) in a box of `size` px, turned by `rot` -> whether it could
function pilDrawSprite(ctx, name, x, y, size, rot, alpha) {
  const e = name && GI.index?.sprite[name];
  const img = e && pilPage(e[0]);
  if (!img) return false;
  const [, sx, sy, w, hh, W, H, ox, oy] = e, k = size / Math.max(W, H);
  ctx.save();
  ctx.translate(x, y);
  if (rot) ctx.rotate(rot);
  if (alpha != null) ctx.globalAlpha = alpha;
  ctx.drawImage(img, sx, sy, w, hh, -W * k / 2 + ox * k, -H * k / 2 + oy * k, w * k, hh * k);
  ctx.restore();
  return true;
}
// the top view of a ship (lootId ship_..._design_sentinel-carbonite -> sentinel-carbonite_top; ship_aegis + company -> aegis-eic_top)
function pilTop(lid, company) {
  if (!lid || !GI.index) return null;
  const k = lid.replace(/^ship_/, ''), last = k.split('_').pop(), firm = (PIL_COMPANY[company]?.[0] || '').toLowerCase();
  for (const c of [last, k.replace(/_/g, '-'), last + '-' + firm, k.split('_')[0]]) if (GI.index.sprite[c + '_top']) return c + '_top';
  return null;
}
const pilOreSprite = tip => { const o = (PIL.cat.ores || []).find(x => x.id === tip); return o ? itemSprite(o.loot) : null; };

// the eased screen position of a moving mark
function pilPos(key, x, y, vx, vy, now, frameDt) {
  const dt = Math.min(1.3, (now - PILM.at) / 1000);
  const tx = x + (vx || 0) * dt, ty = y + (vy || 0) * dt;
  let d = PILM.disp.get(key);
  if (!d || Math.hypot(d[0] - tx, d[1] - ty) > 2500) { d = [tx, ty]; PILM.disp.set(key, d); }
  const k = 1 - Math.exp(-frameDt * 9);
  d[0] += (tx - d[0]) * k; d[1] += (ty - d[1]) * k;
  d.seen = now;
  return d;
}

function pilDraw(now) {
  const ctx = PILM.ctx, W = PILM.W, H = PILM.H, r = PILM.r, frameDt = Math.min(0.1, (now - PILM.last) / 1000);
  PILM.last = now;
  if (!W) return pilResize();
  ctx.setTransform(PILM.dpr, 0, 0, PILM.dpr, 0, 0);
  ctx.fillStyle = '#02060d';
  ctx.fillRect(0, 0, W, H);
  PILM.hits = [];
  if (!r) return;
  const v = PILM.view, s = v.s, X = x => (x - v.x) * s, Y = y => (y - v.y) * s, L = PILM.layers;
  const zoom = s / (PILM.fitS || s), IS = Math.max(16, Math.min(34, 17 * Math.sqrt(zoom)));     // a mark's size on screen
  const hero = r.hero, hp = pilPos('hero', hero.x, hero.y, hero.vx, hero.vy, now, frameDt);
  if (PILM.follow && zoom > 1.02 && !PILM.drag) {             // keep the ship in the middle (eased)
    const k = 1 - Math.exp(-frameDt * 4);
    v.x += (hp[0] - W / 2 / s - v.x) * k; v.y += (hp[1] - H / 2 / s - v.y) * k;
    pilClamp();
  }
  // ground, grid, edge
  ctx.fillStyle = '#050c19';
  ctx.fillRect(X(0), Y(0), r.w * s, r.h * s);
  ctx.lineWidth = 1;
  for (let g = 1000; g < Math.max(r.w, r.h); g += 1000) {
    ctx.strokeStyle = g % 5000 ? 'rgba(64,223,255,.035)' : 'rgba(64,223,255,.09)';
    ctx.beginPath();
    if (g < r.w) { ctx.moveTo(X(g) + .5, Y(0)); ctx.lineTo(X(g) + .5, Y(r.h)); }
    if (g < r.h) { ctx.moveTo(X(0), Y(g) + .5); ctx.lineTo(X(r.w), Y(g) + .5); }
    ctx.stroke();
  }
  ctx.strokeStyle = 'rgba(64,223,255,.28)';
  ctx.strokeRect(X(0) + .5, Y(0) + .5, r.w * s - 1, r.h * s - 1);
  ctx.fillStyle = 'rgba(160,175,200,.16)';
  for (const [x0, y0, x1, y1] of r.walls || []) ctx.fillRect(X(x0), Y(y0), (x1 - x0) * s, (y1 - y0) * s);
  // safe zones, station, quest givers
  if (L.safe) for (const [x, y, rad] of r.safe || []) {
    ctx.beginPath(); ctx.arc(X(x), Y(y), rad * s, 0, 7);
    ctx.fillStyle = 'rgba(62,229,155,.06)'; ctx.fill();
    ctx.strokeStyle = 'rgba(62,229,155,.35)'; ctx.setLineDash([4, 4]); ctx.stroke(); ctx.setLineDash([]);
  }
  if (r.station) {
    const [x, y, , comp] = r.station, firm = (PIL_COMPANY[comp]?.[0] || 'eic').toLowerCase();
    if (!pilDrawSprite(ctx, 'homestation_company_' + firm, X(x), Y(y), IS * 1.5)) { ctx.fillStyle = PIL_COMPANY[comp]?.[1] || '#b9c7da'; ctx.fillRect(X(x) - 6, Y(y) - 6, 12, 12); }
    PILM.hits.push({ x: X(x), y: Y(y), r: IS * 0.75, kind: 'station', d: r.station });
  }
  for (const [x, y] of r.givers || []) {
    pilDrawSprite(ctx, 'homestation_questgiver', X(x), Y(y), IS * 1.1);
    PILM.hits.push({ x: X(x), y: Y(y), r: IS * 0.55, kind: 'giver' });
  }
  // the drawn areas: outside the work area dimmed, areas to avoid hatched red
  const zones = PIL.data.config.zones?.[String(r.map)] || {};
  if (L.areas) pilDrawAreas(ctx, X, Y, s, r, zones);
  // ore and boxes
  if (L.ore) for (const [x, y, tip] of r.ores || []) {
    const sx = X(x), sy = Y(y);
    if (sx < -20 || sy < -20 || sx > W + 20 || sy > H + 20) continue;
    if (!pilDrawSprite(ctx, pilOreSprite(tip), sx, sy, IS * 0.62)) { ctx.fillStyle = '#c38bff'; ctx.beginPath(); ctx.arc(sx, sy, 2.5, 0, 7); ctx.fill(); }
    PILM.hits.push({ x: sx, y: sy, r: 7, kind: 'ore', d: tip });
  }
  if (L.boxes) for (const [x, y, kind] of r.boxes || []) {
    const sx = X(x), sy = Y(y);
    if (!pilDrawSprite(ctx, kind === 'cargo' ? 'cargo_box' : 'bonus_box', sx, sy, IS * 0.7, 0, kind === 'other' ? 0.5 : 1)) {
      ctx.fillStyle = '#ffb94d'; ctx.fillRect(sx - 3, sy - 3, 6, 6);
    }
    PILM.hits.push({ x: sx, y: sy, r: 7, kind: 'box', d: kind });
  }
  // the trail (older = fainter) and the marks (destroyed aliens, deaths; they fade in ten minutes)
  if (L.trail) {
    const tr = (r.trail || []).concat([[hp[0], hp[1]]]);
    ctx.lineWidth = 2; ctx.lineCap = 'round';
    for (let i = 1; i < tr.length; i++) {
      ctx.strokeStyle = `rgba(64,223,255,${(0.05 + 0.5 * i / tr.length).toFixed(3)})`;
      ctx.beginPath(); ctx.moveTo(X(tr[i - 1][0]), Y(tr[i - 1][1])); ctx.lineTo(X(tr[i][0]), Y(tr[i][1])); ctx.stroke();
    }
    const ts = Date.now() / 1000;
    for (const [kind, x, y, t] of r.marks || []) {
      const a = Math.max(0, 1 - (ts - t) / 600);
      if (!a) continue;
      const sx = X(x), sy = Y(y), d = kind === 'death' ? 7 : 4;
      ctx.strokeStyle = kind === 'death' ? `rgba(255,93,108,${a})` : `rgba(255,185,77,${a * 0.85})`;
      ctx.lineWidth = kind === 'death' ? 2.5 : 1.5;
      ctx.beginPath(); ctx.moveTo(sx - d, sy - d); ctx.lineTo(sx + d, sy + d); ctx.moveTo(sx + d, sy - d); ctx.lineTo(sx - d, sy + d); ctx.stroke();
    }
  }
  // portals (the one the ship heads for pulses)
  const goal = (r.intent || {}).portal, pulse = (Math.sin(now / 260) + 1) / 2;
  const pimg = pilImage('images/map_portal.webp');
  ctx.font = '600 11px Bahnschrift, "Segoe UI", sans-serif'; ctx.textAlign = 'center';
  for (const [x, y, name, tid, kind, gid] of r.portals || []) {
    const sx = X(x), sy = Y(y), sz = IS * 1.25;
    if (gid != null && gid === goal) {
      ctx.beginPath(); ctx.arc(sx, sy, sz * (0.75 + pulse * 0.35), 0, 7);
      ctx.strokeStyle = `rgba(255,185,77,${0.4 + pulse * 0.5})`; ctx.lineWidth = 2; ctx.stroke();
    }
    if (pimg) { ctx.globalAlpha = kind === 'map' ? 1 : 0.85; ctx.drawImage(pimg, sx - sz / 2, sy - sz / 2, sz, sz); ctx.globalAlpha = 1; }
    else { ctx.strokeStyle = '#40dfff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(sx, sy, 7, 0, 7); ctx.stroke(); }
    if (name) { ctx.fillStyle = kind === 'map' ? 'rgba(230,240,251,.85)' : 'rgba(155,113,244,.95)'; ctx.fillText(name, sx, sy - sz / 2 - 4); }
    PILM.hits.push({ x: sx, y: sy, r: sz / 2, kind: 'portal', d: { name, kind, target: tid } });
  }
  // aliens: the game's icon; red ring = aggressive, solid red = attacking you, faint = not hunted here, gold star = priority
  const intent = r.intent || {}, target = intent.target, live = new Set();
  let targetPos = null;
  if (L.aliens) for (const n of r.npcs || []) {
    const [id, tip, x, y, vx, vy, hpPct, f] = n, p = pilPos('n' + id, x, y, vx, vy, now, frameDt), sx = X(p[0]), sy = Y(p[1]);
    live.add('n' + id);
    if (id === target) targetPos = p;
    if (sx < -40 || sy < -40 || sx > W + 40 || sy > H + 40) continue;
    const type = r.types[tip] || {}, hunted = f & 8, ignored = f & 32;
    const a = hunted && !ignored ? 1 : 0.42;
    if (f & 2) { ctx.beginPath(); ctx.arc(sx, sy, IS * 0.62, 0, 7); ctx.fillStyle = 'rgba(255,93,108,.22)'; ctx.fill(); }
    if (f & 1) { ctx.beginPath(); ctx.arc(sx, sy, IS * 0.62, 0, 7); ctx.strokeStyle = `rgba(255,93,108,${(f & 2 ? 0.95 : 0.55) * a})`; ctx.lineWidth = f & 2 ? 2 : 1.25; ctx.stroke(); }
    if (!pilDrawSprite(ctx, type.icon, sx, sy, IS, 0, a)) {
      ctx.globalAlpha = a; ctx.fillStyle = f & 1 ? '#ff5d6c' : '#b9c7da'; ctx.beginPath(); ctx.arc(sx, sy, 4, 0, 7); ctx.fill(); ctx.globalAlpha = 1;
    }
    if (hpPct < 100) {
      const bw = IS * 0.9;
      ctx.fillStyle = 'rgba(0,0,0,.6)'; ctx.fillRect(sx - bw / 2, sy + IS * 0.55, bw, 3);
      ctx.fillStyle = '#ff5d6c'; ctx.fillRect(sx - bw / 2, sy + IS * 0.55, bw * hpPct / 100, 3);
    }
    if (f & 16) pilStar(ctx, sx + IS * 0.45, sy - IS * 0.45, 4.5);
    if (ignored) { ctx.strokeStyle = 'rgba(185,199,218,.8)'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(sx - 5, sy - 5); ctx.lineTo(sx + 5, sy + 5); ctx.stroke(); }
    PILM.hits.push({ x: sx, y: sy, r: IS * 0.55, kind: 'alien', d: n });
  }
  // other pilots: their ship seen from above (or a chevron) in their company's color; red ring = could attack you
  if (L.pilots) for (const o of r.ships || []) {
    const [id, name, x, y, vx, vy, comp, ship, hostile, attacking] = o, p = pilPos('s' + id, x, y, vx, vy, now, frameDt), sx = X(p[0]), sy = Y(p[1]);
    live.add('s' + id);
    const color = PIL_COMPANY[comp]?.[1] || '#e6f0fb', ang = Math.hypot(vx, vy) > 5 ? Math.atan2(vy, vx) : -Math.PI / 2;
    if (hostile || attacking) { ctx.beginPath(); ctx.arc(sx, sy, IS * 0.65, 0, 7); ctx.strokeStyle = attacking ? `rgba(255,93,108,${0.55 + pulse * 0.45})` : 'rgba(255,93,108,.5)'; ctx.lineWidth = attacking ? 2 : 1.25; ctx.stroke(); }
    if (!pilDrawSprite(ctx, pilTop(ship, comp), sx, sy, IS * 1.1, ang + Math.PI / 2)) pilChevron(ctx, sx, sy, ang, 7, color);
    ctx.beginPath(); ctx.arc(sx, sy, 2, 0, 7); ctx.fillStyle = color; ctx.fill();
    ctx.fillStyle = color; ctx.fillText(name || '', sx, sy + IS * 0.75 + 9);
    PILM.hits.push({ x: sx, y: sy, r: IS * 0.55, kind: 'pilot', d: o });
  }
  for (const k of PILM.disp.keys()) if (k !== 'hero' && !live.has(k) && now - (PILM.disp.get(k).seen || 0) > 3000) PILM.disp.delete(k);
  // the hero: laser range, where it flies, the target's kiting band and lock
  const hx = X(hp[0]), hy = Y(hp[1]);
  if (Math.hypot(hero.vx, hero.vy) > 5) {
    const want = Math.atan2(hero.vy, hero.vx);
    let d = want - PILM.head; d = Math.atan2(Math.sin(d), Math.cos(d));
    PILM.head += d * (1 - Math.exp(-frameDt * 8));
  }
  if (L.range && hero.range) {
    ctx.beginPath(); ctx.arc(hx, hy, hero.range * s, 0, 7);
    ctx.strokeStyle = 'rgba(185,199,218,.22)'; ctx.lineWidth = 1; ctx.setLineDash([2, 5]); ctx.stroke(); ctx.setLineDash([]);
  }
  if (hero.dest) {
    const way = hero.way && hero.way.length ? hero.way : [hero.dest];       // around walls: through the corners left, to the goal
    const end = way[way.length - 1], dx = X(end[0]), dy = Y(end[1]);
    ctx.strokeStyle = 'rgba(64,223,255,.55)'; ctx.lineWidth = 1.25; ctx.setLineDash([5, 5]);
    ctx.beginPath(); ctx.moveTo(hx, hy); for (const [x, y] of way) ctx.lineTo(X(x), Y(y)); ctx.stroke(); ctx.setLineDash([]);
    ctx.save(); ctx.translate(dx, dy); ctx.rotate(Math.PI / 4); ctx.strokeStyle = '#40dfff'; ctx.strokeRect(-3.5, -3.5, 7, 7); ctx.restore();
  }
  if (targetPos) {
    const tx = X(targetPos[0]), ty = Y(targetPos[1]), cfg = PIL.data.config, R = hero.range || 600;
    ctx.strokeStyle = 'rgba(62,229,155,.30)'; ctx.lineWidth = Math.max(1, (cfg.kite_max - cfg.kite_min) * R * s);
    ctx.beginPath(); ctx.arc(tx, ty, (cfg.kite_min + cfg.kite_max) / 2 * R * s, 0, 7); ctx.stroke();
    ctx.strokeStyle = 'rgba(255,185,77,.6)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(hx, hy); ctx.lineTo(tx, ty); ctx.stroke();
    pilLock(ctx, tx, ty, IS * 0.8, now);
  }
  const glow = ctx.createRadialGradient(hx, hy, 0, hx, hy, IS * 1.1);
  glow.addColorStop(0, 'rgba(64,223,255,.32)'); glow.addColorStop(1, 'rgba(64,223,255,0)');
  ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(hx, hy, IS * 1.1, 0, 7); ctx.fill();
  ctx.beginPath(); ctx.arc(hx, hy, IS * 0.78, 0, 7);
  ctx.strokeStyle = '#40dfff'; ctx.lineWidth = 2; ctx.shadowColor = '#40dfff'; ctx.shadowBlur = 10; ctx.stroke(); ctx.shadowBlur = 0;
  ctx.save(); ctx.translate(hx, hy); ctx.rotate(PILM.head);                      // a notch on the ring: where the ship points
  ctx.beginPath(); ctx.moveTo(IS * 0.78 + 7, 0); ctx.lineTo(IS * 0.78 + 1, -4); ctx.lineTo(IS * 0.78 + 1, 4); ctx.closePath(); ctx.fillStyle = '#40dfff'; ctx.fill();
  ctx.restore();
  if (!pilDrawSprite(ctx, pilTop(hero.ship, hero.company), hx, hy, IS * 1.45, PILM.head + Math.PI / 2)) pilChevron(ctx, hx, hy, PILM.head, 9, '#40dfff');
  PILM.hits.push({ x: hx, y: hy, r: IS * 0.6, kind: 'hero', d: hero });
  // the rectangle being drawn
  const dr = PILM.drag;
  if (dr && dr.rect) {
    const [a, b] = dr.rect, x0 = X(Math.min(a[0], b[0])), y0 = Y(Math.min(a[1], b[1])), w = Math.abs(a[0] - b[0]) * s, hh = Math.abs(a[1] - b[1]) * s;
    ctx.fillStyle = dr.tool === 'work' ? 'rgba(64,223,255,.12)' : 'rgba(255,93,108,.16)';
    ctx.fillRect(x0, y0, w, hh);
    ctx.strokeStyle = dr.tool === 'work' ? '#40dfff' : '#ff5d6c'; ctx.setLineDash([6, 4]); ctx.lineWidth = 1.5; ctx.strokeRect(x0, y0, w, hh); ctx.setLineDash([]);
  }
}

function pilDrawAreas(ctx, X, Y, s, r, zones) {
  const w = zones.work;
  if (w) {
    ctx.save();
    ctx.beginPath();
    ctx.rect(X(0), Y(0), r.w * s, r.h * s);
    ctx.rect(X(w[0]), Y(w[1]), (w[2] - w[0]) * s, (w[3] - w[1]) * s);
    ctx.fillStyle = 'rgba(0,0,0,.5)';
    ctx.fill('evenodd');
    ctx.restore();
    ctx.fillStyle = 'rgba(64,223,255,.045)';
    ctx.fillRect(X(w[0]), Y(w[1]), (w[2] - w[0]) * s, (w[3] - w[1]) * s);
    ctx.strokeStyle = 'rgba(64,223,255,.85)'; ctx.lineWidth = 1.5; ctx.setLineDash([8, 5]);
    ctx.strokeRect(X(w[0]), Y(w[1]), (w[2] - w[0]) * s, (w[3] - w[1]) * s); ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(64,223,255,.9)'; ctx.textAlign = 'left'; ctx.font = '600 11px Bahnschrift, "Segoe UI", sans-serif';
    ctx.fillText(T('Work area'), X(w[0]) + 6, Y(w[1]) + 14);
  }
  for (const a of zones.avoid || []) {
    const x0 = X(a[0]), y0 = Y(a[1]), aw = (a[2] - a[0]) * s, ah = (a[3] - a[1]) * s;
    ctx.save();
    ctx.beginPath(); ctx.rect(x0, y0, aw, ah); ctx.clip();
    ctx.fillStyle = 'rgba(255,93,108,.08)'; ctx.fillRect(x0, y0, aw, ah);
    ctx.strokeStyle = 'rgba(255,93,108,.28)'; ctx.lineWidth = 1;
    ctx.beginPath();
    for (let k = -ah; k < aw; k += 10) { ctx.moveTo(x0 + k, y0 + ah); ctx.lineTo(x0 + k + ah, y0); }
    ctx.stroke();
    ctx.restore();
    ctx.strokeStyle = 'rgba(255,93,108,.8)'; ctx.lineWidth = 1.5; ctx.strokeRect(x0, y0, aw, ah);
  }
  ctx.textAlign = 'center';
}

function pilChevron(ctx, x, y, ang, size, color) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(ang);
  ctx.beginPath(); ctx.moveTo(size, 0); ctx.lineTo(-size * 0.7, size * 0.65); ctx.lineTo(-size * 0.3, 0); ctx.lineTo(-size * 0.7, -size * 0.65); ctx.closePath();
  ctx.fillStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 8; ctx.fill();
  ctx.restore();
}

function pilStar(ctx, x, y, r) {
  ctx.beginPath();
  for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? r * 0.45 : r; ctx.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr); }
  ctx.closePath(); ctx.fillStyle = '#ffb94d'; ctx.shadowColor = '#ffb94d'; ctx.shadowBlur = 6; ctx.fill(); ctx.shadowBlur = 0;
}

// target lock: four amber corners turning slowly
function pilLock(ctx, x, y, r, now) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(now / 1600);
  ctx.strokeStyle = '#ffb94d'; ctx.lineWidth = 2; ctx.shadowColor = '#ffb94d'; ctx.shadowBlur = 6;
  const c = r * 0.45;
  for (let i = 0; i < 4; i++) { ctx.rotate(Math.PI / 2); ctx.beginPath(); ctx.moveTo(r, r - c); ctx.lineTo(r, r); ctx.lineTo(r - c, r); ctx.stroke(); }
  ctx.restore();
}

// ---- map input: zoom, pan, hover, click, drawing the areas
function pilMapEvents() {
  const cv = PILM.cv, at = e => { const rc = cv.getBoundingClientRect(); return [e.clientX - rc.left, e.clientY - rc.top]; };
  cv.addEventListener('wheel', e => {
    if (!PILM.r) return;
    e.preventDefault();
    const [px, py] = at(e), [wx, wy] = pilWorld(px, py), v = PILM.view;
    v.s = Math.max(PILM.fitS, Math.min(PILM.fitS * 12, v.s * Math.exp(-e.deltaY * 0.0015)));
    v.x = wx - px / v.s; v.y = wy - py / v.s;
    pilClamp();
  }, { passive: false });
  cv.addEventListener('dblclick', () => { pilFit(); PILM.follow = true; pilMapButtons(); });
  cv.addEventListener('pointerdown', e => {
    if (!PILM.r || e.button !== 0) return;
    const [px, py] = at(e);
    cv.setPointerCapture(e.pointerId);
    PILM.drag = { px, py, x: PILM.view.x, y: PILM.view.y, moved: false, tool: PILM.tool, start: pilWorld(px, py) };
  });
  cv.addEventListener('pointermove', e => {
    const [px, py] = at(e), dr = PILM.drag;
    if (PILM.r) { const [wx, wy] = pilWorld(px, py); PILM.coordEl.textContent = fmtN(Math.round(wx)) + ' / ' + fmtN(Math.round(wy)); }
    if (dr) {
      if (Math.hypot(px - dr.px, py - dr.py) > 4) dr.moved = true;
      if (!dr.moved) return;
      if (dr.tool === 'look') {
        PILM.follow = false; pilMapButtons();
        PILM.view.x = dr.x - (px - dr.px) / PILM.view.s; PILM.view.y = dr.y - (py - dr.py) / PILM.view.s;
        pilClamp();
      } else if (dr.tool === 'work' || dr.tool === 'avoid') {
        const r = PILM.r, [wx, wy] = pilWorld(px, py);
        dr.rect = [dr.start.map((c, i) => Math.max(0, Math.min(i ? r.h : r.w, c))), [Math.max(0, Math.min(r.w, wx)), Math.max(0, Math.min(r.h, wy))]];
      }
      pilTip(null);
      return;
    }
    pilTip(PILM.tool === 'look' ? pilHit(px, py) : null, px, py);
  });
  cv.addEventListener('pointerup', e => {
    const dr = PILM.drag, [px, py] = at(e);
    PILM.drag = null;
    if (!dr) return;
    if (dr.tool === 'look' && !dr.moved) {
      const hit = pilHit(px, py);
      if (hit && (hit.kind === 'alien' || hit.kind === 'portal' || hit.kind === 'pilot')) pilPopOpen(hit, px, py); else pilPopClose();
    } else if ((dr.tool === 'work' || dr.tool === 'avoid') && dr.rect) {
      const [a, b] = dr.rect, rect = [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])].map(Math.round);
      if (rect[2] - rect[0] < 200 || rect[3] - rect[1] < 200) return toast(T('Too small: drag a bigger rectangle.'), 'info');
      const z = pilZonesCopy(), m = String(PILM.r.map), e2 = z[m] || (z[m] = {});
      if (dr.tool === 'work') e2.work = rect;
      else {
        if ((e2.avoid || []).length >= 8) return toast(T('At most 8 areas to avoid on a map.'), 'info');
        e2.avoid = [...(e2.avoid || []), rect];
      }
      pilSave({ zones: z }, dr.tool === 'work' ? T('Work area saved.') : T('Area to avoid saved.')).then(pilRefreshAliens);
      if (dr.tool === 'work') pilTool('look');                  // one work area per map: back to looking
    } else if (dr.tool === 'erase' && !dr.moved) {
      const [wx, wy] = pilWorld(px, py), z = pilZonesCopy(), m = String(PILM.r.map), e2 = z[m] || {};
      const inR = q => wx >= q[0] && wx <= q[2] && wy >= q[1] && wy <= q[3];
      const i = (e2.avoid || []).findIndex(inR);
      if (i >= 0) e2.avoid.splice(i, 1);
      else if (e2.work && inR(e2.work)) delete e2.work;
      else return toast(T('No area here: click inside one.'), 'info');
      pilSave({ zones: z }, T('Area removed.')).then(pilRefreshAliens);
    }
  });
  cv.addEventListener('pointerleave', () => { pilTip(null); PILM.coordEl.textContent = ''; });
}

function pilHit(px, py) {
  let best = null, bd = 1e9;
  for (const h_ of PILM.hits) {
    const d = Math.hypot(h_.x - px, h_.y - py);
    if (d <= h_.r + 4 && d < bd) { bd = d; best = h_; }
  }
  return best;
}

function pilZonesCopy() { return JSON.parse(JSON.stringify(PIL.data.config.zones || {})); }

// the hover card: what is under the pointer
function pilTip(hit, px, py) {
  const el = PILM.tipEl, r = PILM.r;
  PILM.el.classList.toggle('hovering', !!hit && ['alien', 'portal', 'pilot'].includes(hit.kind));
  if (!hit || !r) { el.style.display = 'none'; return; }
  const row = (k, v) => h('div', { class: 'pil-tip-row' }, h('span', null, k), h('span', null, v));
  let body;
  if (hit.kind === 'alien') {
    const [, tip, , , , , hpPct, f] = hit.d, type = r.types[tip] || {};
    body = [h('div', { class: 'pil-tip-head' }, pilSprite(type.icon, 26), h('b', null, pilName(type.name))),
      row(T('HP'), hpPct + ' %'), row(T('Behaviour'), f & 2 ? T('Attacking you') : f & 1 ? T('Attacks you on sight') : T('Attacks only when hit')),
      row(T('Hunted here'), f & 8 ? T('Yes') : T('No')), f & 16 ? row(T('Priority'), T('Yes')) : null, f & 32 ? row(T('Left alone'), T('took no damage')) : null,
      !(f & 4) ? row(T('Can be attacked'), T('No')) : null];
  } else if (hit.kind === 'pilot') {
    const [, name, , , , , comp, ship, hostile, attacking] = hit.d;
    body = [h('div', { class: 'pil-tip-head' }, gameIcon(ship, 26, null, 'ship'), h('b', null, name)), row(T('Company'), PIL_COMPANY[comp]?.[0] || '—'),
      row(T('Ship'), ship ? itemName(ship) : '—'), row(T('Danger'), attacking ? T('Firing at you') : hostile ? T('Can attack you') : T('Friendly'))];
  } else if (hit.kind === 'portal') {
    body = [h('div', { class: 'pil-tip-head' }, art('map_portal', 'pil-tip-ic'), h('b', null, hit.d.name ? T('Portal to {0}', hit.d.name) : T('Portal')))];
  } else if (hit.kind === 'box') {
    body = [h('b', null, { bonus: T('Bonus box'), cargo: T('Cargo box'), event: T('Event box') }[hit.d] || T('Box'))];
  } else if (hit.kind === 'ore') {
    const o = (PIL.cat.ores || []).find(x => x.id === hit.d);
    body = [h('b', null, o ? itemName(o.loot) : T('Ore'))];
  } else if (hit.kind === 'station') {
    body = [h('b', null, T('Station')), row(T('Company'), PIL_COMPANY[hit.d[3]]?.[0] || '—')];
  } else if (hit.kind === 'giver') {
    body = [h('b', null, T('Quest giver'))];
  } else {
    body = [h('b', null, T('Your ship')), row(T('HP'), fmtN(hit.d.hp) + ' / ' + fmtN(hit.d.hp_max))];
  }
  pilFill(el, body);
  el.style.display = '';
  const w = el.offsetWidth, hh = el.offsetHeight;
  el.style.left = Math.min(PILM.W - w - 8, px + 16) + 'px';
  el.style.top = Math.max(8, Math.min(PILM.H - hh - 8, py - hh / 2)) + 'px';
}

function pilPopClose() { PILM.pop?.el.remove(); PILM.pop = null; }

// the click card: an alien's hunt and priority switches for this map, a portal's "add to the mode's maps", a pilot's details
function pilPopOpen(hit, px, py) {
  pilPopClose();
  pilTip(null);
  const el = h('div', { class: 'pil-pop' }), pop = PILM.pop = { el, hit };
  const close = h('button', { class: 'pil-x', title: T('Close'), onclick: pilPopClose }, '×');
  const r = PILM.r, mapId = String(r.map);
  pop.refresh = () => {
    if (!PILM.r) return;
    if (hit.kind === 'alien') {
      const tip = hit.d[1], type = PILM.r.types[tip] || {}, count = (PILM.r.npcs || []).filter(n => n[1] === tip).length;
      const hunted = pilHunted(mapId, tip), prio = (PIL.data.config.priority?.[mapId] || []).includes(tip);
      pilFill(el, close, h('div', { class: 'pil-pop-head' }, pilSprite(type.icon, 40), h('div', null, h('b', null, pilName(type.name)),
        h('small', null, T('{0} on this map', fmtN(count)), type.aggressive ? ' · ' + T('Aggressive') : ''))),
      h('label', { class: 'pil-check' }, h('input', { type: 'checkbox', checked: hunted, onchange: e => pilHuntSet(mapId, tip, e.target.checked) }),
        h('span', null, T('Hunt it on this map'))),
      h('label', { class: 'pil-check' }, h('input', { type: 'checkbox', checked: prio, onchange: e => pilPrioritySet(mapId, tip, e.target.checked) }),
        h('span', null, T('Priority: taken first when one is around'))));
    } else if (hit.kind === 'portal') {
      const mode = PIL.data.config.mode, path = mode === 'mining' ? 'mining.maps' : 'travel.maps', tid = hit.d.target;
      const known = (PIL.cat.maps || []).some(m => m.id === tid), list = pilGet(path) || [];
      pilFill(el, close, h('div', { class: 'pil-pop-head' }, art('map_portal', 'pil-tip-ic'), h('div', null, h('b', null, hit.d.name ? T('Portal to {0}', hit.d.name) : T('Portal')),
        h('small', null, hit.d.kind === 'map' ? T('Leads to another map') : T('Galaxy gate or event portal')))),
      hit.d.kind === 'map' && known && (mode === 'hunt' || mode === 'mining')
        ? (list.includes(tid) ? h('p', { class: 'muted small', style: { margin: 0 } }, T("{0} is already in the mode's maps.", hit.d.name))
          : btn(T("Add {0} to the mode's maps", hit.d.name), () => pilSet(path, [...list, tid]).then(() => { pop.refresh(); pilCards(); }), 'sm', 'plus'))
        : null);
    } else {
      const [, name, , , , , comp, ship, hostile, attacking] = hit.d;
      pilFill(el, close, h('div', { class: 'pil-pop-head' }, gameIcon(ship, 40, null, 'ship'), h('div', null, h('b', null, name),
        h('small', null, (PIL_COMPANY[comp]?.[0] || '—') + ' · ' + (ship ? itemName(ship) : '')))),
      h('p', { class: 'muted small', style: { margin: 0 } }, attacking ? T('Firing at you') : hostile ? T('Can attack you') : T('Friendly')));
    }
  };
  pop.refresh();
  PILM.el.append(el);
  el.style.left = Math.max(8, Math.min(PILM.W - el.offsetWidth - 8, px + 14)) + 'px';
  el.style.top = Math.max(8, Math.min(PILM.H - el.offsetHeight - 8, py - 20)) + 'px';
}

// ---- the per-map hunt and priority lists (shared by the map's click card and the Aliens card)
function pilKnownTips(mapId) {
  const st = pilSt(), on = String(st.map_id ?? '') === mapId ? (st.map_aliens || []).map(a => a.tip) : [];
  return [...new Set([...on, ...((PIL.data.config.aliens || {})[mapId] || [])])];
}
const pilHunted = (mapId, tip) => { const l = (PIL.data.config.aliens || {})[mapId] || []; return !l.length || l.includes(tip); };
function pilHuntSet(mapId, tip, on) {
  const cur = (PIL.data.config.aliens || {})[mapId] || [], known = pilKnownTips(mapId);
  const base = cur.length ? cur : known;
  const list = on ? [...new Set([...base, tip])] : base.filter(x => x !== tip);
  if (!list.length) {                          // an empty list means "every alien": the last one stays ticked
    toast(T('Keep at least one alien ticked: an empty list hunts every alien.'), 'info');
    PIL.aliensSig = ''; pilRefreshAliens(); PILM.pop?.refresh?.();
    return Promise.resolve();
  }
  const next = Object.assign({}, PIL.data.config.aliens);
  if (known.every(x => list.includes(x))) delete next[mapId]; else next[mapId] = list;
  return pilSave({ aliens: next }).then(() => { PILM.pop?.refresh?.(); PIL.aliensSig = ''; pilRefreshAliens(); });
}
function pilPrioritySet(mapId, tip, on) {
  const cur = (PIL.data.config.priority || {})[mapId] || [], next = Object.assign({}, PIL.data.config.priority);
  const list = on ? [...new Set([...cur, tip])] : cur.filter(x => x !== tip);
  if (list.length) next[mapId] = list; else delete next[mapId];
  return pilSave({ priority: next }).then(() => { PILM.pop?.refresh?.(); PIL.aliensSig = ''; pilRefreshAliens(); });
}

// The hunt list of the map the ship is on (pilot.json aliens: one list per map; a map without a list hunts every alien), with the game's
// icons and the priority star. One of its chosen aliens that is all destroyed right now keeps its row (its name remembered from earlier).
// The rows are rebuilt only when the list of aliens or the choice changes (the counts are updated in place).
function aliensList(box) {
  const d = PIL.data, st = pilSt(), onMap = st.map_aliens || [], mapId = String(st.map_id ?? ''), types = pilRadar()?.types || {};
  for (const a of onMap) PIL.alienNames[a.tip] = a.name;
  const chosen = (d.config.aliens || {})[mapId] || [], prio = (d.config.priority || {})[mapId] || [];
  const known = new Map(onMap.map(a => [a.tip, a]));
  for (const tip of chosen) if (!known.has(tip) && PIL.alienNames[tip]) known.set(tip, { tip, name: PIL.alienNames[tip], count: 0, aggressive: false });
  const sig = mapId + '|' + [...known.keys()].sort().join(',') + '|' + chosen.join(',') + '|' + prio.join(',') + '|' + Object.keys(types).length;
  if (sig === PIL.aliensSig) {
    box.querySelectorAll('[data-count]').forEach(el => { const a = known.get(el.dataset.count); el.textContent = a && a.count ? T('{0} on this map', a.count) : T('none right now'); });
    return;
  }
  PIL.aliensSig = sig;
  const all = !chosen.length;
  const rows = [...known.values()].sort((a, b) => pilName(a.name).localeCompare(pilName(b.name))).map(a => {
    const on = all || chosen.includes(a.tip), star = prio.includes(a.tip);
    return h('label', { class: 'pil-alien' + (on ? '' : ' off') },
      h('input', { type: 'checkbox', checked: on, onchange: e => pilHuntSet(mapId, a.tip, e.target.checked) }),
      pilSprite(types[a.tip]?.icon, 28),
      h('span', { class: 'pil-alien-name' }, pilName(a.name), h('small', { 'data-count': a.tip }, a.count ? T('{0} on this map', a.count) : T('none right now'))),
      a.aggressive ? h('span', { class: 'badge warn', title: T('Attacks you on sight') }, T('Aggressive')) : h('span'),
      h('button', { type: 'button', class: 'pil-star' + (star ? ' on' : ''), title: star ? T('Priority: taken first when one is around') : T('Make it a priority'),
        onclick: e => { e.preventDefault(); pilPrioritySet(mapId, a.tip, !star); } }, icon('star')));
  });
  box.replaceChildren(
    h('div', { class: 'row wrap', style: { gap: '8px' } },
      h('span', { class: 'muted small' }, all ? T('On this map, all aliens are hunted. Untick the ones to leave alone.') : T('On this map, only the ticked aliens are hunted.')),
      all ? null : btn(T('Hunt all'), () => { const next = Object.assign({}, PIL.data.config.aliens); delete next[mapId]; pilSave({ aliens: next }).then(() => { PIL.aliensSig = ''; pilRefreshAliens(); }); }, 'sm ghost')),
    rows.length ? h('div', { class: 'pil-aliens-list' }, rows) : h('div', { class: 'empty' }, T('No alien on this map right now.')),
    h('p', { class: 'muted small', style: { margin: '10px 0 0' } }, T('Tip: click an alien on the map for the same switches.')));
}

// ---- the drawn areas: this map's, and the maps that have some
const pilAreasSig = () => JSON.stringify([PIL.data.config.zones || {}, pilRadar()?.map]);
function pilAreasFill(box) {
  box._sig = pilAreasSig();
  const zones = PIL.data.config.zones || {}, r = pilRadar(), here = r ? String(r.map) : '', z = zones[here] || {};
  const size = q => fmtN(q[2] - q[0]) + ' × ' + fmtN(q[3] - q[1]);
  const save = (next, msg) => pilSave({ zones: next }, msg).then(() => pilAreasFill(box));
  const drop = (m, kind, i) => { const next = pilZonesCopy(); if (kind === 'work') delete next[m].work; else next[m].avoid.splice(i, 1); save(next, T('Area removed.')); };
  const mapName = id => (PIL.cat.maps || []).find(m => String(m.id) === id)?.name || (id === here && r ? r.name : '#' + id);
  const others = Object.keys(zones).filter(m => m !== here);
  pilFill(box,
    h('div', { class: 'pil-areas' },
      z.work ? h('div', { class: 'pil-area' }, h('span', { class: 'pil-sw sq', style: { '--c': '#40dfff' } }), h('span', null, T('Work area'), ' · ', size(z.work)),
        h('button', { class: 'pil-x', title: T('Remove'), onclick: () => drop(here, 'work') }, '×')) : null,
      (z.avoid || []).map((q, i) => h('div', { class: 'pil-area' }, h('span', { class: 'pil-sw sq', style: { '--c': '#ff5d6c' } }), h('span', null, T('Area to avoid'), ' · ', size(q)),
        h('button', { class: 'pil-x', title: T('Remove'), onclick: () => drop(here, 'avoid', i) }, '×'))),
      !z.work && !(z.avoid || []).length ? h('span', { class: 'muted small' }, r ? T('No area on {0}: the ship uses the whole map.', r.name) : T('Start the game once to fill this list.')) : null),
    h('div', { class: 'row wrap', style: { gap: '8px' } },
      btn(T('Draw a work area'), () => { pilTool('work'); PILM.el.scrollIntoView({ behavior: 'smooth', block: 'center' }); }, 'sm', 'area'),
      btn(T('Draw an area to avoid'), () => { pilTool('avoid'); PILM.el.scrollIntoView({ behavior: 'smooth', block: 'center' }); }, 'sm ghost', 'ban')),
    others.length ? h('p', { class: 'muted small', style: { margin: '12px 0 4px' } }, T('Other maps with areas:')) : null,
    others.length ? h('div', { class: 'row wrap pil-chips' }, others.map(m => h('span', { class: 'pill' }, mapName(m),
      h('button', { class: 'pil-x', title: T('Remove its areas'), onclick: () => { const next = pilZonesCopy(); delete next[m]; save(next, T('Area removed.')); } }, '×')))) : null);
}

// ------------------------------------------------------------ the cards: Hunt mode
PILC.push({ id: 'travel', tab: 'mode:hunt', order: 10, build: () => pilCard('globe', T('Maps'),
  T('The maps to hunt on, in order. The bot flies there through the portals; when a map has had nothing to hunt for a while it moves on to the next one.'),
  pilMapList('travel.maps', T('Empty: the bot stays on the map where it started.')),
  pilFields(field(T('Next map after (s) without aliens'), pilNum('travel.leave_empty_sec', 0, 3600, 10)))) });

PILC.push({ id: 'aliens', tab: ['mode:hunt', 'mode:quest'], order: 20, build: () => pilCard('alien', T('Aliens to hunt'),
  PIL.data.config.mode === 'quest' ? T('In Quests mode the quest picks the aliens; the stars still say which ones go first.') : null,
  h('div', { class: 'pil-aliens' })) });

PILC.push({ id: 'areas', tab: ['mode:hunt', 'mode:quest', 'mode:mining'], order: 25, build: () => pilCard('area', T('Areas on the map'),
  T('Draw them on the map above. In the work area the ship hunts, collects and patrols; it never enters an area to avoid. One set per map.'),
  h('div', { class: 'pil-areas-box' })) });

PILC.push({ id: 'boxes', tab: ['mode:hunt', 'mode:quest'], order: 30, build: () => pilCard('box', T('Boxes and patrol'), null,
  h('div', { class: 'row wrap', style: { gap: '14px' } },
    pilCheck('boxes.bonus', T('Bonus boxes')), pilCheck('boxes.cargo', T('Cargo boxes')), pilCheck('boxes.event', T('Event boxes'))),
  pilFields(field(T('Box distance'), pilNum('box_radius', 0, 20000, 100))),
  pilCheck('roam', T('Patrol the map when there is nothing to do'))) });

const pilOres = () => (PIL.cat.ores || []).map(o => [o.id, itemName(o.loot), itemSprite(o.loot) ? sprite(itemSprite(o.loot), 20) : null]);

PILC.push({ id: 'ore', tab: 'mode:hunt', order: 40, build: () => pilCard('cart', T('Ore'), null,
  pilCheck('ore.harvest', T('Harvest ore between fights')),
  pilOres().length ? pilPickSet('ore.types', pilOres()) : pilNoGame(),
  pilFields(field(T('Ore distance'), pilNum('ore.radius', 0, 30000, 100)), field(T('Sell when free cargo at or below'), pilNum('ore.sell_free', 0, 100000, 10))),
  pilCheck('ore.sell', T('Sell the cargo at the base when it is full, then come back'))) });

// ------------------------------------------------------------ Galaxy gate mode
PILC.push({ id: 'gates', tab: 'mode:gate', order: 10, build: () => {
  const gates = PIL.cat.gates || [];
  const cur = gates.find(g => g.key === pilGet('gates.key'));
  const label = g => g.name + ' · ' + (g.ready ? T('ready, {0} lives', g.lives) : g.built ? T('built') : T('parts {0}/{1}', g.parts, g.need));
  return pilCard('star', T('Galaxy gate'),
    T("Builds the gate with the Galaxy Gate Generator's spins when parts are missing (free energy first, then uridium within the build budget), prepares it, buys lives, enters through its portal on X-1 and plays every wave; on the other maps it does not hunt. After a death it repairs at the base and goes back in. Careful: when the last life is lost the gate and its parts are gone."),
    gates.length ? pilFields(field(T('Gate'), pilSelect('gates.key', [['', T('Choose…')], ...gates.map(g => [g.key, label(g)])])),
      field(T('Keep at least (lives)'), pilNum('gates.min_lives', 0, 10)), field(T('Lives budget (U)'), pilNum('gates.life_budget', 0, 1e8, 1000)),
      field(T('Build budget (U)'), pilNum('gates.build_budget', 0, 1e9, 1000)),
      field(T('Leave the gate at (lives, 0: never)'), pilNum('gates.leave_lives', 0, 10))) : pilNoGame(),
    cur ? h('div', { class: 'pil-gauges', style: { margin: '0 0 12px' } },
      pilGauge(T('Waves'), cur.wave, cur.waves, 'var(--accent)', (cur.wave + 1) + ' / ' + cur.waves),
      pilGauge(T('Parts'), cur.parts, cur.need, 'var(--violet)', cur.parts + ' / ' + cur.need),
      pilGauge(T('Lives'), cur.lives, Math.max(cur.lives, 10), 'var(--ok)', String(cur.lives))) : null,
    pilCheck('gates.repeat', T("Once completed, play it again (built again within the build budget)")),
    h('p', { class: 'desc', style: { marginTop: '12px' } }, T('When the gate is done or cannot be played (not built, no life left, no route):')),
    pilThen('gates', 'gate'));
} });

// ------------------------------------------------------------ Quests mode
// The quest to play: Automatic or one of the accepted quests (the ones the bot cannot play are shown but cannot be chosen).
function pilQuestPick() {
  const list = PIL.cat.quests || [], cur = pilGet('quests.qid') || 0;
  const known = list.some(q => q.id === cur);
  return h('select', { class: 'input', onchange: e => pilSet('quests.qid', +e.target.value).then(pilCards) },
    h('option', { value: 0, selected: !cur }, T('Automatic: the first quest that can be played')),
    !cur || known ? null : h('option', { value: cur, selected: true }, T('Quest {0} (no longer accepted)', cur)),
    list.map(q => h('option', { value: q.id, selected: q.id === cur, disabled: !q.playable && q.id !== cur },
      q.playable ? q.name : T('{0} (the bot cannot play it)', q.name))));
}

PILC.push({ id: 'quests', tab: 'mode:quest', order: 10, build: () => {
  const chosen = pilGet('quests.qid');
  return pilCard('note', T('Quests'),
    T("The active quests lead the bot: it hunts only the aliens a quest asks for, on its maps; it also visits maps and coordinates (the pirate and Blacklight maps and LoW too), covers distances, collects boxes and ore (refined, or from the aliens that drop it), plays galaxy gates (built within the Galaxy gate budget), fights enemy pilots (with the player bots on), uses the laboratory, slot bar, Skylab and Assembly, and returns to the quest giver. Quests against the clock come first; the quests' restrictions (forbidden aliens or ammo, no death) are kept."),
    pilFields(field(T('Quest to play'), pilQuestPick())),
    (PIL.cat.quests || []).length ? null : h('p', { class: 'muted small' }, T('No accepted quest: take one in the game (or let the bot take one below).')),
    chosen ? h('p', { class: 'muted small' }, T('Only this quest is played; no other quest is taken.'))
      : pilCheck('quests.accept', T('Take a new quest at a quest giver when none can be played')),
    h('p', { class: 'desc', style: { marginTop: '12px' } }, chosen ? T('When this quest is done or cannot be played:') : T('When no quest can be played nor taken:')),
    pilThen('quests', 'quest'));
} });

// ------------------------------------------------------------ Mining mode
PILC.push({ id: 'mining', tab: 'mode:mining', order: 10, build: () => pilCard('cart', T('Mining'),
  T('The ship only harvests ore (it does not hunt, it only fights back) and sells the cargo at the base when it is full, then comes back.'),
  pilMapList('mining.maps', T('Empty: the bot stays on the map where it started.')),
  pilOres().length ? pilPickSet('mining.types', pilOres()) : pilNoGame(),
  pilFields(field(T('Ore distance'), pilNum('mining.radius', 0, 30000, 100)), field(T('Sell when free cargo at or below'), pilNum('mining.sell_free', 0, 100000, 10)),
    field(T('Next map after (s) without ore'), pilNum('mining.leave_empty_sec', 0, 3600, 10)))) });

// ------------------------------------------------------------ Combat
PILC.push({ id: 'combat', tab: 'combat', order: 10, build: () => {
  const slowCheck = (loot, label) => h('label', { class: 'pil-check' }, h('input', { type: 'checkbox', checked: (pilGet('slow_ammo') || []).includes(loot),
    onchange: e => { const cur = pilGet('slow_ammo') || []; pilSet('slow_ammo', e.target.checked ? [...cur, loot] : cur.filter(x => x !== loot)); } }),
    gameIcon(loot, 20, null, 'ammo'), h('span', null, T('Use {0}', label)));
  return pilCard('play', T('Combat'),
    T('The ship keeps firing and stays between these two distances from its target (share of your laser range): it backs off when the target comes closer and follows it when it moves away. Aliens attacking you come first, then the nearest.'),
    pilFields(
      field(T('Closest (%)'), pilNum('kite_min', 30, 98, 1, 100)), field(T('Farthest (%)'), pilNum('kite_max', 35, 99, 1, 100)),
      field(T('Safety margin'), pilNum('threat_margin', 0, 2000, 10)),
      field(T('Laser ammo'), pilSelect('laser_ammo', [['', T('Keep the selected ammo')], ...PIL.data.ammo.map(a => [a, itemName(a)])])),
      field(T('Rocket'), pilSelect('rocket_ammo', [['', T('Keep the selected rocket')], ...(PIL.data.rockets || []).map(a => [a, itemName(a)])])),
      field(T('Give up a target after (s) without damage'), pilNum('stuck_sec', 0, 600, 5))),
    h('div', { class: 'pil-col' },
      pilCheck('rockets', T('Fire rockets'), T('The selected rocket flies at the target each time it is ready, while the target is within rocket range.')),
      pilCheck('launcher', T('Fire the rocket launcher when it is full'), T('The rocket launcher (RL-LB1, HST) fires its load at the target once it is fully loaded.')),
      pilCheck('avoid_aggressive', T('Avoid aggressive aliens'),
        T('While fighting or patrolling, keep away from the aggressive aliens that are not attacking yet.')),
      pilCheck('clear_path', T('Clear the path between maps'),
        T('On the way to another map (or the gate, the base, a quest giver), destroy the aggressive aliens attacking the ship or about to. Off: the ship keeps going.')),
      pilCheck('defend', T('Defend the work map'),
        T('On the map the mode works on (hunting, mining, the quest), fight back against the aliens attacking the ship. Off: it ignores them and goes on.'))),
    h('p', { class: 'desc', style: { marginTop: '12px' } }, T('Fire RCB-140 / RSB-75 each time their 3 s cooldown ends (RCB-140 first), then go back to the normal ammo.')),
    h('div', { class: 'row wrap', style: { gap: '14px' } }, slowCheck('ammunition_laser_rcb-140', 'RCB-140'), slowCheck('ammunition_laser_rsb-75', 'RSB-75')),
    h('p', { class: 'desc', style: { marginTop: '12px' } },
      T('Below the first shield threshold, fire SAB-50 at shielded aliens (your target first, else an attacker in range) until the shield is back to the second. Needs a shield and SAB-50 in stock.')),
    h('div', { class: 'row wrap', style: { gap: '14px', alignItems: 'center' } },
      h('label', { class: 'pil-check' }, h('input', { type: 'checkbox', checked: !!pilGet('sab.enabled'), onchange: e => pilSet('sab.enabled', e.target.checked) }),
        gameIcon('ammunition_laser_sab-50', 20, null, 'ammo'), h('span', null, T('Use {0}', 'SAB-50')))),
    pilFields(field(T('Shield below (%)'), pilNum('sab.start_pct', 0, 99, 1)), field(T('Until shield at (%)'), pilNum('sab.stop_pct', 1, 100, 1))));
} });

// ------------------------------------------------------------ Support
PILC.push({ id: 'support', tab: 'support', order: 10, build: () => pilCard('zap', T('Abilities and technologies'),
  T('Each rule fires an ability or a technology when its condition holds, as soon as its cooldown allows.'),
  pilRuleList('support.rules', () => { const it = [...(PIL.cat.abilities || []), ...(PIL.cat.techs || [])][0]; return it ? { item: it, when: 'fight', value: 50 } : null; },
    (r, set) => {
      const items = [...(PIL.cat.abilities || []), ...(PIL.cat.techs || [])];
      return [gameIcon(r.item, 28, null, 'zap'), h('select', { class: 'input', onchange: e => set({ item: e.target.value }) },
        [...new Set([r.item, ...items])].map(it => h('option', { value: it, selected: it === r.item }, itemName(it)))),
      h('select', { class: 'input', onchange: e => set({ when: e.target.value }) }, PIL_WHEN.map(([v, l]) => h('option', { value: v, selected: v === r.when }, T(l)))),
      ['hp', 'shield', 'big'].includes(r.when) ? h('input', { class: 'input num', type: 'number', min: 0, value: r.value,
        onchange: e => { if (e.target.value !== '') set({ value: +e.target.value }); } }) : null];
    })) });

PILC.push({ id: 'pet', tab: 'support', order: 20, build: () => {
  const opts = (PIL.cat.pet_gears || []).map(g => [g.id, g.name]);
  return pilCard('shield', T('Configuration and P.E.T.'), null,
    pilCheck('config_switch.enabled', T('Switch to the other config when the shield is low (if the shield it kept is fuller)')),
    pilFields(field(T('Shield below (%)'), pilNum('config_switch.shield_pct', 0, 100))),
    PIL.cat.has_pet === false ? h('p', { class: 'muted small' }, T('You have no P.E.T.')) : h('div', null,
      pilCheck('pet.enabled', T('Keep the P.E.T. out')),
      opts.length ? pilFields(
        field(T('Gear'), pilSelect('pet.gear', opts, Number)),
        field(T('Low HP gear'), pilSelect('pet.low_hp_gear', [[0, T('None')], ...opts], Number)),
        field(T('Below (% HP)'), pilNum('pet.low_hp_pct', 0, 100)),
        field(T('Repair up to (U)'), pilNum('pet.repair_max', 0, 10000000, 100))) : pilNoGame(),
      pilCheck('pet.repair', T('Repair the P.E.T. when it is destroyed'))));
} });

PILC.push({ id: 'supply', tab: 'support', order: 30, build: () => pilCard('cart', T('Ammo resupply'),
  T('Buy ammo when its stock falls below a threshold (silent purchase, within the budgets of the session).'),
  pilRuleList('supply.rules', () => { const a = (PIL.cat.buy_ammo || [])[0]; return a ? { loot: a, below: 1000, amount: 10000 } : null; },
    (r, set) => [
      gameIcon(r.loot, 28, null, 'ammo'),
      h('select', { class: 'input', onchange: e => set({ loot: e.target.value }) },
        [...new Set([r.loot, ...(PIL.cat.buy_ammo || [])])].map(a => h('option', { value: a, selected: a === r.loot }, itemName(a)))),
      h('span', { class: 'muted small' }, T('below')),
      h('input', { class: 'input num', type: 'number', min: 0, step: 100, value: r.below, onchange: e => { if (e.target.value !== '') set({ below: +e.target.value }); } }),
      h('span', { class: 'muted small' }, T('buy')),
      h('input', { class: 'input num', type: 'number', min: 1, step: 100, value: r.amount, onchange: e => { if (e.target.value !== '') set({ amount: +e.target.value }); } })]),
  pilFields(field(T('Credits budget'), pilNum('supply.max_credits', 0, 1e11, 10000)), field(T('Uridium budget'), pilNum('supply.max_uridium', 0, 1e9, 100)))) });

// ------------------------------------------------------------ Safety
PILC.push({ id: 'safety', tab: 'safety', order: 10, build: () => pilCard('alert', T('Safety'),
  T('Below this HP the ship stops fighting, flies to the nearest safe zone (station or portal) and repairs with the repair robot, then resumes. On a map without a safe zone it flies away from the aliens.'),
  pilFields(field(T('Flee below (% HP)'), pilNum('flee_hp', 0, 95)), field(T('Resume at (% HP)'), pilNum('resume_hp', 5, 100)))) });

PILC.push({ id: 'recover', tab: 'safety', order: 20, build: () => pilCard('refresh', T('After a death'),
  T('Repair at the base (free) and fly back to where the mode was. One more death than allowed stops the bot.'),
  pilCheck('recover.revive', T('Repair and come back')),
  pilFields(field(T('Repairs per session'), pilNum('recover.max_revives', 0, 1000)))) });

PILC.push({ id: 'players', tab: 'safety', order: 30, build: () => pilCard('users', T('Enemy pilots'),
  T('Players of another company (friend server) and player bots: what to do when one comes close or fires at your ship.'),
  pilCheck('players.enabled', T('Watch for enemy pilots')),
  pilFields(
    field(T('Reaction'), pilSelect('players.action', [['flee', T('Hide in a safe zone')], ['map', T("Go to another of the mode's maps")], ['stop', T('Stop')]])),
    field(T('Distance'), pilNum('players.distance', 0, 20000, 100)),
    field(T('Stay hidden (s)'), pilNum('players.wait_sec', 0, 3600, 10)),
    field(T('Avoid the map (min)'), pilNum('players.avoid_min', 1, 1440))),
  pilCheck('players.attack_only', T('Only when one fires at me'))) });

// ------------------------------------------------------------ Settings
async function pilProfile(action, name) {
  const r = await act(() => api('/api/pilot/profile', { action, name }), action === 'delete' ? T('Profile deleted.') : action === 'load' ? T('Profile loaded.') : T('Profile saved.'));
  if (r) { PIL.seq++; PIL.data = r; pilTabs(); pilCards(); pilCommand(); }
}

PILC.push({ id: 'profiles', tab: 'settings', order: 10, build: () => {
  const c = PIL.data.config, names = Object.keys(c.profiles || {}).sort((a, b) => a.localeCompare(b));
  const cur = c.profile || '';
  const pick = h('select', { class: 'input', onchange: e => e.target.value && pilProfile('load', e.target.value) },
    h('option', { value: '', selected: !cur }, names.length ? T('Load a profile…') : T('No profile yet')),
    names.map(n => h('option', { value: n, selected: n === cur }, n)));
  return pilCard('save', T('Profiles'), T('Save these settings under a name and switch between them in one click (for example "Farm X-1" or "Gate"). The areas drawn on the maps are part of a profile.'),
    h('div', { class: 'row wrap', style: { gap: '8px' } }, pick,
      cur ? btn(T('Save'), () => pilProfile('save', cur), 'sm', 'save') : null,
      btn(T('Save as…'), async () => { const n = await promptBox(T('New profile'), T('Name'), cur); if (n) pilProfile('save', n); }, 'sm ghost', 'plus'),
      cur ? btn(T('Delete'), async () => { if (await confirmBox(T('Delete the profile?'), cur, { ok: T('Delete'), danger: true })) pilProfile('delete', cur); }, 'sm ghost', 'trash') : null));
} });

PILC.push({ id: 'stop', tab: 'settings', order: 20, build: () => pilCard('stop', T('Stop conditions'), T('0 switches a condition off.'),
  pilFields(field(T('After (minutes)'), pilNum('stop.minutes', 0, 100000)), field(T('After (aliens)'), pilNum('stop.kills', 0, 10000000)),
    field(T('Laser ammo below'), pilNum('stop.ammo_below', 0, 100000000, 100))),
  pilCheck('stop.go_home', T('Fly to the base before stopping'))) });

PILC.push({ id: 'advanced', tab: 'settings', order: 30, build: () => pilCard('sliders', T('Advanced'),
  T('How the ship is moved. If the ship stutters or does not move, try the other one.'),
  pilFields(field(T('Movement'), pilSelect('move_mode', [['hero_move', T('The game flies the ship (recommended)')], ['server', T('The server moves the ship')]])),
    field(T('Pause after a manual move (s)'), pilNum('pause_sec', 0, 120)))) });
