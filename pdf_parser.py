#!/usr/bin/env python3
# =============================================================================
# pdf_parser_v2.py
# IMD Bulletin Parser — rebuilt from study of 15+ real bulletins
# Fixes: 30 issues identified across pre-monsoon, monsoon onset, peak monsoon
# =============================================================================

import os
import re
import sys
import json
import base64
import requests
import pdfplumber
import pytz
from io import BytesIO
from datetime import datetime

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------

IMD_BULLETIN_PAGE = 'https://mausam.imd.gov.in/responsive/all_india_forcast_bulletin.php'
IST               = pytz.timezone('Asia/Kolkata')
GITHUB_TOKEN      = os.environ.get('GITHUB_TOKEN', '')
GITHUB_REPO       = os.environ.get('GITHUB_REPO', 'Ankiii1992/Weather_pdf_parse')
GITHUB_BRANCH     = 'main'
GITHUB_API        = 'https://api.github.com'

HEADERS_IMD = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}
HEADERS_GH = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept':        'application/vnd.github.v3+json',
    'Content-Type':  'application/json',
}

# -----------------------------------------------------------------------------
# SYSTEM PRIORITY — Tier 1 sort order
# -----------------------------------------------------------------------------

SYSTEM_PRIORITY = {
    'Super Cyclonic Storm':             1,
    'Extremely Severe Cyclonic Storm':  2,
    'Very Severe Cyclonic Storm':       3,
    'Severe Cyclonic Storm':            4,
    'Cyclonic Storm':                   5,
    'Deep Depression':                  6,
    'Depression':                       7,
    'Low Pressure Area':                8,
    'Monsoon Trough':                   9,
    'Shear Zone':                       10,
    'Offshore Trough':                  11,
    'East-West Trough':                 12,
    'Western Disturbance':              13,
    'North-South Trough':               14,
}

# -----------------------------------------------------------------------------
# SYSTEM FIELDS CONFIG — remove any field to exclude from JSON output
# -----------------------------------------------------------------------------

SYSTEM_FIELDS = {
    'Low Pressure Area': [
        'type', 'status', 'location', 'coords', 'distance_from',
        'on_land', 'movement', 'forecast', 'associated_cc', 'raw_text',
    ],
    'Depression': [
        'type', 'status', 'location', 'coords', 'distance_from',
        'on_land', 'movement', 'forecast', 'landfall', 'raw_text',
    ],
    'Deep Depression': [
        'type', 'status', 'location', 'coords', 'distance_from',
        'on_land', 'movement', 'forecast', 'landfall', 'raw_text',
    ],
    'Cyclonic Storm': [
        'type', 'status', 'location', 'coords', 'distance_from',
        'on_land', 'movement', 'forecast', 'landfall', 'raw_text',
    ],
    'Severe Cyclonic Storm': [
        'type', 'status', 'location', 'coords', 'distance_from',
        'on_land', 'movement', 'forecast', 'landfall', 'raw_text',
    ],
    'Very Severe Cyclonic Storm': [
        'type', 'status', 'location', 'coords', 'distance_from',
        'on_land', 'movement', 'forecast', 'landfall', 'raw_text',
    ],
    'Extremely Severe Cyclonic Storm': [
        'type', 'status', 'location', 'coords', 'distance_from',
        'on_land', 'movement', 'forecast', 'landfall', 'raw_text',
    ],
    'Super Cyclonic Storm': [
        'type', 'status', 'location', 'coords', 'distance_from',
        'on_land', 'movement', 'forecast', 'landfall', 'raw_text',
    ],
    'Monsoon Trough': [
        'type', 'position', 'passes_through', 'west_end', 'east_end',
        'east_end_system', 'across', 'level', 'raw_text',
    ],
    'Shear Zone': [
        'type', 'location', 'across', 'level', 'tilt', 'raw_text',
    ],
    'Offshore Trough': [
        'type', 'extent', 'level', 'raw_text',
    ],
    'East-West Trough': [
        'type', 'extent', 'across', 'level', 'tilt', 'raw_text',
    ],
    'North-South Trough': [
        'type', 'extent', 'across', 'level', 'raw_text',
    ],
    'Western Disturbance': [
        'type', 'form', 'location', 'axis', 'level',
        'trough_aloft', 'induced_uac', 'raw_text',
    ],
    'Upper Air Cyclonic Circulation': [
        'type', 'location', 'level', 'tilt',
        'induced', 'associated_with', 'raw_text',
    ],
    'Trough': [
        'type', 'subtype', 'extent', 'across', 'level', 'raw_text',
    ],
}

# -----------------------------------------------------------------------------
# TEXT NORMALISATION — fix PDF extraction artefacts before any parsing
# -----------------------------------------------------------------------------

# Merged words seen in real PDFs
MERGE_FIXES = [
    (r'\bextendingupto\b',              'extending upto'),
    (r'\bupto([\.\d]+)',                   r'upto \1'),   # fix merged upto1.5 → upto 1.5
    (r'\bextending up to\b',            'extending upto'),
    (r'\bupto\b',                       'upto'),
    (r'\bup to\b',                      'upto'),
    (r'\b([\d.]+)kmabovemeansealevel\b', r'\1 km above mean sea level'),
    (r'\bkmabovemeansealevel\b',        'km above mean sea level'),
    (r'\babovemeansealevel\b',          'above mean sea level'),
    (r'\bmeansealevel\b',               'mean sea level'),
    (r'\broughlyalong\b',               'roughly along'),
    (r'\bwithitsaxis\b',                'with its axis'),
    (r'\bcycloniccirculation\b',        'cyclonic circulation'),
    (r'\bneighbourhood\b',              'neighbourhood'),
    (r'\b([\d.]+)km\b',                 r'\1 km'),
    # Grammar variants → normalise
    (r'\brun from\b',                   'runs from'),    # "trough run from" → "runs from"
    (r'\blay over\b',                   'lies over'),    # past tense → present
    (r'\blay centered',                 'lies centered'),
    (r'\boff-shore\b',                  'offshore'),     # hyphen variant
    (r'\boff shore\b',                  'offshore'),
    (r'\bSeasonal trough\b',            'Monsoon trough'),  # alias
    (r'\bseasonal trough\b',            'monsoon trough'),
    # "between X km to Y km" → "between X & Y km"
    (r'between\s+([\d.]+)\s*km\s+to\s+([\d.]+)\s*km',
     r'between \1 & \2 km'),
    # Collapse spaces
    (r' {2,}', ' '),
]

def normalise_text(text):
    """Apply all merge fixes and grammar normalisations."""
    for pattern, repl in MERGE_FIXES:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text.strip()


# -----------------------------------------------------------------------------
# LEVEL PARSER
# -----------------------------------------------------------------------------

