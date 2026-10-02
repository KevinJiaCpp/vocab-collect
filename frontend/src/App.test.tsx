import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

afterEach(() => { cleanup(); vi.restoreAllMocks() })

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

it.each([
  ['learning', 'w2m'], ['review', 'w2m'], ['learning', 'm2w'], ['review', 'm2w'],
] as const)('resumes %s %s through the normal Home action', async (kind, direction) => {
  const session = { id: 1, kind, direction, target_count: 2, pool_size: 2, completed_count: 0, status: 'active' }
  const prompt = { session, presentation_token: 'saved-card', revealed: false, item: { card_id: 1, direction, prompt: { word: 'Lucid' } } }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/auth/me')) return json(user)
    if (path.endsWith('/next')) return json(prompt)
    if (path.endsWith('/study/overview')) return json({ due: { w2m: 0, m2w: 0 }, new: { w2m: 0, m2w: 0 }, settings: { learn_batch_size: 10, review_batch_size: 20, pool_multiplier: 1.5, exclude_multiword_expressions: false }, active_sessions: [session] })
    if (path.endsWith('/study/sessions') && init?.method === 'POST') return json(session)
    return json({})
  })
  vi.stubGlobal('fetch', fetchMock)
  mount('/study/1')
  expect(await screen.findByRole('heading', { name: 'Lucid' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Exit' }))
  expect(await screen.findByRole('heading', { name: 'Ready when you are' })).toBeInTheDocument()
  expect(screen.queryByRole('dialog', { name: 'Leave this session?' })).not.toBeInTheDocument()
  expect(screen.queryByText('In progress')).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith('/abandon'))).toBe(false)
  if (direction === 'm2w') fireEvent.click(screen.getByRole('button', { name: 'Meaning → word' }))
  fireEvent.click(screen.getByRole('button', { name: kind === 'review' ? 'Review' : 'Learn' }))
  await waitFor(() => {
    const request = fetchMock.mock.calls.find(([path, init]) => String(path).endsWith('/study/sessions') && init?.method === 'POST')
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({ kind, direction })
  })
  expect(await screen.findByRole('heading', { name: 'Lucid' })).toBeInTheDocument()
})

it('collects a word into a list and removes it again', async () => {
  const entry = { word: 'Lucid', normalized_word: 'lucid', senses: [], pronunciations: [], morphology: null, attribution: 'Test' }
  let contains = false
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/auth/me')) return json(user)
    if (path.includes('/dictionary/search')) return json({ items: [{ word: 'Lucid', match: 'exact' }], page: 1, has_more: false })
    if (path.endsWith('/dictionary/Lucid')) return json(entry)
    if (path.endsWith('/words/Lucid/lists')) return json([{ id: 7, name: 'Favourites', contains, entry_id: contains ? 1 : null }])
    if (path.includes('/lists/7/entries')) {
      if (init?.method === 'DELETE') { contains = false; return new Response(null, { status: 204 }) }
      contains = true
      return json({ id: 1, word: 'Lucid', normalized_word: 'lucid', position: 0, has_definition: true }, 201)
    }
    return json({})
  })
  vi.stubGlobal('fetch', fetchMock)
  mount('/dictionary/Lucid')
  fireEvent.click(await screen.findByRole('button', { name: /Collect/ }))
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Favourites' }))
  await waitFor(() => expect(fetchMock.mock.calls.some(([path, init]) => String(path).endsWith('/lists/7/entries') && init?.method === 'POST')).toBe(true))
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Favourites' })).toBeChecked())
  fireEvent.click(screen.getByRole('checkbox', { name: 'Favourites' }))
  await waitFor(() => expect(fetchMock.mock.calls.some(([path, init]) => String(path).endsWith('/lists/7/entries/1') && init?.method === 'DELETE')).toBe(true))
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Favourites' })).not.toBeChecked())
})

