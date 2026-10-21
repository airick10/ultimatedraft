"""
berserker.py  --  Berserker mode for the AI drafters.

WHAT BERSERKER MODE DOES
    With Berserker mode on, 70% of each AI team's picks are RANDOM. The other 30% run the normal
    AI (tiers, archetype, cap math, everything), so teams still show flashes of intelligence.

    A random pick is still LEGAL:
      - it fills a roster slot the team really has open (no 8th catcher),
      - when a salary cap is on, it only comes from players the team can afford AND still finish
        its roster with (the candidate list is already cap-checked by the caller).

HOW IT IS TURNED ON
    On the setup page ("Berserker mode: On"). The choice is saved in the draft's meta file as
    "berserker": true, and every AI team gets "Berserker": true. Human teams never get the flag,
    so a human whose pick clock runs out still gets a sensible auto-pick. You can also hand-edit
    "Berserker": true onto a single team in the meta file for a one-team berserker.

WHO USES THIS FILE
    - ai.py: ai_select_bb, ai_select_bk and ai_select_fb. Each calls is_berserker() and
      berserker_roll(), and if both say yes, calls berserker_pick() with that sport's own
      "can this player fill this slot?" helper (can_fill_bb / can_fill_bk / can_fill_fb).
"""

import random      # for the 70% roll, the slot shuffle, and the random player choice


# The share of AI picks that are random. 0.70 = 70% random, 30% normal AI.
# Change this one number to make Berserker milder (0.5) or even wilder (0.9).
BERSERKER_RANDOM_CHANCE = 0.70


def is_berserker(team):
    """
    PURPOSE:
        Say whether Berserker mode is switched on for this team.

    ARGUMENTS:
        team (dict) -- one team entry from the draft's meta file (it may contain "Berserker").

    CALLED BY:
        - ai.py: ai_select_bb, ai_select_bk, ai_select_fb (first thing in the Berserker check).

    RETURNS:
        bool -- True if the team has "Berserker": true. False if the key is missing (drafts made
                before Berserker existed) or false.
    """
    return bool(team.get("Berserker"))


def berserker_roll():
    """
    PURPOSE:
        Roll the dice for ONE pick: is this particular pick random (True) or does it go through
        the normal AI (False)?

    ARGUMENTS:
        none

    CALLED BY:
        - ai.py: ai_select_bb, ai_select_bk, ai_select_fb (right after is_berserker()).

    RETURNS:
        bool -- True about 70% of the time (see BERSERKER_RANDOM_CHANCE).
    """
    # random.random() is a number from 0.0 up to (not including) 1.0.
    # "< 0.70" is true for roughly 70% of rolls.
    return random.random() < BERSERKER_RANDOM_CHANCE


def berserker_pick(candidates, open_labels, can_fill):
    """
    PURPOSE:
        Make the random pick. It works in two random steps so teams stay legal:
          1. pick a random open roster slot, then
          2. pick a random player who can fill that slot.
        Picking the slot first (instead of a random player from the whole pool) keeps teams
        from drafting, say, 20 hitters just because there are more hitters than pitchers in the
        pool. Slots with more openings come up more often, so a team missing 3 catchers is more
        likely to be sent after a catcher than one missing 1.

    ARGUMENTS:
        candidates  (list[dict]) -- undrafted players this team may take (already cap-checked).
        open_labels (list[str])  -- one label per still-open roster slot, duplicates included
                                    (["C", "C", "UT", "UT", "UT", "S", ...]).
        can_fill    (function)   -- can_fill(player, label) -> bool. Each sport supplies its own
                                    (can_fill_bb / can_fill_bk / can_fill_fb in ai.py).

    CALLED BY:
        - ai.py: ai_select_bb, ai_select_bk, ai_select_fb.

    RETURNS:
        str | None -- the "id" of the randomly chosen player, or None if no open slot has any
                      eligible player (the caller then falls back to the normal AI).
    """
    # Shuffle a copy so the order of the open slots is random. Because duplicates stay in the
    # list, a slot type with more openings is more likely to land in front.
    labels = list(open_labels)
    random.shuffle(labels)

    # FLEX is a catch-all slot (it takes anybody), so it should only be used when nothing else
    # works. Put every FLEX at the very end of the order.
    ordered = [l for l in labels if l != "FLEX"] + [l for l in labels if l == "FLEX"]

    tried = set()                       # slot kinds we've already looked at
    for label in ordered:
        if label in tried:
            continue                    # already tried this kind of slot; skip the duplicate
        tried.add(label)

        # Everyone who could legally fill this kind of slot.
        options = [p for p in candidates if can_fill(p, label)]
        if options:
            # The random part: any eligible player, equal chance.
            return random.choice(options).get("id")

    # No open slot had a single eligible player.
    return None