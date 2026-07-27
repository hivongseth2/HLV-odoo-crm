#!/usr/bin/env python3
"""
Remap Odoo vendors from stale MISA codes ending in PM to their active base code.

Run in Odoo shell from the repository root.

Preview only (default):

    odoo-bin shell -d <database> --no-http < bin/remap_inactive_misa_pm_vendors.py

Apply changes:

    APPLY=1 odoo-bin shell -d <database> --no-http < bin/remap_inactive_misa_pm_vendors.py

Optional filters:

    AMIS_CONFIG_ID=1 APPLY=1 odoo-bin shell -d <database> --no-http \
        < bin/remap_inactive_misa_pm_vendors.py

The script creates downloadable CSV attachments in Odoo and prints their URLs.
Preview mode does not change vendor/cache mappings, but still commits the report
attachments so they remain downloadable.
"""

import base64
import csv
import io
import os
import re
from datetime import datetime


APPLY = "no"
CONFIG_ID = int(os.environ.get("AMIS_CONFIG_ID", "0") or 0)


def text(value):
    return str(value or "").strip()


def normalized_code(value):
    return re.sub(r"[^0-9A-Z]+", "", text(value).upper())


def pm_base_code(value):
    """Return the normalized base key when a code ends in PM."""
    raw = text(value).upper()
    if not raw.endswith("PM"):
        return ""
    base = re.sub(r"[\s_\-*./]+$", "", raw[:-2])
    return normalized_code(base)


def partner_url(partner):
    if not partner:
        return ""
    return "/web#id=%s&model=res.partner&view_type=form" % partner.id


def cache_url(cache):
    if not cache:
        return ""
    return "/web#id=%s&model=amis.misa.vendor.cache&view_type=form" % cache.id


def add_csv_attachment(filename, rows, columns):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    payload = ("\ufeff" + output.getvalue()).encode("utf-8")
    attachment = env["ir.attachment"].sudo().create(
        {
            "name": filename,
            "type": "binary",
            "mimetype": "text/csv",
            "datas": base64.b64encode(payload),
        }
    )
    base_url = (
        env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
    ).rstrip("/")
    relative_url = "/web/content/%s?download=true" % attachment.id
    absolute_url = "%s%s" % (base_url, relative_url) if base_url else relative_url
    return attachment, absolute_url, relative_url


Cache = env["amis.misa.vendor.cache"].sudo().with_context(active_test=False)
Partner = env["res.partner"].sudo().with_context(active_test=False)
BankCache = env["amis.misa.vendor.bank.cache"].sudo().with_context(active_test=False)

if CONFIG_ID:
    config = env["amis.callback.config"].sudo().browse(CONFIG_ID).exists()
    if not config:
        raise RuntimeError("Khong tim thay amis.callback.config id=%s" % CONFIG_ID)
    config_domain = [("config_id", "=", config.id)]
else:
    config_domain = []

partner_misa_fields = sorted(
    field_name
    for field_name, field in Partner._fields.items()
    if re.match(r"^misa.*account_object_id$", field_name)
    and field.type in ("char", "text")
    and field.store
    and (not field.compute or field.inverse)
)
if not partner_misa_fields:
    raise RuntimeError(
        "Khong tim thay truong res.partner co dang misa*_account_object_id."
    )

pm_caches = Cache.search(
    config_domain + [("is_vendor", "=", True)],
    order="config_id, account_object_code, id",
).filtered(lambda cache: bool(pm_base_code(cache.account_object_code)))

active_base_index = {}
active_base_caches = Cache.search(
    config_domain
    + [
        ("is_vendor", "=", True),
        ("misa_inactive", "=", False),
        ("is_deleted", "=", False),
    ]
).filtered(lambda cache: not pm_base_code(cache.account_object_code))
for active_cache in active_base_caches:
    index_key = (
        active_cache.config_id.id,
        normalized_code(active_cache.account_object_code),
    )
    active_base_index[index_key] = (
        active_base_index.get(index_key, Cache.browse()) | active_cache
    )

