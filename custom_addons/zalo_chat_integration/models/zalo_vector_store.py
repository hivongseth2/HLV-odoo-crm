from odoo import models, fields, api, _
import json
import numpy as np

class ZaloVectorStore(models.Model):
    _name = 'zalo.vector.store'
    _description = 'Zalo Vector Store'
    
    res_model = fields.Char(string='Related Model', required=True, index=True)
    res_id = fields.Integer(string='Related ID', required=True, index=True)
    embedding = fields.Text(string='Vector Embedding', help="JSON string of vector list")
    content = fields.Text(string='Embedded Content', help="Text content used for embedding")
    
    _sql_constraints = [
        ('model_res_id_uniq', 'unique(res_model, res_id)', 'Embedding for this record already exists!')
    ]
    
    def get_embedding_numpy(self):
        """Convert stored JSON embedding to numpy array"""
        self.ensure_one()
        if not self.embedding:
            return None
        return np.array(json.loads(self.embedding))
