# Colab setup
pip install easyocr opencv-python-headless pandas openpyxl

import easyocr
import cv2
import pandas as pd
import re
import os

# EasyOCR modelini Türkçe + İngilizce yükle
reader = easyocr.Reader(['tr','en'])

def clean_amount(value):
    """OCR'dan gelen tutarları normalize et"""
    if not value:
        return ""
    val = re.sub(r"[^\d,\.]", "", value)  # sadece rakam ve noktalama kalsın
    val = val.replace(".", "").replace(",", ".")  # Türkçe formatı normalize et
    try:
        return float(val)
    except:
        return value

def parse_invoice(image_path):
    """Faturayı oku ve JSON formatında verileri çıkar"""
    results = reader.readtext(image_path, detail=0)
    text = " ".join(results)

    invoice_data = {
        "Fatura No": "",
        "Fatura Tarihi": "",
        "Alıcının Adı/Ünvanı": "",
        "Alıcının Adresi": "",
        "VK Bilgisi": "",
        "V.D.H. No": "",
        "Telefon": "",
        "Bağlı olduğu V.D.": "",
        "Vergi sicil no": "",
        "Miktar": [],
        "Açıklama": [],
        "Birim": [],
        "Tutar": [],
        "Ara Toplam": "",
        "KDV": "",
        "Genel Toplam": "",
        "Yazı ile toplam": ""
    }

    # Basit regex örnekleri
    fatura_no = re.search(r"Fatura\s*No[:\s]*([A-Za-z0-9-]+)", text, re.IGNORECASE)
    if fatura_no:
        invoice_data["Fatura No"] = fatura_no.group(1)

    tarih = re.search(r"(\d{2}[./-]\d{2}[./-]\d{4})", text)
    if tarih:
        invoice_data["Fatura Tarihi"] = tarih.group(1)

    genel_toplam = re.search(r"(Genel Toplam|TOPLAM)[:\s]*([\d.,]+)", text, re.IGNORECASE)
    if genel_toplam:
        invoice_data["Genel Toplam"] = clean_amount(genel_toplam.group(2))

    return invoice_data

def process_invoices(image_paths, excel_path="invoices.xlsx"):
    """Birden fazla faturayı işle ve Excel’e yaz"""
    all_invoices = []

    for path in image_paths:
        data = parse_invoice(path)
        all_invoices.append(data)

    df = pd.DataFrame(all_invoices)
    df.to_excel(excel_path, index=False)
    print(f"✅ Excel kaydedildi: {excel_path}")

# Örnek kullanım
uploaded_files = ["fatura1.jpg", "fatura2.png"]  # kendi fatura resimlerini yükle
process_invoices(uploaded_files, "faturalar.xlsx")

