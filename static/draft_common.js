/* draft_common.js
   The code the three draft boards share. It expects, in this order:
     1. the inline  window.DRAFT = {...}  block in the template (this draft's server values)
     2. draft_bb.js / draft_bk.js / draft_fb.js, which define window.SPORT and that sport's filterPos()
   The functions the HTML calls from onclick / onchange are plain globals on purpose. */

const socket           = io();
const currentDraftname = DRAFT.draftname;
const currentSport     = DRAFT.sport;

let selectedPlayerId = null;
let sortDir          = {};
let pickTimer        = null;
let timeLeft         = 0;
let draftRunning     = false;
let draftComplete    = false;
let hasPicks         = DRAFT.hasPicks;
let currentPick      = DRAFT.currentPick;

const SALARY_CAP  = parseFloat(DRAFT.cap) || 0;      // 0 = no cap
const salaryById  = {};                               // player id -> salary
const spentByTeam = {};                               // team name -> salary drafted so far

const DRAFT_TEAMS = DRAFT.teams;                      // teams in draft order
const TOTAL_PICKS = DRAFT_TEAMS.length * DRAFT.rosterSize;
const STRIP_SIZE  = 8;
const logoEls     = new Map();                        // logo strip elements: "p12" = a pick, "d3" = a round divider


// ── talking to the server ──
function draftPlayer() {
    if (!selectedPlayerId) return;
    socket.emit('make_pick', { draftname: currentDraftname, player_id: selectedPlayerId, sport: currentSport });
}

function toggleDraft() {
    socket.emit(draftRunning ? 'pause_draft' : 'start_draft', { draftname: currentDraftname, sport: currentSport });
}

function skipPick() {
    socket.emit('skip_pick', { draftname: currentDraftname, sport: currentSport });
}


// ── draft log and roster panel ──
function logLine(e) {
    return e.is_bonus
        ? `↳ ${e.team} — ${e.pos} ${e.player} (two-way)`
        : `${e.pick}. ${e.team} — ${e.pos} ${e.player}`;
}

function scrollLogToBottom() {
    const pane = document.querySelector('.pane-left');
    if (pane) pane.scrollTop = pane.scrollHeight;
}

function openSlot(root, label) {
    return root.querySelector(`.t-pick[data-slot="${label}"]:not(.filled)`);
}

function mapPosToSlot(pos) {
    return SPORT.posToSlot[pos] || (SPORT.defaultSlot === 'self' ? pos : SPORT.defaultSlot);
}

// a two-way pick gives that team one extra FLEX slot in the roster panel
function ensureFlexSlot(teamName) {
    const root = document.getElementById(`roster-${teamName}`);
    if (!root) return;
    const slot = document.createElement('div');
    slot.className = 't-pick';
    slot.dataset.slot = 'FLEX';
    slot.textContent = 'FLEX: —';
    root.appendChild(slot);
}

// fills a roster slot; the name links to the player's reference page (new window) when his pool row has one
function fillSlot(slot, e, label, row) {
    slot.textContent = '';
    slot.append(`${e.pos}: `);
    const url = row && row.dataset.url;
    if (url) {
        const a = document.createElement('a');
        a.href = url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.className = 'pl-link';
        a.textContent = label;
        slot.append(a);
    } else {
        slot.append(label);
    }
    slot.classList.add('filled');
}

// marks the row drafted, adds the log line, and fills the roster slot for ONE player
function applyPickToUI(e) {
    const row = document.querySelector(`tr[data-id="${e.id}"]`);
    if (row) row.classList.add('drafted');

    const logDiv = document.getElementById('draftLog');
    if (logDiv) {
        const noPicksMsg = logDiv.querySelector('.log-empty');
        if (noPicksMsg) noPicksMsg.remove();
        const el = document.createElement('div');
        el.className = 'log-entry';
        el.textContent = logLine(e);
        logDiv.appendChild(el);
        scrollLogToBottom();
    }

    const root = document.getElementById(`roster-${e.team}`);
    if (root) {
        const slot = SPORT.findSlot(root, mapPosToSlot(e.pos)) || root.querySelector('.t-pick:not(.filled)');
        if (slot) fillSlot(slot, e, SPORT.labelFor(e), row);
    }
}

