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
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .ai import parse_salary
from .services import load_baseball_meta, load_basketball_meta, load_football_meta

from urllib.parse import quote

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
TEXT_KEYS = set()
BOLD_KEYS   = {"s_obtbvl", "s_obtbvr"}

SALARY_KEYS = {"s_sal", "Salary"}     # columns parsed from "$11,150,000" text into real numbers
KEY_ALIASES = {"C-O": ["C-0"], "s_Int": ["s_Int%"]}       # tolerate the zero spelling of C-O

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
        for alt in KEY_ALIASES.get(key, []):
            raw = player.get(alt)
            if raw is not None:
                break
    if raw is None:
        return None
    if key in TEXT_KEYS:
        return str(raw).strip() or None
    if key in SALARY_KEYS:
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
        cell.number_format = "$#,##0" if key in SALARY_KEYS else "0.0"


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



# ---------- basketball ----------

BK_KEYS = [
    "Team", "__name__", "Salary",
    "LG-O", "RG-O", "LF-O", "RF-O", "C-O",
    "LG-D", "RG-D", "LF-D", "RF-D", "C-D",
    "Rest", "Shoot", "Tend", "Fouls", "Assist", "Block", "3pt", "3ptR",
    "Omade", "Oopen", "Ofoul", "Oand1", "Oreplay", "Oblock",
    "Pmade", "Popen", "Pfoul", "Pand1", "Preplay", "Pblock",
    "Imade", "Iopen", "Ifoul", "Iand1", "Ireplay", "Iblock",
    "Fmade", "Fopen", "Ffoul", "Fand1", "Freplay", "Fblock",
    "FT",
    "PassSt", "PassT", "PassDazz", "PassOp", "PassPos",
    "FBPassT", "FBPassSt", "FBPassDazz", "FBPassShot",
    "Dsteal", "DPass1", "Dfoul", "Dpos", "DT",
    "XGoodO", "XGoodP", "XGoodI", "XGoodF",
    "XBlockO", "XBlockP", "XBlockI", "XBlockF",
]
# header = key name, except the name column
BK_COLUMNS = [("Name", k) if k == "__name__" else (k, k) for k in BK_KEYS]


def bk_name(player):
    """Uses a 'Name' key if the JSON has one, otherwise 'FirstName LastName'."""
    name = (player.get("Name") or "").strip()
    if name:
        return name
    return f"{player.get('FirstName', '')} {player.get('LastName', '')}".strip()


def _bk_width(header, key):
    if key == "Team":
        return 6
    if key == "__name__":
        return 20
    if key == "Salary":
        return 13
    return max(8, len(header) + 3)


def _write_bk_sheet(ws, players):
    last = 2 + len(players)

    # row 1: headers
    for c, (header, key) in enumerate(BK_COLUMNS, start=1):
        cell = ws.cell(row=1, column=c, value=header)
        cell.font = Font(bold=True)
        ws.column_dimensions[get_column_letter(c)].width = _bk_width(header, key)

    # row 2: averages over the roster rows
    _write_avg_row(ws, BK_COLUMNS, 2, 3, last, players)

    # rows 3+: the roster, stacked in draft order
    for r, player in enumerate(players, start=3):
        for c, (header, key) in enumerate(BK_COLUMNS, start=1):
            value = bk_name(player) if key == "__name__" else cell_value(key, player)
            cell = ws.cell(row=r, column=c, value=value)
            if key in SALARY_KEYS:
                cell.number_format = "$#,##0"

    ws.freeze_panes = "C3"     # keeps the header, average row, Team and Name visible


def build_bk_workbook(draftname):
    draft_dir = Path("drafts")
    meta = load_basketball_meta(draftname)

    with open(draft_dir / f"{draftname}_bk.json", "r", encoding="utf-8") as f:
        players = json.load(f)

    log = []
    log_path = draft_dir / f"{draftname}_bk_log.json"
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
        _write_bk_sheet(wb.create_sheet(_sheet_title(team["team_name"], used)), mine)

    return wb



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


# ---------- football ----------

def _stats(*names):
    """Column header = name, JSON key = 's_' + name (e.g. 'Cmp%' -> 's_Cmp%')."""
    return [(n, f"s_{n}") for n in names]


