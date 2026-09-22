"""Pure alert timing and public query validation."""
from dataclasses import dataclass


def human_count(info):
    """Unknown/invalid bot counts must never be treated as zero bots."""
    total = getattr(info, "player_count", None)
    bots = getattr(info, "bot_count", None)
    capacity = getattr(info, "max_players", None)
    if not all(type(value) is int for value in (total, bots, capacity)):
        return None
    if not 0 <= bots <= total <= capacity:
        return None
    return total - bots


@dataclass
class ActivityWindow:
    threshold: int = 15
    sustain: int = 120
    rearm_below: int = 4
    rearm_seconds: int = 300
    cooldown: int = 7200
    max_gap: int = 75
    high_since: float | None = None
    low_since: float | None = None
    last_sample: float | None = None

    def observe(self, humans, *, now, wall_time, armed, last_alert):
        # Timers are intentionally not restored after a restart: missing samples
        # cannot prove that either population condition held while offline.
        if self.last_sample is not None and now - self.last_sample > self.max_gap:
            self.high_since = self.low_since = None
        self.last_sample = now
        if humans is None:
            self.high_since = self.low_since = None
            return None
        if armed:
            self.low_since = None
            if humans < self.threshold:
                self.high_since = None
                return None
            if self.high_since is None:
                self.high_since = now
            if now - self.high_since >= self.sustain and (
                not last_alert or wall_time - last_alert >= self.cooldown
            ):
                return "alert"
        else:
            self.high_since = None
            if humans >= self.rearm_below:
                self.low_since = None
                return None
            if self.low_since is None:
                self.low_since = now
            if now - self.low_since >= self.rearm_seconds:
                return "rearm"
        return None
