Đọc TOÀN BỘ `C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md`, đặc biệt §0.1 và §0.2 cập nhật 01/10, rồi báo RULES_LOADED. Đọc current overlay của CODEX_PM_HANDOFF.md và ROADMAP.md. Sau đó thực thi packet này; người dùng tự giao prompt, Codex không launch/message Hermes.

# Làm video mẫu bằng WAN trước — vision tự kiểm và sửa tối đa 10 phiên bản

## 1. Quyết định của người dùng và kết quả phải giao

Người dùng muốn **video mẫu thành công trước rồi mới đưa workflow về làm tool vận hành**. Dùng **WAN qua ComfyUI để sinh lại video**, với diện mạo nhân vật, vật phẩm và nền mới; vẫn giữ sát động tác, tương tác, camera, cut và timeline gốc. Hướng thực thi:

**Video ngắn có sẵn → transcript lời nói + transcript sự kiện hình ảnh theo shot → chọn bộ nhân vật cố định → ComfyUI tạo ảnh cảnh đích → WAN nhận ảnh cảnh đích + driving video nguồn → ghép tiếng gốc → vision/QC → sửa có lý do → MP4 hoàn chỉnh.**

User cho Hermes tự dùng vision để xem, đánh giá và quyết định sửa, tối đa **10 phiên bản sản phẩm**, dừng sớm khi đạt và nộp Codex review một lần. Không xin Codex sau mỗi ảnh/shot/attempt. Đây là **một task media prototype**, không phải chuỗi task code mới.

Packet này thay thứ tự M1-first, yêu cầu chờ UI/public library/anchor API và gate Codex giữa từng attempt trong plan 30/09 cho scope thử nghiệm này. M1-01 và các code corrections tạm hoãn, giữ nguyên dirty bytes. Được chạy headless ComfyUI/harness media trước app; không gọi đó là app end-to-end hoặc S12 hoàn thành. Các invariant của target profile vẫn giữ; deterministic-renderer default cũ không chặn thử nghiệm WAN user đã chọn.

**Deliverable chính: một MP4 mới có âm thanh, đủ toàn bộ source ngắn đã chốt, kèm video so sánh đồng bộ và log tiến bộ từng phiên bản.** Không thay bằng slide, ảnh tĩnh, UI screenshot, test count hoặc video cũ đổi tên. Không hứa 10 lần chắc chắn đạt; giữ bằng chứng nếu chưa đạt.

## 2. Owner, route, workspace và quyền thực hiện

- Manager: resume `20260930_235002_3ac7f9`, chỉ điều phối/QA/report. Nếu user giao vào một Manager mới, ghi rõ takeover Manager và xác nhận không có Manager khác đang dispatch; không tự sinh thêm tầng supervisor.
- Task: **MF-DEMO-E2E-R5 / WAN-PROTOTYPE-01**, resume exact demo owner **`20260929_041810_bc7c61`**. Không tạo owner demo trùng. Saved DB có 517 messages tại preflight Codex; đủ để audit context ngắn, không tự kết luận hỏng chỉ vì dài. Dùng compact current packet, không nạp toàn bộ lịch sử.
- WIP=1, một GPU job tại một thời điểm. M1 worker `20260928_181955_a6d89a`, C19/C25, integration và mọi task code khác không dispatch trong window này. Kiểm process thật trước; không coi DB `ended_at=null` là đang chạy hoặc đã dừng.
- Coding/manager route theo user: custom **`cmc/deepseek/deepseek-v4.1-flash`**, chat_completions, fallback OFF, chỉ reasoning setting route thực hỗ trợ. Saved demo session còn nhãn ocg cũ; kiểm route actual, pin CMC cho lần resume này, không sửa global Hermes/9router/session khác. Vision có thể qua công cụ riêng đã cấu hình; ghi đúng provider/model của công cụ, không gọi text-only là vision.
- Read-only code: `C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION`, branch `codex/mf-end-integration-0928`, expected HEAD **a52fca897906fd61a088016dd802718fdf06d217**. Codex đã thấy clean; Manager kiểm lại. Không merge/cherry-pick, commit, push hoặc sửa production/test.
- Tạo RUN mới duy nhất dưới `C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20261001/<UTC>-wan-prototype/`. Manager chỉ ghi `RUN/manager/**`; demo worker ghi `RUN/tasks/MF-DEMO-E2E-R5/WAN-PROTOTYPE-01/**` (gọi là D). Graph copies, harness, media, environment/cache và evidence trong D được cấp rõ. Không ghi đè old RUN.
- Runtime hiện có: `C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/venv/Scripts/python.exe`, Comfy tại `.../video14b/ComfyUI`, models tại `.../video14b/models`. Models/runtime gốc read-only. Được khởi chạy Comfy với base/input/output/temp/user/cache trong D và một port trống, bind localhost; một lease GPU. Với process background Windows, dùng Hidden. Không chiếm/dừng server người dùng, không sửa global custom_nodes/env.
- Được viết harness ngắn để nối FFmpeg/Comfy API và kiểm kết quả trong D. Ưu tiên reuse graph/API/client có sẵn, không dựng service/DB/queue/editor sản phẩm mới. Existing file dùng bounded patch, preimage/read-back; new file chia nhỏ, không monolithic tool payload.
- Snapshot HEAD/status và hashes của graph gốc/protected paths lúc đầu, kiểm lại cuối. Model nhiều GB: tái dùng full hash/revision đã có chỉ khi file metadata không đổi và ghi provenance; nếu khác phải kiểm lại file liên quan. Không hash lại toàn bộ ổ đĩa mỗi attempt.

