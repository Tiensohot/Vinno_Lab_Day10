# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** BuiDucTien_day10  
**Thành viên:**
| Tên | Vai trò (Day 10) | Email |
|-----|------------------|-------|
| Nguyễn Công Hùng | Ingestion / Raw Owner | — |
| Phùng Hữu Phú | Cleaning & Quality Owner | — |
| Chu Thành Thông | Embed & Idempotency Owner | — |
| Bùi Đức Tiến | Monitoring / Docs Owner | tienvodich456@gmail.com |

**Ngày nộp:** 2026-04-15  
**run_id chính:** `sprint-final-restore`  
**Repo:** BuiDucTien_day10 / Lecture-Day-08-09-10 / day10/lab

---

## 1. Pipeline tổng quan

**Nguồn raw:** `data/raw/policy_export_dirty.csv` (14 dòng mẫu với các failure mode: duplicate, missing date, stale HR version, unknown doc_id, stale refund window, whitespace doc_id, chunk quá ngắn, exported_at cũ).

**Chuỗi lệnh chạy end-to-end:**
```bash
python etl_pipeline.py run --run-id sprint-final-restore
```

**Lệnh chạy một dòng (bao gồm freshness check):**
```bash
python etl_pipeline.py run && python etl_pipeline.py freshness --manifest artifacts/manifests/manifest_$(ls -t artifacts/manifests/ | head -1)
```

**run_id** xuất hiện ở dòng đầu tiên của log (`run_id=sprint-final-restore`) và là prefix của mọi artifact file: `cleaned_sprint-final-restore.csv`, `quarantine_sprint-final-restore.csv`, `manifest_sprint-final-restore.json`.

**Luồng xử lý:** Raw CSV (14) → `load_raw_csv()` → `clean_rows()` (9 rules) → `run_expectations()` (8 checks) → `cmd_embed_internal()` (Chroma upsert + prune) → `manifest_*.json` → `check_manifest_freshness()`.

**Kết quả run sạch:** `raw_records=14`, `cleaned_records=8`, `quarantine_records=6`, `PIPELINE_OK`, tất cả 8 expectation PASS.

---

## 2. Cleaning & expectation

Baseline gồm 6 rule (allowlist doc_id, ISO date parse, HR stale version, empty chunk, dedupe, refund fix). Nhóm thêm **3 rule mới** và **2 expectation mới**:

### 2a. Bảng metric_impact (bắt buộc)

| Rule / Expectation mới (tên ngắn) | Trước (số liệu) | Sau / khi inject (số liệu) | Chứng cứ (log / CSV / commit) |
|-----------------------------------|------------------|-----------------------------|-------------------------------|
| **Rule 7** `normalize_doc_id_whitespace` | Row 11 `" hr_leave_policy "` → quarantine `unknown_doc_id` (quarantine=7) | Row 11 stripped → **cleaned** (quarantine=6) | `quarantine_sprint-final-restore.csv`: row 11 KHÔNG có trong quarantine |
| **Rule 8** `quarantine_few_words` | Row 12 `"Ok"` (1 từ) → baseline cho qua (cleaned=9) | Row 12 → **quarantine** `chunk_too_few_words` (cleaned=8) | `quarantine_sprint-final-restore.csv`: row 12, reason=`chunk_too_few_words`, word_count=1 |
| **Rule 9** `quarantine_stale_source_export` | Row 13 `exported_at=2018` → baseline cho qua (cleaned=9) | Row 13 → **quarantine** `stale_source_export` (cleaned=8) | `quarantine_sprint-final-restore.csv`: row 13, reason=`stale_source_export` |
| **E7** `unique_chunk_ids` (halt) | Không có check này → bug tạo dup chunk_id có thể qua | Inject dup → **expectation FAIL halt** | Demo: sửa tay `chunk_id` để trùng → log `FAIL (halt) :: duplicate_chunk_ids=1` |
| **E8** `effective_date_not_before_2000` (warn) | Không có check → ngày `1900-01-01` qua lọc | Inject `effective_date=1999-12-31` → **FAIL warn** `pre_2000_rows=1` | Demo log: `expectation[effective_date_not_before_2000] FAIL (warn)` |

