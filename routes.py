from flask import Blueprint, render_template, request, abort, current_app
from .services import (
    load_baseball,
    load_basketball,
    load_football,
    load_hitters_json,
    load_pitchers_json,
    load_basketball_json, 
    load_football_json,
    initial_save_baseball_json, 
    initial_save_baseball_meta_json,
    initial_save_baseball_log_json, 
    initial_save_basketball_json, 
    initial_save_basketball_meta_json,
    initial_save_basketball_log_json,
    get_saved_baseball_drafts,
    load_saved_baseball_draft,
    get_saved_basketball_drafts,
    load_saved_basketball_draft,
    get_team_names, 
    get_person, 
    positions, 
    sort_people, 
    get_next_team_id,
    get_team_by_id,
    append_to_log
)
from datetime import datetime
import random
import json
from pathlib import Path
from flask_socketio import emit
from . import socketio



main = Blueprint("main", __name__)

@main.route("/")
def index():
    #return "<h1>Using Blueprint</h1>"
    return render_template("index.html")

@main.route("/baseball")
def start_baseball():
    #people = load_baseball()
    saved_drafts = get_saved_baseball_drafts()
    return render_template("baseball.html", saved_drafts=saved_drafts)

@main.route("/show_bb_logos")
def show_bb_logos():
    human_teams = []
    num_teams = int(request.args.get("num_teams", 1))
    bb_set = get_team_names(32, "bb", human_teams)
    return render_template("partials/show_logos.html", names=bb_set, sport="baseball")

@main.route("/bb_load", methods=["POST"])
def bb_load():
    filename = request.form.get("saved_draft_file", "").strip()

    if not filename:
        abort(400, "No draft file selected.")

    try:
        draft_data = load_saved_baseball_draft(filename)
    except FileNotFoundError:
        abort(404, "Draft file not found.")
    except ValueError as exc:
        abort(400, str(exc))

    meta = draft_data.get("meta", {})
    log = draft_data.get("log", [])
    players = draft_data.get("players", [])

    human_teams = []
    ai_set = []

    for team in meta.get("teams", []):
        if team.get("type") == "human":
            human_teams.append(team.get("team_name"))
        else:
            ai_set.append(team.get("team_name"))

    return render_template(
        "bbdraft.html",
        num_teams=meta.get("num_teams", 0),
        human_teams=human_teams,
        ai_set=ai_set,
        pool=meta.get("pool", ""),
        cap=meta.get("cap", ""),
        draftname=meta.get("draftname", draft_data.get("draftname", "")),
        players=players,
        draft_log=log,
        draft_file=str(draft_data.get("player_path", "")),
        meta_file=str(draft_data.get("meta_path", "")),
        log_file=str(draft_data.get("log_path", ""))
    )

@main.route("/bb_confirm", methods=["POST"])
def bb_confirm():
    num_teams = int(request.form.get("num_teams"))
    human_teams = request.form.getlist("human_teams")
    pool = request.form.get("pool")
    cap = request.form.get("cap")
    draftname = request.form.get("draftname")
    selected_player_ids = request.form.getlist("selected_player_ids")
    ai_set = request.form.getlist("ai_set")
    confirm_stage = request.form.get("confirm_stage")

    num_human_teams = len(human_teams)

    if not ai_set:
        ai_set = get_team_names(
            num_teams - num_human_teams,
            "bb",
            human_teams
        )

    # FULL: final list immediately
    if pool == "full":
        people = load_baseball("full", num_teams)
        mode = "final_confirm"

    # RANDOM: final random list immediately
    elif pool == "random":
        people = load_baseball("random", num_teams)
        mode = "final_confirm"

    # CUSTOM, first visit: show all players with checkboxes
    elif pool == "custom" and not selected_player_ids:
        people = load_baseball("custom", num_teams)
        mode = "select_players"

    # CUSTOM, second visit: user selected players, now show final list
    elif pool == "custom" and selected_player_ids:
        all_players = load_baseball("custom", num_teams)

        selected_id_set = set(str(x) for x in selected_player_ids)

        people = [
            p for p in all_players
            if str(p.get("ID")) in selected_id_set or str(p.get("id")) in selected_id_set
        ]

        mode = "final_confirm"

    else:
        raise ValueError(f"Unknown pool type: {pool}")

    return render_template(
        "bb_confirm.html",
        num_teams=num_teams,
        human_teams=human_teams,
        ai_set=ai_set,
        pool=pool,
        draftname=draftname,
        cap=cap,
        players=people,
        mode=mode
    )

