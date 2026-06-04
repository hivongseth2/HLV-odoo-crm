# -*- coding: utf-8 -*-
"""
fix_legacy_partner_misa_codes.py
================================
Clean legacy MISA/CRM customer codes from res.partner.

Problem found:
  - Company customer code should live on root company only.
  - Old import/sync code copied CRM code to delivery/contact partners.
  - Some root companies have ref/company_registry missing or mismatched.

Safe fixes performed when DRY_RUN = False:
  1. Clear ref/company_registry on non-root partners and non-company partners
     when the value looks like a root company customer code.
  2. For root companies where only one of ref/company_registry is set, copy it
     to the missing side so both fields match.

Risky cases only reported by default:
  - Root companies where ref and company_registry are both set but different.
    These may represent distinct CRM accounts that were incorrectly merged
    into one Odoo partner. The script does not auto-split orders.

Run:
    odoo-bin shell -c <odoo.conf> --no-http < bin/fix_legacy_partner_misa_codes.py
"""

DRY_RUN = False

# For root companies where ref and company_registry differ:
#   - create a new root company for the secondary code company_registry, using
#     the same VAT/name/address.
#   - normalize the original root company back to company_registry = ref.
# This does not split historical SO/PO data.
CREATE_ROOT_FOR_MISMATCH_SECONDARY_CODE = True
FIX_ROOT_MISMATCH_BY_REF = True

SEP = "=" * 100
SEP2 = "-" * 100


def section(title):
    print("\n%s\n  %s\n%s" % (SEP, title, SEP))


def norm(value):
    return (value or "").strip()


def display(value):
    value = norm(value)
    return value if value else "(empty)"


def partner_info(p):
    return "id=%s active=%s is_company=%s parent=%s name=%s ref=%r company_registry=%r" % (
        p.id,
        p.active,
        p.is_company,
        p.parent_id.id if p.parent_id else None,
        p.name,
        p.ref,
        p.company_registry,
    )


def write_partner(partner, vals, reason):
    print("  %s id=%s vals=%s | %s" % (
        "DRY" if DRY_RUN else "FIX",
        partner.id,
        vals,
        reason,
    ))
    if not DRY_RUN:
        partner.write(vals)


Partner = env["res.partner"].sudo().with_context(active_test=False)

section("LOAD ROOT COMPANY CODES")

root_companies = Partner.search([
    ("parent_id", "=", False),
    ("is_company", "=", True),
    "|",
    ("ref", "!=", False),
    ("company_registry", "!=", False),
], order="name asc, id asc")

root_codes = set()
for p in root_companies:
    if norm(p.ref):
        root_codes.add(norm(p.ref))
    if norm(p.company_registry):
        root_codes.add(norm(p.company_registry))

print("  Root companies with codes : %s" % len(root_companies))
print("  Unique code values        : %s" % len(root_codes))

section("1. CLEAR LEGACY CODES FROM CONTACT / NON-ROOT PARTNERS")

legacy_contacts = Partner.search([
    "|",
    ("parent_id", "!=", False),
    ("is_company", "=", False),
    "|",
    ("ref", "!=", False),
    ("company_registry", "!=", False),
], order="name asc, id asc")

to_clear = []
for p in legacy_contacts:
    vals = {}
    reasons = []

    p_ref = norm(p.ref)
    p_reg = norm(p.company_registry)

    if p_ref and p_ref in root_codes:
        vals["ref"] = False
        reasons.append("ref is root-company code")
    if p_reg and p_reg in root_codes:
        vals["company_registry"] = False
        reasons.append("company_registry is root-company code")

    # Delivery/contact partner should not carry customer code even when the
    # parent is missing or dirty. Keep unrelated values for manual review.
    if vals:
        to_clear.append((p, vals, ", ".join(reasons)))

print("  Contacts/non-root with code fields : %s" % len(legacy_contacts))
print("  Safe clear candidates              : %s" % len(to_clear))
print("  %s" % SEP2)

for p, vals, reason in to_clear:
    write_partner(p, vals, "%s | %s" % (reason, partner_info(p)))

section("2. FILL MISSING CODE SIDE ON ROOT COMPANIES")

