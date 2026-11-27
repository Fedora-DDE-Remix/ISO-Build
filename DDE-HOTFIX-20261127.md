# DDE 桌面插件黑屏：定位与临时补丁

## 当前结论

现有 `dde-file-manager 6.6.7-9.fc45` 的 DPF 事件转换回调在嵌套插件加载时出现
不同实例：事件本身已经注册，内层插件却读到空回调，无法把事件名称转换为编号。
这不是 RPM 编译失败，而是已编译库之间的运行时共享状态问题。

真实 Fedora 45 的原包探针已复现问题；将回调改为框架库中的单一定义后，真实
Qt A/B 探针通过。完整临时 RPM 也已编译完成，并在独立的全新 Fedora 容器中
通过整包安装、实际 ELF 检查及嵌套 Qt 探针。**实际桌面和安装 VM 仍待验收，
不能用容器内的探针结果代替桌面恢复证明。**

`45.20261127.1` 的首个 VM 未能完成图形密码输入，因此没有进入用户桌面或
安装阶段，不能用它确认或否定 DPF 修复。其实际镜像还暴露了独立的壁纸与标识
资源缺失，详见下文。`45.20261127.2` 的
[compose / VM 运行](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45974028174)
随后在原桌面 schemas 严格编译处失败，未生成 ISO、未运行 VM。当前
`45.20261127.3` 接入对应的最小源码修复；完整桌面结论仍须来自新 VM 的日志和截图。

## 固定输入和证据

