# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Phung Huu Phu  
**Vai trò:** Cleaning / Quality Owner  
**Ngày nộp:** 2026-04-15  
**Độ dài:** ~540 từ

---

## 1. Tôi phụ trách phần nào?

**File / module:**

- `transform/cleaning_rules.py`
- `quality/expectations.py`
- `etl_pipeline.py` (hành vi khi expectation fail + log)
- `artifacts/quarantine/*.csv` (evidence sau khi áp dụng rule)

Trong project Day 10, tôi phụ trách tầng Cleaning/Quality, tức là phần quyết định dữ liệu nào được publish vào cleaned dataset để đi tiếp sang bước embed, và dữ liệu nào phải quarantine để tránh làm bẩn index. Tôi tập trung mở rộng rule xử lý dữ liệu bẩn ở `cleaning_rules.py`, đồng thời bổ sung expectation trong `quality/expectations.py` để có guardrail rõ ràng giữa mức `warn` và `halt`. Mục tiêu là giảm rủi ro retrieval lấy nhầm chunk stale hoặc chunk không đủ ngữ nghĩa, vì đây là nguyên nhân trực tiếp làm agent trả lời sai nhưng nhìn qua vẫn có vẻ hợp lý.

**Kết nối với thành viên khác:**

Tôi nhận raw export từ ingestion owner, trả lại `cleaned_csv` và `quarantine_csv` để embed owner cập nhật Chroma. Monitoring/docs owner dùng số liệu `cleaned_records`, `quarantine_records` và các reason trong quarantine để viết runbook và giải thích quality decision.

**Bằng chứng (code/comment):**

- Thêm Rule 7/8/9 trong `cleaning_rules.py` với mô tả impact đo được.
- Thêm expectation `unique_chunk_ids` (halt) và `effective_date_not_before_2000` (warn) trong `expectations.py`.
- Cập nhật log warning trong `etl_pipeline.py` cho flow `--skip-validate`.

---

## 2. Một quyết định kỹ thuật

Quyết định kỹ thuật quan trọng nhất của tôi là tách rõ “cleaning để rescue dữ liệu hợp lệ” và “quality gate để chặn dữ liệu nguy hiểm”, thay vì chỉ làm một lớp filter cứng. Cụ thể, Rule 7 chuẩn hoá `doc_id` bằng cách strip khoảng trắng trước khi check allowlist, giúp cứu được bản ghi kiểu `' hr_leave_policy '` khỏi bị loại oan. Ngược lại, Rule 8 và Rule 9 cố ý nghiêm hơn để đưa vào quarantine các chunk có dưới 3 từ (`chunk_too_few_words`) hoặc nguồn export quá cũ (`stale_source_export` trước `2020-01-01T00:00:00`).

Ở lớp expectation, tôi đặt `unique_chunk_ids` là `halt` vì trùng chunk id có thể gây lỗi idempotency và làm index không đáng tin cậy khi rerun. Trong khi đó, `effective_date_not_before_2000` để `warn` nhằm cảnh báo chất lượng metadata mà không làm dừng toàn bộ pipeline ngay lập tức. Cách phân tầng này giúp pipeline vừa an toàn cho publish boundary, vừa linh hoạt cho vận hành thực tế.

---

## 3. Một lỗi hoặc anomaly đã xử lý

Anomaly tôi xử lý là dữ liệu “noise nhưng không rỗng”, làm baseline cũ dễ cho qua dù giá trị ngữ nghĩa thấp hoặc nguồn không đáng tin. Triệu chứng thấy rõ khi inspect quarantine và cleaned: có các dòng ngắn kiểu `"Ok"` và dòng có `exported_at` quá cũ so với luồng hiện tại.

Tôi phát hiện bằng kiểm tra trực tiếp file `artifacts/quarantine/quarantine_inject-bad.csv` (và bản `quarantine_sprint-final.csv`), trong đó xuất hiện các reason mới:

- `chunk_too_few_words` với `word_count=1`
- `stale_source_export` với `exported_at_parsed=2018-06-15T00:00:00`, cutoff `2020-01-01T00:00:00`

Trước khi thêm rule, các dòng này có thể lọt qua và đi vào bước embed, gây nhiễu retrieval top-k. Sau khi fix, chúng bị quarantine có giải thích rõ reason và metadata đi kèm. Nhờ vậy, quality evidence không chỉ là “đã drop record” mà còn có khả năng truy vết cụ thể vì sao record bị loại.

---

## 4. Bằng chứng trước / sau

Tôi dùng evidence theo run/scenario trong artifacts:

- `artifacts/quarantine/quarantine_ci-smoke.csv` và `quarantine_ci-smoke2.csv` (baseline cũ) chủ yếu có các reason như `duplicate_chunk_text`, `missing_effective_date`, `stale_hr_policy_effective_date`, `unknown_doc_id`.
- `artifacts/quarantine/quarantine_inject-bad.csv` và `quarantine_sprint-final.csv` (sau khi bổ sung rule) có thêm reason mới `chunk_too_few_words` và `stale_source_export`.

Hai dòng tiêu biểu:

- `...,policy_refund_v4,Ok,...,reason=chunk_too_few_words,...,word_count=1,...`
- `...,it_helpdesk_faq,...,2018-06-15T00:00:00,reason=stale_source_export,...,cutoff=2020-01-01T00:00:00`

Bằng chứng này cho thấy quality gate đã bắt được anomaly mà baseline chưa bao phủ, và tác động thể hiện trực tiếp trên artifact thực tế.

---

## 5. Cải tiến tiếp theo

Nếu có thêm 2 giờ, tôi sẽ bổ sung `artifacts/eval/before_after_eval.csv` cho đúng cặp scenario clean vs inject, rồi nối thẳng expectation result với retrieval metric (ví dụ `hits_forbidden`, `top1_doc_matches`). Như vậy báo cáo sẽ đi từ “đã quarantine đúng” đến “agent trả lời tốt hơn sau fix” một cách định lượng, sát rubric Merit/Distinction hơn.
