"""生成 `data/demo.db` 业务演示库（工时事实 / CRM / 合同样例）。

数据不是纯随机噪声，而是刻意埋了可以被分析出来的规律：
- 季度趋势：Q3 人均工时与交付量略降（暑期+项目收尾）；
- 区域差异：华东人效最高，东北异常偏低（可被 ChatBI 直接查出来）；
- 加班集中：2025-06 与 2026-06（Q2 末）加班显著抬升；
- 敏感列：worktime_fact.salary（secret）、crm_customer 客户名（internal）。

所有表结构、注释与敏感级都在本文件定义（`TABLE_META` / `COLUMN_META` / `METRICS`），
seed 侧只负责往 app.db 落元数据，避免两处定义漂移。
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

SEED = 20261023
START = date(2024, 1, 1)
END = date(2026, 9, 30)

REGIONS = ["华东", "华南", "华北", "西南", "东北"]
#: 区域人效系数（工时 & 交付量都乘），华东最高、东北异常偏低
REGION_FACTOR = {"华东": (1.07, 1.16), "华南": (1.04, 1.08), "华北": (0.99, 0.98),
                 "西南": (0.95, 0.92), "东北": (0.87, 0.79)}
REGION_MANAGER = {"华东": "沈亦舟", "华南": "梁晞", "华北": "赵砚青", "西南": "罗梓潼", "东北": "韩立冬"}
REGION_CC = {"华东": "CC-HD-001", "华南": "CC-HD-002", "华北": "CC-HD-003",
             "西南": "CC-HD-004", "东北": "CC-HD-005"}

DEPTS = ["研发", "实施", "测试", "运维"]
DEPT_FACTOR = {"研发": 1.02, "实施": 1.06, "测试": 0.95, "运维": 0.97}
DEPT_BILLABLE = {"研发": 0.74, "实施": 0.86, "测试": 0.66, "运维": 0.71}
DEPT_DEFECT = {"研发": 0.34, "实施": 0.12, "测试": 0.62, "运维": 0.09}
DEPT_LEADER = {"研发": "周牧", "实施": "程景舟", "测试": "叶清和", "运维": "许澄"}

PROJECTS = [
    "数据中台二期", "智能报表平台", "供应链数字化", "客户主数据治理",
    "AI 客服助手", "财务共享中心", "门店运营分析", "统一身份平台",
]

SURNAMES = ["陈", "林", "黄", "张", "李", "王", "刘", "周", "吴", "徐", "孙", "马", "朱", "胡",
            "郭", "何", "高", "罗", "郑", "梁", "谢", "宋", "唐", "许", "韩", "冯", "邓", "曹",
            "彭", "曾", "萧", "田", "董", "潘", "袁", "蔡", "蒋", "余", "于", "杜"]
GIVEN = ["嘉铭", "知远", "文瑄", "亦航", "沐辰", "思南", "若初", "星野", "清和", "一诺",
         "子墨", "锦程", "予安", "书言", "雨桐", "柏舟", "君豪", "泽楷", "悦然", "晨曦",
         "启明", "怀瑾", "静姝", "文博", "衡之", "斯年", "望舒", "含章", "致远", "宁静"]


def _employees() -> list[dict]:
    """40 名员工：区域/部门/项目/薪资都为确定性分配。"""
    rng = np.random.default_rng(SEED + 7)
    out: list[dict] = []
    for i in range(40):
        region = REGIONS[i % len(REGIONS)]
        dept = DEPTS[(i // len(REGIONS)) % len(DEPTS)]
        project = PROJECTS[i % len(PROJECTS)]
        given = GIVEN[i % len(GIVEN)]
        name = SURNAMES[i % len(SURNAMES)] + given
        # 级别：0~3，影响薪资与交付
        seniority = int(rng.integers(0, 4))
        base = 12500 + seniority * 2600 + {"研发": 1800, "实施": 900, "测试": 400, "运维": 600}[dept]
        base += {"华东": 1200, "华南": 900, "华北": 400, "西南": -200, "东北": -600}[region]
        salary = round(float(base + rng.normal(0, 380)) / 100.0) * 100
        out.append(
            {
                "employee_id": f"E{i + 1:03d}",
                "employee_name": name,
                "region": region,
                "dept": dept,
                "project": project,
                "seniority": seniority,
                "salary": salary,
            }
        )
    return out


def _workdays() -> list[date]:
    days: list[date] = []
    cur = START
    while cur <= END:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return days


def _quarter_effect(d: date) -> float:
    """季度趋势：Q3 略降，年份间轻微上行。"""
    year_lift = {2024: 0.985, 2025: 1.0, 2026: 1.015}.get(d.year, 1.0)
    q = (d.month - 1) // 3 + 1
    seasonal = {1: 0.99, 2: 1.01, 3: 0.955, 4: 1.0}[q]
    return year_lift * seasonal


def build_fact(employees: list[dict]) -> tuple[list[tuple], list[date]]:
    rng = np.random.default_rng(SEED)
    days = _workdays()
    n_days, n_emp = len(days), len(employees)

    # 员工级系数
    reg_hours = np.array([REGION_FACTOR[e["region"]][0] for e in employees])
    reg_tasks = np.array([REGION_FACTOR[e["region"]][1] for e in employees])
    dept_hours = np.array([DEPT_FACTOR[e["dept"]] for e in employees])
    dept_bill = np.array([DEPT_BILLABLE[e["dept"]] for e in employees])
    dept_defect = np.array([DEPT_DEFECT[e["dept"]] for e in employees])
    proj_lift = np.array([1.0 + 0.02 * (i % 5) for i in range(n_emp)])
    skill = np.array([1.0 + 0.03 * e["seniority"] for e in employees])

    # 日期级系数
    qeff = np.array([_quarter_effect(d) for d in days])
    is_q3 = np.array([d.month in (7, 8, 9) for d in days])
    is_q2_end = np.array([d.month == 6 for d in days])

    hours = (
        7.55
        * reg_hours[None, :]
        * dept_hours[None, :]
        * proj_lift[None, :]
        * qeff[:, None]
        + rng.normal(0, 0.62, size=(n_days, n_emp))
    )
    hours += np.where(is_q3[:, None], -0.18, 0.0)
    hours = np.clip(hours, 3.8, 11.6)

    # 加班：Q2 末（6 月）显著抬升，其余日子零星
    ot_prob = np.where(is_q2_end[:, None], 0.34, 0.055)
    ot_prob = np.broadcast_to(ot_prob, (n_days, n_emp)).copy()
    # 华南/华东加班更多，东北基本不加班
    ot_prob *= np.where(reg_hours > 1.0, 1.25, 1.0)[None, :]
    ot_prob *= np.where(reg_hours < 0.9, 0.35, 1.0)[None, :]
    has_ot = rng.random((n_days, n_emp)) < ot_prob
    ot_hours = np.where(
        has_ot,
        np.where(is_q2_end[:, None], rng.uniform(1.5, 4.2, (n_days, n_emp)), rng.uniform(0.5, 2.4, (n_days, n_emp))),
        0.0,
    )
    ot_hours = np.round(ot_hours * 2) / 2
    overtime = np.minimum(ot_hours, np.maximum(hours - 4.0, 0.0))

    # 可计费：部门/区域/季度共同影响
    billable_p = dept_bill[None, :] * (0.96 + 0.06 * (reg_tasks[None, :] - 0.79))
    billable_p = np.where(is_q3[:, None], billable_p - 0.035, billable_p)
    billable = (rng.random((n_days, n_emp)) < np.clip(billable_p, 0.35, 0.95)).astype(int)

    # 交付任务数：与工时、区域、技能正相关
    lam = np.maximum(hours, 0.1) / 2.35 * reg_tasks[None, :] * skill[None, :] * (1.0 - 0.06 * is_q3[:, None])
    tasks = rng.poisson(np.clip(lam, 0.1, 12)).astype(int)

    # 缺陷：与实际交付复杂度相关；东北与测试部偏高
    lam_d = dept_defect[None, :] * (hours / 7.5) * 0.75
    lam_d = np.where((reg_hours < 0.9)[None, :], lam_d * 1.35, lam_d)
    defects = rng.poisson(np.clip(lam_d, 0.01, 6)).astype(int)

    rows: list[tuple] = []
    idx = 0
    for t, d in enumerate(days):
        ds = d.isoformat()
        for j, emp in enumerate(employees):
            idx += 1
            rows.append(
                (
                    f"WT{idx:06d}",
                    ds,
                    emp["region"],
                    emp["dept"],
                    emp["project"],
                    emp["employee_id"],
                    emp["employee_name"],
                    round(float(hours[t, j]), 1),
                    round(float(overtime[t, j]), 1),
                    int(billable[t, j]),
                    int(tasks[t, j]),
                    int(defects[t, j]),
                    emp["salary"],
                )
            )
    return rows, days


# ---------------------------------------------------------------- CRM


CUSTOMER_PREFIX = ["上海", "北京", "深圳", "广州", "杭州", "南京", "成都", "武汉", "西安", "苏州",
                   "青岛", "合肥", "长沙", "天津", "重庆", "宁波", "无锡", "厦门", "郑州", "济南",
                   "福州", "昆明", "沈阳", "大连", "南昌", "常州", "温州", "东莞", "佛山", "石家庄"]
CUSTOMER_CORE = ["鼎信", "远瞻", "恒泰", "中科", "华曜", "启元", "博远", "锦途", "智联", "云枢",
                 "光华", "瑞恩", "天成", "宏图", "嘉禾", "联创", "新元", "聚力", "晟世", "安澜",
                 "麦禾", "维创", "鸿信", "赛格", "明睿", "融通", "众川", "北斗", "泰合", "青禾"]
CUSTOMER_SUFFIX = ["智能科技有限公司", "信息技术有限公司", "数据服务有限公司", "科技集团股份有限公司",
                   "供应链管理有限公司", "医疗器械有限公司", "新能源科技有限公司", "商业管理有限公司"]
INDUSTRIES = ["制造业", "零售", "金融", "医药", "物流", "能源", "政府", "教育", "地产", "互联网"]
SCALES = ["大型", "中型", "小型"]


def _crm(employees: list[dict], user_ids: dict[str, str], rng: np.random.Generator):
    # 客户负责人：12 家归 sales，其余分给 6 个业务账号（让行级过滤后仍有数据）
    owners = (
        [user_ids["sales"]] * 12
        + [user_ids["zhangwei"]] * 4
        + [user_ids["lisi"]] * 4
        + [user_ids["wangfang"]] * 3
        + [user_ids["chenjie"]] * 3
        + [user_ids["liuyang"]] * 2
        + [user_ids["zhaomin"]] * 2
    )
    rng.shuffle(owners)

    customers: list[tuple] = []
    levels = ["A"] * 4 + ["B"] * 10 + ["C"] * 16
    rng.shuffle(levels)
    today = date(2026, 10, 20)
    for i in range(30):
        name = CUSTOMER_PREFIX[i] + CUSTOMER_CORE[i] + CUSTOMER_SUFFIX[i % len(CUSTOMER_SUFFIX)]
        industry = INDUSTRIES[i % len(INDUSTRIES)]
        scale = SCALES[i % 3]
        region = REGIONS[i % len(REGIONS)]
        level = levels[i]
        if level == "A":
            revenue = round(float(rng.uniform(600, 3200)) * 10000, -3)
            contracts = round(revenue * float(rng.uniform(0.55, 0.95)), -3)
        elif level == "B":
            revenue = round(float(rng.uniform(120, 480)) * 10000, -3)
            contracts = round(revenue * float(rng.uniform(0.4, 0.9)), -3)
        else:
            revenue = round(float(rng.uniform(20, 95)) * 10000, -3)
            contracts = round(revenue * float(rng.uniform(0.3, 0.8)), -3)
        # 3 家长期未联系（关系降温），其余 1~45 天内
        if i in (5, 17, 26):
            last = today - timedelta(days=int(rng.integers(150, 260)))
        else:
            last = today - timedelta(days=int(rng.integers(1, 46)))
        tags = [industry, region, f"{level}级"]
        if last < today - timedelta(days=120):
            tags.append("待激活")
        contact_name = SURNAMES[(i * 3) % len(SURNAMES)] + GIVEN[(i * 5) % len(GIVEN)]
        phone_head = ["138", "139", "136", "158", "186", "177"][i % 6]
        contact_phone = phone_head + "".join(str(int(rng.integers(0, 10))) for _ in range(8))
        customers.append(
            (
                f"C{i + 1:03d}",
                name,
                industry,
                scale,
                region,
                owners[i],
                level,
                revenue,
                contracts,
                datetime(last.year, last.month, last.day, int(rng.integers(9, 19)), int(rng.integers(0, 60))).strftime("%Y-%m-%d %H:%M:%S"),
                "[%s]" % ",".join(tags),
                contact_name,
                contact_phone,
            )
        )

    # 订单 80 条
    stages = ["线索", "商机", "投标", "签约", "回款"]
    stage_w = [0.14, 0.28, 0.16, 0.22, 0.20]
    orders: list[tuple] = []
    for i in range(80):
        c = customers[int(rng.integers(0, len(customers)))]
        stage = stages[int(rng.choice(len(stages), p=stage_w))]
        amount = round(float(rng.uniform(20, 900)) * 10000, -2)
        sign = today - timedelta(days=int(rng.integers(5, 520)))
        orders.append(
            (
                f"O{i + 1:03d}",
                c[0],
                c[1],
                amount,
                stage,
                sign.isoformat(),
                c[5],
            )
        )

    # 沟通记录 150 条
    channels = ["拜访", "电话", "微信", "邮件", "线上会议"]
    summaries = [
        "沟通了二期项目立项进度，客户内部预计下月完成预算评审。",
        "现场演示了工时分析大屏，客户对热力图与异常标注反馈积极。",
        "确认了数据接入范围，客户希望先接 CRM 与工单系统两张表。",
        "讨论了合同付款节点，客户财务要求验收后 60 天付款。",
        "客户反馈上一期交付的报告结论偏保守，希望增加归因分析。",
        "对接了客户信息部，确认 VPN 与账号开通时间。",
        "客户新任 CIO 到岗，安排了下周一次高层见面。",
        "沟通续约意向，客户希望把单价下调 5% 并延长服务期。",
        "排查了报表口径不一致问题，确认是部门维度映射缺失。",
        "客户提出增加移动端入口需求，需要评估排期。",
        "跟进了回款进度，客户已提交付款申请，预计本周到账。",
        "交流了 AI 数字员工在客服场景的可行性，客户愿意做 POC。",
    ]
    next_actions = [
        "下周三前发送二期方案与报价单",
        "安排技术同事做一次数据接入评估",
        "整理验收清单并与客户确认",
        "约客户 CIO 见面，准备行业案例",
        "补充归因分析章节，周五前反馈",
        "跟进合同用印进度",
        "发送 POC 计划与资源清单",
        "推进付款审批，月底前确认到账",
    ]
    logs: list[tuple] = []
    for i in range(150):
        c = customers[int(rng.integers(0, len(customers)))]
        day = today - timedelta(days=int(rng.integers(1, 200)))
        logs.append(
            (
                f"L{i + 1:03d}",
                c[0],
                c[1],
                day.isoformat(),
                channels[int(rng.integers(0, len(channels)))],
                summaries[int(rng.integers(0, len(summaries)))],
                next_actions[int(rng.integers(0, len(next_actions)))],
            )
        )
    return customers, orders, logs


# ---------------------------------------------------------------- 合同样例


CONTRACTS: list[dict] = [
    {
        "name": "云平台技术服务合同（2026）-鼎信智能",
        "clauses": [
            ("1.1", "服务内容", "乙方为甲方提供云平台运维与技术支持服务，服务范围包括 7×24 小时监控、故障响应、版本升级与容量评估。", "服务", "服务范围未附明细清单，建议补充《服务水平协议》附件。"),
            ("2.1", "合同金额", "本合同总金额为人民币 4,860,000 元（含税），分四期支付。", "付款", "金额条款清晰。"),
            ("2.2", "付款方式", "甲方在收到乙方发票后 120 日内支付相应期次款项，验收合格为付款前提。", "付款", "高风险：账期 120 天超过公司 90 天上限，且验收标准未量化。"),
            ("2.3", "验收标准", "以甲方书面确认满意为准，甲方应在收到交付物后 15 个工作日内确认。", "付款", "中风险：验收标准主观（以「满意」为准），建议改为可量化验收清单。"),
            ("3.1", "乙方违约责任", "乙方逾期交付的，每逾期一日按合同总额的千分之五支付违约金，累计不超过合同总额的 30%。", "违约", "高风险：日千分之五（年化 182%）显著高于对方，且未设对等条款。"),
            ("3.2", "甲方违约责任", "甲方逾期付款的，每逾期一日按未付金额的万分之零点五支付违约金。", "违约", "高风险：双方违约金不对等（千分之五 vs 万分之零点五，相差 100 倍）。"),
            ("3.3", "责任上限", "乙方因本合同产生的全部赔偿责任以本合同总金额为上限。", "违约", "有利条款：已设置责任上限，建议保留。"),
            ("4.1", "知识产权", "本项目实施过程中产生的全部成果及乙方既有技术、工具、模板的知识产权均归甲方所有。", "知识产权", "高风险：包含乙方既有技术，超出定制开发范围，必须删除或限定。"),
            ("4.2", "第三方组件", "乙方使用的开源组件按其许可证执行，乙方不承担因开源许可证变更导致的甲方损失。", "知识产权", "中风险：需附开源组件清单。"),
            ("5.1", "保密义务", "双方对因本合同知悉的对方商业秘密承担保密义务，保密期限为合同终止后 1 年。", "保密", "中风险：保密期限 1 年短于公司要求的 2 年。"),
            ("5.2", "个人信息", "涉及个人信息处理的，双方应另行签署数据处理附录，明确处理目的与期限。", "保密", "有利条款，建议保留并附标准附录。"),
            ("6.1", "争议解决", "因本合同发生的争议，双方应友好协商；协商不成的，提交甲方所在地人民法院诉讼解决。", "管辖", "高风险：约定甲方所在地法院（北京），我方主要履约地在上海，管辖不利。"),
            ("7.1", "自动续约", "本合同期满前 60 日内双方均未书面提出终止的，合同自动续约一年，续约期价格不变。", "续约", "中风险：自动续约+价格锁定，建议改为提前 30 天双方书面确认。"),
            ("8.1", "不可抗力", "因不可抗力导致无法履约的，受影响方应及时通知对方并提供证明，双方互不承担违约责任。", "其他", "缺少减损义务约定，建议补充。"),
        ],
    },
    {
        "name": "数据中台实施合同（二期）-远瞻集团",
        "clauses": [
            ("1.1", "项目范围", "乙方负责数据中台二期建设，包括数据接入、指标开发、可视化大屏与数据治理规范落地。", "服务", "范围较粗，建议附工作说明书（SOW）。"),
            ("2.1", "合同金额", "合同总价人民币 3,280,000 元，其中软件许可 980,000 元，实施服务 2,300,000 元。", "付款", "金额拆分清晰。"),
            ("2.2", "付款节点", "预付款 20%，上线验收后支付 50%，终验后 90 日内支付剩余 30%。", "付款", "中风险：尾款 30% 且账期 90 天，回款周期偏长。"),
            ("2.3", "变更管理", "需求变更须经双方项目经理书面确认，变更工作量超过 20 人天的另行签订补充协议。", "服务", "有利条款，建议保留。"),
            ("3.1", "交付期限", "乙方应于 2026 年 12 月 31 日前完成上线，因甲方原因导致的延期相应顺延。", "服务", "工期合理，但需明确「甲方原因」的认定方式。"),
            ("3.2", "延期违约金", "乙方延期交付的，每延期一日按合同总额的千分之一支付违约金，上限为合同总额的 10%。", "违约", "中风险：日千分之一（年化 36.5%）偏高，建议降至万分之五。"),
            ("3.3", "甲方延期责任", "甲方未按期提供数据或环境导致延期的，乙方不承担违约责任，工期相应顺延。", "违约", "有利条款。"),
            ("4.1", "知识产权归属", "定制开发部分著作权归甲方，乙方既有产品与组件（含数据集成引擎）著作权仍归乙方，甲方获得永久使用许可。", "知识产权", "有利条款：权属划分清晰，建议保留。"),
            ("4.2", "数据权属", "甲方业务数据的所有权归甲方，乙方仅在本合同目的范围内处理，不得用于训练通用模型。", "知识产权", "有利条款：明确禁止模型训练，建议保留。"),
            ("5.1", "保密期限", "双方保密义务自合同签署之日起生效，至合同终止后 3 年止。", "保密", "符合公司要求（≥2 年）。"),
            ("6.1", "争议解决", "争议提交上海仲裁委员会按其仲裁规则仲裁，仲裁裁决为终局裁决。", "管辖", "有利条款：我方所在地仲裁。"),
            ("7.1", "验收标准", "按《二期验收清单》逐项验收，未通过项乙方应在 10 个工作日内整改并复验。", "付款", "有利条款：验收可量化。"),
            ("8.1", "连带责任", "乙方对其分包商的履约行为承担连带责任，包括分包商造成的甲方一切损失。", "违约", "中风险：连带范围「一切损失」过宽，建议限定为直接损失。"),
        ],
    },
    {
        "name": "软件采购框架协议（2025-2027）-华曜科技",
        "clauses": [
            ("1.1", "框架范围", "本协议为框架性协议，具体采购以订单形式确认，订单一经双方签署即成为本协议不可分割部分。", "服务", "框架协议常见结构。"),
            ("1.2", "价格条款", "产品单价以附件《价格清单》为准，框架期内单价不得上调；采购量超过 500 套的部分享受 8 折。", "付款", "有利条款：锁价+阶梯折扣。"),
            ("2.1", "结算方式", "按季度结算，甲方于每季度结束后 30 日内核对订单并支付。", "付款", "账期合理。"),
            ("2.2", "逾期付款", "甲方逾期付款的，每逾期一日按应付未付金额的万分之三支付违约金。", "违约", "符合公司标准（万分之三）。"),
            ("2.3", "发票要求", "乙方应在收款前开具增值税专用发票，税率按国家规定执行。", "付款", "清晰。"),
            ("3.1", "交付与验收", "乙方在收到订单后 10 个工作日内交付，甲方在 5 个工作日内完成验收，逾期未提出异议视为验收合格。", "服务", "中风险：默示验收条款，建议保留异议期但明确异议方式。"),
            ("3.2", "质量保证", "乙方保证产品在交付后 12 个月内无重大缺陷，出现重大缺陷的免费修复或替换。", "服务", "质保期偏短（行业常见 12-24 个月），可谈。"),
            ("4.1", "知识产权保证", "乙方保证产品不侵犯第三方知识产权，因侵权导致的索赔由乙方承担并负责抗辩。", "知识产权", "有利条款：含抗辩义务。"),
            ("4.2", "侵权赔偿上限", "乙方的侵权赔偿责任以甲方就涉事产品已支付金额为上限。", "知识产权", "中风险：与 4.1 的抗辩义务存在冲突，建议保留抗辩、删除赔偿上限。"),
            ("5.1", "保密义务", "双方保密期限为协议终止后 2 年，保密信息不包括已公开或独立开发的信息。", "保密", "符合公司要求。"),
            ("5.2", "数据使用", "乙方不得将甲方采购数据、使用日志用于产品改进之外的目的，且需脱敏处理。", "保密", "有利条款。"),
            ("6.1", "自动续约", "本协议期满前 30 日双方未提出终止的，自动续约一年，续约期单价可上调不超过 3%。", "续约", "中风险：自动续约，建议改为书面确认续约。"),
            ("6.2", "协议终止", "任一方严重违约且在收到书面通知后 30 日内未纠正的，守约方有权单方终止协议。", "续约", "标准条款。"),
            ("7.1", "管辖法院", "争议由乙方所在地人民法院管辖。", "管辖", "高风险：乙方所在地（深圳），我方为采购方，管辖不利。"),
            ("7.2", "适用法律", "本协议适用中华人民共和国法律（不含港澳台地区法律）。", "管辖", "清晰。"),
            ("8.1", "不可抗力与情势变更", "因不可抗力不能履约的，双方互不承担违约责任；情势变更的，双方应重新协商价格与交付安排。", "其他", "较完整。"),
        ],
    },
]


# ---------------------------------------------------------------- 元数据定义


TABLE_META: list[dict] = [
    {"name": "worktime_fact", "comment": "工时事实表：区域×部门×项目×员工×工作日", "rows_from": "worktime_fact"},
    {"name": "dim_region", "comment": "区域维表：负责人、编制人数、成本中心", "rows_from": "dim_region"},
    {"name": "dim_dept", "comment": "部门维表：负责人、编制人数", "rows_from": "dim_dept"},
    {"name": "crm_customer", "comment": "CRM 客户主数据：行业、规模、等级、合同额", "rows_from": "crm_customer"},
    {"name": "crm_order", "comment": "CRM 订单/商机：金额、阶段、签约日期", "rows_from": "crm_order"},
    {"name": "crm_contact_log", "comment": "客户沟通记录：渠道、摘要、下一步", "rows_from": "crm_contact_log"},
    {"name": "contract_sample", "comment": "样例合同条款：条款号、正文、类型、风险提示", "rows_from": "contract_sample"},
]

COLUMN_META: list[dict] = [
    # worktime_fact
    {"table": "worktime_fact", "name": "id", "type": "TEXT", "comment": "工时记录 ID", "sensitive_level": "public", "category": "主键"},
    {"table": "worktime_fact", "name": "work_date", "type": "TEXT", "comment": "工作日期（YYYY-MM-DD）", "sensitive_level": "public", "category": "时间"},
    {"table": "worktime_fact", "name": "region", "type": "TEXT", "comment": "区域：华东/华南/华北/西南/东北", "sensitive_level": "public", "category": "维度"},
    {"table": "worktime_fact", "name": "dept", "type": "TEXT", "comment": "部门：研发/实施/测试/运维", "sensitive_level": "public", "category": "维度"},
    {"table": "worktime_fact", "name": "project", "type": "TEXT", "comment": "项目名称", "sensitive_level": "internal", "category": "维度"},
    {"table": "worktime_fact", "name": "employee_id", "type": "TEXT", "comment": "员工工号", "sensitive_level": "internal", "category": "维度"},
    {"table": "worktime_fact", "name": "employee_name", "type": "TEXT", "comment": "员工姓名", "sensitive_level": "internal", "category": "个人信息"},
    {"table": "worktime_fact", "name": "hours", "type": "REAL", "comment": "当日工时（小时）", "sensitive_level": "public", "category": "度量"},
    {"table": "worktime_fact", "name": "overtime_hours", "type": "REAL", "comment": "加班工时（小时）", "sensitive_level": "internal", "category": "度量"},
    {"table": "worktime_fact", "name": "billable", "type": "INTEGER", "comment": "是否可计费（1=可计费）", "sensitive_level": "public", "category": "度量"},
    {"table": "worktime_fact", "name": "delivered_tasks", "type": "INTEGER", "comment": "当日交付任务数", "sensitive_level": "public", "category": "度量"},
    {"table": "worktime_fact", "name": "defect_count", "type": "INTEGER", "comment": "当日缺陷数", "sensitive_level": "public", "category": "度量"},
    {"table": "worktime_fact", "name": "salary", "type": "REAL", "comment": "月薪（元）", "sensitive_level": "secret", "category": "薪酬"},
    # dim_region
    {"table": "dim_region", "name": "region", "type": "TEXT", "comment": "区域名称", "sensitive_level": "public", "category": "维度"},
    {"table": "dim_region", "name": "manager", "type": "TEXT", "comment": "区域负责人", "sensitive_level": "internal", "category": "组织"},
    {"table": "dim_region", "name": "headcount", "type": "INTEGER", "comment": "区域编制人数", "sensitive_level": "internal", "category": "组织"},
    {"table": "dim_region", "name": "cost_center", "type": "TEXT", "comment": "成本中心编码", "sensitive_level": "internal", "category": "财务"},
    # dim_dept
    {"table": "dim_dept", "name": "dept", "type": "TEXT", "comment": "部门名称", "sensitive_level": "public", "category": "维度"},
    {"table": "dim_dept", "name": "leader", "type": "TEXT", "comment": "部门负责人", "sensitive_level": "internal", "category": "组织"},
    {"table": "dim_dept", "name": "headcount", "type": "INTEGER", "comment": "部门编制人数", "sensitive_level": "internal", "category": "组织"},
    # crm_customer
    {"table": "crm_customer", "name": "id", "type": "TEXT", "comment": "客户 ID", "sensitive_level": "public", "category": "主键"},
    {"table": "crm_customer", "name": "name", "type": "TEXT", "comment": "客户名称", "sensitive_level": "internal", "category": "客户"},
    {"table": "crm_customer", "name": "industry", "type": "TEXT", "comment": "所属行业", "sensitive_level": "public", "category": "客户"},
    {"table": "crm_customer", "name": "scale", "type": "TEXT", "comment": "企业规模：大型/中型/小型", "sensitive_level": "public", "category": "客户"},
    {"table": "crm_customer", "name": "region", "type": "TEXT", "comment": "所属区域", "sensitive_level": "public", "category": "客户"},
    {"table": "crm_customer", "name": "owner_id", "type": "TEXT", "comment": "客户负责人（用户 ID）", "sensitive_level": "internal", "category": "客户"},
    {"table": "crm_customer", "name": "owner_name", "type": "TEXT", "comment": "客户负责人姓名", "sensitive_level": "internal", "category": "个人信息"},
    {"table": "crm_customer", "name": "level", "type": "TEXT", "comment": "客户分级：A/B/C", "sensitive_level": "internal", "category": "客户"},
    {"table": "crm_customer", "name": "annual_revenue", "type": "REAL", "comment": "客户年营收（元）", "sensitive_level": "secret", "category": "财务"},
    {"table": "crm_customer", "name": "contracts_amount", "type": "REAL", "comment": "累计合同额（元）", "sensitive_level": "secret", "category": "财务"},
    {"table": "crm_customer", "name": "last_contact_at", "type": "TEXT", "comment": "最近联系时间", "sensitive_level": "internal", "category": "客户"},
    {"table": "crm_customer", "name": "tags", "type": "TEXT", "comment": "客户标签（JSON 字符串）", "sensitive_level": "internal", "category": "客户"},
    {"table": "crm_customer", "name": "contact_name", "type": "TEXT", "comment": "客户对接人姓名", "sensitive_level": "internal", "category": "个人信息"},
    {"table": "crm_customer", "name": "contact_phone", "type": "TEXT", "comment": "客户对接人手机号", "sensitive_level": "top_secret", "category": "个人信息"},
    # crm_order
    {"table": "crm_order", "name": "id", "type": "TEXT", "comment": "订单 ID", "sensitive_level": "public", "category": "主键"},
    {"table": "crm_order", "name": "customer_id", "type": "TEXT", "comment": "客户 ID", "sensitive_level": "internal", "category": "关联"},
    {"table": "crm_order", "name": "customer_name", "type": "TEXT", "comment": "客户名称", "sensitive_level": "internal", "category": "客户"},
    {"table": "crm_order", "name": "amount", "type": "REAL", "comment": "订单金额（元）", "sensitive_level": "secret", "category": "财务"},
    {"table": "crm_order", "name": "stage", "type": "TEXT", "comment": "阶段：线索/商机/投标/签约/回款", "sensitive_level": "public", "category": "销售"},
    {"table": "crm_order", "name": "sign_date", "type": "TEXT", "comment": "签约日期", "sensitive_level": "public", "category": "时间"},
    {"table": "crm_order", "name": "owner_id", "type": "TEXT", "comment": "订单负责人（用户 ID）", "sensitive_level": "internal", "category": "销售"},
    # crm_contact_log
    {"table": "crm_contact_log", "name": "id", "type": "TEXT", "comment": "沟通记录 ID", "sensitive_level": "public", "category": "主键"},
    {"table": "crm_contact_log", "name": "customer_id", "type": "TEXT", "comment": "客户 ID", "sensitive_level": "internal", "category": "关联"},
    {"table": "crm_contact_log", "name": "customer_name", "type": "TEXT", "comment": "客户名称", "sensitive_level": "internal", "category": "客户"},
    {"table": "crm_contact_log", "name": "contact_date", "type": "TEXT", "comment": "沟通日期", "sensitive_level": "internal", "category": "时间"},
    {"table": "crm_contact_log", "name": "channel", "type": "TEXT", "comment": "沟通渠道：拜访/电话/微信/邮件/线上会议", "sensitive_level": "internal", "category": "销售"},
    {"table": "crm_contact_log", "name": "summary", "type": "TEXT", "comment": "沟通摘要", "sensitive_level": "internal", "category": "销售"},
    {"table": "crm_contact_log", "name": "next_action", "type": "TEXT", "comment": "下一步动作", "sensitive_level": "internal", "category": "销售"},
    # contract_sample
    {"table": "contract_sample", "name": "id", "type": "TEXT", "comment": "条款 ID", "sensitive_level": "public", "category": "主键"},
    {"table": "contract_sample", "name": "contract_name", "type": "TEXT", "comment": "合同名称", "sensitive_level": "internal", "category": "合同"},
    {"table": "contract_sample", "name": "clause_no", "type": "TEXT", "comment": "条款号", "sensitive_level": "public", "category": "合同"},
    {"table": "contract_sample", "name": "title", "type": "TEXT", "comment": "条款标题", "sensitive_level": "public", "category": "合同"},
    {"table": "contract_sample", "name": "content", "type": "TEXT", "comment": "条款正文", "sensitive_level": "internal", "category": "合同"},
    {"table": "contract_sample", "name": "category", "type": "TEXT", "comment": "条款类型：付款/违约/管辖/保密/知识产权/续约/其他", "sensitive_level": "public", "category": "合同"},
    {"table": "contract_sample", "name": "risk_hint", "type": "TEXT", "comment": "风险提示（人工标注）", "sensitive_level": "internal", "category": "合同"},
]


METRICS: list[dict] = [
    {
        "code": "avg_hours",
        "name": "人均工时",
        "description": "统计周期内每位员工平均投入工时（含加班），按自然日合计。",
        "expression": "SELECT ROUND(SUM(hours) / COUNT(DISTINCT employee_id), 2) AS avg_hours FROM worktime_fact",
    },
    {
        "code": "utilization_rate",
        "name": "工时利用率",
        "description": "可计费工时占总工时的比例，反映人力投入的商业化程度。",
        "expression": "SELECT ROUND(AVG(billable) * 100, 2) AS utilization_rate FROM worktime_fact",
    },
    {
        "code": "overtime_task_rate",
        "name": "超时工单率",
        "description": "加班工时占总工时的比例，超过 12% 需预警。",
        "expression": "SELECT ROUND(SUM(overtime_hours) * 100.0 / SUM(hours), 2) AS overtime_rate FROM worktime_fact",
    },
    {
        "code": "region_output",
        "name": "区域人均产出",
        "description": "区域维度下人均交付任务数，用于跨区域人效对比。",
        "expression": "SELECT region, ROUND(SUM(delivered_tasks) * 1.0 / COUNT(DISTINCT employee_id), 2) AS output_per_head FROM worktime_fact GROUP BY region",
    },
    {
        "code": "customer_contract_amount",
        "name": "客户合同额",
        "description": "客户累计合同额合计（按客户负责人归属），口径为签约金额而非回款。",
        "expression": "SELECT ROUND(SUM(contracts_amount), 2) AS total_contract_amount FROM crm_customer",
    },
    {
        "code": "collection_rate",
        "name": "回款率",
        "description": "已回款订单金额占签约订单金额的比例。",
        "expression": "SELECT ROUND(SUM(CASE WHEN stage = '回款' THEN amount ELSE 0 END) * 100.0 / SUM(amount), 2) AS collection_rate FROM crm_order",
    },
    {
        "code": "contract_risk_clauses",
        "name": "合同风险条款数",
        "description": "样例合同中标注为高风险的条款数量，用于合同审查类场景。",
        "expression": "SELECT COUNT(*) AS high_risk_clauses FROM contract_sample WHERE risk_hint LIKE '高风险%'",
    },
]


# ---------------------------------------------------------------- 建库


DDL = """
CREATE TABLE worktime_fact (
  id TEXT PRIMARY KEY, work_date TEXT NOT NULL, region TEXT NOT NULL, dept TEXT NOT NULL,
  project TEXT NOT NULL, employee_id TEXT NOT NULL, employee_name TEXT NOT NULL,
  hours REAL NOT NULL, overtime_hours REAL NOT NULL, billable INTEGER NOT NULL,
  delivered_tasks INTEGER NOT NULL, defect_count INTEGER NOT NULL, salary REAL NOT NULL
);
CREATE TABLE dim_region (region TEXT PRIMARY KEY, manager TEXT, headcount INTEGER, cost_center TEXT);
CREATE TABLE dim_dept (dept TEXT PRIMARY KEY, leader TEXT, headcount INTEGER);
CREATE TABLE crm_customer (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, industry TEXT, scale TEXT, region TEXT,
  owner_id TEXT, owner_name TEXT, level TEXT, annual_revenue REAL, contracts_amount REAL,
  last_contact_at TEXT, tags TEXT, contact_name TEXT, contact_phone TEXT
);
CREATE TABLE crm_order (
  id TEXT PRIMARY KEY, customer_id TEXT, customer_name TEXT, amount REAL, stage TEXT,
  sign_date TEXT, owner_id TEXT
);
CREATE TABLE crm_contact_log (
  id TEXT PRIMARY KEY, customer_id TEXT, customer_name TEXT, contact_date TEXT,
  channel TEXT, summary TEXT, next_action TEXT
);
CREATE TABLE contract_sample (
  id TEXT PRIMARY KEY, contract_name TEXT, clause_no TEXT, title TEXT,
  content TEXT, category TEXT, risk_hint TEXT
);
CREATE INDEX IF NOT EXISTS ix_wt_date ON worktime_fact(work_date);
CREATE INDEX IF NOT EXISTS ix_wt_region ON worktime_fact(region, dept);
CREATE INDEX IF NOT EXISTS ix_wt_emp ON worktime_fact(employee_id);
CREATE INDEX IF NOT EXISTS ix_crm_owner ON crm_customer(owner_id);
CREATE INDEX IF NOT EXISTS ix_order_customer ON crm_order(customer_id);
CREATE INDEX IF NOT EXISTS ix_log_customer ON crm_contact_log(customer_id);
CREATE INDEX IF NOT EXISTS ix_contract_name ON contract_sample(contract_name);
"""


def _insert_many(conn: sqlite3.Connection, sql: str, rows: list[tuple], batch: int = 5000) -> None:
    for i in range(0, len(rows), batch):
        conn.executemany(sql, rows[i:i + batch])


def build_demo_db(path: Path, *, user_ids: dict[str, str] | None = None,
                  owner_names: dict[str, str] | None = None,
                  force: bool = False) -> dict:
    """生成 demo.db，返回各表行数统计。已存在且非 force 时直接返回统计。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    user_ids = user_ids or {}
    owner_names = owner_names or {}

    if path.exists() and not force:
        try:
            with sqlite3.connect(path) as chk:
                n = chk.execute("SELECT COUNT(*) FROM worktime_fact").fetchone()[0]
            if n:
                return stats_of(path)
        except Exception:
            pass                                   # 文件损坏 → 重建

    if path.exists():
        path.unlink()

    rng = np.random.default_rng(SEED + 1)
    employees = _employees()
    fact_rows, days = build_fact(employees)

    # 用户 id → 姓名，作为客户负责人名字
    customers, orders, logs = _crm(employees, user_ids or {}, rng)

    regions = []
    for r in REGIONS:
        hc = sum(1 for e in employees if e["region"] == r)
        regions.append((r, REGION_MANAGER[r], hc, REGION_CC[r]))
    depts = []
    for d in DEPTS:
        hc = sum(1 for e in employees if e["dept"] == d)
        depts.append((d, DEPT_LEADER[d], hc))

    clauses: list[tuple] = []
    for ci, contract in enumerate(CONTRACTS, start=1):
        for gi, (no, title, content, category, hint) in enumerate(contract["clauses"], start=1):
            clauses.append(
                (
                    f"CT{ci:02d}{gi:02d}",
                    contract["name"],
                    no,
                    title,
                    content,
                    category,
                    hint,
                )
            )

    conn = sqlite3.connect(path)
    try:
        conn.executescript(DDL)
        _insert_many(
            conn,
            "INSERT INTO worktime_fact (id, work_date, region, dept, project, employee_id, employee_name, "
            "hours, overtime_hours, billable, delivered_tasks, defect_count, salary) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            fact_rows,
        )
        conn.executemany("INSERT INTO dim_region VALUES (?,?,?,?)", regions)
        conn.executemany("INSERT INTO dim_dept VALUES (?,?,?)", depts)
        conn.executemany(
            "INSERT INTO crm_customer (id, name, industry, scale, region, owner_id, owner_name, level, "
            "annual_revenue, contracts_amount, last_contact_at, tags, contact_name, contact_phone) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    c[0], c[1], c[2], c[3], c[4], c[5],
                    owner_names.get(c[5], c[5]),
                    c[6], c[7], c[8], c[9], c[10], c[11], c[12],
                )
                for c in customers
            ],
        )
        conn.executemany(
            "INSERT INTO crm_order (id, customer_id, customer_name, amount, stage, sign_date, owner_id) "
            "VALUES (?,?,?,?,?,?,?)",
            orders,
        )
        conn.executemany(
            "INSERT INTO crm_contact_log (id, customer_id, customer_name, contact_date, channel, summary, next_action) "
            "VALUES (?,?,?,?,?,?,?)",
            logs,
        )
        conn.executemany(
            "INSERT INTO contract_sample (id, contract_name, clause_no, title, content, category, risk_hint) "
            "VALUES (?,?,?,?,?,?,?)",
            clauses,
        )
        conn.commit()
    finally:
        conn.close()

    out = stats_of(path)
    out["days"] = len(days)
    out["employees"] = len(employees)
    return out


def stats_of(path: Path) -> dict:
    tables = ["worktime_fact", "dim_region", "dim_dept", "crm_customer", "crm_order",
              "crm_contact_log", "contract_sample"]
    out: dict = {}
    with sqlite3.connect(path) as conn:
        for t in tables:
            try:
                out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception:
                out[t] = 0
    return out


__all__ = [
    "build_demo_db",
    "stats_of",
    "TABLE_META",
    "COLUMN_META",
    "METRICS",
    "REGIONS",
    "DEPTS",
    "PROJECTS",
    "CONTRACTS",
]