it('filters learned words in a dropdown by status, recall directions, and stage', async () => {
  const words = [
    { word: 'Lucid', normalized_word: 'lucid', status: 'active', cards: [{ direction: 'w2m', state: 2, due: '' }, { direction: 'm2w', state: 1, due: '' }] },
    { word: 'Resilient', normalized_word: 'resilient', status: 'familiar', cards: [{ direction: 'w2m', state: 2, due: '' }] },
    { word: 'Swift', normalized_word: 'swift', status: 'active', cards: [{ direction: 'w2m', state: 0, due: '' }] },
    { word: 'Bold', normalized_word: 'bold', status: 'active', cards: [{ direction: 'w2m', state: 2, due: '' }, { direction: 'm2w', state: 2, due: '' }] },
  ]
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path.endsWith('/auth/me')) return json(user)
    if (path.endsWith('/lists')) return json([])
    if (path.includes('/words/learned')) {
      const q = new URL(path, 'http://localhost').searchParams.get('q')?.toLowerCase() || ''
      return json(words.filter(item => item.normalized_word.includes(q)))
    }
    return json({})
  }))
  mount('/collection')
  fireEvent.click(await screen.findByRole('button', { name: 'Learned words' }))
  expect(await screen.findByText('Lucid')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: /^Filters/ }))
  let dropdown = screen.getByRole('region', { name: 'Learned word filters' })
  fireEvent.click(within(dropdown).getByRole('radio', { name: 'Familiar' }))
  expect(screen.getByText('Resilient')).toBeInTheDocument()
  expect(screen.queryByText('Lucid')).not.toBeInTheDocument()

  fireEvent.click(within(dropdown).getByRole('radio', { name: 'Active' }))
  fireEvent.click(within(dropdown).getByRole('radio', { name: 'Bi direction' }))
  expect(screen.getByText('Lucid')).toBeInTheDocument()
  expect(screen.getByText('Bold')).toBeInTheDocument()
  expect(screen.queryByText('Swift')).not.toBeInTheDocument()
  fireEvent.click(within(dropdown).getByRole('radio', { name: 'Learning' }))
  expect(screen.getByText('Lucid')).toBeInTheDocument()
  expect(screen.queryByText('Bold')).not.toBeInTheDocument()

  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('region', { name: 'Learned word filters' })).not.toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox', { name: 'Search learned words' }), { target: { value: 'bold' } })
  expect(await screen.findByText('No matching words')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /^Filters/ }))
  dropdown = screen.getByRole('region', { name: 'Learned word filters' })
  fireEvent.click(within(dropdown).getByRole('button', { name: 'Clear all' }))
  expect(await screen.findByText('Bold')).toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox', { name: 'Search learned words' }), { target: { value: '' } })
  fireEvent.click(within(dropdown).getByRole('radio', { name: 'Uni direction' }))
  expect(screen.getByText('Resilient')).toBeInTheDocument()
  expect(screen.getByText('Swift')).toBeInTheDocument()
  expect(screen.queryByText('Lucid')).not.toBeInTheDocument()
})

