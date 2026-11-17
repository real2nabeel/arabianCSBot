"""Nightly clip job (run on the Discord machine as the desktop user, see clips/README.md).

1. Download finished HLTV demos (clips-*.dem) and the plugin's lists (clips_*.jsonl) from the game server.
2. Find each listed moment in the demos and pick the best (clips.select.plan).
3. Record each one with sound (clips.render) and make the two video files (clips.compose).
4. Write CLIPS_OUT/<key>/{hq.mp4, discord.mp4, meta.json}. The bot picks those up and posts them for review.

Safe to run often (cron every 30 minutes at night): a lock stops overlapping runs, finished clips are remembered in
WORK/done.json, and if Steam is busy because the owner is playing, the run stops and the next one carries on.

    python -m clips.nightly [--dry-run] [--limit N]
Exit codes: 0 done or nothing to do, 75 Steam busy (try later), 1 error.
"""
import argparse
import datetime as dt
import fcntl
import ftplib
import json
import os
import sys
import time

from clips import compose, demo, render, select

HOME = os.path.expanduser("~/clips")
WORK = os.environ.get("CLIPS_WORK", os.path.join(HOME, "work"))
OUT = os.environ.get("CLIPS_OUT", os.path.join(HOME, "out"))
FTP_ENV = os.environ.get("CLIPS_FTP_ENV", os.path.join(HOME, "ftp.env"))
REMOTE_DEMOS = "servers/hlds/cstrike"
REMOTE_LISTS = "servers/hlds/cstrike/addons/amxmodx/logs"
PER_RUN = int(os.environ.get("CLIPS_PER_NIGHT", "8"))
MIN_SCORE = int(os.environ.get("CLIPS_MIN_SCORE", "30"))
KEEP_DAYS = int(os.environ.get("CLIPS_KEEP_DAYS", "4"))
SETTLED_SECONDS = 600    # a demo not written to for this long is finished (HLTV starts a new one every map)


def say(msg):
    print(f"{dt.datetime.now():%H:%M:%S} {msg}", flush=True)


