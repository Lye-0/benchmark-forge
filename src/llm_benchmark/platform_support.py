"""Host platform operations. These are not an untrusted-code sandbox."""

import os
import signal
import sys
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO

import psutil


def acquire_lock(path: Path) -> BinaryIO:
    file = path.open("a+b")
    try:
        if sys.platform == "win32":
            import msvcrt

            if path.stat().st_size == 0:
                file.write(b"\0")
                file.flush()
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        file.close()
        raise
    return file


def release_lock(file: BinaryIO) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(file, fcntl.LOCK_UN)
    finally:
        file.close()


def worker_environment() -> dict[str, str]:
    env = {
        "PATH": os.defpath,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "TOKENIZERS_PARALLELISM": "false",
    }
    if sys.platform == "win32":
        # DLL loading and temporary storage require these; never inherit credentials or PYTHONPATH.
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
            value = os.environ.get(name)
            if value:
                env[name] = value
        root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        env["PATH"] = str(Path(root) / "System32") + os.pathsep + root
    return env


def peak_ram() -> tuple[int | None, str]:
    if sys.platform == "win32":
        value = getattr(psutil.Process().memory_info(), "peak_wset", None)
        return value, "worker lifetime peak working set (Windows)"
    if sys.platform == "linux":
        import resource

        return resource.getrusage(
            resource.RUSAGE_SELF
        ).ru_maxrss * 1024, "worker lifetime high-water RSS (Linux)"
    return None, "peak RAM unavailable on this platform"


def terminate_worker(proc, job=None):
    if sys.platform == "win32":
        try:
            if job is not None:
                job.close()
        finally:
            if proc.returncode is None:
                with suppress(ProcessLookupError):
                    proc.kill()
    else:
        with suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