def parse_level(text):
    """
    Extract level info from a sentence.
    Returns a level dict or None.
    Handles: at X km, between X & Y km, extending upto X km,
             now seen at/between, tropospheric labels.
    """
    if not text:
        return None
    t = normalise_text(text)

    # now seen at / now seen between (level update sentences)
    now_seen_range = re.search(
        r'now\s+seen\s+between\s+([\d.]+)\s*(?:&|and)\s*([\d.]+)\s*km\s*above',
        t, re.IGNORECASE
    )
    if now_seen_range:
        lo, hi = float(now_seen_range.group(1)), float(now_seen_range.group(2))
        return {'type': 'range', 'min': lo, 'max': hi,
                'display': f'{lo}–{hi} km above MSL'}

    now_seen_single = re.search(
        r'now\s+seen\s+at\s+([\d.]+)\s*km\s*above',
        t, re.IGNORECASE
    )
    if now_seen_single:
        val = float(now_seen_single.group(1))
        return {'type': 'single', 'min': val, 'display': f'{val} km above MSL'}

    # between X & Y km above MSL
    range_m = re.search(
        r'between\s+([\d.]+)\s*(?:&|and)\s*([\d.]+)\s*km\s*above',
        t, re.IGNORECASE
    )
    if range_m:
        lo, hi = float(range_m.group(1)), float(range_m.group(2))
        return {'type': 'range', 'min': lo, 'max': hi,
                'display': f'{lo}–{hi} km above MSL'}

    # extending upto X km above MSL
    upto_m = re.search(
        r'(?:extending\s+|extends\s+)?upto\s+([\d.]+)\s*km\s*above',
        t, re.IGNORECASE
    )
    if upto_m:
        val = float(upto_m.group(1))
        return {'type': 'upto', 'max': val, 'display': f'upto {val} km above MSL'}

    # extends upto [tropospheric label]
    ext_label = re.search(
        r'extends?\s+upto\s+(lower\s*(?:&|and)?\s*(?:middle|upper)?\s*tropospheric)',
        t, re.IGNORECASE
    )
    if ext_label:
        label = re.sub(r'\s+', ' ', ext_label.group(1)).strip().lower()
        return label  # plain string fallback

    # at X km above MSL
    single_m = re.search(r'at\s+([\d.]+)\s*km\s*above', t, re.IGNORECASE)
    if single_m:
        val = float(single_m.group(1))
        return {'type': 'single', 'min': val, 'display': f'{val} km above MSL'}

    # in lower/middle/upper tropospheric levels — return plain string (no numeric values)
    tropo_m = re.search(
        r'in\s+(lower\s*(?:&|and)?\s*(?:middle\s*)?(?:&|and)?\s*(?:upper\s*)?tropospheric)\s*levels?',
        t, re.IGNORECASE
    )
    if tropo_m:
        label = re.sub(r'\s+', ' ', tropo_m.group(1)).strip().lower()
        label = re.sub(r'\s*(and|&)\s*', ' & ', label)
        return label  # plain string fallback

    # mean sea level — plain string
    if re.search(r'at\s+mean\s+sea\s+level|mean\s+sea\s+level', t, re.IGNORECASE):
        return 'mean sea level'  # plain string fallback

    return None


# -----------------------------------------------------------------------------
# TILT EXTRACTOR
# -----------------------------------------------------------------------------

def extract_tilt(text):
    """Extract tilt qualifier if present."""
    m = re.search(
        r'tilting\s+(south\w*|north\w*|east\w*|west\w*)\s+with\s+height',
        text, re.IGNORECASE
    )
    return m.group(0).strip() if m else None


# -----------------------------------------------------------------------------
# LOCATION EXTRACTOR
# -----------------------------------------------------------------------------

# Boundary words — location text must stop before any of these
_LOC_STOP = (
    r'at\s+[\d.]'
    r'|between\s+[\d.]'
    r'|extending\s+upto'
    r'|extends\s+upto'
    r'|upto\s+[\d.]'
    r'|in\s+lower\s+trop'
    r'|in\s+middle\s+trop'
    r'|in\s+upper\s+trop'
    r'|in\s+lower\s+&'
    r'|tilting\s+south'
    r'|tilting\s+north'
    r'|persists'
    r'|now\s+seen'
    r'|has\s+become'
    r'|has\s+moved'
    r'|and\s+extends?\s+upto'
    r'|\.$'
)

def _clean_loc(loc):
    """Strip trailing punctuation and noise from a captured location string."""
    if not loc:
        return None
    loc = loc.strip().rstrip(' ,&')
    # Strip any level text that bled in
    loc = re.split(r'\s+(?:at\s+[\d.]|between\s+[\d.]|extending|upto|in\s+lower|in\s+middle|in\s+upper|tilting)', loc, flags=re.IGNORECASE)[0]
    loc = loc.strip().rstrip(' ,&')
    return loc if loc else None


def extract_location(text):
    """
    Extract the CURRENT location of a system from a sentence.
    Priority:
      1. 'now lies over X' / 'lies over X' — current position after shift
      2. 'lies centered...over X' — centered location
      3. 'over X' — standard
      4. 'lies over X' — standard lies
    Always returns text AFTER the position verb (current location).
    """
    t = normalise_text(text)

    # "now lies over X" — shifted system, location is AFTER this verb
    m = re.search(
        r'now\s+lies\s+(?:centered\s+)?over\s+(.+?)(?=' + _LOC_STOP + r')',
        t, re.IGNORECASE
    )
    if m:
        return _clean_loc(m.group(1))

    # "lies centered...over X"
    m = re.search(
        r'lies\s+centered\s+.{0,40}?over\s+(.+?)(?=' + _LOC_STOP + r')',
        t, re.IGNORECASE
    )
    if m:
        return _clean_loc(m.group(1))

    # "lies over X"
    m = re.search(
        r'lies\s+over\s+(.+?)(?=' + _LOC_STOP + r')',
        t, re.IGNORECASE
    )
    if m:
        return _clean_loc(m.group(1))

    # "over X" — standard
    m = re.search(
        r'\bover\s+(.+?)(?=' + _LOC_STOP + r')',
        t, re.IGNORECASE
    )
    if m:
        return _clean_loc(m.group(1))

    return None


# -----------------------------------------------------------------------------
# COORDINATE PARSER
# -----------------------------------------------------------------------------

def parse_coords(text):
    """Extract lat/lon coordinates from text."""
    if not text:
        return None
    lat_m = re.search(r'[Ll]at(?:itude)?\.?\s*([\d.]+)°?\s*N', text)
    lon_m = re.search(r'[Ll]on(?:g(?:itude)?)?\.?\s*([\d.]+)°?\s*E', text)
    if lat_m and lon_m:
        return {'lat': float(lat_m.group(1)), 'lon': float(lon_m.group(1))}
    slash_m = re.search(r'([\d.]+)°?\s*N\s*/\s*([\d.]+)°?\s*E', text)
    if slash_m:
        return {'lat': float(slash_m.group(1)), 'lon': float(slash_m.group(2))}
    return None


def parse_nlm_coords(text):
    """Extract all NLM lat/lon coordinate pairs."""
    coords  = []
    matches = re.findall(r'([\d.]+)°?\s*N\s*/\s*([\d.]+)°?\s*E', text)
    for lat_s, lon_s in matches:
        coords.append({'lat': float(lat_s), 'lon': float(lon_s)})
    return coords if coords else None


# -----------------------------------------------------------------------------
# DISTANCE FROM PARSER (for Depression / Cyclone)
# -----------------------------------------------------------------------------

def parse_distance_from(text):
    """
    Extract distance references like:
    '70 km southeast of Puri (Odisha), 130 km East of Gopalpur (Odisha)'
    Returns list of {place, distance_km, direction} or None.
    """
    pattern = r'([\d]+)\s*km\s+([\w\-]+(?:\s+[\w\-]+)?)\s+of\s+([\w\s\(\)&]+?)(?=,\s*[\d]+\s*km|\.|$)'
    matches = re.findall(pattern, text, re.IGNORECASE)
    if not matches:
        return None
    result = []
    for dist, direction, place in matches:
        place = place.strip().rstrip(' )')
        if place:
            result.append({
                'place':       place.strip(),
                'distance_km': int(dist),
                'direction':   direction.strip().lower(),
            })
    return result if result else None


