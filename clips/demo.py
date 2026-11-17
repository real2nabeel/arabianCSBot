"""Reading and editing GoldSrc (HLTV) demo files.

A demo is a header, a list of "directory entries" (sections) and, inside each section, a stream of frames. Network
frames carry the raw server messages, which is where the clip_highlights plugin's hidden console lines end up:

  [clips] mark <id> t=<game clock>             one per highlight
  [clips] round <n> t=<game clock>             one per round start
  [clips] kill t=.. k=.. v=.. hs=.. w=.. kt=.. vt=..<TAB>killer<TAB>victim
  [clips] anim t=.. p=<slot> a=<animation> b=<body>   every weapon animation (the game sends these only to the
                                                     weapon's owner, so HLTV wouldn't have them otherwise)

``scan`` finds the mark/round/kill lines with their demo time. ``follow`` writes a copy of a demo that makes HLTV's
camera follow one player in first person during a time window (it appends HLTV director messages to every frame in
the window; the game obeys them because spec_autodirector is on by default), and turns that player's anim lines
into real weapon animation messages, so switching, reloading and knife attacks animate.

  [clips] msg t=.. p=<slot> n=<name> a=<type>:<value>,...   a message the game sent to that player only
                                                            (SetFOV, ScreenFade, ScreenShake, Damage)

``follow`` rebuilds the followed player's messages byte for byte (AMX Mod X argument types, encoded the way the
engine writes them) using the message numbers from the demo's own svc_newusermsg table, so scope zoom, flashbangs,
grenade shake and the hit indicator show in the clip.

``follow`` also adds a console-only time marker ("[clipsync] <demo seconds>", a TextMsg to the console) every half
second up to the clip's start. CS prints them to its console log while it plays the copy, so the renderer can see
exactly where the playback is instead of guessing from how many frames it has run.
"""
import re
import struct

HEADER_LEN = 8 + 4 + 4 + 260 + 260 + 4 + 4   # magic, demo/net protocol, map, game dir, map crc, directory offset
ENTRY_LEN = 92
FRAME_INFO_LEN = 436 + 28                      # demo info + sequence info before a network message

SVC_WEAPONANIM = 35
SVC_DIRECTOR = 51
DRC_CMD_EVENT = 2
DRC_CMD_MODE = 3
OBS_IN_EYE = 4

_LINE = re.compile(rb"\[clips\] (mark|round|kill) ([^\x00\n]*)")
_ANIM = re.compile(rb"\[clips\] anim t=[0-9.]+ p=(\d+) a=(\d+) b=(\d+)")
_MSG = re.compile(rb"\[clips\] msg t=[0-9.]+ p=(\d+) n=(\w+) a=([-0-9.:,]*)")
# One-player messages the plugin copies to HLTV: scope zoom, flashbang, grenade shake, hit indicator.
PERSONAL_MSGS = ("SetFOV", "ScreenFade", "ScreenShake", "Damage")
SYNC_EVERY = 0.5          # demo seconds between time markers
SYNC_RE = re.compile(r"\[clipsync\] ([0-9.]+)")
HUD_PRINTCONSOLE = 2


class DemoError(Exception):
    pass


def _frames(d, p, end):
    """Yield (frame_start, frame_end, time, msg_offset or None) for one directory entry."""
    while p < end:
        start = p
        ftype, t, _ = struct.unpack_from("<Bfi", d, p)
        p += 9
        msg = None
        if ftype in (0, 1):
            p += FRAME_INFO_LEN
            msg = p
            mlen, = struct.unpack_from("<i", d, p)
            p += 4 + mlen
        elif ftype == 2:
            pass
        elif ftype == 3:
            p += 64
        elif ftype == 4:
            p += 32
        elif ftype == 5:
            yield start, p, t, None
            return
        elif ftype == 6:
            p += 84
        elif ftype == 7:
            p += 8
        elif ftype == 8:
            p += 4
            slen, = struct.unpack_from("<i", d, p)
            p += 4 + slen + 16
        elif ftype == 9:
            blen, = struct.unpack_from("<i", d, p)
            p += 4 + blen
        else:
            raise DemoError(f"unknown frame type {ftype} at byte {start}")
        yield start, p, t, msg


