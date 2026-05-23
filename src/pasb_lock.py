"""Exclusive-write lock for PASB runners.

Prevents duplicate writes when a keeper races against the original worker.
Call `acquire(out_path)` once at process start; the returned fd must stay
alive for the lifetime of the process.

A second process that tries the same lock gets BlockingIOError and exits
cleanly (rc=0), so keepers never accumulate redundant writers.
"""
import fcntl
import os
import sys


def acquire(out_path):
    """Acquire exclusive flock on f'{out_path}.lock'. Returns the held fd.

    On contention, prints a notice and sys.exit(0) — keeper retry loops
    then idle while the surviving worker continues.
    """
    lock_path = str(out_path) + ".lock"
    fd = open(lock_path, "a+")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[pasb_lock] another worker holds {lock_path}; exit clean", flush=True)
        sys.exit(0)
    fd.write(f"{os.getpid()}\n")
    fd.flush()
    return fd
