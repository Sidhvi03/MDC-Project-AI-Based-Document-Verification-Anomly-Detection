import hashlib, json, os, logging
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from werkzeug.utils import secure_filename
from app.config import UPLOAD_DIR, ALLOWED_EXTENSIONS, MAX_CONTENT_LENGTH
from app.database.database import init_db, get_all, get_by_hash, insert
from app.modules.ocr import read_image_text, extract_party_names_by_layout
from app.modules.extraction import extract_fields
from app.modules.validation import validate_fields
from app.modules.duplicate_detection import detect_duplicate
from app.modules.anomaly_detection import score_anomaly
from app.modules.decision_engine import decide
app=Flask(__name__); app.secret_key=os.getenv('FLASK_SECRET_KEY', 'local-dev-key-change-before-deployment'); app.config['MAX_CONTENT_LENGTH']=MAX_CONTENT_LENGTH; init_db()
logging.basicConfig(level=logging.INFO)
logger=logging.getLogger(__name__)
def allowed(name): return Path(name).suffix.lower() in ALLOWED_EXTENSIONS
@app.get('/')
def dashboard():
    records=get_all(); statuses=[r['status'] for r in records]
    counts={'total':len(records),'valid':statuses.count('VALID'),'review':statuses.count('NEEDS REVIEW'),'flagged':statuses.count('SUSPICIOUS')+statuses.count('POSSIBLE DUPLICATE')}
    return render_template('dashboard.html',records=records,counts=counts)
@app.route('/upload',methods=['GET','POST'])
def upload():
    if request.method=='GET': return render_template('upload.html')
    f=request.files.get('invoice')
    if not f or not f.filename: flash('Choose an invoice image first.'); return redirect(url_for('upload'))
    if not allowed(f.filename): flash('Unsupported file type.'); return redirect(url_for('upload'))
    name=secure_filename(f.filename)
    if not name: flash('The filename is invalid.'); return redirect(url_for('upload'))
    content=f.read()
    if not content: flash('The uploaded file is empty.'); return redirect(url_for('upload'))
    digest=hashlib.sha256(content).hexdigest()
    old=get_by_hash(digest)
    if old: return redirect(url_for('result',record_id=old['id']))
    path=UPLOAD_DIR/name
    if path.exists(): path=UPLOAD_DIR/f'{path.stem}_{digest[:8]}{path.suffix}'
    path.write_bytes(content)
    try:
        text=read_image_text(path); fields=extract_fields(text)
        # Prefer OCR word geometry for Batch 1's two-column Seller/Client layout.
        fields.update(extract_party_names_by_layout(path))
        validation=validate_fields(fields); history=get_all()
        duplicate=detect_duplicate(fields,history); anomaly=score_anomaly(fields); decision=decide(validation,duplicate,anomaly)
        rid=insert(fields,decision,duplicate,anomaly,digest,path.name)
        return redirect(url_for('result',record_id=rid))
    except Exception as exc:
        logger.exception('Invoice processing failed')
        message = 'OCR engine is unavailable. Check that Tesseract is installed and configured.' if 'tesseract' in str(exc).lower() else 'Could not process this image. Check that it is a valid, readable invoice image.'
        flash(message); return redirect(url_for('upload'))
@app.get('/result/<int:record_id>')
def result(record_id):
    record=next((r for r in get_all() if r['id']==record_id),None)
    if not record: abort(404)
    return render_template('result.html',record=record,reasons=json.loads(record['reasons']))
if __name__=='__main__': app.run(debug=False)
