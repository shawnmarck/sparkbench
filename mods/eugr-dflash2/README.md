# eugr DFlash2 overlay (vLLM PR 52816)

Runtime mod. Overlays [vLLM PR 52816](https://github.com/vllm-project/vllm/pull/52816)
(`19c9351904df`) onto the installed `vllm-node` package so
`incoai/Qwen3.8-27B-DFlash2` (`DFlash2DraftModel`) loads.

Does **not** rebuild wheels. Applies only when the eugr service YAML lists:

```yaml
mods:
  - /opt/spark/mods/eugr-dflash2
```

Idempotent. DFlash v1, DSpark, and MTP checkpoints keep their existing loaders.
Without this overlay a DFlash2 checkpoint would draft as DFlash1 silently.

Pinned against eugr `vllm 0.27.2rc1.dev209+gf9f066d19`. Re-check `prod.patch`
after the next eugr wheel bump.
