export type Theme = 'system' | 'light' | 'dark'

export const accentOptions = [
  { value: 'blue', label: 'Blue' },
  { value: 'teal', label: 'Teal' },
  { value: 'green', label: 'Green' },
  { value: 'violet', label: 'Violet' },
  { value: 'rose', label: 'Rose' },
  { value: 'orange', label: 'Orange' },
] as const

export type AccentColor = typeof accentOptions[number]['value']

const media = window.matchMedia?.('(prefers-color-scheme: dark)')

export function getTheme(): Theme {
  const saved = localStorage.getItem('vocab-theme')
  return saved === 'light' || saved === 'dark' ? saved : 'system'
}

export function getAccentColor(): AccentColor {
  const saved = localStorage.getItem('vocab-accent')
  return accentOptions.find(option => option.value === saved)?.value ?? 'blue'
}

export function applyTheme(theme = getTheme()) {
  document.documentElement.dataset.theme = theme === 'system' ? media?.matches ? 'dark' : 'light' : theme
  document.documentElement.dataset.accent = getAccentColor()
}

export function saveAccentColor(accent: AccentColor) {
  localStorage.setItem('vocab-accent', accent)
  applyTheme()
}

export function saveTheme(theme: Theme) {
  localStorage.setItem('vocab-theme', theme)
  applyTheme(theme)
}

media?.addEventListener('change', () => applyTheme())
