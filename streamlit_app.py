import streamlit as st
import requests
import json

# OCR.space API key
API_KEY = "K84160666388957"
API_URL = "https://api.ocr.space/parse/image"

st.set_page_config(page_title="Fatura OCR", layout="centered")
st.title("📄 Fatura OCR Arayüzü")

uploaded_file = st.file_uploader("Fatura yükle (JPG/PNG/PDF)", type=["jpg", "jpeg", "png", "pdf"])

if uploaded_file is not None:
    # OCR.space API çağrısı
    with st.spinner("OCR işleniyor..."):
        files = {"file": uploaded_file.getvalue()}
        payload = {
            "apikey": API_KEY,
            "language": "tur",  # Türkçe destek
            "isOverlayRequired": False
        }

        response = requests.post(API_URL, files={"file": uploaded_file}, data=payload)
        result = response.json()

    st.success("OCR işlemi tamamlandı ✅")

    # Orijinal JSON göster
    st.subheader("Ham JSON")
    st.json(result)

    # ParsedText alanını al
    parsed_text = result["ParsedResults"][0]["ParsedText"] if "ParsedResults" in result else ""
    st.subheader("Çıkarılan Metin")
    st.text_area("OCR Sonucu", parsed_text, height=300)

    # İndirilebilir TXT çıktısı
    st.download_button(
        label="📥 OCR Metnini İndir (TXT)",
        data=parsed_text,
        file_name="ocr_output.txt",
        mime="text/plain"
    )
