#!/usr/bin/env python3
"""Web UI for extract_site_branding.py — enter a URL, see its logo, icon,
cover image, and brand colors.

Usage:
    python3 app.py
    (then open http://localhost:5050)
"""
import base64
import os

import requests
from flask import Flask, render_template_string, request

from extract_site_branding import analyze_site

app = Flask(__name__)

PAGE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Site Branding Extractor</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    max-width: 720px;
    margin: 60px auto;
    padding: 0 20px;
    background: #fafafa;
    color: #1a1a1a;
  }
  h1 { font-size: 1.4rem; margin-bottom: 4px; }
  p.sub { color: #666; margin-top: 0; }
  form { display: flex; gap: 8px; margin: 24px 0; }
  input[type=text] {
    flex: 1;
    padding: 10px 12px;
    font-size: 1rem;
    border: 1px solid #ccc;
    border-radius: 8px;
  }
  button {
    padding: 10px 18px;
    font-size: 1rem;
    border: none;
    border-radius: 8px;
    background: #1a1a1a;
    color: #fff;
    cursor: pointer;
  }
  button:hover { background: #333; }
  .assets {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
  }
  .card {
    background: #fff;
    border: 1px solid #e5e5e5;
    border-radius: 12px;
    padding: 16px;
  }
  .card h2 {
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #888;
    margin: 0 0 12px;
  }
  .image-box {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100px;
    background:
      linear-gradient(45deg, #eee 25%, transparent 25%),
      linear-gradient(-45deg, #eee 25%, transparent 25%),
      linear-gradient(45deg, transparent 75%, #eee 75%),
      linear-gradient(-45deg, transparent 75%, #eee 75%);
    background-size: 16px 16px;
    background-position: 0 0, 0 8px, 8px -8px, -8px 0px;
    border-radius: 8px;
  }
  .image-box img { max-height: 90px; max-width: 90%; object-fit: contain; }
  .image-box.missing { color: #bbb; font-size: 0.85rem; }
  .colors-card {
    background: #fff;
    border: 1px solid #e5e5e5;
    border-radius: 12px;
    padding: 24px;
    margin-top: 16px;
  }
  .swatches { display: flex; gap: 10px; flex-wrap: wrap; }
  .swatch { text-align: center; }
  .swatch .chip {
    width: 64px;
    height: 64px;
    border-radius: 8px;
    border: 1px solid rgba(0,0,0,0.08);
  }
  .swatch code { font-size: 0.8rem; display: block; margin-top: 6px; }
  .error { color: #b00020; margin-top: 16px; }
  .meta { color: #888; font-size: 0.8rem; margin-top: 10px; word-break: break-all; }
</style>
</head>
<body>
  <h1>Site Branding Extractor</h1>
  <p class="sub">Enter a website URL to pull its logo, icon, cover image, and brand colors.</p>
  <form method="post">
    <input type="text" name="url" placeholder="example.com" value="{{ url or '' }}" autofocus>
    <button type="submit">Extract</button>
  </form>

  {% if error %}
    <p class="error">{{ error }}</p>
  {% endif %}

  {% if result %}
  <div class="assets">
    <div class="card">
      <h2>Logo</h2>
      {% if result.logo %}
      <div class="image-box"><img src="data:{{ result.logo.content_type }};base64,{{ result.logo.b64 }}"></div>
      <p class="meta">{{ result.logo.url }}</p>
      {% else %}
      <div class="image-box missing">Not found</div>
      {% endif %}
    </div>
    <div class="card">
      <h2>Icon</h2>
      {% if result.icon %}
      <div class="image-box"><img src="data:{{ result.icon.content_type }};base64,{{ result.icon.b64 }}"></div>
      <p class="meta">{{ result.icon.url }}</p>
      {% else %}
      <div class="image-box missing">Not found</div>
      {% endif %}
    </div>
    <div class="card">
      <h2>Cover image</h2>
      {% if result.cover_image %}
      <div class="image-box"><img src="data:{{ result.cover_image.content_type }};base64,{{ result.cover_image.b64 }}"></div>
      <p class="meta">{{ result.cover_image.url }}</p>
      {% else %}
      <div class="image-box missing">Not found</div>
      {% endif %}
    </div>
  </div>

  <div class="colors-card">
    <h2 style="font-size:0.8rem;text-transform:uppercase;letter-spacing:0.04em;color:#888;margin:0 0 12px;">Brand colors</h2>
    <div class="swatches">
      {% for color in result.brand_colors %}
      <div class="swatch">
        <div class="chip" style="background:{{ color }}"></div>
        <code>{{ color }}</code>
      </div>
      {% endfor %}
    </div>
  </div>
  {% endif %}
</body>
</html>
"""


def _asset_for_template(asset):
    if not asset:
        return None
    return {
        'url': asset['url'],
        'content_type': asset['content_type'],
        'b64': base64.b64encode(asset['bytes']).decode('ascii'),
    }


@app.route('/', methods=['GET', 'POST'])
def index():
    url = None
    result = None
    error = None

    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        if url:
            try:
                data = analyze_site(url, n_colors=6)
                result = {
                    'logo': _asset_for_template(data['logo']),
                    'icon': _asset_for_template(data['icon']),
                    'cover_image': _asset_for_template(data['cover_image']),
                    'brand_colors': data['brand_colors'],
                }
            except ValueError:
                error = f"Couldn't find a logo, icon, or cover image on {url}."
            except requests.exceptions.ConnectionError:
                error = f"Couldn't reach {url}. Check the URL and try again."
            except requests.exceptions.Timeout:
                error = f'{url} took too long to respond.'
            except requests.exceptions.HTTPError as e:
                error = f'{url} returned an error: {e.response.status_code}.'

    return render_template_string(PAGE, url=url, result=result, error=error)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    app.run(host='0.0.0.0', port=port, debug=True)
