/* ===========================================================================================
   draft_bk.js  --  the BASKETBALL-specific part of the draft board.

   WHAT THIS FILE DOES
     Describes everything about basketball that draft_common.js can't know: where the logos live, which
     roster slot each position fills, and how the position tabs work (including the separate DEF tab for
     defense units). It defines the global window.SPORT and the global function filterPos().

   LOAD ORDER
     Loaded by bkdraft.html BEFORE draft_common.js.

   DIFFERENCES FROM BASEBALL / FOOTBALL
     - No two-way players, so no FLEX slots (flexOnBonus is false).
     - No "All" layout: the pool has just two header rows, one for players and one for defense units, so
       there's no headFor function and no currentPos / applyColumns here.
     - Defense units (position "DEF") stay hidden except under the DEF tab.
   =========================================================================================== */

/**
 * window.SPORT -- basketball's settings. draft_common.js reads these properties:
 *
 *   logoDir, logoCode   the logo folder and file ending ("basketball", "bk")
 *   defaultSlot         the slot for an unlisted position ("UT")
 *   posToSlot           position code -> roster slot. A defense unit's code "DEF" fills the "Def" slot.
 *                       (The same table exists in Python: SHORT_POS_TO_SLOT_BK in services.py.)
 *   flexOnBonus         false: there are no two-way players in basketball
 *   labelFor            function(entry) -> the text shown in the roster slot
 *   findSlot            function(root, label) -> the empty slot element to fill, or null
 *   onReady             function() run once when the page loads (hides the defense rows)
 */
window.SPORT = {
    logoDir:     'basketball',
    logoCode:    'bk',
    defaultSlot: 'UT',
    posToSlot:   { 'C': 'C', 'F': 'F', 'G': 'G', 'DEF': 'Def' },
    flexOnBonus: false,                        // no two-way players in basketball

    /**
     * PURPOSE:   The text for a drafted player in the roster panel: just the name from the pick.
     * ARGUMENTS: e (object) -- the pick entry: {player, ...}.
     * CALLED BY: draft_common.js: applyPickToUI (through SPORT.labelFor).
     * RETURNS:   string -- the name.
     */
    labelFor: e => e.player,

    /**
     * PURPOSE:   Find the empty roster slot a basketball pick should fill: his natural slot (C, F, G or Def),
     *            then UT. Players never take the Def slot, and a defense unit never takes UT (that
     *            check is in the condition: UT is only tried when the label isn't "UT" or "Def").
     * ARGUMENTS: root  (Element) -- the team's roster block.
     *            label (string)  -- the pick's natural slot label.
     * CALLED BY: draft_common.js: applyPickToUI (through SPORT.findSlot).
     * RETURNS:   Element | null -- the empty slot, or null (the caller then takes ANY empty slot).
     */
    // natural slot, then UT (players only, never the defense slot)
    findSlot: (root, label) =>
        openSlot(root, label)
        || (label !== 'UT' && label !== 'Def' ? openSlot(root, 'UT') : null),

    /**
     * PURPOSE:   Run once when the page loads: hide every defense-unit row in the pool. They only show
     *            under the DEF tab (see filterPos below).
     * ARGUMENTS: none
     * CALLED BY: draft_common.js: the page-load handler (through SPORT.onReady).
     * RETURNS:   nothing.
     */
    // defense units only show under the DEF button
    onReady: () => {
        document.querySelectorAll('#playerBody tr[data-pos="DEF"]').forEach(r => { r.style.display = 'none'; });
    },
};

/**
 * PURPOSE:   The position-tab buttons above the pool (All, C, F, G, DEF). Highlights the clicked button and
 *            shows only the matching rows. "All" shows every PLAYER (defense units stay hidden). The DEF tab
 *            swaps the table header to the defense-unit header (def-head) and shows only the units.
 *            (Unlike baseball and football, this does not store currentPos or call applyColumns.)
 * ARGUMENTS: btn (Element) -- the button that was clicked.
 *            pos (string)  -- its tab: "ALL", "C", "F", "G" or "DEF".
 * CALLED BY: onclick="filterPos(this,'C')" on the .btn-pos buttons in bkdraft.html; poolsearch.js (it
 *            calls btn.click() on one of these buttons to jump to the tab a search result is on).
 * RETURNS:   nothing.
 */
// position buttons: the DEF view has its own column headers
function filterPos(btn, pos) {
    document.querySelectorAll('.btn-pos').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const isDef = (pos === 'DEF');
    // two header rows exist in bkdraft.html: player-head and def-head; show the one that fits the tab
    document.getElementById('player-head').style.display = isDef ? 'none' : '';
    document.getElementById('def-head').style.display    = isDef ? '' : 'none';
    document.querySelectorAll('#playerBody tr').forEach(row => {
        const rowPos = row.dataset.pos;
        // All: everything except defense units.  Any other tab: just that position.
        row.style.display = (pos === 'ALL' ? rowPos !== 'DEF' : rowPos === pos) ? '' : 'none';
    });
}