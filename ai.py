"""
ai.py — AI drafting logic (port of the original CLI's aipicks.py).

Currently baseball only. Basketball and football AI will follow the same
shape once their position-eligibility rules are worked out.
"""

import random
import math

from .services import (
    assign_picks_to_slots_bb, assign_picks_to_slots_bk, assign_picks_to_slots_fb,
    SHORT_POS_TO_SLOT_BB, SHORT_POS_TO_SLOT_FB, HB_FB_OVERFLOW, TWO_WAY_BB, TWO_WAY_FB
)
from collections import Counter
from .cap import CapChecker, CapRules, salary_of
from .tiers import tier_pick


# ============================================================
# Raw-data parsers
# The old aipicks.py assumed fields (DP1/DP2/DP3, Bat, Throw, Role, Price)
# that don't exist in this project's data. These derive equivalent values
# from the real fields (s_fielding, Bats, Throws, s_endurance, s_sal).
# ============================================================

def parse_salary(raw):
    """'$11,150,000 ' -> 11150000.0. Returns 0.0 if blank/unparseable."""
    if raw is None:
        return 0.0
    cleaned = str(raw).replace('$', '').replace(',', '').strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def to_float(value, default=0.0):
    """Tolerant number parser: handles None, '$1,200', '45%', and junk like 'Feb-00' (-> default)."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace('$', '').replace(',', '').rstrip('%')
        try:
            number = float(text)
        except ValueError:
            return default
    return number if math.isfinite(number) else default


POS_ABBR_TO_CODE = {
    'c': '2', '1b': '3', '2b': '4', '3b': '5',
    'ss': '6', 'lf': '7', 'cf': '8', 'rf': '9',
}

def parse_fielding(hitter):
    """'rf-1(-2)e6 1b-4e7 cf-2e6' -> ('9', '3', '8')  (DP1, DP2, DP3)."""
    raw = hitter.get('s_fielding', '') or ''
    tokens = raw.strip().split()
    codes = []
    for tok in tokens[:3]:
        abbr = tok.split('-')[0].strip().lower()
        codes.append(POS_ABBR_TO_CODE.get(abbr, ''))
    while len(codes) < 3:
        codes.append('')
    return codes[0], codes[1], codes[2]


def bat_throw_code(value):
    """'Left' -> 'L', 'Right' -> 'R', 'Switch' -> 'S'."""
    if not value:
        return ''
    return value.strip()[0].upper()


def pitcher_role(pitcher):
    """'S(7)' -> 'S' (starter). 'R...' / 'C...' -> 'R' (reliever, closer counts as reliever)."""
    raw = pitcher.get('s_endurance', '') or ''
    first = raw.strip()[:1].upper()
    if first == 'S':
        return 'S'
    if first in ('R', 'C'):
        return 'R'
    return ''


# ============================================================
# Position eligibility
# Port of aipicks.py's eligiblePosition(). Reuses assign_picks_to_slots_bb's
# open-slot bookkeeping rather than duplicating it -- whatever slot came
# back None from that function is, by definition, still open.
# ============================================================

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
    """
    assigned = assign_picks_to_slots_bb(roster_slots, team_picks)
    lottery = []
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
    """
    lottery = open_position_lottery(roster_slots, team_picks)
    selected = ['0', 0, 0]

    if '1' in lottery:
        selected[1] = 1
    if '11' in lottery:
        selected[2] = 11

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
    """The roster slot a player naturally fills. Same lookup the roster display uses."""
    return SHORT_POS_TO_SLOT_BB.get(player.get('short_pos', ''), 'UT')


def open_slot_counts_bb(roster_slots, team_picks):
    """{slot label: number of still-open slots} for this team."""
    assigned = assign_picks_to_slots_bb(roster_slots, team_picks)
    return Counter(label for filled, label in zip(assigned, roster_slots) if filled is None)


FIELD_POS_BB       = ('C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF')
UT_BACKUPS_PER_POS = 1    # raise to 2 to allow more backups at the same position


def hitter_pos_counts_bb(team_picks):
    """How many hitters this team already has at each natural position (starters + backups)."""
    counts = Counter()
    for e in team_picks:
        slot = SHORT_POS_TO_SLOT_BB.get(e.get('pos', ''), 'UT')
        if slot not in ('S', 'R'):
            counts[slot] += 1
    return counts


def fits_open_slots_bb(player, open_counts, pos_counts=None, base_slots=None):
    """True if this player would land in an open slot he belongs in:
    his natural slot, UT (hitters only, with a backup-variety limit), or a FLEX slot."""
    natural = natural_slot_bb(player)
    if open_counts.get(natural):
        return True
    if player.get('kind') == 'hitter' and open_counts.get('UT'):
        if pos_counts is None:          # variety check switched off
            return True
        starters = base_slots.get(natural, 0) if natural in FIELD_POS_BB else 0
        if pos_counts.get(natural, 0) < starters + UT_BACKUPS_PER_POS:
            return True
    return bool(open_counts.get('FLEX'))

def check_functions_bb(def_check):
    def at_slot(label):
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
    return table.get(def_check, lambda p: True)

FOCUS_KINDS_BB = {11: 'P', 13: 'HP', 14: 'H'}


def ai_select_snippet_bb(playerpool, threshold, def_check, avg_salary, focus=0):
    pos_check = check_functions_bb(def_check)
    focus_check = check_functions_bb(focus) if focus else (lambda p: True)
    counter = 0
    for player in playerpool:
        if not (pos_check(player) and focus_check(player)):
            continue
        salary = parse_salary(player.get('s_sal'))
        if salary > avg_salary or salary < 600:
            continue
        if threshold < 0 or counter > threshold:
            return player.get('id')
        counter += 1
    return None


def top_four_grabs_bb(kind, playerpool, position, direction, avg_salary, focus=0):
    if kind == 'P':
        if direction == 1 and position[1] == 1:
            def_check = 1
        elif direction == 11 and position[2] == 11:
            def_check = 11
        else:
            def_check = 0
    else:
        def_check = int(position[0])

    roll = random.randrange(100)
    threshold = -1 if roll < 40 else 0 if roll < 70 else 1 if roll < 90 else 2

    # only apply the focus if it makes sense for this kind of player
    use_focus = focus if kind in FOCUS_KINDS_BB.get(focus, '') else 0

    pick = ai_select_snippet_bb(playerpool, threshold, def_check, avg_salary, use_focus)
    if pick is None and use_focus:
        pick = ai_select_snippet_bb(playerpool, threshold, def_check, avg_salary, 0)
    return pick


def ai_sort_pool_bb(stat_key, players):
    """Highest-better, except ERA/WHIP which sort ascending."""
    ascending = stat_key in ('p_earned_run_avg', 'p_whip')
    if stat_key == 's_sal':
        keyfunc = lambda r: parse_salary(r.get('s_sal'))
    else:
        keyfunc = lambda r: float(r.get(stat_key, 0) or 0)
    return sorted(players, key=keyfunc, reverse=not ascending)


# ============================================================
# Top-level: AIFocus archetypes and the aiSelect() equivalent
# ============================================================

AI_FOCUS_TABLE = {
    1:  {'keys': ['s_sal']*6, 'focus': 0, 'mode': 'H'},
    2:  {'keys': ['b_hr','b_slugging_perc','b_rbi','s_sal','p_so','p_earned_run_avg'], 'focus': 0, 'mode': 'H'},
    3:  {'keys': ['s_sal','p_w','p_earned_run_avg','s_sal','b_onbase_perc','b_hr'], 'focus': 0, 'mode': 'P'},
    4:  {'keys': ['b_batting_avg','b_sb','s_sal','s_sal','p_whip','p_earned_run_avg'], 'focus': 0, 'mode': 'H'},
    5:  {'keys': ['s_sal','b_h','b_batting_avg','s_sal','p_w','p_so'], 'focus': 12, 'mode': 'H'},
    6:  {'keys': ['s_sal','b_sb','b_batting_avg','s_sal','p_w','p_so'], 'focus': 12, 'mode': 'H'},
    7:  {'keys': ['s_sal','p_sv','p_earned_run_avg','s_sal','b_hr','b_rbi'], 'focus': 11, 'mode': 'P'},
    8:  {'keys': ['p_whip','p_earned_run_avg','s_sal','s_sal','b_batting_avg','b_rbi'], 'focus': 0, 'mode': 'P'},
    9:  {'keys': ['b_sb','b_onbase_perc','s_sal','s_sal','p_whip','p_w'], 'focus': 0, 'mode': 'H'},
    10: {'keys': ['b_doubles','b_slugging_perc','b_triples','s_sal','p_so','p_whip'], 'focus': 0, 'mode': 'H'},
    11: {'keys': ['b_onbase_perc','b_batting_avg','s_sal','s_sal','p_whip','p_earned_run_avg'], 'focus': 0, 'mode': 'H'},
    12: {'keys': ['p_so','p_whip','s_sal','s_sal','b_hr','b_slugging_perc'], 'focus': 0, 'mode': 'P'},
    13: {'keys': ['s_sal','b_batting_avg','b_slugging_perc','s_sal','p_earned_run_avg','p_whip'], 'focus': 13, 'mode': 'H'},
    14: {'keys': ['s_sal','b_batting_avg','b_hr','s_sal','p_earned_run_avg','p_w'], 'focus': 0, 'mode': 'H'},
    15: {'keys': ['s_sal','b_batting_avg','b_hr','s_sal','p_earned_run_avg','p_w'], 'focus': 14, 'mode': 'H'},
    16: {'keys': ['b_rbi','b_slugging_perc','s_sal','s_sal','p_whip','p_so'], 'focus': 0, 'mode': 'H'},
}


def first_rounds_bb(hitters_pool, pitchers_pool, avg_salary):
    """
    Port of aipicks.py's firstRounds() -- early-round 'best available',
    no position filter, 30% hitter / 70% pitcher split. Uses the real
    avg_salary passed in rather than the original's hardcoded $20,000,
    which was tuned to a much smaller salary scale than this data uses.
    """
    no_position = ['0', 0, 0]
    if random.randrange(100) < 30:
        pool = ai_sort_pool_bb('s_sal', hitters_pool)
        return top_four_grabs_bb('H', pool, no_position, 0, avg_salary)
    else:
        pool = ai_sort_pool_bb('s_sal', pitchers_pool)
        return top_four_grabs_bb('P', pool, no_position, 0, avg_salary)


def auto_select_hitter_bb(position, hitters_pool, pitchers_pool, round_num, focus, keys, avg_salary):
    """Port of aipicks.py's autoSelectHitter()."""
    side_threshold = 90 if round_num < 3 else 50
    side = random.randrange(100)

    if side < side_threshold and round_num < 3:
        return first_rounds_bb(hitters_pool, pitchers_pool, avg_salary)

    if side < side_threshold:
        key_str = random.choices(keys[0:3], weights=[70, 20, 10])[0]
        pool = ai_sort_pool_bb(key_str, hitters_pool)
        return top_four_grabs_bb('H', pool, position, 0, avg_salary, focus)

    key_str = random.choices(keys[3:6], weights=[70, 20, 10])[0]
    pool = ai_sort_pool_bb(key_str, pitchers_pool)
    direction = 1 if (random.randrange(100) < 80 and position[1] > 0) else 11
    return top_four_grabs_bb('P', pool, position, direction, avg_salary, focus)


