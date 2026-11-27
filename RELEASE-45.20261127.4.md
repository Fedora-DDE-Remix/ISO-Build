# Fedora DDE Remix 45.20261127.4

本文是已构建并完成九组实际安装验证的发布说明。正式 GitHub Release 尚未创建。
拟发布的 tag `45.20261127.4` 对应实际 ISO 配方提交
`ec9903e1addf5e487f468680c6af4e34ce6bf873`；后续报告和测试脚本提交另行记录。

## 镜像与安装

- Fedora 45 / x86_64，普通可写 RPM / DNF 系统，DDE 桌面。
- Live 与安装后均保持 SELinux Enforcing，使用 Fedora 原生 PAM。
- 安装后默认启用 `mozixun/Fedora-DDE-Remix` COPR，保留 GPG 和 TLS 检查。
- 在当前 Live 会话完成用户、密码、时区、键盘及引导配置，由用户决定何时重启。
- 支持新建 LUKS2 加密根：Btrfs root/home 子卷，或 ext4/XFS 根内 home 目录。
  ESP 和独立 `/boot` 保持明文，开机输入口令解锁；目标不保存自动解锁密钥文件。
- 本镜像的加密和未加密安装均通过实际十进制 16 GB 虚拟磁盘验证。

Live 手动登录的用户名和密码均为 `liveuser`。安装目标使用安装时新建的账户，
不会保留 Live 用户。应用菜单与 Live 桌面提供 Fedora DDE Remix Installer。

## 下载与校验

当前产物位于 [Actions ISO artifact](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46002723335/artifacts/15202111074)。
正式发布应使用该 artifact 中已验收的原 ISO；合并后产生的新构建有独立来源身份和验收记录。

```text
文件：Fedora-DDE-Remix-45.20261127.4-x86_64.iso
字节数：3,462,608,896
SHA256：94009516d1751403a77bb24252ff097f3a85943d87430f11b5b2dd0dc808274a
```

解压 Actions artifact 后，可在下载目录运行：

```bash
sha256sum Fedora-DDE-Remix-45.20261127.4-x86_64.iso
```

上面的值对应 ISO 原文件。Actions ZIP 自身的 SHA256 为
`4557755c1adc7ac7de8cfb931685787cd120b9486efd063fd1e2f1a606fc5f87`。

## 本版修复

安装器 `0.3.0-0.3.fc45` 在首次挂载前建立贯穿全部阶段的私有 mount namespace，
修复旧候选加密安装结束时目标挂载被系统服务保留、LUKS 映射无法正常关闭的问题。
实际九组安装都已正常完成清理，三组加密安装随后通过口令解锁并从磁盘启动。

镜像包含 DPF 插件回调集中定义的临时修复、schemas 重复 XML 元素修复，以及
现存 JPEG 背景和 Remix 资源配置；DDM 的配置处理 Fedora 45 kmscon VT 竞争。
桌面维护仓库的 18 份 SPEC 修复独立提交在
[审查 PR](https://github.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/pull/1)，
没有触发 COPR。本 ISO 使用已验证的临时包和当时已发布的软件包，未包含这 18 个
维护版本的完整重新构建结果。

## 实际安装验证

| 场景 | 磁盘 | 结果 |
| --- | --- | --- |
| UEFI / GPT / LUKS2 / Btrfs root/home | 16,000,000,000 字节 | 安装、正常关闭映射、磁盘启动和桌面通过 |
| UEFI / GPT / Btrfs root/home | 64 GiB | 安装和磁盘启动通过 |
| BIOS / GPT / ext4 | 64 GiB | 安装和磁盘启动通过 |
| BIOS / MBR / ext4 | 64 GiB | 安装和磁盘启动通过 |
| UEFI / XFS 根、独立 ext4 home、磁盘 swap | 64 GiB | 同一 ISO 的独立补测通过 |
| UEFI / 新 Btrfs 根、保留既有 home 和 ESP | 64 GiB | 安装、身份/几何/样本内容保留及磁盘启动通过 |
| UEFI / GPT / Btrfs root/home | 16,000,000,000 字节 | 安装和磁盘启动通过 |
| BIOS / GPT / LUKS2 / ext4 | 64 GiB | 安装、正常关闭映射、磁盘启动和桌面通过 |
| UEFI / GPT / LUKS2 / XFS | 64 GiB | 安装、正常关闭映射、磁盘启动和桌面通过 |

这九组使用同一 ISO、KVM、4 vCPU、8 GiB RAM、单块 512 字节扇区的 VirtIO 磁盘。
每组都完成真实后端安装、移除 ISO、从磁盘启动及真实 DDM 图形登录，检查 Enforcing、
Fedora PAM、默认 COPR、可写根和账户清理。它不是安装器 GUI 全流程点选测试。

原 [compose/矩阵 run](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46002723335)
保留 `failure`：XFS/home/swap 一组在下载 ISO 前的宿主回归失败，其他八组成功。
仅修正回归脚本的进程退出观察后，
[同镜像补测](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/46008724244)
的 58 项宿主回归与真实安装全部通过。原失败没有被改写为成功。
完整证据见 [验收报告](VALIDATION-45.20261127.4.md) 与
[九组结果及 artifact 校验值](validation/45.20261127.4-results.json)。

## 使用边界与保留记录

14 GiB 设备初筛、12 GiB 内层根下限及实际 payload 空间检查均保留；16 GB 结果只
适用于本镜像已验证的两种小盘布局，不是未来包集合或所有布局的容量承诺。

加密模式目前不复用已有 LUKS，不支持 LVM、多容器、分离头、独立明文 home/var/
数据挂载或磁盘 swap；使用 zram。已测错误口令拒绝发生在重启前；实际 initramfs
启动验证的是正确口令解锁。保留分区测试比较 UUID、PARTUUID、起止扇区与样本文件
SHA256，没有逐项比较 UID/GID、mode、ACL 或 xattrs。

Secure Boot、实体显卡、多磁盘、4Kn、其他架构、实际 rescue 启动、内核升级后启动
及休眠恢复均未纳入本轮。XFS/home/swap 补测的 Live 登录期间捕获 22 条
`kmscon_t` 对 `tmpfs_t:filesystem` 的 `getattr` 拒绝，`permissive=0`；同次安装后
采集为 0 条。该记录未阻止本次登录或安装，也不构成“全程零 AVC”的结论。
旧环境的剪贴板启动超时仍缺少具体阻塞点证据；可选 reportlog 和设置分组占位告警
未被当作桌面崩溃原因。本轮没有因这些历史日志禁用服务或放宽策略。
