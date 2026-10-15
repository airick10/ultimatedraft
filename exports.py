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
from .services import load_baseball_meta, load_basketball_meta, load_football_meta, unit_label

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
            return unit_label(player) or str(player.get("name") or "")
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
    return {"h": header, "kind": "num", "get": get, "strong": strong, "style": style}


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
    return {"h": header, "kind": kind, "get": get, "strong": strong, "style": "auto"}


def _hand(header, key):
    def get(p):
        raw = str(p.get(key) or "").strip()
        return (raw[:1].upper() or "—", raw.lower() or None)
    return {"h": header, "kind": "text", "get": get, "strong": False}


def _salary(header="Salary"):
    def get(p):
        v = parse_salary(p.get("s_sal") or p.get("Salary"))
        return (_fmt(v, "money"), v) if v > 0 else ("—", None)
    return {"h": header, "kind": "num", "get": get, "strong": False, "style": "money"}


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
            if col.get("unit"):                  # football lines / special teams, basketball defenses: "1985 CHI"
                name = unit_label(p) or str(p.get("name") or "").strip()
            else:
                name = f"{p.get('FirstName', '')} {p.get('LastName', '')}".strip() or str(p.get("name") or "").strip()
            cells.append({"kind": "name", "text": name, "sort": name.lower(), "url": p.get(url_key) or ""})
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

    return {"h": header, "kind": kind, "get": get, "strong": False, "style": "auto3"}


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


# ---------- per-team JSON (baseball) ----------

APP_FIELDS = ("kind", "short_pos", "id", "team_id")    # fields the app adds; the source JSON files don't have them


def build_team_records(draftname, team_id, kind):
    """A team's drafted hitters or pitchers as plain records, shaped like the source JSON files:
    a list of records with the original ID and every original key, minus the app's own bookkeeping."""
    draft_dir = Path("drafts")
    with open(draft_dir / f"{draftname}_bb.json", "r", encoding="utf-8") as f:
        players = json.load(f)

    log = []
    log_path = draft_dir / f"{draftname}_bb_log.json"
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            log = json.load(f)
    pick_order = {str(e["id"]): i for i, e in enumerate(log)}

    want = "hitter" if kind == "hitters" else "pitcher"
    mine = [p for p in players if p.get("team_id", 0) == team_id and p.get("kind") == want]
    mine.sort(key=lambda p: pick_order.get(str(p.get("id")), 10**9))
    return [{k: v for k, v in p.items() if k not in APP_FIELDS} for p in mine]

# ---------- totals / averages rows and the report builders ----------

def _avg_map(headers):
    return {h: "avg" for h in headers}


def _num_at(row, i):
    v = row[i].get("sort")
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _foot_row(columns, rows, agg_map, label):
    """Footer row for a table: sums for counting stats and weighted averages for rates (real stats),
    plain averages for ratings (strat). Returns None for tables with fewer than two players."""
    if not agg_map or len(rows) < 2:
        return None
    heads = [c["h"] for c in columns]
    cells = []
    for i, col in enumerate(columns):
        agg   = agg_map.get(col["h"]) if i > 0 else None
        style = col.get("style", "auto")
        text  = label if i == 0 else ""

        if agg == "sum":
            vals = [v for v in (_num_at(r, i) for r in rows) if v is not None]
            if vals:
                text = _fmt(sum(vals), style)
        elif agg == "avg":
            vals = [v for v in (_num_at(r, i) for r in rows) if v is not None]
            if vals:
                text = _fmt(sum(vals) / len(vals), "d1")
        elif agg == "wl":
            wins = losses = 0
            found = False
            for r in rows:
                m = re.match(r"\s*(\d+)\s*-\s*(\d+)", r[i]["text"])
                if m:
                    wins += int(m.group(1))
                    losses += int(m.group(2))
                    found = True
            if found:
                text = f"{wins}-{losses}"
        elif agg == "pair":
            pairs = [re.match(r"\s*(-?[\d.]+)\s*/\s*(-?[\d.]+)", r[i]["text"]) for r in rows]
            pairs = [m for m in pairs if m]
            if pairs:
                o = sum(float(m.group(1)) for m in pairs) / len(pairs)
                d = sum(float(m.group(2)) for m in pairs) / len(pairs)
                text = f"{_fmt(o, 'd1')}/{_fmt(d, 'd1')}"
        elif isinstance(agg, tuple) and agg[0] == "wavg" and agg[1] in heads:
            w_i = heads.index(agg[1])
            num = den = 0.0
            for r in rows:
                v, w = _num_at(r, i), _num_at(r, w_i)
                if v is not None and w:
                    num += v * w
                    den += w
            if den:
                text = _fmt(num / den, style)

        cells.append({"kind": "name" if i == 0 else col["kind"], "text": text})
    return cells


