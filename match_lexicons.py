#!/usr/bin/env python3
"""
Match Knyght (Elyot 1538) lexicon entries to Lewis & Short identifiers.

Knyght: A21313.xml  — TEI P5, entries as <item><label>Latin</label>def</item>
Lewis & Short: lat.ls.perseus-eng2.xml — TEI P4, entries as <entryFree key=... id=...>

Outputs: knyght_matched.xml — Knyght entries reformatted with LS match info.

Matching strategy (in order of confidence):
  exact          — normalised form matches L&S orth or key exactly
  uv_variant     — matched after u/v or i/j substitution
  inflected_form — deponent -ari/-iri matched to -or lemma; -atus to -o
  gap_pattern    — OCR gap regex (.{N}) matched against length-indexed forms
  prefix         — share first 4 chars, lengths within 3
  fuzzy          — SequenceMatcher ratio >= 0.85 on same-initial-char candidates
  none           — no match found
"""

import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

MACRON_MAP = str.maketrans(
    'āēīōūĀĒĪŌŪáéíóúÁÉÍÓÚàèìòùÀÈÌÒÙâêîôûÂÊÎÔÛäëïöüÄËÏÖÜ',
    'aeiouAEIOUaeiouAEIOUaeiouAEIOUaeiouAEIOUaeiouAEIOU'
)
LONG_S_MAP = str.maketrans('ſ', 's')


def normalize(s: str) -> str:
    """Lowercase, strip macrons/diacritics, collapse whitespace."""
    s = s.translate(MACRON_MAP)
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.lower().strip()
    return s


def uv_variants(s: str) -> list:
    """All u/v and i/j interchange variants of a normalised string."""
    variants = {s}
    for orig, repl in [('u', 'v'), ('v', 'u'), ('i', 'j'), ('j', 'i')]:
        for v in list(variants):
            variants.add(v.replace(orig, repl))
    return list(variants)


# ---------------------------------------------------------------------------
# Step 1: Parse Lewis & Short and build lookup indices
# ---------------------------------------------------------------------------

def strip_tags(s: str) -> str:
    return re.sub(r'<[^>]+>', '', s)


def parse_ls(path: str):
    """
    Returns:
      ls_entries    : list of dicts {key, id, orth_forms}
      norm_index    : normalized_form  -> [entry, ...]
      key_index     : normalized_key   -> [entry, ...]
      prefix_index  : first_4_chars    -> [normalized_form, ...]
      init_index    : first_char       -> [normalized_form, ...]
      length_index  : word_length      -> [normalized_form, ...]  (for gap regex)
    """
    print(f"Parsing Lewis & Short: {path}")
    with open(path, encoding='utf-8') as f:
        content = f.read()

    entry_pat = re.compile(r'<entryFree\s([^>]+)>(.*?)</entryFree>', re.DOTALL)
    orth_pat  = re.compile(r'<orth[^>]*>(.*?)</orth>', re.DOTALL)

    ls_entries   = []
    norm_index   = defaultdict(list)
    key_index    = defaultdict(list)
    prefix_index = defaultdict(list)
    init_index   = defaultdict(list)
    length_index = defaultdict(list)   # int -> [norm_form, ...]

    for m in entry_pat.finditer(content):
        attrs_str, body = m.group(1), m.group(2)

        key_m = re.search(r'key="([^"]+)"', attrs_str)
        id_m  = re.search(r'id="([^"]+)"',  attrs_str)
        if not key_m or not id_m:
            continue

        key   = key_m.group(1)
        ls_id = id_m.group(1)

        orth_forms = [strip_tags(o) for o in orth_pat.findall(body)]
        if not orth_forms:
            orth_forms = [re.sub(r'\d+$', '', key)]

        entry = {'key': key, 'id': ls_id, 'orth_forms': orth_forms}
        ls_entries.append(entry)

        for form in orth_forms:
            for variant in uv_variants(normalize(form)):
                if entry not in norm_index[variant]:
                    norm_index[variant].append(entry)
                if len(variant) >= 4:
                    pfx = variant[:4]
                    if variant not in prefix_index[pfx]:
                        prefix_index[pfx].append(variant)
                if variant:
                    if variant not in init_index[variant[0]]:
                        init_index[variant[0]].append(variant)
                    n = len(variant)
                    if variant not in length_index[n]:
                        length_index[n].append(variant)

        base_key = re.sub(r'\d+$', '', key)
        for variant in uv_variants(normalize(base_key)):
            if entry not in key_index[variant]:
                key_index[variant].append(entry)

    print(f"  Loaded {len(ls_entries)} entries, "
          f"{len(norm_index)} normalised forms")
    return ls_entries, norm_index, key_index, prefix_index, init_index, length_index


