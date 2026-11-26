# 45.20261127 构建与安装验证

## 当前结论

ISO 已实际构建并上传。正式桌面验收仍受阻；不得仅凭 compose 成功、
安装后端成功，或旧测试控制器返回 `passed` 将它标记为可发布的正式桌面版本。
已发现 DDE 桌面插件在创建窗口时崩溃，相关证据与存储测试结果分别记录如下。

这是一次实际 QEMU 安装验证，使用普通账户经 PAM 登录及 sudo，调用 ISO 内的
C++ 分区执行器和完整安装后端。测试结束时关机、移除 ISO，再从同一虚拟硬盘启动。
它没有逐页点击安装器的整个图形向导；图形分区布局逻辑另有安装器 CI 测试。

## ISO 与输入

| 项目 | 值 |
| --- | --- |
| 版本 | Fedora DDE Remix 45.20261127 / x86_64 |
| 类型 | 传统可写 RPM / DNF 系统 |
| 文件 | `Fedora-DDE-Remix-45.20261127-x86_64.iso` |
| ISO 字节数 | 3,460,098,048 |
| ISO SHA-256 | `a03fcdf1ea2473236e88d0752e128fb14e19460c8bb26b8a3c02e0790f2df9dd` |
| ISO 配方提交 | `3bb0254f37940cadc46f92c0335b81c7cca33e3f` |
| 安装器提交 | `e10bf53ad51e0dea7cc5133052a0d8e0dc6bcce9` |
| 安装器 RPM | `fedora-dde-installer-0.2.2-0.1.fc45.x86_64` |
| comps 输入 | `dde-desktop-comps-6.2.1-5.fc45.noarch` |
| 桌面来源 | `mozixun/Fedora-DDE-Remix` 正式 COPR 仓库 |
| SELinux | Enforcing |

[ISO 构建 run 45863633374](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45863633374)
中的 compose job `140060766149` 成功。
[ISO 下载 artifact 15141121124](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45863633374/artifacts/15141121124)
名为 `Fedora-DDE-Remix-45.20261127-x86_64-10`。
这是 Actions 产物，不是已经通过桌面验收的正式 Release。

下载的 artifact 是 ZIP 容器，其 SHA-256 为
`cf1568d9f4623adf104c5b0468d1af410638c0974f5cf9f26e2b6682ee2cb235`；
它与上面的原始 ISO SHA-256 不同。
同一 run 的 `ISO-build-logs-and-RPMs-10` 保存输入、包清单、配置 RPM 和构建检查。

构建从最终 ISO 提取只读 payload，检查 RPM 数据库和关键文件，而不只检查配方：

- `dde-desktop` 的 69 个 mandatory 包全部安装，先安装 comps，再独立安装桌面组。
- Fedora 原生 PAM 配置、SELinux 策略注册和关键文件标签检查通过。
- 只读 payload 不含 Live 账户；Live 账户仅在临时可写层中创建。
- DDM 的 `kmsconvt@tty1.service` 冲突声明实际存在，并由
  `fedora-dde-remix-config-45.20261127-1.fc45.noarch` 所有。

## 容量要求

安装器不再使用原来的 32 GiB 设备过滤、50 GiB 磁盘要求和 32 GiB 根分区下限。
当前设备初筛为 **14 GiB**，根分区下限为 **12 GiB**。
14 GiB 约为 15.03 GB；不能把这个值解释成“任意 14 GB 磁盘均可安装”。

实际能否安装还取决于 ESP、独立 `/boot`、保留分区及镜像占用。
后端在破坏性分区前扫描只读 payload，按文件系统分配及保留余量核算空间；
分区前再次校验，复制前再检查目标文件系统的实际可用空间。
Btrfs root/home 共用空间合并计算，保留分区以只读且不回放日志的方式探测。

已完成的精确 **16,000,000,000 字节**磁盘实测采用：

| 分区 | 大小 / 布局 |
| --- | --- |
| ESP | 600 MiB，FAT32 |
| `/boot` | 2 GiB，ext4 |
| 根文件系统 | 13,221,273,600 字节，约 12.31 GiB，Btrfs |
| `/` 与 `/home` | 同一个 Btrfs 文件系统中的 `root` / `home` 子卷 |

新版 ISO 的这组测试已完成安装、配置、移除 ISO 后启动和 Enforcing 检查。
磁盘启动后 `lsblk -f` 显示 Btrfs `8.5G` 可用、`/boot` `1.3G` 可用；
这是命令的近似容量显示，两个 Btrfs 子卷的可用值不可相加。
旧版 ISO 使用同一安装器的独立基线测试也完成了这块精确 16 GB 磁盘的安装与启动。

## 存储与启动矩阵

### 新 ISO 的六组终态

