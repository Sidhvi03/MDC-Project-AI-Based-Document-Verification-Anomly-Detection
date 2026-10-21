from datetime import date
import math
import re

def validate_fields(fields):
    """Conservative invoice checks; flags uncertainty rather than claiming fraud."""
    issues = []
    invoice_no = str(fields.get("invoice_no") or "").strip()
    invoice_date = str(fields.get("invoice_date") or "").strip()
    seller = str(fields.get("seller") or "").strip()
    total = fields.get("total")

    if not invoice_no:
        issues.append("Invoice number could not be extracted.")
    if not invoice_date:
        issues.append("Invoice date is missing or could not be parsed.")
    else:
        try:
            parsed_date = date.fromisoformat(invoice_date)
            if parsed_date > date.today():
                issues.append("Invoice date is in the future; verify manually.")
            if parsed_date.year < 1990:
                issues.append("Invoice date is unusually old; verify the extracted date.")
        except ValueError:
            issues.append("Invoice date has an invalid normalized value.")
    if not seller:
        issues.append("Seller/vendor could not be extracted.")
    if total is None:
        issues.append("Invoice total could not be parsed reliably.")
    else:
        try:
            numeric_total = float(total)
            if not math.isfinite(numeric_total):
                issues.append("Invoice total is not a finite numeric value.")
            elif numeric_total < 0:
                issues.append("Negative total; verify credit-note/adjustment context.")
            elif numeric_total == 0:
                issues.append("Invoice total is zero; verify the amount manually.")
        except (TypeError, ValueError):
            issues.append("Invoice total is not a valid numeric value.")

    # Tax IDs vary across countries in Batch 1, so check only obviously malformed values.
    tax_id = str(fields.get("tax_id") or "").strip()
    if tax_id and (len(re.sub(r"[^A-Za-z0-9]", "", tax_id)) < 5):
        issues.append("Tax ID was extracted but looks unusually short; verify manually.")

    net, tax = fields.get("net_total"), fields.get("tax_amount")
    if total is not None and net is not None and tax is not None:
        try:
            if all(math.isfinite(float(v)) for v in (net, tax, total)):
                tolerance = max(0.05, abs(float(total)) * 0.01)
                if abs((float(net) + float(tax)) - float(total)) > tolerance:
                    issues.append("Net total plus tax does not approximately equal gross total; verify manually.")
        except (TypeError, ValueError):
            issues.append("Could not validate the relationship between net, tax, and gross totals.")

    return {"valid": not issues, "issues": issues}
