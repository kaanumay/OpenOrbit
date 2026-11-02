/* Auto Mode page (In-game section, Beta): the server flies your ship (server/pilot/). Settings go to /api/pilot (pilot_panel.py, pilot.json
   next to the save); the bot's status comes back from the game server every second. Loaded after panel.js: it adds its own entry to PAGES,
   RENDER and the In-game pages' tab bar (GAME_PAGES); boot() builds the menu after every script has loaded. Kept in its own files (this one
   and pilot.css): a local feature.
   Layout: the In-game bar (gameHeader), a compact status card with the mode selector (Hunt, Galaxy gate, Quests, Mining), then the settings
   in tabs (PIL_TABS): the first one is the chosen mode's ('mode:<mode>' cards), the others are shared. Every card is an entry of PILC
   ({id, tab (or a list of tabs), order, build}).
   Settings: every field edits one setting by its path ('flee_hp', 'pet.gear') and sends only that value; the panel merges a card's value
   into its block (pilot_panel.py). A poll that started before a save does not overwrite it (PIL.seq). */
'use strict';

// The panel has no 'bot' icon yet: a small robot head (also fills the Bots page's empty icon).
if (!ICONS.bot) ICONS.bot = '<rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 8V4"/><circle cx="12" cy="3" r="1"/><circle cx="9" cy="14" r="1.2" fill="currentColor"/><circle cx="15" cy="14" r="1.2" fill="currentColor"/><path d="M2 13v3M22 13v3"/>';
PAGES.push({ id: 'pilot', name: N('Auto Mode'), ic: 'bot', game: true, beta: true, sub: N('The server flies your ship: it fights aliens at the edge of your laser range, collects boxes and repairs at low HP.') });
GAME_PAGES.push(['pilot', N('Auto Mode'), '', 'bot']);
RENDER.pilot = () => renderPilot();

const PIL = { data: null, cat: {}, tab: null, seq: 0, timer: null, polling: false, aliensSig: '', alienNames: {} };
const PILC = [];           // settings cards: {id, tab, order, build}
const PIL_MODES = { hunt: [N('Hunt'), 'search'], gate: [N('Galaxy gate'), 'star'], quest: [N('Quests'), 'note'], mining: [N('Mining'), 'cart'] };
// 'mode' is the chosen mode's tab (its name and icon come from PIL_MODES)
const PIL_TABS = [['mode', '', ''], ['combat', N('Combat'), 'play'], ['support', N('Support'), 'zap'], ['safety', N('Safety'), 'shield'],
  ['settings', N('Settings'), 'sliders']];
const PIL_STATE = { off: N('Stopped'), running: N('Running'), paused: N('Paused') };
const PIL_MODE = {
  fight: N('Fighting'), box: N('Collecting a box'), roam: N('Patrolling'), gate: N('Going to the next wave'), flee: N('Going to a safe zone'),
  repair: N('Repairing'), idle: N('Waiting'), travel: N('Flying to the hunting map'), home: N('Going to the base before stopping'), sell: N('Going to sell the cargo'),
  ore: N('Harvesting ore'), hide: N('Hiding from an enemy pilot'), quest: N('Going to a quest giver'), gate_trip: N('Going to the galaxy gate'),
};
const PIL_REASON = {
  dead: N('Your ship is destroyed.'), jumping: N('Jumping through a portal.'), manual: N('You moved the ship: resuming in {0} s.'),
  client_autopilot: N("The game's own autopilot (Omega AutoTactic) is on: switch it off (F12)."), no_repair_robot: N('No repair robot: waiting in the safe zone.'),
};
const PIL_STOP = {
  time: N('Time limit reached.'), kills: N('Number of aliens reached.'), ammo: N('Out of laser ammo.'), dead: N('Ship destroyed (no repair left).'),
  players: N('Enemy pilot nearby.'), gate_done: N('Galaxy gate completed.'), gate_not_built: N('The galaxy gate is not built.'),
  gate_lives: N('No life left for the galaxy gate.'), gate_no_route: N('No route to the galaxy gate.'), gate_none: N('No galaxy gate chosen.'),
  no_quest: N('No quest to play.'), quest_done: N('The chosen quest is done.'), quest_gone: N('The chosen quest is no longer accepted.'),
};
const PIL_WHEN = [['hp', N('HP below (%)')], ['shield', N('Shield below (%)')], ['fight', N('While fighting')], ['big', N('Target HP at least')], ['always', N('As soon as ready')]];
// A mode's "then" setting: what the bot does when the mode has nothing left to do.
const PIL_THEN = [['stop', N('Stop')], ['hunt', N('Switch to Hunt')], ['quest', N('Switch to Quests')], ['mining', N('Switch to Mining')]];

