#!/usr/bin/env python3
"""Read-only Anki inventory and offline jpdb extraction. Standard library only."""
import argparse
import html
import json
import os
import re
import unicodedata
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

KANJI = re.compile(r'[一-鿿々〆ヵヶ]')
JAPANESE = re.compile(r'[ぁ-んァ-ヶ一-鿿]')
FIELD_PAIRS = [('Word', 'Word Reading'), ('Word', 'Reading'), ('Expression', 'ExpressionReading'), ('Vocabulary', 'Reading')]


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self, exclude=()):
        return ''.join(c if isinstance(c, str) else ('' if c.tag in exclude else c.text(exclude)) for c in self.children)

    def find(self, tag=None, cls=None):
        result = []
        for c in self.children:
            if isinstance(c, str):
                continue
            if (tag is None or c.tag == tag) and (cls is None or cls in c.attrs.get('class', '').split()):
                result.append(c)
            result.extend(c.find(tag, cls))
        return result


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def plain(value):
    return Document(value).root.text(exclude=('rt', 'rp', 'script', 'style')).strip()


def normalize(value, reading=False):
    value = unicodedata.normalize('NFKC', value).strip()
    if reading:
        value = ''.join(chr(ord(c) - 96) if 'ァ' <= c <= 'ヶ' else c for c in value)
    return value


def identity_candidate(a, b):
    """Return a candidate reason, never a reading-only linguistic match."""
    a_ids, b_ids = a.get('dictionary_ids', {}), b.get('dictionary_ids', {})
    common = set(a_ids) & set(b_ids)
    def values(x):
        return {str(v) for v in x} if isinstance(x, list) else {str(x)}
    if any(values(a_ids[k]) & values(b_ids[k]) for k in common):
        return 'verified_dictionary_id'
    if common:
        return None
    if normalize(a['word']) == normalize(b['word']) and normalize(a['reading'], True) == normalize(b['reading'], True):
        return 'surface_needs_sense_review'
    return None


def ruby_content(anchor):
    word, reading, output = '', '', []

    def emit(base, annotation=''):
        nonlocal word, reading
        word += base
        reading += annotation or base
        if annotation and KANJI.search(base):
            output.append('<ruby>' + html.escape(base) + '<rt>' + html.escape(annotation) + '</rt></ruby>')
        else:
            output.append(html.escape(base))

    def emit_ruby(node):
        bases = [c for c in node.children if isinstance(c, Node) and c.tag == 'rb']
        annotations = [c for c in node.children if isinstance(c, Node) and c.tag == 'rt']
        if len(bases) == len(annotations) and len(bases) > 1:
            for base, annotation in zip(bases, annotations):
                emit(base.text(), annotation.text())
            return
        pending = ''
        for c in node.children:
            if isinstance(c, str):
                pending += c
            elif c.tag == 'rt':
                if not pending:
                    raise ValueError('Cannot safely align multiple ruby annotations')
                emit(pending, c.text())
                pending = ''
            elif c.tag not in ('rp', 'script', 'style'):
                if c.find('rt') or c.tag in ('ruby', 'rtc'):
                    raise ValueError('Review complex nested ruby alignment')
                pending += c.text()
        if pending:
            emit(pending)

    def walk(node):
        for child in node.children:
            if isinstance(child, str):
                emit(child)
            elif child.tag == 'ruby':
                emit_ruby(child)
            elif child.tag not in ('rt', 'rp', 'script', 'style'):
                walk(child)
    walk(anchor)
    result = ''.join(output)
    if plain(result) != word:
        raise ValueError('Ruby base does not reconstruct the word')
    return word, reading, result


def extract_jpdb(source, source_url):
    result = []
    for entry in Document(source).root.find(cls='entry'):
        spellings = entry.find(cls='vocabulary-spelling')
        if not spellings:
            continue
        links = spellings[0].find('a')
        if not links:
            raise ValueError('Vocabulary entry has no link')
        anchor = links[0]
        match = re.match(r'/vocabulary/(\d+)/', anchor.attrs.get('href', ''))
        if not match:
            raise ValueError('Unrecognized vocabulary URL')
        word, reading, furigana = ruby_content(anchor)
        children = [c for c in entry.children if isinstance(c, Node)]
        if len(children) != 2:
            raise ValueError('Vocabulary entry layout changed')
        details = [c for c in children[0].children if isinstance(c, Node)]
        frequency_text = children[1].text().strip()
        if len(details) < 2 or not frequency_text.isdigit():
            raise ValueError('Meaning/frequency layout changed')
        vid = match.group(1)
        result.append({
            'source_key': f'jpdb:{vid}:{word}:{reading}',
            'source_entry_id': vid,
            'word': word, 'reading': reading, 'meaning': details[1].text().strip(),
            'furigana_html': furigana, 'frequency': int(frequency_text),
            'source_url': 'https://jpdb.io' + anchor.attrs['href'], 'deck_source_url': source_url,
        })
    if not result:
        raise ValueError('No vocabulary found; verify the supplied pages and markup')
    return result


