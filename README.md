# Funnel Landing Agent

Streamlit tool that generates static landing pages from a brief and publishes
them to GitHub Pages.

## Stack

- **UI**: Streamlit (deployed on Streamlit Community Cloud)
- **Copy + HTML**: Claude (Anthropic API) — single-file Tailwind via CDN
- **Hero image**: Higgsfield Nano Banana Pro (cookie auth)
- **Hosting**: GitHub Pages (free) → custom subdomain via DNS CNAME
- **Logging**: Google Apps Script webhook → Google Sheet (free)

## Output layout

In the target repo (e.g. `funnel-landing-pages`):

```
pages/
  <slug-1>/
    index.html
    hero.jpg
  <slug-2>/
    index.html
    hero.jpg
```

Each landing is reachable at:

- `https://landing.example.com/pages/<slug>/` (with custom domain)
- `https://<user>.github.io/<repo>/pages/<slug>/` (default)

## Setup

1. `cp .env.example .env` and fill in API keys + GitHub token + Higgsfield cookies
2. `python -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `streamlit run app.py`

## DNS configuration (one-time)

In SiteGround DNS for `leonemasterschool.it`:

- **Type**: CNAME
- **Name**: `landing`
- **Value**: `salvotrifiro96-ux.github.io`
- **TTL**: default

In the `funnel-landing-pages` repo, add a `CNAME` file at the root containing
`landing.leonemasterschool.it`. The tool sets this up on first publish via the
Pages API.

## Streamlit Cloud deployment

After pushing this repo to GitHub:

1. Go to https://share.streamlit.io
2. Connect the `funnel-landing-agent` repo
3. Paste the contents of `.streamlit/secrets.toml.example` filled with real values
4. Deploy
