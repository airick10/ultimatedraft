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
};

// position buttons: swap the hitter / pitcher column headers and show the matching rows
function filterPos(btn, pos) {
    document.querySelectorAll('.btn-pos').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const isPitcher = (pos === 'SP' || pos === 'RP');
    const isAll = (pos === 'ALL');
    document.getElementById('hitter-head').style.display  = isPitcher ? 'none' : '';
    document.getElementById('pitcher-head').style.display = isPitcher ? '' : 'none';
    document.querySelectorAll('#playerBody tr').forEach(row => {
        row.style.display = (isAll || row.dataset.pos === pos) ? '' : 'none';
    });
}