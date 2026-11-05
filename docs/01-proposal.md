# Order Checking System — Pre-Development Proposal

Status: **Draft for approval** · Date: 2026-11-05
Source analyzed: `order_check_2026-11-03T08_28_53.726026+03_30.xlsx` (sheet `Query result`)

---

## 0. Decisions from review (2026-11-05) — these override anything below

| Topic | Decision |
|---|---|
| `physical_stock` | It is the stock **after** this order. `0` is normal and is **not** a shortage signal. Stored and shown as info only; no pre-flagging. |
| PDA hardware | New Urovo PDA (model unknown). Scanner layer must be **universal**: configurable broadcast action + extra key with presets (Urovo, Zebra DataWedge, Honeywell, Newland, iData, Sunmi, Chainway), plus keyboard-wedge fallback. Urovo preset is the default. |
| What is scanned | The **unit barcode** (EAN-13) printed on the product/carton. **1 scan = 1 box** regardless. No carton GTIN handling needed. |
| Loose units | Do not occur. No loose-unit entry. Quantities are whole boxes; units = boxes × inc. |
| Pick completion | Out of scope. Picking and checking are separate tasks. Shortages are declared by the checker ("Not found") or at **Finish**. Pickers fix their own mistakes; the app only records them. |
| Hosting | Your own server, good Wi-Fi. Deployed with Docker Compose. PDA still tolerates short drops (local queue + retry). |
| Stack | My choice → Django + DRF + PostgreSQL, React + Ant Design, native Kotlin + Compose. |
| Picker | Will be filled in the order export. Used for the **picker report** (shortages, extras, not-in-order items per picker). |
| Barcode mapping file | Columns: `product_id`, `barcode`, `title`. |
| Extras | Recorded only; no return-to-stock step. |
| Debounce & clocks (found in testing) | Scanner double-reads are decided **only on the PDA** (monotonic clock, 700 ms) and sent flagged `duplicate`; the server never re-decides from timestamps. PDA clock skew is corrected per batch (`sent_at`). |
| Repaired barcodes (found in real data) | A repaired 12-digit barcode is dropped if it equals another product's real barcode (11596 `261182000552` vs 11590 `6261182000552`); real barcodes always win at scan time. |
| **Not-in-order items and over-scans** | Extra boxes **cannot be shipped**. Any scan that is not in the order, or exceeds the ordered quantity, triggers a **blocking red warning + alarm** with two big buttons: **"Removed from pallet"** (recorded as an extra discrepancy, attributed to the picker) or **"Scanned by mistake"** (undo, recorded as duplicate scan). Further scans are rejected with an error tone until the checker answers. This replaces the 5-second Undo banner for extras and also handles accidental double scans. Shipped quantity therefore never exceeds the ordered quantity. |

---

## 1. What the Excel template tells us

| Fact | Value | Design consequence |
|---|---|---|
| Orders per file | **3** (16638, 16639, 16640) in one sheet | Import is *multi-order per file*; group rows by `reference_id`. |
| Lines per order | 223 / 195 / 594 | Must render 600-line lists smoothly on a PDA (virtualized lists, local DB). |
| Boxes per order | 244 / 221 / 607 | ~1 scan per line. Order ≈ 200–600 scans. |
| `pack_ordered` distribution | **995 of 1012 lines = 1 box**; the rest 2–10 (all water / soft drinks) | Almost every line is finished by a single scan → **a second scan of the same barcode is almost always either an accident or a real extra.** This drives duplicate-scan design (§4). |
| `units_ordered = pack × inc` | Holds on **all** 1012 rows | Validation rule is safe to enforce as an error. |
| `packs_picked`, `units_picked` | **All 0** | Export is taken *before* picking. Picked quantities are not available at import time (see Q4). |
| `picker`, `label` | **All empty** | Picker-level error reports impossible unless picker is filled later (see Q7). |
| Duplicate (order, product) rows | 0 | Enforce unique (order, product); if it ever happens, merge or reject (configurable). |
| `physical_stock = 0` | **57 lines** (10 / 10 / 37) | ~~Pre-flag as likely shortage~~ — *superseded (§0): it is post-order stock, informational only.* |
| Same barcode on 2+ products | 0 in this file | Still must be handled (central mapping will have conflicts). |
| `inc_ordered` per product | Constant across orders in this file | Still store `inc` **per order line** (pack sizes change over time). |
| `created_at` | `2026-11-02 22:12:51`, no timezone | Interpret as Asia/Tehran, store as UTC. |
| `reference_type` | Only `TransferRequest` | Keep as free field; uniqueness key = (`reference_type`, `reference_id`). |
| Product titles | 64 contain Arabic ي / ك; 55 contain Latin text | Normalize ي→ی, ك→ک for search; titles are mixed-direction text. |
| Aisle codes | `C-1-26`, `A08-…`, `سردخانه-…` (cold room) | Aisle is mixed Latin/Persian — render as isolated LTR token. |

