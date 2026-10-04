import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from './App'
import type { DictionaryEntry, ListNote, WordList } from './types'

const user = { id: 1, username: 'Reader', created_at: '2026-01-01T00:00:00Z' }
const words = [
  { id: 11, word: 'Lucid', normalized_word: 'lucid', position: 0, has_definition: true },
  { id: 12, word: 'Clear', normalized_word: 'clear', position: 1, has_definition: true },
  { id: 13, word: 'Bright', normalized_word: 'bright', position: 2, has_definition: true },
]
const list: WordList = { id: 7, name: 'Favourites', direction: 'w2m', is_active: true, word_count: 3, unavailable_count: 0, entries: words }
const otherList: WordList = { ...list, id: 9, name: 'Reading', entries: [] }
const sharedNote: ListNote = { id: 31, word_list_id: 7, list_name: list.name, body: 'Lucid and clear both suggest easy understanding.', words: [{ ...words[0], word: 'LUCID' }, words[1]], updated_at: '2026-10-03T00:00:00Z' }
const secondNote: ListNote = { ...sharedNote, id: 32, body: 'Think of a lucid explanation as one with no confusion.', words: [words[0]] }
const entry: DictionaryEntry = {
  word: 'Lucid', normalized_word: 'lucid', pronunciations: [], morphology: null, attribution: 'Test dictionary',
  senses: [{ part_of_speech: 'adjective', definition: 'Clearly expressed and easily understood', examples: [], synonyms: [], antonyms: [], derivatives: [] }],
  notes: [sharedNote, secondNote],
}
const clients: QueryClient[] = []
const originalScroll = HTMLElement.prototype.scrollIntoView

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

function mount(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
  clients.push(client)
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
}

