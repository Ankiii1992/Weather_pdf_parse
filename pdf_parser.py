#!/usr/bin/env python3
# =============================================================================
# pdf_parser.py
# Standalone IMD Bulletin Parser — runs via GitHub Actions cron
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
    'Offshore Trough':                  10,
    'East-West Trough':                 11,
    'Shear Zone':                       12,
    'Western Disturbance':              13,
}

# -----------------------------------------------------------------------------
# GITHUB HELPERS
# -----------------------------------------------------------------------------

def github_get_sha(path):
    url  = f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}'
    resp = requests.get(url, headers=HEADERS_GH, timeout=15)
    if resp.status_code == 200:
        return resp.json().get('sha')
    return None


def github_push_file(path, content_bytes, commit_message):
    url     = f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}'
    encoded = base64.b64encode(content_bytes).decode()
    sha     = github_get_sha(path)
    payload = {
        'message': commit_message,
        'content': encoded,
        'branch':  GITHUB_BRANCH,
    }
    if sha:
        payload['sha'] = sha
    resp = requests.put(url, headers=HEADERS_GH, json=payload, timeout=30)
    if resp.status_code in (200, 201):
        print(f'[GITHUB] ✅ Pushed: {path}')
        return True
    else:
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
            pdf_path = match.group(1)
            pdf_url  = f'https://mausam.imd.gov.in/backend/assets/aiwfb_pdf/{pdf_path}'
            print(f'[IMD] Found PDF URL: {pdf_url}')
            return pdf_url
        print('[IMD] PDF link not found in page HTML')
        print(f'[IMD] Page snippet: {resp.text[2000:2500]}')
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
# PARSING HELPERS
# -----------------------------------------------------------------------------

def parse_level(text):
    if not text:
        return None
    t = text.lower()
    range_match = re.search(r'between\s+([\d.]+)\s*(?:&|to|and)\s*([\d.]+)\s*km', t)
    if range_match:
        lo, hi = float(range_match.group(1)), float(range_match.group(2))
        return {'type': 'range', 'min': lo, 'max': hi, 'display': f'{lo}–{hi} km above MSL'}
    upto_match = re.search(
        r'(?:extending\s+|extends\s+)?up\s*to\s+([\d.]+)\s*km'
        r'|(?:extending\s+)?upto\s+([\d.]+)\s*km', t
    )
    if upto_match:
        val = float(upto_match.group(1) or upto_match.group(2))
        return {'type': 'upto', 'max': val, 'display': f'up to {val} km above MSL'}
    single_match = re.search(r'(?:at\s+)?([\d.]+)\s*km\s*above', t)
    if single_match:
        val = float(single_match.group(1))
        return {'type': 'single', 'min': val, 'display': f'{val} km above MSL'}
    return None


def parse_coords(text):
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
    coords  = []
    matches = re.findall(r'([\d.]+)°?\s*N\s*/\s*([\d.]+)°?\s*E', text)
    for lat_s, lon_s in matches:
        coords.append({'lat': float(lat_s), 'lon': float(lon_s)})
    return coords if coords else None


def extract_over_location(text):
    shifted = re.search(
        r'now\s+lies?\s+over\s+(.+?)(?=\s+(?:at\s+[\d.]|extending|extends|upto|up\s+to|persists|and\s+extend|now\b|\.))',
        text, re.IGNORECASE
    )
    if shifted:
        return shifted.group(1).strip()
    standard = re.search(
        r'\bover\s+(.+?)(?=\s+(?:at\s+[\d.]|extending|extends|upto|up\s+to|persists|and\s+extend|now\b|\.))',
        text, re.IGNORECASE
    )
    if standard:
        return standard.group(1).strip()
    return None


# -----------------------------------------------------------------------------
# MET ANALYSIS EXTRACTOR  ← NEW
# -----------------------------------------------------------------------------

