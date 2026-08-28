# -*- coding: utf-8 -*-
from odoo import models

from .common import rewrite_free_text_domain, TEMPLATE_SEARCH_FIELDS


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _search(self, domain, offset=0, limit=None, order=None):
        domain = rewrite_free_text_domain(list(domain or []), fields=TEMPLATE_SEARCH_FIELDS)
        return super(ProductTemplate, self)._search(domain, offset=offset, limit=limit, order=order)
