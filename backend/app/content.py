import hashlib
from urllib.parse import parse_qs, urlencode, urlparse

import bleach
from bs4 import BeautifulSoup


def article_key(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname != "mp.weixin.qq.com":
        raise ValueError("只接受 mp.weixin.qq.com 文章链接")
    query = parse_qs(parsed.query)
    if all(query.get(key) for key in ("__biz", "mid", "idx")):
        identity = urlencode({key: query[key][0] for key in ("__biz", "mid", "idx")})
    else:
        identity = (
            parsed.path.rstrip("/")
            + "?"
            + urlencode(
                {
                    key: value[0]
                    for key, value in sorted(query.items())
                    if key not in ("scene", "from", "isappinstalled", "chksm")
                }
            )
        )
    return hashlib.sha256(identity.encode()).hexdigest()


def clean_content(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "iframe", "form", "input", "object", "embed"]):
        node.decompose()
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src", "")
        parsed = urlparse(src)
        if parsed.scheme not in ("http", "https") or not (parsed.hostname or "").endswith(
            (".qpic.cn", ".qlogo.cn")
        ):
            img.decompose()
        else:
            img.attrs = {
                "src": src,
                "alt": img.get("alt", ""),
                "loading": "lazy",
                "referrerpolicy": "no-referrer",
            }
    cleaned = bleach.clean(
        str(soup),
        tags=[
            "p",
            "section",
            "div",
            "span",
            "h1",
            "h2",
            "h3",
            "h4",
            "strong",
            "b",
            "em",
            "i",
            "u",
            "blockquote",
            "ul",
            "ol",
            "li",
            "br",
            "hr",
            "a",
            "img",
            "pre",
            "code",
            "table",
            "thead",
            "tbody",
            "tr",
            "td",
            "th",
        ],
        attributes={"a": ["href", "title"], "img": ["src", "alt", "loading", "referrerpolicy"]},
        protocols=["https", "http"],
        strip=True,
    )
    return cleaned, BeautifulSoup(cleaned, "html.parser").get_text("\n", strip=True)
