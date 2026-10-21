"""
services.py  --  the data layer for Ultimate Draft.

In plain words: this file knows how to GET players (download the JSON data files), how to SAVE and
RELOAD drafts (the files in the "drafts" folder), and a handful of small rules the rest of the app
shares (snake order, which roster slot a pick lands in, two-way players, team names).

It contains NO web pages and NO AI decisions. routes.py (pages and live events) and ai.py (the AI
drafters) both lean on it.

------------------------------------------------------------------------------------------------
THE SECTIONS IN THIS FILE (in order)
    1. Data-file links and settings .... input_file_* links, FOOTBALL_POS_MAP, TWO_WAY_NAMES_*
    2. Reading JSON .................... _read_json, _index_by_id, load_*_json (one per data file)
    3. Deleting a saved draft .......... delete_saved_draft
    4. BASEBALL ........................ building the pool, saving/loading a draft, meta files
    5. BASKETBALL ...................... same idea, plus "defense units"
    6. FOOTBALL ........................ same idea, with five data files
    7. MISC ............................ team names, short positions, snake order, the pick log
    8. SLOT MATCHING ................... assign_picks_to_slots_bb / _bk / _fb (which roster slot?)
    9. TWO-WAY PLAYERS ................. twin map, add_twins, and two diagnostics reports

------------------------------------------------------------------------------------------------
HOW A PLAYER LOOKS INSIDE THE APP
    Every player is a dict made from one record of a JSON data file, plus keys this app adds:

        kind       what kind of record it is: "hitter" / "pitcher" (baseball), "defense" (basketball),
                   "passer" / "rusher" / "receiver" / "dlineoline" / "special" (football)
        short_pos  the position used for filters and slots: "SS", "SP", "RP", "DH", "QB", "HB", ...
        id         a text id that is unique across the whole pool (see the prefixes below)
        team_id    added when a draft is SAVED. 0 = undrafted; otherwise the id of the drafting team

    The id prefixes exist because each sport has several data files whose own "ID" numbers can
    overlap (hitter 17 and pitcher 17 are different people):

        baseball    h_<ID> (hitters)      p_<ID> (pitchers)
        basketball  <ID> (players, no prefix)      d_<ID> (defense units)
        football    qb_<ID> hb_<ID> wr_<ID> do_<ID> kp_<ID>

THE THREE FILES SAVED FOR EVERY DRAFT (all in the "drafts" folder, sport code = bb / bk / fb)
    <name>_<sport>.json        the whole player pool, with each player's team_id
    <name>_<sport>_meta.json   settings and state (teams, cap, berserker, current pick, whose turn)
    <name>_<sport>_log.json    the pick-by-pick log (a list of entries, in draft order)

    "drafts" is a RELATIVE path, so it lives wherever you start the app from. Start the app from the
    same folder every time or your saved drafts will seem to vanish.

GOTCHAS WORTH KNOWING
    - Draft names that contain "_bb", "_bk" or "_fb" get cut off when reloaded (the loaders split the
      file name on that text). Avoid those character groups in a draft name.
    - Every JSON record needs an ID that is unique inside its own file. _index_by_id keeps only ONE
      record per ID, so duplicates make players silently disappear (see duplicate_id_report).
    - Nothing here caches the downloads. Each call to a load_*_json function downloads the file again.
"""

import json                    # read and write the JSON files
import random                  # random samples for "Random" pools, shuffling teams, AI focus numbers
import unicodedata             # strips accents so "Álex" can match "alex" (see norm_name)
from pathlib import Path       # file paths that work the same on Windows, Mac and Linux
import requests                # downloads the JSON data files from the internet
import numpy as np             # picking random team names (np.random.choice) and filtering with np.isin
from collections import Counter   # counts repeated values (used to spot duplicate IDs)


# =============================================================================================
# 1. DATA-FILE LINKS AND SETTINGS
# =============================================================================================
#
# Each constant below is the web address of one player data file. To point the app somewhere else
# (a new host, or a local copy), change ONLY these lines.
#   - A web address must start with http:// or https://
#   - A LOCAL file works too: put the .json next to services.py and set the constant to just the
#     file name, e.g.  input_file_baseball_hitters = "alltimebatters.json"
#     (a bare file name only; folders are not supported by _read_json)

# --- baseball: hitters and pitchers are two separate files ---
input_file_baseball_hitters = "https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltimebatters.json"
input_file_baseball_pitchers = "https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltimepitchers.json"

# --- basketball: players, plus a separate file of team "defense units" ---
input_file_basketball = "https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltimebasketball.json"
input_file_basketball_defense = "https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltimebasketball_defense.json"

# --- football: five files (QBs, receivers, rushers, defense/offensive-line units, special teams) ---
input_file_football_passing = "https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltime_football_passing.json"
input_file_football_receiving = "https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltime_football_receiving.json"
input_file_football_rushing = "https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltime_football_rushing.json"
input_file_football_def_ol = "https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltime_football_def_ol.json"
input_file_football_special = "https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltime_football_special.json"

#---- Normalizes Football Positions -----
# The football data stores positions as free text, sometimes with several (like "FL SE"). The app
# only wants these clean codes. normalize_football_pos() takes the FIRST word of that text and looks
# it up here. A word that isn't in this table falls back to a default chosen by the caller.
#
#   KP / DO  our own group codes: kicker-punter units and defense/offensive-line units
#   FL, SE   flanker and split end: both are wide receivers, so both become "WR"
#   RB, HB   running back and halfback both become "HB"
FOOTBALL_POS_MAP = {
    'KP':  'KP',
    'DO':  'DO',
    'FL':  'WR',
    'SE':  'WR',
    'WR':  'WR',
    'TE':  'TE',
    'RB':  'HB',
    'FB':  'FB',
    'HB':  'HB',  # halfback → RB
    'QB':  'QB',
}


# Two-way players: players who appear in the data as TWO records (for example a hitter record and a
# pitcher record for the same person). Drafting either record drafts BOTH, and that team gets one
# extra FLEX roster slot.
#
# They are matched by NAME, written exactly as FirstName + LastName in the data, not by ID, because
# IDs change whenever you edit the source JSON files. Spelling, accents and capitals don't matter
# (see norm_name), but the words must match.
# To add one: add the name here, then open /twin_check/bb or /twin_check/fb to confirm it says OK.
TWO_WAY_NAMES_BB = [
    "Babe Ruth",
    "Shohei Ohtani",
    "Bullet Rogan",
    # add the rest
]

TWO_WAY_NAMES_FB = [
    "Kordell Stewart",     # QB / WR
    "Billy Cannon",        # HB / TE
    "Deebo Samuel",        # HB / WR
    # add the rest
]


# =============================================================================================
# 2. READING JSON DATA
# =============================================================================================

def _read_json(src: str):
    """
    PURPOSE:
        Read one JSON file and return what's inside, from either a web address or a local file.
        Every data file in the app is read through this one function.

    ARGUMENTS:
        src (str) -- a web address starting with http:// or https://, OR a bare file name that sits
                     in the same folder as services.py.

    CALLED BY:
        - services.py: load_hitters_json, load_pitchers_json, load_basketball_json,
                       load_basketball_defense_json, load_football_passing_json,
                       load_football_rushing_json, load_football_receiving_json,
                       load_football_def_ol_json, load_football_special_json, duplicate_id_report.

    RETURNS:
        list | dict -- whatever the JSON file contains. Our data files are lists of records, but a
                       dict also works (see the load_*_json functions).
        Raises requests.HTTPError (download failed) or an OSError / JSON error (local file problem).
    """
    # --- web address: download it ---------------------------------------------------------
    if src.startswith("http://") or src.startswith("https://"):
        resp = requests.get(src, timeout=10)    # give up after 10 seconds instead of hanging forever
        resp.raise_for_status()                 # turn a 404 / 500 into an error rather than silently continue
        return resp.json()                      # parse the downloaded text as JSON

    # --- otherwise: a local file next to this one -----------------------------------------
    # Path(__file__) is services.py itself; with_name swaps the file name for `src`.
    p = Path(__file__).with_name(src)
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def _index_by_id(seq):
    """
    Convert a list of records to a dict keyed by 'ID' (string).
    Ignores items that don't have an ID.

    PURPOSE:
        Turn a list of records into a lookup table: {"123": {record}, "124": {record}, ...}.
        The key is the record's own ID turned into text.

    ARGUMENTS:
        seq (list[dict]) -- the records, as read from a JSON file.

    CALLED BY:
        - services.py: every load_*_json function below (when the file holds a list).

    RETURNS:
        dict -- {id as text: record}. A record with no ID is skipped. If two records share an ID,
                the LAST one wins and the earlier one is lost (duplicate_id_report finds these).
    """
    out = {}
    for rec in seq:
        # try common keys; adjust if your JSON uses a different one
        _id = rec.get("ID") or rec.get("_id") or rec.get("id")
        if _id is None:
            continue                    # no ID at all: can't be looked up, so skip it
        out[str(_id)] = rec             # str() so 5 and "5" are treated as the same key
    return out


# The nine load_*_json functions below all do the same job for a different file:
#     download the file  ->  if it's a list, turn it into {ID: record}  ->  return it.
# A file that is ALREADY a dict is returned as it is.

def load_hitters_json():
    """
    PURPOSE:
        Download the baseball hitters file (input_file_baseball_hitters).

    ARGUMENTS:
        none

    CALLED BY:
        - services.py: load_baseball.
        - routes.py:   suggested_cap (averages the salaries to suggest a cap on the setup page).

    RETURNS:
        dict -- {ID as text: hitter record}.
    """
    data = _read_json(input_file_baseball_hitters)  # likely a list
    return _index_by_id(data) if isinstance(data, list) else data


def load_pitchers_json():
    """
    PURPOSE:
        Download the baseball pitchers file (input_file_baseball_pitchers).

    ARGUMENTS:
        none

    CALLED BY:
        - services.py: load_baseball.
        - routes.py:   suggested_cap.

    RETURNS:
        dict -- {ID as text: pitcher record}.
    """
    data = _read_json(input_file_baseball_pitchers)  # likely a list
    return _index_by_id(data) if isinstance(data, list) else data


