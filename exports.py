"""
exports.py: Excel export for a baseball draft.

Per team, two sheets: "<Team>Hitters" and "<Team>Pitchers".
  row 1   headers
  row 2   column averages (live Excel formulas over the roster rows)
  row 3+  the roster, in draft order
Hitters sheet only, below the roster (after two blank rows):
  a projected lineup vs LHP, then one vs RHP. Each has a header row, an average row,
  then nine players in the order C, 1B, 2B, SS, 3B, LF, CF, RF, DH.
"""
import json
import math
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .ai import parse_salary
from .services import load_baseball_meta

# (header shown in Excel, key in the player JSON)
# Special keys: "__name__" = built name, "__spacer__" = empty narrow column, "__blank__" = empty column (PyScore)
HITTER_COLUMNS = [
    ("TM", "Team"), ("HITTERS", "__name__"), ("WAR", "s_war"),
    ("BAL", "s_bal"), ("INJ", "s_inj"), ("SALARY", "s_sal"), ("AB", "s_ab"),
    ("SO v lhp", "s_sovlhp"), ("BB v lhp", "s_bbvlhp"), ("HIT v lhp", "s_hitvlhp"), ("OB v lhp", "s_obvlhp"),
    ("TB v lhp", "s_tbvlhp"), ("OBTBvL", "s_obtbvl"), ("HR v lhp", "s_hrvlhp"), ("BP v lhp", "s_bpvlhp"),
    ("CL v lhp", "s_clvlhp"), ("DP v lhp", "s_dpvlhp"),
    ("SO v rhp", "s_sovrhp"), ("BB v rhp", "s_bbvrhp"), ("HIT v rhp", "s_hitvrhp"), ("OB v rhp", "s_obvrhp"),
    ("TB v rhp", "s_tbvrhp"), ("OBTBvR", "s_obtbvr"), ("HR v rhp", "s_hrvrhp"), ("BP v rhp", "s_bpvrhp"),
    ("CL v rhp", "s_clvrhp"), ("DP v rhp", "s_dpvrhp"),
    ("STEALING", "s_stealing"), ("STL", "s_stl"), ("SPD", "s_spd"), ("B", "s_b"), ("H", "s_h"),
    ("CA", "s_ca"), ("1B", "s_1b"), ("2B", "s_2b"), ("3B", "s_3b"), ("SS", "s_ss"),
    ("LF", "s_lf"), ("CF", "s_cf"), ("RF", "s_rf"), ("FIELDING", "s_fielding"),
]

PITCHER_COLUMNS = [
    ("TM", "Team"), ("PITCHERS", "__name__"), ("WAR", "s_war"),
    ("BAL", "s_bal"), ("SALARY", "s_sal"), ("IP", "s_ip"),
    ("SO v lhp", "s_sovlhp"), ("BB v lhp", "s_bbvlhp"), ("HIT v lhp", "s_hitvlhp"), ("OB v lhp", "s_obvlhp"),
    ("TB v lhp", "s_tbvlhp"), ("OBTBvL", "s_obtbvl"), ("HR v lhp", "s_hrvlhp"), ("BP v lhp", "s_bpvlhp"),
    ("DP v lhp", "s_dpvlhp"),
    ("SO v rhp", "s_sovrhp"), ("BB v rhp", "s_bbvrhp"), ("HIT v rhp", "s_hitvrhp"), ("OB v rhp", "s_obvrhp"),
    ("TB v rhp", "s_tbvrhp"), ("OBTBvR", "s_obtbvr"), ("HR v rhp", "s_hrvrhp"), ("BP v rhp", "s_bpvrhp"),
    ("DP v rhp", "s_dpvrhp"),
    ("HO", "s_ho"), ("ENDURANCE", "s_endurance"), ("FIELD", "s_field"), ("BK", "s_bk"), ("WP", "s_wp"),
    ("BAT-B", "s_bat_b"), ("STL", "s_stl"), ("SPD", "s_spd"),
]

# Which columns get a header and an average in each lineup block
L_KEYS = {"s_ab", "s_sovlhp", "s_bbvlhp", "s_hitvlhp", "s_obvlhp", "s_tbvlhp",
          "s_obtbvl", "s_hrvlhp", "s_bpvlhp", "s_clvlhp", "s_dpvlhp"}
R_KEYS = {"s_ab", "s_sovrhp", "s_bbvrhp", "s_hitvrhp", "s_obvrhp", "s_tbvrhp",
          "s_obtbvr", "s_hrvrhp", "s_bpvrhp", "s_clvrhp", "s_dpvrhp"}

NO_AVG_KEYS = {"Team", "__name__", "__spacer__", "__blank__"}
TEXT_KEYS = {"s_field"}
BOLD_KEYS   = {"s_obtbvl", "s_obtbvr"}

