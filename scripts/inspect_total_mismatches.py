
import csv
import json
import re
from pathlib import Path

from app.modules.ocr import (
    read_image_text,
    extract_party_names_by_layout,
)
from app.modules.extraction import extract_fields


ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "data" / "reference" / "images"
ANNOTATION_DIR = ROOT / "data" / "reference" / "annotations"

TARGET_FILES = {
    "batch1-0167.jpg",
    "batch1-0098.jpg",
    "batch1-0476.jpg",
}


def load_annotations():
    results = {}

    for csv_path in sorted(ANNOTATION_DIR.glob("*.csv")):
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                filename = Path(
                    str(row.get("File Name", "")).strip()
                ).name

                if filename and filename not in results:
                    results[filename] = row

    return results


def load_images():
    image_map = {}

    for path in sorted(IMAGE_DIR.rglob("*")):
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            image_map.setdefault(path.name, path)

    return image_map


def print_relevant_lines(text):
    keywords = (
        r"total|amount|due|subtotal|gross|net|tax|vat|summary|"
        r"seller|client|bill\s+from|bill\s+to|invoice"
    )

    print("\nRELEVANT OCR LINES:")

    for line in text.splitlines():
        if re.search(keywords, line, re.IGNORECASE):
            print(repr(line))


def main():
    annotations = load_annotations()
    image_map = load_images()

    for filename in sorted(TARGET_FILES):
        print("\n" + "=" * 85)
        print("FILE:", filename)

        row = annotations.get(filename)
        image_path = image_map.get(filename)

        if row is None:
            print("ERROR: Annotation not found.")
            continue

        if image_path is None:
            print("ERROR: Image not found.")
            continue

        try:
            truth = json.loads(row.get("Json Data", "{}") or "{}")
        except json.JSONDecodeError as exc:
            print("ERROR: Invalid annotation JSON:", exc)
            continue

        invoice = truth.get("invoice", {}) or {}
        subtotal = truth.get("subtotal", {}) or {}

        print("\nGROUND-TRUTH VALUES")
        print("Invoice number:", repr(invoice.get("invoice_number")))
        print("Seller:", repr(invoice.get("seller_name")))
        print("Client:", repr(invoice.get("client_name")))
        print("Subtotal object:", repr(subtotal))
        print("Invoice annotation keys:", list(invoice.keys()))

        try:
            text = read_image_text(image_path)
            fields = extract_fields(text)

            print("\nREGEX EXTRACTION")
            print("Invoice number:", repr(fields.get("invoice_no")))
            print("Seller:", repr(fields.get("seller")))
            print("Client:", repr(fields.get("client")))
            print("Total raw:", repr(fields.get("total_raw")))
            print("Total numeric:", repr(fields.get("total")))

            print("\nLAYOUT-BASED PARTY EXTRACTION")
            try:
                layout_fields = extract_party_names_by_layout(image_path)
                print(repr(layout_fields))
            except Exception as exc:
                print(
                    "Layout extraction error:",
                    f"{type(exc).__name__}: {exc}",
                )

            print_relevant_lines(text)

            if filename == "batch1-0476.jpg":
                print("\nFULL OCR TEXT FOR PARTY-NAME ANALYSIS:")
                print(text)

        except Exception as exc:
            print(
                "OCR/EXTRACTION ERROR:",
                f"{type(exc).__name__}: {exc}",
            )


if __name__ == "__main__":
    main()
