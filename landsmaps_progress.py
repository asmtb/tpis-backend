"""
landsmaps_progress.py — บันทึก/โหลด progress เพื่อ resume ได้ถ้า crash กลางคัน
เปลี่ยนจาก track ด้วย "index" ของไฟล์ JSON เดิม → track ด้วย "asset_id" จริง
จาก Supabase เพราะไม่มีไฟล์ led_all_assets.json ให้ index อ้างอิงอีกต่อไป (กลุ่ม 5.1)
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
                    "done_asset_ids": set(data.get("done_asset_ids", [])),
                    "stats": data.get("stats", {}),
                }
            except Exception:
                pass
        return {"done_asset_ids": set(), "stats": {}}

    def is_done(self, asset_id: int) -> bool:
        return asset_id in self.state["done_asset_ids"]

    def mark_done(self, asset_id: int):
        self.state["done_asset_ids"].add(asset_id)

    def save(self, stats: dict):
        self.state["stats"] = stats
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({
                "done_asset_ids": list(self.state["done_asset_ids"]),
                "stats": stats,
            }, f, ensure_ascii=False, indent=2)

    @property
    def done_count(self) -> int:
        return len(self.state["done_asset_ids"])
