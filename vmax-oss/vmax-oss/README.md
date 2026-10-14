# VMAX (open source edition)

แยกมาจากไฟล์ `VMAX_ALL_IN_ONE_CENTRAL_API_CONNECTED_HERMES_REPAIR_CENTER-2.py`
Extracted from the all-in-one VMAX file.

## โครงสร้าง / Layout
| Path | คำอธิบาย |
|---|---|
| `vmax/core.py` | แอปหลัก (Flask + engine ทั้งหมด) ตัด vault เข้ารหัสและระบบปลดล็อกด้วยวลีออกแล้ว |
| `vmax/modules/*.py` | โมดูลที่ฝังเป็น base64 ในไฟล์เดิม: anniversary, viewpoint, selbox banner, armor wiki, gunsmith, ad overlay, bridge templates |
| `vmax/modules/maps/` | โมดูลแผนที่ (Ban Rimpa, Wiang Valley) |
| `vmax/sdk/` | Game-service SDK (Python / JS) และ kernel boot ASM |

หมายเหตุ: `core.py` ยังมีโมดูลชุดเดิมฝังอยู่ด้วย (เพื่อให้รันได้เหมือนเดิม) ไฟล์ใน `vmax/modules` เป็นสำเนาแยกสำหรับอ่าน/แก้/นำไปใช้ต่อ

## ติดตั้งและรัน
```bash
pip install -r requirements.txt          # แกนหลัก
pip install -r requirements-optional.txt # ฟีเจอร์เสริม (เลือกเฉพาะที่ใช้)
python -m vmax
```

## ตัวแปรสภาพแวดล้อม
- `VMAX_PASSWORD_PEPPER` — ค่าสุ่มสำหรับแฮชรหัสผ่าน (สร้างด้วย `python -c "import secrets; print(secrets.token_hex(32))"`)
- `VMAX_ADMIN=1` — เปิดฟังก์ชันแอดมิน (ค่าเริ่มต้น: ล็อก)
- `VMAX_ADMIN_PASSWORD` — รหัสผ่านแอดมินเริ่มต้น (ถ้าไม่ตั้ง ระบบสุ่มให้)
- `VMAX_NEEDLE3_AUTO_INSTALL=0` — ปิดการ pip install อัตโนมัติ

## ข้อควรระวัง
- โค้ดเดิมเป็นไฟล์เดียวขนาดใหญ่ (~126k บรรทัด) ยังไม่ได้แตกเป็นแพ็กเกจย่อยทั้งหมด เพราะมีตัวแปร global ผูกกันมาก
- เส้นทางแอดมินบางจุดใน core จับ exception แล้วข้าม (`except Exception: pass`) ควรรีวิวก่อนนำไปใช้จริงบนเซิร์ฟเวอร์สาธารณะ
- ยังไม่ได้ทดสอบรันจริง ตรวจแค่ว่าทุกไฟล์ compile ผ่าน

## License
MIT — ดู `LICENSE` (เปลี่ยนได้ตามต้องการก่อนเผยแพร่)
