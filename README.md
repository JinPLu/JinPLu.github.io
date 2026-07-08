# Jinpeng Lu Homepage

This is Jinpeng Lu's static academic homepage, published with GitHub Pages at
`https://jinplu.github.io/`.

## Preview

Open `index.html` directly in a browser, or run a local server:

```bash
python3 -m http.server 4173
```

Then visit `http://127.0.0.1:4173/`.

## Contents

- `index.html` - single-page academic homepage draft.
- `assets/css/styles.css` - Hankai Liu-inspired blue-gray academic style, compact sidebar, and paper-box publication rows.
- `assets/img/profile.jpg` - resized profile photo generated from `../figure/me.jpg`.
- `assets/papers/` - original public arXiv TeX source figure assets plus full-page preview images.
- `docs/jinpeng-lu-cv-cn.pdf` - public Chinese CV PDF without private phone or QR-code contact details.
- `docs/jinpeng-lu-cv-en.pdf` - public English CV PDF without private phone or QR-code contact details.
- `tools/update_scholar_metrics.py` - updates the static Google Scholar citation badges in `index.html`.
- `.github/workflows/update-scholar-metrics.yml` - scheduled GitHub Actions workflow for the published Pages repository.

## Scholar Metrics

Google Scholar citation counts in `index.html` are static badge URLs. GitHub Pages
does not refresh them by itself. Update them before publishing with:

```bash
python3 homepage/tools/update_scholar_metrics.py
```

When this `homepage/` directory is copied to the `JinPLu.github.io` repository,
the included GitHub Actions workflow can also refresh the same badges daily and
commit only when the numbers change. It updates the total citation badge,
h-index/i10-index text, and per-paper citation badges matched by Scholar
`citation_for_view` IDs.

## Notes

- Private contact channels are intentionally not published.
- Public academic/resource links currently use the supplied Google Scholar profile and public GitHub repositories.
- Selected publications use original source-figure previews with blue venue badges and text links.
- The page is English-first and can later be ported to Hugo Blox or another static-site generator if needed.
