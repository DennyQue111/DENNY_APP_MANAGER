# Denny App Manager

基于 PySide6 的 Windows 本地应用启动器。它集中启动各项目的前端和后端、分开展示服务日志，并在前端就绪后打开浏览器。

## 启动

双击 `run.bat`。首次运行会创建本项目的 `.venv` 并安装 PySide6。也可以手动运行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

要求电脑已安装 Node.js（提供 `npm`）和 Python。后端优先使用项目已有的 `backend/venv`、`.venv` 或 `venv`，找不到时使用运行管理器的 Python。

## 服务与端口

| 应用 | 前端 | 后端 |
| --- | ---: | ---: |
| AI 图片视频生成器 | 5175 | 8005 |
| AI Audio Studio | 5179 | 8002 |
| AI News Collector | 5176 | 8003 |
| Remotion 视频实验室 | 5177 | 8004 |
| Blender VGGT 场景服务 | — | 8765 |

管理器每 1.5 秒检查一次配置端口，并分别显示前后端状态。若服务由其他终端或工具启动，会标记为“运行中 · 外部服务”；这时可打开前端页面，但停止按钮只会停止由管理器启动的进程。端口检测表示该端口有进程监听，无法仅凭端口确认监听者一定是对应项目。

服务监听 `127.0.0.1`，不会开放到局域网。每张应用卡片的标签页分别显示前端、后端日志。退出管理器时可以选择停止所有由管理器启动的服务。

Vite 前端会把 API 请求转发给对应的后端。端口和启动命令可以在 `apps.json` 修改。

## Git 操作

每个应用卡片显示当前分支相对上游的领先/落后提交数。点击 **Fetch & Rebase** 会先 fetch；远端有新提交且工作区干净时自动 rebase。若有未提交改动，会 fetch 但跳过 rebase，并在 Git 日志中说明原因。**Push** 只在当前分支有尚未推送的提交时高亮可用；未提交的文件需要先 commit。点击 **打开工程** 会在本地 VS Code 的新窗口中打开对应项目文件夹。

Git 操作在后台执行，不会阻塞窗口。项目必须是 Git 仓库并配置当前分支的上游远端，按钮才会启用。当前 `collect_ai_news` 没有配置上游，`remotion_video_generator` 不是 Git 仓库，因此这两个项目的 Git 按钮会保持禁用，直到补齐仓库/远端配置。

VS Code 安装位置可写在本机 `.env` 的 `DENNY_VSCODE_PATH` 中。`.env` 已加入 `.gitignore`，不会提交；`.env.example` 只提供空配置模板。

## 代码结构

```text
main.py                         # 程序入口
denny_app_manager/
├── config.py                   # 路径与应用配置读取
├── controllers/
│   ├── service_controller.py   # 应用进程、端口状态与日志事件
│   └── git_controller.py       # Git 状态与操作调度
├── services/
│   ├── git.py                  # Git 命令和后台任务
│   ├── editor.py               # VS Code 工程目录打开
│   ├── ports.py                # 端口扫描任务
│   └── processes.py            # 进程启动、停止与日志解码
└── ui/
    ├── app_card.py             # 单个应用卡片
    └── main_window.py          # 主窗口与控制器连接
```

## 说明

这是同一台电脑上的本地进程面板，与 Kubernetes 的“集中管理服务”概念有些相似，但不包含容器编排、集群调度、自动扩缩容等 Kubernetes 功能。当前优先覆盖有前后端服务的项目；Blender 插件本体通过 Blender 加载，不作为独立网页服务启动，这里列出的是它依赖的 VGGT API。

AI Audio Studio 的模型推理环境仍按其 README 独立安装和配置。启动管理器不会安装模型、下载权重或修改项目数据。
