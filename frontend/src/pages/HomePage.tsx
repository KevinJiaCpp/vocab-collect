import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, BookMarked, Brain, Clock3, RotateCcw, Settings2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, json } from '../api'
import { Button, ErrorNotice, Loading, Modal, PageHeader, Panel, Segmented, Tag } from '../components'
import type { Direction, Overview, SessionSummary } from '../types'

export default function HomePage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [direction, setDirection] = useState<Direction>('w2m')
  const [showSettings, setShowSettings] = useState(false)
  const [showReviewWarning, setShowReviewWarning] = useState(false)
  const overview = useQuery({ queryKey: ['study-overview'], queryFn: () => api<Overview>('/study/overview') })
  const [settings, setSettings] = useState({ learn_batch_size: 10, review_batch_size: 20, pool_multiplier: 1.5, exclude_multiword_expressions: false })
  useEffect(() => { if (overview.data) setSettings(overview.data.settings) }, [overview.data])
  const updateSettings = useMutation({
    mutationFn: () => api('/settings', json('PUT', settings)),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['study-overview'] }); setShowSettings(false) },
  })
  const start = useMutation({
    mutationFn: ({ kind, override = false }: { kind: 'learning' | 'review'; override?: boolean }) => api<SessionSummary>('/study/sessions', json('POST', { kind, direction, override_due: override })),
    onSuccess: session => navigate(`/study/${session.id}`),
    onError: error => { if (error instanceof ApiError && error.status === 409) setShowReviewWarning(true) },
  })
  if (overview.isLoading) return <Loading label="Loading today’s plan" />
  if (overview.error || !overview.data) return <ErrorNotice error={overview.error} />
  const data = overview.data
  const dueTotal = data.due.w2m + data.due.m2w
  const selectedDue = data.due[direction]
  const selectedNew = data.new[direction]

  return <div className="page home-page">
    <PageHeader eyebrow="Today" title="Ready when you are" actions={<Button variant="secondary" onClick={() => setShowSettings(true)}><Settings2 size={18} /> Study settings</Button>} />
    {data.active_session && <Panel className="resume-banner"><div><Tag tone="amber">In progress</Tag><h2>Continue your {data.active_session.kind} session</h2><p>{data.active_session.completed_count} of {data.active_session.target_count} completed</p></div><Button onClick={() => navigate(`/study/${data.active_session!.id}`)}>Resume <ArrowRight size={18} /></Button></Panel>}
    <section className="today-grid">
      <Panel className="focus-card focus-card--review">
        <div className="focus-icon"><RotateCcw /></div>
        <div><p className="metric-label">Due now</p><strong className="metric-value">{dueTotal}</strong><p className="metric-detail">{data.due.w2m} forward · {data.due.m2w} reverse</p></div>
        <Button onClick={() => start.mutate({ kind: 'review' })} disabled={!selectedDue || start.isPending}>Review {selectedDue || ''}<ArrowRight size={18} /></Button>
      </Panel>
      <Panel className="focus-card focus-card--learn">
        <div className="focus-icon"><Brain /></div>
        <div><p className="metric-label">Ready to learn</p><strong className="metric-value">{selectedNew}</strong><p className="metric-detail">From your active lists</p></div>
        <Button onClick={() => start.mutate({ kind: 'learning' })} disabled={!selectedNew || start.isPending}>Learn {Math.min(selectedNew, settings.learn_batch_size) || ''}<ArrowRight size={18} /></Button>
      </Panel>
    </section>
    {start.error && !(start.error instanceof ApiError && start.error.status === 409) && <ErrorNotice error={start.error} />}
    <Panel className="direction-panel">
      <div><p className="eyebrow">Recall direction</p><h2>Choose your prompt</h2><p>Reverse cards unlock after the forward card reaches review.</p></div>
      <Segmented value={direction} onChange={setDirection} label="Recall direction" options={[{ value: 'w2m', label: 'Word → meaning' }, { value: 'm2w', label: 'Meaning → word' }]} />
    </Panel>
    <section className="mini-grid">
      <Panel><Clock3 size={22} /><div><strong>{settings.review_batch_size}</strong><span>review cards per batch</span></div></Panel>
      <Panel><BookMarked size={22} /><div><strong>{settings.learn_batch_size}</strong><span>new words per batch</span></div></Panel>
      <Panel><Brain size={22} /><div><strong>4</strong><span>learning stages</span></div></Panel>
    </section>

    {showSettings && <Modal title="Study settings" onClose={() => setShowSettings(false)}><form className="modal-form" onSubmit={event => { event.preventDefault(); updateSettings.mutate() }}>
      <label className="field"><span>New words per batch</span><input type="number" min={1} max={100} value={settings.learn_batch_size} onChange={event => setSettings({ ...settings, learn_batch_size: Number(event.target.value) })} /></label>
      <label className="field"><span>Reviews per batch</span><input type="number" min={1} max={100} value={settings.review_batch_size} onChange={event => setSettings({ ...settings, review_batch_size: Number(event.target.value) })} /></label>
      <label className="field"><span>Learning pool multiplier</span><input type="number" min={1} max={3} step={0.1} value={settings.pool_multiplier} onChange={event => setSettings({ ...settings, pool_multiplier: Number(event.target.value) })} /><small>A larger pool adds more variety while you learn.</small></label>
      <label className="checkbox-field"><input type="checkbox" checked={settings.exclude_multiword_expressions} onChange={event => setSettings({ ...settings, exclude_multiword_expressions: event.target.checked })} /><span><strong>Hide multiword expressions</strong><small>Exclude phrases such as “good morning” from dictionary search.</small></span></label>
      {updateSettings.error && <ErrorNotice error={updateSettings.error} />}
      <div className="modal-actions"><Button type="button" variant="ghost" onClick={() => setShowSettings(false)}>Cancel</Button><Button type="submit" disabled={updateSettings.isPending}>Save settings</Button></div>
    </form></Modal>}
    {showReviewWarning && <Modal title="Reviews are waiting" onClose={() => setShowReviewWarning(false)}><div className="dialog-copy"><p>You have {dueTotal} cards due. Reviewing first keeps your schedule accurate.</p><div className="modal-actions stacked-mobile"><Button variant="secondary" onClick={() => { setShowReviewWarning(false); start.mutate({ kind: 'review' }) }}>Review first</Button><Button onClick={() => { setShowReviewWarning(false); start.mutate({ kind: 'learning', override: true }) }}>Learn anyway</Button></div></div></Modal>}
  </div>
}
