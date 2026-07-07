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
      // Preserve executable permissions (critical for node-pty's spawn-helper)
      const stat = fs.statSync(srcPath);
      fs.chmodSync(destPath, stat.mode);
    }
  }
}

const MAIN_PROCESS_DEPS = ['node-pty', 'electron-squirrel-startup'];

const config: ForgeConfig = {
  packagerConfig: {
    icon: path.join(__dirname, 'resources', 'icon_uai'),
    protocols: [
      {
        name: 'UAI Deep Link',
        schemes: ['uai'],
      },
    ],
    asar: {
      unpack: '**/{*.node,spawn-helper}',
    },
    afterCopy: [
      (buildPath: string, _electronVersion: string, _platform: string, _arch: string, callback: (err?: Error) => void) => {
        try {
          for (const dep of MAIN_PROCESS_DEPS) {
            // Check app/node_modules first, then root node_modules (npm workspace hoisting)
            const localDep = path.join(__dirname, 'node_modules', dep);
            const rootDep = path.join(__dirname, '..', 'node_modules', dep);
            const srcDep = fs.existsSync(localDep) ? localDep : rootDep;
            const destDep = path.join(buildPath, 'node_modules', dep);
            if (fs.existsSync(srcDep)) {
              copyDirSync(srcDep, destDep);
            } else {
              callback(new Error(`[afterCopy] Required native dep ${dep} not found at ${localDep} or ${rootDep}`));
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
          entry: 'main/index.ts',
          config: 'vite.main.config.ts',
        },
        {
          entry: 'main/preload.ts',
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
  hooks: {
    postPackage: async (_config, result) => {
      // Fix spawn-helper permissions — asar unpack strips execute bits.
      // node-pty's posix_spawnp fails without +x on spawn-helper.
      console.log(`[postPackage] outputPaths: ${JSON.stringify(result.outputPaths)}`);

      // Stamp the build with who/what/when so a filesystem watcher can report
      // "new UAI build vX by <session>". The build runs in the building
      // session's shell, so AI_TRACKING_ID identifies the builder. There is
      // essentially one build path (forge), so this attribution is reliable.
      let stampVersion = 'unknown';
      try {
        stampVersion = JSON.parse(fs.readFileSync(path.join(__dirname, 'package.json'), 'utf-8')).version;
      } catch { /* keep unknown */ }
      const buildInfo = JSON.stringify({
        version: stampVersion,
        builtBy: process.env.AI_TRACKING_ID || process.env.UAI_LAUNCHED_BY || 'unknown',
        builtByName: process.env.AI_SESSION_NAME || '',
        builtAt: new Date().toISOString(),
        platform: process.platform,
      }, null, 2);

      for (const outputPath of result.outputPaths) {
        // outputPath may be the .app directory itself or the parent
        const bases = [
          outputPath,
          path.join(outputPath, 'unified-ai-interface.app'),
        ];
        // Write build_info.json into the app's Resources for each candidate base.
        for (const base of bases) {
          const resourcesDir = path.join(base, 'Contents/Resources');
          if (fs.existsSync(resourcesDir)) {
            try {
              fs.writeFileSync(path.join(resourcesDir, 'build_info.json'), buildInfo);
              console.log(`[postPackage] Wrote build_info.json (v${stampVersion}) to ${resourcesDir}`);
            } catch (e) { console.warn('[postPackage] build_info write failed:', e); }
          }
        }
        for (const base of bases) {
          const helpers = [
            path.join(base, 'Contents/Resources/app.asar.unpacked/node_modules/node-pty/prebuilds/darwin-arm64/spawn-helper'),
            path.join(base, 'Contents/Resources/app.asar.unpacked/node_modules/node-pty/prebuilds/darwin-x64/spawn-helper'),
          ];
          for (const helper of helpers) {
            if (fs.existsSync(helper)) {
              fs.chmodSync(helper, 0o755);
              console.log(`[postPackage] Fixed spawn-helper permissions: ${helper}`);
            }
          }
        }
      }
    },
  },
};

export default config;
