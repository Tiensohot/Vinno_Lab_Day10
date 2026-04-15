# Quality report — Lab Day 10 (nhóm)

**Nhóm:** Vinno  
**run_id:** sprint-final-restore  
**Ngày:** 2026-04-15

---

## 1. Tóm tắt số liệu

| Chỉ số | Sprint inject (inject-bad) | Sprint clean (sprint-final-restore) | Ghi chú |
|--------|--------------------------|-------------------------------------|---------|
| raw_records | 14 | 14 | Cùng file CSV mẫu (14 dòng) |
| cleaned_records | 8 | 8 | Số dòng được embed vào Chroma |
| quarantine_records | 6 | 6 | Lý do: dup, missing date, stale HR, unknown doc_id, few_words, stale_export |
| Expectation halt? | **FAIL** (E3: violations=1) | **PASS** (tất cả 8 expectation OK) | E3 = `refund_no_stale_14d_window` |
| embed_prune_removed | 0 (inject là lần đầu run xấu) | 1 (clean run prune chunk 14 ngày) | Xác nhận "publish boundary" |

**Breakdown quarantine 6 dòng (run sạch):**

| Row | Reason |
|-----|--------|
| 2 | `duplicate_chunk_text` (bản sao của row 1) |
| 5 | `missing_effective_date` (date rỗng) |
| 7 | `stale_hr_policy_effective_date` (2025-01-01 < 2026-01-01) |
| 9 | `unknown_doc_id` (legacy_catalog_xyz_zzz) |
| 12 | `chunk_too_few_words` (chunk "Ok" = 1 từ) ← Rule 8 mới |
| 13 | `stale_source_export` (exported_at=2018-06-15 < 2020-01-01) ← Rule 9 mới |

---

## 2. Before / after retrieval (bắt buộc)

Artifact: `artifacts/eval/before_inject_eval_k10.csv` (inject, top-k=10) vs `artifacts/eval/before_after_eval.csv` (clean, top-k=10).

### Câu q_refund_window — CHỨNG CỨ CHÍNH

**Trước (inject-bad, --no-refund-fix, top-k=10):**
```
q_refund_window,...,contains_expected=yes,hits_forbidden=yes,...,10
```
- `contains_expected=yes`: top-k vẫn có chunk "7 ngày" (row 1 không bị ảnh hưởng)
- `hits_forbidden=yes`: **chunk "14 ngày làm việc" (row 3 unfixed) nằm trong top-10** → agent có thể đọc phải cả 2 phiên bản mâu thuẫn

**Sau (sprint-final-restore, clean, top-k=10):**
```
q_refund_window,...,contains_expected=yes,hits_forbidden=no,...,10
```
- `hits_forbidden=no`: **không còn chunk nào chứa "14 ngày làm việc"** → index sạch

> **Expectation là signal tin cậy hơn:** Ở top-k=3, `hits_forbidden` bằng `no` cả 2 case (chunk stale không rank cao đủ). Expectation E3 phát hiện vi phạm **deterministically** trong mọi trường hợp — đây là lý do pipeline dùng `halt` thay vì chỉ dựa vào retrieval eval.

### Merit — q_leave_version (HR policy versioning)

**Trước + Sau (cả 2 run):**
```
q_leave_version,...,contains_expected=yes,hits_forbidden=no,top1_doc_expected=yes,10
```
- `contains_expected=yes`: "12 ngày phép năm" có trong top-10 ✓
- `hits_forbidden=no`: "10 ngày phép năm" (bản HR 2025) KHÔNG có trong top-k ✓ — cleaning rule R3 đã quarantine row 7 (stale HR)
- `top1_doc_expected=yes`: top-1 chunk đúng từ `hr_leave_policy` ✓

---

## 3. Freshness & monitor

**Kết quả:** `freshness_check=FAIL` với `age_hours=121.3`, `sla_hours=24.0`

**Giải thích:** CSV mẫu lab dùng `exported_at=2026-04-10T08:00:00` cố định. Khi chạy ngày 2026-04-15, tuổi dữ liệu ~121 giờ vượt SLA 24h → FAIL là hành vi **dự đoán được** và được ghi trong Runbook mục "Kịch bản 2".

**SLA production:** 24h phù hợp cho policy hoàn tiền và HR (thay đổi ít). Cần điều chỉnh nếu dữ liệu real-time hơn (vd SLA ticket P1 nên <= 4h).

---

## 4. Corruption inject (Sprint 3)

**Kịch bản inject:** `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`

- `--no-refund-fix`: bỏ qua rule 6 (fix 14→7 ngày) → Row 3 "14 ngày làm việc" đi thẳng vào embed
- `--skip-validate`: bỏ qua halt khi E3 fail → embed tiếp dù có violation

**Phát hiện qua:**
1. Log: `expectation[refund_no_stale_14d_window] FAIL (halt) :: violations=1`
2. Eval top-k=10: `q_refund_window` → `hits_forbidden=yes`

**Recovery:** Chạy `python etl_pipeline.py run --run-id sprint-final-restore` → `embed_prune_removed=1` (xóa chunk 14 ngày), expectations pass, `hits_forbidden=no`.

---

## 5. Hạn chế & việc chưa làm

- **Freshness SLA chưa đo ở boundary ingest** (chỉ đo ở publish) — Distinction criteria (b) chưa đạt.
- **Model tiếng Việt:** `all-MiniLM-L6-v2` là English-centric; multilingual model sẽ cải thiện ranking chunk tiếng Việt.
- **Grading questions** được tự tạo (chờ GV public bản chính thức sau 17:00).
- **LLM-judge eval** chưa thực hiện — chỉ dùng keyword matching.
