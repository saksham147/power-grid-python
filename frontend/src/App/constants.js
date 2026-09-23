// A monochromatic dark palette: one hue (cyan) carries every accent, live/selected
// state and type distinction, varied only in shade/tint. Red is the sole deliberate
// exception -- reserved for a genuine alert (overloaded, over capacity), the one
// piece of state where dropping color differentiation would actually hurt.
export const ACCENT = '#22d3ee'
export const OFFLINE = '#52525b'
export const POSITIVE = '#67e8f9'
export const NEGATIVE = '#f87171'
export const INK = '#f4f4f5'

export const PLANT_TYPES = {
	THERMAL: { color: '#0e7490', label: 'Thermal' },
	SOLAR: { color: '#22d3ee', label: 'Solar' },
	WIND: { color: '#a5f3fc', label: 'Wind' },
}

export const PROFILE_TYPES = {
	RESIDENTIAL: { color: '#0e7490', label: 'Residential' },
	COMMERCIAL: { color: '#0891b2', label: 'Commercial' },
	INDUSTRIAL: { color: '#22d3ee', label: 'Industrial' },
	GOV: { color: '#a5f3fc', label: 'Government' },
}
