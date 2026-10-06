from flask import Blueprint, render_template, request, abort, current_app, redirect, url_for, send_file
from .ai import ai_select_bb, ai_select_bk, ai_select_fb, parse_salary, to_float
from .services import (
    load_baseball,
    load_basketball,
    load_football,
    load_hitters_json,
    load_pitchers_json,
    load_basketball_json, 
    load_football_passing_json,
    load_football_rushing_json,
    load_football_receiving_json,
    load_football_def_ol_json,
    load_football_special_json,
    initial_save_baseball_json, 
    initial_save_baseball_meta_json,
    initial_save_baseball_log_json, 
    initial_save_basketball_json, 
    initial_save_basketball_meta_json,
    initial_save_basketball_log_json,
    initial_save_football_json, 
    initial_save_football_meta_json,
    initial_save_football_log_json,
    get_saved_baseball_drafts,
    load_saved_baseball_draft,
    get_saved_basketball_drafts,
    load_saved_basketball_draft,
    get_saved_football_drafts,
    load_saved_football_draft,
    get_team_names, 
    get_person, 
    positions, 
    sort_people, 
    get_next_team_id,
    get_team_by_id,
    load_baseball_meta,
    save_baseball_meta,
    load_basketball_meta,
    save_basketball_meta,
    load_football_meta,
    save_football_meta,
    append_to_log,
    assign_picks_to_slots_bb,
    assign_picks_to_slots_bk,
    assign_picks_to_slots_fb,
    delete_saved_draft,
    TWO_WAY_BB
)
from datetime import datetime
from .exports import (
    build_bb_workbook, build_bk_workbook, build_fb_workbook,
    build_log_text, build_bb_report_context, build_bk_report_context, build_fb_report_context,
)
import random
import io
from collections import Counter
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

    meta    = draft_data.get("meta", {})
    draftname = meta.get("draftname", draft_data.get("draftname", ""))
    log     = draft_data.get("log", [])
    players = draft_data.get("players", [])

    # build team lists
    human_teams = []
    ai_set      = []
    for team in meta.get("teams", []):
        if team.get("type") == "human":
            human_teams.append(team.get("team_name"))
        else:
            ai_set.append(team.get("team_name"))

    # baseball roster slots
    roster_slots = ["C", "C", "1B", "2B", "SS", "3B", "LF", "CF", "RF",
                    "UT", "UT", "UT", "UT", "UT", "UT",
                    "S", "S", "S", "S", "S",
                    "R", "R", "R", "R", "R"]

    all_teams = [
        {"team_id": t["team_id"], "name": t["team_name"], "is_human": t["type"] == "human"}
        for t in meta["teams"]
    ]
    logo_rows = [all_teams[i:i+8] for i in range(0, len(all_teams), 8)]

    rosters = {}
    for entry in log:
        rosters.setdefault(entry['team_id'], []).append(entry)

    team_slots = {}
    roster_assignments = {}
    for t in meta["teams"]:
        picks = rosters.get(t["team_id"], [])
        n_bonus = sum(1 for e in picks if e.get('is_bonus'))
        slots = roster_slots + ["FLEX"] * n_bonus
        team_slots[t["team_id"]] = slots
        roster_assignments[t["team_id"]] = assign_picks_to_slots_bb(slots, picks)

    current_team_obj  = get_team_by_id(meta, meta.get('current_team_id', 1))
    current_team      = current_team_obj['team_name'] if current_team_obj else all_teams[0]['name']
    current_team_type = current_team_obj['type'] if current_team_obj else 'human'

    return render_template(
        "bbdraft.html",
        all_teams=all_teams,
        logo_rows=logo_rows,
        roster_slots=roster_slots,
        roster_assignments=roster_assignments,
        team_slots=team_slots,
        num_teams=meta.get("num_teams", 0),
        human_teams=human_teams,
        ai_set=ai_set,
        pool=meta.get("pool", ""),
        cap=meta.get("cap", ""),
        draftname=meta.get("draftname", draft_data.get("draftname", "")),
        players=players,
        label_by_id=roster_labels_bb(players),
        draft_log=log,
        draft_file=str(draft_data.get("player_path", "")),
        sport='bb',
        current_team=current_team,
        current_pick=meta['current_pick'],
        current_team_type=current_team_type,
    )

