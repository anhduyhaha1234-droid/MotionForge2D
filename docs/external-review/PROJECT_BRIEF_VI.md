# MotionForge 2D — Hồ sơ BA và bàn giao thẩm định kỹ thuật

Ngày chốt hồ sơ: **29/09/2026**, cutoff snapshot read-only **17:12 +07**. Đối tượng đọc: BA, developer tiếp quản, technical lead và reviewer độc lập.
Điểm vào hiện hành của gói bàn giao là [START_HERE_EXTERNAL_REVIEW](../../START_HERE_EXTERNAL_REVIEW.md); [hướng dẫn developer](DEVELOPER_ONBOARDING.md) mô tả môi trường và giới hạn tái lập.
Hồ sơ này mô tả yêu cầu sản phẩm và đối chiếu với source; không biến danh sách module hoặc số test xanh thành chứng nhận sản phẩm.

## 1. Kết luận bàn giao và phạm vi snapshot

| Thuộc tính | Giá trị có thẩm quyền trong hồ sơ này |
|---|---|
| Candidate tích hợp được đọc | `a52fca897906fd61a088016dd802718fdf06d217` |
| Trạng thái review độc lập gần nhất | **CHANGES_REQUESTED / NOT_APPROVED / NOT_CLOSED** |
| Chất lượng sản phẩm đã được chấp nhận | **QUALITY_ACCEPTED=0** |
| Kết quả engineering do bên triển khai báo | 884 passed / 3 skipped; không phải suite reviewer chạy lại |
| Demo GPU quan sát được | App đã submit, render ba chunk và stitch publication thật |
| Điều chưa được chứng minh | Reskin sát nguồn đạt chất lượng và chuỗi người dùng hoàn chỉnh đến S12 export |
| Correction C11/C15/C22 ngày 29/09 | Được lưu riêng để thẩm định; **chưa được reviewer xác nhận đã kiểm chứng hoặc tích hợp vào candidate trên** |

Mốc đánh giá là commit cụ thể, không phải tên thư mục, tên task hay trạng thái “xong” của một phiên làm việc.
Snapshot correction, manifest bàn giao và evidence đi kèm cần được đọc theo phân loại của gói bàn giao; không cộng kết quả của chúng vào candidate khi chưa có kiểm chứng.
Các đường dẫn máy cá nhân trong tài liệu lịch sử chỉ là provenance cũ, không phải yêu cầu cài đặt cho developer mới.
C11 có commit riêng `e3b130149c84b193736d14d00a26363bdb279dee`, ghi nhận lúc 17:11 +07; ref bàn giao `review/20260929-c11-correction`. Commit này chưa nằm trong candidate `a52fca8`.
Delta Manager báo lúc 17:10 +07: `ATTACH_ORIGINAL_AUDIO` D0 complete; S12 nhận submit 202 cho run `7da2cb5f-2ea0-414a-a2db-8803ee8f0f59`, render ba chunk rồi **FAILED / PUBLICATIONERROR**, validation `['av_policy']`; hai QC job completed, `qc_item=0`.
Đây là tiến độ **Manager-reported, pending independent reproduction**: đã có export attempt mới, nhưng chưa có accepted export; zero QC items không tự chứng minh pass nội dung.

## 2. Bài toán và kết quả người dùng cần

MotionForge 2D là công cụ local-first biến một video nguồn thành phiên bản có nhân vật, đồ vật và artwork mới, trong khi giữ cấu trúc kể chuyện và chuyển động của nguồn.
Người dùng muốn tạo hoặc chọn bộ cast một lần, lưu vào thư viện, pin bộ đó cho một series và dùng lại cho nhiều video.
Ứng dụng cần giúp người dùng đi từ import, phân tích, chọn cast, duyệt ảnh neo, render, kiểm tra và sửa có mục tiêu đến xuất file nghe/xem được.
Một file MP4 giải mã được chỉ chứng minh file hợp lệ. Thành công nghiệp vụ đòi hỏi nội dung, vai trò và hành động còn đúng.

Các bất biến cần giữ khi thay appearance:

