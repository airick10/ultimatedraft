/* Football specifics. Loads before draft_common.js. */
const HB_FB_OVERFLOW = { 'HB': 'FB', 'FB': 'HB' };

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
};

// position buttons: each group of positions has its own column headers
function filterPos(btn, pos) {
    document.querySelectorAll('.btn-pos').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    const isAll      = (pos === 'ALL');
    const isPasser   = (pos === 'QB');
    const isRusher   = (pos === 'HB' || pos === 'FB');
    const isReceiver = (pos === 'TE' || pos === 'WR');
    const isOLDL     = (pos === 'DO');
    const isSpecial  = (pos === 'KP');

    document.getElementById('passing-head').style.display   = (isPasser || isAll) ? '' : 'none';
    document.getElementById('rushing-head').style.display   = isRusher ? '' : 'none';
    document.getElementById('receiving-head').style.display = isReceiver ? '' : 'none';
    document.getElementById('oldl-head').style.display      = isOLDL ? '' : 'none';
    document.getElementById('special-head').style.display   = isSpecial ? '' : 'none';

    document.querySelectorAll('#playerBody tr').forEach(row => {
        row.style.display = (isAll || row.dataset.pos === pos) ? '' : 'none';
    });
}