@main.route("/bb_confirm", methods=["POST"])
def bb_confirm():
    num_teams = int(request.form.get("num_teams"))
    human_teams = request.form.getlist("human_teams")
    pool = request.form.get("pool")
    cap = read_cap(request.form)
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

    # roster slot labels
    roster_slots = ["C", "C", "1B", "2B", "SS", "3B", "LF", "CF", "RF",
                    "UT", "UT", "UT", "UT", "UT", "UT",
                    "S", "S", "S", "S", "S",
                    "R", "R", "R", "R", "R"]

    output_path = Path("drafts") / f"{draftname}_bb.json"
    meta_path   = Path("drafts") / f"{draftname}_bb_meta.json"
    log_path    = Path("drafts") / f"{draftname}_bb_log.json"

    if not output_path.exists():
        initial_save_baseball_json(people, draftname)
    if not meta_path.exists():
        initial_save_baseball_meta_json(draftname, num_teams, human_teams, ai_set, pool, cap, output_path)
    if not log_path.exists():
        initial_save_baseball_log_json(draftname)

    with open(log_path, "r", encoding="utf-8") as f:
        draft_log = json.load(f)

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    all_teams = [
        {"team_id": t["team_id"], "name": t["team_name"], "is_human": t["type"] == "human"}
        for t in meta["teams"]
    ]
    logo_rows = [all_teams[i:i+8] for i in range(0, len(all_teams), 8)]

    rosters = {}
    for entry in draft_log:
        rosters.setdefault(entry['team_id'], []).append(entry)

    team_slots = {}
    roster_assignments = {}
    for t in meta["teams"]:
        picks = rosters.get(t["team_id"], [])
        n_bonus = sum(1 for e in picks if e.get('is_bonus'))
        slots = roster_slots + ["FLEX"] * n_bonus
        team_slots[t["team_id"]] = slots
        roster_assignments[t["team_id"]] = assign_picks_to_slots_bb(slots, picks)

    # current picking team
    current_team_obj  = get_team_by_id(meta, meta.get('current_team_id', 1))
    current_team      = current_team_obj['team_name'] if current_team_obj else all_teams[0]['name']
    current_team_type = current_team_obj['type'] if current_team_obj else 'human'

    return render_template(
        "bbdraft.html",
        all_teams=all_teams,
        logo_rows=logo_rows,
        roster_slots=roster_slots,
        roster_assignments=roster_assignments,
        team_slots=team_slots,
        pool=pool,
        cap=cap,
        label_by_id=roster_labels_bb(people),
        draftname=draftname,
        players=people,
        draft_file=output_path,
        draft_log=draft_log,
        current_team=current_team,
        current_pick=meta['current_pick'],
        current_team_type=current_team_type,
        sport="bb"
    )

@main.route("/bb_delete", methods=["POST"])
def bb_delete():
    filename = request.form.get("delete_draft_file", "").strip()
    if not filename:
        abort(400, "No draft file selected.")
    try:
        delete_saved_draft(filename, "bb")
    except FileNotFoundError:
        abort(404, "Draft file not found.")
    except ValueError as exc:
        abort(400, str(exc))
    return redirect(url_for("main.start_baseball"))

@main.route("/bb_export/<draftname>")
def bb_export(draftname):
    if Path(draftname).name != draftname:
        abort(400, "Bad draft name.")
    if not (Path("drafts") / f"{draftname}_bb.json").exists():
        abort(404, "Draft not found.")

    wb = build_bb_workbook(draftname)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"{draftname}_rosters.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@main.route("/bb_report/<draftname>")
def bb_report(draftname):
    if Path(draftname).name != draftname:
        abort(400, "Bad draft name.")
    if not (Path("drafts") / f"{draftname}_bb.json").exists():
        abort(404, "Draft not found.")

    html = render_template("report.html", **build_bb_report_context(draftname))
    if request.args.get("view") == "1":      # ?view=1 shows it in the browser instead of downloading
        return html

    buf = io.BytesIO(html.encode("utf-8"))
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"{draftname}_baseball_report.html",
        mimetype="text/html",
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

    meta    = draft_data.get("meta", {})
    draftname = meta.get("draftname", draft_data.get("draftname", ""))
    log     = draft_data.get("log", [])
    players = draft_data.get("players", [])

    # build team lists
    human_teams = []
    ai_set      = []
    for team in meta.get("teams", []):
        if team.get("type") == "human":
            human_teams.append(team.get("team_name"))
        else:
            ai_set.append(team.get("team_name"))

    # basketball roster slots
    roster_slots = ["C", "F", "F", "G", "G", "UT", "UT", "UT", "UT", "UT"]

    all_teams = [
        {"team_id": t["team_id"], "name": t["team_name"], "is_human": t["type"] == "human"}
        for t in meta["teams"]
    ]
    logo_rows = [all_teams[i:i+8] for i in range(0, len(all_teams), 8)]

    rosters = {}
    for entry in log:
        rosters.setdefault(entry['team_id'], []).append(entry)

    roster_assignments = {
        t["team_id"]: assign_picks_to_slots_bk(roster_slots, rosters.get(t["team_id"], []))
        for t in meta["teams"]
    }

    # current picking team
    current_team_obj  = get_team_by_id(meta, meta.get('current_team_id', 1))
    current_team      = current_team_obj['team_name'] if current_team_obj else all_teams[0]['name']
    current_team_type = current_team_obj['type'] if current_team_obj else 'human'


    return render_template(
        "bkdraft.html",
        all_teams=all_teams,
        logo_rows=logo_rows,
        roster_slots=roster_slots,
        roster_assignments=roster_assignments,
        num_teams=meta.get("num_teams", 0),
        human_teams=human_teams,
        ai_set=ai_set,
        pool=meta.get("pool", ""),
        cap=meta.get("cap", ""),
        draftname=meta.get("draftname", draft_data.get("draftname", "")),
        players=players,
        draft_log=log,
        draft_file=str(draft_data.get("player_path", "")),
        current_team=current_team,
        current_team_type=current_team_type,
        sport='bk'
    )