- Chủ thể và loại đối tượng: cảnh giấy/chứng nhận vẫn là cảnh giấy/chứng nhận; người vẫn giữ đúng vai.
- Hành động và sự kiện: động tác mở sách, ký giấy và các chuyển tiếp diễn ra đúng diễn biến nguồn.
- Contact: tay đang giữ sách/bút tiếp tục tiếp xúc đúng vật, đúng người sở hữu.
- Occlusion: thứ tự trước/sau và phần bị che còn nhất quán, kể cả người chỉ hiện một phần ở mép khung.
- Camera: pan, zoom và bố cục theo nguồn; không coi prompt văn bản là bằng chứng camera đã khóa.
- Timing: ánh xạ frame/timebase, cut và tổng thời lượng có chứng cứ; đủ số frame chưa chứng minh đúng boundary.
- Audio: giữ âm thanh gốc theo lựa chọn đã chốt, đồng bộ với hình trong file xuất cuối.
- Appearance: cast đích phải được thay đúng và nhất quán; không dùng nhân vật giống nguồn để đạt một gate kỹ thuật.

Xuất 4K là khả năng đầu ra cần ghi rõ provenance và phương pháp upscale; tăng kích thước khung không chứng minh nội dung sinh ở độ phân giải 4K gốc.
Không có cam kết một lần generation luôn đạt. Quy trình phải phát hiện sai, chỉ ra vị trí và cho phép sửa trong phạm vi nhỏ.

## 3. Nhóm người dùng và trách nhiệm

| Vai trò | Nhu cầu chính | Quyết định/đầu ra họ chịu trách nhiệm |
|---|---|---|
| Người làm nội dung | Nhập video, chọn cast, xem kết quả, xuất và tái dùng cho series | Reference/cast đích, duyệt anchor và nội dung cuối |
| Người phụ trách artwork/cast | Tạo reference đủ góc nhìn, kiểm tra vai và nhận dạng | Pack version có provenance, asset và trạng thái sẵn sàng |
| QA/reviewer sản phẩm | So nguồn với output tại các sự kiện quan trọng | Verdict có frame, role, measurement và evidence; không suy từ test count |
| Developer tiếp quản | Hiểu source, tái lập failure, nối đúng producer và public path | Bản sửa có phạm vi, kiểm thử âm tính và chứng cứ tích hợp |
| Technical lead/đóng gói | Kiểm soát dependency, dữ liệu, restart và vận hành | Cài sạch, dependency pin, vòng đời tiến trình và khả năng bàn giao |

Đây là mô hình vai trò nghiệp vụ để phân công công việc, không phải tuyên bố hệ thống đã có tài khoản, phân quyền hay tính năng cộng tác nhiều người.

## 4. Thuật ngữ và mô hình dữ liệu

| Thuật ngữ | Ý nghĩa nghiệp vụ | Mốc source liên quan |
|---|---|---|
| Workspace / Channel / Project | Các container tổ chức nội dung; batch hiện coi project là series | [models.py](../../app/persistence/models.py) |
| VideoItem / Scene | Video nguồn và các scene có phạm vi thời gian | [videos.py](../../app/persistence/videos.py), [models.py](../../app/persistence/models.py) |
| ObjectRole / Occurrence / Segment | Vai xuyên shot, lần xuất hiện và đoạn theo dõi; vai không đồng nghĩa một bbox | [object_intelligence.py](../../app/persistence/object_intelligence.py) |
| Character / PackVersion / Asset | Nhân vật, phiên bản pack được pin và các asset của phiên bản | [characters.py](../../app/persistence/characters.py) |
| Cast mapping / Series snapshot | Gắn vai với pack version; snapshot cast dùng lại cho series | [project_cast.py](../../app/persistence/project_cast.py) |
| Source facts | Bằng chứng thời gian, role track, camera, contact và occlusion của nguồn | [source_interaction_facts.py](../../app/services/source_interaction_facts.py) |
| SceneUnit | Khái niệm BA: đơn vị nội dung đủ để giữ hành động và quan hệ; không phải tên class/table đã có | [shot_reskin.py](../../app/schemas/shot_reskin.py), [shot_reskin_plan.py](../../app/services/shot_reskin_plan.py) |
| ShotPlan / PlannedShot / ElementUnit | Các mô hình code liên quan khi hiện thực SceneUnit | [shot_reskin.py](../../app/schemas/shot_reskin.py), [shot_reskin_plan.py](../../app/services/shot_reskin_plan.py) |
| Anchor | Ảnh neo toàn cảnh hoặc asset neo được pin, đúng cast và được duyệt trước render theo quy trình đích | [shot_anchor_jobs.py](../../app/workflow/shot_anchor_jobs.py) |
| Structural lock / ApplyCheckpoint | Chốt cấu trúc và trạng thái duyệt có identity để render/recompute | [structural_lock.py](../../app/persistence/structural_lock.py), [reskin_config.py](../../app/persistence/reskin_config.py) |
| Artifact / ArtifactOwner | Bytes có digest, vị trí quản lý và chủ sở hữu nghiệp vụ | [artifacts.py](../../app/persistence/artifacts.py) |
| Job / Attempt / Lease / Receipt | Công việc bền vững, lần thử, quyền xử lý và biên nhận phục vụ restart/replay | [jobs.py](../../app/persistence/jobs.py), [durable_worker.py](../../app/workflow/durable_worker.py) |
| FullApply publication | Kết quả render/ghép được publish ở tầng apply | [s10_full_apply.py](../../app/persistence/s10_full_apply.py) |
| QC / S12 export | Kiểm tra nội dung/đầu ra và lần xuất cuối có gate riêng | [qc_items.py](../../app/persistence/qc_items.py), [s12_export.py](../../app/persistence/s12_export.py) |

