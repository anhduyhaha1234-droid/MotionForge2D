# PROPOSED FIX — test_no_worker_or_api_cutover_tables (pre-existing, ngoài write-set T01C)

**Trạng thái:** ĐỀ XUẤT cho owning session của `tests/test_durable_job_persistence.py`
(Manager route). T01C-R4 không tự sửa vì vượt write-set.

## Root cause (đọc trực tiếp từ source)

- Guard-test expected-table list tại `tests/test_durable_job_persistence.py:383-410`
  (commit cuối đụng file: `a688d86`, era trước S07).
- Migration `migrations/versions/b2c3d4e5f6a7b_s07_project_cast_mapping.py`
  thêm bảng `project_cast_mapping` → schema hiện tại có bảng này nhưng
  expected-list chưa update.
- Failure thật (chạy tươi):
  `E  AssertionError: unexpected tables: ['project_cast_mapping']` @ line 411.
- Chứng minh KHÔNG liên quan T01C: test chỉ inspect schema DB, không import
  handler; chạy song song với attach suite xanh 14/14.

## Bản vá đề xuất (1 dòng)

```diff
--- a/tests/test_durable_job_persistence.py
+++ b/tests/test_durable_job_persistence.py
@@ -407,6 +407,8 @@ def test_no_worker_or_api_cutover_tables(...):
         "scene_graph_occlusion",
         "scene_graph_contact",
+        # S07 project-cast domain mapping (migration b2c3d4e5f6a7b).
+        "project_cast_mapping",
     }
     assert not unexpected, f"unexpected tables: {sorted(unexpected)}"
```

Sau khi áp: `env -u MOTIONFORGE_DATABASE_URL python -m pytest
tests/test_durable_job_persistence.py -q -p no:cacheprovider
--basetemp=<temp>` kỳ vọng **47 passed**.
