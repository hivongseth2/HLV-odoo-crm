# -*- coding: utf-8 -*-
import json
import logging
import time
import uuid
from datetime import timedelta

import requests

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


MISA_CRM_ACCOUNT_GRID_URL = "https://amisapp.misa.vn/crm/g2/api/business/Account/Grid"
MISA_CRM_COLUMNS = (
    "SUQsVGFnSUQsVGFnSURUZXh0LEFjY291bnROdW1iZXIsQWNjb3VudFR5cGVJRCxBY2NvdW50"
    "VHlwZUlEVGV4dCxBY2NvdW50TmFtZSxUYXhDb2RlLE9mZmljZVRlbCxPZmZpY2VFbWFpbCxTZWN0"
    "b3JJRCxTZWN0b3JJRFRleHQsQmlsbGluZ0FkZHJlc3MsQmlsbGluZ1Byb3ZpbmNlSUQsQmls"
    "bGluZ1Byb3ZpbmNlSURUZXh0LEJpbGxpbmdEaXN0cmljdElELEJpbGxpbmdEaXN0cmljdElE"
    "VGV4dCxCaWxsaW5nV2FyZElELEJpbGxpbmdXYXJkSURUZXh0LERlc2NyaXB0aW9uLE93bmVy"
    "SUQsT3duZXJJRFRleHQsTGVhZFNvdXJjZUlELExlYWRTb3VyY2VJRFRleHQsRm9ybUxheW91"
    "dElELEZvcm1MYXlvdXRJRFRleHQsQXZhdGFyLEluYWN0aXZlLElzQ29ycA=="
)


