import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

export const CDP_PORT = 9226;
export const SCREENSHOT_DIR = '/tmp/uai_e2e';

interface CdpTargetInfo {
  id: string;
  type: string;
  title?: string;
  url?: string;
  webSocketDebuggerUrl?: string;
}

interface EvaluateResult<T> {
  result?: {
    value?: T;
    description?: string;
  };
  exceptionDetails?: {
    text?: string;
    exception?: {
      description?: string;
      value?: unknown;
    };
  };
}

interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason?: unknown) => void;
  method: string;
}

function ensureWebSocket(): typeof WebSocket {
  const wsCtor = globalThis.WebSocket;
  if (!wsCtor) {
    throw new Error('Global WebSocket is not available. Use Node 20+ or provide a WebSocket implementation.');
  }
  return wsCtor;
}

function sanitizeName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9_.-]+/g, '_').replace(/^_+|_+$/g, '');
}

function decodeMessageData(data: unknown): string {
  if (typeof data === 'string') return data;
  if (data instanceof ArrayBuffer) return Buffer.from(data).toString('utf8');
  if (ArrayBuffer.isView(data)) return Buffer.from(data.buffer).toString('utf8');
  return String(data);
}

async function fetchTargets(port: number): Promise<CdpTargetInfo[]> {
  const response = await fetch(`http://127.0.0.1:${port}/json/list`);
  if (!response.ok) {
    throw new Error(`CDP target discovery failed: HTTP ${response.status}`);
  }
  return await response.json() as CdpTargetInfo[];
}

function pickTarget(targets: CdpTargetInfo[]): CdpTargetInfo {
  const preferred = targets.find((target) =>
    target.type === 'page'
    && Boolean(target.webSocketDebuggerUrl)
    && ((target.title || '').includes('UAI') || (target.url || '').includes('index.html')),
  );
  if (preferred) return preferred;

  const fallback = targets.find((target) => target.type === 'page' && Boolean(target.webSocketDebuggerUrl));
  if (!fallback) {
    throw new Error('No debuggable page target found on CDP port 9226. Is the packaged app running?');
  }
  return fallback;
}

function extractErrorMessage(result: EvaluateResult<unknown>): string {
  return result.exceptionDetails?.exception?.description
    || result.exceptionDetails?.text
    || 'Unknown Runtime.evaluate failure';
}

export class CdpHarness {
  private readonly ws: WebSocket;
  private nextId = 1;
  private readonly pending = new Map<number, PendingRequest>();
  private closePromise: Promise<void>;

  private constructor(ws: WebSocket) {
    this.ws = ws;
    this.ws.addEventListener('message', (event: MessageEvent) => {
      const payload = JSON.parse(decodeMessageData(event.data)) as { id?: number; result?: unknown; error?: { message?: string } };
      if (!payload.id) return;
      const pending = this.pending.get(payload.id);
      if (!pending) return;
      this.pending.delete(payload.id);
      if (payload.error) {
        pending.reject(new Error(`[CDP:${pending.method}] ${payload.error.message || 'Unknown error'}`));
        return;
      }
      pending.resolve(payload.result);
    });

    this.ws.addEventListener('close', () => {
      for (const pending of this.pending.values()) {
        pending.reject(new Error(`CDP socket closed while waiting for ${pending.method}`));
      }
      this.pending.clear();
    });

    this.closePromise = new Promise((resolve) => {
      this.ws.addEventListener('close', () => resolve(), { once: true });
    });
  }

  public static async connect(port = CDP_PORT): Promise<CdpHarness> {
    const target = pickTarget(await fetchTargets(port));
    const url = target.webSocketDebuggerUrl;
    if (!url) {
      throw new Error('Selected CDP target did not expose webSocketDebuggerUrl');
    }

    const WebSocketCtor = ensureWebSocket();
    const ws = new WebSocketCtor(url);

    await new Promise<void>((resolve, reject) => {
      ws.addEventListener('open', () => resolve(), { once: true });
      ws.addEventListener('error', () => reject(new Error(`Failed to connect to CDP target ${url}`)), { once: true });
    });

    const harness = new CdpHarness(ws);
    await harness.send('Runtime.enable');
    await harness.send('Page.enable');
    await harness.send('DOM.enable');
    await harness.send('Overlay.setShowViewportSizeOnResize', { show: false }).catch(() => undefined);
    return harness;
  }

  public async close(): Promise<void> {
    if (this.ws.readyState === this.ws.CLOSED || this.ws.readyState === this.ws.CLOSING) {
      return;
    }
    this.ws.close();
    await this.closePromise;
  }

  public async send<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T> {
    const id = this.nextId++;
    const message = { id, method, params };
    const promise = new Promise<T>((resolve, reject) => {
      this.pending.set(id, {
        resolve: (value) => resolve(value as T),
        reject,
        method,
      });
    });
    this.ws.send(JSON.stringify(message));
    return await promise;
  }

