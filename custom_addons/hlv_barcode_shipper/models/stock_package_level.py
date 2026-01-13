# -*- coding: utf-8 -*-

from odoo import models, fields, api


class StockPackageLevel(models.Model):
    _inherit = 'stock.package_level'

    scanned = fields.Boolean(
        string='Scanned',
        default=False,
        help='Indicates if this package has been scanned by shipper'
    )
    
    scan_time = fields.Datetime(
        string='Scan Time',
        help='When this package was scanned'
    )
    
    scanned_by = fields.Many2one(
        'res.users',
        string='Scanned By',
        help='User who scanned this package'
    )

    def mark_scanned(self, user_id=None):
        """
        Mark this package as scanned
        """
        self.ensure_one()
        self.write({
            'scanned': True,
            'scan_time': fields.Datetime.now(),
            'scanned_by': user_id or self.env.user.id
        })

    def reset_scan(self):
        """
        Reset scan status
        """
        self.write({
            'scanned': False,
            'scan_time': False,
            'scanned_by': False
        })


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    scanned = fields.Boolean(
        string='Scanned',
        default=False,
        help='Indicates if this product has been scanned by shipper'
    )
    
    scan_time = fields.Datetime(
        string='Scan Time',
        help='When this product was scanned'
    )
    
    scanned_by = fields.Many2one(
        'res.users',
        string='Scanned By',
        help='User who scanned this product'
    )

    def mark_scanned(self, user_id=None):
        """
        Mark this move line as scanned
        """
        self.ensure_one()
        self.write({
            'scanned': True,
            'scan_time': fields.Datetime.now(),
            'scanned_by': user_id or self.env.user.id
        })

    def reset_scan(self):
        """
        Reset scan status
        """
        self.write({
            'scanned': False,
            'scan_time': False,
            'scanned_by': False
        })