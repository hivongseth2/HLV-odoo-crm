# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, models, fields
from odoo.exceptions import ValidationError

from ..lib import pinguin

PREFIX = "__pragmatic_api__"


class Base(models.AbstractModel):
    """Extend base model with API-related methods for Odoo 18."""
    _inherit = "base"

    @api.model
    def search_or_create(self, vals, active_test=True):
        """Search for a record with given values or create it if not found.
        
        Args:
            vals (dict): Dictionary of field values to search/create
            active_test (bool): Whether to filter out inactive records
            
        Returns:
            tuple: (is_new, record_ids) where is_new is True if record was created
        """
        domain = []
        for k, v in vals.items():
            field = self._fields.get(k)
            if field and not isinstance(field, (fields.Many2many, fields.One2many)):
                domain.append((k, "=", v))
                
        records = self.with_context(active_test=active_test).search(domain)
        is_new = not bool(records)
        if is_new:
            records = self.create(vals)
        return (is_new, records.ids)

    @api.model
    def search_read_nested(self, domain=None, fields=None, offset=0, 
                          limit=None, order=None, delimeter="/"):
        """Search and read records with nested related fields.
        
        Args:
            domain (list, optional): Search domain. Defaults to None.
            fields (list, optional): List of fields to read. Defaults to None.
            offset (int, optional): Number of records to skip. Defaults to 0.
            limit (int, optional): Maximum number of records to return. Defaults to None.
            order (str, optional): Sort order. Defaults to None.
            delimeter (str, optional): Delimiter for nested fields. Defaults to "/".
            
        Returns:
            list: List of dictionaries with record data
        """
        if domain is None:
            domain = []
        if fields is None:
            fields = []
            
        result = pinguin.get_dictlist_from_model(
            self._name,
            tuple(fields),
            domain=domain,
            offset=offset,
            limit=limit,
            order=order,
            env=self.env,
            delimeter=delimeter,
        )
        return result

    @api.model
    def create_or_update_by_external_id(self, vals):
        """Create or update a record using an external ID.
        
        Args:
            vals (dict): Dictionary of field values, must include 'id' key with external ID
            
        Returns:
            tuple: (is_new, record_id) where is_new is True if record was created
            
        Raises:
            ValueError: If 'id' is missing or invalid, or if referenced external IDs don't exist
        """
        ext_id = vals.get("id")
        if not isinstance(ext_id, str):
            raise ValueError('The "id" field must be a string')
            
        imd_env = self.env["ir.model.data"]
        fields_2many = []

        def convert_external_2_inner_id(ext_id, field):
            """Convert external ID to internal database ID."""
            try:
                return imd_env._xmlid_lookup(f"{PREFIX}.{ext_id}")[2]
            except ValueError as e:
                raise ValueError(
                    f"No object with external ID '{ext_id}' found for field '{field}'"
                ) from e

        # Process many2one and x2many fields
        for field_name, value in list(vals.items()):
            field = self._fields.get(field_name)
            if not field:
                continue
                
            if field.type == "many2one" and isinstance(value, str):
                # Convert many2one external ID to internal ID
                vals[field_name] = convert_external_2_inner_id(value, field_name)
            elif isinstance(field, (fields.Many2many, fields.One2many)) and value:
                # Collect x2many fields for processing after the loop
                fields_2many.append(field_name)

        # Process x2many fields
        for field_name in fields_2many:
            field = self._fields[field_name]
            commands = vals[field_name]
            new_commands = []
            
            for command in commands:
                if not command:  # Skip empty commands
                    continue
                    
                cmd_type = command[0] if command else None
                cmd_vals = command[1] if len(command) > 1 else None
                
                # Handle different command types (0: create, 1: update, etc.)
                if cmd_type in (0, 1, 2, 3, 4) and isinstance(cmd_vals, (int, str)):
                    # Convert external ID to internal ID
                    new_commands.append((cmd_type, convert_external_2_inner_id(cmd_vals, field_name)))
                elif cmd_type == 6 and isinstance(cmd_vals, (list, tuple)):
                    # Handle set operation (replace all)
                    new_ids = []
                    for item in cmd_vals:
                        if isinstance(item, (int, str)):
                            new_ids.append(convert_external_2_inner_id(item, field_name))
                        else:
                            new_ids.append(item)
                    new_commands.append((cmd_type, 0, new_ids))
                else:
                    new_commands.append(command)
            
            vals[field_name] = new_commands

        # Check if external ID exists
        try:
            # Try to find existing record
            xml_id = f"{PREFIX}.{ext_id}"
            record = self.env['ir.model.data']._xmlid_to_res_model_res_id(
                xml_id, raise_if_not_found=True
            )
            model_name, inner_id = record
            
            # Update existing record
            self.browse(inner_id).write(vals)
            return False, inner_id
            
        except ValueError:
            # Create new record and register external ID
            record = self.create(vals)
            self.env['ir.model.data'].create({
                'name': ext_id,
                'model': self._name,
                'module': PREFIX,
                'res_id': record.id,
                'noupdate': True,
            })
            return True, record.id
