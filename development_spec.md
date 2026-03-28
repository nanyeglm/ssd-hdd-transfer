# SSD-HDD Transfer -- 开发规格文档

## 1. 概述

SSD 与 HDD 之间的项目归档传输工具。底层采用 squashfs + zstd 格式，三大核心功能：归档、提取、追加。

## 2. 硬件环境

| 组件 | 规格 | 挂载点 |
|------|------|--------|
| SSD 1 | NVMe 1.9TB | /mnt/disk1 |
| SSD 2 | NVMe 1.9TB | /mnt/disk2 |
| SSD 合并 | mergerfs 3.7TB | /mnt/data |
| HDD | WD HC530 14TB, 读 248MB/s, 写 262MB/s | /mnt/hdd |

## 3. 核心技术决策

| 决策项 | 选定方案 | 依据 |
|--------|---------|------|
| 归档格式 | squashfs + zstd level 1, 256KB block | 实测全面优于 tar.zst（提取快 5000x） |
| 归档流水线 | 两阶段: SSD 暂存 + 内联 hash 传输 | 节省 37% 时间（校验和零开销） |
| 追加策略 | 顶层冲突检测 + 时间戳重命名 + 原生 append | 极速（毫秒级）、多版本并存 |
| 追加校验和 | 标记旧 hash 失效，不重算 | 避免 20 分钟重读 HDD |
| 执行模式 | 统一守护进程 | 终端可断开，任务不受影响 |
| 搜索 | 多关键词 AND / 通配符 / 正则 | 覆盖模糊记忆到精确查找全场景 |
| 扩展名 | .sqsh | squashfs 标准 |

## 4. 三大核心功能

### 4.1 项目归档 (SSD -> HDD)

两阶段流水线:
1. Phase 1: `mksquashfs source staging.sqsh` 写 SSD 暂存（SSD 无 I/O 瓶颈）
2. Phase 2: 读 SSD 暂存 -> 内联 xxh128 hash -> 写 HDD（hash 开销被 HDD 写速度掩盖）

SSD 空间不足时回退到直写 HDD + 事后 hash。

### 4.2 文件提取 (HDD -> SSD)

三种模式:
- **全量恢复**: `unsquashfs -f -d target -percentage archive.sqsh`
- **指定路径**: 目录浏览器 -> 多选 -> `unsquashfs archive.sqsh path1 path2...`
- **搜索提取**: `unsquashfs -lls` 解析 + Python 搜索引擎 -> 多选累积 -> 提取

### 4.3 数据追加 (SSD -> 归档)

1. `unsquashfs -lls` 获取归档顶层条目（毫秒级）
2. 与源目录 `os.listdir()` 比对，检测冲突
3. 无冲突: 直接 `mksquashfs source archive.sqsh`（原生 append）
4. 有冲突: 创建 staging（硬链接 `cp -al` + 时间戳重命名），再 append
5. 标记旧校验和为 STALE

## 5. 代码架构

三层分离: ui/ -> core/ -> infra/

```
transfer.py                    # 主入口
lib/ui/                        # 交互层（纯 UI，不含业务逻辑）
  menu.py                      # 菜单渲染
  archive_ui.py                # 归档交互
  extract_ui.py                # 提取交互（全量/路径/搜索）
  append_ui.py                 # 追加交互
  status_ui.py                 # 任务状态
  progress.py                  # 日志跟踪 + rich 进度条
lib/core/                      # 业务核心（纯逻辑）
  archiver.py                  # mksquashfs 两阶段归档
  restorer.py                  # unsquashfs 全量恢复
  extractor.py                 # unsquashfs 选择性提取
  appender.py                  # 追加（冲突检测 + staging + append）
  browser.py                   # 归档目录解析 / 搜索引擎
lib/infra/                     # 基础设施（通用工具）
  daemon.py                    # 守护进程 (fork+setsid) + 锁文件
  logger.py                    # 日志系统 (PROGRESS/SUMMARY 格式)
  disk.py                      # 磁盘工具（路径校验/空间/HDD 判断）
  checksum.py                  # xxh128sum 校验和
```

## 6. 守护进程架构

所有任务统一流程:
1. 用户确认 -> `daemonize()` fork+setsid 创建守护进程
2. 守护进程获取锁 -> 执行 mksquashfs/unsquashfs -> 写 PROGRESS 日志 -> 写 SUMMARY -> 释放锁
3. 父进程 `follow_log()` 读日志渲染 rich 进度条
4. Ctrl+C 仅断开 follow，守护进程不受影响
5. `transfer status` 可随时重连跟踪

看门狗机制: follow_log 定期检测守护进程是否存活，进程死亡后自动退出，不会无限挂起。

锁失败反馈: 守护进程锁失败时写 LOCK_FAILED 标记到日志，follow_log 检测后立即提示用户。
