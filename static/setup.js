/* ===========================================================================================
   setup.js  --  the behavior of the SETUP pages (baseball.html, basketball.html, football.html, which
   all share templates/partials/setup_ui.html).

   WHAT IT DOES
     1. SAVED DRAFTS PANEL: a search box that filters the list, and a "Delete ... cannot be undone?"
        confirmation before a draft is deleted.
     2. THE NEW-DRAFT FORM:
          - counts the teams you've claimed ("2 / 4") and stops you from claiming more than the draft has
            (the counter shakes),
          - drops claimed teams that no longer fit when you lower the number of teams,
          - shows or hides the salary-cap amount box, and the Tight / Suggested / Loose preset buttons,
          - writes a one-line summary in the bottom bar ("4 teams · 1 yours · Complete pool · No cap"),
            including " · Berserker" when that mode is on,
          - keeps the Continue button disabled until at least one team is claimed (and, if a cap is on, an
            amount is entered).

   THE TEAM GRID arrives AFTER the page loads (htmx fetches it from /show_bb_logos etc.), so the form
   re-checks itself when htmx finishes ("htmx:afterSwap").

   REQUIRES (in setup_ui.html): #draftFilter, form.su-del, #newDraft, #goBtn, #summary, #teamCount,
   #capWrap, #cap_amount, #clearTeams, .su-presets buttons, and the radios named num_teams, human_teams,
   cap, pool and berserker.
   Loaded by the three setup pages (their "scripts" block).

   The whole file is wrapped in an IIFE ( (function () { ... })(); ) so its variables stay private.
   =========================================================================================== */
