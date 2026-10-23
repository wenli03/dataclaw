package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"
)

// ---------------- 会话与 SSE ----------------

type chatReq struct {
	SessionID string `json:"sessionId"`
	EmpID     string `json:"empId"`
	Content   string `json:"content"`
}

type approvalReq struct {
	ID       string `json:"id"`
	Decision string `json:"decision"`
}

var pending = sync.Map{} // approvalID -> chan bool

func (a *App) handleChat(w http.ResponseWriter, r *http.Request, uid string) {
	var req chatReq
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&req); err != nil {
		writeJSON(w, 400, errBody("BAD_BODY", "请求体不合法"))
		return
	}
	emp, ok := get[Employee](a.db, "employee", req.EmpID)
	if !ok || emp.Owner != uid {
		writeJSON(w, 403, errBody("FORBIDDEN", "无权使用该数字员工"))
		return
	}
	u, _ := get[User](a.db, "user", uid)

	sid := req.SessionID
	if sid == "" {
		sid = newID("s")
		title := []rune(strings.TrimSpace(req.Content))
		if len(title) > 20 {
			title = title[:20]
		}
		_ = put(a.db, "session", sid, Session{ID: sid, EmpID: emp.ID, UserID: uid, Title: string(title), Updated: now(), Count: 0})
	}
	um := newID("m")
	_ = put(a.db, "message", um, Message{ID: um, SessionID: sid, Role: "user", Content: req.Content, Created: now()})

	flusher, _ := w.(http.Flusher)
	w.Header().Set("Content-Type", "text/event-stream; charset=utf-8")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no")
	send := func(ev string, v any) {
		b, _ := json.Marshal(v)
		fmt.Fprintf(w, "event: %s\ndata: %s\n\n", ev, b)
		if flusher != nil {
			flusher.Flush()
		}
	}

	msgID := newID("m")
	send("start", map[string]any{"messageId": msgID, "sessionId": sid, "title": sessionTitle(a, sid)})

	c := &runCtx{a: a, uid: uid, user: u, emp: emp, sid: sid, send: send}
	answer, steps, arts := c.run(req.Content)
	send("done", map[string]any{"messageId": msgID, "steps": len(steps), "artifacts": len(arts)})

	_ = put(a.db, "message", msgID, Message{ID: msgID, SessionID: sid, Role: "assistant",
		Content: answer, Steps: steps, Artifacts: arts, Created: now()})
	if s, ok := get[Session](a.db, "session", sid); ok {
		s.Count += 2
		s.Updated = now()
		_ = put(a.db, "session", sid, s)
	}
	a.audit(uid, "chat", emp.Name, "low", "success", map[string]any{"sessionId": sid, "chars": len(req.Content)})
}

// handleApprove 处理 HITL 审批：唤醒正在等待的 SSE 流。
func (a *App) handleApprove(w http.ResponseWriter, r *http.Request, uid string) {
	var req approvalReq
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&req); err != nil {
		writeJSON(w, 400, errBody("BAD_BODY", "请求体不合法"))
		return
	}
	ch, ok := pending.Load(req.ID)
	if !ok {
		writeJSON(w, 404, errBody("APPROVAL_NOT_FOUND", "审批已失效或不存在"))
		return
	}
	ch.(chan bool) <- req.Decision == "approved"
	writeJSON(w, 200, map[string]any{"ok": true, "decision": req.Decision})
}

func sessionTitle(a *App, sid string) string {
	if s, ok := get[Session](a.db, "session", sid); ok {
		return s.Title
	}
	return "新会话"
}

// runCtx 承载一轮执行（用户身份决定一切数据权限）。
type runCtx struct {
	a    *App
	uid  string
	user User
	emp  Employee
	sid  string
	send func(string, any)
	art  []Artifact
	step []Step
}

func (c *runCtx) emit(title, tool string, out any, ok bool, ms int64) {
	st := Step{Title: title, Tool: tool, Status: "done", Ms: ms, Output: out}
	if !ok {
		st.Status = "error"
	}
	c.step = append(c.step, st)
	c.send("step", st)
}

// tool 执行一个工具并流式回报（running → done）。
func (c *runCtx) tool(title, tool string, fn func() (any, bool)) any {
	c.send("step", map[string]any{"title": title, "tool": tool, "status": "running"})
	t0 := time.Now()
	out, ok := fn()
	c.emit(title, tool, out, ok, time.Since(t0).Milliseconds())
	return out
}

