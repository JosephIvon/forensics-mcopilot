
# ------------------------------------------------------------------ 固高 GTS（手册级真值）

def _gts() -> dict:
    return json.loads((util.KNOWLEDGE_DIR / "sdks" / "gts.json").read_text(encoding="utf-8"))


def _gts_index() -> dict[str, int]:
    """官方手册第 14 章《指令索引》的全部 167 条指令 → 手册页码。

    这是固高侧唯一的「外部真值」：绑定里出现的每个函数都必须能在这张表里找到，
    找不到 = 手册里压根没这个函数 = 真机 EntryPointNotFound。
    """
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / "gts_manual_index.csv"
    rows = list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))
    return {r["函数名"]: int(r["手册页码"]) for r in rows}


def test_固高手册指令索引必须完整():
    idx = _gts_index()
    assert len(idx) == 167, f"固高 GTS 单卡库指令应为 167 条，实得 {len(idx)}"
    protos = list(csv.DictReader(
        (util.KNOWLEDGE_DIR / "sdks" / "official_api" / "gts_prototypes.csv")
        .read_text(encoding="utf-8-sig").splitlines()))
    for r in protos:
        assert r["函数名"] in idx, f"{r['函数名']} 不在手册指令索引里"
        assert r["PDF页码"].strip(), f"{r['函数名']} 缺 PDF 页码（结论必须可回查）"


def test_固高每条PInvoke必须能在官方手册指令索引里找到():
    idx = _gts_index()
    for f in _gts()["pinvoke"]:
        assert f["fn"] in idx, (
            f"固高 {f['fn']} 不在官方手册的 167 条指令索引里 —— "
            "手册里没有这个函数，真机必然 EntryPointNotFound")


def test_固高不得绑定手册里不存在的当量函数():
    """固高**没有** SetPulsePerMm / GetPulsePerMm。

    当量是 GT_ProfileScale(axis, alpha, beta) 的分数比，而手册没给变换公式与
    alpha/beta 方向 —— 谁要是「按脉冲当量猜一个 alpha/beta 调下去」，
    位置会整体偏一个未知比例且不报错。所以这两条不许出现在绑定里。
    """
    idx = _gts_index()
    bound = {f["fn"] for f in _gts()["pinvoke"]}
    for fake in ("GT_SetPulsePerMm", "GT_GetPulsePerMm"):
        assert fake not in idx, f"{fake} 其实存在于手册里，请重新核对结论"
        assert fake not in bound, f"固高 {fake} 是不存在的函数，绑上去真机直接崩"


def test_固高PInvoke参数个数必须与手册原型一致():
    """参数个数对不上 = 栈错位。手册 PDF 的原型是硬证据。"""
    def arg_count(proto: str) -> int:
        inner = proto[proto.index("(") + 1: proto.rindex(")")]
        return 0 if not inner.strip() else len(inner.split(","))

    for f in _gts()["pinvoke"]:
        assert "proto" in f and "page" in f, f"{f['fn']} 缺 proto / page（无法回查手册）"
        n_mine = len(f.get("args", []))
        n_doc = arg_count(f["proto"])
        assert n_mine == n_doc, f"{f['fn']} 本仓库 {n_mine} 参，手册原型 {n_doc} 参：{f['proto']}"


def test_固高结构体字段必须与手册布局逐字一致():
    """THomePrm 的 pad 数组有实际含义（pad1[0]、pad2[1]），顺序错了回零行为就变了。"""
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    expect = [
        "public double acc;", "public double dec;", "public double velStart;", "public short smoothTime;",
        "public short mode;", "public short moveDir;", "public short indexDir;", "public short edge;",
        "public double velHigh;", "public double velLow;",
        "public int homeOffset;", "public int searchHomeDistance;",
        "public int searchIndexDistance;", "public int escapeStep;",
    ]
    for line in expect:
        assert line in code, f"固高结构体缺字段 {line}（与手册 PDF p222/p227/p204 逐字不一致）"
    # 顺序也要对：acc 在 velStart 前面，velStart 在 smoothTime 前面
    assert code.index("public double velStart;") < code.index("public short smoothTime;")
    assert code.index("public double velHigh;") < code.index("public double velLow;")
    assert code.index("public int homeOffset;") < code.index("public int searchHomeDistance;")


def test_固高轴号必须做1基换算():
    """手册的 axis / profile 参数全是 1 基正整数，适配器对外是 0 基 → 内部必须 +1。"""
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    assert "(short)(axis + 1)" in code, "固高适配器没有做轴号 1 基换算"
    # 位掩码同样是 bit0=轴1
    assert "1 << axis" in code, "固高点动/停止的轴掩码没有按 bit0=轴1 构造"