| 输入 | 身份 |
| --- | --- |
| 维护仓库规格 | `Fedora-DDE-Remix/Deepin-Desktop-Environment`，`adcd681b0b9e68cacbf9daa33bede62a253a3315` |
| DFM upstream | `linuxdeepin/dde-file-manager`，`bdd0f409316054d136eeb8eb7a132a977e4915f7`（6.6.7） |
| 当前 DFM RPM | `6.6.7-9.fc45` |
| DDE Shell RPM | `6.2.1-4.fc45` |
| 真实探针工具链 | GCC `16.2.1-3.fc45`、Qt `6.11.2-3.fc45` |
| 原包探针 | [Actions 45941604585](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45941604585) |
| A/B 探针 | [Actions 45948782959](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45948782959) |
| A/B 代码 | [`60f5c89689cb1b3a08a2c3830122c6c6ea4b54ba`](https://github.com/Fedora-DDE-Remix/ISO-Build/commit/60f5c89689cb1b3a08a2c3830122c6c6ea4b54ba) |
| 完整 RPM 构建 | [Actions 45950112995](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45950112995)；编译和安装成功，随后旧符号判据误报，整个运行保留 failure |
| 完整 RPM 独立复验 | [Actions 45956698212](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45956698212)；success |
| 原 ISO 桌面失败证据 | [Actions 45874836926](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45874836926)、[原版报告](VALIDATION-45.20261127.md) |

上述诊断和临时构建位于 ISO-Build 的独立分支。追加授权仔细审查并提交桌面 SPEC
问题后，已有修复另提交至维护仓库的
[draft PR #1](https://github.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/pull/1)，
主分支保持未合并；没有向 COPR 发布、触发 COPR 构建或使用 COPR 私钥。

## 崩溃链条

原 ISO 中，`dde-shell -p org.deepin.ds.desktop` 通过 PAM 登录后加载 DFM 桌面插件，
在 `ddplugin_core::WindowFrame::buildBaseWindow()` 发生 SIGSEGV。日志显示该路径
得到的屏幕数为 0；这里的屏幕列表来自 DPF channel 查询，不能直接解释为 compositor
没有输出或 QGuiApplication 一定没有检测到屏幕。

源代码的多屏分支会访问 `primary->name()`，缺少空值检查。原 RPM 的反汇编确认
`libdd-core-plugin.so+0x5d2cb` 为该对象的虚函数调用读取，机器码与 VM fault bytes
一致。相关固定源码：

- [EventConverter 定义](https://github.com/linuxdeepin/dde-file-manager/blob/bdd0f409316054d136eeb8eb7a132a977e4915f7/include/dfm-framework/event/eventhelper.h)
- [事件注册表](https://github.com/linuxdeepin/dde-file-manager/blob/bdd0f409316054d136eeb8eb7a132a977e4915f7/src/dfm-framework/event/event.cpp)
- [窗口创建路径](https://github.com/linuxdeepin/dde-file-manager/blob/bdd0f409316054d136eeb8eb7a132a977e4915f7/src/plugins/desktop/ddplugin-core/frame/windowframe.cpp)

实际原包探针使用 Qt 的嵌套 `QPluginLoader`，模拟桌面宿主加载内部插件的关系。
外层成功初始化框架，内层则出现：

| 检查 | 原包基线 | 候选头文件 |
| --- | ---: | ---: |
| 直接查询注册表的事件编号 | 10002 | 10002 |
| 名称转换结果 | -1 | 10002 |
| 内层回调有效 | 否 | 是 |
| 外层与内层回调同址 | 否 | 是 |
| 整数 channel 返回 37 | 失败 | 通过 |
| 列表 channel 返回两个元素 | 失败 | 通过 |
| CTest 退出码 | 8 | 0 |

原包与原始探针的 ELF 在多个 `.so` 内均定义 `GLOBAL DEFAULT` 的 `convertFunc`。
候选探针只保留 `UND` 引用，实际执行时指向同一个框架对象。A/B 过程中没有更换
已安装框架库，其 SHA-256 前后相同。

这些证据表明，事件转换器失效能使通道返回无效数据，并与原崩溃的空屏幕对象路径
吻合。是否恢复完整桌面，仍必须在同样 Enforcing 环境中启动新包验证。单独添加空
指针保护不能恢复失效的事件通道，因此临时补丁先修复共享状态的归属。

## 完整 RPM 的验证记录

首次完整构建产出 10 个二进制 RPM（包括开发与调试包）及匹配 SRPM，五个实际
运行/开发包也成功安装。后续检查错误地要求顶层 `org.deepin.ds.desktop.so`
必须包含回调的 `UND` 引用，导致整个 Actions 运行显示失败。

对该 RPM 内实际 ELF 的检查，以及固定源码的 `panel-desktop/main.cpp` 调用关系，
确认顶层模块只调用 DPF LifeCycle 加载插件，并不直接使用回调。头文件改成声明后，
它无需保留无用的定义或引用。这次实际产物为：

| ELF 对象 | 回调符号 | 回调重定位 | framework 依赖 |
| --- | --- | --- | --- |
| `libdfm6-framework.so.1` | 一个 32 字节的 `OBJECT GLOBAL DEFAULT` 定义 | 有 | 本身就是 framework |
| `libdd-core-plugin.so` | `OBJECT GLOBAL DEFAULT UND` | 有 | `DT_NEEDED` 中存在 |
| `org.deepin.ds.desktop.so` | 不存在，没有重复定义 | 无 | `DT_NEEDED` 中存在 |

修正后的判据仅允许顶层未使用者没有该符号；真正的 core 使用者仍必须引用
framework，任何插件自带回调定义都会失败。没有为了迎合检查而加入无用引用。

独立复验固定原构建 artifact `15177359692` 的完整 SHA-256，在全新 Fedora 45
容器安装同一批 RPM，重新验证库字节、符号、重定位和依赖，并运行实际嵌套 Qt 探针。
外层/内层事件编号分别正确转换为 10001/10002，回调同址，整数返回 37、列表返回
两个元素，CTest 通过。RPM、SRPM、源码和补丁字节保持不变。

来源记录使用 schema 2 区分原构建和独立验证：原 `build_commit`、`run_id`、
`build_success=false`、失败阶段和原 manifest 保留；新增 `validation_commit`、
`validation_run_id` 和独立成功状态。新的证据统一放在 `validation/`，镜像导入器
只读取这次成功复验的证据，并核对原产物身份，不会把原来的失败运行改述为成功。

成功复验 artifact：`15179002203`，334,488,427 字节，ZIP SHA-256：

```text
cb994dc1d42ba43de29caa8ba56e1ff8a5ce9ba27805fc9679a8890261d87631
```

## 与 spec 和优化参数的关系

实际 COPR 构建日志显示，framework 和 core plugin 使用 Fedora 的 `-O2`、
`-flto=auto` 等参数，并追加上游的 `-Ofast`，二者使用 `-fPIC`。
没有证据表明 dde-shell 规格中的 `-fPIE` 传播到了这两个目标。

本地 GCC14 的两层 `RTLD_LOCAL` 最小实验进一步区分了条件：无 LTO 时，`-O2`
与 `-Ofast` 均通过，内联变量符号为 `UNIQUE`；加入 LTO 后，两者均产生 `GLOBAL`
副本并复现转换失败；保留 LTO、改用框架唯一定义后通过。最初单层加载实验没有
复现，说明嵌套局部加载关系也是关键条件，不能把 `-Ofast` 单独认定为原因。

这支持一个具体机制：当前工具链的 LTO 产物没有让各局部加载范围共享头文件里的
内联可变回调，而代码依赖了这种共享。临时规格保留维护者原有编译参数、依赖、
SELinux 和子包划分，只增加源码补丁。

## 临时包方案

补丁只改变两处：头文件中声明静态成员，在框架的 `event.cpp` 中定义一次。

- [补丁文件](packaging/hotfix/dde-file-manager/0001-dpf-centralize-event-converter.patch)
- SHA-256：`40b726528a34f41cdcbba4a538e5fc9b08fb3b354f8c340f905ead2c0d3d0381`
- [临时 spec](packaging/hotfix/dde-file-manager/dde-file-manager.spec)
- [固定输入与构建说明](packaging/hotfix/dde-file-manager/README.md)
- [完整构建工作流](.github/workflows/build-dfm-hotfix.yml)

需要同时重建所有使用该头文件的 DFM 子包；仅替换 framework 库会留下旧插件中的
重复定义。临时包为 `6.6.7-9.1.remix1.fc45`，不加入 versionlock，正常后续维护
版本仍能通过默认启用的 COPR 更新。

临时 RPM 来自固定 GitHub Actions 构建，通过固定源提交、源码、补丁、RPM 与
artifact SHA-256 记录来源；它们不是由 COPR 签名的新官方包。镜像只导入四个运行
包，保留匹配 SRPM 和来源记录。若构建时 COPR 的原始四包已不再是 `6.6.7-9.fc45`，
配方停止并要求重新对比，避免覆盖维护者更新。

最终门禁仍要求真实 DDM 登录、无同类 shell 崩溃、持续可见画面、人工截图复核，
以及 Live 和安装后的 SELinux Enforcing。加密和分区检查独立记录，不以存储安装
成功代替桌面成功。

## 壁纸与发行版标识：独立的资源问题

上一候选的完整 SquashFS 清单有 110,228 行，但 `/usr/share/backgrounds` 和
`/usr/share/wallpapers` 下没有可用壁纸文件。实际 wallpaper factory 日志还记录
读取 `deepin-default.jpg` 失败。这能解释缺失背景，不能替代上面的 SIGSEGV 根因。
证据与失败阶段保存在[上一候选报告](VALIDATION-45.20261127.1.md)。

固定 Treeland 0.12.0 的
[默认配置](https://github.com/linuxdeepin/treeland/blob/859a8c314f00947bc98168f46631ba10f9c7e6fa/misc/dconfig/org.deepin.dde.treeland.user.json)
指向 `/usr/share/backgrounds/default_background.jpg`；DDE appearance 的默认背景
以及旧桌面 schemas 引用的 `/usr/share/backgrounds/deepin/desktop.jpg` 也不存在。
只把缺失路径写进配置并不会带来对应资源包。

同时，镜像没有 DSysInfo 使用的 `deepin/distribution.info`。
[Treeland 的 LogoProvider](https://github.com/linuxdeepin/treeland/blob/859a8c314f00947bc98168f46631ba10f9c7e6fa/src/plugins/lockscreen/logoprovider.cpp)
将回退值 `:/dsg/logo.svg` 交给 `QUrl::fromUserInput`，本次实际日志呈现为无效的
`file::/dsg/logo.svg` 路径。候选配置给它提供真实安装的 Remix PNG 路径。

`45.20261127.2` 的处理：

- 依赖 Fedora `desktop-backgrounds-basic`，统一使用其
  `/usr/share/backgrounds/images/earth_from_space.jpg`。选择 JPEG 是为了同时适配
  当前 DDE 的背景选择界面和 Treeland；不依赖所有组件都能处理 JXL。
- 以资源级 DConfig override 设置 Treeland `defaultBackground` 和 appearance
  `Background_Uris`，并提供对应 GSettings 默认值；不重置已有用户的壁纸缓存。
- `distribution.info` 使用 `Name=Fedora DDE Remix`，Logo 与 LogoTransparent
  分别引用 `fedora-remix-logos` 包提供的实际 PNG。
- 镜像门禁检查真实文件、RPM 所有者、文件格式和编译后的 GSettings 默认值；
  VM 在稳定登录后读取实际 Treeland 服务 UID 的用户子路径配置及登录用户的
  appearance 配置，再检查实际截图。静态配置检查不能独立证明渲染成功。

Fedora 的[主标识包说明](https://packages.fedoraproject.org/pkgs/fedora-logos/fedora-logos/index.html)
明确区分 Spin 与 Remix；本项目使用
[Fedora Remix 标识包](https://packages.fedoraproject.org/pkgs/fedora-remix-logos/fedora-remix-logos/)
及 `generic-logos` 系统图形资源。

## desktop-base 的临时依赖调整

维护提交 `adcd681b0b9e68cacbf9daa33bede62a253a3315` 的
`deepin-desktop-base-2026.10.28-1` SPEC 硬性依赖 `fedora-logos`，阻止正常替换系统
图形资源。临时 noarch 重建只有两行变化：

```diff
-Release:        1%{?dist}
+Release:        1.1.remix1%{?dist}
-Requires:       fedora-logos
+Requires:       system-logos
```

上游源码固定到 `63c52c9387a350df684bb5043dd836d86f862092`，其余 SPEC 内容及安装
行为保持一致。镜像先核对原包 EVR 和新包 SHA-256，安装该临时包，再执行定向
`dnf swap fedora-logos generic-logos`，核对没有移除其他桌面包，最后安装配置 RPM。
没有伪造 `fedora-logos` Provides，也没有广泛允许删除依赖包。

原 SPEC、新 SPEC、固定来源、源码归档、二进制 RPM、匹配 SRPM 与构建记录均由
[本仓库的临时构建](packaging/hotfix/deepin-desktop-base/README.md)保留。
该临时包在 `.2` 中已完成原生 RPM/SRPM 构建和定向安装，实际 swap 只移除了
`fedora-logos`，全部 69 个桌面 mandatory 包仍在。`.2` 随后在独立的 schemas
严格检查处失败，没有完成最终镜像检查；这个依赖调整本身不是 DPF 崩溃补丁。
维护者后续若发布更高版本，应同步确认依赖可接受 `system-logos`；继续硬性要求
`fedora-logos` 会与本配置包要求的 `generic-logos` 形成依赖冲突。

## schemas 的实际严格编译失败

`.2` 在全部桌面包安装完成后执行 `glib-compile-schemas --strict`，对
`com.deepin.dde.keybinding.mediakey.gschema.xml` 的 319:23 报错：同一个 key 只允许
一个 summary。上游 `6.0.13` 的 `away` 键实际同时含两个 summary 和两个 description，
后面的两项为空；原 SPEC 的安装脚本静默忽略编译错误，包安装成功无法证明缓存完整。

固定上游提交 `00a92111f8f0cc7bcba8af9ae2a9950c7f02ae4e` 的原文件在本机 GLib
2.84.4 重现相同错误。最小补丁只删除重复的两个空元素，保留 `['XF86Away']`
默认值和 `Lock user` 文案，全部 79 个 XML 随后通过严格编译。x86 base、四组
edition 以及 Remix override 的检查也通过；不加入 ISO override 时，两项背景
默认值已指向 Fedora JPEG。

本机未执行 Go 编译器，override 合并按固定上游生成器的语义重现。`.3` 的
[临时 RPM 配方](packaging/hotfix/deepin-desktop-schemas/README.md)会使用真实 Fedora
Go 工具链，并在 RPM `%check` 对实际 buildroot 执行严格编译。ISO 的严格检查
保留，安装系统仍使用 Fedora glib2 文件触发器维护缓存。

修复补丁 SHA-256 为 `c0e06ede2bfef58227a2dff6cbb2292800b721ef6ac98150cb5fd9323d9ff709`。
维护者 PR 使用普通 Release `2`，ISO 临时包使用较低的 `1.1.remix1`，便于后续升级。

## 其他插件和服务告警

| 实际消息 / 现象 | 源码与证据支持的解释 | 当前处理 |
| --- | --- | --- |
| 多个插件出现无效 Topic / Event，编号为 `-1` | 与共享事件转换回调失效一致；不能逐条解释为独立缺包 | 统一修复 DPF 回调的归属，等待实际桌面日志复验 |
| `Report log plugin load log library failed!` | `reportlogworker.cpp` 动态加载可选 `deepin-event-log` 失败后告警并返回 | 不为消除告警而引入额外遥测库；不是已捕获的 WindowFrame 崩溃位置 |
| `no top group exist: "10_advance"` | 设置 JSON 生成器会插入临时分组并继续构建 | 记录为分组配置告警，没有据此修改插件或关闭桌面服务 |
| `dde-clipboard.service` 约 45.306 秒后启动超时 | 旧日志只证明超时；GUI/daemon 的 BusName 与源码相符，程序、两个 user unit 和三个 activation 文件均在实际 payload 中 | 根因未确定；新 VM 增加局部日志、unit 状态和 D-Bus 名称持有者采集 |

剪贴板固定上游为 `dde-clipboard 6.1.39`、提交
`e29ef6bd5d46fbe8fa227bc6300d6afc56e03bd8`。
[GUI main.cpp](https://github.com/linuxdeepin/dde-clipboard/blob/e29ef6bd5d46fbe8fa227bc6300d6afc56e03bd8/dde-clipboard/main.cpp)
先构造 MainWindow，之后才注册
[user unit 要求的 D-Bus 名称](https://github.com/linuxdeepin/dde-clipboard/blob/e29ef6bd5d46fbe8fa227bc6300d6afc56e03bd8/misc/dde-clipboard.service.in)。
初始化涉及 Display、Dock、Appearance、ClipboardLoader、DConfig 和区域监视器；
任何实际阻塞点都需要局部运行证据才能确认。
[daemon 的 Loader 注册](https://github.com/linuxdeepin/dde-clipboard/blob/e29ef6bd5d46fbe8fa227bc6300d6afc56e03bd8/dde-clipboard-daemon/clipboarddaemon.cpp)
也与 activation 文件对应。目前不通过延长 timeout、改服务名或禁用剪贴板来掩盖未知原因。
