# -*- coding: utf-8 -*-
###############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Aysha Shalin (odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC
#    LICENSE (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from openai import OpenAI

from odoo import models, _
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    """ Inherit product.template model """
    _inherit = 'product.template'

    def action_create_tag_description(self):
        """ Function to create tags from description """
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'openai_api_key')
        if not api_key:
            raise ValidationError(
                _("Invalid API key provided. Please ensure that you have "
                  "entered the correct API key. "))
        product_id = self._context['active_id']
        product = self.env['product.template'].browse(product_id)
        if product.description:
            prompt = "Generate tags for the following description: \n" + str(
                product.description) + "\n\nTags:"
            client = OpenAI(
                api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an AI assistant"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.8,
                top_p=1
            )
            tags = response.choices[0].message.content
            tags = [tag.strip() for tag in tags.split(',')]
            tags_exists = self.env['product.tag'].search([]).mapped('name')
            for tag in tags:
                if tag not in tags_exists:
                    tag_created = self.env['product.tag'].create({
                        'name': tag,
                        'product_template_ids': [(4, product_id)]})
                    product.write({
                        'product_tag_ids': [(4, tag_created.id)]
                    })
                else:
                    tags_exist = self.env['product.tag'].search(
                        [('name', '=', tag)])
                    tags_exist.write(
                        {'product_template_ids': [(4, product_id)]})
                    for tag_apply in tags_exist:
                        product.write({'product_tag_ids': [(4, tag_apply.id)]})
        else:
            raise ValidationError(
                _("No description for this product"))

    def generate_description_from_tags(self):
        """ Function to create description from tags """
        prompt = "Generate a description for a product based on" \
                 " the following tags: \n"
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'openai_api_key')
        product_id = self._context['active_id']
        product = self.env['product.template'].browse(product_id)
        if not api_key:
            raise ValidationError(_("Invalid API key provided. Please ensure"
                                    " that you have entered the correct API "
                                    "key. "))
        if product.product_tag_ids:
            for tag in product.product_tag_ids:
                prompt += f"- {tag.name}\n"
            prompt += "\nDescription:"
            client = OpenAI(
                api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an AI assistant"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.8,
                top_p=1
            )
            description = response.choices[0].message.content
            product.description = description
        else:
            raise ValidationError(_("No tags for this product."))