@main.route("/bk_confirm", methods=["POST"])
def bk_confirm():
    num_teams = int(request.form.get("num_teams"))
    human_teams = request.form.getlist("human_teams")
    pool = request.form.get("pool")
    cap = read_cap(request.form)
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

    # roster slot labels
    roster_slots = ["C", "F", "F", "G", "G", "UT", "UT", "UT", "UT", "UT"]

    output_path = Path("drafts") / f"{draftname}_bk.json"
    meta_path   = Path("drafts") / f"{draftname}_bk_meta.json"
    log_path    = Path("drafts") / f"{draftname}_bk_log.json"

    if not output_path.exists():
        initial_save_basketball_json(people, draftname)
    if not meta_path.exists():
        initial_save_basketball_meta_json(draftname, num_teams, human_teams, ai_set, pool, cap, output_path)
    if not log_path.exists():
        initial_save_basketball_log_json(draftname)

    with open(log_path, "r", encoding="utf-8") as f:
        draft_log = json.load(f)

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    all_teams = [
        {"team_id": t["team_id"], "name": t["team_name"], "is_human": t["type"] == "human"}
        for t in meta["teams"]
    ]
    logo_rows = [all_teams[i:i+8] for i in range(0, len(all_teams), 8)]

    rosters = {}
    for entry in draft_log:
        rosters.setdefault(entry['team_id'], []).append(entry)

    roster_assignments = {
        t["team_id"]: assign_picks_to_slots_bk(roster_slots, rosters.get(t["team_id"], []))
        for t in meta["teams"]
    }

    # current picking team
    current_team_obj  = get_team_by_id(meta, meta.get('current_team_id', 1))
    current_team      = current_team_obj['team_name'] if current_team_obj else all_teams[0]['name']
    current_team_type = current_team_obj['type'] if current_team_obj else 'human'

    return render_template(
        "bkdraft.html",
        all_teams=all_teams,
        logo_rows=logo_rows,
        roster_slots=roster_slots,
        roster_assignments=roster_assignments,
        pool=pool,
        cap=cap,
        draftname=draftname,
        players=people,
        draft_file=output_path,
        draft_log=draft_log,
        current_team=current_team,
        current_team_type=current_team_type,
        sport="bk"
    )

@main.route("/bk_delete", methods=["POST"])
def bk_delete():
    filename = request.form.get("delete_draft_file", "").strip()
    if not filename:
        abort(400, "No draft file selected.")
    try:
        delete_saved_draft(filename, "bk")
    except FileNotFoundError:
        abort(404, "Draft file not found.")
    except ValueError as exc:
        abort(400, str(exc))
    return redirect(url_for("main.start_basketball"))


@main.route("/bk_export/<draftname>")
def bk_export(draftname):
    if Path(draftname).name != draftname:
        abort(400, "Bad draft name.")
    if not (Path("drafts") / f"{draftname}_bk.json").exists():
        abort(404, "Draft not found.")

    wb = build_bk_workbook(draftname)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"{draftname}_rosters.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@main.route("/bk_report/<draftname>")
def bk_report(draftname):
    if Path(draftname).name != draftname:
        abort(400, "Bad draft name.")
    if not (Path("drafts") / f"{draftname}_bk.json").exists():
        abort(404, "Draft not found.")

    html = render_template("report.html", **build_bk_report_context(draftname))
    if request.args.get("view") == "1":
        return html

    buf = io.BytesIO(html.encode("utf-8"))
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"{draftname}_basketball_report.html",
        mimetype="text/html",
    )

# --------- FOOTBALL -------------------------------------------------------------    

@main.route("/football")
def start_football():
    saved_drafts = get_saved_football_drafts()
    return render_template("football.html", saved_drafts=saved_drafts)

@main.route("/show_fb_logos")
def show_fb_logos():
    human_teams = []
    num_teams = int(request.args.get("num_teams", 1))
    fb_set = get_team_names(32, "fb", human_teams)
    return render_template("partials/show_logos.html", names=fb_set, sport="football")

