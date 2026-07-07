import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import * as path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@uai/shared': path.resolve(__dirname, '../packages/shared/src'),
      '@uai/renderer-ui': path.resolve(__dirname, '../packages/renderer-ui/src'),
      '@contracts': path.resolve(__dirname, '../architecture/contracts'),
    },
  },
});
