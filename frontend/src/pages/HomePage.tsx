import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowRight, BookMarked, Brain, Clock3, RotateCcw } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, json } from '../api'
import { Button, ErrorNotice, Loading, Modal, PageHeader, Panel, Segmented } from '../components'
import type { Direction, Overview, SessionSummary } from '../types'

export default function HomePage() {
  const navigate = useNavigate()
  const [direction, setDirection] = useState<Direction>('w2m')
  const [showReviewWarning, setShowReviewWarning] = useState(false)
  const overview = useQuery({ queryKey: ['study-overview'], queryFn: () => api<Overview>('/study/overview') })
  const start = useMutation({
    mutationFn: ({ kind, override = false }: { kind: 'learning' | 'review'; override?: boolean }) => api<SessionSummary>('/study/sessions', json('POST', { kind, direction, override_due: override })),
    onSuccess: session => navigate(`/study/${session.id}`),
    onError: error => { if (error instanceof ApiError && error.status === 409) setShowReviewWarning(true) },
  })
  if (overview.isLoading) return <Loading label="Loading today’s plan" />
  if (overview.error || !overview.data) return <ErrorNotice error={overview.error} />
  const data = overview.data
  const settings = data.settings
  const dueTotal = data.due.w2m + data.due.m2w
  const selectedDue = data.due[direction]
  const selectedNew = data.new[direction]
  const hasReviewSession = data.active_sessions.some(session => session.kind === 'review' && session.direction === direction)
  const hasLearningSession = data.active_sessions.some(session => session.kind === 'learning' && session.direction === direction)

  return <div className="page home-page">
    <PageHeader eyebrow="Today" title="Ready when you are" />
    <section className="today-grid">
      <Panel className="focus-card focus-card--review">
        <div className="focus-icon"><RotateCcw /></div>
        <div><p className="metric-label">Due now</p><strong className="metric-value">{dueTotal}</strong><p className="metric-detail">{data.due.w2m} forward · {data.due.m2w} reverse</p></div>
        <Button onClick={() => start.mutate({ kind: 'review' })} disabled={(!selectedDue && !hasReviewSession) || start.isPending}>Review {selectedDue || ''}<ArrowRight size={18} /></Button>
      </Panel>
      <Panel className="focus-card focus-card--learn">
        <div className="focus-icon"><Brain /></div>
        <div><p className="metric-label">Ready to learn</p><strong className="metric-value">{selectedNew}</strong><p className="metric-detail">From your active lists</p></div>
        <Button onClick={() => start.mutate({ kind: 'learning' })} disabled={(!selectedNew && !hasLearningSession) || start.isPending}>Learn {Math.min(selectedNew, settings.learn_batch_size) || ''}<ArrowRight size={18} /></Button>
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

    {showReviewWarning && <Modal title="Reviews are waiting" onClose={() => setShowReviewWarning(false)}><div className="dialog-copy"><p>You have {dueTotal} cards due. Reviewing first keeps your schedule accurate.</p><div className="modal-actions stacked-mobile"><Button variant="secondary" onClick={() => { setShowReviewWarning(false); start.mutate({ kind: 'review' }) }}>Review first</Button><Button onClick={() => { setShowReviewWarning(false); start.mutate({ kind: 'learning', override: true }) }}>Learn anyway</Button></div></div></Modal>}
  </div>
}
