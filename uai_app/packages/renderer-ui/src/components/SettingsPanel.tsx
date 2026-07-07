/**
 * SettingsPanel — Font/Appearance Settings Modal
 *
 * Triggered by Cmd+, (standard macOS settings shortcut).
 * Allows configuring UI font, mono font, base font size, and terminal font size.
 * Persists to app_state via window.uai.appState.update().
 */

import { useState, useEffect, useCallback } from 'react';
import type { AppearancePrefs } from '@uai/shared/types';
import { useFeatureFlags } from '../stores/features';
import {
  CUSTOM_PREFIX, listCustomThemes, saveCurrentAsTheme, applyCustomTheme,
  clearAppliedTokens, removeCustomTheme, type CustomTheme,
} from '../stores/customThemes';

const UI_FONTS = [
  { label: 'System Default', value: '' },
  { label: 'SF Pro', value: "'SF Pro', -apple-system, sans-serif" },
  { label: 'Inter', value: "'Inter', sans-serif" },
  { label: 'Helvetica Neue', value: "'Helvetica Neue', sans-serif" },
];

const MONO_FONTS = [
  { label: 'SF Mono', value: "'SF Mono', monospace" },
  { label: 'Menlo', value: "'Menlo', monospace" },
  { label: 'JetBrains Mono', value: "'JetBrains Mono', monospace" },
  { label: 'Fira Code', value: "'Fira Code', monospace" },
  { label: 'Cascadia Code', value: "'Cascadia Code', monospace" },
];

// Curated themes (see app/renderer/styles/themes.css). Empty value = default
// palette (base :root, no [data-theme] override). Persisted under this key.
const THEME_STORAGE_KEY = 'uai:theme';
const THEMES = [
  { label: 'Default', value: '' },
  { label: 'Dawn', value: 'dawn' },
  { label: 'Midnight', value: 'midnight' },
  { label: 'High Contrast', value: 'contrast' },
];

/** Apply a theme selection to <html> and persist it. Handles three cases:
 *  '' → default (base :root); 'custom:<name>' → a user-saved theme (inline token
 *  overrides); anything else → a built-in via [data-theme]. */
function applyTheme(theme: string): void {
  if (theme.startsWith(CUSTOM_PREFIX)) {
    applyCustomTheme(theme.slice(CUSTOM_PREFIX.length)); // clears data-theme + prior inline tokens
  } else {
    clearAppliedTokens(); // drop any inline custom-theme tokens first
    if (theme) {
      document.documentElement.dataset.theme = theme;
    } else {
      delete document.documentElement.dataset.theme;
    }
  }
  try {
    if (theme) {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } else {
      localStorage.removeItem(THEME_STORAGE_KEY);
    }
  } catch {
    /* localStorage unavailable — theme still applies for this session */
  }
}

const DEFAULT_PREFS: AppearancePrefs = {
  fontUi: null,
  fontMono: null,
  fontSizeBase: 12,
  fontSizeTerminal: 13,
};

interface SettingsPanelProps {
  visible: boolean;
  onClose: () => void;
  initialPrefs?: AppearancePrefs;
  onSave: (prefs: AppearancePrefs) => void;
}

