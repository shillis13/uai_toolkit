/**
 * UAI Renderer Entry Point — Phase 1
 *
 * Bootstraps the React app and registers initial components
 * with the ComponentRegistry.
 */

import { createRoot } from 'react-dom/client';
import { registerInitialComponents } from '@uai/shared/component-descriptions';
import App from './App';
import { applyCustomTheme, CUSTOM_PREFIX } from '@uai/renderer-ui/stores/customThemes';
import './styles/styles.css';
import './styles/themes.css';

// Apply the persisted theme BEFORE first render to avoid a flash of the default
// palette. Empty/absent value = default theme (base :root). A "custom:<name>"
// value is a user-saved theme (inline token overrides); otherwise it's a
// built-in selected via [data-theme]. See themes.css / stores/customThemes.ts.
try {
  const savedTheme = localStorage.getItem('uai:theme');
  if (savedTheme && savedTheme.startsWith(CUSTOM_PREFIX)) {
    applyCustomTheme(savedTheme.slice(CUSTOM_PREFIX.length));
  } else if (savedTheme) {
    document.documentElement.dataset.theme = savedTheme;
  }
} catch {
  /* localStorage unavailable — fall back to default theme */
}

// Register component descriptions with the ComponentRegistry
registerInitialComponents();

const root = createRoot(document.getElementById('root')!);
root.render(<App />);
