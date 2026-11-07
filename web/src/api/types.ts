/** Role code: built-in ("admin", "supervisor", "checker", "stocktaker") or created in the panel. */
export type Role = string;
export type OrderStatus = "pending_assignment" | "assigned" | "in_progress" | "completed" | "cancelled";
export type LineState = "pending" | "partial" | "ok" | "short" | "extra";
export type Tab = "to_check" | "ok" | "issue";

export interface User {
  id: number; username: string; full_name: string; roles: Role[]; role: Role; language: "fa" | "en";
  role_names: { code: string; name_fa: string; name_en: string }[];
  is_active: boolean; last_login: string | null; date_joined: string; permissions: string[];
}

export interface Checker { id: number; username: string; name: string; active_orders: number; capacity_boxes: number | null; load_today: number }

export interface OrderListItem {
  id: number; reference_type: string; reference_id: string; version: number; customer: string; picker_name: string;
  source_created_at: string | null; imported_at: string; status: OrderStatus;
  checker: { id: number; name: string; assigned_at: string } | null;
  lines_total: number; lines_done: number; boxes_ordered: number; boxes_scanned: number;
  open_issues: number; issues_total: number; progress: number;
  first_scan_at: string | null; last_scan_at: string | null; completed_at: string | null; duration_seconds: number | null;
}

export interface Discrepancy {
  id: number; type: "short" | "extra" | "not_in_order"; qty_boxes: number; qty_units: number;
  reason_id: number | null; reason_code: string | null; note: string; status: "open" | "reasoned" | "resolved";
  picker_name: string; checker_id: number | null; created_at: string; updated_at: string; resolved_at: string | null;
}

export interface OrderLine {
  id: number; product_id: string; title: string; aisle_title: string; aisle_rank: number;
  pack_ordered: number; inc_ordered: number; units_ordered: number; packs_picked: number | null;
  units_picked: number | null; physical_stock: number | null; label: string; is_unordered: boolean;
  boxes_scanned: number; boxes_extra: number; boxes_short: number; units_scanned: number; state: LineState;
  tab: Tab; row_version: number; last_scan_at: string | null; barcodes: string[]; discrepancies: Discrepancy[];
}

export interface Assignment {
  id: number; checker_id: number; checker_name: string; assigned_by_name: string | null; assigned_at: string;
  revoked_at: string | null; revoked_by_name: string | null; revoke_reason: string;
}

export interface OrderDetail extends OrderListItem {
  assignments: Assignment[]; lines: OrderLine[]; completed_by_name: string | null; import_batch_id: number;
  cancelled_at: string | null;
}

export interface CheckEventRow {
  id: string; kind: string; result: string; barcode: string; line_id: number | null; product_id: string | null;
  title: string | null; delta_boxes: number; user: string; at: string; received_at: string; is_late: boolean;
  payload: Record<string, unknown>; ref_event_id: string | null;
}

export interface AuditEntry {
  id: number; at: string; user: string | null; action: string; entity_type: string; entity_id: string;
  order_id?: number | null; order_reference?: string | null; before: unknown; after: unknown; note: string; ip?: string | null;
}

export interface Problem { code: string; [k: string]: unknown }

export interface ImportOrderPreview {
  key: string; reference_type: string; reference_id: string; customer: string; picker: string; created_at: string | null;
  lines: number; boxes: number; units: number; error_rows: number; warning_rows: number; action: string;
  existing_order_id: number | null; existing_status: string | null; existing_version: number | null;
}

export interface ImportBatch {
  id: number; kind: "orders" | "barcodes"; file_name: string; file_sha256: string;
  status: "validated" | "committed" | "discarded" | "failed"; uploaded_by_name: string | null; uploaded_at: string;
  committed_at: string | null; rows_total: number; rows_error: number; rows_warning: number; file_errors: Problem[];
  preview: { headers?: string[]; orders?: ImportOrderPreview[]; actions?: Record<string, number>; importable?: number };
  result: Record<string, unknown>;
}

export interface ImportRow { row_no: number; order_key: string; raw: Record<string, unknown>; errors: Problem[]; warnings: Problem[] }

export interface Reason {
  id: number; code: string; name_fa: string; name_en: string; applies_to: "short" | "extra" | "both";
  category: "stock" | "picking" | "scanning" | "other"; requires_note: boolean; is_active: boolean;
  sort_order: number; default_for: "extra" | "not_in_order" | null;
}

export interface Summary {
  waiting_assignment: number; assigned_not_started: number; in_progress: number; open_issues: number;
  completed_today: number; completed_with_issues_today: number; boxes_scanned_today: number; server_time: string;
}

export interface ProductRow { id: string; title: string; title_en: string }
export interface BarcodeRow {
  id: number; barcode: string; code: string; product_id: string; source: string; is_derived: boolean;
  is_active: boolean; created_at: string; deactivated_at: string | null;
}
export interface ProductDetail extends ProductRow { barcodes: BarcodeRow[] }

