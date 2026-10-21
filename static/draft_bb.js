/* ===========================================================================================
   draft_bb.js  --  the BASEBALL-specific part of the draft board.

   WHAT THIS FILE DOES
     Describes everything about baseball that draft_common.js can't know: where the logos live, which
     roster slot each position fills, and how the pool table's tabs work. It does this by defining a
     global object, window.SPORT, plus one global function, filterPos().

   LOAD ORDER
     Loaded by bbdraft.html BEFORE draft_common.js (which reads window.SPORT while it runs).
     (basketball and football have their own matching files: draft_bk.js and draft_fb.js.)

   FUNCTIONS IN THIS FILE
     filterPos()  the position-tab buttons
     plus the small arrow functions inside window.SPORT: labelFor, findSlot, headFor.
   =========================================================================================== */

/**
 * window.SPORT -- baseball's settings. draft_common.js reads these properties:
 *
 *   logoDir      the folder name used in the fictional-team logo address (".../fictional/baseball/...")
 *   logoCode     the file-name ending of those logos ("Neptunes_bb.png")
 *   defaultSlot  the roster slot for a position that isn't listed in posToSlot (DH and anything unknown)
 *   posToSlot    position code -> roster slot label. SP -> S (starter), RP and CL -> R (reliever).
 *                (The same table exists in Python: SHORT_POS_TO_SLOT_BB in services.py. Keep them in step.)
 *   flexOnBonus  true = drafting a two-way player adds a FLEX slot to that team's roster panel
 *   labelFor     function(entry) -> the text shown in the roster slot, e.g. "Cal Ripken (R)"
 *   findSlot     function(root, label) -> the empty slot element to fill, or null
 *   headFor      function(pos) -> the id of the pool table's header row for that tab
 */
window.SPORT = {
    logoDir:     'baseball',
    logoCode:    'bb',
    defaultSlot: 'UT',                         // positions not listed below (DH and friends) go to UT
    posToSlot: {
        'C': 'C', '1B': '1B', '2B': '2B', '3B': '3B', 'SS': 'SS',
        'LF': 'LF', 'CF': 'CF', 'RF': 'RF', 'SP': 'S', 'RP': 'R', 'CL': 'R'
    },
    flexOnBonus: true,                         // a two-way pick adds a FLEX slot to that team

    /**
     * PURPOSE:   The text for a drafted player in the roster panel. Uses the labels the server prepared
     *            (DRAFT.labels, e.g. "Cal Ripken (R)" with his batting / throwing hand); falls back to the
     *            plain name from the pick if there isn't one.
     * ARGUMENTS: e (object) -- the pick entry: {id, player, ...}.
     * CALLED BY: draft_common.js: applyPickToUI (through SPORT.labelFor).
     * RETURNS:   string -- the label.
     */
    labelFor: e => DRAFT.labels[String(e.id)] || e.player,       // roster label, e.g. "Cal Ripken (R)"

    /**
     * PURPOSE:   Find the empty roster slot a baseball pick should fill: his natural slot first, then a UT
     *            slot (hitters only, never pitchers), then a FLEX slot. (The same order the server uses in
     *            assign_picks_to_slots_bb in services.py.)
     * ARGUMENTS: root  (Element) -- the team's roster block.
     *            label (string)  -- the pick's natural slot label (from mapPosToSlot).
     * CALLED BY: draft_common.js: applyPickToUI (through SPORT.findSlot).
     * RETURNS:   Element | null -- the empty slot, or null (the caller then takes ANY empty slot).
     */
    // natural slot, then UT (hitters only), then FLEX
    findSlot: (root, label) =>
        openSlot(root, label)
        || (label !== 'S' && label !== 'R' ? openSlot(root, 'UT') : null)
        || openSlot(root, 'FLEX'),

    /**
     * PURPOSE:   Say which header row of the pool table goes with a position tab: the All tab has its own
     *            (AVG, HR, W, ERA...), pitcher tabs (SP, RP) use the pitcher header, and every other tab
     *            uses the hitter header. Having this function is what switches on the All-tab layout.
     * ARGUMENTS: pos (string) -- the tab: "ALL", "C", "SP"...
     * CALLED BY: draft_common.js: applyColumns (through SPORT.headFor).
     * RETURNS:   string -- the id of the header row: "all-head", "pitcher-head" or "hitter-head" (these
     *            rows are in bbdraft.html's <thead id="tableHead">).
     */
    // which header row goes with which tab
    headFor: pos => pos === 'ALL' ? 'all-head'
                  : (pos === 'SP' || pos === 'RP') ? 'pitcher-head'
                  : 'hitter-head',
};

/**
 * PURPOSE:   The position-tab buttons above the pool (All, C, 1B ... SP, RP). Highlights the clicked button,
 *            remembers the tab, shows only the matching rows ("All" shows everyone), and then swaps the
 *            header row and columns to match (applyColumns).
 * ARGUMENTS: btn (Element) -- the button that was clicked.
 *            pos (string)  -- its tab: "ALL", "C", "1B", "2B", "SS", "3B", "LF", "CF", "RF", "SP", "RP".
 * CALLED BY: onclick="filterPos(this,'SS')" on the .btn-pos buttons in bbdraft.html; poolsearch.js
 *            (it calls btn.click() on one of these buttons to jump to the tab a search result is on).
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