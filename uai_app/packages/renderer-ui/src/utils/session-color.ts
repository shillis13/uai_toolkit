/**
 * session-color — stable, hash-based color assignment for session names / ids.
 *
 * Shared by PromptLogTab (prompt rows) and MessagesTab (per-sender tinting) so
 * the same session always maps to the same color across the UI.
 */

/** Stable session-name color palette — distinct hues */
// NOTE: no gold/near-gold hue here — warm gold is RESERVED for the user
// (USER_COLOR #e8c07a in MessagesTab), so the user's messages stay uniquely
// colored and never collide with a session (e.g. Git Guardian used to hash to
// #e0af68 yellow ≈ the user's gold).
export const SESSION_COLORS = [
  '#7dcfff', // cyan
  '#9ece6a', // green
  '#f7768e', // red/pink
  '#bb9af7', // purple
  '#ff9e64', // orange
  '#73daca', // teal
  '#c0caf5', // light blue
  '#ff7a93', // coral
  '#b4f9f8', // mint
  '#cfc9c2', // sand
  '#a9b1d6', // lavender
];

/** Map an arbitrary name/id to a stable color from the palette. */
export function sessionColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash + name.charCodeAt(i)) | 0;
  }
  return SESSION_COLORS[Math.abs(hash) % SESSION_COLORS.length];
}
