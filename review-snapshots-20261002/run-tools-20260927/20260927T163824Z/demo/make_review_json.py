"""MF-DEMO-E2E PROOF_GATE — build demo/demo_review.json from measurements on disk.

Read-only on RUN/proof/**; writes only RUN/demo/**. Every hash here is read from the
file at call time. Run:  cd <RUN> && python.exe -B demo/make_review_json.py
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

RUN = Path(__file__).resolve().parents[1]
F = "demo/frames"


def sha(p: str) -> str:
    return hashlib.sha256((RUN / p).read_bytes()).hexdigest()


def entry(p: str, desc: str, verdict: str) -> dict:
    return {
        "file": p,
        "sha256": sha(p),
        "bytes": (RUN / p).stat().st_size,
        "looked_with": "native vision",
        "description": desc,
        "verdict": verdict,
    }


frames = [
    entry(f"{F}/asm_f000.png", "BOOK f0: phong khach; nam toc xam-bac ngoi ghe den ao khoac xam, mieng mo (dang noi), hai tay giu sach XANH nhan vang (KHEP, bia huong ra); nu toc nau vay hong dung sau phai; phai: ban bi-a xanh + 2 nguoi quay lung (nam toc den ao trang vien do) + khoi TIM bi ria phai cat; khong watermark", "PASS"),
    entry(f"{F}/asm_f060.png", "BOOK f60: nhu f0; mieng khep/cuoi, mat nhin sach; sach van KHEP; nu giu nguyen; khong watermark", "PASS"),
    entry(f"{F}/asm_f119.png", "BOOK f119: nhu f0/f60; sach KHEP; khoi tim ria phai to hon chut; khong watermark", "PASS"),
    entry(f"{F}/asm_f120.png", "TURN f0 (sau cut): nen nau caramel; trang giay trang nghieng + bia XANH trai; tieu de CTY TNHH Bao Nam Training; dong Nguoi dai dien / So DKKD / Dia chi / So Dien Thoai 0230232****36 / (Ky Ten); chu SACH; khong watermark", "PASS"),
    entry(f"{F}/asm_f180.png", "TURN f60: LOI - chu NHAN DOI: CTY TNHH Bao Nam Training xuat hien 2 lan lech (ban mo lon + ban ro), cac dong cung doi; them mep trang trang lech phai (2 lop trang); khong watermark", "FINDING P2"),
    entry(f"{F}/asm_f239.png", "TURN f119: trang chung nhan SACH (mot ban chu), nghieng nhe, mep toi goc duoi-phai bat dau chuyen canh; khong watermark", "PASS"),
    entry(f"{F}/asm_f240.png", "OCC_SEG1 f0: trang trang + bia xanh trai; tieu de DO CTY TVTT & PTTM; 4 gach dau dong (Da ho tro gioi thieu du an / Da ket noi khach hang tiem nang / Da tham gia to chuc buoi gap NDT / Da ban giao khach quan tam); ban tay nau + but den goc phai duoi cham trang; khong watermark", "PASS"),
    entry(f"{F}/asm_f300.png", "OCC_SEG1 f60: cung trang; tay/but DICH XUONG duoi giua; khong watermark", "PASS"),
    entry(f"{F}/asm_f341.png", "OCC_SEG1 f101: cung trang; but sat mep duoi, them 2 net toc do; khong watermark", "PASS"),
    entry(f"{F}/asm_f342.png", "OCC_SEG2 f0 (sau cut noi bo): nam tre toc bac-xam undercut, khuyen tai, hoodie nau dam + ao xam + thun den; ngoi ban, hai tay MO cuon sach XANH hai trang trang; ly nhua nap + ong hut XANH + nuoc kem; nen panel trang giua, cua so xanh 2 ben co vet phan chieu cheo, san teal; khong watermark", "PASS"),
    entry(f"{F}/asm_f350.png", "OCC_SEG2 f8: gan nhu y het f342 (diff 2.696/255); dau nghieng nhe; sach mo giu; ly giu; khong watermark", "PASS"),
    entry(f"{F}/asm_f359.png", "OCC_SEG2 f17 (frame cuoi): gan nhu giu nguyen (diff f342->f359 = 2.785); ket clip; khong watermark", "PASS"),
    entry(f"{F}/source/book_src_f000.png", "SOURCE BOOK f0: nguoi toc xam + nu vay hong + ban bi-a + 2 nguoi quay lung + khoi tim ria phai; sach KHEP; CO watermark Lanh Vcl + nut play do goc duoi-trai", "SOURCE-REF"),
    entry(f"{F}/source/book_src_f072.png", "SOURCE BOOK f72: sach van KHEP theo mat doc (khong thay hai trang mo); CO watermark", "SOURCE-REF"),
    entry(f"{F}/source/book_src_f080.png", "SOURCE BOOK f80: sach van KHEP; CO watermark", "SOURCE-REF"),
    entry(f"{F}/source/turn_src_f000.png", "SOURCE TURN f0: trang chung nhan CTY TNHH Bao Nam Training, cung bo cuc; CO watermark Lanh Vcl", "SOURCE-REF"),
    entry(f"{F}/source/occ_src_f102.png", "SOURCE OCC f102 (dau SEG2): nam toc xam ngoi ban, giu sach XANH (KHEP/nghieng), ly trong + ong hut CAM; CO watermark Lanh Vcl", "SOURCE-REF"),
    entry(f"{F}/source/occ_src_f119.png", "SOURCE OCC f119: gan nhu tinh (diff f102->f119 = 0.236/255, max 35) - cua so nguon cua SEG2 gan tinh", "SOURCE-REF"),
    entry(f"{F}/_wm_check_strip.png", "Strip 6 goc duoi-trai: 3 source (co watermark Lanh Vcl + play do) vs 3 frame sinh (sach)", "EVIDENCE"),
    entry(f"{F}/_right_edge_strip.png", "Strip 3 cot 90px ria phai: SRC f0 (co dang nguoi be/kem toc dai bi cat + khung anh tuong) | GEN f0 | GEN f119 (chi con nguoi ao trang quay lung + khoi tim)", "EVIDENCE"),
]

previews = [
    entry("proof/evidence/previews/p7v13_cut_119_120.png", "Cut 119/120 BOOK->TURN: cat canh that, hai ben ro, khong seam/dup", "CLEAN"),
    entry("proof/evidence/previews/p7v13_cut_239_240.png", "Cut 239/240 TURN->OCC: trang chung nhan nghieng | trang TVTT&PTTM; cat sach khong dup", "CLEAN"),
    entry("proof/evidence/previews/p7v13_cut_341_342.png", "Cut 341/342 join noi bo OCC tai cut nguon 101->102: doi canh DUNG cut nguon; khong dup/seam", "CLEAN"),
]

d = {
    "task": "MF-DEMO-E2E PROOF_GATE product-side verification on assembly v1.3",
    "session": "20260926_181543_020847",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "rules_loaded": "C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md (27782 B, read fully this turn)",
    "read_only": "RUN/proof/** (no write); write-set RUN/demo/** only",
    "target": {
        "file": "proof/output/p7/assembly_v13_00001_.mp4",
        "sha256": sha("proof/output/p7/assembly_v13_00001_.mp4"),
        "bytes": (RUN / "proof/output/p7/assembly_v13_00001_.mp4").stat().st_size,
        "ffprobe": {
            "video": "640x368 30/1 12.000000s nb_read_frames=360",
            "audio": "aac 44100 Hz 2ch 11.980998s",
        },
    },
    "pins": {
        "BOOK": {"file": "proof/inputs/p7v13_book.mp4", "sha256": sha("proof/inputs/p7v13_book.mp4"), "frames": 120},
        "TURN": {"file": "proof/inputs/p7v13_turn.mp4", "sha256": sha("proof/inputs/p7v13_turn.mp4"), "frames": 120},
        "OCC_SEG1": {"file": "proof/inputs/p7v13_occ_seg1.mp4", "sha256": sha("proof/inputs/p7v13_occ_seg1.mp4"), "frames": 102},
        "OCC_SEG2": {"file": "proof/inputs/p7v13_occ_seg2.mp4", "sha256": sha("proof/inputs/p7v13_occ_seg2.mp4"), "frames": 18},
    },
    "u20_decode": {
        "command": "ffmpeg -v error -i assembly_v13 -f null -",
        "rc": 0,
        "result": "FULL_DECODE_OK",
        "note": "mo lai tu UI sau restart KHONG test duoc (app chua noi engine)",
    },
    "frames": frames,
    "boundary_previews": previews,
    "motion_measure": {
        "method": "mean abs diff (RGB 0-255) giua cac frame lay mau; doi chieu cung cap frame nguon",
        "output": {"BOOK f0->f60": 3.101, "BOOK f60->f119": 5.959, "TURN f120->f180": 35.198,
                   "TURN f180->f239": 38.199, "OCC1 f240->f300": 15.927, "OCC1 f300->f341": 5.655,
                   "OCC2 f342->f350": 2.696, "OCC2 f350->f359": 2.457, "OCC2 f342->f359": 2.785},
        "source": {"BOOK f0->f60": 0.613, "BOOK f60->f119": 1.637, "OCC2 f102->f119": 0.236},
        "conclusion": "motion co that o moi unit; BOOK/OCC2 output thay doi NHIEU HON source (nguon gan tinh) => khong phai anh tinh dong bang",
    },
    "u_mapping": {
        "U06": "BOOK: nguoi ngoi + nu + 2 nguoi quay lung + nguoi TIM bi cat ria phai deu hien dien dung vi tri; THIEU dang nguoi be/kem bi cat ria phai (finding F2). OCC2: 1 nguoi (nam tre) thay chu the; TURN/OCC1: khong co nguoi (trang giay).",
        "U07": "boi canh/vat doi style phang cel: ban bi-a don gian hoa, khung anh tuong BI BO (F2), rem/tuong giu bo cuc; SEG2 them chi tiet cua so phan chieu; prop references chua co version/manifest (gap).",
        "U08": "BOOK: nguoi toc xam CAM sach (khep ca 2 phia o cac frame lay mau) - ai-cam-gi giu dung; OCC_SEG1: tay-but tren trang TVTT&PTTM dung nguon; OCC_SEG2: nguoi ngoi ban cam sach MO trong khi nguon KHEP (F3, da khai bao); TURN: trang chung nhan + cho ky ten, khong tay but.",
        "U10": "12.000000s / 360 frame / 640x368 / 30fps / AAC 44.1k stereo 11.981s; cut 119/120, 239/240, 341/342 kiem tra bang mat + previews = sach; source_span tung segment khop pin.",
        "U11": ">=3 frame giua moi unit: TURN 35.2/38.2 (lon), OCC1 15.9/5.7 (vua), BOOK 3.1/6.0 (nho nhung >source 0.6/1.6), OCC2 2.7/2.5 (nho, source cung gan tinh 0.24). Khong phat hien thay anh tinh.",
        "U20": "decode toan file rc=0 (360 frame doc du). Mo lai tu UI sau restart: NOT_RUN (app chua noi engine).",
    },
    "findings": [
        {"id": "F1", "severity": "P2", "status": "known-transient, con hien dien v1.3",
         "frame": "assembly f180 = TURN f60",
         "desc": "chu bi nhan doi 2 lop (CTY TNHH Bao Nam Training x2 lech) + mep trang trang lech; sach lai o f239 (TURN f119)",
         "evidence": "demo/frames/asm_f180.png", "owner": "engine lane (VIDEO14B)"},
        {"id": "F2", "severity": "P2", "status": "NEW (demo-side coverage), chua khai bao",
         "frame": "BOOK f0/f60/f119 ria phai",
         "desc": "nguon co 1 dang nguoi be/kem toc dai bi ria phai cat + khung anh treo tuong; ban sinh chi giu nguoi ao trang quay lung + khoi tim - mat 1 doi tuong partial right-edge va khung anh",
         "evidence": "demo/frames/_right_edge_strip.png", "owner": "demo/engine (U06/U07)"},
        {"id": "F3", "severity": "P3", "status": "declared (P5fix3 standing note)",
         "frame": "assembly f359 = OCC_SEG2 f17",
         "desc": "sach MO vs nguon KHEP; hoodie + shading nhieu hon style nguon; ly co nuoc kem + ong hut xanh vs nguon ly trong + ong hut cam - can chot book-state/props policy",
         "evidence": "demo/frames/asm_f359.png + demo/frames/source/occ_src_f102.png", "owner": "product/demo policy"},
        {"id": "F4", "severity": "P3", "status": "INFO",
         "frame": "ca 3 source vs ban sinh",
         "desc": "source ca 3 clip co watermark Lanh Vcl (play do); moi frame sinh lay mau deu SACH => Wan path khong copy watermark; VACE (challenger) copy watermark => khoa nhanh VACE",
         "evidence": "demo/frames/_wm_check_strip.png", "owner": "n/a (constraint)"},
    ],
    "interface_gaps": [
        "FullApply chua co nhanh engine cap shot (renderer_router chi sprite adapters) => UI khong the tao clip nay tu flow import->cast->apply->export (chan demo UI).",
        "Input plumbing: anchor PNG + source window 640x360/120f + pad 640x368 (pad giua) hien dat thu cong duoi proof/inputs; can route/dong goi tu dong + receipt (prompt_id/graph_sha256/wall/vram/seed/output_files).",
        "Cast/PackVersion reuse (U02/U03) chua di qua proof nay: anchors dung reference I1 byte-frozen, khong doc tu character pack cua app; can route publish authored RGBA artwork -> pack -> cast pin + engine doc cast lam reference (vuong D2-01/D2-02).",
        "QC rendered-side mask producer (S08-T05) + contact/occlusion rows (S08-T02) chua co => QC full-scope khong chay.",
        "Book-state policy: BOOK giu khep khop moi frame nguon lay mau (f0/f72/f80 - KHONG thay open_two_pages@72 bang mat thuong => de nghi re-check mapping event); OCC_SEG2 mo vs nguon khep => can quyet dinh san pham.",
        "Watermark: Wan path sach; VACE copy watermark => khong dung VACE cho demo toi khi co cach xu ly.",
        "Artwork placeholder: nhan vat moi demo-grade (boy_hacker/gau_nau placeholder) - khong claim dien mao cuoi.",
    ],
    "verdict": "DEMO_OWNER_VISUAL_PASS (with findings F1-F4, none blocking; 2 policy items: book-state, artwork placeholder; VACE branch blocked by watermark)",
    "not": ["KHONG ghi QUALITY_ACCEPTED", "khong phong release", "khong APPROVED/CLOSED"],
    "terminal": "TASK_SUBMITTED",
}

out = RUN / "demo" / "demo_review.json"
out.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("written:", out, out.stat().st_size, "B  sha256:", hashlib.sha256(out.read_bytes()).hexdigest()[:16])
print("frames:", len(frames), "| previews:", len(previews), "| findings:", len(d["findings"]))
