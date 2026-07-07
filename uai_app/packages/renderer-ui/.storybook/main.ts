import type { StorybookConfig } from '@storybook/react-vite';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const config: StorybookConfig = {
  stories: ['../src/**/*.stories.@(ts|tsx)'],
  addons: [],
  framework: {
    name: '@storybook/react-vite',
    options: {},
  },
  viteFinal: async (config) => {
    config.resolve = config.resolve || {};
    config.resolve.alias = {
      ...config.resolve.alias,
      '@uai/shared': path.resolve(__dirname, '../../shared/src'),
      '@uai/renderer-ui': path.resolve(__dirname, '../src'),
      '@contracts': path.resolve(__dirname, '../../../architecture/contracts'),
    };
    return config;
  },
};

export default config;
