#!/usr/bin/env python3
"""One-off importer: published Ghost posts + About → Markdown and local images."""

from __future__ import annotations

import html as htmlmod
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

import yaml
from bs4 import BeautifulSoup, NavigableString, Tag
from markdownify import markdownify as to_markdown

ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / "src" / "content" / "posts"
ABOUT_PATH = ROOT / "src" / "pages" / "about.md"
IMAGES_DIR = ROOT / "public" / "images"
SITE = "https://www.themarketingstudent.com"
UA = "TheMarketingStudentImporter/1.0 (+https://www.themarketingstudent.com)"
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
SIZE_RE = re.compile(r"/size/w\d+/")
GHOST_IMAGE_MARKERS = (
    "storage.ghost.io",
    "static.ghost.org",
    "ghost.io",
    "/content/images/",
)
SKIP_TITLES = {
    "team with no structure",
    "how to think strategically",
}
REMOTE_IMAGE_HOSTS = (
    "images.unsplash.com",
    "unsplash.com",
    "images.pexels.com",
    "i.imgur.com",
    "imgur.com",
    "pbs.twimg.com",
    "media.giphy.com",
    "www.gravatar.com",
    "gravatar.com",
)


def fetch(url: str, retries: int = 4, timeout: int = 45) -> bytes:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


def sitemap_locs(xml_bytes: bytes) -> list[str]:
    root = ET.fromstring(xml_bytes)
    return [el.text.strip() for el in root.findall("sm:url/sm:loc", SITEMAP_NS) if el.text]


def meta_content(soup: BeautifulSoup, attr: str, value: str) -> str | None:
    tag = soup.find("meta", attrs={attr: value})
    if not tag:
        return None
    content = tag.get("content")
    return htmlmod.unescape(content).strip() if content else None


def first_text(soup: BeautifulSoup, selector: str) -> str | None:
    el = soup.select_one(selector)
    if not el:
        return None
    text = el.get_text(" ", strip=True)
    return text or None


def collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_ghost_asset(url: str) -> bool:
    lower = url.lower()
    if any(host in lower for host in REMOTE_IMAGE_HOSTS):
        # Unsplash sometimes sits behind Ghost's image proxy; treat as remote.
        if "unsplash" in lower:
            return False
        if "gravatar" in lower:
            return False
    return any(marker in lower for marker in GHOST_IMAGE_MARKERS)


def canonical_image_relpath(url: str) -> str | None:
    parsed = urlparse(url)
    path = SIZE_RE.sub("/", parsed.path)
    marker = "/content/images/"
    idx = path.find(marker)
    if idx == -1:
        return None
    rel = path[idx + len(marker) :].lstrip("/")
    return rel or None


def absolutize(url: str, base: str) -> str:
    url = htmlmod.unescape(url).strip()
    if url.startswith("//"):
        return "https:" + url
    return urljoin(base, url)


def strip_ref_query(url: str) -> str:
    parsed = urlparse(url)
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() != "ref" or "themarketingstudent" not in v.lower()
    ]
    return urlunparse(parsed._replace(query=urlencode(query)))


def rewrite_site_link(url: str) -> str:
    url = strip_ref_query(htmlmod.unescape(url).strip())
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host in {"themarketingstudent.com", ""}:
        path = parsed.path or "/"
        if not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
            path += "/"
        return path + (f"#{parsed.fragment}" if parsed.fragment else "")
    return url


def unwrap_nested_formatting(soup: Tag) -> None:
    changed = True
    while changed:
        changed = False
        for tag in list(soup.find_all(["strong", "b", "em", "i"])):
            parent = tag.parent
            if isinstance(parent, Tag) and parent.name == tag.name:
                tag.unwrap()
                changed = True
        for heading in soup.find_all(re.compile(r"^h[1-6]$")):
            children = [c for c in heading.children if not (isinstance(c, NavigableString) and not str(c).strip())]
            if len(children) == 1 and isinstance(children[0], Tag) and children[0].name in {"strong", "b", "em", "i"}:
                children[0].unwrap()
                changed = True


