(function () {
  document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('playerSearch');
    const body  = document.getElementById('playerBody');
    if (!input || !body) return;

    const countEl = document.getElementById('searchCount');
    const rows = Array.from(body.querySelectorAll('tr'));
    const norm = s => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    rows.forEach(r => { r._name = norm(r.cells[1] ? r.cells[1].textContent : ''); });

    const isHidden   = r => r.classList.contains('search-hidden');
    const visibleNow = r => !isHidden(r) && r.style.display !== 'none';
    let timer = null;

    function apply() {
      const tokens = norm(input.value).split(/\s+/).filter(Boolean);
      let matched = 0;
      rows.forEach(r => {
        const hit = tokens.length === 0 || tokens.every(t => r._name.includes(t));
        r.classList.toggle('search-hidden', !hit);
        if (hit) matched++;
      });

      if (tokens.length === 0) { countEl.textContent = ''; return; }

      // matches exist, but none are on the current tab: jump to the tab they live on
      if (matched > 0 && !rows.some(visibleNow)) {
        const positions = [...new Set(rows.filter(r => !isHidden(r)).map(r => r.dataset.pos))];
        const target = positions.length === 1 ? positions[0] : 'ALL';
        const btn = Array.from(document.querySelectorAll('.btn-pos'))
          .find(b => (b.getAttribute('onclick') || '').includes(`'${target}'`));
        if (btn) btn.click();
      }

      const shown = rows.filter(visibleNow).length;
      countEl.textContent = matched === 0
        ? 'No matches'
        : (shown === matched ? `${matched} found` : `${shown} here / ${matched} total`);
    }

    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(apply, 80); });

    input.addEventListener('keydown', e => {
      if (e.key === 'Escape') { input.value = ''; apply(); input.blur(); }
      if (e.key === 'Enter') {
        e.preventDefault();
        const first = Array.from(body.querySelectorAll('tr')).find(r => visibleNow(r) && !r.classList.contains('drafted'));
        if (first) { first.click(); first.scrollIntoView({ block: 'nearest' }); }
      }
    });

    document.addEventListener('keydown', e => {
      if (e.key === '/' && !/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) {
        e.preventDefault();
        input.focus();
        input.select();
      }
    });
  });
})();