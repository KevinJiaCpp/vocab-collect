export type Theme = 'system' | 'light' | 'dark'

const media = window.matchMedia?.('(prefers-color-scheme: dark)')

export function getTheme(): Theme {
  const saved = localStorage.getItem('vocab-theme')
  return saved === 'light' || saved === 'dark' ? saved : 'system'
}

export function applyTheme(theme = getTheme()) {
  document.documentElement.dataset.theme = theme === 'system' ? media?.matches ? 'dark' : 'light' : theme
}

export function saveTheme(theme: Theme) {
  localStorage.setItem('vocab-theme', theme)
  applyTheme(theme)
}

media?.addEventListener('change', () => applyTheme())