@main.route("/bb_draft", methods=["POST"])
def bb_draft():
    num_teams     = int(request.form.get("num_teams"))
    human_teams   = request.form.getlist("human_teams")
    ai_set        = request.form.getlist("ai_set")
    pool          = request.form.get("pool")
    cap           = request.form.get("cap")
    draftname     = request.form.get("draftname")
    selected_ids  = request.form.getlist("selected_player_ids")

    all_players = load_baseball("full", num_teams)

    if pool == "full":
        people = all_players
    else:
        id_set = set(str(x) for x in selected_ids)
        people = [p for p in all_players if str(p.get("id")) in id_set]

    # Build a unified team list: human teams first, then AI
    # Each entry is a dict with name + is_human flag
    all_teams = [{"name": t, "is_human": True}  for t in human_teams] + \
                [{"name": t, "is_human": False} for t in ai_set]

    # Chunk teams into rows of 8 for the logo strip
    logo_rows = [all_teams[i:i+8] for i in range(0, len(all_teams), 8)]

    # Roster slot labels for basketball (2 of each position)
    roster_slots = ["C", "C", "1B", "2B", "SS", "3B", "LF", "CF", "RF", "UT", "UT", "UT", "UT", "UT", "UT", "S", "S", "S", "S", "S", "R", "R", "R", "R", "R"]

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = initial_save_baseball_json(people, draftname, timestamp)
    meta_path   = initial_save_baseball_meta_json(
                      draftname, num_teams, human_teams,
                      ai_set, pool, cap, output_path, timestamp)
    log_path    = initial_save_baseball_log_json(draftname, timestamp)

    if not log_path.exists():
        initial_save_baseball_log_json(draftname)

    with open(log_path, "r", encoding="utf-8") as f:
        draft_log = json.load(f)

    return render_template(
        "bbdraft.html",
        all_teams=all_teams,
        logo_rows=logo_rows,
        roster_slots=roster_slots,
        pool=pool,
        cap=cap,
        draftname=draftname,
        players=people,
        draft_file=output_path,
        draft_log=draft_log,
        sport="bb"
    )

#-------- BASKETBALL -----------------------------------------------------------------

@main.route("/basketball")
def start_basketball():
    saved_drafts = get_saved_basketball_drafts()
    return render_template("basketball.html", saved_drafts=saved_drafts)


@main.route("/show_bk_logos")
def show_bk_logos():
    human_teams = []
    num_teams = int(request.args.get("num_teams", 1))
    bk_set = get_team_names(32, "bk", human_teams)
    return render_template("partials/show_logos.html", names=bk_set, sport="basketball")

@main.route("/bk_load", methods=["POST"])
def bk_load():
    filename = request.form.get("saved_draft_file", "").strip()

    if not filename:
        abort(400, "No draft file selected.")

    try:
        draft_data = load_saved_basketball_draft(filename)
    except FileNotFoundError:
        abort(404, "Draft file not found.")
    except ValueError as exc:
        abort(400, str(exc))

    meta = draft_data.get("meta", {})
    log = draft_data.get("log", [])
    players = draft_data.get("players", [])

    human_teams = []
    ai_set = []

    for team in meta.get("teams", []):
        if team.get("type") == "human":
            human_teams.append(team.get("team_name"))
        else:
            ai_set.append(team.get("team_name"))

    return render_template(
        "bkdraft.html",
        num_teams=meta.get("num_teams", 0),
        human_teams=human_teams,
        ai_set=ai_set,
        pool=meta.get("pool", ""),
        cap=meta.get("cap", ""),
        draftname=meta.get("draftname", draft_data.get("draftname", "")),
        players=players,
        draft_log=log,
        draft_file=str(draft_data.get("player_path", "")),
        meta_file=str(draft_data.get("meta_path", "")),
        log_file=str(draft_data.get("log_path", ""))
    )

