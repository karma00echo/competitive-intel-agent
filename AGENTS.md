# Project instructions

## Scope

This repository implements the Universal Competitive Intelligence Agent.
Keep the product name as the only required user input. Do not require users to
provide website URLs.

## Architecture boundaries

- Use one controlled main agent. Do not introduce a multi-agent architecture.
- Search, official-source validation, and source discovery are separate tools.
- Web fetching, cleaning, fact extraction, comparison, and report generation
  must not access MySQL directly.
- All database reads and writes go through `competitive_intel.persistence`
  repositories.
- Database transactions are owned by the application layer through
  `Persistence.transaction()`.
- Facts without source URL, evidence text, collection time, and confidence
  cannot become confirmed facts.
- A failed page fetch is an unknown comparison result, never an unchanged page.

## Development

- Target Python 3.12.
- Keep tests offline by default except tests explicitly marked `integration`.
- MySQL integration tests must use a disposable database whose name ends in
  `_test`.
- Never commit `.env`, credentials, captured secrets, or production snapshots.
- Do not proceed to the next development phase while the current phase has
  failing tests.


## Git 提交规范
每次完成一个功能模块的修改并且相关测试全部通过后,执行以下操作:

运行 git status 确认改动文件范围
git add 相关文件(不要提交无关文件,比如 __pycache__、日志、临时文件)
用简洁清晰的 message 提交,格式建议:feat: xxx / fix: xxx / test: xxx / docs: xxx
提交后运行 git push,推送到远程 origin main
每次 Git 操作后用 git log --oneline -5 和 git status 验证结果,并把验证结果附在汇报里,不要只口头说"已完成"

如果测试没有全部通过,不要提交,先修复问题。
如果某次改动涉及敏感信息(比如真实密钥、密码),先提醒我确认,不要自动提交。