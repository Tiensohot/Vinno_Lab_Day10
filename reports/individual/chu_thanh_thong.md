# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Chu Thành Thông  
**Vai trò:** Embed & Idempotency Owner  
**Ngày nộp:** 2026-04-15  
**run_id:** sprint-final-restore

---

## 1. Tôi phụ trách phần nào?

**File / module:**

- `etl_pipeline.py` — hàm `cmd_embed_internal()` (dòng 131–177): kết nối ChromaDB, upsert `chunk_id`, logic **prune id thừa**, log `embed_upsert count` và `embed_prune_removed`.
- `eval_retrieval.py` — toàn bộ: query collection, so sánh keyword `must_contain_any` / `must_not_contain`, ghi `before_after_eval.csv`.
- Chạy và giám sát 3 eval scenarios:
  - `artifacts/eval/after_clean_eval.csv` (top-k=3, clean)
  - `artifacts/eval/before_inject_eval_k10.csv` (top-k=10, inject — before)
  - `artifacts/eval/before_after_eval.csv` (top-k=10, clean — after)

**Kết nối với thành viên khác:**

Tôi nhận `cleaned_path` từ Hùng (pipeline orchestrator) → đọc cleaned CSV → upsert Chroma. Phú (Quality) cung cấp danh sách `chunk_id` sạch; tôi dùng nó để prune collection. Tiến (Monitoring) đọc manifest tôi tham gia ghi để check freshness.

**Bằng chứng:**
```
embed_upsert count=8 collection=day10_kb
embed_prune_removed=1  ← log khi clean run sau inject
```

---

## 2. Một quyết định kỹ thuật

**Quyết định: Prune trước upsert, không phải sau.**

Logic prune trong `cmd_embed_internal()`:
```python
prev = col.get(include=[])
prev_ids = set(prev.get("ids") or [])
drop = sorted(prev_ids - set(ids))  # ids trong cleaned hiện tại
if drop:
    col.delete(ids=drop)
    log(f"embed_prune_removed={len(drop)}")
col.upsert(ids=ids, documents=documents, metadatas=metadatas)
```

**Tại sao prune trước:** Nếu upsert trước rồi mới prune, có một khoảng thời gian ngắn collection tồn tại cả chunk cũ lẫn chunk mới → nếu có query đến đúng lúc đó, có thể trả về kết quả sai. Prune trước đảm bảo "atomic-ish publish": xóa hết stale, rồi mới thêm mới.

**Trade-off:** Trong khoảng giữa delete và upsert, collection tạm thời thiếu một số chunk → query có thể miss. Giải pháp production: dùng **shadow collection** (blue-green swap) nhưng phức tạp hơn scope lab.

---

## 3. Một lỗi / anomaly đã xử lý

**Triệu chứng:** Sau khi chạy inject pipeline (`run-id inject-bad`) rồi chạy eval với `--top-k 3`, `hits_forbidden` cho `q_refund_window` vẫn là `no` — mặc dù biết rằng "14 ngày" chunk đã được embed.

**Metric phát hiện:** So sánh `before_inject_eval.csv` (top-k=3) và `before_inject_eval_k10.csv` (top-k=10):
- top-k=3: `hits_forbidden=no` (chunk stale không rank trong top-3)
- top-k=10: `hits_forbidden=yes` (chunk stale lộ ra ở rank 4–10)

**Fix / insight:** Chunk "14 ngày làm việc kể từ xác nhận đơn (ghi chú: bản sync cũ policy-v3 — lỗi migration)" có **semantic similarity thấp hơn** với query "Khách hàng có bao nhiêu ngày để yêu cầu hoàn tiền?" so với chunk "7 ngày làm việc kể từ thời điểm xác nhận đơn hàng" (không có phần "(ghi chú: bản sync cũ...)"). Model đánh giá chunk sạch là relevant hơn.

**Bài học:** Retrieval eval với top-k nhỏ không phải là công cụ đủ mạnh để phát hiện **tất cả** stale data — Expectation suite là cần thiết và đáng tin cậy hơn.

---

## 4. Bằng chứng trước / sau

**run_id: inject-bad** (`artifacts/eval/before_inject_eval_k10.csv`, top-k=10):
```
q_refund_window,...,contains_expected=yes,hits_forbidden=yes,...,10
```

**run_id: sprint-final-restore** (`artifacts/eval/before_after_eval.csv`, top-k=10):
```
q_refund_window,...,contains_expected=yes,hits_forbidden=no,...,10
q_leave_version,...,contains_expected=yes,hits_forbidden=no,top1_doc_expected=yes,10
```

Tất cả 4 câu: `contains_expected=yes`, `hits_forbidden=no`, và `q_leave_version` `top1_doc_expected=yes` sau clean run.

---

## 5. Cải tiến tiếp theo

Nếu có thêm 2 giờ, tôi sẽ thêm **eval slice theo `doc_id`**: hiện tại eval chỉ có 4 câu chung chung. Tôi sẽ tạo ít nhất 2 câu riêng cho mỗi `doc_id` (10 câu tổng) và ghi cột `source_doc` trong CSV kết quả để có breakdown precision/recall per-document. Đây tiếp cận gần Distinction (c): "eval mở rộng (bộ slice ≥5 câu) có mô tả phương pháp + 1 ví dụ fail/pass".
