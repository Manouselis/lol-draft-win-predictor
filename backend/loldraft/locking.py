from contextlib import contextmanager
from pathlib import Path
import os


@contextmanager
def exclusive(path: Path):
    """An OS lock prevents two collectors spending the same API quota."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as file:
        file.seek(0)
        if path.stat().st_size == 0:
            file.write(b"0")
            file.flush()
        file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Another process is already running this job") from None
        try:
            yield
        finally:
            file.seek(0)
            if os.name == "nt":
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file, fcntl.LOCK_UN)


def is_locked(path: Path):
    try:
        with exclusive(path):
            return False
    except RuntimeError:
        return True


class CancelSignal:
    def __init__(self, event, path):
        self.event, self.path = event, path

    def is_set(self):
        return self.event.is_set() or self.path.exists()

    def wait(self, timeout):
        import time
        end = time.monotonic() + timeout
        while not self.is_set():
            remaining = end - time.monotonic()
            if remaining <= 0:
                return False
            self.event.wait(min(.5, remaining))
        return True
