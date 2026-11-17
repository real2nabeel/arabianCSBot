"""Recording one moment of a demo, with sound, using Steam's CS 1.6 on the GPU X server.

CS's own `startmovie` writes frames without sound, so the moment is played at normal speed and ffmpeg records the
screen (x11grab) and a PulseAudio null sink together. Before that, the demo is fast-forwarded with a large
host_framerate step. Settings that `playdemo` resets (volume, the kill feed time) are applied after the
fast-forward, then the config prints ==REC== to the console log, which starts the recording.

Steam lets one account run one game at a time: if the owner is playing elsewhere, Steam asks (inside its main
window) whether to disconnect that session, and logs "KickingOtherSession". The dialog is never answered: Steam is
shut down, which cancels the launch, and SteamBusy is raised so the nightly job can try again later.
"""
import os
import shutil
import subprocess
import time

HL = os.path.expanduser(os.environ.get("CLIPS_HL_DIR", "~/.steam/debian-installation/steamapps/common/Half-Life"))
DISPLAY = os.environ.get("CLIPS_DISPLAY", ":98")
SINK = os.environ.get("CLIPS_SINK", "clips")
VOLUME = os.environ.get("CLIPS_VOLUME", "0.5")
STEP = 0.25            # demo seconds per frame while fast-forwarding (the screen is capped at 60 frames a second)
DEMO_NAME = "clipsrender"
# Debian puts Steam in /usr/games, which cron's minimal PATH leaves out.
STEAM = os.environ.get("CLIPS_STEAM") or shutil.which("steam") or "/usr/games/steam"


class SteamBusy(Exception):
    """Steam refused to start CS because the account is playing on another computer."""


class RenderError(Exception):
    pass


def _env():
    return {**os.environ, "DISPLAY": DISPLAY, "PULSE_SINK": SINK}


def _run(*cmd, check=False, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, env=_env(), check=check, **kw)


def ensure_audio():
    """A null sink called SINK as the default output, kept awake so its monitor never stalls."""
    if _run("pactl", "info").returncode != 0:
        _run("pulseaudio", "--start", "--exit-idle-time=-1")
        time.sleep(1)
    if SINK not in _run("pactl", "list", "short", "sinks").stdout:
        _run("pactl", "load-module", "module-null-sink", f"sink_name={SINK}", f"sink_properties=device.description={SINK}")
    _run("pactl", "set-default-sink", SINK)
    if "module-suspend-on-idle" in _run("pactl", "list", "short", "modules").stdout:
        _run("pactl", "unload-module", "module-suspend-on-idle")
    # Pin the sound server so Steam, CS (started via tmux, which can carry another environment) and ffmpeg all
    # use the same one; otherwise CS can play into one server while ffmpeg records silence from another.
    for line in _run("pactl", "info").stdout.splitlines():
        if line.startswith("Server String:"):
            server = line.split(":", 1)[1].strip()
            os.environ["PULSE_SERVER"] = server if ":" in server else f"unix:{server}"


def ensure_display():
    if _run("xrandr").returncode != 0:
        raise RenderError(f"no X server on {DISPLAY}; start clips-display.service (see clips/README.md)")


def steam_running():
    return _run("pgrep", "-x", "steam").returncode == 0


def start_steam(wait=90):
    if steam_running():
        return
    _run("tmux", "kill-session", "-t", "steam")
    log = os.path.expanduser("~/clips/steam.log")
    _run("tmux", "new-session", "-d", "-s", "steam", f"export DISPLAY={DISPLAY} PULSE_SINK={SINK} PULSE_SERVER='{os.environ.get('PULSE_SERVER', '')}'; "
         f"{STEAM} > {log} 2>&1")
    time.sleep(wait)


def stop_steam():
    if steam_running():
        _run(STEAM, "-shutdown")
        time.sleep(15)
    _run("tmux", "kill-session", "-t", "steam")


def _waits(n):
    out = []
    for size, alias in ((500, "w500"), (50, "w50")):
        out += [alias] * (n // size)
        n %= size
    return ";".join(out + ["wait"] * n)


def write_config(start):
    """clipfind.cfg: fast-forward DEMO_NAME to ``start`` demo seconds, then play it normally and print ==REC==."""
    lines = [
        'alias w50 "' + ";".join(["wait"] * 50) + '"',
        'alias w500 "w50;w50;w50;w50;w50;w50;w50;w50;w50;w50"',
        f"volume {VOLUME}", "cl_showfps 0", "fps_max 100",
        f"host_framerate {STEP}", f"playdemo {DEMO_NAME}",
        _waits(int(round(start / STEP))),
        "host_framerate 0", "stopsound", f"volume {VOLUME}", "hud_deathnotice_time 0", "cl_showfps 0",
        "echo ==REC==",
    ]
    with open(os.path.join(HL, "cstrike", "clipfind.cfg"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


STEAM_LOG = os.path.expanduser(os.environ.get("CLIPS_STEAM_LOG", "~/.steam/debian-installation/logs/console_log.txt"))
BUSY_MARK = "KickingOtherSession"   # Steam logs this while it asks whether to kick the owner's other session


def _log_size():
    try:
        return os.path.getsize(STEAM_LOG)
    except OSError:
        return 0


def _steam_busy_since(offset):
    """True if Steam logged, after ``offset`` bytes, that it is asking to kick the account's other session."""
    try:
        with open(STEAM_LOG, "rb") as fh:
            fh.seek(offset)
            return BUSY_MARK.encode() in fh.read()
    except OSError:
        return False


def record(demo_path, start, length, out_mkv, start_timeout=120):
    """Record ``length`` seconds of ``demo_path`` from demo time ``start`` into ``out_mkv`` (1080p60 + sound)."""
    shutil.copyfile(demo_path, os.path.join(HL, "cstrike", DEMO_NAME + ".dem"))
    write_config(start)
    console = os.path.join(HL, "qconsole.log")
    if os.path.exists(console):
        os.remove(console)
    _run("pkill", "-x", "hl_linux")
    log_offset = _log_size()
    subprocess.Popen([STEAM, "-applaunch", "10", "-windowed", "-noborder", "-w", "1920", "-h", "1080", "-novid",
                      "-nojoy", "-condebug", "+exec", "clipfind.cfg"],
                     env=_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    began = time.time()
    while True:
        text = open(console, errors="replace").read() if os.path.exists(console) else ""
        if "==REC==" in text:
            break
        waited = time.time() - began
        if _steam_busy_since(log_offset):
            # Steam is showing "already playing on another computer". Never answer it: shutting Steam down
            # cancels the launch and leaves the owner's game alone.
            stop_steam()
            raise SteamBusy("Steam says the account is in a game on another computer")
        if waited > start_timeout:
            _run("pkill", "-x", "hl_linux")
            raise RenderError(f"CS did not reach the moment within {start_timeout} s")
        time.sleep(0.05)
    ff = _run("ffmpeg", "-nostdin", "-loglevel", "error", "-y",
              "-thread_queue_size", "1024", "-video_size", "1920x1080", "-framerate", "60", "-f", "x11grab", "-i", DISPLAY,
              "-thread_queue_size", "1024", "-f", "pulse", "-i", f"{SINK}.monitor", "-t", f"{length:.2f}",
              "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", "-c:a", "pcm_s16le", out_mkv,
              stdin=subprocess.DEVNULL)
    _run("pkill", "-x", "hl_linux")
    if ff.returncode != 0 or not os.path.exists(out_mkv):
        raise RenderError(f"ffmpeg failed: {ff.stderr.strip()[-300:]}")
    return time.time() - began
