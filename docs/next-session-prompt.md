# Next-session prompt

Paste this to start the next session:

> Continue the DevOps portfolio. Read `salahuddin-devops-Portfolio/docs/session-handoff.md` first, then `docs/implementation-status.md` and `docs/known-issues.md`. Do not re-audit.
>
> State: 11 of 20 projects are implemented and verified (991 tests). The design-only projects are 02, 03, 05, 07, 08, 09, 11, 12 and 15.
>
> Next, in order:
> 1. Ask the owner whether to push both repos and merge the website to `main`. The merge also removes the leaked diagrams from the live site.
> 2. Implement 02 n8n-keda (helm and kubeconform are installed).
> 3. Implement 11 observability-sre.
> 4. Implement 05 gitops.
> 5. Run gstack `/qa` on the local website build, plus Lighthouse.
> 6. Add an OG image and an FAQ section.
>
> Follow `CLAUDE.md`: one build agent at a time in this repo; re-run its checks before committing; workflows must pass the hardening linter. Flip `status` in the website's `src/data/projects.ts` only after verification. Update the handoff at the end.
