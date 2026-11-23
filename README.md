# Fedora DDE Remix ISO

此仓库构建 **Fedora 45 / x86_64 的传统可写系统 Live ISO**。安装器采用
`Fedora-DDE-Remix/fedora-dde-installer`，在当前 Live 会话内完成安装、用户、
密码、时区和键盘配置，由用户决定何时重启。

**本版按要求关闭 SELinux**：Live 启动和安装后的内核参数均包含 `selinux=0`，
系统配置为 `SELINUX=disabled`。安装器通过本仓库明确提供的 profile 选择此行为；
没有该 profile 的其他镜像仍使用安装器原有的 enforcing 检查。

## 桌面软件来源

维护者提供的桌面安装流程分成两个独立 DNF 事务：

```bash
sudo dnf copr enable mozixun/Fedora-DDE-Remix
sudo dnf install dde-desktop-comps
sudo dnf group install dde-desktop
```

DNF 5 的 `group install` 对应桌面组安装操作。comps RPM 先安装本地组元数据，
下一次 DNF 运行才能解析 `dde-desktop` 组。配方保留这个顺序，不维护第二份桌面包清单。
预检优先执行普通仓库的 `dnf install dde-desktop-comps`。如果仓库索引暂时找不到
这个包，本版只对 comps 使用已成功的 COPR 构建 **11377888**，版本固定为
`6.2.1-1.fc45.noarch`。下载后校验项目公钥、RPM 签名和版本，记录实际 SHA-256；
镜像内先安装同一份已验证的 comps RPM，再单独安装桌面组。桌面其他依赖继续使用
原 COPR，不启用整套 devel 仓库。

产物的 `comps-input.json` 和 `build-info.json` 记录实际选择的来源、版本及校验值。
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

维护者的 DDM `0.5.0-5` 普通登录引用 `system-login`；本仓库自己的
`fedora-dde-remix-config` RPM 提供这个入口，并接入 Fedora 的
`password-auth` / `postlogin`。DDM 自己拥有的 `ddm` 和 `ddm-autologin`
PAM 文件保持原样。该版本自动登录文件使用 Fedora PAM 不接受的 `@include`
语法，因此本版不启用自动登录。构建时用实际 PAM 库检查正确密码、错误密码、
未知账户和过期账户；图形会话还需通过启动验证。

## 构建与产物

推送配方到 `main` 或运行 **Actions → Build Fedora DDE Live ISO → Run workflow**。
工作流在 GitHub hosted 临时 Ubuntu VM 中启动特权 Fedora 45 容器，使用
`livemedia-creator --make-iso --no-virt` 构建 BIOS / UEFI hybrid ISO。
Anaconda 采用目录安装到新创建的临时文件系统镜像，配方不指定物理安装磁盘。

产物包含 ISO、SHA-256 校验文件、包清单、输入提交和构建日志。ISO artifact
保留 14 天；构建失败会保留已生成的日志及 RPM。实际产物以 Actions 状态为准，
提交配方或生成 RPM 不等于 ISO 已经构建成功。

`config/build.env` 固定安装器提交。工作流从该提交构建并测试 RPM，再安装到
ISO 中；不依赖 GitHub 上临时过期的旧 artifact。Fedora 与 COPR 软件包仍取自
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