Pack đã dùng để duyệt hoặc render cần được đối xử như phiên bản bất biến: sửa artwork tạo phiên bản mới và làm rõ những checkpoint/cache nào mất hiệu lực.
Không dùng tên file hoặc nhãn “final” làm identity. Cần digest, chủ sở hữu, source binding, revision và trạng thái chấp nhận.

## 5. Hành trình đích và trách nhiệm của ComfyUI

1. Tạo/chọn project; upload video qua public API; nhận source artifact có hash và metadata.
2. Analyze tạo time map có thẩm quyền, scene/cut, role tracks và các sự kiện/contact/occlusion cần bảo toàn.
3. Người dùng sửa phân vai nếu cần; chọn hoặc tạo reference trong thư viện; pin cast pack cho project/series.
4. Compile SceneUnit theo nội dung thực tế; chọn graph/control phù hợp cho từng unit.
5. Tạo anchor đúng cast/toàn cảnh; hiển thị nguồn và anchor để người dùng duyệt; lưu quyết định và hash.
6. Chạy preview/apply; worker dùng manifest đã pin, ghi attempt/receipt và thu output artifact thật.
7. Producer quan sát output lấy dữ liệu từ bytes đúng run; comparator đối chiếu với source facts đã chốt.
8. Người dùng xem lỗi theo frame/role; sửa đúng dependency bị lỗi; giữ kết quả không liên quan còn hợp lệ.
9. Gắn audio, thực hiện gate export, xuất S12; kiểm tra file cuối và reopen sau restart.
10. Khi một video đạt, chạy ít nhất hai video cùng cast qua batch render/export và đo throughput thực.

ComfyUI là runtime thực thi graph cho từng SceneUnit; app giữ quyền quản lý source, cast, duyệt, job, identity, QC và export.
Ba nhóm xử lý cần được đánh giá theo failure: người/hành động; đồ vật/giấy/background với camera; tương tác nhiều vai và occlusion.
Không ép mọi unit dùng prompt hoặc graph dành cho người. Với chữ/giấy, artwork mới và transform/composite có thể phù hợp hơn việc tái sinh toàn bộ bằng model animation người.
Đây là hướng thiết kế và kiểm chứng cần hoàn thiện; không phải xác nhận cả ba loại đường chạy đã được hỗ trợ trong app hiện tại.
Hard cut phải theo nguồn; chia chunk hoặc subwindow có overlap không được tự tạo jump cut để che lỗi chuyển động.

## 6. AS-IS đối chiếu với sản phẩm đích

