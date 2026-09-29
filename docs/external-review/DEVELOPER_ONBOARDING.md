# MotionForge 2D — Developer onboarding cho external review

Ngày chốt: **29/09/2026**, cutoff snapshot read-only **17:12 +07**. Bắt đầu từ [START_HERE_EXTERNAL_REVIEW](../../START_HERE_EXTERNAL_REVIEW.md) và [hồ sơ BA tiếng Việt](PROJECT_BRIEF_VI.md).
Candidate source: `a52fca897906fd61a088016dd802718fdf06d217`. Verdict: **NOT_APPROVED / NOT_CLOSED / QUALITY_ACCEPTED=0**.
Correction C11/C15/C22 ngày 29/09 được capture riêng; không được coi là đã tích hợp hoặc đã kiểm chứng trên candidate này.
C11 mới nhất là `e3b130149c84b193736d14d00a26363bdb279dee` trên ref bàn giao `review/20260929-c11-correction`; không merge vào candidate chỉ để đọc hoặc tái lập.

## 1. Mức độ kiểm chứng của hướng dẫn

Tài liệu được đối chiếu với source; lượt bàn giao này **không cài dependency, không chạy broad test, không khởi động backend/frontend/Comfy và không chạy GPU**.
Các lệnh dưới đây là quy trình đề xuất cho developer trên máy mới, không phải log chứng minh clean-host setup đã pass.
Một kiểm tra stdlib build của dependency đã được thực hiện trong lượt bàn giao: builder đọc Git object pin từ review checkout, xác minh **11 source files**, tạo wheel ở thư mục tạm ngoài checkout; không pip-install.
Wheel SHA256 của lần build đó: `c5bfa6f6d5a5152209e63f8a681b0f35bdceaae1fb21e0621b6ce95567c065ec`. Đây không phải chứng nhận môi trường mới, runtime hay GPU; wheel chứa provenance/timestamp nên không mặc định mọi lần rebuild có cùng wheel hash.
Dev-host đã có bằng chứng staged package và render GPU thật theo review trước; clean Windows/human acceptance vẫn **NOT_RUN**.
Snapshot độc lập buổi sáng chưa có S12 export; Manager lúc 17:10 +07 báo attach-audio completed, hai QC job completed/zero items và S12 run `7da2cb5f-2ea0-414a-a2db-8803ee8f0f59` failed ở publication với `['av_policy']` sau ba chunk. Báo cáo chiều chưa được tái lập độc lập, không phải accepted export.
Nếu lệnh setup thất bại, lưu lệnh, phiên bản công cụ và lỗi ngắn đã lọc; không sửa pin hoặc lặng lẽ bỏ dependency để tạo kết quả “pass”.

## 2. Repository và dependency source

Clone URL của repository được công bố trong entry point bàn giao. Dùng full clone vì test/provenance có tham chiếu commit lịch sử.
Không mặc định `--depth 1`; một checkout có file app chưa chắc có Git object cần để build dependency.
Sau clone, đứng ở repository root và kiểm candidate:

```powershell
git status --short
git rev-parse HEAD
git show --no-patch --oneline a52fca897906fd61a088016dd802718fdf06d217
```

Nhánh bàn giao tài liệu có thể đứng sau candidate một hoặc nhiều commit chỉ thêm docs. Dùng snapshot manifest để phân biệt source baseline và commit bàn giao.
Nhánh remote dependency dự kiến là **`review/20260929-comfy-pin`**, dùng để mang Git object của `mf_comfy`.
Trước khi fetch, xác nhận nhánh này đã được publish trong entry point/manifest; tên dự kiến ở đây không tự chứng minh remote tồn tại.

```powershell
git ls-remote --heads origin review/20260929-comfy-pin
git fetch origin review/20260929-comfy-pin
git cat-file -t 70f718098f00f9dbdeb6cc9c5d7808b243eb0c57
```

Lệnh cuối phải trả `commit`. Không merge nhánh dependency vào nhánh app chỉ để build wheel; builder đọc object store của repository.
Không cần checkout hoặc sao chép nguyên môi trường của tác giả vào máy mới.

## 3. Prerequisites và các khác biệt setup đã biết

