from odoo.addons.stock.tests.common import TestStockCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestQuantGuardPicked(TestStockCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source_location = cls.env['stock.location'].browse(cls.stock_location)
        cls.dest_location = cls.env['stock.location'].browse(cls.pack_location)
        cls.picking_type = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)],
            limit=1,
        ).int_type_id
        cls.picking_type.create_backorder = 'ask'

    def _create_assigned_picking(self):
        product_picked = self.env['product.product'].create({
            'name': 'HLV Guard Picked Product',
            'is_storable': True,
        })
        product_backorder = self.env['product.product'].create({
            'name': 'HLV Guard Backorder Product',
            'is_storable': True,
        })
        for product in (product_picked, product_backorder):
            self.env['stock.quant']._update_available_quantity(
                product,
                self.source_location,
                5.0,
            )

        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.source_location.id,
            'location_dest_id': self.dest_location.id,
            'move_ids': [
                (0, 0, {
                    'name': product.display_name,
                    'product_id': product.id,
                    'product_uom': product.uom_id.id,
                    'product_uom_qty': 5.0,
                    'location_id': self.source_location.id,
                    'location_dest_id': self.dest_location.id,
                })
                for product in (product_picked, product_backorder)
            ],
        })
        picking.action_confirm()
        picking.action_assign()
        self.assertEqual(picking.state, 'assigned')
        self.assertEqual(len(picking.move_ids), 2)
        self.assertTrue(all(move.quantity == 5.0 for move in picking.move_ids))
        return picking, product_picked, product_backorder

    def _physical_quantity(self, product, location):
        return sum(self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
        ]).mapped('quantity'))

    def _process_backorder(self, picking, action):
        self.assertEqual(action.get('res_model'), 'stock.backorder.confirmation')
        wizard = self.env['stock.backorder.confirmation'].with_context(
            **action['context'],
        ).create({
            'pick_ids': [(6, 0, picking.ids)],
            'backorder_confirmation_line_ids': [
                (0, 0, {
                    'picking_id': picking.id,
                    'to_backorder': True,
                }),
            ],
        })
        self.assertTrue(wizard.process())
        return self.env['stock.picking'].search([
            ('backorder_id', '=', picking.id),
            ('state', '!=', 'cancel'),
        ], limit=1)

    def test_all_unpicked_uses_core_auto_pick_fallback(self):
        picking, product_a, product_b = self._create_assigned_picking()

        deltas_by_picking, _samples = (
            picking._hlv_collect_validate_quant_deltas_by_picking()
        )
        product_ids = {
            key[0] for key in deltas_by_picking[picking.id]
        }

        self.assertEqual(product_ids, {product_a.id, product_b.id})

    def test_mixed_picked_validates_only_selected_and_creates_backorder(self):
        picking, product_picked, product_backorder = self._create_assigned_picking()
        picked_move = picking.move_ids.filtered(
            lambda move: move.product_id == product_picked
        )
        backorder_move = picking.move_ids.filtered(
            lambda move: move.product_id == product_backorder
        )
        picked_move.picked = True

        self.assertTrue(picked_move.picked)
        self.assertTrue(all(picked_move.move_line_ids.mapped('picked')))
        self.assertFalse(backorder_move.picked)
        self.assertTrue(backorder_move.quantity > 0)

        deltas_by_picking, _samples = (
            picking._hlv_collect_validate_quant_deltas_by_picking()
        )
        product_ids = {
            key[0] for key in deltas_by_picking[picking.id]
        }
        self.assertEqual(product_ids, {product_picked.id})

        source_picked_before = self._physical_quantity(
            product_picked, self.source_location,
        )
        source_backorder_before = self._physical_quantity(
            product_backorder, self.source_location,
        )

        backorder = self._process_backorder(picking, picking.button_validate())
        self.assertEqual(picking.state, 'done')
        self.assertTrue(backorder)
        self.assertIn(product_backorder.id, backorder.move_ids.product_id.ids)
        self.assertAlmostEqual(
            self._physical_quantity(product_picked, self.source_location),
            source_picked_before - 5.0,
        )
        self.assertAlmostEqual(
            self._physical_quantity(product_backorder, self.source_location),
            source_backorder_before,
        )
        self.assertAlmostEqual(
            self._physical_quantity(product_picked, self.dest_location),
            5.0,
        )
        self.assertAlmostEqual(
            self._physical_quantity(product_backorder, self.dest_location),
            0.0,
        )

    def test_picked_move_only_moves_picked_lines_from_multiple_locations(self):
        product = self.env['product.product'].create({
            'name': 'HLV Guard Multi-location Product',
            'is_storable': True,
        })
        child_location = self.env['stock.location'].create({
            'name': 'HLV Guard Child Location',
            'location_id': self.source_location.id,
        })
        self.env['stock.quant']._update_available_quantity(
            product, self.source_location, 5.0,
        )
        self.env['stock.quant']._update_available_quantity(
            product, child_location, 5.0,
        )
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.source_location.id,
            'location_dest_id': self.dest_location.id,
            'move_ids': [(0, 0, {
                'name': product.display_name,
                'product_id': product.id,
                'product_uom': product.uom_id.id,
                'product_uom_qty': 10.0,
                'location_id': self.source_location.id,
                'location_dest_id': self.dest_location.id,
            })],
        })
        picking.action_confirm()
        picking.action_assign()

        move = picking.move_ids
        self.assertEqual(len(move.move_line_ids), 2)
        selected_line = move.move_line_ids.filtered(
            lambda line: line.location_id == child_location
        )
        unselected_line = move.move_line_ids - selected_line
        self.assertEqual(len(selected_line), 1)
        self.assertEqual(len(unselected_line), 1)
        selected_line.picked = True

        deltas_by_picking, _samples = (
            picking._hlv_collect_validate_quant_deltas_by_picking()
        )
        deltas = deltas_by_picking[picking.id]
        source_location_ids = {
            key[1] for key, delta in deltas.items() if delta < 0
        }
        self.assertEqual(source_location_ids, {child_location.id})

        source_before = self._physical_quantity(
            product, self.source_location,
        )
        child_before = self._physical_quantity(product, child_location)
        dest_before = self._physical_quantity(product, self.dest_location)

        backorder = self._process_backorder(picking, picking.button_validate())

        self.assertEqual(picking.state, 'done')
        self.assertTrue(backorder)
        self.assertAlmostEqual(
            self._physical_quantity(product, self.source_location),
            source_before,
        )
        self.assertAlmostEqual(
            self._physical_quantity(product, child_location),
            child_before - 5.0,
        )
        self.assertAlmostEqual(
            self._physical_quantity(product, self.dest_location),
            dest_before + 5.0,
        )
        self.assertAlmostEqual(
            sum(backorder.move_ids.filtered(
                lambda backorder_move: backorder_move.product_id == product
            ).mapped('product_uom_qty')),
            5.0,
        )
