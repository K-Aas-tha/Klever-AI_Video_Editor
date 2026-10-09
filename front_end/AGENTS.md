<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

- Keep the video workspace in browser-safe feature components with React session state; this project is a frontend preview, not a connected video-processing service.
- Define visual roles and responsive feature styles in the global design system so the workspace stays consistently themed.
- Use local bundled sample photography for demo projects, and object URLs for user-selected video previews; revoke object URLs when the workspace unmounts.
