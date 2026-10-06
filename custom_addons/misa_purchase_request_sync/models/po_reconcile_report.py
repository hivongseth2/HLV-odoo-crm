# -*- coding: utf-8 -*-
import base64
import logging
import os
import tempfile
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import api, fields, models

from .po_reconcile_xlsx import STATUS_LABELS, build_reconcile_xlsx

_logger = logging.getLogger(__name__)

RECIPIENTS_PARAM = "misa_po_reconcile_emails"
DAYS_PARAM = "misa_po_reconcile_days"
# Thư mục riêng ở gốc My Drive, tách khỏi các thư mục kho chứa video đóng gói
DRIVE_FOLDER = "DOI_CHIEU_DON_MUA_HANG"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class MisaPoReconcileReport(models.AbstractModel):
    _name = "misa.po.reconcile.report"
    _description = "Báo cáo đối chiếu PO Odoo - MISA gửi mail hằng ngày"

    @api.model
    def _gdrive_connect(self):
        """Kết nối Google Drive bằng tài khoản đã cấp quyền ở custom_barcode_scan_redirect
        (dùng chung System Parameters gdrive.*, không import code module đó).
        Trả về (drive, settings_path); bên gọi phải xoá settings_path (chứa client secret)."""
        from oauth2client.client import OAuth2Credentials
        from pydrive2.auth import GoogleAuth
        from pydrive2.drive import GoogleDrive

        ICP = self.env["ir.config_parameter"].sudo()
        creds_json = ICP.get_param("gdrive.user_credentials_json")
        if not creds_json:
            raise ValueError("Chưa kết nối Google Drive (thiếu gdrive.user_credentials_json)")
        scopes = (ICP.get_param("gdrive.oauth_scopes") or "https://www.googleapis.com/auth/drive.file").replace(",", " ").split()
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(
                "client_config_backend: settings\n"
                "client_config:\n"
                '  client_id: "%s"\n  client_secret: "%s"\n  redirect_uri: "%s"\n'
                '  auth_uri: "https://accounts.google.com/o/oauth2/v2/auth"\n'
                '  token_uri: "https://oauth2.googleapis.com/token"\n'
                '  revoke_uri: "https://oauth2.googleapis.com/revoke"\n'
                "oauth_scope:\n%s\n"
                "get_refresh_token: True\nsave_credentials: False\n" % (
                    ICP.get_param("gdrive.oauth_client_id") or "",
                    ICP.get_param("gdrive.oauth_client_secret") or "",
                    ICP.get_param("gdrive.oauth_redirect_uri") or "",
                    "\n".join("  - %s" % s for s in scopes),
                )
            )
            settings_path = f.name
        try:
            gauth = GoogleAuth(settings_path)
            gauth.credentials = OAuth2Credentials.from_json(creds_json)
            if gauth.access_token_expired:
                gauth.Refresh()
            gauth.Authorize()
        except Exception:
            os.remove(settings_path)
            raise
        return GoogleDrive(gauth), settings_path

    @api.model
    def _upload_to_drive(self, filename, content):
        """Đẩy file vào thư mục DRIVE_FOLDER trên Google Drive. Trả về link, lỗi thì None."""
        settings_path = tmp_path = None
        try:
            drive, settings_path = self._gdrive_connect()
            q = ("mimeType='application/vnd.google-apps.folder' and trashed=false and title='%s' "
                 "and 'root' in parents" % DRIVE_FOLDER)
            found = drive.ListFile({"q": q}).GetList()
            if found:
                folder_id = found[0]["id"]
            else:
                folder = drive.CreateFile({"title": DRIVE_FOLDER, "mimeType": "application/vnd.google-apps.folder"})
                folder.Upload()
                folder_id = folder["id"]
            # pydrive2 chỉ upload nhị phân từ file trên đĩa
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            gfile = drive.CreateFile({"title": filename, "parents": [{"id": folder_id}], "mimeType": XLSX_MIME})
            gfile.SetContentFile(tmp_path)
            gfile.Upload()
            gfile.content.close()
            return gfile.get("alternateLink") or "https://drive.google.com/file/d/%s/view" % gfile["id"]
        except Exception:
            _logger.exception("PO reconcile cron: upload Google Drive thất bại, vẫn gửi mail.")
            return None
        finally:
            for path in (settings_path, tmp_path):
                if path and os.path.exists(path):
                    os.remove(path)

    @api.model
    def cron_send_daily_reconcile(self):
        """Cron 19h (GMT+7): đối chiếu PO trong N ngày gần nhất, lưu Excel lên Drive và gửi mail."""
        ICP = self.env["ir.config_parameter"].sudo()
        raw = ICP.get_param(RECIPIENTS_PARAM) or ""
        emails = ",".join(e.strip() for e in raw.replace(";", ",").split(",") if e.strip())
        if not emails:
            _logger.warning("PO reconcile cron: chưa cấu hình System Parameter '%s', bỏ qua.", RECIPIENTS_PARAM)
            return

        try:
            days = max(1, int(ICP.get_param(DAYS_PARAM) or 1))
        except ValueError:
            _logger.warning("PO reconcile cron: '%s' không phải số nguyên, dùng 1 ngày.", DAYS_PARAM)
            days = 1
        today = fields.Date.context_today(self.with_context(tz="Asia/Ho_Chi_Minh"))
        date_to = today.isoformat()
        date_from = (today - timedelta(days=days - 1)).isoformat()
        period = date_to if days == 1 else "%s đến %s" % (date_from, date_to)

        # Import trễ để tránh vòng import models <-> controllers khi load module
        from ..controllers.extension_api import MisaExtensionController
        # su=True: cron cần đọc toàn bộ PO/picking như endpoint của extension
        res = MisaExtensionController()._reconcile_po_only_data(self.env(su=True), date_from, date_to)

        content = build_reconcile_xlsx(res, date_from, date_to)
        filename = "Doi_Chieu_Don_Hang_%s.xlsx" % (date_to if days == 1 else "%s_toi_%s" % (date_from, date_to))
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "datas": base64.b64encode(content),
            "mimetype": XLSX_MIME,
            "res_model": self._name,
        })
        drive_link = self._upload_to_drive(filename, content)

        summary = res.get("summary") or {}
        status_rows = Markup("").join(
            Markup("<li>%s: <b>%s</b></li>") % (STATUS_LABELS.get(k, k), v)
            for k, v in (summary.get("by_status") or {}).items()
        )
        drive_html = (Markup('<p>File cũng được lưu trên Google Drive: <a href="%s">%s</a></p>') % (drive_link, filename)
                      if drive_link else Markup(""))
        body = Markup(
            "<p>Báo cáo đối chiếu Đơn mua hàng Odoo - MISA ngày <b>%s</b>.</p>"
            "<p>Tổng số đơn Odoo: <b>%s</b> — Tổng số đơn MISA: <b>%s</b></p><ul>%s</ul>"
            "<p>Chi tiết xem file Excel đính kèm.</p>%s"
        ) % (escape(period), summary.get("total_odoo") or 0, summary.get("total_misa") or 0, status_rows, drive_html)

        mail = self.env["mail.mail"].sudo().create({
            "subject": "Đối chiếu Đơn mua hàng Odoo - MISA ngày %s" % period,
            "email_from": self.env.company.email_formatted or self.env.user.email_formatted,
            "email_to": emails,
            "body_html": body,
            "attachment_ids": [fields.Command.link(attachment.id)],
            "auto_delete": False,
        })
        # Gửi ngay, không chờ cron hàng đợi mail (1h/lần) vì phần gọi API MISA có thể làm trễ vài phút.
        # Lỗi SMTP không raise: mail chuyển sang "Giao thư đã lỗi", xem lý do và bấm gửi lại trong Settings > Technical > Emails.
        mail.send()
        _logger.info("PO reconcile cron: %s, đã gửi mail tới %s (%s đơn Odoo), trạng thái %s, Drive: %s.",
                     period, emails, summary.get("total_odoo"), mail.state, drive_link or "không lưu được")
