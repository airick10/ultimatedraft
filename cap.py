"""
cap.py  --  salary-cap math shared by the AI drafters and the human-pick warnings.

THE QUESTION THIS FILE ANSWERS
    "If this team drafts player P right now, can it still fill EVERY other open roster slot with
    undrafted players and stay under the salary cap?"

    Without this check a team could spend most of its cap on three stars and then be unable to
    afford anyone for its last ten slots. That would break the draft.

THE TRICK THAT KEEPS IT SIMPLE
    To know if a team can still finish, we only need the CHEAPEST possible way to fill the open
    slots:
      1. Each position-specific slot (C, 1B, QB...) takes the cheapest undrafted player at that
         position.
      2. Then the "free" slots (UT, then FLEX) take the cheapest of whoever is left.
    If even that cheapest roster is over the cap, the pick is not safe. For the slot layouts in
    this app that greedy approach is exact (it finds the true minimum).

THE THREE PIECES
    salary_of(player)   turns a player's salary text ("$11,150,000") into a number.
    CapRules            a small bundle of sport-specific rules (see the class below).
    CapChecker          does the actual math for ONE team at ONE moment in the draft.

WHO USES THIS FILE
    - ai.py       imports CapChecker, CapRules and salary_of. It builds the CAP_RULES table
                  (one CapRules per sport) and make_cap_checker(), which makes a CapChecker.
    - tiers.py    imports salary_of to rank tiered players by salary.
    - routes.py   imports salary_of (for the suggested-cap calculation); it also calls
                  CapChecker.warning() through human_cap_warning().
"""

from collections import Counter   # a dict that counts things: Counter(["C","C","1B"]) -> {"C":2, "1B":1}


def salary_of(player):
    """
    PURPOSE:
        Read a player's salary as a plain number. Salary data arrives as text such as
        "$11,150,000 " (baseball keeps it under the key "s_sal", basketball and football under
        "Salary"), so this strips the "$", commas and spaces and converts it.

    ARGUMENTS:
        player (dict) -- one player record from the draft's player list.

    CALLED BY:
        - cap.py:   CapChecker.__init__ (to sort the pool by price), CapChecker.evaluate,
                    CapChecker.feasible and CapChecker.warning.
        - tiers.py: _choose (to rank targets by salary).
        - ai.py:    ai_select_bb, ai_select_bk, ai_select_fb ("last resort" cheapest-player
                    sorting) and make_cap_checker (adds up what a team has already spent).
        - routes.py: suggested_cap (averages every salary in the data files).

    RETURNS:
        float -- the salary in dollars. 0.0 if there is no salary on the record or it can't be
                 read. (A 0.0 means "unknown", and CapChecker ignores such players when it
                 works out the cheapest way to fill a roster.)
    """
    # Baseball uses "s_sal"; basketball and football use "Salary". "or" picks the first one
    # that has something in it.
    raw = player.get("s_sal") or player.get("Salary")

    # Neither key exists on this record: no salary known.
    if raw is None:
        return 0.0

    try:
        # str(...) so numbers and text are handled the same way, then remove the characters
        # that stop float() from understanding it.
        return float(str(raw).replace("$", "").replace(",", "").strip())
    except ValueError:
        # Something like "n/a" or "Feb-00" (an Excel date accident): treat as unknown.
        return 0.0


