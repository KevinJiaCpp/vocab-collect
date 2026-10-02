import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Headphones, LoaderCircle, Plus, RefreshCw, Search, Sparkles, StickyNote, Volume2, X } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError, api, json } from '../api'
import { Button, Empty, ErrorNotice, Loading, PageHeader, Panel, Tag } from '../components'
import type { DictionaryEntry, Sense, WordListMembership } from '../types'
import type { components } from '../api.generated'

type SearchResult = { items: { word: string; match: string }[]; page: number; has_more: boolean }
type Audio = { url: string; source_url: string; title: string; creator: string; license: string; attribution: string }

export default function DictionaryPage() {
  const params = useParams()
  const navigate = useNavigate()
  const client = useQueryClient()
  const [query, setQuery] = useState(params.word || '')
  const [debounced, setDebounced] = useState(query)
  const [page, setPage] = useState(1)
  const [results, setResults] = useState<SearchResult['items']>([])
  const [hasMore, setHasMore] = useState(false)
  const [selectedWord, setSelectedWord] = useState(params.word || '')
  const [note, setNote] = useState('')
  useEffect(() => { const id = window.setTimeout(() => setDebounced(query.trim()), 250); return () => window.clearTimeout(id) }, [query])
  useEffect(() => { setPage(1); setResults([]); setHasMore(false) }, [debounced])
  const search = useQuery({ queryKey: ['dictionary-search', debounced, page], queryFn: () => api<SearchResult>(`/dictionary/search?q=${encodeURIComponent(debounced)}&page=${page}`), enabled: debounced.length > 0 })
  useEffect(() => { if (search.data) { setResults(previous => page === 1 ? search.data!.items : [...previous, ...search.data!.items]); setHasMore(search.data.has_more) } }, [search.data, page])
  const entry = useQuery({ queryKey: ['dictionary-entry', selectedWord], queryFn: () => api<DictionaryEntry>(`/dictionary/${encodeURIComponent(selectedWord)}`), enabled: !!selectedWord })
  useEffect(() => { setNote(entry.data?.note || '') }, [entry.data])
  const saveNote = useMutation({ mutationFn: () => api(`/words/${encodeURIComponent(selectedWord)}/note`, json('PUT', { body: note, display_word: entry.data?.word })), onSuccess: () => { client.invalidateQueries({ queryKey: ['notes'] }); client.invalidateQueries({ queryKey: ['dictionary-entry', selectedWord] }) } })
  const audio = useMutation({ mutationFn: () => api<Audio>(`/dictionary/${encodeURIComponent(selectedWord)}/audio`) })
  const selectWord = (word: string) => { setSelectedWord(word); setQuery(word); navigate(`/dictionary/${encodeURIComponent(word)}`, { replace: true }); audio.reset() }

  return <div className="page dictionary-page">
    <PageHeader eyebrow="Open English WordNet" title="Dictionary" />
    <div className="dictionary-layout">
      <aside className="dictionary-search-panel">
        <div className="search-field search-field--large"><Search size={21} /><input autoFocus value={query} onChange={event => setQuery(event.target.value)} placeholder="Search a word" aria-label="Search dictionary" /></div>
        {search.isFetching && <Loading label="Searching" />}
        {search.error && <ErrorNotice error={search.error} />}
        {!debounced && <div className="search-hint"><Search size={30} /><strong>Find a word</strong><span>Prefix and fuzzy matching help with partial spellings and typos.</span></div>}
        {(search.data || results.length > 0) && <div className="search-results">{results.map(item => <button key={item.word} className={selectedWord === item.word ? 'active' : ''} onClick={() => selectWord(item.word)}><span>{item.word}</span><Tag tone={item.match === 'exact' ? 'blue' : 'neutral'}>{item.match}</Tag></button>)}{!results.length && <Empty title="No close matches" detail="Check the spelling or try a shorter prefix." />}{hasMore && <button onClick={() => setPage(value => value + 1)} disabled={search.isFetching}>Load more results</button>}</div>}
      </aside>
      <section className="dictionary-entry-panel">
        {!selectedWord ? <Panel className="dictionary-welcome"><div className="dictionary-letter">Aa</div><h2>Definitions, connections, and structure</h2><p>Choose a result to see every sense, pronunciation, morphology, synonyms, antonyms, and derivatives.</p></Panel> : entry.isLoading ? <Loading label={`Looking up ${selectedWord}`} /> : entry.error && !(entry.error instanceof ApiError && entry.error.status === 404) ? <ErrorNotice error={entry.error} /> : !entry.data ? <Empty title="Definition unavailable" detail="This word can stay in a list, but it will not be scheduled for study." /> : <EntryView key={entry.data.word} entry={entry.data} />}
        {entry.data && <>
          <Panel className="dictionary-actions"><div className="panel-heading"><div><p className="eyebrow">Personal note</p><h2>What should you remember?</h2></div><StickyNote size={22} /></div><textarea aria-label={`Note for ${selectedWord}`} value={note} onChange={event => setNote(event.target.value)} rows={5} maxLength={20000} placeholder="Add context, a mnemonic, or your own example…" /><div className="align-right"><Button variant="secondary" onClick={() => saveNote.mutate()} disabled={saveNote.isPending}>Save note</Button></div>{saveNote.isSuccess && <div className="notice notice--success">Note saved.</div>}{saveNote.error && <ErrorNotice error={saveNote.error} />}</Panel>
          <Panel className="dictionary-actions"><div className="panel-heading"><div><p className="eyebrow">Wiktionary audio</p><h2>Hear a pronunciation</h2></div><Headphones size={22} /></div>{!audio.data ? <Button variant="secondary" onClick={() => audio.mutate()} disabled={audio.isPending}><Volume2 size={18} /> {audio.isPending ? 'Finding audio…' : 'Find audio'}</Button> : <div className="audio-result"><audio controls src={audio.data.url} /><div><strong>{audio.data.creator}</strong><span>{audio.data.license}</span>{audio.data.attribution && <small>{audio.data.attribution}</small>}<a href={audio.data.source_url} target="_blank" rel="noreferrer">Source & license <ExternalLink size={14} /></a></div></div>}{audio.error && <ErrorNotice error={audio.error} />}</Panel>
        </>}
      </section>
    </div>
  </div>
}

