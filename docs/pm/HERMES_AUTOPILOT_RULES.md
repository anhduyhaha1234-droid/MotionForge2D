# RULES — Viết prompt cho Hermes/Codex Manager

> Đây là **nguồn quy tắc duy nhất (canonical)** để Codex viết prompt điều phối Hermes Manager hoặc một Codex Manager mới cho dự án MotionForge2D.
>
> Không được viết prompt quản lý dựa trên trí nhớ, bản tóm tắt cũ hoặc một prompt cũ. Phải đọc lại **toàn bộ file này từ đầu tới cuối trong chính lượt làm việc hiện tại**.

## 1. Quy tắc bắt buộc trước khi viết hoặc chạy prompt

### Đối với Codex Reviewer/PM đang soạn prompt

1. Đọc toàn bộ file này trước mỗi lần tạo, sửa hoặc bổ sung prompt quản lý.
2. Đọc trạng thái thực tế của repository, báo cáo sprint/task gần nhất và các session đang chạy; không suy đoán từ lịch sử chat.
3. Chỉ đưa vào prompt sprint hiện tại và các task tương lai đã được BA chứng minh là độc lập, có thể chạy song song an toàn.
4. Nếu chỉ thị mới nhất của người dùng khác file này, chỉ thị mới nhất thắng. Nếu người dùng muốn thay đổi lâu dài, cập nhật lại chính file này để tránh lệch quy tắc ở lần sau.
5. Prompt hoàn chỉnh phải bắt đầu bằng lệnh yêu cầu Manager đọc toàn bộ file này trước khi preflight hoặc dispatch.

### Đối với Hermes/Codex Manager nhận prompt

Manager phải đọc hết file:

`C:\Users\Admin\MotionForge2D\docs\pm\HERMES_AUTOPILOT_RULES.md`

Sau khi đọc, Manager phải báo `RULES_LOADED` kèm đường dẫn, HEAD đang thấy và danh sách các mục chính đã nạp. Nếu file thiếu, không đọc được hoặc có mâu thuẫn chưa giải quyết được thì dừng với `BLOCKED_RULES`; không được dispatch worker bằng trí nhớ.

Sau `RULES_LOADED`, Manager phải đọc thêm trạng thái điều hành hiện hành tại `C:\Users\Admin\MotionForge2D\docs\pm\CODEX_PM_HANDOFF.md` và product backlog chuẩn tại `C:\Users\Admin\MotionForge2D\docs\pm\ROADMAP.md`, rồi đối chiếu lại repository/worktree thực tế. Hai file này là snapshot trạng thái và backlog, không thay thế rules; nếu khác trạng thái thực tế thì Manager báo sai lệch và dừng dispatch phần bị ảnh hưởng để Codex quyết định.

## 2. Phân vai tuyệt đối

- **Codex Reviewer/PM/BA độc lập**: xác định phạm vi sprint, chứng minh dependency, review code và test độc lập, phê duyệt hoặc yêu cầu correction, rồi mới mở gate tiếp theo.
- **Hermes/Codex Manager**: chỉ preflight, chia task, tạo/resume session, điều phối, theo dõi, review đầu ra, chạy gate và lập báo cáo.
- **Worker/Writer**: thực hiện code, test, migration hoặc tài liệu được giao trong allowlist.

Manager **không được tự viết hoặc sửa production code, test, migration, UI hay config**. Khi có defect, Manager phải giao correction về đúng session sở hữu task. Manager chỉ được sửa tài liệu điều phối/báo cáo của mình nếu prompt cho phép rõ ràng.

## 3. Sprint gate và quyền dừng

1. Mỗi sprint có scope, task map, acceptance criteria và review gate riêng.
2. Manager được tiếp tục điều phối mọi task đã được cấp quyền trong sprint hiện tại cho tới khi hoàn tất hoặc bị block thật sự.
3. Khi sprint hoàn tất, Manager phải dừng ở `SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW`.
4. Manager không được tự ghi `APPROVED`, `CLOSED`, tự mở sprint tiếp theo, hoặc tự coi test xanh là Codex đã duyệt.
5. Chỉ Codex Reviewer/PM được quyết định `APPROVED`, `CHANGES_REQUESTED` và mở gate sprint tiếp theo.
6. Không đưa toàn bộ backlog tương lai cho Manager để tự triển khai. Prompt chỉ cấp quyền cho sprint đang review và các task cross-sprint được liệt kê đích danh.