@main.route("/fb_confirm", methods=["POST"])
def fb_confirm():
    num_teams = int(request.form.get("num_teams"))
    human_teams = request.form.getlist("human_teams")
    pool = request.form.get("pool")
    cap = read_cap(request.form)
    draftname = request.form.get("draftname")
    selected_player_ids = request.form.getlist("selected_player_ids")
    ai_set = request.form.getlist("ai_set")
    confirm_stage = request.form.get("confirm_stage")

    num_human_teams = len(human_teams)

    if not ai_set:
        ai_set = get_team_names(
            num_teams - num_human_teams,
            "fb",
            human_teams
        )

    # FULL: final list immediately
    if pool == "full":
        people = load_football("full", num_teams)
        mode = "final_confirm"

    # RANDOM: final random list immediately
    elif pool == "random":
        people = load_football("random", num_teams)
        mode = "final_confirm"

    # CUSTOM, first visit: show all players with checkboxes
    elif pool == "custom" and not selected_player_ids:
        people = load_football("custom", num_teams)
        mode = "select_players"

    # CUSTOM, second visit: user selected players, now show final list
    elif pool == "custom" and selected_player_ids:
        all_players = load_football("custom", num_teams)

        selected_id_set = set(str(x) for x in selected_player_ids)

        people = [
            p for p in all_players
            if str(p.get("ID")) in selected_id_set or str(p.get("id")) in selected_id_set
        ]

        mode = "final_confirm"

    else:
        raise ValueError(f"Unknown pool type: {pool}")

    from collections import Counter
    pos_counts = Counter(p.get('short_pos','') for p in people)
    print(pos_counts)

    return render_template(
        "fb_confirm.html",
        num_teams=num_teams,
        human_teams=human_teams,
        ai_set=ai_set,
        pool=pool,
        draftname=draftname,
        cap=cap,
        players=people,
        mode=mode
    )

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

    meta    = draft_data.get("meta", {})
    draftname = meta.get("draftname", draft_data.get("draftname", ""))
    log     = draft_data.get("log", [])
    players = draft_data.get("players", [])

    # build team lists
    human_teams = []
    ai_set      = []
    for team in meta.get("teams", []):
        if team.get("type") == "human":
            human_teams.append(team.get("team_name"))
        else:
            ai_set.append(team.get("team_name"))

    # football roster slots
    roster_slots = ["QB", "QB", "HB", "HB", "FB", "TE", "TE",
                    "WR", "WR", "WR", "WR", "Def", "Special"]

    all_teams = [
        {"team_id": t["team_id"], "name": t["team_name"], "is_human": t["type"] == "human"}
        for t in meta["teams"]
    ]
    logo_rows = [all_teams[i:i+8] for i in range(0, len(all_teams), 8)]

    rosters = {}
    for entry in log:
        rosters.setdefault(entry['team_id'], []).append(entry)

    roster_assignments = {
        t["team_id"]: assign_picks_to_slots_fb(roster_slots, rosters.get(t["team_id"], []))
        for t in meta["teams"]
    }

    # current picking team
    current_team_obj  = get_team_by_id(meta, meta.get('current_team_id', 1))
    current_team      = current_team_obj['team_name'] if current_team_obj else all_teams[0]['name']
    current_team_type = current_team_obj['type'] if current_team_obj else 'human'


    return render_template(
        "fbdraft.html",
        all_teams=all_teams,
        logo_rows=logo_rows,
        roster_slots=roster_slots,
        roster_assignments=roster_assignments,
        num_teams=meta.get("num_teams", 0),
        human_teams=human_teams,
        ai_set=ai_set,
        pool=meta.get("pool", ""),
        cap=meta.get("cap", ""),
        draftname=meta.get("draftname", draft_data.get("draftname", "")),
        players=players,
        draft_log=log,
        draft_file=str(draft_data.get("player_path", "")),
        current_team=current_team,
        current_team_type=current_team_type,
        sport='fb'
    )


@main.route("/fb_draft", methods=["POST"])
def fb_draft():
    num_teams     = int(request.form.get("num_teams"))
    human_teams   = request.form.getlist("human_teams")
    ai_set        = request.form.getlist("ai_set")
    pool          = request.form.get("pool")
    cap           = request.form.get("cap")
    draftname     = request.form.get("draftname")
    selected_ids  = request.form.getlist("selected_player_ids")

    all_players = load_football("full", num_teams)

    if pool == "full":
        people = all_players
    else:
        id_set = set(str(x) for x in selected_ids)
        people = [p for p in all_players if str(p.get("id")) in id_set]

    # roster slot labels
    roster_slots = ["QB", "QB", "HB", "HB", "FB", "TE", "TE",
                    "WR", "WR", "WR", "WR", "Def", "Special"]

    output_path = Path("drafts") / f"{draftname}_fb.json"
    meta_path   = Path("drafts") / f"{draftname}_fb_meta.json"
    log_path    = Path("drafts") / f"{draftname}_fb_log.json"

    if not output_path.exists():
        initial_save_football_json(people, draftname)
    if not meta_path.exists():
        initial_save_football_meta_json(draftname, num_teams, human_teams, ai_set, pool, cap, output_path)
    if not log_path.exists():
        initial_save_football_log_json(draftname)

    with open(log_path, "r", encoding="utf-8") as f:
        draft_log = json.load(f)

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    all_teams = [
        {"team_id": t["team_id"], "name": t["team_name"], "is_human": t["type"] == "human"}
        for t in meta["teams"]
    ]
    logo_rows = [all_teams[i:i+8] for i in range(0, len(all_teams), 8)]

    rosters = {}
    for entry in draft_log:
        rosters.setdefault(entry['team_id'], []).append(entry)

    roster_assignments = {
        t["team_id"]: assign_picks_to_slots_fb(roster_slots, rosters.get(t["team_id"], []))
        for t in meta["teams"]
    }

    # current picking team
    current_team_obj  = get_team_by_id(meta, meta.get('current_team_id', 1))
    current_team      = current_team_obj['team_name'] if current_team_obj else all_teams[0]['name']
    current_team_type = current_team_obj['type'] if current_team_obj else 'human'

    return render_template(
        "fbdraft.html",
        all_teams=all_teams,
        logo_rows=logo_rows,
        roster_slots=roster_slots,
        roster_assignments=roster_assignments,
        pool=pool,
        cap=cap,
        draftname=draftname,
        players=people,
        draft_file=output_path,
        draft_log=draft_log,
        current_team=current_team,
        current_team_type=current_team_type,
        sport="fb"
    )

@main.route("/fb_delete", methods=["POST"])
def fb_delete():
    filename = request.form.get("delete_draft_file", "").strip()
    if not filename:
        abort(400, "No draft file selected.")
    try:
        delete_saved_draft(filename, "fb")
    except FileNotFoundError:
        abort(404, "Draft file not found.")
    except ValueError as exc:
        abort(400, str(exc))
    return redirect(url_for("main.start_football"))