class CapRules:
    """
    PURPOSE:
        Holds the three sport-specific rules CapChecker needs, so CapChecker itself never has
        to know whether it's looking at baseball, basketball or football. Think of it as a
        small "settings card" for one sport.

    THE THREE RULES (stored as attributes)
        natural(p)   function -> str.
                     The slot label a player NATURALLY belongs to. Examples: baseball "SS" or
                     "S" (starting pitcher), basketball "C" or "Def", football "QB" or "HB".
        free         dict {label: can_fill(p)}.
                     The slots that can take MORE THAN ONE kind of player: UT (any hitter) and
                     FLEX (anyone). Each label maps to a function that says whether a given
                     player may fill it. The ORDER matters: restricted slots (UT) come before
                     the open-to-anyone one (FLEX), so cheap hitters aren't wasted on FLEX.
        priority(p)  function -> list of str.
                     The slot labels a drafted player will try, in order, such as
                     [natural slot, "UT", "FLEX"]. A None in the list is skipped.

    CALLED BY:
        - ai.py: the CAP_RULES table near the bottom of the file builds one CapRules each for
          "bb", "bk" and "fb".
    """

    def __init__(self, natural, free, priority):
        """
        PURPOSE:
            Store the three rules on the new object.

        ARGUMENTS:
            natural  (function) -- player dict -> natural slot label (str).
            free     (dict)     -- {slot label (str): function(player) -> bool}.
            priority (function) -- player dict -> list of slot labels to try, in order.

        CALLED BY:
            - ai.py: the CAP_RULES = { ... } table (module level, runs once at import).

        RETURNS:
            None -- a constructor; Python hands back the new CapRules object itself.
        """
        self.natural = natural
        self.free = free
        self.priority = priority