class MisaCrmContactSyncRun(models.Model):
    _name = "misa.crm.contact.sync.run"
    _description = "MISA CRM Contact Sync Run"
    _order = "start_at desc, id desc"

    name = fields.Char(default=lambda self: fields.Datetime.now().strftime("MISA CRM Sync %Y-%m-%d %H:%M:%S"))
    state = fields.Selection([
        ("running", "Running"),
        ("done", "Done"),
        ("failed", "Failed"),
    ], default="running", required=True)
    service_date = fields.Date(index=True)
    start_at = fields.Datetime(default=fields.Datetime.now, required=True)
    end_at = fields.Datetime()
    duration_seconds = fields.Float()
    total_count = fields.Integer()
    success_count = fields.Integer()
    created_count = fields.Integer()
    updated_count = fields.Integer()
    unchanged_count = fields.Integer()
    failed_count = fields.Integer()
    page_count = fields.Integer()
    message = fields.Text()
    line_ids = fields.One2many("misa.crm.contact.sync.line", "run_id", string="Details")

    def action_run_now(self):
        run = self.sudo().cron_sync_contacts_from_crm(force=True)
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": run.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model
    def cron_sync_contacts_from_crm(self, force=False):
        service_date = self._service_date_for_night_window()
        if not force:
            if not service_date:
                return False
            existing = self.search([
                ("service_date", "=", service_date),
                ("state", "in", ["running", "done"]),
            ], limit=1)
            if existing:
                return existing

        run = self.create({
            "service_date": service_date or fields.Date.context_today(self),
            "state": "running",
        })
        started = time.time()
        try:
            run._sync_contacts()
            run.write({
                "state": "done",
                "end_at": fields.Datetime.now(),
                "duration_seconds": time.time() - started,
                "message": _("Completed"),
            })
        except Exception as exc:
            _logger.exception("MISA CRM contact sync failed")
            run.write({
                "state": "failed",
                "end_at": fields.Datetime.now(),
                "duration_seconds": time.time() - started,
                "message": str(exc),
            })
        return run

    @api.model
    def _service_date_for_night_window(self):
        now_utc = fields.Datetime.now()
        local_now = now_utc + timedelta(hours=7)
        if local_now.hour >= 23:
            return local_now.date()
        if local_now.hour <= 5:
            return (local_now - timedelta(days=1)).date()
        return False

    def _sync_contacts(self):
        self.ensure_one()
        page_size = int(self.env["ir.config_parameter"].sudo().get_param(
            "misa.crm.contact_sync_page_size", "200"
        ) or 200)
        max_pages = int(self.env["ir.config_parameter"].sudo().get_param(
            "misa.crm.contact_sync_max_pages", "100"
        ) or 100)

        total = success = created = updated = unchanged = failed = 0
        page = 1
        while page <= max_pages:
            accounts = self._fetch_crm_account_page(page, page_size)
            if not accounts:
                break
            for account in accounts:
                total += 1
                result = self._sync_one_account(account)
                if result["state"] == "failed":
                    failed += 1
                else:
                    success += 1
                    if result["action"] == "created":
                        created += 1
                    elif result["action"] == "updated":
                        updated += 1
                    else:
                        unchanged += 1
                self.env["misa.crm.contact.sync.line"].create(dict(result, run_id=self.id))

            self.write({
                "total_count": total,
                "success_count": success,
                "created_count": created,
                "updated_count": updated,
                "unchanged_count": unchanged,
                "failed_count": failed,
                "page_count": page,
            })
            if len(accounts) < page_size:
                break
            page += 1

    def _fetch_crm_account_page(self, page, page_size):
        payload = {
            "Columns": MISA_CRM_COLUMNS,
            "Sorts": [{"SortBy": "ModifiedDate", "Type": 0, "SortDirection": 1}],
            "Start": (page - 1) * page_size,
            "Page": page,
            "PageSize": page_size,
            "Filters": [],
            "Formula": "",
            "LayoutCode": "Account",
            "DefaultTotal": True,
            "IsMappingData": False,
            "MappingValueObject": {},
            "IsApproved": False,
            "CustomPagingData": {},
            "IsUsedELTS": True,
            "ListGmailPage": [],
            "ListFacebookPage": {},
            "IsListPaging": True,
            "IsGetCache": False,
            "IsCheckInactive": False,
            "IsConverted": False,
            "SessionID": str(uuid.uuid4()),
            "LayoutCodeCheckPermission": "Account",
            "AISearchKeyword": "",
            "SkipNormalSearch": False,
        }
        headers = self.env["misa.api.utils"].sudo()._get_cached_crm_headers()
        response = requests.post(MISA_CRM_ACCOUNT_GRID_URL, headers=headers, json=payload, timeout=60)
        if response.status_code in (401, 403):
            headers = self.env["misa.api.utils"].sudo()._get_cached_crm_headers(force_refresh=True)
            response = requests.post(MISA_CRM_ACCOUNT_GRID_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        if data.get("Code") != 200 or data.get("Success") is not True:
            raise Exception("MISA CRM Account/Grid failed: %s" % json.dumps(data, ensure_ascii=False)[:500])
        return data.get("Data") or []

    def _sync_one_account(self, account):
        odoo_utils = self.env["odoo.utils"].sudo()
        account_number = (account.get("AccountNumber") or "").strip()
        tax_code = (account.get("TaxCode") or "").strip()
        account_name = (account.get("AccountName") or "").strip()
        misa_id = account.get("ID")

        base_result = {
            "misa_id": str(misa_id or ""),
            "account_number": account_number,
            "tax_code": tax_code,
            "account_name": account_name,
            "state": "done",
            "action": "unchanged",
            "change_summary": "",
            "change_json": "{}",
            "error_message": "",
        }
        try:
            if not account_number:
                raise Exception("Missing AccountNumber")

            tracked_fields = self._tracked_partner_fields()
            before_partner = self._find_partner_by_key(account_number, tax_code)
            before_values = self._partner_snapshot(before_partner, tracked_fields) if before_partner else {}
            partner = odoo_utils._get_or_create_partner(
                account_name or account_number,
                misa_code=account_number,
                tax_code=tax_code,
            )
            vals = self._values_from_crm_account(account, partner)
            if vals:
                partner.write(vals)
            after_values = self._partner_snapshot(partner, tracked_fields)
            changes = self._snapshot_diff(before_values, after_values)

            action = "created" if not before_partner else ("updated" if vals else "unchanged")
            if before_partner and changes:
                action = "updated"
            base_result.update({
                "partner_id": partner.id,
                "action": action,
                "change_summary": ", ".join(sorted(changes)) if changes else "",
                "change_json": json.dumps(changes, ensure_ascii=False, default=str),
            })
            return base_result
        except Exception as exc:
            base_result.update({
                "state": "failed",
                "action": "failed",
                "error_message": str(exc),
            })
            return base_result

    def _find_partner_by_key(self, account_number, tax_code):
        Partner = self.env["res.partner"].sudo().with_context(active_test=False)
        partners = Partner.search([
            ("parent_id", "=", False),
            ("is_company", "=", True),
            "|",
            ("ref", "=", account_number),
            ("company_registry", "=", account_number),
        ], order="active desc, id asc")
        if tax_code:
            tax_match = partners.filtered(lambda p: (p.vat or "").strip() == tax_code)[:1]
            no_tax = partners.filtered(lambda p: not (p.vat or "").strip())[:1]
            return tax_match or no_tax
        return partners[:1]

    def _values_from_crm_account(self, account, partner):
        vals = {}
        mapping = [
            ("AccountName", "name"),
            ("AccountNumber", "ref"),
            ("AccountNumber", "company_registry"),
            ("TaxCode", "vat"),
            ("OfficeTel", "phone"),
            ("OfficeEmail", "email"),
            ("BillingAddress", "street"),
            ("BillingProvinceIDText", "city"),
        ]
        for source_field, target_field in mapping:
            value = account.get(source_field)
            if isinstance(value, str):
                value = value.strip()
            if value and (partner[target_field] or False) != value:
                vals[target_field] = value
        if not partner.customer_rank:
            vals["customer_rank"] = 1
        if not partner.is_company:
            vals["is_company"] = True
        if not partner.active:
            vals["active"] = True
        return vals

    def _tracked_partner_fields(self):
        return [
            "name", "ref", "company_registry", "vat",
            "phone", "email", "street", "city",
            "customer_rank", "is_company", "active",
        ]

    def _partner_snapshot(self, partner, field_names):
        if not partner:
            return {}
        return {field_name: partner[field_name] or False for field_name in field_names}

    def _snapshot_diff(self, before, after):
        changes = {}
        for field_name, new_value in after.items():
            old_value = before.get(field_name, False)
            if old_value != new_value:
                changes[field_name] = {
                    "old": old_value or False,
                    "new": new_value or False,
                }
        return changes


class MisaCrmContactSyncLine(models.Model):
    _name = "misa.crm.contact.sync.line"
    _description = "MISA CRM Contact Sync Line"
    _order = "id asc"

    run_id = fields.Many2one("misa.crm.contact.sync.run", required=True, ondelete="cascade")
    partner_id = fields.Many2one("res.partner", string="Odoo Contact")
    misa_id = fields.Char(string="MISA ID")
    account_number = fields.Char(string="MISA Code")
    tax_code = fields.Char(string="Tax Code")
    account_name = fields.Char(string="CRM Name")
    state = fields.Selection([
        ("done", "Done"),
        ("failed", "Failed"),
    ], default="done", required=True)
    action = fields.Selection([
        ("created", "Created"),
        ("updated", "Updated"),
        ("unchanged", "Unchanged"),
        ("failed", "Failed"),
    ], default="unchanged", required=True)
    change_summary = fields.Char()
    change_json = fields.Text()
    error_message = fields.Text()