function showRoster(teamName) {
    document.querySelectorAll('.roster-team').forEach(el => el.style.display = 'none');
    const el = document.getElementById(`roster-${teamName}`);
    if (el) el.style.display = 'block';
    updateSalaryLine(teamName);
}


// ── salary left (only when the draft has a cap) ──
function parseSalaryText(v) {
    return parseFloat(String(v || '').replace(/[$,\s]/g, '')) || 0;
}

function formatMoney(n) {
    return (n < 0 ? '-$' : '$') + Math.abs(Math.round(n)).toLocaleString('en-US');
}

function buildSalaryMap() {
    document.querySelectorAll('#playerBody tr').forEach(row => {
        salaryById[row.dataset.id] = parseSalaryText(row.dataset.sal);
    });
}

function addSpend(e) {
    spentByTeam[e.team] = (spentByTeam[e.team] || 0) + (salaryById[String(e.id)] || 0);
}

function rebuildSpend(log) {
    Object.keys(spentByTeam).forEach(k => delete spentByTeam[k]);
    log.forEach(addSpend);
}

function updateSalaryLine(teamName) {
    const el = document.getElementById('salaryLeft');
    if (!el) return;
    if (!SALARY_CAP) {
        el.style.display = 'none';
        return;
    }
    const select = document.getElementById('rosterSelect');
    const team = teamName || (select ? select.value : '');
    const left = SALARY_CAP - (spentByTeam[team] || 0);
    el.textContent = `Salary left: ${formatMoney(left)}`;
    el.classList.toggle('over', left < 0);
    el.style.display = 'block';
}


// ── the logo strip: whose turn it is, and the next picks in snake order ──
function teamForPick(pick) {
    const n = DRAFT_TEAMS.length;
    const round = Math.floor((pick - 1) / n);
    const i = (pick - 1) % n;
    return DRAFT_TEAMS[round % 2 === 0 ? i : n - 1 - i];
}

function buildLogoEl(team) {
    const wrap = document.createElement('div');
    wrap.className = 'logo-wrap ' + (team.is_human ? 'human' : 'ai');
    wrap.dataset.team = team.name;

    const img = document.createElement('img');
    img.src = `https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/Logos/fictional/${SPORT.logoDir}/${encodeURIComponent(team.name)}_${SPORT.logoCode}.png`;
    img.alt = team.name;
    img.onerror = () => { img.style.opacity = '0.2'; };

    const label = document.createElement('div');
    label.className = 'team-label';
    label.textContent = team.name;

    wrap.appendChild(img);
    wrap.appendChild(label);
    return wrap;
}