**Rule chính (baseline + mở rộng):**

- R1 allowlist `doc_id` (+ `access_control_sop` mới)
- R2 normalize & parse `effective_date` ISO / dd/mm/yyyy
- R3 quarantine HR stale `effective_date < 2026-01-01`
- R4 quarantine `chunk_text` rỗng
- R5 deduplicate `chunk_text`
- R6 fix refund window `14 → 7 ngày`
- **R7** strip whitespace khỏi `doc_id` (rescued row 11)
- **R8** quarantine chunk < 3 từ (blocked row 12)
- **R9** quarantine `exported_at < 2020` (blocked row 13)

**Ví dụ expectation fail (inject run):**
```
run_id=inject-bad
expectation[refund_no_stale_14d_window] FAIL (halt) :: violations=1
WARN: expectation failed but --skip-validate => tiep tuc embed (chi dung cho demo Sprint 3).
```
Xử lý: rerun pipeline không có `--no-refund-fix` → E3 pass, `embed_prune_removed=1`.

---

## 3. Before / after ảnh hưởng retrieval hoặc agent

**Kịch bản inject:** Chạy `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate` → embed chunk "14 ngày làm việc" vào `day10_kb`.

**Bằng chứng định lượng (từ CSV eval — top-k=10):**

| Question | Scenario | contains_expected | hits_forbidden | top1_doc_expected |
|----------|----------|-------------------|----------------|-------------------|
| `q_refund_window` | inject (before) | yes | **yes** | — |
| `q_refund_window` | clean (after) | yes | **no** | — |
| `q_leave_version` | inject (before) | yes | no | yes |
| `q_leave_version` | clean (after) | yes | no | yes |

File: `artifacts/eval/before_inject_eval_k10.csv` (before) vs `artifacts/eval/before_after_eval.csv` (after).

**Nhận xét quan trọng về observability:** Ở top-k=3, `hits_forbidden` là `no` ở cả 2 trường hợp vì stale chunk không luôn rank cao đủ trong top-3. Tuy nhiên `expectation[refund_no_stale_14d_window] FAIL` phát hiện vi phạm **deterministically**. Đây chứng minh rằng **expectation suite đáng tin cậy hơn retrieval eval** để đảm bảo data quality — tinh thần cốt lõi của observability pipeline.

---

## 4. Freshness & monitoring

**SLA đã chọn:** 24h (`FRESHNESS_SLA_HOURS=24` trong `.env`).

**Kết quả:** `FAIL` với `age_hours=121.3` — CSV mẫu dùng `exported_at=2026-04-10T08:00:00` cố định, khi chạy ngày 2026-04-15 → tuổi ~5 ngày. **Đây là hành vi dự đoán được** (ghi rõ trong Runbook mục "Kịch bản 2" và SCORING FAQ).

- **PASS:** dữ liệu đủ tươi (age <= 24h) — production case bình thường.
- **WARN:** manifest không có timestamp — pipeline chưa ghi `latest_exported_at` đúng cách.
- **FAIL:** dữ liệu vượt SLA — cần trigger rerun hoặc escalate.

---

## 5. Liên hệ Day 09

Pipeline Day 10 dùng **collection riêng** `day10_kb` (không phải collection Day 09) để tránh contamination khi chạy inject Sprint 3. Corpus `data/docs/` là shared (cùng 5 file policy). Nếu agent Day 09 cần đọc phiên bản cleaned từ pipeline Day 10, chỉ cần đổi `CHROMA_COLLECTION=day10_kb` trong `.env` của Day 09 — không cần sửa agent code.

---

## 6. Rủi ro còn lại & việc chưa làm

- Freshness chỉ đo ở boundary **publish** (không phải ingest riêng) — chưa đạt Distinction (b).
- `grading_questions.json` tự tạo; cần replace bằng file GV public sau 17:00.
- `all-MiniLM-L6-v2` không tối ưu tiếng Việt — xem xét `paraphrase-multilingual-MiniLM-L12-v2` cho production.
- LLM-judge eval chưa triển khai — chỉ dùng keyword matching.
- Peer review 3 câu hỏi (Phần E) được ghi đầy đủ trong `docs/runbook.md` mục Prevention.
