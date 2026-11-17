# Highlight clips: the host side

The game server finds the moments; this folder turns them into videos; `cogs/clips.py` reviews and posts them.

```
game server                          Discord machine (host)                       bot container
clip_highlights.amxx  ->  clips_YYYYMMDD.jsonl ─┐
HLTV "arabian-servers.com 2013" -> clips-*.dem ─┴─ FTP ─> clips/nightly.py ─> ~/clips/out/<id>/ ─> cogs/clips.py
                                                          (Steam CS 1.6 on :98,     hq.mp4            review channel 👍/❌
                                                           ffmpeg, PulseAudio)      discord.mp4       -> Facebook, Instagram,
                                                                                    meta.json            YouTube, TikTok
```

## What each file does

| File | |
|---|---|
| `demo.py` | Reads HLTV demos (the plugin's hidden `[clips]` lines with their demo time) and writes a copy that makes the camera follow one player in first person. |
| `select.py` | Picks the clips: finds each moment in the demos, builds its window around the player's own kills, merges overlapping moments of one player, best score first. Unit-tested. |
| `render.py` | Plays the moment in Steam's CS 1.6 at normal speed and records screen + sound with ffmpeg. Stops (exit 75) if Steam says the account is playing elsewhere; it never clicks Continue. |
| `compose.py` | Vertical layout from `ClipsPipeline/format_clips.bat` (gameplay 1680 wide over a blurred copy, `host/logo.png`), our own kill feed with the game's weapon icons, a limiter on the sound. Writes `hq.mp4` (1080x1920 60 fps) and `discord.mp4` (720x1280, under 9.5 MB). |
| `nightly.py` | Downloads finished demos and the lists, plans, renders, writes `~/clips/out/<id>/`. Remembers what it made in `~/clips/work/done.json`. With `--if-requested` (the cron mode) it only runs when `/clips-run` left `~/clips/control/request.json`, and reports in `~/clips/control/status.json`. |
| `host/` | X server config and service, the cron line, the logo. |

## Setting up the Discord machine (Debian)

1. Packages: `xserver-xorg-core mesa-utils ffmpeg pulseaudio pulseaudio-utils tmux xdotool python3-pil fonts-dejavu-core`,
   and Steam (`contrib` + `dpkg --add-architecture i386` + `steam-installer`). Log in to Steam once (QR code) and
   install Counter-Strike (app 10).
2. GPU X server on display `:98`, started at boot:
   ```bash
   sudo cp clips/host/xorg-clips.conf /etc/X11/
   sudo cp clips/host/clips-display.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now clips-display
   ```
3. Blank CS's "Press DUCK for Spectator Menu" line once (the renderer's copy of CS only): in
   `cstrike/resource/cstrike_english.txt` (UTF-16) set `"Cstrike_TitlesTXT_Spec_Duck"` to `""`.
4. `~/clips/ftp.env` with the game server's FTP login (`remote_host=`, `port=`, `username=`, `pass=`), readable only by you.
5. Cron (`crontab -e`): the line in `host/crontab.txt`. It checks every minute for a `/clips-run` request
   (a run with nothing requested exits at once). `mkdir -p ~/clips/control`.
6. In the bot's `.env`: the `CLIPS_*` and `META_*` settings (see `.env.example`), including
   `CLIPS_CONTROL_HOST_DIR=/home/<you>/clips/control`, then recreate the container (`docker compose up -d --build`).

Start a run from Discord with `/clips-run` (clip reviewers only); the result is posted in the review channel.
By hand: `python3 -m clips.nightly --dry-run` lists what it would make; without `--dry-run` it makes them.
Log: `~/clips/nightly.log`.

## Things to know

- Steam allows one game at a time per account. If the owner is playing when a run starts, the run stops (Steam
  is shut down, the other session is never kicked) and the review channel says so; run `/clips-run` again later.
- CS is drawn by the Intel GPU (about 30% of one core). Without the GPU X server it falls back to software
  drawing at ~32 FPS using six cores, which is too slow for 60 FPS recording.
- `playdemo` resets the volume and some HUD settings, so `render.py` sets them again after the fast-forward.
- The kill feed appears 0.46 s after a kill's demo time (`compose.KILL_FEED_DELAY`, measured).
