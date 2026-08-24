from email.message import EmailMessage
from email.utils import formatdate
from html import escape
import smtplib

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


HEADERS = ["Observed (UTC)", "Change", "Product", "Before", "After", "Price (AUD)",
           "Size", "Image URL", "Product URL", "Event ID"]


def write_workbook(path, events):
    wb = Workbook()
    ws = wb.active
    ws.title = "Change History"
    ws.append(HEADERS)
    for event in events:
        ws.append([event["observed_at"], event["change_type"], event["name"], event["before"],
                   event["after"], event["price"], event["size"], event["image_url"],
                   event["product_url"], event["event_id"]])
        row = ws.max_row
        ws.cell(row, 3).hyperlink = event["product_url"]
        ws.cell(row, 3).style = "Hyperlink"
        if event["image_url"]:
            ws.cell(row, 8).hyperlink = event["image_url"]
            ws.cell(row, 8).style = "Hyperlink"
    header_fill = PatternFill("solid", fgColor="C41230")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(vertical="center")
    widths = [22, 18, 48, 30, 30, 14, 14, 52, 52, 28]
    for index, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["F"].number_format = '"$"0.00'
    wb.save(path)


def render_html(events):
    rows = []
    for e in events:
        name = f'<a href="{escape(e["product_url"], quote=True)}">{escape(e["name"])}</a>'
        image = (f'<a href="{escape(e["image_url"], quote=True)}">View image</a>'
                 if e["image_url"] else "")
        price = "" if e["price"] is None else f'${float(e["price"]):.2f}'
        rows.append("<tr>" + "".join(f"<td>{v}</td>" for v in [escape(e["change_type"]), name,
                    escape(str(e["before"] or "")), escape(str(e["after"] or "")), price,
                    escape(e["size"]), image]) + "</tr>")
    return """<!doctype html><html><body><p>Changes detected since the previous successful weekly run:</p>
<table style="border-collapse:collapse" border="1" cellpadding="6"><thead><tr>
<th>Change</th><th>Product</th><th>Before</th><th>After</th><th>Price</th><th>Size</th><th>Image</th>
</tr></thead><tbody>""" + "".join(rows) + "</tbody></table><p>Source: Coles product pages linked above.</p></body></html>"


def send_email(sender, recipient, app_password, events, workbook_path):
    msg = EmailMessage()
    msg["From"], msg["To"] = sender, recipient
    msg["Date"] = formatdate(localtime=False)
    msg["Subject"] = f"Coles product changes — {len(events)} change{'s' if len(events) != 1 else ''}"
    msg.set_content("Changes were detected. Open this message as HTML or see the attached Excel history.")
    msg.add_alternative(render_html(events), subtype="html")
    with open(workbook_path, "rb") as handle:
        msg.add_attachment(handle.read(), maintype="application",
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           filename="coles-product-change-history.xlsx")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(msg)

