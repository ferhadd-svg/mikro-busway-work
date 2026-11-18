# Mikro Busway Quotation Engine

A local API server that turns an SLD drawing into a priced busway BOQ and quotation — automatically, using Claude AI.

---

## What it does

```
Upload SLD drawing  →  Claude reads it (two-pass)  →  Review flags  →  BOQ Excel  →  Quotation Excel
```

- Any salesperson (including newcomers) opens a browser, uploads a drawing, confirms a few values (LME rate, any missing lengths), and downloads finished Excel files.
- Balveen (admin) manages salespeople and price lists from the same browser UI.

---

## Quick start (one-time setup)

### 1. Install Python 3.11+

Download from https://python.org if not already installed.

### 2. Get the code

```bash
git clone https://github.com/ferhadd-svg/mikro-busway-work.git
cd mikro-busway-work
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` and add your Anthropic API key:
```
ANTHROPIC_API_KEY=sk-ant-...
```

Get an API key from https://console.anthropic.com

### 5. Seed default salespeople and the admin login

```bash
python -m app.seed
```

This adds Eric + Gladness and, on an empty database, creates the admin login
(`ADMIN_EMAIL`, default `admin@itmikro.com`). Set `ADMIN_PASSWORD` in `.env`
first to choose its password; otherwise a random one is printed **once** —
log in and change it (Change password button).

To add a new salesperson later, use the **Admin** tab in the browser UI. Each
salesperson also needs a **login** (Admin → User Accounts) linked to their salesperson
record — a sales login only sees its own projects.

### 6. Price list

A default price list ships in `app/bundled_price_list/` and loads
automatically. To use a newer one, go to **Admin → Price List → Upload**
(after starting the server, step 7). A file with no feeder rates is rejected
and the current list stays active; a file missing a sheet (e.g. PIU) is
loaded with a warning, and those items price at RM 0 until fixed.

### 7. Start the server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser at: **http://localhost:8000**

---

## Using the system

### For salespeople

1. Open **http://\<server-ip\>:8000** in any browser (Chrome, Edge, Firefox) and log in.
2. Click **+ New Project**.
3. Fill in: Our Ref, Client Name, Attn, M&E, and select your name.
4. Upload the SLD drawing (PDF, PNG, JPG or TIFF, up to 50 MB — `MAX_DRAWING_MB`).
5. Wait ~20 seconds — Claude reads the drawing automatically.
6. Review the flagged items. Enter the **LME rate** and **USD→MYR rate** (required every time). Fill in any missing feeder lengths.
7. Click **Confirm & Continue** → **Generate BOQ** → **Generate Quotation**.
8. Download the Excel files.

### For Balveen (admin)

Open the **Admin** tab to:
- **Upload a new price list** — becomes active immediately for all users.
- **Add / deactivate salespeople** — newcomers are added here; they show up in the salesperson dropdown instantly.
- **Upload quotation templates** — drop in `QUOTATION_TEMPLATE_<FIRSTNAME>.xlsx` (`.xlsx` only — re-save an old `.xls` as `.xlsx`); picked up automatically by name.
- **Manage logins** — create users (admin or sales), link each sales login to its salesperson, reset passwords.

---

## Running on the company server

On Windows, create a batch file `start_server.bat`:
```bat
@echo off
set ANTHROPIC_API_KEY=sk-ant-...
uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
```

Double-click to start. Colleagues connect to `http://<your-pc-ip>:8000`.

On Linux/Mac:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## Hosting on Render

`render.yaml` deploys the `new-mikro-16` web service. Render's free plan has
no persistent disk, so set `DATABASE_URL` to a hosted Postgres (e.g. Neon or
Supabase): users, projects, uploaded price lists, templates, drawings and
generated files are all kept in the database and written back to disk when
needed. Also set `ANTHROPIC_API_KEY`, `ADMIN_EMAIL` and `ADMIN_PASSWORD`, and
optionally `BREVO_API_KEY` + `EMAIL_FROM` for "Email Quotation". A scheduled
GitHub Action (`.github/workflows/keep-awake.yml`) pings the app every 10
minutes so it doesn't sleep.

---

## API documentation

Interactive API docs (for developers): **http://localhost:8000/docs**

---

## Project workflow (7 steps via API)

| Step | Endpoint | Description |
|---|---|---|
| 0 | `POST /auth/login` | Log in (session cookie) — every endpoint below needs it |
| 1 | `POST /projects/` | Create project record |
| 2 | `POST /projects/{id}/drawing` | Upload SLD → Claude reads it |
| 3 | `GET /projects/{id}/flags` | See what needs confirmation |
| 4 | `POST /projects/{id}/flags` | Submit LME + flag answers |
| 5 | `POST /projects/{id}/generate-boq` | Generate BOQ Excel |
| 6 | `POST /projects/{id}/generate-quotation` | Generate quotation Excel |
| 7 | `GET /projects/{id}/download/boq` | Download BOQ file |
|   | `GET /projects/{id}/download/quotation` | Download quotation file |

---

## Price list format

The engine reads four sheets from your Mikro price list Excel:

| Sheet name | Used for |
|---|---|
| `List Price (Al)` | All aluminium rates |
| `List Price (Cu)` | All copper rates |
| `PIU & TOU` | Plug-in unit rates (Hyundai, by A + kA) |
| `BI METAL PLATE` | Bi-metal plate rates |

Feeders are priced from the `Feeder 3P (4W) + 50%E` / `+ 100%E` rows, or
`Feeder 3P (5W) + 50%E` for a 3P5W run. Where an accessory table is repeated
on a sheet, the first (net) table is used. A run smaller than the smallest
size listed for its material (copper starts at 400A) is priced at that
smallest size, with a note on the BOQ.

---

## File structure

```
app/
  main.py               ← FastAPI entry point
  config.py             ← Settings (.env)
  database.py           ← SQLite setup
  models/               ← Database models
  schemas/              ← Pydantic data shapes
  routers/              ← API endpoints
  services/
    drawing_reader.py   ← Claude vision (two-pass SLD read)
    price_list.py       ← Rate lookups
    boq_builder.py      ← BOQ Excel generator
    quotation_builder.py← Quotation Excel generator
  static/
    index.html          ← Browser UI
  seed.py               ← Pre-load Eric + Gladness and the admin login

data/
  mikro_busway.db       ← SQLite database (auto-created; set DATABASE_URL for Postgres)
  price_list/           ← Upload price lists here
  templates/            ← Upload salesperson templates here
  projects/             ← Generated BOQ + quotation files
```

---

## Adding a new salesperson

**Via browser (easiest):** Admin tab → Add salesperson → fill Name + Title → Add.

**Via seed script:** Edit `app/seed.py`, add to `DEFAULT_SALESPEOPLE`, re-run `python -m app.seed`.

**Via API** (admin session cookie required — log in first):
```bash
curl -c cookies.txt -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" -d '{"email":"admin@itmikro.com","password":"..."}'
curl -b cookies.txt -X POST http://localhost:8000/salespeople/ \
  -H "Content-Type: application/json" \
  -d '{"name":"Ahmad Fariz","title":"Sales Engineer","mobile":"+60 12-345 6789","email":"ahmad@mikro.com.my"}'
```
