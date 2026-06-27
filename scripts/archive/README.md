# Archived helper scripts

Ad-hoc shell helpers we used to seed the model shelf during the first few
months of SparkBench. They are **superseded by `spark hf queue add <repo>`**
and the queue worker (`bench-queue-worker.sh`), which is the supported way
to acquire models today.

Kept for historical reference. Not part of the install path. Safe to delete
this directory if you don't care about provenance — the catalog (`data/model-catalog.yaml`)
already records the final landing path for every model.

| File | What it grabbed |
|------|-----------------|
| `spark-download-models.sh` | Curated initial set (logged to `/opt/spark/logs/`) |
| `spark-download-deepseek-v4-flash-spark.sh` | DeepSeek-V4-Flash weights |
| `spark-download-gemma4.sh` | Gemma 4 family |
| `spark-download-qwen36-27b*.sh` | Qwen 3.6 27B variants — initial, missing-file, resume, MoQ, extras |
| `spark-download-step37-flash*.sh` | Step 3.7 Flash (full + UD-IQ3-S quant) |
| `spark-download-yuxinlu1-batch.sh` | yuxinlu1 community-tunes batch |
| `spark-download-queue-tail.sh` | Chained downloader (wait-then-run) |

## Want the modern equivalent?

```bash
# Single repo
spark hf queue add nvidia/Qwen3-30B-A3B-NVFP4

# Watch progress
spark hf queue list
spark hf queue tail
```