func (c *runCtx) delta(text string) { c.send("delta", map[string]any{"text": text}) }

func (c *runCtx) artifact(art Artifact) {
	art.ID = newID("a")
	_ = put(c.a.db, "artifact", art.ID, art)
	c.art = append(c.art, art)
	c.send("artifact", art)
}

// ---------------- 离线确定性 Planner ----------------

func (c *runCtx) run(q string) (string, []Step, []Artifact) {
	has := func(kw ...string) bool {
		for _, k := range kw {
			if strings.Contains(q, k) {
				return true
			}
		}
		return false
	}
	switch {
	case has("工时", "人效", "大屏", "分析", "报表", "效率"):
		return c.scenarioWorktime(q)
	case has("合同", "审查", "条款", "法务"):
		return c.scenarioContract(q)
	case has("拜访", "客户", "情报", "商机"):
		return c.scenarioSales(q)
	}
	return c.fallback()
}

func (c *runCtx) fallback() (string, []Step, []Artifact) {
	names := []string{}
	for _, id := range c.emp.Skills {
		if s, ok := get[Skill](c.a.db, "skill", id); ok {
			names = append(names, s.Name)
		}
	}
	ans := fmt.Sprintf("我是「%s」。当前已装载技能：%s。\n\n可以让我：\n1. 分析上季度工时效率并出大屏\n2. 准备某个客户的拜访指南\n3. 按公司规则审查合同并输出修订版", c.emp.Name, strings.Join(names, "、"))
	c.delta(ans)
	return ans, c.step, c.art
}

// ---------------- 场景一：工时分析 ----------------

const (
	sqlCur = `select region, dept, substr(work_date,1,7) as m, sum(hours) hours, sum(overtime) ot,
 sum(tasks) tasks, sum(defects) defects, avg(salary) salary
from worktime_fact where work_date >= '2026-07-01' and work_date < '2026-10-01'
group by region, dept, m order by region, m`
	sqlPrev = `select region, dept, substr(work_date,1,7) as m, sum(hours) hours,
 sum(tasks) tasks from worktime_fact where work_date >= '2026-04-01' and work_date < '2026-07-01'
group by region, dept, m`
)

func (c *runCtx) scenarioWorktime(q string) (string, []Step, []Artifact) {
	pols := c.a.policyFor(c.uid, c.user.Role)

	c.tool("列出可用数据表", "chatbi.list_tables", func() (any, bool) {
		out := []map[string]any{}
		for _, t := range c.a.tables() {
			ok, filter, reason := resolveTable(pols, t)
			out = append(out, map[string]any{"table": t, "allowed": ok, "rowFilter": filter, "reason": reason})
		}
		return out, true
	})

	c.tool("查看表字段结构", "chatbi.describe_table", func() (any, bool) {
		cols := []map[string]any{}
		for _, col := range c.a.columnsOf("worktime_fact") {
			mode := ""
			for _, p := range pols {
				if strings.HasSuffix(p.Resource, "."+col) && p.Mask != "" && p.Mask != "none" {
					mode = p.Mask
				}
			}
			cols = append(cols, map[string]any{"column": col, "mask": mode})
		}
		return cols, true
	})

	cur, _ := c.tool("执行自然语言问数（本季度）", "chatbi.ask", func() (any, bool) {
		g := c.a.guard(c.uid, c.user.Role, sqlCur, 500)
		if !g.OK {
			return map[string]any{"denied": g.Denied, "sql": g.SQL}, false
		}
		return map[string]any{"sql": g.SQL, "rows": g.RowCount, "masked": g.Masked, "rules": g.Rules, "sample": firstRows(g.Rows, 2)}, true
	}).(map[string]any)
	if d, _ := cur["denied"].(string); d != "" {
		ans := "当前账号没有工时表的访问权限：" + d + "\n\n请联系管理员在「数据安全 → 访问策略」中授权。"
		c.delta(ans)
		return ans, c.step, c.art
	}

	prevRows := c.a.guard(c.uid, c.user.Role, sqlPrev, 500).Rows
	rows := c.a.guard(c.uid, c.user.Role, sqlCur, 500).Rows

	dash, summary := buildDashboard(rows, prevRows)
	c.tool("生成可视化大屏", "dashboard.build", func() (any, bool) {
		c.artifact(Artifact{Kind: "dashboard", Title: fmt.Sprint(dash["title"]), Payload: dash})
		return map[string]any{"kpis": len(dash["kpis"].([]map[string]any)), "charts": len(dash["charts"].([]map[string]any))}, true
	})
	c.tool("撰写深度分析报告", "report.write", func() (any, bool) {
		html := buildReport(rows, prevRows, c.user.Name)
		c.artifact(Artifact{Kind: "report", Title: "2026年Q3 工时效率深度分析报告",
			Payload: map[string]any{"type": "report", "html": html}})
		return map[string]any{"chars": len(html)}, true
	})

	ans := summary + "\n\n已按你的数据权限执行（薪资列已脱敏、行级过滤生效），大屏与报告已生成。"
	c.delta(ans)
	return ans, c.step, c.art
}

