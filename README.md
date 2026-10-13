# DevOps & Cloud Architecture Examples

Working examples behind the projects on [salahuddin.wesaveall.com/projects](https://salahuddin.wesaveall.com/projects), by Muhammad Salahuddin, Senior DevOps Engineer.

Each project is labeled:

- **Production case study** — a sanitized write-up of work from my CV. Client names, domains, account IDs and figures are withheld.
- **Portfolio implementation** — code built for this portfolio on synthetic data.
- **Reference architecture** — a documented design.

All examples run locally with no cloud account. Terraform is validated only and is never applied from this repo.

| # | Project | Label | Code |
|---|---|---|---|
| 14 | [Cloud Cost Optimization & FinOps Toolkit](projects/finops-cost-optimization/) | Portfolio implementation | ✅ Python toolkit, 71 tests, Terraform guardrails, CI |

The remaining 14 projects are documented on the website and are being implemented one at a time. See [docs/implementation-status.md](docs/implementation-status.md).

## Running a project

```bash
cd projects/finops-cost-optimization
python3 -m unittest discover -s tests -v
python3 -m finops report --input sample-data --budget 6500 --out out --html
```
