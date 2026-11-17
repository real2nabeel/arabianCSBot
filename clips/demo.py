"""Reading and editing GoldSrc (HLTV) demo files.

A demo is a header, a list of "directory entries" (sections) and, inside each section, a stream of frames. Network
frames carry the raw server messages, which is where the clip_highlights plugin's hidden console lines end up:

  [clips] mark <id> t=<game clock>             one per highlight
  [clips] round <n> t=<game clock>             one per round start
  [clips] kill t=.. k=.. v=.. hs=.. w=.. kt=.. vt=..<TAB>killer<TAB>victim

``scan`` finds all of them with their demo time. ``follow`` writes a copy of a demo that makes HLTV's camera follow
one player in first person during a time window (it appends HLTV director messages to every frame in the window;
the game obeys them because spec_autodirector is on by default).
"""
import re
import struct

HEADER_LEN = 8 + 4 + 4 + 260 + 260 + 4 + 4   # magic, demo/net protocol, map, game dir, map crc, directory offset
ENTRY_LEN = 92
FRAME_INFO_LEN = 436 + 28                      # demo info + sequence info before a network message

SVC_DIRECTOR = 51
DRC_CMD_EVENT = 2
DRC_CMD_MODE = 3
OBS_IN_EYE = 4

_LINE = re.compile(rb"\[clips\] (mark|round|kill) ([^\x00\n]*)")


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


def follow(src, dst, entity, t0, t1):
    """Copy ``src`` to ``dst`` with the camera following ``entity`` in first person from t0 to t1 (demo seconds).
    Returns the number of frames changed."""
    d = open(src, "rb").read()
    diroff, = struct.unpack_from("<i", d, HEADER_LEN - 4)
    extra = _director(entity)
    out = bytearray(d[:HEADER_LEN])
    entries, changed = [], 0
    for base, offset, length in _entries(d):
        entry = bytearray(d[base:base + ENTRY_LEN])
        new_offset = len(out)
        for fs, fe, t, msg in _frames(d, offset, offset + length):
            if msg is not None and t0 <= t <= t1:
                mlen, = struct.unpack_from("<i", d, msg)
                out += d[fs:msg] + struct.pack("<i", mlen + len(extra)) + d[msg + 4:fe] + extra
                changed += 1
            else:
                out += d[fs:fe]
        struct.pack_into("<ii", entry, 84, new_offset, len(out) - new_offset)
        entries.append(entry)
    struct.pack_into("<i", out, HEADER_LEN - 4, len(out))
    out += struct.pack("<i", len(entries)) + b"".join(entries)
    open(dst, "wb").write(out)
    return changed
