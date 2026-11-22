export type StudyWindow = { startDate?: string; deadline?: string }

type MonthDay = { year?: number; month: number; day: number; alternative?: MonthDay }
type DateValue = MonthDay | { offset: number } | { weekday: number; week?: number } | { monthOffset: number; day?: number }
export type DateMention = { kind: 'date'; start: number; end: number; value: DateValue }

const monthNames = 'Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?'
const monthNumbers = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
const weekdays = 'Mon(?:day)?|Tue(?:s(?:day)?)?|Wed(?:nesday)?|Thu(?:rs?(?:day)?)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?'
const weekdayNumbers = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat']
const chineseNumber = '[0-9零〇○一二两兩三四五六七八九十廿卅]{1,8}'
const englishNumber = '\\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten'
const day = '\\d{1,2}(?:st|nd|rd|th)?'

export function dateNumber(text: string): number {
  if (/^\d+$/u.test(text)) return Number(text)
  const normalized = text.replace(/[〇○]/gu, '零').replace(/[两兩]/gu, '二')
  const digits = '零一二三四五六七八九'
  if (/^[零一二三四五六七八九]+$/u.test(normalized)) {
    return Number(Array.from(normalized, digit => digits.indexOf(digit)).join(''))
  }
  const tens = normalized.match(/^([一二三四五六七八九]?)十([一二三四五六七八九]?)$/u)
  if (tens) return (tens[1] ? digits.indexOf(tens[1]) : 1) * 10 + (tens[2] ? digits.indexOf(tens[2]) : 0)
  const shortTens = normalized.match(/^([廿卅])([一二三四五六七八九]?)$/u)
  if (shortTens) return (shortTens[1] === '廿' ? 20 : 30) + (shortTens[2] ? digits.indexOf(shortTens[2]) : 0)
  const english = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']
  return english.indexOf(text.toLowerCase())
}

function monthNumber(text: string) {
  return monthNumbers.indexOf(text.toLowerCase().slice(0, 3)) + 1
}