// Small per-browser memory (the open tab, the folded statistics); the page works without it.
const pilMem = (k, v) => { try { if (v === undefined) return localStorage.getItem('pil-' + k); localStorage.setItem('pil-' + k, v); } catch (e) { /* no storage */ } return null; };

// ------------------------------------------------------------ the page
async function renderPilot() {
  clearInterval(PIL.timer);
  await loadGameImages();
  try { PIL.data = await api('/api/pilot'); } catch (e) { return gameError(e, 'pilot'); }
  if (!PIL.data.online) return gameError(new Error(T('Opens once you have logged in to the game.')), 'pilot');     // the other In-game pages' text
  if (PIL.data.status?.catalog) PIL.cat = PIL.data.status.catalog;
  if (!PIL.tab) { const t = pilMem('tab'); PIL.tab = PIL_TABS.some(([k]) => k === t) ? t : 'mode'; }
  const header = h('div'), statusCard = h('div', { class: 'card pil-status' }), cards = h('div', { class: 'grid pil-cards' });
  const mode = PIL_MODES[PIL.data.config.mode] || PIL_MODES.hunt;
  const tabs = h('div', { class: 'seg pil-tabs' }, PIL_TABS.map(([k, t, ic]) => h('button', { class: k === PIL.tab ? 'on info' : '', onclick: () => {
    PIL.tab = k; pilMem('tab', k);
    tabs.querySelectorAll('button').forEach((b, i) => b.className = PIL_TABS[i][0] === k ? 'on info' : '');
    pilCards(cards);
  } }, icon(k === 'mode' ? mode[1] : ic), T(k === 'mode' ? mode[0] : t))));
  $('#content').replaceChildren(h('div', { class: 'stack' }, header, statusCard, tabs, cards));
  pilCards(cards);
  pilRefresh(header, statusCard, cards);
  PIL.timer = setInterval(async () => {
    if (!statusCard.isConnected) return clearInterval(PIL.timer);
    if (document.visibilityState !== 'visible' || PIL.polling) return;
    PIL.polling = true;
    const seq = PIL.seq;
    try {
      const d = await api('/api/pilot');
      if (seq !== PIL.seq) return;                  // a save went out meanwhile: its answer is newer
      PIL.data = d;
    } catch (e) { return; } finally { PIL.polling = false; }
    if (!PIL.data.online) return renderPilot();
    if (PIL.data.status?.catalog) PIL.cat = PIL.data.status.catalog;
    pilRefresh(header, statusCard, cards);
  }, 1000);
  S.timers.push(PIL.timer);
}

// The active tab's cards (the mode tab: the chosen mode's cards, 'mode:<mode>').
function pilCards(box) {
  PIL.aliensSig = '';
  const tab = PIL.tab === 'mode' ? 'mode:' + PIL.data.config.mode : PIL.tab;
  box.replaceChildren(...PILC.filter(c => [].concat(c.tab).includes(tab)).sort((a, b) => a.order - b.order).map(c => c.build()));
  pilRefreshAliens(box);
}

function pilRefresh(header, statusCard, cards) {
  header.replaceChildren(gameHeader(PIL.data.status, 'pilot'));
  pilotStatus(statusCard);
  pilRefreshAliens(cards);
}

