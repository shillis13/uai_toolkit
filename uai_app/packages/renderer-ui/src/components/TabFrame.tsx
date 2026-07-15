/**
 * TabFrame — the standard chrome every app/manager tab should have, in one place.
 *
 * Panes used to hand-roll a header (`<div class="mgr-title-group"><TabNavArrows/>
 * <title/></div>` + assorted actions), and new panes routinely forgot pieces of it
 * (the AI Feed pane shipped with no nav arrows at all). Wrapping a pane's body in
 * <TabFrame> guarantees the common affordances — back/forward nav + a consistent
 * title bar — and gives slots for the pane-specific bits:
 *
 *   header-left   : nav arrows + title (always present)
 *   headerExtra   : inline controls right after the title (filters, tabs, search)
 *   actions       : right-aligned controls (refresh, add, counts)
 *   children      : the pane body (scrolls; header stays fixed)
 *
 * Adopt incrementally: a pane switches from its bespoke header to <TabFrame> and
 * loses the boilerplate. (A future step can auto-wrap app panes in TabContentPane
 * so the chrome is impossible to omit.)
 */

import type { ReactNode } from 'react';
import { TabNavArrows } from './TabNavArrows';

interface TabFrameProps {
  title: ReactNode;
  headerExtra?: ReactNode;   // inline, after the title (filters/search/tabs)
  actions?: ReactNode;       // right-aligned (refresh/add/counts)
  className?: string;        // extra class on the frame root (per-pane theming)
  bodyClassName?: string;    // extra class on the scrolling body
  children: ReactNode;
}

export default function TabFrame({
  title, headerExtra, actions, className, bodyClassName, children,
}: TabFrameProps): JSX.Element {
  return (
    <div className={`tab-frame${className ? ` ${className}` : ''}`}>
      <div className="tab-frame-header">
        <TabNavArrows />
        <span className="tab-frame-title">{title}</span>
        {headerExtra}
        {actions && <span className="tab-frame-actions">{actions}</span>}
      </div>
      <div className={`tab-frame-body${bodyClassName ? ` ${bodyClassName}` : ''}`}>
        {children}
      </div>
    </div>
  );
}
