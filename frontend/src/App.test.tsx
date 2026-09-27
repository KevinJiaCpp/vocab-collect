import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App'

const user = { id: 1, username: 'Reader', created_at: '2026-01-01T00:00:00Z' }

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

function mount(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
}

afterEach(() => vi.restoreAllMocks())

it('protects private routes and provides separate sign-in and registration screens', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).endsWith('/auth/me')) return json({ detail: 'Authentication required' }, 401)
    return json(user)
  })
  vi.stubGlobal('fetch', fetchMock)
  mount('/dashboard')
  expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'New here? Create an account' }))
  expect(await screen.findByRole('heading', { name: 'Create your account' })).toBeInTheDocument()
  expect(screen.getByLabelText('Password')).toHaveAttribute('minlength', '10')
})

it('requires reveal before keyboard grading and completes a study card', async () => {
  const prompt = { session: { id: 1, kind: 'learning', direction: 'w2m', target_count: 1, pool_size: 1, completed_count: 0, status: 'active' }, presentation_token: 'once', revealed: false, item: { card_id: 1, direction: 'w2m', prompt: { word: 'Lucid' } } }
  const answer = { ...prompt, revealed: true, item: { ...prompt.item, answer: { word: 'Lucid', normalized_word: 'lucid', senses: [{ part_of_speech: 'adjective', definition: 'Clearly expressed', examples: [], synonyms: [], antonyms: [], derivatives: [] }], pronunciations: [], morphology: null, attribution: 'Test' } } }
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path.endsWith('/auth/me')) return json(user)
    if (path.endsWith('/next')) return json(prompt)
    if (path.endsWith('/reveal')) return json(answer)
    if (path.endsWith('/answer')) return json({ session: { ...prompt.session, completed_count: 1, status: 'completed' } })
    return json({})
  })
  vi.stubGlobal('fetch', fetchMock)
  mount('/study/1')
  expect(await screen.findByRole('heading', { name: 'Lucid' })).toBeInTheDocument()
  fireEvent.keyDown(window, { key: '4', code: 'Digit4' })
  expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith('/answer'))).toBe(false)
  fireEvent.keyDown(window, { key: ' ', code: 'Space' })
  expect(await screen.findByText('Clearly expressed')).toBeInTheDocument()
  fireEvent.keyDown(window, { key: '4', code: 'Digit4' })
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Nice work.' })).toBeInTheDocument())
})

it('saves the dictionary multiword-expression preference', async () => {
  const settings = { learn_batch_size: 10, review_batch_size: 20, pool_multiplier: 1.5, exclude_multiword_expressions: false }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/auth/me')) return json(user)
    if (path.endsWith('/study/overview')) return json({ due: { w2m: 0, m2w: 0 }, new: { w2m: 0, m2w: 0 }, settings, active_session: null })
    if (path.endsWith('/settings') && init?.method === 'PUT') return json(JSON.parse(String(init.body)))
    return json({})
  })
  vi.stubGlobal('fetch', fetchMock)
  mount('/')
  fireEvent.click(await screen.findByRole('button', { name: 'Study settings' }))
  fireEvent.click(screen.getByRole('checkbox', { name: /Hide multiword expressions/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  await waitFor(() => {
    const request = fetchMock.mock.calls.find(([path, init]) => String(path).endsWith('/settings') && init?.method === 'PUT')
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({ exclude_multiword_expressions: true })
  })
})
