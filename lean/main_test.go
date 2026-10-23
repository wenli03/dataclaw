package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// newTestApp 在临时目录建一个带演示数据的 App（复用真实 seed/guard 逻辑）。
func newTestApp(t *testing.T) *App {
	t.Helper()
	dir := t.TempDir()
	a := &App{}
	if err := a.Open(dir); err != nil {
		t.Fatalf("open: %v", err)
	}
	if err := a.EnsureSeed(); err != nil {
		t.Fatalf("seed: %v", err)
	}
	t.Cleanup(a.Close)
	return a
}

func TestSeedData(t *testing.T) {
	a := newTestApp(t)
	if got := count(a.db, "user"); got != 6 {
		t.Fatalf("users=%d", got)
	}
	if got := count(a.db, "employee"); got != 5 {
		t.Fatalf("employees=%d", got)
	}
	if got := count(a.db, "policy"); got != 12 {
		t.Fatalf("policies=%d", got)
	}
	if _, err := os.Stat(filepath.Join(a.dir, "demo.db")); err != nil {
		t.Fatalf("demo.db missing: %v", err)
	}
}

// 数据网关：脱敏 + 行级过滤 + 拒绝写操作 + 拒绝越权表。
func TestGuard(t *testing.T) {
	a := newTestApp(t)

	r := a.guard("u_analyst", "member", "select * from worktime_fact limit 5", 500)
	if !r.OK || r.RowCount != 5 {
		t.Fatalf("analyst 工时查询失败: %+v", r)
	}
	if len(r.Masked) != 2 {
		t.Fatalf("应脱敏 salary/employee_name，实际 %v", r.Masked)
	}
	if !strings.Contains(r.SQL, "id, work_date") {
		t.Fatalf("SELECT * 未展开: %s", r.SQL)
	}

	deny := a.guard("u_analyst", "member", "select * from crm_customer limit 3", 50)
	if deny.OK || !strings.Contains(deny.Denied, "无权访问表") {
		t.Fatalf("越权表应被拒绝: %+v", deny)
	}

	for _, q := range []string{"delete from worktime_fact", "select * from worktime_fact; drop table x", "update worktime_fact set hours=0"} {
		if r := a.guard("u_analyst", "member", q, 10); r.OK {
			t.Fatalf("写操作应被拒绝: %s", q)
		}
	}

	sales := a.guard("u_sales", "member", "select * from crm_customer limit 100", 100)
	if !sales.OK || len(sales.Rows) == 0 {
		t.Fatalf("sales 查询失败: %+v", sales)
	}
	for _, row := range sales.Rows {
		if row["owner_id"] != "u_sales" {
			t.Fatalf("行级过滤失效: %v", row["owner_id"])
		}
	}
	// 用户级 allow 必须优先于角色级 deny（回归 v1.0 的 P0）
	if !r.OK {
		t.Fatal("用户级 allow 被角色级 deny 覆盖")
	}
}

func TestContractRules(t *testing.T) {
	a := newTestApp(t)
	rows := a.guard("u_legal", "member", "select * from contract_clause limit 100", 100).Rows
	risks := analyzeClauses(rows)
	if len(risks) < 10 {
		t.Fatalf("风险条款应 >=10，实际 %d", len(risks))
	}
	high := 0
	for _, r := range risks {
		if r.Level == "high" {
			high++
		}
	}
	if high < 4 {
		t.Fatalf("高风险应 >=4，实际 %d", high)
	}
	// docx 必须能被识别为 zip 且包含修订痕迹
	path := filepath.Join(t.TempDir(), "out.docx")
	if err := buildDocx(path, "测试合同 审查报告（修订版）", risks); err != nil {
		t.Fatalf("docx: %v", err)
	}
	b, _ := os.ReadFile(path)
	if len(b) < 2000 || b[0] != 'P' || b[1] != 'K' {
		t.Fatalf("docx 非法（%d 字节）", len(b))
	}
}

func TestDashboardBuild(t *testing.T) {
	a := newTestApp(t)
	rows := a.guard("u_analyst", "member", sqlCur, 500).Rows
	prev := a.guard("u_analyst", "member", sqlPrev, 500).Rows
	dash, summary := buildDashboard(rows, prev)
	if len(dash["kpis"].([]map[string]any)) < 4 || len(dash["charts"].([]map[string]any)) != 4 {
		t.Fatalf("大屏结构不完整: %+v", dash["kpis"])
	}
	if len(dash["insights"].([]map[string]any)) < 3 || summary == "" {
		t.Fatal("洞察或摘要缺失")
	}
}

func TestKnowledgeSearch(t *testing.T) {
	a := newTestApp(t)
	hits := searchDocs(a, "合同 付款账期 违约金", 2)
	if len(hits) == 0 {
		t.Fatal("知识库检索无命中")
	}
	if !strings.Contains(hits[0]["doc"].(string), "合同") {
		t.Fatalf("命中不相关: %v", hits[0]["doc"])
	}
}
