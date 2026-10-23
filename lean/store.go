package main

import (
	"database/sql"
	"encoding/json"
	"log"
	"path/filepath"
	"sort"
	"strings"

	_ "modernc.org/sqlite"
)

// App 持有两个库：app.db（应用状态，单表文档存储）与 demo.db（演示分析数据，真实表 + 真实 SQL）。
type App struct {
	db   *sql.DB // app.db
	ana  *sql.DB // demo.db
	dir  string
	user map[string]User // 内存缓存（演示规模极小）
}

// ---------------- 领域模型（JSON 直接落库，省掉 ORM 与 25 张表） ----------------

type User struct {
	ID       string `json:"id"`
	Username string `json:"username"`
	Pwd      string `json:"pwd"`
	Pass     string `json:"pass,omitempty"`
	Name     string `json:"name"`
	Role     string `json:"role"`
	Dept     string `json:"dept"`
	Title    string `json:"title"`
	Avatar   string `json:"avatar"`
}

type Employee struct {
	ID      string   `json:"id"`
	Owner   string   `json:"owner"`
	Name    string   `json:"name"`
	Role    string   `json:"role"`
	Avatar  string   `json:"avatar"`
	Soul    string   `json:"soul"`
	Memory  bool     `json:"memory"`
	AgentID string   `json:"agentId,omitempty"`
	Skills  []string `json:"skills"`
	Created string   `json:"created"`
}

type Skill struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	Desc     string `json:"desc"`
	Content  string `json:"content"`
	Category string `json:"category"`
	Risk     string `json:"risk"`
}

type Agent struct {
	ID      string   `json:"id"`
	Name    string   `json:"name"`
	Role    string   `json:"role"`
	Avatar  string   `json:"avatar"`
	Desc    string   `json:"desc"`
	Soul    string   `json:"soul"`
	Version int      `json:"version"`
	Skills  []string `json:"skills"`
}

type Template struct {
	ID     string   `json:"id"`
	Name   string   `json:"name"`
	Role   string   `json:"role"`
	Avatar string   `json:"avatar"`
	Desc   string   `json:"desc"`
	Soul   string   `json:"soul"`
	Skills []string `json:"skills"`
}

type Assignment struct {
	AgentID string `json:"agentId"`
	UserID  string `json:"userId"`
	EmpID   string `json:"empId"`
}

type Session struct {
	ID      string `json:"id"`
	EmpID   string `json:"empId"`
	UserID  string `json:"userId"`
	Title   string `json:"title"`
	Updated string `json:"updated"`
	Count   int    `json:"count"`
}

type Step struct {
	Title   string `json:"title"`
	Tool    string `json:"tool"`
	Status  string `json:"status"`
	Summary string `json:"summary"`
	Ms      int64  `json:"ms"`
	Output  any    `json:"output,omitempty"`
}

type Artifact struct {
	ID      string `json:"id"`
	Kind    string `json:"kind"` // dashboard | report | html | docx
	Title   string `json:"title"`
	Payload any    `json:"payload,omitempty"`
	File    string `json:"file,omitempty"`
}

type Message struct {
	ID        string     `json:"id"`
	SessionID string     `json:"sessionId"`
	Role      string     `json:"role"`
	Content   string     `json:"content"`
	Steps     []Step     `json:"steps,omitempty"`
	Artifacts []Artifact `json:"artifacts,omitempty"`
	Created   string     `json:"created"`
}

type Policy struct {
	ID        string `json:"id"`
	Who       string `json:"who"`      // user:u_analyst | role:member
	Resource  string `json:"resource"` // table:worktime_fact | column:worktime_fact.salary
	Action    string `json:"action"`   // allow | deny
	Mask      string `json:"mask"`     // none | mask | hash | truncate
	RowFilter string `json:"rowFilter"`
	Note      string `json:"note"`
}

type Audit struct {
	ID     string `json:"id"`
	Ts     string `json:"ts"`
	Actor  string `json:"actor"`
	Action string `json:"action"`
	Target string `json:"target"`
	Risk   string `json:"risk"`
	Result string `json:"result"`
	Detail any    `json:"detail"`
}

type Doc struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	Text string `json:"text"`
	Type string `json:"type"`
}

// ---------------- 打开 / 建库 ----------------

func (a *App) Open(dir string) error {
	a.dir = dir
	if err := ensureDir(dir); err != nil {
		return err
	}
	var err error
	a.db, err = sql.Open("sqlite", filepath.Join(dir, "app.db")+"?_pragma=journal_mode(WAL)")
	if err != nil {
		return err
	}
	if _, err := a.db.Exec(`CREATE TABLE IF NOT EXISTS store (
		kind TEXT NOT NULL, id TEXT NOT NULL, doc TEXT NOT NULL, PRIMARY KEY(kind, id))`); err != nil {
		return err
	}
	a.ana, err = sql.Open("sqlite", filepath.Join(dir, "demo.db"))
	if err != nil {
		return err
	}
	a.db.SetMaxOpenConns(1)
	a.user = map[string]User{}
	return nil
}

