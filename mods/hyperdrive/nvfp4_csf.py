# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
# Modified for Hyperdrive: the _hd_* functions and HYPERDRIVE_CSF_* switches.
"""Lossless NVFP4 expert scale storage with native ModelOpt arithmetic."""

import itertools
import os
import time
from dataclasses import dataclass, field, fields, is_dataclass, replace

import regex as re
import torch

import vllm.envs as envs
from vllm.config import get_current_vllm_config_or_none
from vllm.model_executor.layers.fused_moe import modular_kernel as mk
from vllm.model_executor.layers.fused_moe.activation import MoEActivation
from vllm.model_executor.layers.fused_moe.b12x import (
    B12xExperts,
    _is_current_stream_capturing,
)
from vllm.model_executor.layers.fused_moe.config import (
    nvfp4_moe_quant_config,
    nvfp4_w4a16_moe_quant_config,
)
from vllm.model_executor.layers.fused_moe.fused_moe_method_base import (
    FusedMoEMethodBase,
)
from vllm.model_executor.layers.fused_moe.prepare_finalize.no_dp_ep import (
    MoEPrepareAndFinalizeNoDPEPModular,
)
from vllm.model_executor.weight_transfer import copy_weight, materialize_weight
from vllm.utils.b12x import get_b12x_a16_max_tokens, is_b12x_a4_prefill_enabled
from vllm.utils.math_utils import round_up
from vllm.utils.torch_utils import set_default_torch_num_threads

_FORWARD_TOKENS = itertools.count()

# Hyperdrive: per-layer scales expanded once at load, no per-call CSF decode. Everything below
# is inert unless HYPERDRIVE_CSF_STATIC=1 or HYPERDRIVE_CSF_LOG=1.
_HD_STATIC = os.environ.get("HYPERDRIVE_CSF_STATIC") == "1"
_HD_FREE = os.environ.get("HYPERDRIVE_CSF_STATIC_FREE") == "1"
_HD_LOG = os.environ.get("HYPERDRIVE_CSF_LOG") == "1"
_HD_LAYERS = os.environ.get("HYPERDRIVE_CSF_STATIC_LAYERS", "all")
_HD_STATIC_PTRS: set[int] = set()
# Deferred mode: load stock, then expand into per-layer scales after load_model, past the load
# memory dip and before b12x preparation binds any storage. Layers it cannot convert stay stock.
_HD_DEFER = os.environ.get("HYPERDRIVE_CSF_STATIC_DEFER") == "1"
_HD_VERIFY = os.environ.get("HYPERDRIVE_CSF_STATIC_VERIFY") == "1"
_HD_MIN_GIB = float(os.environ.get("HYPERDRIVE_CSF_STATIC_MIN_GIB", "6"))
_HD_PENDING: list = []
_HD_CONVERTED: list = []
_HD_LOG_LEFT = [960]


def _hd_layer_is_static(index: int) -> bool:
    if not _HD_STATIC:
        return False
    return _HD_LAYERS == "all" or index in {int(i) for i in _HD_LAYERS.split(",")}


def _hd_install_decode_patch() -> None:
    from b12x._lib.quant.nvfp4_csf import Nvfp4CsfDecoder

    if getattr(Nvfp4CsfDecoder, "_hd_patched", False):
        return
    stock = Nvfp4CsfDecoder.decode

    def decode(self, ids, out13, out2, *, barriers=None):
        if _HD_LOG and _HD_LOG_LEFT[0] > 0:
            if _HD_LOG_LEFT[0] == 960:
                print(f"HD_CSF implementation_micro={barriers is not None}", flush=True)
            if not _is_current_stream_capturing() and ids.numel() < 64:
                _HD_LOG_LEFT[0] -= 1
                print(f"HD_CSF routes={ids.numel()} distinct={ids.unique().numel()}", flush=True)
        if out13.data_ptr() in _HD_STATIC_PTRS:
            # Scales are already in place; keep only the barrier reset the MoE expects.
            if barriers is not None:
                barriers[0].zero_()
                barriers[1].zero_()
            return
        return stock(self, ids, out13, out2, barriers=barriers)

    Nvfp4CsfDecoder.decode = decode
    Nvfp4CsfDecoder._hd_patched = True


