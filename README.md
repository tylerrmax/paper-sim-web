# 模拟盘 · 独立网页版（单用户过渡版）

手机/电脑浏览器随时打开的模拟盘网站。数据每天 17:12 管线推送后自动刷新；
页面上的操作（暂停/开始、自动/手动、批准/跳过）约 2 分钟内生效。

## 架构

- 本仓库 = Streamlit 应用 + `snapshot.json`（数据快照）+ `commands/pending/`（指令队列）
- 数据链：Muse VM 上的管线 → `/tmp/sim_snapshot.json` → `tools/git_sync.py`
  每 2 分钟 `git push` → Streamlit Cloud 检测到推送自动刷新页面
- 指令链：页面按钮 → GitHub Contents API 写 `commands/pending/<id>.json`
  → `tools/git_sync.py` 取回 → `apply_commands.py` 执行 → 新快照推回

## 部署（一次性，约 5 分钟）

1. 在 GitHub 新建**私有**仓库 `paper-sim-web`（空仓库，不要加 README）。
2. 建一个 fine-grained PAT：只给这一个仓库，权限 `Contents: Read and write`。
   - 一份自己留着，第 5 步用；另一份通过安全通道发给助手（推送快照用）。
3. 助手把代码推送到该仓库。
4. 打开 share.streamlit.io → New app → 选择该仓库 / main 分支 / `app.py` → Deploy。
5. 在 Streamlit 后台 Manage app → Settings → Secrets，填入：
   ```toml
   APP_PASSWORD = "你自己定的访问密码"
   GITHUB_TOKEN = "你的 PAT"
   GITHUB_REPO = "你的GitHub用户名/paper-sim-web"
   ```
6. 打开 `https://<你起的名字>.streamlit.app`，输入密码即可使用。
   手机上用「添加到主屏幕」，就是全屏图标，和 App 一样打开。

## 本地开发

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# .streamlit/secrets.toml 填入 APP_PASSWORD/GITHUB_TOKEN/GITHUB_REPO（已 gitignore）
streamlit run app.py
```

## 文件

- `app.py` — Streamlit 应用（密码门 + 看板 + 操作）
- `snapshot.json` — 数据快照（由管线生成，不要手改）
- `commands/pending/` — 指令队列（由页面写入，服务端取走）
- `tools/git_sync.py` — 双向同步脚本（cron 每 2 分钟）
