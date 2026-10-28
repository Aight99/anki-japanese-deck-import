#!/usr/bin/env python3
"""Fetch native word MP3s to a resumable cache; never writes to Anki."""
import argparse
import concurrent.futures
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from vocab_tools import normalize

MISSING_SHA256 = 'ae6398b5a27bc8c0a771df6c907ade794be15518174773c58c7c7ddd17098906'


def frame_info(data, offset):
    if offset + 4 > len(data):
        return None
    header = int.from_bytes(data[offset:offset + 4], 'big')
    if header >> 21 != 0x7ff:
        return None
    version, layer = (header >> 19) & 3, (header >> 17) & 3
    bitrate_index, rate_index = (header >> 12) & 15, (header >> 10) & 3
    if version == 1 or layer != 1 or bitrate_index in (0, 15) or rate_index == 3:
        return None
    rates = [44100, 48000, 32000]
    sample_rate = rates[rate_index] // (1 if version == 3 else 2 if version == 2 else 4)
    bitrates = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320] if version == 3 else [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]
    size = (144000 if version == 3 else 72000) * bitrates[bitrate_index] // sample_rate + ((header >> 9) & 1)
    return size, version, sample_rate


def has_mp3_frames(data):
    # Require three complete, consecutive Layer III frames, not an ID3 marker alone.
    offset = 0
    if data.startswith(b'ID3'):
        if len(data) < 10 or any(v & 128 for v in data[6:10]):
            return False
        tag_size = sum(v << shift for v, shift in zip(data[6:10], (21, 14, 7, 0)))
        offset = 10 + tag_size + (10 if data[5] & 16 else 0)
    for start in range(offset, min(len(data) - 4, offset + 65536)):
        first = frame_info(data, start)
        if not first:
            continue
        cursor = start
        for _ in range(3):
            info = frame_info(data, cursor)
            if not info or info[1:] != first[1:] or cursor + info[0] > len(data):
                break
            cursor += info[0]
        else:
            return True
    return False


def audio_status(data):
    if hashlib.sha256(data).hexdigest() == MISSING_SHA256:
        return 'missing'
    return 'found' if has_mp3_frames(data) else 'invalid'


def candidates(record):
    result = [(record['word'], normalize(record['reading'], reading=True))]
    for alternative in record.get('audio_candidates', []):
        pair = alternative['word'], normalize(alternative['reading'], reading=True)
        if pair[1] != result[0][1]:
            raise ValueError('Audio alternatives must retain the selected reading')
        if pair not in result:
            result.append(pair)
    return result[:3]


def fingerprint(record):
    return hashlib.sha256(json.dumps([candidates(record), record.get('dictionary_ids', {})], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def url_for(word, reading):
    params = {'kana': reading}
    if not re.fullmatch(r'[ぁ-んァ-ヶー]+', word):
        params['kanji'] = word
    return 'https://assets.languagepod101.com/dictionary/japanese/audiomp3.php?' + urllib.parse.urlencode(params)


class Fetcher:
    def __init__(self, cache_dir, rate):
        self.directory = Path(cache_dir)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.interval, self.last_request = 1 / rate, 0.0
        self.lock, self.denied = threading.Lock(), threading.Event()

    def request(self, word, reading):
        url = url_for(word, reading)
        for attempt in range(2):
            if self.denied.is_set():
                return {'status': 'error', 'reason': 'provider_access_denied', 'url': url}
            with self.lock:
                time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'AnkiVocabularyAudio/1.0'})
                with urllib.request.urlopen(request, timeout=15) as response:
                    data = response.read()
                status = audio_status(data)
                return {'status': status, 'url': url, 'data': data if status == 'found' else None}
            except urllib.error.HTTPError as error:
                if error.code in (401, 403):
                    self.denied.set()
                    return {'status': 'error', 'reason': 'provider_access_denied', 'url': url}
                if error.code == 404:
                    return {'status': 'missing', 'reason': 'http_404', 'url': url}
                if attempt == 0 and error.code in (429, 500, 502, 503, 504):
                    try:
                        delay = min(30, max(1, int(error.headers.get('Retry-After', '3'))))
                    except ValueError:
                        delay = 3
                    time.sleep(delay)
                else:
                    return {'status': 'error', 'reason': 'http_' + str(error.code), 'url': url}
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if attempt:
                    return {'status': 'error', 'reason': type(error).__name__, 'url': url}
                time.sleep(1)
        return {'status': 'error', 'reason': 'retries_exhausted', 'url': url}

    def fetch(self, record):
        key = record['source_key']
        attempts = []
        for word, reading in candidates(record):
            result = self.request(word, reading)
            if result['status'] == 'found':
                data = result.pop('data')
                digest = hashlib.sha256(data).hexdigest()
                prefix = hashlib.sha256(key.encode()).hexdigest()[:12]
                name = f'anki_vocab_{prefix}_{digest[:12]}.mp3'
                (self.directory / name).write_bytes(data)
                return key, dict(result, filename=name, sha256=digest, bytes=len(data),
                                 source='JapanesePod101', word=word, reading=reading,
                                 fingerprint=fingerprint(record))
            result.pop('data', None)
            attempts.append(result)
            if result.get('reason') == 'provider_access_denied':
                break
        status = 'error' if any(a['status'] == 'error' for a in attempts) else ('invalid' if any(a['status'] == 'invalid' for a in attempts) else 'missing')
        return key, {'status': status, 'attempts': attempts, 'word': record['word'],
                     'reading': record['reading'], 'fingerprint': fingerprint(record)}


def write_manifest(path, manifest):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def reusable(record, cached, directory):
    if not cached or cached.get('fingerprint') != fingerprint(record):
        return False
    if cached['status'] != 'found':
        return True
    path = Path(directory) / cached['filename']
    if not path.is_file():
        return False
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest() == cached['sha256'] and audio_status(data) == 'found'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--cache-dir', required=True)
    parser.add_argument('--workers', type=int, choices=range(1, 9), default=4)
    parser.add_argument('--rate', type=float, default=4)
    parser.add_argument('--retry-unavailable', action='store_true')
    args = parser.parse_args()
    if args.rate <= 0:
        parser.error('Rate must be positive')
    records = json.loads(Path(args.input).read_text(encoding='utf-8'))
    if not isinstance(records, list):
        parser.error('Input must be a normalized JSON array')
    keys = []
    for record in records:
        for field in ('source_key', 'word', 'reading'):
            if not isinstance(record.get(field), str) or not record[field].strip():
                parser.error('Each entry needs nonempty source_key, word and reading')
        candidates(record)
        keys.append(record['source_key'])
    if len(set(keys)) != len(keys):
        parser.error('Duplicate source_key values')
    fetcher = Fetcher(args.cache_dir, args.rate)
    path = Path(args.cache_dir) / 'manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    pending = [r for r in records if not reusable(r, manifest.get(r['source_key']), args.cache_dir)
               or (args.retry_unavailable and manifest.get(r['source_key'], {}).get('status') != 'found')]
    print(f'Entries: {len(records)}; pending: {len(pending)}', flush=True)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for count, future in enumerate(concurrent.futures.as_completed([pool.submit(fetcher.fetch, r) for r in pending]), 1):
                key, result = future.result()
                manifest[key] = result
                if count % 25 == 0 or count == len(pending):
                    write_manifest(path, manifest)
                if count % 100 == 0 or count == len(pending):
                    print(f'Checked {count}/{len(pending)}', flush=True)
    finally:
        write_manifest(path, manifest)
    print(json.dumps(dict(Counter(manifest[k]['status'] for k in keys)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