# ---------------------------------------------------------------------------
# Step 2: Parse Knyght entries
# ---------------------------------------------------------------------------

# Patterns for gap elements in Knyght XML
_GAP_N_PAT   = re.compile(
    r'<gap[^>]+extent="(\d+) letters?"[^>]*>.*?</gap>', re.DOTALL)
_GAP_WD_PAT  = re.compile(
    r'<gap[^>]+extent="1 word"[^>]*>.*?</gap>', re.DOTALL)
_GAP_SPAN_PAT= re.compile(
    r'<gap[^>]+extent="1 span"[^>]*>.*?</gap>', re.DOTALL)

_PLACEHOLDER_N   = '__GAPN{}__'   # filled with count
_PLACEHOLDER_WD  = '__GAPWORD__'
_PLACEHOLDER_UNK = '__GAPUNK__'


def _label_xml_to_gapped(label_xml: str) -> tuple:
    """
    Return (cleaned_text, has_gap, gap_chunk) where gap_chunk has
    __GAPN3__ etc. placeholders for gaps.
    """
    # Replace EOLhyphen / ligature markers
    chunk = re.sub(r'<g ref="char:EOLhyphen"/>-?', '', label_xml)
    chunk = re.sub(r'<g ref="char:EOLunhyphen"/>',  '', chunk)
    chunk = re.sub(r'<g [^>]+>.*?</g>',              '', chunk, flags=re.DOTALL)

    # Mark gaps before stripping tags
    has_gap = bool(_GAP_N_PAT.search(chunk) or
                   _GAP_WD_PAT.search(chunk) or
                   _GAP_SPAN_PAT.search(chunk))

    gap_chunk = _GAP_N_PAT.sub(
        lambda m: _PLACEHOLDER_N.format(m.group(1)), chunk)
    gap_chunk = _GAP_WD_PAT.sub(_PLACEHOLDER_WD, gap_chunk)
    gap_chunk = _GAP_SPAN_PAT.sub(_PLACEHOLDER_UNK, gap_chunk)
    gap_chunk = re.sub(r'<[^>]+>', '', gap_chunk)
    gap_chunk = gap_chunk.translate(LONG_S_MAP)
    gap_chunk = re.sub(r'\s+', ' ', gap_chunk).strip()

    # Plain text version (replace placeholders with •)
    plain = re.sub(r'__GAPN(\d+)__',
                   lambda m: '•' * int(m.group(1)), gap_chunk)
    plain = plain.replace(_PLACEHOLDER_WD,  '〈◊〉')
    plain = plain.replace(_PLACEHOLDER_UNK, '〈…〉')

    return plain, has_gap, gap_chunk


def _build_gap_regex(gap_token: str) -> tuple:
    """
    Given a gap token like 'Ab__GAPN1__ado', return (regex_pattern, min_len, max_len).
    Returns (None, 0, 0) if the token has unknown-length gaps (GAPWORD/GAPUNK).
    """
    if _PLACEHOLDER_WD in gap_token or _PLACEHOLDER_UNK in gap_token:
        return None, 0, 0

    # Calculate fixed-char count and total gap count
    gap_total = 0
    parts = re.split(r'(__GAPN\d+__)', gap_token)
    pat_parts = []
    for part in parts:
        gm = re.match(r'__GAPN(\d+)__', part)
        if gm:
            n = int(gm.group(1))
            gap_total += n
            pat_parts.append(f'.{{{n}}}')
        else:
            # Normalize the literal part (lowercase, strip diacritics)
            lit = normalize(part)
            # Remove spaces (gap was printed with spaces around it)
            lit = lit.replace(' ', '')
            if lit:
                pat_parts.append(re.escape(lit))

    if not pat_parts:
        return None, 0, 0

    pattern = '^' + ''.join(pat_parts) + '$'
    fixed_len = sum(len(normalize(p.replace(' ','')))
                    for p in parts
                    if not re.match(r'__GAPN\d+__', p))
    total_len = fixed_len + gap_total
    return pattern, total_len, total_len  # exact length known