@main.route("/fb_export/<draftname>")
def fb_export(draftname):
    if Path(draftname).name != draftname:
        abort(400, "Bad draft name.")
    if not (Path("drafts") / f"{draftname}_fb.json").exists():
        abort(404, "Draft not found.")

    wb = build_fb_workbook(draftname)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"{draftname}_rosters.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

@main.route("/fb_report/<draftname>")
def fb_report(draftname):
    if Path(draftname).name != draftname:
        abort(400, "Bad draft name.")
    if not (Path("drafts") / f"{draftname}_fb.json").exists():
        abort(404, "Draft not found.")

    html = render_template("report.html", **build_fb_report_context(draftname))
    if request.args.get("view") == "1":
        return html

    buf = io.BytesIO(html.encode("utf-8"))
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"{draftname}_football_report.html",
        mimetype="text/html",
    )

# ------ AI CALLS (Baseball) -------------

def make_ai_pick_bb(draftname):
    """
    Makes one AI-selected pick for whichever team is currently on the clock
    -- AI team or a human whose timer expired. Returns the pick_made payload,
    or None if the draft is already full / something's missing.
    """
    roster_slots = ["C", "C", "1B", "2B", "SS", "3B", "LF", "CF", "RF",
                    "UT", "UT", "UT", "UT", "UT", "UT",
                    "S", "S", "S", "S", "S",
                    "R", "R", "R", "R", "R"]

    draft_path = Path("drafts") / f"{draftname}_bb.json"
    log_path   = Path("drafts") / f"{draftname}_bb_log.json"

    meta    = load_baseball_meta(draftname)
    team_id = meta['current_team_id']
    team    = get_team_by_id(meta, team_id)

    if not team:
        return None

    total_slots = meta['num_teams'] * len(roster_slots)
    if meta['current_pick'] > total_slots:
        return None

    with open(draft_path, "r", encoding="utf-8") as f:
        players = json.load(f)
    with open(log_path, "r", encoding="utf-8") as f:
        log = json.load(f)

    team_picks         = [e for e in log if e['team_id'] == team_id]
    team_slots         = roster_slots + ["FLEX"] * sum(1 for e in team_picks if e.get('is_bonus'))
    round_num          = (meta['current_pick'] - 1) // meta['num_teams'] + 1
    cap                = meta.get('cap')
    salary_cap_enabled = parse_salary(cap) > 0

    player_id = ai_select_bb(team, team_slots, team_picks, players, round_num, cap, salary_cap_enabled)

    if player_id is None:
        undrafted = [p for p in players if p.get('team_id', 0) == 0]
        if not undrafted:
            return None
        undrafted.sort(key=lambda p: parse_salary(p.get('s_sal')))
        player_id = undrafted[0].get('id')

    player = next((p for p in players if str(p.get('id')) == str(player_id)), None)
    if not player:
        return None

    pick_num = meta['current_pick']
    player['team_id'] = team_id

    # NEW: two-way players bring their twin along
    bonus = maybe_add_twin_bb(player, players, team, pick_num, log_path)

    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(players, f, indent=2)

    # advance to the next pick
    meta['current_pick'] += 1
    meta['current_team_id'] = get_next_team_id(meta)
    next_team = get_team_by_id(meta, meta['current_team_id'])

    entry = {
        "pick":            pick_num,
        "team_id":         team_id,
        "team":            team['team_name'],
        "player":          f"{player.get('FirstName')} {player.get('LastName')}",
        "pos":             player.get('short_pos') or player.get('Pos', ''),
        "id":              str(player_id),
        "next_team":       next_team['team_name'] if next_team else '',
        "next_team_type":  next_team['type'] if next_team else '',
        "auto_picked":     team['type'] == 'human',
    }
    append_to_log(log_path, entry)
    if bonus:
        append_to_log(log_path, bonus)
    save_baseball_meta(draftname, meta)

    return {**entry, 'next_pick': meta['current_pick'], 'bonus': bonus}


def run_ai_picks_bb(draftname):
    key = (draftname, 'bb')
    if key in AI_LOOPS:
        return
    AI_LOOPS.add(key)
    try:
        while key in RUNNING_DRAFTS:
            meta = load_baseball_meta(draftname)
            team = get_team_by_id(meta, meta['current_team_id'])
            if not team or team['type'] != 'ai':
                break

            entry = make_ai_pick_bb(draftname)
            if entry is None:
                break

            socketio.emit('pick_made', entry)

            if is_draft_complete(load_baseball_meta(draftname), 'bb'):
                socketio.emit('draft_complete', {'draftname': draftname})
                break

            socketio.sleep(1.5)
    finally:
        AI_LOOPS.discard(key)

# ------ AI CALLS (Basketball) --------

