# Security

Serapis is a local-first academic assistant that may handle personal information, course materials, provider credentials, and browser authentication state.

- Keep `.env`, API tokens, OAuth client secrets, cookies, and `.jarvis-browser/` outside version control. Never include them in bug reports.
- Restrict access to local state, source files, caches, and workspaces. Use only course material you are authorised to process.
- Model-backed workflows may send selected excerpts, notes, and state-derived context to the configured provider. Review that provider's terms and your institution's rules first.
- Blackboard and Google Drive integrations are user initiated; verify the destination and selected files before use.
- Report suspected vulnerabilities privately to the maintainer rather than posting credentials or exploitable personal data in a public issue. Include reproduction steps with synthetic data where possible.

This early project has not undergone an independent security audit. No security response SLA is currently offered.
