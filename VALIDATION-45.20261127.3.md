# 45.20261127.3 候选 ISO：构建与安装验收

## 当前结论

当前候选的[实际 compose](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45981240945/job/140445377978)已成功。
修复宿主 KVM 授权后，同一 ISO 已通过真实 Live 图形登录、稳定桌面、资源和 Fedora PAM
检查；16 GB 加密安装已完成分区、复制、系统配置及同次 Live 启动内的用户配置。
当前阻断是 `finalize` 关闭 LUKS 映射时设备仍被占用。后续诊断已确认，安装器记录的
挂载虽已正常卸载，多个系统服务的独立 mount namespace 仍保留同一目标 Btrfs。
正在修复安装挂载的隔离边界，不放宽关闭映射或硬盘启动门禁。
尚未完成加密硬盘启动，其余八个场景也尚未执行。
本报告不是正式发行通过凭据。

上一候选 `.2` 在原 schemas 严格编译处失败、未生成 ISO，见 [第二候选报告](VALIDATION-45.20261127.2.md)。

旧版 `45.20261127` 的桌面 SIGSEGV 和独立存储结果保留在
[原版报告](VALIDATION-45.20261127.md)；上一候选在 Live 图形输入阶段停止、没有
进入安装的事实保留在[45.20261127.1 报告](VALIDATION-45.20261127.1.md)。
它们不用于替代本候选的实际验收。

## 输入与来源

| 项目 | 本候选固定输入 |
| --- | --- |
| 系统 | Fedora 45，x86_64，传统可写 RPM / DNF 系统 |
| ISO 版本 | `45.20261127.3` |
| 配方提交 | `de9549735f77fd426834f5a3a9a1c3cc9d206a14` |
| 配方 tree | `dbd0d1e75388fb1f5e0b334acbe182e195e947ab` |
| 安装器提交 | `b5816732394a20188593b2918ebdddbc169e68dc` |
| 安装器 RPM | `fedora-dde-installer-0.3.0-0.2.fc45.x86_64` |
| DFM 四个运行包 | `6.6.7-9.1.remix1.fc45`，固定临时源码补丁 |
| desktop-base 临时包 | `2026.10.28-1.1.remix1.fc45.noarch`，仅依赖与 Release 调整 |
| schemas 临时包 | `6.0.13-1.1.remix1.fc45.noarch`，重复 XML 修复、真实 Go 生成物严格检查 |
| 配置 RPM | `fedora-dde-remix-config-45.20261127.3-1.fc45.noarch` |
| 安全配置 | SELinux Enforcing，Fedora 原生 PAM 加 DDE 适配策略 |
| compose job | [140445377978](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45981240945/job/140445377978)，成功 |

