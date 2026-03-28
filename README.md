# SSD-HDD Transfer

SSD 与 HDD 之间的项目归档、提取与追加工具。基于 squashfs + zstd 压缩，针对 NVMe SSD + 大容量 HDD 的混合存储环境优化。

## 功能

- **项目归档 (SSD -> HDD)**: 将 SSD 上的项目目录压缩为 `.sqsh` 归档文件存储到 HDD。两阶段流水线 -- 先写 SSD 暂存再内联 hash 传输到 HDD，校验和零额外开销。
- **文件提取 (HDD -> SSD)**: 从 HDD 归档中恢复数据到 SSD。支持全量恢复、指定路径提取、搜索提取三种模式。
- **数据追加 (SSD -> 归档)**: 向已有归档追加新数据。自动检测冲突并以时间戳后缀命名，利用 mksquashfs 原生 append 极速完成。

## 性能指标

基于 594GB 生物信息学项目（88602 文件）的实测数据：

| 操作 | 耗时 |
|------|------|
| 归档创建 (594GB -> 305GB .sqsh) | ~20 min |
| 全量恢复 (305GB -> 594GB) | ~20 min |
| 提取 211MB 子目录 | 0.12s |
| 提取单个文件 | 0.01s |
| 搜索 90000+ 条目 | < 1s |
| 追加新数据（无冲突） | 0.05s |
| 追加数据（有冲突，时间戳重命名） | 0.12s |

对比旧方案 (tar + zstd)：部分提取从 26 分钟降至 0.1 秒，加速 5000 倍以上。

## 技术方案

- **归档格式**: squashfs + zstd level 1, 256KB block size
- **校验和**: xxh128sum (128-bit, 内联计算零开销)
- **执行模式**: 统一守护进程，所有任务后台运行，终端可随时断开/重连
- **追加冲突**: 顶层检测 + 时间戳重命名 + 原生 append，多版本并存
- **搜索引擎**: 多关键词 AND / 通配符 / 正则表达式，多次搜索累积选择

## 环境要求

### 系统工具

```
mksquashfs / unsquashfs (squashfs-tools >= 4.6)
sqfscat
zstd
xxh128sum
```

### Python

```
Python >= 3.10
rich >= 13.0
```

## 安装

```bash
# 克隆仓库
git clone https://github.com/nanyeglm/ssd-hdd-transfer.git
cd ssd-hdd-transfer

# 安装 Python 依赖
pip install -r requirements.txt

# 添加命令别名（可选）
echo "alias transfer='python $(pwd)/transfer.py'" >> ~/.bashrc
source ~/.bashrc
```

## 使用

```bash
transfer              # 交互主菜单
transfer status       # 查看/跟踪后台任务
```

### 主菜单

```
+----------- SSD <-> HDD 项目归档工具 -----------+
|                                                 |
|   [1]  项目归档    SSD -> HDD                    |
|   [2]  文件提取    HDD -> SSD                    |
|   [3]  数据追加    SSD -> 已有归档                 |
|   [4]  任务状态                                   |
|   [5]  退出                                      |
|                                                 |
+-------------------------------------------------+
```

### 归档

指定 SSD 源目录和 HDD 目标目录，程序自动统计大小、预检空间、后台执行归档。两阶段流水线：Phase 1 压缩到 SSD 暂存（快速），Phase 2 内联 hash 复制到 HDD（hash 开销被 HDD 写速度完全掩盖）。

### 提取

三种模式：

- **全量提取**: 恢复整个归档到 SSD 指定目录
- **指定路径提取**: 交互式目录浏览器，逐层展开、多选、提取
- **搜索提取**: 支持多关键词（空格分隔，AND 逻辑）、通配符（`*.py`）、正则表达式（`/pattern/`）。多次搜索结果累积，一次提取。

### 追加

向已有 `.sqsh` 归档追加新数据。自动检测同名冲突：无冲突直接追加，有冲突则以时间戳后缀重命名后追加。归档中多版本并存，旧校验和标记为失效。

## 项目结构

```
ssd_hdd_transfer/
├── transfer.py              # 主入口
├── lib/
│   ├── ui/                  # 交互层
│   │   ├── menu.py          # 主菜单 / 子菜单
│   │   ├── archive_ui.py    # 归档流程
│   │   ├── extract_ui.py    # 提取流程（全量/指定/搜索）
│   │   ├── append_ui.py     # 追加流程
│   │   ├── status_ui.py     # 任务状态
│   │   └── progress.py      # 日志跟踪 + rich 进度条
│   ├── core/                # 业务核心层
│   │   ├── archiver.py      # mksquashfs 归档（两阶段流水线）
│   │   ├── restorer.py      # unsquashfs 全量恢复
│   │   ├── extractor.py     # unsquashfs 选择性提取
│   │   ├── appender.py      # 追加（冲突检测 + staging + append）
│   │   └── browser.py       # 归档目录解析 / 搜索引擎
│   └── infra/               # 基础设施层
│       ├── daemon.py         # 守护进程 + 锁文件
│       ├── logger.py         # 日志系统
│       ├── disk.py           # 磁盘工具
│       └── checksum.py       # xxh128sum 校验和
├── log/                     # 运行日志
├── requirements.txt
└── benchmark_report.md      # 实测报告
```

## 架构设计

三层分离：ui/ (交互) -> core/ (业务) -> infra/ (基础设施)。ui 不直接调 infra，core 不调 ui。

所有任务统一通过 daemon 模块以守护进程执行：fork + setsid 脱离终端，锁文件保证单任务互斥，日志文件记录进度和摘要。终端仅作为可随时断开的跟踪窗口。

## License

MIT
