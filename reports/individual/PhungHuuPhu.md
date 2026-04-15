# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Phùng Hữu Phú  
**Vai trò:** Cleaning & Quality Owner  
**Ngày nộp:** 2026-04-15  
**run_id:** sprint-final-restore

---

## 1. Tôi phụ trách phần nào?

**File / module:**

- `transform/cleaning_rules.py` — toàn bộ: `clean_rows()` (9 rules), `_normalize_effective_date()`, `_word_count()`, `_parse_exported_at()`, `write_cleaned_csv()`, `write_quarantine_csv()`.
- `quality/expectations.py` — toàn bộ: `run_expectations()` (8 expectations: E1–E6 baseline, **E7–E8 mới**).
- Thêm 4 dòng vào `data/raw/policy_export_dirty.csv` để chứng minh tác động 3 rule mới (rows 11–14).

**Kết nối với thành viên khác:**

Tôi nhận `List[Dict]` rows từ Hùng (Ingest) → xử lý → trả lại `(cleaned, quarantine)`. Thông (Embed) nhận `cleaned` để embed. Tôi cũng định nghĩa `ExpectationResult` mà pipeline chính dùng để quyết định halt hay không.

**Bằng chứng:**
- `artifacts/quarantine/quarantine_sprint-final-restore.csv`: 6 dòng với các reason cụ thể bao gồm 2 reason mới (`chunk_too_few_words`, `stale_source_export`).
- `artifacts/logs/run_sprint-final-restore.log`: tất cả 8 expectation PASS.

---

## 2. Một quyết định kỹ thuật

**Quyết định: Đặt Rule 7 (normalize_doc_id) TRƯỚC Rule 1 (allowlist check), không phải sau.**

Ban đầu tôi đặt normalize sau allowlist check — điều này nghĩa là " hr_leave_policy " (có space) vẫn bị quarantine unknown_doc_id vì code nhận `doc_id = raw.get("doc_id", "")` mà không strip.

Tôi sửa lại: dòng đầu tiên trong loop là `doc_id = (raw.get("doc_id") or "").strip()`. Kết quả: Row 11 được **rescued** thay vì bị quarantine → `quarantine_records` giảm từ 7 xuống 6.

**Tại sao quan trọng:** Strip whitespace là "normalization rule" — nên chạy **trước** validation rule. Nguyên tắc pipeline: chuẩn hóa dữ liệu vào trước, rồi mới validate. Nếu đặt ngược lại, valid data bị reject sai.

**Trade-off:** Cần đảm bảo không over-normalize (vd: không tự động lowercase `doc_id` vì `Policy_Refund_V4` vs `policy_refund_v4` là 2 entity khác nhau theo contract).

---

## 3. Một lỗi / anomaly đã xử lý

**Triệu chứng:** Expectation E3 `refund_no_stale_14d_window` FAIL trong inject run với `violations=1` — nhưng khi kiểm tra `cleaned_inject-bad.csv`, chunk vi phạm là:

```
"Yêu cầu hoàn tiền được chấp nhận trong vòng 14 ngày làm việc kể từ xác nhận đơn (ghi chú: bản sync cũ policy-v3 — lỗi migration)."
```

**Metric phát hiện:** Log dòng `expectation[refund_no_stale_14d_window] FAIL (halt) :: violations=1`.

**Phân tích:** Rule 6 `apply_refund_window_fix` chỉ hoạt động khi `apply_refund_window_fix=True` (default). Khi pipeline chạy với `--no-refund-fix`, `apply_refund_window_fix=False` → text "14 ngày" không được replace → chunk đi vào cleaned → E3 fail. Đây là **thiết kế có chủ đích** cho Sprint 3 inject demo.

**Lesson:** Expectation E3 là "guard" cuối cùng trước embed — dù cleaning rule bị bypass, expectation vẫn phát hiện vi phạm và halt pipeline.

---

## 4. Bằng chứng trước / sau

**Inject run (inject-bad, --no-refund-fix):**
```
expectation[refund_no_stale_14d_window] FAIL (halt) :: violations=1
```
→ `artifacts/eval/before_inject_eval_k10.csv`:
```
q_refund_window,...,contains_expected=yes,hits_forbidden=yes,...,10
```

**Clean run (sprint-final-restore):**
```
expectation[refund_no_stale_14d_window] OK (halt) :: violations=0
```
→ `artifacts/eval/before_after_eval.csv`:
```
q_refund_window,...,contains_expected=yes,hits_forbidden=no,...,10
```

Delta: `hits_forbidden` đổi từ **yes → no** sau khi clean run prune stale chunk.

---

## 5. Cải tiến tiếp theo

Nếu có thêm 2 giờ, tôi sẽ đọc cutoff versioning từ `contracts/data_contract.yaml` thay vì hard-code `"2026-01-01"` trong `cleaning_rules.py`. Cụ thể: load YAML → đọc `policy_versioning.hr_leave_min_effective_date` và `policy_versioning.stale_export_cutoff` → inject vào `clean_rows()` qua params. Đây là Distinction criteria (d): "rule versioning không hard-code" — thay đổi cutoff trong YAML tự động áp dụng mà không cần sửa code.
