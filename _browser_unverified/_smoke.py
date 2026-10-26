import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_min import Browser

here = os.path.dirname(os.path.abspath(__file__))
url = "file:///" + os.path.join(here, "page.html").replace("\\", "/")

t0 = time.time()
b = Browser(width=1920, height=1080, headless=True)
print("launched in %.1fs" % (time.time() - t0))
b.goto(url)
boxes = b.eval("window.__ui.boxes")
print("boxes:", len(boxes), "clickable:", sum(1 for x in boxes if x["clickable"]))
print("first:", json.dumps(boxes[0], ensure_ascii=False))

png = b.screenshot(scale=2 / 3)
open(os.path.join(here, "_smoke.png"), "wb").write(png)
print("screenshot bytes:", len(png))

# 点击 btn-1 的中心，验证点击真的生效
target = [x for x in boxes if x["id"] == "btn-1"][0]
cx, cy = target["x"] + target["w"] / 2, target["y"] + target["h"] / 2
b.eval("window.__reset()")
b.click(cx, cy)
time.sleep(0.2)
print("clicks:", b.eval("window.__ui.clicks"))

# 点击禁用按钮，应当没有记录
d = [x for x in boxes if x["id"] == "disabled-1"][0]
b.eval("window.__reset()")
b.click(d["x"] + 5, d["y"] + 5)
time.sleep(0.2)
print("clicks on disabled:", b.eval("window.__ui.clicks"))

# 视口尺寸校验
print("viewport:", b.eval("[window.innerWidth, window.innerHeight]"))
print("scroll:", b.eval("[document.documentElement.scrollWidth, document.documentElement.scrollHeight]"))
b.close()
print("ok")