# lineup order, as you listed it
LINEUP_SLOTS = ["C", "1B", "2B", "SS", "3B", "LF", "CF", "RF", "DH"]
_FIELD_ABBR  = {"c": 0, "1b": 1, "2b": 2, "ss": 3, "3b": 4, "lf": 5, "cf": 6, "rf": 7}
DH_INDEX     = 8

AVG_FILL   = PatternFill("solid", fgColor="F2DCDB")
TOP_BORDER = Border(top=Side(style="thin", color="000000"))


# ---------- cell values ----------

def display_name(player, side):
    """Heim,J+  : LastName,FirstInitial then * (lefty) or + (switch hitter; hitters only)."""
    last    = (player.get("LastName") or "").strip()
    initial = (player.get("FirstName") or "").strip()[:1].upper()
    if side == "hitter":
        hand = (player.get("Bats") or "").strip().lower()
        mark = "*" if hand.startswith("l") else "+" if hand.startswith("s") else ""
    else:
        hand = (player.get("Throws") or "").strip().lower()
        mark = "*" if hand.startswith("l") else ""
    return f"{last},{initial}{mark}"


def cell_value(key, player):
    """Numbers become real numbers (so Excel can average them); text stays text."""
    raw = player.get(key)
    if raw is None:
        return None
    if key in TEXT_KEYS:
        return str(raw).strip() or None
    if key == "s_sal":
        return parse_salary(raw) if str(raw).strip() else None
    if isinstance(raw, (int, float)):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        number = float(text.replace(",", ""))
    except ValueError:
        return text
    return number if math.isfinite(number) else text


def _num(key, player):
    value = cell_value(key, player)
    return value if isinstance(value, (int, float)) else 0.0


# ---------- projected lineups ----------

def eligible_slots(player):
    """Lineup slot indexes this hitter can fill: every position in his fielding string, plus DH."""
    slots = {DH_INDEX}
    for token in (player.get("s_fielding") or "").split():
        for part in token.split("-")[0].strip().lower().split("/"):
            idx = _FIELD_ABBR.get(part)
            if idx is not None:
                slots.add(idx)
    return slots


def best_lineup(hitters, score_key):
    """Best 9-man lineup (list in LINEUP_SLOTS order; None = nobody could fill it).
    Maximizes the total of score_key with every hitter used at most once.
    Each filled slot is worth a big bonus, so the lineup is as full as possible
    before it is optimized for score."""
    BONUS = 10_000
    n = len(LINEUP_SLOTS)
    best = {0: (0.0, [])}                      # mask of filled slots -> (total, [(slot, hitter index)])
    for pi, player in enumerate(hitters):
        score = _num(score_key, player)
        elig  = eligible_slots(player)
        nxt   = dict(best)                     # option: this hitter sits
        for mask, (total, picks) in best.items():
            for si in elig:
                if mask & (1 << si):
                    continue
                new_mask  = mask | (1 << si)
                new_total = total + BONUS + score
                if new_mask not in nxt or new_total > nxt[new_mask][0]:
                    nxt[new_mask] = (new_total, picks + [(si, pi)])
        best = nxt
    top_mask = max(best, key=lambda m: best[m][0])
    lineup = [None] * n
    for si, pi in best[top_mask][1]:
        lineup[si] = hitters[pi]
    return lineup


# ---------- writing sheets ----------

def _col_width(key):
    return {
        "Team": 6, "__spacer__": 2.5, "__name__": 20, "__blank__": 10,
        "s_fielding": 38, "s_stealing": 17, "s_sal": 13,
    }.get(key, 9.5)


def _sheet_title(name, used):
    """Excel sheet names: max 31 characters, no [ ] : * ? / \\, and unique."""
    base = re.sub(r"[\[\]:*?/\\]", "", name)[:31] or "Sheet"
    title, n = base, 2
    while title in used:
        suffix = str(n)
        title = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(title)
    return title


def _write_player_row(ws, row, columns, player, side):
    for c, (header, key) in enumerate(columns, start=1):
        if key in ("__spacer__", "__blank__"):
            continue
        value = display_name(player, side) if key == "__name__" else cell_value(key, player)
        cell = ws.cell(row=row, column=c, value=value)
        if key == "s_sal":
            cell.number_format = "$#,##0"
        if key in TEXT_KEYS:
            cell.number_format = "@"
        if key in BOLD_KEYS:
            cell.font = Font(bold=True)


def _write_lineup_block(ws, columns, header_row, lineup, group_keys):
    # header row: black line across the table, headers for AB + this side's splits only
    for c, (header, key) in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=c)
        cell.border = TOP_BORDER
        if key in group_keys:
            cell.value = header
            cell.font = Font(bold=True)

    # average row: same columns, over the nine lineup rows
    avg_row = header_row + 1
    first   = header_row + 2
    last    = first + len(lineup) - 1
    for c, (header, key) in enumerate(columns, start=1):
        if key in group_keys:
            letter = get_column_letter(c)
            cell = ws.cell(row=avg_row, column=c,
                           value=f'=IFERROR(AVERAGE({letter}{first}:{letter}{last}),"")')
            cell.fill = AVG_FILL
            cell.font = Font(bold=True)
            cell.number_format = "0.0"

    # the nine players (an unfillable slot stays a blank row so the order never shifts)
    for i, player in enumerate(lineup):
        if player is not None:
            _write_player_row(ws, first + i, columns, player, "hitter")


