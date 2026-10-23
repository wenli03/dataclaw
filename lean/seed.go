package main

import (
	"fmt"
	"math/rand"
	"os"
	"time"
)

// EnsureSeed 幂等：users 非空即跳过。首次启动会建演示数据（app.db + demo.db）。
func (a *App) EnsureSeed() error {
	if count(a.db, "user") > 0 {
		return nil
	}
	pass := "123456"
	users := []User{
		{ID: "u_admin", Username: "admin", Pwd: "admin123", Name: "张明", Role: "platform_admin", Dept: "数智事业部", Title: "事业部负责人", Avatar: "张明"},
		{ID: "u_analyst", Username: "analyst", Pwd: pass, Name: "林知微", Role: "member", Dept: "数据分析组", Title: "高级数据分析师", Avatar: "林知微"},
		{ID: "u_sales", Username: "sales", Pwd: pass, Name: "程景舟", Role: "member", Dept: "销售部", Title: "销售经理", Avatar: "程景舟"},
		{ID: "u_legal", Username: "legal", Pwd: pass, Name: "顾守正", Role: "member", Dept: "法务部", Title: "法务顾问", Avatar: "顾守正"},
		{ID: "u_dev", Username: "dev", Pwd: pass, Name: "周牧", Role: "member", Dept: "数据平台组", Title: "数据开发", Avatar: "周牧"},
		{ID: "u_ops", Username: "ops", Pwd: pass, Name: "许澄", Role: "member", Dept: "运营部", Title: "运营经理", Avatar: "许澄"},
	}
	for _, u := range users {
		if err := put(a.db, "user", u.ID, u); err != nil {
			return err
		}
	}

	templates := []Template{
		{ID: "t_analyst", Name: "数据分析师", Role: "数据分析师", Avatar: "林知微", Desc: "把复杂数据变成可汇报的结论与大屏",
			Soul: "你是林知微，数智事业部的资深数据分析师。你用数据讲清业务问题：先给结论，再给证据，最后给行动建议。\n\n核心原则：数字必须来自真实查询；口径不清先说明；异常要给出可能原因；不编造数据。\n\n输出规范：结论 3 条以内，配 KPI 与图表，附数据来源与权限说明。",
			Skills: []string{"sk_chatbi", "sk_dashboard", "sk_report", "sk_knowledge"}},
		{ID: "t_contract", Name: "合同审查员", Role: "合同审查与合规助手", Avatar: "顾守正", Desc: "按企业规则库逐条审查合同并输出修订版",
			Soul: "你是顾守正，企业法务顾问。你按公司标准合同规则逐条审查，标出风险等级并给出可直接谈判的修订建议。\n\n核心原则：只做初审提效，结论供法务复核；每条风险必须引用原文条款；高风险必须标注。\n\n输出规范：风险清单（条款/问题/建议/等级）+ 修订版文件。",
			Skills: []string{"sk_contract", "sk_knowledge"}},
		{ID: "t_sales", Name: "客户情报员", Role: "销售情报与拜访助手", Avatar: "程景舟", Desc: "把 CRM 与外部信息整合成拜访指南",
			Soul: "你是程景舟，销售情报助手。你帮销售在拜访前 2 分钟拿到客户 360、需求预判与话术。\n\n核心原则：只用你有权限看到的客户数据；外部信息标注来源；没有数据就说没有。\n\n输出规范：客户画像 + 3 条拜访前要做的事 + 3 段话术。",
			Skills: []string{"sk_sales", "sk_knowledge"}},
		{ID: "t_ops", Name: "运营分析助手", Role: "运营数据分析师", Avatar: "许澄", Desc: "看工时、算人效、出大屏",
			Soul: "你是运营分析助手，负责工时与人效分析。你会先说结论，再给口径，最后给可执行建议。\n\n核心原则：一切数字来自真实查询；敏感字段按权限脱敏；异常要标注判定方法。",
			Skills: []string{"sk_chatbi", "sk_dashboard", "sk_report"}},
	}
	for _, t := range templates {
		_ = put(a.db, "template", t.ID, t)
	}

	for _, s := range seedSkills() {
		_ = put(a.db, "skill", s.ID, s)
	}

	agents := []Agent{
		{ID: "ag_ops", Name: "社媒排期官", Role: "DataClaw-Scheduler", Avatar: "社媒", Desc: "统一管理社媒内容排期：选题、素材、发布节奏与复盘。", Version: 1, Skills: []string{"sk_knowledge", "sk_report"},
			Soul: "你是社媒排期官，负责内容排期与复盘。按周产出排期表，标注选题理由与预期指标。"},
		{ID: "ag_data", Name: "数据分析师 2", Role: "DataClaw-Data", Avatar: "数据", Desc: "公共分析员工：问数、做图、写报告三件事，数据权限继承自绑定用户。", Version: 1, Skills: []string{"sk_chatbi", "sk_dashboard", "sk_report"},
			Soul: "你是公共数据分析员工，服务多个业务用户。先确认口径，再执行查询；产出必须可复现。"},
	}
	for _, g := range agents {
		_ = put(a.db, "agent", g.ID, g)
	}

	emps := []Employee{
		{ID: "e_admin", Owner: "u_admin", Name: "运营数据分析师", Role: "运营数据分析师", Avatar: "运营", Skills: []string{"sk_chatbi", "sk_dashboard", "sk_report", "sk_knowledge"}, Memory: true, Created: now(),
			Soul: "你是运营分析助手，可以直查工时、算人效、出大屏。先给结论，再给口径与权限说明。"},
		{ID: "e_analyst1", Owner: "u_analyst", Name: "工时效率分析师", Role: "数据分析师", Avatar: "工时", Skills: []string{"sk_chatbi", "sk_dashboard", "sk_report"}, Memory: true, Created: now(),
			Soul: "你是工时效率分析师。分析维度默认「区域 × 月份」，口径：hours 为计费工时含加班。"},
		{ID: "e_analyst2", Owner: "u_analyst", Name: "数据分析师 2（副本）", Role: "公共分析员工", Avatar: "数据", AgentID: "ag_data", Skills: []string{"sk_chatbi", "sk_dashboard", "sk_report"}, Memory: true, Created: now(),
			Soul: "你是公共数据分析员工的个人副本，记忆与技能可独立调整。"},
		{ID: "e_sales", Owner: "u_sales", Name: "客户情报员", Role: "销售情报与拜访助手", Avatar: "客户", Skills: []string{"sk_sales", "sk_knowledge"}, Memory: true, Created: now(),
			Soul: "你是销售情报助手。只用当前账号有权限的客户数据，外部信息标注来源。"},
		{ID: "e_legal", Owner: "u_legal", Name: "合同审查助理", Role: "合同审查与合规助手", Avatar: "合同", Skills: []string{"sk_contract", "sk_knowledge"}, Memory: true, Created: now(),
			Soul: "你是合同审查助理。按公司规则库初审，输出风险清单与修订版 docx，最终由法务复核。"},
	}
	for _, e := range emps {
		_ = put(a.db, "employee", e.ID, e)
	}
	_ = put(a.db, "assignment", "as_1", Assignment{AgentID: "ag_data", UserID: "u_analyst", EmpID: "e_analyst2"})

	policies := []Policy{
		{ID: "p1", Who: "user:u_admin", Resource: "table:worktime_fact", Action: "allow", Note: "管理员：工时表全量"},
		{ID: "p2", Who: "user:u_admin", Resource: "table:crm_customer", Action: "allow", Note: "管理员：客户表全量"},
		{ID: "p3", Who: "user:u_admin", Resource: "table:contract_clause", Action: "allow", Note: "管理员：合同表全量"},
		{ID: "p4", Who: "user:u_analyst", Resource: "table:worktime_fact", Action: "allow", Note: "分析师：工时分析需要"},
		{ID: "p5", Who: "user:u_analyst", Resource: "column:worktime_fact.salary", Action: "allow", Mask: "mask", Note: "薪资强制掩码"},
		{ID: "p6", Who: "user:u_analyst", Resource: "column:worktime_fact.employee_name", Action: "allow", Mask: "hash", Note: "姓名哈希化"},
		{ID: "p7", Who: "user:u_analyst", Resource: "table:crm_customer", Action: "deny", Note: "分析师不开通客户主数据"},
		{ID: "p8", Who: "user:u_sales", Resource: "table:crm_customer", Action: "allow", RowFilter: "owner_id='u_sales'", Note: "销售只见自己名下客户"},
		{ID: "p9", Who: "user:u_sales", Resource: "table:contract_clause", Action: "deny", Note: "合同条款仅法务可读"},
		{ID: "p10", Who: "user:u_legal", Resource: "table:contract_clause", Action: "allow", Note: "法务：合同审查"},
		{ID: "p11", Who: "user:u_legal", Resource: "table:crm_customer", Action: "allow", Note: "法务：合同主体核对"},
		{ID: "p12", Who: "role:member", Resource: "table:contract_clause", Action: "deny", Note: "角色兜底：普通成员不可读合同"},
	}
	for _, p := range policies {
		_ = put(a.db, "policy", p.ID, p)
	}

	for _, d := range seedDocs() {
		_ = put(a.db, "doc", d.ID, d)
	}
	seedAudit(a, users)

	if err := a.seedAnalytics(); err != nil {
		return err
	}
	return nil
}

