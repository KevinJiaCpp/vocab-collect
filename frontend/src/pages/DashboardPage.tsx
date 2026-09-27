import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, CalendarDays, CheckCircle2, Layers3, SlidersHorizontal, Target } from 'lucide-react'
import { api } from '../api'
import { Button, ErrorNotice, Loading, PageHeader, Panel, Tag } from '../components'

type Dashboard = {
  due: { w2m: number; m2w: number }
  active_lists: number
  learned: number
  familiar: number
  useless: number
  activity_7d: { reviews: number; remembered: number }
  activity_30d: { reviews: number; remembered: number }
}
type Optimizer = { review_count: number; required: number; eligible: boolean; status: string; error?: string; optimized_at?: string }

const rate = (value: { reviews: number; remembered: number }) => value.reviews ? Math.round(value.remembered / value.reviews * 100) : 0

export default function DashboardPage() {
  const client = useQueryClient()
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: () => api<Dashboard>('/dashboard') })
  const optimizer = useQuery({ queryKey: ['optimizer'], queryFn: () => api<Optimizer>('/optimizer'), refetchInterval: query => query.state.data?.status === 'running' ? 2000 : false })
  const run = useMutation({ mutationFn: () => api('/optimizer', { method: 'POST' }), onSuccess: () => client.invalidateQueries({ queryKey: ['optimizer'] }) })
  if (dashboard.isLoading || optimizer.isLoading) return <Loading label="Calculating your progress" />
  if (dashboard.error || optimizer.error || !dashboard.data || !optimizer.data) return <ErrorNotice error={dashboard.error || optimizer.error} />
  const data = dashboard.data
  const opt = optimizer.data
  const progress = Math.min(100, Math.round(opt.review_count / opt.required * 100))
  return <div className="page dashboard-page">
    <PageHeader eyebrow="Progress" title="Dashboard" />
    <section className="stats-grid">
      <Panel className="stat-card"><div className="stat-icon blue"><Target /></div><div><span>Due cards</span><strong>{data.due.w2m + data.due.m2w}</strong><small>{data.due.w2m} forward · {data.due.m2w} reverse</small></div></Panel>
      <Panel className="stat-card"><div className="stat-icon cyan"><Layers3 /></div><div><span>Active lists</span><strong>{data.active_lists}</strong><small>feeding your study queue</small></div></Panel>
      <Panel className="stat-card"><div className="stat-icon purple"><CheckCircle2 /></div><div><span>Collected words</span><strong>{data.learned + data.familiar + data.useless}</strong><small>{data.familiar + data.useless} excluded</small></div></Panel>
    </section>
    <section className="dashboard-grid">
      <Panel className="activity-card"><div className="panel-heading"><div><p className="eyebrow">Recall</p><h2>Recent activity</h2></div><Activity size={23} /></div><div className="period-row"><div><CalendarDays /><span>Last 7 days</span><strong>{data.activity_7d.reviews}</strong><small>reviews</small></div><div className="rate-ring" style={{ '--rate': `${rate(data.activity_7d)}%` } as React.CSSProperties}><span>{rate(data.activity_7d)}%</span></div></div><div className="period-row"><div><CalendarDays /><span>Last 30 days</span><strong>{data.activity_30d.reviews}</strong><small>reviews</small></div><div className="rate-ring" style={{ '--rate': `${rate(data.activity_30d)}%` } as React.CSSProperties}><span>{rate(data.activity_30d)}%</span></div></div></Panel>
      <Panel className="optimizer-card"><div className="panel-heading"><div><p className="eyebrow">Personalization</p><h2>FSRS optimizer</h2></div><SlidersHorizontal size={23} /></div><p>After 400 reviews, Vocab Collect can tune the scheduler to your recall history.</p><div className="progress-track"><div style={{ width: `${progress}%` }} /></div><div className="progress-caption"><span>{opt.review_count} reviews</span><span>{opt.required}</span></div>{opt.status === 'complete' && <Tag tone="green">Optimized</Tag>}{opt.status === 'running' && <Tag tone="amber">Optimizing…</Tag>}{opt.error && <ErrorNotice error={opt.error} />}<Button onClick={() => run.mutate()} disabled={!opt.eligible || opt.status === 'running' || run.isPending}>{opt.eligible ? 'Optimize schedule' : `${opt.required - opt.review_count} reviews to go`}</Button></Panel>
    </section>
  </div>
}

