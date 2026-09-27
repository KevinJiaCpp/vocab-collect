import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { ErrorNotice, Loading, PageHeader, Panel } from '../components'

export default function LicensesPage() {
  const query = useQuery({ queryKey: ['licenses'], queryFn: () => api<{ text: string }>('/licenses') })
  if (query.isLoading) return <Loading label="Loading notices" />
  if (query.error || !query.data) return <ErrorNotice error={query.error} />
  return <div className="page"><PageHeader eyebrow="About" title="Licenses & attribution" /><Panel><pre className="license-text">{query.data.text}</pre></Panel></div>
}