安装器的 [Fedora 45 原生构建](https://github.com/Fedora-DDE-Remix/fedora-dde-installer/actions/runs/45962759570)
已完成 Qt/DTK 编译、RPM/SRPM、三个 CTest 套件和实际 DNF 安装；本地后端为
142 项测试通过。Fedora 45 的解锁程序和 generator 由 `systemd-udev` 提供，
RPM 依赖及原生可执行检查均使用这个实际提供者。

完整 DFM RPM 的[独立复验](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45956698212)
通过安装、ELF、重定位与嵌套 Qt 插件探针。原构建的后续判据误报及 failure 状态
继续保留；schema 2 来源记录没有把旧失败改述为成功。

## 已生成的 ISO 与原生构建证据

compose job 于 `2026-11-27T10:42:14Z` 成功结束。

| 产物 | 实际身份 |
| --- | --- |
| 原始 ISO | `Fedora-DDE-Remix-45.20261127.3-x86_64.iso` |
| 原始 ISO 大小 | `3,462,604,800` 字节 |
| ISO artifact | [15191370433](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45981240945/artifacts/15191370433)，`Fedora-DDE-Remix-45.20261127.3-x86_64-16` |
| artifact ZIP 大小 | `3,462,661,685` 字节 |
| artifact ZIP SHA-256 | `6a4195558b1a3fcf43abeb14879c06eb32acc9bd52c7abc9d8061383e24efdd2` |
| 构建日志及 RPM artifact | [15190487108](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45981240945/artifacts/15190487108)，`98,013,485` 字节 |
| 日志 ZIP SHA-256 | `6cdcec54c18e3e19d7b85d536db72301f0606f0f2bf3c77e9b42bd11fac4dfd7` |

原始 ISO 的 SHA-256 与外层 artifact ZIP 的摘要分别记录，校验 ISO 文件应使用：

```text
99bbaf5401740d1815da8cd20cbec25556d38a9f51c5f4b87a58964658a71a14  Fedora-DDE-Remix-45.20261127.3-x86_64.iso
```

日志 ZIP 已实际下载并独立计算大小与 SHA-256。原始 ISO 的大小和摘要来自已封存
构建日志；VM 工作流实际下载同一 artifact 并通过 ISO 校验。对话环境没有重复下载
超过连接器单文件上限的 ISO。

实际原生日志与最终 payload 检查确认：

- schemas 使用 `go1.27.4-X:nodwarf5 linux/amd64` 编译 override 工具，GLib 为
  `2.90.1`。真实 RPM `%check` 对安装后的 buildroot 执行
  `glib-compile-schemas --strict --dry-run`，返回成功；不是本地 Python 合并替代。
- schemas binary RPM 的 SHA-256 为
  `4a292037c9cf2d0a742da489d1f40d06d855f176c399c67d1a1185fe67f27f20`，
  SRPM 为 `560e65b72be90f3e670881958d3ffe377e04c5fbca949690411eca2d9d85bc9b`。
  安装包身份与对应 SRPM、固定源码补丁一致。
- 69 个 mandatory 桌面包全部存在。定向标识替换只移除 `fedora-logos`，
  安装 `generic-logos-18.0.0-29.fc45`，保留其他桌面包。
- 最终编译缓存保留 mediakey `away=['XF86Away']`；两项 GSettings 背景默认值
  指向实际存在的 JPEG。壁纸、两个 Remix PNG、配置的 RPM 所有者和文件格式均正确。
- COPR 配置默认启用，保留签名/TLS 检查及已核验公钥。镜像中的 crypto 解锁程序
  和 generator 均存在、可执行且由 `systemd-udev` 提供。
- Fedora PAM 的正确/错误密码、未知/过期账户检查通过；图形会话、运行时 Enforcing
  和安装后行为仍由下面的 VM 测试单独验证。

## 本候选新增的修复

本候选在前版资源与控制器改动基础上，修复原 schemas 的重复元素，并由真实 Fedora
Go/RPM 构建生成临时包；检查最终编译缓存中的 mediakey `away` 原默认值。

1. 登录测试按当前 Treeland 的实际输入框定位，先确认焦点，再慢速输入并只提交一次。
   15 项回归包括上一候选的两张原始 PNG；掩码数量仅为诊断，真实 DDM 登录和
   稳定桌面仍是独立门禁。
2. 补齐实际缺失的 JPEG 壁纸、Remix 标识和 DSysInfo 配置。构建检查真实 RPM
   所有权与编译后的默认值，VM 登录后读取实际用户配置并保存渲染截图。
3. 在 ISO-Build 内临时重建 desktop-base 的通用标识依赖，再定向使用 `generic-logos`。
   移除范围检查要求只替换原主标识包。经追加授权，维护仓库的对应修复另见 [SPEC PR #1](https://github.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/pull/1)，主分支保持未合并。

详见[桌面插件、资源与临时 SPEC 报告](DDE-HOTFIX-20261127.md)。

## 安装后默认 COPR

配置 RPM 持久管理标准文件：

```text
/etc/yum.repos.d/_copr:copr.fedorainfracloud.org:mozixun:Fedora-DDE-Remix.repo
```

仓库 ID 保持 `copr:copr.fedorainfracloud.org:mozixun:Fedora-DDE-Remix`，默认启用，
保留 `gpgcheck=1` 与 `sslverify=1`。URL 使用 `$releasever`、`$basearch`，经核验的
公钥由配置包保存并使用 `file://` 引用。目标系统移除 Live 安装器时保留这个配置 RPM。
构建阶段检查最终 payload；Live 和安装系统再分别通过 DNF 确认实际启用状态。
这些是当前实现与验收要求，实际结果以本轮 VM 报告为准。

## 加密与容量

加密模式新建一个 LUKS2/Argon2id 容器，内部为 Btrfs、ext4 或 XFS。
ESP 与独立 ext4 `/boot` 保持未加密；Btrfs 的 root/home 子卷位于同一容器，
ext4/XFS 的 home 位于加密根内。密码通过 sealed memfd 传递，crypttab 的密钥字段
为 `none`，目标系统不保存自动解锁 keyfile。

当前不支持复用已有 LUKS、分离头、多容器或 LVM；加密模式会在分区前拒绝独立
明文 home/data/var 与磁盘 swap，保留 Fedora 的默认 zram 配置。

设备初筛为 14 GiB，内层根下限为 12 GiB，LUKS 另预留 32 MiB。后端按实际
payload、文件系统开销与余量检查容量；设备初筛不能作为所有布局都能安装的承诺。
两组小盘使用精确 16,000,000,000 字节，不能写成 16 GiB，也不承诺未来更大包集
仍有相同最小容量。

## 真实 VM 安装矩阵

所有场景使用同一 ISO、x86_64、单块 VirtIO 磁盘、512 字节逻辑扇区。
UEFI 使用未启用 Secure Boot 的 OVMF，BIOS 使用 SeaBIOS。各场景具有独立
2 GiB ext4 `/boot`，UEFI 场景的 ESP 为 600 MiB FAT32。

| 场景 | 固件 / 分区表 | 磁盘 | 根 / home / swap | 本候选结果 |
| --- | --- | --- | --- | --- |
| `uefi-luks-btrfs-small` | UEFI / GPT | 十进制 16 GB | LUKS2 内 Btrfs root/home | 最新复验：Live 桌面及安装配置通过，finalize 关闭映射失败，尚未硬盘启动 |
| `uefi-btrfs` | UEFI / GPT | 64 GiB | Btrfs root/home | 首轮未展开：canary 失败 |
| `bios-ext4` | BIOS / GPT | 64 GiB | ext4 根、根内 home、2 MiB BIOS boot | 首轮未展开：canary 失败 |
| `bios-mbr-ext4` | BIOS / MBR | 64 GiB | ext4 根、根内 home | 首轮未展开：canary 失败 |
| `uefi-xfs-home-swap` | UEFI / GPT | 64 GiB | 32 GiB XFS 根、独立 ext4 home、2 GiB swap | 首轮未展开：canary 失败 |
| `uefi-preserve` | UEFI / GPT | 64 GiB | 新建 Btrfs 根，保留 ext4 home 与 ESP | 首轮未展开：canary 失败 |
| `uefi-small` | UEFI / GPT | 十进制 16 GB | Btrfs root/home | 首轮未展开：canary 失败 |
| `bios-luks-ext4` | BIOS / GPT | 64 GiB | LUKS2 内 ext4 根与 home | 首轮未展开：canary 失败 |
| `uefi-luks-xfs` | UEFI / GPT | 64 GiB | LUKS2 内 XFS 根与 home | 首轮未展开：canary 失败 |

### 首轮 canary 的实际失败记录

[Job 140455962478](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45981240945/job/140455962478)
在 `live-ddm-password-login-and-desktop` 失败，`installation_checks_completed=false`。
后续矩阵入口 job `140460078277` 被跳过，计划中的八个场景没有展开执行。
完整证据 [artifact 15191192463](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45981240945/artifacts/15191192463)
为 `3,498,976` 字节，SHA-256：
`30d2759cef2fcc3afbb8b5325b7152bba1fd2e250de97b8e4c30b110e467d263`。

本次真实通过串口登录/sudo、Live Enforcing、DDM `xdm_t`、Copr 启用及实际资源检查。
输入证据和人工查看的原始截图确认一次输入、一次提交，框内为八个掩码；最终截图
能看到地球壁纸，但没有面板等完整桌面证据。提交前最后一个完整 session 样本没有
DDM 用户会话或 dde-shell，提交后第 9 条串口命令只返回 BEGIN，没有结果或 END。
因此不能把这次结果判为 PAM 拒绝、DPF 再次崩溃或加密安装失败。

另已确认采集器的内部 `loginctl` 默认时限为 120 秒，外层 session 观察为 45 秒；
缺少分步记录，尚不能定位具体挂起子命令。KVM 探针成功但真实 VM 打开
`/dev/kvm` 被拒，实际使用 TCG；当前没有足够证据解释两次打开的权限差异。

### 同一 ISO 的采集器修复与复验入口

修复仅作用于只读 session 观察和失败证据，不改变安装后端、密码输入、PAM、SELinux、
ISO 内容或桌面通过条件。session 共用最多 30 秒的单调时钟预算，分步输出开始、完成
与不完整 marker；GNU timeout 在正常预算下 33 秒发送 TERM，再过 2 秒 KILL，
为原有 45 秒串口预算保留 END marker 的时间。

采样不完整时必须 `ready=false`；未知崩溃状态为 `null`，已有崩溃事件保留并立即失败。
授权和 boot ID 错误仍硬失败。首次 checkpoint 及最终通过均要求完整观测；硬超时
没有 guest JSON 时明确记录控制器侧失败，不合成 guest 身份或“没有崩溃”的结果。
串口残余输出、恢复失败原因及 KVM UID/GID/ACL/open errno 诊断均持久保存。

本地实际通过 15 项原图形回归、13 项 guest 采样回归及 12 项控制器回归。
包括真实挂起子进程终止/回收、GNU timeout 终止子孙进程后串口仍能返回 END，
以及下一条命令继续执行。另执行了 workflow 显式输入与固定清单的七种选择检查，
确保由 push 调用的 reusable workflow 仍使用调用者传入的 ISO，而非误读复验清单。

专用 `validate-iso3-20261127` 分支通过 `scripts/vm-retest.json` 固定原 compose run、
artifact 名、配方提交与原始 ISO SHA-256。下载后同时检查 CHECKSUM、build-info
来源及独立计算的原始 ISO 摘要；只运行安装复验，不触发新 compose。
先选 `uefi-luks-btrfs-small`，其通过后再选 `remaining` 展开另外八组。
上述局部回归不是实际 VM 桌面或加密安装的替代证据。

首次专用复验 [run 45988598564](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45988598564)
使用测试提交 `0e68e6434f02332fd2cf28a5a7014951d509ea86`，在 VM 启动前的控制器
回归失败。旧 15 项、guest 13 项和真实 sudo shell 检查均通过；新增的真实进程组
超时测试已确认 KILL 返回 137、保留 marker、串口 END 和后续命令正常，之后读取
已退出子进程的 `/proc/<pid>/stat` 遇到 `ProcessLookupError: [Errno 3]`。
这是进程回收与测试读取之间的竞态；本次 ISO 下载、校验、VM 步骤均跳过。
修正仅让该测试接受 ENOENT/ESRCH，仍拒绝其他读取错误及尚存活的非僵尸进程；
增加针对消失文件、权限错误和仍在运行状态的短回归后，控制器套件为 13 项。
此失败保留在原 run，不作为实际桌面或存储结果。

### 第二次专用复验：认证成功与 KVM 授权失效

[Run 45989333939](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45989333939)
使用测试提交 `c7c32d7fb75761e08f098ac5c0188b0a543f2359`，41 项宿主回归、真实 sudo
shell、原 ISO 下载、来源与原始 SHA-256 校验全部通过。实际 VM 的 Live 桌面步骤
在 420 秒原有预算结束时失败，`installation_checks_completed=false`。
这次没有重新 compose；原 ISO 来源仍是 `de9549735f77fd426834f5a3a9a1c3cc9d206a14`。

完整证据 [artifact 15193861879](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45989333939/artifacts/15193861879)
为 `2,353,922` 字节，实际下载后独立核验 SHA-256：
`361b5c587bc9fa7d4780cf5c36a1de52bca0f453c38016108af6692bf161bdaf`，共 58 个文件。

认证证据相互吻合：DDM 日志于 `11:24:14Z` 记录密码认证成功，`11:24:20Z` 记录登录
成功，Treeland 于 `11:24:22Z` 激活 liveuser/session 3。`11:24:54.687990Z` 的完整
采样确认 `Service=ddm`、`Type=wayland`、`Class=user`、UID 1000、VT 2，且会话活动。
同一时刻没有 dde-shell 进程，`ready=false`；当次完成的崩溃检查没有发现记录。
此后 coreinfo 查询本身超时，不能将后续未知状态解释成“确认没有崩溃”。

人工查看原截图 013/014/015，确认八个掩码、一次提交和最终只剩壁纸。没有面板、
图标或完整桌面的通过证据。用户 ApplicationManager 服务反复启动超时并达到
重启计数 4/5/6；audio、bluetooth、RTKit 和用户 systemctl 查询也有长延迟。
当前日志不足以把这些异常归结为某一个包的唯一故障。22 条已收集 AVC 均是
`kmscon_t` 对 `tmpfs_t` 的 filesystem getattr 拒绝，没有已收集的 DDM/dde-shell
对应拒绝证据；SELinux 保持 Enforcing。

ApplicationManager 的 `couldn't find app "dde-session-manager"` 提示已核对
[固定上游源码](https://github.com/linuxdeepin/dde-application-manager/blob/713923b9a29340cbb3c82bf3d319496bcb75a4e8/src/dbus/applicationmanager1service.cpp)：
在应用实例跟踪中查不到对应 desktop app ID 时输出警告并立即返回，不阻止其他初始化。
当前没有据此添加包、伪造 desktop 条目、修改 BusName 或增加启动 timeout。

新采集器正确返回了串口 BEGIN/END 1–19：1–9 和诊断命令 19 退出 0，10–18 为
有界退出 124，串口恢复成功。共七次完整、九次不完整 session 样本，没有 ready=true。
Treeland 实际监听 `/run/treeland/wayland-1`；用户 runtime 目录内没有 socket 只是
诊断字段，不是桌面通过门禁，也不能单独推断 compositor 失败。

宿主 KVM 快照确认了设备权限变化：

| UTC 时间 | 阶段 | UID 1001 的命名 ACL | 打开设备 |
| --- | --- | --- | --- |
| 11:19:47.543 | probe 前 | `user:1001:rw-` | 成功 |
| 11:19:48.164 | probe 后 | 消失 | EACCES / errno 13 |
| 11:19:50.526 | 真实 VM 启动前 | 缺失 | EACCES / errno 13 |
| 11:19:50.627 | 启动失败后 | 缺失 | EACCES / errno 13 |

四次均为同一 PID 3144、UID/EUID/GID 1001 和相同附加组、安全状态；设备 inode、
root:GID 993、0660 模式不变，ACL 与 ctime 发生变化。因此“探测期间访问授权丢失”
是实际结论，具体修改者没有宿主 udev audit 可直接证明。

源码提供吻合的机制：[Linux KVM](https://github.com/torvalds/linux/blob/v6.8/virt/kvm/kvm_main.c)
在创建/销毁 VM 时发送设备 CHANGE 事件；systemd 的
[uaccess 规则](https://github.com/systemd/systemd/blob/v255/rules.d/70-uaccess.rules.in)、
[seat 规则](https://github.com/systemd/systemd/blob/v255/rules.d/73-seat-late.rules.in) 和
[uaccess 实现](https://github.com/systemd/systemd/blob/v255/src/udev/udev-builtin-uaccess.c)
可能在没有活动 seat 用户时清除命名用户 ACL。这是源码支持的解释，未替代本次
宿主修改者的直接记录。

后续宿主修复采用现有设备的 `kvm` 组访问：仅在字符设备与已核验组 GID 相符时
为临时 runner 增加组成员资格，由同一非 root UID 启动具备新附加组的控制器。
启动门禁核对 UID/GID、附加组和实际 open；现有 probe 前后快照继续验证访问是否稳定。
不改变桌面启动时限、ISO 字节或安装验收条件。其真实效果见下一节。

### 第三次专用复验：Live 桌面通过，LUKS 收尾失败

[Run 45992850996](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45992850996)
使用测试提交 `78fc2c28080d9c1af21ed4545d1c28f682d689c1`，原始 ISO 内容不变。
41 项宿主回归、真实 sudo shell 和原始 ISO 来源/摘要校验全部通过。
控制器保持 UID/EUID/GID/EGID 1001，新的附加组包含设备所属的 `kvm` GID 993。
probe 前、probe 后和实际启动前三次真实打开 `/dev/kvm` 均成功；QEMU 使用
`q35,accel=kvm`、`-cpu host`，QMP 实际返回 KVM enabled/present/running。

本轮 Live 桌面、有效资源及原生 PAM 检查通过，`desktop_failures=[]`。
人工查看原始稳定帧 `017-desktop-frame.png`，可见地球壁纸、桌面图标和底部面板。
这是同一 ISO 的实际运行证据；没有改写历史 DPF 构建 artifact 中当时尚未验证桌面的记录。

真正的安装后端已完成 `preflight → partition → copy → system → ready → configure`。
加密检查确认 LUKS2、单个 Argon2id 密钥槽、内层 Btrfs UUID、`crypttab` 密钥字段 `none`，
实际错误口令拒绝与正确口令接受；检查的目标配置、BLS 和安装器状态文件没有测试口令。
这证明当前 payload 在这块十进制 16 GB 盘中完成了复制和配置，尚不能宣称完整安装成功。

`finalize` 失败返回：

```text
cryptsetup failed (exit 5)
device-mapper: remove ioctl ... failed: Device or resource busy
Device luks-9edfb36e-f08b-4943-a127-35694ff95bcb is still in use.
```

失败后的状态为 `phase=finalizing`、`owned_mounts=[]`；完整 `findmnt` 没有 `/target`
或该目标 Btrfs，`lsblk` 中映射仍在且没有挂载点。进程快照仍有该文件系统的 Btrfs
工作线程。现有记录没有各进程 mount namespace、块设备打开计数或持有者，不能
把特定桌面进程、os-prober、udev 或某个 SPEC 指认为原因。
结果继续为 `failed`、`installation_checks_completed=false`，未执行移除 ISO 后的硬盘启动。

完整证据 [artifact 15194364053](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45992850996/artifacts/15194364053)
为 `5,132,094` 字节，共 71 个文件，实际下载后独立核验 SHA-256：
`0f2d2b334d99d10eff36a25a98311ed18773705128892a2dc381f271e91eba5d`。

后续复验仍复用此 ISO，只在原 `finalize` 失败后收集有界只读占用诊断：device-mapper
打开计数/holders、相关进程的 mount namespace、cwd/root/FD 元数据和内核日志。
不终止进程、不额外卸载、不使用 deferred/force 关闭，不把诊断成功当作安装成功。
诊断子进程共用 15 秒软预算，18 秒 TERM、再 2 秒 KILL，父进程最多等待 22 秒；
证据采用私有文件逐步保存，采集超时或短命 PID 不覆盖原安装错误。
新增 15 项诊断回归覆盖 Btrfs 虚拟设备号、mountinfo 转义、进程消失、预算/输出限制、
块设备 FD、权限错误、秘密字段排除及失败状态保留；与既有 41 项合计 56 项本地通过，
真实结果见下一节。

### 第四次专用复验：实际确认其他命名空间保留目标挂载

[Run 45996299589](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45996299589)
使用测试提交 `fa77853c24834802308fb6857df7606cdc6270fc`。56 项宿主回归、KVM、
原始 ISO 身份/摘要校验和 Live 桌面均通过，实际安装再次在 `finalize` 的 mapper close 失败。
本轮生产安装器和 ISO 内容未改；原始失败继续保留，没有执行安装后硬盘启动。

即时诊断与后续 `diagnostics.storage_cleanup` 逐字段相同，明确记录：

- 后端 `phase=finalizing`、`owned_mounts=[]`，自身命名空间已无目标挂载。
- mapper `252:0` 的 open count 为 1，`cryptsetup status` 为 active and in use，
  sysfs holders 为空。
- 保存的 15 个独立服务命名空间仍挂载 Btrfs `0:78` 的 `/root` 子卷到 `/target`，
  SOURCE 均为本次 LUKS mapper；每个还保留 `/target/dev`、`/target/sys` 等子挂载，
  合计每个 17 条。涉及 userdbd、resolved、udevd、dbus-broker、NetworkManager、
  logind 等普通系统服务及数个 DDE 服务，不能归因为 DDE 或 UDisks 单独自动挂盘。
- 这些进程保存下来的直接 FD/cwd/root 引用列表为空；命名空间中的文件系统挂载本身
  就是实际引用，不需要进程另行打开一个目标文件。

已扫描 19 个命名空间、141 个 PID、879 个 FD，耗时 0.047 秒。采集器退出 0，但
到达预设输出上限，明确标记 `collection_complete=false`。保存下来的残留挂载足以
解释目标仍被占用；没有据此声称已经穷举全部命名空间或排除所有其他引用。

完整证据 [artifact 15195739622](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45996299589/artifacts/15195739622)
为 `5,123,443` 字节，共 71 个文件，实际下载后独立核验 SHA-256：
`ffdd1f855ecb92d85d7c4c4b655c18334f6e40939e3b4943a19afd95029c1957`。

修复需要在第一次安装挂载前建立安装器自己的 mount namespace，使目标与 runtime
挂载不出现在 PID 1 的命名空间中。仅对已经传播的 `/target` 事后改为 private 不足以
修复；单个 private 锚点也不能防止之后新建的服务命名空间复制目标挂载。
新修复将验证既有服务观察者、后启动观察者及跨阶段挂载可见性，再由新 RPM/ISO
完成真正的加密关闭和硬盘启动测试。原 `.3` 不会因为后续生产修复而被改述为通过。

### 完整安装的验收流程

每组先真实启动 ISO，经 DDM 登录并验收桌面，执行实际安装后端的
`preflight → partition → copy → system → ready → configure → finalize`。
用户、密码、时区和键盘在复制结束后的同一次 Live 启动内配置。之后关机、移除 ISO，
从同一虚拟硬盘启动，再检查根 UUID、挂载、账户、PAM、COPR、Enforcing 与桌面。

加密场景检查 LUKS2/单个 Argon2id 密钥槽、内层 UUID、crypttab、引导参数、普通
与 rescue initramfs 的解锁组件，且完成后卸载文件系统并关闭安装器创建的 mapper。
Live 目标阶段用 `cryptsetup --test-passphrase` 检查错误密码拒绝及正确密码接受；
硬盘启动阶段观察真实 initramfs 密码提示并输入正确密码，两种证据分别记录。

保留场景比较 home/ESP 的分区几何、UUID、PARTUUID 与随机标记文件摘要；磁盘 swap
场景检查启动后的活动 swap UUID；Btrfs 场景检查实际子卷与压缩挂载参数。

## 与 Fedora 常规安装的关系及验收边界

本项目保留 Fedora 软件源、`os-release`、RPM/DNF、原生认证与内核维护工具。
安装目标是普通可写文件系统；root 密码锁定，普通用户加入 wheel，sudo 仍需密码。
从独立只读基础镜像复制，清理 Live 账户与机器身份，再生成目标系统自己的配置。
Fedora 的 `kernel-install`、dracut、BLS、GRUB 与普通/rescue 镜像钩子均保留。

DDE、DDM、COPR、发行版资源与本安装器流程是 Remix 定制，不能把最终包集称为
官方 GNOME 介质的逐文件复制。自动分区尺寸和支持范围也不完全等同 Anaconda。

本矩阵是后端驱动的真实安装与图形登录测试，报告保留
`graphical_layout_planner_tested=false`。需要检查真实截图；非黑像素、壁纸或面板
单独出现均不能证明完整桌面可用。以下事项不在本轮实际验收范围内：

- 完整安装器 GUI 逐页点击与手动分区界面。
- Secure Boot、aarch64、多磁盘、真实 4Kn/NVMe 硬件及所有分区方式的排列组合。
- 实际选择 rescue 启动、安装后升级一次内核再启动、休眠恢复。
- zram 设备的独立运行断言；当前仅检查默认包/配置存在，磁盘 swap 有单独场景。

## 发布状态

- [ISO-Build draft PR #2](https://github.com/Fedora-DDE-Remix/ISO-Build/pull/2)，包含原候选与后续采集器修复；原 PR #1 已标记被替代并关闭，没有合并。
- [安装器 draft PR #1](https://github.com/Fedora-DDE-Remix/fedora-dde-installer/pull/1)

当前为独立候选的构建与测试工作。正式合并和 Release 应在本轮完整证据可审阅后确认。
