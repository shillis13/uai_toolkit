/**
 * McpTab — MCP server and tool browser.
 *
 * Discovers configured MCP servers and their available tools.
 * Collapsible server sections. Non-modal, draggable tool detail panel.
 * Tool names show a tooltip with description and parameters.
 */

import { useState, useEffect, useCallback, useRef } from 'react';

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
  server: string;
  command: string;
  params: McpToolParam[];
}

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

function buildTooltip(tool: McpTool): string {
  const lines = [];
  if (tool.description) lines.push(tool.description);
  const params = extractParams(tool);
  if (params.length > 0) {
    lines.push('');
    lines.push('Parameters:');
    for (const p of params) {
      const req = p.required ? ' (required)' : '';
      const type = p.type ? `: ${p.type}` : '';
      const desc = p.description ? ` — ${p.description}` : '';
      const def = p.default !== undefined ? ` [default: ${p.default}]` : '';
      const enm = p.enum ? ` [${p.enum.join('|')}]` : '';
      lines.push(`  ${p.name}${type}${req}${desc}${def}${enm}`);
    }
  }
  return lines.join('\n');
}

// ─── Draggable detail panel ──────────────────────────────────────────

function ToolDetailPanel({ detail, onClose }: { detail: McpToolDetail; onClose: () => void }): JSX.Element {
  const panelRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 100, y: 100 });
  const [dragging, setDragging] = useState(false);
  const dragOffset = useRef({ x: 0, y: 0 });

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).tagName === 'BUTTON') return;
    setDragging(true);
    dragOffset.current = {
      x: e.clientX - pos.x,
      y: e.clientY - pos.y,
    };
  }, [pos]);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      setPos({
        x: e.clientX - dragOffset.current.x,
        y: e.clientY - dragOffset.current.y,
      });
    };
    const onUp = () => setDragging(false);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [dragging]);

  return (
    <div
      ref={panelRef}
      style={{
        position: 'fixed',
        left: pos.x,
        top: pos.y,
        zIndex: 1000,
        background: 'var(--bg-panel)',
        border: '1px solid var(--border)',
        borderRadius: '6px',
        padding: '12px 16px',
        width: '380px',
        maxHeight: '60vh',
        overflowY: 'auto',
        boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
        cursor: dragging ? 'grabbing' : 'default',
      }}
    >
      <div
        style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          marginBottom: '10px', cursor: 'grab', userSelect: 'none',
        }}
        onMouseDown={onMouseDown}
      >
        <span style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text)', fontFamily: 'monospace' }}>{detail.name}</span>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: '16px', cursor: 'pointer' }}
        >{'\u00D7'}</button>
      </div>

      <div style={{ fontSize: '11px', color: 'var(--text-sec)', display: 'flex', flexDirection: 'column', gap: '5px' }}>
        <div><span style={{ color: 'var(--text-muted)' }}>Full name:</span> <span style={{ fontFamily: 'monospace', fontSize: '10px' }}>{detail.fullName}</span></div>
        <div><span style={{ color: 'var(--text-muted)' }}>Server:</span> {detail.server}</div>
        {detail.description && <div style={{ marginTop: '4px', lineHeight: '1.4' }}>{detail.description}</div>}
      </div>

      {detail.params.length > 0 && (
        <div style={{ marginTop: '10px', borderTop: '1px solid var(--border)', paddingTop: '8px' }}>
          <div style={{ fontSize: '10px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>
            Parameters ({detail.params.length})
          </div>
          {detail.params.map(p => (
            <div key={p.name} style={{ marginBottom: '6px', fontSize: '11px' }}>
              <div style={{ display: 'flex', gap: '4px', alignItems: 'baseline' }}>
                <span style={{ fontFamily: 'monospace', color: 'var(--accent-blue)', fontWeight: 600 }}>{p.name}</span>
                {p.type && <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>{p.type}</span>}
                {p.required && <span style={{ color: 'var(--accent-red)', fontSize: '9px', fontWeight: 600 }}>required</span>}
              </div>
              {p.description && <div style={{ color: 'var(--text-sec)', fontSize: '10px', marginLeft: '8px', lineHeight: '1.3' }}>{p.description}</div>}
              {p.enum && <div style={{ color: 'var(--text-muted)', fontSize: '10px', marginLeft: '8px', fontFamily: 'monospace' }}>{p.enum.join(' | ')}</div>}
              {p.default !== undefined && <div style={{ color: 'var(--text-muted)', fontSize: '10px', marginLeft: '8px' }}>default: {String(p.default)}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main component ──────────────────────────────────────────────────

export default function McpTab(): JSX.Element {
  const [servers, setServers] = useState<McpServerInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [collapsedServers, setCollapsedServers] = useState<Set<string>>(new Set());
  const [toolDetail, setToolDetail] = useState<McpToolDetail | null>(null);

  const loadServers = useCallback(async () => {
    setLoading(true);
    try {
      const result = await window.uai.mcp.list();
      setServers(result || []);
      setCollapsedServers(prev => {
        if (prev.size === 0 && result?.length) {
          return new Set(result.map((s: McpServerInfo) => s.name));
        }
        return prev;
      });
    } catch {
      setServers([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadServers();
  }, [loadServers]);

  const toggleServer = useCallback((name: string) => {
    setCollapsedServers(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const isLocalServer = useCallback((server: McpServerInfo): boolean => {
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
  }, []);

  const handleToolClick = useCallback((tool: McpTool, server: McpServerInfo) => {
    setToolDetail({
      name: tool.name,
      fullName: tool.fullName,
      description: tool.description,
      server: server.name,
      command: server.command,
      params: extractParams(tool),
    });
  }, []);

  const totalTools = servers.reduce((n, s) => n + s.tools.length, 0);

  if (loading && servers.length === 0) {
    return <div style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px' }}>Discovering MCP servers...</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, overflow: 'hidden' }}>
      <div style={{ padding: '8px 12px', fontSize: '12px', fontWeight: 600, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: '6px', borderBottom: '1px solid var(--border)' }}>
        MCP Servers
        <span style={{ fontSize: '10px', fontWeight: 400, color: 'var(--text-muted)' }}>
          {servers.length} servers, {totalTools} tools
        </span>
        <button
          onClick={loadServers}
          style={{ marginLeft: 'auto', background: 'none', border: '1px solid var(--border)', borderRadius: '3px', color: 'var(--text-sec)', fontSize: '10px', padding: '2px 6px', cursor: 'pointer' }}
          title="Refresh"
        >{'\u21BB'}</button>
      </div>

      {servers.length === 0 && !loading && (
        <div style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px' }}>No MCP servers configured</div>
      )}

      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {servers.map(server => {
          const isCollapsed = collapsedServers.has(server.name);
          const statusColor = server.status === 'ok' ? 'var(--accent-green)'
            : (server.status === 'error' || server.status === 'timeout') ? 'var(--accent-red)'
            : 'var(--text-muted)';

          return (
            <div key={server.name} style={{ borderBottom: '1px solid var(--border)' }}>
              <div
                onClick={() => toggleServer(server.name)}
                style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 12px', cursor: 'pointer', userSelect: 'none', fontSize: '12px' }}
              >
                <span style={{ fontSize: '21px', color: 'var(--text-sec)' }}>{isCollapsed ? '\u25B8' : '\u25BE'}</span>
                <span
                  style={{ color: statusColor, fontSize: '12px' }}
                  title={server.status === 'ok' ? 'Connected' : server.error || server.status || 'Unknown'}
                >{'\u26A1'}</span>
                <span style={{ fontWeight: 600, color: 'var(--text)', flex: 1 }}>
                  {server.name}
                  {isLocalServer(server) && (
                    <span style={{ fontSize: '9px', color: 'var(--text-muted)', fontWeight: 400, marginLeft: '5px', verticalAlign: 'middle' }}>{'\u2302 local'}</span>
                  )}
                </span>
                <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{server.tools.length}</span>
              </div>
              {!isCollapsed && (
                <div style={{ paddingBottom: '4px' }}>
                  {server.tools.length === 0 ? (
                    <div style={{ padding: '4px 12px 4px 32px', fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                      {server.status === 'error' ? `Error: ${server.error || 'connection failed'}` : 'No tools discovered'}
                    </div>
                  ) : (
                    server.tools.map(tool => (
                      <div
                        key={tool.fullName}
                        onClick={() => handleToolClick(tool, server)}
                        title={buildTooltip(tool)}
                        style={{ padding: '3px 12px 3px 32px', fontSize: '11px', fontFamily: 'monospace', color: 'var(--text-sec)', cursor: 'pointer', whiteSpace: 'pre-wrap' }}
                        onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'var(--bg-hover)')}
                        onMouseLeave={e => (e.currentTarget.style.backgroundColor = '')}
                      >
                        {tool.name}
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Non-modal, draggable tool detail panel */}
      {toolDetail && (
        <ToolDetailPanel detail={toolDetail} onClose={() => setToolDetail(null)} />
      )}
    </div>
  );
}