def extract_lemmas_and_patterns(label_xml: str) -> tuple:
    """
    Returns (lemmas, gap_patterns) where:
      lemmas       : list of str  (first comma form, 'and'-split, ¶-stripped)
      gap_patterns : list of (compiled_regex, exact_len) — only when gaps present
    """
    plain, has_gap, gap_chunk = _label_xml_to_gapped(label_xml)

    # ---------- lemma text extraction (for regular matching) ----------
    parts_text = re.split(r'\band\b', plain, flags=re.IGNORECASE)
    lemmas = []
    for part in parts_text:
        first = part.split(',')[0].strip()
        first = re.sub(r'[.,;:\s•〈〉◊…]+$', '', first).strip()
        first = first.lstrip('¶').strip()   # strip paragraph mark
        if first and '〈' not in first:      # skip fully illegible tokens
            lemmas.append(first)

    # ---------- gap pattern extraction (for wildcard matching) ----------
    gap_patterns = []
    if has_gap:
        parts_gap = re.split(r'\band\b', gap_chunk, flags=re.IGNORECASE)
        for part in parts_gap:
            token = part.split(',')[0].strip()
            token = re.sub(r'[.,;:\s]+$', '', token).strip()
            token = token.lstrip('¶').strip()
            if not token:
                continue
            pat, lo, hi = _build_gap_regex(token)
            if pat and lo > 0:
                try:
                    compiled = re.compile(pat)
                    gap_patterns.append((compiled, lo))
                except re.error:
                    pass

    return lemmas, gap_patterns


def parse_knyght(path: str):
    print(f"Parsing Knyght: {path}")
    with open(path, encoding='utf-8') as f:
        content = f.read()

    body_start = content.find('<body>')
    if body_start == -1:
        raise ValueError("No <body> element found")
    body = content[body_start:]

    knyght_entries = []
    list_pat  = re.compile(r'<list>(.*?)</list>', re.DOTALL)
    head_pat  = re.compile(r'<head>(.*?)</head>', re.DOTALL)
    item_pat  = re.compile(r'<item>(.*?)</item>', re.DOTALL)
    label_pat = re.compile(r'<label>(.*?)</label>', re.DOTALL)

    for list_m in list_pat.finditer(body):
        list_xml  = list_m.group(1)
        head_m    = head_pat.search(list_xml)
        list_head = strip_tags(head_m.group(1)).strip() if head_m else ''

        for item_m in item_pat.finditer(list_xml):
            item_xml = item_m.group(1)
            label_m  = label_pat.search(item_xml)
            if not label_m:
                continue

            label_xml  = label_m.group(1)
            lemmas, gap_patterns = extract_lemmas_and_patterns(label_xml)

            # Plain display text (with • for gaps)
            plain, _, _ = _label_xml_to_gapped(label_xml)

            after_label = item_xml[label_m.end():]
            definition  = strip_tags(after_label).translate(LONG_S_MAP)
            definition  = re.sub(r'\s+', ' ', definition).strip()

            knyght_entries.append({
                'label_text':   plain,
                'lemmas':       lemmas,
                'gap_patterns': gap_patterns,
                'definition':   definition,
                'list_head':    list_head,
            })

    print(f"  Loaded {len(knyght_entries)} Knyght entries")
    return knyght_entries


# ---------------------------------------------------------------------------
# Step 3: Match
# ---------------------------------------------------------------------------

CONF_EXACT   = 'exact'
CONF_UV      = 'uv_variant'
CONF_FORM    = 'inflected_form'
CONF_GAP     = 'gap_pattern'
CONF_PREFIX  = 'prefix'
CONF_FUZZY   = 'fuzzy'
CONF_NONE    = 'none'
CONF_RANK    = [CONF_EXACT, CONF_UV, CONF_FORM, CONF_GAP,
                CONF_PREFIX, CONF_FUZZY, CONF_NONE]


def dedup(entries: list) -> list:
    seen, out = set(), []
    for e in entries:
        if e['id'] not in seen:
            seen.add(e['id'])
            out.append(e)
    return out


