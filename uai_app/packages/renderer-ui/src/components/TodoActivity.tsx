/**
 * TodoActivity — the three "worker→work" sections migrated onto the WORK item
 * (worker_pages_unification decision 4): Chat comments · Turn-links,
 * Decisions & pivots, Open questions & recommendations.
 *
 * Shared by BOTH the Work Mgr todo detail (WorkMgrPane) and the session/project/team
 * Work view (ProjectEditor), so the work item carries its Activity everywhere it's shown.
 *
 * Backing data (extracting these from chat/transcripts) isn't wired yet — rendered as
 * clearly-labeled samples so the layout is real and reviewable; each lights up when the
 * capture pipeline lands. Turns are addressable (message numbers aren't), so Turn-links
 * target turn indices.
 */

function actHash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) { h = (h << 5) - h + s.charCodeAt(i); h |= 0; }
  return h;
}

export default function TodoActivity({ name, seed }: { name: string; seed: string }): JSX.Element {
  const base = Math.abs(actHash(seed)) % 40 + 8;
  const comments = [
    { turn: base, text: `Discussed scope of "${name}" — agreed to keep the first pass minimal.` },
    { turn: base + 7, text: `Pivot: original approach dropped in favor of a simpler path.` },
  ];
  const decisions = [
    `Chose the lighter-weight implementation to avoid blocking on infra.`,
    `Deferred edge-case handling until the core flow is verified.`,
  ];
  const questions = [
    `Open: is the scope of "${name}" fully settled, or are there edge cases to confirm?`,
    `Recommendation: add a follow-up todo for test coverage once this lands.`,
  ];
  return (
    <div className="pe-activity">
      <div className="pe-activity-title">Activity <span className="pe-sample-tag">sample · capture not wired</span></div>

      <div className="pe-act-sec">
        <div className="pe-act-h">💬 Chat comments · Turn-links</div>
        {comments.map((c, i) => (
          <div key={i} className="pe-act-comment">
            <span className="pe-turn-chip" title={`Jump to Turn ${c.turn} (target not wired — affordance only)`}>Turn {c.turn} ↗</span>
            <span className="pe-act-text">{c.text}</span>
          </div>
        ))}
        <div className="pe-act-note">Comments about this todo get extracted from the chat; each links to its Turn (Turns are addressable, message numbers aren't).</div>
      </div>

      <div className="pe-act-sec">
        <div className="pe-act-h">🔀 Decisions &amp; pivots</div>
        <ul className="pe-act-list">{decisions.map((d, i) => <li key={i}>{d}</li>)}</ul>
      </div>

      <div className="pe-act-sec">
        <div className="pe-act-h">❓ Open questions &amp; recommendations</div>
        <ul className="pe-act-list">{questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
      </div>
    </div>
  );
}
