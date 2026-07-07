/**
 * WebAIPane — Renders a web-based AI chat interface (ChatGPT, Grok, Gemini, etc.)
 * inside an Electron <webview> with a persistent session partition.
 *
 * - partition="persist:webai" — cookies/auth persist across app restarts
 * - allowpopups — OAuth login flows work
 * - new-window events open external links in the default browser
 *
 * Ported from UCI WebAIPane. Requires webviewTag: true in BrowserWindow webPreferences.
 */

import { useEffect, useRef, useState, useCallback } from 'react';

interface WebAIPaneProps {
  url: string;
}

const WebAIPane = ({ url }: WebAIPaneProps): JSX.Element => {
  const webviewRef = useRef<HTMLWebViewElement | null>(null);
  const [currentUrl, setCurrentUrl] = useState(url);
  const [canGoBack, setCanGoBack] = useState(false);
  const [canGoForward, setCanGoForward] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const handleBack = useCallback(() => {
    const wv = webviewRef.current as any;
    if (wv?.goBack) wv.goBack();
  }, []);

  const handleForward = useCallback(() => {
    const wv = webviewRef.current as any;
    if (wv?.goForward) wv.goForward();
  }, []);

  const handleReload = useCallback(() => {
    const wv = webviewRef.current as any;
    if (wv?.reload) wv.reload();
  }, []);

  const handleOpenExternal = useCallback(() => {
    if (currentUrl) {
      // Electron shell.openExternal via window.open fallback
      window.open(currentUrl, '_blank');
    }
  }, [currentUrl]);

  useEffect(() => {
    const wv = webviewRef.current as any;
    if (!wv) return;

    const onDidNavigate = (e: any) => {
      setCurrentUrl(e.url);
      setCanGoBack(wv.canGoBack());
      setCanGoForward(wv.canGoForward());
    };

    const onDidNavigateInPage = (e: any) => {
      setCurrentUrl(e.url);
      setCanGoBack(wv.canGoBack());
      setCanGoForward(wv.canGoForward());
    };

    const onDidStartLoading = () => setIsLoading(true);
    const onDidStopLoading = () => {
      setIsLoading(false);
      setCanGoBack(wv.canGoBack());
      setCanGoForward(wv.canGoForward());
    };

    const onNewWindow = (e: any) => {
      // Prevent new Electron windows -- open in default browser instead
      e.preventDefault();
      if (e.url) {
        window.open(e.url, '_blank');
      }
    };

    wv.addEventListener('did-navigate', onDidNavigate);
    wv.addEventListener('did-navigate-in-page', onDidNavigateInPage);
    wv.addEventListener('did-start-loading', onDidStartLoading);
    wv.addEventListener('did-stop-loading', onDidStopLoading);
    wv.addEventListener('new-window', onNewWindow);

    return () => {
      wv.removeEventListener('did-navigate', onDidNavigate);
      wv.removeEventListener('did-navigate-in-page', onDidNavigateInPage);
      wv.removeEventListener('did-start-loading', onDidStartLoading);
      wv.removeEventListener('did-stop-loading', onDidStopLoading);
      wv.removeEventListener('new-window', onNewWindow);
    };
  }, []);

  return (
    <div className="webai-pane">
      <div className="webai-toolbar">
        <button
          className="webai-toolbar-btn"
          onClick={handleBack}
          disabled={!canGoBack}
          title="Back"
        >
          {'\u2190'}
        </button>
        <button
          className="webai-toolbar-btn"
          onClick={handleForward}
          disabled={!canGoForward}
          title="Forward"
        >
          {'\u2192'}
        </button>
        <button
          className="webai-toolbar-btn"
          onClick={handleReload}
          title="Reload"
        >
          {isLoading ? '\u00D7' : '\u21BB'}
        </button>
        <div className="webai-url-display" title={currentUrl}>
          {currentUrl}
        </div>
        <button
          className="webai-toolbar-btn"
          onClick={handleOpenExternal}
          title="Open in browser"
        >
          {'\u2197'}
        </button>
      </div>
      <webview
        ref={webviewRef as any}
        className="webai-webview"
        src={url}
        partition="persist:webai"
        allowpopups={'true' as any}
      />
    </div>
  );
};

export default WebAIPane;
