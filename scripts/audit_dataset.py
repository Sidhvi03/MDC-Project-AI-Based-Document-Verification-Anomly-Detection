from pathlib import Path
from collections import Counter
import csv,json
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
IMG=ROOT/'data/reference/images'; ANN=ROOT/'data/reference/annotations'; EXT=ROOT/'data/external_test/images'; OUT=ROOT/'results/dataset_audit.json'
def summarize(folder):
    paths=[p for p in folder.rglob('*') if p.suffix.lower() in {'.jpg','.jpeg','.png'}] if folder.exists() else []
    dims=Counter(); bad=[]
    for p in paths:
        try:
            with Image.open(p) as im: dims[f'{im.width}x{im.height}']+=1
        except Exception: bad.append(str(p))
    return paths,dict(dims),bad
def main():
    imgs,dims,bad=summarize(IMG); ext,edims,ebad=summarize(EXT); rows=[]
    for p in sorted(ANN.glob('*.csv')):
        with p.open(encoding='utf-8-sig',newline='') as f: rows+=list(csv.DictReader(f))
    parsed=[]; errors=0
    for r in rows:
        try: parsed.append((r,json.loads(r.get('Json Data',''))))
        except Exception: errors+=1
    names=[r.get('File Name','').strip() for r in rows]; actual={p.name for p in imgs}; annotated={Path(n).name for n in names if n}
    # Deduplicate repeated annotation rows by source image before distributions.
    unique_parsed=[]; seen_names=set()
    for r,j in parsed:
        name=str(r.get('File Name','')).strip()
        if name and name in seen_names: continue
        if name: seen_names.add(name)
        unique_parsed.append((r,j))
    sellers=Counter(); nums=Counter(); blanks=Counter()
    for r,j in unique_parsed:
        inv=j.get('invoice',{}); sub=j.get('subtotal',{})
        if inv.get('seller_name'): sellers[str(inv['seller_name']).casefold()]+=1
        if inv.get('invoice_number'): nums[str(inv['invoice_number']).casefold()]+=1
        for k,v in [('seller_name',inv.get('seller_name')),('client_name',inv.get('client_name')),('invoice_number',inv.get('invoice_number')),('invoice_date',inv.get('invoice_date')),('due_date',inv.get('due_date')),('total',sub.get('total')),('tax',sub.get('tax')),('discount',sub.get('discount'))]:
            if v is None or str(v).strip()=='': blanks[k]+=1
    report={'batch1':{'images':len(imgs),'dimensions':dims,'csv_files':len(list(ANN.glob('*.csv'))),'annotation_rows':len(rows),'unique_annotation_filenames':len(set(names)),'json_parse_errors':errors,'matched_annotated_images':len(actual&annotated),'images_without_annotations':len(actual-annotated),'annotation_names_without_images':len(annotated-actual),'duplicate_annotation_filenames':{k:v for k,v in Counter(names).items() if v>1},'blank_fields':dict(blanks),'unique_sellers':len(sellers),'repeated_sellers':sum(v>1 for v in sellers.values()),'max_seller_frequency':max(sellers.values(),default=0),'repeated_invoice_numbers':{k:v for k,v in nums.items() if v>1},'unreadable_images':bad},'batch2':{'images':len(ext),'dimensions':edims,'annotation_csvs':len(list((ROOT/'data/external_test').rglob('*.csv'))),'unreadable_images':ebad}}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(report,indent=2),encoding='utf-8'); print(json.dumps(report,indent=2)); print('Wrote',OUT)
if __name__=='__main__': main()