def auto_select_pitcher_bb(position, hitters_pool, pitchers_pool, round_num, focus, keys, avg_salary):
    """Port of aipicks.py's autoSelectPitcher()."""
    side_threshold = 90 if round_num < 3 else 50
    side = random.randrange(100)

    if side < side_threshold and round_num < 3:
        return first_rounds_bb(hitters_pool, pitchers_pool, avg_salary)

    if side < side_threshold:
        key_str = random.choices(keys[0:3], weights=[70, 20, 10])[0]
        pool = ai_sort_pool_bb(key_str, pitchers_pool)
        if random.randrange(100) < 80 and position[1] > 0:
            direction = 1
        else:
            direction = 11
        if focus == 11:      # RP-heavy archetype: always lean reliever
            direction = 11
        return top_four_grabs_bb('P', pool, position, direction, avg_salary, focus)

    key_str = random.choices(keys[3:6], weights=[70, 20, 10])[0]
    pool = ai_sort_pool_bb(key_str, hitters_pool)
    return top_four_grabs_bb('H', pool, position, 0, avg_salary, focus)


def ai_select_bb(team, roster_slots, team_picks, all_players, round_num, cap, salary_cap_enabled):
    """
    Port of aipicks.py's aiSelect() for one team's single pick.
    With a salary cap, only players the team can afford while still being able to finish
    its roster under the cap are candidates. Returns a player id, or None.
    """
    ai_focus = team.get('AIFocus', 1)
    config = AI_FOCUS_TABLE.get(ai_focus, AI_FOCUS_TABLE[1])
    position = eligible_position_bb(roster_slots, team_picks, ai_focus)

    open_counts = open_slot_counts_bb(roster_slots, team_picks)
    pos_counts  = hitter_pos_counts_bb(team_picks)
    base_slots  = Counter(roster_slots)

    undrafted = [p for p in all_players if p.get('team_id', 0) == 0]
    if salary_cap_enabled:
        checker = make_cap_checker('bb', roster_slots, team_picks, all_players, team['team_id'], cap)
        affordable = [p for p in undrafted if checker.feasible(p)]
    else:
        affordable = undrafted
    avg_salary = float('inf')          # the cap checker replaces the old late-round "budget mode"
    # tiered players first (tier 1, then tier 2), as long as they fit an open slot
    pick = tier_pick(affordable, tier_group_bb, tier_open_groups_bb(open_counts))
    if pick is not None:
        return pick

    def attempt(variety):
        pc = pos_counts if variety else None
        hitters_pool = [
            p for p in affordable
            if p.get('kind') == 'hitter' and fits_open_slots_bb(p, open_counts, pc, base_slots)
        ]
        pitchers_pool = [
            p for p in affordable
            if p.get('kind') == 'pitcher' and fits_open_slots_bb(p, open_counts, pc, base_slots)
        ]
        if config['mode'] == 'H':
            pick = auto_select_hitter_bb(position, hitters_pool, pitchers_pool, round_num, config['focus'], config['keys'], avg_salary)
        else:
            pick = auto_select_pitcher_bb(position, hitters_pool, pitchers_pool, round_num, config['focus'], config['keys'], avg_salary)

        # rolled side or slot had nobody: take the best-paid player who fits from either pool
        if pick is None:
            pool = ai_sort_pool_bb('s_sal', hitters_pool + pitchers_pool)
            pick = ai_select_snippet_bb(pool, -1, 0, avg_salary)
        return pick

    pick = attempt(True)
    if pick is None:
        pick = attempt(False)          # only break the UT variety rule if there's no other option

    # last resort (a team that can no longer make the cap): the cheapest player who fits an open slot
    if pick is None:
        fits = [p for p in undrafted if fits_open_slots_bb(p, open_counts)]
        fits.sort(key=lambda p: (salary_of(p) <= 0, salary_of(p), random.random()))
        pick = fits[0].get('id') if fits else None

    return pick


