"""캡처한 page_NNN.png 들을 번호 순서대로 묶어 PDF 생성.

img2pdf(무손실, 권장) 가 있으면 사용하고, 없으면 Pillow 로 폴백한다.
"""
from __future__ import annotations

import os


def _sorted_pages(save_dir: str) -> list[str]:
    files = []
    for name in os.listdir(save_dir):
        if name.startswith("page_") and name.lower().endswith(".png"):
            num = name[len("page_"):-len(".png")]
            if num.isdigit():
                files.append((int(num), os.path.join(save_dir, name)))
    files.sort(key=lambda x: x[0])
    return [p for _, p in files]


def build_pdf(save_dir: str, out_path: str) -> tuple[bool, str]:
    """save_dir 안의 page_NNN.png 들을 out_path PDF 로 병합.

    반환: (성공여부, 메시지)
    """
    pages = _sorted_pages(save_dir)
    if not pages:
        return False, "병합할 page_*.png 파일이 없습니다."

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    # 1) img2pdf 우선 (무손실, 원본 해상도 유지)
    try:
        import img2pdf  # type: ignore

        with open(out_path, "wb") as f:
            f.write(img2pdf.convert(pages))
        return True, f"{len(pages)}장 → {out_path} (img2pdf)"
    except ImportError:
        pass
    except Exception as exc:
        return False, f"img2pdf 변환 실패: {exc}"

    # 2) Pillow 폴백
    try:
        from PIL import Image  # type: ignore

        imgs = [Image.open(p).convert("RGB") for p in pages]
        first, rest = imgs[0], imgs[1:]
        first.save(out_path, save_all=True, append_images=rest)
        return True, f"{len(pages)}장 → {out_path} (Pillow)"
    except ImportError:
        return False, (
            "PDF 생성을 위해 img2pdf 또는 Pillow 가 필요합니다.\n"
            "pip install img2pdf"
        )
    except Exception as exc:
        return False, f"PDF 생성 실패: {exc}"