function renderLogoStrip() {
    const strip = document.getElementById('logoStrip');
    if (!strip) return;

    const n        = DRAFT_TEAMS.length;
    const DURATION = 500;                          // ms: raise for slower, lower for snappier
    const EASE     = 'cubic-bezier(.22, .8, .3, 1)';
    const stripBox = strip.getBoundingClientRect();

    // FIRST: record where everything is now, and cancel any animation still running
    const first = new Map();
    logoEls.forEach((el, key) => {
        first.set(key, el.getBoundingClientRect());
        el.getAnimations().forEach(a => a.cancel());
    });
    const isFirstRender = logoEls.size === 0;

    // work out what should be showing: [key, element] in order
    const desired = [];
    let prevRound = null;
    for (let k = 0; k < STRIP_SIZE; k++) {
        const pick = currentPick + k;
        if (pick > TOTAL_PICKS) break;

        const round = Math.floor((pick - 1) / n);
        if (prevRound !== null && round !== prevRound) {
            const dkey = `d${round}`;
            let div = logoEls.get(dkey);
            if (!div) {
                div = document.createElement('div');
                div.className = 'round-divider';
                div.title = `Round ${round + 1}`;
            }
            desired.push([dkey, div]);
        }
        prevRound = round;

        const key = `p${pick}`;
        let el = logoEls.get(key);
        if (!el) el = buildLogoEl(teamForPick(pick));
        el.classList.toggle('active', k === 0);
        desired.push([key, el]);
    }
    const desiredKeys = new Set(desired.map(d => d[0]));

    // elements no longer showing: slide them out as "ghosts", then remove
    logoEls.forEach((el, key) => {
        if (desiredKeys.has(key)) return;
        const box = first.get(key);
        if (!isFirstRender && box) {
            el.style.position      = 'absolute';
            el.style.left          = (box.left - stripBox.left) + 'px';
            el.style.top           = (box.top  - stripBox.top)  + 'px';
            el.style.width         = box.width  + 'px';
            el.style.height        = box.height + 'px';
            el.style.pointerEvents = 'none';
            const ghost = el;
            ghost.animate(
                [{ transform: 'translateX(0)', opacity: 1 },
                 { transform: `translateX(-${box.width + 8}px)`, opacity: 0 }],
                { duration: DURATION, easing: EASE, fill: 'forwards' }
            ).onfinish = () => ghost.remove();
        } else {
            el.remove();
        }
        logoEls.delete(key);
    });

    // put the wanted elements in order (appendChild moves existing nodes)
    desired.forEach(([key, el]) => {
        strip.appendChild(el);
        logoEls.set(key, el);
    });

    // "Draft complete" placeholder when nothing is left to show
    let empty = strip.querySelector('.strip-empty');
    if (!desired.length) {
        if (!empty) {
            empty = document.createElement('div');
            empty.className = 'team-label strip-empty';
            empty.style.padding = '14px';
            empty.textContent = 'Draft complete';
            strip.appendChild(empty);
        }
    } else if (empty) {
        empty.remove();
    }

    // LAST + INVERT + PLAY: slide survivors from old spot to new, fade new ones in
    if (isFirstRender) return;
    desired.forEach(([key, el]) => {
        const before = first.get(key);
        if (before) {
            const dx = before.left - el.getBoundingClientRect().left;
            if (Math.abs(dx) > 1) {
                el.animate(
                    [{ transform: `translateX(${dx}px)` }, { transform: 'translateX(0)' }],
                    { duration: DURATION, easing: EASE }
                );
            }
        } else {
            el.animate(
                [{ opacity: 0, transform: 'translateX(40px)' }, { opacity: 1, transform: 'translateX(0)' }],
                { duration: DURATION, easing: EASE }
            );
        }
    });
}

function setActiveLogo() {          // older calls still pass a team name; the strip works from currentPick now
    renderLogoStrip();
}


// ── the pick clock and the Start / Stop button ──
function startTimer(seconds) {
    clearInterval(pickTimer);
    timeLeft = seconds;
    updateTimerDisplay();
    if (draftRunning) runClock();       // paused drafts just show the time, no ticking
}

function runClock() {
    clearInterval(pickTimer);
    pickTimer = setInterval(() => {
        timeLeft--;
        updateTimerDisplay();
        if (timeLeft <= 0) {
            clearInterval(pickTimer);
            skipPick();
        }
    }, 1000);
}

function updateTimerDisplay() {
    const el = document.getElementById('tickerTimer');
    if (!el) return;
    const mins = Math.floor(timeLeft / 60);
    const secs = timeLeft % 60;
    el.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
    el.classList.toggle('warning', timeLeft <= 30);
}

function updateToggleBtn() {
    const btn = document.getElementById('draftToggleBtn');
    if (!btn) return;
    if (draftComplete) {
        btn.style.display = 'none';
        return;
    }
    btn.textContent = draftRunning ? 'Stop Draft' : (hasPicks ? 'Resume Draft' : 'Start Draft');
    btn.classList.toggle('running', draftRunning);
}

