package main

import (
	"fmt"
	"net/http"
	"sort"
	"strings"
)

// ---------------- 登录 / 身份 ----------------

func (a *App) handleLogin(w http.ResponseWriter, r *http.Request) {
	var req struct{ Username, Password string }
	if err := jsonDecode(r, &req); err != nil {
		writeJSON(w, 400, errBody("BAD_BODY", "请求体不合法"))
		return
	}
	for _, u := range list[User](a.db, "user") {
		if u.Username == req.Username && u.Pwd == req.Password {
			a.setSession(w, u.ID)
			a.audit(u.ID, "login", "session", "low", "success", map[string]any{"user": u.Username})
			u.Pwd = ""
			writeJSON(w, 200, map[string]any{"user": u})
			return
		}
	}
	a.audit("", "login", req.Username, "medium", "denied", nil)
	writeJSON(w, 401, errBody("BAD_CREDENTIALS", "账号或密码不正确"))
}

func (a *App) handleLogout(w http.ResponseWriter, r *http.Request) {
	if uid := a.uid(r); uid != "" {
		a.audit(uid, "logout", "session", "low", "success", nil)
	}
	http.SetCookie(w, &http.Cookie{Name: "dc", Value: "", Path: "/", MaxAge: -1})
	writeJSON(w, 200, map[string]any{"ok": true})
}

func (a *App) handleMe(w http.ResponseWriter, _ *http.Request, uid string) {
	u, _ := get[User](a.db, "user", uid)
	u.Pwd = ""
	writeJSON(w, 200, map[string]any{"user": u, "isAdmin": u.Role == "platform_admin"})
}

// ---------------- 工作台启动数据（一次请求拿全，减少前端往返） ----------------

func (a *App) handleBootstrap(w http.ResponseWriter, r *http.Request, uid string) {
	u, _ := get[User](a.db, "user", uid)
	u.Pwd = ""
	installed := map[string]bool{}
	for _, p := range list[Skill](a.db, "skill") {
		installed[p.ID] = false
	}
	employees := a.employees(uid)
	// 技能安装态：以员工装载为准（演示简化：任一员工装载即视为已安装）
	for _, e := range employees {
		for _, s := range e.Skills {
			installed[s] = true
		}
	}
	skills := []map[string]any{}
	for _, s := range list[Skill](a.db, "skill") {
		skills = append(skills, map[string]any{"id": s.ID, "name": s.Name, "desc": s.Desc, "category": s.Category,
			"risk": s.Risk, "installed": installed[s.ID], "content": s.Content})
	}
	sessions := []Session{}
	for _, s := range list[Session](a.db, "session") {
		if s.UserID == uid {
			sessions = append(sessions, s)
		}
	}
	sort.Slice(sessions, func(i, j int) bool { return sessions[i].Updated > sessions[j].Updated })

	out := map[string]any{
		"user": u, "isAdmin": u.Role == "platform_admin",
		"employees": employees, "skills": skills,
		"templates": list[Template](a.db, "template"), "sessions": sessions,
		"agents": a.agentsWithCount(), "stats": a.stats(), "denied": a.deniedCount(),
	}
	writeJSON(w, 200, out)
}

func (a *App) agentsWithCount() []map[string]any {
	out := []map[string]any{}
	assigns := list[Assignment](a.db, "assignment")
	for _, g := range list[Agent](a.db, "agent") {
		n := 0
		for _, x := range assigns {
			if x.AgentID == g.ID {
				n++
			}
		}
		out = append(out, map[string]any{"id": g.ID, "name": g.Name, "role": g.Role, "avatar": g.Avatar,
			"desc": g.Desc, "soul": g.Soul, "version": g.Version, "skills": g.Skills, "assignees": n})
	}
	return out
}

// ---------------- 员工 ----------------

