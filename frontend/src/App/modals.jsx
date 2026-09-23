import { useState } from 'react'

import { useCreatePlant, useUpgradePlant } from '../lib/producerQueries.js'
import { useCreateZoneCapacity, useDeleteZoneCapacity, useUpdateZoneCapacity } from '../lib/distributorQueries.js'
import { useCreateUnit, useCreateZone, useDeleteUnit, useDeleteZone, useUpgradeUnit, useUpgradeZone } from '../lib/customerQueries.js'
import { useDecommissionPlant, usePurchasePlant, useUnlocks, useUpgradePlantCost } from '../lib/billingQueries.js'
import { kw, rupees } from '../lib/format'
import { PLANT_TYPES, PROFILE_TYPES, plantCost } from './constants'

/** Shared shell every modal in this file uses: a dimmed backdrop that closes on
 *  click, and a centered card that doesn't. */
export function ModalShell({ onClose, children, wide }) {
	return (
		<div
			className="fixed inset-0 z-10 flex items-center justify-center bg-black/60 px-4"
			onClick={onClose}
		>
			<div
				onClick={(e) => e.stopPropagation()}
				className={`w-full ${wide ? 'max-w-md' : 'max-w-sm'} rounded-2xl border border-zinc-800 bg-zinc-900 p-5 shadow-xl`}
			>
				{children}
			</div>
		</div>
	)
}

export function ErrorBox({ error }) {
	if (!error) return null
	return (
		<div className="mt-3 rounded-lg border border-red-900 bg-red-950/60 px-3 py-2 text-xs text-red-300">
			<p>{error.message}</p>
			{error.details?.length > 0 && (
				<ul className="mt-1 list-disc pl-4">
					{error.details.map((d) => <li key={d}>{d}</li>)}
				</ul>
			)}
		</div>
	)
}

const labelClass = 'mt-3 block text-xs text-zinc-400'
export const inputClass =
	'mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-2.5 py-1.5 text-sm tabular-nums text-zinc-100 focus:outline-2 focus:outline-cyan-400'
const btn = 'rounded-lg border px-3 py-1.5 text-sm font-medium transition disabled:opacity-40'
const btnPrimary = `${btn} border-cyan-500 bg-cyan-500 text-zinc-950 hover:bg-cyan-400`
const btnPlain = `${btn} border-zinc-700 text-zinc-300 hover:bg-zinc-800`
const btnDanger = `${btn} border-red-900 text-red-400 hover:bg-red-950`

function Actions({ children }) {
	return <div className="mt-5 flex justify-end gap-2">{children}</div>
}

// ---- Plants -------------------------------------------------------------------------------