def _table(label, cols, group, agg_map, foot_label, **row_kw):
    rows = [_report_row(cols, p, **row_kw) for p in group]
    return {"label": label, "cols": _head(cols), "rows": rows,
            "foot": _foot_row(cols, rows, agg_map, foot_label)}


# ---- what gets totalled (real stats) or averaged (strat), by column header ----

REAL_HIT_AGG = {
    "AB": "sum", "H": "sum", "2B": "sum", "3B": "sum", "HR": "sum", "RBI": "sum", "R": "sum",
    "SB": "sum", "CS": "sum", "TB": "sum",
    "Avg": ("wavg", "AB"), "OBP": ("wavg", "AB"), "SLG": ("wavg", "AB"), "OPS": ("wavg", "AB"),
    "WAR": "sum", "Salary": "sum",
}
REAL_PIT_AGG = {
    "IP": "sum", "W-L": "wl", "SV": "sum", "R": "sum", "ER": "sum", "H": "sum", "K": "sum", "BB": "sum",
    "SHO": "sum", "CG": "sum",
    "ERA": ("wavg", "IP"), "WHIP": ("wavg", "IP"), "FIP": ("wavg", "IP"),
    "Hp9": ("wavg", "IP"), "HRp9": ("wavg", "IP"), "Kp9": ("wavg", "IP"), "BBp9": ("wavg", "IP"),
    "WAR": "sum", "Salary": "sum",
}
STRAT_HIT_AVG = _avg_map(["OBvL", "TBvL", "OBTBvL", "HRvL", "BPvL", "OBvR", "TBvR", "OBTBvR", "HRvR", "BPvR", "Speed"])
STRAT_PIT_AVG = _avg_map(["OBvL", "TBvL", "OBTBvL", "HRvL", "BPvL", "OBvR", "TBvR", "OBTBvR", "HRvR", "BPvR"])

BK_REAL_AGG = {
    "FG": "sum", "FGA": "sum", "FG3": "sum", "FG3A": "sum", "FT": "sum", "FTA": "sum",
    "RB": "sum", "Ast": "sum", "Pts": "sum",
    "FG%": ("wavg", "FGA"), "3P%": ("wavg", "FG3A"), "FT%": ("wavg", "FTA"),
    "PtspG": "sum", "RBpG": "sum", "AstpG": "sum", "Salary": "sum",
}
BK_STRAT_AVG = {
    **{h: "pair" for h in ("LG-Reb", "RG-Reb", "LF-Reb", "RF-Reb", "C-Reb")},
    **_avg_map(["Shoot", "Tend", "Block", "Omade", "Pmade", "Imade", "Fmade", "PassDazz", "FBPassDazz", "Dsteal"]),
}

_FB_REC_REAL  = {"Receptions": "sum", "RecYards": "sum", "RecTDs": "sum", "Salary": "sum"}
_FB_REC_STRAT = _avg_map(["Run Block", "Pass Block", "Rec%", "Yds/Rec", "FlatPassCatches", "FlatPassYards",
                          "ShortPassCatches", "ShortPassYards", "LongPassCatches", "LongPassYards"])
FB_REAL_AGG = {
    "Passers": {"Pass Attempts": "sum", "PassYards": "sum", "PassTDs": "sum", "Rushes": "sum", "RushYards": "sum",
                "Completion%": ("wavg", "Pass Attempts"), "Int%": ("wavg", "Pass Attempts"), "Salary": "sum"},
    "Rushers (HB / FB)": {"Rushes": "sum", "RushYards": "sum", "RushTDs": "sum", "Receptions": "sum",
                          "RecYards": "sum", "RecTDs": "sum", "RushingAverage": ("wavg", "Rushes"), "Salary": "sum"},
    "Tight Ends": _FB_REC_REAL,
    "Wide Receivers": _FB_REC_REAL,
}
FB_STRAT_AVG = {
    "Passers": _avg_map(["QBRating", "Completion%", "Yds/Attempt", "Int%", "Yds/MustRun", "Must Run",
                         "ShortPassCompletion", "ShortPassYards", "LongPassCompletion", "LongPassYards"]),
    "Rushers (HB / FB)": _avg_map(["Run Block", "Pass Block", "Yds/Rush", "Fum%", "LineBuck", "OffTable",
                                   "End Run", "FlatPassCatches", "FlatPassYards", "ShortPassCatches"]),
    "Tight Ends": _FB_REC_STRAT,
    "Wide Receivers": _FB_REC_STRAT,
}

