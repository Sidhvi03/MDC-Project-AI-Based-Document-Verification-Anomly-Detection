
import re

from PIL import Image, ImageOps, ImageEnhance
import pytesseract

from app.config import TESSERACT_CMD

if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def read_image_text(path):
    """Read text from an invoice image without modifying the source file."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("L")
        im = ImageEnhance.Contrast(im).enhance(1.35)
        return pytesseract.image_to_string(im, config="--psm 6")


def _header_company_candidate(line):
    """Extract a conservative company-name candidate from a mixed line."""
    candidate = line.strip(" :-|")

    # Remove email and everything after it.
    candidate = re.split(
        r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
        candidate,
        maxsplit=1,
    )[0]

    # Remove invoice labels and everything after them.
    candidate = re.split(
        r"\bInvoices?\b",
        candidate,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    # Remove known division suffixes.
    candidate = re.split(
        r"\b(?:Aerostructure Division|FSS\s*-\s*LG)\b",
        candidate,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    # Remove address information starting at a house number.
    candidate = re.split(r"\s+\d", candidate, maxsplit=1)[0]
    candidate = candidate.strip(" :-|,.")

    if not candidate or "@" in candidate:
        return ""

    # Reject address, location, table, and totals text.
    if re.search(
        r"\b(description|quantity|qty|price|subtotal|total|"
        r"invoice|date|due|sales|tax|shipping|handling|"
        r"street|st\.?|avenue|ave\.?|road|rd\.?|boulevard|"
        r"boul\.?|drive|dr\.?|circle|court|suite|unit|"
        r"postal|zip|canada|ontario|united states|"
        r"concord|hamilton|scarborough|independence|"
        r"mississauga|pickering|mon-thurs|receiving only)\b",
        candidate,
        re.IGNORECASE,
    ):
        return ""

    if re.search(r"\d", candidate):
        return ""

    # Require at least three alphabetic characters.
    if len(re.sub(r"[^A-Za-z]", "", candidate)) < 3:
        return ""

        # Reject common invoice text and product-description fragments.
    if re.search(
        r"\b(terms and conditions|thank you|business|"
        r"please send|receiving|only|bottles|rolls|"
        r"case|sleeve|cartridges|subtotal|total due|"
        r"masking tape|cellulose tape|magic tape|"
        r"polyimide tape|araldite|permabond|"
        r"neutral cure|description|quantity)\b",
        candidate,
        re.IGNORECASE,
    ):
        return ""
    
    return candidate


def _extract_label_layout(path):
    """Extract names from invoices with explicit Seller and Client labels."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        image_width = im.width

        data = pytesseract.image_to_data(
            im,
            config="--psm 6",
            output_type=pytesseract.Output.DICT,
        )

    words = []
    for i, raw in enumerate(data.get("text", [])):
        word = str(raw).strip()
        if word:
            words.append({
                "word": word,
                "left": int(data["left"][i]),
                "top": int(data["top"][i]),
            })

    seller_label = next(
        (w for w in words if w["word"].lower().rstrip(":") == "seller"),
        None,
    )
    client_label = next(
        (w for w in words if w["word"].lower().rstrip(":") == "client"),
        None,
    )

    if not seller_label or not client_label:
        return {}

    label_y = max(seller_label["top"], client_label["top"])
    below = sorted({
        w["top"] for w in words
        if label_y + 5 < w["top"] < label_y + 180
    })

    if not below:
        return {}

    name_y = below[0]
    row = [w for w in words if abs(w["top"] - name_y) <= 10]
    midpoint = image_width // 2

    left_words = sorted(
        (w for w in row if w["left"] < midpoint),
        key=lambda w: w["left"],
    )
    right_words = sorted(
        (w for w in row if w["left"] >= midpoint),
        key=lambda w: w["left"],
    )

    seller = " ".join(w["word"] for w in left_words).strip()
    client = " ".join(w["word"] for w in right_words).strip()

    if seller and client:
        return {"seller": seller, "client": client}

    return {}


def extract_party_names_by_layout(path):
    """Extract seller/client names only when the layout provides evidence."""
    text = read_image_text(path)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # 1. Preserve the explicit Seller/Client label layout.
    labelled = _extract_label_layout(path)
    if labelled:
        return labelled

    seller = ""
    client = ""

    # 2. Layout with a Bill To label.
    bill_to_index = next(
        (
            i for i, line in enumerate(lines)
            if re.search(r"\bbill\s*to\b", line, re.IGNORECASE)
        ),
        None,
    )

    if bill_to_index is not None:
        for line in lines:
            match = re.search(
                r"\bbill\s*to\s*:\s*(.*?)"
                r"(?=\s+invoice\s*(?:number|no\.?)\s*:|$)",
                line,
                re.IGNORECASE,
            )
            if match:
                seller = match.group(1).strip(" :-|")
                break

    # 3. Header layout with two company names.
    # Use a limited header window, stopping before item tables or totals.
    if not seller and bill_to_index is None:
        candidates = []

        for line in lines[:10]:
            candidate = _header_company_candidate(line)
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        if len(candidates) >= 2:
            seller, client = candidates[0], candidates[1]

    # 4. Some invoices have a company name at the bottom.
    # Record it only when the text gives no conflicting company candidates.
    if not seller and not client:
        footer_candidates = []

        for line in lines[-8:]:
            candidate = _header_company_candidate(line)
            if candidate and candidate not in footer_candidates:
                footer_candidates.append(candidate)

        if len(footer_candidates) == 1:
            # The company is recognized, but its seller/client role is unknown.
            # Do not guess which role it has.
            return {}

    # 5. Conservative fallback for the client before a standalone Invoice label.
    invoice_index = next(
        (
            i for i, line in enumerate(lines)
            if re.fullmatch(r"Invoice", line, re.IGNORECASE)
        ),
        None,
    )

    if not client and invoice_index is not None:
        for line in reversed(lines[:invoice_index]):
            candidate = _header_company_candidate(line)
            if candidate:
                client = candidate
                break

    result = {}
    if seller:
        result["seller"] = seller
    if client:
        result["client"] = client

    return result
