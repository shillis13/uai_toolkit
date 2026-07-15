import { useState, useEffect, useRef } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, MutableRefObject } from 'react';
import type { SavedPrompt } from '@uai/shared/types';
import { executeCommand } from '../utils/execute-command';
import { useToast } from './Toast';
import PromptLibraryPopover from './PromptLibraryPopover';

/**
 * PromptRewriteDialog — AI Re-Write. Two stacked boxes: the TOP holds instructions
 * to the AI (what to improve/change) with a Library "prompt explorer"; the BOTTOM
 * holds the prompt being rewritten (seeded from the Prompt Box). Both boxes navigate
 * their own history with ↑/↓. Rewrite sends (instruction + prompt) to the AI engine
 * (local LLM by default, Claude optional) and drops the result into the bottom box;
 * "Insert into Prompt Box" pushes the bottom text back to the composer.
 *
 * Histories are module-level so they persist across opens within the app session.
 */
const instructionHist: string[] = [];
const promptHist: string[] = [];

function pushHist(hist: string[], v: string): void {
  const t = v.trim();
  if (t && hist[hist.length - 1] !== v) hist.push(v);
}

export interface PromptRewriteDialogProps {
  initialText: string;
  prompts: SavedPrompt[];
  onRefreshLibrary: () => void;
  onApply: (text: string) => void;
  onClose: () => void;
}

