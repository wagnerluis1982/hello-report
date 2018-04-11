from django.core.validators import validate_comma_separated_integer_list
from django.db import models
from django.utils.translation import gettext_lazy as _


class Invoice(models.Model):
    SALE = 'S'
    SKIPPED = 'K'
    CANCELED = 'C'
    DENIED = 'D'
    SALE_RETURN = 'U'
    PURCHASE_RETURN = 'P'
    RMA = 'R'

    NATURE_CHOICES = (
        (SALE, _('Sale')),
        (SKIPPED, _('Skipped')),
        (CANCELED, _('Canceled')),
        (DENIED, _('Denied')),
        (SALE_RETURN, _('Sale return')),
        (PURCHASE_RETURN, _('Purchase return')),
        (RMA, _('RMA')),
    )

    number = models.PositiveIntegerField(_('number'), primary_key=True)
    date = models.DateField(_('date'))
    customer = models.CharField(_('customer'), max_length=60, null=True, blank=True)
    nature = models.CharField(_('nature'), max_length=1, choices=NATURE_CHOICES)
    total = models.FloatField(_('total'), null=True, blank=True)
    tax = models.FloatField(_('tax'), null=True, blank=True)
    tickets = models.CharField(_('tickets'), max_length=100, validators=[validate_comma_separated_integer_list], null=True, blank=True)
    comment = models.CharField(_('comment'), max_length=100, null=True, blank=True)

    class Meta:
        verbose_name = _('invoice')
        verbose_name_plural = _('invoices')

    def tickets_list(self):
        return self.tickets.split(",")

    def __str__(self):
        return "%06d - %s" % (self.number, self.customer or '[%s]' % self.get_nature_display().upper())
