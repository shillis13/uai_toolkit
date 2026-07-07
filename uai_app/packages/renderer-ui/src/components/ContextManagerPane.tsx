/**
 * ContextManagerPane — In-app context library browser.
 *
 * Ported from UCI TraitsManagerPane. Backed by trait_mgr.py via
 * the uai:traitMgr:run IPC channel.
 * Shows profiles, roles, skills, traits (by category), and validation results.
 */

import { useState, useEffect, useCallback, useRef } from 'react';

type View = 'globals' | 'profiles' | 'roles' | 'skills' | 'traits' | 'validate';

interface TraitRecord {
  category: string;
  name: string;
  slug: string;
  path: string;
  is_symlink: boolean;
}

interface ContextManagerPaneProps {
  tabId?: string;
  deepLinkId?: string;
}

const ContextManagerPane = ({ tabId, deepLinkId }: ContextManagerPaneProps): JSX.Element => {
  const [activeView, setActiveView] = useState<View>('traits');
  const [items, setItems] = useState<any[]>([]);
  const [selectedItem, setSelectedItem] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validateResult, setValidateResult] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set());
  const [viewerContent, setViewerContent] = useState<string | null>(null);
  const [viewerPath, setViewerPath] = useState<string | null>(null);
  const [viewerLoading, setViewerLoading] = useState(false);
  const [copyFeedback, setCopyFeedback] = useState(false);

  const runCommand = useCallback(async (command: string, args: string[] = []) => {
    const result = await window.uai.traitMgr.run(command, args);
    if (!result.ok) {
      throw new Error(result.error || 'Command failed');
    }
    return result.data;
  }, []);

  // Load status on mount
  useEffect(() => {
    runCommand('status').then(setStatus).catch(() => {});
  }, [runCommand]);

  // Load items when view changes
  useEffect(() => {
    if (activeView === 'validate') return;

    setLoading(true);
    setError(null);
    setSelectedItem(null);
    setViewerContent(null);
    setViewerPath(null);

    if (activeView === 'globals') {
      // Globals use a separate IPC handler (not trait_mgr)
      (window as any).uai?.globals?.list?.()
        .then((data: any[]) => {
          setItems(data || []);
        })
        .catch((err: any) => {
          setError(err?.message || 'Failed to list globals');
          setItems([]);
        })
        .finally(() => setLoading(false));
    } else {
      runCommand('list', [activeView])
        .then((data) => {
          if (data) {
            const key = activeView;
            const itemList = data[key] || [];
            setItems(itemList);
          } else {
            setItems([]);
          }
        })
        .catch((err) => {
          setError(err.message);
          setItems([]);
        })
        .finally(() => setLoading(false));
    }
  }, [activeView, runCommand]);

  // Load validation results
  const handleValidate = useCallback(() => {
    setLoading(true);
    setError(null);
    setValidateResult(null);

    runCommand('validate')
      .then((data) => {
        setValidateResult(data);
      })
      .catch((err) => {
        setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [runCommand]);

  // When validate tab is selected, run validation
  useEffect(() => {
    if (activeView === 'validate') {
      handleValidate();
    }
  }, [activeView, handleValidate]);

  // Load file content for the viewer pane
  const loadViewerContent = useCallback(async (identifier: string) => {
    setViewerContent(null);
    setViewerPath(null);
    setViewerLoading(true);
    try {
      const data = await runCommand('view', [identifier]);
      if (data && typeof data === 'object') {
        // trait_mgr view may return { content, path } or raw content
        const content = data.content ?? (typeof data === 'string' ? data : JSON.stringify(data, null, 2));
        setViewerContent(typeof content === 'string' ? content : JSON.stringify(content, null, 2));
        setViewerPath(data.path || null);
      } else if (typeof data === 'string') {
        setViewerContent(data);
      } else {
        setViewerContent(null);
      }
    } catch {
      setViewerContent(null);
    } finally {
      setViewerLoading(false);
    }
  }, [runCommand]);

  // Copy viewer content to clipboard
  const handleCopyContent = useCallback(() => {
    if (!viewerContent) return;
    navigator.clipboard.writeText(viewerContent).then(() => {
      setCopyFeedback(true);
      setTimeout(() => setCopyFeedback(false), 1500);
    }).catch(() => {});
  }, [viewerContent]);

  // Select an item and load its file content into the viewer
  const handleSelectItem = useCallback((identifier: string, _type?: string) => {
    setSelectedItem(identifier);
    loadViewerContent(identifier);
  }, [loadViewerContent]);

  // Auto-select deep link item after items load
  const deepLinkHandledRef = useRef(false);
  useEffect(() => {
    if (!deepLinkId || deepLinkHandledRef.current || items.length === 0) return;
    // Search across all item types for the deep link ID
    const match = items.find((item: any) =>
      item.slug === deepLinkId || item.name === deepLinkId || item.id === deepLinkId
    );
    if (match) {
      deepLinkHandledRef.current = true;
      handleSelectItem(match.slug || match.name || match.id);
    }
  }, [deepLinkId, items, handleSelectItem]);

  const toggleCategory = useCallback((cat: string) => {
    setCollapsedCategories(prev => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }, []);

  // Group traits by category
  const traitsByCategory = activeView === 'traits'
    ? (items as TraitRecord[]).reduce<Record<string, TraitRecord[]>>((acc, t) => {
        if (!acc[t.category]) acc[t.category] = [];
        acc[t.category].push(t);
        return acc;
      }, {})
    : {};

  const viewTabs: { key: View; label: string }[] = [
    { key: 'globals', label: 'Globals' },
    { key: 'profiles', label: 'Profiles' },
    { key: 'roles', label: 'Roles' },
    { key: 'skills', label: 'Skills' },
    { key: 'traits', label: 'Traits' },
    { key: 'validate', label: 'Validate' },
  ];

  return (
    <div className="traits-mgr" data-tab-id={tabId}>
      {/* Header with status */}
      <div className="traits-mgr-header">
        <div className="traits-mgr-title">Context Manager</div>
        {status && (
          <div className="traits-mgr-status">
            <span>{status.traits} traits</span>
            <span>{status.roles} roles</span>
            <span>{status.skills} skills</span>
            <span>{status.profiles} profiles</span>
          </div>
        )}
      </div>

      {/* Tab buttons */}
      <div className="traits-mgr-tabs">
        {viewTabs.map(({ key, label }) => (
          <button
            key={key}
            className={`traits-mgr-tab-btn ${activeView === key ? 'active' : ''}`}
            onClick={(e) => { e.stopPropagation(); setActiveView(key); }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Content area */}
      <div className="traits-mgr-content">
        {error && (
          <div className="traits-mgr-error">{error}</div>
        )}

        {activeView === 'validate' && (
          <div className="traits-mgr-validate">
            {loading ? <div className="traits-mgr-loading">Validating...</div> : validateResult ? renderValidateResult(validateResult) : null}
          </div>
        )}

        {activeView !== 'validate' && (
          <div className="context-mgr-split">
            {/* Left: item list */}
            <div className="context-mgr-list">
              {activeView === 'traits' ? (
                // Grouped by category
                Object.entries(traitsByCategory).sort(([a], [b]) => a.localeCompare(b)).map(([category, traits]) => (
                  <div key={category} className="traits-mgr-category">
                    <div
                      className="traits-mgr-category-header"
                      onClick={() => toggleCategory(category)}
                    >
                      <span className="traits-mgr-collapse-icon">
                        {collapsedCategories.has(category) ? '\u25B6' : '\u25BC'}
                      </span>
                      <span className="traits-mgr-category-name">{category}</span>
                      <span className="traits-mgr-category-count">{traits.length}</span>
                    </div>
                    {!collapsedCategories.has(category) && (
                      <div className="traits-mgr-category-items">
                        {traits.map(t => (
                          <div
                            key={t.slug}
                            className={`traits-mgr-item ${selectedItem === t.slug ? 'selected' : ''}`}
                            onClick={() => handleSelectItem(t.slug, 'trait')}
                          >
                            <span className="traits-mgr-item-name">{t.name}</span>
                            {t.is_symlink && <span className="traits-mgr-item-badge" title="This file is a symlink (versioned)">&#x2197;</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))
              ) : (activeView === 'profiles' || activeView === 'roles' || activeView === 'skills') ? (
                items.map((item: any) => {
                  const id = item.id ?? item.name ?? 'unknown';
                  const name = item.name || item.id || 'unnamed';
                  const subCount = activeView === 'profiles'
                    ? (item.roles?.length ?? 0) + ' roles'
                    : (item.traits?.length ?? 0) + ' traits';
                  return (
                    <div
                      key={id}
                      className={`traits-mgr-item ${selectedItem === id ? 'selected' : ''}`}
                      onClick={() => handleSelectItem(id, activeView === 'profiles' ? 'profile' : activeView === 'roles' ? 'role' : 'skill')}
                    >
                      <span className="traits-mgr-item-name">{name}</span>
                      <span className="traits-mgr-item-sub">{subCount}</span>
                    </div>
                  );
                })
              ) : null}

              {loading && (
                <div className="traits-mgr-loading" style={{ padding: 16 }}>Loading...</div>
              )}
              {items.length === 0 && !loading && !error && (
                <div className="traits-mgr-empty">No items found.</div>
              )}
            </div>

            {/* Right: content viewer */}
            <div className="context-mgr-viewer">
              {selectedItem ? (
                viewerLoading ? (
                  <div className="traits-mgr-loading">Loading content...</div>
                ) : viewerContent !== null ? (
                  <>
                    <div className="context-mgr-viewer-header">
                      <span className="context-mgr-viewer-path" title={viewerPath || selectedItem}>
                        {viewerPath || selectedItem}
                      </span>
                      <button
                        className="context-mgr-viewer-copy"
                        onClick={handleCopyContent}
                      >
                        {copyFeedback ? 'Copied!' : 'Copy'}
                      </button>
                    </div>
                    <pre className="context-mgr-viewer-content">{viewerContent}</pre>
                  </>
                ) : (
                  <div className="traits-mgr-empty">No content available for this item.</div>
                )
              ) : (
                <div className="traits-mgr-empty">Select an item to view its content</div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

/** Render validation results */
function renderValidateResult(result: any): JSX.Element {
  if (!result) return <div className="traits-mgr-empty">No validation data.</div>;

  if (result.error) {
    return <div className="traits-mgr-error">{result.error}</div>;
  }

  const sections: JSX.Element[] = [];

  if (result.valid !== undefined) {
    sections.push(
      <div key="status" className={`traits-mgr-validate-status ${result.valid ? 'valid' : 'invalid'}`}>
        {result.valid ? 'All validations passed' : 'Validation issues found'}
      </div>
    );
  }

  if (result.summary) {
    sections.push(
      <div key="summary" className="traits-mgr-validate-summary">
        <pre>{JSON.stringify(result.summary, null, 2)}</pre>
      </div>
    );
  }

  for (const [key, value] of Object.entries(result)) {
    if (key === 'valid' || key === 'summary') continue;
    if (Array.isArray(value) && (value as any[]).length > 0) {
      sections.push(
        <div key={key} className="traits-mgr-validate-section">
          <h4>{formatSectionName(key)} ({(value as any[]).length})</h4>
          <ul>
            {(value as any[]).map((item, idx) => {
              if (typeof item === 'string') return <li key={idx}>{item}</li>;
              if (item.id && item.missing_traits) {
                return (
                  <li key={idx} className="traits-mgr-validate-item">
                    <strong>{item.id}</strong>
                    <span className="traits-mgr-validate-missing-label"> — {item.missing_traits.length} missing trait{item.missing_traits.length !== 1 ? 's' : ''}:</span>
                    <ul className="traits-mgr-validate-missing-list">
                      {item.missing_traits.map((t: string) => (
                        <li key={t} className="traits-mgr-validate-missing">{t}</li>
                      ))}
                    </ul>
                  </li>
                );
              }
              return <li key={idx}><pre style={{ margin: 0, fontSize: 11 }}>{JSON.stringify(item, null, 2)}</pre></li>;
            })}
          </ul>
        </div>
      );
    } else if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
      sections.push(
        <div key={key} className="traits-mgr-validate-section">
          <h4>{formatSectionName(key)}</h4>
          <pre>{JSON.stringify(value, null, 2)}</pre>
        </div>
      );
    }
  }

  if (sections.length === 0) {
    sections.push(
      <div key="raw" className="traits-mgr-validate-section">
        <pre>{JSON.stringify(result, null, 2)}</pre>
      </div>
    );
  }

  return <>{sections}</>;
}

function formatSectionName(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

export default ContextManagerPane;
