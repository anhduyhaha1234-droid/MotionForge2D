"""MF-END-20 test fixture fixes (bounded, count asserts)."""
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-20")
path = WT / "tests/product_delivery/test_mf_end_20.py"
raw = path.read_bytes().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
data = raw.replace("\r\n", "\n") if nl == "\r\n" else raw

# 1) _result gains an explicit managed-root-relative path
old_sig = (
    'def _result(path: Path, **over: Any) -> dict[str, Any]:\n'
    "    frames = decode_rgb_frames(path)\n"
    '    out: dict[str, Any] = {\n'
    '        "output_relative_path": str(path.name),\n'
)
new_sig = (
    'def _result(path: Path, rel: str | None = None, **over: Any) -> dict[str, Any]:\n'
    "    frames = decode_rgb_frames(path)\n"
    '    out: dict[str, Any] = {\n'
    '        "output_relative_path": str(rel or path.name),\n'
)
assert data.count(old_sig) == 1
data = data.replace(old_sig, new_sig)

# 2) cache-test render closures pin the real managed-root-relative output path
n = data.count("_result(out)")
assert n == 11, f"expected 11 bare _result(out) sites, found {n}"
data = data.replace("_result(out)", '_result(out, "engine_out/ck_0001_00001_.mp4")')
n_book = data.count("_result(out_book)")
n_turn = data.count("_result(out_turn)")
assert n_book == 1 and n_turn == 1, (n_book, n_turn)
data = data.replace("_result(out_book)", '_result(out_book, "engine_out/ck_book_00001_.mp4")')
data = data.replace("_result(out_turn)", '_result(out_turn, "engine_out/ck_turn_00001_.mp4")')

# 3) the model texture component is profile/capability; seed lives in params
old_model = '        "model": {"backend": {**base["backend"], "seed": 7}},\n'
new_model = (
    '        "model": {"backend": {**base["backend"], "profile_id": "other_profile"}},\n'
)
assert data.count(old_model) == 1
data = data.replace(old_model, new_model)

# 4) the probe resolves a REAL managed root without the QA-only MAIN guard:
#    QA mode blocks deps.get_managed_root() (MAIN is protected), so the probe
#    uses the task's canonical run-area managed root (env-overridable).
old_probe = (
    '    if os.name != "nt":\n'
    '        pytest.skip("long-path probe is Windows-specific")\n'
    "    from app.api import deps\n"
    "\n"
    "    real_root = Path(deps.get_managed_root())\n"
    '    assert real_root.is_dir(), f"real managed root missing: {real_root}"\n'
)
new_probe = (
    '    if os.name != "nt":\n'
    '        pytest.skip("long-path probe is Windows-specific")\n'
    "\n"
    "    real_roots: list[Path] = []\n"
    "    env_root = os.environ.get(_PROBE_MANAGED_ROOT_ENV, \"\").strip()\n"
    "    if env_root:\n"
    "        real_roots.append(Path(env_root))\n"
    "    else:\n"
    "        real_roots.append(_DEFAULT_PROBE_MANAGED_ROOT)\n"
    "    try:\n"
    "        from app.api import deps\n"
    "\n"
    "        real_roots.append(Path(deps.get_managed_root()))\n"
    "    except Exception:\n"
    "        pass  # QA/test mode fences the protected MAIN root — use the run area\n"
)
assert data.count(old_probe) == 1
data = data.replace(old_probe, new_probe)

# 4b) loop the probe over every resolved real root (>260 write on each)
old_body = (
    "    sf = _db(tmp_path, name=\"probe.db\")\n"
    "    long_shot = \"shot_\" + \"S\" * 120\n"
    "    long_chunk = \"ck_\" + \"C\" * 130\n"
    "    shot_root = real_root / \"shot_render_cache\"\n"
    "    my_dir = shot_root / long_shot\n"
    "    measurement: dict[str, Any] = {}\n"
    "    try:\n"
)
new_body = (
    "    sf = _db(tmp_path, name=\"probe.db\")\n"
    "    long_shot = \"shot_\" + \"S\" * 120\n"
    "    long_chunk = \"ck_\" + \"C\" * 130\n"
    "    measurements: list[dict[str, Any]] = []\n"
    "    for real_root in real_roots:\n"
    "        assert real_root.is_absolute(), f\"managed root must be absolute: {real_root}\"\n"
    "        real_root.mkdir(parents=True, exist_ok=True)\n"
    "        protected = Path.home() / \"MotionForge2D\"\n"
    "        assert real_root.resolve() != protected.resolve(), (\n"
    "            \"the probe refuses the protected MAIN root\"\n"
    "        )\n"
    "        measurements.append(_probe_one_root(sf, real_root, long_shot, long_chunk))\n"
    "    assert measurements and all(m[\"write\"] == \"OK\" for m in measurements)\n"
    "    assert all(m[\"path_chars\"] > 260 for m in measurements), measurements\n"
    "\n"
    "\n"
    "def _probe_one_root(\n"
    "    sf: Any, real_root: Path, long_shot: str, long_chunk: str\n"
    ") -> dict[str, Any]:\n"
    "    shot_root = real_root / \"shot_render_cache\"\n"
    "    my_dir = shot_root / long_shot\n"
    "    measurement: dict[str, Any] = {}\n"
    "    try:\n"
)
assert data.count(old_body) == 1
data = data.replace(old_body, new_body)

# 4c) the probe body keeps working on the helper's `real_root`; drop the old tail assert
old_tail = (
    "            shutil.rmtree(Path(\"\\\\\\\\?\\\\\" + str(my_dir)), ignore_errors=True)\n"
)
assert data.count(old_tail) == 1, data.count(old_tail)

old_final = (
    "        assert real_root.is_dir()\n"
    "    assert measurement.get(\"write\") == \"OK\" and measurement.get(\"path_chars\", 0) > 260\n"
)
new_final = (
    "        assert real_root.is_dir()\n"
    "    return measurement\n"
)
assert data.count(old_final) == 1
data = data.replace(old_final, new_final)

# 5) module-level probe root constants
old_const = 'WAN_PROFILE = "wan_animate2_int8_pad640x368_cacheoff"\n'
new_const = (
    'WAN_PROFILE = "wan_animate2_int8_pad640x368_cacheoff"\n'
    "#: Real managed root of this task's run area (env-overridable) — the\n"
    "#: long-path probe must run on a REAL absolute managed root, never a\n"
    "#: synthetic short pytest tmp path.\n"
    '_PROBE_MANAGED_ROOT_ENV = "MF_END20_PROBE_MANAGED_ROOT"\n'
    "_DEFAULT_PROBE_MANAGED_ROOT = Path(\n"
    '    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"\n'
    '    "20260927T163824Z/tasks/MF-END-20/managed"\n'
    ")\n"
)
assert data.count(old_const) == 1
data = data.replace(old_const, new_const)

out = data.replace("\n", nl) if nl == "\r\n" else data
path.write_bytes(out.encode("utf-8"))
print(f"TEST_FIXER_OK newline={nl!r}")