def make_ai_pick_bk(draftname):
    """Basketball equivalent of make_ai_pick_bb."""
    roster_slots = ["C", "F", "F", "G", "G", "UT", "UT", "UT", "UT", "UT"]

    draft_path = Path("drafts") / f"{draftname}_bk.json"
    log_path   = Path("drafts") / f"{draftname}_bk_log.json"

    meta    = load_basketball_meta(draftname)
    team_id = meta['current_team_id']
    team    = get_team_by_id(meta, team_id)

    if not team:
        return None

    total_slots = meta['num_teams'] * len(roster_slots)
    if meta['current_pick'] > total_slots:
        return None

    with open(draft_path, "r", encoding="utf-8") as f:
        players = json.load(f)
    with open(log_path, "r", encoding="utf-8") as f:
        log = json.load(f)

    team_picks         = [e for e in log if e['team_id'] == team_id]
    round_num          = (meta['current_pick'] - 1) // meta['num_teams'] + 1
    cap                = meta.get('cap')
    salary_cap_enabled = parse_salary(cap) > 0

    try:
        player_id = ai_select_bk(team, roster_slots, team_picks, players, round_num, cap, salary_cap_enabled)
    except Exception:
        traceback.print_exc()
        player_id = None

    if player_id is None:
        print(f">>> BK AI fallback: {team['team_name']} at pick {meta['current_pick']}; "
              f"Salary sample: {players[0].get('Salary')!r}")
        undrafted = [p for p in players if p.get('team_id', 0) == 0]
        if not undrafted:
            return None
        # best scorer first, random among ties (never just alphabetical)
        undrafted.sort(key=lambda p: (-to_float(p.get('ptspgm')), random.random()))
        player_id = undrafted[0].get('id')

    player = next((p for p in players if str(p.get('id')) == str(player_id)), None)
    if not player:
        return None

    pick_num = meta['current_pick']
    player['team_id'] = team_id
    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(players, f, indent=2)

    meta['current_pick'] += 1
    meta['current_team_id'] = get_next_team_id(meta)
    next_team = get_team_by_id(meta, meta['current_team_id'])

    entry = {
        "pick":            pick_num,
        "team_id":         team_id,
        "team":            team['team_name'],
        "player":          f"{player.get('FirstName')} {player.get('LastName')}",
        "pos":             player.get('short_pos') or player.get('Pos', ''),
        "id":              str(player_id),
        "next_team":       next_team['team_name'] if next_team else '',
        "next_team_type":  next_team['type'] if next_team else '',
        "auto_picked":     team['type'] == 'human',
    }
    append_to_log(log_path, entry)
    save_basketball_meta(draftname, meta)

    return entry


def run_ai_picks_bk(draftname):
    key = (draftname, 'bk')
    if key in AI_LOOPS:
        return
    AI_LOOPS.add(key)
    try:
        while key in RUNNING_DRAFTS:
            meta = load_basketball_meta(draftname)
            team = get_team_by_id(meta, meta['current_team_id'])
            if not team or team['type'] != 'ai':
                break

            entry = make_ai_pick_bk(draftname)
            if entry is None:
                break

            socketio.emit('pick_made', entry)

            if is_draft_complete(load_basketball_meta(draftname), 'bk'):
                socketio.emit('draft_complete', {'draftname': draftname})
                break

            socketio.sleep(1.5)
    finally:
        AI_LOOPS.discard(key)

# ------ AI CALLS (FOOTBALL) --------

def make_ai_pick_fb(draftname):
    """Football equivalent of make_ai_pick_bb/bk."""
    roster_slots = ["QB", "QB", "HB", "HB", "FB", "TE", "TE",
                    "WR", "WR", "WR", "WR", "Def", "Special"]

    draft_path = Path("drafts") / f"{draftname}_fb.json"
    log_path   = Path("drafts") / f"{draftname}_fb_log.json"

    meta    = load_football_meta(draftname)
    team_id = meta['current_team_id']
    team    = get_team_by_id(meta, team_id)

    if not team:
        return None

    total_slots = meta['num_teams'] * len(roster_slots)
    if meta['current_pick'] > total_slots:
        return None

    with open(draft_path, "r", encoding="utf-8") as f:
        players = json.load(f)
    with open(log_path, "r", encoding="utf-8") as f:
        log = json.load(f)

    team_picks         = [e for e in log if e['team_id'] == team_id]
    round_num          = (meta['current_pick'] - 1) // meta['num_teams'] + 1
    cap                = meta.get('cap')
    salary_cap_enabled = parse_salary(cap) > 0

    player_id = ai_select_fb(team, roster_slots, team_picks, players, round_num, cap, salary_cap_enabled)

    if player_id is None:
        print(f">>> FB fallback (cheapest undrafted) for {team['team_name']} at pick {meta['current_pick']}")
        undrafted = [p for p in players if p.get('team_id', 0) == 0]
        if not undrafted:
            return None
        undrafted.sort(key=lambda p: parse_salary(p.get('Salary')))
        player_id = undrafted[0].get('id')

    player = next((p for p in players if str(p.get('id')) == str(player_id)), None)
    if not player:
        return None

    pick_num = meta['current_pick']
    player['team_id'] = team_id
    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(players, f, indent=2)

    meta['current_pick'] += 1
    meta['current_team_id'] = get_next_team_id(meta)
    next_team = get_team_by_id(meta, meta['current_team_id'])

    # football players use 'name' (defense/special) instead of FirstName/LastName
    player_name = player.get('name') or f"{player.get('FirstName', '')} {player.get('LastName', '')}".strip()

    entry = {
        "pick":            pick_num,
        "team_id":         team_id,
        "team":            team['team_name'],
        "player":          player_name,
        "pos":             player.get('short_pos') or player.get('Positions', ''),
        "id":              str(player_id),
        "next_team":       next_team['team_name'] if next_team else '',
        "next_team_type":  next_team['type'] if next_team else '',
        "auto_picked":     team['type'] == 'human',
    }
    append_to_log(log_path, entry)
    save_football_meta(draftname, meta)

    return entry


