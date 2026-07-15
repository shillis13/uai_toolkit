Codex review: UAI terminal geometry todo_0504 (code + ① lease draft)

Scope/evidence:
- Reviewed committed geometry/reset code in `scripts/session_mgmt/lib_session_substrate.py` and `session_ops.py`.
- Reviewed current ② resize/ack implementation in `app/main/terminal.ts`, `app/main/index.ts`, `app/main/preload.ts`, `packages/renderer-ui/src/global.d.ts`, `packages/renderer-ui/src/components/TerminalPane.tsx`.
- Reviewed `docs/designs/uai_terminal_window_pin_lease.md` and Memorex reconcile sections 8-10.
- Smokes run: `session_ops.py geometry --json` -> 29 sessions, 0 manual hazards, 0 client mismatches; `session_ops.py reset-window-size --all` -> dry-run ok; UAI `npm run typecheck` -> passed.

Verdict:
- ② is the right architecture (request/ack; renderer uses `proposeDimensions`; StandaloneTerminal left immediate), but I would not treat v1.3.280 as fleet-safe yet. There are concrete lost-ack/stale-generation cases that can leave xterm stuck or mis-sized, and the hold predicate still misses the known "thinking, not streaming" repro.
- ① should not be built as written. The lease idea is sound, but the current draft's fire-and-forget `resize-window`/release path has race conditions that can leak durable manual state or ack xterm before tmux is actually resized. Build it as an owner-marked, serialized, generation-checked lease transaction coupled to the ② apply/ack path.

Findings on DONE ① audit/reset code

1. HIGH: single-session reset is ambiguous across tmux servers.
`reset_window_size_op(session=NAME, server=None)` collects all matching session names across all discovered servers and resets all of them. For a mutating recovery command, duplicate names should be a hard ambiguity unless `--server` or `--all` is explicit. Geometry can show duplicates; reset should not silently mutate multiple sessions.

2. HIGH/MED: reset success is not actually verified.
`TmuxSubstrate.reset_window_size()` ignores the `set-option -u` return code and then returns the global default from `show-options -g`, not the post-reset effective geometry for that session. If unset fails, or if `manual` is inherited globally/window-scope, the command can report `latest` or `manual` misleadingly. Fix: check return code, then call `get_window_geometry(name)` and return effective `window_size` + `override_set`; if still manual, surface why.

3. MED: explicit vs inherited/manual scope is under-modeled.
`manual_hazard = window_size == "manual"` is useful for audit, but a recovery reset should distinguish: session override manual, inherited global manual, and window/manual state from `resize-window`. Unsetting a session option cannot fix inherited global manual or a different scope. The planned lease also needs this distinction, or startup sweep may say it healed something it did not.

4. MED: tmux server discovery leaks tmux mechanics into `session_ops.py`.
`_discover_tmux_servers()` knows `/tmp/tmux-$uid` and default socket naming. Functionally okay, but if you are holding the DESIGN.md line that all tmux mechanics stay in the substrate, make this `TmuxSubstrate.discover_servers()` (or similar) and let `session_ops` orchestrate only via substrate APIs.

5. Good: the current audit path is read-only and useful.
The smoke confirmed it sweeps the live servers without mutating. The `--all` reset guard is correctly dry-run unless `--yes`; keep that explicit/manual, but do not reuse blanket `--all --yes` as an app startup primitive.

Findings on DONE ② resize/ack implementation

6. BLOCKER: xterm can get stuck because resize requests can be dropped with no ack and renderer advances `lastReq` on send.
`TerminalPane.requestResize()` updates `lastReqCols/Rows` before any ack. `resizeTerminal()` returns without ack when there is no entry, and `applyResize()` can fail but the caller still acks. If the only request for a stable container size is lost, later ResizeObserver ticks for the same proposed dims are skipped, so xterm remains at the old size until some different geometry/remount happens. Fix: every request must resolve (applied/rejected/retryable), or renderer must keep a pending target with timeout/retry and not suppress same-dim retries while unacked. Prefer both: main sends a negative/no-entry ack or renderer awaits attach before starting resize observation.