# -----------------------------------------------------------------------------
# SENTENCE SPLITTER
# -----------------------------------------------------------------------------

# Patterns that mark the START of a new system sentence
_SYSTEM_STARTERS = (
    r'The\s+(?:upper\s+air\s+)?cyclonic\s+circulation'
    r'|The\s+induced\s+upper\s+air\s+cyclonic'
    r'|An?\s+(?:upper\s+air\s+)?cyclonic\s+circulation'
    r'|The\s+Western\s+Disturbance'
    r'|A\s+Western\s+Disturbance'
    r'|The\s+(?:well[\s\-]?marked\s+)?low[\s\-]?pressure\s+area'
    r'|A\s+(?:well[\s\-]?marked\s+)?low[\s\-]?pressure\s+area'
    r'|The\s+(?:deep\s+)?depression'
    r'|A\s+(?:deep\s+)?depression'
    r'|Yesterday\'s\s+(?:depression|low\s+pressure)'
    r'|The\s+(?:very\s+severe|extremely\s+severe|severe|super)\s+cyclonic\s+storm'
    r'|A\s+(?:very\s+severe|extremely\s+severe|severe|super)\s+cyclonic\s+storm'
    r'|The\s+cyclonic\s+storm'
    r'|The\s+monsoon\s+trough'
    r'|The\s+seasonal\s+trough'
    r'|The\s+(?:east[\s\-]west|north[\s\-]south)\s+trough'
    r'|An?\s+(?:east[\s\-]west|north[\s\-]south)\s+trough'
    r'|The\s+(?:offshore|off[\s\-]shore)\s+trough'
    r'|An?\s+(?:offshore|off[\s\-]shore)\s+trough'
    r'|The\s+shear\s+zone'
    r'|A\s+trough\s+(?:runs|now\s+runs|from)'
    r'|The\s+trough'
    r'|However,\s+the\s+associated\s+cyclonic'
    r'|Under\s+the\s+influence\s+of'
    r'|The\s+(?:western\s+end|western\s+part)\s+of\s+(?:monsoon|seasonal)\s+trough'
)

# Continuation sentences — attach to parent system as forecast
_CONTINUATION_PATTERNS = [
    r'^It\s+is\s+(?:very\s+)?likely\s+to\s+move',
    r'^It\s+is\s+(?:very\s+)?likely\s+to\s+',
    r'^Thereafter[,\s]',
    r'^Subsequently\s+it\s+is',
]

# Suppress entirely — not active systems
_SUPPRESS_PATTERNS = [
    r'Under\s+(?:its|the)\s+influence\s+.{0,60}is\s+likely\s+to\s+form',
    r'Under\s+the\s+influence\s+of\s+these\s+systems',
    r'likely\s+to\s+affect\s+(?:northwest|northeast|north|south|west|east)?\s*india',
    r'A\s+fresh\s+[Ww]estern\s+[Dd]isturbance',
    r'has\s+moved\s+away\s+(?:north|south|east|west)',
]


def is_continuation(sentence):
    """Returns True if sentence is a continuation of the previous system."""
    s = sentence.strip()
    return any(re.match(p, s, re.IGNORECASE) for p in _CONTINUATION_PATTERNS)


def is_suppressed(sentence):
    """Returns True if sentence should be completely ignored."""
    s = sentence.strip()
    return any(re.search(p, s, re.IGNORECASE) for p in _SUPPRESS_PATTERNS)


def split_sentences(text):
    """
    Split Met Analysis text into individual system sentences.
    Handles bullet points, merged sentences, and all known starters.
    Accepts either raw multi-line PDF text or pre-processed single-line-per-sentence text.
    """
    # Normalise first
    text = normalise_text(text)

    # Remove bullet characters
    text = re.sub(r'^\s*[❖•\-\*✦◆]\s*', '', text, flags=re.MULTILINE)

    # Insert newline before each known system starter (handles merged paragraphs)
    text = re.sub(
        r'(?<=[.!?])\s+(?=' + _SYSTEM_STARTERS + r')',
        '\n',
        text,
        flags=re.IGNORECASE
    )

    # Join lines that don't end with period back to previous line
    # (fixes PDF line-wrap fragments like "...above\nmean sea level persists.")
    joined_lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if joined_lines and not joined_lines[-1].endswith('.'):
            # Previous line didn't end with period — this is a continuation
            joined_lines[-1] = joined_lines[-1] + ' ' + line
        else:
            joined_lines.append(line)

    raw = [s.strip() for s in joined_lines if s.strip()]

    # Handle "and another over X" — two UACs in one sentence
    expanded = []
    for sent in raw:
        parts = re.split(r'\s+and\s+another\s+over\s+', sent, flags=re.IGNORECASE)
        if len(parts) == 2:
            # Extract shared level from end of sentence
            level_text = ''
            level_m = re.search(
                r'(?:at\s+[\d.]|between\s+[\d.]|extending\s+upto|in\s+\w+\s+tropospheric).*$',
                parts[1], re.IGNORECASE
            )
            if level_m:
                level_text = level_m.group(0)
            # First UAC — keep as is (level already in sentence)
            expanded.append(parts[0].rstrip(' ,') + (' ' + level_text if level_text and level_text not in parts[0] else ''))
            # Second UAC — rebuild sentence
            # Determine prefix from first part
            prefix_m = re.match(r'^(An?\s+(?:upper\s+air\s+)?cyclonic\s+circulation\s+\w+)', parts[0], re.IGNORECASE)
            prefix = prefix_m.group(1) if prefix_m else 'An upper air cyclonic circulation lies'
            expanded.append(f'{prefix} over {parts[1]}')
        else:
            expanded.append(sent)

    return expanded


# -----------------------------------------------------------------------------
# MET ANALYSIS EXTRACTOR
# -----------------------------------------------------------------------------

def extract_met_analysis(page_text):
    """
    Extract and clean the full Meteorological Analysis page text.
    Returns one sentence per line as a single string.
    """
    text = re.sub(r'\*Red color warning.*$', '', page_text, flags=re.IGNORECASE | re.DOTALL).strip()
    text = re.sub(r'^Meteorological\s+Analysis[^\n]*\n', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'^\s*[❖•\-\*✦◆]\s*', '', text, flags=re.MULTILINE)

    # Fix run-together words
    run_fixes = [
        (r'TheWesternDisturbance', 'The Western Disturbance'),
        (r'Theupperair\b', 'The upper air'),
        (r'Theupperaircycloniccirculationovercentral([A-Za-z])', r'The upper air cyclonic circulation over central \1'),
        (r'TheupperaircycloniccirculationoverSoutheast', 'The upper air cyclonic circulation over Southeast'),
        (r'TheupperaircycloniccirculationoverEastcentral', 'The upper air cyclonic circulation over Eastcentral'),
        (r'Theupperaircycloniccirculationover([A-Z])', r'The upper air cyclonic circulation over \1'),
        (r'Theupperair cycloniccirculationover', 'The upper air cyclonic circulation over'),
        (r'cycloniccirculationover([A-Z])', r'cyclonic circulation over \1'),
        (r'\bSoutheastArabian\b', 'Southeast Arabian'),
        (r'\bArabianSea\b', 'Arabian Sea'),
        (r'([a-z])([A-Z][a-z]{3,})', r'\1 \2'),
        (r' {2,}', ' '),
    ]
    for pattern, repl in run_fixes:
        text = re.sub(pattern, repl, text)

    # Insert newlines at sentence boundaries
    text = re.sub(r'\.\s+(The\s|An?\s|A\s)', r'.\n\1', text)

    lines  = [l.strip() for l in text.splitlines() if l.strip()]
    sentences = []
    current   = ''
    for line in lines:
        current = (current + ' ' + line).strip() if current else line
        if re.search(r'\.\s*$', current):
            sentences.append(re.sub(r' {2,}', ' ', current).strip())
            current = ''
    if current.strip():
        sentences.append(current.strip())

    return '\n'.join(sentences)


