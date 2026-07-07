# Visual Test Findings — 2026-05-14

**Source:** PianoMan hands-on testing of packaged UAI build
**Build:** Post data-refresh, 456 sessions, 17 briefs
**Resolution pass:** 2026-05-21 (Solstice session, v0.9.3+ production deployment)

## Data / Functionality Issues

1. **Most sessions not seen as live, even new ones** — Session liveness detection is broken or not matching tmux sessions to session records. New sessions created through the app also show as non-live. **[FIXED 2026-05-21]** Root cause: subprocess calls used devTree AI_ROOT instead of production path. Fixed with `getAiRootMain()` pattern and session-aware tmux server resolution (`_resolve_substrate_for_session()`).

2. **New session only creates basic Claude** — No UI for selecting Gemini, Codex, or custom session types. The "+" buttons exist but may only wire to claude_cli. **[OPEN]**

3. **No transcript view for stopped sessions** — Stopped sessions should still show their transcript history. Currently shows nothing or an error. **[FIXED 2026-05-21]** Transcript tab type and viewer working.

4. **Every keypress into prompt area submitted as separate entry** — Input handling bug. Each character dispatches individually instead of buffering until Enter/Cmd+Enter. **[FIXED 2026-05-21]** Extracted `handleSend()`, added Send button, Cmd+Enter submits.

5. **No Prompt Box** — The prompt box component may not be rendering or is missing from the current layout. **[FIXED 2026-05-21]** PromptBox rendering with Send button.

6. **Projects have no context menu and clicking does nothing** — ProjectCard click handler not wired. No open-as-tab, no context menu. **[OPEN]**

7. **Not all session tabs show Memorex button** — Inconsistent terminal pane headers across tabs. **[FIXED 2026-05-21]** TerminalFormatOverlay ported from UCI production, consistent across all session tabs.

8. **Session tabs show inconsistent title bars** — Some tabs have full headers, others don't. **[FIXED 2026-05-21]** SessionTitleBar standardized.

9. **No button to show transcript** — No explicit way to open a transcript view for a session. **[FIXED 2026-05-21]** Transcript toggle button in SessionTitleBar, shows active state.

10. **No Tab Groups?** — Group tab bracket rendering from 2D may not be working or visible. **[OPEN]** Not verified in production build.

## Memorex Issues

4. **Memorex not finding responses and doesn't indent text correctly** — Parser may be failing on some transcript formats. Text layout needs indentation. **[FIXED 2026-05-21]** TerminalFormatOverlay ported from UCI production — scrollback-based parsing with Unicode marker classification.

12. **Memorex section colors don't match pill colors** — Color mapping between filter pills and block type backgrounds is inconsistent. **[FIXED 2026-05-21]** Production TerminalFormatOverlay has consistent color mapping.

5. **Memorex pills should be to the right** — Currently left-aligned, should be right-aligned in the header. **[OPEN]** Verify in current build.

## Layout / UX Issues

6. **Panel/Drawer handles need more contrast** — Resize handles for bottom panel and right panel are too subtle. Need greater visual presence. **[OPEN]**

7. **Right panel close should stay on the opening bar** — Close button should be on the toggle bar (collapsed state), with triangle pointing outward. Not inside the panel. **[OPEN]**

8. **Top bars (Tab bar + Title bar) should extend over Right Panel** — Right panel should start below the title bar, not alongside it. Shell-level bars are full-width. **[PARTIALLY FIXED 2026-05-21]** Title bar padding increased, tab bar sizing improved.

10. **Recent sessions list in lower half of Navigator regardless of tab** — A persistent "recent sessions" section should appear at the bottom of the left panel on all tabs (Sessions, Groups, Briefs, Teams, Projects). **[OPEN]**

11. **Recent sessions should be smaller, show last activity/time ago, ctx %, colored by platform** — Compact card format with platform-colored icon, relative time, context percentage. **[PARTIALLY FIXED 2026-05-21]** SessionCardVisual now shows tracking_id, turns count, ctx% with color coding, platform badge as colored pill.

16. **Card sizes inconsistent** — Projects, Teams, Groups, Sessions, Briefs cards should have similar visual weight/sizing. **[OPEN]**
