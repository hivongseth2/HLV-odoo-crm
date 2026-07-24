# Copyright 2015-2016 Akretion (http://www.akretion.com) - Alexis de Lattre
# Copyright 2016 ForgeFlow (http://www.forgeflow.com)
# Copyright 2016 Serpent Consulting Services (<http://www.serpentcs.com>)
# Copyright 2018 Tecnativa - Pedro M. Baeza
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestStockNoNegative(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_model = cls.env["product.product"]
        cls.product_ctg_model = cls.env["product.category"]
        cls.lot_model = cls.env["stock.lot"]
        cls.picking_type_id = cls.env.ref("stock.picking_type_out")
        cls.location_id = cls.env.ref("stock.stock_location_stock")
        cls.location_dest_id = cls.env.ref("stock.stock_location_customers")

        # Create product category
        cls.product_ctg = cls.product_ctg_model.create(
            {"name": "test_product_ctg", "allow_negative_stock": False}
        )
        # Create a Product
        cls.product = cls.product_model.create(
            {
                "name": "test_product1",
                "categ_id": cls.product_ctg.id,
                "is_storable": True,
                "type": "consu",
                "allow_negative_stock": False,
            }
        )
        # Create a Product With Lot
        cls.product_with_lot = cls.product_model.create(
            {
                "name": "test_lot_product1",
                "categ_id": cls.product_ctg.id,
                "is_storable": True,
                "type": "consu",
                "tracking": "lot",
                "allow_negative_stock": False,
            }
        )
        # Create Lot
        cls.lot1 = cls.lot_model.create(
            {
                "name": "lot1",
                "product_id": cls.product_with_lot.id,
                "company_id": cls.env.company.id,
            }
        )

    def _create_picking(self, product=None):
        prod = product or self.product
        picking = (
            self.env["stock.picking"]
            .with_context(test_stock_no_negative=True)
            .create(
                {
                    "picking_type_id": self.picking_type_id.id,
                    "move_type": "direct",
                    "location_id": self.location_id.id,
                    "location_dest_id": self.location_dest_id.id,
                }
            )
        )
        move = self.env["stock.move"].create(
            {
                "name": "Test Move",
                "product_id": prod.id,
                "product_uom_qty": 100.0,
                "product_uom": prod.uom_id.id,
                "picking_id": picking.id,
                "location_id": self.location_id.id,
                "location_dest_id": self.location_dest_id.id,
            }
        )
        picking.action_confirm()
        # Create move line with qty_done to pass Odoo 18 _sanity_check()
        self.env["stock.move.line"].create(
            {
                "product_id": prod.id,
                "quantity": 100.0,
                "qty_done": 100.0,
                "picking_id": picking.id,
                "move_id": move.id,
                "location_id": self.location_id.id,
                "location_dest_id": self.location_dest_id.id,
                "picked": True,
            }
        )
        return picking

    def test_check_constrains(self):
        """Assert that constraint is raised when user
        tries to validate the stock operation which would
        make the stock level of the product negative"""
        picking = self._create_picking(self.product)
        with self.assertRaises(ValidationError):
            picking.button_validate()

    def test_check_constrains_with_lot(self):
        """Assert that constraint is raised when user
        tries to validate the stock operation which would
        make the stock level of the product negative with
        a product with lot"""
        picking = self._create_picking(self.product_with_lot)
        # Update the move line with the lot (tracked product requires lot)
        picking.move_line_ids.write({"lot_id": self.lot1.id})
        picking.move_ids.write({"quantity": 100.0, "picked": True})
        with self.assertRaises(ValidationError):
            picking.button_validate()

    def test_true_allow_negative_stock_product(self):
        """Assert that negative stock levels are allowed when
        the allow_negative_stock is set active in the product"""
        self.product.allow_negative_stock = True
        picking = self._create_picking(self.product)
        picking.button_validate()
        quant = self.env["stock.quant"].search(
            [
                ("product_id", "=", self.product.id),
                ("location_id", "=", self.location_id.id),
            ]
        )
        self.assertEqual(quant.quantity, -100)

    def test_true_allow_negative_stock_location(self):
        """Assert that negative stock levels are allowed when
        the allow_negative_stock is set active in the product"""
        self.product.allow_negative_stock = False
        self.location_id.allow_negative_stock = True
        picking = self._create_picking(self.product)
        picking.button_validate()
        quant = self.env["stock.quant"].search(
            [
                ("product_id", "=", self.product.id),
                ("location_id", "=", self.location_id.id),
            ]
        )
        self.assertEqual(quant.quantity, -100)

    def test_true_allow_negative_stock_product_with_lot(self):
        """Assert that negative stock levels are allowed when
        the allow_negative_stock is set active in the product with lot"""
        self.product_with_lot.allow_negative_stock = True
        picking = self._create_picking(self.product_with_lot)
        with self.assertRaises(UserError):
            picking.button_validate()
        # Update the move line with the lot (tracked product requires lot)
        picking.move_line_ids.write({"lot_id": self.lot1.id})
        picking.move_ids.write({"quantity": 100.0, "picked": True})
        picking.button_validate()
        quant = self.env["stock.quant"].search(
            [
                ("product_id", "=", self.product_with_lot.id),
                ("location_id", "=", self.location_id.id),
                ("lot_id", "=", self.lot1.id),
            ]
        )
        self.assertEqual(quant.quantity, -100)
