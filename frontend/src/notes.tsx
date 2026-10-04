import { useEffect, useId, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Pencil, Plus, Search, StickyNote } from 'lucide-react'
import { api, json } from './api'
import { Button, ErrorNotice, Loading } from './components'
import type { ListNote, WordList, WordListMembership } from './types'

export function NoteExplanations({ notes, compact = false, onEdit, onAdd, normalizedWord }: {
  notes: ListNote[]
  compact?: boolean
  onEdit?: (note: ListNote) => void
  onAdd?: () => void
  normalizedWord?: string
}) {
  if (!notes.length) return null
  return <section className={`note-explanations ${compact ? 'note-explanations--compact' : ''}`} aria-label="Your notes">
    <header><div><StickyNote size={18} /><h3>Your notes</h3><span>{notes.length} {notes.length === 1 ? 'note' : 'notes'}</span></div>{onAdd && <button className="text-button" onClick={onAdd}>Add note</button>}</header>
    <div className="note-explanations-body" tabIndex={0} aria-label="Note explanations">{notes.map(note => <article className="note-explanation" key={note.id}>
      <div className="note-explanation-text"><p>{note.body}</p><div className="note-explanation-meta"><span>{note.list_name}</span>{!compact && <span>Updated {new Date(note.updated_at).toLocaleDateString()}</span>}</div>{note.words.length > 1 && <p className="note-related-words">Also linked to {note.words.filter(item => item.normalized_word !== normalizedWord).map((item, index) => <span key={item.id}>{index > 0 && ' · '}{compact ? item.word : <Link to={`/dictionary/${encodeURIComponent(item.word)}`}>{item.word}</Link>}</span>)}</p>}</div>
      {onEdit && <button className="note-edit-link" onClick={() => onEdit(note)} aria-label={`Edit note from ${note.list_name}`}><Pencil size={14} /><span>Edit</span></button>}
    </article>)}</div>
  </section>
}

