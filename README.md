# Ultimate Draft

Flask Application

A live, multiplayer-style draft app for **baseball**, **basketball**, and **football**. You (and friends)
draft against AI teams from all-time player pools, in snake order, with position-based roster slots,
an optional salary cap, an optional "Berserker" mode, and a pick clock.

---

## Quick start

To Run, go to the Flask Directory

**Create Python Environment**
```
python3 -m venv .venv
```

**Run the App**
```
flask run
```

**Deactivate the Python Environment**
```
deactivate
```

### The same steps with the parts the short version leaves out

```
1. go to the Flask directory (the folder that holds wsgi.py and .flaskenv)
cd path/to/ultimatedraft

2. create the environment (one time only)
python3 -m venv .venv

3. activate it (every new terminal)
source .venv/bin/activate          # Mac / Linux
.venv\Scripts\activate             # Windows

4. install the libraries (one time, and again whenever requirements.txt changes)
pip install -r requirements.txt

5. run
flask run                          # or:  python wsgi.py

6. open  http://localhost:5050

7. when you're done
deactivate
```

- `.flaskenv` tells Flask what to run: `FLASK_APP=wsgi.py`, `FLASK_DEBUG=1`, and `FLASK_RUN_PORT=5050`.
- `python wsgi.py` starts the app through `socketio.run(...)`, which is the method the Flask-SocketIO
  docs recommend for WebSockets. `flask run` is fine for development.
- **Always start the app from the same folder.** Saved drafts go in a `drafts/` folder that is created
  *relative to wherever you ran the command*. Start it from somewhere else and you'll see an empty
  Saved Drafts list. Your old drafts are not gone; they're just in the other folder.
- Static files (CSS and JS) get cached by the browser. After editing one, hard refresh with Ctrl+Shift+R.

---

## What's in the project

```
Root folder
  wsgi.py               starts the app (what .flaskenv points at)
  __init__.py           create_app() and the shared socketio object
  routes.py             every web page and every Socket.IO event
  services.py           loading the JSON data, saving/loading drafts, team names, slot logic
  ai.py                 the AI drafters (baseball, basketball, football), UT variety, L/R balance
  cap.py                salary-cap math ("can this team still finish its roster under the cap?")
  tiers.py              tier 1 / tier 2 player targeting for the AI
  berserker.py          Berserker mode (random AI picks)
  exports.py            Excel export, .txt draft log, HTML report, team rankings
  check_cap.py          command-line check: is any team over the cap?
  check_tiers.py        command-line check: where did the tiered players go?
  requirements.txt      Python libraries
  .flaskenv             Flask settings (app file, debug, port)
  socketdocumentation.txt   notes on how Socket.IO was wired in

  static/               (CSS, JavaScript, pictures, fonts)
    draft_common.js     the draft board code all three sports share
    draft_bb.js / draft_bk.js / draft_fb.js   the parts that are different per sport
    poolsearch.js       the "search by name" box above the player pool
    setup.js / confirm.js   the setup page and the confirm / custom pool page
    bbstyle.css / bkstyle.css / fbstyle.css   the three draft-board stylesheets
    confirm.css / setup.css / themes.css      setup + confirm pages (colors and fonts live here)
    responsive.css      the phone and tablet layout (loads last, overrides the rest)
    styles.css          old: only a body color and MLB team colors
    fonts/              the three downloaded fonts (Sancreek, Iceberg, Jersey 25)
    *.jpg               page backgrounds and the landing-page pictures

  templates/
    base.html           the shell every page extends (fonts, Bootstrap, Socket.IO, htmx)
    index.html          landing page (pick a sport)
    baseball.html / basketball.html / football.html     setup pages
    bb_confirm.html / bk_confirm.html / fb_confirm.html     name-your-draft + custom pool pages
    bbdraft.html / bkdraft.html / fbdraft.html          the live draft boards
    report.html         the HTML draft report (all three sports)
    partials/
      setup_ui.html     shared setup form
      confirm_ui.html   shared confirm / custom pool form
      show_logos.html   the team-picker grid (loaded in by htmx)

  drafts/               created automatically while you run; one set of 3 files per saved draft
```