function showDraftComplete() {
    draftComplete = true;
    draftRunning  = false;
    updateToggleBtn();
    clearInterval(pickTimer);
    const announcement = document.getElementById('tickerAnnouncement');
    if (announcement) announcement.textContent = 'Draft complete! 🎉 Use "Export Excel" at the top to download the rosters.';
    const timer = document.getElementById('tickerTimer');
    if (timer) timer.textContent = '--';
    document.getElementById('draftBtn').style.display = 'none';
    document.getElementById('clockTeam').textContent = 'Draft complete';
}


// ── the player pool table ──
const NAME_SUFFIXES = new Set(['jr', 'sr', 'ii', 'iii', 'iv', 'v']);

// "Ken Griffey Jr." sorts under G: ignore Jr / Sr / II / III / IV at the end of a name
function lastNameKey(name) {
    const words = name.trim().split(/\s+/);
    while (words.length > 1 && NAME_SUFFIXES.has(words[words.length - 1].toLowerCase().replace(/[.,]/g, ''))) {
        words.pop();
    }
    return words[words.length - 1] || '';
}

function sortTable(col) {
    const tbody = document.getElementById('playerBody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    sortDir[col] = !sortDir[col];
    // sort by the cells that are actually showing (real-stat and strat-stat cells swap places)
    const cell = row => Array.from(row.cells).filter(c => c.style.display !== 'none')[col];
    rows.sort((a, b) => {
        let aVal = cell(a).innerText.trim();
        let bVal = cell(b).innerText.trim();
        if (col === 1) {
            const c = lastNameKey(aVal).localeCompare(lastNameKey(bVal)) || aVal.localeCompare(bVal);
            return sortDir[col] ? c : -c;
        }
        if (col >= 3) {
            const x = parseFloat(aVal), y = parseFloat(bVal);
            if (isNaN(x) && isNaN(y)) {                       // text columns (like Bats / Throws)
                return sortDir[col] ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
            }
            return sortDir[col] ? (x || 0) - (y || 0) : (y || 0) - (x || 0);
        }
        return sortDir[col] ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    });
    rows.forEach(r => tbody.appendChild(r));
    document.querySelectorAll('.sort-icon').forEach((el, i) => {
        el.textContent = i === col ? (sortDir[col] ? '↑' : '↓') : '↕';
    });
}

function switchStatView(view) {
    const showReal = view === 'real';
    document.querySelectorAll('.stat-real').forEach(el => { el.style.display = showReal ? '' : 'none'; });
    document.querySelectorAll('.stat-strat').forEach(el => { el.style.display = showReal ? 'none' : ''; });
}


// ── messages from the server ──
socket.on('connect', () => {
    socket.emit('request_sync', { draftname: currentDraftname, sport: currentSport });
});

socket.on('pick_made', (entry) => {
    // the server says what the real next pick number is
    currentPick = entry.next_pick || (entry.pick + 1);
    hasPicks = true;
    updateToggleBtn();

    // salary tracking, including a two-way twin
    addSpend(entry);
    if (entry.bonus) addSpend(entry.bonus);

    // the pick, plus the twin and its extra FLEX slot if there is one
    if (entry.bonus && SPORT.flexOnBonus) ensureFlexSlot(entry.team);
    applyPickToUI(entry);
    if (entry.bonus) applyPickToUI(entry.bonus);

    // clear the selection
    selectedPlayerId = null;
    document.getElementById('draftBtn').style.display = 'none';
    document.getElementById('selectedName').textContent = 'Click a player to select';
    document.getElementById('selectedStats').textContent = '';

    // roster dropdown, on-the-clock team, logo strip
    const select = document.getElementById('rosterSelect');
    if (select && entry.next_team) {
        select.value = entry.next_team;
        showRoster(entry.next_team);
    }
    const clockEl = document.getElementById('clockTeam');
    if (clockEl) clockEl.textContent = entry.next_team;
    renderLogoStrip();

    // ticker announcement
    const announcement = document.getElementById('tickerAnnouncement');
    if (announcement) {
        announcement.textContent = entry.bonus
            ? `${entry.team} select ${entry.pos} — ${entry.player} (plus ${entry.bonus.pos} ${entry.bonus.player})`
            : `${entry.team} select ${entry.pos} — ${entry.player}`;
    }

    // reset the clock for the next team (it only ticks if the draft is running)
    startTimer(entry.next_team_type === 'human' ? 120 : 15);
});

socket.on('pick_error', (data) => {
    alert(data.message);
});

socket.on('cap_warning', (data) => {
    if (confirm(data.message + '\n\nDraft this player anyway?')) {
        socket.emit('make_pick', {
            draftname: currentDraftname,
            player_id: data.player_id,
            sport:     currentSport,
            confirmed: true
        });
    }
});

socket.on('full_sync', (data) => {
    rebuildSpend(data.log);
    currentPick  = data.current_pick;
    draftRunning = !!data.running;
    hasPicks     = data.log.length > 0;
    updateToggleBtn();

    const logDiv = document.getElementById('draftLog');
    if (logDiv) {
        logDiv.innerHTML = '';
        if (data.log.length === 0) {
            const el = document.createElement('div');
            el.className = 'log-empty';
            el.textContent = 'No picks yet';
            logDiv.appendChild(el);
        } else {
            data.log.forEach(entry => {
                const el = document.createElement('div');
                el.className = 'log-entry';
                el.textContent = logLine(entry);
                logDiv.appendChild(el);
            });
        }
        scrollLogToBottom();
    }

    data.log.forEach(entry => {
        const row = document.querySelector(`tr[data-id="${entry.id}"]`);
        if (row) row.classList.add('drafted');
    });

    const clockEl = document.getElementById('clockTeam');
    if (clockEl) clockEl.textContent = data.current_team;
    renderLogoStrip();

    const select = document.getElementById('rosterSelect');
    if (select) {
        select.value = data.current_team;
        showRoster(data.current_team);
    }

    if (data.complete) {
        showDraftComplete();
    } else {
        startTimer(data.current_team_type === 'human' ? 120 : 15);
    }
});

socket.on('draft_state', (data) => {
    if (data.draftname !== currentDraftname) return;     // ignore other drafts
    draftRunning = data.running;
    if (draftRunning) {
        runClock();                                       // resumes from wherever the clock was frozen
    } else {
        clearInterval(pickTimer);
    }
    updateToggleBtn();
});

socket.on('draft_complete', showDraftComplete);


// ── page load ──
document.addEventListener('DOMContentLoaded', () => {
    renderLogoStrip();
    buildSalaryMap();
    rebuildSpend(DRAFT.initialLog);
    updateSalaryLine();
    scrollLogToBottom();
    if (SPORT.onReady) SPORT.onReady();

    // show the roster of the team on the clock (the server syncs again right after connecting)
    if (document.getElementById(`roster-${DRAFT.currentTeam}`)) {
        showRoster(DRAFT.currentTeam);
    } else {
        const first = document.querySelector('.roster-team');
        if (first) first.style.display = 'block';
    }

    // click a player row to select him
    document.querySelectorAll('#playerBody tr').forEach(row => {
        row.addEventListener('click', () => {
            selectedPlayerId = row.dataset.id;
            const cells = row.cells;
            document.getElementById('selectedName').textContent  = `${cells[0].innerText} — ${cells[1].innerText}`;
            document.getElementById('selectedStats').textContent =
                `${cells[2].innerText} | ${cells[3].innerText} / ${cells[4].innerText} / ${cells[5].innerText}`;
            document.getElementById('draftBtn').style.display = 'inline-block';
            document.querySelectorAll('#playerBody tr').forEach(r => r.classList.remove('selected-row'));
            row.classList.add('selected-row');
        });
    });

    // the first pick's clock only ticks once the draft is started
    startTimer(DRAFT.currentTeamType === 'human' ? 120 : 15);
});