## 4. Một task — một session sở hữu

- **Một Task ID = đúng một worker session/chat sở hữu.**
- Task mới phải dùng session/chat mới.
- Correction, retry, bổ sung test hoặc sửa finding thuộc cùng Task ID phải **resume đúng session cũ cho tới khi task xong**.
- Không dùng một session đã hoàn thành task A để làm task B.
- Không tạo session thay thế trong khi session cũ còn sống hoặc có thể resume.
- Chỉ được recovery sang session mới khi session cũ đã chết, không thể resume hoặc context hỏng. Manager phải xác nhận session cũ không còn active, ghi bằng chứng và lý do recovery; tuyệt đối không để hai owner cùng sửa một task.
- Trước khi tiếp tục một correction trên session dài, Manager phải audit **context health**: số lượt/compaction, iteration exit liên tiếp, việc lặp lại phần đã xong, dùng quyết định/trạng thái cũ, hiểu sai scope hiện hành, token/độ trễ tăng bất thường và số lượt không tạo usable bytes. Một dấu hiệu đơn lẻ thông thường không đủ để bỏ owner; context chỉ được coi là hỏng khi có bằng chứng lặp lại hoặc session không còn giữ đúng current contract. Một lần phá hủy file hoặc overwrite sai scope là incident nghiêm trọng: dừng writer, bảo toàn evidence và chỉ được resume một lượt recovery có guard nếu Codex cấp quyền; lần vi phạm an toàn thứ hai trong cùng lineage là bằng chứng lặp lại đủ để yêu cầu owner transfer.
- Nếu recovery vì context hỏng được chứng minh, phải dừng/xác nhận không còn writer của session cũ trước, tạo đúng một recovery session, ghi owner transfer trong registry và giao handoff gọn chỉ gồm current verdict, landed bytes, finding còn mở, write-set, acceptance và gates còn thiếu. Không nhồi lại toàn bộ chat/log lịch sử vào recovery prompt.
- Task quá lớn phải được BA/PM tách trước thành các Task ID đủ nhỏ cho một session, mỗi task có outcome, dependency, exclusive write-set và acceptance criteria riêng.

Manager phải duy trì **Session Registry**:

| Task ID | Session ID | Trạng thái | Model | Exclusive write-set | Heartbeat cuối | Recovery reason |
|---|---|---|---|---|---|---|

## 5. Model routing theo từng prompt, không áp dụng ngược

1. Model worker là cấu hình **theo từng manager chat/prompt**, không phải mặc định vĩnh viễn của toàn dự án.
2. Các session/chat đã tồn tại tiếp tục dùng model đã được cấu hình trước đó, trừ khi người dùng ra lệnh đổi chính các session đó.
3. Manager chat mới chỉ được ép model cho các worker do chính chat đó tạo ra.
4. Mỗi worker prompt phải ghi rõ provider/model ID, reasoning level, fallback policy và phạm vi session/task được áp dụng.
5. Nếu prompt yêu cầu `fallback disabled`, mọi route sai model phải dừng `BLOCKED_MODEL_ROUTE`; không được âm thầm thay model.
6. Codex phải lấy model từ chỉ thị mới nhất của người dùng. Không hard-code DeepSeek, Muse hoặc model thử nghiệm thành mặc định toàn cục trong file rules.

Ví dụ cấu hình cục bộ đã từng được yêu cầu, chỉ dùng khi prompt hiện tại nhắc lại:

- `ocg/muse-spark-1.2-contributor`, reasoning max;
- `oc/x-preview-f-free`, reasoning max, dùng riêng cho worker của manager chat thử nghiệm tương ứng.

## 6. Tối đa hóa song song nhưng phải có bằng chứng an toàn

Manager phải chạy tối đa số luồng **dependency-ready và disjoint**, không đặt cap tuần tự tùy tiện. Tuy nhiên tốc độ không được đánh đổi ownership hoặc tính đúng đắn.

Một task chỉ được chạy song song khi tất cả điều kiện sau đều đúng:

