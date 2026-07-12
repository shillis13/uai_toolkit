#!/usr/bin/env python3
"""
Memory Library — Business logic for slot-based memory operations.

Extracted from apps/mcps/memory/server.py to follow the
"thin wrapper around scripts" pattern.
"""

import os
import re
import sys
import yaml
from pathlib import Path
from datetime import datetime, timezone


# === Configuration ===
sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT

MEMORY_PATHS = {  # noqa: updated 2026-03-16 — moved to ai_memories/80_working_memory/
    "default": AI_ROOT / "ai_memories/80_working_memory",
    "working_memory": AI_ROOT / "ai_memories/80_working_memory",
}

DEFAULT_AI = "default"


# === Helper Functions ===

def get_memory_path(ai: str = None) -> Path:
    ai = ai or DEFAULT_AI
    return MEMORY_PATHS.get(ai, MEMORY_PATHS[DEFAULT_AI])


def parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    if ts_str.endswith('Z'):
        ts_str = ts_str[:-1] + '+00:00'
    return datetime.fromisoformat(ts_str)


def load_manifest(ai: str = None) -> dict:
    mem_path = get_memory_path(ai)
    manifest_file = mem_path / "manifest.yml"

    if not manifest_file.exists():
        return {"error": f"Manifest not found: {manifest_file}"}

    with open(manifest_file) as f:
        return yaml.safe_load(f) or {}


