from odoo import models, api, _
import logging
import json

_logger = logging.getLogger(__name__)

class ZaloVectorMixin(models.AbstractModel):
    _name = 'zalo.vector.mixin'
    _description = 'Vector Embedding Mixin'

    def _get_vector_content(self):
        """Override this method to return text content to be embedded"""
        raise NotImplementedError("Models using zalo.vector.mixin must implement _get_vector_content()")

    def _update_vector(self):
        """Generate and update vector embedding for this record"""
        self.ensure_one()
        content = self._get_vector_content()
        if not content:
            return

        # Get Zalo Config for API Key
        # Currently we assume there's at least one config. 
        # Ideally, we should pick the active one or pass it as param.
        config = self.env['zalo.oa.config'].sudo().search([], limit=1)
        if not config or not config.gpt_api_key:
            _logger.warning(f"Skipping vector update for {self._name}({self.id}): No GPT API Key found.")
            return

        try:
            # Generate Embedding via OpenAI
            embedding = config._get_embedding(content)
            
            # Upsert into Vector Store
            vector_store = self.env['zalo.vector.store'].sudo().search([
                ('res_model', '=', self._name),
                ('res_id', '=', self.id)
            ], limit=1)

            vals = {
                'res_model': self._name,
                'res_id': self.id,
                'content': content,
                'embedding': json.dumps(embedding)
            }

            if vector_store:
                vector_store.write(vals)
            else:
                self.env['zalo.vector.store'].sudo().create(vals)
                
            _logger.info(f"Vector updated for {self._name}({self.id})")
            
        except Exception as e:
            _logger.error(f"Failed to update vector for {self._name}({self.id}): {e}")