FB_PASS_STATS = _stats("QBRat", "Cmp%", "YpA", "Int", "YpMR", "MR", "SPR-C", "SPR-Y", "LPR-C", "LPR-Y")
FB_RUSH_STATS = _stats("RunBlock", "PassBlock", "YpRush", "Fum%", "LB-R", "OT-R", "ER-R", "FPR-C", "FPR-Y", "SPR-C")
FB_REC_STATS  = _stats("RunBlock", "PassBlock", "Rec%", "YpRec", "FPR-C", "FPR-Y", "SPR-C", "SPR-Y", "LPR-C", "LPR-Y")
FB_LINE_STATS = _stats("RunRating", "PassRating", "YdspPlay", "Run", "Pass", "Fum%", "Int%", "OLRun", "OLPass", "QBWRFum")
FB_SPECIAL_STATS = _stats("KO-TB", "K_XP", "X_FG33", "P_Avg", "KO_Avg", "KO_TD", "PR_Avg", "PR_TD",
                          "PenDiff%", "PuntCoverage", "KickCoverage")

# (header for the name column, stat columns, nominal row count, who belongs, how the name is built)
FB_SECTIONS = [
    ("PASSERS",      FB_PASS_STATS,    2, lambda p: p.get("kind") == "passer", "person"),
    ("RUSHERS",      FB_RUSH_STATS,    3, lambda p: p.get("kind") == "rusher", "person"),
    ("RECEIVERS",    FB_REC_STATS,     2, lambda p: p.get("kind") == "receiver" and p.get("short_pos") == "TE", "person"),
    ("RECEIVERS",    FB_REC_STATS,     4, lambda p: p.get("kind") == "receiver" and p.get("short_pos") != "TE", "person"),
    ("DEF/OFF LINE", FB_LINE_STATS,    1, lambda p: p.get("kind") == "dlineoline", "team"),
    ("SPECIAL",      FB_SPECIAL_STATS, 1, lambda p: p.get("kind") == "special", "team"),
]


def _fb_cell_value(key, player, name_mode):
    if key == "__tm__":
        return player.get("TM") or player.get("Team")
    if key == "__name__":
        if name_mode == "team":
            return f"{player.get('Year', '')} {player.get('Team', '')}".strip()
        last    = (player.get("LastName") or "").strip()
        initial = (player.get("FirstName") or "").strip()[:1].upper()
        return f"{last},{initial}"
    return cell_value(key, player)


def _write_fb_sheet(ws, players, pick_order):
    row = 1
    for title, stats, nominal, selector, name_mode in FB_SECTIONS:
        columns = [("TM", "__tm__"), (title, "__name__"), ("Positions", "Positions"), ("Salary", "Salary")] + stats

        group = [p for p in players if selector(p)]
        group.sort(key=lambda p: (
            1 if (title == "RUSHERS" and p.get("short_pos") != "HB") else 0,   # HBs before the FB
            pick_order.get(str(p.get("id")), 10**9),                           # then draft order
        ))

        # section header
        for c, (header, key) in enumerate(columns, start=1):
            ws.cell(row=row, column=c, value=header).font = Font(bold=True)
        row += 1

        # the players
        for player in group:
            for c, (header, key) in enumerate(columns, start=1):
                cell = ws.cell(row=row, column=c, value=_fb_cell_value(key, player, name_mode))
                if key in SALARY_KEYS:
                    cell.number_format = "$#,##0"
            row += 1

        row += max(0, nominal - len(group))    # short group: blank rows keep the layout fixed
        row += 1                               # blank row between sections

    # A=TM, B=name, C=Positions, D=Salary, then the stats
    for c in range(1, 16):
        ws.column_dimensions[get_column_letter(c)].width = {1: 6, 2: 20, 3: 11, 4: 13}.get(c, 12)


def build_fb_workbook(draftname):
    draft_dir = Path("drafts")
    meta = load_football_meta(draftname)

    with open(draft_dir / f"{draftname}_fb.json", "r", encoding="utf-8") as f:
        players = json.load(f)

    log = []
    log_path = draft_dir / f"{draftname}_fb_log.json"
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            log = json.load(f)
    pick_order = {str(e["id"]): i for i, e in enumerate(log)}

    wb = Workbook()
    wb.remove(wb.active)
    used = set()

    for team in meta["teams"]:
        mine = [p for p in players if p.get("team_id", 0) == team["team_id"]]
        _write_fb_sheet(wb.create_sheet(_sheet_title(team["team_name"], used)), mine, pick_order)

    return wb