# -----------------------------------------------------------------------------
# MONSOON TEXT EXTRACTOR
# -----------------------------------------------------------------------------

def extract_monsoon_text(text):
    """Extract the Advance of Southwest Monsoon / NLM section."""
    clean = re.sub(r'[ \t]+', ' ', text)
    clean = re.sub(r'\r\n|\r', '\n', clean)
    clean = re.sub(r'\n{3,}', '\n\n', clean)

    adv_m = re.search(
        r'Advance\s+of\s+Southwest\s+Monsoon[^\n]*\n(.*?)'
        r'(?=\n\s*(?:Weather\s+Forecast|Main\s+Features|Significant\s+Weather'
        r'|Northeast\s+India|Northwest\s+India|South\s+Peninsular'
        r'|Central\s+India|East\s+India|West\s+India|\Z))',
        clean, re.IGNORECASE | re.DOTALL
    )
    if adv_m:
        section = adv_m.group(1)
    else:
        nlm_m = re.search(
            r'((?:[❖•\-\*]\s*)?The\s+Northern\s+Limit\s+of\s+Monsoon.+?)'
            r'(?=\n\s*(?:Weather\s+Forecast|Main\s+Features|\Z))',
            clean, re.IGNORECASE | re.DOTALL
        )
        section = nlm_m.group(1) if nlm_m else None

    if not section:
        return None
    section = re.sub(r'^\s*[❖•\-\*]\s*', '', section, flags=re.MULTILINE)
    section = re.sub(r'\s+', ' ', section).strip()
    return section if section else None


# -----------------------------------------------------------------------------
# SYSTEM CLASSIFIERS
# -----------------------------------------------------------------------------

def _build_system(**kwargs):
    """Build a system dict, dropping None values."""
    return {k: v for k, v in kwargs.items() if v is not None}


def filter_system(system):
    """Filter system to only include fields defined in SYSTEM_FIELDS."""
    stype   = system.get('type', '')
    allowed = SYSTEM_FIELDS.get(stype, list(system.keys()))
    return {k: v for k, v in system.items() if k in allowed and v is not None}


def classify_uac(sent, raw):
    """Classify Upper Air Cyclonic Circulation."""
    induced       = bool(re.search(r'\binduced\b', sent, re.IGNORECASE))
    assoc_with_wd = bool(re.search(r'\bwestern\s+disturbance\b', sent, re.IGNORECASE))
    loc           = extract_location(sent)
    level         = parse_level(sent)
    tilt          = extract_tilt(sent)

    return _build_system(
        type           = 'Upper Air Cyclonic Circulation',
        location       = loc,
        level          = level,
        tilt           = tilt,
        induced        = induced if induced else None,
        associated_with= 'WD' if (induced and assoc_with_wd) else None,
        raw_text       = raw,
    )


def classify_wd(sent, raw):
    """Classify Western Disturbance."""
    system = {'type': 'Western Disturbance', 'raw_text': raw}

    # Determine form
    if re.search(r'as\s+(?:a\s+)?(?:an?\s+)?(?:upper\s+air\s+)?cyclonic\s+circulation|seen\s+as\s+(?:a\s+)?cyclonic', sent, re.IGNORECASE):
        system['form'] = 'cyclonic_circulation'
        # Try standard "over X" first, then fallback: "as a cyclonic circulation [LOCATION] at/extending"
        loc = extract_location(sent)
        if not loc:
            # Pattern: "as a cyclonic circulation LOCATION at/between/extending/persists"
            cc_loc_m = re.search(
                r'as\s+(?:a\s+)?(?:an?\s+)?(?:upper\s+air\s+)?cyclonic\s+circulation\s+(?:over\s+)?(.+?)'
                r'(?=\s+(?:at\s+[\d.]|between\s+[\d.]|extending|persists|with\s+a\s+trough|\.$|$))',
                sent, re.IGNORECASE
            )
            if cc_loc_m:
                loc = cc_loc_m.group(1).strip().rstrip(' ,')
        system['location'] = loc
        system['level']    = parse_level(sent)

        # Trough aloft
        aloft_m = re.search(
            r'trough\s+aloft.+?(?:roughly\s+along|along)\s+(.+?)(?:\.|$)',
            sent, re.IGNORECASE
        )
        if aloft_m:
            aloft_lvl = re.search(r'at\s+([\d.]+)\s*km\s*above', aloft_m.group(0), re.IGNORECASE)
            system['trough_aloft'] = _build_system(
                axis  = aloft_m.group(1).strip().rstrip(' ,'),
                level = {'type': 'single', 'min': float(aloft_lvl.group(1)),
                         'display': f'{aloft_lvl.group(1)} km above MSL'} if aloft_lvl else None,
            )
    elif re.search(r'as\s+(?:a\s+)?(?:an?\s+)?(?:upper\s+air\s+)?cyclonic', sent, re.IGNORECASE):
        system['form']     = 'upper_air_cc'
        system['location'] = extract_location(sent)
        system['level']    = parse_level(sent)
    else:
        system['form']  = 'trough_in_westerlies'
        loc_m = re.search(
            r'(?:now\s+runs?\s+)?(?:roughly\s+)?along\s+(.+?)(?:\s+persists|\s+and\s+|\s+has\s+moved|\.$|$)',
            sent, re.IGNORECASE
        )
        if loc_m:
            loc_str = loc_m.group(1).strip().rstrip(' ,')
            # Strip level text that may have bled in
            loc_str = re.split(r'\s+at\s+[\d.]|\s+between\s+[\d.]', loc_str)[0].strip()
            system['axis'] = 'along ' + loc_str
        system['level'] = parse_level(sent)

    return {k: v for k, v in system.items() if v is not None}


def classify_lpa(sent, raw, stype='Low Pressure Area'):
    """Classify LPA / Depression / Cyclone variants."""
    # Determine status
    if re.search(r'has\s+concentrated\s+into|has\s+formed', sent, re.IGNORECASE):
        status = 'forming'
    elif re.search(r'has\s+become\s+less\s+marked', sent, re.IGNORECASE):
        status = 'less_marked'
    elif re.search(r'weaken\s+gradually', sent, re.IGNORECASE):
        status = 'weakening'
    else:
        status = 'active'

    loc    = extract_location(sent)
    coords = parse_coords(sent)
    dist   = parse_distance_from(sent)

    # on_land — no coords and no distance_from references
    on_land = True if (not coords and not dist and loc and
                       not re.search(r'bay\s+of\s+bengal|arabian\s+sea|sea\s+of|ocean|coast\s+off',
                                     loc, re.IGNORECASE)) else False

    # movement
    mov_m = re.search(
        r'(?:moved?|moving)\s+([\w\-]+wards?(?:\s+and\s+[\w\-]+wards?)?)',
        sent, re.IGNORECASE
    )
    movement = mov_m.group(1).strip() if mov_m else None

    # landfall (for DD and stronger)
    landfall = None
    if stype not in ('Low Pressure Area', 'Well Marked Low Pressure Area'):
        lf_m = re.search(
            r'cross\s+(?:the\s+)?(.+?coast.+?)\s+(?:as\s+a\s+([\w\s]+?))?\s+(?:during|by|on)\s+(.+?)(?:\.|$)',
            sent, re.IGNORECASE
        )
        if lf_m:
            landfall = _build_system(
                location = lf_m.group(1).strip(),
                as_      = lf_m.group(2).strip() if lf_m.group(2) else None,
                time     = lf_m.group(3).strip(),
            )

    return _build_system(
        type         = stype,
        status       = status,
        location     = loc,
        coords       = coords,
        distance_from= dist,
        on_land      = on_land if on_land else None,
        movement     = movement,
        landfall     = landfall,
        raw_text     = raw,
    )


