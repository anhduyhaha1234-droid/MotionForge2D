# Reuse để làm video mẫu MotionForge — kiểm tra 01/10/2026

Quyết định: giữ WAN làm video engine; tái sử dụng workflow Comfy native và image editing nhiều reference. Làm một video hoàn chỉnh, tự xem/sửa tối đa 10 phiên bản rồi Codex review. Chưa tích hợp lại app ở lượt này. Nguồn public chứng minh khả năng và cách nối đúng; không tự chứng minh clip nhiều nhân vật của mình đã đạt.

## 1. Phát hiện cấu hình mới cần sửa trước C01

File `C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION/app/media_workflows/wan_shot_v1.json`, node `672:587` đang có `pose_start_percent=0` và **`pose_end_percent=0`**. Tên `pose_video` ở Wan Animate 2 chỉ video chuyển động nguồn.

Runtime `C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/ComfyUI/comfy_extras/nodes_wan.py`, class `WanAnimate2ToVideo`:

- Schema đặt mặc định start=0, end=1; mô tả ngoài khoảng này bỏ hẳn pose branch.
- `execute` tạo conditioning có pose chỉ trong khoảng đã cho; phần bổ sung ngoài khoảng không có pose values.
- Vì vậy khoảng 0→0 không phải cấu hình thích hợp để đánh giá bám chuyển động toàn quá trình. Có thể còn hiệu lực tại biên đầu theo cách sampler so sánh timestep; không được diễn giải thành chứng minh mọi bước đều hoàn toàn không dùng pose.

Đã tạo **bản sao sửa đúng một giá trị**, `reuse_bundle/wan_shot_v1.motion_enabled.api.json`: end 0→1.0; giữ original và hash/delta tại `reuse_bundle/PROVENANCE.json`. Đây là sửa cấu hình tĩnh, **chưa chạy inference, chưa chứng minh chất lượng**. Chưa sửa repo/runtime. Không suy rằng tất cả demo cũ đều dùng đúng graph này. Review độc lập đã đối chiếu graph P6 cùng SHA trong receipt: P6 cũng dùng0→0, nên số135.21s/10763MiB không phải phép đo full-pose.

**Lưu ý template UI cài trên máy cũng có lỗi nối dây:** input `pose_start_percent` cấp cả start và end ở subgraph. Giá trị end=1 lưu trong widget không chứng minh giá trị hiệu lực là1 khi input được nối dây. Vì vậy dùng API copy sửa rõ end1; nếu giao editable UI workflow thì sửa bản sao link/exposure và kiểm export ra API có start0/end1. Không sửa template gốc hoặc tin một bản export lại chưa kiểm. Xem `MOTION_WINDOW_FINDING.md` cho source lines, sampling boundary và graph hashes.

## 2. Nguồn uy tín và áp dụng cụ thể