it('saves the dictionary multiword-expression preference', async () => {
  const settings = { learn_batch_size: 10, review_batch_size: 20, pool_multiplier: 1.5, exclude_multiword_expressions: false }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/auth/me')) return json(user)
    if (path.endsWith('/study/overview')) return json({ due: { w2m: 0, m2w: 0 }, new: { w2m: 0, m2w: 0 }, settings, active_sessions: [] })
    if (path.endsWith('/settings') && !init?.method) return json(settings)
    if (path.endsWith('/settings') && init?.method === 'PUT') return json(JSON.parse(String(init.body)))
    return json({})
  })
  vi.stubGlobal('fetch', fetchMock)
  mount('/')
  expect(await screen.findByRole('heading', { name: 'Ready when you are' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Study settings' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Licenses' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Settings' }))
  fireEvent.click(screen.getByRole('tab', { name: 'Study' }))
  expect(screen.getByRole('dialog', { name: 'Settings' })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'Study' })).toHaveAttribute('aria-selected', 'true')
  expect(await screen.findByRole('checkbox', { name: /Hide multiword expressions/ })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('checkbox', { name: /Hide multiword expressions/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await waitFor(() => {
    const request = fetchMock.mock.calls.find(([path, init]) => String(path).endsWith('/settings') && init?.method === 'PUT')
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({ exclude_multiword_expressions: true })
  })
})

it('generates, restores, regenerates and clears cached examples for the selected sense', async () => {
  const baseSense = { examples: [], generated_examples: [] as string[], synonyms: [], antonyms: [], derivatives: [] }
  const entry = { word: 'Light', normalized_word: 'light', pronunciations: [], morphology: null, attribution: 'Test dictionary', senses: [
    { ...baseSense, part_of_speech: 'noun', definition: 'Visible illumination', examples: ['The light filled the room.'] },
    { ...baseSense, part_of_speech: 'verb', definition: 'To illuminate' },
    { ...baseSense, part_of_speech: 'noun', definition: 'A source of illumination' },
  ] }
  const examples = ['The light above the door flickered.', 'Please switch off the light.', 'A small light stood beside the bed.']
  let respond: (value: Response) => void = () => {}
  const requests: number[] = []
  const clears: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/auth/me')) return json(user)
    if (path.endsWith('/examples') && init?.method === 'POST') {
      requests.push(JSON.parse(String(init.body)).sense_index)
      return new Promise<Response>(resolve => { respond = resolve })
    }
    if (path.endsWith('/examples/2') && init?.method === 'DELETE') {
      clears.push(path)
      return new Promise<Response>(resolve => { respond = resolve })
    }
    if (path.includes('/dictionary/search')) return json({ items: [{ word: 'Light', match: 'exact' }, { word: 'Lucid', match: 'fuzzy' }], page: 1, has_more: false })
    if (path.endsWith('/dictionary/Light')) return json(entry)
    if (path.endsWith('/dictionary/Lucid')) return json({ ...entry, word: 'Lucid', normalized_word: 'lucid', senses: [{ ...baseSense, part_of_speech: 'adjective', definition: 'Clearly expressed' }] })
    if (path.endsWith('/lists')) return json([])
    return json({})
  }))
  mount('/dictionary/Light')
  const definition = await screen.findByText('A source of illumination')
  const sense = within(definition.closest('li')!)
  sense.getByRole('button', { name: 'Generate examples' }).focus()
  fireEvent.click(sense.getByRole('button', { name: 'Generate examples' }))
  expect(await sense.findByRole('button', { name: 'Generating…' })).toBeDisabled()
  expect(sense.getByRole('status')).toHaveTextContent('Generating example sentences')
  await waitFor(() => expect(requests).toEqual([2]))
  entry.senses[2].generated_examples = examples
  respond(json({ examples }))
  expect(await sense.findByRole('region', { name: 'Generated examples for sense 3' })).toHaveTextContent(examples[0])
  expect(screen.getByText('“The light filled the room.”')).toBeInTheDocument()
  expect(sense.getByText('AI-generated')).toBeInTheDocument()
  await waitFor(() => expect(sense.getByRole('button', { name: 'Regenerate' })).toHaveFocus())
  expect(screen.queryByText(/This view only/)).not.toBeInTheDocument()
  fireEvent.click(await sense.findByRole('button', { name: 'Regenerate' }))
  await waitFor(() => expect(requests).toEqual([2, 2]))
  respond(json({ detail: 'The LLM took too long to respond. Try again.' }, 504))
  expect(await sense.findByRole('alert')).toHaveTextContent('The LLM took too long')
  expect(sense.getByRole('region')).toHaveTextContent(examples[0])
  expect(await sense.findByRole('button', { name: 'Regenerate' })).toBeEnabled()
  fireEvent.click(await screen.findByRole('button', { name: 'Lucid fuzzy' }))
  expect(await screen.findByText('Clearly expressed')).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: /Generated examples/ })).not.toBeInTheDocument()
  fireEvent.click(await screen.findByRole('button', { name: 'Light exact' }))
  expect(await screen.findByText('A source of illumination')).toBeInTheDocument()
  expect(await screen.findByRole('region', { name: 'Generated examples for sense 3' })).toHaveTextContent(examples[0])
  expect(requests).toEqual([2, 2])
  cleanup()
  mount('/dictionary/Light')
  const restored = within((await screen.findByText('A source of illumination')).closest('li')!)
  expect(restored.getByRole('region')).toHaveTextContent(examples[0])
  restored.getByRole('button', { name: 'Clear' }).focus()
  fireEvent.click(restored.getByRole('button', { name: 'Clear' }))
  expect(await restored.findByRole('button', { name: 'Clearing…' })).toBeDisabled()
  expect(restored.getByRole('button', { name: 'Regenerate' })).toBeDisabled()
  await waitFor(() => expect(clears).toHaveLength(1))
  respond(json({ detail: 'Could not clear examples. Try again.' }, 500))
  expect(await restored.findByRole('alert')).toHaveTextContent('Could not clear')
  expect(restored.getByRole('region')).toHaveTextContent(examples[0])
  restored.getByRole('button', { name: 'Clear' }).focus()
  fireEvent.click(await restored.findByRole('button', { name: 'Clear' }))
  await waitFor(() => expect(clears).toHaveLength(2))
  entry.senses[2].generated_examples = []
  respond(new Response(null, { status: 204 }))
  await waitFor(() => expect(restored.queryByRole('region')).not.toBeInTheDocument())
  expect(restored.getByRole('button', { name: 'Generate examples' })).toHaveFocus()
  expect(screen.getByText('“The light filled the room.”')).toBeInTheDocument()
  cleanup()
  mount('/dictionary/Light')
  await screen.findByText('A source of illumination')
  expect(screen.queryByRole('region', { name: /Generated examples/ })).not.toBeInTheDocument()
  expect(requests).toEqual([2, 2])
  const reloaded = within(screen.getByText('A source of illumination').closest('li')!)
  reloaded.getByRole('button', { name: 'Generate examples' }).focus()
  fireEvent.click(reloaded.getByRole('button', { name: 'Generate examples' }))
  await waitFor(() => expect(requests).toEqual([2, 2, 2]))
  screen.getByRole('textbox', { name: 'Search dictionary' }).focus()
  respond(json({ examples }))
  await reloaded.findByRole('region')
  expect(screen.getByRole('textbox', { name: 'Search dictionary' })).toHaveFocus()
})

