"""Verify the SQLite tracker: functional semantics + concurrency safety.

Run directly:  python tests/test_tracker_concurrency.py
Uses an isolated temp AI_ROOT, so it never touches real tracking data.
"""
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor


def _set_root(root: str):
    """Point this (possibly spawned) process at the shared AI_ROOT."""
    os.environ["AI_ROOT"] = root
    from ai_toolkit import paths
    paths.ai_root.cache_clear()
    paths.config.cache_clear()


def _worker(args):
    root, session, file_path, n = args
    _set_root(root)  # spawn-safe: every worker targets the SAME db
    from ai_toolkit.file_access import tracker
    for _ in range(n):
        tracker.log_write(session, file_path)
    return n


def main() -> int:
    root = tempfile.mkdtemp(prefix="fa_test_")
    _set_root(root)
    from ai_toolkit.file_access import tracker
    import sqlite3

    target = os.path.join(root, "some_file.py")
    open(target, "w").close()
    canon = tracker._canonical(target)
    ok = True

    # --- functional: conflict detection ---
    tracker.log_read("A", target)
    time.sleep(0.01)
    tracker.log_write("B", target)
    time.sleep(0.01)
    c = tracker.check_conflict("A", target)
    assert c is not None and c.conflicting_session == "B", f"expected B conflict, got {c}"
    print(f"  ✅ conflict detected: A's read clobbered by {c.conflicting_session}")

    tracker.log_read("A", target)  # A re-reads -> now current
    time.sleep(0.01)
    assert tracker.check_conflict("A", target) is None, "re-read should clear conflict"
    print("  ✅ re-read clears the conflict")

    # --- concurrency: 8 procs x 250 writes, zero losses ---
    NPROC, NWRITES = 8, 250
    expected = NPROC * NWRITES
    with ProcessPoolExecutor(max_workers=NPROC) as ex:
        list(ex.map(_worker, [(root, f"S{i}", target, NWRITES) for i in range(NPROC)]))

    db = tracker._db_path()
    conn = sqlite3.connect(str(db))
    got = conn.execute(
        "SELECT COUNT(*) FROM access_state WHERE op='write' AND file=?", (canon,)
    ).fetchone()[0]
    conn.close()
    # +1 for B's earlier write
    if got == expected + 1:
        print(f"  ✅ concurrency: {got} writes recorded, 0 lost ({NPROC} procs x {NWRITES})")
    else:
        ok = False
        print(f"  ❌ concurrency: expected {expected + 1}, got {got} — LOST WRITES")

    # --- prune is atomic & leaves a valid db ---
    tracker.prune(max_age_hours=48)
    conn = sqlite3.connect(str(db))
    integ = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()
    assert integ == "ok", f"integrity check failed: {integ}"
    print(f"  ✅ prune ran; db integrity: {integ}")

    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