[完整复测 run 45869225309](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45869225309)
实际使用上表同一 SHA-256 的 **45.20261127 ISO**，六组均已结束。
除 `uefi-small` 为精确十进制 16 GB 外，其余磁盘为 64 GiB。
下表结论来自各组实际报告、安装后检查、截图和 core 的联合审计。

| 场景 | 布局 | 安装后端 / 移除 ISO 后启动 | 桌面实际结果 | 证据 artifact |
| --- | --- | --- | --- | --- |
| `uefi-btrfs` | UEFI / GPT，Btrfs root/home，独立 boot/ESP | 均通过 | 黑屏、SIGSEGV | [15143629755](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45869225309/artifacts/15143629755) |
| `bios-ext4` | BIOS / GPT，2 MiB BIOS boot 区，ext4 boot/root | 均通过 | 黑屏、SIGSEGV | [15146126199](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45869225309/artifacts/15146126199) |
| `bios-mbr-ext4` | BIOS / MBR，ext4 boot/root | 均通过 | 黑屏、SIGSEGV | [15145940382](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45869225309/artifacts/15145940382) |
| `uefi-xfs-home-swap` | UEFI，32 GiB XFS root、ext4 home、2 GiB swap | 均通过 | 黑屏、SIGSEGV | [15144319702](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45869225309/artifacts/15144319702) |
| `uefi-preserve` | UEFI，保留 ESP 与 ext4 home，在剩余空间安装 | 均通过 | 黑屏、SIGSEGV | [15144769553](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45869225309/artifacts/15144769553) |
| `uefi-small` | 精确 16 GB，UEFI 默认 Btrfs 布局 | 均通过 | 黑屏、SIGSEGV | [15143769737](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45869225309/artifacts/15143769737) |

每组都真实执行了 `preflight → partition → copy → system → ready → configure → finalize`。
`configure` 在复制完成后的同一 Live 会话执行，创建用户、密码、时区和键盘配置；
不依靠第一次重启才能进入账户配置。
新版六组安装后均核验普通 UID 1000 账户、wheel、锁定 root、Live 账户不存在、
可写根目录、SELinux Enforcing，以及 DDM PAM 正确密码成功与错误密码失败。
所有场景最后正常关机。
Btrfs 的 root/home 子卷与 `compress=zstd:1` 挂载参数正确。
XFS 组合的磁盘 swap 和 zram 均激活，resume UUID 与磁盘 swap 一致。
保留分区组合的 ESP、home 在安装及重启前后的 FS UUID、PARTUUID、起止扇区和验证文件哈希逐项相同。

这次完整矩阵的控制器为 `14d60c9f0f837b4573e33444cb611dfbf7f981c7`。
它修正了主机 OCR 超时与启动控制台文字误识别，桌面门禁却仍只检查活动 DDM Wayland
会话和进程，未检测主桌面插件崩溃与黑屏。因此六个 job 的绿色状态是**桌面判断的假阳性**；
上表保留独立成立的存储结果，同时纠正桌面结论。后续严格控制器已经补上这项缺口。

### 严格桌面复测

[严格桌面复测 run 45874836926](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45874836926)
使用同一新 ISO，控制器 `548e2f71b70c287772c89af8efe9475f3d088737`，
选择 `uefi-small` 且关闭“桌面失败后继续”的诊断选项。
严格复测已在 Live 图形登录阶段失败，尚未执行分区。18:27:11 UTC，
`/usr/bin/dde-shell -p org.deepin.ds.desktop`（PID 1904、UID 1000）发生 SIGSEGV。
控制器正确识别为本次启动、登录开始后的目标用户崩溃，18:27:38 判定失败。
18:26:23 至 18:27:32 的 11 张连续画面均为纯黑，最后截图也为黑屏。

[严格复测证据 artifact 15144778386](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45874836926/artifacts/15144778386)
包含完整 `coredumpctl info`、用户日志、截图和报告，ZIP SHA-256：
`b215d50e93a5462d3d7b2379eea9e74c484848ddf2b7cf085dc8f5f8173aaf6a`。

### 较早的基线

[诊断 run 45862956170](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45862956170)
使用 45.20261126 ISO 和同一安装器提交，开启了桌面失败后继续采集的诊断模式。
旧版六组同样完成了安装和磁盘启动；其图形结果不用于替代新版验收。
旧 XFS 组图形失败后未进入安装后 PAM 检查，其他五组完成该检查。

## 桌面阻塞证据

新版六组安装后系统均出现：

1. DDM 接受正确密码，并创建活动 Wayland 用户会话。
2. Treeland 及部分 `dde-shell` 进程存在。
3. 桌面插件 `dde-shell-plugin@org.deepin.ds.desktop.service` 崩溃或反复启动失败。
4. 实际截图为黑屏。

