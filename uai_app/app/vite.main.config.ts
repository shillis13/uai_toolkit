import { builtinModules } from 'node:module';
import { defineConfig } from 'vite';
import * as path from 'path';

const builtins = [...builtinModules, ...builtinModules.map((m) => `node:${m}`)];

export default defineConfig({
  build: {
    lib: {
      entry: path.resolve(__dirname, 'main/index.ts'),
      formats: ['cjs'],
      fileName: () => 'index.js',
    },
    outDir: '.vite/build',
    emptyOutDir: false,
    rollupOptions: {
      external: ['electron', 'node-pty', ...builtins],
    },
  },
  resolve: {
    alias: {
      '@uai/shared': path.resolve(__dirname, '../packages/shared/src'),
      '@uai/renderer-ui': path.resolve(__dirname, '../packages/renderer-ui/src'),
      '@contracts': path.resolve(__dirname, '../architecture/contracts'),
    },
  },
});
