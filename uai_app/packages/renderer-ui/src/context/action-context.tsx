/**
 * ActionContextProvider — React context for actionable regions.
 *
 * Wraps regions of the UI that support context menus and multi-select.
 * Provides entity_ref, selection, select_mode, location to children.
 * Components use useActionContext() to consume.
 *
 * resolveActionTargets() determines whether an action applies to
 * just the clicked entity or all selected entities.
 */

import React, { createContext, useContext, useState, useCallback, useMemo } from 'react';
import type { ActionContext, EntityRef } from '@uai/shared/types';
import { resolveActionTargets } from '@uai/shared/types';

// ─── Context ──────────────────────────────────────────────────────────────

interface ActionContextValue {
  /** Current action context (entity, selection, location) */
  context: ActionContext;

  /** Toggle selection of an entity ID */
  toggleSelect: (id: string) => void;

  /** Set selection to exactly these IDs */
  setSelection: (ids: string[]) => void;

  /** Clear selection and exit select mode */
  clearSelection: () => void;

  /** Set the current entity ref (e.g., hovered/focused card) */
  setEntityRef: (ref: EntityRef | undefined) => void;

  /** Set the current location (folder path) */
  setLocation: (location: string) => void;

  /** Set the active navigator tab */
  setNavigatorTab: (tab: string) => void;

  /** Resolve action targets: selected items or just the clicked one */
  resolveTargets: (clickedId: string) => string[];
}

const ActionCtx = createContext<ActionContextValue | null>(null);

// ─── Provider ─────────────────────────────────────────────────────────────

interface ActionContextProviderProps {
  children: React.ReactNode;
  initialLocation?: string;
  initialNavigatorTab?: string;
}

export function ActionContextProvider({
  children,
  initialLocation = '/',
  initialNavigatorTab = 'sessions',
}: ActionContextProviderProps): React.ReactElement {
  const [selection, setSelectionState] = useState<Set<string>>(new Set());
  const [selectMode, setSelectMode] = useState(false);
  const [entityRef, setEntityRefState] = useState<EntityRef | undefined>();
  const [location, setLocationState] = useState(initialLocation);
  const [navigatorTab, setNavigatorTabState] = useState(initialNavigatorTab);

  const toggleSelect = useCallback((id: string) => {
    setSelectionState(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      setSelectMode(next.size > 0);
      return next;
    });
  }, []);

  const setSelection = useCallback((ids: string[]) => {
    setSelectionState(new Set(ids));
    setSelectMode(ids.length > 0);
  }, []);

  const clearSelection = useCallback(() => {
    setSelectionState(new Set());
    setSelectMode(false);
  }, []);

  const setEntityRef = useCallback((ref: EntityRef | undefined) => {
    setEntityRefState(ref);
  }, []);

  const setLocation = useCallback((loc: string) => {
    setLocationState(loc);
  }, []);

  const setNavigatorTab = useCallback((tab: string) => {
    setNavigatorTabState(tab);
  }, []);

  const context: ActionContext = useMemo(() => ({
    entity_ref: entityRef,
    selection,
    select_mode: selectMode,
    location,
    navigator_tab: navigatorTab,
  }), [entityRef, selection, selectMode, location, navigatorTab]);

  const resolveTargets = useCallback((clickedId: string): string[] => {
    return resolveActionTargets(clickedId, context);
  }, [context]);

  const value: ActionContextValue = useMemo(() => ({
    context,
    toggleSelect,
    setSelection,
    clearSelection,
    setEntityRef,
    setLocation,
    setNavigatorTab,
    resolveTargets,
  }), [context, toggleSelect, setSelection, clearSelection, setEntityRef, setLocation, setNavigatorTab, resolveTargets]);

  return (
    <ActionCtx.Provider value={value}>
      {children}
    </ActionCtx.Provider>
  );
}

// ─── Hook ─────────────────────────────────────────────────────────────────

export function useActionContext(): ActionContextValue {
  const ctx = useContext(ActionCtx);
  if (!ctx) {
    throw new Error('useActionContext must be used within an ActionContextProvider');
  }
  return ctx;
}
