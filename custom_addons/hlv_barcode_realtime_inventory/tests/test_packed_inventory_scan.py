from odoo.tests.common import TransactionCase


class TestPackedInventoryScan(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.location = cls.env['stock.location'].create({
            'name': 'Packed inventory test location',
            'usage': 'internal',
        })
        cls.package = cls.env['stock.quant.package'].create({
            'name': 'PACKED-INVENTORY-TEST',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Packed inventory test product',
            'barcode': 'PACKED-PRODUCT-TEST',
            'is_storable': True,
        })
        cls.env['stock.quant'].create({
            'product_id': cls.product.id,
            'location_id': cls.location.id,
            'package_id': cls.package.id,
            'quantity': 5,
        })

    def _create_check(self):
        check = self.env['inventory.check'].create({
            'device_id': 'packed-inventory-test-device',
        })
        result = check.set_location(check.id, self.location.id)
        self.assertTrue(result['success'])
        return check

    def test_product_barcode_counts_existing_packed_line(self):
        check = self._create_check()
        line = check.line_ids

        self.assertEqual(len(line), 1)
        self.assertEqual(line.package_id, self.package)
        self.assertEqual(line.theoretical_qty, 5)
        self.assertEqual(line.scanned_qty, 0)

        result = check.register_scan(
            check.id, self.product.id, self.location.id, 1
        )

        self.assertTrue(result['success'])
        self.assertEqual(check.line_ids, line)
        self.assertEqual(line.scanned_qty, 1)
        self.assertFalse(check.line_ids.filtered(lambda item: not item.package_id))

    def test_package_scan_counts_contents_once(self):
        check = self._create_check()
        barcode_result = check.search_inventory_barcode(
            self.package.name, self.location.id
        )

        self.assertTrue(barcode_result['success'])
        self.assertEqual(barcode_result['barcode_type'], 'package')

        first_result = check.register_package_scan(
            check.id, self.package.id, self.location.id
        )
        second_result = check.register_package_scan(
            check.id, self.package.id, self.location.id
        )

        self.assertTrue(first_result['success'])
        self.assertTrue(second_result['success'])
        self.assertEqual(check.line_ids.scanned_qty, 5)
        self.assertEqual(check.scan_count, 5)
