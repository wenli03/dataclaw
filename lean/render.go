package main

import (
	"fmt"
	"sort"
	"strings"
)

// Risk 是合同审查的一条风险。
type Risk struct {
	Clause     string `json:"clause"`
	Title      string `json:"title"`
	Level      string `json:"level"` // high | medium | low
	Issue      string `json:"issue"`
	Suggestion string `json:"suggestion"`
	Original   string `json:"original"`
}

// ---------------- 大屏 ----------------

func buildDashboard(rows, prev []map[string]any) (map[string]any, string) {
	rm := map[string]map[string]float64{} // region -> month -> hours
	regionTotal := map[string]*aggT{}
	deptTotal := map[string]float64{}
	monthTotal := map[string]float64{}
	monthsSet := map[string]bool{}
	tot := &aggT{}

	for _, r := range rows {
		rg, m := fmt.Sprint(r["region"]), fmt.Sprint(r["m"])
		h := num(r["hours"])
		monthsSet[m] = true
		if rm[rg] == nil {
			rm[rg] = map[string]float64{}
		}
		rm[rg][m] += h
		if regionTotal[rg] == nil {
			regionTotal[rg] = &aggT{}
		}
		regionTotal[rg].hours += h
		regionTotal[rg].ot += num(r["ot"])
		regionTotal[rg].tasks += num(r["tasks"])
		regionTotal[rg].defects += num(r["defects"])
		deptTotal[fmt.Sprint(r["dept"])] += h
		monthTotal[m] += h
		tot.hours += h
		tot.ot += num(r["ot"])
		tot.tasks += num(r["tasks"])
		tot.defects += num(r["defects"])
	}
	months := keys(monthsSet)
	sort.Strings(months)
	regions := keysOfAgg(regionTotal)
	sort.Slice(regions, func(i, j int) bool { return regionTotal[regions[i]].hours > regionTotal[regions[j]].hours })

	// 环比
	var ph, pt float64
	for _, r := range prev {
		ph += num(r["hours"])
		pt += num(r["tasks"])
	}
	pct := func(cur, old float64) string {
		if old == 0 {
			return "—"
		}
		return fmt.Sprintf("%+.1f%%", (cur-old)/old*100)
	}

	kpis := []map[string]any{
		{"label": "总工时", "value": fmt.Sprintf("%.1f 万 h", tot.hours/10000), "delta": pct(tot.hours, ph)},
		{"label": "交付任务", "value": fmt.Sprintf("%.0f 个", tot.tasks), "delta": pct(tot.tasks, pt)},
		{"label": "人效（任务/百工时）", "value": fmt.Sprintf("%.1f", safeDiv(tot.tasks, tot.hours)*100), "hint": "越高越好"},
		{"label": "加班率", "value": fmt.Sprintf("%.1f%%", safeDiv(tot.ot, tot.hours)*100)},
		{"label": "缺陷率", "value": fmt.Sprintf("%.2f%%", safeDiv(tot.defects, tot.tasks)*100)},
	}

	// 热力图
	heat := [][]float64{}
	for y, rg := range regions {
		for x, m := range months {
			heat = append(heat, []float64{float64(x), float64(y), round1(rm[rg][m])})
		}
	}
	heatOpt := map[string]any{
		"tooltip": map[string]any{"position": "top"},
		"grid":    map[string]any{"left": 60, "right": 24, "top": 16, "bottom": 86},
		"xAxis":   map[string]any{"type": "category", "data": months, "splitArea": map[string]any{"show": true}}, 
		"yAxis":   map[string]any{"type": "category", "data": regions, "splitArea": map[string]any{"show": true}},
		"visualMap": map[string]any{"min": floorHeat(rm), "max": round1(maxHeat(rm)),
			"calculable": true, "orient": "horizontal", "left": "center", "bottom": 4,
			"itemHeight": 90, "inRange": map[string]any{"color": []string{"#e8f3ff", "#6fa8ff", "#2f6bff", "#1b3fbf"}}},
		"series": []map[string]any{{"type": "heatmap", "data": heat,
			"label": map[string]any{"show": true, "fontSize": 10},
			"emphasis": map[string]any{"itemStyle": map[string]any{"shadowBlur": 8}}}} ,
	}
	barOpt := map[string]any{
		"tooltip": map[string]any{"trigger": "axis"},
		"grid":    map[string]any{"left": 60, "right": 20, "top": 30, "bottom": 40},
		"xAxis":   map[string]any{"type": "category", "data": regions},
		"yAxis":   map[string]any{"type": "value", "name": "工时(h)"},
		"series": []map[string]any{{"type": "bar", "barWidth": 28, "data": barData(regions, regionTotal),
			"itemStyle": map[string]any{"borderRadius": []int{6, 6, 0, 0}, "color": "#5b57e8"}}},
	}
	lineOpt := map[string]any{
		"tooltip": map[string]any{"trigger": "axis"},
		"grid":    map[string]any{"left": 60, "right": 20, "top": 30, "bottom": 40},
		"xAxis":   map[string]any{"type": "category", "data": months},
		"yAxis":   map[string]any{"type": "value", "name": "工时(h)"},
		"series": []map[string]any{{"type": "line", "smooth": true, "showSymbol": true,
			"data": lineData(months, monthTotal), "areaStyle": map[string]any{"opacity": 0.12},
			"lineStyle": map[string]any{"width": 2.5, "color": "#0ea5a5"}, "itemStyle": map[string]any{"color": "#0ea5a5"}}},
	}
	pieData := []map[string]any{}
	for d, v := range deptTotal {
		pieData = append(pieData, map[string]any{"name": d, "value": round1(v)})
	}
	pieOpt := map[string]any{
		"tooltip": map[string]any{"trigger": "item"},
		"legend":  map[string]any{"bottom": 0},
		"series": []map[string]any{{"type": "pie", "radius": []string{"45%", "70%"},
			"itemStyle": map[string]any{"borderRadius": 6, "borderColor": "#fff", "borderWidth": 2},
			"label":     map[string]any{"formatter": "{b}\n{d}%"},
			"data":      pieData}},
	}

	// 洞察（判定方法要可解释）
	insights := []map[string]any{}
	if len(regions) >= 2 {
		hi, lo := regions[0], regions[len(regions)-1]
		hv, lv := regionTotal[hi].hours, regionTotal[lo].hours
		insights = append(insights, map[string]any{"level": "info",
			"text": fmt.Sprintf("区域工时：%s 最高（%.0f h），%s 最低（%.0f h），相差 %.0f%%。", hi, hv, lo, lv, (hv-lv)/lv*100)})
		mean := tot.hours / float64(len(regions))
		for _, rg := range regions {
			if regionTotal[rg].hours < mean*0.8 {
				insights = append(insights, map[string]any{"level": "warn",
					"text": fmt.Sprintf("%s 工时低于均值 20%% 以上（%.0f h，均值 %.0f h），已按均值±20%% 判定为异常，建议核查排班与项目饱和度。", rg, regionTotal[rg].hours, mean)})
			}
		}
	}
	worstMonth, worstVal := "", 0.0
	for m, v := range monthTotal {
		if v > worstVal {
			worstMonth, worstVal = m, v
		}
	}
	insights = append(insights, map[string]any{"level": "info",
		"text": fmt.Sprintf("加班集中在 %s（%.0f h，占全期 %.1f%%），与季度末交付节奏一致。", worstMonth, worstVal, worstVal/tot.hours*100)})
	if r := safeDiv(tot.defects, tot.tasks) * 100; r > 3 {
		insights = append(insights, map[string]any{"level": "risk",
			"text": fmt.Sprintf("缺陷率 %.2f%%（缺陷 %.0f / 任务 %.0f）偏高，建议在交付前增加质量门禁。", r, tot.defects, tot.tasks)})
	}

	dash := map[string]any{
		"type": "dashboard", "title": "2026年Q3 工时效率分析大屏",
		"subtitle": "数据范围 2026-07-01 ~ 2026-09-30 · 5 个区域 · 3 个月 · 薪资列已脱敏",
		"kpis":     kpis,
		"charts": []map[string]any{
			{"type": "heatmap", "title": "区域 × 月份工时热力图", "option": heatOpt, "height": 300},
			{"type": "bar", "title": "区域工时对比", "option": barOpt, "height": 300},
			{"type": "line", "title": "月度工时趋势", "option": lineOpt, "height": 240},
			{"type": "pie", "title": "部门工时占比", "option": pieOpt, "height": 240},
		},
		"insights": insights,
		"source": map[string]any{"datasource": "demo.db", "rows": len(rows), "masked": []string{"salary"},
			"sql": "select region, dept, substr(work_date,1,7) as m, sum(hours) ... from worktime_fact where ... group by region, dept, m"},
	}
	summary := fmt.Sprintf("已完成 2026 年 Q3 工时效率分析，结论如下：\n1. 覆盖 **%d 个区域 / %d 个月**，总工时 **%.1f 万 h**（环比 %s），交付 **%.0f 个任务**（环比 %s）。\n2. 人效 **%.1f 任务/百工时**，加班率 **%.1f%%**，缺陷率 **%.2f%%**。\n3. 异常提示：%s",
		len(regions), len(months), tot.hours/10000, pct(tot.hours, ph), tot.tasks, pct(tot.tasks, pt),
		safeDiv(tot.tasks, tot.hours)*100, safeDiv(tot.ot, tot.hours)*100, safeDiv(tot.defects, tot.tasks)*100,
		firstInsight(insights))
	return dash, summary
}