def load_basketball_json():
    """
    PURPOSE:
        Download the basketball players file (input_file_basketball).

    ARGUMENTS:
        none

    CALLED BY:
        - services.py: load_basketball.
        - routes.py:   suggested_cap.

    RETURNS:
        dict -- {ID as text: player record}.
    """
    data = _read_json(input_file_basketball)  # likely a list
    return _index_by_id(data) if isinstance(data, list) else data


def load_basketball_defense_json():
    """
    PURPOSE:
        Download the basketball defense-units file (input_file_basketball_defense). A "defense unit"
        is a whole team's defense for a season, drafted into the single Def roster slot.

    ARGUMENTS:
        none

    CALLED BY:
        - services.py: _defense_units (which load_basketball uses).
        - routes.py:   suggested_cap.

    RETURNS:
        dict -- {ID as text: defense-unit record}.
    """
    data = _read_json(input_file_basketball_defense)
    return _index_by_id(data) if isinstance(data, list) else data


def load_football_passing_json():
    """
    PURPOSE:
        Download the football passers (quarterbacks) file (input_file_football_passing).

    ARGUMENTS:
        none

    CALLED BY:
        - services.py: load_football.
        - routes.py:   suggested_cap.

    RETURNS:
        dict -- {ID as text: passer record}.
    """
    data = _read_json(input_file_football_passing)  # likely a list
    return _index_by_id(data) if isinstance(data, list) else data


def load_football_rushing_json():
    """
    PURPOSE:
        Download the football rushers (halfbacks and fullbacks) file (input_file_football_rushing).

    ARGUMENTS:
        none

    CALLED BY:
        - services.py: load_football.
        - routes.py:   suggested_cap.

    RETURNS:
        dict -- {ID as text: rusher record}.
    """
    data = _read_json(input_file_football_rushing)  # likely a list
    return _index_by_id(data) if isinstance(data, list) else data


def load_football_receiving_json():
    """
    PURPOSE:
        Download the football receivers (wide receivers and tight ends) file
        (input_file_football_receiving).

    ARGUMENTS:
        none

    CALLED BY:
        - services.py: load_football.
        - routes.py:   suggested_cap.

    RETURNS:
        dict -- {ID as text: receiver record}.
    """
    data = _read_json(input_file_football_receiving)  # likely a list
    return _index_by_id(data) if isinstance(data, list) else data


def load_football_def_ol_json():
    """
    PURPOSE:
        Download the football defense / offensive-line units file (input_file_football_def_ol).
        Each record is a whole unit for a team-season, drafted into the single Def roster slot.

    ARGUMENTS:
        none

    CALLED BY:
        - services.py: load_football.
        - routes.py:   suggested_cap.

    RETURNS:
        dict -- {ID as text: unit record}.
    """
    data = _read_json(input_file_football_def_ol)  # likely a list
    return _index_by_id(data) if isinstance(data, list) else data


def load_football_special_json():
    """
    PURPOSE:
        Download the football special-teams units file (input_file_football_special), drafted into
        the single Special roster slot.

    ARGUMENTS:
        none

    CALLED BY:
        - services.py: load_football.
        - routes.py:   suggested_cap.

    RETURNS:
        dict -- {ID as text: special-teams record}.
    """
    data = _read_json(input_file_football_special)  # likely a list
    return _index_by_id(data) if isinstance(data, list) else data


# =============================================================================================
# 3. DELETING A SAVED DRAFT
# =============================================================================================

def delete_saved_draft(filename, sport):
    """Deletes the player, meta, and log files for a saved draft. sport: 'bb', 'bk', or 'fb'.

    PURPOSE:
        Remove all three files that make up one saved draft (player file, meta file, log file).
        Powers the "Delete" button on the setup pages.

    ARGUMENTS:
        filename (str) -- the PLAYER file's name as shown in the saved-drafts list, such as
                          "FallLeague_bb.json" (not a path).
        sport    (str) -- "bb", "bk" or "fb".

    CALLED BY:
        - routes.py: bb_delete, bk_delete, fb_delete (each passes its own sport code).

    RETURNS:
        None.
        Raises ValueError if the name isn't a valid draft file for that sport (or tries to sneak in
        a folder path), and FileNotFoundError if the draft doesn't exist. The routes turn those
        into HTTP 400 / 404 error pages.
    """
    suffix = f"_{sport}.json"                 # every player file ends like this, e.g. "_bb.json"

    # Path(filename).name throws away any folders, so "../../secret.json" becomes "secret.json".
    # If that changed the text, someone sent a path instead of a plain file name: refuse.
    safe_name = Path(filename).name   # strips any path tricks like ../../
    if safe_name != filename or not safe_name.endswith(suffix):
        raise ValueError(f"Not a valid {sport} draft file: {filename}")

    # "FallLeague_bb.json" -> "FallLeague"
    draftname = safe_name[:-len(suffix)]
    draft_dir = Path("drafts")
    player_path = draft_dir / safe_name

    if not player_path.exists():
        raise FileNotFoundError(f"Draft file not found: {filename}")

    player_path.unlink()                                                   # delete the player file
    (draft_dir / f"{draftname}_{sport}_meta.json").unlink(missing_ok=True) # delete meta (fine if missing)
    (draft_dir / f"{draftname}_{sport}_log.json").unlink(missing_ok=True)  # delete log  (fine if missing)


# =============================================================================================
# 4. BASEBALL
# =============================================================================================

def short_hand(value):
    """'Left' -> 'L', 'Right' -> 'R', 'Switch' -> 'S' (anything else is left alone).

    PURPOSE:
        Shorten a batting or throwing hand to one letter so tables and the roster panel stay narrow.
        (Data that is already "L", "R" or "S" passes through unchanged.)

    ARGUMENTS:
        value (str | None) -- the hand as written in the data, such as "Left" or "R".

    CALLED BY:
        - services.py: load_baseball (for every hitter's "Bats" and every record's "Throws").

    RETURNS:
        str -- "L", "R" or "S" when the first letter is one of those; otherwise the original text
               (trimmed). An empty or missing value returns "".
    """
    text = str(value or "").strip()
    # Take the first letter; keep it only if it is one of the three hand codes.
    return text[:1].upper() if text[:1].upper() in ("L", "R", "S") else text


def load_baseball(pool, num_teams):
    """Combine hitters and pitchers into a single sorted LIST.

    PURPOSE:
        Build the baseball PLAYER POOL for a draft: download hitters and pitchers, give each one
        a kind / short_pos / id, and (for a Random pool) cut it down to a sample sized for the number
        of teams.

    ARGUMENTS:
        pool      (str) -- which pool to build:
                           "full" or "custom"  every player in the data (a "custom" pool shows them all
                                               so you can tick the ones you want)
                           anything else       treated as "random": a random sample, 2 players per
                                               hitting position per team and 7 SP + 7 RP per team,
                                               plus any two-way twins
        num_teams (int) -- how many teams are in the draft (sizes the Random sample).

    CALLED BY:
        - routes.py: bb_confirm (all three pool types), bb_draft (always "full", then filters down to
                     the picked ids), twin_check ("full").

    RETURNS:
        list[dict] -- the players, sorted by LastName then FirstName. Each dict is the original record
                      plus the keys "kind" ("hitter"/"pitcher"), "short_pos" and "id" ("h_..."/"p_...").
    """
    hitters  = load_hitters_json()
    pitchers = load_pitchers_json()

    # Turn "Left"/"Right"/"Switch" into L/R/S for every record. This changes the freshly downloaded
    # dicts in place (they're thrown away afterwards, so nothing else is affected).
    for rec in list(hitters.values()) + list(pitchers.values()):
        for key in ("Bats", "Throws"):
            if key in rec:
                rec[key] = short_hand(rec[key])

    # ---------------------------------------------------------------------------------------
    # FULL or CUSTOM pool: everybody goes in
    # ---------------------------------------------------------------------------------------
    if pool == "full" or pool == "custom":
        people = []
        for _id, h in hitters.items():
            people.append({
                "kind":      "hitter",
                "short_pos": compute_short_pos("hitter", h),
                "id":        f"h_{_id}",       # "h_" prefix: a hitter 17 and a pitcher 17 stay distinct
                **h                            # then copy in every key from the original record
            })
        for _id, p in pitchers.items():
            people.append({
                "kind":      "pitcher",
                "short_pos": compute_short_pos("pitcher", p),
                "id":        f"p_{_id}",
                **p
            })

    # ---------------------------------------------------------------------------------------
    # RANDOM pool: sort everyone into position buckets, then sample from each bucket
    # ---------------------------------------------------------------------------------------
    else:
        # One list per position. (fbase / sbase / tbase = first / second / third base; names can't
        # start with a digit, so "1b" wasn't an option.)
        c     = []
        fbase = []
        sbase = []
        tbase = []
        ss    = []
        lf    = []
        cf    = []
        rf    = []
        sp    = []
        rp    = []

        # Drop every hitter into his position's list. A hitter whose short_pos is "DH" (or
        # anything unlisted) is skipped, so DHs never appear in a Random pool.
        for _id, h in hitters.items():
            player = {"kind": "hitter", "short_pos": compute_short_pos("hitter", h), "id": f"h_{_id}", **h}
            pos = player["short_pos"]
            if pos == "C":     c.append(player)
            elif pos == "1B":  fbase.append(player)
            elif pos == "2B":  sbase.append(player)
            elif pos == "3B":  tbase.append(player)
            elif pos == "SS":  ss.append(player)
            elif pos == "LF":  lf.append(player)
            elif pos == "CF":  cf.append(player)
            elif pos == "RF":  rf.append(player)

        # Every pitcher is either a starter (SP) or counts as a reliever (RP, which includes closers).
        for _id, p in pitchers.items():
            player = {"kind": "pitcher", "short_pos": compute_short_pos("pitcher", p), "id": f"p_{_id}", **p}
            pos = player["short_pos"]
            if pos == "SP":  sp.append(player)
            else:            rp.append(player)

        # How many of each position to sample. A roster has 25 slots, but each position gets ONLY
        # 2 per team here because the 6 UT slots are filled by extra hitters at any position.
        # Change these multipliers to make Random pools bigger or smaller.
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

        # random.sample(list, n) picks n different items. min(...) protects against asking for more
        # players than a position has.
        people = (
            random.sample(c,     min(num_c,  len(c)))     +
            random.sample(fbase, min(num_1b, len(fbase))) +
            random.sample(sbase, min(num_2b, len(sbase))) +
            random.sample(ss,    min(num_ss, len(ss)))    +
            random.sample(tbase, min(num_3b, len(tbase))) +
            random.sample(lf,    min(num_lf, len(lf)))    +
            random.sample(cf,    min(num_cf, len(cf)))    +
            random.sample(rf,    min(num_rf, len(rf)))    +
            random.sample(sp,    min(num_sp, len(sp)))    +
            random.sample(rp,    min(num_rp, len(rp)))
        )

        # a two-way player's other record always comes along, so both his hitter and pitcher versions are in the pool
        # `universe` = EVERY record (not just the sample), so add_twins can find a twin that the
        # random sample happened to leave out.
        universe = (
            [{"kind": "hitter",  "short_pos": compute_short_pos("hitter", h),  "id": f"h_{_id}", **h} for _id, h in hitters.items()] +
            [{"kind": "pitcher", "short_pos": compute_short_pos("pitcher", p), "id": f"p_{_id}", **p} for _id, p in pitchers.items()]
        )
        people = add_twins(people, universe, "bb")

    # Alphabetical by last name, then first name. A missing name sorts as "" (first).
    people.sort(key=lambda r: (r.get("LastName", ""), r.get("FirstName", "")))
    return people


