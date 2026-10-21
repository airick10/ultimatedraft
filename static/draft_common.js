/* ===========================================================================================
   draft_common.js  --  the live draft board's brain (shared by baseball, basketball, football).

   WHAT THIS FILE DOES
     Runs in the browser on the draft board page (bbdraft.html / bkdraft.html / fbdraft.html). It:
       - keeps a live Socket.IO connection to the server (routes.py's handlers),
       - sends your actions to the server (Draft button, Start/Stop button, the pick clock hitting 0),
       - receives the server's messages and updates the screen (draft log, rosters, salary left,
         the animated logo strip, the clock, the player pool),
       - runs the player pool table (sorting, switching Real / Strat / All columns, clicking a row to select).

   THE LOAD ORDER (set in the draft templates' "scripts" block; the order matters)
     1. base.html loads the Socket.IO library (gives us the global function io()).
     2. an inline script defines  window.DRAFT = {...}  with this draft's values (see below).
     3. draft_bb.js / draft_bk.js / draft_fb.js  define  window.SPORT  and that sport's filterPos().
     4. THIS file.
     5. poolsearch.js  (the name search box).
     This file fails right away if io, DRAFT or SPORT is missing, so keep that order.

   WHAT THE INLINE window.DRAFT OBJECT HOLDS (filled in by the template from the server)
     draftname        the draft's name (string)
     sport            "bb" / "bk" / "fb"
     currentTeam      name of the team on the clock when the page loaded
     currentTeamType  "human" or "ai"
     currentPick      the next pick number
     hasPicks         true once at least one pick has been made
     teams            list of {team_id, name, is_human}, in round-1 draft order
     rosterSize       roster slots per team (25 / 12 / 13)
     cap              the salary cap as text ("" or 0 = no cap)
     initialLog       the pick log when the page loaded
     labels           {player id: "Name (R)"} roster labels (baseball only)

   THE HTML IDs THIS FILE EXPECTS ON THE PAGE
     logoStrip, tickerAnnouncement, tickerTimer, draftToggleBtn, draftLog, rosterSelect, clockTeam,
     salaryLeft, selectedName, selectedStats, draftBtn, playerBody, tableHead, statView,
     one  roster-<Team Name>  block per team, and one  tr[data-id]  row per player in the pool.

   THE SERVER MESSAGES (routes.py, section 7) AND WHERE THEY ARE HANDLED BELOW
     pick_made, pick_error, cap_warning, full_sync, draft_state, draft_complete.

   The functions that the HTML calls from onclick / onchange attributes are plain globals ON PURPOSE.
   =========================================================================================== */

// ── the connection and the page-wide state ──

// The live connection to the server. io() comes from the Socket.IO library loaded in base.html.
const socket           = io();
const currentDraftname = DRAFT.draftname;      // this draft's name
const currentSport     = DRAFT.sport;          // "bb", "bk" or "fb"

// ---- state that changes while the draft runs ----
let selectedPlayerId = null;     // the id of the pool row the user clicked (null = nothing selected)
let sortDir          = {};       // {column number: true if currently sorted ascending}
let pickTimer        = null;     // the setInterval handle of the pick clock
let timeLeft         = 0;        // seconds left on the pick clock
let draftRunning     = false;    // true between Start/Resume and Stop (the server is the real authority)
let draftComplete    = false;    // true once the last pick is in
let hasPicks         = DRAFT.hasPicks;        // lets the button say "Start Draft" vs "Resume Draft"
let currentPick      = DRAFT.currentPick;     // the next pick number to be made

// which position tab and stat view the player pool is showing
let currentPos  = 'ALL';         // "ALL", "C", "SS", "QB"... (set by each sport's filterPos)
let currentStat = 'real';        // "real" or "strat" (the dropdown above the pool)

// ---- salary tracking (only used when the draft has a cap) ----
const SALARY_CAP  = parseFloat(DRAFT.cap) || 0;      // 0 = no cap
const salaryById  = {};                               // player id -> salary
const spentByTeam = {};                               // team name -> salary drafted so far

// ---- the logo strip ----
const DRAFT_TEAMS = DRAFT.teams;                      // teams in draft order
const TOTAL_PICKS = DRAFT_TEAMS.length * DRAFT.rosterSize;     // how many picks the whole draft has
const STRIP_SIZE  = 8;                                // how many upcoming picks the strip shows
const logoEls     = new Map();                        // logo strip elements: "p12" = a pick, "d3" = a round divider


// ── talking to the server ──

/**
 * PURPOSE:   The Draft button. Sends the selected player to the server as a "make_pick" message.
 *            Does nothing if no player is selected. (The server may answer with a pick_error, a
 *            cap_warning, or a pick_made.)
 * ARGUMENTS: none
 * CALLED BY: the Draft button, onclick="draftPlayer()" (id draftBtn) in bbdraft.html, bkdraft.html
 *            and fbdraft.html.
 * RETURNS:   nothing.
 */
