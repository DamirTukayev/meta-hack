// The interface in six languages. The key of a text is its English wording; a language without that key shows the English.
// Texts that the agent writes while it works (the log, the assumptions, a violation's message, the repair options) stay English for now.
import { useSyncExternalStore } from 'react'
import de from './locales/de.ts'
import es from './locales/es.ts'
import fr from './locales/fr.ts'
import pt from './locales/pt.ts'
import ru from './locales/ru.ts'

export const LANGS = [
  { code: 'en', label: 'English' },
  { code: 'ru', label: 'Русский' },
  { code: 'es', label: 'Español' },
  { code: 'fr', label: 'Français' },
  { code: 'de', label: 'Deutsch' },
  { code: 'pt', label: 'Português' },
] as const
export type Lang = (typeof LANGS)[number]['code']
export const DICTIONARIES: Record<Exclude<Lang, 'en'>, Record<string, string>> = { ru, es, fr, de, pt }

const KEY = 'orbitroute-lang'
const isLang = (v: unknown): v is Lang => LANGS.some((l) => l.code === v)

/** The language of the page: the one chosen before, else the browser's, else English. */
export function pickLang(saved: string | null | undefined, browser: string | undefined): Lang {
  if (isLang(saved)) return saved
  const code = (browser ?? 'en').slice(0, 2).toLowerCase()
  return isLang(code) ? code : 'en'
}

/** The text of `key` in `lang`, with {name} placeholders filled from `vars`. */
export function translate(lang: Lang, key: string, vars?: Record<string, string | number>): string {
  const text = (lang === 'en' ? undefined : DICTIONARIES[lang][key]) ?? key
  return vars ? text.replace(/\{(\w+)\}/g, (whole, name: string) => (name in vars ? String(vars[name]) : whole)) : text
}

function initial(): Lang {
  let saved: string | null = null
  try { saved = localStorage.getItem(KEY) } catch { /* private window: the browser's language is used */ }
  return pickLang(saved, typeof navigator !== 'undefined' ? navigator.language : undefined)
}

let current: Lang = typeof window === 'undefined' ? 'en' : initial()
if (typeof document !== 'undefined') document.documentElement.lang = current
const listeners = new Set<() => void>()

export function setLang(lang: Lang) {
  current = lang
  try { localStorage.setItem(KEY, lang) } catch { /* not remembered */ }
  if (typeof document !== 'undefined') document.documentElement.lang = lang
  listeners.forEach((f) => f())
}

/** Re-renders the component that calls it when the language changes; the other components follow their parent. */
export function useLang(): Lang {
  return useSyncExternalStore((f) => { listeners.add(f); return () => { listeners.delete(f) } }, () => current)
}

export function t(key: string, vars?: Record<string, string | number>): string {
  return translate(current, key, vars)
}

/** Name of a kind of zone ("park_forest" -> "park/forest") in the current language. */
export function zoneName(kind: string): string {
  const names: Record<string, string> = {
    industrial: t('industrial'), commercial: t('commercial'), residential: t('residential'), park_forest: t('park/forest'),
    other: t('other'), flooded: t('flooded'), custom: t('your zone'),
  }
  return names[kind] ?? kind.replace('_', '/')
}
