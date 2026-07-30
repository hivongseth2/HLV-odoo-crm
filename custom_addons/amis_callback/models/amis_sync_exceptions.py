# -*- coding: utf-8 -*-

from odoo.exceptions import UserError


class MisaCatalogPending(Exception):
    """The document must wait until MISA returns an official catalog ID."""


class MeInvoiceDuplicateRefError(UserError):
    """MISA already has an invoice for this RefID.

    Retrying with a different RefID can create a second legally issued invoice
    for the same sale, so callers must stop and reconcile the existing invoice.
    """