class CapChecker:
    """
    PURPOSE:
        Answers cap questions for ONE team at ONE moment of the draft. It is built fresh for
        every AI pick (and every human pick when a cap is on), because what's open and what's
        been spent changes after each pick.

    WHAT IT KNOWS (set up in __init__)
        - which slots the team still has open,
        - how much the team has already spent,
        - the cap,
        - every undrafted player, pre-sorted by price into price lists, one per kind of slot.
          This pre-sorting is what makes "cheapest way to fill the roster" fast.

    TWO PUBLIC QUESTIONS IT ANSWERS
        feasible(player)  -> bool.  Used by the AI.      "Can we still finish if we take him?"
        warning(player)   -> dict.  Used by humans.       "Is this pick risky, and how?"
      Both lean on evaluate(), which does the real calculation.

    CALLED BY:
        - ai.py: make_cap_checker() builds it; ai_select_bb/bk/fb call .feasible() on it.
        - routes.py: human_cap_warning() gets one from make_cap_checker() and calls .warning().
    """

    def __init__(self, rules, pool, open_slots, spent, cap, twin_map=None, safety=1.0):
        """
        PURPOSE:
            Set up the checker: remember the situation, then build the sorted price lists.

        ARGUMENTS:
            rules      (CapRules)  -- this sport's rules (see the CapRules class).
            pool       (list[dict]) -- every UNDRAFTED player still available.
            open_slots (list[str])  -- one label per roster slot still open, duplicates included
                                      (a team missing two catchers passes ["C", "C", ...]).
            spent      (float)      -- salary this team has already drafted.
            cap        (float|str)  -- the salary cap, in dollars.
            twin_map   (dict|None)  -- {player id: twin player id} for two-way players.
                                      Drafting one also drafts the other.
            safety     (float)      -- a cushion multiplier on the "money still needed" number.
                                      1.0 = exact (used for human warnings). The AI passes 1.10,
                                      so it keeps 10% more than the bare minimum.

        CALLED BY:
            - ai.py: make_cap_checker() (the only place a CapChecker is created).

        RETURNS:
            None -- a constructor; Python hands back the new CapChecker object itself.
        """
        # --- remember the situation -------------------------------------------------------
        self.rules = rules
        self.cap = float(cap)
        self.spent = float(spent)
        self.safety = safety
        self.open = Counter(open_slots)              # {"C": 2, "UT": 3, ...}
        self.twin_map = twin_map or {}               # {} if there are no two-way players
        self.by_id = {str(p.get("id")): p for p in pool}   # quick lookup: id -> player

        # --- sort the pool by price, cheapest first -----------------------------------------
        # A list of (salary, id-as-text) pairs.
        ranked = sorted(((salary_of(p), str(p.get("id"))) for p in pool), key=lambda t: t[0])

        # (Same lookup as self.by_id, kept as a separate local name from the original code.
        #  Harmless duplicate; left alone so behavior stays exactly as before.)
        players = {str(p.get("id")): p for p in pool}

        # --- build the price lists ----------------------------------------------------------
        # by_label:   {slot label: [(salary, id), ...]} cheapest first, for position-specific
        #             slots (C, 1B, QB, Def...). Only players whose NATURAL slot is that label.
        # free_lists: {"UT": [...], "FLEX": [...]} cheapest first, for the shared slots. A player
        #             can appear in more than one list (a cheap hitter is in UT and in FLEX).
        self.by_label = {}
        self.free_lists = {label: [] for label in rules.free}

        for sal, pid in ranked:                      # walks the pool from cheapest to priciest
            if sal <= 0:
                # No salary on file: a team can't count on this player being affordable, so he
                # is left out of the "cheapest roster" math entirely.
                continue

            p = players[pid]
            nat = rules.natural(p)                   # e.g. "SS"

            # A natural slot that is NOT one of the shared slots goes in the by_label list.
            if nat and nat not in rules.free:
                self.by_label.setdefault(nat, []).append((sal, pid))

            # Then add him to every shared list he is allowed to fill.
            for label, can_fill in rules.free.items():
                if can_fill(p):
                    self.free_lists[label].append((sal, pid))

    def _slot_for(self, player, counts):
        """
        PURPOSE:
            Work out which still-open slot a drafted player would land in, by trying his
            priority list in order (natural slot first, then UT, then FLEX...).

        ARGUMENTS:
            player (dict)    -- the player being drafted.
            counts (Counter) -- {slot label: how many are still open}. This is a working copy
                                that evaluate() subtracts from as it fills slots.

        CALLED BY:
            - cap.py: CapChecker.evaluate (twice: once for the player, once for a two-way twin).

        RETURNS:
            str | None -- the slot label that will be used, or None if every slot he could take
                          is already full.
        """
        for label in self.rules.priority(player):
            # "label and ..." skips the None entries that priority() can contain.
            if label and counts.get(label, 0) > 0:
                return label
        return None

    def _fill_cost(self, counts, used):
        """
        PURPOSE:
            The core of the file. Works out the CHEAPEST total salary needed to fill every slot
            in `counts` with undrafted players, never using anyone in `used`.

        HOW:
            1. Position-specific slots first: for each one, take the cheapest not-yet-used
               players at that position.
            2. Then the shared slots (UT before FLEX): take the cheapest not-yet-used players
               that slot accepts.
            If any slot cannot be filled at all, the whole thing is impossible.

        ARGUMENTS:
            counts (Counter)  -- {slot label: slots still to fill} AFTER the pick being tested.
            used   (set[str]) -- ids that must not be reused (the player being tested, and his
                                 twin if he has one). The method copies this set, so the
                                 caller's set is never changed.

        CALLED BY:
            - cap.py: CapChecker.evaluate.

        RETURNS:
            float | None -- the minimum total salary, or None if some slot has nobody left who
                            can fill it.
        """
        used = set(used)          # work on a copy
        total = 0.0

        # ---- step 1: position-specific slots ------------------------------------------------
        for label, n in counts.items():
            # skip empty entries, and skip UT/FLEX (they're handled in step 2)
            if n <= 0 or label in self.rules.free:
                continue
            got = 0
            for sal, pid in self.by_label.get(label, ()):     # cheapest first
                if pid in used:
                    continue                                   # already spoken for
                used.add(pid)
                total += sal
                got += 1
                if got == n:                                   # slot group full
                    break
            if got < n:
                return None       # not enough players at this position to fill the roster

        # ---- step 2: shared slots, restricted ones (UT) before FLEX ---------------------------
        for label in self.rules.free:          # dict order = fill order
            n = counts.get(label, 0)
            got = 0
            for sal, pid in self.free_lists[label]:
                if got == n:
                    break
                if pid in used:
                    continue
                used.add(pid)
                total += sal
                got += 1
            if got < n:
                return None

        return total

    def evaluate(self, player):
        """
        PURPOSE:
            Pretend the team drafts `player` right now and report what that would cost and what
            it would leave to be filled. This is the shared calculation behind feasible() and
            warning().

            A two-way player is handled here too: his twin comes along (adding the twin's salary
            and one extra FLEX slot).

        ARGUMENTS:
            player (dict) -- the player being considered.

        CALLED BY:
            - cap.py: CapChecker.feasible and CapChecker.warning.

        RETURNS:
            tuple | None.
              (spend, reserve, slots_left)
                spend       (float) -- salary this pick adds (his, plus the twin's if two-way).
                reserve     (float) -- cheapest possible cost of filling all OTHER open slots.
                slots_left  (int)   -- how many slots would still be open afterwards.
              None if the pick can't be judged (the player fits no open slot, or the pool can't
              fill some other slot).
        """
        pid = str(player.get("id"))
        counts = Counter(self.open)          # a COPY, so the real open-slot counts stay intact
        spend = salary_of(player)
        used = {pid}                         # ids the "cheapest roster" must not reuse

        # Which open slot would he take? If none, we can't evaluate.
        label = self._slot_for(player, counts)
        if label is None:
            return None
        counts[label] -= 1                   # that slot is now spoken for

        # --- two-way player: the twin is drafted too ----------------------------------------
        twin = self.by_id.get(self.twin_map.get(pid))
        if twin is not None:
            used.add(str(twin.get("id")))
            spend += salary_of(twin)
            counts["FLEX"] += 1              # the extra FLEX slot a two-way pick creates
            twin_label = self._slot_for(twin, counts)
            if twin_label is None:
                return None
            counts[twin_label] -= 1

        # What would it cost to fill everything else that's still open?
        reserve = self._fill_cost(counts, used)
        if reserve is None:
            return None

        # Third value: how many slots remain open (ignoring any that went negative).
        return spend, reserve, sum(n for n in counts.values() if n > 0)

    def feasible(self, player):
        """
        PURPOSE:
            The AI's yes/no question: "after taking this player, can the team still finish its
            roster under the cap (with a safety cushion)?"

        ARGUMENTS:
            player (dict) -- the candidate player.

        CALLED BY:
            - ai.py: ai_select_bb, ai_select_bk and ai_select_fb, in a list comprehension
              ("affordable = [p for p in undrafted if checker.feasible(p)]"). Only players who
              pass become candidates.

        RETURNS:
            bool -- True if the pick is safe; False if it would bust the cap or leave too little
                    money for the remaining slots.
        """
        # Quick no: his salary alone pushes the team over the cap.
        if self.spent + salary_of(player) > self.cap:
            return False

        result = self.evaluate(player)
        if result is None:
            # We couldn't judge it (for example the pool can't fill a slot no matter what).
            # Don't block the pick over something that can't be checked.
            return True

        spend, reserve, _ = result
        # safety widens the reserve: with 1.10 the AI wants 10% more than the bare minimum.
        return self.spent + spend + reserve * self.safety <= self.cap

    def warning(self, player, tight=1.25):
        """
        PURPOSE:
            The human version of feasible(): instead of blocking, describe HOW risky the pick is
            so the page can show a "draft anyway?" prompt.

        ARGUMENTS:
            player (dict) -- the player the human clicked Draft on.
            tight  (float) -- how much breathing room counts as "fine". If the money left is
                              under reserve * tight (default 1.25 = 25% above the minimum), the
                              pick is flagged "tight".

        CALLED BY:
            - routes.py: human_cap_warning, which is called from handle_make_pick (the
              'make_pick' Socket.IO handler) before a human pick is accepted.

        RETURNS:
            None (the pick is fine) or a dict:
              {"level": "over" | "short" | "tight",
               "left":    dollars left after the pick (negative if over),
               "reserve": cheapest cost to fill the other slots,
               "slots":   how many slots would still be open}
              over  = the pick itself breaks the cap.
              short = the team could no longer afford even the cheapest players for its last slots.
              tight = affordable, but with almost no room to spare.
        """
        result = self.evaluate(player)

        # If evaluate() couldn't judge it, fall back to just the player's own salary.
        spend = result[0] if result else salary_of(player)
        reserve = result[1] if result else 0.0
        slots = result[2] if result else 0
        left = self.cap - self.spent - spend          # money remaining after this pick

        info = {"left": left, "reserve": reserve, "slots": slots}

        if left < 0:
            return {"level": "over", **info}          # over the cap right now
        if result is None:
            return None                               # can't judge more than that: no warning
        if left < reserve:
            return {"level": "short", **info}         # can't afford the cheapest finish
        if reserve > 0 and left < reserve * tight:
            return {"level": "tight", **info}         # affordable, but close
        return None                                   # all clear