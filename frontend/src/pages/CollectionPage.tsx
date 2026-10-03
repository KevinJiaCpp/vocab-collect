import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Check, ChevronDown, Download, FileUp, MoreHorizontal, Plus, Search, Shuffle, SlidersHorizontal, Trash2, X } from 'lucide-react'
import { api, downloadUrl, json } from '../api'
import { Button, Empty, ErrorNotice, IconButton, Loading, Modal, PageHeader, Panel, Segmented, Tag } from '../components'
import type { ListDirection, WordList } from '../types'

type Tab = 'lists' | 'learned' | 'notes'
type LearnedWord = { word: string; normalized_word: string; status: 'active' | 'familiar' | 'useless'; cards: { direction: string; state: number; due: string }[] }
type LearnedFilters = { status: LearnedWord['status'] | 'all'; direction: 'uni' | 'bi' | 'all'; stage: '0' | '1' | '2' | '3' | 'all' }
type Note = { word: string; normalized_word: string; body: string; updated_at: string }
const defaultLearnedFilters: LearnedFilters = { status: 'all', direction: 'all', stage: 'all' }

export default function CollectionPage() {
  const [tab, setTab] = useState<Tab>('lists')
  return <div className="page collection-page">
    <PageHeader eyebrow="Your library" title="Collection" />
    <Segmented value={tab} onChange={setTab} label="Collection section" options={[{ value: 'lists', label: 'Word lists' }, { value: 'learned', label: 'Learned words' }, { value: 'notes', label: 'Notes' }]} />
    {tab === 'lists' && <ListsView />}
    {tab === 'learned' && <LearnedView />}
    {tab === 'notes' && <NotesView />}
  </div>
}

function ListsView() {
  const client = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [direction, setDirection] = useState<ListDirection>('w2m')
  const lists = useQuery({ queryKey: ['lists'], queryFn: () => api<WordList[]>('/lists') })
  const selected = useQuery({ queryKey: ['list', selectedId], queryFn: () => api<WordList>(`/lists/${selectedId}`), enabled: selectedId !== null })
  const refresh = () => { client.invalidateQueries({ queryKey: ['lists'] }); if (selectedId) client.invalidateQueries({ queryKey: ['list', selectedId] }); client.invalidateQueries({ queryKey: ['study-overview'] }) }
  const create = useMutation({ mutationFn: () => api<WordList>('/lists', json('POST', { name, direction, is_active: true })), onSuccess: value => { refresh(); setCreateOpen(false); setName(''); setSelectedId(value.id) } })
  const patchList = useMutation({ mutationFn: ({ id, body }: { id: number; body: object }) => api(`/lists/${id}`, json('PATCH', body)), onSuccess: refresh })
  const shuffle = useMutation({ mutationFn: (id: number) => api(`/lists/${id}/shuffle`, { method: 'POST' }), onSuccess: refresh })
  const remove = useMutation({ mutationFn: (id: number) => api(`/lists/${id}`, { method: 'DELETE' }), onSuccess: () => { setSelectedId(null); refresh() } })
  const importList = useMutation({ mutationFn: async (file: File) => { const data = new FormData(); data.append('file', file); data.append('direction', direction); return api('/lists/import', { method: 'POST', body: data }) }, onSuccess: refresh })
  if (lists.isLoading) return <Loading label="Opening your lists" />
  if (lists.error || !lists.data) return <ErrorNotice error={lists.error} />
  return <section className="collection-section">
    <div className="section-toolbar"><div><strong>{lists.data.length} lists</strong><span>{lists.data.filter(item => item.is_active).length} active</span></div><div><input ref={fileRef} type="file" accept=".json,.txt,text/plain,application/json" hidden onChange={event => { const file = event.target.files?.[0]; if (file) importList.mutate(file); event.target.value = '' }} /><Button variant="secondary" onClick={() => fileRef.current?.click()}><FileUp size={18} /> Import</Button><Button onClick={() => setCreateOpen(true)}><Plus size={18} /> New list</Button></div></div>
    {(create.error || importList.error || patchList.error || shuffle.error || remove.error) && <ErrorNotice error={create.error || importList.error || patchList.error || shuffle.error || remove.error} />}
    {!lists.data.length ? <Empty title="Create your first word list" detail="Add words manually or import a Vocab Collect JSON or text file." action={<Button onClick={() => setCreateOpen(true)}><Plus size={18} /> New list</Button>} /> : <div className="list-grid">{lists.data.map(item => <Panel key={item.id} className="list-card" ><button className="list-card-main" onClick={() => setSelectedId(item.id)}><div className="list-symbol"><BookOpen size={22} /></div><div><div className="list-card-title"><h3>{item.name}</h3>{item.is_active ? <Tag tone="green">Active</Tag> : <Tag>Paused</Tag>}</div><p>{item.word_count} words{item.unavailable_count ? ` · ${item.unavailable_count} unavailable` : ''}</p><span>{item.direction === 'bidirectional' ? 'Bidirectional' : 'Word → meaning'}</span></div></button><div className="list-card-actions"><button onClick={() => patchList.mutate({ id: item.id, body: { is_active: !item.is_active } })}>{item.is_active ? 'Deactivate' : 'Activate'}</button><IconButton label="Open list" onClick={() => setSelectedId(item.id)}><MoreHorizontal size={19} /></IconButton></div></Panel>)}</div>}
    {createOpen && <Modal title="New word list" onClose={() => setCreateOpen(false)}><form className="modal-form" onSubmit={event => { event.preventDefault(); create.mutate() }}><label className="field"><span>Name</span><input autoFocus value={name} onChange={event => setName(event.target.value)} required maxLength={120} placeholder="Academic vocabulary" /></label><label className="field"><span>Direction</span><select value={direction} onChange={event => setDirection(event.target.value as ListDirection)}><option value="w2m">Word → meaning</option><option value="bidirectional">Bidirectional</option></select><small>Reverse cards unlock after forward recall is established.</small></label>{create.error && <ErrorNotice error={create.error} />}<div className="modal-actions"><Button type="button" variant="ghost" onClick={() => setCreateOpen(false)}>Cancel</Button><Button type="submit" disabled={create.isPending}>Create list</Button></div></form></Modal>}
    {selectedId && <Modal className="word-list-dialog" title={selected.data?.name || 'Word list'} onClose={() => setSelectedId(null)}>{selected.isLoading ? <Loading /> : selected.error || !selected.data ? <ErrorNotice error={selected.error} /> : <ListDetail list={selected.data} refresh={refresh} onPatch={body => patchList.mutate({ id: selected.data!.id, body })} onShuffle={() => shuffle.mutate(selected.data!.id)} onDelete={() => { if (window.confirm(`Delete “${selected.data!.name}”? Your study progress will be kept.`)) remove.mutate(selected.data!.id) }} />}</Modal>}
  </section>
}

