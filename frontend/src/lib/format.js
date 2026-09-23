// Every number the UI shows goes through exactly one of these -- no component
// formats a number on its own.

export const kw = (n) =>
	n >= 1000 ? `${(n / 1000).toFixed(2)} MW` : `${Number(n).toFixed(1)} kW`

export const mw = (n) => `${Number(n).toFixed(1)} MW`

export const mwh = (n) =>
	n >= 1000 ? `${(n / 1000).toFixed(2)} GWh` : `${Number(n).toFixed(1)} MWh`

/** Signed, since a deviation's direction (slow vs. fast) is the point. */
export const hz = (n) => `${n > 0 ? '+' : ''}${Number(n).toFixed(3)} Hz`

export const rupees = (n) => `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

const perSecondDigits = (n) => (Math.abs(n) >= 100 ? 0 : 2)

/** A money rate: ₹12.50/s, or ₹1,908/s once it is big enough that paise are noise. */
export const rupeesPerSec = (n) => {
	const digits = perSecondDigits(Number(n))
	return `₹${Number(n).toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}/s`
}

export const time = (iso) =>
	new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })

/**
 * Splits each zone's billed revenue per second across the buildings inside it, in
 * proportion to how much power each one is drawing right now.
 *
 * Billing works at the zone level -- Customer publishes one demand figure per zone,
 * so that is the finest grain a charge is ever recorded at. While a zone is within
 * its capacity a building's own bill is exactly demand x rate, which is the same as
 * its demand share of the zone's revenue; when the zone is over capacity the
 * surcharge is shared out by the same proportions, the fair split of a cost nobody
 * can attribute to one building. Either way the buildings of a zone always add up to
 * the zone's revenue, never more or less.
 *
 * @param zoneRevenue Map of zoneId -> revenue per second for that zone
 * @param units       Customer's units, each with zoneId, unitId and live demandKw
 * @returns Map of unitId -> revenue per second; 0 for a zone with nothing drawing power
 */
export function revenueByUnit(zoneRevenue, units) {
	const zoneDemand = new Map()
	for (const u of units) {
		zoneDemand.set(u.zoneId, (zoneDemand.get(u.zoneId) ?? 0) + Math.max(0, u.demandKw))
	}

	const byUnit = new Map()
	for (const u of units) {
		const total = zoneDemand.get(u.zoneId) ?? 0
		const share = total > 0 ? Math.max(0, u.demandKw) / total : 0
		byUnit.set(u.unitId, (zoneRevenue.get(u.zoneId) ?? 0) * share)
	}
	return byUnit
}
