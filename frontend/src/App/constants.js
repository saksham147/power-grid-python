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

/** What a plant costs to build (or, at the margin, to grow), debited from the shared
 *  Grid wallet before Producer ever sees the request -- see AddPlantModal/
 *  UpgradePlantModal in modals.jsx. This is a preview only: the server
 *  (billing.PlantPricing) computes and charges the authoritative number from the
 *  same formula, so this must mirror it exactly or the preview lies. cost =
 *  max(minimum, base + progressive per-MW cost): base is the fixed setup cost,
 *  minimum is a floor so a tiny plant is never near-free, and the per-MW cost is
 *  banded like a tax bracket -- each band only charges its own rate on the slice of
 *  capacity inside it, rising band to band. */
export const PLANT_RATES = {
	THERMAL: { base: 2000, minimum: 5000, bands: [{ uptoMw: 300, perMw: 8 }, { uptoMw: 600, perMw: 10 }, { uptoMw: Infinity, perMw: 14 }] },
	WIND: { base: 1000, minimum: 3000, bands: [{ uptoMw: 50, perMw: 16 }, { uptoMw: 100, perMw: 20 }, { uptoMw: Infinity, perMw: 26 }] },
	SOLAR: { base: 500, minimum: 2000, bands: [{ uptoMw: 50, perMw: 8 }, { uptoMw: 150, perMw: 10 }, { uptoMw: Infinity, perMw: 13 }] },
}

export function plantCost(type, capacityMw) {
	const { base, minimum, bands } = PLANT_RATES[type]
	const mw = capacityMw || 0

	let bandedCost = 0
	let coveredMw = 0
	for (const band of bands) {
		const mwInBand = Math.max(0, Math.min(mw, band.uptoMw) - coveredMw)
		bandedCost += mwInBand * band.perMw
		coveredMw = band.uptoMw
		if (mw <= band.uptoMw) break
	}

	return Math.max(minimum, base + bandedCost)
}

/** Fraction of a fresh-build price refunded when a plant is decommissioned -- a
 *  preview only, matching billing.wiring.DECOMMISSION_REFUND_RATIO; the server
 *  computes and credits the authoritative amount. */
export const DECOMMISSION_REFUND_RATIO = 0.5