func (a *App) handleCreateEmployee(w http.ResponseWriter, r *http.Request, uid string) {
	var req struct {
		Name       string   `json:"name"`
		Role       string   `json:"role"`
		Avatar     string   `json:"avatar"`
		Soul       string   `json:"soul"`
		TemplateID string   `json:"templateId"`
		Skills     []string `json:"skills"`
	}
	if err := jsonDecode(r, &req); err != nil || strings.TrimSpace(req.Name) == "" {
		writeJSON(w, 400, errBody("BAD_BODY", "请填写员工名称"))
		return
	}
	emp := Employee{ID: newID("e"), Owner: uid, Name: req.Name, Role: req.Role, Avatar: req.Avatar,
		Soul: req.Soul, Skills: req.Skills, Memory: true, Created: now()}
	if t, ok := get[Template](a.db, "template", req.TemplateID); ok {
		if emp.Role == "" {
			emp.Role = t.Role
		}
		if emp.Avatar == "" {
			emp.Avatar = t.Avatar
		}
		if emp.Soul == "" {
			emp.Soul = t.Soul
		}
		if len(emp.Skills) == 0 {
			emp.Skills = t.Skills
		}
	}
	if emp.Avatar == "" {
		emp.Avatar = string([]rune(emp.Name)[0:min(2, len([]rune(emp.Name)))])
	}
	_ = put(a.db, "employee", emp.ID, emp)
	a.audit(uid, "employee_create", emp.Name, "low", "success", map[string]any{"template": req.TemplateID})
	writeJSON(w, 200, emp)
}

func (a *App) handleUpdateEmployee(w http.ResponseWriter, r *http.Request, uid string) {
	var req struct {
		ID     string `json:"id"`
		Name   string `json:"name"`
		Soul   string `json:"soul"`
		Memory *bool  `json:"memory"`
	}
	if err := jsonDecode(r, &req); err != nil {
		writeJSON(w, 400, errBody("BAD_BODY", "请求体不合法"))
		return
	}
	emp, ok := get[Employee](a.db, "employee", req.ID)
	if !ok || emp.Owner != uid {
		writeJSON(w, 403, errBody("FORBIDDEN", "无权修改该员工"))
		return
	}
	if req.Name != "" {
		emp.Name = req.Name
	}
	if req.Soul != "" {
		emp.Soul = req.Soul
	}
	if req.Memory != nil {
		emp.Memory = *req.Memory
	}
	_ = put(a.db, "employee", emp.ID, emp)
	a.audit(uid, "employee_update", emp.Name, "low", "success", nil)
	writeJSON(w, 200, emp)
}

func (a *App) handleEmployeeSkill(w http.ResponseWriter, r *http.Request, uid string) {
	var req struct {
		ID      string `json:"id"`
		SkillID string `json:"skillId"`
		Enabled bool   `json:"enabled"`
	}
	if err := jsonDecode(r, &req); err != nil {
		writeJSON(w, 400, errBody("BAD_BODY", "请求体不合法"))
		return
	}
	emp, ok := get[Employee](a.db, "employee", req.ID)
	if !ok || emp.Owner != uid {
		writeJSON(w, 403, errBody("FORBIDDEN", "无权修改该员工"))
		return
	}
	next := []string{}
	for _, s := range emp.Skills {
		if s != req.SkillID {
			next = append(next, s)
		}
	}
	if req.Enabled {
		next = append(next, req.SkillID)
	}
	emp.Skills = next
	_ = put(a.db, "employee", emp.ID, emp)
	if req.Enabled {
		a.audit(uid, "skill_install", req.SkillID, "low", "success", map[string]any{"employee": emp.Name})
	}
	writeJSON(w, 200, emp)
}

func (a *App) handleSkillInstall(w http.ResponseWriter, r *http.Request, uid string) {
	var req struct {
		SkillID string `json:"skillId"`
		EmpID   string `json:"empId"`
	}
	if err := jsonDecode(r, &req); err != nil {
		writeJSON(w, 400, errBody("BAD_BODY", "请求体不合法"))
		return
	}
	emps := a.employees(uid)
	if req.EmpID == "" && len(emps) > 0 {
		req.EmpID = emps[0].ID
	}
	emp, ok := get[Employee](a.db, "employee", req.EmpID)
	if !ok || emp.Owner != uid {
		writeJSON(w, 403, errBody("FORBIDDEN", "无权修改该员工"))
		return
	}
	found := false
	for _, s := range emp.Skills {
		if s == req.SkillID {
			found = true
		}
	}
	if !found {
		emp.Skills = append(emp.Skills, req.SkillID)
		_ = put(a.db, "employee", emp.ID, emp)
	}
	a.audit(uid, "skill_install", req.SkillID, "low", "success", map[string]any{"employee": emp.Name})
	writeJSON(w, 200, map[string]any{"ok": true, "employee": emp})
}