def extract_met_analysis(page_text):
    """
    Extracts and cleans the full text of the Meteorological Analysis page.
    - Removes the page header line and footer
    - Removes bullet points
    - Fixes run-together words caused by PDF extraction
    - Returns one sentence per line as a single string
    """
    # Remove footer
    text = re.sub(r'\*Red color warning.*$', '', page_text, flags=re.IGNORECASE | re.DOTALL).strip()
    # Remove title line
    text = re.sub(r'^Meteorological\s+Analysis[^\n]*\n', '', text, flags=re.IGNORECASE).strip()
    # Remove bullet points
    text = re.sub(r'^\s*[•\-\*]\s*', '', text, flags=re.MULTILINE)

    # ── Fix fully-merged patterns (PDF extraction artefacts) ─────────────
    run_together_fixes = [
        # Specific fully-merged sentences
        (r'Thetroughinwesterlieswithitsaxisat([\d.]+)km abovemeansealevelroughlyalongLong\.',
         r'The trough in westerlies with its axis at \1 km above mean sea level roughly along Long.'),
        (r'Thetroughinwesterlieswithitsaxisat([\d.]+)kmabovemeansealevelroughlyalongLong\.',
         r'The trough in westerlies with its axis at \1 km above mean sea level roughly along Long.'),
        (r'Theupperaircycloniccirculationovercentral([A-Za-z])',
         r'The upper air cyclonic circulation over central \1'),
        (r'Theupperaircycloniccirculationover([A-Z])',
         r'The upper air cyclonic circulation over \1'),
        (r'Theupperair cycloniccirculationover',
         'The upper air cyclonic circulation over'),
        (r'Theupperair\b', 'The upper air'),
        # Common merged fragments
        (r'\bextendingupto\b', 'extending upto'),
        (r'\bupto([\d.]+)km\b', r'upto \1 km'),
        (r'\b([\d.]+)kmabovemeansealevel\b', r'\1 km above mean sea level'),
        (r'\bkmabovemeansealevel\b', 'km above mean sea level'),
        (r'\babovemeansealevel\b', 'above mean sea level'),
        (r'\bmeansealevel\b', 'mean sea level'),
        (r'\broughlyalong\b', 'roughly along'),
        (r'\bwithitsaxis\b', 'with its axis'),
        (r'\bitsaxisat\b', 'its axis at'),
        (r'\binwesterlies\b', 'in westerlies'),
        (r'\bwesterlieswith\b', 'westerlies with'),
        (r'\bcycloniccirculation\b', 'cyclonic circulation'),
        (r'\bcirculationover\b', 'circulation over'),
        (r'\bneighbourhoodat\b', 'neighbourhood at'),
        (r'\bneighbourhood at\b', 'neighbourhood at'),
        (r'([A-Za-z])&neighbourhood\b', r'\1 & neighbourhood'),
        (r'([A-Za-z])&\b', r'\1 & '),
        (r'\bSoutheastArabian\b', 'Southeast Arabian'),
        (r'\bArabianSea\b', 'Arabian Sea'),
        (r'\b([\d.]+)km\b', r'\1 km'),
        (r'\bkm(above|below|at|between|extending|roughly|along)\b', r'km \1'),
        # General: insert space before capital letter after lowercase (last resort)
        (r'([a-z])([A-Z][a-z]{2,})', r'\1 \2'),
        # Collapse multiple spaces
        (r' {2,}', ' '),
    ]
    for pattern, repl in run_together_fixes:
        text = re.sub(pattern, repl, text)

    # ── Insert newline at sentence boundaries ────────────────────────────
    text = re.sub(r'\.\s*(The |Conditions )', r'.\n\1', text)

    # ── Build final sentence list ─────────────────────────────────────────
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    sentences = []
    current = ''
    for line in lines:
        current = (current + ' ' + line).strip() if current else line
        if re.search(r'\.\s*$', current):
            sentences.append(re.sub(r' {2,}', ' ', current).strip())
            current = ''
    if current.strip():
        sentences.append(current.strip())

    return '\n'.join(sentences)


# -----------------------------------------------------------------------------
# SYSTEM CLASSIFIER
# -----------------------------------------------------------------------------

