/* ===========================================================================================
   poolsearch.js  --  the "Search first or last name" box above the player pool on the draft boards.

   WHAT IT DOES
     As you type, it hides every pool row whose name doesn't contain ALL of the words you typed (in any
     order, ignoring capitals and accents, so "alex rod" finds "Álex Rodríguez" and "ruth babe" finds
     "Babe Ruth"). It also:
       - shows a counter ("12 found", "No matches", or "3 here / 12 total"),
       - jumps to the right position tab when the matches aren't on the tab you're looking at,
       - Enter selects the first visible, undrafted match (same as clicking it),
       - Escape clears the box,
       - pressing "/" anywhere on the page (outside a text box) focuses the search box.

   HOW IT HIDES ROWS
     It adds / removes the CSS class "search-hidden" on each row (the board stylesheets make that class
     display:none). That is separate from the position-tab hiding, which sets the row's inline
     style.display, so a row shows only if BOTH say it should.

   REQUIRES (in the draft templates)
     input#playerSearch, span#searchCount, tbody#playerBody, and each row's data-pos.
     Loaded by bbdraft.html / bkdraft.html / fbdraft.html AFTER draft_common.js.

   The whole file is wrapped in an IIFE ( (function () { ... })(); ) so its variables stay private.
   =========================================================================================== */
(function () {
  /**
   * PURPOSE:   (event: "DOMContentLoaded") The page has loaded: find the search box and the pool, prepare
   *            every row's searchable name, and wire up the typing, Enter / Escape and "/" shortcuts.
   *            Does nothing if the page has no search box (so it is harmless on other pages).
   * ARGUMENTS: none
   * CALLED BY: the browser, once, when the page has loaded.
   * RETURNS:   nothing.
   */
  document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('playerSearch');
    const body  = document.getElementById('playerBody');
    if (!input || !body) return;

    const countEl = document.getElementById('searchCount');
    const rows = Array.from(body.querySelectorAll('tr'));       // captured once; sorting only moves these same rows

    /**
     * PURPOSE:   Make text comparable: lowercase, and with accents removed ("Á" -> "a").
     * ARGUMENTS: s (string) -- any text.
     * CALLED BY: poolsearch.js: the row-name setup just below, and apply().
     * RETURNS:   string -- the simplified text.
     */
    const norm = s => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

    // Store each row's searchable name on the row itself (the text of its 2nd cell, the Name column).
    rows.forEach(r => { r._name = norm(r.cells[1] ? r.cells[1].textContent : ''); });

    /**
     * PURPOSE:   Is this row currently hidden by the SEARCH (not by the position tab)?
     * ARGUMENTS: r (Element) -- a pool row.
     * CALLED BY: poolsearch.js: visibleNow and apply().
     * RETURNS:   boolean.
     */
    const isHidden   = r => r.classList.contains('search-hidden');

    /**
     * PURPOSE:   Is this row visible RIGHT NOW: not hidden by the search AND not hidden by the position tab?
     * ARGUMENTS: r (Element) -- a pool row.
     * CALLED BY: poolsearch.js: apply() and the Enter handler.
     * RETURNS:   boolean.
     */
    const visibleNow = r => !isHidden(r) && r.style.display !== 'none';

    let timer = null;          // the pending "wait for typing to pause" timer

    /**
     * PURPOSE:   Run the search: split what was typed into words, hide every row that doesn't contain all of
     *            them, update the counter, and (if there are matches but none are on the current tab) click
     *            the position-tab button that shows them: the matches' tab if they all share one position,
     *            otherwise "All".
     * ARGUMENTS: none (it reads the search box)
     * CALLED BY: poolsearch.js: the typing handler (after a short pause) and the Escape key handler.
     * RETURNS:   nothing.
     */
    function apply() {
      const tokens = norm(input.value).split(/\s+/).filter(Boolean);      // the words typed
      let matched = 0;
      rows.forEach(r => {
        // a row matches when its name contains EVERY word (empty search = everything matches)
        const hit = tokens.length === 0 || tokens.every(t => r._name.includes(t));
        r.classList.toggle('search-hidden', !hit);
        if (hit) matched++;
      });

      if (tokens.length === 0) { countEl.textContent = ''; return; }

      // matches exist, but none are on the current tab: jump to the tab they live on
      if (matched > 0 && !rows.some(visibleNow)) {
        const positions = [...new Set(rows.filter(r => !isHidden(r)).map(r => r.dataset.pos))];
        const target = positions.length === 1 ? positions[0] : 'ALL';
        // find the tab button by looking for the position inside its onclick text: onclick="filterPos(this,'SS')"
        const btn = Array.from(document.querySelectorAll('.btn-pos'))
          .find(b => (b.getAttribute('onclick') || '').includes(`'${target}'`));
        if (btn) btn.click();
      }

      const shown = rows.filter(visibleNow).length;
      countEl.textContent = matched === 0
        ? 'No matches'
        : (shown === matched ? `${matched} found` : `${shown} here / ${matched} total`);
    }

    /**
     * PURPOSE:   (event: "input") You typed in the box. Wait 80 milliseconds after the LAST keystroke, then
     *            run apply(), so a fast typist doesn't trigger a search on every letter.
     * CALLED BY: the browser, on every change to the search box.
     * RETURNS:   nothing.
     */
    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(apply, 80); });

    /**
     * PURPOSE:   (event: "keydown" in the search box)
     *              Escape  clear the box, show everyone again, and leave the box.
     *              Enter   select the first visible, not-yet-drafted row (it clicks the row, so the normal
     *                      select-a-player handler in draft_common.js runs) and scroll it into view.
     * CALLED BY: the browser, on every key pressed while the search box is focused.
     * RETURNS:   nothing.
     */
    input.addEventListener('keydown', e => {
      if (e.key === 'Escape') { input.value = ''; apply(); input.blur(); }
      if (e.key === 'Enter') {
        e.preventDefault();                       // don't let Enter do anything else
        // the rows are looked up again here because sorting may have changed their order in the page
        const first = Array.from(body.querySelectorAll('tr')).find(r => visibleNow(r) && !r.classList.contains('drafted'));
        if (first) { first.click(); first.scrollIntoView({ block: 'nearest' }); }
      }
    });

    /**
     * PURPOSE:   (event: "keydown" anywhere on the page) The "/" shortcut: jump to the search box and select
     *            its text, unless you're already typing in a text box, dropdown or text area.
     * CALLED BY: the browser, on every key pressed on the page.
     * RETURNS:   nothing.
     */
    document.addEventListener('keydown', e => {
      if (e.key === '/' && !/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) {
        e.preventDefault();                       // don't type a "/" into the page
        input.focus();
        input.select();
      }
    });
  });
})();