func (a *App) Close() {
	if a.db != nil {
		a.db.Close()
	}
	if a.ana != nil {
		a.ana.Close()
	}
}

// ---------------- 单表文档存储（kind + id + json） ----------------

func put(db *sql.DB, kind, id string, v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	_, err = db.Exec(`INSERT INTO store(kind,id,doc) VALUES(?,?,?)
		ON CONFLICT(kind,id) DO UPDATE SET doc=excluded.doc`, kind, id, string(b))
	return err
}

func del(db *sql.DB, kind, id string) error {
	_, err := db.Exec(`DELETE FROM store WHERE kind=? AND id=?`, kind, id)
	return err
}

func get[T any](db *sql.DB, kind, id string) (T, bool) {
	var t T
	var raw string
	if err := db.QueryRow(`SELECT doc FROM store WHERE kind=? AND id=?`, kind, id).Scan(&raw); err != nil {
		return t, false
	}
	if json.Unmarshal([]byte(raw), &t) != nil {
		return t, false
	}
	return t, true
}

func list[T any](db *sql.DB, kind string) []T {
	rows, err := db.Query(`SELECT doc FROM store WHERE kind=? ORDER BY id`, kind)
	if err != nil {
		return nil
	}
	defer rows.Close()
	out := []T{}
	for rows.Next() {
		var raw string
		if rows.Scan(&raw) == nil {
			var t T
			if json.Unmarshal([]byte(raw), &t) == nil {
				out = append(out, t)
			}
		}
	}
	return out
}

func count(db *sql.DB, kind string) int {
	var n int
	_ = db.QueryRow(`SELECT count(*) FROM store WHERE kind=?`, kind).Scan(&n)
	return n
}

// ---------------- 查询助手 ----------------

func (a *App) employees(owner string) []Employee {
	all := list[Employee](a.db, "employee")
	if owner == "" {
		return all
	}
	out := []Employee{}
	for _, e := range all {
		if e.Owner == owner {
			out = append(out, e)
		}
	}
	return out
}

func (a *App) userList() []User {
	us := list[User](a.db, "user")
	for i := range us {
		us[i].Pwd = ""
	}
	sort.Slice(us, func(i, j int) bool { return us[i].Username < us[j].Username })
	return us
}

func (a *App) policyFor(uid string, role string) []Policy {
	all := list[Policy](a.db, "policy")
	out := []Policy{}
	for _, p := range all {
		if p.Who == "user:"+uid || p.Who == "role:"+role {
			out = append(out, p)
		}
	}
	return out
}

func (a *App) audits() []Audit {
	as := list[Audit](a.db, "audit")
	sort.Slice(as, func(i, j int) bool { return as[i].Ts > as[j].Ts })
	if len(as) > 300 {
		as = as[:300]
	}
	return as
}

func (a *App) messages(sid string) []Message {
	ms := list[Message](a.db, "message")
	out := []Message{}
	for _, m := range ms {
		if m.SessionID == sid {
			out = append(out, m)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Created < out[j].Created })
	return out
}

// kvStore 用 kind 做前缀索引即可；演示规模（<1000 行）无需复杂查询。
func (a *App) kinds() []string { return []string{"user", "employee", "skill", "agent", "template", "assignment", "session", "message", "artifact", "policy", "audit", "doc"} }

func (a *App) stats() map[string]int {
	return map[string]int{
		"employees": count(a.db, "employee"), "sessions": count(a.db, "session"),
		"messages": count(a.db, "message"), "skills": count(a.db, "skill"),
		"agents": count(a.db, "agent"), "policies": count(a.db, "policy"),
		"audits": count(a.db, "audit"), "docs": count(a.db, "doc"),
		"users": count(a.db, "user"), "artifacts": count(a.db, "artifact"),
	}
}

func (a *App) deniedCount() int {
	n := 0
	for _, x := range list[Audit](a.db, "audit") {
		if x.Result == "denied" {
			n++
		}
	}
	return n
}

func sqliteErrCode(err error) string {
	if err == nil {
		return ""
	}
	s := err.Error()
	if strings.Contains(s, "no such table") {
		return "NO_TABLE"
	}
	if strings.Contains(s, "no such column") {
		return "NO_COLUMN"
	}
	return "SQL_ERROR"
}

func logf(f string, args ...any) { log.Printf(f, args...) }