# ============================================================
# BASKETBALL
# ============================================================

def open_position_lottery_bk(roster_slots, team_picks):
    """Open slot labels for this team, one entry per open slot (duplicates included)."""
    assigned = assign_picks_to_slots_bk(roster_slots, team_picks)
    return [label for filled, label in zip(assigned, roster_slots) if filled is None]


def eligible_position_bk(roster_slots, team_picks):
    """Returns a random open slot label ('C'/'F'/'G'/'UT'), or None if the roster is full."""
    open_labels = open_position_lottery_bk(roster_slots, team_picks)
    if not open_labels:
        return None
    return random.choice(open_labels)


def _is_def(p):
    return p.get('kind') == 'defense'


def check_functions_bk(code):
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
    """Position AND focus both have to pass."""
    pos_fn   = check_functions_bk(position_code)
    focus_fn = check_functions_bk(focus_code) if focus_code else (lambda p: True)
    return lambda p: pos_fn(p) and focus_fn(p)


def ai_select_snippet_bk(playerpool, threshold, position_code, focus_code, avg_salary):
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
    roll = random.randrange(100)
    threshold = -1 if roll < 40 else 0 if roll < 70 else 1 if roll < 90 else 2
    return ai_select_snippet_bk(playerpool, threshold, position_code, focus_code, avg_salary)


