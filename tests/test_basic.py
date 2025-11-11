import os
import shutil
import tempfile
import json

# Set storage dir to temp before importing app/db
TMP = tempfile.mkdtemp(prefix='ai-pdf-reader-')
os.environ['STORAGE_DIR'] = TMP

from backend import db as dbm  # noqa: E402
from backend.llm import generate_word_info  # noqa: E402


def setup_module(module):
    dbm.init_db()


def teardown_module(module):
    shutil.rmtree(TMP, ignore_errors=True)


def test_db_word_insert_and_list():
    # seed a pdf record
    dbm.insert_pdf('testpdf', 'test.pdf', 'test.pdf')
    # add a word
    w = dbm.add_word('testpdf', 'example')
    assert w['word'] == 'example'
    words = dbm.list_words('testpdf')
    assert len(words) == 1
    assert words[0]['word'] == 'example'


def test_llm_mock_without_key():
    os.environ.pop('CEREBRAS_API_KEY', None)
    data = generate_word_info('example')
    assert isinstance(data, dict)
    for key in ['definition', 'synonyms', 'antonyms', 'example', 'meaning_bn']:
        assert key in data
