"""生成《医院员工培训守则》PDF（含流程图与表格，5~10 页）。

说明：全部内容为**合成演示数据**，结构参照真实院内培训手册，
不具备临床与制度效力，不可用于实际诊疗或管理决策。
用法：python scripts/data/generate_training_handbook.py
输出：data/医院员工培训守则.pdf
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
OUT_PDF = DATA_DIR / "医院员工培训守则.pdf"
FLOW_IMG = Path(tempfile.gettempdir()) / "cpr_flow.png"

TITLE = "医院员工培训守则"
VERSION = "V1.2"
REVISE_DATE = "2026 年 10 月"
DISCLAIMER = "【合成演示数据】本手册由项目脚本生成，仅用于系统演示与测试，不可用于实际诊疗或管理决策。"


# 中文字体候选：Windows / macOS / Linux 各取常见路径，也可用 MEDIKNOW_FONT 显式指定。
# 都找不到时调用方退回 PIL 默认字体（中文会变成方块），不阻断流程。
_CJK_FONT_CANDIDATES = (
    os.environ.get("MEDIKNOW_FONT", ""),
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)


def _find_cjk_font() -> str | None:
    """返回第一个存在的中文字体路径，找不到返回 None。"""
    for candidate in _CJK_FONT_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def build_cpr_flow() -> Path:
    """用 PIL 绘制 CPR 急救流程图，供 PDF 内嵌。"""
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1080, 1120
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    font_path = _find_cjk_font()
    title_font = ImageFont.truetype(font_path, 40) if font_path else ImageFont.load_default()
    body_font = ImageFont.truetype(font_path, 26) if font_path else ImageFont.load_default()
    small_font = ImageFont.truetype(font_path, 22) if font_path else ImageFont.load_default()

    draw.text((60, 40), "图 1  成人心肺复苏（CPR）标准急救流程", font=title_font, fill=(22, 40, 56))

    steps = [
        ("1", "发现患者倒地", "轻拍双肩、大声呼叫，判断有无反应"),
        ("2", "呼救并取除颤仪", "呼叫附近同事，启动院内急救团队（内线 8119）"),
        ("3", "判断呼吸与脉搏", "同时观察胸廓起伏、触摸颈动脉，不超过 10 秒"),
        ("4", "立即胸外按压", "30 次按压 + 2 次通气，深度 5~6 cm，频率 100~120 次/分"),
        ("5", "除颤与给药", "室颤/无脉室速立即除颤；肾上腺素 1 mg，每 3~5 分钟一次"),
        ("6", "ROSC 后处理", "维持血压与氧合，目标温度管理，转入重症监护"),
    ]

    box_x, box_w, box_h = 90, 900, 118
    y = 130
    for index, (num, head, detail) in enumerate(steps):
        draw.rounded_rectangle(
            [box_x, y, box_x + box_w, y + box_h], radius=14,
            fill=(236, 244, 251), outline=(120, 168, 196), width=2,
        )
        draw.ellipse([box_x + 24, y + 30, box_x + 84, y + 90], fill=(56, 132, 196))
        number = num
        bbox = draw.textbbox((0, 0), number, font=body_font)
        draw.text(
            (box_x + 54 - (bbox[2] - bbox[0]) / 2, y + 60 - (bbox[3] - bbox[1]) / 2 - 6),
            number, font=body_font, fill=(255, 255, 255),
        )
        draw.text((box_x + 110, y + 22), head, font=body_font, fill=(16, 48, 68))
        draw.text((box_x + 110, y + 64), detail, font=small_font, fill=(70, 88, 100))

        if index < len(steps) - 1:
            cx = box_x + box_w // 2
            draw.line([cx, y + box_h + 4, cx, y + box_h + 40], fill=(120, 168, 196), width=3)
            draw.polygon(
                [(cx - 9, y + box_h + 38), (cx + 9, y + box_h + 38), (cx, y + box_h + 52)],
                fill=(120, 168, 196),
            )
        y += box_h + 56

    draw.text((60, height - 60), "注：按压中断时间应小于 10 秒，每 2 分钟轮换按压者。", font=small_font, fill=(120, 128, 136))
    image.save(FLOW_IMG)
    return FLOW_IMG


def build_pdf() -> Path:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (
        Image,
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    font = "STSong-Light"

    title_style = ParagraphStyle("title", fontName=font, fontSize=30, leading=44, alignment=TA_CENTER, textColor=colors.HexColor("#16323C"))
    subtitle_style = ParagraphStyle("subtitle", fontName=font, fontSize=13, leading=24, alignment=TA_CENTER, textColor=colors.HexColor("#4A6472"))
    cover_meta = ParagraphStyle("cover_meta", fontName=font, fontSize=10.5, leading=20, alignment=TA_CENTER, textColor=colors.HexColor("#5F6E78"))
    h1 = ParagraphStyle("h1", fontName=font, fontSize=16, leading=28, spaceBefore=14, spaceAfter=8, textColor=colors.HexColor("#13455C"))
    h2 = ParagraphStyle("h2", fontName=font, fontSize=12.5, leading=22, spaceBefore=10, spaceAfter=5, textColor=colors.HexColor("#1B5A74"))
    body = ParagraphStyle("body", fontName=font, fontSize=10.5, leading=19, spaceAfter=5, alignment=TA_LEFT)
    bullet = ParagraphStyle("bullet", fontName=font, fontSize=10.5, leading=19, leftIndent=14, firstLineIndent=-14, spaceAfter=3)
    note = ParagraphStyle("note", fontName=font, fontSize=9, leading=15, textColor=colors.HexColor("#6B7885"), alignment=TA_LEFT)
    cell = ParagraphStyle("cell", fontName=font, fontSize=9, leading=14)
    cell_head = ParagraphStyle("cell_head", fontName=font, fontSize=9, leading=14, textColor=colors.HexColor("#12384A"))

    def table(data: list[list[str]], widths: list[float], header: bool = True) -> Table:
        rows = [[Paragraph(str(c), cell_head if (header and r == 0) else cell) for c in row] for r, row in enumerate(data)]
        tbl = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
        style = [
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#AFC4D2")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]
        if header:
            style += [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E3EEF5")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#7FA8BF")),
            ]
        tbl.setStyle(TableStyle(style))
        return tbl

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 8.5)
        canvas.setFillColor(colors.HexColor("#8A98A4"))
        canvas.drawString(2 * cm, 1.2 * cm, f"{TITLE}  {VERSION}")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"第 {doc.page} 页")
        canvas.setStrokeColor(colors.HexColor("#D6E2EA"))
        canvas.line(2 * cm, 1.6 * cm, A4[0] - 2 * cm, 1.6 * cm)
        canvas.restoreState()

    story: list = []

    # ---------- 封面 ----------
    story += [
        Spacer(1, 5.2 * cm),
        Paragraph(TITLE, title_style),
        Spacer(1, 0.35 * cm),
        Paragraph("新员工入职 · 医疗安全核心制度 · 心肺复苏 · 院感防控 · 设备维护", subtitle_style),
        Spacer(1, 4.2 * cm),
        Paragraph(f"版本 {VERSION}　|　修订日期 {REVISE_DATE}", cover_meta),
        Paragraph("编制：医务处 · 护理部 · 医院感染管理科 · 医学装备科", cover_meta),
        Paragraph("适用范围：全院在职员工（含新入职、进修、实习及外包驻场人员）", cover_meta),
        Spacer(1, 2.0 * cm),
        Paragraph(DISCLAIMER, note),
        PageBreak(),
    ]

    # ---------- 一、总则 ----------
    story += [
        Paragraph("一、总则", h1),
        Paragraph("1.1　目的", h2),
        Paragraph("为规范新员工入职培训，统一医疗安全底线要求，明确急危重症处置、院感防控与设备管理的基本动作，特制定本守则。", body),
        Paragraph("1.2　适用范围", h2),
        Paragraph("全院在职员工，包括医师、护士、医技、药学、行政、后勤，以及进修人员、实习学生和外包驻场人员。", body),
        Paragraph("1.3　培训要求", h2),
        Paragraph("•　新员工须在入职 1 周内完成必修科目，1 个月内完成岗位专项培训。", bullet),
        Paragraph("•　新员工岗前培训不少于 24 学时，在职员工年度复训不少于 8 学时。", bullet),
        Paragraph("•　理论考核 80 分及以上、操作考核合格，方可独立上岗；两次补考仍不合格者暂停独立执业。", bullet),
        Paragraph("•　培训与考核记录由人事科统一归档，保存期限不少于 3 年。", bullet),
        Paragraph("1.4　守则效力", h2),
        Paragraph("本守则与科室专项操作规程同时执行；两者不一致时，以更严格的规定为准。违反本守则造成不良后果的，按医院相关制度追责。", body),
    ]

    # ---------- 二、入职与核心制度 ----------
    story += [
        Paragraph("二、新员工入职与医疗安全核心制度", h1),
        Paragraph("2.1　入职办理流程", h2),
        table(
            [
                ["序号", "环节", "责任部门", "时限", "需提交材料"],
                ["1", "报到登记", "人事科", "入职当日", "身份证、学历证、执业资格证"],
                ["2", "体检与健康档案", "体检中心", "3 个工作日内", "体检报告、疫苗接种记录"],
                ["3", "岗前培训", "医务处 / 护理部", "5 个工作日内", "培训签到表、考核成绩"],
                ["4", "科室带教", "所在科室", "1 个月内", "带教计划、带教记录"],
                ["5", "授权与考核", "医务处", "考核合格后 2 个工作日", "授权申请表"],
                ["6", "工牌与系统权限", "信息科", "授权后 1 个工作日", "权限申请单"],
            ],
            [1.2 * cm, 3.1 * cm, 3.5 * cm, 3.7 * cm, 5.5 * cm],
        ),
        Spacer(1, 0.3 * cm),
        Paragraph("2.2　医疗质量安全核心制度（十八项）", h2),
        Paragraph("首诊负责制度、三级查房制度、会诊制度、分级护理制度、值班与交接班制度、疑难病例讨论制度、"
                  "急危重患者抢救制度、术前讨论制度、死亡病例讨论制度、查对制度、手术安全核查制度、手术分级管理制度、"
                  "新技术和新项目准入制度、危急值报告制度、病历管理制度、抗菌药物分级管理制度、临床用血审核制度、信息安全管理制度。", body),
        Spacer(1, 0.2 * cm),
        Paragraph("2.3　培训科目与考核方式", h2),
        table(
            [
                ["培训科目", "学时", "考核方式", "合格标准"],
                ["医院文化与规章制度", "4", "线上答题", "≥ 80 分"],
                ["医疗质量安全核心制度", "6", "笔试", "≥ 80 分"],
                ["心肺复苏与急救流程", "4", "模拟人实操", "操作评分 ≥ 85 分"],
                ["医院感染防控", "4", "线上答题 + 手卫生实操", "两项均合格"],
                ["医疗设备使用与维护", "2", "现场演示", "能独立完成日检"],
                ["医患沟通与知情同意", "2", "情景演练", "合格"],
                ["信息系统与病历书写", "2", "上机操作", "完成一份模拟病历"],
            ],
            [6.4 * cm, 2.0 * cm, 4.6 * cm, 4.0 * cm],
        ),
        Paragraph("说明：心肺复苏为全员必修，每年复训一次；麻醉、急诊、ICU、手术室人员每半年复训一次。", note),
    ]

    # ---------- 三、CPR ----------
    story += [
        KeepTogether(
            [
                Paragraph("三、心肺复苏（CPR）标准操作与急救流程", h1),
                Paragraph("3.1　标准急救流程", h2),
                Image(str(FLOW_IMG), width=12.6 * cm, height=13.1 * cm),
                Paragraph("图 1　成人心肺复苏标准急救流程（院内版）", note),
            ]
        ),
        Spacer(1, 0.2 * cm),
        Paragraph("3.2　高质量胸外按压要素", h2),
        table(
            [
                ["要素", "标准", "常见错误"],
                ["按压部位", "胸骨下半部，两乳头连线中点", "位置偏低压迫剑突"],
                ["按压深度", "5~6 cm", "深度不足或超过 6 cm"],
                ["按压频率", "100~120 次/分", "过快导致回弹不充分"],
                ["胸廓回弹", "每次按压后完全回弹", "手不离胸、持续下压"],
                ["按压中断", "每次中断 < 10 秒", "频繁摸脉、整理设备"],
                ["按压通气比", "30:2（高级气道后连续按压）", "通气过多、过度通气"],
            ],
            [3.2 * cm, 6.6 * cm, 7.2 * cm],
        ),
        Spacer(1, 0.3 * cm),
        Paragraph("3.3　除颤与药物", h2),
        table(
            [
                ["环节", "操作要点", "参数 / 剂量"],
                ["除颤时机", "室颤或无脉性室速立即除颤，电极板涂导电糊并压实", "双相波 120~200 J"],
                ["除颤后", "立即恢复按压，2 分钟后再次评估心律", "不检查脉搏"],
                ["肾上腺素", "静脉推注后 20 ml 生理盐水冲管", "1 mg，每 3~5 分钟一次"],
                ["胺碘酮", "第 2~3 次除颤后仍为室颤/无脉室速时使用", "首剂 300 mg，可追加 150 mg"],
                ["可逆病因", "按 5H5T 排查：低血容量、低氧、酸中毒、电解质紊乱、低体温；"
                             "张力性气胸、心包填塞、中毒、肺栓塞、冠脉血栓", "每轮循环复查"],
            ],
            [3.0 * cm, 8.6 * cm, 5.4 * cm],
        ),
        Spacer(1, 0.3 * cm),
        Paragraph("3.4　团队分工与复苏后处理", h2),
        Paragraph("•　按压者每 2 分钟轮换一次，轮换在 5 秒内完成，避免疲劳导致深度不足。", bullet),
        Paragraph("•　气道管理者负责球囊面罩通气与高级气道建立，记录者负责计时、给药与事件记录。", bullet),
        Paragraph("•　组长负责决策与除颤，不参与具体操作，确保全局观察。", bullet),
        Paragraph("•　自主循环恢复后：收缩压维持 ≥ 90 mmHg，SpO₂ 94%~98%，PaCO₂ 35~45 mmHg，启动目标温度管理（32~36 ℃，维持 24 小时）。", bullet),
    ]

    # ---------- 四、院感 ----------
    story += [
        Paragraph("四、医院感染防控与职业暴露处理规范", h1),
        Paragraph("4.1　手卫生五个时刻", h2),
        table(
            [
                ["时刻", "指征", "方式与时长"],
                ["接触患者前", "进入床单元、握手、查体前", "速干手消毒剂 20~30 秒"],
                ["清洁/无菌操作前", "置管、换药、注射、配药前", "流动水 + 皂液 40 秒，七步洗手法"],
                ["体液暴露风险后", "接触血液、体液、分泌物、伤口敷料后", "流动水 + 皂液 40 秒"],
                ["接触患者后", "查体、护理、协助翻身之后", "速干手消毒剂 20~30 秒"],
                ["接触患者周围环境后", "整理床单位、接触床栏与仪器后", "速干手消毒剂 20~30 秒"],
            ],
            [3.8 * cm, 7.2 * cm, 6.0 * cm],
        ),
        Paragraph("注意：戴手套不能替代手卫生，脱手套后必须再次执行手卫生。", note),
        Spacer(1, 0.3 * cm),
        Paragraph("4.2　防护用品选用", h2),
        table(
            [
                ["诊疗情形", "口罩", "手套", "隔离衣", "护目镜/面屏"],
                ["普通门诊、查房", "医用外科口罩", "手卫生即可", "不需要", "不需要"],
                ["可能接触血液体液", "医用外科口罩", "一次性手套", "必要时", "需要"],
                ["气管插管、吸痰", "医用防护口罩（N95）", "双层手套", "防渗隔离衣", "需要"],
                ["多重耐药菌患者", "医用外科口罩", "一次性手套", "接触隔离衣", "按操作需要"],
                ["呼吸道传染病病区", "医用防护口罩（N95）", "一次性手套", "防护服", "需要"],
            ],
            [4.2 * cm, 4.2 * cm, 2.9 * cm, 2.9 * cm, 2.8 * cm],
        ),
        Spacer(1, 0.3 * cm),
        Paragraph("4.3　职业暴露处置流程", h2),
        table(
            [
                ["步骤", "操作要点", "时限", "责任人"],
                ["1 局部处理", "锐器伤：由近心端向远心端挤出血液，流动水冲洗 5 分钟，"
                              "75% 乙醇或碘伏消毒；黏膜暴露用大量生理盐水反复冲洗", "立即", "暴露者"],
                ["2 上报", "报告科室负责人，填写职业暴露登记表", "2 小时内", "暴露者 / 科室"],
                ["3 评估", "院感科评估暴露源（HBV/HCV/HIV/梅毒）与暴露程度", "24 小时内", "院感科"],
                ["4 预防用药", "HBV 暴露按需注射乙肝免疫球蛋白并接种疫苗；"
                              "HIV 暴露在 2 小时内启动阻断用药，最迟不超过 72 小时", "越早越好", "感染科"],
                ["5 随访", "按病原体潜伏期复查（HIV：4 周、8 周、12 周、6 个月）", "按计划", "院感科"],
            ],
            [2.4 * cm, 8.8 * cm, 3.0 * cm, 2.8 * cm],
        ),
        Spacer(1, 0.3 * cm),
        Paragraph("4.4　医疗废物分类", h2),
        table(
            [
                ["类别", "常见物品", "包装与标识"],
                ["感染性废物", "被血液体液污染的棉球、纱布、一次性手套、引流袋", "黄色专用袋，标注「感染性废物」"],
                ["损伤性废物", "针头、刀片、玻璃安瓿、缝合针", "黄色利器盒，装载不超过 3/4"],
                ["病理性废物", "手术及病理取材后的组织、器官", "专用容器，低温暂存"],
                ["药物性废物", "过期、变质或被污染的药品", "单独收集，交药学部统一处置"],
                ["化学性废物", "甲醛、二甲苯、含汞废液", "专用容器，禁止混入感染性废物"],
            ],
            [3.0 * cm, 8.4 * cm, 5.6 * cm],
        ),
    ]

    # ---------- 五、设备 ----------
    story += [
        Paragraph("五、医疗设备日常维护与检查记录", h1),
        Paragraph("5.1　设备分级与巡检频次", h2),
        table(
            [
                ["风险等级", "设备举例", "日常检查", "责任人"],
                ["高风险（生命支持类）", "呼吸机、除颤仪、监护仪、输液泵、麻醉机", "每班一次 + 使用前检查", "当班护士 / 技师"],
                ["中风险（诊疗类）", "超声、心电图机、内镜、离心机", "每日一次", "设备责任人"],
                ["低风险（辅助类）", "体重秤、血压计、雾化器、轮椅", "每周一次", "科室设备管理员"],
            ],
            [4.0 * cm, 6.6 * cm, 3.6 * cm, 2.8 * cm],
        ),
        Spacer(1, 0.35 * cm),
        KeepTogether(
            [
                Paragraph("5.2　医疗设备日常维护与检查记录表", h2),
                Paragraph("使用说明：每台设备每日检查后填写；发现异常立即停用、挂「故障」标识并报修；本表每月交医学装备科归档。", note),
                Spacer(1, 0.15 * cm),
                table(
                    [
                        ["日期", "设备名称 / 编号", "外观与电源", "报警与显示", "附件与耗材", "结论", "检查人"],
                        ["", "", "□正常 □异常", "□正常 □异常", "□齐全 □缺失", "□可用 □停用", ""],
                        ["", "", "□正常 □异常", "□正常 □异常", "□齐全 □缺失", "□可用 □停用", ""],
                        ["", "", "□正常 □异常", "□正常 □异常", "□齐全 □缺失", "□可用 □停用", ""],
                        ["", "", "□正常 □异常", "□正常 □异常", "□齐全 □缺失", "□可用 □停用", ""],
                        ["", "", "□正常 □异常", "□正常 □异常", "□齐全 □缺失", "□可用 □停用", ""],
                        ["", "", "□正常 □异常", "□正常 □异常", "□齐全 □缺失", "□可用 □停用", ""],
                    ],
                    [1.6 * cm, 3.6 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 2.4 * cm, 1.9 * cm],
                ),
            ]
        ),
        Spacer(1, 0.3 * cm),
        Paragraph("5.3　故障报修流程", h2),
        Paragraph("•　第一步：立即停止使用，断开电源，挂「故障待修」标识，移出诊疗区域。", bullet),
        Paragraph("•　第二步：在设备管理系统提交报修单，注明设备编号、故障现象、发生时间。", bullet),
        Paragraph("•　第三步：医学装备科 2 小时内响应；生命支持类设备 30 分钟内到场，必要时调配备用机。", bullet),
        Paragraph("•　第四步：维修完成后由科室设备管理员验收，记录维修内容与更换配件，方可重新投入使用。", bullet),
    ]

    # ---------- 六、考核与附则 ----------
    story += [
        Paragraph("六、培训考核与附则", h1),
        Paragraph("6.1　考核组织", h2),
        Paragraph("新员工培训考核由医务处与护理部联合组织，每年 3 月、9 月各组织一次集中复训；"
                  "科室每月开展一次科内业务学习，内容纳入年度学分管理。", body),
        Paragraph("6.2　结果应用", h2),
        Paragraph("•　考核成绩记入个人技术档案，作为职称晋升、岗位聘任与评优的参考依据。", bullet),
        Paragraph("•　心肺复苏操作考核不合格者，暂停独立值班，补考合格后恢复。", bullet),
        Paragraph("•　无故缺席培训或代签到的，按医院考勤与培训管理规定处理。", bullet),
        Paragraph("6.3　附则", h2),
        Paragraph("本守则由医务处负责解释，自发布之日起施行，每两年修订一次；"
                  "国家或行业规范更新时，及时修订并组织专项培训。", body),
        Spacer(1, 0.35 * cm),
        table(
            [
                ["编制部门", "审核", "批准", "生效日期"],
                ["医务处 · 护理部 · 院感科 · 医学装备科", "医疗质量管理委员会", "院长办公会", REVISE_DATE],
            ],
            [7.0 * cm, 4.0 * cm, 3.4 * cm, 2.6 * cm],
        ),
    ]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT_PDF),
        pagesize=A4,
        title=TITLE,
        author="MediKnow-RAG 演示项目",
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2.0 * cm,
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return OUT_PDF


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    build_cpr_flow()
    path = build_pdf()

    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text_len = sum(len(page.extract_text() or "") for page in reader.pages)
    print(f"已生成：{path.name}")
    print(f"页数：{len(reader.pages)} 页，可提取文本 {text_len} 字，大小 {path.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
