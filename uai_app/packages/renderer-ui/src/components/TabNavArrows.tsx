/**
 * Workspace tab navigation (Back/Forward) exposed via context so any pane can
 * render its OWN nav-arrows instance inline in its OWN title bar — the same
 * affordance Session/Folder title bars have, without a shared title-bar element.
 *
 * Workspace provides the value; manager panes drop <TabNavArrows /> into their
 * title bar. Implementation is shared; each pane gets its own instance.
 */

import { createContext, useContext } from 'react';

export interface TabNav {
  canGoBack: boolean;
  canGoForward: boolean;
  navigateBack: () => void;
  navigateForward: () => void;
}

export const TabNavContext = createContext<TabNav>({
  canGoBack: false,
  canGoForward: false,
  navigateBack: () => {},
  navigateForward: () => {},
});

export function useTabNav(): TabNav {
  return useContext(TabNavContext);
}

/** Back/Forward arrows — matches the Session title bar markup (.stb-nav-*). */
export function TabNavArrows(): JSX.Element {
  const { canGoBack, canGoForward, navigateBack, navigateForward } = useTabNav();
  return (
    <div className="stb-nav-arrows">
      <button className="stb-nav-btn" title="Back" disabled={!canGoBack} onClick={navigateBack}>{'←'}</button>
      <button className="stb-nav-btn" title="Forward" disabled={!canGoForward} onClick={navigateForward}>{'→'}</button>
    </div>
  );
}
