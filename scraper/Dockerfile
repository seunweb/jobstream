# ── Stage 1: build ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# System deps for Playwright + BeautifulSoup
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev libssl-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Playwright system dependencies + correct font package names for Debian Trixie
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libdbus-1-3 libxkbcommon0 libx11-6 libxcomposite1 libxdamage1 \
    libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libxshmfence1 wget ca-certificates \
    fonts-unifont fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY . .

# Install Playwright browser only (deps installed manually above)
RUN playwright install chromium

ENV DB_PATH=/app/data/jobstream.db

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