| Thành phần | Yêu cầu/pin đọc từ source | Chú ý |
|---|---|---|
| Python | `>=3.11,<3.13`; tài liệu package dùng Python 3.11 | Dùng interpreter rõ ràng cho venv/app/migration |
| Node.js | **>=20.9.0** theo engine của Next trong lockfile | Chính xác hơn câu “20+” trong README package |
| npm | Cài cùng Node; dùng `npm ci` | `frontend/package-lock.json` là authority version thực |
| FFmpeg + ffprobe | Executable trên PATH hoặc override tuyệt đối | Core media/export cần cả hai |
| Torch | `2.11.0+cu128` | `scripts/setup.sh` cũ dùng cu124, không chạy mù |
| torchvision | `0.26.0+cu128` | Phải tương thích pin Torch |
| ComfyUI | Profile pin `0.37.0`, commit `73c9bad4d21e7addbe1d13bc92eee0f1431b017d` | Runtime riêng, không được backend tự cài/start |
| Models | External manifests có relpath/hash/bytes/source/license | Không bundled; không auto-download trong package |

Kiểm công cụ bằng `python --version`, `node --version`, `npm --version`, `git --version`, `ffmpeg -version`, `ffprobe -version`.
CUDA/GPU không phải điều kiện để đọc source hoặc chạy một số test CPU; reskin generation bằng profile GPU là bước runtime riêng.
Benchmark model không phải bảo đảm VRAM/RAM tối thiểu cho mọi video. RAM peak trong profile hiện là `NOT_MEASURED`.

Hai điểm phải xác minh khi cài sạch:

1. [pyproject.toml](../../pyproject.toml) khai báo `build-backend = "setuptools.backends._legacy:_Backend"`; khả năng resolve trên môi trường mới chưa được kiểm chứng ở lượt này.
2. App có `UploadFile`/`Form` routes nhưng `python-multipart` không nằm trong dependency khai báo trực tiếp. Kiểm resolver/import route trước khi kết luận core install đầy đủ.

Đây là blocker/verification item về reproducibility, không phải khẳng định lượt bàn giao đã chạy và quan sát lỗi cài đặt.

## 4. Backend venv và dependency — lệnh đề xuất

Ví dụ PowerShell, chạy tại repository root. Trên POSIX thay lệnh tạo/activate venv cho shell tương ứng; không dùng đường dẫn máy tác giả.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install "torch==2.11.0+cu128" "torchvision==0.26.0+cu128" --index-url https://download.pytorch.org/whl/cu128
python -m pip install -e ".[dev]"
python -m pip check
```

Torch được cài trước từ index cu128 để đáp ứng local-version pin trong pyproject. Tính sẵn có của wheel cho OS/Python cụ thể phải được resolver xác nhận.
Nếu build backend hoặc dependency thiếu gây lỗi, xử lý thành correction có diff và kiểm chứng; tài liệu này không tự thay requirements.
`.[dubbing]` là nhóm tùy chọn cho TTS/STT/translation. SAM2/checkpoint cũng là bước riêng; không cần cài các nhóm đó chỉ để đọc review.
[README gốc](../../README.md) chủ yếu mô tả spike sprite/SAM2; [setup.sh](../../scripts/setup.sh) chưa đồng bộ cu128.

## 5. Runtime root mới, port rõ ràng

Code mặc định dùng `~/MotionForge2D`, có thể chứa dữ liệu thật. Developer/test dùng một thư mục mới, tuyệt đối, ở ngoài checkout và ngoài cây đó.
Ví dụ sau chọn tên phiên riêng. Nếu thư mục đã có dữ liệu, chọn tên mới trước khi launch; không xóa để “làm sạch”.

```powershell
$mfRuntime = Join-Path $env:LOCALAPPDATA 'MotionForge2D-external-review-20260929'
Test-Path -LiteralPath $mfRuntime
$env:MOTIONFORGE_ROOT = $mfRuntime
$env:MOTIONFORGE_OUTPUT = Join-Path $mfRuntime 'output'
$env:MOTIONFORGE_MODELS = Join-Path $mfRuntime 'models_checkpoints'
$env:MOTIONFORGE_QA_MODE = '1'
$env:MOTIONFORGE_CORS_ORIGINS = 'http://localhost:3000,http://127.0.0.1:3000'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8888
```

App lifespan khởi tạo/upgrade DB ở `<MOTIONFORGE_ROOT>/data/motionforge.db`, reconcile job cũ rồi start worker/analyze orchestrator.
Managed artifacts mặc định ở `<MOTIONFORGE_ROOT>/artifacts`; output và SAM model root cần đặt riêng như trên vì default của chúng không tự suy từ `MOTIONFORGE_ROOT`.
`MOTIONFORGE_DATABASE_URL` dùng cho migration tooling; không coi nó là cách thay `MOTIONFORGE_ROOT` của app mặc định.
Không cần chạy migration thủ công trước normal startup. Nếu sửa migration, [migrations/env.py](../../migrations/env.py) hỗ trợ explicit `-x db_url=...`; phải chỉ rõ DB mới trước khi thao tác.
Health route: `GET http://127.0.0.1:8888/health`; OpenAPI thường ở `/openapi.json`, tài liệu route ở `/docs`.
Đây là ứng dụng local loopback có Origin allowlist, chưa có mô hình cookie/JWT multi-user. Không đổi host sang public bind để “demo nhanh”.