function draftPlayer() {
    if (!selectedPlayerId) return;
    socket.emit('make_pick', { draftname: currentDraftname, player_id: selectedPlayerId, sport: currentSport });
}

/**
 * PURPOSE:   The Start / Resume / Stop button. Asks the server to start the draft if it is paused, or
 *            pause it if it is running. The button label and the clock change when the server answers
 *            with a "draft_state" message.
 * ARGUMENTS: none
 * CALLED BY: onclick="toggleDraft()" on the button with id draftToggleBtn in the three draft templates.
 * RETURNS:   nothing.
 */
function toggleDraft() {
    socket.emit(draftRunning ? 'pause_draft' : 'start_draft', { draftname: currentDraftname, sport: currentSport });
}

/**
 * PURPOSE:   Tell the server the pick clock hit zero, so it makes an automatic (AI) pick for whoever is
 *            on the clock. Note: EVERY open browser runs its own clock and sends this, so two tabs can
 *            cause a double auto-pick.
 * ARGUMENTS: none
 * CALLED BY: draft_common.js: runClock (when timeLeft reaches 0).
 * RETURNS:   nothing.
 */
function skipPick() {
    socket.emit('skip_pick', { draftname: currentDraftname, sport: currentSport });
}


// ── draft log and roster panel ──

/**
 * PURPOSE:   Turn one pick-log entry into the line of text shown in the Draft Log panel and used by the
 *            ticker. A normal pick reads "12. Neptunes — SS Cal Ripken"; a two-way twin reads
 *            "↳ Neptunes — SP Shohei Ohtani (two-way)".
 * ARGUMENTS: e (object) -- a log entry: {pick, team, pos, player, is_bonus?}.
 * CALLED BY: draft_common.js: applyPickToUI and the full_sync handler.
 * RETURNS:   string -- the line of text.
 */
function logLine(e) {
    return e.is_bonus
        ? `↳ ${e.team} — ${e.pos} ${e.player} (two-way)`
        : `${e.pick}. ${e.team} — ${e.pos} ${e.player}`;
}

/**
 * PURPOSE:   Scroll the left panel (the Draft Log) down to the newest pick.
 * ARGUMENTS: none
 * CALLED BY: draft_common.js: applyPickToUI, the full_sync handler and the page-load handler.
 * RETURNS:   nothing.
 */
function scrollLogToBottom() {
    const pane = document.querySelector('.pane-left');
    if (pane) pane.scrollTop = pane.scrollHeight;
}

/**
 * PURPOSE:   Find the first still-empty roster slot with a given label inside a team's roster block.
 *            (A filled slot has the CSS class "filled".)
 * ARGUMENTS: root  (Element) -- a team's roster block (id "roster-<Team Name>").
 *            label (string)  -- the slot label to look for, like "C", "UT" or "FLEX".
 * CALLED BY: the findSlot functions in draft_bb.js, draft_bk.js and draft_fb.js.
 * RETURNS:   Element | null -- the empty slot's element, or null if there isn't one.
 */
function openSlot(root, label) {
    return root.querySelector(`.t-pick[data-slot="${label}"]:not(.filled)`);
}

/**
 * PURPOSE:   Work out which roster slot label a drafted position belongs to ("SP" -> "S", "DO" -> "Def"),
 *            using the table in window.SPORT. A position that isn't in the table goes to the sport's
 *            defaultSlot ("UT" for baseball and basketball); football uses "self" (keep its own label).
 * ARGUMENTS: pos (string) -- the position code from a pick, like "SS", "SP" or "DO".
 * CALLED BY: draft_common.js: applyPickToUI.
 * RETURNS:   string -- the slot label.
 */
function mapPosToSlot(pos) {
    return SPORT.posToSlot[pos] || (SPORT.defaultSlot === 'self' ? pos : SPORT.defaultSlot);
}

/**
 * PURPOSE:   A two-way pick gives that team one extra FLEX slot. Add an empty "FLEX: —" row to the end of
 *            the team's roster block in the panel.
 * ARGUMENTS: teamName (string) -- the drafting team's name.
 * CALLED BY: draft_common.js: the pick_made handler (only for sports with flexOnBonus, i.e. baseball and
 *            football).
 * RETURNS:   nothing.
 */
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

/**
 * PURPOSE:   Put a drafted player into a roster slot: "SS: Cal Ripken (R)". If his pool row has a
 *            reference-page link (its data-url), the name becomes a link that opens in a new window.
 * ARGUMENTS: slot  (Element) -- the empty slot element to fill.
 *            e     (object)  -- the pick entry (uses e.pos).
 *            label (string)  -- the text to show for the player (from SPORT.labelFor).
 *            row   (Element | null) -- the player's row in the pool table (read for data-url).
 * CALLED BY: draft_common.js: applyPickToUI.
 * RETURNS:   nothing.
 */
