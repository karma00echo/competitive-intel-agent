# Visual exploration only

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
