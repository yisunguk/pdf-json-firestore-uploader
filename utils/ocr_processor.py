import os, json
import cv2
import numpy as np
from pdf2image import convert_from_path
from paddleocr import PaddleOCR
from PIL import Image
import fitz  # PyMuPDF
import pdfplumber  # 추가

# PaddleOCR 초기화
ocr_model = PaddleOCR(use_angle_cls=True, lang='korean')


def pdf_to_images(pdf_path, image_dir, dpi=200):
    os.makedirs(image_dir, exist_ok=True)
    images = convert_from_path(pdf_path, dpi=dpi)
    image_paths = []
    for idx, img in enumerate(images):
        path = os.path.join(image_dir, f'page_{idx+1}.jpg')
        img.save(path, 'JPEG')
        image_paths.append(path)
    return image_paths


def to_builtin(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, bytes):
        return obj.decode('utf-8', errors='ignore')
    if isinstance(obj, (list, tuple)):
        return [to_builtin(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_builtin(v) for k, v in obj.items()}
    return obj


def run_ocr(image_paths, output_path):
    result = {}

    for path in image_paths:
        try:
            ocr_result = ocr_model.ocr(path)
            cleaned_result = []

            for line in ocr_result[0]:
                try:
                    box, (text, confidence) = line[:2]  # 첫 2개 요소만 추출
                    if isinstance(box, np.ndarray):
                        box = box.tolist()
                    cleaned_result.append({
                        'box': box,
                        'text': text,
                        'confidence': float(confidence)
                    })
                except Exception as e:
                    print(f"[⚠️ 경고] line unpack 실패 - {line}: {str(e)}")
                    continue

            result[os.path.basename(path)] = cleaned_result
            print(f"[✅ OCR 성공] {path}")

        except Exception as e:
            print(f"[에러] OCR 실패 - {path}: {str(e)}")
            result[os.path.basename(path)] = {'error': str(e)}

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return output_path


def hybrid_extract(pdf_path, image_dir, output_json_path, min_chars=20, dpi=200):
    """
    PyMuPDF 기반 하이브리드 텍스트 + OCR 추출
    """
    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    result = {
        "pdf_path": pdf_path,
        "total_pages": total_pages,
        "min_chars_threshold": min_chars,
        "dpi": dpi,
        "pages": {},
        "ocr_pages_count": 0
    }

    for page_num in range(total_pages):
        page = doc.load_page(page_num)
        text = page.get_text()
        char_count = len(text.strip())

        page_info = {
            "page_number": page_num + 1,
            "char_count": char_count,
            "extraction_method": "text" if char_count >= min_chars else "ocr",
            "text": text if char_count >= min_chars else ""
        }

        if char_count < min_chars:
            result["ocr_pages_count"] += 1
            os.makedirs(image_dir, exist_ok=True)
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72))
            img_path = os.path.join(image_dir, f"page_{page_num + 1}.jpg")
            pix.save(img_path)

            try:
                ocr_result = ocr_model.ocr(img_path)
                ocr_text = ""
                ocr_data = []

                if ocr_result and ocr_result[0]:
                    for line in ocr_result[0]:
                        box, (text, confidence) = line
                        ocr_text += text + " "
                        ocr_data.append({
                            'box': to_builtin(box),
                            'text': text,
                            'confidence': float(confidence)
                        })

                page_info["text"] = ocr_text.strip()
                page_info["ocr_data"] = ocr_data
                page_info["image_path"] = img_path

            except Exception as e:
                page_info["error"] = str(e)
                print(f"[에러] OCR 실패 - 페이지 {page_num + 1}: {str(e)}")

        result["pages"][f"page_{page_num + 1}"] = page_info

    doc.close()

    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return output_json_path, result["ocr_pages_count"]


def pdfplumber_extract(pdf_path, image_dir, output_json_path, min_chars=20, dpi=200):
    """
    pdfplumber 기반 하이브리드 텍스트 + OCR 추출
    """
    os.makedirs(image_dir, exist_ok=True)
    doc = pdfplumber.open(pdf_path)
    total_pages = len(doc.pages)

    result = {
        "pdf_path": pdf_path,
        "total_pages": total_pages,
        "min_chars_threshold": min_chars,
        "dpi": dpi,
        "pages": {},
        "ocr_pages_count": 0
    }

    for i, page in enumerate(doc.pages):
        text = page.extract_text() or ""
        char_count = len(text.strip())

        page_info = {
            "page_number": i + 1,
            "char_count": char_count,
            "extraction_method": "text" if char_count >= min_chars else "ocr",
            "text": text if char_count >= min_chars else ""
        }

        if char_count < min_chars:
            result["ocr_pages_count"] += 1
            img_path = os.path.join(image_dir, f"page_{i+1}.jpg")
            page_image = page.to_image(resolution=dpi).original
            page_image = page_image.convert("RGB")
            page_image.save(img_path, format="JPEG")

            try:
                ocr_result = ocr_model.ocr(img_path)
                ocr_text = ""
                ocr_data = []

                if ocr_result and ocr_result[0]:
                    for line in ocr_result[0]:
                        box, (text_part, confidence) = line
                        ocr_text += text_part + " "
                        ocr_data.append({
                            'box': to_builtin(box),
                            'text': text_part,
                            'confidence': float(confidence)
                        })

                page_info["text"] = ocr_text.strip()
                page_info["ocr_data"] = ocr_data
                page_info["image_path"] = img_path

            except Exception as e:
                page_info["error"] = str(e)

        result["pages"][f"page_{i+1}"] = page_info

    doc.close()

    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return output_json_path, result["ocr_pages_count"]
