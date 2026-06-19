"""News article scraper that extracts structured data from news websites using XPath selectors."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from curl_cffi import requests
from lxml import html


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


@dataclass
class SiteConfig:
    url: str
    selectors: list[dict[str, Any]]

input_path = sys.argv[1] if len(sys.argv) > 1 else "."
output_path= sys.argv[2] if len(sys.argv) > 2 else os.path.join('.', 'output')

class NewsScraper:
    HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(self, config_dir: str = input_path) -> None:
        self.config_dir: str = config_dir
        self._logger = logging.getLogger(f"{__name__}.{type(self).__name__}")
        self._setup_logging()

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
        self._logger.info(f"Fetching {url}", )
        resp = requests.get(url, headers=self.HEADERS, impersonate="chrome124", timeout=30)
        resp.raise_for_status()
        return html.fromstring(resp.content)

    def _extract_field(self, tree: html.HtmlElement, xpath_expr: str, field_name: str) -> str:
        els = tree.xpath(xpath_expr)
        if not els:
            return ""
        if field_name == "pic":
            return els[0].get("src", "").strip()
        if field_name == "link":
            return els[0].get("href", "").strip()
        return els[0].text_content().strip()

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
        return article

    def get_data(self, config: SiteConfig) -> list[Article]:
        tree = self.fetch_page(config.url)
        return [self._parse_article(tree, sel, i) for i, sel in enumerate(config.selectors)]

    def _fmt_preview(self, text: str, max_len: int = 80) -> str:
        return text[:max_len] if text else "N/A"

    def print_report(self, articles: list[Article], url: str) -> None:
        print(f"\n=== {url} ===")
        for a in articles[:5]:
            print(f"  [{a.index}] {self._fmt_preview(a.title)}")
            if a.content_summary:
                print(f"       {self._fmt_preview(a.content_summary, 120)}")

    def run(self) -> None:
        configs = self.list_configs()
        self._logger.info(f"Found {len(configs)} config file(s): {configs}" )

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
    
    # configs = scrapper.list_configs()
    # print(configs)
    # name=configs[0]
    # filepath = os.path.join(scrapper.config_dir, name)
    # config=scrapper.load_config(name)
    # print (config.url)
    # page_data=scrapper.fetch_page(config.url)
    # print(html.tostring(page_data, pretty_print=True, encoding="unicode"))