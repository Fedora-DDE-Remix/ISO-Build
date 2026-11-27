# 45.20261127.1 候选 ISO：构建与安装验收

## 当前结论

候选 ISO 已实际合成并上传，最终镜像检查通过。首个 VM 在 Live 图形登录阶段失败，
尚未执行分区或加密安装，其余八个场景因此跳过。本候选未通过桌面与安装验收，
不能发布为正式 Release。后续 `45.20261127.2` 将修正登录自动化和独立发现的资源缺失。

这份报告只记录本候选的新证据。旧版 `45.20261127` 的存储测试通过、桌面黑屏
失败仍保留在[原报告](VALIDATION-45.20261127.md)，不用于替代本候选的测试。

## 镜像及固定输入

| 项目 | 身份 / 结果 |
| --- | --- |
| 系统 | Fedora 45，x86_64，传统可写 RPM / DNF 系统 |
| 文件 | `Fedora-DDE-Remix-45.20261127.1-x86_64.iso` |
| 原始 ISO 字节数 | 3,460,298,752 |
| 原始 ISO SHA-256 | `15a126e1e557d65135a75831aca076f82d5d89a0d1f163d332c4a8b4e340e237` |
| ISO 配方提交 | `981b25ae62368599564cf424bbe0185f22dcf89f` |
| 安装器提交 | `b5816732394a20188593b2918ebdddbc169e68dc` |
| 安装器 RPM | `fedora-dde-installer-0.3.0-0.2.fc45.x86_64` |
| comps 输入 | `dde-desktop-comps-6.2.1-5.fc45.noarch` |
| DFM 四个运行包 | `6.6.7-9.1.remix1.fc45`，固定临时补丁 |
| 安全配置 | SELinux Enforcing，Fedora 原生 PAM |
| compose | [run 45964408039](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45964408039)，job `140389533073` 成功 |

[ISO 下载 artifact 15184016036](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45964408039/artifacts/15184016036)
名为 `Fedora-DDE-Remix-45.20261127.1-x86_64-14`，ZIP 大小为 3,460,350,138 字节，
ZIP SHA-256 为 `090d1da84e8f6deb055793642f980b01ada9c899a549d675e0ae6d76d23a35fa`。
**ZIP 校验值与其中原始 ISO 的校验值不同。** 此处原始 ISO 校验值来自封存构建日志
中的校验行，并与 VM 证据中保留的实际 CHECKSUM 相符；VM 工作流已下载精确 artifact
并通过 CHECKSUM 核验，再启动这份 ISO。安装阶段未执行，不声称完成全部安装后的校验。
对话执行环境的下载连接器限制单个 artifact 为 512 MiB，没有在该环境独立下载整份 ISO。

[构建日志与 RPM 输入 artifact 15183312192](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45964408039/artifacts/15183312192)
名为 `ISO-build-logs-and-RPMs-14`，ZIP SHA-256 为
`d0a5f3ca9200a3cdcab05e77e1eea534517ffb0ba81ecc36b43aceb113aedf87`。

## 已完成的构建检查

构建检查从最终 ISO 提取实际 SquashFS、RPM 数据库和关键文件，不只读取配方。

- 1210 个包名，`dde-desktop` 的 69 个 mandatory 包全部安装；先安装维护者 comps RPM，
  再执行 `dnf group install dde-desktop`。
- 四个 DFM 运行包的实际版本和记录的 RPM 来源一致；安装器为上述固定 `0.3.0-0.2`。
- COPR repo、公钥和检查程序由 `fedora-dde-remix-config` 管理；仓库默认启用，
  `gpgcheck=1`、`sslverify=1`，公钥内容与固定输入相符。
- Fedora SELinux 策略及四个 DDE 策略模块注册，关键系统/DDM 文件和持久挂载点的标签正确。
- DDM 与 DDM autologin 使用 Fedora PAM；构建阶段的正确密码、错误密码、未知用户和过期账户检查通过。
- 加密解锁程序和 generator 实际存在、可执行，并由 Fedora `systemd-udev` 提供。
- 最终只读 payload 不含烘焙进去的 Live 账户；Live 账户在启动后的临时可写层创建。
- DDM 对 `kmsconvt@tty1.service` 的冲突声明存在，并由配置 RPM 所有。

