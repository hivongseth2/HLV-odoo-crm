import logging
import re
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup, Comment

from odoo import api, models

_logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}

REQUEST_TIMEOUT = 15

# Tags thường chứa noise (menu, sidebar, quảng cáo...)
NOISE_SELECTORS = [
    "script", "style", "noscript", "iframe",
    "nav", "footer", "header",
    "aside",
    ".menu", ".nav", ".navbar", ".navigation",
    ".sidebar", ".side-bar",
    ".breadcrumb", ".breadcrumbs",
    ".advertisement", ".ads", ".ad-wrapper",
    ".cookie", ".popup", ".modal",
    ".social-share", ".share-buttons",
    ".related-posts", ".related-products",
    ".comment", ".comments",
    "#menu", "#nav", "#sidebar", "#footer", "#header",
    "[role='navigation']", "[role='banner']", "[role='complementary']",
]

# Selectors ưu tiên cho nội dung chính (theo thứ tự ưu tiên)
CONTENT_SELECTORS = [
    # Product detail pages (e-commerce)
    ".product-detail", ".product-info", ".product-content",
    ".product-description", ".product_detail", ".product_info",
    "#product-detail", "#product-info",
    ".woocommerce-product-details__short-description",
    ".woocommerce-Tabs-panel", ".tab-content",
    # Article / Blog
    "article", ".post-content", ".entry-content", ".article-content",
    ".post-body", ".article-body", ".blog-content",
    # Generic content
    "main", "[role='main']",
    ".main-content", ".page-content", "#main-content",
    ".content", "#content",
    ".container .row",
]


