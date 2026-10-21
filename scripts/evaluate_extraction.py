
from pathlib import Path
from collections import defaultdict
import argparse
import csv
import json
import re

from app.modules.ocr import (
    read_image_text,
    extract_party_names_by_layout,
)
from app.modules.extraction import (
    extract_fields,
    normalize_amount,
    normalize_date,
)


ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "data" / "reference" / "images"
ANNOTATION_DIR = ROOT / "data" / "reference" / "annotations"
DEFAULT_OUT = ROOT / "results" / "extraction_evaluation.json"


def norm_text(value):
    """Normalize text for punctuation-insensitive comparisons."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def amounts_equal(first, second):
    """Compare monetary values to two decimal places."""
    return (
        first is not None
        and second is not None
        and round(first, 2) == round(second, 2)
    )


def load_unique_annotations(annotation_dir):
    """Load annotations, keeping the first row for each filename."""
    rows = []
    seen = set()
    duplicate_rows = 0

    for csv_path in sorted(annotation_dir.glob("*.csv")):
        with csv_path.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                name = Path(
                    str(row.get("File Name", "")).strip()
                ).name

                if not name:
                    continue

                if name in seen:
                    duplicate_rows += 1
                    continue

                seen.add(name)
                rows.append((name, row))

    return rows, duplicate_rows


def evaluate(limit=0):
    if not ANNOTATION_DIR.exists():
        raise FileNotFoundError(
            f"Annotation directory not found: {ANNOTATION_DIR}"
        )

    if not IMAGE_DIR.exists():
        raise FileNotFoundError(
            f"Image directory not found: {IMAGE_DIR}"
        )

    annotation_rows, duplicate_rows = load_unique_annotations(
        ANNOTATION_DIR
    )

    image_map = {}

    for path in sorted(IMAGE_DIR.rglob("*")):
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            image_map.setdefault(path.name, path)

    matched = [
        (name, row, image_map[name])
        for name, row in annotation_rows
        if name in image_map
    ]

    missing_images = [
        name for name, _ in annotation_rows
        if name not in image_map
    ]

    if limit > 0:
        matched = matched[:limit]

    field_names = (
        "invoice_number",
        "invoice_date",
        "seller",
        "client",
    )

    completeness_fields = {
        "invoice_number": "invoice_no",
        "invoice_date": "invoice_date",
        "seller": "seller",
        "client": "client",
        "net_total": "net_total",
        "tax_amount": "tax_amount",
        "gross_total": "gross_total",
    }

    completeness_counts = {
        field: {"extracted": 0, "missing": 0}
        for field in completeness_fields
    }

    metrics = defaultdict(
        lambda: {"correct": 0, "evaluated": 0, "skipped": 0}
    )

    amount_counts = {
        "annotation_total_matches_net": 0,
        "annotation_total_matches_gross": 0,
        "annotation_total_matches_both": 0,
        "annotation_total_matches_neither": 0,
        "missing_annotation_total": 0,
        "tax_matches": 0,
        "tax_mismatches": 0,
        "missing_annotation_tax": 0,
    }

    amount_evaluated = {
        "annotation_total": 0,
        "annotation_tax": 0,
    }

    errors = []
    mismatches = []
    amount_examples = []

    for index, (name, row, image_path) in enumerate(
        matched, start=1
    ):
        predictions = {}
        processing_error = None

        try:
            text = read_image_text(image_path)
            predictions = extract_fields(text)

            layout_fields = extract_party_names_by_layout(image_path)
            predictions.update(layout_fields)
            for field, prediction_key in completeness_fields.items():
                value = predictions.get(prediction_key)

                if value is not None and str(value).strip() != "":
                    completeness_counts[field]["extracted"] += 1
                else:
                    completeness_counts[field]["missing"] += 1

        except Exception as exc:
            processing_error = f"{type(exc).__name__}: {exc}"
            errors.append({
                "file": name,
                "error": processing_error,
            })

        try:
            truth = json.loads(row.get("Json Data", "{}") or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append({
                "file": name,
                "error": f"Invalid annotation JSON: {exc}",
            })
            continue

        invoice = truth.get("invoice", {}) or {}
        subtotal = truth.get("subtotal", {}) or {}

        pairs = {
            "invoice_number": (
                predictions.get("invoice_no", ""),
                invoice.get("invoice_number", ""),
            ),
            "invoice_date": (
                normalize_date(
                    predictions.get("invoice_date")
                    or predictions.get("invoice_date_raw")
                ),
                normalize_date(invoice.get("invoice_date")),
            ),
            "seller": (
                predictions.get("seller", ""),
                invoice.get("seller_name", ""),
            ),
            "client": (
                predictions.get("client", ""),
                invoice.get("client_name", ""),
            ),
        }

        # Evaluate text and date fields.
        for field in field_names:
            actual, expected = pairs[field]

            if expected in ("", None):
                metrics[field]["skipped"] += 1
                continue

            metrics[field]["evaluated"] += 1

            if field in ("invoice_number", "seller", "client"):
                correct = norm_text(actual) == norm_text(expected)
            else:
                correct = actual == expected

            if correct:
                metrics[field]["correct"] += 1
            else:
                mismatches.append({
                    "file": name,
                    "field": field,
                    "predicted": actual,
                    "expected": expected,
                    "processing_error": processing_error,
                })

        # Extract predicted amounts separately.
        predicted_net = normalize_amount(
            predictions.get("net_total")
        )
        predicted_tax = normalize_amount(
            predictions.get("tax_amount")
        )
        predicted_gross = normalize_amount(
            predictions.get("gross_total")
        )

        # Annotation total is NOT assumed to always mean net or gross.
        annotation_total = normalize_amount(
            subtotal.get("total")
        )
        annotation_tax = normalize_amount(
            subtotal.get("tax")
        )

        matches_net = amounts_equal(
            annotation_total, predicted_net
        )
        matches_gross = amounts_equal(
            annotation_total, predicted_gross
        )

        if annotation_total is None:
            amount_counts["missing_annotation_total"] += 1
            total_category = "missing_annotation_total"
        else:
            amount_evaluated["annotation_total"] += 1

            if matches_net:
                amount_counts["annotation_total_matches_net"] += 1

            if matches_gross:
                amount_counts["annotation_total_matches_gross"] += 1

            if matches_net and matches_gross:
                amount_counts["annotation_total_matches_both"] += 1
                total_category = "matches_both"
            elif matches_net:
                total_category = "matches_net"
            elif matches_gross:
                total_category = "matches_gross"
            elif predicted_net is None and predicted_gross is None:
                total_category = "prediction_unavailable"
            else:
                amount_counts["annotation_total_matches_neither"] += 1
                total_category = "matches_neither"

        # Evaluate tax only when its annotation is a monetary amount.
        annotation_tax_raw = str(
            subtotal.get("tax") or ""
        ).strip()

        if "%" in annotation_tax_raw:
            amount_counts.setdefault(
                "tax_rate_annotations_skipped", 0
            )
            amount_counts["tax_rate_annotations_skipped"] += 1
            tax_matches = None

        elif annotation_tax is None:
            amount_counts["missing_annotation_tax"] += 1
            tax_matches = None

        else:
            amount_evaluated["annotation_tax"] += 1
            tax_matches = amounts_equal(
                annotation_tax, predicted_tax
            )

            if tax_matches:
                amount_counts["tax_matches"] += 1
            else:
                amount_counts["tax_mismatches"] += 1
        # Save useful amount examples, including discrepancies.
        if (
            total_category not in ("matches_gross",)
            or tax_matches is False
            or predicted_net is None
            or predicted_gross is None
        ):
            if len(amount_examples) < 200:
                amount_examples.append({
                    "file": name,
                    "annotation_total": annotation_total,
                    "predicted_net": predicted_net,
                    "predicted_gross": predicted_gross,
                    "annotation_tax": annotation_tax,
                    "predicted_tax": predicted_tax,
                    "total_category": total_category,
                    "tax_matches": tax_matches,
                })

        if index % 50 == 0:
            print(f"Processed {index}/{len(matched)}")

    # Summarize text/date extraction metrics.
    field_summary = {}

    for field in field_names:
        item = metrics[field]
        evaluated = item["evaluated"]

        field_summary[field] = {
            **item,
            "accuracy": (
                round(item["correct"] / evaluated, 4)
                if evaluated else None
            ),
        }

    # Amount match rates use the number of available annotations.
    amount_rates = {
        "annotation_total_matches_net": (
            round(
                amount_counts["annotation_total_matches_net"]
                / amount_evaluated["annotation_total"],
                4,
            )
            if amount_evaluated["annotation_total"] else None
        ),
        "annotation_total_matches_gross": (
            round(
                amount_counts["annotation_total_matches_gross"]
                / amount_evaluated["annotation_total"],
                4,
            )
            if amount_evaluated["annotation_total"] else None
        ),
        "annotation_total_matches_neither": (
            round(
                amount_counts["annotation_total_matches_neither"]
                / amount_evaluated["annotation_total"],
                4,
            )
            if amount_evaluated["annotation_total"] else None
        ),
        "tax_matches": (
            round(
                amount_counts["tax_matches"]
                / amount_evaluated["annotation_tax"],
                4,
            )
            if amount_evaluated["annotation_tax"] else None
        ),
    }

    report = {
        "dataset": "Batch 1 annotated reference images",
        "documents_evaluated": len(matched),
        "unique_annotation_filenames": len(annotation_rows),
        "duplicate_annotation_rows_skipped": duplicate_rows,
        "annotation_filenames_without_images": len(missing_images),
        "annotation_filenames_without_images_sample": missing_images[:20],
        "field_metrics": field_summary,
        "extraction_completeness": {
            field: {
                **counts,
                "completeness": round(
                    counts["extracted"] / len(matched), 4
                ) if matched else None,
            }
            for field, counts in completeness_counts.items()
        },
        "amount_evaluation": {
            "annotation_total_meaning": (
                "Not assumed to be consistently net or gross."
            ),
            "evaluated_annotation_totals": (
                amount_evaluated["annotation_total"]
            ),
            "evaluated_annotation_taxes": (
                amount_evaluated["annotation_tax"]
            ),
            "counts": amount_counts,
            "rates": amount_rates,
            "examples": amount_examples,
        },
        "errors": errors,
        "mismatches": mismatches,
        "limitations": [
            "OCR predictions are not independent ground truth.",
            "Annotation subtotal.total may represent net or gross "
            "amount inconsistently across invoices.",
            "Net and gross match rates are comparisons against the same "
            "annotation field, not independent accuracy measurements.",
            "Tax results depend on annotation quality and OCR quality.",
            "Blank ground-truth fields are not evaluated.",
            "Extraction accuracy does not measure fraud detection.",
            "Exact monetary matching may be affected by OCR errors.",
        ],
    }

    return report


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate invoice extraction and audit amount labels."
        )
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Evaluate first N matched images; 0 means all.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUT,
        help="Path for the JSON report.",
    )

    args = parser.parse_args()
    report = evaluate(limit=args.limit)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2))
    print(f"\nWrote report to: {args.output}")


if __name__ == "__main__":
    main()