def _quality_bk(p):
    """Rough overall rating from the real stats. Used when the chosen stat has no data."""
    return to_float(p.get('ptspgm')) + to_float(p.get('rbspgm')) + to_float(p.get('astpgm'))


def ai_sort_pool_bk(stat_key, players):
    """Higher is better. If nobody has real data for this stat (e.g. Salary missing from the JSON),
    fall back to an overall rating so the order isn't just alphabetical.
    Ties are broken randomly, never alphabetically."""
    values = [to_float(p.get(stat_key)) for p in players]
    if not values or max(values) == min(values):
        key = _quality_bk
    else:
        key = lambda p: to_float(p.get(stat_key))
    return sorted(players, key=lambda p: (-key(p), random.random()))


AI_FOCUS_TABLE_BK = {
    1:  {'keys': ['Salary']*6, 'focus': 0},
    2:  {'keys': ['Omade','fg3_pct','PassDazz','Salary','ptspgm','Shoot'], 'focus': 0},
    3:  {'keys': ['Salary','rbspgm','Shoot','Salary','fg_pct','Omade'], 'focus': 0},
    4:  {'keys': ['fg3_pct','rbspgm','Salary','Salary','DPass1','PassDazz'], 'focus': 0},
    5:  {'keys': ['Salary','astpgm','fg_pct','Salary','DPass1','rbspgm'], 'focus': 12},
    6:  {'keys': ['Salary','astpgm','fg_pct','Salary','DPass1','rbspgm'], 'focus': 12},
    7:  {'keys': ['Salary','Imade','Shoot','Salary','Omade','astpgm'], 'focus': 11},
    8:  {'keys': ['ptspgm','DPass1','Salary','Salary','fg_pct','astpgm'], 'focus': 0},
    9:  {'keys': ['Imade','astpgm','ptspgm','Salary','PassDazz','ptspgm'], 'focus': 0},
    10: {'keys': ['astpgm','fg3_pct','Imade','Salary','ptspgm','DPass1'], 'focus': 0},
    11: {'keys': ['ptspgm','fg3_pct','Salary','Salary','PassDazz','Shoot'], 'focus': 0},
    12: {'keys': ['ptspgm','DPass1','Salary','Salary','Omade','astpgm'], 'focus': 0},
    13: {'keys': ['Salary','rbspgm','fg3_pct','Salary','Shoot','DPass1'], 'focus': 13},
    14: {'keys': ['Salary','Omade','ptspgm','Salary','Shoot','PassDazz'], 'focus': 0},
    15: {'keys': ['Salary','Omade','ptspgm','Salary','Shoot','PassDazz'], 'focus': 14},
    16: {'keys': ['PassDazz','fg3_pct','Salary','Salary','DPass1','ptspgm'], 'focus': 0},
}