it('saves LLM settings, reopens them, and preserves or removes the saved key', async () => {
  let config = { base_url: 'https://api.openai.com/v1', model: '', has_api_key: false }
  const requests: { base_url: string; model: string; api_key: string | null }[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/auth/me')) return json(user)
    if (path.endsWith('/settings/llm')) {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body))
        requests.push(body)
        config = { base_url: body.base_url, model: body.model, has_api_key: body.api_key === null ? config.has_api_key : Boolean(body.api_key) }
      }
      return json(config)
    }
    return json({ text: '' })
  }))
  mount('/licenses')
  fireEvent.click(await screen.findByRole('button', { name: 'Settings' }))
  fireEvent.click(screen.getByRole('tab', { name: 'LLM' }))
  expect(await screen.findByLabelText('Model')).toHaveValue('')
  expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('API base URL'), { target: { value: 'http://localhost:11434/v1' } })
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'local-model' } })
  const key = screen.getByLabelText(/API key Optional/)
  expect(key).toHaveAttribute('type', 'password')
  fireEvent.change(key, { target: { value: 'test-secret' } })
  fireEvent.click(screen.getByRole('button', { name: 'Show API key' }))
  expect(key).toHaveAttribute('type', 'text')
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  expect(await screen.findByText('LLM settings saved.')).toBeInTheDocument()
  expect(requests[0]).toEqual({ base_url: 'http://localhost:11434/v1', model: 'local-model', api_key: 'test-secret' })
  expect(key).toHaveValue('')
  expect(key).toHaveAttribute('type', 'password')
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  fireEvent.click(screen.getByRole('button', { name: 'Settings' }))
  fireEvent.click(screen.getByRole('tab', { name: 'LLM' }))
  expect(await screen.findByLabelText('Model')).toHaveValue('local-model')
  expect(screen.getByLabelText(/API key Optional/)).toHaveValue('')
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'another-model' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  expect(await screen.findByText('LLM settings saved.')).toBeInTheDocument()
  expect(requests[1].api_key).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Remove saved key' }))
  expect(screen.getByText('Your saved key will be removed when you save.')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  expect(await screen.findByText('LLM settings saved.')).toBeInTheDocument()
  expect(requests[2].api_key).toBe('')
  expect(screen.queryByRole('button', { name: 'Remove saved key' })).not.toBeInTheDocument()
})

it('keeps the LLM draft when saving fails', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/auth/me')) return json(user)
    if (path.endsWith('/settings/llm')) return init?.method === 'PUT' ? json({ detail: 'Could not save. Try again.' }, 500) : json({ base_url: 'https://api.openai.com/v1', model: '', has_api_key: false })
    return json({ text: '' })
  }))
  mount('/licenses')
  fireEvent.click(await screen.findByRole('button', { name: 'Settings' }))
  fireEvent.click(screen.getByRole('tab', { name: 'LLM' }))
  fireEvent.change(await screen.findByLabelText('Model'), { target: { value: 'local-model' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save. Try again.')
  expect(screen.getByLabelText('Model')).toHaveValue('local-model')
  expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled()
})

it('opens settings from the shell and applies the appearance choice', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/licenses') ? json({ text: '' }) : json(user)))
  mount('/licenses')
  fireEvent.click(await screen.findByRole('button', { name: 'Settings' }))
  expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('tab', { name: 'About' }))
  expect(screen.getByRole('link', { name: 'View notices' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('tab', { name: 'Appearance' }))
  fireEvent.click(screen.getByRole('radio', { name: /Dark/ }))
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(localStorage.getItem('vocab-theme')).toBe('dark')
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(screen.queryByRole('dialog', { name: 'Settings' })).not.toBeInTheDocument()
  localStorage.removeItem('vocab-theme')
  document.documentElement.removeAttribute('data-theme')
})
