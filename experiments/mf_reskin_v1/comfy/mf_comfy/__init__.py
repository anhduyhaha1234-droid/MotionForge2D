"""MotionForge ComfyUI stage adapter (MF-V1-COMFY).

Isolated local execution adapter for ComfyUI: lifecycle, typed failures,
hash pinning, exclusive instance lease, single heavy-GPU-stage gate and a
self-describing stage contract.
"""
from .adapter import ComfyStageAdapter, RunSpec
from .contract import SCHEMA, StageInput, StageOutput, build_stage_contract, write_json
from .errors import MfComfyError
from .gpugate import GpuStageGate
from .lease import InstanceEpoch, InstanceLease, pid_alive
from .paths import StagePaths
from .pinning import hash_node_inventory, hash_workflow, sha256_file
from .resources import NullSampler, ResourceSampler
from .transport import HttpTransport, SubmitResult, parse_base_url

__all__ = [
    "ComfyStageAdapter", "RunSpec", "SCHEMA", "StageInput", "StageOutput",
    "build_stage_contract", "write_json", "MfComfyError", "GpuStageGate",
    "InstanceEpoch", "InstanceLease", "pid_alive", "StagePaths",
    "hash_node_inventory", "hash_workflow", "sha256_file", "NullSampler",
    "ResourceSampler", "HttpTransport", "SubmitResult", "parse_base_url",
]
