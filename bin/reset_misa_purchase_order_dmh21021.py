#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reset the MISA identity of purchase order DMH21021 and enqueue a fresh sync.

Run from an Odoo.sh shell at the repository root.

Preview only (default, no database changes):

    odoo-bin shell -d "$PGDATABASE" --no-http \
        < bin/reset_misa_purchase_order_dmh21021.py

Apply:

    APPLY=1 odoo-bin shell -d "$PGDATABASE" --no-http \
        < bin/reset_misa_purchase_order_dmh21021.py

The script must only be applied after the old purchase order has actually been
revoked/deleted on MISA. It deliberately keeps completed/error/skipped jobs as
audit history and skips only jobs that are still pending.
"""

import os

from odoo import fields


PO_NAME = "DMH21021"
APPLY = True

PurchaseOrder = env["purchase.order"].sudo().with_context(active_test=False)
SyncJob = env["amis.sync.job"].sudo()

orders = PurchaseOrder.search([("name", "=", PO_NAME)])
if not orders:
    raise RuntimeError("Khong tim thay Don mua %s." % PO_NAME)
if len(orders) != 1:
    raise RuntimeError(
        "Tim thay %s Don mua co ma %s; dung script de tranh reset nham."
        % (len(orders), PO_NAME)
    )

po = orders.ensure_one()
required_po_fields = {
    "misa_purchase_order_synced",
    "misa_purchase_order_org_refid",
    "misa_purchase_order_refid",
    "misa_purchase_order_state",
    "misa_purchase_order_replacement_pending",
    "misa_purchase_order_last_error",
    "misa_purchase_order_session_id",
    "misa_purchase_order_revision",
}
missing_po_fields = sorted(required_po_fields - set(po._fields))
if missing_po_fields:
    raise RuntimeError(
        "Module amis_callback tren database chua du truong: %s"
        % ", ".join(missing_po_fields)
    )
if po.state not in ("purchase", "done"):
    raise RuntimeError(
        "Don mua %s dang o trang thai %s, khong the enqueue sync MISA."
        % (PO_NAME, po.state)
    )

job_domain = [
    ("purchase_order_id", "=", po.id),
    ("direction", "in", ("purchase_order", "purchase_order_revoke")),
]
jobs = SyncJob.search(job_domain, order="id desc")
pending_jobs = jobs.filtered(lambda job: job.status == "pending")

print("=" * 80)
print("Reset MISA purchase order")
print("Mode: %s" % ("APPLY" if APPLY else "PREVIEW"))
print("PO: %s (id=%s, Odoo state=%s)" % (po.name, po.id, po.state))
print("MISA state: %s" % (po.misa_purchase_order_state or ""))
print("MISA synced: %s" % bool(po.misa_purchase_order_synced))
print("Replacement pending: %s" % bool(po.misa_purchase_order_replacement_pending))
print("MISA org_refid: %s" % (po.misa_purchase_order_org_refid or ""))
print("MISA refid: %s" % (po.misa_purchase_order_refid or ""))
print("MISA session_id: %s" % (po.misa_purchase_order_session_id or ""))
print("Revision: %s" % po.misa_purchase_order_revision)
print("Related jobs: %s; pending jobs to skip: %s" % (len(jobs), len(pending_jobs)))
for job in jobs[:10]:
    print(
        "  job id=%s direction=%s status=%s retry=%s error=%s"
        % (
            job.id,
            job.direction,
            job.status,
            job.retry_count,
            (job.error_msg or "").replace("\n", " ")[:160],
        )
    )
if len(jobs) > 10:
    print("  ... and %s older jobs" % (len(jobs) - 10))
print("=" * 80)

if not APPLY:
    print("PREVIEW ONLY: khong co du lieu nao bi thay doi.")
    print("Neu PO cu da duoc xoa tren MISA, chay lai voi APPLY=1.")
else:
    # Serialize changes to this PO so a queue worker cannot concurrently reset it.
    env.cr.execute(
        "SELECT id FROM purchase_order WHERE id = %s FOR UPDATE",
        [po.id],
    )
    po.invalidate_recordset()

    pending_jobs = SyncJob.search(job_domain + [("status", "=", "pending")])
    if pending_jobs:
        pending_jobs.write(
            {
                "status": "skipped",
                "error_msg": (
                    "Bo qua job cu: reset thu cong thong tin MISA cua %s "
                    "sau khi da thu hoi tren MISA."
                )
                % PO_NAME,
                "processed_at": fields.Datetime.now(),
            }
        )

    old_revision = po.misa_purchase_order_revision
    po.action_reset_misa_purchase_order()
    # action_reset_misa_purchase_order does not clear the callback session.
    po.with_context(skip_misa_purchase_order_lifecycle=True).write(
        {
            "misa_purchase_order_session_id": False,
            "misa_purchase_order_state_updated_at": fields.Datetime.now(),
        }
    )
    po._enqueue_misa_purchase_order(raise_on_skip=True, force=True)

    new_job = SyncJob.search(
        [
            ("purchase_order_id", "=", po.id),
            ("direction", "=", "purchase_order"),
            ("status", "=", "pending"),
        ],
        order="id desc",
        limit=1,
    )
    if not new_job:
        raise RuntimeError("Reset xong nhung khong tao duoc job sync moi cho %s." % PO_NAME)

    env.cr.commit()
    print("APPLIED AND COMMITTED")
    print("Skipped old pending jobs: %s" % len(pending_jobs))
    print("Revision: %s -> %s" % (old_revision, po.misa_purchase_order_revision))
    print("New sync job: id=%s, status=%s" % (new_job.id, new_job.status))
    print(
        "Current MISA identity: org_refid=%s, refid=%s, replacement_pending=%s"
        % (
            po.misa_purchase_order_org_refid or "",
            po.misa_purchase_order_refid or "",
            bool(po.misa_purchase_order_replacement_pending),
        )
    )
