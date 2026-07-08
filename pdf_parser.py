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
# SYSTEM PRIORITY
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
# SYSTEM FIELDS CONFIG
# -----------------------------------------------------------------------------

SYSTEM_FIELDS = {
    'Low Pressure Area': [
        'type', 'status', 'location', 'coords', 'distance_from',
        'on_land', 'movement', 'forecast', 'associated_cc', 'raw_text',
    ],
    'Depression': [
        'type', 'status', 'location', 'coords', 'distance_from',
        'on_land', 'movement', 'forecast', 'landfall', 'associated_cc', 'raw_text',
    ],
    'Deep Depression': [
        'type', 'status', 'location', 'coords', 'distance_from',
        'on_land', 'movement', 'forecast', 'landfall', 'associated_cc', 'raw_text',
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
        'type', 'position', 'extent', 'passes_through', 'west_end', 'east_end',
        'east_end_system', 'across', 'level', 'raw_text',
    ],
    'Shear Zone': [
        'type', 'form', 'location', 'extent', 'across', 'level', 'tilt', 'raw_text',
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
# TEXT NORMALISATION
# -----------------------------------------------------------------------------

MERGE_FIXES = [
    (r'\bextendingupto\b',              'extending upto'),
    (r'\bupto([\.\d]+)',                r'upto \1'),
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
    # NEW: merged words seen in real PDFs
    (r'\bneighbourhoodat\b',            'neighbourhood at'),
    (r'([A-Za-z]{3,})between\b',        r'\1 between'),
    (r'\bWest\s+Bengaland\b',           'West Bengal and'),
    (r'\bnorthOdisha\b',                'north Odisha'),
    (r'\bnorthChhattisgarh\b',          'north Chhattisgarh'),
    (r'\beastcentral\b',                'east-central'),
    # Grammar variants
    (r'\brun from\b',                   'runs from'),
    (r'\blay over\b',                   'lies over'),
    (r'\blay centered',                 'lies centered'),
    (r'\boff-shore\b',                  'offshore'),
    (r'\boff shore\b',                  'offshore'),
    (r'\bSeasonal trough\b',            'Monsoon trough'),
    (r'\bseasonal trough\b',            'monsoon trough'),
    (r'between\s+([\d.]+)\s*km\s+to\s+([\d.]+)\s*km', r'between \1 & \2 km'),
    # Collapse spaces
    (r' {2,}', ' '),
]

def normalise_text(text):
    """Apply all merge fixes and grammar normalisations."""
    if not text:
        return ''
    for pattern, repl in MERGE_FIXES:
        try:
            text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
        except Exception:
            pass
    return text.strip()


# -----------------------------------------------------------------------------
# LEVEL PARSER
# -----------------------------------------------------------------------------

def parse_level(text):
    if not text:
        return None
    try:
        t = normalise_text(text)

        m = re.search(r'now\s+seen\s+between\s+([\d.]+)\s*(?:&|and)\s*([\d.]+)\s*km\s*above', t, re.IGNORECASE)
        if m:
            lo, hi = float(m.group(1)), float(m.group(2))
            return {'type': 'range', 'min': lo, 'max': hi, 'display': f'{lo}–{hi} km above MSL'}

        m = re.search(r'now\s+seen\s+at\s+([\d.]+)\s*km\s*above', t, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            return {'type': 'single', 'min': val, 'display': f'{val} km above MSL'}

        m = re.search(r'between\s+([\d.]+)\s*(?:&|and)\s*([\d.]+)\s*km\s*above', t, re.IGNORECASE)
        if m:
            lo, hi = float(m.group(1)), float(m.group(2))
            return {'type': 'range', 'min': lo, 'max': hi, 'display': f'{lo}–{hi} km above MSL'}

        m = re.search(
            r'(?:and\s+)?(?:extending\s+|extends\s+)?upto\s+([\d.]+)\s*km\s*above',
            t, re.IGNORECASE
        )
        if m:
            val = float(m.group(1))
            return {'type': 'upto', 'max': val, 'display': f'upto {val} km above MSL'}

        m = re.search(
            r'(?:and\s+)?extends?\s+upto\s+(lower\s*(?:&|and)?\s*(?:middle|upper)?\s*tropospheric)',
            t, re.IGNORECASE
        )
        if m:
            label = re.sub(r'\s+', ' ', m.group(1)).strip().lower()
            return label

        m = re.search(r'at\s+([\d.]+)\s*km\s*above', t, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            return {'type': 'single', 'min': val, 'display': f'{val} km above MSL'}

        m = re.search(
            r'in\s+(lower\s*(?:&|and)?\s*(?:middle\s*)?(?:&|and)?\s*(?:upper\s*)?tropospheric)\s*levels?',
            t, re.IGNORECASE
        )
        if m:
            label = re.sub(r'\s+', ' ', m.group(1)).strip().lower()
            label = re.sub(r'\s*(and|&)\s*', ' & ', label)
            return label

        if re.search(r'at\s+mean\s+sea\s+level|mean\s+sea\s+level', t, re.IGNORECASE):
            return 'mean sea level'

    except Exception:
        pass
    return None


# -----------------------------------------------------------------------------
# TILT EXTRACTOR
# -----------------------------------------------------------------------------

def extract_tilt(text):
    try:
        m = re.search(
            r'tilting\s+(south\w*|north\w*|east\w*|west\w*)\s+with\s+height',
            text, re.IGNORECASE
        )
        return m.group(0).strip() if m else None
    except Exception:
        return None


# -----------------------------------------------------------------------------
# LOCATION EXTRACTOR
# -----------------------------------------------------------------------------

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
    if not loc:
        return None
    try:
        loc = loc.strip().rstrip(' ,&')
        loc = re.split(r'\s+(?:at\s+[\d.]|between\s+[\d.]|extending|upto|in\s+lower|in\s+middle|in\s+upper|tilting)', loc, flags=re.IGNORECASE)[0]
        loc = loc.strip().rstrip(' ,&')
        return loc if loc else None
    except Exception:
        return None


def extract_location(text):
    try:
        t = normalise_text(text)

        m = re.search(
            r'now\s+lies\s+(?:centered\s+)?over\s+(.+?)(?=' + _LOC_STOP + r')',
            t, re.IGNORECASE
        )
        if m:
            return _clean_loc(m.group(1))

        m = re.search(
            r'lies\s+centered\s+.{0,40}?over\s+(.+?)(?=' + _LOC_STOP + r')',
            t, re.IGNORECASE
        )
        if m:
            return _clean_loc(m.group(1))

        m = re.search(
            r'lies\s+over\s+(.+?)(?=' + _LOC_STOP + r')',
            t, re.IGNORECASE
        )
        if m:
            return _clean_loc(m.group(1))

        m = re.search(
            r'\bover\s+(.+?)(?=' + _LOC_STOP + r')',
            t, re.IGNORECASE
        )
        if m:
            return _clean_loc(m.group(1))

    except Exception:
        pass
    return None


# -----------------------------------------------------------------------------
# COORDINATE PARSER
# -----------------------------------------------------------------------------

def parse_coords(text):
    if not text:
        return None
    try:
        lat_m = re.search(r'[Ll]at(?:itude)?\.?\s*([\d.]+)°?\s*N', text)
        lon_m = re.search(r'[Ll]on(?:g(?:itude)?)?\.?\s*([\d.]+)°?\s*E', text)
        if lat_m and lon_m:
            return {'lat': float(lat_m.group(1)), 'lon': float(lon_m.group(1))}
        slash_m = re.search(r'([\d.]+)°?\s*N\s*/\s*([\d.]+)°?\s*E', text)
        if slash_m:
            return {'lat': float(slash_m.group(1)), 'lon': float(slash_m.group(2))}
    except Exception:
        pass
    return None


def parse_nlm_coords(text):
    try:
        coords  = []
        matches = re.findall(r'([\d.]+)°?\s*N\s*/\s*([\d.]+)°?\s*E', text)
        for lat_s, lon_s in matches:
            coords.append({'lat': float(lat_s), 'lon': float(lon_s)})
        return coords if coords else None
    except Exception:
        return None


# -----------------------------------------------------------------------------
# DISTANCE FROM PARSER
# -----------------------------------------------------------------------------

def parse_distance_from(text):
    try:
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
    except Exception:
        return None


# -----------------------------------------------------------------------------
# SENTENCE SPLITTER
# -----------------------------------------------------------------------------

_CONTINUATION_PATTERNS = [
    r'^It\s+is\s+(?:very\s+)?likely\s+to\s+move',
    r'^It\s+is\s+(?:very\s+)?likely\s+to\s+',
    r'^Thereafter[,\s]',
    r'^Subsequently\s+it\s+is',
]

_SUPPRESS_PATTERNS = [
    r'Under\s+(?:its|the)\s+influence\s+.{0,60}is\s+likely\s+to\s+form',
    r'Under\s+the\s+influence\s+of\s+these\s+systems',
    r'likely\s+to\s+affect\s+(?:northwest|northeast|north|south|west|east)?\s*india',
    r'A\s+fresh\s+[Ww]estern\s+[Dd]isturbance',
    r'has\s+moved\s+away\s+(?:north|south|east|west)',
]

RUN_FIXES = [
    (r'TheWesternDisturbance', 'The Western Disturbance'),
    (r'Theupperair\b', 'The upper air'),
    (r'Theupperaircycloniccirculationovercentral([A-Za-z])', r'The upper air cyclonic circulation over central \1'),
    (r'TheupperaircycloniccirculationoverSoutheast', 'The upper air cyclonic circulation over Southeast'),
    (r'TheupperaircycloniccirculationoverEastcentral', 'The upper air cyclonic circulation over East-central'),
    (r'Theupperaircycloniccirculationover([A-Z])', r'The upper air cyclonic circulation over \1'),
    (r'Theupperair cycloniccirculationover', 'The upper air cyclonic circulation over'),
    (r'cycloniccirculationover([A-Z])', r'cyclonic circulation over \1'),
    (r'\bSoutheastArabian\b', 'Southeast Arabian'),
    (r'\bArabianSea\b', 'Arabian Sea'),
    (r'([a-z])([A-Z][a-z]{3,})', r'\1 \2'),
    (r' {2,}', ' '),
]

_FOOTER_RE = re.compile(r'^\*\s*Red\s+colo(?:u|u?)r?\s+warning', re.IGNORECASE)

_SYSTEM_START_RE = re.compile(
    r'^(?:The|An?|A)\s+(?:fresh\s+)?(?:'
    r'(?:upper\s+air\s+)?cyclonic\s+circulation'
    r'|induced\s+(?:upper\s+air\s+)?cyclonic'
    r'|Western\s+Disturbance'
    r'|(?:well[\s\-]?marked\s+)?[Ll]ow[\s\-]?[Pp]ressure\s+[Aa]rea'
    r'|[Dd]eep\s+[Dd]epression'
    r'|[Dd]epression'
    r'|(?:very\s+severe|extremely\s+severe|severe|super)\s+cyclonic\s+storm'
    r'|[Cc]yclonic\s+[Ss]torm'
    r'|(?:monsoon|seasonal)\s+trough'
    r'|(?:east[\s\-]west|north[\s\-]south)\s+trough'
    r'|(?:offshore|off[\s\-]shore)\s+trough'
    r'|shear\s+(?:zone|line)'
    r'|trough'
    r')'
    r'|^(?:The|A)\s+(?:western\s+end|eastern\s+end)\s+of\s+(?:monsoon|seasonal)\s+trough'
    r'|^Yesterday\'s\s+(?:depression|low\s+pressure)'
    r'|^However,\s+the\s+associated\s+cyclonic',
    re.IGNORECASE
)

_SKIP_LINE_RE = re.compile(
    r'^Meteorological\s+Analysis'
    r'|^Conditions\s+are\s+favourable'
    r'|^The\s+Northern\s+Limit\s+of\s+Monsoon'
    r'|^The\s+Southwest\s+Monsoon\s+has'
    r'|^Page\s+\d+'
    r'|\(Service\s+to\s+the\s+nation'
    r'|^\d{4}-\d{2}-\d{2}$'
    r'|^For\s+more\s+details'
    r'|^Forecast\s+and\s+[Ww]arning\s+for',
    re.IGNORECASE
)


def _apply_run_fixes(text):
    for pattern, repl in RUN_FIXES:
        try:
            text = re.sub(pattern, repl, text)
        except Exception:
            pass
    return normalise_text(text)


def extract_met_sentences(page_text):
    """Extract system sentences from Met Analysis page."""
    if not page_text:
        return []
    lines = []
    for raw in page_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _FOOTER_RE.match(line):
            break
        line = re.sub(r'^[❖•✦◆\-]\s*', '', line)
        line = line.strip()
        if not line:
            continue
        if _SKIP_LINE_RE.match(line):
            continue
        lines.append(line)

    sentences = []
    current = ''
    for line in lines:
        if _SYSTEM_START_RE.match(line):
            if current:
                sentences.append(current.strip())
            current = line
        else:
            if current:
                current = current + ' ' + line

    if current:
        sentences.append(current.strip())

    return [_apply_run_fixes(s) for s in sentences if s.strip()]


def is_continuation(sentence):
    s = sentence.strip()
    return any(re.match(p, s, re.IGNORECASE) for p in _CONTINUATION_PATTERNS)


def is_suppressed(sentence):
    s = sentence.strip()
    return any(re.search(p, s, re.IGNORECASE) for p in _SUPPRESS_PATTERNS)


def split_sentences(text):
    if not text:
        return []
    text = normalise_text(text)
    raw = [s.strip() for s in text.splitlines() if s.strip()]

    expanded = []
    for sent in raw:
        try:
            parts = re.split(r'\s+and\s+another\s+over\s+', sent, flags=re.IGNORECASE)
            if len(parts) == 2:
                level_m = re.search(
                    r'(?:at\s+[\d.]|between\s+[\d.]|extending\s+upto|in\s+\w+\s+tropospheric).*$',
                    parts[1], re.IGNORECASE
                )
                level_text = level_m.group(0) if level_m else ''
                expanded.append(parts[0].rstrip(' ,') + (' ' + level_text if level_text and level_text not in parts[0] else ''))
                prefix_m = re.match(r'^(An?\s+(?:upper\s+air\s+)?cyclonic\s+circulation\s+\w+)', parts[0], re.IGNORECASE)
                prefix = prefix_m.group(1) if prefix_m else 'An upper air cyclonic circulation lies'
                expanded.append(f'{prefix} over {parts[1]}')
            else:
                expanded.append(sent)
        except Exception:
            expanded.append(sent)
    return expanded


# -----------------------------------------------------------------------------
# MONSOON TEXT EXTRACTORS
# -----------------------------------------------------------------------------

def extract_monsoon_advance(page_text):
    """Extract 'SW Monsoon has further advanced into...' sentence."""
    if not page_text:
        return None
    try:
        clean = ' '.join(page_text.splitlines())
        clean = re.sub(r'[❖•✦◆\-]\s*', ' ', clean)
        clean = re.sub(r'\s{2,}', ' ', clean).strip()
        m = re.search(
            r'(?:The\s+)?Southwest\s+Monsoon\s+has\s+(?:further\s+)?advanced\s+.+?'
            r'(?=\.\s+(?:The\s+Northern|Conditions)|\.?\s*$)',
            clean, re.IGNORECASE | re.DOTALL
        )
        if m:
            return m.group(0).strip().rstrip('.') + '.'
    except Exception:
        pass
    return None


def extract_monsoon_text(page_text):
    """Extract NLM + Conditions text from a page."""
    if not page_text:
        return None
    try:
        clean_lines = []
        for raw in page_text.splitlines():
            line = raw.strip()
            if _FOOTER_RE.match(line):
                break
            clean_lines.append(line)

        text = ' '.join(clean_lines)
        text = re.sub(r'[❖•✦◆\-]\s*', ' ', text)
        text = re.sub(r'\s{2,}', ' ', text).strip()

        # NLM regex — stop at sentence boundary but NOT at "Dist." abbreviation
        nlm_re = re.compile(
            r'(?:The\s+)?Northern\s+Limit\s+of\s+Monsoon\s+.+?'
            r'(?=\.\s+(?:Conditions|The\s+(?:Southwest|Well|depression|monsoon|shear|off|Western|seasonal))|\.?\s*$)',
            re.IGNORECASE | re.DOTALL
        )
        cond_re = re.compile(
            r'Conditions?\s+are\s+favourable\s+.+?'
            r'(?=\.\s+(?:The\s+|$)|\.?\s*$)',
            re.IGNORECASE | re.DOTALL
        )

        parts = []
        m = nlm_re.search(text)
        if m:
            parts.append(m.group(0).strip().rstrip('.') + '.')
        m = cond_re.search(text)
        if m:
            parts.append(m.group(0).strip().rstrip('.') + '.')

        return ' '.join(parts) if parts else None
    except Exception:
        return None


def extract_met_analysis(page_text):
    sentences = extract_met_sentences(page_text)
    return '\n'.join(sentences) if sentences else None


# -----------------------------------------------------------------------------
# SYSTEM CLASSIFIERS
# -----------------------------------------------------------------------------

def _build_system(**kwargs):
    return {k: v for k, v in kwargs.items() if v is not None}


def filter_system(system):
    stype   = system.get('type', '')
    allowed = SYSTEM_FIELDS.get(stype, list(system.keys()))
    return {k: v for k, v in system.items() if k in allowed and v is not None}


def classify_uac(sent, raw):
    try:
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
    except Exception:
        return _build_system(type='Upper Air Cyclonic Circulation', raw_text=raw)


def classify_wd(sent, raw):
    try:
        system = {'type': 'Western Disturbance', 'raw_text': raw}

        if re.search(r'as\s+(?:a\s+)?(?:an?\s+)?(?:upper\s+air\s+)?cyclonic\s+circulation|seen\s+as\s+(?:a\s+)?cyclonic', sent, re.IGNORECASE):
            system['form'] = 'cyclonic_circulation'
            loc = extract_location(sent)
            if not loc:
                cc_loc_m = re.search(
                    r'as\s+(?:a\s+)?(?:an?\s+)?(?:upper\s+air\s+)?cyclonic\s+circulation\s+(?:over\s+)?(.+?)'
                    r'(?=\s+(?:at\s+[\d.]|between\s+[\d.]|extending|persists|with\s+a\s+trough|\.$|$))',
                    sent, re.IGNORECASE
                )
                if cc_loc_m:
                    loc = cc_loc_m.group(1).strip().rstrip(' ,')
            system['location'] = loc
            system['level']    = parse_level(sent)

            aloft_m = re.search(
                r'trough\s+aloft.+?(?:roughly\s+)?(?:along)\s+(.+?)(?:\.|$)',
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
                r'(?:now\s+)?runs?\s+(?:roughly\s+)?along\s+(.+?)(?:\s+persists|\s+and\s+|\s+has\s+moved|\.$|$)',
                sent, re.IGNORECASE
            )
            if not loc_m:
                loc_m = re.search(
                    r'(?:roughly\s+)?along\s+(.+?)(?:\s+persists|\s+and\s+|\s+has\s+moved|\.$|$)',
                    sent, re.IGNORECASE
                )
            if loc_m:
                loc_str = loc_m.group(1).strip().rstrip(' ,')
                loc_str = re.split(r'\s+at\s+[\d.]|\s+between\s+[\d.]', loc_str)[0].strip()
                system['axis'] = 'along ' + loc_str
            system['level'] = parse_level(sent)

        return {k: v for k, v in system.items() if v is not None}
    except Exception:
        return _build_system(type='Western Disturbance', raw_text=raw)


def classify_lpa(sent, raw, stype='Low Pressure Area'):
    """Classify LPA / Depression / Cyclone variants.
    
    Handles the case where a Depression sentence says it weakened into an LPA —
    in that case we reclassify the output as Low Pressure Area with the current
    location and inline associated_cc details.
    """
    try:
        s = normalise_text(sent)

        # ── KEY FIX: Depression weakened into LPA → output as LPA ──────────
        weaken_into_m = re.search(
            r'weakened\s+into\s+(?:a\s+)?(?:well[\s\-]?marked\s+)?low[\s\-]?pressure\s+area\s+'
            r'over\s+(.+?)(?:\s+at\s+\d|\s+at\s+0|(?<![Dd]ist)\.\s|\.$|$)',
            s, re.IGNORECASE
        )
        if weaken_into_m and stype in ('Depression', 'Deep Depression'):
            # Try to capture "and neighbourhood" if present
            full_m = re.search(
                r'weakened\s+into\s+(?:a\s+)?(?:well[\s\-]?marked\s+)?low[\s\-]?pressure\s+area\s+'
                r'over\s+(.+?and\s+neighbourhood)',
                s, re.IGNORECASE
            )
            loc_raw = full_m.group(1).strip() if full_m else weaken_into_m.group(1).strip().rstrip(' ,')

            sys = _build_system(
                type     = 'Low Pressure Area',
                status   = 'weakened_from_depression',
                location = loc_raw,
                on_land  = True,
                raw_text = raw,
            )
            # Inline associated_cc (level + tilt)
            cc_m = re.search(
                r'associated\s+cyclonic\s+circulation\s+extends\s+upto\s+([\d.]+)\s*km\s*above',
                s, re.IGNORECASE
            )
            if cc_m:
                cc = {'level': {'type': 'upto', 'max': float(cc_m.group(1)),
                                'display': f'upto {cc_m.group(1)} km above MSL'}}
                tilt_m = re.search(r'tilting\s+(\w+wards?)\s+with\s+height', s, re.IGNORECASE)
                if tilt_m:
                    cc['tilt'] = f'tilting {tilt_m.group(1)} with height'
                sys['associated_cc'] = cc
            # Forecast
            fc_m = re.search(r'It\s+is\s+(?:very\s+)?likely\s+to\s+(.+?)(?:\.|$)', s, re.IGNORECASE)
            if fc_m:
                sys['forecast'] = 'likely to ' + fc_m.group(1).strip()
            return sys

        # ── Normal classification ────────────────────────────────────────────
        if re.search(r'has\s+concentrated\s+into|has\s+formed', s, re.IGNORECASE):
            status = 'forming'
        elif re.search(r'has\s+become\s+less\s+marked', s, re.IGNORECASE):
            status = 'less_marked'
        elif re.search(r'weaken\s+(?:gradually|further|during)', s, re.IGNORECASE):
            status = 'weakening'
        elif re.search(r'weakened\s+into', s, re.IGNORECASE):
            status = 'weakening'
        else:
            status = 'active'

        loc    = extract_location(s)
        coords = parse_coords(s)
        dist   = parse_distance_from(s)

        on_land = True if (not coords and not dist and loc and
                           not re.search(r'bay\s+of\s+bengal|arabian\s+sea|sea\s+of|ocean|coast\s+off',
                                         loc, re.IGNORECASE)) else False

        mov_m = re.search(
            r'(?:moved?|moving)\s+([\w\-]+wards?(?:\s+and\s+[\w\-]+wards?)?)',
            s, re.IGNORECASE
        )
        movement = mov_m.group(1).strip() if mov_m else None

        landfall = None
        if stype not in ('Low Pressure Area', 'Well Marked Low Pressure Area'):
            lf_m = re.search(
                r'cross\s+(?:the\s+)?(.+?coast.+?)\s+(?:as\s+a\s+([\w\s]+?))?\s+(?:during|by|on)\s+(.+?)(?:\.|$)',
                s, re.IGNORECASE
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
    except Exception:
        return _build_system(type=stype, raw_text=raw)


def classify_monsoon_trough(sent, raw):
    try:
        system = {'type': 'Monsoon Trough', 'raw_text': raw}

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

        if re.search(r'western\s+end|eastern\s+end', sent, re.IGNORECASE):
            west_end = {}
            east_end = {}
            wp = re.search(
                r'[Ww]estern\s+end\s+(?:of\s+monsoon\s+trough\s+)?(?:runs?|lies?)\s+(.+?)'
                r'(?:\s+and\s+eastern|\s+at\s+mean|\.$|$)',
                sent, re.IGNORECASE
            )
            if wp:
                wp_text = wp.group(1).strip().rstrip(' ,')
                if re.search(r'normal|foothills', wp_text, re.IGNORECASE):
                    west_end['position'] = _normalise_position(wp_text)
                else:
                    cities = _split_city_list(wp_text)
                    if cities: west_end['passes_through'] = cities
            wp_cities_m = re.search(
                r'[Ww]estern\s+end.+?(?:passes|pass)\s+through\s+(.+?)'
                r'(?:\s+and\s+eastern|\s+and\s+thence|\s+at\s+mean|\.$|$)',
                sent, re.IGNORECASE
            )
            if wp_cities_m:
                cities = _split_city_list(wp_cities_m.group(1))
                if cities: west_end['passes_through'] = cities
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

        elif re.search(r'(?:passes|pass|continues?)\s+(?:to\s+pass\s+)?through', sent, re.IGNORECASE):
            cities_m = re.search(
                r'(?:passes|pass|continues?)\s+(?:to\s+pass\s+)?through\s+(.+?)'
                r'(?=\s+(?:extending|extends|upto\s+[\d.]|at\s+[\d.]|between\s+[\d.]|\.$|$)|$)',
                sent, re.IGNORECASE
            )
            if cities_m:
                raw_cities = cities_m.group(1)
                thence_m = re.search(
                    r'(?:and\s+)?thence\s+[\w\-]+wards?\s+to\s+(.+?)$',
                    raw_cities, re.IGNORECASE
                )
                terminus = None
                if thence_m:
                    terminus = thence_m.group(1).strip().rstrip(' ,.')
                    terminus = re.sub(r'\s+and\s*$', '', terminus, flags=re.IGNORECASE).strip()
                    terminus = re.sub(r'^the\s+', '', terminus, flags=re.IGNORECASE).strip()
                    raw_cities = raw_cities[:thence_m.start()].strip()
                cities = _split_city_list(raw_cities)
                if terminus:
                    cities.append(terminus)
                if cities:
                    system['passes_through'] = cities

        elif re.search(r'\bto\b.+?\bacross\b|\bfrom\b.+?\bto\b|(?:now\s+)?runs\b', sent, re.IGNORECASE):
            extent_m = re.search(
                r'from\s+(.+?)\s+to\s+(.+?)'
                r'(?=\s+(?:across|at\s+[\d.]|between\s+[\d.]|extending|persists|\.$|$))',
                sent, re.IGNORECASE
            )
            if not extent_m:
                extent_m = re.search(
                    r'(?:now\s+)?runs\s+(.+?)\s+to\s+(.+?)'
                    r'(?=\s+(?:across|at\s+[\d.]|between\s+[\d.]|extending|persists|\.$|$))',
                    sent, re.IGNORECASE
                )
            if extent_m:
                w = extent_m.group(1).strip().rstrip(' ,')
                e = extent_m.group(2).strip().rstrip(' ,')
                system['extent'] = f'{w} to {e}'
            across_m = re.search(
                r'\bacross\s+(.+?)(?=\s+(?:at\s+[\d.]|between\s+[\d.]|extending|persists|\.$|$))',
                sent, re.IGNORECASE
            )
            if across_m:
                system['across'] = across_m.group(1).strip().rstrip(' ,')

        system['level'] = parse_level(sent)
        return {k: v for k, v in system.items() if v is not None}
    except Exception:
        return _build_system(type='Monsoon Trough', raw_text=raw)


def _normalise_position(text):
    t = text.lower().strip()
    if 'foothills' in t: return 'foothills of Himalayas'
    if 'south' in t and 'normal' in t: return 'south of normal'
    if 'north' in t and 'normal' in t: return 'north of normal'
    if 'near' in t and 'normal' in t: return 'near normal'
    if 'normal' in t: return 'normal'
    return text.strip()


def _split_city_list(text):
    if not text:
        return []
    try:
        text = re.sub(r'\s+and\s*$', '', text.strip())
        text = text.strip().rstrip(' ,.')
        raw_items = re.split(r',\s*', text)
        items = []
        current = ''
        for item in raw_items:
            item = item.strip()
            if not item:
                continue
            if current:
                current = current + ', ' + item
                if not re.search(r'^(?:and\s+)?adjoining|^&', item, re.IGNORECASE):
                    items.append(current.strip())
                    current = ''
            elif re.search(r'^center\s+of|^(?:the\s+)?(?:well\s+marked\s+)?low\s+pressure|^(?:the\s+)?(?:upper\s+air\s+)?cyclonic\s+circulation', item, re.IGNORECASE):
                current = item
            else:
                items.append(item)
        if current:
            items.append(current.strip())
        return [i for i in items if i]
    except Exception:
        return []


def classify_shear_zone(sent, raw):
    """Classify Shear Zone — handles both standard and 'now seen as a trough' variants."""
    try:
        s = normalise_text(sent)

        # ── KEY FIX: "shear zone now seen as a trough from X to Y across Z between L1 & L2" ──
        if re.search(r'now\s+seen\s+as\s+a\s+trough', s, re.IGNORECASE):
            extent_m = re.search(
                r'(?:now\s+seen\s+as\s+a\s+trough\s+)?from\s+(.+?)\s+to\s+(.+?)'
                r'(?=\s+(?:across|between\s+[\d.]|at\s+[\d.]|extending|\.$|$))',
                s, re.IGNORECASE
            )
            across_m = re.search(
                r'\bacross\s+(.+?)(?=\s+(?:between\s+[\d.]|at\s+[\d.]|extending|persists|\.$|$))',
                s, re.IGNORECASE
            )
            return _build_system(
                type    = 'Shear Zone',
                form    = 'trough',
                extent  = f'{extent_m.group(1).strip()} to {extent_m.group(2).strip()}' if extent_m else None,
                across  = across_m.group(1).strip() if across_m else None,
                level   = parse_level(s),
                tilt    = extract_tilt(s),
                raw_text= raw,
            )

        # ── Standard shear zone ──────────────────────────────────────────────
        lat_m = re.search(
            r'(?:roughly\s+)?along\s+(?:Lat(?:itude)?\.?\s*)?([\.\d]+°?\s*N)',
            s, re.IGNORECASE
        )
        lat_line = lat_m.group(1).strip() if lat_m else None

        over_m = re.search(
            r'\bover\s+(.+?)(?=\s+(?:at\s+[\d.]|between\s+[\d.]|extending|persists|roughly|across|\.$))',
            s, re.IGNORECASE
        )
        over_loc = _clean_loc(over_m.group(1)) if over_m else None

        if lat_line and over_loc:
            location = f'roughly along {lat_line} over {over_loc}'
        elif lat_line:
            location = f'roughly along {lat_line}'
        elif over_loc:
            location = over_loc
        else:
            location = None

        across_m = re.search(
            r'across\s+(.+?)(?=\s+(?:at\s+[\d.]|between\s+[\d.]|extending|persists|\.$))',
            s, re.IGNORECASE
        )

        return _build_system(
            type     = 'Shear Zone',
            location = location,
            across   = across_m.group(1).strip() if across_m else None,
            level    = parse_level(s),
            tilt     = extract_tilt(s),
            raw_text = raw,
        )
    except Exception:
        return _build_system(type='Shear Zone', raw_text=raw)


def classify_offshore_trough(sent, raw):
    """Classify Offshore Trough — handles 'from X to Y', 'now runs from X to Y', 'along X'."""
    try:
        s = normalise_text(sent)
        extent = None

        # PRIMARY: "from X to Y" or "now runs from X to Y"
        m = re.search(
            r'from\s+(.+?)\s+to\s+(.+?)(?:\s+persists|\s+at\s+[\d.]|\s+extending|\.?\s*$)',
            s, re.IGNORECASE
        )
        if m:
            extent = f'{m.group(1).strip().rstrip(",")} to {m.group(2).strip().rstrip(",. ")}'

        # FALLBACK: "along X"
        if not extent:
            m = re.search(
                r'along\s+(.+?)(?:\s+persists|\s+at\s+[\d.]|\s+extending|\.?\s*$)',
                s, re.IGNORECASE
            )
            if m:
                extent = m.group(1).strip().rstrip(' ,')

        return _build_system(
            type     = 'Offshore Trough',
            extent   = extent,
            level    = parse_level(s),
            raw_text = raw,
        )
    except Exception:
        return _build_system(type='Offshore Trough', raw_text=raw)


def classify_ew_trough(sent, raw):
    try:
        lat_m = re.search(r'(?:roughly\s+)?along\s+Lat\.?\s*([\.\d]+°?\s*N)', sent, re.IGNORECASE)
        lat_label = lat_m.group(1).strip() if lat_m else None

        extent_m = re.search(
            r'from\s+(.+?)\s+to\s+(.+?)(?=\s+(?:at\s+[\d.]|between\s+[\d.]|extending|across|persists|\.$|$))',
            sent, re.IGNORECASE
        )
        if extent_m:
            w = extent_m.group(1).strip()
            e = extent_m.group(2).strip()
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
    except Exception:
        return _build_system(type='East-West Trough', raw_text=raw)


def classify_ns_trough(sent, raw):
    try:
        extent_m = re.search(
            r'from\s+(.+?)\s+to\s+(.+?)(?=\s+(?:across|at\s+[\d.]|extending|persists|\.$|$))',
            sent, re.IGNORECASE
        )
        via_m = re.search(
            r'across\s+(.+?)(?=\s+(?:at\s+[\d.]|between\s+[\d.]|extending|persists|\.$|$))',
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
    except Exception:
        return _build_system(type='North-South Trough', raw_text=raw)


def _clean_extent(extent):
    if not extent:
        return None
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
    try:
        if re.search(r'westerlies|along\s+long\.', sent, re.IGNORECASE):
            subtype = 'westerlies'
            loc_m   = re.search(
                r'(?:roughly\s+)?along\s+(.+?)(?=\s+(?:at\s+[\d.]|extending|persists|\.$|$))',
                sent, re.IGNORECASE
            )
            extent  = f"along {loc_m.group(1).strip()}" if loc_m else None
            return _build_system(
                type    = 'Trough',
                subtype = subtype,
                extent  = extent,
                level   = parse_level(sent),
                raw_text= raw,
            )
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
                r'across\s+(.+?)(?=\s+(?:at\s+[\d.]|between\s+[\d.]|extending|persists|\.$|$))',
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
    except Exception:
        return _build_system(type='Trough', raw_text=raw)


# -----------------------------------------------------------------------------
# MAIN SENTENCE CLASSIFIER
# -----------------------------------------------------------------------------

def classify_sentence(sent, raw=None):
    raw  = raw or sent
    try:
        s    = normalise_text(sent)
        if not s:
            return None

        if is_suppressed(s):
            return None

        if is_continuation(s):
            return ('continuation', s)

        subject = re.sub(r'^(?:The|An?|However,\s+the|Yesterday\'s)\s+', '', s, flags=re.IGNORECASE).lower().strip()

        if re.match(r'western\s+disturbance', subject, re.IGNORECASE):
            return classify_wd(s, raw)

        if re.match(r'(?:induced\s+)?(?:upper\s+air\s+)?cyclonic\s+circulation', subject, re.IGNORECASE):
            if re.search(r'\bassociated\s+cyclonic', s, re.IGNORECASE):
                return ('associated_cc', s)
            return classify_uac(s, raw)

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
                if re.search(r'^under\s+the?\s+influence', s, re.IGNORECASE):
                    if re.search(r'has\s+formed', s, re.IGNORECASE):
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
                    return None
                return classify_lpa(s, raw, stype)

        if re.match(r'(?:monsoon|seasonal)\s+trough', subject, re.IGNORECASE):
            return classify_monsoon_trough(s, raw)
        if re.search(r'(?:western|eastern)\s+end\s+of\s+(?:monsoon|seasonal)\s+trough', s, re.IGNORECASE):
            return classify_monsoon_trough(s, raw)

        if re.match(r'(?:east[\s\-]west)\s+trough', subject, re.IGNORECASE):
            return classify_ew_trough(s, raw)

        if re.match(r'(?:north[\s\-]south)\s+trough', subject, re.IGNORECASE):
            return classify_ns_trough(s, raw)

        if re.match(r'(?:offshore|off[\s\-]shore)\s+trough', subject, re.IGNORECASE):
            return classify_offshore_trough(s, raw)

        if re.match(r'shear\s+(?:zone|line)', subject, re.IGNORECASE):
            return classify_shear_zone(s, raw)

        if re.match(r'trough', subject, re.IGNORECASE):
            if re.search(r'north.south|north\s+to\s+south', s, re.IGNORECASE):
                return classify_ns_trough(s, raw)
            return classify_generic_trough(s, raw)

    except Exception:
        pass
    return None


# -----------------------------------------------------------------------------
# FULL MET ANALYSIS PARSER
# -----------------------------------------------------------------------------

def parse_met_analysis(meteo_text):
    if not meteo_text:
        return {'priority': [], 'uac': [], 'other_troughs': [], 'suppressed_count': 0}

    sentences = split_sentences(meteo_text)

    tier1_systems  = []
    tier2_uac      = []
    tier2_troughs  = []
    suppressed     = 0
    last_lpa       = None

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue

        try:
            if re.search(r'has\s+become\s+less\s+marked', sent, re.IGNORECASE):
                suppressed += 1
                last_lpa = None
                continue

            result = classify_sentence(sent, raw=sent)

            if result is None:
                suppressed += 1
                continue

            if isinstance(result, tuple) and result[0] == 'continuation':
                if last_lpa is not None:
                    existing = last_lpa.get('forecast', '')
                    addition = re.sub(
                        r'^It\s+is\s+(?:very\s+)?likely\s+to\s+|^Thereafter[,\s]+|^Subsequently\s+it\s+is\s+(?:very\s+)?likely\s+to\s+',
                        '', result[1], flags=re.IGNORECASE
                    ).strip()
                    last_lpa['forecast'] = (existing + ' ' + addition).strip() if existing else addition
                else:
                    suppressed += 1
                continue

            if isinstance(result, tuple) and result[0] == 'associated_cc':
                if last_lpa is not None:
                    last_lpa['associated_cc'] = _build_system(
                        location = extract_location(result[1]),
                        level    = parse_level(result[1]),
                    )
                else:
                    suppressed += 1
                continue

            if isinstance(result, dict) and result.get('type'):
                stype = result['type']
                result = filter_system(result)

                if stype in SYSTEM_PRIORITY:
                    tier1_systems.append(result)
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

        except Exception:
            suppressed += 1
            continue

    tier1_systems.sort(key=lambda s: SYSTEM_PRIORITY.get(s.get('type', ''), 99))

    return {
        'priority':        tier1_systems,
        'uac':             tier2_uac,
        'other_troughs':   tier2_troughs,
        'suppressed_count': suppressed,
    }


# -----------------------------------------------------------------------------
# CORE PDF PARSER
# -----------------------------------------------------------------------------

def parse_monsoon_pdf(pdf_bytes, pdf_url):
    result = {
        'success':          True,
        'pdf_url':          pdf_url,
        'last_updated':     None,
        'slot':             None,
        'bulletin_date':    None,
        'monsoon_advance':  None,
        'bulletin': {'morning': None, 'midday': None, 'evening': None, 'night': None},
        'nlm_coords':       None,
        'met_analysis':     None,
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

        # ── STEP 1: Slot, timestamp, bulletin date ────────────────────────
        page1 = pages_text[0] if pages_text else ''

        _MONTHS = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
            'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
        }

        date_m = re.search(r'\b(20\d{2})-(\d{2})-(\d{2})\b', page1)
        if date_m:
            result['bulletin_date'] = date_m.group(0)
        else:
            alt_m = re.search(r'\b(\d{2})-(\d{2})-(20\d{2})\b', page1)
            if alt_m:
                result['bulletin_date'] = f'{alt_m.group(3)}-{alt_m.group(2)}-{alt_m.group(1)}'
            else:
                name_m = re.search(
                    r'(January|February|March|April|May|June|July|August|September'
                    r'|October|November|December)\s+(\d{1,2}),?\s+(20\d{2})',
                    page1, re.IGNORECASE
                )
                if name_m:
                    mon = _MONTHS[name_m.group(1).lower()]
                    day = int(name_m.group(2))
                    yr  = int(name_m.group(3))
                    result['bulletin_date'] = f'{yr:04d}-{mon:02d}-{day:02d}'
                else:
                    result['bulletin_date'] = None
        print(f'[PARSE] Bulletin date: {result["bulletin_date"]}')

        time_m = re.search(
            r'Time\s+of\s+Issue:\s*(\d{2}):?(\d{2})(?::\d{2})?\s*hours',
            page1, re.IGNORECASE
        )
        if time_m:
            try:
                t_obj = datetime.strptime(f'{time_m.group(1)}:{time_m.group(2)}', '%H:%M')
                result['last_updated'] = t_obj.strftime('%I:%M %p') + ' IST'
            except Exception:
                result['last_updated'] = f'{time_m.group(1)}:{time_m.group(2)} IST'

        slot_m = re.search(r'\((Morning|Mid[\s\-]?[Dd]ay|Evening|Night)\)', page1, re.IGNORECASE)
        if slot_m:
            slot_raw = re.sub(r'mid[\s\-]?day', 'midday', slot_m.group(1).lower())
            result['slot'] = slot_raw

        # ── STEP 2: Find Meteorological Analysis page ─────────────────────
        meteo_text = next(
            (p for p in pages_text if 'meteorological analysis' in p.lower()), None
        )

        # ── STEP 3: Extract met_analysis and systems ───────────────────────
        if meteo_text:
            sentences = extract_met_sentences(meteo_text)
            if sentences:
                result['met_analysis'] = '\n'.join(sentences)
                print(f'[PARSE] met_analysis: {len(sentences)} sentences')
                systems = parse_met_analysis(result['met_analysis'])
                result['systems'] = systems
                print(f'[PARSE] Systems: {len(systems["priority"])} priority, '
                      f'{len(systems["uac"])} UAC, {len(systems["other_troughs"])} troughs, '
                      f'{systems["suppressed_count"]} suppressed')

        # ── STEP 4: Extract bulletin (NLM) text ───────────────────────────
        bulletin_text = (
            extract_monsoon_text(pages_text[0])
            or (extract_monsoon_text(meteo_text) if meteo_text else None)
        )
        if bulletin_text and result['slot']:
            result['bulletin'][result['slot']] = bulletin_text
        elif bulletin_text:
            result['bulletin']['morning'] = bulletin_text

        # ── STEP 4.5: Extract monsoon_advance ─────────────────────────────
        advance_text = (
            extract_monsoon_advance(pages_text[0])
            or (extract_monsoon_advance(meteo_text) if meteo_text else None)
        )
        result['monsoon_advance'] = advance_text
        if advance_text:
            print(f'[PARSE] monsoon_advance: {advance_text[:80]}')

        # ── STEP 5: NLM coordinates ────────────────────────────────────────
        coord_source = bulletin_text or full_text
        result['nlm_coords'] = parse_nlm_coords(coord_source)

    except Exception as e:
        import traceback
        traceback.print_exc()
        result['success'] = False
        result['error']   = str(e)

    return result


# -----------------------------------------------------------------------------
# GITHUB HELPERS
# -----------------------------------------------------------------------------

def github_get_sha(path):
    try:
        url  = f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}'
        resp = requests.get(url, headers=HEADERS_GH, timeout=15)
        return resp.json().get('sha') if resp.status_code == 200 else None
    except Exception:
        return None


def github_push_file(path, content_bytes, commit_message):
    try:
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
    except Exception as e:
        print(f'[GITHUB] ❌ Exception pushing {path}: {e}')
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
