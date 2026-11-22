import type { Source } from './types'

export function sourcePageLabel(sources: Source[]) {
  const groups = new Map<number, { label: string; pages: Set<number> }>()
  for (const source of sources) {
    const group = groups.get(source.document_id) || { label: source.position ? `Doc ${source.position}` : source.filename, pages: new Set<number>() }
    group.pages.add(source.page_number); groups.set(source.document_id, group)
  }
  return [...groups.values()].map(group => {
    const pages = [...group.pages].sort((a, b) => a - b)
    const ranges: string[] = []
    for (let i = 0; i < pages.length; i++) {
      const start = pages[i]; let end = start
      while (i + 1 < pages.length && pages[i + 1] === end + 1) end = pages[++i]
      ranges.push(start === end ? `p. ${start}` : `p. ${start}–${end}`)
    }
    return `${group.label} · ${ranges.join(', ')}`
  }).join('  |  ')
}

export default function SourceSummary({ sources }: { sources: Source[] }) {
  const label = sourcePageLabel(sources)
  if (!label) return null
  return <p className="muted small">{label}</p>
}
