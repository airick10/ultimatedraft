from flask import Flask
import json
import random
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


def load_baseball():
    """Combine hitters and pitchers into a single sorted LIST."""
    hitters = load_hitters_json()
    pitchers = load_pitchers_json()

    people = []
    for _id, h in hitters.items():
        pos = h.get("s_fielding", "").split("-")[0].upper()
        if pos == "":
            pos = "DH"
        people.append({
            "kind": "hitter",
            "short_pos": pos,
            "id": _id,                 # keep as string to match your dict keys
            **h
        })
    for _id, p in pitchers.items():
        pos = p.get("s_endurance", "").split("(")[0].strip().upper()
        pos = pos+"P"
        people.append({
            "kind": "pitcher",
            "short_pos": pos,
            "id": _id,
            **p
        })

    # Sort by LastName then FirstName; missing keys fall back to ""
    people.sort(key=lambda r: (r.get("LastName", ""), r.get("FirstName", "")))
    return people

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
        # e.g., "SS-2B" -> "SS"
        return person.get("s_fielding", "").split("-")[0].strip().upper()
    if kind == "pitcher":
        # e.g., "SP(7)" -> "SP"
        return person.get("s_endurance", "").split("(")[0].strip().upper()
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