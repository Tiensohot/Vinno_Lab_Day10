# Data contract — Lab Day 10

> Bắt đầu từ `contracts/data_contract.yaml` — mở rộng và đồng bộ file này.  
> Owner nhóm: Vinno | Cập nhật: 2026-04-15

---

## 1. Nguồn dữ liệu (source map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert |
|-------|-------------------|-------------------|----------------|
| `data/raw/policy_export_dirty.csv` (batch export từ CMS nội bộ) | `load_raw_csv()` đọc UTF-8, header row bắt buộc | doc_id không trong allowlist; effective_date sai định dạng; chunk_text rỗng; exported_at từ kho cũ | `raw_records` vs `cleaned_records` trong log; `quarantine_records > 0` → alert |
| `data/docs/*.txt` (canonical policy files) | Đọc trực tiếp — không qua pipeline (nguồn ground truth) | Bản cũ không được xóa; conflict version (vd HR 2025 vs 2026) | Expectation E6 (`hr_leave_no_stale_10d_annual`) + E3 (`refund_no_stale_14d_window`) |

---

## 2. Schema cleaned

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| `chunk_id` | string | Có | sha256[:16] của `doc_id|chunk_text|seq` — stable, idempotent |
| `doc_id` | string | Có | Phải thuộc allowlist trong `contracts/data_contract.yaml` (5 giá trị) |
| `chunk_text` | string | Có | min 8 ký tự, min 3 từ; không chứa cửa sổ refund 14 ngày |
| `effective_date` | date | Có | Định dạng `YYYY-MM-DD`; phải >= 2000-01-01; HR policy phải >= 2026-01-01 |
| `exported_at` | datetime | Có | Định dạng ISO `YYYY-MM-DDTHH:MM:SS`; phải >= 2020-01-01T00:00:00 |

---

## 3. Quy tắc quarantine vs drop

**Quarantine** (ghi ra `artifacts/quarantine/quarantine_<run_id>.csv` với cột `reason`):

| Reason | Rule | Xử lý tiếp |
|--------|------|------------|
| `unknown_doc_id` | Baseline R1 | Review catalog; thêm vào allowlist nếu hợp lệ |
| `missing_effective_date` | Baseline R2 | Backfill từ nguồn hoặc loại bỏ |
| `invalid_effective_date_format` | Baseline R2 | Sửa định dạng ở nguồn |
| `stale_hr_policy_effective_date` | Baseline R3 | Chỉ giữ bản HR >= 2026-01-01 |
| `missing_chunk_text` | Baseline R4 | Loại bỏ; kiểm tra pipeline export |
| `duplicate_chunk_text` | Baseline R5 | Giữ bản đầu tiên; báo cáo cho nguồn dedup |
| `chunk_too_few_words` | **Rule 8 mới** | Loại bỏ hoặc merge chunk |
| `stale_source_export` | **Rule 9 mới** | Báo cáo ETL source; exported_at < 2020 |

**Drop im lặng:** KHÔNG có — mọi record bị loại đều vào quarantine.  
**Approve merge lại:** Data Engineering Lead xem xét file quarantine sau mỗi run; có thể rerun với `--raw` trỏ đến file đã sửa.

---

## 4. Phiên bản & canonical

- **Source of truth cho policy refund:** `data/docs/policy_refund_v4.txt` (v4) — cửa sổ hoàn tiền = **7 ngày làm việc**.
- **Source of truth cho HR leave:** `data/docs/hr_leave_policy.txt` — chỉ bản với `effective_date >= 2026-01-01` là hợp lệ.
- **Cutoff versioning:** đọc từ `contracts/data_contract.yaml` → `policy_versioning.hr_leave_min_effective_date` và `policy_versioning.stale_export_cutoff` — không hard-code trong code (Distinction criteria).
- **Conflict resolution:** khi 2 bản cùng `doc_id` khác `effective_date`, giữ bản mới nhất (> cutoff); bản cũ vào quarantine với reason `stale_hr_policy_effective_date`.