export function AddPlantModal({ onClose }) {
	const [type, setType] = useState('THERMAL')
	const [capacityMw, setCapacityMw] = useState(0)
	const [spendError, setSpendError] = useState(null)
	const purchase = usePurchasePlant()
	const createPlant = useCreatePlant(onClose)
	// Server-side enforced regardless (purchasePlant rejects a locked type with 403)
	// -- this is only so the picker doesn't invite a submit that's going to fail.
	const { data: unlocks } = useUnlocks()
	const unlockedTypes = unlocks?.unlockedTypes ?? Object.keys(PLANT_TYPES)
	const cost = plantCost(type, capacityMw)

	async function handleSubmit(e) {
		e.preventDefault()
		setSpendError(null)
		const form = new FormData(e.currentTarget)

		try {
			await purchase.mutateAsync({ plantType: type, capacityMw })
		} catch (err) {
			setSpendError(err)
			return
		}

		createPlant.mutate({
			name: form.get('name'),
			type,
			capacityMw: Number(form.get('capacityMw')),
			minOutputMw: Number(form.get('minOutputMw') || 0),
			baseOutputMw: Number(form.get('baseOutputMw') || 0),
		})
	}

	return (
		<ModalShell onClose={onClose}>
			<form onSubmit={handleSubmit}>
				<h2 className="text-sm font-semibold text-zinc-100">Add plant</h2>

				<label className={labelClass}>
					Name
					<input name="name" required className={inputClass.replace('tabular-nums', '')} />
				</label>

				<label className={labelClass}>
					Type
					<select
						name="type"
						value={type}
						onChange={(e) => setType(e.target.value)}
						className={inputClass.replace('tabular-nums', '')}
					>
						{Object.entries(PLANT_TYPES).map(([value, meta]) => (
							<option key={value} value={value} disabled={!unlockedTypes.includes(value)}>
								{meta.label}{unlockedTypes.includes(value) ? '' : ' (locked)'}
							</option>
						))}
					</select>
				</label>

				<div className="mt-3 grid grid-cols-3 gap-2">
					<label className="block text-xs text-zinc-400">
						Capacity MW
						<input
							name="capacityMw" type="number" step="0.1" min="0.1" required
							value={capacityMw || ''}
							onChange={(e) => setCapacityMw(Number(e.target.value))}
							className={inputClass}
						/>
					</label>
					<label className="block text-xs text-zinc-400">
						Min MW
						<input name="minOutputMw" type="number" step="0.1" min="0" defaultValue="0" className={inputClass} />
					</label>
					<label className="block text-xs text-zinc-400">
						Base MW
						<input name="baseOutputMw" type="number" step="0.1" min="0" defaultValue="0" className={inputClass} />
					</label>
				</div>

				<div className="mt-4 flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-xs">
					<span className="text-zinc-400">Cost, from the Grid wallet</span>
					<span className="font-semibold tabular-nums text-zinc-100">{rupees(cost)}</span>
				</div>

				<ErrorBox error={spendError ?? createPlant.error} />

				<Actions>
					<button type="button" onClick={onClose} className={btnPlain}>Cancel</button>
					<button type="submit" disabled={purchase.isPending || createPlant.isPending} className={btnPrimary}>
						{purchase.isPending ? 'Paying…' : createPlant.isPending ? 'Adding…' : `Pay ${rupees(cost)} & add`}
					</button>
				</Actions>
			</form>
		</ModalShell>
	)
}

export function EditPlantModal({ plant, onClose, onDeleted }) {
	const [capacityMw, setCapacityMw] = useState(plant.capacityMw)
	const [spendError, setSpendError] = useState(null)
	const upgradeCost = useUpgradePlantCost()
	const upgradePlant = useUpgradePlant(onClose)
	const decommission = useDecommissionPlant()
	// Growing a plant costs the difference between its old and new price; shrinking
	// it, or leaving capacity unchanged, is free -- matches
	// billing.api.views.upgrade_plant exactly, so this preview can never promise a
	// charge the server won't also make.
	const extraCost = Math.max(0, plantCost(plant.type, capacityMw) - plantCost(plant.type, plant.capacityMw))

	async function handleSubmit(e) {
		e.preventDefault()
		setSpendError(null)
		const form = new FormData(e.currentTarget)

		if (extraCost > 0) {
			try {
				await upgradeCost.mutateAsync({ plantType: plant.type, oldCapacityMw: plant.capacityMw, newCapacityMw: capacityMw })
			} catch (err) {
				setSpendError(err)
				return
			}
		}

		upgradePlant.mutate({
			id: plant.id,
			name: form.get('name'),
			capacityMw,
			minOutputMw: Number(form.get('minOutputMw') || 0),
			baseOutputMw: Number(form.get('baseOutputMw') || 0),
		})
	}

	async function handleDecommission() {
		const refund = rupees(plantCost(plant.type, plant.capacityMw) * 0.5)
		if (!window.confirm(`Decommission ${plant.name}? You get back about ${refund}. This cannot be undone.`)) return
		try {
			await decommission.mutateAsync({ plantType: plant.type, capacityMw: plant.capacityMw })
		} catch {
			// A failed refund credit (network/validation) should not still delete the plant.
			return
		}
		onDeleted(plant.id)
	}

	return (
		<ModalShell onClose={onClose}>
			<form onSubmit={handleSubmit}>
				<h2 className="text-sm font-semibold text-zinc-100">Edit {plant.name}</h2>
				<p className="mt-0.5 text-xs text-zinc-500">{PLANT_TYPES[plant.type]?.label ?? plant.type} · type can't change</p>

				<label className={labelClass}>
					Name
					<input name="name" required defaultValue={plant.name} className={inputClass.replace('tabular-nums', '')} />
				</label>

				<div className="mt-3 grid grid-cols-3 gap-2">
					<label className="block text-xs text-zinc-400">
						Capacity MW
						<input
							name="capacityMw" type="number" step="0.1" min="0.1" required
							value={capacityMw}
							onChange={(e) => setCapacityMw(Number(e.target.value))}
							className={inputClass}
						/>
					</label>
					<label className="block text-xs text-zinc-400">
						Min MW
						<input name="minOutputMw" type="number" step="0.1" min="0" defaultValue={plant.minOutputMw} className={inputClass} />
					</label>
					<label className="block text-xs text-zinc-400">
						Base MW
						<input name="baseOutputMw" type="number" step="0.1" min="0" defaultValue={plant.baseOutputMw} className={inputClass} />
					</label>
				</div>

				<div className="mt-4 flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-xs">
					<span className="text-zinc-400">{extraCost > 0 ? 'Extra cost to grow, from the Grid wallet' : 'Extra cost to grow'}</span>
					<span className="font-semibold tabular-nums text-zinc-100">{extraCost > 0 ? rupees(extraCost) : 'Free'}</span>
				</div>

				<ErrorBox error={spendError ?? upgradePlant.error ?? decommission.error} />

				<div className="mt-5 flex items-center justify-between">
					<button type="button" onClick={handleDecommission} disabled={decommission.isPending} className={btnDanger}>
						{decommission.isPending ? 'Decommissioning…' : 'Decommission'}
					</button>
					<div className="flex gap-2">
						<button type="button" onClick={onClose} className={btnPlain}>Cancel</button>
						<button type="submit" disabled={upgradeCost.isPending || upgradePlant.isPending} className={btnPrimary}>
							{upgradeCost.isPending
								? 'Paying…'
								: upgradePlant.isPending
									? 'Saving…'
									: extraCost > 0 ? `Pay ${rupees(extraCost)} & save` : 'Save changes'}
						</button>
					</div>
				</div>
			</form>
		</ModalShell>
	)
}