export default function SettingsPanel({ visible, onClose, initialPrefs, onSave }: SettingsPanelProps): JSX.Element | null {
  const [prefs, setPrefs] = useState<AppearancePrefs>(initialPrefs || DEFAULT_PREFS);
  // Feature flags — toggles apply live (independent of Save), like Theme.
  const { features, setEnabled } = useFeatureFlags();
  // Theme selection: '' (default), a built-in id, or 'custom:<name>'. Sourced
  // from the persisted 'uai:theme' so custom themes (no [data-theme]) round-trip.
  const [theme, setTheme] = useState<string>(() => localStorage.getItem(THEME_STORAGE_KEY) || '');
  const [customThemes, setCustomThemes] = useState<CustomTheme[]>(() => listCustomThemes());

  // Re-sync the controls with the current theme + saved list whenever the panel opens.
  useEffect(() => {
    if (visible) {
      setTheme(localStorage.getItem(THEME_STORAGE_KEY) || '');
      setCustomThemes(listCustomThemes());
    }
  }, [visible]);

  const handleThemeChange = useCallback((value: string) => {
    setTheme(value);
    applyTheme(value);
    // Applying a custom theme also restores its saved fonts, so the font controls
    // and app_state reflect it (colors AND fonts, as saved).
    if (value.startsWith(CUSTOM_PREFIX)) {
      const ct = listCustomThemes().find((t) => CUSTOM_PREFIX + t.name === value);
      if (ct?.fonts) { setPrefs(ct.fonts); onSave(ct.fonts); }
    }
  }, [onSave]);

  // Save the current live colors + fonts as a named custom theme, then select it.
  const handleSaveCurrentTheme = useCallback(() => {
    const name = (window.prompt('Name this theme (saves current colors & fonts):') || '').trim();
    if (!name) return;
    saveCurrentAsTheme(name, prefs, new Date().toISOString());
    setCustomThemes(listCustomThemes());
    const sel = CUSTOM_PREFIX + name;
    setTheme(sel);
    applyTheme(sel); // persists the selection under 'uai:theme'
  }, [prefs]);

  const handleDeleteTheme = useCallback((name: string) => {
    if (!window.confirm(`Delete theme "${name}"?`)) return;
    removeCustomTheme(name);
    setCustomThemes(listCustomThemes());
    if (theme === CUSTOM_PREFIX + name) { setTheme(''); applyTheme(''); }
  }, [theme]);

  useEffect(() => {
    if (initialPrefs) {
      setPrefs(initialPrefs);
    }
  }, [initialPrefs]);

  // Close on Escape
  useEffect(() => {
    if (!visible) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [visible, onClose]);

  const handleSave = useCallback(() => {
    onSave(prefs);
    onClose();
  }, [prefs, onSave, onClose]);

  if (!visible) return null;

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <h2 className="settings-title">Appearance</h2>
          <button className="settings-close-btn" onClick={onClose} aria-label="Close settings">
            &times;
          </button>
        </div>

        <div className="settings-body">
          {/* Theme — applies + persists immediately (independent of Save).
              Includes user-saved custom themes + a "save current" action. */}
          <div className="settings-section">
            <label className="settings-label">Theme</label>
            <select
              className="settings-select"
              value={theme}
              onChange={(e) => handleThemeChange(e.target.value)}
            >
              <optgroup label="Built-in">
                {THEMES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </optgroup>
              {customThemes.length > 0 && (
                <optgroup label="Custom">
                  {customThemes.map((t) => (
                    <option key={t.name} value={CUSTOM_PREFIX + t.name}>{t.name}</option>
                  ))}
                </optgroup>
              )}
            </select>
            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
              <button
                className="settings-btn"
                onClick={handleSaveCurrentTheme}
                title="Snapshot the current colors + fonts as a reusable theme"
                style={{ fontSize: 12, padding: '5px 11px' }}
              >
                {'＋'} Save current as theme…
              </button>
              {theme.startsWith(CUSTOM_PREFIX) && (
                <button
                  className="settings-btn"
                  onClick={() => handleDeleteTheme(theme.slice(CUSTOM_PREFIX.length))}
                  title="Delete this custom theme"
                  style={{ fontSize: 12, padding: '5px 11px' }}
                >
                  Delete
                </button>
              )}
            </div>
          </div>

          {/* UI Font */}
          <div className="settings-section">
            <label className="settings-label">UI Font</label>
            <select
              className="settings-select"
              value={prefs.fontUi || ''}
              onChange={(e) => setPrefs({ ...prefs, fontUi: e.target.value || null })}
            >
              {UI_FONTS.map((f) => (
                <option key={f.value} value={f.value}>{f.label}</option>
              ))}
            </select>
          </div>

          {/* Mono Font */}
          <div className="settings-section">
            <label className="settings-label">Mono Font</label>
            <select
              className="settings-select"
              value={prefs.fontMono || MONO_FONTS[0].value}
              onChange={(e) => setPrefs({ ...prefs, fontMono: e.target.value || null })}
            >
              {MONO_FONTS.map((f) => (
                <option key={f.value} value={f.value}>{f.label}</option>
              ))}
            </select>
          </div>

          {/* Base Font Size */}
          <div className="settings-section">
            <label className="settings-label">
              Base Font Size: <span className="settings-value">{prefs.fontSizeBase}px</span>
            </label>
            <input
              type="range"
              className="settings-slider"
              min={10}
              max={18}
              step={1}
              value={prefs.fontSizeBase}
              onChange={(e) => setPrefs({ ...prefs, fontSizeBase: Number(e.target.value) })}
            />
          </div>

          {/* Terminal Font Size */}
          <div className="settings-section">
            <label className="settings-label">
              Terminal Font Size: <span className="settings-value">{prefs.fontSizeTerminal}px</span>
            </label>
            <input
              type="range"
              className="settings-slider"
              min={10}
              max={20}
              step={1}
              value={prefs.fontSizeTerminal}
              onChange={(e) => setPrefs({ ...prefs, fontSizeTerminal: Number(e.target.value) })}
            />
          </div>

          {/* Preview */}
          <div className="settings-section">
            <label className="settings-label">Preview</label>
            <div className="settings-preview">
              <p
                className="settings-preview-ui"
                style={{ fontFamily: prefs.fontUi || undefined, fontSize: `${prefs.fontSizeBase}px` }}
              >
                UI text: The quick brown fox jumps over the lazy dog.
              </p>
              <p
                className="settings-preview-mono"
                style={{ fontFamily: prefs.fontMono || undefined, fontSize: `${prefs.fontSizeTerminal}px` }}
              >
                Mono text: const x = fn(42);
              </p>
            </div>
          </div>

          {/* Features — enable/disable UI surfaces. Applies live (like Theme). */}
          <div className="settings-section">
            <label className="settings-label">Features</label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {features.map((f) => (
                <label
                  key={f.key}
                  title={f.description}
                  style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '5px 2px', cursor: 'pointer' }}
                >
                  <input
                    type="checkbox"
                    checked={f.enabled}
                    onChange={(e) => setEnabled(f.key, e.target.checked)}
                    style={{ marginTop: 2, cursor: 'pointer', accentColor: 'var(--accent-blue)' }}
                  />
                  <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                    <span style={{ fontSize: 13 }}>
                      {f.label}
                      {f.group && <span style={{ color: 'var(--text-muted)', fontSize: 11, marginLeft: 6 }}>{f.group}</span>}
                    </span>
                    <span style={{ color: 'var(--text-muted)', fontSize: 11.5, lineHeight: 1.35 }}>{f.description}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="settings-footer">
          <button className="settings-btn settings-btn-cancel" onClick={onClose}>
            Cancel
          </button>
          <button className="settings-btn settings-btn-save" onClick={handleSave}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
