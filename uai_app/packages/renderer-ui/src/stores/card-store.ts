/**
 * CardStore — unified renderer-side card store.
 *
 * Workstream 2A: Card/Container Base Abstractions
 *
 * Combines session and folder data into a single card-oriented store.
 * Provides type-filtered accessors and container-aware queries.
 * Existing useSessionStore() and useFolderStore() remain as separate stores.
 */

import { useState, useEffect } from 'react';
import type { Session } from '@uai/shared/types';
import type { AnyCard, SessionCard, BriefCard, FolderCard, ProjectCard, TeamCard, CardFilter } from '@uai/shared/cards';
import type { ContainerStoreData, ContainerEntry } from '@uai/shared/cards';
import type { EntityId } from '@uai/shared/types';
import type { StoreChangedEvent } from '@uai/shared/types';

// ─── Singleton state ──────────────────────────────────────────────────────

let cards = new Map<string, AnyCard>();
let containerStore: ContainerStoreData | null = null;
let initialized = false;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// ─── Session → SessionCard adapter ───────────────────────────────────────

function sessionToCard(s: Session): SessionCard {
  return {
    entity_id: `session:${s.tracking_id}` as EntityId,
    entity_type: 'session',
    display_name: s.display_name || s.tracking_id,
    created_at: s.created_at,
    last_activity: s.last_activity || s.created_at,
    tags: s.tags || [],
    tracking_id: s.tracking_id,
    platform: s.platform,
    process_status: s.process_status,
    cli_session_id: s.cli_session_id,
    terminal_session: s.terminal_session,
    session_dir: s.session_dir,
    project_dir: s.project_dir,
    parent_tracking_id: s.parent_tracking_id,
    roles: s.roles,
    model: s.model,
    identity_status: s.identity_status,
    archived: s.archived,
    activity_state: s.activity_state,
    context_percent: s.context_percent,
    exchange_count: s.exchange_count,
    pinned: s.pinned,
    notes: s.notes,
    prompt_block: s.prompt_block ?? null,
  };
}

// ─── ContainerEntry → FolderCard adapter ─────────────────────────────────

function containerToCard(entry: ContainerEntry): FolderCard | null {
  const base = {
    entity_id: `${entry.container_type}:${entry.id}` as EntityId,
    display_name: entry.name,
    created_at: '',
    last_activity: '',
    tags: [],
    icon: entry.icon || undefined,
    color: entry.color || undefined,
    container: {
      children: entry.cards as EntityId[],
      sub_containers: entry.sub_containers,
      placement_rule: entry.placement_rule as 'exclusive' | 'non-exclusive',
    },
  };

  if (entry.container_type === 'group') {
    return null;  // Groups removed
  }
  return { ...base, entity_type: 'folder' as const, builtin: entry.builtin } as FolderCard;
}

// ─── Bootstrap and refresh ───────────────────────────────────────────────

function hydrateContainers(data: ContainerStoreData, target: Map<string, AnyCard>): void {
  containerStore = data;
  for (const [id, entry] of Object.entries(data.containers)) {
    const card = containerToCard(entry);
    if (card !== null) {
      target.set(`${entry.container_type}:${id}`, card);
    }
  }
}

export async function bootstrap(): Promise<void> {
  try {
    const [snapshot, containerData, projects, briefs, teams] = await Promise.all([
      window.uai.bootstrap(),
      window.uai.containers.list(),
      window.uai.projects.list(),
      window.uai.briefs.list(),
      window.uai.teams.list(),
    ]);

    cards = new Map();

    for (const session of snapshot.sessions) {
      const card = sessionToCard(session);
      cards.set(card.entity_id, card);
    }

    if (containerData) {
      hydrateContainers(containerData, cards);
    }

    for (const project of projects) {
      cards.set(project.entity_id, project);
    }

    for (const brief of briefs) {
      cards.set(brief.entity_id, brief);
    }

    for (const team of teams) {
      cards.set(team.entity_id, team);
    }

    initialized = true;
    notify();
  } catch {
    initialized = true;
    notify();
  }
}

