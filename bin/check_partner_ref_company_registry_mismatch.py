# -*- coding: utf-8 -*-
"""
check_partner_ref_company_registry_mismatch.py
=============================================
Audit res.partner company records where ref and company_registry should match
but currently differ.

Run:
    odoo-bin shell -c <odoo.conf> --no-http < bin/check_partner_ref_company_registry_mismatch.py
"""

SEP = "=" * 100
SEP2 = "-" * 100


def section(title):
    print("\n%s\n  %s\n%s" % (SEP, title, SEP))


def norm(value):
    return (value or "").strip()


def display(value):
    value = norm(value)
    return value if value else "(empty)"


Partner = env["res.partner"].sudo().with_context(active_test=False)

section("ROOT COMPANIES: ref != company_registry")

companies = Partner.search([
    ("parent_id", "=", False),
    ("is_company", "=", True),
    "|",
    ("ref", "!=", False),
    ("company_registry", "!=", False),
], order="name asc, id asc")

mismatches = companies.filtered(
    lambda p: norm(p.ref) and norm(p.company_registry) and norm(p.ref) != norm(p.company_registry)
)
missing_one_side = companies.filtered(
    lambda p: (bool(norm(p.ref)) != bool(norm(p.company_registry)))
)

print("  Total root companies with code fields : %s" % len(companies))
print("  Mismatched ref/company_registry       : %s" % len(mismatches))
print("  Only one side has value               : %s" % len(missing_one_side))

print("\n  %8s  %-7s  %-45s  %-22s  %-22s  %5s  %5s  %5s" % (
    "ID", "ACTIVE", "NAME", "REF", "COMPANY_REGISTRY", "SO", "PO", "CHILD"
))
print("  %s" % SEP2)

for p in mismatches:
    so_count = env["sale.order"].sudo().search_count([("partner_id", "=", p.id)])
    po_count = env["purchase.order"].sudo().search_count([("partner_id", "=", p.id)])
    child_count = Partner.search_count([("parent_id", "=", p.id)])
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

section("ROOT COMPANIES: only ref or only company_registry")

if not missing_one_side:
    print("  None")
else:
    print("\n  %8s  %-7s  %-45s  %-22s  %-22s" % (
        "ID", "ACTIVE", "NAME", "REF", "COMPANY_REGISTRY"
    ))
    print("  %s" % SEP2)
    for p in missing_one_side:
        print("  %8s  %-7s  %-45s  %-22s  %-22s" % (
            p.id,
            str(p.active),
            (p.name or "")[:45],
            display(p.ref)[:22],
            display(p.company_registry)[:22],
        ))

section("CODE ALSO USED BY NON-ROOT / NON-COMPANY PARTNERS")

codes = sorted(set([norm(p.ref) for p in companies] + [norm(p.company_registry) for p in companies]) - {""})
non_root_hits = Partner.search([
    ("id", "not in", companies.ids or [0]),
    "|",
    ("ref", "in", codes),
    ("company_registry", "in", codes),
], order="name asc, id asc")

if not non_root_hits:
    print("  None")
else:
    print("\n  %8s  %-7s  %-10s  %-8s  %-45s  %-22s  %-22s" % (
        "ID", "ACTIVE", "COMPANY", "PARENT", "NAME", "REF", "COMPANY_REGISTRY"
    ))
    print("  %s" % SEP2)
    for p in non_root_hits:
        print("  %8s  %-7s  %-10s  %-8s  %-45s  %-22s  %-22s" % (
            p.id,
            str(p.active),
            str(p.is_company),
            p.parent_id.id if p.parent_id else "",
            (p.name or "")[:45],
            display(p.ref)[:22],
            display(p.company_registry)[:22],
        ))

section("SUMMARY")
print("  Mismatched root companies : %s" % len(mismatches))
print("  Missing one side          : %s" % len(missing_one_side))
print("  Non-root/code reuse hits  : %s" % len(non_root_hits))
print("\n  Done.")
