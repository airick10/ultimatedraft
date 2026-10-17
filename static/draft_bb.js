/* Baseball specifics. Loads before draft_common.js. */
window.SPORT = {
    logoDir:     'baseball',
    logoCode:    'bb',
    defaultSlot: 'UT',                         // positions not listed below (DH and friends) go to UT
    posToSlot: {
        'C': 'C', '1B': '1B', '2B': '2B', '3B': '3B', 'SS': 'SS',
        'LF': 'LF', 'CF': 'CF', 'RF': 'RF', 'SP': 'S', 'RP': 'R', 'CL': 'R'
    },
    flexOnBonus: true,                         // a two-way pick adds a FLEX slot to that team
    labelFor: e => DRAFT.labels[String(e.id)] || e.player,       // roster label, e.g. "Cal Ripken (R)"
    // natural slot, then UT (hitters only), then FLEX
    findSlot: (root, label) =>
        openSlot(root, label)
        || (label !== 'S' && label !== 'R' ? openSlot(root, 'UT') : null)
        || openSlot(root, 'FLEX'),

    // which header row goes with which tab
    headFor: pos => pos === 'ALL' ? 'all-head'
                  : (pos === 'SP' || pos === 'RP') ? 'pitcher-head'
                  : 'hitter-head',
};

// position buttons: filter the rows, then swap the header and columns to match
function filterPos(btn, pos) {
    document.querySelectorAll('.btn-pos').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentPos = pos;
    document.querySelectorAll('#playerBody tr').forEach(row => {
        row.style.display = (pos === 'ALL' || row.dataset.pos === pos) ? '' : 'none';
    });
    applyColumns();
}