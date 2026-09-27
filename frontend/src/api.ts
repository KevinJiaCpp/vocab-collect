export class ApiError extends Error {
  status: number
  data: unknown
  constructor(status: number, message: string, data: unknown) {
    super(message)
    this.status = status
    this.data = data
  }
}

async function parseResponse(response: Response) {
  if (response.status === 204) return null
  const type = response.headers.get('content-type') || ''
  return type.includes('application/json') ? response.json() : response.text()
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(`/api${path}`, { ...init, headers, credentials: 'include' })
  const data = await parseResponse(response)
  if (!response.ok) {
    const detail = typeof data === 'object' && data && 'detail' in data ? (data as { detail: unknown }).detail : data
    const message = typeof detail === 'string' ? detail : typeof detail === 'object' && detail && 'message' in detail ? String((detail as { message: unknown }).message) : `Request failed (${response.status})`
    throw new ApiError(response.status, message, data)
  }
  return data as T
}

export const json = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
})

export function downloadUrl(path: string) {
  return `/api${path}`
}