# ---------- draft log (.txt), all sports ----------

SPORT_NAMES = {"bb": "Baseball", "bk": "Basketball", "fb": "Football"}
_META_LOADERS = {"bb": load_baseball_meta, "bk": load_basketball_meta, "fb": load_football_meta}

GROUP_BY_ROUND = True    # False = one flat list, exactly like the on-screen log


def build_log_text(draftname, sport):
    meta = _META_LOADERS[sport](draftname)
    with open(Path("drafts") / f"{draftname}_{sport}_log.json", "r", encoding="utf-8") as f:
        log = json.load(f)

    num_teams = meta.get("num_teams") or len(meta.get("teams", [])) or 1
    width = len(str(max((e.get("pick", 0) for e in log), default=0)))

    lines = [
        f"{draftname} - {SPORT_NAMES[sport]} Draft Log",
        f"Exported {datetime.now():%Y-%m-%d %H:%M}",
        "",
    ]

    current_round = None
    for e in log:
        if e.get("is_bonus"):                      # baseball two-way twin, shown under the main pick
            lines.append(f"{' ' * (width + 2)}↳ {e['team']} — {e['pos']} {e['player']} (two-way)")
            continue

        if GROUP_BY_ROUND:
            rnd = (e["pick"] - 1) // num_teams + 1
            if rnd != current_round:
                if current_round is not None:
                    lines.append("")
                lines.append(f"Round {rnd}")
                current_round = rnd

        lines.append(f"{e['pick']:>{width}}. {e['team']} — {e['pos']} {e['player']}")

    return "\n".join(lines) + "\n"

# ---------- baseball HTML report ----------

LOGO_ROOT = "https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/Logos"


