"""
Cleaning rules — raw export → cleaned rows + quarantine.

Baseline gồm các failure mode mở rộng (allowlist doc_id, parse ngày, HR stale version).
Sinh viên thêm ≥3 rule mới: mỗi rule phải ghi `metric_impact` (xem README — chống trivial).

Rule mới (Sprint 2 — nhóm):
  Rule 7 (normalize_doc_id_whitespace): Strip khoảng trắng đầu/cuối trường doc_id trước khi
      kiểm tra allowlist. Impact đo được: Row 11 CSV (' hr_leave_policy ') được RESCUED thay vì
      bị quarantine unknown_doc_id — quarantine_records giảm 1 khi rule hoạt động.

  Rule 8 (quarantine_few_words): Quarantine chunk_text có < 3 từ (sau strip) là noise ngữ nghĩa
      không đủ ngữ cảnh cho retrieval. Impact đo được: Row 12 CSV ('Ok') bị quarantine
      → quarantine_records tăng 1 so với chỉ dùng baseline length check.

  Rule 9 (quarantine_stale_source_export): Quarantine chunk có exported_at trước 2020-01-01
      — dấu hiệu re-export từ kho lưu trữ cũ / clock anomaly. Impact đo được: Row 13 CSV
      (exported_at=2018-06-15) bị quarantine → quarantine_records tăng 1.
"""

from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Khớp export hợp lệ trong lab (mở rộng khi nhóm thêm doc mới — phải đồng bộ contract).
ALLOWED_DOC_IDS = frozenset(
    {
        "policy_refund_v4",
        "sla_p1_2026",
        "it_helpdesk_faq",
        "hr_leave_policy",
        "access_control_sop",  # Rule 9-b: thêm doc mới vào allowlist — đồng bộ data_contract.yaml
    }
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DMY_SLASH = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")

# Ngưỡng cho Rule 9: exported_at trước mốc này là stale source export
_STALE_EXPORT_CUTOFF = "2020-01-01T00:00:00"


def _norm_text(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()


def _stable_chunk_id(doc_id: str, chunk_text: str, seq: int) -> str:
    h = hashlib.sha256(f"{doc_id}|{chunk_text}|{seq}".encode("utf-8")).hexdigest()[:16]
    return f"{doc_id}_{seq}_{h}"


def _normalize_effective_date(raw: str) -> Tuple[str, str]:
    """
    Trả về (iso_date, error_reason).
    iso_date rỗng nếu không parse được.
    """
    s = (raw or "").strip()
    if not s:
        return "", "empty_effective_date"
    if _ISO_DATE.match(s):
        return s, ""
    m = _DMY_SLASH.match(s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}", ""
    return "", "invalid_effective_date_format"


def _word_count(text: str) -> int:
    """Đếm số từ trong chuỗi sau khi strip."""
    return len((text or "").strip().split())


def _parse_exported_at(ts: str) -> datetime | None:
    """Parse exported_at thành datetime UTC; trả None nếu không parse được."""
    s = (ts or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


# Mốc cutoff cho Rule 9 (parse một lần)
_STALE_CUTOFF_DT: datetime = datetime.fromisoformat(_STALE_EXPORT_CUTOFF).replace(
    tzinfo=timezone.utc
)


def load_raw_csv(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def clean_rows(
    rows: List[Dict[str, str]],
    *,
    apply_refund_window_fix: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Trả về (cleaned, quarantine).

    Baseline (mở rộng theo narrative Day 10):
    1) Quarantine: doc_id không thuộc allowlist (export lạ / catalog sai).
    2) Chuẩn hoá effective_date sang YYYY-MM-DD; quarantine nếu không parse được.
    3) Quarantine: chunk hr_leave_policy có effective_date < 2026-01-01 (bản HR cũ / conflict version).
    4) Quarantine: chunk_text rỗng hoặc effective_date rỗng sau chuẩn hoá.
    5) Loại trùng nội dung chunk_text (giữ bản đầu).
    6) Fix stale refund: policy_refund_v4 chứa '14 ngày làm việc' → 7 ngày.

    Rule mới (Sprint 2):
    7) normalize_doc_id_whitespace: strip leading/trailing whitespace khỏi doc_id trước
       khi check allowlist — rescues row có doc_id như ' hr_leave_policy '.
    8) quarantine_few_words: quarantine chunk_text có < 3 từ (semantic noise).
    9) quarantine_stale_source_export: quarantine nếu exported_at < 2020-01-01 (archive bleed).
    """
    quarantine: List[Dict[str, Any]] = []
    seen_text: set[str] = set()
    cleaned: List[Dict[str, Any]] = []
    seq = 0

    for raw in rows:
        # Rule 7 — normalize_doc_id_whitespace: strip trước khi kiểm tra
        doc_id = (raw.get("doc_id") or "").strip()
        text = raw.get("chunk_text", "")
        eff_raw = raw.get("effective_date", "")
        exported_at = raw.get("exported_at", "")

        if doc_id not in ALLOWED_DOC_IDS:
            quarantine.append({**raw, "reason": "unknown_doc_id"})
            continue

        eff_norm, eff_err = _normalize_effective_date(eff_raw)
        if eff_err == "empty_effective_date":
            quarantine.append({**raw, "reason": "missing_effective_date"})
            continue
        if eff_err == "invalid_effective_date_format":
            quarantine.append({**raw, "reason": eff_err, "effective_date_raw": eff_raw})
            continue

        if doc_id == "hr_leave_policy" and eff_norm < "2026-01-01":
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_policy_effective_date",
                    "effective_date_normalized": eff_norm,
                }
            )
            continue

        if not text:
            quarantine.append({**raw, "reason": "missing_chunk_text"})
            continue

        # Rule 9 — quarantine_stale_source_export: exported_at trước 2020 là archive bleed
        exp_dt = _parse_exported_at(exported_at)
        if exp_dt is not None and exp_dt < _STALE_CUTOFF_DT:
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_source_export",
                    "exported_at_parsed": exported_at,
                    "cutoff": _STALE_EXPORT_CUTOFF,
                }
            )
            continue

        # Rule 8 — quarantine_few_words: chunk < 3 từ là noise ngữ nghĩa
        if _word_count(text) < 3:
            quarantine.append(
                {
                    **raw,
                    "reason": "chunk_too_few_words",
                    "word_count": _word_count(text),
                }
            )
            continue

        key = _norm_text(text)
        if key in seen_text:
            quarantine.append({**raw, "reason": "duplicate_chunk_text"})
            continue
        seen_text.add(key)

        fixed_text = text
        if apply_refund_window_fix and doc_id == "policy_refund_v4":
            if "14 ngày làm việc" in fixed_text:
                fixed_text = fixed_text.replace(
                    "14 ngày làm việc",
                    "7 ngày làm việc",
                )
                fixed_text += " [cleaned: stale_refund_window]"

        seq += 1
        cleaned.append(
            {
                "chunk_id": _stable_chunk_id(doc_id, fixed_text, seq),
                "doc_id": doc_id,
                "chunk_text": fixed_text,
                "effective_date": eff_norm,
                "exported_at": exported_at or "",
            }
        )

    return cleaned, quarantine


def write_cleaned_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at\n", encoding="utf-8")
        return
    fieldnames = ["chunk_id", "doc_id", "chunk_text", "effective_date", "exported_at"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_quarantine_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at,reason\n", encoding="utf-8")
        return
    keys: List[str] = []
    seen_k: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen_k:
                seen_k.add(k)
                keys.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore", restval="")
        w.writeheader()
        for r in rows:
            w.writerow(r)
