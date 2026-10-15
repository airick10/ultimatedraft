/* Basketball specifics. Loads before draft_common.js. */
window.SPORT = {
    logoDir:     'basketball',
    logoCode:    'bk',
    defaultSlot: 'UT',
    posToSlot:   { 'C': 'C', 'F': 'F', 'G': 'G', 'DEF': 'Def' },
    flexOnBonus: false,                        // no two-way players in basketball
    labelFor: e => e.player,
    // natural slot, then UT (players only, never the defense slot)
    findSlot: (root, label) =>
        openSlot(root, label)
        || (label !== 'UT' && label !== 'Def' ? openSlot(root, 'UT') : null),
    // defense units only show under the DEF button
    onReady: () => {
        document.querySelectorAll('#playerBody tr[data-pos="DEF"]').forEach(r => { r.style.display = 'none'; });
    },
};

// position buttons: the DEF view has its own column headers
function filterPos(btn, pos) {
    document.querySelectorAll('.btn-pos').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const isDef = (pos === 'DEF');
    document.getElementById('player-head').style.display = isDef ? 'none' : '';
    document.getElementById('def-head').style.display    = isDef ? '' : 'none';
    document.querySelectorAll('#playerBody tr').forEach(row => {
        const rowPos = row.dataset.pos;
        row.style.display = (pos === 'ALL' ? rowPos !== 'DEF' : rowPos === pos) ? '' : 'none';
    });
}