def classify_monsoon_trough(sent, raw):
    """
    Classify Monsoon Trough / Seasonal Trough.

    5 cases:
    1. City list: passes_through = full list including terminus
    2. West/East end explicitly mentioned (rare): west_end{position,passes_through}, east_end{position,passes_through}
    3. Whole trough position only: position field
    4. Foothills: position = "foothills of Himalayas"
    5. Minimum: just type + level
    """
    system = {'type': 'Monsoon Trough', 'raw_text': raw}

    # ── Whole trough position ────────────────────────────────────────────────
    if re.search(r'foothills\s+of\s+himalaya', sent, re.IGNORECASE) or \
       re.search(r'(?:running|shifted|lying)\s+(?:close\s+to|along|near)\s+foothills', sent, re.IGNORECASE):
        system['position'] = 'foothills of Himalayas'

    elif re.search(r'south\s+of\s+(?:its\s+)?normal', sent, re.IGNORECASE) and \
         not re.search(r'western\s+end|eastern\s+end', sent, re.IGNORECASE):
        system['position'] = 'south of normal'

    elif re.search(r'north\s+of\s+(?:its\s+)?normal', sent, re.IGNORECASE) and \
         not re.search(r'western\s+end|eastern\s+end', sent, re.IGNORECASE):
        system['position'] = 'north of normal'

    elif re.search(r'near\s+(?:its\s+)?normal', sent, re.IGNORECASE) and \
         not re.search(r'western\s+end|eastern\s+end', sent, re.IGNORECASE):
        system['position'] = 'near normal'

    elif re.search(r'normal\s+position', sent, re.IGNORECASE) and \
         not re.search(r'western\s+end|eastern\s+end', sent, re.IGNORECASE):
        system['position'] = 'normal'

    # ── West/East end explicitly mentioned (Case 2 — rare) ──────────────────
    if re.search(r'western\s+end|eastern\s+end', sent, re.IGNORECASE):
        west_end = {}
        east_end = {}

        # West end position
        wp = re.search(
            r'[Ww]estern\s+end\s+(?:of\s+monsoon\s+trough\s+)?(?:runs?|lies?)\s+(.+?)'
            r'(?:\s+and\s+eastern|\s+at\s+mean|\.$|$)',
            sent, re.IGNORECASE
        )
        if wp:
            wp_text = wp.group(1).strip().rstrip(' ,')
            # Check if position or city list
            if re.search(r'normal|foothills', wp_text, re.IGNORECASE):
                west_end['position'] = _normalise_position(wp_text)
            else:
                # City list
                cities = _split_city_list(wp_text)
                if cities: west_end['passes_through'] = cities

        # West end passes_through if also has "passes through"
        wp_cities_m = re.search(
            r'[Ww]estern\s+end.+?(?:passes|pass)\s+through\s+(.+?)'
            r'(?:\s+and\s+eastern|\s+and\s+thence|\s+at\s+mean|\.$|$)',
            sent, re.IGNORECASE
        )
        if wp_cities_m:
            cities = _split_city_list(wp_cities_m.group(1))
            if cities: west_end['passes_through'] = cities

        # East end position
        ep = re.search(
            r'[Ee]astern\s+end\s+(?:runs?|lies?)\s+(.+?)(?:\s+at\s+mean|\.$|$)',
            sent, re.IGNORECASE
        )
        if ep:
            ep_text = ep.group(1).strip().rstrip(' ,.')
            if re.search(r'normal|foothills', ep_text, re.IGNORECASE):
                east_end['position'] = _normalise_position(ep_text)
            else:
                cities = _split_city_list(ep_text)
                if cities: east_end['passes_through'] = cities

        if west_end: system['west_end'] = west_end
        if east_end: system['east_end'] = east_end

    # ── City list (Case 1 — most common) ────────────────────────────────────
    elif re.search(r'(?:passes|pass|continues?)\s+(?:to\s+pass\s+)?through', sent, re.IGNORECASE):
        # Extract everything between "passes through" and level/end markers
        cities_m = re.search(
            r'(?:passes|pass|continues?)\s+(?:to\s+pass\s+)?through\s+(.+?)'
            r'(?=\s+(?:extending|extends|upto\s+[\d.]|at\s+[\d.]|between\s+[\d.]|\.$|$)|$)',
            sent, re.IGNORECASE
        )
        if cities_m:
            raw_cities = cities_m.group(1)
            # Extract "thence...to TERMINUS" and append to city list
            thence_m = re.search(
                r'(?:and\s+)?thence\s+[\w\-]+wards?\s+to\s+(.+?)$',
                raw_cities, re.IGNORECASE
            )
            terminus = None
            if thence_m:
                terminus = thence_m.group(1).strip().rstrip(' ,.')
                # Strip trailing "and" from terminus
                terminus = re.sub(r'\s+and\s*$', '', terminus, flags=re.IGNORECASE).strip()
                # Strip leading "the" from terminus
                terminus = re.sub(r'^the\s+', '', terminus, flags=re.IGNORECASE).strip()
                # Remove thence part from cities raw
                raw_cities = raw_cities[:thence_m.start()].strip()

            cities = _split_city_list(raw_cities)
            if terminus:
                cities.append(terminus)
            if cities:
                system['passes_through'] = cities

    system['level'] = parse_level(sent)
    return {k: v for k, v in system.items() if v is not None}


def _normalise_position(text):
    """Normalise position description to standard value."""
    t = text.lower().strip()
    if 'foothills' in t: return 'foothills of Himalayas'
    if 'south' in t and 'normal' in t: return 'south of normal'
    if 'north' in t and 'normal' in t: return 'north of normal'
    if 'near' in t and 'normal' in t: return 'near normal'
    if 'normal' in t: return 'normal'
    return text.strip()


def _split_city_list(text):
    """
    Split a city list by comma, treating system references as single items.
    e.g. "Jaisalmer, Kota, center of LPA over NW MP, Sagar, Puri"
    → ["Jaisalmer", "Kota", "center of LPA over NW MP", "Sagar", "Puri"]
    """
    if not text:
        return []
    # Clean up
    text = re.sub(r'\s+and\s*$', '', text.strip())  # strip trailing "and"
    text = text.strip().rstrip(' ,.')

    # Split by comma
    raw_items = re.split(r',\s*', text)
    items = []
    current = ''
    for item in raw_items:
        item = item.strip()
        if not item:
            continue
        # If current is accumulating a system reference, check if complete
        if current:
            current = current + ', ' + item
            # System reference ends when we have a standalone location
            # Heuristic: if item doesn't look like continuation of "over X"
            if not re.search(r'^(?:and\s+)?adjoining|^&', item, re.IGNORECASE):
                items.append(current.strip())
                current = ''
        elif re.search(r'^center\s+of|^(?:the\s+)?(?:well\s+marked\s+)?low\s+pressure|^(?:the\s+)?(?:upper\s+air\s+)?cyclonic\s+circulation', item, re.IGNORECASE):
            # Start accumulating system reference
            current = item
        else:
            items.append(item)
    if current:
        items.append(current.strip())
    return [i for i in items if i]



