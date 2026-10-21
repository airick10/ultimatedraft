"""
check_cap.py  --  a command-line tool that reports each team's payroll for a saved draft.

HOW TO RUN (from the folder that contains the "drafts" folder)
    python check_cap.py <draftname> <bb|bk|fb>
    python check_cap.py FallLeague bb

WHAT YOU GET
    The cap, then one line per team: team name, human/ai, number of players, total salary, and
    "<-- OVER" if that team's payroll is above the cap. Use it after a draft to confirm the
    salary-cap logic held up.

NOTES
    - This is a stand-alone script. Nothing else in the project imports it.
    - It reads the draft's three saved files in "drafts/": the meta file (for the cap and the
      team list) and the player file (for who is on which team).
    - It has its own tiny salary reader (sal) rather than importing cap.py, so it also works
      when run from outside the package.
"""

import json, sys                 # json: read the saved files.  sys: read the command-line words.
from pathlib import Path         # handles file paths on any operating system


def sal(p):
    """
    PURPOSE:
        Read a player's salary as a number (same idea as salary_of() in cap.py, kept separate so
        this script has no dependency on the app).

    ARGUMENTS:
        p (dict) -- one player record from the draft's player file.

    CALLED BY:
        - check_cap.py: the team loop at the bottom of this file ("total = sum(sal(p) ...)").

    RETURNS:
        float -- the salary in dollars, or 0.0 if missing or unreadable.
    """
    # Baseball keeps salary in "s_sal", basketball/football in "Salary". "or 0" covers neither.
    raw = p.get("s_sal") or p.get("Salary") or 0
    try:
        # remove "$" and "," then convert
        return float(str(raw).replace("$", "").replace(",", "").strip())
    except ValueError:
        return 0.0


# --- read the two command-line words: the draft's name and the sport code -------------------
# python check_cap.py FallLeague bb   ->   sys.argv = ["check_cap.py", "FallLeague", "bb"]
name, sport = sys.argv[1], sys.argv[2]

# --- load the saved draft ---------------------------------------------------------------------
d = Path("drafts")                                                       # relative to where you run it
meta = json.load(open(d / f"{name}_{sport}_meta.json", encoding="utf-8"))      # settings + teams
players = json.load(open(d / f"{name}_{sport}.json", encoding="utf-8"))        # every player + team_id

# --- the cap ------------------------------------------------------------------------------------
# The cap is saved as text (like "100000000"), or "" for no cap. Strip "$" and "," and convert;
# the trailing "or 0" turns an empty string into 0, which means "no cap".
cap = float(str(meta.get("cap") or 0).replace("$", "").replace(",", "") or 0)
print(f"Cap: ${cap:,.0f}")

# --- one line per team ----------------------------------------------------------------------------
for t in meta["teams"]:
    # A player belongs to this team when his team_id matches (0 means undrafted).
    mine = [p for p in players if p.get("team_id") == t["team_id"]]

    # Add up this team's salaries.
    total = sum(sal(p) for p in mine)

    # Flag a team that's over the cap. "cap and ..." means: only flag when a cap exists.
    flag = "  <-- OVER" if cap and total > cap else ""

    # <16 = left-align in 16 characters, > = right-align, so the columns line up.
    print(f"{t['team_name']:<16}{t['type']:<7}{len(mine):>3} players  ${total:>14,.0f}{flag}")