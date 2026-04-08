import logging
import re
import urllib.parse

import requests

from odoo import _, models

_logger = logging.getLogger(__name__)

MECSU_BASE = "https://mecsu.vn"


class HlvDocCrawlerMecSu(models.Model):
    """MecSu-specific crawler methods."""

    _inherit = "hlv.doc.crawler"

    # ─── MecSu HTTP helpers ───────────────────────────────────────────────────

    def _mecsu_headers(self):
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def _mecsu_get(self, url):
        """Lấy HTML từ một URL của mecsu.vn."""
        resp = requests.get(url, headers=self._mecsu_headers(), timeout=25)
        resp.raise_for_status()
        return resp.text

    def _mecsu_parse_listing(self, html):
        """Phân tích trang danh sách sản phẩm MecSu, trả về list {name, sku, url}.

        Tên sản phẩm được lấy từ URL slug (/chi-tiet/{ten-slug}.{id}) vì link text
        thường chỉ là mã số ngắn (0043188) không dùng được để tính điểm.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            _logger.warning("Thư viện bs4 chưa cài — không phân tích được HTML MecSu.")
            return []

        soup = BeautifulSoup(html, "html.parser")
        seen_urls = set()
        results = []

        all_chi_tiet = [a["href"] for a in soup.find_all("a", href=True) if "/chi-tiet/" in a["href"]]
        _logger.info("MecSu parse_listing: HTML=%d bytes, chi-tiet raw links=%d", len(html), len(all_chi_tiet))

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/chi-tiet/" not in href:
                continue
            full_url = (
                href if href.startswith("http") else f"{MECSU_BASE}{href}"
            )
            if full_url in seen_urls:
                continue

            slug_part = href.split("/chi-tiet/")[-1]
            slug_clean = re.sub(r'\.[0-9]+$', '', slug_part)
            name_from_slug = slug_clean.replace("-", " ")
            name_from_slug = re.sub(r'\b(\d+) (\d)\b', r'\1.\2', name_from_slug)

            link_text = a_tag.get_text(strip=True)
            if len(name_from_slug) >= 8:
                name = name_from_slug
            elif link_text and len(link_text) >= 8:
                name = link_text
            else:
                continue

            seen_urls.add(full_url)
            results.append({"name": name, "sku": "", "url": full_url})

        return results

    # ─── MecSu scoring ───────────────────────────────────────────────────────

    # Mapping loại sản phẩm: keyword Odoo → keywords MecSu tương đương
    _MECSU_TYPE_MAP = {
        "bu lông": ["bulong", "bu long"],
        "bulong": ["bulong", "bu long"],
        "lục giác chìm": ["luc giac chim"],
        "lục giác": ["luc giac"],
        "ốc vít": ["oc vit", "vit"],
        "đai ốc": ["dai oc"],
        "vòng đệm": ["vong dem", "long den"],
        "long đen": ["long den"],
        "lông đền": ["long den"],
        "ty ren": ["ty ren", "guzong"],
        "guzong": ["guzong", "ty ren"],
    }

    def _mecsu_score(self, odoo_code, odoo_name, candidate):
        """Tính điểm tương đồng giữa sản phẩm Odoo và kết quả MecSu (0.0–1.0).

        Token-overlap trên: loại SP (0.8) + kích thước (1.0) + grade (0.6) + vật liệu (0.3).
        Penalty mạnh nếu sai loại sản phẩm.
        """
        cand_name = (candidate.get("name") or "").lower()
        odoo_norm = (odoo_name or "").lower()

        # ─── 0. Loại sản phẩm ────────────────────────────────────────────────
        type_score = 0.0
        type_found = False
        for odoo_kw, mecsu_kws in self._MECSU_TYPE_MAP.items():
            if odoo_kw in odoo_norm:
                type_found = True
                if any(k in cand_name for k in mecsu_kws):
                    type_score = 0.8
                else:
                    type_score = -0.5
                break

        # ─── 1. Token kỹ thuật ───────────────────────────────────────────────
        token_rules = [
            (1.0, re.compile(r'm\d+(?:[x×]\d+(?:\.\d+)?)?', re.IGNORECASE)),
            (0.6, re.compile(r'\b(?:4\.8|5\.6|8\.8|10\.9|12\.9|a2-70|a4-80|a2|a4)\b', re.IGNORECASE)),
            (0.4, re.compile(r'(?:din|iso)\s*\d+', re.IGNORECASE)),
        ]
        tokens = []
        for weight, pattern in token_rules:
            for m in pattern.finditer(odoo_norm):
                t = m.group(0).lower().replace(" ", "").replace("×", "x")
                tokens.append((weight, t))

        # ─── 2. Vật liệu ─────────────────────────────────────────────────────
        material_odoo = None
        if any(k in odoo_norm for k in ("ss304", "304", "inox304")):
            material_odoo = "304"
        elif "316" in odoo_norm or "ss316" in odoo_norm:
            material_odoo = "316"
        elif any(k in odoo_norm for k in ("thép đen", " đen", "carbon", "black", "mạ kẽm")):
            material_odoo = "black"
        elif "inox" in odoo_norm:
            material_odoo = "inox_generic"

        if not tokens and not material_odoo and not type_found:
            from difflib import SequenceMatcher
            return SequenceMatcher(None, odoo_norm, cand_name).ratio() * 0.6

        # ─── 3. Tính điểm ────────────────────────────────────────────────────
        total_w = sum(w for w, _ in tokens)
        match_w = 0.0
        for weight, token in tokens:
            if token in cand_name:
                match_w += weight

        mat_score = 0.0
        if material_odoo:
            total_w += 0.3
            if material_odoo == "304":
                mat_score = 0.3 if any(k in cand_name for k in ("304",)) else (0.1 if "inox" in cand_name else -0.1)
            elif material_odoo == "316":
                mat_score = 0.3 if "316" in cand_name else -0.1
            elif material_odoo == "black":
                mat_score = 0.3 if any(k in cand_name for k in ("đen", "carbon", "kẽm", "zinc", "den")) else -0.1
            elif material_odoo == "inox_generic":
                mat_score = 0.3 if "inox" in cand_name else -0.05

        if type_found:
            total_w += 0.8

        raw = match_w + max(-0.5, mat_score) + type_score
        return max(0.0, min(1.0, raw / max(total_w, 0.001)))

    # ─── MecSu search ────────────────────────────────────────────────────────

    def _extract_search_terms(self, odoo_name):
        """Trích xuất cụm từ kỹ thuật tốt nhất để search mecsu.vn."""
        if not odoo_name:
            return odoo_name or ""

        parts = []

        dims = re.findall(r'M\d+(?:[x×]\d+(?:\.\d+)?)?', odoo_name, re.IGNORECASE)
        parts.extend(d.upper() for d in dims[:2])

        standards = re.findall(r'(?:DIN|ISO)\s*\d+', odoo_name, re.IGNORECASE)
        parts.extend(s.upper().replace(" ", "") for s in standards[:1])

        grades = re.findall(r'\b(?:4\.8|8\.8|10\.9|12\.9)\b', odoo_name)
        parts.extend(grades[:1])

        if parts:
            return " ".join(parts)

        words = [w for w in odoo_name.split() if len(w) > 1]
        return " ".join(words[-3:]) if len(words) >= 2 else odoo_name

    def _mecsu_search_via_popup(self, query):
        """Tìm sản phẩm mecsu: GET /site?keyword= → popup button → quick-view → chi-tiet URL."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        try:
            url = f"{MECSU_BASE}/site?keyword={urllib.parse.quote(query)}"
            html = self._mecsu_get(url)
        except Exception as e:
            _logger.warning("MecSu get /site?keyword=%s: %s", query, e)
            return []

        soup = BeautifulSoup(html, "html.parser")
        popup_btns = soup.select('a.mecsu-button-popup-lg[title="Thông số kỹ thuật"]')
        _logger.info("MecSu /site?keyword=%s → %d popup buttons", query, len(popup_btns))

        candidates = []
        seen_urls = set()
        for btn in popup_btns[:15]:
            quick_view_path = btn.get("value", "")
            if not quick_view_path or "product-quick-view" not in quick_view_path:
                continue
            quick_view_url = MECSU_BASE + quick_view_path
            try:
                qv_html = self._mecsu_get(quick_view_url)
                qv_soup = BeautifulSoup(qv_html, "html.parser")
                for link in qv_soup.select('a[href*="/chi-tiet/"]'):
                    href = link.get("href", "")
                    if not href:
                        continue
                    full_url = href if href.startswith("http") else MECSU_BASE + href
                    if full_url in seen_urls:
                        continue
                    slug = href.split("/chi-tiet/")[-1]
                    slug_clean = re.sub(r"\.\d+$", "", slug)
                    name = slug_clean.replace("-", " ")
                    name = re.sub(r"\b(\d+) (\d)\b", r"\1.\2", name)
                    seen_urls.add(full_url)
                    candidates.append({"name": name, "url": full_url, "sku": ""})
                    break
            except Exception as e:
                _logger.warning("MecSu quick-view %s: %s", quick_view_url, e)

        return candidates

    def _mecsu_search(self, odoo_code, odoo_name, max_pages=2):
        """Tìm kiếm sản phẩm trên mecsu.vn qua popup button → quick-view flow."""
        candidates = []
        seen_urls = set()
        tech_query = self._extract_search_terms(odoo_name)

        def _add(items):
            for item in items:
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    candidates.append(item)

        if tech_query and tech_query.lower() != (odoo_name or "").lower():
            _add(self._mecsu_search_via_popup(tech_query))

        if odoo_name and len(candidates) < 3:
            _add(self._mecsu_search_via_popup(odoo_name))

        if not candidates and odoo_name:
            words = odoo_name.split()
            if len(words) > 3:
                _add(self._mecsu_search_via_popup(" ".join(words[-3:])))

        return candidates

    # ─── MecSu detail page ────────────────────────────────────────────────────

    def _mecsu_extract_pdf_url(self, soup):
        """Tìm URL PDF 'Tài liệu tham khảo' từ trang chi tiết MecSu.

        Ưu tiên: img[alt='PDF Icon'] → parent a[href] → link kết thúc .pdf
        """
        # Ưu tiên: tìm img PDF Icon rồi lấy href của thẻ a cha
        img = soup.find("img", attrs={"alt": "PDF Icon"})
        if img:
            parent_a = img.find_parent("a", href=True)
            if parent_a:
                href = parent_a["href"]
                if not href.startswith("http"):
                    href = f"{MECSU_BASE}{href}"
                return href

        # Fallback: bất kỳ link nào kết thúc .pdf
        pdf_a = soup.find("a", href=re.compile(r"\.pdf(\?.*)?$", re.I))
        if pdf_a:
            href = pdf_a["href"]
            if not href.startswith("http"):
                href = f"{MECSU_BASE}{href}"
            return href

        return None

    def _mecsu_download_pdf(self, pdf_url):
        """Tải PDF từ mecsu.vn. Trả về bytes hoặc None nếu lỗi."""
        try:
            resp = requests.get(pdf_url, headers=self._mecsu_headers(), timeout=30)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            _logger.warning("MecSu download PDF failed: %s — %s", pdf_url, e)
            return None

    def _mecsu_fetch_detail(self, url):
        """Lấy trang chi tiết MecSu. Trả về (pdf_url, markdown_str).

        pdf_url: URL file PDF 'Tài liệu tham khảo' nếu có, ngược lại None.
        markdown_str: nội dung markdown từ bảng thông số (dùng khi không có PDF).
        """
        try:
            html = self._mecsu_get(url)
        except Exception as e:
            _logger.warning("MecSu fetch detail failed: %s — %s", url, e)
            return None, ""

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None, self._clean_html(html)

        soup = BeautifulSoup(html, "html.parser")

        # Lấy PDF URL trước khi decompose tags
        pdf_url = self._mecsu_extract_pdf_url(soup)

        # Xóa hoàn toàn các phần không liên quan đến nội dung sản phẩm
        _JUNK_SELECTORS = [
            "script", "style", "nav", "footer", "header",
            ".breadcrumb", ".social-share", ".share",
            ".related", ".product__related", ".similar",
            ".contact", ".hotline", ".phone", ".email",
            ".banner", ".advertisement", ".ads",
            ".cookie", ".popup", ".modal",
            "[class*='footer']", "[class*='header']",
            "[class*='contact']", "[class*='social']",
            "[class*='share']", "[class*='related']",
            "[class*='sidebar']", "[class*='widget']",
        ]
        for sel in _JUNK_SELECTORS:
            for tag in soup.select(sel):
                tag.decompose()

        lines = []

        # Tiêu đề
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""
        if title:
            lines.append(f"# {title}")
            lines.append("")

        # Bảng thông số kỹ thuật (lấy bảng có >= 3 hàng 2 cột)
        for tbl in soup.find_all("table"):
            rows = []
            for tr in tbl.find_all("tr"):
                cells = [
                    td.get_text(separator=" ", strip=True)
                    for td in tr.find_all(["td", "th"])
                ]
                if len(cells) >= 2 and cells[0] and cells[1]:
                    rows.append(f"- **{cells[0]}:** {cells[1]}")
            if len(rows) >= 3:
                lines.append("## Thông số kỹ thuật")
                lines.extend(rows)
                lines.append("")
                break

        # Mô tả sản phẩm — tìm div/section chứa mô tả dài
        _DESC_SELECTORS = [
            ".product__description", ".product-description",
            ".description", ".product__content", ".product-content",
            "[class*='description']", "[class*='content']",
        ]
        for sel in _DESC_SELECTORS:
            desc_el = soup.select_one(sel)
            if desc_el:
                desc_text = desc_el.get_text(separator="\n", strip=True)
                # Lọc bỏ các dòng rác: email, phone, URL, quảng cáo
                clean_lines = []
                for ln in desc_text.splitlines():
                    ln = ln.strip()
                    if not ln:
                        continue
                    # Bỏ dòng chứa thông tin liên hệ / URL website
                    if re.search(
                        r'(\bwww\.|http|@|028\.|0[3-9]\d{8}|'
                        r'more product|email:|phone:|hotline|'
                        r'mecsu\.vn|sales@)',
                        ln, re.IGNORECASE
                    ):
                        continue
                    clean_lines.append(ln)
                desc_clean = "\n".join(clean_lines).strip()
                if len(desc_clean) > 80:
                    lines.append("## Mô tả sản phẩm")
                    lines.append(desc_clean)
                    lines.append("")
                break

        return pdf_url, ("\n".join(lines) if lines else "")

    # ─── MecSu processing ─────────────────────────────────────────────────────

    def _process_mecsu_product(self, product, sku, line, collection):
        """Xử lý 1 sản phẩm qua MecSu search. Trả về True nếu tìm thấy."""
        tech_query = self._extract_search_terms(product.name)
        _logger.info(
            "MecSu [%s] SKU=%s | query='%s' | name='%s'",
            self.name, sku, tech_query, product.name,
        )
        candidates = self._mecsu_search(sku, product.name)
        _logger.info(
            "MecSu [%s] SKU=%s | %d ứng viên",
            self.name, sku, len(candidates),
        )

        best = None
        best_score = 0.0
        score_log = []
        for candidate in candidates:
            score = self._mecsu_score(sku, product.name, candidate)
            score_log.append((score, candidate.get("name", "")[:60]))
            if score > best_score:
                best_score = score
                best = candidate

        if score_log:
            top = sorted(score_log, reverse=True)[:3]
            _logger.info(
                "MecSu [%s] SKU=%s | top token scores: %s",
                self.name, sku,
                "; ".join(f"{s:.2f} – {n}" for s, n in top),
            )

        if not candidates:
            line.write({
                "status": "not_found",
                "error_msg": f"Query: '{tech_query}' | 0 ứng viên",
            })
            return False

        # ─── GPT QC mode ──────────────────────────────────────────────────────
        if self.use_gpt_qc:
            gpt_threshold = self.gpt_qc_threshold or 0.6
            best_gpt_score = 0.0
            best_gpt_reason = ""

            # Nếu không bật gpt_qc_all_candidates → chỉ gửi ứng viên token-best
            to_check = candidates if self.gpt_qc_all_candidates else ([best] if best else [])

            for candidate in to_check:
                gpt_result = self._run_gpt_qc(product.name, candidate.get("name", ""))
                if gpt_result is None:
                    # GPT lỗi hoàn toàn (thiếu key) → dừng sớm, fallback token
                    _logger.warning(
                        "MecSu [%s] SKU=%s: GPT QC lỗi, fallback token threshold",
                        self.name, sku,
                    )
                    threshold = self.mecsu_similarity_threshold or 0.65
                    if best_score < threshold:
                        line.write({
                            "status": "not_found",
                            "error_msg": f"GPT lỗi + token thấp: {best_score:.2f} – {(best or {}).get('name','?')[:50]}",
                        })
                        return False
                    # best đã được tính bằng token score ở trên → dùng luôn
                    break

                g_score = gpt_result["score"]
                g_reason = gpt_result.get("reason", "")
                _logger.info(
                    "MecSu [%s] SKU=%s GPT QC [%s]: %.2f – %s",
                    self.name, sku, candidate.get("name", "")[:40], g_score, g_reason,
                )
                if g_score > best_gpt_score:
                    best_gpt_score = g_score
                    best_gpt_reason = g_reason
                    best = candidate

                # Tìm được ứng viên rất tốt → dừng sớm
                if best_gpt_score >= 0.9:
                    break

            if best is None or best_gpt_score < gpt_threshold:
                line.write({
                    "status": "not_found",
                    "error_msg": (
                        f"GPT reject tất cả {len(candidates)} ứng viên | "
                        f"Cao nhất: {best_gpt_score:.2f} – {best_gpt_reason}"
                    ),
                    "match_score": best_gpt_score,
                })
                return False

            # Ghi lại GPT score vào best_score để hiển thị
            best_score = best_gpt_score

        else:
            # ─── Chế độ token score thuần ─────────────────────────────────
            threshold = self.mecsu_similarity_threshold or 0.65
            if not best or best_score < threshold:
                line.write({
                    "status": "not_found",
                    "error_msg": (
                        f"Query: '{tech_query}' | {len(candidates)} ứng viên"
                        + (f" | Cao nhất: {best_score:.2f} – {best['name'][:50]}" if best else "")
                    ),
                })
                return False

        pdf_url, content = self._mecsu_fetch_detail(best["url"])

        if not pdf_url and not content:
            line.write({
                "status": "error",
                "error_msg": "Không lấy được nội dung trang chi tiết MecSu",
                "wc_url": best["url"],
                "match_score": best_score,
            })
            return False

        # Lưu markdown specs (luôn lưu nếu có)
        doc_md = None
        if content:
            doc_md = self._ensure_product_document(product, f"{sku}_mecsu", content)

        # Lưu PDF (luôn lưu nếu có, song song với markdown)
        doc_pdf = None
        if pdf_url:
            pdf_bytes = self._mecsu_download_pdf(pdf_url)
            if pdf_bytes:
                _logger.info("MecSu [%s] SKU=%s: lưu PDF %s (%d bytes)",
                             self.name, sku, pdf_url, len(pdf_bytes))
                doc_pdf = self._ensure_product_document_pdf(product, f"{sku}_mecsu", pdf_bytes)
            else:
                _logger.warning("MecSu [%s] SKU=%s: PDF download failed %s",
                                self.name, sku, pdf_url)

        # Dùng PDF làm resource chính (nếu có), ngược lại dùng markdown
        doc_primary = doc_pdf or doc_md

        # Index cả 2 nếu auto_index
        resource = None
        if self.auto_index or collection:
            for doc in filter(None, [doc_md, doc_pdf]):
                r = self._ensure_resource(doc, collection)
                if self.auto_index:
                    r.process_resource()
                if doc is doc_primary:
                    resource = r

        line.write(
            {
                "status": "found",
                "wc_url": best["url"],
                "match_score": best_score,
                "document_id": doc_primary.ir_attachment_id.id,
                "resource_id": resource.id if resource else False,
            }
        )
        return True
