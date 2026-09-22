import axios from 'axios'

// One shared fetch wrapper for every backend call this app makes. The reference
// project keeps a near-identical copy of this per service (api.js, gridApi.js,
// distributorApi.js, customerApi.js, billingApi.js, storageApi.js) because each one
// is a separate origin behind its own Vite proxy prefix. This project has one Django
// origin behind one /api/ prefix, so there is nothing per-service left to duplicate --
// every domain's lib/*Queries.js calls this same request() directly.
//
// Built on axios rather than fetch: axios auto-serializes a plain object passed as
// `data` (and sets the JSON content-type itself), so a caller never has to
// JSON.stringify a body or pass its own headers by hand.

/** Carries the backend's own wording so the UI never invents an error message. */
export class ApiError extends Error {
	constructor(message, { status = 0, details = [] } = {}) {
		super(message)
		this.status = status
		this.details = details
	}
}

export async function request(path, config) {
	try {
		const res = await axios(path, config)
		return res.status === 204 ? null : res.data
	} catch (err) {
		if (!err.response) {
			// No response at all: the network failed, the backend is down, or the
			// request never left (axios sets `request` but not `response` here).
			throw new ApiError('Cannot reach the server.', { status: 0 })
		}

		// The backend replies with an ApiError-shaped body ({message, details, ...});
		// a proxy or a dead server in between replies with plain text, which axios
		// leaves as a string when it can't parse it as JSON. Only trust an object.
		const body = err.response.data
		const parsed = body && typeof body === 'object' ? body : null
		throw new ApiError(parsed?.message ?? `Request failed (${err.response.status})`, {
			status: err.response.status,
			details: parsed?.details ?? [],
		})
	}
}