def test_固高速度单位必须按pulse每毫秒换算():
    """固高速度单位是 pulse/ms（不是 pulse/s）。差 1000 倍且不报错。"""
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    assert "mmPerSec * ppm / 1000.0" in code, "固高速度换算没有除以 1000（pulse/ms）"
    assert "mmPerSec2 * ppm / 1000000.0" in code, "固高加速度换算没有除以 1e6（pulse/ms²）"


def test_固高停止原因码必须声明是本工具自定义():
    """固高没有厂商停止原因码 —— 把自定义编码说成厂商码就是在骗现场。"""
    notes = "\n".join(_gts()["notes"])
    assert "没有厂商停止原因码" in notes, "固高 notes 必须写明「没有厂商停止原因码」"
    assert "自定义" in notes, "固高 notes 必须写明停止原因是本工具自定义编码"
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    assert "本工具按状态字位推导的自定义编码" in code, "生成的代码里没有标出停止原因是自定义编码"


def test_固高不得下发当量变换指令():
    """手册没给 alpha/beta 的变换公式与方向 → 谁调谁错，且不报错。"""
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    assert "Native.GT_ProfileScale" not in code, "固高适配器不允许下发 GT_ProfileScale（当量公式未确认）"
    assert "Native.GT_EncScale" not in code, "固高适配器不允许下发 GT_EncScale（当量公式未确认）"


def test_固高IO必须按类型位图映射且端口越界要抛异常():
    """固高 IO 是「类型 + 位图」模型，通用口只有 1~16。"""
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    assert "DiTypeGpi = 4" in code and "DoTypeGpo = 12" in code, "固高 IO 类型常量缺失"
    assert "port < 1 || port > 16" in code, "固高通用口 1~16 的越界校验缺失"


def test_固高未实现的能力必须显式失败():
    """插补的坐标系映射是站点配置，猜错会让轴走到错误坐标 → 必须显式抛异常。"""
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    for op in ("MoveLinear", "MoveArc"):
        seg = code[code.index(f"public void {op}("):]
        seg = seg[:seg.index("\n        }")]
        assert "NotSupportedException" in seg, f"固高 {op} 必须显式抛 NotSupportedException"


def test_固高回零方向未配置时必须抛异常():
    """方向猜错 = 朝机构外跑。没有安全默认方向。"""
    gts = _gts()
    assert any("HomeDirection" in l for l in gts["bodies"]["Home"]), "固高 Home 必须显式检查 HomeDirection"
    code = adapter_gen.render_adapter({**gts, "sdk_file": "gts.json"})
    assert "GtsHomeDir.Unconfigured" in code, "固高回零方向未配置时必须抛异常"


def test_固高已进能力矩阵且从待录入清单移除():
    data = json.loads((util.KNOWLEDGE_DIR / "cards.json").read_text(encoding="utf-8"))
    brands = [c["brand"] for c in data["cards"]]
    assert "固高" in brands, "固高未进能力矩阵"
    assert "固高" not in [p["brand"] for p in data["pending_brands"]], "固高还在待录入清单里"
    g = next(c for c in data["cards"] if c["brand"] == "固高")
    assert g["form_factor"] == "plug_in_card"
    assert "gts.dll" in g["interface"]
    assert "pulse/ms" in g["velocity_unit"], "固高速度单位必须写成 pulse/ms（不是 pulse/s）"
    # 跨品牌差异表必须三家都有列
    for d in data["cross_brand_diffs"]:
        assert d.get("googol"), f"跨品牌差异「{d['topic']}」缺固高那一列"
    # 固高必须有向厂商确认的条目（调用约定 / 当量公式 / 现场型号）
    items = [m for m in data["pending_manual_items"] if m["brand"] == "固高"]
    assert len(items) >= 3, "固高的厂商待确认项不足"
    blob = " ".join(m["item"] + m["why"] for m in items)
    assert "调用约定" in blob and "当量" in blob


def test_固高绑定全部标needs_manual_check():
    """官方 C# 声明文件 gts.cs 没拿到 → 调用约定与结构体打包没最终确认。

    手册原型已经逐条核对并记了 PDF 页码，但在拿到 gts.cs 之前不能标成已确认。
    """
    gts = _gts()
    for f in gts["pinvoke"]:
        assert f["verified"] == "needs-manual-check", \
            f"{f['fn']} 不该标成已确认（官方 gts.cs 未取得）"
    assert gts["dll"] == "gts.dll", "固高库名必须是 gts.dll（手册 PDF p15 原文）"
    assert gts["calling_convention"] == "StdCall"