| Phần | Có trong candidate | Giới hạn hiện tại / bằng chứng còn thiếu |
|---|---|---|
| Upload/analyze | Public upload/analyze và UI gọi chuỗi này đã tồn tại | Demo R5 dùng SQL seed, chưa chứng minh hành trình mới đi qua bridge đầy đủ |
| Thư viện/cast | Persistence, asset ingest, pack, mapping và series snapshot | Chưa chứng minh cast đích được dùng đúng xuyên toàn bộ demo thực |
| Source facts/time map | Compiler/producer/schema có code | Demo có boundary lệch; cần kiểm bytes tại cut và event |
| Anchor | Workflow job và handler đã có | Chưa có public caller được tìm thấy trong API cho build anchor; thiếu UI build anchors |
| Comfy engine | Dependency pin, adapter, graph và worker path có code | Thiếu bootstrap Comfy portable đầy đủ; chất lượng vẫn chưa được chấp nhận |
| FullApply | Render thật ba chunk và stitch publication | “Render complete” chưa có nghĩa đúng nội dung hoặc S12 complete |
| QC | Producer quan sát, detector, comparator, durable check infrastructure | Năm comparator mới chưa có production caller; seed mask không chứng minh observation thật |
| Audio/S12 | Code remux, preflight, job và publication gate tồn tại | Snapshot độc lập buổi sáng chưa có S12 run; Manager chiều báo export failed `av_policy`, chưa có accepted export |
| UI journey | Điều hướng, trạng thái và dependency blockers đã bổ sung | Chưa có browser E2E của toàn vertical slice; có khoảng trống context/anchor |
| Batch | Service/API batch export, restart/control và panel | Chưa batch render; panel chưa mount trong cây giao diện |
| Package | Staged Windows build/lifecycle đã thử trên dev host | Clean Windows/human acceptance NOT_RUN; còn dependency ngoài |

Không kết luận “thiếu import” từ demo đi đường vòng: [upload_video](../../app/api/routes/projects.py) và [ImportAnalyzePanel](../../frontend/src/components/ImportAnalyzePanel.tsx) là đường có sẵn cần thử trước.
Không cộng điểm hoàn thành dựa trên số component. Một chuỗi quan trọng thiếu public wiring vẫn là khoảng trống sản phẩm.

## 7. Kiến trúc hiện tại và nơi developer bắt đầu đọc

```text
Next.js UI -> FastAPI routes -> service/workflow -> durable Job/SQLite
                                      |                 |
                                      |          worker + lease/reconcile
                                      v                 v
                            managed artifacts <-> render adapters
                                                      |       |
                                                legacy     mf_comfy -> ComfyUI
                                      |
                       output observations -> QC -> audio/S12 -> final artifact
```

| Ranh giới | Module chính | Điểm cần giữ khi sửa |
|---|---|---|
| App/lifecycle | [app.py](../../app/api/app.py), [lifecycle.py](../../app/lifecycle.py) | Bootstrap rõ ràng; reconcile trước poll; stop/join có giới hạn |
| Config và lưu trữ | [config.py](../../app/config.py), [deps.py](../../app/api/deps.py) | Root tuyệt đối, nhất quán giữa API/worker/artifact; QA tách dữ liệu người dùng |
| DB/migration | [engine.py](../../app/persistence/engine.py), [migrations](../../migrations) | SQLite foreign keys, revision/migration và backup theo lifecycle |
| Import bridge | [projects.py](../../app/api/routes/projects.py), [analyze_orchestrator.py](../../app/workflow/analyze_orchestrator.py) | Legacy `/api/projects` và durable `/api/v2` cùng tồn tại; không bỏ bridge |
| Role/cast/source | [source_role_tracks.py](../../app/services/source_role_tracks.py), [project_cast.py](../../app/api/routes/project_cast.py) | Role, pack/version và source facts phải giữ binding |
| Plan/render/cache | [s10_chunk_plan.py](../../app/services/s10_chunk_plan.py), [shot_reskin_executor.py](../../app/services/shot_reskin_executor.py), [shot_reskin_cache.py](../../app/services/shot_reskin_cache.py) | Per-shot prompt/anchor; hash và attempt identity; không repost mơ hồ |
| Engine/process | [comfy.py](../../app/adapters/media_engine/comfy.py), [build_mf_comfy_dependency.py](../../scripts/build_mf_comfy_dependency.py) | Package/graph/model pin, live epoch, lease và output provenance |
| QC/evidence | [rendered_observations.py](../../app/services/rendered_observations.py), [qc_checks](../../app/services/qc_checks), [qc_checks_handler.py](../../app/workflow/qc_checks_handler.py) | Invalid/unknown/missing measurement không được đổi thành pass |
| Export | [s12_export](../../app/services/s12_export), [s12_export_jobs.py](../../app/workflow/s12_export_jobs.py) | Publication apply và file export cuối có gate khác nhau |
| UI | [app routes](../../frontend/src/app), [features](../../frontend/src/features), [api.ts](../../frontend/src/lib/api.ts) | Project/video context phải xuyên navigation và reload |

