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
# BULLETIN TEXT EXTRACTOR — FIX: captures all sentences until section header
# -----------------------------------------------------------------------------

def extract_monsoon_text(text):
    """
    Extracts all monsoon-related sentences from the PDF text.
    Strategy:
      1. Find 'Advance of Southwest Monsoon' section
      2. Capture everything until next known section header
      3. Remove bullet points (• - *) from extracted text
      4. Return clean combined text
    """
    # Normalize whitespace — preserve line breaks for section detection
    clean = re.sub(r'[ \t]+', ' ', text)
    clean = re.sub(r'\r\n|\r', '\n', clean)
    clean = re.sub(r'\n{3,}', '\n\n', clean)

    # ── Try to find "Advance of Southwest Monsoon" section ───────────────
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
        # ── Fallback: find NLM sentence directly ─────────────────────────
        nlm_m = re.search(
            r'((?:[•\-\*]\s*)?The\s+Northern\s+Limit\s+of\s+Monsoon.+?)'
            r'(?=\n\s*(?:Weather\s+Forecast|Main\s+Features|\Z))',
            clean, re.IGNORECASE | re.DOTALL
        )
        if nlm_m:
            section_text = nlm_m.group(1)
        else:
            # ── Last fallback: conditions sentence only ───────────────────
            cond_m = re.search(
                r'((?:[•\-\*]\s*)?Conditions\s+are\s+(?:favourable|not\s+favourable).+?)'
                r'(?=\n\s*(?:Weather\s+Forecast|Main\s+Features|\Z))',
                clean, re.IGNORECASE | re.DOTALL
            )
            if cond_m:
                section_text = cond_m.group(1)
            else:
                return None

    # Remove bullet points (•, -, *) at start of lines
    section_text = re.sub(r'^\s*[•\-\*]\s*', '', section_text, flags=re.MULTILINE)

    # Collapse into single clean string
    section_text = re.sub(r'\s+', ' ', section_text).strip()

    return section_text if section_text else None


# -----------------------------------------------------------------------------
# CORE PDF PARSER
# -----------------------------------------------------------------------------

def parse_monsoon_pdf(pdf_bytes, pdf_url):
    result = {
        'success':      True,
        'pdf_url':      pdf_url,
        'last_updated': None,
        'slot':         None,
        'bulletin': {
            'morning': None,
            'midday':  None,
            'evening': None,
            'night':   None,
        },
        'nlm_coords': None,
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

        # ── STEP 1: Slot and timestamp from Page 1 ───────────────────────
        page1 = pages_text[0] if pages_text else ''

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

        # ── FIX 1: Broader slot regex — handles Mid-Day, Mid-day, Midday ──
        slot_m = re.search(
            r'\((Morning|Mid[\s\-]?[Dd]ay|Evening|Night)\)',
            page1, re.IGNORECASE
        )
        if slot_m:
            slot_raw = slot_m.group(1).lower()
            # Normalize all mid-day variants to 'midday'
            slot_raw = re.sub(r'mid[\s\-]?day', 'midday', slot_raw)
            result['slot'] = slot_raw
            print(f'[PARSE] Detected slot: {slot_raw}')
        else:
            print('[PARSE] ⚠️ Could not detect slot from page 1')
            print(f'[PARSE] Page 1 text snippet: {page1[:500]}')

        # ── STEP 2: Find Meteorological Analysis page ─────────────────────
        meteo_text = None
        for page_text in pages_text:
            if 'meteorological analysis' in page_text.lower():
                meteo_text = page_text
                break

        # ── STEP 3: Extract bulletin text ─────────────────────────────────
        # FIX 2: Use new extract_monsoon_text that handles bullets + section headers
        bulletin_text = None
        if meteo_text:
            bulletin_text = extract_monsoon_text(meteo_text)
            if bulletin_text:
                print(f'[PARSE] Extracted bulletin text ({len(bulletin_text)} chars) from meteo page')
            else:
                print('[PARSE] ⚠️ No bulletin text found in meteo page')

        # Fallback: try full text
        if not bulletin_text:
            bulletin_text = extract_monsoon_text(full_text)
            if bulletin_text:
                print(f'[PARSE] Extracted bulletin text from full text fallback')

        if bulletin_text and result['slot']:
            result['bulletin'][result['slot']] = bulletin_text
        elif bulletin_text:
            # No slot detected — store in morning as fallback
            result['bulletin']['morning'] = bulletin_text
            print('[PARSE] ⚠️ No slot detected, storing bulletin in morning slot')

        # ── STEP 4: NLM coordinates ───────────────────────────────────────
        coord_source = bulletin_text or full_text
        nlm_coords   = parse_nlm_coords(coord_source)
        if nlm_coords:
            result['nlm_coords'] = nlm_coords
            print(f'[PARSE] Found {len(nlm_coords)} NLM coordinates')

        # ── STEP 5: Parse systems from Meteorological Analysis page ───────
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
    date_str  = now_ist.strftime('%Y-%m-%d')
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
