# Order Checking System

Warehouse order-checking for a bulk FMCG distribution center: supervisors import
orders from Excel and assign them; checkers scan boxes on Android PDAs; the
system reconciles boxes/units, records discrepancies, and reports productivity.

Design and decisions: [docs/01-proposal.md](docs/01-proposal.md) (§0 holds the
decisions that override the rest).

| Part | Tech | Status |
|---|---|---|
| Backend / API | Django 5.2 + DRF, PostgreSQL 16 | **Stage 1 done** — import, barcode mapping, assignment, checking engine, PDA API |
| Admin panel | React 19 + Ant Design 6 (RTL, Persian default, Jalali) | **Stage 2 done** — live board, orders, assignment, imports, barcodes, reasons, users, permissions, audit |
| PDA app | Kotlin + Jetpack Compose, Room, OkHttp; universal scanner layer | **Stage 3 done** — tested end-to-end on an Android 17 emulator with Urovo scan broadcasts |
| Reports | Django ORM aggregates + Excel export | **Stage 4 done** — overview, checkers, pickers, picked vs checked, reasons, operations |
| Stocktaking | Same backend, panel and PDA app | **Done** — vendors, stocktakes by date, counting on the PDA, WMS Excel export |

## Run on your server

```bash
cp .env.example .env      # then edit every CHANGE value
docker compose up -d --build
curl http://localhost/health/
```

Open `http://<server>/` for the admin panel (port `WEB_PORT`, default 80). The
panel's nginx also proxies `/api/`, so PDAs can use the same address.

- The first admin is created from `ADMIN_USERNAME` / `ADMIN_PASSWORD`.
- Backups: the `backup` service writes a `pg_dump` every 24 h into the `backups`
  volume and keeps 14 days. Restore:
  `docker compose exec -T db pg_restore -U checking -d checking --clean < file.dump`

## Develop

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows; use .venv/bin on Linux
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py test apps                                 # 114 tests, SQLite
docker compose run --rm --no-deps -e DJANGO_DEBUG=true backend python manage.py test apps   # same tests on PostgreSQL
```

Admin panel (Vite dev server on :5173, proxies `/api` to the backend on :8000):

```bash
cd web
npm install
npm run dev
```

`npm run build` type-checks and builds; `web/Dockerfile` serves the build with nginx.

Panel notes: Persian/RTL is the default (switch FA/EN and Jalali/Gregorian in the
header). Barcodes, product IDs and aisle codes are always rendered LTR. Dates are shown in
Asia/Tehran time; date filters send Gregorian `YYYY-MM-DD` to the API. Menu items and actions
follow the signed-in user's permissions. Accounts whose roles only allow PDA work (checking orders, counting stock)
cannot sign in to the panel.

**Roles:** a user can have several roles and gets the union of their permissions (e.g. checker + stocktaker sees
both lists on the PDA). Built-in roles: Admin (always everything), Supervisor, Checker, Stocktaker. More roles can be
created under System → Permissions (name them, tick permissions, then give them to users under Users). Built-in
roles cannot be deleted; a role still held by users cannot be deleted. Permissions are the fixed feature switches
listed on that page.

## Reports (panel → Reports, permission `reports.view`)

Periods: Today / This week (from Saturday) / This month (Jalali month when the Jalali calendar is on) /
Custom; filter by checker (and picker on Reasons). Every tab exports to Excel (RTL with Jalali dates in Persian).

| Tab | Shows |
|---|---|
| Overview | Right now: waiting, assigned-not-started, being checked, open issues. In the period: orders assigned/checked/with discrepancies, SKUs, boxes checked/scanned, shortages (boxes + units), extras, not-in-order, avg time per order, avg active time, seconds per SKU, per-day table |
| Checkers | Per checker: orders, SKUs, boxes scanned, active time, **boxes per active hour**, avg time per order, seconds per SKU, shortages, extras, not-in-order, double-reads, unknown scans, mistaken scans, corrections |
| Pickers | Per picker: orders, SKUs, boxes; shortages split into stock vs picking reasons; extras; not-in-order; **error boxes and error rate** (non-stock shortages + extras + not-in-order); picked vs checked: boxes picked, shortage declared by the picker, recorded-but-not-on-pallet, on-pallet-but-not-recorded, **picking record accuracy** |
| Picked vs checked | Per line: ordered, picked (picker's record from the file), checked, extra removed, difference, result: *recorded but not on pallet*, *on pallet but not recorded*, *picked more than ordered*, *shortage declared by picker*, *match*. Shows only differences by default |
| Reasons | Discrepancies grouped by type and reason: lines, boxes, units, share |
| Operations | Every order active in the period: imported, assigned, started, completed, wait before start, elapsed, active time, progress, discrepancies |

Definitions: an order counts as *checked* in the period it was completed; volumes (SKUs, boxes,
discrepancies) are taken from orders completed in the period so all tabs agree; *boxes scanned* counts
accepted scans in the period (including unfinished orders); *active time* excludes gaps over 5 minutes
(`CHECK_ACTIVE_GAP_SECONDS`); discrepancies that resolved themselves are not counted. *Picked vs checked* compares
`packs_picked` from the order file with what the checker found on the pallet (counted + extra boxes removed); only orders
whose file has picking data (any line with picked > 0) are compared. Picked quantities and the picker name can be added
later by re-uploading the order file: unchanged lines/quantities are applied as *info updated*, even to completed orders.

API: `GET /api/reports/{overview|checkers|pickers|picking|reasons|operations}/?from=YYYY-MM-DD&to=YYYY-MM-DD&checker=&picker=&status=&q=&show=diff|all`,
add `&export=xlsx&lang=fa|en` for Excel.

## PDA app (`pda/`)

Build (JDK 17+, Android SDK 37; Android Studio's bundled JBR works):

```bash
cd pda
./gradlew :app:assembleDebug :app:testDebugUnitTest
```

APK: `pda/app/build/outputs/apk/debug/app-debug.apk` — install with `adb install -r app-debug.apk`
(or copy to the PDA and open it). Android 8.0+ (minSdk 26).

First run: **Settings** → server address (e.g. `http://192.168.1.10`, the panel's address) → *Test
connection* → press the scan button and check the barcode appears under *Scanner test*. Keep the scanner
mode on **Automatic** unless the test shows nothing.