function pilRefreshAliens(box) {
  const aliens = box.querySelector('.pil-aliens');
  if (aliens) aliensList(aliens);
}

// ------------------------------------------------------------ settings: one path per setting ('flee_hp', 'pet.gear')
const pilGet = path => path.split('.').reduce((o, k) => (o == null ? o : o[k]), PIL.data.config);
const pilSave = values => { PIL.seq++; return act(async () => { PIL.data = await api('/api/pilot', { config: values }); }, T('Saved.')); };
const pilSet = (path, v) => { const [a, b] = path.split('.'); return pilSave(b ? { [a]: { [b]: v } } : { [a]: v }); };
const pilNum = (path, min, max, step = 1, scale = 1) => h('input', { class: 'input num', type: 'number', min, max, step,
  value: scale === 1 ? pilGet(path) : Math.round(pilGet(path) * scale),
  onchange: e => { if (e.target.value !== '') pilSet(path, +e.target.value / scale); } });         // an emptied field saves nothing
const pilCheck = (path, label, title) => h('label', { class: 'pil-check', title: title || null },
  h('input', { type: 'checkbox', checked: !!pilGet(path), onchange: e => pilSet(path, e.target.checked) }), h('span', null, label));
const pilSelect = (path, options, cast = String) => h('select', { class: 'input', onchange: e => pilSet(path, cast(e.target.value)) },
  options.map(([v, l]) => h('option', { value: v, selected: String(pilGet(path)) === String(v) }, l)));
const pilFields = (...f) => h('div', { class: 'grid pil-fields' }, ...f);
const pilNoGame = () => h('p', { class: 'muted small' }, T('Start the game once to fill this list.'));
const pilCard = (ic, title, desc, ...body) => h('div', { class: 'card' }, h('h2', null, icon(ic), title), desc ? h('p', { class: 'desc' }, desc) : null, ...body);
const pilThen = (block, own) => pilFields(field(T('Then'), pilSelect(block + '.then', PIL_THEN.filter(([k]) => k !== own).map(([k, l]) => [k, T(l)]))));

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
    box.replaceChildren(...items.map(([id, label]) => h('label', { class: 'pil-check' },
      h('input', { type: 'checkbox', checked: all || sel.includes(id), onchange: e => {
        const cur = pilGet(path) || [];
        const base = cur.length ? cur : items.map(([x]) => x);
        const list = e.target.checked ? [...new Set([...base, id])] : base.filter(x => x !== id);
        pilSet(path, list.length === items.length ? [] : list).then(draw);
      } }), h('span', null, label))));
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