export function NotesEditor({ word, listId, initialListId, editing, onSaved, onCancel }: {
  word?: string
  listId?: number
  initialListId?: number
  editing?: ListNote
  onSaved?: () => void
  onCancel?: () => void
}) {
  const client = useQueryClient()
  const id = useId()
  const [selectedList, setSelectedList] = useState<number | null>(editing?.word_list_id ?? listId ?? initialListId ?? null)
  const [body, setBody] = useState(editing?.body ?? '')
  const [entryIds, setEntryIds] = useState<number[]>(editing?.words.map(item => item.id) ?? [])
  const [search, setSearch] = useState('')
  const seededList = useRef<number | null>(editing?.word_list_id ?? null)
  const seededEntry = useRef<number | null>(null)
  const lists = useQuery({ queryKey: ['lists'], queryFn: () => api<WordList[]>('/lists') })
  const membership = useQuery({ queryKey: ['word-lists', word], queryFn: () => api<WordListMembership[]>(`/words/${encodeURIComponent(word!)}/lists`), enabled: !!word })
  const available = word ? (membership.data ?? []).filter(item => item.contains) : (lists.data ?? [])
  useEffect(() => {
    if (editing || listId || lists.isLoading || (word && membership.isLoading)) return
    if (selectedList === null || !available.some(item => item.id === selectedList)) {
      const nextList = available[0]?.id ?? null
      if (nextList !== selectedList) { setSelectedList(nextList); setEntryIds([]); seededList.current = null; seededEntry.current = null }
    }
  }, [available, selectedList, editing, listId, lists.isLoading, membership.isLoading, word])
  const list = useQuery({ queryKey: ['list', selectedList], queryFn: () => api<WordList>(`/lists/${selectedList}`), enabled: selectedList !== null })
  useEffect(() => {
    if (editing || selectedList === null || !list.data) return
    const current = membership.data?.find(item => item.id === selectedList)
    if (word) {
      if (!current?.entry_id || !list.data.entries?.some(item => item.id === current.entry_id) || seededEntry.current === current.entry_id) return
      setEntryIds(previous => [...new Set([...previous, current.entry_id!])])
      seededEntry.current = current.entry_id
    } else {
      if (seededList.current === selectedList) return
      setEntryIds([])
    }
    seededList.current = selectedList
  }, [editing, selectedList, list.data, membership.data, word])
  useEffect(() => {
    if (!list.data || list.data.id !== selectedList) return
    const valid = new Set(list.data.entries?.map(item => item.id))
    setEntryIds(previous => previous.every(value => valid.has(value)) ? previous : previous.filter(value => valid.has(value)))
  }, [list.data, selectedList])
  const save = useMutation({
    mutationFn: () => api<ListNote>(editing ? `/notes/${editing.id}` : `/lists/${selectedList}/notes`, json(editing ? 'PUT' : 'POST', { body, entry_ids: entryIds })),
    onSuccess: () => {
      for (const key of ['notes', 'lists', 'list', 'dictionary-entry', 'study-session']) client.invalidateQueries({ queryKey: [key] })
      if (!editing) { setBody(''); setEntryIds(word ? entryIds.filter(value => membership.data?.some(item => item.entry_id === value)) : []) }
      onSaved?.()
    },
  })
  const toggle = (entryId: number) => setEntryIds(previous => previous.includes(entryId) ? previous.filter(value => value !== entryId) : [...previous, entryId])
  if (lists.isLoading || (word && membership.isLoading)) return <Loading label="Opening note editor" />
  if (lists.error || membership.error) return <ErrorNotice error={lists.error || membership.error} />
  if (!available.length && !editing && !listId) return <div className="note-editor-empty"><p>{word ? `Collect “${word}” into a word list above to add an explanation.` : 'Create a word list before adding a note.'}</p><Link className="text-button" to="/collection">Open collection</Link></div>
  const entries = list.data?.entries ?? []
  const visible = entries.filter(item => item.word.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))
  return <form className="note-editor" onSubmit={event => { event.preventDefault(); if (body.trim() && selectedList !== null) save.mutate() }}>
    <div className="note-editor-fields">
      <div className="note-editor-writing">
        <label className="field" htmlFor={`${id}-list`}><span>Word list</span><select id={`${id}-list`} value={selectedList ?? ''} disabled={!!editing || !!listId || save.isPending} onChange={event => { setSelectedList(Number(event.target.value)); setEntryIds([]); setSearch(''); save.reset() }}><option value="" disabled>Select a word list</option>{available.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
        <label className="field" htmlFor={`${id}-body`}><span>Explanation</span><textarea id={`${id}-body`} value={body} onChange={event => { setBody(event.target.value); save.reset() }} rows={5} maxLength={20000} required placeholder="Write context, a mnemonic, or a connection…" disabled={save.isPending} /></label>
      </div>
      <fieldset className="note-word-picker" disabled={save.isPending || list.isLoading}>
        <legend>Link to words <span>{entryIds.length} selected</span></legend>
        {list.isLoading ? <Loading label="Loading list words" /> : list.error ? <ErrorNotice error={list.error} /> : !entries.length ? <p className="note-picker-hint">This list has no words yet. Your note can be linked later.</p> : <>
          <div className="search-field note-word-search"><Search size={16} /><input aria-label="Search words to link" placeholder="Find a word in this list" value={search} onChange={event => setSearch(event.target.value)} /></div>
          <div className="note-word-options">{visible.map(item => <label key={item.id}><input type="checkbox" checked={entryIds.includes(item.id)} onChange={() => toggle(item.id)} /><span>{item.word}</span></label>)}{!visible.length && <p className="note-picker-hint">No matching words in this list.</p>}</div>
          {!!entryIds.length && <p className="note-selected-words">{entries.filter(item => entryIds.includes(item.id)).map(item => item.word).join(' · ')}</p>}
        </>}
      </fieldset>
    </div>
    <div className="note-editor-footer"><p>{editing && editing.words.length > 1 ? 'Changes update this note for every linked word.' : 'One explanation can connect several words in this list.'}</p><div>{onCancel && <Button type="button" variant="ghost" onClick={onCancel} disabled={save.isPending}>Cancel</Button>}<Button type="submit" disabled={!body.trim() || selectedList === null || list.isLoading || !!list.error || save.isPending}>{!editing && <Plus size={17} />}{save.isPending ? 'Saving…' : editing ? 'Save changes' : 'Add note'}</Button></div></div>
    {save.error && <ErrorNotice error={save.error} />}{save.isSuccess && !editing && <p className="note-save-status" role="status">Note added.</p>}
  </form>
}