How it works:
- **Scanner:** *Automatic* listens for the broadcast intents of Urovo, Zebra (auto-creates a DataWedge
  profile), Honeywell, Newland, iData, Sunmi, Chainway and Seuic at once; on Urovo it also switches the
  scanner to intent output via `android.device.ScanManager`. Keyboard-wedge input is a fallback.
  Double-reads (same code within 700 ms, monotonic clock) are recorded but never counted.
- **Offline-first:** the order, its barcodes and the central barcode mapping live on the device (Room).
  A scan is applied locally in a few ms with sound + vibration, and stored with its event in one
  transaction; a background sync sends events in order and survives app restarts. The server applies the
  same rules and is authoritative. Completing an order needs the network.
- **Feedback:** short beep = +1 box, double beep = item complete, error tone = unknown barcode, repeating
  alarm + full-screen red block = extra box / not in order (must answer *Removed from pallet* or
  *Scanned by mistake*).
- **Finish:** lists what still blocks completion; remaining items can be marked as shortages in bulk with
  one reason.
- Persian by default (RTL, Vazirmatn, Persian digits; counts shown as "۳ از ۵" because `/` is the Persian
  decimal separator); English in Settings. Barcodes/IDs/aisles always LTR.

Simulate a Urovo scan on an emulator or device:

```bash
adb shell am broadcast -a android.intent.ACTION_DECODE_DATA --es barcode_string 6260108396830
```

Import a file from the command line (preview only; add `--commit` to apply):

```bash
.venv/Scripts/python manage.py import_excel path/to/order_check.xlsx
.venv/Scripts/python manage.py import_excel path/to/mapping.xlsx --kind barcodes --commit
```

## Panel layout

Two main tabs in the header: **Order checking** (live board, orders, import, barcodes, reasons, reports) and
**Stocktaking** (stocktakes, product list, vendors, stocktaking reports). Users, permissions and the audit log are
under *System* in both. Each tab shows only what the signed-in user's permissions allow.

