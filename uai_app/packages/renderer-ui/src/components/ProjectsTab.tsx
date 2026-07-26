/**
 * ProjectsTab — Navigator tab content showing all discovered projects.
 *
 * Groups by lifecycle status: In-Progress, Sandbox, Done, Unregistered.
 * Category (organizing dir) shown as a prefix badge on each project.
 * Click opens project in workspace tab.
 * Right-click context menu: Copy Path, Open in Tab.
 */

import { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import type { AnyCard, ProjectCard } from '@uai/shared/cards';
import { isProjectCard } from '@uai/shared/cards';
import { useCardStore } from '../stores/card-store';
import { useContextMenuDismiss } from '../hooks/use-context-menu-dismiss';
import { useClampToViewport } from '../hooks/use-clamp-to-viewport';
import { CardListView } from './cards';
import { executeCommand } from '../utils/execute-command';

type ProjectSection = 'active' | 'uninstantiated' | 'teams' | 'sandbox' | 'done';

// Structural classification (registry presence × working dir × team), NOT lifecycle.
// Registry entities carry a source_path under ai_general/data/projects/.
function classifyProject(card: ProjectCard): ProjectSection {
  const status = card.lifecycle_status;
  if (status === 'complete' || status === 'archived') return 'done';
  if (card.tags.includes('team') || card.category === 'team') return 'teams';
  const registered = (card.source_path || '').includes('/data/projects/');
  if (registered) return card.working_dir ? 'active' : 'uninstantiated';
  return 'sandbox';
}

const SECTION_ORDER: ProjectSection[] = ['active', 'uninstantiated', 'teams', 'sandbox', 'done'];

const SECTION_LABELS: Record<ProjectSection, string> = {
  'active': 'Active',
  'uninstantiated': 'Uninstantiated',
  'teams': 'Teams',
  'sandbox': 'Sandbox',
  'done': 'Done',
};

const SECTION_COLORS: Record<ProjectSection, string> = {
  'active': 'var(--accent-green)',
  'uninstantiated': 'var(--accent-blue)',
  'teams': 'var(--accent-purple)',
  'sandbox': 'var(--accent-yellow)',
  'done': 'var(--text-muted)',
};

interface ProjectsTabProps {
  onSelectProject?: (project: ProjectCard) => void;
}

export default function ProjectsTab({ onSelectProject }: ProjectsTabProps): JSX.Element {
  const { projects, initialized } = useCardStore();
  const [search, setSearch] = useState('');
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; card: ProjectCard } | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Set<ProjectSection>>(new Set());
  const menuRef = useRef<HTMLDivElement>(null);

  useContextMenuDismiss(menuRef, () => setContextMenu(null), contextMenu != null);
  useClampToViewport(menuRef, contextMenu != null, [contextMenu?.x, contextMenu?.y]);

  // Hidden entities (todo_0532 "Delete" == hide). They're excluded from the card
  // store, so fetch them separately; Restore flips ui_hidden back via setHidden.
  const [hidden, setHidden] = useState<ProjectCard[]>([]);
  const [hiddenCollapsed, setHiddenCollapsed] = useState(true);
  const reloadHidden = useCallback(() => {
    (window as { uai?: { entities?: { listHidden?: () => Promise<ProjectCard[]> } } })
      .uai?.entities?.listHidden?.()
      .then(res => { if (Array.isArray(res)) setHidden(res); })
      .catch(() => { /* best-effort */ });
  }, []);
  // Refetch on mount and whenever the visible set changes (e.g. after a restore).
  useEffect(() => { reloadHidden(); }, [reloadHidden, projects]);
  const restore = (card: ProjectCard) => {
    const isTeam = card.tags.includes('team') || card.category === 'team';
    const id = String(card.entity_id || card.project_id || '').replace(/^(project|team):/, '');
    executeCommand(isTeam ? 'team.setHidden' : 'project.setHidden', { id, hidden: false, sourcePath: card.source_path })
      .then(() => reloadHidden());
  };

  const filtered = useMemo(() => {
    let result = projects as AnyCard[];
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(c =>
        c.display_name.toLowerCase().includes(q) ||
        (isProjectCard(c) && c.category?.toLowerCase().includes(q))
      );
    }
    return result;
  }, [projects, search]);

  // Group by lifecycle section
  const sections = useMemo(() => {
    const groups: Record<ProjectSection, ProjectCard[]> = {
      'active': [], 'uninstantiated': [], 'teams': [], 'sandbox': [], 'done': [],
    };
    for (const c of filtered) {
      if (isProjectCard(c)) {
        groups[classifyProject(c)].push(c);
      }
    }
    return groups;
  }, [filtered]);

  const toggleSection = (section: ProjectSection) => {
    setCollapsedSections(prev => {
      const next = new Set(prev);
      if (next.has(section)) next.delete(section); else next.add(section);
      return next;
    });
  };

  const handleCardClick = (card: AnyCard) => {
    if (isProjectCard(card)) {
      if (onSelectProject) onSelectProject(card);
      executeCommand('workspace.tabs.open', { type: 'project', targetId: card.project_id, label: card.display_name });
    }
  };

  const handleCardContextMenu = (card: AnyCard, e: React.MouseEvent) => {
    e.preventDefault();
    if (isProjectCard(card)) {
      setContextMenu({ x: e.clientX, y: e.clientY, card: card as ProjectCard });
    }
  };

  if (!initialized) {
    return <div className="session-list-empty">Loading projects...</div>;
  }

  // Search-projects input removed for now (per PianoMan). `search` stays '' so
  // the filter below is a no-op; void setSearch to keep it referenced.
  void setSearch;

  return (
    <div className="projects-tab">
      {SECTION_ORDER.map(section => {
        const items = sections[section];
        if (items.length === 0) return null;
        const collapsed = collapsedSections.has(section);
        return (
          <div key={section} className="session-section">
            <div className="session-section-header" onClick={() => toggleSection(section)}>
              <span className="session-section-arrow">{collapsed ? '\u25B6' : '\u25BC'}</span>
              <span className="session-section-title" style={{ color: SECTION_COLORS[section] }}>{SECTION_LABELS[section]}</span>
              <span className="session-section-count" style={{ color: SECTION_COLORS[section] }}>{items.length}</span>
            </div>
            {!collapsed && (
              <div className="nav-section-children">
                <CardListView
                  cards={items as AnyCard[]}
                  onCardClick={handleCardClick}
                  onCardContextMenu={handleCardContextMenu}
                  emptyMessage=""
                  tooltipPosition="right"
                />
              </div>
            )}
          </div>
        );
      })}

      {hidden.length > 0 && (
        <div className="session-section">
          <div className="session-section-header" onClick={() => setHiddenCollapsed(v => !v)}>
            <span className="session-section-arrow">{hiddenCollapsed ? '▶' : '▼'}</span>
            <span className="session-section-title" style={{ color: 'var(--text-muted)' }}>Hidden</span>
            <span className="session-section-count" style={{ color: 'var(--text-muted)' }}>{hidden.length}</span>
          </div>
          {!hiddenCollapsed && (
            <div className="nav-section-children">
              {hidden.map(card => (
                <div key={card.entity_id} className="projects-hidden-row">
                  <span className="projects-hidden-name" title={card.source_path}>
                    {(card.tags.includes('team') || card.category === 'team') ? '👥 ' : '📦 '}{card.display_name}
                  </span>
                  <button className="projects-hidden-restore" title="Un-hide — show this in the lists again" onClick={() => restore(card)}>Restore</button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {filtered.length === 0 && hidden.length === 0 && (
        <div className="session-list-empty" style={{ fontSize: '11px', padding: '8px 12px' }}>
          {search ? 'No matching projects.' : 'No projects discovered.'}
        </div>
      )}

      {contextMenu && (
        <div ref={menuRef} className="context-menu" style={{ position: 'fixed', left: contextMenu.x, top: contextMenu.y, zIndex: 1000 }}>
          <button className="context-menu-item" onClick={() => {
            window.uai.clipboard.write(contextMenu.card.working_dir);
            setContextMenu(null);
          }}>Copy Path</button>
          <button className="context-menu-item" onClick={() => {
            executeCommand('workspace.tabs.open', { type: 'project', targetId: contextMenu.card.project_id, label: contextMenu.card.display_name });
            setContextMenu(null);
          }}>Open in Tab</button>
        </div>
      )}
    </div>
  );
}