> Files left over from earlier versions (safe to delete once you've checked nothing links to them):
> `templates/basketball_test.html`, `templates/partials/show_logos_BAK.html`.

---

## The three sports

Each sport has a two-letter code that appears in file names, routes, and the code:

| Sport | Code | Roster |
|---|---|---|
| Baseball | `bb` | 25 slots: C, C, 1B, 2B, SS, 3B, LF, CF, RF, 6 UT, 5 S (starters), 5 R (relievers) |
| Basketball | `bk` | 12 slots: C, F, F, G, G, 6 UT, 1 Def (a defense unit) |
| Football | `fb` | 13 slots: QB x2, HB x2, FB, TE x2, WR x4, Def, Special |

Two-way players (Ohtani, Babe Ruth, Bullet Rogan; Kordell Stewart, Billy Cannon, Deebo Samuel)
bring their other record along when drafted, and that team gets one extra **FLEX** slot.

---

## How a draft flows

1. **Setup page** (`/baseball`, `/basketball`, `/football`): number of teams, which teams are yours,
   player pool (Complete / Random / Custom), salary cap, Berserker mode.
2. **Confirm page** (`/bb_confirm` and friends): for Custom pools you pick the players; otherwise you
   name the draft. Choices travel from page to page as hidden form fields.
3. **Draft page** (`/bb_draft` and friends): creates the three save files the first time, then shows the board.
4. **Live draft**: the page talks to the server over Socket.IO. Nothing starts until you press **Start Draft**.
5. **Reports**: Excel, `.txt` log, and an HTML report are linked at the top of the draft board.

### The files in `drafts/` (three per draft, named `<draftname>_<sport>...`)

| File | What's in it |
|---|---|
| `<name>_bb.json` | Every player in the pool. A player's `team_id` is `0` until drafted, then the team's id. |
| `<name>_bb_meta.json` | Settings and state: teams, pool, cap, berserker, `current_pick`, `current_team_id`. |
| `<name>_bb_log.json` | The pick-by-pick log. Two-way twins appear as extra entries with `"is_bonus": true`. |

(`bk` and `fb` work the same way.) Deleting a draft from the setup page removes all three.

---

## Data files (the player pools)

The app downloads these every time it needs them (there is no cache). You edit them at the source.
Each is a JSON list of records, and each record needs an `ID` (or `_id` / `id`) that is **unique within its file**.
If two records share an ID, only one of them loads.

| Data | File |
|---|---|
| Baseball hitters | [alltimebatters.json](https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltimebatters.json) |
| Baseball pitchers | [alltimepitchers.json](https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltimepitchers.json) |
| Basketball players | [alltimebasketball.json](https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltimebasketball.json) |
| Basketball defense units | [alltimebasketball_defense.json](https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltimebasketball_defense.json) |
| Football passers | [alltime_football_passing.json](https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltime_football_passing.json) |
| Football receivers | [alltime_football_receiving.json](https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltime_football_receiving.json) |
| Football rushers | [alltime_football_rushing.json](https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltime_football_rushing.json) |
| Football defense / offensive line units | [alltime_football_def_ol.json](https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltime_football_def_ol.json) |
| Football special teams units | [alltime_football_special.json](https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/alltime_football_special.json) |

**Where the links live in the code:** the `input_file_*` constants at the top of `services.py`.
Change a link there and the whole app uses the new one.

**Using a local file instead of a link:** put the `.json` file in the same folder as `services.py`
and set the constant to just the file name, for example `input_file_baseball_hitters = "alltimebatters.json"`.
(It must be a bare file name, not a path with folders.)

### Keys the app reads

| Sport | Keys worth knowing |
|---|---|
| Baseball | `ID`, `FirstName`, `LastName`, `Team`, `Bats` / `Throws` (shown as L/R/S), `b_*` batting stats, `p_*` pitching stats, `s_*` Strat-O-Matic ratings (`s_sal` salary, `s_bal` L/R balance, `s_fielding`, `s_endurance`, `s_obtbvl`, `s_obtbvr`), `BaseballReferenceURL` |
| Basketball | `Salary`, `Pos` (C, F, G), `Team_Logo` (**not** `Team`), `ptspgm` / `rbspgm` / `astpgm` / `fg_pct`, ratings like `Omade`, `Imade`, `PassDazz`, `Dsteal`, `BasketballReferenceURL`. Defense units are a separate file. |
| Football | `Salary`, `Positions`, `TM` (player logo) or `Team_Logo` (unit logo), `Year` + `Team` (units), `s_*` ratings, `FootballReferenceURL` |
| Any sport | `tier`: `1` = elite, `2` = very good. The AI goes after tiered players first (see AI section). |

Gotchas:
- The basketball salary key is **`Salary`**. It used to be "Proposed Salary", so don't code against that.
- Watch out for Excel turning values into dates (like `Feb-00`). Fix those in the source file.
- Baseball positions are worked out from `s_fielding` (hitters) and `s_endurance` (pitchers).

---

## Changing how it looks

### Fonts: where to make changes

| What | Where |
|---|---|
| Setup, confirm, and landing pages: body text | `static/confirm.css`, the `--font` variable in the `:root` block. Per-sport override in `static/themes.css`. |
| Setup, confirm, and landing pages: titles and headings | `--font-display` in the same two places |
| Draft-board player table (the big one) | `static/bbstyle.css`, `bkstyle.css`, `fbstyle.css`: the `font-family` inside `.player-table { ... }`. These use the three downloaded fonts. |
| Everything else on the draft boards (nav, logos, rosters, buttons) | Bootstrap's default font. Add a `font-family` to `body` in the board stylesheet to change it. |
| The HTML report | `static` is not used. It's the `body{ font: ... }` line inside the `<style>` block of `templates/report.html`. |

Per-sport fonts at the moment:

| | Display (titles) | Body | Draft-board table |
|---|---|---|---|
| Baseball | Alfa Slab One | Barlow | Sancreek (downloaded) |
| Basketball | Bebas Neue | Barlow | Iceberg (downloaded) |
| Football | Teko | Barlow | Jersey 25 (downloaded) |

### How to just link a Google Font

1. Go to <https://fonts.google.com> and pick a font. Click **Get font**, then **Get embed code**, and choose **`<link>`**.
2. Easiest: add it to the long `fonts.googleapis.com/css2?...` link in `templates/base.html`.
   Add `&family=Your+Font:wght@400;700` before `&display=swap` (spaces become `+`).
   The family name must match the Google name exactly.
3. Use it in CSS: `font-family: 'Your Font', sans-serif;` (keep a fallback after the comma).
   Pages that use the theme variables want it in `themes.css`, e.g. `--font-display: 'Your Font', serif;`.
4. Hard refresh (Ctrl+Shift+R).

**Using a downloaded font file instead:** drop the `.ttf` in `static/fonts/`, then add an `@font-face`
block to the stylesheet (copy the one at the top of `bbstyle.css`) and use the name you gave it.
The `src: url('fonts/...')` path is relative to the CSS file, which is why it works from `static/`.

### Colors: where to change them

| What | Where |
|---|---|
| Setup / confirm / landing pages | `static/confirm.css`, the **THEME block** at the top (`--accent`, `--ink`, `--card`, `--mine`, and so on). Each variable has a comment. |
| Per-sport accent colors and fonts | `static/themes.css` (`.theme-baseball`, `.theme-basketball`, `.theme-football`). Remove a line there and it falls back to the default in `confirm.css`. |
| Draft boards | `bbstyle.css`, `bkstyle.css`, `fbstyle.css`. The colors are **typed in directly** (no variables yet), so use find-and-replace. The common ones: gold `#c9a84c` (accent), green `#39ff14` (human on the clock, Draft button), red `#ff4444` (AI on the clock, low timer), blue `#2196f3` (your teams), backgrounds `#111`, `#0d0d0d`, `#1a1a1a`. |
| Page background pictures | `static/*.jpg`. Set in the `<style>` of each template (`base_back.jpg`, `bk_back.jpg`, `foot_back.jpg`, and `base_dirt.jpg` / `hardwood.jpg` / `football_field.jpg` for the boards). The boards also lay a 30%-opacity copy over everything. Change `opacity:0.3` in the inline `<div>` near the top of each board template. |
| HTML report | `:root{--navy:...;--gold:...}` at the top of the `<style>` in `templates/report.html` |
| Phone / tablet tweaks | `static/responsive.css` (loads last, so it wins over the others) |
| Old MLB team colors | `static/styles.css` (probably unused) |

### Team names and logos

**The fictional team names** (Aces, Badgers, Neptunes, and so on) are three lists in
`services.py`, in the function `get_team_names()`: one for baseball (`bb_names`), one for basketball
(`bk_names`), and one for football (`fb_names`). There are 32 of each, which is also the biggest draft size.

**The logo for each team** is looked up by name, from this pattern:

```
https://filedn.com/limKzbrdG9qBWDCDLoyNoHF/files/Logos/fictional/<sport folder>/<TeamName>_<code>.png

baseball   Logos/fictional/baseball/Neptunes_bb.png
basketball Logos/fictional/basketball/Wolfpack_bk.png
football   Logos/fictional/football/Orcas_fb.png
```

**To rename a team:** change the name in its list in `services.py`, **and** rename the picture to match
(`NewName_bb.png`). The name is used exactly as written, so they have to match letter for letter.
Heads up: the football list currently spells *Gladitors* and the basketball list spells *Muskateers*.
If you fix a spelling, rename the image too.

**To add a team:** add the name to the list and upload `<Name>_<code>.png` to the right folder.
The setup page picks it up on its own.

**To use a different place for logos:** the pattern is built in four places, so change all of them:
`templates/partials/show_logos.html`, `templates/partials/confirm_ui.html`, `static/draft_common.js`
(`buildLogoEl`), and `exports.py` (`LOGO_ROOT` and the three report builders).

**Logos for the real teams on each player row:**

| Sport | Folder | Which field in the JSON |
|---|---|---|
| Baseball | `Logos/baseballdraft/` | `Team` |
| Basketball | `Logos/basketball/` | `Team_Logo` |
| Football (players) | `Logos/football/` | `TM` |
| Football (lines, special teams) | `Logos/football/` | `Team_Logo` |
| Report pages | `Logos/seal/` (baseball), `Logos/basketball/`, `Logos/football/` | same fields |

---

## Changing how it plays

### Rosters (careful: the slot lists live in more than one place)

`routes.py` keeps the master lists (`BB_ROSTER_SLOTS`, `BK_ROSTER_SLOTS`, `FB_ROSTER_SLOTS`) and sizes
(`ROSTER_SIZE`). **The baseball and football slot lists are also typed out again** inside `bb_load`,
`bb_draft`, `make_ai_pick_bb`, `fb_load`, `fb_draft`, and `make_ai_pick_fb`. If you change a roster, search
`routes.py` for `"UT", "UT"` (or `"WR", "WR"`) and update every copy. Also check:

- `services.py`: the Random pool sizes in `load_baseball`, `load_basketball`, `load_football` (the `num_teams * N` lines).
- `templates/bb_confirm.html` and friends: the `mult` numbers in each group (how many to pick for a Custom pool).
- `ai.py`: `SHORT_POS_TO_SLOT_*` (in `services.py`) and the `CAP_RULES` table.

### Timers

- Pick clock: **120 s** for a human, **15 s** for AI. Search `startTimer(` in `static/draft_common.js`.
- Delay between AI picks: `socketio.sleep(1.5)` in each `run_ai_picks_*` function in `routes.py`.
- Logos shown in the strip: `STRIP_SIZE` at the top of `draft_common.js`.

### Salary cap

- `cap.py` has the math. A team can only draft a player if it can still fill every other open slot
  with the cheapest available players and stay under the cap.
- `CAP_SAFETY` in `ai.py` (1.10) is the extra cushion the AI keeps. Humans get a warning instead of a block.
- `CAP_EASE` in `routes.py` (1.35) sets the suggested cap on the setup page (average salary x roster size x this).

### The AI

- `AI_FOCUS_TABLE`, `AI_FOCUS_TABLE_BK`, and `AI_FOCUS_TABLE_FB` in `ai.py` hold the 16 "archetypes".
  Each AI team is given one at random when the draft is created.
- **Tiers** (`tiers.py`): put `"tier": 1` or `2` on a player in the JSON. `TIER1_PASS_CHANCE` and
  `TIER2_PASS_CHANCE` control how often a team skips them.
- **Berserker** (`berserker.py`): `BERSERKER_RANDOM_CHANCE` (0.70). Stored per AI team in the meta file as
  `"Berserker": true`, so you can also hand-edit a single team.
- **Baseball L/R balance**: `BAL_TOLERANCE`, `BAL_STRICTNESS`, and `LEAN_STICK` in `ai.py`.
  A team's lean can be forced by adding `"Lean": "L"`, `"R"`, or `"B"` to the team in its meta file.
- **Two-way players**: `TWO_WAY_NAMES_BB` and `TWO_WAY_NAMES_FB` in `services.py`, matched by **name**
  (not ID, since IDs shift when you edit the JSON). Check with `/twin_check/bb` or `/twin_check/fb`.

---

## Pages and routes

| Page | URL |
|---|---|
| Landing | `/` |
| Setup | `/baseball`, `/basketball`, `/football` |
| Confirm | `/bb_confirm`, `/bk_confirm`, `/fb_confirm` (POST) |
| Draft board | `/bb_draft`, `/bk_draft`, `/fb_draft` (POST) |
| Open / delete saved draft | `/bb_load`, `/bk_load`, `/fb_load`, `/bb_delete`, ... (POST) |
| Excel | `/bb_export/<draftname>` (and `bk`, `fb`) |
| HTML report | `/bb_report/<draftname>` (add `?view=1` to view instead of download) |
| Draft log (.txt) | `/log_export/<bb|bk|fb>/<draftname>` |
| Data check | `/twin_check/bb`, `/twin_check/fb` |

### Socket.IO events (the live part)

| Browser sends | What it does |
|---|---|
| `make_pick` | A human drafts a player (`{draftname, player_id, sport, confirmed?}`) |
| `skip_pick` | The clock hit zero; the AI picks for that team |
| `request_sync` | "Send me the full state" (on connect) |
| `start_draft` / `pause_draft` | The Start / Stop button |

| Server sends | What it means |
|---|---|
| `pick_made` | A pick happened (carries the next team, pick number, and any two-way twin) |
| `pick_error` | Something was refused (shown in an alert) |
| `cap_warning` | A human pick might break the cap (browser asks "draft anyway?") |
| `full_sync` | The whole log and state, in reply to `request_sync` |
| `draft_state` | Running or paused |
| `draft_complete` | The last pick is in |

---

## Diagnostics

```
python check_cap.py   <draftname> <bb|bk|fb>     # payroll per team, flags anyone over the cap
python check_tiers.py <draftname> <bb|bk|fb>     # where each tier 1 / tier 2 player went
```

Run them from the folder that contains `drafts/`.

---

## Good to know before you change things

- **Drafts pause on restart.** Which drafts are "running" lives in memory (`RUNNING_DRAFTS` in `routes.py`),
  so restarting the app, or the debug reloader kicking in after you save a file, pauses every draft.
  Press **Resume Draft**. Nothing is lost; picks are saved to disk as they happen.
- **The pick clock runs in each browser.** Two tabs open on the same draft each run their own timer.
- **Data is downloaded every time.** Setup pages are only as fast as the file host.
- **There is no file locking.** Picks are read-modify-write on JSON files. Fine for a few people, not for many at once.
- **Opening a draft by name that already exists** reuses its saved files, so changing the pool settings on
  the setup page won't change a draft that's already been created. Delete it first.

### Ideas and loose ends (some may already be done; check before relying on them)

- Server-side pick deadline, so the browser's clock can't skip a pick early or twice.
- A short-lived cache around the JSON downloads.
- Football lines and special teams in the report's Team Rankings.
- Convert the three draft-board stylesheets to the same color variables that `confirm.css` uses.
- A Pool / Roster / Log tab bar for phones (the layout is stacked for now).
- Clean up `requirements.txt` (`pygame`, `wget`, `tabulate`, and `virtualenv` look like leftovers), and
  consider moving off `eventlet`, which is in maintenance mode.