### Barcode quality findings (important)

Of 1,178 distinct barcodes, 1,159 are 13-digit EAN-13. The rest:

| Example | Product | Problem | Handling |
|---|---|---|---|
| `123456` | Pepsi Max 1.5 L (barcode4) | Placeholder/junk | Import **warning**; never used for matching (min-length + blocklist). |
| `626017023008`, `626005580097`, `626054350262`, `626391670039`, `626760441162`, `626168480206`, `261182000552` | various | 12 digits starting `626…` — looks like **EAN-13 with the check digit cut off**. A scanner will read 13 digits and **will not match**. | On import, if a 12-digit value fails UPC-A check but `626…`, also index the computed 13-digit EAN. Flag for review. |
| `012000800443` | Pepsi 250 ml | Real UPC-A | Normalize UPC-A ↔ EAN-13 (`0` + UPC-A) so either scanner output matches. |
| `62600055800466` | Pepsi 250 ml | 14-digit GTIN-14 — **likely the carton (case) barcode** | Matches the "1 scan = 1 box" model well; see Q2. |
| `2162231168480006`, `2162410606110028`, `167110000240026`, `10162130010870033` | tissues, cotton, rice flour, jam | 15–17 digit internal/restricted-circulation codes | Accept as opaque strings; exact match only. |
| `3901780102`, `3901748849`, `11201045` | lentils, energy drink, tuna | 8–10 digit codes (EAN-8 / internal) | Accept; exact match. |

**Normalization pipeline (applied identically on import and on scan):** strip whitespace/control chars and AIM symbology prefixes → convert Persian/Arabic digits to ASCII → if GS1-128/DataMatrix with AI `(01)`, extract GTIN → UPC-A/EAN-13/GTIN-14 leading-zero canonicalization → exact lookup.

---

## 2. Missing business rules (need your decision)

