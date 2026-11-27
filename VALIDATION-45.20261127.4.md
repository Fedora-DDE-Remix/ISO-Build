# 45.20261127.4 候选：安装挂载隔离与真实验收

## 当前状态

本候选将安装器升级到 `0.3.0-0.3`，修复 `.3` 实际加密安装结束时无法关闭 LUKS
映射的问题。新的真实内核隔离回归、Fedora 45 原生 RPM 构建与本候选 ISO compose
已经通过；同一镜像的九个后端驱动真实安装场景，现均已完成正常收尾、无 ISO
硬盘启动和真实 DDM 图形登录。九份实际 VM 报告与证据 ZIP 已下载并核验，详见
[最终机器可读汇总](validation/45.20261127.4-results.json)。

原 run `46002723335` 的总体状态仍是 failure：其中八个实际 VM 场景通过，
XFS/home/swap 一组在启动 VM 前的 host 回归夹具处失败。只修正该夹具后，使用
同一份 ISO 在 run `46008724244` 完成第九组；原失败没有被改写为成功。本报告
区分 ISO 构建、测试控制代码和最终文档提交，不用其他镜像或单元测试替代实际验收。

## 已确认的前版失败与修复

`.3` 的 Live 图形登录、稳定桌面、资源与 Fedora PAM 已通过；16 GB 加密安装已
完成复制、系统和用户配置，但正常卸载后 mapper 仍 busy。其
[实际诊断](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45996299589)
保存了至少 15 个系统服务命名空间中的同一 Btrfs 目标根及 runtime 挂载副本。
安装器自己的 `owned_mounts=[]`，mapper open count 为 1。完整历史和原始 artifact
身份见[第三候选报告](VALIDATION-45.20261127.3.md)，失败结果继续保留。

新安装器在第一次安装挂载前，通过生产 `fedora_namespace.py --exec` 创建私有
mount namespace，然后启动长期 GUI。所有 hook 继承它；GUI 直接入口、后端入口
和后续状态分别核对实际隔离及命名空间身份。PID 1 不会收到安装挂载，因此既有
服务和之后创建的服务都没有目标挂载可继承。正常卸载与关闭 mapper 的要求不变。
同次 Live 启动内的用户、密码、时区和键盘配置也保留。

VM 控制器先完成原有 Live 桌面与 PAM 验证，再让已经通过普通账户和 sudo 认证的
持久 root shell 调用同一个生产执行器。后续阶段、目标加密检查和最终状态都核对
同一 namespace device/inode；没有用测试替代实现。安装器退出后，未完成的旧状态
不会被另一 namespace 接管；这类异常需要重启 Live 环境后处理。

## 固定输入