新版严格复测保存的 2026-11-26 18:27:11 UTC core 栈为：

```text
PID 1904, UID 1000, SIGSEGV
/usr/bin/dde-shell -p org.deepin.ds.desktop
#0 ddplugin_core::WindowFrame::buildBaseWindow()
   libdd-core-plugin.so + 0x5d2cb
#1 Qt signal activation
#2 dpf::PluginManagerPrivate::startPlugins()
#3 dpf::LifeCycle::loadPlugins()
#4 desktop::pluginsLoad()
```

内核同时记录 `segfault at 0`。旧版 BIOS / GPT 的完整调用栈和其余多组崩溃
出现相同函数及模块偏移；新版六组安装后也均有实际 `dde-shell` SIGSEGV 记录。
`libdd-core-plugin.so` 属于 `dde-file-manager-desktop-6.6.7-9.fc45`，
ISO 同时安装 `dde-shell-6.2.1-4.fc45` 和 `treeland-0.12.0-10.fc45`。
上述旧版安装后 SIGSEGV 样本的 AVC 输出为空。
新版严格复测记录了 `kmscon_t` 对 `tmpfs_t` 文件系统 `getattr` 的 SELinux 拒绝；
它与桌面插件的 SIGSEGV 分别记录，不能据此声称整个系统没有 AVC，
也不能将这次桌面空指针崩溃直接归因于 SELinux。Enforcing 始终保持开启。

可复核的上游调用位置：
[6.6.7 windowframe.cpp](https://github.com/linuxdeepin/dde-file-manager/blob/bdd0f409316054d136eeb8eb7a132a977e4915f7/src/plugins/desktop/ddplugin-core/frame/windowframe.cpp)。
源码的多屏分支有未检查空值的 `primary->name()`。
新版严格复测中，重启后的同一桌面插件 PID 2299 在 18:27:44.975 UTC 记录
`Display mode: 0 screen count: 0`，紧接着记录 `Configuring multiple screens`，
然后内核记录 `segfault at 0`、相同模块偏移 `0x5d2cb`。
因此本次确实发生了“零屏进入多屏分支”的失败路径。
为何查询得到空列表仍须进一步处理。日志明确包含五个 `ddplugin_core`
`signal_DesktopFrame_*` 和多个 `ddplugin_canvas` slot 的 invalid 警告，
但未直接记录 `slot_ScreenProxy_*` 无效。
固定源码的 [事件查询](https://github.com/linuxdeepin/dde-file-manager/blob/bdd0f409316054d136eeb8eb7a132a977e4915f7/include/dfm-framework/event/eventchannel.h)
在没有有效 channel 时返回空 QVariant，
[屏幕查询封装](https://github.com/linuxdeepin/dde-file-manager/blob/bdd0f409316054d136eeb8eb7a132a977e4915f7/src/plugins/desktop/desktoputils/ddplugin_eventinterface_helper.h)
会将它变成空列表、模式 0 和空主屏指针。
因此这条“0 屏”日志不等于已经证明真实 Wayland 没有 outputs；
本次未采集屏幕查询 slot ID、返回 QVariant 的有效性和直接 Qt 屏幕列表。

注册宏定义在 [core.h](https://github.com/linuxdeepin/dde-file-manager/blob/bdd0f409316054d136eeb8eb7a132a977e4915f7/src/plugins/desktop/ddplugin-core/core.h)，
随插件编译，并在实例构造时注册；没有发现需要 ISO 补装的独立事件注册文件。
用户 Desktop 目录的 watcher 在日志中成功初始化，当前证据也不支持缺少该目录的解释。
只加空值判断可以防护这一崩溃路径，不能单独证明桌面恢复。

严格控制器增加了本次启动、目标 UID 和登录开始时刻之后的 `dde-shell` core 检查，
以及至少 8 秒的非黑画面观察；任意新增崩溃立即失败，不能靠其他存活的 shell 插件掩盖。
诊断优先保存目标用户最新 core 的文本信息及过滤后的用户日志，不导出原始 core 内存。
非黑画面指标只是自动排除黑屏的必要条件；仍须查看截图并验证实际桌面交互。

## 范围与后续验收

实际 VM 使用 4 vCPU、8 GiB RAM，KVM 启动被宿主拒绝后按既定规则改用 TCG。
分区几何的 512 / 4096 字节逻辑扇区有安装器 CI 覆盖；上述真实 VM 磁盘均为 512 字节扇区。
没有进行实体硬件、Secure Boot、多磁盘或加密安装的实测。

需要桌面包维护者处理已复现的桌面插件问题，再使用修复后的包构建新 ISO，
并完成 Live 桌面、安装和硬盘启动后的桌面验收。
此次工作只修改 ISO-Build 与安装器仓库；`Deepin-Desktop-Environment` 仓库保持只读。
