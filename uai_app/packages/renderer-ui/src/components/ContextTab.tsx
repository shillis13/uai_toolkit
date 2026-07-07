/**
 * ContextTab — Traits browser showing loaded context for a session.
 *
 * Displays traits, roles, skills, and memory slots that are loaded in
 * the active session's context. Items can be selected and loaded on demand.
 * Part of the right panel (ContextPanel) tab system.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { executeCommand } from '../utils/execute-command';

// ─── Types ──────────────────────────────────────────────────────────────

interface ContextItem {
  type: string;
  name: string;
  loaded: boolean;
  /** 'pending' = queued for delivery, 'loaded' = delivered, undefined = not loaded */
  state?: 'pending' | 'loaded';
  src?: string;
  filePath?: string;
  mtime?: string;
}

interface ContextTabProps {
  sessionTrackingId: string | null;
  /** Discovery mode: show all available items even without a session */
  discoveryMode?: boolean;
  /** Called when selection changes — parent can read selected items */
  onSelectionChange?: (selectedItems: Array<{ type: string; name: string; filePath?: string }>) => void;
}

// ─── Helpers ────────────────────────────────────────────────────────────

/** Split trait name on first `/` to get subcategory and display name. */
function splitTraitName(name: string): { subcategory: string; displayName: string } {
  const idx = name.indexOf('/');
  if (idx === -1) return { subcategory: 'other', displayName: name };
  return { subcategory: name.slice(0, idx), displayName: name.slice(idx + 1) };
}

/** Group an array by a key function. */
function groupBy<T>(items: T[], keyFn: (item: T) => string): Record<string, T[]> {
  const result: Record<string, T[]> = {};
  for (const item of items) {
    const key = keyFn(item);
    if (!result[key]) result[key] = [];
    result[key].push(item);
  }
  return result;
}

