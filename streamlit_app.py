import streamlit as st
import requests
import pandas as pd
import re
import unicodedata
from io import BytesIO

# ====== Ayarlar ======
API_KEY = "K84160666388957"
API_URL = "https://api.ocr.space/parse/image"

EXCEL_COLUMNS = [
    "Fatura No",
    "Fatura Tarihi",
    "Alıcının Adı/Ünvanı",
    "Alıcının Adresi",
    "VK Bilgisi",
    "V.D.H. No",
    "Telefon",
    "Bağlı olduğu V.D.",
    "Vergi sicil no",
    "Miktar",
    "Açıklama",
    "Birim",
    "Tutar",
    "Ara Toplam",
    "KDV",
    "Genel Toplam",
    "Yazı ile toplam"
]

# ====== Yardımcılar ======
TR_MONTHS = {
    "oca":"01","ocak":"01",
    "şub":"02","sub":"02","şubat":"02","subat":"02",
    "mar":"03","mart":"03",
    "nis":"04","nisan":"04",
    "may":"05","mayıs":"05","mayis":"05",
    "haz":"06","haziran":"06",
    "tem":"07","temmuz":"07",
    "ağu":"08","agu":"08","ağustos":"08","agustos":"08",
    "eyl":"09","eylül":"09","eylul":"09",
    "eki":"10","ekim":"10",
    "kas":"11","kasım":"11","kasim":"11",
    "ara":"12","aralık":"12","aralik":"12"
}

def normalize_text(t: str) -> str:
    if not t: return ""
    t = unicodedata.normalize("NFKC", t)
    # yaygın OCR karakter karışmaları
    repl = {
        "O":"0","o":"0","I":"1","l":"1","İ":"I","ı":"i",
        "S":"5","s":"5","B":"8","b":"6","€":"E","—":"-","–":"-","’":"'"
    }
    for k,v in repl.items():
        t = t.replace(k, v)
    # para simgelerini tek tipe indir
    t = t.replace("TRY", "₺").replace("TL", "₺").replace("₺ ", "₺")
    # çoklu boşlukları sadeleştir
    t = re.sub(r"[ \t]+", " ", t)
    return t

def normalize_phone(text: str) -> str:
    m = re.search(r"(\+?9?0?\s*5\d{2}\s*\d{3}\s*\d{2}\s*\d{2})", text)
    if not m: 
        m = re.search(r"(\+?9?0?\s*\(?5\d{2}\)?[\s\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2})", text)
    if not m: 
        return ""
    digits = re.sub(r"\D", "", m.group(1))
    if digits.startswith("90") and len(digits)==12:
        return digits
    if digits.startswith("0") and len(digits)==11:
        return digits
    if len(digits)==10 and digits.startswith("5"):
        return "0"+digits
    return digits

def parse_number_from_ocr_string(text: str):
    """
    TR formatlı tutarları güvenli biçimde floata çevirir.
    Örn: '₺116.000,00' -> 116000.00 ; '6.845 TL' -> 6845.00
    """
    if not text:
        return None
    t = text
    t = t.replace("₺","")
    # yalnız rakam ve ayraçları bırak
    t = re.sub(r"[^0-9\.,\-]", "", t)

    if not t:
        return None
    # Ondalık ayırıcıyı belirle: sondaki ayraç neyse odur
    last_comma = t.rfind(",")
    last_dot   = t.rfind(".")
    if last_comma > last_dot:
        # ',' ondalık
        int_part = t[:last_comma].replace(".", "")
        dec_part = t[last_comma+1:]
        t = int_part + "." + dec_part
    elif last_dot > last_comma and last_dot != -1:
        # '.' ondalık
        int_part = t[:last_dot].replace(",", "")
        dec_part = t[last_dot+1:]
        t = int_part + "." + dec_part
    else:
        # hiçbiri yok ya da tek tip – binlikleri sil
        t = t.replace(".", "").replace(",", "")
    try:
        return round(float(t), 2)
    except ValueError:
        return None

def find_label_amount(lines, *label_regexes):
    """
    'ARA TOPLAM', 'KDV', 'TOPLAM', 'G.TOPLAM', 'VERGİ' vs. için
    aynı satırda ya da bir sonraki satırda görünen ilk tutarı döndürür.
    """
    label_pattern = re.compile("|".join(label_regexes), re.I)
    amount_pattern = re.compile(r"(?:₺|TRY|TL)?\s*[-+]?\d[\d\.,]*")
    for i, line in enumerate(lines):
        if label_pattern.search(line):
            # aynı satırda ara
            candidates = amount_pattern.findall(line)
            if candidates:
                return parse_number_from_ocr_string(candidates[-1])
            # bir alt satıra bak
            if i+1 < len(lines):
                candidates = amount_pattern.findall(lines[i+1])
                if candidates:
                    return parse_number_from_ocr_string(candidates[-1])
    return None

