# 45.20261127.2 候选 ISO：构建失败记录

## 当前结论

[Actions 45974028174](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45974028174)
已完成，compose job `140421181413` **失败，没有生成 ISO**。构建在目标根中的
`glib-compile-schemas --strict` 阶段发现原 mediakey schema 的重复元数据并退出；
后续桌面资源检查程序、最终 payload 验证和 ISO 生成均未执行。

GitHub 的两个 VM 测试入口 job 均为 `skipped`，计划中的 **9 个场景全部未执行**。
本轮没有 Live 启动、真实安装、移除 ISO 后的硬盘启动或桌面验收结果，不能作为
正式发行通过凭据。

旧版 `45.20261127` 的桌面 SIGSEGV 和独立存储结果保留在
[原版报告](VALIDATION-45.20261127.md)；上一候选在 Live 图形输入阶段停止、没有
进入安装的事实保留在[45.20261127.1 报告](VALIDATION-45.20261127.1.md)。
它们不用于替代本候选的实际验收。

## 输入与来源

| 项目 | 本候选固定输入 |
| --- | --- |
| 系统 | Fedora 45，x86_64，传统可写 RPM / DNF 系统 |
| ISO 版本 | `45.20261127.2` |
| 配方提交 | `2d1ed2ce6dcb34bb2d3df56903b5de077cd83357` |
| 配方 tree | `3217968511bdf6cb6337a61c0adc199f16654567`，67 个源文件与 mode 已逐项核验 |
| 安装器提交 | `b5816732394a20188593b2918ebdddbc169e68dc` |
| 安装器 RPM | `fedora-dde-installer-0.3.0-0.2.fc45.x86_64` |
| DFM 四个运行包 | `6.6.7-9.1.remix1.fc45`，固定临时源码补丁 |
| desktop-base 临时包 | `2026.10.28-1.1.remix1.fc45.noarch`，仅依赖与 Release 调整 |
| 配置 RPM | `fedora-dde-remix-config-45.20261127.2-1.fc45.noarch` |
| 安全配置 | SELinux Enforcing，Fedora 原生 PAM 加 DDE 适配策略 |
| compose job | `140421181413`，`completed / failure` |
| ISO 产物、大小与 SHA-256 | 未生成，不适用 |

