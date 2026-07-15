/**
 * PromptBox — Staged prompt input at bottom of workspace.
 *
 * Shows target session name. Cmd+Enter stages text to active terminal.
 * Per-session draft preservation: switching tabs keeps unsent text.
 * Auto-grow/shrink textarea. Resize handle.
 * !h or !history command opens prompt history overlay.
 *
 * Registered as part of the workspace component tree.
 */

import { useState, useRef, useCallback, useEffect, useMemo, type CSSProperties } from 'react';
import { useToast } from './Toast';
import { useCommandErrorHandler } from '../hooks/useCommandErrorHandler';
import { executeCommand } from '../utils/execute-command';
import { useViewport } from '../viewport';
import HistoryPanel from './HistoryPanel';
import type { HistoryEntry } from './HistoryPanel';
import PromptBoxConfigurator from './PromptBoxConfigurator';
import PromptLibraryPopover from './PromptLibraryPopover';
import PromptRewriteDialog from './PromptRewriteDialog';
import RecipientPicker from './RecipientPicker';
import { parseSessionMentions } from './prompt-mentions';
import { useMention, MentionPopover, makeRecipientSource, makePathSource } from './mention';
import { useSessionStore } from '../stores/session-store';
import { touchSessionActivity } from '../stores/session-activity';
import { scanSessionPromptArea } from '../stores/prompt-area-state';
import { onPromptBoxFocusRequest } from '../stores/promptbox-focus';
import { applyReminder, reminderHasContent } from './prompt-reminder';
import type { PromptReminder, PromptBoxConfig, SavedPrompt } from '@uai/shared/types';

interface PromptBoxProps {
  sessionId: string;
  sessionName: string;
  cliSessionId?: string | null;
}

// Prompt box sizing. LINE_HEIGHT must match the textarea's CSS line-height.
const PROMPT_LINE_HEIGHT = 18;   // px per line
const PROMPT_VPAD = 16;          // textarea vertical padding (8 top + 8 bottom)
const PROMPT_DEFAULT_LINES = 15;
const PROMPT_DEFAULT_HEIGHT = PROMPT_DEFAULT_LINES * PROMPT_LINE_HEIGHT + PROMPT_VPAD; // ~286px
const PROMPT_MAX_HEIGHT = 1400;  // absolute sanity ceiling; the real cap is viewport-relative (computeMaxHeight)

// Per-session draft storage (in-memory for fast tab switching)
const sessionDrafts = new Map<string, string>();

// Per-session count of outgoing prompts this app-run — drives the reminder 'nth'
// cadence. In-memory only (resets on relaunch); the reminder config itself persists.
const sessionSendCounts = new Map<string, number>();

/** A one-tap quick-react nudge: the button `label` and the `text` it sends (always
 *  submitted, regardless of the auto-submit toggle). Customizable via the configurator
 *  (persisted in appState.promptBoxConfig.quickNudges); this is the default set. */
export interface QuickNudge { label: string; text: string; }
const DEFAULT_NUDGES: QuickNudge[] = [
  { label: 'Proceed', text: 'proceed' },
  { label: 'Continue', text: 'continue' },
  { label: 'Yes', text: 'yes' },
  { label: 'Commit', text: 'commit and push' },
];

/** A messageable group (team or project) resolved to its member sessions. */
interface PromptGroup { name: string; handle: string; kind: 'team' | 'project'; memberIds: string[]; }
/** A @-mention autocomplete/picker target (a session or a group). */
export interface MentionTarget {
  token: string;        // what to insert after `@` (bare word or "quoted name")
  label: string;        // display name
  kind: 'session' | 'team' | 'project';
  count: number;        // sessions it expands to (1 for a session)
  memberIds: string[];
}
/** The `@`-insert token for a name: bare if single-word, else quoted. */
function mentionToken(name: string): string {
  return /\s/.test(name) ? `"${name}"` : name;
}

/** If the pasted text is one OR MORE absolute/home filepaths — one per line, e.g.
 *  Finder "Copy as Pathname" of several files gives newline-separated paths — return
 *  each as an `@`-prefixed mention so the CLI reads them all inline. Returns null for
 *  ordinary text (any non-path line disables it, so prose pastes normally).
 *  Conservative: each non-empty line must start with `/` or `~/`. Paths may contain
 *  spaces (split on newlines only, never spaces). */