def classify_shear_zone(sent, raw):
    """Classify Shear Zone.
    location = full descriptive string: "roughly along 15°N over Indian region"
    """
    # Extract latitude line: "roughly along Lat. 15°N" or "roughly along 22°N"
    lat_m = re.search(r'(?:roughly\s+)?along\s+(?:Lat\.?\s*)?([\.\d]+°?\s*N)', sent, re.IGNORECASE)
    lat_line = lat_m.group(1).strip() if lat_m else None

    # Extract "over X" region
    over_m = re.search(
        r'\bover\s+(.+?)(?=\s+(?:at\s+[\d.]|between\s+[\d.]|extending|persists|roughly|across|\.$))',
        sent, re.IGNORECASE
    )
    over_loc = _clean_loc(over_m.group(1)) if over_m else None

    # Build location: combine lat line + over region into full descriptive string
    if lat_line and over_loc:
        location = f'roughly along {lat_line} over {over_loc}'
    elif lat_line:
        location = f'roughly along {lat_line}'
    elif over_loc:
        location = over_loc
    else:
        location = None

    # Across — passing through multiple locations
    across_m = re.search(
        r'across\s+(.+?)(?=\s+(?:at\s+[\d.]|between\s+[\d.]|extending|persists|\.$))',
        sent, re.IGNORECASE
    )
    across = across_m.group(1).strip() if across_m else None

    return _build_system(
        type     = 'Shear Zone',
        location = location,
        across   = across,
        level    = parse_level(sent),
        tilt     = extract_tilt(sent),
        raw_text = raw,
    )


def classify_offshore_trough(sent, raw):
    """Classify Offshore Trough."""
    # Extent: "along X to Y" or "along X-Y"
    extent_m = re.search(
        r'along\s+(.+?)(?=\s+(?:persists|at\s+[\d.]|extending|\.$|$))',
        sent, re.IGNORECASE
    )
    extent = extent_m.group(1).strip().rstrip(' ,') if extent_m else None

    return _build_system(
        type     = 'Offshore Trough',
        extent   = extent,
        level    = parse_level(sent),
        raw_text = raw,
    )


def classify_ew_trough(sent, raw):
    """Classify East-West Trough."""
    # Extract optional lat line: "roughly along Lat. 15°N"
    lat_m = re.search(r'(?:roughly\s+)?along\s+Lat\.?\s*([\.\d]+°?\s*N)', sent, re.IGNORECASE)
    lat_label = lat_m.group(1).strip() if lat_m else None

    # Extent: "from X to Y"
    extent_m = re.search(
        r'from\s+(.+?)\s+to\s+(.+?)(?=\s+(?:at\s+[\d.]|between\s+[\d.]|extending|across|persists|\.$|$))',
        sent, re.IGNORECASE
    )
    if extent_m:
        w = extent_m.group(1).strip()
        e = extent_m.group(2).strip()
        # Strip any lat label that bled into west end
        w = re.sub(r'(?:roughly\s+)?along\s+Lat\.?\s*[\.\d]+°?\s*N\s*', '', w, flags=re.IGNORECASE).strip()
        extent = f"{w} to {e}"
        if lat_label:
            extent = f"along {lat_label}: {extent}"
    elif lat_label:
        extent = f"along {lat_label}"
    else:
        along_m = re.search(r'(?:runs?\s+)?(?:roughly\s+)?along\s+(.+?)(?=\s+(?:at\s+[\d.]|between|\.$|$))', sent, re.IGNORECASE)
        extent = f"along {along_m.group(1).strip()}" if along_m else None

    via_m = re.search(
        r'across\s+(.+?)(?=\s+(?:at\s+[\d.]|between\s+[\d.]|extending|persists|\.$|$))',
        sent, re.IGNORECASE
    )

    return _build_system(
        type     = 'East-West Trough',
        extent   = extent,
        across   = via_m.group(1).strip() if via_m else None,
        level    = parse_level(sent),
        tilt     = extract_tilt(sent),
        raw_text = raw,
    )


def classify_ns_trough(sent, raw):
    """Classify North-South Trough."""
    extent_m = re.search(
        r'from\s+(.+?)\s+to\s+(.+?)(?=\s+(?:across|at\s+[\d.]|extending|persists|\.$|$))',
        sent, re.IGNORECASE
    )
    via_m = re.search(
        r'across\s+(.+?)(?=\s+(?:at\s+[\d.]|extending|persists|\.$|$))',
        sent, re.IGNORECASE
    )
    ns_extent = None
    if extent_m:
        w = _clean_extent(extent_m.group(1).strip())
        e = _clean_extent(extent_m.group(2).strip())
        ns_extent = f"{w} to {e}" if w and e else None

    return _build_system(
        type     = 'North-South Trough',
        extent   = ns_extent,
        across   = via_m.group(1).strip() if via_m else None,
        level    = parse_level(sent),
        raw_text = raw,
    )


def _clean_extent(extent):
    """
    Strip 'the above cyclonic circulation over' and similar prefixes from extent.
    Keeps only the meaningful location part.
    """
    if not extent:
        return None
    # Strip common prefixes
    prefixes = [
        r'^the\s+above\s+(?:upper\s+air\s+)?cyclonic\s+circulation\s+over\s+',
        r'^(?:upper\s+air\s+)?cyclonic\s+circulation\s+over\s+',
        r'^the\s+above\s+',
        r'^above\s+',
    ]
    result = extent.strip()
    for prefix in prefixes:
        result = re.sub(prefix, '', result, flags=re.IGNORECASE).strip()
    return result if result else None


def classify_generic_trough(sent, raw):
    """Classify generic unnamed trough (Tier 2)."""
    if re.search(r'westerlies|along\s+long\.', sent, re.IGNORECASE):
        subtype = 'westerlies'
        loc_m   = re.search(
            r'(?:roughly\s+)?along\s+(.+?)(?=\s+(?:at\s+[\d.]|extending|persists|\.$|$))',
            sent, re.IGNORECASE
        )
        extent  = f"along {loc_m.group(1).strip()}" if loc_m else None
        via     = None
    else:
        subtype  = 'general'
        extent_m = re.search(
            r'from\s+(.+?)\s+to\s+(.+?)(?=\s+(?:across|at\s+[\d.]|extending|persists|\.$|$))',
            sent, re.IGNORECASE
        )
        if extent_m:
            west = _clean_extent(extent_m.group(1).strip())
            east = _clean_extent(extent_m.group(2).strip())
            extent = f"{west} to {east}" if west and east else None
        else:
            extent = None
        via_m    = re.search(
            r'across\s+(.+?)(?=\s+(?:at\s+[\d.]|extending|persists|\.$|$))',
            sent, re.IGNORECASE
        )
        via      = via_m.group(1).strip() if via_m else None
        return _build_system(
            type    = 'Trough',
            subtype = subtype,
            extent  = extent,
            across  = via,
            level   = parse_level(sent),
            raw_text= raw,
        )

    return _build_system(
        type    = 'Trough',
        subtype = subtype,
        extent  = extent,
        level   = parse_level(sent),
        raw_text= raw,
    )


# -----------------------------------------------------------------------------
# MAIN SENTENCE CLASSIFIER
# -----------------------------------------------------------------------------