def load_saved_baseball_draft(filename):
    """
    PURPOSE:
        Reopen a saved baseball draft: read its player file, meta file and log file from the
        "drafts" folder.

    ARGUMENTS:
        filename (str) -- the player file's name from the saved-drafts list, e.g. "FallLeague_bb.json".

    CALLED BY:
        - routes.py: bb_load (the "Open" button on the baseball setup page).

    RETURNS:
        dict with these keys:
            "players"     list[dict]  the pool with team_ids
            "meta"        dict        the settings and state ({} if the meta file is missing)
            "log"         list        the pick log ([] if the log file is missing)
            "player_path" Path        where the player file lives
            "meta_path"   Path        where the meta file lives
            "log_path"    Path        where the log file lives
            "draftname"   str         the draft's name, worked out from the file name
        Raises FileNotFoundError if the player file doesn't exist and ValueError if the file isn't a
        baseball draft.
    """
    draft_dir   = Path("drafts")
    player_path = draft_dir / filename

    if not player_path.exists():
        raise FileNotFoundError(f"Draft file not found: {filename}")

    # .stem = the file name without ".json", e.g. "FallLeague_bb"
    stem = player_path.stem

    if "_bb" not in stem:
        raise ValueError(f"Not a baseball draft file: {filename}")

    # "FallLeague_bb" -> "FallLeague". NOTE: this splits on the FIRST "_bb", so a draft whose name
    # itself contains "_bb" would be cut short.
    draftname = stem.split("_bb")[0]

    meta_path = draft_dir / f"{draftname}_bb_meta.json"
    log_path  = draft_dir / f"{draftname}_bb_log.json"

    with open(player_path, "r", encoding="utf-8") as f:
        players = json.load(f)

    # The meta and log files are optional here; a missing one just becomes an empty value.
    meta = {}
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    log = []
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            log = json.load(f)

    return {
        "players":     players,
        "meta":        meta,
        "log":         log,
        "player_path": player_path,
        "meta_path":   meta_path,
        "log_path":    log_path,
        "draftname":   draftname
    }


def initial_save_baseball_json(players, draftname):
    """
    PURPOSE:
        Write the player file for a BRAND NEW baseball draft. Every player is saved as undrafted
        (team_id 0). After this, the file is rewritten after every pick.

    ARGUMENTS:
        players   (list[dict]) -- the pool to save (from load_baseball, possibly filtered).
        draftname (str)        -- the draft's name; the file becomes "<draftname>_bb.json".

    CALLED BY:
        - routes.py: bb_draft (only when that draft's file doesn't exist yet).

    RETURNS:
        Path -- the location of the file that was written (drafts/<draftname>_bb.json).
    """
    people = []

    for p in players:
        people.append({
            **p,                                  # keep every key the player already has
            "team_id": 0,                         # 0 = nobody has drafted him yet
            "id": p.get("id") or p.get("ID")      # make sure an "id" key exists (use "ID" if not)
        })

    people.sort(key=lambda r: (r.get("LastName", ""), r.get("FirstName", "")))

    filename = f"{draftname}_bb.json"

    output_dir = Path("drafts")
    output_dir.mkdir(parents=True, exist_ok=True)   # create "drafts" the first time

    output_path = output_dir / filename

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(people, f, indent=2)              # indent=2 keeps the file human-readable

    return output_path


def initial_save_baseball_meta_json(
    draftname,
    num_teams,
    human_teams,
    ai_set,
    pool,
    cap,
    player_file,
    berserker=False
):
    """
    PURPOSE:
        Write the meta file for a BRAND NEW baseball draft: the list of teams (humans and AI, in a
        shuffled order that becomes the first-round pick order), the settings, and the starting state
        (pick 1, first team on the clock).

    ARGUMENTS:
        draftname   (str)       -- the draft's name; the file becomes "<draftname>_bb_meta.json".
        num_teams   (int)       -- how many teams in total.
        human_teams (list[str]) -- names of the teams people control.
        ai_set      (list[str]) -- names of the computer-controlled teams.
        pool        (str)       -- "full", "random" or "custom" (stored for reference).
        cap         (str)       -- the salary cap as digits, or "" for no cap.
        player_file (Path|str)  -- where the player file was saved (stored for reference).
        berserker   (bool)      -- True to turn on Berserker mode for the AI teams. See berserker.py.

    CALLED BY:
        - routes.py: bb_draft (only when that draft's meta file doesn't exist yet).

    RETURNS:
        Path -- the location of the file that was written (drafts/<draftname>_bb_meta.json).
    """
    filename = f"{draftname}_bb_meta.json"

    output_dir = Path("drafts")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / filename

    teams = []
    team_id = 1          # team ids are 1, 2, 3...; 0 is reserved for "undrafted" on players

    # Human teams first...
    for team in human_teams:
        teams.append({
            "team_id": team_id,
            "team_name": team,
            "type": "human"
        })
        team_id += 1

    # ...then AI teams. Each AI team gets a random "archetype" number 1-16 (its drafting
    # personality; see AI_FOCUS_TABLE in ai.py) and the Berserker flag.
    for team in ai_set:
        teams.append({
            "team_id": team_id,
            "team_name": team,
            "type": "ai",
            "AIFocus": random.randint(1, 16),
            "Berserker": bool(berserker)
        })
        team_id += 1

    # Shuffle so the human teams aren't always picking first. The shuffled order is the order of
    # picks in round 1 (it reverses in round 2, and so on: a "snake").
    random.shuffle(teams)

    meta = {
        "draftname": draftname,
        "sport": "bb",
        "num_teams": num_teams,
        "human_teams": len(human_teams),
        "ai_teams": len(ai_set),
        "pool": pool,
        "cap": cap,
        "berserker": bool(berserker),
        "player_file": str(player_file),
        "current_pick": 1,                             # the next pick to be made
        "current_team_id": teams[0]["team_id"],        # the team on the clock
        "teams": teams
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return output_path


def initial_save_baseball_log_json(draftname):
    """
    PURPOSE:
        Create the EMPTY pick log for a brand new baseball draft. Picks are added to it one at a
        time later (see append_to_log).

    ARGUMENTS:
        draftname (str) -- the draft's name; the file becomes "<draftname>_bb_log.json".

    CALLED BY:
        - routes.py: bb_draft (only when that draft's log file doesn't exist yet).

    RETURNS:
        Path -- the location of the file that was written (drafts/<draftname>_bb_log.json).
    """
    filename = f"{draftname}_bb_log.json"

    output_dir = Path("drafts")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / filename

    log = []     # no picks yet

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)

    return output_path


def get_saved_baseball_drafts():
    """
    PURPOSE:
        List the saved baseball drafts so the setup page can show them (and the confirm page can warn
        about a name that already exists).

    ARGUMENTS:
        none

    CALLED BY:
        - routes.py: start_baseball (the saved-drafts panel) and bb_confirm (existing names).

    RETURNS:
        list[str] -- player-file names like "FallLeague_bb.json", sorted Z to A. An empty list if
                     the "drafts" folder doesn't exist yet.
    """
    draft_dir = Path("drafts")
    saved_drafts = []

    if not draft_dir.exists():
        return saved_drafts

    # "*_bb.json" matches the player files only (the meta and log files end in "_meta.json" and
    # "_log.json", so they don't match).
    for file_path in sorted(draft_dir.glob("*_bb.json")):
        saved_drafts.append(file_path.name)

    saved_drafts.sort(reverse=True)
    return saved_drafts


def load_baseball_meta(draftname):
    """
    PURPOSE:
        Read a baseball draft's meta file: who the teams are, the cap, and whose turn it is.

    ARGUMENTS:
        draftname (str) -- the draft's name (no "_bb" suffix).

    CALLED BY:
        - routes.py:  bb_team_json, make_ai_pick_bb, run_ai_picks_bb, handle_make_pick,
                      handle_skip_pick, handle_request_sync, and META_LOADERS (which
                      handle_start_draft uses).
        - exports.py: build_bb_workbook and, through _META_LOADERS, _load_draft,
                      build_log_text and the report builders.

    RETURNS:
        dict -- the contents of drafts/<draftname>_bb_meta.json. Raises FileNotFoundError if missing.
    """
    path = Path("drafts") / f"{draftname}_bb_meta.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_baseball_meta(draftname, meta):
    """
    PURPOSE:
        Write a baseball draft's meta file back to disk (after the current pick and team on the
        clock have been advanced).

    ARGUMENTS:
        draftname (str)  -- the draft's name.
        meta      (dict) -- the full meta dict to save (replaces the old file's contents).

    CALLED BY:
        - routes.py: make_ai_pick_bb and handle_make_pick (after every baseball pick).

    RETURNS:
        None.
    """
    path = Path("drafts") / f"{draftname}_bb_meta.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)



# =============================================================================================
# 5. BASKETBALL
# =============================================================================================
# Same ideas as baseball, with two differences:
#   - There are no separate hitter/pitcher files; players are one list.
#   - There are "defense units" (a team's defense, drafted into the single Def slot).

