# Fedora DDE Remix ISO

此仓库构建 **Fedora 45 / x86_64 的传统可写系统 Live ISO**。安装器采用
`Fedora-DDE-Remix/fedora-dde-installer`，在当前 Live 会话内完成安装、用户、
密码、时区和键盘配置，由用户决定何时重启。

**当前配方为 45.20261127.4 候选，正式 Release 尚未发布。**
旧版 `45.20261127` 的真实桌面插件 SIGSEGV 和存储测试见
[原版验证报告](VALIDATION-45.20261127.md)。`45.20261127.1` 已构建 ISO，但其
首个 VM 在输入登录密码前后失败，未进入安装阶段；实际证据与控制器定位缺陷见
[上一候选报告](VALIDATION-45.20261127.1.md)。`45.20261127.2` 补齐资源后，又在
原桌面 schemas 的严格编译处发现重复 XML 元素，未生成 ISO，见
[第二候选报告](VALIDATION-45.20261127.2.md)。`.3` 加入已复现并修复的 schemas
临时重建，已通过[真实 Go/RPM 严格检查与 ISO compose](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45981240945/job/140445377978)，
以及真实 Live 桌面和同 Live 账户配置，但加密安装收尾发现目标挂载泄漏到系统服务的
mount namespace，详见[第三候选记录](VALIDATION-45.20261127.3.md)。当前 `.4` 使用
安装器 `0.3.0-0.3`，在整个安装会话开始时隔离挂载；现有和后启动服务隔离已通过
[真实内核回归](https://github.com/Fedora-DDE-Remix/fedora-dde-installer/actions/runs/46001067422)。
新 ISO compose 和下列九个后端驱动真实安装、无 ISO 硬盘启动及 DDM 图形登录
场景现已全部通过，包括三个 LUKS2 场景的正常关闭映射和交互口令启动。原 run
`46002723335` 仍保留总体 failure：其中八个 VM 通过，XFS 根、独立 home/swap
一组在启动 VM 前的 host 回归夹具处失败。仅修正夹具观察方式后，该组使用同一
镜像在 run `46008724244` 完整通过，见[第四候选报告](VALIDATION-45.20261127.4.md)
和[九组证据汇总](validation/45.20261127.4-results.json)。这不是安装 GUI 全页
点选测试，也不改写原失败记录。

已测 ISO 的构建提交始终是 `ec9903e1addf5e487f468680c6af4e34ce6bf873`，原文件
SHA-256 为 `94009516d1751403a77bb24252ff097f3a85943d87430f11b5b2dd0dc808274a`。
补测代码 `7c80ee0f6176fdb708bd1296afba157988f12670` 和之后的证据、文档提交不是
这个 ISO 的构建来源；补测没有重建或改写镜像。

**本系列候选保持 SELinux Enforcing**：Live 和安装目标使用 Fedora 原生 PAM，
系统配置为 `SELINUX=enforcing`。Live 启动参数显式包含 `selinux=1 enforcing=1`；
安装器为目标系统生成正常磁盘引导参数，使用 Fedora 默认的 Enforcing 行为。
镜像使用维护者发布的 DDM 和 DDE SELinux 策略包，构建时验证策略注册和文件标签。
本候选已完成下面列出的实际 VM 安装检查；仅生成 ISO 不代表安装验证通过。
运行检查没有枚举编译策略中的全部 permissive 类型，因此不宣称每个域都逐一通过
该项验证。Live 日志还保留了 `kmscon_t` 对 `tmpfs_t` 的 enforcing AVC，具体采集
范围见验证报告；没有以关闭 SELinux 处理，也不声称全程零 AVC。

此版在 ISO 配置 RPM 中加入 DDM 的 `kmsconvt@tty1.service` 启动顺序和冲突声明。
Fedora 45 的新 VT 控制台使用该单元，DDM 上游 0.5.0 原单元仅处理传统
`getty@tty1.service`。缺少新声明可能让 tty1 控制台和 Treeland 同时竞争显卡控制权；
虚拟机曾实际观察到黑屏、Treeland 分配缓冲区失败和重复崩溃。
该配置由本仓库的 RPM 单独管理，采用
[Fedora 同类问题的处理方式](https://bugzilla.redhat.com/show_bug.cgi?id=2549227)，
图形登录恢复情况仍以新版 ISO 的实际测试报告为准。

## 桌面软件来源

维护者提供的桌面安装流程分成两个独立 DNF 事务：

```bash
sudo dnf copr enable mozixun/Fedora-DDE-Remix
sudo dnf install dde-desktop-comps
sudo dnf group install dde-desktop
```

DNF 5 的 `group install` 对应桌面组安装操作。comps RPM 先安装本地组元数据，
下一次 DNF 运行才能解析 `dde-desktop` 组。配方保留这个顺序，不维护第二份桌面包清单。
预检从正式 COPR 仓库刷新并安装 `dde-desktop-comps`，要求版本不低于
`6.2.1-5.fc45`。下载后校验固定项目公钥、RPM 签名和版本，记录实际 SHA-256；
镜像内先安装同一份已验证的 comps RPM，再单独安装桌面组。正式仓库缺包或
校验失败会阻止构建，不再回退到旧版 comps 或 `-devel` 分发。

产物的 `comps-input.json` 和 `build-info.json` 记录实际选择的来源、版本及校验值。
安装后直接读取该 RPM 的 comps 元数据，逐一检查 `dde-desktop` 的 mandatory 包已安装；
DNF 即使跳过缺失的组包并返回成功，也不能绕过这项检查。
本工作流不写入 COPR。经后续追加的 SPEC 修复要求，维护仓库的已确认问题另通过
[独立修复 PR](https://github.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/pull/1)
提交，保留主分支供维护者审阅合并，COPR 构建由维护者自测。
其中 18 份 SPEC 的新增维护者 EVR 尚未完成 COPR 构建验收；本候选临时包的成功
验证不代表这些新版本已全部构建通过。
本次独立 DFM 临时包重建的原因、固定输入和验收边界见
[桌面插件故障与临时补丁报告](DDE-HOTFIX-20261127.md)。

### 安装后默认保留 COPR

从 45.20261127.1 起，配方将 Fedora DDE Remix 的源文件与已核验公钥纳入
`fedora-dde-remix-config` RPM。标准 COPR 仓库 ID 保持为
`copr:copr.fedorainfracloud.org:mozixun:Fedora-DDE-Remix`，默认启用，并保留
`gpgcheck=1` 和 `sslverify=1`。地址使用 `$releasever`、`$basearch`；安装目标
移除 Live 安装器时不会移除配置 RPM。构建检查实际 payload 的配置和 RPM 归属，
Live 与硬盘启动测试再用 DNF 检查源确实处于启用状态。

### LUKS2 加密安装

新版配方包含 `cryptsetup` 和 Fedora 45 的 `systemd-udev`，后者提供
`/usr/bin/systemd-cryptsetup` 与解锁 generator，配合安装器 0.3.0 的加密入口。
ESP 与独立 `/boot` 保持明文；根和个人数据位于同一个 LUKS2 容器中，Btrfs 使用
root/home 子卷，ext4/XFS 的 home 是根内目录。开机交互输入口令解锁。
加密模式暂不接受独立明文 home、var、其他数据挂载和磁盘 swap，保留默认 zram。
不支持复用已有 LUKS、分离头、多容器或 LVM。

口令使用匿名 sealed memfd 传递，crypttab 使用 `none` 密钥文件字段，目标系统
不存放自动解锁密钥。小盘检查额外扣除 32 MiB 加密头，再应用原有 12 GiB 内层根
下限和 payload 实际占用。`.4` 的三个加密场景已有该镜像的真实安装与硬盘解锁
启动报告；每次构建仍先运行 16 GB 加密 Btrfs 场景，成功后才运行其余八组。

### 默认壁纸与 Remix 标识

45.20261127.2 使用 `desktop-backgrounds-basic` 提供的 JPEG 壁纸和
`fedora-remix-logos` 的 Remix 标识。配置 RPM 管理 Treeland、appearance DConfig、
GSettings 的默认路径以及 DSysInfo 的 `distribution.info`；镜像检查会读取实际文件、
RPM 所有者及编译后的 GSettings 默认值，VM 在真实登录后继续核对用户的有效 DConfig。
新默认值不重置已有用户的自选壁纸。

系统通用图形资源由 `generic-logos` 提供。维护者的 `deepin-desktop-base` 当前硬性
依赖主 Fedora 标识包，因此本仓库仅对固定 `2026.10.28-1` SPEC 的依赖和 Release
做临时调整：依赖改为 `system-logos`，版本为 `2026.10.28-1.1.remix1.fc45`。
源码和其余打包行为保持一致；配方先安装这个 noarch 包，再定向替换系统图形资源，
验证没有移除其他桌面包。来源、原 SPEC、临时 SPEC、源码归档及 SRPM 随构建证据保留，
详见[临时依赖调整](packaging/hotfix/deepin-desktop-base/README.md)。

45.20261127.3 还临时重建 `deepin-desktop-schemas-6.0.13-1.1.remix1.fc45`：修复
mediakey `away` 键的重复元素，在真实 RPM `%check` 中严格编译全部 schema 和 Go
生成的 override，并将该包自己的背景默认值也改为现存 JPEG。维护者后续的
`6.0.13-2.fc45` 可以正常替代这个临时版本。镜像和 VM 会读取实际编译缓存，确认
该快捷键 schema 存在并保留原默认值；详见[schemas 临时修复](packaging/hotfix/deepin-desktop-schemas/README.md)。

## Live 登录与 PAM

本版使用 **手动登录**：

| 项目 | 值 |
| --- | --- |
| 用户名 | `liveuser` |
| 密码 | `liveuser` |
| 桌面安装入口 | 应用菜单或桌面的 Fedora DDE Remix Installer |

Live 用户只在带 `rd.live.image` 的启动过程中创建，位于临时可写层，原始只读
payload 不包含这个账户。安装目标使用安装器创建的新账户。

维护者的 DDM `0.5.0-8` 已提供 Fedora 原生 `password-auth` / `postlogin`
配置及 SELinux 会话处理，本仓库不再提供 `/etc/pam.d/system-login` 兼容文件。
构建时核对实际 RPM 中的 PAM 配置，并用实际 PAM 库检查正确密码、错误密码、
未知账户和过期账户。虚拟机检查还必须验证真实的 DDM 登录和桌面会话。

## 构建与产物

推送配方到 `main` 或运行 **Actions → Build Fedora DDE Live ISO → Run workflow**。
工作流在 GitHub hosted 临时 Ubuntu VM 中启动特权 Fedora 45 容器，使用
`livemedia-creator --make-iso --no-virt` 构建 BIOS / UEFI hybrid ISO。
Anaconda 采用目录安装到新创建的临时文件系统镜像，配方不指定物理安装磁盘。

产物包含带日期版本的 ISO、SHA-256 校验文件、包清单、输入提交和构建日志。
ISO 与安装验证证据保留 90 天，构建日志及 RPM 保留 30 天。
实际产物以 Actions 状态为准，提交配方或生成 RPM 不等于 ISO 已经构建成功。

### 虚拟机安装验证

compose 成功后自动调用 **Test ISO installation**。测试下载同一份 ISO 并校验
SHA-256，使用 OVMF UEFI 或 SeaBIOS、独立 sparse qcow2、QEMU 的本地 UNIX 控制接口。
运行前探测 KVM，报告实际使用的加速方式；测试不会传入宿主物理磁盘。

1. 从 ISO 自带 GRUB 启动，只在该次启动中追加串口控制台参数。
2. 正常登录 Live，检查 Enforcing 和真实 DDM 桌面会话。
3. 调用 ISO 内安装器的完整后端流程，实际分区、复制、配置用户、部署引导并完成安装。
4. 关机并移除 ISO，从同一个虚拟硬盘启动。
5. 验证普通用户、wheel 权限、锁定的 root、Live 账户清理、可写根目录和 Enforcing。
6. 新用户经 DDM 输入密码后，要求同一次启动内没有新增的目标用户 `dde-shell`
   崩溃记录，并检查会话及非黑画面持续存在至少 8 秒。保存截图供人工核验；
   仅有 Treeland / DDE Shell 进程不能证明桌面成功，非黑画面本身也不证明全部桌面功能正常。

`.4` 以下九组已完成真实安装、移除 ISO 后的磁盘启动和图形登录。每组实际使用
4 vCPU、8 GiB RAM 和 KVM；这是本轮测试资源，不是经过验证的最低内存要求。

| 场景 | 固件 | 文件系统与布局 | 虚拟磁盘 | `.4` 最终结果 |
| --- | --- | --- | --- | --- |
| `uefi-btrfs` | UEFI | 默认 Btrfs root/home 子卷、独立 `/boot`、ESP | 64 GiB | 通过 |
| `bios-ext4` | BIOS | ext4 根分区、独立 `/boot`、GPT BIOS boot 区 | 64 GiB | 通过 |
| `bios-mbr-ext4` | BIOS | MBR 分区表、ext4 根分区、独立 `/boot` | 64 GiB | 通过 |
| `uefi-xfs-home-swap` | UEFI | XFS 根分区、独立 `/home`、磁盘 swap、`/boot`、ESP | 64 GiB | 同镜像补测通过；原 host 失败保留 |
| `uefi-preserve` | UEFI | 保留已有 home、ESP 及验证文件，在剩余空间安装 | 64 GiB | 通过 |
| `uefi-small` | UEFI | 默认 Btrfs 布局的小容量完整安装 | 16,000,000,000 B | 通过 |
| `uefi-luks-btrfs-small` | UEFI | LUKS2 内 Btrfs root/home，明文 `/boot` 和 ESP | 16,000,000,000 B | 通过 |
| `bios-luks-ext4` | BIOS | GPT、LUKS2 内 ext4 根与 home，明文 `/boot` | 64 GiB | 通过 |
| `uefi-luks-xfs` | UEFI | LUKS2 内 XFS 根与 home，明文 `/boot` 和 ESP | 64 GiB | 通过 |

测试保存阶段日志、截图、ISO 校验值和 JSON 报告；失败仍上传诊断。
测试账户只在这次虚拟机安装中创建，不写入正式 ISO。自动检查的范围以实际
完成的报告为准；这九组调用真实安装器后端，`graphical_layout_planner_tested=false`，
没有宣称整个安装 GUI 已逐页点选。实体硬件、Secure Boot、aarch64、4Kn、多磁盘、
已有加密分区复用、实际 rescue 启动和内核升级后启动不在这组已通过范围内。
保留 home/ESP 验证了 UUID、PARTUUID、起止扇区与 marker 文件内容，未对原有
UID/GID、mode、ACL、xattrs 作完整前后比较。

加密场景在重启前检查错误口令被拒绝、正确口令可用，检查 crypttab 不含密钥文件、
指定目标配置和日志不含测试口令、完成后正常关闭 mapper；随后移除 ISO，实际
initramfs 提示输入口令并以正确口令启动。没有把重启前的负例检查写成启动界面
输入错误口令的测试。两组 16 GB 成功结果也不是所有未来 payload 的容量承诺，
安装前仍执行实际空间检查。

如需对同一镜像重试，在 **Test ISO installation → Run workflow** 填入构建
run ID 和完整 ISO artifact 名称；`scenario` 默认 `all`，也可选一组分区。
控制器改动不会自动触发重新 compose。
本次 `validate-iso4-20261127` 专用的临时 push 补测入口已停用；常规测试入口仅保留
带明确 ISO 输入的 workflow_call / workflow_dispatch。

诊断选项 `continue-after-desktop-failure` 默认关闭。显式开启时，桌面失败仍被
记录，并允许继续收集独立的实际安装、分区和磁盘启动结果；任何桌面失败都会
令总结果失败，不能据此认定正式验收通过。正常 compose 后的自动验收保持严格模式。

`config/build.env` 固定安装器提交。工作流优先复用该提交已经通过完整构建和测试的
安装器 CI artifact，同时核对源提交和固定 ZIP SHA-256；这项只读下载不把 GitHub
令牌传入构建容器。若 artifact 已过期、不可访问或不适用于该提交，则从固定源码
重新构建并测试 RPM。Fedora 与 COPR 软件包仍取自
构建时启用的软件源，产物中的 RPM manifest 用来记录本次实际选择。

本地复现也应使用可丢弃的构建 VM。将本仓库挂载到 `/workspace:ro`，将固定
提交的安装器 checkout 挂载到 `/installer:ro`，提供独立 `/work` 与 `/output`
目录，在特权 `registry.fedoraproject.org/fedora:45` 容器中运行：

```bash
FEDORA_DDE_ISO_BUILD=1 bash /workspace/scripts/build.sh
```

## 维护范围

本仓库管理 ISO 配方、Live 会话与这一版的配置 RPM；安装器改动在安装器仓库维护。
DDE 桌面和 DDM 软件包由 `Deepin-Desktop-Environment` 的维护者负责。ISO 构建工作流
消费已发布的软件包及本文列出的固定临时重建，不自动修改维护仓库或触发 COPR。
另行提交的 SPEC 修复通过独立 PR 审阅，不由 ISO 工作流代替维护者合并与构建。

## 当前交付门槛

`.4` 的九组实际安装证据已完成并可审阅，仍作为独立候选保留。主分支合并及正式
Release 尚待相应批准；现有成功结果不代替合并、发布审阅，也不扩展为上面未测
平台、GUI 路径或维护者新增 SPEC 版本的验收。

## 参考

- [Lorax livemedia-creator](https://weldr.io/lorax/livemedia-creator.html)
- [Fedora 45 Lorax 源码](https://github.com/weldr/lorax/tree/f45-branch)
- [维护者桌面安装说明](https://github.com/Fedora-DDE-Remix/Deepin-Desktop-Environment)
- [Fedora DDE Remix 安装器](https://github.com/Fedora-DDE-Remix/fedora-dde-installer)
