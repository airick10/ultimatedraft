# python check_cap.py <draftname> <bb|bk|fb>
import json, sys
from pathlib import Path

def sal(p):
    raw = p.get("s_sal") or p.get("Salary") or 0
    try:
        return float(str(raw).replace("$", "").replace(",", "").strip())
    except ValueError:
        return 0.0

name, sport = sys.argv[1], sys.argv[2]
d = Path("drafts")
meta = json.load(open(d / f"{name}_{sport}_meta.json", encoding="utf-8"))
players = json.load(open(d / f"{name}_{sport}.json", encoding="utf-8"))
cap = float(str(meta.get("cap") or 0).replace("$", "").replace(",", "") or 0)
print(f"Cap: ${cap:,.0f}")
for t in meta["teams"]:
    mine = [p for p in players if p.get("team_id") == t["team_id"]]
    total = sum(sal(p) for p in mine)
    flag = "  <-- OVER" if cap and total > cap else ""
    print(f"{t['team_name']:<16}{t['type']:<7}{len(mine):>3} players  ${total:>14,.0f}{flag}")