// ---- Zones --------------------------------------------------------------------------------

export function AddZoneModal({ onClose }) {
	const createZone = useCreateZone(onClose)

	function handleSubmit(e) {
		e.preventDefault()
		const form = new FormData(e.currentTarget)
		createZone.mutate({ zoneId: form.get('zoneId'), name: form.get('name') })
	}

	return (
		<ModalShell onClose={onClose}>
			<form onSubmit={handleSubmit}>
				<h2 className="text-sm font-semibold text-zinc-100">Add zone</h2>
				<p className="mt-0.5 text-xs text-zinc-500">Houses, factories and commercial buildings go inside it next.</p>

				<div className="mt-4 grid grid-cols-2 gap-2">
					<label className="block text-xs text-zinc-400">
						Zone ID
						<input name="zoneId" required placeholder="Z-SOUTH" className={inputClass.replace('tabular-nums', '')} />
					</label>
					<label className="block text-xs text-zinc-400">
						Name
						<input name="name" required className={inputClass.replace('tabular-nums', '')} />
					</label>
				</div>

				<ErrorBox error={createZone.error} />

				<Actions>
					<button type="button" onClick={onClose} className={btnPlain}>Cancel</button>
					<button type="submit" disabled={createZone.isPending} className={btnPrimary}>
						{createZone.isPending ? 'Adding…' : 'Add zone'}
					</button>
				</Actions>
			</form>
		</ModalShell>
	)
}

