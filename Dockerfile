FROM python:3.12-slim

# stdout/stderr straight to `docker compose logs` (the bot logs with print()).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Fonts for server-generated leaderboard graphics (including Arabic names).
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Pillow provides prebuilt wheels; no compiler/toolchain is needed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# bot.py auto-loads cogs via a relative "./cogs" listdir, so run from /app.
RUN useradd --create-home --uid 1000 bot && chown -R bot:bot /app
USER bot

CMD ["python", "bot.py"]
