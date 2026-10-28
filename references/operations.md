# Anki and audio operations

## Read-only inventory helper

```sh
python3 scripts/vocab_tools.py inventory --output work/anki-inventory.json
```

The helper uses AnkiConnect at `http://127.0.0.1:8765`. `--url` changes the endpoint; `--api-key-env NAME` reads a key from an environment variable without printing it. It never installs add-ons, opens Anki, writes its database or imports cards. If the service is unavailable, the agent may open Anki using the permitted app tool for an authorized import; check the active profile. Avoid repeatedly relaunching a user-closed app. Report a connection blocker if it persists.

The output includes `notes`, `target_words`, `studied_note_ids`, and `decks`. Deck membership includes descendants, and counts use target-word note IDs. Unknown note types appear under `unmapped_models`; inspect them rather than guessing that every Front field is a Japanese vocabulary word. The snapshot contains private local note data: keep it local and out of skill bundles.

Anki documents `prop:reps` and deck/subdeck searching at [Searching](https://docs.ankiweb.net/manual/searching). The helper's saved output can be used to build the selected union after the user replies.

## AnkiConnect mutation pattern

Use the installed API's actual signatures; inspect its source or current documentation when uncertain. Applicable actions include:

- `deckNames`, `findNotes`, `notesInfo`, `findCards`, `cardsInfo` for discovery and verification.
- `modelFieldNames`, `modelTemplates`, `modelStyling` to inspect the user's Kaishi.
- `createDeck`, `createModel` for a dedicated destination type; check whether the names already exist.
- `canAddNotes`, `addNotes`, `updateNoteFields`, `storeMediaFile`, `exportPackage` for the requested import.

AnkiConnect v6 replies contain `result` and `error`. Nested `multi` actions should specify the API version if relying on v6 result envelopes. Check every result. A `null` error is required; a successful HTTP request does not establish a successful note write. Avoid broad automatic retries for mutating requests: after a lost response, inspect source keys/note IDs to determine what committed.

Store deterministic source IDs, source URL, frequency and optional POS in fields/tags, preserving the display word independently of note uniqueness. If Source ID is the first field, duplicate checking by that field alone does not find linguistic duplicates; complete the selected-deck matching first. The destination's rerun check must also preserve homonyms correctly.

Read-only SQLite is a fallback only. Anki can lock its live database. Copy the collection and its WAL together when a stable read is possible, then open only the copy. Never directly write the user's live SQLite file. Prefer Anki's APIs for coherent snapshots and all mutations.

Before changing an existing destination, save an `.apkg` with `includeSched=true` and a local fields/templates snapshot. Preserve user-renamed decks, scheduling, existing card IDs, model ownership and other decks. Do not change preset settings to imitate Kaishi. Do not create a new note type by changing Kaishi itself.

Only touch notes identified by the destination's source IDs/tags and confirmed membership. Apply filtering before creating notes. Updates should modify just the requested fields/templates. If replacing/removing existing destination entries is requested, use the saved backup and a reviewed exclusion manifest; do not globally delete matches from the collection.

## Furigana and display

`assets/kaishi-vocabulary.json` is a compact fallback using the observed Kaishi fonts, 44px centered word text, 25px meaning, image limits and audio placement. Prefer the actual installed reference when it differs. Copy presentation into a dedicated type; preserve required fields or wrap unavailable sentence/picture fields conditionally.

The fallback expects **raw, sanitized HTML ruby** in `Word Furigana`, unlike the bracket notation processed by Anki's `furigana:` filter. Only allow ruby/rt/rp and escaped text. Check that removing rt/rp yields the original word. The front must not expose furigana or a full reading. The back renders the annotated word once. Save original reading separately but do not display it as a standalone line.

## Native audio helper

```sh
python3 scripts/fetch_audio.py --input work/filtered-words.json --cache-dir work/audio
```

Input uses the normalized array in `sources-and-filtering.md`. Each record has a unique `source_key`, word and reading; an optional `audio_candidates` list contains **verified spellings of the same word and reading**. This is not a free homophone search. The helper fetches native JapanesePod101 audio, writes atomic checkpoints in batches and on completion, and can resume. It does not modify Anki.

Prefer supplied/native local media when already verified. Use current, permitted audio-provider access; if unavailable, another reliable native source may be used. The default lookup follows [Yomitan's audio source implementation](https://github.com/yomidevs/yomitan/blob/master/ext/js/media/audio-downloader.js):

`https://assets.languagepod101.com/dictionary/japanese/audiomp3.php?kanji=WORD&kana=READING`

A kana-only term normally uses only `kana`. Lookup readings are normalized to hiragana. JapanesePod101 can return an MP3 announcing that audio is unavailable. The observed SHA-256 placeholder is `ae6398b5a27bc8c0a771df6c907ade794be15518174773c58c7c7ddd17098906`; verify the current upstream behavior if results become suspicious. The helper requires consecutive complete MPEG Layer III frames and rejects an ID3 marker without frames. This is structural validation, not a pronunciation or full codec check. Headers and an MP3 extension alone are not enough to prove a correct recording. Distinguish missing recordings from exhausted network errors in the manifest.

Use 4–8 workers with a shared rate limit, bounded retries/timeouts, backoff on 429/503, and no TLS-verification bypass. Stop a provider batch on persistent access denials instead of hammering it. The helper defaults to 4 workers and 4 requests/second. Cache already missing results too; `--retry-unavailable` explicitly retries them. The established missing-audio preference is a blank field, not TTS.

Attach verified media with `storeMediaFile`, then use its returned filename in `[sound:...]`. Check write results, save a checkpoint of note IDs and filenames, and resume without creating new notes. A standard answer-side sound field produces the replay button and normal Anki playback. Do not change the user's audio settings unnecessarily. Attribute the audio provider in provenance; keep study-card metadata unobtrusive.

## Verification and handoff

- Count final notes and cards independently; compare to the retained manifest. Confirm destination identity and one recognition card per lexeme unless another layout was requested.
- Verify original content/audio fields and card IDs survive presentation-only changes. Compare relevant scheduling fields when schedule preservation is in doubt. Exclude concurrent user edits from claims about changes made by the agent.
- Check source ruby covers kanji and reconstructed base text equals the target word. Validate cases with kana prefixes, okurigana, individual kanji, kana-only terms and indivisible compound readings.
- Check all sound references exist in the local media collection and match their expected hashes. Reject placeholder audio. Decode representative recordings. Check supplied audio formats using an appropriate decoder rather than forcing them through the MP3 fetch helper.
- Inspect rendered question/answer HTML and a native card preview when available. Anki's renderer can replace `[sound:...]` with `[anki:play:a:0]`; the absence of the original sound tag in rendered HTML is not an audio loss. Do not claim a visual or audible test when only HTML/files were inspected.
- Export using the actual destination name, with media and scheduling. Verify the archive and real collection count. Some `.apkg` files contain both a one-note compatibility `collection.anki2` and the real `collection.anki21` (or a newer compressed format). Do not mistake the warning collection for the exported content.
- If Anki displays a full-sync conflict, do not choose upload/download automatically. Cancel when safe and finish locally; report that synchronization needs the user's version choice. A local `.apkg` backup does not authorize overwriting AnkiWeb.
