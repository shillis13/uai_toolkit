declare module 'ws' {
  export class WebSocket extends globalThis.WebSocket {
    constructor(url: string | URL, protocols?: string | string[]);
  }
}
