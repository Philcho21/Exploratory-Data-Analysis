# Operations Guide — Recruitment Scraper Pipeline

How to install, run, and operate the pipeline and scheduler.

---

## 1. Prerequisites

### Python version
Python 3.10 or later is required (the code uses `match`-free type hints
that need 3.10+ union syntax).

### Install dependencies
From inside the project folder:
```bash
pip install -r requirements.txt
```

`requirements.txt` contains:
```
requests>=2.31
beautifulsoup4>=4.12
lxml>=5.2
schedule>=1.2
```

If you are not inside a virtual environment and get a permissions error, add
`--break-system-packages`:
```bash
pip install -r requirements.txt --break-system-packages
```

### Project folder structure
```
Jobs Project/
├── utils.py               # shared data model, geocoder, salary parser
├── base_scraper.py        # abstract base class for HTML scrapers
├── reed_scraper.py        # Reed.co.uk Partner API
├── adzuna_scraper.py      # Adzuna multi-country API
├── themuse_scraper.py     # The Muse global API (no key)
├── remotive_scraper.py    # Remotive remote jobs API (no key)
├── arbeitnow_scraper.py   # Arbeitnow global tech API (no key)
├── pipeline.py            # ETL orchestrator
├── scheduler.py           # 12-hour recurring runner
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── output/                # created automatically — CSV, JSON, briefings
└── logs/                  # created automatically — rotating scheduler log
```

---

## 2. API Keys

### Built-in keys (zero setup required)
The pipeline ships with working API keys hardcoded for Reed and Adzuna.
You can run everything immediately without registering anywhere.

| Source | Key location | Override env var |
|--------|-------------|-----------------|
| Reed | `reed_scraper.py → _DEFAULT_KEY` | `REED_API_KEY` |
| Adzuna | `adzuna_scraper.py → _DEFAULT_APP_ID / _DEFAULT_API_KEY` | `ADZUNA_APP_ID`, `ADZUNA_API_KEY` |
| The Muse | No key needed | — |
| Remotive | No key needed | — |
| Arbeitnow | No key needed | — |

### Using your own keys (optional)
Set environment variables before running:
```bash
export REED_API_KEY=your_reed_key
export ADZUNA_APP_ID=your_app_id
export ADZUNA_API_KEY=your_api_key
```

Or pass them inline:
```bash
python pipeline.py --reed-key your_key --adzuna-id your_id --adzuna-key your_key
```

---

## 3. Running the Pipeline (one-off)

### Full default run — all 16 keywords, 5 countries
```bash
python pipeline.py
```
This runs all 16 job titles across GB, US, DE, FR, AU and writes three
output files to `output/`.

**Expected duration:** 20–40 minutes (dominated by geocoding delays and
polite rate-limiting between requests).

**To skip geocoding and run faster (~5–10 min):**
```bash
python pipeline.py --no-geo
```

---

### Targeting specific keywords
```bash
python pipeline.py --keywords "Data Analyst,Data Scientist,DevOps Engineer"
```
Comma-separated, no spaces around commas. Keyword matching is
case-insensitive.

### Targeting specific countries
```bash
python pipeline.py --countries gb,us
python pipeline.py --countries us,de,fr,au,ca,in
```

Available country codes: `gb us au ca de fr in nl nz pl sg za br mx at be`

### Targeting a specific city
```bash
python pipeline.py --location "London"
python pipeline.py --location "New York" --countries us
```

When `--location` is empty (the default), each source searches
country-wide.

---

### Adjusting page counts

**Important:** Adzuna has a hard limit of 250 requests/day on the free tier.
The formula is:

```
Adzuna requests = len(keywords) × len(countries) × adzuna_pages
```

The default (16 × 5 × 3 = 240) fits within the limit. If you reduce
keywords or countries you can safely raise `--adzuna-pages`.

```bash
# Fewer keywords → can afford more Adzuna pages
python pipeline.py --keywords "Data Analyst,Data Engineer" --adzuna-pages 10

# Raise Reed pages (no hard cap)
python pipeline.py --reed-pages 10

# Raise TheMuse / Arbeitnow pages (no cap)
python pipeline.py --themuse-pages 5 --arbeitnow-pages 5
```

---

### Disabling individual sources
```bash
python pipeline.py --no-reed         # skip Reed
python pipeline.py --no-adzuna       # skip Adzuna (saves API budget)
python pipeline.py --no-remote       # skip Remotive
python pipeline.py --no-themuse      # skip The Muse
python pipeline.py --no-arbeitnow    # skip Arbeitnow
```

---