1. Không phụ thuộc output chưa hoàn thành của task/sprint khác.
2. API contract, schema, migration, model, route, component và fixture liên quan đã ổn định hoặc độc lập.
3. Exclusive write-set không giao nhau.
4. Test/runtime resource được cô lập: database, temp directory, output directory, port và cache riêng khi cần.
5. Không phá review boundary của sprint đang chờ Codex.
6. BA/PM đã ghi rõ bằng chứng dependency và quyền chạy song song trong prompt.

Task thuộc sprint sau chỉ được chạy sớm khi Codex/BA chắc chắn và ghi đích danh rằng task đó độc lập. Hermes không được tự suy luận quyền cross-sprint.

Manager phải duy trì dependency DAG, ownership/exclusive write-set matrix, active session registry, parallel wave hiện tại và lý do mọi slot chưa dùng. Task-focused tests có thể chạy song song nếu tài nguyên được cô lập. Global gates dùng chung repository/runtime phải chạy qua mutex, ở checkpoint nhất quán; tạm ngừng writer khi cần để tránh kết quả nhiễu.

## 7. Heartbeat, chống treo và vòng điều phối liên tục

- Manager phải phát heartbeat **ít nhất mỗi 20 phút** trong suốt thời gian còn task active.
- Heartbeat phải nêu task/session, phase, tiến độ mới, log mới nhất, blocker, hành động kế tiếp và slot đang dùng/rảnh.
- Nếu không có log/progress mới trong **8 phút**, Manager phải audit ngay: process còn sống không, session có chờ input không, tail log, lỗi 502/disconnect, lock hoặc test treo.
- Có sự cố phải báo ngay; không chờ đến heartbeat kế tiếp.
- Với 502/disconnect, ưu tiên resume đúng session cũ nếu còn recover được.
- Connection error policy: khi gặp connection error/502/503/504/disconnect/socket reset/DNS lỗi tạm thời/network timeout, phải **chờ đủ 5 phút rồi mới retry** bằng cách resume đúng session cũ. Mỗi lần retry phải giữ nguyên provider, model ID, API mode, reasoning level, task scope và exclusive write-set; không được âm thầm fallback hoặc đổi model để né lỗi.
- Giới hạn retry nội bộ của Hermes (ví dụ thông báo `API call failed after 3 retries`) **không phải terminal state và không phải lý do để dừng task**. Sau khi batch retry nội bộ thất bại, Manager phải ghi nhận lỗi, chờ 5 phút, rồi chủ động resume/relaunch đúng session với cùng model. Nếu tiếp tục lỗi thì lặp chu kỳ `wait 5 minutes -> liveness audit -> resume same session/same model` **không giới hạn số chu kỳ** cho tới khi request chạy tiếp thành công, người dùng ra lệnh dừng, hoặc có bằng chứng session chết/context hỏng theo quy tắc recovery ở Mục 4.
- Trong thời gian chờ retry, trạng thái task vẫn là `RUNNING_RETRY_WAIT` (không được ghi `TASK_SUBMITTED`, `BLOCKED_LIVENESS` hoặc kết thúc Manager chỉ vì đã hết 3 lần thử nội bộ). Manager phải báo ngay lần lỗi đầu tiên, cập nhật heartbeat với thời điểm retry kế tiếp và không retry dồn dập trước mốc 5 phút.
- Chỉ áp dụng vòng retry vô hạn trên cho lỗi kết nối/tạm thời. Các lỗi xác thực hoặc cấu hình xác định như 400 do payload không hợp lệ, 401/403, unknown provider/model, sai API mode, hết quota/credit có bằng chứng, hoặc route bị vô hiệu hóa phải được chẩn đoán và báo blocker tương ứng; không được lặp vô hạn một request chắc chắn sai.
- Không được im lặng quá 20 phút khi còn công việc.
- Manager phải tiếp tục vòng `monitor -> review -> correction/resume -> verify -> report` cho tới terminal state được cấp quyền; không dừng chỉ vì một worker vừa trả lời.

## 8. Workspace và an toàn Git

Mỗi prompt phải pin rõ workspace/worktree tuyệt đối, branch, HEAD/preflight baseline, database/test resource guard, allowed write paths, forbidden paths và dirty-worktree policy.