function ListDetail({ list, refresh, onPatch, onShuffle, onDelete }: { list: WordList; refresh: () => void; onPatch: (body: object) => void; onShuffle: () => void; onDelete: () => void }) {
  const [word, setWord] = useState('')
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(list.name)
  const add = useMutation({ mutationFn: () => api(`/lists/${list.id}/entries`, json('POST', { word })), onSuccess: () => { setWord(''); refresh() } })
  const removeEntry = useMutation({ mutationFn: (entryId: number) => api(`/lists/${list.id}/entries/${entryId}`, { method: 'DELETE' }), onSuccess: refresh })
  return <div className="list-detail">
    <div className="list-detail-body" role="region" aria-label="Word list contents" tabIndex={0}>
    <div className="list-detail-meta"><button className={`toggle ${list.is_active ? 'on' : ''}`} onClick={() => onPatch({ is_active: !list.is_active })} aria-pressed={list.is_active}><span /></button><span>{list.is_active ? 'Active in study sessions' : 'Not used for study'}</span><Tag tone="blue">{list.direction === 'bidirectional' ? 'Bidirectional' : 'Forward only'}</Tag></div>
    {renaming ? <form className="inline-form" onSubmit={event => { event.preventDefault(); onPatch({ name }); setRenaming(false) }}><input value={name} onChange={event => setName(event.target.value)} /><Button type="submit"><Check size={18} /> Save</Button><IconButton type="button" label="Cancel" onClick={() => setRenaming(false)}><X size={18} /></IconButton></form> : <button className="text-button" onClick={() => setRenaming(true)}>Rename list</button>}
    <form className="inline-form" onSubmit={event => { event.preventDefault(); if (word.trim()) add.mutate() }}><input value={word} onChange={event => setWord(event.target.value)} placeholder="Add a word" maxLength={240} /><Button type="submit" disabled={!word.trim() || add.isPending}><Plus size={18} /> Add</Button></form>
    {(add.error || removeEntry.error) && <ErrorNotice error={add.error || removeEntry.error} />}
    <div className="entry-list">{list.entries?.length ? list.entries.map((entry, index) => <div key={entry.id} className="entry-row"><span className="entry-number">{index + 1}</span><strong>{entry.word}</strong>{!entry.has_definition && <Tag tone="amber">Definition unavailable</Tag>}<IconButton label={`Remove ${entry.word}`} onClick={() => removeEntry.mutate(entry.id)}><X size={17} /></IconButton></div>) : <Empty title="This list is empty" detail="Add a word above to begin collecting." />}</div>
    </div>
    <footer className="detail-footer"><div><Button variant="secondary" onClick={onShuffle}><Shuffle size={17} /> Shuffle</Button><a className="button button--secondary" href={downloadUrl(`/lists/${list.id}/export?format=json`)}><Download size={17} /> JSON</a><a className="button button--secondary" href={downloadUrl(`/lists/${list.id}/export?format=txt`)}><Download size={17} /> Text</a></div><Button variant="danger" onClick={onDelete}><Trash2 size={17} /> Delete list</Button></footer>
  </div>
}

