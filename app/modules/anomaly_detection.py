import csv, json, math
from pathlib import Path
import numpy as np
from sklearn.ensemble import IsolationForest
from app.config import BASE_DIR
from app.modules.extraction import normalize_amount

ANNOTATION_DIR = BASE_DIR / 'data' / 'reference' / 'annotations'

def load_reference_totals():
    """Read the fixed annotated reference set; do not learn from upload order."""
    values = []
    if not ANNOTATION_DIR.exists():
        return values
    seen = set()
    for path in sorted(ANNOTATION_DIR.glob('*.csv')):
        with path.open(encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                # The source has one duplicated CSV row; deduplicate by source image name.
                filename = str(row.get('File Name', '')).strip()
                if filename and filename in seen:
                    continue
                if filename:
                    seen.add(filename)
                try:
                    data = json.loads(row.get('Json Data', '{}'))
                    raw = data.get('subtotal', {}).get('total')
                    amount = normalize_amount(raw)
                    if amount is not None and math.isfinite(amount) and amount > 0:
                        values.append(float(amount))
                except (ValueError, TypeError, AttributeError):
                    continue
    return values

def score_anomaly(fields):
    """Score a new invoice against the fixed annotated reference distribution.

    This experimental one-feature baseline uses log(total) only. It is not a
    fraud classifier and can be weak when invoice categories/currencies differ.
    """
    current = fields.get('total')
    if current is None or current <= 0:
        return {'status':'NOT_SCORED','reason':'A positive numeric total is required for anomaly scoring.'}
    history = load_reference_totals()
    if len(history) < 30:
        return {'status':'NOT_SCORED','reason':f'Only {len(history)} usable reference totals; at least 30 are required.'}
    model = IsolationForest(n_estimators=200, contamination='auto', random_state=42)
    model.fit(np.log1p(np.asarray(history, dtype=float)).reshape(-1,1))
    sample = np.array([[math.log1p(float(current))]])
    pred = int(model.predict(sample)[0])
    score = float(model.decision_function(sample)[0])
    flagged = pred == -1
    return {'status':'REVIEW_ANOMALY' if flagged else 'NO_ANOMALY_FLAG',
            'reason':'Isolation Forest flagged the log-transformed total against the fixed reference set.' if flagged else 'Isolation Forest did not flag the log-transformed total against the fixed reference set.',
            'decision_score':round(score,6),'reference_count':len(history)}
