# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Bùi Đức Tiến  
**Vai trò:** Monitoring / Docs Owner  
**Ngày nộp:** 2026-04-15  
**run_id:** sprint-final-restore

---

## 1. Tôi phụ trách phần nào?

**File / module:**

- `monitoring/freshness_check.py` — toàn bộ: `check_manifest_freshness()`, `parse_iso()`, logic PASS/WARN/FAIL theo SLA.
- `docs/pipeline_architecture.md` — sơ đồ ASCII + Mermaid, bảng ranh giới, idempotency, liên hệ Day 09.
- `docs/data_contract.md` — source map, schema, quarantine policy, version canonical.
- `docs/runbook.md` — 3 kịch bản sự cố (stale refund, freshness FAIL, PIPELINE_HALT) với symptom → detection → diagnosis → mitigation → prevention.
- `docs/quality_report.md` — số liệu thực tế từ 3 run + before/after eval table.
- `reports/group_report.md` — tổng hợp và bảng `metric_impact`.

**Kết nối với thành viên khác:**

Tôi đọc `manifest_*.json` mà Hùng (Ingest) và Thông (Embed) tạo ra → gọi `check_manifest_freshness()` → trả về PASS/WARN/FAIL cho pipeline. Tôi tổng hợp số liệu từ log của Phú (Cleaning) và eval CSV của Thông vào group_report và quality_report.

**Bằng chứng:**
```
freshness_check=FAIL {"latest_exported_at": "2026-04-10T08:00:00", "age_hours": 121.365, "sla_hours": 24.0, "reason": "freshness_sla_exceeded"}
```

---

## 2. Một quyết định kỹ thuật

**Quyết định: Dùng `latest_exported_at` từ cleaned CSV thay vì `run_timestamp` làm mốc freshness.**

Trong `check_manifest_freshness()`, tôi ưu tiên `latest_exported_at` (watermark của data nguồn) trước `run_timestamp` (thời điểm pipeline chạy):
```python
ts_raw = data.get("latest_exported_at") or data.get("run_timestamp")
```

**Lý do:** `run_timestamp` không phản ánh độ tươi của data — pipeline có thể chạy ngay hôm nay nhưng data nguồn là từ 3 ngày trước. SLA freshness phải đo từ **nguồn gốc data**, không phải thời điểm ETL chạy. Dùng `run_timestamp` sẽ luôn cho PASS (pipeline vừa chạy xong) nhưng data có thể vẫn stale.

**Trade-off chấp nhận được:** Nếu `exported_at` không có trong CSV nguồn (nullable), freshness check fall back sang `run_timestamp` và trả về WARN với reason `no_timestamp_in_manifest` — signal rõ ràng cho operator biết không thể đánh giá freshness.

---

## 3. Một lỗi / anomaly đã xử lý

**Triệu chứng:** `freshness_check=FAIL` ngay trên run sạch `sprint-final-restore`, mặc dù pipeline vừa chạy xong thành công (`PIPELINE_OK`).

**Metric phát hiện:**
```
freshness_check=FAIL {"latest_exported_at": "2026-04-10T08:00:00", "age_hours": 121.365, "sla_hours": 24.0}
```

**Phân tích:** `latest_exported_at` được lấy từ `max(exported_at)` trong cleaned rows. CSV mẫu dùng `exported_at=2026-04-10T08:00:00` cố định cho tất cả rows — pipeline chạy ngày 2026-04-15 → age ≈ 121h > 24h SLA → FAIL là **hành vi đúng**.

**Giải pháp / documentation:** Tôi ghi vào `docs/runbook.md` mục "Kịch bản 2 — freshness_check=FAIL" với ghi chú: "CSV mẫu lab có `exported_at` cố định — FAIL là hành vi dự đoán được. Trong production, `exported_at` sẽ phản ánh timestamp thực từ nguồn DB/API." Đây là anomaly không cần fix code — cần document rõ ràng để team không nhầm lẫn.

---

## 4. Bằng chứng trước / sau

**run_id: inject-bad** (log `artifacts/logs/run_inject-bad.log`):
```
expectation[refund_no_stale_14d_window] FAIL (halt) :: violations=1
freshness_check=FAIL {"age_hours": 121.316, "sla_hours": 24.0, "reason": "freshness_sla_exceeded"}
```

**run_id: sprint-final-restore** (log `artifacts/logs/run_sprint-final-restore.log`):
```
expectation[refund_no_stale_14d_window] OK (halt) :: violations=0
embed_prune_removed=1
freshness_check=FAIL {"age_hours": 121.365, "sla_hours": 24.0, "reason": "freshness_sla_exceeded"}
PIPELINE_OK
```

Freshness FAIL ở cả 2 run (expected với CSV mẫu). Sự khác biệt quan trọng: expectation E3 đổi từ **FAIL → OK** sau clean run — đây là tín hiệu "data quality restored".

---

## 5. Cải tiến tiếp theo

Nếu có thêm 2 giờ, tôi sẽ thêm **freshness check ở 2 boundary** (Distinction criteria b): đo `age_hours` từ `latest_exported_at` (boundary ingest) VÀ từ `run_timestamp` (boundary publish), ghi cả 2 vào manifest. Logic: nếu `ingest_age >> publish_age`, pipeline chạy thường xuyên nhưng data nguồn không được refresh → cần alert khác với "pipeline không chạy". Hiện tại chỉ đo ở publish, chưa phân biệt được 2 trường hợp này.
