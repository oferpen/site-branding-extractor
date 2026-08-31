#!/usr/bin/env python3
"""Extract a website's logo and dominant colors.

Usage:
    python3 extract_site_branding.py <url> [--out DIR] [--colors N]
"""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; BrandExtractor/1.0)'}

LOGO_HINTS = re.compile(r'logo', re.IGNORECASE)


def get_logo_candidates(soup, base_url):
    candidates = []

    # Favicons / touch icons are the most reliable brand mark: small, square,
    # not prone to matching unrelated marketing images that happen to mention "logo".
    # (Filtering by a lambda on `rel=` directly doesn't reliably match this
    # multi-valued attribute in BeautifulSoup, so filter manually instead.)
    for link in soup.find_all('link'):
        rel = link.get('rel') or []
        rel_str = ' '.join(rel).lower()
        href = link.get('href')
        if href and 'icon' in rel_str:
            score = 6 if 'apple-touch' in rel_str else 5
            candidates.append((score, urljoin(base_url, href)))

    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src')
        if not src:
            continue
        cls = ' '.join(img.get('class') or [])
        img_id = img.get('id') or ''
        filename = urlparse(src).path.lower()

        in_header = img.find_parent(['header', 'nav']) is not None
        name_or_id_match = LOGO_HINTS.search(cls) or LOGO_HINTS.search(img_id)
        src_match = LOGO_HINTS.search(filename)
        alt_match = LOGO_HINTS.search(img.get('alt') or '')

        if name_or_id_match and in_header:
            candidates.append((4, urljoin(base_url, src)))
        elif src_match and in_header:
            candidates.append((3, urljoin(base_url, src)))
        elif name_or_id_match:
            candidates.append((2, urljoin(base_url, src)))
        elif alt_match and in_header:
            candidates.append((2, urljoin(base_url, src)))

    og_image = soup.find('meta', property='og:image')
    if og_image and og_image.get('content'):
        candidates.append((1, urljoin(base_url, og_image['content'])))

    candidates.sort(key=lambda c: c[0], reverse=True)
    return [url for _, url in candidates]


HEX_COLOR_RE = re.compile(r'#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b')
CSS_CLASS_RULE_RE = re.compile(r'\.([\w-]+)\s*\{([^}]*)\}')
CLASS_ATTR_RE = re.compile(r'class="([\w\s-]+)"')


def _normalize_hex(hex_value):
    hex_value = hex_value.lower()
    if len(hex_value) == 3:
        hex_value = ''.join(c * 2 for c in hex_value)
    return '#' + hex_value