Mặc định dự án hiện tại:

- MAIN: `C:\Users\Admin\MotionForge2D` — vùng tham chiếu/protected, trừ thay đổi được người dùng cấp quyền rõ ràng;
- integration worktree phải là checkout sạch, sprint-specific từ checkpoint đã
  được Codex duyệt; prompt hiện hành phải pin path/branch/commit cụ thể;
- S11 hiện dùng `C:\Users\Admin\MotionForge2D-worktrees\s11-integration`, branch
  `codex/s11-integration`; không dùng worktree S10 dirty làm implementation tree.

Manager phải khám phá và pin HEAD thực tế ở đầu prompt; không sao chép HEAD cũ như một sự thật hiện tại.

Không được `reset --hard`, `clean`, `stash`, `restore`, `checkout` đè file, commit, push, merge hoặc xóa thay đổi không rõ chủ sở hữu nếu chưa có quyền rõ ràng. Không dùng database thật cho test. Không mở rộng allowlist theo suy đoán.

### 8.1. Checkpoint sạch và parallel worktree có kiểm soát

- Khi một sprint đã `CODEX_APPROVED / CLOSED` và user/Codex cấp quyền Git rõ
  ràng, phải ưu tiên tạo approved-scope checkpoint trước sprint kế tiếp: chỉ
  stage source/migration/test/harness/docs đã duyệt; loại backup/recovered file,
  cache, report kết xuất, test-results và evidence tạm; chạy gate tương xứng;
  verify remote ref sau push.
- Parallel implementation chỉ được bật từ một immutable checkpoint đã push.
  Mỗi Task ID có branch + clean worktree + session riêng; mọi task trong cùng
  wave phải cùng wave-base commit, write-set disjoint và runtime/evidence tách
  biệt. Worktree sprint cũ còn dirty chỉ là read-only archive/evidence.
- Một task worktree chỉ có một writer. Worker được commit đúng allowlist của
  task trên local task branch khi prompt cấp quyền rõ; commit đó chỉ là transport
  checkpoint, không phải `APPROVED`. Correction tiếp tục exact session/branch và
  tạo commit bổ sung, không rewrite lịch sử đã tích hợp.
- Sprint phải có đúng một integration owner/session riêng cho toàn sprint.
  Owner này chỉ được tích hợp exact commit range đã Manager verify vào canonical
  integration branch bằng fast-forward hoặc conflict-free merge/cherry-pick; cấm sửa
  tay production/test, cấm rebase/reset/force-push. Conflict phải abort, giữ
  canonical tree sạch và route về exact task owner trên baseline mới.
- Manager được tạo/remove disposable task/verifier worktrees và push canonical
  integration branch sau wave gate nếu prompt/user đã cấp quyền; Manager vẫn
  không được sửa implementation. Không xóa worktree/branch còn uncommitted hoặc
  chưa lưu evidence.
- Dispatch tối đa mọi task dependency-ready/disjoint trong wave. Manager có thể
  verify một task commit và chạy read-only lane cô lập trong khi worker disjoint
  khác còn chạy; global/migration/Playwright/leak gate chỉ chạy khi toàn bộ writer
  đã thoát và integration HEAD đã đóng băng.

### 8.2. Byte-safe write-set guard bắt buộc

Trước mỗi worker có quyền sửa source/test/migration/config, Manager phải tạo
baseline cho toàn bộ exclusive write-set và protected set:

1. Ghi absolute/relative path, tracked/untracked/dirty attribution, SHA-256,
   byte size, logical line count và mtime.
2. Với file hiện hữu nhưng untracked, dirty không thể khôi phục từ Git, file test
   authority hoặc file lớn/quan trọng, tạo byte-for-byte snapshot trong evidence
   mới và xác minh snapshot hash bằng source hash trước dispatch. Snapshot là
   recovery evidence; Manager không được tự chép nó đè lại implementation.
3. Dùng guard xác định như
   `docs/pm/tools/write_set_guard.py` hoặc cơ chế tương đương để verify protected
   drift và destructive shrink sau mỗi worker terminal. Raw manifest/report phải
   được giữ trong task output.