export interface ReportOverview {
  period: { from: string; to: string };
  orders_assigned: number; orders_checked: number; orders_with_discrepancies: number; skus_checked: number;
  boxes_ordered: number; boxes_checked: number; boxes_scanned: number; discrepancies: number;
  shortage_lines: number; shortage_boxes: number; shortage_units: number; extra_boxes: number; not_in_order_boxes: number;
  avg_elapsed_seconds: number | null; avg_active_seconds: number | null; avg_seconds_per_sku: number | null;
  now: { waiting_assignment: number; assigned_not_started: number; in_progress: number; unresolved_discrepancies: number };
  by_day: { date: string; orders_completed: number; boxes_scanned: number; skus: number }[];
}

export interface CheckerReportRow {
  checker_id: number; name: string; username: string; orders_checked: number; orders_with_discrepancies: number;
  skus_checked: number; boxes_checked: number; boxes_scanned: number; active_seconds: number; boxes_per_hour: number | null;
  avg_elapsed_seconds: number | null; avg_active_seconds: number | null; avg_seconds_per_sku: number | null;
  shortage_lines: number; shortage_boxes: number; extra_boxes: number; not_in_order_boxes: number;
  double_reads: number; unknown_scans: number; mistakes: number; corrections: number;
}

export interface PickerReportRow {
  picker: string; orders: number; skus: number; boxes_ordered: number;
  short_stock_lines: number; short_stock_boxes: number; short_picking_lines: number; short_picking_boxes: number;
  extra_boxes: number; not_in_order_boxes: number; not_in_order_lines: number; error_boxes: number; error_rate_pct: number | null;
  pick_orders: number; pick_lines: number; boxes_picked: number; pick_short_boxes: number; missing_boxes: number;
  unrecorded_boxes: number; pick_mismatch_lines: number; pick_accuracy_pct: number | null;
}

export type PickResult = "missing" | "unrecorded" | "picked_extra" | "declared_short" | "match";

export interface PickingRow {
  line_id: number; order_id: number; reference_id: string; picker: string; checker: string | null; completed_at: string;
  product_id: string; title: string; aisle_title: string; inc: number; ordered: number; picked: number; checked: number;
  extra: number; found: number; diff: number; pick_short: number; missing: number; unrecorded: number; result: PickResult;
}

export interface PickingReport {
  summary: Record<PickResult, { lines: number; boxes: number }>;
  totals: { lines: number; boxes_ordered: number; boxes_picked: number; boxes_found: number };
  orders_compared: number; orders_without_pick_data: number; truncated: boolean; rows: PickingRow[];
}

export interface ReasonReportRow {
  type: "short" | "extra" | "not_in_order"; reason_id: number | null; code: string | null; name_fa: string | null;
  name_en: string | null; category: string | null; lines: number; boxes: number; units: number;
}

export interface OperationsRow {
  order_id: number; reference_id: string; customer: string; picker: string; status: OrderStatus; checker: string | null;
  imported_at: string; assigned_at: string | null; started_at: string | null; completed_at: string | null;
  elapsed_seconds: number | null; active_seconds: number | null; wait_seconds: number | null;
  skus: number; skus_done: number; boxes_ordered: number; boxes_scanned: number; discrepancies: number; open_discrepancies: number;
}

export interface PermissionMatrix { permissions: Record<string, string>; roles: Record<Role, string[]> }
export interface AppRole { id: number; code: string; name_fa: string; name_en: string; is_system: boolean; permissions: string[]; users: number }

// --- Stocktaking ---------------------------------------------------------------------
export interface Vendor { id: number; name: string; code: string; is_active: boolean; created_at: string; stocktakes_count?: number }
export interface Stocktaker { id: number; username: string; name: string; open_stocktakes: number }
export type StocktakeStatus = "open" | "closed";
export interface StocktakeBrief {
  id: number; vendor: { id: number; name: string; code: string }; date: string; status: StocktakeStatus; note: string;
  created_at: string; closed_at: string | null; counters: { id: number; name: string; username: string }[];
  records: number | null; quantity: number | null; barcodes: number | null;
}
export interface StocktakeDetail extends StocktakeBrief {
  countable: boolean;
  by_counter: { user_id: number; name: string; username: string; assigned: boolean; records: number; quantity: number; barcodes: number; last_at: string | null }[];
  totals: { barcodes: number; quantity: number; records: number; price_conflicts: number; without_price: number };
}
export interface StockTotal { key: string; code: string; barcode: string; title: string; quantity: number; records: number; counters: number; price: string | null; price_conflict: boolean }
export interface StockRecord {
  id: string; user: string; user_id: number; barcode: string; code: string; title: string | null; title_typed: boolean;
  quantity: number; price: string | null; counted_at: string; deleted: boolean;
}

export interface MasterItem {
  id: number; barcode: string; code: string; title: string; price: string | null; source: "import" | "manual" | "counter";
  created_by: string | null; created_at: string; updated_at: string;
}
export interface MasterStats { items: number; barcodes: number; multi_title_barcodes: number; by_source: Partial<Record<MasterItem["source"], number>> }
export interface MasterImportResult {
  rows: number; items: number; new: number; updated: number; unchanged: number; removed: number; duplicate_rows: number;
  errors: number; error_rows: { row: number; code: string; barcode?: string }[]; barcodes_with_several_titles: number;
  mode: "merge" | "replace"; dry_run: boolean;
}