## Stocktaking (panel → Stocktaking, permission `stocktake.manage`)

A separate team counts stock with the same PDA app. Users with the **Stocktaker** role see only their stocktakes on the
PDA; checkers see only their orders; a role that holds both permissions gets both lists (switch icon in the top bar).

1. Panel: create a **stocktake** = vendor + date + one or more counters (vendors can be added inline or on the *Vendors* tab).
2. PDA: the stocktake appears from its date on (the next 7 days are shown as "starts on …") until it is closed.
   Scan a barcode → type the count (units) → optional price → **Save** (or Done). Scanning the next item saves the
   current one if its count is filled in. The same barcode can be recorded any number of times (several locations);
   the PDA shows "already counted here: N units in M records". Barcodes do not need to be in the product catalog (vendors define their own). Records can be edited or
   deleted while the stocktake is open. Everything is saved on the device first and synced in the background (offline OK).
3. Panel: live totals per barcode and per counter, price conflicts, all records; **Close** when done (reopen if needed).
4. **Excel for WMS**: one sheet, columns `barcode, title, count, price`, one row per barcode + title with all counters'
   counts summed; barcode as scanned (text, leading zeros kept, no padding added); price = the last price entered
   (empty if none). **Detail Excel**: totals with price conflicts, plus every record by counter and time.

**Stocktaking reports** (separate from the checking reports; Today / week / month / custom, filter by vendor and
counter, Excel export): *Overview* (open/upcoming stocktakes, records, units, barcodes, active time, records per
hour, typed titles, value = count × price, per day), *Counters* (records, units, active time, records/units per
hour, typed titles, edited, deleted), *Vendors* (units, barcodes, counters, value), *Stocktakes* (per stocktake:
records, units, first/last record, elapsed) and *Typed titles* (titles counters typed, with the list's other titles
for that barcode, for review). API: `GET stocktake-reports/{overview|counters|vendors|stocktakes|new-titles}/?from=&to=&vendor=&counter=`.

**Product list (panel → Stocktaking → Product list)** — the stocktaking master, independent of the order-checking
barcode mapping. Import a CSV/Excel with `barcode` + `title` columns (Persian headers `بارکد` / `شرح کالا` work; a
price column is stored but not used). Preview first, then *Add and update* (never removes) or *Replace* (removes
previously imported rows missing from the file; rows added in the panel or by counters are kept). Single rows can be
added, edited and deleted in the panel; the list can be exported. On the PDA (downloaded once, then changes only):
one title → shown; several titles → the counter picks one (or "other title"); not in the list → the counter types
the title, and that title is added to the list marked as *counter* so the next scan finds it.

API: `GET/POST/PATCH vendors/`, `GET/POST/PATCH stocktakes/` (`?status=&vendor=&from=&to=`),
`POST stocktakes/{id}/close|reopen/`, `GET stocktakes/{id}/totals|records/`, `GET stocktakes/{id}/export/?kind=wms|detail&lang=`,
`GET stocktakers/`, `GET/POST/PATCH/DELETE stocktake-master/` (`?q=&source=&multi=`), `POST stocktake-master/import/`
(multipart `file`, `mode=merge|replace`, `dry_run=true|false`), `GET stocktake-master/stats|export/`; PDA: `GET pda/stocktake-master/?since=&after_id=`
(change feed), `GET pda/stocktakes/`, `GET|POST pda/stocktakes/{id}/records/`
(`{sent_at, records:[{id, barcode, title, title_typed, quantity, price?, counted_at, updated_at, deleted?}]}`, idempotent per record id,
newest `updated_at` wins).

## Key rules implemented

- **1 scan = 1 box.** Units are always `boxes × inc_ordered`. Import rejects rows where
  `units_ordered ≠ pack_ordered × inc_ordered`.
- **Barcode lookup:** this order's file barcodes → central mapping → unknown. Real
  barcodes always win over repaired ones.
- **Barcode cleanup** (same on import and scan): AIM prefixes, GS1 `(01)`, Persian
  digits, bidi marks, UPC-A/EAN-13/GTIN-14 leading zeros. Placeholders like
  `123456` are ignored. 12-digit codes with a dropped digit get a repaired EAN-13
  unless it collides with another product's real barcode.
