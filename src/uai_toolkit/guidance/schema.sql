-- context_files_registry.db schema
-- Generated, NOT tracked in git. This file IS tracked.
-- Location: ai_general/data/context_files/context_files_registry.db

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- Registry metadata
CREATE TABLE IF NOT EXISTS registry_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Logical content items (one per context_file, role, skill, profile, etc.)
CREATE TABLE IF NOT EXISTS content_items (
    id TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,          -- context_file|role|skill|profile|global|platform
    category TEXT,                    -- perspective|knowledge|processes|procedures|methods|templates|reminders
    subcategory TEXT,                 -- 10_architecture, 30_protocols, etc.
    composition_type TEXT,            -- for compositions: role|skill|profile|global|platform
    name TEXT NOT NULL,
    status TEXT DEFAULT 'active',     -- active|draft|deprecated|retired
    version TEXT,
    description TEXT,
    created DATE,
    updated DATE,
    scanned_at DATETIME NOT NULL
);

-- Physical file variants for each content item
CREATE TABLE IF NOT EXISTS content_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    variant TEXT NOT NULL,            -- source_md|source_yml|condensed_yml|generated
    is_preferred INTEGER DEFAULT 0,
    content_hash TEXT,
    token_estimate INTEGER,
    file_size INTEGER,
    symlink_target TEXT,
    scanned_at DATETIME NOT NULL,
    FOREIGN KEY (item_id) REFERENCES content_items(id) ON DELETE CASCADE
);

-- Cross-references between items
CREATE TABLE IF NOT EXISTS content_references (
    source_id TEXT NOT NULL,
    target_id TEXT,
    target_path TEXT,
    target_type TEXT NOT NULL,        -- item|mcp|script|tool|external
    target_name TEXT,
    UNIQUE(source_id, target_path),
    FOREIGN KEY (source_id) REFERENCES content_items(id) ON DELETE CASCADE
);

-- Nature tags junction table
CREATE TABLE IF NOT EXISTS item_natures (
    item_id TEXT NOT NULL,
    nature TEXT NOT NULL,
    PRIMARY KEY (item_id, nature),
    FOREIGN KEY (item_id) REFERENCES content_items(id) ON DELETE CASCADE
);

-- Aliases for lookup
CREATE TABLE IF NOT EXISTS item_aliases (
    item_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    alias_type TEXT DEFAULT 'name',   -- name|legacy_topic|abbreviation
    PRIMARY KEY (alias, alias_type),
    FOREIGN KEY (item_id) REFERENCES content_items(id) ON DELETE CASCADE
);

-- MCP server inventory
CREATE TABLE IF NOT EXISTS mcps (
    name TEXT PRIMARY KEY,
    description TEXT,
    tool_count INTEGER,
    server_path TEXT,
    scanned_at DATETIME NOT NULL
);

-- MCP tool detail
CREATE TABLE IF NOT EXISTS mcp_tools (
    mcp_name TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    description TEXT,
    PRIMARY KEY (mcp_name, tool_name),
    FOREIGN KEY (mcp_name) REFERENCES mcps(name) ON DELETE CASCADE
);

-- Scan audit log
CREATE TABLE IF NOT EXISTS scan_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    mode TEXT NOT NULL,
    files_scanned INTEGER,
    items_added INTEGER,
    items_updated INTEGER,
    items_removed INTEGER,
    errors TEXT
);

-- Scan errors
CREATE TABLE IF NOT EXISTS scan_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER,
    path TEXT,
    phase TEXT,
    error_type TEXT,
    message TEXT,
    FOREIGN KEY (scan_id) REFERENCES scan_log(id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_items_type ON content_items(item_type);
CREATE INDEX IF NOT EXISTS idx_items_category ON content_items(category);
CREATE INDEX IF NOT EXISTS idx_items_status ON content_items(status);
CREATE INDEX IF NOT EXISTS idx_items_name ON content_items(name);
CREATE INDEX IF NOT EXISTS idx_files_item ON content_files(item_id);
CREATE INDEX IF NOT EXISTS idx_files_variant ON content_files(variant);
CREATE INDEX IF NOT EXISTS idx_refs_source ON content_references(source_id);
CREATE INDEX IF NOT EXISTS idx_refs_target ON content_references(target_id);
CREATE INDEX IF NOT EXISTS idx_refs_target_type ON content_references(target_type);
CREATE INDEX IF NOT EXISTS idx_natures ON item_natures(nature);
CREATE INDEX IF NOT EXISTS idx_aliases ON item_aliases(alias);

-- FTS5 for natural language search
CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
    item_id, name, description, category
);

-- Convenience views
CREATE VIEW IF NOT EXISTS context_files AS
    SELECT * FROM content_items WHERE item_type = 'context_file';

CREATE VIEW IF NOT EXISTS compositions AS
    SELECT * FROM content_items WHERE item_type != 'context_file';

CREATE VIEW IF NOT EXISTS preferred_files AS
    SELECT * FROM content_files WHERE is_preferred = 1;
