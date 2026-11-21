import { dateNumber, findDateMentions, resolveNoteDate } from './noteDateExpressions'
import type { DateMention, StudyWindow } from './noteDateExpressions'

const fromNote = Symbol('fromNote')

export type CalendarDate = {
  title: string
  date: string
  [fromNote]?: true
}

type TaskMention = { kind: 'task'; start: number; end: number; title: string }
type NoteToken = TaskMention | DateMention

const taskAliases: [string, string][] = [
  ['Final Project Presentation', 'final\\s+project\\s+presentations?'],
  ['Final Presentation', 'final\\s+presentations?|期末(?:展示|汇报|匯報|简报|簡報|演示)'],
  ['Group Presentation', 'group\\s+presentations?|小[组組](?:展示|汇报|匯報|简报|簡報|演示)'],
  ['Oral Presentation', 'oral\\s+presentations?|口[头頭](?:展示|汇报|匯報|简报|簡報|演示|報告|报告)'],
  ['Presentation', 'presentations?|展示|汇报|匯報|简报|簡報|演示'],
  ['Final Exam', 'final\\s+exam(?:inations?)?|期末(?:考试|考試|考)'],
  ['Midterm Exam', 'mid[- ]?term(?:\\s+exam(?:inations?)?)?|期中(?:考试|考試|考)'],
  ['Final Project', 'final\\s+project|(?:期末|最终|最終)(?:项目|項目|專案|专案|專題|专题)'],
  ['Project Proposal', '(?:project\\s+)?proposal|(?:项目|項目)?(?:提案|开题报告|開題報告)'],
  ['Office Hours', 'office\\s+hours?|(?:老师|老師)?答疑'],
  ['Review Session', 'review\\s+session|[复複]習課|复习课'],
  ['Group Meeting', 'group\\s+meeting|小[组組][会會][议議]'],
  ['Quiz', 'quiz(?:\\s*#?\\s*\\d+)?|小[测測](?:[验驗])?|随堂测验|隨堂測驗'],
  ['Lab Report', 'lab\\s+report|[实實][验驗][报報]告'],
  ['Lab', 'lab(?:\\s*#?\\s*\\d+)?|[实實][验驗](?:[课課])?'],
  ['Exam', 'exams?|examinations?|考试|考試'],
  ['Assignment', 'assignments?|homework|hw|problem\\s+sets?|作业|作業|功课|功課|[习習][题題]集'],
]

const number = '[0-9零〇一二两兩三四五六七八九十廿卅]{1,8}'
const numberedAssignment = `(?:\\b(?:assignment|homework|hw|problem\\s+set)\\s*#?\\s*(?<englishNumber>\\d+|[A-Z])\\b|(?:第\\s*)?(?<leadingNumber>${number})\\s*(?:次|号|號|份)?\\s*(?:作业|作業|功课|功課)|(?:作业|作業|功课|功課)\\s*#?\\s*(?<trailingNumber>${number}))`
const taskPattern = new RegExp([
  numberedAssignment,
  ...taskAliases.map(([, pattern], i) => {
    const alternatives = pattern.split('|').map(part => /^[a-z]/iu.test(part) ? `\\b(?:${part})\\b` : part)
    return `(?<task${i}>${alternatives.join('|')})`
  }),
].join('|'), 'giu')

