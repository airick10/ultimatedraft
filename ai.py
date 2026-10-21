"""
ai.py  --  the AI drafters for Ultimate Draft (baseball, basketball and football).

WHAT THIS FILE DOES
    Every time an AI-controlled team is "on the clock" (or a human's pick clock runs out), routes.py
    asks this file one question:

        "Given this team's roster so far and everyone still available, WHO should it draft?"

    The three entry points that answer it are:
        ai_select_bb(...)   baseball
        ai_select_bk(...)   basketball
        ai_select_fb(...)   football
    Each returns the "id" of the player to draft (or None if it truly found nobody; routes.py then
    has its own fallback).

    This is a port of an older command-line program (aipicks.py). That is why some names and numeric
    "position codes" look old-fashioned. The comments below explain them.

------------------------------------------------------------------------------------------------
THE BIG PICTURE: HOW ONE AI PICK IS MADE (the same skeleton for all three sports)
    1. Work out which roster slots the team still has OPEN.
    2. Build the list of "affordable" players: everyone undrafted who fits under the salary cap
       (cap.py's CapChecker). With no cap, that's simply every undrafted player.
    3. BERSERKER (berserker.py): if the team has Berserker mode on, roll the dice; ~70% of the time
       make a completely random (but legal) pick and stop here.
    4. TIERS (tiers.py): look for players marked tier 1 / tier 2 in the data that fit an open slot;
       usually take one of them and stop here.
    5. Otherwise the team's ARCHETYPE decides: each AI team has an "AIFocus" number (1-16) chosen at
       random when the draft was created. The AI_FOCUS_TABLE* tables say which stats that archetype
       prizes (home runs? strikeouts? salary?). The pool is SORTED by the chosen stat, and the team
       takes one of the top few with weighted randomness (best 40%, 2nd 30%, 3rd 20%, 4th 10%).
    6. If that finds nobody, a chain of fallbacks relaxes the rules one at a time, ending with
       "the cheapest player who fits an open slot".

------------------------------------------------------------------------------------------------
VOCABULARY USED THROUGHOUT
    roster_slots   the team's slot labels in order, e.g. ["C","C","1B",...,"UT",...,"S",...,"R",...]
                   (plus one "FLEX" for each two-way player the team has drafted).
    team_picks     this team's pick-log entries (dicts), oldest first; each has "pos", "id", etc.
    open slot      a roster slot that no pick has been matched to yet (services.assign_picks_to_*).
    natural slot   the slot a player belongs in by position: a shortstop's is "SS".
    UT             "utility": any HITTER may fill it (baseball); any non-defense player (basketball).
    FLEX           the extra slot a two-way player creates; anyone may fill it.
    undrafted      a player whose "team_id" is 0.
    affordable     undrafted AND passes the cap check (cap.py). Equals "undrafted" with no cap.
    AIFocus        the AI team's personality, 1-16 (stored on the team in the meta file).
    s_* / b_* / p_*  Strat-O-Matic ratings / real batting stats / real pitching stats in the data.

------------------------------------------------------------------------------------------------
WHO USES THIS FILE
    routes.py   imports: ai_select_bb, ai_select_bk, ai_select_fb (called from make_ai_pick_bb/bk/fb),
                parse_salary, to_float, open_position_lottery_bk and make_cap_checker.
    exports.py  imports: parse_salary.

THINGS WORTH KNOWING (details are in the comments next to each piece)
    - AI_FOCUS_TABLE (baseball), AI_FOCUS_TABLE_BK and AI_FOCUS_TABLE_FB are where you tune the AI's
      personalities. CAP_SAFETY, BAL_* and UT_BACKUPS_PER_POS are the other dials.
    - The "avg_salary" argument that runs through many functions is always float('inf') today (a leftover
      from the original program). It means "no salary ceiling" and is harmless.
    - Baseball's AI does NOT catch errors: a stat value the code can't turn into a number (like Excel's
      "Feb-00" date accident) will crash the AI loop. Basketball and football AI calls ARE wrapped in
      try/except in routes.py. Fix bad values in the source data.
"""

import random      # weighted dice rolls, shuffles, random tie-breaks
import math        # math.isfinite, used by to_float to reject "nan" and "inf"
import re          # regular expressions, used to read the handedness balance code (s_bal)

# Helpers from services.py:
#   assign_picks_to_slots_*   turn a team's picks into a filled-in roster (so we know what's still open)
#   SHORT_POS_TO_SLOT_BB/FB   position code -> roster slot label tables
#   HB_FB_OVERFLOW            football: halfbacks and fullbacks may fill each other's slots
#   twin_map_for              find two-way players' other record (for the cap math)
from .services import (
    assign_picks_to_slots_bb, assign_picks_to_slots_bk, assign_picks_to_slots_fb,
    SHORT_POS_TO_SLOT_BB, SHORT_POS_TO_SLOT_FB, HB_FB_OVERFLOW, twin_map_for
)
from collections import Counter                       # a dict that counts: Counter(["C","C"]) -> {"C": 2}
from .cap import CapChecker, CapRules, salary_of      # salary-cap math (see cap.py)
from .tiers import tier_pick                          # tier 1 / tier 2 targeting (see tiers.py)
from .berserker import is_berserker, berserker_roll, berserker_pick   # Berserker mode (see berserker.py)


# ============================================================
# Raw-data parsers
# The old aipicks.py assumed fields (DP1/DP2/DP3, Bat, Throw, Role, Price)
# that don't exist in this project's data. These derive equivalent values
# from the real fields (s_fielding, Bats, Throws, s_endurance, s_sal).
# ============================================================