def classify_sentence(sent, raw=None):
    """
    Classify a single normalised sentence into a system dict.
    Returns None if sentence should be skipped.
    Returns ('continuation', text) if it's a forecast continuation.
    """
    raw  = raw or sent
    s    = normalise_text(sent)
    slow = s.lower()

    # Check suppression first
    if is_suppressed(s):
        return None

    # Check continuation
    if is_continuation(s):
        return ('continuation', s)

    # Strip leading articles for subject matching
    subject = re.sub(r'^(?:The|An?|However,\s+the|Yesterday\'s)\s+', '', s, flags=re.IGNORECASE).lower().strip()

    # ── WESTERN DISTURBANCE ─────────────────────────────────────────────────
    if re.match(r'western\s+disturbance', subject, re.IGNORECASE):
        return classify_wd(s, raw)

    # ── UAC — both "upper air cyclonic circulation" and "cyclonic circulation" ─
    if re.match(r'(?:induced\s+)?(?:upper\s+air\s+)?cyclonic\s+circulation', subject, re.IGNORECASE):
        # Check if this is "associated cyclonic circulation" (child of LPA)
        if re.search(r'\bassociated\s+cyclonic', s, re.IGNORECASE):
            return ('associated_cc', s)
        return classify_uac(s, raw)

    # ── LPA / DEPRESSION / CYCLONE ───────────────────────────────────────────
    lpa_map = [
        (r'super\s+cyclonic\s+storm',              'Super Cyclonic Storm'),
        (r'extremely\s+severe\s+cyclonic\s+storm',  'Extremely Severe Cyclonic Storm'),
        (r'very\s+severe\s+cyclonic\s+storm',       'Very Severe Cyclonic Storm'),
        (r'severe\s+cyclonic\s+storm',              'Severe Cyclonic Storm'),
        (r'cyclonic\s+storm',                       'Cyclonic Storm'),
        (r'deep\s+depression',                      'Deep Depression'),
        (r'depression',                             'Depression'),
        (r'(?:well[\s\-]?marked\s+)?low[\s\-]?pressure\s+area', 'Low Pressure Area'),
    ]
    for pattern, stype in lpa_map:
        if re.match(pattern, subject, re.IGNORECASE):
            # Check if "has formed" inside "Under influence" sentence
            if re.search(r'^under\s+the?\s+influence', s, re.IGNORECASE):
                if re.search(r'has\s+formed', s, re.IGNORECASE):
                    # Extract embedded LPA
                    embed_m = re.search(
                        r'(?:well[\s\-]?marked\s+)?low[\s\-]?pressure\s+area\s+has\s+formed\s+over\s+(.+?)'
                        r'(?:\s+at\s+\d|\.$|$)',
                        s, re.IGNORECASE
                    )
                    if embed_m:
                        return _build_system(
                            type     = 'Low Pressure Area',
                            status   = 'forming',
                            location = embed_m.group(1).strip().rstrip(' ,'),
                            raw_text = raw,
                        )
                return None  # suppress "Under influence...is likely to form"
            return classify_lpa(s, raw, stype)

    # ── MONSOON / SEASONAL TROUGH ────────────────────────────────────────────
    if re.match(r'(?:monsoon|seasonal)\s+trough', subject, re.IGNORECASE):
        return classify_monsoon_trough(s, raw)
    # Also "Western end of monsoon trough"
    if re.search(r'(?:western|eastern)\s+end\s+of\s+(?:monsoon|seasonal)\s+trough', s, re.IGNORECASE):
        return classify_monsoon_trough(s, raw)

    # ── EAST-WEST TROUGH ─────────────────────────────────────────────────────
    if re.match(r'(?:east[\s\-]west)\s+trough', subject, re.IGNORECASE):
        return classify_ew_trough(s, raw)

    # ── NORTH-SOUTH TROUGH ───────────────────────────────────────────────────
    if re.match(r'(?:north[\s\-]south)\s+trough', subject, re.IGNORECASE):
        return classify_ns_trough(s, raw)

    # ── OFFSHORE TROUGH ──────────────────────────────────────────────────────
    if re.match(r'(?:offshore|off[\s\-]shore)\s+trough', subject, re.IGNORECASE):
        return classify_offshore_trough(s, raw)

    # ── SHEAR ZONE ───────────────────────────────────────────────────────────
    if re.match(r'shear\s+(?:zone|line)', subject, re.IGNORECASE):
        return classify_shear_zone(s, raw)

    # ── GENERIC TROUGH ───────────────────────────────────────────────────────
    if re.match(r'trough', subject, re.IGNORECASE):
        # Check if it's north-south
        if re.search(r'north.south|north\s+to\s+south', s, re.IGNORECASE):
            return classify_ns_trough(s, raw)
        return classify_generic_trough(s, raw)

    return None


# -----------------------------------------------------------------------------
# FULL MET ANALYSIS PARSER
# -----------------------------------------------------------------------------

def parse_met_analysis(meteo_text):
    """
    Parse the full Meteorological Analysis page text into structured systems.
    Returns dict with priority, uac, other_troughs, suppressed_count.
    """
    sentences = split_sentences(meteo_text)

    tier1_systems  = []
    tier2_uac      = []
    tier2_troughs  = []
    suppressed     = 0
    last_lpa       = None   # track last LPA/Depression for continuation attachment

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue

        # Skip "has become less marked" — suppressed systems
        if re.search(r'has\s+become\s+less\s+marked', sent, re.IGNORECASE):
            # But check for associated_cc pattern in NEXT sentence (handled below)
            suppressed += 1
            last_lpa = None  # reset — the LPA is gone
            continue

        result = classify_sentence(sent, raw=sent)

        if result is None:
            suppressed += 1
            continue

        # Continuation — attach forecast to last LPA/Depression/Cyclone
        if isinstance(result, tuple) and result[0] == 'continuation':
            if last_lpa is not None:
                existing = last_lpa.get('forecast', '')
                addition = re.sub(r'^It\s+is\s+(?:very\s+)?likely\s+to\s+|^Thereafter[,\s]+|^Subsequently\s+it\s+is\s+(?:very\s+)?likely\s+to\s+', '', result[1], flags=re.IGNORECASE).strip()
                last_lpa['forecast'] = (existing + ' ' + addition).strip() if existing else addition
            else:
                suppressed += 1
            continue

        # Associated CC — attach to last LPA
        if isinstance(result, tuple) and result[0] == 'associated_cc':
            if last_lpa is not None:
                last_lpa['associated_cc'] = _build_system(
                    location = extract_location(result[1]),
                    level    = parse_level(result[1]),
                )
            else:
                suppressed += 1
            continue

        # Normal system
        if isinstance(result, dict) and result.get('type'):
            stype = result['type']
            result = filter_system(result)

            if stype in SYSTEM_PRIORITY:
                tier1_systems.append(result)
                # Track last LPA/Depression/Cyclone for continuation
                if stype in ('Low Pressure Area', 'Depression', 'Deep Depression',
                             'Cyclonic Storm', 'Severe Cyclonic Storm',
                             'Very Severe Cyclonic Storm',
                             'Extremely Severe Cyclonic Storm',
                             'Super Cyclonic Storm'):
                    last_lpa = result
                else:
                    last_lpa = None
            elif stype == 'Upper Air Cyclonic Circulation':
                tier2_uac.append(result)
                last_lpa = None
            else:
                tier2_troughs.append(result)
                last_lpa = None

    # Sort Tier 1 by SYSTEM_PRIORITY
    tier1_systems.sort(key=lambda s: SYSTEM_PRIORITY.get(s.get('type', ''), 99))

    return {
        'priority':        tier1_systems,
        'uac':             tier2_uac,
        'other_troughs':   tier2_troughs,
        'suppressed_count': suppressed,
    }


# -----------------------------------------------------------------------------
# GITHUB HELPERS
# -----------------------------------------------------------------------------