def parse_turkish_date(text: str) -> str:
    """
    29 Ağu 2025 / 01.11.2021 / 01/11/2021 vb. -> YYYY-MM-DD
    """
    t = text.lower()
    # dd mon yyyy
    m = re.search(r"(\d{1,2})\s*([a-zçğıöşü\.]{3,})\s*(\d{4})", t, re.I)
    if m:
        d = int(re.sub(r"\D","",m.group(1)))
        mon = TR_MONTHS.get(m.group(2).strip(".")[:3], None) or TR_MONTHS.get(m.group(2), None)
        y = m.group(3)
        if mon:
            return f"{y}-{mon}-{d:02d}"
    # dd.mm.yyyy  dd/mm/yyyy
    m = re.search(r"(\d{1,2})[\.\/\-](\d{1,2})[\.\/\-](\d{4})", t)
    if m:
        d, mon, y = int(m.group(1)), int(m.group(2)), m.group(3)
        return f"{y}-{mon:02d}-{d:02d}"
    return text.strip()

def extract_items_block(lines):
    """
    Kalemleri, 'ÖĞE|AÇIKLAMA' ile 'ARA TOPLAM|KDV|TOPLAM' arası bloktan çıkartır.
    Satırın sonunda görülen tutarı alır, miktarı varsa yakalar.
    """
    start_idx, end_idx = None, None
    start_pat = re.compile(r"\b(ÖĞE|OGE|AÇIKLAMA)\b", re.I)
    end_pat   = re.compile(r"\b(ARA TOPLAM|KDV|VERGİ|GENEL TOPLAM|G\.?TOPLAM|TOPLAM)\b", re.I)
    for i, line in enumerate(lines):
        if start_idx is None and start_pat.search(line):
            start_idx = i + 1
            continue
        if start_idx is not None and end_pat.search(line):
            end_idx = i
            break
    if start_idx is None:
        # koçanlı tipte genelde direkt AÇIKLAMA alanı var; baştan tarayalım
        start_idx = 0
    if end_idx is None:
        end_idx = len(lines)

    amount_pat = re.compile(r"(?:₺|TRY|TL)?\s*[-+]?\d[\d\.,]*\s*(?:TL|TRY|₺)?\b")
    qty_pat = re.compile(r"\b(ADET|MİKTAR|MIKTAR)\b[^\d]*(\d+[\,\.]?\d*)", re.I)

    items = []
    for i in range(start_idx, end_idx):
        line = lines[i].strip()
        if not line:
            continue
        amounts = amount_pat.findall(line)
        if not amounts:
            continue
        # açıklama = satır – para ifadeleri – para kısaltmaları
        desc = amount_pat.sub("", line)
        desc = re.sub(r"\b(ORAN|ADET|MİKTAR|MIKTAR|BİRİM|BIRIM|TUTAR[I]?)\b.*", "", desc, flags=re.I).strip(" -:|;")
        if not desc:
            # bir üst satır açıklama, bu satır tutar olabilir
            if i>0 and not amount_pat.findall(lines[i-1]):
                desc = lines[i-1].strip()
        qty = None
        mq = qty_pat.search(line)
        if mq:
            qty = parse_number_from_ocr_string(mq.group(2))
        if qty is None:
            # bir alt/üst satırda miktar olabilir
            for off in (-1,1):
                j = i+off
                if 0<=j<len(lines):
                    mq2 = qty_pat.search(lines[j])
                    if mq2:
                        qty = parse_number_from_ocr_string(mq2.group(2)); break
        if qty is None: qty = 1
        tutar = parse_number_from_ocr_string(amounts[-1])
        if tutar is not None:
            items.append({"Miktar": qty, "Açıklama": desc or "Kalem", "Birim": "Adet", "Tutar": tutar})
    # benzer kalemlerin tekrarlı yakalanmasını azalt: açıklama+tutar bazında uniq
    uniq = {}
    for it in items:
        key = (it["Açıklama"], it["Tutar"])
        if key not in uniq:
            uniq[key] = it
    return list(uniq.values())

