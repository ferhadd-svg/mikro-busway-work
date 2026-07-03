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

### 5. Seed default salespeople (Eric + Gladness)

```bash
python -m app.seed
```

To add a new salesperson later, use the **Admin** tab in the browser UI.

### 6. Upload the price list

Start the server (step 7), then go to **Admin → Price List → Upload**.

### 7. Start the server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser at: **http://localhost:8000**

---

## Using the system

### For salespeople

1. Open **http://\<server-ip\>:8000** in any browser (Chrome, Edge, Firefox).
2. Click **+ New Project**.
3. Fill in: Our Ref, Client Name, Attn, M&E, and select your name.
4. Upload the SLD drawing (PDF, PNG, or JPG).
5. Wait ~20 seconds — Claude reads the drawing automatically.
6. Review the flagged items. Enter the **LME rate** and **USD→MYR rate** (required every time). Fill in any missing feeder lengths.
7. Click **Confirm & Continue** → **Generate BOQ** → **Generate Quotation**.
8. Download the Excel files.

### For Balveen (admin)

Open the **Admin** tab to:
- **Upload a new price list** — becomes active immediately for all users.
- **Add / deactivate salespeople** — newcomers are added here; they show up in the salesperson dropdown instantly.
- **Upload quotation templates** — drop in `QUOTATION_TEMPLATE_<FIRSTNAME>.xlsx`; picked up automatically by name.

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

## API documentation

Interactive API docs (for developers): **http://localhost:8000/docs**

---

## Project workflow (7 steps via API)

| Step | Endpoint | Description |
|---|---|---|
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
| `PIU` | Plug-in unit rates (Hyundai, by A + kA) |
| `BI METAL PLATE` | Bi-metal plate rates |

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
  seed.py               ← Pre-load Eric + Gladness

data/
  mikro_busway.db       ← SQLite database (auto-created)
  price_list/           ← Upload price lists here
  templates/            ← Upload salesperson templates here
  projects/             ← Generated BOQ + quotation files
```

---

## Adding a new salesperson

**Via browser (easiest):** Admin tab → Add salesperson → fill Name + Title → Add.

**Via seed script:** Edit `app/seed.py`, add to `DEFAULT_SALESPEOPLE`, re-run `python -m app.seed`.

**Via API:**
```bash
curl -X POST http://localhost:8000/salespeople/ \
  -H "Content-Type: application/json" \
  -d '{"name":"Ahmad Fariz","title":"Sales Engineer","mobile":"+60 12-345 6789","email":"ahmad@mikro.com.my"}'
```
