
import re
from datetime import datetime


def first(patterns, text):
    """Return the first non-empty regex capture."""
    for pattern in patterns:
        match = re.search(
            pattern,
            text or "",
            re.IGNORECASE | re.MULTILINE,
        )
        if match:
            return match.group(1).strip(" \t:#")
    return ""


def normalize_amount(value):
    """Convert common invoice amount formats to float."""
    if value is None:
        return None

    s = str(value).strip()
    if not s:
        return None

    s = re.sub(r"[^0-9,.\- ]", "", s).replace(" ", "")

    if not s or not re.search(r"\d", s):
        return None

    if s.count("-") > 1 or ("-" in s and not s.startswith("-")):
        return None

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        tail = s.rsplit(",", 1)[-1]
        if len(tail) in (1, 2):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif s.count(".") > 1:
        parts = s.split(".")
        if all(part.isdigit() for part in parts) and all(
            len(part) == 3 for part in parts[1:]
        ):
            s = "".join(parts)
        else:
            return None

    try:
        return float(s)
    except ValueError:
        return None


def normalize_date(value):
    """Normalize supported date strings to YYYY-MM-DD."""
    if not value:
        return ""

    value = str(value).strip().replace(".", "")

    formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d/%m/%Y",
        "%d/%m/%y",
        "%m-%d-%Y",
        "%d-%m-%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%b %d %Y",
        "%B %d %Y",
        "%d %b %Y",
        "%d %B %Y",
    )

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue

    return ""


def extract_fields(text):
    """Extract invoice fields using OCR text and regular expressions."""
    text = text or ""

    invoice_no = first(
        [
            r"\binvoice\s*(?:no\.?|number|#)\s*[:#]?\s*"
            r"([A-Z0-9][A-Z0-9./_-]*)"
        ],
        text,
    )

    date_raw = first(
        [
            r"\b(?:date\s+of\s+issue|invoice\s+date|date)\s*[:\-]?\s*"
            r"([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})",
            r"\b(?:date\s+of\s+issue|invoice\s+date|date)\s*[:\-]?\s*"
            r"(\d{1,4}[/-]\d{1,2}[/-]\d{1,4})",
        ],
        text,
    )

    # Text-only fallback. Layout extraction can override these values.
    seller = first(
        [
            r"\bseller\s*:\s*(.+?)(?=\s+client\s*:|\n|tax\s*id|$)",
            r"\bbill\s+from\s*[:\n]+\s*(.+?)"
            r"(?=\n|bill\s+to|invoice\s+number|$)",
        ],
        text,
    )

    client = first(
        [
            r"\bclient\s*:\s*(.+?)(?=\n|tax\s*id|$)",
            r"\bbill\s+to\s*[:\n]+\s*(.+?)"
            r"(?=\n|invoice\s+number|date\s+of\s+issue|$)",
        ],
        text,
    )

    tax_id = first(
        [r"\btax\s*id\s*:\s*([A-Z0-9-]+)"],
        text,
    )

    
    net_total = None
    tax_amount = None
    gross_total = None

    # Extract amounts from explicit summary lines.
    # Supports decimal formats such as 300.26 and 300,26.
    amount_pattern = (
        r"(?<![A-Za-z0-9])"
        r"-?\d+(?:[ ]\d{3})*(?:[.,]\d{1,2})?"
    )

    lines = (text or "").splitlines()

    # First preference: a Total summary containing net, tax and gross.
    # Example: Total $ 300.26 $ 30.03 $ 330.29
    for line in lines:
        match = re.search(r"\btotal\b(.*)", line, re.IGNORECASE)
        if not match:
            continue

        # Do not treat "Total Due" as a three-value summary unless
        # the line actually contains three amounts.
        summary_text = match.group(1)
        amounts = re.findall(amount_pattern, summary_text)

        if len(amounts) >= 3:
            parsed = [normalize_amount(value) for value in amounts[:3]]

            if all(value is not None for value in parsed):
                net_total, tax_amount, gross_total = parsed
                break

    # If a three-value summary was not found, use explicit labels.
    # Never infer net or tax from a single gross total.
    if net_total is None:
        for line in lines:
            if re.search(r"\bnet\s+total\b", line, re.IGNORECASE):
                values = re.findall(amount_pattern, line)
                if values:
                    net_total = normalize_amount(values[-1])
                    if net_total is not None:
                        break
    if tax_amount is None:
        for line in lines:
            if re.search(
                r"\b(?:tax\s+amount|vat\s+amount|gst\s+amount)\b",
                line,
                re.IGNORECASE,
            ):
                values = re.findall(amount_pattern, line)
                if values:
                    tax_amount = normalize_amount(values[-1])
                    if tax_amount is not None:
                        break

    # Gross total: prefer a specifically labelled final amount.
    if gross_total is None:
        total_labels = (
            r"\bamount\s+due\b",
            r"\btotal\s+due\b",
            r"\bgrand\s+total\b",
            r"\bgross\s+total\b",
            r"\btotal\b",
        )

        for label_pattern in total_labels:
            for line in lines:
                match = re.search(label_pattern, line, re.IGNORECASE)
                if not match:
                    continue

                # Read only text after the label on this line.
                remainder = line[match.end():]
                values = re.findall(amount_pattern, remainder)

                if values:
                    candidate = normalize_amount(values[-1])
                    if candidate is not None:
                        gross_total = candidate
                        break

            if gross_total is not None:
                break

    # Keep the old total_raw field for compatibility.
    total_raw = ""
    if gross_total is not None:
        total_raw = str(gross_total)


    # When the three-value summary exists, net_total and tax_amount are
    # extracted independently. Do not infer net_total from gross_total.
    return {
        "invoice_no": invoice_no,
        "invoice_date_raw": date_raw,
        "invoice_date": normalize_date(date_raw),
        "seller": seller,
        "client": client,
        "tax_id": tax_id,
        "net_total": net_total,
        "tax_amount": tax_amount,
        "total_raw": total_raw,
        "gross_total": gross_total,
        "total": gross_total,
        "ocr_text": text,
    }
