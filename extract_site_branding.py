#!/usr/bin/env python3
"""Extract a website's logo, icon, cover image, and brand colors.

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


def find_icon_candidates(soup, base_url):
    """Favicon / touch-icon links, most specific (apple-touch-icon) first."""
    candidates = []

    # Filtering by a lambda on `rel=` directly doesn't reliably match this
    # multi-valued attribute in BeautifulSoup, so filter manually instead.
    for link in soup.find_all('link'):
        rel = link.get('rel') or []
        rel_str = ' '.join(rel).lower()
        href = link.get('href')
        if href and 'icon' in rel_str:
            score = 2 if 'apple-touch' in rel_str else 1
            candidates.append((score, urljoin(base_url, href)))

    candidates.sort(key=lambda c: c[0], reverse=True)
    urls = [url for _, url in candidates]
    urls.append(urljoin(base_url, '/favicon.ico'))
    return urls


def find_logo_candidates(soup, base_url):
    """The site's actual wordmark/logo image, as distinct from its icon."""
    candidates = []

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

        # Only trust a "logo" hint when the image also sits in the header/nav —
        # a match anywhere on the page (e.g. a customer-logo showcase section)
        # is too likely to be unrelated to the site's own brand mark.
        if name_or_id_match and in_header:
            candidates.append((4, urljoin(base_url, src)))
        elif src_match and in_header:
            candidates.append((3, urljoin(base_url, src)))
        elif alt_match and in_header:
            candidates.append((2, urljoin(base_url, src)))

    candidates.sort(key=lambda c: c[0], reverse=True)
    return [url for _, url in candidates]


def find_cover_image_candidates(soup, base_url):
    """The site's social-share preview image (og:image / twitter:image)."""
    candidates = []

    for prop in ('og:image:secure_url', 'og:image'):
        tag = soup.find('meta', property=prop)
        if tag and tag.get('content'):
            candidates.append(urljoin(base_url, tag['content']))

    tag = soup.find('meta', attrs={'name': 'twitter:image'})
    if tag and tag.get('content'):
        candidates.append(urljoin(base_url, tag['content']))

    return candidates


def find_theme_color(soup):
    """An explicit brand color the site declares itself, if any."""
    for name in ('theme-color', 'msapplication-TileColor'):
        tag = soup.find('meta', attrs={'name': name})
        if not tag or not tag.get('content'):
            continue
        content = tag['content'].strip()
        if re.match(r'^#[0-9a-fA-F]{3}$', content) or re.match(r'^#[0-9a-fA-F]{6}$', content):
            return _normalize_hex(content.lstrip('#'))
    return None


HEX_COLOR_RE = re.compile(r'#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b')
CSS_CLASS_RULE_RE = re.compile(r'\.([\w-]+)\s*\{([^}]*)\}')
CLASS_ATTR_RE = re.compile(r'class="([\w\s-]+)"')


def _normalize_hex(hex_value):
    hex_value = hex_value.lower()
    if len(hex_value) == 3:
        hex_value = ''.join(c * 2 for c in hex_value)
    return '#' + hex_value


def extract_svg_colors(svg_text, n=8):
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


def extract_colors(image_bytes, n=8):
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


def colors_from_asset(asset, n=8):
    """extract_colors/extract_svg_colors dispatch based on the asset's content type."""
    if not asset:
        return []
    is_svg = 'svg' in asset['content_type'] or asset['url'].lower().endswith('.svg')
    try:
        if is_svg:
            return extract_svg_colors(asset['bytes'].decode('utf-8', errors='ignore'), n=n)
        return extract_colors(asset['bytes'], n=n)
    except Exception:
        return []


def rank_colors(weighted_colors, n):
    """Dedupe a list of hex colors (with repeats standing in for weight) into
    the n most-voted, preserving first-seen order as the tiebreaker.
    """
    counts = {}
    order = []
    for color in weighted_colors:
        if color not in counts:
            order.append(color)
        counts[color] = counts.get(color, 0) + 1
    ranked = sorted(order, key=lambda c: counts[c], reverse=True)
    return ranked[:n]