def parse_salary(raw):
    """'$11,150,000 ' -> 11150000.0. Returns 0.0 if blank/unparseable.

    PURPOSE:
        Turn a salary written as text ("$11,150,000 ") into a plain number. Almost the same job as
        salary_of() in cap.py, but this one takes the RAW VALUE instead of a whole player record.

    ARGUMENTS:
        raw (str | int | float | None) -- the salary as found in the data.

    CALLED BY:
        - ai.py:      ai_select_snippet_bb, ai_sort_pool_bb, ai_select_snippet_bk, _defense_score,
                      ai_sort_pool_fb, ai_select_snippet_fb, make_cap_checker.
        - routes.py:  read_cap, make_ai_pick_bb, make_ai_pick_bk, make_ai_pick_fb (cap on/off and the
                      "cheapest undrafted" fallbacks) and human_cap_warning.
        - exports.py: cell_value, _salary, _team_meta_line and the three report builders (payroll).

    RETURNS:
        float -- the salary in dollars, or 0.0 if there is none or it can't be read.
    """
    if raw is None:
        return 0.0
    # remove the characters float() can't digest, then trim spaces
    cleaned = str(raw).replace('$', '').replace(',', '').strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def to_float(value, default=0.0):
    """Tolerant number parser: handles None, '$1,200', '45%', and junk like 'Feb-00' (-> default).

    PURPOSE:
        Read ANY stat value as a number without crashing. Used on stats that might be missing, written
        with "$" or "%", or damaged by Excel.

    ARGUMENTS:
        value   (any)   -- the raw value (None, a number, or text such as "45%").
        default (float) -- what to return when the value can't be read. Defaults to 0.0.

    CALLED BY:
        - ai.py:     check_functions_bk (the focus filters), _quality_bk, ai_sort_pool_bk, _defense_score.
        - routes.py: make_ai_pick_bk (sorting players by points per game in its fallback).

    RETURNS:
        float -- the number, or `default` for None, unreadable text, "nan" or "inf".
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        number = float(value)                    # already a number: just make it a float
    else:
        # strip $ , and a trailing % (so "45%" becomes 45.0, NOT 0.45)
        text = str(value).strip().replace('$', '').replace(',', '').rstrip('%')
        try:
            number = float(text)
        except ValueError:
            return default                       # junk such as 'Feb-00'
    # math.isfinite rejects nan / inf, which would break sorting
    return number if math.isfinite(number) else default


def bat_throw_code(value):
    """'Left' -> 'L', 'Right' -> 'R', 'Switch' -> 'S'.

    PURPOSE:
        Reduce a batting or throwing hand to a single uppercase letter so it can be compared.

    ARGUMENTS:
        value (str | None) -- like "Left", "R" or None.

    CALLED BY:
        - ai.py: check_functions_bb (the "lefty" focus check, code 13).

    RETURNS:
        str -- "L", "R", "S" (or whatever the first letter is), or "" if the value is empty.
    """
    if not value:
        return ''
    return value.strip()[0].upper()


# ============================================================
# Position eligibility
# Port of aipicks.py's eligiblePosition(). Reuses assign_picks_to_slots_bb's
# open-slot bookkeeping rather than duplicating it -- whatever slot came
# back None from that function is, by definition, still open.
# ============================================================

# Baseball slot label -> the OLD numeric position code used by the original program.
# (These are the standard baseball scorekeeping numbers: 2 = catcher, 3 = first base, 4 = second base,
# 5 = third base, 6 = shortstop, 7 = left field, 8 = center field, 9 = right field, 1 = pitcher.)
# 10 = UT and 11 = relief pitcher are this program's own additions.
# The codes are kept as TEXT ("2", not 2) because the rest of the code compares them as text.
SLOT_LABEL_TO_CODE_BB = {
    'C': '2', '1B': '3', '2B': '4', '3B': '5', 'SS': '6',
    'LF': '7', 'CF': '8', 'RF': '9', 'UT': '10', 'S': '1', 'R': '11',
}


def open_position_lottery(roster_slots, team_picks):
    """
    Old aipicks.py-style position codes for every roster slot still open,
    one entry per open slot (duplicates included -- a team missing two
    catchers gets '2' twice, which naturally weights the AI's random pick
    toward positions with more open slots, same as the original).

    PURPOSE:
        List the open slots of a baseball team as old-style numeric codes. Think of it as a hat with
        one ticket per open slot: a team missing 2 catchers and 1 shortstop has two "2" tickets and one
        "6" ticket, so drawing a ticket at random favors catcher.

    ARGUMENTS:
        roster_slots (list[str])  -- the team's slot labels (see the vocabulary at the top).
        team_picks   (list[dict]) -- this team's pick-log entries.

    CALLED BY:
        - ai.py: eligible_position_bb.

    RETURNS:
        list[str] -- one code per open slot, e.g. ['2', '2', '6', '10', '10', '1', '11'].
                     A slot with no code (like FLEX) is left out.
    """
    assigned = assign_picks_to_slots_bb(roster_slots, team_picks)
    lottery = []
    # zip pairs each assigned entry with its slot label; None means the slot is still empty
    for filled, label in zip(assigned, roster_slots):
        if filled is None:
            code = SLOT_LABEL_TO_CODE_BB.get(label)
            if code:
                lottery.append(code)
    return lottery


def eligible_position_bb(roster_slots, team_picks, ai_focus):
    """
    Port of aipicks.py's eligiblePosition(). Returns [primary_code, sp_open, rp_open] --
    primary_code is '0' if only pitching slots remain open.

    PURPOSE:
        Decide, for this one pick, which kind of player the team is "shopping for": one random
        non-pitching slot (the primary code), plus flags saying whether a starter and/or reliever
        slot is open. The later selection functions use these to filter the pool.

    ARGUMENTS:
        roster_slots (list[str])  -- the team's slot labels.
        team_picks   (list[dict]) -- this team's pick-log entries.
        ai_focus     (int)        -- the team's archetype number. Only 15 ("Up the Middle") matters
                                     here: it prefers C / 2B / SS / CF slots when any are open.

    CALLED BY:
        - ai.py: ai_select_bb (once per pick).

    RETURNS:
        list -- [primary_code, sp_flag, rp_flag]
                  primary_code (str): old-style numeric code of one randomly chosen open NON-pitching
                                      slot ('2'..'10'); '0' if only pitching slots remain.
                  sp_flag (int): 1 if a starting-pitcher slot is open, else 0.
                  rp_flag (int): 11 if a reliever slot is open, else 0.
    """
    lottery = open_position_lottery(roster_slots, team_picks)
    selected = ['0', 0, 0]

    # '1' = a starting-pitcher slot is open; '11' = a reliever slot is open.
    if '1' in lottery:
        selected[1] = 1
    if '11' in lottery:
        selected[2] = 11

    # Draw one ticket from the non-pitching ones.
    non_pitching = [c for c in lottery if c not in ('1', '11')]
    if non_pitching:
        primary = random.choice(non_pitching)
        if ai_focus == 15:  # "Up the Middle" -- bias toward C/2B/SS/CF
            up_middle = [c for c in non_pitching if c in ('2', '4', '6', '8')]
            if up_middle:
                primary = random.choice(up_middle)
        selected[0] = primary

    return selected


# ============================================================
# Selection engine
# Port of aipicks.py's check_functions dict, aiSelectSnippet(), and
# topFourGrabs(). Position-eligibility checks use the derived fields above
# instead of the missing DP1/DP2/DP3/Bat/Throw/Role fields.
# ============================================================

def natural_slot_bb(player):
    """The roster slot a player naturally fills. Same lookup the roster display uses.

    PURPOSE:
        Translate a baseball player's position code ("SS", "SP", "DH"...) into the roster slot label
        he naturally belongs in ("SS", "S", "UT"...). Anything unrecognised (DH included) becomes "UT".

    ARGUMENTS:
        player (dict) -- a player record (uses "short_pos").

    CALLED BY:
        - ai.py: fits_open_slots_bb, check_functions_bb (through at_slot), can_fill_bb, tier_group_bb,
                 and the CAP_RULES['bb'] rule (both its "natural" and "priority" functions).

    RETURNS:
        str -- "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "S" (starter), "R" (reliever) or "UT".
    """
    return SHORT_POS_TO_SLOT_BB.get(player.get('short_pos', ''), 'UT')


def open_slot_counts_bb(roster_slots, team_picks):
    """{slot label: number of still-open slots} for this team.

    PURPOSE:
        Count how many slots of each kind are still open (a tally version of the "hat" in
        open_position_lottery, but keyed by slot label instead of old numeric code).

    ARGUMENTS:
        roster_slots (list[str])  -- the team's slot labels.
        team_picks   (list[dict]) -- this team's pick-log entries.

    CALLED BY:
        - ai.py: ai_select_bb.

    RETURNS:
        Counter -- like {"C": 1, "UT": 3, "S": 2}. A label that is full simply isn't present.
    """
    assigned = assign_picks_to_slots_bb(roster_slots, team_picks)
    return Counter(label for filled, label in zip(assigned, roster_slots) if filled is None)


# The eight field positions. Used to tell "a position player" from a pitcher or a DH.
FIELD_POS_BB       = ('C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF')

# Variety rule for the UT slots: a team may use UT slots on at most this many EXTRA players at a position
# beyond its starters there. With 1, a team with one starting shortstop may carry at most one backup SS
# in UT (two SS total), so UT slots go to a mix of positions instead of five more shortstops.
UT_BACKUPS_PER_POS = 1    # raise to 2 to allow more backups at the same position


def hitter_pos_counts_bb(team_picks):
    """How many hitters this team already has at each natural position (starters + backups).

    PURPOSE:
        Tally a team's HITTERS by natural slot (pitchers excluded). The UT variety rule compares this
        count against the number of starting slots to decide whether another player at that
        position is allowed into a UT slot.

    ARGUMENTS:
        team_picks (list[dict]) -- this team's pick-log entries (uses each entry's "pos").

    CALLED BY:
        - ai.py: ai_select_bb.

    RETURNS:
        Counter -- like {"C": 2, "SS": 1, "UT": 1}. Counts the natural slot of every non-pitcher pick.
    """
    counts = Counter()
    for e in team_picks:
        slot = SHORT_POS_TO_SLOT_BB.get(e.get('pos', ''), 'UT')
        if slot not in ('S', 'R'):          # S and R are pitcher slots; skip them
            counts[slot] += 1
    return counts


def fits_open_slots_bb(player, open_counts, pos_counts=None, base_slots=None):
    """True if this player would land in an open slot he belongs in:
    his natural slot, UT (hitters only, with a backup-variety limit), or a FLEX slot.

    PURPOSE:
        The legality test for a baseball pick: "if this team drafted this player, would he fit an open
        slot?" Checked in this order: his natural slot, then UT (hitters only, and only if the variety
        rule allows another player at his position), then FLEX (anyone).

    ARGUMENTS:
        player      (dict)         -- the candidate.
        open_counts (Counter)      -- open slots by label (from open_slot_counts_bb).
        pos_counts  (Counter|None) -- the team's hitters by position (hitter_pos_counts_bb). Pass None
                                      to switch the variety rule OFF.
        base_slots  (Counter|None) -- the team's STARTING slot counts by label (Counter(roster_slots));
                                      needed whenever pos_counts is given.

    CALLED BY:
        - ai.py: ai_select_bb (building the hitter and pitcher pools in attempt(), and the last-resort
                 fallback, which passes only open_counts) and can_fill_bb.

    RETURNS:
        bool -- True if he fits an open slot.
    """
    natural = natural_slot_bb(player)
    if open_counts.get(natural):                       # 1) his own slot is open
        return True
    if player.get('kind') == 'hitter' and open_counts.get('UT'):    # 2) a UT slot is open (hitters only)
        if pos_counts is None:          # variety check switched off
            return True
        # starters = how many STARTING slots exist at his position (0 for a DH, who has no field slot)
        starters = base_slots.get(natural, 0) if natural in FIELD_POS_BB else 0
        # allowed while the team has fewer than (starters + backups) at that position already
        if pos_counts.get(natural, 0) < starters + UT_BACKUPS_PER_POS:
            return True
    return bool(open_counts.get('FLEX'))               # 3) a FLEX slot takes anybody


def check_functions_bb(def_check):
    """
    PURPOSE:
        Return a yes/no test function for a numeric check code. The same table serves two jobs:
        POSITION codes (which slot the AI is shopping for) and FOCUS codes (an archetype's special
        preference). Both are combined in ai_select_snippet_bb.

        Codes:
          0            no filter (anyone)
          1            starting pitcher (natural slot "S")
          2..9         catcher, 1B, 2B, 3B, SS, LF, CF, RF (the old scorekeeping numbers)
          10           UT: any hitter (the pool is already hitters-only, so no real filter)
          11           relief pitcher ("R")
          12           (focus) nothing: the old "position-player defense" rule has no field in this data
          13           (focus) left-handed: bats left OR throws left
          14           (focus) "up the middle": C, 2B, SS or CF

    ARGUMENTS:
        def_check (int) -- one of the codes above. Unknown codes mean "no filter".

    CALLED BY:
        - ai.py: ai_select_snippet_bb (twice: once for the position code, once for the focus code).

    RETURNS:
        function -- check(player_dict) -> bool.
    """
    def at_slot(label):
        # Build a test "is this player's natural slot == label?"
        return lambda p: natural_slot_bb(p) == label

    table = {
        0:  lambda p: True,
        1:  at_slot('S'),
        2:  at_slot('C'),
        3:  at_slot('1B'),
        4:  at_slot('2B'),
        5:  at_slot('3B'),
        6:  at_slot('SS'),
        7:  at_slot('LF'),
        8:  at_slot('CF'),
        9:  at_slot('RF'),
        10: lambda p: True,  # UT -- any hitter fits
        11: at_slot('R'),
        12: lambda p: True,  # old "position-player defense" check has no equivalent field -- no filter for now
        13: lambda p: bat_throw_code(p.get('Bats')) == 'L' or bat_throw_code(p.get('Throws')) == 'L',
        14: lambda p: natural_slot_bb(p) in ('C', '2B', 'SS', 'CF'),   # up the middle
    }
    # .get(code, default): an unknown code gets a "let everyone through" function
    return table.get(def_check, lambda p: True)


# Which KINDS of player each focus code may be applied to: 'P' = pitchers, 'H' = hitters.
# Focus 11 only makes sense for pitchers; 13 (lefty) for both; 14 (up the middle) for hitters.
# A focus code that isn't listed here (like 12) is ignored.
FOCUS_KINDS_BB = {11: 'P', 13: 'HP', 14: 'H'}


def ai_select_snippet_bb(playerpool, threshold, def_check, avg_salary, focus=0):
    """
    PURPOSE:
        Walk down a SORTED list of players and return the id of the one the dice picked. This is the
        piece that turns "best-first order" into "mostly the best, sometimes the next one."

        How `threshold` works: players that pass the position and focus filters are counted in order.
            threshold -1 -> the 1st match      (40% of the time, see top_four_grabs_bb)
            threshold  0 -> the 2nd match      (30%)
            threshold  1 -> the 3rd match      (20%)
            threshold  2 -> the 4th match      (10%)
        Players with a salary under $600 (this includes "no salary on file") are skipped.

    ARGUMENTS:
        playerpool (list[dict]) -- players already sorted best-first.
        threshold  (int)        -- -1, 0, 1 or 2 (see above).
        def_check  (int)        -- the position code to require (see check_functions_bb).
        avg_salary (float)      -- salary ceiling; always float('inf') (no ceiling) today.
        focus      (int)        -- optional archetype focus code (0 = none).

    CALLED BY:
        - ai.py: top_four_grabs_bb and ai_select_bb (the "best-paid who fits" fallback inside attempt()).

    RETURNS:
        str | None -- the chosen player's "id", or None if too few players pass the filters.
    """
    pos_check = check_functions_bb(def_check)
    focus_check = check_functions_bb(focus) if focus else (lambda p: True)
    counter = 0                                      # how many matches we've skipped so far
    for player in playerpool:
        if not (pos_check(player) and focus_check(player)):
            continue                                 # wrong position or doesn't fit the focus
        salary = parse_salary(player.get('s_sal'))
        if salary > avg_salary or salary < 600:
            continue                                 # too expensive (never, today) or no real salary
        if threshold < 0 or counter > threshold:
            return player.get('id')
        counter += 1
    return None


def top_four_grabs_bb(kind, playerpool, position, direction, avg_salary, focus=0):
    """
    PURPOSE:
        The weighted "top four" pick. Rolls the 40 / 30 / 20 / 10 dice, works out which position filter
        applies, then hands off to ai_select_snippet_bb.

        Which position filter is used:
          pitcher pool ('P'): a starter filter if direction is 1 and a starter slot is open; a
                              reliever filter if direction is 11 and a reliever slot is open;
                              otherwise no position filter.
          hitter pool ('H'):  the primary position code chosen by eligible_position_bb.

    ARGUMENTS:
        kind       (str)        -- 'P' (pitchers) or 'H' (hitters).
        playerpool (list[dict]) -- players sorted best-first.
        position   (list)       -- [primary_code, sp_flag, rp_flag] from eligible_position_bb.
        direction  (int)        -- for pitchers: 1 = looking for a starter, 11 = looking for a reliever.
        avg_salary (float)      -- salary ceiling (always infinity today).
        focus      (int)        -- the archetype's focus code (0 = none). Only applied when it makes
                                   sense for this kind (see FOCUS_KINDS_BB); if applying it finds
                                   nobody, it is dropped and the search repeats without it.

    CALLED BY:
        - ai.py: first_rounds_bb, auto_select_hitter_bb, auto_select_pitcher_bb.

    RETURNS:
        str | None -- the chosen player's "id", or None.
    """
    # ---- which position code do we require? ----
    if kind == 'P':
        if direction == 1 and position[1] == 1:
            def_check = 1                        # a starter, and a starter slot is open
        elif direction == 11 and position[2] == 11:
            def_check = 11                       # a reliever, and a reliever slot is open
        else:
            def_check = 0                        # no position filter
    else:
        def_check = int(position[0])             # '6' -> 6 (shortstop), '0' -> no filter

    # ---- the dice: 40% / 30% / 20% / 10% for 1st / 2nd / 3rd / 4th best ----
    roll = random.randrange(100)                 # 0..99
    threshold = -1 if roll < 40 else 0 if roll < 70 else 1 if roll < 90 else 2

    # only apply the focus if it makes sense for this kind of player
    use_focus = focus if kind in FOCUS_KINDS_BB.get(focus, '') else 0

    pick = ai_select_snippet_bb(playerpool, threshold, def_check, avg_salary, use_focus)
    if pick is None and use_focus:
        # the focus was too strict: try again without it
        pick = ai_select_snippet_bb(playerpool, threshold, def_check, avg_salary, 0)
    return pick


def ai_sort_pool_bb(stat_key, players):
    """Highest-better, except ERA/WHIP which sort ascending.

    PURPOSE:
        Put a pool of players in best-first order by one stat. For most stats higher is better; for ERA
        and WHIP lower is better, so those sort the other way.
        Heads-up: a player with NO value for the stat counts as 0, which is "best" for ERA / WHIP.
        Also, a stat value that isn't a plain number (like "Feb-00") raises an error here.

    ARGUMENTS:
        stat_key (str)        -- the data key to sort by, e.g. 'b_hr', 'p_earned_run_avg', 's_sal'.
        players  (list[dict]) -- the pool to sort.

    CALLED BY:
        - ai.py: first_rounds_bb, auto_select_hitter_bb, auto_select_pitcher_bb and ai_select_bb
                 (the "best-paid who fits" fallback inside attempt()).

    RETURNS:
        list[dict] -- a NEW list, best first. The input list is not changed.
    """
    ascending = stat_key in ('p_earned_run_avg', 'p_whip')
    if stat_key == 's_sal':
        # salary is text like "$11,150,000", so it has its own parser
        keyfunc = lambda r: parse_salary(r.get('s_sal'))
    else:
        keyfunc = lambda r: float(r.get(stat_key, 0) or 0)
    # reverse=True sorts biggest first, so ascending stats turn it off
    return sorted(players, key=keyfunc, reverse=not ascending)


# ============================================================
# Top-level: AIFocus archetypes and the aiSelect() equivalent
# ============================================================

# THE BASEBALL ARCHETYPE TABLE. Each AI team is assigned one number 1-16 when the draft is created.
#
#   'keys'  six data keys. keys[0:3] are used when the team shops on its MAIN side (see 'mode'), keys[3:6]
#           when it shops on the OTHER side. Within each group of three, the first key is used 70% of the
#           time, the second 20%, the third 10% (so an archetype mostly, not always, follows its
#           first stat). 's_sal' means "the highest-paid player".
#   'focus' an extra filter code (see check_functions_bb): 0 = none, 11 = relievers, 12 = (does
#           nothing today), 13 = lefties, 14 = up the middle.
#   'mode'  'H' = a hitter-first team, 'P' = a pitcher-first team.
#
# The short labels are descriptions of what each row's stats favor; rename them however you like.
AI_FOCUS_TABLE = {
    1:  {'keys': ['s_sal']*6, 'focus': 0, 'mode': 'H'},                                                                  # big spender: chases the highest salary
    2:  {'keys': ['b_hr','b_slugging_perc','b_rbi','s_sal','p_so','p_earned_run_avg'], 'focus': 0, 'mode': 'H'},         # power: HR / slugging / RBI, then strikeouts and low ERA
    3:  {'keys': ['s_sal','p_w','p_earned_run_avg','s_sal','b_onbase_perc','b_hr'], 'focus': 0, 'mode': 'P'},            # pitching first: salary, wins, low ERA
    4:  {'keys': ['b_batting_avg','b_sb','s_sal','s_sal','p_whip','p_earned_run_avg'], 'focus': 0, 'mode': 'H'},          # contact + speed: average and steals
    5:  {'keys': ['s_sal','b_h','b_batting_avg','s_sal','p_w','p_so'], 'focus': 12, 'mode': 'H'},                          # hit tool: hits and average (focus 12 does nothing today)
    6:  {'keys': ['s_sal','b_sb','b_batting_avg','s_sal','p_w','p_so'], 'focus': 12, 'mode': 'H'},                        # speed: steals and average (focus 12 does nothing today)
    7:  {'keys': ['s_sal','p_sv','p_earned_run_avg','s_sal','b_hr','b_rbi'], 'focus': 11, 'mode': 'P'},                    # bullpen: relievers, saves
    8:  {'keys': ['p_whip','p_earned_run_avg','s_sal','s_sal','b_batting_avg','b_rbi'], 'focus': 0, 'mode': 'P'},          # run prevention: low WHIP and ERA
    9:  {'keys': ['b_sb','b_onbase_perc','s_sal','s_sal','p_whip','p_w'], 'focus': 0, 'mode': 'H'},                        # table setters: steals and on-base
    10: {'keys': ['b_doubles','b_slugging_perc','b_triples','s_sal','p_so','p_whip'], 'focus': 0, 'mode': 'H'},           # gap power: doubles, triples, slugging
    11: {'keys': ['b_onbase_perc','b_batting_avg','s_sal','s_sal','p_whip','p_earned_run_avg'], 'focus': 0, 'mode': 'H'}, # on-base: OBP and average
    12: {'keys': ['p_so','p_whip','s_sal','s_sal','b_hr','b_slugging_perc'], 'focus': 0, 'mode': 'P'},                    # strikeout pitchers
    13: {'keys': ['s_sal','b_batting_avg','b_slugging_perc','s_sal','p_earned_run_avg','p_whip'], 'focus': 13, 'mode': 'H'},  # lefty lean: players who bat or throw left
    14: {'keys': ['s_sal','b_batting_avg','b_hr','s_sal','p_earned_run_avg','p_w'], 'focus': 0, 'mode': 'H'},             # balanced stars: salary, average, home runs
    15: {'keys': ['s_sal','b_batting_avg','b_hr','s_sal','p_earned_run_avg','p_w'], 'focus': 14, 'mode': 'H'},            # "Up the Middle": C / 2B / SS / CF (also biased in eligible_position_bb)
    16: {'keys': ['b_rbi','b_slugging_perc','s_sal','s_sal','p_whip','p_so'], 'focus': 0, 'mode': 'H'},                   # run producers: RBI and slugging
}


def first_rounds_bb(hitters_pool, pitchers_pool, avg_salary):
    """
    Port of aipicks.py's firstRounds() -- early-round 'best available',
    no position filter, 30% hitter / 70% pitcher split. Uses the real
    avg_salary passed in rather than the original's hardcoded $20,000,
    which was tuned to a much smaller salary scale than this data uses.

    PURPOSE:
        The EARLY-ROUND rule (rounds 1 and 2). Early on, teams just take the highest-paid player
        available: a hitter 30% of the time, a pitcher 70%. No position or archetype involved, so every
        team grabs stars first and builds the roster around them.

    ARGUMENTS:
        hitters_pool  (list[dict]) -- hitters this team may take (already legal and affordable).
        pitchers_pool (list[dict]) -- pitchers this team may take.
        avg_salary    (float)      -- salary ceiling (always infinity today).

    CALLED BY:
        - ai.py: auto_select_hitter_bb and auto_select_pitcher_bb.

    RETURNS:
        str | None -- the chosen player's "id", or None if that pool is empty.
    """
    no_position = ['0', 0, 0]          # "no position filter" in the same shape eligible_position_bb returns
    if random.randrange(100) < 30:
        pool = ai_sort_pool_bb('s_sal', hitters_pool)
        return top_four_grabs_bb('H', pool, no_position, 0, avg_salary)
    else:
        pool = ai_sort_pool_bb('s_sal', pitchers_pool)
        return top_four_grabs_bb('P', pool, no_position, 0, avg_salary)


def auto_select_hitter_bb(position, hitters_pool, pitchers_pool, round_num, focus, keys, avg_salary):
    """Port of aipicks.py's autoSelectHitter().

    PURPOSE:
        The pick for a HITTER-FIRST archetype (mode 'H'). It rolls a "side":
          - Rounds 1-2: 90% of picks go to first_rounds_bb (best available).
          - Later rounds: 50% shop for a hitter by the archetype's first three stats, 50% shop for a
            pitcher by its last three stats.
          - In rounds 1-2, the other 10% shop for a pitcher by the last three stats.
        When shopping for a pitcher, it looks for a starter 80% of the time (if a starter slot is
        open), otherwise a reliever.

    ARGUMENTS:
        position      (list)       -- [primary_code, sp_flag, rp_flag] from eligible_position_bb.
        hitters_pool  (list[dict]) -- legal, affordable hitters.
        pitchers_pool (list[dict]) -- legal, affordable pitchers.
        round_num     (int)        -- the current round (1 = first).
        focus         (int)        -- the archetype's focus code.
        keys          (list[str])  -- the archetype's six stat keys.
        avg_salary    (float)      -- salary ceiling (always infinity today).

    CALLED BY:
        - ai.py: ai_select_bb (inside attempt(), when the archetype's mode is 'H').

    RETURNS:
        str | None -- the chosen player's "id", or None.
    """
    side_threshold = 90 if round_num < 3 else 50     # chance (in %) to take the "main" path
    side = random.randrange(100)

    # rounds 1-2, main path: best available
    if side < side_threshold and round_num < 3:
        return first_rounds_bb(hitters_pool, pitchers_pool, avg_salary)

    # later rounds, main path: a hitter, sorted by one of the first three stats (70/20/10 weights)
    if side < side_threshold:
        key_str = random.choices(keys[0:3], weights=[70, 20, 10])[0]
        pool = ai_sort_pool_bb(key_str, hitters_pool)
        return top_four_grabs_bb('H', pool, position, 0, avg_salary, focus)

    # the other path: a pitcher, sorted by one of the last three stats
    key_str = random.choices(keys[3:6], weights=[70, 20, 10])[0]
    pool = ai_sort_pool_bb(key_str, pitchers_pool)
    # starter 80% of the time if a starter slot is open; otherwise (or 20%) a reliever
    direction = 1 if (random.randrange(100) < 80 and position[1] > 0) else 11
    return top_four_grabs_bb('P', pool, position, direction, avg_salary, focus)


def auto_select_pitcher_bb(position, hitters_pool, pitchers_pool, round_num, focus, keys, avg_salary):
    """Port of aipicks.py's autoSelectPitcher().

    PURPOSE:
        The pick for a PITCHER-FIRST archetype (mode 'P'). The mirror image of auto_select_hitter_bb:
        the main path shops for a pitcher by the first three stats, the other path for a hitter by the
        last three. Same round 1-2 rule (90% best available).
        A "bullpen" archetype (focus 11) always looks for a reliever.

    ARGUMENTS:
        position      (list)       -- [primary_code, sp_flag, rp_flag] from eligible_position_bb.
        hitters_pool  (list[dict]) -- legal, affordable hitters.
        pitchers_pool (list[dict]) -- legal, affordable pitchers.
        round_num     (int)        -- the current round (1 = first).
        focus         (int)        -- the archetype's focus code.
        keys          (list[str])  -- the archetype's six stat keys.
        avg_salary    (float)      -- salary ceiling (always infinity today).

    CALLED BY:
        - ai.py: ai_select_bb (inside attempt(), when the archetype's mode is 'P').

    RETURNS:
        str | None -- the chosen player's "id", or None.
    """
    side_threshold = 90 if round_num < 3 else 50
    side = random.randrange(100)

    if side < side_threshold and round_num < 3:
        return first_rounds_bb(hitters_pool, pitchers_pool, avg_salary)

    if side < side_threshold:
        # main path: a pitcher by one of the first three stats
        key_str = random.choices(keys[0:3], weights=[70, 20, 10])[0]
        pool = ai_sort_pool_bb(key_str, pitchers_pool)
        if random.randrange(100) < 80 and position[1] > 0:
            direction = 1             # a starter
        else:
            direction = 11            # a reliever
        if focus == 11:      # RP-heavy archetype: always lean reliever
            direction = 11
        return top_four_grabs_bb('P', pool, position, direction, avg_salary, focus)

    # other path: a hitter by one of the last three stats
    key_str = random.choices(keys[3:6], weights=[70, 20, 10])[0]
    pool = ai_sort_pool_bb(key_str, hitters_pool)
    return top_four_grabs_bb('H', pool, position, 0, avg_salary, focus)


def can_fill_bb(player, label, pos_counts, base_slots):
    """Berserker: can this player take an open slot of this kind?

    PURPOSE:
        Berserker mode's baseball eligibility test: "may this player fill an open slot labeled
        `label`?" FLEX takes anyone; UT takes a hitter the variety rule allows; any other label
        needs the player's natural slot to match exactly.

    ARGUMENTS:
        player     (dict)    -- the candidate.
        label      (str)     -- the open-slot label being filled ("C", "UT", "S", "FLEX"...).
        pos_counts (Counter) -- the team's hitters by position (hitter_pos_counts_bb).
        base_slots (Counter) -- the team's starting slot counts (Counter(roster_slots)).

    CALLED BY:
        - ai.py: ai_select_bb (wrapped in a lambda and handed to berserker_pick, in berserker.py).

    RETURNS:
        bool -- True if the player may take that kind of slot.
    """
    if label == 'FLEX':
        return True
    if label == 'UT':
        # reuse the normal rule by pretending ONLY a UT slot is open
        return fits_open_slots_bb(player, Counter({'UT': 1}), pos_counts, base_slots)
    return natural_slot_bb(player) == label


def ai_select_bb(team, roster_slots, team_picks, all_players, round_num, cap, salary_cap_enabled):
    """
    One baseball AI pick. Order of business: Berserker roll, tiered players, then the archetype's normal pick,
    with the salary cap, the UT variety rule and the L/R balance (s_bal) all narrowing the candidates.
    Returns a player id, or None.

    PURPOSE:
        THE baseball AI: decide who the given team drafts right now. Steps:
          1. Work out open slots, the team's hitter counts and its affordable players.
          2. Berserker roll (random pick) if the team has Berserker on.
          3. Tier 1 / tier 2 targeting.
          4. The archetype's normal pick (auto_select_hitter_bb / auto_select_pitcher_bb), with:
               - the UT VARIETY rule (limit backups at one position),
               - the L/R BALANCE rule (keep the team's hitters and pitchers roughly even between
                 lefty- and righty-strong, unless the team "leans" one way),
             relaxed in this order if nobody is found: balance first, then variety.
          5. Last resort: the cheapest player who fits an open slot.

    ARGUMENTS:
        team               (dict)       -- this team's entry in the meta file (team_id, AIFocus, Lean...).
        roster_slots       (list[str])  -- the team's slot labels (including any FLEX slots).
        team_picks         (list[dict]) -- this team's pick-log entries.
        all_players        (list[dict]) -- the WHOLE draft file (drafted and undrafted players).
        round_num          (int)        -- the current round, 1 = first.
        cap                (str|float)  -- the salary cap ("" or 0 when none).
        salary_cap_enabled (bool)       -- True when a cap is on.

    CALLED BY:
        - routes.py: make_ai_pick_bb (for AI teams, and for a human whose pick clock ran out).

    RETURNS:
        str | None -- the "id" of the player to draft, or None if nothing fits (routes.py then falls
                      back to the cheapest undrafted player).
    """
    ai_focus = team.get('AIFocus', 1)
    config = AI_FOCUS_TABLE.get(ai_focus, AI_FOCUS_TABLE[1])         # unknown focus -> archetype 1
    position = eligible_position_bb(roster_slots, team_picks, ai_focus)

    open_counts = open_slot_counts_bb(roster_slots, team_picks)       # what's still open
    pos_counts  = hitter_pos_counts_bb(team_picks)                    # for the UT variety rule
    base_slots  = Counter(roster_slots)                               # how many starting slots per label

    # ---- who can this team draft? ----
    undrafted = [p for p in all_players if p.get('team_id', 0) == 0]
    if salary_cap_enabled:
        # keep only players the team can take AND still finish its roster under the cap
        checker = make_cap_checker('bb', roster_slots, team_picks, all_players, team['team_id'], cap)
        affordable = [p for p in undrafted if checker.feasible(p)]
    else:
        affordable = undrafted
    avg_salary = float('inf')            # no salary ceiling (vestigial; see the top of the file)

    # Berserker: most of the time, a random player for a random open slot
    if is_berserker(team) and berserker_roll():
        pick = berserker_pick(affordable, list(open_counts.elements()),
                              lambda p, label: can_fill_bb(p, label, pos_counts, base_slots))
        if pick is not None:
            return pick

    # tiered players first (tier 1, then tier 2), as long as they fit an open slot
    pick = tier_pick(affordable, tier_group_bb, tier_open_groups_bb(open_counts))
    if pick is not None:
        return pick

    # ---- handedness balance setup ----
    # handedness balance: where this team's hitters and pitchers lean (L positive, R negative)
    mine  = [p for p in all_players if p.get('team_id', 0) == team['team_id']]     # this team's players so far
    net_h = sum(balance_lean(p) for p in mine if p.get('kind') == 'hitter')        # its hitters' total lean
    net_p = sum(balance_lean(p) for p in mine if p.get('kind') == 'pitcher')       # its pitchers' total lean
    lean  = team_lean_bb(team)                                                      # None, 'L' or 'R'
    respect_balance = random.random() < BAL_STRICTNESS     # 85% of picks follow the balance rule

    def attempt(variety, balanced):
        """
        PURPOSE:
            One try at an archetype pick, with the variety and balance rules switched on or off.

        ARGUMENTS:
            variety  (bool) -- True = enforce the UT variety rule.
            balanced (bool) -- True = enforce the L/R balance rule.

        CALLED BY:
            - ai.py: ai_select_bb (up to three times: with balance, without balance, then without
                     variety either).

        RETURNS:
            str | None -- a player id, or None if nobody qualified under those rules.
        """
        pc = pos_counts if variety else None          # None switches the variety rule off
        hitters_pool = [
            p for p in affordable
            if p.get('kind') == 'hitter' and fits_open_slots_bb(p, open_counts, pc, base_slots)
        ]
        pitchers_pool = [
            p for p in affordable
            if p.get('kind') == 'pitcher' and fits_open_slots_bb(p, open_counts, pc, base_slots)
        ]
        if balanced:
            hitters_pool  = balance_pool(hitters_pool, net_h, lean)
            pitchers_pool = balance_pool(pitchers_pool, net_p, lean)

        # the archetype's mode decides which "autoSelect" runs
        if config['mode'] == 'H':
            pick = auto_select_hitter_bb(position, hitters_pool, pitchers_pool, round_num, config['focus'], config['keys'], avg_salary)
        else:
            pick = auto_select_pitcher_bb(position, hitters_pool, pitchers_pool, round_num, config['focus'], config['keys'], avg_salary)

        # rolled side or slot had nobody: take the best-paid player who fits from either pool
        if pick is None:
            pool = ai_sort_pool_bb('s_sal', hitters_pool + pitchers_pool)
            pick = ai_select_snippet_bb(pool, -1, 0, avg_salary)
        return pick

    pick = attempt(True, respect_balance)
    if pick is None and respect_balance:
        pick = attempt(True, False)          # balance is the first rule to bend
    if pick is None:
        pick = attempt(False, False)         # then the UT variety rule

    # last resort (a team that can no longer make the cap): the cheapest player who fits an open slot
    if pick is None:
        fits = [p for p in undrafted if fits_open_slots_bb(p, open_counts)]
        # sort key: players with no salary go LAST, then cheapest first, then random for ties
        fits.sort(key=lambda p: (salary_of(p) <= 0, salary_of(p), random.random()))
        pick = fits[0].get('id') if fits else None

    return pick


# ============================================================
# BASKETBALL
# ============================================================
# Basketball is simpler than baseball: one pool (players, plus separate "defense units"), slots C / F / G /
# UT / Def, and no handedness balance.

def open_position_lottery_bk(roster_slots, team_picks):
    """Open slot labels for this team, one entry per open slot (duplicates included).

    PURPOSE:
        List the basketball team's open slots as labels ("C", "F", "G", "UT", "Def"), one per open slot.
        Slots that are open more times come up more often when one is drawn at random.

    ARGUMENTS:
        roster_slots (list[str])  -- the team's slot labels.
        team_picks   (list[dict]) -- this team's pick-log entries.

    CALLED BY:
        - ai.py:     eligible_position_bk, and ai_select_bk (Berserker and tier targeting).
        - routes.py: make_ai_pick_bk (its fallback checks whether only the Def slot is left).

    RETURNS:
        list[str] -- like ['C', 'F', 'UT', 'UT', 'Def'].
    """
    assigned = assign_picks_to_slots_bk(roster_slots, team_picks)
    return [label for filled, label in zip(assigned, roster_slots) if filled is None]


def eligible_position_bk(roster_slots, team_picks):
    """Returns a random open slot label ('C'/'F'/'G'/'UT'), or None if the roster is full.

    PURPOSE:
        Pick which open slot the team is shopping for right now (it can also be 'Def' when that's the
        slot chosen). Slots open in larger numbers are chosen more often.

    ARGUMENTS:
        roster_slots (list[str])  -- the team's slot labels.
        team_picks   (list[dict]) -- this team's pick-log entries.

    CALLED BY:
        - ai.py: ai_select_bk.

    RETURNS:
        str | None -- an open slot label, or None if every slot is full.
    """
    open_labels = open_position_lottery_bk(roster_slots, team_picks)
    if not open_labels:
        return None
    return random.choice(open_labels)


def _is_def(p):
    """
    PURPOSE:
        Say whether a record is a basketball DEFENSE UNIT (as opposed to a player).

    ARGUMENTS:
        p (dict) -- a pool record.

    CALLED BY:
        - ai.py: check_functions_bk (the 0, 'UT' and 'Def' checks), can_fill_bk, ai_select_bk (several
                 places), tier_group_bk and the CAP_RULES['bk'] rule... (CAP_RULES tests kind directly).

    RETURNS:
        bool -- True if the record's kind is "defense".
    """
    return p.get('kind') == 'defense'


def check_functions_bk(code):
    """
    PURPOSE:
        Return a yes/no test function for a basketball check code, the same idea as
        check_functions_bb. The codes:
          0       anyone who is NOT a defense unit
          'C'     Pos is C           'F'  Pos is F          'G'  Pos is G
          'UT'    any non-defense player (UT takes anybody)
          'Def'   a defense unit
          11      (focus) shooters:  Omade rating above 10
          12      (focus) defenders: Dsteal above 8, or has a Block rating
          13      (focus) three-point shooters: fg3_pct of .350 or better
          14      (focus) rebounders: 6 or more rebounds per game

    ARGUMENTS:
        code (int | str) -- one of the codes above. An unknown code lets everyone through.

    CALLED BY:
        - ai.py: combined_check_bk (position check and focus check) and ai_select_bk (the last-resort
                 fallback: "players who fit this slot").

    RETURNS:
        function -- check(player_dict) -> bool.
    """
    table = {
        0:     lambda p: not _is_def(p),
        'C':   lambda p: p.get('Pos') == 'C',
        'F':   lambda p: p.get('Pos') == 'F',
        'G':   lambda p: p.get('Pos') == 'G',
        'UT':  lambda p: not _is_def(p),
        'Def': _is_def,
        11:    lambda p: to_float(p.get('Omade')) > 10,
        12:    lambda p: to_float(p.get('Dsteal')) > 8 or p.get('Block') not in (None, ''),
        13:    lambda p: to_float(p.get('fg3_pct')) >= 0.35,
        14:    lambda p: to_float(p.get('rbspgm')) >= 6,
    }
    return table.get(code, lambda p: True)


def combined_check_bk(position_code, focus_code):
    """Position AND focus both have to pass.

    PURPOSE:
        Build ONE test that requires BOTH the slot's position check and the archetype's focus check.

    ARGUMENTS:
        position_code (int | str) -- the slot being filled (see check_functions_bk).
        focus_code    (int)       -- the archetype's focus code; 0 means no focus filter.

    CALLED BY:
        - ai.py: ai_select_snippet_bk.

    RETURNS:
        function -- check(player_dict) -> bool, True only if both checks pass.
    """
    pos_fn   = check_functions_bk(position_code)
    focus_fn = check_functions_bk(focus_code) if focus_code else (lambda p: True)
    return lambda p: pos_fn(p) and focus_fn(p)


def ai_select_snippet_bk(playerpool, threshold, position_code, focus_code, avg_salary):
    """
    PURPOSE:
        The basketball version of ai_select_snippet_bb: walk down a best-first list and return the
        1st, 2nd, 3rd or 4th player who passes the filters (threshold -1, 0, 1, 2).
        Unlike baseball, there is no "$600 minimum" rule, and the salary ceiling is only checked when
        it isn't infinity.

    ARGUMENTS:
        playerpool    (list[dict]) -- players sorted best-first.
        threshold     (int)        -- -1, 0, 1 or 2 (which match to take).
        position_code (int | str)  -- the slot being filled (see check_functions_bk).
        focus_code    (int)        -- the archetype's focus code (0 = none).
        avg_salary    (float)      -- salary ceiling (always infinity today, which switches the check off).

    CALLED BY:
        - ai.py: top_four_grabs_bk.

    RETURNS:
        str | None -- the chosen player's "id", or None if too few pass.
    """
    check = combined_check_bk(position_code, focus_code)
    counter = 0
    for player in playerpool:
        if not check(player):
            continue
        # salary only matters when there's a budget to stay under
        if avg_salary != float('inf') and parse_salary(player.get('Salary')) > avg_salary:
            continue
        if threshold < 0 or counter > threshold:
            return player.get('id')
        counter += 1
    return None


def top_four_grabs_bk(playerpool, position_code, focus_code, avg_salary):
    """
    PURPOSE:
        The basketball "top four" pick: roll the 40 / 30 / 20 / 10 dice (1st, 2nd, 3rd or 4th best
        match) and hand off to ai_select_snippet_bk.

    ARGUMENTS:
        playerpool    (list[dict]) -- players sorted best-first.
        position_code (int | str)  -- the slot being filled.
        focus_code    (int)        -- the archetype's focus code (0 = none).
        avg_salary    (float)      -- salary ceiling (always infinity today).

    CALLED BY:
        - ai.py: auto_select_bk and ai_select_bk (the defense-unit branch).

    RETURNS:
        str | None -- the chosen player's "id", or None.
    """
    roll = random.randrange(100)       # 0..99
    threshold = -1 if roll < 40 else 0 if roll < 70 else 1 if roll < 90 else 2
    return ai_select_snippet_bk(playerpool, threshold, position_code, focus_code, avg_salary)


def _quality_bk(p):
    """Rough overall rating from the real stats. Used when the chosen stat has no data.

    PURPOSE:
        A simple "how good is this player" number: points + rebounds + assists per game. Used to order
        a pool when the stat we wanted to sort by is missing for everyone.

    ARGUMENTS:
        p (dict) -- a basketball player.

    CALLED BY:
        - ai.py: ai_sort_pool_bk.

    RETURNS:
        float -- ptspgm + rbspgm + astpgm (missing values count as 0).
    """
    return to_float(p.get('ptspgm')) + to_float(p.get('rbspgm')) + to_float(p.get('astpgm'))


def ai_sort_pool_bk(stat_key, players):
    """Higher is better. If nobody has real data for this stat (e.g. Salary missing from the JSON),
    fall back to an overall rating so the order isn't just alphabetical.
    Ties are broken randomly, never alphabetically.

    PURPOSE:
        Put a basketball pool in best-first order by one stat (higher is always better here).
        If every player has the same value for it (typically: the stat is missing from the data),
        sort by _quality_bk instead so the order is still sensible. Ties get a random order.

    ARGUMENTS:
        stat_key (str)        -- the data key to sort by, e.g. 'ptspgm', 'Salary', 'Omade'.
        players  (list[dict]) -- the pool to sort.

    CALLED BY:
        - ai.py: auto_select_bk.

    RETURNS:
        list[dict] -- a NEW list, best first.
    """
    values = [to_float(p.get(stat_key)) for p in players]
    if not values or max(values) == min(values):
        key = _quality_bk                                  # no real differences: use the overall rating
    else:
        key = lambda p: to_float(p.get(stat_key))
    # -key(p) sorts biggest first; random.random() breaks ties randomly
    return sorted(players, key=lambda p: (-key(p), random.random()))


# THE BASKETBALL ARCHETYPE TABLE (same idea as AI_FOCUS_TABLE, minus 'mode', since there is only one pool).
#   'keys'  six data keys; keys[0:3] or keys[3:6] is chosen 50/50, then within it the first key is used
#           70% of the time, the second 20%, the third 10%. 'Salary' = the highest-paid.
#   'focus' an extra filter: 0 none, 11 shooters (Omade), 12 defenders (Dsteal / Block),
#           13 three-point shooters, 14 rebounders (see check_functions_bk).
# Labels are descriptions of what each row favors; rename as you like.
AI_FOCUS_TABLE_BK = {
    1:  {'keys': ['Salary']*6, 'focus': 0},                                                    # big spender
    2:  {'keys': ['Omade','fg3_pct','PassDazz','Salary','ptspgm','Shoot'], 'focus': 0},        # outside scoring and flash
    3:  {'keys': ['Salary','rbspgm','Shoot','Salary','fg_pct','Omade'], 'focus': 0},           # rebounding and efficiency
    4:  {'keys': ['fg3_pct','rbspgm','Salary','Salary','DPass1','PassDazz'], 'focus': 0},      # three-point shooting
    5:  {'keys': ['Salary','astpgm','fg_pct','Salary','DPass1','rbspgm'], 'focus': 12},        # playmakers + defenders
    6:  {'keys': ['Salary','astpgm','fg_pct','Salary','DPass1','rbspgm'], 'focus': 12},        # playmakers + defenders (same stats as 5)
    7:  {'keys': ['Salary','Imade','Shoot','Salary','Omade','astpgm'], 'focus': 11},           # shooters (Omade above 10)
    8:  {'keys': ['ptspgm','DPass1','Salary','Salary','fg_pct','astpgm'], 'focus': 0},         # scorers
    9:  {'keys': ['Imade','astpgm','ptspgm','Salary','PassDazz','ptspgm'], 'focus': 0},        # inside game and passing
    10: {'keys': ['astpgm','fg3_pct','Imade','Salary','ptspgm','DPass1'], 'focus': 0},         # assists first
    11: {'keys': ['ptspgm','fg3_pct','Salary','Salary','PassDazz','Shoot'], 'focus': 0},       # scorers and shooters
    12: {'keys': ['ptspgm','DPass1','Salary','Salary','Omade','astpgm'], 'focus': 0},          # scorers
    13: {'keys': ['Salary','rbspgm','fg3_pct','Salary','Shoot','DPass1'], 'focus': 13},        # three-point shooters
    14: {'keys': ['Salary','Omade','ptspgm','Salary','Shoot','PassDazz'], 'focus': 0},         # balanced stars
    15: {'keys': ['Salary','Omade','ptspgm','Salary','Shoot','PassDazz'], 'focus': 14},        # rebounders (6+ per game)
    16: {'keys': ['PassDazz','fg3_pct','Salary','Salary','DPass1','ptspgm'], 'focus': 0},      # flashy passers and shooters
}


def auto_select_bk(position_code, pool, focus_code, keys, avg_salary):
    """Single-pool version of autoSelectHitter -- the side-roll picks between
    two stat triplets purely for variety, since there's only one pool either way.

    PURPOSE:
        Pick a basketball player for one open slot: choose a stat from the archetype's keys, sort the
        pool by it (best first), and take one of the top four with the 40/30/20/10 weights.

    ARGUMENTS:
        position_code (int | str)  -- the slot being filled ('C', 'F', 'G', 'UT', ...).
        pool          (list[dict]) -- affordable non-defense players.
        focus_code    (int)        -- the archetype's focus code (0 = none).
        keys          (list[str])  -- the archetype's six stat keys.
        avg_salary    (float)      -- salary ceiling (always infinity today).

    CALLED BY:
        - ai.py: ai_select_bk (up to three times: with the focus, without it, then "best scorer").

    RETURNS:
        str | None -- the chosen player's "id", or None if nobody qualified.
    """
    side = random.randrange(100)
    triplet = keys[0:3] if side < 50 else keys[3:6]            # 50/50 which group of three stats
    key_str = random.choices(triplet, weights=[70, 20, 10])[0]  # 70% first stat, 20% second, 10% third
    sorted_pool = ai_sort_pool_bk(key_str, pool)
    return top_four_grabs_bk(sorted_pool, position_code, focus_code, avg_salary)


def _defense_score(p):
    """Sort key (ascending): priciest defense first, then the fewest opponent makes.

    PURPOSE:
        Rank defense units: the most expensive first, and among equal prices the one that lets opponents
        make the fewest shots (the sum of its Omade / Pmade / Imade / Fmade / 3made values).

    ARGUMENTS:
        p (dict) -- a defense-unit record.

    CALLED BY:
        - ai.py: ai_select_bk (as the sort key when the slot being filled is the defense).

    RETURNS:
        tuple -- (negative salary, opponent makes). Python sorts a smaller tuple first, so the negative
                 salary puts the priciest defense at the front.
    """
    made = sum(to_float(p.get(k)) for k in ('Omade', 'Pmade', 'Imade', 'Fmade', '3made'))
    return (-parse_salary(p.get('Salary')), made)


def can_fill_bk(player, label):
    """Berserker: can this player take an open slot of this kind?

    PURPOSE:
        Berserker mode's basketball eligibility test. A defense unit may only fill "Def"; a player
        may fill "UT" or the slot that matches his Pos (C / F / G), never "Def".

    ARGUMENTS:
        player (dict) -- the candidate.
        label  (str)  -- the open-slot label ("C", "F", "G", "UT" or "Def").

    CALLED BY:
        - ai.py: ai_select_bk (passed straight to berserker_pick, in berserker.py).

    RETURNS:
        bool -- True if the player may take that kind of slot.
    """
    if label == 'Def':
        return _is_def(player)
    if _is_def(player):
        return False
    return label == 'UT' or player.get('Pos') == label


def ai_select_bk(team, roster_slots, team_picks, all_players, round_num, cap, salary_cap_enabled):
    """Port of aiSelect() for basketball -- one team's single pick.

    PURPOSE:
        THE basketball AI: decide who the team drafts right now. Steps:
          1. Choose a random open slot to shop for (None = roster full).
          2. Build the affordable list (cap check).
          3. Berserker roll.
          4. Tier targeting.
          5. If the slot is the defense, choose among defense units (priciest first, weighted).
          6. Otherwise choose a player by the archetype's stats for that slot; if the focus filter
             finds nobody, drop it; then "best scorer"; then the cheapest legal player.

    ARGUMENTS:
        team               (dict)       -- this team's entry in the meta file.
        roster_slots       (list[str])  -- the team's slot labels.
        team_picks         (list[dict]) -- this team's pick-log entries.
        all_players        (list[dict]) -- the whole draft file.
        round_num          (int)        -- the current round (not used by basketball, kept so all three
                                           sports are called the same way).
        cap                (str|float)  -- the salary cap.
        salary_cap_enabled (bool)       -- True when a cap is on.

    CALLED BY:
        - routes.py: make_ai_pick_bk.

    RETURNS:
        str | None -- the "id" of the player or defense unit to draft, or None if the roster is full or
                      nothing fits (routes.py then runs its own fallback).
    """
    ai_focus = team.get('AIFocus', 1)
    config = AI_FOCUS_TABLE_BK.get(ai_focus, AI_FOCUS_TABLE_BK[1])
    position_code = eligible_position_bk(roster_slots, team_picks)
    if position_code is None:
        return None  # roster already full

    undrafted = [p for p in all_players if p.get('team_id', 0) == 0]
    if salary_cap_enabled:
        checker = make_cap_checker('bk', roster_slots, team_picks, all_players, team['team_id'], cap)
        affordable = [p for p in undrafted if checker.feasible(p)]
    else:
        affordable = undrafted
    avg_salary = float('inf')

    # Berserker: most of the time, a random player for a random open slot
    if is_berserker(team) and berserker_roll():
        pick = berserker_pick(affordable, open_position_lottery_bk(roster_slots, team_picks), can_fill_bk)
        if pick is not None:
            return pick

    # tiered players first (tier 1, then tier 2), as long as they fit an open slot
    pick = tier_pick(affordable, tier_group_bk, Counter(open_position_lottery_bk(roster_slots, team_picks)))
    if pick is not None:
        return pick

    def cheapest(candidates):
        """
        PURPOSE:
            Find the cheapest player in a group (players with no salary are treated as last choice).

        ARGUMENTS:
            candidates (iterable[dict]) -- players or defense units to choose from.

        CALLED BY:
            - ai.py: ai_select_bk itself (the defense fallback and the last-resort fallback).

        RETURNS:
            str | None -- the cheapest candidate's "id", or None if there are no candidates.
        """
        candidates = sorted(candidates, key=lambda p: (salary_of(p) <= 0, salary_of(p), random.random()))
        return candidates[0].get('id') if candidates else None

    # the slot this team is filling is the defense: choose among the defense units
    if position_code == 'Def':
        defenses = sorted((p for p in affordable if _is_def(p)), key=_defense_score)
        pick = top_four_grabs_bk(defenses, 'Def', 0, avg_salary)
        if pick is None:
            pick = cheapest(p for p in undrafted if _is_def(p))
        return pick

    # a player slot: choose among affordable NON-defense players
    pool = [p for p in affordable if not _is_def(p)]
    pick = auto_select_bk(position_code, pool, config['focus'], config['keys'], avg_salary)

    # the archetype's focus filter found nobody: drop it and keep the position
    if pick is None:
        pick = auto_select_bk(position_code, pool, 0, config['keys'], avg_salary)

    # still nobody: best scorer available
    if pick is None:
        pick = auto_select_bk('UT', pool, 0, ['ptspgm'] * 6, avg_salary)

    # last resort (a team that can no longer make the cap): the cheapest player for the open slot
    if pick is None:
        fits = check_functions_bk(position_code)
        pick = cheapest(p for p in undrafted if not _is_def(p) and fits(p))
        if pick is None:
            pick = cheapest(p for p in undrafted if not _is_def(p))

    return pick

# ============================================================
# FOOTBALL
# ============================================================
# Football picks by POOL first: each open slot belongs to one kind of record (passers fill QB, rushers fill
# HB / FB, receivers fill TE / WR, defense units fill Def, special-teams units fill Special).

# Roster slot label -> the "kind" of record that can fill it.
SLOT_TO_POOL_FB = {
    'QB': 'passer',
    'HB': 'rusher', 'FB': 'rusher',
    'TE': 'receiver', 'WR': 'receiver',
    'Def': 'dlineoline',
    'Special': 'special',
}


def open_position_lottery_fb(roster_slots, team_picks):
    """Open slot labels for this team, one entry per open slot (duplicates included).

    PURPOSE:
        List the football team's open slots as labels ("QB", "HB", "WR", "Def", "FLEX"...), one per
        open slot.

    ARGUMENTS:
        roster_slots (list[str])  -- the team's slot labels (including any FLEX slots).
        team_picks   (list[dict]) -- this team's pick-log entries.

    CALLED BY:
        - ai.py: eligible_position_fb, and ai_select_fb (Berserker, tiers and the fallbacks).

    RETURNS:
        list[str] -- like ['QB', 'WR', 'WR', 'Def', 'Special'].
    """
    assigned = assign_picks_to_slots_fb(roster_slots, team_picks)
    return [label for filled, label in zip(assigned, roster_slots) if filled is None]


def eligible_position_fb(roster_slots, team_picks):
    """Returns (slot_label, pool_name) for a randomly chosen open slot, or (None, None) if full.
    A FLEX slot (from a two-way player) is only used when it's the last one open.

    PURPOSE:
        Pick which open slot the team shops for right now, and which kind of record fills it.

    ARGUMENTS:
        roster_slots (list[str])  -- the team's slot labels.
        team_picks   (list[dict]) -- this team's pick-log entries.

    CALLED BY:
        - ai.py: ai_select_fb.

    RETURNS:
        tuple (slot_label, pool_name):
            slot_label (str|None) -- like "WR" ("FLEX" if only FLEX slots are left).
            pool_name  (str|None) -- "passer", "rusher", "receiver", "dlineoline" or "special";
                                     for FLEX, a random one of passer / rusher / receiver.
        (None, None) means the roster is full.
    """
    open_labels = open_position_lottery_fb(roster_slots, team_picks)
    if not open_labels:
        return None, None
    regular = [label for label in open_labels if label != 'FLEX']
    if regular:
        slot_label = random.choice(regular)
        return slot_label, SLOT_TO_POOL_FB.get(slot_label)
    # only FLEX slots remain
    return 'FLEX', random.choice(['passer', 'rusher', 'receiver'])


# Football stats where a LOWER number is better (they're yards or rating a defense allows).
# Every other stat sorts higher-is-better.
FB_ASCENDING_STATS = {'s_Run', 's_Pass', 's_YdspPlay'}  # lower is better


def ai_sort_pool_fb(stat_key, players):
    """
    PURPOSE:
        Put a football pool in best-first order by one stat (higher first, except the stats in
        FB_ASCENDING_STATS, which go lowest first). Handles salary text and values written with a
        trailing "%".

    ARGUMENTS:
        stat_key (str)        -- the data key to sort by, e.g. 'PassYards', 's_QBRat', 'Salary'.
        players  (list[dict]) -- the pool to sort.

    CALLED BY:
        - ai.py: auto_select_fb and ai_select_fb (the "best-paid who fits" fallback).

    RETURNS:
        list[dict] -- a NEW list, best first.
    """
    def keyfunc(r):
        """
        PURPOSE:
            Turn one player's stat into a sortable number.

        CALLED BY:
            - ai.py: ai_sort_pool_fb (as the sort key).

        RETURNS:
            float -- the stat as a number (salary text parsed; "45%" read as 45.0; a "%" value that
                     can't be read counts as 0.0).
        """
        if stat_key == 'Salary':
            return parse_salary(r.get('Salary'))
        raw = r.get(stat_key, 0)
        if isinstance(raw, str) and raw.strip().endswith('%'):
            try:
                return float(raw.strip().rstrip('%'))
            except ValueError:
                return 0.0
        return float(raw or 0)       # any other non-number text raises an error here

    ascending = stat_key in FB_ASCENDING_STATS
    return sorted(players, key=keyfunc, reverse=not ascending)


def ai_select_snippet_fb(playerpool, threshold, avg_salary):
    """No position filter needed -- the pool passed in is already position-locked by kind.

    PURPOSE:
        The football version of ai_select_snippet_bb: walk down a best-first list and return the 1st,
        2nd, 3rd or 4th player (threshold -1, 0, 1, 2). Players with a salary under $600 (including "no
        salary on file") are skipped.

    ARGUMENTS:
        playerpool (list[dict]) -- players sorted best-first.
        threshold  (int)        -- -1, 0, 1 or 2 (which match to take).
        avg_salary (float)      -- salary ceiling (always infinity today).

    CALLED BY:
        - ai.py: top_four_grabs_fb and ai_select_fb (the "best-paid who fits" fallback, which passes -1).

    RETURNS:
        str | None -- the chosen player's "id", or None if too few qualify.
    """
    counter = 0
    for player in playerpool:
        salary = parse_salary(player.get('Salary'))
        if salary > avg_salary or salary < 600:
            continue
        if threshold < 0 or counter > threshold:
            return player.get('id')
        counter += 1
    return None


def top_four_grabs_fb(playerpool, avg_salary):
    """
    PURPOSE:
        The football "top four" pick: roll the 40 / 30 / 20 / 10 dice and hand off to
        ai_select_snippet_fb.

    ARGUMENTS:
        playerpool (list[dict]) -- players sorted best-first.
        avg_salary (float)      -- salary ceiling (always infinity today).

    CALLED BY:
        - ai.py: auto_select_fb.

    RETURNS:
        str | None -- the chosen player's "id", or None.
    """
    roll = random.randrange(100)
    threshold = -1 if roll < 40 else 0 if roll < 70 else 1 if roll < 90 else 2
    return ai_select_snippet_fb(playerpool, threshold, avg_salary)


def auto_select_fb(slot_label, pool_name, all_players, stat_key, avg_salary):
    """
    PURPOSE:
        Pick a football player for one open slot: collect the undrafted records of the right kind that
        fit the slot, sort them by the archetype's stat for that kind, and take one of the top four
        with the 40/30/20/10 weights.

    ARGUMENTS:
        slot_label (str)        -- the slot being filled ("QB", "WR", "Def"...).
        pool_name  (str)        -- the kind of record that fills it ("passer", "receiver"...).
        all_players (list[dict]) -- the candidates, normally the AFFORDABLE list. This function ALSO
                                    filters again for undrafted and for fitting the slot.
        stat_key   (str)        -- the stat to sort by (from the archetype table).
        avg_salary (float)      -- salary ceiling (always infinity today).

    CALLED BY:
        - ai.py: ai_select_fb.

    RETURNS:
        str | None -- the chosen player's "id", or None if nobody qualifies.
    """
    pool = [
        p for p in all_players
        if p.get('kind') == pool_name and p.get('team_id', 0) == 0 and fits_slot_fb(p, slot_label)
    ]
    sorted_pool = ai_sort_pool_fb(stat_key, pool)
    return top_four_grabs_fb(sorted_pool, avg_salary)


# Each archetype picks ONE preferred stat per pool -- no roll needed, since
# eligible_position_fb already determined the pool from the open roster slot.
#
# Columns: the data key to sort by for each kind of record.
#   passer      quarterbacks            rusher      halfbacks and fullbacks
#   receiver    TEs and WRs             dlineoline  defense / offensive-line units
#   special     special-teams units
# 'Salary' = the highest-paid. Stats starting "s_" are Strat-O-Matic ratings (for 's_Run', 's_Pass' and
# 's_YdspPlay' LOWER is better, see FB_ASCENDING_STATS).
AI_FOCUS_TABLE_FB = {
    1:  {'passer': 'Salary',     'rusher': 'Salary',     'receiver': 'Salary',   'dlineoline': 'Salary',   'special': 'Salary'},
    2:  {'passer': 'PassYards',  'rusher': 'RushYards',  'receiver': 'RecYards', 'dlineoline': 's_OLRun',  'special': 's_KO_Avg'},
    3:  {'passer': 's_QBRat',    'rusher': 'RushYards',  'receiver': 'RecYards', 'dlineoline': 's_OLPass', 'special': 's_P_Avg'},
    4:  {'passer': 'CompPct',    'rusher': 'RushAvg',    'receiver': 's_YpRec',  'dlineoline': 's_OLRun',  'special': 's_PR_Avg'},
    5:  {'passer': 'PassTDs',    'rusher': 'RushTDs',    'receiver': 'RecTDs',   'dlineoline': 's_OLPass', 'special': 's_KickCoverage'},
    6:  {'passer': 'CompPct',    'rusher': 'RushYards',  'receiver': 'RecYards', 'dlineoline': 's_Pass',   'special': 's_PuntCoverage'},
    7:  {'passer': 'Salary',     'rusher': 'Salary',     'receiver': 'Salary',   'dlineoline': 'Salary',   'special': 's_KO_TD'},
    8:  {'passer': 's_YpA',      'rusher': 's_YpRush',   'receiver': 's_YpRec',  'dlineoline': 's_YdspPlay','special': 's_P_Avg'},
    9:  {'passer': 'CompPct',    'rusher': 'RushAvg',    'receiver': 's_YpRec',  'dlineoline': 's_YdspPlay','special': 's_KO_Avg'},
    10: {'passer': 'PassYards',  'rusher': 'RushYards',  'receiver': 'RecYards', 'dlineoline': 's_OLPass', 'special': 's_PR_Avg'},
    11: {'passer': 'CompPct',    'rusher': 'RushYards',  'receiver': 'Receptions','dlineoline': 's_OLRun', 'special': 's_P_Avg'},
    12: {'passer': 'PassTDs',    'rusher': 'RushYards',  'receiver': 'RecYards', 'dlineoline': 's_OLPass', 'special': 's_KO_TD'},
    13: {'passer': 's_QBRat',    'rusher': 'RushYards',  'receiver': 'RecYards', 'dlineoline': 's_OLRun',  'special': 's_P_Avg'},
    14: {'passer': 'Salary',     'rusher': 'RushYards',  'receiver': 'RecYards', 'dlineoline': 'Salary',   'special': 'Salary'},
    15: {'passer': 'Salary',     'rusher': 'RushYards',  'receiver': 'RecYards', 'dlineoline': 's_OLRun',  'special': 's_KO_Avg'},
    16: {'passer': 'PassTDs',    'rusher': 'RushTDs',    'receiver': 'RecTDs',   'dlineoline': 's_OLPass', 'special': 's_PR_TD'},
}


def can_fill_fb(player, label):
    """Berserker: can this player take an open slot of this kind?

    PURPOSE:
        Berserker mode's football eligibility test. FLEX takes a passer, rusher or receiver (never a
        unit); any other label needs the player to fit it exactly (strict, so HB and FB do NOT swap).

    ARGUMENTS:
        player (dict) -- the candidate.
        label  (str)  -- the open-slot label ("QB", "HB", "WR", "Def", "FLEX"...).

    CALLED BY:
        - ai.py: ai_select_fb (passed straight to berserker_pick, in berserker.py).

    RETURNS:
        bool -- True if the player may take that kind of slot.
    """
    if label == 'FLEX':
        return player.get('kind') in ('passer', 'rusher', 'receiver')
    return fits_slot_fb(player, label, strict=True)


def ai_select_fb(team, roster_slots, team_picks, all_players, round_num, cap, salary_cap_enabled):
    """Port of aiSelect() for football -- one team's single pick.

    PURPOSE:
        THE football AI: decide who the team drafts right now. Steps:
          1. Choose a random open slot (and its kind of record) to shop for; stop if the roster is full.
          2. Build the affordable list (cap check).
          3. Berserker roll.
          4. Tier targeting.
          5. The archetype's stat for that kind, via auto_select_fb.
          6. Fallbacks: the best-paid player who fits ANY open slot (exact position first, then letting
             HB and FB swap), then the cheapest player who fits an open slot.

    ARGUMENTS:
        team               (dict)       -- this team's entry in the meta file.
        roster_slots       (list[str])  -- the team's slot labels (including any FLEX slots).
        team_picks         (list[dict]) -- this team's pick-log entries.
        all_players        (list[dict]) -- the whole draft file.
        round_num          (int)        -- the current round (unused by football; kept so all three sports
                                           are called the same way).
        cap                (str|float)  -- the salary cap.
        salary_cap_enabled (bool)       -- True when a cap is on.

    CALLED BY:
        - routes.py: make_ai_pick_fb.

    RETURNS:
        str | None -- the "id" of the player or unit to draft, or None if the roster is full or nothing
                      fits (routes.py then runs its own fallback).
    """
    ai_focus = team.get('AIFocus', 1)
    config = AI_FOCUS_TABLE_FB.get(ai_focus, AI_FOCUS_TABLE_FB[1])

    slot_label, pool_name = eligible_position_fb(roster_slots, team_picks)
    if pool_name is None:
        return None  # roster already full

    stat_key = config.get(pool_name, 'Salary')       # the stat this archetype prizes for this kind

    undrafted = [p for p in all_players if p.get('team_id', 0) == 0]
    if salary_cap_enabled:
        checker = make_cap_checker('fb', roster_slots, team_picks, all_players, team['team_id'], cap)
        affordable = [p for p in undrafted if checker.feasible(p)]
    else:
        affordable = undrafted
    avg_salary = float('inf')

    # Berserker: most of the time, a random player for a random open slot
    if is_berserker(team) and berserker_roll():
        pick = berserker_pick(affordable, open_position_lottery_fb(roster_slots, team_picks), can_fill_fb)
        if pick is not None:
            return pick

    # tiered players first (tier 1, then tier 2), as long as they fit an open slot
    pick = tier_pick(affordable, tier_group_fb, Counter(open_position_lottery_fb(roster_slots, team_picks)))
    if pick is not None:
        return pick

    pick = auto_select_fb(slot_label, pool_name, affordable, stat_key, avg_salary)

    # nobody at that exact position was available/affordable: take the best-paid player who fits
    # ANY open slot. Strict first; HB/FB cross-fill only if nothing else works.
    open_labels = set(open_position_lottery_fb(roster_slots, team_picks))
    open_labels = (open_labels - {'FLEX'}) or open_labels      # use FLEX only if it's all that's left
    if pick is None:
        for strict in (True, False):
            pool = [p for p in affordable if any(fits_slot_fb(p, s, strict) for s in open_labels)]
            pick = ai_select_snippet_fb(ai_sort_pool_fb('Salary', pool), -1, avg_salary)
            if pick is not None:
                break

    # last resort (a team that can no longer make the cap): the cheapest player who fits an open slot
    if pick is None:
        fits = [p for p in undrafted if any(fits_slot_fb(p, s, False) for s in open_labels)]
        fits.sort(key=lambda p: (salary_of(p) <= 0, salary_of(p), random.random()))
        pick = fits[0].get('id') if fits else None

    return pick


def fits_slot_fb(player, slot_label, strict=True):
    """True if this player belongs in the given open slot.
    strict=True: exact position only. strict=False: HB and FB may fill each other's slots.
    A FLEX slot takes anyone.

    PURPOSE:
        The legality test for a football pick: "does this player belong in this kind of slot?"

    ARGUMENTS:
        player     (dict) -- the candidate (uses "short_pos").
        slot_label (str)  -- the slot to test ("QB", "HB", "FB", "TE", "WR", "Def", "Special", "FLEX").
        strict     (bool) -- True = exact match only. False = also let an HB fill an FB slot and vice
                             versa.

    CALLED BY:
        - ai.py: auto_select_fb, ai_select_fb (the fallbacks, in both strict and relaxed mode) and
                 can_fill_fb (strict).

    RETURNS:
        bool -- True if the player fits.
    """
    if slot_label == 'FLEX':
        return True
    natural = SHORT_POS_TO_SLOT_FB.get(player.get('short_pos', ''), '')
    if natural == slot_label:
        return True
    # relaxed mode: an HB may fill "FB" and an FB may fill "HB"
    return (not strict) and HB_FB_OVERFLOW.get(slot_label) == natural


# ============================================================
# SALARY CAP
# ============================================================
# The math lives in cap.py. This section supplies the sport-specific RULES it needs and builds a checker for
# a given team at a given moment.

CAP_SAFETY = 1.10    # the AI keeps 10% more than the bare minimum needed to finish its roster

# One CapRules per sport (see CapRules in cap.py for what natural / free / priority mean).
#   natural   which slot label a player naturally belongs to
#   free      the shared slots (UT, FLEX) and which players may fill each. ORDER MATTERS: UT is filled
#             before FLEX so cheap hitters aren't wasted on FLEX.
#   priority  the slots a drafted player tries, in order (None entries are skipped)
CAP_RULES = {
    'bb': CapRules(
        natural=natural_slot_bb,
        free={'UT': lambda p: p.get('kind') == 'hitter', 'FLEX': lambda p: True},
        priority=lambda p: [natural_slot_bb(p), 'UT' if p.get('kind') == 'hitter' else None, 'FLEX'],
    ),
    'bk': CapRules(
        natural=lambda p: 'Def' if p.get('kind') == 'defense' else p.get('Pos', ''),
        free={'UT': lambda p: p.get('kind') != 'defense'},
        priority=lambda p: ['Def'] if p.get('kind') == 'defense' else [p.get('Pos', ''), 'UT'],
    ),
    'fb': CapRules(
        natural=lambda p: SHORT_POS_TO_SLOT_FB.get(p.get('short_pos', ''), ''),
        free={'FLEX': lambda p: True},
        priority=lambda p: [
            SHORT_POS_TO_SLOT_FB.get(p.get('short_pos', ''), ''),
            HB_FB_OVERFLOW.get(SHORT_POS_TO_SLOT_FB.get(p.get('short_pos', ''), '')),
            'FLEX',
        ],
    ),
}

# sport code -> the function that matches picks to roster slots for that sport
_ASSIGN   = {'bb': assign_picks_to_slots_bb, 'bk': assign_picks_to_slots_bk, 'fb': assign_picks_to_slots_fb}


def open_slot_labels(sport, roster_slots, team_picks):
    """
    PURPOSE:
        List a team's open slot labels for ANY sport (one entry per open slot). The cap checker needs
        this to know what it still has to pay for.

    ARGUMENTS:
        sport        (str)        -- "bb", "bk" or "fb".
        roster_slots (list[str])  -- the team's slot labels.
        team_picks   (list[dict]) -- this team's pick-log entries.

    CALLED BY:
        - ai.py: make_cap_checker.

    RETURNS:
        list[str] -- one label per open slot, e.g. ['C', 'UT', 'UT', 'S'].
    """
    assigned = _ASSIGN[sport](roster_slots, team_picks)
    return [label for filled, label in zip(assigned, roster_slots) if filled is None]


def make_cap_checker(sport, roster_slots, team_picks, all_players, team_id, cap, safety=CAP_SAFETY):
    """roster_slots must already include a FLEX slot for each two-way player the team has.

    PURPOSE:
        Build a CapChecker (cap.py) for one team at this moment: it learns who is still undrafted, how
        much the team has already spent, which slots are open, and who the two-way twins are.

    ARGUMENTS:
        sport        (str)        -- "bb", "bk" or "fb".
        roster_slots (list[str])  -- the team's slot labels, INCLUDING one FLEX per two-way player the
                                     team has drafted.
        team_picks   (list[dict]) -- this team's pick-log entries.
        all_players  (list[dict]) -- the whole draft file.
        team_id      (int)        -- the team this is for.
        cap          (str|float)  -- the salary cap.
        safety       (float)      -- cushion multiplier. The AI uses CAP_SAFETY (1.10); the human
                                     warning passes 1.0 for the exact minimum.

    CALLED BY:
        - ai.py:     ai_select_bb, ai_select_bk, ai_select_fb (default safety).
        - routes.py: human_cap_warning (safety=1.0).

    RETURNS:
        CapChecker -- ready to answer .feasible(player) or .warning(player).
    """
    pool  = [p for p in all_players if p.get('team_id', 0) == 0]                      # undrafted players
    spent = sum(salary_of(p) for p in all_players if p.get('team_id', 0) == team_id)  # this team's payroll so far
    return CapChecker(
        CAP_RULES[sport], pool, open_slot_labels(sport, roster_slots, team_picks),
        spent, parse_salary(cap), twin_map=twin_map_for(sport, all_players), safety=safety,
    )

# ============================================================
# TIER GROUPS: which slots count as "his position" for tier targeting
# ============================================================
# tier_pick (tiers.py) needs to know each player's position GROUP and how many open slots each group has.
# These four small functions supply that for each sport.

def tier_group_bb(p):
    """
    PURPOSE:
        The position group of a baseball player for tier targeting. All three outfield spots count as
        one group, "OF", so a tiered outfielder is a target whenever ANY outfield slot is open.

    ARGUMENTS:
        p (dict) -- a baseball player.

    CALLED BY:
        - tiers.py: tier_pick (passed in by ai_select_bb as its group_of function).

    RETURNS:
        str -- "OF" for LF/CF/RF; otherwise his natural slot ("C", "SS", "S", "R", "UT"...).
    """
    slot = natural_slot_bb(p)
    return 'OF' if slot in ('LF', 'CF', 'RF') else slot       # outfielders share one group


def tier_open_groups_bb(open_counts):
    """
    PURPOSE:
        Turn the team's open-slot tally into group counts that match tier_group_bb (outfield slots
        merged into "OF").

    ARGUMENTS:
        open_counts (Counter) -- open slots by label (from open_slot_counts_bb).

    CALLED BY:
        - ai.py: ai_select_bb (handed to tier_pick as open_groups).

    RETURNS:
        Counter -- like {"C": 1, "OF": 2, "UT": 3, "S": 2}.
    """
    groups = Counter()
    for label, n in open_counts.items():
        groups['OF' if label in ('LF', 'CF', 'RF') else label] += n
    return groups


def tier_group_bk(p):
    """
    PURPOSE:
        The position group of a basketball record for tier targeting: "Def" for a defense unit,
        otherwise his Pos ("C", "F" or "G").

    ARGUMENTS:
        p (dict) -- a basketball player or defense unit.

    CALLED BY:
        - tiers.py: tier_pick (passed in by ai_select_bk as its group_of function).

    RETURNS:
        str -- "Def", "C", "F", "G", or "" if there is no Pos.
    """
    return 'Def' if _is_def(p) else p.get('Pos', '')


def tier_group_fb(p):
    """
    PURPOSE:
        The position group of a football record for tier targeting, which is simply its roster slot
        label ("QB", "HB", "FB", "TE", "WR", "Def", "Special").

    ARGUMENTS:
        p (dict) -- a football player or unit.

    CALLED BY:
        - tiers.py: tier_pick (passed in by ai_select_fb as its group_of function).

    RETURNS:
        str -- the slot label, or "" if the position isn't recognised.
    """
    return SHORT_POS_TO_SLOT_FB.get(p.get('short_pos', ''), '')

# ============================================================
# HANDEDNESS BALANCE (s_bal)
# ============================================================
# s_bal looks like '6L', '4R', '1L', 'E'. The letter is the side the player is strong against
# (a 6L hitter crushes lefty pitchers, a 4R pitcher dominates righty hitters) and the number is how
# lopsided he is. 1L, 1R and E are good both ways. A player scores +n for L, -n for R, 0 for E, and a
# team's hitters (and pitchers) are kept near zero unless the team has its own L or R lean.
#
# Baseball only. WHY: a team stacked with players who are all strong against lefties would be easy to beat
# with a righty starter, so the AI nudges each team toward a mix.

BAL_TOLERANCE  = 8      # how far a team's hitters (or pitchers) may lean to one side
BAL_STRICTNESS = 0.85   # share of picks that respect balance; the rest ignore it, for variety
LEAN_STICK     = 0.70   # how often an L or R leaning team sticks to its side


def parse_balance(raw):
    """
    PURPOSE:
        Turn a balance code like '6L', '4R' or 'E' into a signed number: left-strong is positive,
        right-strong is negative, even (E, blank, or unreadable) is 0.

    ARGUMENTS:
        raw (str | None) -- the s_bal value, e.g. '6L'.

    CALLED BY:
        - ai.py: balance_lean.

    RETURNS:
        int -- +n for 'nL', -n for 'nR', 0 otherwise. ('1L' gives +1, '4R' gives -4.)
    """
    # one digit, optional spaces, then L or R, at the start of the text
    m = re.match(r'\s*(\d)\s*([LR])', str(raw or '').upper())
    if not m:
        return 0                              # 'E' or missing: even
    n = int(m.group(1))
    return n if m.group(2) == 'L' else -n


def balance_lean(p):
    """
    PURPOSE:
        Read a player's handedness lean as a signed number. Uses the Strat key "s_bal" (falling back
        to "b_bal" if that's the one present).

    ARGUMENTS:
        p (dict) -- a baseball player.

    CALLED BY:
        - ai.py: ai_select_bb (totalling the team's lean) and balance_pool.

    RETURNS:
        int -- see parse_balance.
    """
    return parse_balance(p.get('s_bal', p.get('b_bal')))


def team_lean_bb(team):
    """None = balanced; 'L' or 'R' = this team likes that side. Set "Lean" in the meta file to force one
    ('L', 'R' or 'B'); otherwise it's derived from the team's id, so it stays the same all draft.

    PURPOSE:
        Decide whether an AI team deliberately leans lefty or righty (a "personality") or stays balanced.
        Not random each pick: it's worked out from the team's AIFocus and team_id so it never changes
        during a draft. About 20% of teams lean L, 20% lean R and 60% stay balanced.
        To force it for one team, add "Lean": "L" / "R" / "B" (B = balanced) to that team in the meta file.

    ARGUMENTS:
        team (dict) -- the team's entry in the meta file.

    CALLED BY:
        - ai.py: ai_select_bb.

    RETURNS:
        str | None -- 'L', 'R', or None for balanced.
    """
    pref = team.get('Lean')
    if pref in ('L', 'R'):
        return pref
    if pref == 'B':
        return None
    # a repeatable number 0-4 built from the team's own numbers; 0 -> L, 1 -> R, 2/3/4 -> balanced
    k = (int(team.get('AIFocus', 1)) * 7 + int(team.get('team_id', 0)) * 3) % 5
    return ('L', 'R', None, None, None)[k]


def balance_pool(pool, net, lean):
    """Keep the players that fit this team's lean. Falls back to the full pool if that leaves nobody.

    PURPOSE:
        Narrow a pool of players to those who keep the team's handedness balance acceptable.
          - Balanced team (lean None): keep a player if the team's total lean AFTER adding him stays
            within +/- BAL_TOLERANCE.
          - Left-leaning team: keep him if the total doesn't fall below -BAL_TOLERANCE, and (70% of the
            time, LEAN_STICK) only if he is left-strong or even.
          - Right-leaning team: the mirror image.
        If that would leave nobody, the whole pool is returned unchanged.

    ARGUMENTS:
        pool (list[dict]) -- the hitters (or pitchers) under consideration.
        net  (int)        -- the team's current total lean for that group (sum of balance_lean).
        lean (str | None) -- the team's lean from team_lean_bb.

    CALLED BY:
        - ai.py: ai_select_bb (inside attempt(), separately for hitters and pitchers).

    RETURNS:
        list[dict] -- the players that pass (never empty unless the input was empty).
    """
    stick = random.random() < LEAN_STICK          # does a leaning team stick to its side THIS pick?
    keep = []
    for p in pool:
        s = balance_lean(p)                       # this player's signed lean
        new = net + s                             # the team's lean if he's added
        if lean is None:
            ok = abs(new) <= BAL_TOLERANCE
        elif lean == 'L':
            ok = new >= -BAL_TOLERANCE and (s >= 0 or not stick)
        else:
            ok = new <= BAL_TOLERANCE and (s <= 0 or not stick)
        if ok:
            keep.append(p)
    return keep or pool