| # | Gap | Proposed default |
|---|---|---|
| R1 | **Scanned product exists but is not in the order** (wrong item picked). Spec only covers "unidentified barcode". | Add it as an *unordered line* (ordered = 0) → goes straight to "With Issue" as *Extra / not in order*. Different sound from unknown barcode. |
| R2 | **When is a shortage declared?** Pallets keep arriving while picking continues; a missing box may simply not have arrived yet. | Partially scanned lines stay in "Items to Check". Shortages are declared only by (a) an explicit "Not found" swipe on a line, or (b) the **Finish** step, which moves all remaining lines to "With Issue" as shortages. |
| R3 | **Loose units / opened cartons** (e.g. 7 units of a 12-pack). Scan = box can't express this. | Allow entering *loose units* on a line from the issue screen (numeric pad). Backend stores boxes and units separately; units = boxes × inc + loose. |
| R4 | **Pack size mismatch** (supplier carton now holds 10, order says 12). | Discrepancy type `INC_MISMATCH` with actual inc entered; unit shortage computed. |
| R5 | **Substitution** (different SKU/flavor sent instead). | Recorded as shortage on ordered line + extra on unordered line; optional "link as substitute". |
| R6 | **Damaged / expired boxes** found during check. | Reason codes; counts as scanned-but-rejected → shortage on that line. |
| R7 | **Re-import of an order that changed** in the source system. | Same file hash → reject. Same `reference_id`, different content: if not started → new *version* replaces lines (old kept for audit); if started → blocked, supervisor sees a diff and decides. |
| R8 | **Reassignment while the old PDA is offline** with unsynced scans. | Scans carry `assignment_id`. Scans made *before* revocation time are accepted (they physically happened) and attributed to the old checker; the old PDA locks the order on next sync. |
| R9 | **Reopening a completed order.** | Supervisor/Admin only, mandatory note, audited; status returns to In Progress. |
| R10 | **Cancelling an order mid-check.** | Supervisor only; PDA locks it; data kept. |
| R11 | **Unknown barcode** — spec says "show error". What then? | Error + log the barcode on the order. Checker can attach it to a product by name search (needs supervisor approval to enter the central mapping). Supervisors see an "unknown barcodes" queue. |
| R12 | **Checking duration** inflated by breaks / waiting for pallets. | Report both *elapsed* (first scan → completion) and *active* time (gaps > 5 min excluded, configurable). Productivity uses active time. |
| R13 | **Can a checker hold several orders at once?** | Yes, multiple assigned, but only one *open* on the PDA at a time. |
| R14 | **Who is "responsible" for a shortage** — picker or stock? | Reason codes carry a category (Stock / Picking / Other) so reports can split them. Requires `picker` filled (Q7). |

---

## 3. Edge cases in the scanning workflow

