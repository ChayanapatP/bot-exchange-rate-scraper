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

API_URL = (
    "https://www.bot.or.th/content/bot/th/statistics/exchange-rate/"
    "jcr:content/root/container/statisticstable2.results.level3cache.json"
)

DEFAULT_OUTFILE = "exchange_rate.txt"


def fetch_data() -> dict:
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(API_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def extract_currency_row(data: dict, currency: str) -> dict:
    for row in data.get("responseContent", []):
        if row.get("currency_id") == currency.upper():
            return row
    raise ValueError(f"Currency '{currency}' not found in BOT exchange rate data")


def extract_weighted_average(data: dict) -> str:
    """Pull the interbank weighted-average rate out of the 'description' HTML field."""
    description = data.get("description", "")
    match = re.search(r">([\d]+\.[\d]+)<", description)
    if not match:
        plain_text = re.sub(r"<[^>]+>", "", description)
        match = re.search(r"(\d+\.\d+)", plain_text)
    return match.group(1) if match else ""


def append_rate(row: dict, weighted_avg: str, outfile: Path) -> str:
    date = row["period"]  # e.g. "2026-09-04"
    currency = row["currency_id"]
    buying_transfer = row["buying_transfer"]
    selling = row["selling"]

    line = (
        f"{date},{currency},buying={buying_transfer},selling={selling},"
        f"weighted_avg={weighted_avg}\n"
    )

    # Avoid appending a duplicate line for a date/currency already recorded.
    if outfile.exists():
        existing = outfile.read_text(encoding="utf-8").splitlines()
        prefix = f"{date},{currency},"
        if any(existing_line.startswith(prefix) for existing_line in existing):
            return ""

    with outfile.open("a", encoding="utf-8") as f:
        f.write(line)

    return line


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape BOT exchange rate and append to a text file.")
    parser.add_argument("--currency", default="USD", help="Currency code, e.g. USD, EUR, JPY (default: USD)")
    parser.add_argument("--outfile", default=DEFAULT_OUTFILE, help=f"Output text file (default: {DEFAULT_OUTFILE})")
    args = parser.parse_args()

    outfile = Path(args.outfile)

    try:
        data = fetch_data()
        row = extract_currency_row(data, args.currency)
        weighted_avg = extract_weighted_average(data)
    except Exception as e:
        print(f"Error fetching exchange rate: {e}", file=sys.stderr)
        sys.exit(1)

    line = append_rate(row, weighted_avg, outfile)
    if line:
        print(f"Appended: {line.strip()}")
    else:
        print(f"Rate for {row['period']} ({row['currency_id']}) already recorded, skipped.")


if __name__ == "__main__":
    main()
