# Pizzavision
![Banner](pizzavision/static/pv25.png)
Your drop‑in party companion for scoring Eurovision with friends. Guests choose a fun **band name**, rank each song live, then watch real‑time leaderboards and quirky awards unfold on a shared screen.

---

## Table of Contents

1. [Features](#features)
2. [Quick Start](#quick-start)
3. [Pages & Endpoints](#pages--endpoints)
4. [Admin Interface](#admin-interface)
5. [Configuration](#configuration)
6. [Development](#development)
7. [Contributing](#contributing)
8. [License](#license)

---

## Features

* **One‑command launch** – run the server from any laptop and share the local address with party‑goers.
* **Mobile‑friendly voting** – each guest ranks entries from their phone, identified by a custom or auto‑generated band name.
* **Live scoreboard** – points update instantly on every device via SocketIO.
* **Tongue‑in‑cheek awards** – Pop Diva, Rockstar, Big 5 Champion, Tastemaker, Contrarian, drink‑themed prizes, and more.
* **Admin control panel** – reorder or remove songs, clear votes, and restore the database.
* **Zero cloud setup** – everything runs locally, data stored in TinyDB.

---

## Quick Start

```bash
# 1. Clone the repo
$ git clone https://github.com/your‑username/pizzavision.git
$ cd pizzavision

# 2. Install dependencies (Python >= 3.10)
$ pip install -r requirements.txt

# 3. Launch the server
$ python pizzavision.py

# 4. Share the printed local address (for example http://192.168.1.42:5000) with your guests.
```

---

## Pages & Endpoints

| Path                   | Purpose                                                         |
| ---------------------- | --------------------------------------------------------------- |
| `/` or `/pizzavision`  | Main voting interface where guests submit and adjust rankings.  |
| `/pizzavision/results` | Real‑time results table and country points breakdown.           |
| `/pizzavision/awards`  | Animated awards reveal once voting closes.                      |
| `/pizzavision/admin`   | Host‑only control panel for song & vote management (see below). |

All routes are served from the same Flask application on port 5000 by default.

---

## Admin Interface

The **Admin** page ( `/pizzavision/admin` ) lets the host manage the night without digging into the database:

| Control             | What it does                                                                                 |
| ------------------- | ----------------------------------------------------------------------------                 |
| **Reorder**         | Drag entries to change the running order (updates immediately for everyone).                 |
| **Remove**          | Remove a song, currently all entries are in the list, you may want to prune after semis.     |
| **Delete Vote**     | Clear all votes and users from the DB (useful after testing)                                 |
| **Restore / Reset** | Bring back all songs from the original list                                                  |

> **Heads‑up:** After heavy admin changes some browsers may cache stale data. If a guest’s screen acts weird, ask them to *hard‑refresh* or clear site data.

---

## Configuration

| Item               | How to tweak                                                                                                                          |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Song list**      | Edit `data/options.json` – each entry must include `label`, `genre`, `lead`, `language`, `former_soviet`, `drink`, and `big5` fields. |
| **Starting votes** | Clear `data/db.json` before a new party or use *Admin → Reset*.                                                                       |
| **Awards**         | Logic lives in `calculate_awards()` inside `backend/awards.py`. Feel free to add or remove trophies.                                  |
| **Port / host**    | Change `HOST` and `PORT` constants at the top of `pizzavision.py` or pass `--host` and `--port` flags when launching.                 |
| **Branding**       | Swap out the logo in `static/img/logo.svg` and update CSS variables in `static/css/theme.css`.                                        |

---

## Contributing

Pull requests are welcome! Open an issue first if you plan a large change so we can discuss direction.

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/my‑cool‑thing`
3. Commit your changes and push: `git push origin feature/my‑cool‑thing`
4. Open a PR – remember to include before/after screenshots where UI is affected.

---

## License

Distributed under the MIT License. See `LICENSE` for more information.

---

### Acknowledgements

Huge thanks to the Eurovision community and to friends who helped test Pizzavision at countless late‑night watch parties. 🍕🎤
