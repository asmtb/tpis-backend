"""
progress.py — บันทึก/โหลด progress เพื่อ resume ได้ถ้า crash กลางคัน
บันทึกเป็น JSON ไฟล์เดียว อัพเดทหลังทุก province เสร็จ
"""

import json
from pathlib import Path


class ProgressTracker:
    def __init__(self, output_dir: str = "led_output"):
        self.path = Path(output_dir) / "progress.json"
        self.state = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                print(f"[Progress] โหลด progress เดิมจาก {self.path}")
                print(f"           จังหวัดที่เสร็จแล้ว: {data.get('completed_provinces', [])}")
                return data
            except Exception:
                pass
        return {"completed_provinces": [], "failed_provinces": []}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def is_completed(self, province_id: str) -> bool:
        return province_id in self.state["completed_provinces"]

    def mark_done(self, province_id: str):
        if province_id not in self.state["completed_provinces"]:
            self.state["completed_provinces"].append(province_id)
        # ลบออกจาก failed ถ้าเคยอยู่
        self.state["failed_provinces"] = [
            p for p in self.state["failed_provinces"] if p != province_id
        ]
        self._save()

    def mark_failed(self, province_id: str):
        if province_id not in self.state["failed_provinces"]:
            self.state["failed_provinces"].append(province_id)
        self._save()

    def reset(self):
        """เริ่มใหม่ทั้งหมด — ลบ progress เก่าทิ้ง"""
        self.state = {"completed_provinces": [], "failed_provinces": []}
        self._save()
        print("[Progress] Reset แล้ว จะเริ่มดึงข้อมูลใหม่ทั้งหมด")

    @property
    def completed(self) -> list:
        return self.state["completed_provinces"]

    @property
    def failed(self) -> list:
        return self.state["failed_provinces"]
