/**
 * ComposeMessage — message composition form for AI Comms.
 *
 * Lets the user send messages to AI sessions with type/urgency selection.
 * Routes through executeCommand('comms.send') via the command bus.
 */

import { useState, useCallback } from 'react';
import { useSessionStore } from '../stores';
import { useToast } from './Toast';
import { executeCommand } from '../utils/execute-command';

interface ComposeMessageProps {
  defaultTo?: string;
  defaultReplyTo?: string;
  onClose?: () => void;
}

export default function ComposeMessage({ defaultTo, defaultReplyTo, onClose }: ComposeMessageProps): JSX.Element {
  const { sessions } = useSessionStore();
  const { showToast } = useToast();
  const [to, setTo] = useState(defaultTo || '');
  const [content, setContent] = useState('');
  const [urgency, setUrgency] = useState<string>('prompt');
  const [responseType, setResponseType] = useState<string>('reply');
  const [sending, setSending] = useState(false);

  const activeSessions = sessions.filter(s => s.process_status === 'running');

  const handleSend = useCallback(async () => {
    if (!to.trim() || !content.trim()) return;
    setSending(true);
    const result = await executeCommand('comms.send', {
      from: 'uai_app',
      to: to.trim(),
      content: content.trim(),
      urgency,
      responseType,
      replyTo: defaultReplyTo || undefined,
    });
    setSending(false);
    if (result.ok) {
      showToast('Message sent', 'info');
      setContent('');
      onClose?.();
    } else {
      showToast(`Send failed: ${result.error?.message || 'unknown error'}`, 'error');
    }
  }, [to, content, urgency, responseType, defaultReplyTo, showToast, onClose]);

  return (
    <div className="compose-message">
      <div className="compose-header">
        <span className="compose-title">Send Message</span>
        {onClose && <button className="compose-close" onClick={onClose}>{'\u2715'}</button>}
      </div>
      <div className="compose-field">
        <label>To</label>
        <select value={to} onChange={(e) => setTo(e.target.value)}>
          <option value="">Select recipient...</option>
          {activeSessions.map(s => (
            <option key={s.tracking_id} value={s.tracking_id}>
              {s.display_name || s.tracking_id}
            </option>
          ))}
        </select>
      </div>
      <div className="compose-row">
        <div className="compose-field">
          <label>Urgency</label>
          <select value={urgency} onChange={(e) => setUrgency(e.target.value)}>
            <option value="prompt">Prompt (normal)</option>
            <option value="interrupt">Interrupt (blocking)</option>
            <option value="async">Async (inbox only)</option>
            <option value="passive">Passive (log only)</option>
          </select>
        </div>
        <div className="compose-field">
          <label>Response</label>
          <select value={responseType} onChange={(e) => setResponseType(e.target.value)}>
            <option value="reply">Reply expected</option>
            <option value="acknowledge">Acknowledge only</option>
            <option value="none">No response</option>
          </select>
        </div>
      </div>
      <div className="compose-field">
        <label>Message</label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Type your message..."
          rows={4}
        />
      </div>
      <div className="compose-actions">
        <button
          className="compose-send"
          onClick={handleSend}
          disabled={sending || !to.trim() || !content.trim()}
        >
          {sending ? 'Sending...' : 'Send'}
        </button>
      </div>
    </div>
  );
}
