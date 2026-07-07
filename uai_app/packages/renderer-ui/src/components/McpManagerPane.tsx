/**
 * McpManagerPane -- MCP server and tool manager.
 *
 * Split-panel layout (left server/tool list, right detail).
 * Replaces the old McpTab that lived in the right panel.
 * Follows the ScheduledTasksPane / ContextManagerPane pattern.
 *
 * Backed by window.uai.mcp IPC namespace.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useToast } from './Toast';
import { TabNavArrows } from './TabNavArrows';
import { useViewport } from '../viewport';

// ---- Types ----------------------------------------------------------------

interface McpToolParam {
  name: string;
  type?: string;
  description?: string;
  required?: boolean;
  default?: unknown;
  enum?: string[];
}

interface McpTool {
  name: string;
  fullName: string;
  description?: string;
  inputSchema?: {
    type?: string;
    properties?: Record<string, {
      type?: string;
      description?: string;
      default?: unknown;
      enum?: string[];
    }>;
    required?: string[];
  };
}

interface McpServerInfo {
  name: string;
  command: string;
  args?: string[];
  status?: string;
  error?: string;
  tools: McpTool[];
}

interface McpToolDetail {
  name: string;
  fullName: string;
  description?: string;
  server: McpServerInfo;
  params: McpToolParam[];
}

interface ConfigSection {
  filePath: string;
  content: string;
  shortPath: string;
}

interface ServerFileInfo {
  name: string;
  size: number;
  path: string;
}

// ---- Helpers ---------------------------------------------------------------

function extractParams(tool: McpTool): McpToolParam[] {
  const schema = tool.inputSchema;
  if (!schema?.properties) return [];
  const required = new Set(schema.required || []);
  return Object.entries(schema.properties).map(([name, prop]) => ({
    name,
    type: prop.type,
    description: prop.description,
    required: required.has(name),
    default: prop.default,
    enum: prop.enum,
  }));
}

function isLocalServer(server: McpServerInfo): boolean {
  const cmd = server.command || '';
  const name = server.name.toLowerCase();
  return name.includes('local')
    || cmd.startsWith('/Users/')
    || cmd.startsWith('/home/')
    || cmd.startsWith('./')
    || cmd.startsWith('../')
    || cmd === 'python3'
    || cmd === 'python'
    || cmd === 'node';
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ---- Selection types -------------------------------------------------------

type Selection =
  | { type: 'server'; server: McpServerInfo }
  | { type: 'tool'; tool: McpTool; server: McpServerInfo };

// ---- Component: Server List (Left Panel) -----------------------------------

function ServerList({
  servers,
  collapsedServers,
  onToggleServer,
  selection,
  onSelect,
  testing,
  testResults,
  onTestConnections,
  onRefresh,
  loading,
}: {
  servers: McpServerInfo[];
  collapsedServers: Set<string>;
  onToggleServer: (name: string) => void;
  selection: Selection | null;
  onSelect: (sel: Selection) => void;
  testing: boolean;
  testResults: Record<string, 'ok' | 'error'>;
  onTestConnections: () => void;
  onRefresh: () => void;
  loading: boolean;
}): JSX.Element {
  const totalTools = servers.reduce((n, s) => n + s.tools.length, 0);

  return (
    <div className="mcp-mgr-list">
      <div className="mcp-mgr-list-header">
        <span className="mcp-mgr-list-label">
          {servers.length} servers, {totalTools} tools
        </span>
        <div className="mcp-mgr-list-actions">
          <button
            className="mcp-mgr-action-btn"
            onClick={onTestConnections}
            disabled={testing}
            title="Test all server connections"
          >
            {testing ? 'Testing...' : 'Test'}
          </button>
          <button
            className="mcp-mgr-action-btn"
            onClick={onRefresh}
            disabled={loading}
            title="Refresh server list"
          >
            {'\u21BB'}
          </button>
        </div>
      </div>

      <div className="mcp-mgr-server-list">
        {servers.map(server => {
          const isCollapsed = collapsedServers.has(server.name);
          const isServerSelected = selection?.type === 'server' && selection.server.name === server.name;
          const local = isLocalServer(server);

          // Determine status indicator
          let statusIcon = '\u26A1';
          let statusColor = 'var(--text-muted)';
          if (testResults[server.name]) {
            statusIcon = testResults[server.name] === 'ok' ? '\u2713' : '\u2717';
            statusColor = testResults[server.name] === 'ok' ? 'var(--accent-green)' : 'var(--accent-red)';
          } else if (server.status === 'ok') {
            statusColor = 'var(--accent-green)';
          } else if (server.status === 'error' || server.status === 'timeout') {
            statusColor = 'var(--accent-red)';
          }

          return (
            <div key={server.name} className="mcp-mgr-server-group">
              <div
                className={`mcp-mgr-server-row${isServerSelected ? ' selected' : ''}`}
                onClick={() => onSelect({ type: 'server', server })}
              >
                <span
                  className="mcp-mgr-chevron"
                  onClick={(e) => { e.stopPropagation(); onToggleServer(server.name); }}
                >
                  {isCollapsed ? '\u25B8' : '\u25BE'}
                </span>
                <span className="mcp-mgr-status-dot" style={{ color: statusColor }}>
                  {statusIcon}
                </span>
                <span className="mcp-mgr-server-name">{server.name}</span>
                {local && <span className="mcp-mgr-local-badge">{'\u2302'} local</span>}
                <span className="mcp-mgr-tool-count">{server.tools.length}</span>
              </div>

              {!isCollapsed && (
                <div className="mcp-mgr-tool-list">
                  {server.tools.length === 0 ? (
                    <div className="mcp-mgr-tool-empty">
                      {server.status === 'error'
                        ? `Error: ${server.error || 'connection failed'}`
                        : 'No tools discovered'}
                    </div>
                  ) : (
                    server.tools.map(tool => {
                      const isToolSelected = selection?.type === 'tool'
                        && selection.tool.fullName === tool.fullName;
                      return (
                        <div
                          key={tool.fullName}
                          className={`mcp-mgr-tool-row${isToolSelected ? ' selected' : ''}`}
                          onClick={() => onSelect({ type: 'tool', tool, server })}
                        >
                          {tool.name}
                        </div>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---- Component: Tool Detail (Right Panel) -----------------------------------

function ToolDetailView({
  tool,
  server,
  configSection,
  configLoading,
  onLoadConfig,
  serverFiles,
  serverFilesLoading,
  onLoadServerFiles,
  expandedFiles,
  fileContents,
  fileContentsLoading,
  onToggleFileExpand,
}: {
  tool: McpTool;
  server: McpServerInfo;
  configSection: ConfigSection | null;
  configLoading: boolean;
  onLoadConfig: (serverName: string) => void;
  serverFiles: ServerFileInfo[];
  serverFilesLoading: boolean;
  onLoadServerFiles: (serverName: string) => void;
  expandedFiles: Set<string>;
  fileContents: Record<string, string>;
  fileContentsLoading: Set<string>;
  onToggleFileExpand: (filePath: string) => void;
}): JSX.Element {
  const params = extractParams(tool);
  const { showToast } = useToast();
  const [configExpanded, setConfigExpanded] = useState(false);
  const local = isLocalServer(server);

  // Load config on first render
  useEffect(() => {
    onLoadConfig(server.name);
  }, [server.name, onLoadConfig]);

  // Load server files on first render (for local servers)
  useEffect(() => {
    if (local) {
      onLoadServerFiles(server.name);
    }
  }, [server.name, local, onLoadServerFiles]);

  return (
    <div className="mcp-mgr-detail">
      {/* Tool header */}
      <div className="mcp-mgr-detail-header">
        <h3 className="mcp-mgr-detail-name">{tool.name}</h3>
      </div>

      <div className="mcp-mgr-detail-meta">
        <div className="mcp-mgr-detail-row">
          <span className="mcp-mgr-detail-label">Full Name</span>
          <span
            className="mcp-mgr-detail-value mono copyable"
            onClick={() => { window.uai.clipboard.write(tool.fullName); showToast('Copied full name', 'info'); }}
            title="Click to copy"
          >
            {tool.fullName}
          </span>
        </div>
        <div className="mcp-mgr-detail-row">
          <span className="mcp-mgr-detail-label">Server</span>
          <span className="mcp-mgr-detail-value">{server.name}</span>
        </div>
        {tool.description && (
          <div className="mcp-mgr-detail-row">
            <span className="mcp-mgr-detail-label">Description</span>
            <span className="mcp-mgr-detail-value mcp-mgr-desc-text">{tool.description}</span>
          </div>
        )}
      </div>

      {/* Parameters table */}
      {params.length > 0 && (
        <div className="mcp-mgr-section">
          <div className="mcp-mgr-section-title">
            Parameters ({params.length})
          </div>
          <table className="mcp-mgr-params-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Req</th>
                <th>Description</th>
                <th>Default</th>
                <th>Enum</th>
              </tr>
            </thead>
            <tbody>
              {params.map(p => (
                <tr key={p.name}>
                  <td className="mcp-mgr-param-name">{p.name}</td>
                  <td className="mcp-mgr-param-type">{p.type || '\u2014'}</td>
                  <td className="mcp-mgr-param-req">{p.required ? '\u2713' : ''}</td>
                  <td className="mcp-mgr-param-desc">{p.description || '\u2014'}</td>
                  <td className="mcp-mgr-param-default">
                    {p.default !== undefined ? String(p.default) : '\u2014'}
                  </td>
                  <td className="mcp-mgr-param-enum">
                    {p.enum ? p.enum.join(' | ') : '\u2014'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Config section */}
      <div className="mcp-mgr-section">
        <div className="mcp-mgr-section-title">Config</div>
        {configLoading && (
          <div className="mcp-mgr-loading-text">Loading config...</div>
        )}
        {!configLoading && configSection && (
          <div className="mcp-mgr-config-block">
            <div className="mcp-mgr-config-path-row">
              <span className="mcp-mgr-detail-label">Config File</span>
              <span
                className="mcp-mgr-detail-value mono copyable"
                onClick={() => window.uai.openPath(configSection.filePath)}
                title={`${configSection.filePath} (click to open)`}
              >
                {configSection.shortPath}
              </span>
            </div>
            <div
              className="mcp-mgr-config-chevron"
              onClick={() => setConfigExpanded(v => !v)}
            >
              {configExpanded ? '\u25BE' : '\u25B8'} {configExpanded ? 'Hide' : 'Show'} config section
            </div>
            {configExpanded && (
              <pre className="mcp-mgr-config-content">{configSection.content}</pre>
            )}
          </div>
        )}
        {!configLoading && !configSection && (
          <div className="mcp-mgr-empty-text">No config file found for this server.</div>
        )}
      </div>

      {/* Local server files */}
      {local && (
        <div className="mcp-mgr-section">
          <div className="mcp-mgr-section-title">Server Files</div>
          {serverFilesLoading && (
            <div className="mcp-mgr-loading-text">Loading files...</div>
          )}
          {!serverFilesLoading && serverFiles.length === 0 && (
            <div className="mcp-mgr-empty-text">No server files found.</div>
          )}
          {!serverFilesLoading && serverFiles.length > 0 && (
            <div className="mcp-mgr-file-list">
              {serverFiles.map(f => {
                const isExpanded = expandedFiles.has(f.path);
                const content = fileContents[f.path];
                const isLoadingContent = fileContentsLoading.has(f.path);
                return (
                  <div key={f.path} className="mcp-mgr-file-item">
                    <div className="mcp-mgr-file-header">
                      <span
                        className="mcp-mgr-file-expand"
                        onClick={() => onToggleFileExpand(f.path)}
                      >
                        {isExpanded ? '\u25BE' : '\u25B8'}
                      </span>
                      <span
                        className="mcp-mgr-file-name mono copyable"
                        onClick={() => window.uai.openPath(f.path)}
                        title={`${f.path} (click to open)`}
                      >
                        {f.name}
                      </span>
                      <span className="mcp-mgr-file-size">{formatBytes(f.size)}</span>
                    </div>
                    {isExpanded && (
                      <div className="mcp-mgr-file-content-wrap">
                        {isLoadingContent && <div className="mcp-mgr-loading-text">Loading...</div>}
                        {!isLoadingContent && content !== undefined && (
                          <pre className="mcp-mgr-file-content">{content}</pre>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---- Component: Server Detail (Right Panel, no tool selected) ----------------

function ServerDetailView({
  server,
  testResult,
  configSection,
  configLoading,
  onLoadConfig,
  serverFiles,
  serverFilesLoading,
  onLoadServerFiles,
  expandedFiles,
  fileContents,
  fileContentsLoading,
  onToggleFileExpand,
}: {
  server: McpServerInfo;
  testResult?: 'ok' | 'error';
  configSection: ConfigSection | null;
  configLoading: boolean;
  onLoadConfig: (serverName: string) => void;
  serverFiles: ServerFileInfo[];
  serverFilesLoading: boolean;
  onLoadServerFiles: (serverName: string) => void;
  expandedFiles: Set<string>;
  fileContents: Record<string, string>;
  fileContentsLoading: Set<string>;
  onToggleFileExpand: (filePath: string) => void;
}): JSX.Element {
  const local = isLocalServer(server);
  const [configExpanded, setConfigExpanded] = useState(false);

  useEffect(() => {
    onLoadConfig(server.name);
  }, [server.name, onLoadConfig]);

  useEffect(() => {
    if (local) {
      onLoadServerFiles(server.name);
    }
  }, [server.name, local, onLoadServerFiles]);

  const statusColor = server.status === 'ok' ? 'var(--accent-green)'
    : (server.status === 'error' || server.status === 'timeout') ? 'var(--accent-red)'
    : 'var(--text-muted)';

  return (
    <div className="mcp-mgr-detail">
      <div className="mcp-mgr-detail-header">
        <h3 className="mcp-mgr-detail-name">{server.name}</h3>
        {local && <span className="mcp-mgr-local-badge">{'\u2302'} local</span>}
      </div>

      <div className="mcp-mgr-detail-meta">
        <div className="mcp-mgr-detail-row">
          <span className="mcp-mgr-detail-label">Command</span>
          <span className="mcp-mgr-detail-value mono">{server.command}</span>
        </div>
        {server.args && server.args.length > 0 && (
          <div className="mcp-mgr-detail-row">
            <span className="mcp-mgr-detail-label">Args</span>
            <span className="mcp-mgr-detail-value mono">{server.args.join(' ')}</span>
          </div>
        )}
        <div className="mcp-mgr-detail-row">
          <span className="mcp-mgr-detail-label">Status</span>
          <span className="mcp-mgr-detail-value" style={{ color: statusColor }}>
            {server.status || 'unknown'}
            {testResult && (
              <span style={{ marginLeft: '8px', color: testResult === 'ok' ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                (test: {testResult === 'ok' ? '\u2713 pass' : '\u2717 fail'})
              </span>
            )}
          </span>
        </div>
        {server.error && (
          <div className="mcp-mgr-detail-row">
            <span className="mcp-mgr-detail-label">Error</span>
            <span className="mcp-mgr-detail-value mcp-mgr-error-text">{server.error}</span>
          </div>
        )}
        <div className="mcp-mgr-detail-row">
          <span className="mcp-mgr-detail-label">Tools</span>
          <span className="mcp-mgr-detail-value">{server.tools.length}</span>
        </div>
      </div>

      {/* Config section */}
      <div className="mcp-mgr-section">
        <div className="mcp-mgr-section-title">Config</div>
        {configLoading && (
          <div className="mcp-mgr-loading-text">Loading config...</div>
        )}
        {!configLoading && configSection && (
          <div className="mcp-mgr-config-block">
            <div className="mcp-mgr-config-path-row">
              <span className="mcp-mgr-detail-label">Config File</span>
              <span
                className="mcp-mgr-detail-value mono copyable"
                onClick={() => window.uai.openPath(configSection.filePath)}
                title={`${configSection.filePath} (click to open)`}
              >
                {configSection.shortPath}
              </span>
            </div>
            <div
              className="mcp-mgr-config-chevron"
              onClick={() => setConfigExpanded(v => !v)}
            >
              {configExpanded ? '\u25BE' : '\u25B8'} {configExpanded ? 'Hide' : 'Show'} config section
            </div>
            {configExpanded && (
              <pre className="mcp-mgr-config-content">{configSection.content}</pre>
            )}
          </div>
        )}
        {!configLoading && !configSection && (
          <div className="mcp-mgr-empty-text">No config file found for this server.</div>
        )}
      </div>

      {/* Local server files */}
      {local && (
        <div className="mcp-mgr-section">
          <div className="mcp-mgr-section-title">Server Files</div>
          {serverFilesLoading && (
            <div className="mcp-mgr-loading-text">Loading files...</div>
          )}
          {!serverFilesLoading && serverFiles.length === 0 && (
            <div className="mcp-mgr-empty-text">No server files found.</div>
          )}
          {!serverFilesLoading && serverFiles.length > 0 && (
            <div className="mcp-mgr-file-list">
              {serverFiles.map(f => {
                const isExpanded = expandedFiles.has(f.path);
                const content = fileContents[f.path];
                const isLoadingContent = fileContentsLoading.has(f.path);
                return (
                  <div key={f.path} className="mcp-mgr-file-item">
                    <div className="mcp-mgr-file-header">
                      <span
                        className="mcp-mgr-file-expand"
                        onClick={() => onToggleFileExpand(f.path)}
                      >
                        {isExpanded ? '\u25BE' : '\u25B8'}
                      </span>
                      <span
                        className="mcp-mgr-file-name mono copyable"
                        onClick={() => window.uai.openPath(f.path)}
                        title={`${f.path} (click to open)`}
                      >
                        {f.name}
                      </span>
                      <span className="mcp-mgr-file-size">{formatBytes(f.size)}</span>
                    </div>
                    {isExpanded && (
                      <div className="mcp-mgr-file-content-wrap">
                        {isLoadingContent && <div className="mcp-mgr-loading-text">Loading...</div>}
                        {!isLoadingContent && content !== undefined && (
                          <pre className="mcp-mgr-file-content">{content}</pre>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---- Main Component ---------------------------------------------------------

interface McpManagerPaneProps {
  tabId?: string;
}

export default function McpManagerPane({ tabId }: McpManagerPaneProps): JSX.Element {
  const { showToast } = useToast();
  const [servers, setServers] = useState<McpServerInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [collapsedServers, setCollapsedServers] = useState<Set<string>>(new Set());
  const [selection, setSelection] = useState<Selection | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResults, setTestResults] = useState<Record<string, 'ok' | 'error'>>({});

  // Config cache
  const [configCache, setConfigCache] = useState<Record<string, ConfigSection | null>>({});
  const [configLoading, setConfigLoading] = useState<Set<string>>(new Set());

  // Server files cache
  const [serverFilesCache, setServerFilesCache] = useState<Record<string, ServerFileInfo[]>>({});
  const [serverFilesLoading, setServerFilesLoading] = useState<Set<string>>(new Set());

  // File content expansion and caching
  const [expandedFiles, setExpandedFiles] = useState<Set<string>>(new Set());
  const [fileContents, setFileContents] = useState<Record<string, string>>({});
  const [fileContentsLoading, setFileContentsLoading] = useState<Set<string>>(new Set());

  // Viewport reporter — exposes the MCP servers (with per-server tool counts and
  // status as inline children) plus the current selection to describeViewport() /
  // agents / the e2e harness, so this pane shows content in "Capture Content"
  // instead of an empty node. (No text filter/search exists in this pane yet, so
  // none is reported; there is no Command Bus command for MCP actions — they run
  // via window.uai.mcp directly — so no `actions` are advertised.)
  useViewport('mcp_manager', () => ({
    visible: true,
    label: 'MCP Manager',
    state: {
      totalServers: servers.length,
      totalTools: servers.reduce((n, s) => n + (s.tools?.length ?? 0), 0),
      loading,
      testing,
      selected: selection
        ? selection.type === 'server'
          ? {
              type: 'server',
              server: selection.server.name,
              status: selection.server.status ?? null,
              tools: selection.server.tools?.length ?? 0,
            }
          : { type: 'tool', tool: selection.tool.fullName, server: selection.server.name }
        : null,
    },
    children: servers.slice(0, 20).map((s) => ({
      id: `mcp_server:${s.name}`,
      label: s.name,
      visible: true,
      state: {
        status: s.status ?? testResults[s.name] ?? null,
        tools: s.tools?.length ?? 0,
        command: s.command,
        error: s.error ?? null,
        selected: selection?.type === 'server' && selection.server.name === s.name,
      },
      children: [],
    })),
  }));

  // Load servers on mount
  const loadServers = useCallback(async () => {
    setLoading(true);
    try {
      const result = await window.uai.mcp.list();
      setServers(result || []);
      // Start collapsed if first load
      if (result?.length && collapsedServers.size === 0) {
        setCollapsedServers(new Set(result.map((s: McpServerInfo) => s.name)));
      }
    } catch {
      setServers([]);
      showToast('Failed to load MCP servers', 'error');
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    loadServers();
  }, [loadServers]);

  // Toggle server collapse
  const toggleServer = useCallback((name: string) => {
    setCollapsedServers(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  // Test connections: re-run discovery and check status
  const testConnections = useCallback(async () => {
    setTesting(true);
    setTestResults({});
    try {
      const result = await window.uai.mcp.list();
      const results: Record<string, 'ok' | 'error'> = {};
      for (const server of (result || [])) {
        results[server.name] = server.status === 'ok' ? 'ok' : 'error';
      }
      setTestResults(results);
      setServers(result || []);
      const ok = Object.values(results).filter(v => v === 'ok').length;
      const fail = Object.values(results).filter(v => v === 'error').length;
      showToast(`Test complete: ${ok} ok, ${fail} failed`, ok === Object.values(results).length ? 'info' : 'warning');
    } catch {
      showToast('Test failed', 'error');
    } finally {
      setTesting(false);
    }
  }, [showToast]);

  // Load config for a server
  const loadConfig = useCallback(async (serverName: string) => {
    if (configCache[serverName] !== undefined || configLoading.has(serverName)) return;
    setConfigLoading(prev => { const n = new Set(prev); n.add(serverName); return n; });
    try {
      const result = await window.uai.mcp.readConfigFile(serverName);
      setConfigCache(prev => ({
        ...prev,
        [serverName]: result || null,
      }));
    } catch {
      setConfigCache(prev => ({ ...prev, [serverName]: null }));
    } finally {
      setConfigLoading(prev => { const n = new Set(prev); n.delete(serverName); return n; });
    }
  }, [configCache, configLoading]);

  // Load server files
  const loadServerFiles = useCallback(async (serverName: string) => {
    if (serverFilesCache[serverName] !== undefined || serverFilesLoading.has(serverName)) return;
    setServerFilesLoading(prev => { const n = new Set(prev); n.add(serverName); return n; });
    try {
      const result = await window.uai.mcp.listServerFiles(serverName);
      setServerFilesCache(prev => ({ ...prev, [serverName]: result || [] }));
    } catch {
      setServerFilesCache(prev => ({ ...prev, [serverName]: [] }));
    } finally {
      setServerFilesLoading(prev => { const n = new Set(prev); n.delete(serverName); return n; });
    }
  }, [serverFilesCache, serverFilesLoading]);

  // Toggle file content expansion
  const toggleFileExpand = useCallback(async (filePath: string) => {
    setExpandedFiles(prev => {
      const n = new Set(prev);
      if (n.has(filePath)) { n.delete(filePath); }
      else {
        n.add(filePath);
        // Load content if not cached
        if (fileContents[filePath] === undefined && !fileContentsLoading.has(filePath)) {
          setFileContentsLoading(prevL => { const nl = new Set(prevL); nl.add(filePath); return nl; });
          window.uai.mcp.readServerFile(filePath).then(content => {
            setFileContents(prevC => ({ ...prevC, [filePath]: content || '' }));
          }).catch(() => {
            setFileContents(prevC => ({ ...prevC, [filePath]: '(failed to read file)' }));
          }).finally(() => {
            setFileContentsLoading(prevL => { const nl = new Set(prevL); nl.delete(filePath); return nl; });
          });
        }
      }
      return n;
    });
  }, [fileContents, fileContentsLoading]);

  // Get the currently selected server name for config/files
  const selectedServerName = selection?.type === 'server'
    ? selection.server.name
    : selection?.type === 'tool'
      ? selection.server.name
      : null;

  if (loading && servers.length === 0) {
    return (
      <div className="mcp-mgr">
        <div className="mcp-mgr-header">
          <div className="mgr-title-group"><TabNavArrows /><h2 className="mcp-mgr-title">MCP Manager</h2></div>
        </div>
        <div className="mcp-mgr-loading">Discovering MCP servers...</div>
      </div>
    );
  }

  return (
    <div className="mcp-mgr">
      <div className="mcp-mgr-header">
        <div className="mgr-title-group"><TabNavArrows /><h2 className="mcp-mgr-title">MCP Manager</h2></div>
        <div className="mcp-mgr-header-actions">
          <span className="mcp-mgr-header-stats">
            {servers.length} servers, {servers.reduce((n, s) => n + s.tools.length, 0)} tools
          </span>
        </div>
      </div>

      <div className="mcp-mgr-split">
        <ServerList
          servers={servers}
          collapsedServers={collapsedServers}
          onToggleServer={toggleServer}
          selection={selection}
          onSelect={setSelection}
          testing={testing}
          testResults={testResults}
          onTestConnections={testConnections}
          onRefresh={loadServers}
          loading={loading}
        />

        {/* Right panel: detail view */}
        <div className="mcp-mgr-detail-container">
          {!selection && (
            <div className="mcp-mgr-placeholder">
              <p>Select a server or tool to view details.</p>
              <p className="mcp-mgr-placeholder-sub">
                Use the [Test] button to verify all server connections.
              </p>
            </div>
          )}

          {selection?.type === 'tool' && (
            <ToolDetailView
              tool={selection.tool}
              server={selection.server}
              configSection={configCache[selection.server.name] || null}
              configLoading={configLoading.has(selection.server.name)}
              onLoadConfig={loadConfig}
              serverFiles={serverFilesCache[selection.server.name] || []}
              serverFilesLoading={serverFilesLoading.has(selection.server.name)}
              onLoadServerFiles={loadServerFiles}
              expandedFiles={expandedFiles}
              fileContents={fileContents}
              fileContentsLoading={fileContentsLoading}
              onToggleFileExpand={toggleFileExpand}
            />
          )}

          {selection?.type === 'server' && (
            <ServerDetailView
              server={selection.server}
              testResult={testResults[selection.server.name]}
              configSection={configCache[selection.server.name] || null}
              configLoading={configLoading.has(selection.server.name)}
              onLoadConfig={loadConfig}
              serverFiles={serverFilesCache[selection.server.name] || []}
              serverFilesLoading={serverFilesLoading.has(selection.server.name)}
              onLoadServerFiles={loadServerFiles}
              expandedFiles={expandedFiles}
              fileContents={fileContents}
              fileContentsLoading={fileContentsLoading}
              onToggleFileExpand={toggleFileExpand}
            />
          )}
        </div>
      </div>
    </div>
  );
}