def verb_form_candidates(lemma: str) -> list:
    """
    Generate alternative lemma strings by reversing common inflected endings.
    Deponent infinitives (-ari, -eri, -iri) → try -or form.
    Participial forms (-atus, -itus) → try -o/-or.
    """
    norm = normalize(lemma)
    candidates = []
    # Deponent: -ari → -or  (e.g. apricari → apricor)
    if norm.endswith('ari') and len(norm) > 5:
        candidates.append(norm[:-3] + 'or')
        candidates.append(norm[:-3] + 'o')
    # Deponent: -iri → -ior or -or
    if norm.endswith('iri') and len(norm) > 5:
        candidates.append(norm[:-3] + 'ior')
        candidates.append(norm[:-3] + 'or')
    # Passive infinitive: -eri → -or, -o
    if norm.endswith('eri') and len(norm) > 5:
        candidates.append(norm[:-3] + 'or')
        candidates.append(norm[:-3] + 'o')
    # Perfect participle: -atus / -itus / -utus → -o
    for suffix in ('atus', 'ita', 'utus'):
        if norm.endswith(suffix) and len(norm) > len(suffix) + 2:
            candidates.append(norm[:-len(suffix)] + 'o')
            candidates.append(norm[:-len(suffix)] + 'or')
    # Accusative/genitive of 3rd decl: try removing -is, -em, -e, -i
    for suffix in ('em', 'is', 'um'):
        if norm.endswith(suffix) and len(norm) > len(suffix) + 3:
            candidates.append(norm[:-len(suffix)])
    return candidates


def match_lemma(lemma: str,
                norm_index, key_index,
                prefix_index, init_index) -> tuple:
    norm     = normalize(lemma)
    variants = uv_variants(norm)

    # 1. Exact / UV match
    hits = []
    for v in variants:
        hits.extend(norm_index.get(v, []))
        hits.extend(key_index.get(v, []))
    if hits:
        conf = CONF_EXACT if (norm in norm_index or norm in key_index) else CONF_UV
        return conf, dedup(hits)

    # 2. Inflected form candidates
    for cand in verb_form_candidates(lemma):
        for v in uv_variants(cand):
            hits.extend(norm_index.get(v, []))
            hits.extend(key_index.get(v, []))
    if hits:
        return CONF_FORM, dedup(hits)

    # 3. Prefix match
    if len(norm) >= 4:
        pfx  = norm[:4]
        phits = []
        for cand in prefix_index.get(pfx, []):
            if abs(len(norm) - len(cand)) <= 3:
                phits.extend(norm_index.get(cand, []))
        if phits:
            return CONF_PREFIX, dedup(phits)

    # 4. Fuzzy match
    if norm:
        pool       = init_index.get(norm[0], [])
        best_ratio = 0.0
        best_form  = None
        for cand in pool:
            r = SequenceMatcher(None, norm, cand, autojunk=False).ratio()
            if r > best_ratio:
                best_ratio = r
                best_form  = cand
        if best_ratio >= 0.85 and best_form:
            return CONF_FUZZY, dedup(norm_index.get(best_form, []))

    return CONF_NONE, []


def match_gap_patterns(gap_patterns: list,
                       length_index, norm_index) -> tuple:
    """Try each compiled gap-regex against L&S forms of the right length."""
    hits = []
    for compiled, exact_len in gap_patterns:
        for cand in length_index.get(exact_len, []):
            if compiled.match(cand):
                hits.extend(norm_index.get(cand, []))
    if hits:
        return CONF_GAP, dedup(hits)
    return CONF_NONE, []


def match_entry(entry: dict,
                norm_index, key_index,
                prefix_index, init_index,
                length_index) -> dict:
    best_conf    = CONF_NONE
    best_matches = []
    best_lemma   = None

    # Try each extracted lemma through the main pipeline
    for lemma in entry['lemmas']:
        conf, matches = match_lemma(lemma, norm_index, key_index,
                                    prefix_index, init_index)
        if CONF_RANK.index(conf) < CONF_RANK.index(best_conf):
            best_conf    = conf
            best_matches = matches
            best_lemma   = lemma
        if best_conf == CONF_EXACT:
            break

    # If not yet a confident match, try gap patterns (OCR wildcards)
    if (best_conf not in (CONF_EXACT, CONF_UV, CONF_FORM)
            and entry['gap_patterns']):
        conf, matches = match_gap_patterns(
            entry['gap_patterns'], length_index, norm_index)
        if CONF_RANK.index(conf) < CONF_RANK.index(best_conf):
            best_conf    = conf
            best_matches = matches
            best_lemma   = '(gap pattern)'

    return {**entry,
            'match_confidence': best_conf,
            'match_lemma':      best_lemma,
            'ls_matches':       best_matches}


