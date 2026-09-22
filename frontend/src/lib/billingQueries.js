import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './api'

export const billingKeys = {
	wallets: ['billing', 'wallets'],
	wallet: (zoneId) => ['billing', 'wallets', zoneId],
	unlocks: ['billing', 'unlocks'],
	summary: ['billing', 'summary'],
	history: (zoneId) => ['billing', 'zones', zoneId, 'history'],
	transactions: (zoneId) => ['billing', 'zones', zoneId, 'transactions'],
}

// Billing has no clock of its own either -- see distributorQueries -- so most reads
// here poll at the same 1s cadence as Grid/Distributor rather than the slower 5s tick
// cadence. Money flow (billing.flow) has no backend counterpart in this port yet, so
// there is no useMoneyFlow here the way the reference has one.

export function useWallets() {
	return useQuery({
		queryKey: billingKeys.wallets,
		queryFn: () => request('/api/billing/wallets/'),
		refetchInterval: 1000,
		retry: false,
	})
}

/** One zone's wallet directly, for a lookup by id rather than filtering the full
 *  list -- 404s (via ApiError) for a zone that has never been billed. */
export function useWallet(zoneId, enabled) {
	return useQuery({
		queryKey: billingKeys.wallet(zoneId),
		queryFn: () => request(`/api/billing/zones/${zoneId}/wallet/`),
		enabled,
		refetchInterval: 1000,
		retry: false,
	})
}

/** Polls at the same cadence as useWallets -- unlocks change only as slowly as
 *  cumulative kWh sold, but there's no separate "something changed" signal. */
export function useUnlocks() {
	return useQuery({
		queryKey: billingKeys.unlocks,
		queryFn: () => request('/api/billing/unlocks/'),
		refetchInterval: 1000,
		retry: false,
	})
}

export function useBillingSummary() {
	return useQuery({
		queryKey: billingKeys.summary,
		queryFn: () => request('/api/billing/summary/'),
		refetchInterval: 1000,
		retry: false,
	})
}

/** Fetched only while a zone's history panel is open, same gating as
 *  producerQueries.usePlantHistory. */
export function useZoneHistory(zoneId, enabled) {
	return useQuery({
		queryKey: billingKeys.history(zoneId),
		queryFn: () => request(`/api/billing/zones/${zoneId}/history/`, { params: { limit: 50 } }),
		enabled,
		refetchInterval: 5000,
		retry: false,
	})
}

/** Fetched only while a zone's transaction panel is open. */
export function useZoneTransactions(zoneId, enabled) {
	return useQuery({
		queryKey: billingKeys.transactions(zoneId),
		queryFn: () => request(`/api/billing/zones/${zoneId}/transactions/`, { params: { limit: 50 } }),
		enabled,
		refetchInterval: 5000,
		retry: false,
	})
}

function useWalletMutation(mutationFn, onSuccess) {
	const qc = useQueryClient()
	return useMutation({
		mutationFn,
		onSuccess: (...args) => {
			qc.invalidateQueries({ queryKey: billingKeys.wallets })
			onSuccess?.(...args)
		},
	})
}

/** A failed purchase (402 insufficient funds, 403 locked type) rejects the mutation
 *  rather than silently succeeding, so a caller must explicitly decide what to do
 *  next. The resolved value carries the server-computed amountRupees actually
 *  charged. */
export const usePurchasePlant = (onSuccess) =>
	useWalletMutation((body) => request('/api/billing/plants/purchase/', { method: 'POST', data: body }), onSuccess)

/** Same shape as usePurchasePlant, for the extra charge an upgrade costs. */
export const useUpgradePlantCost = (onSuccess) =>
	useWalletMutation((body) => request('/api/billing/plants/upgrade/', { method: 'POST', data: body }), onSuccess)

/** Credits a decommission refund. Never rejects for insufficient funds -- a credit
 *  can't fail -- so callers only need to handle network/validation errors. */
export const useDecommissionPlant = (onSuccess) =>
	useWalletMutation((body) => request('/api/billing/plants/decommission/', { method: 'POST', data: body }), onSuccess)
