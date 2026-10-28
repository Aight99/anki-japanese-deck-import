# Japanese Deck Import for Anki

A Codex skill that imports Japanese vocabulary from jpdb, other websites, word lists, or `.apkg` files into Kaishi-style cards.

- Choose existing decks to exclude familiar words.
- Remove particles, grammar, interjections, and character names.
- Add native word audio; leave unavailable recordings blank.
- Show furigana above the corresponding kanji on the answer side.

## Install

Requires Codex, Python 3.9+, and Anki with AnkiConnect.

```sh
git clone https://github.com/Aight99/anki-japanese-deck-import.git "${CODEX_HOME:-$HOME/.codex}/skills/anki-japanese-deck-import"
```

## Example

With Anki running, ask Codex:

```text
Use $anki-japanese-deck-import to import this deck into Anki:
https://jpdb.io/anime/3904/re-zero-kara-hajimeru-isekai-seikatsu
```

The skill lists your decks and asks which ones to use for exclusions before importing. Studied words are excluded by default; you can choose all words from those decks instead.

Card presentation follows your installed [Kaishi](https://github.com/donkuri/Kaishi) deck.
