/* Football specifics. Loads before draft_common.js. */
const HB_FB_OVERFLOW = { 'HB': 'FB', 'FB': 'HB' };

const HEAD_FOR_POS_FB = {
    ALL: 'all-head',
    QB: 'passing-head',
    HB: 'rushing-head',   FB: 'rushing-head',
    TE: 'receiving-head', WR: 'receiving-head',
    DO: 'oldl-head',
    KP: 'special-head'
};

window.SPORT = {
    logoDir:     'football',
    logoCode:    'fb',
    defaultSlot: 'self',                       // unknown positions keep their own label
    posToSlot: { 'QB': 'QB', 'HB': 'HB', 'FB': 'FB', 'TE': 'TE', 'WR': 'WR', 'DO': 'Def', 'KP': 'Special' },
    flexOnBonus: true,                         // a two-way pick adds a FLEX slot to that team
    labelFor: e => e.player,
    // natural slot, then HB/FB overflow, then FLEX
    findSlot: (root, label) =>
        openSlot(root, label)
        || (HB_FB_OVERFLOW[label] ? openSlot(root, HB_FB_OVERFLOW[label]) : null)
        || openSlot(root, 'FLEX'),

    headFor: pos => HEAD_FOR_POS_FB[pos],
    compactAll: true,
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