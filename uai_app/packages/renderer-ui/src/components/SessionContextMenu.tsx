/**
 * SessionContextMenu — THE single context menu for session entities.
 *
 * Used by both Workspace (tab right-click) and Navigator (card right-click).
 * Same entity = same menu, everywhere.
 *
 * Ported directly from UCI TabBar.tsx session context menu (lines 736-858).
 * This is the authoritative structure — do not modify without explicit approval.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useSessionStore, useCardStore } from '../stores';
import { useFolderStore } from '../stores/folder-store';
import { useToast } from './Toast';
import { useViewport } from '../viewport';
import { useContextMenuDismiss } from '../hooks/use-context-menu-dismiss';
import { executeCommand } from '../utils/execute-command';
import type { Session } from '@uai/shared/types';
import BriefDialog from './BriefDialog';
import type { CreateBriefOpts } from './BriefDialog';
import ResumeCustomDialog from './ResumeCustomDialog';
import type { ResumeCustomOpts } from './ResumeCustomDialog';

interface SessionContextMenuProps {
  x: number;
  y: number;
  session: Session;
  onClose: () => void;
  /** Tab ID — present when opened from a tab, enables Close Tab/Close Others */
  tabId?: string;
  /** Callback for Close Tab */
  onCloseTab?: (tabId: string) => void;
  /** Callback for Close Others */
  onCloseOthers?: (keepTabId: string) => void;
  /** Callback for Rename (inline editing) */
  onRename?: () => void;
}

// ─── Submenu component (ported from UCI SubMenuItem) ───────────────────────