def unit_label(d):
    """'2025 Washington'. Your sample has Team and Year swapped (Team=2025, Year='Washington'),
    so whichever value is all digits goes first.

    PURPOSE:
        Build the display name for a team-season "unit" (a basketball defense, or a football
        defense / special-teams unit) as "<year> <team>".

    ARGUMENTS:
        d (dict) -- the unit's record. Uses its "Year" and "Team" values.

    CALLED BY:
        - services.py: _defense_units (basketball defense names).
        - exports.py:  _fb_cell_value and _report_row (names of football and basketball units).

    RETURNS:
        str -- for example "2025 Washington". Blank values are tolerated.
    """
    # Read both values as clean text. (Some data has the year in "Team" and the city in "Year".)
    a, b = str(d.get("Year") or "").strip(), str(d.get("Team") or "").strip()

    # If "Team" holds the digits and "Year" doesn't, they're swapped: swap them back.
    if b.isdigit() and not a.isdigit():
        a, b = b, a
    return f"{a} {b}".strip()


def _defense_units():
    """
    PURPOSE:
        Download the basketball defense units and dress each one up like a player so it can sit in
        the same pool and table: give it a prefixed id, a kind of "defense", the position "DEF" and a
        display name.

    ARGUMENTS:
        none

    CALLED BY:
        - services.py: load_basketball.

    RETURNS:
        list[dict] -- one dict per defense unit, with extra keys id / ID ("d_<ID>"), kind
                      ("defense"), Pos ("DEF"), short_pos ("DEF") and name (e.g. "2025 Washington").
    """
    out = []
    for _id, d in load_basketball_defense_json().items():
        uid = f"d_{_id}"                       # prefixed so it can never collide with a player's ID
        out.append({
            **d,                               # the unit's own keys come first...
            "id": uid, "ID": uid,              # ...then these override anything with the same name
            "kind": "defense", "Pos": "DEF", "short_pos": "DEF",
            "name": unit_label(d),
        })
    return out


def load_basketball(pool, num_teams):
    """
    PURPOSE:
        Build the basketball PLAYER POOL (players plus defense units), the same way load_baseball
        does for baseball.

    ARGUMENTS:
        pool      (str) -- "full" or "custom": everybody. Anything else is treated as "random": a
                           sample of 3 centers, 5 forwards and 5 guards per team, plus 2 defense units
                           per team.
        num_teams (int) -- how many teams are in the draft.

    CALLED BY:
        - routes.py: bk_confirm (all pool types) and bk_draft (always "full", then filtered).

    RETURNS:
        list[dict] -- players sorted by LastName then FirstName, with every defense unit moved to the
                      END of the list. Player dicts get an "id" key (their own ID); defense units
                      get "d_<ID>".
    """
    players = load_basketball_json()
    defense = _defense_units()
    people = []

    # ---- FULL / CUSTOM: everybody -------------------------------------------------------
    if pool == "full" or pool == "custom":
        for _id, h in players.items():
            people.append({"id": _id, **h})
        people.extend(defense)

    # ---- RANDOM: bucket by position, then sample -----------------------------------------
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
                guards.append(player)       # anything that isn't C or F counts as a guard

        # 11 player slots per team (1 C, 2 F, 2 G, 6 UT) plus a spare of each position, and 2 defenses
        num_centers  = num_teams * 3
        num_forwards = num_teams * 5
        num_guards   = num_teams * 5

        people = (
            random.sample(centers,  min(num_centers,  len(centers)))  +
            random.sample(forwards, min(num_forwards, len(forwards))) +
            random.sample(guards,   min(num_guards,   len(guards)))   +
            random.sample(defense,  min(num_teams * 2, len(defense)))
        )

    # defense units go last in the pool
    # Sort key is a tuple: first "is this a defense?" (False sorts before True, so players come
    # first), then last name, then first name.
    people.sort(key=lambda r: (r.get("kind") == "defense", r.get("LastName", ""), r.get("FirstName", "")))
    return people


def initial_save_basketball_json(players, draftname):
    """
    PURPOSE:
        Write the player file for a BRAND NEW basketball draft, with everyone undrafted (team_id 0).

    ARGUMENTS:
        players   (list[dict]) -- the pool to save (from load_basketball, possibly filtered).
        draftname (str)        -- the draft's name; the file becomes "<draftname>_bk.json".

    CALLED BY:
        - routes.py: bk_draft (only when that draft's file doesn't exist yet).

    RETURNS:
        Path -- the location of the file that was written (drafts/<draftname>_bk.json).
    """
    people = []

    for p in players:
        people.append({
            **p,
            "team_id": 0,
            "id": p.get("id") or p.get("ID")
        })

    # Same sort as load_basketball: players first, defense units last.
    people.sort(key=lambda r: (r.get("kind") == "defense", r.get("LastName", ""), r.get("FirstName", "")))

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
    berserker=False
):
    """
    PURPOSE:
        Write the meta file for a BRAND NEW basketball draft (teams in shuffled pick order, the
        settings, and the starting state). Identical in behavior to
        initial_save_baseball_meta_json except for the sport code ("bk").

    ARGUMENTS:
        draftname   (str)       -- the draft's name; the file becomes "<draftname>_bk_meta.json".
        num_teams   (int)       -- how many teams in total.
        human_teams (list[str]) -- names of the human-controlled teams.
        ai_set      (list[str]) -- names of the AI-controlled teams.
        pool        (str)       -- "full", "random" or "custom".
        cap         (str)       -- the salary cap as digits, or "" for no cap.
        player_file (Path|str)  -- where the player file was saved.
        berserker   (bool)      -- True to turn on Berserker mode for the AI teams.

    CALLED BY:
        - routes.py: bk_draft (only when that draft's meta file doesn't exist yet).

    RETURNS:
        Path -- the location of the file that was written (drafts/<draftname>_bk_meta.json).
    """
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
            "type": "ai",
            "AIFocus": random.randint(1, 16),     # AI personality, see AI_FOCUS_TABLE_BK in ai.py
            "Berserker": bool(berserker)
        })
        team_id += 1

    random.shuffle(teams)       # the shuffled order is round 1's pick order

    meta = {
        "draftname": draftname,
        "sport": "bk",
        "num_teams": num_teams,
        "human_teams": len(human_teams),
        "ai_teams": len(ai_set),
        "pool": pool,
        "cap": cap,
        "berserker": bool(berserker),
        "player_file": str(player_file),
        "current_pick": 1,
        "current_team_id": teams[0]["team_id"],
        "teams": teams
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return output_path


def initial_save_basketball_log_json(draftname):
    """
    PURPOSE:
        Create the EMPTY pick log for a brand new basketball draft.

    ARGUMENTS:
        draftname (str) -- the draft's name; the file becomes "<draftname>_bk_log.json".

    CALLED BY:
        - routes.py: bk_draft (only when that draft's log file doesn't exist yet).

    RETURNS:
        Path -- the location of the file that was written (drafts/<draftname>_bk_log.json).
    """
    filename = f"{draftname}_bk_log.json"

    output_dir = Path("drafts")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / filename

    log = []

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)

    return output_path


def get_saved_basketball_drafts():
    """
    PURPOSE:
        List the saved basketball drafts (for the setup page and the "name already exists" warning).

    ARGUMENTS:
        none

    CALLED BY:
        - routes.py: start_basketball and bk_confirm.

    RETURNS:
        list[str] -- player-file names like "BKDraft_bk.json", sorted Z to A. Empty if there is no
                     "drafts" folder.
    """
    draft_dir = Path("drafts")
    saved_drafts = []

    if not draft_dir.exists():
        return saved_drafts

    for file_path in sorted(draft_dir.glob("*_bk.json")):
        saved_drafts.append(file_path.name)

    saved_drafts.sort(reverse=True)
    return saved_drafts


def load_saved_basketball_draft(filename):
    """
    PURPOSE:
        Reopen a saved basketball draft: read its player, meta and log files. Same job and same
        result shape as load_saved_baseball_draft.

    ARGUMENTS:
        filename (str) -- the player file's name, e.g. "BKDraft_bk.json".

    CALLED BY:
        - routes.py: bk_load (the "Open" button on the basketball setup page).

    RETURNS:
        dict with keys "players", "meta", "log", "player_path", "meta_path", "log_path" and
        "draftname" (see load_saved_baseball_draft for what each holds).
        Raises FileNotFoundError / ValueError the same way.
    """
    draft_dir = Path("drafts")
    player_path = draft_dir / filename
    if not player_path.exists():
        raise FileNotFoundError(f"Draft file not found: {filename}")
    stem = player_path.stem  # "BKDraft_bk"
    if "_bk" not in stem:
        raise ValueError(f"Not a basketball draft file: {filename}")
    draftname = stem.split("_bk")[0]  # "BKDraft"    (cuts at the FIRST "_bk" in the name)
    meta_path = draft_dir / f"{draftname}_bk_meta.json"
    log_path  = draft_dir / f"{draftname}_bk_log.json"
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
        "players":     players,
        "meta":        meta,
        "log":         log,
        "player_path": player_path,
        "meta_path":   meta_path,
        "log_path":    log_path,
        "draftname":   draftname
    }


def load_basketball_meta(draftname):
    """
    PURPOSE:
        Read a basketball draft's meta file (teams, cap, whose turn it is).

    ARGUMENTS:
        draftname (str) -- the draft's name (no "_bk" suffix).

    CALLED BY:
        - routes.py:  make_ai_pick_bk, run_ai_picks_bk, handle_make_pick, handle_skip_pick,
                      handle_request_sync, and META_LOADERS (used by handle_start_draft).
        - exports.py: build_bk_workbook and, through _META_LOADERS, _load_draft and
                      build_log_text.

    RETURNS:
        dict -- the contents of drafts/<draftname>_bk_meta.json.
    """
    path = Path("drafts") / f"{draftname}_bk_meta.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_basketball_meta(draftname, meta):
    """
    PURPOSE:
        Write a basketball draft's meta file back to disk after a pick.

    ARGUMENTS:
        draftname (str)  -- the draft's name.
        meta      (dict) -- the full meta dict to save.

    CALLED BY:
        - routes.py: make_ai_pick_bk and handle_make_pick.

    RETURNS:
        None.
    """
    path = Path("drafts") / f"{draftname}_bk_meta.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


