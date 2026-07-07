import type { ForgeConfig } from '@electron-forge/shared-types';
import { MakerZIP } from '@electron-forge/maker-zip';
import { VitePlugin } from '@electron-forge/plugin-vite';
import { AutoUnpackNativesPlugin } from '@electron-forge/plugin-auto-unpack-natives';
import * as path from 'path';
import * as fs from 'fs';

function copyDirSync(src: string, dest: string): void {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDirSync(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

const MAIN_PROCESS_DEPS = ['node-pty', 'electron-squirrel-startup'];

const config: ForgeConfig = {
  packagerConfig: {
    asar: {
      unpack: '**/{*.node,spawn-helper}',
    },
    afterCopy: [
      (buildPath: string, _electronVersion: string, _platform: string, _arch: string, callback: (err?: Error) => void) => {
        try {
          for (const dep of MAIN_PROCESS_DEPS) {
            const srcDep = path.join(__dirname, 'node_modules', dep);
            const destDep = path.join(buildPath, 'node_modules', dep);
            if (fs.existsSync(srcDep)) {
              copyDirSync(srcDep, destDep);
            } else {
              callback(new Error(`[afterCopy] Required native dep ${dep} not found at ${srcDep}`));
              return;
            }
          }
          callback();
        } catch (err) {
          callback(err as Error);
        }
      },
    ],
  },
  rebuildConfig: {},
  makers: [new MakerZIP({}, ['darwin'])],
  plugins: [
    new AutoUnpackNativesPlugin({}),
    new VitePlugin({
      build: [
        {
          entry: 'src/main/index.ts',
          config: 'vite.main.config.ts',
        },
        {
          entry: 'src/main/preload.ts',
          config: 'vite.preload.config.ts',
        },
      ],
      renderer: [
        {
          name: 'main_window',
          config: 'vite.renderer.config.ts',
        },
      ],
    }),
  ],
};

export default config;