function mockApi(handler: (path: string, init?: RequestInit) => Response | undefined = () => undefined) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/auth/me')) return json(user)
    const response = handler(path, init)
    if (response) return response
    if (path.includes('/dictionary/search')) return json({ items: [{ word: 'Lucid', match: 'exact' }], page: 1, has_more: false })
    if (path.endsWith('/dictionary/Lucid')) return json(entry)
    if (path.endsWith('/words/Lucid/lists')) return json([{ id: 7, name: list.name, contains: true, entry_id: 11 }])
    if (path.endsWith('/lists')) return json([list, otherList])
    if (path.endsWith('/lists/7')) return json(list)
    if (path.endsWith('/lists/9')) return json(otherList)
    if (path.startsWith('/api/notes?')) return json([sharedNote])
    throw new Error(`Unexpected request: ${init?.method || 'GET'} ${path}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, writable: true, value: vi.fn() })
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })))
})

afterEach(() => {
  cleanup()
  clients.splice(0).forEach(client => client.clear())
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, writable: true, value: originalScroll })
})

it('shows multiple dictionary notes before definitions and excludes the current word regardless of casing', async () => {
  mockApi()
  mount('/dictionary/Lucid')
  await screen.findByText(sharedNote.body)
  const notes = screen.getByRole('region', { name: 'Your notes' })
  expect(within(notes).getByText(secondNote.body)).toBeInTheDocument()
  expect(notes.compareDocumentPosition(screen.getByText(entry.senses[0].definition)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(within(notes).getByRole('link', { name: 'Clear' })).toHaveAttribute('href', '/dictionary/Clear')
  expect(within(notes).queryByRole('link', { name: /^lucid$/i })).not.toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Note editor' }).compareDocumentPosition(screen.getByText(entry.senses[0].definition)) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
})

it('creates one list-owned note linked to several selected words', async () => {
  let notes: ListNote[] = []
  const fetchMock = mockApi((path, init) => {
    if (path.startsWith('/api/notes?')) return json(notes)
    if (path.endsWith('/lists/7/notes') && init?.method === 'POST') {
      const payload = JSON.parse(String(init.body))
      notes = [{ ...sharedNote, body: payload.body, words: words.filter(word => payload.entry_ids.includes(word.id)) }]
      return json(notes[0], 201)
    }
  })
  mount('/collection')
  fireEvent.click(await screen.findByRole('button', { name: 'Notes' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Add note' }))
  const dialog = within(screen.getByRole('dialog', { name: 'Add note' }))
  const explanation = await dialog.findByRole('textbox', { name: 'Explanation' })
  expect(dialog.getByRole('combobox', { name: 'Word list' })).toBeEnabled()
  fireEvent.change(explanation, { target: { value: 'Use these words for clear communication.' } })
  fireEvent.click(await dialog.findByRole('checkbox', { name: 'Lucid' }))
  fireEvent.click(dialog.getByRole('checkbox', { name: 'Clear' }))
  fireEvent.click(dialog.getByRole('button', { name: 'Add note' }))
  await waitFor(() => {
    const request = fetchMock.mock.calls.find(([path, init]) => String(path).endsWith('/lists/7/notes') && init?.method === 'POST')
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({ body: 'Use these words for clear communication.', entry_ids: [11, 12] })
  })
  expect(await screen.findByText('Use these words for clear communication.')).toBeInTheDocument()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('edits a shared note body and links while keeping its owning list fixed', async () => {
  let note = sharedNote
  const fetchMock = mockApi((path, init) => {
    if (path.startsWith('/api/notes?')) return json([note])
    if (path.endsWith('/notes/31') && init?.method === 'PUT') {
      const payload = JSON.parse(String(init.body))
      note = { ...note, body: payload.body, words: words.filter(word => payload.entry_ids.includes(word.id)) }
      return json(note)
    }
  })
  mount('/collection')
  fireEvent.click(await screen.findByRole('button', { name: 'Notes' }))
  const article = (await screen.findByText(sharedNote.body)).closest('article')!
  fireEvent.click(within(article).getByRole('button', { name: 'Edit' }))
  const dialog = within(screen.getByRole('dialog', { name: 'Edit note' }))
  const explanation = await dialog.findByRole('textbox', { name: 'Explanation' })
  expect(dialog.getByRole('combobox', { name: 'Word list' })).toBeDisabled()
  expect(dialog.getByRole('combobox', { name: 'Word list' })).toHaveValue('7')
  expect(explanation).toHaveValue(sharedNote.body)
  expect(await dialog.findByRole('checkbox', { name: 'Lucid' })).toBeChecked()
  expect(dialog.getByRole('checkbox', { name: 'Clear' })).toBeChecked()
  fireEvent.change(explanation, { target: { value: 'Lucid and bright can describe a clear mind.' } })
  fireEvent.click(dialog.getByRole('checkbox', { name: 'Clear' }))
  fireEvent.click(dialog.getByRole('checkbox', { name: 'Bright' }))
  fireEvent.click(dialog.getByRole('button', { name: 'Save changes' }))
  await waitFor(() => {
    const request = fetchMock.mock.calls.find(([path, init]) => String(path).endsWith('/notes/31') && init?.method === 'PUT')
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({ body: 'Lucid and bright can describe a clear mind.', entry_ids: [11, 13] })
  })
  expect(await screen.findByText('Lucid and bright can describe a clear mind.')).toBeInTheDocument()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it.each([
  ['learning', 'w2m'], ['review', 'w2m'], ['learning', 'm2w'], ['review', 'm2w'],
] as const)('shows notes only after revealing a %s %s card', async (kind, direction) => {
  const prompt = {
    session: { id: 1, kind, direction, target_count: 1, pool_size: 1, completed_count: 0, status: 'active' },
    presentation_token: 'card-token', revealed: false,
    item: { card_id: 1, direction, prompt: direction === 'w2m' ? { word: 'Lucid' } : { senses: entry.senses } },
  }
  mockApi((path, init) => {
    if (path.endsWith('/next')) return json(prompt)
    if (path.endsWith('/reveal') && init?.method === 'POST') return json({ ...prompt, revealed: true, item: { ...prompt.item, answer: entry } })
  })
  mount('/study/1')
  const reveal = await screen.findByRole('button', { name: /Reveal answer/ })
  expect(screen.queryByText(sharedNote.body)).not.toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Your notes' })).not.toBeInTheDocument()
  fireEvent.click(reveal)
  expect(await screen.findByText(sharedNote.body)).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Your notes' })).toHaveTextContent(secondNote.body)
})

it('scopes collection notes to a list and seeds that list for a new note without locking the chooser', async () => {
  const readingNote: ListNote = { ...secondNote, id: 33, word_list_id: 9, list_name: otherList.name, body: 'A reading note from a different word list.' }
  const fetchMock = mockApi(path => {
    if (path.startsWith('/api/notes?')) {
      const selected = new URL(path, 'http://localhost').searchParams.get('list_id')
      return json(selected === '9' ? [readingNote] : [sharedNote, readingNote])
    }
  })
  mount('/collection')
  fireEvent.click(await screen.findByRole('button', { name: 'Notes' }))
  await screen.findByText(sharedNote.body)
  fireEvent.change(screen.getByRole('combobox', { name: 'Filter notes by word list' }), { target: { value: '9' } })
  expect(await screen.findByText(readingNote.body)).toBeInTheDocument()
  await waitFor(() => expect(screen.queryByText(sharedNote.body)).not.toBeInTheDocument())
  expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/notes?') && new URL(String(path), 'http://localhost').searchParams.get('list_id') === '9')).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Add note' }))
  const dialog = within(screen.getByRole('dialog', { name: 'Add note' }))
  const chooser = await dialog.findByRole('combobox', { name: 'Word list' })
  expect(chooser).toHaveValue('9')
  expect(chooser).toBeEnabled()
  fireEvent.change(chooser, { target: { value: '7' } })
  expect(await dialog.findByRole('checkbox', { name: 'Lucid' })).toBeInTheDocument()
  expect(chooser).toHaveValue('7')
})

it('refreshes notes and uses the current entry id after uncollecting and recollecting a word', async () => {
  let entryId: number | null = 11
  let note = sharedNote
  const fetchMock = mockApi((path, init) => {
    if (path.endsWith('/dictionary/Lucid')) return json({ ...entry, notes: note.words.some(word => word.id === entryId) ? [note] : [] })
    if (path.endsWith('/words/Lucid/lists')) return json([{ id: 7, name: list.name, contains: entryId !== null, entry_id: entryId }])
    if (path.endsWith('/lists/7')) return json({ ...list, entries: [...(entryId === null ? [] : [{ ...words[0], id: entryId }]), words[1], words[2]] })
    if (path.endsWith('/lists/7/entries/11') && init?.method === 'DELETE') {
      entryId = null
      note = { ...note, words: [words[1]] }
      return new Response(null, { status: 204 })
    }
    if (path.endsWith('/lists/7/entries') && init?.method === 'POST') {
      entryId = 21
      return json({ ...words[0], id: entryId }, 201)
    }
    if (path.endsWith('/lists/7/notes') && init?.method === 'POST') return json({ ...secondNote, body: JSON.parse(String(init.body)).body }, 201)
  })
  mount('/dictionary/Lucid')
  await screen.findByText(sharedNote.body)
  fireEvent.click(screen.getByRole('button', { name: /Collect/ }))
  const membership = await screen.findByRole('checkbox', { name: list.name })
  fireEvent.click(membership)
  await waitFor(() => expect(screen.queryByText(sharedNote.body)).not.toBeInTheDocument())
  await waitFor(() => expect(membership).not.toBeChecked())
  fireEvent.click(membership)
  await waitFor(() => expect(membership).toBeChecked())
  const editor = within(screen.getByRole('region', { name: 'Note editor' }))
  await waitFor(() => expect(editor.getByRole('checkbox', { name: 'Lucid' })).toBeChecked())
  fireEvent.change(editor.getByRole('textbox', { name: 'Explanation' }), { target: { value: 'A note for the recollected word.' } })
  fireEvent.click(editor.getByRole('button', { name: 'Add note' }))
  await waitFor(() => {
    const request = fetchMock.mock.calls.find(([path, init]) => String(path).endsWith('/lists/7/notes') && init?.method === 'POST')
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({ body: 'A note for the recollected word.', entry_ids: [21] })
  })
})
