# Siril MCP

Cursor/LLM control of a live **Siril** GUI session via an in-app Python bridge (Option B).

## Architecture

1. **Bridge** (`bridge/bridge.py`) — started inside Siril with `pyscript -async`. Talks to Siril through `sirilpy` and listens on a Unix socket.
2. **MCP server** (`siril-mcp`) — stdio MCP process for Cursor; forwards tools to the bridge.

```
Cursor → siril-mcp (stdio) → ~/Library/Application Support/siril-mcp/bridge.sock → bridge.py → Siril
```

## Setup

### 1. Install the MCP package

```bash
cd ~/code/siril-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Install the Siril Scripts launcher

```bash
./scripts/install_bridge_to_siril_scripts.sh
```

### 3. Start the bridge in Siril

Open **Siril.app**, then either:

- Command line in Siril: `pyscript -async /Users/nick/code/siril-mcp/bridge/bridge.py`
- Or run **Start_MCP_Bridge** from the Scripts menu after installing the helper (prefer async).

You should see `[siril-mcp] listening on .../bridge.sock` in the Siril log.

### 4. Register with Cursor

Add to your Cursor MCP config (e.g. `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "siril": {
      "command": "/Users/nick/code/siril-mcp/.venv/bin/siril-mcp",
      "args": []
    }
  }
}
```

Restart Cursor MCP / reload window after editing.

### Optional: StarNet

If you plan to use StarNet for star removal, ask your favorite LLM to install it for you (or install it yourself via Siril’s usual StarNet setup). This MCP stack does not install or configure StarNet; once it is available to Siril, scriptable StarNet commands work like any other command through the bridge.

## Tools

| Tool | Purpose |
|------|---------|
| `siril_ping` | Bridge health |
| `siril_get_state` | Loaded image, size, selection, cwd, keywords |
| `siril_list_commands` | Filterable scriptable command catalog |
| `siril_run_command` | Run one Siril command |
| `siril_run_script` | Run multi-line `.ssf` or `.py` |
| `siril_get_preview` | Autostretched PNG (optional ROI, max edge) |
| `siril_set_selection` | Set selection rectangle |
| `siril_get_stats` | Per-channel stats |
| `siril_undo` | Undo last op |

If the bridge is down, tools fail with an explicit start hint (they do **not** fall back to browsing the filesystem).

## Bridge limitations (what you don’t get yet)

This stack only reaches what **scripts / `sirilpy` already expose**. GUI-only or poorly scripted Siril features are out of scope for the bridge approach, including:

- Display / STF / `visu` state matching exactly what the user sees in the viewport
- Inspector-style diagnostics
- Curves, remixer, and compositing UI hooks (unless a documented command equivalent exists)
- Reliable sequence / `load_seq` context and Python-style metadata that today only exists on GUI-only paths
- True canvas screenshots (overlays, zoom, annotations) vs an autostretched `gfit` preview
- Attaching to Siril without manually starting the bridge (`pyscript -async`)
- Headless `siril-cli -p` as the primary control path (optional later; not what this bridge is)

If this project proves useful day-to-day, we may consider a **fully integrated** approach (a built-in Siril control socket / Option C), and/or **rewriting some of that GUI-only functionality in Siril** so it is also available via scripts and thus via MCP.

## Canonical test queries

See [PLAN.md](PLAN.md) section **Canonical test queries**. Quick smoke:

1. *Ping Siril and tell me if an image is loaded, its size, filename, and selection.*
2. *Show a preview of the current image (max 1024px) and describe it.*
3. *List stretch-related Siril commands.*

## Troubleshooting

- **Bridge not running:** start `pyscript -async` again; check `~/Library/Application Support/siril-mcp/bridge.status.json`.
- **Socket permissions:** socket is created mode `0600` under Application Support.
- **First Siril run:** wait until Siril finishes Python venv setup before starting the bridge.
- **Nested `pyscript`:** `siril_run_script` with `kind=py` runs sync `pyscript`; prefer `siril_run_command` for simple ops.

## Option C (later)

After this proves useful, promote the same tool contract into a built-in Siril control socket (see PLAN.md Phase 3).
