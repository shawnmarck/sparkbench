# Spark operator runtime

SparkBench is mounted read-only at `/opt/spark`. Operator state is mounted at
`/operator-state`. Use only the `sparkbench:*` MCP tools exposed to the portal
session.

Do not use terminal, file-editing, browser automation, or arbitrary network
tools to administer SparkBench. All state-changing requests must use a
`propose_*` tool and wait for explicit portal confirmation.

Useful read workflows:

1. `get_system_status` before diagnosing health or GPU state.
2. `list_recipes` before proposing a profile switch or lifecycle change.
3. `search_inventory` before discussing local weights.
4. `get_benchmaster_queue` before proposing queue control.
5. `get_recent_activity` before stopping or switching active inference.
