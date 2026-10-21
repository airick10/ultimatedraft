/* ===========================================================================================
   confirm.js  --  the behavior of the CONFIRM pages (bb_confirm.html, bk_confirm.html, fb_confirm.html,
   which all share templates/partials/confirm_ui.html).

   THE CONFIRM PAGE HAS TWO FACES, and this file handles both (it simply does nothing for the face that
   isn't on the page):

     A) "FINAL CONFIRM"  (Complete and Random pools, and Custom after you've picked)
          - the "Name your draft" box: cleans the name, warns if a draft with that name already exists,
            and only enables the Start button once a name is typed
          - the "Browse all players" search box

     B) "CUSTOM POOL PICKER"  (first visit of a Custom pool)
          - one box of checkboxes per position group, each with a "need" count
          - counters that show progress (and turn green once a group has enough)
          - per-group Random / All / Clear buttons, a "Random fill all" button, and a name filter
          - the Continue button only enables once EVERY group has at least its required number

   REQUIRES (in confirm_ui.html): #draftname, #startBtn, #nameWarn, #poolSearch, #poolList, #poolForm,
   .cf-group (with data-need and data-code), .cf-pill, #poolSubmit, #randomAll, .cf-gsearch.
   Loaded by the three *_confirm.html pages (their "scripts" block).

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
   * PURPOSE:   Shortcut for document.querySelectorAll, but returns a real array (so .forEach / .filter /
   *            .map work).
   * ARGUMENTS: s (string) -- a CSS selector.   r (Element) -- where to look (default: the whole page).
   * CALLED BY: every section of this file.
   * RETURNS:   Element[] -- all matches.
   */
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // ---------- final confirm: draft name ----------
  const nameInput = $('#draftname');
  if (nameInput) {
    const btn  = $('#startBtn');
    const warn = $('#nameWarn');
    let existing = [];       // the names of drafts that already exist, lower-cased (from the page's data-existing)
    try {
      existing = JSON.parse(nameInput.dataset.existing || '[]').map(s => String(s).toLowerCase());
    } catch (e) { /* no list: skip the duplicate warning */ }

    /**
     * PURPOSE:   Check the draft name as it is typed:
     *              - remove the characters that can't be in a file name (\ / : * ? " < > |), because the
     *                name becomes part of the saved files' names;
     *              - disable the Start button until the name isn't blank;
     *              - show a warning, and change the button to "Open existing draft", if a draft with that
     *                name (any capitalization) already exists.
     * ARGUMENTS: none (it reads the name box)
     * CALLED BY: confirm.js: the name box's "input" handler (just below) and once at page load.
     * RETURNS:   nothing.
     */
    const check = () => {
      const cleaned = nameInput.value.replace(/[\\\/:*?"<>|]/g, '');   // characters that can't go in a file name
      if (cleaned !== nameInput.value) nameInput.value = cleaned;
      const v = nameInput.value.trim();
      btn.disabled = v.length === 0;
      warn.hidden = !existing.includes(v.toLowerCase());
      btn.textContent = warn.hidden ? 'Start draft' : 'Open existing draft';
    };
    nameInput.addEventListener('input', check);      // (event: "input") re-check on every keystroke
    check();                                         // and once now, so the button starts disabled
  }

  // ---------- final confirm: browse the pool ----------
  const poolSearch = $('#poolSearch');
  if (poolSearch) {
    // (event: "input") Hide the list items whose name doesn't contain what was typed.
    // Each <li> carries its lower-case name in data-name.
    poolSearch.addEventListener('input', () => {
      const q = poolSearch.value.trim().toLowerCase();
      $$('#poolList li').forEach(li => { li.hidden = q !== '' && !li.dataset.name.includes(q); });
    });
  }

  // ---------- custom pool picker ----------
  const poolForm = $('#poolForm');
  if (poolForm) {
    const groups = $$('.cf-group', poolForm);        // one box per position group
    const submit = $('#poolSubmit');                 // the Continue button

    /**
     * PURPOSE:   Recount every group and refresh the page: each group's "n / need" counter, its colour state
     *            (data-state: "empty" none picked, "part" some, "ok" enough picked), the matching pill in the
     *            sticky bar, and whether the Continue button is enabled (only when EVERY group has at
     *            least its needed number).
     *            Note: more than "need" is allowed (the state stays "ok"); the CSS has an "over" colour, but
     *            nothing here sets it.
     * ARGUMENTS: none
     * CALLED BY: confirm.js: the click handler (after any button), the "Random fill all" button, the form's
     *            "change" handler (after any checkbox) and once at page load.
     * RETURNS:   nothing.
     */
    function update() {
      let ok = true;
      groups.forEach(g => {
        const need = Number(g.dataset.need);                                  // set by the template: teams x multiplier
        const n = $$('input[type=checkbox]:checked', g).length;               // how many are ticked
        const state = n >= need ? 'ok' : n === 0 ? 'empty' : 'part';
        g.dataset.state = state;
        $('.cf-count', g).textContent = `${n} / ${need}`;
        const pill = $(`.cf-pill[data-code="${g.dataset.code}"]`);            // the summary pill for this group
        if (pill) {
          pill.dataset.state = state;
          $('b', pill).textContent = `${n}/${need}`;
        }
        if (n < need) ok = false;
      });
      submit.disabled = !ok;
    }

    /**
     * PURPOSE:   Pick `need` players at RANDOM in one group: untick everything, shuffle the checkboxes
     *            (Fisher-Yates shuffle), and tick the first `need`. (It ignores the name filter: hidden
     *            players can be chosen too.)
     * ARGUMENTS: g (Element) -- a group box (.cf-group).
     * CALLED BY: confirm.js: the group "Random N" buttons (click handler) and the "Random fill all" button.
     * RETURNS:   nothing. (The caller then runs update().)
     */
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

    /**
     * PURPOSE:   (event: "click" anywhere in the form) Handle the three small buttons in each group box, which
     *            carry data-act="random" / "all" / "none":
     *              random  pick `need` players at random in that group
     *              all     tick every player that the name filter isn't hiding
     *              none    clear that group
     *            then refresh the counters.
     * CALLED BY: the browser, on any click inside the form (clicks that aren't on one of those buttons are
     *            ignored at the first line).
     * RETURNS:   nothing.
     */
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

    /**
     * PURPOSE:   (event: "click" on the "Random fill all" button) Randomly fill EVERY group, then refresh.
     * CALLED BY: the browser, when #randomAll is clicked.
     * RETURNS:   nothing.
     */
    $('#randomAll').addEventListener('click', () => { groups.forEach(randomFill); update(); });

    // (event: "change") Any checkbox ticked or unticked: refresh the counters and the Continue button.
    poolForm.addEventListener('change', update);

    // per-group filter (Enter must not submit the form)
    $$('.cf-gsearch', poolForm).forEach(inp => {
      // (event: "keydown") Pressing Enter in a filter box would submit the whole form: block that.
      inp.addEventListener('keydown', e => { if (e.key === 'Enter') e.preventDefault(); });
      // (event: "input") Hide the players in this group whose name doesn't contain what was typed.
      inp.addEventListener('input', () => {
        const q = inp.value.trim().toLowerCase();
        $$('label', inp.closest('.cf-group')).forEach(l => { l.hidden = q !== '' && !l.dataset.name.includes(q); });
      });
    });

    update();       // set the counters and the Continue button for the starting (empty) state
  }
})();