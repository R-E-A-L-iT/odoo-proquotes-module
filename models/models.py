#-*- coding: utf-8 -*-

import ast
import base64
import re

from datetime import datetime, timedelta
from functools import partial
from itertools import groupby

from odoo import api, fields, models, SUPERUSER_ID, _, tools
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.misc import formatLang, get_lang
from odoo.osv import expression
from odoo.tools import float_is_zero, float_compare
from odoo import models, fields, api

class order(models.Model):
    _inherit = 'sale.order'
    
    partner_ids = fields.Many2many('res.partner','display_name', string="Contacts")
    
    def _amount_all(self):
        for order in self:
            amount_untaxed = amount_tax = 0.0
            for line in order.order_line:
                if(line.selected == 'true' and line.sectionSelected == 'true'):
                    amount_untaxed += line.price_subtotal
                    amount_tax += line.price_tax
            order.update({
                'amount_untaxed': amount_untaxed,
                'amount_tax': amount_tax,
                'amount_total': amount_untaxed + amount_tax,
            })
            
    def _compute_amount_undiscounted(self):
        for order in self:
            total = 0.0
            for line in order.order_line:
                if(line.selected == 'true' and line.sectionSelected == 'true'):
                    total += line.price_subtotal + line.price_unit * ((line.discount or 0.0) / 100.0) * line.product_uom_qty  # why is there a discount in a field named amount_undiscounted ??
            order.amount_undiscounted = total 
            
    def _amount_by_group(self):
        for order in self:
            currency = order.currency_id or order.company_id.currency_id
            fmt = partial(formatLang, self.with_context(lang=order.partner_id.lang).env, currency_obj=currency)
            res = {}
            for line in order.order_line:
                price_reduce = line.price_unit * (1.0 - line.discount / 100.0)
                taxes = line.tax_id.compute_all(price_reduce, quantity=line.product_uom_qty, product=line.product_id, partner=order.partner_shipping_id)['taxes']
                for tax in line.tax_id:
                    group = tax.tax_group_id
                    res.setdefault(group, {'amount': 0.0, 'base': 0.0})
                    for t in taxes:
                        if(line.selected != 'true' or line.sectionSelected != 'true'):
                            break;
                        if (t['id'] == tax.id or t['id'] in tax.children_tax_ids.ids):
                            res[group]['amount'] += t['amount']
                            res[group]['base'] += t['base']
            res = sorted(res.items(), key=lambda l: l[0].sequence)
            order.amount_by_group = [(
                l[0].name, l[1]['amount'], l[1]['base'],
                fmt(l[1]['amount']), fmt(l[1]['base']),
                len(res),
            ) for l in res]

class orderLineProquotes(models.Model):
    _inherit = 'sale.order.line'
    
    variant = fields.Many2one('proquotes.variant', string="Variant Group")
    
    selected = fields.Selection([
        ('true', "Yes"),
        ('false', "No")], default="true", required=True, help="Field to Mark Wether Customer has Selected Product")
    
    sectionSelected = fields.Selection([
        ('true', "Yes"),
        ('false', "No")], default="true", required=True, help="Field to Mark Wether Container Section is Selected")
    
    special = fields.Selection([
        ('regular', "regular"),
        ('multiple', "Multiple"),
        ('optional', "Optional")], default='regular', required=True, help="Technical field for UX purpose.")
    
    hiddenSection = fields.Selection([
        ('yes', "Yes"),
        ('no', "No")], default='no', required=True, help="Field To Track if Sections are folded")
    
    optional = fields.Selection([
        ('yes', "Yes"),
        ('no', "No")], default="no", required=True, help="Field to Mark Product as Optional")
    
    quantityLocked = fields.Selection([
        ('yes', "Yes"),
        ('no', "No")], string="Lock Quantity", default="yes", required=True, help="Field to Lock Quantity on Products")
    
    def get_sale_order_line_multiline_description_sale(self, product):
        if product.description_sale:
            return product.description_sale
        else:
            return "<span></span>"    

class proquotesMail(models.TransientModel):
    _inherit = 'mail.compose.message'
    
    def generate_email_for_composer(self, template_id, res_ids, fields):
        """ Call email_template.generate_email(), get fields relevant for
            mail.compose.message, transform email_cc and email_to into partner_ids """
        multi_mode = True
        if isinstance(res_ids, int):
            multi_mode = False
            res_ids = [res_ids]

        returned_fields = fields + ['partner_ids', 'attachments']
        values = dict.fromkeys(res_ids, False)

        template_values = self.env['mail.template'].with_context(tpl_partners_only=True).browse(template_id).generate_email(res_ids, fields)
        for res_id in res_ids:
            res_id_values = dict((field, template_values[res_id][field]) for field in returned_fields if template_values[res_id].get(field))
            res_id_values['body'] = res_id_values.pop('body_html', '')
            if template_values[res_id].get('model') == 'sale.order':
                res_id_values['partner_ids'] = self.env['sale.order'].browse(res_id).partner_id + self.env['sale.order'].browse(res_id).partner_ids
            values[res_id] = res_id_values
        return multi_mode and values or values[res_ids[0]]
    
        
class variant(models.Model):
    _name = 'proquotes.variant'
    _description = "Model that Represents Variants for Customer Multi-Level Choices"
    
    name = fields.Char(string='Variant Group', required=True, copy=False, index=True, default="New")
    
    rule = fields.Char(string="Variant Rule", required=True, default="None")
    
class person(models.Model):
    _inherit = "res.partner"
    
    products = fields.One2many('stock.production.lot', 'owner', string="Products")
    
class owner(models.Model):
    _inherit = "stock.production.lot"
    
    owner = fields.Many2one('res.partner', string="Owner")
