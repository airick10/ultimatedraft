"""
tiers.py  --  tier-aware targeting for the AI drafters.

THE IDEA
    You can mark players in the JSON files with a "tier" number:
        tier 1 = elite,   tier 2 = very good,   anything else (or no tier) = untiered.

    Before each AI pick, tier_pick() looks for tiered players the team could take:
        1. Tier 1 players that fit one of the team's OPEN slots are targeted first.
        2. If there are none (or the team "passes" on them), tier 2 players are next.
        3. A team sometimes PASSES on a tier, so elite players don't always go in the first
           few picks and the draft stays unpredictable.
    If nothing is chosen, tier_pick() returns None and the AI makes its normal pick.

WHAT "FITS AN OPEN SLOT" MEANS
    Positions are grouped (the caller decides how; for baseball all three outfield spots count
    as one group "OF"). A tiered player is only a target if his group still has an open slot.
    So a team with no catcher slots left never "targets" a tier-1 catcher.

WHO USES THIS FILE
    - ai.py: ai_select_bb, ai_select_bk and ai_select_fb each call tier_pick().
      (Berserker mode in berserker.py is rolled BEFORE this, so it can override it.)
    - check_tiers.py does NOT import this file; it has its own copy of the tier-reading code.
"""

import random                          # for the pass chances and the weighted choice

from .cap import salary_of             # reads a salary as a number, used to rank the targets

# ---------------------------------------------------------------------------
# Settings you can tune
# ---------------------------------------------------------------------------
TIER1_PASS_CHANCE = 0.15            # chance a team passes on tier 1 (and looks at tier 2 instead)
TIER2_PASS_CHANCE = 0.25            # chance a team passes on tier 2 once no tier 1 is left for it

# When there are several targets, the team looks at the best-ranked few and picks among them with
# these weights, so the very best isn't ALWAYS taken. 40/30/20/10 means: best 40%, second 30%,
# third 20%, fourth 10%. It's the same spread the rest of the AI uses.
PICK_WEIGHTS      = [40, 30, 20, 10]


def tier_of(player):
    """
    PURPOSE:
        Read a player's tier as a whole number. The JSON might store it as 1, "1", "1.0" or under
        a capital-T "Tier" key, so this tolerates all of those.

    ARGUMENTS:
        player (dict) -- one player record.

    CALLED BY:
        - tiers.py: tier_pick (once per candidate player).

    RETURNS:
        int | None -- the tier (1, 2, or whatever number is stored), or None if there is no tier
                      or it can't be read as a number.
    """
    # Look for "tier" first, then "Tier".
    raw = player.get("tier", player.get("Tier"))
    try:
        # str() -> strip spaces -> float() -> int(): handles 1, "1", " 1 " and "1.0" the same way.
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        # No tier at all (None becomes "None" and fails float()) or text that isn't a number.
        return None


def _choose(targets):
    """
    PURPOSE:
        From a list of acceptable target players, pick one: rank them by highest salary first,
        then choose among the top few with weighted randomness (see PICK_WEIGHTS). Salary is the
        yardstick for "best" because it is available for every player in every sport.

    ARGUMENTS:
        targets (list[dict]) -- player records that are all fair game. Must not be empty.

    CALLED BY:
        - tiers.py: tier_pick (up to twice, once for tier 1 and once for tier 2).

    RETURNS:
        str -- the "id" of the chosen player.
    """
    # Sort by salary, biggest first. The random.random() part is a tie-breaker so equal salaries
    # don't always come out in the same order.
    ranked = sorted(targets, key=lambda p: (-salary_of(p), random.random()))

    # Only the first few get a chance (as many as there are weights).
    top = ranked[:len(PICK_WEIGHTS)]

    # random.choices returns a list of 1; [0] takes the player. The weights list is cut to the
    # same length as `top` in case there are fewer than four targets.
    return random.choices(top, weights=PICK_WEIGHTS[:len(top)])[0].get("id")


def tier_pick(candidates, group_of, open_groups):
    """
    PURPOSE:
        The main entry point. Decide whether this AI team should grab a tiered player right now,
        and if so, which one.

    ARGUMENTS:
        candidates  (list[dict]) -- undrafted players this team could take (already filtered
                                    by the salary cap).
        group_of    (function)   -- group_of(player) -> the position group he belongs to, such
                                    as "SS", "OF", "QB" or "Def". Each sport supplies its own.
        open_groups (dict)       -- {group: number of still-open slots in that group}. Groups
                                    with 0 are not targeted.

    CALLED BY:
        - ai.py: ai_select_bb  (with tier_group_bb and tier_open_groups_bb)
                 ai_select_bk  (with tier_group_bk)
                 ai_select_fb  (with tier_group_fb)

    RETURNS:
        str | None -- the "id" of the player to draft, or None meaning "no tiered pick; let the
                      normal AI logic choose".
    """
    # Sort every eligible tiered player into a tier 1 list or a tier 2 list.
    targets = {1: [], 2: []}
    for p in candidates:
        t = tier_of(p)
        # t in targets  -> only tiers 1 and 2 count.
        # open_groups.get(...) > 0 -> his position group still has room on this roster.
        if t in targets and open_groups.get(group_of(p), 0) > 0:
            targets[t].append(p)

    # ---- tier 1 is available --------------------------------------------------------------
    if targets[1]:
        # random.random() gives 0.0 to 1.0. Below the pass chance (15%) = the team passes.
        if random.random() >= TIER1_PASS_CHANCE:
            return _choose(targets[1])          # takes an elite player
        # The team passed on tier 1: fall back to tier 2 if any exist...
        if targets[2]:
            return _choose(targets[2])
        # ...otherwise let the normal AI pick.
        return None

    # ---- no tier 1 left for this team: maybe tier 2 ----------------------------------------
    if targets[2] and random.random() >= TIER2_PASS_CHANCE:
        return _choose(targets[2])

    # No tiered pick this time.
    return None