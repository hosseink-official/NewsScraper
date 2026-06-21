"""News article scraper that extracts structured data from news websites using XPath selectors."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from lxml import html
from playwright.async_api import async_playwright


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
    page_location: str = ""
    manual_weight: int = 0


@dataclass
class SiteConfig:
    url: str
    selectors: list[dict[str, Any]] | dict[str, Any]
    list_config: dict[str, Any] | None = None

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

    async def _get_browser(self):
        if self._browser is not None:
            return self._browser
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
            ],
        )
        return self._browser

    async def _make_page(self):
        browser = await self._get_browser()
        context = await browser.new_context(
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
        await context.add_init_script(self.STEALTH_SCRIPT)
        return await context.new_page()

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
        return SiteConfig(
            url=raw["url"],
            selectors=raw.get("data", []),
            list_config=raw.get("list"),
        )

    @staticmethod
    def _extract_field(tree: html.HtmlElement, xpath_expr: str, field_name: str) -> str:
        els = tree.xpath(xpath_expr)
        if not els:
            return ""
        if field_name == "pic":
            return els[0].get("src", "").strip()
        if field_name == "link":
            return els[0].get("href", "").strip()
        return els[0].text_content().strip()

    @staticmethod
    def _extract_field_from_item(item: html.HtmlElement, xpath_expr: str, field_name: str) -> str:
        els = item.xpath(xpath_expr)
        if not els:
            return ""
        if field_name == "pic":
            return els[0].get("src", "").strip()
        if field_name == "link":
            return els[0].get("href", "").strip()
        return els[0].text_content().strip()

    @staticmethod
    def _extract_field_list_from_item(item: html.HtmlElement, xpath_list: list[str]) -> list[str]:
        return [
            els[0].text_content().strip()
            for xp in xpath_list
            if xp and (els := item.xpath(xp))
        ]

    @staticmethod
    async def _extract_font_size_by_xpath(page, xpath: str) -> str:
        if not xpath or page is None:
            return ""
        try:
            escaped = xpath.replace("'", "\\'")
            return await page.evaluate(f"""() => {{
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

    @staticmethod
    def _extract_field_list(tree: html.HtmlElement, xpath_list: list[str]) -> list[str]:
        return [
            els[0].text_content().strip()
            for xp in xpath_list
            if xp and (els := tree.xpath(xp))
        ]

    async def _parse_article(
        self, tree: html.HtmlElement, selectors: dict[str, Any], idx: int, page
    ) -> Article:
        article = Article(index=idx + 1)
        for field, xpath in selectors.items():
            if field == "page-location":
                article.page_location = xpath if isinstance(xpath, str) else ""
                continue
            if field == "manual_weight":
                article.manual_weight = xpath if isinstance(xpath, (int, float)) else 0
                continue
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
            article.title_font_size = await self._extract_font_size_by_xpath(page, title_xp)

        caption_xp = selectors.get("picCaption")
        if caption_xp and isinstance(caption_xp, str):
            article.pic_caption_font_size = await self._extract_font_size_by_xpath(page, caption_xp)

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
                        article.link = urljoin(page.url, href) if page else href
                        break
                    if href.startswith("http"):
                        article.link = href
                        break

        return article

    async def _scroll_to_bottom(self, page, scroll_delay: float = 0.5) -> None:
        prev_height = -1
        while True:
            cur_height = await page.evaluate("document.body.scrollHeight")
            if cur_height == prev_height:
                break
            prev_height = cur_height
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(int(scroll_delay * 1000))

    async def _parse_articles_from_container(
        self, tree: html.HtmlElement, cfg: dict[str, Any], page, page_url: str
    ) -> list[Article]:
        container_xp = cfg["container"]
        item_xp = cfg.get("item", "./li")
        fields = cfg["fields"]
        containers = tree.xpath(container_xp)
        if not containers:
            self._logger.warning(f"Container not found: {container_xp}")
            return []
        items = []
        for c in containers:
            items.extend(c.xpath(item_xp))
        articles = []
        for i, item in enumerate(items):
            article = Article(index=i + 1)
            for field, xpath in fields.items():
                if field == "page-location":
                    article.page_location = xpath if isinstance(xpath, str) else ""
                    continue
                if field == "manual_weight":
                    article.manual_weight = xpath if isinstance(xpath, (int, float)) else 0
                    continue
                if not xpath or (isinstance(xpath, list) and not xpath):
                    continue
                try:
                    if isinstance(xpath, list):
                        setattr(article, field, self._extract_field_list_from_item(item, xpath))
                    else:
                        setattr(article, field, self._extract_field_from_item(item, xpath, field))
                except Exception:
                    self._logger.warning(f"Field failed for {field} at index {i}")
                    setattr(article, field, [] if isinstance(xpath, list) else "")
            article.page_url = page_url
            if not article.link or not article.link.startswith("http"):
                for candidate in ["title", "content_summary", "pic", "main"]:
                    xp = fields.get(candidate)
                    if not xp or not isinstance(xp, str):
                        continue
                    try:
                        els = item.xpath(xp)
                        if not els:
                            continue
                        a = els[0].xpath("./ancestor-or-self::a[1]")
                        if not a:
                            a = els[0].xpath(".//a[1]")
                    except Exception:
                        continue
                    if a:
                        href = a[0].get("href", "").strip()
                        if href.startswith("//"):
                            article.link = "https:" + href
                            break
                        if href.startswith("/"):
                            article.link = urljoin(page_url, href) if page else href
                            break
                        if href.startswith("http"):
                            article.link = href
                            break
            articles.append(article)
        self._logger.info(f"Found {len(articles)} articles via container discovery")
        return articles

    async def get_data(self, config: SiteConfig, page) -> list[Article]:
        self._logger.info(f"Fetching {config.url}")
        await page.goto(config.url, wait_until="networkidle", timeout=60000)
        await self._scroll_to_bottom(page)
        content = await page.content()
        tree = html.fromstring(content)
        articles: list[Article] = []
        for i, sel in enumerate(config.selectors):
            a = await self._parse_article(tree, sel, i, page)
            a.page_url = config.url
            articles.append(a)
        if config.list_config:
            list_articles = await self._parse_articles_from_container(tree, config.list_config, page, config.url)
            list_articles = [a for a in list_articles if a.title or a.content_summary or a.main]
            offset = len(articles)
            for a in list_articles:
                a.index = offset + a.index
            articles.extend(list_articles)
        return articles

    @staticmethod
    def _fmt_preview(text: str, max_len: int = 80) -> str:
        return text[:max_len] if text else "N/A"

    @staticmethod
    def print_report(articles: list[Article], url: str) -> None:
        print(f"\n=== {url} ===")
        for a in articles[:5]:
            print(f"  [{a.index}] {NewsScraper._fmt_preview(a.title)}")
            if a.content_summary:
                print(f"       {NewsScraper._fmt_preview(a.content_summary, 120)}")

    async def _process_one_config(self, name: str) -> None:
        filepath = os.path.join(self.config_dir, name)
        try:
            config = self.load_config(name)
            page = await self._make_page()
            try:
                articles = await self.get_data(config, page)
                self.print_report(articles, config.url)
                await self._save_json(articles, name)
            finally:
                await page.close()
        except Exception as e:
            self._logger.error(f"Failed to scrape {filepath}: {e}")
            print(f"Failed: {filepath} - {e}")

    async def run(self) -> None:
        configs = self.list_configs()
        self._logger.info(f"Found {len(configs)} config file(s): {configs}")
        try:
            await asyncio.gather(*(self._process_one_config(n) for n in configs))
        finally:
            await self._cleanup()

    async def _save_json(self, articles: list[Article], config_name: str) -> None:
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
                "page-location": a.page_location,
                "manual_weight": a.manual_weight,
            }
            for a in articles
        ]
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._logger.info(f"Saved {len(articles)} articles to {out_file}")
        print(f"Saved: {out_file}")

    async def _cleanup(self):
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


if __name__ == "__main__":
    scrapper = NewsScraper()
    asyncio.run(scrapper.run())