// ------------------------------------------------------------ the status card
// State, the mode selector and Start/Stop, one line of what the ship is doing, the statistics folded below. Its frame, the mode selector,
// the Start/Stop button (until the state changes) and the statistics (until they change) are not rebuilt by the refresh every second.
function pilotStatus(card) {
  const d = PIL.data, st = d.status, cfg = d.config;
  const on = cfg.enabled;
  if (!card._pil) {
    const modeSel = h('select', { class: 'input pil-mode', title: T('Mode'), onchange: e => pilSet('mode', e.target.value).then(() => RENDER.pilot()) },
      Object.entries(PIL_MODES).map(([k, [name]]) => h('option', { value: k, selected: k === cfg.mode }, T(name))));
    const body = h('div');
    const more = h('details', { class: 'pil-more', open: pilMem('stats') === '1', ontoggle: e => pilMem('stats', e.target.open ? '1' : '0') },
      h('summary', null, T('Statistics and journal')), body);
    card._pil = { left: h('div', { class: 'row wrap pil-line' }), toggle: h('span'), items: h('div', { class: 'pil-items' }), body, on: null, sig: '' };
    card.replaceChildren(h('div', { class: 'row between wrap pil-head' }, card._pil.left,
      h('div', { class: 'row wrap', style: { gap: '8px' } }, h('span', { class: 'lbl' }, T('Mode')), modeSel, card._pil.toggle)), card._pil.items, more);
  }
  const p = card._pil;
  if (p.on !== on) {
    p.on = on;
    const b = btn(on ? T('Stop') : T('Start'), async () => {
      b.disabled = true;
      const r = await act(() => api(on ? '/api/pilot/stop' : '/api/pilot/start', {}));
      b.disabled = false;
      if (r) { PIL.seq++; PIL.data = r; pilotStatus(card); }
    }, on ? 'danger' : 'primary', on ? 'x' : 'play');
    p.toggle.replaceChildren(b);
  }
  const state = on ? st.state : 'off';
  const cls = state === 'running' ? 'ok' : state === 'paused' ? 'warn' : '';
  const reason = st.reason && PIL_REASON[st.reason] ? T(PIL_REASON[st.reason], st.pause_left) : '';
  const hp = st.hp_max ? Math.round(100 * st.hp / st.hp_max) : null;
  const t = st.target;
  const item = (k, v) => h('span', { class: 'pil-item' }, h('span', { class: 'lbl' }, k), ' ', h('b', null, v));
  const stopped = !on && st.stats?.stop_reason && PIL_STOP[st.stats.stop_reason] ? T(PIL_STOP[st.stats.stop_reason]) : '';
  // after a mode's end the running mode can differ from the chosen one ('then')
  const other = on && st.run_mode && st.run_mode !== cfg.mode && PIL_MODES[st.run_mode]
    ? T('Running: {0} (after {1})', T(PIL_MODES[st.run_mode][0]), T((PIL_MODES[cfg.mode] || PIL_MODES.hunt)[0])) : '';
  const fill = (el, ...kids) => el.replaceChildren(...kids.filter(Boolean));       // (replaceChildren would print a null)
  fill(p.left, h('h2', null, icon('bot'), T('Auto Mode')),
    h('span', { class: 'pill' }, dot(cls), T(PIL_STATE[state] || state)),
    on && state === 'running' && st.mode ? h('span', { class: 'pill' }, T(PIL_MODE[st.mode] || st.mode)) : null,
    other ? h('span', { class: 'pill warn' }, other) : null,
    reason ? h('span', { class: 'muted small' }, reason) : null, stopped ? h('span', { class: 'muted small' }, stopped) : null);
  fill(p.items,
    item(T('Map'), st.map || '—'), item(T('HP'), hp == null ? '—' : hp + ' %'),
    item(T('Target'), t ? t.name + ' · ' + Math.round(100 * t.hp / Math.max(1, t.hp_max)) + ' % · ' + fmtN(t.dist) + ' / ' + fmtN(t.range) : '—'),
    item(T('Map of the mode'), st.hunt_map || st.map || '—'), st.quest ? item(T('Quest'), st.quest.name) : null,
    item(T('Aliens'), fmtN(st.stats?.kills)), item(T('Boxes'), fmtN(st.stats?.boxes)),
    on && st.stats?.started ? item(T('Running for'), fmtDur(Date.now() / 1000 - st.stats.started)) : null);
  const sig = JSON.stringify(st.stats || {}) + '|' + Math.floor(Date.now() / 60000);       // the rates move once a minute
  if (sig !== p.sig) { p.sig = sig; p.body.replaceChildren(pilStats(st.stats || {})); }
}