def run_ai_picks_fb(draftname):
    key = (draftname, 'fb')
    if key in AI_LOOPS:
        return
    AI_LOOPS.add(key)
    try:
        while key in RUNNING_DRAFTS:
            meta = load_football_meta(draftname)
            team = get_team_by_id(meta, meta['current_team_id'])
            if not team or team['type'] != 'ai':
                break

            entry = make_ai_pick_fb(draftname)
            if entry is None:
                break

            socketio.emit('pick_made', entry)

            if is_draft_complete(load_football_meta(draftname), 'fb'):
                socketio.emit('draft_complete', {'draftname': draftname})
                break

            socketio.sleep(1.5)
    finally:
        AI_LOOPS.discard(key)

ROSTER_SIZE = {'bb': 25, 'bk': 10, 'fb': 13}

RUNNING_DRAFTS = set()   # {(draftname, sport), ...}  drafts that are currently live
AI_LOOPS       = set()   # {(draftname, sport), ...}  prevents duplicate AI loops

def is_draft_complete(meta, sport):
    return meta['current_pick'] > meta['num_teams'] * ROSTER_SIZE[sport]

def roster_labels_bb(players):
    """{player id: 'Cal Ripken (R)'}: full name plus batting hand (hitters) or throwing hand (pitchers)."""
    out = {}
    for p in players:
        name = f"{p.get('FirstName') or ''} {p.get('LastName') or ''}".strip()
        raw = p.get("Bats") if p.get("kind") == "hitter" else p.get("Throws")
        hand = str(raw or "").strip()[:1].upper()
        if name:
            out[str(p.get("id"))] = f"{name} ({hand})" if hand else name
    return out


def maybe_add_twin_bb(player, players, team, pick_num, log_path):
    """If the drafted player has a two-way twin, assign the twin to the same team.
    Returns the bonus log entry (not yet written to the log), or None."""
    twin_id = TWO_WAY_BB.get(str(player.get('id')))
    if not twin_id:
        return None

    twin = next((p for p in players if str(p.get('id')) == twin_id), None)
    if not twin or twin.get('team_id', 0) != 0:
        return None            # twin isn't in this pool, or is already taken

    twin['team_id'] = team['team_id']
    return {
        "pick":     pick_num,  # same pick number as the main pick
        "team_id":  team['team_id'],
        "team":     team['team_name'],
        "player":   f"{twin.get('FirstName')} {twin.get('LastName')}",
        "pos":      twin.get('short_pos') or twin.get('Pos', ''),
        "id":       str(twin_id),
        "is_bonus": True,
    }

def read_cap(form):
    """Returns the salary cap as a clean number string, or '' for no cap."""
    raw = (form.get("cap") or "").strip()
    if raw.lower() == "yes":
        raw = (form.get("cap_amount") or "").strip()
    raw = raw.replace("$", "").replace(",", "")
    return raw if parse_salary(raw) > 0 else ""


@main.route("/log_export/<sport>/<draftname>")
def log_export(sport, draftname):
    if sport not in ("bb", "bk", "fb"):
        abort(404)
    if Path(draftname).name != draftname:
        abort(400, "Bad draft name.")
    if not (Path("drafts") / f"{draftname}_{sport}_log.json").exists():
        abort(404, "Draft log not found.")

    text = build_log_text(draftname, sport)
    buf = io.BytesIO(text.encode("utf-8-sig"))     # BOM so Notepad shows accents and dashes correctly
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"{draftname}_{sport}_draft_log.txt",
        mimetype="text/plain",
    )

# ------ SOCKET IO CALLS -------

@socketio.on('make_pick')
def handle_make_pick(data):
    print(f">>> make_pick received: {data}")
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

    # draft already over
    if is_draft_complete(meta, sport):
        emit('pick_error', {'message': 'The draft is over'})
        return

    # draft is paused / not started
    if (draftname, sport) not in RUNNING_DRAFTS:
        emit('pick_error', {'message': 'The draft is paused. Hit Start/Resume first.'})
        return

    # pull state from meta
    team_id  = meta['current_team_id']
    team     = get_team_by_id(meta, team_id)
    pick_num = meta['current_pick']

    # only humans pick through this handler
    if team['type'] != 'human':
        emit('pick_error', {'message': 'It is not your turn'})
        return

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

    # NEW: baseball two-way players bring their twin along
    bonus = None
    if sport == 'bb':
        bonus = maybe_add_twin_bb(player, players, team, pick_num, log_path)

    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(players, f, indent=2)

    # advance the pick counter
    meta['current_pick'] += 1
    meta['current_team_id'] = get_next_team_id(meta)
    next_team = get_team_by_id(meta, meta['current_team_id'])

    # football OL/DL and Special use 'name' instead of FirstName/LastName
    player_name = player.get('name') or f"{player.get('FirstName', '')} {player.get('LastName', '')}".strip()

    entry = {
        "pick":           pick_num,
        "team_id":        team_id,
        "team":           team['team_name'],
        "player":         player_name,
        "pos":            player.get('short_pos') or player.get('Pos', ''),
        "id":             player_id,
        "next_team":      next_team['team_name'],
        "next_team_type": next_team['type']
    }
    append_to_log(log_path, entry)
    if bonus:                                  # NEW
        append_to_log(log_path, bonus)

    # save meta
    if sport == 'bb':
        save_baseball_meta(draftname, meta)
    elif sport == 'bk':
        save_basketball_meta(draftname, meta)
    elif sport == 'fb':
        save_football_meta(draftname, meta)

    # NEW: the live event also carries the real next pick number and the bonus entry
    payload = {**entry, 'next_pick': meta['current_pick'], 'bonus': bonus}
    socketio.emit('pick_made', payload)

    # that was the last pick: announce it and don't start any more AI picks
    if is_draft_complete(meta, sport):
        socketio.emit('draft_complete', {'draftname': draftname})
        return

    if next_team['type'] == 'ai':
        if sport == 'bb':
            socketio.start_background_task(run_ai_picks_bb, draftname)
        elif sport == 'bk':
            socketio.start_background_task(run_ai_picks_bk, draftname)
        elif sport == 'fb':
            socketio.start_background_task(run_ai_picks_fb, draftname)

