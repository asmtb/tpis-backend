"""
landsmaps_progress.py — บันทึก/โหลด progress เพื่อ resume ได้ถ้า crash กลางคัน
ต่างจาก progress.py ของ LED (ที่ track เป็นรายจังหวัด) เพราะ landsmaps
ประมวลผลทีละ record ไม่ใช่ทีละจังหวัด จึงต้อง track เป็น "done_indices" แทน
"""

import json
from pathlib import Path


class LandsMapsProgressTracker:
    def __init__(self, progress_file: str):
        self.path = Path(progress_file)
        self.state = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                return {
                    "done_indices": set(data.get("done_indices", [])),
                    "stats": data.get("stats", {}),
                }
            except Exception:
                pass
        return {"done_indices": set(), "stats": {}}

    def is_done(self, idx: int) -> bool:
        return idx in self.state["done_indices"]

    def mark_done(self, idx: int):
        self.state["done_indices"].add(idx)

    def save(self, stats: dict):
        self.state["stats"] = stats
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({
                "done_indices": list(self.state["done_indices"]),
                "stats": stats,
            }, f, ensure_ascii=False, indent=2)

    @property
    def done_count(self) -> int:
        return len(self.state["done_indices"])