def auto_select_bk(position_code, pool, focus_code, keys, avg_salary):
    """Single-pool version of autoSelectHitter -- the side-roll picks between
    two stat triplets purely for variety, since there's only one pool either way."""
    side = random.randrange(100)
    triplet = keys[0:3] if side < 50 else keys[3:6]
    key_str = random.choices(triplet, weights=[70, 20, 10])[0]
    sorted_pool = ai_sort_pool_bk(key_str, pool)
    return top_four_grabs_bk(sorted_pool, position_code, focus_code, avg_salary)


def _defense_score(p):
    """Sort key (ascending): priciest defense first, then the fewest opponent makes."""
    made = sum(to_float(p.get(k)) for k in ('Omade', 'Pmade', 'Imade', 'Fmade', '3made'))
    return (-parse_salary(p.get('Salary')), made)


def ai_select_bk(team, roster_slots, team_picks, all_players, round_num, cap, salary_cap_enabled):
    """Port of aiSelect() for basketball -- one team's single pick."""
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

    # tiered players first (tier 1, then tier 2), as long as they fit an open slot
    pick = tier_pick(affordable, tier_group_bk, Counter(open_position_lottery_bk(roster_slots, team_picks)))
    if pick is not None:
        return pick

    def cheapest(candidates):
        candidates = sorted(candidates, key=lambda p: (salary_of(p) <= 0, salary_of(p), random.random()))
        return candidates[0].get('id') if candidates else None

    # the slot this team is filling is the defense: choose among the defense units
    if position_code == 'Def':
        defenses = sorted((p for p in affordable if _is_def(p)), key=_defense_score)
        pick = top_four_grabs_bk(defenses, 'Def', 0, avg_salary)
        if pick is None:
            pick = cheapest(p for p in undrafted if _is_def(p))
        return pick

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

