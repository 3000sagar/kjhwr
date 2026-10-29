# Day-Ahead Wind Forecast Portal

## Summary

This React dashboard and read-only FastAPI service replays UK day-ahead wind buying decisions and evaluates WINDFOR forecasts against Elexon FUELHH wind actuals. For a delivery day D, the decision cutoff is 09:00 Europe/London on D-1; for each target start time, the selected forecast is the WINDFOR row with the latest `publishTime` at or before that cutoff. Hourly forecasts are aligned to half-hour periods. The deployed app reads the committed files in `data/processed/` and does not call Elexon.

**Live app:** [https://kjhwr-mu.vercel.app](https://kjhwr-mu.vercel.app)

## Repository guide

- `backend/app/` — FastAPI routes, data loading, forecast selection, schemas, and accuracy metrics.
- `backend/pipeline/` — `fetch.py` downloads source snapshots; `build.py` normalizes them into processed CSVs and the cache; `build_cache.py` rebuilds the cache from processed data.
- `backend/tests/` — API, metric, forecast-selection, Vercel path, and cache acceptance tests.
- `api/index.py` — Vercel FastAPI entry point and path-restoring middleware.
- `frontend/` — React, TypeScript, and Vite dashboard, with local npm scripts in `frontend/package.json`.
- `frontend/scripts/copy-to-public.mjs` — copies the built frontend to the project-root `public/` directory for Vercel static serving.
- `data/processed/` — committed actuals, forecasts, decision table, and `cache/` JSON summaries/charts for cutoff-selection outcomes and modes.
- `docs/notes.md` — detailed data, method, acceptance, and analysis verification log.
- `Dockerfile` — builds the frontend and packages the API and processed data into one image.
- `docker-compose.yml` — runs the container and maps port 8000.
- `vercel.json` — frontend build/output settings, API bundle inclusion, and API/SPA rewrites.
- `requirements.txt` — Python runtime dependencies.

## Run locally

From the repository root, create and activate a virtual environment, then install Python requirements:

```sh
python -m venv .venv
# macOS/Linux
. .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start the backend in one terminal:

```sh
uvicorn backend.app.main:app --reload
```

Start the frontend in a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open the Vite URL printed by the dev server (usually `http://localhost:5173`). The backend API docs are at `http://localhost:8000/docs`.

Run the backend tests from the repository root:

```sh
python -m pytest -q
```

Run the full app in Docker from the repository root:

```sh
docker compose up --build
```

Open the dashboard at `http://localhost:8000` and API docs at `http://localhost:8000/docs`.

## Data refresh

The raw Elexon snapshots under `data/raw/` are intentionally not committed and require network access. Set `BMRS_API_BASE` to the Elexon dataset API base URL, then run these commands from the repository root:

```sh
python -m backend.pipeline.fetch
python -m backend.pipeline.build
```

The fetch step writes `data/raw/fuelhh.json` and `data/raw/windfor.json`; the build step writes processed CSVs and regenerates `data/processed/cache/*.json`. To rebuild only the cache from existing processed data, run:

```sh
python -m backend.pipeline.build_cache
```

## Scope and method

“Purchase decisions made in January 2026” means decisions from January 1–31, with delivery days January 2 through February 1, 2026. FUELHH actuals from December 18, 2025 onward are fetched as lookback data for the trailing bias correction; those earlier actuals are not part of the January decision sample.

The scored set contains **744 hourly forecasts** aligned to **1,488 half-hour points**. The raw forecast has MAE **2,041.96 MW**, bias **+1,747.89 MW**, and a P90 buffer of **4,140.10 MW** (90% day-bootstrap CI **3,250.91–5,317.80 MW**). The trailing bias-corrected result has MAE **1,619 MW** and P90 **3,336 MW**. Paired raw-minus-corrected changes are **+422.84 MW** for MAE (90% CI **+165.02 to +673.75 MW**) and **+803.83 MW** for P90 (90% CI **+403.02 to +1,529.38 MW**).

The displayed P90 buffer is the 90th percentile of `max(forecast - actual, 0)` across all valid half-hours, including zero error values whenever actual wind met or exceeded forecast. Thus the card wording is: “In 90% of half-hours, actual wind came in no more than X MW below forecast.”

The positive bias is similar across forecast horizons, including forecasts published after the target hour. This indicates a forecast-versus-FUELHH definitional gap rather than forecast skill; the cause has not been established. WINDFOR publishes at 02:30, 04:30, 07:30, 09:30, 11:30, 15:30, 18:30, and 22:30 UTC. The 09:00 Europe/London cutoff selects the 07:30 UTC publish, 1.5 hours old. Cutoffs from 07:30 through 09:29 select the same publications and produce identical results. Later cutoffs show no demonstrated accuracy gain. See [the verification log](docs/notes.md) for the detailed checks and cutoff analysis.

## Deployment

Vercel builds the frontend and `frontend/scripts/copy-to-public.mjs` copies `frontend/dist/` into the project-root `public/` directory configured by `vercel.json`. `/api/*` is rewritten to `api/index.py`; middleware restores the original API path. The function bundle includes `data/processed/**`, including the JSON cache. Docker serves the API and dashboard from one container.

## AI use

AI tools (an AI coding assistant and Claude) were used to help plan, write, and review the code, tests, and documentation. The analysis choices and reported numbers were checked against the raw data.

## Limitations and next step

- The analysis covers one January decision month and 31 delivery days.
- The day-level bootstrap ignores multi-day autocorrelation, so its intervals are optimistic.
- The trailing seven-day bias correction is descriptive and in-sample; it has not been independently validated.
- A multiplicative correction looked better on this sample (MAE **1,444 MW**, P90 **3,071 MW**) than the constant-offset correction (MAE **1,619 MW**, P90 **3,336 MW**) or raw forecast (MAE **2,042 MW**, P90 **4,140 MW**), but it was not adopted.
- Hourly forecasts are forward-filled to two half-hour periods.
