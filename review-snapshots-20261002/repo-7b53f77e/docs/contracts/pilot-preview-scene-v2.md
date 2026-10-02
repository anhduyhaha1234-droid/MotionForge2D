# MotionForge pilot-preview scene contract v2 (FROZEN)

`pilot-preview-scene-v2` is the source-locked scene annotation for the
bounded V3 pilot window. It is owned by DV3-R2-T01 and validated by
`tests/pilot_preview/test_r2_scene_contract.py` (13 tests). It does not
modify any existing file.

## Window and timebase

- Source: `source-0040-0110.mp4`, 640x360, 30/1 fps, 900 frames, audio.
  SHA-256 `22e7577d…9ce1a` (877221 B), re-hashed by running.
- Window: source frames **450..569** inclusive (120 frames, 15.0–19.0 s).
- Output-local 0/60/119 = source 450/510/569. Any diagnostic named
  0/60/119 is LOCAL, never a clip frame.

## Roles (per-frame visibility + z-bands, no single global order)

| Role | Content | z-band |
|---|---|---|
| room | walls/curtain/floor + watermark (source-only) | 0 |
| chair_occupied | dark-gray chair under reader (rear) | 1 |
| chair_spare | second dark-gray chair behind woman (rear) | 1 |
| character | gray-haired seated reader (REPLACE TARGET) | 2 |
| woman | brown-hair woman, magenta dress, SEATED (same dark-gray chair type) | 2 |
| table | wooden table + diorama prop | 2 |
| book | blue prop at reader chest (source-sized) | 3 |
| seated_back | black-haired back-view figure at table | 3 |
| chair_foreground | light-gray chair back, lower-right (front) | 4 |

Target-removal masks (tight propagated target mask) are separate from the
replacement alpha (RGBA asset alpha only) and from the operator edit
envelope (prompt bbox). Chair rear/front are distinct layers. The worker
consumes these fields as pixels before encode; they are not post-render
labels.

## Ground-truth events (measured + vision-verified, none invented)

- Reader seated, both hands on book at chest: source 450..569 (all).
- Book CLOSED (single solid blue cover, yellow badge at left): 450..521.
- Book OPEN (two blue pages, dark center spine, badge occluded):
  522..569. Transition: **522** (win-064..win-072 byte-identical closed
  hold — any @516 claim is false; insert-ROI mid-blue step 0.405→0.528
  at 521→522; 12-tile insert strip src513..src524: last closed 521,
  first open 522).
- The book close-up is a picture-in-picture insert box over the reader's
  chest, full-frame approx (235,210)–(295,285). The wide master stays
  locked; only the insert interior changes at the transition.
- Reader mouth closed (line/dot, never open): all sampled frames.
- Woman SEATED on the same dark-gray chair type (seat band under hem +
  brown legs to floor, no bare legs/feet): all 120 frames.
- Back-view figure seated, no visible hands, no hand near face: all frames.
- Watermark `Lanh Vcl` + play icon bottom-left: source-only, preserve as
  pixels, never reproduce as graphics.

## Anchors and coordinate spaces

Anchors: head, seat_pelvis, hand_grip_l, hand_grip_r, book_corners
(plane), supports. Every anchor carries an explicit space:

- `fullframe_px` — pixels in the 640x360 decoded frame.
- `normalized` — full-frame divided by (640, 360), in [0,1]^2.
- `bbox_local` — pixel offset inside a role bbox (origin = top-left).
- `asset_local` — pixel offset inside the replacement asset canvas.

Pure conversions live in `scene_contract.py`
(`anchor_fullframe_to_normalized`, `anchor_fullframe_to_bbox_local`).
The source head anchor is the replacement target's left seated reader
(`258,125`), never the woman in the center overlap region (`310,125`). The
pelvis anchor is the actual seat wedge center (`275,266`), not legs or feet.
The server pack manifest supplies the asset-local anchors and native canvas;
scale/rotation are applied to that local point before translation is solved.

## Compatibility gate (fail-closed, BEFORE heavy work)

A candidate pack must be selected by a server-owned versioned `pack_id` and
its manifest must hash/decode each state image and verify its measured
anchors. A candidate pack must cover ALL of: seated_pose, grip_both_hands_chest,
book_open_variant, book_closed_variant, mouth_closed_state,
view_three_quarter_front (this window), alpha_genuine, anchor_head,
anchor_seat_pelvis, anchor_hand_grip_l/r, anchor_book_corners.
Anything missing or claimed only by the client → readable
`SceneContractError`/pack-resolution reject, no SAM2/render. Boolean fields
are strict booleans; camera view is a recognized string, not `true`.

The pack manifest must also contain an approved semantic compatibility review:
the head and seat-pelvis anchors must be assigned to the replacement
character, the pelvis must reference the occupied chair seat, book contact
must be compatible, and contact samples must cover 450/510/521/522/523/569
with reviewed error bounds. The resolver verifies anchor coordinates land on
decoded nontransparent replacement pixels; it does not trust client
capabilities or a string-only semantic claim.

The current V3 hands-on-knees asset is the INTENTIONAL incompatible
negative fixture: hands empty, book deleted, no grip/book anchors.
Known R1 failure (after-frame-119, documented): the woman stays seated
unchanged (comparison sheet pixel-identical); the candidate's fault is
the leftover blue book smear behind/between the replacement legs plus
head/torso halo — incomplete removal of the source book, not a re-seat
of the woman.

## Versioning

Contract `pilot-preview-scene-v2`, annotation rev `r2-20260908`.
Deterministic SHA-256 over canonical JSON (`scene_contract_hash`).
Any new asset pack = new version/hash/provenance, never overwrites V3.