def classify_system(sentence):
    s     = sentence.strip()
    lower = s.lower()

    if 'has become less marked' in lower:
        return None
    if 'northern limit of monsoon' in lower:
        return None
    if lower.lstrip().startswith('conditions are') and 'monsoon' in lower:
        return None

    subject = re.sub(r'^(The|An?)\s+', '', s, flags=re.IGNORECASE).lower().strip()

    # ── WESTERN DISTURBANCE ──────────────────────────────────────────────
    if subject.startswith('western disturbance'):
        system = {'tier': 1, 'type': 'Western Disturbance'}
        if 'cyclonic circulation' in lower:
            system['form'] = 'cyclonic_circulation'
            loc = re.search(
                r'cyclonic\s+circulation\s+over\s+(.+?)(?=\s+(?:at\s+[\d.]|extending|extends|upto|up\s+to|with\s+a\s+trough|persists|\.))',
                s, re.IGNORECASE
            )
            if loc:
                system['location'] = loc.group(1).strip()
            system['level'] = parse_level(s)
            if 'trough aloft' in lower:
                aloft  = {}
                axis_m = re.search(
                    r'(?:roughly\s+)?along\s+(Long\.?\s*[\d.]+°?\s*E[^.]+?Lat\.?\s*[\d.]+°?\s*N[^.]*)',
                    s, re.IGNORECASE
                )
                if axis_m:
                    aloft['axis'] = 'along ' + axis_m.group(1).strip().rstrip(' ,')
                aloft_lvl = re.search(
                    r'trough\s+aloft[^.]*?(?:at\s+)?([\d.]+)\s*km\s*above',
                    s, re.IGNORECASE
                )
                if aloft_lvl:
                    aloft['level'] = f'{float(aloft_lvl.group(1))} km above MSL'
                if aloft:
                    system['trough_aloft'] = aloft
        else:
            system['form'] = 'trough_in_westerlies'
            loc_m = re.search(
                r'(?:now\s+runs?\s+)?(?:roughly\s+)?along\s+(.+?)(?:\s+persists|\s+and\s+|\.$|$)',
                s, re.IGNORECASE
            )
            if loc_m:
                system['location'] = 'along ' + loc_m.group(1).strip().rstrip(' ,')
            coords = parse_coords(s)
            if coords:
                system['coords'] = coords
            system['level'] = parse_level(s)
        return {k: v for k, v in system.items() if v is not None}

    # ── EAST-WEST TROUGH ────────────────────────────────────────────────
    if subject.startswith('east-west trough') or subject.startswith('east west trough'):
        system = {'tier': 1, 'type': 'East-West Trough'}
        extent_m = re.search(
            r'from\s+(.+?)\s+to\s+(.+?)(?=\s+across|\s+at\s+[\d.]|\s+extending|\s+persists|\.|$)',
            s, re.IGNORECASE
        )
        if extent_m:
            system['extent'] = f"from {extent_m.group(1).strip()} to {extent_m.group(2).strip()}"
        via_m = re.search(
            r'across\s+(.+?)(?=\s+(?:at\s+[\d.]|extending|extends|upto|up\s+to|persists|\.))',
            s, re.IGNORECASE
        )
        if via_m:
            system['via'] = via_m.group(1).strip()
        system['level'] = parse_level(s)
        return {k: v for k, v in system.items() if v is not None}

    # ── MONSOON TROUGH ───────────────────────────────────────────────────
    if subject.startswith('monsoon trough'):
        system = {'tier': 1, 'type': 'Monsoon Trough'}
        if 'south of normal'   in lower: system['position'] = 'South of normal'
        elif 'north of normal' in lower: system['position'] = 'North of normal'
        elif 'foothills'       in lower: system['position'] = 'Foothills of Himalayas'
        elif 'normal position' in lower: system['position'] = 'Normal position'
        extent_m = re.search(
            r'from\s+(.+?)\s+to\s+(.+?)(?=\s+across|\s+at\s+[\d.]|\s+extending|\s+persists|\.|$)',
            s, re.IGNORECASE
        )
        if extent_m:
            system['west_end'] = extent_m.group(1).strip()
            system['east_end'] = extent_m.group(2).strip()
        via_m = re.search(
            r'across\s+(.+?)(?=\s+(?:at\s+[\d.]|extending|extends|upto|up\s+to|persists|\.))',
            s, re.IGNORECASE
        )
        if via_m:
            system['via'] = via_m.group(1).strip()
        system['level'] = parse_level(s)
        return {k: v for k, v in system.items() if v is not None}

    # ── OFFSHORE TROUGH ──────────────────────────────────────────────────
    if subject.startswith('offshore trough'):
        system = {'tier': 1, 'type': 'Offshore Trough'}
        extent_m = re.search(
            r'from\s+(.+?)\s+to\s+(.+?)(?=\s+at\s+[\d.]|\s+extending|\s+persists|\.|$)',
            s, re.IGNORECASE
        )
        if extent_m:
            system['extent'] = f"{extent_m.group(1).strip()} to {extent_m.group(2).strip()}"
        else:
            along_m = re.search(r'along\s+(.+?)(?=\s+persists|\.|$)', s, re.IGNORECASE)
            if along_m:
                system['extent'] = along_m.group(1).strip()
        system['level'] = parse_level(s)
        return {k: v for k, v in system.items() if v is not None}

    # ── SHEAR ZONE ───────────────────────────────────────────────────────
    if subject.startswith('shear zone') or subject.startswith('shear line'):
        system = {'tier': 1, 'type': 'Shear Zone'}
        system['location'] = extract_over_location(s)
        system['level']    = parse_level(s)
        return {k: v for k, v in system.items() if v is not None}

    # ── LPA / DEPRESSION / CYCLONE ───────────────────────────────────────
    lpa_keywords = [
        'low pressure area', 'well marked low pressure', 'well-marked low pressure',
        'depression', 'deep depression', 'cyclonic storm',
        'severe cyclonic storm', 'very severe cyclonic storm',
        'extremely severe cyclonic storm', 'super cyclonic storm'
    ]
    matched_lpa = next((k for k in lpa_keywords if subject.startswith(k)), None)
    if matched_lpa:
        if 'super cyclonic'         in matched_lpa: stype = 'Super Cyclonic Storm'
        elif 'extremely severe'     in matched_lpa: stype = 'Extremely Severe Cyclonic Storm'
        elif 'very severe cyclonic' in matched_lpa: stype = 'Very Severe Cyclonic Storm'
        elif 'severe cyclonic'      in matched_lpa: stype = 'Severe Cyclonic Storm'
        elif 'cyclonic storm'       in matched_lpa: stype = 'Cyclonic Storm'
        elif 'deep depression'      in matched_lpa: stype = 'Deep Depression'
        elif 'depression'           in matched_lpa: stype = 'Depression'
        else:                                        stype = 'Low Pressure Area'
        system = {'tier': 1, 'type': stype}
        system['location'] = extract_over_location(s)
        system['coords']   = parse_coords(s)
        mov_m = re.search(r'moving\s+(.+?)(?=\s+at\s+[\d.]|\s+and\s+|\s+likely|\.|$)', s, re.IGNORECASE)
        if mov_m:
            system['movement'] = mov_m.group(1).strip()
        return {k: v for k, v in system.items() if v is not None}

    # ── UPPER AIR CYCLONIC CIRCULATION (Tier 2) ──────────────────────────
    if subject.startswith('upper air cyclonic circulation'):
        system = {'tier': 2, 'type': 'Upper Air Cyclonic Circulation'}
        system['location'] = extract_over_location(s)
        system['level']    = parse_level(s)
        return {k: v for k, v in system.items() if v is not None}

    # ── GENERIC TROUGH (Tier 2) ──────────────────────────────────────────
    if subject.startswith('trough'):
        if 'western disturbance' in lower:
            return None
        system = {'tier': 2, 'type': 'Trough'}
        if subject.startswith('trough in westerlies') or \
           ('westerlies' in lower and 'along long' in lower):
            system['subtype'] = 'westerlies'
            loc_m = re.search(
                r'(?:roughly\s+)?along\s+(.+?)(?=\s+(?:at\s+[\d.]|extending|persists|\.))',
                s, re.IGNORECASE
            )
            if loc_m:
                system['extent'] = 'along ' + loc_m.group(1).strip()
        else:
            system['subtype'] = 'general'
            extent_m = re.search(
                r'from\s+(.+?)\s+to\s+(.+?)(?=\s+across|\s+at\s+[\d.]|\s+extending|\s+persists|\.|$)',
                s, re.IGNORECASE
            )
            if extent_m:
                system['extent'] = f"from {extent_m.group(1).strip()} to {extent_m.group(2).strip()}"
            via_m = re.search(
                r'across\s+(.+?)(?=\s+(?:at\s+[\d.]|extending|extends|upto|up\s+to|persists|\.))',
                s, re.IGNORECASE
            )
            if via_m:
                system['via'] = via_m.group(1).strip()
        system['level'] = parse_level(s)
        return {k: v for k, v in system.items() if v is not None}

    return None


