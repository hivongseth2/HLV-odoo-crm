# -*- coding: utf-8 -*-
import base64
import logging

from markupsafe import Markup, escape

from odoo import api, fields, models

from .po_reconcile_xlsx import STATUS_LABELS, build_reconcile_xlsx

_logger = logging.getLogger(__name__)

RECIPIENTS_PARAM = "misa_po_reconcile_emails"


class MisaPoReconcileReport(models.AbstractModel):
    _name = "misa.po.reconcile.report"
    _description = "Báo cáo đối chiếu PO Odoo - MISA gửi mail hằng ngày"

    @api.model
    def cron_send_daily_reconcile(self):
        """Cron 19h (GMT+7): đối chiếu PO trong ngày và gửi Excel cho danh sách email trong System Parameter."""
        raw = self.env["ir.config_parameter"].sudo().get_param(RECIPIENTS_PARAM) or ""
        emails = ",".join(e.strip() for e in raw.replace(";", ",").split(",") if e.strip())
        if not emails:
            _logger.warning("PO reconcile cron: chưa cấu hình System Parameter '%s', bỏ qua.", RECIPIENTS_PARAM)
            return

        today = fields.Date.context_today(self.with_context(tz="Asia/Ho_Chi_Minh")).isoformat()
        # Import trễ để tránh vòng import models <-> controllers khi load module
        from ..controllers.extension_api import MisaExtensionController
        # su=True: cron cần đọc toàn bộ PO/picking như endpoint của extension
        res = MisaExtensionController()._reconcile_po_only_data(self.env(su=True), today, today)

        filename = "Doi_Chieu_Don_Hang_%s.xlsx" % today
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "datas": base64.b64encode(build_reconcile_xlsx(res, today, today)),
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "res_model": self._name,
        })

        summary = res.get("summary") or {}
        status_rows = Markup("").join(
            Markup("<li>%s: <b>%s</b></li>") % (STATUS_LABELS.get(k, k), v)
            for k, v in (summary.get("by_status") or {}).items()
        )
        body = Markup(
            "<p>Báo cáo đối chiếu Đơn mua hàng Odoo - MISA ngày <b>%s</b>.</p>"
            "<p>Tổng số đơn Odoo: <b>%s</b> — Tổng số đơn MISA: <b>%s</b></p><ul>%s</ul>"
            "<p>Chi tiết xem file Excel đính kèm.</p>"
        ) % (escape(today), summary.get("total_odoo") or 0, summary.get("total_misa") or 0, status_rows)

        mail = self.env["mail.mail"].sudo().create({
            "subject": "Đối chiếu Đơn mua hàng Odoo - MISA ngày %s" % today,
            "email_from": self.env.company.email_formatted or self.env.user.email_formatted,
            "email_to": emails,
            "body_html": body,
            "attachment_ids": [fields.Command.link(attachment.id)],
            "auto_delete": False,
        })
        # Gửi ngay, không chờ cron hàng đợi mail (1h/lần) vì phần gọi API MISA có thể làm trễ vài phút.
        # Lỗi SMTP không raise: mail chuyển sang "Giao thư đã lỗi", xem lý do và bấm gửi lại trong Settings > Technical > Emails.
        mail.send()
        _logger.info("PO reconcile cron: đã gửi mail tới %s (%s đơn Odoo), trạng thái %s.",
                     emails, summary.get("total_odoo"), mail.state)
