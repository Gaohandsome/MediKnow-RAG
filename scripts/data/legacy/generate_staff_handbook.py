"""【早期简版，保留备查】生成《医院员工培训守则》PDF（A4，7~8 页）。

现行版本是 scripts/data/generate_training_handbook.py（含流程图与 8 张表格），
两者输出同一个文件 data/医院员工培训守则.pdf，一般不要运行本脚本。

内容为合成演示数据，结构参照院内制度汇编，不可用于实际管理或诊疗决策。
用法：python scripts/data/generate_staff_handbook.py
输出：data/医院员工培训守则.pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "医院员工培训守则.pdf"

FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(FONT))

PAGE_W, PAGE_H = A4
MARGIN_L = MARGIN_R = 56
MARGIN_T = 62
MARGIN_B = 56
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R

INK = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#6B7280")
ACCENT = colors.HexColor("#1D4E89")
LINE = colors.HexColor("#C9D3DD")
FILL_HEAD = colors.HexColor("#E8EEF5")
FILL_SOFT = colors.HexColor("#F5F8FB")
WARN = colors.HexColor("#B45309")

S_TITLE = ParagraphStyle("title", fontName=FONT, fontSize=26, leading=36, textColor=ACCENT, alignment=TA_CENTER)
S_SUB = ParagraphStyle("sub", fontName=FONT, fontSize=11, leading=20, textColor=MUTED, alignment=TA_CENTER)
S_H1 = ParagraphStyle("h1", fontName=FONT, fontSize=15, leading=24, textColor=ACCENT, spaceBefore=14, spaceAfter=7)
S_H2 = ParagraphStyle("h2", fontName=FONT, fontSize=11.5, leading=20, textColor=INK, spaceBefore=9, spaceAfter=5)
S_BODY = ParagraphStyle("body", fontName=FONT, fontSize=10.2, leading=17.5, textColor=INK, wordWrap="CJK", spaceAfter=4)
S_NOTE = ParagraphStyle("note", fontName=FONT, fontSize=8.8, leading=14, textColor=MUTED, wordWrap="CJK", spaceAfter=3)
S_CELL = ParagraphStyle("cell", fontName=FONT, fontSize=8.8, leading=13.5, textColor=INK, wordWrap="CJK")
S_CELL_C = ParagraphStyle("cellc", parent=S_CELL, alignment=TA_CENTER)
S_CELL_H = ParagraphStyle("cellh", parent=S_CELL, textColor=colors.white)
S_CELL_HC = ParagraphStyle("cellhc", parent=S_CELL_H, alignment=TA_CENTER)
S_CAPTION = ParagraphStyle("cap", fontName=FONT, fontSize=8.8, leading=14, textColor=MUTED, alignment=TA_CENTER, spaceBefore=4)


def P(text: str, style: ParagraphStyle = S_BODY) -> Paragraph:
    return Paragraph(text, style)


def bullets(items: list[str]) -> list[Paragraph]:
    return [Paragraph(f"• {item}", S_BODY) for item in items]


def table(data: list[list], widths: list[float], header: bool = True, align_center_cols: set[int] | None = None) -> Table:
    """构造统一风格的表格；单元格内容支持 Paragraph。"""
    rows = []
    for r_index, row in enumerate(data):
        cells = []
        for c_index, cell in enumerate(row):
            if isinstance(cell, Paragraph):
                cells.append(cell)
                continue
            center = c_index in (align_center_cols or set())
            if header and r_index == 0:
                style = S_CELL_HC if center else S_CELL_H
            else:
                style = S_CELL_C if center else S_CELL
            cells.append(Paragraph(str(cell), style))
        rows.append(cells)

    tbl = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), ACCENT))
    tbl.setStyle(TableStyle(commands))
    return tbl


def cpr_flow() -> Drawing:
    """CPR 标准急救流程图（矢量绘制，元素位置按序累加，保证不重叠）。"""
    steps = [
        ("发现患者倒地", "轻拍双肩、大声呼叫，判断有无反应"),
        ("呼救并取除颤仪", "呼叫附近同事，启动院内急救团队（内线 8119）"),
        ("判断呼吸与脉搏", "观察胸廓起伏、触摸颈动脉，时间不超过 10 秒"),
        ("立即胸外按压", "30 次按压 + 2 次通气，深度 5~6 cm，频率 100~120 次/分"),
        ("除颤与给药", "室颤或无脉室速立即除颤；肾上腺素 1 mg，每 3~5 分钟一次"),
        ("ROSC 后处理", "维持血压与氧合，目标温度管理，转 ICU 继续监护"),
    ]
    box_h, gap, top_pad, note_h = 44, 15, 4, 22
    width = CONTENT_W
    height = top_pad + len(steps) * box_h + (len(steps) - 1) * gap + note_h

    drawing = Drawing(width, height)
    box_x, box_w = 30, width - 40
    cx = box_x + box_w / 2

    for index, (title, desc) in enumerate(steps):
        y = height - top_pad - (index + 1) * box_h - index * gap
        drawing.add(
            Rect(
                box_x, y, box_w, box_h,
                rx=7, ry=7,
                fillColor=FILL_SOFT,
                strokeColor=colors.HexColor("#8FB3D9"),
                strokeWidth=0.7,
            )
        )
        badge_cy = y + box_h / 2
        drawing.add(Circle(box_x + 20, badge_cy, 11, fillColor=ACCENT, strokeColor=None))
        drawing.add(
            String(box_x + 20, badge_cy - 3.6, str(index + 1), fontName=FONT, fontSize=10,
                   fillColor=colors.white, textAnchor="middle")
        )
        drawing.add(String(box_x + 40, y + box_h - 18, title, fontName=FONT, fontSize=10.2, fillColor=INK))
        drawing.add(String(box_x + 40, y + 10, desc, fontName=FONT, fontSize=8.4, fillColor=MUTED))

        if index < len(steps) - 1:
            arrow_top = y
            arrow_bottom = y - gap
            drawing.add(Line(cx, arrow_top, cx, arrow_bottom + 4, strokeColor=colors.HexColor("#8FB3D9"), strokeWidth=1.1))
            drawing.add(
                Polygon(
                    [cx - 3.6, arrow_bottom + 5, cx + 3.6, arrow_bottom + 5, cx, arrow_bottom],
                    fillColor=colors.HexColor("#8FB3D9"), strokeColor=None,
                )
            )

    note_y = height - top_pad - len(steps) * box_h - (len(steps) - 1) * gap - 13
    drawing.add(
        String(box_x, note_y, "注：每次按压中断不超过 10 秒；按压者每 2 分钟轮换一次，轮换在 5 秒内完成。",
               fontName=FONT, fontSize=8.2, fillColor=MUTED)
    )
    return drawing


class NumberedCanvas(pdf_canvas.Canvas):
    """两遍绘制，用于「第 X 页 / 共 Y 页」。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            if self._pageNumber > 1:
                self._header_footer(total)
            super().showPage()
        super().save()

    def _header_footer(self, total: int):
        self.setFont(FONT, 8.2)
        self.setFillColor(MUTED)
        self.drawString(MARGIN_L, PAGE_H - 40, "医院员工培训守则  V1.2")
        self.setStrokeColor(LINE)
        self.setLineWidth(0.4)
        self.line(MARGIN_L, PAGE_H - 46, PAGE_W - MARGIN_R, PAGE_H - 46)
        self.drawCentredString(PAGE_W / 2, 32, f"第 {self._pageNumber} 页 / 共 {total} 页")
        self.drawRightString(PAGE_W - MARGIN_R, 32, "院内文件 · 合成演示数据")