func seedSkills() []Skill {
	return []Skill{
		{ID: "sk_chatbi", Name: "chatbi", Desc: "用自然语言查询企业数据仓：自动改写 SQL，并遵守列级脱敏与行级权限。", Category: "数据", Risk: "medium",
			Content: "---\nname: chatbi\ndescription: 自然语言问数；自动生成 SQL 并经过数据权限网关\n---\n\n# ChatBI 数据查询技能\n\n## 能力边界（仅三种）\n| 能力 | 说明 |\n|---|---|\n| list-tables | 列出你有权限访问的表 |\n| describe-table | 指定表的字段与敏感级别 |\n| ask | 自然语言 → SQL → 网关校验 → 执行 |\n\n## 首选工作流\n1. 先 list-tables 确认有没有相关数据；\n2. describe-table 确认口径与敏感列；\n3. ask 执行，回报行数与已脱敏列。\n\n## 禁止事项\n- 不得绕过网关直接连库；\n- 不得把脱敏列还原成明文；\n- 不得执行 INSERT/UPDATE/DELETE。"},
		{ID: "sk_dashboard", Name: "dashboard", Desc: "把查询结果变成可交付的 ECharts 大屏：KPI + 多图联动 + 异常标注。", Category: "可视化", Risk: "low",
			Content: "---\nname: dashboard\ndescription: 查询结果 → ECharts 大屏\n---\n\n# 可视化大屏技能\n\n## 输出规范\n- 3–5 个 KPI（含环比/同比与解释）；\n- 2–4 张图：热力图（二维对比）、柱状（排名）、折线（趋势）、饼图（占比）；\n- 至少 1 条异常洞察（判定方法必须写出来）。\n\n## 禁止事项\n- 图表里不得出现未脱敏的敏感字段；\n- 不得编造未查询出的数据点。"},
		{ID: "sk_report", Name: "report", Desc: "把洞察写成结论先行的 Markdown 深度报告，可直接用于汇报。", Category: "文档", Risk: "low",
			Content: "---\nname: report\ndescription: 结论先行的深度分析报告\n---\n\n# 深度报告技能\n\n## 结构\n1. 核心结论（3 条以内）；\n2. 关键指标表；\n3. 归因分析；\n4. 行动建议（含责任方与时间）。\n\n## 规范\n- 每个数字标注来源与口径；\n- 权限受限处必须写明。"},
		{ID: "sk_contract", Name: "contract", Desc: "按企业规则库审查合同：风险分级 + 逐条修订建议 + 带修订痕迹的 docx。", Category: "法务", Risk: "high",
			Content: "---\nname: contract\ndescription: 合同初审；输出风险清单与修订版 docx\n---\n\n# 合同智能审查技能\n\n## 规则库（12 类，节选）\n| 类别 | 判定 | 风险 |\n|---|---|---|\n| 付款账期 | > 60 天 | 高 |\n| 违约责任 | 单方约束/比例不对等 | 高 |\n| 管辖法院 | 非被告所在地/我方所在地 | 高 |\n| 知识产权 | 归属约定模糊 | 高 |\n| 保密期限 | < 3 年 | 中 |\n| 自动续约 | 未设书面确认 | 中 |\n\n## 禁止事项\n- 不得替代法务出具最终意见；\n- 不得改动合同实质条款，只做建议。"},
		{ID: "sk_sales", Name: "sales", Desc: "整合 CRM 与外部信息，生成客户 360 与拜访指南。", Category: "销售", Risk: "medium",
			Content: "---\nname: sales\ndescription: 拜访前情报准备\n---\n\n# 销售情报技能\n\n## 工作流\n1. 取客户 360（订单、金额、最近沟通）；\n2. 补充外部信息（标注来源/是否模拟）；\n3. 给出需求预判与 3 段话术。\n\n## 禁止事项\n- 不得查看非本人负责的客户；\n- 不得输出未标注来源的外部信息。"},
		{ID: "sk_knowledge", Name: "knowledge", Desc: "在企业知识库中检索制度、规则与方法论，遵守文档权限。", Category: "知识", Risk: "low",
			Content: "---\nname: knowledge\ndescription: 企业知识库检索（BM25）\n---\n\n# 知识检索技能\n\n- 输入：查询词；输出：片段 + 出处 + 相关度。\n- 只返回当前用户可读的文档。\n- 命中不足时明确说\"知识库中没有\"，不要编造。"},
	}
}

