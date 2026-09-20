# Power-Grid → Django Port — Task List

One task per mini-module, as broken down in `Power-Grid/architecture-doc.html`. Each
task is "build this module's equivalent inside the Django `powergrid` project."
Grouped by service, in the same order as the architecture doc.

## Grid (time) — target: `grid` Django app

- [x] **simulation** — Canonical tick clock + auto-control loop. Port `SimulationClock`
      (tick↔time math), a tick runner, `FrequencyController` (AGC: nudge deviation
      toward zero), and in-memory `GridStateTracker` (latest total supply/demand).
      _Done as the project-level `simulation` app: clock, `runsimulation` tick runner,
      persisted `SimulationState`, `tick_advanced` signal, and the `compute_deviation`
      AGC formula. Not yet done: `GridStateTracker` and wiring AGC into the tick loop
      (needs fleet supply/demand from producer/distributor)._
- [ ] **kafka** — Publish the tick heartbeat every 5s; listen for Producer's output and
      Distributor's zone balance to feed `GridStateTracker`.
- [ ] **redis** — Persist current tick/day (e.g. Django cache or a singleton DB row) so
      a restart resumes time instead of resetting it.
- [ ] **api / api.dto** — `GET` status endpoint, `PUT` manual frequency-deviation
      override (bounded ±0.25 Hz, switches auto-control off), uniform error shape.
- [ ] **event / config** — Wire records/serializers for the tick, producer-output, and
      zone-balance payloads Grid produces/consumes.

## Producer (supply) — target: `producer` Django app

- [x] **simulation** — Tick loop driving generation forward; local copy of the
      canonical clock; autostart toggle.
- [x] **generation** — One output-curve strategy per plant type (Thermal droop,
      Solar diurnal+cloud+season curve, Wind front+gust+season curve).
- [x] **model** — `PowerPlant`, `PlantType`, `GenerationRecord` (raw per-tick history),
      `GenerationRollup` (compressed history), with their queries.
- [ ] **history** — Rollup job: keep raw output 24h, compress older rows into 1-minute
      buckets every 10 minutes; merged read query for charts.
- [ ] **kafka / event** — Publish one output event per active plant per tick.
- [ ] **api / api.dto** — Fleet CRUD (create/upgrade/activate/deactivate plant),
      simulation status read, output-history read.

## Customer (demand) — target: `customer` Django app

- [ ] **domain** — Framework-free core: `Zone`, `ConsumerUnit`, `DemandProfile` (24-point
      hourly curve + weekend factor per type), `DemandModel` (demand = capacity ×
      profile factor), `ZoneDemand`.
- [ ] **application** — Use case: sum each zone's units into a per-zone reading every
      tick, then publish and cache the result independently.
- [ ] **infrastructure.kafka** — React to the grid tick; publish per-zone demand,
      keyed by zone id.
- [ ] **infrastructure.redis** — Zones/units as key-value store entries (or Django
      cache); latest demand cached independent of the tick loop.
- [ ] **api** — Zone CRUD, consumer-unit CRUD, live per-zone demand read (joins cached
      demand against zone/unit config).

## Distributor (merge) — target: `distributor` Django app

- [ ] **distribution** — Merge use case: split total supply across zones proportional
      to each zone's demand share; zone-capacity admin use case (billing ceiling, not
      a hard delivery cap).
- [ ] **model** — `DistributionRecord` (raw per-zone balance), `ZoneCapacity` (admin
      config), `DistributionDailyRollup` (compressed history).
- [ ] **history** — Keep 15 simulated days raw, compress older rows into daily
      avg/min/max per zone.
- [ ] **kafka / event** — Consume producer output + zone demand; publish zone balance
      and zone-capacity-change events independently (one failing doesn't cost the
      other).
- [ ] **api / api.dto** — System-wide status snapshot; zone-capacity CRUD with a live
      over-capacity flag.

## Billing (money) — target: `billing` Django app

- [ ] **billing** — Billing-cycle use case: kWh × rate, overage above a zone's assigned
      capacity billed separately; voluntary-spend use case (plant/storage purchase,
      refusable on insufficient funds); server-side plant/storage pricing formula;
      unlock/tech-tree gating; in-memory mirror of Distributor's zone capacity.
- [ ] **model** — `Wallet` (current balance per zone + shared Grid wallet),
      `WalletTransaction` (insert-only ledger), `BillingRecord` (raw per-tick charge,
      unique per zone+tick as the idempotency guard), `BillingDailyRollup`.
- [ ] **history** — Same 15-simulated-day retention pattern, rows summed (not
      averaged) since kWh/₹ are additive.
- [ ] **kafka / event** — Two independent consumers: one bills off zone demand, one
      mirrors Distributor's capacity config.
- [ ] **api / api.dto** — Wallet/history/transaction reads, plant purchase/upgrade/
      decommission, storage purchase, unlock status, revenue-vs-spend summary.

## Database (storage) — target: shared Postgres schemas / cache keys

- [ ] **producer.\*** — `power_plant`, `generation_record`, `generation_rollup` tables
      (Producer-owned schema/tables).
- [ ] **distributor.\*** — `distribution_record`, `zone_capacity`,
      `distribution_daily_rollup` tables (Distributor-owned).
- [ ] **billing.\*** — `wallet`, `wallet_transaction`, `billing_record`,
      `billing_daily_rollup` tables (Billing-owned).
- [ ] **customer:\*** — Zones, units, latest-demand as cache/key-value entries
      (Customer-owned namespace).
- [ ] **grid:\*** — Current tick/day as a cache/key-value entry (Grid-owned namespace).

## Frontend (view) — target: templates / API consumers

- [ ] **lib/\*Api.js** — One thin fetch wrapper per backend origin (here: per Django
      app/API prefix) — the only place a raw URL or HTTP verb appears.
- [ ] **lib/\*Queries.js** — One data-fetching hook/helper per operation — polling
      interval and cache invalidation live here only.
- [ ] **lib/format.js** — Shared `kw`/`mw`/`rupees`/`time` formatters — every number the
      UI shows goes through exactly one of these.
- [ ] **Dashboard — nodes** — One card component per visual "thing" (service status,
      plant, zone, customer), each owning its own edit/delete affordances.
- [ ] **Dashboard — modals** — One create/edit/delete flow per entity, sharing one
      modal shell.
- [ ] **Dashboard — layout** — Turn live data into a node/edge graph fresh each render,
      with drag-to-reposition as a stateful override.
