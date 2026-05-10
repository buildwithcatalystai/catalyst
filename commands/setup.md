---
description: Configure the Catalyst plugin (backend URL + shared secret). Run once after install.
argument-hint: ""
---

Configure the Catalyst plugin so its hooks can talk to the wizard backend.

## What to do

1. **Ask the user for two values:**
   - **Catalyst backend URL** — the wizard host the PostToolUse hook posts events to (e.g. `http://13.202.117.250:8000` or `http://localhost:8000`).
   - **Shared secret** — the value of `CATALYST_MCP_SECRET` from the wizard's own `.env`. They must obtain it from their Catalyst operator. Without it the backend will reject every event with HTTP 403.

   Use `AskUserQuestion` with two short-text prompts. Default the backend URL to `http://localhost:8000` if they don't say.

2. **Write `~/.claude/.env.catalyst`** with the two values. Use the `Bash` tool with this exact pattern (substituting the values):

   ```sh
   umask 077 && cat > ~/.claude/.env.catalyst <<'EOF'
   CATALYST_BACKEND_URL=<value>
   CATALYST_MCP_SECRET=<value>
   EOF
   chmod 600 ~/.claude/.env.catalyst
   ```

   `umask 077` + explicit `chmod 600` makes the file owner-readable only so other local users can't read the secret.

3. **Confirm** to the user:
   - The file path written.
   - That the values take effect on the **next** Catalyst MCP tool call (no restart needed for the hook — it re-reads on each invocation).
   - That `/catalyst:setup` is safe to re-run any time they need to rotate the secret or switch backends.

## Notes

- If `~/.claude/.env.catalyst` already exists, show its current `CATALYST_BACKEND_URL` (mask the secret) before overwriting — let them confirm.
- Never echo the secret back in chat output after writing. Refer to it as "secret stored".
- If the user only wants to change one value, read the file first and preserve the other.