# ---------------------------------------------------------------------------
# Step 4: Write output XML
# ---------------------------------------------------------------------------

def xml_escape(s: str) -> str:
    return (s.replace('&', '&amp;')
             .replace('<', '&lt;')
             .replace('>', '&gt;')
             .replace('"', '&quot;'))


def entry_to_xml(entry: dict) -> str:
    conf  = entry['match_confidence']
    label = xml_escape(entry['label_text'])
    defn  = xml_escape(entry['definition'])
    head  = xml_escape(entry['list_head'])

    lines = [f'  <entryFree source="Knyght1538" sectionHead="{head}">',
             f'    <orth lang="la">{label}</orth>',
             f'    <def lang="en">{defn}</def>']

    matches = entry['ls_matches']
    if matches:
        lines.append(f'    <lsMatch confidence="{conf}">')
        for m in matches:
            orths = ', '.join(m['orth_forms'][:3])
            lines.append(f'      <ref lsId="{m["id"]}" lsKey="{xml_escape(m["key"])}" '
                         f'lsOrth="{xml_escape(orths)}" />')
        lines.append('    </lsMatch>')
    else:
        lines.append('    <lsMatch confidence="none" />')

    lines.append('  </entryFree>')
    return '\n'.join(lines)


def write_output(matched_entries: list, output_path: str):
    print(f"Writing output: {output_path}")
    counts = defaultdict(int)
    for e in matched_entries:
        counts[e['match_confidence']] += 1
    total = len(matched_entries)

    conf_levels = [CONF_EXACT, CONF_UV, CONF_FORM, CONF_GAP,
                   CONF_PREFIX, CONF_FUZZY, CONF_NONE]

    stats_lines = '\n'.join(
        f'    {c:16s}: {counts[c]:6d}  ({100*counts[c]/total:.1f}%)'
        for c in conf_levels
    )

    header = f"""<?xml version="1.0" encoding="UTF-8"?>
<!--
  Knyght (Elyot 1538) lexicon reformatted with Lewis & Short match information.
  Source Knyght  : A21313.xml (EEBO-TCP Phase 1)
  Lewis & Short  : lat.ls.perseus-eng2.xml (Perseus Project, 1997)

  Match confidence levels:
    exact           = normalised form matches L&S orth or key exactly
    uv_variant      = matched after u/v or i/j substitution
    inflected_form  = deponent/participial form mapped to lemma
    gap_pattern     = OCR gap regex (.{{N}}) matched by word length
    prefix          = share first 4 chars, length difference <= 3
    fuzzy           = SequenceMatcher ratio >= 0.85, same initial char
    none            = no match found

  Statistics (total {total}):
{stats_lines}
-->
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>The Dictionary of Syr Thomas Eliot Knyght (1538) — matched to Lewis &amp; Short</title>
        <author>Elyot, Thomas, Sir, 1490?-1546</author>
        <respStmt>
          <resp>Lewis &amp; Short ID matching by</resp>
          <name>match_lexicons.py</name>
        </respStmt>
      </titleStmt>
    </fileDesc>
  </teiHeader>
  <text>
    <body>
      <div type="dictionary">
"""
    footer = "      </div>\n    </body>\n  </text>\n</TEI>\n"

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(header)
        for entry in matched_entries:
            f.write(entry_to_xml(entry))
            f.write('\n')
        f.write(footer)

    print("  Done.")
    for c in conf_levels:
        print(f"    {c:16s}: {counts[c]:6d}  ({100*counts[c]/total:.1f}%)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import os
    base = os.path.dirname(os.path.abspath(__file__))

    (ls_entries, norm_index, key_index,
     prefix_index, init_index, length_index) = parse_ls(
        os.path.join(base, 'lat.ls.perseus-eng2.xml')
    )
    knyght_entries = parse_knyght(os.path.join(base, 'A21313.xml'))

    print(f"Matching {len(knyght_entries)} entries…")
    matched = []
    for i, entry in enumerate(knyght_entries):
        matched.append(match_entry(entry, norm_index, key_index,
                                   prefix_index, init_index, length_index))
        if (i + 1) % 5000 == 0:
            print(f"  {i+1}/{len(knyght_entries)}")

    write_output(matched, os.path.join(base, 'knyght_matched.xml'))
