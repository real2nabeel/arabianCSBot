"""Recording one moment of a demo, with sound, using Steam's CS 1.6 on the GPU X server.

CS's own `startmovie` writes frames without sound, so the moment is played at normal speed and ffmpeg records the
screen (x11grab) and a PulseAudio null sink together. Before that, the demo is fast-forwarded with a large
host_framerate step.

How far a fast-forward frame gets depends on the demo (a frame of an update-rate-100 demo covered about a quarter
of the 0.25 s asked for), so the frames aren't counted, and the game can't be steered while it plays (it doesn't
re-read a config it has already run). Instead the demo copy (demo.follow) carries:
  - SLOW_COMMANDS at SLOW_LEAD seconds before the moment: normal speed, and the settings `playdemo` resets (volume,
    the kill feed time), ending with "echo ==SLOW==";
  - a console-only time marker every half second up to the moment.
CS prints both to qconsole.log. The renderer checks that ==SLOW== came, then starts recording when a marker says the
moment is due (at normal speed a demo second is a real second).

Steam lets one account run one game at a time: if the owner is playing elsewhere, Steam asks (inside its main
window) whether to disconnect that session, and logs "KickingOtherSession". The dialog is never answered: Steam is
shut down, which cancels the launch, and SteamBusy is raised so the nightly job can try again later.
"""
import os
import shutil
import subprocess
import time

from clips import demo

HL = os.path.expanduser(os.environ.get("CLIPS_HL_DIR", "~/.steam/debian-installation/steamapps/common/Half-Life"))
DISPLAY = os.environ.get("CLIPS_DISPLAY", ":98")
SINK = os.environ.get("CLIPS_SINK", "clips")
VOLUME = os.environ.get("CLIPS_VOLUME", "0.5")
STEP = 0.25            # host_framerate while fast-forwarding (asked-for demo seconds per frame)
SLOW_LEAD = 15.0       # switch to normal speed this many demo seconds before the moment
SLOW_COMMANDS = f"host_framerate 0;stopsound;volume {VOLUME};hud_deathnotice_time 0;cl_showfps 0;echo ==SLOW=="
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


def _write(name, lines):
    path = os.path.join(HL, "cstrike", name)
    with open(path + ".tmp", "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(path + ".tmp", path)   # the game may exec it at any moment


def write_config():
    """clipfind.cfg: play DEMO_NAME fast-forwarding; the demo itself switches to normal speed (SLOW_COMMANDS)."""
    _write("clipfind.cfg", [f"volume {VOLUME}", "cl_showfps 0", "fps_max 100",
                            f"host_framerate {STEP}", f"playdemo {DEMO_NAME}"])


# Console lines meaning the demo didn't load (e.g. a model the server uses that this CS doesn't have).
FAILURE_MARKS = ("cannot continue without", "disconnecting", "couldn't open", "bad demo")

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


class _Console:
    """Reads what CS appends to qconsole.log."""

    def __init__(self, path):
        self.path, self.pos = path, 0

    def new_text(self):
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.pos)
                data = fh.read()
        except OSError:
            return ""
        self.pos += len(data)
        return data.decode("latin1")


def record(demo_path, start, length, out_mkv, start_timeout=400):
    """Record ``length`` seconds of ``demo_path`` from demo time ``start`` into ``out_mkv`` (1080p60 + sound).
    The demo must come from demo.follow with sync_until=start and commands=(start - SLOW_LEAD, SLOW_COMMANDS)."""
    shutil.copyfile(demo_path, os.path.join(HL, "cstrike", DEMO_NAME + ".dem"))
    write_config()
    console = os.path.join(HL, "qconsole.log")
    if os.path.exists(console):
        os.remove(console)
    _run("pkill", "-x", "hl_linux")
    log_offset = _log_size()
    subprocess.Popen([STEAM, "-applaunch", "10", "-windowed", "-noborder", "-w", "1920", "-h", "1080", "-novid",
                      "-nojoy", "-condebug", "+exec", "clipfind.cfg"],
                     env=_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    began = time.time()
    log, slow, tail = _Console(console), False, ""
    while True:
        text = log.new_text()
        lines = (tail + text).split("\n")
        tail = lines.pop()   # an unfinished last line is read again next time
        failed = next((line.strip() for line in lines if any(m in line.lower() for m in FAILURE_MARKS)), None)
        if failed:
            # The config keeps running after playdemo fails, so without this the error screen gets recorded.
            _run("pkill", "-x", "hl_linux")
            raise RenderError(f"CS couldn't play the demo: {failed}")
        if any("==SLOW==" in line for line in lines):
            slow = True
        marks = [m for line in lines for m in demo.SYNC_RE.findall(line)]
        if marks:
            at = float(marks[-1])
            if not slow and at > start - SLOW_LEAD + 3:
                _run("pkill", "-x", "hl_linux")
                raise RenderError(f"the demo's switch to normal speed didn't run (playback at {at:.1f} s)")
            if slow and at >= start - 2 * demo.SYNC_EVERY:
                if at > start:
                    _run("pkill", "-x", "hl_linux")
                    raise RenderError(f"playback overshot the moment (at {at:.1f} s, moment at {start:.1f} s)")
                time.sleep(max(0.0, start - at))   # normal speed now: demo seconds are real seconds
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
