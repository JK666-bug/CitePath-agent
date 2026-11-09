import ipaddress
import json
import socket
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

PAGE_LIMIT = 2
PAGE_CHARS = 3500


def search_pages(query: str) -> list[dict]:
    text = query.strip()
    if not text:
        return []
    pages = _duckduckgo(text) or _wikipedia(text) or _wikipedia(_focus(text))
    return pages[:PAGE_LIMIT]


def _focus(query: str) -> str:
    text = query.strip()
    lowered = text.lower()
    for prefix in ("what is ", "what's ", "who is ", "define "):
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip(" ?.")
    return text


def _duckduckgo(query: str) -> list[dict]:
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
    url = (
        "https://en.wikipedia.org/w/api.php?action=opensearch&limit=2&namespace=0&format=json&search="
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
        summary = _wiki_summary(str(title))
        if not summary:
            continue
        pages.append({"title": str(title)[:200], "url": str(link), "body": summary[:PAGE_CHARS]})
    return pages


def _wiki_summary(title: str) -> str:
    url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(title)
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
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True