# =============================================================================================
# 6. FOOTBALL
# =============================================================================================
# Football has five data files (passers, rushers, receivers, defense/offensive-line units, special
# teams units). Four of the kinds are individual PEOPLE (passer / rusher / receiver) or UNITS
# (dlineoline / special), but they all live in one pool and follow the same id-prefix idea.

def load_football(pool, num_teams):
    """
    PURPOSE:
        Build the football PLAYER POOL from all five data files, the same way load_baseball does.

    ARGUMENTS:
        pool      (str) -- "full" or "custom": everybody. Anything else is treated as "random": a
                           per-team sample of 3 QB, 3 HB, 2 FB, 3 TE, 5 WR, 2 defense units and 2
                           special-teams units, plus any two-way twins.
        num_teams (int) -- how many teams are in the draft.

    CALLED BY:
        - routes.py: fb_confirm (all pool types), fb_draft (always "full", then filtered),
                     twin_check ("full").

    RETURNS:
        list[dict] -- the players and units sorted by LastName then FirstName (units have no names, so
                      they sort to the front). Each dict is the original record plus "kind", "short_pos"
                      and "id". Units also get a "name" like "1985 Chicago DO".
    """
    passers   = load_football_passing_json()
    rushers   = load_football_rushing_json()
    receivers = load_football_receiving_json()
    defoff   = load_football_def_ol_json()
    special = load_football_special_json()

    # ids already used, so a receiver and a passer/rusher can never be listed twice. (The prefixes
    # already keep ids apart, so this is a second line of defense.)
    seen_ids = set()
    people   = []

    # ---------------------------------------------------------------------------------------
    # FULL / CUSTOM: everybody goes in
    # ---------------------------------------------------------------------------------------
    if pool == "full" or pool == "custom":
        for _id, p in passers.items():
            uid = f"qb_{_id}"
            seen_ids.add(uid)
            people.append({
                "kind":      "passer",
                "short_pos": "QB",             # every passer is a quarterback
                "id":        uid,
                **p
            })
        for _id, h in rushers.items():
            uid = f"hb_{_id}"
            seen_ids.add(uid)
            raw = h.get("Positions", "HB")                          # e.g. "RB" or "FB"
            pos = normalize_football_pos(raw, default='HB')         # cleaned to HB or FB
            people.append({
                "kind":      "rusher",
                "short_pos": pos,
                "id":        uid,
                **h
            })
        for _id, r in receivers.items():
            uid = f"wr_{_id}"
            if uid in seen_ids:
                continue
            raw = r.get("Positions", "WR")
            pos = normalize_football_pos(raw, default='WR')         # WR or TE
            people.append({
                "kind":      "receiver",
                "short_pos": pos,
                "id":        uid,
                **r
            })
        for _id, d in defoff.items():
            uid = f"do_{_id}"
            if uid in seen_ids:
                continue
            raw = d.get("Positions", "DO")
            pos = normalize_football_pos(raw, default='DO')
            people.append({
                "kind":      "dlineoline",
                # units have no first/last name, so build a display name from year + team + positions
                "name": f"{d.get('Year','')} {d.get('Team','')} {d.get('Positions','')}",
                "short_pos": pos,
                "id":        uid,
                **d
            })
        for _id, k in special.items():
            uid = f"kp_{_id}"
            if uid in seen_ids:
                continue
            raw = k.get("Positions", "KP")
            pos = normalize_football_pos(raw, default='KP')
            people.append({
                "kind":      "special",
                "name": f"{k.get('Year','')} {k.get('Team','')} {k.get('Positions','')}",
                "short_pos": pos,
                "id":        uid,
                **k
            })

    # ---------------------------------------------------------------------------------------
    # RANDOM: bucket by position, then sample from each bucket
    # ---------------------------------------------------------------------------------------
    else:
        qb = []
        hb = []
        fb = []
        te = []
        wr = []
        do = []
        kp = []

        for _id, p in passers.items():
            uid = f"qb_{_id}"
            seen_ids.add(uid)
            player = {"kind": "passer", "short_pos": "QB", "id": uid, **p}
            qb.append(player)

        # Rushers split into halfbacks (HB) and everything else (fullbacks).
        for _id, h in rushers.items():
            uid = f"hb_{_id}"
            seen_ids.add(uid)
            raw = h.get("Positions", "HB")
            player = {"kind": "rusher", "short_pos": normalize_football_pos(raw, default='HB'), "id": uid, **h}
            pos = player["short_pos"]
            if pos == "HB":  hb.append(player)
            else:            fb.append(player)

        # Receivers split into wide receivers and tight ends (anything else is left out).
        for _id, r in receivers.items():
            uid = f"wr_{_id}"
            if uid in seen_ids:
                continue
            raw = r.get("Positions", "WR")
            player = {"kind": "receiver", "short_pos": normalize_football_pos(raw, default='WR'), "id": uid, **r}
            pos = player["short_pos"]
            if pos == "WR":  wr.append(player)
            elif pos == "TE":  te.append(player)

        for _id, d in defoff.items():
            uid = f"do_{_id}"
            seen_ids.add(uid)
            player = {"kind": "dlineoline", "name": f"{d.get('Year','')} {d.get('Team','')} {d.get('Positions','')}", "short_pos": "DO", "id": uid, **d}
            do.append(player)

        for _id, k in special.items():
            uid = f"kp_{_id}"
            seen_ids.add(uid)
            player = {"kind": "special", "name": f"{k.get('Year','')} {k.get('Team','')} {k.get('Positions','')}", "short_pos": "KP", "id": uid, **k}
            kp.append(player)

        # How many of each to sample: the roster slots plus a spare, per team.
        num_qb = num_teams * 3     # 2 slots + 1 spare per team
        num_hb = num_teams * 3     # 2 slots + 1 spare
        num_fb = num_teams * 2     # 1 slot + 1 spare
        num_te = num_teams * 3     # 2 slots + 1 spare
        num_wr = num_teams * 5     # 4 slots + 1 spare
        num_do = num_teams * 2     # 1 slot + 1 spare
        num_kp = num_teams * 2     # 1 slot + 1 spare

        people = (
            random.sample(qb, min(num_qb, len(qb))) +
            random.sample(hb, min(num_hb, len(hb))) +
            random.sample(fb, min(num_fb, len(fb))) +
            random.sample(te, min(num_te, len(te))) +
            random.sample(wr, min(num_wr, len(wr))) +
            random.sample(do, min(num_do, len(do))) +
            random.sample(kp, min(num_kp, len(kp)))
        )

        # a two-way player's other record always comes along
        # `universe` = every PERSON record (passers, rushers, receivers). Units can't be two-way, so
        # they're left out of it.
        universe = []
        for _id, p in passers.items():
            universe.append({"kind": "passer", "short_pos": "QB", "id": f"qb_{_id}", **p})
        for _id, h in rushers.items():
            universe.append({"kind": "rusher", "short_pos": normalize_football_pos(h.get("Positions", "HB"), default='HB'),
                             "id": f"hb_{_id}", **h})
        for _id, r in receivers.items():
            universe.append({"kind": "receiver", "short_pos": normalize_football_pos(r.get("Positions", "WR"), default='WR'),
                             "id": f"wr_{_id}", **r})
        people = add_twins(people, universe, "fb")

    people.sort(key=lambda r: (r.get("LastName", ""), r.get("FirstName", "")))
    return people


def initial_save_football_meta_json(
    draftname,
    num_teams,
    human_teams,
    ai_set,
    pool,
    cap,
    player_file,
    berserker=False
):
    """
    PURPOSE:
        Write the meta file for a BRAND NEW football draft (teams in shuffled pick order, settings,
        starting state). Identical in behavior to initial_save_baseball_meta_json except for the
        sport code ("fb").

    ARGUMENTS:
        draftname   (str)       -- the draft's name; the file becomes "<draftname>_fb_meta.json".
        num_teams   (int)       -- how many teams in total.
        human_teams (list[str]) -- names of the human-controlled teams.
        ai_set      (list[str]) -- names of the AI-controlled teams.
        pool        (str)       -- "full", "random" or "custom".
        cap         (str)       -- the salary cap as digits, or "" for no cap.
        player_file (Path|str)  -- where the player file was saved.
        berserker   (bool)      -- True to turn on Berserker mode for the AI teams.

    CALLED BY:
        - routes.py: fb_draft (only when that draft's meta file doesn't exist yet).

    RETURNS:
        Path -- the location of the file that was written (drafts/<draftname>_fb_meta.json).
    """
    filename = f"{draftname}_fb_meta.json"

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
            "type": "ai",
            "AIFocus": random.randint(1, 16),     # AI personality, see AI_FOCUS_TABLE_FB in ai.py
            "Berserker": bool(berserker)
        })
        team_id += 1

    random.shuffle(teams)       # the shuffled order is round 1's pick order

    meta = {
        "draftname": draftname,
        "sport": "fb",
        "num_teams": num_teams,
        "human_teams": len(human_teams),
        "ai_teams": len(ai_set),
        "pool": pool,
        "cap": cap,
        "berserker": bool(berserker),
        "player_file": str(player_file),
        "current_pick": 1,
        "current_team_id": teams[0]["team_id"],
        "teams": teams
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return output_path


def initial_save_football_log_json(draftname):
    """
    PURPOSE:
        Create the EMPTY pick log for a brand new football draft.

    ARGUMENTS:
        draftname (str) -- the draft's name; the file becomes "<draftname>_fb_log.json".

    CALLED BY:
        - routes.py: fb_draft (only when that draft's log file doesn't exist yet).

    RETURNS:
        Path -- the location of the file that was written (drafts/<draftname>_fb_log.json).
    """
    filename = f"{draftname}_fb_log.json"

    output_dir = Path("drafts")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / filename

    log = []

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)

    return output_path


def get_saved_football_drafts():
    """
    PURPOSE:
        List the saved football drafts (for the setup page and the "name already exists" warning).

    ARGUMENTS:
        none

    CALLED BY:
        - routes.py: start_football and fb_confirm.

    RETURNS:
        list[str] -- player-file names like "FallLeague_fb.json", sorted Z to A. Empty if there is
                     no "drafts" folder.
    """
    draft_dir = Path("drafts")
    saved_drafts = []

    if not draft_dir.exists():
        return saved_drafts

    for file_path in sorted(draft_dir.glob("*_fb.json")):
        saved_drafts.append(file_path.name)

    saved_drafts.sort(reverse=True)
    return saved_drafts