@main.route("/bk_confirm", methods=["POST"])
def bk_confirm():
    num_teams = int(request.form.get("num_teams"))
    human_teams = request.form.getlist("human_teams")
    pool = request.form.get("pool")
    cap = request.form.get("cap")
    draftname = request.form.get("draftname")
    selected_player_ids = request.form.getlist("selected_player_ids")
    ai_set = request.form.getlist("ai_set")
    confirm_stage = request.form.get("confirm_stage")

    num_human_teams = len(human_teams)

    if not ai_set:
        ai_set = get_team_names(
            num_teams - num_human_teams,
            "bk",
            human_teams
        )

    # FULL: final list immediately
    if pool == "full":
        people = load_basketball("full", num_teams)
        mode = "final_confirm"

    # RANDOM: final random list immediately
    elif pool == "random":
        people = load_basketball("random", num_teams)
        mode = "final_confirm"

    # CUSTOM, first visit: show all players with checkboxes
    elif pool == "custom" and not selected_player_ids:
        people = load_basketball("custom", num_teams)
        mode = "select_players"

    # CUSTOM, second visit: user selected players, now show final list
    elif pool == "custom" and selected_player_ids:
        all_players = load_basketball("custom", num_teams)

        selected_id_set = set(str(x) for x in selected_player_ids)

        people = [
            p for p in all_players
            if str(p.get("ID")) in selected_id_set or str(p.get("id")) in selected_id_set
        ]

        mode = "final_confirm"

    else:
        raise ValueError(f"Unknown pool type: {pool}")

    return render_template(
        "bk_confirm.html",
        num_teams=num_teams,
        human_teams=human_teams,
        ai_set=ai_set,
        pool=pool,
        draftname=draftname,
        cap=cap,
        players=people,
        mode=mode
    )

'''
@main.route("/bk_draft", methods=["POST"])
def bk_draft():
    num_teams = int(request.form.get("num_teams"))
    human_teams = request.form.getlist("human_teams")
    ai_set = request.form.getlist("ai_set")
    pool = request.form.get("pool")
    cap = request.form.get("cap")
    draftname = request.form.get("draftname")
    selected_player_ids = request.form.getlist("selected_player_ids")

    all_players = load_basketball("full", num_teams)

    if pool == "full":
        people = all_players
    else:
        selected_id_set = set(str(x) for x in selected_player_ids)

        people = [
            p for p in all_players
            if str(p.get("ID")) in selected_id_set or str(p.get("id")) in selected_id_set
        ]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_path = initial_save_basketball_json(people, draftname, timestamp)
    meta_path = initial_save_basketball_meta_json(
        draftname,
        num_teams,
        human_teams,
        ai_set,
        pool,
        cap,
        output_path,
        timestamp
    )
    log_path = initial_save_basketball_log_json(draftname, timestamp)

    return render_template(
        "bkdraft.html",
        num_teams=num_teams,
        human_teams=human_teams,
        ai_set=ai_set,
        pool=pool,
        cap=cap,
        draftname=draftname,
        players=people,
        draft_file=output_path
    )   
'''


@main.route("/bk_draft", methods=["POST"])
def bk_draft():
    num_teams     = int(request.form.get("num_teams"))
    human_teams   = request.form.getlist("human_teams")
    ai_set        = request.form.getlist("ai_set")
    pool          = request.form.get("pool")
    cap           = request.form.get("cap")
    draftname     = request.form.get("draftname")
    selected_ids  = request.form.getlist("selected_player_ids")

    all_players = load_basketball("full", num_teams)

    if pool == "full":
        people = all_players
    else:
        id_set = set(str(x) for x in selected_ids)
        people = [p for p in all_players if str(p.get("id")) in id_set]

    # Build a unified team list: human teams first, then AI
    # Each entry is a dict with name + is_human flag
    all_teams = [{"name": t, "is_human": True}  for t in human_teams] + \
                [{"name": t, "is_human": False} for t in ai_set]

    # Chunk teams into rows of 8 for the logo strip
    logo_rows = [all_teams[i:i+8] for i in range(0, len(all_teams), 8)]

    # Roster slot labels for basketball (2 of each position)
    roster_slots = ["C", "C", "PF", "PF", "SF", "SF", "SG", "SG", "PG", "PG"]

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = initial_save_basketball_json(people, draftname, timestamp)
    meta_path   = initial_save_basketball_meta_json(
                      draftname, num_teams, human_teams,
                      ai_set, pool, cap, output_path, timestamp)
    log_path    = initial_save_basketball_log_json(draftname, timestamp)

    if not log_path.exists():
        initial_save_baseball_log_json(draftname)

    with open(log_path, "r", encoding="utf-8") as f:
        draft_log = json.load(f)

    return render_template(
        "bkdraft.html",
        all_teams=all_teams,
        logo_rows=logo_rows,
        roster_slots=roster_slots,
        pool=pool,
        cap=cap,
        draftname=draftname,
        players=people,
        draft_file=output_path,
        draft_log=draft_log,
        sport="bk"
    )

