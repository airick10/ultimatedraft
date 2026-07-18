from flask import Flask
import json
import random
from datetime import datetime
from pathlib import Path
from functools import lru_cache
from operator import itemgetter
import requests
import numpy as np

input_file_baseball_hitters = "https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltimebatters.json"
input_file_baseball_pitchers = "https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltimepitchers.json"
input_file_basketball = "https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltimebasketball.json"
input_file_football = "https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltimefootball.json"

def _read_json(src: str):
    if src.startswith("http://") or src.startswith("https://"):
        resp = requests.get(src, timeout=10)
        resp.raise_for_status()
        return resp.json()
    p = Path(__file__).with_name(src)
    with p.open(encoding="utf-8") as f:
        return json.load(f)

def _index_by_id(seq):
    """
    Convert a list of records to a dict keyed by 'ID' (string).
    Ignores items that don't have an ID.
    """
    out = {}
    for rec in seq:
        # try common keys; adjust if your JSON uses a different one
        _id = rec.get("ID") or rec.get("_id") or rec.get("id")
        if _id is None:
            continue
        out[str(_id)] = rec
    return out

def load_hitters_json():
    data = _read_json(input_file_baseball_hitters)  # likely a list
    return _index_by_id(data) if isinstance(data, list) else data

def load_pitchers_json():
    data = _read_json(input_file_baseball_pitchers)  # likely a list
    return _index_by_id(data) if isinstance(data, list) else data

def load_basketball_json():
    data = _read_json(input_file_basketball)  # likely a list
    return _index_by_id(data) if isinstance(data, list) else data

def load_football_json():
    data = _read_json(input_file_football)  # likely a list
    return _index_by_id(data) if isinstance(data, list) else data


def load_baseball(pool, num_teams):
    """Combine hitters and pitchers into a single sorted LIST."""
    hitters = load_hitters_json()
    pitchers = load_pitchers_json()
    if pool == "full" or pool == "custom":
        people = []
        for _id, h in hitters.items():
            #pos = h.get("s_fielding", "").split("-")[0].upper()
            #if pos == "":
                #pos = "DH"
            people.append({
                "kind": "hitter",
                "short_pos": compute_short_pos("hitter", h),
                "id": _id,                 # keep as string to match your dict keys
                **h
            })
        for _id, p in pitchers.items():
            #pos = p.get("s_endurance", "").split("(")[0].strip().upper()
            #pos = pos+"P"
            people.append({
                "kind": "pitcher",
                "short_pos": compute_short_pos("pitcher", p),
                "id": _id,
                **p
            })
    else:
        c = []
        fbase = []
        sbase = []
        tbase = []
        ss = []
        lf = []
        cf = []
        rf = []
        sp = []
        rp = []


        for _id, h in hitters.items():
            player = {"kind": "hitter", "short_pos": compute_short_pos("hitter", h), "id": _id, **h}
            pos = player["short_pos"]
            if pos == "C":
                c.append(player)
            elif pos == "1B":
                fbase.append(player)
            elif pos == "2B":
                sbase.append(player)
            elif pos == "3B":
                tbase.append(player)
            elif pos == "SS":
                ss.append(player)
            elif pos == "LF":
                lf.append(player)
            elif pos == "CF":
                cf.append(player)
            elif pos == "RF":
                rf.append(player)

        for _id, p in pitchers.items():
            player = {"kind": "pitcher", "short_pos": compute_short_pos("pitcher", p), "id": _id, **p}
            pos = player["short_pos"]
            if pos == "SP":
                sp.append(player)
            else:
                rp.append(player)


        num_c  = num_teams * 2
        num_1b = num_teams * 2
        num_2b = num_teams * 2
        num_3b = num_teams * 2
        num_ss = num_teams * 2
        num_lf = num_teams * 2
        num_cf = num_teams * 2
        num_rf = num_teams * 2
        num_sp = num_teams * 7
        num_rp = num_teams * 7

        people = (
            random.sample(c,  min(num_c,  len(c)))  +
            random.sample(fbase, min(num_1b, len(fbase))) +
            random.sample(sbase, min(num_2b, len(sbase))) +
            random.sample(ss, min(num_ss, len(ss))) +
            random.sample(tbase, min(num_3b, len(tbase))) +
            random.sample(lf, min(num_lf, len(lf))) +
            random.sample(cf, min(num_cf, len(cf))) +
            random.sample(rf, min(num_rf, len(rf))) +
            random.sample(sp, min(num_sp, len(sp))) +
            random.sample(rp,   min(num_rp,   len(rp)))
        )

    # Sort by LastName then FirstName; missing keys fall back to ""
    people.sort(key=lambda r: (r.get("LastName", ""), r.get("FirstName", "")))
    return people


