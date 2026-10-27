import { useCallback, useEffect, useRef, useState } from 'react'
import { downsample, encodeWav } from './wav'

const TARGET_RATE = 16000
const MAX_SECONDS = 20
const MIN_SECONDS = 0.4

type Phase = 'idle' | 'recording' | 'sending'

interface Recorder {
  ctx: AudioContext
  stream: MediaStream
  node: ScriptProcessorNode
  chunks: Float32Array[]
  timer: number
}

/** Record from the microphone, send a short WAV to the server and hand back the transcript. */
export function useVoice(onText: (text: string) => void) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState('')
  const [heard, setHeard] = useState('')
  const rec = useRef<Recorder | null>(null)

  const release = () => {
    const r = rec.current
    if (!r) return
    window.clearTimeout(r.timer)
    r.node.disconnect()
    r.stream.getTracks().forEach((t) => t.stop())
    void r.ctx.close()
    rec.current = null
  }

  const stop = useCallback(async () => {
    const r = rec.current
    if (!r) return
    const rate = r.ctx.sampleRate
    const chunks = r.chunks
    release()
    const total = chunks.reduce((n, c) => n + c.length, 0)
    if (total / rate < MIN_SECONDS) {
      setPhase('idle')
      setError('That was too short. Hold the button a little longer and speak.')
      return
    }
    const all = new Float32Array(total)
    let at = 0
    chunks.forEach((c) => { all.set(c, at); at += c.length })
    setPhase('sending')
    try {
      const wav = encodeWav(downsample(all, rate, TARGET_RATE), Math.min(rate, TARGET_RATE))
      const res = await fetch('/api/transcribe', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav })
      const j = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'Speech recognition failed.')
      if (!j.text) throw new Error('I could not hear any words. Try again, a bit closer to the microphone.')
      setHeard(j.text)
      onText(j.text)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Speech recognition failed.')
    } finally {
      setPhase('idle')
    }
  }, [onText])

  const start = useCallback(async () => {
    setError('')
    setHeard('')
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('This browser cannot use the microphone here (it needs a secure page).')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } })
      const ctx = new AudioContext()
      const source = ctx.createMediaStreamSource(stream)
      const node = ctx.createScriptProcessor(4096, 1, 1)
      const chunks: Float32Array[] = []
      node.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)))
      source.connect(node)
      node.connect(ctx.destination) // a script processor only runs while connected; its output is silent
      rec.current = { ctx, stream, node, chunks, timer: window.setTimeout(() => void stop(), MAX_SECONDS * 1000) }
      setPhase('recording')
    } catch (e) {
      const denied = e instanceof DOMException && (e.name === 'NotAllowedError' || e.name === 'SecurityError')
      setError(denied ? 'Microphone access was blocked. Allow it in the browser and try again.' : 'No microphone could be opened.')
    }
  }, [stop])

  const toggle = useCallback(() => {
    if (phase === 'recording') void stop()
    else if (phase === 'idle') void start()
  }, [phase, start, stop])

  useEffect(() => release, [])
  return { phase, error, heard, toggle, supported: typeof navigator !== 'undefined' && !!navigator.mediaDevices }
}
