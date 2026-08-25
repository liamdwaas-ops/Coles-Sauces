from email.message import EmailMessage
from email.utils import formatdate
from html import escape
import smtplib

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


HEADERS = ["Observed (UTC)", "Retailer", "Brand", "Change", "Product", "Before", "After",
           "Current Price (AUD)", "Original Price (AUD)", "Promotional Price (AUD)",
           "Discount", "Online Only", "Availability", "Size", "Image URL", "Product URL",
           "Event ID"]


def _style_sheet(ws, widths):
    header_fill = PatternFill("solid", fgColor="C41230")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(vertical="center")
    for index, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False


def write_workbook(path, events, current=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "Change History"
    ws.append(HEADERS)
    for event in events:
        ws.append([event["observed_at"], event.get("retailer", ""), event.get("brand", ""),
                   event["change_type"], event["name"], event["before"], event["after"],
                   event["price"], event.get("original_price"), event.get("promotional_price"),
                   event.get("discount_percent"), "Yes" if event.get("online_only") else "No",
                   event.get("availability_label", ""), event["size"], event["image_url"],
                   event["product_url"], event["event_id"]])
        row = ws.max_row
        ws.cell(row, 5).hyperlink = event["product_url"]
        ws.cell(row, 5).style = "Hyperlink"
        if event["image_url"]:
            ws.cell(row, 15).hyperlink = event["image_url"]
            ws.cell(row, 15).style = "Hyperlink"
    _style_sheet(ws, [22, 14, 18, 20, 48, 28, 28, 16, 16, 18, 12, 13, 22, 14, 52, 52, 28])
    for column in ("H", "I", "J"):
        for cell in ws[column][1:]:
            cell.number_format = '"$"0.00'
    for cell in ws["K"][1:]:
        cell.number_format = "0.0%"
    if current is not None:
        products = wb.create_sheet("Current Products", 0)
        products.append(["Product ID", "Retailer", "Brand", "Product", "Current Price (AUD)",
                         "Original Price (AUD)", "Promotional Price (AUD)", "Discount",
                         "Online Only", "Availability", "Size", "Image URL", "Product URL"])
        for product_id, product in sorted(current.items(), key=lambda item: (item[1].get("retailer", ""), item[1]["name"].lower())):
            products.append([product_id, product.get("retailer", ""), product.get("brand", ""),
                             product["name"], product["price"], product.get("original_price"),
                             product.get("promotional_price"), product.get("discount_percent"),
                             "Yes" if product.get("online_only") else "No",
                             product.get("availability_label", ""), product["size"],
                             product["image_url"], product["product_url"]])
            row = products.max_row
            products.cell(row, 4).hyperlink = product["product_url"]
            products.cell(row, 4).style = "Hyperlink"
            if product["image_url"]:
                products.cell(row, 12).hyperlink = product["image_url"]
                products.cell(row, 12).style = "Hyperlink"
            for column in (5, 6, 7):
                products.cell(row, column).number_format = '"$"0.00'
            products.cell(row, 8).number_format = "0.0%"
        _style_sheet(products, [18, 14, 18, 50, 16, 16, 18, 12, 13, 22, 14, 52, 52])
    wb.save(path)


def render_html(events):
    rows = []
    for e in events:
        name = f'<a href="{escape(e["product_url"], quote=True)}">{escape(e["name"])}</a>'
        image = (f'<a href="{escape(e["image_url"], quote=True)}">View image</a>'
                 if e["image_url"] else "")
        price = "" if e["price"] is None else f'${float(e["price"]):.2f}'
        original = "" if e.get("original_price") is None else f'${float(e["original_price"]):.2f}'
        promotional = "" if e.get("promotional_price") is None else f'${float(e["promotional_price"]):.2f}'
        discount = "" if e.get("discount_percent") is None else f'{float(e["discount_percent"]):.1%}'
        rows.append("<tr>" + "".join(f"<td>{v}</td>" for v in
                    [escape(e.get("retailer", "")), escape(e.get("brand", "")),
                     escape(e["change_type"]), name, escape(str(e["before"] or "")),
                     escape(str(e["after"] or "")), price, original, promotional, discount,
                     "Yes" if e.get("online_only") else "No",
                     escape(e.get("availability_label", "")), escape(e["size"]), image]) + "</tr>")
    return """<!doctype html><html><body><p>Changes detected since the previous successful weekly run:</p>
<table style="border-collapse:collapse" border="1" cellpadding="6"><thead><tr>
<th>Retailer</th><th>Brand</th><th>Change</th><th>Product</th><th>Before</th><th>After</th>
<th>Current Price</th><th>Original Price</th><th>Promotional Price</th><th>Discount</th>
<th>Online Only</th><th>Availability</th><th>Size</th><th>Image</th>
</tr></thead><tbody>""" + "".join(rows) + "</tbody></table><p>Source: Coles product pages linked above.</p></body></html>"


def render_baseline_html(current):
    rows = []
    for product in sorted(current.values(), key=lambda item: item["name"].lower()):
        name = f'<a href="{escape(product["product_url"], quote=True)}">{escape(product["name"])}</a>'
        image = (f'<a href="{escape(product["image_url"], quote=True)}">View image</a>'
                 if product["image_url"] else "")
        price = "" if product["price"] is None else f'${float(product["price"]):.2f}'
        original = ("" if product.get("original_price") is None else
                    f'${float(product["original_price"]):.2f}')
        promotional = ("" if product.get("promotional_price") is None else
                       f'${float(product["promotional_price"]):.2f}')
        discount = ("" if product.get("discount_percent") is None else
                    f'{float(product["discount_percent"]):.1%}')
        rows.append("<tr>" + "".join(f"<td>{v}</td>" for v in
                    [escape(product.get("retailer", "")), escape(product.get("brand", "")),
                     name, price, original, promotional, discount,
                     "Yes" if product.get("online_only") else "No",
                     escape(product.get("availability_label", "")), escape(product["size"]), image]) + "</tr>")
    return """<!doctype html><html><body><p>Initial Coles and Woolworths product baseline for Cheltenham VIC 3192:</p>
<table style="border-collapse:collapse" border="1" cellpadding="6"><thead><tr>
<th>Retailer</th><th>Brand</th><th>Product</th><th>Current Price</th><th>Original Price</th>
<th>Promotional Price</th><th>Discount</th><th>Online Only</th><th>Availability</th><th>Size</th><th>Image</th>
</tr></thead><tbody>""" + \
        "".join(rows) + "</tbody></table><p>Future emails will contain only new changes.</p></body></html>"


def send_email(sender, recipient, app_password, events, workbook_path, baseline=None):
    msg = EmailMessage()
    msg["From"], msg["To"] = sender, recipient
    msg["Date"] = formatdate(localtime=False)
    if baseline is not None:
        msg["Subject"] = f"Coles & Woolworths product baseline — {len(baseline)} products"
        msg.set_content("Initial Coles and Woolworths product baseline. Open as HTML or see the attached Excel workbook.")
        msg.add_alternative(render_baseline_html(baseline), subtype="html")
    else:
        msg["Subject"] = f"Coles & Woolworths product changes — {len(events)} change{'s' if len(events) != 1 else ''}"
        msg.set_content("Changes were detected. Open this message as HTML or see the attached Excel history.")
        msg.add_alternative(render_html(events), subtype="html")
    with open(workbook_path, "rb") as handle:
        msg.add_attachment(handle.read(), maintype="application",
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           filename="coles-woolworths-sauce-change-history.xlsx")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(msg)