class LLMToolWebSearch(models.Model):
    _inherit = "llm.tool"

    @api.model
    def _get_available_implementations(self):
        implementations = super()._get_available_implementations()
        return implementations + [("hard_search", "Hard Search")]

    def get_input_schema(self):
        schema = super().get_input_schema()
        if self.implementation == "hard_search":
            sites = self.env["llm.web.search.site"].sudo().search([("active", "=", True)])
            if sites:
                site_descriptions = ", ".join(
                    f"'{s.name}' ({self.env['llm.web.search.site']._get_domain_from_url(s.url)})"
                    for s in sites
                )
                if "properties" in schema and "site_domain" in schema["properties"]:
                    schema["properties"]["site_domain"]["description"] = (
                        f"Domain cụ thể để tìm kiếm (để trống = tìm tất cả). "
                        f"Các site có sẵn: {site_descriptions}"
                    )
        return schema

    # ----------------------------------------------------------------
    # Main tool method
    # ----------------------------------------------------------------
    def hard_search_execute(
        self,
        query: str,
        site_domain: str = "",
        max_results: int = 5,
    ) -> dict[str, Any]:
        """
        Tìm kiếm và trích xuất nội dung từ các website được cấu hình.

        Sử dụng công cụ này khi cần:
        - Tìm kiếm sản phẩm, bài viết, thông tin trên các website của công ty
        - Trả lời câu hỏi về sản phẩm hoặc dịch vụ từ website
        - Lấy thông tin cập nhật từ các trang web

        Parameters:
            query: Từ khóa tìm kiếm (bắt buộc). VD: "máy lọc nước", "sản phẩm mới"
            site_domain: Domain cụ thể để giới hạn tìm kiếm. VD: "ketnoitieudung.vn". Để trống để tìm trên tất cả website.
            max_results: Số kết quả tối đa trả về (1-10, mặc định 5).
        """
        max_results = max(1, min(10, max_results))

        allowed_sites = self._get_allowed_sites()
        if not allowed_sites:
            return {"error": "Chưa có website nào được cấu hình."}

        # Filter by specific domain if provided
        if site_domain:
            allowed_sites = [s for s in allowed_sites if site_domain in s["domain"]]
            if not allowed_sites:
                available = ", ".join(s["domain"] for s in self._get_allowed_sites())
                return {"error": f"Domain '{site_domain}' không có. Các domain: {available}"}

        # === Strategy: search EACH site separately to ensure coverage ===
        all_results = []
        results_per_site = max(max(2, max_results // len(allowed_sites)), 3)

        for site in allowed_sites:
            site_results = self._search_google(query, site, results_per_site)
            if not site_results:
                site_results = self._search_duckduckgo(query, site, results_per_site)
            if not site_results:
                site_results = self._search_on_site(query, site, results_per_site)
            if not site_results:
                site_results = self._fallback_crawl_links(query, site, results_per_site)

            for r in site_results:
                r["source_site"] = site["name"]
            all_results.extend(site_results)

        if not all_results:
            return {
                "query": query,
                "results": [],
                "message": "Không tìm thấy kết quả phù hợp.",
            }

        # Deduplicate by URL
        seen_urls = set()
        unique_results = []
        for r in all_results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                unique_results.append(r)

        # Limit results
        unique_results = unique_results[:max_results]

        # Fetch full content for each result
        enriched_results = []
        for result in unique_results:
            content = self._fetch_page_content(result["url"])
            enriched_results.append({
                "title": result.get("title", ""),
                "url": result["url"],
                "source_site": result.get("source_site", ""),
                "snippet": result.get("snippet", ""),
                "content": content[:4000] if content else result.get("snippet", ""),
            })

        return {
            "query": query,
            "sites_searched": [s["domain"] for s in allowed_sites],
            "total_results": len(enriched_results),
            "results": enriched_results,
        }

    # ----------------------------------------------------------------
    # Private helpers
    # ----------------------------------------------------------------
    def _get_allowed_sites(self):
        """Load danh sách website được phép."""
        sites = self.env["llm.web.search.site"].sudo().search([("active", "=", True)])
        result = []
        for site in sites:
            domain = self.env["llm.web.search.site"]._get_domain_from_url(site.url)
            result.append({
                "id": site.id,
                "name": site.name,
                "url": site.url,
                "domain": domain,
                "description": site.description or "",
            })
        return result

    # ----------------------------------------------------------------
    # Search methods (each searches ONE site at a time)
    # ----------------------------------------------------------------
    def _search_google(self, query, site, max_results):
        """Search Google for a specific site."""
        results = []
        search_query = f"site:{site['domain']} {query}"
        try:
            url = f"https://www.google.com/search?q={quote_plus(search_query)}&num={max_results}&hl=vi"
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for g_div in soup.select("div.g, div[data-hveid]"):
                a_tag = g_div.select_one("a[href]")
                if not a_tag:
                    continue
                href = a_tag.get("href", "")
                if not href.startswith("http"):
                    continue
                if not self._is_allowed_url(href, [site]):
                    continue

                title_tag = g_div.select_one("h3")
                title = title_tag.get_text(strip=True) if title_tag else a_tag.get_text(strip=True)

                snippet = ""
                for sel in [".VwiC3b", ".lEBKkf", "span.st", ".s .st"]:
                    snip_el = g_div.select_one(sel)
                    if snip_el:
                        snippet = snip_el.get_text(strip=True)
                        break

                if title:
                    results.append({"title": title, "url": href, "snippet": snippet})
                    if len(results) >= max_results:
                        break
        except Exception as e:
            _logger.debug("Google search failed for %s: %s", site["domain"], e)

        return results

    def _search_duckduckgo(self, query, site, max_results):
        """Search DuckDuckGo for a specific site."""
        results = []
        search_query = f"site:{site['domain']} {query}"
        try:
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(search_query)}"
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for item in soup.select(".result"):
                link_tag = item.select_one(".result__a")
                snippet_tag = item.select_one(".result__snippet")
                if not link_tag:
                    continue

                href = link_tag.get("href", "")
                if "uddg=" in href:
                    parsed = urlparse(href)
                    params = parse_qs(parsed.query)
                    href = params.get("uddg", [href])[0]

                if not self._is_allowed_url(href, [site]):
                    continue

                title = link_tag.get_text(strip=True)
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

                results.append({"title": title, "url": href, "snippet": snippet})
                if len(results) >= max_results:
                    break
        except Exception as e:
            _logger.debug("DuckDuckGo search failed for %s: %s", site["domain"], e)

        return results

    def _search_on_site(self, query, site, max_results):
        """Try the site's built-in search (common patterns: ?s=, ?q=, /search?q=)."""
        results = []
        search_paths = [
            f"{site['url'].rstrip('/')}/?s={quote_plus(query)}",
            f"{site['url'].rstrip('/')}/search?q={quote_plus(query)}",
            f"{site['url'].rstrip('/')}/tim-kiem?q={quote_plus(query)}",
            f"{site['url'].rstrip('/')}/search?keyword={quote_plus(query)}",
        ]

        for search_url in search_paths:
            try:
                resp = requests.get(search_url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                # Look for product/article links in search results
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag.get("href", "")
                    text = a_tag.get_text(strip=True)
                    if not text or len(text) < 10:
                        continue

                    full_url = urljoin(site["url"], href)
                    if not self._is_allowed_url(full_url, [site]):
                        continue

                    # Skip navigation/category links (short text, generic)
                    if self._is_likely_nav_link(href, text):
                        continue

                    # Check if the link text seems related to the query
                    query_lower = query.lower()
                    text_lower = text.lower()
                    if any(w in text_lower or w in href.lower()
                           for w in query_lower.split() if len(w) > 2):
                        results.append({
                            "title": text[:200],
                            "url": full_url,
                            "snippet": "",
                        })
                        if len(results) >= max_results:
                            return results

                if results:
                    return results
            except Exception:
                continue

        return results

    def _fallback_crawl_links(self, query, site, max_results):
        """Last resort: crawl homepage for relevant links."""
        results = []
        query_words = [w.lower() for w in query.split() if len(w) > 2]
        if not query_words:
            return results

        try:
            resp = requests.get(site["url"], headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            scored_links = []
            for a_tag in soup.find_all("a", href=True):
                href = a_tag.get("href", "")
                text = a_tag.get_text(strip=True)
                if not text or len(text) < 8:
                    continue

                full_url = urljoin(site["url"], href)
                if not self._is_allowed_url(full_url, [site]):
                    continue
                if self._is_likely_nav_link(href, text):
                    continue

                combined = (text + " " + href).lower()
                score = sum(1 for w in query_words if w in combined)
                if score > 0:
                    scored_links.append((score, text, full_url))

            # Sort by relevance score
            scored_links.sort(key=lambda x: x[0], reverse=True)
            for score, text, url in scored_links[:max_results]:
                results.append({"title": text[:200], "url": url, "snippet": ""})

        except Exception as e:
            _logger.debug("Fallback crawl failed for %s: %s", site["url"], e)

        return results

    # ----------------------------------------------------------------
    # Content extraction
    # ----------------------------------------------------------------
    def _fetch_page_content(self, url):
        """Fetch and extract main content from URL, removing noise."""
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # 1. Remove all noise elements
            for selector in NOISE_SELECTORS:
                for tag in soup.select(selector):
                    tag.decompose()

            # Remove HTML comments
            for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
                comment.extract()

            # 2. Extract page title
            title = ""
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)

            # 3. Extract meta description
            meta_desc = ""
            meta = soup.find("meta", attrs={"name": "description"})
            if meta:
                meta_desc = meta.get("content", "")

            # 4. Try to find product price (e-commerce)
            price_text = self._extract_price(soup)

            # 5. Find main content using selectors
            main_el = None
            for selector in CONTENT_SELECTORS:
                main_el = soup.select_one(selector)
                if main_el:
                    # Verify it has substantial text (not just nav)
                    text = main_el.get_text(strip=True)
                    if len(text) > 100:
                        break
                    main_el = None

            if not main_el:
                main_el = soup.body

            if not main_el:
                return meta_desc or ""

            # 6. Remove remaining noise inside main content
            for tag in main_el.find_all(["ul", "div"]):
                # Remove lists that look like navigation menus (many links, short text)
                links = tag.find_all("a")
                if len(links) > 5:
                    total_text = tag.get_text(strip=True)
                    link_text = " ".join(a.get_text(strip=True) for a in links)
                    # If >70% of text is links, it's probably a menu
                    if len(link_text) > len(total_text) * 0.7:
                        tag.decompose()

            # 7. Extract text
            text = main_el.get_text(separator="\n", strip=True)

            # 8. Clean up
            lines = text.split("\n")
            clean_lines = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                # Skip very short lines that are likely nav items
                if len(line) < 3:
                    continue
                # Skip lines that are just ">" or "|" separators
                if re.match(r'^[\s>|/\\•·→←]+$', line):
                    continue
                clean_lines.append(line)

            content = "\n".join(clean_lines)
            # Remove excessive duplicate newlines
            content = re.sub(r'\n{3,}', '\n\n', content)

            # 9. Prepend useful metadata
            parts = []
            if title:
                parts.append(f"Tiêu đề: {title}")
            if price_text:
                parts.append(f"Giá: {price_text}")
            if meta_desc:
                parts.append(f"Mô tả: {meta_desc}")
            if parts:
                content = "\n".join(parts) + "\n---\n" + content

            return content.strip()

        except Exception as e:
            _logger.warning("Failed to fetch content from %s: %s", url, e)
            return ""

    def _extract_price(self, soup):
        """Try to extract product price from common selectors."""
        price_selectors = [
            ".product-price", ".price", ".product_price",
            "[itemprop='price']", ".woocommerce-Price-amount",
            ".current-price", ".sale-price", ".special-price",
            ".price-box", ".price-wrapper", "#product-price",
            ".pro-price", ".detail-price",
        ]
        for sel in price_selectors:
            el = soup.select_one(sel)
            if el:
                price = el.get_text(strip=True)
                # Must contain digits to be a real price
                if re.search(r'\d', price):
                    return price[:100]
        return ""

    # ----------------------------------------------------------------
    # Utility
    # ----------------------------------------------------------------
    def _is_allowed_url(self, url, sites):
        """Check URL thuộc domain được phép."""
        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower()
            return any(s["domain"].lower() in host for s in sites)
        except Exception:
            return False

    def _is_likely_nav_link(self, href, text):
        """Detect navigation/category links to skip."""
        href_lower = href.lower()
        text_lower = text.lower()

        # Skip common nav patterns
        nav_patterns = [
            r'^/?$', r'^/?#', r'^javascript:',
            r'/category/?$', r'/danh-muc/?$', r'/lien-he/?$',
            r'/gioi-thieu/?$', r'/about/?$', r'/contact/?$',
            r'/chinh-sach/?$', r'/dieu-khoan/?$',
        ]
        for pattern in nav_patterns:
            if re.search(pattern, href_lower):
                return True

        # Short generic text
        if len(text) < 8 and text_lower in [
            "home", "trang chủ", "liên hệ", "giới thiệu",
            "about", "contact", "menu", "đăng nhập",
        ]:
            return True

        return False
