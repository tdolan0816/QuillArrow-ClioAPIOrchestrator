/**
 * Light/Dark theme context.
 *
 * - Tailwind v4 class strategy: we toggle a `dark` class on <html>, and
 *   `@custom-variant dark` in index.css makes every `dark:` utility respond.
 * - Charts (Chart.js + custom SVG) can't use CSS classes for canvas-drawn
 *   colors, so components read `theme` from useTheme() and pick their colors
 *   from theme token objects (see CHART_THEME / GAUGE_THEME in the pages).
 * - Preference persists in localStorage under 'qa-theme' — the same storage
 *   mechanism the app already uses for the auth token.
 */

import { createContext, useContext, useEffect, useState } from 'react';

const STORAGE_KEY = 'qa-theme';

const ThemeContext = createContext({ theme: 'light', toggleTheme: () => {} });

function getInitialTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    /* storage unavailable — fall through to default */
  }
  return 'light';
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(getInitialTheme);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* storage unavailable — theme still applies for this session */
    }
  }, [theme]);

  const toggleTheme = () => setTheme(t => (t === 'dark' ? 'light' : 'dark'));

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTheme() {
  return useContext(ThemeContext);
}