def load_saved_baseball_draft(filename):
    draft_dir = Path("drafts")
    player_path = draft_dir / filename

    if not player_path.exists():
        raise FileNotFoundError(f"Draft file not found: {filename}")

    stem = player_path.stem

    if "_bb_" not in stem:
        raise ValueError(f"Not a baseball draft file: {filename}")

    draftname, timestamp = stem.split("_bb", 1)

    meta_path = draft_dir / f"{draftname}_bb_meta.json"
    log_path = draft_dir / f"{draftname}_bb_log.json"

    with open(player_path, "r", encoding="utf-8") as f:
        players = json.load(f)

    meta = {}
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    log = []
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            log = json.load(f)

    return {
        "players": players,
        "meta": meta,
        "log": log,
        "player_path": player_path,
        "meta_path": meta_path,
        "log_path": log_path,
        "draftname": draftname,
        "timestamp": timestamp,
    }

def initial_save_baseball_json(players, draftname, timestamp):
    people = []

    for p in players:
        people.append({
            **p,
            "team_id": 0,
            "id": p.get("id") or p.get("ID")
        })

    people.sort(key=lambda r: (r.get("LastName", ""), r.get("FirstName", "")))

    filename = f"{draftname}_bb.json"

    output_dir = Path("drafts")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / filename

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(people, f, indent=2)

    return output_path


def initial_save_baseball_meta_json(
    draftname,
    num_teams,
    human_teams,
    ai_set,
    pool,
    cap,
    player_file,
    timestamp
):
    filename = f"{draftname}_bb_meta.json"

    output_dir = Path("drafts")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / filename

    teams = []
    team_id = 1

    for team in human_teams:
        teams.append({
            "team_id": team_id,
            "team_name": team,
            "type": "human"
        })
        team_id += 1

    for team in ai_set:
        teams.append({
            "team_id": team_id,
            "team_name": team,
            "type": "ai"
        })
        team_id += 1

    meta = {
        "draftname": draftname,
        "sport": "bb",
        "num_teams": num_teams,
        "human_teams": len(human_teams),
        "ai_teams": len(ai_set),
        "pool": pool,
        "cap": cap,
        "player_file": str(player_file),
        "current_pick": 1,
        "current_team_id": 1,
        "teams": teams
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return output_path


def initial_save_baseball_log_json(draftname, timestamp):
    filename = f"{draftname}_bb_log.json"

    output_dir = Path("drafts")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / filename

    log = []

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)

    return output_path


def get_saved_baseball_drafts():
    draft_dir = Path("drafts")
    saved_drafts = []

    if not draft_dir.exists():
        return saved_drafts

    for file_path in sorted(draft_dir.glob("*_bb_*.json")):
        name = file_path.name

        if "_meta_" in name or "_log_" in name:
            continue

        saved_drafts.append(name)

    saved_drafts.sort(reverse=True)
    return saved_drafts

def load_baseball_meta(draftname):
    path = Path("drafts") / f"{draftname}_bb_meta.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_baseball_meta(draftname, meta):
    path = Path("drafts") / f"{draftname}_bb_meta.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)




# ------------------- BASKETBALL ---------------------------







def load_basketball(pool, num_teams):
    players = load_basketball_json()
    people = []
    if pool == "full" or pool == "custom":
        for _id, h in players.items():
            people.append({
                "id":_id,
                **h
                })
        '''
        people = []
        for _id, h in players.items():
            pos = h.get("s_fielding", "").split("-")[0].upper()
            if pos == "":
                pos = "DH"
            people.append({
                "kind": "hitter",
                "short_pos": pos,
                "id": _id,                 # keep as string to match your dict keys
                **h
            })
        '''

        # Sort by LastName then FirstName; missing keys fall back to ""
        # people.sort(key=lambda r: (r.get("LastName", ""), r.get("FirstName", "")))
    else:
        centers = []
        forwards = []
        guards = []

        for _id, h in players.items():
            pos = h.get("Pos", "")
            player = {"id": _id, **h}
            if pos == "C":
                centers.append(player)
            elif pos == "F":
                forwards.append(player)
            else:
                guards.append(player)

        num_centers  = num_teams * 2
        num_forwards = num_teams * 4
        num_guards   = num_teams * 4

        people = (
            random.sample(centers,  min(num_centers,  len(centers)))  +
            random.sample(forwards, min(num_forwards, len(forwards))) +
            random.sample(guards,   min(num_guards,   len(guards)))
        )

    people.sort(key=lambda r: (r.get("LastName", ""), r.get("FirstName", "")))
    return people


from datetime import datetime
from pathlib import Path
import json


