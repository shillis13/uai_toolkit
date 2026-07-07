#!/usr/bin/env python3
"""
gemini_memory_lock.py - Reference-counted lock for suppressing ~/.gemini/GEMINI.md

When multiple shard processes need to run without the global memory file
influencing their context, they acquire this lock. The file is hidden when
the first process acquires, restored when the last releases.

Usage:
    from gemini_memory_lock import GeminiMemoryLock
    
    with GeminiMemoryLock():
        # GEMINI.md is hidden during this block
        run_shard_init()
    
    # Or manual acquire/release:
    lock = GeminiMemoryLock()
    lock.acquire()
    try:
        run_shard_init()
    finally:
        lock.release()
"""

from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path


GEMINI_DIR = Path.home() / ".gemini"
MEMORY_FILE = GEMINI_DIR / "GEMINI.md"
BACKUP_FILE = GEMINI_DIR / "GEMINI.md.shard_suppressed"
LOCK_FILE = GEMINI_DIR / ".memory_lock"
COUNT_FILE = GEMINI_DIR / ".memory_lock_count"

# Timeout for acquiring the lock file itself
LOCK_TIMEOUT = 30


class GeminiMemoryLockError(Exception):
    """Error acquiring or releasing the memory lock."""
    pass


class GeminiMemoryLock:
    """
    Reference-counted lock for suppressing ~/.gemini/GEMINI.md.
    
    Thread/process safe via file locking. The memory file is renamed
    (hidden) when first acquired, restored when last released.
    """
    
    def __init__(self):
        self._lock_fd = None
    
    def __enter__(self):
        self.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False
    
    def _get_lock(self) -> int:
        """Acquire exclusive lock on the lock file. Returns file descriptor."""
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        fd = os.open(str(LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o644)
        
        start = time.time()
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                if time.time() - start > LOCK_TIMEOUT:
                    os.close(fd)
                    raise GeminiMemoryLockError(
                        f"Timeout waiting for memory lock after {LOCK_TIMEOUT}s"
                    )
                time.sleep(0.1)
    
    def _release_lock(self, fd: int) -> None:
        """Release the lock file."""
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    
    def _read_count(self) -> int:
        """Read current reference count."""
        try:
            return int(COUNT_FILE.read_text().strip())
        except (FileNotFoundError, ValueError):
            return 0
    
    def _write_count(self, count: int) -> None:
        """Write reference count."""
        COUNT_FILE.write_text(str(count))
    
    def acquire(self) -> None:
        """
        Acquire the lock. Increments reference count.
        On first acquisition (0→1), hides the memory file.
        """
        fd = self._get_lock()
        try:
            count = self._read_count()
            
            if count == 0:
                # First acquirer - hide the memory file
                if MEMORY_FILE.exists():
                    MEMORY_FILE.rename(BACKUP_FILE)
            
            self._write_count(count + 1)
        finally:
            self._release_lock(fd)
    
    def release(self) -> None:
        """
        Release the lock. Decrements reference count.
        On last release (1→0), restores the memory file.
        """
        fd = self._get_lock()
        try:
            count = self._read_count()
            
            if count <= 0:
                # Shouldn't happen, but be defensive
                self._write_count(0)
                return
            
            new_count = count - 1
            self._write_count(new_count)
            
            if new_count == 0:
                # Last releaser - restore the memory file
                if BACKUP_FILE.exists():
                    BACKUP_FILE.rename(MEMORY_FILE)
        finally:
            self._release_lock(fd)
    
    @classmethod
    def force_reset(cls) -> str:
        """
        Force reset the lock state. Use if processes crashed without releasing.
        Returns status message.
        """
        fd = None
        try:
            # Try to get lock with short timeout
            LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o644)
            
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return "ERROR: Lock held by another process. Cannot force reset."
            
            # Reset count
            COUNT_FILE.write_text("0")
            
            # Restore backup if exists
            if BACKUP_FILE.exists():
                if MEMORY_FILE.exists():
                    # Both exist - backup takes precedence (was the original)
                    MEMORY_FILE.unlink()
                BACKUP_FILE.rename(MEMORY_FILE)
                return "Reset complete. Restored GEMINI.md from backup."
            elif MEMORY_FILE.exists():
                return "Reset complete. GEMINI.md was already in place."
            else:
                return "Reset complete. No GEMINI.md found (neither original nor backup)."
        finally:
            if fd is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except:
                    pass
                os.close(fd)
    
    @classmethod
    def status(cls) -> dict:
        """Get current lock status."""
        count = 0
        try:
            count = int(COUNT_FILE.read_text().strip())
        except (FileNotFoundError, ValueError):
            pass
        
        return {
            "reference_count": count,
            "memory_file_exists": MEMORY_FILE.exists(),
            "backup_file_exists": BACKUP_FILE.exists(),
            "lock_file_exists": LOCK_FILE.exists(),
            "suppressed": count > 0,
        }


# CLI for manual testing/recovery
if __name__ == "__main__":
    import argparse
    import json
    
    parser = argparse.ArgumentParser(description="Manage Gemini memory file lock")
    parser.add_argument("command", choices=["status", "acquire", "release", "reset"],
                        help="Command to run")
    
    args = parser.parse_args()
    
    if args.command == "status":
        print(json.dumps(GeminiMemoryLock.status(), indent=2))
    
    elif args.command == "acquire":
        lock = GeminiMemoryLock()
        lock.acquire()
        print("Acquired. Current status:")
        print(json.dumps(GeminiMemoryLock.status(), indent=2))
    
    elif args.command == "release":
        lock = GeminiMemoryLock()
        lock.release()
        print("Released. Current status:")
        print(json.dumps(GeminiMemoryLock.status(), indent=2))
    
    elif args.command == "reset":
        result = GeminiMemoryLock.force_reset()
        print(result)
        print("Current status:")
        print(json.dumps(GeminiMemoryLock.status(), indent=2))