Backend là Python/FastAPI, SQLAlchemy/Alembic và SQLite; frontend là Next.js/React, React Query, Zustand và Konva.
Các runtime nặng gồm FFmpeg, segmentation và ComfyUI/model weights. Source clone không bao gồm toàn bộ môi trường, checkpoint hay media riêng.
Hệ thống hiện phục vụ local loopback với Origin allowlist; mô hình account/authentication đa người dùng không nằm trong nghiệm thu này.

## 8. Yêu cầu chức năng và điều kiện nghiệm thu

Bảng dưới là **yêu cầu đích**. Tồn tại một API/module không đồng nghĩa FR đã đạt; phải có evidence trên candidate cụ thể.

| ID | Yêu cầu | Điều kiện nghiệm thu đo/quan sát được |
|---|---|---|
| FR-01 | Import bền vững | Upload qua UI/API, artifact có hash; restart vẫn mở đúng video; không SQL seed |
| FR-02 | Phân tích và time map | Source có metadata/timebase, cut và mapping; kiểm bytes quanh mọi boundary của fixture |
| FR-03 | Phân loại nội dung | Người, prop, giấy và background có vai đúng; cảnh giấy không bị đổi thành người |
| FR-04 | Thư viện reference tái dùng | Asset ingest/generate có provenance; trạng thái thiếu reference hiển thị rõ và chặn bước phụ thuộc |
| FR-05 | Pack version bất biến | Render pin version/hash; cập nhật tạo version mới; run cũ vẫn truy được asset đã dùng |
| FR-06 | Cast nhất quán series | Hai video dùng cùng snapshot/pack; mapping lệch bị chặn với reason cụ thể |
| FR-07 | Compile SceneUnit | Mỗi unit có source span, roles, facts và graph/control theo nội dung; thiếu input không submit |
| FR-08 | Anchor đúng cast và duyệt | UI tạo/xem/duyệt anchor; receipt liên kết source/cast/graph; anchor stale chưa được render |
| FR-09 | Per-unit generation | Mỗi unit dùng prompt/reference/control đã pin; có negative control chứng minh không dùng chung prompt sai |
| FR-10 | Giữ action/contact | Event mở sách/ký giấy và chủ sở hữu vật đúng trong cửa sổ frame nguồn; sai phải non-pass |
| FR-11 | Giữ occlusion/coverage | Thứ tự trước/sau, người mép khung và cut nội bộ được kiểm bằng output thật |
| FR-12 | Giữ camera/timing | Pan/zoom/cut/PTS được đối chiếu; đủ frame nhưng lệch boundary phải non-pass |
| FR-13 | Observation thật | Producer đọc bytes output đúng run/hash sau render; mask dựng trước render không dùng làm acceptance |
| FR-14 | QC fail-closed | Invalid, unknown và thiếu measurement chặn acceptance/export theo gate; không zero-item pass giả |
| FR-15 | Review có vị trí | Mỗi issue có role, frame/span, reason và evidence mở được từ context project/video |
| FR-16 | Sửa có mục tiêu | Thay một dependency chỉ invalidate phần phụ thuộc; hash phần không liên quan được giữ và kiểm lại |
| FR-17 | Cache/restart/replay | Cùng identity tái dùng đúng receipt; crash sau submit không tự POST lần hai; output sai hash bị từ chối |
| FR-18 | Cancel/retry an toàn | Cancel đúng owner/attempt; output muộn không publish; retry có identity và lịch sử rõ |
| FR-19 | Audio cuối | S12 output có stream audio theo yêu cầu, thời lượng/đồng bộ được đo và nghe kiểm tại cut/event |
| FR-20 | Export trung thực | Codec/dims/frame/timebase/publication được kiểm; native/upscale 4K được ghi đúng provenance |
| FR-21 | Hành trình UI đầy đủ | Import→cast→anchor→apply→QC→audio→export thực hiện không script seed; reload giữ context |
| FR-22 | Batch render/export | Ít nhất hai video khác nhau cùng cast hoàn tất; lỗi một video không xóa/chặn mất kết quả video kia |
| FR-23 | Đóng gói cài sạch | Máy Windows sạch thực hiện check/start/status/stop/reopen; thiếu dependency có blocker rõ |
| FR-24 | Chỉ số vận hành thật | Ghi cold/warm, peak VRAM/RAM và accepted seconds; chưa đo ghi unmeasured, không suy throughput |

