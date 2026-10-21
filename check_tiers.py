"""
check_tiers.py  --  a command-line tool that shows where every tiered player ended up.

HOW TO RUN (from the folder that contains the "drafts" folder)
    python check_tiers.py <draftname> <bb|bk|fb>
    python check_tiers.py FallLeague bb

WHAT YOU GET
    One line per tier 1 and tier 2 player, sorted by tier and then by pick number:
        Tier 1  Babe Ruth                 DH   pick   3   Badgers
        Tier 2  Some Player               SS   not drafted  undrafted
    It is the quickest way to see whether the tier system is behaving: elite players should go
    early, but not ALWAYS first (the teams sometimes pass; see tiers.py).

NOTES
    - A stand-alone script. Nothing else in the project imports it.
    - It repeats the tier-reading logic from tiers.py (tier_of) instead of importing it, so it
      works from outside the package.
    - Players with no tier, or a tier other than 1 or 2, are ignored.
"""

import json, sys                 # json: read the saved files.  sys: read the command-line words.
from pathlib import Path         # handles file paths on any operating system

# --- read the two command-line words: the draft's name and the sport code -------------------------
name, sport = sys.argv[1], sys.argv[2]

# --- load the saved draft ------------------------------------------------------------------------------
d = Path("drafts")                                                                      # relative to where you run it
players = json.load(open(d / f"{name}_{sport}.json", encoding="utf-8"))               # every player in the pool
log = json.load(open(d / f"{name}_{sport}_log.json", encoding="utf-8"))                # the pick-by-pick log

# Quick lookup: player id (as text) -> his log entry (which pick, which team, which position).
by_id = {str(e["id"]): e for e in log}

# --- collect one row for every tier 1 / tier 2 player ----------------------------------------------------
rows = []
for p in players:
    # Read the tier the same forgiving way tiers.tier_of() does: "tier" or "Tier", number or text.
    try:
        tier = int(float(str(p.get("tier", p.get("Tier"))).strip()))
    except (TypeError, ValueError):
        continue                       # no readable tier: skip this player

    if tier not in (1, 2):
        continue                       # only tiers 1 and 2 are interesting

    e = by_id.get(str(p.get("id")))    # his log entry, or None if he was never drafted

    # Basketball defense / football units have a "name"; people have FirstName + LastName.
    label = p.get("name") or f"{p.get('FirstName', '')} {p.get('LastName', '')}".strip()

    # (tier, pick number, name, team, position). 10**6 is a huge pick number for undrafted
    # players, so they sort to the bottom of each tier.
    rows.append((tier, e["pick"] if e else 10**6, label,
                 e["team"] if e else "undrafted", e["pos"] if e else ""))

# --- print, sorted by tier then pick number ------------------------------------------------------------------
for tier, pick, label, team, pos in sorted(rows):
    where = f"pick {pick:>3}" if pick < 10**6 else "not drafted"
    # <26 and <5 and <12 pad each piece so the columns line up.
    print(f"Tier {tier}  {label:<26}{pos:<5}{where:<12}{team}")