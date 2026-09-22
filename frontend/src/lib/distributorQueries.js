import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './api'

export const distributorKeys = {
	status: ['distributor', 'status'],
	zoneCapacities: ['distributor', 'zoneCapacities'],
}

/** Distributor has no clock of its own; it reacts to each zone-demand event as it
 *  arrives, so this polls at the same 1s cadence as Grid rather than the slower 5s
 *  tick cadence. */
export function useDistributionStatus() {
	return useQuery({
		queryKey: distributorKeys.status,
		queryFn: () => request('/api/distributor/status/'),
		refetchInterval: 1000,
		retry: false,
	})
}

/** Each row carries its own currentDemandKw/overCapacity, live off GridStateTracker --
 *  1s cadence matches useDistributionStatus so the two never visibly disagree. */
export function useZoneCapacities() {
	return useQuery({
		queryKey: distributorKeys.zoneCapacities,
		queryFn: () => request('/api/distributor/zones/'),
		refetchInterval: 1000,
		retry: false,
	})
}

function useRefreshingMutation(mutationFn, onSuccess) {
	const qc = useQueryClient()
	return useMutation({
		mutationFn,
		onSuccess: (...args) => {
			qc.invalidateQueries({ queryKey: distributorKeys.zoneCapacities })
			onSuccess?.(...args)
		},
	})
}

export const useCreateZoneCapacity = (onSuccess) =>
	useRefreshingMutation((body) => request('/api/distributor/zones/', { method: 'POST', data: body }), onSuccess)

export const useUpdateZoneCapacity = (onSuccess) =>
	useRefreshingMutation(
		({ zoneId, ...body }) => request(`/api/distributor/zones/${zoneId}/`, { method: 'PUT', data: body }),
		onSuccess,
	)

export const useDeleteZoneCapacity = (onSuccess) =>
	useRefreshingMutation((zoneId) => request(`/api/distributor/zones/${zoneId}/`, { method: 'DELETE' }), onSuccess)
