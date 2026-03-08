#!/usr/bin/env python3
"""
Parse knyght_matched.xml and write lexicon.json for the web interface.

Each entry:
  o  – original orth text (with OCR gaps as •)
  n  – normalised orth (lowercase, no diacritics, no punctuation) for search
  d  – definition text
  h  – section head (e.g. "A. ante B.")
  c  – L&S match confidence
  r  – L&S refs: list of {id, k (key), w (orth display)}
"""

import re
import json
import unicodedata
import html

MACRON_MAP = str.maketrans(
    'āēīōūĀĒĪŌŪáéíóúÁÉÍÓÚàèìòùÀÈÌÒÙâêîôûÂÊÎÔÛäëïöüÄËÏÖÜ',
    'aeiouAEIOUaeiouAEIOUaeiouAEIOUaeiouAEIOUaeiouAEIOU'
)

def normalize(s):
    s = s.translate(MACRON_MAP)
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-z0-9 ]', ' ', s.lower())
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def clean_def(d):
    """Unescape double-escaped entities, tidy whitespace."""
    d = html.unescape(d)     # &amp;amp; -> &amp; -> &
    d = re.sub(r'\s+', ' ', d).strip()
    # Capitalise first letter
    if d and d[0].islower():
        d = d[0].upper() + d[1:]
    return d


def parse_xml(path):
    with open(path, encoding='utf-8') as f:
        content = f.read()

    entry_pat = re.compile(r'<entryFree[^>]+>.*?</entryFree>', re.DOTALL)
    orth_pat  = re.compile(r'<orth[^>]*>(.*?)</orth>', re.DOTALL)
    def_pat   = re.compile(r'<def[^>]*>(.*?)</def>', re.DOTALL)
    head_pat  = re.compile(r'sectionHead="([^"]*)"')
    conf_pat  = re.compile(r'<lsMatch confidence="([^"]+)"')
    ref_pat   = re.compile(r'lsId="([^"]+)"\s+lsKey="([^"]+)"\s+lsOrth="([^"]*)"')

    entries = []
    for m in entry_pat.finditer(content):
        block = m.group(0)

        orth_m = orth_pat.search(block)
        def_m  = def_pat.search(block)
        head_m = head_pat.search(block)
        conf_m = conf_pat.search(block)
        if not orth_m or not def_m:
            continue

        orth = html.unescape(orth_m.group(1)).strip()
        defn = clean_def(def_m.group(1))
        head = html.unescape(head_m.group(1)).strip() if head_m else ''
        conf = conf_m.group(1) if conf_m else 'none'

        refs = []
        for r in ref_pat.finditer(block):
            refs.append({'id': r.group(1),
                         'k':  html.unescape(r.group(2)),
                         'w':  html.unescape(r.group(3))})

        # Normalised search key: strip OCR gaps and punctuation
        orth_clean = re.sub(r'[•〈〉◊…]', '', orth)
        norm = normalize(orth_clean)

        entry = {'o': orth, 'n': norm, 'd': defn, 'h': head, 'c': conf}
        if refs:
            entry['r'] = refs[:4]   # cap at 4 refs to keep JSON small
        entries.append(entry)

    return entries


if __name__ == '__main__':
    import os
    base = os.path.dirname(os.path.abspath(__file__))
    src  = os.path.join(base, 'knyght_matched.xml')
    dst  = os.path.join(base, 'lexicon.json')

    print(f'Parsing {src} …')
    entries = parse_xml(src)
    print(f'  {len(entries)} entries parsed')

    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, separators=(',', ':'))

    size_kb = os.path.getsize(dst) // 1024
    print(f'Written {dst} ({size_kb} KB)')