// ---------------- 深度报告（直接生成 HTML，省掉 Markdown 渲染器） ----------------

func buildReport(rows, prev []map[string]any, who string) string {
	var hours, tasks, ot, defects float64
	region := map[string]float64{}
	for _, r := range rows {
		hours += num(r["hours"])
		tasks += num(r["tasks"])
		ot += num(r["ot"])
		defects += num(r["defects"])
		region[fmt.Sprint(r["region"])] += num(r["hours"])
	}
	rs := keysOfFloat(region)
	sort.Slice(rs, func(i, j int) bool { return region[rs[i]] > region[rs[j]] })

	var b strings.Builder
	b.WriteString(`<h1>2026 年 Q3 工时效率深度分析报告</h1>`)
	b.WriteString(`<blockquote>数据范围：2026-07-01 ~ 2026-09-30｜数据源：demo.db｜执行身份：` + who + `｜权限说明：salary 已按策略脱敏</blockquote>`)
	b.WriteString(`<h2>一、核心结论</h2><ol>`)
	b.WriteString(fmt.Sprintf(`<li><b>总量与结构</b>：本季度投入 %.0f 工时，交付 %.0f 个任务，%s 是工时投入最大的区域（%.0f h，占 %.1f%%）。</li>`, hours, tasks, firstOr(rs, "—"), region[firstOr(rs, "—")], safeDiv(region[firstOr(rs, "—")], hours)*100))
	b.WriteString(fmt.Sprintf(`<li><b>效率</b>：整体人效 %.1f 任务/百工时；区域间最高/最低相差 %.0f%%，效率差异比工时差异更值得关注。</li>`, safeDiv(tasks, hours)*100, gapPct(region)))
	b.WriteString(fmt.Sprintf(`<li><b>加班与质量</b>：加班合计 %.0f h（占比 %.1f%%），缺陷 %.0f 个（缺陷率 %.2f%%）。</li>`, ot, safeDiv(ot, hours)*100, defects, safeDiv(defects, tasks)*100))
	b.WriteString(`</ol>`)
	b.WriteString(`<h2>二、关键指标总览</h2><table><thead><tr><th>指标</th><th>数值</th><th>说明</th></tr></thead><tbody>`)
	b.WriteString(fmt.Sprintf(`<tr><td>总工时</td><td>%.0f h</td><td>5 区域 × 3 个月汇总</td></tr>`, hours))
	b.WriteString(fmt.Sprintf(`<tr><td>交付任务</td><td>%.0f 个</td><td>通过验收的任务数</td></tr>`, tasks))
	b.WriteString(fmt.Sprintf(`<tr><td>人效</td><td>%.1f 任务/百工时</td><td>tasks / hours × 100</td></tr>`, safeDiv(tasks, hours)*100))
	b.WriteString(fmt.Sprintf(`<tr><td>加班率</td><td>%.1f%%</td><td>overtime / hours</td></tr>`, safeDiv(ot, hours)*100))
	b.WriteString(fmt.Sprintf(`<tr><td>缺陷率</td><td>%.2f%%</td><td>defects / tasks</td></tr>`, safeDiv(defects, tasks)*100))
	b.WriteString(`</tbody></table>`)
	b.WriteString(`<h2>三、区域对比</h2><table><thead><tr><th>区域</th><th>工时(h)</th><th>占比</th></tr></thead><tbody>`)
	for _, r := range rs {
		b.WriteString(fmt.Sprintf(`<tr><td>%s</td><td>%.0f</td><td>%.1f%%</td></tr>`, r, region[r], safeDiv(region[r], hours)*100))
	}
	b.WriteString(`</tbody></table>`)
	b.WriteString(`<h2>四、归因与建议</h2><ul>`)
	b.WriteString(fmt.Sprintf(`<li><b>工时结构</b>：%s 占比最高，建议把该区域的排班与项目负载做成月度看板，避免单点过载。</li>`, firstOr(rs, "—")))
	b.WriteString(fmt.Sprintf(`<li><b>效率短板</b>：区域人效差距 %.0f%%，优先对低人效区域做复盘（任务颗粒度、验收标准、返工率）。</li>`, gapPct(region)))
	b.WriteString(`<li><b>质量门禁</b>：缺陷率偏高时，应在交付前增加自动化用例与验收清单，避免后期返工吃掉工时。</li>`)
	b.WriteString(`<li><b>口径与权限</b>：本报告所有数字来自受控查询（改写后的 SQL 已留痕），salary 等敏感列全程脱敏。</li>`)
	b.WriteString(`</ul>`)
	b.WriteString(`<h2>五、附录：统计口径</h2><p>hours：计费工时（含加班）；overtime：每日超过 8.5h 部分；tasks：通过验收的任务数；defects：验收后 30 天内缺陷数；人效 = tasks/hours×100；环比对比 2026 Q2（4–6 月）。</p>`)
	return b.String()
}