## 6. Frontend — terminal riêng

```powershell
Set-Location frontend
npm ci
$env:NEXT_PUBLIC_API_URL = 'http://127.0.0.1:8888'
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Mở `http://127.0.0.1:3000`. Backend phải chạy ở port tương ứng.
[next.config.ts](../../frontend/next.config.ts), [api.ts](../../frontend/src/lib/api.ts) và [s12-export-api.ts](../../frontend/src/lib/s12-export-api.ts) mặc định backend `8888`; bare uvicorn mặc định `8000`, nên luôn truyền port như trên.
Build production frontend phải pin endpoint trước build vì public env/rewrites được đóng vào artifact:

```powershell
$env:NEXT_PUBLIC_API_URL = 'http://127.0.0.1:8888'
npm run build
npm run start -- --hostname 127.0.0.1 --port 3000
```

Không chạy dev và start trên cùng port đồng thời. `npm run build` pass chứng minh build frontend, không chứng minh backend route, GPU hoặc chất lượng video.
Khi sửa frontend, đọc [frontend/AGENTS.md](../../frontend/AGENTS.md) và guide Next cài trong `node_modules/next/dist/docs/`.

## 7. mf_comfy — build từ object pin, không dùng worktree tác giả

Distribution `mf-comfy==0.1.0` được build từ **11 module files** dưới `experiments/mf_reskin_v1/comfy/mf_comfy` tại commit `70f718098f00f9dbdeb6cc9c5d7808b243eb0c57`.
Builder và adapter kiểm manifest hash/size/provenance. `pip install mf-comfy` từ registry bất kỳ chưa được xác nhận tương đương pin này.
Sau khi fetch thành công nhánh dependency, chạy ở root repository trong venv đã activate:

```powershell
$mfSourceRepo = (Get-Location).Path
$mfDependencyBuild = Join-Path $env:LOCALAPPDATA 'MotionForge2D-external-review-deps-20260929'
python scripts/build_mf_comfy_dependency.py --source-repo $mfSourceRepo --out $mfDependencyBuild --pip-install
python -c "from app.adapters.media_engine.comfy import engine_status; print(engine_status())"
```

Kỳ vọng `engine_status()` trả `available: True`, source commit pin đúng và `files_verified: 11`. Đây là kiểm package bytes, chưa phải kiểm Comfy live.
Luôn truyền `--source-repo`: default builder là đường dẫn tác giả `C:/Users/Admin/.../wt-comfy` và không portable.
`--install-target` chỉ giải nén vào target; nó không tự đưa thư mục đó vào import path. `--pip-install` cài wheel vào interpreter hiện tại bằng chế độ offline/no-deps.
Giữ wheel/provenance ngoài checkout. Builder có thể từ chối source commit/file/hash sai; không sửa hash pin để né refusal.

## 8. Comfy runtime, models và những phần bootstrap chưa hoàn chỉnh

Đọc [model_profiles.json](../../app/media_workflows/model_profiles.json), [workflow manifests](../../app/media_workflows) và [model inventory](../../packaging/demo/models.json).
`engine.models_root` trong profile đang chứa đường dẫn cá nhân. Cung cấp model root của máy mới bằng tham số runtime/launcher phù hợp; không tạo lại cây `C:/Users/Admin`.
Demo launcher nhận `-ModelsRoot` hoặc `MF2D_MODELS_ROOT`. `MOTIONFORGE_MODELS` của app/SAM và model root Comfy là hai phạm vi khác nhau.
Launcher check model tồn tại/không rỗng không thay cho việc đối chiếu đầy đủ SHA256 và pin theo manifest.
Wan baseline `wan_animate2_int8_pad640x368_cacheoff` đã có benchmark GPU, nhưng **chưa được chấp nhận chất lượng**. Controlled path vẫn unsupported trong profile này.

Adapter cần live boot identity tại:

```text
<managed_root>/media_engine/comfy_shot_engine/instance_epoch.json
```