def cover() -> list:
    meta = Table(
        [
            ["文件编号", "YZ-TR-2026-01", "版本", "V1.2"],
            ["生效日期", "2026 年 10 月", "修订周期", "每年一次"],
            ["编制部门", "医务处 · 护理部 · 院感科 · 医学装备科", "适用范围", "全院在职员工"],
            ["密级", "院内公开", "归口管理", "人事科"],
        ],
        colWidths=[76, 190, 72, 142],
        hAlign="CENTER",
    )
    meta.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (-1, -1), INK),
                ("BACKGROUND", (0, 0), (0, -1), FILL_HEAD),
                ("BACKGROUND", (2, 0), (2, -1), FILL_HEAD),
                ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return [
        Spacer(1, 40 * mm),
        P("医院员工培训守则", S_TITLE),
        Spacer(1, 4),
        P("新员工入职 · 医疗安全核心制度 · 心肺复苏 · 院感防控 · 设备维护", S_SUB),
        Spacer(1, 14 * mm),
        meta,
        Spacer(1, 16 * mm),
        Table(
            [[Paragraph(
                "【合成演示数据】本手册由项目脚本生成，仅用于系统演示与测试，不可用于实际诊疗或管理决策。",
                ParagraphStyle("warn", fontName=FONT, fontSize=9, leading=15, textColor=WARN, wordWrap="CJK"),
            )]],
            colWidths=[CONTENT_W],
            style=TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#F0C48A")),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FDF6EC")),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ]
            ),
        ),
    ]