def fetch_first_valid_image(candidate_urls):
    """Try candidate URLs in order, returning the first that's actually an
    image. Some sites (SPAs with catch-all routing) return 200 OK with an
    HTML page for a nonexistent image path, so a URL isn't trustworthy
    until its response's Content-Type confirms it's really an image.
    """
    for candidate_url in candidate_urls:
        try:
            resp = requests.get(candidate_url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except requests.exceptions.RequestException:
            continue
        content_type = resp.headers.get('Content-Type', '')
        if content_type.startswith('image/'):
            return {'url': candidate_url, 'bytes': resp.content, 'content_type': content_type}
    return None


def _asset_summary(asset):
    if not asset:
        return None
    return {'url': asset['url'], 'content_type': asset['content_type']}


def analyze_site(url, n_colors=6):
    """Fetch a site and pull its logo, icon, cover image, and brand colors.

    Returns a dict: url, icon, logo, cover_image (each None or
    {url, bytes, content_type}), and brand_colors (list of hex strings).
    Raises ValueError if none of icon/logo/cover_image can be found.
    """
    url = url if url.startswith('http') else 'https://' + url
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    icon = fetch_first_valid_image(find_icon_candidates(soup, url))
    logo = fetch_first_valid_image(find_logo_candidates(soup, url))
    cover_image = fetch_first_valid_image(find_cover_image_candidates(soup, url))

    if not icon and not logo and not cover_image:
        raise ValueError(f'no logo, icon, or cover image found for {url}')

    # Most sites don't have a distinct header wordmark separate from their
    # icon; fall back to showing the icon as the logo in that case.
    if not logo:
        logo = icon

    theme_color = find_theme_color(soup)

    color_votes = []
    if theme_color:
        color_votes.extend([theme_color] * 4)
    color_votes.extend(colors_from_asset(logo))
    if icon and icon is not logo:
        color_votes.extend(colors_from_asset(icon))

    brand_colors = rank_colors(color_votes, n=n_colors)

    return {
        'url': url,
        'icon': icon,
        'logo': logo,
        'cover_image': cover_image,
        'brand_colors': brand_colors,
    }


def _save_asset(asset, out_dir, domain, label):
    if not asset:
        return None
    ext = Path(urlparse(asset['url']).path).suffix or '.png'
    path = out_dir / f'{domain}_{label}{ext}'
    path.write_bytes(asset['bytes'])
    return str(path)


def main():
    parser = argparse.ArgumentParser(description="Extract a website's logo, icon, cover image, and brand colors")
    parser.add_argument('url', help='Website URL, e.g. https://example.com')
    parser.add_argument('--out', default='.', help='Output directory for saved images (default: current dir)')
    parser.add_argument('--colors', type=int, default=6, help='Number of brand colors to extract (default: 6)')
    args = parser.parse_args()

    try:
        result = analyze_site(args.url, n_colors=args.colors)
    except ValueError as e:
        print(json.dumps({'error': str(e)}))
        return

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    domain = urlparse(result['url']).netloc.replace('.', '_')

    print(json.dumps({
        'url': result['url'],
        'icon': {
            'url': result['icon']['url'],
            'saved_to': _save_asset(result['icon'], out_dir, domain, 'icon'),
        } if result['icon'] else None,
        'logo': {
            'url': result['logo']['url'],
            'saved_to': _save_asset(result['logo'], out_dir, domain, 'logo'),
        } if result['logo'] else None,
        'cover_image': {
            'url': result['cover_image']['url'],
            'saved_to': _save_asset(result['cover_image'], out_dir, domain, 'cover'),
        } if result['cover_image'] else None,
        'brand_colors': result['brand_colors'],
    }, indent=2))


if __name__ == '__main__':
    main()