| Bước | Nguồn gốc | Dùng lại trong demo | Bằng chứng cần có |
|---|---|---|---|
| Tạo cast/ảnh cảnh | [BFL FLUX.2](https://github.com/black-forest-labs/flux2), [Comfy Klein](https://docs.comfy.org/tutorials/flux/flux-2-klein) | Klein 4B distilled hiện có; template image edit + ReferenceLatent. Ảnh 1 quyết định bố cục; ảnh 2/3/4 mang identity từng role, ghi mapping rõ. Existing graph có chuỗi multi-reference; không cần viết model/renderer ảnh mới. | Input hashes, reference order, prompt từng shot, ảnh đích thật và vision kiểm đủ vai/props/contact/occlusion. |
| Truyền chuyển động | [Comfy Wan Animate 2](https://docs.comfy.org/tutorials/video/wan/wan-animate-2), [Wan upstream](https://github.com/Wan-Video/Wan-Animate-2) | Graph native với ảnh cảnh đích + driving clip đúng span; INT8 convrot, đúng LightX2V và encoder/VAE đã cài. Bắt đầu bản sao motion_enabled nêu trên; không tự xây sampling engine. | Graph actual từ history, model pin, pose range0→1, nguồn thực sự nối vào node, sampler passes, video kết quả. |
| Caption ảnh | [Hướng dẫn chính thức BFL](https://github.com/black-forest-labs/skills/blob/master/skills/flux-image-best-practices/SKILL.md) | Mô tả trực tiếp thay gì và giữ gì; reference-role rõ. Với Klein distilled đang cfg1, không trông chờ thêm đoạn negative prompt dài để sửa cấu trúc. | Prompt ngắn đúng facts của shot, không còn BOOK literal áp cho cảnh khác. |
| Transcript lời | [Whisper upstream](https://github.com/openai/whisper) | ASR đã có; chỉ bổ sung engine nhỏ cô lập nếu thiếu. Tách lời nói khỏi sự kiện hình ảnh. | Timestamp, unknown/no-speech thực; không gọi ASR là nguồn motion. |
| Cắt, ghép, tiếng gốc | [FFmpeg documentation](https://ffmpeg.org/documentation.html) | Dùng FFmpeg/ffprobe hiện có cho source map, concat/remux/compare; không dựng editor mới. | Decode toàn file, frame/cut map, audio content và PTS thực. |

Klein upstream công bố hỗ trợ editing một và nhiều reference, có profile distilled khác Base. Local graph đã đặt **4 steps, cfg1, Euler**; giữ đúng profile khi bắt đầu, không thay bằng thông số Base vì tên gần giống. Graph ảnh đang có 48 nodes, graph WAN63 nodes: phần inference chủ yếu đã có, việc cần làm là cấp input đúng và sửa cấu hình.

Wan Animate 2 hỗ trợ camera độc lập; đó là khả năng điều khiển, không phải đảm bảo tự khóa camera nguồn. Prompt phải mô tả đúng camera gốc và output vẫn phải đo/xem. Không thêm chuyển động camera để làm clip có vẻ đẹp hơn nhưng sai goal.

## 3. Không trộn các thế hệ WAN

[Hướng dẫn Wan2.2 Animate cũ](https://github.com/Wan-Video/Wan2.2/blob/main/wan/modules/animate/preprocess/UserGuider.md) nêu mask extractor mặc định chỉ dành cho một người và tỷ lệ cơ thể lệch có thể gây méo. Đây là điều kiện của pipeline cũ, không phải bằng chứng Wan Animate 2 cấm nhiều người.

Wan Animate 2 đang chọn nhận video trực tiếp. Không chép mù pose/face/mask pipeline hoặc LoRA của Wan2.2 Animate sang model mới. Runtime hiện có chỉ lấy `reference_image[:1]`: nhiều nhân vật phải được sắp đúng trong một scene anchor; batch nhiều portrait vào node này không tự tạo role binding. Khả năng giữ tương tác nhiều người/phụ kiện trên clip cụ thể vẫn cần thử và xem thật.

## 4. Vì sao pipeline mình chưa đạt

Đã có bằng chứng local trong [CODE_REVIEW.md](C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/mf-goal-review-skills-20260929/CODE_REVIEW.md): cast crop nguồn bị lặp thành nhiều slot; binding theo shot chưa xong; lỗi request field làm public anchor route thất bại; lỗi QC chưa chặn readiness đúng. Chúng là vấn đề ứng dụng/input, không chứng minh WAN không có khả năng.

Phát hiện zero-width pose window ở mục1 là lỗi cấu hình cần loại bỏ trước khi kết luận năng lực model. Nó cũng cho thấy “model được cài” và “motion conditioning được dùng đúng” là hai bằng chứng khác nhau.

Public demo thay một người trong một shot không tự chứng minh thay đồng thời toàn bộ cast/props/background, tương tác và giữ cut/audio. Dự án vẫn cần kiểm các tiêu chí đó, nhưng phải kiểm trên workflow chuẩn. Không cần build lại từ đầu để làm phép thử này.

## 5. Bộ reuse đã chuẩn bị và thứ tự thực thi

`reuse_bundle/` chứa bản gốc wrapper, API graph đã trích `.graph`, hai template UI chính thức đang cài và provenance hashes. Template UI có `nodes/links` không được gửi nguyên vào API `/prompt`. Các baseline còn literal BOOK/file cũ; **chưa phải payload nộp ngay**.

1. Copy bundle vào D, kiểm hash, đọc source graph và object_info actual; kiểm node/model/links và một sampled output. Không update toàn bộ Comfy.
2. Ghi `reuse_decision.json`: upstream/template hash, graph hash, node changes và lý do. Dùng Klein graph hiện có, WAN motion_enabled copy. Minimal changes: media, caption, output path, span/pad và các control có lỗi cụ thể.
3. Rebind source facts/role map/keyframe/cast/positive appearance và positive_pose từng shot. Không sao metadata BOOK cũ thành facts mới. Giữ refs/cast ổn định, giữ che khuất đúng nguồn.
4. Kiểm ảnh trước; ảnh đạt mới sinh video. Motion window0→1, strength1 là baseline. Không giảm hoặc tắt branch để đạt số giây render đẹp. Đo lại thời gian/VRAM/profile thực; nếu OOM ghi slot thất bại và sửa tài nguyên có lý do trong budget.
5. Review contact/camera/identity và ghép toàn clip với tiếng gốc. Chỉ rerender unit lỗi, không dùng test count thay chất lượng.

Trần10 phiên bản và mọi budget trong NEXT_HERMES_DEMO_PROMPT vẫn giữ. `batch_size=1` chỉ số video độc lập ở sampler/latent; các IMAGE batch theo thời gian và `RebatchImages` giữ đúng frame count, không sửa tất cả batch_size thành1. Loop continuation cho các đoạn liên tiếp của cùng timeline phải có span/pass count hữu hạn, không seed sweep hay phương án ẩn.

Không chạy thêm upstream sample bên ngoài ledger. C01 dùng source đã chốt; không đổi sang chân dung dễ để báo thành công. Nếu core model vẫn không đáp ứng sau corrections có chứng cứ, nộp clip tốt nhất, lỗi cụ thể và giới hạn kỹ thuật; không mở thêm project code trong cùng lượt.