// fills a roster slot; the name links to the player's reference page (new window) when his pool row has one
function fillSlot(slot, e, label, row) {
    slot.textContent = '';                    // clear the "SS: —" placeholder
    slot.append(`${e.pos}: `);
    const url = row && row.dataset.url;
    if (url) {
        const a = document.createElement('a');
        a.href = url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';        // security: the new window can't control this one
        a.className = 'pl-link';
        a.textContent = label;
        slot.append(a);
    } else {
        slot.append(label);
    }
    slot.classList.add('filled');
}

/**
 * PURPOSE:   Show ONE pick on screen: grey out the player's row in the pool, add a line to the Draft Log,
 *            and fill a slot in the drafting team's roster block (his natural slot, then the sport's
 *            overflow rules, then any empty slot at all).
 * ARGUMENTS: e (object) -- a pick entry: {id, team, pos, player, ...}. A two-way twin is passed as its own
 *                          entry.
 * CALLED BY: draft_common.js: the pick_made handler (once for the pick, once more for a twin).
 * RETURNS:   nothing.
 */
// marks the row drafted, adds the log line, and fills the roster slot for ONE player
function applyPickToUI(e) {
    // 1) grey out the player in the pool (the .drafted CSS class lowers his opacity and blocks clicks)
    const row = document.querySelector(`tr[data-id="${e.id}"]`);
    if (row) row.classList.add('drafted');

    // 2) add the line to the Draft Log
    const logDiv = document.getElementById('draftLog');
    if (logDiv) {
        const noPicksMsg = logDiv.querySelector('.log-empty');
        if (noPicksMsg) noPicksMsg.remove();            // remove the "No picks yet" placeholder
        const el = document.createElement('div');
        el.className = 'log-entry';
        el.textContent = logLine(e);
        logDiv.appendChild(el);
        scrollLogToBottom();
    }

    // 3) fill his slot in the team's roster block
    const root = document.getElementById(`roster-${e.team}`);
    if (root) {
        const slot = SPORT.findSlot(root, mapPosToSlot(e.pos)) || root.querySelector('.t-pick:not(.filled)');
        if (slot) fillSlot(slot, e, SPORT.labelFor(e), row);
    }
}

/**
 * PURPOSE:   Show one team's roster in the right-hand panel (and hide the others), and update the
 *            "Salary left" line for that team.
 * ARGUMENTS: teamName (string) -- the team to show.
 * CALLED BY: the roster dropdown, onchange="showRoster(this.value)" (id rosterSelect) in the three draft
 *            templates; draft_common.js: the pick_made handler, the full_sync handler and the page-load
 *            handler.
 * RETURNS:   nothing.
 */
function showRoster(teamName) {
    document.querySelectorAll('.roster-team').forEach(el => el.style.display = 'none');
    const el = document.getElementById(`roster-${teamName}`);
    if (el) el.style.display = 'block';
    updateSalaryLine(teamName);
}


// ── salary left (only when the draft has a cap) ──

/**
 * PURPOSE:   Turn salary text like "$11,150,000" into a number.
 * ARGUMENTS: v (string | number | undefined) -- the salary as written on the page.
 * CALLED BY: draft_common.js: buildSalaryMap.
 * RETURNS:   number -- the salary in dollars, 0 if missing or unreadable.
 */
function parseSalaryText(v) {
    return parseFloat(String(v || '').replace(/[$,\s]/g, '')) || 0;
}

/**
 * PURPOSE:   Format a number of dollars for display: 1250000 -> "$1,250,000"; negatives get a leading
 *            minus: "-$50,000".
 * ARGUMENTS: n (number) -- dollars.
 * CALLED BY: draft_common.js: updateSalaryLine.
 * RETURNS:   string -- the formatted amount.
 */
function formatMoney(n) {
    return (n < 0 ? '-$' : '$') + Math.abs(Math.round(n)).toLocaleString('en-US');
}

/**
 * PURPOSE:   Build the id -> salary lookup by reading every pool row's data-sal attribute. (The attribute is
 *            present on every row, even when the Salary column is hidden because there's no cap.)
 * ARGUMENTS: none
 * CALLED BY: draft_common.js: the page-load handler.
 * RETURNS:   nothing. Fills the global salaryById.
 */
function buildSalaryMap() {
    document.querySelectorAll('#playerBody tr').forEach(row => {
        salaryById[row.dataset.id] = parseSalaryText(row.dataset.sal);
    });
}

