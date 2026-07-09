#!/usr/bin/env python3
"""
gemini_mcp_lock.py - Reference-counted lock for suppressing MCP servers in Gemini.

When shard processes need to run without MCP servers (to prevent tool usage
and avoid initialization delays), they acquire this lock. The mcpServers
config is cleared when the first process acquires, restored when the last releases.

Usage:
    from uai_toolkit.cli.gemini_mcp_lock import GeminiMCPLock
    
    with GeminiMCPLock():
        # MCP servers are disabled during this block
        run_shard_query()
    
    # Or manual acquire/release:
    lock = GeminiMCPLock()
    lock.acquire()
    try:
        run_shard_query()
    finally:
        lock.release()
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path


GEMINI_DIR = Path.home() / ".gemini"
SETTINGS_FILE = GEMINI_DIR / "settings.json"
BACKUP_FILE = GEMINI_DIR / "settings.json.mcp_backup"
LOCK_FILE = GEMINI_DIR / ".mcp_lock"
COUNT_FILE = GEMINI_DIR / ".mcp_lock_count"

# Project-level config (ai_root)
AI_ROOT = Path.home() / "AI/ai_root"
PROJECT_GEMINI_DIR = AI_ROOT / ".gemini"
PROJECT_BACKUP_DIR = AI_ROOT / ".gemini.mcp_suppressed"

# Timeout for acquiring the lock file itself
LOCK_TIMEOUT = 30


class GeminiMCPLockError(Exception):
    """Error acquiring or releasing the MCP lock."""
    pass


class GeminiMCPLock:
    """
    Reference-counted lock for suppressing MCP servers in Gemini.
    
    Thread/process safe via file locking. The mcpServers config is
    backed up and cleared when first acquired, restored when last released.
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
                    raise GeminiMCPLockError(
                        f"Timeout waiting for MCP lock after {LOCK_TIMEOUT}s"
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
        On first acquisition (0→1), backs up and clears mcpServers.
        Also renames project-level .gemini directory to suppress it.
        """
        fd = self._get_lock()
        try:
            count = self._read_count()
            
            if count == 0:
                # First acquirer - backup and clear MCP servers (global)
                if SETTINGS_FILE.exists():
                    settings = json.loads(SETTINGS_FILE.read_text())
                    
                    # Backup just the mcpServers section
                    mcp_servers = settings.get("mcpServers", {})
                    BACKUP_FILE.write_text(json.dumps(mcp_servers, indent=2))
                    
                    # Clear mcpServers in settings
                    settings["mcpServers"] = {}
                    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))
                
                # Also suppress project-level .gemini directory
                if PROJECT_GEMINI_DIR.exists() and not PROJECT_BACKUP_DIR.exists():
                    PROJECT_GEMINI_DIR.rename(PROJECT_BACKUP_DIR)
            
            self._write_count(count + 1)
        finally:
            self._release_lock(fd)
    
    def release(self) -> None:
        """
        Release the lock. Decrements reference count.
        On last release (1→0), restores mcpServers from backup.
        Also restores project-level .gemini directory.
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
                # Last releaser - restore MCP servers (global)
                if BACKUP_FILE.exists() and SETTINGS_FILE.exists():
                    settings = json.loads(SETTINGS_FILE.read_text())
                    mcp_servers = json.loads(BACKUP_FILE.read_text())
                    
                    settings["mcpServers"] = mcp_servers
                    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))
                    
                    # Clean up backup
                    BACKUP_FILE.unlink()
                
                # Restore project-level .gemini directory
                if PROJECT_BACKUP_DIR.exists() and not PROJECT_GEMINI_DIR.exists():
                    PROJECT_BACKUP_DIR.rename(PROJECT_GEMINI_DIR)
        finally:
            self._release_lock(fd)
    
    @classmethod
    def force_reset(cls) -> str:
        """
        Force reset the lock state. Use if processes crashed without releasing.
        Returns status message.
        """
        fd = None
        messages = []
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
            
            # Restore global backup if exists
            if BACKUP_FILE.exists() and SETTINGS_FILE.exists():
                settings = json.loads(SETTINGS_FILE.read_text())
                mcp_servers = json.loads(BACKUP_FILE.read_text())
                
                settings["mcpServers"] = mcp_servers
                SETTINGS_FILE.write_text(json.dumps(settings, indent=2))
                BACKUP_FILE.unlink()
                
                messages.append(f"Restored {len(mcp_servers)} global MCP servers.")
            elif BACKUP_FILE.exists():
                BACKUP_FILE.unlink()
                messages.append("Removed orphaned global backup.")
            
            # Restore project directory if suppressed
            if PROJECT_BACKUP_DIR.exists() and not PROJECT_GEMINI_DIR.exists():
                PROJECT_BACKUP_DIR.rename(PROJECT_GEMINI_DIR)
                messages.append("Restored project .gemini directory.")
            elif PROJECT_BACKUP_DIR.exists() and PROJECT_GEMINI_DIR.exists():
                # Both exist - remove backup
                import shutil
                shutil.rmtree(PROJECT_BACKUP_DIR)
                messages.append("Removed orphaned project backup (original exists).")
            
            return "Reset complete. " + " ".join(messages) if messages else "Reset complete. Nothing to restore."
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
        
        mcp_count = 0
        if SETTINGS_FILE.exists():
            try:
                settings = json.loads(SETTINGS_FILE.read_text())
                mcp_count = len(settings.get("mcpServers", {}))
            except:
                pass
        
        backup_count = 0
        if BACKUP_FILE.exists():
            try:
                backup = json.loads(BACKUP_FILE.read_text())
                backup_count = len(backup)
            except:
                pass
        
        return {
            "reference_count": count,
            "active_mcp_servers": mcp_count,
            "backed_up_mcp_servers": backup_count,
            "suppressed": count > 0,
        }


# CLI for manual testing/recovery
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Manage Gemini MCP server lock")
    parser.add_argument("command", choices=["status", "acquire", "release", "reset"],
                        help="Command to run")
    
    args = parser.parse_args()
    
    if args.command == "status":
        print(json.dumps(GeminiMCPLock.status(), indent=2))
    
    elif args.command == "acquire":
        lock = GeminiMCPLock()
        lock.acquire()
        print("Acquired. Current status:")
        print(json.dumps(GeminiMCPLock.status(), indent=2))
    
    elif args.command == "release":
        lock = GeminiMCPLock()
        lock.release()
        print("Released. Current status:")
        print(json.dumps(GeminiMCPLock.status(), indent=2))
    
    elif args.command == "reset":
        result = GeminiMCPLock.force_reset()
        print(result)
        print("Current status:")
        print(json.dumps(GeminiMCPLock.status(), indent=2))
