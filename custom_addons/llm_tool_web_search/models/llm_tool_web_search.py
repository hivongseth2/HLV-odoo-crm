import logging
import re
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from odoo import api, models

_logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}

REQUEST_TIMEOUT = 15


class LLMToolWebSearch(models.Model):
    _inherit = "llm.tool"

    @api.model
    def _get_available_implementations(self):
        implementations = super()._get_available_implementations()
        return implementations + [("web_search", "Web Search")]

    def get_input_schema(self):
        schema = super().get_input_schema()
        if self.implementation == "web_search":
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
    def web_search_execute(
        self,
        query: str,
        site_domain: str = "",
        max_results: int = 3,
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
            max_results: Số kết quả tối đa trả về (1-5, mặc định 3).
        """
        max_results = max(1, min(5, max_results))

        allowed_sites = self._get_allowed_sites()
        if not allowed_sites:
            return {"error": "Chưa có website nào được cấu hình. Vui lòng thêm website trong cấu hình."}

        # Filter by specific domain if provided
        if site_domain:
            allowed_sites = [s for s in allowed_sites if site_domain in s["domain"]]
            if not allowed_sites:
                available = ", ".join(s["domain"] for s in self._get_allowed_sites())
                return {"error": f"Domain '{site_domain}' không nằm trong danh sách cho phép. Các domain có sẵn: {available}"}

        # Search using DuckDuckGo with site: operator
        search_results = self._search_duckduckgo(query, allowed_sites, max_results)

        if not search_results:
            # Fallback: try fetching site directly and searching content
            search_results = self._fallback_site_search(query, allowed_sites, max_results)

        if not search_results:
            return {
                "query": query,
                "results": [],
                "message": "Không tìm thấy kết quả phù hợp.",
            }

        # Fetch full content for each result
        enriched_results = []
        for result in search_results[:max_results]:
            content = self._fetch_page_content(result["url"])
            enriched_results.append({
                "title": result.get("title", ""),
                "url": result["url"],
                "snippet": result.get("snippet", ""),
                "content": content[:3000] if content else result.get("snippet", ""),
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

    def _search_duckduckgo(self, query, sites, max_results):
        """Tìm kiếm qua DuckDuckGo HTML."""
        results = []
        site_query_parts = " OR ".join(f"site:{s['domain']}" for s in sites)
        search_query = f"{query} {site_query_parts}"

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
                # DuckDuckGo wraps URLs in redirect
                if "uddg=" in href:
                    from urllib.parse import parse_qs, urlparse as _urlparse
                    parsed = _urlparse(href)
                    params = parse_qs(parsed.query)
                    href = params.get("uddg", [href])[0]

                # Verify URL belongs to allowed domains
                if not self._is_allowed_url(href, sites):
                    continue

                title = link_tag.get_text(strip=True)
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

                results.append({
                    "title": title,
                    "url": href,
                    "snippet": snippet,
                })

                if len(results) >= max_results:
                    break

        except Exception as e:
            _logger.warning("DuckDuckGo search failed: %s", e)

        return results

    def _fallback_site_search(self, query, sites, max_results):
        """Fallback: fetch homepage / sitemap and look for relevant links."""
        results = []
        query_lower = query.lower()
        query_words = set(re.split(r'\s+', query_lower))

        for site in sites:
            if len(results) >= max_results:
                break
            try:
                resp = requests.get(site["url"], headers=HEADERS, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")

                for a_tag in soup.find_all("a", href=True):
                    href = a_tag.get("href", "")
                    text = a_tag.get_text(strip=True)
                    if not text or len(text) < 5:
                        continue

                    # Make absolute URL
                    full_url = urljoin(site["url"], href)
                    if not self._is_allowed_url(full_url, sites):
                        continue

                    # Check relevance
                    combined = (text + " " + href).lower()
                    if any(w in combined for w in query_words):
                        results.append({
                            "title": text,
                            "url": full_url,
                            "snippet": "",
                        })
                        if len(results) >= max_results:
                            break

            except Exception as e:
                _logger.warning("Fallback search failed for %s: %s", site["url"], e)

        return results

    def _fetch_page_content(self, url):
        """Fetch và trích xuất nội dung chính từ một URL."""
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Remove noise elements
            for tag in soup.select("script, style, nav, footer, header, aside, .menu, .sidebar, .advertisement, .ads, iframe, noscript"):
                tag.decompose()

            # Try to find main content area
            main = (
                soup.select_one("article")
                or soup.select_one("main")
                or soup.select_one(".post-content")
                or soup.select_one(".entry-content")
                or soup.select_one(".content")
                or soup.select_one("#content")
                or soup.body
            )

            if not main:
                return ""

            text = main.get_text(separator="\n", strip=True)
            # Clean up excessive whitespace
            text = re.sub(r'\n{3,}', '\n\n', text)
            return text.strip()

        except Exception as e:
            _logger.warning("Failed to fetch page content from %s: %s", url, e)
            return ""

    def _is_allowed_url(self, url, sites):
        """Check URL thuộc domain được phép."""
        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower()
            return any(s["domain"].lower() in host for s in sites)
        except Exception:
            return False