def load_saved_football_draft(filename):
    """
    PURPOSE:
        Reopen a saved football draft: read its player, meta and log files. Same job and result
        shape as load_saved_baseball_draft.

    ARGUMENTS:
        filename (str) -- the player file's name, e.g. "FallLeague_fb.json".

    CALLED BY:
        - routes.py: fb_load (the "Open" button on the football setup page).

    RETURNS:
        dict with keys "players", "meta", "log", "player_path", "meta_path", "log_path" and
        "draftname" (see load_saved_baseball_draft). Raises FileNotFoundError / ValueError the same
        way.
    """
    draft_dir   = Path("drafts")
    player_path = draft_dir / filename

    if not player_path.exists():
        raise FileNotFoundError(f"Draft file not found: {filename}")

    stem = player_path.stem

    if "_fb" not in stem:
        raise ValueError(f"Not a football draft file: {filename}")

    draftname = stem.split("_fb")[0]      # cuts at the FIRST "_fb" in the name

    meta_path = draft_dir / f"{draftname}_fb_meta.json"
    log_path  = draft_dir / f"{draftname}_fb_log.json"

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
        "players":     players,
        "meta":        meta,
        "log":         log,
        "player_path": player_path,
        "meta_path":   meta_path,
        "log_path":    log_path,
        "draftname":   draftname
    }


def initial_save_football_json(players, draftname):
    """
    PURPOSE:
        Write the player file for a BRAND NEW football draft, with everyone undrafted (team_id 0).

    ARGUMENTS:
        players   (list[dict]) -- the pool to save (from load_football, possibly filtered).
        draftname (str)        -- the draft's name; the file becomes "<draftname>_fb.json".

    CALLED BY:
        - routes.py: fb_draft (only when that draft's file doesn't exist yet).

    RETURNS:
        Path -- the location of the file that was written (drafts/<draftname>_fb.json).
    """
    people = []

    for p in players:
        people.append({
            **p,
            "team_id": 0,
            "id": p.get("id") or p.get("ID")
        })

    people.sort(key=lambda r: (r.get("LastName", ""), r.get("FirstName", "")))

    filename = f"{draftname}_fb.json"

    output_dir = Path("drafts")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / filename

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(people, f, indent=2)

    return output_path


def load_football_meta(draftname):
    """
    PURPOSE:
        Read a football draft's meta file (teams, cap, whose turn it is).

    ARGUMENTS:
        draftname (str) -- the draft's name (no "_fb" suffix).

    CALLED BY:
        - routes.py:  make_ai_pick_fb, run_ai_picks_fb, handle_make_pick, handle_skip_pick,
                      handle_request_sync, and META_LOADERS (used by handle_start_draft).
        - exports.py: build_fb_workbook and, through _META_LOADERS, _load_draft and
                      build_log_text.

    RETURNS:
        dict -- the contents of drafts/<draftname>_fb_meta.json.
    """
    path = Path("drafts") / f"{draftname}_fb_meta.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_football_meta(draftname, meta):
    """
    PURPOSE:
        Write a football draft's meta file back to disk after a pick.

    ARGUMENTS:
        draftname (str)  -- the draft's name.
        meta      (dict) -- the full meta dict to save.

    CALLED BY:
        - routes.py: make_ai_pick_fb and handle_make_pick.

    RETURNS:
        None.
    """
    path = Path("drafts") / f"{draftname}_fb_meta.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def normalize_football_pos(raw_pos, default='WR'):
    """
    PURPOSE:
        Turn the football data's free-text position (like "FL SE" or "rb") into one clean code
        (WR, TE, HB, FB, QB, DO, KP) using FOOTBALL_POS_MAP.

    ARGUMENTS:
        raw_pos (str) -- the "Positions" text from the data. Must contain at least one word.
        default (str) -- the code to use when the first word isn't in FOOTBALL_POS_MAP.

    CALLED BY:
        - services.py: load_football (in several places: every file that has a Positions column).

    RETURNS:
        str -- the cleaned position code.
        Heads-up: an EMPTY Positions value (nothing but spaces) raises an IndexError here, so make
        sure every football record has some text in Positions.
    """
    # take first token — "FL SE" → "FL"
    first = raw_pos.strip().split()[0].upper()
    return FOOTBALL_POS_MAP.get(first, default)


# =============================================================================================
# 7. MISC: TEAM NAMES, SHORT POSITIONS, SNAKE ORDER, THE PICK LOG
# =============================================================================================

def get_team_names(num_teams, sport, human_team_name):
    """
    PURPOSE:
        Supply the fictional team names. Each sport has a list of 32 names (below). This function
        either returns the whole list (for the team-picker grid on the setup page) or picks random
        AI team names that don't collide with the human teams.

        >>> TO RENAME, ADD OR REMOVE A TEAM, EDIT THE LISTS IN THIS FUNCTION. <<<
        The name is also used to find the team's logo picture
        (Logos/fictional/<sport>/<Name>_<bb|bk|fb>.png), so the picture's file name must match the
        spelling here exactly.

    ARGUMENTS:
        num_teams       (int)       -- how many AI team names to pick (only used when there are human
                                       teams to avoid).
        sport           (str)       -- "bk", "bb" or anything else (treated as football).
        human_team_name (list[str]) -- the names the humans picked. They are removed from the choices
                                       so an AI team can't get the same name. Pass an empty list to get
                                       the complete list back.

    CALLED BY:
        - routes.py: show_bb_logos, show_bk_logos, show_fb_logos (human_team_name = [], so they get
                     all 32 names for the picker grid) and bb_confirm, bk_confirm, fb_confirm (they
                     ask for num_teams minus the number of human teams).

    RETURNS:
        numpy.ndarray of str -- either all 32 names (when human_team_name is empty) or exactly
        num_teams random names that exclude the human teams. Raises ValueError if more names are
        requested than remain.
    """
    # ------------------------------ BASKETBALL ------------------------------
    if sport == "bk":
        bk_names = np.array(["Aliens", "Armadillos", "Aztecs", "Black Crows", "Bloom", "Blues", "Cyclones",
        "Dolphins", "Dragons", "Drillers", "Explorers", "Gorillas", "Heroes", "Hunters", "Ice Hawks", "Monarchs",
        "Muskateers", "Nationalists", "Pandas", "Quake", "Rays", "Razor Bats", "Rebels", "Sabers", "Shock",
        "Sorcerers", "Stallions", "Thieves", "Undead", "Vikings", "Wolfpack", "Zombies"])
        if not human_team_name:
            return bk_names                       # no humans to avoid: hand back the full list
        #np.isin filters out anything in human_team_name from being randomly selected.
        # (np.isin marks which names are in the human list; the ~ flips it to keep the OTHERS.)
        available = bk_names[~np.isin(bk_names, human_team_name)]
        return np.random.choice(available, size=num_teams, replace=False)   # replace=False = no repeats

    # ------------------------------ BASEBALL ------------------------------
    elif sport == "bb":
        bb_names = np.array(["Aces", "Arrows", "Badgers", "Bandits", "Barons", "Bombers", "Buccaneers", "Buckeyes",
            "Claws", "Comets", "Copperheads", "Expos", "Falcons", "Gators", "Greyhounds", "Irish", "Jesters", "Monsters",
            "Neptunes", "Nitros", "Oilers", "Pioneers", "Quest", "Rams", "Rockers", "Scorpions", "Sharks", "Stars",
            "Storm", "Twisters", "Warriors", "Wizards"])
        if not human_team_name:
            return bb_names
        available = bb_names[~np.isin(bb_names, human_team_name)]
        return np.random.choice(available, size=num_teams, replace=False)

    # ------------------------------ FOOTBALL (the "else") ------------------------------
    else:
        fb_names = np.array(["Admirals", "Aeros", "Aztecs", "Badgers", "Blaze", "Bruisers", "Cossacks", "Cougars",
            "Cruisers", "Dukes", "Generals", "Gladitors", "Hawks", "Hilltoppers", "Ironclads", "Jackrabbits", "Lunar Cats",
            "Miners", "Orcas", "Pilots", "Polar Bears", "Rebels", "Roadsters", "Sabers", "Samurai", "Seals", "Settlers",
            "Sharks", "Storm", "Thunder", "Truckers", "Vultures"])
        if not human_team_name:
            return fb_names
        available = fb_names[~np.isin(fb_names, human_team_name)]
        return np.random.choice(available, size=num_teams, replace=False)


def compute_short_pos(kind: str, person: dict) -> str:
    """
    PURPOSE:
        Work out a baseball player's roster position code from the Strat-O-Matic text fields:
          hitters  -> the FIRST position in "s_fielding" (like "ss-3e20 2b-4e18" gives "SS"),
                      or "DH" if the field is empty
          pitchers -> "SP" if "s_endurance" starts with S, "RP" if it starts with R or C (closers
                      count as relievers), "SP" if the field is empty or unclear

    ARGUMENTS:
        kind   (str)  -- "hitter" or "pitcher".
        person (dict) -- the player's record.

    CALLED BY:
        - services.py: load_baseball (once per hitter and pitcher, in both the full/custom and the
                       random branches, and again when building the twin "universe").

    RETURNS:
        str -- "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH" for hitters (whatever text comes
               first in s_fielding is used), "SP" or "RP" for pitchers, or "" for any other kind.
    """
    # ---------------- hitters: read the first fielding position ----------------
    if kind == "hitter":
        raw = person.get("s_fielding", "").strip()
        if not raw:
            return "DH"                                  # no fielding info: designated hitter
        # first word ("ss-3e20"), then the part before the first "-" ("ss"), uppercased ("SS")
        primary = raw.split()[0].split("-")[0].upper()
        return primary if primary else "DH"

    # ---------------- pitchers: read the endurance code ----------------
    if kind == "pitcher":
        raw = person.get("s_endurance", "").strip()
        if not raw:
            return "SP"  # fallback if missing
        first = raw[0].upper()                           # first letter: S(tarter), R(eliever), C(loser)
        if first == "S":
            return "SP"
        if first == "R":
            return "RP"
        if first == "C":
            return "RP"
        return "SP"  # safe default

    return ""     # not a kind we know about


