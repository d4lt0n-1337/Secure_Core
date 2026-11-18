Frontend unit tests live here.

This repo already uses Vitest via `client/package.json`.

Suggested structure:
- Put React/component tests under `client/src/**/__tests__/*.test.tsx`
- Keep this folder for cross-service documentation and any shared fixtures.

Run:

```zsh
cd client
npm test
```