def _hd_free_tensors(value, seen=None) -> int:
    """Release the compressed planes held by a decoder; returns bytes released."""
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    if isinstance(value, torch.Tensor):
        freed = value.numel() * value.element_size()
        value.data = value.data.new_empty(0)
        return freed
    if isinstance(value, (tuple, list)):
        return sum(_hd_free_tensors(v, seen) for v in value)
    if hasattr(value, "__dict__") and type(value).__module__.startswith(("b12x", "flashinfer")):
        return sum(_hd_free_tensors(v, seen) for v in vars(value).values())
    return 0


def _hd_mem_available_gib() -> float:
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1048576
    return 0.0


def _hd_holds(value, ptrs, seen=None) -> bool:
    """Whether a prepared-weights tree still references one of these tensor addresses."""
    seen = set() if seen is None else seen
    if id(value) in seen:
        return False
    seen.add(id(value))
    if isinstance(value, torch.Tensor):
        return value.numel() > 0 and value.data_ptr() in ptrs
    if isinstance(value, (tuple, list)):
        return any(_hd_holds(v, ptrs, seen) for v in value)
    if is_dataclass(value) and not isinstance(value, type):
        return any(_hd_holds(getattr(value, f.name), ptrs, seen) for f in fields(value))
    return False


def _hd_repoint(impl, old, new):
    """The same field replacement CSF preparation makes, aimed at new scale storage."""
    rep = impl.representation
    native = None if rep is None else rep.value
    if native is not None:
        moved = {
            name: new[i]
            for name, i in (
                ("w13_scale", 0),
                ("micro_w13_scale", 0),
                ("w2_scale", 1),
                ("micro_w2_scale", 1),
            )
            if getattr(native, name, None) is old[i]
        }
        if moved:
            rep = replace(rep, value=replace(native, **moved))
    return replace(impl, representation=rep, w1_blockscale=new[0], w2_blockscale=new[1])


def _hd_materialize_static() -> None:
    pending = sorted(_HD_PENDING, key=lambda item: item[0].layer_index)
    _HD_PENDING.clear()
    if not pending:
        return
    start, first_avail, done = time.perf_counter(), _hd_mem_available_gib(), 0
    with torch.no_grad():
        for method, layer in pending:
            avail = _hd_mem_available_gib()
            if avail < _HD_MIN_GIB:
                print(f"HD_CSF defer_stopped layer={method.layer_index} avail_gib={avail:.1f}", flush=True)
                break
            done += method._hd_make_static(layer)
    print(
        f"HD_CSF defer_done converted={done}/{len(pending)} s={time.perf_counter() - start:.2f} "
        f"avail_gib={first_avail:.1f}->{_hd_mem_available_gib():.1f}",
        flush=True,
    )


def _hd_free_converted() -> None:
    freed = 0
    for method in _HD_CONVERTED:
        decoder = method.prepared._impl.nvfp4_csf
        if decoder is not None and not getattr(method, "_hd_freed", False):
            method._hd_freed = True
            freed += _hd_free_tensors((decoder.first, decoder.second))
    torch.cuda.empty_cache()
    print(f"HD_CSF defer_freed layers={len(_HD_CONVERTED)} bytes={freed}", flush=True)


def _hd_install_worker_hook() -> None:
    from vllm.v1.worker.gpu_worker import Worker

    if getattr(Worker, "_hd_hooked", False):
        return
    begin, measure = Worker.begin_b12x_preparation, Worker.determine_available_memory

    def begin_b12x_preparation(self, **kwargs):
        if kwargs.get("stage", "weights") == "weights":
            _hd_materialize_static()
        return begin(self, **kwargs)

    def determine_available_memory(self, *args, **kwargs):
        # Late enough that weights preparation is over, early enough to count toward the KV cache.
        if _HD_FREE:
            if getattr(self, "_b12x_startup_coordinator", None) is None:
                _hd_free_converted()
            else:
                print("HD_CSF defer_free_skipped preparation_active", flush=True)
        return measure(self, *args, **kwargs)

    Worker.begin_b12x_preparation = begin_b12x_preparation
    Worker.determine_available_memory = determine_available_memory
    Worker._hd_hooked = True