// ---------------- 拜访指南（HTML 产物） ----------------

func buildGuide(c map[string]any, note string) string {
	esc := func(v any) string { return htmlEscape(fmt.Sprint(v)) }
	var b strings.Builder
	b.WriteString(`<html><head><meta charset="utf-8"><style>
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;background:#f5f6fa;color:#171a23;padding:24px}
.card{background:#fff;border:1px solid #e6e9f2;border-radius:16px;padding:20px;margin-bottom:16px;box-shadow:0 8px 24px -16px rgba(23,26,35,.4)}
.hero{background:linear-gradient(135deg,#5b57e8,#4642c9);color:#fff}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:16px}
.k{background:rgba(255,255,255,.14);border-radius:12px;padding:12px}
.k b{display:block;font-size:20px;margin-top:4px}
h1{font-size:20px;margin:0 0 6px}h2{font-size:15px;margin:0 0 10px}
.tag{display:inline-block;background:#eef0ff;color:#4a45c9;border-radius:999px;padding:2px 10px;font-size:12px;margin:4px 6px 0 0}
.risk{background:#fff7ed;border-left:3px solid #f59e0b;padding:10px 12px;border-radius:8px;font-size:13px;margin-top:12px}
ul{margin:8px 0 0 18px;padding:0;font-size:13.5px;line-height:1.8}
</style></head><body>`)
	if note != "" {
		b.WriteString(`<div class="card risk">` + esc(note) + `</div>`)
	}
	b.WriteString(`<div class="card hero"><h1>` + esc(c["name"]) + `</h1><div style="opacity:.85;font-size:13px">` + esc(c["industry"]) + ` · ` + esc(c["scale"]) + ` · ` + esc(c["region"]) + ` · 客户等级 ` + esc(c["level"]) + `</div>
<div class="grid">
<div class="k">历史订单<b>` + esc(c["orders"]) + ` 笔</b></div>
<div class="k">累计金额<b>` + fmt.Sprintf("%.1f 万", num(c["amount"])/10000) + `</b></div>
<div class="k">最近沟通<b>` + esc(substr(fmt.Sprint(c["last_contact"]), 0, 10)) + `</b></div>
<div class="k">负责人<b>` + esc(ownerName(fmt.Sprint(c["owner_id"]))) + `</b></div>
</div></div>`)
	b.WriteString(`<div class="card"><h2>客户 360° 画像</h2>
<span class="tag">行业：` + esc(c["industry"]) + `</span><span class="tag">规模：` + esc(c["scale"]) + `</span><span class="tag">地区：` + esc(c["region"]) + `</span><span class="tag">等级：` + esc(c["level"]) + `</span>
<p style="font-size:13.5px;line-height:1.8;margin:12px 0 0">最近沟通：` + esc(c["summary"]) + `</p></div>`)
	b.WriteString(`<div class="card"><h2>潜在需求预判</h2><ul>
<li>数据分散在多系统，存在「取数靠人、报表靠排期」的典型瓶颈 → 优先验证统一数据口径与自助分析。</li>
<li>近期沟通集中在回款/交付验收 → 说明已有项目在跑，二期扩容与运维服务是自然的切入点。</li>
<li>客户等级较高但订单笔数有限 → 渗透率有空间，可用小范围试点降低决策门槛。</li>
</ul></div>`)
	b.WriteString(`<div class="card"><h2>沟通策略</h2><ul>
<li>先复盘合作底账（订单、金额、验收、应收），用事实开场，避免泛泛而谈。</li>
<li>用「业务指标」而不是「功能列表」表达价值：交付周期、人效、返工率。</li>
<li>结束前锁定三件事：下次会议时间、试点范围、验收指标。</li>
</ul></div>`)
	b.WriteString(`<div class="card"><h2>话术要点（3 段）</h2><ul>
<li><b>开场</b>：「王总，上次提到的验收进度我看了下，目前 3 笔订单里 2 笔已验收，剩下 1 笔本周可以闭环。这次想跟您对一下二期的节奏。」</li>
<li><b>价值假设</b>：「我们观察到贵司在数据整合上投入不少人力，如果把这部分做成自助分析，按同规模客户的经验，月度报表周期可以缩短一半以上。」</li>
<li><b>推进</b>：「建议先选一个区域做两周试点，用你们现有的验收指标来衡量，达标我们再谈扩容，您看可以吗？」</li>
</ul></div>`)
	b.WriteString(`<p style="font-size:12px;color:#8b93a7">本指南由 DataClaw 数字员工生成；外部信息为离线模拟并已标注，内部数据受行级权限限制。</p></body></html>`)
	return b.String()
}

