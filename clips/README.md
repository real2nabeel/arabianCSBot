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
| `select.py` | Picks the clips: finds each moment in the demos, builds its window around the player's own kills, merges overlapping moments of one player, and scores each clip on the kills it shows (knife kills, headshots, AWP kills and fast bursts count most; only 1v6 and bigger clutches get much for the clutch). Best first. Unit-tested. |
| `render.py` | Plays the moment in Steam's CS 1.6 at normal speed and records screen + sound with ffmpeg. Stops (exit 75) if Steam says the account is playing elsewhere; it never clicks Continue. |
| `compose.py` | Vertical layout from `ClipsPipeline/format_clips.bat` (gameplay over a blurred copy at the old clips' 945 px height, with the spectator top bar hidden in the game and the bottom one cropped), a band above the gameplay with `host/logo.png` and the server name as its biggest line, the play under it ("TRIPLE KILL · AK-47", "1v3 CLUTCH", named like the server's streak announcements), a details line and kill dots that fill as each kill lands (the only area TikTok, Reels and Shorts all leave uncovered), our own kill feed with the game's weapon icons, a limiter on the sound. Writes `hq.mp4` (1080x1920 60 fps) and `discord.mp4` (720x1280, under 9.5 MB). |
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
5. Cron (`crontab -e`): the lines in `host/crontab.txt`. One checks every minute for a `/clips-run` request
   (a run with nothing requested exits at once); one downloads new demos every hour without rendering,
   because the game server deletes its demos after a day; and one makes the day's 20 best new clips at 04:00
   (the machine's clock is on Palestine time, `Asia/Gaza`, so cron follows its summer and winter time).
   `mkdir -p ~/clips/control`.
6. In the bot's `.env`: the `CLIPS_*` and `META_*` settings (see `.env.example`), including
   `CLIPS_CONTROL_HOST_DIR=/home/<you>/clips/control`, then recreate the container (`docker compose up -d --build`).

Clips are made every morning at 04:00 Palestine time (the 20 best new ones; at about 100 a day, the rest are
dropped with their demos after 4 days). Start an extra run from Discord with `/clips-run` (clip reviewers only);
the result is posted in the review channel. The 04:00 run posts only the clips themselves.
By hand: `python3 -m clips.nightly --dry-run` lists what it would make; without `--dry-run` it makes them.
Log: `~/clips/nightly.log`.

## Things to know

- Steam allows one game at a time per account. If the owner is playing when a run starts, the run stops (Steam
  is shut down, the other session is never kicked) and the review channel says so; run `/clips-run` again later.
- CS is drawn by the Intel GPU (about 30% of one core). Without the GPU X server it falls back to software
  drawing at ~32 FPS using six cores, which is too slow for 60 FPS recording.
- The server's own models, sounds, sprites and HUD graphics (skins, plugin models) are mirrored once a day into the
  renderer's `cstrike_downloads` (`nightly.sync_content`), with any custom map a demo uses: demo playback can't
  download them and CS stops with "Cannot continue without model ...". If CS fails to load a demo, the clip
  fails with that console line instead of recording the error screen.
- `playdemo` resets the volume and some HUD settings, so `render.py` sets them again after the fast-forward.
- Picture brightness is set in `clipfind.cfg` before `playdemo`, because CS builds a map's lighting when it loads: `brightness 1.77`, `gamma 2.76` (about 90% on the video sliders; change with `CLIPS_BRIGHTNESS` / `CLIPS_GAMMA` in the host's environment). The game's own defaults, 0 and 2.2, made clips darker than the game looks to players.
- The kill feed appears 0.46 s after a kill's demo time (`compose.KILL_FEED_DELAY`, measured).
