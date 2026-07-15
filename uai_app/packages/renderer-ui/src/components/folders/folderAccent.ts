/**
 * folderAccent — one source of truth for a folder's color.
 *
 * Both the Navigator folder LIST (FolderTree) and the center-pane Folder Tab
 * VIEW (TabContentPane) resolve a folder's accent through this helper, so the
 * same folder reads as the same color in both places.
 *
 * An explicit color (set on the folder/container) always wins. Otherwise the
 * folder's stable id (falling back to name) hashes to one of the app's own
 * accent tokens — we deliberately stay inside the --accent-* palette so the
 * hues match the rest of the UAI app rather than introducing new ones.
 */

// The app's accent palette, in a fixed order so the hash is stable.
const FOLDER_ACCENTS = [
  '--accent-cyan', '--accent-green', '--accent-purple', '--accent-blue',
  '--accent-orange', '--accent-amber', '--accent-red', '--accent-yellow',
];

interface ColorableFolder { id?: string | null; name?: string | null; color?: string | null }

/** Returns a CSS color string (a var() token, or the explicit color as-is). */
export function folderAccent(folder: ColorableFolder): string {
  const c = folder.color;
  if (c) {
    if (c.startsWith('#') || c.startsWith('var(') || c.startsWith('rgb') || c.startsWith('hsl')) return c;
    if (c.startsWith('--')) return `var(${c})`;
    return `var(--accent-${c})`;          // bare token name, e.g. "cyan"
  }
  const s = folder.id || folder.name || '';
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return `var(${FOLDER_ACCENTS[h % FOLDER_ACCENTS.length]})`;
}