  public async js<T = unknown>(expression: string): Promise<T> {
    const result = await this.send<EvaluateResult<T>>('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    });
    if (result.exceptionDetails) {
      throw new Error(extractErrorMessage(result));
    }
    return result.result?.value as T;
  }

  public async sleep(ms: number): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, ms));
  }

  public async waitFor(selector: string, timeoutMs = 10_000): Promise<void> {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      const present = await this.js<boolean>(`Boolean(document.querySelector(${JSON.stringify(selector)}))`);
      if (present) return;
      await this.sleep(100);
    }
    throw new Error(`Timed out waiting for selector: ${selector}`);
  }

  public async waitForText(text: string, timeoutMs = 10_000): Promise<void> {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      const found = await this.js<boolean>(`document.body.innerText.includes(${JSON.stringify(text)})`);
      if (found) return;
      await this.sleep(100);
    }
    throw new Error(`Timed out waiting for text: ${text}`);
  }

  public async exists(selector: string): Promise<boolean> {
    return await this.js<boolean>(`Boolean(document.querySelector(${JSON.stringify(selector)}))`);
  }

  public async count(selector: string): Promise<number> {
    return await this.js<number>(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
  }

  public async text(selector: string): Promise<string> {
    return await this.js<string>(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      return el ? (el.textContent || '').trim() : '';
    })()`);
  }

  public async click(selector: string): Promise<void> {
    await this.waitFor(selector);
    const box = await this.boundingBox(selector);
    if (!box) throw new Error(`Cannot click missing selector: ${selector}`);
    await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y, button: 'none' });
    await this.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: box.x, y: box.y, button: 'left', clickCount: 1 });
    await this.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: box.x, y: box.y, button: 'left', clickCount: 1 });
  }

  public async rightClick(selector: string): Promise<void> {
    await this.waitFor(selector);
    const box = await this.boundingBox(selector);
    if (!box) throw new Error(`Cannot right-click missing selector: ${selector}`);
    await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y, button: 'none' });
    await this.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: box.x, y: box.y, button: 'right', clickCount: 1 });
    await this.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: box.x, y: box.y, button: 'right', clickCount: 1 });
  }

  public async clickText(text: string, selector = '*'): Promise<void> {
    const found = await this.js<boolean>(`(() => {
      const needle = ${JSON.stringify(text)};
      const elements = Array.from(document.querySelectorAll(${JSON.stringify(selector)}));
      const match = elements.find((el) => (el.textContent || '').trim() === needle);
      if (!match) return false;
      (match as HTMLElement).click();
      return true;
    })()`);
    if (!found) {
      throw new Error(`Could not find text ${text} within selector ${selector}`);
    }
  }

  public async type(selector: string, text: string): Promise<void> {
    await this.waitFor(selector);
    const wrote = await this.js<boolean>(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) {
        return false;
      }
      const prototype = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!nativeInputValueSetter) {
        throw new Error('Missing native input value setter');
      }
      el.focus();
      nativeInputValueSetter.call(el, ${JSON.stringify(text)});
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`);
    if (!wrote) {
      throw new Error(`Selector is not a text input/textarea: ${selector}`);
    }
  }

  public async pressShortcut(selector: string, key: string, options: { metaKey?: boolean; ctrlKey?: boolean; shiftKey?: boolean } = {}): Promise<void> {
    await this.waitFor(selector);
    const dispatched = await this.js<boolean>(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!(el instanceof HTMLElement)) return false;
      el.focus();
      const init = {
        key: ${JSON.stringify(key)},
        bubbles: true,
        cancelable: true,
        metaKey: ${Boolean(options.metaKey)},
        ctrlKey: ${Boolean(options.ctrlKey)},
        shiftKey: ${Boolean(options.shiftKey)},
      };
      el.dispatchEvent(new KeyboardEvent('keydown', init));
      el.dispatchEvent(new KeyboardEvent('keyup', init));
      return true;
    })()`);
    if (!dispatched) {
      throw new Error(`Cannot dispatch shortcut to selector: ${selector}`);
    }
  }

  public async drag(selector: string, deltaX: number, deltaY: number): Promise<void> {
    await this.waitFor(selector);
    const box = await this.boundingBox(selector);
    if (!box) throw new Error(`Cannot drag missing selector: ${selector}`);
    const targetX = box.x + deltaX;
    const targetY = box.y + deltaY;
    await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y, button: 'none' });
    await this.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: box.x, y: box.y, button: 'left', clickCount: 1 });
    await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: targetX, y: targetY, button: 'left', buttons: 1 });
    await this.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: targetX, y: targetY, button: 'left', clickCount: 1 });
  }

  public async boundingBox(selector: string): Promise<BoundingBox | null> {
    return await this.js<BoundingBox | null>(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!(el instanceof HTMLElement)) return null;
      el.scrollIntoView({ block: 'center', inline: 'center' });
      const rect = el.getBoundingClientRect();
      return {
        x: rect.left + rect.width / 2,
        y: rect.top + rect.height / 2,
        width: rect.width,
        height: rect.height,
      };
    })()`);
  }

  public async screenshot(name: string): Promise<string> {
    mkdirSync(SCREENSHOT_DIR, { recursive: true });
    const filePath = join(SCREENSHOT_DIR, `${sanitizeName(name)}.png`);
    const result = await this.send<{ data: string }>('Page.captureScreenshot', { format: 'png' });
    writeFileSync(filePath, Buffer.from(result.data, 'base64'));
    return filePath;
  }
}

export function assert(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

export async function connectHarness(port = CDP_PORT): Promise<CdpHarness> {
  return await CdpHarness.connect(port);
}

export async function captureFailureScreenshot(name: string): Promise<string | null> {
  let harness: CdpHarness | null = null;
  try {
    harness = await connectHarness();
    return await harness.screenshot(`failure_${name}`);
  } catch {
    return null;
  } finally {
    if (harness) {
      await harness.close();
    }
  }
}