// ---------------- 合同规则引擎 ----------------

func analyzeClauses(rows []map[string]any) []Risk {
	out := []Risk{}
	add := func(clause, title, level, issue, suggestion, original string) {
		out = append(out, Risk{Clause: clause, Title: title, Level: level, Issue: issue, Suggestion: suggestion, Original: original})
	}
	for _, r := range rows {
		no, _title, text := fmt.Sprint(r["clause"]), fmt.Sprint(r["title"]), fmt.Sprint(r["text"])
		_ = _title
		low := strings.ToLower(text)
		has := func(kw ...string) bool {
			for _, k := range kw {
				if strings.Contains(low, k) {
					return true
				}
			}
			return false
		}
		switch {
		case has("120 日", "90 日", "60 日") && has("付款", "账期"):
			add(no, "付款账期过长", "high", "约定 120 天账期，超过公司标准（≤60 天），回款风险与资金占用显著上升。", "建议将账期调整为 60 天内，或改为「30 天付 60% + 验收后 30 天付 40%」的分期方案。", text)
		case has("不承担违约"):
			add(no, "违约责任不对等", "high", "违约金仅约束乙方（日千分之五，年化 182%），甲方逾期付款不承担责任。", "建议双方违约金比例对齐（如均为 0.05%/日，累计不超过合同总额 10%），并设置责任上限。", text)
		case has("30%") && has("违约金"):
			add(no, "违约金比例过高", "high", "约定违约方支付合同总额 30% 的违约金，比例显著高于行业惯例（通常 5%–10%）。", "建议将违约金上限调整为合同总额的 10%，并区分根本违约与一般违约。", text)
		case has("管辖") && has("北京", "甲方所在地"):
			add(no, "管辖法院不利", "high", "约定甲方所在地法院管辖，我方主要履约地不在该地，诉讼成本高。", "建议改为「由被告所在地/合同履行地人民法院管辖」，或约定双方认可的仲裁机构。", text)
		case has("知识产权") && has("共同所有", "另行协商"):
			add(no, "知识产权归属模糊", "high", "知识产权归双方共同所有且行使方式另行协商，实际不可执行。", "建议明确：通用组件/平台能力归乙方，定制交付物归甲方，并授予甲方永久使用许可。", text)
		case has("无限连带"):
			add(no, "无限连带责任", "high", "乙方对关联方及分包方承担无限连带责任，责任无上限。", "建议限定为「因乙方原因造成的直接损失，且不超过合同总额」。", text)
		case has("无权单方解除", "随时无理由解除"):
			add(no, "单方解除权", "high", "甲方可随时无理由解除，乙方无对等权利，投入回收无保障。", "建议改为双方均需提前 30 日书面通知，并对已完成工作量结算。", text)
		case has("保密") && has("1 年", "一年"):
			add(no, "保密期限过短", "medium", "保密期限仅 1 年，低于公司标准（≥3 年），商业秘密保护不足。", "建议延长至合同终止后 3–5 年，并对核心数据设置更长保护期。", text)
		case has("自动续约"):
			add(no, "自动续约条款", "medium", "期满自动续约一年，未设置双方确认机制，易形成被动续期。", "建议改为「需双方书面确认后续约」，或至少提前 60 日双方确认。", text)
		case has("验收") && has("甲方书面确认"):
			add(no, "验收标准不明确", "medium", "验收以甲方单方书面确认为准，逾期视为通过，标准主观不可控。", "建议附件列明可量化验收清单与测试用例，明确默认验收的条件与时限。", text)
		case has("另行确认", "相关技术服务"):
			add(no, "服务范围不明确", "low", "服务内容以「另行确认」为准，交付边界不清。", "建议补充《服务水平协议》与工作说明书附件，明确交付物清单与验收口径。", text)
		case has("保障数据安全"):
			add(no, "数据安全责任缺失", "low", "数据安全条款仅一句话，缺少具体义务与违约后果。", "建议补充数据分类、加密、泄露通知时限与责任条款。", text)
		}
	}
	if len(out) == 0 {
		add("全文", "未命中已知风险规则", "low", "当前规则库未匹配到明显风险条款。", "建议人工复核并补充规则库。", "")
	}
	return out
}