func seedDocs() []Doc {
	return []Doc{
		{ID: "d_rule", Name: "标准合同审查规则 V3", Type: "doc", Text: "合同审查规则：付款账期不得超过 60 天，超过属于高风险；违约金应双方对等，日利率不超过万分之五，累计不超过合同总额 10%；管辖法院应为被告所在地或我方所在地；知识产权需明确定制交付物归甲方、通用能力归乙方；保密期限不少于 3 年；自动续约必须双方书面确认；不得约定无限连带责任；单方解除权需对等。"},
		{ID: "d_sales", Name: "销售拜访方法论", Type: "doc", Text: "拜访三步法：第一步复盘合作底账（历史订单、合同额、最近沟通、应收）；第二步带着假设去（基于行业与规模推测痛点，准备 2-3 个验证问题）；第三步按痛点确认→价值假设→小范围试点推进，结束前确认下次沟通时间与验收指标。话术要具体到客户的业务指标，不要泛泛而谈。"},
		{ID: "d_worktime", Name: "工时管理规范", Type: "doc", Text: "工时数据口径：hours 为计费工时含加班；overtime 为每日超过 8 小时部分；tasks 为通过验收的交付任务数；defects 为验收后 30 天内缺陷数；salary 为月度人力成本，属机密级字段，任何分析产出都必须脱敏；人效 = tasks / hours，按区域与月份对比。"},
	}
}