def read_env(path):
    cfg = {}
    for line in open(path, encoding="utf8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def fetch():
    """Download finished demos and the last two days' lists. Returns the local demo folder."""
    cfg = read_env(FTP_ENV)
    demos_dir = os.path.join(WORK, "demos")
    os.makedirs(demos_dir, exist_ok=True)
    ftp = ftplib.FTP(timeout=120)
    ftp.connect(cfg["remote_host"], int(cfg.get("port", 21)))
    ftp.login(cfg["username"], cfg["pass"])
    ftp.voidcmd("TYPE I")
    now = dt.datetime.now(dt.timezone.utc)
    try:
        for name, f in ftp.mlsd(REMOTE_DEMOS, facts=["type", "size", "modify"]):
            if f.get("type") != "file" or not (name.startswith("clips-") and name.endswith(".dem")):
                continue
            modified = dt.datetime.strptime(f["modify"][:14], "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
            if (now - modified).total_seconds() < SETTLED_SECONDS:
                continue  # still being recorded
            local = os.path.join(demos_dir, name)
            if os.path.exists(local) and os.path.getsize(local) == int(f["size"]):
                continue
            say(f"downloading {name} ({int(f['size']) / 1e6:.0f} MB)")
            with open(local + ".part", "wb") as fh:
                ftp.retrbinary(f"RETR {REMOTE_DEMOS}/{name}", fh.write)
            os.replace(local + ".part", local)
        for day in (now - dt.timedelta(days=1), now):
            name = f"clips_{day:%Y%m%d}.jsonl"
            try:
                with open(os.path.join(WORK, name + ".part"), "wb") as fh:
                    ftp.retrbinary(f"RETR {REMOTE_LISTS}/{name}", fh.write)
                os.replace(os.path.join(WORK, name + ".part"), os.path.join(WORK, name))
            except ftplib.error_perm:
                os.remove(os.path.join(WORK, name + ".part"))  # no highlights that day (yet)
    finally:
        ftp.quit()
    return demos_dir


def load_moments():
    moments = []
    for name in sorted(os.listdir(WORK)):
        if name.startswith("clips_") and name.endswith(".jsonl"):
            for line in open(os.path.join(WORK, name), encoding="utf8", errors="replace"):
                line = line.strip()
                if line:
                    try:
                        moments.append(json.loads(line))
                    except ValueError:
                        pass
    return moments


def scan_demos(demos_dir):
    """Scan results per demo, cached next to each demo."""
    out = {}
    for name in sorted(os.listdir(demos_dir)):
        if not name.endswith(".dem"):
            continue
        path = os.path.join(demos_dir, name)
        cache = path + ".scan.json"
        if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(path):
            out[path] = json.load(open(cache, encoding="utf8"))
            continue
        try:
            info = demo.scan(path)
        except demo.DemoError as e:
            say(f"skipping {name}: {e}")
            continue
        json.dump(info, open(cache, "w", encoding="utf8"))
        out[path] = info
    return out


def cleanup(demos_dir):
    cutoff = time.time() - KEEP_DAYS * 86400
    for name in os.listdir(demos_dir):
        path = os.path.join(demos_dir, name)
        if os.path.getmtime(path) < cutoff:
            os.remove(path)


def make_clip(clip, info, done):
    key = clip["key"]
    out_dir = os.path.join(OUT, key)
    tmp_dir = os.path.join(WORK, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    followed = os.path.join(tmp_dir, "follow.dem")
    raw = os.path.join(tmp_dir, "raw.mkv")
    demo.follow(clip["demo"], followed, clip["entity"], clip["start"] - 10, clip["end"] + 2)
    length = clip["end"] - clip["start"]
    took = render.record(followed, clip["start"], length, raw)
    compose.compose(raw, info["kills"], clip["start"], out_dir + ".part", featured=clip["entity"])
    meta = {k: clip[k] for k in ("key", "map", "player", "team", "score", "summary")}
    first = clip["moments"][0]
    meta.update({"date": first.get("date", ""), "round": first.get("round"), "length": round(length, 1),
                 "types": sorted({m["type"] for m in clip["moments"]}),
                 "moments": clip["moments"], "demo": os.path.basename(clip["demo"]),
                 "rendered": dt.datetime.now().isoformat(timespec="seconds")})
    json.dump(meta, open(os.path.join(out_dir + ".part", "meta.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    if os.path.exists(out_dir):
        os.rename(out_dir, out_dir + ".old")
    os.rename(out_dir + ".part", out_dir)   # the bot only sees complete folders
    done[key] = meta["rendered"]
    os.remove(raw)
    say(f"made {key}: {clip['player']} - {clip['summary']} ({length:.0f} s, recorded in {took:.0f} s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="download and choose, but don't render")
    ap.add_argument("--limit", type=int, default=PER_RUN)
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    lock = open(os.path.join(WORK, "lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        say("another run is still going")
        return 0
    done_path = os.path.join(WORK, "done.json")
    done = json.load(open(done_path)) if os.path.exists(done_path) else {}

    demos_dir = os.path.join(WORK, "demos") if a.no_fetch else fetch()
    demos = scan_demos(demos_dir)
    moments = load_moments()
    clips = [c for c in select.plan(moments, demos, top=10_000, min_score=MIN_SCORE) if c["key"] not in done]
    say(f"{len(moments)} moments listed, {len(demos)} demos, {len(clips)} new clips; making up to {a.limit}")
    for c in clips[:a.limit]:
        say(f"  {c['score']:>4}  {c['player']} - {c['summary']} ({c['end'] - c['start']:.0f} s, {os.path.basename(c['demo'])})")
    if a.dry_run or not clips:
        return 0

    render.ensure_display()
    render.ensure_audio()
    render.start_steam()
    status = 0
    try:
        for c in clips[:a.limit]:
            try:
                make_clip(c, demos[c["demo"]], done)
            except render.SteamBusy as e:
                say(f"stopping: {e}; the next run will carry on")
                status = 75
                break
            except Exception as e:  # one bad clip shouldn't stop the night
                say(f"failed {c['key']}: {type(e).__name__}: {e}")
                done[c["key"]] = "failed"
            json.dump(done, open(done_path, "w"), indent=1)
    finally:
        if os.environ.get("CLIPS_STOP_STEAM", "1") == "1":
            render.stop_steam()
        cleanup(demos_dir)
    return status


if __name__ == "__main__":
    sys.exit(main())
