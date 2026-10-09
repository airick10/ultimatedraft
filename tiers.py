"""
tiers.py: tier-aware targeting for the AI drafters.

Players can carry a "tier" key in the JSON: 1 = elite, 2 = very good, anything else = untiered.
On each AI pick, tier 1 players that fit one of the team's open slots are targeted first,
then tier 2, with a chance that the team passes on them and picks the normal way.
"""
import random

from .cap import salary_of

TIER1_PASS_CHANCE = 0.15            # chance a team passes on tier 1 (and looks at tier 2 instead)
TIER2_PASS_CHANCE = 0.25            # chance a team passes on tier 2 once no tier 1 is left for it
PICK_WEIGHTS      = [40, 30, 20, 10]   # among the best-ranked targets, same spread as the rest of the AI


def tier_of(player):
    raw = player.get("tier", player.get("Tier"))
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def _choose(targets):
    """Highest salary first, with the usual weighted randomness over the top few."""
    ranked = sorted(targets, key=lambda p: (-salary_of(p), random.random()))
    top = ranked[:len(PICK_WEIGHTS)]
    return random.choices(top, weights=PICK_WEIGHTS[:len(top)])[0].get("id")


def tier_pick(candidates, group_of, open_groups):
    """candidates:  undrafted players this team could take (already cap-checked).
    group_of(p):    the position group a player belongs to.
    open_groups:    {group: number of still-open slots for that group}.
    Returns a player id, or None to fall through to the normal archetype logic."""
    targets = {1: [], 2: []}
    for p in candidates:
        t = tier_of(p)
        if t in targets and open_groups.get(group_of(p), 0) > 0:
            targets[t].append(p)

    if targets[1]:
        if random.random() >= TIER1_PASS_CHANCE:
            return _choose(targets[1])
        if targets[2]:
            return _choose(targets[2])
        return None

    if targets[2] and random.random() >= TIER2_PASS_CHANCE:
        return _choose(targets[2])
    return None