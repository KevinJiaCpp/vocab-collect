import { createContext, useContext, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BarChart3, BookOpen, Home, Library, LogOut, Menu, Scale, Search, Sparkles, X } from 'lucide-react'
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { ApiError, api, json } from './api'
import { Button, ErrorNotice, Field, Loading } from './components'
import type { User } from './types'
import HomePage from './pages/HomePage'
import DashboardPage from './pages/DashboardPage'
import CollectionPage from './pages/CollectionPage'
import DictionaryPage from './pages/DictionaryPage'
import StudyPage from './pages/StudyPage'
import LicensesPage from './pages/LicensesPage'

type AuthContextValue = { user: User; logout: () => Promise<void> }
const AuthContext = createContext<AuthContextValue | null>(null)
export const useAuth = () => {
  const value = useContext(AuthContext)
  if (!value) throw new Error('Auth context is unavailable')
  return value
}

function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => api<User>(`/auth/${mode}`, json('POST', { username, password })),
    onSuccess: user => queryClient.setQueryData(['me'], user),
  })
  return <main className="auth-layout">
    <div className="auth-brand"><div className="brand-mark"><BookOpen size={27} /></div><span>Vocab Collect</span></div>
    <section className="auth-card">
      <p className="eyebrow">Your vocabulary, in motion</p>
      <h1>{mode === 'login' ? 'Welcome back' : 'Create your account'}</h1>
      <p className="auth-copy">Collect useful words and build lasting recall at your own pace.</p>
      <form onSubmit={event => { event.preventDefault(); mutation.mutate() }}>
        <Field label="Username" autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} required minLength={3} maxLength={32} />
        <Field label="Password" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={event => setPassword(event.target.value)} required minLength={10} maxLength={128} hint={mode === 'register' ? 'Use at least 10 characters.' : undefined} />
        {mutation.error && <ErrorNotice error={mutation.error} />}
        <Button type="submit" disabled={mutation.isPending}>{mutation.isPending ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}</Button>
      </form>
      <button className="text-button" onClick={() => navigate(mode === 'login' ? '/register' : '/login')}>
        {mode === 'login' ? 'New here? Create an account' : 'Already have an account? Sign in'}
      </button>
    </section>
    <p className="auth-footnote">Self-hosted · Your progress stays on this server</p>
  </main>
}

const navItems = [
  { to: '/', label: 'Home', icon: Home },
  { to: '/dashboard', label: 'Dashboard', icon: BarChart3 },
  { to: '/collection', label: 'Collection', icon: Library },
  { to: '/dictionary', label: 'Dictionary', icon: Search },
]

function Shell({ user, children }: { user: User; children: React.ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const location = useLocation()
  const logout = async () => {
    await api('/auth/logout', { method: 'POST' })
    queryClient.setQueryData(['me'], null)
    queryClient.clear()
    navigate('/login')
  }
  return <AuthContext.Provider value={{ user, logout }}>
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand"><div className="brand-mark"><BookOpen size={24} /></div><strong>Vocab Collect</strong></div>
        <nav aria-label="Primary">{navItems.map(item => <NavLink key={item.to} to={item.to} end={item.to === '/'} className={({ isActive }) => isActive ? 'active' : ''}><item.icon size={21} /><span>{item.label}</span></NavLink>)}</nav>
        <div className="sidebar-footer">
          <NavLink to="/licenses"><Scale size={20} /><span>Licenses</span></NavLink>
          <div className="user-chip"><div className="avatar">{user.username.slice(0, 1).toUpperCase()}</div><div><strong>{user.username}</strong><span>Local account</span></div></div>
          <button className="logout-button" onClick={logout}><LogOut size={18} /> Sign out</button>
        </div>
      </aside>
      <header className="mobile-header"><div className="sidebar-brand"><div className="brand-mark"><BookOpen size={21} /></div><strong>Vocab Collect</strong></div><button className="icon-button" onClick={() => setMenuOpen(!menuOpen)} aria-label="Open account menu">{menuOpen ? <X /> : <Menu />}</button></header>
      {menuOpen && <div className="mobile-menu"><strong>{user.username}</strong><NavLink to="/licenses" onClick={() => setMenuOpen(false)}><Scale size={18} /> Licenses</NavLink><button onClick={logout}><LogOut size={18} /> Sign out</button></div>}
      <main className="main-content" key={location.pathname}>{children}</main>
      <nav className="bottom-nav" aria-label="Primary">{navItems.map(item => <NavLink key={item.to} to={item.to} end={item.to === '/'} className={({ isActive }) => isActive ? 'active' : ''}><item.icon size={21} /><span>{item.label}</span></NavLink>)}</nav>
    </div>
  </AuthContext.Provider>
}

function ProtectedApp({ user }: { user: User }) {
  const location = useLocation()
  if (location.pathname.startsWith('/study/')) return <Routes><Route path="/study/:sessionId" element={<StudyPage />} /></Routes>
  return <Shell user={user}><Routes>
    <Route path="/" element={<HomePage />} />
    <Route path="/dashboard" element={<DashboardPage />} />
    <Route path="/collection" element={<CollectionPage />} />
    <Route path="/dictionary" element={<DictionaryPage />} />
    <Route path="/dictionary/:word" element={<DictionaryPage />} />
    <Route path="/licenses" element={<LicensesPage />} />
    <Route path="/login" element={<Navigate to="/" replace />} />
    <Route path="/register" element={<Navigate to="/" replace />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes></Shell>
}

export default function App() {
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<User>('/auth/me'), retry: false })
  if (me.isLoading) return <div className="splash"><div className="brand-mark"><Sparkles /></div><Loading label="Opening your collection" /></div>
  if (me.error && !(me.error instanceof ApiError && me.error.status === 401)) return <main className="auth-layout"><ErrorNotice error={me.error} /><Button onClick={() => me.refetch()}>Try again</Button></main>
  if (!me.data) return <Routes>
    <Route path="/login" element={<AuthPage mode="login" />} />
    <Route path="/register" element={<AuthPage mode="register" />} />
    <Route path="*" element={<Navigate to="/login" replace />} />
  </Routes>
  return <ProtectedApp user={me.data} />
}
