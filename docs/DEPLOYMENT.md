# GitHub, Render, and OpenAI deployment

This repository is a FastAPI application, not a Frappe application. The production configuration below matches the code deployed at https://work-16.onrender.com.

## 1. GitHub repository

1. Upload these changes to ferhadd-svg/mikro-busway-work on branch main.
2. In GitHub, open Settings > Actions > General and allow GitHub Actions.
3. Open Settings > Branches, protect main, and require the test status check before merging.
4. Never add a real .env file or API key to GitHub. The ignore rules exclude environment files while retaining the examples.

The workflow in .github/workflows/ci.yml compiles the application and runs unit tests on pushes and pull requests.

## 2. Render connection

1. In Render, choose New > Blueprint.
2. Connect GitHub and select ferhadd-svg/mikro-busway-work.
3. Select branch main and apply render.yaml.
4. When Render asks for OPENAI_API_KEY, paste a key created in the OpenAI Console. Do not put this key in render.yaml.
5. If retaining the existing work-16 service, set its build command, start command, health check, disk, and environment variables to match render.yaml.

autoDeployTrigger: checksPass deploys main only after GitHub checks pass. The persistent disk preserves SQLite data. Keep one application worker while using SQLite. Seed data runs in the start command because Render disks are available only at runtime, not during builds.

## 3. Environments

Development commands:

    Copy-Item .env.development.example .env
    # Edit .env and set your own OPENAI_API_KEY
    python -m pip install -r requirements.txt
    uvicorn app.main:app --reload

For production, Render provides the values listed in .env.production.example. The real OpenAI key exists only in Render's Environment page.

## 4. Verification

After Render deploys:

    python scripts/test_render_api.py
    python scripts/test_render_api.py --test-claude

Endpoints:

- GET /health verifies the web service.
- GET /ai/status reports configuration without making a paid request.
- POST /ai/test-connection makes a minimal authenticated OpenAI request.
- POST /ai/analyze-file accepts a photo, PDF, spreadsheet, CSV, or text file.
- POST /projects/{project_id}/drawing extracts busway runs from an SLD.

The application logs startup state, OpenAI failures, and provider request IDs. It never logs or returns the API key.

## 5. Troubleshooting

- A 503 from /ai/test-connection means OPENAI_API_KEY is missing.
- A 502 means OpenAI rejected or could not complete the request; inspect Render logs for the request ID.
- A failed health check means the application did not start or the disk is not mounted at /opt/render/project/src/data.
- SQLite is appropriate for one Render instance. Move DATABASE_URL to managed PostgreSQL before horizontal scaling.
