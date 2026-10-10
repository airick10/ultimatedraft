(function () {
  const $  = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // ---------- saved drafts: search and delete confirmation ----------
  const filter = $('#draftFilter');
  if (filter) {
    filter.addEventListener('input', () => {
      const q = filter.value.trim().toLowerCase();
      $$('.su-draft').forEach(li => { li.hidden = q !== '' && !li.dataset.name.includes(q); });
    });
  }
  $$('form.su-del').forEach(f => {
    f.addEventListener('submit', e => {
      if (!confirm(`Delete "${f.dataset.name}" and all of its files? This cannot be undone.`)) e.preventDefault();
    });
  });

  // ---------- new draft form ----------
  const form = $('#newDraft');
  if (!form) return;

  const goBtn    = $('#goBtn');
  const summary  = $('#summary');
  const counter  = $('#teamCount');
  const capWrap  = $('#capWrap');
  const capInput = $('#cap_amount');

  const numTeams = () => Number($('input[name="num_teams"]:checked', form).value);
  const mine     = () => $$('input[name="human_teams"]:checked', form);
  const capOn    = () => $('input[name="cap"]:checked', form).value === 'Yes';

  function refresh() {
    const n = numTeams();
    const picked = mine().length;
    const on = capOn();
    const amount = Number(capInput.value);

    counter.textContent = `${picked} / ${n}`;
    capWrap.hidden = !on;
    capInput.required = on;

    const poolName = { full: 'Complete pool', random: 'Random pool', custom: 'Custom pool' }[
      $('input[name="pool"]:checked', form).value
    ];
    const capText = !on ? 'No cap' : (amount > 0 ? `Cap $${amount.toLocaleString('en-US')}` : 'Cap amount needed');

    summary.textContent = picked === 0
      ? 'Pick at least one team to continue'
      : `${n} teams \u00b7 ${picked} yours \u00b7 ${poolName} \u00b7 ${capText}`;
    summary.classList.toggle('su-dim', picked === 0);
    goBtn.disabled = !(picked > 0 && (!on || amount > 0));
  }

  form.addEventListener('change', e => {
    const t = e.target;
    if (t.name === 'num_teams') {
      mine().slice(numTeams()).forEach(b => { b.checked = false; });   // drop picks that no longer fit
    }
    if (t.name === 'human_teams' && mine().length > numTeams()) {
      t.checked = false;                                              // can't claim more teams than exist
      counter.classList.remove('su-shake');
      void counter.offsetWidth;
      counter.classList.add('su-shake');
    }
    refresh();
  });

  form.addEventListener('input', e => { if (e.target === capInput) refresh(); });

  $('#clearTeams').addEventListener('click', () => {
    mine().forEach(b => { b.checked = false; });
    refresh();
  });

  $$('.su-presets button', form).forEach(b => {
    b.addEventListener('click', () => { capInput.value = b.dataset.amount; refresh(); });
  });

  document.body.addEventListener('htmx:afterSwap', refresh);   // the team grid arrives after page load
  refresh();
})();