[ComfyShotEngine](../../app/adapters/media_engine/comfy.py) từ chối `EPOCH_MISSING` nếu identity chưa được launcher tạo đúng; một server trả HTTP 200 chưa đủ.
Source adapter nhắc `serve_comfy`, nhưng không tìm thấy implementation tương ứng trong `app/` hoặc `scripts/` của candidate đã đọc.
[mf_delivery_launcher.ps1](../../scripts/mf_delivery_launcher.ps1) hiện start backend/frontend, không chứng minh có bootstrap Comfy live epoch hoàn chỉnh.
Vì vậy chưa có lệnh one-shot Comfy portable được xác nhận để đưa vào hồ sơ. Developer cần giải quyết khoảng trống launcher/epoch với authority hiện có, không tự viết JSON epoch giả.
FullApply có `engine_base_url` loopback trong manifest; default adapter là `http://127.0.0.1:8188`. Không mặc định port demo cũ còn tồn tại.
Cast recommendation còn pin advisory endpoint local `http://127.0.0.1:20128/v1` và model `ocg/deepseek-v4.1-flash` trong [cast_recommendation.py](../../app/services/cast_recommendation.py); máy mới không tự có dịch vụ đó.
Không đổi advisory/model route hoặc tải model chỉ để làm onboarding pass; ghi dependency thiếu và kiểm UI xử lý unavailable.

## 9. Kiểm tra có ý nghĩa, chạy theo phạm vi

Các lệnh pytest dưới **chưa được chạy trong lượt bàn giao**. Chọn nhóm đúng thay đổi; không bắt đầu bằng toàn bộ suite hoặc GPU demo dài.

```powershell
python -m pytest tests/test_schema.py -q
python -m pytest tests/product_delivery/test_mf_end_19.py tests/product_delivery/test_mf_end_20.py tests/product_delivery/test_mf_end_22.py -q
```

Nhóm END-19/20/22 kiểm manifest/planning, receipt/cache/restart và comparator với fixture/control. Một số case media cần FFmpeg; đây không phải chứng cứ fidelity GPU.
Adapter dependency tests cần source repo có pin; nếu thiếu fixture có thể skip:

```powershell
$env:MF_END18_SOURCE_REPO = (Get-Location).Path
python -m pytest tests/product_delivery/test_mf_end_18.py -q -ra
```

Ghi cả skipped và lý do. Một số assertions dựa vào historical Git commit; không coi lỗi shallow clone là lỗi render hay bỏ test để báo xanh.
Frontend kiểm `npm run build` và `npm run lint` trong `frontend/`. Playwright mặc định [playwright.config.ts](../../frontend/playwright.config.ts) yêu cầu backend/frontend đã chạy, không tự start web server.
Browser E2E thật phải kiểm project/video context xuyên reload và import→cast→anchor→apply→QC→audio→S12. Test route/logic với SQLite fixture không thay cho lần chạy đó.

## 10. Windows staged package và giới hạn bàn giao

[Windows guide](../../docs/packaging/s12-windows.md) và [demo guide](../../packaging/demo/README.md) mô tả stage ở ngoài checkout, runtime root riêng và external prerequisites.
Không dùng `packaging/windows/manifest.json` lịch sử làm chứng cứ artifact mới đã được build cho candidate; builder cần tạo manifest mới với source/toolchain/hash hiện hành.
Ví dụ lệnh build có tham số placeholder cần thay bằng thư mục tuyệt đối mới:

```powershell
python scripts/s12/s12_t06a_stage.py --stage-root <ABSOLUTE_NEW_STAGE> --backend-port 8426 --frontend-port 3126
```

Đây là lệnh có build/write, không phải read-only preflight. Stage phải ngoài checkout và protected runtime; existing stage bị từ chối.
Package không tự cài Python, Node, Python dependencies, FFmpeg, ComfyUI hoặc model weights. Nó cũng không mang DB/media/token của tác giả.
Theo dõi lifecycle bằng runner và identity records; không kill theo PID cũ nếu identity không khớp. Uninstall mặc định giữ data/artifacts/output.
Nghiệm thu clean Windows/host độc lập và human acceptance vẫn là gate riêng, chưa được miễn bằng dev-host smoke.

## 11. Những điều cần báo lại khi tiếp quản

- Commit app/docs/dependency đã checkout/fetch; correction nào chỉ đang review và chưa tích hợp.
- OS, Python/Node/npm/FFmpeg versions; lệnh setup và dependency blocker đã tái lập được.
- Runtime root, endpoint và model manifest được chọn; không gửi dữ liệu nhạy cảm hoặc raw session log.
- Test đã tự chạy, kết quả, skipped và giới hạn; tách khỏi 884 tests do bên triển khai báo.
- Một failure nội dung cụ thể với source/output hash, frame/span, role và expected/actual.
- Diff sửa đúng nguyên nhân, negative control và public-path evidence; trạng thái quality acceptance cập nhật bởi reviewer.

Source of truth cho cấu trúc là [app](../../app), [frontend/src](../../frontend/src) và [pyproject.toml](../../pyproject.toml), không phải các đường dẫn môi trường cũ trong reports.