def section_general() -> list:
    return [
        KeepTogether([
            P("一、总则", S_H1),
            P("1.1 目的", S_H2),
            P("为规范新员工入职培训，统一医疗安全底线要求，明确急危重症处置、院感防控与设备管理的基本动作，特制定本守则。"),
        ]),
        P("1.2 适用范围", S_H2),
        P("全院在职员工，包括医师、护士、医技、药学、行政、后勤人员，以及进修人员、实习学生和外包驻场人员。"),
        P("1.3 培训要求", S_H2),
        *bullets(
            [
                "新员工须在入职 1 周内完成必修科目，1 个月内完成岗位专项培训。",
                "新员工岗前培训不少于 24 学时，在职员工年度复训不少于 8 学时。",
                "理论考核 80 分及以上、操作考核合格，方可独立上岗；两次补考仍不合格者暂停独立执业。",
                "培训与考核记录由人事科统一归档，保存期限不少于 3 年。",
            ]
        ),
        P("1.4 守则效力", S_H2),
        P("本守则与科室专项操作规程同时执行；两者不一致时，以更严格的规定为准。违反本守则造成不良后果的，按医院相关制度追责。"),
    ]


def section_onboarding() -> list:
    flow = table(
        [
            ["序号", "环节", "责任部门", "时限", "需提交材料"],
            ["1", "报到登记", "人事科", "入职当日", "身份证、学历证、执业资格证"],
            ["2", "体检与健康档案", "体检中心", "3 个工作日内", "体检报告、疫苗接种记录"],
            ["3", "岗前培训", "医务处 / 护理部", "5 个工作日内", "培训签到表、考核成绩"],
            ["4", "科室带教", "所在科室", "1 个月内", "带教计划、带教记录"],
            ["5", "授权与考核", "医务处", "考核合格后 2 个工作日", "授权申请表"],
            ["6", "工牌与系统权限", "信息科", "授权后 1 个工作日", "权限申请单"],
        ],
        [30, 88, 96, 106, 160],
        align_center_cols={0, 1, 2, 3},
    )

    core_items = [
        "首诊负责制度", "三级查房制度", "会诊制度", "分级护理制度",
        "值班与交接班制度", "疑难病例讨论制度", "急危重患者抢救制度", "术前讨论制度",
        "死亡病例讨论制度", "查对制度", "手术安全核查制度", "手术分级管理制度",
        "新技术和新项目准入制度", "危急值报告制度", "病历管理制度", "抗菌药物分级管理制度",
        "临床用血审核制度", "信息安全管理制度",
    ]
    core_rows = [[f"{i * 3 + j + 1}. {core_items[i * 3 + j]}" for j in range(3)] for i in range(6)]
    core = table(core_rows, [160, 160, 160], header=False)

    subjects = table(
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
        [160, 50, 150, 120],
        align_center_cols={1, 2, 3},
    )

    return [
        KeepTogether([P("二、新员工入职与医疗安全核心制度", S_H1), P("2.1 入职办理流程", S_H2)]),
        flow,
        KeepTogether([P("2.2 医疗质量安全核心制度（十八项）", S_H2), P("以下十八项制度为全院强制执行的底线要求，各科室不得另行简化："), core]),
        P("说明：十八项制度的具体执行标准见各制度单行文件；本守则仅作总纲提示，培训考核以单行文件为准。", S_NOTE),
        KeepTogether([P("2.3 培训科目与考核方式", S_H2), subjects]),
        P("说明：心肺复苏为全员必修，每年复训一次；麻醉、急诊、ICU、手术室人员每半年复训一次。", S_NOTE),
    ]


