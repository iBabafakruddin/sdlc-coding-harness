# Common Coding Style
- Prefer immutability (`final`, `readonly`, `const`, Java `record`, Python `@dataclass(frozen=True)`).
- Keep functions < 40 lines and files < 300 lines; extract single-responsibility helpers.
- Handle errors explicitly with typed exceptions or RFC 7807 Problem Details; never swallow exceptions silently.
- Never hardcode secrets, credentials, URLs, or API keys; use environment variables.
