/**
 * CardRichTooltip — hover tooltip showing detailed card info.
 *
 * Renders via createPortal to document.body, positioned above the card.
 * Stays open when mouse moves onto the tooltip itself.
 * Shows type-specific fields via type narrowing on AnyCard.
 */

import { createPortal } from 'react-dom';
import type { BaseCard, SessionCard, BriefCard, ProjectCard, FolderCard } from '@uai/shared/cards';
import { isSessionCard, isBriefCard, isProjectCard, isFolderCard } from '@uai/shared/cards';

export type TooltipPosition = 'above' | 'right';

interface CardRichTooltipProps {
  card: BaseCard;
  cardRect: DOMRect;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  position?: TooltipPosition;
}

const STATUS_CLASSES: Record<string, string> = {
  running: 'crt-status-running',
  idle: 'crt-status-idle',
  stopped: 'crt-status-stopped',
  exited: 'crt-status-stopped',
  archived: 'crt-status-archived',
};

const PLATFORM_LABELS: Record<string, string> = {
  claude_cli: 'Claude',
  codex_cli: 'Codex',
  gemini_cli: 'Gemini',
};

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-blue)',
};

function abbreviatePath(p: string): string {
  const home = '$HOME';
  return p.startsWith(home) ? '~' + p.slice(home.length) : p;
}

function Row({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
  return (
    <div className="crt-row">
      <span className="crt-label">{label}</span>
      <span className="crt-value">{children}</span>
    </div>
  );
}

function SessionTooltipFields({ card }: { card: SessionCard }): JSX.Element {
  const statusClass = STATUS_CLASSES[card.process_status] || '';
  return (
    <>
      <Row label="Status"><span className={statusClass}>{card.process_status}</span></Row>
      <Row label="Platform"><span style={{ color: PLATFORM_COLORS[card.platform] }}>{PLATFORM_LABELS[card.platform] || card.platform}</span></Row>
      {card.roles && card.roles.length > 0 && <Row label="Role">{card.roles[0]}</Row>}
      <Row label="Tracking"><span className="crt-mono crt-selectable">{card.tracking_id}</span></Row>
      {card.cli_session_id && <Row label="UUID"><span className="crt-mono crt-selectable">{card.cli_session_id}</span></Row>}
      {card.project_dir && <Row label="Project"><span className="crt-mono crt-selectable">{abbreviatePath(card.project_dir)}</span></Row>}
      {card.context_percent != null && card.context_percent > 0 && (
        <Row label="Context">
          <span className={card.context_percent >= 80 ? 'crt-ctx-high' : card.context_percent >= 60 ? 'crt-ctx-medium' : 'crt-ctx-ok'}>
            {card.context_percent}% used
          </span>
        </Row>
      )}
      {card.exchange_count != null && card.exchange_count > 0 && <Row label="Turns">{card.exchange_count}</Row>}
      {card.tags.length > 0 && (
        <Row label="Tags">
          <span className="crt-tags">{card.tags.map(t => <span key={t} className="crt-tag">{t}</span>)}</span>
        </Row>
      )}
    </>
  );
}

function BriefTooltipFields({ card }: { card: BriefCard }): JSX.Element {
  return (
    <>
      <Row label="Status"><span className={`crt-status-${card.status === 'active' ? 'running' : 'stopped'}`}>{card.status}</span></Row>
      {card.description && <Row label="Desc">{card.description}</Row>}
      {card.file_size != null && <Row label="Size">{Math.round(card.file_size / 1024)}KB</Row>}
      <Row label="Path"><span className="crt-mono crt-selectable">{abbreviatePath(card.brief_path)}</span></Row>
    </>
  );
}

function ProjectTooltipFields({ card }: { card: ProjectCard }): JSX.Element {
  return (
    <>
      <Row label="Status"><span className={`crt-status-${card.git_status === 'clean' ? 'running' : card.git_status === 'dirty' ? 'idle' : 'stopped'}`}>{card.git_status}</span></Row>
      <Row label="Dir"><span className="crt-mono crt-selectable">{abbreviatePath(card.working_dir)}</span></Row>
      {card.branch && <Row label="Branch"><span className="crt-mono">{card.branch}</span></Row>}
      {card.session_count != null && card.session_count > 0 && <Row label="Sessions">{card.session_count}</Row>}
    </>
  );
}

function ContainerTooltipFields({ card }: { card: FolderCard }): JSX.Element {
  const memberCount = card.container.children.length;
  const subCount = card.container.sub_containers.length;
  return (
    <>
      <Row label="Type">Folder (exclusive)</Row>
      <Row label="Items">{memberCount}</Row>
      {subCount > 0 && <Row label="Sub">{subCount} sub-containers</Row>}
    </>
  );
}

export default function CardRichTooltip({ card, cardRect, onMouseEnter, onMouseLeave, position = 'above' }: CardRichTooltipProps): JSX.Element {
  const posStyle: React.CSSProperties = position === 'right'
    ? {
        position: 'fixed',
        top: Math.max(8, cardRect.top),
        left: cardRect.right + 8,
        minWidth: 320,
        maxWidth: 600,
      }
    : {
        position: 'fixed',
        bottom: window.innerHeight - cardRect.top - 2,
        left: Math.max(8, cardRect.left - cardRect.width * 0.125),
        width: cardRect.width * 1.25,
        minWidth: 320,
        maxWidth: 600,
      };
  return createPortal(
    <div
      className="card-rich-tooltip"
      style={posStyle}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="crt-row crt-name">{card.display_name}</div>

      {isSessionCard(card) && <SessionTooltipFields card={card} />}
      {isBriefCard(card) && <BriefTooltipFields card={card} />}
      {isProjectCard(card) && <ProjectTooltipFields card={card} />}
      {isFolderCard(card) && <ContainerTooltipFields card={card} />}

      <Row label="Created">{card.created_at ? new Date(card.created_at).toLocaleString() : 'unknown'}</Row>
      {card.last_activity && card.last_activity !== card.created_at && (
        <Row label="Updated">{new Date(card.last_activity).toLocaleString()}</Row>
      )}
    </div>,
    document.body
  );
}