function LearnedView() {
  const client = useQueryClient()
  const [q, setQ] = useState('')
  const [filters, setFilters] = useState<LearnedFilters>(defaultLearnedFilters)
  const [filterOpen, setFilterOpen] = useState(false)
  const [filterPlacement, setFilterPlacement] = useState({ above: false, maxHeight: 520 })
  const filterRoot = useRef<HTMLDivElement>(null)
  const query = useQuery({ queryKey: ['learned', q], queryFn: () => api<LearnedWord[]>(`/words/learned?q=${encodeURIComponent(q)}`) })
  const status = useMutation({ mutationFn: ({ word, value }: { word: string; value: LearnedWord['status'] }) => api(`/words/${encodeURIComponent(word)}/status`, json('PUT', { status: value })), onSuccess: () => { client.invalidateQueries({ queryKey: ['learned'] }); client.invalidateQueries({ queryKey: ['study-overview'] }) } })
  useEffect(() => {
    if (!filterOpen) return
    const placeFilter = () => {
      const bounds = filterRoot.current?.getBoundingClientRect()
      if (!bounds) return
      const below = window.innerHeight - bounds.bottom - (window.innerWidth <= 650 ? 98 : 26)
      const above = bounds.top - 26
      const placeAbove = below < 240 && above > below
      setFilterPlacement({ above: placeAbove, maxHeight: Math.max(140, Math.min(520, placeAbove ? above : below)) })
    }
    placeFilter()
    filterRoot.current?.querySelector<HTMLInputElement>('.learned-filter-popover input')?.focus()
    const closeOutside = (event: PointerEvent | FocusEvent) => {
      if (event.target instanceof Node && !filterRoot.current?.contains(event.target)) setFilterOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setFilterOpen(false); filterRoot.current?.querySelector<HTMLButtonElement>('.learned-filter-button')?.focus() }
    }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('focusin', closeOutside)
    document.addEventListener('keydown', closeOnEscape)
    window.addEventListener('resize', placeFilter)
    window.addEventListener('scroll', placeFilter, { passive: true })
    return () => {
      document.removeEventListener('pointerdown', closeOutside)
      document.removeEventListener('focusin', closeOutside)
      document.removeEventListener('keydown', closeOnEscape)
      window.removeEventListener('resize', placeFilter)
      window.removeEventListener('scroll', placeFilter)
    }
  }, [filterOpen])
  if (query.isLoading) return <Loading label="Loading learned words" />
  if (query.error || !query.data) return <ErrorNotice error={query.error} />
  const activeFilterCount = Object.values(filters).filter(value => value !== 'all').length
  const visible = query.data.filter(item => {
    const forward = item.cards.some(card => card.direction === 'w2m')
    const reverse = item.cards.some(card => card.direction === 'm2w')
    return (filters.status === 'all' || item.status === filters.status) &&
      (filters.direction === 'all' || (filters.direction === 'uni' ? forward && !reverse : forward && reverse)) &&
      (filters.stage === 'all' || item.cards.some(card => card.state === Number(filters.stage)))
  })

  return <section className="collection-section">
    <div className="learned-toolbar">
      <div className="search-field"><Search size={19} /><input aria-label="Search learned words" value={q} onChange={event => setQ(event.target.value)} placeholder="Search learned words" /></div>
      <div className="learned-filter-wrap" ref={filterRoot}>
        <Button variant="secondary" className={`learned-filter-button ${activeFilterCount ? 'is-active' : ''}`} aria-expanded={filterOpen} aria-controls={filterOpen ? 'learned-word-filters' : undefined} onClick={() => setFilterOpen(open => !open)}><SlidersHorizontal size={18} /> Filters{activeFilterCount > 0 && <span className="learned-filter-count">{activeFilterCount}</span>}<ChevronDown size={16} className={filterOpen ? 'filter-chevron-open' : ''} /></Button>
        {filterOpen && <div id="learned-word-filters" className={`learned-filter-popover ${filterPlacement.above ? 'above' : ''}`} style={{ maxHeight: filterPlacement.maxHeight }} role="region" aria-label="Learned word filters">
          <div className="learned-filter-head"><div><strong>Refine words</strong><span>{visible.length} of {query.data.length} shown</span></div><IconButton label="Close filters" onClick={() => setFilterOpen(false)}><X size={18} /></IconButton></div>
          <FilterOptions label="Word status" value={filters.status} options={[{ value: 'all', label: 'All' }, { value: 'active', label: 'Active' }, { value: 'familiar', label: 'Familiar' }, { value: 'useless', label: 'Useless' }]} onChange={value => setFilters(current => ({ ...current, status: value }))} />
          <FilterOptions label="Recall directions" hint="Uni: word → meaning · Bi: both ways" value={filters.direction} options={[{ value: 'all', label: 'All' }, { value: 'uni', label: 'Uni direction' }, { value: 'bi', label: 'Bi direction' }]} onChange={value => setFilters(current => ({ ...current, direction: value }))} />
          <FilterOptions label="Card stage" value={filters.stage} options={[{ value: 'all', label: 'All' }, { value: '0', label: 'New' }, { value: '1', label: 'Learning' }, { value: '2', label: 'Review' }, { value: '3', label: 'Relearning' }]} onChange={value => setFilters(current => ({ ...current, stage: value }))} />
          <div className="learned-filter-foot"><button type="button" className="text-button" disabled={!activeFilterCount} onClick={() => setFilters(defaultLearnedFilters)}>Clear all</button><Button type="button" onClick={() => setFilterOpen(false)}>Done</Button></div>
        </div>}
      </div>
    </div>
    {status.error && <ErrorNotice error={status.error} />}
    {!visible.length ? <Empty title={q || activeFilterCount ? 'No matching words' : 'No learned words yet'} detail={q || activeFilterCount ? 'Try another search or clear your filters.' : 'Words appear here once a study card is created.'} /> : <Panel className="table-panel"><div className="data-table">{visible.map(item => <div className="data-row" key={item.normalized_word}><div><strong>{item.word}</strong><span>{item.cards.length} card{item.cards.length > 1 ? 's' : ''}</span></div><select aria-label={`Status for ${item.word}`} value={item.status} onChange={event => status.mutate({ word: item.word, value: event.target.value as LearnedWord['status'] })}><option value="active">Active</option><option value="familiar">Familiar</option><option value="useless">Useless</option></select></div>)}</div></Panel>}
  </section>
}

