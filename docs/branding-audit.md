# Branding and naming audit (Serapis vs University Jarvis)

User-facing text (Hub pages, CLI program name `serapis`, README, docs, exports) says Serapis. Remaining Jarvis names are internal or legacy.

| Item | Status |
| --- | --- |
| Python package `university_jarvis` (imports, `serapis` console entry point, package data, tests, eval scripts) | Kept for compatibility. **Deferred:** rename to `serapis` in one dedicated change with an import shim; it touches every module, test patch target and frozen eval hash. |
| Environment variables | `SERAPIS_WORKSPACE_DIR`, `SERAPIS_CACHE_DIR`, `SERAPIS_STATE_FILE`, `SERAPIS_LEDGER_FILE`, `SERAPIS_REASONING_MODEL`, `SERAPIS_BLACKBOARD_BASE_URL` are now documented and preferred in messages. The matching `JARVIS_*` names still work as fallbacks. |
| `.jarvis-cache/` (old cache) | Only used if it already exists; new data goes to the `serapis` data folder. Still git-ignored. |
| `.jarvis-browser/` (Blackboard browser profile with sign-in cookies) | Kept: renaming would silently drop a logged-in profile. **Deferred** with a migration note. Documented in SECURITY.md. |
| CSS classes `jarvis-orb`, `.node.jarvis` in templates | Internal, invisible. **Deferred** (cosmetic). |
| `data/` sample, eval result files, `AGENTS.md` | Evaluation records and instructions that name the old path or University Jarvis the separate project; left as historical record. |
