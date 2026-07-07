/**
 * prompt-mentions — parse `@target` recipient mentions out of Prompt Box text.
 *
 * A `@target` resolves to one or more sessions:
 *   - `@<sessionDisplayName>`  → that session
 *   - `@<projectName>`         → every session whose working dir matches the project
 *   - `@<teamName>`            → the team's member sessions
 * so `@team` / `@project` fan out to their members automatically.
 *
 * Grammar (confirmed with PianoMan):
 *   - `@` + `/` or `~`  → a FILE path (`@/x`, `@~/x`) — NOT a recipient (left literal).
 *   - `@` + a word matching a known session/team/project name → recipient(s).
 *   - anything else → literal text.
 *
 * The `@name` markers are NOT stripped from the delivered text — every recipient gets
 * the full prompt with all markers intact, so each can see the parts addressed to them.
 */

/** Tracking-ids of sessions @-mentioned in `text`, resolving session/team/project
 *  names. Case-insensitive. `nameToSessions` maps lowercased name → session tracking_ids
 *  (one for a session, many for a team/project). */
export function parseSessionMentions(text: string, nameToSessions: Map<string, string[]>): string[] {
  const ids = new Set<string>();
  // `@"quoted name"` (may contain spaces) OR `@word`, at start-of-string or after
  // whitespace. The bare-word form requires an alphanumeric right after `@`, so
  // `@/path` and `@~/path` (files) never match.
  const re = /(?:^|\s)@(?:"([^"]+)"|([A-Za-z0-9][A-Za-z0-9_-]*))/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const key = (m[1] ?? m[2]).toLowerCase();
    const members = nameToSessions.get(key);
    if (members) for (const id of members) ids.add(id);
  }
  return [...ids];
}