def get_next_team_id(meta):
    """
    PURPOSE:
        Work out which team picks at pick number meta["current_pick"], following SNAKE order:
        round 1 goes first team to last, round 2 goes last to first, round 3 forward again, and so on.
        The teams list in the meta file is already in round-1 order.

        IMPORTANT: it reads meta["current_pick"], so it must be called AFTER that number has been
        increased (the callers do "current_pick += 1" first). It answers "who picks NEXT?".

    ARGUMENTS:
        meta (dict) -- the draft's meta dict. Uses "num_teams", "current_pick" and "teams".

    CALLED BY:
        - routes.py: make_ai_pick_bb, make_ai_pick_bk, make_ai_pick_fb and handle_make_pick.

    RETURNS:
        int -- the team_id of the team that is on the clock for meta["current_pick"].
    """
    num_teams = meta["num_teams"]
    pick = meta["current_pick"]
    teams = meta["teams"]
    # snake order: picks 1-8 go forward, 9-16 go backward, etc.
    round_num = (pick - 1) // num_teams  # 0-indexed round (// is whole-number division)
    pick_in_round = (pick - 1) % num_teams   # 0-indexed position inside the round (% is the remainder)
    if round_num % 2 == 0:
        # even-numbered rounds (round 1, 3, ...): forward
        idx = pick_in_round
    else:
        # odd-numbered rounds (round 2, 4, ...): reverse
        idx = num_teams - 1 - pick_in_round
    return teams[idx]["team_id"]


def get_team_by_id(meta, team_id):
    """
    PURPOSE:
        Find one team's entry in the meta file by its team_id.

    ARGUMENTS:
        meta    (dict) -- the draft's meta dict (uses its "teams" list).
        team_id (int)  -- the id to look for.

    CALLED BY:
        - routes.py: bb_load, bb_draft, bb_team_json, bk_load, bk_draft, fb_load, fb_draft, the three
                     make_ai_pick_* functions, the three run_ai_picks_* functions, handle_make_pick,
                     handle_skip_pick, handle_request_sync and handle_start_draft.

    RETURNS:
        dict | None -- the team's dict ({"team_id", "team_name", "type", ...}), or None if no team has
                       that id.
    """
    # next(generator, None): take the first match, or None if there isn't one.
    return next((t for t in meta["teams"] if t["team_id"] == team_id), None)


def append_to_log(log_path, entry):
    """
    PURPOSE:
        Add one pick to the end of a draft's pick-log file. It reads the whole log, adds the entry,
        and writes the whole log back (simple, but not safe for two writers at the same moment).

    ARGUMENTS:
        log_path (Path) -- the log file, e.g. drafts/FallLeague_bb_log.json.
        entry    (dict) -- the log entry: pick, team_id, team, player, pos, id, and so on. A two-way
                           twin's entry has "is_bonus": True.

    CALLED BY:
        - routes.py: make_ai_pick_bb, make_ai_pick_bk, make_ai_pick_fb and handle_make_pick (the
                     latter two also call it a second time for a two-way twin).

    RETURNS:
        None.
    """
    with open(log_path, "r", encoding="utf-8") as f:
        log = json.load(f)
    log.append(entry)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)



# =============================================================================================
# 8. SLOT MATCHING (WHICH ROSTER SLOT DOES A PICK LAND IN?)
# =============================================================================================
# Three small lookup tables, then three functions (one per sport) that turn a team's list of picks
# into a filled-in roster. The AI and the roster panel both use these so they always agree.

# Baseball: the position code a pick has -> the roster slot label it naturally fills.
#   A pitcher's SP/RP/CL codes map to S (starter) and R (reliever) slots. A position that isn't in
#   this table (such as "DH") falls back to "UT" in the code that uses it.
SHORT_POS_TO_SLOT_BB = {
    'C': 'C', '1B': '1B', '2B': '2B', '3B': '3B', 'SS': 'SS',
    'LF': 'LF', 'CF': 'CF', 'RF': 'RF', 'SP': 'S', 'RP': 'R', 'CL': 'R',
}

# Football: position code -> roster slot label. Defense/OL units (DO) fill the "Def" slot and
# special-teams units (KP) fill the "Special" slot.
SHORT_POS_TO_SLOT_FB = {
    'QB': 'QB', 'HB': 'HB', 'FB': 'FB', 'TE': 'TE', 'WR': 'WR',
    'DO': 'Def', 'KP': 'Special',
}

# Football: halfbacks and fullbacks may fill each other's slots once their own are full.
HB_FB_OVERFLOW = {'HB': 'FB', 'FB': 'HB'}

# Basketball: position code -> slot label. "DEF" (a defense unit) fills the "Def" slot.
SHORT_POS_TO_SLOT_BK = {
    'C': 'C', 'F': 'F', 'G': 'G', 'DEF': 'Def',
}


def assign_picks_to_slots_bb(roster_slots, team_picks):
    """
    Match each drafted player (in draft order) to a roster slot by position.
    roster_slots: template list, e.g. ["C","C","1B",...,"UT","UT",...,"S","S",...,"R","R",...]
                  plus one "FLEX" per two-way bonus player on this team.
    team_picks: this team's log entries, in the order they were drafted.
    Priority: natural slot, then UT (hitters only), then FLEX (anyone), then any open slot.
    Returns a list the same length as roster_slots, each entry either the matching
    log entry dict or None if that slot is still open.

    PURPOSE:
        Turn a baseball team's list of picks into a filled-in roster, deciding which pick sits in
        which slot. Used to draw the roster panel, and by the AI to know which slots are STILL open.

    ARGUMENTS:
        roster_slots (list[str])  -- the team's slot labels, in display order (25 labels, plus one
                                     "FLEX" per two-way player the team drafted).
        team_picks   (list[dict]) -- this team's pick-log entries, oldest first. Only each entry's
                                     "pos" is read.

    CALLED BY:
        - routes.py: bb_load and bb_draft (to draw each team's roster).
        - ai.py:     open_position_lottery, open_slot_counts_bb, and the _ASSIGN table behind
                     open_slot_labels (which the cap checker uses).

    RETURNS:
        list -- the same length as roster_slots; each position holds that slot's pick-log entry
                (a dict) or None when the slot is still empty.
    """
    # One empty box per slot.
    assigned = [None] * len(roster_slots)

    # open_by_label groups the slot POSITIONS by label, like {"C": [0, 1], "UT": [9, 10, 11...]}.
    # As slots get filled, their index is removed (pop) from the list.
    open_by_label = {}
    for i, label in enumerate(roster_slots):
        open_by_label.setdefault(label, []).append(i)

    # Go through the picks in the order they were made so earlier picks claim natural slots first.
    for pick in team_picks:
        slot_label = SHORT_POS_TO_SLOT_BB.get(pick.get('pos', ''), 'UT')    # unknown position -> UT
        target = None

        if open_by_label.get(slot_label):
            # 1) his natural slot has room
            target = open_by_label[slot_label].pop(0)
        elif slot_label not in ('S', 'R') and open_by_label.get('UT'):
            # 2) overflow into UT, but only hitters (pitchers never take a UT slot)
            target = open_by_label['UT'].pop(0)
        elif open_by_label.get('FLEX'):
            # 3) a FLEX slot takes anybody
            target = open_by_label['FLEX'].pop(0)
        else:
            # 4) last resort: any slot at all that still has room
            for label, indices in open_by_label.items():
                if indices:
                    target = indices.pop(0)
                    break

        if target is not None:
            assigned[target] = pick

    return assigned


def assign_picks_to_slots_bk(roster_slots, team_picks):
    """
    C/F/G are their own buckets; once a position's slots are full, the pick overflows into UT.
    A defense unit only ever goes in the Def slot, and players never take the Def slot.

    PURPOSE:
        The basketball version of assign_picks_to_slots_bb: decide which slot each of a team's picks
        sits in.

    ARGUMENTS:
        roster_slots (list[str])  -- the team's slot labels (12: C, F, F, G, G, six UT, Def).
        team_picks   (list[dict]) -- this team's pick-log entries, oldest first. Only "pos" is read.

    CALLED BY:
        - routes.py: bk_load and bk_draft (roster display).
        - ai.py:     open_position_lottery_bk and the _ASSIGN table behind open_slot_labels.

    RETURNS:
        list -- the same length as roster_slots; each position holds the pick-log entry (dict) in
                that slot, or None if empty.
    """
    assigned = [None] * len(roster_slots)
    open_by_label = {}
    for i, label in enumerate(roster_slots):
        open_by_label.setdefault(label, []).append(i)

    for pick in team_picks:
        slot_label = SHORT_POS_TO_SLOT_BK.get(pick.get('pos', ''), 'UT')
        target = None

        if slot_label == 'Def':
            # A defense unit goes ONLY in the Def slot. If that's already taken he gets no slot.
            if open_by_label.get('Def'):
                target = open_by_label['Def'].pop(0)
        elif open_by_label.get(slot_label):
            target = open_by_label[slot_label].pop(0)       # his own position (C, F or G)
        elif open_by_label.get('UT'):
            target = open_by_label['UT'].pop(0)             # overflow into UT
        else:
            # Last resort: any open slot EXCEPT Def (players never take the Def slot).
            for label, indices in open_by_label.items():
                if label != 'Def' and indices:
                    target = indices.pop(0)
                    break

        if target is not None:
            assigned[target] = pick

    return assigned