安装器的[完整 Fedora 45 构建](https://github.com/Fedora-DDE-Remix/fedora-dde-installer/actions/runs/45962759570)
已完成 Qt/DTK 编译、二进制 RPM/SRPM、三个 CTest 套件和原生 RPM 安装检查。
本地后端测试为 142 项通过。新的原生安装门禁实际安装本次 RPM，并检查
`/usr/bin/systemd-cryptsetup`、generator 的可执行性、RPM 所有者及 `--help`。

## 安装后默认 COPR

安装系统应保留标准 COPR 配置文件：

```text
/etc/yum.repos.d/_copr:copr.fedorainfracloud.org:mozixun:Fedora-DDE-Remix.repo
```

仓库 ID 为 `copr:copr.fedorainfracloud.org:mozixun:Fedora-DDE-Remix`，baseurl 使用
`fedora-$releasever-$basearch/`。公钥由配置包安装到 `/etc/pki/rpm-gpg/`，
使用 `file://` 引用，签名和 TLS 校验保留开启。

真实 VM 的 Live 与安装系统都要运行 `/usr/libexec/fedora-dde-check-copr`，
并通过 `dnf --cacheonly repo list --enabled --json` 验证精确仓库 ID 恰好出现一次。
本候选已在 Live VM 中验证这些项目；安装后尚未执行，不能仅凭构建检查替代。

## 加密安装及容量边界

本版支持新建一个 **LUKS2 / Argon2id** 容器，内部为 Btrfs、ext4 或 XFS。
ESP 和独立 ext4 `/boot` 保持未加密；Btrfs 的根目录和 home 子卷位于同一个
加密文件系统，ext4/XFS 的 home 位于加密根目录中。

本版不支持复用已有 LUKS、分离头、多加密容器或 LVM。在加密模式下，
独立明文 home/data/var 和磁盘 swap 会在分区前被拒绝。
密码经密封内存文件描述符传递，不放入安装 JSON、命令行或目标系统密钥文件。
crypttab 使用 `none`，从硬盘启动时需要输入密码。

设备初筛为 **14 GiB**，根文件系统下限为 **12 GiB**，加密根另预留 **32 MiB**
LUKS 头空间。后端还按实际 payload、文件系统分配和余量检查容量，不能把初筛值
理解为所有布局在同等总容量的物理磁盘上都可安装。

两组小盘测试使用精确 **16,000,000,000 字节**，不是 16 GiB；其中加密 Btrfs
作为首个 canary。只有其实际安装与硬盘启动成功，才能声明本 ISO 在该布局上的
16 GB 实测结果，不对未来体积变化的镜像作固定容量承诺。

## 真实 VM 安装矩阵

所有场景使用同一 ISO、x86_64、单块 VirtIO 磁盘、512 字节逻辑扇区。
UEFI 使用 OVMF、未启用 Secure Boot；BIOS 使用 SeaBIOS。
各场景具有独立 2 GiB ext4 `/boot`，UEFI 场景具有 600 MiB FAT32 ESP。

| 场景 | 固件 / 分区表 | 磁盘容量 | 根 / home / swap | 本候选结果 |
| --- | --- | --- | --- | --- |
| `uefi-luks-btrfs-small` | UEFI / GPT | 十进制 16 GB | LUKS2 内 Btrfs root/home 子卷 | Live 图形登录失败，未分区 |
| `uefi-btrfs` | UEFI / GPT | 64 GiB | Btrfs root/home 子卷 | 跳过 |
| `bios-ext4` | BIOS / GPT | 64 GiB | ext4 根，home 在根目录内，2 MiB BIOS boot 区 | 跳过 |
| `bios-mbr-ext4` | BIOS / MBR | 64 GiB | ext4 根，home 在根目录内 | 跳过 |
| `uefi-xfs-home-swap` | UEFI / GPT | 64 GiB | 32 GiB XFS 根、独立 ext4 home、2 GiB swap | 跳过 |
| `uefi-preserve` | UEFI / GPT | 64 GiB | 新建 Btrfs 根，保留 ext4 home 和 ESP | 跳过 |
| `uefi-small` | UEFI / GPT | 十进制 16 GB | Btrfs root/home 子卷 | 跳过 |
| `bios-luks-ext4` | BIOS / GPT | 64 GiB | LUKS2 内 ext4 根，home 在根目录内 | 跳过 |
| `uefi-luks-xfs` | UEFI / GPT | 64 GiB | LUKS2 内 XFS 根，home 在根目录内 | 跳过 |

### 本轮 canary 的实际结果

证据为 [artifact 15184540664](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45964408039/artifacts/15184540664)，
ZIP SHA-256 为 `ddc8fe0b9a01a2fb6b15477c1d4e64b68de329332a40d3869aa22a416471f0e2`。
包内保存真实 CHECKSUM、精确 ISO 来源、报告、串口输出、日志和截图。

固件/ISO 启动、普通用户串口登录及 sudo、Live Enforcing、默认 COPR 和四个临时
DFM 包身份均已通过。宿主 KVM 探针通过，但实际 QEMU 启动因权限失败而自动使用
TCG；这是已有的真实软件模拟回退，并非跳过虚拟机。

图形登录阶段在 420 秒截止时仍没有 DDM 用户会话，`dde_shell=[]`，也没有同类
shell coredump。末次串口命令受剩余截止时间截断，最终异常是等待完成标记超时；
它是该阶段耗尽时间时的症状，不能据此认定串口传输或加密后端故障。

两张关键截图均停留在 Live User 登录页，结束时密码框为空。控制器把 OCR 识别的
“Please enter password”说明文字当作输入控件点击；固定 Treeland 0.12.0 的
`UserInput.qml` 显示这段文字实际位于密码框下方。这是已确认的测试输入定位缺陷，
应改为真实输入区定位并在提交前验证可见的掩码输入。
本轮 `installation_checks_completed=false`，没有加密安装结果，也没有完整桌面恢复证据。

此外，最终 payload 的完整 110,228 行文件清单确认没有默认壁纸文件。Treeland、
appearance DConfig 与旧 GSettings 指向的背景路径均缺失，实际 wallpaper factory
再次记录 `deepin-default.jpg` 读取失败。它独立于 DPF 回调问题，需要在下一候选
的 RPM 依赖和发行配置中修复。缺失的 `distribution.info` 也使 Logo 落入无效的
`file::/dsg/logo.svg` 回退。维护者仓库保持只读。

### 每组的验收过程

测试真实启动 ISO，经 DDM 密码登录、检查桌面，再调用 ISO 内的 C++ 分区执行器和
安装后端，依次执行 `preflight → partition → copy → system → ready → configure → finalize`。
用户、密码、时区和键盘配置在复制完成后的**同一次 Live 启动**内完成。
随后关机、移除 ISO，从同一虚拟硬盘启动，核对实际挂载、账户、PAM、COPR 和 Enforcing，
再次进行图形登录及桌面检查。

加密场景还需核验：LUKS2、单个 Argon2id 密钥槽、内部文件系统 UUID、无 keyfile 的
crypttab、正确内核参数、完成后卸载与关闭本安装器创建的 mapper；在 Live 的目标系统
阶段使用 `cryptsetup --test-passphrase` 验证错误密码拒绝、正确密码接受；硬盘启动时
观察真实 initramfs 密码提示并输入正确密码，之后实际登录安装系统。
错误密码负测不是在启动提示处进行，两项证据分别记录。

保留场景比较 ESP/home 的几何、FS UUID、PARTUUID 和随机验证文件的哈希；
swap 场景比较启动后的活动 swap UUID；Btrfs 场景核对子卷和压缩挂载参数。

### 图形结果的判定边界

自动门禁要求活动 DDM Wayland 用户会话、Treeland/dde-shell 进程、无当前登录后的
同类 dde-shell coredump，并持续出现非黑画面。还需要逐组检查实际 Live 与安装后
截图，不能把壁纸、面板或非黑像素单独当作完整桌面功能正常的证明。

这些是**后端驱动的真实安装与图形登录测试**，不是逐页点击整个安装器 GUI。
报告明确记录 `graphical_layout_planner_tested=false`。
没有覆盖所有固件×文件系统×加密组合，也未验证 Secure Boot、aarch64、物理 4Kn、
多磁盘及真实 NVMe 硬件。不能将九个场景表述为所有分区方式均已测试。

## DDE 黑屏临时补丁

详见[定位与补丁报告](DDE-HOTFIX-20261127.md)。原包的嵌套 Qt 插件加载会让事件
转换器回调在不同共享库中形成不同实例，导致事件已注册但内层转换失败；桌面代码
随后取得空屏幕对象并在 `WindowFrame::buildBaseWindow()` 崩溃。

临时补丁将头文件中的内联可变回调改成由 framework 统一定义，重建所有相关 DFM
子包；保留原规格的编译参数、依赖和 SELinux 设置。真实原包/候选 A/B 探针通过，
完整 RPM 在新 Fedora 容器中通过安装、ELF、重定位及嵌套 Qt 探针验证。
实际桌面恢复仍以本候选 VM 日志和截图为准。

临时包位于 ISO-Build 的独立分支，没有修改专人维护的
`Fedora-DDE-Remix/Deepin-Desktop-Environment`，也没有向 COPR 发布。
版本 `6.6.7-9.1.remix1.fc45` 不加入 versionlock，后续维护者发布更高版本时仍可正常升级。

## 发布状态

本候选与安装器均在独立分支和 draft PR 中：

- [ISO-Build PR #1](https://github.com/Fedora-DDE-Remix/ISO-Build/pull/1)
- [fedora-dde-installer PR #1](https://github.com/Fedora-DDE-Remix/fedora-dde-installer/pull/1)

默认分支及维护仓库保持原状态。这份报告针对候选 Actions 产物；合并和正式 Release
须在测试结论可审阅后另行确认，不能仅凭 compose 成功当作已经发布。
