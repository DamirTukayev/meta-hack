import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { test } from 'node:test'
import { DICTIONARIES, LANGS, pickLang, translate } from '../src/i18n.ts'

const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(',')
const others = LANGS.filter((l) => l.code !== 'en').map((l) => l.code)

// Texts the code passes to t() through a variable, so that a search for t('...') does not find them.
const DYNAMIC = [
  'Read image', 'Understand', 'Plan', 'Verify', 'Repair', 'SAM 3.1', 'Muse Spark', 'Solver', 'Independent', 'If needed',
  'Every order is served exactly once', 'Fleet size is respected', 'Truck capacity is respected', 'Every leg follows real roads', 'All work finishes before the deadline', 'Avoided zones are not entered',
  'school', 'hospital or clinic', 'store or mall', 'church or hall', 'hotel or office', 'sports or event hall', 'apartment blocks', 'houses', 'warehouse or factory', 'public building',
  'hospital', 'clinic', 'community centre', 'place of worship', 'town hall', 'fire station', 'college', 'university', 'library', 'mall', 'supermarket', 'department store',
  'Road mask', 'Graph', 'Zones', 'Orders', 'Routes', 'industrial', 'commercial', 'residential', 'park/forest', 'other', 'flooded', 'your zone',
]

function usedKeys(): string[] {
  const dir = new URL('../src/', import.meta.url)
  const keys = new Set<string>()
  for (const file of readdirSync(dir).filter((f) => /\.tsx?$/.test(f) && !f.startsWith('i18n'))) {
    const src = readFileSync(new URL(file, dir), 'utf8')
    for (const m of src.matchAll(/\bt\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|`((?:[^`\\]|\\.)*)`)/g)) {
      keys.add((m[1] ?? m[2] ?? m[3]).replace(/\\'/g, "'").replace(/\\"/g, '"'))
    }
  }
  return [...keys]
}

test('every language has exactly the keys of the others, none of them empty', () => {
  const reference = Object.keys(DICTIONARIES.ru).sort()
  for (const lang of others) {
    assert.deepEqual(Object.keys(DICTIONARIES[lang as keyof typeof DICTIONARIES]).sort(), reference, lang)
    for (const [key, text] of Object.entries(DICTIONARIES[lang as keyof typeof DICTIONARIES])) assert.ok(text.trim().length > 0, `${lang}: empty text for ${key}`)
  }
})

test('a translation keeps the placeholders of its English text', () => {
  for (const lang of others) {
    for (const [key, text] of Object.entries(DICTIONARIES[lang as keyof typeof DICTIONARIES])) assert.equal(placeholders(text), placeholders(key), `${lang}: ${key}`)
  }
})

test('every text the interface shows is translated', () => {
  const missing = [...usedKeys(), ...DYNAMIC].filter((k) => !(k in DICTIONARIES.ru))
  assert.deepEqual(missing, [])
})

test('English is the key, placeholders are filled, an unknown text stays as it is', () => {
  assert.equal(translate('en', 'Plan route'), 'Plan route')
  assert.equal(translate('en', 'Plan #{n}', { n: 3 }), 'Plan #3')
  assert.equal(translate('ru', 'Plan #{n}', { n: 3 }), 'План №3')
  assert.equal(translate('de', 'Plan route'), 'Route planen')
  assert.equal(translate('fr', 'A text nobody translated {x}', { x: 1 }), 'A text nobody translated 1')
  assert.equal(translate('es', 'Order #{n} is left out: {why}', { n: 2 }), 'El pedido n.º 2 queda fuera: {why}') // a value that is not given stays visible
})

test('the page opens in the saved language, else the browser language, else English', () => {
  assert.equal(pickLang('de', 'ru-RU'), 'de')
  assert.equal(pickLang(null, 'ru-RU'), 'ru')
  assert.equal(pickLang(undefined, 'pt-BR'), 'pt')
  assert.equal(pickLang('xx', 'ja-JP'), 'en')
  assert.equal(pickLang(null, undefined), 'en')
})