Threshold hình ảnh/chuyển động cần được hiệu chuẩn trước trên control và failure fixture, gắn phiên bản và không nới sau khi thấy candidate fail.
Đối với yêu cầu thị giác không có phép đo đủ tin cậy, giữ trạng thái unknown và quyết định review có evidence; không bịa độ chính xác phần trăm.

## 9. Blocker, biểu hiện và giả thuyết nguyên nhân

| ID | Quan sát của review 29/09 | Nguyên nhân/công việc cần kiểm chứng |
|---|---|---|
| B-01 | R5 dùng prompt BOOK cho mọi shot; cảnh giấy/ký biến thành người đọc sách | Đường app không mang đủ per-unit source facts/reference/control từ proof; sửa binding trước đổi model |
| B-02 | Demo dựng mask rectangle trước render và nhân một ảnh thành nhiều pose slot | Seed phục vụ plumbing bị dùng như bằng chứng nội dung; thay bằng producer output đúng run |
| B-03 | Năm comparator mới chỉ có definition trong app, chưa có caller production | Nối producer→composer/orchestrator→durable gate; tái lập invalid/unknown propagation |
| B-04 | Demo seed source/scene/roles/packs trực tiếp; thiếu thao tác build anchors | Thử public upload/analyze hiện có; hoàn thiện bridge/context/anchor, không tạo queue/API trùng vô cớ |
| B-05 | Nguồn demo đổi cảnh tại 121/241/343; manifest ở 120/240 và thiếu cut cuối | Chuẩn hóa source time map theo decoded bytes; xử lý audio/timebase riêng; không sửa nguồn cho khớp manifest sai |
| B-06 | Sách không mở, cast/coverage chưa đúng nhưng gate từng được giảm thành backlog | Khôi phục yêu cầu nguồn đã chốt; không xin miễn trừ cho mất hành động cốt lõi |
| B-07 | Batch mới export; panel chưa mount | Hoàn tất một vertical slice đạt trước, sau đó nối render và UI batch |
| B-08 | Package chỉ chạy dev host; runtime/dependency ngoài còn thiếu tài liệu | Bổ sung bootstrap/dependency reproducibility và nghiệm thu clean Windows riêng |

R5 là render thật nhưng publication có hash trùng R4 thất bại. Sửa plumbing không được báo là cải thiện pixel nếu bytes và quan sát không đổi.
Snapshot độc lập buổi sáng của R5 chưa submit QC/S12, nên publication video-only không chứng minh audio fix thất bại; báo cáo chiều về export failed `av_policy` là evidence mới cần tái lập riêng.
Không suy attach-audio job completed đồng nghĩa final export đúng audio policy; phải kiểm output và validation của đúng export attempt.
Rủi ro invalid QC thành zero-item pass cần isolated repro: review nêu đường truyền status có vấn đề, chưa khẳng định đã quan sát false-pass readiness live.
Correction C11/C15/C22 được giữ như candidate riêng để tìm nguyên nhân và diff; chưa giải quyết các blocker trong bảng chỉ bằng việc có commit mới.

## 10. Mốc hoàn thiện đề xuất và Definition of Done

