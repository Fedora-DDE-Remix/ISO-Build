# Fedora DDE Remix ISO

此仓库构建 **Fedora 45 / x86_64 的传统可写系统 Live ISO**。安装器采用
`Fedora-DDE-Remix/fedora-dde-installer`，在当前 Live 会话内完成安装、用户、
密码、时区和键盘配置，由用户决定何时重启。

**45.20261127 已生成 ISO，但桌面验收失败，尚未作为正式 Release 发布。**
严格实测捕获了 DDE 桌面插件的 SIGSEGV 和黑屏；安装、分区和硬盘启动的独立结果见
[本版验证报告](VALIDATION-45.20261127.md)。

**45.20261127 版保持 SELinux Enforcing**：Live 和安装目标使用 Fedora 原生 PAM，
系统配置为 `SELINUX=enforcing`。Live 启动参数显式包含 `selinux=1 enforcing=1`；
安装器为目标系统生成正常磁盘引导参数，使用 Fedora 默认的 Enforcing 行为。
镜像使用维护者发布的 DDM 和 DDE SELinux 策略包，构建时验证策略注册和文件标签。
正式交付还需要通过下面的实际虚拟机安装检查；仅生成 ISO 不代表安装验证通过。

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
本工作流不写入 COPR，也不构建或修改 `Deepin-Desktop-Environment` 仓库。

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

测试覆盖以下组合，所有场景都必须安装后移除 ISO 并从磁盘启动：

| 场景 | 固件 | 文件系统与布局 | 虚拟磁盘 |
| --- | --- | --- | --- |
| `uefi-btrfs` | UEFI | 默认 Btrfs root/home 子卷、独立 `/boot`、ESP | 64 GiB |
| `bios-ext4` | BIOS | ext4 根分区、独立 `/boot`、GPT BIOS boot 区 | 64 GiB |
| `bios-mbr-ext4` | BIOS | MBR 分区表、ext4 根分区、独立 `/boot` | 64 GiB |
| `uefi-xfs-home-swap` | UEFI | XFS 根分区、独立 `/home`、磁盘 swap、`/boot`、ESP | 64 GiB |
| `uefi-preserve` | UEFI | 保留已有分区及验证文件，在剩余空间安装 | 64 GiB |
| `uefi-small` | UEFI | 默认 Btrfs 布局的小容量完整安装 | 16 GB（十进制） |

测试保存阶段日志、截图、ISO 校验值和 JSON 报告；失败仍上传诊断。
测试账户只在这次虚拟机安装中创建，不写入正式 ISO。自动检查的范围以实际
完成的报告为准；实体硬件、Secure Boot、多磁盘与加密安装不在这组测试范围内。

如需对同一镜像重试，在 **Test ISO installation → Run workflow** 填入构建
run ID 和完整 ISO artifact 名称；`scenario` 默认 `all`，也可选一组分区。
控制器改动不会自动触发重新 compose。

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
DDE 桌面和 DDM 软件包由 `Deepin-Desktop-Environment` 的维护者负责。本仓库消费其
已发布的软件包，不修改或触发该仓库的构建。

## 参考

- [Lorax livemedia-creator](https://weldr.io/lorax/livemedia-creator.html)
- [Fedora 45 Lorax 源码](https://github.com/weldr/lorax/tree/f45-branch)
- [维护者桌面安装说明](https://github.com/Fedora-DDE-Remix/Deepin-Desktop-Environment)
- [Fedora DDE Remix 安装器](https://github.com/Fedora-DDE-Remix/fedora-dde-installer)