/**
 * PURPOSE:   Add one pick's salary to its team's running total.
 * ARGUMENTS: e (object) -- a pick entry: {team, id}.
 * CALLED BY: draft_common.js: the pick_made handler (for the pick and for a twin) and rebuildSpend (once
 *            per log entry).
 * RETURNS:   nothing. Updates the global spentByTeam.
 */
function addSpend(e) {
    spentByTeam[e.team] = (spentByTeam[e.team] || 0) + (salaryById[String(e.id)] || 0);
}

/**
 * PURPOSE:   Recalculate every team's total spend from scratch using the whole pick log.
 * ARGUMENTS: log (array) -- the pick-log entries.
 * CALLED BY: draft_common.js: the full_sync handler and the page-load handler.
 * RETURNS:   nothing. Rebuilds the global spentByTeam.
 */
function rebuildSpend(log) {
    Object.keys(spentByTeam).forEach(k => delete spentByTeam[k]);      // empty it first
    log.forEach(addSpend);
}

/**
 * PURPOSE:   Show "Salary left: $X" for a team in the right-hand panel (red if the team is over the cap).
 *            Hidden entirely when the draft has no cap.
 * ARGUMENTS: teamName (string | undefined) -- the team; if omitted, the team picked in the roster dropdown.
 * CALLED BY: draft_common.js: showRoster and the page-load handler.
 * RETURNS:   nothing.
 */
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
    el.classList.toggle('over', left < 0);        // the .over CSS class turns it red
    el.style.display = 'block';
}


// ── the logo strip: whose turn it is, and the next picks in snake order ──

/**
 * PURPOSE:   Work out which team makes a given pick number, in SNAKE order: round 1 goes first team to last,
 *            round 2 goes last to first, round 3 forward again, and so on. (The same rule as
 *            get_next_team_id in services.py.)
 * ARGUMENTS: pick (number) -- the pick number, 1 = first.
 * CALLED BY: draft_common.js: renderLogoStrip.
 * RETURNS:   object -- that team's entry from DRAFT_TEAMS ({team_id, name, is_human}).
 */
function teamForPick(pick) {
    const n = DRAFT_TEAMS.length;
    const round = Math.floor((pick - 1) / n);        // 0 for round 1, 1 for round 2...
    const i = (pick - 1) % n;                         // position within the round
    return DRAFT_TEAMS[round % 2 === 0 ? i : n - 1 - i];
}

/**
 * PURPOSE:   Build the little HTML block for one team in the logo strip: its logo picture and its name.
 *            The logo address follows the pattern
 *            .../Logos/fictional/<baseball|basketball|football>/<Team>_<bb|bk|fb>.png
 *            (if you ever move the logos, this is one of four places to change; see the README).
 *            A picture that fails to load fades to 20% opacity.
 * ARGUMENTS: team (object) -- {name, is_human}.
 * CALLED BY: draft_common.js: renderLogoStrip.
 * RETURNS:   Element -- a div.logo-wrap (class "human" or "ai") ready to add to the strip.
 */
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