def _to_float(value):
    """A number, or None. Handles '$1,200', '45%' and numeric text; anything else -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    text = str(value).strip().replace("$", "").replace(",", "").rstrip("%")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _fmt(v, style):
    if style == "int":
        return str(int(round(v)))
    if style == "rate":                          # .305 instead of 0.305
        s = f"{v:.3f}"
        return s[1:] if s.startswith("0.") else s
    if style == "d1":
        return f"{v:.1f}"
    if style == "d2":
        return f"{v:.2f}"
    if style == "auto3":
        return f"{v:.3f}".rstrip("0").rstrip(".")      # up to 3 decimals, trailing zeros trimmed
    if style == "money":
        return f"${v:,.0f}"
    return f"{v:.2f}".rstrip("0").rstrip(".")    # "auto": up to 2 decimals, trailing zeros trimmed


def _col(header, key, style="auto", strong=False):
    def get(p):
        v = _to_float(p.get(key))
        return (_fmt(v, style), v) if v is not None else ("—", None)
    return {"h": header, "kind": "num", "get": get, "strong": strong}


def _mixed(header, key, alt=None, kind="num", strong=False):
    """Numbers are formatted and sort numerically; text like '7*', 'w' or '1L' is shown as stored."""
    def get(p):
        raw = p.get(key)
        if raw is None and alt:
            raw = p.get(alt)
        v = _to_float(raw)
        if v is not None:
            return (_fmt(v, "auto"), v)
        text = str(raw).strip() if raw is not None else ""
        return (text or "—", text.lower() or None)
    return {"h": header, "kind": kind, "get": get, "strong": strong}


def _hand(header, key):
    def get(p):
        raw = str(p.get(key) or "").strip()
        return (raw[:1].upper() or "—", raw.lower() or None)
    return {"h": header, "kind": "text", "get": get, "strong": False}


def _salary(header="Salary"):
    def get(p):
        v = parse_salary(p.get("s_sal") or p.get("Salary"))
        return (_fmt(v, "money"), v) if v > 0 else ("—", None)
    return {"h": header, "kind": "num", "get": get, "strong": False}


def _wl(header="W-L"):
    def get(p):
        wins, losses = _to_float(p.get("p_w")), _to_float(p.get("p_l"))
        if wins is None and losses is None:
            return ("—", None)
        return (f"{int(wins or 0)}-{int(losses or 0)}", wins or 0)
    return {"h": header, "kind": "num", "get": get, "strong": False}


NAME_COL = {"h": "Name", "kind": "name"}
TEAM_COL = {"h": "Team", "kind": "team"}

REAL_HIT_COLS = [
    NAME_COL, TEAM_COL, _hand("Bats", "Bats"),
    _col("AB", "b_ab", "int"), _col("H", "b_h", "int"), _col("2B", "b_doubles", "int"),
    _col("3B", "b_triples", "int"), _col("HR", "b_hr", "int"), _col("RBI", "b_rbi", "int"),
    _col("R", "b_r", "int"), _col("SB", "b_sb", "int"), _col("CS", "b_cs", "int"),
    _col("TB", "b_tb", "int"),
    _col("Avg", "b_batting_avg", "rate"), _col("OBP", "b_onbase_perc", "rate"),
    _col("SLG", "b_slugging_perc", "rate"), _col("OPS", "b_onbase_plus_slugging", "rate"),
    _col("WAR", "b_war", "d1"), _salary(),
]

REAL_PIT_COLS = [
    NAME_COL, TEAM_COL, _hand("Throws", "Throws"),
    _col("IP", "p_ip", "d1"), _wl(), _col("SV", "p_sv", "int"), _col("R", "p_r", "int"),
    _col("ER", "p_er", "int"), _col("H", "p_h", "int"), _col("K", "p_so", "int"),
    _col("BB", "p_bb", "int"), _col("SHO", "p_sho", "int"), _col("CG", "p_cg", "int"),
    _col("ERA", "p_earned_run_avg", "d2"), _col("WHIP", "p_whip", "d2"), _col("FIP", "p_fip", "d2"),
    _col("Hp9", "p_hits_per_nine", "d1"), _col("HRp9", "p_hr_per_nine", "d1"),
    _col("Kp9", "p_so_per_nine", "d1"), _col("BBp9", "p_bb_per_nine", "d1"),
    _col("WAR", "p_war", "d1"), _salary(),
]

STRAT_HIT_COLS = [
    NAME_COL, TEAM_COL, _hand("Bats", "Bats"),
    _mixed("Balance", "s_bal", alt="b_bal"),
    _col("OBvL", "s_obvlhp"), _col("TBvL", "s_tbvlhp"), _col("OBTBvL", "s_obtbvl", strong=True),
    _col("HRvL", "s_hrvlhp"), _mixed("BPvL", "s_bpvlhp"),
    _col("OBvR", "s_obvrhp"), _col("TBvR", "s_tbvrhp"), _col("OBTBvR", "s_obtbvr", strong=True),
    _col("HRvR", "s_hrvrhp"), _mixed("BPvR", "s_bpvrhp"),
    _mixed("Stealing", "s_stealing", kind="text"), _col("Speed", "s_spd"),
    _mixed("Fielding", "s_fielding", kind="text"),
    _salary(), _col("WAR", "s_war", "d1"),
]

STRAT_PIT_COLS = [
    NAME_COL, TEAM_COL, _hand("Throws", "Throws"),
    _mixed("Balance", "s_bal", alt="b_bal"),
    _col("OBvL", "s_obvlhp"), _col("TBvL", "s_tbvlhp"), _col("OBTBvL", "s_obtbvl", strong=True),
    _col("HRvL", "s_hrvlhp"), _mixed("BPvL", "s_bpvlhp"),
    _col("OBvR", "s_obvrhp"), _col("TBvR", "s_tbvrhp"), _col("OBTBvR", "s_obtbvr", strong=True),
    _col("HRvR", "s_hrvrhp"), _mixed("BPvR", "s_bpvrhp"),
    _mixed("Endurance", "s_endurance", kind="text"),
    _salary(), _col("WAR", "s_war", "d1"),
]


def _head(cols):
    return [{"h": c["h"], "kind": c["kind"]} for c in cols]


_IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


def _logo_url(value, logo_dir):
    """Returns (image URL, short text) for a logo value that may be a code ('LAL'),
    a file name ('LAL.png'), or a full URL."""
    value = str(value or "").strip()
    if not value:
        return "", ""
    if value.lower().startswith(("http://", "https://")):
        name = value.rsplit("/", 1)[-1]
        return value, name.rsplit(".", 1)[0]
    if value.lower().endswith(_IMG_EXT):
        return f"{logo_dir}/{quote(value)}", value.rsplit(".", 1)[0]
    return f"{logo_dir}/{quote(value)}.png", value


def _report_row(columns, p, logo_dir=None, url_key="BaseballReferenceURL", team_key="Team"):
    logo_dir = logo_dir or f"{LOGO_ROOT}/seal"
    cells = []
    for col in columns:
        if col["kind"] == "name":
            if col.get("unit"):                          # football lines / special teams: "1985 CHI"
                name = f"{p.get('Year', '')} {p.get('Team', '')}".strip()
                url = ""
            else:
                name = f"{p.get('FirstName', '')} {p.get('LastName', '')}".strip()
                url = p.get(url_key) or ""
            cells.append({"kind": "name", "text": name, "sort": name.lower(), "url": url})
        elif col["kind"] == "team":
            logo, code = _logo_url(p.get(team_key), logo_dir)
            if not code and team_key != "Team":          # no value for that key: fall back to plain Team
                logo, code = _logo_url(p.get("Team"), logo_dir)
            cells.append({"kind": "team", "text": code, "sort": code.lower(), "logo": logo})
        else:
            text, sort = col["get"](p)
            cells.append({"kind": col["kind"], "text": text,
                          "sort": "" if sort is None else sort, "strong": col.get("strong", False)})
    return cells


def _slug(name, used):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "team"
    slug, n = base, 2
    while slug in used:
        slug = f"{base}-{n}"
        n += 1
    used.add(slug)
    return slug


def _load_draft(draftname, sport):
    """Meta, the saved player list, and a {player id: pick order} map."""
    draft_dir = Path("drafts")
    meta = _META_LOADERS[sport](draftname)

    with open(draft_dir / f"{draftname}_{sport}.json", "r", encoding="utf-8") as f:
        players = json.load(f)

    log = []
    log_path = draft_dir / f"{draftname}_{sport}_log.json"
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            log = json.load(f)
    pick_order = {str(e["id"]): i for i, e in enumerate(log)}
    return meta, players, pick_order


def _team_meta_line(parts, payroll, cap):
    if payroll > 0:
        text = f"Payroll {_fmt(payroll, 'money')}"
        if cap > 0:
            text += f" of {_fmt(cap, 'money')} cap"
        parts.append(text)
    return " · ".join(parts)


def build_bb_report_context(draftname):
    meta, players, pick_order = _load_draft(draftname, "bb")
    cap = parse_salary(meta.get("cap"))
    used = set()
    teams = []

    for team in meta["teams"]:
        mine = [p for p in players if p.get("team_id", 0) == team["team_id"]]
        mine.sort(key=lambda p: pick_order.get(str(p.get("id")), 10**9))
        hitters  = [p for p in mine if p.get("kind") == "hitter"]
        pitchers = [p for p in mine if p.get("kind") == "pitcher"]
        payroll  = sum(parse_salary(p.get("s_sal") or p.get("Salary")) for p in mine)
        name     = team["team_name"]

        teams.append({
            "name":     name,
            "slug":     "team-" + _slug(name, used),
            "is_human": team.get("type") == "human",
            "logo":     f"{LOGO_ROOT}/fictional/baseball/{quote(name)}_bb.png",
            "meta":     _team_meta_line([f"{len(hitters)} hitters", f"{len(pitchers)} pitchers"], payroll, cap),
            "sections": [
                {"cls": "real", "title": "Real Stats", "tables": [
                    {"label": "Hitters",  "cols": _head(REAL_HIT_COLS),
                     "rows": [_report_row(REAL_HIT_COLS, p) for p in hitters]},
                    {"label": "Pitchers", "cols": _head(REAL_PIT_COLS),
                     "rows": [_report_row(REAL_PIT_COLS, p) for p in pitchers]},
                ]},
                {"cls": "strat", "title": "Strat-O-Matic Ratings", "tables": [
                    {"label": "Hitters",  "cols": _head(STRAT_HIT_COLS),
                     "rows": [_report_row(STRAT_HIT_COLS, p) for p in hitters]},
                    {"label": "Pitchers", "cols": _head(STRAT_PIT_COLS),
                     "rows": [_report_row(STRAT_PIT_COLS, p) for p in pitchers]},
                ]},
            ],
        })

    return {
        "title":       draftname,
        "sport_label": "Baseball",
        "generated":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "teams":       teams,
    }

# ---------- basketball HTML report ----------

BK_SEAL_DIR = f"{LOGO_ROOT}/basketball"     # NBA team logos, same folder as the draft board uses


def _pair(header, key_o, key_d):
    """Shows two ratings as 'O/D' (a number, a slash, a number; not a division)."""
    def side(p, key):
        raw = p.get(key)
        if raw is None:
            for alt in KEY_ALIASES.get(key, []):
                raw = p.get(alt)
                if raw is not None:
                    break
        v = _to_float(raw)
        if v is not None:
            return _fmt(v, "auto"), v
        text = str(raw).strip() if raw is not None else ""
        return (text or "—"), None

    def get(p):
        o_text, o_val = side(p, key_o)
        d_text, d_val = side(p, key_d)
        if o_text == "—" and d_text == "—":
            return ("—", None)
        return (f"{o_text}/{d_text}", o_val)      # sorts by the first (offense) number

    return {"h": header, "kind": "num", "get": get, "strong": False}


BK_REAL_COLS = [
    NAME_COL, TEAM_COL,
    _col("FG", "fg", "int"), _col("FGA", "fga", "int"),
    _col("FG3", "fg3", "int"), _col("FG3A", "fg3a", "int"),
    _col("FT", "ft", "int"), _col("FTA", "fta", "int"),
    _col("RB", "trb", "int"), _col("Ast", "ast", "int"), _col("Pts", "pts", "int"),
    _col("FG%", "fg_pct", "rate"), _col("3P%", "fg3_pct", "rate"), _col("FT%", "ft_pct", "rate"),
    _col("PtspG", "ptspgm", "d1"), _col("RBpG", "rbspgm", "d1"), _col("AstpG", "astpgm", "d1"),
    _salary(),
]

BK_STRAT_COLS = [
    NAME_COL, TEAM_COL,
    _pair("LG-Reb", "LG-O", "LG-D"), _pair("RG-Reb", "RG-O", "RG-D"),
    _pair("LF-Reb", "LF-O", "LF-D"), _pair("RF-Reb", "RF-O", "RF-D"),
    _pair("C-Reb", "C-O", "C-D"),
    _mixed("Shoot", "Shoot"), _mixed("Tend", "Tend"), _mixed("Block", "Block"),
    _mixed("Omade", "Omade"), _mixed("Pmade", "Pmade"),
    _mixed("Imade", "Imade"), _mixed("Fmade", "Fmade"),
    _mixed("PassDazz", "PassDazz"), _mixed("FBPassDazz", "FBPassDazz"),
    _mixed("Dsteal", "Dsteal"),
    _salary(),
]


def build_bk_report_context(draftname):
    meta, players, pick_order = _load_draft(draftname, "bk")
    cap = parse_salary(meta.get("cap"))
    used = set()
    teams = []

    for team in meta["teams"]:
        mine = [p for p in players if p.get("team_id", 0) == team["team_id"]]
        mine.sort(key=lambda p: pick_order.get(str(p.get("id")), 10**9))
        payroll = sum(parse_salary(p.get("Salary")) for p in mine)
        name    = team["team_name"]

        def rows(cols):
            return [_report_row(cols, p, BK_SEAL_DIR, "BasketballReferenceURL", "Team_Logo") for p in mine]

        teams.append({
            "name":     name,
            "slug":     "team-" + _slug(name, used),
            "is_human": team.get("type") == "human",
            "logo":     f"{LOGO_ROOT}/fictional/basketball/{quote(name)}_bk.png",
            "meta":     _team_meta_line([f"{len(mine)} players"], payroll, cap),
            "sections": [
                {"cls": "real", "title": "Real Stats", "tables": [
                    {"label": "", "cols": _head(BK_REAL_COLS), "rows": rows(BK_REAL_COLS)},
                ]},
                {"cls": "strat", "title": "Strat-O-Matic Ratings", "tables": [
                    {"label": "", "cols": _head(BK_STRAT_COLS), "rows": rows(BK_STRAT_COLS)},
                ]},
            ],
        })

    return {
        "title":       draftname,
        "sport_label": "Basketball",
        "generated":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "teams":       teams,
    }

# ---------- football HTML report ----------

FB_SEAL_DIR = f"{LOGO_ROOT}/football"     # logos for the TM code on player rows
# line / special-team rows use their own Team_Logo value, relative to LOGO_ROOT (like basketball)

UNIT_NAME_COL = {"h": "Team", "kind": "name", "unit": True}      # shows "1985 CHI"
UNIT_LOGO_COL = {"h": "Logo", "kind": "team"}


def _fcol(header, key, alt=None, kind="num"):
    """Football column. Looks up key, then alt, then the capital-S spelling (S_...).
    Numbers show up to 3 decimals; text is shown as stored."""
    tries = [key] + ([alt] if alt else [])
    if key.startswith("s_"):
        tries.append("S_" + key[2:])

    def get(p):
        raw = None
        for k in tries:
            raw = p.get(k)
            if raw is not None:
                break
        v = _to_float(raw)
        if v is not None:
            return (_fmt(v, "auto3"), v)
        text = str(raw).strip() if raw is not None else ""
        return (text or "—", text.lower() or None)

    return {"h": header, "kind": kind, "get": get, "strong": False}


POS_COL        = _fcol("Position", "Positions", kind="text")
FB_PERSON_LEAD = [NAME_COL, TEAM_COL, POS_COL]
FB_UNIT_LEAD   = [UNIT_NAME_COL, UNIT_LOGO_COL, POS_COL]

FB_PASS_REAL = FB_PERSON_LEAD + [
    _fcol("Pass Attempts", "Attempts"), _fcol("Completion%", "CompPct"), _fcol("PassYards", "PassYards"),
    _fcol("PassTDs", "PassTDs"), _fcol("Int%", "IntPct"), _fcol("Rushes", "Rushes"),
    _fcol("RushYards", "RushYards"), _salary(),
]
FB_PASS_STRAT = FB_PERSON_LEAD + [
    _fcol("QBRating", "s_QBRat"), _fcol("Completion%", "s_Cmp%"), _fcol("Yds/Attempt", "s_YpA"),
    _fcol("Int%", "s_Int%", alt="s_Int"), _fcol("Yds/MustRun", "s_YpMR"), _fcol("Must Run", "s_MR"),
    _fcol("ShortPassCompletion", "s_SPR-C"), _fcol("ShortPassYards", "s_SPR-Y"),
    _fcol("LongPassCompletion", "s_LPR-C"), _fcol("LongPassYards", "s_LPR-Y"), _salary(),
]

FB_RUSH_REAL = FB_PERSON_LEAD + [
    _fcol("Rushes", "Rushes"), _fcol("RushYards", "RushYards"), _fcol("RushTDs", "RushTDs"),
    _fcol("RushingAverage", "RushAvg"), _fcol("Receptions", "Receptions"),
    _fcol("RecYards", "RecYards"), _fcol("RecTDs", "RecTDs"), _salary(),
]
FB_RUSH_STRAT = FB_PERSON_LEAD + [
    _fcol("Run Block", "s_RunBlock"), _fcol("Pass Block", "s_PassBlock"), _fcol("Yds/Rush", "s_YpRush"),
    _fcol("Fum%", "s_Fum%"), _fcol("LineBuck", "s_LB-R"), _fcol("OffTable", "s_OT-R"),
    _fcol("End Run", "s_ER-R"), _fcol("FlatPassCatches", "s_FPR-C"), _fcol("FlatPassYards", "s_FPR-Y"),
    _fcol("ShortPassCatches", "s_SPR-C"), _salary(),
]

FB_REC_REAL = FB_PERSON_LEAD + [
    _fcol("Receptions", "Receptions"), _fcol("RecYards", "RecYards"), _fcol("RecTDs", "RecTDs"), _salary(),
]
FB_REC_STRAT = FB_PERSON_LEAD + [
    _fcol("Run Block", "s_RunBlock"), _fcol("Pass Block", "s_PassBlock"), _fcol("Rec%", "s_Rec%"),
    _fcol("Yds/Rec", "s_YpRec"), _fcol("FlatPassCatches", "s_FPR-C"), _fcol("FlatPassYards", "s_FPR-Y"),
    _fcol("ShortPassCatches", "s_SPR-C"), _fcol("ShortPassYards", "s_SPR-Y"),
    _fcol("LongPassCatches", "s_LPR-C"), _fcol("LongPassYards", "s_LPR-Y"), _salary(),
]

FB_LINE_REAL = FB_UNIT_LEAD + [
    _fcol("Yds/Play", "s_YdspPlay"), _fcol("DvsRun", "s_Run"), _fcol("DvsPass", "s_Pass"),
    _fcol("OLvsRun", "s_OLRun"), _fcol("OLvsPass", "s_OLPass"),
    _fcol("Fum%", "s_Fum%"), _fcol("Int%", "s_Int%"), _salary(),
]
FB_LINE_STRAT = FB_UNIT_LEAD + [
    _fcol("Yds/Play", "s_YdspPlay"), _fcol("DvsRun", "s_Run"), _fcol("DvsPass", "s_Pass"),
    _fcol("OLvsRun", "s_OLRun"), _fcol("OLvsPass", "s_OLPass"),
    _fcol("RunRating", "s_RunRating"), _fcol("PassRating", "s_PassRating"), _salary(),
]

FB_SPECIAL_REAL = FB_UNIT_LEAD + [
    _fcol("TouchBacks", "s_KO-TB"), _fcol("XP", "s_K_XP"), _fcol("FG33", "s_X_FG33"),
    _fcol("PuntAverage", "s_P_Avg"), _fcol("KRAvg", "s_KO_Avg"), _fcol("KRTD", "s_KO_TD"),
    _fcol("PRAvg", "s_PR_Avg"), _fcol("PRTD", "s_PR_TD"), _salary(),
]
FB_SPECIAL_STRAT = FB_UNIT_LEAD + [
    _fcol("TouchBacks", "s_KO-TB"), _fcol("XP", "s_K_XP"), _fcol("FG33", "s_X_FG33"),
    _fcol("PuntAverage", "s_P_Avg"), _fcol("Penalties", "s_PenDiff%"),
    _fcol("PuntCoverage", "s_PuntCoverage"), _fcol("KickCoverage", "s_KickCoverage"), _salary(),
]

# (table label, who belongs, real columns, strat columns, row style)
FB_REPORT_GROUPS = [
    ("Passers", lambda p: p.get("kind") == "passer", FB_PASS_REAL, FB_PASS_STRAT, "person"),
    ("Rushers (HB / FB)", lambda p: p.get("kind") == "rusher", FB_RUSH_REAL, FB_RUSH_STRAT, "person"),
    ("Tight Ends",
     lambda p: p.get("kind") == "receiver" and p.get("short_pos") == "TE", FB_REC_REAL, FB_REC_STRAT, "person"),
    ("Wide Receivers",
     lambda p: p.get("kind") == "receiver" and p.get("short_pos") != "TE", FB_REC_REAL, FB_REC_STRAT, "person"),
    ("Defense / Offensive Line", lambda p: p.get("kind") == "dlineoline", FB_LINE_REAL, FB_LINE_STRAT, "unit"),
    ("Special", lambda p: p.get("kind") == "special", FB_SPECIAL_REAL, FB_SPECIAL_STRAT, "unit"),
]


def build_fb_report_context(draftname):
    meta, players, pick_order = _load_draft(draftname, "fb")
    cap = parse_salary(meta.get("cap"))
    used = set()
    teams = []

    for team in meta["teams"]:
        mine = [p for p in players if p.get("team_id", 0) == team["team_id"]]
        mine.sort(key=lambda p: (
            1 if (p.get("kind") == "rusher" and p.get("short_pos") != "HB") else 0,   # HBs before the FB
            pick_order.get(str(p.get("id")), 10**9),
        ))
        payroll = sum(parse_salary(p.get("Salary")) for p in mine)
        name    = team["team_name"]

        real_tables, strat_tables = [], []
        for label, selector, real_cols, strat_cols, style in FB_REPORT_GROUPS:
            group = [p for p in mine if selector(p)]
            team_key, logo_dir = ("TM", FB_SEAL_DIR) if style == "person" else ("Team_Logo", FB_SEAL_DIR)
            real_tables.append({
                "label": label, "cols": _head(real_cols),
                "rows": [_report_row(real_cols, p, logo_dir, "FootballReferenceURL", team_key) for p in group],
            })
            strat_tables.append({
                "label": label, "cols": _head(strat_cols),
                "rows": [_report_row(strat_cols, p, logo_dir, "FootballReferenceURL", team_key) for p in group],
            })

        teams.append({
            "name":     name,
            "slug":     "team-" + _slug(name, used),
            "is_human": team.get("type") == "human",
            "logo":     f"{LOGO_ROOT}/fictional/football/{quote(name)}_fb.png",
            "meta":     _team_meta_line([f"{len(mine)} players"], payroll, cap),
            "sections": [
                {"cls": "real",  "title": "Real Stats",            "tables": real_tables},
                {"cls": "strat", "title": "Strat-O-Matic Ratings", "tables": strat_tables},
            ],
        })

    return {
        "title":       draftname,
        "sport_label": "Football",
        "generated":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "teams":       teams,
    }