// The session's totals and rates per hour, and the journal (newest first).
function pilStats(s) {
  const hours = s.started ? (Date.now() / 1000 - s.started) / 3600 : 0;
  const rate = k => hours >= 5 / 60 ? fmtN(Math.round((s[k] || 0) / hours)) : '—';      // after 5 minutes (earlier the rates mean little)
  const cell = (label, k) => h('div', { class: 'pil-kv' }, h('span', { class: 'lbl' }, label), h('b', null, fmtN(s[k] || 0)), h('span', { class: 'dim small' }, T('{0} per hour', rate(k))));
  const journal = (s.journal || []).slice(-8).reverse();
  return h('div', { class: 'pil-stats' },
    h('div', { class: 'pil-grid' }, cell(T('Credits'), 'credits'), cell(T('Uridium'), 'uridium'), cell(T('Experience'), 'ep'), cell(T('Honor'), 'honor'),
      h('div', { class: 'pil-kv' }, h('span', { class: 'lbl' }, T('Deaths / repairs')), h('b', null, fmtN(s.deaths || 0) + ' / ' + fmtN(s.revives || 0))),
      h('div', { class: 'pil-kv' }, h('span', { class: 'lbl' }, T('Spent')), h('b', null, fmtN(s.spent_credits || 0) + ' C · ' + fmtN(s.spent_uridium || 0) + ' U'))),
    journal.length ? h('ul', { class: 'pil-journal' }, journal.map(([t, text]) => h('li', null, h('span', { class: 'dim small' }, new Date(t * 1000).toLocaleTimeString()), ' ', text)))
      : h('p', { class: 'muted small' }, T('Nothing yet.')));
}

// The hunt list of the map the ship is on (pilot.json aliens: one list per map; a map without a list hunts every alien). Only this map's
// aliens are shown; one of its chosen aliens that is all destroyed right now keeps its box (its name remembered from earlier). The boxes are
// rebuilt only when the list of aliens or the choice changes (the counts are updated in place).
function aliensList(box) {
  const d = PIL.data, onMap = d.status?.map_aliens || [], mapId = String(d.status?.map_id ?? '');
  for (const a of onMap) PIL.alienNames[a.tip] = a.name;
  const chosenNow = () => (PIL.data.config.aliens || {})[mapId] || [];
  const chosen = chosenNow();
  const known = new Map(onMap.map(a => [a.tip, a]));
  for (const tip of chosen) if (!known.has(tip) && PIL.alienNames[tip]) known.set(tip, { tip, name: PIL.alienNames[tip], count: 0, aggressive: false });
  const sig = mapId + '|' + [...known.keys()].sort().join(',') + '|' + chosen.join(',');
  if (sig === PIL.aliensSig) {
    box.querySelectorAll('[data-count]').forEach(el => { const a = known.get(el.dataset.count); el.textContent = a && a.count ? '×' + a.count : ''; });
    return;
  }
  PIL.aliensSig = sig;
  const all = !chosen.length;
  const setList = list => {
    const next = Object.assign({}, PIL.data.config.aliens);
    if (list.length) next[mapId] = list; else delete next[mapId];
    return pilSave({ aliens: next }).then(() => aliensList(box));
  };
  const items = [...known.values()].sort((a, b) => a.name.localeCompare(b.name)).map(a => h('label', { class: 'pil-check' },
    h('input', { type: 'checkbox', checked: all || chosen.includes(a.tip), onchange: e => {
      const cur = chosenNow();
      const base = cur.length ? cur : [...known.keys()];
      const list = e.target.checked ? [...new Set([...base, a.tip])] : base.filter(x => x !== a.tip);
      setList(list.length === known.size && onMap.every(x => list.includes(x.tip)) ? [] : list);
    } }),
    h('span', null, a.name), h('span', { class: 'dim small', 'data-count': a.tip }, a.count ? '×' + a.count : ''),
    a.aggressive ? h('span', { class: 'badge warn', title: T('Attacks you on sight') }, T('Aggressive')) : null));
  box.replaceChildren(
    h('div', { class: 'row wrap', style: { gap: '8px' } },
      h('span', { class: 'muted small' }, all ? T('On this map, all aliens are hunted. Untick the ones to leave alone.') : T('On this map, only the ticked aliens are hunted.')),
      all ? null : btn(T('Hunt all'), () => setList([]), 'sm ghost')),
    items.length ? h('div', { class: 'pil-checks' }, items) : h('div', { class: 'empty' }, T('No alien on this map right now.')));
}