// ---------------- 会话与产物 ----------------

func (a *App) handleSessions(w http.ResponseWriter, r *http.Request, uid string) {
	empID := r.URL.Query().Get("emp")
	sid := r.URL.Query().Get("sid")
	if empID == "" {
		writeJSON(w, 200, map[string]any{"items": []Session{}})
		return
	}
	items := []Session{}
	for _, s := range list[Session](a.db, "session") {
		if s.UserID == uid && s.EmpID == empID {
			items = append(items, s)
		}
	}
	sort.Slice(items, func(i, j int) bool { return items[i].Updated > items[j].Updated })
	target := sid
	if target == "" && len(items) > 0 {
		target = items[0].ID
	}
	writeJSON(w, 200, map[string]any{"items": items, "messages": a.messages(target), "activeId": target})
}

func (a *App) handleArtifact(w http.ResponseWriter, r *http.Request, uid string) {
	rest := strings.TrimPrefix(r.URL.Path, "/api/artifact/")
	if strings.HasSuffix(rest, "/download") {
		id := strings.TrimSuffix(rest, "/download")
		art, ok := get[Artifact](a.db, "artifact", id)
		if !ok || art.File == "" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Disposition", "attachment; filename*=UTF-8''"+urlEncode(art.File))
		w.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
		http.ServeFile(w, r, a.path(art.File))
		a.audit(uid, "export", art.Title, "medium", "success", map[string]any{"artifact": art.ID})
		return
	}
	art, ok := get[Artifact](a.db, "artifact", rest)
	if !ok {
		http.NotFound(w, r)
		return
	}
	writeJSON(w, 200, art)
}

// ---------------- 管理后台 ----------------

func (a *App) handleAdmin(w http.ResponseWriter, r *http.Request, uid string) {
	audits := list[Audit](a.db, "audit")
	sort.Slice(audits, func(i, j int) bool { return audits[i].Ts > audits[j].Ts })
	if len(audits) > 100 {
		audits = audits[:100]
	}
	trend := []map[string]any{}
	denied := 0
	for _, x := range audits {
		if x.Result == "denied" {
			denied++
		}
	}
	for i := 6; i >= 0; i-- {
		d := nowTime().AddDate(0, 0, -i).Format("01-02")
		n := 0
		for _, x := range audits {
			if strings.HasPrefix(x.Ts, nowTime().AddDate(0, 0, -i).Format("2006-01-02")) {
				n++
			}
		}
		trend = append(trend, map[string]any{"date": d, "count": n})
	}
	writeJSON(w, 200, map[string]any{
		"stats": a.stats(), "denied": denied, "users": a.userList(),
		"agents": a.agentsWithCount(), "policies": list[Policy](a.db, "policy"),
		"audits": audits, "trend": trend, "docs": list[Doc](a.db, "doc"),
	})
}

func (a *App) handlePolicy(w http.ResponseWriter, r *http.Request, uid string) {
	switch r.Method {
	case http.MethodDelete:
		id := r.URL.Query().Get("id")
		_ = del(a.db, "policy", id)
		a.audit(uid, "policy_change", id, "high", "success", map[string]any{"op": "delete"})
		writeJSON(w, 200, map[string]any{"ok": true})
	default:
		var p Policy
		if err := jsonDecode(r, &p); err != nil || p.Resource == "" || p.Who == "" {
			writeJSON(w, 400, errBody("BAD_BODY", "请填写主体与资源"))
			return
		}
		if p.ID == "" {
			p.ID = newID("p")
		}
		if p.Action == "" {
			p.Action = "allow"
		}
		_ = put(a.db, "policy", p.ID, p)
		a.audit(uid, "policy_change", p.Resource, "high", "success", map[string]any{"who": p.Who, "action": p.Action})
		writeJSON(w, 200, p)
	}
}

