"""
Scrape the daily USD/THB (or other currency) exchange rate from the
Bank of Thailand website and append it to a text file.

Source page (rendered via JS): https://www.bot.or.th/th/statistics/exchange-rate.html
Underlying data API used here (same data, no browser required):
https://www.bot.or.th/content/bot/th/statistics/exchange-rate/jcr:content/root/container/statisticstable2.results.level3cache.json

That response also embeds the interbank weighted-average rate
("อัตราแลกเปลี่ยนถัวเฉลี่ยถ่วงน้ำหนักระหว่างธนาคาร") as a number inside its
"description" HTML field, which is extracted here via regex.

Usage:
    python bot_exchange_rate.py
    python bot_exchange_rate.py --currency EUR
    python bot_exchange_rate.py --currency USD --outfile my_rates.txt
"""

import argparse
import re
import sys
from pathlib import Path

import requests

# URL ของ API (JSON) ที่หน้าเว็บ ธปท. เรียกใช้จริงเบื้องหลัง เพื่อดึงตารางอัตราแลกเปลี่ยนประจำวัน
API_URL = (
    "https://www.bot.or.th/content/bot/th/statistics/exchange-rate/"
    "jcr:content/root/container/statisticstable2.results.level3cache.json"
)

# ชื่อไฟล์ผลลัพธ์เริ่มต้น ถ้าไม่ระบุ --outfile ตอนรันสคริปต์
DEFAULT_OUTFILE = "exchange_rate.txt"


def fetch_data() -> dict:
    # Step 1: ยิง HTTP GET ไปที่ API ของ ธปท. พร้อมตั้ง User-Agent กันบางเซิร์ฟเวอร์บล็อก request ที่ไม่มี header นี้
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(API_URL, headers=headers, timeout=15)
    # Step 2: ถ้า HTTP status ไม่ใช่ 2xx (เช่น 404, 500) ให้โยน exception ออกไปทันที
    resp.raise_for_status()
    # Step 3: แปลง response body (ข้อความ JSON) ให้เป็น dict ของ Python แล้วส่งคืน
    return resp.json()


def extract_currency_row(data: dict, currency: str) -> dict:
    # Step 1: ข้อมูล JSON ที่ได้จะมี key "responseContent" เป็น list ของแต่ละสกุลเงิน (USD, EUR, JPY, ...)
    # วนลูปหาแถวที่ currency_id ตรงกับสกุลเงินที่ผู้ใช้ต้องการ (แปลงเป็นตัวพิมพ์ใหญ่ก่อนเทียบ เช่น usd -> USD)
    for row in data.get("responseContent", []):
        if row.get("currency_id") == currency.upper():
            return row
    # Step 2: ถ้าวนจนจบ list แล้วไม่เจอสกุลเงินนั้น ให้แจ้ง error ว่าไม่พบ
    raise ValueError(f"Currency '{currency}' not found in BOT exchange rate data")


def extract_weighted_average(data: dict) -> str:
    """Pull the interbank weighted-average rate out of the 'description' HTML field."""
    # Step 1: อัตราถัวเฉลี่ยถ่วงน้ำหนักระหว่างธนาคาร ไม่ได้แยกเป็น field ของตัวเอง
    # แต่ถูกฝังอยู่ในข้อความ HTML ของ key "description" เช่น "...ธนาคาร <span>32.932</span> บาท..."
    description = data.get("description", "")

    # Step 2: ลองหาตัวเลขทศนิยมที่อยู่ระหว่าง ">" กับ "<" ก่อน (กรณีตัวเลขถูกครอบด้วย <span>ตัวเลข</span>)
    match = re.search(r">([\d]+\.[\d]+)<", description)

    # Step 3: ถ้าหาไม่เจอด้วยวิธีแรก ให้ตัดแท็ก HTML ทั้งหมดออกก่อน แล้วค่อยหาตัวเลขทศนิยมตัวแรกในข้อความล้วน ๆ
    if not match:
        plain_text = re.sub(r"<[^>]+>", "", description)
        match = re.search(r"(\d+\.\d+)", plain_text)

    # Step 4: ถ้าเจอ ให้คืนค่าตัวเลขที่จับได้ (string) ถ้าไม่เจอเลยให้คืนสตริงว่าง
    return match.group(1) if match else ""


