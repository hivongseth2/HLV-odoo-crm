# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


def post_load():
    """Make import in post_load to avoid applying monkey patches when this
    module is not installed."""
    from . import models
    from . import controllers