SLOT_TO_POOL_FB = {
    'QB': 'passer',
    'HB': 'rusher', 'FB': 'rusher',
    'TE': 'receiver', 'WR': 'receiver',
    'Def': 'dlineoline',
    'Special': 'special',
}


def open_position_lottery_fb(roster_slots, team_picks):
    """Open slot labels for this team, one entry per open slot (duplicates included)."""
    assigned = assign_picks_to_slots_fb(roster_slots, team_picks)
    return [label for filled, label in zip(assigned, roster_slots) if filled is None]


def eligible_position_fb(roster_slots, team_picks):
    """Returns (slot_label, pool_name) for a randomly chosen open slot, or (None, None) if full.
    A FLEX slot (from a two-way player) is only used when it's the last one open."""
    open_labels = open_position_lottery_fb(roster_slots, team_picks)
    if not open_labels:
        return None, None
    regular = [label for label in open_labels if label != 'FLEX']
    if regular:
        slot_label = random.choice(regular)
        return slot_label, SLOT_TO_POOL_FB.get(slot_label)
    return 'FLEX', random.choice(['passer', 'rusher', 'receiver'])


FB_ASCENDING_STATS = {'s_Run', 's_Pass', 's_YdspPlay'}  # lower is better


def ai_sort_pool_fb(stat_key, players):
    def keyfunc(r):
        if stat_key == 'Salary':
            return parse_salary(r.get('Salary'))
        raw = r.get(stat_key, 0)
        if isinstance(raw, str) and raw.strip().endswith('%'):
            try:
                return float(raw.strip().rstrip('%'))
            except ValueError:
                return 0.0
        return float(raw or 0)

    ascending = stat_key in FB_ASCENDING_STATS
    return sorted(players, key=keyfunc, reverse=not ascending)


