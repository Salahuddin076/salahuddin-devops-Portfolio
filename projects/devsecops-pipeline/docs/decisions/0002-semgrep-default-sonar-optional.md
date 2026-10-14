# ADR 0002: Semgrep OSS as the default SAST gate, Sonar optional

- **Status:** accepted
- **Date:** 2026-10-14

## Context

Production pipelines in the owner's background used SonarQube (with quality
gates) and Snyk alongside image scanning. Both need external state: a Sonar
server or SonarCloud organization plus a token, or a Snyk account plus a
token. A reusable pipeline that *requires* them fails on fork PRs (no
secrets), in a fresh repository, and in this portfolio repository, which has
no server.

## Decision

- **Semgrep OSS** (`semgrep scan --config p/python --sarif --error`) is the
  always-on SAST gate. It needs no server or account, and with `--metrics off`
  it sends no usage telemetry. Its SARIF goes to code scanning. Semgrep is
  installed at an exact version.
- **SonarQube/SonarCloud** runs only when `sonar-enabled: true` **and**
  `SONAR_TOKEN` is set. Secrets cannot appear in `if:`, so a step converts
  `secrets.SONAR_TOKEN != ''` into a boolean output without exposing the
  value. Sonar runs with `sonar.qualitygate.wait=true`, so its quality gate
  blocks when enabled.
- **Snyk** follows the same pattern next to Trivy in `sca`: it runs when
  `SNYK_TOKEN` is set.

## Consequences

- The pipeline works with no external services, including on fork PRs.
- Teams that already run Sonar keep its quality gate, coverage and
  maintainability views without losing the Semgrep baseline.
- Semgrep's `p/python` registry ruleset is fetched at run time and can change
  between runs. Pin rules by vendoring a ruleset file if results must be
  reproducible. That is a listed limitation.
- When Sonar is enabled but has no token, the job warns rather than failing,
  so a mis-configured secret does not block every fork PR. Watch for the
  warning annotation.
