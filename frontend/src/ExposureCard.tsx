import type { Exposure, XY } from './types'

const KIND_LABEL: Record<string, string> = {
  school: 'school', hospital_or_clinic: 'hospital or clinic', store_or_mall: 'store or mall', church_or_hall: 'church or hall',
  hotel_or_office: 'hotel or office', sports_or_event_hall: 'sports or event hall', amenity: 'public building',
  hospital: 'hospital', clinic: 'clinic', community_centre: 'community centre', place_of_worship: 'place of worship', townhall: 'town hall',
  fire_station: 'fire station', college: 'college', university: 'university', library: 'library', mall: 'mall', supermarket: 'supermarket', department_store: 'department store',
}

// What the photo says about the water: how many buildings it touches and where a crowd could be put up. A rough reading, never a count.
export default function ExposureCard(props: { x: Exposure; running: boolean; onUseDepot: (xy: XY) => void }) {
  const { x } = props
  return (
    <section className="panel exposure">
      <h2>Water <small>rough, from the photo</small></h2>
      <p className="expo-line">
        <b>{x.in_water}</b> building{x.in_water === 1 ? '' : 's'} in the water, <b>{x.surrounded}</b> surrounded by it (within 15 m), of {x.buildings} found.
      </p>
      <p className="expo-line">
        People: <b>{x.people_low}–{x.people_high}</b> <span className="muted">({x.assumption}). The lower figure counts only buildings in the water, the upper adds the surrounded ones; the photo shows water, not its depth or any damage, and water under trees is missed, so both are rough.</span>
      </p>
      <h3>Where a crowd could go</h3>
      {x.shelters.length === 0 ? (
        <p className="muted small">No large dry building within reach by roads that are not under water{x.cut_off_by_water ? ` (${x.cut_off_by_water} large dry buildings are cut off by the water)` : ''}.</p>
      ) : (
        <ul className="shelters">
          {x.shelters.map((s, i) => (
            <li key={i}>
              <span><b>{i + 1}.</b> {s.name ?? (s.kind ? KIND_LABEL[s.kind] ?? s.kind : s.guess ? `large dry building, type unknown (maybe ${(KIND_LABEL[s.guess] ?? s.guess.replace(/_/g, ' '))}, the model is not sure)` : 'large dry building, type unknown')}{s.name && s.kind ? ` (${KIND_LABEL[s.kind] ?? s.kind})` : ''} · {s.area_m2} m² · up to ~{s.capacity} people on the ground floor · {s.minutes} min by dry roads from the depot</span>
              <button type="button" disabled={props.running} onClick={() => props.onUseDepot(s.xy)}>Use as depot</button>
            </li>
          ))}
        </ul>
      )}
      {Object.keys(x.not_shelters ?? {}).length > 0 && <p className="muted small">Left out after looking at them: {Object.entries(x.not_shelters).map(([k, v]) => `${v} ${k === 'apartment_block' ? 'apartment blocks' : k}`).join(', ')}.</p>}
      <p className="muted small">Nothing here says a building is open, safe or has the room: it says where to look first.</p>
    </section>
  )
}