## 3. Nạp kiến thức đúng phần, preflight một lần

Packet Codex: `C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/mf-rebuild-skills-20261001`.
Đọc `SESSION_OPENING_PROPOSAL.md`, `PROTOTYPE_PREFLIGHT.json`, `DECISION_AND_COMPARISON.md`; tra `SKILLS_INSTALL_REPORT.md` khi chọn skill. Tối đa 2–3 skills trực tiếp liên quan. Handoff hiện có là authority; không chạy thêm full brainstorm/spec/plan của nhiều framework.

Đọc `REUSE_EXECUTION_MATRIX.md` và `MOTION_WINDOW_FINDING.md` trong cùng packet. Codex đã chuẩn bị `reuse_bundle/PROVENANCE.json`, snapshots graph/template và API graph đã trích đúng định dạng. Copy bộ này vào D, rebind media/facts theo shot; baseline còn BOOK/file cũ nên chưa submit thẳng. Ghi `reuse_decision.json` với source hashes và delta tối thiểu. Không xây lại inference engine hoặc thêm framework; bắt đầu WAN từ `reuse_bundle/wan_shot_v1.motion_enabled.api.json` đã sửa pose window. Được sửa graph/bindings/harness task-local cần thiết, không đợi UI hoàn thiện.

Áp dụng `search-first` cho reuse; dùng `ce-debug` chỉ khi có lỗi cần tìm nguyên nhân; dùng `planning-with-files` nếu cần chống mất context, ánh xạ vào plan/findings/progress trong D thay vì tạo backlog cạnh tranh. Đọc đúng SKILL.md tại path installation report. Skill/hook không cấp quyền tự chạy task khác, gọi model khác, cài service hoặc nới budget. Không kích hoạt hook/autoloop/telemetry; không cài Superpowers đang bị admin disable.

Nguồn kỹ thuật chính thức, đã được Codex kiểm:
- https://docs.comfy.org/tutorials/video/wan/wan-animate-2
- https://github.com/Wan-Video/Wan-Animate-2
- https://docs.comfy.org/tutorials/flux/flux-2-klein
- https://github.com/openai/whisper (ASR lời nói, không phân tích hành động)

Reuse trong INTEGRATION: `app/media_workflows/shot_anchor_v1.json`, `wan_shot_v1.json`, manifests và `reference_asset_v1.json`. Các file có wrapper metadata; submit đúng graph API đã trích, không gửi cả wrapper vào `/prompt`. Bỏ bindings/prompt literal BOOK cũ khi không tương ứng shot mới. `reference_asset_v1` tạo view từ reference cùng nhân vật, không được dùng source crop rồi giả đó là cast mới.