func seedAudit(a *App, users []User) {
	acts := []struct{ action, target, risk, result string }{
		{"login", "admin", "low", "success"}, {"chat", "运营数据分析师", "low", "success"},
		{"tool_call", "chatbi.ask", "low", "success"}, {"sql_query", "worktime_fact", "low", "success"},
		{"sql_query", "crm_customer", "high", "denied"}, {"export", "工时分析报告", "medium", "success"},
		{"skill_install", "chatbi", "low", "success"}, {"doc_read", "标准合同审查规则 V3", "low", "success"},
		{"hitl_approval", "导出修订版合同", "high", "success"}, {"agent_assign", "数据分析师 2", "medium", "success"},
	}
	base := time.Now().Add(-72 * time.Hour)
	for i := 0; i < 40; i++ {
		x := acts[i%len(acts)]
		u := users[i%len(users)]
		_ = put(a.db, "audit", fmt.Sprintf("au_seed_%02d", i), Audit{
			ID: fmt.Sprintf("au_seed_%02d", i), Ts: base.Add(time.Duration(i*47) * time.Minute).Format(time.RFC3339),
			Actor: u.ID, Action: x.action, Target: x.target, Risk: x.risk, Result: x.result,
			Detail: map[string]any{"seed": true},
		})
	}
}