def github_get_sha(path):
    url  = f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}'
    resp = requests.get(url, headers=HEADERS_GH, timeout=15)
    return resp.json().get('sha') if resp.status_code == 200 else None


def github_push_file(path, content_bytes, commit_message):
    url     = f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}'
    encoded = base64.b64encode(content_bytes).decode()
    sha     = github_get_sha(path)
    payload = {'message': commit_message, 'content': encoded, 'branch': GITHUB_BRANCH}
    if sha:
        payload['sha'] = sha
    resp = requests.put(url, headers=HEADERS_GH, json=payload, timeout=30)
    if resp.status_code in (200, 201):
        print(f'[GITHUB] ✅ Pushed: {path}')
        return True
    print(f'[GITHUB] ❌ Failed {path}: {resp.status_code} — {resp.text[:300]}')
    return False


def github_push_json(path, data, commit_message):
    content = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
    return github_push_file(path, content, commit_message)


# -----------------------------------------------------------------------------
# IMD FETCH HELPERS
# -----------------------------------------------------------------------------

def fetch_imd_pdf_url():
    try:
        resp = requests.get(IMD_BULLETIN_PAGE, headers=HEADERS_IMD, timeout=15)
        resp.raise_for_status()
        match = re.search(
            r'href=["\']\.\.\/backend\/assets\/aiwfb_pdf\/([a-f0-9]+\.pdf)["\']',
            resp.text
        )
        if match:
            pdf_url = f'https://mausam.imd.gov.in/backend/assets/aiwfb_pdf/{match.group(1)}'
            print(f'[IMD] Found PDF URL: {pdf_url}')
            return pdf_url
        print('[IMD] PDF link not found in page HTML')
        return None
    except Exception as e:
        print(f'[IMD] Error fetching bulletin page: {e}')
        return None


def download_pdf(pdf_url):
    try:
        resp = requests.get(pdf_url, headers=HEADERS_IMD, timeout=30, stream=True)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f'[IMD] Error downloading PDF: {e}')
        return None


# -----------------------------------------------------------------------------
# CORE PDF PARSER
# -----------------------------------------------------------------------------

def parse_monsoon_pdf(pdf_bytes, pdf_url):
    result = {
        'success':       True,
        'pdf_url':       pdf_url,
        'last_updated':  None,
        'slot':          None,
        'bulletin_date': None,
        'bulletin': {'morning': None, 'midday': None, 'evening': None, 'night': None},
        'nlm_coords':    None,
        'met_analysis':  None,
        'systems': {
            'priority':         [],
            'uac':              [],
            'other_troughs':    [],
            'suppressed_count': 0,
        },
        'mjo': None,
    }

    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            pages_text = [page.extract_text() or '' for page in pdf.pages]
        full_text = '\n'.join(pages_text)

        # ── STEP 1: Slot, timestamp, bulletin date from Page 1 ────────────
        page1 = pages_text[0] if pages_text else ''

        date_m = re.search(r'(20[0-9]{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01]))', page1)
        if date_m:
            result['bulletin_date'] = date_m.group(1)
        else:
            alt_m = re.search(r'(\d{2})-(\d{2})-(20[0-9]{2})', page1)
            result['bulletin_date'] = f'{alt_m.group(3)}-{alt_m.group(2)}-{alt_m.group(1)}' if alt_m else None
        print(f'[PARSE] Bulletin date: {result["bulletin_date"]}')

        time_m = re.search(r'Time\s+of\s+Issue:\s*(\d{2}:\d{2})', page1, re.IGNORECASE)
        if time_m:
            try:
                t_obj = datetime.strptime(time_m.group(1), '%H:%M')
                result['last_updated'] = t_obj.strftime('%I:%M %p') + ' IST'
            except Exception:
                result['last_updated'] = time_m.group(1) + ' IST'

        slot_m = re.search(r'\((Morning|Mid[\s\-]?[Dd]ay|Evening|Night)\)', page1, re.IGNORECASE)
        if slot_m:
            slot_raw = re.sub(r'mid[\s\-]?day', 'midday', slot_m.group(1).lower())
            result['slot'] = slot_raw

        # ── STEP 2: Find Meteorological Analysis page ─────────────────────
        meteo_text = next(
            (p for p in pages_text if 'meteorological analysis' in p.lower()), None
        )

        # ── STEP 3: Extract met_analysis full text ─────────────────────────
        if meteo_text:
            met_analysis = extract_met_analysis(meteo_text)
            if met_analysis:
                result['met_analysis'] = met_analysis
                print(f'[PARSE] met_analysis: {len(met_analysis.splitlines())} sentences')

        # ── STEP 4: Extract bulletin text ──────────────────────────────────
        bulletin_text = extract_monsoon_text(meteo_text or '') or extract_monsoon_text(full_text)
        if bulletin_text and result['slot']:
            result['bulletin'][result['slot']] = bulletin_text
        elif bulletin_text:
            result['bulletin']['morning'] = bulletin_text

        # ── STEP 5: NLM coordinates ────────────────────────────────────────
        coord_source   = bulletin_text or full_text
        result['nlm_coords'] = parse_nlm_coords(coord_source)

        # ── STEP 6: Parse systems ──────────────────────────────────────────
        # Use pre-processed met_analysis (multi-line sentences already joined)
        parse_source = result.get('met_analysis') or meteo_text
        if parse_source:
            systems = parse_met_analysis(parse_source)
            result['systems'] = systems
            print(f'[PARSE] Systems: {len(systems["priority"])} priority, '
                  f'{len(systems["uac"])} UAC, {len(systems["other_troughs"])} troughs, '
                  f'{systems["suppressed_count"]} suppressed')

    except Exception as e:
        import traceback
        traceback.print_exc()
        result['success'] = False
        result['error']   = str(e)

    return result


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main():
    print(f'[MAIN] Starting monsoon parser — {datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")}')

    if not GITHUB_TOKEN:
        print('[MAIN] ❌ GITHUB_TOKEN not set')
        sys.exit(1)

    pdf_url = fetch_imd_pdf_url()
    if not pdf_url:
        print('[MAIN] ❌ Could not find PDF URL')
        sys.exit(1)

    pdf_bytes = download_pdf(pdf_url)
    if not pdf_bytes:
        print('[MAIN] ❌ Could not download PDF')
        sys.exit(1)

    print(f'[MAIN] Downloaded PDF — {len(pdf_bytes):,} bytes')

    parsed = parse_monsoon_pdf(pdf_bytes, pdf_url)
    if not parsed['success']:
        print(f'[MAIN] ❌ Parse failed: {parsed.get("error")}')
        sys.exit(1)

    now_ist       = datetime.now(IST)
    slot          = parsed.get('slot') or 'unknown'
    bulletin_date = parsed.get('bulletin_date') or now_ist.strftime('%Y-%m-%d')
    timestamp     = now_ist.strftime('%Y-%m-%d %H:%M IST')
    parsed['fetched_at'] = timestamp

    commit_msg = f'Monsoon bulletin {bulletin_date} {slot} ({now_ist.strftime("%H:%M IST")})'

    github_push_json(f'weather_pdf/bulletins/{bulletin_date}_{slot}.json', parsed, commit_msg)
    github_push_file(f'weather_pdf/pdfs/{bulletin_date}_{slot}.pdf', pdf_bytes, commit_msg)
    github_push_json('weather_pdf/latest.json', parsed, f'Update latest.json — {timestamp}')

    print(f'[MAIN] ✅ Done — {timestamp}')


if __name__ == '__main__':
    main()
