import os, tempfile
os.environ['STORAGE_DIR'] = tempfile.mkdtemp(prefix='ai-pdf-reader-')
from backend.app import create_app
from backend import db as dbm

app = create_app()
client = app.test_client()

pdf_id = 'p_test'
dbm.insert_pdf(pdf_id, 't.pdf', 't.pdf')

resp = client.post('/api/word/ensure', json={'pdf_id': pdf_id, 'word':'alpha'})
print('ensure_status', resp.status_code)
print('ensure_has_word', 'word' in resp.get_json())

resp2 = client.post('/api/word/ensure', json={'pdf_id': pdf_id, 'word':'alpha'})
print('ensure_again_status', resp2.status_code)
print('has_data', bool(resp2.get_json()['word'].get('data')))

resp3 = client.get(f'/api/words?pdf_id={pdf_id}')
print('list_status', resp3.status_code)
print('list_count', len(resp3.get_json().get('words', [])))
