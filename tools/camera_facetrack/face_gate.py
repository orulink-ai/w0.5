"""Presence debounce only; tracking IDs are never treated as identities."""


class FaceGate:
    def __init__(self, stable_seconds=1.0, leave_seconds=3.0):
        self.stable_seconds = stable_seconds
        self.leave_seconds = leave_seconds
        self.armed = True
        self.present_since = None
        self.absent_since = None

    def suspend(self):
        # Paused/stale video is unknown, never evidence that someone left.
        self.present_since = None
        self.absent_since = None

    def block_until_departure(self):
        self.armed = False
        self.suspend()

    def update(self, present, now, fresh=True):
        if not fresh:
            self.suspend()
            return False
        if present:
            self.absent_since = None
            if self.present_since is None:
                self.present_since = now
            if self.armed and now - self.present_since >= self.stable_seconds:
                self.armed = False
                return True
        else:
            self.present_since = None
            if self.absent_since is None:
                self.absent_since = now
            if now - self.absent_since >= self.leave_seconds:
                self.armed = True
        return False
