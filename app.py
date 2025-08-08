import os
import json
from datetime import datetime
import streamlit as st
import fitz  # PyMuPDF
import pdfplumber

# Firestore 연동
import firebase_admin
from firebase_admin import credentials, firestore

# --- 기본 설정 ---
st.set_page_config(page_title="PDF 텍스트 추출기", layout="centered")
st.title("\ud83d\udcc4 PDF \ud14d\uc2a4\ud2b8 \ucc3e\uae30 (\ud398\uc774\uc9c0\ubcc4 JSON \ubcc0\ud654 + Firestore \uc800\uc7a5)")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- 세션 초기화 ---
for k, v in {"timestamp": None, "json_path": None}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# --- Firestore 초기화 (Streamlit Secrets 기반) ---
if "firebase_app" not in st.session_state:
    try:
        st.info("Firebase \ucd08\uae30\ud654 \uc2dc\ub3c4...")
        firebase_config = {
            k: st.secrets["firebase"][k].replace('\\n', '\n') if k == "private_key" else st.secrets["firebase"][k]
            for k in st.secrets["firebase"]
        }

        if not firebase_admin._apps:
            cred = credentials.Certificate(firebase_config)
            firebase_admin.initialize_app(cred)

        db = firestore.client()
        st.session_state.firebase_app = True

    except Exception as e:
        st.error(f"\u274c Firebase \ucd08\uae30\ud654 \uc2e4\ud328: {e}")
        db = None
else:
    db = firestore.client()

# --- PDF \ud30c\uc77c \uc5c5\ub85c\ub4dc & \ucc3e\uae30 ---
uploaded_file = st.file_uploader("PDF \ud30c\uc77c\uc744 \uc5c5\ub85c\ub4dc\ud558\uc138\uc694", type=["pdf"])
extract_method = st.selectbox("\ud14d\uc2a4\ud2b8 \ucc3e\uae30 \ubc29\uc2dd \uc120\ud0dd", ["PyMuPDF", "pdfplumber"])

if uploaded_file:
    if not st.session_state.timestamp:
        st.session_state.timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    filename_base = os.path.splitext(uploaded_file.name)[0]
    temp_pdf = os.path.join(BASE_DIR, f"temp_{st.session_state.timestamp}.pdf")
    json_path = os.path.join(BASE_DIR, "output", "json", f"{filename_base}_text_result_{st.session_state.timestamp}.json")
    os.makedirs(os.path.dirname(json_path), exist_ok=True)

    with open(temp_pdf, "wb") as f:
        f.write(uploaded_file.getbuffer())

    if st.button("\ud83d\ude80 \ud14d\uc2a4\ud2b8 \ucc3e\uae30 \uc2e4\ud589"):
        try:
            st.info("\ud14d\uc2a4\ud2b8 \ucc3e\uae30 \uc911...")
            result = {"pdf_path": temp_pdf, "pages": []}

            if extract_method == "PyMuPDF":
                with fitz.open(temp_pdf) as doc:
                    for i, page in enumerate(doc):
                        text = page.get_text().strip()
                        result["pages"].append({
                            "page_number": i + 1,
                            "char_count": len(text),
                            "text": text
                        })
            else:
                with pdfplumber.open(temp_pdf) as doc:
                    for i, page in enumerate(doc.pages):
                        text = page.extract_text() or ""
                        result["pages"].append({
                            "page_number": i + 1,
                            "char_count": len(text),
                            "text": text
                        })

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            st.success("\u2705 \uac00\ub2a5! JSON \uacb0\uacfc \uc0dd\uc131\ud568.")
            with open(json_path, "rb") as f:
                st.download_button("\ud83d\udcc5 JSON \ub2e4\uc6b4\ub85c\ub4dc", f, file_name=os.path.basename(json_path), mime="application/json")

            st.session_state.json_path = json_path

        except Exception as e:
            st.error(f"\u274c \uc2e4\ud328: {e}")

# --- Firestore\uc5d0 JSON \uc800\uc7a5 ---
if st.session_state.json_path and db:
    st.info("\ud83d\udcc2 Firestore\uc5d0 \uc800\uc7a5\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4.")
    if st.button("\ud83d\udcc4 Firestore\uc5d0 \uc800\uc7a5"):
        try:
            with open(st.session_state.json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)

            doc_name = f"{filename_base}_{st.session_state.timestamp}"
            db.collection("pdf_texts").document(doc_name).set(json_data)
            st.success(f"\u2705 Firestore \uc800\uc7a5 \uc644\ub8cc: {doc_name}")

        except Exception as e:
            st.error(f"Firestore \uc800\uc7a5 \uc2e4\ud328: {e}")

# --- Firestore\uc758 \ubb38\uc11c\ub4f1 \ucd9c\ub825/\uc0ad\uc81c/\uc800\uc7a5 ---
import pandas as pd

st.markdown("---")
st.subheader("\ud83d\udcc2 Firestore \ubb38\uc11c \ud14c\uc774\ube14 (\ubb38\uc11c \uc0ad\uc81c / \uc800\uc7a5 \ud568\uaed8)")

try:
    docs = db.collection("pdf_texts").stream()
    doc_list = []

    for i, doc in enumerate(docs, start=1):
        doc_id = doc.id
        data = doc.to_dict()
        total_chars = sum(p.get("char_count", 0) for p in data.get("pages", []))
        first_text = data["pages"][0]["text"] if data.get("pages") else ""
        preview = first_text[:100] + "..." if len(first_text) > 100 else first_text

        doc_list.append({
            "index": i,
            "doc_id": doc_id,
            "char_count": total_chars,
            "preview": preview,
            "full_data": data
        })

    if doc_list:
        for doc in doc_list:
            col1, col2, col3, col4, col5, col6, col7 = st.columns([0.5, 0.5, 1, 2, 3, 1, 1])

            with col1:
                st.checkbox("", key=f"chk_{doc['doc_id']}")
            with col2:
                st.write(doc["index"])
            with col3:
                st.write(doc["char_count"])
            with col4:
                st.write(doc["doc_id"])
            with col5:
                with st.expander("\ud83d\udcc4 \ubb38\uc11c \ubbf8\ub9ac\ubcf4\uae30"):
                    for page in doc["full_data"].get("pages", []):
                        st.markdown(f"**\ud398\uc774\uc9c0 {page['page_number']}**")
                        st.write(page["text"])
            with col6:
                if st.button("\ud83d\uddd1 \uc0ad\uc81c", key=f"del_{doc['doc_id']}"):
                    db.collection("pdf_texts").document(doc["doc_id"]).delete()
                    st.warning(f"\u274c `{doc['doc_id']}` \uc0ad\uc81c \uc644\ub8cc (\uc0c8\ub85c\uace0\uce68 \ud544\uc694)")
            with col7:
                json_data = json.dumps(doc["full_data"], ensure_ascii=False, indent=2)
                st.download_button("\ud83d\udcc4 \uc800\uc7a5", data=json_data, file_name=f"{doc['doc_id']}.json", mime="application/json", key=f"save_{doc['doc_id']}")

    else:
        st.info("Firestore\uc5d0 \uc800\uc7a5\ub41c \ubb38\uc11c\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.")

except Exception as e:
    st.error(f"\ubb38\uc11c \ub85c\ub529 \uc2e4\ud328: {e}")