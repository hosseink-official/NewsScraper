"""News article scraper that extracts structured data from news websites using XPath selectors."""

from __future__ import annotations

import json
import logging
import os
import sys
from urllib.parse import urljoin
from dataclasses import dataclass, field
from typing import Any

from lxml import html
from playwright.sync_api import sync_playwright


@dataclass
class Article:
    index: int = 0
    title: str = ""
    content_summary: str = ""
    pic: str = ""
    picCaption: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)
    time: str = ""
    main: str = ""
    link: str = ""
    page_url: str = ""
    title_font_size: str = ""
    pic_caption_font_size: str = ""


@dataclass
class SiteConfig:
    url: str
    selectors: list[dict[str, Any]]

input_path = sys.argv[1] if len(sys.argv) > 1 else "."
output_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join('.', 'output')


class NewsScraper:
    STEALTH_SCRIPT = """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });
        window.chrome = { runtime: {} };
    """

    def __init__(self, config_dir: str = input_path) -> None:
        self.config_dir: str = config_dir
        self._logger = logging.getLogger(f"{__name__}.{type(self).__name__}")
        self._setup_logging()
        self._playwright = None
        self._browser = None
        self._page = None

    def _setup_logging(self) -> None:
        self._logger.setLevel(logging.INFO)
        logfile = os.path.abspath(os.path.join(self.config_dir, "scrapper.log"))
        if any(
            isinstance(h, logging.FileHandler)
            and os.path.abspath(h.baseFilename) == logfile
            for h in self._logger.handlers
        ):
            return
        fh = logging.FileHandler(logfile)
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        self._logger.addHandler(fh)

    def _ensure_browser(self):
        if self._page is not None:
            return self._page
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
            ],
        )
        context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": "https://www.google.com/",
            },
        )
        context.add_init_script(self.STEALTH_SCRIPT)
        self._page = context.new_page()
        return self._page

    def list_configs(self) -> list[str]:
        if not os.path.isdir(self.config_dir):
            raise ValueError(f"Directory does not exist: {self.config_dir}")
        return sorted(
            f for f in os.listdir(self.config_dir)
            if f.lower().endswith(".json") and os.path.isfile(os.path.join(self.config_dir, f))
        )

    def load_config(self, filename: str) -> SiteConfig:
        filepath = os.path.join(self.config_dir, filename)
        self._logger.info(f"Loading config from {filepath}")
        with open(filepath, encoding="utf-8") as f:
            raw = json.load(f)
        return SiteConfig(url=raw["url"], selectors=raw["data"])

    def fetch_page(self, url: str) -> html.HtmlElement:
        self._logger.info(f"Fetching {url}")
        page = self._ensure_browser()
        page.goto(url, wait_until="networkidle", timeout=60000)
        content = page.content()
        return html.fromstring(content)

    def _extract_field(self, tree: html.HtmlElement, xpath_expr: str, field_name: str) -> str:
        els = tree.xpath(xpath_expr)
        if not els:
            return ""
        if field_name == "pic":
            return els[0].get("src", "").strip()
        if field_name == "link":
            return els[0].get("href", "").strip()
        return els[0].text_content().strip()

    def _extract_font_size_by_xpath(self, xpath: str) -> str:
        if not xpath or self._page is None:
            return ""
        try:
            escaped = xpath.replace("'", "\\'")
            return self._page.evaluate(f"""() => {{
                const el = document.evaluate(
                    '{escaped}', document, null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
                if (!el) return '';
                const s = window.getComputedStyle(el);
                return s.fontSize;
            }}""")
        except Exception:
            return ""

    def _extract_field_list(self, tree: html.HtmlElement, xpath_list: list[str]) -> list[str]:
        return [
            els[0].text_content().strip()
            for xp in xpath_list
            if xp and (els := tree.xpath(xp))
        ]

    def _parse_article(self, tree: html.HtmlElement, selectors: dict[str, Any], idx: int) -> Article:
        article = Article(index=idx + 1)
        for field, xpath in selectors.items():
            if not xpath or (isinstance(xpath, list) and not xpath):
                continue
            try:
                if isinstance(xpath, list):
                    setattr(article, field, self._extract_field_list(tree, xpath))
                else:
                    setattr(article, field, self._extract_field(tree, xpath, field))
            except Exception:
                self._logger.warning(f"XPath failed for {field} at index {idx}")
                setattr(article, field, [] if isinstance(xpath, list) else "")

        title_xp = selectors.get("title")
        if title_xp and isinstance(title_xp, str):
            article.title_font_size = self._extract_font_size_by_xpath(title_xp)

        caption_xp = selectors.get("picCaption")
        if caption_xp and isinstance(caption_xp, str):
            article.pic_caption_font_size = self._extract_font_size_by_xpath(caption_xp)

        if not article.link or not article.link.startswith("http"):
            for candidate in ["title", "content_summary", "pic", "main"]:
                xp = selectors.get(candidate)
                if not xp or not isinstance(xp, str):
                    continue
                try:
                    els = tree.xpath(xp)
                    if not els:
                        continue
                    a = els[0].xpath("./ancestor-or-self::a[1]")
                except Exception:
                    continue
                if a:
                    href = a[0].get("href", "").strip()
                    if href.startswith("//"):
                        article.link = "https:" + href
                        break
                    if href.startswith("/"):
                        from urllib.parse import urljoin
                        article.link = urljoin(self._page.url, href) if self._page else href
                        break
                    if href.startswith("http"):
                        article.link = href
                        break

        return article

    def get_data(self, config: SiteConfig) -> list[Article]:
        tree = self.fetch_page(config.url)
        articles = [self._parse_article(tree, sel, i) for i, sel in enumerate(config.selectors)]
        for a in articles:
            a.page_url = config.url
        return articles

    def _fmt_preview(self, text: str, max_len: int = 80) -> str:
        return text[:max_len] if text else "N/A"

    def print_report(self, articles: list[Article], url: str) -> None:
        print(f"\n=== {url} ===")
        for a in articles[:5]:
            print(f"  [{a.index}] {self._fmt_preview(a.title)}")
            if a.content_summary:
                print(f"       {self._fmt_preview(a.content_summary, 120)}")

    def _cleanup(self):
        if self._page is not None:
            self._page.close()
            self._page = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def run(self) -> None:
        configs = self.list_configs()
        self._logger.info(f"Found {len(configs)} config file(s): {configs}")

        try:
            for name in configs:
                filepath = os.path.join(self.config_dir, name)
                try:
                    config = self.load_config(name)
                    articles = self.get_data(config)
                    self.print_report(articles, config.url)
                    self._save_json(articles, name)
                except Exception as e:
                    self._logger.error(f"Failed to scrape {filepath}: {e}")
                    print(f"Failed: {filepath} - {e}")
        finally:
            self._cleanup()

    def _save_json(self, articles: list[Article], config_name: str) -> None:
        os.makedirs(output_path, exist_ok=True)
        base_name = os.path.splitext(config_name)[0]
        timestamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = os.path.join(output_path, f"{base_name}_{timestamp}.json")
        data = [
            {
                "index": a.index,
                "title": a.title,
                "content_summary": a.content_summary,
                "pic": a.pic,
                "picCaption": a.picCaption,
                "author": a.author,
                "tags": a.tags,
                "time": a.time,
                "main": a.main,
                "link": a.link,
                "pageUrl": a.page_url,
                "titleFontSize": a.title_font_size,
                "picCaptionFontSize": a.pic_caption_font_size,
            }
            for a in articles
        ]
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._logger.info(f"Saved {len(articles)} articles to {out_file}")
        print(f"Saved: {out_file}")


if __name__ == "__main__":
    scrapper = NewsScraper()
    scrapper.run()