def initial_save_basketball_json(players, draftname, timestamp):
    people = []

    for p in players:
        people.append({
            **p,
            "team_id": 0,
            "id": p.get("id") or p.get("ID")
        })

    people.sort(key=lambda r: (r.get("LastName", ""), r.get("FirstName", "")))

    filename = f"{draftname}_bk.json"

    output_dir = Path("drafts")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / filename

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(people, f, indent=2)

    return output_path


def initial_save_basketball_meta_json(
    draftname,
    num_teams,
    human_teams,
    ai_set,
    pool,
    cap,
    player_file,
    timestamp
):
    filename = f"{draftname}_bk_meta.json"

    output_dir = Path("drafts")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / filename

    teams = []
    team_id = 1

    for team in human_teams:
        teams.append({
            "team_id": team_id,
            "team_name": team,
            "type": "human"
        })
        team_id += 1

    for team in ai_set:
        teams.append({
            "team_id": team_id,
            "team_name": team,
            "type": "ai"
        })
        team_id += 1

    meta = {
        "draftname": draftname,
        "sport": "bk",
        "num_teams": num_teams,
        "human_teams": len(human_teams),
        "ai_teams": len(ai_set),
        "pool": pool,
        "cap": cap,
        "player_file": str(player_file),
        "current_pick": 1,
        "current_team_id": 1,
        "teams": teams
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return output_path


def initial_save_basketball_log_json(draftname, timestamp):
    filename = f"{draftname}_bk_log.json"

    output_dir = Path("drafts")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / filename

    log = []

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)

    return output_path


def get_saved_basketball_drafts():
    draft_dir = Path("drafts")
    saved_drafts = []

    if not draft_dir.exists():
        return saved_drafts

    for file_path in sorted(draft_dir.glob("*_bk_*.json")):
        name = file_path.name

        if "_meta_" in name or "_log_" in name:
            continue

        saved_drafts.append(name)

    saved_drafts.sort(reverse=True)
    return saved_drafts


def load_saved_basketball_draft(filename):
    draft_dir = Path("drafts")
    player_path = draft_dir / filename

    if not player_path.exists():
        raise FileNotFoundError(f"Draft file not found: {filename}")

    stem = player_path.stem

    if "_bk_" not in stem:
        raise ValueError(f"Not a basketball draft file: {filename}")

    draftname, timestamp = stem.split("_bk", 1)

    meta_path = draft_dir / f"{draftname}_bk_meta.json"
    log_path = draft_dir / f"{draftname}_bk_log.json"

    with open(player_path, "r", encoding="utf-8") as f:
        players = json.load(f)

    meta = {}
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    log = []
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            log = json.load(f)

    return {
        "players": players,
        "meta": meta,
        "log": log,
        "player_path": player_path,
        "meta_path": meta_path,
        "log_path": log_path,
        "draftname": draftname,
        "timestamp": timestamp,
    }

def load_basketball_meta(draftname):
    path = Path("drafts") / f"{draftname}_bk_meta.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_basketball_meta(draftname, meta):
    path = Path("drafts") / f"{draftname}_bk_meta.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


#------------ Football -------------------------------------



def load_football():
    players = load_football_json()

    people = []
    for _id, h in players.items():
        pos = h.get("s_fielding", "").split("-")[0].upper()
        if pos == "":
            pos = "DH"
        people.append({
            "kind": "hitter",
            "short_pos": pos,
            "id": _id,                 # keep as string to match your dict keys
            **h
        })

    # Sort by LastName then FirstName; missing keys fall back to ""
    people.sort(key=lambda r: (r.get("LastName", ""), r.get("FirstName", "")))
    return people


def load_saved_football_draft(filename):
    draft_dir = Path("drafts")
    player_path = draft_dir / filename

    if not player_path.exists():
        raise FileNotFoundError(f"Draft file not found: {filename}")

    stem = player_path.stem

    if "_fb_" not in stem:
        raise ValueError(f"Not a football draft file: {filename}")

    draftname, timestamp = stem.split("_fb", 1)

    meta_path = draft_dir / f"{draftname}_fb_meta.json"
    log_path = draft_dir / f"{draftname}_fb_log.json"

    with open(player_path, "r", encoding="utf-8") as f:
        players = json.load(f)

    meta = {}
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    log = []
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            log = json.load(f)

    return {
        "players": players,
        "meta": meta,
        "log": log,
        "player_path": player_path,
        "meta_path": meta_path,
        "log_path": log_path,
        "draftname": draftname,
        "timestamp": timestamp,
    }

# -------- MISC -----------------------------------------------------