// seedAnalytics 生成 demo.db：工时事实 / 客户 / 合同条款。真实表 + 真实 SQL。
func (a *App) seedAnalytics() error {
	if _, err := os.Stat(a.path("demo.db")); err == nil {
		return nil // 已存在
	}
	schema := `
CREATE TABLE worktime_fact(id INTEGER PRIMARY KEY, work_date TEXT, region TEXT, dept TEXT,
  employee_name TEXT, hours REAL, overtime REAL, tasks INT, defects INT, salary REAL);
CREATE TABLE crm_customer(id TEXT PRIMARY KEY, name TEXT, industry TEXT, scale TEXT, region TEXT,
  level TEXT, owner_id TEXT, orders INT, amount REAL, last_contact TEXT, summary TEXT);
CREATE TABLE contract_clause(id INTEGER PRIMARY KEY, contract TEXT, clause TEXT, title TEXT, text TEXT);
CREATE INDEX ix_wt ON worktime_fact(region, work_date);
CREATE INDEX ix_crm ON crm_customer(owner_id);`
	if _, err := a.ana.Exec(schema); err != nil {
		return err
	}

	rnd := rand.New(rand.NewSource(42))
	regions := []string{"华东", "华南", "华北", "西南", "东北"}
	depts := []string{"研发", "实施", "测试", "运维"}
	names := []string{"张伟", "李思", "王芳", "陈杰", "刘洋", "赵敏", "周牧", "许澄", "程景舟", "林知微", "顾守正", "孙悦"}
	base := map[string]float64{"华东": 8.4, "华南": 8.1, "华北": 7.9, "西南": 7.6, "东北": 6.9}

	tx, _ := a.ana.Begin()
	stmt, _ := tx.Prepare(`INSERT INTO worktime_fact(work_date,region,dept,employee_name,hours,overtime,tasks,defects,salary) VALUES(?,?,?,?,?,?,?,?,?)`)
	start := time.Date(2025, 4, 1, 0, 0, 0, 0, time.UTC)
	for d := 0; d < 548; d++ { // 18 个月
		day := start.AddDate(0, 0, d)
		if day.Weekday() == time.Saturday || day.Weekday() == time.Sunday {
			continue
		}
		for _, rg := range regions {
			for _, dp := range depts {
				for k := 0; k < 4; k++ { // 每区域/部门 4 人
					name := names[(len(rg)+len(dp)+k)%len(names)]
					h := base[rg] + rnd.NormFloat64()*0.9
					if day.Month() == 6 { // 6 月加班集中
						h += 1.4
					}
					if day.Year() == 2026 && day.Month() >= 7 {
						h -= 0.5 // Q3 回落
					}
					ot := 0.0
					if h > 8.0 {
						ot = (h - 8.0) * 0.8
					}
					tasks := int(h/2.1) + rnd.Intn(2)
					defects := 0
					if rnd.Intn(12) == 0 {
						defects = 1
					}
					if rg == "东北" {
						tasks = int(h/3.1) + rnd.Intn(1) // 人效异常偏低
						if rnd.Intn(6) == 0 {
							defects = 1
						}
					}
					salary := 18000 + rnd.Float64()*12000
					stmt.Exec(day.Format("2006-01-02"), rg, dp, name, round1(h), round1(ot), tasks, defects, round1(salary))
				}
			}
		}
	}
	stmt.Close()

	customers := [][]any{
		{"c01", "重庆嘉禾新能源科技有限公司", "物流", "中型", "西南", "A", "u_sales", 3, 17363000.0, "2026-10-03", "跟进回款，已提交付款申请"},
		{"c02", "上海星海智能装备有限公司", "制造", "大型", "华东", "A", "u_sales", 2, 9850000.0, "2026-09-21", "技术方案待确认"},
		{"c03", "深圳前海云智数据服务有限公司", "TMT", "中型", "华南", "B", "u_sales", 1, 4200000.0, "2026-08-30", "等待预算审批"},
		{"c04", "北京华信医疗器械集团", "医疗", "大型", "华北", "A", "u_zhangwei", 4, 21500000.0, "2026-10-01", "年度框架协议续签"},
		{"c05", "杭州数联供应链科技有限公司", "物流", "小型", "华东", "C", "u_zhangwei", 1, 860000.0, "2026-07-12", "首次接触"},
		{"c06", "成都锦江建设集团", "建筑", "大型", "西南", "B", "u_lisi", 2, 6700000.0, "2026-09-05", "招标阶段"},
		{"c07", "苏州精工自动化有限公司", "制造", "中型", "华东", "B", "u_lisi", 3, 5300000.0, "2026-10-08", "二期扩容"},
		{"c08", "广州南沙港务集团", "港口", "大型", "华南", "A", "u_wangfang", 2, 12400000.0, "2026-09-28", "验收中"},
	}
	for _, c := range customers {
		tx.Exec(`INSERT OR REPLACE INTO crm_customer VALUES(?,?,?,?,?,?,?,?,?,?,?)`, c...)
	}

	clauses := [][]any{
		{1, "云平台技术服务合同（2026）-鼎信智能", "2.2", "付款账期过长", "甲方应于服务交付后 120 日内支付服务费，逾期未付的，乙方可暂停服务。"},
		{2, "云平台技术服务合同（2026）-鼎信智能", "3.1", "违约责任不对等", "乙方逾期交付的，每日按合同总额的千分之五向甲方支付违约金；甲方逾期付款的，不承担违约责任。"},
		{3, "云平台技术服务合同（2026）-鼎信智能", "3.2", "违约金比例过高", "任何一方违约，均应向对方支付合同总额 30% 的违约金。"},
		{4, "云平台技术服务合同（2026）-鼎信智能", "4.1", "知识产权归属模糊", "服务过程中产生的知识产权归双方共同所有，具体行使方式另行协商。"},
		{5, "云平台技术服务合同（2026）-鼎信智能", "5.1", "保密期限过短", "双方对合作中知悉的商业秘密保密期限为 1 年，自合同终止之日起算。"},
		{6, "云平台技术服务合同（2026）-鼎信智能", "6.1", "自动续约条款", "本合同期满后自动续约一年，除一方提前 30 日书面通知不再续约。"},
		{7, "云平台技术服务合同（2026）-鼎信智能", "6.2", "管辖法院不利", "因本合同发生争议，由甲方所在地北京市朝阳区人民法院管辖。"},
		{8, "云平台技术服务合同（2026）-鼎信智能", "7.1", "无限连带责任", "乙方对其关联方及分包方的一切行为承担无限连带责任。"},
		{9, "云平台技术服务合同（2026）-鼎信智能", "7.2", "单方解除权", "甲方有权随时无理由解除本合同，乙方无权单方解除。"},
		{10, "云平台技术服务合同（2026）-鼎信智能", "8.1", "验收标准不明确", "服务是否验收合格以甲方书面确认为准，甲方未在 7 日内反馈的视为验收通过。"},
		{11, "云平台技术服务合同（2026）-鼎信智能", "9.1", "服务范围不明确", "乙方提供云平台相关技术服务，具体内容以双方另行确认为准。"},
		{12, "云平台技术服务合同（2026）-鼎信智能", "9.2", "数据安全责任缺失", "乙方应保障数据安全。"},
	}
	for _, c := range clauses {
		tx.Exec(`INSERT OR REPLACE INTO contract_clause VALUES(?,?,?,?,?)`, c...)
	}
	return tx.Commit()
}

func round1(f float64) float64 { return float64(int(f*10+0.5)) / 10 }

func ensureDir(p string) error { return os.MkdirAll(p, 0o755) }