def _write_sheet(ws, columns, players, side):
    roster_last = 2 + len(players)

    # row 1: headers
    for c, (header, key) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=c, value=header or None)
        cell.font = Font(bold=True)
        ws.column_dimensions[get_column_letter(c)].width = _col_width(key)

    # row 2: averages as live formulas over the roster rows
    for c, (header, key) in enumerate(columns, start=1):
        cell = ws.cell(row=2, column=c)
        cell.fill = AVG_FILL
        cell.font = Font(bold=True)
        if key in NO_AVG_KEYS or not players:
            continue
        letter = get_column_letter(c)
        cell.value = f'=IFERROR(AVERAGE({letter}3:{letter}{roster_last}),"")'
        cell.number_format = "$#,##0" if key == "s_sal" else "0.0"

    # rows 3+: the roster
    for r, player in enumerate(players, start=3):
        _write_player_row(ws, r, columns, player, side)

    # hitters only: projected lineups below the roster (two blank rows, then vs LHP, then vs RHP)
    if side == "hitter" and players:
        header_row = roster_last + 3
        for score_key, group in (("s_obtbvl", L_KEYS), ("s_obtbvr", R_KEYS)):
            lineup = best_lineup(players, score_key)
            _write_lineup_block(ws, columns, header_row, lineup, group)
            header_row += len(lineup) + 3          # header + average + players, then one blank row

    ws.freeze_panes = "C3"     # keeps the two top rows plus TM / spacer / name visible


def _is_starter(player):
    """Starter if his position is SP; relievers and closers go in the second group."""
    pos = (player.get("short_pos") or "").upper()
    if pos:
        return pos == "SP"
    return (player.get("s_endurance") or "").strip().upper().startswith("S")


def _write_avg_row(ws, columns, row, first, last, has_players):
    """A pink average row (live formulas) over rows first..last."""
    for c, (header, key) in enumerate(columns, start=1):
        cell = ws.cell(row=row, column=c)
        cell.fill = AVG_FILL
        cell.font = Font(bold=True)
        if key in NO_AVG_KEYS or not has_players:
            continue
        letter = get_column_letter(c)
        cell.value = f'=IFERROR(AVERAGE({letter}{first}:{letter}{last}),"")'
        cell.number_format = "$#,##0" if key == "s_sal" else "0.0"


def _write_pitcher_sheet(ws, columns, pitchers):
    """Row 1 headers, then starters (with their average row on top),
    one blank row, then relievers (with their average row on top)."""
    starters  = [p for p in pitchers if _is_starter(p)]
    relievers = [p for p in pitchers if not _is_starter(p)]

    # row 1: headers
    for c, (header, key) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=c, value=header or None)
        cell.font = Font(bold=True)
        ws.column_dimensions[get_column_letter(c)].width = _col_width(key)

    row = 2
    for group in (starters, relievers):
        avg_row = row
        first   = row + 1
        last    = row + len(group)
        _write_avg_row(ws, columns, avg_row, first, last, bool(group))
        for i, player in enumerate(group):
            _write_player_row(ws, first + i, columns, player, "pitcher")
        row = last + 2          # one blank row between the two groups

    ws.freeze_panes = "C3"

def build_bb_workbook(draftname):
    draft_dir = Path("drafts")
    meta = load_baseball_meta(draftname)

    with open(draft_dir / f"{draftname}_bb.json", "r", encoding="utf-8") as f:
        players = json.load(f)

    log = []
    log_path = draft_dir / f"{draftname}_bb_log.json"
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            log = json.load(f)
    pick_order = {str(e["id"]): i for i, e in enumerate(log)}

    wb = Workbook()
    wb.remove(wb.active)
    used = set()

    for team in meta["teams"]:
        mine = [p for p in players if p.get("team_id", 0) == team["team_id"]]
        mine.sort(key=lambda p: pick_order.get(str(p.get("id")), 10**9))
        hitters  = [p for p in mine if p.get("kind") == "hitter"]
        pitchers = [p for p in mine if p.get("kind") == "pitcher"]

        name = team["team_name"]
        _write_sheet(wb.create_sheet(_sheet_title(f"{name}Hitters", used)), HITTER_COLUMNS, hitters, "hitter")
        _write_pitcher_sheet(wb.create_sheet(_sheet_title(f"{name}Pitchers", used)), PITCHER_COLUMNS, pitchers)

    return wb