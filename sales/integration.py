import calendar
import datetime
import io
from dataclasses import dataclass
from xml.etree import ElementTree

from django.db import connections, transaction

from sales.models import Invoice


@dataclass(frozen=True)
class ParsedInvoice:
    number: int
    date: datetime.date
    customer: str
    operation: float
    total: float
    tax: float


def parse_invoice_xml(file) -> ParsedInvoice:
    """Read the necessary fields of a Brazilian invoice XML
    """
    NS = {'p': 'http://www.portalfiscal.inf.br/nfe'}

    tree = ElementTree.parse(file)
    root = tree.find('.//p:infNFe', NS)

    e = root.find('p:ide', NS)
    txt_number = e.find('p:nNF', NS).text
    try:
        txt_date = e.find('p:dhEmi', NS).text[0:10]
    except AttributeError:
        txt_date = e.find('p:dEmi', NS).text

    e = root.find('p:dest', NS)
    txt_customer = e.find('p:xNome', NS).text

    e = root.find('p:det/p:prod', NS)
    txt_operation = e.find('p:CFOP', NS).text

    e = root.find('p:total/p:ICMSTot', NS)
    txt_total = e.find('p:vNF', NS).text
    txt_tax = e.find('p:vICMS', NS).text

    return ParsedInvoice(
        number=int(txt_number),
        date=datetime.date.fromisoformat(txt_date),
        customer=txt_customer.upper(),
        operation=int(txt_operation) / 1000,
        total=float(txt_total),
        tax=float(txt_tax),
    )


CODE_NATURE = {
    1.411: Invoice.SALE_RETURN,
    5.929: Invoice.SALE,
    6.202: Invoice.PURCHASE_RETURN,
    6.411: Invoice.PURCHASE_RETURN,
    6.915: Invoice.RMA,
    6.949: Invoice.RMA,
}


def import_invoices(year: int, month: int):
    """Import from the sales system the invoices issued at a specified period
    """
    begin_date = datetime.date(year, month, 1)
    end_date = datetime.date(year, month, calendar.monthlen(year, month))

    conn = connections['integration']

    with conn.cursor() as v_cursor, conn.cursor() as t_cursor:
        sql = '''
            SELECT
              NUMERO, DATA_EMISSAO, XML, RECIBO_CODSTATUS, CANCELA_CODSTATUS
            FROM
              VENDAS_NFE
            WHERE DOC = 'NF' AND DATA_EMISSAO BETWEEN %s AND %s
            ORDER BY NUMERO
        '''

        v_cursor.execute(sql, [begin_date, end_date])

        with transaction.atomic():
            for txt_number, date, xml, status, cancel_status in v_cursor:
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
                    pix = parse_invoice_xml(io.BytesIO(xml))
                    assert pix.number == number
                    assert pix.date == date

                    # Fill the invoice with the extra info
                    v.nature = CODE_NATURE[pix.operation]
                    v.customer = pix.customer
                    v.total = pix.total
                    v.tax = pix.tax

                    # If invoice is a sale, we need an extra database query to get the tickets.
                    # This is needed to avoid an expensive and not very correct search in XML comments.
                    if v.nature == Invoice.SALE:
                        sql = "SELECT DISTINCT NUMERO_IMP FROM ITEVENDAS WHERE DOC = 'NF' AND NUMERO = '%s'"
                        t_cursor.execute(sql % txt_number)
                        tickets_list = t_cursor.fetchall()
                        if any(tickets_list):
                            v.tickets = ','.join([e for (e,) in tickets_list if e])

                # And the invoice is saved \o/
                v.full_clean()
                v.save()