function EntryView({ entry }: { entry: DictionaryEntry }) {
  const byPos = entry.senses.reduce<Record<string, DictionaryEntry['senses']>>((groups, sense) => { (groups[sense.part_of_speech] ||= []).push(sense); return groups }, {})
  return <div className="entry-content">
    <header className="entry-header"><h2>{entry.word}</h2><CollectMenu word={entry.word} /><div className="pronunciations">{entry.pronunciations.length ? entry.pronunciations.map(value => <span key={value}>{value}</span>) : <span>Pronunciation unavailable</span>}</div></header>
    {entry.morphology && <Panel className="morphology"><p className="eyebrow">Word structure</p><div>{entry.morphology.prefixes?.map(item => <span key={`p-${item}`}><small>prefix</small>{item}</span>)}{entry.morphology.roots?.map(item => <span className="root" key={`r-${item}`}><small>root</small>{item}</span>)}{entry.morphology.suffixes?.map(item => <span key={`s-${item}`}><small>suffix</small>{item}</span>)}</div></Panel>}
    <div className="sense-groups">{Object.entries(byPos).map(([part, senses]) => <section key={part}><h3>{part}</h3><ol>{senses.map((sense, index) => <li key={`${part}-${index}`}><SenseExamples word={entry.word} sense={sense} senseIndex={entry.senses.indexOf(sense)} />{sense.synonyms.length > 0 && <Relation label="Synonyms" values={sense.synonyms} tone="blue" />}{sense.antonyms.length > 0 && <Relation label="Antonyms" values={sense.antonyms} tone="red" />}{sense.derivatives.length > 0 && <Relation label="Derivatives" values={sense.derivatives} tone="neutral" />}</li>)}</ol></section>)}</div>
    <p className="attribution">{entry.attribution}</p>
  </div>
}