function FilterOptions<T extends string>({ label, hint, value, options, onChange }: { label: string; hint?: string; value: T; options: { value: T; label: string }[]; onChange: (value: T) => void }) {
  return <fieldset className="learned-filter-group"><legend>{label}</legend><div className="learned-filter-options">{options.map(option => <label key={option.value} className={`learned-filter-option ${value === option.value ? 'selected' : ''}`}><input type="radio" name={label} value={option.value} checked={value === option.value} onChange={() => onChange(option.value)} /><span>{option.label}</span></label>)}</div>{hint && <p className="learned-filter-hint">{hint}</p>}</fieldset>
}

function NotesView() {
  const client = useQueryClient()
  const [q, setQ] = useState('')
  const query = useQuery({ queryKey: ['notes', q], queryFn: () => api<Note[]>(`/notes?q=${encodeURIComponent(q)}`) })
  const remove = useMutation({ mutationFn: (word: string) => api(`/words/${encodeURIComponent(word)}/note`, { method: 'DELETE' }), onSuccess: () => client.invalidateQueries({ queryKey: ['notes'] }) })
  const filtered = useMemo(() => query.data || [], [query.data])
  if (query.isLoading) return <Loading label="Loading notes" />
  if (query.error) return <ErrorNotice error={query.error} />
  return <section className="collection-section"><div className="search-field"><Search size={19} /><input value={q} onChange={event => setQ(event.target.value)} placeholder="Search notes" /></div>{remove.error && <ErrorNotice error={remove.error} />}{!filtered.length ? <Empty title="No notes yet" detail="Attach a note from any dictionary entry and it will appear here." /> : <div className="notes-grid">{filtered.map(note => <Panel className="note-card" key={note.normalized_word}><div><Tag tone="blue">{note.word}</Tag><IconButton label={`Delete note for ${note.word}`} onClick={() => remove.mutate(note.word)}><Trash2 size={17} /></IconButton></div><p>{note.body}</p><small>Updated {new Date(note.updated_at).toLocaleDateString()}</small></Panel>)}</div>}</section>
}

