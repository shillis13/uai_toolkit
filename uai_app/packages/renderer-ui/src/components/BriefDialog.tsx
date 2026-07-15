/**
 * BriefDialog — modal for creating a brief from one or more sessions.
 *
 * Ported from UCI BriefDialog.tsx. Uses createPortal to render as overlay.
 * Fields: brief name, description, condenser session selector, folder,
 * "launch after create" checkbox with platform picker.
 */

import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import type { Session } from '@uai/shared/types';

// ── Types ────────────────────────────────────────────────────────────────────

export interface CreateBriefOpts {
  name: string;
  description?: string;
  folder: string;
  launch?: boolean;
  launchName?: string;
  launchPlatform?: string;
  condenserSession?: string;
  hostSession?: string;   // NEW model (todo_0506): the session that spawns the briefing subagent
}

interface BriefDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (opts: CreateBriefOpts) => void;
  sourceSessions: Session[];
  existingNames: string[];
  folders: string[];
  preCheckLaunch?: boolean;
  // Host picker (todo_0506): who spawns the briefing subagent.
  hostCandidates?: Session[];       // all RUNNING sessions (universe when filter is off)
  condenserHostIds?: Set<string>;   // tracking_ids that are condenser-tagged OR in a *condenser* folder
}

// ── Helpers ──────────────────────────────────────────────────────────────────

// Launchable platforms (Gemini retired — no longer a current tool).
const PLATFORMS = ['claude_cli', 'codex_cli'] as const;
// Display maps keep gemini_cli so any historical Gemini session still renders.
const PLATFORM_LABELS: Record<string, string> = {
  claude_cli: 'Claude',
  codex_cli: 'Codex',
  gemini_cli: 'Gemini',
};
// Canonical session glyphs/colors (match Navigator + RecipientPicker).
const PLATFORM_ICONS: Record<string, string> = {
  claude_cli: '●', codex_cli: '■', gemini_cli: '◆',
};
const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)', codex_cli: 'var(--accent-purple)', gemini_cli: 'var(--accent-cyan)',
};

