# PIZZAVISION

![PIZZAVISION](pizzavision/static/pv25.png)

**A real-time Eurovision watch-party app.** Guests scan in on their phones, get an AI-generated stage persona (band name, backstory and portrait), rank the songs live by dragging them, and then the room watches a shared big screen reveal the leaderboard and 32 tongue-in-cheek awards.

Built as an annual project for a real party. Everything here runs in production on Cloud Run for one night a year, which shaped most of the interesting engineering decisions: it has to survive scale-to-zero, cold starts, flaky phone connections, and a dozen guests all hitting the AI pipeline at once.

---

## Contents

1. [What it does](#what-it-does)
2. [Architecture](#architecture)
3. [The AI pipeline](#the-ai-pipeline)
4. [Scoring and awards](#scoring-and-awards)
5. [Screens and API](#screens-and-api)
6. [Live sync](#live-sync)
7. [Run it locally](#run-it-locally)
8. [Configuration](#configuration)
9. [Deploying to Cloud Run](#deploying-to-cloud-run)
10. [Project layout](#project-layout)
11. [Running it for a new contest year](#running-it-for-a-new-contest-year)
12. [Notes](#notes)

---

## What it does

**Guests get onboarded as a Eurovision act.** Instead of typing a nickname, each guest answers five quick prompts (their first name, a song title, the song's vibe, their own vibe, and an optional extra). Each field has a "surprise me" button backed by an LLM if inspiration runs dry. The app then generates three candidate band names, and while the guest is still reading them, it is already drawing two portrait photos of their act in the background. They pick a name, pick a portrait, and they are in.

**Voting is a drag-and-drop ballot.** Guests reorder the full running list on their phone. Every reorder is pushed over WebSockets and persisted immediately, so a dropped connection or an accidental refresh never loses a ballot. The contest moves through three states (`pre`, `open`, `closed`) that the host controls, and every connected phone reacts instantly.

**The big screen is the payoff.** A results page reveals countries one at a time with per-voter point breakdowns, confetti and a party horn. An awards presentation runs through 32 awards, each with a winner, a generated insight line and artwork. There is also a "guess the performer" party game that puts each guest's AI portrait on screen and drips out clues (song, vibe, stage name, real name) while the room shouts guesses.

**The host has a real control panel.** Reorder or drop entries after the semi-finals, open and close voting, clear one guest's ballot or delete them entirely, and watch a live users table with online indicators, ballot progress and timestamps that updates without a refresh. The panel is password gated on both sides: a session login to view it, since it lists every guest by name, and a re-checked password on each mutating request, so a stolen cookie on its own changes nothing.

---

## Architecture

Flask plus Flask-SocketIO, served by eventlet, running as a single Cloud Run instance with session affinity. The interesting part is the storage layer.

```
                    Browser (phone)                Big screen
                          |                             |
                    WebSocket + HTTP              HTTP (presentation)
                          |                             |
              +-----------+-----------------------------+
              |          Flask + Flask-SocketIO         |
              |         (eventlet, single instance)     |
              +--+-------------+--------------+---------+
                 |             |              |
           vote_store    image_store     config_store      <- adapter layer
                 |             |              |
        Firestore | TinyDB   GCS | disk   Firestore | JSON file
                 |
        +--------+--------------------------------+
        |   OpenAI (names, prompts, roasts)       |
        |   Gemini (portraits)                    |
        |   Anthropic (optional roast provider)   |
        +-----------------------------------------+
```

**Three storage adapters, one pattern.** Cloud Run's container filesystem is ephemeral, so anything mutable had to move off disk. Rather than bolt on a database, every category of mutable state got the same shape: a pair of backend classes behind one API, chosen by a factory that keys on `GOOGLE_CLOUD_PROJECT`.

| Store | Local dev | Cloud Run | Holds |
| --- | --- | --- | --- |
| `vote_store.py` | TinyDB (`db.json`) | Firestore (`pizzavision_votes`) | Ballots, guest profiles, image state, vote history |
| `image_store.py` | `static/generated/` | GCS (`gs://$PV_GCS_BUCKET/generated/`) | Candidate and chosen portraits |
| `config_store.py` | `options.json` | Firestore (`pizzavision_config/singleton`) | Voting state, running order |

The result is that local development needs no cloud account at all, and production keeps everything through a scale-to-zero cold start. The config store is slightly cleverer than the other two: the JSON file stays the static seed for entry metadata, and Firestore only overlays the fields the admin actually mutates at runtime. It also compares the entry label sets on read, so deploying next year's lineup does not silently serve last year's order out of Firestore.

**Guests are identified by a client UUID, not a name.** Band names are mutable and non-unique, so every row is keyed on a UUID persisted in the browser. That makes rename, rejoin, multi-tab, and targeted admin actions ("clear this one person's ballot") all work correctly.

---

## The AI pipeline

Three providers, each doing the thing it is best at.

| Stage | Model | Why |
| --- | --- | --- |
| Band names, field suggestions, image prompts | `gpt-4o-mini` | Fast and cheap, called several times per guest |
| Roasts (act and ballot) | `gpt-4o` | The mini variant defangs the jokes |
| Portraits | `gemini-3-pro-image-preview` (Nano Banana Pro) | Coherent staging and readable text on stage props |
| Roasts (optional swap) | `claude-opus-4-7` | Set `ROAST_PROVIDER=anthropic` to A/B the writing |

A few things worth calling out:

**Prefetch hides the latency.** Image generation starts when the guest reaches the name-picking step, not after they pick. The prompt LLM falls back to "the act" framing because the band name is not chosen yet, which costs nothing visually. By the time the guest has read three name options, the portraits are usually done.

**The generation fans out properly.** One LLM call writes both image prompts, then each portrait generates in its own background task. The catch was that the Gemini SDK's HTTP transport does not yield to the eventlet hub, so "parallel" generations serialized and all landed at once. Running the call through `eventlet.tpool` in a real OS thread keeps the hub free and the images stream in one by one.

**Nothing in the pipeline can block onboarding.** Missing API key, exhausted quota, broken bucket: every failure path lands a fallback image in the slot, records the real error on the guest's row for debugging, and lets them carry on. Reroll doubles as the retry path, and guests can pin one portrait they like while rerolling only the other.

**The picker polls instead of trusting sockets.** Socket emits from nested background tasks proved unreliable under this eventlet plus python-socketio plus Flask-SocketIO combination, so `/api/image-state` is the source of truth and the emits are best-effort instant feedback on top.

There is also `roast_harness.py`, a small dev tool that runs the roast prompts against a curated set of test inputs with multiple samples per case, so prompt changes can be read in bulk and compared across providers.

---

## Scoring and awards

Ballots are scored with the real Eurovision distribution: `12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1` to each voter's top eleven.

Every entry in `options.json` carries metadata beyond the song title: genre, lead singer gender, language, region, act type, selection route, returning artist, former Soviet state, Big 5 membership, a drink pairing, GDP and population. The awards engine weights that metadata by the points each voter assigned, then finds winners (with proper tie handling) across 32 awards, including:

- **Taste and similarity:** Tastemaker, Contrarian, Twinzies, Lone Wolf, Squad Goals, Voice of the People
- **Genre and act:** Pop Diva, Rockstar, Folk Hero, Mr. Roboto, Crooner, For the Girls, Polyglot, Welcome Back
- **Geography and economics:** Big 5, Nordic Friend Zone, Balkan Brotherhood, Baltic Squad, Mediterranean Mood, Moneybags, Slummin' It, Extrovert, Introvert
- **Voting behaviour:** Juggler, Commitment Issues, Flip Flop, Markie Likey

That last group is derived from a per-voter history the vote store keeps: every time a voter's number one pick changes, the store appends a timestamped entry. That gives the awards engine how many times someone changed their mind, how long each song sat at the top, and which song they kept coming back to. Each award also generates an insight line explaining why that person won.

---

## Screens and API

The app mounts under `/pizzavision`, and `/` redirects there.

| Path | Purpose |
| --- | --- |
| `/pizzavision/` | Onboarding and the drag-and-drop ballot |
| `/pizzavision/results` | Live results with per-country point breakdowns and reveal animations |
| `/pizzavision/awards` | Fullscreen awards presentation |
| `/pizzavision/guess` | "Guess the performer" party game with progressive clue reveals |
| `/pizzavision/admin` | Host control panel (password protected) |

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/pizzavision/api/generate-names` | POST | Three candidate band names from the onboarding answers |
| `/pizzavision/api/suggest-answer` | POST | Per-field "surprise me" suggestion |
| `/pizzavision/api/image-state` | GET | Poll the portrait pipeline for a client ID |
| `/pizzavision/api/roast-band` | POST | Roast a guest's act |
| `/pizzavision/api/roast-votes` | POST | Roast a guest's finished ballot |
| `/pizzavision/api/awards` | GET | Calculated award winners as JSON |

Every AI endpoint returns a structured error code (`no_api_key`, `no_openai_package`, `api_error`, and so on) and the frontend treats any non-200 as "hide this block", so a dead key degrades the party rather than ending it.

---

## Live sync

Guests emit `rankchanged`, `nameChanged`, `onboarding_complete`, `prefetch_band_images`, `regenerate_band_images` and `pick_band_image`. Each guest joins a room keyed on their client UUID, and admins join a shared `admin` room.

That room structure is what makes targeted actions work. When the host clears one guest's ballot, only that phone receives `your_rank_cleared` and resets; nobody else is disturbed. Deleting a guest sends `you_were_cleared` to just them and `admin_user_removed` to every open admin tab. Contest state changes broadcast `voting_state_changed` to the whole room, and the users table updates through `admin_user_upsert` and `admin_user_online` rather than polling.

Online presence is tracked by mapping socket IDs to client UUIDs, with the multi-tab case handled: opening a second tab does not re-fire "came online", and closing one tab does not mark someone offline while another is open.

---

## Run it locally

Python 3.10 or newer.

```bash
git clone https://github.com/prdoring/PIZZAVISION.git
cd PIZZAVISION

pip install -r requirements.txt

# Optional, only needed for the AI features
cp .env.example .env   # then fill in your keys

python pizzavision.py
```

The server listens on port 5000. Share the machine's LAN address (for example `http://192.168.1.42:5000`) with guests on the same Wi-Fi.

With no `GOOGLE_CLOUD_PROJECT` set, everything runs locally: TinyDB for votes, `options.json` for config, and local disk for images. No GCP account needed. Without `OPENAI_API_KEY` and `GEMINI_API_KEY` the app still runs, but onboarding falls back to its non-AI paths.

The admin panel is at `/pizzavision/admin`. It sits behind a login screen and falls back to the password `changeme` when `ADMIN_PASSWORD` is unset, so set a real one before letting anyone else onto the network. The deploy script refuses to ship without it.

---

## Configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | For AI features | Band names, field suggestions, image prompts, roasts |
| `GEMINI_API_KEY` | For portraits | Portrait generation |
| `ANTHROPIC_API_KEY` | Optional | Only if routing roasts to Claude |
| `ROAST_PROVIDER` | Optional | `anthropic` swaps the roast provider, default `openai` |
| `ANTHROPIC_ROAST_MODEL` | Optional | Override the Claude model, defaults to `claude-opus-4-7` |
| `ADMIN_PASSWORD` | Yes | Admin panel password. Falls back to `changeme` locally; `deploy.ps1` aborts if it is unset or still the default |
| `SECRET_KEY` | Optional | Signs the admin session cookie. Derived from `ADMIN_PASSWORD` when unset |
| `GOOGLE_CLOUD_PROJECT` | Cloud Run only | Flips all three stores to their cloud backends |
| `PV_GCS_BUCKET` | Cloud Run only | Bucket for generated portraits |
| `PORT` | Optional | Server port, defaults to 5000 locally and 8080 in Docker |
| `FLASK_DEBUG` | Optional | `true` enables debug mode |

The song lineup lives in `pizzavision/options.json`. Each entry needs `label` (formatted `Country: Song`), plus `genre`, `lead`, `language`, `region`, `act_type`, `selection_type`, `returning_artist`, `former_soviet`, `big5`, `drink`, `gdp` and `population`. The same file holds the point distribution and the award artwork and subtext.

---

## Deploying to Cloud Run

`deploy.ps1` wraps the whole lifecycle. It harvests keys from the local `.env` so they do not have to be maintained separately, aborts if the required key is missing, and warns (without blocking) when optional ones are absent.

```powershell
.\deploy.ps1 deploy       # build from source and deploy
.\deploy.ps1 status       # service status and URL
.\deploy.ps1 logs         # recent server logs
.\deploy.ps1 stop         # scale to zero, stop serving
.\deploy.ps1 start        # resume traffic
.\deploy.ps1 restart      # fresh instance, same image
.\deploy.ps1 rollback <commit>
```

The service runs as a single instance with session affinity and a one hour request timeout, which is what WebSockets need. `setup-image-bucket.ps1` provisions the GCS bucket for portraits.

The subdomain commands (`setup-subdomain`, `subdomain-status`, `teardown-subdomain`) attach the service to a load balancer shared with another project of mine. Every mutation there is additive and guarded, and the script health-checks the neighbouring site mid-flight and aborts with rollback instructions if it stops serving.

---

## Project layout

```
pizzavision.py              App entry point, Flask + SocketIO wiring
pizzavision/
  routes.py                 HTTP routes, socket handlers, image pipeline
  utils.py                  Scoring and the 32-award engine
  vote_store.py             Ballots: Firestore or TinyDB
  image_store.py            Portraits: GCS or local disk
  config_store.py           Config: Firestore overlay or JSON file
  openai_client.py          Names, suggestions, image prompts, roasts
  gemini_image_client.py    Portrait generation
  anthropic_client.py       Optional roast provider
  options.json              Song lineup, points, award artwork
  templates/                index, results, awards, guess, admin
  static/                   Assets, plasma shader, presentation JS
deploy.ps1                  Cloud Run lifecycle management
setup-image-bucket.ps1      GCS bucket provisioning
roast_harness.py            Dev tool for tuning roast prompts
Dockerfile                  python:3.12-slim, eventlet server on 8080
```

---

## Running it for a new contest year

1. Drop the new lineup into `pizzavision/options.json` (a dated copy such as `2026options.json` is kept alongside it), and back it up to `options_bak.json` so the admin restore button has something to restore.
2. Swap the `pv*.png` branding in `pizzavision/static/` and update the year strings in the templates.
3. Set `voting_state` back to `pre`.
4. Deploy, then click **Restore Defaults** in the admin panel once. That re-syncs the Firestore config overlay with the new lineup, which the config store deliberately ignores until you do.

---

## Notes

Built for a real annual party, which is the reason for a lot of the defensive design: the AI pipeline never blocks a guest, the storage layer survives scale-to-zero, admin actions are targeted rather than broadcast, and every failure path degrades to something still playable. Nobody wants to debug a WebSocket during the interval act.

Published as a portfolio piece. There is no open source license attached, so please get in touch before reusing the code.

Thanks to the Eurovision community, and to the friends who have stress-tested this at several late-night watch parties. 🍕🎤