export function EditZoneModal({ zone, onClose, onDeleted }) {
	const upgradeZone = useUpgradeZone(onClose)
	const deleteZone = useDeleteZone()

	function handleSubmit(e) {
		e.preventDefault()
		const form = new FormData(e.currentTarget)
		upgradeZone.mutate({ zoneId: zone.zoneId, name: form.get('name') })
	}

	function handleDelete() {
		if (!window.confirm(`Delete zone ${zone.name} and every building inside it? This cannot be undone.`)) return
		deleteZone.mutate(zone.zoneId, { onSuccess: () => onDeleted(zone.zoneId) })
	}

	return (
		<ModalShell onClose={onClose}>
			<form onSubmit={handleSubmit}>
				<h2 className="text-sm font-semibold text-zinc-100">Edit {zone.name}</h2>
				<p className="mt-0.5 text-xs text-zinc-500">{zone.zoneId}</p>

				<label className={labelClass}>
					Name
					<input name="name" required defaultValue={zone.name} className={inputClass.replace('tabular-nums', '')} />
				</label>

				<ErrorBox error={upgradeZone.error ?? deleteZone.error} />

				<div className="mt-5 flex items-center justify-between">
					<button type="button" onClick={handleDelete} disabled={deleteZone.isPending} className={btnDanger}>
						{deleteZone.isPending ? 'Deleting…' : 'Delete zone'}
					</button>
					<div className="flex gap-2">
						<button type="button" onClick={onClose} className={btnPlain}>Cancel</button>
						<button type="submit" disabled={upgradeZone.isPending} className={btnPrimary}>
							{upgradeZone.isPending ? 'Saving…' : 'Save'}
						</button>
					</div>
				</div>
			</form>
		</ModalShell>
	)
}

// ---- Buildings (customer units) ------------------------------------------------------------

export const smallInputClass =
	'rounded-lg border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-xs text-zinc-100 focus:outline-2 focus:outline-cyan-400'

export function AddCustomerModal({ zones, defaultZoneId, onClose }) {
	const createUnit = useCreateUnit(onClose)
	const hasZones = Boolean(zones?.length)

	function handleSubmit(e) {
		e.preventDefault()
		const form = new FormData(e.currentTarget)
		createUnit.mutate({
			unitId: form.get('unitId'),
			zoneId: form.get('zoneId'),
			name: form.get('name'),
			type: form.get('type'),
			capacityKw: Number(form.get('capacityKw')),
		})
	}

	return (
		<ModalShell onClose={onClose}>
			<form onSubmit={handleSubmit}>
				<h2 className="text-sm font-semibold text-zinc-100">Add customer</h2>

				<label className={labelClass}>
					Zone
					{hasZones ? (
						<select name="zoneId" required defaultValue={defaultZoneId ?? ''} className={inputClass.replace('tabular-nums', '')}>
							<option value="" disabled>Choose a zone…</option>
							{zones.map((z) => <option key={z.zoneId} value={z.zoneId}>{z.name}</option>)}
						</select>
					) : (
						<span className="mt-1 block rounded-lg border border-dashed border-zinc-700 px-2.5 py-1.5 text-zinc-500">
							Add a zone first
						</span>
					)}
				</label>

				<div className="mt-3 grid grid-cols-2 gap-2">
					<label className="block text-xs text-zinc-400">
						Customer ID
						<input name="unitId" required placeholder="U-NEW" className={inputClass.replace('tabular-nums', '')} />
					</label>
					<label className="block text-xs text-zinc-400">
						Name
						<input name="name" required className={inputClass.replace('tabular-nums', '')} />
					</label>
				</div>

				<div className="mt-3 grid grid-cols-2 gap-2">
					<label className="block text-xs text-zinc-400">
						Type
						<select name="type" defaultValue="RESIDENTIAL" className={inputClass.replace('tabular-nums', '')}>
							{Object.entries(PROFILE_TYPES).map(([value, m]) => <option key={value} value={value}>{m.label}</option>)}
						</select>
					</label>
					<label className="block text-xs text-zinc-400">
						Capacity kW
						<input name="capacityKw" type="number" step="1" min="1" required className={inputClass} />
					</label>
				</div>

				<ErrorBox error={createUnit.error} />

				<Actions>
					<button type="button" onClick={onClose} className={btnPlain}>Cancel</button>
					<button type="submit" disabled={!hasZones || createUnit.isPending} className={btnPrimary}>
						{createUnit.isPending ? 'Adding…' : 'Add customer'}
					</button>
				</Actions>
			</form>
		</ModalShell>
	)
}