def save_manifest(manifest: dict, ai: str = None):
    mem_path = get_memory_path(ai)
    manifest_file = mem_path / "manifest.yml"

    with open(manifest_file, 'w') as f:
        yaml.dump(manifest, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def load_slot(slot: int, ai: str = None) -> tuple[list, dict]:
    """Load slot contents. Returns (observations list, full data dict)."""
    mem_path = get_memory_path(ai)
    slot_file = mem_path / f"{slot:02d}.yml"

    if not slot_file.exists():
        return [], {}

    try:
        with open(slot_file) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return [{"error": f"YAML parse error: {e}", "file": str(slot_file)}], {}

    if not data:
        return [], {}

    # Schema v1: structured with observations key
    if isinstance(data, dict) and 'observations' in data:
        return data.get('observations', []), data

    # Legacy: pure list format
    if isinstance(data, list):
        return data, {'observations': data}

    # Single entry (shouldn't happen but handle it)
    return [data], {'observations': [data]}


def save_slot(slot: int, observations: list, ai: str = None, full_data: dict = None):
    """Save observations to slot file, preserving reference section if present."""
    mem_path = get_memory_path(ai)
    slot_file = mem_path / f"{slot:02d}.yml"

    # If we have full structured data, update observations and preserve rest
    if full_data and isinstance(full_data, dict):
        full_data['observations'] = observations
        # Update metadata timestamp
        if 'metadata' in full_data:
            full_data['metadata']['last_updated'] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            full_data['metadata']['updated_by'] = 'Claude Desktop'
        with open(slot_file, 'w') as f:
            yaml.dump(full_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    else:
        # Legacy pure list format
        with open(slot_file, 'w') as f:
            yaml.dump(observations, f, default_flow_style=False, allow_unicode=True)


# === Core Operations ===

def op_read(slot: int, ai: str = None, limit: int = None,
            since: str = None, oldest_first: bool = False,
            include_reference: bool = False) -> dict:
    """Read slot with optional filters."""
    observations, full_data = load_slot(slot, ai)

    if not observations and not full_data:
        return {"slot": slot, "exists": False, "entries": [], "total": 0}

    # Filter by time if specified
    if since:
        since_dt = parse_timestamp(since)
        observations = [e for e in observations
                   if 'ts' in e and parse_timestamp(e['ts']) >= since_dt]

    # Sort order
    if oldest_first:
        filtered = observations  # Already chronological
    else:
        filtered = list(reversed(observations))  # Newest first

    # Apply limit
    total = len(filtered)
    if limit:
        filtered = filtered[:limit]

    result = {
        "slot": slot,
        "exists": True,
        "entries": filtered,
        "returned": len(filtered),
        "total": total
    }

    if include_reference and full_data.get('reference'):
        result['reference'] = full_data['reference']

    return result


def op_append(slot: int, content: str, ai: str = None) -> dict:
    """Append timestamped observation."""
    observations, full_data = load_slot(slot, ai)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {"ts": ts, "content": content}
    observations.append(entry)

    save_slot(slot, observations, ai, full_data if full_data else None)

    return {
        "success": True,
        "slot": slot,
        "entry": entry,
        "total_entries": len(observations)
    }


def op_update(slot: int, index: int, content: str, ai: str = None) -> dict:
    """Update entry at index (preserves original timestamp)."""
    observations, full_data = load_slot(slot, ai)

    if index < 0 or index >= len(observations):
        return {"success": False, "error": f"Index {index} out of range (0-{len(observations)-1})"}

    old_entry = observations[index]
    observations[index] = {"ts": old_entry.get("ts", "unknown"), "content": content}

    save_slot(slot, observations, ai, full_data if full_data else None)

    return {
        "success": True,
        "slot": slot,
        "index": index,
        "old": old_entry,
        "new": observations[index]
    }


def op_delete(slot: int, ai: str = None, index: int = None, before: str = None) -> dict:
    """Delete by index or by time (before date)."""
    observations, full_data = load_slot(slot, ai)
    original_count = len(observations)

    if index is not None:
        if index < 0 or index >= len(observations):
            return {"success": False, "error": f"Index {index} out of range"}
        deleted = observations.pop(index)
        save_slot(slot, observations, ai, full_data if full_data else None)
        return {
            "success": True,
            "slot": slot,
            "deleted": deleted,
            "remaining": len(observations)
        }

    if before:
        before_dt = parse_timestamp(before)
        kept = [e for e in observations
                if 'ts' not in e or parse_timestamp(e['ts']) >= before_dt]
        deleted_count = original_count - len(kept)
        save_slot(slot, kept, ai, full_data if full_data else None)
        return {
            "success": True,
            "slot": slot,
            "deleted_count": deleted_count,
            "remaining": len(kept)
        }

    return {"success": False, "error": "Must specify index or before"}


def op_search(query: str, ai: str = None, slots: list = None,
              regex: bool = False, since: str = None,
              content_only: bool = True) -> dict:
    """Search across slots."""
    mem_path = get_memory_path(ai)

    # Determine slots to search
    if slots:
        slot_nums = slots
    else:
        slot_nums = [int(f.stem) for f in mem_path.glob("*.yml")
                     if f.stem.isdigit()]

    # Compile pattern
    if regex:
        pattern = re.compile(query, re.IGNORECASE)
        match_fn = lambda s: pattern.search(s)
    else:
        query_lower = query.lower()
        match_fn = lambda s: query_lower in s.lower()

    # Time filter
    since_dt = parse_timestamp(since) if since else None

    results = []
    for slot in sorted(slot_nums):
        entries, _ = load_slot(slot, ai)

        for i, entry in enumerate(entries):
            # Time filter
            if since_dt and 'ts' in entry:
                if parse_timestamp(entry['ts']) < since_dt:
                    continue

            # Content matching
            if content_only:
                search_text = str(entry.get('content', ''))
            else:
                search_text = str(entry)

            if match_fn(search_text):
                results.append({"slot": slot, "index": i, "entry": entry})

    return {"query": query, "regex": regex, "matches": len(results), "results": results}


def op_set_slot_config(slot: int, ai: str = None, name: str = None,
                       purpose: str = None, load: str = None,
                       tags: list = None) -> dict:
    """Update or create slot definition in manifest."""
    manifest = load_manifest(ai)

    if "error" in manifest:
        return manifest

    if "slot_structure" not in manifest:
        manifest["slot_structure"] = {}

    slot_key = str(slot)

    # Get existing or create new
    if slot_key in manifest["slot_structure"]:
        config = manifest["slot_structure"][slot_key]
    else:
        config = {}

    # Update provided fields
    if name is not None:
        config["name"] = name
    if purpose is not None:
        config["purpose"] = purpose
    if load is not None:
        config["load"] = load
    if tags is not None:
        config["tags"] = tags

    manifest["slot_structure"][slot_key] = config
    save_manifest(manifest, ai)

    return {
        "success": True,
        "slot": slot,
        "config": config
    }


def op_stats(ai: str = None) -> dict:
    """Get stats for all slots."""
    mem_path = get_memory_path(ai)
    manifest = load_manifest(ai)
    slot_structure = manifest.get("slot_structure", manifest.get("slots", {}))

    stats = []
    for slot_file in sorted(mem_path.glob("*.yml")):
        if not slot_file.stem.isdigit():
            continue

        slot_num = int(slot_file.stem)
        entries, _ = load_slot(slot_num, ai)

        # Get slot name from manifest (support both old slot_structure and new slots keys)
        slot_config = slot_structure.get(str(slot_num), {})

        # Find latest timestamp
        latest_ts = None
        if entries:
            for e in reversed(entries):
                if 'ts' in e:
                    latest_ts = e['ts']
                    break

        stats.append({
            "slot": slot_num,
            "name": slot_config.get("name", "unnamed"),
            "entries": len(entries),
            "size_bytes": slot_file.stat().st_size,
            "last_updated": latest_ts
        })

    return {
        "ai": ai or DEFAULT_AI,
        "slot_count": len(stats),
        "slots": stats,
        "total_entries": sum(s["entries"] for s in stats),
        "total_bytes": sum(s["size_bytes"] for s in stats)
    }


def op_get_manifest(ai: str = None) -> dict:
    """Get manifest with slot structure formatted for tool response."""
    manifest = load_manifest(ai)
    slot_structure = manifest.get("slot_structure", manifest.get("slots", {}))
    return {
        "ai": ai or DEFAULT_AI,
        "manifest_path": str(get_memory_path(ai) / "manifest.yml"),
        "slots": {
            int(k): {
                "name": v.get("name"),
                "purpose": v.get("purpose"),
                "load": v.get("load"),
                "tags": v.get("tags", [])
            }
            for k, v in slot_structure.items()
        }
    }


def op_test() -> dict:
    """Test server connectivity."""
    return {
        "server": "memory",
        "status": "ok",
        "memory_paths": {k: str(v) for k, v in MEMORY_PATHS.items()},
        "default_ai": DEFAULT_AI
    }