def assign_picks_to_slots_fb(roster_slots, team_picks):
    """
    QB/TE/WR/Def/Special are each their own strict bucket. HB and FB share a pool.
    A pick that doesn't fit its own slot goes to a FLEX slot (takes anyone), then to any open slot.

    PURPOSE:
        The football version of assign_picks_to_slots_bb: decide which slot each of a team's picks
        sits in.

    ARGUMENTS:
        roster_slots (list[str])  -- the team's slot labels (13: QB x2, HB x2, FB, TE x2, WR x4, Def,
                                     Special; plus one "FLEX" per two-way player).
        team_picks   (list[dict]) -- this team's pick-log entries, oldest first. Only "pos" is read.

    CALLED BY:
        - routes.py: fb_load and fb_draft (roster display).
        - ai.py:     open_position_lottery_fb and the _ASSIGN table behind open_slot_labels.

    RETURNS:
        list -- the same length as roster_slots; each position holds the pick-log entry (dict) in
                that slot, or None if empty.
    """
    assigned = [None] * len(roster_slots)
    open_by_label = {}
    for i, label in enumerate(roster_slots):
        open_by_label.setdefault(label, []).append(i)

    for pick in team_picks:
        # '' (blank) for a position we don't recognise: it then skips the first two checks.
        slot_label = SHORT_POS_TO_SLOT_FB.get(pick.get('pos', ''), '')
        target = None

        if slot_label and open_by_label.get(slot_label):
            # 1) his own slot has room
            target = open_by_label[slot_label].pop(0)
        elif slot_label in HB_FB_OVERFLOW and open_by_label.get(HB_FB_OVERFLOW[slot_label]):
            # 2) an HB may take an open FB slot, and an FB an open HB slot
            target = open_by_label[HB_FB_OVERFLOW[slot_label]].pop(0)
        elif open_by_label.get('FLEX'):
            # 3) FLEX takes anybody
            target = open_by_label['FLEX'].pop(0)
        else:
            # 4) last resort: any slot with room
            for label, indices in open_by_label.items():
                if indices:
                    target = indices.pop(0)
                    break

        if target is not None:
            assigned[target] = pick

    return assigned


# =============================================================================================
# 9. TWO-WAY PLAYERS
# =============================================================================================
# A two-way player is stored as TWO records (for example Ohtani the hitter and Ohtani the pitcher).
# These helpers find each record's twin so that drafting one drafts the other.

def norm_name(s):
    """Lower-case, accent-free, single-spaced, so 'Álex  Rodríguez' matches 'alex rodriguez'.

    PURPOSE:
        Make a name safe to compare: lowercase, accents removed, and extra spaces squeezed to one.
        Used so the two-way name lists match the data even if capitals, accents or spacing differ.

    ARGUMENTS:
        s (str | None) -- any text. None is treated as an empty string.

    CALLED BY:
        - services.py: _record_name, build_twin_map and twin_report.

    RETURNS:
        str -- the cleaned text, e.g. "alex rodriguez".
    """
    # NFD splits "á" into "a" + an accent mark; encode("ascii", "ignore") then drops the accent mark.
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode()
    # split() with no arguments splits on any run of spaces, and " ".join puts back single spaces.
    return " ".join(s.lower().split())


def _record_name(p):
    """
    PURPOSE:
        Get a player's full name, cleaned for comparison.

    ARGUMENTS:
        p (dict) -- a player record (uses its "FirstName" and "LastName").

    CALLED BY:
        - services.py: build_twin_map and twin_report.

    RETURNS:
        str -- the name cleaned by norm_name, e.g. "shohei ohtani".
    """
    return norm_name(f"{p.get('FirstName', '')} {p.get('LastName', '')}")


def build_twin_map(players, names, kinds):
    """{player id: twin player id} for the listed two-way names.

    PURPOSE:
        Find each two-way player's two records and link them to each other. A name is only linked
        if EXACTLY TWO records match it and they are of different kinds (one hitter and one pitcher,
        say). Anything else is ignored, which is why a misspelled name quietly does nothing; use
        /twin_check to see.

    ARGUMENTS:
        players (list[dict]) -- the records to search (must have "kind" and "id").
        names   (list[str])  -- the two-way names, e.g. TWO_WAY_NAMES_BB.
        kinds   (tuple[str]) -- which kinds of record can be a twin, e.g. ("hitter", "pitcher").

    CALLED BY:
        - services.py: twin_map_for and twin_report.

    RETURNS:
        dict -- {id: twin's id} with an entry in BOTH directions, e.g.
                {"h_12": "p_8", "p_8": "h_12"}. Empty if nothing matched.
    """
    wanted = {norm_name(n) for n in names}          # a set of cleaned names for quick lookup
    by_name = {}                                    # {clean name: [the records with that name]}
    for p in players:
        if p.get("kind") not in kinds:
            continue                                # not a kind that can be two-way
        key = _record_name(p)
        if key in wanted:
            by_name.setdefault(key, []).append(p)

    twins = {}
    for recs in by_name.values():
        # Exactly two records, and they must be different kinds (not two hitters with one name).
        if len(recs) == 2 and recs[0].get("kind") != recs[1].get("kind"):
            a, b = str(recs[0].get("id")), str(recs[1].get("id"))
            twins[a] = b
            twins[b] = a
    return twins


def twin_map_for(sport, players):
    """
    PURPOSE:
        Build the twin map for one sport, using that sport's two-way name list and kinds. This is the
        function the rest of the app calls; it hides which list belongs to which sport.

    ARGUMENTS:
        sport   (str)        -- "bb" or "fb". Any other sport (basketball) has no two-way players.
        players (list[dict]) -- the records to search.

    CALLED BY:
        - services.py: add_twins.
        - routes.py:   maybe_add_twin_bb and maybe_add_twin_fb (to find the bonus player on a pick).
        - ai.py:       make_cap_checker (so the cap math counts a twin's salary too).

    RETURNS:
        dict -- {id: twin's id} in both directions (see build_twin_map); {} for basketball.
    """
    if sport == "bb":
        return build_twin_map(players, TWO_WAY_NAMES_BB, ("hitter", "pitcher"))
    if sport == "fb":
        return build_twin_map(players, TWO_WAY_NAMES_FB, ("passer", "rusher", "receiver"))
    return {}


def add_twins(people, universe, sport):
    """Random / Custom pools: if one record of a two-way player made the pool, add his other record too.
    universe = every record for the sport (used to find the twin).

    PURPOSE:
        Keep two-way players whole. If a Random or Custom pool contains one record of a two-way
        player but not the other, append the missing record so both are in the draft.

    ARGUMENTS:
        people   (list[dict]) -- the pool as chosen so far.
        universe (list[dict]) -- EVERY record for the sport, used to find a twin that isn't in
                                 `people` yet.
        sport    (str)        -- "bb" or "fb".

    CALLED BY:
        - services.py: load_baseball and load_football (their random branches).
        - routes.py:   bb_confirm and fb_confirm (after a Custom pool's checkboxes are applied).

    RETURNS:
        list[dict] -- `people` plus any missing twins at the end (the original list is not changed).
    """
    twins = twin_map_for(sport, universe)
    have  = {str(p.get("id")) for p in people}                 # ids already in the pool
    by_id = {str(p.get("id")): p for p in universe}            # id -> record, for looking twins up
    extra = []
    for pid in list(have):
        tid = twins.get(pid)                                   # this player's twin id, if any
        if tid and tid not in have and tid in by_id:
            extra.append(by_id[tid])
            have.add(tid)                                      # so we never add the same twin twice
    return people + extra


def twin_report(sport, players):
    """Plain-text check of how each listed two-way name matches up in the data.

    PURPOSE:
        A diagnostic: for every name in the sport's two-way list, show which records it matched and
        whether a proper pair was found. Shows up on the /twin_check/bb and /twin_check/fb pages.

    ARGUMENTS:
        sport   (str)        -- "bb" for baseball; anything else is treated as football.
        players (list[dict]) -- the full pool (for example load_baseball("full", 8)).

    CALLED BY:
        - routes.py: twin_check.

    RETURNS:
        list[str] -- one line per name, like
            "OK       Shohei Ohtani: hitter h_501 (DH), pitcher p_88 (SP)"
            "PROBLEM  Bullet Rogan: no records found"
        PROBLEM means the name wasn't found exactly twice with two different kinds.
    """
    if sport == "bb":
        names, kinds = TWO_WAY_NAMES_BB, ("hitter", "pitcher")
    else:
        names, kinds = TWO_WAY_NAMES_FB, ("passer", "rusher", "receiver")
    twins = build_twin_map(players, names, kinds)
    lines = []
    for name in names:
        key = norm_name(name)
        # Every record whose cleaned name matches this one.
        recs = [p for p in players if p.get("kind") in kinds and _record_name(p) == key]
        detail = ", ".join(f"{p.get('kind')} {p.get('id')} ({p.get('short_pos', '')})" for p in recs) or "no records found"
        ok = any(str(p.get("id")) in twins for p in recs)      # did the pair get linked?
        lines.append(f"{'OK     ' if ok else 'PROBLEM'}  {name}: {detail}")
    return lines


def duplicate_id_report(sport):
    """Counts records that share an ID. The loader keeps only one record per ID, so duplicates make players vanish.

    PURPOSE:
        A diagnostic: download each data file for the sport and count how many IDs appear more than
        once. Duplicate IDs are dangerous because _index_by_id keeps only one record per ID, so the
        others silently disappear from the draft.

    ARGUMENTS:
        sport (str) -- "bb" for baseball's two files; anything else is treated as football's five.
                       (Basketball isn't covered.)

    CALLED BY:
        - routes.py: twin_check (shown under the twin report on /twin_check/<sport>).

    RETURNS:
        list[str] -- one line per data file, like
            "batters: 2213 records, 0 duplicate IDs"
            "pitchers: 1800 records, 2 duplicate IDs  (e.g. 412, 977)"
        or a line saying the file couldn't be read / isn't a list.
    """
    if sport == "bb":
        files = [("batters", input_file_baseball_hitters), ("pitchers", input_file_baseball_pitchers)]
    else:
        files = [("passing", input_file_football_passing), ("rushing", input_file_football_rushing),
                 ("receiving", input_file_football_receiving), ("def/ol", input_file_football_def_ol),
                 ("special", input_file_football_special)]
    lines = []
    for label, url in files:
        try:
            data = _read_json(url)
        except Exception as exc:
            lines.append(f"{label}: could not read ({exc})")
            continue
        if not isinstance(data, list):
            lines.append(f"{label}: not a list, skipped")
            continue
        # The same ID lookup _index_by_id uses (ID, then _id, then id).
        ids = [str(r.get("ID") or r.get("_id") or r.get("id")) for r in data]
        # Counter counts how often each id appears; keep the ones seen more than once.
        dupes = [i for i, n in Counter(ids).items() if n > 1]
        extra = f"  (e.g. {', '.join(dupes[:5])})" if dupes else ""
        lines.append(f"{label}: {len(data)} records, {len(dupes)} duplicate IDs{extra}")
    return lines