export function EditCustomerModal({ unit, onClose, onDeleted }) {
	const upgradeUnit = useUpgradeUnit(onClose)
	const deleteUnit = useDeleteUnit()

	function handleSubmit(e) {
		e.preventDefault()
		const form = new FormData(e.currentTarget)
		upgradeUnit.mutate({
			unitId: unit.unitId,
			zoneId: unit.zoneId,
			name: form.get('name'),
			type: unit.type,
			capacityKw: Number(form.get('capacityKw')),
		})
	}

	function handleDelete() {
		if (!window.confirm(`Delete ${unit.name}?`)) return
		deleteUnit.mutate(unit.unitId, { onSuccess: () => onDeleted(unit.unitId) })
	}

	return (
		<ModalShell onClose={onClose}>
			<form onSubmit={handleSubmit}>
				<h2 className="text-sm font-semibold text-zinc-100">Edit {unit.name}</h2>
				<p className="mt-0.5 text-xs text-zinc-500">{PROFILE_TYPES[unit.type]?.label ?? unit.type} · type can't change</p>

				<label className={labelClass}>
					Name
					<input name="name" required defaultValue={unit.name} className={inputClass.replace('tabular-nums', '')} />
				</label>

				<label className={labelClass}>
					Capacity kW
					<input name="capacityKw" type="number" step="1" min="1" required defaultValue={unit.capacityKw} className={inputClass} />
				</label>

				<ErrorBox error={upgradeUnit.error ?? deleteUnit.error} />

				<div className="mt-5 flex items-center justify-between">
					<button type="button" onClick={handleDelete} disabled={deleteUnit.isPending} className={btnDanger}>
						{deleteUnit.isPending ? 'Deleting…' : 'Delete'}
					</button>
					<div className="flex gap-2">
						<button type="button" onClick={onClose} className={btnPlain}>Cancel</button>
						<button type="submit" disabled={upgradeUnit.isPending} className={btnPrimary}>
							{upgradeUnit.isPending ? 'Saving…' : 'Save'}
						</button>
					</div>
				</div>
			</form>
		</ModalShell>
	)
}

// ---- Zone capacities ------------------------------------------------------------------------

/**
 * "Distributor is just a line zone manager": add, edit and remove the power
 * capacity assigned to each zone. This never touches Customer's own zone list
 * (zones are added/removed via AddZoneModal/EditZoneModal) -- a capacity here is a
 * billing ceiling keyed to a zone id Customer already owns, not a second copy of
 * the zone itself. Demand above it is never refused; Billing surcharges the excess
 * instead.
 */