7. BLOCKER: stale timers/acks from a replaced attach can affect a new mount.
`attachTerminal()` kills/deletes an existing entry but does not clear `existing.quietTimer`. The old timer closure can later `applyResize(oldEntry)` and `ackResize(oldEntry, seq, ...)` after a remount. The renderer sequence resets per component, so a stale old ack with a high seq can be accepted by the new listener. Fix: clear old timers in the attach replacement path, make `armQuietFlush` re-check `ptyEntries.get(sessionId) === entry` before applying/acking, and include a mount/attach generation token in resize requests and acks. `sessionId + seq` is not enough.

8. HIGH: `applyResize` acks even when the PTY resize failed.
`applyResize()` catches and ignores errors; callers immediately ack. That can intentionally resize xterm after the PTY is dead/exited or refused resize. Return success/failure from `applyResize`; ack only on success or on proven same-size. On failure, detach/emit exit or negative ack and let the renderer retry/remount.

9. HIGH: the hold predicate still misses the proven not-streaming case.
Current hold is only `lastDataAt` within 1000ms. The earlier review's key requirement was activity-state aware safety: "thinking/responding but no PTY output" must still be unsafe. Otherwise a right-panel toggle during Claude thinking can still send mid-response SIGWINCH and re-open the dot-marker/drop corruption that 3c46c24c2 was preventing. Add activity_state/responding/prompt-stable gating before broad rollout.

10. MED: same-size ack is conceptually right, but only with monotonic generation.
Acking same-size without SIGWINCH is correct; clearing a pending resize when the renderer requests the current applied size is also correct as a "resize back" cancellation. But that assumes the request belongs to the current mount and arrives in order. With old-generation requests/acks, same-size can clear a newer pending resize. Generation tokens and main-side monotonic seq checks fix this.

11. MED: initial open is mostly safe, but do not rely on IPC ordering.
The initial `fitAddon.fit()` before attach is okay because it establishes the spawn size. The race is that `terminal.attach()` is invoked but not awaited before RAF/ResizeObserver requests can fire. If Electron ordering ever lets a resize beat the attach entry, it is the lost-ack/stuck case above. Safer: await `attach` before enabling ResizeObserver/RAF resize requests, or have main queue/ack resize requests received before attach completes.

12. Needed diagnostic surface before live test: expose applied state.
Right now CDP can read xterm rows, but the reviewer/tester also needs main's applied PTY rows/cols, pending target, last acked seq, hold reason, and activity_state. Otherwise a passing visual test can hide a still-mismatched tmux/window state.

Findings on PLANNED ① window-pin lease

13. BLOCKER: fire-and-forget `resize-window` breaks the lockstep invariant and races out of order.
The draft says acquire/maintain may spawn `session_ops.py` fire-and-forget. That creates a period where PTY client size != tmux window size, and worse, multiple async `resize-window` subprocesses can complete out of order: old acquire after newer maintain, old maintain after release, release before old maintain. That is exactly how a lease leaks durable manual state again. Fix: per-session serialized operation queue with generation checks; ack xterm only after the PTY resize and tmux `resize-window` have both completed (or at least been verified). If the spawn cost is 100-300ms, accept delayed visual resize or build a persistent helper; do not ack before tmux is at the target size.

14. BLOCKER: release on detach can reintroduce mid-response resize/repaint or leak via pending maintain.
`TerminalPane` detaches on tab unmount. If release resets `window-size latest` while Claude is responding and a foreign client remains or attaches, tmux can resize/repaint mid-response. Also a pending async maintain can set manual again after release. Release must be sequenced after cancelling/invalidating pending maintains, and should be quiet-gated or held through hidden-tab/responding states. At minimum: no release that can trigger a resize while activity_state is responding; no maintain may run after a release generation.