const timePattern = /\b(?:at\s+)?(?:\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)|\d{1,2}:\d{2})\b|(?:凌晨|早上|上午|中午|下午|晚上)?\s*[0-9零〇一二两兩三四五六七八九十]{1,3}\s*(?:点|點|时|時)(?:半|[0-9零〇一二三四五六七八九十]{1,3}\s*分)?/giu
const weekdayNote = /[(（](?:(?:星期|周|週|礼拜|禮拜)[一二三四五六日天]|(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*)[)）]/giu
const dateIntro = /^(?:(?:on|by|before|due|deadline|date)(?:\s+(?:on|by))?|(?:我|我们|我們)?(?:会|會|将|將)?(?:在|于|於|到|截至|截止(?:到)?)?)\s*$/iu
const eventListJoin = /^(?:\s|[,、/&+]|\band\b|\bas well as\b|\balong with\b|和|跟|与|與|及|以及|还有|還有)+$/iu
const rangeJoin = /^(?:\s|[-–—~～])+$|^(?:to|through|until|至|到)$/iu
const shorthandRange = /^\s*(?:[-–—~～]|至|到|或是?|or\b)\s*(?:\d{1,2}(?:st|nd|rd|th)?\b|[一二三四五六七八九十廿卅]+(?:日|号|號))/iu
const uncertainty = /^(?:either\s+)?(?:or|或者|或是?|還是|还是|二选一|二選一)$/iu

function findTasks(clause: string): TaskMention[] {
  return Array.from(clause.matchAll(taskPattern), match => {
    const groups = match.groups || {}
    const numeral = groups.englishNumber || groups.leadingNumber || groups.trailingNumber
    const index = taskAliases.findIndex((_, i) => Boolean(groups[`task${i}`]))
    const parsed = numeral ? dateNumber(numeral) : -1
    const title = numeral ? `Assignment ${parsed > 0 ? parsed : numeral.toUpperCase()}`
      : index >= 0 ? taskAliases[index][0] : match[0].trim()
    const suffix = !numeral && /\d+$/u.test(match[0]) ? ` ${match[0].match(/\d+$/u)?.[0]}` : ''
    return { kind: 'task' as const, start: match.index, end: match.index + match[0].length, title: title + suffix }
  })
}

function gapText(text: string) {
  return text.replace(weekdayNote, '').replace(timePattern, '')
    .replace(/^[\s.,:=()[\]·—–-]+|[\s.,:=()[\]·—–-]+$/gu, '').trim()
}

function linksTaskAndDate(gap: string, taskFirst: boolean) {
  if (taskFirst) {
    return /^(?:(?:is|are|will be|must be)\s+)?(?:(?:both|all)\s+)?(?:due|scheduled|to be (?:held|submitted)|takes? place|set|deadline(?:\s+is)?|submission(?:\s+is)?|on|by|before|at|will be)(?:\s+(?:on|by|before|for|at|no later than|the))*$|^(?:(?:的|都|均|一律|要|需要|需|须|須|将|將|于|於|在|定于|定於|安排在|是|截止|截至|到期|提交|上交|考[试試]|日期|不[迟遲]于)\s*)+$/iu.test(gap)
  }
  return /^(?:(?:i|we)\s+)?(?:(?:will|must|need\s+to|have\s+to|should)\s+)?(?:is|are|for|have|give|do|present|submit|turn in|hand in|attend|finish|complete)(?:\s+(?:a|an|the|my|our))?$|^(?:(?:我[们們]?|是|有|的|都|要|需要|需|将|將|进行|進行|做|交|上交|提交|举行|舉行|完成|参加|參加|考|前|之前|截止|安排|须|須|一起|一场|一場|一次|一个|一個)\s*)+$/iu.test(gap)
}

function customTitle(text: string) {
  return gapText(text)
    .replace(/^(?:(?:i|we)\s+(?:will|need to|have to|must|should)\s+)?(?:(?:submit|turn in|hand in|give|attend|complete|finish|have)(?:\s+(?:the|a|an|my|our))?\s+)?/iu, '')
    .replace(/^(?:(?:我[们們]?|将要|將要|需要|必须|必須|要|进行|進行|提交|上交|交|参加|參加|完成|举行|舉行|之前|前)\s*)+/u, '')
    .replace(/(?:\s+(?:(?:is\s+)?due(?:\s+(?:on|by))?|(?:is\s+)?scheduled(?:\s+for)?|on|by|before|is|takes place)|\s*(?:的)?(?:要|需|将|將)?(?:在|于|於|定于|定於|截止(?:到)?|到期|提交日期))+\s*$/iu, '')
    .replace(/^[\s.：:–—-]+|[\s.：:–—-]+$/gu, '')
    .trim()
}

function datesInRange(clause: string, dates: DateMention[]) {
  const blocked = new Set(dates.filter(date => shorthandRange.test(clause.slice(date.end))))
  for (let i = 1; i < dates.length; i++) {
    const first = dates[i - 1]
    const second = dates[i]
    const between = clause.slice(first.end, second.start).trim()
    const prefix = clause.slice(0, first.start)
    if ((between && rangeJoin.test(between)) || uncertainty.test(between)
      || (/\bbetween\s*$/iu.test(prefix) && /^and$/iu.test(between))) {
      blocked.add(first)
      blocked.add(second)
    }
  }
  return blocked
}

function extractClause(clause: string, dates: DateMention[], noteYear: number | undefined, window: StudyWindow, today: string): CalendarDate[] {
  if (!dates.length) return []
  const tasks = findTasks(clause)
  const blocked = datesInRange(clause, dates)
  const tokens: NoteToken[] = [...dates, ...tasks].sort((a, b) => a.start - b.start)
  const usedDates = new Set<DateMention>()
  const usedTasks = new Set<TaskMention>()
  const result: { start: number; event: CalendarDate }[] = []

  function entry(title: string, date: DateMention, start: number) {
    const resolved = resolveNoteDate(date.value, noteYear, window, today)
    if (resolved && title) result.push({ start, event: { title: title.slice(0, 255), date: resolved } })
  }

  const pairs = tokens.slice(0, -1).flatMap((left, index) => {
    const right = tokens[index + 1]
    if (left.kind === right.kind) return []
    const task = left.kind === 'task' ? left : right as TaskMention
    const date = left.kind === 'date' ? left : right as DateMention
    if (blocked.has(date)) return []
    const rawGap = clause.slice(left.end, right.start)
    const gap = gapText(rawGap)
    if (gap && !linksTaskAndDate(gap, left.kind === 'task')) return []
    const crossedComma = rawGap.includes(',')
    // A task on the same side of a comma wins over a bare adjacent date.
    return [{ task, date, score: (gap ? 0 : 2) + (crossedComma ? 1 : 0) }]
  })

  const attached: { task: TaskMention; date: DateMention }[] = []
  for (const { task, date } of pairs.sort((a, b) => a.score - b.score)) {
    if (usedTasks.has(task) || usedDates.has(date)) continue
    usedTasks.add(task)
    usedDates.add(date)
    attached.push({ task, date })
    entry(task.title, date, task.start)
  }

  // An explicit date can apply to a list of tasks on the same side of it.
  for (const { task, date } of attached) {
    const direction = task.start < date.start ? -1 : 1
    const initial = tokens.indexOf(task)
    for (let i = initial + direction; i >= 0 && i < tokens.length; i += direction) {
      const next = tokens[i]
      if (next.kind !== 'task' || usedTasks.has(next)) break
      const [first, second] = direction === -1 ? [next, tokens[i + 1]] : [tokens[i - 1], next]
      if (!eventListJoin.test(clause.slice(first.end, second.start))) break
      usedTasks.add(next)
      entry(next.title, date, next.start)
    }
  }

  // Preserve custom task names for phrases with one date, including a
  // date-only introduction separated by a comma.
  const boundaries = [0, ...Array.from(clause.matchAll(/[,、]/gu), match => match.index + 1)
    .filter(index => !dates.some(date => date.start < index && index <= date.end)), clause.length + 1]
  for (let i = 0; i < boundaries.length - 1; i++) {
    const start = boundaries[i]
    const end = boundaries[i + 1] - 1
    const localDates = dates.filter(date => date.start >= start && date.start < end)
    if (localDates.length !== 1) continue
    const [date] = localDates
    if (usedDates.has(date) || blocked.has(date) || tasks.some(task => task.start >= start && task.start < end)) continue
    const before = clause.slice(start, date.start).trim()
    const after = clause.slice(date.end, end)
    const hasDateIntro = dateIntro.test(before)
    let title = customTitle(`${hasDateIntro ? '' : before} ${after}`)
    if (!title && hasDateIntro && i + 2 < boundaries.length) {
      const nextEnd = boundaries[i + 2] - 1
      if (!dates.some(other => other.start > date.end && other.start < nextEnd)) {
        title = customTitle(clause.slice(boundaries[i + 1], nextEnd))
      }
    }
    if (title && !dateIntro.test(title) && /[\p{L}]/u.test(title) && !/^(?:maybe|perhaps|tbd|待定|可能|待确认|待確認)$/iu.test(title)) {
      entry(title, date, date.start)
    }
  }

  return result.sort((a, b) => a.start - b.start).map(item => item.event)
}

function eventKey({ title, date }: CalendarDate) {
  return `${date} ${title.trim().normalize('NFKC').toLowerCase()}`
}

function suggestions(note: string, window: StudyWindow, today: string) {
  const text = note.normalize('NFKC')
  const parsed = text.split(/[\n;。!?]|(?<!\b[aApP]\.[mM])\.(?=\s+[A-Z\u3400-\u9fff])/u)
    .map(clause => ({ clause, dates: findDateMentions(clause, today) }))
  const years = new Set(parsed.flatMap(({ dates }) =>
    dates.flatMap(({ value }) => 'year' in value && value.year ? [value.year] : []),
  ))
  const noteYear = years.size === 1 ? [...years][0] : undefined
  return parsed.flatMap(({ clause, dates }) => extractClause(clause, dates, noteYear, window, today))
}

export function updateNoteDates(
  note: string, events: CalendarDate[], window: StudyWindow, today: string, previousNote?: string,
) {
  const next = suggestions(note, window, today)
  const nextKeys = new Set(next.map(eventKey))
  const previous = previousNote === undefined
    ? new Set<string>()
    : new Set(suggestions(previousNote, window, today).map(eventKey))
  const result = events.filter(event => !event[fromNote] || nextKeys.has(eventKey(event)))
  const existing = new Set(result.map(eventKey))
  for (const event of next) {
    const key = eventKey(event)
    if (existing.has(key) || previous.has(key)) continue
    result.push({ ...event, [fromNote]: true })
    existing.add(key)
  }
  return result
}
