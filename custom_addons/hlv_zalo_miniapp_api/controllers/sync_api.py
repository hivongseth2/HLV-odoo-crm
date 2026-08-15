# -*- coding: utf-8 -*-
import logging
import time

from odoo import fields, http
from odoo.http import request

from .base_api import ZaloBaseAPI

_logger = logging.getLogger(__name__)


class ZaloSyncAPI(ZaloBaseAPI, http.Controller):
    """API Đồng bộ Version Snapshot dữ liệu Zalo Mini App"""

    @http.route(
        "/api/v1/zalo/sync/version",
        type="http",
        auth="public",
        methods=["GET", "POST", "OPTIONS"],
        csrf=False,
    )
    def sync_version(self, **params):
        """Trả về version hiện tại của Catalog và Banner.
        Ưu tiên forced version từ System Parameters (được auto-bump khi dữ liệu thay đổi).
        Chỉ fallback tính max(write_date) khi chưa có forced version."""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            Param = request.env["ir.config_parameter"].sudo()
            forced_cat = Param.get_param("zalo_miniapp_forced_catalog_version", "")
            forced_ban = Param.get_param("zalo_miniapp_forced_banner_version", "")
            forced_loy = Param.get_param("zalo_miniapp_forced_loyalty_version", "")

            catalog_ts = 0
            banner_ts = 0
            latest_prod = None
            latest_cat = None

            # Chỉ query DB khi chưa có forced version
            if not (forced_cat and forced_cat.isdigit()):
                timestamps = []

                # 1. pos.category max write_date (x_active_zalo = True)
                try:
                    Cat = request.env["pos.category"].sudo()
                    domain_cat = [("x_active_zalo", "=", True)] if hasattr(Cat, "x_active_zalo") else []
                    latest_cat = Cat.search(domain_cat, order="write_date desc, id desc", limit=1)
                    if latest_cat:
                        wdate = latest_cat.write_date or latest_cat.create_date
                        if wdate:
                            timestamps.append(int(fields.Datetime.to_datetime(wdate).timestamp()))
                except Exception as e:
                    _logger.warning("Error calculating pos.category max write_date: %s", e)

                # 2. product.product max write_date (x_active_zalo = True)
                try:
                    Prod = request.env["product.product"].sudo()
                    domain_prod = [
                        ("x_active_zalo", "=", True),
                        ("active", "=", True),
                        ("sale_ok", "=", True),
                    ]
                    latest_prod = Prod.search(domain_prod, order="write_date desc, id desc", limit=1)
                    if latest_prod:
                        wdate = latest_prod.write_date or latest_prod.create_date
                        if wdate:
                            timestamps.append(int(fields.Datetime.to_datetime(wdate).timestamp()))
                except Exception as e:
                    _logger.warning("Error calculating product.product max write_date: %s", e)

                # 3. stock.quant max write_date cho các sản phẩm Zalo active
                try:
                    Quant = request.env["stock.quant"].sudo()
                    active_prods = request.env["product.product"].sudo().search([
                        ("x_active_zalo", "=", True),
                        ("active", "=", True),
                        ("sale_ok", "=", True),
                    ])
                    if active_prods:
                        latest_quant = Quant.search(
                            [("product_id", "in", active_prods.ids)],
                            order="write_date desc, id desc",
                            limit=1,
                        )
                        if latest_quant:
                            wdate = latest_quant.write_date or latest_quant.create_date
                            if wdate:
                                timestamps.append(int(fields.Datetime.to_datetime(wdate).timestamp()))
                except Exception as e:
                    _logger.warning("Error calculating stock.quant max write_date: %s", e)

                catalog_ts = max(timestamps) if timestamps else int(time.time())

                # Áp dụng forced version nếu cao hơn
                if forced_cat and forced_cat.isdigit():
                    catalog_ts = max(catalog_ts, int(forced_cat))
            else:
                catalog_ts = int(forced_cat)

            if not (forced_ban and forced_ban.isdigit()):
                banner_ts = int(time.time())
                try:
                    Banner = request.env["zalo.miniapp.banner"].sudo()
                    latest_banner = Banner.search([("active", "=", True)], order="write_date desc, id desc", limit=1)
                    if latest_banner:
                        wdate = latest_banner.write_date or latest_banner.create_date
                        if wdate:
                            banner_ts = int(fields.Datetime.to_datetime(wdate).timestamp())
                except Exception as e:
                    _logger.warning("Error calculating banner max write_date: %s", e)

                if forced_ban and forced_ban.isdigit():
                    banner_ts = max(banner_ts, int(forced_ban))
            else:
                banner_ts = int(forced_ban)

            # 4. Loyalty catalog version (tiers + voucher packages + program config)
            if not (forced_loy and forced_loy.isdigit()):
                loyalty_timestamps = []
                for model, domain in (
                    ("hlv.loyalty.tier", []),
                    ("hlv.loyalty.voucher.package", [("active", "=", True)]),
                    ("hlv.loyalty.program", [("active", "=", True)]),
                ):
                    try:
                        rec = request.env[model].sudo().search(domain, order="write_date desc, id desc", limit=1)
                        if rec and (rec.write_date or rec.create_date):
                            loyalty_timestamps.append(int(fields.Datetime.to_datetime(rec.write_date or rec.create_date).timestamp()))
                    except Exception as e:
                        _logger.warning("Error calculating %s max write_date: %s", model, e)
                loyalty_ts = max(loyalty_timestamps) if loyalty_timestamps else int(time.time())
                if forced_loy and forced_loy.isdigit():
                    loyalty_ts = max(loyalty_ts, int(forced_loy))
            else:
                loyalty_ts = int(forced_loy)

            data = {
                "catalog_version": str(catalog_ts),
                "banner_version": str(banner_ts),
                "loyalty_version": str(loyalty_ts),
                "timestamp": int(time.time()),
            }

            # Auto-sync log entry in zalo.miniapp.snapshot.log (chỉ khi dùng tính toán tự động)
            try:
                Log = request.env["zalo.miniapp.snapshot.log"].sudo()
                existing = Log.search([("snapshot_type", "=", "catalog"), ("version_code", "=", str(catalog_ts))], limit=1)
                if not existing:
                    Log.search([("snapshot_type", "=", "catalog"), ("state", "=", "active")]).write({"state": "historical"})
                    affected_name = "Khởi tạo version tự động"
                    if latest_prod and latest_prod.exists():
                        affected_name = f"Sản phẩm: {latest_prod.display_name}"
                    elif latest_cat and latest_cat.exists():
                        affected_name = f"Danh mục: {latest_cat.name}"

                    Log.create({
                        "name": f"Catalog Snapshot #{catalog_ts}",
                        "snapshot_type": "catalog",
                        "version_code": str(catalog_ts),
                        "version_datetime": fields.Datetime.now(),
                        "trigger_source": "auto_prod" if (latest_prod and latest_prod.exists()) else "auto_cat",
                        "trigger_reason": "Tự động phát hiện thay đổi dữ liệu Zalo",
                        "affected_record_name": affected_name,
                        "state": "active",
                    })
            except Exception as log_err:
                _logger.warning("Error auto-syncing snapshot log: %s", log_err)

            return self._response_success_cached(data, max_age=60)

        except Exception as e:
            _logger.exception("sync_version error")
            return self._response_error("SERVER_ERROR", str(e), 500)