// ------------------------------------------------------------ the cards: Hunt mode
PILC.push({ id: 'travel', tab: 'mode:hunt', order: 10, build: () => pilCard('globe', T('Maps'),
  T('The maps to hunt on, in order. The bot flies there through the portals; when a map has had nothing to hunt for a while it moves on to the next one.'),
  pilMapList('travel.maps', T('Empty: the bot stays on the map where it started.')),
  pilFields(field(T('Next map after (s) without aliens'), pilNum('travel.leave_empty_sec', 0, 3600, 10)))) });

PILC.push({ id: 'aliens', tab: 'mode:hunt', order: 20, build: () => pilCard('bot', T('Aliens to hunt'), null, h('div', { class: 'pil-aliens' })) });

PILC.push({ id: 'boxes', tab: ['mode:hunt', 'mode:quest'], order: 30, build: () => pilCard('cart', T('Boxes and patrol'), null,
  h('div', { class: 'row wrap', style: { gap: '14px' } },
    pilCheck('boxes.bonus', T('Bonus boxes')), pilCheck('boxes.cargo', T('Cargo boxes')), pilCheck('boxes.event', T('Event boxes'))),
  pilFields(field(T('Box distance'), pilNum('box_radius', 0, 20000, 100))),
  pilCheck('roam', T('Patrol the map when there is nothing to do'))) });

const pilOres = () => (PIL.cat.ores || []).map(o => [o.id, itemName(o.loot)]);

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
    T('Prepares the gate, buys lives, enters through its portal on X-1 and plays every wave; on the other maps it does not hunt. After a death it repairs at the base and goes back in. Careful: when the last life is lost the gate and its parts are gone.'),
    gates.length ? pilFields(field(T('Gate'), pilSelect('gates.key', [['', T('Choose…')], ...gates.map(g => [g.key, label(g)])])),
      field(T('Keep at least (lives)'), pilNum('gates.min_lives', 0, 10)), field(T('Lives budget (U)'), pilNum('gates.life_budget', 0, 1e8, 1000))) : pilNoGame(),
    cur ? h('p', { class: 'muted small' }, T('Wave {0}/{1} · lives {2} · lives bought {3}/{4}', cur.wave + 1, cur.waves, cur.lives, cur.lives_bought, cur.max_bought)) : null,
    pilCheck('gates.repeat', T('Once completed, play it again if its parts are complete again')),
    h('p', { class: 'desc', style: { marginTop: '12px' } }, T('When the gate is done or cannot be played (not built, no life left, no route):')),
    pilThen('gates', 'gate'));
} });

// ------------------------------------------------------------ Quests mode
// The quest to play: Automatic or one of the accepted quests (the ones the bot cannot play are shown but cannot be chosen).
function pilQuestPick() {
  const list = PIL.cat.quests || [], cur = pilGet('quests.qid') || 0;
  const known = list.some(q => q.id === cur);
  return h('select', { class: 'input', onchange: e => pilSet('quests.qid', +e.target.value).then(() => RENDER.pilot()) },
    h('option', { value: 0, selected: !cur }, T('Automatic: the first quest that can be played')),
    !cur || known ? null : h('option', { value: cur, selected: true }, T('Quest {0} (no longer accepted)', cur)),
    list.map(q => h('option', { value: q.id, selected: q.id === cur, disabled: !q.playable && q.id !== cur },
      q.playable ? q.name : T('{0} (the bot cannot play it)', q.name))));
}

