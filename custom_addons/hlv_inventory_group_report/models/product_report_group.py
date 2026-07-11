from odoo import api, fields, models


class HlvProductReportGroupLine(models.Model):
    _name = 'hlv.product.report.group.line'
    _description = 'Sản phẩm trong nhóm báo cáo tồn kho'
    _order = 'created_at desc, id desc'
    _legacy_m2m_migration_param = 'hlv_inventory_group_report.legacy_many2many_migrated'

    group_id = fields.Many2one(
        'hlv.product.report.group',
        string='Nhóm',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Sản phẩm',
        required=True,
        ondelete='cascade',
        index=True,
        domain=[('type', 'in', ['consu', 'product'])],
    )
    created_at = fields.Datetime(
        string='Thêm lúc',
        default=fields.Datetime.now,
        readonly=True,
        copy=False,
        index=True,
    )
    updated_at = fields.Datetime(
        string='Cập nhật lúc',
        default=fields.Datetime.now,
        readonly=True,
        copy=False,
        index=True,
    )

    _sql_constraints = [
        (
            'group_product_unique',
            'unique(group_id, product_id)',
            'Sản phẩm này đã có trong nhóm báo cáo.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        for vals in vals_list:
            vals.setdefault('created_at', now)
            vals.setdefault('updated_at', now)
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        vals['updated_at'] = fields.Datetime.now()
        return super().write(vals)

    def init(self):
        self._migrate_legacy_many2many()

    def _legacy_m2m_migration_done(self):
        self.env.cr.execute(
            "SELECT value FROM ir_config_parameter WHERE key = %s",
            (self._legacy_m2m_migration_param,),
        )
        return bool(self.env.cr.fetchone())

    def _mark_legacy_m2m_migration_done(self):
        self.env.cr.execute(
            """
            INSERT INTO ir_config_parameter
                (key, value, create_uid, create_date, write_uid, write_date)
            VALUES
                (%s, '1', 1, NOW() AT TIME ZONE 'UTC', 1, NOW() AT TIME ZONE 'UTC')
            ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value,
                    write_uid = EXCLUDED.write_uid,
                    write_date = EXCLUDED.write_date
            """,
            (self._legacy_m2m_migration_param,),
        )

    def _migrate_legacy_many2many(self):
        if self._legacy_m2m_migration_done():
            return
        self.env.cr.execute("SELECT to_regclass('hlv_report_group_product_rel')")
        if not self.env.cr.fetchone()[0]:
            self._mark_legacy_m2m_migration_done()
            return
        self.env.cr.execute("SELECT 1 FROM hlv_product_report_group_line LIMIT 1")
        if self.env.cr.fetchone():
            # init() runs on module updates; do not replay stale legacy M2M rows.
            self._mark_legacy_m2m_migration_done()
            return
        self.env.cr.execute(
            """
            INSERT INTO hlv_product_report_group_line
                (group_id, product_id, created_at, updated_at, create_uid, write_uid, create_date, write_date)
            SELECT DISTINCT
                rel.group_id,
                rel.product_id,
                COALESCE(grp.write_date, grp.create_date, NOW() AT TIME ZONE 'UTC'),
                COALESCE(grp.write_date, grp.create_date, NOW() AT TIME ZONE 'UTC'),
                COALESCE(grp.create_uid, 1),
                COALESCE(grp.write_uid, grp.create_uid, 1),
                COALESCE(grp.write_date, grp.create_date, NOW() AT TIME ZONE 'UTC'),
                COALESCE(grp.write_date, grp.create_date, NOW() AT TIME ZONE 'UTC')
            FROM hlv_report_group_product_rel rel
            JOIN hlv_product_report_group grp ON grp.id = rel.group_id
            JOIN product_product prod ON prod.id = rel.product_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM hlv_product_report_group_line line
                WHERE line.group_id = rel.group_id
                  AND line.product_id = rel.product_id
            )
            """
        )
        self.env.cr.execute(
            """
            UPDATE hlv_product_report_group grp
            SET product_count = counts.product_count
            FROM (
                SELECT group_id, COUNT(*) AS product_count
                FROM hlv_product_report_group_line
                GROUP BY group_id
            ) counts
            WHERE counts.group_id = grp.id
            """
        )
        self._mark_legacy_m2m_migration_done()


class HlvProductReportGroup(models.Model):
    _name = 'hlv.product.report.group'
    _description = 'Nhóm sản phẩm báo cáo tồn kho'
    _order = 'sequence, name'

    name = fields.Char('Tên nhóm', required=True)
    description = fields.Text('Mô tả')
    sequence = fields.Integer('Thứ tự', default=10)
    color = fields.Integer('Màu sắc')
    active = fields.Boolean('Hoạt động', default=True)

    line_ids = fields.One2many(
        'hlv.product.report.group.line',
        'group_id',
        string='Sản phẩm trong nhóm',
        copy=True,
    )
    product_ids = fields.Many2many(
        'product.product',
        string='Sản phẩm',
        domain=[('type', 'in', ['consu', 'product'])],
        compute='_compute_product_ids',
        inverse='_inverse_product_ids',
        search='_search_product_ids',
    )
    product_count = fields.Integer(
        'Số sản phẩm',
        compute='_compute_product_count',
        store=True,
    )

    @api.depends('line_ids.product_id')
    def _compute_product_ids(self):
        for rec in self:
            rec.product_ids = rec.line_ids.mapped('product_id')

    def _inverse_product_ids(self):
        Line = self.env['hlv.product.report.group.line']
        for rec in self:
            existing_lines = rec.line_ids
            existing_by_product = {
                line.product_id.id: line
                for line in existing_lines
            }
            target_ids = set(rec.product_ids.ids)
            existing_ids = set(existing_by_product)
            removed_lines = existing_lines.filtered(
                lambda line: line.product_id.id not in target_ids
            )
            if removed_lines:
                removed_lines.unlink()
            for product_id in target_ids - existing_ids:
                Line.create({
                    'group_id': rec.id,
                    'product_id': product_id,
                })

    def _search_product_ids(self, operator, value):
        return [('line_ids.product_id', operator, value)]

    @api.depends('line_ids')
    def _compute_product_count(self):
        for rec in self:
            rec.product_count = len(rec.line_ids)

    def action_open_report_wizard(self):
        """Open quick stock viewer pre-filled with this group."""
        return {
            'type': 'ir.actions.client',
            'tag': 'hlv_stock_quick_action',
            'name': 'Tồn kho - ' + (self.name or ''),
            'target': 'current',
            'context': {'default_group_id': self.id},
        }
