# Video Import V1 PM Decisions

Approved for S05-T02 after review of `VIDEO_PREFLIGHT_CONTRACT.md`:

- Accept MP4 with H.264 or HEVC video. Accept AAC audio or no audio. Other containers/codecs are rejected fail-closed in V1; no automatic transcode.
- No arbitrary maximum file-size cap in V1 because copying and hashing are streaming. Preflight/import must require enough free managed-storage space for the source plus 10% safety margin, with a minimum 1 GiB reserve.
- Structural minimum only: positive duration and positive width/height. Product-quality resolution thresholds are not an import blocker.
- First video stream and first audio stream are canonical for V1. Multi-stream selection UI is deferred.
- HDR/10-bit inputs are rejected until the canonical proxy/timebase task proves support.
- Checksum is computed while streaming the managed copy; the worker may compare a preflight hash when available but must not synchronously hash an arbitrarily large file in the request path.
- All unsupported decisions return stable actionable errors; never silently convert or publish partial files.