# --------- FOOTBALL -------------------------------------------------------------    

@main.route("/football")
def start_football():
    #people = load_football()
    return render_template("football.html")

@main.route("/show_fb_logos")
def show_fb_logos():
    human_teams = []
    num_teams = int(request.args.get("num_teams", 1))
    fb_set = get_team_names(32, "fb", human_teams)
    return render_template("partials/show_logos.html", names=fb_set, sport="football")

@main.route("/fb_confirm", methods=["POST"])
def fb_confirm():
    num_teams = int(request.form.get("num_teams"))
    human_teams  = request.form.getlist("human_teams")
    num_human_teams = len(human_teams)
    pool  = request.form.get("pool")
    cap  = request.form.get("cap")
    ai_set = get_team_names(num_teams - num_human_teams, "fb", human_teams)
    return render_template("fb_confirm.html", num_teams=num_teams, human_teams=human_teams, ai_set=ai_set, pool=pool, cap=cap)

@main.route("/fb_load", methods=["POST"])
def fb_load():
    filename = request.form.get("saved_draft_file", "").strip()

    if not filename:
        abort(400, "No draft file selected.")

    try:
        draft_data = load_saved_football_draft(filename)
    except FileNotFoundError:
        abort(404, "Draft file not found.")
    except ValueError as exc:
        abort(400, str(exc))

    meta = draft_data.get("meta", {})
    log = draft_data.get("log", [])
    players = draft_data.get("players", [])

    human_teams = []
    ai_set = []

    for team in meta.get("teams", []):
        if team.get("type") == "human":
            human_teams.append(team.get("team_name"))
        else:
            ai_set.append(team.get("team_name"))

    return render_template(
        "fbdraft.html",
        num_teams=meta.get("num_teams", 0),
        human_teams=human_teams,
        ai_set=ai_set,
        pool=meta.get("pool", ""),
        cap=meta.get("cap", ""),
        draftname=meta.get("draftname", draft_data.get("draftname", "")),
        players=players,
        draft_log=log,
        draft_file=str(draft_data.get("player_path", "")),
        meta_file=str(draft_data.get("meta_path", "")),
        log_file=str(draft_data.get("log_path", ""))
    )


# ------ SOCKET IO CALLS -------

@socketio.on('make_pick')
def handle_make_pick(data):
    draftname = data['draftname']
    player_id = str(data['player_id'])
    sport     = data.get('sport', 'bb')

    # load correct meta and draft file based on sport
    if sport == 'bb':
        meta       = load_baseball_meta(draftname)
        draft_path = Path("drafts") / f"{draftname}_bb.json"
        log_path   = Path("drafts") / f"{draftname}_bb_log.json"
    elif sport == 'bk':
        meta       = load_basketball_meta(draftname)
        draft_path = Path("drafts") / f"{draftname}_bk.json"
        log_path   = Path("drafts") / f"{draftname}_bk_log.json"
    elif sport == 'fb':
        meta       = load_football_meta(draftname)
        draft_path = Path("drafts") / f"{draftname}_fb.json"
        log_path   = Path("drafts") / f"{draftname}_fb_log.json"
    else:
        emit('pick_error', {'message': f'Unknown sport: {sport}'})
        return

    # pull state from meta
    team_id  = meta['current_team_id']
    team     = get_team_by_id(meta, team_id)
    pick_num = meta['current_pick']

    # load players
    with open(draft_path, "r", encoding="utf-8") as f:
        players = json.load(f)

    # validate player
    player = next((p for p in players if str(p.get("id")) == player_id), None)
    if not player:
        emit('pick_error', {'message': 'Player not found'})
        return
    if player.get('team_id', 0) != 0:
        emit('pick_error', {'message': 'Player already drafted'})
        return

    # assign player to team
    player['team_id'] = team_id
    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(players, f, indent=2)

    # build log entry
    entry = {
        "pick":    pick_num,
        "team_id": team_id,
        "team":    team['team_name'],
        "player":  f"{player.get('FirstName')} {player.get('LastName')}",
        "pos":     player.get('short_pos', ''),
        "id":      player_id
    }
    append_to_log(log_path, entry)

    # advance pick counter
    meta['current_pick'] += 1
    meta['current_team_id'] = get_next_team_id(meta)

    # save meta back to correct sport file
    if sport == 'bb':
        save_baseball_meta(draftname, meta)
    elif sport == 'bk':
        save_basketball_meta(draftname, meta)

    # broadcast to all clients
    socketio.emit('pick_made', entry)