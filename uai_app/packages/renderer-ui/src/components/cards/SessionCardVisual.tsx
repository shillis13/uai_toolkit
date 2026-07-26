/**
 * SessionCardVisual — session-specific card rendering.
 *
 * Layout (compact/Navigator):
 *   <sessionName>                              msgs: <#msgs> [<#unread>] [pill]
 *   <createdDateTime>   [inbox: <#inboxUnread>]              ctx used: <%ctx>
 *   <lastActivity>                                                     <uri>
 *
 * All text dimmed when session is Stopped.
 * #msgs blinks when session is currently responding.
 */

import type { SessionCard } from '@uai/shared/cards';
import { SessionBadges } from '../SessionBadges';
import { SessionStateIndicator } from '../SessionStateIndicator';
import { promptBlockChip } from '../../utils/prompt-block';

function formatDateTime(iso: string): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return ''; }
}

function formatTimeAgo(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const diff = Date.now() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  } catch { return ''; }
}

function formatBytes(n?: number | null): string {
  if (n == null) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)}K`;
  return `${(n / (1024 * 1024)).toFixed(1)}M`;
}

interface SessionCardVisualProps {
  card: SessionCard;
  hasTab?: boolean;
}

export default function SessionCardVisual({ card, hasTab }: SessionCardVisualProps): JSX.Element {
  const isStopped = card.process_status !== 'running';
  const isResponding = card.activity_state === 'responding';
  const ctxClass = card.context_percent != null
    ? card.context_percent >= 80 ? 'high' : card.context_percent >= 50 ? 'medium' : ''
    : '';

  const turnCount = card.exchange_count ?? 0;
  const block = promptBlockChip(card.prompt_block);

  // Attention severity, derived from context pressure (more triggers — unread comms,
  // open-todo backlog, long-idle — land as those signals get wired onto the card).
  const ctxPct = card.context_percent;
  const attn = isStopped
    ? 'dormant'
    : ctxPct != null && ctxPct >= 85 ? 'crit'
    : ctxPct != null && ctxPct >= 70 ? 'warn'
    : 'ok';
  const attnReason = attn === 'crit'
    ? `context ${ctxPct}% — compaction imminent`
    : attn === 'warn'
    ? `context ${ctxPct}% — filling`
    : '';
  const restarts = card.restart_count ?? 0;
  const sizeStr = formatBytes(card.transcript_bytes);

  return (
    <div className={`card-meta${isStopped ? ' card-meta-stopped' : ''}${attn === 'crit' ? ' card-attn-crit' : attn === 'warn' ? ' card-attn-warn' : ''}`}>
      {/* Row 1: status + turns + pill (right) */}
      <div className="card-row">
        <span className="card-row-left">
          <SessionStateIndicator
            activityState={card.activity_state}
            processStatus={card.process_status}
            withLabel
          />
          {block && <span className="card-prompt-block" title={block.tooltip}>{block.short}</span>}
        </span>
        <span className="card-row-right">
          <span className={`card-msg-count${isResponding ? ' card-msg-blink' : ''}`}>
            Turns: {turnCount}
          </span>
          {card.identity_status && card.identity_status !== 'confirmed' && (
            <span className="card-badge draft">{card.identity_status}</span>
          )}
        </span>
      </div>

      {/* Row 2: created (left) ... ctx (right) */}
      <div className="card-row">
        <span className="card-row-left card-created">{formatDateTime(card.created_at)}</span>
        <span className="card-row-right">
          {card.context_percent != null && card.context_percent > 0 && (
            <span className={`card-ctx ${ctxClass}`}>ctx: {card.context_percent}%</span>
          )}
        </span>
      </div>

      {/* Row 3: lastActivity + shared badges (single source of truth) */}
      <div className="card-row">
        <span className="card-row-left card-last-activity">{formatTimeAgo(card.last_activity)}</span>
        <span className="card-row-right card-badges">
          <SessionBadges
            trackingId={card.tracking_id}
            lastActivity={card.last_activity}
            exchangeCount={card.exchange_count}
            hasTab={hasTab}
          />
        </span>
      </div>

      {/* Signal row: attention reason (left) + restart count and transcript size (right). */}
      {(attnReason || restarts > 0 || sizeStr) && (
        <div className="card-row card-signal-row">
          <span className={`card-row-left card-attn card-attn-${attn}`}>{attnReason}</span>
          <span className="card-row-right card-signals">
            {restarts > 0 && <span className="card-restarts" title="Session restarts">{'↻'}{restarts}</span>}
            {sizeStr && <span className="card-logsize" title="Transcript (JSONL) size">{sizeStr}</span>}
          </span>
        </div>
      )}

      {/* Row 4: URI on its own line, full width, smaller font, no wrap */}
      <div className="card-row card-uri-row">
        <span className="card-uri">uai://session/{card.tracking_id}</span>
      </div>
    </div>
  );
}