class AnkiClient:
    def __init__(self, url='http://127.0.0.1:8765', api_key=None):
        self.url, self.api_key = url, api_key

    def call(self, action, **params):
        body = {'action': action, 'version': 6, 'params': params}
        if self.api_key:
            body['key'] = self.api_key
        request = urllib.request.Request(self.url, json.dumps(body).encode(), {'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.load(response)
        if data.get('error') is not None:
            raise RuntimeError(f'{action}: {data["error"]}')
        return data['result']


def target_word(note):
    fields = note['fields']
    for word_field, reading_field in FIELD_PAIRS:
        if word_field not in fields or reading_field not in fields:
            continue
        word, reading = plain(fields[word_field]['value']), plain(fields[reading_field]['value'])
        if not JAPANESE.search(word) or not reading:
            return None
        meaning_field = next((f for f in ('Word Meaning', 'MainDefinition', 'Meaning') if f in fields), None)
        return {
            'note_id': note['noteId'], 'model': note['modelName'], 'word': word,
            'reading': reading, 'meaning': plain(fields[meaning_field]['value']) if meaning_field else '',
        }
    return None


def inventory(client):
    note_ids = client.call('findNotes', query='')
    notes = [note for start in range(0, len(note_ids), 300)
             for note in client.call('notesInfo', notes=note_ids[start:start + 300])]
    profile = client.call('getActiveProfile')
    targets = [word for n in notes if (word := target_word(n)) is not None]
    target_ids = {r['note_id'] for r in targets}
    studied = set(client.call('findNotes', query='prop:reps>0'))
    decks = []
    for name in client.call('deckNames'):
        # Quote the whole search token and escape Anki wildcard characters.
        escaped = re.sub(r'([\\"*_])', r'\\\1', name)
        members = set(client.call('findNotes', query='"deck:' + escaped + '"'))
        eligible = members & target_ids
        started = eligible & studied
        decks.append({
            'name': name, 'includes_descendants': True, 'note_ids': sorted(members),
            'target_note_ids': sorted(eligible), 'studied_target_note_ids': sorted(started),
            'total_notes': len(members), 'studied_notes': len(members & studied),
            'target_words': len(eligible), 'studied_words': len(started),
            'studied_percent': round(100 * len(started) / len(eligible), 1) if eligible else None,
        })
    mapped_models = {n['modelName'] for n in notes if any(w in n['fields'] and r in n['fields'] for w, r in FIELD_PAIRS)}
    unmapped = Counter(n['modelName'] for n in notes if n['modelName'] not in mapped_models)
    return {
        'profile': profile,
        'notes': notes, 'target_words': targets, 'studied_note_ids': sorted(studied),
        'decks': sorted(decks, key=lambda d: (-d['studied_words'], d['name'])),
        'unmapped_models': dict(unmapped),
    }


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('inventory')
    p.add_argument('--url', default='http://127.0.0.1:8765')
    p.add_argument('--api-key-env', default='ANKICONNECT_API_KEY')
    p.add_argument('--output', required=True)
    p = commands.add_parser('extract-jpdb')
    p.add_argument('--html-dir', required=True)
    p.add_argument('--source-url', required=True)
    p.add_argument('--expected-count', type=int)
    p.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.command == 'inventory':
        data = inventory(AnkiClient(args.url, os.environ.get(args.api_key_env)))
        write_json(args.output, data)
        print(json.dumps({'profile': data['profile'], 'decks': [{k: d[k] for k in ('name', 'total_notes', 'studied_notes', 'target_words', 'studied_words', 'studied_percent')} for d in data['decks']], 'unmapped_models': data['unmapped_models']}, ensure_ascii=False, indent=2))
    else:
        files = sorted(Path(args.html_dir).glob('*.html'), key=lambda p: (0, int(p.stem)) if p.stem.isdigit() else (1, p.name))
        if not files:
            parser.error('No cached HTML files')
        records = [r for path in files for r in extract_jpdb(path.read_text(encoding='utf-8'), args.source_url)]
        keys = [r['source_key'] for r in records]
        if len(set(keys)) != len(keys):
            parser.error('Duplicate source entries; check cached pagination')
        if args.expected_count is not None and len(records) != args.expected_count:
            parser.error(f'Expected {args.expected_count} entries, extracted {len(records)}')
        write_json(args.output, records)
        print(json.dumps({'entries': len(records), 'occurrences': sum(r['frequency'] for r in records)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
