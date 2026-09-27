import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookPlus, ExternalLink, Headphones, Search, StickyNote, Volume2 } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError, api, json } from '../api'
import { Button, Empty, ErrorNotice, Loading, PageHeader, Panel, Tag } from '../components'
import type { DictionaryEntry, WordList } from '../types'

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
  const [selectedList, setSelectedList] = useState('')
  const [note, setNote] = useState('')
  useEffect(() => { const id = window.setTimeout(() => setDebounced(query.trim()), 250); return () => window.clearTimeout(id) }, [query])
  useEffect(() => { setPage(1); setResults([]); setHasMore(false) }, [debounced])
  const search = useQuery({ queryKey: ['dictionary-search', debounced, page], queryFn: () => api<SearchResult>(`/dictionary/search?q=${encodeURIComponent(debounced)}&page=${page}`), enabled: debounced.length > 0 })
  useEffect(() => { if (search.data) { setResults(previous => page === 1 ? search.data!.items : [...previous, ...search.data!.items]); setHasMore(search.data.has_more) } }, [search.data, page])
  const entry = useQuery({ queryKey: ['dictionary-entry', selectedWord], queryFn: () => api<DictionaryEntry>(`/dictionary/${encodeURIComponent(selectedWord)}`), enabled: !!selectedWord })
  useEffect(() => { setNote(entry.data?.note || '') }, [entry.data])
  const lists = useQuery({ queryKey: ['lists'], queryFn: () => api<WordList[]>('/lists') })
  const add = useMutation({ mutationFn: () => api(`/lists/${selectedList}/entries`, json('POST', { word: selectedWord })), onSuccess: () => client.invalidateQueries({ queryKey: ['lists'] }) })
  const saveNote = useMutation({ mutationFn: () => api(`/words/${encodeURIComponent(selectedWord)}/note`, json('PUT', { body: note, display_word: entry.data?.word })), onSuccess: () => { client.invalidateQueries({ queryKey: ['notes'] }); client.invalidateQueries({ queryKey: ['dictionary-entry', selectedWord] }) } })
  const audio = useMutation({ mutationFn: () => api<Audio>(`/dictionary/${encodeURIComponent(selectedWord)}/audio`) })
  const selectWord = (word: string) => { setSelectedWord(word); setQuery(word); navigate(`/dictionary/${encodeURIComponent(word)}`, { replace: true }); audio.reset(); add.reset() }

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
        {!selectedWord ? <Panel className="dictionary-welcome"><div className="dictionary-letter">Aa</div><h2>Definitions, connections, and structure</h2><p>Choose a result to see every sense, pronunciation, morphology, synonyms, antonyms, and derivatives.</p></Panel> : entry.isLoading ? <Loading label={`Looking up ${selectedWord}`} /> : entry.error && !(entry.error instanceof ApiError && entry.error.status === 404) ? <ErrorNotice error={entry.error} /> : !entry.data ? <Empty title="Definition unavailable" detail="This word can stay in a list, but it will not be scheduled for study." /> : <EntryView entry={entry.data} />}
        {entry.data && <>
          <Panel className="dictionary-actions"><div className="panel-heading"><div><p className="eyebrow">Collect</p><h2>Save this word</h2></div><BookPlus size={22} /></div><div className="inline-form"><select value={selectedList} onChange={event => setSelectedList(event.target.value)} aria-label="Word list"><option value="">Choose a list</option>{lists.data?.map(list => <option key={list.id} value={list.id}>{list.name}</option>)}</select><Button onClick={() => add.mutate()} disabled={!selectedList || add.isPending}>Add to list</Button></div>{add.isSuccess && <div className="notice notice--success">Added to your list.</div>}{add.error && <ErrorNotice error={add.error} />}</Panel>
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
    <header className="entry-header"><div><h2>{entry.word}</h2><div className="pronunciations">{entry.pronunciations.length ? entry.pronunciations.map(value => <span key={value}>{value}</span>) : <span>Pronunciation unavailable</span>}</div></div>{entry.morphology?.seg && <Tag tone="blue">{entry.morphology.seg}</Tag>}</header>
    {entry.morphology && <Panel className="morphology"><p className="eyebrow">Word structure</p><div>{entry.morphology.prefixes?.map(item => <span key={`p-${item}`}><small>prefix</small>{item}</span>)}{entry.morphology.roots?.map(item => <span className="root" key={`r-${item}`}><small>root</small>{item}</span>)}{entry.morphology.suffixes?.map(item => <span key={`s-${item}`}><small>suffix</small>{item}</span>)}</div></Panel>}
    <div className="sense-groups">{Object.entries(byPos).map(([part, senses]) => <section key={part}><h3>{part}</h3><ol>{senses.map((sense, index) => <li key={`${part}-${index}`}><p>{sense.definition}</p>{sense.examples?.map(example => <blockquote key={example}>“{example}”</blockquote>)}{sense.synonyms.length > 0 && <Relation label="Synonyms" values={sense.synonyms} tone="blue" />}{sense.antonyms.length > 0 && <Relation label="Antonyms" values={sense.antonyms} tone="red" />}{sense.derivatives.length > 0 && <Relation label="Derivatives" values={sense.derivatives} tone="neutral" />}</li>)}</ol></section>)}</div>
    <p className="attribution">{entry.attribution}</p>
  </div>
}

function Relation({ label, values, tone }: { label: string; values: string[]; tone: 'blue' | 'red' | 'neutral' }) {
  return <div className="relation-row"><span>{label}</span><div>{values.map(value => <Tag key={value} tone={tone}>{value}</Tag>)}</div></div>
}
