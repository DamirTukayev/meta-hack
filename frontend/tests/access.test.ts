import assert from 'node:assert/strict'
import { test } from 'node:test'
import { codeFromHash } from '../src/access.ts'

test('the code is read from the part of the link after the hash', () => {
  assert.equal(codeFromHash('#code=example123'), 'example123')
  assert.equal(codeFromHash('code=example123'), 'example123')
})

test('other hashes, an empty code and stray spaces give no code', () => {
  assert.equal(codeFromHash(''), '')
  assert.equal(codeFromHash('#'), '')
  assert.equal(codeFromHash('#section=2'), '')
  assert.equal(codeFromHash('#code='), '')
  assert.equal(codeFromHash('#code=%20ab%20'), 'ab')
})