| 项目 | 本候选输入 |
| --- | --- |
| 系统 | Fedora 45 / x86_64，普通可写 RPM / DNF 系统 |
| ISO / 配置 RPM 版本 | `45.20261127.4` |
| ISO 构建源码 | `ec9903e1addf5e487f468680c6af4e34ce6bf873`，compose run `46002723335` |
| 安装器源码 | `bd06acc59908771c726b907d65c92bc84b9f807d` |
| 安装器 tree | `5e637e59b7cee183526f76d51972a96834d257f7`，503 个源文件已完整核对 |
| 安装器版本 | `0.3.0-0.3` |
| 安装器构建 | [46001067422](https://github.com/Fedora-DDE-Remix/fedora-dde-installer/actions/runs/46001067422)，原生构建、3 个 CTest、实际 DNF 安装与加密依赖提供者检查均成功 |
| 安装器 RPM artifact | [15198317588](https://github.com/Fedora-DDE-Remix/fedora-dde-installer/actions/runs/46001067422/artifacts/15198317588)，实际 ZIP 27,185,010 字节，SHA-256 `4f74da31a87cc93bdd5285d4ce15fb6033f5683d77bb5e0ae670c4441778098f` |
| 安装器二进制 RPM | `fedora-dde-installer-0.3.0-0.3.fc45.x86_64.rpm`，3,034,868 字节，SHA-256 `83d50c61fc8c811b3e3a659a605c6a8f720b51168e1ff7ad044adf04c881d247` |
| 安装器 SRPM | `fedora-dde-installer-0.3.0-0.3.fc45.src.rpm`，3,177,459 字节，SHA-256 `222cf647eaf3a9325fd76ad4dd4223e39d673897efd391505f45caebec59022b` |
| DFM 临时四个运行包 | `6.6.7-9.1.remix1.fc45`，继续使用已核验 schema 2 输入 |
| desktop-base / schemas | 继续使用固定源码、补丁与严格检查的临时重建 |
| 安全配置 | SELinux Enforcing，Fedora 原生 PAM，已启用 COPR 及签名/TLS 检查 |
| XFS/home/swap 补测控制代码 | `7c80ee0f6176fdb708bd1296afba157988f12670`，retest run `46008724244`；不是 ISO 构建来源 |

`.3` 专用的临时 push 复测入口只保留在当时的提交中。本候选使用完整的
`compose → 小盘加密 canary → 其余八组` 自动链，以及带显式 ISO run/artifact
参数的 workflow_call / workflow_dispatch。本次补测曾通过仅允许
`validate-iso4-20261127` 分支的临时 push 入口，固定原 ISO 的 commit、run、artifact
与原文件 SHA-256，只选择 `uefi-xfs-home-swap`。该自动 push 入口现已停用，常规
入口保留 workflow_call / workflow_dispatch。补测和之后的汇总、文档提交都没有
重新 compose；已测 ISO 的构建来源始终是 `ec9903e1…`，不是 `7c80ee0f…` 或最终
文档提交。

## 实际 ISO compose

[Run 46002723335 / compose job 140518179572](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46002723335/job/140518179572)
成功；实际配方 commit 为 `ec9903e1addf5e487f468680c6af4e34ce6bf873`，tree
`6bb0dbbdc6024537fcf9232b8eb6a011efab3bb8`，81 个源文件的 blob 与 mode 已完整核验。

| 产物 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `Fedora-DDE-Remix-45.20261127.4-x86_64.iso` | 3,462,608,896 | `94009516d1751403a77bb24252ff097f3a85943d87430f11b5b2dd0dc808274a` |
| [ISO ZIP artifact 15202111074](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46002723335/artifacts/15202111074) | 3,462,665,781 | `4557755c1adc7ac7de8cfb931685787cd120b9486efd063fd1e2f1a606fc5f87` |
| [日志/RPM ZIP artifact 15202375965](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46002723335/artifacts/15202375965) | 98,046,960 | `9bcd27ff5ee7e2bd0954e9e3f6815bbfc76c864bddf0e92fddc0fa9439c0fea5` |

ISO 原文件与 ZIP 校验值不同。原 ISO 校验值由实际 compose 日志及构建日志记录，
本地没有下载这份 3 GB 镜像；VM 工作流在下载后另行验证真实文件。小证据 ZIP 已
实际下载并独立重新计算哈希。`build-info.json` 明确记录使用上表新安装器 RPM，
其 binary/SRPM digest 与原生构建一致；没有走重建或旧版回退。

实际 payload 有 1,212 个包名，桌面组 69 个 mandatory 包全部存在。
`fedora-dde-remix-config` 为 `45.20261127.4-1.fc45`，安装器为
`0.3.0-0.3.fc45`；native Fedora PAM、目标策略注册与标签、资源及编译后的 schemas、
BIOS/UEFI 引导文件检查均通过。这些镜像检查不替代下一节的运行时验收。

## 真实内核隔离证据

[安装器 run 46001067422](https://github.com/Fedora-DDE-Remix/fedora-dde-installer/actions/runs/46001067422)
的 safe-tests 在独立的 Linux mount namespace 中，仅用临时 tmpfs/bind 挂载与
测试自己的进程，实际完成：

- shared 正对照能向已有 slave 观察者传播，并在普通卸载后消失。
- 生产执行器内四个独立阶段进程保持同一 namespace；挂载数依次为 7、7、0、0。
- 已有观察者、模拟 host，以及挂载后从 host 新建的观察者都没有目标挂载或标记。
- 普通卸载释放目标及准备文件系统，测试外层 mountinfo 恢复原状。
- 非 root 实际调用返回 1，明确报告需要 root，目标命令未执行；使用的两份生产
  文件与源文件 SHA-256 完全一致。

真实 JSON `passed=true`，artifact [15197957599](https://github.com/Fedora-DDE-Remix/fedora-dde-installer/actions/runs/46001067422/artifacts/15197957599)
为 1,402 字节，实际下载后独立核验 SHA-256：
`92d1026085236f7858e69a1964aec2ba40207d3a6367639250c0a232bb44a11d`。

初版测试 [46000297976](https://github.com/Fedora-DDE-Remix/fedora-dde-installer/actions/runs/46000297976)
曾在非 root 子进程断言处失败，RPM 未构建；当时未保存该子进程 stderr，因此不能
认定权限绕过，也不能把 checkout 路径权限认定为已证实原因。后续仅修正测试的
代码可访问前提和诊断，保留同一生产拒绝规则；原失败没有被覆盖。

此内核回归在 GitHub Ubuntu runner 上执行，验证传播机制。随后 Fedora 45 的真实
Qt/RPM 构建与 `%check` 的 3 个 CTest 全部通过，实际安装的版本为
`0.3.0-0.3.fc45`。两个加密启动文件确由 `systemd-udev` 提供，RPM 中的 namespace
helper 与后端 SHA-256 分别为 `3faedc0c22ee0bea9b2be6017d06ad08eff096733a2bd2fee34966b7daa81e7f`
和 `327bfe7697dcc5249c2a55ef700368440b261ea334582f80e4e17f23966d88d5`，与冻结源码一致。
本候选的 16 GB 加密 canary 现已完成 Fedora VM 中的 SELinux、真实 dm-crypt
关闭和硬盘启动验证，具体记录如下。

## SELinux 核查范围

当前镜像使用固定维护提交 `adcd681b0b9e68cacbf9daa33bede62a253a3315` 的四个
DDE 策略包。只读核对实际
[ddm.te](https://github.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/blob/adcd681b0b9e68cacbf9daa33bede62a253a3315/ddm-selinux/ddm.te)、
[dde_daemon.te](https://github.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/blob/adcd681b0b9e68cacbf9daa33bede62a253a3315/dde-daemon-selinux/dde_daemon.te)、
[dde_api.te](https://github.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/blob/adcd681b0b9e68cacbf9daa33bede62a253a3315/dde-api-selinux/dde_api.te) 和
[deepin_system_monitor.te](https://github.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/blob/adcd681b0b9e68cacbf9daa33bede62a253a3315/deepin-system-monitor-selinux/deepin_system_monitor.te)
及对应 SPEC，未发现显式 permissive 声明、`setenforce` 或 `semanage permissive`
操作。DDM 使用已有 `xdm_t`；Fedora 默认的 `unconfined_t` / `unconfined_service_t`
与将域显式设为 permissive 是不同概念，没有据此扩大加固或更改维护者策略。

运行时验收检查全局 Enforcing、启动参数、四个模块注册、核心文件标签和 DDM
实际 `xdm_t`。它没有保存编译策略中所有 permissive 类型的完整清单，因此不作
“所有域均已逐一验证 enforcing”的额外声明。本候选实际选择 `enforcing` 安装
profile，镜像检查拒绝禁用 SELinux 的启动参数。

Enforcing 不等于没有 AVC。实际 Live 日志保留了 `kmscon_t` 对 `tmpfs_t`
文件系统的 `getattr` 拒绝，`permissive=0`。例如 XFS/home/swap
[补测 job 140538520123](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46008724244/job/140538520123)
的 `live/diagnostics.json → avc` 保存 22 条此类记录，发生于首次 Live 图形登录
阶段、进入安装 namespace 之前；该次 installed 采集返回零条 AVC。这里仅说明
已保存的采集结果，不声称全部场景全程零 AVC，也不从该日志推断具体 tmpfs 挂载点。

## 本轮真实 VM 矩阵

所有场景均使用同一实际 ISO、x86_64、4 vCPU、8 GiB RAM、实际 KVM 加速，
单块 VirtIO 磁盘和 512 字节扇区。
UEFI 为未启用 Secure Boot 的 OVMF，BIOS 为 SeaBIOS；各场景有独立 2 GiB ext4
`/boot`，UEFI ESP 为 600 MiB。小盘是十进制 16,000,000,000 字节。
8 GiB 是本轮测试配置，没有据此给出经过验证的最低内存要求。

[最终汇总 JSON](validation/45.20261127.4-results.json) 逐组记录 run/job/artifact、
ZIP 与报告 SHA-256、ISO 身份及验收字段。八组来自原 run `46002723335`，
`uefi-xfs-home-swap` 来自同镜像补测 `46008724244`。

| 场景 | 根与数据布局 | 状态 |
| --- | --- | --- |
| `uefi-luks-btrfs-small` | 16 GB，GPT，LUKS2 内 Btrfs root/home | 正常关闭映射、硬盘解锁启动和图形登录通过 |
| `uefi-btrfs` | 64 GiB，GPT，Btrfs root/home | 实际安装、硬盘启动和图形登录通过 |
| `bios-ext4` | 64 GiB，GPT，ext4，2 MiB BIOS boot | 实际安装、GPT 硬盘启动和图形登录通过 |
| `bios-mbr-ext4` | 64 GiB，MBR，ext4 | 实际安装、MBR 硬盘启动和图形登录通过 |
| `uefi-xfs-home-swap` | 64 GiB，GPT，XFS 根、ext4 home、2 GiB swap | 原 VM 前失败保留；同镜像补测完整通过 |
| `uefi-preserve` | 64 GiB，GPT，新 Btrfs 根，保留 home 和 ESP | 硬盘启动、图形登录及保留内容检查通过 |
| `uefi-small` | 16 GB，GPT，Btrfs root/home | 小盘完整安装、硬盘启动和图形登录通过 |
| `bios-luks-ext4` | BIOS/GPT，64 GiB，LUKS2 内 ext4 | 正常关闭映射、硬盘解锁启动和图形登录通过 |
| `uefi-luks-xfs` | 64 GiB，GPT，LUKS2 内 XFS | 正常关闭映射、硬盘解锁启动和图形登录通过 |

### 16 GB 加密 canary 的实际证据

[Job 140529003262](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46002723335/job/140529003262)
成功，实际运行 442.51 秒；`report.json` 为 `passed`、
`installation_checks_completed=true`、`desktop_failures=[]`。
[Artifact 15200938525](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46002723335/artifacts/15200938525)
保存 115 个文件，实际 ZIP 9,613,138 字节，独立重算 SHA-256 为
`e58279adf83bf512b579db44daea042ca2e54590d9a5837dc36a5d94adf6f860`。

- 真实下载的 ISO 大小与 SHA-256 匹配上表；本次 VM 为 4 vCPU、8 GiB RAM、
  16,000,000,000 字节磁盘，实际启用 KVM。
- namespace 从 `4026531832` 切换到 `4026532662`，七个生产后端阶段及 finalized
  状态都保持后者。普通 finalize 在 0.50 秒内完成，`owned_mounts=[]`、
  `owned_mappers=[]`、`secrets_cleared=true`；Live 诊断中的 LUKS 分区已无 dm 子设备。
- 重启前实际拒绝错误口令、接受正确口令；容器为 LUKS2 / Argon2id / 一个 keyslot，
  crypttab 密钥文件字段为 `none`。正常与 rescue BLS 配置和安装摘要未包含测试口令。
- 随后 QEMU 命令不带 ISO，boot ID 从 `29c2f1ab-69bd-4402-b446-2f8289fe4111`
  变为 `99f7153c-0b7f-4b4c-b4f5-abe23e3a8353`。实际 initramfs 提示输入口令，
  正确口令解锁后成功登录。没有把重启前的错误口令检查表述为启动界面错误口令测试。
- `/` 与 `/home` 从同一个已解锁 Btrfs 的 root/home 子卷挂载，根可写；普通用户
  UID 1000 / wheel，root 锁定，Live 用户已移除。Live、安装后及图形登录后的
  Enforcing、DDM `xdm_t`、原生 PAM 和已启用且保留 GPG/TLS 检查的 COPR 均通过。
- 原始截图与运行日志复核确认壁纸、面板和 Computer/Trash 图标存在；安装后没有
  安装器快捷方式。一次预览显示差异已通过原 PNG 对应区域的逐像素一致比较排除，
  没有据此修改桌面包。桌面服务 active、2 项图标已加载，未记录 coredump。

### 其他布局增加的实际覆盖

- BIOS GPT 与 MBR 的分区日志分别记录 `mklabel gpt` 和 `mklabel msdos`；随后
  无 ISO 的磁盘启动内核参数分别来自 `(hd0,gpt2)` 与 `(hd0,msdos1)`，实际根 UUID
  与安装结果一致。没有仅依据预定分区计划声称两种启动方式通过。
- 两个未加密 Btrfs 场景的 `/` 与 `/home` 实际使用同一 UUID 的 root/home 子卷，
  均有 `compress=zstd:1`。16 GB 未加密安装也完整通过；安装后 `lsblk` 显示约
  `8.5G` 可用空间。各场景的运行诊断均观察到启用的 zram。
- BIOS 加密 ext4 和 UEFI 加密 XFS 都在普通 finalize 后关闭 mapper，再通过
  硬盘启动时的交互口令解锁。`/home` 是同一加密根内的目录，未落到明文独立分区。
  两组都验证 LUKS2、Argon2id、一个 keyslot、crypttab 的 `none` 密钥文件字段。
- 保留场景在磁盘启动后逐项比较原 home 和 ESP 的文件系统 UUID、PARTUUID、
  起止扇区，以及各自 256 字节随机 marker 的 SHA-256，全部一致。新系统正确挂载
  保留的 ext4 `/home`；ESP 中无关厂商目录的测试文件也保留。该测试没有比较
  安装前后的 UID/GID、mode、ACL 或 xattrs，不能扩大为这些属性已全部实测不变。

最后完成的 UEFI 加密 XFS
[job 140533252835](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46002723335/job/140533252835)
为 success；[artifact 15203771377](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46002723335/artifacts/15203771377)
实际 ZIP 9,899,924 字节，SHA-256
`2709fa07f349fede777cb9defaf5e27938639f5f0e1079b371ca2560a95980bc`。
安装后根与 home 均位于 `luks-814c1b9f-aae2-49cf-b361-df9f1ada8a12`，XFS UUID
为 `0499308b-d1e3-4fcf-9bb4-8cdc6b017dd4`；明文 ext4 `/boot` 和 FAT ESP 独立挂载。

### XFS/home/swap 的前置回归失败及补测

[原 job 140533252729](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46002723335/job/140533252729)
在下载 ISO、启动 VM 之前失败：GNU timeout 返回 137，串口结束标记和后续命令均
已通过，但测试只读一次 `/proc/PID/stat` 并断言 `Z`，当时读到 `R`。旧日志没有
记录 starttime，不能确定是异步退出尚未结束还是 PID 复用，也不能据此判定 XFS 安装失败。

原 [artifact 15201068518](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46002723335/artifacts/15201068518)
只有 4 个 host 诊断文件，没有 VM 报告；实际 ZIP 964 字节，SHA-256
`1fd6e11c89dcca2da60957696571c10135f132c135515c45942f4319e20adb54`，失败继续保留。

仅修正 host 回归夹具：在进程存活时记录 PID/starttime，对原身份最多观察 3 秒；
只有已消失、`ENOENT/ESRCH`、`Z/X` 或 PID 身份已变化才通过。原身份持续存活仍失败，
权限错误仍失败，137/串口 END/后续命令断言不变；cleanup 也核对原进程身份和唯一
临时路径。4 项针对性验证通过，含一次真实 timeout。生产控制器、安装器、ISO、
桌面等待时间及验收规则均未改变。

[补测 run 46008724244 / job 140538520123](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46008724244/job/140538520123)
现已成功：58 项 host 回归通过，随后 22 个实际 VM 阶段全部通过。
[Artifact 15203276917](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46008724244/artifacts/15203276917)
实际 ZIP 9,921,189 字节，独立核验 SHA-256
`9553ba4abbf022851537c7b5d075b4dc2dc450e0a4f3ce2d92aa01f015362066`。
报告确认仍是上表 `94009516…` 的同一 ISO，`iso_unchanged=true`；安装后 XFS 根
实际挂载于 `/dev/vda3`，独立 ext4 home 为 `/dev/vda4`，`/dev/vda5` 的磁盘 swap
与 `/dev/zram0` 同时启用。正常 finalize、无 ISO 磁盘启动、新 boot ID、用户与根
UUID、Enforcing、PAM、COPR、Live 与安装后图形登录均通过。原 run 的总体 failure
及其 host 失败 artifact 继续保留，不用这个独立成功结果改写历史。

上述九组实际验收包含正常 finalize、移除 ISO 后启动、账户与根 UUID、普通可写根、
Enforcing、Fedora PAM、默认 COPR、真实 DDM 会话与稳定桌面画面。三个加密场景
还在重启前实际拒绝错误口令，保存无目标 keyfile 的配置，并通过硬盘启动时的
initramfs 交互口令解锁。

以上九组均为后端驱动的真实安装和图形登录测试，`graphical_layout_planner_tested=false`；
生产流程确实在同一次 Live 启动内经过 ready、用户配置和 finalize，再由测试主动
关机切换到硬盘启动；这不等于安装 GUI 的每一页已经逐项点选验收。
没有宣称 GUI 全流程点选、Secure Boot、实体硬件、aarch64、4Kn、多磁盘、所有布局
排列组合、实际 rescue 启动或内核升级后启动已通过。14 GiB 设备初筛及 12 GiB
内层根下限不是所有未来 payload 的容量承诺，实际空间检查和本轮小盘结果才是依据。

## 发布门槛

九组实际安装验收已完成，当前仍为独立候选，正式 Release 尚未发布。完整证据
供最终审阅；主分支合并和正式 Release 仍需相应批准，已有成功结果不代替这些门槛。
桌面维护仓库的 [18 份 SPEC 修复 PR](https://github.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/pull/1)
独立保留，未触发 COPR 构建；新增维护者 EVR 尚未完成其 COPR 构建验收。本 ISO
验证的是固定发布包及这里列出的临时重建版本，不能将其当作 18 份新 SPEC 版本
全部构建成功。维护者自测范围和已验证部分写在对应审查记录中。
