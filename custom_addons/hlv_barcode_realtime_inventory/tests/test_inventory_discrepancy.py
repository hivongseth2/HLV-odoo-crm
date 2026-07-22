from odoo.tests.common import TransactionCase


class TestInventoryDiscrepancy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({
            'name': 'Discrepancy sync test product',
        })
        cls.location = cls.env['stock.location'].create({
            'name': 'Discrepancy sync test location',
            'usage': 'internal',
        })
        cls.check = cls.env['inventory.check'].create({})
        cls.line = cls.env['inventory.check.line'].create({
            'check_id': cls.check.id,
            'product_id': cls.product.id,
            'location_id': cls.location.id,
            'theoretical_qty': 102,
            'scanned_qty': 103,
        })
        cls.discrepancy = cls.env['inventory.discrepancy'].create({
            'check_id': cls.check.id,
            'line_id': cls.line.id,
            'reason': 'kiem_ton',
        })

    def test_difference_follows_inventory_line(self):
        self.assertEqual(self.discrepancy.difference, 1)

        self.line.scanned_qty = 152

        self.assertEqual(self.line.difference, 50)
        self.assertEqual(self.discrepancy.difference, 50)