Preflight kiểm route/công cụ vision, file nguồn, model/node availability, GPU/VRAM/disk, ports và source timebase. Không chạy broad tests của app hoặc nghiên cứu lại toàn bộ shortlist. Checkpoint đầu mục tiêu trong 20–30 phút: source/transcript/cast/graph được pin và đã có image job thực hoặc GPU đang xử lý; nếu load lạnh lâu, báo phase/log thực, không coi thời gian mục tiêu là lý do bịa kết quả hoặc kill job có tiến độ.

**Vision preflight bắt buộc:** dùng công cụ vision thật đọc một hình với nội dung kiểm tra được và contact sheet nguồn, lưu tool receipt cùng file/hash và câu trả lời. Tên model/flag vision không đủ. Nếu công cụ không đọc được media, không tự chấm PASS hay sweep 10 bản mù; nộp `VISION_UNAVAILABLE` cùng sản phẩm hiện có và capability error. Không tự cài model vision mới hoặc đổi provider để né quota.

## 4. Chốt source, transcript và cast một lần

Source ưu tiên đã xác minh tồn tại:
`C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-DEMO-E2E-R5/raw/source_12s.mp4`
SHA256 **fc18e859599f8feeb730ee9018413ced4c183f90a15e20ccc162433c4666c8cc**, 629545 bytes.

Dùng **toàn bộ clip ngắn này** làm mẫu; ffprobe/decode để đo actual frame count/fps/PTS/audio, không suy từ tên 12s. Kiểm cut bằng frames thực; bản phân tích trước ghi boundaries 121/241/343, cần xác nhận trên chính SHA này. Không chia đều thành các đoạn tùy ý, không bỏ shot ngắn cuối. Giới hạn tối đa 4 units cho nguồn mẫu; nếu source hash/cuts khác thì ghi mismatch, không âm thầm lấy clip dễ hơn. Một contact/prop event phải còn trong mẫu; không thay bằng chân dung đứng yên khi khó.

Lưu `source_manifest.json` và source copy byte-identical. Source/cast/frame map đóng băng trước candidate 1; không đổi benchmark để nâng điểm. Nếu file không còn hợp lệ, báo cụ thể để chọn lại trước render.

Tạo `transcript.json` + bản người đọc được:
- Speech: lời nói theo thời gian, ngôn ngữ, đoạn không nghe rõ. Reuse ASR/transcript đã có nếu cùng hash và kiểm đúng. Nếu thiếu ASR, được tạo venv riêng trong D, cài một engine Whisper/faster-whisper từ upstream chính thức và tải một checkpoint nhỏ phù hợp tiếng Việt, tổng tải mới không quá 1 GiB. Cache trong D, chạy CPU khi cần để không tranh VRAM; không sửa Comfy venv/global Python. Nếu không có speech ghi `NO_SPEECH`; không bịa lời hoặc mở TTS.
- Visual: mỗi shot có start/end frame, keyframes, role/prop IDs, ai làm gì, mốc bắt đầu/kết thúc/tiếp xúc, trạng thái vật trước/sau, che khuất, framing/camera, cut. VLM mô tả kèm evidence frame và confidence/unknown. Xem dày hơn quanh sự kiện; ASR không thay visual transcript. Không gọi model trên từng frame theo mặc định.
- Tách source facts khỏi target appearance. Prompt text không phải dữ liệu chuyển động; driving clip phải đúng span và thực sự tới node video.

Cast: tìm ảnh đích đã có và có provenance trước. Nếu thiếu, **được dùng Comfy image workflow sẵn có tạo một bộ demo mới**, kiểu 2D phù hợp hình thể và động tác nguồn; pin danh tính/palette/clothes/refs một lần, dùng xuyên cả clip. Lưu `cast_manifest.json`, ảnh reference thật, role mapping và hash. Đây là pack demo trong D, không seed DB hoặc giả published PackVersion của app. Không lặp một ảnh vào sáu pose, không yêu cầu sáu view khi graph chỉ cần một. Thay cả props/background theo hướng tương thích kiểu cầm/kích thước; giữ nội dung chữ có ý nghĩa nếu nguồn có.

