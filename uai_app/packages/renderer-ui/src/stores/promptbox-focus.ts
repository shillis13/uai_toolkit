/**
 * PromptBox focus bus — lets other parts of the UI ask the active session's
 * PromptBox to take the cursor. Used to pull focus BACK to the Prompt Box after
 * the user submits in the raw CLI prompt area (Enter in the terminal), nudging
 * them toward composing in the box rather than the terminal.
 */

type Listener = (sessionId: string) => void;
const listeners = new Set<Listener>();

/** Ask the PromptBox for `sessionId` to focus its input. */
export function requestPromptBoxFocus(sessionId: string): void {
  for (const fn of listeners) fn(sessionId);
}

export function onPromptBoxFocusRequest(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
