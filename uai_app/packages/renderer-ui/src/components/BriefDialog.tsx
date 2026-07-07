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
}

interface BriefDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (opts: CreateBriefOpts) => void;
  sourceSessions: Session[];
  existingNames: string[];
  folders: string[];
  preCheckLaunch?: boolean;
  condenserSessions?: Session[];  // active sessions tagged 'condenser'
  allSessions?: Session[];        // all sessions (for "Show Stopped" toggle)
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const PLATFORMS = ['claude_cli', 'codex_cli', 'gemini_cli'] as const;
const PLATFORM_LABELS: Record<string, string> = {
  claude_cli: 'Claude',
  codex_cli: 'Codex',
  gemini_cli: 'Gemini',
};

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
  condenserSessions = [],
  allSessions = [],
}) => {
  const [showStopped, setShowStopped] = useState(false);

  // Condenser list: active tagged 'condenser' by default, optionally include stopped
  const visibleCondensers = showStopped
    ? [...condenserSessions, ...allSessions.filter(s => s.process_status !== 'running' && s.tags.includes('condenser'))]
    : condenserSessions;
  const isMulti = sourceSessions.length > 1;
  const primarySession = sourceSessions[0];
  const defaultName = isMulti
    ? `combined_${sourceSessions.length}_sessions`
    : (primarySession?.display_name ?? '');

  const [name, setName] = useState(defaultName);
  const [description, setDescription] = useState('');
  const [folder, setFolder] = useState(folders[0] ?? '');
  const [selectedCondenser, setSelectedCondenser] = useState('');
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
    setNewFolderMode(false);
    setNewFolderValue('');
    setLaunch(preCheckLaunch);
    setLaunchName('');
    setLaunchPlatform('claude_cli');
  } else if (!isOpen && prevOpen) {
    setPrevOpen(false);
  }

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
      condenserSession: selectedCondenser || undefined,
    });
  };

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
              placeholder="Leave blank — Condenser will generate"
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

          {/* Condenser session */}
          <div className="field-group">
            <label>
              Condenser <span style={{ color: 'var(--text-muted)', fontWeight: 'normal' }}>(optional)</span>
            </label>
            <select value={selectedCondenser} onChange={(e) => setSelectedCondenser(e.target.value)}>
              <option value="">Auto (oldest available)</option>
              {visibleCondensers.map(s => (
                <option key={s.tracking_id} value={s.tracking_id}>
                  {s.display_name ?? s.tracking_id} {s.process_status !== 'running' ? '(stopped)' : ''}
                </option>
              ))}
            </select>
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px', fontSize: '11px', color: 'var(--text-muted)', cursor: 'pointer' }}>
              <input type="checkbox" checked={showStopped} onChange={(e) => setShowStopped(e.target.checked)} style={{ margin: 0 }} />
              Show Stopped Sessions
            </label>
            {visibleCondensers.length === 0 && (
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic', marginTop: '4px' }}>
                No sessions tagged "condenser". Tag a running session to use it here.
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
          <button className="confirm-btn" onClick={handleConfirm}>Create Brief</button>
        </div>
      </div>
    </div>,
    document.body
  );
};

export default BriefDialog;