## 5. ComfyUI tạo ảnh cảnh và WAN sinh video

**Ảnh cảnh:** bản sao graph `shot_anchor_v1` dựa FLUX.2 Klein 4B FP8 hiện có; dùng source keyframe làm bố cục, cast/props/style đích làm diện mạo. Không dùng prompt BOOK chung. Mỗi shot phải xét đủ vai, kể cả người ở mép/đang bị che, nhưng giữ đúng phần thấy/che của nguồn; không làm lộ toàn thân người vốn bị che. Ảnh phải giữ vị trí tay/vật và trạng thái sự kiện. Vision tự kiểm trước video; sai ảnh thì sửa ảnh trước, không đốt WAN để sửa ảnh đầu vào sai. Manager/worker tự duyệt ảnh kỹ thuật cho experiment theo quyền user, ghi `EXPERIMENT_ANCHOR_CHECKED`, không ghi user đã duyệt hoặc mở public review gate của app.

Reuse Klein distilled profile hiện có4steps/cfg1/Euler; không thay thông số Base theo tên model. Ghi rõ reference order: ảnh nguồn cho bố cục, ảnh đích tương ứng từng role; kiểm chuỗi ReferenceLatent thực sự tới sampler. Mô tả thay thế trực tiếp, không kỳ vọng negative prompt dài sửa bố cục. Các nguồn và contract đã ghi trong reuse matrix, không cần thêm vòng research chung.

**Video engine bắt buộc WAN:** baseline **Wan-Animate-2 INT8 convrot + LightX2V rank64** đang có, qua graph Comfy native đã pin. Không chuyển sang VACE/MoCha/Kling/model khác trong lượt này. Không tải lại cả bộ model hoặc update Comfy toàn cục. Runtime đã chạy được trước; kiểm object_info actual. Nếu thiếu node/model thật, nộp exact blocker sau kiểm có giới hạn, không mở dự án cài môi trường mới.

**Sửa cấu hình bắt buộc trước C01:** graph repo/P6 cũ có `pose_start_percent=0, pose_end_percent=0`; template UI installed cũng nối start vào cả end. Khoảng zero-width chỉ có thể tác động ở boundary đầu, không duy trì driving toàn denoising. API copy Codex đã sửa riêng end thành1.0. Kiểm graph thực nộp/history và mọi loop lần lượt có start0/end1, strength1; giữ cho phép thử chuẩn. Nếu giao UI workflow, sửa link trên bản sao và kiểm exported API, không re-export nguyên template lỗi. Không tắt driving để tránh OOM hoặc khoe tốc độ. Đo lại VRAM/thời gian; số P6 cũ không là ước tính full-pose. Đây là correction có căn cứ code, chưa phải kết quả video đã đạt.

Mỗi unit nhận ảnh cảnh đích + đoạn nguồn đúng frame span. Node `WanAnimate2ToVideo` hiện chỉ dùng `reference_image[:1]`; không nhét batch nhiều reference rồi gọi là multi-role mapping. Ảnh scene đích phải gom đủ cast trong bố cục. Node `pose_video` của variant này là driving video; không ép tạo skeleton chỉ vì tên trường. Không thêm SAM/depth/flow vào mọi shot nếu graph không đọc.

Caption theo contract Animate 2: mô tả target appearance/background và camera mong muốn đúng nguồn; source motion từ driving. Không yêu cầu camera tự do, thêm hành động hoặc đổi nhịp. Giữ aspect ratio; nếu latent cần bội16 thì pad có khai báo rồi bỏ pad khi ghép, không crop mất người/vật ở cạnh. Tuân điều kiện frame-length node; extra context frames chỉ trim theo source map, không sửa event timing bằng speed-up/freeze.

Cut thật dùng anchor riêng; không truyền frame cuối shot trước qua cut khác cảnh. Nếu phải chia cùng shot, continuation có frame offset/overlap được node hỗ trợ và map rõ; mọi unit bổ sung vẫn trong trần 4 units/40 video submissions của packet. Không tự sinh frame bằng nội suy hoặc lặp ảnh để giả WAN motion.