async function refresh(): Promise<void> {
  try {
    const [sessions, containerData, projects, briefs, teams] = await Promise.all([
      window.uai.sessions.list(),
      window.uai.containers.list(),
      window.uai.projects.list(),
      window.uai.briefs.list(),
      window.uai.teams.list(),
    ]);

    const newCards = new Map<string, AnyCard>();

    for (const session of sessions) {
      const card = sessionToCard(session);
      newCards.set(card.entity_id, card);
    }

    if (containerData) {
      hydrateContainers(containerData, newCards);
    }

    for (const project of projects) {
      newCards.set(project.entity_id, project);
    }

    for (const brief of briefs) {
      newCards.set(brief.entity_id, brief);
    }

    for (const team of teams) {
      newCards.set(team.entity_id, team);
    }

    cards = newCards;
    notify();
  } catch {
    // Keep current state
  }
}

// ─── Imperative API ──────────────────────────────────────────────────────

export function getCard(entityId: string): AnyCard | undefined {
  return cards.get(entityId);
}

export function listAllCards(filter?: CardFilter): AnyCard[] {
  let result = Array.from(cards.values());

  if (filter?.entity_types) {
    result = result.filter(c => filter.entity_types!.includes(c.entity_type));
  }
  if (filter?.tags && filter.tags.length > 0) {
    result = result.filter(c => filter.tags!.some(t => c.tags.includes(t)));
  }
  if (filter?.search) {
    const q = filter.search.toLowerCase();
    result = result.filter(c => c.display_name.toLowerCase().includes(q));
  }

  return result;
}

export function getContainerForId(containerId: string): ContainerEntry | undefined {
  return containerStore?.containers[containerId];
}

export function getCardsInContainer(containerId: string, opts?: { descendants?: boolean }): AnyCard[] {
  const entry = containerStore?.containers[containerId];
  if (!entry) return [];

  const cardIds = [...entry.cards];

  if (opts?.descendants) {
    const queue = [...entry.sub_containers];
    while (queue.length > 0) {
      const childId = queue.shift()!;
      const child = containerStore?.containers[childId];
      if (!child) continue;
      cardIds.push(...child.cards);
      queue.push(...child.sub_containers);
    }
  }

  return cardIds.map(id => cards.get(id)).filter((c): c is AnyCard => c !== undefined);
}

export function getContainersForCard(cardId: string): string[] {
  if (!containerStore) return [];
  return Object.entries(containerStore.containers)
    .filter(([, entry]) => entry.cards.includes(cardId))
    .map(([id]) => id);
}

// ─── Type-specific convenience accessors ─────────────────────────────────

export function getSessions(): SessionCard[] {
  return listAllCards({ entity_types: ['session'] }) as SessionCard[];
}

export function getBriefs(): BriefCard[] {
  return listAllCards({ entity_types: ['brief'] }) as BriefCard[];
}

export function getFolders(): FolderCard[] {
  return listAllCards({ entity_types: ['folder'] }) as FolderCard[];
}

export function getProjects(): ProjectCard[] {
  return listAllCards({ entity_types: ['project'] }) as ProjectCard[];
}

export function getTeams(): TeamCard[] {
  return listAllCards({ entity_types: ['team'] }) as TeamCard[];
}

// ─── Path 2: Store change subscription ───────────────────────────────────

let unsubStoreChanged: (() => void) | null = null;

function startListening(): void {
  if (unsubStoreChanged) return;
  unsubStoreChanged = window.uai.onStoreChanged((event: StoreChangedEvent) => {
    if (event.changed.includes('sessions') || event.changed.includes('folders')
      || event.changed.includes('projects') || event.changed.includes('teams')) {
      refresh();
    }
  });
}

// ─── React Hook ──────────────────────────────────────────────────────────

export function useCardStore() {
  const [, forceUpdate] = useState(0);

  useEffect(() => {
    if (!initialized) {
      bootstrap();
      startListening();
    }
    const unsub = subscribe(() => forceUpdate(n => n + 1));
    return unsub;
  }, []);

  return {
    initialized,
    getCard,
    listCards: listAllCards,
    getCardsInContainer,
    getContainersForCard,
    getContainer: getContainerForId,
    containerStore,
    sessions: getSessions(),
    briefs: getBriefs(),
    folders: getFolders(),
    projects: getProjects(),
    teams: getTeams(),
    refresh,
  };
}
