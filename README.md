# Day-Ahead Wind Forecast Portal

A React dashboard and read-only FastAPI service for reviewing wind generation forecasts used in day-ahead power buying. It shows the latest eligible WINDFOR forecast at a configurable cutoff and its historical accuracy against FUELHH wind actuals. The deployed app reads only files under `data/processed/`; it never calls Elexon.

## Scope and assumptions

- “Decisions made in January 2026” means decisions on Jan 1–31, so delivery days are Jan 2–Feb 1, 2026.
- A decision for delivery day D uses the prior day cutoff in Europe/London (default 09:00).
- For each target start time, selection uses the row with the maximum WINDFOR `publishTime` at or before the cutoff. Hourly forecasts are repeated across the two half-hour periods.
- The snapshot uses Elexon FUELHH (WIND) actuals and WINDFOR forecasts only. Actuals cover Dec 18, 2025 through Feb 1, 2026; this lookback supports the D-8 through D-2 correction while the scored decision window remains 31 delivery days.
- The dashboard shows raw and bias-corrected MAE and P90 buffer with intervals, plus separate bias and spread. Its sample size is 744 hourly forecasts. It states the one-month limit and labels the empirical uncertainty band as in-sample.

## Files and directories

- `frontend/` contains the Vite, React and TypeScript dashboard.
- `backend/app/` contains API routes, configuration, selection, and metrics.
- `backend/pipeline/fetch.py` downloads source snapshots locally; `build.py` normalizes them and builds the cache; `build_cache.py` can rebuild the cache alone.
- `backend/tests/` contains selection, metric, API, and cache acceptance tests.
- `api/index.py` and `vercel.json` configure the Vercel function, frontend build, processed data bundle, and SPA routes.
- `data/processed/` contains actuals, forecasts, the decision table, and `cache/` JSON for each selection outcome and mode. `data/raw/` is local pipeline input and is not included in the app.
- `Dockerfile` and `docker-compose.yml` run the API and dashboard together. `docs/notes.md` records the phase results.

## Start locally

For local development, install `requirements.txt` in a Python environment, run `uvicorn backend.app.main:app --reload` from the repository root, then in a second terminal run `cd frontend`, `npm ci`, and `npm run dev`. Vite serves the dashboard and proxies `/api` to FastAPI at port 8000. The API docs are at `http://localhost:8000/docs`.

To build and run the complete app in Docker, run `docker compose up --build` from the repository root. The app is at `http://localhost:8000`, with API docs at `/docs`.

Docker close-out was verified on this machine: the image built and the container started; `GET /docs` returned 200, `GET /api/health` returned `200 {"status":"ok"}`, and `GET /accuracy` returned `200 text/html; charset=utf-8`.

To refresh the snapshot, run `python -m backend.pipeline.fetch`, then `python -m backend.pipeline.build`. The build step creates `data/processed/cache/*.json`. The API startup only loads those JSON files; it does not fetch Elexon or recalculate the summaries, bootstrap intervals, or chart tables.

## Vercel

Frontend API requests use relative `/api/...` paths. `vercel.json` builds the frontend, routes API requests to the Python function, includes `data/processed/**` (including `cache/`) in the function bundle, and rewrites client-side paths to the app shell. The deployment is not yet created; deployment and the live URL are user-owned. **Live app URL: pending deployment.** After deployment, record the URL here and check the app and API docs in an incognito window.

## Limitations and next step

- The scored sample is one month (31 delivery days; 744 hourly forecasts), so it does not establish year-round performance.
- The delivery-day bootstrap treats days as independent and ignores multi-day autocorrelation; its confidence intervals may be optimistic.
- The trailing correction is evaluated in-sample on this month, using a fixed D-8 through D-2 window; it is descriptive, not independent validation.
- A multiplicative correction is a next step to validate: on this sample it had MAE/P90 1,444/3,071 MW, compared with 1,619/3,336 MW for the constant offset and 2,042/4,140 MW raw. This comparison did not change the correction model.

## AI use

AI coding tools assisted with scaffolding, implementation, and documentation. The project’s maintainers reviewed the code, selection rule, assumptions, and analysis.