1. Scanner double-decode (same physical box read twice within milliseconds).
2. Trigger held → continuous-mode scanner reads the same box repeatedly.
3. Box scanned twice by mistake seconds later (the dominant risk: 98% of lines are 1 box).
4. Legitimate fast repeat scans of a 10-box water line.
5. Barcode matches a product in another order assigned to the same checker → must **not** be counted on the open order; treated as "not in this order".
6. Barcode maps to two products in the central mapping → resolve within the order first (order-scoped match wins); if both/neither are in the order → ambiguity prompt.
7. Barcode found only in central mapping and its product is in the order under a different barcode → match (that's the point of the mapping).
8. Damaged/unreadable label → manual search by product name / last digits.
9. Scan arrives while a dialog is open → must never be lost or mis-applied.
10. Network drop mid-order; app killed; battery swap; device reboot → zero data loss.
11. Scan made after order completion → rejected with clear "order locked" feedback.
12. Same scan event retried by sync → server must not double count.
13. Checker logs in on a different PDA mid-order → server state reconciles.
14. Over-scan on a line that already has a recorded shortage reason → reason must be re-evaluated.

---

## 4. Duplicate-scan protection (recommended design)

Layered, none of which slows normal scanning:

1. **Hardware config:** scanner in *single-trigger* mode (not continuous/presentation mode), delivered via **broadcast intent** (not keyboard wedge). Eliminates cases 1–2 at the source.
2. **Debounce:** identical barcode within **700 ms** (configurable) is ignored and logged as `DUPLICATE_IGNORED`. A human cannot pick up and scan a *second* box in < 700 ms, so legitimate scans are unaffected.
3. **Over-quantity guard (the real protection):** a scan that would exceed the ordered quantity is recorded as **Extra**, with a distinct alarm sound + red flash + vibration, and a big **Undo** button on the result banner for 5 s. No confirmation dialog in the normal path; one tap fixes an accident.
   *Optional strict mode (per config):* extras are held as "pending" until confirmed by a tap.
4. **Idempotency:** every scan has a client-generated UUID; server ignores replays (edge case 12).
5. **Audit:** undo is itself an event (never a delete), so duplicates and their corrections are visible in reports per checker.

---

## 5. Recommendations to maximize checking speed

1. **Local-first scanning.** The PDA holds the full order + all barcodes for its products + a cached copy of the central barcode mapping (delta-synced). Every scan resolves locally in < 50 ms; network is never in the scan path.
2. **One screen, no navigation.** Scanning works from any tab; a large "last scan" card at the top shows product, `scanned / ordered`, and remaining. Tabs update live.
3. **Distinct audio per outcome:** line complete ✓, partial (more boxes expected), extra, not-in-order, unknown, locked. Checker doesn't need to look at the screen for the normal case.
4. ~~Pre-flag likely shortages~~ — dropped (§0).
5. **Bulk reasoning at Finish:** multi-select shortages → one reason → done. Typical order with 10 zero-stock lines = 3 taps instead of 30.
6. **Prefetch on assignment:** order downloads to the PDA as soon as it's assigned, so opening is instant.
7. **Items to Check** sorted by `aisle_rank` by default (matches pallet build order roughly) with optional sort by "recently scanned" — never enforced.
8. **Manual fallback** for unreadable labels: numeric keypad barcode entry and Persian/English name search with ی/ک normalization.
9. **Progress header:** lines OK / issues / remaining, boxes scanned / ordered.

---

## 6. Proposed architecture

```
 ┌──────────────── PDA (Android) ────────────────┐         ┌───────────── Server (Docker) ─────────────┐
 │ Kotlin + Jetpack Compose (RTL native)         │  HTTPS  │ API: Django + Django REST Framework       │
 │ Scanner adapter layer:                        │ ──────► │  • Auth (JWT access + refresh, device id) │
 │   Zebra DataWedge │ Honeywell │ Urovo │       │  JSON   │  • RBAC (role → permissions table)        │
 │   Newland │ Sunmi │ keyboard-wedge fallback   │ ◄────── │  • Import service (openpyxl, profiles)    │
 │ Room (SQLite) local DB = order, lines,        │         │  • Barcode resolution service             │
 │   barcodes, outbox of scan events             │         │  • Scan event ingest (idempotent)         │
 │ WorkManager background sync + retry           │         │  • Reporting (SQL + daily rollups)        │
 │ SoundPool audio, vibration                    │         │  • Audit log                              │
 └───────────────────────────────────────────────┘         │ PostgreSQL 16 (+ nightly dump + WAL/PITR) │
 ┌──────────── Admin Panel (browser) ────────────┐         │ Nginx (TLS, static web panel)             │
 │ React + TypeScript + Vite                     │ ──────► └───────────────────────────────────────────┘
 │ Ant Design 5 (built-in RTL + fa_IR locale)    │
 │ dayjs + jalali plugin, Vazirmatn font         │
 │ TanStack Query (10 s polling for monitoring)  │
 └───────────────────────────────────────────────┘
```

### Technology evaluation

| Decision | Choice | Why (warehouse suitability) | Rejected alternative |
|---|---|---|---|
| PDA app | **Native Kotlin + Compose** | Scanner SDKs/intents are Android-native; lowest scan latency; Room + WorkManager are the most reliable offline/sync primitives; native RTL; runs on Android 8+ PDAs. | Flutter/React Native: workable, but every scanner vendor still needs native bridge code, plus extra runtime overhead on low-end PDAs. PWA/web: no reliable scanner intents, weak offline, browser kills. |
| Scanner input | **Broadcast intent** per vendor, keyboard wedge as fallback | Wedge depends on input focus, can be affected by IME/RTL, can inject into wrong field. Intents deliver symbology + raw data reliably. | Camera scanning: too slow for 600 scans. |
| Backend | **Django + DRF** (Python) | Strong Excel tooling, mature auth/permissions, migrations, admin for emergency data fixes, `jdatetime` for Jalali, fast to build and easy to hire for. Load is tiny (tens of checkers, ~1 scan/s each). | Node/NestJS or .NET are equally viable — **choose whatever your team maintains** (Q6). |
| Database | **PostgreSQL 16** | Transactions + partial unique indexes enforce "one active assignment per order" and "one active owner per barcode" at DB level; JSONB to keep raw import rows; strong reporting SQL. | MySQL: weaker partial indexes. NoSQL: integrity rules matter more than schema flexibility here. |
| Web UI | **React + Ant Design 5** | First-class `direction="rtl"`, fa_IR locale, dense tables for 600-line orders. | |
| Real-time | **Polling (10 s)** | Enough for supervisor dashboards; no extra infra. WebSockets can be added later. | |
| Deployment | **Docker Compose** on one server (on-prem or cloud, Q5) | Simple to run, back up and restore. | Kubernetes: unnecessary at this scale. |

### Sync model (PDA ⇄ server)

- Server is the source of truth; **scan events are an append-only log**; line quantities are derived.
- PDA applies a scan locally, writes an event to the **outbox**, and pushes in the background (batched, retried with backoff). Each event has a UUID → server dedupes.
- Server responds with authoritative line state; PDA reconciles.
- **Finish/Complete requires online** so the server validates completion rules and locks the order atomically.
- On revocation (reassign/cancel) the server rejects new events after `revoked_at` and the PDA locks the order.

---

## 7. Proposed database schema (PostgreSQL)

```
users            id, username UNIQUE, full_name, password_hash, role_id, language('fa'|'en'),
                 is_active, last_login_at, created_at
roles            id, code ('admin','supervisor','checker'), name_fa, name_en
permissions      id, code ('orders.import','orders.assign','reasons.manage',...)
role_permissions role_id, permission_id
devices          id, serial UNIQUE, model, app_version, last_seen_at, last_user_id

customers        id, name, name_normalized UNIQUE
products         id (= source product_id), title, title_en, title_normalized, updated_at
barcodes         id, barcode_normalized, product_id, source('order_import'|'mapping_file'|'manual'),
                 is_active, valid_from, valid_to, created_by, created_at, import_batch_id
                 -- UNIQUE (barcode_normalized) WHERE is_active   ← no duplicates, history kept
                 -- INDEX (product_id)

import_profiles  id, kind('orders'|'barcodes'), name, column_map JSONB,
                 barcode_column_pattern ('^barcode\d+$'), is_default
                 -- lets the Excel structure change without code changes
import_batches   id, kind, file_name, file_sha256 UNIQUE, stored_path, profile_id, uploaded_by,
                 uploaded_at, status('validated'|'committed'|'rejected'), rows_total, rows_error,
                 orders_created, orders_updated
import_rows      id, batch_id, row_no, raw JSONB, errors JSONB, warnings JSONB, order_line_id NULL
                 -- original data preserved verbatim for audit

orders           id, reference_type, reference_id, version, customer_id, picker_name,
                 source_created_at, import_batch_id, status, current_assignment_id NULL,
                 first_scan_at, completed_at, completed_by, cancelled_at, cancelled_by,
                 lines_total, boxes_ordered, boxes_scanned, open_issues   -- cached counters
                 -- UNIQUE (reference_type, reference_id)
                 -- status: PENDING_ASSIGNMENT | ASSIGNED | IN_PROGRESS | COMPLETED | CANCELLED
                 --  ("Reassigned" is recorded as an assignment event, not a status, so the
                 --   order stays IN_PROGRESS/ASSIGNED with full history)
order_lines      id, order_id, product_id, title_snapshot, aisle_title, aisle_rank,
                 pack_ordered, inc_ordered, units_ordered, packs_picked, units_picked,
                 physical_stock, label, extra JSONB, is_unordered BOOL,
                 boxes_scanned, loose_units, inc_actual NULL,
                 state('PENDING'|'PARTIAL'|'OK'|'SHORT'|'EXTRA'|'MISMATCH'),
                 issue_status('NONE'|'OPEN'|'REASONED'|'RESOLVED'), row_version
                 -- UNIQUE (order_id, product_id)
order_line_barcodes  order_line_id, order_id, barcode_normalized   -- snapshot from import file
                 -- INDEX (order_id, barcode_normalized)  ← priority-1 lookup

assignments      id, order_id, checker_id, assigned_by, assigned_at,
                 revoked_at, revoked_by, revoke_reason
                 -- UNIQUE (order_id) WHERE revoked_at IS NULL   ← never two active checkers

scan_events      id UUID (client-generated PK → idempotent), order_id, order_line_id NULL,
                 assignment_id, checker_id, device_id, raw_barcode, barcode_normalized,
                 match_source('order'|'mapping'|'none'), result('COUNTED'|'EXTRA'|'NOT_IN_ORDER'|
                 'UNKNOWN'|'DUPLICATE_IGNORED'|'LOCKED'|'UNDO'), delta_boxes (+1/-1/0),
                 undoes_event_id NULL, scanned_at (device clock), received_at (server clock)
                 -- INDEX (order_id, scanned_at), (checker_id, scanned_at)

discrepancy_reasons  id, code, name_fa, name_en, applies_to('SHORT'|'EXTRA'|'BOTH'),
                 category('STOCK'|'PICKING'|'SCANNING'|'OTHER'), requires_note, is_active, sort_order
discrepancies    id, order_line_id, type('SHORT'|'EXTRA'|'NOT_IN_ORDER'|'INC_MISMATCH'),
                 qty_boxes, qty_units, reason_id NULL, note, status('OPEN'|'REASONED'|'RESOLVED'),
                 created_by, created_at, updated_by, updated_at, resolved_by, resolved_at
line_corrections id, order_line_id, field, old_value, new_value, reason_id, user_id, at

audit_log        id, at, user_id, device_id, ip, entity_type, entity_id, action,
                 before JSONB, after JSONB
checker_daily_stats  (date, checker_id) → orders, lines, boxes, scans, extras, shortages,
                 undo_count, active_seconds   -- rollup for fast reports
```

**Quantities:** all stored as integers in boxes and units; units always derived as `boxes × inc + loose_units`. **Dates:** `timestamptz` (UTC); Jalali conversion happens only in the UI.

**Barcode resolution order (per scan):** `order_line_barcodes` for this order → active `barcodes` mapped to a product *that is in this order* → active `barcodes` for any product (→ NOT_IN_ORDER) → UNKNOWN. Adding a new mapping never rewrites existing orders but immediately helps resolution.

---

## 8. User flows

### 8.1 Admin panel

**Import orders (Supervisor)**
1. Upload `.xlsx` → server hashes the file (duplicate file rejected) → parses with active import profile.
2. **Preview screen:** orders found, lines per order, errors (blocking) and warnings (non-blocking, e.g. `123456` barcode, 12-digit barcode, zero stock), and per-order status *New / Unchanged / Changed-not-started / Changed-started (blocked)*.
3. Supervisor commits → orders created as **Pending Assignment**.

**Assign (Supervisor)**
1. Orders list filtered to *Pending Assignment* → select one or many → choose checker → assign. PDA receives it on next sync.
2. Reassign: from order detail → choose new checker + reason → previous assignment revoked; progress preserved; audit entry.

**Monitor (Supervisor)** — live board: waiting / assigned-not-started / in progress (progress bar, checker, elapsed) / with open issues / completed today.

**Order detail** — header + 3 views mirroring the PDA tabs + scan timeline + assignment history + audit; reopen / cancel actions with mandatory note.

**Reasons (Admin/Supervisor)** — CRUD, activate/deactivate, applies-to, category, FA/EN names, order.

**Barcode mapping** — upload mapping file (preview, conflicts shown: barcode already owned by another product → choose keep/replace), search product → see active + historical barcodes, approve barcodes proposed from PDA.

**Users** — create/edit/deactivate, role, reset password, activity (last login, device, scans today).

**Reports** — Overall / Checker / Operational tabs; filters: Daily, Weekly, Monthly, Custom (Jalali pickers), checker, order, status; export to Excel.

### 8.2 PDA app

```
Login (username + PIN, numeric keypad)  ─►  My Orders
                                             • ref, store, SKUs, boxes, progress bar, status
                                             • tap order ─► Checking screen
Checking screen
 ┌───────────────────────────────────────────────┐
 │ 16638 · سوپرمارکت نمونه        ✓180  ⚠6  ○37 │  ← progress header
 │ ┌───────────────────────────────────────────┐ │
 │ │ LAST SCAN: پپسی نوشابه مکس 1.5 لیتر        │ │  ← big colored card
 │ │ 2 / 2 boxes ✓        [ Undo ]              │ │
 │ └───────────────────────────────────────────┘ │
 │ [ To Check 37 ] [ No Issue 180 ] [ Issue 6 ]  │
 │  … virtualized list …                         │
 │                               [ Finish ]      │
 └───────────────────────────────────────────────┘
```

- **Scan** anywhere on this screen → local resolve → sound + card + tab counts update. No product pre-selection.
- **To Check row** → swipe/long-press "Not found" → becomes shortage in Issue tab.
- **Issue row** → bottom sheet: ordered vs scanned (boxes + units), shortage/extra, reason chips (large), optional loose units / actual inc / note, *Save*. Multi-select for bulk reason.
- **Finish** → remaining lines are listed as shortages → bulk reason → server validates rules (§ spec 6) → **Completed**, order locked, back to My Orders.
- Offline indicator + pending-event count always visible; nothing blocks scanning while offline.
- Language switch (FA default / EN) in settings; barcodes, aisle codes and numbers always rendered as isolated LTR.

---

## 9. RTL / Persian specifics

- Default `fa`, toggle to `en`; all strings in resource files (Android `values-fa`, web i18n JSON).
- Font: **Vazirmatn** (open license) in both apps.
- Barcodes, aisle codes, reference IDs: wrapped in LTR isolation (`<bdi dir="ltr">` on web, `⁦…⁩` / `TextDirectionHeuristics.LTR` on Android). Never Persian digits inside barcodes.
- Quantities: Persian digits optional per user setting (default: Persian digits for quantities, Latin for codes).
- Jalali dates in UI (`dayjs-jalali` web, `PersianCalendar` / ICU on Android), UTC in DB and API.
- Search normalization: ي→ی, ك→ک, ZWNJ/whitespace folding, Persian→ASCII digits.

---

## 10. Delivery stages

| Stage | Scope | Exit test |
|---|---|---|
| 0 | Repo, Docker Compose, CI, DB migrations | `docker compose up` gives empty working stack |
| 1 | Backend core: auth/RBAC, schema, Excel import + validation + preview, barcode mapping import, resolution service | Import the provided file: 3 orders, 1,012 lines, warnings for `123456` and 12-digit codes; unit tests for every rule in §2–§4 |
| 2 | Admin panel: login, import UI, orders, assignment/reassignment, reasons, users, barcode mapping — RTL + Jalali | Supervisor end-to-end on the sample file |
| 3 | PDA app: login, order list, offline store + sync, scanner adapters, scanning engine, 3 tabs, discrepancies, Finish | Full order checked on a real PDA incl. airplane-mode test and kill/restart test |
| 4 | Reports & live monitoring, Excel export | Numbers reconcile with raw scan events |
| 5 | Pilot on the floor, tuning (debounce, sounds), backups/restore drill | One shift of real orders |

---

## 11. Open questions (blocking)

1. **PDA hardware:** brand/model and Android version (Zebra, Honeywell, Urovo, Newland, iData, Sunmi…)? Determines scanner integration.
2. **What is physically scanned on a box:** the carton's own barcode (GTIN-14/ITF-14, like `62600055800466`) or a unit's EAN-13 printed on the carton? Are there cartons with *no* barcode?
3. **Loose units / opened cartons:** does this happen in practice, and should the checker record them?
4. **Pick completion:** is there any signal that picking for an order is finished (would the picked columns be filled later, or a separate file)? Otherwise shortages are declared only at Finish.
5. **Hosting:** on-prem server in the warehouse or cloud? Wi-Fi coverage quality in the checking area?
6. **Team stack:** who will maintain this — is Python/Django acceptable, or does your team prefer Node/.NET/Go/PHP?
7. **Picker field:** will `picker` be filled in future exports? (Needed for picker-error reporting.)
8. **Barcode mapping file:** please share it when available (and its columns).
9. **Extras:** when an extra/not-in-order box is found, is it just recorded, or does it also need a "returned to stock" step?