/**
 * PURPOSE:   Draw the logo strip at the top of the page: the team on the clock first, then the next picks in
 *            snake order (up to STRIP_SIZE picks), with a divider between rounds. When a pick happens, the
 *            logos GLIDE left into their new places, the first one slides out, and a new one fades in at
 *            the right.
 *
 *            HOW THE ANIMATION WORKS ("FLIP"):
 *              FIRST   record where every logo is right now;
 *              LAST    rearrange the page to the new layout (the logos jump to their new spots);
 *              INVERT  measure how far each one jumped;
 *              PLAY    animate each logo from its old spot back to its new one.
 *            Logos that disappear are turned into "ghosts" (absolutely positioned where they were) that slide
 *            away and are then removed. Each element is remembered in logoEls under a key: "p12" for pick
 *            12's logo, "d2" for the divider before round 3, so elements are reused, not rebuilt.
 *            The first call (page load) is drawn without animation.
 * ARGUMENTS: none (it reads the global currentPick)
 * CALLED BY: draft_common.js: the pick_made handler, the full_sync handler, the page-load handler and
 *            setActiveLogo.
 * RETURNS:   nothing.
 */
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
        if (pick > TOTAL_PICKS) break;              // don't show picks past the end of the draft

        const round = Math.floor((pick - 1) / n);
        if (prevRound !== null && round !== prevRound) {
            // a new round starts here: add a divider line (reuse the old one if it exists)
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
        el.classList.toggle('active', k === 0);      // the first logo is the team on the clock
        desired.push([key, el]);
    }
    const desiredKeys = new Set(desired.map(d => d[0]));

    // elements no longer showing: slide them out as "ghosts", then remove
    logoEls.forEach((el, key) => {
        if (desiredKeys.has(key)) return;
        const box = first.get(key);
        if (!isFirstRender && box) {
            // pin the element exactly where it was, then animate it off to the left and fade it out
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
    if (isFirstRender) return;                       // no animation on the very first draw
    desired.forEach(([key, el]) => {
        const before = first.get(key);
        if (before) {
            // it existed before: slide from where it WAS to where it is now
            const dx = before.left - el.getBoundingClientRect().left;
            if (Math.abs(dx) > 1) {
                el.animate(
                    [{ transform: `translateX(${dx}px)` }, { transform: 'translateX(0)' }],
                    { duration: DURATION, easing: EASE }
                );
            }
        } else {
            // a brand-new logo: fade it in from the right
            el.animate(
                [{ opacity: 0, transform: 'translateX(40px)' }, { opacity: 1, transform: 'translateX(0)' }],
                { duration: DURATION, easing: EASE }
            );
        }
    });
}

/**
 * PURPOSE:   A leftover wrapper from an older version, when the strip highlighted a team by name. The strip
 *            now works from currentPick, so this just redraws it.
 * ARGUMENTS: none used (older callers passed a team name).
 * CALLED BY: nothing in the current code (kept so older calls would still work). Safe to delete.
 * RETURNS:   nothing.
 */
function setActiveLogo() {          // older calls still pass a team name; the strip works from currentPick now
    renderLogoStrip();
}


// ── the pick clock and the Start / Stop button ──
// The clock lives in THIS browser. The server never ticks it, so if the draft is paused the clock is just
// frozen on screen. The lengths are set where startTimer() is called: 120 seconds for a human team, 15 for AI
// (search this file for "startTimer(" and change those two numbers).

/**
 * PURPOSE:   Reset the pick clock to a number of seconds and show it. It only starts TICKING if the draft is
 *            running; a paused draft just displays the time.
 * ARGUMENTS: seconds (number) -- the time to put on the clock (120 for a human, 15 for AI).
 * CALLED BY: draft_common.js: the pick_made handler, the full_sync handler and the page-load handler.
 * RETURNS:   nothing.
 */
function startTimer(seconds) {
    clearInterval(pickTimer);
    timeLeft = seconds;
    updateTimerDisplay();
    if (draftRunning) runClock();       // paused drafts just show the time, no ticking
}

/**
 * PURPOSE:   Start the clock ticking once a second. At zero it stops and calls skipPick() so the server
 *            makes an automatic pick.
 * ARGUMENTS: none (it counts down the global timeLeft)
 * CALLED BY: draft_common.js: startTimer (when the draft is running) and the draft_state handler (when the
 *            draft is started or resumed, continuing from the frozen time).
 * RETURNS:   nothing.
 */
function runClock() {
    clearInterval(pickTimer);                 // never run two timers at once
    pickTimer = setInterval(() => {
        timeLeft--;
        updateTimerDisplay();
        if (timeLeft <= 0) {
            clearInterval(pickTimer);
            skipPick();
        }
    }, 1000);
}

/**
 * PURPOSE:   Draw the clock as "m:ss" in the ticker, and turn it red (the "warning" CSS class) at 30 seconds
 *            or less.
 * ARGUMENTS: none (it reads the global timeLeft)
 * CALLED BY: draft_common.js: startTimer and runClock.
 * RETURNS:   nothing.
 */
function updateTimerDisplay() {
    const el = document.getElementById('tickerTimer');
    if (!el) return;
    const mins = Math.floor(timeLeft / 60);
    const secs = timeLeft % 60;
    el.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;      // 5 -> "0:05"
    el.classList.toggle('warning', timeLeft <= 30);
}

/**
 * PURPOSE:   Set the label and color of the Start button: "Start Draft" (nothing picked yet), "Resume Draft"
 *            (paused partway) or "Stop Draft" (running, shown in red via the "running" class). Hides the
 *            button once the draft is complete.
 * ARGUMENTS: none (it reads draftRunning, draftComplete and hasPicks)
 * CALLED BY: draft_common.js: the pick_made, full_sync and draft_state handlers, and showDraftComplete.
 * RETURNS:   nothing.
 */
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

/**
 * PURPOSE:   Put the page into its "finished" state: stop the clock, hide the Start and Draft buttons, show
 *            a "Draft complete!" message and tell the roster panel the draft is over.
 * ARGUMENTS: none
 * CALLED BY: draft_common.js: the full_sync handler (when data.complete), and registered directly as the
 *            handler for the server's "draft_complete" message.
 * RETURNS:   nothing.
 */
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

// Name endings ignored when sorting by last name (so "Ken Griffey Jr." sorts under G).
const NAME_SUFFIXES = new Set(['jr', 'sr', 'ii', 'iii', 'iv', 'v']);

/**
 * PURPOSE:   Get the part of a name to sort by: the last word, ignoring endings like Jr / Sr / II / III / IV
 *            ("Ken Griffey Jr." -> "Griffey").
 * ARGUMENTS: name (string) -- a full name as shown in the table.
 * CALLED BY: draft_common.js: sortTable (when sorting the Name column).
 * RETURNS:   string -- the last name ("" for an empty name).
 */
// "Ken Griffey Jr." sorts under G: ignore Jr / Sr / II / III / IV at the end of a name
function lastNameKey(name) {
    const words = name.trim().split(/\s+/);
    while (words.length > 1 && NAME_SUFFIXES.has(words[words.length - 1].toLowerCase().replace(/[.,]/g, ''))) {
        words.pop();
    }
    return words[words.length - 1] || '';
}

/**
 * PURPOSE:   Get only the cells of a row (or a header row) that are actually SHOWING. The pool table keeps
 *            the Real, Strat and All columns all in the HTML and hides the ones not in use, so positions
 *            must be counted among the visible cells only.
 * ARGUMENTS: row (Element) -- a <tr>.
 * CALLED BY: draft_common.js: sortTable (several places) and the row-click handler in the page-load handler.
 * RETURNS:   Element[] -- the visible <td> / <th> cells, in order.
 */
// the cells of a row (or header row) that are actually showing
function visibleCells(row) {
    return Array.from(row.cells).filter(c => c.style.display !== 'none');
}

/**
 * PURPOSE:   Show the right header row and the right group of columns for the current tab and stat view.
 *            Three column groups exist in the HTML: ".stat-real", ".stat-strat" and ".stat-all". The "All"
 *            tab (baseball, football) uses the "all" group; every other tab uses the group chosen in the
 *            Real / Strat dropdown. On the All tab the dropdown is hidden. Football's narrow All tab adds
 *            the "all-compact" CSS class so it packs to the left.
 *            A sport opts in to the "All" layout by defining SPORT.headFor(pos), which names the header row
 *            to use; basketball has no headFor, so only the real / strat groups switch.
 * ARGUMENTS: none (it reads currentPos and currentStat)
 * CALLED BY: draft_bb.js and draft_fb.js: filterPos; draft_common.js: switchStatView and the page-load
 *            handler.
 * RETURNS:   nothing.
 */
// shows the right header row and column group (real / strat / all) for the current tab.
// A sport opts in to an "All" layout by defining SPORT.headFor(pos) -> header row id.
function applyColumns() {
    const isAll = !!SPORT.headFor && currentPos === 'ALL';
    const mode  = isAll ? 'all' : currentStat;

    // show only the header row that matches this tab
    if (SPORT.headFor) {
        const headId = SPORT.headFor(currentPos);
        document.querySelectorAll('#tableHead tr').forEach(tr => {
            tr.style.display = (tr.id === headId) ? '' : 'none';
        });
    }
    // show only the column group that matches the mode
    ['real', 'strat', 'all'].forEach(g => {
        document.querySelectorAll('.stat-' + g).forEach(el => {
            el.style.display = (g === mode) ? '' : 'none';
        });
    });

    // nothing to toggle on the All tab
    const sv = document.getElementById('statView');
    if (sv) sv.style.display = isAll ? 'none' : '';

    // a sport with a narrow All tab (football) packs it to the left instead of stretching it
    const pane = document.querySelector('.pane-center');
    if (pane) pane.classList.toggle('all-compact', isAll && !!SPORT.compactAll);
}

/**
 * PURPOSE:   Sort the player pool by a column. Clicking the same column again reverses the order. The rules:
 *              column 1 (Name)        by LAST name, ignoring Jr / Sr / II..., then by the full name
 *              column 3 and later     as NUMBERS (handles "$11,150,000"); if both cells are text (Bats,
 *                                     Throws, Balance) alphabetically; a blank number counts as 0
 *              columns 0 and 2        alphabetically (position, team)
 *            Columns are counted among the VISIBLE cells only. After sorting, the arrows (↕ ↑ ↓) in the
 *            showing header row are updated. Sorting only reorders the existing rows.
 * ARGUMENTS: arg (Element | number) -- a <th> element (from onclick="sortTable(this)", used by baseball and
 *            football), or a plain visible-column number (from onclick="sortTable(3)", used by basketball).
 * CALLED BY: onclick on the header cells in bbdraft.html and fbdraft.html (sortTable(this)) and
 *            bkdraft.html (sortTable(number)).
 * RETURNS:   nothing.
 */
// sortTable(this) from a <th>, or sortTable(3) with a plain visible-column number
function sortTable(arg) {
    const tbody = document.getElementById('playerBody');
    const rows  = Array.from(tbody.querySelectorAll('tr'));
    const col   = (typeof arg === 'number') ? arg : visibleCells(arg.parentElement).indexOf(arg);
    if (col < 0) return;
    sortDir[col] = !sortDir[col];                 // flip ascending / descending for this column

    // helpers: the text of a row's cell in this column, and a cell's text as a number
    const text = row => { const c = visibleCells(row)[col]; return c ? c.innerText.trim() : ''; };
    const num  = v => parseFloat(v.replace(/[$,]/g, ''));          // handles "$11,150,000"

    rows.sort((a, b) => {
        const aVal = text(a), bVal = text(b);
        if (col === 1) {
            // the Name column: by last name, then by the whole name
            const c = lastNameKey(aVal).localeCompare(lastNameKey(bVal)) || aVal.localeCompare(bVal);
            return sortDir[col] ? c : -c;
        }
        if (col >= 3) {
            // the stat columns: numbers (or text if neither cell is a number)
            const x = num(aVal), y = num(bVal);
            if (isNaN(x) && isNaN(y)) {                            // text columns (Bats / Throws / Balance)
                return sortDir[col] ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
            }
            return sortDir[col] ? (x || 0) - (y || 0) : (y || 0) - (x || 0);
        }
        // position and team: plain alphabetical
        return sortDir[col] ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    });
    rows.forEach(r => tbody.appendChild(r));      // re-adding the rows in order moves them

    // sort arrows, only on the header row that's showing
    const head = Array.from(document.querySelectorAll('#tableHead tr, thead tr')).find(r => r.style.display !== 'none');
    if (head) {
        visibleCells(head).forEach((th, i) => {
            const icon = th.querySelector('.sort-icon');
            if (icon) icon.textContent = i === col ? (sortDir[col] ? '↑' : '↓') : '↕';
        });
    }
}

/**
 * PURPOSE:   The "Real Stats / Strat Stats" dropdown: remember the choice and redraw the right columns.
 * ARGUMENTS: view (string) -- "real" or "strat".
 * CALLED BY: onchange="switchStatView(this.value)" on the select with id statView in the three draft
 *            templates.
 * RETURNS:   nothing.
 */
function switchStatView(view) {
    currentStat = view;
    applyColumns();
}


// ── messages from the server ──
// Each socket.on(...) below is an EVENT HANDLER: the Socket.IO library calls it when the server sends that
// message. Nothing in our own code calls these directly. The server side of each message is in routes.py,
// section 7 ("SOCKET.IO").

/**
 * PURPOSE:   (event: "connect") The connection to the server just opened (or reopened after a drop). Ask for
 *            the complete current state so a fresh or refreshed page catches up.
 * ARGUMENTS: none
 * CALLED BY: the Socket.IO library, when the connection is made.
 * RETURNS:   nothing. The server answers with "full_sync" (handled below).
 */
socket.on('connect', () => {
    socket.emit('request_sync', { draftname: currentDraftname, sport: currentSport });
});

/**
 * PURPOSE:   (event: "pick_made") A pick just happened, by anyone: a human, an AI team, or an automatic
 *            timeout pick. Update EVERYTHING on the screen: the pick counter, the salary tracking, the pool
 *            row, the Draft Log, the roster slot (plus any two-way twin and its extra FLEX slot), clear the
 *            selection, move the roster panel and the "on the clock" label to the next team, redraw the logo
 *            strip, show the ticker announcement, and restart the clock for the next team (120 seconds for
 *            a human, 15 for AI).
 * ARGUMENTS: entry (object) -- the server's payload: {pick, team, player, pos, id, next_team,
 *            next_team_type, next_pick, bonus (a twin's entry or null)}. (Basketball's payload has no
 *            next_pick or bonus, so the next pick is worked out as pick + 1.)
 * CALLED BY: the Socket.IO library, when the server broadcasts "pick_made" (routes.py: handle_make_pick,
 *            handle_skip_pick, run_ai_picks_bb / bk / fb).
 * RETURNS:   nothing.
 */
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

/**
 * PURPOSE:   (event: "pick_error") The server refused a pick (not your turn, draft paused, player already
 *            taken, roster full...). Show the reason in a pop-up. Sent only to the browser that asked.
 * ARGUMENTS: data (object) -- {message: the reason}.
 * CALLED BY: the Socket.IO library, when the server sends "pick_error" (routes.py: handle_make_pick).
 * RETURNS:   nothing.
 */
socket.on('pick_error', (data) => {
    alert(data.message);
});

/**
 * PURPOSE:   (event: "cap_warning") The server says this pick might leave the team unable to finish its
 *            roster under the salary cap. Ask the user "Draft this player anyway?". If they say yes, resend
 *            the pick with confirmed: true so the server accepts it without warning again.
 * ARGUMENTS: data (object) -- {player_id, message: the warning text}.
 * CALLED BY: the Socket.IO library, when the server sends "cap_warning" (routes.py: handle_make_pick).
 * RETURNS:   nothing.
 */
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

/**
 * PURPOSE:   (event: "full_sync") The complete current state of the draft, sent in reply to our
 *            "request_sync". Rebuild everything that depends on history: spend totals, the pick counter,
 *            the running flag, the Start button, the whole Draft Log, the greyed-out pool rows, the
 *            "on the clock" label, the logo strip, the roster dropdown, and the clock (or the finished
 *            state if the draft is over).
 *            NOTE: this does not rebuild the roster slots' contents; those come from the page itself when
 *            it loads (routes.py draws them in the HTML).
 * ARGUMENTS: data (object) -- {log, current_team, current_team_type, running, complete, current_pick}.
 * CALLED BY: the Socket.IO library, when the server sends "full_sync" (routes.py: handle_request_sync).
 * RETURNS:   nothing.
 */
socket.on('full_sync', (data) => {
    rebuildSpend(data.log);
    currentPick  = data.current_pick;
    draftRunning = !!data.running;
    hasPicks     = data.log.length > 0;
    updateToggleBtn();

    // rebuild the Draft Log from scratch
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

    // grey out every player who has already been drafted
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

/**
 * PURPOSE:   (event: "draft_state") The draft was started / resumed or stopped (by anyone). Update the
 *            running flag: start the clock ticking from where it was frozen, or stop it. Update the Start /
 *            Stop button. Messages about OTHER drafts are ignored.
 * ARGUMENTS: data (object) -- {draftname, running: true/false}.
 * CALLED BY: the Socket.IO library, when the server broadcasts "draft_state" (routes.py:
 *            handle_start_draft, handle_pause_draft).
 * RETURNS:   nothing.
 */
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

// (event: "draft_complete") The last pick is in. The handler is showDraftComplete (above), passed in directly.
// Sent by routes.py: handle_make_pick, handle_skip_pick, handle_start_draft and the run_ai_picks_* loops.
socket.on('draft_complete', showDraftComplete);


// ── page load ──

/**
 * PURPOSE:   (event: "DOMContentLoaded") The page's HTML is fully loaded. Do the one-time setup:
 *              - draw the logo strip, build the salary lookup, total up each team's spend, update the
 *                salary line and scroll the log;
 *              - run the sport's own onReady hook (basketball hides its defense rows);
 *              - baseball and football start on the All tab with every row showing;
 *              - pick the starting Real / Strat columns;
 *              - show the roster of the team on the clock;
 *              - attach the click handler to every pool row (selecting a player fills the bar at the bottom);
 *              - set the first pick's clock (it only ticks once the draft is started).
 * ARGUMENTS: none
 * CALLED BY: the browser, once, when the page has loaded.
 * RETURNS:   nothing.
 */
document.addEventListener('DOMContentLoaded', () => {
    renderLogoStrip();
    buildSalaryMap();
    rebuildSpend(DRAFT.initialLog);
    updateSalaryLine();
    scrollLogToBottom();
    if (SPORT.onReady) SPORT.onReady();

    // baseball and football open on the All tab with every row showing (basketball keeps its DEF rows hidden)
    if (SPORT.headFor) {
        document.querySelectorAll('#playerBody tr').forEach(row => { row.style.display = ''; });
    }
    const sv = document.getElementById('statView');
    if (sv) currentStat = sv.value;                      // in case the browser remembered the dropdown
    applyColumns();

    // show the roster of the team on the clock (the server syncs again right after connecting)
    if (document.getElementById(`roster-${DRAFT.currentTeam}`)) {
        showRoster(DRAFT.currentTeam);
    } else {
        const first = document.querySelector('.roster-team');
        if (first) first.style.display = 'block';
    }

    // click a player row to select him (uses only the columns that are showing)
    document.querySelectorAll('#playerBody tr').forEach(row => {
        row.addEventListener('click', () => {
            selectedPlayerId = row.dataset.id;
            // the text of every visible cell: [position, name, team, stat, stat, ...]
            const c = visibleCells(row).map(td => td.innerText.trim());
            const isAll = !!SPORT.headFor && currentPos === 'ALL';
            // the first few stats, skipping blanks and the "—" placeholder
            const stats = c.slice(3, isAll ? 7 : 6).filter(t => t && t !== '—');
            document.getElementById('selectedName').textContent  = `${c[0]} — ${c[1]}`;
            document.getElementById('selectedStats').textContent = stats.length ? `${c[2]} | ${stats.join(' / ')}` : c[2];
            document.getElementById('draftBtn').style.display = 'inline-block';
            document.querySelectorAll('#playerBody tr').forEach(r => r.classList.remove('selected-row'));
            row.classList.add('selected-row');
        });
    });

    // the first pick's clock only ticks once the draft is started
    startTimer(DRAFT.currentTeamType === 'human' ? 120 : 15);
});