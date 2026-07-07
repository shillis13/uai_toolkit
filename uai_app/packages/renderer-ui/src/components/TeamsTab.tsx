/**
 * TeamsTab — Navigator tab content showing all discovered teams.
 *
 * Workstream 2K: Teams Entity
 *
 * Renders TeamCards via CardListView. Self-contained component
 * that Navigator imports and renders in the "Teams" tab.
 */

import { useState, useMemo } from 'react';
import type { AnyCard, TeamCard } from '@uai/shared/cards';
import { isTeamCard } from '@uai/shared/cards';
import { useCardStore } from '../stores/card-store';
import { CardListView } from './cards';

interface TeamsTabProps {
  onSelectTeam?: (team: TeamCard) => void;
}

export default function TeamsTab({ onSelectTeam }: TeamsTabProps): JSX.Element {
  const { teams, initialized } = useCardStore();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | null>(null);

  const filtered = useMemo(() => {
    let result = teams as AnyCard[];

    if (search) {
      const q = search.toLowerCase();
      result = result.filter(c => c.display_name.toLowerCase().includes(q));
    }

    if (statusFilter) {
      result = result.filter(c => {
        if (!isTeamCard(c)) return false;
        return c.status === statusFilter;
      });
    }

    return result;
  }, [teams, search, statusFilter]);

  if (!initialized) {
    return <div className="session-list-empty">Loading teams...</div>;
  }

  return (
    <div className="teams-tab">
      <div className="nav-filter-toolbar">
        <div className="nav-filter-row">
          {['active', 'paused', 'disbanded'].map(s => (
            <button
              key={s}
              className={`filter-pill${statusFilter === s ? ' active' : ''}`}
              onClick={() => setStatusFilter(statusFilter === s ? null : s)}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="nav-filter-row">
          <input
            type="text"
            className="nav-search-input"
            placeholder="Search teams..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>
      <CardListView
        cards={filtered}
        onCardClick={(card) => {
          if (isTeamCard(card) && onSelectTeam) {
            onSelectTeam(card);
          }
        }}
        emptyMessage={search || statusFilter ? 'No teams match filter.' : 'No teams defined yet.'}
      />
    </div>
  );
}
