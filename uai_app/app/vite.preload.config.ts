import { builtinModules } from 'node:module';
import { defineConfig } from 'vite';
import * as path from 'path';

const builtins = [...builtinModules, ...builtinModules.map((m) => `node:${m}`)];

export default defineConfig({
  build: {
    lib: {
      entry: path.resolve(__dirname, 'main/preload.ts'),
      formats: ['cjs'],
      fileName: () => 'preload.js',
    },
    outDir: '.vite/build',
    emptyOutDir: false,
    rollupOptions: {
      external: ['electron', ...builtins],
    },
  },
  resolve: {
    alias: {
      '@uai/shared': path.resolve(__dirname, '../packages/shared/src'),
      '@contracts': path.resolve(__dirname, '../architecture/contracts'),
    },
  },
});
