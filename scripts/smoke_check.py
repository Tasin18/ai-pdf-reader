import os, tempfile
os.environ['STORAGE_DIR'] = tempfile.mkdtemp(prefix='ai-pdf-reader-')
from backend import db as dbm
from backend.app import create_app

# init db
dbm.init_db()
# create app
app = create_app()
print('app_ok', bool(app))
# seed pdf + words
pdf_id = 'p1'
dbm.insert_pdf(pdf_id, 'x.pdf', 'x.pdf')
# add three words
w1 = dbm.add_word(pdf_id, 'alpha')
w2 = dbm.add_word(pdf_id, 'beta')
w3 = dbm.add_word(pdf_id, 'gamma')
# mark one as having existing data
from backend.db import upsert_word_info
upsert_word_info(w2['id'], {'definition':'d','_source':'LLM'})
rows = dbm.list_words(pdf_id)
print('rows_count', len(rows))
print('has_data_flags', [bool(r.get('data')) for r in rows])
# emulate selection with regenerate=False: only words without data
targets = []
for r in rows:
    if r.get('data'):
        continue
    targets.append(r['word'])
print('targets', targets)
