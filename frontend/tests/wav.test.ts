import assert from 'node:assert/strict'
import { test } from 'node:test'
import { downsample, encodeWav } from '../src/wav.ts'

test('downsampling 48 kHz to 16 kHz keeps a third of the samples and the average level', () => {
  const input = new Float32Array(4800).fill(0.5)
  const out = downsample(input, 48000, 16000)
  assert.equal(out.length, 1600)
  assert.ok(out.every((x) => Math.abs(x - 0.5) < 1e-6))
})

test('downsampling to a higher rate is a no-op', () => {
  const input = new Float32Array([0.1, 0.2])
  assert.equal(downsample(input, 8000, 16000), input)
})

test('the WAV has a valid header for 16 kHz mono 16-bit PCM', () => {
  const wav = new DataView(encodeWav(new Float32Array(160), 16000))
  const tag = (o: number) => String.fromCharCode(...[0, 1, 2, 3].map((i) => wav.getUint8(o + i)))
  assert.deepEqual([tag(0), tag(8), tag(12), tag(36)], ['RIFF', 'WAVE', 'fmt ', 'data'])
  assert.equal(wav.byteLength, 44 + 320)
  assert.equal(wav.getUint32(4, true), 36 + 320)
  assert.equal(wav.getUint16(20, true), 1) // PCM
  assert.equal(wav.getUint16(22, true), 1) // mono
  assert.equal(wav.getUint32(24, true), 16000)
  assert.equal(wav.getUint16(34, true), 16)
})

test('samples are scaled to 16-bit and clipped', () => {
  const wav = new DataView(encodeWav(new Float32Array([1, -1, 0, 2, -3]), 16000))
  const at = (i: number) => wav.getInt16(44 + i * 2, true)
  assert.deepEqual([0, 1, 2, 3, 4].map(at), [32767, -32767, 0, 32767, -32767])
})