15. BLOCKER: startup sweep must be owner-marked and stale-only, not blanket reset.
Do not reset all manual sessions on all servers at UAI startup. Manual window-size can be intentional outside UAI, and multiple UAI instances/windows can exist. Add tmux user-options as the lease record, e.g. owner app pid/uuid, sessionId, generation, cols/rows, updated_at. Startup sweeps only UAI-owned leases whose owner process is dead/stale. The explicit human recovery command can keep `--all --yes`, but app startup should never blanket-reset arbitrary manual windows.

16. HIGH: acquire must be conditional on safety, not always "manual + resize-window" after attach.
Setting manual plus `resize-window` after attach is itself a tmux window resize/SIGWINCH. If the session is already responding, eager acquire can cause the corruption you are trying to prevent. Recommended: eager lease ownership is fine, but only resize to UAI target when the ② safety gate says safe. If unsafe, either pin at current tmux window size and defer the size change, or defer acquisition until quiet. Never force `resize-window` mid-response.

17. MED: multi-window sessions need an explicit assumption/guard.
`window-size` is session-scoped; `resize-window` is window-scoped. UAI sessions are probably one-window, but a fleet tool should detect/report multiple windows and either refuse to pin or target the active window with a recorded window id. Otherwise one session option can pin all windows while only resizing one.

Answers to the five open questions

1. Eager vs reactive: choose eager per attached UAI session, not reactive, because reactive detects the problem only after at least one unsafe foreign-client resize. But make it owner-marked, generation-checked, and safety-gated. Do not blanket-pin all sessions; pin only sessions UAI is actively driving.

2. `resize-window` cost/timing: the async transient is not acceptable if xterm acks before tmux window is at the same size. Couple ① into the ② transaction: request -> safety gate -> apply PTY resize + tmux resize-window in order/serialized -> verify or trust completion -> emit `resizeApplied`. If subprocess cost is too high, optimize the control path, not the invariant.

3. Startup sweep scope: UAI-owned stale leases only. A blanket reset is okay only as a manually invoked recovery with dry-run/yes guard. The app startup sweep should inspect lease owner markers and process liveness.

4. Interaction with ② hold: yes, maintain must hang off the post-quiet apply path only. Also update the hold predicate to activity_state/responding, not just recent output. No independent `resize-window` from the request path.

5. Crash residual: startup sweep + manual reset is sufficient for v1 only after owner markers and stale/dead-owner detection exist. A heartbeat/expiry is optional defense; prefer owner PID/uuid + generation first. TTL alone can misfire after sleep/debugger pauses and should not clear an apparently live owner.

Live-test approach

A single CDP-driven resize during one streaming response is necessary but not sufficient. Measure these each time:
- xterm `cols/rows` and rendered bottom rows.
- main-process applied PTY `cols/rows`, pending target, last request seq, last ack seq, hold reason.
- `session_ops.py geometry --json` for tmux window WxH, `window-size`, clients WxH.
- activity_state / prompt-stable / responding flag at request and at ack.
- scrollback integrity: no superimposed bottom rows, no off-screen dot-marker fold into previous tool section, and Memorex section/msg labeling if enabled.

Exercise at least:
1. quiet resize (applies immediately, no stuck state);
2. streaming resize (held, latest-only, no xterm local reflow until ack);
3. thinking/no-output resize (must hold; this is the repro that current code still misses);
4. rapid repeated resizes and resize-back-to-original while held;
5. same-size resize/no-op ack;
6. tab switch/remount with a pending held resize (old ack must not hit new mount);
7. detach/close/quit with pending resize and then app restart sweep;
8. PTY exit while resize pending;
9. foreign client attach at different size while UAI lease is active;
10. StandaloneTerminal resize remains immediate.

Memorex matcher sanity check

Yes: the Review-1 v1 contract still holds, and section 10 makes it stronger. The current `matchSectionsToTranscript` is exactly a blind backward type-walk: no content anchor, no uniqueness, no monotonic neighbor proof. Any overlay-vs-transcript divergence can misnumber msg#/timestamps. The direction should remain: projected visible stream, content-anchored unique matching, MERGE/join-only for real repair, residual subtraction rather than insertion, fail closed on ambiguity, and no Memorex repair until the terminal resize source fix has landed and monitoring proves residual corruption remains.
