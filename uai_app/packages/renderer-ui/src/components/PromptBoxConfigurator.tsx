/**
 * PromptBoxConfigurator — the full Prompt Box settings surface, opened from the
 * "⚙ Config" button in the Prompt Box control pane. Houses the quick toggles (also
 * surfaced inline in the pane), the editable Quick Actions, and the per-session
 * reminder — with room for more options as features land.
 *
 * Rendered as a popover pinned above the Prompt Box; dismiss on outside click,
 * the × button, or Escape.
 */

import { useEffect, useRef, useState, type CSSProperties } from 'react';
import type { PromptReminder } from '@uai/shared/types';
import { useDraggable } from '../hooks/useDraggable';

type QuickAction = { label: string; text: string };

interface PromptBoxConfiguratorProps {
  autoSubmit: boolean;
  onToggleAutoSubmit: () => void;
  /** Whether the 📎 Attach button is shown in the control pane. */
  showAttach: boolean;
  onToggleShowAttach: () => void;
  /** Whether the 🔖 Library button is shown in the control pane. */
  showLibrary: boolean;
  onToggleShowLibrary: () => void;
  /** Editable quick actions (label + text sent). Order = display order. */
  quickNudges: QuickAction[];
  onQuickNudgesChange: (next: QuickAction[]) => void;
  /** How many columns to lay the quick-action buttons out in (1–4). */
  quickNudgeColumns: number;
  onQuickNudgeColumnsChange: (n: number) => void;
  /** Default prompt-box height in lines (the floor it opens/collapses to). */
  defaultHeightLines: number;
  onDefaultHeightLinesChange: (n: number) => void;
  multiSendDelaySec: number;
  onMultiSendDelayChange: (sec: number) => void;
  /** Target session — reminders are per-session, so we label the section with it. */
  sessionName: string;
  /** Current per-session reminder (undefined = none set). */
  reminder?: PromptReminder;
  /** Persist a reminder change (undefined clears it). */
  onReminderChange: (next: PromptReminder | undefined) => void;
  /** Fixed-position anchor style so the popover escapes the pane's overflow clip. */
  anchorStyle?: CSSProperties;
  onClose: () => void;
}

const EMPTY_REMINDER: PromptReminder = { enabled: true, cadence: 'every', prepend: '', append: '' };