Graph/settings/checkpoint/seed/prompt/input hashes phải lưu theo candidate. Bắt đầu từ pin đã đo; mỗi sửa dựa trên lỗi cụ thể. Được sửa bản sao graph/bindings/controls trong D, không sửa graph trong repo. Không tự train LoRA hoặc thêm engine khác.

## 6. Vòng tự cải thiện — tối đa 10 sản phẩm, không loop mù

Tạo thư mục `candidates/C01` … `C10`. Một candidate là **một phiên bản của cùng video nguồn hoàn chỉnh**, không phải mỗi shot là một sản phẩm.

- Trước job video đầu tiên, cấp slot và ghi ledger. Mọi inference video, kể cả smoke/failed/OOM/cancelled, gắn candidate_id + unit_id; slot lỗi/partial vẫn tính trong 10. Không có thử nghiệm ngoài ledger.
- Trong mỗi candidate, tối đa một video submission mới cho mỗi unit. Cùng unit cần sinh lại lần nữa thì sang candidate kế; không đặt 20 retries trong C01. Tối đa **40 video submissions** toàn lượt và tối đa 10 candidate slots; trần đạt trước thì dừng. Slot sau được tái dùng clip unit không đổi theo hash/provenance, chỉ rerender phần lỗi.
- Video `batch_size=1`, đúng một sampled output cho mỗi unit submission; không seed sweep/best-of-N hoặc nhánh graph sinh biến thể ẩn. Biến thể sampled bổ sung phải chiếm candidate slot và ngân sách tương ứng. Preview/side-by-side/encode từ cùng sampled bytes không phải biến thể inference mới.
- `batch_size=1` nói số video độc lập ở latent/node WAN, không phải số frames trong IMAGE tensors hay RebatchImages. Giữ batching thời gian đúng. Loop continuation tạo các đoạn nối tiếp của cùng output phải có span/iteration/sampler-pass count hữu hạn trong ledger; không biến thành best-of-N hoặc rerender ẩn.
- Candidate 1 có thể bắt đầu từ unit tương tác khó nhất để tránh phí; khi đạt thì làm các unit còn lại và xuất đủ source trong cùng candidate. Nếu unit đó fail phải sửa, ghi C01 partial và cấp C02; không đổi nguồn/cast để né lỗi.
- Tổng **20 image submissions** cho cast + anchors + corrections, kể cả thất bại. Batch output một candidate ảnh mỗi submission, không giấu hàng loạt samples. Ghi ledger riêng. Tái dùng artwork hợp lệ.
- Timeout mạng khi submit: query queue/history bằng prompt_id/client mapping trước retry; chưa rõ job đã được nhận thì không submit trùng. Mọi request/job có trạng thái rõ.
- Sau mỗi candidate có output: vision/QC → nguyên nhân → một nhóm thay đổi có liên hệ → candidate tiếp. Phân loại sai transcript, sai ảnh cảnh, sai binding, cấu hình model hay model chưa đáp ứng. Không đổi seed vô hạn và không prompt dài hơn như biện pháp mặc định.
- Nếu cùng lỗi/cùng cách sửa hai lần không có tiến bộ, dừng cách đó; thử giả thuyết khác đã được cấp nếu còn budget. Không đổi model/goal, không tạo lý do khác tên nhưng cùng thao tác.
- Giữ best-so-far theo số blocker và tiêu chí đã chốt; bản cuối không mặc nhiên tốt nhất. Giữ cả failed outputs. Không ghi đè C01 sau khi chuyển C02.
- **Đủ tất cả tiêu chí thì dừng ngay**, không chạy hết 10 cho đẹp log. Hết 10 hoặc budget/blocker thật thì nộp tốt nhất cùng lỗi chưa giải quyết, không tự tăng trần.

## 7. Vision review và acceptance sản phẩm mẫu

Vision phải đọc **source và output actual**, không chỉ đọc transcript hoặc metrics. Lưu phương thức xem: native video input/playback nếu tool hỗ trợ; nếu chỉ xem ảnh, tạo cặp frame cùng timestamp khoảng 4 fps và dense frame burst quanh contact/cut, kèm optical-flow/motion/timebase kiểm riêng. Ảnh lấy mẫu không chứng minh đã xem video liên tục; ghi giới hạn và đánh dấu UNKNOWN khi chưa đủ. Không tự PASS temporal/lip-sync từ vài keyframes.

