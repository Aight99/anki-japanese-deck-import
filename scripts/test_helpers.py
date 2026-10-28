#!/usr/bin/env python3
"""Offline regression checks. Never connects to or modifies Anki."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import fetch_audio
from vocab_tools import Document, extract_jpdb, identity_candidate, inventory, normalize, plain, ruby_content, target_word


def note(nid, word=None, reading=None, model='Kaishi 1.5k'):
    fields = {'Word': word, 'Word Reading': reading, 'Word Meaning': 'example'} if word is not None else {'Front': '犬を見る', 'Back': 'see a dog'}
    return {'noteId': nid, 'modelName': model, 'fields': {k: {'value': v or '', 'order': i} for i, (k, v) in enumerate(fields.items())}, 'cards': [nid * 10, nid * 10 + 1]}


class HelpersTest(unittest.TestCase):
    def test_jpdb_alignment_and_sanitizing(self):
        source = '<div class="entry"><div><div class="vocabulary-spelling"><a href="/vocabulary/123/お客様#a">お<ruby onclick="bad()">客<rt>きゃく</rt></ruby><ruby>様<rt>さま</rt></ruby></a></div><div>guest &amp; customer</div></div><div><div></div><div>44</div></div></div>'
        row = extract_jpdb(source, 'https://jpdb.io/test')[0]
        self.assertEqual((row['word'], row['reading'], row['frequency']), ('お客様', 'おきゃくさま', 44))
        self.assertEqual(row['meaning'], 'guest & customer')
        self.assertEqual(row['furigana_html'], 'お<ruby>客<rt>きゃく</rt></ruby><ruby>様<rt>さま</rt></ruby>')
        self.assertEqual(plain(row['furigana_html']), row['word'])
        self.assertNotIn('dictionary_ids', row)
        with self.assertRaises(ValueError):
            extract_jpdb('<html>Layout changed</html>', 'https://jpdb.io/test')

    def test_grouped_and_kana_readings(self):
        anchor = Document('<a>お<ruby>土産<rt>みやげ</rt></ruby></a>').root.find('a')[0]
        self.assertEqual(ruby_content(anchor), ('お土産', 'おみやげ', 'お<ruby>土産<rt>みやげ</rt></ruby>'))
        anchor = Document('<a><ruby>ゲーム</ruby></a>').root.find('a')[0]
        self.assertEqual(ruby_content(anchor), ('ゲーム', 'ゲーム', 'ゲーム'))

    def test_interleaved_ruby_keeps_each_annotation(self):
        for source in ['<ruby>学<rt>がく</rt>校<rt>こう</rt></ruby>', '<ruby><rb>学</rb><rb>校</rb><rt>がく</rt><rt>こう</rt></ruby>']:
            anchor = Document('<a>' + source + '</a>').root.find('a')[0]
            self.assertEqual(ruby_content(anchor), ('学校', 'がくこう', '<ruby>学<rt>がく</rt></ruby><ruby>校<rt>こう</rt></ruby>'))

    def test_homophones_and_verified_aliases(self):
        self.assertIsNone(identity_candidate({'word': 'に', 'reading': 'に'}, {'word': '二', 'reading': 'に'}))
        self.assertIsNone(identity_candidate({'word': '欲', 'reading': 'よく'}, {'word': 'よく', 'reading': 'よく'}))
        a = {'word': 'いる', 'reading': 'いる', 'dictionary_ids': {'JMdict': '1'}}
        b = {'word': 'いる', 'reading': 'いる', 'dictionary_ids': {'JMdict': '2'}}
        self.assertIsNone(identity_candidate(a, b))
        self.assertEqual(identity_candidate({'word': 'いる', 'reading': 'いる'}, a), 'surface_needs_sense_review')
        self.assertEqual(identity_candidate({'word': '嘘', 'reading': 'うそ', 'dictionary_ids': {'JMdict': '3'}}, {'word': 'ウソ', 'reading': 'ウソ', 'dictionary_ids': {'JMdict': '3'}}), 'verified_dictionary_id')
        self.assertEqual(normalize('ｹﾞｰﾑ', True), 'げーむ')
        self.assertNotEqual(normalize('けい', True), normalize('けー', True))

    def test_inventory_counts_notes_and_marks_unmapped_models(self):
        notes = [note(1, '犬', 'いぬ'), note(2, '猫', 'ねこ'), note(3, 'Welcome!', ''), note(4, model='Sentence')]
        class Client:
            def call(self, action, **params):
                if action == 'getActiveProfile':
                    return 'Test'
                if action == 'notesInfo':
                    if set(params) != {'notes'}:
                        raise TypeError('notesInfo requires explicit note IDs')
                    return [n for n in notes if n['noteId'] in params['notes']]
                if action == 'deckNames':
                    return ['Kaishi', 'Kaishi::Child', 'Sentences']
                query = params['query']
                if query == '':
                    return [n['noteId'] for n in notes]
                if query == 'prop:reps>0':
                    return [1, 4]
                return {'"deck:Kaishi"': [1, 2, 3], '"deck:Kaishi::Child"': [1], '"deck:Sentences"': [4]}[query]
        output = inventory(Client())
        deck = next(d for d in output['decks'] if d['name'] == 'Kaishi')
        self.assertEqual((deck['target_words'], deck['studied_words'], deck['studied_percent']), (2, 1, 50.0))
        self.assertEqual(output['profile'], 'Test')
        self.assertEqual(output['unmapped_models'], {'Sentence': 1})
        sentence = next(d for d in output['decks'] if d['name'] == 'Sentences')
        self.assertEqual((sentence['studied_notes'], sentence['studied_words']), (1, 0))
        self.assertIsNone(target_word(notes[2]))
        self.assertIsNone(target_word(notes[3]))
        legacy = note(5, '魔女', 'まじょ', model='JPDB Vocabulary')
        legacy['fields']['Reading'] = legacy['fields'].pop('Word Reading')
        self.assertEqual(target_word(legacy)['word'], '魔女')

    def test_audio_cache_content_and_identity(self):
        record = {'source_key': 'sample:1', 'word': '魔女', 'reading': 'まじょ'}
        data = (bytes.fromhex('fffb9000') + bytes(413)) * 3
        self.assertEqual(fetch_audio.audio_status(b'ID3' + bytes(1100)), 'invalid')
        with tempfile.TemporaryDirectory() as directory:
            fetcher = fetch_audio.Fetcher(directory, rate=1000)
            with patch.object(fetcher, 'request', return_value={'status': 'found', 'url': 'https://example.invalid/audio', 'data': data}):
                key, result = fetcher.fetch(record)
            self.assertEqual(key, record['source_key'])
            self.assertTrue(fetch_audio.reusable(record, result, directory))
            changed = dict(record, reading='べつ')
            self.assertFalse(fetch_audio.reusable(changed, result, directory))
            path = Path(directory) / result['filename']
            path.write_bytes(b'corrupt')
            self.assertFalse(fetch_audio.reusable(record, result, directory))
            invalid = b'ID3' + bytes(1100)
            path.write_bytes(invalid)
            stale = dict(result, sha256=hashlib.sha256(invalid).hexdigest())
            self.assertFalse(fetch_audio.reusable(record, stale, directory))
            manifest = Path(directory) / 'manifest.json'
            fetch_audio.write_manifest(manifest, {key: result})
            self.assertEqual(json.loads(manifest.read_text())[key]['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(fetch_audio.audio_status(b'<html>' + b'x' * 2000), 'invalid')
        with self.assertRaises(ValueError):
            fetch_audio.candidates(dict(record, audio_candidates=[{'word': '魔女', 'reading': 'べつ'}]))

    def test_template_reveals_reading_only_on_back(self):
        asset = json.loads((Path(__file__).resolve().parent.parent / 'assets/kaishi-vocabulary.json').read_text())
        template = asset['templates'][0]
        self.assertNotIn('Word Furigana', template['Front'])
        self.assertNotIn('Word Audio', template['Front'])
        self.assertIn('{{Word Furigana}}', template['Back'])
        self.assertNotIn('{{Word Reading}}', template['Back'])
        self.assertNotIn('{{FrontSide}}', template['Back'])


if __name__ == '__main__':
    unittest.main()
