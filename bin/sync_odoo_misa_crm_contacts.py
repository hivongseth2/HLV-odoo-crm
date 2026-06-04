# -*- coding: utf-8 -*-
"""
sync_odoo_misa_crm_contacts.py
==============================
Sync thong tin cong ty tu MISA CRM Account/Grid ve Odoo res.partner.

Dung cho case sau khi da archive/merge duplicate company:
  - Fetch MISA CRM theo ten cong ty.
  - Validate/match bang ma khach hang MISA: AccountNumber.
  - Odoo match ma bang ref hoac company_registry.
  - Update thong tin cong ty Odoo tu MISA CRM neu tim dung ma.

Chay trong odoo shell:
    $env:MISA_CRM_AUTHORIZATION="Bearer <token>"
    odoo-bin shell -c <odoo.conf> --no-http < bin/sync_odoo_misa_crm_contacts.py

DRY_RUN mac dinh True. Doi DRY_RUN=False de ghi that.
"""

import json
import os
import re
import time
import unicodedata
import uuid

import requests


DRY_RUN = False
CREATE_MISSING_ROOT = True
MISA_FETCH_ATTEMPTS = 3

# False: chỉ chạy TARGET_NAMES bên dưới.
# True : lấy toàn bộ root customer trong Odoo, trừ khách Shopee nếu EXCLUDE_SHOPEE_PARTNERS=True.
SYNC_ALL_ODOO_CUSTOMERS = False
EXCLUDE_SHOPEE_PARTNERS = True
SYNC_ALL_LIMIT = 0  # 0 = no limit

get_param = env['ir.config_parameter'].sudo().get_param
TARGET_NAMES = [
    "CÔNG TY TRÁCH NHIỆM HỮU HẠN DONGJIN TEXTILE VINA",
    "CÔNG TY TNHH MILWAUKEE TOOL (VIỆT NAM)",
    "CHI NHÁNH CÔNG TY TNHH BOSCH VIỆT NAM TẠI THÀNH PHỐ HỒ CHÍ MINH",
]

MISA_CRM_URL = "https://amisapp.misa.vn/crm/g2/api/business/Account/Grid"
MISA_CRM_COMPANY_CODE = get_param("misa.crm.company_code") or "3R2PY2F4"
MISA_CRM_AUTHORIZATION = (
    get_param("misa.crm.authorization")
    or get_param("MISA_CRM_AUTHORIZATION")
    or os.environ.get("MISA_CRM_AUTHORIZATION", "")
).strip()

# MISA CRM yeu cau giu nguyen Columns nay de tra du field.
MISA_CRM_COLUMNS = (
    "SUQsVGFnSUQsVGFnSURUZXh0LEFjY291bnROdW1iZXIsQWNjb3VudFR5cGVJRCxBY2NvdW50"
    "VHlwZUlEVGV4dCxBY2NvdW50TmFtZSxUYXhDb2RlLE9mZmljZVRlbCxPZmZpY2VFbWFpbCxTZWN0"
    "b3JJRCxTZWN0b3JJRFRleHQsQmlsbGluZ0FkZHJlc3MsQmlsbGluZ1Byb3ZpbmNlSUQsQmls"
    "bGluZ1Byb3ZpbmNlSURUZXh0LEJpbGxpbmdEaXN0cmljdElELEJpbGxpbmdEaXN0cmljdElE"
    "VGV4dCxCaWxsaW5nV2FyZElELEJpbGxpbmdXYXJkSURUZXh0LERlc2NyaXB0aW9uLE93bmVy"
    "SUQsT3duZXJJRFRleHQsTGVhZFNvdXJjZUlELExlYWRTb3VyY2VJRFRleHQsRm9ybUxheW91"
    "dElELEZvcm1MYXlvdXRJRFRleHQsQXZhdGFyLEluYWN0aXZlLElzQ29ycA=="
)

SEP = "=" * 92
SEP2 = "-" * 92


def section(title):
    print("\n%s\n  %s\n%s" % (SEP, title, SEP))


def norm_code(value):
    return (value or "").strip().upper().replace(" ", "")


def norm_text(value):
    value = (value or "").strip().upper()
    value = unicodedata.normalize("NFC", value)
    value = re.sub(r"\s+", " ", value)
    return value


def clean(value):
    if value is None:
        return False
    if isinstance(value, str):
        value = value.strip()
    return value or False