function SenseExamples({ word, sense, senseIndex }: { word: string; sense: Sense; senseIndex: number }) {
  const client = useQueryClient()
  const trigger = useRef<HTMLButtonElement>(null)
  const clearTrigger = useRef<HTMLButtonElement>(null)
  const restoreFocus = useRef<'generate' | 'clear' | null>(null)
  const examples = sense.generated_examples || []
  const updateExamples = (values: string[]) => client.setQueriesData<DictionaryEntry>({ queryKey: ['dictionary-entry'] }, entry => !entry || entry.word !== word ? entry : {
    ...entry, senses: entry.senses.map((item, index) => index === senseIndex ? { ...item, generated_examples: values } : item),
  })
  const generate = useMutation({
    mutationFn: () => api<components['schemas']['ExampleSentencesOutput']>(`/dictionary/${encodeURIComponent(word)}/examples`, json('POST', { sense_index: senseIndex })),
    onMutate: () => { clear.reset(); return client.cancelQueries({ queryKey: ['dictionary-entry'] }) },
    onSuccess: data => updateExamples(data.examples),
  })
  const clear = useMutation({
    mutationFn: () => api(`/dictionary/${encodeURIComponent(word)}/examples/${senseIndex}`, { method: 'DELETE' }),
    onMutate: () => { generate.reset(); return client.cancelQueries({ queryKey: ['dictionary-entry'] }) },
    onSuccess: () => updateExamples([]),
  })
  const busy = generate.isPending || clear.isPending
  useEffect(() => {
    if (busy) {
      const onFocus = (event: FocusEvent) => { if (event.target !== trigger.current && event.target !== clearTrigger.current) restoreFocus.current = null }
      document.addEventListener('focusin', onFocus)
      return () => document.removeEventListener('focusin', onFocus)
    }
    if (restoreFocus.current && document.activeElement === document.body) (restoreFocus.current === 'clear' && examples.length ? clearTrigger : trigger).current?.focus()
    restoreFocus.current = null
  }, [examples.length, busy])
  return <div className="sense-examples" aria-busy={busy}>
    <div className="sense-definition">
      <p>{sense.definition}</p>
      {!examples.length && <button ref={trigger} type="button" className="example-action" aria-label={generate.isPending ? 'Generating…' : 'Generate examples'} title="Generate example sentences for this sense" disabled={busy} onClick={() => { restoreFocus.current = document.activeElement === trigger.current ? 'generate' : null; generate.mutate() }}>
        {generate.isPending ? <LoaderCircle size={14} className="spin" /> : <Sparkles size={14} />}
        {generate.isPending ? 'Generating…' : 'Examples'}
      </button>}
    </div>
    {sense.examples?.map(example => <blockquote key={example}>“{example}”</blockquote>)}
    {busy && <span className="sr-only" role="status">{generate.isPending ? 'Generating example sentences' : 'Clearing example sentences'}</span>}
    {examples.length > 0 && <div className="generated-examples" role="region" aria-label={`Generated examples for sense ${senseIndex + 1}`} aria-live="polite">
      <div className="sense-examples-actions">
        <span className="generated-examples-label"><Sparkles size={13} /> AI-generated</span>
        <button ref={trigger} type="button" className="example-action" disabled={busy} onClick={() => { restoreFocus.current = document.activeElement === trigger.current ? 'generate' : null; generate.mutate() }}>{generate.isPending ? <LoaderCircle size={14} className="spin" /> : <RefreshCw size={14} />}{generate.isPending ? 'Generating…' : 'Regenerate'}</button>
        <button ref={clearTrigger} type="button" className="example-action" disabled={busy} onClick={() => { restoreFocus.current = document.activeElement === clearTrigger.current ? 'clear' : null; clear.mutate() }}>{clear.isPending ? <LoaderCircle size={14} className="spin" /> : <X size={14} />}{clear.isPending ? 'Clearing…' : 'Clear'}</button>
      </div>
      {examples.map((example, index) => <blockquote key={index}>“{example}”</blockquote>)}
    </div>}
    {generate.error && <ErrorNotice error={generate.error} />}
    {clear.error && <ErrorNotice error={clear.error} />}
  </div>
}

function CollectMenu({ word }: { word: string }) {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const membership = useQuery({ queryKey: ['word-lists', word], queryFn: () => api<WordListMembership[]>(`/words/${encodeURIComponent(word)}/lists`) })
  const toggle = useMutation({
    mutationFn: (item: WordListMembership) => item.contains
      ? api(`/lists/${item.id}/entries/${item.entry_id}`, { method: 'DELETE' })
      : api(`/lists/${item.id}/entries`, json('POST', { word })),
    onSuccess: () => { client.invalidateQueries({ queryKey: ['word-lists', word] }); client.invalidateQueries({ queryKey: ['lists'] }) },
  })
  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => { if (!wrap.current?.contains(event.target as Node)) setOpen(false) }
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); trigger.current?.focus() } }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => { document.removeEventListener('mousedown', onPointerDown); document.removeEventListener('keydown', onKeyDown) }
  }, [open])
  const items = membership.data || []
  const collected = items.filter(item => item.contains).length
  return <div className="collect-menu-wrap" ref={wrap}>
    <button ref={trigger} type="button" className="collect-button" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen(value => !value)}>Collect{collected > 0 && <span className="collect-count">{collected}</span>}<Plus size={16} /></button>
    {open && <div className="collect-menu" role="group" aria-label="Word lists">
      {membership.isLoading && <Loading label="Loading lists" />}
      {membership.error && <ErrorNotice error={membership.error} />}
      {!membership.isLoading && !items.length && <p className="collect-empty">No word lists yet. Create one in the Collection tab.</p>}
      {items.map(item => <label className="collect-option" key={item.id}><input type="checkbox" checked={item.contains} disabled={toggle.isPending && toggle.variables?.id === item.id} onChange={() => toggle.mutate(item)} /><span>{item.name}</span></label>)}
      {toggle.error && <ErrorNotice error={toggle.error} />}
    </div>}
  </div>
}

function Relation({ label, values, tone }: { label: string; values: string[]; tone: 'blue' | 'red' | 'neutral' }) {
  return <div className="relation-row"><span>{label}</span><div>{values.map(value => <Tag key={value} tone={tone}>{value}</Tag>)}</div></div>
}
