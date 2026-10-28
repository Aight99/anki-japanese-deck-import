# Source records and vocabulary decisions

## Normalized JSON

Use a UTF-8 JSON array. Each retained record needs:

```json
{
  "source_key": "provider:stable-entry:spelling:reading",
  "word": "お客様",
  "reading": "おきゃくさま",
  "meaning": "guest; visitor; customer",
  "furigana_html": "お<ruby>客<rt>きゃく</rt></ruby><ruby>様<rt>さま</rt></ruby>",
  "source_url": "https://provider.example/entry",
  "frequency": 44,
  "dictionary_ids": {"JMdict": "verified-entry-id"},
  "pos": ["noun"],
  "audio_candidates": [{"word": "お客様", "reading": "おきゃくさま"}]
}
```

`frequency`, `dictionary_ids`, `pos`, `audio_candidates` and example/media fields are optional. Add dictionary identities only after verifying their namespace and correspondence. jpdb numeric IDs are not universally interchangeable with JMdict: custom entries, names, revisions and grammatical entries exist. Keep a stable original source key even when a display spelling changes.

`furigana_html` may be absent during extraction, but resolve it for kanji entries before import. Preserve verified existing bracket furigana when using an Anki bracket template instead. Do not invent examples or silently claim complete per-kanji alignment when only an unsegmented reading is available. Review unresolved alignment; a justified compound ruby is preferable to fabricated per-character readings.

## Source adapters

- **jpdb:** Read the supplied page; follow its actual vocabulary-list and pagination links. Cache all vocabulary pages. Compare extracted counts with the displayed entry count; preserve frequencies and original ruby blocks. The bundled extractor works on the observed `.entry` / `.vocabulary-spelling` structure, fails on missing/duplicate entries, and performs no network access. If markup changes, inspect and adapt it rather than reporting zero words as success. Do not upload Anki's collection or study status to jpdb.
- **Other sites:** Use an available connector if sufficient; otherwise read the permitted public/authenticated content. Map fields and stable identities explicitly, retain original ruby and audio URLs where usable, and validate pagination. Reuse no jpdb-specific selector or source-ID assumption without checking it.
- **CSV/TSV/text:** Inspect delimiter, headers, encoding, reading and meaning fields. A reading line is not per-kanji furigana. Read source data as text, not formulas or executable content.
- **APKG:** Inspect in a temporary directory/temporary collection first. Distinguish the real collection from the warning/compatibility collection. Extract vocabulary, source audio and existing alignment; build filtered fresh notes rather than silently importing the package's scheduling, shared models or reverse-card templates.
- **Bare word list:** Resolve readings, meanings and alignment from an appropriate dictionary/source. Keep uncertainty visible; do not present dictionary disambiguation guesses as source-specific meanings.

## Familiarity and identity

The exclusion set is the selected deck union plus the chosen familiarity rule. `findNotes` with `prop:reps>0` identifies notes with an answered card; filter those IDs to target-word note types. A new reverse card must not make a studied recognition word appear unfamiliar. Introductory notes and all words incidentally appearing in sentence fields do not count as known target words.

For Kaishi, target fields are `Word`, `Word Reading`, `Word Meaning`; for Lapis they are usually `Expression`, `ExpressionReading`, `MainDefinition`. Inspect actual fields. Jlab is primarily sentence-based: do not mark every lemma in a sentence as a vocabulary target. Generic Basic/Front models require a field mapping before treating them as target-word cards.

Normalize Unicode width and reading kana for candidate lookup, while retaining the original display spelling. Split explicitly enumerated readings such as なに・なん. Do not remove long vowels, small kana, or voicing to force matches.

Use dictionary aliases with their reading/sense restrictions. Equal readings or translations alone are not lexical identity. If a kana spelling maps to multiple senses, inspect the existing meaning and the incoming entry. Different verified dictionary identities sharing a surface are homonyms to review, not automatically duplicate notes to merge. A stable source ID may group spelling variants only when their lexical identity is verified; preserve alternative readings/meanings where relevant.

## Content vocabulary

Use POS to find candidates for exclusion, then inspect source context and mixed senses. Exclude grammar even when a dictionary also tags it as a lexical verb: じゃない, ではない, ことがある, ことになる, ことができる, ようになる, ようにする, and てもいい are typical traps. Counting forms and standalone honorific suffixes do not belong in this user's content-vocabulary deck.

Keep ordinary nouns, verbs, adjectives, adverbs and lexicalized compounds. An idiom with lexical meaning is not automatically a grammar pattern. Conversely, a sentence constructed from already-known words is not necessarily a useful new lexeme. Avoid a giant universal word blacklist: ゲート, 魔獣, 精霊 and マナ can be useful fiction vocabulary, while a character with a common-noun spelling must be removed in that source's context.

Maintain a local decision manifest with `keep`, `exclude` and `review`, plus reasons and matched existing note IDs. Inspect frequent doubtful entries and all suspected proper names. Do not silently import unresolved cases; report them as held out for review.
