/**
 * SessionPane — Terminal view for a single session.
 *
 * Wraps TerminalPane with a session header showing name, terminal session,
 * and Memorex toggle. Ported from spike, wired to 1A stores.
 *
 * Registered as 'session_pane' in ComponentRegistry.
 */

import type { Session } from '@uai/shared/types';
import TerminalPane from './TerminalPane';
import { useViewport } from '../viewport';

interface SessionPaneProps {
  session: Session;
  memorexEnabled?: boolean;
}

export default function SessionPane({ session, memorexEnabled }: SessionPaneProps): JSX.Element {
  useViewport('session_pane', () => ({
    visible: true,
    label: session?.display_name || session?.tracking_id || 'Unknown Session',
    state: {
      trackingId: session?.tracking_id,
      platform: session?.platform,
      processStatus: session?.process_status,
      memorexEnabled: memorexEnabled ?? true,
    },
    children: ['terminal_pane', 'prompt_box'],
  }));

  return (
    <TerminalPane
      sessionId={session.tracking_id}
      terminalSession={session.terminal_session!}
      cliSessionId={session.cli_session_id}
      displayName={session.display_name || session.tracking_id}
      memorexEnabled={memorexEnabled}
    />
  );
}