def section_cpr() -> list:
    press = table(
        [
            ["要素", "标准", "常见错误"],
            ["按压部位", "胸骨下半部，两乳头连线中点", "位置偏低压迫剑突"],
            ["按压深度", "5~6 cm", "深度不足或超过 6 cm"],
            ["按压频率", "100~120 次/分", "过快导致回弹不充分"],
            ["胸廓回弹", "每次按压后完全回弹", "手不离胸、持续下压"],
            ["按压中断", "每次中断 < 10 秒", "频繁摸脉、整理设备"],
            ["按压通气比", "30:2（建立高级气道后改为连续按压）", "通气过多、过度通气"],
        ],
        [80, 250, 150],
    )
    drugs = table(
        [
            ["环节", "操作要点", "参数 / 剂量"],
            ["除颤时机", "室颤或无脉性室速立即除颤，电极板涂导电糊并压实", "双相波 120~200 J"],
            ["除颤后", "立即恢复按压，2 分钟后再次评估心律", "不检查脉搏"],
            ["肾上腺素", "静脉推注后用 20 ml 生理盐水冲管", "1 mg，每 3~5 分钟一次"],
            ["胺碘酮", "第 2~3 次除颤后仍为室颤 / 无脉室速时使用", "首剂 300 mg，可追加 150 mg"],
            ["可逆病因", "按 5H5T 排查：低血容量、低氧、酸中毒、电解质紊乱、低体温；张力性气胸、心包填塞、中毒、肺栓塞、冠脉血栓", "每轮循环复查"],
        ],
        [70, 260, 150],
    )

    return [
        KeepTogether([
            P("三、心肺复苏（CPR）标准操作与急救流程", S_H1),
            P("3.1 标准急救流程", S_H2),
            cpr_flow(),
            P("图 1　成人心肺复苏（CPR）标准急救流程（院内版）", S_CAPTION),
        ]),
        KeepTogether([P("3.2 高质量胸外按压要素", S_H2), press]),
        KeepTogether([P("3.3 除颤与药物", S_H2), drugs]),
        P("3.4 团队分工与复苏后处理", S_H2),
        *bullets(
            [
                "按压者每 2 分钟轮换一次，轮换在 5 秒内完成，避免疲劳导致深度不足。",
                "气道管理者负责球囊面罩通气与高级气道建立；记录者负责计时、给药与事件记录。",
                "组长负责决策与除颤，不参与具体操作，确保全局观察。",
                "自主循环恢复后：收缩压维持 ≥ 90 mmHg，SpO2 94%~98%，PaCO2 35~45 mmHg，并启动目标温度管理（32~36 ℃，维持 24 小时）。",
            ]
        ),
    ]


def section_infection() -> list:
    hand = table(
        [
            ["时刻", "指征", "方式与时长"],
            ["接触患者前", "进入床单元、握手、查体前", "速干手消毒剂 20~30 秒"],
            ["清洁 / 无菌操作前", "置管、换药、注射、导尿前", "流动水洗手 40 秒或速干手消毒"],
            ["体液暴露风险后", "接触血液、体液、分泌物、伤口敷料后", "流动水 + 皂液洗手 40 秒"],
            ["接触患者后", "查体、协助翻身、更换床单后", "速干手消毒剂 20~30 秒"],
            ["接触周围环境后", "接触床栏、床头柜、监护仪后", "速干手消毒剂 20~30 秒"],
        ],
        [110, 210, 160],
    )
    exposure = table(
        [
            ["步骤", "操作要点", "时限", "责任人"],
            ["1 局部处理", "锐器伤由近心端向远心端挤出血液，流动水冲洗 5 分钟，75% 乙醇或碘伏消毒；黏膜暴露用大量生理盐水反复冲洗", "立即", "暴露者"],
            ["2 上报", "报告科室负责人，填写职业暴露登记表", "2 小时内", "暴露者 / 科室"],
            ["3 评估", "院感科评估暴露源（HBV / HCV / HIV / 梅毒）与暴露程度", "24 小时内", "院感科"],
            ["4 预防用药", "HBV 暴露按需注射乙肝免疫球蛋白并接种疫苗；HIV 暴露 2 小时内启动阻断用药，最迟不超过 72 小时", "越早越好", "感染科"],
            ["5 随访", "按病原体潜伏期复查（HIV：4 周、8 周、12 周、6 个月）", "按计划", "院感科"],
        ],
        [62, 248, 90, 80],
    )
    waste = table(
        [
            ["类别", "常见物品", "包装与标识"],
            ["感染性废物", "被血液体液污染的棉球、纱布、一次性手套、引流袋", "黄色专用袋，标注「感染性废物」"],
            ["损伤性废物", "针头、刀片、玻璃安瓿、缝合针", "黄色利器盒，装载不超过 3/4"],
            ["病理性废物", "手术及病理取材后的组织、器官", "专用容器，低温暂存"],
            ["药物性废物", "过期、变质或被污染的药品", "单独收集，交药学部统一处置"],
            ["化学性废物", "甲醛、二甲苯、含汞器械", "专用容器，交有资质单位处置"],
        ],
        [80, 250, 150],
    )

    return [
        KeepTogether([P("四、医院感染防控与职业暴露处理规范", S_H1), P("4.1 手卫生五个时刻", S_H2)]),
        hand,
        P("4.2 标准预防要点", S_H2),
        *bullets(
            [
                "所有患者的血液、体液、分泌物均视为具有潜在传染性，接触时按标准预防执行。",
                "预计接触血液体液飞溅时，加戴护目镜或面屏；操作前后执行手卫生。",
                "一次性物品不得重复使用；可复用器械使用后立即预处理并密闭转运。",
                "发生职业暴露后 2 小时内上报，不得隐瞒或延迟。",
            ]
        ),
        KeepTogether([P("4.3 职业暴露处置流程", S_H2), exposure]),
        KeepTogether([P("4.4 医疗废物分类", S_H2), waste]),
    ]


