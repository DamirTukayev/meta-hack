import type { RoutePlan, XY } from './types'

export function polyLen(poly: XY[]): number {
  let d = 0
  for (let i = 1; i < poly.length; i++) d += Math.hypot(poly[i][0] - poly[i - 1][0], poly[i][1] - poly[i - 1][1])
  return d
}

/** The point at distance d along a polyline and the direction of travel there (radians). */
export function pointAt(poly: XY[], d: number): { xy: XY; angle: number } {
  let left = Math.max(d, 0)
  for (let i = 1; i < poly.length; i++) {
    const [x0, y0] = poly[i - 1]
    const [x1, y1] = poly[i]
    const seg = Math.hypot(x1 - x0, y1 - y0)
    if (seg > 0 && left <= seg) {
      const f = left / seg
      return { xy: [x0 + (x1 - x0) * f, y0 + (y1 - y0) * f], angle: Math.atan2(y1 - y0, x1 - x0) }
    }
    left -= seg
  }
  const n = poly.length
  if (n < 2) return { xy: poly[0] ?? [0, 0], angle: 0 }
  return { xy: poly[n - 1], angle: Math.atan2(poly[n - 1][1] - poly[n - 2][1], poly[n - 1][0] - poly[n - 2][0]) }
}

/** The part of a polyline up to distance d. */
export function upTo(poly: XY[], d: number): XY[] {
  if (d <= 0 || poly.length === 0) return poly.length ? [poly[0]] : []
  const out: XY[] = [poly[0]]
  let left = d
  for (let i = 1; i < poly.length; i++) {
    const seg = Math.hypot(poly[i][0] - poly[i - 1][0], poly[i][1] - poly[i - 1][1])
    if (left >= seg) {
      out.push(poly[i])
      left -= seg
    } else {
      const f = seg > 0 ? left / seg : 0
      out.push([poly[i - 1][0] + (poly[i][0] - poly[i - 1][0]) * f, poly[i - 1][1] + (poly[i][1] - poly[i - 1][1]) * f])
      break
    }
  }
  return out
}

/** Direction markers along a leg: roughly every `spacing` px, and always at least one in the middle. */
export function arrowsAlong(poly: XY[], spacing: number): { xy: XY; angle: number }[] {
  const total = polyLen(poly)
  if (total < spacing * 0.4) return []
  const n = Math.max(1, Math.round(total / spacing))
  return Array.from({ length: n }, (_, i) => pointAt(poly, (total * (i + 0.5)) / n))
}

export interface RouteGeo {
  legs: XY[][]
  flat: XY[]
  stopDist: number[] // distance along `flat` at which each stop is reached
  total: number
}

export function buildGeo(r: RoutePlan): RouteGeo {
  const legs = r.legs && r.legs.length ? r.legs : [r.polyline]
  const flat: XY[] = []
  const stopDist: number[] = []
  let acc = 0
  legs.forEach((leg, i) => {
    flat.push(...(flat.length ? leg.slice(1) : leg))
    acc += polyLen(leg)
    if (i < legs.length - 1) stopDist.push(acc)
  })
  return { legs, flat, stopDist, total: acc }
}