// ─── Styles ─────────────────────────────────────────────────────────────

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column' as const,
    flex: 1,
    minHeight: 0,
    overflow: 'hidden',
  },
  scrollArea: {
    flex: 1,
    overflowY: 'auto' as const,
    padding: '0',
  },
  loadBar: {
    position: 'sticky' as const,
    zIndex: 5,
    background: 'var(--bg-panel)',
    padding: '6px 10px',
  },
  loadBarTop: {
    top: 0,
    borderBottom: '1px solid var(--border)',
  },
  loadBarBottom: {
    bottom: 0,
    borderTop: '1px solid var(--border)',
  },
  loadBarBtn: {
    width: '100%',
    padding: '5px 12px',
    fontSize: '11px',
    fontWeight: 600,
    border: '1px solid var(--accent-blue)',
    borderRadius: '4px',
    background: 'color-mix(in srgb, var(--accent-blue) 15%, var(--bg-secondary))',
    color: 'var(--accent-blue)',
    cursor: 'pointer',
  },
  loadBarBtnDisabled: {
    opacity: 0.4,
    cursor: 'not-allowed',
    border: '1px solid var(--text-muted)',
    background: 'var(--bg-secondary)',
    color: 'var(--text-muted)',
  },
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '6px 12px',
    cursor: 'pointer',
    userSelect: 'none' as const,
    fontSize: '12px',
    fontWeight: 600,
    color: 'var(--text)',
  },
  sectionCount: {
    fontSize: '11px',
    fontWeight: 400,
    color: 'var(--text-sec)',
    marginLeft: '6px',
  },
  sectionChevron: {
    fontSize: '18px',
    color: 'var(--text-sec)',
    marginRight: '4px',
    lineHeight: 1,
  },
  subcategoryHeader: {
    padding: '4px 12px 2px 20px',
    fontSize: '10px',
    fontWeight: 600,
    color: 'var(--text-muted)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.3px',
  },
  itemRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '3px 12px 3px 28px',
    fontSize: '12px',
    fontFamily: 'monospace',
    color: 'var(--text-primary)',
    cursor: 'default',
  },
  itemRowLoaded: {
    backgroundColor: 'color-mix(in srgb, var(--accent-green) 6%, transparent)',
  },
  itemRowPending: {
    backgroundColor: 'color-mix(in srgb, var(--accent-yellow) 6%, transparent)',
  },
  loadedIndicator: {
    fontSize: '8px',
    lineHeight: 1,
    flexShrink: 0,
    width: '10px',
    textAlign: 'center' as const,
  },
  checkboxCell: {
    flexShrink: 0,
    width: '16px',
    textAlign: 'center' as const,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkmark: {
    color: 'var(--accent-green)',
    fontWeight: 700,
    fontSize: '13px',
    lineHeight: 1,
  },
  checkbox: {
    flexShrink: 0,
    cursor: 'pointer',
    accentColor: 'var(--accent-green)',
    margin: 0,
  },
  itemName: {
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  itemNameClickable: {
    cursor: 'pointer',
    textDecoration: 'none',
    borderBottom: '1px dotted var(--text-muted)',
  },
  empty: {
    padding: '24px 16px',
    textAlign: 'center' as const,
    color: 'var(--text-muted)',
    fontSize: '12px',
  },
  loading: {
    padding: '24px 16px',
    textAlign: 'center' as const,
    color: 'var(--text-muted)',
    fontSize: '12px',
  },
};

// ─── Section Component ──────────────────────────────────────────────────

interface SectionProps {
  title: string;
  loadedCount: number;
  totalCount: number;
  defaultExpanded: boolean;
  children: React.ReactNode;
  depth?: number;
}

function Section({ title, loadedCount, totalCount, defaultExpanded, children, depth = 0 }: SectionProps): JSX.Element {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [hasUserToggled, setHasUserToggled] = useState(false);

  // Update expansion state when defaultExpanded changes, but only if user hasn't manually toggled
  useEffect(() => {
    if (!hasUserToggled) {
      setExpanded(defaultExpanded);
    }
  }, [defaultExpanded, hasUserToggled]);

  const depthColors = ['var(--text)', 'var(--accent-blue)', 'var(--accent-cyan)'];
  const titleColor = depthColors[Math.min(depth, depthColors.length - 1)];

  return (
    <div style={{ paddingLeft: depth > 0 ? `${depth * 16}px` : undefined }}>
      <div
        style={styles.sectionHeader}
        onClick={() => { setHasUserToggled(true); setExpanded(!expanded); }}
      >
        <span>
          <span style={styles.sectionChevron}>{expanded ? '\u25BE' : '\u25B8'}</span>
          {' '}<strong style={{ fontWeight: depth === 0 ? 600 : 500, color: titleColor }}>{title}</strong>
          <span style={styles.sectionCount}>{loadedCount}/{totalCount}</span>
        </span>
      </div>
      {expanded && children}
    </div>
  );
}

// ─── ContextTab ─────────────────────────────────────────────────────────

export default function ContextTab({ sessionTrackingId, discoveryMode, onSelectionChange }: ContextTabProps): JSX.Element {
  const [items, setItems] = useState<ContextItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loadingItems, setLoadingItems] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Context search ─────────────────────────────────────────────────
  const [contextSearch, setContextSearch] = useState('');
  const [contextTitlesOnly, setContextTitlesOnly] = useState(false);
  const [contentMatchedKeys, setContentMatchedKeys] = useState<Set<string>>(new Set());
  const [contextSearchBusy, setContextSearchBusy] = useState(false);
  const fileContentCacheRef = useRef<Map<string, string>>(new Map());

  // ── Data loading ────────────────────────────────────────────────────

  const loadItems = useCallback(async () => {
    if (!sessionTrackingId && !discoveryMode) {
      setItems([]);
      return;
    }
    try {
      // In discovery mode without a session, use a dummy ID — the IPC handler
      // calls session_traits.py --session X list --all, which returns all available
      // items regardless of session. Any valid tracking ID works.
      const effectiveId = sessionTrackingId || '_discovery_';
      const result = await window.uai.traits.list(effectiveId);
      setItems(result || []);
      setError(null);
    } catch (e) {
      setItems([]);
      setError('Failed to load context items.');
    }
  }, [sessionTrackingId]);

  // Initial load + re-load on session change
  useEffect(() => {
    setLoading(true);
    setSelected(new Set());
    loadItems().finally(() => setLoading(false));
  }, [loadItems]);

  // Poll every 5 seconds (skip in discovery mode — static list)
  useEffect(() => {
    if (!sessionTrackingId && !discoveryMode) return;
    if (discoveryMode) return; // no polling in discovery mode
    const interval = setInterval(loadItems, 5000);
    return () => clearInterval(interval);
  }, [sessionTrackingId, discoveryMode, loadItems]);

  // ── Search filtering ────────────────────────────────────────────────

  const contextQuery = contextSearch.trim().toLowerCase();

  const matchesTitle = useCallback((item: ContextItem, query: string): boolean => {
    if (!query) return true;
    const haystacks = [item.name, item.type, splitTraitName(item.name).displayName]
      .map(v => v.toLowerCase());
    return haystacks.some(v => v.includes(query));
  }, []);

  // Content search: when searching with "Titles only" unchecked, also search file contents
  useEffect(() => {
    if (!contextQuery || contextTitlesOnly) {
      setContentMatchedKeys(new Set());
      setContextSearchBusy(false);
      return;
    }

    const candidates = items.filter(item => item.filePath && !matchesTitle(item, contextQuery));
    if (candidates.length === 0) {
      setContentMatchedKeys(new Set());
      setContextSearchBusy(false);
      return;
    }

    let cancelled = false;
    setContextSearchBusy(true);

    const run = async (): Promise<void> => {
      const matched = new Set<string>();
      for (const item of candidates) {
        const cacheKey = item.filePath!;
        let content = fileContentCacheRef.current.get(cacheKey);
        if (content == null) {
          try {
            // Use clipboard read as a proxy — or if fs.read is available
            const raw = await (window.uai as any).fs?.read?.(cacheKey) ?? '';
            content = (typeof raw === 'string' ? raw : '').toLowerCase();
          } catch {
            content = '';
          }
          fileContentCacheRef.current.set(cacheKey, content);
        }
        if (content.includes(contextQuery)) {
          matched.add(`${item.type}::${item.name}`);
        }
      }
      if (!cancelled) {
        setContentMatchedKeys(matched);
        setContextSearchBusy(false);
      }
    };

    run().catch(() => {
      if (!cancelled) {
        setContentMatchedKeys(new Set());
        setContextSearchBusy(false);
      }
    });

    return () => { cancelled = true; };
  }, [contextQuery, contextTitlesOnly, items, matchesTitle]);

  const filteredItems = useMemo(() => {
    if (!contextQuery) return items;
    return items.filter(item => {
      if (matchesTitle(item, contextQuery)) return true;
      return !contextTitlesOnly && contentMatchedKeys.has(`${item.type}::${item.name}`);
    });
  }, [items, contextQuery, contextTitlesOnly, contentMatchedKeys, matchesTitle]);

  // ── Grouping ────────────────────────────────────────────────────────

  const grouped = useMemo(() => {
    const globals: ContextItem[] = [];
    const traits: ContextItem[] = [];
    const roles: ContextItem[] = [];
    const skills: ContextItem[] = [];
    const profiles: ContextItem[] = [];
    const mslots: ContextItem[] = [];
    const briefs: ContextItem[] = [];

    for (const item of filteredItems) {
      if (item.type === 'globals') {
        globals.push(item);
      } else if (item.type === 'roles') {
        if (item.name.startsWith('skill:')) {
          skills.push(item);
        } else {
          roles.push(item);
        }
      } else if (item.type === 'profiles') {
        profiles.push(item);
      } else if (item.type === 'mslots') {
        mslots.push(item);
      } else if (item.type === 'briefs') {
        briefs.push(item);
      } else {
        // traits (and any other type) go into traits section
        traits.push(item);
      }
    }

    // Sub-group traits by subcategory
    const traitsByCategory = groupBy(traits, (t) => splitTraitName(t.name).subcategory);

    // Sort briefs newest-first by file modification time
    briefs.sort((a, b) => (b.mtime || '').localeCompare(a.mtime || ''));

    return { globals, traits, traitsByCategory, roles, skills, profiles, mslots, briefs };
  }, [filteredItems]);

  // ── Selection ───────────────────────────────────────────────────────

  const toggleSelection = useCallback((type: string, name: string) => {
    const key = `${type}::${name}`;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  // ── Notify parent of selection changes ──────────────────────────────
  useEffect(() => {
    if (!onSelectionChange) return;
    const selectedItems = Array.from(selected).map(key => {
      const [type, name] = key.split('::');
      const item = items.find(i => i.type === type && i.name === name);
      return { type, name, filePath: item?.filePath };
    });
    onSelectionChange(selectedItems);
  }, [selected, items, onSelectionChange]);

  // ── Load Selected ───────────────────────────────────────────────────

  const handleLoadSelected = useCallback(async () => {
    if (!sessionTrackingId || selected.size === 0) return;

    const toLoad = Array.from(selected).map((key) => {
      const [type, name] = key.split('::');
      return { type, name };
    });

    setLoadingItems(true);
    try {
      const cmdResult = await executeCommand<{ results: Array<{ success: boolean }> }>('traits.load', {
        sessionId: sessionTrackingId,
        items: toLoad,
      });
      const results = cmdResult.data?.results;
      const successCount = results?.filter((r) => r.success).length ?? 0;
      const failCount = (results?.length ?? 0) - successCount;
      setSelected(new Set());
      await loadItems();
      // Show feedback
      if (failCount > 0) {
        setError(`Loaded ${successCount}, failed ${failCount}`);
        setTimeout(() => setError(null), 5000);
      }
    } catch (e) {
      setError(`Load failed: ${e instanceof Error ? e.message : String(e)}`);
      setTimeout(() => setError(null), 5000);
    } finally {
      setLoadingItems(false);
    }
  }, [sessionTrackingId, selected, loadItems]);

  // ── Deselect All ────────────────────────────────────────────────────

  const handleDeselectAll = useCallback(() => {
    setSelected(new Set());
  }, []);

  // ── Open file handler ───────────────────────────────────────────────

  const handleOpenFile = useCallback((filePath: string | undefined) => {
    if (!filePath) return;
    window.uai.traits.openFile(filePath);
  }, []);

  // ── Render helpers ──────────────────────────────────────────────────

  const renderItem = useCallback((item: ContextItem, displayName: string) => {
    const key = `${item.type}::${item.name}`;
    const isSelected = selected.has(key);
    const hasFile = !!item.filePath;
    const isPending = item.state === 'pending';
    const isLoaded = item.loaded && !isPending;

    return (
      <div
        key={key}
        style={{
          ...styles.itemRow,
          ...(isLoaded ? styles.itemRowLoaded : {}),
          ...(isPending ? styles.itemRowPending : {}),
        }}
      >
        <span style={styles.checkboxCell as React.CSSProperties}>
          {isLoaded ? (
            <span style={styles.checkmark}>{'\u2713'}</span>
          ) : isPending ? (
            <input
              type="checkbox"
              style={{ ...styles.checkbox, cursor: 'default', accentColor: 'var(--accent-yellow)' }}
              checked
              disabled
              title="Pending — will load on next prompt"
            />
          ) : (
            <input
              type="checkbox"
              style={styles.checkbox}
              checked={isSelected}
              onChange={() => toggleSelection(item.type, item.name)}
            />
          )}
        </span>
        <span
          style={{
            ...styles.itemName,
            ...(hasFile ? styles.itemNameClickable : {}),
          }}
          title={item.filePath || item.name}
          onClick={hasFile ? () => handleOpenFile(item.filePath) : undefined}
        >
          {displayName}
        </span>
      </div>
    );
  }, [selected, toggleSelection, handleOpenFile]);

  // ── Empty / loading states ──────────────────────────────────────────

  if (!sessionTrackingId && !discoveryMode) {
    return <div style={styles.empty}>Select a session to view its context.</div>;
  }

  if (loading && items.length === 0) {
    return <div style={styles.loading}>Loading context...</div>;
  }

  if (error && items.length === 0) {
    return <div style={styles.empty}>{error}</div>;
  }

  // ── Count helpers ───────────────────────────────────────────────────

  const countLoaded = (arr: ContextItem[]) => arr.filter((i) => i.loaded).length;

  const globalsLoaded = countLoaded(grouped.globals);
  const traitsLoaded = countLoaded(grouped.traits);
  const rolesLoaded = countLoaded(grouped.roles);
  const skillsLoaded = countLoaded(grouped.skills);
  const profilesLoaded = countLoaded(grouped.profiles);
  const mslotsLoaded = countLoaded(grouped.mslots);
  const briefsLoaded = countLoaded(grouped.briefs);

  // Sort subcategory keys, putting "other" last
  const subcatKeys = Object.keys(grouped.traitsByCategory).sort((a, b) => {
    if (a === 'other') return 1;
    if (b === 'other') return -1;
    return a.localeCompare(b);
  });

  const selectedCount = selected.size;
  const loadBtnDisabled = selectedCount === 0 || loadingItems;
  const loadBtnLabel = loadingItems ? 'Loading...' : `Load Selected (${selectedCount})`;

  const loadButton = (
    <div style={{ display: 'flex', gap: '6px' }}>
      <button
        style={{
          ...styles.loadBarBtn,
          ...(loadBtnDisabled ? styles.loadBarBtnDisabled : {}),
          flex: 1,
        }}
        disabled={loadBtnDisabled}
        onClick={handleLoadSelected}
      >
        {loadBtnLabel}
      </button>
      {selectedCount > 0 && (
        <button
          style={{
            ...styles.loadBarBtn,
            flex: 'none',
            width: 'auto',
            border: '1px solid var(--text-muted)',
            background: 'var(--bg-secondary)',
            color: 'var(--text-sec)',
          }}
          onClick={handleDeselectAll}
        >
          Deselect All
        </button>
      )}
    </div>
  );

  const totalLoadedCount = items.filter(i => i.loaded).length;
  const totalItemCount = items.length;

  return (
    <div className="context-tab" style={styles.container}>
      {/* ── Sticky toolbar: search + Load Selected ── */}
      <div className="traits-context-toolbar" style={{ ...styles.loadBar, ...styles.loadBarTop, flexShrink: 0 }}>
        {sessionTrackingId && (
          <div style={{ marginBottom: '6px' }}>
            {loadButton}
          </div>
        )}
        <div className="traits-context-search" style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-sec)' }}>Search Context</span>
            <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '10px', color: 'var(--text-muted)', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={contextTitlesOnly}
                onChange={e => setContextTitlesOnly(e.target.checked)}
                style={{ margin: 0 }}
              />
              Titles only
            </label>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <input
              type="text"
              value={contextSearch}
              onChange={e => setContextSearch(e.target.value)}
              placeholder={contextTitlesOnly ? 'Search titles\u2026' : 'Search titles and file contents\u2026'}
              style={{
                flex: 1,
                padding: '4px 8px',
                fontSize: '11px',
                background: 'var(--bg-deep)',
                border: '1px solid var(--border)',
                borderRadius: '4px',
                color: 'var(--text)',
                outline: 'none',
              }}
            />
            {contextSearchBusy && (
              <span style={{ fontSize: '10px', color: 'var(--accent-blue)' }}>Searching\u2026</span>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '6px' }}>
          <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text)' }}>
            {sessionTrackingId ? 'Session Context' : 'Available Context'}
          </span>
          <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
            {contextQuery
              ? `${filteredItems.length}/${totalItemCount} shown`
              : `${totalLoadedCount}/${totalItemCount}`
            }
          </span>
        </div>
      </div>

      <div style={styles.scrollArea}>
        <div className="context-sections">
          {/* Globals */}
          {grouped.globals.length > 0 && (
            <Section
              title="Globals"
              loadedCount={globalsLoaded}
              totalCount={grouped.globals.length}
              defaultExpanded={true}
            >
              {grouped.globals.map((item) => renderItem(item, item.name))}
            </Section>
          )}

          {/* Session Briefs */}
          {grouped.briefs.length > 0 && (
            <Section
              title="Session Briefs"
              loadedCount={briefsLoaded}
              totalCount={grouped.briefs.length}
              defaultExpanded={false}
            >
              {grouped.briefs.map((item) => renderItem(item, item.name))}
            </Section>
          )}

          {/* Profiles */}
          {grouped.profiles.length > 0 && (
            <Section
              title="Profiles"
              loadedCount={profilesLoaded}
              totalCount={grouped.profiles.length}
              defaultExpanded={false}
            >
              {grouped.profiles.map((item) => renderItem(item, item.name))}
            </Section>
          )}

          {/* Memories */}
          {grouped.mslots.length > 0 && (
            <Section
              title="Memories"
              loadedCount={mslotsLoaded}
              totalCount={grouped.mslots.length}
              defaultExpanded={false}
            >
              {grouped.mslots.map((item) => renderItem(item, item.name))}
            </Section>
          )}

          {/* Roles — top level */}
          {grouped.roles.length > 0 && (
            <Section
              title="Roles"
              loadedCount={rolesLoaded}
              totalCount={grouped.roles.length}
              defaultExpanded={false}
            >
              {grouped.roles.map((item) => renderItem(item, item.name))}
            </Section>
          )}

          {/* Skills — top level */}
          {grouped.skills.length > 0 && (
            <Section
              title="Skills"
              loadedCount={skillsLoaded}
              totalCount={grouped.skills.length}
              defaultExpanded={false}
            >
              {grouped.skills.map((item) =>
                renderItem(item, item.name.replace(/^skill:/, ''))
              )}
            </Section>
          )}

          {/* Traits & Docs — contains trait subcategories */}
          {grouped.traits.length > 0 && (
            <Section
              title="Traits & Docs"
              loadedCount={traitsLoaded}
              totalCount={grouped.traits.length}
              defaultExpanded={true}
            >
              {subcatKeys.map((subcat) => (
                <Section depth={1}
                  key={subcat}
                  title={subcat.charAt(0).toUpperCase() + subcat.slice(1)}
                  loadedCount={grouped.traitsByCategory[subcat].filter(i => i.loaded).length}
                  totalCount={grouped.traitsByCategory[subcat].length}
                  defaultExpanded={false}
                >
                  {grouped.traitsByCategory[subcat].map((item) =>
                    renderItem(item, splitTraitName(item.name).displayName)
                  )}
                </Section>
              ))}
            </Section>
          )}

          {/* Keep backward compat: show mslots if no other data */}
          {grouped.mslots.length > 0 && grouped.traits.length === 0 && grouped.roles.length === 0 && grouped.skills.length === 0 && (
            <Section
              title="Memory Slots"
              loadedCount={mslotsLoaded}
              totalCount={grouped.mslots.length}
              defaultExpanded={false}
            >
              {grouped.mslots.map((item) => renderItem(item, item.name))}
            </Section>
          )}

          {filteredItems.length === 0 && !loading && (
            <div style={styles.empty}>
              {contextQuery ? 'No matching context items.' : 'No context items found for this session.'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
