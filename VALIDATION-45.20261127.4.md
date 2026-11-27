# 45.20261127.4 候选：安装挂载隔离与真实验收

## 当前状态

本候选将安装器升级到 `0.3.0-0.3`，修复 `.3` 实际加密安装结束时无法关闭 LUKS
映射的问题。新的真实内核隔离回归和 Fedora 45 原生 RPM 构建已经通过；本候选 ISO 的 compose、完整安装和
硬盘启动仍待执行。这里不以单元测试、源码修复或上一镜像的桌面结果替代本轮验收。

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

`.3` 专用的临时 push 复测入口只保留在当时的提交中。本候选继续使用完整的
`compose → 小盘加密 canary → 其余八组` 自动链，以及带显式 ISO run/artifact
参数的 workflow_call / workflow_dispatch。发布新配方不会意外复测旧 `.3` 镜像。

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
Fedora VM 中的 SELinux、真实 dm-crypt 关闭和硬盘启动仍待本候选实际验收。

## 本轮真实 VM 矩阵

所有场景均使用同一实际 ISO、x86_64、单块 VirtIO 磁盘和 512 字节扇区。
UEFI 为未启用 Secure Boot 的 OVMF，BIOS 为 SeaBIOS；各场景有独立 2 GiB ext4
`/boot`，UEFI ESP 为 600 MiB。小盘是十进制 16,000,000,000 字节。

| 场景 | 根与数据布局 | 状态 |
| --- | --- | --- |
| `uefi-luks-btrfs-small` | 16 GB，GPT，LUKS2 内 Btrfs root/home | 待本候选实际运行 |
| `uefi-btrfs` | 64 GiB，GPT，Btrfs root/home | 待 canary 成功后运行 |
| `bios-ext4` | 64 GiB，GPT，ext4，2 MiB BIOS boot | 待 canary 成功后运行 |
| `bios-mbr-ext4` | 64 GiB，MBR，ext4 | 待 canary 成功后运行 |
| `uefi-xfs-home-swap` | 64 GiB，GPT，XFS 根、ext4 home、2 GiB swap | 待 canary 成功后运行 |
| `uefi-preserve` | 64 GiB，GPT，新 Btrfs 根，保留 home 和 ESP | 待 canary 成功后运行 |
| `uefi-small` | 16 GB，GPT，Btrfs root/home | 待 canary 成功后运行 |
| `bios-luks-ext4` | 64 GiB，GPT，LUKS2 内 ext4 | 待 canary 成功后运行 |
| `uefi-luks-xfs` | 64 GiB，GPT，LUKS2 内 XFS | 待 canary 成功后运行 |

真实验收必须包含正常 finalize、移除 ISO 后启动、账户与根 UUID、普通可写根、
Enforcing、Fedora PAM、默认 COPR 及完整桌面。加密场景还要真实拒绝错误口令，
保存无目标 keyfile 的配置，并通过硬盘启动时的 initramfs 口令解锁。

这仍是后端驱动的真实安装和图形登录测试，`graphical_layout_planner_tested=false`；
没有宣称 GUI 全流程点选、Secure Boot、实体硬件、aarch64、4Kn、多磁盘、所有布局
排列组合、实际 rescue 启动或内核升级后启动已通过。14 GiB 设备初筛及 12 GiB
内层根下限不是所有未来 payload 的容量承诺，实际空间检查和本轮小盘结果才是依据。

## 发布门槛

当前仍为独立候选。完整证据可审阅后，再处理主分支合并和正式 Release。
桌面维护仓库的 [18 份 SPEC 修复 PR](https://github.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/pull/1)
独立保留，未触发 COPR 构建；维护者自测范围和已验证部分写在对应审查记录中。
