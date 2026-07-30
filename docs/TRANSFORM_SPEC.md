# Transform Specification — MotionForge 2D

Defines the exact transform pipeline for compositing a replacement asset onto a video frame.

This specification is shared between frontend preview (canvas) and backend render (FFmpeg).
Both must produce identical positioning.

---

## Coordinate Systems

### Source Video Coordinates
- Origin: top-left of frame
- Units: pixels
- Range: [0, width) × [0, height)

### Normalized Coordinates
- Origin: top-left of frame
- Range: [0.0, 1.0] × [0.0, 1.0]
- Used for: anchor, offset (resolution-independent)

### Canvas Coordinates
- Mapped from source coordinates via viewport transform
- `canvas_x = source_x * scale + offset_x`
- `canvas_y = source_y * scale + offset_y`

---

## Replacement Object Schema

```json
{
  "mode": "static_asset",
  "assetPath": "assets/replacement.png",
  "anchor": {"x": 0.5, "y": 0.5},
  "offset": {"x": 0.0, "y": 0.0},
  "scale": 1.0,
  "rotationOffsetDeg": 0.0,
  "opacity": 1.0,
  "fitMode": "contain"
}
```

### Fields

| Field | Type | Range | Unit | Description |
|-------|------|-------|------|-------------|
| `mode` | enum | — | — | `none`, `static_asset`, `frame_sequence`, `keyframe_assets` |
| `assetPath` | string | — | — | Relative path to replacement PNG (must have alpha) |
| `anchor.x` | float | 0.0–1.0 | relative | Horizontal anchor within asset bbox |
| `anchor.y` | float | 0.0–1.0 | relative | Vertical anchor within asset bbox |
| `offset.x` | float | any | normalized | Global horizontal offset (0.5 = half frame width) |
| `offset.y` | float | any | normalized | Global vertical offset |
| `scale` | float | 0.01–10.0 | multiplier | Scale relative to tracked bbox size |
| `rotationOffsetDeg` | float | -180–180 | degrees | Additional rotation on top of tracked rotation |
| `opacity` | float | 0.0–1.0 | multiplier | Alpha multiplier for replacement |
| `fitMode` | enum | — | — | `contain`, `cover`, `stretch` |

---

## Transform Pipeline (ORDER MATTERS)

Given a frame with tracked motion data (centroid, bbox, rotation, scale):

### Step 1: Resolve Asset Bounds

Load replacement PNG. Get its natural width and height.

```
asset_w = replacement_image.width
asset_h = replacement_image.height
```

### Step 2: Determine Target Size from Fit Mode

Based on `fitMode` and the tracked bbox:

```
bbox_w = tracked_bbox.width * tracked_scale_x
bbox_h = tracked_bbox.height * tracked_scale_y

if fitMode == "contain":
    ratio = min(bbox_w / asset_w, bbox_h / asset_h)
    target_w = asset_w * ratio
    target_h = asset_h * ratio
elif fitMode == "cover":
    ratio = max(bbox_w / asset_w, bbox_h / asset_h)
    target_w = asset_w * ratio
    target_h = asset_h * ratio
elif fitMode == "stretch":
    target_w = bbox_w
    target_h = bbox_h
```

### Step 3: Apply Scale

```
final_w = target_w * replacement.scale
final_h = target_h * replacement.scale
```

### Step 4: Apply Anchor

The anchor defines which point of the asset aligns with the tracked centroid.

```
anchor_px_x = final_w * replacement.anchor.x
anchor_px_y = final_h * replacement.anchor.y
```

### Step 5: Compute Position

```
# Position = centroid - anchor + offset
pos_x = tracked_centroid_x - anchor_px_x + (replacement.offset.x * frame_width)
pos_y = tracked_centroid_y - anchor_px_y + (replacement.offset.y * frame_height)
```

### Step 6: Apply Rotation

Total rotation = tracked rotation + rotation offset.

```
total_rotation = tracked_rotation_deg + replacement.rotationOffsetDeg
center_x = pos_x + final_w / 2
center_y = pos_y + final_h / 2
```

Rotate the asset around its center by `total_rotation` degrees.

### Step 7: Alpha Composite

```
alpha = replacement.opacity * mask_at_pixel
output = background * (1 - alpha) + foreground * alpha
```

---

## Fit Mode Details

### Contain
Asset fits entirely within the tracked bbox, preserving aspect ratio.
May leave transparent areas if aspect ratios differ.

### Cover
Asset covers the entire tracked bbox, preserving aspect ratio.
May crop parts of the asset if aspect ratios differ.

### Stretch
Asset is stretched to exactly match the tracked bbox dimensions.
May distort the asset.

---

## Frontend Preview vs Backend Render

| Aspect | Frontend (Konva) | Backend (OpenCV/FFmpeg) |
|--------|-----------------|------------------------|
| Transform | `Konva.Image` with `x, y, scaleX, scaleY, rotation` | `cv2.warpAffine` + `cv2.seamlessClone` or alpha blend |
| Coordinate source | Canvas mouse events (inverse transform) | Motion data from JSON |
| Resolution | Viewport-scaled | Source resolution |
| Alpha | Canvas globalAlpha | Per-pixel alpha from mask |

Both use the same transform formulas above. The frontend applies them via Konva node properties; the backend applies them via numpy/OpenCV operations.

---

## Extension Points (Milestone 1B+)

### frame_sequence mode
Each frame can have a different replacement asset.
Schema: `{"mode": "frame_sequence", "frames": {"0": "path.png", "10": "path2.png"}}`

### keyframe_assets mode
Keyframes define asset changes at specific frames, with interpolation.
Schema: `{"mode": "keyframe_assets", "keyframes": [{"frame": 0, "asset": "a.png"}, {"frame": 30, "asset": "b.png"}]}`

### Background cleaning
- `clean_plate` mode: use a frame where the object is absent
- `user_background` mode: user uploads a clean background
- `inpainting` mode: local AI inpainting (future)
