import { builtinModules } from 'node:module';
import { defineConfig } from 'vite';

const builtins = [...builtinModules, ...builtinModules.map((m) => `node:${m}`)];

export default defineConfig({
  build: {
    rollupOptions: {
      external: ['electron', 'node-pty', ...builtins],
    },
  },
});
