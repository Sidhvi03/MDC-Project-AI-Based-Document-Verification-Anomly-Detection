def decide(validation, duplicate, anomaly):
    """Combine signals; a flag is a review signal, not proof of fraud."""
    reasons = list(validation.get("issues", []))

    if duplicate.get("status") == "DUPLICATE":
        reasons.insert(0, duplicate.get("reason", "Strong duplicate match found."))
        return {"status": "SUSPICIOUS", "reasons": reasons}

    if duplicate.get("status") == "POSSIBLE_DUPLICATE":
        reasons.append(duplicate.get("reason", "Possible duplicate match."))
    if anomaly.get("status") == "REVIEW_ANOMALY":
        reasons.append(anomaly.get("reason", "Anomaly flag."))
    if anomaly.get("status") == "NOT_SCORED":
        # Do not make an otherwise clean invoice fail solely because the optional
        # anomaly baseline could not score it; surface this on the result instead.
        pass

    if reasons:
        return {"status": "SUSPICIOUS" if anomaly.get("status") == "REVIEW_ANOMALY" else "NEEDS REVIEW", "reasons": reasons}
    return {"status": "VALID", "reasons": ["No configured validation, duplicate, or anomaly rule raised a flag."]}