export function ManageZoneCapacitiesModal({ capacities, zones, onClose }) {
	const [adding, setAdding] = useState(false)
	const [editingZoneId, setEditingZoneId] = useState(null)

	const createCapacity = useCreateZoneCapacity(() => setAdding(false))
	const updateCapacity = useUpdateZoneCapacity(() => setEditingZoneId(null))
	const deleteCapacity = useDeleteZoneCapacity()

	const cappedZoneIds = new Set(capacities.map((c) => c.zoneId))
	const availableZones = zones.filter((z) => !cappedZoneIds.has(z.zoneId))

	function handleAdd(e) {
		e.preventDefault()
		const form = new FormData(e.currentTarget)
		const zoneId = form.get('zoneId')
		const zone = zones.find((z) => z.zoneId === zoneId)
		createCapacity.mutate({ zoneId, zoneName: zone?.name ?? zoneId, capacityKw: Number(form.get('capacityKw')) })
	}

	function handleEdit(e, capacity) {
		e.preventDefault()
		const form = new FormData(e.currentTarget)
		updateCapacity.mutate({ zoneId: capacity.zoneId, zoneName: capacity.zoneName, capacityKw: Number(form.get('capacityKw')) })
	}

	return (
		<ModalShell onClose={onClose} wide>
			<div className="flex items-start justify-between gap-3">
				<div>
					<h2 className="text-sm font-semibold text-zinc-100">Zone capacities</h2>
					<p className="mt-0.5 text-xs text-zinc-500">what Distributor will supply before Billing surcharges the rest</p>
				</div>
				<button type="button" onClick={onClose} className="text-zinc-500 hover:text-zinc-200">✕</button>
			</div>

			<div className="mt-4 max-h-72 overflow-y-auto rounded-lg border border-zinc-800">
				{capacities.length === 0 && (
					<p className="px-3 py-4 text-center text-xs text-zinc-500">No zone capacities set — every zone is unmetered.</p>
				)}
				{capacities.map((capacity) => {
					if (editingZoneId === capacity.zoneId) {
						return (
							<form key={capacity.zoneId} onSubmit={(e) => handleEdit(e, capacity)} className="border-b border-zinc-800 px-3 py-2 last:border-0">
								<div className="flex items-center gap-2">
									<div className="min-w-0 flex-1">
										<p className="truncate text-xs font-medium text-zinc-100">{capacity.zoneName}</p>
										<p className="text-[10px] text-zinc-500">{capacity.zoneId}</p>
									</div>
									<input
										name="capacityKw" type="number" step="1" min="1" required autoFocus
										defaultValue={capacity.capacityKw} className={`w-28 tabular-nums ${smallInputClass}`}
									/>
									<span className="text-[10px] text-zinc-500">kW</span>
								</div>
								<div className="mt-2 flex justify-end gap-2">
									<button type="submit" className="text-xs font-medium text-cyan-400 hover:text-cyan-300">Save</button>
									<button type="button" onClick={() => setEditingZoneId(null)} className="text-xs text-zinc-500 hover:text-zinc-300">
										Cancel
									</button>
								</div>
								<ErrorBox error={updateCapacity.error} />
							</form>
						)
					}

					const over = capacity.overCapacity
					return (
						<div key={capacity.zoneId} className="flex items-center justify-between gap-3 border-b border-zinc-800 px-3 py-2 text-xs last:border-0">
							<div className="min-w-0">
								<p className="truncate font-medium text-zinc-100">{capacity.zoneName}</p>
								<p className="text-[10px] text-zinc-500">{capacity.zoneId}</p>
							</div>
							<div className="flex shrink-0 items-center gap-2">
								<span className="tabular-nums font-medium" style={{ color: over ? '#f87171' : '#f4f4f5' }}>
									{kw(capacity.currentDemandKw)} <span className="font-normal text-zinc-500">/ {kw(capacity.capacityKw)}</span>
								</span>
								{over && (
									<span className="rounded-full px-1.5 py-0.5 text-[9px] font-semibold" style={{ background: '#450a0a', color: '#f87171' }}>
										OVER
									</span>
								)}
								<button type="button" onClick={() => setEditingZoneId(capacity.zoneId)} className="text-zinc-500 hover:text-zinc-100">
									Edit
								</button>
								<button
									type="button"
									onClick={() => {
										if (window.confirm(`Remove the capacity for ${capacity.zoneName}? It will bill at the normal rate only.`)) {
											deleteCapacity.mutate(capacity.zoneId)
										}
									}}
									className="text-zinc-500 hover:text-red-400"
								>
									Delete
								</button>
							</div>
						</div>
					)
				})}
			</div>

			{adding ? (
				<form onSubmit={handleAdd} className="mt-3 rounded-lg border border-zinc-800 p-3">
					{availableZones.length > 0 ? (
						<select name="zoneId" required defaultValue="" className={smallInputClass}>
							<option value="" disabled>Choose a zone…</option>
							{availableZones.map((z) => <option key={z.zoneId} value={z.zoneId}>{z.name}</option>)}
						</select>
					) : (
						<p className="rounded-lg border border-dashed border-zinc-700 px-2.5 py-1.5 text-xs text-zinc-500">
							Every zone already has a capacity assigned.
						</p>
					)}
					<input name="capacityKw" type="number" step="1" min="1" required placeholder="Capacity kW" className={`mt-2 w-full tabular-nums ${smallInputClass}`} />
					<ErrorBox error={createCapacity.error} />
					<div className="mt-2 flex justify-end gap-2">
						<button type="button" onClick={() => setAdding(false)} className="text-xs text-zinc-500 hover:text-zinc-300">Cancel</button>
						<button type="submit" disabled={createCapacity.isPending || availableZones.length === 0} className={`${btnPrimary} px-3 py-1 text-xs`}>
							{createCapacity.isPending ? 'Adding…' : 'Add zone'}
						</button>
					</div>
				</form>
			) : (
				<button type="button" onClick={() => setAdding(true)} className="mt-3 w-full rounded-lg border border-dashed border-zinc-700 py-2 text-xs font-medium text-zinc-500 hover:border-zinc-500 hover:text-zinc-300">
					+ Add zone capacity
				</button>
			)}
		</ModalShell>
	)
}
