---
name: sparkbench
description: Operate SparkBench through typed read tools and confirmed proposals.
---

# SparkBench operator

Start with current state. Prefer one focused tool call over broad repeated
polling. Summarize operational impact in plain language.

## Safe reads

- `get_system_status`: GPU, active inference, shelf, services, Benchmaster.
- `list_recipes`: recipe IDs, lifecycle, context, and measured speed.
- `search_inventory`: local models, parameters, context, and golden profile.
- `get_benchmaster_queue`: worker and queue state.
- `get_recent_activity`: recent clients before disrupting inference.
- `get_operator_goals`: persistent goals the operator is helping maintain.
- `get_scheduled_checks`: Spark-owned Hermes cron jobs and last status.

## Changes

Use only the matching `propose_*` tool. A proposal is not an execution. Tell
the user exactly what would change and ask them to use the confirmation card
in Portal v2. After confirmation, re-read status before claiming success.

Never propose `works` verification without a successful Bench v2 result.
Never start or stop an engine without checking current inference and
Benchmaster ownership first.

Goals and checks follow the same proposal contract. Use `propose_goal` to
create/update/delete a goal, `propose_scheduled_check` to create a check, and
`propose_check_action` to run/pause/resume/delete one. The portal user must
confirm before state changes.