def extract_invoice_fields(raw_text: str):
    text = normalize_text(raw_text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    U = "\n".join(lines)  # satır kırpılmış birleştirilmiş metin

    data = {col: "" for col in EXCEL_COLUMNS}

    # Fatura No – 'FATURA' başlığının yanındaki/alttaki uzun sayı
    m = re.search(r"FATURA\s*(?:NO|No|#|:)?\s*([0-9]{4,})", U, re.I)
    if not m:
        # alt satırda olabilir
        for i, line in enumerate(lines):
            if re.search(r"\bFATURA\b", line, re.I):
                if i+1 < len(lines):
                    m2 = re.search(r"([0-9]{4,})", lines[i+1])
                    if m2: 
                        data["Fatura No"] = m2.group(1)
                break
    else:
        data["Fatura No"] = m.group(1)

    # Tarih
    m = re.search(r"\b(TAR[Iİ]H|Tarih)\b[^\n]*", U, re.I)
    date_str = None
    if m:
        date_str = parse_turkish_date(m.group(0))
    if not date_str:
        # alternatif: 'İMZALANDIĞI TARİH' satırı ya da ilk görülen tarih
        for line in lines:
            if re.search(r"İMZALANDI(GI|ĞI)\s*TAR[Iİ]H", line, re.I):
                date_str = parse_turkish_date(line)
                break
        if not date_str:
            for line in lines:
                if re.search(r"\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{4}", line) or re.search(r"\d{1,2}\s*[a-zçğıöşü\.]{3,}\s*\d{4}", line, re.I):
                    date_str = parse_turkish_date(line); break
    if date_str: data["Fatura Tarihi"] = date_str

    # Alıcı adı/ünvanı
    m = re.search(r"FATURA\s*ALICISI\s*\n?(.+)", U, re.I)
    if m:
        data["Alıcının Adı/Ünvanı"] = m.group(1).strip()
    else:
        m = re.search(r"Alıc[ıi]n[ıi]n\s+Ad[ıi]\s*/?\s*Ünvan[ıi]?\s*[:\-]?\s*(.+)", U, re.I)
        if m:
            data["Alıcının Adı/Ünvanı"] = m.group(1).strip()

    # Telefon
    tel = normalize_phone(U)
    if tel: data["Telefon"] = tel

    # Adres (telefon satırının bir üstü/öncesi)
    if tel:
        for i, line in enumerate(lines):
            if tel in re.sub(r"\D", "", line):
                if i>0:
                    data["Alıcının Adresi"] = lines[i-1]
                break

    # Vergi / VKN / V.D.H / Bağlı olduğu V.D / Vergi sicil
    m = re.search(r"\bVK[:\s]*([A-Za-z0-9\-\.]+)", U, re.I)
    if m: data["VK Bilgisi"] = m.group(1)

    m = re.search(r"V\.\s*D\.\s*H\.?\s*No[:\s]*([A-Za-z0-9\-\.]+)", U, re.I)
    if m: data["V.D.H. No"] = m.group(1)

    m = re.search(r"Ba[ğg]l[ıi]\s*oldu[gğ]u\s*V\.\s*D\.[:\s]*([^\n]+)", U, re.I)
    if m: data["Bağlı olduğu V.D."] = m.group(1).strip()

    m = re.search(r"Vergi\s*sicil\s*no[:\s]*([A-Za-z0-9\-\.]+)", U, re.I)
    if m: data["Vergi sicil no"] = m.group(1)

    # Kalemler
    items = extract_items_block(lines)
    if items:
        data["Miktar"]     = [it["Miktar"] for it in items]
        data["Açıklama"]   = [it["Açıklama"] for it in items]
        data["Birim"]      = [it["Birim"] for it in items]
        data["Tutar"]      = [it["Tutar"] for it in items]

    # Ara Toplam / KDV / Genel Toplam / Yazı ile
    ara = find_label_amount(lines, r"\bARA\s*TOPLAM\b")
    kdv = find_label_amount(lines, r"\bKDV\b", r"\bVERG[iİ]\b", r"\bVERG[Iİ]\s*\(\s*\d+%\s*\)")
    gen = find_label_amount(lines, r"\bGENEL\s*TOPLAM\b", r"\bG\.?\s*TOPLAM\b", r"^\s*TOPLAM\b")

    if ara is None and items:
        ara = round(sum(it["Tutar"] for it in items), 2)
    if gen is None and ara is not None and kdv is not None:
        gen = round(ara + kdv, 2)
    if kdv is None and ara is not None and gen is not None:
        kdv = round(gen - ara, 2)

    if ara is not None: data["Ara Toplam"] = ara
    if kdv is not None: data["KDV"] = kdv
    if gen is not None: data["Genel Toplam"] = gen

    # Yazı ile toplam
    m = re.search(r"Yaz[ıi]\s*ile\s*([^\n#]+)", U, re.I)
    if m: data["Yazı ile toplam"] = m.group(1).strip().strip("# ")

    return data

def to_csv_bytes(df):
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

# ====== Streamlit Arayüzü ======
st.title("📄 Çoklu Fatura OCR ve Excel/CSV Export (Gelişmiş Parse)")

uploaded_files = st.file_uploader("Faturaları seçin", type=["jpg","jpeg","png","pdf"], accept_multiple_files=True)

if uploaded_files:
    all_data = []
    for file in uploaded_files:
        st.info(f"{file.name} işleniyor...")
        files = {"file": file}
        payload = {"apikey": API_KEY, "language": "tur", "isOverlayRequired": False}
        response = requests.post(API_URL, files=files, data=payload)

        if response.status_code == 200:
            result = response.json()
            parsed_text = result.get("ParsedResults", [{}])[0].get("ParsedText","")
            invoice_data = extract_invoice_fields(parsed_text)
            all_data.append(invoice_data)
        else:
            st.error(f"{file.name} OCR hatası: {response.status_code}")

    if all_data:
        df = pd.DataFrame(all_data)
        st.subheader("📊 Tespit Edilen Faturalar")
        st.dataframe(df)
        csv_bytes = to_csv_bytes(df)
        st.download_button(
            label="📥 Tüm Faturaları Excel/CSV Olarak İndir",
            data=csv_bytes,
            file_name="faturalar_ocr.csv",
            mime="text/csv"
        )