@socketio.on('skip_pick')
def handle_skip_pick(data):
    draftname = data['draftname']
    sport     = data.get('sport', 'bb')

    # NEW: ignore timeouts when the draft is paused
    if (draftname, sport) not in RUNNING_DRAFTS:
        return

    if sport == 'bb':
        entry = make_ai_pick_bb(draftname)
        if entry is None:
            return

        socketio.emit('pick_made', entry)

        meta = load_baseball_meta(draftname)
        if is_draft_complete(meta, 'bb'):
            socketio.emit('draft_complete', {'draftname': draftname})
            return

        next_team = get_team_by_id(meta, meta['current_team_id'])
        if next_team and next_team['type'] == 'ai':
            socketio.start_background_task(run_ai_picks_bb, draftname)
        return

    elif sport == 'bk':
        entry = make_ai_pick_bk(draftname)
        if entry is None:
            return

        socketio.emit('pick_made', entry)

        meta = load_basketball_meta(draftname)
        if is_draft_complete(meta, 'bk'):
            socketio.emit('draft_complete', {'draftname': draftname})
            return

        next_team = get_team_by_id(meta, meta['current_team_id'])
        if next_team and next_team['type'] == 'ai':
            socketio.start_background_task(run_ai_picks_bk, draftname)
        return

    elif sport == 'fb':
        entry = make_ai_pick_fb(draftname)
        if entry is None:
            return

        socketio.emit('pick_made', entry)

        meta = load_football_meta(draftname)
        if is_draft_complete(meta, 'fb'):
            socketio.emit('draft_complete', {'draftname': draftname})
            return

        next_team = get_team_by_id(meta, meta['current_team_id'])
        if next_team and next_team['type'] == 'ai':
            socketio.start_background_task(run_ai_picks_fb, draftname)
        return

    else:
        return



@socketio.on('request_sync')
def handle_request_sync(data):
    draftname = data['draftname']
    sport     = data.get('sport', 'bb')

    if sport == 'bb':
        meta     = load_baseball_meta(draftname)
        log_path = Path("drafts") / f"{draftname}_bb_log.json"
    elif sport == 'bk':
        meta     = load_basketball_meta(draftname)
        log_path = Path("drafts") / f"{draftname}_bk_log.json"
    elif sport == 'fb':
        meta     = load_football_meta(draftname)
        log_path = Path("drafts") / f"{draftname}_fb_log.json"
    else:
        return

    with open(log_path, "r", encoding="utf-8") as f:
        log = json.load(f)

    current_team = get_team_by_id(meta, meta['current_team_id'])

    emit('full_sync', {
        'log': log,
        'current_team': current_team['team_name'] if current_team else '',
        'current_team_type': current_team['type'] if current_team else 'human',
        'running': (draftname, sport) in RUNNING_DRAFTS,
        'complete': is_draft_complete(meta, sport),
        'current_pick': meta['current_pick'],
    })

META_LOADERS = {'bb': load_baseball_meta, 'bk': load_basketball_meta, 'fb': load_football_meta}
AI_RUNNERS   = {'bb': run_ai_picks_bb,    'bk': run_ai_picks_bk,      'fb': run_ai_picks_fb}


@socketio.on('start_draft')
def handle_start_draft(data):
    draftname = data['draftname']
    sport     = data.get('sport', 'bb')
    if sport not in META_LOADERS:
        return

    meta = META_LOADERS[sport](draftname)
    if is_draft_complete(meta, sport):
        socketio.emit('draft_complete', {'draftname': draftname})
        return

    RUNNING_DRAFTS.add((draftname, sport))
    socketio.emit('draft_state', {'draftname': draftname, 'running': True})

    # if an AI team is on the clock, get it picking
    team = get_team_by_id(meta, meta['current_team_id'])
    if team and team['type'] == 'ai':
        socketio.start_background_task(AI_RUNNERS[sport], draftname)


@socketio.on('pause_draft')
def handle_pause_draft(data):
    draftname = data['draftname']
    sport     = data.get('sport', 'bb')
    RUNNING_DRAFTS.discard((draftname, sport))
    socketio.emit('draft_state', {'draftname': draftname, 'running': False})