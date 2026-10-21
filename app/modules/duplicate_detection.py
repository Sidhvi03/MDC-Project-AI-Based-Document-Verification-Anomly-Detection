import re
from difflib import SequenceMatcher

def norm(v): return re.sub(r'[^a-z0-9]', '', str(v or '').casefold())

def detect_duplicate(fields, records):
    no, seller = norm(fields.get('invoice_no')), norm(fields.get('seller'))
    if not no: return {'status':'NOT_CHECKABLE','reason':'Invoice number is unavailable.'}
    possible = []
    for r in records:
        old_no, old_seller = norm(r.get('invoice_no')), norm(r.get('seller'))
        if not old_no: continue
        if no == old_no and seller and old_seller and seller == old_seller:
            return {'status':'DUPLICATE','reason':'Same normalized invoice number and seller.','match_id':r.get('id')}
        if no == old_no or (seller and old_seller and seller == old_seller and SequenceMatcher(None,no,old_no).ratio() >= .94):
            possible.append(r)
    if possible: return {'status':'POSSIBLE_DUPLICATE','reason':'Invoice number matches or is highly similar, but seller identity is missing/different.','match_id':possible[0].get('id')}
    return {'status':'NO_MATCH','reason':'No strong duplicate match found.'}