# -----------------------------------------------------------------------------
# BULLETIN TEXT EXTRACTOR
# -----------------------------------------------------------------------------

def extract_monsoon_text(text):
    clean = re.sub(r'[ \t]+', ' ', text)
    clean = re.sub(r'\r\n|\r', '\n', clean)
    clean = re.sub(r'\n{3,}', '\n\n', clean)

    adv_section_m = re.search(
        r'Advance\s+of\s+Southwest\s+Monsoon[^\n]*\n(.*?)'
        r'(?=\n\s*(?:Weather\s+Forecast|Main\s+Features|Significant\s+Weather'
        r'|Northeast\s+India|Northwest\s+India|South\s+Peninsular'
        r'|Central\s+India|East\s+India|West\s+India|\Z))',
        clean, re.IGNORECASE | re.DOTALL
    )

    if adv_section_m:
        section_text = adv_section_m.group(1)
    else:
        nlm_m = re.search(
            r'((?:[•\-\*]\s*)?The\s+Northern\s+Limit\s+of\s+Monsoon.+?)'
            r'(?=\n\s*(?:Weather\s+Forecast|Main\s+Features|\Z))',
            clean, re.IGNORECASE | re.DOTALL
        )
        if nlm_m:
            section_text = nlm_m.group(1)
        else:
            cond_m = re.search(
                r'((?:[•\-\*]\s*)?Conditions\s+are\s+(?:favourable|not\s+favourable).+?)'
                r'(?=\n\s*(?:Weather\s+Forecast|Main\s+Features|\Z))',
                clean, re.IGNORECASE | re.DOTALL
            )
            if cond_m:
                section_text = cond_m.group(1)
            else:
                return None

    section_text = re.sub(r'^\s*[•\-\*]\s*', '', section_text, flags=re.MULTILINE)
    section_text = re.sub(r'\s+', ' ', section_text).strip()
    return section_text if section_text else None


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
        'bulletin': {
            'morning': None,
            'midday':  None,
            'evening': None,
            'night':   None,
        },
        'nlm_coords':   None,
        'met_analysis': None,   # ← NEW field
        'systems': {
            'priority':        [],
            'uac':             [],
            'other_troughs':   [],
            'suppressed_count': 0,
        },
        'mjo': None,
    }

    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            pages_text = [page.extract_text() or '' for page in pdf.pages]

        full_text = '\n'.join(pages_text)

        # ── STEP 1: Slot, timestamp and bulletin date from Page 1 ──────────
        page1 = pages_text[0] if pages_text else ''

        # Extract bulletin date — e.g. "2026-05-28" at top of page 1
        # Use simple string search to avoid regex word-boundary issues
        date_m = re.search(r'(20[0-9]{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01]))', page1)
        if date_m:
            result['bulletin_date'] = date_m.group(1)
            print(f'[PARSE] Bulletin date from PDF: {date_m.group(1)}')
        else:
            # Fallback: try DD-MM-YYYY format
            alt_m = re.search(r'(\d{2})-(\d{2})-(20[0-9]{2})', page1)
            if alt_m:
                result['bulletin_date'] = f'{alt_m.group(3)}-{alt_m.group(2)}-{alt_m.group(1)}'
                print(f'[PARSE] Bulletin date (alt format): {result["bulletin_date"]}')
            else:
                result['bulletin_date'] = None
                print('[PARSE] ⚠️ Could not extract bulletin date from PDF')

        time_m = re.search(
            r'Time\s+of\s+Issue:\s*(\d{2}:\d{2}(?::\d{2})?)\s*hours\s*IST',
            page1, re.IGNORECASE
        )
        if time_m:
            raw_time = time_m.group(1)[:5]
            try:
                t_obj = datetime.strptime(raw_time, '%H:%M')
                result['last_updated'] = t_obj.strftime('%I:%M %p') + ' IST'
            except Exception:
                result['last_updated'] = raw_time + ' IST'

        slot_m = re.search(
            r'\((Morning|Mid[\s\-]?[Dd]ay|Evening|Night)\)',
            page1, re.IGNORECASE
        )
        if slot_m:
            slot_raw = slot_m.group(1).lower()
            slot_raw = re.sub(r'mid[\s\-]?day', 'midday', slot_raw)
            result['slot'] = slot_raw
            print(f'[PARSE] Detected slot: {slot_raw}')
        else:
            print('[PARSE] ⚠️ Could not detect slot from page 1')

        # ── STEP 2: Find Meteorological Analysis page ─────────────────────
        meteo_text = None
        for page_text in pages_text:
            if 'meteorological analysis' in page_text.lower():
                meteo_text = page_text
                break

        # ── STEP 3: Extract met_analysis full text  ← NEW ─────────────────
        if meteo_text:
            met_analysis = extract_met_analysis(meteo_text)
            if met_analysis:
                result['met_analysis'] = met_analysis
                print(f'[PARSE] Extracted met_analysis ({len(met_analysis.splitlines())} sentences)')
            else:
                print('[PARSE] ⚠️ Could not extract met_analysis text')

        # ── STEP 4: Extract bulletin text ─────────────────────────────────
        bulletin_text = None
        if meteo_text:
            bulletin_text = extract_monsoon_text(meteo_text)
            if bulletin_text:
                print(f'[PARSE] Extracted bulletin text ({len(bulletin_text)} chars)')

        if not bulletin_text:
            bulletin_text = extract_monsoon_text(full_text)
            if bulletin_text:
                print('[PARSE] Extracted bulletin text from full text fallback')

        if bulletin_text and result['slot']:
            result['bulletin'][result['slot']] = bulletin_text
        elif bulletin_text:
            result['bulletin']['morning'] = bulletin_text
            print('[PARSE] ⚠️ No slot detected, storing bulletin in morning slot')

        # ── STEP 5: NLM coordinates ───────────────────────────────────────
        coord_source = bulletin_text or full_text
        nlm_coords   = parse_nlm_coords(coord_source)
        if nlm_coords:
            result['nlm_coords'] = nlm_coords
            print(f'[PARSE] Found {len(nlm_coords)} NLM coordinates')

        # ── STEP 6: Parse systems from Meteorological Analysis page ───────
        if meteo_text:
            clean = re.sub(r'\s+', ' ', meteo_text).strip()

            raw_sentences = re.split(
                r'(?<=[.!?])\s+(?='
                r'(?:The|An?)\s+'
                r'(?:upper\s+air\s+cyclonic|western\s+disturbance|'
                r'east[\s-]west\s+trough|monsoon\s+trough|offshore\s+trough|'
                r'shear\s+zone|shear\s+line|'
                r'trough\s+(?:from|now|runs|in\s+westerlies)|'
                r'low\s+pressure|well\s+marked\s+low|well-marked\s+low|'
                r'deep\s+depression|depression|cyclonic\s+storm|'
                r'severe\s+cyclonic|very\s+severe|extremely\s+severe|super\s+cyclonic)'
                r')',
                clean, flags=re.IGNORECASE
            )

            suppressed_count = 0
            all_systems      = []

            for sent in raw_sentences:
                sent = sent.strip()
                if not sent:
                    continue
                if 'has become less marked' in sent.lower():
                    suppressed_count += 1
                    continue
                system = classify_system(sent)
                if system is None:
                    continue
                all_systems.append(system)

            tier1 = [s for s in all_systems if s.get('tier') == 1]
            tier2 = [s for s in all_systems if s.get('tier') == 2]
            tier1.sort(key=lambda s: SYSTEM_PRIORITY.get(s.get('type', ''), 99))

            uacs          = [s for s in tier2 if s.get('type') == 'Upper Air Cyclonic Circulation']
            other_troughs = [s for s in tier2 if s.get('type') != 'Upper Air Cyclonic Circulation']

            def clean_system(s):
                return {k: v for k, v in s.items() if k != 'tier' and v is not None}

            result['systems']['priority']      = [clean_system(s) for s in tier1]
            result['systems']['uac']           = [
                {k: v for k, v in {'location': s.get('location'), 'level': s.get('level')}.items() if v is not None}
                for s in uacs
            ]
            result['systems']['other_troughs'] = [
                {k: v for k, v in {
                    'subtype': s.get('subtype'), 'extent': s.get('extent'),
                    'via': s.get('via'), 'level': s.get('level')
                }.items() if v is not None}
                for s in other_troughs
            ]
            result['systems']['suppressed_count'] = suppressed_count
            print(f'[PARSE] Systems: {len(tier1)} priority, {len(uacs)} UAC, {len(other_troughs)} troughs')

    except Exception as e:
        print(f'[PARSE] Error: {e}')
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
        print('[MAIN] ❌ GITHUB_TOKEN not set — cannot push to GitHub')
        sys.exit(1)

    pdf_url = fetch_imd_pdf_url()
    if not pdf_url:
        print('[MAIN] ❌ Could not find PDF URL — aborting')
        sys.exit(1)

    pdf_bytes = download_pdf(pdf_url)
    if not pdf_bytes:
        print('[MAIN] ❌ Could not download PDF — aborting')
        sys.exit(1)

    print(f'[MAIN] Downloaded PDF — {len(pdf_bytes):,} bytes')

    parsed = parse_monsoon_pdf(pdf_bytes, pdf_url)
    if not parsed['success']:
        print(f'[MAIN] ❌ Parse failed: {parsed.get("error")}')
        sys.exit(1)

    now_ist   = datetime.now(IST)
    slot      = parsed.get('slot') or 'unknown'

    # ── Use actual bulletin date from PDF, not script run time ────────────
    bulletin_date = parsed.get('bulletin_date')
    if bulletin_date:
        date_str = bulletin_date
        print(f'[MAIN] Using bulletin date from PDF: {date_str}')
    else:
        date_str = now_ist.strftime('%Y-%m-%d')
        print(f'[MAIN] ⚠️ Bulletin date not found in PDF — falling back to today: {date_str}')

    timestamp = now_ist.strftime('%Y-%m-%d %H:%M IST')

    parsed['fetched_at'] = timestamp
    print(f'[MAIN] Parsed successfully — slot: {slot}')

    commit_msg = f'Monsoon bulletin {date_str} {slot} ({now_ist.strftime("%H:%M IST")})'

    json_path = f'weather_pdf/bulletins/{date_str}_{slot}.json'
    github_push_json(json_path, parsed, commit_msg)

    pdf_path = f'weather_pdf/pdfs/{date_str}_{slot}.pdf'
    github_push_file(pdf_path, pdf_bytes, commit_msg)

    github_push_json('weather_pdf/latest.json', parsed, f'Update latest.json — {timestamp}')

    print(f'[MAIN] ✅ Done — {timestamp}')


if __name__ == '__main__':
    main()