def misa_headers():
    if not MISA_CRM_AUTHORIZATION:
        raise Exception(
            "Thieu MISA_CRM_AUTHORIZATION. Set bien moi truong: "
            '$env:MISA_CRM_AUTHORIZATION="Bearer <token>"'
        )
    return {
        "accept": "application/json, text/plain, */*",
        "authorization": MISA_CRM_AUTHORIZATION,
        "companycode": MISA_CRM_COMPANY_CODE,
        "content-type": "application/json",
        "layoutcode": "account",
        "x-misa-language": "vi-VN",
    }


def misa_payload(keyword, page=1, page_size=20, use_cache=False):
    session_id = str(uuid.uuid4())
    return {
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
        "IsGetCache": use_cache,
        "IsCheckInactive": False,
        "IsConverted": False,
        "SessionID": session_id,
        "LayoutCodeCheckPermission": "Account",
        "AISearchKeyword": keyword,
        "SkipNormalSearch": False,
    }


def fetch_misa_accounts(keyword):
    expected_name = norm_text(keyword)
    last_raw = []

    for attempt in range(1, MISA_FETCH_ATTEMPTS + 1):
        resp = requests.post(
            MISA_CRM_URL,
            headers=misa_headers(),
            data=json.dumps(
                misa_payload(keyword, use_cache=False),
                ensure_ascii=False,
            ).encode("utf-8"),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("Code") != 200 or data.get("Success") is not True:
            raise Exception("MISA CRM loi: Code=%s SubCode=%s raw=%s" % (
                data.get("Code"), data.get("SubCode"), json.dumps(data, ensure_ascii=False)[:500]
            ))

        raw_accounts = data.get("Data") or []
        last_raw = raw_accounts
        matched = [
            account for account in raw_accounts
            if norm_text(account.get("AccountName")) == expected_name
        ]

        if matched:
            if len(matched) != len(raw_accounts):
                print("  [WARN] MISA attempt %s returned %s raw rows, keep %s exact AccountName match(es)" % (
                    attempt, len(raw_accounts), len(matched)
                ))
            return matched

        print("  [WARN] MISA attempt %s returned %s raw rows but 0 exact AccountName matches; retry..." % (
            attempt, len(raw_accounts)
        ))
        time.sleep(0.8)

    sample = [
        "%s:%s" % (a.get("AccountNumber"), a.get("AccountName"))
        for a in last_raw[:5]
    ]
    raise Exception(
        "MISA search khong tra ve AccountName khop keyword sau %s lan. "
        "Raw rows=%s sample=%s" % (MISA_FETCH_ATTEMPTS, len(last_raw), sample)
    )


def odoo_domain_for_misa_code(misa_code):
    return [
        ("active", "in", [True, False]),
        "|",
        ("ref", "=", misa_code),
        ("company_registry", "=", misa_code),
    ]


def partner_codes(partner):
    return set(filter(None, [norm_code(partner.ref), norm_code(partner.company_registry)]))


def find_partner_for_account(account):
    misa_code = clean(account.get("AccountNumber"))
    tax_code = clean(account.get("TaxCode"))
    if not misa_code:
        return env["res.partner"], env["res.partner"]

    exact = env["res.partner"].sudo().with_context(active_test=False).search(
        odoo_domain_for_misa_code(misa_code),
        order="active desc, is_company desc, parent_id asc, id asc",
    )
    exact_company = exact.filtered(
        lambda p: p.is_company and not p.parent_id
        and ((p.ref or "").strip() == misa_code
             or (not p.ref and (p.company_registry or "").strip() == misa_code))
    )
    if tax_code:
        tax_match = exact_company.filtered(lambda p: (p.vat or "").strip() == tax_code)
        no_tax = exact_company.filtered(lambda p: not (p.vat or "").strip())
        if tax_match:
            return tax_match, exact - tax_match
        if no_tax:
            return no_tax, exact - no_tax
        return env["res.partner"], exact
    if exact_company:
        return exact_company, exact - exact_company

    misa_norm = norm_code(misa_code)
    candidates = env["res.partner"].sudo().with_context(active_test=False).search([
        ("active", "in", [True, False]),
        "|",
        ("ref", "!=", False),
        ("company_registry", "!=", False),
    ]).filtered(lambda p: misa_norm in partner_codes(p))
    company_candidates = candidates.filtered(
        lambda p: p.is_company and not p.parent_id
        and ((p.ref or "").strip() == misa_code
             or (not p.ref and (p.company_registry or "").strip() == misa_code))
    )
    if tax_code:
        tax_match = company_candidates.filtered(lambda p: (p.vat or "").strip() == tax_code)
        no_tax = company_candidates.filtered(lambda p: not (p.vat or "").strip())
        if tax_match:
            return tax_match, candidates - tax_match
        if no_tax:
            return no_tax, candidates - no_tax
        return env["res.partner"], candidates
    return company_candidates, candidates - company_candidates


def values_from_misa(account, partner):
    vals = {}

    mapping = [
        ("TaxCode", "vat"),
        ("OfficeTel", "phone"),
        ("OfficeEmail", "email"),
        ("BillingAddress", "street"),
        ("BillingProvinceIDText", "city"),
    ]
    for misa_field, odoo_field in mapping:
        value = clean(account.get(misa_field))
        if value and (partner[odoo_field] or False) != value:
            vals[odoo_field] = value

    return vals


def create_values_from_misa(account):
    misa_code = clean(account.get("AccountNumber"))
    vals = {
        "name": clean(account.get("AccountName")) or misa_code,
        "is_company": True,
        "customer_rank": 1,
        "ref": misa_code,
        "company_registry": misa_code,
    }
    mapping = [
        ("TaxCode", "vat"),
        ("OfficeTel", "phone"),
        ("OfficeEmail", "email"),
        ("BillingAddress", "street"),
        ("BillingProvinceIDText", "city"),
    ]
    for misa_field, odoo_field in mapping:
        value = clean(account.get(misa_field))
        if value:
            vals[odoo_field] = value
    return vals


def describe_partner(partner):
    return "id=%s active=%s is_company=%s parent=%s name=%s ref=%r company_registry=%r" % (
        partner.id,
        partner.active,
        partner.is_company,
        partner.parent_id.id if partner.parent_id else None,
        partner.name,
        partner.ref,
        partner.company_registry,
    )


def shopee_sale_order_domain():
    SaleOrder = env["sale.order"].sudo()
    fields = SaleOrder._fields
    clauses = []
    for field_name in ("shopee_order_ref", "x_studio_tham_chiu_shopee", "shopee_shop_id"):
        if field_name in fields:
            clauses.append((field_name, "!=", False))

    if not clauses:
        return []
    if len(clauses) == 1:
        return clauses
    return ["|"] * (len(clauses) - 1) + clauses


def shopee_commercial_partner_ids():
    if not EXCLUDE_SHOPEE_PARTNERS:
        return set()

    domain = shopee_sale_order_domain()
    if not domain:
        return set()

    SaleOrder = env["sale.order"].sudo()
    orders = SaleOrder.search(domain)
    partners = env["res.partner"].sudo()
    for order in orders:
        for partner in (order.partner_id, order.partner_invoice_id, order.partner_shipping_id):
            if partner:
                partners |= partner.commercial_partner_id
    return set(partners.ids)


def target_names_from_odoo():
    if not SYNC_ALL_ODOO_CUSTOMERS:
        return TARGET_NAMES

    Partner = env["res.partner"].sudo().with_context(active_test=False)
    excluded_ids = shopee_commercial_partner_ids()

    domain = [
        ("parent_id", "=", False),
        ("is_company", "=", True),
        ("customer_rank", ">", 0),
        ("active", "=", True),
    ]
    if excluded_ids:
        domain.append(("id", "not in", list(excluded_ids)))

    partners = Partner.search(domain, order="name asc", limit=SYNC_ALL_LIMIT or None)
    names = []
    seen = set()
    for partner in partners:
        name = clean(partner.name)
        key = norm_text(name)
        if name and key not in seen:
            names.append(name)
            seen.add(key)

    print("  SYNC_ALL_ODOO_CUSTOMERS=True")
    print("  Excluded Shopee commercial partners: %s" % len(excluded_ids))
    print("  Odoo target root customer names    : %s" % len(names))
    return names


section("SYNC ODOO CONTACTS FROM MISA CRM")
print("  DRY_RUN=%s" % DRY_RUN)
print("  CREATE_MISSING_ROOT=%s" % CREATE_MISSING_ROOT)
print("  SYNC_ALL_ODOO_CUSTOMERS=%s" % SYNC_ALL_ODOO_CUSTOMERS)
print("  EXCLUDE_SHOPEE_PARTNERS=%s" % EXCLUDE_SHOPEE_PARTNERS)
targets = target_names_from_odoo()
print("  Target names: %s" % len(targets))

total_accounts = 0
matched_accounts = 0
updated_partners = 0
skipped_accounts = 0
errors = 0

for keyword in targets:
    section("FETCH MISA CRM: %s" % keyword)
    try:
        accounts = fetch_misa_accounts(keyword)
    except Exception as exc:
        errors += 1
        print("  [ERROR] Khong fetch duoc MISA: %s" % exc)
        continue

    total_accounts += len(accounts)
    print("  MISA tra ve %s account(s)" % len(accounts))

    for account in accounts:
        misa_code = clean(account.get("AccountNumber"))
        print("\n  %s" % SEP2)
        print("  MISA ID=%s code=%r inactive=%s name=%s" % (
            account.get("ID"),
            misa_code,
            account.get("Inactive"),
            account.get("AccountName"),
        ))
        print("       tax=%r phone=%r email=%r" % (
            account.get("TaxCode"), account.get("OfficeTel"), account.get("OfficeEmail")
        ))

        if not misa_code:
            skipped_accounts += 1
            print("  [SKIP] MISA account khong co AccountNumber")
            continue

        partners, non_company_matches = find_partner_for_account(account)
        if non_company_matches:
            print("  Note: ma nay cung nam tren partner khong phai match chinh theo ref/code:")
            for p in non_company_matches:
                print("       - %s" % describe_partner(p))

        if not partners:
            create_vals = create_values_from_misa(account)
            if CREATE_MISSING_ROOT:
                print("  CREATE root company by key %s-%s vals=%s" % (
                    account.get("TaxCode") or "-",
                    misa_code,
                    json.dumps(create_vals, ensure_ascii=False, default=str),
                ))
                if not DRY_RUN:
                    partner = env["res.partner"].sudo().create(create_vals)
                    partner.message_post(body=(
                        "Created from MISA CRM Account/Grid by key %s-%s. MISA ID=%s"
                    ) % (account.get("TaxCode") or "-", misa_code, account.get("ID")))
                updated_partners += 1
            else:
                skipped_accounts += 1
                print("  [SKIP] Odoo khong co root company dung key tax+code=%r-%r" % (
                    account.get("TaxCode"), misa_code
                ))
            continue

        active_partners = partners.filtered(lambda p: p.active)
        if len(active_partners) > 1:
            skipped_accounts += 1
            print("  [SKIP] Co nhieu Odoo partner active cung ma %r, can xu ly tay:" % misa_code)
            for p in active_partners:
                print("       - %s" % describe_partner(p))
            continue

        partner = active_partners[:1] or partners[:1]
        matched_accounts += 1
        print("  Odoo match: %s" % describe_partner(partner))

        vals = values_from_misa(account, partner)
        if account.get("TaxCode") and not partner.vat:
            vals["vat"] = clean(account.get("TaxCode"))
        if misa_code:
            if not partner.ref:
                vals["ref"] = misa_code
            if not partner.company_registry:
                vals["company_registry"] = misa_code
        if not vals:
            print("  OK khong co field can update")
            continue

        print("  Update vals: %s" % json.dumps(vals, ensure_ascii=False, default=str))
        if not DRY_RUN:
            try:
                partner.sudo().write(vals)
                partner.message_post(body=(
                    "Synced from MISA CRM Account/Grid. "
                    "MISA ID=%s, AccountNumber=%s, fields=%s"
                ) % (account.get("ID"), misa_code, ", ".join(sorted(vals))))
                updated_partners += 1
                print("  UPDATED")
            except Exception as exc:
                errors += 1
                print("  [ERROR] Ghi Odoo loi: %s" % exc)
        else:
            updated_partners += 1
            print("  DRY RUN - chua ghi")

    time.sleep(0.2)

if not DRY_RUN:
    env.cr.commit()

section("SUMMARY")
print("  MISA accounts fetched : %s" % total_accounts)
print("  Accounts matched      : %s" % matched_accounts)
print("  Partners to update    : %s" % updated_partners)
print("  Skipped accounts      : %s" % skipped_accounts)
print("  Errors                : %s" % errors)
print("  Commit                : %s" % ("NO (DRY_RUN)" if DRY_RUN else "YES"))
print("\n  Done.")