### Full CLI reference
```
usage: pipeline.py [-h]
  [--keywords KEYWORDS]
  [--location LOCATION]
  [--countries COUNTRIES]
  [--reed-pages N]
  [--adzuna-pages N]
  [--themuse-pages N]
  [--arbeitnow-pages N]
  [--adzuna-limit N]
  [--reed-key KEY]
  [--adzuna-id ID]
  [--adzuna-key KEY]
  [--no-reed] [--no-adzuna] [--no-remote] [--no-themuse] [--no-arbeitnow]
  [--no-geo]
```

---

## 4. Output Files

Each pipeline run writes three files to `output/`, named with a UTC timestamp:

```
output/
└── multi_keyword_20260530_1435.csv          ← spreadsheet-ready flat table
└── multi_keyword_20260530_1435.json         ← full structured records
└── multi_keyword_20260530_1435_briefing.txt ← human-readable summary report
```

The CSV and JSON contain identical data. Use the CSV for Excel / pandas /
any BI tool. Use the JSON for downstream API consumption or database loading.
The briefing text file is a quick-read intelligence summary.

---

## 5. Running the Scheduler (recurring every 12 hours)

### Start with defaults
```bash
python scheduler.py
```

The scheduler:
1. Runs the full pipeline **immediately** on start (you get data right away)
2. Waits 12 hours
3. Runs again
4. Repeats until stopped

### Change the interval
```bash
python scheduler.py --interval 6    # every 6 hours
python scheduler.py --interval 24   # once a day
```

### Pass through pipeline options
All pipeline flags are available on the scheduler:
```bash
python scheduler.py \
  --keywords "Data Analyst,Data Engineer,DevOps Engineer" \
  --countries gb,us,de \
  --interval 12 \
  --no-geo
```

### Stopping the scheduler
Press `Ctrl+C`. The scheduler catches the signal and exits cleanly after the
current pipeline run finishes. It will not interrupt a run mid-way.

### Logs
The scheduler writes to both stdout and `logs/scheduler.log`.
The log file rotates automatically at 10 MB, keeping the last 5 files
(50 MB total). To follow logs live in a second terminal:
```bash
tail -f logs/scheduler.log
```

### Full CLI reference
```
usage: scheduler.py [-h]
  [--keywords KEYWORDS]
  [--location LOCATION]
  [--countries COUNTRIES]
  [--interval HOURS]
  [--reed-pages N]
  [--adzuna-pages N]
  [--themuse-pages N]
  [--arbeitnow-pages N]
  [--no-reed] [--no-adzuna] [--no-remote] [--no-themuse] [--no-arbeitnow]
  [--no-geo]
```

---

## 6. Running in the Background (Linux / macOS)

### Using nohup (simplest)
```bash
nohup python scheduler.py > logs/nohup.out 2>&1 &
echo $! > logs/scheduler.pid
```

Stop it later:
```bash
kill $(cat logs/scheduler.pid)
```

### Using screen
```bash
screen -S scraper
python scheduler.py
# Detach: Ctrl+A then D
# Reattach: screen -r scraper
```

### Using systemd (Linux server, persistent across reboots)
Create `/etc/systemd/system/recruitment-scraper.service`:
```ini
[Unit]
Description=Recruitment Scraper Pipeline
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/path/to/Jobs Project
ExecStart=/usr/bin/python3 scheduler.py
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable recruitment-scraper
sudo systemctl start recruitment-scraper
sudo journalctl -u recruitment-scraper -f   # follow logs
```

---

## 7. Running with Docker (production deployment)

### Build and start
```bash
docker-compose up -d
```

### Follow logs
```bash
docker-compose logs -f scraper
```

### Stop
```bash
docker-compose down
```

Output files appear in `./output/` and logs in `./logs/` on the host machine
(bind-mounted from the container), so data persists across container restarts.

### Override the search at runtime
```bash
docker-compose run --rm scraper \
  --keywords "Data Analyst,DevOps Engineer" \
  --countries gb,us,de \
  --interval 12
```

---

## 8. Common Issues

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `ModuleNotFoundError: No module named 'schedule'` | Dependencies not installed | `pip install -r requirements.txt` |
| Adzuna returns 0 results for all keywords | Daily 250-request budget already exhausted | Wait until UTC midnight for the budget to reset |
| `RuntimeError: Adzuna daily budget exhausted` | Too many keywords × countries × pages | Reduce `--adzuna-pages`, or reduce `--countries` |
| TheMuse returns 0 for a keyword | Keyword too specific / not in any job title or HTML description | Try a broader term |
| Geocoding very slow | Nominatim enforces 1 req/s; many unique locations | Pass `--no-geo` for fast runs; geocoding can be done as a post-process |
| Output files not appearing | `output/` directory permissions | Run `mkdir -p output` in the project folder |