import React, { Component, type ErrorInfo, type ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  errorMessage: string;
}

const styles = {
  shell: {
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '32px',
    background: 'var(--bg-deep)',
    color: 'var(--text)',
    fontFamily: 'Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  } satisfies React.CSSProperties,
  panel: {
    width: '100%',
    maxWidth: '720px',
    border: '1px solid rgba(255, 255, 255, 0.12)',
    borderRadius: '16px',
    background: 'rgba(255, 255, 255, 0.04)',
    boxShadow: '0 24px 80px rgba(0, 0, 0, 0.45)',
    padding: '28px 32px',
  } satisfies React.CSSProperties,
  badge: {
    display: 'inline-block',
    marginBottom: '14px',
    padding: '4px 10px',
    borderRadius: '999px',
    background: 'rgba(255, 107, 107, 0.16)',
    color: 'var(--accent-red)',
    fontSize: '12px',
    fontWeight: 700,
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
  } satisfies React.CSSProperties,
  title: {
    margin: '0 0 12px 0',
    fontSize: '28px',
    lineHeight: 1.2,
    fontWeight: 700,
  } satisfies React.CSSProperties,
  body: {
    margin: '0 0 18px 0',
    color: 'var(--text-sec)',
    fontSize: '15px',
    lineHeight: 1.55,
  } satisfies React.CSSProperties,
  code: {
    margin: '0 0 22px 0',
    padding: '14px 16px',
    borderRadius: '10px',
    background: 'rgba(0, 0, 0, 0.35)',
    border: '1px solid rgba(255, 255, 255, 0.08)',
    color: 'var(--accent-red)',
    fontSize: '13px',
    lineHeight: 1.5,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  } satisfies React.CSSProperties,
  button: {
    appearance: 'none',
    border: 'none',
    borderRadius: '10px',
    padding: '12px 18px',
    background: 'var(--accent-blue-solid)',
    color: '#ffffff',
    fontSize: '14px',
    fontWeight: 700,
    cursor: 'pointer',
  } satisfies React.CSSProperties,
} as const;

export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  public constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      errorMessage: '',
    };
  }

  public static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return {
      hasError: true,
      errorMessage: error.message || String(error),
    };
  }

  public componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[UAI ErrorBoundary] Renderer crash intercepted.', error, info.componentStack);
  }

  public render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div style={styles.shell}>
        <div style={styles.panel}>
          <div style={styles.badge}>Renderer Error</div>
          <h1 style={styles.title}>Something in the UI crashed.</h1>
          <p style={styles.body}>
            The app caught the error before it could blank the entire window. You can reload the
            renderer and try again.
          </p>
          <pre style={styles.code}>{this.state.errorMessage || 'Unknown renderer error'}</pre>
          <button style={styles.button} onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      </div>
    );
  }
}
