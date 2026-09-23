# Visual exploration only

## Selected editorial homepage

The reference-led homepage lives at **http://127.0.0.1:8010/final-editorial-demo/**
when served using the command below. It is isolated from the production homepage.

`final-editorial-demo/content.js` contains replaceable mock navigation, cards,
competitor records, signals, report outlines, and suggestions. `theme.css` controls
the reference-inspired warm paper / sage design. Local SVG illustrations require
no external fonts, image services, or network requests.

Navigation opens local preview panels; search finds demo sections and companies;
suggestions fill the analyst input; submission shows a research outline only.
Web search and Evidence are preview preferences, not live integrations. Export
offers a selectable Markdown preview and requests a sample file download. The
preview remains usable in embedded browsers that do not support downloads;
the UI does not claim that a file was saved. Ctrl/Cmd+K focuses search,
Ctrl/Cmd+Enter submits the preview, Alt+N starts a new input, and Escape closes
search results and the mobile navigation. No database or API is accessed.

Future changes can replace content, connect approved data, or tune typography,
illustrations and density without changing the other four demos.

## Earlier visual explorations

Four static demos share one dataset, renderer and set of interactions. Only CSS differs.
No application modules, APIs, databases or AgentRunner are used or modified.
All displayed records are synthetic design fixtures, not current product intelligence.
Analysis controls only show a local preview and never start a real task.

Run from the repository root:

```powershell
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m http.server 8010 --bind 127.0.0.1 --directory ui-demos
```

- http://127.0.0.1:8010/01-studio/
- http://127.0.0.1:8010/02-nightfall/
- http://127.0.0.1:8010/03-editorial/
- http://127.0.0.1:8010/04-precision/

Each entry offers the same six navigation sections, signal filters, competitor tabs,
controlled Analyst preview, local Markdown download and expandable run traces.
No design is selected or applied to the existing application.
