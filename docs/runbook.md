# Runbook — Lab Day 10 (incident tối giản)

**Maintained by:** Bùi Đức Tiến (Monitoring / Docs Owner)  
**Cập nhật:** 2026-04-15

---

## Symptom

**Kịch bản 1 — Agent trả lời sai cửa sổ hoàn tiền:**  
User / agent nhận kết quả "14 ngày làm việc" thay vì "7 ngày làm việc" khi hỏi về policy hoàn tiền.

**Kịch bản 2 — freshness_check=FAIL:**  
Log pipeline hoặc cron alert báo `freshness_sla_exceeded`, `age_hours > 24`.

**Kịch bản 3 — PIPELINE_HALT:**  
`python etl_pipeline.py run` exit code 2; log có dòng `PIPELINE_HALT: expectation suite failed`.

---

## Detection

| Signal | Tool / File | Ngưỡng cảnh báo |
|--------|------------|-----------------|
| `hits_forbidden=yes` trong eval | `artifacts/eval/before_after_eval.csv` | Bất kỳ câu nào |
| `expectation[refund_no_stale_14d_window] FAIL` | `artifacts/logs/run_*.log` | violations > 0 |
| `freshness_sla_exceeded` | `artifacts/manifests/manifest_*.json` | age_hours > 24 |
| `quarantine_records` tăng đột biến | Log / manifest | > baseline (hiện tại 6) |
| `embed_prune_removed` lớn bất thường | Log | > 3 (tùy corpus size) |

---

## Diagnosis

### Kịch bản 1 — Stale refund chunk

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|------------------|
| 1 | Mở `artifacts/logs/run_<latest>.log`, tìm `expectation[refund_no_stale_14d_window]` | `FAIL (halt) :: violations=N` nếu pipeline chạy với `--no-refund-fix` hoặc `--skip-validate` |
| 2 | Mở `artifacts/quarantine/quarantine_<latest>.csv` | Không có reason `stale_source_export` hay `missing_effective_date` bất thường |
| 3 | Kiểm tra `artifacts/manifests/manifest_<latest>.json` | Trường `no_refund_fix` phải là `false` trong run sạch |
| 4 | Chạy `python eval_retrieval.py --top-k 10` | `hits_forbidden` cột `q_refund_window` phải là `no` sau clean run |

### Kịch bản 2 — freshness_check=FAIL

> **Ghi chú:** CSV mẫu lab có `exported_at = 2026-04-10T08:00:00`. Khi chạy lab ngày 2026-04-15, tuổi dữ liệu ~121h > 24h SLA → **FAIL là hành vi dự đoán được** cho môi trường học.

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|------------------|
| 1 | Đọc `manifest_*.json` → trường `latest_exported_at` | Kiểm tra giá trị thực tế vs `sla_hours` |
| 2 | Nếu data production: kiểm tra pipeline có chạy đúng lịch không | Pipeline log mới nhất < SLA giờ trước |
| 3 | Nếu data lab/demo: điều chỉnh `FRESHNESS_SLA_HOURS` trong `.env` hoặc cập nhật timestamp CSV | WARN thay vì FAIL nếu muốn |

**Giải thích PASS/WARN/FAIL:**
- `PASS`: `age_hours <= sla_hours` (24h) — dữ liệu đủ tươi.
- `WARN`: `no_timestamp_in_manifest` — manifest không có trường timestamp; không thể đánh giá.
- `FAIL`: `age_hours > sla_hours` hoặc manifest file không tồn tại — dữ liệu có thể stale.

### Kịch bản 3 — PIPELINE_HALT

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|------------------|
| 1 | Đọc log: dòng `expectation[...] FAIL (halt)` | Xác định expectation nào fail (vd E3: refund 14 ngày) |
| 2 | Mở `artifacts/cleaned/cleaned_<run_id>.csv` | Tìm row có `chunk_text` chứa vi phạm |
| 3 | Sửa nguồn: cập nhật `data/raw/` hoặc thêm cleaning rule | Source data không còn vi phạm |
| 4 | Rerun: `python etl_pipeline.py run --run-id <new-id>` | Exit 0, `PIPELINE_OK` |

---

## Mitigation

1. **Stale embed:** Rerun `python etl_pipeline.py run --run-id <new-id>` — pipeline prune chunk cũ và upsert chunk mới.
2. **Rollback embed:** Xóa `chroma_db/` và rerun pipeline với CSV đã clean để rebuild index từ đầu.
3. **Tạm thời:** Banner "Thông tin hoàn tiền đang được cập nhật, vui lòng liên hệ CS" khi `freshness_check=FAIL` kéo dài > 48h.
4. **Inject pipeline đã chạy nhầm:** Chạy lại `python etl_pipeline.py run --run-id recover-<date>` (không có `--no-refund-fix`). Log sẽ có `embed_prune_removed=N` xác nhận stale vector đã bị xóa.

---

## Prevention

1. **Thêm expectation** mỗi khi phát hiện pattern lỗi mới (vd: E7 `unique_chunk_ids`, E8 `effective_date_not_before_2000`).
2. **CI check** (nếu có GitHub Actions): chạy `python etl_pipeline.py run --run-id ci-smoke` trong PR pipeline; fail build nếu exit != 0.
3. **Alert channel** (production): `contracts/data_contract.yaml` → `freshness.alert_channel: "slack:#data-ops-alerts"`.
4. **Peer review câu hỏi (Phần E — slide Day 10):**
   - *Khi nào cần halt vs warn?* → Halt khi dữ liệu sai ảnh hưởng đến quyết định agent (vd refund policy sai → lawsuit risk). Warn khi chỉ là noise không ảnh hưởng semantic (vd chunk ngắn < 8 ký tự).
   - *Idempotency có đảm bảo không?* → Có: upsert theo `chunk_id` + prune. Kiểm tra bằng `embed_prune_removed=0` khi rerun cùng data.
   - *Freshness SLA nên đặt bao lâu?* → Phụ thuộc business: policy hoàn tiền thay đổi ít (SLA 24-48h OK); SLA P1 ticket phải update gần real-time (SLA 1-4h nếu cần).
