#!/usr/bin/env python3
"""Web UI for extract_site_branding.py — enter a URL, see the logo and colors.

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
    max-width: 640px;
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
  .card {
    background: #fff;
    border: 1px solid #e5e5e5;
    border-radius: 12px;
    padding: 24px;
    margin-top: 16px;
  }
  .logo-box {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 140px;
    background:
      linear-gradient(45deg, #eee 25%, transparent 25%),
      linear-gradient(-45deg, #eee 25%, transparent 25%),
      linear-gradient(45deg, transparent 75%, #eee 75%),
      linear-gradient(-45deg, transparent 75%, #eee 75%);
    background-size: 16px 16px;
    background-position: 0 0, 0 8px, 8px -8px, -8px 0px;
    border-radius: 8px;
    margin-bottom: 20px;
  }
  .logo-box img { max-height: 100px; max-width: 90%; }
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
  .meta { color: #888; font-size: 0.85rem; margin-top: 16px; word-break: break-all; }
</style>
</head>
<body>
  <h1>Site Branding Extractor</h1>
  <p class="sub">Enter a website URL to pull its logo and dominant colors.</p>
  <form method="post">
    <input type="text" name="url" placeholder="example.com" value="{{ url or '' }}" autofocus>
    <button type="submit">Extract</button>
  </form>

  {% if error %}
    <p class="error">{{ error }}</p>
  {% endif %}

  {% if result %}
  <div class="card">
    <div class="logo-box">
      <img src="data:{{ result.logo_content_type }};base64,{{ result.logo_b64 }}">
    </div>
    <div class="swatches">
      {% for color in result.dominant_colors %}
      <div class="swatch">
        <div class="chip" style="background:{{ color }}"></div>
        <code>{{ color }}</code>
      </div>
      {% endfor %}
    </div>
    <p class="meta">Logo source: {{ result.logo_url }}</p>
  </div>
  {% endif %}
</body>
</html>
"""


@app.route('/', methods=['GET', 'POST'])
def index():
    url = None
    result = None
    error = None

    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        if url:
            try:
                data = analyze_site(url, n_colors=5)
                result = {
                    'logo_content_type': data['logo_content_type'],
                    'logo_b64': base64.b64encode(data['logo_bytes']).decode('ascii'),
                    'dominant_colors': data['dominant_colors'],
                    'logo_url': data['logo_url'],
                }
            except ValueError:
                error = f"Couldn't find a logo on {url}."
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
