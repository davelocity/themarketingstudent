# The Marketing Student

A static blog about marketing, leading teams, and frameworks that help you do your best work. Written by David Fallarme.

This repo replaces the old Ghost.org site at [themarketingstudent.com](https://www.themarketingstudent.com). Posts are Markdown files in git. The site is built with [Astro](https://astro.build) and meant to be hosted on Cloudflare Pages.

**About is stale.** The current `/about/` page still says David leads content marketing at On Deck. That copy was imported as-is from Ghost and will be rewritten later.

## Local development

Requires Node 22+ (see `.nvmrc`) and npm.

```bash
npm install
npm run dev
```

Then open the URL Astro prints (usually `http://localhost:4321`).

```bash
npm run build     # writes static files to dist/
npm run preview   # serve the production build locally
```

## Adding a post

1. Create a Markdown (or MDX) file in `src/content/posts/`.
2. Name it after the URL slug. `src/content/posts/daily-journal-template.md` becomes `/daily-journal-template/`.
3. Add frontmatter:

```md
---
title: A Simple Daily Journal Template That Will Kickstart Your Day
pubDate: 2017-04-15T00:00:00.000Z
description: Optional excerpt for the homepage, RSS, and social cards.
heroImage: /images/2020/09/daily-journal-template-hero.jpg
---

Your post in Markdown.
```

`heroImage` can be a local path under `public/` or a remote URL (Unsplash images from the old site are still remote). Put local images in `public/images/` and reference them as `/images/...`.

There is no tag taxonomy. Don’t add one unless you mean to.

## Deploying to Cloudflare Pages

This is a static site (`output: 'static'`). No Worker or Pages Functions are required. `wrangler.jsonc` points Cloudflare at the `dist/` folder.

**Option A — Git integration (usual path)**

1. In the Cloudflare dashboard, create a Pages project and connect this GitHub repo.
2. Build settings:
   - Framework preset: Astro
   - Build command: `npm run build`
   - Build output directory: `dist`
   - Node version: `22` (set `NODE_VERSION=22` if you need to override)
3. Production branch: `main`.

**Option B — Wrangler from this machine**

```bash
npm run deploy
```

That runs `astro build` and `wrangler pages deploy dist`. You will need to be logged in with `npx wrangler login` (or a Cloudflare API token).

## DNS cutover

`themarketingstudent.com` still lives at Namecheap and currently points at Ghost. Pointing the domain at Cloudflare happens later, after this site is deployed and checked. Do not change Namecheap DNS until that cutover.

## Import notes

Published posts and the About page were imported from the live Ghost site (74 posts in `/sitemap-posts.xml`, plus `/about/`). Images that used to live on Ghost’s CDN, and Unsplash photos used as heroes, are stored in `public/images/` and referenced as `/images/...`. The one-off importer lives at `scripts/import-ghost.py` and is not part of the build.

Two drafts from the old export — “Team with no structure” and “How to think strategically” — were not published on Ghost and are not in this repo.