function isoDate(year: number, month: number, dayOfMonth: number) {
  if (!Number.isInteger(year) || year < 1000 || year > 9999 || month < 1 || month > 12 || dayOfMonth < 1 || dayOfMonth > 31) return ''
  const iso = `${year}-${String(month).padStart(2, '0')}-${String(dayOfMonth).padStart(2, '0')}`
  const parsed = new Date(`${iso}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === iso ? iso : ''
}

function numericMonthDay(first: string, second: string, year?: string): MonthDay {
  const month = Number(first)
  const day = Number(second)
  const parsedYear = year ? Number(year) : undefined
  if (month > 12) return { year: parsedYear, month: day, day: month }
  return {
    year: parsedYear,
    month,
    day,
    ...(day <= 12 && day !== month ? { alternative: { year: parsedYear, month: day, day: month } } : {}),
  }
}

function relativeYear(text: string, today: string) {
  if (!text) return undefined
  const year = Number(today.slice(0, 4))
  if (/^(?:今|本)年$/u.test(text)) return year
  if (text === '明年') return year + 1
  if (/^[后後]年$/u.test(text)) return year + 2
  if (text === '去年') return year - 1
  return dateNumber(text.slice(0, -1))
}

const patterns: { source: string; value: (parts: string[], today: string) => DateValue; priority?: number }[] = [
  { source: '(?<![a-z0-9/.-])(\\d{4})\\s*[-/.]\\s*(\\d{1,2})\\s*[-/.]\\s*(\\d{1,2})(?!\\d|[-/.]\\s*\\d)',
    value: ([year, month, day]) => ({ year: Number(year), month: Number(month), day: Number(day) }) },
  { source: '(?<![a-z0-9/.-])(\\d{1,2})\\s*[-/.]\\s*(\\d{1,2})(?:\\s*[-/.]\\s*(\\d{4}))?(?!\\d|[-/.]\\s*\\d)',
    value: ([first, second, year]) => numericMonthDay(first, second, year) },
  { source: `(?<![0-9零〇○一二两兩三四五六七八九十廿卅])((?:(?:[0-9零〇○一二三四五六七八九]{4}|今|本|明|后|後|去)\\s*年\\s*)?)(${chineseNumber})\\s*月\\s*(${chineseNumber})(?:\\s*(?:日|号|號)|(?![0-9零〇○一二三四五六七八九十廿卅]))`,
    value: ([year, month, day], today) => ({ year: relativeYear(year.replace(/\s/gu, ''), today), month: dateNumber(month), day: dateNumber(day) }) },
  { source: `\\b(${monthNames})\\.?\\s+(${day})(?:,?\\s+(\\d{4}))?\\b`,
    value: ([month, day, year]) => ({ year: year ? Number(year) : undefined, month: monthNumber(month), day: Number.parseInt(day, 10) }) },
  { source: `\\b(${day})\\s+(?:of\\s+)?(${monthNames})\\.?(?:,?\\s+(\\d{4}))?\\b`,
    value: ([day, month, year]) => ({ year: year ? Number(year) : undefined, month: monthNumber(month), day: Number.parseInt(day, 10) }) },
  { source: '\\b(day after tomorrow|day before yesterday|today|tonight|tomorrow|yesterday|tmrw|tmr)\\b|([大]?[后後]天|大前天|前天|昨天|昨日|今天|今日|今晚|明天|明日|明晚)',
    value: ([english, chinese]) => ({
      offset: ({
        'day after tomorrow': 2, 'day before yesterday': -2, today: 0, tonight: 0, tomorrow: 1, yesterday: -1,
        tmrw: 1, tmr: 1, 大后天: 3, 大後天: 3, 后天: 2, 後天: 2, 大前天: -3, 前天: -2, 昨天: -1, 昨日: -1, 明天: 1, 明日: 1, 明晚: 1,
      } as Record<string, number>)[english?.toLowerCase() || chinese] ?? 0,
    }) },
  { source: `\\bin\\s+(${englishNumber})\\s+days?\\b|\\b(${englishNumber})\\s+days?\\s+(?:from\\s+now|later)\\b|(${chineseNumber})\\s*(?:天|日)\\s*(?:之)?[后後]`,
    value: ([inDays, daysFromNow, daysInChinese]) => ({ offset: dateNumber(inDays || daysFromNow || daysInChinese) }) },
  { source: `\\b(?:in\\s+(${englishNumber})\\s+weeks?|(${englishNumber})\\s+weeks?\\s+from\\s+now)\\b|(${chineseNumber})\\s*(?:个|個)?(?:星期|礼拜|禮拜|周|週)\\s*(?:之)?[后後]`,
    value: ([inWeeks, weeksFromNow, weeksInChinese]) => ({ offset: dateNumber(inWeeks || weeksFromNow || weeksInChinese) * 7 }) },
  { source: `\\b(?:(this|next|last|coming)\\s+)?(${weekdays})\\b(?:\\.)?`,
    value: ([period, weekday]) => {
      const week = ({ this: 0, next: 1, last: -1 } as Record<string, number>)[period?.toLowerCase()]
      return { weekday: weekdayNumbers.indexOf(weekday.toLowerCase().slice(0, 3)), week }
    }, priority: 1 },
  { source: '(下下|上上|下|上|本|这|這)?(?:个|個)?(?:星期|礼拜|禮拜|周|週)([一二三四五六日天1-7])',
    value: ([period, weekday]) => ({
      weekday: /[日天7]/u.test(weekday) ? 0 : dateNumber(weekday),
      week: ({ 下下: 2, 上上: -2, 下: 1, 上: -1, 本: 0, 这: 0, 這: 0 } as Record<string, number>)[period],
    }), priority: 1 },
  { source: `(下|上|本|这|這)(?:个|個)?月(?:的)?\\s*(${chineseNumber})\\s*(?:日|号|號)|(?:(本|这|這|下|上)(?:个|個)?月(?:的)?(?:月底|末|最后一天|最後一天))|(月底|月末)`,
    value: ([period, day, endPeriod]) => ({
      monthOffset: (period || endPeriod) === '下' ? 1 : (period || endPeriod) === '上' ? -1 : 0,
      day: day ? dateNumber(day) : undefined,
    }) },
  { source: '\\b(?:the\\s+)?(?:end|last day)\\s+of\\s+(?:(this|next|last|the)\\s+)?month\\b',
    value: ([period]) => ({ monthOffset: period?.toLowerCase() === 'next' ? 1 : period?.toLowerCase() === 'last' ? -1 : 0 }) },
]

const recognizers = patterns.map(({ source, value, priority }) => ({ regex: new RegExp(source, 'giu'), value, priority: priority ?? 0 }))

export function findDateMentions(text: string, today: string): DateMention[] {
  const matches = recognizers.flatMap(({ regex, value, priority }) =>
    Array.from(text.matchAll(regex), match => ({
      kind: 'date' as const, start: match.index, end: match.index + match[0].length,
      value: value(match.slice(1), today), priority,
    })),
  ).sort((a, b) => a.start - b.start || b.end - a.end || a.priority - b.priority)

  const mentions: DateMention[] = []
  for (const match of matches) {
    if (mentions.length && match.start < mentions[mentions.length - 1].end) continue
    mentions.push(match)
  }
  // An adjacent weekday is usually a label for the full date.
  const annotation = /^[\s,，()（）]*$/u
  return mentions.filter((mention, i) => {
    if (!('weekday' in mention.value) || mention.value.week !== undefined) return true
    const prev = mentions[i - 1]
    const next = mentions[i + 1]
    return !(prev && 'month' in prev.value && annotation.test(text.slice(prev.end, mention.start)))
      && !(next && 'month' in next.value && annotation.test(text.slice(mention.end, next.start)))
  })
}

function inWindow(day: string, { startDate, deadline }: StudyWindow) {
  return Boolean(day && startDate && deadline && day >= startDate && day <= deadline)
}

function resolveMonthDay(value: MonthDay, noteYear: number | undefined, window: StudyWindow, today: string): string {
  const { year, month, day, alternative } = value
  const effectiveWindow = { startDate: window.startDate || today, deadline: window.deadline }
  const startYear = Number(effectiveWindow.startDate.slice(0, 4))
  const finalYear = Number(effectiveWindow.deadline?.slice(0, 4) || startYear)
  const daysInWindow = (candidate: MonthDay) => [...new Set([candidate.year ?? startYear, candidate.year ?? finalYear])]
    .map(y => isoDate(y, candidate.month, candidate.day))
    .find(iso => inWindow(iso, effectiveWindow))
  const preferred = daysInWindow(value) || (alternative && daysInWindow(alternative))
  if (preferred) return preferred
  const explicitYear = year ?? noteYear
  if (explicitYear !== undefined) return isoDate(explicitYear, month, day)
  const currentYear = Number(today.slice(0, 4))
  return [currentYear, currentYear + 1]
    .map(y => isoDate(y, month, day))
    .find(iso => iso && iso >= today) || ''
}

export function resolveNoteDate(value: DateValue, noteYear: number | undefined, window: StudyWindow, today: string) {
  if ('month' in value) return resolveMonthDay(value, noteYear, window, today)
  const date = new Date(`${today}T00:00:00Z`)
  if (!Number.isFinite(date.getTime())) return ''
  if ('offset' in value) {
    date.setUTCDate(date.getUTCDate() + value.offset)
  } else if ('weekday' in value) {
    const weekday = date.getUTCDay()
    const offset = value.week === undefined
      ? (value.weekday - weekday + 7) % 7
      : value.week * 7 + (value.weekday + 6) % 7 - (weekday + 6) % 7
    date.setUTCDate(date.getUTCDate() + offset)
  } else {
    const y = date.getUTCFullYear()
    const m = date.getUTCMonth() + value.monthOffset
    const first = new Date(Date.UTC(y, m, 1))
    if (value.day !== undefined) return isoDate(first.getUTCFullYear(), first.getUTCMonth() + 1, value.day)
    date.setUTCFullYear(y, m + 1, 0)
  }
  return date.toISOString().slice(0, 10)
}
