# -*- coding: utf-8 -*-
import base64
import os
from odoo import models, fields, api


class HlvLoyaltyTier(models.Model):
    _name = 'hlv.loyalty.tier'
    _description = 'Hạng Khách hàng thân thiết'
    _order = 'min_points asc'

    name = fields.Char(string='Tên hạng', required=True)
    min_points = fields.Integer(string='Điểm tối thiểu', required=True, default=0)
    max_points = fields.Integer(
        string='Điểm tối đa',
        help='Để trống nếu không giới hạn (hạng cao nhất)',
    )
    color = fields.Selection([
        ('brown', 'Đồng'),
        ('silver', 'Bạc'),
        ('gold', 'Vàng'),
        ('platinum', 'Bạch kim'),
        ('diamond', 'Kim cương'),
    ], string='Màu hạng', default='brown')
    icon = fields.Char(
        string='Icon CSS', default='fa-medal',
        help='Font Awesome icon class, vd: fa-medal, fa-star, fa-crown',
    )
    tier_image = fields.Image(
        string='Ảnh hạng', max_width=256, max_height=256,
    )
    description = fields.Char(string='Mô tả ngắn')
    benefit_ids = fields.One2many(
        'hlv.loyalty.tier.benefit', 'tier_id', string='Quyền lợi',
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    # Màu badge cho UI
    badge_color = fields.Char(
        string='Màu badge', compute='_compute_badge_color', store=True,
    )
    image_url = fields.Char(
        string='URL ảnh hạng', compute='_compute_image_url',
    )

    @api.depends('color')
    def _compute_badge_color(self):
        color_map = {
            'brown': '#cd7f32',
            'silver': '#a8a9ad',
            'gold': '#d4af37',
            'platinum': '#e5e4e2',
            'diamond': '#b9f2ff',
        }
        for tier in self:
            tier.badge_color = color_map.get(tier.color, '#cd7f32')

    @api.depends('color', 'tier_image')
    def _compute_image_url(self):
        static_map = {
            'brown': '/hlv_loyalty/static/description/brozen.png',
            'silver': '/hlv_loyalty/static/description/platinum.png',
            'gold': '/hlv_loyalty/static/description/gold.png',
            'platinum': '/hlv_loyalty/static/description/platinum.png',
            'diamond': '/hlv_loyalty/static/description/platinum.png',
        }
        for tier in self:
            if tier.tier_image:
                tier.image_url = f'/api/v1/loyalty/tiers/{tier.id}/image'
            else:
                tier.image_url = static_map.get(tier.color, '/hlv_loyalty/static/description/brozen.png')

    def name_get(self):
        return [(t.id, f'{t.name} (≥{t.min_points} điểm)') for t in self]


class HlvLoyaltyTierBenefit(models.Model):
    _name = 'hlv.loyalty.tier.benefit'
    _description = 'Quyền lợi theo hạng'

    tier_id = fields.Many2one('hlv.loyalty.tier', required=True, ondelete='cascade')
    name = fields.Char(string='Quyền lợi', required=True)
    icon = fields.Char(string='Icon', default='fa-check')