(function () {
  /**
   * PURPOSE:   Shortcut for document.querySelector (find ONE element), optionally inside a parent.
   * ARGUMENTS: s (string) -- a CSS selector.   r (Element) -- where to look (default: the whole page).
   * CALLED BY: every section of this file.
   * RETURNS:   Element | null -- the first match.
   */
  const $  = (s, r = document) => r.querySelector(s);

  /**
   * PURPOSE:   Shortcut for document.querySelectorAll, but returns a real array.
   * ARGUMENTS: s (string) -- a CSS selector.   r (Element) -- where to look (default: the whole page).
   * CALLED BY: every section of this file.
   * RETURNS:   Element[] -- all matches.
   */
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // ---------- saved drafts: search and delete confirmation ----------
  const filter = $('#draftFilter');        // the search box (only shown when there are more than 6 saved drafts)
  if (filter) {
    // (event: "input") Hide the saved drafts whose name doesn't contain what was typed.
    // Each <li> carries its lower-case name in data-name.
    filter.addEventListener('input', () => {
      const q = filter.value.trim().toLowerCase();
      $$('.su-draft').forEach(li => { li.hidden = q !== '' && !li.dataset.name.includes(q); });
    });
  }
  $$('form.su-del').forEach(f => {
    // (event: "submit" on each Delete button's form) Ask first. Cancelling stops the form from being sent.
    f.addEventListener('submit', e => {
      if (!confirm(`Delete "${f.dataset.name}" and all of its files? This cannot be undone.`)) e.preventDefault();
    });
  });

  // ---------- new draft form ----------
  const form = $('#newDraft');
  if (!form) return;      // not the setup form (e.g. only the saved-drafts panel): nothing more to do

  const goBtn    = $('#goBtn');            // the Continue button
  const summary  = $('#summary');          // the one-line summary text in the bottom bar
  const counter  = $('#teamCount');        // the "0 / 4" teams-claimed counter
  const capWrap  = $('#capWrap');          // the box holding the cap amount and preset buttons
  const capInput = $('#cap_amount');       // the cap amount number input

  /**
   * PURPOSE:   Read the "How many teams?" choice.
   * CALLED BY: confirm... no: setup.js: refresh and the form's "change" handler.
   * RETURNS:   number -- the chosen team count (2, 4, 8, 12, 16, 24 or 32).
   */
  const numTeams = () => Number($('input[name="num_teams"]:checked', form).value);

  /**
   * PURPOSE:   Get the team checkboxes that are currently ticked (the teams the user claimed).
   * CALLED BY: setup.js: refresh, the "change" handler and the Clear button.
   * RETURNS:   Element[] -- the ticked checkboxes (the team grid is loaded by htmx, so this is empty until
   *            it arrives).
   */
  const mine     = () => $$('input[name="human_teams"]:checked', form);

  /**
   * PURPOSE:   Is the "Use a cap" option selected?
   * CALLED BY: setup.js: refresh.
   * RETURNS:   boolean.
   */
  const capOn    = () => $('input[name="cap"]:checked', form).value === 'Yes';

  /**
   * PURPOSE:   Is Berserker mode switched on?
   * CALLED BY: setup.js: refresh.
   * RETURNS:   boolean.
   */
  const bzOn     = () => $('input[name="berserker"]:checked', form).value === 'Yes';

  /**
   * PURPOSE:   Bring the whole form up to date with the current choices: the teams-claimed counter, the cap
   *            box's visibility (and whether the amount is required), the bottom-bar summary text, and
   *            whether the Continue button is enabled.
   * ARGUMENTS: none
   * CALLED BY: setup.js: the form's "change" handler, the cap box's "input" handler, the Clear button, the
   *            cap preset buttons, the htmx "afterSwap" handler and once at page load.
   * RETURNS:   nothing.
   */
  function refresh() {
    const n = numTeams();
    const picked = mine().length;
    const on = capOn();
    const amount = Number(capInput.value);

    counter.textContent = `${picked} / ${n}`;
    capWrap.hidden = !on;                 // show the cap box only when a cap is wanted
    capInput.required = on;               // ...and require an amount only then

    const poolName = { full: 'Complete pool', random: 'Random pool', custom: 'Custom pool' }[
      $('input[name="pool"]:checked', form).value
    ];
    const capText = !on ? 'No cap' : (amount > 0 ? `Cap $${amount.toLocaleString('en-US')}` : 'Cap amount needed');
    const modeText = bzOn() ? ' \u00b7 Berserker' : '';        // \u00b7 is the middle dot "·"

    summary.textContent = picked === 0
      ? 'Pick at least one team to continue'
      : `${n} teams \u00b7 ${picked} yours \u00b7 ${poolName} \u00b7 ${capText}${modeText}`;
    summary.classList.toggle('su-dim', picked === 0);          // grey text until a team is claimed
    // Continue needs at least one team, and an amount if the cap is on
    goBtn.disabled = !(picked > 0 && (!on || amount > 0));
  }

  /**
   * PURPOSE:   (event: "change" anywhere in the form) Something was clicked or selected. Two special cases:
   *              - the team count was changed: untick any claimed teams beyond the new count;
   *              - a team was ticked and now the user has claimed MORE teams than exist: undo that tick and
   *                make the counter shake (the "su-shake" animation is restarted by removing the class,
   *                forcing a reflow, and adding it back).
   *            Then refresh() everything.
   * CALLED BY: the browser, whenever a form control changes.
   * RETURNS:   nothing.
   */
  form.addEventListener('change', e => {
    const t = e.target;
    if (t.name === 'num_teams') {
      mine().slice(numTeams()).forEach(b => { b.checked = false; });   // drop picks that no longer fit
    }
    if (t.name === 'human_teams' && mine().length > numTeams()) {
      t.checked = false;                                              // can't claim more teams than exist
      counter.classList.remove('su-shake');
      void counter.offsetWidth;                                       // (forces the browser to restart the animation)
      counter.classList.add('su-shake');
    }
    refresh();
  });

  // (event: "input") Typing in the cap amount box updates the summary and the Continue button live.
  form.addEventListener('input', e => { if (e.target === capInput) refresh(); });

  // (event: "click" on "Clear") Untick every claimed team.
  $('#clearTeams').addEventListener('click', () => {
    mine().forEach(b => { b.checked = false; });
    refresh();
  });

  // (event: "click" on a Tight / Suggested / Loose button) Put that amount in the cap box.
  // The amount is in the button's data-amount (the server computed it; see cap_choices in routes.py).
  $$('.su-presets button', form).forEach(b => {
    b.addEventListener('click', () => { capInput.value = b.dataset.amount; refresh(); });
  });

  // (event: "htmx:afterSwap") The team grid has just been loaded into the page by htmx: recount.
  document.body.addEventListener('htmx:afterSwap', refresh);   // the team grid arrives after page load
  refresh();       // set the starting state
})();