def simplify_images_and_links(soup: Tag, page_url: str, image_urls: set[str]) -> None:
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    for img in soup.find_all("img"):
        src = img.get("src")
        if not src:
            img.decompose()
            continue
        src = absolutize(src, page_url)
        alt = img.get("alt") or ""
        if isinstance(alt, list):
            alt = " ".join(alt)
        fig = img.find_parent("figure")
        if fig and not alt:
            cap = fig.find("figcaption")
            if cap:
                alt = cap.get_text(" ", strip=True)
        img.attrs = {"src": src, "alt": alt}
        if is_ghost_asset(src):
            image_urls.add(src)

    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if not href:
            continue
        href = rewrite_site_link(absolutize(href, page_url))
        new_attrs = {"href": href}
        if href.startswith("http"):
            new_attrs["rel"] = "noopener noreferrer"
        anchor.attrs = new_attrs


def html_to_markdown(body: Tag) -> str:
    unwrap_nested_formatting(body)
    text = to_markdown(str(body), heading_style="ATX", bullets="-", strip=["span", "div"])
    while "****" in text:
        text = text.replace("****", "**")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.replace("\\-", "-")
    return text.strip() + "\n"


def excerpt_from(body: Tag, og_description: str | None) -> str:
    if og_description:
        cleaned = collapse_ws(og_description)
        if len(cleaned) > 40:
            if len(cleaned) > 280:
                cut = cleaned[:277].rsplit(" ", 1)[0]
                return cut.rstrip(".,;:") + "…"
            return cleaned
    parts: list[str] = []
    for p in body.find_all("p"):
        t = collapse_ws(p.get_text(" ", strip=True))
        if t:
            parts.append(t)
        if sum(len(x) for x in parts) >= 180:
            break
    text = " ".join(parts)
    if len(text) > 280:
        text = text[:277].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
    return text


def dump_frontmatter(data: dict) -> str:
    dumped = yaml.dump(
        data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=88,
    )
    return f"---\n{dumped}---\n"


def parse_post(url: str, html: str, image_urls: set[str]) -> dict | None:
    soup = BeautifulSoup(html, "lxml")
    title = meta_content(soup, "property", "og:title") or first_text(soup, "h1.single-title")
    if not title:
        raise ValueError(f"No title for {url}")
    if title.strip().lower() in SKIP_TITLES:
        print(f"skip draft title: {title}", file=sys.stderr)
        return None

    pub = meta_content(soup, "property", "article:published_time")
    updated = meta_content(soup, "property", "article:modified_time")
    og_desc = meta_content(soup, "property", "og:description")
    hero = meta_content(soup, "property", "og:image")
    body = soup.select_one("div.single-content")
    if body is None:
        raise ValueError(f"No body for {url}")

    simplify_images_and_links(body, url, image_urls)
    if hero:
        hero = absolutize(hero, url)
        if is_ghost_asset(hero):
            image_urls.add(hero)

    markdown = html_to_markdown(body)
    slug = urlparse(url).path.strip("/")
    return {
        "slug": slug,
        "title": title,
        "pubDate": pub,
        "updatedDate": updated if updated and updated != pub else None,
        "description": excerpt_from(body, og_desc),
        "heroImage": hero,
        "markdown": markdown,
        "is_about": slug == "about",
    }


def collect_image_refs(markdown: str, hero: str | None) -> list[str]:
    urls = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown)
    if hero:
        urls.append(hero)
    return urls


def download_images(urls: set[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    unique: dict[str, str] = {}
    for url in urls:
        rel = canonical_image_relpath(url)
        if not rel:
            print(f"warn: could not map image {url}", file=sys.stderr)
            continue
        download_url = SIZE_RE.sub("/", url.split("?")[0])
        unique[download_url] = rel
        mapping[url] = "/images/" + rel
        mapping[download_url] = "/images/" + rel

    def one(item: tuple[str, str]) -> tuple[str, str, bool]:
        url, rel = item
        dest = IMAGES_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 0:
            return url, rel, True
        data = fetch(url)
        dest.write_bytes(data)
        return url, rel, False

    print(f"Downloading {len(unique)} Ghost images…")
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(one, item) for item in unique.items()]
        for fut in as_completed(futures):
            url, rel, cached = fut.result()
            status = "cached" if cached else "saved"
            print(f"  {status} {rel}")
    return mapping


def apply_image_map(text: str, mapping: dict[str, str]) -> str:
    # Longest URLs first so sized variants rewrite before prefixes collide.
    for remote, local in sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True):
        text = text.replace(remote, local)
    return text


