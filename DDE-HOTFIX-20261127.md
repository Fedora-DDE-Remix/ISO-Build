# DDE 桌面插件黑屏：定位与临时补丁

## 当前结论

现有 `dde-file-manager 6.6.7-9.fc45` 的 DPF 事件转换回调在嵌套插件加载时出现
不同实例：事件本身已经注册，内层插件却读到空回调，无法把事件名称转换为编号。
这不是 RPM 编译失败，而是已编译库之间的运行时共享状态问题。

真实 Fedora 45 的原包探针已复现问题；将回调改为框架库中的单一定义后，真实
Qt A/B 探针通过。完整临时 RPM 也已编译完成，并在独立的全新 Fedora 容器中
通过整包安装、实际 ELF 检查及嵌套 Qt 探针。**实际桌面和安装 VM 仍待验收，
不能用容器内的探针结果代替桌面恢复证明。**

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

维护仓库保持只读。上述诊断和临时构建都位于 ISO-Build 的独立分支，没有向维护
仓库提交，也没有向 COPR 发布或使用 COPR 私钥。

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