export default function PromptBoxConfigurator({
  autoSubmit,
  onToggleAutoSubmit,
  showAttach,
  onToggleShowAttach,
  showLibrary,
  onToggleShowLibrary,
  quickNudges,
  onQuickNudgesChange,
  quickNudgeColumns,
  onQuickNudgeColumnsChange,
  defaultHeightLines,
  onDefaultHeightLinesChange,
  multiSendDelaySec,
  onMultiSendDelayChange,
  sessionName,
  reminder,
  onReminderChange,
  anchorStyle,
  onClose,
}: PromptBoxConfiguratorProps): JSX.Element {
  const ref = useRef<HTMLDivElement>(null);
  const drag = useDraggable();

  // ── Local editing mirrors (responsive typing; persistence debounced) ──────
  const [draft, setDraft] = useState<PromptReminder>(reminder ?? { ...EMPTY_REMINDER, enabled: false });
  const reminderTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [actions, setActions] = useState<QuickAction[]>(quickNudges);
  const actionsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => { setDraft(reminder ?? { ...EMPTY_REMINDER, enabled: false }); }, [reminder]);
  useEffect(() => { setActions(quickNudges); }, [quickNudges]);

  const pushReminder = (next: PromptReminder, immediate: boolean): void => {
    setDraft(next);
    if (reminderTimer.current) { clearTimeout(reminderTimer.current); reminderTimer.current = null; }
    if (immediate) onReminderChange(next);
    else reminderTimer.current = setTimeout(() => onReminderChange(next), 400);
  };

  const pushActions = (next: QuickAction[], immediate: boolean): void => {
    setActions(next);
    if (actionsTimer.current) { clearTimeout(actionsTimer.current); actionsTimer.current = null; }
    if (immediate) onQuickNudgesChange(next);
    else actionsTimer.current = setTimeout(() => onQuickNudgesChange(next), 400);
  };

  useEffect(() => () => {
    if (reminderTimer.current) clearTimeout(reminderTimer.current);
    if (actionsTimer.current) clearTimeout(actionsTimer.current);
  }, []);

  // Dismiss on outside-click or Escape. Flush any pending text persist first.
  useEffect(() => {
    const flush = () => {
      if (reminderTimer.current) { clearTimeout(reminderTimer.current); reminderTimer.current = null; onReminderChange(draft); }
      if (actionsTimer.current) { clearTimeout(actionsTimer.current); actionsTimer.current = null; onQuickNudgesChange(actions); }
    };
    const onDown = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      // Ignore clicks on the ⚙ Config button itself — it owns the open/close toggle;
      // otherwise this handler closes just as the button's onClick reopens (no-op).
      if (t.closest && t.closest('.promptbox-config')) return;
      if (ref.current && !ref.current.contains(t)) { flush(); onClose(); }
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { flush(); onClose(); } };
    const t = setTimeout(() => {
      document.addEventListener('mousedown', onDown);
      document.addEventListener('keydown', onKey);
    }, 0);
    return () => {
      clearTimeout(t);
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose, onReminderChange, onQuickNudgesChange, draft, actions]);

  // Quick-action edit ops.
  const editAction = (i: number, patch: Partial<QuickAction>) =>
    pushActions(actions.map((a, j) => (j === i ? { ...a, ...patch } : a)), false);
  const moveAction = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= actions.length) return;
    const next = actions.slice();
    [next[i], next[j]] = [next[j], next[i]];
    pushActions(next, true);
  };
  const removeAction = (i: number) => pushActions(actions.filter((_, j) => j !== i), true);
  const addAction = () => pushActions([...actions, { label: 'New', text: '' }], true);

  const hasReminderContent = !!(draft.prepend && draft.prepend.trim()) || !!(draft.append && draft.append.trim());

  return (
    <div
      className={`promptbox-config-popover${drag.dragging ? ' is-dragging' : ''}`}
      ref={ref}
      role="dialog"
      aria-label="Prompt Box settings"
      style={{ ...anchorStyle, ...drag.dragStyle }}
    >
      <div
        className="promptbox-config-head promptbox-drag-handle"
        onMouseDown={drag.onHandleMouseDown}
        title="Drag to move"
      >
        <span className="promptbox-config-title">{'✥'} Prompt Box Settings</span>
        <button className="promptbox-config-close" onClick={onClose} title="Close">{'×'}</button>
      </div>

      <div className="promptbox-config-section">
        <label className="promptbox-config-row">
          <input type="checkbox" checked={autoSubmit} onChange={onToggleAutoSubmit} />
          <span className="promptbox-config-label">
            <span className="promptbox-config-name">Auto-submit</span>
            <span className="promptbox-config-desc">
              Send types the prompt and presses Enter for you. Turn off to <em>stage</em>
              {' '}the text into the CLI prompt area without submitting — you review it and
              {' '}press Enter yourself.
            </span>
          </span>
        </label>
        <label className="promptbox-config-row">
          <input type="checkbox" checked={showAttach} onChange={onToggleShowAttach} />
          <span className="promptbox-config-label">
            <span className="promptbox-config-name">Attach button</span>
            <span className="promptbox-config-desc">
              Show the {'📎'} Attach button in the control pane (file/image picker → inserts an
              {' '}<code>@path</code> the CLI reads). Turn off to hide it.
            </span>
          </span>
        </label>
        <label className="promptbox-config-row">
          <input type="checkbox" checked={showLibrary} onChange={onToggleShowLibrary} />
          <span className="promptbox-config-label">
            <span className="promptbox-config-name">Library button</span>
            <span className="promptbox-config-desc">
              Show the {'🔖'} Library button in the control pane (saved-prompts repository →
              {' '}insert, send, or save the current draft). Turn off to hide it.
            </span>
          </span>
        </label>
        <label className="promptbox-config-row" style={{ alignItems: 'center' }}>
          <input
            type="number"
            min={3}
            max={32}
            step={1}
            value={defaultHeightLines}
            onChange={(e) => onDefaultHeightLinesChange(Number(e.target.value))}
            style={{ width: 56 }}
          />
          <span className="promptbox-config-label">
            <span className="promptbox-config-name">Default height (lines)</span>
            <span className="promptbox-config-desc">
              How tall the prompt box opens, and the floor it collapses to when you
              {' '}double-click the resize bar. Default 15. You can still drag it taller for a
              {' '}single message.
            </span>
          </span>
        </label>
        <label className="promptbox-config-row" style={{ alignItems: 'center' }}>
          <input
            type="number"
            min={0}
            max={30}
            step={0.25}
            value={multiSendDelaySec}
            onChange={(e) => onMultiSendDelayChange(Number(e.target.value))}
            style={{ width: 56 }}
          />
          <span className="promptbox-config-label">
            <span className="promptbox-config-name">Multi-send pause (seconds)</span>
            <span className="promptbox-config-desc">
              When one Send goes to several recipients, wait this long between each
              {' '}delivery — lets each session's terminal settle instead of firing back-to-back.
              {' '}Default 0 (no pause). Only applies when sending to more than one recipient.
            </span>
          </span>
        </label>
      </div>

      {/* ── Quick actions ────────────────────────────────────────────────── */}
      <div className="promptbox-config-section">
        <div className="promptbox-config-label" style={{ marginBottom: 6 }}>
          <span className="promptbox-config-name">Quick Actions</span>
          <span className="promptbox-config-desc">
            One-tap buttons that send a fixed prompt and submit it. Edit the label and the
            {' '}text sent, reorder, add or remove.
          </span>
        </div>

        <div className="promptbox-qa-list">
          {actions.map((a, i) => (
            <div className="promptbox-qa-row" key={i}>
              <input
                className="promptbox-qa-label"
                value={a.label}
                placeholder="Label"
                onChange={(e) => editAction(i, { label: e.target.value })}
              />
              <input
                className="promptbox-qa-text"
                value={a.text}
                placeholder="Text sent"
                onChange={(e) => editAction(i, { text: e.target.value })}
              />
              <div className="promptbox-qa-ops">
                <button disabled={i === 0} onClick={() => moveAction(i, -1)} title="Move up">{'▲'}</button>
                <button disabled={i === actions.length - 1} onClick={() => moveAction(i, 1)} title="Move down">{'▼'}</button>
                <button className="promptbox-qa-remove" onClick={() => removeAction(i)} title="Remove">{'×'}</button>
              </div>
            </div>
          ))}
        </div>

        <div className="promptbox-qa-footer">
          <button className="promptbox-qa-add" onClick={addAction}>{'＋'} Add action</button>
          <label className="promptbox-qa-columns">
            Columns
            <select
              value={quickNudgeColumns}
              onChange={(e) => onQuickNudgeColumnsChange(Number(e.target.value))}
            >
              <option value={1}>1</option>
              <option value={2}>2</option>
              <option value={3}>3</option>
              <option value={4}>4</option>
            </select>
          </label>
        </div>
      </div>

      {/* ── Per-session reminder ─────────────────────────────────────────── */}
      <div className="promptbox-config-section">
        <label className="promptbox-config-row">
          <input
            type="checkbox"
            checked={!!draft.enabled}
            onChange={(e) => pushReminder({ ...draft, enabled: e.target.checked }, true)}
          />
          <span className="promptbox-config-label">
            <span className="promptbox-config-name">Reminder — {sessionName}</span>
            <span className="promptbox-config-desc">
              A prepend/append that auto-wraps your prompts to <em>this session</em> on a
              {' '}cadence. The visible, in-band cousin of a standing note.
            </span>
          </span>
        </label>

        <div className="promptbox-reminder-editor" data-enabled={draft.enabled ? '1' : '0'}>
          <label className="promptbox-reminder-field">
            <span className="promptbox-reminder-field-label">Prepend (above your prompt)</span>
            <textarea
              className="promptbox-reminder-textarea"
              value={draft.prepend ?? ''}
              placeholder="e.g. REMEMBER: commit via Git Guardian."
              rows={2}
              onChange={(e) => pushReminder({ ...draft, prepend: e.target.value }, false)}
            />
          </label>
          <label className="promptbox-reminder-field">
            <span className="promptbox-reminder-field-label">Append (below your prompt)</span>
            <textarea
              className="promptbox-reminder-textarea"
              value={draft.append ?? ''}
              placeholder="e.g. Report the deployed version number."
              rows={2}
              onChange={(e) => pushReminder({ ...draft, append: e.target.value }, false)}
            />
          </label>

          <div className="promptbox-reminder-cadence-row">
            <span className="promptbox-reminder-field-label">Cadence</span>
            <div className="promptbox-reminder-cadence-opts">
              <label>
                <input type="radio" name="reminder-cadence" checked={draft.cadence === 'every'}
                  onChange={() => pushReminder({ ...draft, cadence: 'every' }, true)} />
                <span>Every send</span>
              </label>
              <label>
                <input type="radio" name="reminder-cadence" checked={draft.cadence === 'nth'}
                  onChange={() => pushReminder({ ...draft, cadence: 'nth', n: draft.n ?? 3 }, true)} />
                <span>Every</span>
                <input type="number" className="promptbox-reminder-n" min={2} value={draft.n ?? 3}
                  disabled={draft.cadence !== 'nth'}
                  onChange={(e) => pushReminder({ ...draft, cadence: 'nth', n: Math.max(2, Number(e.target.value) || 2) }, true)} />
                <span>sends</span>
              </label>
              <label>
                <input type="radio" name="reminder-cadence" checked={draft.cadence === 'once'}
                  onChange={() => pushReminder({ ...draft, cadence: 'once' }, true)} />
                <span>Next send only</span>
              </label>
            </div>
          </div>

          <div className="promptbox-reminder-actions">
            <button
              className="promptbox-reminder-clear"
              disabled={!hasReminderContent && !reminder}
              onClick={() => {
                if (reminderTimer.current) { clearTimeout(reminderTimer.current); reminderTimer.current = null; }
                setDraft({ ...EMPTY_REMINDER, enabled: false });
                onReminderChange(undefined);
              }}
              title="Remove this session's reminder entirely"
            >
              Clear reminder
            </button>
          </div>
        </div>
      </div>

      <div className="promptbox-config-note">
        More Prompt Box options appear here as features land.
      </div>
    </div>
  );
}