/** "last active 5m ago" style relative label from an ISO timestamp. */
function formatIdleAgo(isoStr: string | null | undefined): string {
  if (!isoStr) return 'idle time unknown';
  const then = new Date(isoStr).getTime();
  if (Number.isNaN(then)) return 'idle time unknown';
  const diffMs = Date.now() - then;
  if (diffMs < 60000) return 'active just now';
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 60) return `last active ${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `last active ${hours}h ago`;
  return `last active ${Math.floor(hours / 24)}d ago`;
}

/** Suggest a non-conflicting brief name by appending _01, _02, etc. */
function suggestBriefName(baseName: string, existingNames: string[]): string {
  if (!existingNames.includes(baseName)) return baseName;
  for (let i = 1; i <= 99; i++) {
    const candidate = `${baseName}_${String(i).padStart(2, '0')}`;
    if (!existingNames.includes(candidate)) return candidate;
  }
  return `${baseName}_${Date.now()}`;
}

// ── Component ────────────────────────────────────────────────────────────────

const BriefDialog: React.FC<BriefDialogProps> = ({
  isOpen,
  onClose,
  onConfirm,
  sourceSessions,
  existingNames,
  folders,
  preCheckLaunch = false,
  hostCandidates = [],
  condenserHostIds = new Set<string>(),
}) => {
  const isMulti = sourceSessions.length > 1;
  const primarySession = sourceSessions[0];
  // The brief target = the primary source session. Its own session is the
  // default host when it's running (self-brief); otherwise no default.
  const targetId = primarySession?.tracking_id ?? '';
  const targetRunning = primarySession?.process_status === 'running';
  const defaultName = isMulti
    ? `combined_${sourceSessions.length}_sessions`
    : (primarySession?.display_name ?? '');

  const [name, setName] = useState(defaultName);
  const [description, setDescription] = useState('');
  const [folder, setFolder] = useState(folders[0] ?? '');
  // Host picker (todo_0506): default = target if running, else unset.
  const [onlyCondenser, setOnlyCondenser] = useState(true);
  const [selectedHost, setSelectedHost] = useState(targetRunning ? targetId : '');
  const [newFolderMode, setNewFolderMode] = useState(false);
  const [newFolderValue, setNewFolderValue] = useState('');
  const [launch, setLaunch] = useState(preCheckLaunch);
  const [launchName, setLaunchName] = useState('');
  const [launchPlatform, setLaunchPlatform] = useState<string>('claude_cli');

  // Reset state only when dialog first opens (not on every re-render)
  const [prevOpen, setPrevOpen] = useState(false);
  if (isOpen && !prevOpen) {
    setPrevOpen(true);
    setName(isMulti ? `combined_${sourceSessions.length}_sessions` : (primarySession?.display_name ?? ''));
    setDescription('');
    setFolder(folders[0] ?? '');
    setOnlyCondenser(true);
    setSelectedHost(targetRunning ? targetId : '');
    setNewFolderMode(false);
    setNewFolderValue('');
    setLaunch(preCheckLaunch);
    setLaunchName('');
    setLaunchPlatform('claude_cli');
  } else if (!isOpen && prevOpen) {
    setPrevOpen(false);
  }

  // Host list: running sessions, filtered to condenser-tagged/foldered when the
  // checkbox is on. The target itself is ALWAYS listed when running (it's the
  // default self-brief host), even if it wouldn't pass the condenser filter.
  const visibleHosts = hostCandidates.filter(s => {
    if (s.tracking_id === targetId && targetRunning) return true;
    if (onlyCondenser) return condenserHostIds.has(s.tracking_id);
    return true;
  });

  // Keep launchName in sync with name field when user hasn't manually edited it
  const defaultLaunchName = `${name} v2`;
  const effectiveLaunchName = launchName || defaultLaunchName;

  const nameConflict = existingNames.includes(name);
  const suggestedName = nameConflict ? suggestBriefName(name, existingNames) : null;

  const effectiveFolder = newFolderMode ? newFolderValue : folder;

  const handleConfirm = () => {
    onConfirm({
      name,
      description: description || undefined,
      folder: effectiveFolder,
      launch: launch || undefined,
      launchName: launch ? effectiveLaunchName : undefined,
      launchPlatform: launch ? launchPlatform : undefined,
      hostSession: selectedHost || undefined,
    });
  };

  const confirmDisabled = !selectedHost;

  const handleOverlayMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  if (!isOpen) return null;

  return createPortal(
    <div className="brief-dialog-overlay" onMouseDown={handleOverlayMouseDown}>
      <div className="brief-dialog" onClick={(e) => e.stopPropagation()} onMouseDown={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="brief-dialog-header">
          <h3>Create Brief</h3>
          <div className="subtitle">
            {isMulti
              ? `from ${sourceSessions.length} sessions: ${sourceSessions.map(s => s.display_name ?? s.tracking_id).join(', ')}`
              : `from: ${primarySession?.display_name ?? ''}`}
          </div>
        </div>

        {/* Body */}
        <div className="brief-dialog-body">
          {/* Name field */}
          <div className="field-group">
            <label>Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
            {nameConflict && (
              <div className="name-conflict">
                "{name}" already exists.
                {suggestedName && (
                  <> Suggested: <span
                    style={{ cursor: 'pointer', textDecoration: 'underline' }}
                    onClick={() => setName(suggestedName)}
                  >{suggestedName}</span></>
                )}
              </div>
            )}
          </div>

          {/* Description field */}
          <div className="field-group">
            <label>Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Leave blank — the briefing subagent will generate"
              className="auto-gen-hint"
            />
          </div>

          {/* Folder field */}
          <div className="field-group">
            <label>Folder</label>
            {newFolderMode ? (
              <div className="folder-row">
                <input
                  type="text"
                  value={newFolderValue}
                  onChange={(e) => setNewFolderValue(e.target.value)}
                  placeholder="New folder name"
                  style={{ flex: 1 }}
                />
                <button
                  className="folder-new-btn"
                  onClick={() => setNewFolderMode(false)}
                >
                  Back
                </button>
              </div>
            ) : (
              <div className="folder-row">
                <select value={folder} onChange={(e) => setFolder(e.target.value)}>
                  {folders.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
                <button
                  className="folder-new-btn"
                  onClick={() => setNewFolderMode(true)}
                >
                  + New
                </button>
              </div>
            )}
          </div>

          {/* Condenser session picker (todo_0506): who spawns the briefing subagent */}
          <div className="field-group">
            <label>
              Condenser session <span style={{ color: 'var(--text-muted)', fontWeight: 'normal' }}>— the session that writes the brief</span>
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', margin: '0 0 8px', fontSize: '11px', color: 'var(--text-muted)', cursor: 'pointer' }}>
              <input type="checkbox" checked={onlyCondenser} onChange={(e) => setOnlyCondenser(e.target.checked)} style={{ margin: 0 }} />
              Only show condenser-tagged sessions
            </label>
            <div className="brief-host-list" role="radiogroup" aria-label="Condenser session">
              {visibleHosts.length === 0 && (
                <div className="brief-host-empty">
                  {onlyCondenser
                    ? 'No running condenser-tagged sessions. Uncheck the filter to pick any running session.'
                    : 'No running sessions available to condense the brief.'}
                </div>
              )}
              {visibleHosts.map(s => {
                const selected = selectedHost === s.tracking_id;
                const isSelf = s.tracking_id === targetId;
                const glyph = PLATFORM_ICONS[s.platform] ?? '○';
                const glyphColor = PLATFORM_COLORS[s.platform] ?? 'var(--text-muted)';
                const ctx = s.context_percent != null ? `${Math.round(s.context_percent)}%` : '—';
                const idle = s.activity_state === 'idle' ? 'idle now' : formatIdleAgo(s.last_activity);
                return (
                  <button
                    key={s.tracking_id}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    className={`brief-host-row${selected ? ' selected' : ''}`}
                    onClick={() => setSelectedHost(s.tracking_id)}
                  >
                    <span className="brief-host-glyph" style={{ color: glyphColor }} title={PLATFORM_LABELS[s.platform] ?? s.platform}>{glyph}</span>
                    <span className="brief-host-name">
                      {s.display_name ?? s.tracking_id}
                      {isSelf && <span className="brief-host-self">this session</span>}
                    </span>
                    <span className="brief-host-ctx" title="context used">{ctx}</span>
                    <span className="brief-host-idle">{idle}</span>
                  </button>
                );
              })}
            </div>
            {!targetRunning && (
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic', marginTop: '6px' }}>
                Target isn't running — pick a condenser to brief it from its saved transcript.
              </div>
            )}
          </div>

          <div className="brief-dialog-divider" />

          {/* Launch checkbox */}
          <label className="launch-checkbox">
            <input
              type="checkbox"
              checked={launch}
              onChange={(e) => setLaunch(e.target.checked)}
            />
            <span>Launch new session from Brief</span>
          </label>

          {/* Launch options */}
          {launch && (
            <div className="launch-options">
              <div className="field-group">
                <label>Session name</label>
                <input
                  type="text"
                  value={launchName}
                  onChange={(e) => setLaunchName(e.target.value)}
                  placeholder={defaultLaunchName}
                />
              </div>
              <div className="field-group">
                <label>Platform</label>
                <select
                  value={launchPlatform}
                  onChange={(e) => setLaunchPlatform(e.target.value)}
                >
                  {PLATFORMS.map((p) => (
                    <option key={p} value={p}>{PLATFORM_LABELS[p] ?? p}</option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="brief-dialog-footer">
          <button className="cancel-btn" onClick={onClose}>Cancel</button>
          <button className="confirm-btn" onClick={handleConfirm} disabled={confirmDisabled} title={confirmDisabled ? 'Pick a condenser session first' : undefined}>Create Brief</button>
        </div>
      </div>
    </div>,
    document.body
  );
};

export default BriefDialog;