all_rows = []
unresolved_rows = []
remapped_count = 0
preview_count = 0

print("=" * 80)
print("MISA PM vendor remap")
print("Mode: %s" % ("APPLY" if APPLY else "PREVIEW"))
print("Config filter: %s" % (CONFIG_ID or "all"))
print("Partner MISA fields: %s" % ", ".join(partner_misa_fields))
print("PM vendor caches found: %s" % len(pm_caches))
print("=" * 80)

for index, pm_cache in enumerate(pm_caches, start=1):
    base_key = pm_base_code(pm_cache.account_object_code)
    stale_pm = bool(pm_cache.misa_inactive or pm_cache.is_deleted)
    base_candidates = active_base_index.get(
        (pm_cache.config_id.id, base_key),
        Cache.browse(),
    )

    linked_partners = Partner.browse()
    if pm_cache.partner_id:
        linked_partners |= pm_cache.partner_id
    for field_name in partner_misa_fields:
        linked_partners |= Partner.search(
            [(field_name, "=", pm_cache.account_object_id)]
        )
    linked_partners = linked_partners.exists()

    base_cache = base_candidates[:1]
    partner = linked_partners[:1]
    matching_partner_fields = [
        field_name
        for field_name in partner_misa_fields
        if partner
        and text(partner[field_name]).lower()
        == text(pm_cache.account_object_id).lower()
    ]
    partner_misa_before = "; ".join(
        "%s=%s" % (field_name, text(partner[field_name]))
        for field_name in partner_misa_fields
    ) if partner else ""
    partner_ref_before = text(partner.ref) if partner else ""
    partner_ref_is_same_pm_variant = bool(
        partner and pm_base_code(partner.ref) == base_key
    )
    partner_ref_is_compatible = bool(
        not partner
        or not partner_ref_before
        or normalized_code(partner_ref_before) == base_key
        or partner_ref_is_same_pm_variant
    )
    status = ""
    detail = ""

    if not stale_pm:
        status = "bo_qua_pm_con_hoat_dong"
        detail = "Cache PM chua ngung su dung va chua bi xoa tren MISA."
    elif not base_candidates:
        status = "khong_co_cap_goc"
        detail = "Khong tim thay cache NCC goc dang hoat dong co cung ma co so."
    elif len(base_candidates) > 1:
        status = "nhieu_cap_goc"
        detail = "Tim thay %s cache goc dang hoat dong; khong tu chon." % len(
            base_candidates
        )
    elif len(linked_partners) > 1:
        status = "nhieu_partner_dang_map_pm"
        detail = "Co %s partner Odoo dang map cung ID PM; can xu ly tay." % len(
            linked_partners
        )
    elif partner and not matching_partner_fields:
        status = "id_misa_partner_khong_khop_cache_pm"
        detail = (
            "Cache PM co partner_id nhung cac truong misa*_account_object_id "
            "cua partner khong map ID PM; khong tu dong sua."
        )
    elif partner and not partner_ref_is_compatible:
        status = "ma_ncc_odoo_khong_khop_cap_pm"
        detail = (
            "Ma NCC Odoo khong cung ma co so voi cap PM/goc; "
            "khong tu dong remap de tranh ghi sai NCC MISA."
        )
    elif (
        base_cache.partner_id
        and linked_partners
        and base_cache.partner_id != linked_partners
    ):
        status = "xung_dot_partner_cap_goc"
        detail = (
            "Cache goc dang map partner #%s, cache PM dang map partner #%s."
            % (base_cache.partner_id.id, linked_partners.id)
        )
    else:
        if not partner:
            status = "khong_co_partner_odoo"
            detail = "Cache PM khong con lien ket voi partner Odoo nao."
        elif APPLY:
            write_vals = {
                field_name: base_cache.account_object_id
                for field_name in matching_partner_fields
            }
            if partner_ref_is_same_pm_variant:
                write_vals["ref"] = base_cache.account_object_code
            partner.with_context(skip_misa_partner_sync=True).write(write_vals)
            pm_cache.write({"partner_id": False})
            BankCache.search(
                [("vendor_cache_id", "=", pm_cache.id)]
            ).write({"partner_bank_id": False})
            if not base_cache.partner_id:
                base_cache.write({"partner_id": partner.id})
            status = "da_remap"
            detail = "Da map partner sang ID MISA cua cache goc."
            remapped_count += 1
        else:
            status = "se_remap"
            detail = "Du dieu kien remap khi chay voi APPLY=1."
            preview_count += 1

    row = {
        "stt": index,
        "trang_thai": status,
        "chi_tiet": detail,
        "config_id": pm_cache.config_id.id,
        "config": pm_cache.config_id.display_name,
        "pm_cache_id": pm_cache.id,
        "pm_cache_url": cache_url(pm_cache),
        "pm_id_misa": pm_cache.account_object_id,
        "pm_ma_misa": pm_cache.account_object_code,
        "pm_ten_misa": pm_cache.account_object_name,
        "pm_ma_so_thue": pm_cache.company_tax_code,
        "pm_ngung_su_dung": pm_cache.misa_inactive,
        "pm_da_xoa": pm_cache.is_deleted,
        "ma_co_so": base_key,
        "so_cap_goc": len(base_candidates),
        "goc_cache_id": base_cache.id or "",
        "goc_cache_url": cache_url(base_cache),
        "goc_id_misa": base_cache.account_object_id or "",
        "goc_ma_misa": base_cache.account_object_code or "",
        "goc_ten_misa": base_cache.account_object_name or "",
        "partner_id": partner.id or "",
        "partner_url": partner_url(partner),
        "partner_ten": partner.display_name or "",
        "partner_ma_truoc": partner_ref_before,
        "partner_ma_sau": partner.ref or "",
        "partner_ma_so_thue": partner.vat or "",
        "partner_misa_id_truoc": partner_misa_before,
    }
    all_rows.append(row)
    if status not in {"da_remap", "se_remap"}:
        unresolved_rows.append(row)

    print(
        "[%s/%s] %s -> %s | partner=%s | %s"
        % (
            index,
            len(pm_caches),
            pm_cache.account_object_code or pm_cache.account_object_id,
            base_cache.account_object_code or "-",
            partner.id or "-",
            status,
        )
    )