Trước attempt 1, đóng băng checklist sự kiện/role bắt buộc và phép đo khả dụng. Với mỗi tiêu chí ghi PASS/FAIL/UNKNOWN, timestamps/frame evidence, lý do và đề xuất sửa; UNKNOWN bắt buộc không tính PASS. Vision đánh giá clip kết quả độc lập với câu tự nhận của worker; không đưa “bản này đã tốt” vào câu hỏi chấm.

Các tiêu chí phải đủ:
1. Video đủ toàn source, đúng frame count/timeline/cut sau assembly; không bỏ shot hoặc dùng source frame thay cho đoạn chưa sinh.
2. Cast đích nhận ra được và ổn định qua các shot; mọi role/props/background thuộc scope đã thay diện mạo, không mất/thêm vai vô cớ; không leak watermark/identity nguồn. Chỉ đổi màu không đủ thay nhân vật.
3. Đúng hành động, thứ tự và mốc sự kiện chính của nguồn; tay chạm/cầm đúng vật, vật ở đúng trạng thái, visibility/occlusion hợp lý. Không đổi ký giấy thành đọc sách. Camera/framing/scale không trôi, crop hoặc thêm chuyển động không có trong nguồn.
4. Không đứng hình giả, biến dạng/flicker/drift nghiêm trọng, không dùng animation pan một ảnh thay video WAN. Giữ source holds thật khi chúng có trong nguồn; không dùng mức motion lớn hơn làm điểm tốt hơn.
5. Audio đúng nội dung nguồn, không TTS/thay nhạc; timeline không bị retime. Đo PTS A/V drift theo chính sách hiện có (không quá một frame), phân biệt codec priming với lệch thực. Nếu miệng/va chạm hiển thị rõ thì kiểm sync sự kiện. Không gọi audio PASS chỉ vì có stream.
6. MP4 decode toàn file, có thể mở lại; side-by-side cùng timeline và timecode phục vụ review. Không lấy pixel similarity với video gốc làm điểm reskin. Không xóa/giảm validator trong code để tạo PASS.

Được dùng FFmpeg trong D để ghép/remux đúng nguồn, không cần sửa public export còn lỗi. Ghi rõ workaround prototype và việc phải tích hợp sau; không báo S12 đã pass. Video master giữ độ phân giải/aspect nguồn; không upscale để che lỗi. Hash không được dùng thay review hình.

Ngưỡng định lượng đã có trong target/benchmark áp dụng đúng scope. Với tiêu chí chưa có máy đo đáng tin, ghi nhận xét frame cụ thể + confidence và giới hạn; không bịa phần trăm motion/camera. Self-review là sàng lọc nội bộ, Codex quyết định nghiệm thu cuối.

## 8. Budget, liveness và điều kiện dừng

- Cửa sổ mới cho đúng prototype: **300 observed model attempts worker, 60 Manager, tối đa 40 vision requests** toàn lượt; vision nếu đã nằm trong counter worker/manager thì ghi liên kết và không cộng token hai lần. ASR/local GPU jobs báo riêng. Warning ở 80%. Đây là operating budgets quan sát, không bịa hard HTTP limiter. Giữ usage các vòng trước, không relabel 0.
- **Deadline tuyệt đối 6 giờ từ dispatch đầu**, tối đa initial launch + 3 technical continuations cùng demo owner, dùng chung mọi counter/deadline. `--max-turns` mỗi process không quá120, không phải cumulative HTTP cap. Supervisor không dùng LLM, chỉ quản lý process tree đã xác minh của task.
- Output cap mặc định đã thấy16384; dùng patch/tool payload nhỏ. Nếu thật sự cần và runtime hỗ trợ, một trial child-env `HERMES_MAX_TOKENS=32768`, rollback nếu provider không nhận; không đổi global hoặc liên tục retry payload lớn.
- Heartbeat20 phút; nếu8 phút không progress thì kiểm log/queue/GPU một lần có giới hạn. GPU đang có tiến độ không phải treo. Poll queue bằng script nhẹ, không gọi LLM mỗi lần poll. Dừng đúng process của mình, bảo toàn artifacts trước cleanup; không đụng GPU job/app của người dùng.
- Quota/auth/config lỗi xác định thì dừng báo thực; transient retry tối đa2 chu kỳ có backoff5 phút trong window, không retry vô hạn. Hai lần fail cùng phương pháp không delta thì đổi phương pháp hoặc nộp blocker.
- Không dùng hết budget nếu đã đạt. Không quay lại sửa UI hoặc nghiên cứu frameworks khi chờ GPU. Không auto-run sau submission.