# basketball defense units get their own table (year + team, logo, their own ratings)
BK_DEF_COLS = [
    UNIT_NAME_COL, UNIT_LOGO_COL,
    _mixed("Omade", "Omade"), _mixed("OT", "OT"), _mixed("Pmade", "Pmade"), _mixed("PDfoul", "PDfoul"),
    _mixed("POFoul", "POFoul"), _mixed("PT", "PT"), _mixed("Imade", "Imade"), _mixed("Iopen", "Iopen"),
    _mixed("Fmade", "Fmade"), _mixed("3made", "3made"),
    _salary(),
]


# ---- the three builders ----

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
            "team_id":  team["team_id"],
            "slug":     "team-" + _slug(name, used),
            "is_human": team.get("type") == "human",
            "logo":     f"{LOGO_ROOT}/fictional/baseball/{quote(name)}_bb.png",
            "meta":     _team_meta_line([f"{len(hitters)} hitters", f"{len(pitchers)} pitchers"], payroll, cap),
            "sections": [
                {"cls": "real", "title": "Real Stats", "tables": [
                    _table("Hitters",  REAL_HIT_COLS, hitters,  REAL_HIT_AGG, "Total"),
                    _table("Pitchers", REAL_PIT_COLS, pitchers, REAL_PIT_AGG, "Total"),
                ]},
                {"cls": "strat", "title": "Strat-O-Matic Ratings", "tables": [
                    _table("Hitters",  STRAT_HIT_COLS, hitters,  STRAT_HIT_AVG, "Average"),
                    _table("Pitchers", STRAT_PIT_COLS, pitchers, STRAT_PIT_AVG, "Average"),
                ]},
            ],
        })

    return {
        "title":       draftname,
        "sport_label": "Baseball",
        "generated":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "teams":       teams,
    }


def build_bk_report_context(draftname):
    meta, players, pick_order = _load_draft(draftname, "bk")
    cap = parse_salary(meta.get("cap"))
    used = set()
    teams = []

    for team in meta["teams"]:
        mine = [p for p in players if p.get("team_id", 0) == team["team_id"]]
        mine.sort(key=lambda p: pick_order.get(str(p.get("id")), 10**9))
        squad    = [p for p in mine if p.get("kind") != "defense"]
        defenses = [p for p in mine if p.get("kind") == "defense"]
        payroll  = sum(parse_salary(p.get("Salary")) for p in mine)
        name     = team["team_name"]
        kw = dict(logo_dir=BK_SEAL_DIR, url_key="BasketballReferenceURL", team_key="Team_Logo")

        parts = [f"{len(squad)} players"] + ([f"{len(defenses)} defense"] if defenses else [])
        strat_tables = [_table("Players" if defenses else "", BK_STRAT_COLS, squad, BK_STRAT_AVG, "Average", **kw)]
        if defenses:
            strat_tables.append(_table("Defense", BK_DEF_COLS, defenses, {}, "", **kw))

        teams.append({
            "name":     name,
            "slug":     "team-" + _slug(name, used),
            "is_human": team.get("type") == "human",
            "logo":     f"{LOGO_ROOT}/fictional/basketball/{quote(name)}_bk.png",
            "meta":     _team_meta_line(parts, payroll, cap),
            "sections": [
                {"cls": "real", "title": "Real Stats", "tables": [
                    _table("", BK_REAL_COLS, squad, BK_REAL_AGG, "Total", **kw),
                ]},
                {"cls": "strat", "title": "Strat-O-Matic Ratings", "tables": strat_tables},
            ],
        })

    return {
        "title":       draftname,
        "sport_label": "Basketball",
        "generated":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "teams":       teams,
    }


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
            kw = dict(logo_dir=FB_SEAL_DIR, url_key="FootballReferenceURL",
                      team_key="TM" if style == "person" else "Team_Logo")
            real_tables.append(_table(label, real_cols, group, FB_REAL_AGG.get(label), "Total", **kw))
            strat_tables.append(_table(label, strat_cols, group, FB_STRAT_AVG.get(label), "Average", **kw))

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