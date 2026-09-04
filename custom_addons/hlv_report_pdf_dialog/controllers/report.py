
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from urllib.parse import quote
from typing import Any, List

from werkzeug import urls
from werkzeug.wrappers import Response

from odoo import http
from odoo.http import request, route
from odoo.tools.safe_eval import safe_eval
from odoo.tools.safe_eval import time as safe_time

from odoo.addons.web.controllers.report import ReportController


class ReportDialogController(ReportController):
    """Override /report/pdf to return inline for browser preview."""

    def _get_extra_context_for_single_record(self, report_name, ignore_expr=None):
        import re
        ignore_expr = ignore_expr or []
        extra_ctx = {}
        for expr in re.findall(r"%.?\(.*?\)", report_name or ""):
            expr = expr.replace("%", "").strip()[1:-1].strip()
            if "." in expr:
                expr = expr.split(".")[0]
            if expr in ignore_expr:
                continue
            extra_ctx[expr] = "report"
        return extra_ctx

    def _compose_report_file_name(self, docids, report):
        report_name = "report"
        if docids:
            records = request.env[report.model].browse(docids)
            record_count = len(docids)
            if record_count == 1 and report.sudo().print_report_name:
                print_report_name = report.sudo().print_report_name
                extra_ctx = self._get_extra_context_for_single_record(
                    print_report_name, ignore_expr=["object", "time"]
                )
                report_name = safe_eval(
                    print_report_name,
                    {
                        "object": records,
                        "time": safe_time,
                        **extra_ctx,
                    },
                )
            else:
                report_name = f"{report.name} x{record_count}"
        else:
            report_name = report.name
        return report_name or "report"

    @route(
        ["/report/<converter>/<reportname>", "/report/<converter>/<reportname>/<docids>"],
        type="http",
        auth="user",
        website=True,
    )
    def report_routes(
        self,
        reportname: str,
        docids: str | None = None,
        converter: str | None = None,
        **data: dict[str, Any],
    ) -> Response:
        if converter != "pdf":
            return super().report_routes(reportname, docids=docids, converter=converter, **data)

        report = request.env["ir.actions.report"]._get_report_from_name(reportname)
        if not report:
            return request.not_found()

        context = dict(request.env.context)

        if data.get("options"):
            options_str = data.pop("options")
            if isinstance(options_str, str):
                try:
                    data.update(json.loads(urls.url_unquote_plus(options_str)))
                except Exception:
                    pass

        if data.get("context"):
            context_str = data.get("context")
            if isinstance(context_str, str):
                try:
                    context.update(json.loads(urls.url_unquote_plus(context_str)))
                except Exception:
                    pass

        cid = data.get("cid")
        if cid:
            try:
                allowed_company_ids = [int(cid) for cid in cid.split(",")]
                context["allowed_company_ids"] = allowed_company_ids
            except Exception:
                return request.not_found()

        request.env.context = context

        ids_list: List[int] = []
        if docids:
            try:
                ids_list = [int(i) for i in docids.split(",")]
                recs = request.env[report.model].browse(ids_list)
                recs.check_access("read")
            except Exception:
                return request.not_found()

        report_name = self._compose_report_file_name(ids_list, report)
        pdf, _ = report.with_context(**context)._render_qweb_pdf(reportname, ids_list, data=data)

        return request.make_response(
            pdf,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Length", len(pdf)),
                (
                    "Content-Disposition",
                    f"inline; filename=\"{quote(report_name, safe='')}.pdf\"",
                ),
            ],
        )

    @http.route("/report/check_wkhtmltopdf", type="json", auth="user")
    def check_wkhtmltopdf(self):
        return request.env["ir.actions.report"].get_wkhtmltopdf_state()

    @http.route("/report/download", type="http", auth="user")
    def report_download(self, data, context=None, token=None):
        """Override report_download to fix Content-Disposition header format.

        Odoo gốc đôi khi trả về HAI header 'Content-Disposition' riêng biệt (1 bản ASCII
        filename="..." + 1 bản RFC2231 filename*=charset'lang'encoded) — hợp lệ theo cách
        Werkzeug lưu nhưng trình duyệt (Chrome mới) coi là lỗi
        (net::ERR_RESPONSE_HEADERS_MULTIPLE_CONTENT_DISPOSITION) và HỦY response luôn.
        response.headers.get(...) chỉ đọc được BẢN ĐẦU TIÊN — nếu bản đó không chứa
        'filename*=', code cũ bỏ qua không sửa gì, để nguyên 2 header trùng tên gây lỗi.
        Ở đây gom HẾT các bản trùng tên (get_all) rồi ghi lại ĐÚNG 1 header duy nhất."""
        response = super().report_download(data, context=context, token=token)

        if not hasattr(response, "headers"):
            return response
        disposition_values = response.headers.get_all("Content-Disposition")
        if not disposition_values:
            return response

        import re
        from urllib.parse import unquote

        # Ưu tiên bản RFC2231 (filename*=) vì nó giữ đúng tên file gốc (có dấu/unicode) —
        # bản ASCII fallback thường chỉ là tên đã rút gọn/thay thế ký tự.
        chosen = next((v for v in disposition_values if "filename*=" in v), disposition_values[0])
        disposition_type = "attachment" if chosen.startswith("attachment") else "inline"

        filename = None
        match = re.search(r"filename\*=([^']+)'([^']*)'(.+?)(?:;|$)", chosen)
        if match:
            try:
                filename = unquote(match.group(3))
            except Exception:
                filename = None
        if filename is None:
            match_ascii = re.search(r'filename="?([^";]+)"?', chosen)
            if match_ascii:
                filename = match_ascii.group(1)

        if filename:
            safe_filename = quote(filename, safe="")
            new_content_disp = f'{disposition_type}; filename="{safe_filename}"'
        else:
            # Không tách được tên file từ BẤT KỲ bản nào — vẫn phải gom về 1 header duy nhất,
            # dùng nguyên bản đầu tiên thay vì để nguyên cả 2 gây lỗi trình duyệt.
            new_content_disp = chosen

        # QUAN TRỌNG: __setitem__ trên Headers của Werkzeug tự xóa HẾT các bản trùng tên trước
        # khi ghi bản mới — đảm bảo response cuối cùng chỉ còn ĐÚNG 1 header Content-Disposition.
        response.headers["Content-Disposition"] = new_content_disp

        return response