// ---------------- 场景二：销售情报 ----------------

func (c *runCtx) scenarioSales(q string) (string, []Step, []Artifact) {
	cust, _ := c.tool("调取客户 360（受行级权限限制）", "sales.customer_360", func() (any, bool) {
		g := c.a.guard(c.uid, c.user.Role, "select * from crm_customer limit 50", 50)
		if !g.OK {
			return map[string]any{"denied": g.Denied}, false
		}
		want := extractName(q)
		var pick map[string]any
		for _, r := range g.Rows {
			if want != "" && strings.Contains(fmt.Sprint(r["name"]), want) {
				pick = r
				break
			}
		}
		note := ""
		if pick == nil && len(g.Rows) > 0 {
			pick = g.Rows[0]
			if want != "" {
				note = fmt.Sprintf("你提到的「%s」不在你负责的客户列表，已改用你负责的「%v」作为示例。", want, pick["name"])
			}
		}
		if pick == nil {
			return map[string]any{"denied": "你的账号下暂无客户数据，请联系管理员分配客户或检查行级权限。"}, false
		}
		return map[string]any{"customer": pick, "note": note, "rows": g.RowCount, "masked": g.Masked}, true
	}).(map[string]any)
	if d, _ := cust["denied"].(string); d != "" {
		ans := "无法生成拜访指南：" + d
		c.delta(ans)
		return ans, c.step, c.art
	}
	row, _ := cust["customer"].(map[string]any)
	note, _ := cust["note"].(string)

	c.tool("检索知识库（拜访方法论）", "knowledge.search", func() (any, bool) {
		return searchDocs(c.a, "拜访 客户 话术 方法论", 2), true
	})
	c.tool("融合内外部情报", "sales.fuse", func() (any, bool) {
		return map[string]any{"internal": 1, "external": 2, "simulated": true}, true
	})
	c.tool("生成拜访指南", "sales.build_guide", func() (any, bool) {
		html := buildGuide(row, note)
		c.artifact(Artifact{Kind: "html", Title: fmt.Sprint(row["name"], " 拜访指南"),
			Payload: map[string]any{"type": "html", "html": html}})
		return map[string]any{"bytes": len(html)}, true
	})

	ans := ""
	if note != "" {
		ans = "> " + note + "\n\n"
	}
	ans += fmt.Sprintf("拜访 **%v** 前，先做这 3 件事：\n1. 复盘合作底账：历史订单 %v 笔 / 累计 %.1f 万 / 最近沟通 %v。\n2. 带着假设去：客户属 %v·%v·%v，优先验证「数据整合与提效」。\n3. 准备好话术与下一步：按「痛点确认 → 价值假设 → 小范围试点」推进，结束时确认下次沟通时间。\n\n已生成《%v 拜访指南》。",
		row["name"], row["orders"], num(row["amount"])/10000, row["last_contact"],
		row["industry"], row["scale"], row["region"], row["name"])
	c.delta(ans)
	return ans, c.step, c.art
}

// ---------------- 场景三：合同审查 ----------------

