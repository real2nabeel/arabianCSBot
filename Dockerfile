FROM python:3.12-slim

# stdout/stderr straight to `docker compose logs` (the bot logs with print()).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies are pure Python (discord.py, aiomysql, python-a2s), so no
# compiler/toolchain is needed. Copied first so the layer caches across edits.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# bot.py auto-loads cogs via a relative "./cogs" listdir, so run from /app.
RUN useradd --create-home --uid 1000 bot && chown -R bot:bot /app
USER bot

CMD ["python", "bot.py"]
