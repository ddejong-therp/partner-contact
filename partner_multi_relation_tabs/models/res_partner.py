# Copyright 2014-2020 Therp BV <https://therp.nl>.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
# pylint: disable=no-member
"""Add tab fields to res.partner model and make sure tabs are added to form."""
import logging
from lxml import etree

from odoo import _, api, fields, models


_logger = logging.getLogger(__name__)  # pylint: disable=invalid-name


class ResPartner(models.Model):
    """Add tab fields and automatically load tabs in partner forms."""
    _inherit = "res.partner"
    _tab_modification_sequence = 0

    @api.model
    def browse(self, arg=None, prefetch=None):
        """Make sure tabs are always up to date."""
        self._update_tab_fields()
        return super().browse(arg=arg, prefetch=prefetch)

    @api.model
    def fields_view_get(
            self, view_id=None, view_type="form", toolbar=False, submenu=False):
        """Override to add relation tabs to form."""
        result = super().fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu
        )
        if view_type != "form" or self.env.context.get("check_view_ids"):
            return result
        view = etree.fromstring(result["arch"])
        extra_fields = self._add_tab_pages(view)
        view_model = self.env["ir.ui.view"]
        result["arch"], original_fields = view_model.postprocess_and_fields(
            self._name, view, result["view_id"]
        )
        for fieldname in extra_fields:
            result["fields"][fieldname] = original_fields[fieldname]
        return result

    def _update_tab_fields(self):
        """Make sure all defined tab fields are present."""
        if not self._need_tab_update():
            return
        for tab in self._get_tabs():
            fieldname = tab.get_fieldname()
            if fieldname not in self._fields:
                # Check this for performance reasons.
                self.add_field(tab)

    def _need_tab_update(self):
        """Check wether tab needs update."""
        sequence_model = self.env["res.partner.tab.sequence"]
        tab_modification_sequence = sequence_model.get_sequence()
        if tab_modification_sequence == self._tab_modification_sequence:
            return False  # We are already up to date.
        _logger.info(_("Updating tabs to modification %d"), tab_modification_sequence)
        self._set_tab_modification_sequence(tab_modification_sequence)
        return True

    @classmethod
    def _set_tab_modification_sequence(cls, tab_modification_sequence):
        """Use class method to prevent creating copies of modification level."""
        cls._tab_modification_sequence = tab_modification_sequence

    def _add_tab_pages(self, view):
        """Adds the relevant tabs to the partner's formview."""
        def add_invisible_extra_field(view, extra_fields, fieldname):
            """Add invisible field to view."""
            view.append(etree.Element("field", name=fieldname, invisible="True"))
            extra_fields.append(fieldname)

        last_page_nodes = view.xpath("//page[last()]")
        if not last_page_nodes:
            # Nothing to do if form contains no pages/tabs.
            return []
        extra_fields = []
        if not view.xpath('//field[@name="id"]'):
            add_invisible_extra_field(view, extra_fields, "id")
        last_page = last_page_nodes[0]
        for tab in self._get_tabs():  # get all tabs
            self.add_field(tab)
            add_invisible_extra_field(view, extra_fields, tab.get_visible_fieldname())
            extra_fields.append(tab.get_fieldname())
            tab_page = tab.create_page()
            last_page.addnext(tab_page)
            last_page = tab_page  # Keep ordering of tabs
        return extra_fields

    @api.depends("is_company", "category_id")
    def _compute_tabs_visibility(self):
        """Compute for all tabs wether they should be visible."""
        for tab in self._get_tabs():  # get all tabs
            for this in self:
                this[tab.get_visible_fieldname()] = tab.compute_visibility(this)

    def _get_tabs(self):
        tab_model = self.env["res.partner.tab"]
        return tab_model.get_tabs()

    def add_field(self, tab):
        """Add tab field to model.

        Will replace existing field if already present.
        """
        # Visible field determines wether first field will be visible.
        # This is because domains on many2many no longer work in 9.0
        # and above.
        visible_field = fields.Boolean(compute="_compute_tabs_visibility")
        self._add_field(tab.get_visible_fieldname(), visible_field)
        if visible_field not in self._field_computed:
            self._field_computed[visible_field] = [visible_field]
        tab_field = fields.One2many(
            comodel_name="res.partner.relation.all",
            inverse_name="this_partner_id",
            domain=[("tab_id", "=", tab.tab_record.id)],
            context={"active_test": False},
            string=tab.tab_record.name,
        )
        self._add_field(tab.get_fieldname(), tab_field)
