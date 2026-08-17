# -*- coding: utf-8 -*-
import glob
import json
import logging
import os
import time

from odoo import models

from ..controllers._shared import STREAM_DIR, _uploading_meta_path, _bg_upload_to_drive

_logger = logging.getLogger(__name__)

# No new chunk written for this long -> the recording session is considered
# abandoned (browser crash, tab/app killed, worker restarted mid-recording)
# and gets force-finalized instead of sitting in STREAM_DIR forever.
STALE_AFTER_SECONDS = 15 * 60


class PackVideoStreamCron(models.AbstractModel):
    _name = 'custom.barcode.scan.redirect.stream.cron'
    _description = "Pack Video Stream - Finalize Abandoned Recording Sessions"

    def _cron_finalize_stale_uploads(self):
        """finish_upload() never ran for these sessions (client never called
        it), so nothing ever triggered the Drive upload. Whatever chunks did
        arrive are still sitting in STREAM_DIR - upload them anyway instead
        of leaving the recording lost."""
        if not os.path.isdir(STREAM_DIR):
            return

        dbname = self.env.cr.dbname
        now = time.time()

        for meta_file in glob.glob(os.path.join(STREAM_DIR, '*.meta.json')):
            try:
                mtime = os.path.getmtime(meta_file)
            except OSError:
                continue
            if now - mtime < STALE_AFTER_SECONDS:
                continue  # still actively receiving chunks

            upload_id = os.path.basename(meta_file).replace('.meta.json', '')
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
            except Exception:
                _logger.exception("STALE_UPLOAD could not read meta %s", meta_file)
                continue

            filepath = meta.get('path')
            picking_id = int(meta.get('picking_id') or 0)
            mimetype = meta.get('mimetype') or 'video/webm'

            if not filepath or not os.path.exists(filepath):
                _logger.warning("STALE_UPLOAD no webm file for id=%s, dropping meta", upload_id)
                try:
                    os.remove(meta_file)
                except Exception:
                    pass
                continue

            claimed_meta_file = _uploading_meta_path(upload_id)
            try:
                os.replace(meta_file, claimed_meta_file)
            except FileNotFoundError:
                continue  # a real finish_upload call claimed it in the meantime

            _logger.info(
                "STALE_UPLOAD auto-finalizing abandoned session id=%s pick=%s "
                "(idle %.0fs)", upload_id, picking_id, now - mtime,
            )
            _bg_upload_to_drive(dbname, picking_id, filepath, mimetype)
            try:
                os.remove(claimed_meta_file)
            except Exception:
                pass