def get_team_names(num_teams, sport, human_team_name):
    empty = []
    if sport == "bk":
        bk_names = np.array(["Aliens", "Armadillos", "Aztecs", "Black Crows", "Bloom", "Blues", "Cyclones",
        "Dolphins", "Dragons", "Drillers", "Explorers", "Gorillas", "Heroes", "Hunters", "Ice Hawks", "Monarchs", 
        "Muskateers", "Nationalists", "Pandas", "Quake", "Rays", "Razor Bats", "Rebels", "Sabers", "Shock", 
        "Sorcerers", "Stallions", "Thieves", "Undead", "Vikings", "Wolfpack", "Zombies"])
        if not human_team_name:
            return bk_names
        #np.isin filters out anything in human_team_name from being randomly selected.
        available = bk_names[~np.isin(bk_names, human_team_name)]
        return np.random.choice(available, size=num_teams, replace=False)
    elif sport == "bb":
        bb_names = np.array(["Aces", "Arrows", "Badgers", "Bandits", "Barons", "Bombers", "Buccaneers", "Buckeyes",
            "Claws", "Comets", "Copperheads", "Expos", "Falcons", "Gators", "Greyhounds", "Irish", "Jesters", "Monsters", 
            "Neptunes", "Nitros", "Oilers", "Pioneers", "Quest", "Rams", "Rockers", "Scorpions", "Sharks", "Stars", 
            "Storm", "Twisters", "Warriors", "Wizards"])
        if not human_team_name:
            return bb_names
        available = bb_names[~np.isin(bb_names, human_team_name)]
        return np.random.choice(available, size=num_teams, replace=False)
    else:
        fb_names = np.array(["Warriors"])
        if not human_team_name:
            return fb_names
        available = fb_names[~np.isin(fb_names, human_team_name)]
        return np.random.choice(available, size=num_teams, replace=False)

    return empty


def get_person(kind: str, _id: str):
    """Lookup helper for detail pages."""
    if kind == "hitter":
        return load_hitters().get(_id)
    if kind == "pitcher":
        return load_pitchers().get(_id)
    return None

def compute_short_pos(kind: str, person: dict) -> str:
    if kind == "hitter":
        raw = person.get("s_fielding", "").strip()
        if not raw:
            return "DH"
        primary = raw.split()[0].split("-")[0].upper()
        return primary if primary else "DH"
    if kind == "pitcher":
        raw = person.get("s_endurance", "").strip()
        if not raw:
            return "SP"  # fallback if missing
        first = raw[0].upper()
        if first == "S":
            return "SP"
        if first == "R":
            return "RP"
        if first == "C":
            return "CL"
        return "SP"  # safe default
    return ""


def positions(fielding: str):
    match fielding:
        case "C":
            return "Catcher"
        case "1B":
            return "First Baseman"
        case "2B":
            return "Second Baseman"
        case "SS":
            return "Shortstop"
        case "3B":
            return "Third Baseman"
        case "LF":
            return "Left Fielder"
        case "CF":
            return "Center Fielder"
        case "RF":
            return "Right Fielder"
        case "S":
            return "Starting Pitcher"
        case "R":
            return "Relief Pitcher"
        case "C":
            return "Closing Pitcher"
        case _:
            return "Designated Hitter"

def sort_people(stat: str, people: dict):

    if (stat != "p_earned_run_avg" and stat != "p_whip" and stat != "p_bb_per_nine"):
        people.sort(key=lambda r: float(r.get(stat, 0) or 0), reverse=True)
    else:
        people.sort(key=lambda r: float(r.get(stat, 0) or 0))

    return people

def pos_player_pool(pos: str, people: list[dict]) -> list[dict]:
    # filter down to just this position
    pool_temp = [h for h in people if h.get("short_pos") == pos]

    # how many to take (20%)
    num_players = round(len(pool_temp) * 0.2)

    # pick random unique players
    pool = random.sample(pool_temp, k=num_players) if num_players > 0 else []

    return pool

def get_next_team_id(meta):
    num_teams = meta["num_teams"]
    pick = meta["current_pick"]
    teams = meta["teams"]
    # snake order: picks 1-8 go forward, 9-16 go backward, etc.
    round_num = (pick - 1) // num_teams  # 0-indexed round
    pick_in_round = (pick - 1) % num_teams
    if round_num % 2 == 0:
        # forward
        idx = pick_in_round
    else:
        # reverse
        idx = num_teams - 1 - pick_in_round
    return teams[idx]["team_id"]

def get_team_by_id(meta, team_id):
    return next((t for t in meta["teams"] if t["team_id"] == team_id), None)

def append_to_log(log_path, entry):
    with open(log_path, "r", encoding="utf-8") as f:
        log = json.load(f)
    log.append(entry)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)