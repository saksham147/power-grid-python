import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './api'

export const customerKeys = {
	demand: ['customer', 'demand'],
	zones: ['customer', 'zones'],
	units: ['customer', 'units'],
}

/** Ticks every 5 real seconds, same cadence as Producer. */
export function useDemand() {
	return useQuery({
		queryKey: customerKeys.demand,
		queryFn: () => request('/api/customer/demand/'),
		refetchInterval: 5000,
		retry: false,
	})
}

/** Zone configuration changes rarely compared to demand, but 5s keeps a fresh
 *  add/edit/delete visible without a manual refresh. */
export function useZones() {
	return useQuery({
		queryKey: customerKeys.zones,
		queryFn: () => request('/api/customer/zones/'),
		refetchInterval: 5000,
		retry: false,
	})
}

/** Every unit, each with its live demand. */
export function useUnits() {
	return useQuery({
		queryKey: customerKeys.units,
		queryFn: () => request('/api/customer/units/'),
		refetchInterval: 5000,
		retry: false,
	})
}

function useRefreshingMutation(mutationFn, onSuccess) {
	const qc = useQueryClient()
	return useMutation({
		mutationFn,
		onSuccess: (...args) => {
			qc.invalidateQueries({ queryKey: customerKeys.zones })
			qc.invalidateQueries({ queryKey: customerKeys.units })
			qc.invalidateQueries({ queryKey: customerKeys.demand })
			onSuccess?.(...args)
		},
	})
}

export const useCreateZone = (onSuccess) =>
	useRefreshingMutation((body) => request('/api/customer/zones/', { method: 'POST', data: body }), onSuccess)
export const useUpgradeZone = (onSuccess) =>
	useRefreshingMutation(
		({ zoneId, ...body }) => request(`/api/customer/zones/${zoneId}/`, { method: 'PUT', data: body }),
		onSuccess,
	)
export const useDeleteZone = (onSuccess) =>
	useRefreshingMutation((zoneId) => request(`/api/customer/zones/${zoneId}/`, { method: 'DELETE' }), onSuccess)

export const useCreateUnit = (onSuccess) =>
	useRefreshingMutation((body) => request('/api/customer/units/', { method: 'POST', data: body }), onSuccess)
export const useUpgradeUnit = (onSuccess) =>
	useRefreshingMutation(
		({ unitId, ...body }) => request(`/api/customer/units/${unitId}/`, { method: 'PUT', data: body }),
		onSuccess,
	)
export const useDeleteUnit = (onSuccess) =>
	useRefreshingMutation((unitId) => request(`/api/customer/units/${unitId}/`, { method: 'DELETE' }), onSuccess)