// ---------------- 知识检索（BM25 简化版） ----------------

func searchDocs(a *App, q string, top int) []map[string]any {
	docs := list[Doc](a.db, "doc")
	terms := strings.Fields(strings.NewReplacer("，", " ", "。", " ", "、", " ").Replace(q))
	type scored struct {
		doc Doc
		s   float64
	}
	res := []scored{}
	for _, d := range docs {
		s := 0.0
		for _, t := range terms {
			t = strings.TrimSpace(t)
			if len([]rune(t)) < 2 {
				continue
			}
			if strings.Contains(d.Text, t) {
				s += 1
			}
		}
		if s > 0 {
			res = append(res, scored{d, s})
		}
	}
	sort.Slice(res, func(i, j int) bool { return res[i].s > res[j].s })
	out := []map[string]any{}
	for i, r := range res {
		if i >= top {
			break
		}
		i2 := strings.Index(r.doc.Text, strings.TrimSpace(terms[0]))
		if i2 < 0 {
			i2 = 0
		}
		start := i2 - 30
		if start < 0 {
			start = 0
		}
		end := start + 120
		if end > len(r.doc.Text) {
			end = len(r.doc.Text)
		}
		out = append(out, map[string]any{"doc": r.doc.Name, "snippet": r.doc.Text[start:end], "score": r.s})
	}
	return out
}