function filepathMentions(s: string): string[] | null {
  const lines = s.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (lines.length === 0 || !lines.every((l) => /^@?~?\//.test(l))) return null;
  return lines.map((p) => (p.startsWith('@') ? p : `@${p}`));
}

/** Collapse single newlines (hard-wrap artifacts) to spaces while KEEPING paragraph
 *  breaks (blank lines). For the Cmd/Ctrl+Shift+V "paste unwrapped" gesture. */
function unwrapHardBreaks(s: string): string {
  return s
    .replace(/\r\n?/g, '\n')
    .split(/\n{2,}/)
    .map((p) => p.replace(/[ \t]*\n[ \t]*/g, ' ').trim())
    .join('\n\n');
}

/** Human label for a reminder's cadence, for the active-reminder strip. */
function reminderCadenceLabel(r: PromptReminder): string {
  if (r.cadence === 'every') return 'every send';
  if (r.cadence === 'once') return 'next send only';
  return `every ${Math.max(2, Math.floor(r.n ?? 3))} sends`;
}

/** Truncate reminder text for the compact strip preview. */
function reminderSnippet(s: string, max = 48): string {
  const one = s.trim().replace(/\s+/g, ' ');
  return one.length > max ? one.slice(0, max - 1) + '…' : one;
}

/** Check if a session has a non-empty draft in PromptBox */
export function hasPromptBoxDraft(sessionId: string): boolean {
  const draft = sessionDrafts.get(sessionId);
  return !!draft && draft.trim().length > 0;
}

/** Filter out system-injected messages, matching HistoryPanel logic */
const isRealUserPrompt = (content: string): boolean => {
  const trimmed = content.trim();
  if (!trimmed) return false;
  if (trimmed.startsWith('Base directory for this skill:')) return false;
  if (trimmed.startsWith('AI_ROOT:')) return false;
  if (trimmed.startsWith('<system-reminder>')) return false;
  if (trimmed.startsWith('<task-notification>')) return false;
  if (trimmed.startsWith('<command-name>')) return false;
  if (trimmed.startsWith('<command-message>')) return false;
  if (trimmed.startsWith('<local-command-stdout>')) return false;
  if (trimmed.startsWith('# ') && trimmed.length > 1000) return false;
  if (/^[!/]/.test(trimmed) && trimmed.length < 50) return false;
  return true;
};

/** Persist prompt draft to app_state.json sessionPrefs */
async function persistDraft(sessionId: string, draft: string): Promise<void> {
  const appState = await window.uai.appState.get();
  const prefs = (appState.sessionPrefs || {}) as Record<string, Record<string, unknown>>;
  const sessionPref = prefs[sessionId] || {};
  await executeCommand('app.state.update', {
    patch: {
      sessionPrefs: {
        ...prefs,
        [sessionId]: { ...sessionPref, promptDraft: draft || undefined },
      },
    },
  });
}

/** Persist the per-session prompt reminder to app_state.json sessionPrefs.
 *  Passing undefined clears it. */
async function persistReminder(sessionId: string, reminder: PromptReminder | undefined): Promise<void> {
  const appState = await window.uai.appState.get();
  const prefs = (appState.sessionPrefs || {}) as Record<string, Record<string, unknown>>;
  const sessionPref = prefs[sessionId] || {};
  await executeCommand('app.state.update', {
    patch: {
      sessionPrefs: {
        ...prefs,
        [sessionId]: { ...sessionPref, reminder: reminder || undefined },
      },
    },
  });
}

export default function PromptBox({ sessionId, sessionName, cliSessionId }: PromptBoxProps): JSX.Element {
  const [text, setText] = useState(() => sessionDrafts.get(sessionId) || '');
  const draftTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Recipients: explicit send targets (tracking_ids). Empty = the current tab
  // (default). Chosen via the title-bar picker; resets to default on tab switch.
  const { sessions, getSession } = useSessionStore();
  const [recipients, setRecipients] = useState<string[]>([]);
  const [showRecipientPicker, setShowRecipientPicker] = useState(false);
  const recipientChipRef = useRef<HTMLDivElement>(null);

  // team/project name → member session tracking_ids. In this system a "team" is a
  // project tagged `team`, and membership lives in the project's `assigned_ais`
  // (member display names/ids); real projects also match by working dir. Keyed by both
  // display_name and project_id (the single-word handle you can `@`-mention, e.g.
  // `@uai_core`, since display names may contain spaces). Loaded async.
  const [groups, setGroups] = useState<PromptGroup[]>([]);
  useEffect(() => {
    let cancelled = false;
    const norm = (x?: string) => (x || '').replace(/^"+|"+$/g, '').replace(/\/+$/, '');
    (async () => {
      const out: PromptGroup[] = [];
      try {
        const projects = await window.uai.projects.list();
        for (const p of projects) {
          const members = new Set<string>();
          // Explicit members — assigned_ais holds display names (or ids).
          for (const m of (p as { assigned_ais?: string[] }).assigned_ais || []) {
            const sess = sessions.find((s) => !s.archived && (s.display_name === m || s.tracking_id === m));
            if (sess) members.add(sess.tracking_id);
          }
          // Implicit members — sessions whose working dir matches the project's.
          const wd = norm((p as { working_dir?: string }).working_dir);
          if (wd) for (const s of sessions) if (!s.archived && norm(s.project_dir) === wd) members.add(s.tracking_id);
          if (!members.size) continue;
          const isTeam = (p.tags || []).includes('team');
          out.push({
            name: p.display_name || String((p as { project_id?: string }).project_id || ''),
            handle: String((p as { project_id?: string }).project_id || '').toLowerCase(),
            kind: isTeam ? 'team' : 'project',
            memberIds: [...members],
          });
        }
      } catch { /* projects unavailable */ }
      if (!cancelled) setGroups(out);
    })();
    return () => { cancelled = true; };
  }, [sessions]);

  // Lowercased name/handle → session tracking_ids. Sessions map to [self]; teams/projects
  // to their members. A session name takes precedence over a same-named group.
  const nameToSessions = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const g of groups) {
      if (g.name) m.set(g.name.toLowerCase(), g.memberIds);
      if (g.handle) m.set(g.handle.toLowerCase(), g.memberIds);
    }
    for (const s of sessions) {
      if (!s.archived && s.display_name) m.set(s.display_name.toLowerCase(), [s.tracking_id]);
    }
    return m;
  }, [sessions, groups]);

  // Unified messageable targets (sessions + groups) for the @-autocomplete and picker.
  const mentionTargets = useMemo<MentionTarget[]>(() => {
    const out: MentionTarget[] = [];
    for (const s of sessions) {
      // Active (running) sessions only — no stale ghosts in the @ list (note_0035).
      if (s.archived || !s.display_name || s.process_status !== 'running') continue;
      out.push({ token: mentionToken(s.display_name), label: s.display_name, kind: 'session', count: 1, memberIds: [s.tracking_id] });
    }
    for (const g of groups) {
      out.push({ token: g.handle || mentionToken(g.name), label: g.name, kind: g.kind, count: g.memberIds.length, memberIds: g.memberIds });
    }
    return out;
  }, [sessions, groups]);
  // Everyone who'll receive a send = picker selection ∪ `@target` mentions in the draft
  // (a @team / @project mention expands to its member sessions).
  const effectiveRecipients = useMemo(
    () => Array.from(new Set([...recipients, ...parseSessionMentions(text, nameToSessions)])),
    [recipients, text, nameToSessions],
  );
  // The ACTUAL send targets. A title-bar picker selection is an explicit redirect and is
  // honored as-is. Otherwise the CURRENT TAB is ALWAYS a target and body `@name` mentions
  // only ADD recipients — so a stray `@Prism` typed into a prompt meant for the Anvil tab
  // can never silently steal the whole send away from the tab you're looking at.
  const sendTargets = useMemo(
    () => recipients.length
      ? effectiveRecipients
      : Array.from(new Set([sessionId, ...effectiveRecipients])),
    [recipients, effectiveRecipients, sessionId],
  );
  // "Off-tab" = at least one target that isn't the current tab (an explicit redirect or a
  // body mention). Drives the confirmation toast so a redirect is never a silent surprise.
  const sendsOffTab = useMemo(
    () => sendTargets.some((t) => t !== sessionId),
    [sendTargets, sessionId],
  );
  // A target is "busy" when it's actively responding — typing a follow-up into its live
  // prompt could collide with the in-flight turn, so we offer to Queue it instead.
  const anyTargetBusy = useMemo(
    () => sendTargets.some((t) => getSession(t)?.activity_state === 'responding'),
    [sendTargets, getSession, sessions],
  );

  useViewport('prompt_box', () => ({
    visible: true,
    state: {
      hasText: text.trim().length > 0,
      targetSessionId: sessionId,
      targetSessionName: sessionName,
    },
    actions: [
      { id: 'send', command: 'prompt.send', label: 'Send prompt to session', payload: { sessionId } },
    ],
    children: [],
  }));
  const [showHistory, setShowHistory] = useState(false);
  // Prompt Box config (persisted, global). autoSubmit: Send types + Enter (default);
  // when off, Send stages the text into the CLI prompt area without submitting.
  const [autoSubmit, setAutoSubmit] = useState(true);
  const [showAttach, setShowAttach] = useState(true);
  const [showLibrary, setShowLibrary] = useState(true);
  const [showLibraryPanel, setShowLibraryPanel] = useState(false);
  const [showRewrite, setShowRewrite] = useState(false);
  const [savedPrompts, setSavedPrompts] = useState<SavedPrompt[]>([]);
  const [quickNudges, setQuickNudges] = useState<QuickNudge[]>(DEFAULT_NUDGES);
  const [quickNudgeColumns, setQuickNudgeColumns] = useState(1);
  // Quick Actions open as a roomy flyout popover (breaks out of the narrow control
  // pane so multi-column layouts have space) — not an inline dropdown.
  const [showQuickActions, setShowQuickActions] = useState(false);
  const quickActionsRef = useRef<HTMLDivElement>(null);
  const [showConfig, setShowConfig] = useState(false);
  // Per-session prompt reminder (prepend/append wrap on a cadence). Loaded from
  // sessionPrefs when the session changes; edited via the configurator.
  const [reminder, setReminder] = useState<PromptReminder | undefined>(undefined);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // ── @-autocomplete (reusable ./mention module) ──────────────────────────────
  // Refs keep the source getters reading live values without rebuilding the sources
  // each render (which would otherwise reset the popover mid-type).
  const mentionTargetsRef = useRef(mentionTargets);
  mentionTargetsRef.current = mentionTargets;
  const mentionBaseDirRef = useRef<string | null | undefined>(undefined);
  mentionBaseDirRef.current = getSession(sessionId)?.project_dir;
  const mentionSources = useMemo(() => [
    makeRecipientSource(() => mentionTargetsRef.current),           // @name → sessions/teams/projects
    makePathSource({ baseDir: () => mentionBaseDirRef.current }),   // @/… @~/… @./… → files & folders
  ], []);
  const commitMentionText = useCallback((next: string, caret: number) => {
    setText(next);
    sessionDrafts.set(sessionId, next);
    persistDraft(sessionId, next);
    requestAnimationFrame(() => {
      const ta = textareaRef.current;
      ta?.focus();
      ta?.setSelectionRange(caret, caret);
    });
  }, [sessionId]);
  const mention = useMention({ textareaRef, sources: mentionSources, onApply: commitMentionText });

  // The persistence source of truth for promptBoxConfig. app.state.update shallow-
  // merges at the top level, so a partial promptBoxConfig patch would WIPE sibling
  // fields (toggling auto-submit used to drop custom quick actions). We must write the
  // WHOLE object — but rebuilding it from React state closures races: a debounced
  // field-edit persist can fire with a stale value for a DIFFERENT field and clobber
  // it. So keep a ref that's mutated synchronously in call order; every write merges
  // its override into the ref and persists the ref. No stale-closure clobber.
  const configRef = useRef<PromptBoxConfig>({
    autoSubmit: true, quickNudges: DEFAULT_NUDGES, quickNudgeColumns: 1, showAttach: true, showLibrary: true, multiSendDelaySec: 0,
  });

  // Load persisted config once on mount.
  useEffect(() => {
    let cancelled = false;
    window.uai.appState.get().then((s: { promptBoxConfig?: PromptBoxConfig }) => {
      if (cancelled || !s?.promptBoxConfig) return;
      const c = s.promptBoxConfig;
      configRef.current = { ...configRef.current, ...c };
      if (typeof c.autoSubmit === 'boolean') setAutoSubmit(c.autoSubmit);
      if (typeof c.showAttach === 'boolean') setShowAttach(c.showAttach);
      if (typeof c.showLibrary === 'boolean') setShowLibrary(c.showLibrary);
      if (Array.isArray(c.quickNudges) && c.quickNudges.length) setQuickNudges(c.quickNudges);
      if (typeof c.quickNudgeColumns === 'number') setQuickNudgeColumns(Math.max(1, Math.min(4, c.quickNudgeColumns)));
      if (typeof c.defaultHeightLines === 'number') {
        const v = Math.max(3, Math.min(32, Math.round(c.defaultHeightLines)));
        setDefaultHeightLines(v);
        // On mount the user hasn't dragged yet, so adopt the configured floor.
        setMinHeight(v * PROMPT_LINE_HEIGHT + PROMPT_VPAD);
      }
      if (typeof c.multiSendDelaySec === 'number') setMultiSendDelaySec(Math.max(0, Math.min(30, c.multiSendDelaySec)));
    }).catch(() => { /* fall back to defaults */ });
    return () => { cancelled = true; };
  }, []);

  const persistPromptBoxConfig = useCallback((over: Partial<PromptBoxConfig>) => {
    configRef.current = { ...configRef.current, ...over };
    executeCommand('app.state.update', { patch: { promptBoxConfig: configRef.current } })
      .catch(() => { /* non-critical — persists next change */ });
  }, []);

  const toggleAutoSubmit = useCallback(() => {
    setAutoSubmit((prev) => {
      const next = !prev;
      persistPromptBoxConfig({ autoSubmit: next });
      return next;
    });
  }, [persistPromptBoxConfig]);

  const toggleShowAttach = useCallback(() => {
    setShowAttach((prev) => {
      const next = !prev;
      persistPromptBoxConfig({ showAttach: next });
      return next;
    });
  }, [persistPromptBoxConfig]);

  const toggleShowLibrary = useCallback(() => {
    setShowLibrary((prev) => {
      const next = !prev;
      persistPromptBoxConfig({ showLibrary: next });
      return next;
    });
  }, [persistPromptBoxConfig]);

  // Quick-action editors (used by the configurator).
  const updateQuickNudges = useCallback((next: QuickNudge[]) => {
    setQuickNudges(next);
    persistPromptBoxConfig({ quickNudges: next });
  }, [persistPromptBoxConfig]);
  const updateQuickNudgeColumns = useCallback((n: number) => {
    const cols = Math.max(1, Math.min(4, Math.floor(n) || 1));
    setQuickNudgeColumns(cols);
    persistPromptBoxConfig({ quickNudgeColumns: cols });
  }, [persistPromptBoxConfig]);
  // Default prompt-box height (lines). Persist it AND re-adopt it as the current
  // floor so the change is visible immediately, not just next open.
  const updateDefaultHeightLines = useCallback((n: number) => {
    const lines = Math.max(3, Math.min(32, Math.round(n) || PROMPT_DEFAULT_LINES));
    setDefaultHeightLines(lines);
    setMinHeight(lines * PROMPT_LINE_HEIGHT + PROMPT_VPAD);
    setManualHeight(null); // adopt the new default — leave any manual drag override
    persistPromptBoxConfig({ defaultHeightLines: lines });
  }, [persistPromptBoxConfig]);

  const updateMultiSendDelay = useCallback((sec: number) => {
    const v = Math.max(0, Math.min(30, Number.isFinite(sec) ? sec : 0));
    setMultiSendDelaySec(v);
    persistPromptBoxConfig({ multiSendDelaySec: v });
  }, [persistPromptBoxConfig]);

  // Dismiss the Quick Actions flyout on outside-click or Escape.
  useEffect(() => {
    if (!showQuickActions) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (quickActionsRef.current && !quickActionsRef.current.contains(t) && !t.closest('.promptbox-nudges-trigger')) {
        setShowQuickActions(false);
      }
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setShowQuickActions(false); };
    const timer = setTimeout(() => {
      document.addEventListener('mousedown', onDown);
      document.addEventListener('keydown', onKey);
    }, 0);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [showQuickActions]);

  // 5.2 — Focus discipline: the Prompt Box, not the raw CLI prompt area, is the
  // default cursor home. Focus it when the session changes (tab open/switch), and
  // pull focus back whenever something requests it (e.g. after the user hits Enter
  // in the terminal — see TerminalPane / promptbox-focus bus).
  useEffect(() => {
    const id = requestAnimationFrame(() => textareaRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [sessionId]);
  useEffect(() => {
    return onPromptBoxFocusRequest((target) => {
      if (target === sessionId) textareaRef.current?.focus();
    });
  }, [sessionId]);
  // Height model: minHeight is the user-controlled floor. The DEFAULT floor is
  // configurable (Prompt Box [Config] → "Default height (lines)", default 15).
  // A manual drag changes minHeight and it sticks until the resize bar is
  // double-clicked, which collapses it to max(default, lines needed for content).
  const [defaultHeightLines, setDefaultHeightLines] = useState(PROMPT_DEFAULT_LINES);
  const defaultHeightPx = defaultHeightLines * PROMPT_LINE_HEIGHT + PROMPT_VPAD;
  // Pause between deliveries when one Send fans out to multiple recipients (0 = none).
  // Kept in a ref so the send callbacks read the latest value without re-memoizing.
  const [multiSendDelaySec, setMultiSendDelaySec] = useState(0);
  const multiSendDelayMsRef = useRef(0);
  multiSendDelayMsRef.current = Math.max(0, Math.round((multiSendDelaySec || 0) * 1000));
  const [minHeight, setMinHeight] = useState(PROMPT_DEFAULT_HEIGHT);
  // Explicit height set by dragging the resize bar. When non-null it fixes the
  // textarea height (content SCROLLS past it), so a drag can shrink the box BELOW
  // its content — the auto-grow floor (minHeight) can't. null = auto-grow mode.
  const [manualHeight, setManualHeight] = useState<number | null>(null);
  const draggingRef = useRef(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const { showToast } = useToast();
  const errorHandler = useCommandErrorHandler({
    fields: { prompt: textareaRef },
  });

  // ── Prompt history navigation (Up/Down arrow) ──────────────────────
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1); // -1 = not navigating
  const draftRef = useRef<string | null>(null); // unsaved text before navigation started

  // Load history from transcript on mount or session/cliSessionId change
  useEffect(() => {
    setHistory([]);
    setHistoryIndex(-1);
    draftRef.current = null;

    if (!cliSessionId) return;

    let cancelled = false;
    window.uai.transcript.history(cliSessionId)
      .then((result) => {
        if (cancelled || !result.ok) return;
        const userPrompts = result.messages
          .filter(m => m.role === 'user' && isRealUserPrompt(m.content))
          .map(m => m.content);
        if (!cancelled) setHistory(userPrompts);
      })
      .catch(() => { /* transcript unavailable — history stays empty */ });

    return () => { cancelled = true; };
  }, [sessionId, cliSessionId]);

  // Restore draft when session changes — prefer in-memory, fall back to persisted
  useEffect(() => {
    const memoryDraft = sessionDrafts.get(sessionId);
    if (memoryDraft !== undefined) {
      setText(memoryDraft);
    } else {
      // Load persisted draft from app_state.json on first mount or cold switch
      window.uai.appState.get().then(state => {
        const prefs = state.sessionPrefs?.[sessionId];
        if (prefs?.promptDraft) {
          setText(prefs.promptDraft);
          sessionDrafts.set(sessionId, prefs.promptDraft);
        } else {
          setText('');
        }
      });
    }
    setShowHistory(false);
  }, [sessionId]);

  // Load the per-session reminder when the session changes.
  useEffect(() => {
    let cancelled = false;
    window.uai.appState.get().then(state => {
      if (cancelled) return;
      setReminder(state.sessionPrefs?.[sessionId]?.reminder);
    }).catch(() => { if (!cancelled) setReminder(undefined); });
    return () => { cancelled = true; };
  }, [sessionId]);

  // Switching tabs resets recipients to the default (send to the new current tab).
  useEffect(() => { setRecipients([]); setShowRecipientPicker(false); }, [sessionId]);

  // Update the reminder locally + persist. Passing undefined clears it.
  const updateReminder = useCallback((next: PromptReminder | undefined) => {
    setReminder(next);
    persistReminder(sessionId, next).catch(() => { /* non-critical — persists next edit */ });
  }, [sessionId]);

  // Save draft on text change (in-memory immediately, persist with 1s debounce)
  // Historical prompts are freely editable — submitting sends the edited text
  // as a new prompt without modifying history.
  const handleChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setText(val);
    sessionDrafts.set(sessionId, val);

    // Drive the @-autocomplete from the caret position.
    const cur = typeof e.target.selectionStart === 'number' ? e.target.selectionStart : val.length;
    mention.sync(val, cur);

    // Debounce persistence to app_state.json
    if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
    draftTimerRef.current = setTimeout(() => {
      persistDraft(sessionId, val);
    }, 1000);
  }, [sessionId, mention]);

  // Max prompt-box height: viewport-relative so it can grow well past the old flat
  // 600px cap on large screens, while always leaving room for the terminal above.
  const computeMaxHeight = useCallback((): number => {
    const container = boxRef.current?.closest('.entity-view-content') as HTMLElement | null;
    const avail = container?.clientHeight ?? window.innerHeight;
    const box = boxRef.current;
    const ta = textareaRef.current;
    const chrome = box && ta ? Math.max(0, box.offsetHeight - ta.offsetHeight) : 90; // toolbar/buttons around the textarea
    const TERMINAL_MIN = 160; // keep at least this much terminal visible
    return Math.max(120, Math.min(PROMPT_MAX_HEIGHT, Math.round(avail - TERMINAL_MIN - chrome)));
  }, []);

  // Size the textarea. In auto mode (manualHeight === null) grow to fit content
  // between the configured floor and the cap. In manual mode use the dragged
  // height exactly — content taller than it SCROLLS (overflow-y:auto), so a drag
  // can shrink the box below its content.
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    const cap = computeMaxHeight();
    if (manualHeight != null) {
      ta.style.height = `${Math.max(40, Math.min(manualHeight, cap))}px`;
      return;
    }
    ta.style.height = 'auto';
    const scrollHeight = ta.scrollHeight;
    ta.style.height = `${Math.max(minHeight, Math.min(scrollHeight, cap))}px`;
  }, [text, minHeight, manualHeight, computeMaxHeight]);

  // Focus the prompt box when switching to / opening a session tab
  useEffect(() => {
    const id = setTimeout(() => textareaRef.current?.focus(), 60);
    return () => clearTimeout(id);
  }, [sessionId]);

  // Clean up debounce timer on unmount
  useEffect(() => {
    return () => {
      if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
    };
  }, []);

  // History action handler
  const handleHistoryAction = useCallback((action: string, entry: HistoryEntry) => {
    setShowHistory(false);
    if (action === 'edit') {
      setText(entry.content);
      sessionDrafts.set(sessionId, entry.content);
      persistDraft(sessionId, entry.content);
      textareaRef.current?.focus();
    } else if (action === 'resend') {
      executeCommand('prompt.send', { sessionId, text: entry.content }, {
        onFailure: 'toast', toastFn: showToast,
      });
    }
  }, [sessionId, showToast]);

  // Apply the per-session reminder to an outgoing prompt, advancing the send count
  // and auto-disabling a 'once' reminder after it fires. Returns the wrapped text
  // (unchanged when the reminder doesn't fire). History/draft keep the RAW text.
  const wrapOutgoing = useCallback((raw: string): string => {
    const before = sessionSendCounts.get(sessionId) ?? 0;
    const { text: wrapped, disableAfter } = applyReminder(raw, reminder, before);
    sessionSendCounts.set(sessionId, before + 1);
    if (disableAfter && reminder) updateReminder({ ...reminder, enabled: false });
    return wrapped;
  }, [sessionId, reminder, updateReminder]);

  // ── Prompt library (saved-prompts repository) ────────────────────────────────
  // The store + CRUD live in scripts/prompts/prompt_library.py (external ground
  // truth); the app is a thin wrapper over the prompt.library.* bus commands, which
  // return the full current list so one round-trip refreshes everything. No copy in
  // appState. Re-listed on every panel open so hand-edits / other callers show up.
  const refreshLibrary = useCallback(async () => {
    const r = await executeCommand<{ prompts: SavedPrompt[] }>('prompt.library.list', {}, { onFailure: 'silent' });
    if (r.ok && r.data) setSavedPrompts(r.data.prompts);
  }, []);
  const saveCurrentPrompt = useCallback(async (title: string, tag?: string) => {
    if (!text.trim()) return;
    const r = await executeCommand<{ prompts: SavedPrompt[] }>('prompt.library.save',
      { title, body: text, ...(tag ? { tag } : {}) }, { onFailure: 'toast', toastFn: showToast });
    if (r.ok && r.data) { setSavedPrompts(r.data.prompts); showToast(`Saved “${title}” to the prompt library`, 'info'); }
  }, [text, showToast]);
  const updateSavedPrompt = useCallback(async (id: string, patch: { title?: string; body?: string; tag?: string; clearTag?: boolean }) => {
    const r = await executeCommand<{ prompts: SavedPrompt[] }>('prompt.library.update',
      { id, ...patch }, { onFailure: 'toast', toastFn: showToast });
    if (r.ok && r.data) setSavedPrompts(r.data.prompts);
  }, [showToast]);
  const deleteSavedPrompt = useCallback(async (id: string) => {
    const r = await executeCommand<{ prompts: SavedPrompt[] }>('prompt.library.delete',
      { id }, { onFailure: 'toast', toastFn: showToast });
    if (r.ok && r.data) setSavedPrompts(r.data.prompts);
  }, [showToast]);
  // Refresh from the store whenever the library panel opens.
  useEffect(() => { if (showLibraryPanel) refreshLibrary(); }, [showLibraryPanel, refreshLibrary]);

  // Fire a library prompt as-is to the current target(s). Deliberately does NOT touch
  // the draft box (unlike handleSend's optimistic clear) — the box keeps whatever the
  // user was typing. Same fan-out + reminder-wrap rules as a default send.
  const deliverToTargets = useCallback(async (raw: string) => {
    const trimmed = raw.trim();
    if (!trimmed) return;
    const targets = sendTargets;
    const isDefault = targets.length === 1 && targets[0] === sessionId;
    const outgoing = isDefault ? wrapOutgoing(raw) : raw;
    let anyOk = false;
    let firstSend = true;
    for (const target of targets) {
      // Configurable pause between deliveries on a multi-recipient fan-out (0 = none).
      if (!firstSend && multiSendDelayMsRef.current > 0) await new Promise((r) => setTimeout(r, multiSendDelayMsRef.current));
      firstSend = false;
      const result = await executeCommand('prompt.send', { sessionId: target, text: outgoing, submit: autoSubmit }, {
        onFailure: 'inline', errorHandler, field: 'prompt', toastFn: showToast,
      });
      if (result.ok) { anyOk = true; touchSessionActivity(target); scanSessionPromptArea(target, 700); }
    }
    if (anyOk) {
      const names = targets.map((id) => (id === sessionId ? sessionName : (getSession(id)?.display_name || id)));
      showToast(`${autoSubmit ? 'Sent' : 'Staged'} to ${names.join(', ')}`, 'info');
    } else {
      showToast('Send failed', 'error');
    }
  }, [sendTargets, sessionId, wrapOutgoing, autoSubmit, errorHandler, showToast, sessionName, getSession]);

  const handleSend = useCallback(async () => {
    const trimmed = text.trim();
    if (!trimmed) return;

    // ── !-command registry ──────────────────────────────────────────────
    // A prompt whose first word is a known !-command is a LOCAL Prompt Box action,
    // not text sent to the CLI. Unknown !… text falls through and is sent normally,
    // so you can still send a prompt that happens to start with '!'.
    if (trimmed.startsWith('!')) {
      const [rawCmd, ...rest] = trimmed.slice(1).split(/\s+/);
      const cmd = rawCmd.toLowerCase();
      const arg = rest.join(' ').trim();
      const clearDraft = () => {
        setText('');
        sessionDrafts.delete(sessionId);
        if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
        persistDraft(sessionId, '');
      };
      if (cmd === 'h' || cmd === 'history') {
        clearDraft();
        if (cliSessionId) setShowHistory(true);
        else showToast('No CLI UUID — cannot load prompt history', 'error');
        return;
      }
      if (cmd === 'shell' || cmd === 'sh') {
        clearDraft();
        executeCommand('workspace.tabs.open', {
          type: 'terminal', targetId: `terminal_${Date.now()}`, label: 'Terminal',
        }, { onFailure: 'toast', toastFn: showToast });
        showToast(
          arg
            ? 'Opened a shell terminal tab — type your command there (!shell pre-fill is coming).'
            : 'Opened a shell terminal tab.',
          'info',
        );
        return;
      }
      // Unknown !command — fall through to a normal send.
    }

    // Fan-out: picker selection ∪ @name mentions, or the current tab when none. The
    // @name markers stay inline (5c: everyone gets the full text). The per-session
    // reminder only wraps the default single-target send (each recipient has its own).
    const targets = sendTargets;
    const isDefault = targets.length === 1 && targets[0] === sessionId;
    const outgoing = isDefault ? wrapOutgoing(text) : text;

    // OPTIMISTIC CLEAR — empty the box the instant Send is pressed so the UI feels
    // immediate, instead of holding the text for the full ~1.5s delivery (3 subprocess
    // spawns + settle sleeps) and only clearing after. Restore it if EVERY target fails,
    // so a delivery failure is visible (text back + error toast) rather than silently lost.
    const restoreText = text;
    setHistory(prev => [...prev, trimmed]);
    setHistoryIndex(-1);
    draftRef.current = null;
    setText('');
    sessionDrafts.delete(sessionId);
    if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
    persistDraft(sessionId, '');

    let anyOk = false;
    let firstSend = true;
    for (const target of targets) {
      // Configurable pause between deliveries on a multi-recipient fan-out (0 = none).
      if (!firstSend && multiSendDelayMsRef.current > 0) await new Promise((r) => setTimeout(r, multiSendDelayMsRef.current));
      firstSend = false;
      const result = await executeCommand('prompt.send', { sessionId: target, text: outgoing, submit: autoSubmit }, {
        onFailure: 'inline', errorHandler, field: 'prompt', toastFn: showToast,
      });
      if (result.ok) {
        anyOk = true;
        touchSessionActivity(target);
        scanSessionPromptArea(target, 700);
      }
    }
    if (anyOk) {
      // Surface the destination whenever the send goes anywhere other than JUST the current
      // tab — a redirect (picker or a body `@name`) should never be a silent surprise.
      if (sendsOffTab) {
        const names = targets.map((id) => (id === sessionId ? sessionName : (getSession(id)?.display_name || id)));
        showToast(`${autoSubmit ? 'Sent' : 'Staged'} to ${names.join(', ')}`, 'info');
      } else if (!autoSubmit) {
        showToast('Staged to prompt area — press Enter in the terminal to submit', 'info');
      }
    } else {
      // Nothing was delivered — undo the optimistic clear so the draft isn't lost.
      setText(restoreText);
      sessionDrafts.set(sessionId, restoreText);
      persistDraft(sessionId, restoreText);
      setHistory(prev => prev.slice(0, -1));
      showToast('Send failed — text restored to the box', 'error');
    }
  }, [text, sessionId, sessionName, cliSessionId, errorHandler, showToast, autoSubmit, wrapOutgoing, sendTargets, sendsOffTab, getSession]);

  // Queue (stack) the draft into the target session(s)' incoming prompt queue instead of
  // typing it into the live prompt area. Offered when a target is actively responding, so a
  // follow-up prompt can't collide with the in-flight turn — the comms daemon delivers it
  // when the session goes idle. Same optimistic-clear + restore-on-failure as Send.
  const handleQueue = useCallback(async () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const targets = sendTargets;
    const isDefault = targets.length === 1 && targets[0] === sessionId;
    const outgoing = isDefault ? wrapOutgoing(text) : text;
    const restoreText = text;
    setHistory(prev => [...prev, trimmed]);
    setHistoryIndex(-1);
    draftRef.current = null;
    setText('');
    sessionDrafts.delete(sessionId);
    if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
    persistDraft(sessionId, '');

    let anyOk = false;
    for (const target of targets) {
      const result = await executeCommand('prompt.queue', { sessionId: target, text: outgoing }, {
        onFailure: 'inline', errorHandler, field: 'prompt', toastFn: showToast,
      });
      if (result.ok) anyOk = true;
    }
    if (anyOk) {
      const names = targets.map((id) => (id === sessionId ? sessionName : (getSession(id)?.display_name || id)));
      showToast(`Queued for ${names.join(', ')} — delivers when idle`, 'info');
    } else {
      setText(restoreText);
      sessionDrafts.set(sessionId, restoreText);
      persistDraft(sessionId, restoreText);
      setHistory(prev => prev.slice(0, -1));
      showToast('Queue failed — text restored to the box', 'error');
    }
  }, [text, sessionId, sessionName, errorHandler, showToast, wrapOutgoing, sendTargets, getSession]);

  // Quick-react nudge: send a canned prompt and submit it, independent of the draft
  // (the textarea's content is left untouched). Always submits — it's an explicit
  // one-tap send — even when the auto-submit toggle is off.
  const handleNudge = useCallback(async (nudgeText: string) => {
    // A nudge is a one-tap send to the session you're looking at. Honor an explicit picker
    // selection, but do NOT pull `@name` mentions out of the (unsent) draft — those belong to
    // the draft, not to a canned quick-react.
    const targets = recipients.length ? recipients : [sessionId];
    const isDefault = recipients.length === 0;
    const outgoing = isDefault ? wrapOutgoing(nudgeText) : nudgeText;
    let anyOk = false;
    let firstSend = true;
    for (const target of targets) {
      if (!firstSend && multiSendDelayMsRef.current > 0) await new Promise((r) => setTimeout(r, multiSendDelayMsRef.current));
      firstSend = false;
      const result = await executeCommand('prompt.send', { sessionId: target, text: outgoing, submit: true }, {
        onFailure: 'inline', errorHandler, field: 'prompt', toastFn: showToast,
      });
      if (result.ok) { anyOk = true; touchSessionActivity(target); scanSessionPromptArea(target, 700); }
    }
    if (anyOk) {
      setHistory((prev) => [...prev, nudgeText]);
      setHistoryIndex(-1);
    }
  }, [sessionId, errorHandler, showToast, wrapOutgoing, recipients]);

  // ── File/image attach (todo_0356) ──────────────────────────────────────
  // Insert a snippet at the textarea cursor and keep draft state in sync.
  const insertAtCursor = useCallback((snippet: string) => {
    const ta = textareaRef.current;
    let next: string;
    if (ta && typeof ta.selectionStart === 'number') {
      const s = ta.selectionStart, e = ta.selectionEnd;
      next = text.slice(0, s) + snippet + text.slice(e);
      requestAnimationFrame(() => {
        ta.focus();
        const pos = s + snippet.length;
        ta.setSelectionRange(pos, pos);
      });
    } else {
      next = text + snippet;
    }
    setText(next);
    sessionDrafts.set(sessionId, next);
    persistDraft(sessionId, next);
  }, [text, sessionId]);

  // 📎 → native file picker → insert `@path` mentions (Claude Code reads them inline).
  const handleAttach = useCallback(async () => {
    try {
      const paths = await window.uai.dialog?.showOpenFile?.();
      if (!paths || !paths.length) return;
      insertAtCursor(paths.map((p) => `@${p}`).join('\n') + ' ');
    } catch {
      showToast('Could not open the file picker', 'error');
    }
  }, [insertAtCursor, showToast]);

  // Paste a clipboard image → save to temp → insert its `@path`. Text pastes fall
  // through to the textarea's default handling.
  const handlePaste = useCallback(async (e: React.ClipboardEvent) => {
    const dt = e.clipboardData;
    if (!dt) return;
    // Image paste → save to a temp PNG and insert its @path.
    if (Array.from(dt.items).some((it) => it.type.startsWith('image/'))) {
      e.preventDefault();
      try {
        const p = await window.uai.clipboard.saveImageToTemp();
        if (p) insertAtCursor(`@${p} `);
        else showToast('No image found in the clipboard', 'info');
      } catch {
        showToast('Could not save the pasted image', 'error');
      }
      return;
    }
    // Filepath paste → auto-prefix '@' so the CLI reads the file(s) inline. Handles a
    // single path OR several at once (newline-separated, e.g. Finder "Copy as Pathname"
    // of multiple files), prefixing EACH. Multiple files stay NEWLINE-separated (one @path
    // per line) — a space separator merged them into one visual blob. Ordinary text pastes
    // normally.
    const txt = dt.getData('text/plain');
    const mentions = txt ? filepathMentions(txt) : null;
    if (mentions) {
      e.preventDefault();
      insertAtCursor(mentions.join('\n') + ' ');
    }
  }, [insertAtCursor, showToast]);

  // Cmd+Enter → send; Up/Down arrow → history navigation
  const handleKeyDown = useCallback(async (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      handleSend();
      return;
    }

    // Cmd/Ctrl+Shift+V → paste UNWRAPPED: collapse single newlines (hard-wrap
    // artifacts) to spaces while KEEPING paragraph breaks. For prose copied from a PDF
    // or a narrow pane where the line breaks are wrapping, not content. Explicit gesture
    // (never auto-guessed) so intentional multi-line pastes are untouched.
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'v') {
      e.preventDefault();
      try {
        const raw = await navigator.clipboard.readText();
        if (raw) insertAtCursor(unwrapHardBreaks(raw));
      } catch { showToast('Could not read the clipboard', 'error'); }
      return;
    }

    // @-autocomplete: navigate/select/dismiss while the dropdown is open (before the
    // history arrows so ↑/↓ move through suggestions, not history).
    if (mention.handleKeyDown(e)) return;

    // Tab indents inside the box instead of moving focus out. 4 SPACES, not a literal
    // \t — the draft is delivered to the CLI via send-keys, and a real tab there can
    // trigger tab-completion/menus in the target terminal. Shift+Tab outdents. Block-
    // aware for multi-line selections; falls through to the @-popover's Tab (above).
    if (e.key === 'Tab') {
      const ta = textareaRef.current;
      if (!ta) return;
      e.preventDefault();
      const UNIT = '    ';
      const val = text;
      const s = ta.selectionStart ?? val.length;
      const en = ta.selectionEnd ?? val.length;
      const selHasNL = val.slice(s, en).includes('\n');

      // Simple caret indent (or replace a within-line selection) → reuse insertAtCursor.
      if (!e.shiftKey && !selHasNL) { insertAtCursor(UNIT); return; }

      // Block indent/outdent: operate on every full line the selection touches.
      const lineStart = val.lastIndexOf('\n', s - 1) + 1;
      let lineEnd = val.indexOf('\n', en);
      if (lineEnd === -1) lineEnd = val.length;
      const lines = val.slice(lineStart, lineEnd).split('\n');
      let deltaFirst = 0, deltaTotal = 0;
      const out = lines.map((ln, i) => {
        if (e.shiftKey) {
          const removed = (ln.match(/^ {1,4}/)?.[0].length) ?? 0;
          if (i === 0) deltaFirst = -removed;
          deltaTotal -= removed;
          return ln.slice(removed);
        }
        if (i === 0) deltaFirst = UNIT.length;
        deltaTotal += UNIT.length;
        return UNIT + ln;
      });
      const next = val.slice(0, lineStart) + out.join('\n') + val.slice(lineEnd);
      setText(next);
      sessionDrafts.set(sessionId, next);
      persistDraft(sessionId, next);
      requestAnimationFrame(() => {
        ta.focus();
        ta.setSelectionRange(Math.max(lineStart, s + deltaFirst), en + deltaTotal);
      });
      return;
    }

    // Up Arrow — navigate to older history entry (only when cursor is at start)
    if (e.key === 'ArrowUp' && history.length > 0) {
      const ta = textareaRef.current;
      if (ta && ta.selectionStart === 0 && ta.selectionEnd === 0) {
        e.preventDefault();
        if (historyIndex === -1) {
          // Entering history mode — save current text as draft
          draftRef.current = text;
          const newIdx = history.length - 1;
          setHistoryIndex(newIdx);
          setText(history[newIdx]);
          sessionDrafts.set(sessionId, history[newIdx]);
        } else if (historyIndex > 0) {
          const newIdx = historyIndex - 1;
          setHistoryIndex(newIdx);
          setText(history[newIdx]);
          sessionDrafts.set(sessionId, history[newIdx]);
        }
      }
      return;
    }

    // Down Arrow — navigate to newer history entry (only when cursor is at end)
    if (e.key === 'ArrowDown' && historyIndex !== -1) {
      const ta = textareaRef.current;
      if (ta && ta.selectionStart === ta.value.length && ta.selectionEnd === ta.value.length) {
        e.preventDefault();
        if (historyIndex < history.length - 1) {
          const newIdx = historyIndex + 1;
          setHistoryIndex(newIdx);
          setText(history[newIdx]);
          sessionDrafts.set(sessionId, history[newIdx]);
        } else {
          // Past the newest entry — restore draft
          setHistoryIndex(-1);
          const draft = draftRef.current ?? '';
          draftRef.current = null;
          setText(draft);
          sessionDrafts.set(sessionId, draft);
        }
      }
      return;
    }
  }, [handleSend, history, historyIndex, text, sessionId, mention, insertAtCursor]);

  // Resize handle drag — sets an EXPLICIT manual height (either direction). Start
  // from the box's current on-screen height so the drag is continuous whether we
  // were in auto or manual mode.
  const handleResizeMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = true;
    const startY = e.clientY;
    const startHeight = textareaRef.current?.offsetHeight ?? manualHeight ?? minHeight;
    const cap = computeMaxHeight();
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';

    const onMouseMove = (ev: MouseEvent) => {
      if (!draggingRef.current) return;
      const delta = startY - ev.clientY;
      setManualHeight(Math.max(40, Math.min(startHeight + delta, cap)));
    };

    const onMouseUp = () => {
      draggingRef.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  }, [minHeight, manualHeight, computeMaxHeight]);

  // Double-click the resize bar → clear the manual height and return to auto-grow
  // mode (box fits its content between the configured floor and the cap).
  const handleResizeDoubleClick = useCallback(() => {
    setManualHeight(null);
  }, []);

  // The config popover and quick-actions flyout open UPWARD from the prompt box, but
  // the prompt box's ancestor (.entity-view-content) has overflow:hidden, which was
  // CLIPPING them at the content top — under the Center Pane title bar. Render them
  // position:fixed anchored to the prompt box so they escape the clip and float on top.
  const popoverAnchorStyle = (): CSSProperties => {
    const r = boxRef.current?.getBoundingClientRect();
    if (!r) return {};
    return { position: 'fixed', left: r.left + 8, right: 'auto', top: 'auto', bottom: window.innerHeight - r.top + 6, zIndex: 1000 };
  };

  return (
    <div className="promptbox" ref={boxRef}>
      <div className="promptbox-resize-handle" onMouseDown={handleResizeMouseDown} onDoubleClick={handleResizeDoubleClick} title="Drag to resize · double-click to fit" />
      {showHistory && cliSessionId && (
        <HistoryPanel
          cliSessionId={cliSessionId}
          onDismiss={() => { setShowHistory(false); textareaRef.current?.focus(); }}
          onAction={handleHistoryAction}
        />
      )}
      {showConfig && (
        <PromptBoxConfigurator
          autoSubmit={autoSubmit}
          onToggleAutoSubmit={toggleAutoSubmit}
          showAttach={showAttach}
          onToggleShowAttach={toggleShowAttach}
          showLibrary={showLibrary}
          onToggleShowLibrary={toggleShowLibrary}
          quickNudges={quickNudges}
          onQuickNudgesChange={updateQuickNudges}
          quickNudgeColumns={quickNudgeColumns}
          onQuickNudgeColumnsChange={updateQuickNudgeColumns}
          defaultHeightLines={defaultHeightLines}
          onDefaultHeightLinesChange={updateDefaultHeightLines}
          multiSendDelaySec={multiSendDelaySec}
          onMultiSendDelayChange={updateMultiSendDelay}
          sessionName={sessionName}
          reminder={reminder}
          onReminderChange={updateReminder}
          anchorStyle={popoverAnchorStyle()}
          onClose={() => setShowConfig(false)}
        />
      )}
      {showQuickActions && quickNudges.length > 0 && (
        <div className="promptbox-nudges-popover" ref={quickActionsRef} role="menu" aria-label="Quick Actions" style={popoverAnchorStyle()}>
          <div className="promptbox-nudges-popover-head">
            <span className="promptbox-nudges-popover-title">{'⚡'} Quick Actions</span>
            <button
              className="promptbox-nudges-popover-edit"
              onClick={() => { setShowQuickActions(false); setShowConfig(true); }}
              title="Edit quick actions"
            >
              {'⚙'} Edit
            </button>
          </div>
          <div
            className="promptbox-nudges"
            style={{ gridTemplateColumns: `repeat(${quickNudgeColumns}, minmax(0, 1fr))` }}
          >
            {quickNudges.map((n, i) => (
              <button
                key={i}
                className="promptbox-nudge"
                onClick={() => handleNudge(n.text)}
                title={`Send "${n.text}"`}
              >
                {n.label}
              </button>
            ))}
          </div>
        </div>
      )}
      {showRecipientPicker && (
        <RecipientPicker
          targets={mentionTargets}
          getSession={getSession}
          selected={recipients}
          currentSessionId={sessionId}
          onChange={setRecipients}
          onClose={() => setShowRecipientPicker(false)}
          anchorStyle={popoverAnchorStyle()}
        />
      )}
      {showLibraryPanel && (
        <PromptLibraryPopover
          prompts={savedPrompts}
          draft={text}
          autoSubmit={autoSubmit}
          onInsert={(body) => insertAtCursor(body)}
          onSend={(body) => deliverToTargets(body)}
          onSave={(title, tag) => saveCurrentPrompt(title, tag)}
          onUpdate={(id, patch) => updateSavedPrompt(id, patch)}
          onDelete={(id) => deleteSavedPrompt(id)}
          anchorStyle={popoverAnchorStyle()}
          onClose={() => setShowLibraryPanel(false)}
        />
      )}
      {showRewrite && (
        <PromptRewriteDialog
          initialText={text}
          prompts={savedPrompts}
          onRefreshLibrary={refreshLibrary}
          onApply={(rewritten) => {
            setText(rewritten);
            sessionDrafts.set(sessionId, rewritten);
            persistDraft(sessionId, rewritten);
            setShowRewrite(false);
            requestAnimationFrame(() => textareaRef.current?.focus());
          }}
          onClose={() => setShowRewrite(false)}
        />
      )}
      <MentionPopover state={mention} />
      <div className="promptbox-header">
        <div
          className="promptbox-recipients"
          ref={recipientChipRef}
          onClick={() => setShowRecipientPicker((v) => !v)}
          title="Choose recipient(s) \u2014 defaults to this tab"
        >
          <span className="promptbox-recipients-arrow">{'\u2192'}</span>
          <span className={`promptbox-recipients-label${sendsOffTab ? ' offtab' : ''}`}>
            {sendTargets.map((id) => (id === sessionId ? sessionName : (getSession(id)?.display_name || id))).join(', ')}
          </span>
          {recipients.length > 0 && (
            <span
              className="promptbox-recipients-reset"
              onClick={(e) => { e.stopPropagation(); setRecipients([]); }}
              title="Clear picker selection (reset to current tab)"
            >{'\u21ba'}</span>
          )}
        </div>
        <span className="promptbox-hint">Cmd+Enter to {autoSubmit ? 'send' : 'stage'} {'\u00b7'} {'\u2191\u2193'} history {'\u00b7'} !h history {'\u00b7'} !shell</span>
      </div>
      {reminderHasContent(reminder) && reminder && (
        <div
          className="promptbox-reminder-strip"
          onClick={() => setShowConfig(true)}
          title="A reminder wraps your prompts to this session. Click to edit."
        >
          <span className="promptbox-reminder-icon">{'\u27f3'}</span>
          <span className="promptbox-reminder-cadence">{reminderCadenceLabel(reminder)}</span>
          {reminder.prepend && reminder.prepend.trim() && (
            <span className="promptbox-reminder-part">{'\u25b2'} {reminderSnippet(reminder.prepend)}</span>
          )}
          {reminder.append && reminder.append.trim() && (
            <span className="promptbox-reminder-part">{'\u25bc'} {reminderSnippet(reminder.append)}</span>
          )}
        </div>
      )}
      <div className="promptbox-body">
        {/* Left control pane: Send at top, quick on/off toggles, config opener */}
        <div className="promptbox-controls">
          <button
            className="promptbox-send"
            onClick={handleSend}
            disabled={!text.trim()}
            title={autoSubmit ? 'Send — types the prompt and presses Enter (Cmd+Enter)' : 'Stage — types the prompt into the CLI prompt area without submitting (Cmd+Enter)'}
          >
            {autoSubmit ? 'Send' : 'Stage'}
          </button>
          {anyTargetBusy && (
            <button
              className="promptbox-queue"
              onClick={handleQueue}
              disabled={!text.trim()}
              title="Session is responding — stack this prompt into its incoming queue; it delivers when the session next goes idle (instead of typing into the live prompt)."
            >
              {'⧉'} Queue
            </button>
          )}
          <label
            className="promptbox-toggle"
            title="Auto-submit: Send presses Enter for you. Off = stage the text into the CLI prompt area for you to review and submit."
          >
            <input type="checkbox" checked={autoSubmit} onChange={toggleAutoSubmit} />
            <span>auto-submit</span>
          </label>
          {/* Quick-react actions: one-tap canned sends (always submit). The trigger
              opens a roomy flyout popover (rendered at the promptbox root, below) so
              the configurable multi-column grid has real space — not cramped in this
              narrow pane. Fully configurable (label/text/order/columns) via Config. */}
          {/* Compact utility buttons pair up 2-per-row instead of stacking. */}
          <div className="promptbox-controls-grid">
            {quickNudges.length > 0 && (
              <button
                className={`promptbox-nudges-trigger${showQuickActions ? ' is-open' : ''}`}
                onClick={() => setShowQuickActions((v) => !v)}
                title="Quick Actions — one-tap canned sends"
              >
                {'⚡'} QA
              </button>
            )}
            {showLibrary && (
              <button
                className={`promptbox-library${showLibraryPanel ? ' is-open' : ''}`}
                onClick={() => setShowLibraryPanel((v) => !v)}
                title="Prompt Library — insert or send a saved prompt, or save the current draft"
              >
                {'🔖'} Lib
              </button>
            )}
            {showAttach && (
              <button
                className="promptbox-attach"
                onClick={handleAttach}
                title="Attach a file or image — inserts an @path the CLI reads (or paste an image)"
              >
                {'📎'} Attach
              </button>
            )}
            <button
              className={`promptbox-rewrite${showRewrite ? ' is-open' : ''}`}
              onClick={() => setShowRewrite(true)}
              disabled={!text.trim()}
              title="AI Re-Write — improve this prompt with an AI, guided by your instructions"
            >
              {'✨'} Rewrite
            </button>
          </div>
          <button
            className="promptbox-config"
            onClick={() => setShowConfig((v) => !v)}
            title="Prompt Box settings"
          >
            {'⚙'} Config
          </button>
        </div>
        <div className="promptbox-input-row">
          <textarea
            ref={textareaRef}
            className="promptbox-textarea"
            value={text}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            onClick={(e) => mention.sync(e.currentTarget.value, e.currentTarget.selectionStart ?? 0)}
            onBlur={() => setTimeout(() => mention.close(), 150)}
            placeholder="✦ Type your prompt here — Cmd+Enter to send"
            rows={1}
            spellCheck={true}
            style={{ minHeight: '40px' }}
          />
        </div>
      </div>
    </div>
  );
}