def append_rate(row: dict, weighted_avg: str, outfile: Path) -> str:
    # Step 1: ดึงค่าที่ต้องใช้ออกจากข้อมูลแถวสกุลเงินที่ส่งเข้ามา
    date = row["period"]  # e.g. "2026-09-04"
    currency = row["currency_id"]
    buying_transfer = row["buying_transfer"]
    selling = row["selling"]

    # Step 2: ประกอบเป็นบรรทัดข้อความเดียว คั่นด้วยจุลภาค พร้อม \n ต่อท้ายเพื่อขึ้นบรรทัดใหม่
    line = (
        f"{date},{currency},buying={buying_transfer},selling={selling},"
        f"weighted_avg={weighted_avg}\n"
    )

    # Step 3: ถ้าไฟล์ผลลัพธ์มีอยู่แล้ว ให้อ่านทุกบรรทัดเดิมมาตรวจสอบก่อน
    # เพื่อกันไม่ให้บันทึกซ้ำ ถ้าวันที่และสกุลเงินเดียวกันนี้เคยถูกบันทึกไปแล้ว (เช่นรันสคริปต์ซ้ำในวันเดียวกัน)
    if outfile.exists():
        existing = outfile.read_text(encoding="utf-8").splitlines()
        prefix = f"{date},{currency},"
        if any(existing_line.startswith(prefix) for existing_line in existing):
            return ""  # พบข้อมูลซ้ำ -> ไม่บันทึกซ้ำ คืนค่าว่างกลับไป

    # Step 4: เปิดไฟล์ในโหมด append ("a") แล้วเขียนบรรทัดใหม่ต่อท้ายไฟล์ (ไม่ลบข้อมูลเดิม)
    with outfile.open("a", encoding="utf-8") as f:
        f.write(line)

    # Step 5: คืนค่าบรรทัดที่เพิ่งบันทึกไป เพื่อให้ main() นำไปแสดงผลได้
    return line


def main() -> None:
    # Step 1: ตั้งค่า command-line arguments ที่รับได้ 2 ตัว คือ --currency (สกุลเงิน) และ --outfile (ไฟล์ปลายทาง)
    parser = argparse.ArgumentParser(description="Scrape BOT exchange rate and append to a text file.")
    parser.add_argument("--currency", default="USD", help="Currency code, e.g. USD, EUR, JPY (default: USD)")
    parser.add_argument("--outfile", default=DEFAULT_OUTFILE, help=f"Output text file (default: {DEFAULT_OUTFILE})")
    args = parser.parse_args()

    # Step 2: แปลง path ของไฟล์ปลายทางจาก string ให้เป็น Path object เพื่อใช้งานง่ายขึ้น
    outfile = Path(args.outfile)

    # Step 3: ดึงข้อมูลจาก ธปท., หาแถวของสกุลเงินที่ต้องการ, และหาค่าอัตราถัวเฉลี่ยถ่วงน้ำหนัก
    # ถ้าขั้นตอนไหนพัง (เช่น เน็ตหลุด, สกุลเงินพิมพ์ผิด) ให้พิมพ์ error ออกทาง stderr แล้วจบโปรแกรมด้วย exit code 1
    try:
        data = fetch_data()
        row = extract_currency_row(data, args.currency)
        weighted_avg = extract_weighted_average(data)
    except Exception as e:
        print(f"Error fetching exchange rate: {e}", file=sys.stderr)
        sys.exit(1)

    # Step 4: บันทึกข้อมูลลงไฟล์ (append_rate จะเช็คข้อมูลซ้ำให้เอง) แล้วพิมพ์สรุปผลให้ผู้ใช้เห็น
    line = append_rate(row, weighted_avg, outfile)
    if line:
        print(f"Appended: {line.strip()}")
    else:
        print(f"Rate for {row['period']} ({row['currency_id']}) already recorded, skipped.")


if __name__ == "__main__":
    # Step 5: จุดเริ่มต้นของโปรแกรมเมื่อรันไฟล์นี้ตรง ๆ ด้วยคำสั่ง python bot_exchange_rate.py
    main()
