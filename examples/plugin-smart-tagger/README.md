> ⚠️ **DEPRECATED**: This example plugin has a known bug — it uses the `on_store` hook (fires *after* storage), so tag modifications are **not persisted** to the database. Use the built-in [`memory_os_plugins.smart_tagger`](../../memory-os-plugins/src/memory_os_plugins/smart_tagger/) package instead, which correctly uses the `before_store` hook.

# Plugin: Smart Tagger

Auto-tags memories on store and boosts mistake-notes on retrieve.

## Features

1. **Auto-tagging**: Detects patterns in content and adds semantic tags (decision, bug, convention, database, infra, etc.)
2. **Mistake-note boost**: When retrieving memories, results tagged `mistake-note` get a configurable score boost — so past errors surface before you repeat them.

## Install

```bash
pip install -e examples/plugin-smart-tagger/
# Restart mcp-memory-service
```

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `MCP_PLUGIN_SMART_TAGGER_ENABLED` | `true` | Enable/disable the plugin |
| `MCP_PLUGIN_SMART_TAGGER_BOOST` | `0.15` | Score boost for mistake-notes on retrieve |

## Extending

Add your own tag rules by editing `TAG_RULES` in `__init__.py`. Each rule is a `(regex_pattern, tag_name)` tuple.