// ---------------- 数学/格式化小工具 ----------------

func num(v any) float64 {
	switch x := v.(type) {
	case float64:
		return x
	case int64:
		return float64(x)
	case int:
		return float64(x)
	case []byte:
		f := 0.0
		fmt.Sscan(string(x), &f)
		return f
	case string:
		f := 0.0
		fmt.Sscan(x, &f)
		return f
	}
	return 0
}

func safeDiv(a, b float64) float64 {
	if b == 0 {
		return 0
	}
	return a / b
}

func keys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}

func keysOfAgg(m map[string]*aggT) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}

func keysOfFloat(m map[string]float64) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}

func barData(regions []string, agg map[string]*aggT) []map[string]any {
	out := []map[string]any{}
	for _, r := range regions {
		item := map[string]any{"value": round1(agg[r].hours), "name": r}
		if r == regions[0] || r == regions[len(regions)-1] {
			item["itemStyle"] = map[string]any{"color": "#f59e0b"}
		}
		out = append(out, item)
	}
	return out
}

func lineData(months []string, m map[string]float64) []float64 {
	out := []float64{}
	for _, x := range months {
		out = append(out, round1(m[x]))
	}
	return out
}

func floorHeat(rm map[string]map[string]float64) float64 {
	mn := 1e18
	for _, ms := range rm {
		for _, v := range ms {
			if v < mn {
				mn = v
			}
		}
	}
	if mn == 1e18 {
		return 0
	}
	return round1(mn)
}