## 9. Bằng chứng mỗi sản phẩm và bàn giao cuối

Trong từng Cxx lưu: `candidate.json` (parent/reused units, source/cast/input hashes, graph/model/settings/seed, prompt_ids, timings/VRAM/status), transcript version, ảnh cảnh đã dùng, video unit thực, master nếu đủ, `vision_review.json` (tool/model/input media/observations), `qc.json`, `change_reason.md` ngắn. File nào không tạo được ghi NOT_PRODUCED và lý do; không tạo placeholder MP4 hoặc copy clip cũ để đủ danh sách.

Một bảng `CANDIDATE_LOG.csv`/JSONL ghi theo thứ tự C01–C10: time, hypothesis, changed inputs, image/video job count, inference minutes, vision findings, mandatory passes/fails/unknowns, quality delta (better/same/worse/mixed), best flag, lý do dừng. Candidate chưa dùng ghi NOT_RUN sau early stop, không giả có10 sản phẩm. Usage log giữ actual input/output/cache/missing accounting; không đồng nhất cache-read với uncached.

Nộp tối thiểu:
- `FINAL_DEMO.mp4` nếu có full candidate; `BEST_SO_FAR.mp4` chỉ khi full nhưng chưa đạt, hoặc các partial clips ghi rõ nếu chưa ghép đủ. File final trỏ/copy byte-identical từ candidate đã chọn, không render thêm ngoài ledger.
- `SOURCE_VS_RESULT.mp4`, `transcript.json/.md`, `cast_manifest.json`, source manifest, ảnh cast/anchor, workflow API JSON cùng UI workflow khi có, ledger candidates/jobs và receipts.
- `REPRODUCE.md`: đường dẫn runtime/model đã pin, lệnh chạy cùng input, version dependencies; không nhét checkpoint nhiềuGB vào packet.
- `reuse_decision.json`: graph/template upstream đã reuse, hash, delta bindings/config, bằng chứng motion start0/end1 trong submitted graph và sampler-pass count. Không ghi cài model là bằng chứng motion đúng.
- Manager kiểm độc lập best candidate, full-source coverage/cuts/audio, media thật, budget và protected hashes. Không sinh thêm video trong final verify. Tạo đúng một `manager/NEXT_CODEX_REVIEW.md`, bảng criteria và manifest tất định không tự hash chính nó; link trực tiếp video để người dùng/Codex mở.

Terminal khi self-review đạt: **SELF_REVIEW_PASS_PENDING_CODEX**. Nếu chưa đạt: **PROTOTYPE_PARTIAL / LIMIT_REACHED** hoặc blocker cụ thể, kèm best evidence và root cause. Product envelope vẫn **SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW — NOT_APPROVED / NOT_CLOSED; QUALITY_ACCEPTED=0**. Chỉ Codex review rồi mới quyết định mở việc tích hợp tool; không tự close S12/S13.

## 10. Bắt đầu thực hiện

**RULES_LOADED → preflight gọn và vision probe → resume exact demo owner → source/transcript/cast → Comfy ảnh cảnh → WAN C01 → tự xem/sửa trong trần10 → nộp MP4 + log.** Không chỉ trả lại một kế hoạch hoặc xin quyền chia patch. Mọi microstep này thuộc một outcome đã được user cấp; Codex review một lần khi nộp. Người dùng sẽ tự mang kết quả về Codex.
