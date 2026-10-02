import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Ban, CheckCircle2, Eye, Flag, Keyboard, Volume2 } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, json } from '../api'
import { Button, ErrorNotice, Loading, Panel, Tag } from '../components'
import type { DictionaryEntry, Direction, Sense, SessionSummary } from '../types'

type StudyResponse = {
  session: SessionSummary
  presentation_token?: string
  revealed?: boolean
  item: null | {
    card_id: number
    direction: Direction
    prompt: { word?: string; senses?: Sense[] }
    answer?: DictionaryEntry
  }
}

const ratingLabels = [
  { value: 1, label: 'Again', hint: 'Forgot', className: 'again' },
  { value: 2, label: 'Hard', hint: 'Struggled', className: 'hard' },
  { value: 3, label: 'Good', hint: 'Recalled', className: 'good' },
  { value: 4, label: 'Easy', hint: 'Instant', className: 'easy' },
]

export default function StudyPage() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const client = useQueryClient()
  const startedAt = useRef(Date.now())
  const study = useQuery({ queryKey: ['study-session', sessionId], queryFn: () => api<StudyResponse>(`/study/sessions/${sessionId}/next`), enabled: !!sessionId })
  useEffect(() => { client.removeQueries({ queryKey: ['study-overview'] }) }, [client])
  useEffect(() => { startedAt.current = Date.now() }, [study.data?.presentation_token])
  const reveal = useMutation({ mutationFn: () => api<StudyResponse>(`/study/sessions/${sessionId}/reveal`, json('POST', { presentation_token: study.data?.presentation_token })), onSuccess: data => client.setQueryData(['study-session', sessionId], data) })
  const answer = useMutation({ mutationFn: (rating: number) => api<{ session: SessionSummary }>(`/study/sessions/${sessionId}/answer`, json('POST', { presentation_token: study.data?.presentation_token, rating, duration_ms: Date.now() - startedAt.current })), onSuccess: async data => { client.invalidateQueries({ queryKey: ['study-overview'] }); client.invalidateQueries({ queryKey: ['dashboard'] }); if (data.session.status === 'completed') client.setQueryData(['study-session', sessionId], { session: data.session, item: null }); else await study.refetch() } })
  const exclude = useMutation({ mutationFn: ({ status }: { status: 'familiar' | 'useless' }) => api<SessionSummary>(`/study/sessions/${sessionId}/skip`, json('POST', { presentation_token: study.data?.presentation_token, status })), onSuccess: async data => { client.invalidateQueries({ queryKey: ['study-overview'] }); if (data.status === 'completed') client.setQueryData(['study-session', sessionId], { session: data, item: null }); else await study.refetch() } })

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && event.target.closest('button, a, input, textarea, select, [contenteditable]')) return
      if (event.code === 'Space') { event.preventDefault(); if (!study.data?.revealed && study.data?.item && !reveal.isPending) reveal.mutate() }
      if (study.data?.revealed && !answer.isPending && ['1', '2', '3', '4'].includes(event.key)) answer.mutate(Number(event.key))
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [study.data, reveal, answer])

  if (study.isLoading) return <div className="study-page"><Loading label="Preparing your cards" /></div>
  if (study.error || !study.data) return <div className="study-page"><ErrorNotice error={study.error} /></div>
  const data = study.data
  if (data.session.status === 'completed' || !data.item) return <div className="study-page study-complete"><Panel><div className="complete-mark"><CheckCircle2 size={42} /></div><p className="eyebrow">Session complete</p><h1>Nice work.</h1><p>You completed {data.session.completed_count} {data.session.completed_count === 1 ? 'card' : 'cards'} in this {data.session.kind} session.</p><div className="session-progress"><div style={{ width: '100%' }} /></div><Button onClick={() => navigate('/')}>Back to home</Button></Panel></div>
  const progress = Math.min(100, Math.round(data.session.completed_count / Math.max(1, data.session.target_count) * 100))

  return <div className="study-page">
    <header className="study-header"><button className="back-button" onClick={() => navigate('/')}><ArrowLeft size={20} /> Exit</button><div><strong>{data.session.kind === 'learning' ? 'Learning' : 'Review'}</strong><span>{data.session.direction === 'w2m' ? 'Word → meaning' : 'Meaning → word'}</span></div><span>{data.session.completed_count} / {data.session.target_count}</span></header>
    <div className="session-progress"><div style={{ width: `${progress}%` }} /></div>
    <main className="study-workspace">
      <section className={`study-card ${data.revealed ? 'revealed' : ''}`}>
        <div className="card-label">{data.item.direction === 'w2m' ? 'What does this word mean?' : 'Which word matches these meanings?'}</div>
        <div className="card-prompt">{data.item.prompt.word ? <h1>{data.item.prompt.word}</h1> : <PromptSenses senses={data.item.prompt.senses || []} />}</div>
        {!data.revealed ? <Button className="reveal-button" onClick={() => reveal.mutate()} disabled={reveal.isPending}><Eye size={19} /> Reveal answer <kbd>Space</kbd></Button> : data.item.answer && <Answer entry={data.item.answer} />}
      </section>
      {data.revealed && <div className="rating-area"><p>How well did you recall it?</p><div className="rating-buttons">{ratingLabels.map(rating => <button key={rating.value} className={rating.className} onClick={() => answer.mutate(rating.value)} disabled={answer.isPending}><span>{rating.value}</span><strong>{rating.label}</strong><small>{rating.hint}</small></button>)}</div></div>}
      <div className="study-secondary-actions"><button onClick={() => exclude.mutate({ status: 'familiar' })}><Flag size={17} /> I already know this</button><button onClick={() => exclude.mutate({ status: 'useless' })}><Ban size={17} /> Not useful to me</button><span><Keyboard size={16} /> Space to reveal · 1–4 to grade</span></div>
      {(reveal.error || answer.error || exclude.error) && <ErrorNotice error={reveal.error || answer.error || exclude.error} />}
    </main>
  </div>
}

function PromptSenses({ senses }: { senses: Sense[] }) {
  return <div className="reverse-prompt">{senses.map((sense, index) => <div key={index}><Tag>{sense.part_of_speech}</Tag><p>{sense.definition}</p></div>)}</div>
}

function Answer({ entry }: { entry: DictionaryEntry }) {
  return <div className="card-answer"><div className="answer-heading"><div><h2>{entry.word}</h2><span>{entry.pronunciations.join(' · ')}</span></div>{entry.pronunciations.length > 0 && <Volume2 size={21} />}</div>{entry.morphology?.seg && <Tag tone="blue">{entry.morphology.seg}</Tag>}<ol>{entry.senses.map((sense, index) => <li key={index}><span>{sense.part_of_speech}</span><p>{sense.definition}</p>{sense.synonyms.length > 0 && <small>Synonyms: {sense.synonyms.join(', ')}</small>}</li>)}</ol></div>
}
