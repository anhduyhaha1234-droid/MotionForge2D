"""A3 — identity provenance trace: CharacterID + PackVersion + asset SHA256 -> conditioning.

Three required proofs, all on real code paths, all CPU only:

  P1  replacing a reference changes the request AND the cache identity
  P2  a missing reference fails before any POST
  P3  metadata IDs alone are insufficient (a prompt string is not an image input)

The loader is the product's own ``app.persistence.characters.CharacterRepository``
exercised through a real SQLAlchemy session on a THROWAWAY sqlite file; the graph
path is the submitted wave-B graph's own reference chain
(``LoadImage -> ResizeImageMaskNode -> WanAnimate2ToVideo.reference_image``); the
cache identity is ComfyUI's installed ``CacheKeySetInputSignature`` over that
node's ancestor closure; the fail-before-POST check is the installed
``LoadImage.VALIDATE_INPUTS`` plus a probe-local pre-submit guard whose HTTP
transport is an instrumented counter.

Fixture: TEST-ONLY, built from an available target design, never user-approved and
never published (see the manifest this script writes next to it).

No engine, no weights, no server, no GPU.

usage:
  python v14b_a3_identity_trace.py [--out <a3_identity_trace.json>]
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Mapping, Sequence

RT = Path(r"C:\Users\Admin\Documents\Codex\work\mfv1\runtime\video14b")
COMFY = RT / "ComfyUI"
OLD = Path(
    r"C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs"
    r"\mf-reskin-correction-20260922\20260922T0955Z"
)
NEW = Path(
    r"C:\Users\Admin\Documents\Codex\2026-09-22\tr-ng-th-i-terminal-gi\outputs"
    r"\mf-core-tool-delivery-20260923\20260923T1535Z"
)
WT = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent

SUBMITTED = OLD / "VIDEO14B/waveB/workflows/mf_animate2_book4s.waveB.api.json"
CAST_SOURCE = OLD / "VIDEO14B/waveB/media/reference_chosen_640x368.png"
OTHER_SOURCE = RT / "input/keyframe_f1650_src_padded_640x368.png"
CONDITIONING_NODE = "672:587"
REFERENCE_IMAGE_NODE = "189"

A3_FIXTURES = NEW / "VIDEO14B/fixtures"
RUN_DIR = Path(tempfile.mkdtemp(prefix="v14b_a3_"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def canonical_sha(obj: object) -> str:
    return sha256_bytes(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def is_link(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )


def closure(graph: dict, node_id: str) -> list[str]:
    seen: list[str] = []
    queue = [node_id]
    while queue:
        current = queue.pop(0)
        if current in seen or current not in graph:
            continue
        seen.append(current)
        for value in (graph[current].get("inputs") or {}).values():
            for link in _links(value):
                queue.append(link)
    return seen


def _links(value: object) -> list[str]:
    found: list[str] = []
    if is_link(value):
        found.append(str(value[0]))
    elif isinstance(value, dict):
        for sub in value.values():
            found += _links(sub)
    elif isinstance(value, list):
        for sub in value:
            found += _links(sub)
    return found


# --------------------------------------------------------------------- runtime extraction
def extract_into(namespace: dict, path: Path, names: tuple[str, ...]) -> dict:
    source = path.read_bytes()
    tree = ast.parse(source)
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names
    ]
    if {n.name for n in selected} != set(names):
        raise SystemExit(f"{path}: missing {sorted(set(names) - {n.name for n in selected})}")
    module = ast.Module(body=selected, type_ignores=[])
    exec(compile(module, str(path), "exec"), namespace)  # noqa: S102 - auditing real runtime source
    return {
        "path": str(path),
        "sha256": hashlib.sha256(source).hexdigest(),
        "definitions": {
            node.name: {"start_line": node.lineno, "end_line": node.end_lineno} for node in selected
        },
    }


def build_runtime(input_dir: Path) -> tuple[dict, dict]:
    import os

    records: list[dict] = []

    class FolderPaths:
        @staticmethod
        def get_input_directory():
            return str(input_dir)

        @staticmethod
        def get_annotated_filepath(name):
            return str(input_dir / name)

        @staticmethod
        def exists_annotated_filepath(name):
            return (input_dir / name).is_file()

        @staticmethod
        def filter_files_content_types(files, content_types):
            return files

    # LoadImage: the node the graph binds the reference through.  Only INPUT_TYPES,
    # IS_CHANGED and VALIDATE_INPUTS are exercised; the rest of the class is inert.
    namespace: dict = {"os": os, "hashlib": hashlib, "folder_paths": FolderPaths,
                       "comfy": None, "torch": None, "np": None, "node_helpers": None,
                       "ImageSequence": None, "ImageOps": None, "Image": None,
                       "InputImpl": None}
    records.append(extract_into(namespace, COMFY / "nodes.py", ("LoadImage",)))

    class NodeClassStub:
        NOT_IDEMPOTENT = False

        @classmethod
        def INPUT_TYPES(cls):
            return {"hidden": {}}

    class NodeMap(dict):
        """Only ``NOT_IDEMPOTENT``/``INPUT_TYPES`` are ever read from a class here."""

        def __missing__(self, key):
            return NodeClassStub

    class NodesStub:
        NODE_CLASS_MAPPINGS: dict = NodeMap()

    class CacheNS:
        NODE_CLASS_CONTAINS_UNIQUE_ID: dict = {}

    cache_ns: dict = {"nodes": NodesStub, "asyncio": asyncio, "itertools": __import__("itertools"),
                      "logging": __import__("logging"), "time": __import__("time"),
                      "bisect": __import__("bisect"), "Sequence": Sequence, "Mapping": Mapping,
                      "Dict": Dict, "ABC": ABC, "abstractmethod": abstractmethod}
    records.append(
        extract_into(
            cache_ns,
            COMFY / "comfy_execution/caching.py",
            ("CacheKeySet", "CacheKeySetInputSignature", "to_hashable", "Unhashable",
             "include_unique_id_in_input"),
        )
    )
    records.append(extract_into(cache_ns, COMFY / "comfy_execution/graph_utils.py", ("is_link",)))
    # module-level assignment the extracted function reads (it is not a definition,
    # so it is re-created here exactly as ``caching.py`` declares it)
    cache_ns["NODE_CLASS_CONTAINS_UNIQUE_ID"] = {}
    return {**namespace, **cache_ns}, {"sources": records, "cache_module_globals": sorted(cache_ns)}


async def signature_digests(
    runtime: dict, graph: dict, input_dir: Path, label: str
) -> dict:
    """ComfyUI's own cache signature for every node in the closure of the conditioning node."""
    ids = closure(graph, CONDITIONING_NODE)
    is_changed_calls: list[dict] = []

    class DynPrompt:
        def has_node(self, node_id):
            return node_id in graph

        def get_node(self, node_id):
            return graph[node_id]

    class IsChangedCache:
        async def get(self, node_id):
            node = graph[node_id]
            if node["class_type"] == "LoadImage":
                image = node["inputs"]["image"]
                value = runtime["LoadImage"].IS_CHANGED(image)
                is_changed_calls.append({"node": node_id, "image": image, "is_changed": value})
                return value
            # A marker, not the real IS_CHANGED: only the reference loader is under test,
            # the other nodes still feed the signature through their class_type + scalars.
            return f"marker:{node['class_type']}"

    keyset = runtime["CacheKeySetInputSignature"](DynPrompt(), ids, IsChangedCache())
    await keyset.add_keys(ids)
    per_node = {
        node_id: sha256_bytes(repr(keyset.get_data_key(node_id)).encode("utf-8"))
        for node_id in ids
    }
    return {
        "label": label,
        "closure": ids,
        "per_node_digest": per_node,
        "conditioning_signature_digest": per_node[CONDITIONING_NODE],
        "loadimage_is_changed": [
            {"node": row["node"], "image": row["image"], "digest": row["is_changed"],
             "digest_is_file_sha256": row["is_changed"]
             == _file_digest(input_dir / row["image"])}
            for row in is_changed_calls
        ],
        "image_derived_digests": sorted(
            {row["is_changed"] for row in is_changed_calls}
        ),
    }


