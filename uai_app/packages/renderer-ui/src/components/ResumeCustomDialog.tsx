/**
 * ResumeCustomDialog — parameterized session resume/fork dialog.
 *
 * Replaces the old window.prompt() placeholder (which Electron disables).
 * Lets the user override working directory, model, roles, and an optional
 * initial prompt when resuming or forking a session.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import type { Session } from '@uai/shared/types';

export interface ResumeCustomOpts {
  workdir?: string;
  model?: string;
  roles?: string[];
  prePrompt?: string;
}

interface ResumeCustomDialogProps {
  session: Session;
  /** 'resume' reattaches the same session; 'fork' branches a new one */
  mode: 'resume' | 'fork';
  x: number;
  y: number;
  onSubmit: (opts: ResumeCustomOpts) => void;
  onClose: () => void;
}

export default function ResumeCustomDialog({
  session, mode, x, y, onSubmit, onClose,
}: ResumeCustomDialogProps): JSX.Element {
  const [workdir, setWorkdir] = useState(session.project_dir || '');
  const [model, setModel] = useState(session.model || '');
  const [roles, setRoles] = useState((session.roles || []).join(', '));
  const [prePrompt, setPrePrompt] = useState('');

  const [pos, setPos] = useState({ x, y });
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleDragStart = useCallback((e: React.MouseEvent) => {
    if (!(e.target as HTMLElement).closest('.resume-dialog-header')) return;
    dragRef.current = { startX: e.clientX, startY: e.clientY, origX: pos.x, origY: pos.y };
    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      setPos({
        x: dragRef.current.origX + (ev.clientX - dragRef.current.startX),
        y: dragRef.current.origY + (ev.clientY - dragRef.current.startY),
      });
    };
    const onUp = () => {
      dragRef.current = null;
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }, [pos]);

  const handleSubmit = () => {
    const roleList = roles.split(',').map(r => r.trim()).filter(Boolean);
    onSubmit({
      workdir: workdir.trim() || undefined,
      model: model.trim() || undefined,
      roles: roleList.length > 0 ? roleList : undefined,
      prePrompt: prePrompt.trim() || undefined,
    });
  };

  const title = mode === 'resume' ? 'Resume Custom' : 'Fork Custom';
  const actionLabel = mode === 'resume' ? 'Resume' : 'Fork';
  const displayName = session.display_name || session.tracking_id;

  return createPortal(
    <div
      className="resume-dialog-overlay"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
    <div
      className="resume-dialog"
      style={{ position: 'fixed', left: pos.x, top: pos.y, zIndex: 10000 }}
      onMouseDown={handleDragStart}
    >
      <div className="resume-dialog-header" style={{ cursor: 'grab' }}>
        {title}
        <span className="resume-dialog-subtitle">{displayName}</span>
      </div>

      <div className="resume-dialog-body">
        <div className="resume-dialog-field">
          <label className="resume-dialog-label">Working Directory</label>
          <input
            className="resume-dialog-input"
            type="text"
            value={workdir}
            onChange={e => setWorkdir(e.target.value)}
            placeholder={session.project_dir || '$AI_ROOT'}
          />
        </div>

        <div className="resume-dialog-field">
          <label className="resume-dialog-label">Model <span className="resume-dialog-hint">(blank = session default)</span></label>
          <input
            className="resume-dialog-input"
            type="text"
            value={model}
            onChange={e => setModel(e.target.value)}
            placeholder={session.model || 'e.g. claude-opus-4-8, claude-sonnet-4-6'}
          />
        </div>

        <div className="resume-dialog-field">
          <label className="resume-dialog-label">Roles <span className="resume-dialog-hint">(comma-separated)</span></label>
          <input
            className="resume-dialog-input"
            type="text"
            value={roles}
            onChange={e => setRoles(e.target.value)}
            placeholder="assistant, worker"
          />
        </div>

        <div className="resume-dialog-field">
          <label className="resume-dialog-label">Initial Prompt <span className="resume-dialog-hint">(optional)</span></label>
          <textarea
            className="resume-dialog-textarea"
            value={prePrompt}
            onChange={e => setPrePrompt(e.target.value)}
            placeholder="Optional message to send after resume..."
            rows={3}
          />
        </div>
      </div>

      <div className="resume-dialog-actions">
        <button className="resume-dialog-btn resume-dialog-btn-cancel" onClick={onClose}>Cancel</button>
        <button className="resume-dialog-btn resume-dialog-btn-submit" onClick={handleSubmit}>{actionLabel}</button>
      </div>
    </div>
    </div>,
    document.body,
  );
}
