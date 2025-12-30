import json
import base64
import logging
from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class PosCategoryImportWizard(models.TransientModel):
    _name = 'pos.category.import.wizard'
    _description = 'Import POS Categories from JSON'

    json_file = fields.Binary(string='JSON File', required=True)
    json_filename = fields.Char(string='Filename')

    def action_import_categories(self):
        self.ensure_one()
        if not self.json_file:
            raise UserError(_("Please upload a JSON file."))

        try:
            file_content = base64.b64decode(self.json_file)
            data = json.loads(file_content)
        except Exception as e:
            raise UserError(_("Invalid JSON file: %s") % str(e))

        if not isinstance(data, list):
            # If it's not a list, maybe it's a dict with a key? Assuming list as per example.
            raise UserError(_("JSON data must be a list of categories."))

        # Create a map of existing categories by MISA ID for quick lookup and update
        existing_categories = self.env['pos.category'].search([('x_misa_id', '!=', False)])
        misa_id_map = {cat.x_misa_id: cat for cat in existing_categories}

        # Recursive function to process categories
        def process_category(node, parent_id=False):
            misa_id = node.get('ID')
            name = node.get('ProductCategoryName')
            if not name:
                _logger.warning("Category node missing name: %s", node)
                return

            vals = {
                'name': name,
                'parent_id': parent_id,
                'x_misa_id': misa_id,
                # Add other fields if necessary, e.g. sequence
            }

            category = misa_id_map.get(misa_id)
            if category:
                category.write(vals)
            else:
                # Check if exists by name if MISA ID is missing (though we expect MISA ID)
                # For now, rely on MISA ID. If strict import, creating new.
                category = self.env['pos.category'].create(vals)
                if misa_id:
                    misa_id_map[misa_id] = category

            children = node.get('Children', [])
            for child in children:
                process_category(child, parent_id=category.id)

        # Process top-level nodes
        for node in data:
            process_category(node, parent_id=False)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Categories imported successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