4. File đã tồn tại không được sửa bằng `write_file`, full-file replace, shell
   redirection, `Set-Content`, `Out-File`, heredoc, script direct-write hoặc
   copy/move-overwrite. Mặc định chỉ dùng bounded patch có preimage (`apply_patch`
   hoặc cơ chế tương đương) và kiểm hash/size/line count ngay sau patch. Whole-file
   generation chỉ được dùng cho file mới chưa tồn tại, đúng allowlist.
5. Nếu file biến mất, line/byte count giảm bất thường, nhiều definition biến
   mất, hoặc guard báo destructive shrink, phải dừng ngay; không tiếp tục code,
   không chạy broad gate và không cố che bằng rebuild từ memory.

### 8.3. Recovery khi source/test authority bị phá hủy

- Đóng băng writer và mọi production write; bảo toàn file hỏng, backup, pyc,
  tool log, state database và message/tool payload liên quan. Không chạy lệnh có
  thể ghi đè cache/pyc ground truth trước khi snapshot evidence.
- Manager và Codex Reviewer không được sửa/rebuild implementation. Recovery
  bytes thuộc đúng worker owner hoặc recovery owner được Codex cấp quyền.
- Candidate phải được dựng ngoài path chính từ nguồn có provenance (Git/blob,
  byte snapshot, full tool payload hoặc deterministic patch replay). Nếu có
  reviewed SHA cũ, candidate phải match exact SHA trước khi patch path chính.
  Tên test, docstring, compile, pyc function list hoặc test xanh không thay thế
  exact source authority.
- State/session database chỉ được mở read-only; mọi query/script/export phải
  được giữ trong evidence, không chỉ `%TEMP%`. Không vacuum hoặc mutate DB.
- Report recovery phải ghi cả pass lẫn fail của full relevant module, collect
  node IDs, duplicate definitions, unresolved symbols và raw command. Không
  được suy rộng từ một selection thành trạng thái toàn file.
- Nếu exact authority không thể phục hồi, dừng `BLOCKED_TEST_AUTHORITY`; không
  tự chấp nhận semantic reconstruction. Nếu guarded owner tái phạm hành vi phá
  hủy/sai scope, dừng `BLOCKED_CONTEXT_HEALTH / OWNER_TRANSFER_REQUIRED`.

## 9. Cấu trúc bắt buộc của một prompt quản lý chuẩn

Mỗi prompt phải có đầy đủ:

1. **Authority & role** — Codex là reviewer gate; Manager không code.
2. **Mandatory rules load** — đọc toàn bộ file này và báo `RULES_LOADED`.
3. **Current verdict/status** — sprint/task nào đã duyệt, bị correction hay đang chờ review.
4. **Authorized scope / out of scope** — quyền làm chính xác và ranh giới dừng.
5. **Workspace preflight** — path, branch, HEAD, dirty tree, runtime, DB guard,
   byte-safe write-set manifest/snapshot và destructive-shrink guard.
6. **Model policy** — model/reasoning/fallback cho manager chat và từng worker mới; bảo toàn session cũ.
7. **Task map** — từng Task ID có outcome, dependencies, exclusive write allowlist, forbidden paths, acceptance criteria và owner session rule.
8. **Parallel waves** — task nào chạy đồng thời, bằng chứng an toàn và task nào phải chờ.
9. **Session/correction routing** — new task = new session; correction = resume session cũ.
10. **Heartbeat/liveness** — heartbeat 20 phút, audit 8 phút, báo sự cố ngay.
11. **Verification gates** — task-focused test, contract/integration test, global gate/mutex và evidence phải lưu.
12. **Terminal condition** — trạng thái được phép kết thúc và review boundary.
13. **Required report** — task/session/model map, files changed, tests, findings, blockers, risks, evidence paths và đề xuất tiếp theo.
14. **Start command** — yêu cầu Manager bắt đầu preflight/dispatch ngay, không chỉ trả lại kế hoạch lý thuyết.

Nếu prompt không chia sprint thành Task ID cụ thể, không gán mỗi task cho một session mới, hoặc không nêu correction phải resume session cũ thì prompt chưa đạt chuẩn.

## 10. Review độc lập của Codex

