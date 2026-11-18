import ipaddress
import json
import re
import socket
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

PAGE_LIMIT = 3
PAGE_CHARS = 3500
SEARCH_BACKENDS = ("auto", "bing", "google")


def search_pages(query: str) -> list[dict]:
    text = query.strip()
    if not text:
        return []
    focused = _focus(text)
    pages: list[dict] = []

    # Definitions / "what is" — Wikipedia is faster and more reliable than SERP.
    if _looks_definition(text) or _looks_definition(focused):
        for term in (focused, text):
            for page in _wikipedia(term):
                pages = _merge(pages, [page])
                if len(pages) >= PAGE_LIMIT:
                    return pages[:PAGE_LIMIT]

    pages = _merge(pages, _web_search(focused) or _web_search(text))
    if len(pages) < PAGE_LIMIT:
        for term in (focused, text):
            pages = _merge(pages, _wikipedia(term))
            if len(pages) >= PAGE_LIMIT:
                break
    if not pages:
        pages = _duckduckgo_instant(focused) or _duckduckgo_instant(text)
    return pages[:PAGE_LIMIT]


def _merge(current: list[dict], extra: list[dict]) -> list[dict]:
    seen = {page["url"] for page in current}
    out = list(current)
    for page in extra:
        url = page.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(page)
        if len(out) >= PAGE_LIMIT:
            break
    return out


def _focus(query: str) -> str:
    text = query.strip()
    lowered = text.lower()
    for prefix in (
        "what is ",
        "what's ",
        "who is ",
        "define ",
        "explain ",
        "tell me about ",
    ):
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip(" ??.。！!")
    for prefix in (
        "什么是",
        "什么叫",
        "啥是",
        "介绍一下",
        "解释一下",
        "请解释",
        "讲一下",
        "说说",
    ):
        if text.startswith(prefix):
            return text[len(prefix) :].strip(" ??.。！!")
    # Long follow-up topics: keep a short searchable head.
    if len(text) > 80:
        return text[:80].strip()
    return text


def _looks_definition(query: str) -> bool:
    text = query.strip().lower()
    markers = (
        "what is ",
        "what's ",
        "define ",
        "definition",
        "什么是",
        "什么叫",
        "是什么",
        "含义",
        "定义",
    )
    return any(marker in text for marker in markers) or len(text.split()) <= 4


def _web_search(query: str) -> list[dict]:
    """Real web results via ddgs; keep snippet hits even when page extract fails."""
    hits: list[dict] = []
    for backend in SEARCH_BACKENDS:
        raw = _ddgs_text(query, backend)
        if not raw:
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            link = _result_url(str(item.get("href") or item.get("link") or ""))
            title = str(item.get("title") or "").strip() or query
            snippet = str(item.get("body") or item.get("description") or "").strip()
            if not link or not _public_http(link):
                continue
            if link in {page["url"] for page in hits}:
                continue
            body = _page_body(link, snippet, title)
            if not body:
                continue
            hits.append({"title": title[:200], "url": link, "body": body[:PAGE_CHARS]})
            if len(hits) >= PAGE_LIMIT:
                return hits
        if hits:
            return hits
    return hits


def _ddgs_text(query: str, backend: str) -> list[dict]:
    try:
        from ddgs import DDGS

        return list(DDGS().text(query, backend=backend, max_results=PAGE_LIMIT + 3))
    except Exception:
        return []


def _page_body(url: str, snippet: str, title: str = "") -> str:
    # Prefer search snippets: full-page extractors often return nav chrome.
    text = " ".join(str(snippet or "").split())
    if len(text) >= 40:
        return text[:PAGE_CHARS]
    extracted = _extract_page(url)
    if len(extracted) > len(text):
        return extracted[:PAGE_CHARS]
    if text:
        return text[:PAGE_CHARS]
    # Last resort: keep the hit with its title so search is not emptied by extractors.
    label = " ".join(str(title or "").split())
    return label[:PAGE_CHARS] if label else ""


def _extract_page(url: str) -> str:
    try:
        from ddgs import DDGS

        data = DDGS().extract(url)
    except Exception:
        return ""
    if isinstance(data, dict):
        content = str(data.get("content") or data.get("text") or "").strip()
    else:
        content = str(data or "").strip()
    if not content:
        return ""
    # Drop markdown link noise from extractors.
    content = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", content)
    content = re.sub(r"\[[^\]]*\]\[[^\]]*\]", " ", content)
    content = re.sub(r"\s+", " ", content).strip()
    # Reject obvious site-chrome dumps.
    if content.count("Training") > 8 or content.count("][") > 20:
        return ""
    return content[:PAGE_CHARS]


def _duckduckgo_instant(query: str) -> list[dict]:
    url = "https://api.duckduckgo.com/?q=" + quote(query) + "&format=json&no_html=1&skip_disambig=1"
    try:
        data = json.loads(_read(url, 400_000))
    except Exception:
        return []
    pages = []
    abstract = str(data.get("AbstractText") or "").strip()
    abstract_url = str(data.get("AbstractURL") or "")
    title = str(data.get("Heading") or query).strip() or query
    if abstract and _public_http(abstract_url):
        pages.append({"title": title[:200], "url": abstract_url, "body": abstract[:PAGE_CHARS]})
    for item in data.get("RelatedTopics") or []:
        if len(pages) >= PAGE_LIMIT or not isinstance(item, dict) or "Topics" in item:
            continue
        link = str(item.get("FirstURL") or "")
        body = str(item.get("Text") or "").strip()
        if body and _public_http(link) and link not in {page["url"] for page in pages}:
            pages.append({"title": body[:200], "url": link, "body": body[:PAGE_CHARS]})
    return pages


def _wikipedia(query: str) -> list[dict]:
    pages: list[dict] = []
    for lang in ("zh", "en"):
        for page in _wikipedia_lang(query, lang):
            if page["url"] in {item["url"] for item in pages}:
                continue
            pages.append(page)
            if len(pages) >= PAGE_LIMIT:
                return pages
    return pages


def _wikipedia_lang(query: str, lang: str) -> list[dict]:
    host = f"https://{lang}.wikipedia.org"
    url = (
        f"{host}/w/api.php?action=opensearch&limit=2&namespace=0&format=json&search="
        + quote(query)
    )
    try:
        data = json.loads(_read(url, 100_000))
    except Exception:
        return []
    if not isinstance(data, list) or len(data) < 4:
        return []
    pages = []
    for title, link in zip(data[1], data[3]):
        if len(pages) >= PAGE_LIMIT or not _public_http(str(link)):
            continue
        summary = _wiki_summary(str(title), lang)
        if not summary:
            continue
        pages.append({"title": str(title)[:200], "url": str(link), "body": summary[:PAGE_CHARS]})
    return pages


def _wiki_summary(title: str, lang: str = "en") -> str:
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/" + quote(title)
    try:
        data = json.loads(_read(url, 100_000))
    except Exception:
        return ""
    return str(data.get("extract") or "").strip()


def _result_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return target
    return href


def _read(url: str, limit: int) -> str:
    request = Request(
        url,
        headers={"User-Agent": "CitePath/1.0 (course study assistant)"},
    )
    with urlopen(request, timeout=8) as response:
        content_type = str(response.headers.get("Content-Type") or "")
        if content_type and not any(kind in content_type for kind in ("html", "text", "json")):
            return ""
        return response.read(limit).decode("utf-8", "replace")


def _public_http(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if host in {"localhost"} or host.endswith(".local"):
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    if not addresses:
        return False
    # Accept when any resolved address is public (hosts may also list link-local).
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_global:
            return True
    return False
