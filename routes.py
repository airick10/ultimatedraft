from flask import Blueprint, render_template, request, abort, current_app
from .services import load_baseball, load_basketball, load_football, load_hitters_json, load_pitchers_json, load_basketball_json, load_football_json, get_team_names, get_person, compute_short_pos, positions, sort_people, pos_player_pool
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
    #people = load_basketball()
    return render_template("basketball.html")

@main.route("/show_bk_logos")
def show_bk_logos():
    human_teams = []
    num_teams = int(request.args.get("num_teams", 1))
    bk_set = get_team_names(32, "bk", human_teams)
    return render_template("partials/show_logos.html", names=bk_set, sport="basketball")

@main.route("/bk_confirm", methods=["POST"])
def bk_confirm():
    num_teams = int(request.form.get("num_teams"))
    human_teams  = request.form.getlist("human_teams")
    pool  = request.form.get("pool")
    cap  = request.form.get("cap")
    people = load_basketball(pool, num_teams)
    num_human_teams = len(human_teams)
    ai_set = get_team_names(num_teams - num_human_teams, "bk", human_teams)
    return render_template("bk_confirm.html", num_teams=num_teams, human_teams=human_teams, ai_set=ai_set, pool=pool, cap=cap, players=people)

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