func (a *App) handleGuardPreview(w http.ResponseWriter, r *http.Request, uid string) {
	var req struct {
		SQL string `json:"sql"`
		As  string `json:"as"`
	}
	if err := jsonDecode(r, &req); err != nil || strings.TrimSpace(req.SQL) == "" {
		writeJSON(w, 400, errBody("BAD_BODY", "请提供 SQL"))
		return
	}
	target := uid
	role := "platform_admin"
	if req.As != "" {
		target = req.As
		u, _ := get[User](a.db, "user", req.As)
		role = u.Role
	}
	writeJSON(w, 200, a.guard(target, role, req.SQL, 500))
}

func (a *App) handleAssign(w http.ResponseWriter, r *http.Request, uid string) {
	var req struct {
		AgentID string `json:"agentId"`
		UserID  string `json:"userId"`
	}
	if err := jsonDecode(r, &req); err != nil || req.AgentID == "" || req.UserID == "" {
		writeJSON(w, 400, errBody("BAD_BODY", "参数不完整"))
		return
	}
	agent, ok := get[Agent](a.db, "agent", req.AgentID)
	if !ok {
		writeJSON(w, 404, errBody("NOT_FOUND", "公共员工不存在"))
		return
	}
	for _, as := range list[Assignment](a.db, "assignment") {
		if as.AgentID == req.AgentID && as.UserID == req.UserID {
			writeJSON(w, 200, map[string]any{"created": 0, "skipped": 1})
			return
		}
	}
	u, _ := get[User](a.db, "user", req.UserID)
	emp := Employee{ID: newID("e"), Owner: req.UserID, Name: agent.Name + "（副本）", Role: agent.Role,
		Avatar: agent.Avatar, Soul: agent.Soul, Skills: agent.Skills, Memory: true, AgentID: agent.ID, Created: now()}
	_ = put(a.db, "employee", emp.ID, emp)
	_ = put(a.db, "assignment", newID("as"), Assignment{AgentID: agent.ID, UserID: req.UserID, EmpID: emp.ID})
	a.audit(uid, "agent_assign", agent.Name, "medium", "success", map[string]any{"to": u.Name, "empId": emp.ID})
	writeJSON(w, 200, map[string]any{"created": 1, "skipped": 0, "employeeId": emp.ID})
}

// ---------------- 知识 / 渠道 ----------------

func (a *App) handleKnowledge(w http.ResponseWriter, r *http.Request, _ string) {
	var req struct {
		Q string `json:"q"`
	}
	_ = jsonDecode(r, &req)
	writeJSON(w, 200, map[string]any{"items": searchDocs(a, req.Q, 5)})
}

func (a *App) handleChannelInbound(w http.ResponseWriter, r *http.Request) {
	if r.Header.Get("X-DataClaw-Token") != "demo-token" {
		writeJSON(w, 401, errBody("BAD_TOKEN", "渠道 token 不合法"))
		return
	}
	var req struct{ Text string }
	_ = jsonDecode(r, &req)
	hits := searchDocs(a, req.Text, 2)
	reply := "已收到：" + req.Text
	if len(hits) > 0 {
		reply = fmt.Sprintf("根据企业知识库《%v》：%v", hits[0]["doc"], hits[0]["snippet"])
	}
	a.audit("channel:web", "channel_inbound", "web", "low", "success", map[string]any{"text": req.Text})
	writeJSON(w, 200, map[string]any{"reply": reply, "hits": len(hits)})
}

// ---------------- 小工具 ----------------

func jsonDecode(r *http.Request, v any) error {
	return jsonDecodeReader(r, v)
}

func urlEncode(s string) string {
	const hex = "0123456789ABCDEF"
	var b strings.Builder
	for _, c := range []byte(s) {
		if (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' || c == '-' || c == '_' {
			b.WriteByte(c)
		} else {
			b.WriteByte('%')
			b.WriteByte(hex[c>>4])
			b.WriteByte(hex[c&15])
		}
	}
	return b.String()
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
