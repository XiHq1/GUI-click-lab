# 浏览器点击版（暂未验证，先别用）

这里放的是 `cdp_min.py` + `_smoke.py`：一个只用标准库驱动 Chrome 的极简实现
（启动无头 Chrome → DevTools 协议 → 截图 / 点击）。

**没有验证过**：写它的环境禁止了浏览器必需的命名管道（mojo IPC），Chrome 一启动就崩：

```
FATAL:mojo\public\cpp\platform\platform_channel.cc:112 Check failed: 拒绝访问
```

在你的机器上大概率能跑，但在你真正需要"点一下"之前，别把时间花在这里。

## 什么时候回来用它

- 想验证"坐标算对了，但点击没生效"（比如 DPI 缩放、窗口焦点问题）
- 想在没有虚拟机的条件下先练"截图 → 预测 → 点击 → 再截图确认"的闭环

## 用法（如果要用）

```powershell
cd E:\Deepseek\gui-click-lab
python _browser_unverified\_smoke.py
```

它会：启动 Chrome → 打开 `..\page.html` → 取所有元素坐标 → 截一张 1280 宽的图 →
点一下 `btn-01` → 读回点击记录。全打印出来就说明这条链路是通的。

## 更省事的替代

等虚拟机到位后，直接用 OSWorld 的 `DesktopEnv`：

```python
from desktop_env.desktop_env import DesktopEnv
env = DesktopEnv(provider_name="vmware", action_space="pyautogui")
obs = env.reset(task_config=cfg)
env.step("pyautogui.click(201, 231)")
```

它把"截图 / 点击 / 重置"都封装好了，不用自己写 CDP。
