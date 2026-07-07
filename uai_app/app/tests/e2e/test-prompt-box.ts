import { assert, connectHarness } from './test-harness';

export async function run(): Promise<void> {
  const h = await connectHarness();
  try {
    await h.clickText('Sessions', '.nav-tab');
    const runningSessionName = await h.js<string | null>(`window.uai.sessions.list().then((items) => {
      const running = items.find((item) => item.process_status === 'running');
      return running ? (running.display_name || running.tracking_id) : null;
    })`);
    assert(runningSessionName, 'No running session available for PromptBox test');

    await h.clickText(runningSessionName!, '.card-name');
    await h.waitFor('.promptbox');
    await h.waitFor('.promptbox-textarea');

    await h.js(`(() => {
      const inputs = [];
      (window as any).__uaiTerminalInputs = inputs;
      const originalInput = window.uai.terminal.input.bind(window.uai.terminal);
      (window as any).__uaiOriginalTerminalInput = originalInput;
      window.uai.terminal.input = ((sessionId, data) => {
        inputs.push({ sessionId, data });
        return originalInput(sessionId, data);
      }) as typeof window.uai.terminal.input;
    })()`);

    await h.type('.promptbox-textarea', 'hello from e2e');
    const promptState = await h.js<{ value: string; forwarded: number }>(`(() => {
      const textarea = document.querySelector('.promptbox-textarea') as HTMLTextAreaElement | null;
      return {
        value: textarea?.value || '',
        forwarded: ((window as any).__uaiTerminalInputs || []).length,
      };
    })()`);
    assert(promptState.value === 'hello from e2e', 'PromptBox textarea did not receive typed text');
    assert(promptState.forwarded === 0, 'Typing into PromptBox forwarded data to terminal input unexpectedly');

    await h.js(`(() => {
      const calls = [];
      (window as any).__uaiExecuteCalls = calls;
      const originalExecute = window.uai.execute.bind(window.uai);
      (window as any).__uaiOriginalExecute = originalExecute;
      window.uai.execute = (async (command) => {
        calls.push(command);
        return { ok: true, command_id: command.id };
      }) as typeof window.uai.execute;
    })()`);

    await h.pressShortcut('.promptbox-textarea', 'Enter', { metaKey: true });
    await h.sleep(200);
    const sentCommandType = await h.js<string | null>(`(() => {
      const calls = (window as any).__uaiExecuteCalls || [];
      return calls.length > 0 ? calls[calls.length - 1].type : null;
    })()`);
    assert(sentCommandType === 'prompt.send', `Cmd+Enter did not send prompt via command bus (got ${sentCommandType})`);

    const heightBefore = (await h.boundingBox('.promptbox'))?.height || 0;
    await h.drag('.promptbox-resize-handle', 0, -60);
    await h.sleep(150);
    const heightAfter = (await h.boundingBox('.promptbox'))?.height || 0;
    assert(heightAfter !== heightBefore, 'PromptBox resize handle did not change height');

    await h.js(`(() => {
      const originalInput = (window as any).__uaiOriginalTerminalInput;
      if (originalInput) window.uai.terminal.input = originalInput;
      const originalExecute = (window as any).__uaiOriginalExecute;
      if (originalExecute) window.uai.execute = originalExecute;
    })()`);
  } finally {
    await h.close();
  }
}