def ai_select_snippet_fb(playerpool, threshold, avg_salary):
    """No position filter needed -- the pool passed in is already position-locked by kind."""
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
    roll = random.randrange(100)
    threshold = -1 if roll < 40 else 0 if roll < 70 else 1 if roll < 90 else 2
    return ai_select_snippet_fb(playerpool, threshold, avg_salary)


def auto_select_fb(slot_label, pool_name, all_players, stat_key, avg_salary):
    pool = [
        p for p in all_players
        if p.get('kind') == pool_name and p.get('team_id', 0) == 0 and fits_slot_fb(p, slot_label)
    ]
    sorted_pool = ai_sort_pool_fb(stat_key, pool)
    return top_four_grabs_fb(sorted_pool, avg_salary)


# Each archetype picks ONE preferred stat per pool -- no roll needed, since
# eligible_position_fb already determined the pool from the open roster slot.
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


def ai_select_fb(team, roster_slots, team_picks, all_players, round_num, cap, salary_cap_enabled):
    """Port of aiSelect() for football -- one team's single pick."""
    ai_focus = team.get('AIFocus', 1)
    config = AI_FOCUS_TABLE_FB.get(ai_focus, AI_FOCUS_TABLE_FB[1])

    slot_label, pool_name = eligible_position_fb(roster_slots, team_picks)
    if pool_name is None:
        return None  # roster already full

    stat_key = config.get(pool_name, 'Salary')

    undrafted = [p for p in all_players if p.get('team_id', 0) == 0]
    if salary_cap_enabled:
        checker = make_cap_checker('fb', roster_slots, team_picks, all_players, team['team_id'], cap)
        affordable = [p for p in undrafted if checker.feasible(p)]
    else:
        affordable = undrafted
    avg_salary = float('inf')

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
    A FLEX slot takes anyone."""
    if slot_label == 'FLEX':
        return True
    natural = SHORT_POS_TO_SLOT_FB.get(player.get('short_pos', ''), '')
    if natural == slot_label:
        return True
    return (not strict) and HB_FB_OVERFLOW.get(slot_label) == natural


# ============================================================
# SALARY CAP
# ============================================================

CAP_SAFETY = 1.10    # the AI keeps 10% more than the bare minimum needed to finish its roster

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
TWIN_MAPS = {'bb': TWO_WAY_BB, 'bk': {}, 'fb': TWO_WAY_FB}
_ASSIGN   = {'bb': assign_picks_to_slots_bb, 'bk': assign_picks_to_slots_bk, 'fb': assign_picks_to_slots_fb}


def open_slot_labels(sport, roster_slots, team_picks):
    assigned = _ASSIGN[sport](roster_slots, team_picks)
    return [label for filled, label in zip(assigned, roster_slots) if filled is None]


def make_cap_checker(sport, roster_slots, team_picks, all_players, team_id, cap, safety=CAP_SAFETY):
    """roster_slots must already include a FLEX slot for each two-way player the team has."""
    pool  = [p for p in all_players if p.get('team_id', 0) == 0]
    spent = sum(salary_of(p) for p in all_players if p.get('team_id', 0) == team_id)
    return CapChecker(
        CAP_RULES[sport], pool, open_slot_labels(sport, roster_slots, team_picks),
        spent, parse_salary(cap), twin_map=TWIN_MAPS[sport], safety=safety,
    )

# ============================================================
# TIER GROUPS: which slots count as "his position" for tier targeting
# ============================================================

def tier_group_bb(p):
    slot = natural_slot_bb(p)
    return 'OF' if slot in ('LF', 'CF', 'RF') else slot       # outfielders share one group


def tier_open_groups_bb(open_counts):
    groups = Counter()
    for label, n in open_counts.items():
        groups['OF' if label in ('LF', 'CF', 'RF') else label] += n
    return groups


def tier_group_bk(p):
    return 'Def' if _is_def(p) else p.get('Pos', '')


def tier_group_fb(p):
    return SHORT_POS_TO_SLOT_FB.get(p.get('short_pos', ''), '')