import json, sys
from pathlib import Path

name, sport = sys.argv[1], sys.argv[2]
d = Path("drafts")
players = json.load(open(d / f"{name}_{sport}.json", encoding="utf-8"))
log = json.load(open(d / f"{name}_{sport}_log.json", encoding="utf-8"))
by_id = {str(e["id"]): e for e in log}

rows = []
for p in players:
    try:
        tier = int(float(str(p.get("tier", p.get("Tier"))).strip()))
    except (TypeError, ValueError):
        continue
    if tier not in (1, 2):
        continue
    e = by_id.get(str(p.get("id")))
    label = p.get("name") or f"{p.get('FirstName', '')} {p.get('LastName', '')}".strip()
    rows.append((tier, e["pick"] if e else 10**6, label, e["team"] if e else "undrafted", e["pos"] if e else ""))

for tier, pick, label, team, pos in sorted(rows):
    where = f"pick {pick:>3}" if pick < 10**6 else "not drafted"
    print(f"Tier {tier}  {label:<26}{pos:<5}{where:<12}{team}")