def section_equipment() -> list:
    blank = "□正常<br/>□异常"
    rows = [["日期", "设备名称 / 编号", "外观与电源", "报警与显示", "附件与耗材", "结论", "检查人"]]
    for _ in range(6):
        rows.append(["", "", blank, blank, "□齐全<br/>□缺失", "□可用<br/>□停用", ""])
    record = table(rows, [58, 100, 64, 64, 64, 62, 68], align_center_cols={0, 1, 2, 3, 4, 5, 6})

    return [
        KeepTogether([
            P("五、医疗设备日常维护与检查", S_H1),
            P("5.1 日常检查要求", S_H2),
            P("• 每日首次使用前完成外观、电源、报警与附件的四项检查，并填写检查记录表。"),
        ]),
        *bullets(
            [
                "生命支持类设备（呼吸机、除颤仪、输液泵）须每日测试报警功能，每周核对电池续航。",
                "发现异常立即停用、挂「故障」标识、移出诊疗区域，并在设备管理系统报修。",
                "设备档案、维修记录、计量检定证书由医学装备科统一保管，保存期限不少于 5 年。",
            ]
        ),
        KeepTogether([
            P("5.2 医疗设备日常维护与检查记录表", S_H2),
            P("使用说明：每台设备每日检查后填写；发现异常立即停用、挂「故障」标识并报修；本表每月交医学装备科归档。", S_NOTE),
            record,
        ]),
        P("5.3 故障报修流程", S_H2),
        *bullets(
            [
                "第一步：立即停止使用，断开电源，挂「故障待修」标识，移出诊疗区域。",
                "第二步：在设备管理系统提交报修单，注明设备编号、故障现象、发生时间。",
                "第三步：医学装备科 2 小时内响应；生命支持类设备 30 分钟内到场，必要时调配备用机。",
                "第四步：维修完成后由科室设备管理员验收，记录维修内容与更换配件，方可重新投入使用。",
            ]
        ),
    ]


def section_final() -> list:
    return [
        P("六、培训考核与附则", S_H1),
        P("6.1 考核与上岗", S_H2),
        P("新员工完成全部必修科目并通过考核后，由医务处或护理部核发上岗授权；未取得授权者不得独立值班、独立操作或独立出具报告。"),
        P("6.2 复训与继续教育", S_H2),
        *bullets(
            [
                "全体员工每年完成不少于 8 学时的院内复训，中心肺复苏为必训项目。",
                "麻醉、急诊、ICU、手术室人员每半年完成一次心肺复苏复训。",
                "新发布或修订的院内制度，应在发布后 1 个月内完成全员培训。",
            ]
        ),
        P("6.3 附则", S_H2),
        *bullets(
            [
                "本守则由医务处负责解释，人事科负责培训档案管理。",
                "本守则自发布之日起施行，原有相关规定与本守则不一致的，以本守则为准。",
                "本守则每年修订一次；遇重大制度调整时及时修订并重新发布。",
            ]
        ),
        Spacer(1, 10),
        P("编制：医务处 · 护理部 · 医院感染管理科 · 医学装备科　　审核：医疗质量管理委员会　　批准：院长办公会", S_NOTE),
    ]


def build() -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=MARGIN_T,
        bottomMargin=MARGIN_B,
        title="医院员工培训守则",
        author="MediKnow-RAG 演示项目",
        subject="院内培训制度汇编（合成演示数据）",
    )
    frame = Frame(MARGIN_L, MARGIN_B, CONTENT_W, PAGE_H - MARGIN_T - MARGIN_B, id="body",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame])])

    story: list = []
    story += cover()
    story.append(PageBreak())
    story += section_general()
    story += section_onboarding()
    story += section_cpr()
    story += section_infection()
    story += section_equipment()
    story += section_final()

    doc.build(story, canvasmaker=NumberedCanvas)
    return OUT


def main() -> int:
    path = build()
    print(f"已生成：{path}")
    print(f"大小：{path.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
