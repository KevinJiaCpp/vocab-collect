import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff } from 'lucide-react'
import { api, json } from './api'
import type { components } from './api.generated'
import { Button, ErrorNotice, Field, IconButton, Loading } from './components'

type LLMSettings = components['schemas']['LLMSettingsOutput']

export default function LLMSettingsPanel({ userId }: { userId: number }) {
  const client = useQueryClient()
  const queryKey = ['llm-settings', userId]
  const query = useQuery({ queryKey, queryFn: () => api<LLMSettings>('/settings/llm') })
  const [draft, setDraft] = useState<{ base_url: string; model: string } | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [removeKey, setRemoveKey] = useState(false)
  useEffect(() => {
    if (query.data) setDraft(current => current ?? { base_url: query.data.base_url, model: query.data.model })
  }, [query.data])
  const save = useMutation({
    mutationFn: () => api<LLMSettings>('/settings/llm', json('PUT', {
      ...draft,
      api_key: removeKey ? '' : apiKey.trim() || null,
    })),
    onSuccess: data => {
      client.setQueryData(queryKey, data)
      setDraft({ base_url: data.base_url, model: data.model })
      setApiKey('')
      setShowKey(false)
      setRemoveKey(false)
    },
  })

  if (!draft || !query.data) return query.error ? <ErrorNotice error={query.error} /> : <Loading label="Loading LLM settings" />
  const changed = draft.base_url !== query.data.base_url || draft.model !== query.data.model || Boolean(apiKey.trim()) || removeKey
  return <form className="settings-form" onSubmit={event => { event.preventDefault(); save.mutate() }}>
    <div className="settings-section-heading"><h3>Your language model</h3><p>Configure an OpenAI-compatible service or a local model server.</p></div>
    <fieldset className="llm-fields" disabled={save.isPending}>
      <Field label="API base URL" type="url" required maxLength={2048} spellCheck={false} autoCapitalize="none" value={draft.base_url} onChange={event => setDraft({ ...draft, base_url: event.target.value })} hint="Include the API path, such as /v1, if your service requires it." />
      <Field label="Model" required maxLength={200} placeholder="Enter your model ID" spellCheck={false} autoCapitalize="none" value={draft.model} onChange={event => setDraft({ ...draft, model: event.target.value })} hint="Use the exact model ID provided by your service." />
      <div className="field">
        <label htmlFor="llm-api-key">API key <span className="llm-optional">Optional for local services</span></label>
        <div className="llm-key-input">
          <input id="llm-api-key" type={showKey ? 'text' : 'password'} value={apiKey} maxLength={4096} autoComplete="off" spellCheck={false} autoCapitalize="none" disabled={removeKey} aria-describedby="llm-key-hint" placeholder={query.data.has_api_key && !removeKey ? 'Leave blank to keep your saved key' : 'Enter an API key'} onChange={event => setApiKey(event.target.value)} />
          <IconButton type="button" label={showKey ? 'Hide API key' : 'Show API key'} disabled={removeKey || !apiKey} onClick={() => setShowKey(!showKey)}>{showKey ? <EyeOff size={18} /> : <Eye size={18} />}</IconButton>
        </div>
        <small id="llm-key-hint">{removeKey ? 'Your saved key will be removed when you save.' : query.data.has_api_key ? 'An API key is saved for your account.' : 'Leave blank if your service does not require a key.'}</small>
        {query.data.has_api_key && <button type="button" className="text-button llm-remove-key" onClick={() => { setRemoveKey(!removeKey); setApiKey(''); setShowKey(false) }}>{removeKey ? 'Keep saved key' : 'Remove saved key'}</button>}
      </div>
    </fieldset>
    <p className="settings-footnote">Saved to your account on this server. API keys are stored in the server database and are never sent back to the browser.</p>
    {save.error && <ErrorNotice error={save.error} />}
    {save.isSuccess && !changed && <p className="settings-saved" role="status">LLM settings saved.</p>}
    <div className="settings-actions"><Button type="submit" disabled={save.isPending || !changed || !draft.model.trim()}>{save.isPending ? 'Saving…' : 'Save changes'}</Button></div>
  </form>
}
