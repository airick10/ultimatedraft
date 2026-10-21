/* ===========================================================================================
   draft_fb.js  --  the FOOTBALL-specific part of the draft board.

   WHAT THIS FILE DOES
     Describes everything about football that draft_common.js can't know: where the logos live, which
     roster slot each position fills, which table header goes with which tab, and how the position tabs
     work. It defines the global window.SPORT, two helper tables, and the global function filterPos().

   LOAD ORDER
     Loaded by fbdraft.html BEFORE draft_common.js.

   NOTES
     - Football has two-way players (QB/WR, HB/TE, HB/WR), so a two-way pick adds a FLEX slot.
     - There are six different header rows (passing, rushing, receiving, defense/line, special, and the
       narrow All tab) because each kind of record has its own stats.
   =========================================================================================== */

// Halfbacks and fullbacks may fill each other's slots once their own are full.
// (The same rule exists in Python: HB_FB_OVERFLOW in services.py. Keep them in step.)
const HB_FB_OVERFLOW = { 'HB': 'FB', 'FB': 'HB' };

// Which header row of the pool table goes with which position tab. The values are the ids of the <tr> rows
// inside fbdraft.html's <thead id="tableHead">. (OL/DL tab -> "DO"; the Special tab -> "KP".)
const HEAD_FOR_POS_FB = {
    ALL: 'all-head',
    QB: 'passing-head',
    HB: 'rushing-head',   FB: 'rushing-head',
    TE: 'receiving-head', WR: 'receiving-head',
    DO: 'oldl-head',
    KP: 'special-head'
};

/**
 * window.SPORT -- football's settings. draft_common.js reads these properties:
 *
 *   logoDir, logoCode   the logo folder and file ending ("football", "fb")
 *   defaultSlot         "self" = a position that isn't listed keeps its own label as the slot
 *   posToSlot           position code -> roster slot. DO (defense / offensive-line unit) fills "Def"; KP
 *                       (special-teams unit) fills "Special".
 *                       (The same table exists in Python: SHORT_POS_TO_SLOT_FB in services.py.)
 *   flexOnBonus         true: drafting a two-way player adds a FLEX slot to that team's roster panel
 *   labelFor            function(entry) -> the text shown in the roster slot
 *   findSlot            function(root, label) -> the empty slot element to fill, or null
 *   headFor             function(pos) -> the id of the header row for that tab
 *   compactAll          true: the All tab only has three columns, so it is packed to the left (adds the
 *                       "all-compact" CSS class, see fbstyle.css and responsive.css)
 */
window.SPORT = {
    logoDir:     'football',
    logoCode:    'fb',
    defaultSlot: 'self',                       // unknown positions keep their own label
    posToSlot: { 'QB': 'QB', 'HB': 'HB', 'FB': 'FB', 'TE': 'TE', 'WR': 'WR', 'DO': 'Def', 'KP': 'Special' },
    flexOnBonus: true,                         // a two-way pick adds a FLEX slot to that team

    /**
     * PURPOSE:   The text for a drafted player in the roster panel: just the name from the pick.
     * ARGUMENTS: e (object) -- the pick entry: {player, ...}.
     * CALLED BY: draft_common.js: applyPickToUI (through SPORT.labelFor).
     * RETURNS:   string -- the name.
     */
    labelFor: e => e.player,

    /**
     * PURPOSE:   Find the empty roster slot a football pick should fill: his natural slot, then the HB/FB
     *            overflow slot (an HB may take an open FB slot and vice versa), then a FLEX slot. (The same
     *            order the server uses in assign_picks_to_slots_fb in services.py.)
     * ARGUMENTS: root  (Element) -- the team's roster block.
     *            label (string)  -- the pick's natural slot label.
     * CALLED BY: draft_common.js: applyPickToUI (through SPORT.findSlot).
     * RETURNS:   Element | null -- the empty slot, or null (the caller then takes ANY empty slot).
     */
    // natural slot, then HB/FB overflow, then FLEX
    findSlot: (root, label) =>
        openSlot(root, label)
        || (HB_FB_OVERFLOW[label] ? openSlot(root, HB_FB_OVERFLOW[label]) : null)
        || openSlot(root, 'FLEX'),

    /**
     * PURPOSE:   Say which header row of the pool table goes with a position tab, by looking it up in
     *            HEAD_FOR_POS_FB. Having this function is what switches on the All-tab layout.
     * ARGUMENTS: pos (string) -- the tab: "ALL", "QB", "HB", "FB", "TE", "WR", "DO" or "KP".
     * CALLED BY: draft_common.js: applyColumns (through SPORT.headFor).
     * RETURNS:   string -- the id of the header row (undefined for an unknown tab).
     */
    headFor: pos => HEAD_FOR_POS_FB[pos],
    compactAll: true,
};

/**
 * PURPOSE:   The position-tab buttons above the pool (All, QB, HB, FB, TE, WR, OL/DL, Special). Highlights
 *            the clicked button, remembers the tab, shows only the matching rows ("All" shows everyone), and
 *            then swaps the header row and columns to match (applyColumns).
 * ARGUMENTS: btn (Element) -- the button that was clicked.
 *            pos (string)  -- its tab: "ALL", "QB", "HB", "FB", "TE", "WR", "DO" or "KP".
 * CALLED BY: onclick="filterPos(this,'QB')" on the .btn-pos buttons in fbdraft.html; poolsearch.js (it
 *            calls btn.click() on one of these buttons to jump to the tab a search result is on).
 * RETURNS:   nothing.
 */
// position buttons: filter the rows, then swap the header and columns to match
function filterPos(btn, pos) {
    document.querySelectorAll('.btn-pos').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentPos = pos;                                  // (a global defined in draft_common.js)
    document.querySelectorAll('#playerBody tr').forEach(row => {
        row.style.display = (pos === 'ALL' || row.dataset.pos === pos) ? '' : 'none';
    });
    applyColumns();                                    // (defined in draft_common.js)
}