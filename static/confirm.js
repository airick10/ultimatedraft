(function () {
  const $  = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // ---------- final confirm: draft name ----------
  const nameInput = $('#draftname');
  if (nameInput) {
    const btn  = $('#startBtn');
    const warn = $('#nameWarn');
    let existing = [];
    try {
      existing = JSON.parse(nameInput.dataset.existing || '[]').map(s => String(s).toLowerCase());
    } catch (e) { /* no list: skip the duplicate warning */ }

    const check = () => {
      const cleaned = nameInput.value.replace(/[\\\/:*?"<>|]/g, '');   // characters that can't go in a file name
      if (cleaned !== nameInput.value) nameInput.value = cleaned;
      const v = nameInput.value.trim();
      btn.disabled = v.length === 0;
      warn.hidden = !existing.includes(v.toLowerCase());
      btn.textContent = warn.hidden ? 'Start draft' : 'Open existing draft';
    };
    nameInput.addEventListener('input', check);
    check();
  }

  // ---------- final confirm: browse the pool ----------
  const poolSearch = $('#poolSearch');
  if (poolSearch) {
    poolSearch.addEventListener('input', () => {
      const q = poolSearch.value.trim().toLowerCase();
      $$('#poolList li').forEach(li => { li.hidden = q !== '' && !li.dataset.name.includes(q); });
    });
  }

  // ---------- custom pool picker ----------
  const poolForm = $('#poolForm');
  if (poolForm) {
    const groups = $$('.cf-group', poolForm);
    const submit = $('#poolSubmit');

    function update() {
      let ok = true;
      groups.forEach(g => {
        const need = Number(g.dataset.need);
        const n = $$('input[type=checkbox]:checked', g).length;
        const state = n >= need ? 'ok' : n === 0 ? 'empty' : 'part';
        g.dataset.state = state;
        $('.cf-count', g).textContent = `${n} / ${need}`;
        const pill = $(`.cf-pill[data-code="${g.dataset.code}"]`);
        if (pill) {
          pill.dataset.state = state;
          $('b', pill).textContent = `${n}/${need}`;
        }
        if (n < need) ok = false;
      });
      submit.disabled = !ok;
    }

    function randomFill(g) {
      const need  = Number(g.dataset.need);
      const boxes = $$('input[type=checkbox]', g);
      boxes.forEach(b => { b.checked = false; });
      for (let i = boxes.length - 1; i > 0; i--) {          // shuffle
        const j = Math.floor(Math.random() * (i + 1));
        [boxes[i], boxes[j]] = [boxes[j], boxes[i]];
      }
      boxes.slice(0, need).forEach(b => { b.checked = true; });
    }

    poolForm.addEventListener('click', e => {
      const b = e.target.closest('button[data-act]');
      if (!b) return;
      const g = b.closest('.cf-group');
      if (b.dataset.act === 'random') randomFill(g);
      if (b.dataset.act === 'none') $$('input[type=checkbox]', g).forEach(x => { x.checked = false; });
      if (b.dataset.act === 'all') {
        $$('input[type=checkbox]', g).forEach(x => { if (!x.closest('label').hidden) x.checked = true; });
      }
      update();
    });

    $('#randomAll').addEventListener('click', () => { groups.forEach(randomFill); update(); });
    poolForm.addEventListener('change', update);

    // per-group filter (Enter must not submit the form)
    $$('.cf-gsearch', poolForm).forEach(inp => {
      inp.addEventListener('keydown', e => { if (e.key === 'Enter') e.preventDefault(); });
      inp.addEventListener('input', () => {
        const q = inp.value.trim().toLowerCase();
        $$('label', inp.closest('.cf-group')).forEach(l => { l.hidden = q !== '' && !l.dataset.name.includes(q); });
      });
    });

    update();
  }
})();