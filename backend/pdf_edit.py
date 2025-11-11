import os
import tempfile
import time
from typing import List, Dict, Any, Tuple

from pypdf import PdfReader, PdfWriter
def _atomic_replace(src: str, dst: str, attempts: int = 10, delay: float = 0.05):
    """Replace dst with src, retrying briefly on Windows PermissionError.
    Helps when the file is momentarily locked by antivirus or lingering handles.
    """
    last_err = None
    for _ in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            last_err = e
            time.sleep(delay)
    if last_err:
        raise last_err
from pypdf.generic import DictionaryObject, NameObject, ArrayObject, FloatObject, NumberObject


def _annotation_from_quads(quads: List[float], color: List[float]):
    # Build a highlight annotation dictionary for given quadpoints
    # QuadPoints is a flat list per quad: [x1,y1,x2,y2,x3,y3,x4,y4]
    # Compute bounding box rect from points
    xs = quads[0::2]
    ys = quads[1::2]
    rect = [min(xs), min(ys), max(xs), max(ys)]

    annot = DictionaryObject()
    annot.update({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Highlight"),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in rect]),
        NameObject("/QuadPoints"): ArrayObject([FloatObject(v) for v in quads]),
        NameObject("/C"): ArrayObject([FloatObject(color[0]), FloatObject(color[1]), FloatObject(color[2])]),
        NameObject("/F"): NumberObject(4),  # print the annotation, no zoom/move flags
    })
    return annot


def add_highlights_to_pdf(pdf_path: str, highlights: List[Dict[str, Any]]):
    """Apply highlight annotations to the provided PDF file in-place.

    highlights: list of items with keys:
      - page: 1-based page index
      - color: [r,g,b] floats 0..1
      - quads: list of quad arrays, each [x1,y1,x2,y2,x3,y3,x4,y4] in PDF user space points
    """
    pdf_path = os.path.abspath(pdf_path)
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(pdf_path)
    # Open explicitly so handle is closed before replacing on Windows
    with open(pdf_path, "rb") as rf:
        reader = PdfReader(rf)
        writer = PdfWriter()
        # Clone entire document to preserve outlines, metadata, names, etc.
        if hasattr(writer, "clone_document_from_reader"):
            writer.clone_document_from_reader(reader)
        else:
            # Fallback: copy pages (may lose outlines on older pypdf)
            for i in range(len(reader.pages)):
                writer.add_page(reader.pages[i])

    # Apply annotations
    for item in highlights:
        page_index = int(item.get("page", 0)) - 1
        if page_index < 0 or page_index >= len(writer.pages):
            continue
        color = item.get("color", [1, 1, 0])  # default yellow
        quads_list = item.get("quads", [])
        for quad in quads_list:
            if not isinstance(quad, (list, tuple)) or len(quad) != 8:
                continue
            annot = _annotation_from_quads(list(map(float, quad)), list(map(float, color)))
            writer.add_annotation(page_number=page_index, annotation=annot)

    # Write to a temp file then atomically replace original
    dirn = os.path.dirname(pdf_path)
    fd, tmp = tempfile.mkstemp(prefix="annot-", suffix=".pdf", dir=dirn)
    try:
        os.close(fd)
        with open(tmp, "wb") as f:
            writer.write(f)
        _atomic_replace(tmp, pdf_path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _quad_to_rect(quad: List[float]) -> Tuple[float, float, float, float]:
    xs = quad[0::2]
    ys = quad[1::2]
    return (min(xs), min(ys), max(xs), max(ys))


def _rects_overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float], tol: float = 0.5) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    # Expand a bit by tol to be forgiving
    ax1 -= tol; ay1 -= tol; ax2 += tol; ay2 += tol
    bx1 -= tol; by1 -= tol; bx2 += tol; by2 += tol
    return not (ax2 < bx1 or bx2 < ax1 or ay2 < by1 or by2 < ay1)