export default function PromptRewriteDialog({
  initialText, prompts, onRefreshLibrary, onApply, onClose,
}: PromptRewriteDialogProps): JSX.Element {
  const [instruction, setInstruction] = useState('');
  const [promptText, setPromptText] = useState(initialText);
  const [engine, setEngine] = useState<'lllm' | 'claude'>('lllm');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showExplorer, setShowExplorer] = useState(false);
  const [instrIdx, setInstrIdx] = useState(-1);
  const [promptIdx, setPromptIdx] = useState(-1);
  const instrDraft = useRef('');
  const promptDraft = useRef(initialText);
  const instrRef = useRef<HTMLTextAreaElement>(null);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const { showToast } = useToast();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { if (showExplorer) setShowExplorer(false); else onClose(); }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, showExplorer]);

  // ↑/↓ history navigation — ↑ only when the caret is on the first line, ↓ on the
  // last line, so normal multi-line editing still moves the cursor.
  const histNav = (
    e: ReactKeyboardEvent<HTMLTextAreaElement>,
    hist: string[], value: string, setValue: (s: string) => void,
    idx: number, setIdx: (n: number) => void, draftRef: MutableRefObject<string>,
  ): void => {
    const ta = e.currentTarget;
    const atStart = ta.selectionStart === 0 && ta.selectionEnd === 0;
    const atEnd = ta.selectionStart === ta.value.length && ta.selectionEnd === ta.value.length;
    if (e.key === 'ArrowUp' && atStart && hist.length) {
      e.preventDefault();
      if (idx === -1) { draftRef.current = value; setIdx(hist.length - 1); setValue(hist[hist.length - 1]); }
      else if (idx > 0) { setIdx(idx - 1); setValue(hist[idx - 1]); }
    } else if (e.key === 'ArrowDown' && atEnd && idx !== -1) {
      e.preventDefault();
      if (idx < hist.length - 1) { setIdx(idx + 1); setValue(hist[idx + 1]); }
      else { setIdx(-1); setValue(draftRef.current); }
    }
  };

  const doRewrite = async () => {
    if (!promptText.trim() || busy) return;
    setBusy(true); setError(null);
    pushHist(instructionHist, instruction);
    pushHist(promptHist, promptText);   // pre-rewrite text stays recoverable via ↑
    setInstrIdx(-1); setPromptIdx(-1);
    const r = await executeCommand<{ text: string }>('ai.rewrite',
      { instruction, text: promptText, engine }, { onFailure: 'silent' });
    setBusy(false);
    if (r.ok && r.data?.text) {
      promptDraft.current = r.data.text;
      setPromptText(r.data.text);
      showToast('Rewritten — review below, then Insert into Prompt Box', 'info');
    } else {
      setError(r.error?.message || 'Rewrite failed.');
    }
  };

  return (
    <div className="promptbox-rw-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="promptbox-rw-dialog" role="dialog" aria-label="AI Re-Write">
        <div className="promptbox-rw-head">
          <span className="promptbox-rw-title">{'✨'} AI Re-Write</span>
          <div className="promptbox-rw-head-actions">
            <label className="promptbox-rw-engine" title="Which AI does the rewrite">
              Engine
              <select value={engine} onChange={(e) => setEngine(e.target.value as 'lllm' | 'claude')}>
                <option value="lllm">Local LLM</option>
                <option value="claude">Claude</option>
              </select>
            </label>
            <button className="promptbox-rw-close" onClick={onClose} title="Close (Esc)">{'✕'}</button>
          </div>
        </div>

        {/* Top: instructions to the AI */}
        <div className="promptbox-rw-section">
          <div className="promptbox-rw-label">
            <span>Instructions {'—'} what to improve or change</span>
            <button
              className="promptbox-rw-explore"
              onClick={() => { onRefreshLibrary(); setShowExplorer(true); }}
              title="Browse the Prompt Library and use a saved prompt as the instruction"
            >{'📚'} Library</button>
          </div>
          <textarea
            ref={instrRef}
            className="promptbox-rw-textarea promptbox-rw-instruction"
            value={instruction}
            placeholder="e.g. Make it more specific and add step-by-step structure. ↑/↓ for history."
            onChange={(e) => { setInstruction(e.target.value); setInstrIdx(-1); }}
            onKeyDown={(e) => histNav(e, instructionHist, instruction, setInstruction, instrIdx, setInstrIdx, instrDraft)}
            rows={3}
          />
        </div>

        {/* Bottom: the prompt being rewritten */}
        <div className="promptbox-rw-section promptbox-rw-section-grow">
          <div className="promptbox-rw-label"><span>Prompt {'—'} the text to rewrite {busy && <em className="promptbox-rw-busy">rewriting…</em>}</span></div>
          <textarea
            ref={promptRef}
            className="promptbox-rw-textarea promptbox-rw-prompt"
            value={promptText}
            placeholder="The prompt to improve. ↑/↓ for history (your pre-rewrite versions are kept)."
            onChange={(e) => { setPromptText(e.target.value); setPromptIdx(-1); promptDraft.current = e.target.value; }}
            onKeyDown={(e) => histNav(e, promptHist, promptText, setPromptText, promptIdx, setPromptIdx, promptDraft)}
          />
        </div>

        {error && <div className="promptbox-rw-error">{error}</div>}

        <div className="promptbox-rw-foot">
          <button className="promptbox-rw-btn primary" onClick={doRewrite} disabled={busy || !promptText.trim()}>
            {busy ? 'Rewriting…' : '✨ Rewrite'}
          </button>
          <button
            className="promptbox-rw-btn"
            onClick={() => onApply(promptText)}
            disabled={busy || !promptText.trim()}
            title="Replace the Prompt Box text with what's below"
          >Insert into Prompt Box</button>
          <button className="promptbox-rw-btn ghost" onClick={onClose}>Cancel</button>
        </div>
      </div>

      {showExplorer && (
        <PromptLibraryPopover
          browseOnly
          heading={'📚 Library — pick an instruction'}
          insertLabel="Use as the AI instruction"
          prompts={prompts}
          onInsert={(body) => {
            setInstruction((prev) => (prev.trim() ? `${prev}\n${body}` : body));
            setInstrIdx(-1);
            setShowExplorer(false);
            requestAnimationFrame(() => instrRef.current?.focus());
          }}
          anchorStyle={{ position: 'fixed', left: '50%', top: '50%', transform: 'translate(-50%, -50%)', zIndex: 1200 }}
          onClose={() => setShowExplorer(false)}
        />
      )}
    </div>
  );
}