def extract_svg_colors(svg_text, n=5):
    """Pull dominant colors straight from SVG markup (fill/stroke), since
    Pillow can't rasterize SVG. Weighted by how many shapes use each color,
    counting both CSS-class-defined fills and inline fill/style attributes.
    """
    counts = {}

    # Colors defined once in a <style> block and referenced by class="...".
    class_to_color = {}
    for class_name, rule_body in CSS_CLASS_RULE_RE.findall(svg_text):
        match = HEX_COLOR_RE.search(rule_body)
        if match:
            class_to_color[class_name] = _normalize_hex(match.group(1))

    for class_attr in CLASS_ATTR_RE.findall(svg_text):
        for class_name in class_attr.split():
            color = class_to_color.get(class_name)
            if color:
                counts[color] = counts.get(color, 0) + 1

    # Inline fill="#hex" / stroke="#hex" and style="fill:#hex" attributes.
    for attr in ('fill', 'stroke'):
        for match in re.finditer(attr + r'\s*=\s*"(#[0-9a-fA-F]{3,6})"', svg_text):
            color = _normalize_hex(match.group(1).lstrip('#'))
            counts[color] = counts.get(color, 0) + 1

    for style_attr in re.finditer(r'style="([^"]*)"', svg_text):
        match = HEX_COLOR_RE.search(style_attr.group(1))
        if match:
            color = _normalize_hex(match.group(1))
            counts[color] = counts.get(color, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [color for color, _ in ranked[:n]]


def is_near_white_or_gray(r, g, b, threshold=18):
    """Flag whites/near-blacks/grays so the flattened background doesn't dominate the palette."""
    if max(r, g, b) > 245 or max(r, g, b) < 12:
        return True
    return max(r, g, b) - min(r, g, b) < threshold


def extract_colors(image_bytes, n=5):
    img = Image.open(BytesIO(image_bytes)).convert('RGBA')

    background = Image.new('RGBA', img.size, (255, 255, 255, 255))
    flattened = Image.alpha_composite(background, img).convert('RGB')

    small = flattened.resize((150, 150))
    quantized = small.quantize(colors=16, method=Image.MEDIANCUT)
    palette = quantized.getpalette()
    color_counts = quantized.getcolors()
    color_counts.sort(reverse=True)

    hex_colors = []
    fallback = []
    for count, index in color_counts:
        r, g, b = palette[index * 3:index * 3 + 3]
        hex_color = '#{:02x}{:02x}{:02x}'.format(r, g, b)
        if is_near_white_or_gray(r, g, b):
            fallback.append(hex_color)
            continue
        hex_colors.append(hex_color)
        if len(hex_colors) == n:
            return hex_colors

    hex_colors.extend(fallback[: n - len(hex_colors)])
    return hex_colors[:n]


def analyze_site(url, n_colors=5):
    """Fetch a site, find its logo, and extract dominant colors.

    Returns a dict with url, logo_url, logo_bytes, logo_content_type, dominant_colors.
    Raises ValueError if no logo can be found.
    """
    url = url if url.startswith('http') else 'https://' + url
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    candidates = get_logo_candidates(soup, url)
    if not candidates:
        raise ValueError(f'no logo found for {url}')

    # Some sites (SPAs with catch-all routing) return 200 OK with an HTML
    # page for a nonexistent image path, so a candidate isn't trustworthy
    # until its response actually looks like an image.
    logo_url = None
    logo_resp = None
    for candidate_url in candidates:
        try:
            candidate_resp = requests.get(candidate_url, headers=HEADERS, timeout=15)
            candidate_resp.raise_for_status()
        except requests.exceptions.RequestException:
            continue
        if candidate_resp.headers.get('Content-Type', '').startswith('image/'):
            logo_url = candidate_url
            logo_resp = candidate_resp
            break

    if not logo_resp:
        raise ValueError(f'no logo found for {url}')

    content_type = logo_resp.headers.get('Content-Type', 'image/png')
    is_svg = 'svg' in content_type or logo_url.lower().endswith('.svg')

    try:
        if is_svg:
            colors = extract_svg_colors(logo_resp.text, n=n_colors)
        else:
            colors = extract_colors(logo_resp.content, n=n_colors)
    except Exception:
        colors = []

    return {
        'url': url,
        'logo_url': logo_url,
        'logo_bytes': logo_resp.content,
        'logo_content_type': content_type,
        'dominant_colors': colors,
    }


def main():
    parser = argparse.ArgumentParser(description="Extract a website's logo and dominant colors")
    parser.add_argument('url', help='Website URL, e.g. https://example.com')
    parser.add_argument('--out', default='.', help='Output directory for the saved logo (default: current dir)')
    parser.add_argument('--colors', type=int, default=5, help='Number of dominant colors to extract (default: 5)')
    args = parser.parse_args()

    try:
        result = analyze_site(args.url, n_colors=args.colors)
    except ValueError as e:
        print(json.dumps({'error': str(e)}))
        return

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(urlparse(result['logo_url']).path).suffix or '.png'
    domain = urlparse(result['url']).netloc.replace('.', '_')
    logo_path = out_dir / f'{domain}_logo{ext}'
    logo_path.write_bytes(result['logo_bytes'])

    print(json.dumps({
        'url': result['url'],
        'logo_url': result['logo_url'],
        'logo_saved_to': str(logo_path),
        'dominant_colors': result['dominant_colors'],
    }, indent=2))


if __name__ == '__main__':
    main()