安装器的 [Fedora 45 原生构建](https://github.com/Fedora-DDE-Remix/fedora-dde-installer/actions/runs/45962759570)
已完成 Qt/DTK 编译、RPM/SRPM、三个 CTest 套件和实际 DNF 安装；本地后端为
142 项测试通过。Fedora 45 的解锁程序和 generator 由 `systemd-udev` 提供，
RPM 依赖及原生可执行检查均使用这个实际提供者。

完整 DFM RPM 的[独立复验](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45956698212)
通过安装、ELF、重定位与嵌套 Qt 插件探针。原构建的后续判据误报及 failure 状态
继续保留；schema 2 来源记录没有把旧失败改述为成功。

上述安装器构建与 DFM 复验是本候选使用的既有输入证据，不代表本轮已启动或
安装过 ISO。

## 本轮实际完成阶段与失败证据

| 阶段 | 实际结果与证据 |
| --- | --- |
| desktop-base 临时 RPM/SRPM 原生构建 | 完成；`desktop-base-rpmbuild.log` 记录两个产物，`desktop-base-hotfix-input.json` 的 `build_success` 为 `true` |
| Remix 配置 RPM/SRPM 构建 | 完成；`config-rpmbuild.log` 记录 `45.20261127.2-1.fc45` 的两个产物 |
| 定向标识包替换 | 通过移除范围检查；仅移除 `fedora-logos`，保留所有桌面包 |
| 本地安装器、配置及 DFM 四个运行包安装 | DNF 事务完成，实际 NEVRA 记于 `image-config.log` |
| `dde-desktop` 必选包检查 | 通过；69 个 mandatory 包全部安装 |
| 严格 GLib schema 编译 | **失败**；mediakey schema 在 `319:23` 报重复 `<summary>` |
| `/usr/libexec/fedora-dde-check-desktop-assets` | 未执行；位于失败的 schema 编译命令之后 |
| 最终 payload 检查、ISO 封装与启动结构检查 | 未执行，没有最终镜像产物 |
| 9 个 VM 场景 | 全部跳过，没有实际安装或启动结果 |

`logs/image-config.log` 的末尾在 mandatory 包检查通过后立即记录：

```text
/usr/share/glib-2.0/schemas/com.deepin.dde.keybinding.mediakey.gschema.xml:319:23  Error on line 319 char 23: Only one <summary> element allowed inside <key>.  --strict was specified; exiting.
```

原 schema 的 `away` key 已有 `summary` 和 `description`，后面又各有一个空元素。
GLib 在首个重复 `summary` 处退出。冻结配方中的命令顺序是先严格编译 schema，
再调用桌面资源检查程序；因此本轮没有该程序的通过结果，也没有最终 payload
通过结果。包安装完成不能替代这些未执行的验证。

### 失败诊断产物

| 项目 | 已核验记录 |
| --- | --- |
| Actions artifact | [`15187031683`](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45974028174/artifacts/15187031683) |
| ZIP 文件 | `ISO-build-logs-and-RPMs-15.zip` |
| ZIP 大小 | `96,362,606` 字节 |
| ZIP SHA-256 | `aa8c13ba85d84fc4a2067343f04d65a1732648c0f14f690316783c980124b4a6` |
| 内容 | 构建日志、输入记录、已生成 RPM/SRPM 及其来源证据；不含 ISO |

完整 ZIP 摘要已独立校验。主要诊断文件为 `logs/image-config.log`、
`logs/build.log`、`logs/anaconda-snapshot/runtime/anaconda.log`、
`logs/desktop-base-rpmbuild.log`、`logs/config-rpmbuild.log` 和 `build-info.json`。
上表中的大小与摘要属于失败诊断 ZIP，不能当作 ISO 身份。

## 本候选新增的修复

1. 登录测试按当前 Treeland 的实际输入框定位，先确认焦点，再慢速输入并只提交一次。
   15 项回归包括上一候选的两张原始 PNG；掩码数量仅为诊断，真实 DDM 登录和
   稳定桌面仍是独立门禁。
2. 补齐实际缺失的 JPEG 壁纸、Remix 标识和 DSysInfo 配置。设计要求构建时检查
   真实 RPM 所有权与编译后的默认值，VM 登录后读取实际用户配置并保存渲染截图；
   本轮在这些资源检查与 VM 步骤之前失败。
3. 在 ISO-Build 内临时重建 desktop-base 的通用标识依赖，再定向使用 `generic-logos`。
   本次 compose 时维护仓库保持只读；移除范围检查已确认只替换原主标识包。

详见[桌面插件、资源与临时 SPEC 报告](DDE-HOTFIX-20261127.md)。

## 安装后默认 COPR

配置 RPM 持久管理标准文件：

```text
/etc/yum.repos.d/_copr:copr.fedorainfracloud.org:mozixun:Fedora-DDE-Remix.repo
```

仓库 ID 保持 `copr:copr.fedorainfracloud.org:mozixun:Fedora-DDE-Remix`，默认启用，
保留 `gpgcheck=1` 与 `sslverify=1`。URL 使用 `$releasever`、`$basearch`，经核验的
公钥由配置包保存并使用 `file://` 引用。目标系统移除 Live 安装器时保留这个配置 RPM。
配方要求在构建末期检查最终 payload，再分别在 Live 和安装系统中通过 DNF
确认实际启用状态。本轮没有到达这些最终检查，也没有运行 VM；此节说明的是
实现与预定验收要求，不能记为本候选的运行验证通过。

## 加密与容量

本节记录本候选安装器的实现和计划验证范围；本轮未执行加密或非加密安装。

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

## 计划的真实 VM 安装矩阵：全部跳过

本轮没有 ISO 可供启动。两个测试入口
[加密小盘与桌面首测](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45974028174/job/140425274554)
和[其余分区组合](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45974028174/job/140425274384)
均为 `completed / skipped`，没有展开为 9 次实际 VM 执行。

计划要求所有场景使用同一 ISO、x86_64、单块 VirtIO 磁盘、512 字节逻辑扇区。
UEFI 使用未启用 Secure Boot 的 OVMF，BIOS 使用 SeaBIOS。各场景具有独立
2 GiB ext4 `/boot`，UEFI 场景的 ESP 为 600 MiB FAT32。

| 场景 | 固件 / 分区表 | 磁盘 | 根 / home / swap | 本候选结果 |
| --- | --- | --- | --- | --- |
| `uefi-luks-btrfs-small` | UEFI / GPT | 十进制 16 GB | LUKS2 内 Btrfs root/home | 跳过，未执行 |
| `uefi-btrfs` | UEFI / GPT | 64 GiB | Btrfs root/home | 跳过，未执行 |
| `bios-ext4` | BIOS / GPT | 64 GiB | ext4 根、根内 home、2 MiB BIOS boot | 跳过，未执行 |
| `bios-mbr-ext4` | BIOS / MBR | 64 GiB | ext4 根、根内 home | 跳过，未执行 |
| `uefi-xfs-home-swap` | UEFI / GPT | 64 GiB | 32 GiB XFS 根、独立 ext4 home、2 GiB swap | 跳过，未执行 |
| `uefi-preserve` | UEFI / GPT | 64 GiB | 新建 Btrfs 根，保留 ext4 home 与 ESP | 跳过，未执行 |
| `uefi-small` | UEFI / GPT | 十进制 16 GB | Btrfs root/home | 跳过，未执行 |
| `bios-luks-ext4` | BIOS / GPT | 64 GiB | LUKS2 内 ext4 根与 home | 跳过，未执行 |
| `uefi-luks-xfs` | UEFI / GPT | 64 GiB | LUKS2 内 XFS 根与 home | 跳过，未执行 |

预定流程是每组先真实启动 ISO，经 DDM 登录并验收桌面，执行实际安装后端的
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

预定矩阵使用后端驱动的真实安装与图形登录测试，范围标记为
`graphical_layout_planner_tested=false`；本轮没有生成 VM 报告或截图。
实际执行时仍需检查真实截图；非黑像素、壁纸或面板
单独出现均不能证明完整桌面可用。以下事项不在本轮实际验收范围内：

- 完整安装器 GUI 逐页点击与手动分区界面。
- Secure Boot、aarch64、多磁盘、真实 4Kn/NVMe 硬件及所有分区方式的排列组合。
- 实际选择 rescue 启动、安装后升级一次内核再启动、休眠恢复。
- zram 设备的独立运行断言；当前仅检查默认包/配置存在，磁盘 swap 有单独场景。

## 发布状态

- [ISO-Build draft PR #1](https://github.com/Fedora-DDE-Remix/ISO-Build/pull/1)
- [安装器 draft PR #1](https://github.com/Fedora-DDE-Remix/fedora-dde-installer/pull/1)
- [桌面维护仓库 draft PR #1](https://github.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/pull/1)

`45.20261127.2` 的结论固定为构建失败、无 ISO、9 个 VM 场景未执行。
后续 `45.20261127.3` 计划集成 schema 修复后重新构建，其证据与结果单独记录，
不会回填为本候选成功，也不借用 `.1` 或原版的检查结果。

本次 `.2` 构建期间，桌面维护仓库仅作为只读来源。随后用户另行授权审查并提交
已确认的 SPEC 修复，改动已放入上述维护仓库的独立分支与 draft PR；维护仓库
`main` 尚未修改，也没有为这些提案触发 COPR 构建。维护者将自行构建验证。
这些后续提案不属于本次 `.2` 固定输入。

本候选不具备正式合并或 Release 的通过依据。