def _entries(d):
    if d[:8] != b"HLDEMO\x00\x00":
        raise DemoError("not a GoldSrc demo")
    diroff, = struct.unpack_from("<i", d, HEADER_LEN - 4)
    if not 0 < diroff < len(d):
        raise DemoError("no directory (the demo was not finished)")
    count, = struct.unpack_from("<i", d, diroff)
    for e in range(count):
        base = diroff + 4 + e * ENTRY_LEN
        offset, length = struct.unpack_from("<ii", d, base + 84)
        yield base, offset, length


def map_name(d):
    return d[16:16 + 260].split(b"\x00", 1)[0].decode("latin1")


def scan(path):
    """All [clips] lines in a demo: {"marks": {id: t}, "rounds": [(n, t)], "kills": [dict]} (t in demo seconds)."""
    d = open(path, "rb").read()
    marks, rounds, kills, seen = {}, [], [], set()
    for _, offset, length in _entries(d):
        for _, _, t, msg in _frames(d, offset, offset + length):
            if msg is None:
                continue
            mlen, = struct.unpack_from("<i", d, msg)
            body = d[msg + 4:msg + 4 + mlen]
            if b"[clips]" not in body:
                continue
            for m in _LINE.finditer(body):
                if m.group(0) in seen:   # HLTV can repeat a reliable message in a later frame
                    continue
                seen.add(m.group(0))
                kind, text = m.group(1), m.group(2).decode("utf8", "replace")
                if kind == b"mark":
                    marks[text.split()[0]] = round(t, 3)
                elif kind == b"round":
                    rounds.append((int(text.split()[0]), round(t, 3)))
                else:
                    kills.append(parse_kill(text, t))
    return {"map": map_name(d), "marks": marks, "rounds": rounds, "kills": kills}


def parse_kill(text, t):
    fields, *names = text.split("\t")
    k = dict(x.split("=", 1) for x in fields.split() if "=" in x)
    return {"t": round(t, 3), "k": int(k.get("k", 0)), "v": int(k.get("v", 0)), "hs": int(k.get("hs", 0)),
            "w": k.get("w", ""), "kt": int(k.get("kt", 0)), "vt": int(k.get("vt", 0)),
            "kn": names[0] if names else "", "vn": names[1] if len(names) > 1 else ""}


def _director(entity):
    event = bytes([DRC_CMD_EVENT]) + struct.pack("<hhi", entity, 0, 0)
    mode = bytes([DRC_CMD_MODE, OBS_IN_EYE])
    return bytes([SVC_DIRECTOR, len(mode)]) + mode + bytes([SVC_DIRECTOR, len(event)]) + event


SVC_NEWUSERMSG = 39


def user_messages(d, names=PERSONAL_MSGS + ("TextMsg",)):
    """{name: (id, size)} from the demo's svc_newusermsg table (size 255 = variable length)."""
    out = {}
    for name in names:
        key = name.encode() + b"\x00"
        pos = d.find(key)
        while pos != -1:
            if pos >= 3 and d[pos - 3] == SVC_NEWUSERMSG:
                out[name] = (d[pos - 2], d[pos - 1])
                break
            pos = d.find(key, pos + 1)
    return out


