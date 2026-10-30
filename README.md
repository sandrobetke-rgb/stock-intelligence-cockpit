# Stock Intelligence Cockpit

Dark-mode React cockpit + Python data pipeline + GitHub Actions. Designed for desktop and mobile.

## Architecture (free-first)
- Python (`yfinance`, `pandas`) calculates daily stock data and Balanced quality filters.
- GitHub Actions runs the pipeline on weekdays and publishes JSON files to GitHub Pages.
- React/Vite reads the published JSON as a static REST-style API (`/api/*.json`).
- No always-on server, paid API key, or private X/Facebook scraping is required.

> GitHub Pages JSON endpoints are public and read-only. Do not publish private watchlists, credentials, account data, or confidential notes. A real authenticated write API requires a separate backend host/database.

## Included views
Overview, Quality Stocks, Opportunity Radar (including failed filters), Social Intelligence, Politics, Fact Check, Trading Lab.
The social/politics views ingest user-provided CSV files. They are intentionally not presented as automatic feeds: X, Facebook, and many Reddit data endpoints require platform approval/API access and may impose restrictions.

## Setup
1. Create a new GitHub repository, e.g. `stock-intelligence-cockpit`.
2. Upload the complete contents of this folder to the repository root.
3. In GitHub: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
4. In **Settings → Actions → General**, allow workflows to create and approve pull requests only if needed; this project only publishes Pages.
5. Run **Actions → Build stock data → Run workflow** once.
6. Enable Pages (step 3). Your cockpit will be available at `https://<USERNAME>.github.io/<REPOSITORY>/`.

The scheduled workflow runs Monday–Friday at 22:30 UTC. GitHub scheduled runs can be delayed. This is 23:30 in German winter time and 00:30 next day in summer time. Change `.github/workflows/publish.yml` to adjust.

## Data sources / limits
- Prices and available company fundamentals: Yahoo Finance via `yfinance` (unofficial wrapper; availability and terms can change).
- Universe: starter list in `backend/config/universe.csv`; edit it to add/remove tickers.
- Balanced quality filters: market cap >= $1bn, positive operating cash flow where available, positive revenue growth where available, debt/equity <= 2 where available, and trend/volume checks. Missing fundamentals are marked `unknown`, not silently treated as passed.
- This is a research aid, not financial advice. No automatic order execution.
- Social and political items: add records to `data/imports/social.csv` and `data/imports/politics.csv`. The pipeline scores source quality and flags unverified claims; it does not infer that a politician's disclosed transaction is a recommendation.
- `data/imports/fact_checks.csv` can hold claims and primary-source URLs.

## Local development
### Pipeline
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r backend/requirements.txt
python backend/run_pipeline.py
```
Outputs are written to `public/api/`.

### Frontend
```bash
cd frontend
npm install
npm run dev
```
For local UI against generated data, set `VITE_API_BASE_URL=/api` in `frontend/.env`.
```bash
npm run build
```

## Import CSV formats
- `social.csv`: `date,ticker,platform,author,claim,url,engagement`
- `politics.csv`: `date,politician,ticker,transaction,amount_range,disclosure_url`
- `fact_checks.csv`: `date,ticker,claim,verdict,evidence_url,notes`

Keep URLs to original posts/disclosures/documents. Do not add private group content or credentials.