Codex không được chỉ tin report, test count hoặc kết luận của Hermes. Khi review sprint phải kiểm tra diff/code/test thực tế, đối chiếu acceptance criteria từng task, chạy lại test/gate theo rủi ro, kiểm tra regression/contract/migration/ownership/artifact và kết luận theo sprint.

Finding phải có mức độ (`P0/P1/P2`), file/dòng, cách tái hiện hoặc chứng cứ, expected/actual, ảnh hưởng, test cần bổ sung và Task ID/session owner phải nhận correction.

Nếu `CHANGES_REQUESTED`, prompt tiếp theo phải resume đúng session owner của từng finding. Nếu `APPROVED`, Codex/BA mới lập và cấp quyền cho sprint hoặc parallel wave tiếp theo.

Sau **mọi** verdict/review, Codex phải đưa ngay một **Session Opening Proposal** cho bước kế tiếp, kể cả khi gate còn blocked. Proposal tối thiểu phải nêu:

1. Task ID nào mở session mới, Task ID nào resume exact session cũ, và session nào cần context-health audit hoặc recovery có điều kiện.
2. Dependency/activation condition, parallel wave tối đa an toàn, exclusive write-set và lý do các task chưa được mở.
3. Provider/model/reasoning/fallback dự kiến theo chỉ thị user mới nhất.
4. Với recovery: bằng chứng context hỏng cần đạt, cách dừng owner cũ, handoff tối thiểu và đảm bảo zero concurrent writer.
5. Trạng thái quyền hạn: `PROPOSED_ONLY`, `AUTHORIZED_TO_DISPATCH` hoặc `BLOCKED_DEPENDENCY`. Proposal không tự động tạo/mở session nếu Codex/user chưa cấp dispatch authority.

Nếu review đồng thời tạo prompt Hermes tiếp theo, phần Session Opening Proposal phải khớp chính xác task/session/model/wave trong prompt; không được đưa một phương án trong chat nhưng cấp quyền khác trong file.

## 11. Từ vựng trạng thái chuẩn

- `RULES_LOADED`
- `PREFLIGHT_OK`
- `RUNNING`
- `RUNNING_RETRY_WAIT`
- `BLOCKED_RULES`
- `BLOCKED_MODEL_ROUTE`
- `BLOCKED_DEPENDENCY`
- `BLOCKED_LIVENESS`
- `BLOCKED_TEST_AUTHORITY`
- `BLOCKED_CONTEXT_HEALTH`
- `BLOCKED_ROLE_VIOLATION`
- `TASK_SUBMITTED`
- `TASK_MANAGER_VERIFIED`
- `SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW`
- `CHANGES_REQUESTED`
- `APPROVED`

Không dùng `DONE`, `CLOSED` hoặc `APPROVED` theo cách làm mờ quyền review của Codex.

## 12. Checklist cuối trước khi giao prompt cho người dùng

- [ ] Đã đọc toàn bộ file này trong lượt hiện tại.
- [ ] Prompt bắt Manager đọc toàn bộ file này trước mọi hành động.
- [ ] Chỉ có sprint/task được cấp quyền; không giao cả backlog.
- [ ] Sprint được tách thành Task ID cụ thể.
- [ ] Mỗi task mới có một session/chat mới; correction resume session cũ.
- [ ] Model áp dụng đúng manager chat, không đổi session cũ ngoài ý muốn.
- [ ] Có dependency DAG, exclusive write-set và parallel wave tối đa an toàn.
- [ ] Có heartbeat 20 phút, liveness audit 8 phút và báo lỗi ngay.
- [ ] Manager không code.
- [ ] Có write-set SHA/size/line manifest, snapshot cho critical untracked/dirty
      bytes, patch-only guard cho file hiện hữu và post-worker shrink verification.
- [ ] Gate chạy theo thứ tự micro -> matrix -> focused/static -> final broad;
      không dùng broad xanh để waive một binary row còn mở.
- [ ] Có test/evidence/terminal state và dừng để Codex review sau sprint.
- [ ] Sau review đã đưa Session Opening Proposal: new/resume/recovery, context health, model, dependency, write-set, parallel wave và dispatch authority.

---

**Quy tắc duy trì:** mọi thay đổi lâu dài về cách điều phối phải được cập nhật tại file này, không tạo thêm một bản rules cạnh tranh.