def remove_highlights_from_pdf(pdf_path: str, targets: List[Dict[str, Any]]) -> Dict[str, int]:
    """Remove (fully or partially) highlight annotations overlapping provided quads.

    targets: list of { page: 1-based index, quads: [[...8 numbers...], ...] }
    Behavior:
      * If ALL quads of an annotation overlap selection quads => remove entire annotation.
      * Else remove only overlapping quads and keep remaining.
    Returns dict with counts: {removed_annots, removed_quads}
    """
    pdf_path = os.path.abspath(pdf_path)
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(pdf_path)
    with open(pdf_path, "rb") as rf:
        reader = PdfReader(rf)
        writer = PdfWriter()
        if hasattr(writer, "clone_document_from_reader"):
            writer.clone_document_from_reader(reader)
        else:
            for i in range(len(reader.pages)):
                writer.add_page(reader.pages[i])

    removed_annots = 0
    removed_quads = 0
    # Group target rects by page index
    by_page: Dict[int, List[Tuple[float, float, float, float]]] = {}
    for t in targets:
        p = int(t.get("page", 0)) - 1
        if p < 0 or p >= len(writer.pages):
            continue
        rects = by_page.setdefault(p, [])
        for q in t.get("quads", []) or []:
            if isinstance(q, (list, tuple)) and len(q) == 8:
                rects.append(_quad_to_rect([float(x) for x in q]))

    for page_index, rects in by_page.items():
        page = writer.pages[page_index]
        annots = page.get(NameObject("/Annots"))
        if not annots:
            continue
        try:
            ann_array = annots.get_object() if hasattr(annots, 'get_object') else annots
        except Exception:
            ann_array = annots
        if not isinstance(ann_array, ArrayObject):
            continue
        keep = ArrayObject()
        for ref in ann_array:
            try:
                annot = ref.get_object() if hasattr(ref, 'get_object') else ref
            except Exception:
                annot = ref
            subtype = annot.get(NameObject("/Subtype")) if isinstance(annot, DictionaryObject) else None
            if subtype == NameObject("/Highlight"):
                qps = annot.get(NameObject("/QuadPoints")) if isinstance(annot, DictionaryObject) else None
                if isinstance(qps, ArrayObject) and len(qps) >= 8 and len(qps) % 8 == 0:
                    overlapping_indices = []
                    total_quads = len(qps) // 8
                    for i in range(0, len(qps), 8):
                        quad = [float(qps[i + j]) for j in range(8)]
                        ar = _quad_to_rect(quad)
                        if any(_rects_overlap(ar, tr) for tr in rects):
                            overlapping_indices.append(i // 8)
                    if overlapping_indices:
                        if len(overlapping_indices) == total_quads:
                            # Remove entire annotation
                            removed_annots += 1
                            removed_quads += total_quads
                            continue
                        # Partial removal: rebuild quadpoints array without overlapped quads
                        new_qps = []
                        for i in range(0, len(qps), 8):
                            idx = i // 8
                            if idx in overlapping_indices:
                                removed_quads += 1
                                continue
                            for j in range(8):
                                new_qps.append(FloatObject(float(qps[i + j])))
                        annot[NameObject("/QuadPoints")] = ArrayObject(new_qps)
                        # Recompute /Rect from remaining quads
                        xs = []
                        ys = []
                        for i in range(0, len(new_qps), 2):
                            # positions stored as x,y pairs consecutively
                            if (i // 2) % 4 in (0, 1, 2, 3):
                                xs.append(float(new_qps[i]))
                                ys.append(float(new_qps[i + 1]))
                        if xs and ys:
                            annot[NameObject("/Rect")] = ArrayObject([
                                FloatObject(min(xs)), FloatObject(min(ys)),
                                FloatObject(max(xs)), FloatObject(max(ys))
                            ])
                else:
                    # Fallback: compare /Rect if no QuadPoints, remove entirely if overlap
                    rect = annot.get(NameObject("/Rect")) if isinstance(annot, DictionaryObject) else None
                    if isinstance(rect, ArrayObject) and len(rect) == 4:
                        ar = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
                        if any(_rects_overlap(ar, tr) for tr in rects):
                            removed_annots += 1
                            # Treat as single quad
                            removed_quads += 1
                            continue
            keep.append(ref)
        # Write back filtered array
        if len(keep) > 0:
            page[NameObject("/Annots")] = keep
        else:
            # remove annots key if empty
            if NameObject("/Annots") in page:
                del page[NameObject("/Annots")]

    dirn = os.path.dirname(pdf_path)
    fd, tmp = tempfile.mkstemp(prefix="annot-del-", suffix=".pdf", dir=dirn)
    try:
        os.close(fd)
        with open(tmp, "wb") as f:
            writer.write(f)
        _atomic_replace(tmp, pdf_path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
    return {"removed_annots": removed_annots, "removed_quads": removed_quads}


def undo_last_highlight(pdf_path: str) -> int:
    """Undo last added highlight annotation (removes the most recently appended highlight).
    Returns number of annotations removed (0 or 1)."""
    pdf_path = os.path.abspath(pdf_path)
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(pdf_path)
    with open(pdf_path, "rb") as rf:
        reader = PdfReader(rf)
        writer = PdfWriter()
        if hasattr(writer, "clone_document_from_reader"):
            writer.clone_document_from_reader(reader)
        else:
            for i in range(len(reader.pages)):
                writer.add_page(reader.pages[i])
    # Traverse pages in reverse to find last highlight
    found = False
    for page_index in range(len(writer.pages)-1, -1, -1):
        page = writer.pages[page_index]
        annots = page.get(NameObject("/Annots"))
        if not annots:
            continue
        try:
            ann_array = annots.get_object() if hasattr(annots, 'get_object') else annots
        except Exception:
            ann_array = annots
        if not isinstance(ann_array, ArrayObject):
            continue
        # Iterate reversed
        for idx in range(len(ann_array)-1, -1, -1):
            ref = ann_array[idx]
            try:
                annot = ref.get_object() if hasattr(ref, 'get_object') else ref
            except Exception:
                annot = ref
            subtype = annot.get(NameObject("/Subtype")) if isinstance(annot, DictionaryObject) else None
            if subtype == NameObject("/Highlight"):
                # Remove this reference
                new_arr = ArrayObject([r for i, r in enumerate(ann_array) if i != idx])
                if len(new_arr) > 0:
                    page[NameObject("/Annots")] = new_arr
                else:
                    if NameObject("/Annots") in page:
                        del page[NameObject("/Annots")]
                found = True
                break
        if found:
            break
    if not found:
        return 0
    dirn = os.path.dirname(pdf_path)
    fd, tmp = tempfile.mkstemp(prefix="annot-undo-", suffix=".pdf", dir=dirn)
    try:
        os.close(fd)
        with open(tmp, "wb") as f:
            writer.write(f)
        _atomic_replace(tmp, pdf_path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
    return 1