def _forward_token() -> int | None:
    """An id of the current forward pass, or None outside of one."""
    from vllm.forward_context import get_forward_context, is_forward_context_available

    if not is_forward_context_available():
        return None
    context = get_forward_context()
    token = context.additional_kwargs.get("b12x_csf_token")
    if token is None:
        token = next(_FORWARD_TOKENS)
        context.additional_kwargs["b12x_csf_token"] = token
    return token


@dataclass
class Nvfp4CsfState:
    scale_scratch: tuple[torch.Tensor, ...] | None = None
    scale_layers: dict[int, "Nvfp4CsfMoEMethod"] = field(default_factory=dict)
    scale_stream: torch.cuda.Stream | None = None
    scale_prefetch: tuple[int, int, torch.cuda.Event] | None = None


class Nvfp4CsfMoEMethod(FusedMoEMethodBase):
    """Decode selected scale planes into model-owned native E4M3 scratch."""

    def __init__(self, moe, owner, *, use_a16=False, encoding="csf_32x2_v1"):
        super().__init__(moe)
        self.encoding = encoding
        self.owner = owner
        self.use_a16 = use_a16 or bool(envs.VLLM_B12X_MOE_FP4_FORCE_A16)
        config = get_current_vllm_config_or_none()
        if config is not None and (
            config.parallel_config.pipeline_parallel_size != 1
            or config.parallel_config.use_ubatching
        ):
            raise NotImplementedError(
                "CSF shared scratch requires PP1 without ubatching"
            )
        parallel = moe.moe_parallel_config
        if (
            parallel.use_ep
            or parallel.ep_size != 1
            or parallel.dp_size != 1
            or parallel.use_all2all_kernels
            or parallel.enable_eplb
        ):
            raise NotImplementedError("NVFP4-CSF supports TP without EP/DP")
        if (
            moe.activation != MoEActivation.SILU
            or moe.in_dtype != torch.bfloat16
            or moe.has_bias
        ):
            raise ValueError("NVFP4-CSF requires bias-free BF16 SwiGLU experts")

    def create_weights(
        self,
        layer,
        num_experts,
        hidden_size,
        intermediate_size_per_partition,
        params_dtype,
        **extra_weight_attrs,
    ):
        match = re.search(r"(?:^|\.)layers\.(\d+)\.", layer.layer_name)
        if match is None or params_dtype != torch.bfloat16:
            raise ValueError("NVFP4-CSF requires a numbered BF16 expert layer")
        self.layer_index = int(match.group(1))
        self.num_experts, self.hidden_size = num_experts, hidden_size
        self.local_intermediate = intermediate_size_per_partition
        # A TP-padded expert (GLM-5.3 at TP6) keeps its checkpoint width.
        vllm_config = get_current_vllm_config_or_none()
        model_config = getattr(vllm_config, "model_config", None)
        self.checkpoint_width = getattr(
            getattr(model_config, "hf_text_config", None),
            "original_moe_intermediate_size",
            None,
        )
        self._components = {}
        self._scale_parts = {}
        self._seen = set()
        self._packed: tuple[torch.Tensor, torch.Tensor] | None = None
        for prefix in ("w13", "w2"):
            for component, dtype in (
                ("weight", torch.uint8),
                ("weight_scale_2", torch.float32),
                ("input_scale", torch.float32),
            ):
                param = torch.nn.Parameter(
                    torch.empty(0, dtype=dtype), requires_grad=False
                )
                param.weight_loader = self.weight_loader
                param.csf_component = component
                layer.register_parameter(f"{prefix}_{component}", param)
            scales = torch.nn.Module()
            fields = (
                (("fixed", torch.uint8), ("exceptions", torch.uint32))
                if self.encoding == "csf"
                else (
                    ("bases", torch.uint8),
                    ("codes", torch.uint8),
                    ("page_bases", torch.uint32),
                    ("offsets", torch.uint16),
                    ("exceptions", torch.uint16),
                )
            )
            for component, dtype in fields:
                param = torch.nn.Parameter(
                    torch.empty(0, dtype=dtype), requires_grad=False
                )
                param.weight_loader = self.weight_loader
                param.csf_component = component
                scales.register_parameter(
                    f"{'nvfp4_csf' if self.encoding == 'csf' else 'csf32'}_{component}",
                    param,
                )
            layer.add_module(f"{prefix}_weight_scale", scales)

    def weight_loader(
        self,
        param,
        loaded_weight,
        weight_name=None,
        shard_id=None,
        expert_id=None,
        return_success=False,
    ):
        from b12x.loader._csf_source import stage_csf_sources

        if (
            shard_id not in ("w1", "w2", "w3")
            or expert_id is None
            or not 0 <= expert_id < self.num_experts
        ):
            raise ValueError("CSF tensor requires a valid expert and projection")
        field_name = param.csf_component
        key = (expert_id, shard_id)
        identity = (*key, field_name)
        if identity in self._seen:
            raise ValueError(f"Duplicate CSF tensor: {identity}")
        self._seen.add(identity)
        width = self.checkpoint_width or self.local_intermediate * self.moe.tp_size
        first = self.moe.tp_rank * self.local_intermediate
        last = min(first + self.local_intermediate, width)
        if first >= last:
            raise ValueError("CSF TP rank has no checkpoint channels")
        h, n = self.hidden_size, self.local_intermediate
        values = self._components.setdefault(key, {})
        if field_name == "weight":
            expected = (h, width // 2) if shard_id == "w2" else (width, h // 2)
            if (
                tuple(loaded_weight.shape) != expected
                or loaded_weight.dtype != torch.uint8
            ):
                raise ValueError(f"Invalid NVFP4 weight shape or dtype: {weight_name}")
            if self._packed is None:
                # Projections land directly in the layer's packed FC1 (up/gate
                # rows) and FC2 weights. Per-expert device tensors fragment the
                # caching allocator across a large model.
                self._packed = (
                    torch.zeros(
                        (self.num_experts, 2 * n, h // 2),
                        dtype=torch.uint8,
                        device=param.device,
                    ),
                    torch.zeros(
                        (self.num_experts, h, n // 2),
                        dtype=torch.uint8,
                        device=param.device,
                    ),
                )
            w13, w2 = self._packed
            if shard_id == "w2":
                local = w2[expert_id]
                copy_weight(
                    local[:, : (last - first) // 2],
                    loaded_weight[:, first // 2 : last // 2],
                )
            else:
                local = w13[expert_id, :n] if shard_id == "w3" else w13[expert_id, n:]
                copy_weight(local[: last - first], loaded_weight[first:last])
            values[field_name] = local
        elif field_name in ("weight_scale_2", "input_scale"):
            if loaded_weight.numel() != 1 or loaded_weight.dtype != torch.float32:
                raise ValueError(f"CSF {field_name} must contain one FP32 value")
            values[field_name] = materialize_weight(loaded_weight).cpu()
        else:
            parts = self._scale_parts.setdefault(key, {})
            parts[field_name] = materialize_weight(loaded_weight)
            if len(parts) == (2 if self.encoding == "csf" else 5):
                if shard_id == "w2":
                    rows, columns = h, width // 16
                    row_slice, column_slice = (0, h), (first // 16, last // 16)
                    out_rows, out_columns = h, n // 16
                else:
                    rows, columns = width, h // 16
                    row_slice, column_slice = (first, last), (0, columns)
                    out_rows, out_columns = n, columns
                fields = (
                    ("fixed", "exceptions")
                    if self.encoding == "csf"
                    else ("bases", "codes", "page_bases", "offsets", "exceptions")
                )
                values["scales"] = stage_csf_sources(
                    [tuple(parts[field] for field in fields)],
                    rows=rows,
                    columns=columns,
                    quantization="nvfp4",
                    encoding=self.encoding,
                    device=param.device,
                    row_range=row_slice,
                    column_range=column_slice,
                    padded_rows=out_rows,
                    padded_columns=out_columns,
                    padding_base=0x38,
                )
                del self._scale_parts[key]
        return True if return_success else None

    def _expert_tensors(self):
        from vllm.model_executor.model_loader.csf_utils import CsfMatrix

        from .utils.nvfp4_csf_utils import TensorView

        for expert in range(self.num_experts):
            projections = []
            for shard in ("w3", "w1", "w2"):
                values = self._components.get((expert, shard), {})
                required = {"weight", "scales", "weight_scale_2"}
                if not self.use_a16:
                    required.add("input_scale")
                missing = required - values.keys()
                if missing:
                    raise ValueError(
                        f"Missing CSF tensors for expert {expert}/{shard}: "
                        f"{sorted(missing)}"
                    )
                projections.append(
                    CsfMatrix(
                        weight=TensorView(values["weight"]),
                        scales=values["scales"],
                        global_scale=values["weight_scale_2"],
                        input_scale=values.get(
                            "input_scale",
                            torch.ones((), dtype=torch.float32, device="cpu"),
                        ),
                    )
                )
            yield tuple(projections)

    def get_fused_moe_quant_config(self, layer):
        return self.moe_quant_config

    def process_weights_after_loading(self, layer):
        from b12x.moe import fused_moe

        from .utils.nvfp4_csf_utils import prepare_nvfp4_csf_weights

        device = layer.w13_weight.device
        e, h, n = self.num_experts, self.hidden_size, self.local_intermediate
        # Native E4M3 scale storage: the F8_128x4 grid (rows in 128s, k-groups
        # in 4s), which TP-padded shards (GLM-5.3 TP6: 352 channels) fill.
        shapes = (
            (e, round_up(2 * n, 128), h // 16),
            (e, h, round_up(n // 16, 4)),
        )
        hd_wanted = _hd_layer_is_static(self.layer_index)
        self._hd_static = hd_wanted and not _HD_DEFER
        if hd_wanted or _HD_LOG:
            _hd_install_decode_patch()
        if self.owner.scale_scratch is None and not self._hd_static:
            self.owner.scale_scratch = tuple(
                torch.empty(s, dtype=torch.float8_e4m3fn, device=device) for s in shapes
            )
        scratch = (
            tuple(torch.empty(s, dtype=torch.float8_e4m3fn, device=device) for s in shapes)
            if self._hd_static
            else self.owner.scale_scratch
        )
        if any(
            tuple(t.shape) != s or t.device != device for t, s in zip(scratch, shapes)
        ):
            raise ValueError("NVFP4-CSF shared scratch geometry/device mismatch")
        with set_default_torch_num_threads(1):
            weights = prepare_nvfp4_csf_weights(
                self._expert_tensors(),
                num_experts=e,
                hidden_size=h,
                intermediate_size=n,
                tp_rank=0,
                tp_size=1,
                device=device,
                w13_scale_scratch=scratch[0],
                w2_scale_scratch=scratch[1],
                local_size=n,
                packed=self._packed,
            )
        self._components.clear()
        self._scale_parts.clear()
        self._seen.clear()
        self._packed = None
        packed = weights.packed
        layer_max = envs.VLLM_B12X_MOE_FP4_LAYER_MAX_INPUT_SCALE
        packed = replace(
            packed,
            input_scale=(
                packed.input_scale.amin()
                if layer_max in ("1", "all", "w13")
                else packed.input_scale
            ),
            intermediate_scale=(
                packed.intermediate_scale.amin()
                if layer_max in ("1", "all", "w2")
                else packed.intermediate_scale
            ),
        )
        weights = replace(weights, packed=packed)
        plan = fused_moe.plan_weights(
            source=fused_moe.PackedSource(format="modelopt_nvfp4", w13_layout="w13"),
            activation=fused_moe.ActivationSpec(
                mode="a16" if self.use_a16 else "a4",
                nonlinearity="silu",
                io_dtype=torch.bfloat16,
                swiglu_limit=self.moe.swiglu_limit,
                a16_max_tokens=(
                    get_b12x_a16_max_tokens()
                    if self.use_a16 and not is_b12x_a4_prefill_enabled()
                    else 0
                ),
            ),
            geometry=fused_moe.MoEGeometry(
                num_experts=e, hidden_size=h, intermediate_size=n
            ),
        )
        prepared = fused_moe.prepare_weights(plan=plan, weights=weights)
        quant_builder = (
            nvfp4_w4a16_moe_quant_config if self.use_a16 else nvfp4_moe_quant_config
        )
        self.moe_quant_config = quant_builder(
            g1_alphas=packed.w13_global_scales,
            g2_alphas=packed.w2_global_scales,
            **(
                {}
                if self.use_a16
                else {
                    "a1_gscale": packed.input_scale,
                    "a2_gscale": packed.intermediate_scale,
                }
            ),
            w1_scale=scratch[0],
            w2_scale=scratch[1],
            gemm1_clamp_limit=self.moe.swiglu_limit,
        )
        backend = B12xExperts(self.moe, self.moe_quant_config)
        backend.install_prepared_experts(layer, prepared)
        self.moe_kernel = mk.FusedMoEKernel(
            MoEPrepareAndFinalizeNoDPEPModular(), backend
        )
        self.backend, self.prepared = backend, prepared
        self.moe_done = torch.cuda.Event()
        self.scales_ready = torch.cuda.Event()
        if self._hd_static:
            fused_moe.expand_scales(prepared)
            torch.cuda.synchronize(device)
            _HD_STATIC_PTRS.add(prepared._impl.w1_blockscale.data_ptr())
        elif self.use_a16 and envs.VLLM_B12X_CSF_SCALE_PREFETCH:
            self.owner.scale_layers[self.layer_index] = self
            if self.owner.scale_stream is None:
                self.owner.scale_stream = torch.cuda.Stream(device)
        if hd_wanted and _HD_DEFER:
            _HD_PENDING.append((self, layer))
            _hd_install_worker_hook()

    def _hd_make_static(self, layer) -> int:
        """Move this layer from shared scratch to its own expanded scales; 1 if converted."""
        from b12x.moe import fused_moe

        impl = self.prepared._impl
        old = (impl.w1_blockscale, impl.w2_blockscale)
        buffers = tuple(s.clone() for s in self.owner.scale_scratch)
        new = tuple(
            b.view(torch.uint8).reshape(-1)[: o.numel() * o.element_size()].view(o.dtype).view_as(o)
            for b, o in zip(buffers, old, strict=True)
        )
        repointed = _hd_repoint(impl, old, new)
        if _hd_holds(repointed, {o.data_ptr() for o in old}):
            print(f"HD_CSF defer_skipped layer={self.layer_index} shared_scale_still_held", flush=True)
            return 0
        prepared = replace(self.prepared, _impl=repointed)
        fused_moe.expand_scales(prepared)
        if _HD_VERIFY and not _HD_CONVERTED:
            # Scales must not depend on what the buffer held before: expand over a sentinel.
            sentinel = tuple(
                torch.full((o.numel() * o.element_size(),), 0xA5, dtype=torch.uint8, device=o.device)
                .view(o.dtype)
                .view_as(o)
                for o in new
            )
            impl_decoder = repointed.nvfp4_csf
            impl_decoder.decode_all(*sentinel)
            torch.cuda.synchronize(new[0].device)
            diff = sum(
                int((a.view(torch.uint8) != b.view(torch.uint8)).sum())
                for a, b in zip(new, sentinel, strict=True)
            )
            print(f"HD_CSF defer_verify layer={self.layer_index} differing_bytes={diff}", flush=True)
            del sentinel
        torch.cuda.synchronize(new[0].device)
        q = self.moe_quant_config
        if hasattr(q, "_w1") and hasattr(q, "_w2"):
            q._w1.scale, q._w2.scale = buffers
        self.backend._plan, self.backend._plan_key = None, None
        self.backend._prepared_experts = prepared
        layer._b12x_prepared_experts = prepared
        self.prepared = prepared
        self.owner.scale_layers.pop(self.layer_index, None)
        self.owner.scale_prefetch = None
        _HD_STATIC_PTRS.add(new[0].data_ptr())
        self._hd_static = True
        _HD_CONVERTED.append(self)
        return 1

    def apply(
        self,
        layer,
        x,
        topk_weights,
        topk_ids,
        shared_experts,
        shared_experts_input,
        workspace=None,
    ):
        moe_kernel = self.moe_kernel
        assert moe_kernel is not None

        def run():
            return moe_kernel.apply(
                hidden_states=x,
                w1=layer.w13_weight,
                w2=layer.w2_weight,
                topk_weights=topk_weights,
                topk_ids=topk_ids,
                activation=layer.activation,
                global_num_experts=layer.global_num_experts,
                expert_map=layer.expert_map,
                apply_router_weight_on_input=layer.apply_router_weight_on_input,
                shared_experts=shared_experts,
                shared_experts_input=shared_experts_input,
                workspace=workspace,
            )

        if self._hd_static:
            if _HD_FREE and not _HD_DEFER and not _is_current_stream_capturing() and x.shape[0] >= 2048:
                decoder = self.prepared._impl.nvfp4_csf
                if decoder is not None and not getattr(self, "_hd_freed", False):
                    self._hd_freed = True
                    freed = _hd_free_tensors((decoder.first, decoder.second))
                    print(f"HD_CSF layer={self.layer_index} freed_bytes={freed}", flush=True)
            # Large calls take the same expanded-scale path stock takes after a prefetch.
            self.backend.scales_expanded = not _is_current_stream_capturing() and (
                self._prefetches_all_experts(x, topk_ids)
            )
            try:
                return run()
            finally:
                self.backend.scales_expanded = False
        owner = self.owner
        if self.layer_index not in owner.scale_layers or _is_current_stream_capturing():
            return run()
        token = _forward_token()
        pending, owner.scale_prefetch = owner.scale_prefetch, None
        stream = torch.cuda.current_stream()
        if pending is not None:
            # The shared scratch must never race an expansion still in flight.
            stream.wait_event(pending[2])
        self.backend.scales_expanded = (
            token is not None
            and pending is not None
            and (pending[:2] == (self.layer_index, token))
        )
        try:
            result = run()
        finally:
            self.backend.scales_expanded = False
        following = owner.scale_layers.get(self.layer_index + 1)
        if (
            token is not None
            and following is not None
            and following._prefetches_all_experts(x, topk_ids)
        ):
            # The next layer's MoE would expand its scales into the same scratch:
            # do it now on a side stream, overlapping that layer's attention.
            from b12x.moe import fused_moe

            self.moe_done.record(stream)
            side = owner.scale_stream
            side.wait_event(self.moe_done)
            with torch.cuda.stream(side):
                fused_moe.expand_scales(following.prepared)
                following.scales_ready.record(side)
            owner.scale_prefetch = (
                following.layer_index,
                token,
                following.scales_ready,
            )
        return result

    def _prefetches_all_experts(self, x: torch.Tensor, topk_ids: torch.Tensor) -> bool:
        """Whether prefetch matches the call's full-expert expansion workload."""
        if topk_ids.numel() < 16 * self.num_experts:
            return False
        if self.backend._a4_prefill_enabled:
            return self.backend.uses_expanded_nvfp4_scales(
                int(x.shape[0]), topk_ids.dtype
            )
        return True