func (c *runCtx) scenarioContract(q string) (string, []Step, []Artifact) {
	cl, _ := c.tool("解析合同并读取条款", "contract.parse", func() (any, bool) {
		g := c.a.guard(c.uid, c.user.Role, "select * from contract_clause limit 100", 100)
		if !g.OK {
			return map[string]any{"denied": g.Denied}, false
		}
		return map[string]any{"clauses": g.RowCount, "rows": g.Rows}, true
	}).(map[string]any)
	if d, _ := cl["denied"].(string); d != "" {
		ans := "无法审查：当前账号没有合同表的访问权限（" + d + "）。"
		c.delta(ans)
		return ans, c.step, c.art
	}
	rows, _ := cl["rows"].([]map[string]any)

	c.tool("匹配企业审查规则库", "contract.rules", func() (any, bool) {
		return searchDocs(c.a, "合同 审查 规则 付款 违约金 管辖", 2), true
	})
	risks, _ := c.tool("逐条比对并给出风险分级", "contract.analyze", func() (any, bool) {
		return analyzeClauses(rows), true
	}).([]Risk)

	// HITL：导出高风险文件前必须人工确认（事件发出后服务端挂起等待）
	approvalID := newID("ap")
	ch := make(chan bool, 1)
	pending.Store(approvalID, ch)
	c.send("approval", map[string]any{"id": approvalID, "action": "export_docx", "risk": "high",
		"reason": "将导出含企业条款的修订版文件（人工审批后执行）"})
	approved := false
	select {
	case approved = <-ch:
	case <-time.After(60 * time.Second):
	}
	pending.Delete(approvalID)
	result := "denied"
	if approved {
		result = "success"
	}
	c.a.audit(c.uid, "hitl_approval", "export_docx", "high", result, map[string]any{"approvalId": approvalID})

	title := "合同审查报告（修订版）"
	if len(rows) > 0 {
		title = fmt.Sprint(rows[0]["contract"]) + " 审查报告（修订版）"
	}
	if approved {
		c.tool("导出带修订痕迹的 docx", "contract.export_docx", func() (any, bool) {
			file := fmt.Sprintf("合同审查-%d.docx", time.Now().Unix())
			if err := buildDocx(c.a.path(file), title, risks); err != nil {
				return map[string]any{"error": err.Error()}, false
			}
			high, mid, low := 0, 0, 0
			for _, r := range risks {
				switch r.Level {
				case "high":
					high++
				case "medium":
					mid++
				default:
					low++
				}
			}
			c.artifact(Artifact{Kind: "docx", Title: title, File: file, Payload: map[string]any{
				"type": "docx", "fileName": file,
				"stats":    map[string]int{"risks": len(risks), "high": high, "medium": mid, "low": low},
				"redlines": risks,
			}})
			return map[string]any{"file": file, "risks": len(risks)}, true
		})
	}

	high := 0
	for _, r := range risks {
		if r.Level == "high" {
			high++
		}
	}
	verdict := "导出未获审批，仅输出风险清单。"
	if approved {
		verdict = "已生成带修订痕迹的 docx，可直接下载。"
	}
	ans := fmt.Sprintf("合同审查完成：《%v》共识别 **%d 项风险**（高 %d / 中 %d / 低 %d）。\n\n1. 高风险优先处理：%s\n2. 中风险建议确认：%s\n3. %s",
		strings.TrimSuffix(title, " 审查报告（修订版）"), len(risks), high, len(risks)-high-2, 2,
		joinTop(risks, "high"), joinTop(risks, "medium"), verdict)
	c.delta(ans)
	return ans, c.step, c.art
}

// ---------------- 小工具 ----------------

func firstRows(rows []map[string]any, n int) []map[string]any {
	if len(rows) < n {
		return rows
	}
	return rows[:n]
}

func extractName(q string) string {
	for _, kw := range []string{"拜访", "客户"} {
		if i := strings.Index(q, kw); i >= 0 {
			s := strings.TrimSpace(q[i+len(kw):])
			s = strings.NewReplacer("，", "", "。", "", ",", "", ".", "", "帮我", "", "准备", "", "指南", "").Replace(s)
			s = strings.TrimSpace(s)
			if r := []rune(s); len(r) >= 2 {
				if len(r) > 12 {
					r = r[:12]
				}
				return string(r)
			}
		}
	}
	return ""
}

func joinTop(rs []Risk, level string) string {
	out := []string{}
	for _, r := range rs {
		if r.Level == level && len(out) < 3 {
			out = append(out, r.Clause+" "+r.Title)
		}
	}
	if len(out) == 0 {
		return "无"
	}
	return strings.Join(out, "、")
}