columns = [
    "stt",
    "trang_thai",
    "chi_tiet",
    "config_id",
    "config",
    "pm_cache_id",
    "pm_cache_url",
    "pm_id_misa",
    "pm_ma_misa",
    "pm_ten_misa",
    "pm_ma_so_thue",
    "pm_ngung_su_dung",
    "pm_da_xoa",
    "ma_co_so",
    "so_cap_goc",
    "goc_cache_id",
    "goc_cache_url",
    "goc_id_misa",
    "goc_ma_misa",
    "goc_ten_misa",
    "partner_id",
    "partner_url",
    "partner_ten",
    "partner_ma_truoc",
    "partner_ma_sau",
    "partner_ma_so_thue",
    "partner_misa_id_truoc",
]

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
mode = "apply" if APPLY else "preview"
audit_attachment, audit_url, audit_relative_url = add_csv_attachment(
    "misa_pm_vendor_remap_%s_%s.csv" % (mode, timestamp),
    all_rows,
    columns,
)
unresolved_attachment, unresolved_url, unresolved_relative_url = add_csv_attachment(
    "misa_pm_vendor_chua_xu_ly_%s_%s.csv" % (mode, timestamp),
    unresolved_rows,
    columns,
)

env.cr.commit()

print("=" * 80)
print("Eligible in preview: %s" % preview_count)
print("Remapped: %s" % remapped_count)
print("Unresolved/skipped: %s" % len(unresolved_rows))
print("Audit attachment #%s: %s" % (audit_attachment.id, audit_url))
print("Audit relative URL: %s" % audit_relative_url)
print(
    "Unresolved attachment #%s: %s"
    % (unresolved_attachment.id, unresolved_url)
)
print("Unresolved relative URL: %s" % unresolved_relative_url)
print("=" * 80)
