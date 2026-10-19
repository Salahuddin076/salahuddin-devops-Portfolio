# Next-session prompt

Paste this to start the next session:

> Continue the DevOps portfolio. Read `salahuddin-devops-Portfolio/docs/session-handoff.md` first, then `docs/implementation-status.md` and `docs/known-issues.md`. Do not re-audit.
>
> State: 16 of 20 projects are implemented and verified. The design-only projects are 07 (gcp-ai-pharmacy-platform), 08 (azure-aks-platform), 09 (multi-cloud-kubernetes) and 12 (hybrid-cloud-fintech). All four are GCP/Azure/multi-cloud or hybrid — terraform validation for them needs the google/azurerm providers, which haven't been pulled into `TF_PLUGIN_CACHE_DIR` yet (only `hashicorp/aws` 6.68.0 is cached); the first validate on a new provider will be slow.
>
> Two open owner items from session 4, not yet closed:
> - `public/resume.pdf` on the website still says "7+" years; there's no source file in the repo to regenerate it from — needs a manual re-export.
> - K2: confirm whether the Secrets Manager value referenced in `thedusttest-iac`'s old (now purged) state file needs rotating.
>
> Next, in order:
> 1. Implement one or two of 07/08/09/12 (owner's choice of which, or default to 09 multi-cloud-kubernetes since it's closest in shape to already-implemented EKS projects).
> 2. Run gstack `/qa` on the local website build, plus Lighthouse (still not done — see K5).
>
> Follow `CLAUDE.md`: one build agent at a time in this repo; re-run its checks before committing; workflows must pass the hardening linter. Flip `status` in the website's `src/data/projects.ts` only after verification. Update the handoff at the end.