- **Extras can't ship:** an over-scan or a not-in-order product is never counted;
  it blocks scanning until the checker answers *Removed from pallet* (recorded as
  a discrepancy, attributed to the picker, default reason) or *Scanned by mistake*.
- **Shortages** are declared by the checker (*Not found* or at Finish); late boxes
  shrink them automatically.
- **Completion** requires every line complete or short-with-reason, no pending
  decision, no discrepancy without a reason. Completed orders reject scans.
- **Duplicate protection:** scanner double-reads are flagged on the PDA (monotonic
  clock, 700 ms); every event has a PDA-generated UUID, so re-sent batches are never
  applied twice; PDA clock skew is corrected per batch via `sent_at`.
- **One active checker per order** (database constraint). Reassignment keeps all
  scans; offline scans made before the reassignment are still accepted (flagged late).
- **Audit:** every import, assignment, discrepancy change, correction, completion,
  cancel/reopen, user and permission change.

## API overview

All endpoints are under `/api/`, JSON, `Authorization: Bearer <access token>`.
Errors: `{"code": "<stable_key>", "detail": "...", "data": {...}}`.

| Method & path | Permission | Purpose |
|---|---|---|
| `POST auth/login/` | — | `{username, password, device_serial?, device_model?, app_version?}` → tokens + user |
| `POST auth/refresh/` · `GET/PATCH auth/me/` | any | token refresh · profile / language |
| `GET/POST/PATCH users/` · `POST users/{id}/reset-password/` · `GET users/activity/` | users.manage | user admin (no delete; deactivate) |
| `GET/PUT role-permissions/` | permissions.manage | role → permission matrix (`{role: code, permissions: [...]}`) |
| `GET/POST/PATCH/DELETE roles/` | permissions.manage (read: users.manage) | roles: `{name_fa, name_en}`; users get `roles: [codes]` |
| `GET checkers/` | orders.view | active checkers with current workload |
| `GET orders/summary/` | orders.view | live board counters |
| `GET audit/?action=&user=&from=&to=` | audit.view | global audit log |
| `GET/POST/PATCH reasons/` | reasons.manage (read: any) | discrepancy reasons |
| `POST imports/` (multipart `file`, `kind=orders\|barcodes`) | orders.import / barcodes.manage | upload → validated preview |
| `GET imports/{id}/rows/?filter=errors\|warnings` · `POST imports/{id}/commit/` · `…/discard/` | same | review and apply |
| `GET orders/?status=&checker=&unassigned=&has_issues=&q=&from=&to=` · `GET orders/{id}/` | orders.view | lists and detail (lines, tabs, discrepancies, assignments) |
| `POST orders/{id}/assign\|reassign\|unassign/` · `POST orders/bulk-assign/` | orders.assign | `{checker_id, reason?}` |
| `POST orders/{id}/cancel\|reopen/` | orders.manage | `{note}` required |
| `GET orders/{id}/events/` · `GET orders/{id}/audit/` | orders.view · audit.view | scan timeline · audit trail |
| `GET products/?q=` · `GET products/{id}/` · `POST products/{id}/barcodes/` | any · barcodes.manage | search, barcode history, manual mapping |
| `GET pda/config/` | checking.perform | debounce, active reasons |
| `GET pda/orders/` · `GET pda/orders/{id}/` | checking.perform | my orders · full offline snapshot |
| `POST pda/orders/{id}/events/` | checking.perform | `{sent_at, events:[{id, kind, at, …}]}` (≤500) |
| `GET pda/orders/{id}/finish-check/` · `POST pda/orders/{id}/finish/` | checking.perform | completion problems · complete |
| `GET pda/barcodes/?since=&after_id=` | checking.perform | central mapping change feed for the PDA cache |

PDA event kinds: `scan {barcode, duplicate?}`, `extra_decision {ref, decision: removed|mistake}`,
`declare_short {line_id, reason_id?, note?}`, `set_reason {line_id, type, reason_id, note?}`,
`adjust {line_id, boxes, reason_id?, note?}`.
