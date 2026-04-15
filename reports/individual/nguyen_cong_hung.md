# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Nguyễn Công Hùng  
**Vai trò:** Ingestion / Raw Owner  
**Ngày nộp:** 2026-04-15  
**run_id:** sprint-final-restore

---

## 1. Tôi phụ trách phần nào?

**File / module:**

- `etl_pipeline.py` — hàm `cmd_run()` (dòng 49–128): đọc args, gọi `load_raw_csv()`, khởi tạo thư mục artifact, ghi log với đầy đủ `run_id`, `raw_records`, `cleaned_records`, `quarantine_records`.
- `transform/cleaning_rules.py` — hàm `load_raw_csv()` (dòng 57–63): đọc CSV UTF-8, DictReader, strip khoảng trắng mỗi cell.
- Thiết lập cấu trúc thư mục `artifacts/logs/`, `manifests/`, `quarantine/`, `cleaned/` và `.env` từ `.env.example`.

**Kết nối với thành viên khác:**

Tôi đưa ra `List[Dict]` rows từ `load_raw_csv()` → Phú (Cleaning Owner) nhận để chạy `clean_rows()`. Sau khi có `cleaned_path`, tôi kích hoạt `cmd_embed_internal()` → Thông (Embed Owner) chịu trách nhiệm logic upsert/prune trong hàm đó. Tôi ghi `manifest_*.json` → Tiến (Monitoring) đọc để chạy `check_manifest_freshness()`.

**Bằng chứng (log):**
```
run_id=sprint-final-restore
raw_records=14
cleaned_records=8
quarantine_records=6
cleaned_csv=artifacts\cleaned\cleaned_sprint-final-restore.csv
quarantine_csv=artifacts\quarantine\quarantine_sprint-final-restore.csv
```

---

## 2. Một quyết định kỹ thuật

**Quyết định: Ghi log theo từng dòng (append mode) thay vì structured JSON log.**

Hàm `_log(path, line)` ghi từng dòng `key=value` ra file `.log` theo append mode, và `print()` ra stdout đồng thời. Tôi cân nhắc dùng Python `logging` module hoặc JSON log, nhưng chọn text line vì:

1. **Grep-friendly:** Giảng viên và CI script có thể `grep "quarantine_records=" run_*.log` ngay mà không cần parser.
2. **Ít dependency:** Không cần thư viện ngoài; format đủ đơn giản để `instructor_quick_check.py` parse.
3. **Incremental debug:** Mỗi step ghi ngay khi hoàn thành → nếu pipeline crash giữa chừng, log vẫn có thông tin đến bước đó.

Trade-off chấp nhận được: không phải JSON nên không parse được bằng `json.loads()` trực tiếp — nhưng manifest đã dùng JSON để bù lại.

---

## 3. Một lỗi / anomaly đã xử lý

**Triệu chứng:** Chạy `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate` lần đầu bị exit code 1 với traceback:

```
UnicodeEncodeError: 'charmap' codec can't encode character '\u2192' in position 45
```

**Metric / check phát hiện:** Python traceback trên Windows terminal (codepage cp1252), dòng 91 của `etl_pipeline.py`.

**Fix:** Thay ký tự `→` (U+2192) bằng ASCII `=>` trong chuỗi log:
```python
# Trước:
log("WARN: expectation failed but --skip-validate → tiếp tục embed...")
# Sau:
log("WARN: expectation failed but --skip-validate => tiep tuc embed...")
```

**Bài học:** Luôn test trên Windows terminal trước khi submit vì Python mặc định dùng codepage hệ thống khi `print()` ra stdout. Giải pháp dài hạn: set `PYTHONIOENCODING=utf-8` hoặc dùng `sys.stdout.reconfigure(encoding='utf-8')`.

---

## 4. Bằng chứng trước / sau

**run_id: inject-bad** (inject pipeline — trước fix):
```
expectation[refund_no_stale_14d_window] FAIL (halt) :: violations=1
WARN: expectation failed but --skip-validate => tiep tuc embed (chi dung cho demo Sprint 3).
```

**run_id: sprint-final-restore** (clean pipeline — sau fix):
```
expectation[refund_no_stale_14d_window] OK (halt) :: violations=0
embed_prune_removed=1
PIPELINE_OK
```

`embed_prune_removed=1` xác nhận chunk "14 ngày làm việc" đã bị prune khỏi collection sau clean run.

---

## 5. Cải tiến tiếp theo

Nếu có thêm 2 giờ, tôi sẽ thêm **ingest từ nhiều nguồn**: hiện tại `cmd_run()` chỉ đọc 1 file CSV. Tôi sẽ hỗ trợ `--raw` nhận **glob pattern** (vd `data/raw/*.csv`) và merge tất cả files trước khi clean, ghi `source_files=["file1.csv","file2.csv"]` vào manifest. Điều này mô phỏng thực tế hơn khi nhiều team export ra nhiều files batch riêng.
