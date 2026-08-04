# Task S06-T03: Pose Completeness, Transparency & Resolution Validation

- **Task ID:** `S06-T03`
- **Sprint:** `S06` (Durable Character Library)
- **Status:** `IMPLEMENTATION`
- **Owner:** Hermes (Parallel Worktree `s06-t01`)
- **Depends On:** `S06-T02`

## Objectives
1. Implement `app/workflow/character_validator.py` to validate character pack pose completeness and asset quality before publishing:
   - Verification of 6 required core pose slots (`front`, `three_quarter`, `side`, `back`, `sitting`, `walking`).
   - Image aspect ratio, transparency (alpha channel check for RGBA), minimum resolution (e.g. 512x512), and non-empty file size verification.
2. Integrate validation check into `CharacterRepository.publish_pack_version` or `CharacterService`.
3. Add unit test suite `tests/test_character_validator.py`.