PILC.push({ id: 'quests', tab: 'mode:quest', order: 10, build: () => {
  const chosen = pilGet('quests.qid');
  return pilCard('note', T('Quests'),
    T('The active quests lead the hunt: the bot hunts the aliens of the quest on its maps; "visit a map" and "return to the quest giver" are done too.'),
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
    h('span', null, T('Use {0}', label)));
  return pilCard('play', T('Combat'),
    T('The ship keeps firing and stays between these two distances from its target (share of your laser range): it backs off when the target comes closer and follows it when it moves away. Aliens attacking you come first, then the nearest.'),
    pilFields(
      field(T('Closest (%)'), pilNum('kite_min', 30, 98, 1, 100)), field(T('Farthest (%)'), pilNum('kite_max', 35, 99, 1, 100)),
      field(T('Safety margin'), pilNum('threat_margin', 0, 2000, 10)),
      field(T('Laser ammo'), pilSelect('laser_ammo', [['', T('Keep the selected ammo')], ...PIL.data.ammo.map(a => [a, itemName(a)])]))),
    h('div', { class: 'pil-col' },
      pilCheck('avoid_aggressive', T('Avoid aggressive aliens'),
        T('While fighting or patrolling, keep away from the aggressive aliens that are not attacking yet.')),
      pilCheck('clear_path', T('Clear the path between maps'),
        T('On the way to another map (or the gate, the base, a quest giver), destroy the aggressive aliens attacking the ship or about to. Off: the ship keeps going.')),
      pilCheck('defend', T('Defend the work map'),
        T('On the map the mode works on (hunting, mining, the quest), fight back against the aliens attacking the ship. Off: it ignores them and goes on.'))),
    h('p', { class: 'desc', style: { marginTop: '12px' } }, T('Fire RCB-140 / RSB-75 each time their 3 s cooldown ends (RCB-140 first), then go back to the normal ammo.')),
    h('div', { class: 'row wrap', style: { gap: '14px' } }, slowCheck('ammunition_laser_rcb-140', 'RCB-140'), slowCheck('ammunition_laser_rsb-75', 'RSB-75')));
} });

// ------------------------------------------------------------ Support
PILC.push({ id: 'support', tab: 'support', order: 10, build: () => pilCard('zap', T('Abilities and technologies'),
  T('Each rule fires an ability or a technology when its condition holds, as soon as its cooldown allows.'),
  pilRuleList('support.rules', () => { const it = [...(PIL.cat.abilities || []), ...(PIL.cat.techs || [])][0]; return it ? { item: it, when: 'fight', value: 50 } : null; },
    (r, set) => {
      const items = [...(PIL.cat.abilities || []), ...(PIL.cat.techs || [])];
      return [h('select', { class: 'input', onchange: e => set({ item: e.target.value }) },
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
      h('select', { class: 'input', onchange: e => set({ loot: e.target.value }) },
        [...new Set([r.loot, ...(PIL.cat.buy_ammo || [])])].map(a => h('option', { value: a, selected: a === r.loot }, itemName(a)))),
      h('span', { class: 'muted small' }, T('below')),
      h('input', { class: 'input num', type: 'number', min: 0, step: 100, value: r.below, onchange: e => { if (e.target.value !== '') set({ below: +e.target.value }); } }),
      h('span', { class: 'muted small' }, T('buy')),
      h('input', { class: 'input num', type: 'number', min: 1, step: 100, value: r.amount, onchange: e => { if (e.target.value !== '') set({ amount: +e.target.value }); } })]),
  pilFields(field(T('Credits budget'), pilNum('supply.max_credits', 0, 1e11, 10000)), field(T('Uridium budget'), pilNum('supply.max_uridium', 0, 1e9, 100)))) });

// ------------------------------------------------------------ Safety
PILC.push({ id: 'safety', tab: 'safety', order: 10, build: () => pilCard('alert', T('Safety'),
  T('Below this HP the ship stops fighting, flies to the nearest safe zone (station or portal) and repairs with the repair robot, then resumes.'),
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
  if (r) { PIL.seq++; PIL.data = r; RENDER.pilot(); }
}

PILC.push({ id: 'profiles', tab: 'settings', order: 10, build: () => {
  const c = PIL.data.config, names = Object.keys(c.profiles || {}).sort((a, b) => a.localeCompare(b));
  const cur = c.profile || '';
  const pick = h('select', { class: 'input', onchange: e => e.target.value && pilProfile('load', e.target.value) },
    h('option', { value: '', selected: !cur }, names.length ? T('Load a profile…') : T('No profile yet')),
    names.map(n => h('option', { value: n, selected: n === cur }, n)));
  return pilCard('save', T('Profiles'), T('Save these settings under a name and switch between them in one click (for example "Farm X-1" or "Gate").'),
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
