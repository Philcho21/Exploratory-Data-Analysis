# ── Recruitment Scraper Pipeline ──────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# System deps for lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Source
COPY *.py .

# Output + log directories (can be bind-mounted)
RUN mkdir -p output logs

# Default: run the scheduler (every 12 h, global search)
ENTRYPOINT ["python", "scheduler.py"]
CMD ["--keyword", "Data Analyst, Data Scientist, Data Engineer", "--countries", "gb,us,de", "--pages", "2"]
