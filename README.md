# Knyght's Dictionarium

A searchable edition of **Thomas Elyot's *Dictionary*** (London, 1538) — one of the first Latin–English dictionaries — with each entry matched to the corresponding entry in Lewis & Short.

**[Browse the lexicon →](https://mimno.github.io/KnyghtLexicon/)**

---

## About the texts

**Thomas Elyot's *Dictionary*** (1538) is an early printed Latin–English lexicon, terse in style: a Latin headword or headword with principal parts, followed by a brief English gloss. The source XML is the EEBO-TCP transcription (identifier A21313), released into the public domain.

**Lewis & Short** (*A Latin Dictionary*, Oxford 1879) is the standard scholarly Latin reference. The Perseus Project digitised it and released the XML under CC BY-SA 4.0.

---

## Matching methodology

`match_lexicons.py` reads both XML files and attempts to link each Knyght lemma to one or more Lewis & Short entry identifiers. Matching is tried in order of confidence:

| Confidence | Description |
|---|---|
| `exact` | Normalised form matches a L&S headword or key directly |
| `uv_variant` | Matched after u/v or i/j substitution (common in Renaissance Latin) |
| `inflected_form` | Deponent infinitive (‑ari → ‑or) or participial form mapped to lemma |
| `gap_pattern` | OCR gap regex (`.{N}`) matched against length-indexed L&S forms |
| `prefix` | Share first 4 characters, length difference ≤ 3 |
| `fuzzy` | SequenceMatcher ratio ≥ 0.85 on same-initial-character candidates |
| `none` | No match found |

Of 26,542 Knyght entries: ~61% match exactly, ~28% match by prefix (candidate set only), and ~10% have no match — mostly phrases, biblical proper names, or fully illegible OCR gaps.

The web interface only displays L&S links for the four high-confidence levels (exact, uv\_variant, inflected\_form, gap\_pattern).

---

## Files

| File | Description |
|---|---|
| `A21313.xml` | Knyght *Dictionary* source (EEBO-TCP TEI P5) |
| `match_lexicons.py` | Lemma matching pipeline |
| `knyght_matched.xml` | Output: Knyght entries with L&S IDs embedded |
| `build_lexicon_json.py` | Converts matched XML to `lexicon.json` for the browser |
| `lexicon.json` | Pre-built search index (5.6 MB) |
| `index.html` | Web interface |

`lat.ls.perseus-eng2.xml` (Lewis & Short, 74 MB) is not included. Download it from the [PerseusDL/lexica](https://github.com/PerseusDL/lexica) repository.

---

## Running locally

```bash
# Regenerate the match file (requires lat.ls.perseus-eng2.xml)
python3 match_lexicons.py

# Regenerate the search index
python3 build_lexicon_json.py

# Serve the web interface
python3 -m http.server 8080
# then open http://localhost:8080/
```

---

## Licence

- `A21313.xml`: public domain (EEBO-TCP Phase 1, released 2015)
- Lewis & Short data: CC BY-SA 4.0 (Perseus Project)
- Code and web interface: MIT