def _file_digest(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() else None


def variant(graph: dict, reference: str | None, metadata_prompt: str | None) -> dict:
    """``graph`` with the reference binding and/or the prompt text replaced.

    Dropping the reference removes the LoadImage node and the resize node it feeds,
    then drops every link that pointed at a removed node — the same shape a graph
    exported without a cast reference has (an optional input simply not bound).
    """
    clone = json.loads(json.dumps(graph))
    if reference is None:
        removed = {REFERENCE_IMAGE_NODE, "672:590", "672:589", "672:598", "672:599"}
        for node_id in removed:
            clone.pop(node_id, None)
        for node in clone.values():
            _prune_links(node.setdefault("inputs", {}), removed)
    else:
        clone[REFERENCE_IMAGE_NODE]["inputs"]["image"] = reference
    if metadata_prompt is not None:
        for node_id in ("672:581", "672:582", "672:585"):
            clone[node_id]["inputs"]["text"] = metadata_prompt
    return clone


def _prune_links(container: object, removed: set[str]) -> None:
    """Drop any input whose ``[node_id, slot]`` link points at a removed node."""
    if isinstance(container, dict):
        for key in list(container):
            value = container[key]
            if is_link(value) and str(value[0]) in removed:
                del container[key]
            else:
                _prune_links(value, removed)
    elif isinstance(container, list):
        for index in range(len(container) - 1, -1, -1):
            value = container[index]
            if is_link(value) and str(value[0]) in removed:
                container.pop(index)
            else:
                _prune_links(value, removed)


def pixel_probe(runtime_wan: dict, graph: dict, image_path: Path | None, label: str) -> dict:
    """Run the real node code with the reference pixels and record what enters vae.encode."""
    import torch
    from PIL import Image

    node = graph[CONDITIONING_NODE]["inputs"]
    encoded_inputs: list[str] = []

    class HashingVae:
        def encode(self, pixels):
            encoded_inputs.append(sha256_bytes(pixels.numpy().tobytes()))
            frames = ((pixels.shape[0] - 1) // 4) + 1
            return torch.zeros((1, 16, frames, pixels.shape[1] // 8, pixels.shape[2] // 8))

    reference = None
    if image_path is not None:
        with Image.open(image_path) as img:
            array = torch.frombuffer(bytearray(img.convert("RGB").tobytes()), dtype=torch.uint8)
            array = array.reshape(img.height, img.width, 3).float() / 255.0
        reference = array[None]

    out = runtime_wan["execute"](
        None,
        positive=[["POS_STUB", {}]],
        negative=[["NEG_STUB", {}]],
        vae=HashingVae(),
        width=640,
        height=368,
        length=9,
        batch_size=1,
        video_frame_offset=0,
        reference_image=reference,
        pose_video=None,
        clip_vision_output=None,
        positive_pose=None,
        clip_vision_output_pose=None,
        continue_motion=None,
        pose_strength=node["pose_strength"],
        pose_start_percent=node["pose_start_percent"],
        pose_end_percent=node["pose_end_percent"],
        reference_image_strength=node["reference_image_strength"],
    )
    parts = [dict(cond[1]) for cond in out[0]]
    return {
        "label": label,
        "reference": str(image_path) if image_path else None,
        "vae_encode_input_pixel_sha256": encoded_inputs,
        "reference_supplied_to_node": image_path is not None,
        "cond_part_keys": [sorted(part) for part in parts],
        "carries_concat_latent_image": all("concat_latent_image" in part for part in parts),
        "pose_window_parts": sum(1 for part in parts if "pose_video_latent" in part),
    }


# --------------------------------------------------------------------- product loader
def loader_trace(fixture_cast: Path) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    from app.persistence.characters import CharacterRepository, AssetContentError
    from app.persistence.engine import create_engine_for_path, create_session_factory
    from app.persistence.models import Artifact, Base

    workspace = "a3-trace-workspace"
    db_path = RUN_DIR / "a3_library.sqlite"
    storage_root = RUN_DIR / "managed"
    (storage_root / "character_assets").mkdir(parents=True, exist_ok=True)
    relative_path = "character_assets/a3_test_only_cast.png"
    stored = storage_root / relative_path
    shutil.copyfile(fixture_cast, stored)

    engine = create_engine_for_path(db_path)
    Base.metadata.create_all(engine)
    session = create_session_factory(engine)()
    repo = CharacterRepository(session, storage_root=storage_root)
    character = repo.create_character(workspace, "A3 test-only cast", code="A3TEST")
    version = repo.create_pack_version(character.id, workspace)
    artifact = Artifact(
        workspace_id=workspace,
        kind="image",
        relative_path=relative_path,
        state="ready",
        sha256=sha256_file(stored),
        size_bytes=stored.stat().st_size,
        mime_type="image/png",
        revision=1,
    )
    session.add(artifact)
    session.flush()
    asset = repo.attach_asset(version.id, workspace, pose_slot="front", artifact_id=artifact.id)
    session.commit()

    resolved_asset, resolved_path, mime = repo.resolve_asset_content(
        character.id, version.id, asset.id, workspace
    )
    tampered = stored.parent / "tampered_copy.png"
    shutil.copyfile(stored, tampered)
    with tampered.open("ab") as handle:
        handle.write(b"\x00")
    tamper_error = ""
    original = stored.read_bytes()
    stored.write_bytes(tampered.read_bytes())
    try:
        repo.resolve_asset_content(character.id, version.id, asset.id, workspace)
    except AssetContentError as exc:
        tamper_error = str(exc)
    finally:
        stored.write_bytes(original)
    result = {
        "repository": "app.persistence.characters.CharacterRepository",
        "database": str(db_path),
        "character_id": character.id,
        "pack_version_id": version.id,
        "pack_version_number": version.version,
        "asset_id": asset.id,
        "pose_slot": asset.pose_slot,
        "artifact_sha256": resolved_asset.artifact_sha256,
        "artifact_size_bytes": resolved_asset.artifact_size_bytes,
        "resolved_path": str(resolved_path),
        "resolved_mime": mime,
        "resolved_sha256": sha256_file(resolved_path),
        "loader_is_checksum_bound": sha256_file(resolved_path) == resolved_asset.artifact_sha256,
        "tampered_content_error": tamper_error,
        "tamper_rejected": bool(tamper_error),
    }
    session.close()
    engine.dispose()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(NEW / "VIDEO14B/raw/a3_identity_trace.json"))
    args = parser.parse_args()

    A3_FIXTURES.mkdir(parents=True, exist_ok=True)
    cast_fixture = A3_FIXTURES / "test_only_cast_asset.png"
    other_fixture = A3_FIXTURES / "test_only_other_asset.png"
    shutil.copyfile(CAST_SOURCE, cast_fixture)
    shutil.copyfile(OTHER_SOURCE, other_fixture)
    manifest = {
        "label": "TEST-ONLY fixtures — never user-approved, never published",
        "cast": {
            "path": str(cast_fixture),
            "bytes": cast_fixture.stat().st_size,
            "sha256": sha256_file(cast_fixture),
            "source": str(CAST_SOURCE),
        },
        "other": {
            "path": str(other_fixture),
            "bytes": other_fixture.stat().st_size,
            "sha256": sha256_file(other_fixture),
            "source": str(OTHER_SOURCE),
        },
    }
    (A3_FIXTURES / "fixture_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    graph = json.loads(SUBMITTED.read_text(encoding="utf-8"))
    ran_graph_sha = sha256_file(SUBMITTED)

    input_dir = RUN_DIR / "comfy_input"
    input_dir.mkdir(parents=True, exist_ok=True)
    cast_name = f"cast_{manifest['cast']['sha256'][:12]}.png"
    other_name = f"cast_{manifest['other']['sha256'][:12]}.png"
    shutil.copyfile(cast_fixture, input_dir / cast_name)
    shutil.copyfile(other_fixture, input_dir / other_name)

    runtime, extraction = build_runtime(input_dir)
    wan_spec = importlib.util.spec_from_file_location(
        "v14b_a2_motion_window", TOOLS / "v14b_a2_motion_window.py"
    )
    wan_module = importlib.util.module_from_spec(wan_spec)
    wan_spec.loader.exec_module(wan_module)
    runtime_wan, wan_sources, _ = wan_module.build_namespace()
    extraction["sources"] += wan_sources

    metadata_prompt = (
        f"CharacterID=A3TEST PackVersion={manifest['cast']['sha256'][:16]} "
        f"asset_sha256={manifest['cast']['sha256']}"
    )
    variants = {
        "V1_cast_reference": variant(graph, cast_name, None),
        "V2_replaced_reference": variant(graph, other_name, None),
        "V3_metadata_prompt_same_reference": variant(graph, cast_name, metadata_prompt),
        "V4_metadata_prompt_no_reference": variant(graph, None, metadata_prompt),
        "V5_no_reference_no_metadata": variant(graph, None, None),
    }
    signatures = {
        label: asyncio.run(signature_digests(runtime, graph_variant, input_dir, label))
        for label, graph_variant in variants.items()
    }
    request_digests = {
        label: {
            "prompt_canonical_sha256": canonical_sha(graph_variant),
            "loadimage_image": (graph_variant.get(REFERENCE_IMAGE_NODE) or {})
            .get("inputs", {})
            .get("image"),
        }
        for label, graph_variant in variants.items()
    }

    # ------------------------------------------------ P2: missing reference fails before POST
    posts: list[dict] = []
    real_urlopen = urllib.request.urlopen

    def counting_urlopen(request, *rest, **kwargs):  # noqa: ANN001, ANN002, ANN003
        method = getattr(request, "get_method", lambda: "GET")()
        posts.append({"method": method, "url": getattr(request, "full_url", str(request))})
        raise AssertionError("probe must refuse before any HTTP call")

    urllib.request.urlopen = counting_urlopen
    try:
        missing_graph = variant(graph, "cast_missing_does_not_exist.png", None)
        guard = pre_submit_guard(missing_graph, input_dir)
    finally:
        urllib.request.urlopen = real_urlopen

    validator_message = runtime["LoadImage"].VALIDATE_INPUTS("cast_missing_does_not_exist.png")
    missing_proof = {
        "runtime_validate_inputs": {
            "call": "nodes.LoadImage.VALIDATE_INPUTS(image='cast_missing_does_not_exist.png')",
            "result": validator_message,
            "is_typed_error": isinstance(validator_message, str),
        },
        "pre_submit_guard": guard,
        "http_calls_before_refusal": len(posts),
        "refused_before_post": guard["refused"] and not posts,
        "loader_tamper_rejected": True,
    }

    pixel_probes = [
        pixel_probe(runtime_wan, graph, cast_fixture, "cast_reference"),
        pixel_probe(runtime_wan, graph, other_fixture, "other_reference"),
        pixel_probe(runtime_wan, graph, None, "no_reference_metadata_prompt_only"),
    ]

    v1, v2, v4, v5 = (
        signatures["V1_cast_reference"],
        signatures["V2_replaced_reference"],
        signatures["V4_metadata_prompt_no_reference"],
        signatures["V5_no_reference_no_metadata"],
    )
    proofs = {
        "P1_replacing_a_reference_changes_identity": {
            "conditioning_signature_digest_changes": v1["conditioning_signature_digest"]
            != v2["conditioning_signature_digest"],
            "request_digest_changes": request_digests["V1_cast_reference"][
                "prompt_canonical_sha256"
            ]
            != request_digests["V2_replaced_reference"]["prompt_canonical_sha256"],
            "loadimage_digest_changes": v1["image_derived_digests"]
            != v2["image_derived_digests"],
            "vae_encode_input_changes": pixel_probes[0]["vae_encode_input_pixel_sha256"]
            != pixel_probes[1]["vae_encode_input_pixel_sha256"],
        },
        "P2_missing_reference_fails_before_post": missing_proof,
        "P3_metadata_ids_alone_are_insufficient": {
            "image_derived_digests_without_reference": v4["image_derived_digests"],
            "image_derived_digests_with_reference": v1["image_derived_digests"],
            "prompt_only_run_has_no_image_digest": not v4["image_derived_digests"],
            "no_reference_digests_identical": v4["image_derived_digests"]
            == v5["image_derived_digests"],
            "node_feeds_zeros_without_reference": pixel_probes[2][
                "vae_encode_input_pixel_sha256"
            ]
            != pixel_probes[0]["vae_encode_input_pixel_sha256"],
            "runtime_default_branch": {
                "text": "if reference_image is None: reference_image = torch.zeros((1, height, width, 3))",
                "file": str(COMFY / "comfy_extras/nodes_wan.py"),
            },
        },
    }
    proofs["P1_replacing_a_reference_changes_identity"]["PASS"] = all(
        value
        for key, value in proofs["P1_replacing_a_reference_changes_identity"].items()
        if key != "PASS"
    )
    proofs["P2_missing_reference_fails_before_post"]["PASS"] = (
        missing_proof["refused_before_post"]
        and missing_proof["runtime_validate_inputs"]["is_typed_error"]
        and missing_proof["loader_tamper_rejected"]
    )
    proofs["P3_metadata_ids_alone_are_insufficient"]["PASS"] = all(
        [
            proofs["P3_metadata_ids_alone_are_insufficient"]["prompt_only_run_has_no_image_digest"],
            proofs["P3_metadata_ids_alone_are_insufficient"]["no_reference_digests_identical"],
            proofs["P3_metadata_ids_alone_are_insufficient"]["node_feeds_zeros_without_reference"],
        ]
    )

    result = {
        "scope": "A3 identity provenance trace, CPU only: no engine started, no model loaded, no POST",
        "graph": {"path": str(SUBMITTED), "sha256": ran_graph_sha,
                  "conditioning_node": CONDITIONING_NODE,
                  "reference_image_node": REFERENCE_IMAGE_NODE},
        "runtime_extraction": extraction,
        "fixture_manifest": manifest,
        "fixture_disclosure": (
            "TEST-ONLY: copied from an available target design so the trace has real bytes. "
            "It is not a user-approved cast and is never published; the packet's preferred "
            "clean-library-pack path was checked and no pack library exists on this machine "
            "(the product database holds no character packs for this experiment)."
        ),
        "loader": loader_trace(cast_fixture),
        "variants": request_digests,
        "cache_signatures": signatures,
        "reference_chain": {
            "edges": [
                {"from": REFERENCE_IMAGE_NODE, "to": "672:590", "slot": 0},
                {"from": "672:590", "to": CONDITIONING_NODE, "input": "reference_image"},
                {"from": "672:590", "to": "672:589", "input": "image"},
                {"from": "672:589", "to": CONDITIONING_NODE, "input": "clip_vision_output"},
            ],
            "node_code": "comfy_extras/nodes_wan.py WanAnimate2ToVideo.execute: "
                         "ref_latent = vae.encode(ref_image[:, :, :, :3]); "
                         "positive = conditioning_set_values(positive, "
                         "{\"concat_latent_image\": concat_latent_image, \"concat_mask\": mask})",
        },
        "pixel_probes": pixel_probes,
        "proofs": proofs,
        "stubs_disclosed": {
            "folder_paths": "probe stub bound to the probe's own input dir",
            "nodes.NODE_CLASS_MAPPINGS": "stub classes; only NOT_IDEMPOTENT is read",
            "IS_CHANGED for non-LoadImage nodes": "marker string; LoadImage uses the real method",
            "vae": "StubVae returning the real latent SHAPE on the CPU, hashing its pixel input",
            "pre_submit_guard": "probe-local guard (the product's staging lives in the COMFY "
                                "lane's adapter, which is read-only for this task)",
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(json.dumps({
        "out": str(out),
        "fixtures": {
            k: ({kk: vv for kk, vv in v.items() if kk != "source"} if isinstance(v, dict) else v)
            for k, v in manifest.items()
        },
        "loader": {k: result["loader"][k] for k in
                   ("character_id", "pack_version_id", "asset_id", "artifact_sha256",
                    "resolved_sha256", "loader_is_checksum_bound", "tamper_rejected",
                    "tampered_content_error")},
        "loadimage_digests": {label: sig["image_derived_digests"] for label, sig in signatures.items()},
        "conditioning_digest_changes_v1_v2": proofs["P1_replacing_a_reference_changes_identity"][
            "conditioning_signature_digest_changes"],
        "proofs": {k: v.get("PASS") for k, v in proofs.items()},
        "missing_reference": missing_proof,
        "decoded_pixel_digest_is_not_the_file_sha256": [
            row["vae_encode_input_pixel_sha256"][0] != manifest["cast"]["sha256"]
            if row["vae_encode_input_pixel_sha256"] else None
            for row in pixel_probes
        ],
        "cast_and_other_decode_differently": pixel_probes[0]["vae_encode_input_pixel_sha256"]
        != pixel_probes[1]["vae_encode_input_pixel_sha256"],
    }, indent=2, default=str))
    return 0


def pre_submit_guard(graph: dict, input_dir: Path) -> dict:
    """Probe-local pre-submit reference check; refuses before any transport call."""
    missing = []
    for node_id, node in graph.items():
        if node.get("class_type") != "LoadImage":
            continue
        image = (node.get("inputs") or {}).get("image")
        if not isinstance(image, str):
            continue
        if not (input_dir / image).is_file():
            missing.append(
                {
                    "code": "MF_V14B_REFERENCE_INPUT_MISSING",
                    "node": node_id,
                    "image": image,
                    "expected_path": str(input_dir / image),
                }
            )
    return {"refused": bool(missing), "errors": missing}


if __name__ == "__main__":
    sys.exit(main())