missing_side = []
for p in root_companies:
    p_ref = norm(p.ref)
    p_reg = norm(p.company_registry)
    if p_ref and not p_reg:
        missing_side.append((p, {"company_registry": p_ref}, "company_registry empty, copy ref"))
    elif p_reg and not p_ref:
        missing_side.append((p, {"ref": p_reg}, "ref empty, copy company_registry"))

print("  Root companies missing one side : %s" % len(missing_side))
print("  %s" % SEP2)

for p, vals, reason in missing_side:
    write_partner(p, vals, "%s | %s" % (reason, partner_info(p)))

section("3. ROOT COMPANIES WITH ref != company_registry")

root_mismatch = []
for p in root_companies:
    p_ref = norm(p.ref)
    p_reg = norm(p.company_registry)
    if p_ref and p_reg and p_ref != p_reg:
        so_count = env["sale.order"].sudo().search_count([("partner_id", "=", p.id)])
        po_count = env["purchase.order"].sudo().search_count([("partner_id", "=", p.id)])
        child_count = Partner.search_count([("parent_id", "=", p.id)])
        root_mismatch.append((p, so_count, po_count, child_count))

print("  Root mismatches : %s" % len(root_mismatch))
print("  CREATE_ROOT_FOR_MISMATCH_SECONDARY_CODE=%s" % CREATE_ROOT_FOR_MISMATCH_SECONDARY_CODE)
print("  FIX_ROOT_MISMATCH_BY_REF=%s" % FIX_ROOT_MISMATCH_BY_REF)
print("\n  %8s  %-7s  %-45s  %-22s  %-22s  %5s  %5s  %5s" % (
    "ID", "ACTIVE", "NAME", "REF", "COMPANY_REGISTRY", "SO", "PO", "CHILD"
))
print("  %s" % SEP2)

for p, so_count, po_count, child_count in root_mismatch:
    print("  %8s  %-7s  %-45s  %-22s  %-22s  %5s  %5s  %5s" % (
        p.id,
        str(p.active),
        (p.name or "")[:45],
        display(p.ref)[:22],
        display(p.company_registry)[:22],
        so_count,
        po_count,
        child_count,
    ))
    secondary_code = norm(p.company_registry)
    tax_code = norm(p.vat)
    if CREATE_ROOT_FOR_MISMATCH_SECONDARY_CODE and secondary_code and tax_code:
        existing_secondary = Partner.search([
            ("parent_id", "=", False),
            ("is_company", "=", True),
            ("vat", "=", tax_code),
            "|",
            ("ref", "=", secondary_code),
            ("company_registry", "=", secondary_code),
        ], limit=1)
        if existing_secondary:
            print("  SKIP create secondary: key %s-%s already exists at id=%s" % (
                tax_code, secondary_code, existing_secondary.id
            ))
        else:
            vals = {
                "name": p.name,
                "is_company": True,
                "customer_rank": p.customer_rank,
                "supplier_rank": p.supplier_rank,
                "vat": tax_code,
                "ref": secondary_code,
                "company_registry": secondary_code,
                "phone": p.phone,
                "mobile": p.mobile,
                "email": p.email,
                "street": p.street,
                "street2": p.street2,
                "city": p.city,
                "zip": p.zip,
                "country_id": p.country_id.id if p.country_id else False,
                "state_id": p.state_id.id if p.state_id else False,
            }
            print("  %s create secondary root vals=%s | from id=%s key=%s-%s" % (
                "DRY" if DRY_RUN else "FIX",
                vals,
                p.id,
                tax_code,
                secondary_code,
            ))
            if not DRY_RUN:
                Partner.create(vals)
    elif CREATE_ROOT_FOR_MISMATCH_SECONDARY_CODE and secondary_code and not tax_code:
        print("  SKIP create secondary for id=%s code=%s because VAT is empty" % (p.id, secondary_code))

    if FIX_ROOT_MISMATCH_BY_REF:
        write_partner(
            p,
            {"company_registry": norm(p.ref)},
            "normalize root mismatch by canonical ref | %s" % partner_info(p),
        )

if not DRY_RUN:
    env.cr.commit()

section("SUMMARY")
print("  DRY_RUN                         : %s" % DRY_RUN)
print("  Cleared contact/non-root codes  : %s" % len(to_clear))
print("  Filled missing root code side   : %s" % len(missing_side))
print("  Root mismatches reported        : %s" % len(root_mismatch))
print("  Commit                          : %s" % ("NO" if DRY_RUN else "YES"))
print("\n  Done.")