def write_post(entry: dict, mapping: dict[str, str]) -> None:
    hero = entry["heroImage"]
    if hero:
        hero = mapping.get(hero, hero)
        # Sized Ghost URLs may not be exact mapping keys.
        rel = canonical_image_relpath(hero) if is_ghost_asset(hero) else None
        if rel:
            hero = "/images/" + rel
    markdown = apply_image_map(entry["markdown"], mapping)
    # Catch any leftover ghost CDN refs that slipped through.
    markdown = re.sub(
        r"https://storage\.ghost\.io/[^)\s]+/content/images/(?:size/w\d+/)?",
        "/images/",
        markdown,
    )
    markdown = markdown.replace("https://www.themarketingstudent.com/content/images/", "/images/")

    fm = {
        "title": entry["title"],
        "pubDate": entry["pubDate"],
    }
    if entry["updatedDate"]:
        fm["updatedDate"] = entry["updatedDate"]
    if entry["description"]:
        fm["description"] = entry["description"]
    if hero:
        fm["heroImage"] = hero

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    path = POSTS_DIR / f"{entry['slug']}.md"
    path.write_text(dump_frontmatter(fm) + "\n" + markdown, encoding="utf-8")


def write_about(entry: dict, mapping: dict[str, str]) -> None:
    hero = entry["heroImage"]
    if hero:
        rel = canonical_image_relpath(hero) if is_ghost_asset(hero) else None
        hero = ("/images/" + rel) if rel else mapping.get(hero, hero)
    markdown = apply_image_map(entry["markdown"], mapping)
    markdown = re.sub(
        r"https://storage\.ghost\.io/[^)\s]+/content/images/(?:size/w\d+/)?",
        "/images/",
        markdown,
    )
    fm = {
        "layout": "../layouts/Page.astro",
        "title": "About",
        "description": entry["description"],
    }
    if hero:
        fm["heroImage"] = hero
    ABOUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ABOUT_PATH.write_text(dump_frontmatter(fm) + "\n" + markdown, encoding="utf-8")


def main() -> None:
    print("Fetching sitemaps…")
    posts_xml = fetch(f"{SITE}/sitemap-posts.xml")
    pages_xml = fetch(f"{SITE}/sitemap-pages.xml")
    post_urls = sitemap_locs(posts_xml)
    page_urls = [u for u in sitemap_locs(pages_xml) if urlparse(u).path.strip("/") == "about"]
    print(f"Sitemap posts: {len(post_urls)}")
    print(f"About pages: {page_urls}")

    urls = post_urls + page_urls
    html_by_url: dict[str, str] = {}

    def fetch_page(url: str) -> tuple[str, str]:
        return url, fetch(url).decode("utf-8", "replace")

    print(f"Fetching {len(urls)} HTML pages…")
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_page, url) for url in urls]
        for fut in as_completed(futures):
            url, html = fut.result()
            html_by_url[url] = html
            print(f"  fetched {urlparse(url).path}")

    image_urls: set[str] = set()
    entries: list[dict] = []
    about_entry: dict | None = None
    for url in urls:
        entry = parse_post(url, html_by_url[url], image_urls)
        if entry is None:
            continue
        if entry["is_about"]:
            about_entry = entry
        else:
            entries.append(entry)

    print(f"Parsed posts: {len(entries)}")
    mapping = download_images(image_urls)

    for entry in entries:
        write_post(entry, mapping)
    if about_entry:
        write_about(about_entry, mapping)

    years = []
    for entry in entries:
        if entry["pubDate"]:
            years.append(int(entry["pubDate"][:4]))
    leftover = []
    for path in POSTS_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if "ghost.io" in text or "/content/images/" in text:
            leftover.append(path.name)
    about_text = ABOUT_PATH.read_text(encoding="utf-8") if ABOUT_PATH.exists() else ""
    if "ghost.io" in about_text:
        leftover.append("about.md")

    summary = {
        "posts": len(entries),
        "about": bool(about_entry),
        "images": len({v for v in mapping.values()}),
        "year_min": min(years) if years else None,
        "year_max": max(years) if years else None,
        "leftover_ghost_refs": leftover,
        "slugs": sorted(e["slug"] for e in entries),
    }
    print(json.dumps({k: v for k, v in summary.items() if k != "slugs"}, indent=2))
    if leftover:
        print("WARNING leftover Ghost URLs:", leftover, file=sys.stderr)
        sys.exit(1)
    if len(entries) != 74:
        print(f"WARNING expected 74 posts, got {len(entries)}", file=sys.stderr)


if __name__ == "__main__":
    main()