def encode_args(text):
    """"1:90,3:-2,6:12.5" (AMX Mod X type:value) -> the bytes the engine writes for those arguments."""
    out = bytearray()
    for item in filter(None, text.split(",")):
        kind, _, value = item.partition(":")
        kind = int(kind)
        if kind in (1, 2):                       # byte, char
            out += struct.pack("<B", int(value) & 0xFF)
        elif kind in (3, 8):                     # short, entity
            out += struct.pack("<H", int(value) & 0xFFFF)
        elif kind == 4:                          # long
            out += struct.pack("<I", int(value) & 0xFFFFFFFF)
        elif kind == 5:                          # angle: 1/256ths of a turn
            out += struct.pack("<B", int(float(value) * 256 / 360) & 0xFF)
        elif kind == 6:                          # coord: 1/8ths of a unit
            out += struct.pack("<H", int(float(value) * 8) & 0xFFFF)
        else:
            raise ValueError(f"unsupported argument type {kind}")
    return bytes(out)


def _user_message(table, name, args):
    if name not in table:
        return b""
    msg_id, size = table[name]
    payload = encode_args(args)
    if size == 255:
        return bytes([msg_id, len(payload)]) + payload
    return bytes([msg_id]) + payload if len(payload) == size else b""


def console_text(table, text):
    """A TextMsg that prints ``text`` to the console only (nothing on screen), or b"" if the demo has no TextMsg."""
    if "TextMsg" not in table:
        return b""
    msg_id, size = table["TextMsg"]
    payload = bytes([HUD_PRINTCONSOLE]) + text.encode("latin1") + b"\x00"
    return bytes([msg_id, len(payload)]) + payload if size == 255 else b""


def follow(src, dst, entity, t0, t1, sync_until=None):
    """Copy ``src`` to ``dst`` with the camera following ``entity`` in first person from t0 to t1 (demo seconds),
    with a time marker every SYNC_EVERY seconds before ``sync_until`` (see the module notes).
    Returns the number of frames changed."""
    d = open(src, "rb").read()
    diroff, = struct.unpack_from("<i", d, HEADER_LEN - 4)
    extra = _director(entity)
    table = user_messages(d)
    out = bytearray(d[:HEADER_LEN])
    entries, changed, seen = [], 0, set()
    next_sync = 0.0
    # Markers only after the game has learnt the TextMsg number (an unknown user message would stop the demo).
    key = b"TextMsg\x00"
    registered = d.find(key)
    while registered != -1 and not (registered >= 3 and d[registered - 3] == SVC_NEWUSERMSG):
        registered = d.find(key, registered + 1)
    for base, offset, length in _entries(d):
        entry = bytearray(d[base:base + ENTRY_LEN])
        new_offset = len(out)
        for fs, fe, t, msg in _frames(d, offset, offset + length):
            add = b""
            if (msg is not None and sync_until is not None and next_sync <= t < sync_until
                    and registered != -1 and fs > registered):
                add += console_text(table, f"[clipsync] {t:.2f}")
                next_sync = t + SYNC_EVERY
            if msg is not None and t0 <= t <= t1:
                mlen, = struct.unpack_from("<i", d, msg)
                add += extra
                body = d[msg + 4:msg + 4 + mlen]
                if b"[clips] anim" in body:
                    for m in _ANIM.finditer(body):
                        if int(m.group(1)) == entity and m.group(0) not in seen:   # HLTV can repeat a line
                            seen.add(m.group(0))
                            add += bytes([SVC_WEAPONANIM, int(m.group(2)) & 0xFF, int(m.group(3)) & 0xFF])
                if b"[clips] msg" in body:
                    for m in _MSG.finditer(body):
                        if int(m.group(1)) == entity and m.group(0) not in seen:
                            seen.add(m.group(0))
                            add += _user_message(table, m.group(2).decode(), m.group(3).decode())
            if add:
                mlen, = struct.unpack_from("<i", d, msg)
                out += d[fs:msg] + struct.pack("<i", mlen + len(add)) + d[msg + 4:fe] + add
                changed += 1
            else:
                out += d[fs:fe]
        struct.pack_into("<ii", entry, 84, new_offset, len(out) - new_offset)
        entries.append(entry)
    struct.pack_into("<i", out, HEADER_LEN - 4, len(out))
    out += struct.pack("<i", len(entries)) + b"".join(entries)
    open(dst, "wb").write(out)
    return changed
