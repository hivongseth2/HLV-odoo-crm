# -*- coding: utf-8 -*-
from odoo import models


class IrActionsActions(models.Model):
    _inherit = 'ir.actions.actions'

    def _extract_active_ids(self):
        active_ids = self.env.context.get('active_ids') or []
        if not active_ids and self.env.context.get('active_id'):
            active_ids = [self.env.context.get('active_id')]
        if not active_ids:
            params = self.env.context.get('params') or {}
            if params.get('id'):
                active_ids = [params.get('id')]

        normalized_ids = []
        for value in active_ids:
            try:
                normalized_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        return normalized_ids

    def _is_outgoing_picking_context(self):
        active_ids = self._extract_active_ids()
        if not active_ids:
            return None

        pickings = self.env['stock.picking'].browse(active_ids).exists()
        if not pickings:
            return None

        return all(p.picking_type_code == 'outgoing' for p in pickings)

    def get_bindings(self, model_name):
        """Hide print bindings for non-outgoing stock pickings."""
        res = super().get_bindings(model_name)

        if model_name != 'stock.picking':
            return res

        is_outgoing = self._is_outgoing_picking_context()
        if is_outgoing is not True:
            if 'report' in res:
                res['report'] = []
            if 'reports' in res:
                res['reports'] = []

        return res