function SubMenu({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <div
      className="context-menu-item submenu-trigger"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      {label} {'\u25B6'}
      {open && <div className="context-submenu">{children}</div>}
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────

export default function SessionContextMenu({
  x, y, session, onClose, tabId, onCloseTab, onCloseOthers, onRename,
}: SessionContextMenuProps): JSX.Element {
  const { showToast } = useToast();
  const cardStore = useCardStore();
  const folderStore = useFolderStore();
  const menuRef = useRef<HTMLDivElement>(null);

  const isRunning = session.process_status === 'running';
  const isStopped = !isRunning;
  const displayName = session.display_name || session.tracking_id;

  // BriefDialog state
  const [briefDialogOpen, setBriefDialogOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [briefPreCheckLaunch, setBriefPreCheckLaunch] = useState(false);

  // ResumeCustomDialog state
  const [resumeDialog, setResumeDialog] = useState<{ mode: 'resume' | 'fork' } | null>(null);

  const handleResumeCustom = (opts: ResumeCustomOpts) => {
    executeCommand('session.resume', {
      trackingId: session.tracking_id,
      workdir: opts.workdir,
      model: opts.model,
      roles: opts.roles,
      prePrompt: opts.prePrompt,
    }, { onFailure: 'toast', toastFn: showToast });
    setResumeDialog(null);
    close();
  };

  const handleForkCustom = async (opts: ResumeCustomOpts) => {
    const result = await executeCommand('session.create', {
      parentTrackingId: session.tracking_id,
      platform: session.platform,
      projectDir: opts.workdir,
      model: opts.model,
      roles: opts.roles,
      prePrompt: opts.prePrompt,
    }, { onFailure: 'toast', toastFn: showToast });
    const data = result?.data as { trackingId?: string } | undefined;
    if (result?.ok && data?.trackingId) {
      executeCommand('workspace.tabs.open', { type: 'session', targetId: data.trackingId, label: `Fork of ${displayName}` });
    }
    setResumeDialog(null);
    close();
  };

  // Gather condenser sessions — active sessions tagged 'condenser' by default
  const { sessions: allSessions } = useSessionStore();
  const condenserSessions = allSessions.filter(s =>
    s.process_status === 'running' && s.tags.includes('condenser')
  );

  // Gather existing brief names for conflict detection
  const { briefs: briefCards } = useCardStore();
  const existingBriefNames = briefCards.map(b => b.display_name || b.name);

  const handleCreateBrief = async (opts: CreateBriefOpts) => {
    setBriefDialogOpen(false);
    showToast('Creating brief...', 'info');
    try {
      const result = await executeCommand('brief.create', {
        sessionIds: [session.tracking_id],
        opts: {
          name: opts.name,
          description: opts.description,
          folder: opts.folder,
          launch: opts.launch,
          launchName: opts.launchName,
          launchPlatform: opts.launchPlatform,
          condenserSession: opts.condenserSession,
        },
      });
      if (result.ok) {
        showToast(`Brief "${opts.name}" created`, 'info');
      } else {
        showToast(`Brief creation failed: ${result.error?.message || 'unknown error'}`, 'error');
      }
    } catch (err: any) {
      showToast(`Brief creation error: ${err.message}`, 'error');
    }
    close();
  };

  useContextMenuDismiss(menuRef, onClose);

  const close = onClose;
  const copy = (text: string, label: string) => {
    window.uai.clipboard.write(text);
    showToast(`Copied ${label}`, 'info');
    close();
  };
  const cmd = (type: string, payload: Record<string, unknown>) => {
    executeCommand(type, payload, { onFailure: 'toast', toastFn: showToast });
    close();
  };

  // Clamp position to viewport
  const menuX = Math.min(x, window.innerWidth - 220);
  const menuY = Math.min(y, window.innerHeight - 500);

  // Folder data for Move to Folder submenu
  const folders = folderStore.storeData.folders;
  const sessionsRoot = 'all_sessions';
  const userFolders = Object.values(folders).filter(f => f.id !== 'all_sessions' && f.id !== 'all_briefs' && !f.builtin);

  const sessionCardId = `session:${session.tracking_id}`;

  // ── Viewport reporting ──────────────────────────────────────────────────

  const actions: Array<{ id: string; command: string; label: string; payload: Record<string, unknown> }> = [
    { id: 'session_details', command: 'workspace.tabs.open', label: 'Session Details', payload: {} },
    { id: 'rename', command: 'session.update', label: 'Rename', payload: {} },
    { id: 'copy_name', command: 'clipboard.write', label: 'Copy Name', payload: {} },
    { id: 'copy_uri', command: 'clipboard.write', label: 'Copy URI', payload: {} },
    { id: 'copy_cli_uuid', command: 'clipboard.write', label: 'Copy CLI UUID', payload: {} },
    { id: 'copy_terminal', command: 'clipboard.write', label: 'Copy Terminal Name', payload: {} },
    { id: 'pin', command: 'session.update', label: session.pinned ? 'Unpin' : 'Pin', payload: {} },
    { id: 'resume', command: 'session.resume', label: 'Resume', payload: {} },
    { id: 'fork', command: 'session.fork', label: 'Fork', payload: {} },
    { id: 'archive', command: 'session.archive', label: 'Archive', payload: {} },
  ];
  if (isRunning) actions.push({ id: 'stop', command: 'session.stop', label: 'Stop', payload: {} });
  if (isStopped) actions.push({ id: 'delete', command: 'session.archive', label: 'Delete', payload: {} });
  if (tabId) {
    actions.push({ id: 'close_tab', command: 'workspace.tabs.close', label: 'Close Tab', payload: {} });
    actions.push({ id: 'close_others', command: 'workspace.tabs.close', label: 'Close Others', payload: {} });
  }

  useViewport('session_context_menu', () => ({
    visible: true,
    label: `context menu for ${displayName}`,
    state: { targetId: session.tracking_id },
    actions,
    children: [],
  }));

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <div ref={menuRef} className="context-menu session-context-menu" style={{ position: 'fixed', left: menuX, top: menuY, zIndex: 1000 }}>

      {/* 1. Session Details / Open in New Tab */}
      <button className="context-menu-item" onClick={() => {
        executeCommand('workspace.tabs.open', { type: 'session', targetId: session.tracking_id, label: displayName });
        close();
      }}>Open in New Tab</button>

      <div className="context-menu-separator" />

      {/* 2. Rename */}
      {!renaming ? (
        <button className="context-menu-item" onClick={() => {
          if (onRename) { onRename(); close(); }
          else setRenaming(true);
        }}>Rename</button>
      ) : (
        <div className="context-menu-item" style={{ padding: '4px 8px' }} onClick={e => e.stopPropagation()}>
          <input
            className="context-menu-rename-input"
            defaultValue={displayName}
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                const val = (e.target as HTMLInputElement).value.trim();
                if (val && val !== displayName) {
                  executeCommand('session.update', {
                    trackingId: session.tracking_id,
                    patch: { display_name: val },
                  }, { onFailure: 'toast', toastFn: showToast });
                }
                close();
              }
              if (e.key === 'Escape') setRenaming(false);
            }}
            style={{ width: '100%', padding: '3px 6px', fontSize: '12px', background: 'var(--bg-input, #1a1d28)', border: '1px solid var(--accent-blue)', borderRadius: '3px', color: 'var(--text)', outline: 'none' }}
          />
        </div>
      )}

      {/* 3. Copy submenu */}
      <SubMenu label="Copy">
        <button className="context-menu-item" onClick={() => copy(displayName, 'name')}>Name</button>
        <button className="context-menu-item" onClick={() => copy(session.tracking_id, 'tracking ID')}>Tracking ID</button>
        <button className="context-menu-item" onClick={() => copy(session.cli_session_id || '', 'session ID (UUID)')}>Session ID (UUID)</button>
        <button className="context-menu-item" onClick={() => copy(session.terminal_session || '', 'terminal ID')}>Terminal ID</button>
        <button className="context-menu-item" onClick={() => copy(`uai://session/${session.tracking_id}`, 'URI')}>URI</button>
      </SubMenu>

      <div className="context-menu-separator" />

      {/* 4. Resume / Fork submenu */}
      <SubMenu label="Resume / Fork">
        <button className="context-menu-item" disabled={isRunning} onClick={() => cmd('session.resume', { trackingId: session.tracking_id })}>Resume</button>
        <button className="context-menu-item" disabled={isRunning} onClick={() => setResumeDialog({ mode: 'resume' })}>Resume Custom...</button>
        <div className="context-menu-separator" />
        <button className="context-menu-item" onClick={async () => {
          const result = await executeCommand('session.create', { parentTrackingId: session.tracking_id, platform: session.platform }, { onFailure: 'toast', toastFn: showToast });
          const data = result?.data as { trackingId?: string } | undefined;
          if (result?.ok && data?.trackingId) {
            executeCommand('workspace.tabs.open', { type: 'session', targetId: data.trackingId, label: `Fork of ${displayName}` });
          }
          close();
        }}>Fork</button>
        <button className="context-menu-item" onClick={() => setResumeDialog({ mode: 'fork' })}>Fork Custom...</button>
      </SubMenu>

      {/* 5. Briefings submenu */}
      <SubMenu label="Briefings">
        <button className="context-menu-item" onClick={() => { setBriefPreCheckLaunch(false); setBriefDialogOpen(true); }}>Create Brief...</button>
        <button className="context-menu-item" onClick={() => { setBriefPreCheckLaunch(true); setBriefDialogOpen(true); }}>Create Brief and Launch</button>
        {isRunning && <button className="context-menu-item" onClick={() => { showToast('Load Brief — coming soon', 'info'); close(); }}>Load Brief...</button>}
      </SubMenu>

      <div className="context-menu-separator" />

      {/* 6. Tags submenu */}
      <SubMenu label="Tags">
        <div style={{ padding: '4px 8px' }} onClick={e => e.stopPropagation()}>
          <input
            className="context-menu-tag-input"
            placeholder="Add tag..."
            onKeyDown={async (e) => {
              if (e.key === 'Enter') {
                const tag = (e.target as HTMLInputElement).value.trim();
                if (tag) { cmd('tag.add', { cardId: sessionCardId, tag }); }
              }
            }}
            autoFocus
          />
        </div>
        {session.tags.length > 0 && (
          <>
            <div className="context-menu-separator" />
            {session.tags.map(tag => (
              <button key={tag} className="context-menu-item" onClick={() => cmd('tag.remove', { cardId: sessionCardId, tag })}>
                Remove "{tag}"
              </button>
            ))}
          </>
        )}
      </SubMenu>

      {/* 7. Move to Folder submenu */}
      {userFolders.length > 0 && (
        <SubMenu label="Move to Folder">
          <button className="context-menu-item" onClick={() => cmd('folder.moveCard', { cardId: sessionCardId, targetFolderId: sessionsRoot })}>/ All Sessions</button>
          {userFolders.map(f => (
            <button key={f.id} className="context-menu-item" onClick={() => cmd('folder.moveCard', { cardId: sessionCardId, targetFolderId: f.id })}>{f.name}</button>
          ))}
        </SubMenu>
      )}

      <div className="context-menu-separator" />

      {/* 8. Prompt block / unblock (Noctis prompt-blocks). When blocked, the
          session holds prompts from every other session — PianoMan's input
          always passes. The 🔒 chip flips after the command (handler re-emits
          a 'sessions' refresh). */}
      {session.prompt_block ? (
        <button className="context-menu-item" onClick={() => cmd('session.unblock', { trackingId: session.tracking_id })}>
          {'🔓'} Unblock prompts
        </button>
      ) : (
        <SubMenu label={'🔒 Block prompts'}>
          <button className="context-menu-item" onClick={() => cmd('session.block', { trackingId: session.tracking_id })}>Indefinitely</button>
          <button className="context-menu-item" onClick={() => cmd('session.block', { trackingId: session.tracking_id, until: '+30m' })}>+30 min</button>
          <button className="context-menu-item" onClick={() => cmd('session.block', { trackingId: session.tracking_id, until: '+1h' })}>+1 hour</button>
          <button className="context-menu-item" onClick={() => cmd('session.block', { trackingId: session.tracking_id, turns: 3 })}>3 turns</button>
        </SubMenu>
      )}

      <div className="context-menu-separator" />

      {/* 9. Close Tab / Close Others — only from tab context */}
      {tabId && onCloseTab && (
        <button className="context-menu-item" onClick={() => { onCloseTab(tabId); close(); }}>Close Tab</button>
      )}
      {tabId && onCloseOthers && (
        <SubMenu label="Close Others">
          <button className="context-menu-item" onClick={() => { onCloseOthers(tabId); close(); }}>All Others</button>
        </SubMenu>
      )}

      <div className="context-menu-separator" />

      {/* 10. Stop / Resume / Force Stop / Delete */}
      {isRunning && (
        <button className="context-menu-item danger" onClick={() => cmd('session.stop', { trackingId: session.tracking_id })}>Stop</button>
      )}
      {isStopped && (
        <button className="context-menu-item" onClick={() => cmd('session.resume', { trackingId: session.tracking_id })}>Resume</button>
      )}
      {isRunning && (
        <button className="context-menu-item danger" onClick={() => cmd('session.stop', { trackingId: session.tracking_id, force: true })}>Force Stop</button>
      )}
      {isStopped && (
        <button className="context-menu-item danger" onClick={async () => {
          if (!confirm(`Delete session "${displayName}"?`)) { close(); return; }
          // Close tab first (renderer-side, immediate visual feedback)
          if (tabId && onCloseTab) onCloseTab(tabId);
          // Then archive + remove from disk
          await executeCommand('session.delete', { trackingId: session.tracking_id }, { onFailure: 'toast', toastFn: showToast });
          close();
        }}>Delete</button>
      )}

      {/* BriefDialog — rendered as portal overlay */}
      <BriefDialog
        isOpen={briefDialogOpen}
        onClose={() => { setBriefDialogOpen(false); close(); }}
        onConfirm={handleCreateBrief}
        sourceSessions={[session]}
        existingNames={existingBriefNames}
        folders={['/']}
        preCheckLaunch={briefPreCheckLaunch}
        condenserSessions={condenserSessions}
        allSessions={allSessions}
      />

      {/* ResumeCustomDialog — parameterized resume/fork */}
      {resumeDialog && (
        <ResumeCustomDialog
          session={session}
          mode={resumeDialog.mode}
          x={Math.min(x + 40, window.innerWidth - 380)}
          y={Math.min(y, window.innerHeight - 420)}
          onSubmit={resumeDialog.mode === 'resume' ? handleResumeCustom : handleForkCustom}
          onClose={() => { setResumeDialog(null); close(); }}
        />
      )}
    </div>
  );
}
