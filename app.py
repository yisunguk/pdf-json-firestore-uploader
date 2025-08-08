import os
import json
from datetime import datetime
import streamlit as st
import fitz  # PyMuPDF
import pdfplumber

# Firestore
import firebase_admin
from firebase_admin import credentials, firestore

# Azure OpenAI
from openai import AzureOpenAI

# --- 기본 설정 ---
st.set_page_config(page_title="PDF 텍스트 추출기", layout="wide")
st.title("📄 PDF 텍스트 추출기 (페이지별 JSON 변환 + Firestore 저장)")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- 세션 초기화 ---
for k, v in {"timestamp": None, "json_path": None}.items():
    st.session_state.setdefault(k, v)

# --- Firebase 초기화 ---
if "firebase_app" not in st.session_state:
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate({
                k: st.secrets["firebase"][k].replace("\\n", "\n") if k == "private_key" else st.secrets["firebase"][k]
                for k in st.secrets["firebase"]
            })
            firebase_admin.initialize_app(cred)
        st.session_state.firebase_app = True
    except Exception as e:
        st.error(f"Firebase 초기화 실패: {e}")

db = firestore.client() if firebase_admin._apps else None

# --- Azure OpenAI 초기화 ---
try:
    openai_client = AzureOpenAI(
        api_key=st.secrets["azure_openai"]["api_key"],
        api_version=st.secrets["azure_openai"]["api_version"],
        azure_endpoint=st.secrets["azure_openai"]["endpoint"]
    )
    openai_deployment = st.secrets["azure_openai"]["deployment"]
except Exception as e:
    st.error(f"OpenAI 초기화 실패: {e}")
    openai_client, openai_deployment = None, None

# --- 파일 업로드 ---
uploaded_file = st.file_uploader("PDF 파일을 업로드하세요", type=["pdf"])
extract_method = st.selectbox("텍스트 추출 방식 선택", ["PyMuPDF", "pdfplumber"])

# --- 텍스트 추출 ---
if uploaded_file:
    st.session_state.timestamp = st.session_state.timestamp or datetime.now().strftime("%Y%m%d%H%M%S")
    filename_base = os.path.splitext(uploaded_file.name)[0]
    temp_pdf = os.path.join(BASE_DIR, f"temp_{st.session_state.timestamp}.pdf")
    json_path = os.path.join(BASE_DIR, "output", f"{filename_base}_text_result_{st.session_state.timestamp}.json")
    os.makedirs(os.path.dirname(json_path), exist_ok=True)

    with open(temp_pdf, "wb") as f:
        f.write(uploaded_file.getbuffer())

    if st.button("🚀 텍스트 추출 실행"):
        try:
            result = {"pdf_path": temp_pdf, "pages": []}
            st.info("텍스트 추출 중...")
            if extract_method == "PyMuPDF":
                with fitz.open(temp_pdf) as doc:
                    result["pages"] = [
                        {"page_number": i+1, "char_count": len(t := page.get_text().strip()), "text": t}
                        for i, page in enumerate(doc)
                    ]
            else:
                with pdfplumber.open(temp_pdf) as doc:
                    result["pages"] = [
                        {"page_number": i+1, "char_count": len(t := (page.extract_text() or "")), "text": t}
                        for i, page in enumerate(doc.pages)
                    ]

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            st.success("✅ 완료! 결과 JSON 생성됨.")
            with open(json_path, "rb") as f:
                st.download_button("📥 결과 JSON 다운로드", f, file_name=os.path.basename(json_path), mime="application/json")
            st.session_state.json_path = json_path
        except Exception as e:
            st.error(f"❌ 추출 실패: {e}")

# --- Firestore 저장 ---
if st.session_state.json_path and db:
    st.info("💾 JSON을 Firestore에 저장할 수 있습니다.")
    if st.button("📤 Firestore에 저장"):
        try:
            with open(st.session_state.json_path, encoding="utf-8") as f:
                json_data = json.load(f)
            doc_name = f"{filename_base}_{st.session_state.timestamp}"
            db.collection("pdf_texts").document(doc_name).set(json_data)
            st.success(f"✅ Firestore 저장 완료: {doc_name}")
        except Exception as e:
            st.error(f"Firestore 저장 실패: {e}")

# --- Firestore 문서 목록 표시 ---
if db:
    st.markdown("---")
    st.subheader("📂 Firestore 문서 테이블 (문서 삭제 / 저장 / AI 분석)")
    try:
        docs = db.collection("pdf_texts").stream()
        doc_list = [(i+1, doc.id, doc.to_dict()) for i, doc in enumerate(docs)]

        if doc_list:
            headers = ["선택", "번호", "글자수", "문서제목", "미리보기", "AI 분석", "삭제", "저장"]
            for col, head in zip(st.columns(len(headers)), headers):
                col.markdown(f"<b>{head}</b>", unsafe_allow_html=True)

            for i, doc_id, data in doc_list:
                total_chars = sum(p.get("char_count", 0) for p in data.get("pages", []))
                cols = st.columns(8)
                cols[0].checkbox("", key=f"select_{doc_id}")
                cols[1].markdown(f"<span style='color:limegreen; font-weight:bold'>{i}</span>", unsafe_allow_html=True)
                cols[2].markdown(f"<span style='color:teal'>{total_chars}</span>", unsafe_allow_html=True)
                cols[3].markdown(doc_id)

                with cols[4]:
                    with st.expander("📄 문서 미리보기"):
                        for page in data.get("pages", []):
                            st.markdown(f"**📄 Page {page['page_number']}**")
                            st.code(page['text'][:1000] + ("..." if len(page['text']) > 1000 else ""))

                with cols[5]:
                    if st.button("🧠 AI 분석", key=f"analyze_btn_{doc_id}"):
                        st.session_state[f"popup_{doc_id}"] = True

                with cols[6]:
                    if st.button("🗑 삭제", key=f"delete_{doc_id}"):
                        db.collection("pdf_texts").document(doc_id).delete()
                        st.success(f"❌ `{doc_id}` 삭제 완료")
                        st.experimental_rerun()

                with cols[7]:
                    st.download_button("💾 저장", json.dumps(data, ensure_ascii=False, indent=2),
                        file_name=f"{doc_id}.json", mime="application/json", key=f"download_{doc_id}")

                if st.session_state.get(f"popup_{doc_id}"):
                    with st.expander("📌 AI 분석 결과 보기", expanded=True):
                        prompt = st.text_area("✍️ 프롬프트 입력", key=f"prompt_{doc_id}")
                        if st.button("🚀 분석 실행", key=f"run_analysis_{doc_id}") and openai_client:
                            try:
                                full_text = "\n".join(p["text"] for p in data.get("pages", []))[:8000]
                                response = openai_client.chat.completions.create(
                                    messages=[
                                        {"role": "system", "content": "You are an assistant that summarizes PDF contents."},
                                        {"role": "user", "content": f"{prompt}\n---\n{full_text}"}
                                    ],
                                    model=openai_deployment,
                                    max_tokens=1000,
                                    temperature=0.7,
                                    top_p=1.0
                                )
                                st.success("✅ 분석 완료")
                                st.markdown(response.choices[0].message.content)
                            except Exception as e:
                                st.error(f"AI 분석 실패: {e}")
        else:
            st.info("Firestore에 저장된 문서가 없습니다.")
    except Exception as e:
        st.error(f"문서 로딩 실패: {e}")
