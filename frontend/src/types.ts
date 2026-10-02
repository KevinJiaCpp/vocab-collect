import type { components } from './api.generated'

export type User = { id: number; username: string; created_at: string }
export type Direction = components['schemas']['StudyStartInput']['direction']
export type ListDirection = components['schemas']['WordListInput']['direction']
export type WordListEntry = { id: number; word: string; normalized_word: string; position: number; has_definition: boolean }
export type WordList = {
  id: number
  name: string
  direction: ListDirection
  is_active: boolean
  word_count: number
  unavailable_count: number
  entries?: WordListEntry[]
}
export type WordListMembership = { id: number; name: string; contains: boolean; entry_id: number | null }
export type Sense = {
  part_of_speech: string
  definition: string
  examples: string[]
  generated_examples?: string[]
  synonyms: string[]
  antonyms: string[]
  derivatives: string[]
}
export type DictionaryEntry = {
  word: string
  normalized_word: string
  senses: Sense[]
  pronunciations: string[]
  morphology: null | { seg?: string; prefixes?: string[]; roots?: string[]; suffixes?: string[] }
  attribution: string
  note?: string
}
export type SessionSummary = {
  id: number
  kind: 'learning' | 'review'
  direction: Direction
  target_count: number
  pool_size: number
  completed_count: number
  status: 'active' | 'completed' | 'abandoned'
}
export type Overview = {
  due: Record<Direction, number>
  new: Record<Direction, number>
  settings: { learn_batch_size: number; review_batch_size: number; pool_multiplier: number; exclude_multiword_expressions: boolean }
  active_sessions: SessionSummary[]
}
