from flask import Blueprint, render_template, request, abort, current_app
from .services import (
    load_baseball,
    load_basketball,
    load_football,
    load_hitters_json,
    load_pitchers_json,
    load_basketball_json, 
    load_football_json, 
    initial_save_basketball_json, 
    initial_save_basketball_meta_json,
    initial_save_basketball_log_json,
    get_saved_basketball_drafts,
    load_saved_basketball_draft,
    get_team_names, 
    get_person, 
    compute_short_pos, 
    positions, 
    sort_people, 
    pos_player_pool
)
from datetime import datetime
import random



main = Blueprint("main", __name__)

@main.route("/")
def index():
    #return "<h1>Using Blueprint</h1>"
    return render_template("index.html")

@main.route("/baseball")
def start_baseball():
    #people = load_baseball()
    return render_template("baseball.html")

@main.route("/show_bb_logos")
def show_bb_logos():
    human_teams = []
    num_teams = int(request.args.get("num_teams", 1))
    bb_set = get_team_names(32, "bb", human_teams)
    return render_template("partials/show_logos.html", names=bb_set, sport="baseball")

@main.route("/bb_confirm", methods=["POST"])
def bb_confirm():
    num_teams = int(request.form.get("num_teams"))
    human_teams  = request.form.getlist("human_teams")
    num_human_teams = len(human_teams)
    pool  = request.form.get("pool")
    cap  = request.form.get("cap")
    ai_set = get_team_names(num_teams - num_human_teams, "bb", human_teams)
    return render_template("bb_confirm.html", num_teams=num_teams, human_teams=human_teams, ai_set=ai_set, pool=pool, cap=cap)

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
        log_file=str(draft_data.get("log_path", "")),
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

    return render_template(
        "bkdraft.html",
        all_teams=all_teams,
        logo_rows=logo_rows,
        roster_slots=roster_slots,
        pool=pool,
        cap=cap,
        draftname=draftname,
        players=people,
        draft_file=output_path
    )

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