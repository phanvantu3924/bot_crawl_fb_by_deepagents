FROM python:3.11-slim

# ── System dependencies (Chrome + ChromeDriver) ───────────────────────────
RUN apt-get update && apt-get install -y \
    wget curl gnupg unzip \
    # Chrome dependencies
    fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 \
    libatspi2.0-0 libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 \
    libnspr4 libnss3 libxcomposite1 libxdamage1 libxfixes3 \
    libxkbcommon0 libxrandr2 xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# ── Install Google Chrome (Modern way without apt-key) ────────────────────
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# ── Python app ────────────────────────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ── Run ───────────────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
EXPOSE 5000
# Updated to use main:app with 1 worker and multiple threads so in-memory state is shared
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "300", "main:app"]
