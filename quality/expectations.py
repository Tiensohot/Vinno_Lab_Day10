"""
Expectation suite đơn giản (không bắt buộc Great Expectations).

Sinh viên có thể thay bằng GE / pydantic / custom — miễn là có halt có kiểm soát.

Expectation mới (Sprint 2):
  E7 unique_chunk_ids (halt): Tất cả chunk_id trong cleaned phải duy nhất.
      Impact: phát hiện khi cleaning rule tạo ra chunk_id trùng (hash collision / bug).
      Demo inject: nếu clean_rows có lỗi hoặc dữ liệu bị nhồi chunk_id giả trùng → halt.

  E8 effective_date_not_before_2000 (warn): Không có effective_date trước 2000-01-01.
      Impact: phát hiện ngày hiệu lực vô lý (placeholder "1900-01-01", lỗi parse ngày âm).
      Demo inject: thêm row với effective_date=1999-12-31 → expectation FAIL (warn).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass
class ExpectationResult:
    name: str
    passed: bool
    severity: str  # "warn" | "halt"
    detail: str


def run_expectations(cleaned_rows: List[Dict[str, Any]]) -> Tuple[List[ExpectationResult], bool]:
    """
    Trả về (results, should_halt).

    should_halt = True nếu có bất kỳ expectation severity halt nào fail.
    """
    results: List[ExpectationResult] = []

    # E1: có ít nhất 1 dòng sau clean
    ok = len(cleaned_rows) >= 1
    results.append(
        ExpectationResult(
            "min_one_row",
            ok,
            "halt",
            f"cleaned_rows={len(cleaned_rows)}",
        )
    )

    # E2: không doc_id rỗng
    bad_doc = [r for r in cleaned_rows if not (r.get("doc_id") or "").strip()]
    ok2 = len(bad_doc) == 0
    results.append(
        ExpectationResult(
            "no_empty_doc_id",
            ok2,
            "halt",
            f"empty_doc_id_count={len(bad_doc)}",
        )
    )

    # E3: policy refund không được chứa cửa sổ sai 14 ngày (sau khi đã fix)
    bad_refund = [
        r
        for r in cleaned_rows
        if r.get("doc_id") == "policy_refund_v4"
        and "14 ngày làm việc" in (r.get("chunk_text") or "")
    ]
    ok3 = len(bad_refund) == 0
    results.append(
        ExpectationResult(
            "refund_no_stale_14d_window",
            ok3,
            "halt",
            f"violations={len(bad_refund)}",
        )
    )

    # E4: chunk_text đủ dài
    short = [r for r in cleaned_rows if len((r.get("chunk_text") or "")) < 8]
    ok4 = len(short) == 0
    results.append(
        ExpectationResult(
            "chunk_min_length_8",
            ok4,
            "warn",
            f"short_chunks={len(short)}",
        )
    )

    # E5: effective_date đúng định dạng ISO sau clean (phát hiện parser lỏng)
    iso_bad = [
        r
        for r in cleaned_rows
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", (r.get("effective_date") or "").strip())
    ]
    ok5 = len(iso_bad) == 0
    results.append(
        ExpectationResult(
            "effective_date_iso_yyyy_mm_dd",
            ok5,
            "halt",
            f"non_iso_rows={len(iso_bad)}",
        )
    )

    # E6: không còn marker phép năm cũ 10 ngày trên doc HR (conflict version sau clean)
    bad_hr_annual = [
        r
        for r in cleaned_rows
        if r.get("doc_id") == "hr_leave_policy"
        and "10 ngày phép năm" in (r.get("chunk_text") or "")
    ]
    ok6 = len(bad_hr_annual) == 0
    results.append(
        ExpectationResult(
            "hr_leave_no_stale_10d_annual",
            ok6,
            "halt",
            f"violations={len(bad_hr_annual)}",
        )
    )

    # E7 (mới — halt): unique_chunk_ids — tất cả chunk_id phải duy nhất
    # Impact: phát hiện bug trong hàm _stable_chunk_id hoặc inject chunk_id trùng
    chunk_ids = [r.get("chunk_id") or "" for r in cleaned_rows]
    dup_ids = [cid for cid in set(chunk_ids) if chunk_ids.count(cid) > 1]
    ok7 = len(dup_ids) == 0
    results.append(
        ExpectationResult(
            "unique_chunk_ids",
            ok7,
            "halt",
            f"duplicate_chunk_ids={len(dup_ids)} examples={dup_ids[:3]}",
        )
    )

    # E8 (mới — warn): effective_date_not_before_2000 — ngày hiệu lực không được < 2000-01-01
    # Impact: phát hiện ngày placeholder lỗi (1900-01-01) hoặc parse ngày sai
    old_date = [
        r
        for r in cleaned_rows
        if (r.get("effective_date") or "") < "2000-01-01"
        and re.match(r"^\d{4}-\d{2}-\d{2}$", (r.get("effective_date") or ""))
    ]
    ok8 = len(old_date) == 0
    results.append(
        ExpectationResult(
            "effective_date_not_before_2000",
            ok8,
            "warn",
            f"pre_2000_rows={len(old_date)}",
        )
    )

    halt = any(not r.passed and r.severity == "halt" for r in results)
    return results, halt