| Mốc | Phạm vi | Exit criterion |
|---|---|---|
| M0 — Nhận bàn giao tái lập được | Clone, dependency pin, root tách, inventory và source/evidence boundary | Developer mới đọc/run kiểm tra tối thiểu; blockers ghi rõ; không cần đường dẫn máy tác giả |
| M1 — Chốt nguồn và cast | Source hash/time map, role facts, reference/pack và anchor | BOOK/TURN/OCC có source binding đúng; anchor đích được duyệt; không pose/mask giả |
| M2 — Đóng từng failure nội dung | Per-unit graph/control, output observations và comparator production | Có control pass và failure non-pass trên media thật; action/contact/camera đúng theo fixture |
| M3 — Một video qua app | Toàn hành trình public UI/API đến audio/S12, restart/reopen | Không SQL seed; final artifact mở/nghe được; FR liên quan có evidence và quality verdict |
| M4 — Series và hiệu năng | Hai video cùng cast, batch render/export và lỗi/retry | Bytes/identity độc lập; không mất output khác; chỉ số accepted output có mẫu thật |
| M5 — Bàn giao chạy sạch | Package, model/runtime prerequisites và clean-host/human run | Cài/khởi động/dừng/reopen được trên host sạch; S12 closure được review riêng |

Một hạng mục chỉ Done khi có commit, trigger tái lập, expected/actual, evidence phù hợp tầng và kiểm thử âm tính liên quan.
Toàn sản phẩm chỉ được chấp nhận khi quality verdict và hành trình người dùng đạt; test unit/CI hoặc GPU render success là các bằng chứng riêng.
Không ấn định ngày hoặc tỷ lệ hoàn thành từ số task. Ước lượng lịch sau khi reviewer tái lập các blocker trọng yếu và chốt dependency còn thiếu.

## 11. Checklist cho reviewer tiếp quản

- [ ] Xác nhận commit candidate, nhánh dependency Comfy và snapshot correction riêng; không trộn tree chưa tích hợp.
- [ ] Đọc source tại các link trên; README cũ là tài liệu spike, không phải mô tả đầy đủ sản phẩm hiện tại.
- [ ] Phân biệt test do bên triển khai báo, kiểm tra reviewer tự chạy, GPU evidence và human acceptance.
- [ ] Dùng runtime root mới; kiểm DB/artifact path trước khi khởi động; giữ dữ liệu nguồn bất biến.
- [ ] Tái lập upload→analyze bằng public path; kiểm durable rows/artifacts tồn tại sau restart.
- [ ] Kiểm đúng cast/pack, source span, prompt, graph, anchor và các hash trong manifest từng unit.
- [ ] So BOOK mở sách, TURN giấy/camera, OCC ký/contact/cut trên source và output đúng frame.
- [ ] Chứng minh QC đọc output thật; missing/invalid/unknown không trở thành pass hoặc zero-issue acceptance.
- [ ] Kiểm final S12 bytes/audio/provenance; không dùng bản copy publication gắn tên demo_final làm bằng chứng export.
- [ ] Kiểm restart/cancel/retry/cache bằng identity, không chỉ số lượng job hoặc exit code wrapper.
- [ ] Sau một video đạt, kiểm hai video cùng cast và batch lỗi cục bộ; đo accepted seconds.
- [ ] Ghi clean Windows/human run độc lập; không suy từ dev host hoặc clean venv.

## 12. Cách đọc tài liệu lịch sử và evidence

Ưu tiên entry point bàn giao, snapshot manifest, source ở commit pin và review độc lập được đóng gói cùng hồ sơ.
[README gốc](../../README.md), [frontend README](../../frontend/README.md) và các tài liệu sprint vẫn hữu ích để hiểu lịch sử, nhưng có giả định setup/phạm vi đã cũ.
[Model profiles](../../app/media_workflows/model_profiles.json) và [demo packaging](../../packaging/demo/README.md) phân biệt benchmark, eligibility, quality acceptance và model ngoài gói.
Không đưa khóa, token, DB người dùng, media riêng hoặc raw session log vào gói source để lấp khoảng trống tái lập; dùng manifest/evidence đã được chọn lọc và quyền truy cập riêng khi cần.
