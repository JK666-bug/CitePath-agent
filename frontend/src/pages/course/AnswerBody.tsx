import type { ReactNode } from 'react'

export function plainAnswer(text: string) {
  return text
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
}

function renderInline(text: string, key: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|__[^_]+__)/g)
  return parts.map((part, index) => {
    if (
      (part.startsWith('**') && part.endsWith('**') && part.length > 4) ||
      (part.startsWith('__') && part.endsWith('__') && part.length > 4)
    ) {
      return (
        <strong key={`${key}-${index}`}>
          {part.slice(2, -2)}
        </strong>
      )
    }
    return <span key={`${key}-${index}`}>{part}</span>
  })
}

export default function AnswerBody({
  text,
}: {
  text: string
}) {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let list: string[] = []
  let paragraph: string[] = []

  function flushParagraph() {
    if (!paragraph.length) return
    const body = paragraph.join(' ').trim()
    paragraph = []
    if (!body) return
    blocks.push(
      <p key={`p-${blocks.length}`}>
        {renderInline(body, `p-${blocks.length}`)}
      </p>,
    )
  }

  function flushList() {
    if (!list.length) return
    const items = list
    list = []
    blocks.push(
      <ul key={`ul-${blocks.length}`}>
        {items.map((item, index) => (
          <li key={`li-${blocks.length}-${index}`}>
            {renderInline(item, `li-${blocks.length}-${index}`)}
          </li>
        ))}
      </ul>,
    )
  }

  for (const line of lines) {
    const bullet = line.match(/^\s*[-*+]\s+(.+)$/)
    if (bullet) {
      flushParagraph()
      list.push(bullet[1].trim())
      continue
    }
    if (!line.trim()) {
      flushList()
      flushParagraph()
      continue
    }
    flushList()
    paragraph.push(line.trim())
  }
  flushList()
  flushParagraph()

  if (!blocks.length) {
    return <div className="answer-text" />
  }

  return <div className="answer-text">{blocks}</div>
}
