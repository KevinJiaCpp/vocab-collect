import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Bot, Check, GraduationCap, Info, LogOut, Monitor, Moon, Palette, Scale, Sun, UserRound } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, json } from './api'
import { Button, ErrorNotice, Loading, Modal } from './components'
import { accentOptions, getAccentColor, getTheme, saveAccentColor, saveTheme, type AccentColor, type Theme } from './theme'
import type { Overview, User } from './types'
import LLMSettingsPanel from './LLMSettingsPanel'

export type SettingsTab = 'account' | 'appearance' | 'study' | 'llm' | 'about'

const tabs = [
  { id: 'account', label: 'Account', icon: UserRound },
  { id: 'appearance', label: 'Appearance', icon: Palette },
  { id: 'study', label: 'Study', icon: GraduationCap },
  { id: 'llm', label: 'LLM', icon: Bot },
  { id: 'about', label: 'About', icon: Info },
] as const

function StudySettings() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['settings'], queryFn: () => api<Overview['settings']>('/settings') })
  const [settings, setSettings] = useState<Overview['settings'] | null>(null)
  useEffect(() => { if (query.data) setSettings(query.data) }, [query.data])
  const save = useMutation({
    mutationFn: () => api<Overview['settings']>('/settings', json('PUT', settings)),
    onSuccess: data => {
      client.setQueryData(['settings'], data)
      client.invalidateQueries({ queryKey: ['study-overview'] })
      client.invalidateQueries({ queryKey: ['dictionary-search'] })
    },
  })

  if (query.isLoading || !settings) return query.error ? <ErrorNotice error={query.error} /> : <Loading label="Loading study preferences" />
  return <form className="settings-form" onSubmit={event => { event.preventDefault(); save.mutate() }}>
    <div className="settings-section-heading"><h3>Session size</h3><p>Choose how many cards appear in each study session.</p></div>
    <div className="settings-field-grid">
      <label className="field"><span>New words per batch</span><input type="number" min={1} max={100} required value={settings.learn_batch_size} onChange={event => setSettings({ ...settings, learn_batch_size: Number(event.target.value) })} /></label>
      <label className="field"><span>Reviews per batch</span><input type="number" min={1} max={100} required value={settings.review_batch_size} onChange={event => setSettings({ ...settings, review_batch_size: Number(event.target.value) })} /></label>
    </div>
    <label className="field"><span>Learning pool multiplier</span><input type="number" min={1} max={3} step={0.1} required value={settings.pool_multiplier} onChange={event => setSettings({ ...settings, pool_multiplier: Number(event.target.value) })} /><small>A larger pool adds more variety while you learn.</small></label>
    <div className="settings-section-heading settings-divider"><h3>Dictionary search</h3><p>Choose which entries appear in search results.</p></div>
    <label className="checkbox-field"><input type="checkbox" checked={settings.exclude_multiword_expressions} onChange={event => setSettings({ ...settings, exclude_multiword_expressions: event.target.checked })} /><span><strong>Hide multiword expressions</strong><small>Exclude phrases such as “good morning” from dictionary search.</small></span></label>
    {save.error && <ErrorNotice error={save.error} />}
    {save.isSuccess && JSON.stringify(settings) === JSON.stringify(query.data) && <p className="settings-saved" role="status">Study preferences saved.</p>}
    <div className="settings-actions"><Button type="submit" disabled={save.isPending || JSON.stringify(settings) === JSON.stringify(query.data)}>{save.isPending ? 'Saving…' : 'Save changes'}</Button></div>
  </form>
}

