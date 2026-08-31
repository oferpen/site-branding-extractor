# Site Branding Extractor

Given a website URL, finds its logo (favicon/touch-icon first, then header
logo images, then `og:image`) and extracts its dominant colors.

## CLI

```bash
pip install -r requirements.txt
python3 extract_site_branding.py example.com --out ./output --colors 5
```

Prints JSON with the logo URL, saved file path, and a list of hex colors.

## Web UI

```bash
pip install -r requirements.txt
python3 app.py
```

Open http://localhost:5050, enter a URL, and see the logo plus color swatches.

## Notes

- SVG-only logos aren't rasterized for color extraction (Pillow doesn't
  support SVG), so the logo still downloads but color extraction is skipped.
- Some heavily JS-rendered sites don't expose a logo in server-rendered HTML;
  the tool falls back through favicon → header image → `og:image`.
