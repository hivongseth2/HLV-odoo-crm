import hashlib
import json

from odoo import api, fields, models


class HlvSalePlanWebPushSubscription(models.Model):
    _name = 'hlv.sale.plan.web.push.subscription'
    _description = 'Sale Plan Web Push Subscription'
    _order = 'write_date desc, id desc'

    user_id = fields.Many2one('res.users', index=True, ondelete='cascade')
    alias = fields.Char(index=True)
    endpoint = fields.Char(required=True, index=True)
    endpoint_hash = fields.Char(required=True, index=True)
    p256dh = fields.Char()
    auth = fields.Char()
    subscription_json = fields.Text(required=True)
    backend_messages = fields.Boolean(default=False, index=True)
    active = fields.Boolean(default=True, index=True)

    @api.model
    def _hash_endpoint(self, endpoint):
        return hashlib.sha256((endpoint or '').encode('utf-8')).hexdigest()

    @api.model
    def upsert_subscription(self, user, subscription, aliases=None, backend_messages=False):
        endpoint = (subscription or {}).get('endpoint') or ''
        keys = (subscription or {}).get('keys') or {}
        if not endpoint:
            return self.browse()
        endpoint_hash = self._hash_endpoint(endpoint)
        aliases = aliases or ['']
        records = self.browse()
        payload = json.dumps(subscription, separators=(',', ':'))
        for alias in aliases:
            alias = (alias or '').strip().lower().lstrip('@')
            domain = [('endpoint_hash', '=', endpoint_hash), ('alias', '=', alias)]
            rec = self.sudo().search(domain, limit=1)
            vals = {
                'user_id': user.id if user and user.exists() else False,
                'alias': alias,
                'endpoint': endpoint,
                'endpoint_hash': endpoint_hash,
                'p256dh': keys.get('p256dh') or '',
                'auth': keys.get('auth') or '',
                'subscription_json': payload,
                'backend_messages': bool(backend_messages),
                'active': True,
            }
            if rec:
                rec.write(vals)
            else:
                rec = self.sudo().create(vals)
            records |= rec
        return records
