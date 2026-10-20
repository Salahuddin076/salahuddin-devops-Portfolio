# Next-session prompt

Paste this to start the next session:

> Continue the DevOps portfolio. Read `salahuddin-devops-Portfolio/docs/session-handoff.md` first, then `docs/implementation-status.md` and `docs/known-issues.md`. Do not re-audit.
>
> State: all 20 projects are implemented. 1,474 tests across the portfolio, but a single full regression run across all 20 has not been re-done since projects 03/15/07/08/09/12 were added individually this session (session 4) — each was verified on its own, not as part of one combined run.
>
> Two open owner items from session 4, not yet closed:
> - `public/resume.pdf` on the website still says "7+" years; there's no source file in the repo to regenerate it from — needs a manual re-export.
> - K2: confirm whether the Secrets Manager value referenced in `thedusttest-iac`'s old (now purged) state file needs rotating.
>
> With no design-only projects left, likely next steps (owner's call, not pre-decided):
> 1. A full regression run across all 20 projects' test suites plus every terraform/helm/ansible validation, to confirm nothing regressed between sessions.
> 2. Run gstack `/qa` on the local website build, plus Lighthouse (still not done — see K5).
> 3. Tackle the smaller remaining known-issues (K6's CSP `'unsafe-inline'`, K11's test brittleness, K9's sandbox-account acceptance if the owner wants real-AWS verification).
> 4. Ask the owner whether any project should be deepened further (e.g. an actual sandbox-account deploy) rather than staying validation-only.
>
> Follow `CLAUDE.md`: one build agent at a time in this repo; re-run its checks before committing; workflows must pass the hardening linter. If a build subagent gets cut off by a usage limit mid-task (see K14), finish it directly rather than discarding the partial work or re-running a fresh subagent on the same project.
