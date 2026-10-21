
from pathlib import Path
from collections import Counter
import csv
import json

from app.modules.ocr import read_image_text
from app.modules.extraction import extract_fields, normalize_amount


ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "data" / "reference" / "images"
ANNOTATION_DIR = ROOT / "data" / "reference" / "annotations"
OUTPUT_PATH = ROOT / "results" / "amount_label_audit.json"


def rounded(value):
    if value is None:
        return None
    return round(float(value), 2)


def load_annotations():
    rows = []
    seen = set()
    duplicate_rows = 0

    for csv_path in sorted(ANNOTATION_DIR.glob("*.csv")):
        with csv_path.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                filename = Path(
                    str(row.get("File Name", "")).strip()
                ).name

                if not filename:
                    continue

                if filename in seen:
                    duplicate_rows += 1
                    continue

                seen.add(filename)
                rows.append((filename, row))

    return rows, duplicate_rows


def main():
    annotations, duplicate_rows = load_annotations()

    image_map = {}
    for path in sorted(IMAGE_DIR.rglob("*")):
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            image_map.setdefault(path.name, path)

    counts = Counter()
    examples = []
    errors = []
    records = []

    matched = [
        (name, row, image_map[name])
        for name, row in annotations
        if name in image_map
    ]

    missing_images = [
        name for name, _ in annotations
        if name not in image_map
    ]

    for index, (name, row, image_path) in enumerate(matched, start=1):
        try:
            truth = json.loads(row.get("Json Data", "{}") or "{}")
            subtotal = truth.get("subtotal", {}) or {}

            annotation_total = rounded(
                normalize_amount(subtotal.get("total"))
            )
            annotation_tax = rounded(
                normalize_amount(subtotal.get("tax"))
            )

            text = read_image_text(image_path)
            prediction = extract_fields(text)

            predicted_net = rounded(prediction.get("net_total"))
            predicted_tax = rounded(prediction.get("tax_amount"))
            predicted_gross = rounded(prediction.get("total"))

            if annotation_total is None:
                category = "missing_annotation_total"
            elif (
                predicted_net is not None
                and annotation_total == predicted_net
            ):
                category = "annotation_total_matches_net"
            elif (
                predicted_gross is not None
                and annotation_total == predicted_gross
            ):
                category = "annotation_total_matches_gross"
            else:
                category = "annotation_total_matches_neither"

            counts[category] += 1

            total_matches_net = (
                annotation_total is not None
                and predicted_net is not None
                and annotation_total == predicted_net
            )
            total_matches_gross = (
                annotation_total is not None
                and predicted_gross is not None
                and annotation_total == predicted_gross
            )
            tax_matches = (
                annotation_tax is not None
                and predicted_tax is not None
                and annotation_tax == predicted_tax
            )

            if total_matches_net:
                counts["total_matches_net"] += 1
            if total_matches_gross:
                counts["total_matches_gross"] += 1
            if tax_matches:
                counts["tax_matches"] += 1

            record = {
                "file": name,
                "annotation_total": annotation_total,
                "annotation_tax": annotation_tax,
                "predicted_net": predicted_net,
                "predicted_tax": predicted_tax,
                "predicted_gross": predicted_gross,
                "total_matches_net": total_matches_net,
                "total_matches_gross": total_matches_gross,
                "tax_matches": tax_matches,
                "category": category,
            }
            records.append(record)

            if (
                category != "annotation_total_matches_net"
                or not tax_matches
            ) and len(examples) < 100:
                examples.append(record)

        except Exception as exc:
            errors.append({
                "file": name,
                "error": f"{type(exc).__name__}: {exc}",
            })

        if index % 100 == 0:
            print(f"Processed {index}/{len(matched)} invoices")

    processed = len(records)

    report = {
        "dataset": "Batch 1 annotated reference images",
        "annotation_rows": len(annotations),
        "duplicate_annotation_rows_skipped": duplicate_rows,
        "matched_images": len(matched),
        "processed_images": processed,
        "missing_images": len(missing_images),
        "missing_images_sample": missing_images[:20],
        "category_counts": dict(counts),
        "rates": {
            "annotation_total_matches_net": (
                round(counts["total_matches_net"] / processed, 4)
                if processed else None
            ),
            "annotation_total_matches_gross": (
                round(counts["total_matches_gross"] / processed, 4)
                if processed else None
            ),
            "annotation_tax_matches_ocr_tax": (
                round(counts["tax_matches"] / processed, 4)
                if processed else None
            ),
        },
        "examples": examples,
        "errors": errors,
        "limitations": [
            "OCR predictions are not independent ground truth.",
            "Exact amount matching may be affected by OCR errors.",
            "This audit detects label inconsistencies; it does not correct labels.",
            "Invoices where net and gross predictions are unavailable "
            "cannot be reliably classified.",
        ],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2))
    print(f"\nAudit report saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
