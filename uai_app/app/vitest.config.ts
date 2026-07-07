import { defineConfig } from 'vitest/config';
import * as path from 'path';

export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'node',
  },
  resolve: {
    alias: {
      '@uai/shared': path.resolve(__dirname, '../packages/shared/src'),
      '@uai/renderer-ui': path.resolve(__dirname, '../packages/renderer-ui/src'),
      '@contracts': path.resolve(__dirname, '../architecture/contracts'),
    },
  },
});
