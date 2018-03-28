import calendar
import datetime
import io
from dataclasses import dataclass
from html.parser import HTMLParser

from django.conf import settings
from django.db import transaction
from sqlalchemy import create_engine

from sales.models import Invoice


@dataclass(frozen=True)
class ParsedInvoice:
    number: int
    date: datetime.date
    customer: str
    operation: float
    total: float
    tax: float


class InvoiceParser(HTMLParser):
    """Read the necessary fields of a Brazilian invoice XML
    """
    def reset(self):
        super().reset()
        self.result = {}
        self.track = {k: False for k in ('infnfe', 'ide', 'dest', 'det', 'prod', 'total', 'icmstot')}
        self.tag = None

    def handle_starttag(self, tag, attrs):
        self.tag = tag
        if tag in self.track:
            self.track[tag] = True

    def handle_endtag(self, tag):
        self.tag = None
        if tag in self.track:
            self.track[tag] = False

    def handle_data(self, data):
        tag = self.tag
        is_prev = self.is_prev

        if is_prev('infnfe'):
            if is_prev('ide'):
                if tag == 'nnf':
                    self.result['number'] = data
                elif tag == 'dhemi':
                    self.result['date'] = data[0:10]
                elif tag == 'demi':
                    self.result['date'] = data
                self.free('ide', if_has=('number', 'date'))
            elif is_prev('dest'):
                if tag == 'xnome':
                    self.result['customer'] = data
                    self.free('dest')
            elif is_prev('det', 'prod'):
                if tag == 'cfop':
                    self.result['operation'] = data
                    self.free('det', 'prod')
            elif is_prev('total', 'icmstot'):
                if tag == 'vnf':
                    self.result['total'] = data
                elif tag == 'vicms':
                    self.result['tax'] = data
                self.free('total', 'icmstot', if_has=('total', 'tax'))

    def is_prev(self, *tags):
        for tag in tags:
            if tag == self.tag or not self.track[tag]:
                return False
        return True

    def free(self, *tags, if_has=()):
        for k in if_has:
            if k not in self.result:
                return
        for tag in tags:
            self.track[tag] = False

    def error(self, message):
        raise Exception(message)

    @classmethod
    def parse(cls, file) -> ParsedInvoice:
        """Parse and format the parsing result
        """
        content = file.read()
        if isinstance(content, bytes):
            content = content.decode()

        parser = cls()
        parser.feed(content)

        r = parser.result

        return ParsedInvoice(
            number=r['number'],
            date=r['date'][0:10],
            customer=r['customer'],
            operation=r['operation'],
            total=r['total'],
            tax=r['tax'],
        )


CODE_NATURE = {
    '1411': Invoice.SALE_RETURN,
    '5929': Invoice.SALE,
    '6202': Invoice.PURCHASE_RETURN,
    '6411': Invoice.PURCHASE_RETURN,
    '6915': Invoice.RMA,
    '6949': Invoice.RMA,
}


def import_invoices(year: int, month: int, engine=create_engine(settings.INTEGRATION_DATABASE)):
    """Import from the sales system the invoices issued at a specified period
    """
    begin_date = datetime.date(year, month, 1)
    end_date = datetime.date(year, month, calendar.monthlen(year, month))

    with engine.connect() as conn:
        sql = '''
            SELECT
              NUMERO, DATA_EMISSAO, XML, RECIBO_CODSTATUS, CANCELA_CODSTATUS
            FROM
              VENDAS_NFE
            WHERE DOC = 'NF' AND DATA_EMISSAO BETWEEN ? AND ?
            ORDER BY NUMERO
        '''

        v_result = conn.execute(sql, [begin_date, end_date])

        with transaction.atomic():
            for txt_number, date, xml, status, cancel_status in v_result:
                # Ensure number as integer
                number = int(txt_number)

                # Create a not yet complete invoice
                v = Invoice(number=number, date=date)

                # On canceled or denied invoice, we don't need more info.
                if cancel_status:
                    v.nature = Invoice.CANCELED
                elif status != '100':
                    v.nature = Invoice.DENIED

                # Otherwise, we need to parse the invoice XML.
                else:
                    pix = InvoiceParser.parse(io.BytesIO(xml))
                    assert int(pix.number) == number
                    assert pix.date == date.isoformat()

                    # Fill the invoice with the extra info
                    v.nature = CODE_NATURE[pix.operation]
                    v.customer = pix.customer.upper()
                    v.total = float(pix.total)
                    v.tax = float(pix.tax)

                    # If invoice is a sale, we need an extra database query to get the tickets.
                    # This is needed to avoid an expensive and not very correct search in XML comments.
                    if v.nature == Invoice.SALE:
                        sql = "SELECT DISTINCT NUMERO_IMP FROM ITEVENDAS WHERE DOC = 'NF' AND NUMERO = '%s'"
                        t_result = conn.execute(sql % txt_number)
                        tickets_list = t_result.fetchall()
                        if any(tickets_list):
                            v.tickets = ','.join([e for (e,) in tickets_list if e])

                # And the invoice is saved \o/
                v.full_clean()
                v.save()
