# Architecture overview

```mermaid
flowchart LR
  subgraph web["salahuddin-profile-website (Vercel)"]
    data["src/data/projects.ts<br/>15 projects: evidence, status, content"] --> pages["/projects and /projects/[slug]<br/>static (SSG)"]
    data --> seo["sitemap.xml · robots.txt · JSON-LD"]
  end
  subgraph ex["salahuddin-devops-Portfolio (this repo)"]
    proj["projects/&lt;slug&gt;/<br/>code · docs · tests"] --> ci[".github/workflows/&lt;slug&gt;.yml"]
  end
  pages -- "GitHub link (only when repo is public)" --> proj
```

- **Website:** Next.js 16 App Router, fully static output. Content is typed data, not CMS. Client JS limited to the navbar and the gallery filter.
- **Examples repo:** independent projects, each runnable and testable locally with no cloud account. CI per project via path filters.
- **Contract between them:** the project slug and the `status` field. When a project's code passes validation here, flip its `status` to `implemented` in the website and update `docs/implementation-status.md`.