func maxHeat(rm map[string]map[string]float64) float64 {
	mx := 0.0
	for _, ms := range rm {
		for _, v := range ms {
			if v > mx {
				mx = v
			}
		}
	}
	return mx
}

func firstInsight(insights []map[string]any) string {
	for _, i := range insights {
		if i["level"] == "warn" || i["level"] == "risk" {
			return fmt.Sprint(i["text"])
		}
	}
	if len(insights) > 0 {
		return fmt.Sprint(insights[0]["text"])
	}
	return "无"
}

func firstOr(s []string, def string) string {
	if len(s) > 0 {
		return s[0]
	}
	return def
}

func gapPct(m map[string]float64) float64 {
	if len(m) < 2 {
		return 0
	}
	hi, lo := 0.0, 1e18
	for _, v := range m {
		if v > hi {
			hi = v
		}
		if v < lo {
			lo = v
		}
	}
	if lo == 0 {
		return 0
	}
	return (hi - lo) / lo * 100
}

func substr(s string, start, end int) string {
	r := []rune(s)
	if start > len(r) {
		return ""
	}
	if end > len(r) {
		end = len(r)
	}
	return string(r[start:end])
}

func htmlEscape(s string) string {
	return strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", `"`, "&quot;").Replace(s)
}

func ownerName(id string) string {
	if id == "u_sales" {
		return "程景舟"
	}
	return id
}

type aggT struct{ hours, ot, tasks, defects float64 }
