"""
berserker.py: Berserker mode for the AI drafters.

With Berserker mode on, 70% of each AI team's picks are random. The other 30% run the normal AI
(tiers, archetype, cap math, everything). A random pick is still legal: it fills a roster slot the
team really has open, and when a salary cap is on it only comes from players the team can afford
and still finish its roster with.
"""
import random

BERSERKER_RANDOM_CHANCE = 0.70      # share of AI picks that are random; the rest use the normal AI


def is_berserker(team):
    """Berserker is stored per AI team in the draft's meta file ("Berserker": true)."""
    return bool(team.get("Berserker"))


def berserker_roll():
    return random.random() < BERSERKER_RANDOM_CHANCE


def berserker_pick(candidates, open_labels, can_fill):
    """candidates:  undrafted players this team could take (already cap-checked).
    open_labels:    one entry per still-open roster slot.
    can_fill(p, label): True if player p may take a slot of that kind.
    Picks a random open slot (slots with more openings come up more often), then a random player
    for it. A FLEX slot is only tried after every other kind. Returns a player id, or None."""
    labels = list(open_labels)
    random.shuffle(labels)
    ordered = [l for l in labels if l != "FLEX"] + [l for l in labels if l == "FLEX"]

    tried = set()
    for label in ordered:
        if label in tried:
            continue
        tried.add(label)
        options = [p for p in candidates if can_fill(p, label)]
        if options:
            return random.choice(options).get("id")
    return None