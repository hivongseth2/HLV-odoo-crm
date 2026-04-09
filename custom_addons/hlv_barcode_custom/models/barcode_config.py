# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class BarcodeCustomConfig(models.TransientModel):
    """Configuration settings for HLV Custom Barcode module."""
    _inherit = 'res.config.settings'
    _description = 'HLV Barcode Custom Settings'

    barcode_auto_focus = fields.Boolean(
        string='Tự động Focus ô quét',
        default=True,
        config_parameter='hlv_barcode_custom.auto_focus',
    )
    barcode_sound_success = fields.Boolean(
        string='Âm thanh khi quét thành công',
        default=True,
        config_parameter='hlv_barcode_custom.sound_success',
    )
    barcode_sound_error = fields.Boolean(
        string='Âm thanh khi quét lỗi',
        default=True,
        config_parameter='hlv_barcode_custom.sound_error',
    )
    barcode_strict_delivery = fields.Boolean(
        string='Chặn cứng phiếu xuất (không cho vượt kế hoạch)',
        default=True,
        config_parameter='hlv_barcode_custom.strict_delivery',
    )
    barcode_decimal_step = fields.Float(
        string='Bước nhảy thập phân (+/-)',
        default=0.1,
        config_parameter='hlv_barcode_custom.decimal_step',
    )
    barcode_camera_enabled = fields.Boolean(
        string='Cho phép quét bằng Camera',
        default=True,
        config_parameter='hlv_barcode_custom.camera_enabled',
    )