export default function SettingsDialog({ initialTab, user, logout, onClose }: { initialTab: SettingsTab; user: User; logout: () => Promise<void>; onClose: () => void }) {
  const [tab, setTab] = useState<SettingsTab>(initialTab)
  const [theme, setTheme] = useState<Theme>(getTheme)
  const [accent, setAccent] = useState<AccentColor>(getAccentColor)
  const chooseTheme = (choice: Theme) => { setTheme(choice); saveTheme(choice) }
  const chooseAccent = (choice: AccentColor) => { setAccent(choice); saveAccentColor(choice) }

  return <Modal title="Settings" className="settings-dialog" onClose={onClose}>
    <div className="settings-intro"><p>Make Vocab Collect work the way you like.</p></div>
    <div className="settings-tabs" role="tablist" aria-label="Settings sections">
      {tabs.map(item => <button key={item.id} id={`settings-tab-${item.id}`} role="tab" type="button" aria-selected={tab === item.id} aria-controls="settings-panel" tabIndex={tab === item.id ? 0 : -1} onClick={() => setTab(item.id)} onKeyDown={event => {
        if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
        event.preventDefault()
        const index = tabs.findIndex(value => value.id === item.id)
        const next = tabs[(index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length]
        setTab(next.id)
        document.getElementById(`settings-tab-${next.id}`)?.focus()
      }}><item.icon size={18} /><span>{item.label}</span></button>)}
    </div>
    <div id="settings-panel" className="settings-panel" role="tabpanel" aria-labelledby={`settings-tab-${tab}`}>
      {tab === 'account' && <div className="settings-stack">
        <div className="settings-section-heading"><h3>Your account</h3><p>Your progress is saved to this server.</p></div>
        <div className="settings-profile"><div className="settings-avatar" aria-hidden="true">{user.username.slice(0, 1).toUpperCase()}</div><div><strong>{user.username}</strong><span>Local account</span></div></div>
        <dl className="settings-details"><div><dt>Username</dt><dd>{user.username}</dd></div><div><dt>Member since</dt><dd>{new Intl.DateTimeFormat(undefined, { year: 'numeric', month: 'long', day: 'numeric' }).format(new Date(user.created_at))}</dd></div></dl>
        <div className="settings-account-action"><div><strong>Sign out</strong><p>End this session on this device.</p></div><Button variant="secondary" onClick={() => void logout()}><LogOut size={17} /> Sign out</Button></div>
      </div>}
      {tab === 'appearance' && <div className="settings-stack">
        <div className="settings-section-heading"><h3>Color theme</h3><p>Choose how the app looks on this device.</p></div>
        <div className="theme-options" role="radiogroup" aria-label="Color theme">
          {([{ value: 'system', label: 'System', detail: 'Match your device', icon: Monitor }, { value: 'light', label: 'Light', detail: 'Bright and clear', icon: Sun }, { value: 'dark', label: 'Dark', detail: 'Easy on the eyes', icon: Moon }] as const).map(option => <label key={option.value} className={`theme-option ${theme === option.value ? 'selected' : ''}`}><input type="radio" name="theme" value={option.value} checked={theme === option.value} onChange={() => chooseTheme(option.value)} /><option.icon size={22} /><strong>{option.label}</strong><span>{option.detail}</span></label>)}
        </div>
        <div className="settings-section-heading settings-divider"><h3>Accent color</h3><p>Personalize buttons, links, and highlights.</p></div>
        <div className="accent-options" role="radiogroup" aria-label="Accent color">
          {accentOptions.map(option => <label key={option.value} data-accent={option.value} className={`accent-option ${accent === option.value ? 'selected' : ''}`}><input type="radio" name="accent" value={option.value} checked={accent === option.value} onChange={() => chooseAccent(option.value)} /><span className="accent-swatch" aria-hidden="true">{accent === option.value && <Check size={17} />}</span><span>{option.label}</span></label>)}
        </div>
        <p className="settings-footnote">Changes apply immediately and are saved in this browser.</p>
      </div>}
      {tab === 'study' && <StudySettings />}
      {tab === 'llm' && <LLMSettingsPanel userId={user.id} />}
      {tab === 'about' && <div className="settings-stack">
        <div className="settings-about-mark"><BookOpen size={27} /></div>
        <div className="settings-section-heading"><h3>Vocab Collect</h3><p>A self-hosted place to collect words and build lasting recall.</p></div>
        <div className="settings-account-action"><div><strong>Licenses & attribution</strong><p>Read the notices for the dictionary data and software used by this app.</p></div><Link className="button button--secondary" to="/licenses" onClick={onClose}><Scale size={17} /> View notices</Link></div>
      </div>}
    </div>
  </Modal>
}
